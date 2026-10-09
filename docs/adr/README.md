# Architecture decision records

Short records of the decisions that shape Rebuttal. Each Accepted record is grounded in the code it cites; a Proposed record cites code that is planned but not yet written.

| ADR | Summary |
|---|---|
| [0001](0001-single-paypal-write-path.md) | Only the graph `execute` node may write to PayPal, enforced by a transport gate, `permit_writes()` and a scanning test. |
| [0002](0002-read-only-client-for-analysis.md) | Analysis nodes hold `client.read_only()`, whose transport refuses anything but GET. |
| [0003](0003-human-approval-via-interrupt.md) | Merchant approval is a LangGraph `interrupt()`; only approve or edit reaches `execute`. |
| [0004](0004-facts-in-code-guard-over-model.md) | Facts are computed in code; the model only decides, and `guard()` rejects what the facts do not support. |
| [0005](0005-deterministic-request-id-and-audit-log.md) | Approved writes carry a deterministic `PayPal-Request-Id`; every step is audit-logged. |
| [0006](0006-supabase-postgres-free-tier.md) | Free Supabase Postgres holds checkpoints and the audit log instead of paid Postgres. |
| [0007](0007-held-out-evals.md) | Held-out eval sets, never tuned against, give the honest accuracy numbers. |
| [0008](0008-read-only-paypal-toolkit-adapter.md) | Analysis will read PayPal through a four-tool read-only adapter shaped like the PayPal Agent Toolkit, because the official package cannot be installed or made strictly read-only. |
