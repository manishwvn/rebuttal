# Rebuttal: 3-minute demo video script

Draft 1, Oct 9, 2026 (due Oct 12; rough cut Oct 23; final Week 5). Built from `docs/pitches.md` (script A and the judge
review), `STATUS.md` and the dashboard as it exists today (`frontend/`, PR #3). The hero shots (segments 2-5) were
dry-run on Oct 9 against the real dashboard build and the mock backend with the rules reasoner, and the selectors,
assertions and on-screen text below come from that run. The Groq variant of the same shots is not rehearsed yet.

Target runtime **2:45** with the AG Studio segment, **2:31** without it. Hard limit 3:00.

## 1. At a glance

One hero case (`agent_wrong_size`, dispute PP-D-2000 in the seeded mock): a buyer's AI shopping assistant was told
"medium", the order was for a large, the buyer disputes. Rebuttal compares the two in code, the model's first pick is
a free replacement, the guard turns it into a refund after the return because PayPal does not allow a replacement
offer on this dispute, the merchant edits one line and approves, one PayPal call goes out. Two cutaways: the safety
design and the eval numbers. The earlier script (pitches.md, A) also had an escalated claim with an evidence PDF and a
Bryntum board; both are cut because the judge review said the script was overloaded.

| # | Time | Length | Segment | Words | Words/s | Main criteria |
|---|---|---|---|---|---|---|
| 1 | 0:00-0:10 | 10 s | Hook: the problem and the new kind of dispute | 24 | 2.4 | Impact, Presentation |
| 2 | 0:10-0:22 | 12 s | Open the case, run the agent | 27 | 2.3 | Tech, Design |
| 3 | 0:22-0:46 | 24 s | AI-assistant mismatch and the facts | 44 | 1.8 | Innovation, Tech (Agentic Commerce) |
| 4 | 0:46-1:10 | 24 s | The decision and the guard | 46 | 1.9 | Tech, Innovation (PayPal + AI) |
| 5 | 1:10-1:34 | 24 s | Edit, approve, one PayPal call | 41 | 1.7 | Design, Tech (PayPal) |
| 6 | 1:34-1:52 | 18 s | Cutaway A: the safety design | 39 | 2.2 | Tech, Impact |
| 7 | 1:52-2:10 | 18 s | Cutaway B: the eval numbers | 38 | 2.1 | Tech (PayPal + AI), Presentation |
| 8 | 2:10-2:24 | 14 s | [PLANNED] AG Studio dashboard | 19 | 1.4 | Design, Impact (AG Grid prize) |
| 9 | 2:24-2:45 | 21 s | Close: impact, what is real and what is demo | 47 | 2.2 | Impact, Presentation |
| | | **165 s** | | **325** | **2.0 avg** | |

Pace check: 325 words in 165 s is 118 words per minute on average; the fastest single row is 2.46 words per second
(148 wpm, the 2:32-2:45 row). Counts are computed from the narration cells, not estimated.
The slack is on purpose: the viewer needs silent moments to read the screen. Without segment 8: 306 words in 151 s.

Burned-in captions (added in editing, not in the app):

- Bottom right for segments 1-5: "Mock PayPal sandbox. Demo data."
- Segment 1, small lower-left tag: "Inbox: AG Grid".

## 2. Rules for this script

- **Honest claims only.** Every spoken claim is in the claims ledger (section 5) with its evidence. Tags used below:
  **[PLANNED]** not built yet, **[TBD]** a number we do not have yet, **[VERIFY]** check before recording,
  **[CONDITIONAL]** say it only when the stated condition is true.
- **No invented statistics.** The script has no industry numbers (chargeback rates, losses). If you want one, add it
  with a source and put the source on screen.
- Numbers are spoken as words. Say "PayPal", "Rebuttal", "Atlas", "AG Grid" plainly. No hype words.
- Narration is the text inside curly quotes. Square-bracket notes are for the editor, not for speech.

## 3. Segments

Criteria abbreviations follow the judging categories: **Tech** (Technological Implementation), **Design**,
**Impact**, **Innovation**, **Presentation**. Prize names in brackets: Agentic Commerce, PayPal + AI, Most Impactful,
AG Grid, APIMatic.

### Segment 1: Hook (0:00-0:10)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 0:00-0:10 | URL `http://localhost:4173/` (the dashboard has one page, no routes). Header "Rebuttal / PayPal dispute desk", badge `mock / groq`. The Simulator panel is above the inbox and stays visible. Inbox (AG Grid) shows six rows sorted by Age: PP-D-2003 4h, PP-D-2000 28h, PP-D-2002 2d 4h, PP-D-2004 4d 4h, PP-D-2001 7d 4h, PP-D-2005 8d 4h, every Status "Not analyzed". Cursor hovers the PP-D-2000 row ($48.00, Not as described). Tags: "Inbox: AG Grid", "Mock PayPal sandbox. Demo data." | “Every PayPal dispute costs a small seller time and money. And now there's a new kind: the buyer's AI assistant ordered the wrong size.” | Impact, Presentation, Agentic Commerce |

### Segment 2: Open the case, run the agent (0:10-0:22)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 0:10-0:16 | Click row PP-D-2000. The case panel shows "PP-D-2000", "Not as described", "$48.00" and the note "The agent has not looked at this dispute yet. Analyzing only reads from PayPal; nothing is sent." with the button "Analyze dispute". The inbox row is highlighted. | “This is Rebuttal. Normally a PayPal webhook starts it; here I click Analyze.” | Tech (webhook-driven), Presentation |
| 0:16-0:22 | Click "Analyze dispute"; the button reads "Analyzing…", then the case view fills in: "PP-D-2000 · INQUIRY", "Not as described", "Priya Shah · $48.00 disputed", green pill "8d 21h left to respond", amber pill "Pending". Inbox row now reads "Refund after the item is returned / Pending". [With the model this takes a few seconds: cut or speed-ramp the wait in editing.] | “It only reads: the dispute from PayPal, plus the order, tracking and store policies.” | Tech (read-only analysis), Design |

### Segment 3: The AI-assistant mismatch and the facts (0:22-0:46)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 0:22-0:32 | Scroll so the buyer quote and the teal assistant panel fill the frame. Quote: "I asked for a medium. This is a large. Not what I ordered." Panel title "Bought by the buyer's AI assistant: instruction vs what shipped". Left card "Atlas (buyer's AI shopping assistant) was told": "Get my brother the navy linen shirt in medium, under $60." Right card "What shipped": "Linen shirt (Navy / Size L)". Red pill "The order did not match the instruction". Caption (editor): "Order record and assistant instruction are demo data." | “The buyer says she asked for a medium. Her assistant, Atlas, was told the same, and ordered a large.” | Innovation, Agentic Commerce |
| 0:32-0:46 | Scroll so both lower panels are in frame. Left panel "Facts computed in code": ✓ Order found: Linen shirt (Navy / Size L); ✓ Tracking is on the PayPal transaction; ✓ USPS 9400111899223344556677: delivered 2026-10-01; ✓ Delivered to the address on the order; i Inside the return window; i Buyer has not asked for a refund; ✓ No duplicate charge found; i Purchased 8 days ago. Slow cursor run down the checkmarks. | “The store shipped exactly what was ordered, to the right address. Every one of these facts is computed in code, not guessed by a model.” | Tech, Innovation |

### Segment 4: The decision and the guard (0:46-1:10)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 0:46-0:56 | Same scroll. Right panel "Why this proposal": "Reasoner (groq)" = "Offer a free replacement"; "Final action" (bold) = "Refund after the item is returned"; a confidence bar with a percentage. Cursor rests on the Reasoner line, then moves to Final action. [VERIFY at record time: the Reasoner line must read the replacement and the source must read groq; see 4.1.] | “Now the decision. The model's first instinct is a free replacement, which would keep the sale.” | Tech (PayPal + AI), Innovation |
| 0:56-1:10 | Zoom on the amber box "Guard adjusted this": "OFFER_REPLACEMENT is not possible on this dispute: PayPal does not allow it (allowed_response_options); proposing OFFER_RETURN_FOR_REFUND instead." Then scroll to the black-bordered proposal card: heading "Offer full refund of $48.00 after return", the dashed call line `POST /v1/customer/disputes/PP-D-2000/make-offer · offer_type REFUND_WITH_RETURN`, and the message box (Hi Priya, sorry about the mix-up… we'll ship the right one as soon as the return is scanned). | “But PayPal only allows refund offers on this dispute. The guard catches that and proposes a full refund once the return is scanned, and the message promises the right size.” | Tech (guard), Innovation, Best Use of PayPal |

### Segment 5: Edit, approve, one PayPal call (1:10-1:34)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 1:10-1:18 | Click into the message box, caret to the end, type " Thank you for your patience." at human speed. The button changes from "Approve" to "Approve with my edits". | “I add a line in my own words, then approve.” | Design, Presentation |
| 1:18-1:28 | Click "Approve with my edits". Modal "Send this to PayPal with your edits?": "Approving makes exactly this one call to the PayPal sandbox:" Call `POST /v1/customer/disputes/PP-D-2000/make-offer`; Action "Offer full refund of $48.00 after return"; Offer type `REFUND_WITH_RETURN`; Amount "$48.00"; Message with the pill "Your edited version". | “Before anything leaves, it shows the exact PayPal call: make offer, refund with return, forty-eight dollars, with my wording.” | Design, Tech (approval gate) |
| 1:28-1:34 | Click "Approve and send". Modal closes, pill "Pending" becomes green "Executed", green bar "Sent to PayPal. Offer full refund of $48.00 after return." The message box is read-only. Scroll the audit trail into view: gather, decide, guard, propose, then approve ("Merchant approved with an edited message"), execute ("Sent to PayPal: Offer full refund of $48.00 after return"), record ("Recorded as EXECUTED"). Inbox row reads Executed. | “One click. The audit trail records my approval and the single write.” | Tech (audit log), Presentation |

### Segment 6: Cutaway A, the safety design (1:34-1:52)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 1:34-1:44 | [Static card, not the app; see 4.3.] The graph as one left-to-right row: "gather (read-only GET)" > "decide (the only model call)" > "guard" > "plan one action" > "human approves, edits or rejects" > "execute (the only PayPal writes)". Source: README mermaid diagram and `backend/rebuttal/agent/graph.py`. | “Why trust it? Only one step in the app can write to PayPal, and it won't run without a human approval.” | Tech, Impact |
| 1:44-1:52 | Terminal. Command `cd backend && uv run pytest tests/test_write_boundary.py "tests/test_core.py::test_analyze_never_writes_to_paypal" -v`. The viewer sees test names scroll (`test_execute_refuses_to_run_without_an_approval`, `test_only_approve_and_edit_route_to_execute`, `test_analyze_never_writes_to_paypal`) and the last line "24 passed". [VERIFY the count on the release commit; it was 24 on Oct 9.] | “Analysis runs on a read-only client, and tests scan the code for any other route to a write.” | Tech |

### Segment 7: Cutaway B, the eval numbers (1:52-2:10)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 1:52-2:02 | [Static card from `backend/evals/RESULTS.md` and an `evals.run --rules` run; see 4.3.] Title "20 labeled disputes". Two columns. Left: "Rules only, no model: 85% overall, hard cases 1 of 4". Right (greyed until the next row): "Model + guard (Groq qwen/qwen3.8-27b)". Footer, small: "4 hard cases = the buyer's wording changes the right answer." | “Twenty labeled disputes. A rules-only baseline solves one of the four hard cases, where the buyer's words change the answer.” | Tech (PayPal + AI) |
| 2:02-2:10 | Same card, right column lights up: "90% (18 of 20), hard cases 4 of 4, PayPal writes before approval: 0". Footer chips: "Single run; runs swing 80-95%. The 20 cases were used for tuning." and "Held-out set, 10 cases: [TBD]". | “The model plus the guard solves all four: eighteen of twenty overall, with zero PayPal writes before approval.” | Tech, Presentation |

[CONDITIONAL, once the held-out run exists (STATUS next step 1): replace the footer chip with the real number and add
"On ten cases I never tuned against, it got N." only if you can drop about 5 seconds elsewhere (cut the 1:10-1:18
row first).]

### Segment 8: [PLANNED] AG Studio dashboard (2:10-2:24)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 2:10-2:24 | **[PLANNED] Do not record until tasks B1 and B2 in `docs/autopilot/QUEUE.md` are merged.** Intended shot: AG Studio dashboard in the Rebuttal theme (tokens from `preview/template.html`). Custom widgets: disputes by reason and by product, money kept versus refunded, response deadlines, model-versus-final agreement from the audit log. Then the Studio agent box with a plain-English question, for example "Which products cause the most disputes?" and its read-only answer. Replace this row with what actually shipped. | “[PLANNED, rewrite to match what shipped] In AG Studio, the merchant sees what disputes cost and what was kept, and asks questions in plain English.” | Design, Impact (AG Grid prize) |

If Studio is not ready by the freeze (Nov 3): drop this row, keep the "Inbox: AG Grid" tag from segment 1, and the video
runs 2:31. Do not describe AG Studio in the voice-over unless the shot exists.

### Segment 9: Close (2:24-2:45)

| Time | On screen | Narration | Criterion |
|---|---|---|---|
| 2:24-2:32 | [Static card.] Large text: "The agent does the digging. The merchant makes the call." Under it, the hero in one line: "$48 order, AI assistant ordered L, told M: refund after return, the right size promised, approved in one click." | “Rebuttal is for the shop with no dispute team: the agent digs, the merchant decides.” | Impact, Presentation (Most Impactful) |
| 2:32-2:45 | [Static card, two columns.] Real: "PayPal sandbox API, signed webhooks, Render deployment, Groq model, Supabase Postgres, AG Grid inbox, 20-case eval, write-boundary tests." Demo: "This recording runs on a mock sandbox. Order records and the assistant's instruction are seeded demo data. Sandbox only: no live money." End line: "github.com/manishwvn/rebuttal, MIT licence". Small credits line: "PayPal Disputes, Orders and Webhooks APIs · LangGraph · AG Grid · Render · Supabase · Langfuse". [CONDITIONAL, add "APIMatic Context Plugin for PayPal" to the credits only when `docs/apimatic-log.md` has real entries; its table is empty on Oct 9.] | “This recording used a mock of PayPal's sandbox. The same code runs on Render against the real sandbox: a dispute filed there arrived by signed webhook and stopped at the approval gate.” | Tech, Impact, Presentation (honesty) |

[PLANNED, optional 3-4 s insert for 2:38 onward once task A5 ships: the dashboard served from the Render service
showing the live sandbox dispute at "Pending". Mask the API token; never show it.]

## 4. Shot list for the automated recorder

The recorder is task B4 (Playwright plus `ffmpeg`). Everything in 4.2 for shots 1-10 was dry-run on Oct 9 against the
real dashboard and the mock backend (rules reasoner) and passed; the model variant needs one rehearsal.

### 4.1 Setup

Fresh backend process for every take: the mock is in memory, and after one approval PP-D-2000 is EXECUTED.

```bash
# Terminal 1. Mock PayPal sandbox, real model (Groq key comes from backend/.env), no database, no tracing.
cd backend
REBUTTAL_MOCK=1 REBUTTAL_ALLOW_OPEN_API=1 REBUTTAL_API_TOKEN= DATABASE_URL= REBUTTAL_CHECKPOINT_URL= \
  REBUTTAL_TRACING=0 REBUTTAL_AUDIT_PATH="$TMPDIR/rebuttal-video-audit.jsonl" \
  REBUTTAL_CORS_ORIGINS=http://localhost:4173 uv run uvicorn rebuttal.app:app --port 8000

# Terminal 2. The production build of the dashboard (not `npm run dev`, see quirk Q3).
cd frontend && npm ci && npm run build && npx vite preview --port 4173 --strictPort

# Gate: the badge and health must say groq. If it says rules the model is not wired, stop.
curl -s localhost:8000/api/health        # expect "mode":"mock / groq"
```

Variant R (deterministic fallback): add `REBUTTAL_REASONER=rules`. The badge reads `mock / rules` and the Why panel
reads "Reasoner (rules)". Say "The baseline reasoner's first instinct" in segment 4 instead of "The model's", and the
AI evidence in the video rests on segments 7 and 9. The shots behave identically, so use this to test the recorder
without spending Groq tokens (the 200k daily quota is shared with the live service).

Model non-determinism: if the Reasoner line does not read "Offer a free replacement" (the model picked the refund
directly), the guard beat in segment 4 disappears. Restart the backend and retake; the live Oct 7 run with Groq picked
the replacement and the guard converted it.

### 4.2 Playwright conventions and steps

- Chrome (`channel: 'chrome'`), viewport 1280x720, `colorScheme: 'light'`. At 1280 wide the page fills its 1180 px
  column and the type stays readable on a phone.
- **Freeze the page clock before `goto`:** `await page.clock.setFixedTime(new Date('2026-10-06T16:00:00Z'))`. The mock
  runs on a fixed clock (2026-10-06 15:00 UTC) while the inbox "Age" column uses the browser's clock; without this the
  ages grow with the real date (Oct 23 would show PP-D-2000 as "17d") and contradict "8d 21h left to respond".
- Each shot has a target duration equal to its time range. After the actions, `waitForTimeout(target - elapsed)`; when
  the narration audio exists, use its measured length instead.
- Wait 800 ms after any grid update (AG Grid animates row moves). Smooth scroll with
  `el.scrollIntoView({behavior: 'smooth', block: 'center'})` then wait 700 ms.
- Selectors are the dashboard's own: `[row-id="PP-D-2000"]`, `getByTestId('mode-badge' | 'case-view' |
  'assistant-panel' | 'facts' | 'reasoner-choice' | 'final-action' | 'guard-notes' | 'paypal-call' | 'send-summary' |
  'send-message' | 'case-status' | 'audit-trail')`, `getByLabel(/Message the buyer will receive/)`, and buttons by name.
- Use the seeded dispute `PP-D-2000`. Do not use the Simulator panel for the hero (quirk Q1).

| Shot | Video time | Steps (deterministic) | Waits and assertions |
|---|---|---|---|
| 0 | before recording | Start both servers (4.1). Create the context, freeze the clock, `goto('/')`. | `mode-badge` contains "mock / groq". `[row-id="PP-D-2000"]` visible. `locator('[row-id]').count()` equals 6. Row status cell reads "Not analyzed". |
| 1 | 0:00-0:10 | Start recording. Hover the PP-D-2000 row. | Hold to 0:10. |
| 2 | 0:10-0:16 | Click `[row-id="PP-D-2000"]`. | "Analyze dispute" button visible; text "The agent has not looked at this dispute yet". Hold to 0:16. |
| 3 | 0:16-0:22 | Click "Analyze dispute". | Wait for `assistant-panel` visible (timeout 60 s, then cut the wait). `case-status` reads "Pending". Row status cell reads "Pending". Hold the case header in view. |
| 4 | 0:22-0:32 | Smooth-scroll the buyer quote (`blockquote.quote`) to the top of the viewport. | `assistant-instruction` contains "navy linen shirt in medium"; `assistant-shipped` contains "Size L"; panel contains "did not match the instruction". |
| 5 | 0:32-0:46 | Smooth-scroll the facts and Why panels (`#facts-title` parent grid) to the centre. Cursor moves down the facts. | `facts` contains "Delivered to the address on the order" and "No duplicate charge found" (aborts a take that hit quirk Q1). |
| 6 | 0:46-0:56 | Hover the Reasoner line, then Final action. | `reasoner-choice` equals "Offer a free replacement"; `final-action` equals "Refund after the item is returned". The `dt` text contains "Reasoner (groq)". Any mismatch: abort and retake. |
| 7 | 0:56-1:10 | Scroll `guard-notes` to centre (about 5 s), then scroll the proposal card (parent of `paypal-call`) to the top. | `guard-notes` contains "OFFER_REPLACEMENT is not possible on this dispute". `paypal-call` contains "make-offer" and "REFUND_WITH_RETURN". |
| 8 | 1:10-1:18 | Focus the message box, `el.setSelectionRange(len, len)`, `pressSequentially(' Thank you for your patience.', {delay: 40})`. | Button "Approve with my edits" visible. |
| 9 | 1:18-1:28 | Click "Approve with my edits". | `getByRole('dialog')` visible. `send-summary` contains `POST /v1/customer/disputes/PP-D-2000/make-offer`, `REFUND_WITH_RETURN`, `$48.00`. `send-message` ends with "Thank you for your patience." |
| 10 | 1:28-1:34 | Click "Approve and send" in the dialog. Wait for the dialog to hide, then smooth-scroll `audit-trail` to the end of the viewport. | `case-status` reads "Executed"; row status cell reads "Executed"; audit `data-step` values equal gather, decide, guard, propose, approve, execute, record; audit text contains "Merchant approved with an edited message". |
| 11 | 1:34-1:44 | Cutaway card A (static page, 4.3). | n/a |
| 12 | 1:44-1:52 | Terminal clip T1 (4.3). | Last line contains "24 passed" [VERIFY]. |
| 13 | 1:52-2:10 | Cutaway card B (static page, 4.3), two states (left only, then both columns). | Numbers equal the verified table in 4.3. |
| 14 | 2:10-2:24 | **[PLANNED]** AG Studio view. Not scriptable yet. | n/a |
| 15 | 2:24-2:45 | Close cards C and D (static pages, 4.3). | n/a |

Reference snippet for shots 0-10 (dry-run verified on the mock with the rules reasoner; not committed as code):

```ts
await page.clock.setFixedTime(new Date('2026-10-06T16:00:00Z'))
await page.goto('http://localhost:4173/')
await page.locator('[row-id="PP-D-2000"]').click()
await page.getByRole('button', { name: 'Analyze dispute' }).click()
await page.getByTestId('assistant-panel').waitFor({ timeout: 60_000 })
const draft = page.getByLabel(/Message the buyer will receive/)
await draft.focus()
await draft.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(el.value.length, el.value.length))
await draft.pressSequentially(' Thank you for your patience.', { delay: 40 })
await page.getByRole('button', { name: 'Approve with my edits' }).click()
await page.getByRole('dialog').getByRole('button', { name: 'Approve and send' }).click()
await page.getByTestId('case-status').filter({ hasText: 'Executed' }).waitFor()
```

### 4.3 Shots that need something other than the dashboard

| Need | Used in | What it is | Status |
|---|---|---|---|
| Terminal clip T1 | Shot 12 | The real stdout of the pytest command in segment 6. Either screen-record Terminal.app, or run the command with `tee` and render the captured text in a monospace HTML card and screenshot it. Do not fake the output. | Command works today (24 passed in about 2 s). |
| Static card A | Shot 11 | The pipeline row from segment 6, drawn in the dashboard's design tokens (`preview/template.html`: ink `#14202e`, accent `#0e6b63`, background `#f2f5f8`; Bricolage Grotesque, Public Sans, JetBrains Mono). | To author in B4. |
| Static card B | Shot 13 | Eval numbers. Verified Oct 9: Groq `qwen/qwen3.8-27b` run `groq-qwen3.8-27b-20261007-112629`: 90% overall (18 of 20), standard 88%, hard 100% of 4, gate violations 0. Rules baseline (`uv run python -m evals.run --rules`, run on this commit Oct 9): 85% overall, 100% standard, 25% hard (1 of 4), gate violations 0. Re-run `--rules` on the release commit in a throwaway checkout, because it rewrites `evals/RESULTS.md` and adds a file under `evals/results/`. | Numbers verified; card to author. Held-out chip is [TBD] (task A2). |
| Static cards C and D | Shot 15 | Close cards from segment 9. | To author in B4. |
| AG Studio view | Shot 14 | See segment 8. | **[PLANNED]** tasks B1, B2. |
| Live-proof insert | Segment 9, optional | Dashboard on the Render service with the live dispute pending. | **[PLANNED]** task A5. |
| Audio | all | Rough cut: macOS `say` from section 7. Final: Manish's own voice, same text. | B4 / USER item. |

Video capture: Playwright's `recordVideo` needs its own ffmpeg build (`npx playwright install ffmpeg`, a download:
ask Manish first). Joining audio and cards needs `brew install ffmpeg`. Neither is installed on this machine today.

