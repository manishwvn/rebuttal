"""Mock sandbox: dispute links, escalate, appeal and the evidence checks behind them (queue S2, piece p1-mock).

The link rel names, the appeal stage transition, the appeal multipart body and the evidence_info rules come from the
Disputes v1 OpenAPI spec only. VERIFY: not yet confirmed on the live sandbox.
"""

import json

import httpx
import pytest

from rebuttal.paypal.client import PayPalClient, PayPalError, permit_writes
from rebuttal.paypal.mock import MockPayPal

BASE = "https://api-m.sandbox.paypal.com"
DISPUTE = "PP-D-1"
APPEAL_PATH = f"/v1/customer/disputes/{DISPUTE}/appeal"
EVIDENCE = {"evidence_type": "OTHER", "notes": "Delivered per tracking"}
NOT_ALLOWED = [{"issue": "ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE"}]


def _dispute(stage="INQUIRY", status="WAITING_FOR_SELLER_RESPONSE", outcome=None) -> dict:
    dispute = {
        "dispute_id": DISPUTE,
        "create_time": "2026-10-01T00:00:00.000Z",
        "update_time": "2026-10-01T00:00:00.000Z",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
        "status": status,
        "dispute_life_cycle_stage": stage,
        "dispute_channel": "INTERNAL",
        "dispute_amount": {"currency_code": "USD", "value": "25.00"},
        "disputed_transactions": [{"seller_transaction_id": "CAP-1"}],
    }
    if outcome:
        dispute["dispute_outcome"] = {"outcome_code": outcome}
    return dispute


@pytest.fixture
def sandbox() -> MockPayPal:
    return MockPayPal()


@pytest.fixture
def client(sandbox: MockPayPal) -> PayPalClient:
    return PayPalClient(BASE, "id", "secret", transport=sandbox.transport())


def _post_evidence(sandbox: MockPayPal, action: str, evidences, request_id: str = "req-1") -> httpx.Response:
    """A provide-evidence or appeal request, built as the multipart body: an `input` JSON part plus a document."""
    files = {
        "input": (None, json.dumps({"evidences": evidences}), "application/json"),
        "file1": ("a.pdf", b"%PDF", "application/pdf"),
    }
    with httpx.Client(base_url=BASE, transport=sandbox.transport()) as http:
        return http.post(f"/v1/customer/disputes/{DISPUTE}/{action}",
                         headers={"Authorization": "Bearer x", "PayPal-Request-Id": request_id}, files=files)


def _post_appeal(sandbox: MockPayPal, evidences, request_id: str = "req-appeal-1") -> httpx.Response:
    return _post_evidence(sandbox, "appeal", evidences, request_id)


