# STATUS

Read this at the start of a session; update it at the end of every task. Last updated: Oct 9, 2026 (branch `feat/demo-mode`:
A6, judge demo mode). Detail: `docs/handoff-2026-10-07.md`, `PLAN.md`, `docs/deploy.md`.

**Autopilot:** an unattended lead-dev session works through `docs/autopilot/QUEUE.md` every 3 hours; see
`docs/autopilot/README.md`. Progress: `docs/autopilot/LOG.md`.

**Prize strategy:** `docs/prize-fit.md` (prizes, rules, competition, decisions; read Oct 9 from Devpost and Discord).

## Where we are

- **Q4 (branch `feat/q4-sandbox-dispute`, PR open):** `backend/scripts/make_sandbox_dispute.py` opens a sandbox dispute as the buyer business account (`PAYPAL_BUYER_CLIENT_ID/SECRET`) via `PayPalClient.create_dispute`. Not yet run against the real sandbox; request body carries a VERIFY note. Manual step: the buyer approves the order link once.
- **Live backend:** Render free plan, service `rebuttal` (render.yaml names it `rebuttal-api`), id
  `srv-db3179ss728c73b0do1g`, `https://rebuttal-oq3g.onrender.com`, health `/api/health`. Real PayPal sandbox
  (`REBUTTAL_MOCK=0`), Groq as the model (`GROQ_MODEL` unset on Render, so the code default `qwen/qwen3.8-27b`),
  Supabase Postgres (`bqhumxlcnatwugmgfluu`, RLS on) for LangGraph checkpoints and `public.rebuttal_audit`.
  Secrets live only in the Render dashboard and `backend/.env`. Render env var names: `PAYPAL_ENV=sandbox`,
  `REBUTTAL_MOCK=0`, `PAYPAL_CLIENT_ID`/`SECRET`, `PAYPAL_WEBHOOK_ID`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `LANGFUSE_*`
  (3), `DATABASE_URL`, `REBUTTAL_API_TOKEN`, `REBUTTAL_MODEL`. `SUPABASE_ACCESS_TOKEN` was removed on purpose. GitHub variable `APP_HEALTH_URL` runs the daily
  Supabase keep-alive.
- **Webhook proven live:** `47P29746F3179022C` (sandbox app "Default Application") -> `/api/webhooks/paypal` for `CUSTOMER.DISPUTE.CREATED/UPDATED/RESOLVED`; arrives about 3.5-4
  minutes after a buyer files, signature verified, then gather > decide > guard > propose and stops at the approval
  interrupt. Only CREATED starts an analysis; Webhooks Simulator events get 401 by design.
- **Hero case correct live** (dispute `PP-R-SVN-10190455`): order found, assistant said "medium" vs shipped L,
  `buyer_asks_for_refund` true; Groq chose OFFER_REPLACEMENT, the guard converted it to "refund $48 after return". Older live disputes
  `PP-R-GFH-10190453` and `PP-R-HDU-10190454` hold stale proposals; leave them unapproved.
