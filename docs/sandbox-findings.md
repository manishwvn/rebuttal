# Sandbox findings: Disputes shapes confirmed on the live sandbox (S3)

Run date: 2026-10-14. Sandbox only (`https://api-m.sandbox.paypal.com`). Every write below changed a sandbox dispute for
good. The disputes are the merchant app's own sandbox disputes; buyer-side actions used the second sandbox business
account. No order was created, no money moved, and no personal value is recorded here or in the fixtures.

## How to rerun

```
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes survey
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes escalate <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes send-message <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes buyer-reply <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes proof-of-return <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes appeal <dispute id>
```

`survey` only reads, but it overwrites the `sandbox_dispute_*` fixtures of the categories it finds. Each write command
saves redacted JSON to `backend/tests/fixtures/sandbox_<name>.json` under the same name every run, so a second run
overwrites the first. Every command refuses to run on the mock. `backend/tests/test_sandbox_fixtures.py` pins this
snapshot: after a rerun, update its targeted checks with the new findings.

## Fixtures (backend/tests/fixtures)

| File | What it holds |
| --- | --- |
| `sandbox_dispute_escalate_link.json` | PP-R-SVN-10190455, INQUIRY, WAITING_FOR_SELLER_RESPONSE, with the `escalate` link (before any write) |
| `sandbox_dispute_inquiry_waiting_seller.json` | Same dispute and state as above (survey category `inquiry_waiting_seller`) |
| `sandbox_dispute_inquiry_under_review.json` | PP-R-HDU-10190454 after the seller message and escalate, INQUIRY, UNDER_REVIEW |
| `sandbox_dispute_after_seller_message.json` | PP-R-HDU-10190454 after the seller message: status UNDER_REVIEW, `posted_by` SELLER |
| `sandbox_dispute_after_escalate.json` | PP-R-HDU-10190454 after escalate: stage still INQUIRY, no escalate link |
| `sandbox_dispute_after_buyer_reply.json` | PP-R-GBK-10190434, INQUIRY, WAITING_FOR_BUYER_RESPONSE, after a refused buyer reply (name kept from the script) |
| `sandbox_escalate_response.json` | Escalate record for PP-R-HDU-10190454 (the second escalate run; see item 2) |
| `sandbox_proof_of_return_response.json` | PROOF_OF_RETURN record for PP-R-GFH-10190453 (the second attempt; see item 4) |

Survey found no CHARGEBACK-stage dispute and no dispute with an appeal link, so there are no fixtures for those categories.

## Runs in order (all 2026-10-14)

1. `survey`: 5 disputes. PP-R-SVN-10190455, PP-R-HDU-10190454 and PP-R-GFH-10190453 are INQUIRY / WAITING_FOR_SELLER_RESPONSE
   (GFH is NOT_RECEIVED, the others NOT_AS_DESCRIBED). PP-R-GBK-10190434 and PP-R-AFT-10190433 are INQUIRY / WAITING_FOR_BUYER_RESPONSE.
2. `escalate PP-R-GFH-10190453` (waiting for the seller): accepted on the first try, no `buyer_escalation_reason`.
3. `proof-of-return PP-R-SVN-10190455`: refused, state unchanged.
4. `send-message PP-R-HDU-10190454`: accepted, status became UNDER_REVIEW.
5. `escalate PP-R-HDU-10190454` (after the seller message): accepted on the first try.
6. `survey` again (read): shows the states after 2 to 5.
7. `buyer-reply PP-R-GBK-10190434`: refused.
8. `proof-of-return PP-R-GFH-10190453`: refused (`provide_evidence` now listed).
9. `make_sandbox_dispute --transaction-id` on the GBK capture as the buyer account: refused.
10. `appeal PP-R-GFH-10190453`: precheck only, no appeal link, nothing sent.

Note on the order: the plan ran escalate on GFH before proof-of-return, which removed the `provide_evidence` link
from GFH at once. The link came back on the next read, so PROOF_OF_RETURN was retried on GFH at step 8 instead of
before the escalate. The refused SVN attempt at step 3 was saved first and then overwritten by step 8's record.
The escalate record for GFH (step 2) was overwritten by step 5's record. Its fields are quoted below.

## 1. Link rel names `escalate` and `appeal`

Run 2026-10-14, dispute PP-R-SVN-10190455 (survey, no write).

**Verdict: escalate CONFIRMED (`sandbox_dispute_escalate_link.json`); appeal STILL UNVERIFIED.**

