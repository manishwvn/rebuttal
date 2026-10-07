"""Where the workflow checkpoints live, chosen by one setting (REBUTTAL_CHECKPOINT_URL or DATABASE_URL).

- unset in mock mode, or ":memory:"  -> InMemorySaver (state resets with the mock sandbox; tests and evals)
- a file path or sqlite:///file.db    -> SqliteSaver (local development, one process)
- postgres:// or postgresql:// URL    -> PostgresSaver (Supabase or any Postgres; needs the `postgres` extra: uv sync --extra postgres)

A checkpoint holds the paused proposal, so with a durable saver an approval can arrive after a restart or redeploy.
"""

from __future__ import annotations

import fcntl
import hashlib
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from .audit import open_pool

POSTGRES_SCHEMES = ("postgres://", "postgresql://")


def make_checkpointer(target: str | None) -> BaseCheckpointSaver:
    if not target or target == ":memory:":
        return InMemorySaver()
    if target.startswith(POSTGRES_SCHEMES):
        return _postgres_saver(target)
    path = Path(target.removeprefix("sqlite:///") if target.startswith("sqlite:///") else target).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)  # SqliteSaver serialises access with its own lock
    conn.execute("PRAGMA journal_mode=WAL")  # readers do not block the writer; durable on commit
    return SqliteSaver(conn)


def _postgres_saver(url: str) -> BaseCheckpointSaver:
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except ImportError as exc:
        raise RuntimeError("Postgres checkpointing needs the 'postgres' extra: uv sync --extra postgres") from exc
    pool = open_pool(url)  # the connection settings PostgresSaver requires
    saver = PostgresSaver(pool)
    saver.setup()  # creates the checkpoint tables on first use; safe to repeat
    with pool.connection() as conn:  # Supabase exposes `public` tables over its REST API: RLS with no policy closes that
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"):
            conn.execute(f"ALTER TABLE IF EXISTS {table} ENABLE ROW LEVEL SECURITY")
    return saver


class DisputeLocks:
    """Mutual exclusion per dispute, so two approvals of one proposal cannot both run the workflow.

    This base class locks threads inside one process. For a SQLite checkpoint file or a Postgres database the
    subclasses below also lock across processes (two workers, or the old and new instance during a redeploy)."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    @contextmanager
    def hold(self, dispute_id: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(dispute_id, threading.Lock())
        with lock, self._process_lock(dispute_id):
            yield

    @contextmanager
    def _process_lock(self, dispute_id: str) -> Iterator[None]:
        yield


class FileDisputeLocks(DisputeLocks):
    """flock on one lock file per dispute, next to the SQLite checkpoint file (any process on this machine)."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _process_lock(self, dispute_id: str) -> Iterator[None]:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", dispute_id)[:80] + "-" + hashlib.sha256(dispute_id.encode()).hexdigest()[:8]
        with open(self._dir / f"{name}.lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class PostgresDisputeLocks(DisputeLocks):
    """A session-level Postgres advisory lock per dispute (any instance sharing the database). Each held lock uses
    its own short-lived connection, not the checkpointer's pool, so locks cannot starve the graph of connections.
    Exercised against a live Supabase database (session pooler) in tests/live_postgres.py."""

    def __init__(self, conninfo: str) -> None:
        super().__init__()
        self._conninfo = conninfo

    @contextmanager
    def _process_lock(self, dispute_id: str) -> Iterator[None]:
        import psycopg

        key = int.from_bytes(hashlib.sha256(dispute_id.encode()).digest()[:8], "big", signed=True)
        with psycopg.connect(self._conninfo, autocommit=True) as conn:
            conn.execute("SELECT pg_advisory_lock(%s)", (key,))
            try:
                yield
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


def make_locks(checkpointer: BaseCheckpointSaver) -> DisputeLocks:
    """The strongest lock the checkpointer allows: file locks for SQLite, advisory locks for Postgres."""
    if isinstance(checkpointer, SqliteSaver):
        with checkpointer.lock:
            files = [row[2] for row in checkpointer.conn.execute("PRAGMA database_list").fetchall() if row[2]]
        if files:
            return FileDisputeLocks(Path(files[0] + ".locks"))
    if type(checkpointer).__name__ == "PostgresSaver":
        return PostgresDisputeLocks(checkpointer.conn.conninfo)
    return DisputeLocks()
