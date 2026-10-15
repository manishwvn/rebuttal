"""Mock sandbox: dispute links, escalate, appeal and the evidence checks behind them (queue S2, piece p1-mock).

The escalate link and escalate behaviour are pinned to the live sandbox runs of 2026-10-14 (queue S3,
docs/sandbox-findings.md). The appeal link rel, the appeal stage transition, the appeal multipart body and the
evidence_info rules come from the Disputes v1 OpenAPI spec only. VERIFY: not yet confirmed on the live sandbox.
"""

import json
from pathlib import Path

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
    (_dispute(status="WAITING_FOR_BUYER_RESPONSE"), ["self", "escalate"]),  # seen live on a dispute with a seller offer
    (_dispute(status="UNDER_REVIEW"), ["self"]),
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


def test_escalate_keeps_the_inquiry_stage_and_records_the_note_as_other_evidence(sandbox, client):
    # Live (PP-R-HDU-10190454): stage INQUIRY, status UNDER_REVIEW, an OTHER entry from the seller, no escalate link.
    sandbox.add_dispute(_dispute())
    with permit_writes():
        client.escalate(DISPUTE, "Buyer wants a refund, we disagree")
    dispute = client.get_dispute(DISPUTE)
    assert dispute["dispute_life_cycle_stage"] == "INQUIRY"
    assert dispute["status"] == "UNDER_REVIEW"
    assert [(e["evidence_type"], e["source"], e["notes"]) for e in dispute["evidences"]] == [
        ("OTHER", "SUBMITTED_BY_SELLER", "Buyer wants a refund, we disagree")]
    assert [link["rel"] for link in dispute["links"]] == ["self"]
    assert "seller_response_due_date" not in dispute


@pytest.mark.parametrize("status", ["WAITING_FOR_BUYER_RESPONSE", "UNDER_REVIEW"])
def test_escalate_is_accepted_on_an_inquiry_in_those_statuses_too(sandbox, client, status):
    # Live: accepted in UNDER_REVIEW with the link absent, and offered while waiting for the buyer.
    sandbox.add_dispute(_dispute(status=status))
    with permit_writes():
        client.escalate(DISPUTE, "Please review")
    assert sandbox.disputes[DISPUTE]["status"] == "UNDER_REVIEW"
    assert sandbox.disputes[DISPUTE]["dispute_life_cycle_stage"] == "INQUIRY"


def test_escalate_refused_once_past_inquiry(sandbox, client):
    sandbox.add_dispute(_dispute(stage="CHARGEBACK"))
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.escalate(DISPUTE, "Too late")
    assert err.value.status == 422
    assert err.value.body["details"] == NOT_ALLOWED


def test_escalate_refused_on_a_resolved_inquiry(sandbox, client):
    sandbox.add_dispute(_dispute(status="RESOLVED", outcome="RESOLVED_SELLER_FAVOUR"))
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.escalate(DISPUTE, "Too late")
    assert err.value.status == 422
    assert "evidences" not in sandbox.disputes[DISPUTE]


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


@pytest.mark.parametrize("evidence_type", ["PROOF_OF_RETURN", "PROOF_OF_FULFILLMENT", "PROOF_OF_REFUND"])
def test_provide_evidence_proof_needs_evidence_info(sandbox, client, evidence_type):
    sandbox.add_dispute(_dispute())
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.provide_evidence(DISPUTE, [{"evidence_type": evidence_type, "notes": "proof"}])
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


@pytest.mark.parametrize("tracking", [{"carrier_name": "USPS"}, {"tracking_number": "TRK-1"}])
def test_provide_evidence_tracking_needs_carrier_and_number(sandbox, client, tracking):
    sandbox.add_dispute(_dispute())
    evidence = {"evidence_type": "PROOF_OF_FULFILLMENT", "evidence_info": {"tracking_info": [tracking]}}
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.provide_evidence(DISPUTE, [evidence])
    assert err.value.status == 400
    assert err.value.body["details"] == [{"field": "/evidences/0/evidence_info/tracking_info", "location": "body",
                                          "issue": "MISSING_REQUIRED_PARAMETER"}]
    assert sandbox.disputes[DISPUTE]["status"] == "WAITING_FOR_SELLER_RESPONSE"
    assert DISPUTE not in sandbox.evidence_files


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


def test_a_second_offer_is_refused_once_the_first_left_the_dispute_waiting_for_the_buyer(sandbox, client):
    sandbox.add_dispute(_dispute())
    with permit_writes():
        client.make_offer(DISPUTE, note="x", offer_type="REFUND")
        assert sandbox.disputes[DISPUTE]["status"] == "WAITING_FOR_BUYER_RESPONSE"
        with pytest.raises(PayPalError) as err:
            client.make_offer(DISPUTE, note="again", offer_type="REFUND")
    assert err.value.status == 400
    assert {"issue": "INVALID_OFFER_TYPE"} in err.value.body["details"]
    assert len(sandbox.disputes[DISPUTE]["offer"]["history"]) == 1


