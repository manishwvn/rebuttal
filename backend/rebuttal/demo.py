"""Isolated, bounded demo runtime for judges.

Each demo session gets its own Runtime: a private mock PayPal seeded with the demo disputes, the rules reasoner (no
model is ever called), an in-memory checkpointer and audit log, and no tracing or database. Settings are rebuilt with
credentials, database and model keys blanked, and the PayPal client only talks to the mock, so the real environment
cannot reach a demo session. Nothing is persisted: sessions live in this process's memory. DemoManager keeps the demo
bounded: at most max_sessions sessions (at capacity only a session idle for a few minutes is evicted, else new sessions
get 429), idle and absolute expiry, a cap on disputes
per session, a budget of workflow runs per session (each run adds checkpoints and audit rows to memory, and Reset demo
restores the budget), and sliding-window limits on creating or resetting sessions, one per client and one for the whole service. Work on one
session is serialised by its lock; a caller waits for it only briefly, then gets 429.
"""

from __future__ import annotations

import dataclasses
import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver

from .agent.pipeline import Proposal
from .config import load_settings
from .runtime import Runtime
from .scenarios import load_cases, seed_case

DEMO_CASE_IDS = [  # hero case first, so its dispute is seed index 0
    "agent_wrong_size",
    "inr_delivered",
    "inr_misdelivered",
    "snad_damaged_low_value",
    "unauth_agent_mandate",
    "cnp_refunded",
]
HERO_DISPUTE_ID = "PP-D-2000"


class DemoError(Exception):
    """Base class for errors from the demo runtime."""


class DemoSessionNotFound(DemoError):
    """No live demo session has this id: it never existed, expired or was evicted."""


class DemoLimitReached(DemoError):
    """The session holds the maximum number of disputes or has used up its workflow runs."""


class DemoUnknownCase(DemoError):
    """The case id is not one of the labelled cases."""


class DemoRateLimited(DemoError):
    """Too many sessions were created or reset within the window."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"too many demo sessions started; retry in {retry_after} seconds")
        self.retry_after = retry_after


class DemoBusy(DemoError):
    """The session lock stayed taken for the whole wait: another request is still working on this session."""


class DemoUnavailable(DemoError):
    """The demo runtime could not be built."""


def build_demo_runtime() -> Runtime:
    """A mock-only Runtime with the demo disputes seeded and the hero proposal waiting for approval. Analysis only:
    nothing is sent to PayPal."""
    settings = dataclasses.replace(
        load_settings(), mock=True, client_id="", client_secret="", anthropic_api_key=None, nvidia_api_key=None,
        groq_api_key=None, database_url=None, checkpoint_target=None, provider=None, reasoner="rules",
        paypal_webhook_id=None,
    )
    runtime = Runtime(settings, seed_cases=DEMO_CASE_IDS, force_rules=True, audit_to_file=False,
                      checkpointer=InMemorySaver(), tracing=False)
    if runtime.mock is None or runtime.mode != "mock / rules":
        raise RuntimeError(f"demo runtime must be mock / rules, got {runtime.mode}")
    hero = runtime.analyze(HERO_DISPUTE_ID)
    if hero.status != "PENDING":
        raise RuntimeError(f"the hero proposal must wait for approval, got {hero.status}")
    return runtime


def simulator_cases() -> list[dict]:
    """The labelled cases the simulator can create, in the shape the dashboard's picker reads."""
    return [
        {"id": c["id"], "title": c["title"], "reason": c["reason"], "agent_purchase": bool(c.get("agent_purchase"))}
        for c in load_cases()
    ]


@dataclasses.dataclass
class DemoSession:
    id: str
    runtime: Runtime
    lock: threading.RLock  # serialises all work on this session's runtime; reentrant, so a call may nest use()
    created_at: float
    last_used: float
    runs: int = 0  # workflow runs charged to this session since it was created or last reset

    def has_dispute(self, dispute_id: str) -> bool:
        return dispute_id in self.runtime.mock.disputes


