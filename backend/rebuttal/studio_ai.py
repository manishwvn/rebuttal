"""Read-only proxy for the AG Studio AI assistant.

Forwards AG Studio Agent Framework chat turns from the browser to Groq's OpenAI-compatible chat-completions API, so the
Groq key never reaches the browser. It is read-only: it takes the key and the model as arguments, sends only chat
completions to Groq, and cannot reach PayPal.
"""

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

log = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"  # Groq's OpenAI-compatible chat endpoint
MAX_OUTPUT_TOKENS = 512  # one reply; the free tier allows 1,000 output tokens a minute for the whole key
MAX_BODY_BYTES = 131_072  # 128 KiB: caps the bytes read and parsed per request
MAX_MESSAGES = 200  # longest chat history forwarded in one turn
MAX_TOOLS = 64  # most tool definitions forwarded in one turn
MAX_TEXT_CHARS = 100_000  # longest content of one message
UPSTREAM_TIMEOUT = 30.0  # seconds; a slow model fails fast for the browser
SHORT_WINDOW = 60.0  # seconds, the window of the per-client and global limits
DAY_WINDOW = 86_400.0  # seconds, the window of the daily limit
CLIENT_LIMIT = 6  # requests per SHORT_WINDOW for one client, so one client cannot drain the shared quota
GLOBAL_LIMIT = 12  # requests per SHORT_WINDOW for the whole service, under Groq's 30 requests a minute
DAILY_LIMIT = 150  # requests per DAY_WINDOW, well under the 1K a day that the dispute agent also uses
RETRY_AFTER_DEFAULT = 5  # seconds, when Groq's 429 has no usable Retry-After
RETRY_AFTER_MAX = 60  # seconds, the longest Retry-After passed on to the browser


class ToolCallFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: str


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["function"]
    function: ToolCallFunction


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = Field(default=None, max_length=200)


class ToolChoiceFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


class ToolChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["function"]
    function: ToolChoiceFunction


class ResponseFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["json_object"]


