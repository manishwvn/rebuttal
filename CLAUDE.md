# Rebuttal: brief for Claude Code

PayPal AI Hackathon entry. Deadline Nov 12, 2026, 12:00 PM PT; we submit Nov 10. Plan and gates: `PLAN.md`.
Pitch, video script and the judge review that picked this idea: `docs/pitches.md`.

## What we're building

A dispute-prevention agent for small PayPal merchants. On a new dispute it gathers the order, tracking,
transactions, store policies and (for AI-assistant purchases) the assistant's purchase instruction; computes hard
facts in code; decides the cheapest fair resolution; drafts the buyer message or evidence; and waits for the
merchant to approve. Hero demo case: `agent_wrong_size` in `backend/evals/cases.json`.

Prizes we aim at: Most Impactful / Best Use of PayPal + AI / Best Use of Agentic Commerce, plus one sponsor prize
(Bryntum, AG Grid or APIMatic). Judges score Technological Implementation, Design, Impact, Innovation, Presentation
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
python -m pytest
python -m evals.run            # Claude if ANTHROPIC_API_KEY set; --rules forces the baseline
python -m scripts.demo && python -m scripts.build_preview
python -m scripts.spike_sandbox
uvicorn rebuttal.app:app --reload
```

## Next tasks, in order

1. Run the spike with Manish; fix whatever the real sandbox does differently; update the mock.
2. Turn on Claude mode; get ≥ 90% overall and ≥ 3/4 hard cases without editing the expected answers.
3. Week 2–5 items in `PLAN.md`.

## Tooling

Use the PayPal AI Toolkit plugin (github.com/paypal/AI-Toolkit) and the APIMatic Context Plugin for PayPal when
writing PayPal integration code. Note in the README where APIMatic helped (needed for its sponsor prize).
