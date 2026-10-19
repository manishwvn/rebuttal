"""AuditLog keeps its in-memory list only when there is no database to read from."""

from contextlib import contextmanager

from rebuttal.audit import AuditLog


class _Conn:
    def __init__(self, calls: list):
        self.calls = calls

    def execute(self, sql, params=None):
        self.calls.append(sql)


class _FakePool:
    def __init__(self):
        self.calls: list[str] = []

    @contextmanager
    def connection(self):
        yield _Conn(self.calls)


def test_records_grow_without_a_pool():
    audit = AuditLog()
    audit.log("D1", "gather", {})
    assert len(audit.records) == 1 and len(audit.for_dispute("D1")) == 1


def test_records_stay_empty_with_a_pool(monkeypatch):
    monkeypatch.setattr("rebuttal.audit.Jsonb", lambda value: value)  # psycopg is an optional extra
    audit = AuditLog()
    audit._pool = pool = _FakePool()
    audit.log("D1", "gather", {})
    assert audit.records == []
    assert len(pool.calls) == 1 and pool.calls[0].startswith("INSERT INTO rebuttal_audit")


def test_file_mode_reads_records_from_an_earlier_process(tmp_path):
    path = tmp_path / "audit.jsonl"
    first = AuditLog(path=path)
    first.log("D1", "approve", {"decision": "approve"})
    first.log("D2", "gather", {})
    fresh = AuditLog(path=path)  # a restart: empty memory, same file
    fresh.log("D1", "execute", {})
    assert [r["step"] for r in fresh.for_dispute("D1")] == ["approve", "execute"]  # no duplicates
    assert [r["step"] for r in fresh.for_dispute("D2")] == ["gather"]
    assert [r["step"] for r in first.for_dispute("D1")] == ["approve", "execute"]
