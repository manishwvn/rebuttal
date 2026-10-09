# Rebuttal: brief for Claude Code

PayPal AI Hackathon entry. Deadline Nov 12, 2026, 12:00 PM PT; we submit Nov 10. Plan and gates: `PLAN.md`.
Pitch, video script and the judge review that picked this idea: `docs/pitches.md`.

## Workflow

- **At session start read `STATUS.md`. At the end of every task update `STATUS.md`.**
- **Work on a branch per task and open a PR; never push code straight to `main`.** Docs-only STATUS updates ride on
  the task's PR. CI (`.github/workflows/tests.yml`) must pass before merge.
- **Code-minimizing skills (for example Ponytail) must never remove tests, guard rules, or the approval boundary.**
  Safety code that looks redundant is deliberate; leave it.
- Use the `reviewer` agent (`.claude/agents/reviewer.md`) before merging a non-trivial change and the `chores` agent
  for small edits, formatting and docs.

## What we're building

A dispute-prevention agent for small PayPal merchants. On a new dispute it gathers the order, tracking,
transactions, store policies and (for AI-assistant purchases) the assistant's purchase instruction; computes hard
facts in code; decides the cheapest fair resolution; drafts the buyer message or evidence; and waits for the
merchant to approve. Hero demo case: `agent_wrong_size` in `backend/evals/cases.json`.

Prizes we aim at: Most Impactful / Best Use of PayPal + AI / Best Use of Agentic Commerce, plus sponsor prizes:
**AG Grid is the main target** (AG Studio dashboard with custom widgets, theming and the Studio Agent Framework;
AG Grid confirmed on Discord that unlicensed use with the watermark isn't penalized), **APIMatic** (document its use,
below), and **Bryntum as backup only**. The 3-minute video is a top priority: script by Oct 12, rough cut by end of
Week 3, final in Week 5. Feature freeze Nov 3, submit Nov 10. See "Prize strategy" in `PLAN.md`. Judges score Technological Implementation, Design, Impact, Innovation, Presentation
equally, often from the video alone.

## Rules that never bend

- Sandbox only. `load_settings()` raises unless `PAYPAL_ENV=sandbox`. Never add a live base URL.
- Only the graph's `execute` node (in `rebuttal/approval.py`) may call PayPal write endpoints (message, offer,
  evidence, accept). The graph routes to it only after a human approve or edit decision (LangGraph `interrupt()`),
  and it refuses to run without one. Analysis nodes hold `client.read_only()`, a clone whose transport refuses
  anything but GET; the full client raises on any write outside `permit_writes()`, which only `execute` (and the
  named manual sandbox scripts) enter. Nothing fallible may run after `interrupt()` returns or after the PayPal call
  inside `execute`. `tests/test_write_boundary.py` and `tests/test_core.py::test_analyze_never_writes_to_paypal`
  must stay green.
- Facts are computed in code (`agent/facts.py`). The model interprets words and drafts text, and only the `decide`
  node calls a model; its output is validated against a Pydantic schema. `guard()` rejects model choices the facts
  don't support.
- Every agent step and PayPal write goes to the audit log, and every approved PayPal write carries a deterministic
  `PayPal-Request-Id`.
- Tests never call a model or send traces: `tests/conftest.py` sets `REBUTTAL_REASONER=rules` and
  `REBUTTAL_TRACING=0`, because `backend/.env` holds real keys.
- No secrets in git. `.env` is ignored; keep `.env.example` current.
- The mock (`paypal/mock.py`) must mirror the real sandbox. When the spike shows a difference, fix the mock and the
  client together, and remove the matching `VERIFY` note.
- Repo stays public with the MIT license.

## Layout

```
backend/
  rebuttal/config.py        settings, sandbox guard
  rebuttal/paypal/client.py PayPal REST client, read_only(), permit_writes()   paypal/mock.py  in-memory sandbox
  rebuttal/store.py         merchant order records (incl. AI-assistant purchase intent)
  rebuttal/policies.py      store policies + retriever (Elastic later)
  rebuttal/agent/graph.py   the LangGraph workflow: gather_facts > decide > guard > plan_actions > approval > execute > record
  rebuttal/agent/facts.py   gather + hard facts      agent/reasoner.py  rules baseline, guard, prompt
  rebuttal/agent/llm.py     ModelReasoner: LangChain chat models + Pydantic DecisionOut (Anthropic | Groq | NVIDIA)
  rebuttal/agent/pipeline.py plan_actions, evidence PDF, Proposal
  rebuttal/approval.py      the approval interrupt + the execute node (the only PayPal writes) + ApprovalQueue
  rebuttal/persistence.py   checkpointer (memory | SQLite | Postgres) + per-dispute locks      audit.py   audit log (file | Postgres)
  rebuttal/tracing.py       Langfuse tracing, dataset upload, experiments (off unless keys are set)
  rebuttal/runtime.py       wiring            app.py     FastAPI (dashboard API, webhook, simulator)
  rebuttal/scenarios.py     labeled case -> sandbox state
  rebuttal/demo.py, demo_api.py  judge demo: per-visitor mock Runtime + public /api/demo routes
  evals/cases.json, run.py  20 labeled disputes, accuracy report (--langfuse records an experiment)
  scripts/spike_sandbox.py  Gate 1 real-sandbox test     scripts/demo.py   demo run -> preview_data.json
  scripts/build_preview.py  preview page from template
preview/                    template.html -> rebuttal-preview.html (design target for the React app)
```

