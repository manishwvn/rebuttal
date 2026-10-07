"""Append-only audit trail of every agent step and every PayPal write."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: list[dict] = []

    def log(self, dispute_id: str, step: str, detail: dict) -> dict:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dispute_id": dispute_id,
            "step": step,
            "detail": detail,
        }
        self.records.append(record)
        if self.path:
            with self.path.open("a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
        return record

    def for_dispute(self, dispute_id: str) -> list[dict]:
        return [r for r in self.records if r["dispute_id"] == dispute_id]
