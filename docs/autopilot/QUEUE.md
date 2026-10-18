# Autopilot task queue

Ordered. The lead takes the first runnable task each cycle (see `CYCLE.md`). Status: `todo`, `in-progress`,
`waiting: <why>`, `done <PR>`. Sizes: S (under an hour of agent work), M, L (split into several PRs). A large task
may carry an explicit share done as `[NN%]` in its status. `docs/autopilot/progress.py` turns this file into the
project completion percent (CYCLE.md section 7).
Deadlines: video script Oct 12, AG Studio first pass and demo-video rough cut Oct 23, **feature freeze Nov 3**,
final check Nov 8, Manish submits Nov 10 (hard deadline Nov 12, 12:00 PM PT).

## Tasks

### R1 Stop mock mode from writing to the live Supabase database — size S — done #55 (DB cleanup of stray PP-D-2000 rows left undone: shared live database, not needed for live behaviour) — audit Oct 14, priority now
Evidence: backend/rebuttal/config.py:66-67 sets checkpoint_target from any postgres DATABASE_URL, and line 86 sets database_url, both regardless of `mock`. _load_dotenv reads backend/.env, which holds the live DATABASE_URL, and REBUTTAL_MOCK defaults to 1. So a plain `uv run uvicorn rebuttal.app:app` or any ad-hoc script stores mock proposals and audit rows (ids PP-D-2xxx) in the database the live Render service uses. The reviewer's probe left rows for PP-D-2000, including one APPROVED proposal. app.py:61 only requires a token in that case; it does not stop the writes. Fix: when settings.mock is true, set database_url=None and checkpoint_target=None unless REBUTTAL_CHECKPOINT_URL is set explicitly. tests/live_postgres.py must keep working, so give it an explicit opt-in if it needs one. Acceptance: (1) a new test shows that with REBUTTAL_MOCK=1 and DATABASE_URL=postgresql://x, load_settings().database_url and .checkpoint_target are both None; (2) the same with REBUTTAL_MOCK=0 and real-looking keys still gives the postgres target; (3) update the persistence.py docstring and docs/deploy.md; (4) delete rows with dispute_id or thread_id 'PP-D-2000' from rebuttal_audit and the checkpoint tables, using a read-first query and logging the counts. If the autopilot may not write to the shared database, leave this step to Manish.

### Q1 Deterministic quality gates in CI — size M — done #18
Catch basic mistakes without spending model usage. Add to `.github/workflows/tests.yml` (all free):
- Secret scan of every push and PR with gitleaks (free for personal accounts; `gitleaks/gitleaks-action@v2` or the
  gitleaks binary), with an allowlist only for the vendored skill examples if needed.
- Backend lint with `ruff check` (add `ruff` to the `dev` dependency group with `uv add --dev ruff`, a minimal
  `[tool.ruff]` config in `backend/pyproject.toml`; fix what it flags in the same PR, do not disable rules wholesale).
- Frontend: confirm `npm run build` (already `tsc -b && vite build`) and `npm run lint` stay in CI; add `tsc --noEmit`
  for the e2e folder if it is not covered.
- GitHub security and supply-chain scanners, all free for public repos: CodeQL (Python + JavaScript), OSV-Scanner,
  OpenSSF Scorecard (badge in README), Dependabot alerts config; coverage report for the backend (pytest-cov) with
  the number in README.
- A test that every environment variable read by the backend (`os.getenv` / `os.environ`) is listed in
  `backend/.env.example` or explicitly allowlisted.
Done when CI runs the new jobs on the PR and they pass.

### Q2 Architecture decision records — size S — done #25
`docs/adr/`: short ADRs (context, decision, consequences) for the safety design: single PayPal write path in
`execute`, read-only client for analysis, human approval via LangGraph interrupt, facts in code + guard over the model,
deterministic PayPal-Request-Id, Supabase over paid Postgres, held-out evals. Link them from README. (Competitor Stood
shows 24 ADRs; judges score Technological Implementation first in ties.)

