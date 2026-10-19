"""Step 1-3 of the agent: triage the dispute and gather evidence.

Hard facts are computed in code, never guessed by the model: whether the
package was delivered, to which address, inside which policy window, whether a
refund or duplicate charge exists, and whether an AI assistant's purchase
matched what its user asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from pydantic import ValidationError

from .. import policies
from ..paypal.client import PayPalClient, PayPalError
from ..store import MerchantOrder, MerchantStore
from .toolkit import ReadOnlyToolkit


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


_ADDRESS_WORDS = {"street": "st", "avenue": "ave", "road": "rd", "apartment": "apt", "unit": "apt"}


def _norm(addr: str | None) -> str:
    """Lowercase, punctuation as spaces, common street words shortened: one address written two ways compares equal."""
    text = (addr or "").lower().replace("#", " apt ")
    out: list[str] = []
    for word in re.sub(r"[\W_]", " ", text).split():
        word = _ADDRESS_WORDS.get(word, word)
        if word == "apt" and out and out[-1] == "apt":  # "Apt #4B" becomes "apt apt 4b"
            continue
        out.append(word)
    return " ".join(out)


def _house_zip_city(addr: str) -> tuple[str, str, str] | None:
    """(house number, ZIP5, city's last word) of a normalised address, or None when one of the three is missing."""
    addr = re.sub(r"(\d{5}) (\d{4})$", r"\1\2", addr)  # ZIP+4 "89501-1234" normalises to "89501 1234": one token
    words = addr.split()
    if len(words) < 4 or not words[0].isdigit():
        return None
    zip_word, state = words[-1], words[-2]
    if not (zip_word.isdigit() and len(zip_word) in (5, 9)) or not (len(state) == 2 and state.isalpha()):
        return None
    return words[0], zip_word[:5], words[-3]


def _unit(addr: str) -> str | None:
    """The word after 'apt' in a normalised address, or None when there is no unit."""
    words = addr.split()
    if "apt" not in words or words.index("apt") + 1 >= len(words):
        return None
    i = words.index("apt") + 1
    unit = words[i]
    # "Apt 4 B" and "Apt 4-B" are "Apt 4B": join a lone trailing letter onto a unit that ends in a digit.
    if i + 1 < len(words) and len(words[i + 1]) == 1 and words[i + 1].isalpha() and unit[-1:].isdigit():
        unit += words[i + 1]
    return unit


def _address_match(delivered_to: str | None, ship_to: str | None) -> bool | None:
    """True when the addresses match after normalising. None when house number, ZIP and city agree but the rest is
    written differently (uncertain). False otherwise, including a different unit in the same building."""
    delivered, shipped = _norm(delivered_to), _norm(ship_to)
    if delivered == shipped:
        return True
    a, b = _house_zip_city(delivered), _house_zip_city(shipped)
    if a is not None and a == b:
        unit_a, unit_b = _unit(delivered), _unit(shipped)
        if unit_a and unit_b and unit_a != unit_b:
            return False
        return None
    return False


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
    def from_dict(cls, data: dict) -> CaseFile:
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


def normalize_text(text: str | None) -> str:
    """Collapse every run of whitespace to one space and strip the ends, so a re-wrapped copy compares equal."""
    return " ".join((text or "").split())


def seller_activity(dispute: dict) -> dict:
    """What the seller side already did on this dispute. `execute` compares against it, not against clocks, to tell
    whether its own message or offer has already landed. Messages are whitespace-normalised (`normalize_text`) so a
    copy PayPal re-wraps still matches. The `messages[].posted_by` (BUYER, SELLER) and `offer.history[].actor == 'SELLER'`
    shapes, and the offer note appearing as a SELLER message, were seen on the live sandbox (2026-10-14,
    tests/fixtures/sandbox_dispute_after_buyer_reply_*.json and sandbox_dispute_after_seller_message_*.json)."""
    return {
        "messages": [normalize_text(m.get("content")) for m in dispute.get("messages", [])
                     if m.get("posted_by") == "SELLER"],
        "offers": [h.get("offer_type") for h in (dispute.get("offer") or {}).get("history", [])
                   if h.get("actor") == "SELLER"],
    }


def dispute_actions(dispute: dict) -> dict[str, bool]:
    """Whether the seller may escalate or appeal this dispute now, read from PayPal's HATEOAS links. Fails closed:
    no links, or no matching link, means False.
    The 'escalate' rel was seen on the live sandbox (2026-10-14). VERIFY: the 'appeal' rel is from the Disputes v1 docs
    only, because the sandbox held no appealable dispute; if it differs, can_appeal stays False and the agent never
    proposes an appeal."""
    rels = {link.get("rel") for link in dispute.get("links") or []}
    return {
        "can_escalate": "escalate" in rels and dispute.get("dispute_life_cycle_stage") == "INQUIRY",
        "can_appeal": "appeal" in rels,
    }


def gather(dispute_id: str, client: PayPalClient, store: MerchantStore, now: datetime) -> CaseFile:
    calls: list[str] = []
    toolkit = ReadOnlyToolkit(client)  # every PayPal read below goes through its four read tools

    dispute = toolkit.call("get_dispute", {"dispute_id": dispute_id})
    calls.append(f"get_dispute: GET /v1/customer/disputes/{dispute_id}")
    txn = (dispute.get("disputed_transactions") or [{}])[0]
    capture_id = txn.get("seller_transaction_id")
    hint = {"now": now, "capture_id": capture_id, "buyer_name": (txn.get("buyer") or {}).get("name")}
    order = store.by_invoice(txn.get("invoice_number"), hint) or store.by_capture(capture_id)
    calls.append(f"merchant orders: lookup invoice {txn.get('invoice_number')}")
    if order and not order.order_id and capture_id:
        # A live order's PayPal order id is not in the merchant record; the capture says which order it belongs to.
        try:
            found = toolkit.call("get_capture_order_id", {"capture_id": capture_id})["order_id"]
            order = replace(order, order_id=found)
            calls.append(f"get_capture_order_id: GET /v2/payments/captures/{capture_id} (order id)")
        except PayPalError as exc:  # trackers then stay "not checked", like a 403 on transaction search
            calls.append(f"get_capture_order_id: GET /v2/payments/captures/{capture_id}: {exc.status}, "
                         "order id unknown, tracking not checked")
    if order and order.demo_fixture:
        calls.append("merchant record is a DEMO FIXTURE built from a labeled case, not a real shop record")

    trackers: list[dict] | None = None  # None = not checked
    transactions: list[dict] | None = None  # None = not checked or unavailable
    if order and order.order_id:
        try:
            trackers = toolkit.call(
                "get_order_trackers", {"order_id": order.order_id, "capture_id": capture_id}
            )["trackers"]
            calls.append(f"get_order_trackers: GET /v2/checkout/orders/{order.order_id} (shipping.trackers)")
        except ValidationError:  # empty or odd seller_transaction_id: no request was sent; trackers stay unchecked
            calls.append("get_order_trackers: skipped, capture id missing or invalid, tracking not checked")
    if order:
        start = order.created - timedelta(days=1)
        end = order.created + timedelta(days=1)
        try:
            transactions = toolkit.call(
                "list_transactions", {"start_date": start.isoformat(), "end_date": end.isoformat()}
            )["transaction_details"]
            calls.append("list_transactions: GET /v1/reporting/transactions (purchase day)")
        except PayPalError as exc:
            if exc.status != 403:  # sandbox apps without Transaction Search access get 403; not fatal
                raise
            calls.append(
                "list_transactions: GET /v1/reporting/transactions: 403, skipped (no Transaction Search access)"
            )

    amount = float(dispute["dispute_amount"]["value"])
    # The sandbox omits seller_response_due_date on some disputes (e.g. INQUIRY / UNDER_REVIEW).
    due = parse_time(dispute["seller_response_due_date"]) if dispute.get("seller_response_due_date") else None
    buyer_messages = buyer_statements(dispute)

    facts = _compute_facts(order, trackers, transactions, amount, now, buyer_messages)
    activity = seller_activity(dispute)
    # From the dispute itself, so set even when no merchant order was found.
    facts.update(dispute_actions(dispute),
                 seller_already_responded=bool(activity["messages"] or activity["offers"]))
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
        seller_activity=activity,
    )


