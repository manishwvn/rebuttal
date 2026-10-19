# Autopilot task queue

Ordered. The lead takes the first runnable task each cycle (see `CYCLE.md`). Status: `todo`, `in-progress`,
`waiting: <why>`, `done <PR>`. Sizes: S (under an hour of agent work), M, L (split into several PRs). A large task
may carry an explicit share done as `[NN%]` in its status. `docs/autopilot/progress.py` turns this file into the
project completion percent (CYCLE.md section 7).
Deadlines: video script Oct 12, AG Studio first pass and demo-video rough cut Oct 23, **feature freeze Nov 3**,
final check Nov 8, Manish submits Nov 10 (hard deadline Nov 12, 12:00 PM PT).

## Tasks

### R25 Guard: single-shot fallback, no refund substitution for turn-based refusals, no crash surfaces as bare 500 — size M — done #106 — audit Oct 19, priority now
Files: backend/rebuttal/agent/reasoner.py (guard, fallback at ~362, PAYPAL_ALTERNATIVES block ~473-500), backend/rebuttal/app.py.
Evidence (verified at f038629): seed cnp_refunded with status UNDER_REVIEW or WAITING_FOR_BUYER_RESPONSE and allowed_response_options=None. RuleReasoner gives SUBMIT_REFUND_PROOF, and guard() raises RecursionError. paypal_allows refuses it through SELLER_TURN_ONLY, then the alternative OFFER_RETURN_FOR_REFUND hits the refund-issued check and calls fallback(), which calls guard() again. The 'Cannot loop' comment at 366-370 is false. End to end on the mock: Runtime(seed_cases=['cnp_refunded']).analyze -> approve -> EXECUTED (mock status UNDER_REVIEW) -> analyze again -> RecursionError. Afterwards approvals.latest_for() is None and snapshot.next == ('guard',), so the executed proposal vanishes from the dashboard. The Analyze button reappears and crashes again. POST /api/disputes/{id}/analyze and the public /api/demo analyze catch only PayPalError/TransportError, and there is no app.exception_handler, so the client gets a bare 500 with no CORS headers. Related: duplicate_false at UNDER_REVIEW turns SUBMIT_EVIDENCE into OFFER_RETURN_FOR_REFUND (a money proposal for a charge that was not duplicated). The note says 'PayPal does not allow it (allowed_response_options)' even though no option list exists and the real reason is turn order. At line 492, `_, fallback = effective_options(...)` shadows the nested fallback().
Fix: (1) guard() gets a private `_depth` argument. On the second pass it never calls fallback() again: it keeps the rules' choice, caps confidence at 0.3 and adds 'not possible now; resolve in Resolution Center or wait for the buyer'. (2) Look for PAYPAL_ALTERNATIVES only when the refusal comes from PAYPAL_REQUIRES (an offer or accept type is missing), never for a SELLER_TURN_ONLY or status refusal. (3) Make the note name the real cause: not the seller's turn, versus not in the list. (4) Rename the local to used_fallback_options. (5) Add a generic Exception handler in app.py and the demo router that logs and returns JSON 500 through the CORS middleware.
Acceptance: new tests (a) guard() returns for cnp_refunded and holdout2 ho2_dup_already_refunded at UNDER_REVIEW and WAITING_FOR_BUYER_RESPONSE; (b) graph test: analyze, approve, analyze again on cnp_refunded does not raise, and a proposal is still visible; (c) SUBMIT_EVIDENCE on duplicate_false at UNDER_REVIEW does not become a refund offer; (d) an unexpected exception in a route returns JSON 500. A sweep over all cases x statuses x resolutions shows 0 RecursionErrors. All existing tests stay green, including test_write_boundary.py. Do not touch approval.py's execute path.

### R26 Hero offer note must match the refund action — size S — done (R26 PR) — audit Oct 19, priority now
Evidence: agent_wrong_size (the hero case) proposes make_offer REFUND_WITH_RETURN $48.00 with note 'Send it back and we'll ship the right one as soon as the return is scanned.' The note never mentions the refund. CaseView.tsx:432 warns 'The message below also promises a replacement.' A buyer who reads it, or a judge in the approve dialog, sees a refund action next to a replacement promise. If the merchant honours both, they pay twice. Cause: the guard swaps OFFER_REPLACEMENT for OFFER_RETURN_FOR_REFUND (reasoner.py ~484-489) but keeps the misorder wording from draft_message.
Fix: when the final resolution is OFFER_RETURN_FOR_REFUND, the draft states the refund first: 'Send it back and we'll refund the $48.00 as soon as the return is scanned; if you'd rather have the right size, reply and we'll ship it instead.' The rules and model paths both go through guard. Keep the replacement option as an explicit alternative.
Acceptance: a test asserts the hero proposal's note contains 'refund' and the amount, and does not unconditionally promise a shipment. scripts.demo preview and frontend e2e are updated. Flag on the U3 video re-record note in the QUEUE whether the approve-dialog shot must be re-recorded.

### R27 Guard money rules: UNAUTHORISED mandate, uncertain address, refund already issued for all reasons — size M — in review (PR #109, items 1 and 2; item 3 split into R27b) — after R25 — audit Oct 19, priority next
Evidence (verified): (1) ho2_unauth_over_cap facts within_agent_spending_limit=False, is_agent_purchase=True: rules give ACCEPT_CLAIM, but guard(SUBMIT_EVIDENCE) and guard(OFFER_PARTIAL_REFUND) pass unchanged with guard_notes []. (2) reasoner.py:198 `if f.get("delivered_address_matches"):` treats None (an uncertain match) as False, so unauth_delivered with None gives ACCEPT_CLAIM. Every other consumer treats None as 'not a misdelivery'. (3) snad_damaged_low_value with refund_issued=True and refunded_amount=amount: guard(ACCEPT_CLAIM) passes with no note. The second-refund check (reasoner.py ~453) covers only CREDIT_NOT_PROCESSED and DUPLICATE_TRANSACTION.
Fix: (1) UNAUTHORISED + SUBMIT_EVIDENCE when is_agent_purchase and not (within_agent_spending_limit and agent_followed_instruction): convert to the rules' choice through the single-shot path from the first task, with a note. (2) For None, return SUBMIT_EVIDENCE at about 0.5 confidence with 'address written differently, check it'. (3) For any reason, when refund_issued and refunded >= amount - 0.01 and the resolution is ACCEPT_CLAIM, OFFER_PARTIAL_REFUND or OFFER_RETURN_FOR_REFUND: add a note, cap confidence at 0.3, and prefer SUBMIT_REFUND_PROOF if paypal_allows it. Do not reuse fallback() in a way that loops.
Acceptance: new unit tests for each of the three cases. Evals main, holdout and holdout2 are run with --rules and show no regression. The guard change is recorded in run.py HOLDOUT2_NOTES as no longer blind for ho2_unauth_over_cap, and README notes are updated. Depends on the first task.

### R27b Refuse a second refund for every dispute reason — size S — waiting: sign-off to change a pinned guard test — split from R27 item (3), priority next
Evidence: R27 item (3). `snad_damaged_low_value` (or any non-CNP/DUP reason) with refund_issued=True and refunded_amount >= amount - 0.01: guard(ACCEPT_CLAIM, OFFER_PARTIAL_REFUND, OFFER_RETURN_FOR_REFUND) passes with no note. The block built in R27 (worker p1, not merged) is in the PR description's history: place it after the CNP/DUP block, add the note 'A refund covering the disputed amount was already issued; refusing a second one.', cap confidence at 0.3, convert to SUBMIT_REFUND_PROOF only if paypal_allows, never call fallback(), ignore refunded_amount None.
Blocker: it contradicts `tests/test_guard_fallback.py::test_a_refund_on_another_reason_does_not_trigger_the_refusal` (R15 pinned `snad_changed_mind` with a full refund staying ACCEPT_CLAIM). Manish decides whether that pin was deliberate; if not, rewrite it to expect SUBMIT_REFUND_PROOF and add tests for full, within-a-cent, partial (unchanged), evidence (unchanged) and refund-proof-not-allowed (cap only).
Acceptance: the tests above; evals --rules on main, holdout and holdout2 show no regression.

