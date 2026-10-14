# Devpost submission draft

Draft text for every Devpost field. Facts come from the repo (README.md, STATUS.md, backend/evals/RESULTS.md,
docs/). Re-check each number against its source before pasting. Manish submits; nothing here is posted.

Items marked TODO need Manish or a later task.

## Project name

Rebuttal

## Tagline (under 200 characters)

An AI agent that handles PayPal disputes for small shops: it checks the facts in code, drafts the cheapest fair fix, and sends nothing to PayPal until the merchant approves.

(173 characters.)

## Inspiration

Small merchants lose PayPal disputes by not showing up, refund out of fear, or send weak evidence. A new kind of dispute is also coming: a buyer's AI shopping assistant orders the wrong thing, and the buyer files "not as described". The merchant has no record of what the assistant was told to buy. We wanted an agent that does the dull evidence work, handles that new case, and still leaves the money decision to the human.

## What it does

When a buyer opens a dispute, PayPal sends a signature-verified webhook. Rebuttal gathers the order, shipment tracking, transaction history and store policies. It computes hard facts in code: delivered or not, inside the return window or not, duplicate charge or not. A model then reads the buyer's words and picks a resolution. A guard rejects any choice the facts, or PayPal's allowed offer types, do not support. The agent drafts one PayPal action and stops.

The merchant sees the facts, the reasoning and the drafted message in a dashboard, then approves, edits or rejects. Only then does one PayPal call go out. Every step is in an audit log.

Hero case: the buyer's AI assistant was told "medium", the order shipped a large. In the live Groq run (see backend/evals/RESULTS.md), the model first suggested a free replacement, PayPal does not allow that offer on this dispute, and the guard changed it to a refund after the return. The judge demo uses the offline rules reasoner and goes straight to the refund after return.

The dashboard has an inbox (AG Grid), a case view, and an Analytics tab built with AG Studio, with custom widgets and an assistant that answers questions about the dispute data.

## How we built it

- Backend: Python, FastAPI, a LangGraph workflow `gather_facts > decide > guard > plan_actions > approval > execute > record`, LangChain chat models (Groq live; Anthropic and NVIDIA supported), Pydantic-validated model output.
- Safety: only the `execute` node can write to PayPal. Analysis holds a read-only client whose transport refuses anything but GET. Approval is a LangGraph `interrupt()`. Approved writes carry a deterministic `PayPal-Request-Id`. A test scans the code to keep it that way.
- PayPal: Disputes API (read, message, offer, evidence, accept, escalate, appeal), Orders v2 and tracking, transaction search, dispute webhooks with signature verification. Sandbox only, enforced in code.
- State: LangGraph checkpoints and the audit log in free Supabase Postgres, so a proposal waiting for approval survives a restart.
- Frontend: React, Vite, TypeScript, AG Grid for the inbox, AG Studio for analytics with four custom widgets, a theme from our design tokens, and an assistant via the Studio Agent Framework (through a read-only backend proxy so the key never reaches the browser).
- Judge demo: each visitor gets a private in-memory mock session, with no token and no PayPal account.
- Deployed on Render (free plan). CI runs tests, ruff, gitleaks, CodeQL, OSV-Scanner, OpenSSF Scorecard and Playwright.
- We built it with Claude Code and used the APIMatic Context Plugin for PayPal while checking our PayPal client (see docs/apimatic-log.md).

## Challenges we ran into

- The official PayPal Agent Toolkit could not be used read-only: it pins an old `langchain`, runs any tool by name, bypasses our HTTP transport and omits the payer email we need. We wrote a four-tool read-only adapter in its tool shape instead (ADR 0008).
- PayPal's Disputes API does not allow every offer type on every dispute. The model kept choosing a replacement that PayPal would refuse, which is why the guard exists.
- PayPal documents `PayPal-Request-Id` for Orders and Payments but not for Disputes, so we do not rely on it there. `execute` reads the dispute first and skips a message or offer that already landed.
- Honest evals. We tuned on a 20-case set, so we wrote two held-out sets blind to the guard code and report them separately.
- Free-tier limits: a shared Groq token budget and Render cold starts of about 50 seconds.

## Accomplishments that we're proud of

- A real sandbox dispute went end to end on Oct 7, 2026: buyer files, verified webhook, gather, decide, guard, propose, and stop at the approval gate with no PayPal write.
- Eval numbers (from backend/evals/RESULTS.md, Groq `qwen/qwen3.8-27b`): main set 75% model alone, 95% (19/20) final on Oct 14; held-out set 1: 80% model alone, 100% (10/10) final; held-out set 2: 80% model alone, 100% (10/10) final. Zero PayPal writes before approval in every run. Held-out sets have 10 cases each, so the sample is small.
- The write boundary is enforced by tests, not by convention.
- A public demo that needs no accounts and cannot reach the real PayPal client.
- 469 backend tests at 93% combined line and branch coverage, ten architecture decision records.

## What we learned

- Put facts in code and let the model do words. The guard turned model-alone scores of 75-80% into 95-100% final, and the held-out sets say the guard is not just fitted to our own cases.
- A human approval gate is easiest to trust when it is a graph interrupt and a test, not a UI button.
- Read the vendor tool's source before you depend on it. The SDK and toolkit checks changed what we built.
- A demo for judges is a product feature: it needs isolation, limits and its own tests.

## What's next

- Run the AG Studio assistant against live Groq (tested with mocks only so far).
- Page through PayPal's dispute list (analytics cover the first page today).
- Run a real approved write against the sandbox through the deployed app.
- A real login for the hosted dashboard (today it is a sign-in with one API token).

## Built with

Python, FastAPI, LangGraph, LangChain, Pydantic, Groq, Anthropic API, Langfuse, PayPal REST APIs (Disputes, Orders v2, transaction search, webhooks), PostgreSQL, Supabase, Render, React, TypeScript, Vite, AG Grid, AG Studio, Playwright, Claude Code, APIMatic Context Plugin.

## Try it out

- Live demo (no sign-in, no PayPal account): https://rebuttal-oq3g.onrender.com/#demo
- Source code (MIT): https://github.com/manishwvn/rebuttal
- Health check: https://rebuttal-oq3g.onrender.com/api/health

## Video

<YouTube link, added by Manish>

## Testing instructions for judges

1. Open https://rebuttal-oq3g.onrender.com/#demo. No login, token or PayPal account is needed. The service sleeps when idle, so the first load can take about 50 seconds.
2. A private demo session starts with six disputes. Open "Buyer's AI assistant ordered the wrong size". It is already analyzed.
3. Read the facts, the decision and the drafted message. Edit a line if you want, then approve. The call goes to an in-memory mock of the PayPal sandbox, never to the real one.
4. Use the simulator to add any of the 20 labeled disputes, or click Reset demo.
5. The demo uses the offline rules reasoner, not a model. The live service (not the demo) uses Groq against the real PayPal sandbox and requires an API token, so it is not part of judge testing.
6. Run it yourself: README.md, section "Try it in 60 seconds". Needs uv and Node.js, no keys. `cd backend && uv run pytest` runs the tests.

## Not verified / TODO before submitting

- TODO (Manish): keep the project free to test until Dec 15, 2026. Hosting is Render's free plan, so keep the service up until judging ends.
- TODO: video link (Manish).
- TODO: a sourced number for what disputes cost small merchants, if we want to claim impact in figures. None is in the repo, so none is used above.
- Not verified: the full demo click-through on the deployed service (only the session API was checked), the AG Studio assistant against live Groq, and the GitHub URL being public with the MIT license shown in the About box (check on github.com).
- Re-check the Devpost rules page before submitting; they can change.
