"""Correlation of the open paper positions' daily returns (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.04, §4 item 3,
§7 `GET /api/v1/risk/correlation/{id}`). Reads only.

SYMBOLS   the caller's open SPT positions (spt_positions not CLOSED) and open desk paper trades (desk_paper_trades:
          the stock of a share trade, the underlying of an F&O structure), largest exposure first, at most MAX_SYMBOLS
          with `?with=SYMBOL` (the candidate being looked at) last. Symbols left out are named in `notes`.
PRICES    the SAME end-of-day source the SPT validation reads (services/spt/opportunities/inputs: NSE bhavcopy closes
          through services/desk_trading.fetch_bars, cached by the validation's reader). These are RAW traded prices,
          NOT adjusted for bonuses or splits.
RETURNS   simple close-to-close returns over the last `days` sessions of each series (days + 1 closes), aligned by date.
PEARSON   ρ on the dates both series have. A cell is null, with the reason in `notes` and `cells`, when:
            * a series cannot be read, is empty or is stale (last close older than BARS_BUDGET_SESSIONS sessions, the
              validation's own budget)
            * a series holds a one-day move of JUMP_PCT % or more inside the window (or the exit-watch break rule,
              0.65 / 1.5): a bonus or split not adjusted in the source, or a gap; ρ would be dominated by that one day,
              so it is not reported. LIMIT: a bonus smaller than 1:4 (a price change under JUMP_PCT %) is not detected
            * the two series share fewer than min_overlap(days) = max(20, ⌈⅔ × days⌉) returns
            * a series does not move (zero variance)
          The diagonal is 1.0 for a usable series, null otherwise. |ρ| ≥ THRESHOLD (0.70) is "concentrated" (§2.04).
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services import data_freshness as fresh
from services.exit_watch import rules as break_rules

from . import constants as C

logger = logging.getLogger(__name__)

VERSION = "spt-correlation-v1"
DEFAULT_DAYS = 60
MIN_DAYS, MAX_DAYS = 20, 250
MAX_SYMBOLS = 6
THRESHOLD = 0.7
JUMP_PCT = 18.0
BARS_BUDGET_SESSIONS = 2
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,29}$")
BASIS = ("Pearson correlation of daily close-to-close returns over the last {days} sessions, NSE end-of-day closes "
         "(the SPT validation's source: services/desk_trading.fetch_bars, raw traded prices, not bonus/split adjusted)")


def min_overlap(days: int) -> int:
    return max(20, int(math.ceil(days * 2.0 / 3.0)))


def _day(b: Dict[str, Any]) -> str:
    d = b.get("date") if b.get("date") is not None else b.get("as_of_date")
    return d.isoformat() if isinstance(d, date) else str(d)[:10]


def _close(b: Dict[str, Any]) -> Optional[float]:
    v = b.get("close") if b.get("close") is not None else b.get("close_price")
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def series(symbol: str, read: Dict[str, Any], days: int, now: datetime) -> Dict[str, Any]:
    """One symbol's returns over the window, or why it cannot be used. Pure."""
    out: Dict[str, Any] = {"symbol": symbol, "usable": False, "reason": None, "returns": {}, "observations": 0,
                           "as_of": None, "source": read.get("source")}
    if read.get("error"):
        out["reason"] = f"{symbol}: {read['error']}"
        return out
    bars = [(_day(b), _close(b)) for b in read.get("bars") or []]
    bars = sorted((d, c) for d, c in bars if c is not None and d)
    if len(bars) < 2:
        out["reason"] = f"{symbol}: no end-of-day closes to measure returns from"
        return out
    out["as_of"] = bars[-1][0]
    f = fresh.assess(read.get("source") or "end-of-day bars", bars[-1][0], budget_sessions=BARS_BUDGET_SESSIONS, now=now)
    if not f["ok"]:
        out["reason"] = f"{symbol}: the last close is stale ({f.get('reason')})"
        return out
    window = bars[-(days + 1):]
    low = max(break_rules.BREAK_LOW, 1.0 - JUMP_PCT / 100.0)
    high = min(break_rules.BREAK_HIGH, 1.0 / low)
    rets: Dict[str, float] = {}
    for (d0, c0), (d1, c1) in zip(window, window[1:]):
        ratio = c1 / c0
        if ratio <= low or ratio >= high:
            out["reason"] = (f"{symbol}: a one-day move of {(ratio - 1) * 100:+.1f}% on {d1} (close {c0:g} → {c1:g}) looks "
                             f"like a bonus or split not adjusted in the source, or a gap; the correlation would rest on "
                             f"that one day, so it is not shown")
            out["jump"] = {"day": d1, "pct": round((ratio - 1) * 100, 2)}
            return out
        rets[d1] = ratio - 1.0
    out["returns"] = rets
    out["observations"] = len(rets)
    if len(rets) < min_overlap(days):
        out["reason"] = f"{symbol}: only {len(rets)} daily returns in the window; at least {min_overlap(days)} are needed"
        return out
    out["usable"] = True
    return out


def pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return max(-1.0, min(1.0, sxy / math.sqrt(sxx * syy)))


