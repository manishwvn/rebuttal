"""Escalate and appeal: the facts that gate them, and the approval gate's paths for them.

The execute tests use a stub client that records calls and hand-made disputes, never the mock. The execute state is
built from a real analysis of the seeded case, so its shape is the graph's own. The gather defaults read the seeded
mock dispute, as the other gather tests do.
"""

from types import SimpleNamespace

import pytest

from rebuttal import approval
from rebuttal.agent import facts
from rebuttal.agent.facts import dispute_actions, gather
from rebuttal.agent.toolkit import ReadOnlyToolkit
from rebuttal.approval import (
    ApprovalError,
    already_applied,
    execute_action,
    idempotency_key,
    make_execute_node,
    not_allowed_now,
)
from rebuttal.audit import AuditLog
from rebuttal.runtime import Runtime
from rebuttal.scenarios import DEMO_NOW, build_order, load_cases

EVIDENCES = [{"evidence_type": "PROOF_OF_FULFILLMENT", "notes": "Shipped and delivered."}]
ESCALATE = {"kind": "escalate", "params": {"note": "Please review."}}
APPEAL = {"kind": "appeal", "params": {"evidences": EVIDENCES, "filename": "appeal.pdf"}}


def link(rel: str) -> dict:
    return {"href": f"https://api-m.sandbox.paypal.com/v1/customer/disputes/PP-D-9/{rel}", "rel": rel,
            "method": "POST"}


def with_links(stage: str, *rels: str, status: str = "WAITING_FOR_SELLER_RESPONSE") -> dict:
    return {"dispute_life_cycle_stage": stage, "status": status, "links": [link(rel) for rel in rels]}


class StubClient:
    """Records the calls the execute node makes. It is not the mock and never talks to PayPal."""

    def __init__(self, dispute: dict):
        self.dispute = dispute
        self.calls: list[tuple] = []

    def get_dispute(self, dispute_id: str) -> dict:
        self.calls.append(("get_dispute", dispute_id))
        return self.dispute

    def escalate(self, dispute_id: str, note: str, *, request_id: str | None = None) -> dict:
        self.calls.append(("escalate", dispute_id, note, request_id))
        return {"escalated": True}

    def appeal(self, dispute_id: str, evidences: list, files=(), *, request_id: str | None = None) -> dict:
        self.calls.append(("appeal", dispute_id, evidences, list(files), request_id))
        return {"appealed": True}

    def calls_to(self, method: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == method]


@pytest.fixture
def analyzed_rt():
    rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
    rt.analyze("PP-D-2000")
    return rt


def approved(rt: Runtime, *actions: dict, stage: str | None = None) -> dict:
    """The graph state the execute node gets after a human approved the real proposal for PP-D-2000."""
    base = rt.agent.snapshot("PP-D-2000").values
    case = base["case"] if stage is None else {**base["case"], "stage": stage}
    return {**base, "case": case, "actions": list(actions),
            "approval": {"status": "approved", "by": "t", "reason": "", "edited_message": None}}


def without_links(monkeypatch) -> None:
    """Strip the HATEOAS links from the seeded dispute as the toolkit reads it."""
    read = ReadOnlyToolkit.call

    def strip(self, method, params):
        result = read(self, method, params)
        return {k: v for k, v in result.items() if k != "links"} if method == "get_dispute" else result

    monkeypatch.setattr(ReadOnlyToolkit, "call", strip)


# ------------------------------------------------------------------------------------------ dispute_actions
def test_escalate_is_offered_only_at_inquiry_with_the_escalate_link():
    assert dispute_actions(with_links("INQUIRY", "escalate")) == {"can_escalate": True, "can_appeal": False}
    assert dispute_actions(with_links("CHARGEBACK", "escalate")) == {"can_escalate": False, "can_appeal": False}


@pytest.mark.parametrize("dispute", [
    {"dispute_life_cycle_stage": "INQUIRY"},  # no links key
    {"dispute_life_cycle_stage": "INQUIRY", "links": None},
    with_links("INQUIRY", "self"),  # links that are not escalate or appeal
])
def test_missing_or_unrelated_links_mean_neither_action(dispute):
    assert dispute_actions(dispute) == {"can_escalate": False, "can_appeal": False}


def test_the_appeal_link_alone_allows_an_appeal_at_any_stage():
    assert dispute_actions(with_links("CHARGEBACK", "appeal")) == {"can_escalate": False, "can_appeal": True}


def test_both_links_at_inquiry_allow_both_actions():
    assert dispute_actions(with_links("INQUIRY", "escalate", "appeal")) == {"can_escalate": True, "can_appeal": True}


# ------------------------------------------------------------------------------------------ gather facts
@pytest.fixture
def rt():
    return Runtime(seed_cases=["inr_delivered"], force_rules=True)


def test_a_seeded_dispute_offers_neither_action_and_has_no_seller_reply(rt, monkeypatch):
    without_links(monkeypatch)  # the mock's own links are not what this test is about
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["can_escalate"] is False
    assert case.facts["can_appeal"] is False
    assert case.facts["seller_already_responded"] is False


