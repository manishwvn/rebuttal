# 0010. A read-only, token-gated proxy for the Studio assistant

Status: Accepted

## Context

The AG Studio Agent Framework needs an LLM that the host app supplies, and calling Groq from the browser would expose
the key. ADR 0004 says only the `decide` node calls a model, and ADR 0001 and 0002 keep PayPal writes out of
everything but `execute`. The assistant is a second model path, so it needs its own boundary. It also shares one Groq
key, and so one per-minute budget, with the dispute agent.

## Decision

`POST /api/studio/ai` and `GET /api/studio/ai/status` live in
[`studio_ai.py`](../../backend/rebuttal/studio_ai.py), behind the same API token as the other dashboard routes.

- The module takes only the Groq key, the model name and the shared Groq budget. It imports nothing from `paypal/`,
  `approval.py`, the agent, the runtime or the app (tested), so it holds no PayPal client and cannot reach PayPal.
- It sees only what the browser sends: Studio's chat turn over the analytics data the page already holds. It makes no
  dispute decisions and writes nothing. The model, token cap and `stream` are fixed by the proxy.
- It draws from the dispute agent's process-wide Groq `TokenBudget`, and books a turn only if one dispute call's room
  is left afterwards, refusing at once instead of waiting. Per-client, service and daily request caps, and size limits,
  apply on top. A malformed request is rejected before any limit is charged.
- The key, upstream bodies and prompts are never returned or logged.

Alternatives rejected:

- Calling Groq from the browser, as the docs' example adapter does. The key would be public.
- A separate Studio limiter. It could not see the dispute agent's use, so a Studio chat could push a dispute call into
  a Groq 429.
- Routing the assistant through the agent graph. It would put a chat on the path that decides disputes.

## Consequences

- A busy Studio assistant can make itself unavailable, never the dispute agent (the reverse is expected).
- Two model paths exist, so changes to either must keep the other out of PayPal. The import test enforces it here.
- Not verified against live Groq (`docs/ag-studio.md` section 9).
