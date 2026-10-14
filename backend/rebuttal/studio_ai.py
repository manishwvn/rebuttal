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
MAX_OUTPUT_TOKENS = 256  # one reply; Groq counts max_tokens against the key's output tokens a minute up front
MAX_BODY_BYTES = 131_072  # 128 KiB: the body is read in chunks and refused past this, so memory stays bounded
MAX_MESSAGES = 200  # longest chat history forwarded in one turn
MAX_TOOLS = 64  # most tool definitions forwarded in one turn
MAX_TEXT_CHARS = 100_000  # longest content of one message
UPSTREAM_TIMEOUT = 30.0  # seconds; a slow model fails fast for the browser
SHORT_WINDOW = 60.0  # seconds, the window of the per-client and global limits
DAY_WINDOW = 86_400.0  # seconds, the window of the daily limit
CLIENT_LIMIT = 6  # requests per SHORT_WINDOW for one client, so one client cannot drain the shared quota
GLOBAL_LIMIT = 12  # requests per SHORT_WINDOW for the whole service, under Groq's 30 requests a minute
DAILY_LIMIT = 150  # requests per DAY_WINDOW, well under the 1K a day that the dispute agent also uses
# Groq's per-minute limits belong to one key that the dispute agent also uses, so the proxy draws from the agent's
# own TokenBudget (agent/llm.py), passed in by app.py. It books a turn only if the window keeps room for one dispute
# call afterwards, so a Studio chat is refused before it can push the dispute agent into a Groq 429.
KEEP_TOKENS = 3_000  # tokens a minute left free for one dispute call
KEEP_OUTPUT_TOKENS = 500  # output tokens a minute left free for one dispute call (llm.GROQ_MAX_TOKENS)
KEEP_REQUESTS = 2  # requests a minute left free for the dispute agent
BYTES_PER_TOKEN = 3  # a rough estimate, low on purpose because JSON tool schemas tokenize densely; not a count
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
    """Sliding windows for one client, the whole service and the day. A request counts only when every window has
    room. The token limits are not here: they come from the shared Groq budget."""

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        client_limit: int,
        global_limit: int,
        daily_limit: int,
    ) -> None:
        self._clock = clock
        self._client_limit = client_limit
        self._global_limit = global_limit
        self._daily_limit = daily_limit
        self._lock = threading.Lock()
        self._clients: dict[str, deque[tuple[float, int]]] = {}
        self._global: deque[tuple[float, int]] = deque()
        self._daily: deque[tuple[float, int]] = deque()

    def acquire(self, client: str) -> int | None:
        """Count one request and return None, or return the whole seconds to wait (at least 1) when a window is full."""
        now = self._clock()
        with self._lock:
            self._sweep(now)
            hits = self._clients.setdefault(client, deque())
            # Each entry is (window, cost of this request in that window, the window's limit, the window's span).
            windows = [
                (hits, 1, self._client_limit, SHORT_WINDOW),
                (self._global, 1, self._global_limit, SHORT_WINDOW),
                (self._daily, 1, self._daily_limit, DAY_WINDOW),
            ]
            waits = [_wait(window, cost, limit, span, now) for window, cost, limit, span in windows]
            blocking = [wait for wait in waits if wait is not None]
            if blocking:
                if not hits:
                    del self._clients[client]
                return max(1, math.ceil(max(blocking)))
            for window, cost, _, _ in windows:
                window.append((now, cost))
            return None

    def _sweep(self, now: float) -> None:
        """Forget clients whose hits have all left the window, so the table holds only clients still being counted."""
        for client in list(self._clients):
            hits = self._clients[client]
            _prune(hits, SHORT_WINDOW, now)
            if not hits:
                del self._clients[client]


def _prune(window: deque[tuple[float, int]], span: float, now: float) -> None:
    while window and now - window[0][0] >= span:
        window.popleft()


def _wait(window: deque[tuple[float, int]], cost: int, limit: int, span: float, now: float) -> float | None:
    """Drop entries older than the span. None when the cost fits under the limit, else the seconds until enough of the
    oldest entries have expired for it to fit. A cost over the limit by itself never fits, so it waits one whole span."""
    _prune(window, span, now)
    used = sum(size for _, size in window)
    if used + cost <= limit:
        return None
    for when, size in window:
        used -= size
        if used + cost <= limit:
            return when + span - now
    return span


def _client_key(request: Request) -> str:
    """The rightmost X-Forwarded-For hop (cut to 64 characters), else the socket peer, else ''.

    The rightmost hop is the one the edge proxy appends. The first hop is whatever the caller sent, so keying on it
    would let a caller open a new per-client bucket on every request.
    """
    hop = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()[:64]
    if hop:
        return hop
    return request.client.host if request.client else ""


def _declared_length(request: Request) -> int:
    try:
        return int(request.headers.get("content-length", "0"))
    except ValueError:
        return 0  # not a length: the body is still checked once it is read


async def _read_body(request: Request) -> bytes:
    """Read the body chunk by chunk and stop past MAX_BODY_BYTES, so an oversized upload is never held whole."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Request too large.")
    return bytes(body)


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
    except httpx.HTTPError as exc:
        log.warning("Studio AI upstream error=%s", type(exc).__name__)
        if isinstance(exc, httpx.TimeoutException):
            raise HTTPException(504, "The AI model timed out.") from None
        if isinstance(exc, httpx.TransportError):
            raise HTTPException(502, "The AI model could not be reached.") from None
        raise HTTPException(502, "The AI model request failed.") from None  # e.g. an undecodable reply


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
    budget: Any,
) -> APIRouter:
    """The /api/studio/ai routes. No auth here (app.py adds the token dependency); a falsy api_key disables them.

    `budget` is the process-wide Groq TokenBudget shared with the dispute agent (try_reserve, tpm). It is required:
    settle and cancel only take its short state lock, so they are safe to call from the event loop."""
    limiter = _RateLimiter(
        clock,
        client_limit=CLIENT_LIMIT,
        global_limit=GLOBAL_LIMIT,
        daily_limit=DAILY_LIMIT,
    )
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
        body = await _read_body(request)
        try:
            payload = StudioAiRequest.model_validate_json(body)
        except ValidationError:
            raise HTTPException(422, "Invalid AI request.") from None  # before any limiter, so it costs no slot
        estimate = len(body) // BYTES_PER_TOKEN + MAX_OUTPUT_TOKENS
        if estimate + KEEP_TOKENS > budget.tpm:
            raise HTTPException(413, "Request too large.")  # more than the whole share: waiting would not help
        reservation, wait = budget.try_reserve(
            estimate, MAX_OUTPUT_TOKENS, keep_tokens=KEEP_TOKENS, keep_output=KEEP_OUTPUT_TOKENS, keep_requests=KEEP_REQUESTS
        )
        if reservation is None:
            raise HTTPException(
                429, "Too many AI requests. Try again shortly.", headers={"Retry-After": str(math.ceil(wait))}
            )
        retry = limiter.acquire(_client_key(request))
        if retry is not None:
            reservation.cancel()
            raise HTTPException(429, "Too many AI requests. Try again shortly.", headers={"Retry-After": str(retry)})
        try:
            response = await _forward(client, api_key, _upstream_body(payload, model))
        except HTTPException:
            reservation.cancel()  # timeout or connection error: Groq never counted the call
            raise
        if response.status_code >= 500:
            reservation.cancel()  # an upstream failure charged no tokens
        reply = _reply(response, model)
        usage = reply["usage"]
        if usage:
            reservation.settle(usage["prompt_tokens"] + usage["completion_tokens"])
        return reply

    return router