### 4.4 Quirks found in the dry run (do not rediscover them)

- **Q1: do not use the Simulator for the hero, and do not reuse `docs/screenshots/hero-case.png`.** The simulator
  cycles six buyers, so a new hero dispute can land on the same buyer, amount and day as the seeded PP-D-2000 (the
  third simulated dispute does). The duplicate-charge fact then fires and the facts list shows a red "2 matching
  charges on the purchase day". That screenshot has exactly that. The seeded PP-D-2000 on a fresh backend shows a green
  "No duplicate charge found".
- **Q2: clock.** See 4.2. Audit-trail times show the real recording date (they come from the server as ISO strings);
  harmless, but keep the audit trail small in frame.
- **Q3: `npm run dev` breaks the confirm dialog.** In the Vite dev server the "Approve" modal closes immediately and
  never shows (observed). Likely cause: React StrictMode runs the effect in `ConfirmDialog` twice, and the cleanup's
  `dialog.close()` fires `onClose`, which calls `onCancel`. The production build (`vite preview`) works and is what the
  e2e suite uses. Record from the build. Worth a follow-up fix in `frontend/src/components/ConfirmDialog.tsx`.
- **Q4: one take per backend process.** Restart the backend between takes.
- **Q5: Groq latency.** With the model the Analyze step takes seconds, not milliseconds; shot 3 waits for the assistant
  panel, and the editor trims the wait.

