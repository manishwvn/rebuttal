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
npm run build        # type-check + production build into dist/
npm run lint         # oxlint
npx playwright test  # end-to-end: starts the mock backend and the built dashboard itself, uses your Google Chrome
SCREENSHOTS=1 npx playwright test screenshots   # regenerates docs/screenshots/
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE` | `http://localhost:8000` | Backend base URL |
| `VITE_API_TOKEN` | unset | Bearer token, sent when the backend has `REBUTTAL_API_TOKEN` set. Anything in `VITE_*` is public in the built bundle, and the backend has one token, which is the one that authorizes approve. Use it for local runs only. A hosted build must not set it: add a login or session before the dashboard is deployed (slice 2). |

The browser needs the backend to allow its origin: set `REBUTTAL_CORS_ORIGINS` on the backend (comma separated, no
wildcard). Playwright sets it for `http://localhost:4173`.

## Layout

```
src/api.ts                 the only network code (backend API client)
src/types.ts               API shapes (Proposal.to_dict(), Decision, ...)
src/labels.ts              display names and PayPal endpoint names
src/components/Inbox.tsx   AG Grid inbox
src/components/CaseView.tsx  assistant-vs-shipped, facts, proposal, guard note, approve / edit / reject, audit
src/components/ConfirmDialog.tsx  native modal <dialog>
src/components/SimulatorPanel.tsx  mock-only case picker
e2e/                       Playwright tests
```
