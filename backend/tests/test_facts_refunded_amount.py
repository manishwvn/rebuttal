"""refunded_amount fact: the sum of refunds, so a partial refund is not read as a full one (queue R15, piece p1)."""

from rebuttal.agent.facts import _compute_facts, gather
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW


def _gather(case_id):
    rt = Runtime(seed_cases=[case_id], force_rules=True)
    return gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)


def test_refunded_amount_is_the_refund_total_when_refunded():
    case = _gather("cnp_refunded")
    assert case.facts["refund_issued"] is True
    assert case.facts["refunded_amount"] == 54.0
    assert case.facts["refunded_amount"] == sum(r["amount"] for r in case.order.refunds)


def test_refunded_amount_is_zero_without_a_refund():
    case = _gather("inr_no_tracking")
    assert case.order.refunds == []
    assert case.facts["refund_issued"] is False
    assert case.facts["refunded_amount"] == 0.0


def test_refunded_amount_sums_several_refunds():
    case = _gather("inr_no_tracking")
    case.order.refunds.append({"refund_id": "RF0001", "amount": 10.10, "at": "2026-10-01T00:00:00Z"})
    case.order.refunds.append({"refund_id": "RF0002", "amount": 20.20, "at": "2026-10-02T00:00:00Z"})
    facts = _compute_facts(case.order, None, None, case.amount, DEMO_NOW, case.buyer_messages)
    assert facts["refunded_amount"] == 30.3
    assert facts["refund_ids"] == ["RF0001", "RF0002"]
