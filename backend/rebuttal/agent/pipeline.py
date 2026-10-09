"""Pure pieces of the dispute workflow: plan the PayPal action, build the evidence PDF, shape a proposal.

The workflow itself (gather -> decide -> guard -> plan -> approval -> execute -> record) is the LangGraph graph in
`agent/graph.py`; everything here is deterministic code that its nodes call. Nothing in this module talks to PayPal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from fpdf import FPDF

from .. import policies
from ..store import MerchantStore
from .facts import CaseFile
from .reasoner import Decision


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
    status: str = "PENDING"  # PENDING | APPROVED (execution interrupted, retry) | EXECUTED | REJECTED | FAILED
    result: list[dict] = field(default_factory=list)
    # What the buyer will read once the merchant has approved: their edit if they made one, else the drafted text.
    # Read-only for the dashboard (the retry dialog shows it); `execute` reads the approval record itself.
    approved_message: str | None = None
    evidence_pdf: bytes | None = field(default=None, repr=False)

    @property
    def needs_evidence_pdf(self) -> bool:
        return any(a.kind == "provide_evidence" for a in self.actions)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("evidence_pdf", None)
        d["has_evidence_document"] = self.needs_evidence_pdf
        return d

    @classmethod
    def from_state(cls, values: dict, *, status: str | None = None, with_pdf: bool = False) -> Proposal:
        """Rebuild a proposal from graph state (the case, decision and actions are all JSON in the checkpoint)."""
        case = CaseFile.from_dict(values["case"])
        decision = Decision.from_dict(values["decision"])
        proposal = cls(
            id=values["proposal_id"], dispute_id=values["dispute_id"], created=values["created"],
            decision=decision, actions=[PlannedAction(**a) for a in values["actions"]],
            case_summary=case_summary(case), status=status or values.get("status") or "PENDING",
            result=list(values.get("result") or []),
            approved_message=approved_text(values["actions"], values.get("approval")),
        )
        if with_pdf and proposal.needs_evidence_pdf:
            proposal.evidence_pdf = build_evidence_pdf(case, decision)
        return proposal


def approved_text(actions: list[dict], approval: dict | None) -> str | None:
    """The buyer-facing text the merchant approved, for display only (nothing here sends or changes anything).

    An edit lives in the approval record until `execute` applies it to the action, so while an approved proposal is
    waiting for a retry the planned action still holds the draft. None before a decision, after a rejection, and for
    an action with no buyer text (evidence)."""
    status = (approval or {}).get("status")
    if status not in ("approved", "edited") or not actions:
        return None
    params = actions[0]["params"]
    drafted = params.get("message", params.get("note"))
    if drafted is None:
        return None
    return approval["edited_message"] if status == "edited" else drafted


def case_summary(case: CaseFile) -> dict:
    return {
        "reason": case.reason, "stage": case.stage, "amount": case.amount,
        "due": case.due.isoformat() if case.due else None, "hours_left": case.hours_left,
        "buyer": case.order.buyer_name if case.order else None,
        "buyer_messages": case.buyer_messages, "facts": case.facts,
        "policies": [t for t, _ in case.policies], "tool_calls": case.tool_calls,
    }


def _money(v: float) -> dict:
    return {"currency_code": "USD", "value": f"{v:.2f}"}


def plan_actions(decision: Decision, case: CaseFile) -> list[PlannedAction]:
    """One PayPal call per proposal. The explanation for the buyer rides in the offer's `note`, never in a
    separate message: in the real sandbox a message moved the dispute to UNDER_REVIEW and blocked the offer.
    The evidence PDF is not built here; it is rebuilt from the case and decision at execution time."""
    actions = _plan_actions(decision, case)
    if len(actions) != 1:
        raise RuntimeError(f"A proposal must carry exactly one PayPal call, got {[a.kind for a in actions]}")
    return actions


def _plan_actions(decision: Decision, case: CaseFile) -> list[PlannedAction]:
    f, r = case.facts, decision.resolution
    msg = decision.message_to_buyer

    if r == "SHARE_TRACKING":
        return [PlannedAction("send_message", "Message buyer with tracking", {"message": msg})]
    if r == "OFFER_REPLACEMENT":
        return [PlannedAction("make_offer", "Offer replacement (no refund)",
                              {"note": msg, "offer_type": "REPLACEMENT_WITHOUT_REFUND"})]
    if r == "OFFER_PARTIAL_REFUND":
        amount = round(case.amount * (decision.partial_refund_pct or 15) / 100, 2)
        return [PlannedAction("make_offer", f"Offer ${amount:.2f} partial refund",
                              {"note": msg, "offer_type": "REFUND", "amount": _money(amount)})]
    if r == "OFFER_RETURN_FOR_REFUND":
        return [PlannedAction("make_offer", f"Offer full refund of ${case.amount:.2f} after return",
                              {"note": msg, "offer_type": "REFUND_WITH_RETURN", "amount": _money(case.amount),
                               "return_address": policies.RETURN_ADDRESS})]
    if r == "ACCEPT_CLAIM":
        return [PlannedAction("accept_claim", f"Accept claim and refund ${case.amount:.2f}", {"note": msg})]

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
    return [PlannedAction("provide_evidence", f"Submit {evidences[0]['evidence_type']} with evidence PDF",
                          {"evidences": evidences, "filename": f"evidence-{case.dispute_id}.pdf"})]


def _latin1(text: str) -> str:
    return text.replace("—", "-").replace("’", "'").replace("“", '"').replace(
        "”", '"').encode("latin-1", "replace").decode("latin-1")


def build_evidence_pdf(case: CaseFile, decision: Decision) -> bytes:
    """Deterministic: rebuilt at execution time, and a retry must send the same bytes under the same request id."""
    pdf = FPDF()
    pdf.set_creation_date(case.order.created if case.order else datetime(2000, 1, 1, tzinfo=UTC))
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
