"""Trade Desk › Chart Analysis › Live chart, the chart's own read (the owner's design of 28 Oct). Read only.

    GET /api/desk/live-chart/{symbol}?plan_id=&interval=15m&sessions=2

One answer for the chart card and the SIGNAL CONDITIONS card, so the line, the marker and the condition read the same bars:
    timeframe    the candles drawn: Kite 15m (interval, "Kite intraday", raw prices) when the platform Kite session works,
                 else the daily bars (nidp.prices_eod_adjusted) with `reason` (token_missing / token_expired / ...), so the
                 screen says "Kite login needed for 15m candles" and labels the timeframe. Before the exchange's end-of-day
                 file for today is in, today's daily bar comes from Kite (services/kite_live_feed/day_quote.py): the live
                 quote in the session, the saved Kite close after it; `timeframe.today` says which (provisional), and
                 `today_why` why none was added (eod_in, feed_not_live, no_saved_close, does_not_join, ...)
    bars         [[time, o, h, l, c, v]] of the sessions shown, with `ema20` and `rvol` aligned (services/desk_live_chart.py;
                 worked out on extra warm-up bars that are not sent)
    levels       the TradePlan's (?plan_id, Mongo trade_plans, the reader may open it) or, without a plan, the scanner's
                 latest signal (positional_signals): entry, stop, targets, the entry rule, valid_for_sessions, signal day
    signal       the latest scanner signal for the symbol: day, stage, revision, engine version (positional_signals)
    markers      WATCH / READY / CONFIRMED from the scanner's stages by day (positional_signals and _history), and the RVOL
                 bar from the conditions; `markers_error` when the database could not be read (then no marker is drawn)
    conditions   ✓ / waiting / not hit per condition with its value (services/desk_live_chart.conditions)
    paper_engine the reminder that a condition is not a fill: the paper engine fills on end-of-day bars

Requires the `charting` feature flag (the chart routes' flag). Nothing is written; nothing is sent to a broker.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query

from deps import db
from feature_gate import require_feature
from services import desk_live_chart as lc
from services import pg_client
from services.kite_live_feed import config as kite_cfg
from services.kite_live_feed import day_quote as dq
from services.strategy_plan import trade_plan as tpm

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk/live-chart", tags=["desk"])
FLAG = "charting"
SymbolPath = PathParam(..., pattern=r"^[A-Za-z0-9&\-]{1,32}$")
INTERVAL_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "60m": 60}
DAILY_SHOWN = 60                       # daily bars drawn in the fallback
DAILY_READ_DAYS = 200                  # calendar days read for the fallback (EMA warm-up)
WARMUP_SESSIONS = 2                    # extra intraday sessions read for the EMA 20 / RVOL warm-up
SIGNAL_LOOKBACK_DAYS = 45
PAPER_ENGINE = ("A condition met on the chart is not a fill: the paper engine fills on end-of-day bars (break above / pull back "
                "to / at once), and a stop does not cap a loss in a gap.")
KITE_REASON = {
    "token_missing": "Kite login needed for 15m candles: the platform Kite session is not logged in today.",
    "token_expired": "Kite login needed for 15m candles: the platform Kite session expired.",
    "symbol_not_found": "Kite has no intraday instrument for this symbol.",
    "no_bars": "Kite returned no intraday candles for this symbol.",
    "upstream_unavailable": "Kite did not answer for intraday candles.",
}


def _iso_day(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return s[:10] if len(s) >= 10 else None


def levels_from_plan(tp: Dict[str, Any]) -> Dict[str, Any]:
    entry, stop = tp.get("entry") or {}, tp.get("stop") or {}
    targets = [{"name": t.get("name"), "price": t.get("price"), "primary": bool(t.get("primary"))}
               for t in (tp.get("targets") or []) if isinstance(t, dict) and t.get("price") is not None][:2]
    setup = tp.get("setup") or {}
    return {"source": "plan", "plan_id": tp.get("plan_id") or tp.get("_id"), "entry": entry.get("price"), "stop": stop.get("price"),
            "targets": targets, "rule": entry.get("desk_entry_rule"), "valid_for_sessions": entry.get("valid_for_sessions"),
            "reference_close": entry.get("reference_close"), "direction": (tp.get("strategy") or {}).get("direction"),
            "signal_date": _iso_day(setup.get("signal_date")), "invalidation": stop.get("invalidation")}


def levels_from_signal(sig: Optional[Dict[str, Any]], close: Optional[float]) -> Dict[str, Any]:
    if not sig or sig.get("entry") is None:
        return {"source": None, "plan_id": None, "entry": None, "stop": None, "targets": [], "rule": None, "valid_for_sessions": None,
                "reference_close": None, "direction": None, "signal_date": sig.get("signal_date") if sig else None, "invalidation": None}
    order = tpm.order_type_for(float(sig["entry"]), close, stage=sig.get("stage"))
    return {"source": "signal", "plan_id": None, "entry": sig["entry"], "stop": sig.get("stop"),
            "targets": [{"name": "T1", "price": sig["target"], "primary": True}] if sig.get("target") is not None else [],
            "rule": tpm.DESK_ENTRY_RULE.get(order), "valid_for_sessions": None, "reference_close": close, "direction": "long",
            "signal_date": sig.get("signal_date"), "invalidation": None}


async def read_signals(sym: str, since: date) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """The scanner's signals for the symbol since `since` (live rows and superseded revisions), or ([], reason)."""
    try:
        pool = await pg_client.get_pool()
    except Exception as e:  # noqa: BLE001
        logger.warning("live chart: pg pool unavailable (%s)", type(e).__name__)
        pool = None
    if pool is None:
        return [], "the signal database is not reachable"
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT signal_date, stage, COALESCE(revision, 1) AS revision, entry_price, stoploss, target_price, engine_version, computed_at "
                "FROM positional_signals WHERE nse_symbol = $1 AND signal_date >= $2 ORDER BY signal_date", sym, since)
            hist: List[Any] = []
            try:
                hist = await conn.fetch(
                    "SELECT signal_date, stage, COALESCE(revision, 1) AS revision FROM positional_signals_history "
                    "WHERE nse_symbol = $1 AND signal_date >= $2", sym, since)
            except Exception as e:  # noqa: BLE001 — migration 025 not applied: the live rows still answer
                logger.info("live chart: positional_signals_history unreadable (%s)", type(e).__name__)
    except Exception as e:  # noqa: BLE001
        logger.warning("live chart: positional_signals unreadable (%s)", type(e).__name__)
        return [], "the scanner's signals could not be read"
    out = [{"signal_date": _iso_day(r["signal_date"]), "stage": r["stage"], "revision": int(r["revision"]),
            "entry": float(r["entry_price"]) if r["entry_price"] is not None else None,
            "stop": float(r["stoploss"]) if r["stoploss"] is not None else None,
            "target": float(r["target_price"]) if r["target_price"] is not None else None,
            "engine_version": r["engine_version"], "computed_at": r["computed_at"].isoformat() if r["computed_at"] else None, "live": True}
           for r in rows]
    out += [{"signal_date": _iso_day(r["signal_date"]), "stage": r["stage"], "revision": int(r["revision"]), "live": False} for r in hist]
    return out, None


