"""Store policies and a small retriever.

Week 4 swaps `retrieve` for Elasticsearch hybrid search; the interface stays.
"""

from __future__ import annotations

import re

RETURN_WINDOW_DAYS = 30
SMALL_ITEM_REFUND_THRESHOLD = 20.0
LOST_PACKAGE_DAYS = 10
DAMAGE_WORDS = ("broken", "cracked", "damaged", "scratch", "shattered", "dent", "torn", "chipped", "leak")
REFUND_WORDS = ("refund", "money back", "my money", "reimburse", "get my money", "charge back", "chargeback")

RETURN_ADDRESS = {
    "address_line_1": "200 Congress Ave",
    "admin_area_2": "Austin",
    "admin_area_1": "TX",
    "postal_code": "78701",
    "country_code": "US",
}

POLICY_SECTIONS: list[tuple[str, str]] = [
    ("Returns", "Unused items can be returned within 30 days of delivery for a full refund. "
     "The buyer pays return shipping unless the item arrived damaged or incorrect."),
    ("Size exchanges", "Apparel can be exchanged for a different size free of charge within "
     "30 days of delivery. We ship the new size as soon as the return is scanned by the carrier."),
    ("Damaged items", "If an item arrives damaged or broken, contact us within 7 days and we replace it "
     "or refund it. If a damaged item costs under $20, we refund it in full and do not ask for a return."),
    ("Shipping", "Orders ship within 2 business days with tracking uploaded to PayPal. Delivery "
     "usually takes 3 to 7 business days."),
    ("Lost packages", "If tracking shows no movement for 10 days, we file a carrier claim and send "
     "a replacement or a full refund, whichever the buyer prefers."),
    ("AI assistant purchases", "Orders placed by a customer's AI shopping assistant are processed "
     "exactly as the assistant submits them. We store the assistant's purchase instructions with "
     "the order. If an assistant picks the wrong size or variant, we offer a free exchange."),
    ("Standing reorders", "Standing reorder instructions a customer gives their assistant stay "
     "active until the customer cancels them. Each reorder is charged and shipped like a normal order."),
]

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


def retrieve(query: str, k: int = 3) -> list[tuple[str, str]]:
    q = _tokens(query)
    scored = sorted(
        POLICY_SECTIONS,
        key=lambda s: len(q & _tokens(s[0] + " " + s[1])),
        reverse=True,
    )
    return scored[:k]
