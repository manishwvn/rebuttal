"""evals/holdout2.json, the second held-out set. Schema and seeding checks only: no model is called and no analysis
runs (the labels are for a later, deliberate eval run, and nothing here may be tuned against them)."""

from langgraph.checkpoint.memory import InMemorySaver

from evals import run as ev
from rebuttal.runtime import Runtime
from rebuttal.scenarios import load_cases, seed_case

REQUIRED = {"id", "title", "reason", "stage", "days_since_purchase", "days_open", "buyer_message", "item", "ship_to",
            "shipment", "expected", "hard", "why"}


def _sets():
    return (load_cases(ev.SETS["holdout2"]), load_cases(ev.SETS["main"]), load_cases(ev.SETS["holdout"]))


def test_the_runner_knows_the_second_held_out_set():
    assert ev.SETS["holdout2"].name == "holdout2.json" and ev.SETS["holdout2"].exists()
    assert ev.DATASETS["holdout2"] and ev.DATASETS["holdout2"] != ev.DATASETS["holdout"]


def test_holdout2_ids_are_unique_and_do_not_collide_with_other_sets():
    cases, main, holdout = _sets()
    ids = [c["id"] for c in cases]
    assert len(ids) == 10 and len(set(ids)) == 10
    assert all(i.startswith("ho2_") for i in ids)
    assert not set(ids) & {c["id"] for c in main + holdout}


def test_holdout2_fields_and_labels_are_valid():
    cases, main, holdout = _sets()
    labels = {c["expected"] for c in main}  # the action labels cases.json uses
    reasons = {c["reason"] for c in main + holdout}
    stages = {c["stage"] for c in main + holdout}
    for c in cases:
        assert REQUIRED <= set(c), c["id"]
        assert c["expected"] in labels, c["id"]
        assert c["reason"] in reasons and c["stage"] in stages, c["id"]
        assert isinstance(c["hard"], bool) and c["why"].strip() and c["buyer_message"].strip(), c["id"]
        assert c["item"]["price"] > 0 and {"sku", "name", "variant"} <= set(c["item"]), c["id"]
        # Events cannot predate the purchase or lie in the future.
        s = c["shipment"]
        assert s is None or 0 <= s["days_after_purchase"] <= c["days_since_purchase"], c["id"]
        assert not c.get("refund") or 0 <= c["refund"]["days_ago"] <= c["days_since_purchase"], c["id"]
        r = c.get("return_shipment")
        assert not r or 0 <= r["days_ago"] <= c["days_since_purchase"] - (s["days_after_purchase"] if s else 0), c["id"]
    assert sum(c["hard"] for c in cases) >= 3
    assert {c["reason"] for c in cases} == reasons  # every dispute reason is covered
    assert any(c.get("agent_purchase") for c in cases) and any(c.get("duplicate_charge") for c in cases)


def test_every_holdout2_case_seeds_the_mock_without_a_write():
    settings = ev.eval_settings()
    assert settings.mock  # evals always use the mock sandbox
    for case in load_cases(ev.SETS["holdout2"]):
        rt = Runtime(settings=settings, seed_cases=[], force_rules=True, tracing=False,
                     checkpointer=InMemorySaver(), provider=None, strict=True)
        assert seed_case(case, 0, rt.mock, rt.store) == "PP-D-2000", case["id"]
        assert rt.mock.write_calls() == [], case["id"]


def test_save_run_names_the_second_held_out_set_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "HERE", tmp_path)
    base = {"provider": "groq", "model": "qwen/qwen3.8-27b", "date": "2026-10-09"}
    assert ev.save_run({**base, "set": "holdout2"}).name == "groq-qwen3.8-27b-holdout2-20261009.json"
    assert ev.save_run({**base, "set": "holdout"}).name == "groq-qwen3.8-27b-holdout-20261009.json"
    assert ev.save_run({**base, "set": "main"}).name == "groq-qwen3.8-27b-20261009.json"


def test_holdout2_runs_offline_on_the_rules_baseline_without_a_write():
    """Smoke test, no model: every case is analysed up to the approval gate and nothing is written to PayPal."""
    settings = ev.eval_settings()
    for case in load_cases(ev.SETS["holdout2"]):
        row, _, _ = ev.run_case(case, settings, force_rules=True)
        assert row["writes_before_approval"] == 0, case["id"]


def test_a_holdout2_results_file_lands_in_its_own_results_section(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(ev, "HERE", tmp_path)
    (tmp_path / "results").mkdir()

    def run_file(name, cid, set_name=None):
        row = {"id": cid, "title": cid, "hard": False, "expected": "ACCEPT_CLAIM", "got": "ACCEPT_CLAIM",
               "correct": True, "confidence": 0.9, "source": "x", "provider": "p", "model": "m"}
        d = {"mode": "m", "cases": 1, "accuracy": 1.0, "standard_accuracy": 1.0, "hard_accuracy": None,
             "hard_cases": 0, "approval_gate_violations": 0, "rows": [row], "tokens_used": 1, "langfuse": None,
             "provider": "p", "model": "m", "date": "2026-10-09"}
        if set_name:
            d["set"] = set_name
        (tmp_path / "results" / name).write_text(json.dumps(d))

    run_file("main.json", "main_a")
    run_file("ho.json", "ho_a", "holdout")
    run_file("ho2.json", "ho2_a", "holdout2")
    ev.write_results_md()
    text = (tmp_path / "RESULTS.md").read_text()
    rest, ho2 = text.split("## Held-out set 2 (not used for tuning)")
    assert "ho2_a" in ho2 and "ho2_a" not in rest
    assert "ho_a" in rest and "ho_a" not in ho2 and "main_a" in rest


def test_a_holdout2_miss_is_marked_as_a_facts_limit_not_a_model_failure(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr(ev, "HERE", tmp_path)
    (tmp_path / "results").mkdir()
    row = {"id": "ho2_inr_unit_format", "title": "t", "hard": True, "expected": "SHARE_TRACKING",
           "got": "OFFER_REPLACEMENT", "correct": False, "confidence": 0.9, "source": "x", "provider": "p",
           "model": "m"}
    d = {"mode": "m", "cases": 1, "accuracy": 0.0, "standard_accuracy": None, "hard_accuracy": 0.0, "hard_cases": 1,
         "approval_gate_violations": 0, "rows": [row], "tokens_used": 1, "langfuse": None, "provider": "p",
         "model": "m", "date": "2026-10-09", "set": "holdout2"}
    (tmp_path / "results" / "ho2.json").write_text(json.dumps(d))
    ev.write_results_md()
    text = (tmp_path / "RESULTS.md").read_text()
    assert "ho2_inr_unit_format (facts limit)" in text and "not a model failure" in text