async def read_holidays(start: date, end: date) -> Tuple[Optional[set], bool]:
    """NSE cash holidays in [start, end] from the data platform, and whether they were read."""
    from services.copilot_tools import daas_client
    try:
        status, body = await daas_client.get_raw("/holidays", {"segment": "CM", "from": start.isoformat(), "to": end.isoformat()})
    except Exception as e:  # noqa: BLE001
        logger.warning("live chart: holidays unreadable (%s)", type(e).__name__)
        return None, False
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return None, False
    out = set()
    for r in body["data"]:
        try:
            out.add(date.fromisoformat(str(r.get("holiday_date"))[:10]))
        except (TypeError, ValueError):
            continue
    return out, True


async def read_intraday(sym: str, interval: str, sessions: int, user: dict) -> Dict[str, Any]:
    """The intraday chart route's own read (Kite candles, live price merged into the candle in progress only)."""
    from routes import research_chart_intraday as rci
    return await rci.intraday(symbol=sym, interval=interval, sessions=sessions, user=user)


async def read_daily(sym: str) -> List[list]:
    """Daily bars (split and bonus adjusted), oldest first, through the chart-live route's reader."""
    from routes.move_odds import _proxy
    from routes.research_chart_live import _bar
    start = (date.today() - timedelta(days=DAILY_READ_DAYS)).isoformat()
    payload = await _proxy(f"/prices/adjusted/{sym}", {"limit": 1000, "start": start})
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="upstream_shape")
    return [b for b in (_bar(r) for r in reversed(rows)) if b is not None]


def _now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(kite_cfg.IST)


