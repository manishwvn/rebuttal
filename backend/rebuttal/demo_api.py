"""HTTP routes for the public demo: one throwaway PayPal mock per visitor, reached by a session id.

The routes take no token. A session id reaches only its own demo session, and the router can reach nothing but the
DemoManager it was built with. The module never imports the app, so the dashboard's runtime is out of reach.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from .agent.graph import DisputeAgent
from .approval import ApprovalError
from .demo import (
    HERO_DISPUTE_ID,
    DemoBusy,
    DemoLimitReached,
    DemoManager,
    DemoRateLimited,
    DemoSession,
    DemoSessionNotFound,
    DemoUnavailable,
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
    A sandbox call that raises (a PayPal error or a network failure) gets one fixed message. A 4xx answer to a write is
    different: the workflow records it as the proposal's result, and it is returned as the mock sent it."""
    try:
        yield
    except DemoSessionNotFound as exc:
        raise HTTPException(404, "Demo session expired or unknown. Start a new demo.") from exc
    except DemoUnknownCase as exc:
        raise HTTPException(404, "Unknown case") from exc
    except DemoLimitReached as exc:
        raise HTTPException(429, "Demo limit reached for this session. Reset the demo.") from exc
    except DemoRateLimited as exc:
        raise HTTPException(429, "Too many demo sessions right now. Try again shortly.",
                            headers={"Retry-After": str(exc.retry_after)}) from exc
    except DemoBusy as exc:
        raise HTTPException(429, "This demo session is busy. Try again in a moment.", headers={"Retry-After": "1"}) from exc
    except DemoUnavailable as exc:
        raise HTTPException(503, "The demo is unavailable right now. Try again shortly.", headers={"Retry-After": "5"}) from exc
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (PayPalError, httpx.TransportError) as exc:
        raise HTTPException(502, "The demo sandbox failed. Reset the demo.") from exc


def client_key(request: Request) -> str:
    """Who the per-client limit counts: the first X-Forwarded-For hop (the proxy in front of the service sets it), else
    the socket peer."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    return request.client.host if request.client else ""


def _own_proposal(session: DemoSession, proposal_id: str) -> None:
    """Refuses a proposal whose dispute the session does not hold, before the workflow takes a per-dispute lock for it:
    that lock table never shrinks, so caller-chosen ids must not reach it."""
    if not session.has_dispute(DisputeAgent.dispute_of(proposal_id)):
        raise ApprovalError(f"Unknown proposal {proposal_id}")


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
    def create_session(request: Request) -> dict:
        with _demo_errors():
            return info(manager.create(client_key(request)))

    @router.post("/{session_id}/reset")
    def reset(session_id: str, request: Request) -> dict:
        with _demo_errors():
            return info(manager.reset(session_id, client_key(request)))

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
            manager.charge_run(session)
            return session.runtime.analyze(dispute_id).to_dict()

    @router.post("/{session_id}/proposals/{proposal_id}/approve")
    def approve(session_id: str, proposal_id: str, body: Annotated[ApproveBody, Body(default_factory=ApproveBody)]) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            _own_proposal(session, proposal_id)
            manager.charge_run(session)
            return session.runtime.approvals.approve(proposal_id, body.edited_message).to_dict()

    @router.post("/{session_id}/proposals/{proposal_id}/retry")
    def retry(session_id: str, proposal_id: str) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            _own_proposal(session, proposal_id)
            manager.charge_run(session)
            return session.runtime.approvals.retry(proposal_id).to_dict()

    @router.post("/{session_id}/proposals/{proposal_id}/reject")
    def reject(session_id: str, proposal_id: str, body: Annotated[RejectBody, Body(default_factory=RejectBody)]) -> dict:
        with _demo_errors(), manager.use(session_id) as session:
            _own_proposal(session, proposal_id)
            manager.charge_run(session)
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
