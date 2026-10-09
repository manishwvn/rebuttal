"""Run the agent on every labeled dispute and report accuracy.

    uv run python -m evals.run             # the model for the first provider key set, else the rules baseline
    uv run python -m evals.run --rules     # force the offline baseline
    uv run python -m evals.run --provider nvidia   # pin the model provider: groq | nvidia | anthropic
    uv run python -m evals.run --langfuse  # also record the run as a Langfuse experiment (needs the Langfuse keys)

A model run is strict: if the model hits a rate or quota limit (or any call fails) the run stops and is marked
INVALID. Nothing falls back to the rules, and no results files are written for an invalid run.

Each case runs in a fresh mock sandbox with an in-memory checkpointer. Saves the run to evals/results/ and
refreshes evals/RESULTS.md. Tracing is off unless --langfuse is given, so a plain run never sends anything anywhere.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from rebuttal.agent.llm import PROVIDERS, ModelCallFailed
from rebuttal.config import Settings, load_settings
from rebuttal.runtime import Runtime
from rebuttal.scenarios import load_cases, seed_case

HERE = Path(__file__).resolve().parent
# Labeled sets. The held-out ones were written independently of the guard and the facts code and are never used for
# tuning: they are only run and reported.
SETS = {"main": HERE / "cases.json", "holdout": HERE / "holdout.json", "holdout2": HERE / "holdout2.json"}
DATASETS = {"main": None, "holdout": "rebuttal-disputes-holdout",
            "holdout2": "rebuttal-disputes-holdout2"}  # Langfuse dataset names (None = the default)


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def eval_settings() -> Settings:
    settings = load_settings()
    if not settings.mock:
        settings = type(settings)(**{**settings.__dict__, "mock": True})  # evals always use the mock
    # Evals never touch the online database: every case is dispute PP-D-2000 in a throwaway sandbox.
    return type(settings)(**{**settings.__dict__, "database_url": None, "checkpoint_target": None})



# Cases whose label is a judgment call, not a clear-cut fact. Misses here are worth reading, not necessarily a bug.
JUDGMENT_CALLS = {
    "snad_outside_window": "A buyer 91 days out of the return window, not asking for a refund. We label it "
                           "SUBMIT_EVIDENCE (the policy wins, so defend). OFFER_PARTIAL_REFUND is a defensible "
                           "business choice that avoids a fight over $40, so models that pick it are not clearly wrong.",
}

# Cases in the held-out sets whose miss is a known limit of the facts code, not a model failure. Same display as
# JUDGMENT_CALLS; the labels are kept (they are the correct outcome) and nothing is tuned against them.
HOLDOUT2_NOTES = {
    "ho2_inr_unit_format": "Facts-normalisation limit, not a model failure. 'Mill Street Apt 4B' and 'Mill St #4B' "
                           "are one address, but the code that compares the ship-to with the delivered-to address "
                           "does not normalise street suffixes or unit markers, so it can report a mismatch. We keep "
                           "the case and the label, and do not tune against it.",
}


def results_dir() -> Path:
    return HERE / "results"


def slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in ".-" else "-" for c in text.split("/")[-1]).strip("-")


def save_run(summary: dict) -> Path:
    """Keep every valid run as evals/results/<provider>-<model>-<date>.json (a same-day rerun gets -2, -3, ...)."""
    results_dir().mkdir(exist_ok=True)
    case_set = summary.get("set")
    tag = "" if case_set in (None, "main") else "-" + case_set
    base = f"{summary['provider']}-{slug(summary['model'])}{tag}-{summary['date'].replace('-', '')}"
    path, n = results_dir() / f"{base}.json", 2
    while path.exists():
        path, n = results_dir() / f"{base}-{n}.json", n + 1
    path.write_text(json.dumps(summary, indent=2))
    return path


def _cell(row: dict | None) -> str:
    if row is None:
        return "n/a"
    text = "yes" if row["correct"] else f"**{row['got']}**"
    raw = row.get("raw")
    return text if raw is None or raw == row["got"] else f"{text} (model: {raw})"


def _section(runs: list[dict], title: str, intro: str, judgment: dict[str, str],
             kind: str = "judgment call") -> list[str]:
    lines = [f"## {title}", "", intro, "",
             "| Date | Provider | Model | Model alone | Final (model + guard) | Standard | Hard | Guard changed | Tokens "
             "| Gate violations | Langfuse experiment |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        lf = (r.get("langfuse") or {}).get("name", "")
        final = f"{pct(r['accuracy'])} ({round(r['accuracy'] * r['cases'])}/{r['cases']})"
        if r.get("raw_accuracy") is None:
            alone, changed = "final only", "n/a"
        else:
            alone = f"{pct(r['raw_accuracy'])} ({round(r['raw_accuracy'] * r['cases'])}/{r['cases']})"
            changed = f"{r['guard_changes']}/{r['cases']} ({pct(r['guard_changes'] / r['cases'])})"
        lines.append(f"| {r['date']} | {r['provider']} | {r['model']} | {alone} | {final} | "
                     f"{pct(r['standard_accuracy'])} | {pct(r['hard_accuracy'])} of {r['hard_cases']} | {changed} | "
                     f"{r['tokens_used']:,} | {r['approval_gate_violations']} | {lf} |")
    names = [f"{r['provider']}/{slug(r['model'])} {r['date'][5:]}" for r in runs]
    lines += ["", "Per case: `yes` = the final action matches the label; otherwise the final action is shown, and "
              "`(model: X)` means the model alone chose X before the guard changed it. Runs marked final only "
              "have no raw choice.", "",
              "| Case | Expected | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(runs)]
    for cid in [row["id"] for row in runs[-1]["rows"]]:
        cells, expected, hard = [], "", False
        for r in runs:
            row = next((x for x in r["rows"] if x["id"] == cid), None)
            if row:
                expected, hard = row["expected"], row["hard"]
            cells.append(_cell(row))
        flag = f" ({kind})" if cid in judgment else " (hard)" if hard else ""
        lines.append(f"| {cid}{flag} | {expected} | " + " | ".join(cells) + " |")
    if judgment:
        lines += ["", kind.capitalize() + "s:", ""] + [f"- `{cid}`: {note}" for cid, note in judgment.items()]
    return lines


def write_results_md() -> None:
    """RESULTS.md: the main set and the held-out set, each with one line per saved run and a case-by-run matrix."""
    runs = sorted((json.loads(p.read_text()) | {"file": p.name} for p in results_dir().glob("*.json")),
                  key=lambda r: (r["date"], r["file"]))
    lines = ["# Eval results", "",
             "Every valid run is kept in `evals/results/<provider>-<model>[-holdout|-holdout2]-<date>.json`. "
             "A run that hit a rate or quota limit is invalid and is never saved. Rules baseline = no model. "
             "**Model alone** is the model's own choice before `guard()`; **final** is what the agent would propose after the guard."]
    main = [r for r in runs if r.get("set", "main") == "main"]
    holdout = [r for r in runs if r.get("set") == "holdout"]
    holdout2 = [r for r in runs if r.get("set") == "holdout2"]
    if main:
        lines += [""] + _section(main, "Main set (evals/cases.json)",
                                 "20 labeled disputes. The guard rules and the facts were developed against these.",
                                 JUDGMENT_CALLS)
    if holdout:
        lines += [""] + _section(holdout, "Held-out (not used for tuning)",
                                 "evals/holdout.json: 10 disputes written independently of the guard and facts code. "
                                 "Run and reported only; no code is tuned against these results.", {})
    if holdout2:
        lines += [""] + _section(holdout2, "Held-out set 2 (not used for tuning)",
                                 "evals/holdout2.json: 10 more disputes, written blind to the guard and facts code. "
                                 "Run and reported only; no code is tuned against these results.", HOLDOUT2_NOTES, "facts limit")
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n")


class InvalidRun(RuntimeError):
    """The model failed or was rate limited mid-run, so the accuracy would not be the model's."""


