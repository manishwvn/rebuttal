"""Live check against the real online database (DATABASE_URL in backend/.env): approval flow, restart, resume.

    cd backend && uv run python tests/live_postgres.py

Not part of pytest (the suite never touches the online database). Two separate Python processes share nothing but
the database: the first analyses a dispute in the mock sandbox and exits with the proposal paused at the approval
gate; the second starts cold, finds the paused proposal in Postgres and approves it. Also checks the audit table and
the per-dispute advisory lock. Cleans up its own rows (thread ids starting with PP-LIVE-) when done. Prints no secrets.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

CHILD = """
import os, sys
os.environ["REBUTTAL_TRACING"] = "0"; os.environ["REBUTTAL_MOCK"] = "1"; os.environ["REBUTTAL_REASONER"] = "rules"
from rebuttal.runtime import Runtime
rt = Runtime(seed_cases=["agent_wrong_size"], force_rules=True)
assert rt.settings.database_url, "DATABASE_URL is not set"
"""


def child(code: str) -> str:
    out = subprocess.run([sys.executable, "-c", CHILD + code], cwd=BACKEND, capture_output=True, text=True, timeout=180)
    if out.returncode:
        sys.exit(f"child failed:\n{out.stderr[-1500:]}")
    return out.stdout.strip().splitlines()[-1]


def main() -> int:
    from rebuttal.audit import open_pool
    from rebuttal.config import load_settings

    url = load_settings().database_url
    if not url:
        print("DATABASE_URL (postgres) is not set in backend/.env")
        return 1
    pool = open_pool(url, max_size=2)

    def clean():
        with pool.connection() as c:
            for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                c.execute(f"DELETE FROM {t} WHERE thread_id LIKE 'PP-D-2000%'")
            c.execute("DELETE FROM rebuttal_audit WHERE dispute_id = 'PP-D-2000'")

    from rebuttal.audit import AuditLog
    from rebuttal.persistence import make_checkpointer

    make_checkpointer(url), AuditLog(None, url)  # creates the tables on first use
    clean()
    try:
        print("1. process one analyses the dispute and exits (proposal paused at the approval gate)")
        pid = child('print(rt.analyze("PP-D-2000").id)')
        with pool.connection() as c:
            n = c.execute("SELECT count(*) AS n FROM checkpoints WHERE thread_id = 'PP-D-2000'").fetchone()["n"]
        print(f"   proposal {pid}; {n} checkpoints stored in Postgres")
        assert n > 0

        print("2. process two starts cold, sees the pending proposal, approves it")
        result = child(f"""
pending = [p.id for p in rt.approvals.pending()]
assert {pid!r} in pending, pending
done = rt.approvals.approve({pid!r})
print(done.status, rt.mock.disputes["PP-D-2000"]["offer"]["offer_type"], len(rt.mock.write_calls()))
""")
        print("   ", result)
        assert result == "EXECUTED REFUND_WITH_RETURN 1", result

        print("3. audit log is in the database and readable from a third process")
        steps = child('print(",".join(r["step"] for r in rt.audit.for_dispute("PP-D-2000")))')
        print("   ", steps)
        assert "approve" in steps and "execute" in steps, steps

        print("4. advisory lock: a second holder waits for the first")
        import threading
        import time

        from rebuttal.persistence import PostgresDisputeLocks
        locks, order = PostgresDisputeLocks(url), []

        def holder(name, hold_s):
            with locks.hold("PP-LIVE-lock"):
                order.append(f"{name}+")
                time.sleep(hold_s)
                order.append(f"{name}-")
        a = threading.Thread(target=holder, args=("a", 1.0))
        a.start()
        time.sleep(0.3)
        b = threading.Thread(target=holder, args=("b", 0.0))
        b.start()
        a.join()
        b.join()
        print("   ", order)
        assert order == ["a+", "a-", "b+", "b-"], order

        with pool.connection() as c:
            rls = c.execute("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(%s)",
                            (["checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations", "rebuttal_audit"],)).fetchall()
        print("5. row level security on (closes the public REST API):", {r["relname"]: r["relrowsecurity"] for r in rls})
        assert all(r["relrowsecurity"] for r in rls) and len(rls) == 5
        print("\nLIVE POSTGRES CHECK PASSED")
        return 0
    finally:
        clean()
        pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
