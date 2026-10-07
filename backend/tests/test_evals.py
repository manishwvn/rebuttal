"""evals/run.py: the --langfuse branch, with Langfuse faked (backend/.env holds real keys; the suite must not use them)."""

import json

import pytest
from langchain_core.runnables import RunnableLambda

from evals import run as evals_run
from rebuttal import tracing
from rebuttal.scenarios import load_cases

LABELS = ("expected", "why", "hard")


@pytest.fixture
def fake_langfuse(monkeypatch, tmp_path):
    seen = {"traced": []}
    monkeypatch.setattr(evals_run, "HERE", tmp_path)  # never overwrite the committed results files
    monkeypatch.setattr(tracing, "langfuse_configured", lambda: True)
    monkeypatch.setattr(tracing, "trace_config", lambda **kw: seen["traced"].append(kw) or {})
    monkeypatch.setattr(tracing, "flush", lambda: seen.setdefault("flushed", True))

    def upload_dataset(cases, name=tracing.DATASET_NAME):
        seen["uploaded"] = [c["id"] for c in cases]
        return name

    def run_experiment(*, name, task, **kw):
        seen["experiment"] = {"name": name, **kw}
        # What the SDK does: hand each dataset item's input (the case without its labels) to the task.
        seen["outputs"] = [task({k: v for k, v in c.items() if k not in LABELS}) for c in load_cases()]
        return type("Result", (), {"dataset_run_url": "https://langfuse.example/run/1"})()

    monkeypatch.setattr(tracing, "upload_dataset", upload_dataset)
    monkeypatch.setattr(tracing, "run_experiment", run_experiment)
    return seen


def test_langfuse_run_uploads_the_dataset_and_runs_every_case_traced(fake_langfuse, tmp_path):
    summary = evals_run.run(force_rules=True, langfuse=True)
    assert fake_langfuse["uploaded"] == [c["id"] for c in load_cases()]
    assert fake_langfuse["experiment"]["name"].startswith("rules-rules-baseline-")
    assert len(summary["rows"]) == len(fake_langfuse["outputs"]) == 20 and fake_langfuse["flushed"]
    assert {o["resolution"] for o in fake_langfuse["outputs"]} >= {"SHARE_TRACKING", "ACCEPT_CLAIM"}
    assert len(fake_langfuse["traced"]) == 20  # tracing was on for each case...
    assert all(k["provider"] == "rules" for k in fake_langfuse["traced"])
    assert summary["langfuse"] == {"name": fake_langfuse["experiment"]["name"], "dataset": tracing.DATASET_NAME,
                                   "url": "https://langfuse.example/run/1"}
    assert json.loads(next((tmp_path / "results").glob("*.json")).read_text())["cases"] == 20
    assert summary["approval_gate_violations"] == 0


def test_a_plain_run_never_touches_langfuse(fake_langfuse):
    summary = evals_run.run(force_rules=True, only={"agent_wrong_size", "inr_no_tracking"})
    assert [r["id"] for r in summary["rows"]] == ["agent_wrong_size", "inr_no_tracking"]
    assert fake_langfuse["traced"] == [] and "uploaded" not in fake_langfuse and summary["langfuse"] is None


def test_langfuse_flag_needs_keys_and_the_whole_dataset(fake_langfuse, monkeypatch):
    with pytest.raises(SystemExit, match="drop --only"):
        evals_run.run(force_rules=True, langfuse=True, only={"agent_wrong_size"})
    monkeypatch.setattr(tracing, "langfuse_configured", lambda: False)
    with pytest.raises(SystemExit, match="LANGFUSE_PUBLIC_KEY"):
        evals_run.run(force_rules=True, langfuse=True)


def test_a_rate_limited_model_makes_the_eval_invalid_and_writes_nothing(monkeypatch, tmp_path):
    import json

    from evals import run as ev
    from rebuttal.agent import llm

    def limited(messages, config=None):
        raise RuntimeError("429 rate_limit_exceeded")

    def fake_build(settings, **kw):
        r = llm.ModelReasoner(name="fake", model_name="m", structured=RunnableLambda(limited), strict=kw.get("strict", False))
        return r

    monkeypatch.setattr("rebuttal.runtime.build_reasoner", fake_build)
    monkeypatch.setattr(ev, "HERE", tmp_path)
    monkeypatch.setenv("REBUTTAL_REASONER", "auto")
    with pytest.raises(ev.InvalidRun, match="rate or quota limit on case"):
        ev.run(force_rules=False, only={"agent_wrong_size", "snad_damaged_high_value"})
    assert not list(tmp_path.iterdir())


