"""Planner actions for escalating a dispute and appealing it, and the richer evidence lists they and SUBMIT_EVIDENCE send."""

from rebuttal.agent.facts import gather
from rebuttal.agent.pipeline import PlannedAction, Proposal, approved_text, build_evidence_pdf, plan_actions
from rebuttal.agent.reasoner import Decision
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW


def _case(**facts):
    """A real case from the seeded `agent_wrong_size` dispute, with the shipment facts set by hand."""
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    case.facts.update(facts)
    return case


def _decision(resolution, summary="Seller evidence summary.", message="We are sorting this out.", **over):
    return Decision(resolution, 0.9, [], "", message, summary, source="rules", **over)


def _tracked(carrier="UPS", number="1Z999", status="DELIVERED", **over):
    return dict(has_tracking=True, carrier=carrier, tracking_number=number, shipment_status=status,
                return_received=False, **over)


UNTRACKED = dict(has_tracking=False, return_received=False)
RETURN_RECEIVED = dict(return_received=True, return_carrier="FEDEX", return_tracking_number="7489")


def _evidence_list(facts, resolution="SUBMIT_EVIDENCE", summary="Seller evidence summary."):
    (action,) = plan_actions(_decision(resolution, summary), _case(**facts))
    return action.params["evidences"]


# --- escalate ------------------------------------------------------------------------------------------------------
def test_escalate_plans_one_claim_escalation_with_the_buyer_note():
    case = _case(**_tracked())
    (action,) = plan_actions(_decision("ESCALATE", message="Escalating to a claim."), case)
    assert action.kind == "escalate"
    assert action.summary == "Escalate to a PayPal claim"
    assert action.params == {"note": "Escalating to a claim."}


def test_escalate_note_is_trimmed_to_paypal_limit():
    (action,) = plan_actions(_decision("ESCALATE", message="x" * 2500), _case(**_tracked()))
    assert action.params["note"] == "x" * 2000


def test_escalate_needs_no_evidence_pdf():
    proposal = Proposal("p1", "PP-D-2000", "2026-10-14T00:00:00+00:00", _decision("ESCALATE"),
                        [PlannedAction("escalate", "Escalate", {"note": "n"})], {})
    assert proposal.needs_evidence_pdf is False and proposal.to_dict()["has_evidence_document"] is False


# --- appeal --------------------------------------------------------------------------------------------------------
def test_appeal_plans_one_appeal_with_evidences_and_a_pdf_name():
    case = _case(**_tracked())
    (action,) = plan_actions(_decision("APPEAL"), case)
    assert action.kind == "appeal"
    assert action.summary == "Appeal with new evidence and evidence PDF"
    assert set(action.params) == {"evidences", "filename"}
    assert action.params["filename"] == f"appeal-{case.dispute_id}.pdf"
    assert action.params["evidences"][0]["evidence_type"] == "PROOF_OF_FULFILLMENT"


def test_appeal_needs_the_evidence_pdf():
    proposal = Proposal("p2", "PP-D-2000", "2026-10-14T00:00:00+00:00", _decision("APPEAL"),
                        [PlannedAction("appeal", "Appeal", {"evidences": [], "filename": "a.pdf"})], {})
    assert proposal.needs_evidence_pdf is True and proposal.to_dict()["has_evidence_document"] is True


# --- evidence lists ------------------------------------------------------------------------------------------------
def test_delivered_shipment_is_proof_of_fulfillment_with_tracking_info():
    (entry,) = _evidence_list(_tracked(carrier="USPS", number="9400111"))
    assert entry == {"evidence_type": "PROOF_OF_FULFILLMENT",
                     "evidence_info": {"tracking_info": [{"carrier_name": "USPS", "tracking_number": "9400111"}]},
                     "notes": "Seller evidence summary."}


def test_in_transit_tracked_shipment_is_proof_of_fulfillment():
    # Before this change an in-transit shipment was sent as OTHER; a shipment with tracking is proof of fulfillment.
    (entry,) = _evidence_list(_tracked(status="IN_TRANSIT"))
    assert entry["evidence_type"] == "PROOF_OF_FULFILLMENT"
    assert entry["evidence_info"]["tracking_info"] == [{"carrier_name": "UPS", "tracking_number": "1Z999"}]


def test_untracked_order_is_a_plain_other_entry_with_the_summary():
    assert _evidence_list(UNTRACKED) == [{"evidence_type": "OTHER", "notes": "Seller evidence summary."}]


