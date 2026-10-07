"""HTTP API for the merchant dashboard and PayPal webhooks.

Run:  uvicorn rebuttal.app:app --reload   (from backend/)
"""

from __future__ import annotations

import hmac
import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from .approval import ApprovalError
from .runtime import Runtime
from .scenarios import load_cases, seed_case

DEMO_CASES = ["agent_wrong_size", "inr_delivered", "inr_misdelivered",
              "snad_damaged_low_value", "unauth_agent_mandate", "cnp_refunded"]

app = FastAPI(title="Rebuttal", version="0.1.0")
rt = Runtime(seed_cases=DEMO_CASES, audit_to_file=True)


# Opt-in shared secret for the dashboard API: when REBUTTAL_API_TOKEN is set, every /api route except health and the
# PayPal webhook needs `Authorization: Bearer <token>`. Unset (local development) leaves the API open. Whoever can call
# approve is the "human" in the approval gate, so set it on any deployment.
API_TOKEN = os.getenv("REBUTTAL_API_TOKEN", "").strip()
if not API_TOKEN and (not rt.settings.mock or rt.settings.database_url) and os.getenv("REBUTTAL_ALLOW_OPEN_API") != "1":
    # Real sandbox or a shared database: an open approve endpoint would make the approval gate meaningless.
    raise RuntimeError("Set REBUTTAL_API_TOKEN (any long random string) before serving the real sandbox or a shared "
                       "database. For local development only, REBUTTAL_ALLOW_OPEN_API=1 skips this check.")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if API_TOKEN and not hmac.compare_digest((authorization or "").encode(), f"Bearer {API_TOKEN}".encode()):
        raise HTTPException(401, "Missing or wrong API token")


protected = [Depends(require_token)]


class ApproveBody(BaseModel):
    edited_message: str | None = None


class RejectBody(BaseModel):
    reason: str = ""


@app.get("/api/health")
def health():
    # With a database configured this also runs `SELECT 1`, so the daily keep-alive ping keeps a free Supabase
    # project from being paused for inactivity.
    try:
        database = rt.audit.ping()
    except Exception:  # noqa: BLE001 - health must answer even when the database is down
        return {"ok": False, "mode": rt.mode, "auth": bool(API_TOKEN), "database": False}
    return {"ok": True, "mode": rt.mode, "auth": bool(API_TOKEN), "database": database}


@app.get("/api/disputes", dependencies=protected)
def list_disputes():
    out = []
    for d in rt.client.list_disputes():
        p = rt.approvals.latest_for(d["dispute_id"])
        out.append({**d, "proposal": p.to_dict() if p else None})
    return out


@app.post("/api/disputes/{dispute_id}/analyze", dependencies=protected)
def analyze(dispute_id: str):
    return rt.analyze(dispute_id).to_dict()


@app.post("/api/proposals/{proposal_id}/approve", dependencies=protected)
def approve(proposal_id: str, body: ApproveBody):
    try:
        return rt.approvals.approve(proposal_id, body.edited_message).to_dict()
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/proposals/{proposal_id}/retry", dependencies=protected)
def retry(proposal_id: str):
    """Continue an approved proposal whose PayPal call was interrupted (it reads the dispute first and does not
    resend a message or offer that already landed)."""
    try:
        return rt.approvals.retry(proposal_id).to_dict()
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/proposals/pending", dependencies=protected)
def pending():
    return [p.to_dict() for p in rt.approvals.pending()]


@app.post("/api/proposals/{proposal_id}/reject", dependencies=protected)
def reject(proposal_id: str, body: RejectBody):
    try:
        return rt.approvals.reject(proposal_id, body.reason).to_dict()
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/audit/{dispute_id}", dependencies=protected)
def audit(dispute_id: str):
    return rt.audit.for_dispute(dispute_id)


@app.post("/api/webhooks/paypal")
async def paypal_webhook(request: Request, background: BackgroundTasks):
    # TODO(week 3): verify signature via POST /v1/notifications/verify-webhook-signature
    event = await request.json()
    if event.get("event_type") == "CUSTOMER.DISPUTE.CREATED":
        dispute_id = event.get("resource", {}).get("dispute_id")
        if dispute_id:
            background.add_task(rt.analyze, dispute_id)
    return {"received": True}


@app.post("/api/simulator/dispute/{case_id}", dependencies=protected)
def simulate(case_id: str):
    """Judge-facing simulator. Mock mode seeds a labeled case; sandbox mode comes in week 2."""
    if rt.mock is None:
        raise HTTPException(501, "Sandbox simulator lands in week 2 (buyer-side dispute creation).")
    cases = {c["id"]: c for c in load_cases()}
    if case_id not in cases:
        raise HTTPException(404, f"Unknown case {case_id}")
    dispute_id = seed_case(cases[case_id], len(rt.mock.disputes) + 100, rt.mock, rt.store)
    return rt.analyze(dispute_id).to_dict()
