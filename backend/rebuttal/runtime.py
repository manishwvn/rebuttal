"""Wires settings, PayPal client (mock or sandbox), merchant store, reasoner, audit and the workflow graph."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from .agent.graph import DisputeAgent
from .agent.llm import build_reasoner
from .agent.pipeline import Proposal
from .agent.reasoner import RuleReasoner
from .approval import ApprovalQueue
from .audit import AuditLog
from .config import Settings, load_settings
from .paypal.client import PayPalClient
from .paypal.mock import MockPayPal
from .persistence import make_checkpointer
from .scenarios import DEMO_NOW, fixture_order, load_cases, seed_case
from .store import MerchantStore


def _tracing_configured() -> bool:
    if os.getenv("REBUTTAL_TRACING", "").strip().lower() in ("0", "false", "off"):
        return False  # explicitly off: do not even import the Langfuse module
    from . import tracing  # Langfuse stays optional: nothing is imported or sent unless keys are set

    return tracing.langfuse_configured()


class Runtime:
    def __init__(self, settings: Settings | None = None, seed_cases: list[str] | None = None,
                 force_rules: bool = False, audit_to_file: bool = False, checkpointer=None,
                 tracing: bool | None = None, provider: str | None = None, strict: bool = False):
        """`checkpointer`: a LangGraph saver; default comes from settings (in memory in mock mode).
        `tracing`: True/False forces Langfuse tracing on/off; None means on when Langfuse keys are set."""
        self.settings = settings or load_settings()
        self.store = MerchantStore(fixtures=fixture_order)
        self.mock: MockPayPal | None = None

        if self.settings.mock:
            self.mock = MockPayPal()
            self.client = PayPalClient(self.settings.base_url, "mock-id", "mock-secret",
                                       transport=self.mock.transport())
            self.clock = lambda: DEMO_NOW
        else:
            self.client = PayPalClient(self.settings.base_url, self.settings.client_id,
                                       self.settings.client_secret)
            self.clock = lambda: datetime.now(UTC)

        rules_only = force_rules or self.settings.reasoner == "rules"
        self.reasoner = (None if rules_only else build_reasoner(self.settings, provider=provider, strict=strict)) or RuleReasoner()

        self.audit = AuditLog(self.settings.audit_path if audit_to_file else None, self.settings.database_url)
        self.agent = DisputeAgent(
            client=self.client, store=self.store, reasoner=self.reasoner, audit=self.audit, clock=self.clock,
            checkpointer=checkpointer or make_checkpointer(self.settings.checkpoint_target),
            tracing=_tracing_configured() if tracing is None else tracing)
        self.approvals = ApprovalQueue(self.agent)
        self.due_dates: dict[str, tuple[float, str | None]] = {}  # analytics: dispute id -> (expiry, seller due date)

        if self.mock is not None and seed_cases is not None:
            cases = {c["id"]: c for c in load_cases()}
            for i, cid in enumerate(seed_cases):
                seed_case(cases[cid], i, self.mock, self.store)

    @property
    def mode(self) -> str:
        return ("mock" if self.mock else "sandbox") + f" / {self.reasoner.name}"

    def analyze(self, dispute_id: str, *, force: bool = False, config_extra: dict | None = None) -> Proposal:
        """Run the workflow to the approval gate (nothing is sent to PayPal) and return the proposal."""
        return self.agent.analyze(dispute_id, force=force, config_extra=config_extra)
