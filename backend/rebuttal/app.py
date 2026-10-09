"""HTTP API for the merchant dashboard and PayPal webhooks.

Run:  uvicorn rebuttal.app:app --reload   (from backend/)
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics
from .agent.graph import DisputeAgent
from .approval import ApprovalError
from .demo import DemoManager
from .demo_api import make_demo_router
from .paypal.client import PayPalError
from .runtime import Runtime
from .scenarios import load_cases, seed_case

logger = logging.getLogger(__name__)

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


# Opt-in shared secret for the dashboard API: when REBUTTAL_API_TOKEN is set, every /api route except health, the
# PayPal webhook and the public demo under /api/demo (each reaches only its own mock session) needs
# `Authorization: Bearer <token>`. Unset (local development) leaves the API open. Whoever can call approve is the
# "human" in the approval gate, so set it on any deployment.
API_TOKEN = os.getenv("REBUTTAL_API_TOKEN", "").strip()
if not API_TOKEN and (not rt.settings.mock or rt.settings.database_url) and os.getenv("REBUTTAL_ALLOW_OPEN_API") != "1":
    # Real sandbox or a shared database: an open approve endpoint would make the approval gate meaningless.
    raise RuntimeError("Set REBUTTAL_API_TOKEN (any long random string) before serving the real sandbox or a shared "
                       "database. For local development only, REBUTTAL_ALLOW_OPEN_API=1 skips this check.")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if API_TOKEN and not hmac.compare_digest((authorization or "").encode(), f"Bearer {API_TOKEN}".encode()):
        raise HTTPException(401, "Missing or wrong API token")


protected = [Depends(require_token)]
# The demo router is deliberately NOT behind the token: it can only reach its own DemoManager, an isolated mock
# runtime per session, and never `rt`. Nothing here may pass `rt`, `rt.client` or `rt.settings` to the demo.
# tests/test_demo_isolation.py enforces that and checks that every other /api route keeps the token.
# The real-sandbox routes below keep `protected`.
demo_manager = DemoManager()
app.include_router(make_demo_router(demo_manager))


def paypal_interrupted(proposal_id: str, exc: PayPalError | httpx.TransportError) -> HTTPException:
    """PayPal failed (or could not be reached) while an approved action was being sent or while the dispute was being
    read first. The approval is already saved (the proposal now reads APPROVED), so say that in a normal JSON error:
    an unhandled exception would become a bare 500 that browsers on another origin cannot even read, because it
    carries no CORS headers. The response says nothing about PayPal's reply beyond its status; the status and
    debug_id go to the server log and the audit trail, where an operator can follow them up."""
    status = exc.status if isinstance(exc, PayPalError) else None
    debug_id = exc.debug_id if isinstance(exc, PayPalError) else None
    logger.warning("PayPal call interrupted for %s: %s status=%s debug_id=%s", proposal_id, type(exc).__name__,
                   status, debug_id)
    try:
        rt.audit.log(DisputeAgent.dispute_of(proposal_id), "execute_interrupted",
                     {"proposal": proposal_id, "status": status, "debug_id": debug_id, "error": type(exc).__name__})
    except Exception:  # noqa: BLE001 - the audit store must not turn a readable 502 back into a bare 500
        logger.exception("Could not audit the interrupted PayPal call for %s", proposal_id)
    what = f"PayPal answered with an error ({status})" if status is not None else "PayPal could not be reached"
    retryable = status is None or status >= 500  # a 4xx is an answer: retrying the same call will not change it
    return HTTPException(502, f"{what} while sending or checking the dispute. Your approval is saved"
                              + ("; retry to continue." if retryable else "."))


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
    except (PayPalError, httpx.TransportError) as exc:
        raise paypal_interrupted(proposal_id, exc) from exc


@app.post("/api/proposals/{proposal_id}/retry", dependencies=protected)
def retry(proposal_id: str):
    """Continue an approved proposal whose PayPal call was interrupted (it reads the dispute first and does not
    resend a message or offer that already landed)."""
    try:
        return rt.approvals.retry(proposal_id).to_dict()
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (PayPalError, httpx.TransportError) as exc:
        raise paypal_interrupted(proposal_id, exc) from exc


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


DUE_DATE_TTL = 60.0  # seconds a looked-up seller due date is reused by the analytics sweeps


def _with_due_date(reader, dispute: dict) -> dict:
    """The list summary may leave out `seller_response_due_date` (the mock's does, and PayPal documents only a few list
    fields), but the deadlines view needs it for disputes waiting on the seller: read it from the dispute itself.
    A due date is reused for `DUE_DATE_TTL` seconds, so a refresh does not cost one PayPal read per waiting dispute.
    When that read fails the dispute is shown without a due date (and the lookup is tried again next time), because
    one failed read should not blank the whole tab."""
    if dispute.get("seller_response_due_date") or dispute["status"] != "WAITING_FOR_SELLER_RESPONSE":
        return dispute
    dispute_id, now = dispute["dispute_id"], time.monotonic()
    cached = rt.due_dates.get(dispute_id)
    if cached and cached[0] > now:
        due = cached[1]
    else:
        try:
            due = reader.get_dispute(dispute_id).get("seller_response_due_date")
        except (PayPalError, httpx.TransportError) as exc:
            logger.warning("Analytics: could not read the due date of %s: %s", dispute_id, type(exc).__name__)
            return dispute
        rt.due_dates[dispute_id] = (now + DUE_DATE_TTL, due)
    return {**dispute, "seller_response_due_date": due}


def _analytics_rows() -> list[dict]:
    """Every dispute with its latest proposal and audit trail, shaped for `analytics`. Reads only. When PayPal cannot
    list the disputes the tab gets a readable 502 (like the other PayPal routes), not a bare 500."""
    reader = rt.client.read_only()  # a handle whose transport refuses every write
    try:
        listed = reader.list_disputes()
    except (PayPalError, httpx.TransportError) as exc:
        status = exc.status if isinstance(exc, PayPalError) else None
        debug_id = exc.debug_id if isinstance(exc, PayPalError) else None
        logger.warning("Analytics: could not list the disputes: %s status=%s debug_id=%s", type(exc).__name__, status,
                       debug_id)
        raise HTTPException(502, "PayPal could not be read for the analytics. Try again shortly.") from exc
    disputes = [_with_due_date(reader, d) for d in listed]
    proposals: dict[str, dict] = {}
    audits: dict[str, list[dict]] = {}
    for d in disputes:
        dispute_id = d["dispute_id"]
        proposal = rt.approvals.latest_for(dispute_id)
        if proposal:
            proposals[dispute_id] = proposal.to_dict()
            audits[dispute_id] = rt.audit.for_dispute(dispute_id)
    return analytics.build_rows(disputes, proposals, audits)


# Analytics routes: they only read (PayPal through the read-only handle, the approval queue and the audit log).
# The dashboard loads `/api/analytics`: one sweep of the disputes feeds all three parts, so they agree with each other
# and PayPal is read once. The three single-part routes stay for scripts and tests.
@app.get("/api/analytics", dependencies=protected)
def analytics_report():
    rows, now = _analytics_rows(), rt.clock()
    return {"rows": rows, "summary": analytics.summarize(rows, now), "deadlines": analytics.deadlines(rows, now)}


@app.get("/api/analytics/rows", dependencies=protected)
def analytics_rows():
    return _analytics_rows()


@app.get("/api/analytics/summary", dependencies=protected)
def analytics_summary():
    return analytics.summarize(_analytics_rows(), rt.clock())


@app.get("/api/analytics/deadlines", dependencies=protected)
def analytics_deadlines():
    return analytics.deadlines(_analytics_rows(), rt.clock())


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


@app.post("/api/simulator/interrupt-next-write", dependencies=protected)
def interrupt_next_write():
    """Mock mode only. The next PayPal write is applied and then answered with a 503, as when a gateway fails after
    PayPal acted: the approved proposal is left APPROVED and the dashboard's Retry has something to do."""
    if rt.mock is None:
        raise HTTPException(501, "Only the mock sandbox can be made to fail.")
    rt.mock.interrupt_next_write = True
    return {"armed": True}


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


def frontend_dir() -> Path | None:
    """The built dashboard (frontend/dist), or REBUTTAL_FRONTEND_DIR. None when it has not been built."""
    raw = os.getenv("REBUTTAL_FRONTEND_DIR", "").strip()
    path = Path(raw) if raw else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return path if (path / "index.html").is_file() else None


def mount_frontend(application: FastAPI, directory: Path | None) -> None:
    """Serve the built dashboard from the same origin. Registered after every API route, so it can never shadow
    one; /api/* paths that match no route stay a JSON 404 instead of falling back to the page."""
    if directory is None:
        return
    root = directory.resolve()
    root_str = os.path.realpath(root)
    application.mount("/assets", StaticFiles(directory=root / "assets", check_dir=False), name="frontend-assets")

    @application.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        try:
            target = os.path.realpath(os.path.join(root_str, path))
            if path and target.startswith(root_str + os.sep) and os.path.isfile(target):
                return FileResponse(target)
        except (ValueError, OSError):  # e.g. an embedded null byte
            pass
        return FileResponse(root / "index.html")


mount_frontend(app, frontend_dir())