- **PayPal Agent Toolkit shape, read-only (PR #28, Q3):** the official `paypal-agent-toolkit` 1.11.0 cannot be used
  strictly read-only (langchain pin conflicts with ours, `run()` dispatches any tool by name, it uses `requests`
  past our transport, `list_transactions` lacks `fields=all`). `rebuttal/agent/toolkit.py` is a four-tool adapter in its
  tool shape over `client.read_only()`; `gather` reads PayPal only through it and the audit lines name the tool. ADR 0008;
  tests `test_toolkit.py`, `test_gather_toolkit.py`. No dependency added.
- **Guard rules** (facts decide, the model does not): no offer type PayPal does not allow (fallback to the proven
  REFUND / REFUND_WITH_RETURN when PayPal lists none; execute refuses too), assistant mis-orders get the friendly
  fix, no tracking on not-received gets a refund, damaged high-value items get return-for-refund (`f4cb66d`, added after the 90% run:
  `snad_damaged_high_value` went 1/3 to 3/3).
- **Evals:** main set (20 cases) on Groq 90% (18/20), hard cases 4/4, run `groq-qwen3.8-27b-20261007-112629`;
  swings 80-95% run to run. The main set has been used for tuning. `snad_outside_window` is a judgment call.
  **Held-out set** (`evals/holdout.json`, 10 cases, written without reading the guard or facts code) ran Oct 9 on
  Groq: model alone 80% (8/10), final 100% (10/10), hard 3/3, gate violations 0, 13.7k tokens (run
  `groq-qwen3.8-27b-holdout-20261009-054233`). Both guard changes turned OFFER_REPLACEMENT (an offer type PayPal does
  not allow) into OFFER_RETURN_FOR_REFUND. Small sample: 10 cases. No code changed. Table: `backend/evals/RESULTS.md`.
  **Second held-out set** (`evals/holdout2.json`, 10 cases, 5 hard, written blind by a subagent that never read the
  agent code): ran Oct 10 on Groq: model alone 80% (8/10), final 100% (10/10), hard 6/6 by the run's count, gate
  violations 0, 14.0k tokens (run `groq-qwen3.8-27b-holdout2-20261010-051607`). Guard changed 2/10. No code changed.
- **Frontend slice 1 (merged, PR #3; follow-ups in PR #9, `fix/frontend-followups`):** `frontend/` is Vite + React + TS with an AG Grid
  Community inbox (only the five grid modules it uses; JS bundle 1,399 kB -> 996 kB, gzip 398 -> 288 kB), case view
  (assistant instruction vs shipped, facts, reasoner choice vs final action, guard note, editable message), approve / edit /
  reject behind a confirm dialog that states the exact PayPal call, audit timeline, and a mock-only simulator. After a
  failed call the dialog stays readable but its button is disabled once the proposal is no longer pending. An
  approved-but-interrupted case shows the approved text (the merchant's edit) and the retry dialog states it.
  `npm run build` refuses `VITE_API_TOKEN` (see `frontend/README.md`). Built and tested with `REBUTTAL_MOCK=1 REBUTTAL_REASONER=rules`,
  no model key, no real sandbox, no Supabase. 8 Playwright tests run in CI (hero approve-with-edit, reject, 409, cancel,
  interrupted call then retry, 3 build-guard); run commands: `frontend/README.md`.
  Backend changes (additive): CORS from `REBUTTAL_CORS_ORIGINS`, `GET /api/simulator/cases` (mock only),
  `approved_message` on the proposal payload (read from the approval record; execute unchanged), a JSON 502 when PayPal
  fails or cannot be reached during approve or retry (was a bare 500 that cross-origin browsers cannot read; the
  status and debug_id go to the server log and an `execute_interrupted` audit line, never the response; a retry is
  promised only for a 5xx or a network error), and mock-only `POST /api/simulator/interrupt-next-write` (the next
  PayPal write is applied, then answered 503, for the retry test; any seller write attempt uses the flag up). The
  `VITE_API_TOKEN` build guard is a Vite plugin hook, so it reads the same env the build inlines from any start directory.
- **Analytics (PR `feat/studio-data`, B1 part 1):** read-only `GET /api/analytics` (rows, summary and deadlines from one
  sweep of the disputes, which the tab loads) plus the single-part `/api/analytics/rows`, `/summary`, `/deadlines`
  (`backend/rebuttal/analytics.py`, same API token as the other reads, PayPal read through `client.read_only()`; a
  waiting dispute's due date is read from the dispute because the list summary may omit it). Frontend: lazy-loaded
  **Analytics** tab with an AG Studio 3.0.0 dashboard (`ag-studio` + `ag-studio-react`, unlicensed with the watermark
  allowed on Discord; five KPIs, three charts, deadlines grid, light and dark). Notes: `docs/ag-studio.md`;
  screenshot `docs/screenshots/analytics.png`. Fallback to Community grid/charts not needed.
- **Judge demo mode (A6, branch `feat/demo-mode`):** "Try the demo" (`/#demo`) gives each visitor a private mock-only
  Runtime (mock PayPal, rules reasoner, in-memory checkpoints and audit, no database, no tracing) behind the public
  `/api/demo/{session}/...` routes, with hard bounds (40 sessions, 30 min idle, 2 h max age, 16 disputes, 20 creates or
  resets a minute, 100 workflow runs per session). `rebuttal/demo.py` and `demo_api.py` import nothing from the app, and `app.py` passes nothing from
  `rt` into the demo; `approval.py`, `paypal/`, `facts.py`, `reasoner.py` and `config.py` are untouched, and the
  approve button still runs the one `execute` node, on the mock. Every other `/api` route keeps the token
  (`tests/test_demo_isolation.py`). Frontend: `App.tsx` is now a router shell over `Dashboard`, `DemoApp` and the shared
  `Desk`. Docs: `docs/demo-mode.md`, ADR 0009. Not verified: a run against the deployed Render service.
- **Tests:** 376 pass (backend), 25 Playwright tests (23 run, 2 skipped); the PayPal write boundary (only `approval.py`'s `execute`) is enforced by tests.

## Known issues (analytics)

- Studio bundle: the lazy Analytics chunk is about 4.4 MB (1.2 MB gzip); `AllCommunityModule` can be trimmed later.
- A Studio data refresh remounts the widget (Studio resets state when `data` changes), so Refresh flashes.
- `useAgThemeMode` duplicates the Inbox's theme-mode effect; dedupe in C1.
- Whether the real sandbox list returns `seller_response_due_date` is unverified; the deadlines view reads it from the
  dispute either way (one extra GET per waiting dispute, reused for 60 s; a failed read leaves that dispute without a
  deadline). A failed dispute list answers 502.
- `PayPalClient.list_disputes` is unpaginated, so the analytics (and the inbox) cover the first page PayPal returns.
  Paging through `next_page` is a later task. Each refresh also reads the checkpoint and audit log once per dispute.
- "Refunded" means the offer or claim reached PayPal as executed, not that the buyer accepted it. Sums ignore currency (USD).

## Next, in order

1. Autopilot queue: `docs/autopilot/QUEUE.md` (source of truth for what is next).
2. B1 parts 2-3: custom Studio widgets (`createWidgets`) and the Agent Framework (browser adapter proxied through the
   backend, read-only); trim `AllCommunityModule`. Then frontend slice 2: Studio polish, Render static site, point the dashboard at the
   live sandbox with `VITE_API_BASE` + `VITE_API_TOKEN`. Slice 1 is done (see above). Build and test with
   `REBUTTAL_REASONER=rules`, `REBUTTAL_MOCK=1` to save Groq tokens (`REBUTTAL_PROVIDER=rules` is not a valid value).
3. Video script by **Oct 12**; rough cut Oct 23.
4. Render paid plan by **Nov 1** (use the $50 credit). Feature freeze Nov 3. **Submit Nov 10** (deadline Nov 12).
   Delete the Render service Dec 22.

## Open decisions

- Tick "Transaction search" in the PayPal sandbox app (explains the 403; optional, Manish's call).
- Discord answers pending: Bryntum license, whether a replacement offer type exists.
- A second free Groq key for evals before recording the video (see known issues).
- Ponytail plugin: not installed; maybe a one-shot ponytail-audit after the hackathon, read-only.
- Which sponsor prize beyond AG Grid (APIMatic log in `docs/apimatic-log.md`; Bryntum is backup only).

## Known issues

- `VITE_API_TOKEN` is public in a built bundle, so the build now refuses it; there is still no login: add one before
  deploying the dashboard (queue task A5).
- Frontend: the grid still ships about 1 MB of JS (the grid core plus React; the module list is already minimal).
- On a retry `execute` runs again and logs its `approve` line again, so the audit trail shows two `approve` rows for one
  approval (the `execute` row is single, and says when the first attempt had already landed).
- The tab icon (`frontend/public/favicon.svg`) is still the Vite logo; swap it for a Rebuttal icon.
- A simulated dispute created twice from the same case shows "2 matching charges": the mock holds both same-amount
  charges, so the duplicate-charge fact is genuine, not a UI bug.

- **Groq daily quota (200k tokens) is shared** by the live service and every eval run; a heavy eval day can starve
  live analyses (they then fall back to the rules baseline and say so in the guard notes).
- **Free Render cold starts** (about 50 s after 15 idle minutes); a webhook that arrives while it sleeps may time out
  (PayPal retries; repeating an analysis is harmless).
- Render also has `NVIDIA_API_KEY` and `REBUTTAL_MODEL` set although the blueprint does not list them; check
  `REBUTTAL_MODEL` is still a `claude-*` name or empty, because any other value is read as the NVIDIA model name.
- Sandbox accounts: buyer `sb-medfn53234339@personal.example.com`, business `sb-g0sby53230819@business.example.com`.
- One incomplete Langfuse (cloud, US) experiment in dataset `rebuttal-disputes-holdout` (7/10): ignore it.
- Sandbox buyer logins expire often; Manish types the passwords.