## Commands (from backend/)

```
uv sync                                  # once, and after pyproject.toml changes (creates backend/.venv)
uv run pytest
uv run python -m evals.run               # model if a provider key is set; --rules forces the baseline
uv run python -m evals.run --langfuse    # also record the run as a Langfuse experiment (needs the Langfuse keys)
uv run python -m scripts.demo && uv run python -m scripts.build_preview
uv run python -m scripts.spike_sandbox
uv run uvicorn rebuttal.app:app --reload
uv add <package>                         # add a dependency (never pip install, never a requirements.txt)
```

The backend is a uv project: `backend/pyproject.toml`, `backend/uv.lock` (commit both), `backend/.python-version`.

## Current state and next tasks

Live: the backend runs on Render (free plan, `https://rebuttal-oq3g.onrender.com`) against the real PayPal sandbox
(`REBUTTAL_MOCK=0`), with Groq as the model, Supabase Postgres for checkpoints and the audit log, and a registered
webhook (`CUSTOMER.DISPUTE.*`, signature-verified). Proven end to end on Oct 7: a buyer-filed sandbox dispute produced
a verified webhook, then gather > decide > guard > propose, and paused at the approval interrupt with no PayPal write.
A live order maps to a merchant record when its invoice is `RB-<case id>-<n>`: make one with
`uv run python -u -m scripts.make_test_order --case agent_wrong_size` (see `scripts/make_test_order.py`).

Next, in order:

1. Frontend (`frontend/`, none yet): inbox of disputes, case view (facts, reasoning, drafted message), approve / edit /
   reject against `/api/proposals/*`, using the `preview/` page as the design target.
2. AG Grid dashboard (AG Studio, custom widgets, theming): the main sponsor-prize target.
3. Video script by Oct 12; rough cut by end of Week 3. Then the remaining Week 2-5 items in `PLAN.md`.

## Tooling

**Skills.** At the start of any new kind of work (a new framework, deploy, testing, design, docs), run the
`find-skills` skill first and recommend matches before installing anything (global rule: ask first). Project skills
already installed in `.claude/skills/`: frontend-design, vercel-react-best-practices, playwright-cli, webapp-testing,
render-deploy, uv, langgraph-fundamentals, langgraph-persistence, ag-dev, ag-update.

**MCP servers and plugins: prefer these over memory for API details.** Look the answer up, then write the code.
- `paypal` plugin (PayPal AI Toolkit, project scope) and its `paypal-sandbox` MCP server: PayPal API behavior and
  error codes. It needs `PAYPAL_SANDBOX_ACCESS_TOKEN` in `.claude/settings.local.json` (git-ignored). Refresh it
  with `backend/scripts/refresh_paypal_token.sh` (tokens last about 9 hours), then restart Claude Code. The sandbox
  MCP can also write to disputes: use it to read and to look things up, never to act on a dispute. Only
  `rebuttal/approval.py` writes.
- APIMatic Context Plugin for PayPal (`paypal@context-plugins-local`, user scope, installed with
  `npx context-plugins install https://github.com/paypaldev/server-sdk-context-plugin-preview`): PayPal Server SDK
  skills. Log every place it helped in `docs/apimatic-log.md`; the APIMatic prize depends on it.
- `langchain-docs` and `langchain-reference`: LangGraph and LangChain docs and API reference (`.mcp.json`).
- `ag-mcp`: AG Grid docs by version, for the AG Studio dashboard (`.mcp.json`).
- `playwright`: drive the app in a browser for end-to-end checks (`.mcp.json`).
- `supabase` MCP: the online database (free project `rebuttal`, us-east-1). Use `search_docs` for Supabase facts. The
  password is only in `backend/.env` as `DATABASE_URL` (session pooler, port 5432). Tests and evals blank it and never
  touch the online database; `backend/tests/live_postgres.py` is the one deliberate live check. Ask before creating
  anything that could cost money.
- Render MCP is not installed. Add it when we deploy, and ask Manish before using any Render API key.
- Project-scoped servers in `.mcp.json` need approval once per machine (run `claude` and approve).

**Subagents.** Use subagents for independent tasks that can run in parallel (for example research on one
sponsor tool while another agent writes tests), and for code review of any non-trivial change before it is
committed. Give each subagent a self-contained prompt; they do not see this conversation.

**Keys.** Never print, commit or guess a key or token. Ask Manish.
