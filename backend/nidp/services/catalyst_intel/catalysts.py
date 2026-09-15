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
GATE = {"exact_nse_issuer": 100, "exact_bse_issuer": 100, "exact_isin": 100, "exact_entity": 100, "verified_subsidiary": 95, "verified_parent": 95, "verified_investee": 90, "verified_promoter": 90,
        "named_in_title": 90, "associate_jv": 85, "project_contractor": 85, "named_in_summary": 80, "supplier_customer": 60, "sector_inference": 30, "keyword_similarity": 0}
GATE_MIN = 80
ROW_COLUMNS = ("symbol", "event_id", "event_time", "known_at", "source", "source_url", "source_entity", "affected_entity", "listed_entity", "entity_match_type", "entity_match_score", "hops",
               "event_type", "event_subtype", "direction", "event_severity", "business_materiality", "exposure_score", "confidence", "catalyst_score", "title", "classification_method", "path")


def gate(match_type: str) -> int:
    return GATE.get(match_type, 0)


def catalyst_score(event_severity: int, entity_match_score: int, exposure_score: int, confidence: float) -> int:
    """severity × match × exposure × confidence, 0 below the entity gate. Direct issuer: exposure 100."""
    if entity_match_score < GATE_MIN:
        return 0
    return int(round(event_severity * (entity_match_score / 100) * (exposure_score / 100) * min(1.0, max(0.0, confidence)) / 0.9))
DDL = """
CREATE TABLE IF NOT EXISTS normalized_events (hash TEXT PRIMARY KEY, event_type TEXT, event_subtype TEXT, direction TEXT, materiality INT, confidence REAL,
  named_authorities TEXT, matched_terms TEXT, quantities TEXT, raw_language TEXT, classifier TEXT, classified_at TEXT, doc_used INT);
CREATE TABLE IF NOT EXISTS event_stock_impacts (hash TEXT, symbol TEXT, hops INT, exposure REAL, path TEXT, source_url TEXT, direction TEXT, impact_score INT, known_at TEXT, PRIMARY KEY (hash, symbol));
CREATE INDEX IF NOT EXISTS ix_impacts_symbol ON event_stock_impacts(symbol, known_at);
CREATE TABLE IF NOT EXISTS stock_events (symbol TEXT, event_id TEXT, event_time TEXT, known_at TEXT, source TEXT, source_url TEXT, source_entity TEXT, affected_entity TEXT, listed_entity TEXT,
  entity_match_type TEXT, entity_match_score INT, hops INT, event_type TEXT, event_subtype TEXT, direction TEXT, event_severity INT, business_materiality INT, exposure_score INT, confidence REAL,
  catalyst_score INT, title TEXT, classification_method TEXT, path TEXT, PRIMARY KEY (symbol, event_id));
CREATE INDEX IF NOT EXISTS ix_stock_events_symbol ON stock_events(symbol, known_at);
CREATE INDEX IF NOT EXISTS ix_stock_events_known ON stock_events(known_at);
"""


def write_rows(db, rows: list[dict]) -> None:
    for r in rows:
        db.execute("INSERT OR REPLACE INTO stock_events VALUES (" + ",".join("?" * len(ROW_COLUMNS)) + ")", tuple(r.get(k) for k in ROW_COLUMNS))


def impact_score(materiality: int, exposure: Optional[float], credibility: float, novelty: int = 100) -> int:
    exp = 1.0 if exposure is None else max(0.0, min(1.0, exposure))
    exp_eff = exp if exposure is not None else 0.5          # an unsized relationship counts half, never full
    return int(round(materiality * exp_eff * (0.5 + 0.5 * novelty / 100) * credibility))


def _exposure_score(imp: dict) -> int:
    if imp["hops"] == 0:
        return 100
    if imp.get("exposure") is None:
        return 50                                        # verified but unsized relationship counts half
    return int(round(min(100, 30 + 70 * min(1.0, float(imp["exposure"]) / 0.25))))   # a 25% stake is full exposure; 2.53% -> ~37


