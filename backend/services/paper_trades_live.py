"""Live status of today's paper portfolio (Research → Paper), from Yahoo Finance 5-minute bars (~1 min delayed).

The paper engine stores the official record once a day, after the close (NSE bhavcopy). During the session this module
answers one narrower question for the latest frozen selection: on the pre-registered levels (rules_v1 target_stop), has
the secondary target/stop experiment touched its target or its stop yet, and where does each position stand?

  · Entry is the official open of the entry session. Until tonight's run stores it, the first 5-minute bar's open is used
    and every level derived from it is marked provisional.
  · Levels use exactly the engine's formula (nidp.services.tpd_model.paper.sim.levels): stop = entry − k·ATR14, or the
    10-session support when it sits lower, never more than 8% below entry; target = entry × (1 + target%).
  · First touch wins; a bar that touches both counts the stop (the engine's rule). From the second session on, an open
    beyond a level exits at that open.
  · Bars from any other date than the one asked about are never used (Yahoo serves the previous session before the open
    and on holidays): the position is then awaiting the open, not "flat".
  · A symbol Yahoo cannot answer is "unavailable" — never a stale or guessed price.

Nothing here is written anywhere; the official values come from the engine after the close.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Optional

import httpx

from services.move_odds_live import CHART, _get_json

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE = dtime(9, 15), dtime(15, 30)
STOP_CAP = 0.08
BANDS = (0.02, 0.05, 0.10, 0.20)
BAND_TOL = 0.0025
PRICE_EPS = 0.005
TTL = 60.0
CONCURRENCY = 6
_cache: dict[str, tuple[float, Optional[dict]]] = {}


def levels(entry: float, atr: Optional[float], support: Optional[float], k: float, target_pct: float, cap: float = STOP_CAP) -> Optional[dict]:
    """The engine's pre-registered stop and target for one entry (sim.levels, scalar)."""
    if entry is None or atr is None or not entry > 0:
        return None
    stop_atr = entry - k * atr
    use_sup = support is not None and support < entry and support < stop_atr
    stop, method = (support, "SUPPORT") if use_sup else (stop_atr, "ATR")
    floor = entry * (1 - cap)
    if stop < floor:
        stop, method = floor, "CAP_8PCT"
    return {"stop": stop, "stop_method": method, "target": entry * (1 + target_pct / 100.0)}


def bars5(res: Optional[dict], day: date) -> list[dict]:
    """5-minute OHLC bars of `day` only (IST), in time order."""
    if not res:
        return []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        start = datetime.fromtimestamp(ts, IST)
        vals = [(q.get(k) or [])[i] if i < len(q.get(k) or []) else None for k in ("open", "high", "low", "close")]
        if start.date() != day or any(v is None for v in vals):
            continue
        out.append({"start": start, "open": float(vals[0]), "high": float(vals[1]), "low": float(vals[2]), "close": float(vals[3])})
    return out


def first_touch(bars: list[dict], stop: float, target: float, gap_rule: bool) -> Optional[dict]:
    """The first barrier reached in `bars`; a bar touching both counts the stop; with gap_rule an open beyond a level exits there."""
    if gap_rule and bars:
        o = bars[0]["open"]
        if o <= stop:
            return {"kind": "stop", "price": o, "at": bars[0]["start"], "gap": True}
        if o >= target:
            return {"kind": "target", "price": o, "at": bars[0]["start"], "gap": True}
    for b in bars:
        if b["low"] <= stop:
            return {"kind": "stop", "price": stop, "at": b["start"], "gap": False}
        if b["high"] >= target:
            return {"kind": "target", "price": target, "at": b["start"], "gap": False}
    return None


def _upper_circuit_open(bars: list[dict], prev_close: Optional[float]) -> bool:
    if not bars or not prev_close:
        return False
    o, hi = bars[0]["open"], max(b["high"] for b in bars)
    gap = o / prev_close - 1
    return abs(o - hi) < PRICE_EPS and any(abs(gap - b) <= BAND_TOL for b in BANDS)


