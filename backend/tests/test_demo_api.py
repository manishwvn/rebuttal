"""Tests for the unauthenticated /api/demo router (rebuttal/demo_api.py).

FakeManager implements the rebuttal.demo contract over real Runtime objects on the PayPal mock, so approve really runs
the workflow. No request here sends an Authorization header: the demo routes take none.
"""

from __future__ import annotations

import ast
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rebuttal import demo_api
from rebuttal.agent.pipeline import Proposal
from rebuttal.demo import (
    HERO_DISPUTE_ID,
    DemoLimitReached,
    DemoManager,
    DemoRateLimited,
    DemoSession,
    DemoSessionNotFound,
    DemoUnknownCase,
    simulator_cases,
)
from rebuttal.demo_api import make_demo_router
from rebuttal.paypal.client import PayPalError
from rebuttal.persistence import DisputeLocks
from rebuttal.runtime import Runtime
from rebuttal.scenarios import load_cases, seed_case

SEED_CASES = ["agent_wrong_size", "inr_no_tracking"]
NOT_FOUND = "Demo session expired or unknown. Start a new demo."
UNKNOWN = "no-such-session"
FORBIDDEN_NAMES = {"send_message", "make_offer", "provide_evidence", "accept_claim", "escalate", "require_evidence",
                   "adjudicate", "create_order", "capture_order", "add_order_tracking", "permit_writes", "_request",
                   "_http", "_init"}


class FakeManager:
    """The rebuttal.demo contract. `failures` maps an operation name to the exception that operation raises."""

    max_disputes = 3

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sessions: dict[str, DemoSession] = {}
        self.failures: dict[str, Exception] = {}

    def _new_session(self, session_id: str) -> DemoSession:
        now = time.time()
        runtime = Runtime(seed_cases=SEED_CASES, force_rules=True)
        return DemoSession(id=session_id, runtime=runtime, lock=threading.RLock(), created_at=now, last_used=now)

    def _fail_if_set(self, operation: str) -> None:
        if operation in self.failures:
            raise self.failures[operation]

    def create(self) -> DemoSession:
        self._fail_if_set("create")
        session = self._new_session(uuid.uuid4().hex)
        with self._lock:
            self.sessions[session.id] = session
        return session

    @contextmanager
    def use(self, session_id: str) -> Iterator[DemoSession]:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise DemoSessionNotFound("no such session")
        with session.lock:
            yield session

    def reset(self, session_id: str) -> DemoSession:
        self._fail_if_set("reset")
        with self.use(session_id):  # like DemoManager.reset: unknown ids 404, and the session lock is taken
            fresh = self._new_session(session_id)
            with self._lock:
                self.sessions[session_id] = fresh
            return fresh

    def expires_in(self, session: DemoSession) -> int:
        return 1800

    def charge_run(self, session: DemoSession) -> None:
        self._fail_if_set("charge_run")

    def simulate(self, session: DemoSession, case_id: str) -> Proposal:
        self._fail_if_set("simulate")
        cases = {c["id"]: c for c in load_cases()}
        if case_id not in cases:
            raise DemoUnknownCase(case_id)
        runtime = session.runtime
        dispute_id = seed_case(cases[case_id], len(runtime.mock.disputes) + 100, runtime.mock, runtime.store)
        return runtime.analyze(dispute_id)


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def client(manager: FakeManager) -> TestClient:
    app = FastAPI()
    app.include_router(make_demo_router(manager))
    return TestClient(app)


def new_session(client: TestClient) -> str:
    return client.post("/api/demo/sessions").json()["session_id"]


def test_create_session_returns_the_demo_info(client, manager):
    body = client.post("/api/demo/sessions").json()
    assert list(manager.sessions) == [body["session_id"]]
    assert body == {"session_id": body["session_id"], "expires_in_seconds": 1800,
                    "max_disputes": manager.max_disputes, "hero_dispute_id": HERO_DISPUTE_ID}


def test_health_reports_the_mock_mode_without_auth(client):
    sid = new_session(client)
    assert client.get(f"/api/demo/{sid}/health").json() == {
        "ok": True, "mode": "mock / rules", "auth": False, "database": None, "demo": True,
        "expires_in_seconds": 1800}


def test_hero_flow_runs_end_to_end_without_a_token(client):
    sid = new_session(client)
    base = f"/api/demo/{sid}"

    disputes = {d["dispute_id"]: d for d in client.get(f"{base}/disputes").json()}
    assert set(disputes) == {"PP-D-2000", "PP-D-2001"} and disputes[HERO_DISPUTE_ID]["proposal"] is None

    proposal = client.post(f"{base}/disputes/{HERO_DISPUTE_ID}/analyze").json()
    assert proposal["status"] == "PENDING"
    assert [p["id"] for p in client.get(f"{base}/proposals/pending").json()] == [proposal["id"]]

    done = client.post(f"{base}/proposals/{proposal['id']}/approve",
                       json={"edited_message": "Edited through the demo."}).json()
    assert done["status"] == "EXECUTED"
    again = client.post(f"{base}/proposals/{proposal['id']}/approve", json={})
    assert again.status_code == 409 and "EXECUTED" in again.json()["detail"]

    steps = [entry["step"] for entry in client.get(f"{base}/audit/{HERO_DISPUTE_ID}").json()]
    assert steps[-2:] == ["execute", "record"]
    assert client.get(f"{base}/proposals/pending").json() == []


