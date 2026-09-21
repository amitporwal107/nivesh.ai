"""Live prices and breakout conditions for Research → Move odds (Yahoo Finance chart API, ~1 min delayed).

For each requested symbol: last price, change and day high/low against the previous close, the ±5%/±10% touch levels
and whether today's high/low has reached them, and the five pre-registered breakout conditions evaluated on completed
60-minute bars (.claude/workspace/ten-percent-days-3/evidence/entry_signal/PREREGISTRATION.md). The conditions use
exactly the backtested rule; whether they may be called an entry signal is decided by that test, not here
(ENTRY_SIGNAL_VALIDATED).

Honesty: a symbol Yahoo cannot answer comes back with error "unavailable" (never a stale or guessed price); conditions
are omitted when their inputs are missing; the bar still in progress is never used.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.NS"
SESSION_MINUTES = 375
QUOTE_TTL = 60.0
ADV_TTL = 6 * 3600.0
CONCURRENCY = 8
LEVELS = {"p_up5_1d": 1.05, "p_down5_1d": 0.95, "p_up10_1d": 1.10, "p_down10_1d": 0.90}
# The pre-registered test's decision (.claude/workspace/ten-percent-days-3/evidence/entry_signal/entry_signal_result.json,
# run 2026-09-17 on Jan–Aug 2025 v4 walk-forward predictions with Yahoo 60-minute bars). The five checks concentrate
# +5% touches (23.8% after the checks vs 10.9% unconditional) but buying the breakout lost money: mean −0.61% per
# trade net of 0.10% costs, 95% CI [−0.98%, −0.22%], 84 trades, and fewer than the 100 required. So the checks are
# shown as facts only and never labelled as a signal. These are test statistics, not model estimates.
ENTRY_SIGNAL_VALIDATED = False            # stays False: the test failed. The signal is shown by the owner's decision, with this record.
SIGNAL_RECORD: Optional[dict] = {"window": "Jan–Aug 2025", "candidates": "each session's 10 highest +5% estimates", "trades": 84,
                                 "touch_rate_after_checks": 0.238, "touch_rate_unconditional": 0.109, "mean_net_return": -0.0061,
                                 "ci95_mean_net_return": [-0.0098, -0.0022], "verdict": "failed its pre-registered test; shown at the owner's request"}

_quote_cache: dict[str, tuple[float, dict]] = {}
_adv_cache: dict[tuple[str, date], tuple[float, Optional[float]]] = {}


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def summarise_quote(symbol: str, meta: dict) -> Optional[dict]:
    last, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
    if not last or not prev:
        return None
    hi, lo = meta.get("regularMarketDayHigh"), meta.get("regularMarketDayLow")
    t = meta.get("regularMarketTime")
    qt = datetime.fromtimestamp(t, IST) if t else None
    levels = {h: round(prev * k, 2) for h, k in LEVELS.items()}
    touched = {h: (hi is not None and hi >= lv) if k > 1 else (lo is not None and lo <= lv) for (h, k), lv in zip(LEVELS.items(), levels.values())}
    return {"symbol": symbol, "last": _r(last), "prev_close": _r(prev), "change_pct": (last / prev - 1) * 100,
            "day_high": _r(hi), "day_low": _r(lo), "high_pct": (hi / prev - 1) * 100 if hi else None, "low_pct": (lo / prev - 1) * 100 if lo else None,
            "volume": meta.get("regularMarketVolume"), "quote_time": qt.isoformat() if qt else None,
            "session_date": qt.date().isoformat() if qt else None, "levels": levels, "touched": touched}


def bars_from_chart(res: dict) -> list[dict]:
    """Hourly bars on NSE's :15 grid; drops Yahoo's trailing live-quote point and empty rows."""
    q = (res.get("indicators") or {}).get("quote") or [{}]
    q = q[0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        start = datetime.fromtimestamp(ts, IST)
        vals = [q.get(k, [None])[i] if i < len(q.get(k, [])) else None for k in ("open", "high", "low", "close", "volume")]
        if start.minute != 15 or any(v is None for v in vals[:4]):
            continue
        out.append({"start": start, "open": float(vals[0]), "high": float(vals[1]), "low": float(vals[2]), "close": float(vals[3]), "volume": float(vals[4] or 0)})
    return out


def adv20_from_daily(res: dict, today: date) -> Optional[float]:
    vols = [(datetime.fromtimestamp(ts, IST).date(), v) for ts, v in zip(res.get("timestamp") or [], ((res.get("indicators") or {}).get("quote") or [{}])[0].get("volume") or [])]
    prior = [v for d, v in vols if d < today and v]
    if len(prior) < 10:
        return None
    last = prior[-20:]
    return sum(last) / len(last)


def evaluate_conditions(bars: list[dict], prev_close: float, adv20: Optional[float], now: datetime) -> Optional[dict]:
    """The five pre-registered conditions at each completed hourly bar from the second on. Returns the checks for the
    latest completed bar, the first bar where all five held (the close of that bar is recorded), or None when inputs are missing."""
    if not bars or not prev_close or not adv20:
        return None
    done = [b for b in bars if b["start"] + timedelta(minutes=60) <= now]
    if not done:
        return None
    level = prev_close * 1.05
    first_high = done[0]["high"]
    cum_pv = cum_v = 0.0
    run_high = float("-inf")
    latest = at_first = None
    first_met = entry = None
    run_since = run_close = None                 # the current unbroken run of bars where all five hold
    for i, b in enumerate(done):
        tp = (b["high"] + b["low"] + b["close"]) / 3
        cum_pv += tp * b["volume"]; cum_v += b["volume"]
        run_high = max(run_high, b["high"])
        if i == 0:
            continue
        elapsed = min((b["start"] + timedelta(minutes=60) - done[0]["start"]).total_seconds() / 60, SESSION_MINUTES)
        vwap = cum_pv / cum_v if cum_v else None
        checks = {"above_prev_close": b["close"] > prev_close, "above_opening_range": b["close"] > first_high,
                  "above_vwap": vwap is not None and b["close"] > vwap, "room_to_level": run_high < level,
                  "volume_pace": cum_v >= adv20 * elapsed / SESSION_MINUTES}
        latest = {**checks, "bar": f"{b['start']:%H:%M}-{b['start'] + timedelta(minutes=60):%H:%M}", "close": round(b["close"], 2),
                  "vwap": round(vwap, 2) if vwap else None, "opening_range_high": round(first_high, 2), "cum_volume": int(cum_v),
                  "volume_needed": int(adv20 * elapsed / SESSION_MINUTES), "met": sum(checks.values())}
        if all(checks.values()):
            if first_met is None:
                first_met, entry, at_first = latest["bar"], round(b["close"], 2), dict(latest)
            if run_since is None:
                run_since, run_close = latest["bar"], round(b["close"], 2)
        else:
            run_since = run_close = None
    # Entry signal (user decision 2026-09-17, decisions-log.md): ON while all five checks hold at the latest completed
    # hourly bar; "since" is the first bar of the current unbroken run. The rule failed its pre-registered 2025 test
    # (SIGNAL_RECORD) and the page must say so beside every signal.
    return {"evaluated_bars": len(done), "latest": latest, "first_met_at": first_met, "close_at_first_met": entry, "at_first_met": at_first,
            "entry_signal": run_since is not None, "entry_signal_since": run_since, "close_at_signal_start": run_close}


# ── Paper trade on the early signal (user 2026-09-17: "for early signal I enter a false 1000 quantity and sell at 5-10%
# rise intraday… just give an indicator"). Entry: 1,000 shares at the close of the first bar where all five checks held.
# Exit: the first 5-minute bar after entry whose high reaches +5% (or +10%) from entry, filled at that level; otherwise
# marked at the latest price, which after 15:30 is the day's close. Charges are an estimate for discount-broker intraday.
PAPER_QTY = 1000
PAPER_EXITS = (0.05, 0.10)
SESSION_CLOSE = (15, 30)


def intraday_charges(buy: float, sell: float, qty: int = PAPER_QTY) -> float:
    tb, ts = buy * qty, sell * qty
    brokerage = min(20.0, 0.0003 * tb) + min(20.0, 0.0003 * ts)
    txn = 0.0000297 * (tb + ts)
    sebi = 10 / 1e7 * (tb + ts)
    return round(brokerage + 0.00025 * ts + txn + sebi + 0.00003 * tb + 0.18 * (brokerage + txn + sebi), 2)


def bars5_from_chart(res: dict) -> list[dict]:
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        hi = (q.get("high") or [None] * (i + 1))[i] if i < len(q.get("high") or []) else None
        if hi is None:
            continue
        out.append({"start": datetime.fromtimestamp(ts, IST), "high": float(hi)})
    return out


def paper_trade(conditions: Optional[dict], bars5: list[dict], last: float, now: datetime) -> Optional[dict]:
    """None unless an early signal fired on a bar that ends before the close."""
    if not conditions or not conditions.get("first_met_at") or last is None:
        return None
    start_s, end_s = conditions["first_met_at"].split("-")
    if start_s >= "15:15":
        return None
    local = now.astimezone(IST)
    entry_time = local.replace(hour=int(end_s[:2]), minute=int(end_s[3:]), second=0, microsecond=0)
    entry = float(conditions["close_at_first_met"])
    closed = (local.hour, local.minute) >= SESSION_CLOSE
    exits = []
    for pct in PAPER_EXITS:
        level = round(entry * (1 + pct), 2)
        hit = next((b for b in bars5 if b["start"] >= entry_time and b["high"] >= level), None)
        price = level if hit else round(float(last), 2)
        gross = round((price - entry) * PAPER_QTY, 2)
        cost = intraday_charges(entry, price)
        exits.append({"pct": int(round(pct * 100)), "level": level, "reached": hit is not None, "at": hit["start"].strftime("%H:%M") if hit else None,
                      "price": price, "state": "exited" if hit else ("closed at day end" if closed else "open"),
                      "gross": gross, "charges": cost, "net": round(gross - cost, 2)})
    return {"qty": PAPER_QTY, "entry_price": round(entry, 2), "entry_time": end_s, "exits": exits, "marked_at": local.strftime("%H:%M")}


async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> Optional[dict]:
    try:
        r = await client.get(url, params=params, headers={"User-Agent": UA, "Accept": "application/json"})
        if r.status_code != 200:
            return None
        res = (r.json().get("chart") or {}).get("result") or []
        return res[0] if res else None
    except (httpx.HTTPError, ValueError):
        return None


async def _one(client: httpx.AsyncClient, sem: asyncio.Semaphore, symbol: str, now: datetime) -> dict:
    hit = _quote_cache.get(symbol)
    if hit and time.monotonic() - hit[0] < QUOTE_TTL:
        return hit[1]
    async with sem:
        intraday = await _get_json(client, CHART.format(sym=symbol), {"interval": "60m", "range": "1d"})
        q = summarise_quote(symbol, (intraday or {}).get("meta") or {}) if intraday else None
        if q is None:
            return {"symbol": symbol, "error": "unavailable"}
        today = now.astimezone(IST).date()
        adv_hit = _adv_cache.get((symbol, today))
        if adv_hit and time.monotonic() - adv_hit[0] < ADV_TTL:
            adv20 = adv_hit[1]
        else:
            daily = await _get_json(client, CHART.format(sym=symbol), {"interval": "1d", "range": "3mo"})
            adv20 = adv20_from_daily(daily, today) if daily else None
            _adv_cache[(symbol, today)] = (time.monotonic(), adv20)
    q["conditions"] = evaluate_conditions(bars_from_chart(intraday), q["prev_close"], adv20, now) if q["session_date"] == now.astimezone(IST).date().isoformat() else None
    q["paper"] = None
    if q["conditions"] and q["conditions"].get("first_met_at"):
        m5 = await _get_json(client, CHART.format(sym=symbol), {"interval": "5m", "range": "1d"})
        q["paper"] = paper_trade(q["conditions"], bars5_from_chart(m5) if m5 else [], q["last"], now)
    q["error"] = None
    _quote_cache[symbol] = (time.monotonic(), q)
    return q


async def live_quotes(symbols: list[str], now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(IST)
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=12.0) as client:
        quotes = await asyncio.gather(*[_one(client, sem, s, now) for s in symbols])
    return {"source": "Yahoo Finance", "delay_note": "delayed up to about a minute", "fetched_at": now.isoformat(),
            "entry_signal_validated": ENTRY_SIGNAL_VALIDATED, "signal_record": SIGNAL_RECORD, "quotes": quotes}
