"""The dashboard API on top of the graph: analyze, list, approve, edit, reject, retry."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from rebuttal import app as app_module
from rebuttal.paypal.client import PayPalError
from rebuttal.runtime import Runtime


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "rt", Runtime(seed_cases=["agent_wrong_size", "inr_no_tracking"], force_rules=True))
    return TestClient(app_module.app)


def test_analyze_then_approve_through_the_api(client):
    assert client.get("/api/health").json()["mode"] == "mock / rules"
    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    assert proposal["status"] == "PENDING" and proposal["actions"][0]["kind"] == "make_offer"
    assert proposal["approved_message"] is None
    listed = {d["dispute_id"]: d for d in client.get("/api/disputes").json()}
    assert listed["PP-D-2000"]["proposal"]["id"] == proposal["id"] and listed["PP-D-2001"]["proposal"] is None
    assert [p["id"] for p in client.get("/api/proposals/pending").json()] == [proposal["id"]]

    done = client.post(f"/api/proposals/{proposal['id']}/approve", json={"edited_message": "Edited via API"}).json()
    assert done["status"] == "EXECUTED" and done["decision"]["message_to_buyer"] == "Edited via API"
    assert done["approved_message"] == "Edited via API"
    assert client.get("/api/proposals/pending").json() == []
    again = client.post(f"/api/proposals/{proposal['id']}/approve", json={})
    assert again.status_code == 409 and "EXECUTED" in again.json()["detail"]
    steps = [r["step"] for r in client.get("/api/audit/PP-D-2000").json()]
    assert steps == ["gather", "decide", "guard", "propose", "approve", "execute", "record"]


def test_reject_and_unknown_proposals_through_the_api(client):
    proposal = client.post("/api/disputes/PP-D-2001/analyze").json()
    rejected = client.post(f"/api/proposals/{proposal['id']}/reject", json={"reason": "calling the buyer"}).json()
    assert rejected["status"] == "REJECTED"
    assert client.post("/api/proposals/prop_deadbeef_PP-D-2001/approve", json={}).status_code == 409
    assert client.post("/api/proposals/nonexistent/approve", json={}).status_code == 409
    assert client.post(f"/api/proposals/{proposal['id']}/retry").status_code == 409


def test_webhook_triggers_an_analysis_that_waits_for_approval(client):
    event = {"event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-2001"}}
    assert client.post("/api/webhooks/paypal", json=event).json() == {"received": True}
    proposal = app_module.rt.approvals.latest_for("PP-D-2001")
    assert proposal.status == "PENDING" and app_module.rt.mock.write_calls() == []


def test_the_api_token_is_enforced_when_set_and_the_webhook_and_health_stay_open(client, monkeypatch):
    monkeypatch.setattr(app_module, "API_TOKEN", "s3cret")
    assert client.get("/api/health").json()["auth"] is True
    assert client.get("/api/disputes").status_code == 401
    assert client.post("/api/disputes/PP-D-2000/analyze", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/proposals/prop_x_PP-D-2000/approve", json={}).status_code == 401
    assert app_module.rt.mock.write_calls() == []
    ok = client.post("/api/disputes/PP-D-2000/analyze", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and ok.json()["status"] == "PENDING"
    event = {"event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-2001"}}
    assert client.post("/api/webhooks/paypal", json=event).status_code == 200  # open in local mock mode when no webhook id is set


def test_health_reports_no_database_when_none_is_configured(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True and body["database"] is None


SIG = {"paypal-auth-algo": "SHA256withRSA", "paypal-cert-url": "https://api.sandbox.paypal.com/cert",
       "paypal-transmission-id": "t-1", "paypal-transmission-sig": "good", "paypal-transmission-time": "2026-10-07T00:00:00Z"}


def test_a_configured_webhook_id_requires_a_genuine_signature(client, monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(app_module.rt, "settings", replace(app_module.rt.settings, paypal_webhook_id="WH-1"))
    event = {"event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-2001"}}
    assert client.post("/api/webhooks/paypal", json=event).status_code == 401  # no signature headers at all
    assert client.post("/api/webhooks/paypal", json=event, headers={**SIG, "paypal-transmission-sig": "invalid"}
                       ).status_code == 401
    assert app_module.rt.approvals.latest_for("PP-D-2001") is None  # nothing was analysed
    assert client.post("/api/webhooks/paypal", json=event, headers=SIG).json() == {"received": True}
    assert app_module.rt.approvals.latest_for("PP-D-2001").status == "PENDING"
    assert app_module.rt.mock.write_calls() == []  # verifying is not a write


def test_a_real_sandbox_refuses_webhooks_when_no_webhook_id_is_set(client, monkeypatch):
    monkeypatch.setattr(app_module.rt, "mock", None)
    event = {"event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-2001"}}
    assert client.post("/api/webhooks/paypal", json=event).status_code == 503


def test_cors_origins_come_from_the_environment_and_never_allow_a_wildcard():
    assert app_module.cors_origins("") == []
    assert app_module.cors_origins("http://localhost:5173/, https://app.example.com") == [
        "http://localhost:5173", "https://app.example.com"]
    assert app_module.cors_origins("*,http://localhost:5173") == ["http://localhost:5173"]


def test_cors_headers_only_for_configured_origins():
    from fastapi import FastAPI

    probe = FastAPI()
    probe.get("/ping")(lambda: {"ok": True})
    app_module.configure_cors(probe, ["http://localhost:5173"])
    web = TestClient(probe)
    ask = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "authorization,content-type"}
    allowed = web.options("/ping", headers=ask)
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in allowed.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-origin" not in web.options("/ping", headers={**ask, "Origin": "http://evil.example"}).headers

    plain = FastAPI()
    plain.get("/ping")(lambda: {"ok": True})
    app_module.configure_cors(plain, [])  # unset: the middleware is not installed at all
    assert "access-control-allow-origin" not in TestClient(plain).get("/ping", headers={"Origin": "http://x"}).headers


def test_the_simulator_lists_the_labeled_cases(client):
    cases = client.get("/api/simulator/cases").json()
    hero = next(c for c in cases if c["id"] == "agent_wrong_size")
    assert hero["agent_purchase"] is True and hero["title"] and len(cases) == 20
    created = client.post("/api/simulator/dispute/agent_wrong_size").json()
    assert created["status"] == "PENDING" and app_module.rt.mock.write_calls() == []


def test_the_simulator_case_list_is_mock_only(client, monkeypatch):
    monkeypatch.setattr(app_module.rt, "mock", None)
    assert client.get("/api/simulator/cases").status_code == 501


def test_an_interrupted_paypal_call_leaves_the_proposal_approved_and_a_retry_finishes_it(client):
    mock = app_module.rt.mock
    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    assert client.post("/api/simulator/interrupt-next-write").json() == {"armed": True}
    assert client.get("/api/disputes").status_code == 200 and mock.interrupt_next_write is True  # reads do not trip it

    failed = client.post(f"/api/proposals/{proposal['id']}/approve", json={"edited_message": "Edited via API"})
    assert failed.status_code == 502  # a JSON error the dashboard can read, not a bare 500
    assert "approval is saved" in failed.json()["detail"] and "503" in failed.json()["detail"]
    for internal in ("mock-debug", "SERVICE_UNAVAILABLE", "may have been applied"):  # nothing PayPal said, except the status
        assert internal not in failed.json()["detail"]
    assert mock.interrupt_next_write is False and len(mock.write_calls()) == 1  # PayPal acted before the 503

    waiting = {d["dispute_id"]: d for d in client.get("/api/disputes").json()}["PP-D-2000"]["proposal"]
    assert waiting["status"] == "APPROVED" and waiting["approved_message"] == "Edited via API"
    assert waiting["actions"][0]["params"]["note"] != "Edited via API"  # the planned action still holds the draft
    assert [p["id"] for p in client.get("/api/proposals/pending").json()] == []

    done = client.post(f"/api/proposals/{proposal['id']}/retry").json()
    assert done["status"] == "EXECUTED" and done["result"][0]["reconciled"] is True
    assert len(mock.write_calls()) == 1  # the retry read the dispute, saw the offer, and sent nothing
    sellers = [m["content"] for m in mock.disputes["PP-D-2000"]["messages"] if m["posted_by"] == "SELLER"]
    assert sellers == ["Edited via API"]


def test_a_paypal_error_before_anything_was_sent_is_a_readable_502_and_retry_then_sends_once(client, monkeypatch):
    from rebuttal import approval

    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    real = approval.execute_action
    monkeypatch.setattr(approval, "execute_action",
                        lambda *a, **k: (_ for _ in ()).throw(PayPalError(503, {"name": "SERVICE_UNAVAILABLE"}, "mock-debug")))
    failed = client.post(f"/api/proposals/{proposal['id']}/approve", json={})
    assert failed.status_code == 502 and "approval is saved" in failed.json()["detail"]
    assert "retry to continue" in failed.json()["detail"] and "sending or checking the dispute" in failed.json()["detail"]
    assert "mock-debug" not in failed.json()["detail"] and "SERVICE_UNAVAILABLE" not in failed.json()["detail"]
    waiting = {d["dispute_id"]: d for d in client.get("/api/disputes").json()}["PP-D-2000"]["proposal"]
    assert waiting["status"] == "APPROVED" and app_module.rt.mock.write_calls() == []  # nothing had been sent

    monkeypatch.setattr(approval, "execute_action", real)
    done = client.post(f"/api/proposals/{proposal['id']}/retry").json()
    assert done["status"] == "EXECUTED" and len(app_module.rt.mock.write_calls()) == 1


def test_an_interrupted_call_is_logged_and_audited_with_the_status_and_debug_id_but_not_the_body(client, monkeypatch, caplog):
    from rebuttal import approval

    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    monkeypatch.setattr(approval, "execute_action", lambda *a, **k: (_ for _ in ()).throw(
        PayPalError(503, {"name": "SERVICE_UNAVAILABLE", "message": "private words"}, "debug-abc")))
    with caplog.at_level(logging.WARNING, logger="rebuttal.app"):
        assert client.post(f"/api/proposals/{proposal['id']}/approve", json={}).status_code == 502
    assert any(proposal["id"] in r.getMessage() and "503" in r.getMessage() and "debug-abc" in r.getMessage()
               and "private words" not in r.getMessage() for r in caplog.records)
    interrupted = [r for r in client.get("/api/audit/PP-D-2000").json() if r["step"] == "execute_interrupted"]
    assert len(interrupted) == 1
    assert interrupted[0]["detail"] == {"proposal": proposal["id"], "status": 503, "debug_id": "debug-abc",
                                        "error": "PayPalError"}  # no response body


def test_a_network_error_while_sending_is_a_readable_502_and_retry_then_sends_once(client, monkeypatch, caplog):
    from rebuttal import approval

    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    real = approval.execute_action
    monkeypatch.setattr(approval, "execute_action", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("timed out")))
    with caplog.at_level(logging.WARNING, logger="rebuttal.app"):
        failed = client.post(f"/api/proposals/{proposal['id']}/approve", json={})
    assert failed.status_code == 502  # a JSON error the dashboard can read, not a bare 500
    assert "could not be reached" in failed.json()["detail"] and "approval is saved" in failed.json()["detail"]
    assert "retry to continue" in failed.json()["detail"] and "timed out" not in failed.json()["detail"]
    assert any("ReadTimeout" in r.getMessage() for r in caplog.records)
    interrupted = [r for r in client.get("/api/audit/PP-D-2000").json() if r["step"] == "execute_interrupted"]
    assert interrupted[0]["detail"]["status"] is None and interrupted[0]["detail"]["error"] == "ReadTimeout"
    waiting = {d["dispute_id"]: d for d in client.get("/api/disputes").json()}["PP-D-2000"]["proposal"]
    assert waiting["status"] == "APPROVED" and app_module.rt.mock.write_calls() == []

    monkeypatch.setattr(approval, "execute_action", real)
    done = client.post(f"/api/proposals/{proposal['id']}/retry").json()
    assert done["status"] == "EXECUTED" and len(app_module.rt.mock.write_calls()) == 1


def test_a_network_error_during_retry_is_a_readable_502(client, monkeypatch):
    def unreachable(proposal_id):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(app_module.rt.approvals, "retry", unreachable)
    answer = client.post("/api/proposals/prop_x_PP-D-2000/retry")
    assert answer.status_code == 502 and "retry to continue" in answer.json()["detail"]
    assert "no route" not in answer.json()["detail"]


def test_a_paypal_4xx_while_sending_or_checking_does_not_promise_that_a_retry_will_help(client, monkeypatch):
    def refused(proposal_id):
        raise PayPalError(404, {"name": "RESOURCE_NOT_FOUND"}, "debug-404")

    monkeypatch.setattr(app_module.rt.approvals, "retry", refused)
    answer = client.post("/api/proposals/prop_x_PP-D-2000/retry")
    assert answer.status_code == 502 and "(404)" in answer.json()["detail"]
    assert "approval is saved" in answer.json()["detail"] and "retry" not in answer.json()["detail"]


def test_a_failing_audit_store_does_not_turn_the_502_into_a_bare_500(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database down")

    def down(proposal_id):
        raise PayPalError(503, {})

    monkeypatch.setattr(app_module.rt.approvals, "retry", down)
    monkeypatch.setattr(app_module.rt.audit, "log", broken)
    assert client.post("/api/proposals/prop_x_PP-D-2000/retry").status_code == 502


def test_a_paypal_error_during_retry_is_a_readable_502(client, monkeypatch):
    def still_down(proposal_id):
        raise PayPalError(503, {"name": "SERVICE_UNAVAILABLE"})

    monkeypatch.setattr(app_module.rt.approvals, "retry", still_down)
    answer = client.post("/api/proposals/prop_x_PP-D-2000/retry")
    assert answer.status_code == 502 and "retry to continue" in answer.json()["detail"]


def test_the_interrupt_is_used_up_by_any_seller_write_attempt_even_a_failed_one(client):
    mock = app_module.rt.mock
    http = httpx.Client(transport=mock.transport(), base_url="https://api-m.sandbox.paypal.com",
                        headers={"Authorization": "Bearer MOCK-TOKEN"})
    mock.interrupt_next_write = True
    assert http.get("/v1/customer/disputes/PP-D-2000").status_code == 200 and mock.interrupt_next_write is True
    missing = http.post("/v1/customer/disputes/PP-D-NOPE/send-message", json={"message": "x"})
    assert missing.status_code == 404 and mock.interrupt_next_write is False  # failed, but it used up the flag

    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    assert client.post(f"/api/proposals/{proposal['id']}/approve", json={}).status_code == 200  # not tripped later


def test_interrupting_a_write_is_mock_only(client, monkeypatch):
    mock = app_module.rt.mock
    monkeypatch.setattr(app_module.rt, "mock", None)
    assert client.post("/api/simulator/interrupt-next-write").status_code == 501
    assert mock.interrupt_next_write is False
