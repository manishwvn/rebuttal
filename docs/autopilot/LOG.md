# Autopilot log

## 2026-10-09 16:15 CDT | W 82→82 % | F 3→3 % | S1 | PR open
Checked Orders v2 payloads and carrier values against the paypal-server-sdk models (installed in a scratch venv): no drift; SDK has no Disputes API. Logged in apimatic-log.md. QUEUE A4 marked done (script already on main). Docs only; no code touched.

Newest first. One block per working cycle; skipped cycles go to `~/.rebuttal-autopilot/runs.log` only.

## 2026-10-09 16:40 CDT | W 82→~85 % | A5 | merged #39
Sonnet built same-origin SPA serving, sign-in (sessionStorage, "Try the demo" #demo), render.yaml frontend build. Reviewer: no blockers; fixed traversal test, null-byte 500, HEAD 405, and made the Render build fall back to API-only if Node/npm fails Live health ok after merge, but `/` returned 404 about 15 min later: not yet confirmed whether Render built the frontend (no Render MCP workspace selected, no key use).

## 2026-10-09 | A6 | in review (PR #33)
Judge demo mode built by the team workflow: per-visitor isolated mock Runtime (`demo.py`), public `/api/demo/{session}` router (`demo_api.py`), router shell + shared Desk + DemoApp on the frontend, docs and ADR 0009. Integration fixed the open audit findings (reset lock, 404 before 422, per-dispute lock growth, docstring, `demo-route` spec). approval.py, paypal/, facts.py, reasoner.py, config.py untouched. Needs lead review of the isolation; not run against Render.

ALERT weekly-80 2026-10-14T00:00:00Z sent

## 2026-10-09 11:35 CDT | W 72→81 % | F 29→98 % | A6 | merged #33
Team workflow built demo mode; Opus reviewer: no blockers, 1 medium (one client could evict all sessions) fixed with per-client limit (env REBUTTAL_DEMO_CLIENT_LIMIT, default 10/min) and 429 at capacity; e2e failure from shared-IP limit fixed. Live POST /api/demo/sessions returns 200 and health ok after deploy.

## 2026-10-09 09:15 CDT | W 68→72 % | F 10→26 % | Q3, A7 | merged #28, #26
Q3: official paypal-agent-toolkit can't be read-only, so a 4-tool read-only adapter now backs gather(); Opus review confirmed write boundary. A7 merged. Follow-up: replace waitForTimeout(500) in dev-strictmode.spec.ts; README/ADR source notes added.

## 2026-10-09 | Q3 | in review (PR #28)
The official `paypal-agent-toolkit` 1.11.0 cannot be made strictly read-only (langchain pin, `run()` dispatches every tool, `requests` bypasses our transport, no `fields=all`). Built by the team workflow: `agent/toolkit.py` (four read tools in the toolkit's shape over `client.read_only()`), `gather` wired to it by the lead, ADR 0008, README and prize-fit. Evals JSON identical before and after. APIMatic plugin not used, so no apimatic-log entry. Needs lead review: touches `facts.py`.

## 2026-10-09 | A7 | PR open
ConfirmDialog closed at once under the Vite dev server: StrictMode's simulated unmount calls `close()`, and the late `close` event ran `onCancel`. Fix: `onClose` only cancels when the dialog is really closed. New Playwright project server (Vite dev on 5174) and `e2e/dev-strictmode.spec.ts` failed before the fix, passes after. StrictMode stays on.

## 2026-10-09 | W 68% | F 6% | Q2 | PR open
Stale lock (180 min) taken over. ADRs written by a Sonnet agent, claims spot-checked against code and workflows. Q1 was already merged (#18).

## 2026-10-09 | B1 part 1 | in review (PR #16)
Analytics endpoints, AG Studio 3.0.0 Analytics tab and docs/ag-studio.md, built by the team workflow. Decision: Studio
runs unlicensed (watermark allowed); deadlines read the due date per waiting dispute because the mock/list may omit it.

## 2026-10-09 00:40-01:00 CDT | W 55→? % | F 6→? % | A1, A2 (+ A3, A4 started) | merged #6, this PR
Lead worked directly in the planner session instead of waiting for the 3 AM cycle (Manish's call). A1 keep-awake ping
merged (#6) and triggered. A2 held-out eval: model alone 80%, final 100%, 0 gate violations. Pacing below 80% dropped.
A3 frontend follow-ups and A4 video script running as Sonnet subagents in worktrees.

## 2026-10-09 | setup
Autopilot set up by the lead session: runbook `CYCLE.md`, queue `QUEUE.md`, scheduled task every 3 hours, alerts by
push and by issue in the private repo `manishwvn/rebuttal-alerts` (GitHub emails the @mention). PR #3 (frontend
slice 1) merged after review. Weekly usage at setup: 54% (resets Oct 14).