def test_reject_closes_the_proposal_and_keeps_the_reason_in_the_audit(client):
    sid = new_session(client)
    base = f"/api/demo/{sid}"
    proposal = client.post(f"{base}/disputes/PP-D-2001/analyze").json()
    rejected = client.post(f"{base}/proposals/{proposal['id']}/reject",
                           json={"reason": "Calling the buyer first"}).json()
    assert rejected["status"] == "REJECTED"
    assert client.get(f"{base}/proposals/pending").json() == []
    reject_entries = [e for e in client.get(f"{base}/audit/PP-D-2001").json() if e["step"] == "reject"]
    assert reject_entries[0]["detail"]["reason"] == "Calling the buyer first"


@pytest.mark.parametrize("action,body", [
    ("approve", {"edited_message": "x" * 2001}),
    ("reject", {"reason": "x" * 501}),
])
def test_request_bodies_past_their_limits_are_refused(client, action, body):
    sid = new_session(client)
    assert client.post(f"/api/demo/{sid}/proposals/prop_x_{HERO_DISPUTE_ID}/{action}", json=body).status_code == 422


def test_analyze_refuses_a_dispute_the_session_does_not_hold(client):
    sid = new_session(client)
    r = client.post(f"/api/demo/{sid}/disputes/PP-D-9999/analyze")
    assert r.status_code == 404 and r.json() == {"detail": "Unknown demo dispute"}


def test_reset_starts_over_under_the_same_session_id(client):
    sid = new_session(client)
    base = f"/api/demo/{sid}"
    client.post(f"{base}/disputes/{HERO_DISPUTE_ID}/analyze")
    body = client.post(f"{base}/reset").json()
    assert body["session_id"] == sid
    assert all(d["proposal"] is None for d in client.get(f"{base}/disputes").json())


def test_reset_with_the_real_manager_finishes_and_leaves_the_session_usable():
    manager = DemoManager(runtime_factory=lambda: Runtime(seed_cases=SEED_CASES, force_rules=True))
    app = FastAPI()
    app.include_router(make_demo_router(manager))
    http = TestClient(app)
    sid = http.post("/api/demo/sessions").json()["session_id"]
    result: dict = {}

    def run() -> None:
        result["reset"] = http.post(f"/api/demo/{sid}/reset").status_code
        result["health"] = http.get(f"/api/demo/{sid}/health").status_code

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=10)  # a lock deadlock fails here instead of hanging the run
    assert not worker.is_alive(), "reset did not finish"
    assert result == {"reset": 200, "health": 200}


def test_an_unknown_session_reset_does_not_spend_the_rate_limit():
    manager = DemoManager(runtime_factory=lambda: Runtime(seed_cases=SEED_CASES, force_rules=True), create_limit=2)
    app = FastAPI()
    app.include_router(make_demo_router(manager))
    http = TestClient(app)
    for _ in range(5):
        assert http.post(f"/api/demo/{UNKNOWN}/reset").status_code == 404
    assert http.post("/api/demo/sessions").status_code == 200


def test_a_proposal_for_a_dispute_the_session_does_not_hold_is_refused_before_any_lock(client):
    sid = new_session(client)
    with patch.object(DisputeLocks, "hold") as hold:
        for action, body in (("approve", {}), ("retry", None), ("reject", {})):
            r = client.post(f"/api/demo/{sid}/proposals/prop_abc_PP-D-9999/{action}", json=body)
            assert r.status_code == 409 and r.json() == {"detail": "Unknown proposal prop_abc_PP-D-9999"}
    hold.assert_not_called()


def test_retry_refuses_a_proposal_that_is_still_waiting_for_approval(client):
    sid = new_session(client)
    proposal = client.post(f"/api/demo/{sid}/disputes/PP-D-2001/analyze").json()
    r = client.post(f"/api/demo/{sid}/proposals/{proposal['id']}/retry")
    assert r.status_code == 409 and "not waiting to continue" in r.json()["detail"]


def test_simulator_lists_the_cases_and_runs_one(client):
    sid = new_session(client)
    base = f"/api/demo/{sid}"
    assert client.get(f"{base}/simulator/cases").json() == simulator_cases()
    assert client.post(f"{base}/simulator/dispute/inr_no_tracking").json()["status"] == "PENDING"