def run_case(case: dict, settings: Settings, *, force_rules: bool, tracing: bool = False,
             provider: str | None = None) -> tuple[dict, int, str]:
    """Analyse one labeled case through the graph, up to the approval gate. Returns (row, tokens used, mode)."""
    rt = Runtime(settings=settings, seed_cases=[], force_rules=force_rules, tracing=tracing,
                 checkpointer=InMemorySaver(), provider=provider, strict=True)
    dispute_id = seed_case(case, 0, rt.mock, rt.store)  # works for any case set, not just cases.json
    # Every eval case is dispute PP-D-2000 in its own sandbox, so tag traces with the case id instead.
    trace = {"tags": ["eval", f"case:{case['id']}"],
             "metadata": {"case_id": case["id"], "hard": bool(case.get("hard")),
                          "langfuse_session_id": f"eval:{case['id']}"}}
    p = rt.analyze(dispute_id, config_extra=trace)
    # The model's own choice, before guard(): the "decide" line of the audit trail.
    raw = next(r["detail"]["resolution"] for r in rt.audit.for_dispute(dispute_id) if r["step"] == "decide")
    row = {
        "id": case["id"], "title": case["title"], "hard": case.get("hard", False),
        "expected": case["expected"], "got": p.decision.resolution,
        "correct": p.decision.resolution == case["expected"],
        "raw": raw, "raw_correct": raw == case["expected"], "guard_changed": raw != p.decision.resolution,
        "confidence": p.decision.confidence, "source": p.decision.source,
        "writes_before_approval": len(rt.mock.write_calls()),
        "buyer_wants": p.decision.buyer_wants, "reasoning": p.decision.reasoning,
        "guard_notes": p.decision.guard_notes,
        "provider": rt.reasoner.name, "model": getattr(rt.reasoner, "model_name", "rules"),
    }
    return row, getattr(rt.reasoner, "tokens_used", 0), rt.mode


