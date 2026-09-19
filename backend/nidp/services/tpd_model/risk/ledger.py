"""Append-only decision / order / fill / event ledger (PRD §16.3, §20.2). Records are canonical JSON lines; the digest
(sha256 over the lines in order) makes a run reproducible and tamper-evident. Optionally mirrored to a JSONL file,
opened in append mode only."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from typing import Optional


def _default(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o).__name__}")


class Ledger:
    def __init__(self, path: Optional[str] = None):
        self.lines: list[str] = []
        self.path = path

    def append(self, kind: str, record: dict) -> None:
        line = json.dumps({"kind": kind, **record}, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=False)
        self.lines.append(line)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def records(self, kind: Optional[str] = None) -> list[dict]:
        rows = (json.loads(x) for x in self.lines)
        return [r for r in rows if kind is None or r["kind"] == kind]

    def digest(self) -> str:
        return hashlib.sha256("\n".join(self.lines).encode()).hexdigest()
