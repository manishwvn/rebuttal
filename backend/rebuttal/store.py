"""The merchant's own order system (what a small shop already has).

PayPal knows the payment; the shop knows what was in the box, where it went,
and — for orders placed by a buyer's AI assistant — what the assistant was
told to buy. Disputes link back here through the invoice number we set as
`invoice_id` / `custom_id` on the PayPal order at checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@dataclass
class Shipment:
    carrier: str
    number: str
    status: str  # DELIVERED | IN_TRANSIT
    delivered_to: str | None
    event_at: datetime  # delivery time, or last carrier scan if in transit

    def to_dict(self) -> dict:
        return {"carrier": self.carrier, "number": self.number, "status": self.status,
                "delivered_to": self.delivered_to, "event_at": _ts(self.event_at)}

    @classmethod
    def from_dict(cls, data: dict) -> "Shipment":
        return cls(**{**data, "event_at": datetime.fromisoformat(data["event_at"])})


@dataclass
class MerchantOrder:
    invoice_id: str
    capture_id: str
    created: datetime
    buyer_name: str
    buyer_email: str
    items: list[dict]
    ship_to: str
    shipment: Shipment | None = None
    intent: dict | None = None  # purchase-intent record from the buyer's AI assistant
    refunds: list[dict] = field(default_factory=list)
    return_shipment: Shipment | None = None
    order_id: str | None = None  # PayPal order id; needed to read trackers from the order

    def to_dict(self) -> dict:
        """JSON-safe snapshot (datetimes as ISO strings), used in graph state and checkpoints."""
        return {
            "invoice_id": self.invoice_id, "capture_id": self.capture_id, "created": _ts(self.created),
            "buyer_name": self.buyer_name, "buyer_email": self.buyer_email, "items": self.items,
            "ship_to": self.ship_to, "shipment": self.shipment.to_dict() if self.shipment else None,
            "intent": self.intent, "refunds": self.refunds,
            "return_shipment": self.return_shipment.to_dict() if self.return_shipment else None,
            "order_id": self.order_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MerchantOrder":
        return cls(**{
            **data,
            "created": datetime.fromisoformat(data["created"]),
            "shipment": Shipment.from_dict(data["shipment"]) if data.get("shipment") else None,
            "return_shipment": Shipment.from_dict(data["return_shipment"]) if data.get("return_shipment") else None,
        })

    @property
    def total(self) -> float:
        return round(sum(i["price"] * i.get("qty", 1) for i in self.items), 2)


class MerchantStore:
    name = "Juniper & Oak"

    def __init__(self) -> None:
        self._by_invoice: dict[str, MerchantOrder] = {}
        self._by_capture: dict[str, MerchantOrder] = {}

    def add(self, order: MerchantOrder) -> None:
        self._by_invoice[order.invoice_id] = order
        self._by_capture[order.capture_id] = order

    def by_invoice(self, invoice_id: str | None) -> MerchantOrder | None:
        return self._by_invoice.get(invoice_id or "")

    def by_capture(self, capture_id: str | None) -> MerchantOrder | None:
        return self._by_capture.get(capture_id or "")
