# Prize fit and strategy

Read Oct 9, 2026 from the Devpost page (overview, rules, resources) and the PayPal Developer Discord. Re-check the
Devpost rules page before submitting; they can change.

## What can be won

- Pool $67,500; about 9,900 registered participants.
- Grand: 1st $12,000, 2nd $8,000, 3rd $5,000. Honorable mentions, $5,000 each: Most Creative, Most Impactful, Best
  Demo Delivery, Best Use of PayPal + AI, Best Use of Agentic Commerce.
- Sponsor: AG Grid 1st $5,000 / 2nd $2,000 / 3rd $1,000 (x3); APIMatic $1,000 (x3) + 6 months business plan; Bryntum
  $1,000 (x3); Channel3 $1,500 (x1); Render $1,000 / $750 / $500 in credits.
- **One project wins at most one Grand or one Honorable prize, plus one Sponsor prize.** Ceiling for Rebuttal:
  $12,000 + $5,000 = $17,000.
- **Several submissions are allowed** if each is substantially different; each can win its own pair.

## How it is judged

- Stage 1 pass/fail: fits the theme and really uses PayPal APIs plus AI.
- Stage 2, equally weighted: Technological Implementation, Design (a complete product, not a proof of concept),
  Potential Impact (credible, specific, shown working), Innovation, Presentation (video shows it end to end; who, what,
  why). Ties break in that order, so Technological Implementation matters most in a tie.
- Judges may score from the text, images and video alone, and may use automated AI analysis of submissions.
- Judging Dec 1-15. The project must stay free to test until Dec 15. A private site needs login credentials in the
  testing instructions; a hosted demo URL or complete run instructions are required.
- Repo public with an open-source license visible in the GitHub About box. Video under 3 minutes, public on YouTube,
  no third-party trademarks or copyrighted music without permission.

## Where Rebuttal stands

| Prize | Fit | What raises it |
|---|---|---|
| Grand / Best Use of PayPal + AI | Strong: Disputes API end to end, webhook, real sandbox, AI decides, code guards | Planned, not yet merged: a toolkit-shaped read-only tool layer (see "PayPal Agent Toolkit decision (Q3)" below). Still raises it: that layer landing, a real-sandbox demo, and the read-only tool calls shown in the audit trail in the video |
| Best Use of Agentic Commerce | Strong: disputes caused by AI shopping assistants are our hero case | Show the assistant-mandate evidence clearly; agent acting on PayPal after approval |
| Most Impactful | Good: small merchants lose money and time to disputes | One sourced number on dispute cost; before/after time per dispute |
| Best Demo Delivery | Depends on the video | Human narration, crisp 2:45, hero case live |
| AG Grid 1st | Main sponsor target | AG Studio dashboard with custom widgets, theming, Studio Agent Framework; Oct 12 webinar "Build a payments dashboard without building a dashboard" |
| APIMatic | Backup sponsor (only one sponsor prize counts) | Real use of the PayPal Server SDK context plugin, logged in `docs/apimatic-log.md` (empty today) |

## Competition seen on Discord

- **Stood** (escrowed milestone payments, PayPal Orders v2 + AI): public repo, 729 unit tests, 61 merged PRs, 24
  architecture decision records, CodeQL, OpenSSF Scorecard, OSV-Scanner, PayPal AI Toolkit as a read-only second
  witness, APIMatic plugin, Render. Same "AI suggests, rules move money" story as ours. This sets the bar for
  Technological Implementation.
- At least one other builder ("Palisade") works on the Disputes API, including buyer-side dispute creation.
- Invoice Pilot (WhatsApp agent for PayPal invoices).

## Decisions

1. Close the engineering-signal gap cheaply and for free: security scanners in CI (CodeQL, OSV-Scanner, OpenSSF
   Scorecard, gitleaks), coverage reporting, short architecture decision records for the safety design.
2. Use PayPal's own AI tooling: the PayPal Agent Toolkit (or the PayPal MCP server) for the agent's read-only PayPal
   lookups, keeping `execute` as the only writer. Planned as a read-only adapter in the toolkit's tool format, not yet
   merged; the official package could not be installed or made strictly read-only, details below.
3. Real-sandbox judge path: create test disputes through the API with a second sandbox **business** account acting as
   buyer (a builder on Discord confirmed personal accounts cannot own a REST app). Needs that account once (USER item).
4. Hosted demo with testing credentials for judges (demo mode, A6) moves up: judges must be able to try it.
5. Second submission: decide by Oct 20 whether a substantially different second entry (aimed at Bryntum or Channel3 plus
   an honorable mention) is worth it; only if Rebuttal is on track.
6. Human narration for the video (Best Demo Delivery); the automated recording stays as the base.

## PayPal Agent Toolkit decision (Q3)

What we checked: the PyPI package `paypal-agent-toolkit`, version 1.11.0, its dependency pins, and its source
(`PayPalAPI.run`, the tools it exposes and its HTTP calls).

Findings:

- Dependency conflict. It pins `langchain==0.3.23`, `openai-agents==0.0.2` and `crewai-tools==0.13.2`. Rebuttal
  requires `langchain>=1.4.3`, and uv reports no solution for the two together.
- No read-only gate. `PayPalAPI.run` runs any tool by name, whatever actions are configured. That includes write
  tools such as `accept_dispute_claim`, `create_order` and `pay_order`.
- Transport bypass. It calls `requests` directly, so Rebuttal's read-only transport and the mock cannot gate its
  calls.
- Missing field. Its `list_transactions` does not pass `fields=all`.

What is planned, not in the repo yet: `backend/rebuttal/agent/toolkit.py`, a read-only adapter with the toolkit's tool
shape. It would expose `get_dispute` and `list_transactions` under the toolkit's names, plus `get_order_trackers` and
`get_capture_order_id`, which the toolkit does not name (its closest tool is `get_shipment_tracking`), all running over
`client.read_only()`. `PayPalClient` has no `list_transactions` today, so the adapter
would wrap the existing `search_transactions`. The adapter is not wired into `gather_facts`: `backend/rebuttal/agent/facts.py`
still calls `PayPalClient` directly. `execute` in `rebuttal/approval.py` is the only writer in the agent
graph and the API; the manual sandbox and demo scripts in `backend/scripts/` are the exception.

How the boundary is proven:

- Today: `backend/tests/test_write_boundary.py` scans the source so that only the approval module can reach a PayPal
  write, and `backend/tests/test_core.py::test_analyze_never_writes_to_paypal` checks at run time that analysis makes
  no write calls.
- Planned with the adapter: `backend/tests/test_toolkit.py`, which does not exist yet. It should check that only the
  four read tools are registered, that a write name such as `accept_dispute_claim`, `create_order` or `pay_order`
  raises, and that calls go through `read_only()` and issue only GET. A test that `gather_facts` calls the adapter is
  also needed.

What we do not claim:

- The official `paypal-agent-toolkit` package is not a dependency of Rebuttal and is not imported.
- The PayPal sandbox MCP server (from the `paypal` plugin enabled in `.claude/settings.json`) is a developer tool we
  use while building. It is not part of the runtime.

Follow-up: land the read-only adapter with `test_toolkit.py` and a `gather_facts` test on a branch, then update the
"planned" wording above to match the code. Swap in the official package if its langchain pin is lifted and it gains a
read-only mode.
