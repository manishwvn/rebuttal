# 0002. A read-only client for analysis nodes

Status: Accepted

## Context

Analysis nodes (`gather_facts`, `decide`, `guard`, planning) only need to read disputes, orders and policies. The
write gate in ADR 0001 relies on a context variable; we wanted analysis code to be unable to write even if that
variable were ever set around it, or if someone reached for the client's private attributes.

## Decision

`PayPalClient.read_only()` ([`paypal/client.py`](../../backend/rebuttal/paypal/client.py)) returns a clone with the
same credentials and endpoint, whose transport is `ReadOnlyTransport`: it passes GET and HEAD (plus the OAuth token
and webhook-verify POSTs) and raises `WriteNotPermitted` for everything else. The clone discards its build recipe
(`_init = None`), so it cannot be turned back into a writable client. `build_graph` in
[`agent/graph.py`](../../backend/rebuttal/agent/graph.py) takes `reader = client.read_only()` and gives that to every
node except `execute`, which receives the full client.

## Consequences

- The refusal happens at the HTTP layer, below any method on the client.
- Analysis can run freely (retries, re-reads, webhook-triggered runs) with no way to change a dispute.
- `tests/test_core.py::test_analyze_never_writes_to_paypal` and the eval counter of PayPal writes before approval
  (`writes_before_approval` in [`evals/run.py`](../../backend/evals/run.py)) check the property end to end.
