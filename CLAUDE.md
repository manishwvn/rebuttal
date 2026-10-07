# Rebuttal: brief for Claude Code

PayPal AI Hackathon entry. Deadline Nov 12, 2026, 12:00 PM PT; we submit Nov 10. Plan and gates: `PLAN.md`.
Pitch, video script and the judge review that picked this idea: `docs/pitches.md`.

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
- Only `rebuttal/approval.py` may call PayPal write endpoints (message, offer, evidence, accept). The agent proposes;
  it never executes. `tests/test_core.py::test_analyze_never_writes_to_paypal` must stay green.
- Facts are computed in code (`agent/facts.py`). The model interprets words and drafts text. `guard()` rejects model
  choices the facts don't support.
- Every agent step and PayPal write goes to the audit log.
- No secrets in git. `.env` is ignored; keep `.env.example` current.
- The mock (`paypal/mock.py`) must mirror the real sandbox. When the spike shows a difference, fix the mock and the
  client together, and remove the matching `VERIFY` note.
- Repo stays public with the MIT license.

## Layout

```
backend/
  rebuttal/config.py        settings, sandbox guard
  rebuttal/paypal/client.py PayPal REST client      paypal/mock.py  in-memory sandbox
  rebuttal/store.py         merchant order records (incl. AI-assistant purchase intent)
  rebuttal/policies.py      store policies + retriever (Elastic later)
  rebuttal/agent/           facts.py, reasoner.py (Claude | rules, guard), pipeline.py (actions, evidence PDF)
  rebuttal/approval.py      approval gate     audit.py   audit log
  rebuttal/runtime.py       wiring            app.py     FastAPI (dashboard API, webhook, simulator)
  rebuttal/scenarios.py     labeled case -> sandbox state
  evals/cases.json, run.py  20 labeled disputes, accuracy report
  scripts/spike_sandbox.py  Gate 1 real-sandbox test     scripts/demo.py   demo run -> preview_data.json
  scripts/build_preview.py  preview page from template
preview/                    template.html -> rebuttal-preview.html (design target for the React app)
```

## Commands (from backend/)

```
uv sync                                  # once, and after pyproject.toml changes (creates backend/.venv)
uv run pytest
uv run python -m evals.run               # model if a provider key is set; --rules forces the baseline
uv run python -m scripts.demo && uv run python -m scripts.build_preview
uv run python -m scripts.spike_sandbox
uv run uvicorn rebuttal.app:app --reload
uv add <package>                         # add a dependency (never pip install, never a requirements.txt)
```

The backend is a uv project: `backend/pyproject.toml`, `backend/uv.lock` (commit both), `backend/.python-version`.

## Next tasks, in order

1. Run the spike with Manish; fix whatever the real sandbox does differently; update the mock.
2. Turn on Claude mode; get ≥ 90% overall and ≥ 3/4 hard cases without editing the expected answers.
3. Week 2–5 items in `PLAN.md`.

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
- Render MCP is not installed. Add it when we deploy, and ask Manish before using any Render API key.
- Project-scoped servers in `.mcp.json` need approval once per machine (run `claude` and approve).

**Subagents.** Use subagents for independent tasks that can run in parallel (for example research on one
sponsor tool while another agent writes tests), and for code review of any non-trivial change before it is
committed. Give each subagent a self-contained prompt; they do not see this conversation.

**Keys.** Never print, commit or guess a key or token. Ask Manish.
