"""evals/run.py: the --langfuse branch, with Langfuse faked (backend/.env holds real keys; the suite must not use them)."""

import json

import pytest

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
    assert json.loads((tmp_path / "results.json").read_text())["cases"] == 20
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
