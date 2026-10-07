"""The single approval gate. The only code path that changes a dispute at PayPal."""

from __future__ import annotations

from .agent.pipeline import Proposal
from .audit import AuditLog
from .paypal.client import PayPalClient, PayPalError


class ApprovalError(RuntimeError):
    pass


class ApprovalQueue:
    def __init__(self, client: PayPalClient, audit: AuditLog):
        self.client = client
        self.audit = audit
        self.proposals: dict[str, Proposal] = {}

    def submit(self, proposal: Proposal) -> Proposal:
        self.proposals[proposal.id] = proposal
        return proposal

    def pending(self) -> list[Proposal]:
        return [p for p in self.proposals.values() if p.status == "PENDING"]

    def latest_for(self, dispute_id: str) -> Proposal | None:
        found = [p for p in self.proposals.values() if p.dispute_id == dispute_id]
        return found[-1] if found else None

    def reject(self, proposal_id: str, reason: str = "", approver: str = "merchant") -> Proposal:
        p = self._get_pending(proposal_id)
        p.status = "REJECTED"
        self.audit.log(p.dispute_id, "reject", {"proposal": p.id, "by": approver, "reason": reason})
        return p

    def approve(self, proposal_id: str, edited_message: str | None = None, approver: str = "merchant") -> Proposal:
        p = self._get_pending(proposal_id)
        if edited_message:
            for a in p.actions:
                if "message" in a.params:
                    a.params["message"] = edited_message
                if "note" in a.params:
                    a.params["note"] = edited_message
            p.decision.message_to_buyer = edited_message
        self.audit.log(p.dispute_id, "approve", {"proposal": p.id, "by": approver, "edited": bool(edited_message)})

        for action in p.actions:
            try:
                response = self._execute(p, action)
                p.result.append({"action": action.kind, "ok": True, "response": response})
                self.audit.log(p.dispute_id, "execute", {"action": action.kind, "summary": action.summary})
            except PayPalError as exc:
                p.status = "FAILED"
                p.result.append({"action": action.kind, "ok": False, "error": str(exc)})
                self.audit.log(p.dispute_id, "execute_failed", {"action": action.kind, "error": str(exc)})
                return p
        p.status = "EXECUTED"
        return p

    def _get_pending(self, proposal_id: str) -> Proposal:
        p = self.proposals.get(proposal_id)
        if p is None:
            raise ApprovalError(f"Unknown proposal {proposal_id}")
        if p.status != "PENDING":
            raise ApprovalError(f"Proposal {proposal_id} is {p.status}, not PENDING")
        return p

    def _execute(self, p: Proposal, action) -> dict:
        prm = action.params
        if action.kind == "send_message":
            return self.client.send_message(p.dispute_id, prm["message"])
        if action.kind == "make_offer":
            return self.client.make_offer(p.dispute_id, note=prm["note"], offer_type=prm["offer_type"],
                                          amount=prm.get("amount"), return_address=prm.get("return_address"))
        if action.kind == "accept_claim":
            return self.client.accept_claim(p.dispute_id, note=prm["note"])
        if action.kind == "provide_evidence":
            files = [(prm["filename"], p.evidence_pdf, "application/pdf")] if p.evidence_pdf else []
            return self.client.provide_evidence(p.dispute_id, prm["evidences"], files)
        raise ApprovalError(f"Unknown action {action.kind}")
