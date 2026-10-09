# STATUS

Read this at the start of a session; update it at the end of every task. Last updated: Oct 9, 2026 (branch `fix/frontend-followups`:
PR #3 review follow-ups, on top of `6597e0b`). Detail: `docs/handoff-2026-10-07.md`, `PLAN.md`, `docs/deploy.md`.

**Autopilot:** an unattended lead-dev session works through `docs/autopilot/QUEUE.md` every 3 hours; see
`docs/autopilot/README.md`. Progress: `docs/autopilot/LOG.md`.

## Where we are

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
- **Frontend slice 1 (merged, PR #3; follow-ups in `fix/frontend-followups`):** `frontend/` is Vite + React + TS with an AG Grid
  Community inbox (only the five grid modules it uses; JS bundle 1,399 kB -> 996 kB, gzip 398 -> 288 kB), case view
  (assistant instruction vs shipped, facts, reasoner choice vs final action, guard note, editable message), approve / edit /
  reject behind a confirm dialog that states the exact PayPal call, audit timeline, and a mock-only simulator. After a
  failed call the dialog stays readable but its button is disabled once the proposal is no longer pending. An
  approved-but-interrupted case shows the approved text (the merchant's edit) and the retry dialog states it.
  `npm run build` refuses `VITE_API_TOKEN` (see `frontend/README.md`). Built and tested with `REBUTTAL_MOCK=1 REBUTTAL_REASONER=rules`,
  no model key, no real sandbox, no Supabase. 7 Playwright tests run in CI (hero approve-with-edit, reject, 409, cancel,
  interrupted call then retry, 2 build-guard); run commands: `frontend/README.md`.
  Backend changes (additive): CORS from `REBUTTAL_CORS_ORIGINS`, `GET /api/simulator/cases` (mock only),
  `approved_message` on the proposal payload (read from the approval record; execute unchanged), a JSON 502 when PayPal
  fails during approve or retry (was a bare 500 that cross-origin browsers cannot read), and mock-only
  `POST /api/simulator/interrupt-next-write` (the next PayPal write is applied, then answered 503, for the retry test).
- **Tests:** 180 pass (173 + 3 for `approved_message` + 4 for the 502 and the interrupt hook); the PayPal write boundary (only `approval.py`'s `execute`) is enforced by tests.

## Next, in order

1. Autopilot queue: `docs/autopilot/QUEUE.md` (source of truth for what is next).
2. Frontend slice 2: AG Studio dashboard (custom widgets, theming), Render static site, point the dashboard at the
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
