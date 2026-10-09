"""The demo runtime is isolated and bounded: no path to the real PayPal sandbox, and DemoManager's limits hold."""

import threading
import time
from types import SimpleNamespace

import pytest

import rebuttal.demo as demo_module
import rebuttal.runtime as runtime_module
from rebuttal.agent.pipeline import Proposal
from rebuttal.demo import (
    DEMO_CASE_IDS,
    HERO_DISPUTE_ID,
    DemoLimitReached,
    DemoManager,
    DemoRateLimited,
    DemoSessionNotFound,
    DemoUnknownCase,
    build_demo_runtime,
    simulator_cases,
)
from rebuttal.scenarios import load_cases


class FakeClock:
    """Stands in for time.monotonic, so each test moves time by hand."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_demo_runtime_is_mock_rules_and_ignores_real_environment(monkeypatch):
    monkeypatch.setenv("PAYPAL_ENV", "sandbox")
    monkeypatch.setenv("REBUTTAL_MOCK", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "fake-client-secret")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.setenv("NVIDIA_API_KEY", "fake-nvidia-key")
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "fake-webhook-id")
    monkeypatch.setenv("REBUTTAL_REASONER", "auto")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/x")

    def must_not_run(*args, **kwargs):
        raise AssertionError("the demo runtime must not build a model, a checkpointer or tracing")

    monkeypatch.setattr(runtime_module, "build_reasoner", must_not_run)
    monkeypatch.setattr(runtime_module, "make_checkpointer", must_not_run)
    monkeypatch.setattr(runtime_module, "_tracing_configured", must_not_run)

    rt = build_demo_runtime()

    assert rt.mock is not None
    assert rt.mode == "mock / rules"
    assert rt.settings.mock is True
    assert rt.settings.client_id == ""
    assert rt.settings.client_secret == ""
    assert rt.settings.database_url is None
    assert rt.settings.anthropic_api_key is None
    assert rt.settings.nvidia_api_key is None
    assert rt.settings.groq_api_key is None
    assert rt.settings.paypal_webhook_id is None
    assert rt.audit._pool is None
    assert rt.audit.path is None  # demo audit lines never reach the file the live app writes
    assert rt.mock.write_calls() == []
    assert len(rt.mock.disputes) == len(DEMO_CASE_IDS)
    hero_case = next(c for c in load_cases() if c["id"] == "agent_wrong_size")
    assert rt.mock.disputes[HERO_DISPUTE_ID]["messages"][0]["content"] == hero_case["buyer_message"]
    assert rt.approvals.latest_for(HERO_DISPUTE_ID).status == "PENDING"


@pytest.mark.parametrize("stub", [
    SimpleNamespace(mock=None, mode="sandbox / rules"),
    SimpleNamespace(mock=object(), mode="mock / groq"),
])
def test_build_refuses_a_runtime_that_is_not_mock_rules(monkeypatch, stub):
    monkeypatch.setattr(demo_module, "Runtime", lambda *args, **kwargs: stub)
    with pytest.raises(RuntimeError, match="mock / rules"):
        build_demo_runtime()


def test_build_refuses_a_hero_that_does_not_wait_for_approval(monkeypatch):
    stub = SimpleNamespace(mock=object(), mode="mock / rules",
                           analyze=lambda dispute_id: SimpleNamespace(status="EXECUTED"))
    monkeypatch.setattr(demo_module, "Runtime", lambda *args, **kwargs: stub)
    with pytest.raises(RuntimeError, match="wait for approval"):
        build_demo_runtime()


def test_two_runtimes_share_nothing():
    first, second = build_demo_runtime(), build_demo_runtime()
    assert first.mock is not second.mock
    assert first.client is not second.client
    assert first.store is not second.store
    assert first.audit is not second.audit

    proposal = first.approvals.latest_for(HERO_DISPUTE_ID)
    assert first.approvals.approve(proposal.id).status == "EXECUTED"
    assert first.mock.write_calls()
    assert second.mock.write_calls() == []
    assert second.approvals.latest_for(HERO_DISPUTE_ID).status == "PENDING"


def test_simulator_cases_list_every_labelled_case_in_the_api_shape():
    cases = simulator_cases()
    assert [c["id"] for c in cases] == [c["id"] for c in load_cases()]
    assert all(set(c) == {"id", "title", "reason", "agent_purchase"} for c in cases)
    assert all(isinstance(c["agent_purchase"], bool) for c in cases)


def test_create_use_and_unknown_session_id():
    manager = DemoManager(runtime_factory=SimpleNamespace)
    session = manager.create()
    with manager.use(session.id) as used:
        assert used is session
    with pytest.raises(DemoSessionNotFound):
        with manager.use("no-such-session"):
            pass


def test_idle_sessions_expire_and_are_swept():
    clock = FakeClock()
    manager = DemoManager(idle_ttl=100.0, clock=clock, runtime_factory=SimpleNamespace)
    session = manager.create()
    clock.now = 100.0  # exactly idle_ttl since creation: still alive
    with manager.use(session.id):
        pass
    clock.now = 201.0  # 101 seconds since the last use
    with pytest.raises(DemoSessionNotFound):
        with manager.use(session.id):
            pass
    assert manager.session_count() == 0


def test_sessions_expire_at_max_age_even_while_busy():
    clock = FakeClock()
    manager = DemoManager(idle_ttl=100.0, max_age=1000.0, clock=clock, runtime_factory=SimpleNamespace)
    session = manager.create()
    for now in range(100, 1001, 100):  # used every 100 seconds, so the idle limit never applies
        clock.now = float(now)
        with manager.use(session.id):
            pass
    clock.now = 1001.0  # 1001 seconds old
    with pytest.raises(DemoSessionNotFound):
        with manager.use(session.id):
            pass


def test_reset_restarts_the_absolute_lifetime():
    clock = FakeClock()
    manager = DemoManager(max_age=100.0, clock=clock, runtime_factory=SimpleNamespace)
    session = manager.create()  # created at 0
    clock.now = 90.0
    manager.reset(session.id)  # the fresh runtime starts a new 100 second life at 90
    clock.now = 150.0  # 150 seconds since create, 60 since reset
    with manager.use(session.id):
        pass
    clock.now = 191.0  # 101 seconds since reset
    with pytest.raises(DemoSessionNotFound):
        with manager.use(session.id):
            pass


def test_expires_in_counts_down_to_the_nearer_limit():
    clock = FakeClock()
    by_idle = DemoManager(idle_ttl=100.0, max_age=1000.0, clock=clock, runtime_factory=SimpleNamespace)
    session = by_idle.create()
    assert by_idle.expires_in(session) == 100
    clock.now = 30.0
    assert by_idle.expires_in(session) == 70
    clock.now = 2000.0
    assert by_idle.expires_in(session) == 0

    by_age = DemoManager(idle_ttl=1000.0, max_age=50.0, clock=clock, runtime_factory=SimpleNamespace)
    session = by_age.create()  # created at 2000
    clock.now = 2020.0
    assert by_age.expires_in(session) == 30


def test_session_count_stays_within_max_sessions():
    clock = FakeClock()
    manager = DemoManager(max_sessions=5, create_limit=1000, clock=clock, runtime_factory=SimpleNamespace)
    for _ in range(100):
        clock.now += 1.0
        manager.create()
        assert manager.session_count() <= 5
    assert manager.session_count() == 5


def test_create_sweeps_expired_sessions_out_of_the_table():
    clock = FakeClock()
    manager = DemoManager(idle_ttl=100.0, clock=clock, runtime_factory=SimpleNamespace)
    manager.create()
    clock.now = 101.0  # the first session is now idle past its limit
    manager.create()
    assert manager.session_count() == 1


def test_at_capacity_the_least_recently_used_session_is_evicted():
    clock = FakeClock()
    manager = DemoManager(max_sessions=2, create_limit=1000, clock=clock, runtime_factory=SimpleNamespace)
    clock.now = 1.0
    first = manager.create()
    clock.now = 2.0
    second = manager.create()
    clock.now = 3.0
    with manager.use(first.id):  # first is now the most recently used
        pass
    clock.now = 4.0
    third = manager.create()  # evicts second, not first
    with manager.use(first.id):
        pass
    with manager.use(third.id):
        pass
    with pytest.raises(DemoSessionNotFound):
        with manager.use(second.id):
            pass


def test_a_session_that_lapsed_during_a_build_is_dropped_not_evicted_in_its_place():
    clock = FakeClock()
    build_seconds = [0.0]

    def slow_factory():
        clock.now += build_seconds[0]  # the build takes time on the fake clock
        return SimpleNamespace()

    manager = DemoManager(max_sessions=2, idle_ttl=1000.0, max_age=100.0, create_limit=1000, clock=clock,
                          runtime_factory=slow_factory)
    clock.now = 0.0
    lapsing = manager.create()  # created at 0
    clock.now = 40.0
    live = manager.create()  # created at 40, never used since
    clock.now = 90.0
    with manager.use(lapsing.id):  # the lapsing session is the most recently used
        pass
    clock.now = 95.0
    build_seconds[0] = 10.0
    manager.create()  # the build ends at 105, when `lapsing` is 105 seconds old and `live` is 65
    with manager.use(live.id):  # still alive: the full table was not used to evict it
        pass
    with pytest.raises(DemoSessionNotFound):
        with manager.use(lapsing.id):
            pass
    assert manager.session_count() == 2


def test_creates_are_rate_limited_and_recover_after_the_window():
    clock = FakeClock()
    manager = DemoManager(create_limit=3, create_window=60.0, clock=clock, runtime_factory=SimpleNamespace)
    for now in (0.0, 1.0, 2.0):
        clock.now = now
        manager.create()
    clock.now = 3.0
    with pytest.raises(DemoRateLimited) as refused:
        manager.create()
    assert refused.value.retry_after == 57  # the first create leaves the 60 second window at t=60
    clock.now = 61.0
    manager.create()


def test_reset_keeps_the_id_gives_a_fresh_runtime_and_counts_toward_the_limit():
    manager = DemoManager(create_limit=2, clock=FakeClock())
    session = manager.create()
    old_runtime = session.runtime
    proposal = old_runtime.approvals.latest_for(HERO_DISPUTE_ID)
    old_runtime.approvals.approve(proposal.id)
    assert old_runtime.approvals.latest_for(HERO_DISPUTE_ID).status == "EXECUTED"

    assert manager.reset(session.id) is session
    assert session.runtime is not old_runtime
    assert session.runtime.approvals.latest_for(HERO_DISPUTE_ID).status == "PENDING"
    with pytest.raises(DemoRateLimited):  # the create and the reset used up the two allowed in the window
        manager.create()


def test_simulate_adds_a_dispute_until_the_limit():
    manager = DemoManager(max_disputes=7)
    session = manager.create()
    case_id = simulator_cases()[0]["id"]
    with manager.use(session.id) as live:
        with pytest.raises(DemoUnknownCase):
            manager.simulate(live, "nope")
        proposal = manager.simulate(live, case_id)
        assert isinstance(proposal, Proposal)
        assert proposal.status == "PENDING"  # analysis stops at the approval gate
        assert live.has_dispute(proposal.dispute_id)
        assert len(live.runtime.mock.disputes) == 7
        with pytest.raises(DemoLimitReached):
            manager.simulate(live, case_id)


def test_work_on_one_session_is_serialised():
    manager = DemoManager(runtime_factory=SimpleNamespace)
    session = manager.create()
    events: list[str] = []
    first_inside = threading.Event()

    def first() -> None:
        with manager.use(session.id):
            events.append("first in")
            first_inside.set()
            time.sleep(0.2)
            events.append("first out")

    def second() -> None:
        first_inside.wait(5)
        with manager.use(session.id):
            events.append("second in")
            events.append("second out")

    workers = [threading.Thread(target=first), threading.Thread(target=second)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
    assert events == ["first in", "first out", "second in", "second out"]


def test_a_nested_reset_inside_use_on_the_same_thread_finishes():
    manager = DemoManager(runtime_factory=SimpleNamespace)
    session = manager.create()
    done = threading.Event()

    def nested() -> None:
        with manager.use(session.id):
            manager.reset(session.id)  # takes the same session's lock again on this thread
        done.set()

    worker = threading.Thread(target=nested, daemon=True)  # a deadlock must not hang the test run
    worker.start()
    worker.join(5)
    assert done.is_set()
