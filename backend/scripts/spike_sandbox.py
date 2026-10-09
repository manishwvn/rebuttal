"""Week-1 go/no-go spike against the REAL PayPal sandbox.

    cd backend && python -m scripts.spike_sandbox

Needs PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET in backend/.env (sandbox app with
Disputes enabled) and your sandbox buyer login. Two steps are done by hand in
the browser (approving the payment, opening the dispute); everything else is
API. Each step is PASS/FAIL; results go to spike_report.json.
"""

from __future__ import annotations

import json
import time
import traceback
from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.memory import InMemorySaver

from rebuttal.agent.graph import DisputeAgent
from rebuttal.agent.reasoner import RuleReasoner
from rebuttal.audit import AuditLog
from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalClient, PayPalError, permit_writes
from rebuttal.store import MerchantOrder, MerchantStore, Shipment

REPORT: list[dict] = []
CRITICAL = {"token", "create_order", "capture", "dispute_visible", "dispute_fields",
            "send_message", "make_offer", "provide_evidence", "adjudicate"}


TRACKING_NUMBER = "9400111899223344556677"


def step(name: str, fn, report: list[dict] | None = None):
    report = REPORT if report is None else report
    print(f"\n== {name}")
    try:
        out = fn()
        report.append({"step": name, "ok": True, "detail": out})
        print(f"   PASS {json.dumps(out, default=str)[:300] if out else ''}")
        return out
    except Exception as exc:  # report and continue
        report.append({"step": name, "ok": False, "error": repr(exc)})
        print(f"   FAIL {exc!r}")
        traceback.print_exc(limit=1)
        return None


def skip_if_forbidden(fn):
    """Non-critical lookups: a 403 means the sandbox app lacks that permission, not that the code is wrong."""
    def run():
        try:
            return fn()
        except PayPalError as exc:
            if exc.status != 403:
                raise
            return {"skipped": "403 NOT_AUTHORIZED (sandbox app lacks access)"}
    return run


def dry_run(pp: PayPalClient, *, invoice: str, capture_id: str, dispute_id: str, order_id: str | None = None):
    """Run the agent against a real dispute with a stand-in merchant order. Reads only."""
    store = MerchantStore()
    store.add(MerchantOrder(
        invoice_id=invoice, capture_id=capture_id, order_id=order_id,
        created=datetime.now(UTC) - timedelta(hours=1),
        buyer_name="Sandbox Buyer", buyer_email="buyer@example.com",
        items=[{"sku": "LIN-SHIRT", "name": "Linen shirt", "variant": "Navy / Size L", "price": 48.0}],
        ship_to="(sandbox)",
        shipment=Shipment("USPS", TRACKING_NUMBER, "DELIVERED", "(sandbox)", datetime.now(UTC)),
        intent={"intent_id": "INT-SPIKE", "agent": "Atlas (buyer's AI shopping assistant)",
                "user_instruction": "Get my brother the navy linen shirt in medium, under $60.",
                "constraints": {"variant": "Size M", "max_price": 60},
                "submitted_item": {"sku": "LIN-SHIRT", "variant": "Navy / Size L", "price": 48.0},
                "recorded_at": datetime.now(UTC).isoformat()}))
    agent = DisputeAgent(client=pp, store=store, reasoner=RuleReasoner(), audit=AuditLog(),
                         clock=lambda: datetime.now(UTC), checkpointer=InMemorySaver())
    return agent.analyze(dispute_id)  # stops at the approval gate; nothing is sent to PayPal


SELLER_STEPS = ("send_message", "make_offer", "require_evidence", "provide_evidence", "adjudicate", "final_state")


def seller_action_steps(pp: PayPalClient, dispute_id: str, proposal, report: list[dict] | None = None,
                        only: set[str] | None = None) -> None:
    """The steps that change the dispute. Shared by the full spike and scripts.spike_retry.

    `only` limits the run to those SELLER_STEPS names (default: all)."""
    run = lambda name, fn: (None if only and name.split(" ")[0] not in only  # noqa: E731
                            else step(name, fn, report))
    run("send_message", lambda: pp.send_message(dispute_id, "Thanks for reaching out - checking your order now."))
    run("make_offer", lambda: pp.make_offer(dispute_id, note="Free exchange for the right size.",
                                            offer_type="REPLACEMENT_WITHOUT_REFUND"))
    run("require_evidence (sandbox)", lambda: pp.require_evidence(dispute_id, "SELLER_EVIDENCE"))

    def evidence():
        pdf = proposal.evidence_pdf if proposal and proposal.evidence_pdf else b"%PDF-1.4\n%placeholder\n"
        evid = [{"evidence_type": "PROOF_OF_FULFILLMENT",
                 "evidence_info": {"tracking_info": [{"carrier_name": "USPS", "tracking_number": TRACKING_NUMBER}]},
                 "notes": "Order shipped as submitted by the buyer's assistant. Instruction record attached."}]
        return pp.provide_evidence(dispute_id, evid, [(f"evidence-{dispute_id}.pdf", pdf, "application/pdf")])

    run("provide_evidence", evidence)
    run("adjudicate (sandbox)", lambda: pp.adjudicate(dispute_id, "SELLER_FAVOR"))
    run("final_state", lambda: {k: pp.get_dispute(dispute_id).get(k) for k in ("status", "dispute_outcome")})


