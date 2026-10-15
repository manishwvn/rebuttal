"""Offline checks for scripts/spike_shapes.py: the redaction that keeps personal data out of the fixtures, the summary
the findings use, the link prechecks, the audit trail and the refusal to overwrite a record. The PayPal client is a
fake, and no model call is made."""

import copy
import json

import httpx
import pytest

from rebuttal.audit import AuditLog
from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalError
from scripts import spike_shapes
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


def test_survey_never_opens_the_audit_log_even_with_a_database(monkeypatch):
    # survey only reads, so it must not touch the online database that DATABASE_URL points at.
    class FakeSettings:
        mock = False
        client_id = "id"
        client_secret = "secret"
        base_url = "https://api-m.sandbox.paypal.com"
        audit_path = "unused.jsonl"
        database_url = "postgresql://example.invalid/db"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def list_disputes(self, page_size):
            return []

        def close(self):
            pass

    def audit_must_not_open(*args, **kwargs):
        raise AssertionError("survey must not open the audit log")

    monkeypatch.setattr(spike_shapes, "load_settings", lambda: FakeSettings())
    monkeypatch.setattr(spike_shapes, "PayPalClient", FakeClient)
    monkeypatch.setattr(spike_shapes, "AuditLog", audit_must_not_open)
    assert main(["survey"]) == 0


class FakePP:
    """Stands in for PayPalClient. Each write is recorded as a tuple, and the queued PayPalErrors are raised, in
    order, before a write succeeds."""

    def __init__(self, dispute: dict, errors: list[PayPalError] | None = None):
        self.dispute = dispute
        self.errors = list(errors or [])
        self.writes: list[tuple] = []

    def get_dispute(self, dispute_id: str) -> dict:
        return copy.deepcopy(self.dispute)

    def _write(self, *call):
        self.writes.append(call)
        if self.errors:
            raise self.errors.pop(0)
        return {"links": []}

    def escalate(self, dispute_id, note, *, request_id=None):
        return self._write("escalate", dispute_id, request_id)

    def send_message(self, dispute_id, message, *, request_id=None):
        return self._write("send_message", dispute_id, request_id)

    def provide_evidence(self, dispute_id, evidences, files=(), *, request_id=None):
        return self._write("provide_evidence", dispute_id, request_id)

    def appeal(self, dispute_id, evidences, files=(), *, request_id=None):
        return self._write("appeal", dispute_id, request_id)

    def _request(self, method, path, *, request_id=None, **kw):
        return self._write("_request", method, path, kw, request_id)


def dispute_at(stage: str, status: str, *rels: str) -> dict:
    return {"dispute_id": "PP-R-TEST-1", "dispute_life_cycle_stage": stage, "status": status,
            "links": [{"rel": "self"}, *({"rel": rel} for rel in rels)]}


@pytest.fixture
def records_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(spike_shapes, "FIXTURES", tmp_path)
    return tmp_path


def test_escalate_sends_nothing_without_an_escalate_link(records_dir, capsys):
    pp = FakePP(dispute_at("INQUIRY", "WAITING_FOR_SELLER_RESPONSE"))
    audit = AuditLog()
    assert spike_shapes.escalate(pp, audit, "PP-R-TEST-1") == 1
    assert pp.writes == [] and audit.records == []
    assert "offers no escalate link" in capsys.readouterr().out


def test_escalate_sends_nothing_outside_an_inquiry(records_dir):
    pp = FakePP(dispute_at("CHARGEBACK", "UNDER_REVIEW", "escalate"))
    assert spike_shapes.escalate(pp, AuditLog(), "PP-R-TEST-1") == 1
    assert pp.writes == []


def test_escalate_refuses_to_overwrite_an_existing_record_before_sending(records_dir):
    existing = records_dir / "sandbox_escalate_response_PP-R-TEST-1.json"
    existing.write_text("{}")
    pp = FakePP(dispute_at("INQUIRY", "UNDER_REVIEW", "escalate"))
    assert spike_shapes.escalate(pp, AuditLog(), "PP-R-TEST-1") == 1
    assert pp.writes == [] and existing.read_text() == "{}"


