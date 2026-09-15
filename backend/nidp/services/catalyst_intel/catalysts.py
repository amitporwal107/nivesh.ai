"""Impacts, scores and the nine-question explanation; plus the CLI that runs the rules engine over the raw store.

    python -m nidp.services.catalyst_intel.catalysts run --home <events> --names <company_names.csv> [--since ISO] [--docs]
    python -m nidp.services.catalyst_intel.catalysts explain --home <events> --names <csv> --symbol PNCINFRA [--before ISO]
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..tpd_model.event_gate import IST
from .documents import DocumentCache, needs_document
from .entities import EntityMap
from .registry import get_source
from .rules import classify

logger = logging.getLogger(__name__)
CREDIBILITY = {"P0": 1.0, "P1": 0.9, "P2": 0.6, "P3": 0.3}
DDL = """
CREATE TABLE IF NOT EXISTS normalized_events (hash TEXT PRIMARY KEY, event_type TEXT, event_subtype TEXT, direction TEXT, materiality INT, confidence REAL,
  named_authorities TEXT, matched_terms TEXT, quantities TEXT, raw_language TEXT, classifier TEXT, classified_at TEXT, doc_used INT);
CREATE TABLE IF NOT EXISTS event_stock_impacts (hash TEXT, symbol TEXT, hops INT, exposure REAL, path TEXT, source_url TEXT, direction TEXT, impact_score INT, known_at TEXT, PRIMARY KEY (hash, symbol));
CREATE INDEX IF NOT EXISTS ix_impacts_symbol ON event_stock_impacts(symbol, known_at);
"""


def impact_score(materiality: int, exposure: Optional[float], credibility: float, novelty: int = 100) -> int:
    exp = 1.0 if exposure is None else max(0.0, min(1.0, exposure))
    exp_eff = exp if exposure is not None else 0.5          # an unsized relationship counts half, never full
    return int(round(materiality * exp_eff * (0.5 + 0.5 * novelty / 100) * credibility))


def build_impacts(e: dict, c: dict, em: EntityMap) -> list[dict]:
    """Which listed stocks an event touches: the filer itself (exact symbol / scrip), entities named in the text, and
    listed companies reached through sourced relationships."""
    cred = CREDIBILITY[get_source(e["source_id"]).priority]
    subjects = []
    ent = em.resolve_symbol(e.get("symbol"))
    if ent:
        subjects.append(ent["entity_name"])
    text = " ".join(x for x in (e.get("title"), e.get("summary"), e.get("doc_text"), e.get("entity_text")) if x)
    for h in em.find_in_text(text):
        if h["entity_name"] not in subjects:
            subjects.append(h["entity_name"])
    out, seen = [], set()
    for s in subjects:
        for imp in em.propagate(s, c["direction"], c["materiality"]):
            if imp["symbol"] in seen:
                continue
            seen.add(imp["symbol"])
            # a regulator named in a company's own filing is the authority, not a second subject: the filer keeps hops 0
            score = impact_score(c["materiality"], imp["exposure"], cred * imp["confidence"])
            out.append({**imp, "direction": c["direction"], "impact_score": score, "known_at": e["first_seen_at"].isoformat() if hasattr(e["first_seen_at"], "isoformat") else e["first_seen_at"]})
    out.sort(key=lambda i: (i["hops"], -i["impact_score"]))
    return out


def explain(e: dict, c: dict, impacts: list[dict], symbol: str) -> dict:
    src = get_source(e["source_id"])
    mine = [i for i in impacts if i["symbol"] == symbol]
    why = f"{c['event_type']}/{c['event_subtype']}: terms {', '.join(c['matched_terms'][:4])}" + (f"; authority {', '.join(c['named_authorities'])}" if c["named_authorities"] else "")
    if mine and mine[0]["hops"] > 0:
        why += f"; exposure through {mine[0]['path']}"
    return {"when_first_available": e["first_seen_at"].isoformat() if hasattr(e["first_seen_at"], "isoformat") else e["first_seen_at"],
            "published_by_source_at": e["published_at"].isoformat() if hasattr(e["published_at"], "isoformat") else e["published_at"],
            "where_found": f"{e['source_id']} ({src.name}, {src.priority}) {e['url']}",
            "what_happened": (e.get("summary") or e.get("title") or "")[:300] + (f" | document: {(e.get('doc_text') or '')[:300]}" if e.get("doc_text") else ""),
            "which_entity": e.get("entity_text") or e.get("symbol") or (impacts[0]["path"].split(" →")[0] if impacts else None),
            "which_stocks": [{"symbol": i["symbol"], "hops": i["hops"], "exposure": i["exposure"], "impact_score": i["impact_score"], "path": i["path"]} for i in impacts],
            "why": why, "direction": c["direction"], "materiality": c["materiality"], "confidence": c["confidence"], "language": c["raw_language"]}


def _load_events(db: sqlite3.Connection, since: Optional[str], limit: int, only_symbol: Optional[str] = None) -> list[dict]:
    q, args = "SELECT * FROM raw_events WHERE 1=1", []
    if since: q += " AND published_at >= ?"; args.append(since)
    if only_symbol: q += " AND (symbol = ? OR title LIKE ? OR summary LIKE ?)"; args += [only_symbol, f"%{only_symbol}%", f"%{only_symbol}%"]
    q += " ORDER BY published_at DESC LIMIT ?"; args.append(limit)
    cur = db.execute(q, args); cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def run(home: Path, names: Path, since: Optional[str], docs: bool, limit: int) -> dict:
    db = sqlite3.connect(home / "events.sqlite", timeout=120); db.executescript(DDL)
    em = EntityMap.from_files(names); dc = DocumentCache(home / "docs")
    events = _load_events(db, since, limit)
    done = {r[0] for r in db.execute("SELECT hash FROM normalized_events")}
    stats = {"seen": len(events), "classified": 0, "docs_fetched": 0, "impacts": 0, "by_type": {}}
    for e in events:
        if e["hash"] in done:
            continue
        if docs and needs_document(e):
            e["doc_text"] = dc.text(e["hash"], e["url"]); stats["docs_fetched"] += 1 if e["doc_text"] else 0
        c = classify(e)
        db.execute("INSERT OR REPLACE INTO normalized_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (e["hash"], c["event_type"], c["event_subtype"], c["direction"], c["materiality"], c["confidence"], json.dumps(c["named_authorities"]), json.dumps(c["matched_terms"]),
                    json.dumps(c["quantities"]), c["raw_language"], c["classifier"], datetime.now(IST).isoformat(), int(bool(e.get("doc_text")))))
        if c["event_type"] not in ("routine", "unclassified") or e.get("symbol"):
            for i in build_impacts(e, c, em):
                db.execute("INSERT OR REPLACE INTO event_stock_impacts VALUES (?,?,?,?,?,?,?,?,?)", (e["hash"], i["symbol"], i["hops"], i["exposure"], i["path"], i["source_url"], i["direction"], i["impact_score"], i["known_at"]))
                stats["impacts"] += 1
        stats["classified"] += 1; stats["by_type"][c["event_type"]] = stats["by_type"].get(c["event_type"], 0) + 1
        if stats["classified"] % 50 == 0:
            db.commit()                                   # short transactions: the cron chain and a manual run may overlap
    db.commit()
    return stats


def explain_symbol(home: Path, names: Path, symbol: str, before: Optional[str], docs: bool = True) -> list[dict]:
    db = sqlite3.connect(home / "events.sqlite", timeout=120); db.executescript(DDL)
    em = EntityMap.from_files(names); dc = DocumentCache(home / "docs")
    out = []
    for e in _load_events(db, None, 2000, only_symbol=None):
        if before and e["published_at"] and e["published_at"] > before:
            continue
        if docs and needs_document(e) and (e.get("symbol") == symbol):
            e["doc_text"] = dc.text(e["hash"], e["url"])
        elif docs and needs_document(e):
            p = home / "docs" / f"{e['hash']}.txt"
            e["doc_text"] = p.read_text() if p.exists() else None
        c = classify(e)
        if c["event_type"] in ("routine",):
            continue
        imps = build_impacts(e, c, em)
        if any(i["symbol"] == symbol for i in imps):
            out.append({"event": {k: e[k] for k in ("source_id", "published_at", "first_seen_at", "title", "url")}, "explanation": explain(e, c, imps, symbol)})
    out.sort(key=lambda x: -max(i["impact_score"] for i in x["explanation"]["which_stocks"] if i["symbol"] == symbol))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "explain"):
        p = sub.add_parser(name); p.add_argument("--home", type=Path, required=True); p.add_argument("--names", type=Path, required=True)
        if name == "run":
            p.add_argument("--since", default=None); p.add_argument("--docs", action="store_true"); p.add_argument("--limit", type=int, default=50000)
        else:
            p.add_argument("--symbol", required=True); p.add_argument("--before", default=None); p.add_argument("--top", type=int, default=3)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.cmd == "run":
        print(json.dumps(run(a.home, a.names, a.since, a.docs, a.limit), indent=1)); return 0
    for x in explain_symbol(a.home, a.names, a.symbol, a.before)[: a.top]:
        print(json.dumps(x, indent=1, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
