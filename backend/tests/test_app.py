"""The dashboard API on top of the graph: analyze, list, approve, edit, reject, retry."""

import pytest
from fastapi.testclient import TestClient

from rebuttal import app as app_module
from rebuttal.runtime import Runtime


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "rt", Runtime(seed_cases=["agent_wrong_size", "inr_no_tracking"], force_rules=True))
    return TestClient(app_module.app)


def test_analyze_then_approve_through_the_api(client):
    assert client.get("/api/health").json()["mode"] == "mock / rules"
    proposal = client.post("/api/disputes/PP-D-2000/analyze").json()
    assert proposal["status"] == "PENDING" and proposal["actions"][0]["kind"] == "make_offer"
    listed = {d["dispute_id"]: d for d in client.get("/api/disputes").json()}
    assert listed["PP-D-2000"]["proposal"]["id"] == proposal["id"] and listed["PP-D-2001"]["proposal"] is None
    assert [p["id"] for p in client.get("/api/proposals/pending").json()] == [proposal["id"]]

    done = client.post(f"/api/proposals/{proposal['id']}/approve", json={"edited_message": "Edited via API"}).json()
    assert done["status"] == "EXECUTED" and done["decision"]["message_to_buyer"] == "Edited via API"
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
