"""Today's P&L curve of the open paper book, from Kite intraday candles (spec §7.4: cumulative, measured from the session's
opening baseline). Read-only.

What the curve is: the CURRENT open positions marked at each candle's close through the latest session (today while or after
it trades; the previous session before the open), plus the realized P&L of trades closed that session. A candle an instrument
did not trade in carries its last close forward; before its first candle the previous close is used. A position with no
candles at all is left out and listed in `missing`, and the curve says it is partial. `baseline_gross` is the same book at the
previous close, so `change_since_baseline` is the session's move.

Why candles and not stored snapshots: the curve exists from the first minute, needs no new job or table, and can be rebuilt
for any session. Candles are Kite's own (raw prices), read with the platform token through the read-only client.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.kite_live_feed import config as cfg
from services.kite_live_feed import day_quote as dq
from services.kite_live_feed.intraday import INTERVALS, IntradayService, _bar

from . import ledger, prices
from .book import Book

logger = logging.getLogger(__name__)

ALLOWED = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "60m"}
CACHE_OPEN_S, CACHE_CLOSED_S = 60.0, 600.0
SPACING_S = 0.4                                   # Kite historical: ~3 requests a second

_SVC: Optional[IntradayService] = None
_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_GATE = asyncio.Lock()
_LAST_CALL = [0.0]


def _service() -> IntradayService:
    global _SVC
    if _SVC is None:
        _SVC = IntradayService()
    return _SVC


async def _paced(fn, *args):
    async with _GATE:
        wait = SPACING_S - (time.monotonic() - _LAST_CALL[0])
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            return await asyncio.to_thread(fn, *args)
        finally:
            _LAST_CALL[0] = time.monotonic()


def curve(series: Dict[str, List[list]], books: List[Dict[str, Any]], *, realized: float, charges: float,
          day: str) -> Dict[str, Any]:
    """The pure part. `series[key]` = [[iso time, o, h, l, c, v], ...] of one instrument (any days); `books` = positions
    [{key, net_quantity, avg_price, multiplier, prev_close}]. Returns points for `day` plus the baseline and what is missing."""
    times = sorted({b[0] for rows in series.values() for b in rows if str(b[0])[:10] == day})
    used, missing = [], []
    lines: List[Tuple[Dict[str, Any], Dict[str, float]]] = []
    for p in books:
        rows = [b for b in series.get(p["key"], []) if str(b[0])[:10] == day]
        if not rows:
            missing.append({"position_id": p["key"], "reason": "no intraday candles for this instrument in the session"})
            continue
        used.append(p["key"])
        lines.append((p, {b[0]: float(b[4]) for b in rows}))
    baseline_unreal = 0.0
    baseline_known = True
    for p, _ in lines:
        if p.get("prev_close") is None:
            baseline_known = False
        else:
            baseline_unreal += (p["prev_close"] - p["avg_price"]) * p["net_quantity"] * p["multiplier"]
    baseline = round(baseline_unreal + realized, 2) if baseline_known else None
    points = []
    last: Dict[str, Optional[float]] = {p["key"]: p.get("prev_close") for p, _ in lines}
    for t in times:
        total, known = 0.0, True
        for p, closes in lines:
            if t in closes:
                last[p["key"]] = closes[t]
            px = last[p["key"]]
            if px is None:
                known = False
                break
            total += (px - p["avg_price"]) * p["net_quantity"] * p["multiplier"]
        if not known:
            continue
        gross = round(total + realized, 2)
        points.append({"t": t, "unrealized_pnl": round(total, 2), "realized_pnl": round(realized, 2), "gross_pnl": gross,
                       "net_pnl": round(gross - charges, 2),
                       "change_since_baseline": round(gross - baseline, 2) if baseline is not None else None})
    return {"points": points, "baseline_gross": baseline, "positions_used": used, "missing": missing,
            "partial": bool(missing)}


TRADE_MAX_SESSIONS = 10


def trade_curve(series: Dict[str, List[list]], lines: List[Dict[str, Any]], *, charges: float, start: str) -> Dict[str, Any]:
    """One trade's P&L from `start` (an IST ISO time) through the last candle, over any days. `lines` are its open positions
    [{key, net_quantity, avg_price, multiplier, prev_close}]; a time before every line has a price is skipped; a candle a line
    did not trade in carries its last close forward. Net = gross − `charges` (the estimate for closing now, held constant)."""
    used, missing, closes = [], [], []
    for p in lines:
        rows = [b for b in series.get(p["key"], []) if str(b[0]) >= start]
        if not rows:
            missing.append({"position_id": p["key"], "reason": "no intraday candles for this instrument since the entry"})
            continue
        used.append(p["key"])
        closes.append((p, {b[0]: float(b[4]) for b in rows}))
    times = sorted({t for _, c in closes for t in c})
    last: Dict[str, Optional[float]] = {p["key"]: None for p, _ in closes}
    points = []
    for t in times:
        total, known = 0.0, True
        for p, c in closes:
            if t in c:
                last[p["key"]] = c[t]
            px = last[p["key"]]
            if px is None:
                known = False
                break
            total += (px - p["avg_price"]) * p["net_quantity"] * p["multiplier"]
        if not known or missing:
            continue
        gross = round(total, 2) + 0.0
        points.append({"t": t, "gross_pnl": gross, "net_pnl": round(gross - charges, 2)})
    return {"points": points, "positions_used": used, "missing": missing, "partial": bool(missing)}


def _ist_iso(stamp: Any) -> Optional[str]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(cfg.IST).isoformat()


def _sessions_since(day: str, today: str) -> int:
    """Weekdays from `day` through `today` (a holiday counts: Kite then just has no candles for it)."""
    try:
        a, b = datetime.fromisoformat(day).date(), datetime.fromisoformat(today).date()
    except ValueError:
        return 1
    n, d = 0, a
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return max(1, n)


def paper_lines(book: Book, quotes: Dict[str, prices.Quote], items: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
    """The open positions of the paper book (or of `items`) as curve lines."""
    out = []
    for item in (book.open if items is None else items):
        if not item.entered:
            continue
        pos_map = ledger.build(item.executions)
        for leg in item.legs:
            pos = pos_map.get(leg.position_key)
            if pos is None or not pos.is_open or pos.average_price is None:
                continue
            q = quotes.get(leg.position_key)
            out.append({"key": leg.position_key, "net_quantity": pos.net_quantity, "avg_price": pos.average_price,
                        "multiplier": pos.multiplier, "prev_close": q.prev_close if q else None, "instrument": leg.instrument,
                        "leg": leg})
    return out


async def _series(lines: List[Dict[str, Any]], iv: str, kname: str, *, sessions: int, session_open: bool,
                  now: datetime) -> Tuple[Dict[str, List[list]], List[str]]:
    """Candles for each line's instrument: stocks from the intraday service, contracts by their Kite token."""
    stock_keys: Dict[str, List[str]] = {}
    contract_legs = []
    for ln in lines:
        leg = ln["leg"]
        if leg.kind == "cash":
            stock_keys.setdefault(leg.symbol, []).append(ln["key"])
        elif leg.kind in ("future", "option"):
            contract_legs.append(leg)
    series: Dict[str, List[list]] = {}
    notes: List[str] = []
    if stock_keys or contract_legs:
        from services.kite_live_feed.feed import get_feed
        await prices.ensure_token(get_feed().db)          # the candles are read with the day's platform token
    svc = _service()
    for sym, keys in stock_keys.items():
        try:
            got = await svc.bars(sym, iv, sessions=sessions, session_open=session_open)
        except Exception as e:  # noqa: BLE001 — one instrument's failure leaves it out of the curve, said so
            notes.append(f"{sym}: intraday candles could not be read ({type(e).__name__}).")
            continue
        if got.get("availability") != "ok":
            notes.append(f"{sym}: no intraday candles ({got.get('reason') or got.get('availability')}).")
        for k in keys:
            series[k] = got.get("bars") or []
    if contract_legs:
        kite = prices.kite_client()
        if kite is None:
            notes.append("No Kite session for the platform: futures and options are left out of the curve.")
        else:
            today = now.astimezone(cfg.IST).date().isoformat()
            try:
                tokens = await prices.contract_tokens(kite, contract_legs, today)
            except Exception as e:  # noqa: BLE001
                tokens = {}
                notes.append(f"The contract list could not be read ({type(e).__name__}).")
            t_to = now.astimezone(cfg.IST).replace(tzinfo=None)
            for leg in contract_legs:
                tok = tokens.get(leg.position_key)
                if not tok:
                    notes.append(f"{leg.instrument}: no listed contract found for its candles.")
                    continue
                try:
                    rows = await _paced(kite.historical_data, tok[1], t_to - timedelta(days=5), t_to, kname)
                except Exception as e:  # noqa: BLE001
                    notes.append(f"{leg.instrument}: candles could not be read ({type(e).__name__}).")
                    continue
                series[leg.position_key] = sorted((b for b in (_bar(c) for c in rows or []) if b), key=lambda b: b[0])
    return series, notes


