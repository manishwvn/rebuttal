# Eval results (mock / nvidia)

- Overall: 80% of 20 labeled disputes
- Standard cases: 75%
- Hard cases (meaning, not keywords): 100% of 4
- PayPal writes before merchant approval: 0

| Case | Expected | Got | OK |
|---|---|---|---|
| hard_agent_right_size (hard) | OFFER_RETURN_FOR_REFUND | OFFER_RETURN_FOR_REFUND | yes |
| hard_two_pieces (hard) | ACCEPT_CLAIM | ACCEPT_CLAIM | yes |
| hard_stuck_wants_refund (hard) | ACCEPT_CLAIM | ACCEPT_CLAIM | yes |
| hard_inr_wrong_color (hard) | OFFER_REPLACEMENT | OFFER_REPLACEMENT | yes |
| duplicate_false | SUBMIT_EVIDENCE | SHARE_TRACKING | NO |
| duplicate_true | ACCEPT_CLAIM | ACCEPT_CLAIM | yes |
| cnp_owed | ACCEPT_CLAIM | SUBMIT_EVIDENCE | NO |
| cnp_refunded | SUBMIT_REFUND_PROOF | SUBMIT_REFUND_PROOF | yes |
| unauth_delivered | SUBMIT_EVIDENCE | SUBMIT_EVIDENCE | yes |
| unauth_agent_mandate | SUBMIT_EVIDENCE | SUBMIT_EVIDENCE | yes |
| snad_outside_window | SUBMIT_EVIDENCE | SHARE_TRACKING | NO |
| snad_damaged_high_value | OFFER_RETURN_FOR_REFUND | OFFER_RETURN_FOR_REFUND | yes |
| snad_damaged_low_value | ACCEPT_CLAIM | ACCEPT_CLAIM | yes |
| snad_changed_mind | OFFER_RETURN_FOR_REFUND | OFFER_RETURN_FOR_REFUND | yes |
| inr_misdelivered | OFFER_REPLACEMENT | SUBMIT_EVIDENCE | NO |
| inr_no_tracking | ACCEPT_CLAIM | ACCEPT_CLAIM | yes |
| inr_in_transit | SHARE_TRACKING | SHARE_TRACKING | yes |
| inr_delivered_claim | SUBMIT_EVIDENCE | SUBMIT_EVIDENCE | yes |
| inr_delivered | SHARE_TRACKING | SHARE_TRACKING | yes |
| agent_wrong_size | OFFER_RETURN_FOR_REFUND | OFFER_RETURN_FOR_REFUND | yes |
