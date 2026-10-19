"""Escalate and appeal end to end on the mock sandbox: analysis, the approval gate, the one PayPal write, the refusals.

No model: `force_rules=True`. The unit pieces are in the other test_*dispute_actions* files; this one runs them
together through `Runtime`, the way the dashboard does.
"""

import pytest

from rebuttal.agent.facts import dispute_actions
from rebuttal.approval import idempotency_key
from rebuttal.paypal.client import permit_writes
from rebuttal.runtime import Runtime

ID = "PP-D-2000"


def escalatable_rt() -> Runtime:
    """A delivered NOT_RECEIVED inquiry the seller has already answered and is waiting on the seller again: the case
    the rules escalate. The mock moves the dispute to UNDER_REVIEW after the message, as the real sandbox did, and
    the sandbox-only require-evidence stands in for the buyer's reply that brings it back to the seller.
    VERIFY: whether a real buyer reply returns an INQUIRY to WAITING_FOR_SELLER_RESPONSE: S3 could not test it (the
    second sandbox account is not the buyer on the existing disputes; docs/sandbox-findings.md item 5)."""
    rt = Runtime(seed_cases=["inr_delivered"], force_rules=True)
    with permit_writes():
        rt.client.send_message(ID, "It was delivered, see tracking.")
        rt.client.require_evidence(ID)
    assert rt.mock.disputes[ID]["status"] == "WAITING_FOR_SELLER_RESPONSE"
    rt.mock.calls.clear()  # the setup writes are not the proposal's
    rt.mock.request_ids.clear()
    return rt


def lost_chargeback_rt() -> Runtime:
    """A chargeback PayPal resolved for the buyer: the dispute shows the appeal link."""
    rt = Runtime(seed_cases=["inr_delivered_claim"], force_rules=True)
    dispute = rt.mock.disputes[ID]
    dispute.update(status="RESOLVED", dispute_life_cycle_stage="CHARGEBACK",
                   dispute_outcome={"outcome_code": "RESOLVED_BUYER_FAVOUR"})
    return rt


def test_a_seller_reply_on_a_delivered_inquiry_is_escalated_once_approved():
    rt = escalatable_rt()
    proposal = rt.analyze(ID)
    assert proposal.decision.resolution == "ESCALATE"
    assert [a.kind for a in proposal.actions] == ["escalate"]
    assert rt.mock.write_calls() == []  # nothing is sent before the merchant decides

    done = rt.approvals.approve(proposal.id)

    assert done.status == "EXECUTED" and done.result[0]["ok"]
    # As the live sandbox did (PP-R-HDU-10190454): the stage stays INQUIRY, the status is UNDER_REVIEW, and the note
    # is recorded as an OTHER evidence entry. The escalate link is gone, so the dispute cannot be escalated again.
    assert rt.mock.disputes[ID]["dispute_life_cycle_stage"] == "INQUIRY"
    assert rt.mock.disputes[ID]["status"] == "UNDER_REVIEW"
    assert rt.mock.disputes[ID]["evidences"][-1]["evidence_type"] == "OTHER"
    assert dispute_actions(rt.client.get_dispute(ID))["can_escalate"] is False
    assert rt.mock.write_calls() == [("POST", f"/v1/customer/disputes/{ID}/escalate")]
    assert rt.mock.request_ids == [(f"/v1/customer/disputes/{ID}/escalate",
                                    idempotency_key(proposal.id, 0, "escalate"))]


def test_a_lost_chargeback_is_appealed_with_the_evidence_pdf_once_approved():
    rt = lost_chargeback_rt()
    proposal = rt.analyze(ID)
    assert proposal.decision.resolution == "APPEAL"
    assert [a.kind for a in proposal.actions] == ["appeal"] and proposal.needs_evidence_pdf
    assert rt.mock.write_calls() == []

    done = rt.approvals.approve(proposal.id)

    assert done.status == "EXECUTED" and done.result[0]["ok"]
    assert rt.mock.disputes[ID]["dispute_life_cycle_stage"] == "PRE_ARBITRATION"
    assert rt.mock.disputes[ID]["status"] == "UNDER_REVIEW"
    assert rt.mock.evidence_files[ID] == [proposal.actions[0].params["filename"]]
    assert rt.mock.write_calls() == [("POST", f"/v1/customer/disputes/{ID}/appeal")]


@pytest.mark.parametrize("build,moved", [
    (escalatable_rt, {"status": "UNDER_REVIEW"}),
    (lost_chargeback_rt, {"status": "UNDER_REVIEW", "dispute_life_cycle_stage": "PRE_ARBITRATION"}),
])
def test_a_dispute_that_moved_on_before_approval_sends_nothing(build, moved):
    rt = build()
    proposal = rt.analyze(ID)
    rt.mock.disputes[ID].update(moved)

    done = rt.approvals.approve(proposal.id)

    assert done.status == "FAILED" and done.result[0]["sent"] is False
    assert rt.mock.write_calls() == []


@pytest.mark.parametrize("build", [escalatable_rt, lost_chargeback_rt])
def test_a_rejected_proposal_writes_nothing(build):
    rt = build()
    proposal = rt.analyze(ID)

    assert rt.approvals.reject(proposal.id, reason="not now").status == "REJECTED"
    assert rt.mock.write_calls() == []


def test_a_dispute_moved_to_chargeback_between_gather_and_guard_blocks_escalate():
    """The guard re-reads the dispute and refreshes stage and the can_escalate fact, not only the allowed options."""
    rt = escalatable_rt()
    rules_decide = rt.agent.reasoner.decide

    def decide_then_move(case, config=None):
        decision = rules_decide(case, config)
        assert decision.resolution == "ESCALATE" and case.stage == "INQUIRY"
        rt.mock.disputes[ID]["dispute_life_cycle_stage"] = "CHARGEBACK"  # the buyer went to their bank meanwhile
        return decision

    rt.agent.reasoner.decide = decide_then_move
    proposal = rt.analyze(ID)

    assert proposal.decision.resolution != "ESCALATE"
    assert all(a.kind != "escalate" for a in proposal.actions)
    assert rt.mock.write_calls() == []
