"""Judge demo mode stays isolated from the real sandbox (A6, piece B3).

The demo router is mounted without the API token on purpose. These checks pin down what makes that safe: no demo route
reaches the real runtime `app_module.rt`, a demo approval writes only to its own session's mock, no PayPal client is
built without the mock transport, the demo's limits hold over HTTP, and the demo modules cannot reach the app, the real
runtime or a PayPal write.
"""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from rebuttal import app as app_module
from rebuttal import runtime as runtime_module
from rebuttal.demo import DemoManager
from rebuttal.demo_api import make_demo_router
from rebuttal.runtime import Runtime

PACKAGE = Path(__file__).resolve().parents[1] / "rebuttal"
DEMO_MODULES = [PACKAGE / "demo.py", PACKAGE / "demo_api.py"]
HERO = "PP-D-2000"
# The PayPal writes (tests/test_write_boundary.py), the write permit, and the private client handles that reach them.
FORBIDDEN = {"send_message", "make_offer", "provide_evidence", "accept_claim", "escalate", "require_evidence",
             "adjudicate", "create_order", "capture_order", "add_order_tracking", "_request", "_http", "_init",
             "permit_writes"}
# Real-sandbox routes that must refuse a request without the token; a JSON body is sent where the route takes one.
REAL_ROUTES = [
    ("GET", "/api/disputes", None),
    ("POST", "/api/disputes/PP-D-2000/analyze", None),
    ("POST", "/api/proposals/x/approve", {}),
    ("POST", "/api/proposals/x/retry", None),
    ("POST", "/api/proposals/x/reject", {}),
    ("GET", "/api/proposals/pending", None),
    ("GET", "/api/audit/PP-D-2000", None),
    ("GET", "/api/analytics", None),
    ("GET", "/api/analytics/rows", None),
    ("GET", "/api/simulator/cases", None),
    ("POST", "/api/simulator/dispute/agent_wrong_size", None),
    ("POST", "/api/simulator/interrupt-next-write", None),
]
# A hostile environment: real-sandbox mode, real-looking keys, a real database, and a model provider.
HOSTILE_ENV = {
    "REBUTTAL_MOCK": "0",
    "PAYPAL_CLIENT_ID": "fake",
    "PAYPAL_CLIENT_SECRET": "fake",
    "GROQ_API_KEY": "x",
    "REBUTTAL_REASONER": "auto",
    "DATABASE_URL": "postgresql://u:p@localhost:5432/x",
}


class RealRuntimeTripwire:
    """Stands in for the real sandbox runtime. Any attribute read means a demo route reached for it."""

    def __getattr__(self, name):
        raise AssertionError("real runtime touched by a demo route")


class FakeClock:
    """Stands in for time.monotonic, so a test can age a session without waiting."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def guarded(monkeypatch):
    """The real runtime is a tripwire and the API token is set: a demo route must need neither."""
    monkeypatch.setattr(app_module, "rt", RealRuntimeTripwire())
    monkeypatch.setattr(app_module, "API_TOKEN", "s3cret")
    return TestClient(app_module.app)


def hero_proposal(client, sid):
    disputes = client.get(f"/api/demo/{sid}/disputes").json()
    return next(d for d in disputes if d["dispute_id"] == HERO)["proposal"]


def test_a_judge_runs_the_demo_without_a_token_and_never_touches_the_real_runtime(guarded):
    created = guarded.post("/api/demo/sessions")  # no Authorization header
    assert created.status_code == 200 and created.json()["hero_dispute_id"] == HERO
    sid = created.json()["session_id"]

    disputes = guarded.get(f"/api/demo/{sid}/disputes").json()
    assert len(disputes) == 6
    hero = next(d for d in disputes if d["dispute_id"] == HERO)
    assert hero["proposal"]["status"] == "PENDING"

    approved = guarded.post(f"/api/demo/{sid}/proposals/{hero['proposal']['id']}/approve",
                            json={"edited_message": "Edited in the demo"})
    assert approved.status_code == 200 and approved.json()["status"] == "EXECUTED"
    steps = [row["step"] for row in guarded.get(f"/api/demo/{sid}/audit/{HERO}").json()]
    assert "execute" in steps

    assert guarded.post(f"/api/demo/{sid}/reset").status_code == 200
    other = next(d["dispute_id"] for d in disputes if d["dispute_id"] != HERO)
    assert guarded.post(f"/api/demo/{sid}/disputes/{other}/analyze").status_code == 200
    assert guarded.post(f"/api/demo/{sid}/simulator/dispute/inr_delivered").status_code == 200


@pytest.mark.parametrize("method,path,body", REAL_ROUTES)
def test_without_a_token_every_real_sandbox_route_is_refused_before_it_runs(guarded, method, path, body):
    # FastAPI resolves the token dependency before the body, so the refusal comes before any touch of `rt`.
    assert guarded.request(method, path, json=body).status_code == 401


def test_demo_routes_answer_without_a_token_and_ignore_a_wrong_one(guarded):
    sid = guarded.post("/api/demo/sessions").json()["session_id"]
    for path in (f"/api/demo/{sid}/disputes", f"/api/demo/{sid}/proposals/pending",
                 f"/api/demo/{sid}/simulator/cases"):
        assert guarded.get(path).status_code == 200, path
        assert guarded.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 200, path


def test_health_stays_open_without_a_token(monkeypatch):
    # Health reads the real runtime by design, so it is checked outside the tripwire.
    monkeypatch.setattr(app_module, "API_TOKEN", "s3cret")
    health = TestClient(app_module.app).get("/api/health")
    assert health.status_code == 200 and health.json()["auth"] is True


def served_api_routes(routes):
    """Every APIRoute the app serves. FastAPI keeps a router from include_router nested in an _IncludedRouter that
    wraps it, so the walk goes into the wrapped routers too."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from served_api_routes(route.original_router.routes)


