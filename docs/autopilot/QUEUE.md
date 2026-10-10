# Autopilot task queue

Ordered. The lead takes the first runnable task each cycle (see `CYCLE.md`). Status: `todo`, `in-progress`,
`waiting: <why>`, `done <PR>`. Sizes: S (under an hour of agent work), M, L (split into several PRs).
Deadlines: video script Oct 12, AG Studio first pass and demo-video rough cut Oct 23, **feature freeze Nov 3**,
final check Nov 8, Manish submits Nov 10 (hard deadline Nov 12, 12:00 PM PT).

## Tasks

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

### Q2 Architecture decision records — size S — in review (branch docs/adr)
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

### S1 APIMatic plugin in every PayPal change — size S — first pass done (this PR, no drift found); standing rule stays
Sponsor research (Oct 9): the APIMatic Context Plugin for the PayPal Server SDK is free and installed, but
`docs/apimatic-log.md` is empty, so we have no evidence of use. From now on every task that touches PayPal calls,
the mock or the client asks the plugin first and logs each use there (date, question, answer, what changed, PR).
First pass now: use it to check our Disputes calls and mock shapes against the SDK models, fix any drift, log it.

### S2 More of the Disputes API — size M — todo — after Q4
Strengthens Best Use of PayPal + AI. Add the appeal and escalate paths and more evidence types (proof of
fulfillment, refund, return tracking), each proposed by the agent and executed only by `execute` after approval,
with deterministic `PayPal-Request-Id`, mock parity and tests. Look up shapes with the paypal plugin and APIMatic
(log in `docs/apimatic-log.md`). Sandbox-only flows (`require-evidence`) only in the named manual scripts.

### A1 Keep the live backend awake (free) — size S — done #6
GitHub Actions workflow `keep-render-awake.yml`: `curl` `https://rebuttal-oq3g.onrender.com/api/health` every
10 minutes (public repo, so Actions minutes are free; one free Render service running 24/7 fits the 750 free hours a
month). This replaces the planned paid Render plan. Done when the workflow is merged and its first run is green.

### A2 Held-out eval — size S — done (this PR): model alone 80%, final 100%, results in `backend/evals/RESULTS.md`
`cd backend && uv run python -m evals.run --set holdout --provider groq --langfuse`. Report model-alone vs final
accuracy and the per-case misses in `docs/evals.md` (create it, include the main-set numbers from `STATUS.md`) and in
`STATUS.md`. **Change no agent code because of the result.** If Groq returns 429 (daily quota), mark
`waiting: Groq quota until <time>` and move on; retry next day.

### A3 Frontend follow-ups from the PR #3 review — size M — in review (branch fix/frontend-followups)
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

### A8 Re-run the main eval on current code — size S — todo — after Oct 11 (Oct 10 Groq run used by B3)
The 90% main-set number predates guard rule `f4cb66d`. Run `uv run python -m evals.run --provider groq --langfuse`
once (respects one Groq eval per day), update `backend/evals/RESULTS.md`, `STATUS.md` and the eval card in
`docs/video-script.md`. Change no agent code because of the result. A8 must run on a different day than the holdout2 Groq run (B3), so the
two do not share one day's Groq quota.

### B1 AG Studio dashboard, first pass — size L — in progress: part 1 (data endpoints, Studio integration, first dashboard view) in review (PR #16); parts 2-3 custom widgets and Agent Framework todo — deadline Oct 23
Main sponsor prize. Use the `ag-dev` skill and `ag-mcp` for AG Studio APIs in the installed version. Analytics view:
disputes by reason and by product, money kept vs refunded, response deadlines, model-vs-final agreement from the
audit log. Custom widgets and a theme matching `preview/`. New read-only backend endpoints for the aggregates (with
tests). Split into PRs: data endpoints, Studio layout and theme, custom widgets.

