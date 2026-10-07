"""Run the agent end to end on the demo disputes (mock sandbox) and export what happened.

    cd backend && python -m scripts.demo

Prints each decision and writes preview_data.json, which the product preview page renders.
"""

from __future__ import annotations

import json
from pathlib import Path

from rebuttal.app import DEMO_CASES
from rebuttal.runtime import Runtime

OUT = Path(__file__).resolve().parents[1] / "preview_data.json"
EVALS = Path(__file__).resolve().parents[1] / "evals" / "results.json"


def main() -> None:
    rt = Runtime(seed_cases=DEMO_CASES)
    cases = []
    for d in rt.client.list_disputes():
        p = rt.analyze(d["dispute_id"])
        before = dict(rt.mock.disputes[d["dispute_id"]])
        print(f"{d['dispute_id']}  {p.decision.resolution:<24} conf {p.decision.confidence:.2f}  "
              f"{p.actions[0].summary}")
        rt.approvals.approve(p.id)
        # Sandbox-side outcome so the preview can show the end state.
        if p.decision.resolution.startswith("OFFER_"):
            rt.client._request("POST", f"/v1/customer/disputes/{d['dispute_id']}/accept-offer", json={})
        elif p.decision.resolution.startswith("SUBMIT_"):
            rt.client.adjudicate(d["dispute_id"], "SELLER_FAVOR")
        after = rt.mock.disputes[d["dispute_id"]]
        cases.append({
            "dispute_id": d["dispute_id"],
            "created": before["create_time"],
            "due": before["seller_response_due_date"],
            "reason": before["reason"],
            "stage": before["dispute_life_cycle_stage"],
            "amount": float(before["dispute_amount"]["value"]),
            "proposal": p.to_dict(),
            "audit": rt.audit.for_dispute(d["dispute_id"]),
            "final_status": after["status"],
            "final_outcome": (after.get("dispute_outcome") or {}).get("outcome_code"),
        })
    data = {"mode": rt.mode, "now": rt.clock().isoformat(), "store": rt.store.name, "cases": cases,
            "evals": json.loads(EVALS.read_text()) if EVALS.exists() else None}
    OUT.write_text(json.dumps(data, indent=2, default=str))
    print(f"\nWrote {OUT.name} ({len(cases)} disputes, mode {rt.mode})")


if __name__ == "__main__":
    main()
