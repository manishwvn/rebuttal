"""Unexpected errors in the API become a JSON 500 that browsers on another origin can read (CORS headers included)."""

import importlib
import logging
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from rebuttal import app as app_module
from rebuttal.paypal.client import PayPalError
from rebuttal.runtime import Runtime

ORIGIN = "http://localhost:5173"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "rt", Runtime(seed_cases=["agent_wrong_size", "inr_no_tracking"], force_rules=True))
    return TestClient(app_module.app)


@contextmanager
def real_app_with_cors(monkeypatch):
    """The real app rebuilt with CORS for ORIGIN: app.py reads REBUTTAL_CORS_ORIGINS at import time, so it is reloaded
    with the variable set, then reloaded again without it on the way out."""
    monkeypatch.setenv("REBUTTAL_CORS_ORIGINS", ORIGIN)
    importlib.reload(app_module)
    try:
        yield app_module.app
    finally:
        monkeypatch.undo()
        importlib.reload(app_module)


def test_an_unexpected_error_is_a_json_500_without_the_exception_text(client, monkeypatch, caplog):
    def boom(dispute_id):
        raise RuntimeError("boom secret")

    monkeypatch.setattr(app_module.rt, "analyze", boom)
    with caplog.at_level(logging.ERROR, logger="rebuttal.app"):
        response = client.post("/api/disputes/PP-D-2000/analyze")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "boom secret" not in response.text
    assert "Unhandled error on POST /api/disputes/PP-D-2000/analyze" in caplog.text
    assert "Traceback" in caplog.text and "RuntimeError: boom secret" in caplog.text


def test_the_json_500_carries_the_cors_headers_for_a_configured_origin():
    probe = FastAPI()

    @probe.get("/boom")
    def boom():
        raise ValueError("internal detail")

    probe.middleware("http")(app_module.json_500)  # same order as app.py: the handler first, then CORS
    app_module.configure_cors(probe, [ORIGIN])
    response = TestClient(probe).get("/boom", headers={"Origin": ORIGIN})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "internal detail" not in response.text


def test_http_exceptions_keep_their_status_and_detail():
    probe = FastAPI()

    @probe.get("/missing")
    def missing():
        raise HTTPException(404, "Nothing here")

    probe.middleware("http")(app_module.json_500)
    response = TestClient(probe).get("/missing")
    assert response.status_code == 404 and response.json() == {"detail": "Nothing here"}


def test_paypal_failures_stay_a_readable_502(client, monkeypatch):
    def fail(*a, **k):
        raise PayPalError(503, {"name": "SERVICE_UNAVAILABLE"}, "dbg-2")

    monkeypatch.setattr(app_module.rt.agent, "analyze", fail)
    response = client.post("/api/disputes/PP-D-2000/analyze")
    assert response.status_code == 502 and "dbg-2" not in response.json()["detail"]


def test_the_real_app_registers_json_500_inside_cors(monkeypatch):
    """Starlette lists the last-added middleware first (outermost). app.py adds json_500 before CORS, so the CORS entry
    must come first in the list. Registering json_500 after configure_cors would fail here."""
    with real_app_with_cors(monkeypatch) as application:
        entries = list(application.user_middleware)
        cors = [i for i, m in enumerate(entries) if m.cls is CORSMiddleware]
        json_500 = [i for i, m in enumerate(entries) if m.kwargs.get("dispatch") is app_module.json_500]
        assert cors and json_500 and cors[0] < json_500[0]


def test_the_real_app_json_500_carries_the_cors_headers(monkeypatch):
    with real_app_with_cors(monkeypatch) as application:
        monkeypatch.setattr(app_module, "rt", Runtime(seed_cases=["agent_wrong_size"], force_rules=True))

        def boom(dispute_id):
            raise RuntimeError("boom secret")

        monkeypatch.setattr(app_module.rt, "analyze", boom)
        response = TestClient(application).post("/api/disputes/PP-D-2000/analyze", headers={"Origin": ORIGIN})
        assert response.status_code == 500 and response.json() == {"detail": "Internal server error"}
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert "boom secret" not in response.text
