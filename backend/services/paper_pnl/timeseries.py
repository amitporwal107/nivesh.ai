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


async def build(uid: str, book: Book, quotes: Dict[str, prices.Quote], interval: str, *, charges_estimated: float,
                now: Optional[datetime] = None) -> Dict[str, Any]:
    if interval not in ALLOWED:
        raise ValueError("invalid_interval")
    now = now or datetime.now(timezone.utc)
    session_open = dq.in_session(now)
    hit = _CACHE.get((uid, interval))
    if hit and time.monotonic() - hit[0] < (CACHE_OPEN_S if session_open else CACHE_CLOSED_S):
        return hit[1]
    iv = ALLOWED[interval]
    kname = INTERVALS[iv][0]
    today = now.astimezone(cfg.IST).date().isoformat()

    books: List[Dict[str, Any]] = []
    stock_keys: Dict[str, List[str]] = {}
    contract_legs = []
    for item in book.open:
        if not item.entered:
            continue
        pos_map = ledger.build(item.executions)
        for leg in item.legs:
            pos = pos_map.get(leg.position_key)
            if pos is None or not pos.is_open or pos.average_price is None:
                continue
            q = quotes.get(leg.position_key)
            books.append({"key": leg.position_key, "net_quantity": pos.net_quantity, "avg_price": pos.average_price,
                          "multiplier": pos.multiplier, "prev_close": q.prev_close if q else None, "instrument": leg.instrument})
            if leg.kind == "cash":
                stock_keys.setdefault(leg.symbol, []).append(leg.position_key)
            else:
                contract_legs.append(leg)

    series: Dict[str, List[list]] = {}
    notes: List[str] = []
    if stock_keys or contract_legs:
        from services.kite_live_feed.feed import get_feed
        await prices.ensure_token(get_feed().db)          # the candles are read with the day's platform token
    svc = _service()
    for sym, keys in stock_keys.items():
        try:
            got = await svc.bars(sym, iv, sessions=1, session_open=session_open)
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
            try:
                tokens = await prices.contract_tokens(kite, contract_legs, today)
            except Exception as e:  # noqa: BLE001
                tokens = {}
                notes.append(f"The contract list could not be read ({type(e).__name__}).")
            t_to = now.astimezone(cfg.IST).replace(tzinfo=None)
            for leg in contract_legs:
                tok = tokens.get(leg.position_key)
                if not tok:
                    continue
                try:
                    rows = await _paced(kite.historical_data, tok[1], t_to - timedelta(days=5), t_to, kname)
                except Exception as e:  # noqa: BLE001
                    notes.append(f"{leg.instrument}: candles could not be read ({type(e).__name__}).")
                    continue
                series[leg.position_key] = sorted((b for b in (_bar(c) for c in rows or []) if b), key=lambda b: b[0])

    days = sorted({str(b[0])[:10] for rows in series.values() for b in rows})
    day = days[-1] if days else today
    realized = 0.0
    for item in book.closed:
        if (item.public.get("exit_session") or "") == day and item.public.get("realized_pnl_rs") is not None:
            realized += float(item.public["realized_pnl_rs"])
    out = curve(series, books, realized=round(realized, 2), charges=charges_estimated, day=day)
    out.update({"date": day, "interval": interval, "is_today": day == today, "session_open": session_open,
                "as_of": now.isoformat(), "notes": notes, "mode": "PAPER",
                "basis": "Kite intraday candles (raw prices), each candle's close; a candle an instrument did not trade in "
                         "carries its last close forward. The book is today's open positions; charges are today's estimate "
                         "for closing them, held constant. Display only."})
    _CACHE[(uid, interval)] = (time.monotonic(), out)
    return out