- `escalate` is a rel on the dispute's `links`, method POST, href `.../disputes/<id>/escalate`.
- The action rels use underscores (`send_message`, `make_offer`, `accept_claim`, `provide_evidence`), the hrefs use
  hyphens (`send-message`, `make-offer`, `accept-claim`). `escalate` has no separator, so both forms agree.
- `appeal`: not seen. None of the 5 disputes had an appeal link, and the sandbox holds no resolved, lost chargeback
  (see item 3). The rel name stays unconfirmed.

## 2. Escalate accepted on an INQUIRY waiting for the seller

Run 2026-10-14, dispute PP-R-GFH-10190453 (NOT_RECEIVED, WAITING_FOR_SELLER_RESPONSE, `escalate` link present).

**Verdict: CONFIRMED. Escalate is accepted on an INQUIRY waiting for the seller.** Fixture: the record of this run was
overwritten. `sandbox_escalate_response.json` holds the second run (item 5), which was on an UNDER_REVIEW inquiry.

Observed for this run:
- `POST .../escalate` with `{"note": ...}` only returned 200 with `links: [{rel: "detail", method: GET}]`.
- Re-read at once: stage INQUIRY (not CHARGEBACK), status UNDER_REVIEW, links `[self]`.
- The note appeared as an evidence entry of type OTHER (on PP-R-HDU-10190454 the source is SUBMITTED_BY_SELLER).

## 3. Appeal body and the stage it moves to

Run 2026-10-14, dispute PP-R-GFH-10190453 (`appeal`, precheck only).

**Verdict: STILL UNVERIFIED.** The precheck printed `no appeal link at stage INQUIRY / UNDER_REVIEW; appeal not tried`
(exit 1, no request sent). Appeal needs a lost chargeback in CHARGEBACK or PRE_ARBITRATION. The sandbox has none, and
this run did not adjudicate one to make one. What would confirm it: a buyer-favour chargeback in the sandbox
(a buyer escalation or a human decision), then `appeal` with the same multipart body as provide-evidence.

## 4. The seller can send PROOF_OF_RETURN

Runs 2026-10-14, disputes PP-R-SVN-10190455 (step 3) and PP-R-GFH-10190453 (step 8).

**Verdict: STILL UNVERIFIED. PayPal refused PROOF_OF_RETURN both times.**