### Q3 PayPal Agent Toolkit in the agent (read-only) — size M — done #28
Result: the official package cannot be used strictly read-only (langchain pin conflict, `run()` dispatches any tool, `requests` bypasses our transport, no `fields=all`), so `agent/toolkit.py` is a four-tool read-only adapter in the toolkit's tool shape and `gather` reads through it; see ADR 0008.
PayPal promotes its AI Toolkit / MCP server for this hackathon. Use the PayPal Agent Toolkit (Python package, check
the paypal plugin and https://developer.paypal.com for the current package and dispute/transaction tools) for the
agent's read-only lookups in `gather_facts` (show dispute, list transactions), behind the existing read-only boundary:
the toolkit must only be given read tools, and `execute` stays the only writer. Tests prove no write tool is
reachable from analysis. Document it in README and `docs/prize-fit.md`. Log any APIMatic plugin help in
`docs/apimatic-log.md`.

### Q4 Real-sandbox dispute creation for the judge path — size M — done #42 (body VERIFY until first live run) (U1 done Oct 9: buyer business account sb-mku4z53114841@business.example.com, keys in backend/.env, token verified with disputes + checkout scopes)
Create test disputes through the Disputes API with a second sandbox business account acting as buyer (it owns its own
REST app; personal accounts cannot). Script `backend/scripts/make_sandbox_dispute.py` (order -> capture -> create
dispute -> webhook arrives), credentials from `backend/.env` (`PAYPAL_BUYER_CLIENT_ID` / `_SECRET`, added to
`.env.example`). Replaces the password-based buyer steps (supersedes B5).

### S1 APIMatic plugin in every PayPal change — size S — done (first pass, no drift found); standing rule stays
Sponsor research (Oct 9): the APIMatic Context Plugin for the PayPal Server SDK is free and installed, but
`docs/apimatic-log.md` is empty, so we have no evidence of use. From now on every task that touches PayPal calls,
the mock or the client asks the plugin first and logs each use there (date, question, answer, what changed, PR).
First pass now: use it to check our Disputes calls and mock shapes against the SDK models, fix any drift, log it.

### S2 More of the Disputes API — size M — done #69 — after Q4
Strengthens Best Use of PayPal + AI. Add the appeal and escalate paths and more evidence types (proof of
fulfillment, refund, return tracking), each proposed by the agent and executed only by `execute` after approval,
with deterministic `PayPal-Request-Id`, mock parity and tests. Look up shapes with the paypal plugin and APIMatic
(log in `docs/apimatic-log.md`). Sandbox-only flows (`require-evidence`) only in the named manual scripts.

### A1 Keep the live backend awake (free) — size S — done #6
GitHub Actions workflow `keep-render-awake.yml`: `curl` `https://rebuttal-oq3g.onrender.com/api/health` every
10 minutes (public repo, so Actions minutes are free; one free Render service running 24/7 fits the 750 free hours a
month). This replaces the planned paid Render plan. Done when the workflow is merged and its first run is green.

### A2 Held-out eval — size S — done (this PR): model alone 80%, final 100%, results in `backend/evals/RESULTS.md`
`cd backend && uv run python -m evals.run --set holdout --provider groq --langfuse --save`. Report model-alone vs final
accuracy and the per-case misses in `docs/evals.md` (create it, include the main-set numbers from `STATUS.md`) and in
`STATUS.md`. **Change no agent code because of the result.** If Groq returns 429 (daily quota), mark
`waiting: Groq quota until <time>` and move on; retry next day.

### A3 Frontend follow-ups from the PR #3 review — size M — done #9
- Delete the unused Vite scaffold (`frontend/src/assets/`, `frontend/public/icons.svg`, unused CSS).
- Register only the AG Grid modules in use instead of `AllCommunityModule` (`ag-mcp` for module names); report the
  bundle size before and after.
- After a non-409 error, close the confirm dialog or disable "Approve and send" when the refreshed proposal is no
  longer PENDING.
- Retry dialog shows the approved text: expose the approved message in the proposal API (backend change, additive,
  with a test), and add an end-to-end test for the retry path.
- Make `npm run build` fail if `VITE_API_TOKEN` is set for a production build.

### A4 Video script — size S — done (on main, docs/video-script.md) — deadline Oct 12
`docs/video-script.md`: under 3 minutes, built from `docs/pitches.md`. One hero case (`agent_wrong_size`), two
cutaways, the eval number on screen. Columns: time, what is on screen (exact UI state or terminal), narration text,
which judging criterion it serves (Tech, Design, Impact, Innovation, Presentation). Include a shot list the
automated recorder (B4) can follow step by step.

### A5 Dashboard on the live service with a login — size M — merged #39; done #39; live `/` returns 200 and health ok (checked Oct 10)
Serve the built frontend from the FastAPI app on the existing Render service (same origin: no CORS, no new Render
resource, no cost). Replace `VITE_API_TOKEN` with a sign-in screen where the merchant pastes the API token; keep it in
`sessionStorage`, never in the bundle. Update `render.yaml` build to also build the frontend (check Node is available
in Render's Python runtime; if not, find a free alternative and document it). Done when
`https://rebuttal-oq3g.onrender.com/` shows the sign-in screen after deploy and a Playwright test covers sign-in.
The sign-in screen must also show a "Try the demo" link (`href="#demo"`): `DemoApp` needs no token, so judges reach it
without one. `VITE_API_TOKEN` must never be set in a public frontend build.

### A6 Judge demo mode — size M — done #33 — priority now (rules: judges must be able to try it; testing credentials go in the submission)
Judges must be able to try Rebuttal without PayPal accounts. Add a demo mode on the same service: a "Try the demo"
button that runs the hero case and the other demo cases against the in-memory mock sandbox in a separate, isolated
runtime (no access to the real sandbox client, never writes to PayPal, resets itself). The real-sandbox inbox stays
behind the token. Reviewer must confirm the isolation. Document it in the README.

### A7 Approve dialog closes at once under `npm run dev` — size S — done
Found by the A4 dry run: in the Vite dev server the Approve confirm dialog closes immediately (likely a React
StrictMode double-effect in `frontend/src/components/ConfirmDialog.tsx`); the production build is fine. Reproduce with
a Playwright test against the dev server, fix the effect, keep StrictMode on.

### A8 Re-run the main eval on current code — size S — done Oct 14 (final 95%, model alone 75%, run groq-qwen3.8-27b-20261014-001228) — after Oct 11 (Oct 10 Groq run used by B3)
The 90% main-set number predates guard rule `f4cb66d`. Run `uv run python -m evals.run --provider groq --langfuse --save`
once (respects one Groq eval per day), update `backend/evals/RESULTS.md`, `STATUS.md` and the eval card in
`docs/video-script.md`. Change no agent code because of the result. A8 must run on a different day than the holdout2 Groq run (B3), so the
two do not share one day's Groq quota.

### B1 AG Studio dashboard, first pass — size L — done #52 (part 1 #16, part 2 #48, part 3 Agent Framework #52) — deadline Oct 23
Main sponsor prize. Use the `ag-dev` skill and `ag-mcp` for AG Studio APIs in the installed version. Analytics view:
disputes by reason and by product, money kept vs refunded, response deadlines, model-vs-final agreement from the
audit log. Custom widgets and a theme matching `preview/`. New read-only backend endpoints for the aggregates (with
tests). Split into PRs: data endpoints, Studio layout and theme, custom widgets.

### B2 AG Studio depth — size L — done #70 (saved views, starters e2e, licence note, 10 widget screenshots, live Groq smoke pass 505 ms) — needs B1
Studio Agent Framework: plain-English questions over the dispute data ("which products cause most disputes this
month?"), using Groq free tier, read-only data access only (assistant + read-only proxy done #52; left: one live
Groq smoke check of the assistant, prompt starters showing, AI module licence note). Saved views. Playwright screenshots of every widget into
`docs/screenshots/`.

### B3 More evals — size M — done (holdout2 run Oct 10: final 100%, model alone 80%; this PR)
Grow to about 40 cases: 10 more held-out cases written by a subagent that is **not allowed to read**
`agent/facts.py`, `agent/reasoner.py` or `agent/llm.py` (give it only `cases.json` format and the dispute types).
Run once on Groq (respect the one-run-per-day rule). Update `docs/evals.md`.

### B4 Automated demo video — size L — in-progress [90%] (#68 merged) (part 1 #66 one-command rough cut; part 2: Analytics segment, live-proof card, 2:50; left: USER review and upload) — after A4, B1 — rough cut deadline Oct 23
Free tooling only: Playwright records the browser (video) following the A4 shot list in demo mode; narration from
the A4 script via macOS `say` (pick a natural voice, export AIFF); `ffmpeg` (`brew install ffmpeg`) joins them,
adds captions and title cards. Output `media/rebuttal-demo.mp4` (git-ignored; keep the script and the build command
`scripts/make_video.sh` in git). Under 3:00. Then add a USER item: watch it, optionally re-record the narration in his
own voice (give exact steps), and upload to YouTube as Public.

USER: (1) Watch media/rebuttal-demo.mp4 (open it in QuickTime; run scripts/make_video.sh first if the file is missing). Check the Analytics segment (about 1:36) and the live-proof card (about 2:23) read right and nothing is cut off.
(2) Optional, a better voice: VIDEO_VOICE="<name>" scripts/make_video.sh (list the voices with `say -v ?`). Own voice is not wired: make_video.sh always writes the narration with `say`, and the shot hold times follow the narration length, so a dropped-in audio file would not line up. If you want your own voice, record each caption from docs/video-script.md section 7 and send the files in chat; the lead wires an own-voice option.
(3) Upload to YouTube as Public: go to studio.youtube.com, click Create (top right) > Upload videos > Select files, choose media/rebuttal-demo.mp4; title "Rebuttal: a PayPal dispute agent that waits for your approval"; description from docs/devpost.md; under "Audience" choose "No, it is not made for kids"; click Next three times; on Visibility choose Public and click Publish; copy the link into the Devpost form.
(4) Say done in chat.

### B5 Sandbox simulator for judges — size M — superseded by Q4
Research (PayPal plugin, docs) whether a test dispute can be created on the real sandbox without a buyer password.
If yes, add it to the simulator in sandbox mode. If it needs a buyer login, make it a USER item with exact steps and
skip the code.

### E1 Second submission decision — size S — done (go: Mandate, separate repo and routine, docs/second-entry.md)
Rules allow several substantially different submissions, each winning up to one Grand/Honorable + one Sponsor
prize. Only if Rebuttal's queue is on track: scope a second, different entry aimed at Bryntum ($1,000 x3) or Channel3
($1,500) plus one honorable mention, reusing nothing user-visible from Rebuttal. Write `docs/second-entry.md` with
the idea, effort and a go/no-go; go only if it fits before Nov 3 without slowing Rebuttal.
Sponsor research (Oct 9): Bryntum ships free `-trial` npm packages (no card) but the trial is 45-60 days and
"evaluation only, not production"; judging runs to Dec 15, so verify the trial terms (or ask Bryntum on Discord via a
USER item) before choosing it. Channel3 has a free MCP tier (product catalog search), weak fit for disputes.

### C1 Design polish — size M — done #73 — after B1
`frontend-design` skill pass over inbox, case view and Studio: typography, spacing, empty and loading states,
keyboard access, accessible contrast; Playwright screenshots before/after in the PR.

### C2 README and submission docs — size M — done (this PR)
README: what it is, 60-second judge quickstart (demo mode link + local run), architecture diagram (Mermaid), safety
design (single write path, guard, approval), eval table, how each sponsor tool is used (AG Grid/Studio, APIMatic with
`docs/apimatic-log.md`, PayPal APIs), license. Draft `docs/devpost.md` (every Devpost field) and
`docs/discord-preview.md` (short post asking for judge-style feedback). Prepare the APIMatic form answers.

### C3 Discord preview — size S — done (this PR) — after C2 and A5 — target Oct 23
Make the USER item: post `docs/discord-preview.md` in the AG Grid and general channels (exact steps). Do not post.

### D1 Feature freeze — Nov 3
From Nov 3 only fixes, docs, video. Move any unfinished feature task to `## Cut` with one line why.

### R13 Early final-check dry run — size M — todo — priority now (banked reset week, Oct 18-20)
Run the D2 checklist now, minus the video and Devpost items, so problems surface before the Nov 3 freeze: gitleaks
over the whole history, every README link, CI green, live health ok, judge demo mode from a fresh browser (Playwright,
no console errors), the documented judge commands leave the tree clean. Fix what fails in small PRs; record results
in STATUS.md. D2 still runs after Nov 7.

### D2 Final check — size M — after Nov 7
Secret scan of the whole git history (`gitleaks` via Homebrew or `trufflehog`), license file, all links in README
work, CI green, live health ok, demo mode works from a fresh browser, video under 3:00, Devpost draft complete. Then
send one alert with the final USER checklist (upload video, submit Devpost, APIMatic form) for Nov 10.

### D3 Learning pack — size M — after D2
Manish wants to learn at the end. Update the local `LEARNING.md` (never commit it): one section per merged PR since
PR #3 (what, why, how, Mermaid where useful, ELI5), a glossary, and the 10 interview questions a PayPal engineer
would ask with model answers.

### D5 Submitted on Devpost — size M — waiting: Manish submits Nov 10
Done when Manish confirms the Devpost submission (video uploaded, repo link, testing credentials, APIMatic form). The
lead marks it done only on his word in chat or a LOG.md note from him; this is the last step to 100%.

### D4 Post-hackathon reminder — Dec 22
Alert: delete the Render service (judging ends Dec 15). Do not delete it yourself.

### R2 Guard: rules fallback must pass the PayPal-allowed and policy checks; handle a missing merchant order — size M — done #65 — audit Oct 14, priority next
Evidence: (1) In reasoner.py:276-288, fallback() returns RuleReasoner().decide(case) directly, so the paypal_allows() / PAYPAL_ALTERNATIVES step (reasoner.py:327), the cannot_prove_delivery conversion and the damage threshold never run on the replacement. Example: on a NOT_RECEIVED dispute where only REFUND is allowed, an unknown resolution falls back to OFFER_REPLACEMENT, which PayPal will refuse at execute. (2) _compute_facts returns early when order is None (facts.py:184-186), leaving has_tracking and refund_issued unset. RuleReasoner._pick (reasoner.py:120, 159, 152) then proposes ACCEPT_CLAIM: 0.85 'No tracking on file' for NOT_RECEIVED, 0.75 'No refund on file' for CREDIT_NOT_PROCESSED, 0.6 for UNAUTHORISED. This hits every live dispute whose invoice is not RB-<case>-<n>. (3) Nit in the same file: _pick re-derives damage from the last message and from case.amount instead of using facts.buyer_reports_damage and refund_without_return_eligible. Fix: in fallback(), set the notes on base, then `return guard(base, case)`. This cannot loop, because rules only pick SHARE_TRACKING when there is tracking and SUBMIT_REFUND_PROOF when a refund exists. In _pick, when facts.order_found is false, return SUBMIT_EVIDENCE at confidence <= 0.3 with 'No merchant order record; needs merchant review'. Also add a guard rule that caps confidence and adds a note for ACCEPT_CLAIM or OFFER_REPLACEMENT when order_found is false. In _pick, use buyer_reports_damage and refund_without_return_eligible. Acceptance: new tests fail on the old code. They cover a guard fallback with allowed_response_options=['accept_claim'] on NOT_RECEIVED, giving a PayPal-allowed resolution; order_found False for NOT_RECEIVED, CREDIT_NOT_PROCESSED and UNAUTHORISED, giving no ACCEPT_CLAIM above 0.3; and damage reported in the claim notes plus a follow-up message. Do not retune against holdout.json or holdout2.json. Re-run evals and report any change. Also (Opus review of #63, Oct 14): at stage CHARGEBACK with allowed_response_options missing, effective_options returns None so paypal_allows says yes to everything; return False for make_offer resolutions at CHARGEBACK and add a test.

### R3 Duplicate-charge fact: match the invoice and successful status only — size S — done #58 — audit Oct 14, priority next
Evidence: facts.py:226-233 counts every transaction with the same buyer email and amount, ignoring transaction_info.invoice_id and transaction_status. A second legitimate same-price order, or a denied attempt, sets duplicate_charge_found True, and the rules then propose ACCEPT_CLAIM at 0.9. holdout.json ho_duplicate_two_orders seeds only one transaction, so it never tests this. Fix: count only transactions with transaction_status == 'S' and, when present, invoice_id == order.invoice_id. Check that the mock (paypal/mock.py) and scenarios.py transaction shapes include both keys, and mirror the real Transaction Search shape. Acceptance: unit tests cover a different invoice (duplicate False), a denied 'D' transaction (False) and two 'S' transactions on the same invoice (True). Evals stay at or above the current main-set accuracy. Do not edit held-out labels to fit.

### R4 Verify the PROOF_OF_REFUND evidence_info.refund_ids shape against PayPal — size S — done #61 — audit Oct 14, priority next
Evidence: pipeline.py:130-131 sends evidence_info.refund_ids as a list of strings. As far as I recall, PayPal's provide-evidence schema defines refund_ids as an array of objects ({"refund_id": "..."}), like tracking_info. No VERIFY note exists, and the mock does not validate evidence shape, so tests cannot catch this. A wrong shape fails at execute, after the human has approved. Fix: check the schema with the paypal-sandbox MCP (read-only lookup) or the APIMatic PayPal SDK skill, and log the APIMatic use in docs/apimatic-log.md. If objects are required, send [{'refund_id': id}], make mock.py reject the string form with a 400 INVALID_REQUEST like the real API, and add a plan_actions test plus a mock rejection test. Otherwise add a VERIFY note at pipeline.py:131 and in mock.py. Acceptance: the shape is cited from the docs or the SDK model, and a test pins it.

### R5 API hardening: webhook and analyze never return a bare 500 — size S — done (this PR) — audit Oct 14, priority next
Evidence (reproduced at 40518cf with the database blanked, TestClient): POST /api/webhooks/paypal with body b'notjson' returns 500; with {event_type: CUSTOMER.DISPUTE.CREATED, resource: null} returns 500; POST /api/disputes/NOPE/analyze returns 500 (PayPalError 404 not caught). app.py:259 calls `await request.json()` unguarded, and :272 calls `event.get('resource', {}).get`. analyze (:136) and list_disputes (:130) do not catch PayPalError or httpx.TransportError, unlike _analytics_rows (:212). Fix: wrap the JSON parse and return 400; reject a non-dict body with 400; use `resource = event.get('resource') or {}`. In analyze and list_disputes, map PayPalError to 404 when the status is 404 and to 502 otherwise, map TransportError to 502, and log status and debug_id. Also change the sandbox simulator 501 text 'lands in week 2' (app.py:301) to 'The simulator only runs against the mock sandbox.' Acceptance: new tests cover non-JSON, a JSON list and a null resource (4xx or 200, never 500); analyze on an unknown id (404) and a PayPal 5xx or transport error (502); webhook verification raising ConnectError (503, no analysis); a verified CUSTOMER.DISPUTE.UPDATED (200, no proposal); health with ping raising (ok False, database False); and the sandbox-mode POST simulator returning 501.

### R6 Case view deadline: compute live from the server clock, show Overdue — size S — done #59 — audit Oct 14, priority next
Evidence: CaseView.tsx:167 shows summary.hours_left, which is frozen at analysis time (facts.py:169, pipeline.py case_summary). On the live service a proposal left overnight still shows the old hours, and labels.ts clamps negative values to 0, giving '0h left to respond'. Cross-component caution: the reviewer's fix (Date.parse(summary.due) - Date.now()) would break the judge demo, because mock and demo mode use a frozen clock (runtime.py:44 `self.clock = lambda: DEMO_NOW`, scenarios.py:18 DEMO_NOW = 2026-10-06), so every demo case would read Overdue. Fix: compute hours_left at read time on the server with rt.clock(), for example in the /api/disputes and proposal to_dict paths, or return a server 'now' and have the frontend use it. Render 'Overdue' for negative values. Acceptance: a backend test checks that hours_left follows the clock after analysis; e2e tests show the demo hero case with a positive hours pill and a mocked past due date showing 'Overdue'.

### R7 Frontend robustness nits: reasoner row, failed inbox load, audit step labels, widget field mapping — size M — done #64 — audit Oct 14, priority later
Evidence: (a) CaseView.tsx:112 falls back to decision.resolution while the audit has not loaded, so the 'Reasoner' row shows the guarded choice. Show a placeholder instead. (b) Desk.tsx:89: if the first GET /api/disputes fails, the inbox shows 'Loading disputes…' forever. Add a failed state with a Retry button. (c) AuditTrail.tsx:9 has no case for execute_failed or execute_interrupted, so it prints raw JSON. Add readable text, and assert it in the interrupted-call e2e test. (d) DeadlineListWidget.tsx:53 and AgreementWidget index into fieldsets without length checks, so a remap in Studio edit mode throws and unmounts the app. Use setDisplayState('incompleteDataMapping') and add an error boundary. (e) frontend/.gitignore:28 mentions .env.example, but none exists. Add frontend/.env.example with commented VITE_API_BASE and VITE_API_TOKEN. Acceptance: npm run lint, npm run build and npx playwright test all pass, with a new assertion for (b) and (c).

### R8 Fix stale agent brief and status docs (CLAUDE.md, STATUS.md, deploy.md, PLAN.md) — size S — done #60 — audit Oct 14, priority next
Evidence: CLAUDE.md:104 lists 'Frontend (frontend/, none yet)' and the AG Grid dashboard as next tasks, but both have shipped. The Layout block omits frontend/, analytics.py, studio_ai.py and agent/toolkit.py. STATUS.md:93 says 398 backend tests (actual 469 passed) and 29 Playwright tests (about 43 test() calls). STATUS:8 says 44% (progress.py prints 58%). STATUS:15 says Q4 'PR open' (it merged as #42). STATUS:114 and PLAN.md plan a paid Render plan, while docs/autopilot/QUEUE.md says A1's keep-render-awake.yml replaced it. deploy.md:125 says the keep-alive does not keep Render awake, but .github/workflows/keep-render-awake.yml exists. deploy.md:115 still calls Node on Render unverified, yet the live root serves the Vite build. Fix: point 'Next, in order' at QUEUE.md and update the Layout; correct the counts, percentages and merge state; make deploy.md, PLAN.md and STATUS agree on Render (best-effort 10-minute ping, no paid plan unless Manish decides otherwise); mark the Node build as verified. Acceptance: running `uv run pytest -q` and `npx playwright test --list` gives the counts quoted in the docs, and the docs contain no contradictory Render plan. CLAUDE.md is the project brief, so keep the change limited to facts.

### R9 README judge path: make the documented commands leave the git tree clean — size S — done #62 — audit Oct 14, priority next
Evidence: the README's 'Backend only' commands rewrite tracked files. `uv run python -m evals.run --rules` rewrites backend/evals/RESULTS.md (run.py:269-271) and adds evals/results/*.json. `uv run python -m scripts.demo` rewrites backend/preview_data.json. The run.py:279 --only help says results are overwritten, but a partial run writes nothing. The README says 93% coverage while `pytest --cov --cov-branch` gives 94%. README.md:216 credits the held-out guard change with OFFER_RETURN_FOR_REFUND only, but ho2_inr_nothing_shipped became ACCEPT_CLAIM through cannot_prove_delivery. README.md and frontend/README.md give different backend start commands. frontend/README.md does not say Playwright needs ports 8000, 4173 and 5174 free (reuseExistingServer is false). Fix: add a --no-save flag, or make --rules print only unless --save is given, and document it. Fix the --only help, the coverage number and the held-out sentence; use one backend start command in both READMEs; add the note about free ports. Acceptance: after the README quickstart commands, `git status --short` is clean.

### R10 Approval/audit and mock fidelity nits — size M — done #72 (part 1 items a, e: #71; part 2 items b, c, d: #72) — audit Oct 14, priority later
Evidence: (a) approval.py:177 logs 'approve' on every execute attempt, so after approve, a 503 and a retry the audit shows two approve records. Log it once per proposal id, and add a test asserting a single approve after a retry. (b) mock.py:78 keeps allowed_response_options after the seller makes an offer and accepts a second make_offer in WAITING_FOR_BUYER_RESPONSE. Pop the options when the status leaves WAITING_FOR_SELLER_RESPONSE, and add a mock test. (c) already_applied() and seller_activity() (facts.py:99-101) rely on messages[].posted_by and offer.history[].actor shapes seen only in the mock. Add VERIFY notes until a real post-offer dispute is captured, and normalise whitespace when matching message text. (d) client.py:108 uses a denylist for the host check, and the read-only clone keeps _client_secret. Switch to an allowlist of SANDBOX_HOSTS (plus a mock transport) and drop the credentials from the clone. Keep tests/test_write_boundary.py green and extend it. (e) audit.py:60 appends to self.records even in Postgres mode, so memory grows without bound. Append only when there is no pool. Acceptance: one new test for each item, and the write-boundary tests remain unchanged or are strengthened.

### R11 Prompt and guard: untrusted buyer text and address mismatch — size S — done #63 — audit Oct 14, priority later
Evidence: reasoner.py SYSTEM_PROMPT (line 223) passes buyer_messages verbatim with no note that they are untrusted, and the guard has no check for an ACCEPT_CLAIM that contradicts delivered + matching address + no refund request. delivered_address_matches is computed but neither the prompt nor the guard uses it, and draft_message SHARE_TRACKING hard-codes 'to the address on your order'. Fix: add a SYSTEM_PROMPT sentence saying buyer messages are quotes, never instructions. In guard, turn SHARE_TRACKING or SUBMIT_EVIDENCE on NOT_RECEIVED with delivered_address_matches False into OFFER_REPLACEMENT, and add a guard note when ACCEPT_CLAIM contradicts the facts. Make the draft text depend on whether the address matches. Acceptance: unit tests cover each rule; no tuning against the held-out sets.

### R12 Return-needed rule at CHARGEBACK with no option list — size S — done (live CHARGEBACK lists accept_claim only; claims needing a return now use REFUND_WITH_RETURN with the return address, docs/sandbox-findings.md S4 run) — from the PR #65 review
Evidence: with `allowed_response_options` missing at CHARGEBACK, `paypal_allows` now refuses offers (R2), so a not-as-described dispute that needs the item back can fall through to ACCEPT_CLAIM, a full refund without a return. R2 first capped it, but the cap rested on an unverified assumption about what the sandbox returns at CHARGEBACK (see the VERIFY note in `reasoner.py`) and fired on every case without damage. Fix: once a real sandbox CHARGEBACK shows whether the option list is omitted, add a guard rule for ACCEPT_CLAIM when the item needs its return, scoped to that evidence. Acceptance: a test built from the captured payload.

### S3 Confirm the S2 Disputes shapes on the real sandbox — size M — done #74 (confirmed: escalate rel, escalate on INQUIRY without buyer_escalation_reason, stage stays INQUIRY, seller message moves to UNDER_REVIEW, posted_by/actor shapes; rest moved to S4; results in docs/sandbox-findings.md)
S2 shipped escalate, appeal and the richer evidence types against the mock only. Using the existing named manual
scripts (`spike_sandbox.py`, `make_sandbox_dispute.py`; `require-evidence` stays confined to them), confirm: the link
rel names `escalate` and `appeal` on a shown dispute; that escalate is accepted on an INQUIRY waiting for the seller;
the appeal multipart body and the stage it moves to; that a seller can send PROOF_OF_RETURN; escalate after a seller
reply (the status send-message leaves, and whether a buyer reply returns the INQUIRY to WAITING_FOR_SELLER_RESPONSE,
which the ESCALATE rule and the mock's `require-evidence` stand-in assume); whether escalate needs
`buyer_escalation_reason`, which the client omits. Fix the mock and the
client together and remove the matching `VERIFY` notes (`client.py`, `mock.py`, `facts.py`, `approval.py`).

### S4 Remaining sandbox confirmations from S3 — size S — [60%] waiting: CHARGEBACK options and accept-with-return confirmed Oct 15; still needs an appealable (lost) case (sandbox adjudicate refused) and a buyer reply on a dispute the buyer app owns
Left STILL UNVERIFIED by S3 (#74, see `docs/sandbox-findings.md`): the `appeal` rel, multipart body and next stage; PROOF_OF_RETURN acceptance (refused on a NOT_RECEIVED inquiry; try a NOT_AS_DESCRIBED one); whether a buyer reply returns the INQUIRY to WAITING_FOR_SELLER_RESPONSE; whether escalate removes its link (retry safety note in `approval.py`); `allowed_response_options` at CHARGEBACK (unblocks R12). Also the review nits from #74: VERIFY note for mock escalate in WAITING_FOR_BUYER_RESPONSE (`mock.py:300-305`) and `body.get("note")` in the mock escalate branch. Use `scripts/spike_shapes.py` only. Fix mock and client together, remove VERIFY notes only with a fixture.

## USER

Things only Manish can do. Each with exact steps; the lead adds them here and alerts at most once a day.

- **U3 Demo video review and upload** (ready Oct 14, from B4): follow the four USER steps under B4 above: watch `media/rebuttal-demo.mp4` (run `scripts/make_video.sh` first if missing), optionally pick a better `say` voice, upload to YouTube as Public, then tell the lead "U3 done" with the link.

- **U2 APIMatic form and Discord preview**: ready on Oct 23 (after C3). Inputs are ready: `docs/apimatic-form.md` (answers for the APIMatic form) and `docs/discord-preview.md` (the posts, sections A and B).
  0. Before step 1, take 2-3 screenshots (or a short clip from `media/rebuttal-demo.mp4`) of the AG Studio Analytics tab in the signed-in dashboard; post A asks about it and the public demo does not show it.
  1. Discord, AG Grid channel: in the hackathon's Discord server (use the invite link from the Devpost page; the repo does not name the server or its channels), open the AG Grid sponsor channel. Paste section A of `docs/discord-preview.md` (the text under "## A. AG Grid channel", without the heading) and attach the screenshots from step 0, then post it.
  2. Discord, general channel: open the general feedback channel, paste section B (the text under "## B. General channel") and attach the screenshots from step 0, then post it.
  3. Tell the lead "U2 Discord posted" once both posts are up.
  4. APIMatic form: open the APIMatic form link from the hackathon's sponsor resources (the repo does not record the form URL). Check its questions against `docs/apimatic-form.md`, which was written for generic questions.
  5. Paste the answers from `docs/apimatic-form.md`: "How did you use the APIMatic Context Plugin?", "What did it not help with?", "Links to evidence", and the "Short answer" if the form has a small text box. Skip "Note for Manish" and "Before you submit".
  6. Replace `<YouTube link, added by Manish>` in "Links to evidence" with the video link, or leave that line out if there is no video yet.
  7. Separately, submit the free-subscription claim form (link in `docs/apimatic-log.md`) yourself if you want the free plan. It is not the prize form.
  8. Submit the APIMatic form yourself, then tell the lead "U2 done".

- ~~**U1 Second sandbox business account**~~ done Oct 9. Original steps kept for reference: developer.paypal.com > log in > Testing Tools >
  Sandbox Accounts > Create account > Business, United States > Create. Then Apps & Credentials (Sandbox) > Create App
  > name "rebuttal-buyer" > Merchant > pick the new business account > Create. Copy the Client ID and Secret into
  `backend/.env` as `PAYPAL_BUYER_CLIENT_ID=` and `PAYPAL_BUYER_CLIENT_SECRET=` (never paste them in chat). Then tell
  the lead "U1 done".

## Cut

- Render paid plan: replaced by A1 (no spending).
- Bryntum: backup only; dropped unless everything else is done before Oct 30.
- Elastic retrieval: optional; dropped unless everything else is done before Oct 30.
- Ticking "Transaction search" in the PayPal app: account setting, not needed.
