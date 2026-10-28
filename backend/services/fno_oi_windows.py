"""Futures OI build-up by N-bar window, per expiry and consolidated (Trade Desk › Chart Analysis › Live chart).

    GET /api/fno/{symbol}/futures/oi-buildup   (routes/fno.py) answers with the functions below.

Two modes, said in the answer's `mode`:
  intraday     Kite candles WITH open interest (historical_data oi=1) for the current, next and far month futures, read
               with the platform token (services/kite_live_feed/intraday.py futures_bars). Each window is a block of
               `size` bar slots counted from the 09:15 open (15m × 4 = 09:15–10:15, 10:15–11:15, …), by TIME, so the
               three contracts and the cash chart share the same windows even when an illiquid month has no trade in a
               slot.
  end_of_day   no Kite session: the latest NSE F&O bhavcopy day per expiry (the rows /api/fno/{symbol}/futures reads),
               one window = the day, labelled end of day.

Per window
  close          the contract's last traded price in the window (carried from the previous window when it did not trade)
  price_change   close − the previous window's close
  oi             open interest at the window's end. A contract's OI changes only by a trade, so a contract with no candle
                 in a window keeps its OI: that is the exchange's figure, not an estimate
  oi_change      oi − the previous window's oi
  volume         contracts traded in the window (a slot with no candle traded nothing)
  label          buildup_label(price_change, oi_change), the desk build-up board's rule
                 (nidp/services/daas_api/routers/desk_market.py buildup_label; tests/test_desk_live_chart.py keeps them equal)
  complete       false for the window still in progress (fewer than `size` slots have closed)
Consolidated: the near month's close and price change with the OI and volume SUMMED over the three expiries, the board's
own consolidation ("OI summed over every expiry, so a roll near expiry does not read as unwinding"). Null OI while any
contract has no OI yet.

The first window of a series has no baseline, so the reader asks Kite for one extra session and `trim` drops that
session's windows: every window shown has its previous window. Nothing here reads a database or Kite. OI shows
positioning, not who initiated it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

LABELS = ("long_buildup", "short_buildup", "short_covering", "long_unwinding", "neutral")
SLOTS = ("current", "next", "far")
OPEN_MINUTES = 9 * 60 + 15                 # NSE F&O and cash open, 09:15 IST
CLOSE_MINUTES = 15 * 60 + 30               # and close, 15:30 IST: the last window ends there
NOTE = "OI shows positioning, not who initiated it. Build-up is a reading of price change and OI change together."


def buildup_label(price_chg: Optional[float], oi_chg: Optional[float]) -> Optional[str]:
    """The build-up reading of a price change and an OI change (the desk board's rule). None when either is missing."""
    if price_chg is None or oi_chg is None:
        return None
    if price_chg > 0 and oi_chg > 0:
        return "long_buildup"
    if price_chg < 0 and oi_chg > 0:
        return "short_buildup"
    if price_chg > 0 and oi_chg < 0:
        return "short_covering"
    if price_chg < 0 and oi_chg < 0:
        return "long_unwinding"
    return "neutral"


def _pct(change: Optional[float], base: Optional[float]) -> Optional[float]:
    if change is None or base is None or base == 0:
        return None
    return round(change / base * 100, 2)


def window_key(t_iso: str, minutes: int, size: int) -> Tuple[str, int]:
    """(session day, window index from the 09:15 open) of a bar's start time."""
    t = datetime.fromisoformat(t_iso)
    since_open = t.hour * 60 + t.minute - OPEN_MINUTES
    return t_iso[:10], max(0, since_open) // (minutes * size)


def _window_bounds(day: str, idx: int, minutes: int, size: int, tz_suffix: str) -> Tuple[str, str]:
    start = OPEN_MINUTES + idx * minutes * size
    end = min(start + minutes * size, CLOSE_MINUTES)
    fmt = lambda m: f"{day}T{m // 60:02d}:{m % 60:02d}:00{tz_suffix}"  # noqa: E731
    return fmt(start), fmt(end)


def series_windows(contracts: Sequence[Sequence[Sequence[Any]]], minutes: int, size: int) -> List[Dict[str, Any]]:
    """Windows over one or more contracts' bars ([iso, o, h, l, c, v, oi], oldest first). contracts[0] carries the price;
    OI and volume are summed over every contract (one contract: itself). See the module docstring."""
    if not contracts or not contracts[0]:
        return []
    tz_suffix = contracts[0][0][0][19:] or "+05:30"
    per: List[Dict[Tuple[str, int], List[Sequence[Any]]]] = []
    keys = set()
    for bars in contracts:
        groups: Dict[Tuple[str, int], List[Sequence[Any]]] = {}
        for b in bars:
            k = window_key(b[0], minutes, size)
            groups.setdefault(k, []).append(b)
            keys.add(k)
        per.append(groups)
    last_close: Optional[float] = None
    last_oi: List[Optional[float]] = [None] * len(contracts)
    prev_close: Optional[float] = None
    prev_oi: Optional[float] = None
    out: List[Dict[str, Any]] = []
    for k in sorted(keys):
        volume = 0.0
        slots = 0
        for i, groups in enumerate(per):
            bars = groups.get(k) or []
            volume += sum(float(b[5] or 0) for b in bars)
            for b in bars:
                if b[6] is not None:
                    last_oi[i] = float(b[6])
            if i == 0 and bars:
                last_close = float(bars[-1][4])
                slots = len(bars)
        if last_close is None:
            continue                                   # the near month has not traded yet: no price to read
        oi = sum(x for x in last_oi) if all(x is not None for x in last_oi) else None   # type: ignore[misc]
        price_change = round(last_close - prev_close, 2) if prev_close is not None else None
        oi_change = oi - prev_oi if (oi is not None and prev_oi is not None) else None
        start, end = _window_bounds(k[0], k[1], minutes, size, tz_suffix)
        out.append({
            "day": k[0], "index": k[1], "start": start, "end": end, "bars": slots,
            "close": last_close, "price_change": price_change, "price_change_pct": _pct(price_change, prev_close),
            "oi": int(oi) if oi is not None else None, "oi_change": int(oi_change) if oi_change is not None else None,
            "oi_change_pct": _pct(oi_change, prev_oi), "volume": int(volume),
            "label": buildup_label(price_change, oi_change),
        })
        prev_close, prev_oi = last_close, oi
    return out


def mark_complete(windows: List[Dict[str, Any]], minutes: int, size: int, now: datetime) -> List[Dict[str, Any]]:
    """`complete` false for a window whose end is still in the future (the one in progress)."""
    for w in windows:
        w["complete"] = datetime.fromisoformat(w["end"]) <= now
    return windows


def trim(windows: List[Dict[str, Any]], sessions: int) -> List[Dict[str, Any]]:
    """Only the windows of the last `sessions` session days (the extra, older session was the baseline)."""
    days = sorted({w["day"] for w in windows})[-sessions:]
    return [w for w in windows if w["day"] in days]


def _counts(windows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    return {lab: sum(1 for w in windows if w["label"] == lab) for lab in LABELS} | {"unclassified": sum(1 for w in windows if w["label"] is None)}


def intraday_answer(symbol: str, raw: Dict[str, Any], interval: str, minutes: int, size: int, sessions: int, now: datetime) -> Dict[str, Any]:
    """The route's body from IntradayService.futures_bars (raw['contracts'] nearest expiry first, at most three)."""
    contracts = raw.get("contracts") or []
    out_contracts = []
    for slot, c in zip(SLOTS, contracts):
        w = trim(mark_complete(series_windows([c["bars"]], minutes, size), minutes, size, now), sessions)
        out_contracts.append({"slot": slot, "expiry": c.get("expiry"), "tradingsymbol": c.get("tradingsymbol"),
                              "lot_size": c.get("lot_size"), "windows": w, "counts": _counts(w)})
    missing = [slot for slot in SLOTS[len(contracts):]]
    cons_w = trim(mark_complete(series_windows([c["bars"] for c in contracts], minutes, size), minutes, size, now), sessions) if contracts else []
    last_bar = max((c["bars"][-1][0] for c in contracts if c.get("bars")), default=None)
    return {
        "symbol": symbol, "mode": "intraday", "interval": interval, "window": size, "sessions": sessions,
        "source": raw.get("source"), "snapshot_at": raw.get("as_of"), "last_bar_at": last_bar,
        "contracts": out_contracts,
        "consolidated": {"slot": "consolidated", "expiries": [c.get("expiry") for c in contracts], "windows": cons_w, "counts": _counts(cons_w),
                         "basis": "the near month's price change; OI and volume summed over the expiries listed"},
        "missing_slots": missing,
        "missing_note": (f"Kite lists {len(contracts)} futures for {symbol} right now: after an expiry the new far month is listed later "
                         f"in the morning, so the consolidated figure sums the {len(contracts)} listed.") if missing else None,
        "kite_reason": None, "note": NOTE, "read_only": True,
    }


def eod_answer(symbol: str, as_of: str, futures: Sequence[Dict[str, Any]], kite_reason: Optional[str]) -> Dict[str, Any]:
    """The fallback body from the latest bhavcopy day's shaped futures (routes/fno.shape_futures, nearest first): one
    window per contract, the day itself."""
    rows = list(futures)[:3]

    def one(f: Dict[str, Any]) -> Dict[str, Any]:
        price_change, oi_change = f.get("change"), f.get("change_in_oi")
        oi = f.get("oi")
        prev_oi = oi - oi_change if (oi is not None and oi_change is not None) else None
        return {"day": as_of, "index": 0, "start": as_of, "end": as_of, "bars": 1, "close": f.get("close"),
                "price_change": price_change, "price_change_pct": f.get("change_pct"), "oi": oi, "oi_change": oi_change,
                "oi_change_pct": _pct(oi_change, prev_oi), "volume": f.get("volume"),
                "label": buildup_label(price_change, oi_change), "complete": True}

    contracts = []
    for slot, f in zip(SLOTS, rows):
        w = [one(f)]
        contracts.append({"slot": slot, "expiry": f.get("expiry"), "tradingsymbol": None, "lot_size": None, "windows": w, "counts": _counts(w)})
    cons: List[Dict[str, Any]] = []
    if rows:
        near = one(rows[0])
        ois = [f.get("oi") for f in rows]
        chgs = [f.get("change_in_oi") for f in rows]
        vols = [f.get("volume") for f in rows]
        oi = sum(ois) if all(x is not None for x in ois) else None
        oi_change = sum(chgs) if all(x is not None for x in chgs) else None
        prev_oi = oi - oi_change if (oi is not None and oi_change is not None) else None
        cons = [{**near, "oi": oi, "oi_change": oi_change, "oi_change_pct": _pct(oi_change, prev_oi),
                 "volume": sum(vols) if all(x is not None for x in vols) else None,
                 "label": buildup_label(near["price_change"], oi_change)}]
    return {
        "symbol": symbol, "mode": "end_of_day", "interval": "1d", "window": 1, "sessions": 1,
        "source": "NSE F&O bhavcopy (nidp.fno_bhavcopy), end of day", "snapshot_at": as_of, "last_bar_at": as_of,
        "contracts": contracts,
        "consolidated": {"slot": "consolidated", "expiries": [f.get("expiry") for f in rows], "windows": cons, "counts": _counts(cons),
                         "basis": "the near month's price change; OI and volume summed over the expiries listed"},
        "missing_slots": [slot for slot in SLOTS[len(rows):]], "missing_note": None,
        "kite_reason": kite_reason, "note": NOTE, "read_only": True,
    }
