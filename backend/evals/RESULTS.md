# Eval results

Every valid run is kept in `evals/results/<provider>-<model>-<date>.json`. A run that hit a rate or quota limit is invalid and is never saved. Rules baseline = no model.

| Date | Provider | Model | Overall | Standard | Hard | Tokens | Gate violations | Langfuse experiment |
|---|---|---|---|---|---|---|---|---|
| 2026-10-07 | groq | qwen/qwen3.8-27b | 90% (18/20) | 88% | 100% of 4 | 27,146 | 0 | groq-qwen3.8-27b-20261007-112629 |
| 2026-10-07 | groq | qwen/qwen3.8-27b | 85% (17/20) | 81% | 100% of 4 | 27,199 | 0 | groq-qwen3.8-27b-20261007-043611 |
| 2026-10-07 | nvidia | z-ai/glm-5.3 | 100% (20/20) | 100% | 100% of 4 | 53,138 | 0 | nvidia-glm-5.3-20261007-055102 |
| 2026-10-07 | nvidia | z-ai/glm-5.3-flash | 95% (19/20) | 94% | 100% of 4 | 59,808 | 0 | nvidia-glm-5.3-flash-20261007-064723 |

## Per case (yes = matches the label; otherwise what the run chose)

| Case | Expected | groq/qwen3.8-27b 10-07 | groq/qwen3.8-27b 10-07 | nvidia/glm-5.3 10-07 | nvidia/glm-5.3-flash 10-07 |
|---|---|---|---|---|---|
| hard_agent_right_size (hard) | OFFER_RETURN_FOR_REFUND | yes | yes | yes | yes |
| hard_two_pieces (hard) | ACCEPT_CLAIM | yes | yes | yes | yes |
| hard_stuck_wants_refund (hard) | ACCEPT_CLAIM | yes | yes | yes | yes |
| hard_inr_wrong_color (hard) | OFFER_REPLACEMENT | yes | yes | yes | yes |
| duplicate_false | SUBMIT_EVIDENCE | yes | yes | yes | yes |
| duplicate_true | ACCEPT_CLAIM | yes | yes | yes | yes |
| cnp_owed | ACCEPT_CLAIM | yes | yes | yes | yes |
| cnp_refunded | SUBMIT_REFUND_PROOF | yes | yes | yes | yes |
| unauth_delivered | SUBMIT_EVIDENCE | yes | **SHARE_TRACKING** | yes | yes |
| unauth_agent_mandate | SUBMIT_EVIDENCE | yes | yes | yes | yes |
| snad_outside_window (judgment call) | SUBMIT_EVIDENCE | **OFFER_PARTIAL_REFUND** | **OFFER_PARTIAL_REFUND** | yes | **OFFER_PARTIAL_REFUND** |
| snad_damaged_high_value | OFFER_RETURN_FOR_REFUND | **ACCEPT_CLAIM** | yes | yes | yes |
| snad_damaged_low_value | ACCEPT_CLAIM | yes | yes | yes | yes |
| snad_changed_mind | OFFER_RETURN_FOR_REFUND | yes | yes | yes | yes |
| inr_misdelivered | OFFER_REPLACEMENT | yes | yes | yes | yes |
| inr_no_tracking | ACCEPT_CLAIM | yes | **OFFER_REPLACEMENT** | yes | yes |
| inr_in_transit | SHARE_TRACKING | yes | yes | yes | yes |
| inr_delivered_claim | SUBMIT_EVIDENCE | yes | yes | yes | yes |
| inr_delivered | SHARE_TRACKING | yes | yes | yes | yes |
| agent_wrong_size | OFFER_RETURN_FOR_REFUND | yes | yes | yes | yes |

## Judgment calls

- `snad_outside_window`: A buyer 91 days out of the return window, not asking for a refund. We label it SUBMIT_EVIDENCE (the policy wins, so defend). OFFER_PARTIAL_REFUND is a defensible business choice that avoids a fight over $40, so models that pick it are not clearly wrong.
