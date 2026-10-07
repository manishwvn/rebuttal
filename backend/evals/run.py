"""Run the agent on every labeled dispute and report accuracy.

    uv run python -m evals.run             # the model for the first provider key set, else the rules baseline
    uv run python -m evals.run --rules     # force the offline baseline
    uv run python -m evals.run --provider nvidia   # pin the model provider: groq | nvidia | anthropic
    uv run python -m evals.run --langfuse  # also record the run as a Langfuse experiment (needs the Langfuse keys)

A model run is strict: if the model hits a rate or quota limit (or any call fails) the run stops and is marked
INVALID. Nothing falls back to the rules, and no results files are written for an invalid run.

Each case runs in a fresh mock sandbox with an in-memory checkpointer. Writes evals/results.json and
evals/RESULTS.md. Tracing is off unless --langfuse is given, so a plain run never sends anything anywhere.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from rebuttal.agent.llm import PROVIDERS, ModelCallFailed
from rebuttal.config import Settings, load_settings
from rebuttal.runtime import Runtime
from rebuttal.scenarios import load_cases

HERE = Path(__file__).resolve().parent


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def eval_settings() -> Settings:
    settings = load_settings()
    if not settings.mock:
        settings = type(settings)(**{**settings.__dict__, "mock": True})  # evals always use the mock
    # Evals never touch the online database: every case is dispute PP-D-2000 in a throwaway sandbox.
    return type(settings)(**{**settings.__dict__, "database_url": None, "checkpoint_target": None})


class InvalidRun(RuntimeError):
    """The model failed or was rate limited mid-run, so the accuracy would not be the model's."""


def run_case(case: dict, settings: Settings, *, force_rules: bool, tracing: bool = False,
             provider: str | None = None) -> tuple[dict, int, str]:
    """Analyse one labeled case through the graph, up to the approval gate. Returns (row, tokens used, mode)."""
    rt = Runtime(settings=settings, seed_cases=[case["id"]], force_rules=force_rules, tracing=tracing,
                 checkpointer=InMemorySaver(), provider=provider, strict=True)
    dispute_id = rt.client.list_disputes()[0]["dispute_id"]
    # Every eval case is dispute PP-D-2000 in its own sandbox, so tag traces with the case id instead.
    trace = {"tags": ["eval", f"case:{case['id']}"],
             "metadata": {"case_id": case["id"], "hard": bool(case.get("hard")),
                          "langfuse_session_id": f"eval:{case['id']}"}}
    p = rt.analyze(dispute_id, config_extra=trace)
    row = {
        "id": case["id"], "title": case["title"], "hard": case.get("hard", False),
        "expected": case["expected"], "got": p.decision.resolution,
        "correct": p.decision.resolution == case["expected"],
        "confidence": p.decision.confidence, "source": p.decision.source,
        "writes_before_approval": len(rt.mock.write_calls()),
        "buyer_wants": p.decision.buyer_wants, "reasoning": p.decision.reasoning,
        "guard_notes": p.decision.guard_notes,
    }
    return row, getattr(rt.reasoner, "tokens_used", 0), rt.mode


