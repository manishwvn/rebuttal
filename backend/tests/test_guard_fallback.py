"""Guard fallback, missing merchant order, facts-based damage and CHARGEBACK offers (queue R2, piece p1)."""

import pytest

from rebuttal.agent.facts import _compute_facts, gather
from rebuttal.agent.reasoner import (
    RESOLUTIONS,
    Decision,
    RuleReasoner,
    draft_evidence_summary,
    draft_message,
    guard,
    paypal_allows,
)
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW

ORDERLESS_REASONS = ("MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "CREDIT_NOT_PROCESSED", "UNAUTHORISED")


def _gather(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _orderless_case(reason, case_id="inr_no_tracking"):
    """A gathered case with no merchant order record, at INQUIRY with no PayPal option list."""
    case = _gather(case_id)
    case.order = None
    case.facts = _compute_facts(None, None, None, case.amount, DEMO_NOW, case.buyer_messages)
    case.reason = reason
    case.stage = "INQUIRY"
    case.allowed_response_options = None
    return case


def test_unknown_resolution_falls_back_to_a_resolution_paypal_allows():
    case = _gather("hard_stuck_wants_refund")
    case.facts.update(has_tracking=True, shipment_status="SHIPPED", days_since_last_scan=12)
    assert RuleReasoner().decide(case).resolution == "OFFER_REPLACEMENT"

    case.allowed_response_options = {
        "accept_claim": {"accept_claim_types": ["REFUND"]},
        "make_offer": {"offer_types": []},
    }
    d = guard(Decision("NOT_A_REAL_RESOLUTION", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and paypal_allows(d.resolution, case)
    assert any("Unknown resolution" in n for n in d.guard_notes)
    assert any("Fell back to rules" in n for n in d.guard_notes)
    assert any("OFFER_REPLACEMENT is not possible" in n and "PayPal does not allow it" in n for n in d.guard_notes)


def test_fallback_with_nothing_allowed_keeps_the_rules_choice_at_low_confidence():
    case = _gather("hard_stuck_wants_refund")
    case.facts.update(has_tracking=True, shipment_status="SHIPPED", days_since_last_scan=12)
    case.allowed_response_options = {"accept_claim": {"accept_claim_types": []}, "make_offer": {"offer_types": []}}
    d = guard(Decision("NOT_A_REAL_RESOLUTION", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_REPLACEMENT" and d.confidence <= 0.3


@pytest.mark.parametrize("reason", ORDERLESS_REASONS)
def test_missing_order_rules_ask_for_merchant_review(reason):
    d = RuleReasoner().decide(_orderless_case(reason))
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence <= 0.3
    assert "No merchant order record; needs merchant review." in d.reasoning


def test_drafts_do_not_crash_without_an_order():
    case = _orderless_case("UNAUTHORISED")
    for resolution in RESOLUTIONS:
        assert draft_message(resolution, case)
        assert draft_evidence_summary(resolution, case)


@pytest.mark.parametrize("resolution", ["ACCEPT_CLAIM", "OFFER_REPLACEMENT"])
def test_missing_order_caps_a_claim_or_replacement_and_keeps_the_resolution(resolution):
    case = _orderless_case("MERCHANDISE_OR_SERVICE_NOT_RECEIVED")
    d = guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == resolution and d.confidence <= 0.3
    assert any("No merchant order record" in n for n in d.guard_notes)


def test_missing_order_keeps_evidence_confidence_and_a_normal_claim_has_no_such_note():
    case = _orderless_case("MERCHANDISE_OR_SERVICE_NOT_RECEIVED")
    d = guard(Decision("SUBMIT_EVIDENCE", 0.9, [], "", "m", "evidence", source="claude"), case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence == 0.9

    normal = _gather("inr_no_tracking")
    assert normal.facts["order_found"] is True
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), normal)
    assert d.resolution == "ACCEPT_CLAIM" and d.confidence == 0.9
    assert not any("No merchant order record" in n for n in d.guard_notes)


@pytest.mark.parametrize("reason", ORDERLESS_REASONS)
def test_unknown_model_choice_without_an_order_never_accepts_above_0_3(reason):
    case = _orderless_case(reason)
    d = guard(Decision("NOT_A_REAL_RESOLUTION", 0.9, [], "", "m", "", source="claude"), case)
    assert not (d.resolution == "ACCEPT_CLAIM" and d.confidence > 0.3)


def test_damage_is_read_from_facts_not_from_the_last_buyer_message():
    case = _gather("snad_changed_mind")
    case.buyer_messages = ["It arrived broken.", "Any update on this?"]
    case.amount = 100.0
    case.facts.update(
        is_agent_purchase=False,
        buyer_reports_damage=True,
        refund_without_return_eligible=False,
        within_return_window=True,
    )
    resolution, confidence, _ = RuleReasoner()._pick(case)
    assert (resolution, confidence) == ("OFFER_REPLACEMENT", 0.75)

    case.facts["refund_without_return_eligible"] = True  # a small item by price, whatever the claim amount says
    resolution, confidence, _ = RuleReasoner()._pick(case)
    assert (resolution, confidence) == ("ACCEPT_CLAIM", 0.8)

    case.facts.update(buyer_reports_damage=False, refund_without_return_eligible=False)
    resolution, _, _ = RuleReasoner()._pick(case)
    assert resolution == "OFFER_RETURN_FOR_REFUND"


def test_chargeback_without_a_paypal_list_allows_no_offer():
    case = _gather("inr_delivered_claim")
    assert case.stage == "CHARGEBACK"
    case.allowed_response_options = None
    for resolution in ("OFFER_REPLACEMENT", "OFFER_PARTIAL_REFUND", "OFFER_RETURN_FOR_REFUND"):
        assert not paypal_allows(resolution, case)
    for resolution in ("ACCEPT_CLAIM", "SUBMIT_EVIDENCE", "SHARE_TRACKING"):
        assert paypal_allows(resolution, case)


def test_chargeback_guard_turns_an_offer_into_a_claim():
    case = _gather("inr_delivered_claim")
    case.allowed_response_options = None
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM"
    assert any("OFFER_REPLACEMENT is not possible" in n for n in d.guard_notes)


def test_inquiry_without_a_paypal_list_and_the_proven_fallback_are_unchanged():
    case = _gather("hard_stuck_wants_refund")
    case.allowed_response_options = None
    assert paypal_allows("OFFER_REPLACEMENT", case)

    case = _gather("snad_changed_mind")
    case.allowed_response_options = None
    assert not paypal_allows("OFFER_REPLACEMENT", case)
    assert paypal_allows("OFFER_RETURN_FOR_REFUND", case) and paypal_allows("ACCEPT_CLAIM", case)
