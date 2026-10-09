# Where the APIMatic Context Plugin helped

The APIMatic prize needs evidence that the APIMatic Context Plugin for PayPal shaped our integration. Add one entry
per use, as it happens: date, what we asked, what the plugin gave, and which file changed.

Plugin: `paypal@context-plugins-local`, from
https://github.com/paypaldev/server-sdk-context-plugin-preview (skills for the APIMatic-generated PayPal Server SDK).
Installed 2026-10-06 with `npx context-plugins install <repo> --targets claude`.
Free subscription claim form: https://docs.google.com/forms/d/e/1FAIpQLScc2oCgAFACm7d6H3R4mgzv-O34DdyVnLIBNiwmUNggr_-hhA/viewform
(Manish submits it; do not submit it from Claude Code.)

| Date | What we asked | What the plugin gave | Files changed |
|---|---|---|---|
| 2026-10-09 | Do our Orders v2 payloads (create order with `payment_source.paypal.experience_context`, capture, `POST /v2/checkout/orders/{id}/track` body, carrier values) match the PayPal Server SDK models? The plugin's skills are language-generic (no Orders models), so we installed the `paypal-server-sdk` Python package (the SDK the plugin documents) in a scratch venv and read its models, following `python-models` and `python-calling-endpoints` guidance. | `OrderTrackerRequest` fields: `capture_id`, `tracking_number`, `carrier`, `carrier_name_other`, `notify_payer`, `items`; `PaypalWalletExperienceContext` has `return_url` / `cancel_url`; `OrderRequest` has `intent`, `purchase_units`, `payment_source`; `ShipmentCarrier` has `UPS` and `USPS`. All match what `paypal/client.py` and the mock send. No drift. The SDK has no Disputes controller (controllers: orders, payments, vault, subscriptions, transaction search), so dispute shapes stay checked against the PayPal docs and the live sandbox. | none (check only; this PR adds the log) |

## Candidate uses (not done yet)

- Compare our hand-written `backend/rebuttal/paypal/client.py` (Disputes, Orders v2, tracking) against the SDK's
  models and error handling, and fix any field names or enum values we got wrong.
- Use the SDK's `python-error-handling` and `python-testing` guidance for `PayPalError` and the mock sandbox.
