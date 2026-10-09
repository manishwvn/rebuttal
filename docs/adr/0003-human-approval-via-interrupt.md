# 0003. Human approval through LangGraph `interrupt()`

Status: Accepted

## Context

Every resolution must wait for the merchant, possibly for days, across restarts and redeploys. A custom pending-queue
table would duplicate state the workflow already has and invite drift between "what was proposed" and "what runs".

## Decision

The workflow is `gather_facts > decide > guard > plan_actions > approval > execute > record`
([`agent/graph.py`](../../backend/rebuttal/agent/graph.py)). The `approval` node calls LangGraph's `interrupt()` with
the proposal and a `response_schema` of `ApprovalDecision` (approve, edit or reject; an edit needs a non-empty
message). `route_after_approval` sends only `approved` or `edited` to `execute`; a rejection goes straight to
`record`. The paused state lives in the checkpointer ([`persistence.py`](../../backend/rebuttal/persistence.py)), one
thread per dispute. `ApprovalQueue` in [`approval.py`](../../backend/rebuttal/approval.py) only drives the graph.

Because LangGraph remembers the first resume value of a task, nothing fallible runs after `interrupt()` returns, and
nothing fallible runs after the PayPal call inside `execute`; audit lines are written by `record`.

## Consequences

- A proposal survives a restart when a durable checkpointer is configured.
- Approving is resuming by exact proposal id, so a stale proposal is never approved by mistake.
- Node code around the interrupt has a strict rule, documented at the top of `approval.py`.