def attribute(e: dict, c: dict, em: EntityMap) -> list[dict]:
    """Issuer first (hops 0, match 100); a listed company named in the TITLE of a regulator / institution / news item (90) or
    in its SUMMARY (80); then only stocks reached through sourced graph edges from those subjects. Document text never
    attributes. Rows below the entity gate are not created."""
    src = get_source(e["source_id"]); cred = CREDIBILITY[src.priority]
    known_at = e["first_seen_at"].isoformat() if hasattr(e["first_seen_at"], "isoformat") else e["first_seen_at"]
    event_time = e["published_at"].isoformat() if hasattr(e["published_at"], "isoformat") else e["published_at"]
    authority = c["named_authorities"][0] if c.get("named_authorities") else None
    from .entities import AUTHORITY_ALIASES
    authority_name = next((n for n, al in AUTHORITY_ALIASES.items() if authority and authority.lower() in [a.lower() for a in al] + [n.lower()]), authority)
    subjects: list[tuple[str, str, Optional[dict]]] = []          # (entity_name, match_type, entity)
    issuer = em.resolve_issuer(e)
    if issuer:
        subjects.append((issuer[0]["entity_name"], issuer[1], issuer[0]))
    else:
        for h in em.find_in_text(e.get("title") or ""):
            if h.get("entity_type") in ("listed_company", "group_holding", "unlisted_company"):
                subjects.append((h["entity_name"], "named_in_title", h))
        for h in em.find_in_text(e.get("summary") or ""):
            if h.get("entity_type") in ("listed_company", "group_holding", "unlisted_company") and all(h["entity_name"] != s_[0] for s_ in subjects):
                subjects.append((h["entity_name"], "named_in_summary", h))
    source_entity = authority_name or (src.name if src.klass in ("regulator", "government", "global", "ratings") else (subjects[0][0] if subjects else src.name))
    rows, seen = [], set()
    for name, mtype, ent in subjects:
        for imp in em.propagate(name, include_self=True):
            if imp["symbol"] in seen:
                continue
            m_type = mtype if imp["hops"] == 0 else imp["match_type"]
            m_score = gate(m_type)
            if imp["hops"] > 0 and imp["confidence"] < 0.7:
                m_score = int(round(m_score * imp["confidence"]))     # a weakly sourced edge is discounted; a sourced one (>= 0.7) keeps its gate score
            if m_score < GATE_MIN:
                continue
            seen.add(imp["symbol"])
            exposure = _exposure_score(imp); conf = round(c["confidence"] * cred, 2)
            listed = em.resolve_symbol(imp["symbol"]); listed_name = listed["entity_name"] if listed else imp["symbol"]
            rows.append({"symbol": imp["symbol"], "event_id": e["hash"], "event_time": event_time, "known_at": known_at, "source": e["source_id"], "source_url": e.get("url"),
                         "source_entity": source_entity, "affected_entity": name, "listed_entity": listed_name, "entity_match_type": m_type, "entity_match_score": m_score, "hops": imp["hops"],
                         "event_type": c["event_type"], "event_subtype": c["event_subtype"], "direction": c["direction"], "event_severity": c["event_severity"],
                         "business_materiality": int(round(c["event_severity"] * exposure / 100)), "exposure_score": exposure, "confidence": conf,
                         "catalyst_score": catalyst_score(c["event_severity"], m_score, exposure, conf), "title": e.get("title"), "classification_method": c.get("classification_method", "RULE"),
                         "path": imp["path"] if imp["hops"] else name})
    rows.sort(key=lambda r: (r["hops"], -r["catalyst_score"]))
    return rows


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
    if mine:
        why += f"; match {mine[0]['entity_match_type']} {mine[0]['entity_match_score']}"
    return {"when_first_available": e["first_seen_at"].isoformat() if hasattr(e["first_seen_at"], "isoformat") else e["first_seen_at"],
            "published_by_source_at": e["published_at"].isoformat() if hasattr(e["published_at"], "isoformat") else e["published_at"],
            "where_found": f"{e['source_id']} ({src.name}, {src.priority}) {e['url']}",
            "what_happened": (e.get("summary") or e.get("title") or "")[:300] + (f" | document: {(e.get('doc_text') or '')[:300]}" if e.get("doc_text") else ""),
            "which_entity": e.get("entity_text") or e.get("symbol") or (impacts[0]["path"].split(" →")[0] if impacts else None),
            "which_stocks": [{"symbol": i["symbol"], "hops": i["hops"], "exposure_score": i["exposure_score"], "entity_match_type": i["entity_match_type"], "entity_match_score": i["entity_match_score"],
                              "catalyst_score": i["catalyst_score"], "path": i["path"]} for i in impacts],
            "why": why, "direction": c["direction"], "materiality": c["event_severity"], "event_severity": c["event_severity"], "confidence": c["confidence"], "language": c["raw_language"],
            "classification_method": c.get("classification_method", "RULE")}


