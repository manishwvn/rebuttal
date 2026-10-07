"""Fresh sandbox order -> wait for you to file a dispute -> make_offer first, no message beforehand.

    cd backend && python -u -m scripts.spike_fresh

Non-interactive: prints the buyer approval link, polls until the order is approved, captures it, adds
tracking, then polls for a dispute on that capture. As soon as the dispute is WAITING_FOR_SELLER_RESPONSE
and PayPal offers make_offer, it sends the offer and nothing else (no message, no adjudicate).
Sandbox only. Results go to spike_fresh_report.json.
"""

from __future__ import annotations

import json
import time

from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalClient, permit_writes
from scripts.spike_retry import SELLER_STATUS, dispute_summary
from scripts.spike_sandbox import TRACKING_NUMBER, seller_action_steps, step

APPROVAL_WAIT_S = 15 * 60
DISPUTE_WAIT_S = 30 * 60
POLL_S = 20


def main() -> int:
    s = load_settings()
    pp = PayPalClient(s.base_url, s.client_id, s.client_secret)
    invoice = f"JO-SPIKE-{int(time.time())}"
    report: list[dict] = []
    ctx: dict = {}

    def create():
        order = pp.create_order(
            [{"amount": {"currency_code": "USD", "value": "48.00"}, "invoice_id": invoice, "custom_id": invoice,
              "description": "Linen shirt (Navy / Size L)"}],
            return_url="https://example.com/return", cancel_url="https://example.com/cancel")
        ctx["order_id"] = order["id"]
        link = next(l["href"] for l in order["links"] if l["rel"] in ("payer-action", "approve"))
        print(f"\n   APPROVE AS SANDBOX BUYER: {link}", flush=True)
        return {"order_id": order["id"], "invoice": invoice, "approval_link": link}

    step("create_order", create, report)
    if "order_id" not in ctx:
        return 1

    def approved():
        deadline = time.time() + APPROVAL_WAIT_S
        while time.time() < deadline:
            status = pp.get_order(ctx["order_id"]).get("status")
            if status == "APPROVED":
                return {"status": status}
            print(f"   order {status}; waiting for approval...", flush=True)
            time.sleep(POLL_S)
        raise TimeoutError("Order not approved within 15 minutes")

    step("wait_for_approval", approved, report)

    def capture():
        cap = pp.capture_order(ctx["order_id"])
        ctx["capture_id"] = cap["purchase_units"][0]["payments"]["captures"][0]["id"]
        return {"capture_id": ctx["capture_id"], "status": cap["status"]}

    step("capture", capture, report)
    if "capture_id" not in ctx:
        return 1
    step("add_tracking", lambda: pp.add_order_tracking(ctx["order_id"], ctx["capture_id"], TRACKING_NUMBER, "USPS")
         and {"tracking_number": TRACKING_NUMBER}, report)
    print("\n   NOW FILE THE DISPUTE as the sandbox buyer for this $48.00 payment "
          "(item not as described). Waiting...", flush=True)

    def wait_for_seller_turn():
        deadline = time.time() + DISPUTE_WAIT_S
        last = None
        while time.time() < deadline:
            for d in pp.list_disputes():
                full = pp.get_dispute(d["dispute_id"])
                if not any(t.get("seller_transaction_id") == ctx["capture_id"]
                           for t in full.get("disputed_transactions", [])):
                    continue
                ctx["dispute_id"] = d["dispute_id"]
                summ = dispute_summary(full)
                state = (summ["stage"], summ["status"], tuple(summ["allowed_actions"]))
                if state != last:
                    print(f"   {time.strftime('%H:%M:%S')} {json.dumps(summ)}", flush=True)
                    last = state
                if summ["status"] == SELLER_STATUS and "make_offer" in summ["allowed_actions"]:
                    return summ
            time.sleep(POLL_S)
        raise TimeoutError("Dispute never reached WAITING_FOR_SELLER_RESPONSE with make_offer allowed")

    step("wait_for_seller_turn", wait_for_seller_turn, report)
    if "dispute_id" in ctx and report[-1]["ok"]:
        seller_action_steps(pp, ctx["dispute_id"], None, report, only={"make_offer"})
        step("state_after_offer", lambda: dispute_summary(pp.get_dispute(ctx["dispute_id"])), report)

    json.dump({"invoice": invoice, **ctx, "steps": report}, open("spike_fresh_report.json", "w"),
              indent=2, default=str)
    failed = [r["step"] for r in report if not r["ok"]]
    print(f"\n{'=' * 60}\nFailed steps: {failed or 'none'}\nReport: spike_fresh_report.json", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    with permit_writes():  # manual sandbox tool: it answers a real sandbox dispute
        raise SystemExit(main())
