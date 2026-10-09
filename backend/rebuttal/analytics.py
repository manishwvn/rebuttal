"""Read-only analytics over disputes, their latest proposal and the audit trail.

Pure functions, with no I/O and no Runtime, so each rule is unit-tested without PayPal. `app.py` gathers the three
inputs (the dispute list, `Proposal.to_dict()` per dispute and the audit records per dispute) and passes them in.

Outcome of a dispute (`build_rows`):
- no proposal                                                   -> not_analyzed
- proposal REJECTED / FAILED                                    -> rejected / failed
- proposal EXECUTED, by its final resolution:
    ACCEPT_CLAIM, OFFER_RETURN_FOR_REFUND                       -> refunded (the full amount is agreed)
    OFFER_PARTIAL_REFUND                                        -> partially_refunded (the offered amount, 0 if unreadable)
    SHARE_TRACKING, OFFER_REPLACEMENT, SUBMIT_EVIDENCE,
    SUBMIT_REFUND_PROOF                                         -> kept (we agreed no refund; for evidence PayPal
                                                                   still decides)
- anything else (PENDING, APPROVED, INTERRUPTED)                -> awaiting_merchant

Money, in cents, so that refunded + kept + open == amount on every row. Only an EXECUTED proposal moves money: its
refunded part is the whole amount for `refunded`, the offered amount (capped at the disputed amount) for
`partially_refunded`, and nothing otherwise. The rest of an executed amount is kept, and everything else is open.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .agent.facts import parse_time

NOT_ANALYZED = "NOT_ANALYZED"
CENT = Decimal("0.01")
_EXECUTED_OUTCOME = {"ACCEPT_CLAIM": "refunded", "OFFER_RETURN_FOR_REFUND": "refunded",
                     "OFFER_PARTIAL_REFUND": "partially_refunded"}  # any other executed resolution is "kept"
_CLOSED_OUTCOME = {"REJECTED": "rejected", "FAILED": "failed"}


def build_rows(disputes: list[dict], proposals: dict[str, dict], audits: dict[str, list[dict]]) -> list[dict]:
    """One row per dispute, in input order. `proposals` maps a dispute id to `Proposal.to_dict()` (absent = not
    analysed) and `audits` maps it to that dispute's audit records. `agrees` is 1 when the reasoner's first choice
    (the last `decide` record) is the final resolution, 0 when the guard changed it, and None when either is missing."""
    return [_row(d, proposals.get(d["dispute_id"]), audits.get(d["dispute_id"], [])) for d in disputes]


def summarize(rows: list[dict], now: datetime) -> dict[str, Any]:
    """Totals, the breakdowns by reason and by product, the money split, and how often the guard changed the
    reasoner's choice. Sums are exact (Decimal), so the figures never show float noise."""
    compared = [r for r in rows if r["agrees"] is not None]
    agreed = sum(r["agrees"] == 1 for r in compared)
    return {
        "generated_at": now.isoformat(),
        "totals": {
            "disputes": len(rows),
            "analyzed": sum(r["status"] != NOT_ANALYZED for r in rows),
            "executed": sum(r["status"] == "EXECUTED" for r in rows),
        },
        "by_status": dict(sorted(Counter(r["status"] for r in rows).items())),
        "by_reason": _breakdown(rows, "reason"),
        "by_product": _breakdown(rows, "product"),
        "money": {
            "currency": "USD",
            "disputed": _total(rows, "amount"),
            "refunded": _total(rows, "refunded"),
            "kept": _total(rows, "kept"),
            "open": _total(rows, "open"),
        },
        "agreement": {
            "compared": len(compared),
            "agreed": agreed,
            "rate": round(agreed / len(compared), 4) if compared else None,
            "guard_changes": sum(r["agrees"] == 0 for r in compared),
        },
    }


def deadlines(rows: list[dict], now: datetime) -> list[dict]:
    """Open seller response deadlines, most urgent first. Overdue entries have negative `hours_left`; ties sort by
    dispute id. Only WAITING_FOR_SELLER_RESPONSE counts: it is the one status in which PayPal waits on the seller and
    the due date is the seller's clock. In the other statuses (WAITING_FOR_BUYER_RESPONSE, UNDER_REVIEW, ...) no seller
    deadline is running, so those disputes are left out. A due date that cannot be parsed is left out too."""
    entries = []
    for r in rows:
        if r["paypal_status"] != "WAITING_FOR_SELLER_RESPONSE" or r["due"] is None:
            continue
        try:
            hours_left = round((parse_time(r["due"]) - now).total_seconds() / 3600, 1)
        except ValueError:  # an unreadable due date: leave that dispute out rather than fail the whole report
            continue
        entries.append({
            "dispute_id": r["dispute_id"], "reason": r["reason"], "amount": r["amount"], "status": r["status"],
            "paypal_status": r["paypal_status"], "due": r["due"], "hours_left": hours_left})
    return sorted(entries, key=lambda e: (e["hours_left"], e["dispute_id"]))


