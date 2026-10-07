"""The approval gate: the only code in the package that changes a dispute at PayPal.

Two graph nodes live here, side by side so the rule is easy to audit:

- `approval` pauses the workflow with LangGraph's `interrupt()` and waits for a human decision (approve, edit or
  reject, validated by `ApprovalDecision`). Nothing is sent while it waits, for as long as that takes, even across
  a restart, because the paused state is in the checkpointer.
- `execute` makes the PayPal write call. The graph only routes to it after an approve or edit decision, and it
  refuses to run without one. Every call carries a deterministic idempotency key, and before sending it reads the
  dispute to see whether this very action already landed (a retry after a crash).

Two rules for node code, both learned from review:

- Nothing that can fail runs after `interrupt()` returns. LangGraph remembers the first resume value of a task, so a
  failure there would let the first answer silently decide a later resume. `approval` only turns the answer into a
  plain dict; the edit, the audit lines and the PayPal call happen in the next nodes.
- Nothing that can fail runs after the PayPal call inside `execute`. It builds its result in memory and returns;
  the audit lines for what happened are written by `record`.

`ApprovalQueue` is the thin facade the API uses to list, approve, edit and reject proposals; it only drives the
graph. `tests/test_write_boundary.py` fails if any other module in `rebuttal/` can reach a PayPal write.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from langgraph.types import interrupt
from pydantic import BaseModel, Field, ValidationError, model_validator

from .agent.facts import CaseFile, seller_activity
from .agent.pipeline import Proposal, build_evidence_pdf
from .agent.reasoner import Decision
from .audit import AuditLog
from .paypal.client import PayPalClient, PayPalError, permit_writes

if TYPE_CHECKING:  # the graph module imports this one
    from .agent.graph import DisputeAgent


class ApprovalError(RuntimeError):
    pass


class ApprovalDecision(BaseModel):
    """What a human sends back to resume a paused proposal (validated by LangGraph on resume)."""

    decision: Literal["approve", "edit", "reject"]
    edited_message: str | None = Field(default=None, max_length=2000)
    approver: str = "merchant"
    reason: str = ""

    @model_validator(mode="after")
    def _edit_means_a_message(self) -> "ApprovalDecision":
        has_text = bool(self.edited_message and self.edited_message.strip())
        if self.decision == "edit" and not has_text:
            raise ValueError("decision 'edit' needs a non-empty edited_message")
        if self.decision != "edit" and self.edited_message is not None:
            raise ValueError("edited_message is only valid with decision 'edit'")
        return self


APPROVAL_STATUS = {"approve": "approved", "edit": "edited", "reject": "rejected"}


def idempotency_key(proposal_id: str, index: int, kind: str) -> str:
    """Same approved action, same key: a retry after a crash is the same request to PayPal, not a second one."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rebuttal:{proposal_id}:{index}:{kind}"))


def has_buyer_text(actions: list[dict]) -> bool:
    return any("message" in a["params"] or "note" in a["params"] for a in actions)


def with_edited_text(state: dict, message: str) -> tuple[list[dict], dict]:
    """Apply a merchant's edit to the buyer-facing text of the planned actions and to the decision."""
    actions = []
    for action in state["actions"]:
        params = dict(action["params"])
        for key in ("message", "note"):
            if key in params:
                params[key] = message
        actions.append({**action, "params": params})
    return actions, {**state["decision"], "message_to_buyer": message}


def already_applied(dispute: dict, action: dict, baseline: dict) -> bool:
    """Did this action already reach PayPal since the analysis? Reads the dispute; sends nothing.

    `baseline` is what the seller side had already said or offered when the case was gathered
    (`facts.seller_activity`): the action has landed if the dispute now holds more of the same message or offer
    type than it did then. Best effort, for a retry after a crash between the PayPal call and the checkpoint:
    PayPal documents `PayPal-Request-Id` for Orders and Payments but not for the Disputes API, so the key alone
    cannot be relied on here. Messages and offers are recognised; evidence and accept-claim are not (they fall back
    to `not_allowed_now`, the key, and PayPal's own refusal of a repeated action)."""
    now = seller_activity(dispute)
    kind, params = action["kind"], action["params"]
    if kind == "send_message":
        return now["messages"].count(params["message"]) > baseline.get("messages", []).count(params["message"])
    if kind == "make_offer":
        return now["offers"].count(params["offer_type"]) > baseline.get("offers", []).count(params["offer_type"])
    return False


def not_allowed_now(dispute: dict, action: dict) -> str | None:
    """Why PayPal would refuse this action on the dispute as it is now, if its own list of allowed responses says
    so (the dispute may have moved on while the proposal waited, or after a crash that did send). None = go ahead."""
    options = dispute.get("allowed_response_options")
    if not options:
        return None
    kind, params = action["kind"], action["params"]
    if kind == "accept_claim" and "accept_claim" not in options:
        return "PayPal no longer allows accepting this claim (the dispute has changed since the proposal was made)"
    if kind == "make_offer" and params["offer_type"] not in options.get("make_offer", {}).get("offer_types", []):
        return f"PayPal no longer allows a {params['offer_type']} offer (the dispute has changed since the proposal was made)"
    return None