@router.get("/{symbol}")
async def live_chart(symbol: str = SymbolPath, plan_id: Optional[str] = Query(None, max_length=40),
                     interval: str = Query("15m"), sessions: int = Query(2, ge=1, le=5),
                     user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    if interval not in INTERVAL_MINUTES:
        raise HTTPException(status_code=400, detail=f"interval must be one of {', '.join(INTERVAL_MINUTES)}")
    sym = symbol.upper()
    now = _now_ist()
    plan = None
    if plan_id:
        plan = await tpm.load(db, plan_id, user["user_id"])
        if plan is None:
            raise HTTPException(status_code=404, detail="plan_not_found")
        if str((plan.get("instrument") or {}).get("symbol") or "").upper() != sym:
            raise HTTPException(status_code=400, detail="plan_symbol_mismatch")

    # candles: Kite intraday, else daily with the reason
    reason = None
    bars: List[list] = []
    live_merged = False
    try:
        got = await read_intraday(sym, interval, sessions + WARMUP_SESSIONS, user)
        if got.get("availability") == "ok" and got.get("bars"):
            bars, live_merged = [list(b) for b in got["bars"]], bool(got.get("live_merged"))
        else:
            reason = got.get("availability") or "no_bars"
    except HTTPException as e:
        reason = "upstream_unavailable" if e.status_code >= 500 else "intraday_refused"
    if bars:
        minutes: Optional[int] = INTERVAL_MINUTES[interval]
        keep_days = sorted({b[0][:10] for b in bars})[-sessions:]
        shown_from = next(i for i, b in enumerate(bars) if b[0][:10] in keep_days)
        tf = {"interval": interval, "label": interval.upper(), "source": "Kite intraday", "adjusted": False, "reason": None,
              "live_merged": live_merged, "note": "Kite candles, raw prices (not split or bonus adjusted)."}
    else:
        bars = await read_daily(sym)
        if not bars:
            raise HTTPException(status_code=404, detail="no_bars_for_symbol")
        # today before the exchange's end-of-day file: the live Kite bar in the session, the saved Kite close after it
        bars, today = await dq.extend_daily(bars, sym, now=now)
        minutes = None
        shown_from = max(0, len(bars) - DAILY_SHOWN)
        tf = {"interval": "1d", "label": "DAILY", "source": "nidp.prices_eod_adjusted (end of day)", "adjusted": True,
              "reason": reason, "reason_text": KITE_REASON.get(reason or "", "Intraday candles are unavailable."),
              "live_merged": False, "note": "Daily bars, split and bonus adjusted.",
              "today": today if today.get("used") else None,
              "today_why": None if today.get("used") else today.get("why"), "today_text": today.get("text")}

    ema = lc.ema_series([b[4] for b in bars])
    rvol = lc.rvol_series([b[5] for b in bars])

    signals, signals_error = await read_signals(sym, now.date() - timedelta(days=SIGNAL_LOOKBACK_DAYS))
    live_sigs = [s for s in signals if s.get("live")]
    latest = max(live_sigs, key=lambda s: s["signal_date"]) if live_sigs else None
    last_close = float(bars[-1][4])
    levels = levels_from_plan(plan) if plan else levels_from_signal(latest, last_close)
    if levels.get("signal_date") is None and latest:
        levels["signal_date"] = latest["signal_date"]
    sig_day = date.fromisoformat(levels["signal_date"]) if levels.get("signal_date") else None

    holidays, checked = (None, False)
    if sig_day is not None:
        holidays, checked = await read_holidays(sig_day, now.date() + timedelta(days=30))
    cond = lc.conditions(bars, ema, rvol, levels, minutes=minutes, now=now, tf=tf["label"].lower() if minutes else "daily",
                         signal_day=sig_day, holidays=holidays, holidays_checked=checked)

    shown = bars[shown_from:]
    markers = [] if signals_error else lc.stage_markers([s for s in signals if s.get("signal_date")], shown)
    vb = cond.get("volume_bar")
    if vb and vb["index"] >= shown_from:
        markers.append({"kind": "RVOL", "at": vb["at"], "rvol": vb["rvol"], "text": f"Volume {vb['rvol']:.1f}× the 20-bar average"})
    li = lc.last_completed(bars, minutes, now)
    return {
        "symbol": sym, "as_of": now.isoformat(), "timeframe": tf,
        "bars": shown, "ema20": ema[shown_from:], "rvol": rvol[shown_from:],
        "last": {"price": last_close, "at": bars[-1][0], "bar_complete": li == len(bars) - 1,
                 "source": ((tf.get("today") or {}).get("source") if minutes is None and tf.get("today") else ("kite_intraday" if minutes else "eod"))},
        "levels": levels,
        "signal": ({"signal_date": latest["signal_date"], "stage": latest["stage"], "kind": lc.STAGE_KIND.get(str(latest["stage"] or "").upper()),
                    "revision": latest["revision"], "engine_version": latest["engine_version"], "computed_at": latest["computed_at"]}
                   if latest else None),
        "signals_error": signals_error,
        "markers": markers, "markers_error": signals_error,
        "conditions": cond["conditions"], "evaluated_at_bar": cond["evaluated_at_bar"],
        "valid_until": cond["valid_until"], "sessions_left": cond["sessions_left"],
        "holidays_checked": checked,
        "paper_engine": PAPER_ENGINE, "read_only": True, "sent_to_broker": False,
    }
