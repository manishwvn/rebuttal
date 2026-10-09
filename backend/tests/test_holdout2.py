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
