"""Turns a labeled case (evals/cases.json) into PayPal sandbox state + merchant records.

Used by the eval runner, the demo, and the judge-facing simulator in mock mode.
In sandbox mode the same cases drive scripts/seed_sandbox.py (week 2).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .paypal.mock import MockPayPal
from .store import MerchantOrder, MerchantStore, Shipment

DEMO_NOW = datetime(2026, 10, 6, 15, 0, tzinfo=UTC)
CASES_PATH = Path(__file__).resolve().parents[1] / "evals" / "cases.json"
INQUIRY_RESPONSE_DAYS = 10  # VERIFY: real sandbox omitted seller_response_due_date on an INQUIRY in UNDER_REVIEW

BUYERS = [
    ("Priya Shah", "priya.s@example.com"), ("Marcus Lee", "marcus.l@example.com"),
    ("Dana Ortiz", "dana.o@example.com"), ("Sam Okafor", "sam.o@example.com"),
    ("Lena Novak", "lena.n@example.com"), ("Theo Grant", "theo.g@example.com"),
]


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text())


@lru_cache(maxsize=1)
def _default_cases() -> tuple[dict, ...]:
    return tuple(load_cases())


def _money(value: float) -> dict:
    return {"currency_code": "USD", "value": f"{value:.2f}"}


def _txn(txn_id: str, when: datetime, amount: float, email: str, invoice: str) -> dict:
    return {
        "transaction_info": {
            "transaction_id": txn_id,
            "transaction_initiation_date": iso(when),
            "transaction_amount": _money(amount),
            "transaction_status": "S",
            "invoice_id": invoice,
        },
        "payer_info": {"email_address": email},
    }


LIVE_INVOICE = re.compile(r"^RB-([A-Za-z0-9_]+)-(\d+)$")


def live_invoice_id(case_id: str, stamp: int) -> str:
    """The invoice id scripts/make_test_order.py puts on a sandbox order so the store can find the case's record."""
    return f"RB-{case_id}-{stamp}"


def build_order(case: dict, *, index: int, invoice: str, capture_id: str, order_id: str | None, now: datetime,
                buyer: tuple[str, str]) -> MerchantOrder:
    """The merchant record a labeled case describes, placed `days_since_purchase` days before `now`."""
    purchased = now - timedelta(days=case["days_since_purchase"])
    item = dict(case["item"], qty=1)

    shipment = None
    if case.get("shipment"):
        s = case["shipment"]
        shipment = Shipment(
            carrier=s["carrier"], number=s["number"], status=s["status"],
            delivered_to=s.get("delivered_to"),
            event_at=purchased + timedelta(days=s["days_after_purchase"]),
        )

    return_shipment = None
    if case.get("return_shipment"):
        r = case["return_shipment"]
        return_shipment = Shipment(r["carrier"], r["number"], r["status"], "Juniper & Oak returns",
                                   now - timedelta(days=r["days_ago"]))

    refunds = []
    if case.get("refund"):
        refunds.append({"refund_id": f"RF{index:03d}2Y7741", "amount": case["refund"]["amount"],
                        "at": iso(now - timedelta(days=case["refund"]["days_ago"]))})

    intent = None
    if case.get("agent_purchase"):
        a = case["agent_purchase"]
        intent = {
            "intent_id": f"INT-{index:04d}",
            "agent": a["agent"],
            "user_instruction": a["instruction"],
            "constraints": a.get("constraints", {}),
            "submitted_item": {"sku": item["sku"], "variant": item["variant"], "price": item["price"]},
            "recorded_at": iso(purchased),
        }

    return MerchantOrder(
        invoice_id=invoice, capture_id=capture_id, created=purchased, buyer_name=buyer[0],
        buyer_email=buyer[1], items=[item], ship_to=case["ship_to"], shipment=shipment,
        intent=intent, refunds=refunds, return_shipment=return_shipment, order_id=order_id,
    )


