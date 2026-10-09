# 0004. Facts computed in code, `guard()` over the model

Status: Accepted

## Context

A language model reads buyer wording well, but should not be trusted to decide whether a package was delivered, whether a
refund exists or whether an AI assistant ordered the wrong variant. Those are checkable.

## Decision

- Hard facts (tracking, delivery against the ship-to address, policy windows, refunds, duplicate charges, assistant
  purchase versus instruction) are computed in [`agent/facts.py`](../../backend/rebuttal/agent/facts.py), not by the
  model.
- Only the `decide` node calls a model. `ModelReasoner` in [`agent/llm.py`](../../backend/rebuttal/agent/llm.py) uses
  `with_structured_output` against the Pydantic `DecisionOut`; invalid output falls back to the rules baseline
  (`RuleReasoner` in [`agent/reasoner.py`](../../backend/rebuttal/agent/reasoner.py)).
- `guard()` in `reasoner.py` then rejects or converts choices the facts do not support (for example sharing tracking
  when there is none, or refund proof when no refund exists) and records `guard_notes`. The `guard` node also
  re-reads the dispute and checks PayPal's current `allowed_response_options`.

## Consequences

- Tests and evals can run with no model (`REBUTTAL_REASONER=rules`, set in `tests/conftest.py`).
- Guard rules are safety code: they are covered by the evals and must not be removed as redundant.
- A fact the code cannot compute (for example street-suffix normalisation in address comparison) is a known limit,
  annotated in [`evals/run.py`](../../backend/evals/run.py) (`HOLDOUT2_NOTES`) rather than hidden by the model.