_NEGATORS = {"not", "no", "without", "never", "cannot"}


def _mentions(said: str, words: tuple[str, ...], whole_word: bool = True) -> bool:
    """True if one of `words` appears in `said` (lowercase) and is not negated.

    A hit counts only at a word start, so "student" does not read as "dent". With `whole_word` it must also end the
    word (plus a plural or tense ending), so "tornado" does not read as "torn"; refund words skip that so "reimbursed"
    and "refundable" still match. A hit is negated by not, n't, no, never, without or "rather than" within the 4
    words before it, in the same clause ("i don't want a refund", "the box is not damaged"). One real hit anywhere
    is enough: "not damaged on the outside, but the lid is cracked" still counts.
    """
    said = said.replace("\u2019", "'")
    end = r"(?:s|es|ed|ing)?\b" if whole_word else ""
    for w in words:
        for m in re.finditer(r"\b" + re.escape(w).replace(r"\ ", r"\s+") + end, said):
            before = re.split(r"[.!?;,\n]", said[:m.start()])[-1].split()[-4:]
            negated = any(t in _NEGATORS or t.endswith("n't") for t in before) \
                or "rather than" in " ".join(before)
            if not negated:
                return True
    return False


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
            # True, False, or None: None means the address is written differently but house number, ZIP and city agree.
            f["delivered_address_matches"] = _address_match(s.delivered_to, order.ship_to)
            f["days_since_delivery"] = (now - s.event_at).days
            f["within_return_window"] = f["days_since_delivery"] <= policies.RETURN_WINDOW_DAYS
        else:
            f["within_return_window"] = True

    # Words from anything the buyer said: the refund request may sit in the claim notes, not the latest message.
    said = " ".join(buyer_messages).lower()
    f["buyer_asks_for_refund"] = _mentions(said, policies.REFUND_WORDS, whole_word=False)
    # Shipped, not delivered, and no carrier scan for LOST_PACKAGE_DAYS: treat the package as lost.
    f["likely_lost"] = bool(s and s.status != "DELIVERED"
                            and f["days_since_last_scan"] >= policies.LOST_PACKAGE_DAYS)
    # Damaged and under the small-item threshold: refund in full, no return required.
    # The disputed amount decides the size, not the first order line: a cheap first line must not make a big damaged
    # claim look small.
    f["buyer_reports_damage"] = _mentions(said, policies.DAMAGE_WORDS)
    f["refund_without_return_eligible"] = (amount < policies.SMALL_ITEM_REFUND_THRESHOLD
                                           and f["buyer_reports_damage"])

    f["refund_issued"] = bool(order.refunds)
    # The guard compares this with the disputed amount, so a partial refund is not mistaken for a full one.
    f["refunded_amount"] = round(sum(float(r["amount"]) for r in order.refunds), 2)
    if order.refunds:
        f["refund_ids"] = [r["refund_id"] for r in order.refunds]
    f["return_received"] = bool(order.return_shipment and order.return_shipment.status == "DELIVERED")
    if order.return_shipment:
        f["return_carrier"] = order.return_shipment.carrier
        f["return_tracking_number"] = order.return_shipment.number

    f["transaction_search_available"] = transactions is not None
    if transactions is not None:
        # VERIFY: PayPal rejects a reused invoice id by default (DUPLICATE_INVOICE_ID), so a real double checkout may
        # carry different invoice ids. Confirm with a real sandbox double charge. Pending ('P') charges are excluded
        # on purpose: only settled money counts as a duplicate.
        same_buyer = []
        for t in transactions:
            info = t.get("transaction_info", {})
            if (t.get("payer_info", {}).get("email_address") == order.buyer_email
                    and info.get("transaction_status") == "S"
                    and info.get("invoice_id") in (None, "", order.invoice_id)
                    and abs(float(info["transaction_amount"]["value"]) - amount) < 0.01):
                same_buyer.append(t)
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