def test_every_api_route_is_guarded_except_the_demo_and_the_two_open_ones():
    demo_routes = 0
    for route in served_api_routes(app_module.app.routes):
        if not route.path.startswith("/api/"):
            continue
        calls = [dependency.call for dependency in route.dependant.dependencies]
        if route.path.startswith("/api/demo"):
            demo_routes += 1
            assert not any(call is app_module.require_token for call in calls), route.path
        elif route.path not in ("/api/health", "/api/webhooks/paypal"):
            assert any(call is app_module.require_token for call in calls), route.path
    assert demo_routes > 0


def test_a_demo_approval_writes_only_to_its_own_mock(monkeypatch):
    monkeypatch.setattr(app_module, "rt", Runtime(seed_cases=["agent_wrong_size"], force_rules=True))
    client = TestClient(app_module.app)
    sid = client.post("/api/demo/sessions").json()["session_id"]
    proposal = hero_proposal(client, sid)
    assert client.post(f"/api/demo/{sid}/proposals/{proposal['id']}/approve", json={}).status_code == 200

    assert app_module.rt.mock.write_calls() == []
    with app_module.demo_manager.use(sid) as session:
        assert session.runtime.mock.write_calls()
        assert session.runtime.mock is not app_module.rt.mock
        assert session.runtime.client is not app_module.rt.client


def test_a_hostile_environment_still_gives_a_mock_rules_demo(guarded, monkeypatch):
    for name, value in HOSTILE_ENV.items():
        monkeypatch.setenv(name, value)
    built = []
    real_client = runtime_module.PayPalClient

    def recorder(*args, **kwargs):
        assert kwargs.get("transport") is not None, "a PayPal client was built without the mock transport"
        built.append(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "PayPalClient", recorder)
    sid = guarded.post("/api/demo/sessions").json()["session_id"]
    health = guarded.get(f"/api/demo/{sid}/health").json()
    assert health["mode"] == "mock / rules" and health["demo"] is True
    assert built, "the demo did not build its client through rebuttal.runtime, so the recorder proved nothing"


def test_the_creation_and_simulation_limits_hold_over_http():
    app = FastAPI()
    app.include_router(make_demo_router(DemoManager(max_disputes=7, create_limit=2, create_window=60.0)))
    client = TestClient(app)
    first = client.post("/api/demo/sessions")
    second = client.post("/api/demo/sessions")
    assert first.status_code == 200 and second.status_code == 200
    third = client.post("/api/demo/sessions")
    assert third.status_code == 429 and third.headers.get("Retry-After")

    simulate = f"/api/demo/{first.json()['session_id']}/simulator/dispute/agent_wrong_size"
    assert client.post(simulate).status_code == 200  # six seeded disputes plus this one is the cap of seven
    assert client.post(simulate).status_code == 429  # the eighth is refused
    assert client.get("/api/demo/no-such-session/disputes").status_code == 404


def test_an_expired_session_answers_404():
    clock = FakeClock()
    app = FastAPI()
    app.include_router(make_demo_router(DemoManager(clock=clock)))
    client = TestClient(app)
    sid = client.post("/api/demo/sessions").json()["session_id"]
    assert client.get(f"/api/demo/{sid}/disputes").status_code == 200
    clock.now += 7201  # past the idle limit (1800 s) and the maximum age (7200 s)
    assert client.get(f"/api/demo/{sid}/disputes").status_code == 404


def test_max_sessions_evicts_the_oldest_session():
    app = FastAPI()
    manager = DemoManager(max_sessions=2, create_limit=10, create_window=60.0)
    app.include_router(make_demo_router(manager))
    client = TestClient(app)
    sids = []
    for _ in range(4):
        sids.append(client.post("/api/demo/sessions").json()["session_id"])
        assert manager.session_count() <= 2
    assert client.get(f"/api/demo/{sids[0]}/disputes").status_code == 404  # the oldest was evicted
    assert client.get(f"/api/demo/{sids[-1]}/disputes").status_code == 200  # the newest is still served


def callee(call):
    return call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")


def imported_modules(tree):
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules.update(f"{node.module or ''}.{alias.name}" for alias in node.names)
    return modules


def name_ids(node):
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def used_names(tree):
    """Every name a module reads, calls or imports: plain names, attributes and import aliases."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
    return names


def assigns_at_module_level(tree, name):
    return any(isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets)
               for stmt in tree.body)


@pytest.mark.parametrize("path", DEMO_MODULES, ids=lambda path: path.name)
def test_the_demo_modules_cannot_reach_the_app_the_real_runtime_or_a_paypal_write(path):
    tree = ast.parse(path.read_text())
    assert not any(module.split(".")[-1] == "app" for module in imported_modules(tree)), "imports the app"
    assert "rt" not in name_ids(tree), "uses the real runtime `rt`"
    assert not used_names(tree) & FORBIDDEN, "reaches a PayPal write or the write permit"


def test_app_py_hands_the_demo_its_own_manager_and_never_rt():
    tree = ast.parse((PACKAGE / "app.py").read_text())
    assert assigns_at_module_level(tree, "demo_manager"), "demo_manager must be a module-level object"
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and callee(node) in {"DemoManager", "make_demo_router"}]
    assert {callee(call) for call in calls} == {"DemoManager", "make_demo_router"}
    for call in calls:
        for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
            assert "rt" not in name_ids(argument), "app.py passes the real runtime to the demo"
