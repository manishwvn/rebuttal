"""Run the agent on every labeled dispute and report accuracy.

    python -m evals.run            # Claude if ANTHROPIC_API_KEY is set, else rules baseline
    python -m evals.run --rules    # force the offline baseline

Each case runs in a fresh mock sandbox. Writes evals/results.json and evals/RESULTS.md.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rebuttal.config import load_settings
from rebuttal.runtime import Runtime
from rebuttal.scenarios import load_cases

HERE = Path(__file__).resolve().parent


def run(force_rules: bool, pause: float = 0.0, only: set[str] | None = None) -> dict:
    settings = load_settings()
    if not settings.mock:
        settings = type(settings)(**{**settings.__dict__, "mock": True})  # evals always use the mock
    rows, tokens_total = [], 0
    cases = [c for c in load_cases() if not only or c["id"] in only]
    for n, case in enumerate(cases):
        if n and pause:
            time.sleep(pause)  # free-tier API rate limits
        rt = Runtime(settings=settings, seed_cases=[case["id"]], force_rules=force_rules)
        dispute_id = rt.client.list_disputes()[0]["dispute_id"]
        p = rt.analyze(dispute_id)
        writes_before_approval = len(rt.mock.write_calls())
        rows.append({
            "id": case["id"], "title": case["title"], "hard": case.get("hard", False),
            "expected": case["expected"], "got": p.decision.resolution,
            "correct": p.decision.resolution == case["expected"],
            "confidence": p.decision.confidence, "source": p.decision.source,
            "writes_before_approval": writes_before_approval,
            "buyer_wants": p.decision.buyer_wants, "reasoning": p.decision.reasoning,
            "guard_notes": p.decision.guard_notes,
        })
        mode = rt.mode
        tokens_total += getattr(rt.reasoner, "tokens_used", 0)
        print(f"[{n + 1}/{len(cases)}] {case['id']}: {p.decision.resolution} ({p.decision.source})"
              f"{'' if p.decision.resolution == case['expected'] else '  <- MISS'}", flush=True)

    def acc(rs):
        return round(sum(r["correct"] for r in rs) / len(rs), 3) if rs else None

    hard = [r for r in rows if r["hard"]]
    summary = {
        "mode": mode, "cases": len(rows), "accuracy": acc(rows),
        "standard_accuracy": acc([r for r in rows if not r["hard"]]),
        "hard_accuracy": acc(hard), "hard_cases": len(hard),
        "approval_gate_violations": sum(r["writes_before_approval"] for r in rows),
        "rows": rows, "tokens_used": tokens_total,
    }
    (HERE / "results.json").write_text(json.dumps(summary, indent=2))
    lines = [f"# Eval results ({mode})", "",
             f"- Overall: {summary['accuracy']:.0%} of {len(rows)} labeled disputes",
             f"- Standard cases: {summary['standard_accuracy']:.0%}",
             f"- Hard cases (meaning, not keywords): {summary['hard_accuracy']:.0%} of {len(hard)}",
             f"- PayPal writes before merchant approval: {summary['approval_gate_violations']}", "",
             "| Case | Expected | Got | OK |", "|---|---|---|---|"]
    lines += [f"| {r['id']}{' (hard)' if r['hard'] else ''} | {r['expected']} | {r['got']} | "
              f"{'yes' if r['correct'] else 'NO'} |" for r in rows]
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true", help="force the offline rules baseline")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to wait between cases (rate limits)")
    ap.add_argument("--only", help="comma-separated case ids (results files are overwritten with just these)")
    args = ap.parse_args()
    s = run(force_rules=args.rules, pause=args.pause, only=set(args.only.split(",")) if args.only else None)
    print(f"{s['mode']}: {s['accuracy']:.0%} overall, {s['standard_accuracy']:.0%} standard, "
          f"{s['hard_accuracy']:.0%} hard ({s['hard_cases']}), gate violations {s['approval_gate_violations']}")
    if s["tokens_used"]:
        print(f"tokens used: {s['tokens_used']:,}")
    for r in s["rows"]:
        if not r["correct"]:
            print(f"  MISS {r['id']}: expected {r['expected']}, got {r['got']} ({r['source']}, conf {r['confidence']:.2f})")
            print(f"       wants: {r['buyer_wants']}")
            for line in r["reasoning"]:
                print(f"       - {line}")
            for note in r["guard_notes"]:
                print(f"       ! {note}")
