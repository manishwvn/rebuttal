"""The dispute workflow as a LangGraph graph.

    gather_facts -> decide -> guard -> plan_actions -> approval (interrupt) -> execute -> record
                                                            \\-- rejected ------------> record

Every node except `decide` is plain deterministic code (facts, guard, planning, the PayPal client). Only `decide`
calls a model. The thread id is the dispute id, so a paused proposal can be resumed days later, from another
process, with `Command(resume=...)`.

PayPal access is split on purpose: analysis nodes only get `client.read_only()`, a clone whose transport refuses any
write; the full client reaches exactly one node, `execute` (in `rebuttal/approval.py`), which the graph routes to
only after a human approves, and which is the only code that enters `permit_writes()`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy
from typing_extensions import TypedDict

from ..approval import (ApprovalDecision, ApprovalError, has_buyer_text, make_approval_node, make_execute_node,
                        route_after_approval)
from ..audit import AuditLog
from ..paypal.client import PayPalClient, PayPalError
from ..persistence import DisputeLocks, make_locks
from ..store import MerchantStore
from .facts import CaseFile, gather
from .pipeline import Proposal, plan_actions
from .reasoner import Decision, guard as apply_guard


class GraphState(TypedDict, total=False):
    """Everything is plain JSON so a checkpoint can be read, diffed and resumed by any process."""

    dispute_id: str
    case: dict           # CaseFile.to_dict(): the dispute, order, tracking, policies and the computed facts
    decision: dict       # Decision.to_dict()
    actions: list[dict]  # PlannedAction dicts: exactly one PayPal call per proposal
    proposal_id: str
    created: str
    approval: dict | None  # {"status": approved | edited | rejected, "by", "reason", "edited_message"}
    result: list[dict]     # what PayPal answered
    status: str            # ANALYZING | PENDING | EXECUTED | FAILED | REJECTED


def _transient(exc: Exception) -> bool:
    """Retry reads on network trouble and PayPal 5xx; a 4xx is an answer, not a glitch."""
    return isinstance(exc, httpx.TransportError) or (isinstance(exc, PayPalError) and exc.status >= 500)


DEFAULT_RETRY = RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0, retry_on=_transient)


def build_graph(*, client: PayPalClient, store: MerchantStore, reasoner, audit: AuditLog,
                clock: Callable[[], datetime], checkpointer: BaseCheckpointSaver | None,
                retry_policy: RetryPolicy = DEFAULT_RETRY):
    reader = client.read_only()  # what every node except `execute` gets

    def gather_facts(state: GraphState) -> dict:
        case = gather(state["dispute_id"], reader, store, clock())
        audit.log(case.dispute_id, "gather", {"tool_calls": case.tool_calls, "facts": case.facts,
                                              "policies": [t for t, _ in case.policies]})
        # A new analysis starts clean even when the thread already holds an earlier run.
        return {"case": case.to_dict(), "decision": None, "actions": [], "proposal_id": None, "created": None,
                "approval": None, "result": [], "status": "ANALYZING"}

    def decide(state: GraphState, config: RunnableConfig) -> dict:
        case = CaseFile.from_dict(state["case"])
        decision = reasoner.decide(case, config)
        audit.log(case.dispute_id, "decide", {"source": decision.source, "resolution": decision.resolution,
                                              "confidence": decision.confidence, "reasoning": decision.reasoning})
        return {"decision": decision.to_dict()}

    def guard(state: GraphState) -> dict:
        case = CaseFile.from_dict(state["case"])
        # The dispute may have moved since gather (UNDER_REVIEW has no allowed options; WAITING_FOR_SELLER_RESPONSE
        # does): check the decision against PayPal's current list. A failed read keeps what gather saw.
        try:
            current = reader.get_dispute(case.dispute_id)
        except (PayPalError, httpx.TransportError):
            current = None
        if current is not None and (current.get("allowed_response_options") or None) != (case.allowed_response_options or None):
            case.allowed_response_options = current.get("allowed_response_options") or None  # even if now empty
            case.status = current.get("status", case.status)
            case.tool_calls.append("re-read the dispute before the guard: allowed_response_options changed")
        decision = apply_guard(Decision.from_dict(state["decision"]), case)
        if decision.guard_notes:
            audit.log(case.dispute_id, "guard", {"notes": decision.guard_notes})
        return {"decision": decision.to_dict(), "case": case.to_dict()}

    def plan(state: GraphState) -> dict:
        case = CaseFile.from_dict(state["case"])
        actions = plan_actions(Decision.from_dict(state["decision"]), case)
        proposal_id = f"prop_{uuid.uuid4().hex[:8]}_{case.dispute_id}"
        audit.log(case.dispute_id, "propose", {"proposal": proposal_id, "actions": [a.summary for a in actions]})
        return {"actions": [{"kind": a.kind, "summary": a.summary, "params": a.params} for a in actions],
                "proposal_id": proposal_id, "created": clock().isoformat(), "status": "PENDING"}

    def record(state: GraphState) -> dict:
        """Close the run and write the audit lines for what the human decided and what PayPal answered."""
        dispute_id, proposal_id = state["dispute_id"], state["proposal_id"]
        approval = state.get("approval") or {}
        if approval.get("status") == "rejected":
            audit.log(dispute_id, "reject", {"proposal": proposal_id, "by": approval.get("by"),
                                             "reason": approval.get("reason")})
            status = "REJECTED"
        else:
            status = state.get("status", "FAILED")
            for action, outcome in zip(state.get("actions", []), state.get("result", [])):
                if outcome["ok"]:
                    audit.log(dispute_id, "execute", {"action": action["kind"], "summary": action["summary"],
                                                      "idempotency_key": outcome["idempotency_key"],
                                                      "reconciled": outcome.get("reconciled", False)})
                else:
                    audit.log(dispute_id, "execute_failed", {"action": action["kind"], "error": outcome["error"],
                                                             "idempotency_key": outcome["idempotency_key"]})
        audit.log(dispute_id, "record", {"proposal": proposal_id, "status": status})
        return {"status": status}

    builder = StateGraph(GraphState)
    builder.add_node("gather_facts", gather_facts, retry_policy=retry_policy)
    builder.add_node("decide", decide)
    builder.add_node("guard", guard)
    builder.add_node("plan_actions", plan)
    builder.add_node("approval", make_approval_node())
    builder.add_node("execute", make_execute_node(client, audit))  # no automatic retry: see DisputeAgent.retry
    builder.add_node("record", record)
    builder.add_edge(START, "gather_facts")
    builder.add_edge("gather_facts", "decide")
    builder.add_edge("decide", "guard")
    builder.add_edge("guard", "plan_actions")
    builder.add_edge("plan_actions", "approval")
    builder.add_conditional_edges("approval", route_after_approval, ["execute", "record"])
    builder.add_edge("execute", "record")
    builder.add_edge("record", END)
    return builder.compile(checkpointer=checkpointer)


def _merge(base: dict, extra: dict | None) -> dict:
    """Merge a RunnableConfig fragment (callbacks, tags, metadata, configurable) into `base`."""
    for key, value in (extra or {}).items():
        if key in ("callbacks", "tags") and value:
            base[key] = [*base.get(key, []), *value]
        elif key in ("metadata", "configurable") and value:
            base[key] = {**base.get(key, {}), **value}
        else:
            base[key] = value
    return base


class DisputeAgent:
    """The compiled graph plus the per-dispute plumbing: thread ids, locks, tracing, reading proposals back."""

    def __init__(self, *, client: PayPalClient, store: MerchantStore, reasoner, audit: AuditLog,
                 clock: Callable[[], datetime], checkpointer: BaseCheckpointSaver, tracing: bool = False,
                 retry_policy: RetryPolicy = DEFAULT_RETRY, locks: DisputeLocks | None = None):
        self.reasoner, self.audit, self.checkpointer = reasoner, audit, checkpointer
        self._tracing = tracing
        self._locks = locks or make_locks(checkpointer)
        self.graph = build_graph(client=client, store=store, reasoner=reasoner, audit=audit, clock=clock,
                                 checkpointer=checkpointer, retry_policy=retry_policy)

    # ------------------------------------------------------------------ plumbing
    @staticmethod
    def dispute_of(handle: str) -> str:
        """The dispute (thread) a proposal id belongs to: ids look like `prop_<hex>_<dispute id>`."""
        parts = handle.split("_", 2)
        return parts[2] if handle.startswith("prop_") and len(parts) == 3 else handle

    def _config(self, dispute_id: str, extra: dict | None = None) -> dict:
        config: dict = {"configurable": {"thread_id": dispute_id}}
        if self._tracing:
            from .. import tracing  # imported lazily: Langfuse is optional

            _merge(config, tracing.trace_config(dispute_id=dispute_id, provider=self.reasoner.name,
                                                model=getattr(self.reasoner, "model_name", self.reasoner.name)))
        return _merge(config, extra)

    def snapshot(self, dispute_id: str):
        return self.graph.get_state({"configurable": {"thread_id": dispute_id}})

    # ------------------------------------------------------------------- reading
    def proposal(self, dispute_id: str, *, with_pdf: bool = False) -> Proposal | None:
        snapshot = self.snapshot(dispute_id)
        values = snapshot.values
        if not values or not values.get("proposal_id") or not values.get("actions"):
            return None
        waiting = any(task.interrupts for task in snapshot.tasks)
        if waiting and snapshot.next == ("approval",):
            status = "PENDING"  # only when the thread really is paused at the gate
        elif snapshot.next == ("execute",):
            status = "APPROVED"  # approved, but the PayPal call did not finish: retry() continues it
        elif snapshot.next and snapshot.next != ("record",):
            status = "INTERRUPTED"  # a newer analysis stopped part-way; the values are the previous proposal's
        else:
            status = values.get("status")
        return Proposal.from_state(values, status=status, with_pdf=with_pdf)

    def pending_proposals(self) -> list[Proposal]:
        # Collect the thread ids first: SqliteSaver.list() holds its lock while it iterates, and reading a
        # proposal (get_state) needs the same lock.
        threads = list(dict.fromkeys(item.config["configurable"]["thread_id"]
                                     for item in self.checkpointer.list(None)))
        proposals = (self.proposal(thread) for thread in threads)
        return [p for p in proposals if p and p.status == "PENDING"]

    # ------------------------------------------------------------------- running
    def analyze(self, dispute_id: str, *, force: bool = False, config_extra: dict | None = None,
                with_pdf: bool = True) -> Proposal:
        """Run the workflow up to the approval gate. Nothing is sent to PayPal. A proposal that is already waiting
        for approval is returned as it is (PayPal can deliver a webhook twice); `force` starts a fresh analysis.
        An approved proposal whose PayPal call is unfinished is never replaced: retry it first."""
        with self._locks.hold(dispute_id):
            existing = self.proposal(dispute_id, with_pdf=with_pdf)
            if existing and self.snapshot(dispute_id).next in (("execute",), ("record",)):
                # Approved and not closed out (the PayPal call may have happened): a new run would lose its record.
                if force:
                    raise ApprovalError(f"Proposal {existing.id} is approved and not finished; retry it first")
                return existing
            if existing and existing.status == "PENDING" and not force:
                return existing
            self.graph.invoke({"dispute_id": dispute_id}, self._config(dispute_id, config_extra),
                              durability="sync")
            return self.proposal(dispute_id, with_pdf=with_pdf)

    def _checked(self, dispute_id: str, expected: str, wanted_status: str) -> Proposal:
        """Under the dispute's lock: the proposal exists, is the one the caller saw, and is in `wanted_status`.
        (LangGraph itself would quietly return the final state when resuming a finished thread.)"""
        proposal = self.proposal(dispute_id)
        if proposal is None:
            raise ApprovalError(f"Unknown proposal {expected}")
        if expected != proposal.id:
            # Always the exact id the human was shown: a bare dispute id, or an id from an earlier analysis,
            # must never approve a proposal the human has not seen.
            raise ApprovalError(f"Proposal {expected} is not the current proposal for this dispute ({proposal.id})")
        if proposal.status != wanted_status:
            raise ApprovalError(f"Proposal {proposal.id} is {proposal.status}, not {wanted_status}")
        return proposal

    def resume(self, dispute_id: str, decision: ApprovalDecision, *, expected: str,
               config_extra: dict | None = None) -> Proposal:
        """Deliver a human decision to the paused proposal; `expected` is the proposal id the human was shown."""
        with self._locks.hold(dispute_id):
            proposal = self._checked(dispute_id, expected, "PENDING")
            if decision.decision == "edit" and not has_buyer_text([{"params": a.params} for a in proposal.actions]):
                raise ApprovalError("This proposal has no buyer-facing message to edit")
            self.graph.invoke(Command(resume=decision.model_dump()), self._config(dispute_id, config_extra),
                              durability="sync")
            return self.proposal(dispute_id)

    def retry(self, dispute_id: str, *, expected: str, config_extra: dict | None = None) -> Proposal:
        """Continue a run that stopped after approval (execute or record did not finish). Before sending, `execute`
        reads the dispute and skips a message or offer that already landed, and it reuses the same idempotency key.
        PayPal documents that key for Orders and Payments, not for Disputes, so this is best effort: if PayPal
        refuses a repeat, the result says FAILED even though the first attempt may have gone through."""
        with self._locks.hold(dispute_id):
            proposal = self.proposal(dispute_id)
            if proposal is None or expected != proposal.id:
                raise ApprovalError(f"Unknown or replaced proposal {expected}")
            if self.snapshot(dispute_id).next not in (("execute",), ("record",)):
                raise ApprovalError(f"Proposal {proposal.id} is {proposal.status}, not waiting to continue")
            self.graph.invoke(None, self._config(dispute_id, config_extra), durability="sync")
            return self.proposal(dispute_id)