def _load_events(db: sqlite3.Connection, since: Optional[str], limit: int, only_symbol: Optional[str] = None) -> list[dict]:
    q, args = "SELECT * FROM raw_events WHERE 1=1", []
    if since: q += " AND published_at >= ?"; args.append(since)
    if only_symbol: q += " AND (symbol = ? OR title LIKE ? OR summary LIKE ?)"; args += [only_symbol, f"%{only_symbol}%", f"%{only_symbol}%"]
    q += " ORDER BY published_at DESC LIMIT ?"; args.append(limit)
    cur = db.execute(q, args); cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def run(home: Path, names: Path, since: Optional[str], docs: bool, limit: int, reclassify: bool = False) -> dict:
    db = sqlite3.connect(home / "events.sqlite", timeout=120); db.executescript(DDL)
    em = EntityMap.from_files(names); dc = DocumentCache(home / "docs")
    events = _load_events(db, since, limit)
    if reclassify:                                       # the rules changed: drop this window's readings and impacts, keep documents and LLM cache
        hashes = [e["hash"] for e in events]
        for k in range(0, len(hashes), 500):
            chunk = hashes[k:k + 500]; qm = ",".join("?" * len(chunk))
            db.execute(f"DELETE FROM normalized_events WHERE hash IN ({qm})", chunk); db.execute(f"DELETE FROM event_stock_impacts WHERE hash IN ({qm})", chunk); db.execute(f"DELETE FROM stock_events WHERE event_id IN ({qm})", chunk)
        db.commit()
    done = {r[0] for r in db.execute("SELECT hash FROM normalized_events")}
    stats = {"seen": len(events), "classified": 0, "docs_fetched": 0, "impacts": 0, "by_type": {}}
    for e in events:
        if e["hash"] in done:
            continue
        if docs and needs_document(e):
            e["doc_text"] = dc.text(e["hash"], e["url"]); stats["docs_fetched"] += 1 if e["doc_text"] else 0
        c = classify(e)
        db.execute("INSERT OR REPLACE INTO normalized_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (e["hash"], c["event_type"], c["event_subtype"], c["direction"], c["event_severity"], c["confidence"], json.dumps(c["named_authorities"]), json.dumps(c["matched_terms"]),
                    json.dumps(c["quantities"]), c["raw_language"], c["classifier"], datetime.now(IST).isoformat(), int(bool(e.get("doc_text")))))
        if c["event_type"] not in ("ROUTINE",):
            rows_ = attribute(e, c, em); write_rows(db, rows_); stats["impacts"] += len(rows_)
        stats["classified"] += 1; stats["by_type"][c["event_type"]] = stats["by_type"].get(c["event_type"], 0) + 1
        if stats["classified"] % 50 == 0:
            db.commit()                                   # short transactions: the cron chain and a manual run may overlap
    db.commit()
    return stats


def explain_symbol(home: Path, names: Path, symbol: str, before: Optional[str], docs: bool = True) -> list[dict]:
    db = sqlite3.connect(home / "events.sqlite", timeout=120); db.executescript(DDL)
    em = EntityMap.from_files(names); dc = DocumentCache(home / "docs")
    out = []
    q = """SELECT DISTINCT r.* FROM raw_events r LEFT JOIN stock_events i ON i.event_id = r.hash
           WHERE (r.symbol = ? OR i.symbol = ?) ORDER BY r.published_at DESC LIMIT 500"""
    cur = db.execute(q, (symbol, symbol)); cols = [c[0] for c in cur.description]
    for e in [dict(zip(cols, r)) for r in cur.fetchall()]:
        if before and e["published_at"] and e["published_at"] > before:
            continue
        if docs and needs_document(e) and (e.get("symbol") == symbol):
            e["doc_text"] = dc.text(e["hash"], e["url"])
        elif docs and needs_document(e):
            p = home / "docs" / f"{e['hash']}.txt"
            e["doc_text"] = p.read_text() if p.exists() else None
        c = classify(e)
        if c["event_type"] in ("ROUTINE",):
            continue
        rows_ = attribute(e, c, em)
        if any(r["symbol"] == symbol for r in rows_):
            out.append({"event": {k: e[k] for k in ("source_id", "published_at", "first_seen_at", "title", "url")}, "explanation": explain(e, c, rows_, symbol)})
    out.sort(key=lambda x: -max(i["catalyst_score"] for i in x["explanation"]["which_stocks"] if i["symbol"] == symbol))
    return out


