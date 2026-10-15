# Sandbox findings: Disputes shapes confirmed on the live sandbox (S3)

Run date: 2026-10-14. Sandbox only (`https://api-m.sandbox.paypal.com`). Every write below changed a sandbox dispute for
good. The disputes are the merchant app's own sandbox disputes; buyer-side actions used the second sandbox business
account. No order was created, no money moved, and no personal value is recorded here or in the fixtures.

Verdicts: CONFIRMED means a fixture in `backend/tests/fixtures` backs the claim (named in the verdict). Anything seen
only in console output is labelled run log only, and does not count as confirmed.

## How to rerun

```
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes survey
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes escalate <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes send-message <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes buyer-reply <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes proof-of-return <dispute id>
cd backend && REBUTTAL_MOCK=0 uv run python -u -m scripts.spike_shapes appeal <dispute id>
```

- `survey` only reads. It replaces the `sandbox_dispute_<category>.json` snapshots of the categories it finds.
- Each write command first checks the dispute's own links: `escalate` needs an `escalate` link on an INQUIRY,
  `proof-of-return` needs a `provide_evidence` link, `appeal` needs an `appeal` link. If the link is missing, nothing is
  sent. `send-message` and `buyer-reply` do not check a link.
- Each write sends a fresh `PayPal-Request-Id`. Its request and result go to the audit log (`REBUTTAL_AUDIT_PATH`, and
  the `rebuttal_audit` table when `DATABASE_URL` is set).
- Each write saves its redacted record as `backend/tests/fixtures/sandbox_<name>_<dispute id>.json`. It refuses before
  sending when that file exists, so a rerun on the same dispute never overwrites a record. Move the old file aside first.
- Every command refuses to run on the mock.

`backend/tests/test_sandbox_fixtures.py` pins this snapshot. After a rerun on a new dispute, add its targeted checks and
update the verdicts below.

## Fixtures (backend/tests/fixtures)

| File | What it holds |
| --- | --- |
| `sandbox_dispute_escalate_link.json` | PP-R-SVN-10190455, INQUIRY, WAITING_FOR_SELLER_RESPONSE, with the `escalate` link (before any write) |
| `sandbox_dispute_inquiry_waiting_seller.json` | Same dispute and state as above (survey category `inquiry_waiting_seller`) |
| `sandbox_dispute_inquiry_under_review.json` | PP-R-HDU-10190454 after the seller message and escalate, INQUIRY, UNDER_REVIEW |
| `sandbox_dispute_after_seller_message_PP-R-HDU-10190454.json` | PP-R-HDU-10190454 after the seller message: status UNDER_REVIEW, `posted_by` SELLER |
| `sandbox_dispute_after_escalate_PP-R-HDU-10190454.json` | PP-R-HDU-10190454 after escalate: stage still INQUIRY, no escalate link |
| `sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json` | PP-R-GBK-10190434, INQUIRY, WAITING_FOR_BUYER_RESPONSE, after a refused buyer reply |
| `sandbox_escalate_response_PP-R-HDU-10190454.json` | Escalate record for PP-R-HDU-10190454: before, first attempt, after |
| `sandbox_proof_of_return_response_PP-R-GFH-10190453.json` | PROOF_OF_RETURN record for PP-R-GFH-10190453: refused, with the after state |

Records of the first escalate on PP-R-GFH-10190453 (waiting for the seller), the refused PROOF_OF_RETURN on
PP-R-SVN-10190455, and the first appeal precheck were saved under names that the second run overwrote, or were not saved.
They are run log only.

Survey found no CHARGEBACK-stage dispute and no dispute with an appeal link, so there are no fixtures for those categories.

## Runs in order (all 2026-10-14)

1. `survey`: 5 disputes. PP-R-SVN-10190455, PP-R-HDU-10190454 and PP-R-GFH-10190453 are INQUIRY / WAITING_FOR_SELLER_RESPONSE
   (GFH is NOT_RECEIVED, the others NOT_AS_DESCRIBED). PP-R-GBK-10190434 and PP-R-AFT-10190433 are INQUIRY / WAITING_FOR_BUYER_RESPONSE.
2. `escalate PP-R-GFH-10190453` (waiting for the seller): accepted on the first try, no `buyer_escalation_reason`. Run log only.
3. `proof-of-return PP-R-SVN-10190455`: refused, state unchanged. Run log only. (The current script would not send it: SVN has no `provide_evidence` link.)
4. `send-message PP-R-HDU-10190454`: accepted, status became UNDER_REVIEW.
5. `escalate PP-R-HDU-10190454` (after the seller message): accepted on the first try. The escalate link was already absent
   here, so the current script would not send it.