def test_return_received_adds_proof_of_return_with_tracking_info():
    entries = _evidence_list({**_tracked(), **RETURN_RECEIVED})
    assert [e["evidence_type"] for e in entries] == ["PROOF_OF_FULFILLMENT", "PROOF_OF_RETURN"]
    assert entries[1] == {"evidence_type": "PROOF_OF_RETURN",
                          "evidence_info": {"tracking_info": [{"carrier_name": "FEDEX", "tracking_number": "7489"}]},
                          "notes": "Seller evidence summary."}


def test_return_alone_is_still_sent_when_nothing_was_tracked():
    entries = _evidence_list({**UNTRACKED, **RETURN_RECEIVED})
    assert [e["evidence_type"] for e in entries] == ["PROOF_OF_RETURN"]


def test_no_return_entry_when_the_return_is_not_received():
    entries = _evidence_list({**_tracked(), "return_received": False, "return_carrier": "FEDEX",
                              "return_tracking_number": "7489"})
    assert [e["evidence_type"] for e in entries] == ["PROOF_OF_FULFILLMENT"]


def test_unknown_carrier_goes_as_other_with_its_name():
    (entry,) = _evidence_list(_tracked(carrier="Royal Mail", number="RM123"))
    assert entry["evidence_info"]["tracking_info"] == [
        {"carrier_name": "OTHER", "carrier_name_other": "Royal Mail", "tracking_number": "RM123"}]


def test_unknown_return_carrier_goes_as_other_with_its_name():
    entries = _evidence_list({**UNTRACKED, "return_received": True, "return_carrier": "Evri",
                              "return_tracking_number": "E42"})
    assert entries[0]["evidence_info"]["tracking_info"] == [
        {"carrier_name": "OTHER", "carrier_name_other": "Evri", "tracking_number": "E42"}]


def test_appeal_sends_the_same_evidence_list_as_submit_evidence():
    facts = {**_tracked(), **RETURN_RECEIVED}
    (appeal,) = plan_actions(_decision("APPEAL"), _case(**facts))
    assert appeal.params["evidences"] == _evidence_list(facts)


def test_evidence_notes_are_trimmed_to_paypal_limit():
    entries = _evidence_list({**_tracked(), **RETURN_RECEIVED}, summary="s" * 2500)
    assert all(len(e["notes"]) == 2000 for e in entries)


def test_refund_proof_with_a_received_return_adds_proof_of_return():
    case = _case(refund_issued=True, refund_ids=["RF1"], **RETURN_RECEIVED)
    (action,) = plan_actions(_decision("SUBMIT_REFUND_PROOF", summary="Refund issued."), case)
    refund, ret = action.params["evidences"]
    assert refund["evidence_type"] == "PROOF_OF_REFUND" and refund["evidence_info"] == {"refund_ids": ["RF1"]}
    assert refund["notes"] == "Refund issued."
    assert ret["evidence_type"] == "PROOF_OF_RETURN"
    assert ret["evidence_info"]["tracking_info"] == [{"carrier_name": "FEDEX", "tracking_number": "7489"}]


def test_refund_proof_without_a_return_is_only_the_refund():
    case = _case(refund_issued=True, refund_ids=["RF1"], **UNTRACKED)
    (action,) = plan_actions(_decision("SUBMIT_REFUND_PROOF"), case)
    assert [e["evidence_type"] for e in action.params["evidences"]] == ["PROOF_OF_REFUND"]


# --- evidence PDF --------------------------------------------------------------------------------------------------
def test_evidence_pdf_builds_and_is_identical_across_calls_with_return_facts():
    case = _case(**{**_tracked(), **RETURN_RECEIVED})
    decision = _decision("APPEAL", summary="Delivered; return received.")
    first = build_evidence_pdf(case, decision)
    assert first.startswith(b"%PDF") and first == build_evidence_pdf(case, decision)


# --- approved text -------------------------------------------------------------------------------------------------
def test_approved_text_is_the_escalation_note_and_the_merchant_edit_replaces_it():
    actions = [{"kind": "escalate", "summary": "Escalate", "params": {"note": "Drafted note."}}]
    assert approved_text(actions, {"status": "approved"}) == "Drafted note."
    assert approved_text(actions, {"status": "edited", "edited_message": "Merchant edit."}) == "Merchant edit."


def test_approved_text_is_none_for_an_appeal_even_when_approved_or_edited():
    actions = [{"kind": "appeal", "summary": "Appeal", "params": {"evidences": [], "filename": "a.pdf"}}]
    assert approved_text(actions, {"status": "approved"}) is None
    assert approved_text(actions, {"status": "edited", "edited_message": "Merchant edit."}) is None
