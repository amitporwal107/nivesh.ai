"""The `visual-answer-v1` payload: formats, per-source freshness, assembly, the contract check and the facts block.

Contract: docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md. The frontend parses it with
frontend-v5/src/components/chat/visual/schema.ts; `validate` mirrors that schema's required parts so a payload the
renderer would drop is caught here first (tests/test_copilot_visual.py and the staging capture).

Nothing here makes a number: it formats, dates and labels the numbers the builders read.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = "visual-answer-v1"
IST = timezone(timedelta(hours=5, minutes=30))
MINUS = "−"
TONES = ("up", "down", "neutral", "warn")
DECISION_LABELS = {"setup_ready": "Setup ready", "wait": "Wait", "avoid": "Avoid", "no_setup": "No setup yet",
                   "info": "For information"}
CAVEAT_TAIL = "Ideas to review, not recommendations; nothing is sent to a broker."
LEVEL_KINDS = ("support", "resistance", "entry", "stop", "target", "wall_call", "wall_put", "max_pain")
RANKED_FORMATS = ("price", "pct", "x", "int", "text")


# ── numbers and formats ──────────────────────────────────────────────────────

def num(v: Any) -> Optional[float]:
    """A finite float, or None. Never a guess: a missing or unreadable figure stays None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def r2(v: Any) -> Optional[float]:
    f = num(v)
    return None if f is None else round(f, 2)


def _signed(f: float, body: str) -> str:
    return (MINUS if f < 0 else "+") + body


def price(v: Any) -> Optional[str]:
    f = num(v)
    return None if f is None else f"₹{f:,.2f}"


def level(v: Any) -> Optional[str]:
    """An index level or a point figure, two decimals, no currency."""
    f = num(v)
    return None if f is None else f"{f:,.2f}"


def pct(v: Any) -> Optional[str]:
    f = num(v)
    return None if f is None else _signed(f, f"{abs(f):.2f}%")


def crore(v: Any) -> Optional[str]:
    f = num(v)
    return None if f is None else _signed(f, f"₹{abs(f):,.2f} Cr")


def times(v: Any) -> Optional[str]:
    f = num(v)
    return None if f is None else f"{f:.1f}×"


def day_text(d: Any) -> Optional[str]:
    """'29 Oct 2026'."""
    s = iso_day(d)
    if not s:
        return None
    x = date.fromisoformat(s)
    return f"{x.day} {x.strftime('%b %Y')}"


def short_day(d: Any) -> Optional[str]:
    """'29 Oct' (axis labels)."""
    s = iso_day(d)
    if not s:
        return None
    x = date.fromisoformat(s)
    return f"{x.day} {x.strftime('%b')}"


def iso_day(d: Any) -> Optional[str]:
    if isinstance(d, datetime):
        return d.astimezone(IST).date().isoformat() if d.tzinfo else d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    if isinstance(d, str) and len(d) >= 10:
        try:
            return date.fromisoformat(d[:10]).isoformat()
        except ValueError:
            return None
    return None


def tone_of(v: Any) -> str:
    f = num(v)
    if f is None or f == 0:
        return "neutral"
    return "up" if f > 0 else "down"


# ── sources and their freshness ──────────────────────────────────────────────

