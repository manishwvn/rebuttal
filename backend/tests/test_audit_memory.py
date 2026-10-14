"""AuditLog keeps its in-memory list only when there is no database to read from."""

from contextlib import contextmanager

from rebuttal.audit import AuditLog


class _Conn:
    def execute(self, *args, **kwargs):
        return None


class _FakePool:
    @contextmanager
    def connection(self):
        yield _Conn()


def test_records_grow_without_a_pool():
    audit = AuditLog()
    audit.log("D1", "gather", {})
    assert len(audit.records) == 1 and len(audit.for_dispute("D1")) == 1


def test_records_stay_empty_with_a_pool(monkeypatch):
    monkeypatch.setattr("rebuttal.audit.Jsonb", lambda value: value)  # psycopg is an optional extra
    audit = AuditLog()
    audit._pool = _FakePool()
    audit.log("D1", "gather", {})
    assert audit.records == []
