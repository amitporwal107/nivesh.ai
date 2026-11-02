"""Raw cache of TrueData corporate answers: one gzipped JSON file per day list or statement, never fetched twice.

Layout (the same as the supervised 2 Nov fetch, so that cache can seed this one by a plain copy):
    <root>/lists/YYYY-MM-DD.json.gz     {"status": "Success", "Records": [...]}
    <root>/al/<filing id>.json.gz       balance sheet              (getResultALById)
    <root>/cf/<filing id>.json.gz       cash flow, cumulative      (getCashFlowDetailById)
    <root>/pl/<filing id>.json.gz       P&L, cumulative            (getPnLById cumulative=true; FY unit anchor)
    <root>/plq/<filing id>.json.gz      P&L, the quarter alone     (getPnLById cumulative=false; finance costs)

A statement TrueData answered "no such statement" for is stored as {"_truedata_empty": "<code>: <message>"}, so it is
not asked for again. Files written by the supervised fetch that hold TrueData's JSON failure answer
({"status": "There is no row at position 0.", ...}) read back as the same empty marker.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from nidp.shared.sources.truedata import classify_json_status

from .transform import EMPTY_KEY

KINDS = ("lists", "al", "cf", "pl", "plq")


class RawCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, kind: str, key: Any) -> Path:
        if kind not in KINDS:
            raise ValueError(f"unknown cache kind {kind!r}")
        name = key.isoformat() if isinstance(key, date) else str(int(key))
        return self.root / kind / f"{name}.json.gz"

    def has(self, kind: str, key: Any) -> bool:
        return self.path(kind, key).exists()

    def read(self, kind: str, key: Any) -> Optional[Dict[str, Any]]:
        """The stored answer; None when absent or unreadable (so it is fetched again)."""
        p = self.path(kind, key)
        try:
            payload = json.loads(gzip.decompress(p.read_bytes()))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, EOFError):
            return None
        if not isinstance(payload, dict):
            return None
        if kind != "lists":
            failure = classify_json_status(payload)
            if failure:
                return {EMPTY_KEY: f"{failure[0]}: {failure[1]}"}
        return payload

    def write(self, kind: str, key: Any, payload: Dict[str, Any]) -> None:
        p = self.path(kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".part{os.getpid()}")
        tmp.write_bytes(gzip.compress(json.dumps(payload, separators=(",", ":")).encode()))
        os.replace(tmp, p)

    def write_empty(self, kind: str, key: Any, code: str, message: str) -> None:
        self.write(kind, key, {EMPTY_KEY: f"{code}: {message}"[:300]})

    def list_days(self) -> List[date]:
        d = self.root / "lists"
        out = []
        for p in d.glob("*.json.gz") if d.exists() else []:
            try:
                out.append(date.fromisoformat(p.name[:10]))
            except ValueError:
                continue
        return sorted(out)

    def list_records(self, days: Optional[List[date]] = None) -> List[Dict[str, Any]]:
        recs: List[Dict[str, Any]] = []
        for day in (days if days is not None else self.list_days()):
            payload = self.read("lists", day) or {}
            records = payload.get("Records")
            if isinstance(records, list):
                recs.extend(r for r in records if isinstance(r, dict))
        return recs
