# 0001. A single PayPal write path: the graph `execute` node

Status: Accepted

## Context

Rebuttal changes real disputes (messages, offers, evidence, accept-claim). A merchant must be able to trust that
nothing reaches PayPal unless they approved it. With many modules and scripts holding a PayPal client, that is easy
to break by accident.

## Decision

Only the `execute` node in [`backend/rebuttal/approval.py`](../../backend/rebuttal/approval.py) makes PayPal write
calls. Three layers enforce it:

1. `PayPalClient` ([`paypal/client.py`](../../backend/rebuttal/paypal/client.py)) wraps its transport in
   `WriteGateTransport`; a POST/PATCH/PUT/DELETE raises `WriteNotPermitted` unless the caller is inside the
   `permit_writes()` context manager (a `ContextVar`). The OAuth token and webhook-verify POSTs are the only
   exemptions, because they change nothing at PayPal.
2. `execute` is the only graph node that enters `permit_writes()`, and it raises `ApprovalError` without an
   approved or edited decision. Named manual sandbox scripts also enter it.
3. [`tests/test_write_boundary.py`](../../backend/tests/test_write_boundary.py) scans the package, scripts and evals
   for any other reference to a write method or `permit_writes`.

## Consequences

- A new feature that needs a write must go through `execute`; the boundary test fails otherwise.
- The three layers are deliberately redundant. Code-minimising tools must not remove them.
- Manual sandbox scripts are a named, tested exception, not an open door.
