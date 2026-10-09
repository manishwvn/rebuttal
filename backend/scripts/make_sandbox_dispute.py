"""Open a real sandbox dispute as the BUYER through the Disputes API, so the webhook fires on its own.

    cd backend && uv run python -u -m scripts.make_sandbox_dispute --case agent_wrong_size
    cd backend && uv run python -u -m scripts.make_sandbox_dispute --transaction-id <capture id> --amount 48.00

Needs a second sandbox BUSINESS account acting as the buyer (personal accounts cannot own a REST app): its keys are
PAYPAL_BUYER_CLIENT_ID / PAYPAL_BUYER_CLIENT_SECRET in backend/.env. Flow:
  1. merchant client creates an order (invoice `RB-<case>-<ts>`, same as make_test_order) and prints the approval link;
     approve it once as the buyer account (PayPal gives no API to approve an order), then the script captures it;
  2. the BUYER client creates the dispute (reason MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED) on the capture id;
  3. prints the dispute id; the registered webhook (CUSTOMER.DISPUTE.CREATED) then reaches the agent.
--transaction-id skips step 1 and disputes a capture you already have.

Like make_test_order this is a manual tool outside the approval gate: it enters permit_writes() to create test
fixtures and nothing else. It never prints a secret, and nothing in the agent graph imports it. Every run sends a new PayPal-Request-Id, so a
rerun is a second dispute attempt, not a replay of the first.
"""

from __future__ import annotations

import argparse
import os
import time
from urllib.parse import urlparse

import httpx

from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalClient, PayPalError, permit_writes
from rebuttal.scenarios import live_invoice_id, load_cases

DEFAULT_REASON = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"


def dispute_id_from(response: dict) -> str:
    """The id of a freshly created dispute: the `self` link (…/disputes/PP-D-…), else a body `dispute_id`."""
    for link in response.get("links") or []:
        if link.get("rel") == "self" and link.get("href"):
            return urlparse(link["href"]).path.rstrip("/").rsplit("/", 1)[-1]
    if response.get("dispute_id"):
        return response["dispute_id"]
    raise ValueError("PayPal's create-dispute response carried no dispute id")


def create_buyer_dispute(base_url: str, buyer_id: str, buyer_secret: str, capture_id: str, amount: str,
                         *, reason: str = DEFAULT_REASON, note: str | None = None, currency: str = "USD",
                         transport: httpx.BaseTransport | None = None) -> str:
    """Authenticate as the buyer account, open the dispute on the merchant's capture, return the dispute id."""
    if not (buyer_id and buyer_secret):
        raise ValueError("Set PAYPAL_BUYER_CLIENT_ID and PAYPAL_BUYER_CLIENT_SECRET in backend/.env")
    buyer = PayPalClient(base_url, buyer_id, buyer_secret, transport=transport)
    try:
        with permit_writes():
            resp = buyer.create_dispute(capture_id, reason, {"currency_code": currency, "value": amount}, note)
    finally:
        buyer.close()
    return dispute_id_from(resp)


def merchant_order_and_capture(pp: PayPalClient, case: dict, wait_minutes: int) -> tuple[str, str] | None:
    """Create the merchant's order, wait for the buyer's approval, capture. Returns (capture id, amount) or None."""
    item = case["item"]
    invoice = live_invoice_id(case["id"], int(time.time()))
    with permit_writes():
        order = pp.create_order(
            [{"amount": {"currency_code": "USD", "value": f"{item['price']:.2f}"}, "invoice_id": invoice,
              "custom_id": invoice, "description": f"{item['name']} ({item['variant']})"}],
            return_url="https://example.com/return", cancel_url="https://example.com/cancel")
    link = next((lk["href"] for lk in order.get("links", []) if lk["rel"] in ("payer-action", "approve")), None)
    if link is None:
        raise RuntimeError(f"PayPal returned no approval link for order {order['id']}")
    print(f"ORDER {order['id']}  invoice {invoice}\nOPEN AS THE SANDBOX BUYER AND APPROVE: {link}", flush=True)
    for _ in range(wait_minutes * 6):
        try:
            status = pp.get_order(order["id"]).get("status")
        except (PayPalError, httpx.HTTPError) as exc:  # a blip must not abort the wait
            print("poll failed, retrying:", type(exc).__name__, flush=True)
            status = None
        print("status", status, flush=True)
        if status == "APPROVED":
            break
        time.sleep(10)
    else:
        return None
    with permit_writes():
        captured = pp.capture_order(order["id"])
    capture_id = captured["purchase_units"][0]["payments"]["captures"][0]["id"]
    print("CAPTURED", captured.get("status"), capture_id, flush=True)
    return capture_id, f"{item['price']:.2f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", default="agent_wrong_size", help="labeled case id from evals/cases.json")
    ap.add_argument("--transaction-id", help="dispute this existing capture id instead of making an order")
    ap.add_argument("--amount", help="dispute amount (with --transaction-id); default is the case's item price")
    ap.add_argument("--reason", default=DEFAULT_REASON)
    ap.add_argument("--wait-minutes", type=int, default=15, help="how long to wait for the buyer to approve")
    args = ap.parse_args(argv)

    if args.amount and not args.transaction_id:
        ap.error("--amount only makes sense with --transaction-id")
    case = next((c for c in load_cases() if c["id"] == args.case), None)
    if case is None:
        print(f"Unknown case {args.case!r}. Known: {', '.join(c['id'] for c in load_cases())}")
        return 2
    s = load_settings()
    if s.mock:
        print("This needs the real PayPal sandbox: set REBUTTAL_MOCK=0 and the sandbox keys in backend/.env")
        return 2
    buyer_id = os.getenv("PAYPAL_BUYER_CLIENT_ID", "")
    buyer_secret = os.getenv("PAYPAL_BUYER_CLIENT_SECRET", "")
    if not (buyer_id and buyer_secret):
        print("Set PAYPAL_BUYER_CLIENT_ID and PAYPAL_BUYER_CLIENT_SECRET (second sandbox business account) in backend/.env")
        return 2

    if args.transaction_id:
        capture_id, amount = args.transaction_id, args.amount or f"{case['item']['price']:.2f}"
    else:
        pp = PayPalClient(s.base_url, s.client_id, s.client_secret)
        done = merchant_order_and_capture(pp, case, args.wait_minutes)
        if done is None:
            print("Timed out waiting for approval")
            return 1
        capture_id, amount = done
    note = f"Item not as described: {case['item']['name']} ({case['item']['variant']}) is not what I ordered."
    dispute_id = create_buyer_dispute(s.base_url, buyer_id, buyer_secret, capture_id, amount,
                                      reason=args.reason, note=note)
    print(f"DISPUTE {dispute_id} created on capture {capture_id}; the CUSTOMER.DISPUTE.CREATED webhook follows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
