"""The agent pipeline: gather -> decide -> guard -> plan actions -> wait for approval.

`analyze` never changes anything at PayPal. It returns a Proposal whose
actions only run through `approval.ApprovalQueue.approve`.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from fpdf import FPDF

from .. import policies
from ..audit import AuditLog
from ..paypal.client import PayPalClient
from ..store import MerchantStore
from .facts import CaseFile, gather
from .reasoner import Decision, guard


@dataclass
class PlannedAction:
    kind: str  # send_message | make_offer | provide_evidence | accept_claim
    summary: str
    params: dict


@dataclass
class Proposal:
    id: str
    dispute_id: str
    created: str
    decision: Decision
    actions: list[PlannedAction]
    case_summary: dict
    status: str = "PENDING"  # PENDING | EXECUTED | REJECTED | FAILED
    result: list[dict] = field(default_factory=list)
    evidence_pdf: bytes | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("evidence_pdf", None)
        d["has_evidence_document"] = self.evidence_pdf is not None
        return d


def _money(v: float) -> dict:
    return {"currency_code": "USD", "value": f"{v:.2f}"}


def plan_actions(decision: Decision, case: CaseFile) -> tuple[list[PlannedAction], bytes | None]:
    """One PayPal call per proposal. The explanation for the buyer rides in the offer's `note`, never in a
    separate message: in the real sandbox a message moved the dispute to UNDER_REVIEW and blocked the offer."""
    actions, pdf = _plan_actions(decision, case)
    if len(actions) != 1:
        raise RuntimeError(f"A proposal must carry exactly one PayPal call, got {[a.kind for a in actions]}")
    return actions, pdf


def _plan_actions(decision: Decision, case: CaseFile) -> tuple[list[PlannedAction], bytes | None]:
    f, r = case.facts, decision.resolution
    msg = decision.message_to_buyer
    pdf: bytes | None = None

    if r == "SHARE_TRACKING":
        return [PlannedAction("send_message", "Message buyer with tracking", {"message": msg})], None
    if r == "OFFER_REPLACEMENT":
        return [PlannedAction("make_offer", "Offer replacement (no refund)",
                              {"note": msg, "offer_type": "REPLACEMENT_WITHOUT_REFUND"})], None
    if r == "OFFER_PARTIAL_REFUND":
        amount = round(case.amount * (decision.partial_refund_pct or 15) / 100, 2)
        return [PlannedAction("make_offer", f"Offer ${amount:.2f} partial refund",
                              {"note": msg, "offer_type": "REFUND", "amount": _money(amount)})], None
    if r == "OFFER_RETURN_FOR_REFUND":
        return [PlannedAction("make_offer", f"Offer full refund of ${case.amount:.2f} after return",
                              {"note": msg, "offer_type": "REFUND_WITH_RETURN", "amount": _money(case.amount),
                               "return_address": policies.RETURN_ADDRESS})], None
    if r == "ACCEPT_CLAIM":
        return [PlannedAction("accept_claim", f"Accept claim and refund ${case.amount:.2f}", {"note": msg})], None

    if r == "SUBMIT_REFUND_PROOF":
        evidences = [{"evidence_type": "PROOF_OF_REFUND",
                      "evidence_info": {"refund_ids": f.get("refund_ids", [])},
                      "notes": decision.evidence_summary[:2000]}]
    else:  # SUBMIT_EVIDENCE
        if f.get("shipment_status") == "DELIVERED":
            evidences = [{"evidence_type": "PROOF_OF_FULFILLMENT",
                          "evidence_info": {"tracking_info": [{"carrier_name": f["carrier"],
                                                               "tracking_number": f["tracking_number"]}]},
                          "notes": decision.evidence_summary[:2000]}]
        else:
            evidences = [{"evidence_type": "OTHER", "notes": decision.evidence_summary[:2000]}]
    pdf = build_evidence_pdf(case, decision)
    return [PlannedAction("provide_evidence", f"Submit {evidences[0]['evidence_type']} with evidence PDF",
                          {"evidences": evidences, "filename": f"evidence-{case.dispute_id}.pdf"})], pdf


def _latin1(text: str) -> str:
    return text.replace("—", "-").replace("’", "'").replace("“", '"').replace(
        "”", '"').encode("latin-1", "replace").decode("latin-1")


def build_evidence_pdf(case: CaseFile, decision: Decision) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, _latin1(f"Seller evidence - dispute {case.dispute_id}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    rows = [("Merchant", MerchantStore.name), ("Reason", case.reason), ("Amount", f"${case.amount:.2f}")]
    if case.order:
        rows += [("Invoice", case.order.invoice_id), ("Order date", case.order.created.date().isoformat()),
                 ("Ship to", case.order.ship_to)]
    for key in ("item", "carrier", "tracking_number", "shipment_status", "delivered_on"):
        if key in case.facts:
            rows.append((key.replace("_", " ").title(), str(case.facts[key])))
    for k, v in rows:
        pdf.multi_cell(0, 6, _latin1(f"{k}: {v}"), new_x="LMARGIN", new_y="NEXT")
    if case.order and case.order.intent:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "AI assistant purchase record", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        it = case.order.intent
        for line in (f"Assistant: {it['agent']}", f"Instruction from account holder: {it['user_instruction']}",
                     f"Item submitted by assistant: {it['submitted_item']}", f"Recorded at: {it['recorded_at']}"):
            pdf.multi_cell(0, 6, _latin1(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(0, 6, _latin1(decision.evidence_summary), new_x="LMARGIN", new_y="NEXT")
    for title, body in case.policies:
        pdf.multi_cell(0, 6, _latin1(f"Policy - {title}: {body}"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


class Agent:
    def __init__(self, client: PayPalClient, store: MerchantStore, reasoner, audit: AuditLog, clock):
        self.client, self.store, self.reasoner, self.audit, self.clock = client, store, reasoner, audit, clock

    def analyze(self, dispute_id: str) -> Proposal:
        now: datetime = self.clock()
        case = gather(dispute_id, self.client, self.store, now)
        self.audit.log(dispute_id, "gather", {"tool_calls": case.tool_calls, "facts": case.facts,
                                              "policies": [t for t, _ in case.policies]})
        decision = self.reasoner.decide(case)
        self.audit.log(dispute_id, "decide", {"source": decision.source, "resolution": decision.resolution,
                                              "confidence": decision.confidence, "reasoning": decision.reasoning})
        decision = guard(decision, case)
        if decision.guard_notes:
            self.audit.log(dispute_id, "guard", {"notes": decision.guard_notes})
        actions, pdf = plan_actions(decision, case)
        proposal = Proposal(
            id=f"prop_{uuid.uuid4().hex[:8]}",
            dispute_id=dispute_id,
            created=now.isoformat(),
            decision=decision,
            actions=actions,
            case_summary={
                "reason": case.reason, "stage": case.stage, "amount": case.amount,
                "due": case.due.isoformat() if case.due else None, "hours_left": case.hours_left,
                "buyer": case.order.buyer_name if case.order else None,
                "buyer_messages": case.buyer_messages, "facts": case.facts,
                "policies": [t for t, _ in case.policies], "tool_calls": case.tool_calls,
            },
            evidence_pdf=pdf,
        )
        self.audit.log(dispute_id, "propose", {"proposal": proposal.id,
                                               "actions": [a.summary for a in actions]})
        return proposal
