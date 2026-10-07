"""The merchant's own order system (what a small shop already has).

PayPal knows the payment; the shop knows what was in the box, where it went,
and — for orders placed by a buyer's AI assistant — what the assistant was
told to buy. Disputes link back here through the invoice number we set as
`invoice_id` / `custom_id` on the PayPal order at checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Shipment:
    carrier: str
    number: str
    status: str  # DELIVERED | IN_TRANSIT
    delivered_to: str | None
    event_at: datetime  # delivery time, or last carrier scan if in transit


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