def test_gather_reads_the_links_and_seller_replies_of_the_dispute(rt, monkeypatch):
    read = ReadOnlyToolkit.call

    def dispute_with_links_and_a_seller_reply(self, method, params):
        result = read(self, method, params)
        if method == "get_dispute":
            result = {**result, "links": [link("escalate"), link("appeal")],
                      "messages": [*result.get("messages", []),
                                   {"posted_by": "SELLER", "content": "We shipped it on the 3rd."}]}
        return result

    monkeypatch.setattr(ReadOnlyToolkit, "call", dispute_with_links_and_a_seller_reply)
    case = gather("PP-D-2000", rt.client, rt.store, DEMO_NOW)
    assert case.facts["can_escalate"] is True  # the seeded dispute is at INQUIRY
    assert case.facts["can_appeal"] is True
    assert case.facts["seller_already_responded"] is True


def test_a_return_shipment_adds_its_carrier_and_tracking_number_to_the_facts():
    case = next(c for c in load_cases() if c["id"] == "cnp_owed")  # has a return_shipment
    order = build_order(case, index=0, invoice="JO-3000", capture_id="CAPTURE", order_id=None, now=DEMO_NOW,
                        buyer=("Priya Shah", "priya.s@example.com"))
    f = facts._compute_facts(order, None, None, case["item"]["price"], DEMO_NOW, [])
    assert f["return_carrier"] == "USPS"
    assert f["return_tracking_number"] == "9400111899223377001122"
    assert f["return_received"] is True

    plain = next(c for c in load_cases() if c["id"] == "inr_delivered")  # no return_shipment
    order = build_order(plain, index=0, invoice="JO-3000", capture_id="CAPTURE", order_id=None, now=DEMO_NOW,
                        buyer=("Priya Shah", "priya.s@example.com"))
    f = facts._compute_facts(order, None, None, plain["item"]["price"], DEMO_NOW, [])
    assert "return_carrier" not in f and "return_tracking_number" not in f


# ------------------------------------------------------------------------------------------ execute_action
def test_execute_action_routes_escalate_and_appeal_with_the_request_id_and_the_pdf_only_for_appeal():
    client = StubClient({})
    assert execute_action(client, "PP-D-9", ESCALATE, "KEY-1", b"%PDF") == {"escalated": True}
    execute_action(client, "PP-D-9", APPEAL, "KEY-2", b"%PDF-1.4")
    execute_action(client, "PP-D-9", APPEAL, "KEY-3", None)
    assert client.calls == [
        ("escalate", "PP-D-9", "Please review.", "KEY-1"),
        ("appeal", "PP-D-9", EVIDENCES, [("appeal.pdf", b"%PDF-1.4", "application/pdf")], "KEY-2"),
        ("appeal", "PP-D-9", EVIDENCES, [], "KEY-3"),
    ]


# ------------------------------------------------------------------------------------------ not_allowed_now
def test_not_allowed_now_refuses_escalate_once_the_inquiry_escalate_link_is_gone():
    assert not_allowed_now(with_links("INQUIRY", "escalate"), ESCALATE) is None
    assert "escalating" in not_allowed_now(with_links("CHARGEBACK", "escalate"), ESCALATE)
    assert "escalating" in not_allowed_now({"dispute_life_cycle_stage": "INQUIRY"}, ESCALATE)
    # the link is also offered while the buyer is to respond, but escalate is only for the seller's turn
    waiting_buyer = with_links("INQUIRY", "escalate", status="WAITING_FOR_BUYER_RESPONSE")
    assert "escalating" in not_allowed_now(waiting_buyer, ESCALATE)
    # PayPal's options list does not stand in for the escalate link
    options = {"dispute_life_cycle_stage": "INQUIRY", "allowed_response_options": {"accept_claim": {}}}
    assert "escalating" in not_allowed_now(options, ESCALATE)


def test_not_allowed_now_refuses_appeal_once_the_appeal_link_is_gone():
    assert not_allowed_now(with_links("CHARGEBACK", "appeal"), APPEAL) is None
    assert "appealing" in not_allowed_now(with_links("CHARGEBACK", "escalate"), APPEAL)


def test_not_allowed_now_still_checks_offers_and_claims_against_allowed_response_options():
    options = {"allowed_response_options": {"make_offer": {"offer_types": ["REFUND"]}}}

    def offer(offer_type: str) -> dict:
        return {"kind": "make_offer", "params": {"offer_type": offer_type, "note": "x"}}

    accept = {"kind": "accept_claim", "params": {"note": "x"}}
    assert not_allowed_now(options, offer("REFUND")) is None
    assert "REFUND_WITH_RETURN" in not_allowed_now(options, offer("REFUND_WITH_RETURN"))
    assert "accepting this claim" in not_allowed_now(options, accept)
    assert not_allowed_now({"dispute_life_cycle_stage": "INQUIRY"}, accept) is None


