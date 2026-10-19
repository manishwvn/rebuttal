# Eval results

Every valid run is kept in `evals/results/<provider>-<model>[-holdout|-holdout2]-<date>.json`. A run that hit a rate or quota limit is invalid and is never saved. Rules baseline = no model. **Model alone** is the model's own choice before `guard()`; **final** is what the agent would propose after the guard.

## Main set (evals/cases.json)

20 labeled disputes. The guard rules and the facts were developed against these.

| Date | Provider | Model | Model alone | Final (model + guard) | Standard | Hard | Guard changed | Tokens | Gate violations | Langfuse experiment |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-07 | groq | qwen/qwen3.8-27b | final only | 90% (18/20) | 88% | 100% of 4 | n/a | 27,146 | 0 | groq-qwen3.8-27b-20261007-112629 |
| 2026-10-07 | groq | qwen/qwen3.8-27b | final only | 85% (17/20) | 81% | 100% of 4 | n/a | 27,199 | 0 | groq-qwen3.8-27b-20261007-043611 |
| 2026-10-07 | nvidia | z-ai/glm-5.3 | final only | 100% (20/20) | 100% | 100% of 4 | n/a | 53,138 | 0 | nvidia-glm-5.3-20261007-055102 |
| 2026-10-07 | nvidia | z-ai/glm-5.3-flash | final only | 95% (19/20) | 94% | 100% of 4 | n/a | 59,808 | 0 | nvidia-glm-5.3-flash-20261007-064723 |
| 2026-10-14 | groq | qwen/qwen3.8-27b | 75% (15/20) | 95% (19/20) | 94% | 100% of 4 | 4/20 (20%) | 27,532 | 0 | groq-qwen3.8-27b-20261014-001228 |
| 2026-10-19 | groq | qwen/qwen3.8-27b | 75% (15/20) | 85% (17/20) | 81% | 100% of 4 | 2/20 (10%) | 31,471 | 0 |  |

Per case: `yes` = the final action matches the label; otherwise the final action is shown, and `(model: X)` means the model alone chose X before the guard changed it. Runs marked final only have no raw choice.

| Case | Expected | groq/qwen3.8-27b 10-07 | groq/qwen3.8-27b 10-07 | nvidia/glm-5.3 10-07 | nvidia/glm-5.3-flash 10-07 | groq/qwen3.8-27b 10-14 | groq/qwen3.8-27b 10-19 |
|---|---|---|---|---|---|---|---|
| agent_wrong_size | OFFER_RETURN_FOR_REFUND | yes | yes | yes | yes | yes (model: OFFER_REPLACEMENT) | yes |
| inr_delivered | SHARE_TRACKING | yes | yes | yes | yes | yes | yes |
| inr_delivered_claim | SUBMIT_EVIDENCE | yes | yes | yes | yes | yes | yes |
| inr_in_transit | SHARE_TRACKING | yes | yes | yes | yes | yes | yes |
| inr_no_tracking | ACCEPT_CLAIM | yes | **OFFER_REPLACEMENT** | yes | yes | yes (model: OFFER_REPLACEMENT) | yes |
| inr_misdelivered | OFFER_REPLACEMENT | yes | yes | yes | yes | yes | yes (model: ESCALATE) |
| snad_changed_mind | OFFER_RETURN_FOR_REFUND | yes | yes | yes | yes | yes | yes |
| snad_damaged_low_value | ACCEPT_CLAIM | yes | yes | yes | yes | yes | yes |
| snad_damaged_high_value | OFFER_RETURN_FOR_REFUND | **ACCEPT_CLAIM** | yes | yes | yes | yes (model: OFFER_REPLACEMENT) | **OFFER_PARTIAL_REFUND** |
| snad_outside_window (judgment call) | SUBMIT_EVIDENCE | **OFFER_PARTIAL_REFUND** | **OFFER_PARTIAL_REFUND** | yes | **OFFER_PARTIAL_REFUND** | **OFFER_PARTIAL_REFUND** | **OFFER_PARTIAL_REFUND** |
| unauth_agent_mandate | SUBMIT_EVIDENCE | yes | yes | yes | yes | yes | yes |
| unauth_delivered | SUBMIT_EVIDENCE | yes | **SHARE_TRACKING** | yes | yes | yes | **OFFER_RETURN_FOR_REFUND** |
| cnp_refunded | SUBMIT_REFUND_PROOF | yes | yes | yes | yes | yes | yes |
| cnp_owed | ACCEPT_CLAIM | yes | yes | yes | yes | yes | yes |
| duplicate_true | ACCEPT_CLAIM | yes | yes | yes | yes | yes | yes |
| duplicate_false | SUBMIT_EVIDENCE | yes | yes | yes | yes | yes | yes |
| hard_inr_wrong_color (hard) | OFFER_REPLACEMENT | yes | yes | yes | yes | yes | yes |
| hard_stuck_wants_refund (hard) | ACCEPT_CLAIM | yes | yes | yes | yes | yes | yes |
| hard_two_pieces (hard) | ACCEPT_CLAIM | yes | yes | yes | yes | yes | yes |
| hard_agent_right_size (hard) | OFFER_RETURN_FOR_REFUND | yes | yes | yes | yes | yes (model: OFFER_REPLACEMENT) | yes (model: OFFER_REPLACEMENT) |

