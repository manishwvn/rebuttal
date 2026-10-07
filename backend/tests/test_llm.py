"""The model-backed `decide` step: schema-validated output, fallback to rules, provider choice, Groq pacing."""

import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from rebuttal.agent.facts import gather
from rebuttal.agent.llm import DecisionOut, ModelReasoner, TokenBudget, build_reasoner
from rebuttal.agent.reasoner import RESOLUTIONS, SYSTEM_PROMPT, guard
from rebuttal.config import Settings, load_settings
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW

ANSWER = {"buyer_wants": "a medium", "resolution": "OFFER_REPLACEMENT", "partial_refund_pct": None,
          "confidence": 0.9, "reasoning": ["assistant picked L"], "message_to_buyer": "Hi", "evidence_summary": ""}


@pytest.fixture
def case():
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def reasoner(fn, **kw):
    """A ModelReasoner whose structured-output runnable is `fn(messages) -> {"raw", "parsed", "parsing_error"}`."""
    return ModelReasoner(name="fake", model_name="fake-model", structured=RunnableLambda(fn), **kw)


def parsed_result(tokens=1400, **overrides):
    out = DecisionOut(**{**ANSWER, **overrides})
    raw = AIMessage(content="", usage_metadata={"input_tokens": tokens - 300, "output_tokens": 300,
                                                "total_tokens": tokens})
    return {"raw": raw, "parsed": out, "parsing_error": None}


def test_decision_comes_from_the_schema_and_the_guard_still_applies(case):
    seen = []

    def fn(messages):
        seen.append(messages)
        return parsed_result()

    r = reasoner(fn)
    d = r.decide(case)
    assert (d.resolution, d.source, d.buyer_wants, d.confidence) == ("OFFER_REPLACEMENT", "fake", "a medium", 0.9)
    assert r.tokens_used == 1400
    system, user = seen[0]
    assert system.content == SYSTEM_PROMPT
    payload = json.loads(user.content)
    assert payload["facts"]["assistant_misordered"] is True
    # PayPal allows only refund offers on this dispute, so the model is not even offered a replacement.
    assert "OFFER_REPLACEMENT" not in payload["allowed_resolutions"]
    assert "OFFER_RETURN_FOR_REFUND" in payload["allowed_resolutions"]
    guarded = guard(d, case)
    assert guarded.resolution == "OFFER_RETURN_FOR_REFUND"
    assert any("allowed_response_options" in n for n in guarded.guard_notes)


def test_json_inside_thinking_text_is_extracted_and_validated(case):
    thinking = ('<think>The buyer wants {"resolution": "SHARE_TRACKING"}? No. Let me reconsider.</think>\n'
                'Okay, my analysis: sizes differ {not json}.\n')
    text = thinking + json.dumps({**ANSWER, "resolution": "OFFER_RETURN_FOR_REFUND"})
    d = reasoner(lambda m: {"raw": AIMessage(content=text), "parsed": None, "parsing_error": ValueError("x")}).decide(case)
    assert (d.resolution, d.source) == ("OFFER_RETURN_FOR_REFUND", "fake")


@pytest.mark.parametrize("bad", [
    {"raw": AIMessage(content="I could not decide."), "parsed": None, "parsing_error": ValueError("no tool call")},
    {"raw": AIMessage(content=json.dumps({**ANSWER, "resolution": "REFUND_EVERYTHING"})), "parsed": None,
     "parsing_error": None},
])
def test_unusable_output_falls_back_to_rules_and_says_so(case, bad):
    d = reasoner(lambda m: bad).decide(case)
    assert d.source == "rules" and d.guard_notes[0].startswith("Model call failed")


def test_provider_error_falls_back_to_rules(case):
    def boom(messages):
        raise RuntimeError("429 rate limited")

    d = reasoner(boom).decide(case)
    assert d.source == "rules" and "RuntimeError" in d.guard_notes[0] and "429" in d.guard_notes[0]


def test_schema_rejects_unknown_resolutions_and_clamps_numbers():
    with pytest.raises(ValidationError):
        DecisionOut(**{**ANSWER, "resolution": "REFUND_EVERYTHING"})
    out = DecisionOut(**{**ANSWER, "confidence": 1.7, "partial_refund_pct": 90,
                         "reasoning": [f"r{i}" for i in range(9)]})
    assert (out.confidence, out.partial_refund_pct, len(out.reasoning)) == (1.0, 50, 5)
    assert DecisionOut(**{**ANSWER, "confidence": -1, "partial_refund_pct": 1}).partial_refund_pct == 5
    assert set(DecisionOut.model_json_schema()["properties"]["resolution"]["enum"]) == set(RESOLUTIONS)


def test_token_usage_falls_back_to_response_metadata(case):
    raw = AIMessage(content="", response_metadata={"token_usage": {"total_tokens": 777}})
    r = reasoner(lambda m: {**parsed_result(), "raw": raw})
    r.decide(case)
    assert r.tokens_used == 777


def test_throttle_is_reserved_before_and_settled_after_each_call(case):
    calls = []

    class Reservation:
        def settle(self, tokens):
            calls.append(("settle", tokens))

    class Budget:
        def reserve(self, estimate, output=0):
            calls.append(("reserve", output))
            return Reservation()

    reasoner(lambda m: parsed_result(1234), throttle=Budget(), max_output_tokens=500).decide(case)
    assert calls == [("reserve", 500), ("settle", 1234)]


