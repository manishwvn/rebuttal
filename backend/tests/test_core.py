import os

import pytest

from rebuttal.agent.facts import gather
from rebuttal.agent.reasoner import Decision, guard
from rebuttal.approval import ApprovalError
from rebuttal.config import load_settings
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW


@pytest.fixture
def rt():
    return Runtime(seed_cases=["agent_wrong_size", "inr_no_tracking", "inr_delivered_claim"], force_rules=True)


def test_refuses_live_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("PAYPAL_ENV", "live")
    with pytest.raises(RuntimeError, match="sandbox"):
        load_settings(env_file=tmp_path / "missing.env")
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")


def test_analyze_never_writes_to_paypal(rt):
    for d in rt.client.list_disputes():
        rt.analyze(d["dispute_id"])
    assert rt.mock.write_calls() == []


def test_approval_executes_offer(rt):
    p = rt.analyze("PP-D-2000")
    assert p.decision.resolution == "OFFER_RETURN_FOR_REFUND"  # PayPal allows no replacement offer here
    rt.approvals.approve(p.id, edited_message="Edited by merchant")
    d = rt.mock.disputes["PP-D-2000"]
    assert d["offer"]["offer_type"] == "REFUND_WITH_RETURN"
    assert d["offer"]["seller_offered_amount"] == {"currency_code": "USD", "value": "48.00"}
    assert d["messages"][-1] == {**d["messages"][-1], "posted_by": "SELLER", "content": "Edited by merchant"}
    with pytest.raises(ApprovalError):
        rt.approvals.approve(p.id)  # cannot execute twice


