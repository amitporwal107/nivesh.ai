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


def board(home: Path, known_before: str, since: str, min_score: int = 20, universe: Optional[set] = None, limit: int = 200) -> list[dict]:
    """Stocks exposed to non-routine events published since `since` and known (first_seen_at) at or before `known_before`,
    one row per stock: the best impact, its direction, the event behind it and how many events touch the stock."""
    db = sqlite3.connect(home / "events.sqlite", timeout=120)
    q = """SELECT i.symbol, i.hops, i.exposure, i.path, i.direction, i.impact_score, i.known_at, n.event_type, n.event_subtype, n.materiality, n.confidence, n.classifier,
                  r.title, r.source_id, r.url, r.published_at, r.hash
           FROM event_stock_impacts i JOIN normalized_events n ON n.hash = i.hash JOIN raw_events r ON r.hash = i.hash
           WHERE i.known_at <= ? AND r.published_at >= ? AND n.event_type NOT IN ('routine') AND i.impact_score >= ?
           ORDER BY i.symbol, i.impact_score DESC, i.known_at DESC"""
    rows = db.execute(q, (known_before, since, min_score)).fetchall(); db.close()
    out, cur = [], None
    for sym, hops, exp, path, direction, score, known_at, etype, sub, mat, conf, clf, title, src, url, pub, h in rows:
        if cur is None or cur["symbol"] != sym:
            cur = {"symbol": sym, "in_universe": (sym in universe) if universe is not None else None, "best_score": int(score), "direction": direction, "hops": int(hops), "exposure": exp,
                   "n_events": 0, "event_types": [], "top_event": {"hash": h, "title": title, "source_id": src, "url": url, "published_at": pub, "known_at": known_at, "event_type": etype,
                                                                   "event_subtype": sub, "materiality": mat, "confidence": conf, "classifier": clf, "path": path}}
            out.append(cur)
        cur["n_events"] += 1
        if etype not in cur["event_types"]:
            cur["event_types"].append(etype)
    out.sort(key=lambda r: (-r["best_score"], r["symbol"]))
    return out[:limit]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "explain", "board"):
        p = sub.add_parser(name); p.add_argument("--home", type=Path, required=True); p.add_argument("--names", type=Path, required=False)
        if name == "run":
            p.add_argument("--since", default=None); p.add_argument("--docs", action="store_true"); p.add_argument("--limit", type=int, default=50000)
        elif name == "explain":
            p.add_argument("--symbol", required=True); p.add_argument("--before", default=None); p.add_argument("--top", type=int, default=3)
        else:
            p.add_argument("--known-before", required=True); p.add_argument("--since", required=True); p.add_argument("--min-score", type=int, default=20)
            p.add_argument("--universe-csv", type=Path, default=None, help="a predictions csv whose symbol column is the universe"); p.add_argument("--out", type=Path, default=None); p.add_argument("--top", type=int, default=60)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.cmd == "run":
        print(json.dumps(run(a.home, a.names, a.since, a.docs, a.limit), indent=1)); return 0
    if a.cmd == "board":
        uni = None
        if a.universe_csv:
            import csv
            uni = {r["symbol"] for r in csv.DictReader(open(a.universe_csv))}
        b = board(a.home, a.known_before, a.since, a.min_score, uni)
        if a.out:
            a.out.write_text(json.dumps(b, indent=1, ensure_ascii=False))
        print(f"{'symbol':12s} {'uni':3s} {'score':>5s} {'dir':8s} {'hops':>4s} {'n':>3s} {'type/subtype':30s} {'known_at':25s} {'source':22s} title")
        for r in b[: a.top]:
            t = r["top_event"]
            print(f"{r['symbol']:12s} {('yes' if r['in_universe'] else ('no' if r['in_universe'] is False else '-')):3s} {r['best_score']:5d} {r['direction']:8s} {r['hops']:4d} {r['n_events']:3d} {(t['event_type'] + '/' + str(t['event_subtype']))[:30]:30s} {t['known_at'][:19]:25s} {t['source_id'][:22]:22s} {t['title'][:70]}")
        return 0
    for x in explain_symbol(a.home, a.names, a.symbol, a.before)[: a.top]:
        print(json.dumps(x, indent=1, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