### R28 Frontend: handle INTERRUPTED proposals and stop claiming 'Sent to PayPal' for non-executed states — size S — done #105 — audit Oct 19, priority next
Evidence: graph.py:224-225 can return status INTERRUPTED, for example when re-analysis of a REJECTED or EXECUTED dispute fails in gather. frontend/src/types.ts:59 ProposalStatus omits it. labels.ts STATUS_LABEL and STATUS_TONE have no 'interrupted' entry, and the labels.ts:28 comment is stale. CaseView.tsx:340 renders <Outcome>, whose last branch (around line 477) says 'Sent to PayPal.' for any non-REJECTED, non-FAILED status. AnalyticsStatus (types.ts:116) already has INTERRUPTED.
Fix: add INTERRUPTED to ProposalStatus and DisplayStatus, with label 'Interrupted' and tone 'warn'. CaseView shows 'A newer analysis stopped part-way. Nothing new was sent.' plus an 'Analyze again' button (api.analyze). Outcome says 'Sent' only for EXECUTED.
Acceptance: a Playwright e2e test stubs /api/disputes with status INTERRUPTED and asserts the pill reads 'Interrupted' and 'Sent to PayPal' is absent. tsc, lint and vitest pass.

### R29 Approval and boundary hardening: empty edit, HEAD allowance, CORS wiring test, file-mode audit — size S — done #108 — audit Oct 19, priority next
Evidence: approval.py:309-310 `decision="edit" if edited_message else "approve"`. approve(pid, '') reaches EXECUTED with the original draft (verified on the mock), while '   ' returns 409. The UI blocks empty drafts (CaseView.tsx:114 canApprove), so only a direct token-auth API call reaches it. client.py _is_read_only allows HEAD, but the docstrings and CLAUDE.md say 'refuses anything but GET', and no test covers HEAD. tests/test_app.py:106 tests configure_cors on a throwaway app, so removing app.py:53 would leave every test green. audit.py:86 for_dispute reads only this process's in-memory records when there is no DATABASE_URL, so the 'approve' line can repeat after a restart in local file mode.
Fix: branch on `edited_message is not None`. Either drop HEAD from the allow-list or add it to test_only_post_to_the_token_and_verify_paths_passes_the_write_gates, and reword the docs to 'GET/HEAD plus the token and verify-webhook-signature POSTs'. Add a test that reloads rebuttal.app with REBUTTAL_CORS_ORIGINS set and checks a preflight on /api/health. Either make for_dispute read the JSONL file when a path is set, or document that file mode is per-process.
Acceptance: tests: approve(pid,'') raises ApprovalError and mock.write_calls()==[]; the HEAD test; the CORS wiring test. test_write_boundary.py is unchanged or only strengthened.

### R30 Docs and eval-honesty drift sweep — size S — todo — audit Oct 19, priority next
Evidence (verified): README.md:73 says '976 backend tests', but pytest gives 1041 passed. docs/devpost.md:57 says '469 backend tests at 93%' (now 1041 at 96%; 'ten ADRs' is correct). evals/run.py:33-34 and the --set help at :295 say held-out sets are 'never used for tuning', and run.py:161-163 says 'one case later fixed', yet HOLDOUT2_NOTES lists two fixes (ho2_inr_unit_format R16, ho2_dup_already_refunded R15). README.md:222-226 already carries both caveats. frontend/video/cards.ts:196 says 'written blind' with no caveat. docs/deploy.md:138 says 'Not verified here: the uv build/start commands on Render', yet the live service runs. STATUS.md:3 header says Oct 18/R17, but the entries are R21/R22 from Oct 19. docs/autopilot/QUEUE.md:115 and :176 point at docs/evals.md, which does not exist. README lacks a Vite port example and a note on backend/audit.jsonl. frontend/README does not say the AG Studio licence banner is logged with console.error.
Fix: write 'over 1,000 backend tests' (or the exact count) in the README and devpost. Fix the run.py comment, help and section title to 'two cases later fixed', then run `uv run python -m evals.run --rebuild-md`. Add a caveat to the cards.ts held-out line. Correct deploy.md, the STATUS header and the QUEUE paths (to backend/evals/RESULTS.md). Add `VITE_API_BASE=http://localhost:8001 npm run dev -- --port 5174` and a one-line audit.jsonl note to the README, and the console.error note to frontend/README.
Acceptance: grep finds no 976/469 claims, no 'never used for tuning', and no docs/evals.md references. RESULTS.md is regenerated. Tests stay green.

### R31 facts.py: negation-aware refund/damage keywords — size S — todo — audit Oct 19, priority later
Evidence (verified): with the text "i don't want a refund, just send a replacement. the box is not damaged", REFUND_WORDS matches 'refund' (facts.py:291) and DAMAGE_WORDS matches 'damaged' (facts.py:298, no end anchor, so 'torn' also matches 'tornado'). buyer_asks_for_refund then drives guard line ~421, which turns SHARE_TRACKING into ACCEPT_CLAIM on a likely-lost package.
Fix: skip a hit preceded within 3 words by not/n't/no/without/'rather than', and anchor DAMAGE_WORDS with \b at both ends.
Acceptance: tests for 'don't want a refund', 'not damaged' and 'tornado'. Evals --rules on all three sets show no regression.

### R32 Analytics: label unanalyzed disputes and small-sample agreement — size S — todo — audit Oct 19, priority later
Evidence: in a fresh mock session after one hero approval, Analytics shows 'Disputes by product: Unknown 6 / Linen shirt 1' and 'MODEL VS FINAL AGREEMENT 0.0%' (0 of 1). Fix: label unanalyzed disputes 'Not analyzed' (or exclude them from the product chart), and show agreement as n/a when the sample is under 5. Acceptance: a frontend unit or e2e test covers both.

### R15 Guard and rules refuse a second refund — size M — done #96 — audit Oct 18, priority now
Problem: guard() (backend/rebuttal/agent/reasoner.py:336) lets ACCEPT_CLAIM, OFFER_PARTIAL_REFUND and OFFER_RETURN_FOR_REFUND through when facts.refund_issued is True. RuleReasoner._pick DUPLICATE_TRANSACTION branch (reasoner.py:195-201) checks duplicate_charge_found before refund_issued, so it proposes ACCEPT_CLAIM. Evidence: `uv run python -m evals.run --rules --set holdout2` prints 'MISS ho2_dup_already_refunded: expected SUBMIT_REFUND_PROOF, got ACCEPT_CLAIM (rules, conf 0.90)'. The guard has no refund_issued check on refund-type choices; it only checks SUBMIT_REFUND_PROOF at line 356. Also, facts.py:250 `refund_issued = bool(order.refunds)` has no amount, so a partial refund looks like a full one.
Fix: (1) In _pick DUPLICATE_TRANSACTION, return SUBMIT_REFUND_PROOF when refund_issued, before the duplicate check. (2) Add a refunded_amount fact (sum of order.refunds) in facts.py. (3) In guard, when the resolution is in (ACCEPT_CLAIM, OFFER_PARTIAL_REFUND, OFFER_RETURN_FOR_REFUND) and the reason is CREDIT_NOT_PROCESSED or DUPLICATE_TRANSACTION, call fallback('A refund was already issued; refusing a second one.') if refunded_amount >= dispute amount minus 0.01. For a partial refund, keep the choice, add a note and cap confidence at 0.5. (4) For DUPLICATE_TRANSACTION with transaction_search_available True and duplicate_charge_found False, convert ACCEPT_CLAIM to SUBMIT_EVIDENCE with a note. Keep the comment in fallback() that says it cannot loop true.
Acceptance: new tests in backend/tests/test_guard_fallback.py fail on 72b0728 and pass after the change. Cover cnp_refunded + ACCEPT_CLAIM, ho2_dup_already_refunded + ACCEPT_CLAIM/OFFER_PARTIAL_REFUND, duplicate_false + ACCEPT_CLAIM, and a partial refund. `evals.run --rules --set holdout2` no longer misses ho2_dup_already_refunded. Main-set rules score must not drop: final 85%, gate violations 0. In evals/HOLDOUT2_NOTES, note that this fix was prompted by a held-out miss. Full pytest passes.