BASIS = ("Kite intraday candles (raw prices), each candle's close; a candle an instrument did not trade in carries its last close "
         "forward. The book is today's open positions (the desk's paper trades and the scanner's SPT positions alike); "
         "realised = trades closed that session plus the scanner positions' partial exits that session; charges are today's "
         "estimate for closing them, held constant. Display only.")


def partial_realized(item: Any, day: str) -> float:
    """The realised P&L of an open position's closing executions on IST `day` (a scanner position's T1 partial exit),
    replayed through the same weighted-average ledger in the same order as ledger.build."""
    out = 0.0
    pos = ledger.Position(key=item.trade_id)
    ordered = [e for _, e in sorted(enumerate(item.executions), key=lambda p: (p[1].at or "", p[0]))]
    for ex in ordered:
        before = pos.realized_pnl
        ledger.apply(pos, ex)
        if ex.side < 0 and (_ist_iso(ex.at) or "")[:10] == day:
            out += pos.realized_pnl - before
    return round(out, 2)


async def build(uid: str, book: Book, quotes: Dict[str, prices.Quote], interval: str, *, charges_estimated: float,
                now: Optional[datetime] = None, mode: str = "PAPER", live_lines: Optional[List[Dict[str, Any]]] = None
                ) -> Dict[str, Any]:
    """The book's curve through the latest session. `mode` PAPER (the paper book), LIVE (`live_lines`, the broker positions)
    or ALL (both)."""
    if interval not in ALLOWED:
        raise ValueError("invalid_interval")
    now = now or datetime.now(timezone.utc)
    session_open = dq.in_session(now)
    hit = _CACHE.get((uid, interval, mode))
    if hit and time.monotonic() - hit[0] < (CACHE_OPEN_S if session_open else CACHE_CLOSED_S):
        return hit[1]
    iv = ALLOWED[interval]
    kname = INTERVALS[iv][0]
    today = now.astimezone(cfg.IST).date().isoformat()

    lines: List[Dict[str, Any]] = []
    if mode in ("ALL", "PAPER"):
        lines += paper_lines(book, quotes)
    if mode in ("ALL", "LIVE"):
        lines += list(live_lines or [])
    series, notes = await _series(lines, iv, kname, sessions=1, session_open=session_open, now=now)
    books = [{k: v for k, v in ln.items() if k != "leg"} for ln in lines]

    days = sorted({str(b[0])[:10] for rows in series.values() for b in rows})
    day = days[-1] if days else today
    realized = 0.0
    if mode in ("ALL", "PAPER"):
        for item in book.closed:
            if (item.public.get("exit_session") or "") == day and item.public.get("realized_pnl_rs") is not None:
                realized += float(item.public["realized_pnl_rs"])
        for item in book.open:
            if getattr(item, "source", "desk") == "scanner" and item.entered:
                realized += partial_realized(item, day)
    out = curve(series, books, realized=round(realized, 2), charges=charges_estimated, day=day)
    out.update({"date": day, "interval": interval, "is_today": day == today, "session_open": session_open,
                "as_of": now.isoformat(), "notes": notes, "mode": mode, "basis": BASIS})
    if mode in ("ALL", "LIVE"):
        out["basis"] += (" Live positions: the broker's quantity and average from its last read; realised P&L of the broker "
                         "positions is not in the curve (brokers do not split it).")
    _CACHE[(uid, interval, mode)] = (time.monotonic(), out)
    return out


