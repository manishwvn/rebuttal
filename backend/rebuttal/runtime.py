"""Wires settings, PayPal client (mock or sandbox), merchant store, reasoner, audit and approvals."""

from __future__ import annotations

from datetime import datetime, timezone

from .agent.pipeline import Agent, Proposal
from .agent.reasoner import ClaudeReasoner, GroqReasoner, NvidiaReasoner, RuleReasoner
from .approval import ApprovalQueue
from .audit import AuditLog
from .config import Settings, load_settings
from .paypal.client import PayPalClient
from .paypal.mock import MockPayPal
from .scenarios import DEMO_NOW, load_cases, seed_case
from .store import MerchantStore


class Runtime:
    def __init__(self, settings: Settings | None = None, seed_cases: list[str] | None = None,
                 force_rules: bool = False, audit_to_file: bool = False):
        self.settings = settings or load_settings()
        self.store = MerchantStore()
        self.mock: MockPayPal | None = None

        if self.settings.mock:
            self.mock = MockPayPal()
            self.client = PayPalClient(self.settings.base_url, "mock-id", "mock-secret",
                                       transport=self.mock.transport())
            self.clock = lambda: DEMO_NOW
        else:
            self.client = PayPalClient(self.settings.base_url, self.settings.client_id,
                                       self.settings.client_secret)
            self.clock = lambda: datetime.now(timezone.utc)

        if self.settings.anthropic_api_key and not force_rules:
            self.reasoner = ClaudeReasoner(self.settings.anthropic_api_key, self.settings.model)
        elif self.settings.groq_api_key and not force_rules:
            self.reasoner = GroqReasoner(self.settings.groq_api_key, self.settings.groq_model)
        elif self.settings.nvidia_api_key and not force_rules:
            self.reasoner = NvidiaReasoner(self.settings.nvidia_api_key, self.settings.nvidia_model)
        else:
            self.reasoner = RuleReasoner()

        self.audit = AuditLog(self.settings.audit_path if audit_to_file else None)
        self.agent = Agent(self.client, self.store, self.reasoner, self.audit, self.clock)
        self.approvals = ApprovalQueue(self.client, self.audit)

        if self.mock is not None and seed_cases is not None:
            cases = {c["id"]: c for c in load_cases()}
            for i, cid in enumerate(seed_cases):
                seed_case(cases[cid], i, self.mock, self.store)

    @property
    def mode(self) -> str:
        return ("mock" if self.mock else "sandbox") + f" / {self.reasoner.name}"

    def analyze(self, dispute_id: str) -> Proposal:
        return self.approvals.submit(self.agent.analyze(dispute_id))