def settings(**kw):
    return Settings(**{**load_settings().__dict__, "mock": True, "reasoner": "auto", "anthropic_api_key": None,
                       "groq_api_key": None, "nvidia_api_key": None, **kw})


def test_providers_are_picked_in_order_anthropic_groq_nvidia_rules():
    both = settings(anthropic_api_key="a", groq_api_key="g", nvidia_api_key="n")
    assert build_reasoner(both).name == "claude"
    assert build_reasoner(settings(groq_api_key="g", nvidia_api_key="n")).name == "groq"
    assert build_reasoner(settings(nvidia_api_key="n")).name == "nvidia"
    assert build_reasoner(settings()) is None
    assert Runtime(settings=settings(groq_api_key="g"), seed_cases=[]).mode == "mock / groq"
    assert Runtime(settings=settings(nvidia_api_key="n"), seed_cases=[]).mode == "mock / nvidia"
    assert Runtime(settings=settings(), seed_cases=[]).reasoner.name == "rules"
    assert Runtime(settings=both, seed_cases=[], force_rules=True).reasoner.name == "rules"
    assert Runtime(settings=settings(groq_api_key="g", reasoner="rules"), seed_cases=[]).reasoner.name == "rules"


def test_chat_models_are_configured_for_repeatable_decisions():
    claude = build_reasoner(settings(anthropic_api_key="a"))
    assert claude.chat_model.temperature == 0 and claude.model_name == "claude-sonnet-5-5"
    groq = build_reasoner(settings(groq_api_key="g", groq_model="qwen/qwen3.8-27b"))
    assert groq.chat_model.temperature < 1e-6  # LangChain sends 1e-8 to Groq, which rejects exactly 0
    assert (groq.chat_model.reasoning_format, groq.chat_model.max_tokens) == ("hidden", 500)
    assert groq.chat_model.model_name == "qwen/qwen3.8-27b"
    nvidia = build_reasoner(settings(nvidia_api_key="n", nvidia_model="deepseek-ai/deepseek-v4.1-flash"))
    assert nvidia.chat_model.temperature == 0 and nvidia.chat_model.max_tokens == 4096
    assert "integrate.api.nvidia.com" in str(nvidia.chat_model.openai_api_base)
    assert nvidia.chat_model.model_name == "deepseek-ai/deepseek-v4.1-flash"


def test_groq_calls_share_one_budget_across_reasoners():
    a = build_reasoner(settings(groq_api_key="g"))
    b = build_reasoner(settings(groq_api_key="g"))
    assert a._throttle is b._throttle and (a._throttle.tpm, a._throttle.rpm, a._throttle.otpm) == (8000, 30, 1000)


def fake_clock():
    now = [0.0]
    return now, (lambda: now[0]), (lambda secs: now.__setitem__(0, now[0] + secs))


def test_token_budget_waits_for_the_window():
    now, clock, sleep = fake_clock()
    b = TokenBudget(tpm=8000, rpm=30, clock=clock, sleep=sleep)
    b.reserve(5000).settle(5000)
    b.reserve(5000)  # 5000 + 5000 > 8000: must wait out the first call's 60s window
    assert now[0] >= 60


def test_token_budget_limits_reserved_output_tokens():
    now, clock, sleep = fake_clock()
    b = TokenBudget(tpm=8000, rpm=30, otpm=1000, clock=clock, sleep=sleep)
    for _ in range(2):
        b.reserve(1500, 500).settle(900)
    t = now[0]
    b.reserve(1500, 500)  # a third 500-token reservation would exceed 1,000/min
    assert now[0] - t >= 59


def test_token_budget_books_capacity_at_reserve_time_and_is_thread_safe():
    """Two threads asking at once must not both see an empty window: the second waits for the first's slot."""
    import threading
    import time

    b = TokenBudget(tpm=1000, rpm=30, otpm=None, sleep=lambda secs: time.sleep(0.01))
    first = b.reserve(900)  # in flight, not settled yet
    order = []
    waiter = threading.Thread(target=lambda: (b.reserve(900), order.append("second")))
    waiter.start()
    time.sleep(0.05)
    assert order == []  # blocked: 900 + 900 > 1000 although the first call has not finished
    b._events[0][0] -= 61  # the first call ages out of the 60s window
    waiter.join(timeout=2)
    assert order == ["second"] and first is not None


def test_strict_reasoner_raises_instead_of_using_the_rules(case):
    from rebuttal.agent.llm import ModelCallFailed

    def limited(messages):
        raise RuntimeError("Error code: 429 - rate_limit_exceeded")

    with pytest.raises(ModelCallFailed) as err:
        reasoner(limited, strict=True).decide(case)
    assert err.value.rate_limited

    def broken(messages):
        raise ValueError("bad json")

    with pytest.raises(ModelCallFailed) as err:
        reasoner(broken, strict=True).decide(case)
    assert not err.value.rate_limited


def test_provider_can_be_pinned_and_needs_its_key():
    both = settings(groq_api_key="g", nvidia_api_key="n")
    assert build_reasoner(both, provider="nvidia").name == "nvidia"
    assert build_reasoner(settings(groq_api_key="g", nvidia_api_key="n", provider="nvidia")).name == "nvidia"
    with pytest.raises(ValueError, match="needs its API key"):
        build_reasoner(settings(groq_api_key="g"), provider="nvidia")
    with pytest.raises(ValueError, match="unknown provider"):
        build_reasoner(both, provider="openai")
    assert build_reasoner(both, strict=True).strict
