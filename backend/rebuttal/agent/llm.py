"""Model-backed decisions: LangChain chat models with schema-validated (Pydantic) output.

Only the `decide` step talks to a model. The model reads the buyer's words and the pre-computed facts and returns a
`DecisionOut`; everything else (facts, guard, planning, PayPal calls) stays deterministic code.

Provider order, picked by which key is set: Anthropic, then Groq, then NVIDIA (OpenAI-compatible), else the rules
baseline. Temperature is 0 everywhere (LangChain sends 1e-8 to Groq, which rejects 0). Groq's free tier is paced by
`TokenBudget`. Anthropic and Groq use their native JSON-schema output; NVIDIA uses forced tool calling.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel, Field, field_validator

from ..config import Settings
from .facts import CaseFile
from .reasoner import (
    RESOLUTIONS,
    SYSTEM_PROMPT,
    TEMPERATURE,
    Decision,
    RuleReasoner,
    build_payload,
    extract_decision_json,
)

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
ResolutionName = Literal[tuple(RESOLUTIONS)]  # type: ignore[valid-type]


class ModelCallFailed(RuntimeError):
    """A strict reasoner (evals) could not get a decision from its model. Never silently replaced by the rules."""

    def __init__(self, message: str, *, rate_limited: bool = False):
        super().__init__(message)
        self.rate_limited = rate_limited


def is_rate_limit(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return (getattr(exc, "status_code", None) == 429 or "ratelimit" in text or "rate limit" in text
            or "rate_limit" in text or "quota" in text or "429" in text)


class DecisionOut(BaseModel):
    """The resolution for one dispute, with the reasoning and the drafts for the buyer or PayPal."""

    buyer_wants: str = Field(description="One sentence: what the buyer actually wants.")
    resolution: ResolutionName = Field(description="The chosen resolution; one of the allowed resolutions.")
    partial_refund_pct: int | None = Field(
        default=None, description="Integer 5-50, only for OFFER_PARTIAL_REFUND, otherwise null.")
    confidence: float = Field(description="0.0 to 1.0.")
    reasoning: list[str] = Field(description="3-5 short bullet strings citing facts or policies.")
    message_to_buyer: str = Field(description="Friendly, under 90 words, signed 'Juniper & Oak'.")
    evidence_summary: str = Field(
        default="", description="2-4 factual sentences for PayPal, only if submitting evidence, otherwise empty.")

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, value))

    @field_validator("partial_refund_pct")
    @classmethod
    def _clamp_pct(cls, value: int | None) -> int | None:
        return None if value is None else max(5, min(50, value))

    @field_validator("reasoning")
    @classmethod
    def _cap_reasoning(cls, value: list[str]) -> list[str]:
        return value[:5]

    def to_decision(self, source: str) -> Decision:
        return Decision(
            resolution=self.resolution, confidence=self.confidence, reasoning=list(self.reasoning),
            buyer_wants=self.buyer_wants, message_to_buyer=self.message_to_buyer,
            evidence_summary=self.evidence_summary, partial_refund_pct=self.partial_refund_pct, source=source,
        )


class TokenBudget:
    """Keeps calls inside a provider's per-minute limits (sliding 60s window): requests, total tokens, and
    reserved output tokens (providers count a request's max_tokens against the output limit up front).

    Thread-safe. `reserve()` blocks until the call fits and books its estimate straight away, so two threads cannot
    both think there is room; `Reservation.settle()` swaps the estimate for the tokens the call really used."""

    def __init__(self, tpm: int, rpm: int, otpm: int | None = None, clock=time.monotonic, sleep=time.sleep):
        self.tpm, self.rpm, self.otpm, self._clock, self._sleep = tpm, rpm, otpm, clock, sleep
        self._events: list[list] = []  # [time, tokens, reserved output]
        self._lock = threading.Lock()

    def reserve(self, estimate: int, output: int = 0) -> "Reservation":
        with self._lock:  # held while waiting, which queues other callers behind this one
            while True:
                now = self._clock()
                self._events = [e for e in self._events if now - e[0] < 60]
                used, reserved = sum(e[1] for e in self._events), sum(e[2] for e in self._events)
                fits = (len(self._events) < self.rpm and used + estimate <= self.tpm
                        and (self.otpm is None or reserved + output <= self.otpm))
                if fits or not self._events:
                    event = [now, estimate, output]
                    self._events.append(event)
                    return Reservation(event, self._lock)
                self._sleep(max(0.5, 60 - (now - self._events[0][0])))


class Reservation:
    def __init__(self, event: list, lock: threading.Lock):
        self._event, self._lock = event, lock

    def settle(self, tokens: int) -> None:
        with self._lock:
            self._event[1] = tokens


def _total_tokens(raw: AIMessage | None) -> int:
    if raw is None:
        return 0
    usage = getattr(raw, "usage_metadata", None) or {}
    if usage.get("total_tokens"):
        return int(usage["total_tokens"])
    return int((getattr(raw, "response_metadata", None) or {}).get("token_usage", {}).get("total_tokens") or 0)


class ModelReasoner:
    """Decides with a chat model whose output is validated against `DecisionOut`.

    `structured` is a runnable from `chat_model.with_structured_output(DecisionOut, include_raw=True)`, so it yields
    {"raw": AIMessage, "parsed": DecisionOut | None, "parsing_error": Exception | None}. If a provider returns prose
    around the JSON instead of a tool call, the JSON is pulled out of the raw text and validated the same way. Any
    failure (network, rate limit, invalid output) falls back to the rules baseline and says so in the guard notes.
    """

    def __init__(self, *, name: str, model_name: str, structured: Runnable, chat_model=None,
                 max_output_tokens: int = 1024, throttle: TokenBudget | None = None,
                 fallback: RuleReasoner | None = None, strict: bool = False):
        self.strict = strict  # True (evals): a failed model call raises ModelCallFailed instead of using the rules
        self.name = name
        self.model_name = model_name
        self.chat_model = chat_model  # the underlying LangChain chat model, for inspection
        self._structured = structured
        self._max_output_tokens = max_output_tokens
        self._throttle = throttle
        self._fallback = fallback or RuleReasoner()
        self.tokens_used = 0

    def decide(self, case: CaseFile, config: RunnableConfig | None = None) -> Decision:
        try:
            payload = json.dumps(build_payload(case), indent=2, default=str)
            reservation = None
            if self._throttle:
                reservation = self._throttle.reserve((len(SYSTEM_PROMPT) + len(payload)) // 3 + self._max_output_tokens,
                                                     self._max_output_tokens)
            result = self._structured.invoke(
                [SystemMessage(SYSTEM_PROMPT), HumanMessage(payload)], config=config)
            raw = result.get("raw")
            used = _total_tokens(raw)
            self.tokens_used += used
            if reservation:
                reservation.settle(used)
            parsed = result.get("parsed")
            if parsed is None:
                text = raw.text if isinstance(raw, AIMessage) else ""
                try:
                    parsed = DecisionOut.model_validate(extract_decision_json(text))
                except Exception as exc:
                    raise ValueError(f"no valid decision in model output ({result.get('parsing_error') or exc})") from exc
            return parsed.to_decision(self.name)
        except Exception as exc:  # network, rate limit, invalid output
            if self.strict:
                raise ModelCallFailed(f"{self.name} call failed ({type(exc).__name__}: {str(exc)[:300]})",
                                      rate_limited=is_rate_limit(exc)) from exc
            d = self._fallback.decide(case)
            d.guard_notes.append(f"Model call failed ({type(exc).__name__}: {str(exc)[:600]}); used rules baseline.")
            return d


# One budget per process: the evals build a reasoner per case, and the limits are per account.
_GROQ_BUDGET: TokenBudget | None = None
# Groq free tier for qwen/qwen3.8-27b: 30 requests/min, 1K/day, 8K tokens/min, 200K/day, and (from the 429 error)
# 1,000 output tokens/min. max_tokens is reserved against that, so 500 means two calls a minute.
GROQ_LIMITS = {"tpm": 8000, "rpm": 30, "otpm": 1000}
GROQ_MAX_TOKENS = 500


def _groq_budget() -> TokenBudget:
    global _GROQ_BUDGET
    if _GROQ_BUDGET is None:
        _GROQ_BUDGET = TokenBudget(**GROQ_LIMITS)
    return _GROQ_BUDGET


# NVIDIA build free tier: 40 requests/min (no published token limit). Stay a little under it.
NVIDIA_LIMITS = {"tpm": 10**9, "rpm": 30}
_NVIDIA_BUDGET: TokenBudget | None = None


def _nvidia_budget() -> TokenBudget:
    global _NVIDIA_BUDGET
    if _NVIDIA_BUDGET is None:
        _NVIDIA_BUDGET = TokenBudget(**NVIDIA_LIMITS)
    return _NVIDIA_BUDGET


PROVIDERS = ("anthropic", "groq", "nvidia")


def build_reasoner(settings: Settings, *, provider: str | None = None, strict: bool = False) -> ModelReasoner | None:
    """The model reasoner for `provider` (or the first provider with a key), or None (rules baseline).

    An explicit provider without its key raises: the caller asked for a specific model."""
    provider = provider or settings.provider
    if provider:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}; use one of {', '.join(PROVIDERS)}")
        if not getattr(settings, f"{'anthropic' if provider == 'anthropic' else provider}_api_key"):
            raise ValueError(f"provider {provider} needs its API key in backend/.env")
    want = lambda name: (provider == name) if provider else bool(getattr(settings, f"{name}_api_key"))  # noqa: E731
    r = _build(settings, want)
    if r:
        r.strict = strict
    return r


def _build(settings: Settings, want) -> ModelReasoner | None:
    if want("anthropic") and settings.anthropic_api_key:
        from langchain_anthropic import ChatAnthropic

        chat = ChatAnthropic(model=settings.model, api_key=settings.anthropic_api_key, temperature=TEMPERATURE,
                             max_tokens=1200, timeout=60, max_retries=2)
        return ModelReasoner(name="claude", model_name=settings.model, max_output_tokens=1200, chat_model=chat,
                             structured=chat.with_structured_output(DecisionOut, method="json_schema",
                                                                    include_raw=True))
    if want("groq") and settings.groq_api_key:
        from langchain_groq import ChatGroq

        chat = ChatGroq(model=settings.groq_model, api_key=settings.groq_api_key, temperature=TEMPERATURE,
                        max_tokens=GROQ_MAX_TOKENS, reasoning_format="hidden", timeout=60, max_retries=2)
        return ModelReasoner(name="groq", model_name=settings.groq_model, max_output_tokens=GROQ_MAX_TOKENS,
                             chat_model=chat, throttle=_groq_budget(),
                             structured=chat.with_structured_output(DecisionOut, method="json_schema",
                                                                    include_raw=True))
    if want("nvidia") and settings.nvidia_api_key:
        from langchain_openai import ChatOpenAI

        chat = ChatOpenAI(model=settings.nvidia_model, api_key=settings.nvidia_api_key, base_url=NVIDIA_BASE_URL,
                          temperature=TEMPERATURE, max_tokens=4096, timeout=240, max_retries=1)
        return ModelReasoner(name="nvidia", model_name=settings.nvidia_model, max_output_tokens=4096,
                             chat_model=chat, throttle=_nvidia_budget(),
                             structured=chat.with_structured_output(DecisionOut, method="function_calling",
                                                                    include_raw=True))
    return None
