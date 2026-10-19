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


def test_file_mode_skips_garbage_partial_and_non_object_lines(tmp_path):
    import json

    path = tmp_path / "audit.jsonl"
    good = lambda step: json.dumps({"ts": "t", "dispute_id": "D1", "step": step, "detail": {}})  # noqa: E731
    path.write_bytes((good("a") + "\nnot json\n[]\n123\n" + good("b")[:20] + "\n\xff\xfe\n" + good("c") + "\n").encode("latin-1"))
    assert [r["step"] for r in AuditLog(path=path).for_dispute("D1")] == ["a", "c"]


def test_file_mode_without_a_file_yet_uses_memory(tmp_path):
    audit = AuditLog(path=tmp_path / "missing.jsonl")
    audit.records.append({"ts": "t", "dispute_id": "D1", "step": "x", "detail": {}})
    assert [r["step"] for r in audit.for_dispute("D1")] == ["x"]