Judgment calls:

- `snad_outside_window`: A buyer 91 days out of the return window, not asking for a refund. We label it SUBMIT_EVIDENCE (the policy wins, so defend). OFFER_PARTIAL_REFUND is a defensible business choice that avoids a fight over $40, so models that pick it are not clearly wrong.

Oct 19 drop (95% to 85%, task R23): model noise, no guard or facts regression. Model alone is 75% in both runs; the
final score fell because the guard had less to fix. Compared per case (`results/groq-qwen3.8-27b-20261014.json` vs `-20261019.json`):

- `snad_damaged_high_value`: Oct 14 the model chose OFFER_REPLACEMENT and the guard turned it into OFFER_RETURN_FOR_REFUND
  (PayPal does not allow a replacement on not-as-described). Oct 19 the model chose OFFER_PARTIAL_REFUND, which is
  allowed and which the guard never converted in either run (no guard rule targets a partial offer on damage; the
  `f4cb66d` rule only converts a bare ACCEPT_CLAIM). Facts for the case are unchanged. Model noise.
- `unauth_delivered`: Oct 14 the model chose SUBMIT_EVIDENCE; Oct 19 it chose OFFER_RETURN_FOR_REFUND. The guard has no rule
  on UNAUTHORISED offers in either version. Model noise.
- `snad_outside_window`: OFFER_PARTIAL_REFUND in both runs, the existing judgment call above. Not a change.
- Offsetting guard saves on Oct 19: `inr_misdelivered` (model ESCALATE, guard fell back to OFFER_REPLACEMENT) while
  `agent_wrong_size`, `inr_no_tracking` and `snad_damaged_high_value` no longer needed the guard.
- Held-out 2 `ho2_unauth_over_cap` (model OFFER_PARTIAL_REFUND, wanted ACCEPT_CLAIM): reported only, no code change.

## Held-out (not used for tuning)

evals/holdout.json: 10 disputes written independently of the guard and facts code. Run and reported only; no code is tuned against these results.

| Date | Provider | Model | Model alone | Final (model + guard) | Standard | Hard | Guard changed | Tokens | Gate violations | Langfuse experiment |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-09 | groq | qwen/qwen3.8-27b | 80% (8/10) | 100% (10/10) | 100% | 100% of 3 | 2/10 (20%) | 13,685 | 0 | groq-qwen3.8-27b-holdout-20261009-054233 |
| 2026-10-19 | groq | qwen/qwen3.8-27b | 70% (7/10) | 100% (10/10) | 100% | 100% of 3 | 3/10 (30%) | 15,737 | 0 |  |

Per case: `yes` = the final action matches the label; otherwise the final action is shown, and `(model: X)` means the model alone chose X before the guard changed it. Runs marked final only have no raw choice.