def run(force_rules: bool, pause: float = 0.0, only: set[str] | None = None, langfuse: bool = False,
        provider: str | None = None, case_set: str = "main") -> dict:
    settings = eval_settings()
    cases = [c for c in load_cases(SETS[case_set]) if not only or c["id"] in only]
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
        name = f"{probe.reasoner.name}-{probe.reasoner.model_name.split('/')[-1]}{'' if case_set == 'main' else '-' + case_set}-" \
               f"{datetime.now(UTC):%Y%m%d-%H%M%S}"
        dataset = DATASETS[case_set] or tracing.DATASET_NAME
        tracing.upload_dataset(cases, dataset)
        result = tracing.run_experiment(
            name=name, task=lambda case: run_one(by_id[case["id"]]), dataset_name=dataset,
            description="evals/run.py --langfuse: every labeled dispute analysed up to the approval gate",
            metadata={"mode": probe.mode, "cases": len(cases)})
        tracing.flush()
        experiment = {"name": name, "dataset": dataset,
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
        "hard_accuracy": acc(hard), "hard_cases": len(hard), "set": case_set,
        "raw_accuracy": acc([{"correct": r["raw_correct"]} for r in rows]),
        "guard_changes": sum(r["guard_changed"] for r in rows),
        "approval_gate_violations": sum(r["writes_before_approval"] for r in rows),
        "rows": rows, "tokens_used": tokens_total, "langfuse": experiment,
    }
    first = rows[0] if rows else {"provider": "rules", "model": "rules"}
    summary.update(provider=first["provider"], model=first["model"],
                   date=datetime.now(UTC).strftime("%Y-%m-%d"))
    if not only:  # a partial run (--only) is not a result worth keeping
        save_run(summary)
        write_results_md()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true", help="force the offline rules baseline")
    ap.add_argument("--pause", type=float, default=0.0, help="seconds to wait between cases (rate limits)")
    ap.add_argument("--only", help="comma-separated case ids (results files are overwritten with just these)")
    ap.add_argument("--langfuse", action="store_true",
                    help="trace every case and record the run as a Langfuse experiment (needs the Langfuse keys)")
    ap.add_argument("--set", dest="case_set", choices=list(SETS), default="main",
                    help="main = cases.json; holdout, holdout2 = the held-out sets (never used for tuning)")
    ap.add_argument("--rebuild-md", action="store_true", help="regenerate RESULTS.md from evals/results/ and exit")
    ap.add_argument("--provider", choices=PROVIDERS, help="pin the model provider (needs its key in backend/.env)")
    args = ap.parse_args()
    if args.rebuild_md:
        write_results_md()
        raise SystemExit(0)
    try:
        s = run(force_rules=args.rules, pause=args.pause, only=set(args.only.split(",")) if args.only else None,
                langfuse=args.langfuse, provider=args.provider, case_set=args.case_set)
    except InvalidRun as exc:
        raise SystemExit(f"EVAL INVALID, no results written: {exc}") from exc
    print(f"{s['mode']} [{s['set']}]: model alone {pct(s['raw_accuracy'])}, guard changed {s['guard_changes']}/{s['cases']}, "
          f"final {pct(s['accuracy'])} overall, {pct(s['standard_accuracy'])} standard, "
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
