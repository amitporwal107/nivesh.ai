"""Raw event store: one JSONL file per calendar day (of received_at, IST) per source under <home>/raw/<YYYY-MM-DD>/<source_id>.jsonl,
plus a SQLite index keyed by the content hash so an event is kept once with its first_seen_at."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..tpd_model.event_gate import IST

DDL = """
CREATE TABLE IF NOT EXISTS raw_events (
  hash TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_event_id TEXT, url TEXT, title TEXT, summary TEXT, category TEXT,
  symbol TEXT, scrip_code TEXT, entity_text TEXT, published_at TEXT, received_at TEXT NOT NULL, first_seen_at TEXT NOT NULL, day TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_raw_events_source_pub ON raw_events(source_id, published_at);
CREATE INDEX IF NOT EXISTS ix_raw_events_symbol ON raw_events(symbol);
CREATE INDEX IF NOT EXISTS ix_raw_events_day ON raw_events(day);
"""


class EventStore:
    def __init__(self, home: Path):
        self.home = Path(home); (self.home / "raw").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.home / "events.sqlite", timeout=120); self.db.executescript(DDL)   # wait for a concurrent writer

    def add(self, events: list[dict]) -> int:
        new = 0
        for e in events:
            recv = e["received_at"] if e["received_at"].tzinfo else e["received_at"].replace(tzinfo=IST)
            day = recv.astimezone(IST).date().isoformat()
            row = {**e, "published_at": e["published_at"].isoformat() if e["published_at"] else None, "received_at": recv.isoformat(),
                   "first_seen_at": recv.isoformat(), "day": day}
            cur = self.db.execute("INSERT OR IGNORE INTO raw_events (hash, source_id, source_event_id, url, title, summary, category, symbol, scrip_code, entity_text, published_at, received_at, first_seen_at, day) "
                                  "VALUES (:hash, :source_id, :source_event_id, :url, :title, :summary, :category, :symbol, :scrip_code, :entity_text, :published_at, :received_at, :first_seen_at, :day)", row)
            if cur.rowcount:
                new += 1
                d = self.home / "raw" / day; d.mkdir(parents=True, exist_ok=True)
                with open(d / f"{e['source_id']}.jsonl", "a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.db.commit()
        return new

    def query(self, since: Optional[datetime] = None, source_id: Optional[str] = None, symbol: Optional[str] = None, limit: int = 10000) -> list[dict]:
        q, args = "SELECT * FROM raw_events WHERE 1=1", []
        if since is not None:
            s = since if since.tzinfo else since.replace(tzinfo=IST); q += " AND published_at >= ?"; args.append(s.isoformat())
        if source_id: q += " AND source_id = ?"; args.append(source_id)
        if symbol: q += " AND symbol = ?"; args.append(symbol)
        q += " ORDER BY published_at DESC LIMIT ?"; args.append(limit)
        cur = self.db.execute(q, args); cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def counts(self, day: Optional[str] = None) -> dict:
        q = "SELECT source_id, count(*) FROM raw_events" + (" WHERE day = ?" if day else "") + " GROUP BY source_id"
        return dict(self.db.execute(q, (day,) if day else ()).fetchall())
