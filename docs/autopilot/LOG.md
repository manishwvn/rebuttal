# Autopilot log

# Daily summary 2026-10-19
progress 85% (48/59 tasks done, 22 days to Nov 10 submit)
Daily system audit on f038629 (Sonnet per component, fresh clone, Opus principal): healthy, 1041 tests pass, write boundary intact, no secrets, not critical; 27 raw findings, 6 rejected, 8 tasks queued (R25-R32), so the percent dropped from 91% before rising again.
Main defect: guard() recursed forever on a refund-proof decision when it was not the seller's turn (re-analysis after an approve gave a bare 500; nothing reached PayPal). Fixed today in R25 (#106); R28 (#105) shows INTERRUPTED proposals instead of "Sent to PayPal".
Next: R26 hero offer note must say refund (may need a video re-record), R27 guard money rules, R29 boundary hardening, R30 docs drift, R31 negation-aware keywords, R32 analytics labels.

## 2026-10-19 12:10 | W 77 % | F 3 % | R27 | merged #109
Items 1 (over-limit assistant purchase falls back to rules once) and 2 (uncertain address: evidence at 0.5) shipped; rules evals unchanged (main 17/20, holdout 9/10, holdout2 10/10).
Item 3 split into R27b, waiting: it contradicts the pinned R15 test test_a_refund_on_another_reason_does_not_trigger_the_refusal and needs Manish's sign-off.

## 2026-10-19 11:10 CDT | W 76→77 % | F 70→0 % (window reset) | R29 | merged #108
H=4, so one task; picked R29 (size S) over R27 (size M, strict) to stay under the 80% weekly cap. Sonnet builder + Opus reviewer: write boundary and guard intact, no blockers.
Fixed both should-fixes in the same PR (audit file read skips corrupt/non-object lines, tests for them) plus nits (docstrings, CORS test env restore, PUT/PATCH/DELETE/OPTIONS refused). Backend 1088 passed. R27 next (needs H >= 3 and a fresh week ideally).
## 2026-10-19 10:10 CDT | W 76→? % | F 64→? % | R26 | PR (see runs.log)
H=4, so one size S task. Sonnet builder + Sonnet reviewer: no blockers; should-fix (stale video narration in shots.json and video-script.md) fixed in the same PR.
Hero note now states the $48.00 refund first, replacement only on request; guard logic unchanged (message text only). Rules evals unchanged (85%); backend 1082 passed. U3 approve-dialog shot needs re-recording.
## 2026-10-19 08:10 CDT | W 68→73 % | F 4→44 % | audit, R25, R28 | merged #105, #106
One team-cycle workflow (26 agents, 46 min) over two disjoint tasks; R25 strict (Opus principal: write boundary and guard intact, safe_to_merge), R28 non-strict. No findings left on either.
R25 merged after #105 with a STATUS.md header conflict only (both entries kept). Rules evals unchanged (main 85%, holdout 90%, holdout2 100%); backend 1081 passed.
## 2026-10-19 02:10 CDT | W 64→? % | F 7→? % | R19 | PR (see runs.log)
Only runnable task. One Sonnet builder ran Groq once per set (main, holdout, holdout2; about 63k tokens, free tier) as one eval round; decision: R19's three sets count as today's one eval run. Main 85% (was 95%), held-out 1 100%, held-out 2 90%; reported as found, nothing tuned.
Queued R23 (find the main-set drop, offline) and R24 (video cards and script still say 95% and 10/10).
R23 (same cycle, one Sonnet builder, offline): model noise; raw choices changed, guard and facts same for those inputs. No code change; note moved out of generated RESULTS.md into docs/eval-notes/.
R24 (same cycle, Sonnet builder): video cards, shots.json held-out narration (+6 words) and video-script.md now say main 85-95% across Groq runs, held-out 7/10 model alone, 10/10 and 9/10 final. Video not re-recorded; U3 says to re-run make_video.sh.

