"""Create a sandbox order that maps to a seeded merchant record, so a dispute on it has real facts to gather.

    cd backend && uv run python -u -m scripts.make_test_order --case agent_wrong_size

What it does (PayPal sandbox only, never touches a dispute):
  1. creates a $48-style order from the labeled case in evals/cases.json (its item, amount and description), with the
     invoice id `RB-<case>-<timestamp>`; the store resolves that pattern to the case's merchant record, so
     `order_found` is true and, for agent_wrong_size, the buyer's AI-assistant instruction ("medium") is known;
  2. prints the buyer approval link and waits for you to approve it as the sandbox buyer;
  3. captures the payment;
  4. adds the case's tracking number to the order (skip with --no-tracking), so tracking facts are real too.

Then file the dispute as the buyer in the sandbox Resolution Center ("item not as described"); the webhook does the
rest. Like the spike scripts this is a manual tool outside the approval gate: it enters permit_writes() to create test
fixtures and nothing else.
"""

from __future__ import annotations

import argparse
import time

from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalClient, permit_writes
from rebuttal.scenarios import live_invoice_id, load_cases


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", default="agent_wrong_size", help="labeled case id from evals/cases.json")
    ap.add_argument("--no-tracking", action="store_true", help="do not add the case's tracking number to the order")
    ap.add_argument("--wait-minutes", type=int, default=15, help="how long to wait for the buyer to approve")
    args = ap.parse_args(argv)

    case = next((c for c in load_cases() if c["id"] == args.case), None)
    if case is None:
        print(f"Unknown case {args.case!r}. Known: {', '.join(c['id'] for c in load_cases())}")
        return 2
    s = load_settings()
    if s.mock:
        print("This needs the real PayPal sandbox: set REBUTTAL_MOCK=0 and the sandbox keys in backend/.env")
        return 2
    pp = PayPalClient(s.base_url, s.client_id, s.client_secret)
    item = case["item"]
    invoice = live_invoice_id(case["id"], int(time.time()))
    with permit_writes():
        order = pp.create_order(
            [{"amount": {"currency_code": "USD", "value": f"{item['price']:.2f}"}, "invoice_id": invoice,
              "custom_id": invoice, "description": f"{item['name']} ({item['variant']})"}],
            return_url="https://example.com/return", cancel_url="https://example.com/cancel")
    link = next(l["href"] for l in order["links"] if l["rel"] in ("payer-action", "approve"))
    print(f"ORDER {order['id']}  invoice {invoice}\nOPEN AS SANDBOX BUYER AND APPROVE: {link}", flush=True)

    for _ in range(args.wait_minutes * 6):
        status = pp.get_order(order["id"]).get("status")
        print("status", status, flush=True)
        if status == "APPROVED":
            break
        time.sleep(10)
    else:
        print("Timed out waiting for approval")
        return 1

    with permit_writes():
        captured = pp.capture_order(order["id"])
        capture_id = captured["purchase_units"][0]["payments"]["captures"][0]["id"]
        print("CAPTURED", captured.get("status"), capture_id, flush=True)
        if case.get("shipment") and not args.no_tracking:
            ship = case["shipment"]
            pp.add_order_tracking(order["id"], capture_id, ship["number"], ship["carrier"])
            print(f"TRACKING added: {ship['carrier']} {ship['number']}", flush=True)
    print(f"\nNext: file the dispute as the buyer for this {item['price']:.2f} payment (invoice {invoice}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