# ------------------------------------------------------------------------------------------ already_applied
def test_already_applied_does_not_recognise_escalate_or_appeal_even_after_the_stage_moved():
    # An INQUIRY to CHARGEBACK move also happens when the buyer escalates, so it cannot prove this action landed.
    moved = {"dispute_life_cycle_stage": "CHARGEBACK", "links": [link("self")]}
    assert already_applied(moved, ESCALATE, {"stage": "INQUIRY"}) is False
    assert already_applied(moved, ESCALATE, {"stage": "CHARGEBACK"}) is False
    assert already_applied(with_links("INQUIRY", "escalate"), ESCALATE, {"stage": "INQUIRY"}) is False
    assert already_applied(moved, APPEAL, {"stage": "INQUIRY"}) is False


# ------------------------------------------------------------------------------------------ execute node
def test_execute_sends_an_approved_escalate_once_under_its_idempotency_key(analyzed_rt):
    client = StubClient(with_links("INQUIRY", "escalate"))
    state = approved(analyzed_rt, ESCALATE, stage="INQUIRY")
    out = make_execute_node(client, AuditLog())(state)
    key = idempotency_key(state["proposal_id"], 0, "escalate")
    assert out["status"] == "EXECUTED"
    assert out["result"] == [{"action": "escalate", "ok": True, "response": {"escalated": True},
                              "idempotency_key": key}]
    assert client.calls_to("escalate") == [("escalate", "PP-D-2000", "Please review.", key)]


def test_execute_fails_without_sending_when_the_dispute_has_no_escalate_link(analyzed_rt):
    client = StubClient({"dispute_life_cycle_stage": "INQUIRY"})
    state = approved(analyzed_rt, ESCALATE, stage="INQUIRY")
    out = make_execute_node(client, AuditLog())(state)
    result = out["result"][0]
    assert out["status"] == "FAILED"
    assert result["ok"] is False and result["sent"] is False
    assert result["idempotency_key"] == idempotency_key(state["proposal_id"], 0, "escalate")
    assert "escalating" in result["error"] and "may already have been sent" in result["error"]
    assert client.calls_to("escalate") == []


def test_execute_refuses_an_escalate_once_the_dispute_waits_for_the_buyer(analyzed_rt):
    client = StubClient(with_links("INQUIRY", "escalate", status="WAITING_FOR_BUYER_RESPONSE"))
    state = approved(analyzed_rt, ESCALATE, stage="INQUIRY")
    out = make_execute_node(client, AuditLog())(state)
    result = out["result"][0]
    assert out["status"] == "FAILED"
    assert result["ok"] is False and result["sent"] is False and "escalating" in result["error"]
    assert client.calls_to("escalate") == []


def test_execute_does_not_reconcile_an_escalate_whose_dispute_moved_to_chargeback(analyzed_rt):
    """A dispute that moved from INQUIRY to CHARGEBACK may be a buyer's own escalation, so the node must not claim
    this send landed. It refuses instead, and sends nothing."""
    client = StubClient({"dispute_life_cycle_stage": "CHARGEBACK", "links": [link("self")]})
    state = approved(analyzed_rt, ESCALATE, stage="INQUIRY")
    out = make_execute_node(client, AuditLog())(state)
    result = out["result"][0]
    assert out["status"] == "FAILED"
    assert result["ok"] is False and result["sent"] is False and "reconciled" not in result
    assert "may already have been sent" in result["error"]
    assert client.calls_to("escalate") == []


def test_execute_builds_the_evidence_pdf_for_an_appeal_and_attaches_it(analyzed_rt, monkeypatch):
    built = []

    def fake_pdf(case, decision):
        built.append(case.dispute_id)
        return b"%PDF-appeal"

    monkeypatch.setattr(approval, "build_evidence_pdf", fake_pdf)
    client = StubClient(with_links("CHARGEBACK", "appeal"))
    state = approved(analyzed_rt, APPEAL)
    out = make_execute_node(client, AuditLog())(state)
    key = idempotency_key(state["proposal_id"], 0, "appeal")
    assert built == ["PP-D-2000"] and out["status"] == "EXECUTED"
    assert client.calls_to("appeal") == [
        ("appeal", "PP-D-2000", EVIDENCES, [("appeal.pdf", b"%PDF-appeal", "application/pdf")], key)]


def test_an_edit_on_an_appeal_proposal_is_refused_before_it_resumes(analyzed_rt, monkeypatch):
    """An appeal has no buyer-facing text, so an edit cannot apply to it. The refusal happens before the graph
    resumes, so the paused proposal stays paused and nothing is sent."""
    real = analyzed_rt.agent.proposal("PP-D-2000")
    appeal_only = SimpleNamespace(id=real.id, status="PENDING",
                                  actions=[SimpleNamespace(kind="appeal", params=APPEAL["params"])])
    monkeypatch.setattr(analyzed_rt.agent, "proposal", lambda *args, **kwargs: appeal_only)
    resumed = []
    monkeypatch.setattr(analyzed_rt.agent.graph, "invoke", lambda *args, **kwargs: resumed.append(args))
    with pytest.raises(ApprovalError, match="no buyer-facing message"):
        analyzed_rt.approvals.approve(real.id, edited_message="Please look again.")
    assert resumed == [] and analyzed_rt.mock.write_calls() == []