def test_escalate_audits_the_request_id_it_sends_and_saves_a_redacted_record(records_dir):
    pp = FakePP(dispute_at("INQUIRY", "UNDER_REVIEW", "escalate"))
    audit = AuditLog()
    assert spike_shapes.escalate(pp, audit, "PP-R-TEST-1") == 0
    assert [w[0] for w in pp.writes] == ["escalate"]
    assert [r["step"] for r in audit.records] == ["spike.escalate.request", "spike.escalate.result"]
    sent_id = pp.writes[0][2]
    assert sent_id and all(r["detail"]["request_id"] == sent_id for r in audit.records)
    saved = json.loads((records_dir / "sandbox_escalate_response_PP-R-TEST-1.json").read_text())
    assert saved["first_attempt"]["ok"] is True
    assert saved["before"]["link_rels"] == ["escalate", "self"]
    assert "retry_with_buyer_escalation_reason" not in saved
    assert (records_dir / "sandbox_dispute_after_escalate_PP-R-TEST-1.json").exists()


def test_escalate_retries_once_with_buyer_escalation_reason_when_paypal_asks_for_it(records_dir):
    body = {"details": [{"field": "buyer_escalation_reason", "issue": "MISSING_REQUIRED_PARAMETER"}]}
    pp = FakePP(dispute_at("INQUIRY", "UNDER_REVIEW", "escalate"), errors=[PayPalError(400, body)])
    audit = AuditLog()
    assert spike_shapes.escalate(pp, audit, "PP-R-TEST-1") == 0
    assert [w[0] for w in pp.writes] == ["escalate", "_request"]
    assert pp.writes[1][1:4] == ("POST", "/v1/customer/disputes/PP-R-TEST-1/escalate",
                                 {"json": {"note": spike_shapes.NOTE, "buyer_escalation_reason": "OTHER"}})
    assert len(audit.records) == 4  # the first request and result, then the retry's request and result
    saved = json.loads((records_dir / "sandbox_escalate_response_PP-R-TEST-1.json").read_text())
    first = saved["first_attempt"]
    assert (first["ok"], first["http_status"], first["error"]) == (False, 400, body)
    assert saved["retry_with_buyer_escalation_reason"]["ok"] is True


def test_send_message_refuses_to_overwrite_an_existing_record(records_dir):
    (records_dir / "sandbox_dispute_after_seller_message_PP-R-TEST-1.json").write_text("{}")
    pp = FakePP(dispute_at("INQUIRY", "WAITING_FOR_SELLER_RESPONSE"))
    assert spike_shapes.send_message(pp, AuditLog(), "PP-R-TEST-1") == 1
    assert pp.writes == []


def test_proof_of_return_sends_nothing_without_a_provide_evidence_link(records_dir):
    pp = FakePP(dispute_at("INQUIRY", "WAITING_FOR_SELLER_RESPONSE", "escalate"))
    assert spike_shapes.proof_of_return(pp, AuditLog(), "PP-R-TEST-1") == 1
    assert pp.writes == []


def test_proof_of_return_records_a_paypal_refusal_with_its_issue_code(records_dir):
    body = {"details": [{"issue": "EVIDENCE_TYPE_IS_NOT_ALLOWED"}]}
    pp = FakePP(dispute_at("INQUIRY", "UNDER_REVIEW", "provide_evidence"), errors=[PayPalError(400, body)])
    assert spike_shapes.proof_of_return(pp, AuditLog(), "PP-R-TEST-1") == 0
    saved = json.loads((records_dir / "sandbox_proof_of_return_response_PP-R-TEST-1.json").read_text())
    assert saved["result"]["ok"] is False and saved["result"]["http_status"] == 400
    assert saved["result"]["error"] == body
    assert saved["before"]["link_rels"] == ["provide_evidence", "self"]


def test_appeal_sends_nothing_without_an_appeal_link(records_dir):
    pp = FakePP(dispute_at("INQUIRY", "UNDER_REVIEW", "escalate"))
    assert spike_shapes.appeal(pp, AuditLog(), "PP-R-TEST-1") == 1
    assert pp.writes == []


def test_attempt_audits_the_request_even_when_the_call_raises_something_unexpected():
    audit = AuditLog()

    def dropped(request_id):
        raise RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        spike_shapes.attempt(audit, "PP-R-TEST-1", "send_message", dropped)
    assert [r["step"] for r in audit.records] == ["spike.send_message.request", "spike.send_message.result"]
    assert "ok" not in audit.records[1]["detail"]