@pytest.mark.parametrize(("dispute", "rels"), [
    (_dispute(), ["self", "escalate"]),
    (_dispute(status="WAITING_FOR_BUYER_RESPONSE"), ["self"]),
    (_dispute(stage="CHARGEBACK", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"), ["self", "appeal"]),
    (_dispute(stage="PRE_ARBITRATION", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"), ["self", "appeal"]),
    (_dispute(stage="ARBITRATION", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"), ["self"]),
    (_dispute(stage="CHARGEBACK", status="RESOLVED", outcome="RESOLVED_SELLER_FAVOUR"), ["self"]),
    (_dispute(stage="CHARGEBACK", status="UNDER_REVIEW"), ["self"]),
    (_dispute(stage="CHARGEBACK"), ["self"]),
])
def test_links_follow_the_dispute_state(sandbox, client, dispute, rels):
    sandbox.add_dispute(dispute)
    got = client.get_dispute(DISPUTE)
    assert [link["rel"] for link in got["links"]] == rels
    assert "links" not in sandbox.disputes[DISPUTE]  # the stored dispute is not mutated


def test_escalate_link_points_at_the_escalate_path(sandbox, client):
    sandbox.add_dispute(_dispute())
    escalate = client.get_dispute(DISPUTE)["links"][1]
    assert escalate == {"href": f"/v1/customer/disputes/{DISPUTE}/escalate", "rel": "escalate", "method": "POST"}


def test_escalate_from_inquiry_moves_to_chargeback(sandbox, client):
    sandbox.add_dispute(_dispute())
    with permit_writes():
        client.escalate(DISPUTE, "Buyer wants a refund, we disagree")
    dispute = client.get_dispute(DISPUTE)
    assert dispute["dispute_life_cycle_stage"] == "CHARGEBACK"
    assert dispute["status"] == "UNDER_REVIEW"


def test_escalate_refused_once_past_inquiry(sandbox, client):
    sandbox.add_dispute(_dispute(stage="CHARGEBACK"))
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.escalate(DISPUTE, "Too late")
    assert err.value.status == 422
    assert err.value.body["details"] == NOT_ALLOWED


def test_escalate_refused_while_waiting_for_the_buyer(sandbox, client):
    sandbox.add_dispute(_dispute(status="WAITING_FOR_BUYER_RESPONSE"))
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.escalate(DISPUTE, "Buyer has not answered")
    assert err.value.status == 422
    assert err.value.body["details"] == NOT_ALLOWED
    assert sandbox.disputes[DISPUTE]["dispute_life_cycle_stage"] == "INQUIRY"


@pytest.mark.parametrize("note", ["", "x" * 2001])
def test_escalate_note_must_be_1_to_2000_characters(sandbox, client, note):
    sandbox.add_dispute(_dispute())
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.escalate(DISPUTE, note)
    assert err.value.status == 400
    assert err.value.body["details"] == [{"field": "/note", "location": "body", "issue": "INVALID_STRING_LENGTH"}]
    assert sandbox.disputes[DISPUTE]["dispute_life_cycle_stage"] == "INQUIRY"


@pytest.mark.parametrize(("stage", "next_stage"), [
    ("CHARGEBACK", "PRE_ARBITRATION"),
    ("PRE_ARBITRATION", "ARBITRATION"),
])
def test_appeal_on_a_lost_dispute_goes_back_under_review(sandbox, stage, next_stage):
    sandbox.add_dispute(_dispute(stage=stage, status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"))
    resp = _post_appeal(sandbox, [EVIDENCE])
    assert resp.status_code == 200
    assert resp.json()["links"][0]["rel"] == "self"
    dispute = sandbox.disputes[DISPUTE]
    assert dispute["dispute_life_cycle_stage"] == next_stage
    assert dispute["status"] == "UNDER_REVIEW"
    assert "dispute_outcome" not in dispute
    assert dispute["evidences"] == [EVIDENCE]
    assert sandbox.evidence_files[DISPUTE] == ["a.pdf"]
    assert sandbox.events[-1]["event_type"] == "CUSTOMER.DISPUTE.UPDATED"


@pytest.mark.parametrize(("stage", "status", "outcome"), [
    ("INQUIRY", "WAITING_FOR_SELLER_RESPONSE", None),  # open dispute
    ("CHARGEBACK", "RESOLVED", "RESOLVED_SELLER_FAVOUR"),  # seller won, nothing to appeal
    ("CHARGEBACK", "UNDER_REVIEW", "RESOLVED_BUYER_FAVOUR"),  # already contested
    ("ARBITRATION", "RESOLVED", "RESOLVED_BUYER_FAVOUR"),  # lost at the last stage
])
def test_appeal_refused_when_no_appeal_is_offered(sandbox, stage, status, outcome):
    sandbox.add_dispute(_dispute(stage=stage, status=status, outcome=outcome))
    resp = _post_appeal(sandbox, [EVIDENCE])
    assert resp.status_code == 422
    assert resp.json()["details"] == NOT_ALLOWED
    dispute = sandbox.disputes[DISPUTE]
    assert dispute["dispute_life_cycle_stage"] == stage
    assert dispute["status"] == status
    assert DISPUTE not in sandbox.evidence_files  # refused before the upload is recorded


def test_appeal_needs_at_least_one_evidence(sandbox):
    sandbox.add_dispute(_dispute(stage="CHARGEBACK", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"))
    resp = _post_appeal(sandbox, [])
    assert resp.status_code == 400
    assert resp.json()["details"] == [{"field": "/evidences", "location": "body", "issue": "INVALID_ARRAY_SIZE"}]
    assert sandbox.disputes[DISPUTE]["status"] == "RESOLVED"
    assert DISPUTE not in sandbox.evidence_files


def test_provide_evidence_proof_of_return_needs_evidence_info(sandbox, client):
    sandbox.add_dispute(_dispute())
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.provide_evidence(DISPUTE, [{"evidence_type": "PROOF_OF_RETURN", "notes": "returned"}])
    assert err.value.status == 400
    assert err.value.body["details"] == [{"field": "/evidences/0/evidence_info", "location": "body",
                                          "issue": "MISSING_REQUIRED_PARAMETER"}]
    assert sandbox.disputes[DISPUTE]["status"] == "WAITING_FOR_SELLER_RESPONSE"


def test_provide_evidence_tracking_other_needs_carrier_name_other(sandbox, client):
    sandbox.add_dispute(_dispute())
    evidence = {"evidence_type": "PROOF_OF_FULFILLMENT",
                "evidence_info": {"tracking_info": [{"carrier_name": "OTHER", "tracking_number": "TRK-1"}]}}
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.provide_evidence(DISPUTE, [evidence])
    assert err.value.status == 400
    assert err.value.body["details"] == [{"field": "/evidences/0/evidence_info/tracking_info", "location": "body",
                                          "issue": "MISSING_REQUIRED_PARAMETER"}]


def test_rejected_provide_evidence_keeps_the_filename_out_of_the_record(sandbox):
    sandbox.add_dispute(_dispute())
    resp = _post_evidence(sandbox, "provide-evidence", [{"evidence_type": "PROOF_OF_RETURN"}])
    assert resp.status_code == 400
    assert DISPUTE not in sandbox.evidence_files


def test_appeal_checks_evidence_info_too(sandbox):
    sandbox.add_dispute(_dispute(stage="CHARGEBACK", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"))
    resp = _post_appeal(sandbox, [{"evidence_type": "PROOF_OF_REFUND"}])
    assert resp.status_code == 400
    assert resp.json()["details"] == [{"field": "/evidences/0/evidence_info", "location": "body",
                                       "issue": "MISSING_REQUIRED_PARAMETER"}]
    assert sandbox.disputes[DISPUTE]["status"] == "RESOLVED"
    assert DISPUTE not in sandbox.evidence_files


def test_repeated_appeal_request_id_is_replayed_not_applied_twice(sandbox):
    sandbox.add_dispute(_dispute(stage="CHARGEBACK", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"))
    first = _post_appeal(sandbox, [EVIDENCE], request_id="req-1")
    second = _post_appeal(sandbox, [EVIDENCE], request_id="req-1")
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert sandbox.replayed == [(APPEAL_PATH, "req-1")]
    dispute = sandbox.disputes[DISPUTE]
    assert dispute["dispute_life_cycle_stage"] == "PRE_ARBITRATION"
    assert dispute["evidences"] == [EVIDENCE]


def test_interrupted_appeal_is_applied_then_answered_503(sandbox):
    sandbox.add_dispute(_dispute(stage="CHARGEBACK", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR"))
    sandbox.interrupt_next_write = True
    resp = _post_appeal(sandbox, [EVIDENCE])
    assert resp.status_code == 503
    assert sandbox.disputes[DISPUTE]["dispute_life_cycle_stage"] == "PRE_ARBITRATION"
    assert sandbox.interrupt_next_write is False
