# Judge demo mode

Judges have no PayPal accounts, so Rebuttal has a demo mode that needs none. It runs on the same FastAPI service as the dashboard, under `/api/demo/...`, with a session per visitor that never reaches the real PayPal client, the real runtime or a database.

## How a judge uses it

1. Open the dashboard and click the **Try the demo** link in its header, or add `#demo` to its address (for example `http://localhost:5173/#demo` locally). The page creates a session with `POST /api/demo/sessions`.
2. The inbox holds six seeded disputes. The hero case, `agent_wrong_size`, is already analyzed and waits for approval. Open it, read the facts, the reasoning and the drafted message, then approve, edit or reject.
3. Add any of the 20 labeled cases from the simulator, or click **Reset demo** to start again.

An approval goes through the same path as the real service: `ApprovalQueue`, the LangGraph `interrupt()`, then `execute` in [`approval.py`](../backend/rebuttal/approval.py). In a demo session, `execute` writes only to the in-memory mock sandbox.

## Routes

Every route but the first is under `/api/demo/{session_id}`. Treat the session id as a secret; the routes take no bearer token.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/demo/sessions` | Create a session; returns its secret session id |
| GET | `/api/demo/{session_id}/health` | Health of the session |
| GET | `/api/demo/{session_id}/disputes` | List the session's disputes |
| POST | `/api/demo/{session_id}/disputes/{id}/analyze` | Analyze a dispute |
| GET | `/api/demo/{session_id}/proposals/pending` | Proposals waiting for approval |
| POST | `/api/demo/{session_id}/proposals/{id}/approve` | Approve a proposal (mock sandbox) |
| POST | `/api/demo/{session_id}/proposals/{id}/retry` | Continue an approved proposal whose PayPal call was interrupted |
| POST | `/api/demo/{session_id}/proposals/{id}/reject` | Reject a proposal with a reason |
| GET | `/api/demo/{session_id}/audit/{dispute_id}` | Audit trail of a dispute |
| GET | `/api/demo/{session_id}/simulator/cases` | The labeled cases |
| POST | `/api/demo/{session_id}/simulator/dispute/{case_id}` | Create a dispute from a labeled case |
| POST | `/api/demo/{session_id}/reset` | Reset the session |

## Isolation guarantees

1. A demo session never receives the real runtime or the real PayPal client. Test: the tripwire on the real runtime in `backend/tests/test_demo_isolation.py`.
2. Environment settings do not reach demo sessions: `REBUTTAL_MOCK=0`, the PayPal keys, the Groq key and `DATABASE_URL` are ignored. Test: the hostile-environment case in `backend/tests/test_demo_isolation.py`.
3. Each session has its own Runtime (in-memory MockPayPal, rules reasoner, tracing off, in-memory checkpointer and audit log, no database), so sessions share no state. Test: `backend/tests/test_demo.py`.
4. The real routes keep `REBUTTAL_API_TOKEN`; the demo routes take none. Test: the route inventory of the token dependency in `backend/tests/test_demo_isolation.py`.
5. The demo modules have no PayPal write path except `execute` ([ADR 0001](adr/0001-single-paypal-write-path.md)). Test: the write-boundary scan of the demo modules in `backend/tests/test_demo_isolation.py`.
6. A demo approval runs the real approval path against the mock: `ApprovalQueue`, the interrupt, then `execute`. Test: `backend/tests/test_demo_api.py`.

The browser flow is tested by `frontend/e2e/demo.spec.ts`.

## Limits

| Limit | Value | What happens |
|---|---|---|
| Live sessions | 40 | The least recently used session is evicted. |
| Idle expiry | 30 minutes | The session expires and its state is gone. |
| Maximum age | 2 hours | The session expires, even when in use. |
| Disputes per session | 16 | Creating more returns 429. |
| Session creations and resets | 20 per minute, whole service | Returns 429 with `Retry-After`. |
| Edited message | 2000 characters | Longer bodies are refused. |
| Reject reason | 500 characters | Longer bodies are refused. |

## Run it locally

Terminal 1, the backend. `REBUTTAL_API_TOKEN=` and `DATABASE_URL=` are blank so a `backend/.env` on your machine cannot change this run. `REBUTTAL_CORS_ORIGINS` lets the page on port 5173 call the API.

```bash
cd backend
uv sync                                    # once
REBUTTAL_MOCK=1 REBUTTAL_REASONER=rules REBUTTAL_API_TOKEN= DATABASE_URL= \
  REBUTTAL_CORS_ORIGINS=http://localhost:5173 uv run uvicorn rebuttal.app:app --port 8000
```

Terminal 2, the dashboard. Its setup is in [frontend/README.md](../frontend/README.md).

```bash
cd frontend
npm install                                # once
npm run dev                                # then open http://localhost:5173/#demo
```

The demo needs no keys and no model.

## Known limits

- Sessions live in memory, in one process. A restart, an expiry or a Render free-plan cold start clears every session (the free plan sleeps after 15 idle minutes, see [deploy.md](deploy.md)). A second instance would not see them.