### B2 AG Studio depth — size L — todo — needs B1
Studio Agent Framework: plain-English questions over the dispute data ("which products cause most disputes this
month?"), using Groq free tier, read-only data access only. Saved views. Playwright screenshots of every widget into
`docs/screenshots/`.

### B3 More evals — size M — done (holdout2 run Oct 10: final 100%, model alone 80%; this PR)
Grow to about 40 cases: 10 more held-out cases written by a subagent that is **not allowed to read**
`agent/facts.py`, `agent/reasoner.py` or `agent/llm.py` (give it only `cases.json` format and the dispute types).
Run once on Groq (respect the one-run-per-day rule). Update `docs/evals.md`.

### B4 Automated demo video — size L — todo — after A4, B1 — rough cut deadline Oct 23
Free tooling only: Playwright records the browser (video) following the A4 shot list in demo mode; narration from
the A4 script via macOS `say` (pick a natural voice, export AIFF); `ffmpeg` (`brew install ffmpeg`) joins them,
adds captions and title cards. Output `media/rebuttal-demo.mp4` (git-ignored; keep the script and the build command
`scripts/make_video.sh` in git). Under 3:00. Then add a USER item: watch it, optionally re-record the narration in his
own voice (give exact steps), and upload to YouTube as Public.

### B5 Sandbox simulator for judges — size M — superseded by Q4
Research (PayPal plugin, docs) whether a test dispute can be created on the real sandbox without a buyer password.
If yes, add it to the simulator in sandbox mode. If it needs a buyer login, make it a USER item with exact steps and
skip the code.

### E1 Second submission decision — size S — todo — after Oct 18, before Oct 20
Rules allow several substantially different submissions, each winning up to one Grand/Honorable + one Sponsor
prize. Only if Rebuttal's queue is on track: scope a second, different entry aimed at Bryntum ($1,000 x3) or Channel3
($1,500) plus one honorable mention, reusing nothing user-visible from Rebuttal. Write `docs/second-entry.md` with
the idea, effort and a go/no-go; go only if it fits before Nov 3 without slowing Rebuttal.
Sponsor research (Oct 9): Bryntum ships free `-trial` npm packages (no card) but the trial is 45-60 days and
"evaluation only, not production"; judging runs to Dec 15, so verify the trial terms (or ask Bryntum on Discord via a
USER item) before choosing it. Channel3 has a free MCP tier (product catalog search), weak fit for disputes.

### C1 Design polish — size M — todo — after B1
`frontend-design` skill pass over inbox, case view and Studio: typography, spacing, empty and loading states,
keyboard access, accessible contrast; Playwright screenshots before/after in the PR.

### C2 README and submission docs — size M — todo — after B1
README: what it is, 60-second judge quickstart (demo mode link + local run), architecture diagram (Mermaid), safety
design (single write path, guard, approval), eval table, how each sponsor tool is used (AG Grid/Studio, APIMatic with
`docs/apimatic-log.md`, PayPal APIs), license. Draft `docs/devpost.md` (every Devpost field) and
`docs/discord-preview.md` (short post asking for judge-style feedback). Prepare the APIMatic form answers.

### C3 Discord preview — size S — after C2 and A5 — target Oct 23
Make the USER item: post `docs/discord-preview.md` in the AG Grid and general channels (exact steps). Do not post.

### D1 Feature freeze — Nov 3
From Nov 3 only fixes, docs, video. Move any unfinished feature task to `## Cut` with one line why.

### D2 Final check — size M — after Nov 7
Secret scan of the whole git history (`gitleaks` via Homebrew or `trufflehog`), license file, all links in README
work, CI green, live health ok, demo mode works from a fresh browser, video under 3:00, Devpost draft complete. Then
send one alert with the final USER checklist (upload video, submit Devpost, APIMatic form) for Nov 10.

### D3 Learning pack — size M — after D2
Manish wants to learn at the end. Update the local `LEARNING.md` (never commit it): one section per merged PR since
PR #3 (what, why, how, Mermaid where useful, ELI5), a glossary, and the 10 interview questions a PayPal engineer
would ask with model answers.

### D4 Post-hackathon reminder — Dec 22
Alert: delete the Render service (judging ends Dec 15). Do not delete it yourself.

## USER

Things only Manish can do. Each with exact steps; the lead adds them here and alerts at most once a day.

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
