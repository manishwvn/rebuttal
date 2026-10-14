"""The AG Studio AI proxy: gating, validation, rate limits, the Groq call and error mapping. No network, no model."""

import ast
import inspect
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rebuttal import studio_ai
from rebuttal.studio_ai import (
    CLIENT_LIMIT,
    DAY_WINDOW,
    GROQ_CHAT_URL,
    MAX_BODY_BYTES,
    MAX_OUTPUT_TOKENS,
    MAX_TEXT_CHARS,
    SHORT_WINDOW,
    _RateLimiter,
    make_studio_ai_router,
)

URL = "/api/studio/ai"
API_KEY = "k"
VALID_TURN = {"messages": [{"role": "user", "content": "hello"}]}
TOOL = {"type": "function", "function": {"name": "lookup_order", "parameters": {"type": "object"}}}
CALL = {"id": "call_1", "type": "function", "function": {"name": "lookup_order", "arguments": '{"order_id": "PP-1"}'}}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_client(handler, *, api_key: str | None = API_KEY, clock: FakeClock | None = None):
    clock = clock or FakeClock()
    app = FastAPI()
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.include_router(make_studio_ai_router(api_key, "m", client=upstream, clock=clock))
    return TestClient(app), clock


def answer(content: str = "hello"):
    """A handler that answers every call with a valid reply, and the list of requests it received."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=reply_body(content))

    return handler, calls


def reply_body(content: str) -> dict:
    """A valid Groq reply carrying fields the proxy must never pass on."""
    return {
        "id": "chatcmpl-1",
        "model": "m",
        "api_key": "gsk-LEAKED",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "debug": "UPSTREAM-SECRET-BODY"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }


def post(client: TestClient, forwarded_for: str = "10.0.0.1", turn: dict = VALID_TURN):
    return client.post(URL, json=turn, headers={"X-Forwarded-For": forwarded_for})


@pytest.mark.parametrize("api_key", [API_KEY, None, ""])
def test_status_reports_enabled_only_when_a_key_is_set(api_key):
    handler, _ = answer()
    client, _ = make_client(handler, api_key=api_key)
    assert client.get(f"{URL}/status").json() == {"enabled": bool(api_key)}


def test_post_without_a_key_is_503_and_never_reaches_upstream():
    handler, calls = answer()
    client, _ = make_client(handler, api_key=None)
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "The AI assistant is not configured."}
    assert calls == []


def test_a_body_over_the_limit_is_413_by_size_and_by_declared_length():
    handler, calls = answer()
    client, _ = make_client(handler)
    # A generator is sent without Content-Length, so only the measured body can trip the limit.
    big_chunks = iter([b'{"messages":[{"role":"user","content":"', b"x" * MAX_BODY_BYTES, b'"}]}'])
    too_big = client.post(URL, content=big_chunks)
    assert too_big.status_code == 413
    assert too_big.json() == {"detail": "Request too large."}
    declared = client.post(URL, content=b"{}", headers={"Content-Length": "999999999"})
    assert declared.status_code == 413
    assert declared.json() == {"detail": "Request too large."}
    assert calls == []


def test_a_content_length_that_is_not_a_number_falls_back_to_the_measured_body():
    handler, _ = answer()
    client, _ = make_client(handler)
    resp = client.post(URL, json=VALID_TURN, headers={"Content-Length": "not-a-number"})
    assert resp.status_code == 200


def test_without_an_injected_client_each_call_opens_one_with_the_upstream_timeout(monkeypatch):
    real_client = httpx.AsyncClient
    timeouts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reply_body("hello"))

    def opened_client(**kwargs):
        timeouts.append(kwargs["timeout"])
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(studio_ai.httpx, "AsyncClient", opened_client)
    app = FastAPI()
    app.include_router(make_studio_ai_router(API_KEY, "m", clock=FakeClock()))
    client = TestClient(app)
    assert client.post(URL, json=VALID_TURN).status_code == 200
    assert client.post(URL, json=VALID_TURN).status_code == 200
    assert timeouts == [studio_ai.UPSTREAM_TIMEOUT, studio_ai.UPSTREAM_TIMEOUT]


INVALID_TURNS = [
    pytest.param(
        {"messages": [{"role": "user", "content": "hi"}], "stream": "SECRET-INPUT-MARKER"}, id="unknown-field"
    ),
    pytest.param({"messages": [{"role": "bot", "content": "SECRET-INPUT-MARKER"}]}, id="bad-role"),
    pytest.param({"messages": []}, id="empty-messages"),
    pytest.param(
        {"messages": [{"role": "user", "content": "hi"}], "tool_choice": "SECRET-INPUT-MARKER"}, id="bad-tool-choice"
    ),
    pytest.param({"messages": [{"role": "user", "content": "hi"}], "model": "SECRET-INPUT-MARKER"}, id="client-model"),
    pytest.param({"messages": [{"role": "user", "content": "x" * (MAX_TEXT_CHARS + 1)}]}, id="content-too-long"),
    pytest.param(b"{not json SECRET-INPUT-MARKER", id="not-json"),
]


@pytest.mark.parametrize("payload", INVALID_TURNS)
def test_invalid_turns_are_422_and_echo_none_of_the_input(payload):
    handler, calls = answer()
    client, _ = make_client(handler)
    if isinstance(payload, bytes):
        resp = client.post(URL, content=payload)
    else:
        resp = client.post(URL, json=payload)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Invalid AI request."}
    assert "SECRET-INPUT-MARKER" not in resp.text
    assert calls == []


def test_a_turn_reaches_groq_with_only_the_settings_the_router_chooses():
    handler, calls = answer()
    client, _ = make_client(handler)
    turn = {
        "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "where is my order?"}],
        "tools": [TOOL],
        "tool_choice": "auto",
        "response_format": {"type": "json_object"},
    }
    assert client.post(URL, json=turn).status_code == 200
    (sent,) = calls
    assert str(sent.url) == GROQ_CHAT_URL
    assert sent.headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(sent.content) == {
        **turn,
        "model": "m",
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "reasoning_format": "hidden",
    }


def test_the_reply_is_the_whitelisted_shape_only():
    handler, _ = answer("hello")
    client, _ = make_client(handler)
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 200
    assert resp.json() == {
        "message": {"content": "hello", "tool_calls": []},
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        "model": "m",
    }
    assert "UPSTREAM-SECRET-BODY" not in resp.text
    assert "gsk-LEAKED" not in resp.text


def test_tool_calls_round_trip():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        message = {"role": "assistant", "content": None, "tool_calls": [CALL]}
        return httpx.Response(
            200, json={"choices": [{"message": message, "finish_reason": "tool_calls"}], "model": "m"}
        )

    client, _ = make_client(handler)
    turn = {
        "messages": [
            {"role": "user", "content": "where is it?"},
            {"role": "assistant", "tool_calls": [CALL]},
            {"role": "tool", "tool_call_id": "call_1", "content": "shipped"},
        ],
        "tools": [TOOL],
    }
    resp = client.post(URL, json=turn)
    assert seen["body"]["messages"] == turn["messages"]
    assert seen["body"]["tools"] == [TOOL]
    assert resp.json() == {
        "message": {"content": None, "tool_calls": [CALL]},
        "finish_reason": "tool_calls",
        "usage": None,
        "model": "m",
    }


def test_each_client_gets_client_limit_requests_per_window_and_then_recovers():
    handler, _ = answer()
    client, clock = make_client(handler)
    for _ in range(CLIENT_LIMIT):
        assert post(client, "10.0.0.1").status_code == 200
    blocked = post(client, "10.0.0.1")
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many AI requests. Try again shortly."}
    assert int(blocked.headers["Retry-After"]) >= 1
    assert post(client, "10.0.0.2").status_code == 200
    clock.now += SHORT_WINDOW + 1
    assert post(client, "10.0.0.1").status_code == 200


def test_client_key_is_the_first_forwarded_hop_cut_to_64_characters():
    handler, _ = answer()
    client, _ = make_client(handler)
    base = "a" * 64
    for i in range(CLIENT_LIMIT):
        assert post(client, f"{base}-{i}").status_code == 200
    assert post(client, f"{base}-x, 10.9.9.9").status_code == 429


def test_the_whole_service_has_a_global_limit(monkeypatch):
    monkeypatch.setattr(studio_ai, "GLOBAL_LIMIT", 2)
    handler, _ = answer()
    client, _ = make_client(handler)
    assert post(client, "10.1.0.1").status_code == 200
    assert post(client, "10.1.0.2").status_code == 200
    blocked = post(client, "10.1.0.3")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_the_day_has_a_limit_that_resets_after_a_day(monkeypatch):
    monkeypatch.setattr(studio_ai, "DAILY_LIMIT", 2)
    handler, _ = answer()
    client, clock = make_client(handler)
    assert post(client, "10.2.0.1").status_code == 200
    assert post(client, "10.2.0.2").status_code == 200
    blocked = post(client, "10.2.0.3")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    clock.now += DAY_WINDOW + 1
    assert post(client, "10.2.0.3").status_code == 200


def test_a_refused_client_leaves_no_entry_behind():
    limiter = _RateLimiter(FakeClock(), client_limit=2, global_limit=1, daily_limit=10)
    assert limiter.acquire("a") is None
    assert limiter.acquire("b") == 60
    assert "b" not in limiter._clients
    assert "a" in limiter._clients


@pytest.mark.parametrize("status", [401, 403, 500])
def test_upstream_auth_and_server_failures_are_502(status):
    client, _ = make_client(lambda request: httpx.Response(status, text="UPSTREAM-SECRET-BODY"))
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 502
    assert resp.json() == {"detail": "The AI model request failed."}
    assert "UPSTREAM-SECRET-BODY" not in resp.text


@pytest.mark.parametrize(
    ("header", "expected"),
    [("7", "7"), ("999", "60"), ("0", "1"), ("soon", "5"), (None, "5")],
)
def test_upstream_busy_is_429_with_a_clamped_retry_after(header, expected):
    headers = {} if header is None else {"Retry-After": header}
    client, _ = make_client(lambda request: httpx.Response(429, headers=headers, text="UPSTREAM-SECRET-BODY"))
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "The AI model is busy. Try again shortly."}
    assert resp.headers["Retry-After"] == expected
    assert "UPSTREAM-SECRET-BODY" not in resp.text


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (httpx.ReadTimeout("UPSTREAM-SECRET-BODY"), 504, "The AI model timed out."),
        (httpx.ConnectError("UPSTREAM-SECRET-BODY"), 502, "The AI model could not be reached."),
    ],
)
def test_transport_failures_are_mapped_without_leaking_detail(error, status, detail):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    client, _ = make_client(handler)
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == status
    assert resp.json() == {"detail": detail}
    assert "UPSTREAM-SECRET-BODY" not in resp.text


@pytest.mark.parametrize(
    "make_response",
    [
        pytest.param(lambda: httpx.Response(200, text="UPSTREAM-SECRET-BODY"), id="not-json"),
        pytest.param(lambda: httpx.Response(200, json={"choices": []}), id="no-choices"),
        pytest.param(lambda: httpx.Response(200, json={"model": "m"}), id="no-message"),
        pytest.param(lambda: httpx.Response(200, json=["UPSTREAM-SECRET-BODY"]), id="not-an-object"),
    ],
)
def test_a_malformed_success_reply_is_502(make_response):
    client, _ = make_client(lambda request: make_response())
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 502
    assert resp.json() == {"detail": "The AI model request failed."}
    assert "UPSTREAM-SECRET-BODY" not in resp.text


def test_logs_keep_the_status_and_drop_the_key_the_body_and_the_prompt(caplog):
    caplog.set_level(logging.WARNING, logger="rebuttal.studio_ai")
    client, _ = make_client(lambda request: httpx.Response(401, text="UPSTREAM-SECRET-BODY"))
    client.post(URL, json={"messages": [{"role": "user", "content": "PROMPT-TEXT-XYZ"}]})
    studio_records = [record for record in caplog.records if record.name == "rebuttal.studio_ai"]
    assert any(record.getMessage() == "Studio AI upstream status=401" for record in studio_records)
    assert "UPSTREAM-SECRET-BODY" not in caplog.text
    assert "PROMPT-TEXT-XYZ" not in caplog.text
    assert all(API_KEY not in record.getMessage() for record in studio_records)


FORBIDDEN_IMPORTS = {"paypal", "approval", "app", "runtime", "agent", "demo", "demo_api", "config"}


def test_the_module_imports_nothing_from_the_paypal_or_app_side():
    tree = ast.parse(Path(studio_ai.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            names.update(alias.name for alias in node.names)
    assert not names & FORBIDDEN_IMPORTS


def test_the_factory_takes_only_the_key_model_client_and_clock():
    assert list(inspect.signature(make_studio_ai_router).parameters) == ["api_key", "model", "client", "clock"]
