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
| | | | |

## Candidate uses (not done yet)

- Compare our hand-written `backend/rebuttal/paypal/client.py` (Disputes, Orders v2, tracking) against the SDK's
  models and error handling, and fix any field names or enum values we got wrong.
- Use the SDK's `python-error-handling` and `python-testing` guidance for `PayPalError` and the mock sandbox.
