# 0009. An isolated judge demo runtime

Status: Accepted

## Context

Judges have no PayPal accounts. The real API needs a bearer token (`REBUTTAL_API_TOKEN`), and whoever holds it can
call approve, so the real API cannot be opened to judges ([README](../../README.md#run-it), the configuration
table). The demo still has to run the agent end to end, with approval, and it must not become a path to the real
sandbox or the real approval gate.

## Decision

The demo runs on the same FastAPI service, under `/api/demo/...`. Those routes need no token and reach only a demo
manager. The manager gives each visitor a session with its own Runtime, built with the in-memory MockPayPal, the rules
reasoner (no model call), tracing off, an in-memory LangGraph checkpointer, an in-memory audit log and no database. A
session never receives the real PayPal client, the settings secrets or the real runtime, whatever the environment
says.

Approval in a demo session uses the same path as the real service: `ApprovalQueue`, the LangGraph `interrupt()`, then
the `execute` node in [`approval.py`](../../backend/rebuttal/approval.py). ADR 0001 still holds, and the writes land
on the mock.

Sessions are bounded: 40 live, 30 minutes idle, 2 hours maximum age, 16 disputes each, and 20 creations or resets per
minute for the whole service. The isolation guarantees are tested in `backend/tests/test_demo_isolation.py`.

Alternatives rejected:

- A shared, global demo runtime. One visitor's approve or reset would change another visitor's disputes.
- A public token for judges. Values in `VITE_*` are readable in the built bundle ([frontend README](../../frontend/README.md)),
  and the backend token authorizes approve.
- The demo on the real runtime in mock mode. The real runtime reads the service's environment (keys, `DATABASE_URL`,
  `REBUTTAL_MOCK`), so demo traffic would depend on every one of those settings staying safe. A separate runtime that
  ignores them does not.
- A client-side-only demo. Canned responses in the browser would not run the API, the approval interrupt or the audit
  log, so judges would not see the agent work.

## Consequences

- Demo sessions run the same graph and approval code as the real service, so a change to the agent changes the demo too.
- The demo routes are open on purpose, so their bounds are what limit how much a visitor can use. A route inventory
  test keeps the real API routes behind the token, except `/api/health` and the PayPal webhook, which is checked by
  signature.
- State lives in memory. A restart or a free-plan cold start clears every session; an expiry clears only that session.
  The UI offers Reset demo.
- Demo approvals never reach PayPal. The demo shows the write path without a real write.
- The demo adds routes and tests to maintain. Changes to the demo must keep the isolation tests green.