## 5. Claims ledger

Every factual claim spoken or shown, and what backs it. "Demo" means true of the recording, not of a real shop.

| Claim | Evidence | Status |
|---|---|---|
| A PayPal webhook starts the agent | `backend/rebuttal/app.py` (only `CUSTOMER.DISPUTE.CREATED` starts an analysis, signature verified); proven live Oct 7 (STATUS) | Verified |
| Analysis only reads | Analysis nodes hold `client.read_only()`; `tests/test_write_boundary.py`, `test_analyze_never_writes_to_paypal` | Verified (ran Oct 9, 24 passed) |
| The assistant was told "medium", the order was a large | `evals/cases.json` `agent_wrong_size`, seeded into the mock | **Demo data.** No real assistant integration exists; the shop's own order record holds the instruction (store policy: "We store the assistant's purchase instructions with the order") |
| Facts are computed in code | `backend/rebuttal/agent/facts.py` | Verified |
| "The model's first instinct is a free replacement" | Live Oct 7: Groq chose OFFER_REPLACEMENT, guard converted it (STATUS). Rules baseline does the same in mock. | Verified live; **[VERIFY]** in mock plus Groq at record time (shot 6 asserts it) |
| "PayPal only allows refund offers on this dispute" | The guard reads PayPal's `allowed_response_options`; `evals/cases.json` `why`; the mock mirrors the sandbox | Verified for this dispute type. Whether any replacement offer type exists is an open Discord question, so the narration says "on this dispute" |
| The buyer message "promises the right size" | After the guard, the message is a fixed template (`draft_message` in `reasoner.py`), not model text | Verified. Do not say the model wrote it. |
| One approval, one PayPal call, audit trail | `approval.py` `execute`; e2e test `hero case…approve with an edited message` | Verified (mock) |
| Only one step in the app can write to PayPal | `approval.py`, `permit_writes()`, `test_write_boundary.py`. Named manual scripts (`spike_sandbox`, `make_test_order`) are outside the app | Verified; wording says "in the app" |
| 20 labeled disputes, 4 hard | `evals/cases.json` | Verified |
| 90% (18 of 20), hard 4 of 4, zero writes before approval | `evals/RESULTS.md`, run `groq-qwen3.8-27b-20261007-112629` | Verified; single run, runs swing 80-95%, the set was used for tuning (shown on the card). The guard rule `f4cb66d` came after that run, so current code is unmeasured. |
| Rules-only baseline solves 1 of 4 hard cases | `evals.run --rules` on this commit, Oct 9: 85% overall, 25% hard | Verified |
| Held-out result | `evals/holdout.json`, not run yet | **[TBD]** |
| Runs on Render against the real sandbox; a dispute arrived by signed webhook and stopped at the approval gate | STATUS "Webhook proven live", dispute `PP-R-SVN-10190455` | Verified Oct 7. Not yet shown approving a write on the live sandbox through the dashboard |
| Inbox is built with AG Grid | `frontend/src/components/Inbox.tsx` (AG Grid Community) | Verified |
| AG Studio dashboard, Studio agent | none yet | **[PLANNED]** B1, B2 |
| APIMatic Context Plugin shaped the PayPal code | Plugin installed Oct 6; `docs/apimatic-log.md` table is empty | **[CONDITIONAL]** do not claim until entries exist |
| 8d 21h left to respond | Mock assumes a 10-day inquiry window (`scenarios.py`, marked VERIFY: the real sandbox omitted the due date on an inquiry under review) | Demo number; the narration does not say it |
| "Costs a small seller time and money"; "a new kind of dispute" | Opinion, no source | Unsourced framing; fine for a hook, no figure attached |

