"""The AG Studio AI proxy: gating, validation, rate limits, the Groq call and error mapping. No network, no model."""

import ast
import asyncio
import inspect
import json
import logging
import sys
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
    MAX_MESSAGES,
    MAX_OUTPUT_TOKENS,
    MAX_TEXT_CHARS,
    MAX_TOOLS,
    SHORT_WINDOW,
    _RateLimiter,
    make_studio_ai_router,
)

URL = "/api/studio/ai"
API_KEY = "k"  # short on purpose: the happy path checks the Bearer header against it
KEY_MARKER = "gsk-KEY-MARKER"  # distinctive, so a leak into a response or a log is unmistakable
ROOM = 10**9  # a limit no test reaches, for the tests that exercise other limits
VALID_TURN = {"messages": [{"role": "user", "content": "hello"}]}
TOOL = {"type": "function", "function": {"name": "lookup_order", "parameters": {"type": "object"}}}
CALL = {"id": "call_1", "type": "function", "function": {"name": "lookup_order", "arguments": '{"order_id": "PP-1"}'}}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def roomy_output_share(monkeypatch):
    """Most tests exercise the other limits, so the output-token share is set high here. It is tested on its own."""
    monkeypatch.setattr(studio_ai, "STUDIO_OUTPUT_TOKENS_PER_MINUTE", ROOM)


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


def test_an_oversized_body_without_a_length_is_refused_before_it_is_all_read():
    handler, calls = answer()
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = FastAPI()
    app.include_router(make_studio_ai_router(API_KEY, "m", client=upstream, clock=FakeClock()))
    chunk = b"x" * 8192
    consumed: list[int] = []

    async def chunks():
        for index in range(1000):
            consumed.append(index)
            yield chunk

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            return await http.post(URL, content=chunks())

    resp = asyncio.run(send())
    assert resp.status_code == 413
    assert resp.json() == {"detail": "Request too large."}
    assert len(consumed) <= MAX_BODY_BYTES // len(chunk) + 2
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
    pytest.param({"messages": [{"role": "user", "content": "hi"}] * (MAX_MESSAGES + 1)}, id="too-many-messages"),
    pytest.param(
        {"messages": [{"role": "user", "content": "hi"}], "tools": [TOOL] * (MAX_TOOLS + 1)}, id="too-many-tools"
    ),
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
    handler, calls = answer()
    client, clock = make_client(handler)
    for _ in range(CLIENT_LIMIT):
        assert post(client, "10.0.0.1").status_code == 200
    blocked = post(client, "10.0.0.1")
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many AI requests. Try again shortly."}
    assert int(blocked.headers["Retry-After"]) >= 1
    assert len(calls) == CLIENT_LIMIT
    assert post(client, "10.0.0.2").status_code == 200
    clock.now += SHORT_WINDOW + 1
    assert post(client, "10.0.0.1").status_code == 200


def test_a_spoofed_first_forwarded_hop_does_not_open_a_new_client_bucket():
    handler, calls = answer()
    client, _ = make_client(handler)
    for i in range(CLIENT_LIMIT):
        assert post(client, f"spoof-{i}, 10.9.9.9").status_code == 200
    blocked = post(client, "spoof-new, 10.9.9.9")
    assert blocked.status_code == 429
    assert len(calls) == CLIENT_LIMIT


def test_client_key_is_the_rightmost_forwarded_hop_cut_to_64_characters():
    handler, _ = answer()
    client, _ = make_client(handler)
    base = "a" * 64
    for i in range(CLIENT_LIMIT):
        assert post(client, f"10.8.0.{i}, {base}-{i}").status_code == 200
    assert post(client, f"10.8.1.1, {base}-x").status_code == 429


def test_the_whole_service_has_a_global_limit(monkeypatch):
    monkeypatch.setattr(studio_ai, "GLOBAL_LIMIT", 2)
    handler, calls = answer()
    client, _ = make_client(handler)
    assert post(client, "10.1.0.1").status_code == 200
    assert post(client, "10.1.0.2").status_code == 200
    blocked = post(client, "10.1.0.3")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert len(calls) == 2


def test_the_day_has_a_limit_that_resets_after_a_day(monkeypatch):
    monkeypatch.setattr(studio_ai, "DAILY_LIMIT", 2)
    handler, calls = answer()
    client, clock = make_client(handler)
    assert post(client, "10.2.0.1").status_code == 200
    assert post(client, "10.2.0.2").status_code == 200
    blocked = post(client, "10.2.0.3")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert len(calls) == 2
    clock.now += DAY_WINDOW + 1
    assert post(client, "10.2.0.3").status_code == 200


def test_the_output_token_share_caps_replies_a_minute(monkeypatch):
    monkeypatch.setattr(studio_ai, "STUDIO_OUTPUT_TOKENS_PER_MINUTE", 2 * MAX_OUTPUT_TOKENS)
    handler, calls = answer()
    client, clock = make_client(handler)
    assert post(client, "10.3.0.1").status_code == 200
    assert post(client, "10.3.0.2").status_code == 200
    blocked = post(client, "10.3.0.3")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert len(calls) == 2
    clock.now += SHORT_WINDOW + 1
    assert post(client, "10.3.0.3").status_code == 200


def test_a_refused_client_leaves_no_entry_behind():
    limiter = _RateLimiter(FakeClock(), client_limit=2, global_limit=1, daily_limit=10, output_limit=10)
    assert limiter.acquire("a") is None
    assert limiter.acquire("b") == 60
    assert "b" not in limiter._clients
    assert "a" in limiter._clients