class DemoManager:
    """Creates, finds, resets and expires demo sessions and enforces their limits. Thread-safe: one lock guards the
    session table and the rate-limit window, and each session has its own lock."""

    def __init__(
        self,
        *,
        max_sessions: int = 40,
        idle_ttl: float = 1800.0,
        max_age: float = 7200.0,
        max_disputes: int = 16,
        max_runs: int = 100,
        create_limit: int = 20,
        create_window: float = 60.0,
        client_create_limit: int = 5,
        recent_window: float = 300.0,
        lock_timeout: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        runtime_factory: Callable[[], Runtime] = build_demo_runtime,
    ) -> None:
        self.idle_ttl = idle_ttl
        self.max_age = max_age
        self.max_disputes = max_disputes
        self.max_runs = max_runs
        self._max_sessions = max_sessions
        self._create_limit = create_limit
        self._create_window = create_window
        self._client_create_limit = client_create_limit
        self._recent_window = recent_window
        self._lock_timeout = lock_timeout
        self._clock = clock
        self._runtime_factory = runtime_factory
        self._lock = threading.Lock()  # guards _sessions and _attempts
        self._sessions: dict[str, DemoSession] = {}
        self._attempts: deque[float] = deque()  # when create and reset calls happened, oldest first
        self._client_attempts: dict[str, deque[float]] = {}  # the same, per client key

    def create(self, client: str = "") -> DemoSession:
        with self._lock:
            now = self._clock()
            self._sweep_locked(now)
            self._check_room_locked(now)  # refuse before spending a build and a rate-limit slot
            self._admit_locked(now, client)
        runtime = self._build()  # outside the lock: it takes a moment
        with self._lock:
            now = self._clock()
            self._sweep_locked(now)  # after the build: a session that lapsed during it is dropped, not evicted for
            victim = self._check_room_locked(now)
            if victim is not None:
                del self._sessions[victim.id]
            session = DemoSession(id=secrets.token_urlsafe(16), runtime=runtime, lock=threading.RLock(),
                                  created_at=now, last_used=now)
            self._sessions[session.id] = session
        return session

    @contextmanager
    def use(self, session_id: str) -> Iterator[DemoSession]:
        """Hold one session for the duration of the with block; other callers on that session wait up to lock_timeout
        seconds, then get DemoBusy."""
        with self._lock:
            now = self._clock()
            self._sweep_locked(now)
            session = self._sessions.get(session_id)
            if session is None:
                raise DemoSessionNotFound("no live demo session has this id")
            session.last_used = now
        # outside the table lock, so one busy session does not block the others
        if not session.lock.acquire(timeout=self._lock_timeout):
            raise DemoBusy("this demo session is busy")
        try:
            yield session
        finally:
            session.lock.release()

    def reset(self, session_id: str, client: str = "") -> DemoSession:
        """Give a session a fresh demo runtime under the same id. Its previous state is discarded."""
        with self.use(session_id):  # lookup only: an unknown id answers 404 before reset spends the rate limit
            pass
        with self._lock:
            self._admit_locked(self._clock(), client)
        runtime = self._build()  # built before taking the session lock, so a rebuild never holds it
        with self.use(session_id) as session:
            session.runtime = runtime
            session.runs = 0
            return session

    def _build(self) -> Runtime:
        try:
            return self._runtime_factory()
        except RuntimeError as exc:
            raise DemoUnavailable("the demo runtime could not be built") from exc

    def charge_run(self, session: DemoSession) -> None:
        """Counts one workflow run against the session's budget, or refuses it. Call it before every analyze, approve,
        reject, retry or simulate, while holding the session through use(): each run adds checkpoints and audit rows to
        the session's memory, and nothing else bounds how many a client can start."""
        if session.runs >= self.max_runs:
            raise DemoLimitReached(f"a demo session allows at most {self.max_runs} workflow runs")
        session.runs += 1

    def simulate(self, session: DemoSession, case_id: str) -> Proposal:
        """Seed one more dispute from a labelled case and analyze it. The caller holds `session` through use()."""
        cases = {case["id"]: case for case in load_cases()}
        if case_id not in cases:
            raise DemoUnknownCase(case_id)
        mock = session.runtime.mock
        if len(mock.disputes) >= self.max_disputes:
            raise DemoLimitReached(f"a demo session holds at most {self.max_disputes} disputes")
        self.charge_run(session)
        # +100 keeps simulated ids clear of the seeded demo ids (PP-D-2000 to PP-D-2005).
        dispute_id = seed_case(cases[case_id], len(mock.disputes) + 100, mock, session.runtime.store)
        return session.runtime.analyze(dispute_id)

    def expires_in(self, session: DemoSession) -> int:
        """Whole seconds until the session expires, by idle time or by age, whichever comes first."""
        now = self._clock()
        left = min(self.idle_ttl - (now - session.last_used), self.max_age - (now - session.created_at))
        return int(max(0, left))

    def session_count(self) -> int:
        """Sessions held, including expired ones that have not been swept yet."""
        with self._lock:
            return len(self._sessions)

    def _sweep_locked(self, now: float) -> None:
        self._sessions = {
            sid: session for sid, session in self._sessions.items()
            if now - session.last_used <= self.idle_ttl and now - session.created_at <= self.max_age
        }

    def _check_room_locked(self, now: float) -> DemoSession | None:
        """None when there is a free slot. At capacity, the least recently used session that has been idle for at least
        recent_window (the one to evict), or DemoRateLimited when every session was active more recently than that."""
        if len(self._sessions) < self._max_sessions:
            return None
        least_recent = min(self._sessions.values(), key=lambda s: s.last_used)
        idle = now - least_recent.last_used
        if idle < self._recent_window:
            raise DemoRateLimited(max(1, math.ceil(self._recent_window - idle)))
        return least_recent

    def _admit_locked(self, now: float, client: str = "") -> None:
        """The limits shared by create() and reset(): one for the client, one for the whole service. Records this
        attempt in both, or refuses it with the seconds to wait and records nothing."""
        window = self._create_window
        for key in [k for k, q in self._client_attempts.items() if not q or now - q[-1] >= window]:
            del self._client_attempts[key]  # keeps the table at the clients active within the window
        mine = self._client_attempts.get(client, deque())
        while mine and now - mine[0] >= window:
            mine.popleft()
        attempts = self._attempts
        while attempts and now - attempts[0] >= window:
            attempts.popleft()
        for queue, limit in ((mine, self._client_create_limit), (attempts, self._create_limit)):
            if len(queue) >= limit:
                raise DemoRateLimited(max(1, math.ceil(window - (now - queue[0]))))
        mine.append(now)
        attempts.append(now)
        self._client_attempts[client] = mine
