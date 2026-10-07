# Two candidate entries — PayPal AI Hackathon (Devpost), Oct 2026

Both are scoped for one engineer (strong in Python, RAG, agents) building with Claude Code over ~5 weeks.

---

## Idea A — "Rebuttal": a dispute-prevention agent for PayPal small merchants

**Pitch.** When a buyer opens a PayPal dispute, small merchants either miss the response deadline, refund out of fear, or send weak evidence. Rebuttal watches every dispute from the moment it opens. While it is still an *inquiry* (before PayPal escalates it to a claim), the agent pulls the order, shipment tracking, transaction history and the store's own policies, works out what actually happened, and proposes the cheapest correct resolution: message the buyer with tracking proof, offer a partial refund or replacement, or accept quickly when the buyer is right. If the dispute does escalate, it assembles the evidence package. Nothing is sent and no money moves until the merchant approves; every step is logged.

**Showcase case for agentic commerce.** A buyer's AI assistant bought the wrong size; the buyer files "not as described." Rebuttal retrieves the purchase-intent record the assistant created at checkout and the merchant's size chart, and proposes a replacement instead of a refund — the kind of dispute that will grow as PayPal pushes checkout inside AI assistants.

**PayPal surface used (all available in sandbox):** Orders v2, Disputes API (list, details, send-message, make-offer with REFUND / REPLACEMENT types, provide-evidence, accept-claim, escalate), sandbox-only require-evidence and adjudicate for outcomes, dispute webhooks (CREATED / UPDATED / RESOLVED), shipment tracking, transaction search.

**AI.** Hybrid agent: code computes hard facts (was it delivered, inside the return window, does tracking match the address), Claude handles judgment and writing (what the buyer actually wants, the message, the evidence narrative). Retrieval over store policies and past outcomes. Eval suite of labeled disputes with accuracy reported in the README.

**Sponsor tools.** Bryntum Scheduler deadline board (every open case against its response deadline, colored by evidence readiness — Bryntum's own idea list names a "dispute triage board"); AG Studio analytics (money saved, disputes by reason and product, natural-language questions); APIMatic plugin during the build; Render hosting.

**Judge simulator.** A button opens a test dispute in the sandbox; judges watch the agent resolve it live.

**Known weaknesses.** Commercial dispute tools exist (Chargeflow, Justt, Midigator), mainly card chargebacks on Shopify/Stripe. One other public hackathon repo ("Witness", 1 commit) does dispute evidence for AI-agent purchases. Disputes are an operational, not glamorous, topic.

### 3-minute video script (A)
- 0:00–0:20 — Hook: "Every PayPal dispute starts as a conversation. Most small sellers lose it by not showing up." Show an inquiry arriving, deadline counting down.
- 0:20–1:20 — Live: dispute opens (simulator) → agent timeline: pulls order, tracking shows delivered to the right address, retrieves return policy → proposes "send tracking proof + 10% goodwill offer" with reasoning and a confidence score → merchant edits one line, approves → message and offer appear on the PayPal dispute.
- 1:20–1:55 — Agentic commerce case: AI-assistant purchase, wrong size → replacement offered with the size chart and intent record as evidence.
- 1:55–2:25 — Escalated claim: evidence package auto-assembled and submitted; sandbox adjudication → seller wins; Bryntum board turns green, AG Studio shows money saved.
- 2:25–2:50 — Trust: approval gate, audit log, eval results ("correct resolution on N of M labeled disputes").
- 2:50–3:00 — Who it's for, why it matters to PayPal: trust on both sides of every transaction.

---

## Idea B — "Shelfready": make any small PayPal store buyable by AI shopping agents

**Pitch.** PayPal is betting that shopping is moving into AI assistants (checkout in ChatGPT, Google, Copilot; Store Sync; WebMCP support announced Sep 2026). Large merchants get there through platforms; a small seller with a hand-built site is invisible to agents. Shelfready crawls the store, uses an LLM to turn messy product pages into a clean structured catalog (variants, sizes, stock, policies), and publishes an agent-callable storefront (an MCP server / WebMCP-style tools: search, get product, create cart, checkout) whose checkout runs on PayPal Orders. Then it runs a fleet of simulated AI shoppers with different goals against the store and reports an "agent conversion score": where agents got confused, what data was missing, and fixes the merchant can accept in one click.

**PayPal surface used:** Orders v2 (create, authorize/capture), Catalog Products API, PayPal JS SDK on the merchant site, optionally the PayPal MCP server inside the simulated shoppers; WebMCP / Store Sync where available (may not be available in sandbox — fallback is our own MCP server).

**AI.** LLM catalog extraction and enrichment; simulated buyer agents (multi-agent); LLM-generated fix suggestions.

**Sponsor tools.** Channel3 (benchmark the merchant's products against comparable products across retailers); AG Studio (agent-readiness dashboard); Render hosting. Weak fit for Bryntum.

**Judge simulator.** Paste any store URL → see the agent-ready storefront → watch a simulated shopper buy something through PayPal sandbox.

**Known weaknesses.** PayPal's own Store Sync / Agent Ready and Shopify's agentic storefronts target the same problem; risk of looking like a rebuild of PayPal's product. One public hackathon repo ("AgentBaazar") makes small stores agent-ready. Crawling arbitrary stores is fragile; sandbox may not support WebMCP / Store Sync.

### 3-minute video script (B)
- 0:00–0:20 — Hook: "Ask ChatGPT to buy a candle from Maya's shop. It can't. Her store doesn't exist to agents."
- 0:20–1:15 — Paste Maya's URL → catalog extracted live, gaps flagged (no sizes, no return policy) → agent-ready storefront published.
- 1:15–2:05 — Three simulated shoppers ("gift under $30", "unscented, ships by Friday", "cheapest refill") buy through the agent tools; PayPal sandbox checkout completes; one fails on missing shipping info → fix suggested and accepted → rerun succeeds.
- 2:05–2:40 — Agent conversion score before/after; dashboard of what agents searched for and couldn't find.
- 2:40–3:00 — Why it matters: PayPal's agentic commerce reaches the long tail of small sellers.

---

## Independent judge review (Oct 6, 2026)

A separate agent, given only this file, the judging rules and the competitor scan, scored both ideas as the PayPal panel would.

| | Tech | Design | Impact | Innovation | Presentation | Total |
|---|---|---|---|---|---|---|
| A: Rebuttal | 8 | 8 | 7 | 6 | 7 | **36** |
| B: Shelfready | 6 | 6 | 6 | 6 | 8 | **32** |

- Estimated chance of at least one cash prize: A about 40%, B about 22% (rough estimates).
- A's biggest risk: the demo looking staged or breaking on camera; the script was overloaded.
- B's biggest risk: looking like a rebuild of PayPal's own Store Sync; generic checkout as the PayPal surface.
- Change adopted for A: make the AI-assistant wrong-size dispute the hero case, keep sponsor views as short
  cutaways, show the eval number on screen.
- Verdict: build A.
