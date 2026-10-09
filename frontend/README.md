# Rebuttal dashboard

The merchant's dispute desk: an inbox of disputes (AG Grid), a case view that shows why the agent proposes what it
proposes, and approve / edit / reject with a confirm step that states exactly what goes to PayPal. React + Vite +
TypeScript; the grid is AG Grid Community (MIT, no licence key needed).

The dashboard only calls the Rebuttal backend (`/api/...`). It never calls PayPal, and every PayPal write still
happens only in the backend's `execute` node after a human decision.

## Run it (mock mode, no keys, no model)

Terminal 1, the backend on the in-memory mock sandbox with the offline rules baseline:

```bash
cd backend
REBUTTAL_MOCK=1 REBUTTAL_REASONER=rules REBUTTAL_ALLOW_OPEN_API=1 REBUTTAL_API_TOKEN= DATABASE_URL= \
  REBUTTAL_CORS_ORIGINS=http://localhost:5173 uv run uvicorn rebuttal.app:app --port 8000
```

Terminal 2, the dashboard:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

In mock mode a **Simulator** panel appears: pick a case (start with the hero case, "Buyer's AI assistant ordered the
wrong size"), create the dispute, and it opens in the case view.

## Commands

```bash
npm run dev          # Vite dev server
npm run build        # type-check + production build into dist/ (refuses VITE_API_TOKEN, see below)
npm run lint         # oxlint
npx playwright test  # end-to-end: starts the mock backend and the built dashboard itself, uses your Google Chrome
SCREENSHOTS=1 npx playwright test screenshots   # regenerates docs/screenshots/
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE` | `http://localhost:8000` in `npm run dev`, empty (same origin) in a build | Backend base URL |
| `VITE_API_TOKEN` | unset | Bearer token, sent when the backend has `REBUTTAL_API_TOKEN` set. **For `npm run dev` only: `npm run build` fails while it is set** (see below). |

### The build refuses `VITE_API_TOKEN`

Anything in `VITE_*` is inlined into the built JavaScript, so a token there is readable by every visitor, and the
backend has one token, the one that authorizes approve. `vite.config.ts` therefore stops any `vite build` (whatever
`--mode`) with a clear error while `VITE_API_TOKEN` is set, in your shell or in a `.env*` file, before it writes
anything. Pass it inline to the dev server (`VITE_API_TOKEN=... npm run dev`); if you keep it in `.env.local`
(git-ignored), take it out before you build. A hosted dashboard asks for the token on a sign-in screen instead (kept in `sessionStorage`; `e2e/signin.spec.ts`). CI never sets
it, and the Playwright run blanks it for its own build, so a token on your machine can neither break nor leak into the
end-to-end run. `e2e/build-guard.spec.ts` checks the refusal.

The browser needs the backend to allow its origin: set `REBUTTAL_CORS_ORIGINS` on the backend (comma separated, no
wildcard). Playwright sets it for `http://localhost:4173`.

## Demo mode

The judge demo is at the `#demo` route (for example `http://localhost:5173/#demo`). It needs no `VITE_API_TOKEN`: the
demo routes take no token and reach only the backend's demo manager. `src/components/DemoApp.tsx` mounts the same
`Desk` as the dashboard, with an API context that points at `/api/demo/{session}`. Setup and the isolation guarantees
are in [docs/demo-mode.md](../docs/demo-mode.md). End-to-end test:

```bash
npx playwright test e2e/demo.spec.ts
```

## Layout

```
src/api.ts                 the only network code (backend API client)
src/types.ts               API shapes (Proposal.to_dict(), Decision, ...)
src/labels.ts              display names and PayPal endpoint names
src/components/Inbox.tsx   AG Grid inbox
src/components/CaseView.tsx  assistant-vs-shipped, facts, proposal, guard note, approve / edit / reject, audit
src/components/ConfirmDialog.tsx  native modal <dialog>
src/components/SimulatorPanel.tsx  mock-only case picker
src/components/analytics/  Analytics tab: an AG Studio 3.0.0 dashboard (unlicensed, watermark allowed) fed by
                           /api/analytics (one call); lazy-loaded. Notes: docs/ag-studio.md
e2e/                       Playwright tests (dispute flows, and the build guard)
```