async def build_trade(uid: str, book: Book, quotes: Dict[str, prices.Quote], interval: str, trade: str, *,
                      charges_by_key: Dict[str, Optional[float]], live_lines: Optional[List[Dict[str, Any]]] = None,
                      now: Optional[datetime] = None) -> Dict[str, Any]:
    """ONE trade's curve. A paper SHARE trade from its entry (at most TRADE_MAX_SESSIONS sessions back); a paper structure or
    a live position over the latest session only. LookupError("trade_not_found") for an id that is not an open position."""
    if interval not in ALLOWED:
        raise ValueError("invalid_interval")
    now = now or datetime.now(timezone.utc)
    session_open = dq.in_session(now)
    hit = _CACHE.get((uid, interval, "trade:" + trade))
    if hit and time.monotonic() - hit[0] < (CACHE_OPEN_S if session_open else CACHE_CLOSED_S):
        return hit[1]
    iv = ALLOWED[interval]
    kname = INTERVALS[iv][0]
    today = now.astimezone(cfg.IST).date().isoformat()

    item = next((i for i in book.open if i.entered and (i.trade_id == trade or any(l.position_key == trade for l in i.legs))), None)
    if item is not None:
        lines = paper_lines(book, quotes, [item])
        mode = "PAPER"
    else:
        lines = [ln for ln in (live_lines or []) if ln["key"] == trade]
        mode = "LIVE"
    if not lines:
        raise LookupError("trade_not_found")
    charges = round(sum(charges_by_key.get(ln["key"]) or 0.0 for ln in lines), 2)
    charges_known = all(charges_by_key.get(ln["key"]) is not None for ln in lines)

    since_entry, sessions, why = False, 1, None
    entry_day = None
    if item is not None and item.kind == "cash":
        entry_day = item.entry_session or (_ist_iso(item.public.get("opened_at")) or "")[:10] or None
    if entry_day:
        n = _sessions_since(entry_day, today)
        sessions = min(TRADE_MAX_SESSIONS, n)
        since_entry = n <= TRADE_MAX_SESSIONS
        if not since_entry:
            why = f"Entered {entry_day}: more than {TRADE_MAX_SESSIONS} sessions ago, so the curve starts {TRADE_MAX_SESSIONS} sessions back."
    elif item is not None:
        why = "A structure is drawn over the latest session only (its legs' candles are read for one session)."
    else:
        why = "A broker position is drawn over the latest session only: brokers do not send when it was opened."
    series, notes = await _series(lines, iv, kname, sessions=sessions, session_open=session_open, now=now)
    days = sorted({str(b[0])[:10] for rows in series.values() for b in rows})
    if since_entry and entry_day:
        opened = _ist_iso(item.public.get("opened_at")) if item is not None else None
        # An at-once fill is at its recording time; a fill decided on an end-of-day bar is the whole entry session.
        start = opened if opened and opened[:10] == entry_day else f"{entry_day}T00:00:00+05:30"
    else:
        start = f"{days[-sessions] if len(days) >= sessions else (days[0] if days else today)}T00:00:00+05:30"
        if item is None or item.kind != "cash":
            start = f"{days[-1] if days else today}T00:00:00+05:30"
    out = trade_curve(series, lines, charges=charges, start=start)
    out.update({"trade": trade, "mode": mode, "from": out["points"][0]["t"] if out["points"] else None,
                "since_entry": since_entry, "interval": interval, "as_of": now.isoformat(), "notes": notes,
                "date": days[-1] if days else today, "charges_estimated": charges if charges_known else None,
                "basis": ("Kite intraday candles (raw prices), each candle's close, against the position's average price; net = "
                          "gross − the estimate for closing it now, held constant. " + (why or "Drawn from the entry.")).strip()})
    _CACHE[(uid, interval, "trade:" + trade)] = (time.monotonic(), out)
    return out