def test_waiting_for_the_buyer_lists_accept_claim_refund_only_as_the_live_fixture_does(sandbox, client):
    # Live (PP-R-GBK-10190434): in WAITING_FOR_BUYER_RESPONSE the options were {accept_claim: {accept_claim_types: [REFUND]}}.
    live = json.loads((Path(__file__).parent / "fixtures" / "sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json").read_text())
    sandbox.add_dispute({**_dispute(), "seller_response_due_date": "2026-10-11T00:00:00.000Z"})
    with permit_writes():
        client.make_offer(DISPUTE, note="x", offer_type="REFUND")
    got = client.get_dispute(DISPUTE)
    assert got["status"] == live["status"] == "WAITING_FOR_BUYER_RESPONSE"
    assert got["allowed_response_options"] == live["allowed_response_options"]
    assert "seller_response_due_date" not in got


def test_options_return_when_the_sandbox_hands_the_dispute_back_to_the_seller(sandbox, client):
    sandbox.add_dispute(_dispute())
    with permit_writes():
        client.send_message(DISPUTE, "Hello buyer")
    assert sandbox.disputes[DISPUTE]["status"] == "UNDER_REVIEW"
    assert "allowed_response_options" not in sandbox.disputes[DISPUTE]
    with httpx.Client(base_url=BASE, transport=sandbox.transport()) as http:
        resp = http.post(f"/v1/customer/disputes/{DISPUTE}/require-evidence",
                         headers={"Authorization": "Bearer x"}, json={"action": "SELLER_EVIDENCE"})
    assert resp.status_code == 200
    options = sandbox.disputes[DISPUTE]["allowed_response_options"]
    assert "REFUND" in options["make_offer"]["offer_types"]
    with permit_writes():
        client.make_offer(DISPUTE, note="x", offer_type="REFUND")
    assert sandbox.disputes[DISPUTE]["status"] == "WAITING_FOR_BUYER_RESPONSE"


def test_a_message_leaves_the_inquiry_under_review_and_drops_the_seller_deadline_and_options(sandbox, client):
    # Live (PP-R-HDU-10190454): after a seller message the status was UNDER_REVIEW, and the escalate link,
    # allowed_response_options and seller_response_due_date were gone.
    sandbox.add_dispute({**_dispute(), "seller_response_due_date": "2026-10-11T00:00:00.000Z"})
    with permit_writes():
        client.send_message(DISPUTE, "Your tracking: TRK-1")
    got = client.get_dispute(DISPUTE)
    assert got["status"] == "UNDER_REVIEW"
    assert [link["rel"] for link in got["links"]] == ["self"]
    assert "allowed_response_options" not in got and "seller_response_due_date" not in got
    assert got["messages"][-1]["posted_by"] == "SELLER"


def test_proof_of_return_is_refused_on_a_not_received_inquiry_with_the_live_issue_code(sandbox, client):
    # Live (PP-R-GFH-10190453): HTTP 400 INVALID_REQUEST / EVIDENCE_TYPE_IS_NOT_ALLOWED, nothing changed.
    sandbox.add_dispute({**_dispute(), "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"})
    evidence = {"evidence_type": "PROOF_OF_RETURN",
                "evidence_info": {"tracking_info": [{"carrier_name": "USPS", "tracking_number": "TRK-1"}]}}
    with permit_writes(), pytest.raises(PayPalError) as err:
        client.provide_evidence(DISPUTE, [evidence])
    assert err.value.status == 400
    assert err.value.body["name"] == "INVALID_REQUEST"
    assert err.value.body["details"] == [{"issue": "EVIDENCE_TYPE_IS_NOT_ALLOWED"}]
    assert sandbox.disputes[DISPUTE]["status"] == "WAITING_FOR_SELLER_RESPONSE"
    assert DISPUTE not in sandbox.evidence_files


def test_proof_of_return_is_still_accepted_on_a_not_as_described_inquiry(sandbox, client):
    sandbox.add_dispute(_dispute())
    evidence = {"evidence_type": "PROOF_OF_RETURN",
                "evidence_info": {"tracking_info": [{"carrier_name": "USPS", "tracking_number": "TRK-1"}]}}
    with permit_writes():
        client.provide_evidence(DISPUTE, [evidence])
    assert sandbox.disputes[DISPUTE]["status"] == "UNDER_REVIEW"
