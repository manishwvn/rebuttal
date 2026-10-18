# 0007. Held-out evals

Status: Accepted

## Context

The facts code and guard rules were developed against the 20 labeled disputes in `evals/cases.json`. Scores on those
cases overstate how the agent behaves on new disputes.

## Decision

Keep labeled sets under [`backend/evals/`](../../backend/evals) and treat two as held out:
[`holdout.json`](../../backend/evals/holdout.json) and [`holdout2.json`](../../backend/evals/holdout2.json), 10
disputes each, written independently of the guard and facts code. They are reported, not tuned against
(`SETS` in [`evals/run.py`](../../backend/evals/run.py)). Each valid run is saved under `evals/results/`; a run that
hit a rate or quota limit is marked invalid and not saved. The report separates the model alone from the final
(model plus guard) outcome and counts PayPal writes before approval, which must be 0.
[`RESULTS.md`](../../backend/evals/RESULTS.md) holds the numbers. A known facts limit on a held-out case is annotated (`HOLDOUT2_NOTES` in
[`evals/run.py`](../../backend/evals/run.py)), not fixed to fit the label. One exception: on Oct 18 the rules baseline and `guard()` were fixed after Held-out 2 showed
a double refund (`ho2_dup_already_refunded`); the Oct 10 numbers predate the fix, and later results on that case are not
blind.

## Consequences

- The main-set score is a development number; the held-out numbers are the more honest ones (one Held-out 2 case was later fixed, see above).
- Run results come from [`RESULTS.md`](../../backend/evals/RESULTS.md) and should be quoted from there, not recalled.