# Daily summary 2026-10-18
progress 84% (39/49 tasks done, 23 days to Nov 10 submit)
Daily system audit on 72b0728 (Sonnet per component, fresh clone, Opus principal): healthy, 961 tests pass, write boundary intact, not critical; 28 raw findings, 4 rejected, 8 tasks queued (R15-R22).
Main weakness was money logic: a second refund could be proposed, an address written differently became a free replacement, and a retry after a lost checkpoint could resend evidence or accept-claim.
Fixed today in one team cycle: R15 second refund refused (#96), R17 retry fails closed (#95), R20 judge-path UI copy (#94). Backend 997 passed; rules evals main 85% (0 gate violations), holdout2 90%.
Next: R16 address near-match, R18 API safety tests, R19 eval re-run, R21 docs sweep, R22 robustness; S4 now also holds R17's three sandbox fixtures (before Nov 3).

## 2026-10-18 21:11 CDT | W 50→57 % | F 3→52 % | R18, R22, R16, R21 | merged #98, #99, #100, #101
R16 via team-cycle (30 agents, 33 min, strict, Opus principal: boundary intact, safe_to_merge); R18, R22, R21 via one Sonnet builder plus an independent reviewer each. R22's Opus review caught a duplicate-send risk on legacy checkpoints (no seller_activity); fixed to fail closed before any PayPal call, re-reviewed clean.
R16 branch was handed back on a detached HEAD; lead re-attached it, merged main, re-ran pytest (1040) before merge. A force-push was refused by permissions; used plain pushes only. Live health ok after each merge.

## 2026-10-18 16:11 CDT | W 37→49 % | F 2→96 % | audit, R15, R17, R20 | merged #94, #95, #96
One team-cycle workflow (70 agents, 57 min) over three disjoint tasks; R15 and R17 strict (Opus principal: write boundary and guard intact), R20 non-strict. All three verdicts safe_to_merge with no findings left.
Merges conflicted only in STATUS.md headers and one test file (both sides kept); lead re-ran pytest (997) and rules evals on the merged R15 branch before merging. Live health ok after merge.
F reached 96%, so no second round this cycle.

## 2026-10-18 06:10 CDT | W 18→? % | F 29→? % | R14 | PR (see runs.log)
Live still served the pre-#92 bundle 10 h after merge. Cause (Render docs): `rootDir: backend` limits auto-deploys to backend/ changes; #92 was frontend-only.
Sonnet builder: render.yaml without rootDir, `cd backend` commands, buildFilter, test pins it; Sonnet reviewer: no blockers, 2 should-fix applied.
Live service `rebuttal` looks hand-made (Blueprint names `rebuttal-api`), so the redeploy and settings are USER item U4. Render MCP not used: it needs a person to pick the workspace.

## 2026-10-18 01:11 CDT | W 8→13 % | F 55→92 % | R13 | merged #92
Lead ran the dry-run checks itself (no team workflow: checks, not building): gitleaks 331 commits clean, README links ok except dead uvicorn.org, CI and live health green, live /#demo from a fresh Playwright browser works with zero console errors, judge commands leave the tree clean, 961 backend tests (96%), 99 e2e.
One real finding: the demo said "Sent to PayPal" though its banner promises nothing reaches PayPal. Sonnet builder added DemoContext; Sonnet reviewer found more demo strings (dialogs, leads, notes), fixed in one round, re-review clean. README counts fixed.
F reached 92% (other use in the 5-hour window), so no second task.

# Daily summary 2026-10-14
progress 48% (17/36 tasks done, 27 days to Nov 10 submit)
The daily system audit (Sonnet per component, fresh clone, Opus principal) found the system healthy: 469 tests pass, write boundary intact, no secrets.
It added 11 tasks (R1-R11), so the percent dropped from 58% to 48%; that is honest, not a regression.
Most important: mock mode wrote into the live Supabase database; fixed in this cycle (R1). Next: R2 guard fallback, R3-R6, R8-R9 small fixes, then S2, B2, B4.
Deadlines ahead: AG Studio first pass and video rough cut Oct 23 (B4 not started), feature freeze Nov 3.

## 2026-10-15 00:20 CDT | W 61→66 % | F 34→68 % | S3 | merged #74
One team-cycle workflow (24 agents, 60 min, strict). New manual script `scripts/spike_shapes.py` (writes only inside permit_writes) captured live fixtures: escalate rel exists, escalate accepted on an INQUIRY without buyer_escalation_reason and the stage stays INQUIRY; ESCALATE now only on the seller's turn (guard stricter). Mock and client fixed together; VERIFY notes removed only where a fixture proves it.
Principal (Opus) left one medium (mock kept buyer-only options on return to the seller) plus nits; a Sonnet fix round closed them, Opus re-review: write boundary and guard intact. Appeal, PROOF_OF_RETURN, buyer reply, CHARGEBACK options stay unverified: new task S4 (waiting).

## 2026-10-14 21:10 CDT | W 57→61+ % | F 1→31+ % | R10 part 2, C1 | merged #72, #73
One team-cycle workflow (46 agents, 59 min). R10 (strict, Opus principal: write boundary intact): mock drops offer options outside WAITING_FOR_SELLER_RESPONSE, VERIFY notes + whitespace-normalised seller message match, sandbox host allowlist (https only, or in-process MockTransport) and a read-only clone without the client secret. R10 done.
C1: contrast fixes, inbox loading/failed/empty states, keyboard tabs and safer confirm dialog (starts on Cancel, Enter never confirms), a11y labels, 375 px overflow fix; before/after PNGs in docs/screenshots/c1/. Integrator's STATUS edits conflicted again; resolved by keeping both entries.

## 2026-10-14 18:10 CDT | W 56→56+ % | F 77→79+ % | R10 part 1 | PR #71
F was 77 %, so no team workflow: one Sonnet builder for items (a) approve logged once per proposal and (e) no in-memory audit copy in Postgres mode, then an Opus reviewer (approval.py is a strict path): no blockers, write boundary and guard intact. Lead applied the two nits (test asserts the INSERT; comment on file-mode for_dispute).
R10 (b), (c), (d) stay queued; (d) touches paypal/client.py, so it needs a strict review too.

## 2026-10-14 16:45 CDT | W 46→55+ % | F 2→72+ % | S2, B2, B4 part 2 | merged #68, #70, #69
One team-cycle workflow (99 agents, 81 min). S2 (strict, Opus principal: write boundary intact): ESCALATE and APPEAL plus PROOF_OF_FULFILLMENT and PROOF_OF_RETURN, only via `execute`, gated on dispute links; mock-only shapes are VERIFY and queued as S3. Lead fixed the four low review nits (ADR 0001 write list, count, wraps); Sonnet re-review ok.
B2: saved views, starters e2e, licence note, widget screenshots, live Groq smoke pass. B4 part 2: Analytics segment + live-proof card, 2:50; USER item U3 added, USER alert sent.
Integrators again edited STATUS/QUEUE against the spec, so each merge conflicted in STATUS.md; resolved by keeping both entries. A `git push -q` from a worktree pushed nothing once (no upstream); push with `origin HEAD`.

## 2026-10-14 14:20 CDT | W 45→45 % | F 73→75 % | C3 | merged (this PR)
F was 73 %, so one size S docs task instead of a team workflow. Haiku chores split docs/discord-preview.md into an AG Grid post (A) and a general post (B) and wrote the U2 USER steps.
Sonnet reviewer caught that the public /#demo has no Analytics tab (it is in the signed-in dashboard); post A now asks about attached screenshots, and U2 step 0 says to take them.

## 2026-10-14 13:30 CDT | W 39→45 % | F 23→70 % | R2, R7, B4 part 1 | merged #65, #64, #66
One team-cycle workflow (81 agents, 63 min) built all three in parallel worktrees. R2 (strict, Opus principal confirmed write boundary and guard intact): rules fallback re-runs guard(), no-order cases cap at 0.3 and propose SUBMIT_EVIDENCE, CHARGEBACK without an option list refuses offers (VERIFY); rules evals unchanged at 85%.
R7: inbox load failure + Retry, readable execute_failed/interrupted audit text, widget remap shows incompleteDataMapping, DashboardErrorBoundary. B4 part 1: scripts/make_video.sh renders a 2:31 rough cut locally (ffmpeg installed via Homebrew; Playwright ffmpeg cache stubbed to system ffmpeg on this Mac).
Integrators edited STATUS/QUEUE despite the spec; resolved the STATUS conflicts by hand. Leftover worktree-wf_* local branches stay (git branch -D blocked).

## 2026-10-14 12:55 CDT | R2 | PR #65 open
Tech lead integrated R2: guard fallback re-runs guard(), missing order caps confidence at 0.3, CHARGEBACK without an option list refuses offers, _pick uses damage facts. Also fixed two audit findings in facts.py (damage words match at word start; refund-without-return sized by disputed amount). Rules evals unchanged (85% overall, 0 gate violations). ADR 0004 updated.

## 2026-10-14 11:50 CDT | W 38→39 % | F 18→21 % | R11 | merged #63
Sonnet builder: SYSTEM_PROMPT marks buyer messages as quotes, never instructions; guard converts tracking/evidence on a not-received dispute delivered to a non-matching address into OFFER_REPLACEMENT when PayPal allows it, else notes it and caps confidence at 0.5; ACCEPT_CLAIM contradicting delivery gets a note; SHARE_TRACKING draft only claims the order address when it matches. 501 tests, rules eval unchanged (85%).
Opus reviewer found a pre-existing gap (paypal_allows at CHARGEBACK with no options); added to R2. Cycle total: 6 S tasks merged (#58-#63), W 36→39 %.

## 2026-10-14 11:40 CDT | W 37→? % | F 11→? % | R4, R9 | merged #61, #62
R4: PayPal Disputes v1 schema.json says evidence_info.refund_ids is an array of 1-100 plain strings, so the request was already right; mock now rejects malformed refund_ids with 400 INVALID_REQUEST, VERIFY until a live PROOF_OF_REFUND. Opus reviewer confirmed the write boundary and the schema independently.
R9: evals.run and scripts.demo print only unless --save; README start commands unified (dropped REBUTTAL_ALLOW_OPEN_API, kept blank REBUTTAL_CHECKPOINT_URL), coverage 94%.

## 2026-10-14 11:11 CDT | W 36→37 % | F 3→11 % | R3, R6, R8 | merged #58, #59, #60
Three disjoint S tasks in parallel worktrees: Sonnet builders for R3 (facts.py duplicate filter: settled 'S' and same or missing invoice, VERIFY note on DUPLICATE_INVOICE_ID) and R6 (hours_left recomputed from the runtime clock at read time, Overdue pill), Haiku chores for R8 docs.
Reviewers: Opus on R3 (write boundary and guard confirmed intact, 26 boundary tests pass), Sonnet on R6 and R8; every should-fix fixed in one round. #59 conflicted with #58 in test_core.py (both added tests); kept both, 487 pass.
A reviewer ran evals in the main checkout and left RESULTS.md modified; restored from HEAD. Reviewer prompts must say: never run evals.

## 2026-10-14 08:31 CDT | W 34→? % | F 69→? % | R5 | merged (this PR)
Sonnet agent: webhook returns 400 for non-JSON or non-object bodies and ignores a null resource; list/analyze map PayPal 404 to 404 and other PayPal or transport errors to 502 (helper `paypal_read_failed`, logs status and debug_id only); 11 new tests (480 pass).
Lead slip in #55: merged before the docs-only fixup commit's CI finished; it then passed. From now on wait on `gh pr checks` for the last pushed commit.

## 2026-10-14 08:11 CDT | W 28→34 % | F 26→69 % | audit, R1 | merged #55
Daily system-audit: 41 raw findings, 11 verified tasks, 5 rejected, not critical. The audit alone used about 37% of the 5-hour window.
R1 built by a Sonnet agent: mock mode ignores DATABASE_URL unless REBUTTAL_MOCK_USE_DATABASE=1 (live_postgres.py opts in); explicit REBUTTAL_CHECKPOINT_URL still wins; 4 new tests.
Left undone on purpose: deleting the stray PP-D-2000 rows from the shared live database (no live effect).

## 2026-10-14 07:35 CDT | W 27→? % | F 19→? % | C2 | merged #53
Took C2 (docs) instead of S2: S2 needs a strict team-cycle run that will not fit the rest of this cycle. Sonnet wrote the README rework, docs/devpost.md, docs/discord-preview.md and docs/apimatic-form.md. The Sonnet reviewer caught the judge steps promising a model first choice and a guard change that the offline demo does not show, plus stale coverage (now 93%, 469 tests). All fixed.

## 2026-10-14 07:11 CDT | W 26→? % | F 8→? % | B1 part 3 | merged #52
Stale lock (04:11, 180 min) taken over; that cycle's team-cycle workflow had died after building and auditing 4 of 5 pieces. Salvaged them by cherry-pick, Sonnet integrator built p3 (Studio wiring, edit-mode toggle, since ag-studio 3.0.0 exposes `ai` only in edit mode) and opened #52. Sonnet reviewer, 3 rounds: shared Groq TokenBudget with the dispute agent (try_reserve), fixed an event-loop stall (reserve slept holding the budget lock), cancel on upstream failure, ADR 0010 + CLAUDE.md carve-out for the second model path.
Not verified live: no real Groq turn yet (B2 left items).

## 2026-10-14 03:12 CDT | W 23→23 % | F 63→63 % | queue sync | docs-only PR
Stale lock (Oct 13 21:31, over 170 min) taken over. Usage W 23%, cap 80 (no override), H 57, F 63. Queue status fixed: Q2 done #25, A3 done #9, B1 part 2 done #48 (were still 'in review'). No code task picked this cycle: remaining runnable work is S2 (M, PayPal write path, strict review) and B1 part 3 / B2 (L, Agent Framework); both need a full team-cycle run that will not fit the 2 h left in the 5-hour window, so they go to the next window. Progress 43→44 %.

## 2026-10-10 01:15 CDT | W 85→85 % | F 7→7 % | A5 live check | confirmed
`/` returns 200 and `/api/health` ok on Render, so A5 is done. No new task: headroom H=5 (cap 90) is too small for S2 (M, touches PayPal write paths); wait for a lower week or the Oct 14 reset.

## 2026-10-10 00:20 CDT | W 85→85 % | F 6→6 % | B3 holdout2 run | PR open
One Groq holdout2 eval: model alone 80%, final 100%, gate violations 0, no code changed. A8 moved to Oct 11 (one Groq eval per day). H=5, so no M task started (S2 waits).

## 2026-10-09 18:15 CDT | W 83→84 % | F 14→? % | Q4 | merged #42
make_sandbox_dispute.py + PayPalClient.create_dispute (write only inside permit_writes, manual script). Opus review: no blockers; 8 should-fix/low items fixed. Request body still VERIFY until a live run. Daily system-audit skipped: weekly headroom too small.

## 2026-10-09 16:15 CDT | W 82→82 % | F 3→3 % | S1 | PR open
Checked Orders v2 payloads and carrier values against the paypal-server-sdk models (installed in a scratch venv): no drift; SDK has no Disputes API. Logged in apimatic-log.md. QUEUE A4 marked done (script already on main). Docs only; no code touched.

Newest first. One block per working cycle; skipped cycles go to `~/.rebuttal-autopilot/runs.log` only.

## 2026-10-13 19:20 CDT (run id 001228 is UTC) | W 0→0 % | F 0→0 % | A8 eval re-run | done, PR #46 open
Weekly reset happened (W 0%, cap override 90 in `~/.rebuttal-autopilot/weekly-cap`, H=90). One Groq main-set run on current code: final 95% (19/20), model alone 75%, hard 4/4, gate violations 0, 27.5k tokens. Only miss `snad_outside_window` (judgment call). No agent code changed; numbers updated in `RESULTS.md`, `STATUS.md` and the video eval card. Live `/api/health` returned 502 once at 23:58 (keep-alive run failed) and 200 on recheck.
Not done this cycle: daily system-audit (due, not run: lead time-boxed to A8 with no team workflow); B1 part 2, S2 deferred to the next cycle.

## 2026-10-09 17:20 CDT | W 83→83 % | F 13→13 % | A5 live check | confirmed
`/api/health` ok and `/` returns 200 on Render, so the frontend build is served. No new task started: headroom H=7 (cap 90), nothing runnable beyond docs.

## 2026-10-09 16:40 CDT | W 82→~85 % | A5 | merged #39
Sonnet built same-origin SPA serving, sign-in (sessionStorage, "Try the demo" #demo), render.yaml frontend build. Reviewer: no blockers; fixed traversal test, null-byte 500, HEAD 405, and made the Render build fall back to API-only if Node/npm fails Live health ok after merge, but `/` returned 404 about 15 min later: not yet confirmed whether Render built the frontend (no Render MCP workspace selected, no key use).

## 2026-10-09 | A6 | in review (PR #33)
Judge demo mode built by the team workflow: per-visitor isolated mock Runtime (`demo.py`), public `/api/demo/{session}` router (`demo_api.py`), router shell + shared Desk + DemoApp on the frontend, docs and ADR 0009. Integration fixed the open audit findings (reset lock, 404 before 422, per-dispute lock growth, docstring, `demo-route` spec). approval.py, paypal/, facts.py, reasoner.py, config.py untouched. Needs lead review of the isolation; not run against Render.

ALERT weekly-80 2026-10-14T00:00:00Z sent

## 2026-10-09 11:35 CDT | W 72→81 % | F 29→98 % | A6 | merged #33
Team workflow built demo mode; Opus reviewer: no blockers, 1 medium (one client could evict all sessions) fixed with per-client limit (env REBUTTAL_DEMO_CLIENT_LIMIT, default 10/min) and 429 at capacity; e2e failure from shared-IP limit fixed. Live POST /api/demo/sessions returns 200 and health ok after deploy.

## 2026-10-09 09:15 CDT | W 68→72 % | F 10→26 % | Q3, A7 | merged #28, #26
Q3: official paypal-agent-toolkit can't be read-only, so a 4-tool read-only adapter now backs gather(); Opus review confirmed write boundary. A7 merged. Follow-up: replace waitForTimeout(500) in dev-strictmode.spec.ts; README/ADR source notes added.

## 2026-10-09 | Q3 | in review (PR #28)
The official `paypal-agent-toolkit` 1.11.0 cannot be made strictly read-only (langchain pin, `run()` dispatches every tool, `requests` bypasses our transport, no `fields=all`). Built by the team workflow: `agent/toolkit.py` (four read tools in the toolkit's shape over `client.read_only()`), `gather` wired to it by the lead, ADR 0008, README and prize-fit. Evals JSON identical before and after. APIMatic plugin not used, so no apimatic-log entry. Needs lead review: touches `facts.py`.

## 2026-10-09 | A7 | PR open
ConfirmDialog closed at once under the Vite dev server: StrictMode's simulated unmount calls `close()`, and the late `close` event ran `onCancel`. Fix: `onClose` only cancels when the dialog is really closed. New Playwright project server (Vite dev on 5174) and `e2e/dev-strictmode.spec.ts` failed before the fix, passes after. StrictMode stays on.

## 2026-10-09 | W 68% | F 6% | Q2 | PR open
Stale lock (180 min) taken over. ADRs written by a Sonnet agent, claims spot-checked against code and workflows. Q1 was already merged (#18).

## 2026-10-09 | B1 part 1 | in review (PR #16)
Analytics endpoints, AG Studio 3.0.0 Analytics tab and docs/ag-studio.md, built by the team workflow. Decision: Studio
runs unlicensed (watermark allowed); deadlines read the due date per waiting dispute because the mock/list may omit it.

## 2026-10-09 00:40-01:00 CDT | W 55→? % | F 6→? % | A1, A2 (+ A3, A4 started) | merged #6, this PR
Lead worked directly in the planner session instead of waiting for the 3 AM cycle (Manish's call). A1 keep-awake ping
merged (#6) and triggered. A2 held-out eval: model alone 80%, final 100%, 0 gate violations. Pacing below 80% dropped.
A3 frontend follow-ups and A4 video script running as Sonnet subagents in worktrees.

## 2026-10-09 | setup
Autopilot set up by the lead session: runbook `CYCLE.md`, queue `QUEUE.md`, scheduled task every 3 hours, alerts by
push and by issue in the private repo `manishwvn/rebuttal-alerts` (GitHub emails the @mention). PR #3 (frontend
slice 1) merged after review. Weekly usage at setup: 54% (resets Oct 14).
