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


@pytest.mark.parametrize(
    "case_id, resolution",
    [
        ("snad_damaged_high_value", "ACCEPT_CLAIM"),
        ("snad_damaged_high_value", "OFFER_RETURN_FOR_REFUND"),
        ("snad_damaged_high_value", "OFFER_REPLACEMENT"),
        ("snad_changed_mind", "OFFER_RETURN_FOR_REFUND"),
        ("snad_changed_mind", "OFFER_REPLACEMENT"),
        ("snad_changed_mind", "ACCEPT_CLAIM"),
    ],
)
def test_chargeback_without_a_list_never_refunds_a_return_claim_in_full(case_id, resolution):
    case = _gather(case_id)
    case.stage = "CHARGEBACK"
    case.allowed_response_options = None
    d = guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case)
    assert not (d.resolution == "ACCEPT_CLAIM" and d.confidence > 0.3)
    assert d.confidence <= 0.3


def test_chargeback_without_a_list_note_says_no_list_was_given():
    case = _gather("inr_delivered_claim")
    case.allowed_response_options = None
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert any("PayPal gave no option list at this chargeback" in n for n in d.guard_notes)
    assert not any("PayPal does not allow it" in n for n in d.guard_notes)


def test_chargeback_with_a_list_keeps_the_does_not_allow_note():
    case = _gather("inr_delivered_claim")
    case.allowed_response_options = {"accept_claim": {"accept_claim_types": ["REFUND"]},
                                     "make_offer": {"offer_types": []}}
    d = guard(Decision("OFFER_REPLACEMENT", 0.9, [], "", "m", "", source="claude"), case)
    assert any("PayPal does not allow it (allowed_response_options)" in n for n in d.guard_notes)


def test_change_of_mind_claim_without_return_becomes_return_for_refund_when_damaged():
    case = _gather("snad_changed_mind")
    assert case.stage == "INQUIRY" and case.facts["refund_without_return_eligible"] is False
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and d.guard_notes == []  # no damage: this rule leaves the claim alone
    case.facts["buyer_reports_damage"] = True
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"


def test_missing_order_caps_partial_and_return_offers_too():
    for resolution in ("OFFER_PARTIAL_REFUND", "OFFER_RETURN_FOR_REFUND"):
        case = _orderless_case("MERCHANDISE_OR_SERVICE_NOT_RECEIVED")
        d = guard(Decision(resolution, 0.9, [], "", "m", "", source="claude"), case)
        assert d.resolution == resolution and d.confidence <= 0.3
        assert any("No merchant order record" in n for n in d.guard_notes)


@pytest.mark.parametrize("message", [
    "I am a student and I changed my mind, refund me.",
    "I'm confident it is fine, I just changed my mind, refund me.",
    "It is not evident as described, I just changed my mind.",
])
@pytest.mark.xfail(strict=True, reason="facts.py DAMAGE_WORDS is a substring match ('dent' in 'student', 'confident', "
                   "'evident'); needs a word-start fix in facts.py, outside queue R2 p1 scope")
def test_common_words_are_not_read_as_damage(message):
    order = _gather("inr_no_tracking").order
    facts = _compute_facts(order, None, None, 10.0, DEMO_NOW, [message])
    assert facts["buyer_reports_damage"] is False


@pytest.mark.xfail(strict=True, reason="facts.py refund_without_return_eligible uses items[0] only, not the damaged "
                   "line; guard() now caps it by the disputed amount, but the fact needs a facts.py fix outside queue "
                   "R2 p1 scope")
def test_two_line_order_with_a_cheap_first_line_is_not_refund_without_return():
    order = _gather("inr_no_tracking").order
    order.items = [{"name": "Vase", "variant": "Blue", "price": 15.0},
                   {"name": "Lamp", "variant": "Brass", "price": 200.0}]
    facts = _compute_facts(order, None, None, 215.0, DEMO_NOW, ["The lamp arrived broken."])
    assert facts["refund_without_return_eligible"] is False


def test_damaged_big_claim_on_a_cheap_first_line_is_not_refunded_without_return():
    """items[0] makes the fact look small; the disputed amount is what the claim is for."""
    case = _gather("inr_no_tracking")
    case.order.items = [{"name": "Vase", "variant": "Blue", "price": 15.0},
                        {"name": "Lamp", "variant": "Brass", "price": 200.0}]
    case.reason = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
    case.stage = "INQUIRY"
    case.amount = 215.0
    case.buyer_messages = ["The lamp arrived broken."]
    case.facts = _compute_facts(case.order, None, None, 215.0, DEMO_NOW, case.buyer_messages)
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "OFFER_RETURN_FOR_REFUND"
    assert any("refund-without-return threshold" in n for n in d.guard_notes)


def test_damaged_small_claim_is_still_refunded_without_return():
    case = _gather("inr_no_tracking")
    case.order.items = [{"name": "Vase", "variant": "Blue", "price": 15.0}]
    case.reason = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
    case.stage = "INQUIRY"
    case.amount = 15.0
    case.buyer_messages = ["The vase arrived broken."]
    case.facts = _compute_facts(case.order, None, None, 15.0, DEMO_NOW, case.buyer_messages)
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and d.confidence == 0.9


def test_chargeback_full_refund_without_a_list_and_no_return_is_capped():
    case = _gather("snad_changed_mind")
    case.stage = "CHARGEBACK"
    case.allowed_response_options = None
    d = guard(Decision("ACCEPT_CLAIM", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "ACCEPT_CLAIM" and d.confidence <= 0.3
    assert any("no option list" in n and "Resolution Center" in n for n in d.guard_notes)