def board(home: Path, known_before: str, since: str, min_score: int = 20, universe: Optional[set] = None, limit: int = 200) -> list[dict]:
    """Stocks exposed to non-routine events published since `since` and known (first_seen_at) at or before `known_before`,
    one row per stock: the best impact, its direction, the event behind it and how many events touch the stock."""
    db = sqlite3.connect(home / "events.sqlite", timeout=120)
    q = "SELECT " + ", ".join(ROW_COLUMNS) + """ FROM stock_events WHERE known_at <= ? AND event_time >= ? AND event_type NOT IN ('ROUTINE') AND catalyst_score >= ?
           ORDER BY symbol, catalyst_score DESC, known_at DESC"""
    rows = [dict(zip(ROW_COLUMNS, r)) for r in db.execute(q, (known_before, since, min_score)).fetchall()]; db.close()
    out, cur = [], None
    for r in rows:
        if cur is None or cur["symbol"] != r["symbol"]:
            cur = {**r, "in_universe": (r["symbol"] in universe) if universe is not None else None, "n_events": 0, "event_types": []}
            out.append(cur)
        cur["n_events"] += 1
        if r["event_type"] not in cur["event_types"]:
            cur["event_types"].append(r["event_type"])
    out.sort(key=lambda r: (-r["catalyst_score"], r["symbol"]))
    return out[:limit]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "explain", "board"):
        p = sub.add_parser(name); p.add_argument("--home", type=Path, required=True); p.add_argument("--names", type=Path, required=False)
        if name == "run":
            p.add_argument("--since", default=None); p.add_argument("--docs", action="store_true"); p.add_argument("--limit", type=int, default=50000); p.add_argument("--reclassify", action="store_true")
        elif name == "explain":
            p.add_argument("--symbol", required=True); p.add_argument("--before", default=None); p.add_argument("--top", type=int, default=3)
        else:
            p.add_argument("--known-before", required=True); p.add_argument("--since", required=True); p.add_argument("--min-score", type=int, default=20)
            p.add_argument("--universe-csv", type=Path, default=None, help="a predictions csv whose symbol column is the universe"); p.add_argument("--out", type=Path, default=None); p.add_argument("--top", type=int, default=60)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.cmd == "run":
        print(json.dumps(run(a.home, a.names, a.since, a.docs, a.limit, a.reclassify), indent=1)); return 0
    if a.cmd == "board":
        uni = None
        if a.universe_csv:
            import csv
            uni = {r["symbol"] for r in csv.DictReader(open(a.universe_csv))}
        b = board(a.home, a.known_before, a.since, a.min_score, uni)
        if a.out:
            a.out.write_text(json.dumps(b, indent=1, ensure_ascii=False))
        print(f"{'symbol':11s} {'uni':3s} {'cat':>3s} {'sev':>3s} {'exp':>3s} {'match':>5s} {'hop':>3s} {'dir':8s} {'meth':8s} {'type/subtype':26s} {'source_entity':22s} {'affected_entity':26s} {'known_at':16s} {'source':21s} title")
        for r in b[: a.top]:
            print(f"{r['symbol']:11s} {('yes' if r['in_universe'] else ('no' if r['in_universe'] is False else '-')):3s} {r['catalyst_score']:3d} {r['event_severity']:3d} {r['exposure_score']:3d} {r['entity_match_score']:5d} {r['hops']:3d} {r['direction']:8s} {r['classification_method']:8s} "
                  f"{(r['event_type'] + '/' + str(r['event_subtype']))[:26]:26s} {str(r['source_entity'])[:22]:22s} {str(r['affected_entity'])[:26]:26s} {r['known_at'][:16]:16s} {r['source'][:21]:21s} {str(r['title'])[:60]}")
        return 0
    for x in explain_symbol(a.home, a.names, a.symbol, a.before)[: a.top]:
        print(json.dumps(x, indent=1, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
