# 0005. Deterministic PayPal-Request-Id and an audit log

Status: Accepted

## Context

An approved action can be retried after a crash between the PayPal call and the checkpoint. A random idempotency key
would make the retry a new request. Merchants and reviewers also need a record of every step and write.

## Decision

- `idempotency_key(proposal_id, index, kind)` in [`approval.py`](../../backend/rebuttal/approval.py) is a UUIDv5 of
  `rebuttal:<proposal>:<index>:<kind>`. `execute` passes it as `request_id`, and `PayPalClient._request` sends it as
  `PayPal-Request-Id`; any other POST or PATCH gets a fresh UUID4.
- PayPal documents that header for Orders and Payments, not clearly for Disputes, so it is not relied on alone: before
  sending, `execute` reads the dispute and skips a message or offer that `already_applied` shows has landed.
- [`audit.py`](../../backend/rebuttal/audit.py) appends a record per step (`gather`, `decide`, `guard`, `propose`,
  `approve`, `execute`, `execute_failed`, `execute_interrupted`, `reject`, `record`), including the key. It lives in memory, a JSONL file, or
  the Postgres table `rebuttal_audit`.

## Consequences

- A retry of the same action is the same request to PayPal.
- Evidence and accept-claim are not reconciled by `already_applied`; a repeated one can report FAILED even if the
  first went through, so the merchant should check the dispute.