## 6. Open items

For Manish or the lead:

1. Decide Groq (needs a key in `backend/.env` and a take that shows the guard beat) versus the rules variant for the
   final recording of segment 4. The Groq run is the stronger "PayPal + AI" evidence.
2. Run the held-out eval (A2) before the final cut and fill the card chip; do not change code afterwards.
3. APIMatic: log real uses in `docs/apimatic-log.md` (candidate uses are listed there) before saying anything about it.
4. Segment 8 depends on B1 and B2; the freeze is Nov 3.
5. Fix or document quirk Q3 (dev-mode confirm dialog). Regenerate `docs/screenshots/hero-case.png` from the seeded
   PP-D-2000 (its spec uses the Simulator) so it does not show the false duplicate-charge mark (quirk Q1).
6. Approve the ffmpeg downloads for B4 (4.3).
7. Optional: one real approve on a live sandbox dispute, then add one sentence to segment 9.

## 7. Narration only (for text to speech)

Plain text, in order. Pauses are marked with a line of three dots; leave them in the audio so the screen can be read.

```
[1, 0:00]
Every PayPal dispute costs a small seller time and money. And now there's a new kind: the buyer's AI assistant ordered the wrong size.
...
[2, 0:10]
This is Rebuttal. Normally a PayPal webhook starts it; here I click Analyze.
...
It only reads: the dispute from PayPal, plus the order, tracking and store policies.
...
[3, 0:22]
The buyer says she asked for a medium. Her assistant, Atlas, was told the same, and ordered a large.
...
The store shipped exactly what was ordered, to the right address. Every one of these facts is computed in code, not guessed by a model.
...
[4, 0:46]
Now the decision. The model's first instinct is a free replacement, which would keep the sale.
...
But PayPal only allows refund offers on this dispute. The guard catches that and proposes a full refund once the return is scanned, and the message promises the right size.
...
[5, 1:10]
I add a line in my own words, then approve.
...
Before anything leaves, it shows the exact PayPal call: make offer, refund with return, forty-eight dollars, with my wording.
...
One click. The audit trail records my approval and the single write.
...
[6, 1:34]
Why trust it? Only one step in the app can write to PayPal, and it won't run without a human approval.
...
Analysis runs on a read-only client, and tests scan the code for any other route to a write.
...
[7, 1:52]
Twenty labeled disputes. A rules-only baseline solves one of the four hard cases, where the buyer's words change the answer.
...
The model plus the guard solves all four: eighteen of twenty overall, with zero PayPal writes before approval.
...
[8, 2:10, PLANNED, record only if the AG Studio shot exists]
In AG Studio, the merchant sees what disputes cost and what was kept, and asks questions in plain English.
...
[9, 2:24]
Rebuttal is for the shop with no dispute team: the agent digs, the merchant decides.
...
This recording used a mock of PayPal's sandbox. The same code runs on Render against the real sandbox: a dispute filed there arrived by signed webhook and stopped at the approval gate.
```
