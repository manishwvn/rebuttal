# Judge demo mode

Judges have no PayPal accounts, so Rebuttal has a demo mode that needs none. It runs on the same FastAPI service as the dashboard, under `/api/demo/...`, with a session per visitor that never reaches the real PayPal client, the real runtime or a database. The demo runs locally now and will be on Render once A5 serves the built frontend.

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

1. A demo session never receives the real runtime. Test: `test_a_judge_runs_the_demo_without_a_token_and_never_touches_the_real_runtime` (a tripwire on the real runtime) in `backend/tests/test_demo_isolation.py`.
2. Environment settings do not reach demo sessions: `REBUTTAL_MOCK=0`, the PayPal keys, the Groq key and `DATABASE_URL` are ignored, and every PayPal client a session builds uses the mock transport. Test: `test_a_hostile_environment_still_gives_a_mock_rules_demo` in `backend/tests/test_demo_isolation.py`, and `test_demo_runtime_is_mock_rules_and_ignores_real_environment` in `backend/tests/test_demo.py`.
3. Each session has its own Runtime (in-memory MockPayPal, rules reasoner, tracing off, in-memory checkpointer and audit log, no database), so sessions share no state. Test: `test_two_runtimes_share_nothing` in `backend/tests/test_demo.py`.
4. The real API routes keep `REBUTTAL_API_TOKEN`, except `/api/health` and the PayPal webhook, which is checked by signature. The demo routes take none. Test: `test_every_api_route_is_guarded_except_the_demo_and_the_two_open_ones` in `backend/tests/test_demo_isolation.py`.
5. The demo modules have no PayPal write path except `execute` ([ADR 0001](adr/0001-single-paypal-write-path.md)). Test: `test_the_demo_modules_cannot_reach_the_app_the_real_runtime_or_a_paypal_write` in `backend/tests/test_demo_isolation.py`.
6. A demo approval runs the real approval path against the mock: `ApprovalQueue`, the interrupt, then `execute`. Test: `test_hero_flow_runs_end_to_end_without_a_token` in `backend/tests/test_demo_api.py`.

The browser flow is tested by `frontend/e2e/demo.spec.ts`.

## Limits

| Limit | Value | What happens |
|---|---|---|
| Live sessions | 40 | At capacity, a session idle for 5 minutes or more is evicted to make room; if every session was active more recently, the new one gets 429 with `Retry-After`. |
| Idle expiry | 30 minutes | The session expires and its state is gone. |
| Maximum age | 2 hours | The session expires, even when in use. A reset does not restart it. |
| Disputes per session | 16 | Creating more returns 429. |
| Workflow runs per session | 100 | Analyze, approve, reject, retry and simulate each count as one run. Every run adds checkpoints and audit rows to the session's memory, so the 101st returns 429 until the visitor clicks **Reset demo**, which restores the budget. |
| Session creations and resets | 5 per minute per client (first `X-Forwarded-For` hop, else the peer address), 20 per minute for the whole service | Returns 429 with `Retry-After`. |
| Waiting for a busy session | 10 seconds | Returns 429. |
| Runtime build failure | none | Returns 503 with JSON. |
| Edited message | 2000 characters | Longer bodies are refused. |
| Reject reason | 500 characters | Longer bodies are refused. |

## Run it locally

Terminal 1, the backend. `REBUTTAL_API_TOKEN=`, `DATABASE_URL=` and `REBUTTAL_CHECKPOINT_URL=` are blank so a `backend/.env` on your machine cannot change this run. `REBUTTAL_CORS_ORIGINS` lets the page on port 5173 call the API.

```bash
cd backend
uv sync                                    # once
REBUTTAL_MOCK=1 REBUTTAL_REASONER=rules REBUTTAL_API_TOKEN= DATABASE_URL= REBUTTAL_CHECKPOINT_URL= \
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

- Sessions live in memory, in one process. A restart or a Render free-plan cold start clears every session (the free plan sleeps after 15 idle minutes, see [deploy.md](deploy.md)). An idle or maximum-age expiry clears only that visitor's session. A second instance would not see them.