class Sources:
    """Each source behind the answer: its date and whether it is current. Current = today's data or the previous NSE
    session's (owner rule 2026-10-28, services/market_freshness.Window). A missing source is listed with its reason."""

    def __init__(self, window: Any):
        self.w = window
        self.rows: List[Dict[str, Any]] = []
        self.missing: List[str] = []
        self.notices: List[Dict[str, Any]] = []

    def fresh(self, as_of: Any) -> bool:
        return bool(self.w is not None and self.w.current(as_of))

    def add(self, name: str, as_of: Any, note: Optional[str] = None) -> bool:
        """Record a source that answered; True when it is current. A stale one gets a warn notice naming its date."""
        day = iso_day(as_of)
        ok = self.fresh(day)
        self.rows.append({"name": name, "as_of": day, "status": "fresh" if ok else "stale", "note": note})
        if not ok:
            self.notices.append(notice(
                f"{name} is from {day_text(day) or 'an unknown date'}, older than the previous session"
                f"{' (' + day_text(self.w.floor) + ')' if self.w is not None else ''}: shown with its date, not as today's.",
                "warn", f"stale-{len(self.notices)}"))
        return ok

    def miss(self, name: str, reason: str) -> None:
        """Record a source that could not answer: no number from it is shown."""
        self.rows.append({"name": name, "as_of": None, "status": "missing", "note": reason[:200]})
        self.missing.append(f"{name}: {reason[:200]}")
        self.notices.append(notice(f"{name} is not available ({reason[:160]}), so its figures are left out.", "warn",
                                   f"missing-{len(self.notices)}"))

    @property
    def stale(self) -> bool:
        return any(r["status"] == "stale" for r in self.rows)

    def quality(self) -> Dict[str, Any]:
        return {"sources": self.rows, "stale": self.stale, "missing": list(self.missing)}


def why(e: BaseException) -> str:
    detail = getattr(e, "detail", None)
    code = getattr(e, "status_code", None)
    if code is not None:
        return f"HTTP {code}: {detail if isinstance(detail, str) else 'refused'}"
    return f"{type(e).__name__}: {str(e)[:140]}" if str(e) else type(e).__name__


# ── blocks ───────────────────────────────────────────────────────────────────

def notice(text: str, tone: str = "info", bid: str = "notice") -> Dict[str, Any]:
    return {"type": "notice", "id": bid, "title": None, "note": None, "tone": tone, "text": text}


def block(btype: str, bid: str, title: Optional[str], note: Optional[str] = None, **data: Any) -> Dict[str, Any]:
    return {"type": btype, "id": bid, "title": title, "note": note, **data}


