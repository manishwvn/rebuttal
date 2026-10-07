"""Re-check one real sandbox dispute and retry only the seller-action steps.

    cd backend && python -m scripts.spike_retry PP-R-AFT-10190433
    cd backend && python -m scripts.spike_retry PP-R-AFT-10190433 --status-only

Prints the dispute's stage, status and the actions PayPal currently offers (the
`links` rels on the dispute), then runs send_message, make_offer,
require_evidence, provide_evidence, adjudicate and final_state. No order or
payment is created. Sandbox only. Results go to spike_retry_report.json.

adjudicate resolves the dispute. Use --only send_message,make_offer to leave it open, or
--status-only to look without touching.
"""

from __future__ import annotations

import argparse
import json

from rebuttal.config import load_settings
from rebuttal.paypal.client import PayPalClient
from scripts.spike_sandbox import SELLER_STEPS, dry_run, seller_action_steps

SELLER_STATUS = "WAITING_FOR_SELLER_RESPONSE"
# The API names link rels with underscores (send_message); endpoints use hyphens.
ACTION_RELS = {"send_message", "make_offer", "provide_evidence", "accept_claim", "escalate",
               "require_evidence", "adjudicate", "accept_offer"}


def dispute_summary(dispute: dict) -> dict:
    return {
        "dispute_id": dispute.get("dispute_id"),
        "stage": dispute.get("dispute_life_cycle_stage"),
        "status": dispute.get("status"),
        "reason": dispute.get("reason"),
        "seller_response_due_date": dispute.get("seller_response_due_date"),
        "allowed_actions": sorted({l.get("rel") for l in dispute.get("links", [])} & ACTION_RELS),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dispute_id")
    ap.add_argument("--status-only", action="store_true", help="show status and allowed actions, change nothing")
    ap.add_argument("--only", help=f"comma-separated steps to run, from: {', '.join(SELLER_STEPS)} (default: all)")
    args = ap.parse_args(argv)
    only = {n.strip() for n in args.only.split(",")} if args.only else None
    if only and only - set(SELLER_STEPS):
        ap.error(f"unknown step(s): {', '.join(sorted(only - set(SELLER_STEPS)))}")

    s = load_settings()
    if not (s.client_id and s.client_secret):
        raise SystemExit("Add PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET (sandbox) to backend/.env first.")
    pp = PayPalClient(s.base_url, s.client_id, s.client_secret)

    dispute = pp.get_dispute(args.dispute_id)
    summary = dispute_summary(dispute)
    print(json.dumps(summary, indent=2))
    if args.status_only:
        return 0
    if summary["status"] != SELLER_STATUS:
        print(f"\nNote: status is {summary['status']}, not {SELLER_STATUS}; PayPal will probably reject "
              "seller actions. Retrying anyway.")

    txn = (dispute.get("disputed_transactions") or [{}])[0]
    capture_id = txn.get("seller_transaction_id") or ""
    invoice = txn.get("invoice_number") or txn.get("custom") or "JO-SPIKE-RETRY"
    proposal = None
    if not only or "provide_evidence" in only:
        try:  # only for the evidence PDF; reads only
            proposal = dry_run(pp, invoice=invoice, capture_id=capture_id, dispute_id=args.dispute_id)
        except Exception as exc:  # noqa: BLE001 - the retry should still run with a placeholder PDF
            print(f"\n(agent dry run skipped, using placeholder PDF: {exc!r})")

    report: list[dict] = []
    seller_action_steps(pp, args.dispute_id, proposal, report, only)

    failed = [r["step"] for r in report if not r["ok"]]
    after = dispute_summary(pp.get_dispute(args.dispute_id))
    with open("spike_retry_report.json", "w") as fh:
        json.dump({"before": summary, "after": after, "steps": report}, fh, indent=2, default=str)
    print(f"\n{'=' * 60}\nBefore: {summary['stage']} / {summary['status']}"
          f"\nAfter:  {after['stage']} / {after['status']}"
          f"\nFailed steps: {failed or 'none'}\nReport: spike_retry_report.json")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