def fixture_order(invoice: str, hint: dict) -> MerchantOrder | None:
    """Merchant record for a live sandbox order whose invoice id is `RB-<case id>-<digits>` (see
    scripts/make_test_order.py). The record comes from evals/cases.json, which ships with the backend, so it works on
    Render. It is a demo fixture: the order is placed `days_since_purchase` days before the dispute is gathered, with
    the case's shipment and (for AI-assistant cases) the assistant's purchase intent. Real orders do not match. Fixture records are flagged `demo_fixture`, which
    shows in the case facts, the audit trail and the proposal. Limits: `created` is relative to when the dispute is
    gathered and the buyer email is a placeholder, so duplicate-charge facts are not reliable for these orders."""
    match = LIVE_INVOICE.fullmatch(invoice)
    if not match:
        return None
    case = next((c for c in _default_cases() if c["id"] == match.group(1)), None)
    if case is None:
        return None
    order = build_order(case, index=int(match.group(2)) % 10_000, invoice=invoice,
                        capture_id=hint.get("capture_id") or "", order_id=None,
                        now=hint.get("now") or datetime.now(UTC),
                        buyer=(hint.get("buyer_name") or BUYERS[0][0], hint.get("buyer_email") or BUYERS[0][1]))
    order.demo_fixture = True
    return order


def seed_case(case: dict, index: int, mock: MockPayPal, store: MerchantStore, now: datetime = DEMO_NOW) -> str:
    """Create the order, payment, tracking and dispute for one case. Returns dispute_id."""
    name, email = BUYERS[index % len(BUYERS)]
    purchased = now - timedelta(days=case["days_since_purchase"])
    opened = now - timedelta(days=case.get("days_open", 1), hours=3)
    invoice = f"JO-{3000 + index}"
    capture_id = f"8MC{index:03d}58471P{index:03d}X"
    order_id = f"5O{index:03d}19047A{index:03d}Z"
    dispute_id = f"PP-D-{2000 + index}"
    item = dict(case["item"], qty=1)
    amount = item["price"]

    mock.add_order(order_id, capture_id)
    order = build_order(case, index=index, invoice=invoice, capture_id=capture_id, order_id=order_id, now=now,
                        buyer=(name, email))
    if order.shipment:
        mock.add_tracker(order_id, capture_id, order.shipment.number,
                         "DELIVERED" if order.shipment.status == "DELIVERED" else "SHIPPED")
    store.add(order)

    mock.add_transaction(_txn(capture_id, purchased, amount, email, invoice))
    if case.get("duplicate_charge"):
        mock.add_transaction(_txn(capture_id + "D", purchased + timedelta(minutes=2), amount, email, invoice))

    mock.add_dispute({
        "dispute_id": dispute_id,
        "create_time": iso(opened),
        "update_time": iso(opened),
        "reason": case["reason"],
        "status": "WAITING_FOR_SELLER_RESPONSE",
        "dispute_life_cycle_stage": case["stage"],
        "dispute_channel": "INTERNAL",
        "dispute_amount": _money(amount),
        "seller_response_due_date": iso(opened + timedelta(days=INQUIRY_RESPONSE_DAYS)),
        "disputed_transactions": [{
            "seller_transaction_id": capture_id,
            "buyer_transaction_id": f"BUY{index:03d}",
            "create_time": iso(purchased),
            "gross_amount": _money(amount),
            "invoice_number": invoice,
            "custom": invoice,
            "buyer": {"name": name},
            "items": [{"item_name": f'{item["name"]} ({item["variant"]})', "item_description": item["name"],
                       "item_quantity": "1", "reason": case["reason"], "notes": case["buyer_message"],
                       "item_type": "PRODUCT"}],
        }],
        "messages": [{"posted_by": "BUYER", "time_posted": iso(opened), "content": case["buyer_message"]}],
        # The real sandbox echoes the buyer's opening message as a CREATE evidence.
        "evidences": [{"evidence_type": "CREATE", "notes": case["buyer_message"], "source": "SUBMITTED_BY_BUYER",
                       "date": iso(opened), "dispute_life_cycle_stage": case["stage"]}],
    })
    return dispute_id
