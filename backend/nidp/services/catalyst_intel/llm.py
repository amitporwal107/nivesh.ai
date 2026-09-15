"""Optional LLM refiner for the Catalyst Intelligence Engine. The rules engine decides; this pass may refine within
bounds, on candidates only, with a validated contract. It may not invent relationships: every affected listed company it
names must resolve in the entity map or is dropped and recorded. The API key is read from a file (OPENAI_API_KEY_FILE,
default /app/docs/.OPENAI_API_KEY) and never logged. No SDK: plain HTTPS to the chat-completions endpoint.

    python -m nidp.services.catalyst_intel.llm --home <events> --names <company_names.csv> [--since ISO] [--max-events N] [--max-usd X]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time as _time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..tpd_model.event_gate import IST
from .entities import EntityMap
from .rules import classify

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "gpt-4o-mini"
PRICE_PER_1M = {"gpt-4o-mini": (0.15, 0.60)}          # USD, prompt / completion (public list price, for the cap only)
from .rules import TAXONOMY
EVENT_TYPES = tuple(TAXONOMY)
DIRECTIONS = ("positive", "negative", "mixed", "neutral"); HORIZONS = ("intraday", "days", "weeks", "months", "structural")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["event_type", "event_subtype", "direction", "materiality", "novelty", "confidence", "time_horizon", "economic_mechanism", "entities", "affected_listed", "quantities", "rationale"],
          "properties": {"event_type": {"type": "string", "enum": list(EVENT_TYPES)}, "event_subtype": {"type": "string"}, "direction": {"type": "string", "enum": list(DIRECTIONS)},
                         "materiality": {"type": "integer"}, "novelty": {"type": "integer"}, "confidence": {"type": "number"}, "time_horizon": {"type": "string", "enum": list(HORIZONS)},
                         "economic_mechanism": {"type": "string"}, "entities": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "role"], "properties": {"name": {"type": "string"}, "role": {"type": "string"}}}},
                         "affected_listed": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "why"], "properties": {"name": {"type": "string"}, "why": {"type": "string"}}}},
                         "quantities": {"type": "object", "additionalProperties": False, "required": ["order_value_cr", "penalty_cr", "revenue_impact_pct"], "properties": {"order_value_cr": {"type": ["number", "null"]}, "penalty_cr": {"type": ["number", "null"]}, "revenue_impact_pct": {"type": ["number", "null"]}}},
                         "rationale": {"type": "string"}}}
SYSTEM = ("You read one Indian capital-markets event (an exchange filing, a regulator's release, a ministry notice or a news headline) and return a structured reading. "
          "Be literal: report what the text says happened. Direction is for the affected listed companies. Materiality 0-100 is how likely this moves a stock 10% or more: "
          "results and orders scale with size relative to the company; debarments, bans, licence losses, warning letters and import alerts are 75-95; routine notices are 0-10. "
          "Name affected listed companies only when the text or plain public knowledge supports the link, and say why. Do not speculate beyond the text.")


def load_key() -> str:
    path = os.environ.get("OPENAI_API_KEY_FILE", "/app/docs/.OPENAI_API_KEY")
    with open(path) as f:
        return f.read().strip()


class _HttpClient:
    """The subset of the OpenAI client interface the refiner uses, over urllib (no SDK in the venv)."""
    def __init__(self, key: str, timeout: int = 90):
        self._key, self.timeout = key, timeout
        self.chat = type("Chat", (), {})(); self.chat.completions = self

    def create(self, **kw):
        body = json.dumps(kw).encode()
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            d = json.loads(r.read())
        msg = type("M", (), {"content": d["choices"][0]["message"]["content"]})()
        usage = type("U", (), {"prompt_tokens": d.get("usage", {}).get("prompt_tokens", 0), "completion_tokens": d.get("usage", {}).get("completion_tokens", 0)})()
        return type("R", (), {"choices": [type("C", (), {"message": msg})()], "usage": usage})()


def make_client():
    return _HttpClient(load_key())


def is_candidate(e: dict, rules: dict) -> bool:
    if rules["event_type"] == "ROUTINE":
        return False
    if rules["event_type"] == "UNCLASSIFIED":
        return bool(e.get("symbol") or e.get("scrip_code"))
    return rules["event_severity"] >= 40 or bool(rules["named_authorities"])


def _prompt(e: dict, rules: dict) -> str:
    parts = [f"SOURCE: {e['source_id']}", f"TITLE: {e.get('title')}", f"CATEGORY: {e.get('category')}", f"FILER: {e.get('entity_text') or e.get('symbol') or ''}",
             f"SUMMARY: {e.get('summary') or ''}", f"DOCUMENT (first part): {(e.get('doc_text') or '')[:6000]}",
             f"RULES READING: type={rules['event_type']}/{rules['event_subtype']} direction={rules['direction']} severity={rules['event_severity']} authorities={rules['named_authorities']}",
             f"ALLOWED TYPES: {list(TAXONOMY)}; ALLOWED SUBTYPES PER TYPE: {TAXONOMY}"]
    return "\n".join(parts)


def _validate(raw: str) -> dict:
    d = json.loads(raw)
    for k in SCHEMA["required"]:
        if k not in d:
            raise ValueError(f"contract: missing {k}")
    if d["event_type"] not in EVENT_TYPES or d["direction"] not in DIRECTIONS or d["time_horizon"] not in HORIZONS:
        raise ValueError("contract: enum")
    if not (0 <= int(d["materiality"]) <= 100 and 0 <= int(d["novelty"]) <= 100 and 0 <= float(d["confidence"]) <= 1):
        raise ValueError("contract: range")
    return d


def refine(e: dict, rules: dict, em: EntityMap, client=None, model: str = DEFAULT_MODEL, band: int = 20) -> dict:
    """Rules result plus the model's refinement, bounded; falls back to the rules result on any failure."""
    out = dict(rules); out.update(materiality_rules=rules["event_severity"], direction_rules=rules["direction"], affected_listed=[], dropped_entities=[], llm_error=None, usage=None)
    try:
        client = client or make_client()
        t0 = _time.time()
        resp = client.chat.completions.create(model=model, temperature=0, max_tokens=700,
                                              response_format={"type": "json_schema", "json_schema": {"name": "catalyst_event", "strict": True, "schema": SCHEMA}},
                                              messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(e, rules)}])
        d = _validate(resp.choices[0].message.content)
    except Exception as ex:  # noqa: BLE001 — the rules result stands
        out["llm_error"] = f"contract: {ex}" if isinstance(ex, (ValueError, KeyError, json.JSONDecodeError)) else f"{type(ex).__name__}: {str(ex)[:120]}"
        return out
    lo, hi = max(0, rules["event_severity"] - band), min(100, rules["event_severity"] + band)
    if rules["event_type"] == "UNCLASSIFIED":
        lo, hi = 0, 100
    sub = d["event_subtype"] if d["event_subtype"] in TAXONOMY.get(d["event_type"], ()) else (rules["event_subtype"] if rules["event_type"] == d["event_type"] else TAXONOMY[d["event_type"]][0])
    sev = int(min(hi, max(lo, int(d["materiality"]))))
    out.update(event_type=d["event_type"], event_subtype=sub, direction=d["direction"], materiality=sev, event_severity=sev, classification_method="RULE+LLM",
               novelty=int(d["novelty"]), confidence=round(float(d["confidence"]), 2), time_horizon=d["time_horizon"], economic_mechanism=d["economic_mechanism"],
               entities=d["entities"], quantities={**rules.get("quantities", {}), **{k: v for k, v in d["quantities"].items() if v is not None}}, rationale=d["rationale"][:500],
               classifier=f"llm:{model}", usage={"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens, "seconds": round(_time.time() - t0, 1)})
    for a in d["affected_listed"]:
        hits = em.find_in_text(a["name"])
        listed = [h for h in hits if h.get("symbol")]
        if listed:
            out["affected_listed"].append({"symbol": listed[0]["symbol"], "entity_name": listed[0]["entity_name"], "why": a["why"][:200]})
        else:
            out["dropped_entities"].append(a["name"])
    return out


class RefineCache:
    def __init__(self, home: Path):
        self.home = Path(home); self.home.mkdir(parents=True, exist_ok=True)

    def get(self, h: str) -> Optional[dict]:
        p = self.home / f"{h}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, h: str, d: dict) -> None:
        (self.home / f"{h}.json").write_text(json.dumps(d, ensure_ascii=False))


def run(home: Path, names: Path, since: Optional[str], max_events: int, max_usd: float, model: str = DEFAULT_MODEL) -> dict:
    from .catalysts import DDL, _load_events, attribute, write_rows
    db = sqlite3.connect(home / "events.sqlite", timeout=120); db.executescript(DDL)
    db.executescript("CREATE TABLE IF NOT EXISTS llm_refinements (hash TEXT PRIMARY KEY, model TEXT, event_type TEXT, event_subtype TEXT, direction TEXT, materiality INT, novelty INT, confidence REAL, time_horizon TEXT, economic_mechanism TEXT, affected_listed TEXT, dropped_entities TEXT, rationale TEXT, prompt_tokens INT, completion_tokens INT, refined_at TEXT, error TEXT);")
    em = EntityMap.from_files(names); cache = RefineCache(home / "llm"); client = make_client()
    done = {r[0] for r in db.execute("SELECT hash FROM llm_refinements")}
    stats = {"seen": 0, "candidates": 0, "refined": 0, "errors": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0, "changed_direction": 0}
    pin, pout = PRICE_PER_1M.get(model, (1.0, 3.0))
    for e in _load_events(db, since, 50000):
        stats["seen"] += 1
        if e["hash"] in done:
            continue
        p = home / "docs" / f"{e['hash']}.txt"
        e["doc_text"] = p.read_text() if p.exists() else None
        rules = classify(e)
        if not is_candidate(e, rules):
            continue
        stats["candidates"] += 1
        if stats["refined"] >= max_events or stats["usd"] >= max_usd:
            continue
        cached = cache.get(e["hash"])
        if cached:
            out = cached; stats["cached"] += 1
        else:
            out = refine(e, rules, em, client=client, model=model); cache.put(e["hash"], out)
        if out.get("llm_error"):
            stats["errors"] += 1
        else:
            stats["refined"] += 1
            u = out["usage"]; stats["prompt_tokens"] += u["prompt_tokens"]; stats["completion_tokens"] += u["completion_tokens"]
            stats["usd"] += u["prompt_tokens"] / 1e6 * pin + u["completion_tokens"] / 1e6 * pout
            if out["direction"] != out["direction_rules"]:
                stats["changed_direction"] += 1
            # the refined reading replaces the rules row for this event; impacts are rebuilt from it
            db.execute("INSERT OR REPLACE INTO normalized_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (e["hash"], out["event_type"], out["event_subtype"], out["direction"], out["materiality"], out["confidence"],
                       json.dumps(out["named_authorities"]), json.dumps(out["matched_terms"]), json.dumps(out["quantities"]), out["raw_language"], out["classifier"], datetime.now(IST).isoformat(), int(bool(e.get("doc_text")))))
            db.execute("DELETE FROM stock_events WHERE event_id = ?", (e["hash"],))
            write_rows(db, attribute(e, out, em))          # the LLM may only refine the reading; attribution stays graph-gated (its affected_listed is recorded, not scored)
        db.execute("INSERT OR REPLACE INTO llm_refinements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (e["hash"], model, out.get("event_type"), out.get("event_subtype"), out.get("direction"), out.get("materiality"), out.get("novelty"), out.get("confidence"),
                   out.get("time_horizon"), out.get("economic_mechanism"), json.dumps(out.get("affected_listed")), json.dumps(out.get("dropped_entities")), out.get("rationale"), (out.get("usage") or {}).get("prompt_tokens"), (out.get("usage") or {}).get("completion_tokens"), datetime.now(IST).isoformat(), out.get("llm_error")))
        db.commit()
    stats["usd"] = round(stats["usd"], 4)
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--home", type=Path, required=True); ap.add_argument("--names", type=Path, required=True); ap.add_argument("--since", default=None)
    ap.add_argument("--max-events", type=int, default=300); ap.add_argument("--max-usd", type=float, default=1.0); ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(a.home, a.names, a.since, a.max_events, a.max_usd, a.model), indent=1)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