def position_status(p: dict, cfg: dict, bars: Optional[list[dict]], today: date, now_t: dtime) -> dict:
    """One position's live state. `bars`: today's 5-minute bars, or None when Yahoo did not answer."""
    entry_session = date.fromisoformat(p["intended_entry_date"])
    base = {"trade_id": p["trade_id"], "symbol": p["symbol"], "entry_session": p["intended_entry_date"], "entry": None, "entry_source": None,
            "provisional": False, "stop": None, "target": None, "stop_method": None, "last": None, "return_from_entry": None, "day_high": None,
            "day_low": None, "at": None, "quote_time": None}
    ts_exit = (p.get("exits") or {}).get("TARGET_STOP") or {}
    if p["status"] in ("ENTRY_UNAVAILABLE", "SUSPENDED", "DATA_ERROR", "CANCELLED_BY_RULE"):
        return {**base, "state": "no_entry", "label": "No entry", "note": (p.get("status_reason") or p["status"]).replace("_", " ").lower()}
    if ts_exit.get("state") == "CLOSED":
        kind = "target" if ts_exit.get("target_hit") else "stop" if ts_exit.get("stop_hit") else "horizon"
        return {**base, "entry": p.get("entry_price"), "entry_source": "official", "stop": p.get("stop_loss_price"), "target": p.get("target_1_price")
                if cfg["target_pct"] == 5 else p.get("target_2_price"), "stop_method": p.get("stop_method"), "state": f"exited_{kind}",
                "label": {"target": "Exited · target", "stop": "Exited · stop", "horizon": "Exited · day 5 close"}[kind],
                "note": f"official, {ts_exit.get('exit_date')}"}
    if today < entry_session or (today == entry_session and now_t < OPEN):
        return {**base, "state": "awaiting_open", "label": "Await entry", "note": f"enters at the official open on {entry_session.isoformat()}"}
    if bars is None:
        return {**base, "state": "unavailable", "label": "Unavailable", "note": "live prices unavailable; official values after tonight's run"}
    if not bars:
        return {**base, "state": "awaiting_open", "label": "Await entry", "note": f"no bars yet for {today.isoformat()}"}
    official = p.get("entry_price") is not None
    if official:
        entry = p["entry_price"]
        lv = {"stop": p.get("stop_loss_price"), "target": entry * (1 + cfg["target_pct"] / 100.0), "stop_method": p.get("stop_method")}
    else:
        if today != entry_session:            # entry day passed without an official entry: the engine has not run yet
            return {**base, "state": "unavailable", "label": "Pending", "note": "awaiting tonight's official entry record"}
        if _upper_circuit_open(bars, p.get("prev_close")):
            return {**base, "state": "no_entry", "label": "Await entry", "note": "opened locked at the upper circuit · no fill"}
        entry = bars[0]["open"]
        lv = levels(entry, p.get("atr_14"), p.get("support_level"), cfg["atr_multiplier"], cfg["target_pct"])
        if lv is None:
            return {**base, "state": "unavailable", "label": "Unavailable", "note": "no ATR on record for this stock"}
    last = bars[-1]["close"]
    hit = first_touch(bars, lv["stop"], lv["target"], gap_rule=today > entry_session)
    out = {**base, "entry": round(entry, 2), "entry_source": "official" if official else "yahoo_first_bar", "provisional": not official,
           "stop": round(lv["stop"], 2), "target": round(lv["target"], 2), "stop_method": lv["stop_method"], "last": round(last, 2),
           "return_from_entry": last / entry - 1, "day_high": round(max(b["high"] for b in bars), 2), "day_low": round(min(b["low"] for b in bars), 2),
           "quote_time": bars[-1]["start"].isoformat()}
    if hit:
        at = hit["at"].strftime("%H:%M")
        return {**out, "state": hit["kind"], "at": at, "label": "Exit · target" if hit["kind"] == "target" else "Exit · stop",
                "note": ("opened beyond the level" if hit["gap"] else ("+" if hit["kind"] == "target" else "−")
                         + f"{abs(hit['price'] / entry - 1) * 100:.1f}% touched") + f" at {at}"}
    closed = now_t >= CLOSE
    return {**out, "state": "holding", "label": "Hold", "note": "carry to next session" if closed else "neither level touched yet"}


async def _bars(client: httpx.AsyncClient, sem: asyncio.Semaphore, symbol: str, day: date) -> Optional[list[dict]]:
    hit = _cache.get(f"{symbol}|{day}")
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    async with sem:
        res = await _get_json(client, CHART.format(sym=symbol), {"interval": "5m", "range": "1d"})
    out = bars5(res, day) if res else None
    _cache[f"{symbol}|{day}"] = (time.monotonic(), out)
    return out


async def live_status(portfolio: dict, now: Optional[datetime] = None) -> dict:
    """`portfolio`: the DaaS /v1/paper-trades/portfolio data for the latest forward selection."""
    now = (now or datetime.now(IST)).astimezone(IST)
    today, now_t = now.date(), now.time()
    cfg = portfolio["config"]
    positions = portfolio.get("positions") or []
    need = [p for p in positions if p["status"] not in ("ENTRY_UNAVAILABLE", "SUSPENDED", "DATA_ERROR", "CANCELLED_BY_RULE")
            and date.fromisoformat(p["intended_entry_date"]) <= today and not (date.fromisoformat(p["intended_entry_date"]) == today and now_t < OPEN)]
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=12.0) as client:
        got = await asyncio.gather(*[_bars(client, sem, p["symbol"], today) for p in need])
    bars = {p["symbol"]: b for p, b in zip(need, got)}
    rows = [position_status(p, cfg, bars.get(p["symbol"]), today, now_t) for p in positions]
    counts = {k: sum(1 for r in rows if r["state"] in ks) for k, ks in (("holding", ("holding",)), ("target", ("target", "exited_target")),
                                                                      ("stop", ("stop", "exited_stop")), ("awaiting", ("awaiting_open", "no_entry", "unavailable")))}
    return {"source": "Yahoo Finance 5-minute bars", "delay_note": "delayed up to about a minute", "fetched_at": now.isoformat(),
            "prediction_date": portfolio["prediction_date"], "portfolio": portfolio["portfolio"], "experiment": "TARGET_STOP (secondary, pre-registered levels)",
            "official_note": "Official entries, levels and exits are written after the close from the NSE bhavcopy.", "counts": counts, "positions": rows}
