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
| Grand / Best Use of PayPal + AI | Strong: Disputes API end to end, webhook, real sandbox, AI decides, code guards | PayPal Agent Toolkit / MCP in the agent (PayPal's own AI tooling is what they promote); real-sandbox demo |
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
   lookups, keeping `execute` as the only writer.
3. Real-sandbox judge path: create test disputes through the API with a second sandbox **business** account acting as
   buyer (a builder on Discord confirmed personal accounts cannot own a REST app). Needs that account once (USER item).
4. Hosted demo with testing credentials for judges (demo mode, A6) moves up: judges must be able to try it.
5. Second submission: decide by Oct 20 whether a substantially different second entry (aimed at Bryntum or Channel3 plus
   an honorable mention) is worth it; only if Rebuttal is on track.
6. Human narration for the video (Best Demo Delivery); the automated recording stays as the base.