class StudioAiRequest(BaseModel):
    """One chat turn. The client cannot choose the model, the output size, streaming or temperature."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=MAX_TOOLS)
    tool_choice: Literal["auto", "none", "required"] | ToolChoice | None = None
    response_format: ResponseFormat | None = None


class _RateLimiter:
    """Sliding windows for one client, the whole service and the day. A request counts only when all three have room."""

    def __init__(self, clock: Callable[[], float], *, client_limit: int, global_limit: int, daily_limit: int) -> None:
        self._clock = clock
        self._client_limit = client_limit
        self._global_limit = global_limit
        self._daily_limit = daily_limit
        self._lock = threading.Lock()
        self._clients: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._daily: deque[float] = deque()

    def acquire(self, client: str) -> int | None:
        """Count one request and return None, or return the whole seconds to wait (at least 1) when a window is full."""
        now = self._clock()
        with self._lock:
            hits = self._clients.setdefault(client, deque())
            waits = [
                _wait(hits, self._client_limit, SHORT_WINDOW, now),
                _wait(self._global, self._global_limit, SHORT_WINDOW, now),
                _wait(self._daily, self._daily_limit, DAY_WINDOW, now),
            ]
            blocking = [wait for wait in waits if wait is not None]
            if blocking:
                if not hits:
                    del self._clients[client]
                return max(1, math.ceil(max(blocking)))
            for window in (hits, self._global, self._daily):
                window.append(now)
            return None


def _wait(hits: deque[float], limit: int, window: float, now: float) -> float | None:
    """Drop hits older than the window. None when a slot is free, else the seconds until the oldest hit expires."""
    while hits and now - hits[0] >= window:
        hits.popleft()
    if len(hits) < limit:
        return None
    return hits[0] + window - now


def _client_key(request: Request) -> str:
    """The first X-Forwarded-For hop (cut to 64 characters), else the socket peer, else ''."""
    hop = request.headers.get("x-forwarded-for", "").split(",")[0].strip()[:64]
    if hop:
        return hop
    return request.client.host if request.client else ""


def _declared_length(request: Request) -> int:
    try:
        return int(request.headers.get("content-length", "0"))
    except ValueError:
        return 0  # not a length: the body is still checked once it is read


def _upstream_body(payload: StudioAiRequest, model: str) -> dict[str, Any]:
    """The validated turn plus the settings only this router chooses: model, output cap, no stream."""
    return payload.model_dump(exclude_none=True) | {
        "model": model,
        "max_completion_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "reasoning_format": "hidden",  # same as agent/llm.py: the model's reasoning stays out of the reply
    }


async def _forward(http: httpx.AsyncClient | None, api_key: str, body: dict[str, Any]) -> httpx.Response:
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        if http is None:
            async with httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT) as own:
                return await own.post(GROQ_CHAT_URL, json=body, headers=headers)
        return await http.post(GROQ_CHAT_URL, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        log.warning("Studio AI upstream error=%s", type(exc).__name__)
        raise HTTPException(504, "The AI model timed out.") from None
    except httpx.TransportError as exc:
        log.warning("Studio AI upstream error=%s", type(exc).__name__)
        raise HTTPException(502, "The AI model could not be reached.") from None


def _upstream_retry_after(value: str | None) -> int:
    try:
        return min(RETRY_AFTER_MAX, max(1, int(value)))  # int(None) raises TypeError for a missing header
    except (TypeError, ValueError):
        return RETRY_AFTER_DEFAULT


def _whitelist(data: Any, model: str) -> dict[str, Any]:
    """Keep only the fields the browser uses. Raises LookupError, TypeError or AttributeError on a malformed body."""
    choice = data["choices"][0]
    message = choice["message"]
    usage = data.get("usage")
    tool_calls = [
        {
            "id": call["id"],
            "type": "function",
            "function": {"name": call["function"]["name"], "arguments": call["function"]["arguments"]},
        }
        for call in message.get("tool_calls") or []
    ]
    return {
        "message": {"content": message.get("content"), "tool_calls": tool_calls},
        "finish_reason": choice.get("finish_reason"),
        "usage": {"prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"]}
        if usage
        else None,
        "model": data.get("model") or model,
    }


def _reply(response: httpx.Response, model: str) -> dict[str, Any]:
    if not response.is_success:
        log.warning("Studio AI upstream status=%s", response.status_code)
        if response.status_code == 429:
            retry = _upstream_retry_after(response.headers.get("retry-after"))
            raise HTTPException(429, "The AI model is busy. Try again shortly.", headers={"Retry-After": str(retry)})
        raise HTTPException(502, "The AI model request failed.")
    try:
        return _whitelist(response.json(), model)
    except (ValueError, LookupError, TypeError, AttributeError):
        log.warning("Studio AI upstream reply malformed")
        raise HTTPException(502, "The AI model request failed.") from None


def make_studio_ai_router(
    api_key: str | None,
    model: str,
    *,
    client: httpx.AsyncClient | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> APIRouter:
    """The /api/studio/ai routes. No auth here (app.py adds the token dependency); a falsy api_key disables them."""
    limiter = _RateLimiter(clock, client_limit=CLIENT_LIMIT, global_limit=GLOBAL_LIMIT, daily_limit=DAILY_LIMIT)
    router = APIRouter(prefix="/api/studio/ai", tags=["studio-ai"])

    @router.get("/status")
    async def status() -> dict[str, bool]:
        return {"enabled": bool(api_key)}

    @router.post("")
    async def chat(request: Request) -> dict[str, Any]:
        if not api_key:
            raise HTTPException(503, "The AI assistant is not configured.")
        if _declared_length(request) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large.")
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large.")
        retry = limiter.acquire(_client_key(request))
        if retry is not None:
            raise HTTPException(429, "Too many AI requests. Try again shortly.", headers={"Retry-After": str(retry)})
        try:
            payload = StudioAiRequest.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "Invalid AI request.") from None
        response = await _forward(client, api_key, _upstream_body(payload, model))
        return _reply(response, model)

    return router
