# 0006. Free Supabase Postgres for checkpoints and audit

Status: Accepted

## Context

The backend runs on a Render free web service, whose filesystem is lost on each redeploy, so a SQLite checkpoint file
would drop proposals waiting for approval. Render's own Postgres was a paid line item; the hackathon project has no
budget for it.

## Decision

Use a free Supabase Postgres project for both the LangGraph checkpoints and the `rebuttal_audit` table, switched on
by a `postgresql://` `DATABASE_URL` ([`persistence.py`](../../backend/rebuttal/persistence.py),
[`audit.py`](../../backend/rebuttal/audit.py)). Without it the app uses SQLite, or memory in mock mode, so anyone can
run it with no setup. The decision and its limits are written up in [PLAN.md](../../PLAN.md) ("Persistence:
Supabase").

- Session pooler, port 5432: the checkpointer and per-dispute advisory locks (`PostgresDisputeLocks`) hold session
  state.
- Row level security is enabled with no policy on each table so Supabase's public REST API cannot read them.
- Free projects pause after low activity; `/api/health` runs `SELECT 1` (`AuditLog.ping`) and a scheduled GitHub
  workflow pings daily.

## Consequences

- $0 persistence, at the cost of pausing risk and the free-plan size limits.
- Moving to another Postgres is a change of `DATABASE_URL` only.
