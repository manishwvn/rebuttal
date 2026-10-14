"""ESCALATE and APPEAL: PayPal gating, rules picks, guard fallbacks, drafts and the model schema (queue S2, piece p4)."""

from typing import get_args

import pytest
from pydantic import ValidationError

from rebuttal.agent.facts import _compute_facts, gather
from rebuttal.agent.llm import DecisionOut, ResolutionName
from rebuttal.agent.reasoner import (
    RESOLUTIONS,
    Decision,
    RuleReasoner,
    build_payload,
    draft_evidence_summary,
    draft_message,
    guard,
    paypal_allows,
)
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW

FACT_VALUES = [True, False, 1, None]  # None = the fact is missing; 1 is truthy but not True


def _gather(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def _delivered_case():
    """inr_delivered: a NOT_RECEIVED inquiry, delivered to the address on the order."""
    case = _gather("inr_delivered")
    assert case.reason == "MERCHANDISE_OR_SERVICE_NOT_RECEIVED" and case.stage == "INQUIRY"
    assert case.facts["shipment_status"] == "DELIVERED" and case.facts["delivered_address_matches"] is True
    assert "can_escalate" not in case.facts and "can_appeal" not in case.facts
    return case


def _orderless_delivered_case():
    case = _delivered_case()
    case.order = None
    case.facts = _compute_facts(None, None, None, case.amount, DEMO_NOW, case.buyer_messages)
    return case


def _set_fact(case, key, value):
    if value is None:
        case.facts.pop(key, None)
    else:
        case.facts[key] = value


# ------------------------------------------------------------------ PayPal gating
@pytest.mark.parametrize("value,allowed", [(True, True), (False, False), (1, False), ("yes", False), (None, False)])
def test_paypal_allows_ESCALATE_only_when_can_escalate_is_true(value, allowed):
    case = _delivered_case()
    _set_fact(case, "can_escalate", value)
    assert paypal_allows("ESCALATE", case) is allowed


@pytest.mark.parametrize("value,allowed", [(True, True), (False, False), (1, False), ("yes", False), (None, False)])
def test_paypal_allows_APPEAL_only_when_can_appeal_is_true(value, allowed):
    case = _delivered_case()
    _set_fact(case, "can_appeal", value)
    assert paypal_allows("APPEAL", case) is allowed


def test_the_other_resolutions_keep_their_paypal_rules():
    case = _delivered_case()
    assert paypal_allows("SHARE_TRACKING", case) and paypal_allows("SUBMIT_EVIDENCE", case)


def test_build_payload_offers_ESCALATE_and_APPEAL_only_with_their_facts():
    case = _delivered_case()
    offered = build_payload(case)["allowed_resolutions"]
    assert "ESCALATE" not in offered and "APPEAL" not in offered

    case.facts.update(can_escalate=True, can_appeal=False)
    offered = build_payload(case)["allowed_resolutions"]
    assert offered["ESCALATE"] == RESOLUTIONS["ESCALATE"] and "APPEAL" not in offered

    case.facts.update(can_escalate=False, can_appeal=True)
    offered = build_payload(case)["allowed_resolutions"]
    assert offered["APPEAL"] == RESOLUTIONS["APPEAL"] and "ESCALATE" not in offered


def test_the_model_is_asked_for_ESCALATE_and_APPEAL_only_with_their_facts():
    case = _delivered_case()
    listed = build_payload(case)["respond_with"]["resolution"]
    assert "ESCALATE" not in listed and "APPEAL" not in listed
    assert "SHARE_TRACKING" in listed and "SUBMIT_EVIDENCE" in listed

    case.facts.update(can_escalate=True, can_appeal=True)
    listed = build_payload(case)["respond_with"]["resolution"]
    assert "ESCALATE" in listed and "APPEAL" in listed


# --------------------------------------------------------------------- rules picks
def test_rules_pick_ESCALATE_for_a_delivered_inquiry_the_seller_already_answered():
    case = _delivered_case()
    case.facts.update(can_escalate=True, seller_already_responded=True)
    resolution, confidence, why = RuleReasoner()._pick(case)
    assert (resolution, confidence) == ("ESCALATE", 0.7)
    assert why == ["Delivered to the order address and we already answered the buyer, but the dispute is still "
                   "open; ask PayPal to decide."]
    assert guard(RuleReasoner().decide(case), case).resolution == "ESCALATE"


@pytest.mark.parametrize("facts", [
    {"can_escalate": True, "seller_already_responded": False},
    {"can_escalate": True},
    {"can_escalate": False, "seller_already_responded": True},
])
def test_rules_still_share_tracking_without_both_escalation_facts(facts):
    case = _delivered_case()
    case.facts.update(facts)
    assert RuleReasoner()._pick(case)[0] == "SHARE_TRACKING"


def test_rules_never_escalate_at_a_chargeback():
    case = _delivered_case()
    case.stage = "CHARGEBACK"
    case.facts.update(can_escalate=True, seller_already_responded=True)
    assert RuleReasoner()._pick(case)[0] == "SUBMIT_EVIDENCE"


@pytest.mark.parametrize("stage", ["INQUIRY", "PRE_ARBITRATION", "ARBITRATION", "CHARGEBACK"])
def test_only_an_inquiry_can_be_escalated(stage):
    case = _delivered_case()
    case.stage = stage
    case.facts.update(can_escalate=True, seller_already_responded=True)
    only_inquiry = stage == "INQUIRY"
    assert paypal_allows("ESCALATE", case) is only_inquiry
    assert (RuleReasoner()._pick(case)[0] == "ESCALATE") is only_inquiry
    kept = guard(Decision("ESCALATE", 0.9, [], "", "m", "", source="claude"), case)
    assert (kept.resolution == "ESCALATE") is only_inquiry
    assert only_inquiry or any("Proposed escalating" in n for n in kept.guard_notes)


def test_rules_pick_APPEAL_when_paypal_offers_one_and_the_order_is_found():
    case = _delivered_case()
    case.facts["can_appeal"] = True
    resolution, confidence, why = RuleReasoner()._pick(case)
    assert (resolution, confidence) == ("APPEAL", 0.6)
    assert why == ["PayPal ruled against us and offers an appeal; resubmit our evidence."]


def test_rules_do_not_pick_APPEAL_without_an_order_record():
    case = _orderless_delivered_case()
    case.facts["can_appeal"] = True
    assert RuleReasoner()._pick(case) == ("SUBMIT_EVIDENCE", 0.3, ["No merchant order record; needs merchant review."])


def test_truthy_but_not_true_facts_do_not_open_the_dispute_actions():
    case = _delivered_case()
    case.facts.update(can_escalate=1, can_appeal=1, seller_already_responded=True)
    assert RuleReasoner()._pick(case)[0] == "SHARE_TRACKING"
    assert not paypal_allows("ESCALATE", case) and not paypal_allows("APPEAL", case)


# --------------------------------------------------------------------------- guard
def test_guard_turns_an_unsupported_ESCALATE_into_the_rules_pick():
    case = _delivered_case()
    case.facts["seller_already_responded"] = True  # can_escalate is missing
    d = guard(Decision("ESCALATE", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "SHARE_TRACKING" and d.source == "claude+guard"
    assert any(n.startswith("Proposed escalating, but PayPal does not offer escalation here or delivery to the order "
                            "address is not proven.") for n in d.guard_notes)
    assert any("Fell back to rules: SHARE_TRACKING." in n for n in d.guard_notes)


@pytest.mark.parametrize("change", [
    {"shipment_status": "SHIPPED", "days_since_last_scan": 2},
    {"delivered_address_matches": False},
    {"can_escalate": False},
])
def test_guard_turns_ESCALATE_into_the_rules_pick_when_delivery_is_not_proven(change):
    case = _delivered_case()
    case.facts.update({"can_escalate": True, "seller_already_responded": True})
    case.facts.update(change)
    rules = RuleReasoner().decide(case).resolution
    assert rules != "ESCALATE"
    d = guard(Decision("ESCALATE", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == rules
    assert any("Proposed escalating" in n for n in d.guard_notes)


def test_guard_turns_an_unsupported_APPEAL_into_the_rules_pick():
    case = _delivered_case()
    d = guard(Decision("APPEAL", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "SHARE_TRACKING" and d.source == "claude+guard"
    assert any("Proposed an appeal, but PayPal offers none or we hold no order record." in n for n in d.guard_notes)


def test_guard_turns_APPEAL_into_the_rules_pick_without_an_order_record():
    case = _orderless_delivered_case()
    case.facts["can_appeal"] = True
    d = guard(Decision("APPEAL", 0.9, [], "", "m", "", source="claude"), case)
    assert d.resolution == "SUBMIT_EVIDENCE" and d.confidence <= 0.3
    assert any("Proposed an appeal" in n for n in d.guard_notes)


def test_guard_keeps_a_valid_ESCALATE_untouched():
    case = _delivered_case()
    case.facts.update(can_escalate=True, seller_already_responded=True)
    d = guard(Decision("ESCALATE", 0.8, ["x"], "", "our message", "", source="claude"), case)
    assert (d.resolution, d.confidence, d.message_to_buyer, d.guard_notes) == ("ESCALATE", 0.8, "our message", [])


def test_guard_keeps_a_valid_APPEAL_untouched():
    case = _delivered_case()
    case.facts["can_appeal"] = True
    d = guard(Decision("APPEAL", 0.8, ["x"], "", "m", "Our new proof.", source="claude"), case)
    assert (d.resolution, d.confidence, d.evidence_summary, d.guard_notes) == ("APPEAL", 0.8, "Our new proof.", [])


def test_APPEAL_without_an_evidence_summary_gets_the_evidence_draft():
    case = _delivered_case()
    case.facts["can_appeal"] = True
    d = guard(Decision("APPEAL", 0.8, [], "", "m", "", source="claude"), case)
    assert d.evidence_summary and d.evidence_summary == draft_evidence_summary("APPEAL", case)


@pytest.mark.parametrize("can_escalate", FACT_VALUES)
@pytest.mark.parametrize("can_appeal", FACT_VALUES)
@pytest.mark.parametrize("seller_already_responded", [True, False])
@pytest.mark.parametrize("delivered_address_matches", [True, False, 1, "yes", None])
def test_the_fallback_cannot_loop_for_any_combination_of_dispute_facts(
        can_escalate, can_appeal, seller_already_responded, delivered_address_matches):
    """The rules only pick ESCALATE or APPEAL when the guard accepts them, so a fallback never recurses forever."""
    case = _delivered_case()
    case.facts["seller_already_responded"] = seller_already_responded
    case.facts["delivered_address_matches"] = delivered_address_matches
    _set_fact(case, "can_escalate", can_escalate)
    _set_fact(case, "can_appeal", can_appeal)

    guarded = guard(RuleReasoner().decide(case), case)
    assert not any("Fell back to rules" in n for n in guarded.guard_notes)
    for proposed in ("ESCALATE", "APPEAL"):
        d = guard(Decision(proposed, 0.9, [], "", "m", "", source="claude"), case)
        assert d.resolution != proposed or paypal_allows(proposed, case)


# -------------------------------------------------------------------------- drafts
def test_draft_message_ESCALATE_mentions_the_tracking_and_stays_short():
    case = _delivered_case()
    msg = draft_message("ESCALATE", case)
    assert f"{case.facts['carrier']} {case.facts['tracking_number']}" in msg
    assert case.facts["delivered_on"] in msg and "PayPal" in msg
    assert len(msg.split()) < 90


# ------------------------------------------------------------------ model schema
@pytest.mark.parametrize("resolution", list(RESOLUTIONS))
def test_every_resolution_validates_in_the_model_output_schema(resolution):
    out = DecisionOut(buyer_wants="x", resolution=resolution, confidence=0.5, reasoning=[], message_to_buyer="m")
    assert out.resolution == resolution


def test_the_model_schema_offers_exactly_the_resolutions_including_both_dispute_actions():
    assert set(get_args(ResolutionName)) == set(RESOLUTIONS)
    assert {"ESCALATE", "APPEAL"} <= set(get_args(ResolutionName))
    with pytest.raises(ValidationError):
        DecisionOut(buyer_wants="x", resolution="NOT_A_RESOLUTION", confidence=0.5, reasoning=[], message_to_buyer="m")