| Case | Expected | groq/qwen3.8-27b 10-09 | groq/qwen3.8-27b 10-19 |
|---|---|---|---|
| ho_agent_wrong_color | OFFER_RETURN_FOR_REFUND | yes (model: OFFER_REPLACEMENT) | yes (model: OFFER_REPLACEMENT) |
| ho_inr_porch | SHARE_TRACKING | yes | yes (model: ESCALATE) |
| ho_claim_no_tracking | ACCEPT_CLAIM | yes | yes |
| ho_lost_wants_replacement (hard) | OFFER_REPLACEMENT | yes | yes |
| ho_split_lamp (hard) | OFFER_RETURN_FOR_REFUND | yes (model: OFFER_REPLACEMENT) | yes (model: OFFER_REPLACEMENT) |
| ho_snapped_mug (hard) | ACCEPT_CLAIM | yes | yes |
| ho_colour_preference | OFFER_RETURN_FOR_REFUND | yes | yes |
| ho_refund_already_sent | SUBMIT_REFUND_PROOF | yes | yes |
| ho_unauth_assistant_reorder | SUBMIT_EVIDENCE | yes | yes |
| ho_duplicate_two_orders | SUBMIT_EVIDENCE | yes | yes |

## Held-out set 2 (one case later fixed)

evals/holdout2.json: 10 more disputes, written blind to the guard and facts code. Run and reported; one case (ho2_dup_already_refunded) prompted a fix, see notes.

| Date | Provider | Model | Model alone | Final (model + guard) | Standard | Hard | Guard changed | Tokens | Gate violations | Langfuse experiment |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-10 | groq | qwen/qwen3.8-27b | 80% (8/10) | 100% (10/10) | 100% | 100% of 6 | 2/10 (20%) | 13,979 | 0 | groq-qwen3.8-27b-holdout2-20261010-051607 |
| 2026-10-19 | groq | qwen/qwen3.8-27b | 70% (7/10) | 90% (9/10) | 100% | 83% of 6 | 2/10 (20%) | 16,106 | 0 |  |

Per case: `yes` = the final action matches the label; otherwise the final action is shown, and `(model: X)` means the model alone chose X before the guard changed it. Runs marked final only have no raw choice.

| Case | Expected | groq/qwen3.8-27b 10-10 | groq/qwen3.8-27b 10-19 |
|---|---|---|---|
| ho2_inr_nothing_shipped | ACCEPT_CLAIM | yes (model: OFFER_REPLACEMENT) | yes (model: OFFER_REPLACEMENT) |
| ho2_inr_unit_format (note) | SHARE_TRACKING | yes | yes |
| ho2_inr_digits_swapped (hard) | OFFER_REPLACEMENT | yes | yes |
| ho2_snad_dead_fan (hard) | OFFER_RETURN_FOR_REFUND | yes (model: OFFER_REPLACEMENT) | yes (model: OFFER_REPLACEMENT) |
| ho2_snad_rough_spoon (hard) | ACCEPT_CLAIM | yes | yes |
| ho2_unauth_over_cap (hard) | ACCEPT_CLAIM | yes | **OFFER_PARTIAL_REFUND** |
| ho2_unauth_standing_filters | SUBMIT_EVIDENCE | yes | yes |
| ho2_dup_already_refunded (note) | SUBMIT_REFUND_PROOF | yes | yes |
| ho2_cnp_refund_posted | SUBMIT_REFUND_PROOF | yes | yes |
| ho2_cnp_return_received | ACCEPT_CLAIM | yes | yes |

Notes:

- `ho2_inr_unit_format`: The rules baseline missed this in the Oct 18 audit (OFFER_REPLACEMENT instead of SHARE_TRACKING, because the facts code did not normalise street suffixes or unit markers). That miss prompted the R16 fix: addresses are normalised, and the same house number, ZIP and city with different wording is 'uncertain' and never turned into a replacement. The case and its label are kept unchanged, and later results on this case are not blind.
- `ho2_dup_already_refunded`: The rules baseline missed this in the Oct 18 audit (ACCEPT_CLAIM, a second refund). That miss prompted the R15 fix: the rules check the refund before the duplicate charge, and guard() refuses a second refund. The case and its label are kept unchanged, and it now passes. This was a real fix prompted by a held-out result, so later results on this case are no longer blind.