# ----------------------------------------------------------------- graph nodes
def make_approval_node():
    """Pause for a human. Everything before `interrupt()` runs again on resume, so it only reads state."""

    def approval(state: dict) -> dict:
        decision = Decision.from_dict(state["decision"])
        human: ApprovalDecision = interrupt(
            {
                "proposal_id": state["proposal_id"], "dispute_id": state["dispute_id"],
                "resolution": decision.resolution, "confidence": decision.confidence,
                "message_to_buyer": decision.message_to_buyer, "guard_notes": decision.guard_notes,
                "actions": state["actions"],
            },
            response_schema=ApprovalDecision,
        )
        # Nothing fallible below this line (see the module docstring).
        return {"approval": {"status": APPROVAL_STATUS[human.decision], "by": human.approver,
                             "reason": human.reason, "edited_message": human.edited_message}}

    return approval


def route_after_approval(state: dict) -> Literal["execute", "record"]:
    return "execute" if (state.get("approval") or {}).get("status") in ("approved", "edited") else "record"


def execute_action(client: PayPalClient, dispute_id: str, action: dict, request_id: str,
                   evidence_pdf: bytes | None) -> dict:
    """The PayPal write calls. Called only from the `execute` node, inside `permit_writes()`."""
    kind, prm = action["kind"], action["params"]
    if kind == "send_message":
        return client.send_message(dispute_id, prm["message"], request_id=request_id)
    if kind == "make_offer":
        return client.make_offer(dispute_id, note=prm["note"], offer_type=prm["offer_type"],
                                 amount=prm.get("amount"), return_address=prm.get("return_address"),
                                 request_id=request_id)
    if kind == "accept_claim":
        return client.accept_claim(dispute_id, note=prm["note"], request_id=request_id)
    if kind == "provide_evidence":
        files = [(prm["filename"], evidence_pdf, "application/pdf")] if evidence_pdf else []
        return client.provide_evidence(dispute_id, prm["evidences"], files, request_id=request_id)
    raise ApprovalError(f"Unknown action {kind}")


def make_execute_node(client: PayPalClient, audit: AuditLog):
    def execute(state: dict) -> dict:
        approval = state.get("approval") or {}
        if approval.get("status") not in ("approved", "edited"):
            raise ApprovalError("Refusing to execute: this proposal has no approval")
        dispute_id, proposal_id = state["dispute_id"], state["proposal_id"]
        actions, decision = state["actions"], state["decision"]
        if approval["status"] == "edited":
            if not has_buyer_text(actions):
                raise ApprovalError("This proposal has no buyer-facing message to edit")
            actions, decision = with_edited_text(state, approval["edited_message"])
        # Everything that can fail before the first byte is sent happens here: if any of it raises, nothing was sent.
        audit.log(dispute_id, "approve", {"proposal": proposal_id, "by": approval["by"],
                                          "edited": approval["status"] == "edited"})
        pdf = None
        if any(a["kind"] == "provide_evidence" for a in actions):
            pdf = build_evidence_pdf(CaseFile.from_dict(state["case"]), Decision.from_dict(decision))
        current = client.get_dispute(dispute_id)

        results: list[dict] = []
        status = "EXECUTED"
        with permit_writes():
            for index, action in enumerate(actions):
                key = idempotency_key(proposal_id, index, action["kind"])
                if already_applied(current, action, state["case"].get("seller_activity", {})):
                    results.append({"action": action["kind"], "ok": True, "reconciled": True,
                                    "idempotency_key": key})
                    continue
                if reason := not_allowed_now(current, action):
                    results.append({"action": action["kind"], "ok": False, "error": reason, "sent": False,
                                    "idempotency_key": key})
                    status = "FAILED"
                    break
                try:
                    response = execute_action(client, dispute_id, action, key, pdf)
                except PayPalError as exc:
                    if exc.status >= 500:
                        # PayPal may or may not have acted. Not a result: the thread stays approved-but-unfinished and
                        # retry() reads the dispute before sending again.
                        raise
                    results.append({"action": action["kind"], "ok": False, "error": str(exc),
                                    "idempotency_key": key})
                    status = "FAILED"
                    break
                results.append({"action": action["kind"], "ok": True, "response": response,
                                "idempotency_key": key})
        # Nothing fallible after the PayPal call: return the outcome; `record` writes the audit lines.
        return {"result": results, "status": status, "actions": actions, "decision": decision}

    return execute


# ---------------------------------------------------------------------- facade
class ApprovalQueue:
    """List, approve, edit and reject proposals. It only drives the graph; it never calls PayPal itself."""

    def __init__(self, agent: "DisputeAgent"):
        self._agent = agent

    def latest_for(self, dispute_id: str) -> Proposal | None:
        return self._agent.proposal(dispute_id)

    def pending(self) -> list[Proposal]:
        return self._agent.pending_proposals()

    def reject(self, proposal_id: str, reason: str = "", approver: str = "merchant") -> Proposal:
        return self._decide(proposal_id, decision="reject", reason=reason, approver=approver)

    def approve(self, proposal_id: str, edited_message: str | None = None,
                approver: str = "merchant") -> Proposal:
        return self._decide(proposal_id, decision="edit" if edited_message else "approve",
                            edited_message=edited_message or None, approver=approver)

    def retry(self, proposal_id: str) -> Proposal:
        """Continue an approved proposal whose execution was interrupted (for example by a crash). It first reads
        the dispute and does not resend a message or offer that already landed."""
        return self._agent.retry(self._agent.dispute_of(proposal_id), expected=proposal_id)

    def _decide(self, proposal_id: str, **fields) -> Proposal:
        try:
            decision = ApprovalDecision(**fields)
        except ValidationError as exc:
            raise ApprovalError("; ".join(e["msg"] for e in exc.errors())) from exc
        return self._agent.resume(self._agent.dispute_of(proposal_id), decision, expected=proposal_id)