6. `survey` again (read): shows the states after 2 to 5.
7. `buyer-reply PP-R-GBK-10190434`: refused.
8. `proof-of-return PP-R-GFH-10190453`: refused (`provide_evidence` now listed).
9. `make_sandbox_dispute --transaction-id` on the GBK capture as the buyer account: refused.
10. `appeal PP-R-GFH-10190453`: precheck only, no appeal link, nothing sent.

Note on the order: the plan ran escalate on GFH before proof-of-return, which removed the `provide_evidence` link
from GFH at once. The link came back on the next read, so PROOF_OF_RETURN was retried on GFH at step 8 instead of
before the escalate. The refused SVN attempt at step 3 was not saved, and the escalate record for GFH (step 2) was
not kept. Their details are in the run log only.

## 1. Link rel names `escalate` and `appeal`

Run 2026-10-14, dispute PP-R-SVN-10190455 (survey, no write).

**Verdict: escalate CONFIRMED (`sandbox_dispute_escalate_link.json`); appeal STILL UNVERIFIED.**

- `escalate` is a rel on the dispute's `links`, method POST, href `.../disputes/<id>/escalate`.
- The action rels use underscores (`send_message`, `make_offer`, `accept_claim`, `provide_evidence`), the hrefs use
  hyphens (`send-message`, `make-offer`, `accept-claim`). `escalate` has no separator, so both forms agree.
- `appeal`: not seen. None of the 5 disputes had an appeal link, and the sandbox holds no resolved, lost chargeback
  (see item 3). The rel name stays unconfirmed.

## 2. Escalate accepted on an INQUIRY

Run 2026-10-14, dispute PP-R-HDU-10190454 (escalate after the seller message, status UNDER_REVIEW, no escalate link).
Also run 2026-10-14 on PP-R-GFH-10190453 (WAITING_FOR_SELLER_RESPONSE, escalate link present): run log only.

**Verdict: CONFIRMED on an INQUIRY in UNDER_REVIEW (`sandbox_escalate_response_PP-R-HDU-10190454.json`). Acceptance on
an INQUIRY waiting for the seller: STILL UNVERIFIED as a fixture.** That run was accepted (200) in console output only,
and its record was overwritten by a later run. A rerun of `escalate` on a fresh waiting INQUIRY would save
`sandbox_escalate_response_<id>.json` and confirm it.

Observed on PP-R-HDU-10190454 (fixture):
- The first `POST .../escalate` with `{"note": ...}` only returned 200 with `links: [{rel: "detail", method: GET}]`.
- Stage stayed INQUIRY and status stayed UNDER_REVIEW. An evidence entry of type OTHER (source SUBMITTED_BY_SELLER) was added.
- The escalate link was absent before this escalate, so PayPal accepted escalate without the link. The current script refuses that case.

## 3. Appeal body and the stage it moves to

Run 2026-10-14, dispute PP-R-GFH-10190453 (`appeal`, precheck only).

**Verdict: STILL UNVERIFIED.** The precheck printed `no appeal link at stage INQUIRY / UNDER_REVIEW; appeal not tried`
(exit 1, no request sent). Appeal needs a lost chargeback in CHARGEBACK or PRE_ARBITRATION. The sandbox has none, and
this run did not adjudicate one to make one. What would confirm it: a buyer-favour chargeback in the sandbox
(a buyer escalation or a human decision), then `appeal` with the same multipart body as provide-evidence.

## 4. The seller can send PROOF_OF_RETURN

Runs 2026-10-14, disputes PP-R-SVN-10190455 (step 3, run log only) and PP-R-GFH-10190453 (step 8).

**Verdict: STILL UNVERIFIED. PayPal refused PROOF_OF_RETURN on both disputes.** Fixture for the GFH refusal:
`sandbox_proof_of_return_response_PP-R-GFH-10190453.json`.

- PP-R-GFH-10190453 (NOT_RECEIVED, UNDER_REVIEW, `provide_evidence` link present): HTTP 400, `INVALID_REQUEST`, issue
  `EVIDENCE_TYPE_IS_NOT_ALLOWED`, debug id `f201119653905`. Nothing changed (fixture, and `test_item_4`).