UNKNOWN_SESSION_CALLS = [
    pytest.param("POST", f"/api/demo/{UNKNOWN}/reset", None, id="reset"),
    pytest.param("GET", f"/api/demo/{UNKNOWN}/health", None, id="health"),
    pytest.param("GET", f"/api/demo/{UNKNOWN}/disputes", None, id="disputes"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/disputes/{HERO_DISPUTE_ID}/analyze", None, id="analyze"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/proposals/prop_x_{HERO_DISPUTE_ID}/approve", {}, id="approve"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/proposals/prop_x_{HERO_DISPUTE_ID}/approve", None, id="approve-no-body"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/proposals/prop_x_{HERO_DISPUTE_ID}/reject", None, id="reject-no-body"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/proposals/prop_x_{HERO_DISPUTE_ID}/retry", None, id="retry"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/proposals/prop_x_{HERO_DISPUTE_ID}/reject", {}, id="reject"),
    pytest.param("GET", f"/api/demo/{UNKNOWN}/proposals/pending", None, id="pending"),
    pytest.param("GET", f"/api/demo/{UNKNOWN}/audit/{HERO_DISPUTE_ID}", None, id="audit"),
    pytest.param("GET", f"/api/demo/{UNKNOWN}/simulator/cases", None, id="simulator-cases"),
    pytest.param("POST", f"/api/demo/{UNKNOWN}/simulator/dispute/inr_no_tracking", None, id="simulate"),
]


@pytest.mark.parametrize("method,path,body", UNKNOWN_SESSION_CALLS)
def test_an_unknown_session_is_a_404_on_every_route(client, method, path, body):
    r = client.request(method, path, json=body)
    assert r.status_code == 404 and r.json() == {"detail": NOT_FOUND}


def test_the_demo_limit_is_a_429(client, manager):
    sid = new_session(client)
    manager.failures["simulate"] = DemoLimitReached("limit reached")
    r = client.post(f"/api/demo/{sid}/simulator/dispute/inr_no_tracking")
    assert r.status_code == 429
    assert r.json() == {"detail": "Demo limit reached for this session. Reset the demo."}


def test_a_session_that_runs_the_workflow_past_its_budget_gets_a_429_until_it_is_reset():
    manager = DemoManager(runtime_factory=lambda: Runtime(seed_cases=SEED_CASES, force_rules=True), max_runs=6)
    app = FastAPI()
    app.include_router(make_demo_router(manager))
    http = TestClient(app)
    sid = http.post("/api/demo/sessions").json()["session_id"]
    base = f"/api/demo/{sid}"
    statuses = []
    for _ in range(4):  # an analyze then a reject per loop: each one re-runs the graph and grows the session's memory
        proposal = http.post(f"{base}/disputes/PP-D-2001/analyze")
        statuses.append(proposal.status_code)
        if proposal.status_code == 200:
            statuses.append(http.post(f"{base}/proposals/{proposal.json()['id']}/reject", json={}).status_code)
    assert statuses == [200, 200, 200, 200, 200, 200, 429]  # runs 1-6 pass, the 7th is refused; the loop stops there
    r = http.post(f"{base}/disputes/PP-D-2001/analyze")
    assert r.status_code == 429 and r.json() == {"detail": "Demo limit reached for this session. Reset the demo."}

    assert http.post(f"{base}/reset").status_code == 200  # Reset demo restores the budget
    assert http.post(f"{base}/disputes/PP-D-2001/analyze").status_code == 200


def test_a_rate_limited_session_start_is_a_429_with_retry_after(client, manager):
    manager.failures["create"] = DemoRateLimited(retry_after=7)
    r = client.post("/api/demo/sessions")
    assert r.status_code == 429 and r.headers["Retry-After"] == "7"
    assert r.json() == {"detail": "Too many demo sessions right now. Try again shortly."}


def test_an_unknown_case_is_a_404(client):
    sid = new_session(client)
    r = client.post(f"/api/demo/{sid}/simulator/dispute/no_such_case")
    assert r.status_code == 404 and r.json() == {"detail": "Unknown case"}


@pytest.mark.parametrize("failure", [
    PayPalError(500, {"message": "SECRET-PAYPAL-TEXT"}, debug_id="dbg-123"),
    httpx.ConnectError("SECRET-PAYPAL-TEXT"),
], ids=["paypal-error", "transport-error"])
def test_a_failed_sandbox_call_is_a_502_that_never_echoes_paypal(client, manager, failure):
    sid = new_session(client)
    approvals = manager.sessions[sid].runtime.approvals
    with patch.object(approvals, "approve", side_effect=failure):
        r = client.post(f"/api/demo/{sid}/proposals/prop_x_{HERO_DISPUTE_ID}/approve", json={})
    assert r.status_code == 502
    assert r.json() == {"detail": "The demo sandbox failed. Reset the demo."}


def test_every_route_sits_under_the_prefix_and_none_has_a_dependency(manager):
    router = make_demo_router(manager)
    assert router.routes and router.dependencies == []
    for route in router.routes:
        assert route.path.startswith("/api/demo")
        assert route.dependencies == [] and route.dependant.dependencies == []


def test_the_module_names_no_paypal_write_and_no_private_client_handle():
    tree = ast.parse(Path(demo_api.__file__).read_text(encoding="utf-8"))
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not used & FORBIDDEN_NAMES, sorted(used & FORBIDDEN_NAMES)


def test_the_module_does_not_import_the_app():
    tree = ast.parse(Path(demo_api.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported += [node.module or ""] + [alias.name for alias in node.names]
    assert not any("app" in name.split(".") for name in imported), imported
