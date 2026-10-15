"""Offline checks for scripts/spike_shapes.py: the redaction that keeps personal data out of the fixtures, the summary
the findings use, and the refusal to run on the mock. No PayPal call and no model call is made."""

import copy

import httpx

from rebuttal.config import load_settings
from scripts.spike_shapes import main, redact, summarize

SAMPLE = {
    "dispute_id": "PP-R-TEST-1",
    "dispute_life_cycle_stage": "INQUIRY",
    "status": "WAITING_FOR_SELLER_RESPONSE",
    "dispute_amount": {"currency_code": "USD", "value": "48.00"},
    "links": [{"rel": "self", "href": "/v1/customer/disputes/PP-R-TEST-1", "method": "GET"},
              {"rel": "escalate", "href": "/v1/customer/disputes/PP-R-TEST-1/escalate", "method": "POST"}],
    "disputed_transactions": [{
        "seller_transaction_id": "CAPTURE1",
        "buyer": {"name": "Jane Buyer", "email_address": "jane@example.com", "payer_id": "PAYERID123",
                  "address": {"line1": "1 Main St", "city": "Springfield"}},
        "seller": {"name": "Shop Owner", "merchant_id": "MERCH1"},
    }],
    "messages": [{"posted_by": "BUYER", "content": "Write to jane@example.com please"}],
}


def test_redact_strips_the_email_buyer_name_payer_id_and_address_from_a_nested_sample():
    out = redact(SAMPLE)
    txn = out["disputed_transactions"][0]
    assert txn["buyer"] == {"name": "REDACTED", "email_address": "redacted@example.com", "payer_id": "REDACTED",
                            "address": {"redacted": True}}
    assert txn["seller"] == {"name": "REDACTED", "merchant_id": "REDACTED"}
    assert out["messages"][0]["content"] == "redacted@example.com"  # a free-text value holding an email
    flat = repr(out)
    assert "jane" not in flat and "Jane" not in flat and "PAYERID123" not in flat and "Springfield" not in flat


def test_redact_hides_every_address_object_the_sandbox_sends():
    sample = {"extensions": {"merchandize_dispute_properties": {"return_shipping_address": {
        "address_line_1": "200 Main St", "admin_area_2": "Springfield", "postal_code": "00000"}}}}
    out = redact(sample)
    assert out["extensions"]["merchandize_dispute_properties"]["return_shipping_address"] == {"redacted": True}
    assert "Springfield" not in repr(out)


def test_redact_keeps_dispute_id_amount_stage_and_link_rels():
    out = redact(SAMPLE)
    assert out["dispute_id"] == "PP-R-TEST-1"
    assert out["dispute_amount"] == {"currency_code": "USD", "value": "48.00"}
    assert out["dispute_life_cycle_stage"] == "INQUIRY"
    assert [link["rel"] for link in out["links"]] == ["self", "escalate"]
    assert out["links"][1]["href"] == "/v1/customer/disputes/PP-R-TEST-1/escalate"
    assert out["disputed_transactions"][0]["seller_transaction_id"] == "CAPTURE1"


def test_redact_does_not_mutate_its_input():
    before = copy.deepcopy(SAMPLE)
    redact(SAMPLE)
    assert SAMPLE == before


def test_summarize_returns_stage_status_sorted_rels_and_presence_flags():
    dispute = {"dispute_id": "PP-D-1", "dispute_life_cycle_stage": "CHARGEBACK", "status": "UNDER_REVIEW",
               "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
               "links": [{"rel": "self"}, {"rel": "escalate"}, {"rel": "appeal"}],
               "allowed_response_options": {}}
    s = summarize(dispute)
    assert s["stage"] == "CHARGEBACK" and s["status"] == "UNDER_REVIEW"
    assert s["link_rels"] == ["appeal", "escalate", "self"]
    assert s["has_allowed_response_options"] is True
    assert s["has_seller_response_due_date"] is False
    assert s["message_posted_by"] == [] and s["evidence_types"] == []


def test_summarize_reports_posted_by_and_evidence_types_without_values():
    s = summarize({**SAMPLE, "evidences": [{"evidence_type": "CREATE", "notes": "jane@example.com"}],
                   "seller_response_due_date": "2026-10-20T00:00:00Z"})
    assert s["message_posted_by"] == ["BUYER"]
    assert s["evidence_types"] == ["CREATE"]
    assert s["has_seller_response_due_date"] is True
    assert "jane" not in repr(s)


def test_survey_refuses_on_the_mock_without_any_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the refusal path must not make an HTTP request")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.Client, "request", no_network)
    assert load_settings().mock is True  # conftest pins REBUTTAL_MOCK=1
    assert main(["survey"]) == 2