def test_agent_purchase_mismatch_detected(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["is_agent_purchase"] is True
    assert case.facts["agent_followed_instruction"] is False


def test_guard_blocks_unsupported_model_choice(rt):
    case = gather("PP-D-2001", rt.client, rt.store, DEMO_NOW)  # no tracking
    bad = Decision("SHARE_TRACKING", 0.99, ["made up"], "", "msg", "", source="claude")
    fixed = guard(bad, case)
    assert fixed.resolution == "ACCEPT_CLAIM"
    assert any("no tracking" in n for n in fixed.guard_notes)


def test_guard_converts_tracking_message_in_claim_stage(rt):
    case = gather("PP-D-2002", rt.client, rt.store, DEMO_NOW)
    d = guard(Decision("SHARE_TRACKING", 0.8, [], "", "msg", "", source="claude"), case)
    assert d.resolution == "SUBMIT_EVIDENCE"


def test_evidence_submission_attaches_pdf(rt):
    p = rt.analyze("PP-D-2002")
    assert p.evidence_pdf and p.evidence_pdf.startswith(b"%PDF")
    rt.approvals.approve(p.id)
    assert rt.mock.evidence_files["PP-D-2002"] == ["evidence-PP-D-2002.pdf"]


class _FakeMessages:
    def __init__(self, text):
        self.text = text

    def create(self, **kw):
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("R", (), {"content": [block]})()


def test_claude_reasoner_parses_and_is_guarded(rt):
    from rebuttal.agent.reasoner import ClaudeReasoner

    r = ClaudeReasoner.__new__(ClaudeReasoner)
    r._model, r._fallback = "test", __import__("rebuttal.agent.reasoner", fromlist=["RuleReasoner"]).RuleReasoner()
    r._client = type("C", (), {"messages": _FakeMessages(
        'Sure: {"buyer_wants": "a medium", "resolution": "OFFER_REPLACEMENT", "partial_refund_pct": null,'
        ' "confidence": 0.9, "reasoning": ["assistant picked L"], "message_to_buyer": "Hi", "evidence_summary": ""}')})()
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    d = guard(r.decide(case), case)
    # The model chose a replacement; PayPal allows only refund offers on this dispute, so guard converts it.
    assert (d.resolution, d.source, d.buyer_wants) == ("OFFER_RETURN_FOR_REFUND", "claude", "a medium")
    assert any("allowed_response_options" in n for n in d.guard_notes)

    r._client = type("C", (), {"messages": _FakeMessages("not json")})()
    d2 = r.decide(case)
    assert d2.source == "rules" and "failed" in d2.guard_notes[0]


def test_missing_due_date_is_tolerated(rt):
    del rt.mock.disputes["PP-D-2000"]["seller_response_due_date"]
    p = rt.analyze("PP-D-2000")
    assert p.case_summary["due"] is None and p.case_summary["hours_left"] is None


def test_trackers_come_from_the_order(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert [t["tracking_number"] for t in case.trackers] == [case.order.shipment.number]
    assert case.facts["tracking_uploaded_to_paypal"] is True
    assert not any("/v1/shipping/trackers" in c for _, c in rt.mock.calls)


def test_transaction_search_403_is_not_fatal():
    from rebuttal.paypal.client import PayPalError

    rt = Runtime(seed_cases=["duplicate_true"], force_rules=True)

    def forbidden(*a, **kw):
        raise PayPalError(403, {"name": "NOT_AUTHORIZED"})

    rt.client.search_transactions = forbidden
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["transaction_search_available"] is False
    assert "duplicate_charge_found" not in case.facts
    assert any("403, skipped" in c for c in case.tool_calls)
    p = rt.analyze("PP-D-2000")  # must not claim "only one charge" without having looked
    assert p.decision.confidence < 0.5


def test_mock_rejects_seller_actions_while_under_review(rt):
    from rebuttal.paypal.client import PayPalError

    rt.mock.disputes["PP-D-2000"]["status"] = "UNDER_REVIEW"
    with pytest.raises(PayPalError) as err:
        rt.client.send_message("PP-D-2000", "hi")
    assert err.value.status == 422 and "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE" in str(err.value)


def test_spike_retry_status_only(rt, capsys, monkeypatch):
    from scripts import spike_retry

    monkeypatch.setattr(spike_retry, "load_settings", lambda: type("S", (), {
        "client_id": "x", "client_secret": "y", "base_url": "https://mock.invalid"})())
    monkeypatch.setattr(spike_retry, "PayPalClient", lambda *a, **kw: rt.client)
    assert spike_retry.main(["PP-D-2000", "--status-only"]) == 0
    assert '"status": "WAITING_FOR_SELLER_RESPONSE"' in capsys.readouterr().out
    assert rt.mock.write_calls() == []


def test_every_proposal_is_a_single_paypal_call():
    from rebuttal.scenarios import load_cases

    ids = [c["id"] for c in load_cases()]
    rt = Runtime(seed_cases=ids, force_rules=True)
    for d in rt.client.list_disputes():
        p = rt.analyze(d["dispute_id"])
        assert len(p.actions) == 1, (d["dispute_id"], [a.kind for a in p.actions])
        if p.actions[0].kind == "make_offer":
            assert p.actions[0].params["note"]  # the explanation lives in the offer note


def test_guard_only_proposes_what_paypal_allows(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.allowed_response_options["make_offer"]["offer_types"] == ["REFUND", "REFUND_WITH_RETURN"]
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "We will replace it", "", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"
    assert "ship the right one as soon as the return is scanned" in d.message_to_buyer

    case.allowed_response_options = {"make_offer": {"offer_types": []}, "accept_claim": {"accept_claim_types": []}}
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_REPLACEMENT" and d.confidence <= 0.3  # nothing allowed: flag, don't invent

    case.allowed_response_options = None  # PayPal gave no list: no restriction
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_REPLACEMENT"


def test_mock_rejects_offer_types_paypal_does_not_allow(rt):
    from rebuttal.paypal.client import PayPalError

    with pytest.raises(PayPalError) as err:
        rt.client.make_offer("PP-D-2000", note="x", offer_type="REPLACEMENT_WITHOUT_REFUND")
    assert err.value.status == 400 and "INVALID_OFFER_TYPE" in str(err.value)
    assert rt.mock.disputes["PP-D-2000"]["status"] == "WAITING_FOR_SELLER_RESPONSE"


class _FakeChat:
    def __init__(self, content, reasoning_content=None, fail=False):
        self.content, self.reasoning_content, self.fail, self.kwargs = content, reasoning_content, fail, None

    def create(self, **kw):
        self.kwargs = kw
        if self.fail:
            raise RuntimeError("429 rate limited")
        msg = type("M", (), {"content": self.content, "reasoning_content": self.reasoning_content})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()


def _nvidia(chat):
    from rebuttal.agent.reasoner import NvidiaReasoner

    client = type("C", (), {"chat": type("Ch", (), {"completions": chat})()})()
    return NvidiaReasoner("unused", "deepseek-ai/deepseek-v4.1-flash", client=client)


_ANSWER = ('{"buyer_wants": "a medium", "resolution": "OFFER_RETURN_FOR_REFUND", "partial_refund_pct": null, '
           '"confidence": 0.9, "reasoning": ["assistant picked L"], "message_to_buyer": "Hi", "evidence_summary": ""}')


def test_nvidia_reasoner_skips_thinking_before_json(rt):
    thinking = ('<think>The buyer wants {"resolution": "SHARE_TRACKING"}? No. Let me reconsider the facts.</think>\n'
                'Okay, my analysis: sizes differ {not json}.\n')
    chat = _FakeChat(thinking + _ANSWER, reasoning_content='{"resolution": "ACCEPT_CLAIM"} scratch work')
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    d = _nvidia(chat).decide(case)
    assert (d.resolution, d.source, d.buyer_wants) == ("OFFER_RETURN_FOR_REFUND", "nvidia", "a medium")
    assert chat.kwargs["model"] == "deepseek-ai/deepseek-v4.1-flash"
    assert chat.kwargs["temperature"] == 0.2 and chat.kwargs["max_tokens"] == 4096


def test_nvidia_reasoner_falls_back_to_rules(rt):
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    d = _nvidia(_FakeChat("I could not decide.")).decide(case)
    assert d.source == "rules" and "failed" in d.guard_notes[0]
    d = _nvidia(_FakeChat("", fail=True)).decide(case)
    assert d.source == "rules" and "RuntimeError" in d.guard_notes[0]


def test_runtime_prefers_anthropic_groq_nvidia_then_rules(monkeypatch):
    from rebuttal.config import Settings

    base = load_settings()
    mk = lambda **kw: Runtime(settings=Settings(**{**base.__dict__, "mock": True, **kw}), seed_cases=[])  # noqa: E731
    assert mk(anthropic_api_key="a", groq_api_key="g").reasoner.name == "claude"
    assert mk(anthropic_api_key=None, groq_api_key="g", nvidia_api_key="n").mode == "mock / groq"
    assert mk(anthropic_api_key=None, groq_api_key=None, nvidia_api_key="n").mode == "mock / nvidia"
    assert mk(anthropic_api_key=None, groq_api_key=None, nvidia_api_key=None).reasoner.name == "rules"


def test_groq_reasoner_hides_reasoning_and_stays_in_budget(rt):
    from rebuttal.agent.reasoner import GroqReasoner, TokenBudget

    chat = _FakeChat("<think>hmm {\"resolution\": \"ACCEPT_CLAIM\"}</think>" + _ANSWER)
    chat.create_orig = chat.create
    client = type("C", (), {"chat": type("Ch", (), {"completions": chat})()})()
    r = GroqReasoner("unused", "qwen/qwen3.8-27b", client=client)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    d = r.decide(case)
    assert (d.resolution, d.source) == ("OFFER_RETURN_FOR_REFUND", "groq")
    assert chat.kwargs["extra_body"] == {"reasoning_format": "hidden"} and chat.kwargs["max_tokens"] == 500


def test_token_budget_waits_for_the_window():
    from rebuttal.agent.reasoner import TokenBudget

    now, slept = [0.0], []
    b = TokenBudget(tpm=8000, rpm=30, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    b.wait(5000); b.record(5000)
    b.wait(5000)  # 5000 + 5000 > 8000: must wait out the first call's 60s window
    assert slept and now[0] >= 60


def test_token_budget_limits_reserved_output_tokens():
    from rebuttal.agent.reasoner import TokenBudget

    now = [0.0]
    b = TokenBudget(tpm=8000, rpm=30, otpm=1000, clock=lambda: now[0],
                    sleep=lambda s: now.__setitem__(0, now[0] + s))
    for _ in range(2):
        b.wait(1500, 500); b.record(900, 500)
    t = now[0]
    b.wait(1500, 500)  # a third 500-token reservation would exceed 1,000/min
    assert now[0] - t >= 59


def _case_facts(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return rt, gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def test_likely_lost_and_refund_without_return_facts():
    _, stuck = _case_facts("hard_stuck_wants_refund")
    assert stuck.facts["likely_lost"] is True and stuck.facts["buyer_asks_for_refund"] is True
    _, cheap = _case_facts("snad_damaged_low_value")
    assert cheap.facts["refund_without_return_eligible"] is True and cheap.facts["likely_lost"] is False
    _, pricey = _case_facts("snad_damaged_high_value")
    assert pricey.facts["refund_without_return_eligible"] is False
    _, moving = _case_facts("inr_in_transit")
    assert moving.facts["likely_lost"] is False


def test_guard_refunds_a_likely_lost_package_when_buyer_wants_money_back():
    _, case = _case_facts("hard_stuck_wants_refund")
    d = guard(Decision("SHARE_TRACKING", 0.95, [], "", "Here is your tracking", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and any("likely lost" in n for n in d.guard_notes)
    _, moving = _case_facts("inr_in_transit")
    assert guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), moving).resolution == "SHARE_TRACKING"


def test_guard_refunds_when_delivery_cannot_be_proven():
    _, case = _case_facts("inr_no_tracking")
    assert case.facts["cannot_prove_delivery"] is True
    d = guard(Decision("SUBMIT_EVIDENCE", 0.95, [], "", "m", "evidence", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and any("can't be proven" in n for n in d.guard_notes)
    _, shipped = _case_facts("inr_delivered")
    assert shipped.facts["cannot_prove_delivery"] is False


def test_assistant_misordered_fact_and_guard():
    rt, case = _case_facts("agent_wrong_size")
    assert case.facts["assistant_misordered"] is True
    d = guard(Decision("SUBMIT_EVIDENCE", 0.95, [], "", "m", "evidence", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"  # replacement is converted: PayPal allows refund offers only
    assert any("assistant ordered a different variant" in n for n in d.guard_notes)
    assert "ship the right one as soon as the return is scanned" in d.message_to_buyer
    _, right = _case_facts("hard_agent_right_size")
    assert right.facts["assistant_misordered"] is False
    assert guard(Decision("SUBMIT_EVIDENCE", 0.9, [], "", "m", "e", source="claude"), right).resolution == "SUBMIT_EVIDENCE"
    _, plain = _case_facts("inr_delivered")
    assert plain.facts["assistant_misordered"] is False
