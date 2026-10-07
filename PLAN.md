# Rebuttal: plan to submission

Hackathon: PayPal AI Hackathon (Devpost). Deadline **Thu Nov 12, 12:00 PM PT**. Our submit date: **Tue Nov 10**.
Judging Dec 1–15, winners ~Dec 21. Owner: Manish. Builder: Claude Code. Strategy and writing: Claude chat.

## Where things stand (Oct 6)

- Idea chosen by an independent judge pass: dispute-prevention agent, 36/50 vs 32/50 for the runner-up
  (agent-readiness tester for small stores). Estimated chance of at least one cash prize: about 40% vs 22%.
  These are estimates, not facts.
- Hero case: a buyer's AI shopping assistant ordered the wrong size. Targets Best Use of Agentic Commerce and
  separates us from card-chargeback tools.
- Prototype done and passing: PayPal client (Disputes, Orders, tracking, transactions, webhooks), mock sandbox,
  agent pipeline (gather → decide → guard → plan), single approval gate, audit log, evidence PDF, FastAPI API,
  judge simulator (mock), 20 labeled eval cases, 8 tests, sandbox spike script.
- Offline baseline: 85% overall, 100% on standard cases, 25% on hard cases, 0 PayPal writes before approval.

## Gate 1: prove it before building more (Oct 7–9)

Nothing else gets built until this passes.

| Check | Who | Pass when |
|---|---|---|
| PayPal developer account, sandbox app with Disputes enabled, buyer + business test accounts | You | Keys in `backend/.env` |
| `python -m scripts.spike_sandbox` | You run it, Claude Code fixes | Verdict GO: order, capture, dispute visible to merchant, message, offer, evidence, adjudicate all pass |
| Anthropic API key in `.env`, then `python -m evals.run` | You add key, Claude Code tunes | Claude mode ≥ 90% overall and at least 3 of 4 hard cases |
| PayPal Discord: is a dispute-prevention agent interesting? Can Bryntum and AG Studio trials stay live through Dec 15? | You | Answers recorded in this file |

**If the spike fails** because disputes can't be created or answered in sandbox even by hand: switch to the runner-up.
The PayPal client, approval gate, audit log and eval harness carry over, so the switch costs about a day.
**If Claude mode can't beat the baseline on hard cases**: keep the idea, fix prompts and the case file first.

## Week 2 (Oct 10–16): real sandbox end to end

- `scripts/seed_sandbox.py`: create orders, upload tracking, open disputes (buyer API with consent, or Resolution Center by hand).
- Persist proposals and audit to SQLite.
- Webhook endpoint with signature verification; deploy backend to Render so PayPal can reach it.
- Grow evals to ~40 cases. You write 10 of them yourself, without looking at the agent, so the score isn't self-graded.

## Week 3 (Oct 17–23): the product people see

- React + Vite frontend built from the preview page: inbox, case view, edit-and-approve, audit trail.
- Bryntum Scheduler deadline board (start the trial now).
- Judge simulator in sandbox mode: one click opens a real test dispute and the agent handles it live.
- Deploy frontend + backend on Render.

## Week 4 (Oct 24–30): sponsor depth and polish

- AG Studio analytics: sales kept, disputes by reason and product, plus its agent for plain-English questions.
- Optional: Elastic retrieval for policies and past outcomes (only if Weeks 2–3 are on time).
- Rough cut of the video; get two people to watch it cold and say what they didn't understand.

## Week 5 (Oct 31–Nov 10): ship

- **Feature freeze Nov 3.** After that only fixes, docs and video.
- README with setup, sandbox test credentials, eval table, and how each sponsor tool is used.
- Final video under 3 minutes (script in `docs/pitches.md`), uploaded public on YouTube.
- Devpost write-up, APIMatic subscription form, license check, submit **Nov 10**.

## Risks and what we do about them

| Risk | Plan |
|---|---|
| Sandbox dispute creation is fiddly (buyer consent + auth header) | Resolution Center by hand for the demo; API creation only for the simulator |
| Sponsor trials (45 days) expire before judging ends Dec 15 | Ask sponsors in Gate 1. Fallback: the video and screenshots carry the sponsor features |
| Render free tier sleeps; judges see a cold start | Use the $50 participant credits for an always-on instance through Dec 15 |
| Another entrant ("Witness") covers AI-assistant dispute evidence | Our pitch is prevention for all disputes; the assistant case is one showcase |
| Video overloaded | One hero case, two cutaways, eval number on screen |
| Scope creep | Freeze Nov 3; Elastic and extra sponsor work are cut first |

## Who does what

- **You:** accounts and keys, the two browser steps in the spike, Discord questions, writing 10 eval cases, final
  decisions, recording the video in your voice, submitting under your name.
- **Claude Code:** all code, tests, evals, deployment config, README.
- **Claude chat:** gate reviews, video script, Devpost write-up, final check before submission.