- PP-R-SVN-10190455 (NOT_AS_DESCRIBED, WAITING_FOR_SELLER_RESPONSE, no `provide_evidence` link): HTTP 422,
  `UNPROCESSABLE_ENTITY`, issue `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, debug id `f252997e374b7`. Nothing changed.
  This run's record was overwritten by step 8.
- PP-R-GFH-10190453 (NOT_RECEIVED, UNDER_REVIEW, `provide_evidence` link present): HTTP 400, `INVALID_REQUEST`, issue
  `EVIDENCE_TYPE_IS_NOT_ALLOWED`, debug id `f201119653905`. Nothing changed. Fixture: `sandbox_proof_of_return_response.json`.

So on a NOT_RECEIVED inquiry PayPal does not accept PROOF_OF_RETURN at all, and on a NOT_AS_DESCRIBED inquiry it offers
no evidence action. The shape of the body was not accepted anywhere. What would confirm it: a dispute that lists
`provide_evidence` for a return claim (a NOT_AS_DESCRIBED dispute at a stage where the seller may submit evidence).

## 5. Escalate after a seller reply, and a buyer reply

Runs 2026-10-14, disputes PP-R-HDU-10190454 (seller reply, then escalate) and PP-R-GBK-10190434 (buyer reply).

**Verdict: the status after send-message is CONFIRMED (`sandbox_dispute_after_seller_message.json`). Escalate after a
seller reply is accepted, which contradicts the VERIFY note. Whether a buyer reply returns the INQUIRY to
WAITING_FOR_SELLER_RESPONSE is STILL UNVERIFIED.**

- Seller `send-message` on an INQUIRY waiting for the seller: 200. Status became UNDER_REVIEW (not WAITING_FOR_BUYER_RESPONSE).
  The `escalate` rel disappeared (links `[self]`). The message is posted as `posted_by: SELLER` with the text we sent.
  `allowed_response_options` and `seller_response_due_date` disappeared too.
- Escalate on that same dispute, still UNDER_REVIEW and without an escalate link: accepted (200). Stage stayed INQUIRY,
  status UNDER_REVIEW, and an OTHER evidence entry was added. `sandbox_escalate_response.json` and
  `sandbox_dispute_after_escalate.json` hold this run. The client's VERIFY note said PayPal refused escalate on an
  INQUIRY in UNDER_REVIEW. That refusal was not reproduced here.
- Buyer reply: the second business account is refused. `send-message` as the buyer on PP-R-GBK-10190434
  (WAITING_FOR_BUYER_RESPONSE) returned HTTP 403, `NOT_AUTHORIZED`, issue `ACTION_NOT_ALLOWED`, debug id `f969866f974cb`.
  A buyer-created dispute on the same capture (`make_sandbox_dispute --transaction-id`) returned HTTP 400,
  `INVALID_REQUEST`, issue `INVALID_BUYER_TRANSACTION_ID`, debug id `f375785bc8a29`. So the second account is not the
  buyer on that capture. Confirming the return to WAITING_FOR_SELLER_RESPONSE needs a dispute that account opened.
  That needs a capture it paid, which means a buyer approval of a new order (a human step, not done in this run).

## 6. Does escalate need `buyer_escalation_reason`?

**Verdict: CONFIRMED, not required on these two disputes.** Escalate with `{"note": ...}` alone was accepted on
PP-R-GFH-10190453 (waiting for the seller) and on PP-R-HDU-10190454 (UNDER_REVIEW). The retry with
`buyer_escalation_reason` never ran. Fixture: `sandbox_escalate_response.json`, which holds the PP-R-HDU run.
The field may still be validated when a value is given, and this run did not test that.

## 7. Does the `escalate` link disappear after a successful escalate?

**Verdict: CONFIRMED (`sandbox_dispute_after_escalate.json`).** After escalate the links are `[self]` on PP-R-HDU-10190454.
PP-R-GFH-10190453 also read `[self]` right after its escalate. At the next survey it listed `provide_evidence` and
`self`, with no `escalate`.

Caveat for `approval.py`: the link is gone, but PayPal accepted an escalate on PP-R-HDU-10190454 while the link was
already absent (item 5). The link check in `not_allowed_now` is therefore a fail-closed guard, not a rule PayPal
applies. A second escalate on a dispute that has already been escalated was not tested.

## 8. Does a CHARGEBACK-stage dispute omit `allowed_response_options`?

**Verdict: STILL UNVERIFIED. No CHARGEBACK-stage dispute was found.** Survey printed
`CHARGEBACK: allowed_response_options absent on 0 of 0 disputes`. Escalate kept both escalated disputes at INQUIRY.
R12 stays blocked on this item.

## 9. Does an INQUIRY show `seller_response_due_date`?

**Verdict: CONFIRMED (`sandbox_dispute_escalate_link.json`, `sandbox_dispute_inquiry_under_review.json`).**
- INQUIRY / WAITING_FOR_SELLER_RESPONSE: present on all 3 such disputes at survey (SVN, HDU, GFH).
- INQUIRY / UNDER_REVIEW: absent (PP-R-HDU-10190454 and PP-R-GFH-10190453 after our writes), as the note in
  `scenarios.py` assumed.
- INQUIRY / WAITING_FOR_BUYER_RESPONSE: absent. It has `buyer_response_due_date` instead
  (`sandbox_dispute_after_buyer_reply.json`).

## Other observations

- `allowed_response_options` is listed on INQUIRY / WAITING_FOR_BUYER_RESPONSE too (PP-R-GBK-10190434 and PP-R-AFT-10190433;
  GBK lists `accept_claim` REFUND only). The mock lists them only while the seller is to respond.
- The `escalate` rel is listed on INQUIRY / WAITING_FOR_BUYER_RESPONSE (GBK, AFT). The mock offers it only for the seller turn.
- `seller_activity` shapes confirmed: a seller message is `posted_by: SELLER` (HDU). An offer appears as
  `offer.history[].actor: SELLER` with `offer_type: REFUND_WITH_RETURN`, and its note is also posted as a SELLER
  message at the same time (GBK, made before this run).
- Reads can lag a write. PP-R-GFH-10190453 showed `[self]` right after escalate and `provide_evidence` at the next read.
- Error codes seen: `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` (422), `EVIDENCE_TYPE_IS_NOT_ALLOWED` (400),
  `NOT_AUTHORIZED` / `ACTION_NOT_ALLOWED` (403), `INVALID_BUYER_TRANSACTION_ID` (400).
- The `create_dispute` body was parsed: the refusal names the transaction, not a field.

## Code changes this implies

Nothing in `rebuttal/` was changed by S3. Each row names the note to change and what the mock should do.

| Item | File and note | Change |
| --- | --- | --- |
| 1 | `paypal/client.py` `escalate` docstring | Keep the rel name. Drop the VERIFY on the rel. |
| 1 | `agent/facts.py` `dispute_actions` VERIFY | `escalate` confirmed. Keep the VERIFY for `appeal` only. |
| 1 | `paypal/mock.py` `dispute_links` | Offer `escalate` on INQUIRY in WAITING_FOR_BUYER_RESPONSE too (items seen on GBK and AFT). |
| 2 | `paypal/mock.py` `escalate` branch | Keep stage INQUIRY (the mock sets CHARGEBACK). Set status UNDER_REVIEW. Add an OTHER evidence entry (SUBMITTED_BY_SELLER) with the note. |
| 2 | `paypal/client.py` `escalate` VERIFY "refused in UNDER_REVIEW" | Replace with: accepted on PP-R-HDU-10190454 in UNDER_REVIEW without the link. Remove the "allowed case not yet confirmed" wording. |
| 2 | `paypal/mock.py` `_dispatch` escalate gate | Accept escalate in UNDER_REVIEW too, since PayPal did. Decide with the lead whether the link stays a gate on our side (see approval.py). |
| 3 | `paypal/mock.py` appeal VERIFY (lines near 27 and 368) | No change. Still unverified. |
| 4 | `paypal/mock.py` `_EVIDENCE_INFO_REQUIRED` and provide-evidence | Refuse PROOF_OF_RETURN on NOT_RECEIVED with 400 `EVIDENCE_TYPE_IS_NOT_ALLOWED`. Refuse provide-evidence with no `provide_evidence` link with 422 `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`. |
| 4 | `agent/pipeline.py` `_return_entries` | Do not send PROOF_OF_RETURN for NOT_RECEIVED. Keep the NOT_AS_DESCRIBED path as unconfirmed. |
| 5 | `agent/facts.py` `seller_activity` VERIFY | Confirmed for `messages` (posted_by SELLER) and `offers` (actor SELLER). Remove the VERIFY. Keep the unconfirmed buyer-after-offer part until a buyer reply works. |
| 5 | `approval.py` `already_applied` VERIFY (seller message and offer shapes) | Confirmed as above. Remove that VERIFY. |
| 5 | `paypal/mock.py` `send-message` VERIFY (lines near 342) | Status after a seller message is UNDER_REVIEW, which the mock already does. Keep the buyer-reply VERIFY. |
| 5 | `agent/reasoner.py` rule VERIFY near line 147 | Escalate was accepted in UNDER_REVIEW. Decide whether the ESCALATE rule should keep requiring the link. Keep the buyer-reply premise unverified. |
| 6 | `paypal/client.py` `escalate` VERIFY "is buyer_escalation_reason optional" | Confirmed not required on these disputes. Remove the VERIFY. |
| 7 | `approval.py` VERIFY on retry safety (`already_applied` docstring and near line 219) | The link disappears after a successful escalate. Note that PayPal accepted escalate with no link, so the link check is a fail-closed guard. Remove the "PayPal removing the link" VERIFY. A second escalate is still untested. |
| 8 | `agent/reasoner.py` `effective_options` VERIFY near line 85 | Keep. Still unverified. |
| 9 | `scenarios.py` `INQUIRY_RESPONSE_DAYS` VERIFY (line 20) | Confirmed: `seller_response_due_date` is absent in UNDER_REVIEW and WAITING_FOR_BUYER_RESPONSE, present in WAITING_FOR_SELLER_RESPONSE. Update the note. `scenarios.py` line 166 sets it on every INQUIRY, so the mock should set it only while the seller responds. |
| all | `tests/test_write_boundary.py` `MANUAL_SCRIPTS` | Add `spike_shapes.py` to the named manual scripts. Not done in S3 (see below). |

## Not run or not confirmed

- Item 3 (appeal), item 8 (CHARGEBACK) and the buyer-reply half of item 5: not reachable with the disputes in the sandbox.
- Item 4: PROOF_OF_RETURN refused on both disputes. The body shape was not accepted anywhere.
- The `buyer_escalation_reason` retry branch of `escalate` did not run.
- The write-boundary test `tests/test_write_boundary.py::test_scripts_and_evals_do_not_write_to_paypal_except_the_named_manual_tools`
  fails until `spike_shapes.py` is added to its `MANUAL_SCRIPTS` (not edited here, per the task).
