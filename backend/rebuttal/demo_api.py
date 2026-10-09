"""HTTP routes for the public demo: one throwaway PayPal mock per visitor, reached by a session id.

The routes take no token. A session id reaches only its own demo session, and the router can reach nothing but the
DemoManager it was built with. The module never imports the app, so the dashboard's runtime is out of reach.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .approval import ApprovalError
from .demo import (
    HERO_DISPUTE_ID,
    DemoLimitReached,
    DemoManager,
    DemoRateLimited,
    DemoSession,
    DemoSessionNotFound,
    DemoUnknownCase,
    simulator_cases,
)
from .paypal.client import PayPalError


class ApproveBody(BaseModel):
    edited_message: str | None = Field(default=None, max_length=2000)


class RejectBody(BaseModel):
    reason: str = Field(default="", max_length=500)


@contextmanager
def _demo_errors() -> Iterator[None]:
    """Turns the demo's own errors and sandbox failures into JSON errors. A bare 500 would carry no CORS headers.
    A failed sandbox call gets one fixed message: PayPal's reply is never sent to the browser."""
    try:
        yield
    except DemoSessionNotFound as exc:
        raise HTTPException(404, "Demo session expired or unknown. Start a new demo.") from exc
    except DemoUnknownCase as exc:
        raise HTTPException(404, "Unknown case") from exc
    except DemoLimitReached as exc:
        raise HTTPException(429, "Demo dispute limit reached for this session. Reset the demo.") from exc
    except DemoRateLimited as exc:
        raise HTTPException(429, "Too many demo sessions right now. Try again shortly.",
                            headers={"Retry-After": str(exc.retry_after)}) from exc
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (PayPalError, httpx.TransportError) as exc:
        raise HTTPException(502, "The demo sandbox failed. Reset the demo.") from exc


def make_demo_router(manager: DemoManager) -> APIRouter:
    """Every route except session creation looks its session up first, so an unknown or expired id answers 404."""
    router = APIRouter(prefix="/api/demo", tags=["demo"])

    def info(session: DemoSession) -> dict:
        return {
            "session_id": session.id,
            "expires_in_seconds": manager.expires_in(session),
            "max_disputes": manager.max_disputes,
            "hero_dispute_id": HERO_DISPUTE_ID,
        }

    @router.post("/sessions")
    def create_session() -> dict:
        with _demo_errors():
            return info(manager.create())

    @router.post("/{session_id}/reset")
    def reset(session_id: str) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            return info(manager.reset(session.id))

    @router.get("/{session_id}/health")
    def health(session_id: str) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            return {
                "ok": True,
                "mode": session.runtime.mode,
                "auth": False,
                "database": None,
                "demo": True,
                "expires_in_seconds": manager.expires_in(session),
            }

    @router.get("/{session_id}/disputes")
    def list_disputes(session_id: str) -> list[dict]:
        with _demo_errors(), manager.use(session_id) as session:
            rows = []
            for dispute in session.runtime.client.list_disputes():
                proposal = session.runtime.approvals.latest_for(dispute["dispute_id"])
                rows.append({**dispute, "proposal": proposal.to_dict() if proposal else None})
            return rows

    @router.post("/{session_id}/disputes/{dispute_id}/analyze")
    def analyze(session_id: str, dispute_id: str) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            if not session.has_dispute(dispute_id):
                raise HTTPException(404, "Unknown demo dispute")
            return session.runtime.analyze(dispute_id).to_dict()

    @router.post("/{session_id}/proposals/{proposal_id}/approve")
    def approve(session_id: str, proposal_id: str, body: ApproveBody) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            return session.runtime.approvals.approve(proposal_id, body.edited_message).to_dict()

    @router.post("/{session_id}/proposals/{proposal_id}/retry")
    def retry(session_id: str, proposal_id: str) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            return session.runtime.approvals.retry(proposal_id).to_dict()

    @router.post("/{session_id}/proposals/{proposal_id}/reject")
    def reject(session_id: str, proposal_id: str, body: RejectBody) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            return session.runtime.approvals.reject(proposal_id, body.reason).to_dict()

    @router.get("/{session_id}/proposals/pending")
    def pending(session_id: str) -> list[dict]:
        with _demo_errors(), manager.use(session_id) as session:
            return [p.to_dict() for p in session.runtime.approvals.pending()]

    @router.get("/{session_id}/audit/{dispute_id}")
    def audit(session_id: str, dispute_id: str) -> list[dict]:
        with _demo_errors(), manager.use(session_id) as session:
            return session.runtime.audit.for_dispute(dispute_id)

    @router.get("/{session_id}/simulator/cases")
    def list_simulator_cases(session_id: str) -> list[dict]:
        with _demo_errors(), manager.use(session_id):  # the lookup alone answers 404 for an unknown session
            return simulator_cases()

    @router.post("/{session_id}/simulator/dispute/{case_id}")
    def simulate_dispute(session_id: str, case_id: str) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            return manager.simulate(session, case_id).to_dict()

    return router
