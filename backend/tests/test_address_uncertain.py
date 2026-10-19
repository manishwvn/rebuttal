"""A delivered address that is written differently (fact None) is uncertain, not a misdelivery (queue R16, piece B)."""

import pytest

from rebuttal.agent.facts import gather
from rebuttal.agent.reasoner import SYSTEM_PROMPT, Decision, RuleReasoner, draft_evidence_summary, guard
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW

NOTE = "Delivery address written differently; confirm before relying on tracking"
ADDRESS_LINES = {
    True: "Delivered to the address on the order.",
    None: "Delivery address is written differently from the order address (same house number, ZIP and city).",
    False: "Delivery address differs from the order address.",
}


def _case_facts(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return rt, gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _delivered_case(address_matches, **over):
    _, case = _case_facts("inr_delivered")
    case.facts.update(shipment_status="DELIVERED", has_tracking=True, delivered_on="2026-01-01",
                      delivered_address_matches=address_matches, **over)
    case.reason = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"
    case.stage = "INQUIRY"
    case.allowed_response_options = None
    return case


@pytest.mark.parametrize("choice", ["SHARE_TRACKING", "SUBMIT_EVIDENCE"])
def test_uncertain_address_keeps_the_choice_adds_a_note_and_caps_confidence(choice):
    d = guard(Decision(choice, 0.9, [], "", "m", "", source="claude"), _delivered_case(None))
    assert d.resolution == choice
    assert NOTE in d.guard_notes
    assert d.confidence == 0.6


def test_uncertain_address_never_raises_a_lower_confidence():
    d = guard(Decision("SHARE_TRACKING", 0.4, [], "", "m", "", source="claude"), _delivered_case(None))
    assert d.resolution == "SHARE_TRACKING" and d.confidence == 0.4
    assert NOTE in d.guard_notes


def test_uncertain_address_note_is_added_once_when_guard_runs_twice():
    case = _delivered_case(None)
    d = guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), case)
    d = guard(d, case)
    assert d.guard_notes.count(NOTE) == 1 and d.confidence == 0.6


def test_mismatched_address_still_becomes_a_replacement_without_the_uncertain_note():
    for choice in ("SHARE_TRACKING", "SUBMIT_EVIDENCE"):
        d = guard(Decision(choice, 0.9, [], "", "m", "", source="claude"), _delivered_case(False))
        assert d.resolution == "OFFER_REPLACEMENT" and NOTE not in d.guard_notes


def test_matching_address_adds_no_uncertain_note_and_no_cap():
    d = guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), _delivered_case(True))
    assert d.resolution == "SHARE_TRACKING" and NOTE not in d.guard_notes and d.confidence == 0.9


def test_missing_address_key_adds_no_uncertain_note_and_no_cap():
    case = _delivered_case(None)
    del case.facts["delivered_address_matches"]
    case.facts["shipment_status"] = "SHIPPED"
    d = guard(Decision("SHARE_TRACKING", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "SHARE_TRACKING" and NOTE not in d.guard_notes and d.confidence == 0.9


def test_uncertain_address_shares_tracking_instead_of_offering_a_replacement():
    case = _delivered_case(None)
    rules = RuleReasoner().decide(case)
    assert rules.resolution == "SHARE_TRACKING"
    d = guard(rules, case)
    assert d.resolution == "SHARE_TRACKING" and NOTE in d.guard_notes and d.confidence == 0.6


def test_mismatched_address_is_still_the_replacement_pick_for_the_rules():
    rules = RuleReasoner().decide(_delivered_case(False))
    assert rules.resolution == "OFFER_REPLACEMENT"
    assert guard(rules, _delivered_case(False)).resolution == "OFFER_REPLACEMENT"


@pytest.mark.parametrize("missing", [False, True])
def test_rules_never_offer_a_replacement_or_escalate_on_an_uncertain_address(missing):
    case = _delivered_case(None, can_escalate=True, seller_already_responded=True)
    if missing:
        del case.facts["delivered_address_matches"]
    assert RuleReasoner().decide(case).resolution == "SHARE_TRACKING"


@pytest.mark.parametrize("matches", [True, None, False])
def test_evidence_summary_states_the_address_check_in_three_ways(matches):
    summary = draft_evidence_summary("SUBMIT_EVIDENCE", _delivered_case(matches))
    assert ADDRESS_LINES[matches] in summary
    assert all(line not in summary for key, line in ADDRESS_LINES.items() if key != matches)


def test_system_prompt_says_a_null_address_fact_is_not_a_misdelivery():
    assert "If delivered_address_matches is null" in SYSTEM_PROMPT
    assert "do not treat that as a misdelivery" in SYSTEM_PROMPT