### R16 Address near-match is 'uncertain', not a misdelivery (backend + Facts panel null handling) — size M — done #100 — audit Oct 18, priority now
Problem: facts.py:27 `_norm` only lowercases and strips commas, so 'Mill Street Apt 4B' and 'Mill St #4B' compare unequal and delivered_address_matches is False. guard (reasoner.py:409-418) then converts SHARE_TRACKING or SUBMIT_EVIDENCE into OFFER_REPLACEMENT, which ships a free item for a parcel that was delivered correctly. Evidence: `evals.run --rules --set holdout2` prints 'MISS ho2_inr_unit_format: expected SHARE_TRACKING, got OFFER_REPLACEMENT'. Cross-component: frontend/src/components/Facts.tsx shows boolean facts with `has(key)` plus `Boolean(value)`, so a null fact renders as a red negative. Today this already shows 'No tracking on the PayPal transaction' when tracking_uploaded_to_paypal is None (not checked, facts.py:151). An 'uncertain' address fact would show 'Delivered to a different address' in the same way.
Fix: normalise addresses (drop punctuation; map street/st, avenue/ave, road/rd, apartment/apt/unit/#). Return True on an exact normalised match. Return None (uncertain) when the house number, postal code and city match but the rest differs. Return False otherwise. The guard keeps converting only on `is False`. On None, it adds a note ('Delivery address written differently; confirm before relying on tracking') and caps confidence at 0.6. Rules _pick must treat None as not-False for the replacement branch. In Facts.tsx, render a neutral row (mark null) when tracking_uploaded_to_paypal or delivered_address_matches is null: 'Tracking on the PayPal transaction was not checked' and 'Delivery address written differently; check it'.
Acceptance: a unit test that 'Mill Street Apt 4B, Reno, NV 89501' and 'Mill St #4B, Reno NV 89501' are not False. A test that a different house number or ZIP is still False. A guard test that ho2_inr_unit_format + SHARE_TRACKING stays SHARE_TRACKING. A Playwright or unit check that a no-order dispute does not show 'No tracking on the PayPal transaction'. ho2_inr_digits_swapped still gets OFFER_REPLACEMENT. pytest, npm run lint and npm run build pass.

### R17 Execute: retry of provide_evidence/accept_claim fails closed; interrupted audit names actions and keys — size S — done #95 — audit Oct 18, priority now
Note: before the Nov 3 freeze a sandbox fixture must confirm the fail-closed result: (1) provide_evidence sent, then read: status is not WAITING_FOR_SELLER_RESPONSE; (2) plain accept_claim sent, then read: same; (3) provide_evidence on an UNDER_REVIEW dispute: PayPal's answer (docs/sandbox-findings.md :116, :231).
Problem: not_allowed_now (backend/rebuttal/approval.py:117-151) returns None for provide_evidence and plain accept_claim on an UNDER_REVIEW or RESOLVED dispute. When PayPal lists no options, effective_options returns options=None. I probed: not_allowed_now({'status':'UNDER_REVIEW'|'RESOLVED', stage CHARGEBACK, no links}, provide_evidence|accept_claim) -> None for all four. So after a send that landed but whose checkpoint was lost, retry() sends a second write POST. The mock hides this only by replaying PayPal-Request-Id, which PayPal does not document for Disputes. The docstring at approval.py:99-100 ('Evidence and accept-claim fall back the same way') is false. Separately, app.py:96 paypal_interrupted writes execute_interrupted on a 5xx or transport error but omits the action kinds and idempotency keys.
Fix: in not_allowed_now, refuse provide_evidence and every accept_claim when dispute.status != 'WAITING_FOR_SELLER_RESPONSE'. Use the same 'an earlier attempt may already have been sent' wording. First check with the paypal MCP or docs that PayPal accepts provide-evidence only on the seller's turn. If it accepts other statuses, list them explicitly. Add the planned [{action, idempotency_key}] to the state, or derive them in paypal_interrupted from the proposal, so execute_interrupted records them. Do not add any audit call inside the execute loop after a PayPal call.
Acceptance: tests modelled on test_graph.py's replay-cache-off send_message test, for provide_evidence (inr_delivered_claim) and accept_claim (inr_no_tracking). Mock replay cache cleared, crash after PayPal answers, retry: assert len(write_calls()) == 1 and the result has sent False. Both tests fail on 72b0728. Update the docstring. A test that execute_interrupted carries the action kind and key after a simulated 503. tests/test_write_boundary.py is unchanged and green.

### R18 API safety tests: token-required startup guard and webhook analyze failure audit — size S — done #98 — audit Oct 18, priority next
Problem 1: the import-time check at backend/rebuttal/app.py:61 has no test. It refuses to serve the real sandbox or a DATABASE_URL without REBUTTAL_API_TOKEN, and it is what keeps approve from being open on Render. `grep -rn 'ALLOW_OPEN_API\|Set REBUTTAL_API_TOKEN' backend/tests` finds nothing. Problem 2: app.py:298 runs rt.analyze in BackgroundTasks after answering 200. If it raises (PayPal outage, transport error), nothing is audited and PayPal will not redeliver.
Fix: extract `check_api_token(settings, token, allow_open)`, call it at import with the same condition, and unit-test four cases. Mock with no DB and no token passes. mock=False with no token raises. database_url with no token raises. allow_open='1' passes. Wrap the webhook task in `_analyze_from_webhook(dispute_id)`, which catches Exception, calls logger.exception and writes rt.audit.log(dispute_id, 'webhook_analyze_failed', {'error': type(exc).__name__}). Show that step in AuditTrail.tsx with a readable line ('Automatic analysis failed; click Analyze').
Acceptance: the four guard tests pass, and deleting the condition makes at least one fail. A test patches rt.analyze to raise httpx.ConnectError, POSTs a CREATED webhook in mock mode, gets 200, and finds an audit row. pytest passes.

### R19 Re-run evals on current code and refresh README/RESULTS numbers — size S — done (R19 PR) — after R15, R16 — audit Oct 18, priority next
Depends on the double-refund and address tasks. Problem: README.md:206-207 and evals/RESULTS.md report 100% final for held-out 1 (2026-10-09) and held-out 2 (2026-10-10). reasoner.py and facts.py changed since (c33adf0, 2026-10-15). On 72b0728 the rules baseline gives holdout2 final 80% and holdout final 90% (ho_snapped_mug miss). Groq results are stale.
Fix: run `uv run python -m evals.run --provider groq --save` for the main, holdout and holdout2 sets. Then refresh the README table and RESULTS.md with dates and the rules baseline lines. Report the numbers as found, and do not tune the guard against held-out misses. Groq usage must stay on the free tier.
Acceptance: new evals/results/*-holdout-*.json and *-holdout2-*.json dated on or after the fix commit. The README table matches them, and each row has a commit hash or date. The rules-baseline paragraph matches a fresh `--rules` run.

### R23 Main-set eval drop 95% to 85%: find the cause — size S — done (R23 PR: model noise by result files and code read, no code change, docs/eval-notes/2026-10-19-main-drop.md) — from R19, priority next
Oct 19 Groq main set (6b0fa6a, after R15/R16/R22): final 85% (17/20), down from 95% on Oct 14. Misses: `snad_damaged_high_value` (got OFFER_PARTIAL_REFUND; was 3/3 after `f4cb66d`), `unauth_delivered` (got OFFER_RETURN_FOR_REFUND), `snad_outside_window` (judgment call). Held-out 2 miss `ho2_unauth_over_cap` (expected ACCEPT_CLAIM, got OFFER_PARTIAL_REFUND).
Fix: compare the two result files' per-case `facts` and guard notes (`evals/results/groq-qwen3.8-27b-20261014.json` vs `-20261019.json`) offline, no model call. If a guard or facts change since Oct 14 regressed a main-set case, fix it with a unit test (the main set is the tuning set). Never tune against held-out misses. Report a model-noise verdict if facts and guard are unchanged for those cases. No Groq run in this task (R19 used today's).

### R24 Refresh eval numbers in the video and its script — size S — done (R24 PR) — after R23 (done: drop is model noise, so say "85-95% across Groq runs"), priority next
`frontend/video/cards.ts` (about lines 178-181 and the held-out card), `docs/video-script.md` (about lines 111-112, 218, 259-261) still show Oct 14 main 95% (19/20), held-out 8/10 and 10/10, rules 85%/25%. After R23, set them to the latest numbers in `backend/evals/RESULTS.md` (or say "85-95% across Groq runs"), keep under 3:00, run the video spec checks. U3 (video upload) should wait for this.

### R20 Judge-path UI and copy fixes — size S — done #94 — audit Oct 18, priority next
Confirmed items: (a) frontend/src/api.ts:60 prints 'Cannot reach the backend at . Is it running?' on same-origin builds (API_BASE is ''). Use `API_BASE || window.location.origin`. (b) CaseView.tsx:217 shows 'Reasoner: Loading…' forever when the loaded audit has no decide step. Show 'Not in the audit trail' once the audit has loaded. (c) SimulatorPanel.tsx:48 says 'Nothing leaves this machine.' but it also renders in the hosted demo. Change it to 'Nothing is sent to PayPal.' (d) After EXECUTED, the heading still reads 'MESSAGE THE BUYER WILL RECEIVE' and the sent text is hidden. Use a past-tense heading and keep the text. (e) Hero case PP-D-2000 is not preselected in #demo, and the README says to open a case by a title the inbox does not show. Preselect it or name the row in the README. (f) Hero approve dialog: the action reads 'Offer full refund of $48.00 after return', but the message promises 'we'll ship the right one'. This is deliberate, because PayPal takes no replacement offer here (reasoner.py:425-430, test_core.py:188). Add a one-line explanation under the action when the guard notes contain the replacement-in-note conversion.
Acceptance: Playwright or unit coverage for (a) and (b). npm run lint, npm run build and the existing e2e pass. A manual #demo check shows (d), (e) and (f).

### R21 Docs drift sweep — size S — done #101 — audit Oct 18, priority later
Fix each, verified against code on 72b0728: docs/deploy.md:99-101 says 'there is no per-client limit', but demo.py:142-144 enforces 10 per minute per client (REBUTTAL_DEMO_CLIENT_LIMIT); describe 10 per client and 20 for the whole service. docs/demo-mode.md:52 says '5 per minute per client'; change it to 10 and name the env var. docs/video-script.md:105,190,216,250 say '24 passed'; the command now prints 53, so re-check on the release commit and drop the VERIFY. PLAN.md:15 says '8 tests'; give the current count or none. STATUS.md:30 Q4 says it was not run against the sandbox, but sandbox-findings.md:210 records a live run (keep the client VERIFY). docs/sandbox-findings.md:203 says the mock offers escalate only on the seller turn, but mock.py:95 offers it on both turns. frontend/README.md:69 says `npm run e2e`, but no such script exists; use `npx playwright test`. Add a README quick-start line on busy ports (set --port, REBUTTAL_CORS_ORIGINS and VITE_API_BASE together). policies.py:3: reword the Elastic 'Week 4' claim as optional. reasoner.py: the prompt asks for a 'Juniper & Oak' signature that rules drafts never add, and draft_message:246 hardcodes '30-day'; use policies.RETURN_WINDOW_DAYS and align the signature.
Acceptance: grep finds no '24 passed', 'no per-client limit', '5 per minute per client' or 'npm run e2e'. pytest passes.

### R22 Small robustness: guard re-read refresh, missing seller_activity baseline, stale proposals on dispute updates — size S — done #99 — audit Oct 18, priority later
(a) graph.py:96-99: the guard re-read refreshes only allowed_response_options and status. Also recompute case.stage, dispute_actions(current) and seller_activity(current) into case.facts, so the ESCALATE and APPEAL guards use current values. (b) approval.py:107: already_applied defaults a missing seller_activity to {}, so any earlier identical seller message or offer is 'reconciled' and the send is silently skipped. Return False when 'seller_activity' not in case. (c) Cross-component: the webhook analyzes only on CUSTOMER.DISPUTE.CREATED (app.py:294). A buyer reply (UPDATED) never re-runs analysis, so the ESCALATE rule (reasoner.py:159-166, which needs a buyer reply) is reachable live only by a manual forced Analyze. Document this in STATUS or decide to re-analyze on UPDATED when no proposal is pending.
Acceptance: a test for (b) that a case dict without seller_activity sends the message once. A test for (a) that a dispute moved to CHARGEBACK between gather and guard blocks ESCALATE. Write-boundary tests stay unchanged.

### R1 Stop mock mode from writing to the live Supabase database — size S — done #55 (DB cleanup of stray PP-D-2000 rows left undone: shared live database, not needed for live behaviour) — audit Oct 14, priority now
Evidence: backend/rebuttal/config.py:66-67 sets checkpoint_target from any postgres DATABASE_URL, and line 86 sets database_url, both regardless of `mock`. _load_dotenv reads backend/.env, which holds the live DATABASE_URL, and REBUTTAL_MOCK defaults to 1. So a plain `uv run uvicorn rebuttal.app:app` or any ad-hoc script stores mock proposals and audit rows (ids PP-D-2xxx) in the database the live Render service uses. The reviewer's probe left rows for PP-D-2000, including one APPROVED proposal. app.py:61 only requires a token in that case; it does not stop the writes. Fix: when settings.mock is true, set database_url=None and checkpoint_target=None unless REBUTTAL_CHECKPOINT_URL is set explicitly. tests/live_postgres.py must keep working, so give it an explicit opt-in if it needs one. Acceptance: (1) a new test shows that with REBUTTAL_MOCK=1 and DATABASE_URL=postgresql://x, load_settings().database_url and .checkpoint_target are both None; (2) the same with REBUTTAL_MOCK=0 and real-looking keys still gives the postgres target; (3) update the persistence.py docstring and docs/deploy.md; (4) delete rows with dispute_id or thread_id 'PP-D-2000' from rebuttal_audit and the checkpoint tables, using a read-first query and logging the counts. If the autopilot may not write to the shared database, leave this step to Manish.

### Q1 Deterministic quality gates in CI — size M — done #18
Catch basic mistakes without spending model usage. Add to `.github/workflows/tests.yml` (all free):
- Secret scan of every push and PR with gitleaks (free for personal accounts; `gitleaks/gitleaks-action@v2` or the
  gitleaks binary), with an allowlist only for the vendored skill examples if needed.
- Backend lint with `ruff check` (add `ruff` to the `dev` dependency group with `uv add --dev ruff`, a minimal
  `[tool.ruff]` config in `backend/pyproject.toml`; fix what it flags in the same PR, do not disable rules wholesale).
- Frontend: confirm `npm run build` (already `tsc -b && vite build`) and `npm run lint` stay in CI; add `tsc --noEmit`
  for the e2e folder if it is not covered.
- GitHub security and supply-chain scanners, all free for public repos: CodeQL (Python + JavaScript), OSV-Scanner,
  OpenSSF Scorecard (badge in README), Dependabot alerts config; coverage report for the backend (pytest-cov) with
  the number in README.
- A test that every environment variable read by the backend (`os.getenv` / `os.environ`) is listed in
  `backend/.env.example` or explicitly allowlisted.
Done when CI runs the new jobs on the PR and they pass.

### Q2 Architecture decision records — size S — done #25
`docs/adr/`: short ADRs (context, decision, consequences) for the safety design: single PayPal write path in
`execute`, read-only client for analysis, human approval via LangGraph interrupt, facts in code + guard over the model,
deterministic PayPal-Request-Id, Supabase over paid Postgres, held-out evals. Link them from README. (Competitor Stood
shows 24 ADRs; judges score Technological Implementation first in ties.)

### Q3 PayPal Agent Toolkit in the agent (read-only) — size M — done #28
Result: the official package cannot be used strictly read-only (langchain pin conflict, `run()` dispatches any tool, `requests` bypasses our transport, no `fields=all`), so `agent/toolkit.py` is a four-tool read-only adapter in the toolkit's tool shape and `gather` reads through it; see ADR 0008.
PayPal promotes its AI Toolkit / MCP server for this hackathon. Use the PayPal Agent Toolkit (Python package, check
the paypal plugin and https://developer.paypal.com for the current package and dispute/transaction tools) for the
agent's read-only lookups in `gather_facts` (show dispute, list transactions), behind the existing read-only boundary:
the toolkit must only be given read tools, and `execute` stays the only writer. Tests prove no write tool is
reachable from analysis. Document it in README and `docs/prize-fit.md`. Log any APIMatic plugin help in
`docs/apimatic-log.md`.

### Q4 Real-sandbox dispute creation for the judge path — size M — done #42 (body VERIFY until first live run) (U1 done Oct 9: buyer business account sb-mku4z53114841@business.example.com, keys in backend/.env, token verified with disputes + checkout scopes)
Create test disputes through the Disputes API with a second sandbox business account acting as buyer (it owns its own
REST app; personal accounts cannot). Script `backend/scripts/make_sandbox_dispute.py` (order -> capture -> create
dispute -> webhook arrives), credentials from `backend/.env` (`PAYPAL_BUYER_CLIENT_ID` / `_SECRET`, added to
`.env.example`). Replaces the password-based buyer steps (supersedes B5).

### S1 APIMatic plugin in every PayPal change — size S — done (first pass, no drift found); standing rule stays
Sponsor research (Oct 9): the APIMatic Context Plugin for the PayPal Server SDK is free and installed, but
`docs/apimatic-log.md` is empty, so we have no evidence of use. From now on every task that touches PayPal calls,
the mock or the client asks the plugin first and logs each use there (date, question, answer, what changed, PR).
First pass now: use it to check our Disputes calls and mock shapes against the SDK models, fix any drift, log it.

### S2 More of the Disputes API — size M — done #69 — after Q4
Strengthens Best Use of PayPal + AI. Add the appeal and escalate paths and more evidence types (proof of
fulfillment, refund, return tracking), each proposed by the agent and executed only by `execute` after approval,
with deterministic `PayPal-Request-Id`, mock parity and tests. Look up shapes with the paypal plugin and APIMatic
(log in `docs/apimatic-log.md`). Sandbox-only flows (`require-evidence`) only in the named manual scripts.

### A1 Keep the live backend awake (free) — size S — done #6
GitHub Actions workflow `keep-render-awake.yml`: `curl` `https://rebuttal-oq3g.onrender.com/api/health` every
10 minutes (public repo, so Actions minutes are free; one free Render service running 24/7 fits the 750 free hours a
month). This replaces the planned paid Render plan. Done when the workflow is merged and its first run is green.

### A2 Held-out eval — size S — done (this PR): model alone 80%, final 100%, results in `backend/evals/RESULTS.md`
`cd backend && uv run python -m evals.run --set holdout --provider groq --langfuse --save`. Report model-alone vs final
accuracy and the per-case misses in `docs/evals.md` (create it, include the main-set numbers from `STATUS.md`) and in
`STATUS.md`. **Change no agent code because of the result.** If Groq returns 429 (daily quota), mark
`waiting: Groq quota until <time>` and move on; retry next day.

### A3 Frontend follow-ups from the PR #3 review — size M — done #9
- Delete the unused Vite scaffold (`frontend/src/assets/`, `frontend/public/icons.svg`, unused CSS).
- Register only the AG Grid modules in use instead of `AllCommunityModule` (`ag-mcp` for module names); report the
  bundle size before and after.
- After a non-409 error, close the confirm dialog or disable "Approve and send" when the refreshed proposal is no
  longer PENDING.
- Retry dialog shows the approved text: expose the approved message in the proposal API (backend change, additive,
  with a test), and add an end-to-end test for the retry path.
- Make `npm run build` fail if `VITE_API_TOKEN` is set for a production build.

### A4 Video script — size S — done (on main, docs/video-script.md) — deadline Oct 12
`docs/video-script.md`: under 3 minutes, built from `docs/pitches.md`. One hero case (`agent_wrong_size`), two
cutaways, the eval number on screen. Columns: time, what is on screen (exact UI state or terminal), narration text,
which judging criterion it serves (Tech, Design, Impact, Innovation, Presentation). Include a shot list the
automated recorder (B4) can follow step by step.

### A5 Dashboard on the live service with a login — size M — merged #39; done #39; live `/` returns 200 and health ok (checked Oct 10)
Serve the built frontend from the FastAPI app on the existing Render service (same origin: no CORS, no new Render
resource, no cost). Replace `VITE_API_TOKEN` with a sign-in screen where the merchant pastes the API token; keep it in
`sessionStorage`, never in the bundle. Update `render.yaml` build to also build the frontend (check Node is available
in Render's Python runtime; if not, find a free alternative and document it). Done when
`https://rebuttal-oq3g.onrender.com/` shows the sign-in screen after deploy and a Playwright test covers sign-in.
The sign-in screen must also show a "Try the demo" link (`href="#demo"`): `DemoApp` needs no token, so judges reach it
without one. `VITE_API_TOKEN` must never be set in a public frontend build.

### A6 Judge demo mode — size M — done #33 — priority now (rules: judges must be able to try it; testing credentials go in the submission)
Judges must be able to try Rebuttal without PayPal accounts. Add a demo mode on the same service: a "Try the demo"
button that runs the hero case and the other demo cases against the in-memory mock sandbox in a separate, isolated
runtime (no access to the real sandbox client, never writes to PayPal, resets itself). The real-sandbox inbox stays
behind the token. Reviewer must confirm the isolation. Document it in the README.

### A7 Approve dialog closes at once under `npm run dev` — size S — done
Found by the A4 dry run: in the Vite dev server the Approve confirm dialog closes immediately (likely a React
StrictMode double-effect in `frontend/src/components/ConfirmDialog.tsx`); the production build is fine. Reproduce with
a Playwright test against the dev server, fix the effect, keep StrictMode on.

### A8 Re-run the main eval on current code — size S — done Oct 14 (final 95%, model alone 75%, run groq-qwen3.8-27b-20261014-001228) — after Oct 11 (Oct 10 Groq run used by B3)
The 90% main-set number predates guard rule `f4cb66d`. Run `uv run python -m evals.run --provider groq --langfuse --save`
once (respects one Groq eval per day), update `backend/evals/RESULTS.md`, `STATUS.md` and the eval card in
`docs/video-script.md`. Change no agent code because of the result. A8 must run on a different day than the holdout2 Groq run (B3), so the
two do not share one day's Groq quota.

### B1 AG Studio dashboard, first pass — size L — done #52 (part 1 #16, part 2 #48, part 3 Agent Framework #52) — deadline Oct 23
Main sponsor prize. Use the `ag-dev` skill and `ag-mcp` for AG Studio APIs in the installed version. Analytics view:
disputes by reason and by product, money kept vs refunded, response deadlines, model-vs-final agreement from the
audit log. Custom widgets and a theme matching `preview/`. New read-only backend endpoints for the aggregates (with
tests). Split into PRs: data endpoints, Studio layout and theme, custom widgets.

### B2 AG Studio depth — size L — done #70 (saved views, starters e2e, licence note, 10 widget screenshots, live Groq smoke pass 505 ms) — needs B1
Studio Agent Framework: plain-English questions over the dispute data ("which products cause most disputes this
month?"), using Groq free tier, read-only data access only (assistant + read-only proxy done #52; left: one live
Groq smoke check of the assistant, prompt starters showing, AI module licence note). Saved views. Playwright screenshots of every widget into
`docs/screenshots/`.

### B3 More evals — size M — done (holdout2 run Oct 10: final 100%, model alone 80%; this PR)
Grow to about 40 cases: 10 more held-out cases written by a subagent that is **not allowed to read**
`agent/facts.py`, `agent/reasoner.py` or `agent/llm.py` (give it only `cases.json` format and the dispute types).
Run once on Groq (respect the one-run-per-day rule). Update `docs/evals.md`.

### B4 Automated demo video — size L — in-progress [90%] (#68 merged) (part 1 #66 one-command rough cut; part 2: Analytics segment, live-proof card, 2:50; left: USER review and upload) — after A4, B1 — rough cut deadline Oct 23
Free tooling only: Playwright records the browser (video) following the A4 shot list in demo mode; narration from
the A4 script via macOS `say` (pick a natural voice, export AIFF); `ffmpeg` (`brew install ffmpeg`) joins them,
adds captions and title cards. Output `media/rebuttal-demo.mp4` (git-ignored; keep the script and the build command
`scripts/make_video.sh` in git). Under 3:00. Then add a USER item: watch it, optionally re-record the narration in his
own voice (give exact steps), and upload to YouTube as Public.

USER: (1) Watch media/rebuttal-demo.mp4 (open it in QuickTime; run scripts/make_video.sh first if the file is missing). Check the Analytics segment (about 1:36) and the live-proof card (about 2:23) read right and nothing is cut off.
(2) Optional, a better voice: VIDEO_VOICE="<name>" scripts/make_video.sh (list the voices with `say -v ?`). Own voice is not wired: make_video.sh always writes the narration with `say`, and the shot hold times follow the narration length, so a dropped-in audio file would not line up. If you want your own voice, record each caption from docs/video-script.md section 7 and send the files in chat; the lead wires an own-voice option.
(3) Upload to YouTube as Public: go to studio.youtube.com, click Create (top right) > Upload videos > Select files, choose media/rebuttal-demo.mp4; title "Rebuttal: a PayPal dispute agent that waits for your approval"; description from docs/devpost.md; under "Audience" choose "No, it is not made for kids"; click Next three times; on Visibility choose Public and click Publish; copy the link into the Devpost form.
(4) Say done in chat.

### B5 Sandbox simulator for judges — size M — superseded by Q4
Research (PayPal plugin, docs) whether a test dispute can be created on the real sandbox without a buyer password.
If yes, add it to the simulator in sandbox mode. If it needs a buyer login, make it a USER item with exact steps and
skip the code.

### E1 Second submission decision — size S — done (go: Mandate, separate repo and routine, docs/second-entry.md)
Rules allow several substantially different submissions, each winning up to one Grand/Honorable + one Sponsor
prize. Only if Rebuttal's queue is on track: scope a second, different entry aimed at Bryntum ($1,000 x3) or Channel3
($1,500) plus one honorable mention, reusing nothing user-visible from Rebuttal. Write `docs/second-entry.md` with
the idea, effort and a go/no-go; go only if it fits before Nov 3 without slowing Rebuttal.
Sponsor research (Oct 9): Bryntum ships free `-trial` npm packages (no card) but the trial is 45-60 days and
"evaluation only, not production"; judging runs to Dec 15, so verify the trial terms (or ask Bryntum on Discord via a
USER item) before choosing it. Channel3 has a free MCP tier (product catalog search), weak fit for disputes.

### C1 Design polish — size M — done #73 — after B1
`frontend-design` skill pass over inbox, case view and Studio: typography, spacing, empty and loading states,
keyboard access, accessible contrast; Playwright screenshots before/after in the PR.

### C2 README and submission docs — size M — done (this PR)
README: what it is, 60-second judge quickstart (demo mode link + local run), architecture diagram (Mermaid), safety
design (single write path, guard, approval), eval table, how each sponsor tool is used (AG Grid/Studio, APIMatic with
`docs/apimatic-log.md`, PayPal APIs), license. Draft `docs/devpost.md` (every Devpost field) and
`docs/discord-preview.md` (short post asking for judge-style feedback). Prepare the APIMatic form answers.

### C3 Discord preview — size S — done (this PR) — after C2 and A5 — target Oct 23
Make the USER item: post `docs/discord-preview.md` in the AG Grid and general channels (exact steps). Do not post.

### R14 Confirm Render redeployed #92 — size S — done (this PR; live redeploy itself is USER item U4) — priority now
After #92 merged (Oct 18 01:24 CDT) the live site still served `assets/index-PGbThk6e.js` 25 minutes later, which has "Sent to PayPal" but not "demo sandbox"; `/api/health` stayed ok. Check that the live bundle now contains "demo sandbox". If not, find out why Render did not redeploy (auto-deploy setting or a failed build; read only, do not change Render settings) and add a USER item with the exact steps for Manish.
Result Oct 18 06:20 CDT: still `index-PGbThk6e.js`, no "demo sandbox". Cause: `rootDir: backend`; Render only auto-deploys on changes under the root directory, and #92 touched only `frontend/`. Fix in this PR: no rootDir, `cd backend` in both commands, `buildFilter` on `backend/**`, `frontend/**`, `render.yaml`, pinned by a test. The live service is named `rebuttal`, not the Blueprint's `rebuttal-api`, so it is likely not Blueprint-managed and its dashboard settings must be changed by hand: USER item U4. Render MCP was not used (it asks a person to pick the workspace).

### D1 Feature freeze — Nov 3
From Nov 3 only fixes, docs, video. Move any unfinished feature task to `## Cut` with one line why.

### R13 Early final-check dry run — size M — done #92 — priority now (banked reset week, Oct 18-20)
Run the D2 checklist now, minus the video and Devpost items, so problems surface before the Nov 3 freeze: gitleaks
over the whole history, every README link, CI green, live health ok, judge demo mode from a fresh browser (Playwright,
no console errors), the documented judge commands leave the tree clean. Fix what fails in small PRs; record results
in STATUS.md. D2 still runs after Nov 7.

### D2 Final check — size M — after Nov 7
Secret scan of the whole git history (`gitleaks` via Homebrew or `trufflehog`), license file, all links in README
work, CI green, live health ok, demo mode works from a fresh browser, video under 3:00, Devpost draft complete. Then
send one alert with the final USER checklist (upload video, submit Devpost, APIMatic form) for Nov 10.

### D3 Learning pack — size M — after D2
Manish wants to learn at the end. Update the local `LEARNING.md` (never commit it): one section per merged PR since
PR #3 (what, why, how, Mermaid where useful, ELI5), a glossary, and the 10 interview questions a PayPal engineer
would ask with model answers.

### D5 Submitted on Devpost — size M — waiting: Manish submits Nov 10
Done when Manish confirms the Devpost submission (video uploaded, repo link, testing credentials, APIMatic form). The
lead marks it done only on his word in chat or a LOG.md note from him; this is the last step to 100%.

### D4 Post-hackathon reminder — Dec 22
Alert: delete the Render service (judging ends Dec 15). Do not delete it yourself.

### R2 Guard: rules fallback must pass the PayPal-allowed and policy checks; handle a missing merchant order — size M — done #65 — audit Oct 14, priority next
Evidence: (1) In reasoner.py:276-288, fallback() returns RuleReasoner().decide(case) directly, so the paypal_allows() / PAYPAL_ALTERNATIVES step (reasoner.py:327), the cannot_prove_delivery conversion and the damage threshold never run on the replacement. Example: on a NOT_RECEIVED dispute where only REFUND is allowed, an unknown resolution falls back to OFFER_REPLACEMENT, which PayPal will refuse at execute. (2) _compute_facts returns early when order is None (facts.py:184-186), leaving has_tracking and refund_issued unset. RuleReasoner._pick (reasoner.py:120, 159, 152) then proposes ACCEPT_CLAIM: 0.85 'No tracking on file' for NOT_RECEIVED, 0.75 'No refund on file' for CREDIT_NOT_PROCESSED, 0.6 for UNAUTHORISED. This hits every live dispute whose invoice is not RB-<case>-<n>. (3) Nit in the same file: _pick re-derives damage from the last message and from case.amount instead of using facts.buyer_reports_damage and refund_without_return_eligible. Fix: in fallback(), set the notes on base, then `return guard(base, case)`. This cannot loop, because rules only pick SHARE_TRACKING when there is tracking and SUBMIT_REFUND_PROOF when a refund exists. In _pick, when facts.order_found is false, return SUBMIT_EVIDENCE at confidence <= 0.3 with 'No merchant order record; needs merchant review'. Also add a guard rule that caps confidence and adds a note for ACCEPT_CLAIM or OFFER_REPLACEMENT when order_found is false. In _pick, use buyer_reports_damage and refund_without_return_eligible. Acceptance: new tests fail on the old code. They cover a guard fallback with allowed_response_options=['accept_claim'] on NOT_RECEIVED, giving a PayPal-allowed resolution; order_found False for NOT_RECEIVED, CREDIT_NOT_PROCESSED and UNAUTHORISED, giving no ACCEPT_CLAIM above 0.3; and damage reported in the claim notes plus a follow-up message. Do not retune against holdout.json or holdout2.json. Re-run evals and report any change. Also (Opus review of #63, Oct 14): at stage CHARGEBACK with allowed_response_options missing, effective_options returns None so paypal_allows says yes to everything; return False for make_offer resolutions at CHARGEBACK and add a test.

### R3 Duplicate-charge fact: match the invoice and successful status only — size S — done #58 — audit Oct 14, priority next
Evidence: facts.py:226-233 counts every transaction with the same buyer email and amount, ignoring transaction_info.invoice_id and transaction_status. A second legitimate same-price order, or a denied attempt, sets duplicate_charge_found True, and the rules then propose ACCEPT_CLAIM at 0.9. holdout.json ho_duplicate_two_orders seeds only one transaction, so it never tests this. Fix: count only transactions with transaction_status == 'S' and, when present, invoice_id == order.invoice_id. Check that the mock (paypal/mock.py) and scenarios.py transaction shapes include both keys, and mirror the real Transaction Search shape. Acceptance: unit tests cover a different invoice (duplicate False), a denied 'D' transaction (False) and two 'S' transactions on the same invoice (True). Evals stay at or above the current main-set accuracy. Do not edit held-out labels to fit.

### R4 Verify the PROOF_OF_REFUND evidence_info.refund_ids shape against PayPal — size S — done #61 — audit Oct 14, priority next
Evidence: pipeline.py:130-131 sends evidence_info.refund_ids as a list of strings. As far as I recall, PayPal's provide-evidence schema defines refund_ids as an array of objects ({"refund_id": "..."}), like tracking_info. No VERIFY note exists, and the mock does not validate evidence shape, so tests cannot catch this. A wrong shape fails at execute, after the human has approved. Fix: check the schema with the paypal-sandbox MCP (read-only lookup) or the APIMatic PayPal SDK skill, and log the APIMatic use in docs/apimatic-log.md. If objects are required, send [{'refund_id': id}], make mock.py reject the string form with a 400 INVALID_REQUEST like the real API, and add a plan_actions test plus a mock rejection test. Otherwise add a VERIFY note at pipeline.py:131 and in mock.py. Acceptance: the shape is cited from the docs or the SDK model, and a test pins it.

### R5 API hardening: webhook and analyze never return a bare 500 — size S — done (this PR) — audit Oct 14, priority next
Evidence (reproduced at 40518cf with the database blanked, TestClient): POST /api/webhooks/paypal with body b'notjson' returns 500; with {event_type: CUSTOMER.DISPUTE.CREATED, resource: null} returns 500; POST /api/disputes/NOPE/analyze returns 500 (PayPalError 404 not caught). app.py:259 calls `await request.json()` unguarded, and :272 calls `event.get('resource', {}).get`. analyze (:136) and list_disputes (:130) do not catch PayPalError or httpx.TransportError, unlike _analytics_rows (:212). Fix: wrap the JSON parse and return 400; reject a non-dict body with 400; use `resource = event.get('resource') or {}`. In analyze and list_disputes, map PayPalError to 404 when the status is 404 and to 502 otherwise, map TransportError to 502, and log status and debug_id. Also change the sandbox simulator 501 text 'lands in week 2' (app.py:301) to 'The simulator only runs against the mock sandbox.' Acceptance: new tests cover non-JSON, a JSON list and a null resource (4xx or 200, never 500); analyze on an unknown id (404) and a PayPal 5xx or transport error (502); webhook verification raising ConnectError (503, no analysis); a verified CUSTOMER.DISPUTE.UPDATED (200, no proposal); health with ping raising (ok False, database False); and the sandbox-mode POST simulator returning 501.

### R6 Case view deadline: compute live from the server clock, show Overdue — size S — done #59 — audit Oct 14, priority next
Evidence: CaseView.tsx:167 shows summary.hours_left, which is frozen at analysis time (facts.py:169, pipeline.py case_summary). On the live service a proposal left overnight still shows the old hours, and labels.ts clamps negative values to 0, giving '0h left to respond'. Cross-component caution: the reviewer's fix (Date.parse(summary.due) - Date.now()) would break the judge demo, because mock and demo mode use a frozen clock (runtime.py:44 `self.clock = lambda: DEMO_NOW`, scenarios.py:18 DEMO_NOW = 2026-10-06), so every demo case would read Overdue. Fix: compute hours_left at read time on the server with rt.clock(), for example in the /api/disputes and proposal to_dict paths, or return a server 'now' and have the frontend use it. Render 'Overdue' for negative values. Acceptance: a backend test checks that hours_left follows the clock after analysis; e2e tests show the demo hero case with a positive hours pill and a mocked past due date showing 'Overdue'.

### R7 Frontend robustness nits: reasoner row, failed inbox load, audit step labels, widget field mapping — size M — done #64 — audit Oct 14, priority later
Evidence: (a) CaseView.tsx:112 falls back to decision.resolution while the audit has not loaded, so the 'Reasoner' row shows the guarded choice. Show a placeholder instead. (b) Desk.tsx:89: if the first GET /api/disputes fails, the inbox shows 'Loading disputes…' forever. Add a failed state with a Retry button. (c) AuditTrail.tsx:9 has no case for execute_failed or execute_interrupted, so it prints raw JSON. Add readable text, and assert it in the interrupted-call e2e test. (d) DeadlineListWidget.tsx:53 and AgreementWidget index into fieldsets without length checks, so a remap in Studio edit mode throws and unmounts the app. Use setDisplayState('incompleteDataMapping') and add an error boundary. (e) frontend/.gitignore:28 mentions .env.example, but none exists. Add frontend/.env.example with commented VITE_API_BASE and VITE_API_TOKEN. Acceptance: npm run lint, npm run build and npx playwright test all pass, with a new assertion for (b) and (c).

### R8 Fix stale agent brief and status docs (CLAUDE.md, STATUS.md, deploy.md, PLAN.md) — size S — done #60 — audit Oct 14, priority next
Evidence: CLAUDE.md:104 lists 'Frontend (frontend/, none yet)' and the AG Grid dashboard as next tasks, but both have shipped. The Layout block omits frontend/, analytics.py, studio_ai.py and agent/toolkit.py. STATUS.md:93 says 398 backend tests (actual 469 passed) and 29 Playwright tests (about 43 test() calls). STATUS:8 says 44% (progress.py prints 58%). STATUS:15 says Q4 'PR open' (it merged as #42). STATUS:114 and PLAN.md plan a paid Render plan, while docs/autopilot/QUEUE.md says A1's keep-render-awake.yml replaced it. deploy.md:125 says the keep-alive does not keep Render awake, but .github/workflows/keep-render-awake.yml exists. deploy.md:115 still calls Node on Render unverified, yet the live root serves the Vite build. Fix: point 'Next, in order' at QUEUE.md and update the Layout; correct the counts, percentages and merge state; make deploy.md, PLAN.md and STATUS agree on Render (best-effort 10-minute ping, no paid plan unless Manish decides otherwise); mark the Node build as verified. Acceptance: running `uv run pytest -q` and `npx playwright test --list` gives the counts quoted in the docs, and the docs contain no contradictory Render plan. CLAUDE.md is the project brief, so keep the change limited to facts.

### R9 README judge path: make the documented commands leave the git tree clean — size S — done #62 — audit Oct 14, priority next
Evidence: the README's 'Backend only' commands rewrite tracked files. `uv run python -m evals.run --rules` rewrites backend/evals/RESULTS.md (run.py:269-271) and adds evals/results/*.json. `uv run python -m scripts.demo` rewrites backend/preview_data.json. The run.py:279 --only help says results are overwritten, but a partial run writes nothing. The README says 93% coverage while `pytest --cov --cov-branch` gives 94%. README.md:216 credits the held-out guard change with OFFER_RETURN_FOR_REFUND only, but ho2_inr_nothing_shipped became ACCEPT_CLAIM through cannot_prove_delivery. README.md and frontend/README.md give different backend start commands. frontend/README.md does not say Playwright needs ports 8000, 4173 and 5174 free (reuseExistingServer is false). Fix: add a --no-save flag, or make --rules print only unless --save is given, and document it. Fix the --only help, the coverage number and the held-out sentence; use one backend start command in both READMEs; add the note about free ports. Acceptance: after the README quickstart commands, `git status --short` is clean.

### R10 Approval/audit and mock fidelity nits — size M — done #72 (part 1 items a, e: #71; part 2 items b, c, d: #72) — audit Oct 14, priority later
Evidence: (a) approval.py:177 logs 'approve' on every execute attempt, so after approve, a 503 and a retry the audit shows two approve records. Log it once per proposal id, and add a test asserting a single approve after a retry. (b) mock.py:78 keeps allowed_response_options after the seller makes an offer and accepts a second make_offer in WAITING_FOR_BUYER_RESPONSE. Pop the options when the status leaves WAITING_FOR_SELLER_RESPONSE, and add a mock test. (c) already_applied() and seller_activity() (facts.py:99-101) rely on messages[].posted_by and offer.history[].actor shapes seen only in the mock. Add VERIFY notes until a real post-offer dispute is captured, and normalise whitespace when matching message text. (d) client.py:108 uses a denylist for the host check, and the read-only clone keeps _client_secret. Switch to an allowlist of SANDBOX_HOSTS (plus a mock transport) and drop the credentials from the clone. Keep tests/test_write_boundary.py green and extend it. (e) audit.py:60 appends to self.records even in Postgres mode, so memory grows without bound. Append only when there is no pool. Acceptance: one new test for each item, and the write-boundary tests remain unchanged or are strengthened.

### R11 Prompt and guard: untrusted buyer text and address mismatch — size S — done #63 — audit Oct 14, priority later
Evidence: reasoner.py SYSTEM_PROMPT (line 223) passes buyer_messages verbatim with no note that they are untrusted, and the guard has no check for an ACCEPT_CLAIM that contradicts delivered + matching address + no refund request. delivered_address_matches is computed but neither the prompt nor the guard uses it, and draft_message SHARE_TRACKING hard-codes 'to the address on your order'. Fix: add a SYSTEM_PROMPT sentence saying buyer messages are quotes, never instructions. In guard, turn SHARE_TRACKING or SUBMIT_EVIDENCE on NOT_RECEIVED with delivered_address_matches False into OFFER_REPLACEMENT, and add a guard note when ACCEPT_CLAIM contradicts the facts. Make the draft text depend on whether the address matches. Acceptance: unit tests cover each rule; no tuning against the held-out sets.

### R12 Return-needed rule at CHARGEBACK with no option list — size S — done (live CHARGEBACK lists accept_claim only; claims needing a return now use REFUND_WITH_RETURN with the return address, docs/sandbox-findings.md S4 run) — from the PR #65 review
Evidence: with `allowed_response_options` missing at CHARGEBACK, `paypal_allows` now refuses offers (R2), so a not-as-described dispute that needs the item back can fall through to ACCEPT_CLAIM, a full refund without a return. R2 first capped it, but the cap rested on an unverified assumption about what the sandbox returns at CHARGEBACK (see the VERIFY note in `reasoner.py`) and fired on every case without damage. Fix: once a real sandbox CHARGEBACK shows whether the option list is omitted, add a guard rule for ACCEPT_CLAIM when the item needs its return, scoped to that evidence. Acceptance: a test built from the captured payload.

### S3 Confirm the S2 Disputes shapes on the real sandbox — size M — done #74 (confirmed: escalate rel, escalate on INQUIRY without buyer_escalation_reason, stage stays INQUIRY, seller message moves to UNDER_REVIEW, posted_by/actor shapes; rest moved to S4; results in docs/sandbox-findings.md)
S2 shipped escalate, appeal and the richer evidence types against the mock only. Using the existing named manual
scripts (`spike_sandbox.py`, `make_sandbox_dispute.py`; `require-evidence` stays confined to them), confirm: the link
rel names `escalate` and `appeal` on a shown dispute; that escalate is accepted on an INQUIRY waiting for the seller;
the appeal multipart body and the stage it moves to; that a seller can send PROOF_OF_RETURN; escalate after a seller
reply (the status send-message leaves, and whether a buyer reply returns the INQUIRY to WAITING_FOR_SELLER_RESPONSE,
which the ESCALATE rule and the mock's `require-evidence` stand-in assume); whether escalate needs
`buyer_escalation_reason`, which the client omits. Fix the mock and the
client together and remove the matching `VERIFY` notes (`client.py`, `mock.py`, `facts.py`, `approval.py`).

### S4 Remaining sandbox confirmations from S3 — size S — [60%] waiting: CHARGEBACK options and accept-with-return confirmed Oct 15; still needs an appealable (lost) case (sandbox adjudicate refused) and a buyer reply on a dispute the buyer app owns
Left STILL UNVERIFIED by S3 (#74, see `docs/sandbox-findings.md`): the `appeal` rel, multipart body and next stage; PROOF_OF_RETURN acceptance (refused on a NOT_RECEIVED inquiry; try a NOT_AS_DESCRIBED one); whether a buyer reply returns the INQUIRY to WAITING_FOR_SELLER_RESPONSE; whether escalate removes its link (retry safety note in `approval.py`); `allowed_response_options` at CHARGEBACK (unblocks R12). Also the review nits from #74: VERIFY note for mock escalate in WAITING_FOR_BUYER_RESPONSE (`mock.py:300-305`) and `body.get("note")` in the mock escalate branch. Use `scripts/spike_shapes.py` only. Fix mock and client together, remove VERIFY notes only with a fixture. Also from R17 (#95, before the Nov 3 freeze): fixtures for (1) evidence sent then read: status is no longer WAITING_FOR_SELLER_RESPONSE; (2) plain accept_claim sent then read: same; (3) provide_evidence on an UNDER_REVIEW dispute: PayPal's answer. Remove the matching VERIFY notes in approval.py only with a fixture.

## USER

Things only Manish can do. Each with exact steps; the lead adds them here and alerts at most once a day.

- **U4 Render: redeploy and fix auto-deploy** (ready Oct 18, from R14; the live demo still serves the pre-#92 bundle). Change the three fields together in one save; a cleared Root Directory with the old commands would fail the build.
  1. Go to dashboard.render.com, sign in, open the service `rebuttal` (URL `rebuttal-oq3g.onrender.com`), click **Settings**, scroll to **Build & Deploy**.
  2. **Root Directory**: click Edit, clear the field (empty), Save.
  3. **Build Command**: Edit, paste `cd backend && pip install uv && uv sync --frozen --no-dev --extra postgres && (cd ../frontend && npm ci && npm run build || echo "frontend build failed, serving the API only")`, Save.
  4. **Start Command**: Edit, paste `cd backend && uv run --no-sync uvicorn rebuttal.app:app --host 0.0.0.0 --port $PORT`, Save.
  5. **Build Filters** > Included Paths: add `backend/**`, `frontend/**`, `render.yaml`, Save.
  6. Top right: **Manual Deploy** > **Deploy latest commit**. Wait for "Live" (about 5 minutes).
  7. Check: open `https://rebuttal-oq3g.onrender.com/#demo`, approve a proposal; the dialog says "demo sandbox". Tell the lead "U4 done".
  If anything fails, set Root Directory back to `backend` and the two commands back to the versions without `cd backend &&`, then Manual Deploy again.

- **U3 Demo video review and upload** (ready Oct 14, from B4): follow the four USER steps under B4 above: watch `media/rebuttal-demo.mp4` (run `scripts/make_video.sh` first; re-run it even if the file exists, because R24 on Oct 19 changed the eval cards and the held-out narration), optionally pick a better `say` voice, upload to YouTube as Public, then tell the lead "U3 done" with the link. R26 changed the hero offer note (it now states the $48.00 refund first and offers the replacement only as an alternative), so the approve-dialog shot in `frontend/video/record.spec.ts` shows new text: re-recording with `scripts/make_video.sh` is required, not optional.

- **U2 APIMatic form and Discord preview**: ready on Oct 23 (after C3). Inputs are ready: `docs/apimatic-form.md` (answers for the APIMatic form) and `docs/discord-preview.md` (the posts, sections A and B).
  0. Before step 1, take 2-3 screenshots (or a short clip from `media/rebuttal-demo.mp4`) of the AG Studio Analytics tab in the signed-in dashboard; post A asks about it and the public demo does not show it.
  1. Discord, AG Grid channel: in the hackathon's Discord server (use the invite link from the Devpost page; the repo does not name the server or its channels), open the AG Grid sponsor channel. Paste section A of `docs/discord-preview.md` (the text under "## A. AG Grid channel", without the heading) and attach the screenshots from step 0, then post it.
  2. Discord, general channel: open the general feedback channel, paste section B (the text under "## B. General channel") and attach the screenshots from step 0, then post it.
  3. Tell the lead "U2 Discord posted" once both posts are up.
  4. APIMatic form: open the APIMatic form link from the hackathon's sponsor resources (the repo does not record the form URL). Check its questions against `docs/apimatic-form.md`, which was written for generic questions.
  5. Paste the answers from `docs/apimatic-form.md`: "How did you use the APIMatic Context Plugin?", "What did it not help with?", "Links to evidence", and the "Short answer" if the form has a small text box. Skip "Note for Manish" and "Before you submit".
  6. Replace `<YouTube link, added by Manish>` in "Links to evidence" with the video link, or leave that line out if there is no video yet.
  7. Separately, submit the free-subscription claim form (link in `docs/apimatic-log.md`) yourself if you want the free plan. It is not the prize form.
  8. Submit the APIMatic form yourself, then tell the lead "U2 done".

- ~~**U1 Second sandbox business account**~~ done Oct 9. Original steps kept for reference: developer.paypal.com > log in > Testing Tools >
  Sandbox Accounts > Create account > Business, United States > Create. Then Apps & Credentials (Sandbox) > Create App
  > name "rebuttal-buyer" > Merchant > pick the new business account > Create. Copy the Client ID and Secret into
  `backend/.env` as `PAYPAL_BUYER_CLIENT_ID=` and `PAYPAL_BUYER_CLIENT_SECRET=` (never paste them in chat). Then tell
  the lead "U1 done".

## Cut

- Render paid plan: replaced by A1 (no spending).
- Bryntum: backup only; dropped unless everything else is done before Oct 30.
- Elastic retrieval: optional; dropped unless everything else is done before Oct 30.
- Ticking "Transaction search" in the PayPal app: account setting, not needed.
