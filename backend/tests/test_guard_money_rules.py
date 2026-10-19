"""Guard money rules for queue R27: over-limit assistant buys and uncertain addresses."""

import pytest

from evals import run as ev
from rebuttal.agent.facts import gather
from rebuttal.agent.reasoner import Decision, RuleReasoner, guard
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW, load_cases, seed_case


def _gather(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _holdout2(case_id):
    """A holdout2 case, seeded the way the eval runner seeds it (mock sandbox, no write)."""
    spec = next(c for c in load_cases(ev.SETS["holdout2"]) if c["id"] == case_id)
    rt = Runtime(settings=ev.eval_settings(), seed_cases=[], force_rules=True, tracing=False, provider=None,
                 strict=True)
    seed_case(spec, 0, rt.mock, rt.store)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _model(resolution, confidence=0.9):
    return Decision(resolution, confidence, [], "", "m", "", source="claude")


# ------------------------------------- an assistant purchase outside its limit or instruction is not defended
@pytest.mark.parametrize("resolution", ["SUBMIT_EVIDENCE", "OFFER_PARTIAL_REFUND"])
def test_over_cap_assistant_purchase_is_not_defended_and_falls_back_to_the_rules(resolution):
    case = _holdout2("ho2_unauth_over_cap")
    assert case.facts["is_agent_purchase"] is True and case.facts["within_agent_spending_limit"] is False
    assert RuleReasoner().decide(case).resolution == "ACCEPT_CLAIM"
    d = guard(_model(resolution), case)
    assert d.resolution == "ACCEPT_CLAIM"
    assert any("spending limit or instruction" in n for n in d.guard_notes)
    assert any("Fell back to rules" in n for n in d.guard_notes)


def test_over_cap_assistant_purchase_with_a_matched_address_keeps_the_rules_evidence_once():
    case = _holdout2("ho2_unauth_over_cap")
    case.facts["delivered_address_matches"] = True
    d = guard(_model("SUBMIT_EVIDENCE"), case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence == 0.7
    assert sum("Fell back to rules" in n for n in d.guard_notes) == 1
    assert not any("not possible now" in n for n in d.guard_notes)


def test_assistant_purchase_within_limit_and_instruction_is_still_defended():
    case = _gather("unauth_agent_mandate")
    assert case.facts["within_agent_spending_limit"] is True and case.facts["agent_followed_instruction"] is True
    d = guard(_model("SUBMIT_EVIDENCE"), case)
    assert d.resolution == "SUBMIT_EVIDENCE"
    assert not any("spending limit or instruction" in n for n in d.guard_notes)


# --------------------------------------------- an uncertain address (None) is evidence with a check, not a misdelivery
@pytest.mark.parametrize(("address_matches", "expected"), [
    (True, ("SUBMIT_EVIDENCE", 0.7)),
    (False, ("ACCEPT_CLAIM", 0.6)),
])
def test_unauthorised_rules_read_a_proven_address_match(address_matches, expected):
    case = _gather("unauth_delivered")
    case.facts["delivered_address_matches"] = address_matches
    d = RuleReasoner().decide(case)
    assert (d.resolution, d.confidence) == expected


def test_unauthorised_uncertain_address_is_evidence_at_half_confidence_with_a_check():
    case = _gather("unauth_delivered")
    case.facts["delivered_address_matches"] = None
    d = RuleReasoner().decide(case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence == 0.5
    assert any("written differently" in r for r in d.reasoning)


def test_unauthorised_without_an_address_fact_is_a_claim():
    case = _gather("unauth_delivered")
    case.facts.pop("delivered_address_matches")
    d = RuleReasoner().decide(case)
    assert (d.resolution, d.confidence) == ("ACCEPT_CLAIM", 0.6)


def test_unauthorised_uncertain_address_stays_evidence_through_guard():
    case = _gather("unauth_delivered")
    case.facts["delivered_address_matches"] = None
    d = guard(RuleReasoner().decide(case), case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence == 0.5