def main() -> None:
    s = load_settings()
    if not (s.client_id and s.client_secret):
        raise SystemExit("Add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (sandbox) to backend/.env first.")
    pp = PayPalClient(s.base_url, s.client_id, s.client_secret)
    invoice = f"JO-SPIKE-{int(time.time())}"
    ctx: dict = {}

    step("token", lambda: {"ok": bool(pp._access_token())})

    def create():
        order = pp.create_order(
            [{"amount": {"currency_code": "USD", "value": "48.00"}, "invoice_id": invoice, "custom_id": invoice,
              "description": "Linen shirt (Navy / Size L)"}],
            return_url="https://example.com/return", cancel_url="https://example.com/cancel")
        ctx["order_id"] = order["id"]
        link = next(lk["href"] for lk in order["links"] if lk["rel"] in ("payer-action", "approve"))
        print(f"\n   Open this link, log in as your SANDBOX BUYER, and approve the payment:\n   {link}")
        input("   Press Enter after approving... ")
        return {"order_id": order["id"]}

    step("create_order", create)

    def capture():
        cap = pp.capture_order(ctx["order_id"])
        ctx["capture_id"] = cap["purchase_units"][0]["payments"]["captures"][0]["id"]
        return {"capture_id": ctx["capture_id"], "status": cap["status"]}

    step("capture", capture)
    step("add_tracking", lambda: pp.add_order_tracking(ctx["order_id"], ctx["capture_id"],
                                                       TRACKING_NUMBER, "USPS"))

    print("\n   Now open https://www.sandbox.paypal.com as the SANDBOX BUYER -> Resolution Center ->"
          "\n   report a problem with this payment ($48.00, 'item not as described'), message: "
          "'I asked for a medium. This is a large.'")
    input("   Press Enter once the dispute is filed... ")

    def find_dispute():
        deadline = time.time() + 300
        while time.time() < deadline:
            for d in pp.list_disputes():
                full = pp.get_dispute(d["dispute_id"])
                txns = full.get("disputed_transactions", [])
                if any(t.get("seller_transaction_id") == ctx["capture_id"] for t in txns):
                    ctx["dispute_id"], ctx["dispute"] = d["dispute_id"], full
                    return {"dispute_id": d["dispute_id"], "stage": full.get("dispute_life_cycle_stage"),
                            "status": full.get("status")}
            print("   ...not visible yet, retrying in 20s")
            time.sleep(20)
        raise TimeoutError("Dispute not visible to merchant after 5 minutes")

    step("dispute_visible", find_dispute)

    def fields():
        d = ctx["dispute"]
        t = d["disputed_transactions"][0]
        needed = {"invoice_number_or_custom": t.get("invoice_number") or t.get("custom"),
                  "buyer_message": next((m["content"] for m in d.get("messages", [])), None),
                  "stage": d.get("dispute_life_cycle_stage")}
        missing = [k for k, v in needed.items() if not v]
        if missing:
            raise ValueError(f"Missing fields the agent relies on: {missing}")
        # Optional: the sandbox omits it on some disputes (INQUIRY / UNDER_REVIEW); the agent copes.
        return {**needed, "seller_response_due_date": d.get("seller_response_due_date")}

    step("dispute_fields", fields)

    def agent_dry_run():
        p = dry_run(pp, invoice=invoice, capture_id=ctx["capture_id"], dispute_id=ctx["dispute_id"],
                    order_id=ctx["order_id"])
        ctx["proposal"] = p
        return {"resolution": p.decision.resolution, "actions": [a.summary for a in p.actions],
                "tool_calls": p.case_summary["tool_calls"]}

    step("agent_dry_run (reads only)", agent_dry_run)
    seller_action_steps(pp, ctx["dispute_id"], ctx.get("proposal"))

    now = datetime.now(UTC)
    step("trackers_lookup (non-critical)", lambda: pp.get_order_trackers(ctx["order_id"], ctx["capture_id"]))
    step("transaction_search (non-critical)", skip_if_forbidden(
        lambda: len(pp.search_transactions((now - timedelta(days=2)).isoformat(), now.isoformat()))))
    step("webhook_events (needs a webhook on the app)",
         lambda: [e["event_type"] for e in pp.list_webhook_events() if "DISPUTE" in e["event_type"]][:10])

    failed = [r["step"] for r in REPORT if not r["ok"]]
    critical_failed = [f for f in failed if f.split(" ")[0] in CRITICAL]
    verdict = "GO" if not critical_failed else "NO-GO (see failed critical steps)"
    json.dump({"verdict": verdict, "invoice": invoice, "steps": REPORT},
              open("spike_report.json", "w"), indent=2, default=str)
    print(f"\n{'=' * 60}\nVERDICT: {verdict}\nFailed steps: {failed or 'none'}\nReport: spike_report.json")


if __name__ == "__main__":
    with permit_writes():  # manual sandbox tool: it creates and answers real sandbox disputes
        main()
