# Builder prompt: frontend slice 1 (inbox, case view, approval)

Read CLAUDE.md, STATUS.md and PLAN.md first. Work on branch `feat/frontend-inbox`, open a PR to `main`, and keep CI
green. Do not touch `rebuttal/approval.py`, the PayPal client, the guard or the facts code.

## Goal

The first working dashboard: a merchant sees an inbox of disputes, opens one, reads why the agent proposes what it
proposes, and approves, edits then approves, or rejects. `preview/rebuttal-preview.html` is the design target.

## Rules for this task

- Run everything with `REBUTTAL_MOCK=1 REBUTTAL_PROVIDER=rules REBUTTAL_ALLOW_OPEN_API=1` and `DATABASE_URL` blank.
  No Groq calls, no real sandbox, no Supabase. Say in the PR that you never used a model key.
- Before starting, run `find-skills` for React + Vite + AG Grid + Playwright work, recommend matches, and ask Manish
  before installing anything. Use the installed `ag-dev` skill and the `ag-mcp` server before writing any AG Grid code;
  `frontend-design` and `vercel-react-best-practices` for the UI.
- The frontend never calls PayPal. It only calls the backend API below.

## Stack

`frontend/`: Vite + React + TypeScript, AG Grid Community (watermark is fine). npm, lockfile committed. API base URL
from `VITE_API_BASE` (default `http://localhost:8000`), optional bearer token from `VITE_API_TOKEN`. If the browser
needs CORS, add a minimal `CORSMiddleware` to `rebuttal/app.py` with origins from an env var (`REBUTTAL_CORS_ORIGINS`),
add it to `.env.example`, and add a test.

## Backend API (already exists, `backend/rebuttal/app.py`)

- `GET /api/health`
- `GET /api/disputes` (each item carries its latest `proposal` or null)
- `GET /api/proposals/pending`
- `POST /api/disputes/{id}/analyze`
- `POST /api/proposals/{id}/approve` body `{"edited_message": str | null}`; 409 means not approvable
- `POST /api/proposals/{id}/reject` body `{"reason": str}`
- `POST /api/proposals/{id}/retry`
- `GET /api/audit/{dispute_id}`
- `POST /api/simulator/dispute/{case_id}` (mock only; case ids from `backend/evals/cases.json`)

Read `Proposal.to_dict()` for the real field names; do not guess them.

## Screens

1. **Inbox** (AG Grid): dispute id, buyer reason, amount, age, proposed action, status (pending / approved /
   rejected / executed). Click a row to open the case.
2. **Case view**: for AI-assistant purchases, "assistant instruction vs what shipped" side by side at the top (the
   hero case `agent_wrong_size`: "medium" vs L); the computed facts; the model's choice, the final action and the
   guard note when the guard changed it; the drafted buyer message in an editable textarea.
3. **Approve / edit / reject**: every action opens a confirm dialog that states exactly what will be sent to PayPal
   (action, amount, message). Show 409 errors plainly. After a decision, refresh the case and the inbox.
4. **Audit trail**: timeline from `/api/audit/{dispute_id}` on the case view.
5. **Simulator panel** (shown only when health says mock mode): pick a case from a list, create a dispute, it appears
   in the inbox.

## Done when

- `npm run build` and `npm run lint` pass; `uv run pytest` still passes (169+).
- A Playwright test (in `frontend/`, using the `playwright-cli` or `webapp-testing` skill) starts the backend in mock
  mode, simulates `agent_wrong_size`, opens it, checks the assistant-vs-shipped panel and the guard note, approves with
  an edited message, and sees status change plus a new audit entry. A second test rejects a case.
- CI runs the frontend build and the Playwright test (extend `.github/workflows/tests.yml`).
- Screenshots of the inbox and the hero case view attached to the PR.
- `README` or `frontend/README.md` has the run commands.

Out of scope for this PR: AG Studio dashboard, Render static site deploy, live sandbox mode. Use the reviewer agent
on the diff before opening the PR. Report back: PR link, CI result, anything you changed in the backend and why.