def matrix(rows: List[Dict[str, Any]], days: int) -> Tuple[List[List[Optional[float]]], List[Dict[str, Any]]]:
    """(the matrix, [{a, b, reason}] for each null off-diagonal cell). Pure."""
    n = len(rows)
    m: List[List[Optional[float]]] = [[None] * n for _ in range(n)]
    cells: List[Dict[str, Any]] = []
    need = min_overlap(days)
    for i in range(n):
        if rows[i]["usable"]:
            m[i][i] = 1.0
        for j in range(i + 1, n):
            a, b = rows[i], rows[j]
            why = None
            if not a["usable"] or not b["usable"]:
                why = a["reason"] if not a["usable"] else b["reason"]
            else:
                common = sorted(set(a["returns"]) & set(b["returns"]))
                if len(common) < need:
                    why = f"only {len(common)} common sessions; at least {need} are needed"
                else:
                    r = pearson([a["returns"][d] for d in common], [b["returns"][d] for d in common])
                    if r is None:
                        why = "one of the two series does not move over the window"
                    else:
                        m[i][j] = m[j][i] = round(r, 4)
            if why:
                cells.append({"a": a["symbol"], "b": b["symbol"], "reason": why})
    return m, cells


def build(rows: List[Dict[str, Any]], days: int, *, left_out: List[str], with_symbol: Optional[str]) -> Dict[str, Any]:
    m, cells = matrix(rows, days)
    notes = []
    seen = set()
    for r in rows:
        if r["reason"] and r["reason"] not in seen:
            seen.add(r["reason"])
            notes.append(r["reason"])
    if left_out:
        notes.append(f"Only {MAX_SYMBOLS} symbols are shown (largest exposure first); left out: {', '.join(left_out)}.")
    if not rows:
        notes.append("No open paper position to correlate.")
    notes.append(f"Bonus/split check: a one-day move of {JUMP_PCT:g}% or more nulls the series; a smaller unadjusted "
                 f"bonus (under 1:4) is not detected.")
    concentrated = [{"a": rows[i]["symbol"], "b": rows[j]["symbol"], "rho": m[i][j]}
                    for i in range(len(rows)) for j in range(i + 1, len(rows))
                    if m[i][j] is not None and abs(m[i][j]) >= THRESHOLD]
    return {"symbols": [r["symbol"] for r in rows], "matrix": m, "days": days, "threshold": THRESHOLD,
            "basis": BASIS.format(days=days), "notes": notes, "cells": cells, "concentrated_pairs": concentrated,
            "series": [{"symbol": r["symbol"], "usable": r["usable"], "observations": r["observations"],
                        "as_of": r["as_of"], "reason": r["reason"], "source": r.get("source"), "role": r.get("role")}
                       for r in rows],
            "with": with_symbol, "min_overlap": min_overlap(days), "version": VERSION}


def clean_symbol(raw: Optional[str]) -> Optional[str]:
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValueError("with must be an NSE symbol (letters, digits, & _ . -)")
    return s


async def open_symbols(db, user_id: str) -> List[Tuple[str, float, str]]:
    """[(symbol, exposure ₹, role)] of the open paper positions, largest first, one row per symbol."""
    from services import desk_strategy_trades as strat
    from services import desk_trading as desk
    found: Dict[str, Tuple[float, str]] = {}

    def add(sym: Any, exposure: Any, role: str) -> None:
        s = str(sym or "").upper().strip()
        if not s:
            return
        e = float(exposure) if isinstance(exposure, (int, float)) and not isinstance(exposure, bool) else 0.0
        prev = found.get(s)
        found[s] = (prev[0] + e if prev else e, prev[1] if prev else role)

    for p in await db[C.POSITIONS].find({"user_id": user_id, "state": {"$in": list(C.POS_OPEN_STATES)}}).to_list(500):
        add(p.get("symbol"), (p.get("quantity") or 0) * (p.get("avg_entry_price") or 0), "spt_position")
    for t in await db[desk.TRADES].find({"user_id": user_id, "status": "open"}).to_list(500):
        if t.get("kind") == strat.KIND:
            add(t.get("underlying") or t.get("symbol"), strat.exposure_rs(t), "desk_fno_underlying")
        else:
            add(t.get("symbol"), (t.get("quantity") or 0) * (t.get("entry_price") or 0), "desk_share")
    return sorted(((s, e, r) for s, (e, r) in found.items()), key=lambda x: (-x[1], x[0]))


BarsReader = Callable[[str, datetime], Awaitable[Dict[str, Any]]]


async def _default_bars(symbol: str, now: datetime) -> Dict[str, Any]:
    from .opportunities import inputs
    return await inputs.get_inputs().bars(symbol, now)


async def read(db, user_id: str, *, now: datetime, days: int = DEFAULT_DAYS, with_symbol: Optional[str] = None,
               bars_reader: Optional[BarsReader] = None) -> Dict[str, Any]:
    held = await open_symbols(db, user_id)
    held = [h for h in held if h[0] != with_symbol]
    room = MAX_SYMBOLS - (1 if with_symbol else 0)
    picked = [(s, r) for s, _, r in held[:room]] + ([(with_symbol, "with")] if with_symbol else [])
    left_out = [s for s, _, _ in held[room:]]
    reader = bars_reader or _default_bars
    rows = []
    for sym, role in picked:
        try:
            got = await reader(sym, now)
        except Exception as e:  # noqa: BLE001 — that symbol's cells are null with the reason
            logger.warning("correlation: bars for %s unreadable (%s)", sym, type(e).__name__)
            got = {"bars": [], "error": f"the end-of-day bars could not be read ({type(e).__name__})"}
        row = series(sym, got, days, now)
        row["role"] = role
        rows.append(row)
    return build(rows, days, left_out=left_out, with_symbol=with_symbol)
