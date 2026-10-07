"""Step 1-3 of the agent: triage the dispute and gather evidence.

Hard facts are computed in code, never guessed by the model: whether the
package was delivered, to which address, inside which policy window, whether a
refund or duplicate charge exists, and whether an AI assistant's purchase
matched what its user asked for.
"""

from __future__ import annotations

from dataclasses import replace, dataclass, field
from datetime import datetime, timedelta

from .. import policies
from ..paypal.client import PayPalClient, PayPalError
from ..store import MerchantOrder, MerchantStore


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _norm(addr: str | None) -> str:
    return " ".join((addr or "").lower().replace(",", " ").split())


@dataclass
class CaseFile:
    dispute_id: str
    reason: str
    stage: str
    status: str
    amount: float
    currency: str
    due: datetime | None
    hours_left: float | None
    buyer_messages: list[str]
    order: MerchantOrder | None
    trackers: list[dict] | None
    transactions: list[dict] | None
    policies: list[tuple[str, str]]
    facts: dict
    tool_calls: list[str] = field(default_factory=list)
    allowed_response_options: dict | None = None  # PayPal's own list of what the seller may do now
    seller_activity: dict = field(default_factory=dict)  # seller messages and offer types already on the dispute

    @property
    def last_buyer_message(self) -> str:
        return self.buyer_messages[-1] if self.buyer_messages else ""

    def to_dict(self) -> dict:
        """JSON-safe snapshot: this is what travels through the graph state and into checkpoints."""
        return {
            "dispute_id": self.dispute_id, "reason": self.reason, "stage": self.stage, "status": self.status,
            "amount": self.amount, "currency": self.currency,
            "due": self.due.isoformat() if self.due else None, "hours_left": self.hours_left,
            "buyer_messages": self.buyer_messages, "order": self.order.to_dict() if self.order else None,
            "trackers": self.trackers, "transactions": self.transactions,
            "policies": [list(p) for p in self.policies], "facts": self.facts, "tool_calls": self.tool_calls,
            "allowed_response_options": self.allowed_response_options,
            "seller_activity": self.seller_activity,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CaseFile":
        return cls(**{
            **data,
            "due": parse_time(data["due"]) if data.get("due") else None,
            "order": MerchantOrder.from_dict(data["order"]) if data.get("order") else None,
            "policies": [tuple(p) for p in data["policies"]],
        })


def buyer_statements(dispute: dict) -> list[str]:
    """Everything the buyer has said, from the three places the real PayPal dispute holds it: the buyer's notes on the
    claim (`disputed_transactions[].items[].notes`, where "I would like a refund" lives), `evidences[]` the buyer
    submitted, and `messages[]` (the conversation). Claim notes and evidence come first because they are filed with the
    claim, so the last entry is the buyer's latest message; exact repeats are dropped (PayPal copies the opening
    message into `evidences`)."""
    found = []
    for txn in dispute.get("disputed_transactions") or []:
        found += [item.get("notes") for item in txn.get("items") or []]
    found += [e.get("notes") for e in dispute.get("evidences") or [] if e.get("source") == "SUBMITTED_BY_BUYER"]
    found += [m.get("content") for m in dispute.get("messages", []) if m.get("posted_by") == "BUYER"]
    out: list[str] = []
    for text in found:
        if text and text.strip() and text.strip() not in out:
            out.append(text.strip())
    return out


def seller_activity(dispute: dict) -> dict:
    """What the seller side already did on this dispute. `execute` compares against it, not against clocks, to tell
    whether its own message or offer has already landed."""
    return {
        "messages": [m.get("content") for m in dispute.get("messages", []) if m.get("posted_by") == "SELLER"],
        "offers": [h.get("offer_type") for h in (dispute.get("offer") or {}).get("history", [])
                   if h.get("actor") == "SELLER"],
    }


def gather(dispute_id: str, client: PayPalClient, store: MerchantStore, now: datetime) -> CaseFile:
    calls: list[str] = []

    dispute = client.get_dispute(dispute_id)
    calls.append(f"GET /v1/customer/disputes/{dispute_id}")
    txn = (dispute.get("disputed_transactions") or [{}])[0]
    capture_id = txn.get("seller_transaction_id")
    hint = {"now": now, "capture_id": capture_id, "buyer_name": (txn.get("buyer") or {}).get("name")}
    order = store.by_invoice(txn.get("invoice_number"), hint) or store.by_capture(capture_id)
    calls.append(f"merchant orders: lookup invoice {txn.get('invoice_number')}")
    if order and not order.order_id and capture_id:
        # A live order's PayPal order id is not in the merchant record; the capture says which order it belongs to.
        try:
            order = replace(order, order_id=client.get_capture_order_id(capture_id))
            calls.append(f"GET /v2/payments/captures/{capture_id} (order id)")
        except PayPalError as exc:  # trackers then stay "not checked", like a 403 on transaction search
            calls.append(f"GET /v2/payments/captures/{capture_id}: {exc.status}, order id unknown, tracking not checked")
    if order and order.demo_fixture:
        calls.append("merchant record is a DEMO FIXTURE built from a labeled case, not a real shop record")

    trackers: list[dict] | None = None  # None = not checked
    transactions: list[dict] | None = None  # None = not checked or unavailable
    if order and order.order_id:
        trackers = client.get_order_trackers(order.order_id, capture_id)
        calls.append(f"GET /v2/checkout/orders/{order.order_id} (shipping.trackers)")
    if order:
        start = order.created - timedelta(days=1)
        end = order.created + timedelta(days=1)
        try:
            transactions = client.search_transactions(start.isoformat(), end.isoformat())
            calls.append("GET /v1/reporting/transactions (purchase day)")
        except PayPalError as exc:
            if exc.status != 403:  # sandbox apps without Transaction Search access get 403; not fatal
                raise
            calls.append("GET /v1/reporting/transactions: 403, skipped (no Transaction Search access)")

    amount = float(dispute["dispute_amount"]["value"])
    # The sandbox omits seller_response_due_date on some disputes (e.g. INQUIRY / UNDER_REVIEW).
    due = parse_time(dispute["seller_response_due_date"]) if dispute.get("seller_response_due_date") else None
    buyer_messages = buyer_statements(dispute)

    facts = _compute_facts(order, trackers, transactions, amount, now, buyer_messages)
    query = " ".join([dispute["reason"].replace("_", " "), *buyer_messages,
                      "assistant" if facts.get("is_agent_purchase") else ""])
    return CaseFile(
        dispute_id=dispute_id,
        reason=dispute["reason"],
        stage=dispute["dispute_life_cycle_stage"],
        status=dispute["status"],
        amount=amount,
        currency=dispute["dispute_amount"]["currency_code"],
        due=due,
        hours_left=round((due - now).total_seconds() / 3600, 1) if due else None,
        buyer_messages=buyer_messages,
        order=order,
        trackers=trackers,
        transactions=transactions,
        policies=policies.retrieve(query, k=3),
        facts=facts,
        tool_calls=calls,
        allowed_response_options=dispute.get("allowed_response_options"),
        seller_activity=seller_activity(dispute),
    )


def _compute_facts(order, trackers, transactions, amount, now, buyer_messages=()) -> dict:
    f: dict = {"order_found": order is not None, "demo_fixture": bool(order and order.demo_fixture),
               "tracking_uploaded_to_paypal": None if trackers is None else bool(trackers)}
    if order is None:
        return f

    item = order.items[0]
    f["item"] = f'{item["name"]} ({item["variant"]})'
    f["item_price"] = item["price"]
    f["days_since_purchase"] = (now - order.created).days

    s = order.shipment
    f["has_tracking"] = s is not None
    # No shipment on file: the merchant has nothing to show that the package was sent or delivered.
    f["cannot_prove_delivery"] = s is None
    if s:
        f["carrier"] = s.carrier
        f["tracking_number"] = s.number
        f["shipment_status"] = s.status
        f["days_since_last_scan"] = (now - s.event_at).days
        if s.status == "DELIVERED":
            f["delivered_on"] = s.event_at.date().isoformat()
            f["delivered_address_matches"] = _norm(s.delivered_to) == _norm(order.ship_to)
            f["days_since_delivery"] = (now - s.event_at).days
            f["within_return_window"] = f["days_since_delivery"] <= policies.RETURN_WINDOW_DAYS
        else:
            f["within_return_window"] = True

    # Words from anything the buyer said: the refund request may sit in the claim notes, not the latest message.
    said = " ".join(buyer_messages).lower()
    f["buyer_asks_for_refund"] = any(w in said for w in policies.REFUND_WORDS)
    # Shipped, not delivered, and no carrier scan for LOST_PACKAGE_DAYS: treat the package as lost.
    f["likely_lost"] = bool(s and s.status != "DELIVERED"
                            and f["days_since_last_scan"] >= policies.LOST_PACKAGE_DAYS)
    # Damaged and under the small-item threshold: refund in full, no return required.
    f["refund_without_return_eligible"] = (item["price"] < policies.SMALL_ITEM_REFUND_THRESHOLD
                                           and any(w in said for w in policies.DAMAGE_WORDS))

    f["refund_issued"] = bool(order.refunds)
    if order.refunds:
        f["refund_ids"] = [r["refund_id"] for r in order.refunds]
    f["return_received"] = bool(order.return_shipment and order.return_shipment.status == "DELIVERED")

    f["transaction_search_available"] = transactions is not None
    if transactions is not None:
        same_buyer = [
            t for t in transactions
            if t.get("payer_info", {}).get("email_address") == order.buyer_email
            and abs(float(t["transaction_info"]["transaction_amount"]["value"]) - amount) < 0.01
        ]
        f["matching_charges_same_day"] = len(same_buyer)
        f["duplicate_charge_found"] = len(same_buyer) > 1

    intent = order.intent
    f["is_agent_purchase"] = intent is not None
    f["assistant_misordered"] = False
    if intent:
        constraints = intent.get("constraints", {})
        wanted_variant = constraints.get("variant")
        variant_ok = wanted_variant is None or wanted_variant.lower() in item["variant"].lower()
        price_ok = item["price"] <= constraints.get("max_price", float("inf"))
        f["agent_name"] = intent["agent"]
        f["agent_instruction"] = intent["user_instruction"]
        f["agent_followed_instruction"] = variant_ok
        f["assistant_misordered"] = not variant_ok  # the assistant's order didn't match its user's instruction
        f["within_agent_spending_limit"] = price_ok
    return f
