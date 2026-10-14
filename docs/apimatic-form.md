# APIMatic sponsor prize: prepared answers

For Manish to paste into the APIMatic form. Claude does not submit it. The form's real questions were not read for
this draft, so the answers are written for the generic questions below; adapt them to the exact wording. Source for
every claim: [docs/apimatic-log.md](apimatic-log.md).

## Honest summary of the evidence

The evidence is thin. The plugin was used twice, both times as a check, and it changed no code. The APIMatic PayPal
Server SDK has no Disputes controller, and disputes are most of what Rebuttal calls. Say so plainly rather than
overstating; the log is public in the repo. Before submitting, add real uses to the log if they happen (the
"Candidate uses" at the bottom of the log are not done).

## How did you use the APIMatic Context Plugin?

We installed the APIMatic Context Plugin for PayPal (`paypal@context-plugins-local`, from
https://github.com/paypaldev/server-sdk-context-plugin-preview) on 2026-10-06 and used it in Claude Code while building
the PayPal integration in `backend/rebuttal/paypal/client.py`. We followed its Python skills (`python-models`,
`python-calling-endpoints`) and installed the `paypal-server-sdk` Python package it documents in a scratch virtual
environment to read the generated models. We used it to check our hand-written client against the SDK models.

## What did it help with?

1. Orders v2 payloads (2026-10-09). We checked the create-order body with `payment_source.paypal.experience_context`,
   the capture call, and the `POST /v2/checkout/orders/{id}/track` body against the SDK models: `OrderTrackerRequest`
   (`capture_id`, `tracking_number`, `carrier`, `carrier_name_other`, `notify_payer`, `items`),
   `PaypalWalletExperienceContext` (`return_url`, `cancel_url`), `OrderRequest`, and the `ShipmentCarrier` values. All
   matched what the client and the mock send. Result: no drift found, no change made.
2. Dispute creation (2026-10-09). We wanted the body of `POST /v1/customer/disputes` for our sandbox script that opens a
   dispute as a second business account. The SDK has no Disputes controller (it covers orders, payments, vault,
   subscriptions and transaction search), so it could not confirm the body. It did confirm the OAuth client-credentials
   pattern we reuse for the buyer account, and that the capture id is the seller transaction id of the disputed payment.
   The body follows the PayPal docs and carries a `VERIFY` note in the code until it runs against the live sandbox.

## What did it not help with?

- It did not change any file in either logged use; both were checks.
- It has no Disputes models, so the Disputes API (the core of Rebuttal) is checked against the PayPal docs and the live
  sandbox instead.
- We did not use the SDK in production code. Rebuttal keeps its own small `httpx` client so a read-only transport and an
  in-memory mock can gate every call.

## Links to evidence

- Log: https://github.com/manishwvn/rebuttal/blob/main/docs/apimatic-log.md
- Code the checks touched: https://github.com/manishwvn/rebuttal/blob/main/backend/rebuttal/paypal/client.py
  (`create_order`, `add_order_tracking`, `create_dispute`) and
  https://github.com/manishwvn/rebuttal/blob/main/backend/scripts/make_sandbox_dispute.py
- README section "Sponsor tools and PayPal APIs": https://github.com/manishwvn/rebuttal#sponsor-tools-and-paypal-apis
- Live demo: https://rebuttal-oq3g.onrender.com/#demo
- Video: <YouTube link, added by Manish>

## Short answer (if the form has a small text box)

We used the APIMatic Context Plugin for PayPal in Claude Code to check our PayPal client against the generated Server
SDK models. It confirmed our Orders v2 payloads and shipment tracking fields matched, and showed the SDK has no
Disputes API, so dispute shapes stay checked against PayPal's docs and the live sandbox. Two uses are logged in
docs/apimatic-log.md; neither changed code.

## Before you submit

- TODO (Manish): the free-subscription claim form linked in `docs/apimatic-log.md` is a separate form; do not submit
  anything from Claude Code.
- TODO: add more logged uses to `docs/apimatic-log.md` if the lead completes the "Candidate uses" first.
- Check the form's questions and the prize rules on Devpost; only one sponsor prize counts per project
  (see docs/prize-fit.md), and AG Grid is the main target.
