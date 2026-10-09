"""HTTP API for the merchant dashboard and PayPal webhooks.

Run:  uvicorn rebuttal.app:app --reload   (from backend/)
"""

from __future__ import annotations

import hmac
import os

from fastapi.concurrency import run_in_threadpool
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .approval import ApprovalError
from .runtime import Runtime
from .scenarios import load_cases, seed_case

DEMO_CASES = ["agent_wrong_size", "inr_delivered", "inr_misdelivered",
              "snad_damaged_low_value", "unauth_agent_mandate", "cnp_refunded"]

def cors_origins(raw: str | None = None) -> list[str]:
    """Browser origins allowed to call the API (REBUTTAL_CORS_ORIGINS, comma separated). Unset = none, which is
    right when the dashboard is served from the same origin. Never `*`: the API takes a bearer token."""
    raw = os.getenv("REBUTTAL_CORS_ORIGINS", "") if raw is None else raw
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip() and o.strip() != "*"]


def configure_cors(application: FastAPI, origins: list[str]) -> None:
    if origins:
        application.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                                   allow_headers=["Authorization", "Content-Type"])


app = FastAPI(title="Rebuttal", version="0.1.0")
rt = Runtime(seed_cases=DEMO_CASES, audit_to_file=True)  # loads backend/.env into the environment
configure_cors(app, cors_origins())  # after the Runtime, so REBUTTAL_CORS_ORIGINS may live in backend/.env


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
    """PayPal sends CUSTOMER.DISPUTE.* here. Every delivery is verified with PayPal's verify-webhook-signature call
    against PAYPAL_WEBHOOK_ID before anything happens. Without a webhook id only the local mock accepts deliveries
    (fail closed on a real sandbox). Only CUSTOMER.DISPUTE.CREATED starts an analysis, which never writes."""
    event = await request.json()
    webhook_id = rt.settings.paypal_webhook_id
    if webhook_id:
        try:
            genuine = await run_in_threadpool(rt.client.read_only().verify_webhook_signature,
                                              webhook_id, dict(request.headers), event)
        except Exception as exc:  # noqa: BLE001 - PayPal unreachable: ask it to deliver again later
            raise HTTPException(503, "Could not verify the webhook with PayPal") from exc
        if not genuine:
            raise HTTPException(401, "Webhook signature verification failed")
    elif rt.mock is None:
        raise HTTPException(503, "PAYPAL_WEBHOOK_ID is not set; refusing unverified webhooks")
    if event.get("event_type") == "CUSTOMER.DISPUTE.CREATED":
        dispute_id = event.get("resource", {}).get("dispute_id")
        if dispute_id:
            background.add_task(rt.analyze, dispute_id)
    return {"received": True}


@app.get("/api/simulator/cases", dependencies=protected)
def simulator_cases():
    """The labeled cases the simulator can create, for the dashboard's picker. Mock mode only, like the simulator."""
    if rt.mock is None:
        raise HTTPException(501, "The simulator only runs against the mock sandbox.")
    return [{"id": c["id"], "title": c["title"], "reason": c["reason"], "agent_purchase": bool(c.get("agent_purchase"))}
            for c in load_cases()]


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