def candle_bars(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    """[{d, o, h, l, c, v}] from [date, o, h, l, c, v] lists; a bar missing a price is dropped, never patched."""
    out = []
    for r in rows:
        d, o, h, l, c = (r[0], num(r[1]), num(r[2]), num(r[3]), num(r[4]))
        if None in (o, h, l, c) or not iso_day(d):
            continue
        out.append({"d": iso_day(d), "o": round(o, 2), "h": round(h, 2), "l": round(l, 2), "c": round(c, 2),
                    "v": num(r[5]) if len(r) > 5 else None})
    return out


def follow(*queries: str) -> List[Dict[str, str]]:
    return [{"label": q, "query": q} for q in queries]


def assemble(intent: str, title: str, as_of: Any, headline: Optional[str], tone: str, blocks: List[Dict[str, Any]],
             src: Sources, follow_ups: List[Dict[str, str]], decision: Optional[Dict[str, Any]] = None,
             evidence: Optional[List[Dict[str, Any]]] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The payload. Stale and missing notices go first, so the reader sees them before the figures."""
    day = iso_day(as_of)
    caveat = (f"Built from end-of-day data of {day_text(day)}. " if day else "Built from end-of-day data. ") + CAVEAT_TAIL
    return {
        "schema": SCHEMA,
        "intent": intent,
        "title": title,
        "as_of": day,
        "generated_at": (now or datetime.now(IST)).astimezone(IST).isoformat(timespec="seconds"),
        "mode": "eod",
        "headline": {"text": headline, "tone": tone if tone in TONES else "neutral"} if headline else None,
        "decision": decision,
        "blocks": src.notices + blocks,
        "evidence": evidence or [],
        "data_quality": src.quality(),
        "follow_ups": follow_ups[:4],
        "caveat": caveat,
    }


# ── the contract check (mirror of the frontend zod schema's required parts) ──

def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _opt_str(v: Any) -> bool:
    return v is None or isinstance(v, str)


def _block_problems(b: Any, i: int) -> List[str]:
    p = f"blocks[{i}]"
    if not isinstance(b, dict) or not isinstance(b.get("type"), str):
        return [f"{p}: not a block"]
    t = b["type"]
    out: List[str] = []
    if not (_opt_str(b.get("title")) and _opt_str(b.get("note"))) or not isinstance(b.get("id", ""), str):
        out.append(f"{p}: id/title/note must be text")
    if t == "kpis":
        items = b.get("items")
        if not isinstance(items, list) or not all(isinstance(x, dict) and isinstance(x.get("label"), str)
                                                  and (x.get("value") is None or isinstance(x.get("value"), str) or _is_num(x.get("value")))
                                                  for x in items):
            out.append(f"{p} kpis: items need a label and a text/number/null value")
    elif t == "candles":
        bars = b.get("bars")
        if not isinstance(b.get("symbol"), str) or not isinstance(bars, list) or not bars:
            out.append(f"{p} candles: symbol and at least one bar")
        elif not all(isinstance(x, dict) and isinstance(x.get("d"), str) and all(_is_num(x.get(k)) for k in "ohlc")
                     and (x.get("v") is None or _is_num(x.get("v"))) for x in bars):
            out.append(f"{p} candles: every bar needs d and numeric o/h/l/c")
        for k, s in ((b.get("overlays") or {}).items() if isinstance(b.get("overlays"), dict) else []):
            if k not in ("ema20", "ema50", "ema200") or not isinstance(s, list) or not all(x is None or _is_num(x) for x in s):
                out.append(f"{p} candles: overlay {k} must be numbers or null")
            elif isinstance(bars, list) and len(s) != len(bars):
                out.append(f"{p} candles: overlay {k} is not aligned to the bars")
        for lv in b.get("levels") or []:
            if not (isinstance(lv, dict) and isinstance(lv.get("kind"), str) and _is_num(lv.get("price")) and _opt_str(lv.get("label"))):
                out.append(f"{p} candles: a level needs kind and a numeric price")
        band = b.get("band")
        if band is not None and not (isinstance(band, dict) and _is_num(band.get("low")) and _is_num(band.get("high"))):
            out.append(f"{p} candles: band needs numeric low and high")
    elif t == "bars":
        items = b.get("items")
        if not isinstance(b.get("unit"), str) or not isinstance(items, list) or not items or not all(
                isinstance(x, dict) and isinstance(x.get("label"), str) and (x.get("value") is None or _is_num(x.get("value"))) for x in items):
            out.append(f"{p} bars: unit and at least one labelled numeric item")
    elif t == "heatmap":
        cells = b.get("cells")
        if not isinstance(cells, list) or not cells or not all(
                isinstance(x, dict) and isinstance(x.get("label"), str) and (x.get("value") is None or _is_num(x.get("value"))) for x in cells):
            out.append(f"{p} heatmap: at least one labelled numeric cell")
    elif t == "quadrant":
        pts = b.get("points")
        q = b.get("quadrants")
        if not (isinstance(b.get("x"), dict) and isinstance(b.get("y"), dict) and isinstance(q, dict)
                and all(isinstance(q.get(k), str) for k in ("tr", "tl", "br", "bl"))):
            out.append(f"{p} quadrant: x, y and four quadrant names")
        if not isinstance(pts, list) or not pts or not all(isinstance(x, dict) and isinstance(x.get("label"), str)
                                                          and _is_num(x.get("x")) and _is_num(x.get("y")) for x in pts):
            out.append(f"{p} quadrant: at least one point with numeric x and y")
    elif t == "ranked":
        cols = b.get("columns")
        if not isinstance(cols, list) or not cols or not all(isinstance(c, dict) and isinstance(c.get("key"), str)
                                                            and isinstance(c.get("label"), str) for c in cols):
            out.append(f"{p} ranked: at least one column with key and label")
        for c in cols or []:
            if isinstance(c, dict) and c.get("format") is not None and c["format"] not in RANKED_FORMATS:
                out.append(f"{p} ranked: unknown format {c['format']}")
        rows = b.get("rows")
        if not isinstance(rows, list) or not all(
                isinstance(r, dict) and isinstance(r.get("cells"), dict)
                and all(v is None or isinstance(v, (str, bool)) or _is_num(v) for v in r["cells"].values())
                and _opt_str(r.get("symbol")) and _opt_str(r.get("plan_id")) and _opt_str(r.get("ask")) for r in rows):
            out.append(f"{p} ranked: rows need cells of text/number/bool/null")
    elif t == "trade_plan":
        if not (isinstance(b.get("plan_id"), str) and b["plan_id"]):
            out.append(f"{p} trade_plan: plan_id")
    elif t == "list":
        items = b.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(x, dict) and isinstance(x.get("text"), str) for x in items):
            out.append(f"{p} list: at least one item with text")
    elif t == "notice":
        if b.get("tone") not in ("warn", "info") or not isinstance(b.get("text"), str):
            out.append(f"{p} notice: tone warn|info and text")
    else:
        out.append(f"{p}: unknown block type {t}")
    return out


def validate(p: Any) -> List[str]:
    """Problems that would make the frontend drop the payload or a block; [] when it matches the contract."""
    if not isinstance(p, dict):
        return ["payload: not an object"]
    out: List[str] = []
    if p.get("schema") != SCHEMA:
        out.append("schema")
    if p.get("intent") not in (
            "market_view", "smart_money", "top_opportunities", "breakouts", "unusual_volume", "stock_decision", "expected_move"):
        out.append("intent")
    if not isinstance(p.get("title"), str) or not p["title"]:
        out.append("title")
    if p.get("as_of") is not None and iso_day(p["as_of"]) != p["as_of"]:
        out.append("as_of: YYYY-MM-DD or null")
    if p.get("mode") not in ("live", "eod", "mixed"):
        out.append("mode")
    h = p.get("headline")
    if h is not None and not (isinstance(h, dict) and isinstance(h.get("text"), str) and h.get("tone") in TONES):
        out.append("headline")
    d = p.get("decision")
    if d is not None:
        if not (isinstance(d, dict) and d.get("status") in DECISION_LABELS and d.get("label") == DECISION_LABELS[d["status"]]):
            out.append("decision: status and its fixed label")
        elif not all(isinstance(c, dict) and isinstance(c.get("text"), str) and (c.get("met") is None or isinstance(c.get("met"), bool))
                     for c in d.get("conditions") or []):
            out.append("decision: conditions")
    blocks = p.get("blocks")
    if not isinstance(blocks, list):
        out.append("blocks")
    else:
        for i, b in enumerate(blocks):
            out += _block_problems(b, i)
    for e in p.get("evidence") or []:
        if not (isinstance(e, dict) and isinstance(e.get("label"), str)):
            out.append("evidence")
    dq = p.get("data_quality")
    if not (isinstance(dq, dict) and isinstance(dq.get("sources"), list) and isinstance(dq.get("stale"), bool)
            and isinstance(dq.get("missing"), list)):
        out.append("data_quality")
    else:
        for s in dq["sources"]:
            if not (isinstance(s, dict) and isinstance(s.get("name"), str) and s.get("status") in ("fresh", "stale", "missing")):
                out.append("data_quality.sources")
    if not all(isinstance(f, dict) and isinstance(f.get("label"), str) and isinstance(f.get("query"), str)
               for f in p.get("follow_ups") or []):
        out.append("follow_ups")
    return out


# ── the facts block for the engine ───────────────────────────────────────────

FACTS_MAX = 6000


def _cell(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "n/a" if v is None else str(v)


def facts(p: Dict[str, Any], subject: Optional[str] = None) -> str:
    """The payload's figures as text for the specialist node (passed as a delimited data block, like TRADE_PLAN). The
    engine explains the dashboard in words; it never sees a number the dashboard does not show. `subject` (a stock)
    is written first, so the stock analyst's resolver reads it as the stock."""
    head = f"VISUAL_ANSWER for {subject} ({p.get('intent')})" if subject else f"VISUAL_ANSWER ({p.get('intent')})"
    lines = [
        head + ": a visual dashboard built from the platform's own end-of-day data is shown above this answer. These "
        "figures are the tool data for this question. Explain what the dashboard shows in a few short lines: quote only "
        "figures below with their dates, do not invent or compute new levels, say plainly what is missing or stale, and "
        "never say \"buy now\", \"recommend\" or \"pick\" (they are ideas to review).",
        f"Title: {p.get('title')} · as of {p.get('as_of') or 'unknown'} · mode {p.get('mode')}",
    ]
    if p.get("headline"):
        lines.append(f"Headline: {p['headline']['text']}")
    d = p.get("decision")
    if d:
        lines.append(f"Decision (the desk plan's own status, not the model's): {d.get('label')} — {d.get('reason') or ''}".rstrip(" —"))
        for c in d.get("conditions") or []:
            lines.append(f"  condition: {c['text']} — {'met' if c.get('met') else 'not met' if c.get('met') is False else 'unknown'}")
        if d.get("invalidation"):
            lines.append(f"  invalidation: {d['invalidation']}")
    for b in p.get("blocks") or []:
        t, title = b.get("type"), b.get("title") or b.get("id")
        if t == "notice":
            lines.append(f"Notice ({b.get('tone')}): {b.get('text')}")
        elif t == "kpis":
            lines.append(f"{title}: " + "; ".join(f"{i['label']} {i.get('value') if i.get('value') is not None else 'n/a'}"
                                                  + (f" ({i['sub']})" if i.get("sub") else "") for i in b.get("items") or []))
        elif t in ("bars", "heatmap"):
            items = b.get("items") if t == "bars" else b.get("cells")
            lines.append(f"{title} [{b.get('unit')}]: " + "; ".join(f"{i['label']} {_cell(i.get('value'))}" for i in items or []))
        elif t == "quadrant":
            pts = b.get("points") or []
            lines.append(f"{title}: {len(pts)} points (x {b['x']['label']} %, y {b['y']['label']} %): "
                         + "; ".join(f"{q['label']} {q['x']:+.2f}/{q['y']:+.2f}" for q in pts[:12]))
        elif t == "ranked":
            cols = b.get("columns") or []
            lines.append(f"{title} (columns: {', '.join(c['label'] for c in cols)}):")
            for r in (b.get("rows") or [])[:10]:
                lines.append("  " + " | ".join(_cell(r["cells"].get(c["key"])) for c in cols))
        elif t == "candles":
            bars = b.get("bars") or []
            last = bars[-1] if bars else {}
            lv = "; ".join(f"{x.get('label') or x['kind']} {x['price']:,.2f}" for x in b.get("levels") or [])
            band = b.get("band")
            lines.append(f"{title}: {len(bars)} daily candles of {b.get('symbol')}, last {last.get('d')} close {_cell(last.get('c'))}"
                         + (f"; levels: {lv}" if lv else "")
                         + (f"; band {band['low']:,.2f}–{band['high']:,.2f} ({band.get('label')})" if band else ""))
        elif t == "trade_plan":
            lines.append(f"The desk's TradePlan card {b.get('plan_id')} is shown.")
        elif t == "list":
            lines.append(f"{title}: " + "; ".join(i["text"] for i in b.get("items") or []))
        if b.get("note") and t != "notice":
            lines.append(f"  note: {b['note']}")
    dq = p.get("data_quality") or {}
    lines.append("Sources: " + "; ".join(f"{s['name']} {s.get('as_of') or 'n/a'} {s['status']}" for s in dq.get("sources") or []))
    if dq.get("missing"):
        lines.append("Missing: " + "; ".join(dq["missing"]))
    text = "\n".join(lines)
    return text if len(text) <= FACTS_MAX else text[:FACTS_MAX] + "\n[facts cut]"
