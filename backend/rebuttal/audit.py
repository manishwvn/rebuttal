"""Append-only audit trail of every agent step and every PayPal write.

Three places it can live: memory only (tests, evals), a JSON-lines file (`audit_to_file`), or the Postgres table
`rebuttal_audit` when a Postgres URL is given (DATABASE_URL), which survives restarts and redeploys on hosts with an
ephemeral disk. In Postgres mode `for_dispute` reads the table, so the history is the same from any instance."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DDL = ["""
CREATE TABLE IF NOT EXISTS rebuttal_audit (
    id bigserial PRIMARY KEY,
    ts timestamptz NOT NULL,
    dispute_id text NOT NULL,
    step text NOT NULL,
    detail jsonb NOT NULL
)""", "CREATE INDEX IF NOT EXISTS rebuttal_audit_dispute ON rebuttal_audit (dispute_id, id)",
             "ALTER TABLE rebuttal_audit ENABLE ROW LEVEL SECURITY"]  # one statement per call (no prepared multi-command)


def open_pool(url: str, max_size: int = 10):
    """A psycopg connection pool in the mode LangGraph's PostgresSaver needs (autocommit, dict rows, no prepared
    statements, which also keeps it working behind a pooler)."""
    try:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError("Postgres needs the 'postgres' extra: uv sync --extra postgres") from exc
    return ConnectionPool(conninfo=url, min_size=1, max_size=max_size, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})


def Jsonb(value):  # noqa: N802 - imported lazily so SQLite-only installs need no psycopg
    from psycopg.types.json import Jsonb as _Jsonb

    return _Jsonb(value)


class AuditLog:
    def __init__(self, path: Path | None = None, database_url: str | None = None):
        self.path = path
        self.records: list[dict] = []
        self._pool = None
        if database_url:
            self._pool = open_pool(database_url, max_size=4)
            with self._pool.connection() as conn:
                for statement in AUDIT_DDL:
                    conn.execute(statement)

    def log(self, dispute_id: str, step: str, detail: dict) -> dict:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dispute_id": dispute_id,
            "step": step,
            "detail": detail,
        }
        self.records.append(record)
        if self._pool:
            with self._pool.connection() as conn:
                conn.execute("INSERT INTO rebuttal_audit (ts, dispute_id, step, detail) VALUES (%s, %s, %s, %s)",
                             (record["ts"], dispute_id, step, Jsonb(json.loads(json.dumps(detail, default=str)))))
        if self.path:
            with self.path.open("a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        return record

    def ping(self) -> bool | None:
        """One trivial query on the database: counts as activity for a free Supabase project. None = no database."""
        if not self._pool:
            return None
        with self._pool.connection() as conn:
            conn.execute("SELECT 1")
        return True

    def for_dispute(self, dispute_id: str) -> list[dict]:
        if self._pool:
            with self._pool.connection() as conn:
                rows = conn.execute("SELECT ts, dispute_id, step, detail FROM rebuttal_audit "
                                    "WHERE dispute_id = %s ORDER BY id", (dispute_id,)).fetchall()
            return [{"ts": r["ts"].isoformat(timespec="seconds"), "dispute_id": r["dispute_id"], "step": r["step"],
                     "detail": r["detail"]} for r in rows]
        return [r for r in self.records if r["dispute_id"] == dispute_id]
