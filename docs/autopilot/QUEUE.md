# Autopilot task queue

Ordered. The lead takes the first runnable task each cycle (see `CYCLE.md`). Status: `todo`, `in-progress`,
`waiting: <why>`, `done <PR>`. Sizes: S (under an hour of agent work), M, L (split into several PRs).
Deadlines: video script Oct 12, AG Studio first pass and demo-video rough cut Oct 23, **feature freeze Nov 3**,
final check Nov 8, Manish submits Nov 10 (hard deadline Nov 12, 12:00 PM PT).

## Tasks

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

### A4 Video script — size S — in-progress (branch docs/video-script) — deadline Oct 12
`docs/video-script.md`: under 3 minutes, built from `docs/pitches.md`. One hero case (`agent_wrong_size`), two
cutaways, the eval number on screen. Columns: time, what is on screen (exact UI state or terminal), narration text,
which judging criterion it serves (Tech, Design, Impact, Innovation, Presentation). Include a shot list the
automated recorder (B4) can follow step by step.

### A5 Dashboard on the live service with a login — size M — todo
Serve the built frontend from the FastAPI app on the existing Render service (same origin: no CORS, no new Render
resource, no cost). Replace `VITE_API_TOKEN` with a sign-in screen where the merchant pastes the API token; keep it in
`sessionStorage`, never in the bundle. Update `render.yaml` build to also build the frontend (check Node is available
in Render's Python runtime; if not, find a free alternative and document it). Done when
`https://rebuttal-oq3g.onrender.com/` shows the sign-in screen after deploy and a Playwright test covers sign-in.

### A6 Judge demo mode — size M — todo
Judges must be able to try Rebuttal without PayPal accounts. Add a demo mode on the same service: a "Try the demo"
button that runs the hero case and the other demo cases against the in-memory mock sandbox in a separate, isolated
runtime (no access to the real sandbox client, never writes to PayPal, resets itself). The real-sandbox inbox stays
behind the token. Reviewer must confirm the isolation. Document it in the README.

### B1 AG Studio dashboard, first pass — size L — todo — deadline Oct 23
Main sponsor prize. Use the `ag-dev` skill and `ag-mcp` for AG Studio APIs in the installed version. Analytics view:
disputes by reason and by product, money kept vs refunded, response deadlines, model-vs-final agreement from the
audit log. Custom widgets and a theme matching `preview/`. New read-only backend endpoints for the aggregates (with
tests). Split into PRs: data endpoints, Studio layout and theme, custom widgets.

### B2 AG Studio depth — size L — todo — needs B1
Studio Agent Framework: plain-English questions over the dispute data ("which products cause most disputes this
month?"), using Groq free tier, read-only data access only. Saved views. Playwright screenshots of every widget into
`docs/screenshots/`.

### B3 More evals — size M — todo
Grow to about 40 cases: 10 more held-out cases written by a subagent that is **not allowed to read**
`agent/facts.py`, `agent/reasoner.py` or `agent/llm.py` (give it only `cases.json` format and the dispute types).
Run once on Groq (respect the one-run-per-day rule). Update `docs/evals.md`.

### B4 Automated demo video — size L — todo — after A4, B1 — rough cut deadline Oct 23
Free tooling only: Playwright records the browser (video) following the A4 shot list in demo mode; narration from
the A4 script via macOS `say` (pick a natural voice, export AIFF); `ffmpeg` (`brew install ffmpeg`) joins them,
adds captions and title cards. Output `media/rebuttal-demo.mp4` (git-ignored; keep the script and the build command
`scripts/make_video.sh` in git). Under 3:00. Then add a USER item: watch it, optionally re-record the narration in his
own voice (give exact steps), and upload to YouTube as Public.

### B5 Sandbox simulator for judges — size M — todo
Research (PayPal plugin, docs) whether a test dispute can be created on the real sandbox without a buyer password.
If yes, add it to the simulator in sandbox mode. If it needs a buyer login, make it a USER item with exact steps and
skip the code.

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

- (none yet)

## Cut

- Render paid plan: replaced by A1 (no spending).
- Bryntum: backup only; dropped unless everything else is done before Oct 30.
- Elastic retrieval: optional; dropped unless everything else is done before Oct 30.
- Ticking "Transaction search" in the PayPal app: account setting, not needed.