def _roomy_limiter(clock: FakeClock) -> _RateLimiter:
    return _RateLimiter(clock, client_limit=2, global_limit=ROOM, daily_limit=ROOM, output_limit=ROOM)


def test_clients_whose_hits_have_expired_are_dropped_on_the_next_request():
    clock = FakeClock()
    limiter = _roomy_limiter(clock)
    for name in ("a", "b", "c"):
        assert limiter.acquire(name) is None
    clock.now += SHORT_WINDOW + 1
    assert limiter.acquire("new") is None
    assert set(limiter._clients) == {"new"}


def test_thousands_of_allowed_clients_leave_nothing_behind_once_they_expire():
    clock = FakeClock()
    limiter = _roomy_limiter(clock)
    for i in range(500):
        assert limiter.acquire(f"client-{i}") is None
    assert len(limiter._clients) == 500
    clock.now += SHORT_WINDOW + 1
    limiter.acquire("one")
    assert set(limiter._clients) == {"one"}


def test_one_shot_clients_over_time_keep_the_table_small():
    clock = FakeClock()
    limiter = _roomy_limiter(clock)
    for i in range(1000):
        clock.now += 1
        assert limiter.acquire(f"client-{i}") is None
        assert len(limiter._clients) <= SHORT_WINDOW


@pytest.mark.parametrize("status", [401, 403, 500])
def test_upstream_auth_and_server_failures_are_502(status):
    client, _ = make_client(lambda request: httpx.Response(status, text="UPSTREAM-SECRET-BODY"), api_key=KEY_MARKER)
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 502
    assert resp.json() == {"detail": "The AI model request failed."}
    assert "UPSTREAM-SECRET-BODY" not in resp.text
    assert KEY_MARKER not in resp.text


@pytest.mark.parametrize(
    ("header", "expected"),
    [("7", "7"), ("999", "60"), ("0", "1"), ("soon", "5"), (None, "5")],
)
def test_upstream_busy_is_429_with_a_clamped_retry_after(header, expected):
    headers = {} if header is None else {"Retry-After": header}
    client, _ = make_client(
        lambda request: httpx.Response(429, headers=headers, text="UPSTREAM-SECRET-BODY"), api_key=KEY_MARKER
    )
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "The AI model is busy. Try again shortly."}
    assert resp.headers["Retry-After"] == expected
    assert "UPSTREAM-SECRET-BODY" not in resp.text
    assert KEY_MARKER not in resp.text


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        (httpx.ReadTimeout("UPSTREAM-SECRET-BODY"), 504, "The AI model timed out."),
        (httpx.ConnectError("UPSTREAM-SECRET-BODY"), 502, "The AI model could not be reached."),
        (httpx.DecodingError("UPSTREAM-SECRET-BODY"), 502, "The AI model request failed."),
    ],
)
def test_transport_failures_are_mapped_without_leaking_detail(error, status, detail):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    client, _ = make_client(handler, api_key=KEY_MARKER)
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == status
    assert resp.json() == {"detail": detail}
    assert "UPSTREAM-SECRET-BODY" not in resp.text
    assert KEY_MARKER not in resp.text


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
    client, _ = make_client(lambda request: make_response(), api_key=KEY_MARKER)
    resp = client.post(URL, json=VALID_TURN)
    assert resp.status_code == 502
    assert resp.json() == {"detail": "The AI model request failed."}
    assert "UPSTREAM-SECRET-BODY" not in resp.text
    assert KEY_MARKER not in resp.text


def test_logs_keep_the_status_and_drop_the_key_the_body_and_the_prompt(caplog):
    caplog.set_level(logging.WARNING, logger="rebuttal.studio_ai")
    client, _ = make_client(lambda request: httpx.Response(401, text="UPSTREAM-SECRET-BODY"), api_key=KEY_MARKER)
    client.post(URL, json={"messages": [{"role": "user", "content": "PROMPT-TEXT-XYZ"}]})
    studio_records = [record for record in caplog.records if record.name == "rebuttal.studio_ai"]
    assert any(record.getMessage() == "Studio AI upstream status=401" for record in studio_records)
    assert "UPSTREAM-SECRET-BODY" not in caplog.text
    assert "PROMPT-TEXT-XYZ" not in caplog.text
    assert KEY_MARKER not in caplog.text


FORBIDDEN_IMPORTS = {"paypal", "approval", "app", "runtime", "agent", "demo", "demo_api", "config"}
ALLOWED_TOP_LEVEL_IMPORTS = set(sys.stdlib_module_names) | {"httpx", "fastapi", "pydantic"}


def _module_tree() -> ast.AST:
    return ast.parse(Path(studio_ai.__file__).read_text(encoding="utf-8"))


def test_the_module_imports_nothing_from_the_paypal_or_app_side():
    names: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            names.update(alias.name for alias in node.names)
    assert not names & FORBIDDEN_IMPORTS


def test_the_module_imports_only_stdlib_httpx_fastapi_and_pydantic_and_no_relative_modules():
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"relative import on line {node.lineno}"
            modules = [node.module or ""]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
        for module in modules:
            assert module.split(".")[0] in ALLOWED_TOP_LEVEL_IMPORTS, f"{module} on line {node.lineno}"


def test_the_factory_takes_only_the_key_model_client_and_clock():
    assert list(inspect.signature(make_studio_ai_router).parameters) == ["api_key", "model", "client", "clock"]