# ------------------------------------------------------------------ helpers
def _row(dispute: dict, proposal: dict | None, records: list[dict]) -> dict[str, Any]:
    status = proposal["status"] if proposal else NOT_ANALYZED
    outcome = _outcome(proposal)
    amount = _cents(dispute["dispute_amount"]["value"])
    refunded = _refunded(outcome, amount, proposal)
    executed = status == "EXECUTED"
    model, final = _model_resolution(records), _resolution(proposal)
    return {
        "dispute_id": dispute["dispute_id"],
        "reason": dispute["reason"],
        "paypal_status": dispute["status"],
        "created": dispute["create_time"],
        "due": dispute.get("seller_response_due_date"),
        "product": _product_name(_facts(proposal).get("item")),
        "amount": float(amount),
        "status": status,
        "outcome": outcome,
        "refunded": float(refunded),
        "kept": float(amount - refunded) if executed else 0.0,
        "open": 0.0 if executed else float(amount),
        "model_resolution": model,
        "final_resolution": final,
        "agrees": _agrees(model, final),
        "count": 1,
    }


def _outcome(proposal: dict | None) -> str:
    if proposal is None:
        return "not_analyzed"
    if proposal["status"] == "EXECUTED":
        return _EXECUTED_OUTCOME.get(_resolution(proposal), "kept")
    return _CLOSED_OUTCOME.get(proposal["status"], "awaiting_merchant")


def _refunded(outcome: str, amount: Decimal, proposal: dict | None) -> Decimal:
    if outcome == "refunded":
        return amount
    if outcome == "partially_refunded":
        return min(_offered(proposal), amount)
    return Decimal("0")


def _offered(proposal: dict | None) -> Decimal:
    """The amount of the proposal's `make_offer` action, wherever it sits in the action list. When no action carries
    one (an edited or older payload), nothing is counted as refunded: only an amount we can read is reported."""
    for action in (proposal or {}).get("actions") or []:
        if action.get("kind") != "make_offer":
            continue
        value = ((action.get("params") or {}).get("amount") or {}).get("value")
        if value is not None:
            return _cents(value)
    return Decimal("0")


def _model_resolution(records: list[dict]) -> str | None:
    """What the reasoner chose before the guard: the last `decide` record."""
    decisions = [r for r in records if r["step"] == "decide"]
    return decisions[-1]["detail"].get("resolution") if decisions else None


def _agrees(model: str | None, final: str | None) -> int | None:
    if model is None or final is None:
        return None
    return int(model == final)


def _resolution(proposal: dict | None) -> str | None:
    return ((proposal or {}).get("decision") or {}).get("resolution")


def _facts(proposal: dict | None) -> dict:
    return ((proposal or {}).get("case_summary") or {}).get("facts") or {}


def _product_name(item: str | None) -> str:
    """`facts.item` reads "<name> (<variant>)". The variant may hold brackets of its own ("Size (L)"), so the cut is at
    the bracket that matches the last one, not at the first " (". Without an item the product is Unknown."""
    if not item:
        return "Unknown"
    if item.endswith(")"):
        depth = 0
        for i in range(len(item) - 1, -1, -1):
            if item[i] == ")":
                depth += 1
            elif item[i] == "(":
                depth -= 1
                if depth == 0:
                    return item[:i].rstrip() or "Unknown"
    return item


def _breakdown(rows: list[dict], field: str) -> list[dict]:
    """Count and disputed amount per value of `field`: most disputes first, then by name."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row[field], []).append(row)
    out = [{field: value, "count": len(members), "amount": _total(members, "amount")}
           for value, members in groups.items()]
    return sorted(out, key=lambda g: (-g["count"], g[field]))


def _cents(value: Any) -> Decimal:
    """A money value (PayPal's string, or a float this module wrote) as exact cents."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _total(rows: list[dict], field: str) -> float:
    return float(sum((_cents(r[field]) for r in rows), Decimal("0")))
