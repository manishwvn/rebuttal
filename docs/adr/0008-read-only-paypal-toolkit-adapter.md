# 0008. A read-only adapter shaped like the PayPal Agent Toolkit

Status: Proposed

## Context

PayPal promotes its Agent Toolkit for the hackathon. We wanted the agent's read-only lookups (show dispute, list
transactions) to use that tool format, behind the ADR 0002 boundary. We read PyPI `paypal-agent-toolkit` 1.11.0 and
found four problems:

- It pins `langchain==0.3.23` (also `openai-agents==0.0.2`, `crewai-tools==0.13.2`). That cannot resolve with our
  `langchain>=1.4.3` (uv: no solution).
- `PayPalAPI.run(method, params)` dispatches any tool by name without checking the configured actions, so write tools
  (`accept_dispute_claim`, `create_order`, `pay_order`) stay callable.
- It uses `requests` directly, so our `ReadOnlyTransport` and the httpx mock do not apply.
- `list_transactions` omits `fields=all`, so `payer_info` (used by the duplicate-charge fact) is not returned.

## Decision

[`agent/toolkit.py`](../../backend/rebuttal/agent/toolkit.py) will define `READ_TOOLS`: exactly four read tools in the
toolkit's tool-dict shape (method, name, description, args_schema, actions, execute): `get_dispute`,
`list_transactions`, `get_order_trackers`, `get_capture_order_id`. `ReadOnlyToolkit(client)` will store
`client.read_only()` even if it is given the full client. It will validate parameters with pydantic (`extra=forbid`, id
pattern), offer `call` and `run` (JSON string, like the toolkit), and raise `ToolNotAvailable` for any other name.
`gather` in [`agent/facts.py`](../../backend/rebuttal/agent/facts.py) will read PayPal only through it once it is wired.
Until then it calls the client directly (`facts.py` lines 105-131).

## Consequences

- No write tool will exist in the registry. The module may reference only `read_only()` and the four read methods; an
  AST test in `backend/tests/test_toolkit.py` will check this.
- The package-wide scan in `test_write_boundary.py` will also cover the file, because it is outside `paypal/` and is not
  `approval.py`.
- `execute` remains the only writer (ADR 0001).
- A later swap to the official package needs its langchain pin lifted, and its `run` limited to our four names, with its
  `requests` traffic going through our read-only transport. Neither safety condition holds in 1.11.0.
- Cost: a small module to maintain, and a Rebuttal-specific pair of tools the official toolkit does not have.