def run(force_rules: bool, pause: float = 0.0, only: set[str] | None = None, langfuse: bool = False,
        provider: str | None = None) -> dict:
    settings = eval_settings()
    cases = [c for c in load_cases() if not only or c["id"] in only]
    rows: list[dict] = []
    tokens_total, mode, experiment = 0, "", None
    invalid: list[str] = []  # why the run is invalid (first failure); later cases are skipped

    def run_one(case: dict) -> dict:
        nonlocal tokens_total, mode
        if invalid:
            return {"skipped": "run already invalid"}
        try:
            row, tokens, mode = run_case(case, settings, force_rules=force_rules, tracing=langfuse, provider=provider)
        except Exception as exc:
            cause = exc if isinstance(exc, ModelCallFailed) else exc.__cause__
            if not isinstance(cause, ModelCallFailed):
                raise
            kind = "rate or quota limit" if cause.rate_limited else "model call failure"
            invalid.append(f"{kind} on case {case['id']}: {cause}")
            print(f"INVALID RUN: {invalid[0]}", flush=True)
            return {"invalid": invalid[0]}
        tokens_total += tokens
        rows.append(row)
        print(f"[{len(rows)}/{len(cases)}] {case['id']}: {row['got']} ({row['source']})"
              f"{'' if row['correct'] else '  <- MISS'}", flush=True)
        return {"resolution": row["got"], "confidence": row["confidence"], "source": row["source"],
                "buyer_wants": row["buyer_wants"], "reasoning": row["reasoning"], "guard_notes": row["guard_notes"]}

    if langfuse:
        from rebuttal import tracing

        if not tracing.langfuse_configured():
            raise SystemExit("--langfuse needs LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (and LANGFUSE_BASE_URL) "
                             "in backend/.env, and REBUTTAL_TRACING must not be 0.")
        if only:
            raise SystemExit("--langfuse runs the whole dataset; drop --only.")
        by_id = {c["id"]: c for c in cases}
        probe = Runtime(settings=settings, seed_cases=[], force_rules=force_rules, tracing=False, provider=provider)
        name = f"{probe.reasoner.name}-{probe.reasoner.model_name.split('/')[-1]}-" \
               f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
        tracing.upload_dataset(cases)
        result = tracing.run_experiment(
            name=name, task=lambda case: run_one(by_id[case["id"]]),
            description="evals/run.py --langfuse: every labeled dispute analysed up to the approval gate",
            metadata={"mode": probe.mode, "cases": len(cases)})
        tracing.flush()
        experiment = {"name": name, "dataset": tracing.DATASET_NAME,
                      "url": getattr(result, "dataset_run_url", None)}
    else:
        for n, case in enumerate(cases):
            if n and pause:
                time.sleep(pause)  # free-tier API rate limits
            run_one(case)
            if invalid:
                break
    if invalid:
        if langfuse:
            tracing.flush()
        raise InvalidRun(invalid[0] + (f" (after {len(rows)} of {len(cases)} cases; "
                                       "the Langfuse experiment, if any, is invalid: ignore or delete it)" if langfuse else
                                       f" (after {len(rows)} of {len(cases)} cases)"))

    def acc(rs):
        return round(sum(r["correct"] for r in rs) / len(rs), 3) if rs else None

    hard = [r for r in rows if r["hard"]]
    summary = {
        "mode": mode, "cases": len(rows), "accuracy": acc(rows),
        "standard_accuracy": acc([r for r in rows if not r["hard"]]),
        "hard_accuracy": acc(hard), "hard_cases": len(hard),
        "approval_gate_violations": sum(r["writes_before_approval"] for r in rows),
        "rows": rows, "tokens_used": tokens_total, "langfuse": experiment,
    }
    (HERE / "results.json").write_text(json.dumps(summary, indent=2))
    lines = [f"# Eval results ({mode})", "",
             f"- Overall: {pct(summary['accuracy'])} of {len(rows)} labeled disputes",
             f"- Standard cases: {pct(summary['standard_accuracy'])}",
             f"- Hard cases (meaning, not keywords): {pct(summary['hard_accuracy'])} of {len(hard)}",
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
    ap.add_argument("--langfuse", action="store_true",
                    help="trace every case and record the run as a Langfuse experiment (needs the Langfuse keys)")
    ap.add_argument("--provider", choices=PROVIDERS, help="pin the model provider (needs its key in backend/.env)")
    args = ap.parse_args()
    try:
        s = run(force_rules=args.rules, pause=args.pause, only=set(args.only.split(",")) if args.only else None,
                langfuse=args.langfuse, provider=args.provider)
    except InvalidRun as exc:
        raise SystemExit(f"EVAL INVALID, no results written: {exc}")
    print(f"{s['mode']}: {pct(s['accuracy'])} overall, {pct(s['standard_accuracy'])} standard, "
          f"{pct(s['hard_accuracy'])} hard ({s['hard_cases']}), gate violations {s['approval_gate_violations']}")
    if s["tokens_used"]:
        print(f"tokens used: {s['tokens_used']:,}")
    if s["langfuse"]:
        print(f"Langfuse experiment: {s['langfuse']['name']} (dataset {s['langfuse']['dataset']})"
              + (f"\n  {s['langfuse']['url']}" if s["langfuse"]["url"] else ""))
    for r in s["rows"]:
        if not r["correct"]:
            print(f"  MISS {r['id']}: expected {r['expected']}, got {r['got']} ({r['source']}, conf {r['confidence']:.2f})")
            print(f"       wants: {r['buyer_wants']}")
            for line in r["reasoning"]:
                print(f"       - {line}")
            for note in r["guard_notes"]:
                print(f"       ! {note}")
