"""Escalate and appeal end to end on the mock sandbox: analysis, the approval gate, the one PayPal write, the refusals.

No model: `force_rules=True`. The unit pieces are in the other test_*dispute_actions* files; this one runs them
together through `Runtime`, the way the dashboard does.
"""

import pytest

from rebuttal.approval import idempotency_key
from rebuttal.runtime import Runtime

ID = "PP-D-2000"


def escalatable_rt() -> Runtime:
    """A delivered NOT_RECEIVED inquiry the seller has already answered: the case the rules escalate."""
    rt = Runtime(seed_cases=["inr_delivered"], force_rules=True)
    rt.mock.disputes[ID].setdefault("messages", []).append(
        {"posted_by": "SELLER", "time_posted": "2026-10-05T10:00:00Z", "content": "It was delivered, see tracking."})
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
    assert rt.mock.disputes[ID]["dispute_life_cycle_stage"] == "CHARGEBACK"
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
