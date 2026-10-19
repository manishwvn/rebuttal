"""The approval gate: the only code in the package that changes a dispute at PayPal.

Two graph nodes live here, side by side so the rule is easy to audit:

- `approval` pauses the workflow with LangGraph's `interrupt()` and waits for a human decision (approve, edit or
  reject, validated by `ApprovalDecision`). Nothing is sent while it waits, for as long as that takes, even across
  a restart, because the paused state is in the checkpointer.
- `execute` makes the PayPal write call. The graph only routes to it after an approve or edit decision, and it
  refuses to run without one. Every call carries a deterministic idempotency key, and before sending it reads the
  dispute to see whether this very action already landed (a retry after a crash). `already_applied` recognises
  messages and offers only. Escalate, appeal, evidence and accept-claim are not recognised: they fall back to
  `not_allowed_now`, which fails closed once the dispute's stage, links or status have moved on.

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

from .agent.facts import CaseFile, dispute_actions, normalize_text, seller_activity
from .agent.pipeline import EVIDENCE_KINDS, Proposal, build_evidence_pdf
from .agent.reasoner import Decision, effective_options
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
    def _edit_means_a_message(self) -> ApprovalDecision:
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


def already_applied(dispute: dict, action: dict, case: dict) -> bool:
    """Did this action already reach PayPal since the analysis? Reads the dispute; sends nothing.

    `case` is the gathered case the proposal was made from. Its `seller_activity` is what the seller side had already
    said or offered (`facts.seller_activity`): the action has landed if the dispute now holds more of the same message
    or offer type than it did then. Best effort, for a retry after a crash between the PayPal call and the checkpoint:
    PayPal documents `PayPal-Request-Id` for Orders and Payments but not for the Disputes API, so the key alone
    cannot be relied on here. Messages and offers are recognised. Escalate and appeal are not: a stage move from
    INQUIRY to CHARGEBACK also happens when the buyer escalates, so it cannot prove this action landed. They fall back
    to `not_allowed_now`, which refuses once the dispute's stage or links have moved on, so a retry after a send that
    landed fails closed (`sent` False) instead of being reconciled. Evidence and accept-claim are not recognised either:
    `not_allowed_now` refuses them unless PayPal is still waiting for the seller (the only status PayPal documents for
    evidence), so a retry after a send that landed fails closed (`sent` False).
    VERIFY: that evidence and claim refusal holds only if a read after a landed send shows PayPal left the seller's
    turn. The sandbox record does not confirm it: provide_evidence is listed in UNDER_REVIEW (docs/sandbox-findings.md
    :116, :231, :240), accept_claim REFUND in WAITING_FOR_BUYER_RESPONSE (:200, :241), reads can lag writes (:206), and
    the evidence status UNDER_REVIEW after a send is in the run log only (:253). A plain accept to RESOLVED has no
    live record. Confirm with a sandbox fixture before the Nov 3 freeze.
    VERIFY: retry safety for escalate and appeal depends on PayPal removing the link after a successful send. The live
    sandbox showed no before and after pair for escalate (docs/sandbox-findings.md item 7), and it accepted an escalate
    on a dispute with no link, so this check is our own fail-closed guard, not a rule PayPal was seen to apply.
    The seller message and offer shapes read here (`posted_by`, `actor`, the offer note as a SELLER message) were
    seen on the live sandbox (2026-10-14)."""
    if "seller_activity" not in case:
        return False  # no baseline: an earlier identical message or offer would look new, so send rather than skip
    now = seller_activity(dispute)
    baseline = case["seller_activity"]
    kind, params = action["kind"], action["params"]
    if kind == "send_message":
        message = normalize_text(params["message"])
        return now["messages"].count(message) > [normalize_text(m) for m in baseline.get("messages", [])].count(message)
    if kind == "make_offer":
        return now["offers"].count(params["offer_type"]) > baseline.get("offers", []).count(params["offer_type"])
    return False


def not_allowed_now(dispute: dict, action: dict) -> str | None:
    """Why PayPal would refuse this action on the dispute as it is now, if its own list of allowed responses says
    so, for escalate and appeal, if the dispute's links no longer offer them, or for evidence and claim acceptance,
    unless PayPal is still waiting for the seller (the dispute may have moved on while the proposal waited, or after
    a crash that did send). None = go ahead."""
    kind, params = action["kind"], action["params"]
    # Escalate and appeal do not depend on allowed_response_options, so they are checked before the options logic.
    # The refusal does not say whether an earlier attempt landed: the dispute changed, and it may have been this action.
    # Same rule as the analysis side (reasoner._escalation_offered): the escalate link is also offered while the
    # buyer is to respond, but we only escalate on the seller's turn.
    if kind == "escalate" and (not dispute_actions(dispute)["can_escalate"]
                               or dispute.get("status") != "WAITING_FOR_SELLER_RESPONSE"):
        return ("PayPal no longer allows escalating this dispute to a claim (the dispute has changed since the proposal "
                "was made, so an earlier attempt may already have been sent)")
    if kind == "appeal" and not dispute_actions(dispute)["can_appeal"]:
        return ("PayPal no longer allows appealing this dispute (the dispute has changed since the proposal was made, "
                "so an earlier attempt may already have been sent)")
    # Evidence and every claim acceptance go only on the seller's turn. A replay after a send that landed may find the
    # dispute UNDER_REVIEW or RESOLVED with no option list (a REFUND_WITH_RETURN acceptance may leave it so), so the
    # options check below would let it through.
    # VERIFY: this rule's fail-closed result holds only if a read after a landed send shows PayPal left the seller's
    # turn. Three sandbox fixtures must confirm it before the Nov 3 freeze: (1) evidence sent, then read: the status
    # is no longer WAITING_FOR_SELLER_RESPONSE; (2) plain accept_claim sent, then read: the same; (3) provide_evidence
    # on an UNDER_REVIEW dispute: the record lists it there (docs/sandbox-findings.md :116, :231, :240), so if PayPal
    # accepts it, this rule refuses a send PayPal allows. The record does not confirm (1) or (2) (:200, :206, :241,
    # :253), so the refusal can say an earlier attempt may have been sent when none was. Narrowing the rule reopens the
    # replay hole, so keep it until the three checks pass.
    if kind in ("provide_evidence", "accept_claim") and dispute.get("status") != "WAITING_FOR_SELLER_RESPONSE":
        return ("PayPal is no longer waiting for the seller on this dispute (the dispute has changed since the proposal "
                "was made, so an earlier attempt may already have been sent)")
    options, _ = effective_options(dispute.get("allowed_response_options"), dispute.get("reason", ""),
                                   dispute.get("dispute_life_cycle_stage", ""))  # none listed: the proven fallback
    if options is None:
        return None
    if kind == "accept_claim" and "accept_claim" not in options:
        return "PayPal no longer allows accepting this claim (the dispute has changed since the proposal was made)"
    claim_type = params.get("accept_claim_type", "REFUND")
    # No accept_claim_types list keeps the old behaviour (a plain claim acceptance goes ahead); a list must name the type.
    if kind == "accept_claim" and claim_type not in ((options.get("accept_claim") or {})
                                                     .get("accept_claim_types", [claim_type])):
        return f"PayPal no longer allows a {claim_type} claim acceptance (the dispute has changed since the proposal was made)"
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
        return client.accept_claim(dispute_id, note=prm["note"], accept_claim_type=prm.get("accept_claim_type", "REFUND"),
                                   return_address=prm.get("return_address"), request_id=request_id)
    if kind == "escalate":
        return client.escalate(dispute_id, prm["note"], request_id=request_id)
    if kind == "provide_evidence":
        files = [(prm["filename"], evidence_pdf, "application/pdf")] if evidence_pdf else []
        return client.provide_evidence(dispute_id, prm["evidences"], files, request_id=request_id)
    if kind == "appeal":
        files = [(prm["filename"], evidence_pdf, "application/pdf")] if evidence_pdf else []
        return client.appeal(dispute_id, prm["evidences"], files, request_id=request_id)
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
        # Once per proposal: a retry after a failed send must not add a second "approve" line.
        if not any(r["step"] == "approve" and r["detail"].get("proposal") == proposal_id
                   for r in audit.for_dispute(dispute_id)):
            audit.log(dispute_id, "approve", {"proposal": proposal_id, "by": approval["by"],
                                              "edited": approval["status"] == "edited"})
        pdf = None
        if any(a["kind"] in EVIDENCE_KINDS for a in actions):
            pdf = build_evidence_pdf(CaseFile.from_dict(state["case"]), Decision.from_dict(decision))
        current = client.get_dispute(dispute_id)

        results: list[dict] = []
        status = "EXECUTED"
        with permit_writes():
            for index, action in enumerate(actions):
                key = idempotency_key(proposal_id, index, action["kind"])
                if already_applied(current, action, state["case"]):
                    results.append({"action": action["kind"], "ok": True, "reconciled": True,
                                    "idempotency_key": key})
                    continue
                # VERIFY: for escalate and appeal this refusal can follow a send that landed (a crash, then a retry).
                # Retry safety for them rests on PayPal removing the link after success. S3 could not confirm that:
                # no sandbox escalate was recorded with the link present before and absent after.
                # `sent` False means this attempt sent nothing; the reason says an earlier attempt may have.
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

    def __init__(self, agent: DisputeAgent):
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