def test_a_run_records_the_models_raw_choice_next_to_the_final_action(monkeypatch, tmp_path):
    """`raw` is the choice before guard(); `guard_changed` and the summary counts follow from it."""
    from evals import run as ev
    from rebuttal.agent import llm
    from rebuttal.agent.reasoner import Decision

    class Insists:  # always a replacement: the guard must turn it into something PayPal allows on this dispute
        name, model_name, tokens_used, strict = "fake", "fake-model", 0, True

        def decide(self, case, config=None):
            return Decision("OFFER_REPLACEMENT", 0.9, ["x"], "wants", "We will replace it", "", source="fake")

    monkeypatch.setattr("rebuttal.runtime.build_reasoner", lambda settings, **kw: Insists())
    monkeypatch.setattr(ev, "HERE", tmp_path)
    monkeypatch.setenv("REBUTTAL_REASONER", "auto")
    summary = ev.run(force_rules=False, only={"agent_wrong_size", "snad_changed_mind"})
    rows = {r["id"]: r for r in summary["rows"]}
    wrong = rows["agent_wrong_size"]  # PayPal allows only refund offers here
    assert wrong["raw"] == "OFFER_REPLACEMENT" and wrong["got"] == "OFFER_RETURN_FOR_REFUND"
    assert wrong["guard_changed"] is True and wrong["correct"] is True and wrong["raw_correct"] is False
    assert summary["guard_changes"] >= 1 and summary["raw_accuracy"] < summary["accuracy"]
    assert summary["set"] == "main"


def test_results_md_separates_model_alone_from_final_and_the_held_out_set(tmp_path, monkeypatch):
    from evals import run as ev

    monkeypatch.setattr(ev, "HERE", tmp_path)
    (tmp_path / "results").mkdir()

    def row(cid, raw, got, expected="ACCEPT_CLAIM"):
        r = {"id": cid, "title": cid, "hard": False, "expected": expected, "got": got, "correct": got == expected,
             "confidence": 0.9, "source": "x", "provider": "p", "model": "m"}
        if raw:
            r.update(raw=raw, raw_correct=raw == expected, guard_changed=raw != got)
        return r

    def run_file(name, rows, set_name=None, raw_accuracy=None, changes=0):
        d = {"mode": "m", "cases": len(rows), "accuracy": sum(r["correct"] for r in rows) / len(rows),
             "standard_accuracy": 1.0, "hard_accuracy": None, "hard_cases": 0, "approval_gate_violations": 0,
             "rows": rows, "tokens_used": 1, "langfuse": None, "provider": "p", "model": "m", "date": "2026-10-07"}
        if set_name:
            d["set"] = set_name
        if raw_accuracy is not None:
            d.update(raw_accuracy=raw_accuracy, guard_changes=changes)
        (tmp_path / "results" / name).write_text(json.dumps(d))

    run_file("old.json", [row("a", None, "ACCEPT_CLAIM")])  # an older run: no raw choice
    run_file("new.json", [row("a", "OFFER_REPLACEMENT", "ACCEPT_CLAIM")], raw_accuracy=0.0, changes=1)
    run_file("ho.json", [row("ho_a", "ACCEPT_CLAIM", "ACCEPT_CLAIM")], set_name="holdout", raw_accuracy=1.0)
    ev.write_results_md()
    text = (tmp_path / "RESULTS.md").read_text()
    main, held = text.split("## Held-out (not used for tuning)")
    assert "final only" in main and "1/1 (100%)" in main  # the old run is marked, the new one counts guard changes
    assert "yes (model: OFFER_REPLACEMENT)" in main
    assert "ho_a" in held and "ho_a" not in main


def test_the_held_out_set_loads_seeds_and_runs_offline():
    """Schema check only (rules baseline, no model): every held-out case seeds into the mock and is analysed."""
    from evals import run as ev
    from rebuttal.scenarios import load_cases

    cases = load_cases(ev.SETS["holdout"])
    assert len(cases) == 10 and len({c["id"] for c in cases}) == 10
    assert not {c["id"] for c in cases} & {c["id"] for c in load_cases(ev.SETS["main"])}  # item ids stay unique
    settings = ev.eval_settings()
    for case in cases:
        row, _, _ = ev.run_case(case, settings, force_rules=True)
        assert row["writes_before_approval"] == 0 and row["raw"] and row["got"]


def test_save_run_names_the_held_out_set_separately(tmp_path, monkeypatch):
    from evals import run as ev

    monkeypatch.setattr(ev, "HERE", tmp_path)
    base = {"provider": "groq", "model": "qwen/qwen3.8-27b", "date": "2026-10-07"}
    assert ev.save_run({**base, "set": "main"}).name == "groq-qwen3.8-27b-20261007.json"
    assert ev.save_run({**base, "set": "holdout"}).name == "groq-qwen3.8-27b-holdout-20261007.json"