- PP-R-SVN-10190455 (NOT_AS_DESCRIBED, WAITING_FOR_SELLER_RESPONSE, no `provide_evidence` link): HTTP 422,
  `UNPROCESSABLE_ENTITY`, issue `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, debug id `f252997e374b7`. Run log only.
  The current script refuses to send this without the link.

PayPal refused PROOF_OF_RETURN once, on PP-R-GFH-10190453 (NOT_RECEIVED, fixture). On a NOT_AS_DESCRIBED inquiry
(PP-R-SVN-10190455, run log only) it offered no evidence action. One refusal does not show that PayPal never accepts
PROOF_OF_RETURN on a NOT_RECEIVED inquiry. The shape of the body was not accepted in either run. What would confirm it: a dispute that lists
`provide_evidence` for a return claim (a NOT_AS_DESCRIBED dispute at a stage where the seller may submit evidence).

## 5. Escalate after a seller reply, and a buyer reply

Runs 2026-10-14, disputes PP-R-HDU-10190454 (seller reply, then escalate) and PP-R-GBK-10190434 (buyer reply).

**Verdict: the status after a seller message is CONFIRMED (`sandbox_dispute_after_seller_message_PP-R-HDU-10190454.json`).
Escalate after a seller reply is accepted, CONFIRMED on the same UNDER_REVIEW escalate record
(`sandbox_escalate_response_PP-R-HDU-10190454.json`). Whether a buyer reply returns the INQUIRY to
WAITING_FOR_SELLER_RESPONSE is STILL UNVERIFIED.**

- Seller `send-message` on an INQUIRY waiting for the seller: accepted. Status became UNDER_REVIEW (not WAITING_FOR_BUYER_RESPONSE).
  The `escalate` rel disappeared (links `[self]`), and `allowed_response_options` and `seller_response_due_date` disappeared
  too. The message is posted as `posted_by: SELLER`. (fixture)
- Rule consequence: a seller offer leaves the INQUIRY in WAITING_FOR_BUYER_RESPONSE with the `escalate` link still present
  (`sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json`). The agent proposes ESCALATE only in
  WAITING_FOR_SELLER_RESPONSE (its turn), so it never asks PayPal to decide while the buyer is still considering our offer.
- Escalate on that same dispute, UNDER_REVIEW and without an escalate link: accepted. Stage stayed INQUIRY, status UNDER_REVIEW,
  and an OTHER evidence entry was added. The client's VERIFY note said PayPal refused escalate on an INQUIRY in UNDER_REVIEW.
  That refusal was not reproduced here. (fixture)
- Buyer reply: the second business account is refused. `send-message` as the buyer on PP-R-GBK-10190434
  (WAITING_FOR_BUYER_RESPONSE) returned HTTP 403, `NOT_AUTHORIZED`, issue `ACTION_NOT_ALLOWED`, debug id `f969866f974cb`
  (run log only; the buyer run saved only the after state, `sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json`,
  which is still WAITING_FOR_BUYER_RESPONSE). A buyer-created dispute on the same capture (`make_sandbox_dispute --transaction-id`)
  returned HTTP 400, `INVALID_REQUEST`, issue `INVALID_BUYER_TRANSACTION_ID`, debug id `f375785bc8a29` (run log only). So the second
  account is not the buyer on that capture. Confirming the return to WAITING_FOR_SELLER_RESPONSE needs a dispute that account
  opened. That needs a capture it paid, which means a buyer approval of a new order (a human step, not done in this run).

## 6. Does escalate need `buyer_escalation_reason`?

Run 2026-10-14, dispute PP-R-HDU-10190454 (fixture). Escalate on PP-R-GFH-10190453 without the field was also accepted (run log only).

**Verdict: CONFIRMED on PP-R-HDU-10190454 (`sandbox_escalate_response_PP-R-HDU-10190454.json`): escalate with `{"note": ...}`
alone was accepted, and the retry with `buyer_escalation_reason` never ran.** The field may still be validated when a value
is given. That was not tested, and the script's retry branch is therefore still unexercised.

## 7. Does the `escalate` link disappear after a successful escalate?

Runs 2026-10-14, disputes PP-R-HDU-10190454 and PP-R-GFH-10190453.

**Verdict: STILL UNVERIFIED for removal by escalate. No fixture pair shows it.**

- PP-R-HDU-10190454: the escalate link was already absent before the escalate (`before.link_rels` is `["self"]` in
  `sandbox_escalate_response_PP-R-HDU-10190454.json`). This dispute cannot show removal.
- PP-R-GFH-10190453: the escalate link was present before the escalate (survey, run log only). Right after the escalate
  the read showed `[self]` (run log only). `sandbox_proof_of_return_response_PP-R-GFH-10190453.json` shows a later read
  with `provide_evidence` and `self`, and no `escalate`. That is not a before/after pair.

Caveat for `approval.py`: the link check is a fail-closed guard, not a rule PayPal is shown to apply. PayPal accepted an
escalate on PP-R-HDU-10190454 with no link (item 2). A second escalate on a dispute already escalated was not tested.
Keep the retry-safety VERIFY in `approval.py` until a before/after fixture pair exists.

## 8. Does a CHARGEBACK-stage dispute omit `allowed_response_options`?

Run 2026-10-14, no dispute: survey only.

**Verdict: STILL UNVERIFIED. No CHARGEBACK-stage dispute was found.** Survey printed
`CHARGEBACK: allowed_response_options absent on 0 of 0 disputes`. Escalate kept both escalated disputes at INQUIRY.
R12 stays blocked on this item.

## 9. Does an INQUIRY show `seller_response_due_date`?

Runs 2026-10-14, disputes PP-R-SVN-10190455 (survey), PP-R-HDU-10190454 and PP-R-GBK-10190434 (after-write reads).

**Verdict: CONFIRMED (`sandbox_dispute_escalate_link.json`, `sandbox_dispute_inquiry_under_review.json`,
`sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json`).**
- INQUIRY / WAITING_FOR_SELLER_RESPONSE: `seller_response_due_date` present. Fixture for PP-R-SVN-10190455. Survey also
  showed it on PP-R-HDU-10190454 and PP-R-GFH-10190453 before our writes (run log only).
- INQUIRY / UNDER_REVIEW: absent (`sandbox_dispute_inquiry_under_review.json`). It has `buyer_response_due_date` instead.
- INQUIRY / WAITING_FOR_BUYER_RESPONSE: absent. It has `buyer_response_due_date` instead
  (`sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json`).

## Other observations

- `allowed_response_options` is listed on INQUIRY / WAITING_FOR_BUYER_RESPONSE too (PP-R-GBK-10190434, fixture: it lists
  `accept_claim` REFUND only). PP-R-AFT-10190433 showed the same in survey (run log only). The mock mirrors this: full options while the seller is to respond, `accept_claim` REFUND only while the buyer is.
- The `escalate` rel is also offered on INQUIRY / WAITING_FOR_BUYER_RESPONSE (PP-R-GBK-10190434, fixture
  `sandbox_dispute_after_buyer_reply_PP-R-GBK-10190434.json`). PP-R-AFT-10190433 showed it in survey (run log only).
  The mock offers it only for the seller turn.
- `seller_activity` shapes: a seller message is `posted_by: SELLER` (PP-R-HDU-10190454, fixture). An offer appears as
  `offer.history[].actor: SELLER` with `offer_type: REFUND_WITH_RETURN` (PP-R-GBK-10190434, fixture, made before this run).
- Reads can lag a write (run log only): PP-R-GFH-10190453 showed `[self]` right after escalate and `provide_evidence` at the next read.
- Error codes seen (each one's source is named): `EVIDENCE_TYPE_IS_NOT_ALLOWED` (400, fixture, `test_item_4`),
  `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` (422, run log), `NOT_AUTHORIZED` / `ACTION_NOT_ALLOWED` (403, run log),
  `INVALID_BUYER_TRANSACTION_ID` (400, run log).
- The `create_dispute` body was parsed: the refusal names the transaction, not a field (run log).

## Not run or not confirmed

- Item 3 (appeal), item 8 (CHARGEBACK) and the buyer-reply half of item 5: not reachable with the disputes in the sandbox.
- Item 4: PROOF_OF_RETURN refused on both disputes. The body shape was not accepted anywhere.
- Item 2: acceptance on an INQUIRY waiting for the seller has no fixture (run log only).
- Item 7: removal of the escalate link by escalate has no before/after fixture pair.
- The `buyer_escalation_reason` retry branch of `escalate` did not run.
- `send-message` and `buyer-reply` do not check a link before sending (the escalate and proof-of-return prechecks do).

## Code changes this implies (applied in the S3 PR unless marked "kept")

The first column is the item above. "Kept" means the VERIFY note stays because the item is STILL UNVERIFIED.

| Item | File and note | What the PR did |
| --- | --- | --- |
| 1 | `client.py` `escalate` docstring, `facts.py` `dispute_actions` | Escalate rel marked confirmed. `appeal` rel VERIFY kept. |
| 1 | `mock.py` `dispute_links` | `escalate` offered on INQUIRY in WAITING_FOR_BUYER_RESPONSE too. Not offered in UNDER_REVIEW. |
| 2 | `mock.py` escalate | Stage stays INQUIRY, status UNDER_REVIEW, an OTHER evidence entry (SUBMITTED_BY_SELLER) carries the note. Accepted at any open INQUIRY, link or not, as PayPal did. A conflicting earlier refusal is noted as a VERIFY. Acceptance while waiting for the seller: kept as unverified in the `client.py` docstring. |
| 3 | `mock.py`, `client.py` appeal | Kept. |
| 4 | `mock.py` provide-evidence | PROOF_OF_RETURN on a NOT_RECEIVED inquiry is refused with 400 `EVIDENCE_TYPE_IS_NOT_ALLOWED`. The PROOF_OF_RETURN acceptance VERIFY is kept. `pipeline.py` unchanged: it sends PROOF_OF_RETURN only with a received return on file. The 422 `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE` on a dispute with no `provide_evidence` link has no fixture, so the mock was not changed for it (it also differs: the live GFH dispute offered `provide_evidence` in UNDER_REVIEW, which the mock never does). |
| 5 | `facts.py` `seller_activity`, `approval.py` `already_applied` | Message and offer shape VERIFY removed. |
| 5 | `mock.py` send-message, `reasoner.py` ESCALATE rule | Status UNDER_REVIEW confirmed. Buyer-reply VERIFY kept in both. |
| 6 | `client.py` `escalate` | `buyer_escalation_reason` VERIFY removed. The client still omits the field. |
| 7 | `approval.py` retry safety | Kept, now saying the link check is our own fail-closed guard. |
| 8 | `reasoner.py` `effective_options` | Kept. R12 stays blocked. |
| 9 | `scenarios.py`, `mock.py` | Note updated. The mock drops `seller_response_due_date` once the dispute leaves WAITING_FOR_SELLER_RESPONSE. |
| all | `tests/test_write_boundary.py` | `spike_shapes.py` added to the named manual scripts (it enters `permit_writes()` explicitly). |

Observed but not mirrored in the mock: `provide_evidence` offered in UNDER_REVIEW; `seller_response_due_date` is not restored when a dispute returns to WAITING_FOR_SELLER_RESPONSE. The mock does mirror
`allowed_response_options` listing `accept_claim` REFUND on INQUIRY / WAITING_FOR_BUYER_RESPONSE.

## S4 run, 2026-10-15

PP-R-HDU-10190454 and PP-R-GFH-10190453, escalated by S3, had moved to CHARGEBACK / WAITING_FOR_SELLER_RESPONSE by the
next day. Commands: `spike_shapes survey`, `accept-return`, `adjudicate` (new), and `spike_retry --only provide_evidence`.

| # | Question | Verdict |
|---|---|---|
| 1 | Does PayPal send `allowed_response_options` at CHARGEBACK? | CONFIRMED yes, on both (survey). For NOT_AS_DESCRIBED it lists only `accept_claim`: REFUND, PARTIAL_REFUND, REFUND_WITH_RETURN, REFUND_WITH_RETURN_SHIPMENT_LABEL, and no `make_offer` (`sandbox_dispute_chargeback.json`). Links: accept_claim, provide_evidence, self. Unblocks R12. |
| 2 | accept-claim REFUND_WITH_RETURN at CHARGEBACK | CONFIRMED: refused without an address, 400 `MISSING_RETURN_SHIPPING_ADDRESS` (`sandbox_accept_return_no_address_PP-R-HDU-10190454.json`); accepted with `return_shipping_address`; the dispute became UNDER_REVIEW with only `provide_supporting_info` and no option list (`sandbox_accept_return_response_PP-R-HDU-10190454.json`; the redaction hides the retry body, the after state shows it landed). |
| 3 | Sandbox `adjudicate` to make a lost (appealable) case | Refused, 400 `ACTION_NOT_ALLOWED_IN_CURRENT_DISPUTE_STATE`, at CHARGEBACK in both WAITING_FOR_SELLER_RESPONSE and UNDER_REVIEW (after PROOF_OF_FULFILLMENT evidence) (`sandbox_adjudicate_*_PP-R-GFH-10190453.json`). The appeal rel, body and next stage stay unverified. |
| 4 | Evidence at CHARGEBACK | Run log only: PROOF_OF_FULFILLMENT via `spike_retry` accepted on GFH; status UNDER_REVIEW, link `provide_supporting_info`. |

Changes: the mock lists the captured CHARGEBACK options for NOT_AS_DESCRIBED and mirrors item 2; `client.accept_claim`
takes `accept_claim_type` and `return_address`; `pipeline.accept_with_return` plans REFUND_WITH_RETURN with the store's
return address when the item must come back and PayPal lists that type (R12); `approval.not_allowed_now` refuses a claim
type PayPal no longer lists. Tests: `tests/test_chargeback_return.py`.

Same day, live end to end: approving the Oct 7 proposal for PP-R-SVN-10190455 on the Render backend ran
approve > execute (`make_offer` REFUND_WITH_RETURN) > record EXECUTED; PayPal shows the dispute UNDER_REVIEW.
