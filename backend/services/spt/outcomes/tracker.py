"""Signal outcome tracker `spt-outcome-v1` (constants.OUTCOME_VERSION; PRD §13.1, §14.3; Workflow §17.1, §24).

For every outcome-eligible scanner event (spt_signal_events.outcome_eligible: a valid symbol, price and time — a signal
received late is still a real observation) and, separately, every strong signal, from NSE end-of-day bars
(desk_trading.fetch_bars through opportunities/inputs.MarketInputs; raw traded prices):

    forward      T+0 (the detection day's close) and T+1 / T+5 / T+10 / T+20 = the close of the Nth session after the
                 detection day, as a return from the detection price, in the signal's own direction (`return_pct`; a
                 short signal gains when the price falls) and raw (`raw_return_pct`). MFE / MAE over sessions 1..N: the
                 most favourable and most adverse session high / low against the detection price, in the signal's
                 direction. The detection day's own high and low are left out: daily bars cannot say whether they came
                 before or after the detection.
    series break a close-to-close ratio outside exit_watch.rules BREAK_LOW / BREAK_HIGH after the detection (a bonus or a
                 split: the bars are not adjusted) ends the measurement: that horizon and later ones are
                 {status: "series_break", day} with null values, never a fake −50 %.
    fade         strong signals: the day's scores doc at its last save (scan_builder.signals.load_scores, the evening's
                 copy) has the stock below 70 → faded. List marks keep `score_at_close` when the doc has it. No doc
                 (Redis keeps 3 days) → null with the reason.
    plan         strong signals only, the hypothetical scan-plan-v3 trade from its frozen levels. The stop is judged on
                 daily closes (scan-plan-v3's own rule, signal_strength.PLAN_TEXT): a close below the stop exits at that
                 close, also on the detection day. Targets on the session high, from the first session after the
                 detection (exit at the target, or at the open when it gaps above). Trend exit: a close below the
                 20-session average of the closes to that day. A session that reaches a target and closes below the
                 stop counts as the stop (conservative). First event ∈ stop | target_1 | target_2 | trend_exit |
                 time_exit (MAX_HOLD sessions) | open (not decided yet); every level's first day is kept in `hits`;
                 the walk ends at the stop, T2 or the trend exit.
    association  the opportunities the signal is in (spt_opportunities.signals.signal_id)

Stored in `spt_signal_outcomes` with `_id` = the signal id, recomputed each evening until `complete` (T+20 known, or the
series broke). Paper trades are never read or written here: signal performance and trade performance stay apart.

Evening run (`evening`, called by the SPT loop out of session): weekdays from EVENING_FROM (19:30 IST), only once NSE's
end-of-day file for the day is in the bars (a liquid reference symbol has a bar dated today), at most MAX_PER_ROUND events a
round, newest days first; `spt_state` {_id: "spt_a_outcomes"} records the day it finished.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from services.exit_watch import rules

from .. import constants as C
from ..opportunities import inputs as inputs_mod
from ..opportunities import store as opp_store
from ..opportunities.validate import cut_at_breaks
from ..signals import clock
from ..signals import store as sig_store

logger = logging.getLogger(__name__)

COLL = C.SIGNAL_OUTCOMES
VERSION = C.OUTCOME_VERSION
HORIZONS = (1, 5, 10, 20)
MAX_HOLD = 20
STRONG_MIN = 70
TRACK_SESSIONS = 32                 # detection days still measured (T+20 plus slack for holidays)
EVENING_FROM = dtime(19, 30)
MAX_PER_ROUND = 3000
REFERENCE_SYMBOL = "RELIANCE"
STATE_ID = "spt_a_outcomes"
LIGHT = {"supporting_metrics": 0, "explanations": 0, "source": 0}     # the evening's read of a day's events


def _r(v: Optional[float], dp: int = 2) -> Optional[float]:
    return None if v is None or not math.isfinite(v) else round(v, dp)


def _d(b: Dict[str, Any]) -> date:
    d = b["date"]
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _split(bars: List[Dict[str, Any]], det_day: date):
    clean = rules.clean_bars(bars)
    day0 = next((b for b in clean if _d(b) == det_day), None)
    before = [b for b in clean if _d(b) <= det_day]
    after = [b for b in clean if _d(b) > det_day]
    return clean, day0, before, after


def _break_index(day0: Optional[Dict[str, Any]], prev: Optional[Dict[str, Any]], after: List[Dict[str, Any]]) -> Optional[int]:
    """Index into `after` of the first session whose close jumps against the session before (a bonus/split); -1 when the
    detection day itself jumped against the session before it; None when no break."""
    if day0 is not None and prev is not None:
        r = float(day0["close"]) / float(prev["close"])
        if r < rules.BREAK_LOW or r > rules.BREAK_HIGH:
            return -1
    last = day0 or prev
    for i, b in enumerate(after):
        if last is not None:
            r = float(b["close"]) / float(last["close"])
            if r < rules.BREAK_LOW or r > rules.BREAK_HIGH:
                return i
        last = b
    return None


def forward(bars: List[Dict[str, Any]], *, det_day: date, price: float, direction: str) -> Dict[str, Any]:
    """{t0, t1, t5, t10, t20, complete, bars_through} (see the module docstring)."""
    clean, day0, before, after = _split(bars, det_day)
    prev = before[-2] if day0 is not None and len(before) >= 2 else (before[-1] if day0 is None and before else None)
    brk = _break_index(day0, prev, after)
    sign = 1.0 if direction == "long" else -1.0
    out: Dict[str, Any] = {"bars_through": _d(clean[-1]).isoformat() if clean else None}

    def ret(c: float) -> Dict[str, Optional[float]]:
        raw = (c / price - 1.0) * 100.0
        return {"return_pct": _r(sign * raw), "raw_return_pct": _r(raw)}

    if brk == -1:
        out["t0"] = {"status": "series_break", "day": det_day.isoformat()}
    elif day0 is None:
        out["t0"] = {"status": "no_bar", "day": det_day.isoformat()}
    else:
        out["t0"] = {"status": "done", "day": det_day.isoformat(), "close": _r(float(day0["close"])),
                     **ret(float(day0["close"]))}
    for k in HORIZONS:
        key = f"t{k}"
        if brk is not None and (brk == -1 or brk < k):
            bd = det_day.isoformat() if brk == -1 else _d(after[brk]).isoformat()
            out[key] = {"status": "series_break", "day": bd, "return_pct": None, "raw_return_pct": None,
                        "mfe_pct": None, "mae_pct": None}
            continue
        if len(after) < k:
            out[key] = {"status": "pending", "sessions_known": len(after)}
            continue
        win = after[:k]
        c = float(win[-1]["close"])
        highs = [_num(b.get("high")) or float(b["close"]) for b in win]
        lows = [_num(b.get("low")) or float(b["close"]) for b in win]
        if direction == "long":
            mfe, mae = (max(highs) / price - 1) * 100, (min(lows) / price - 1) * 100
        else:
            mfe, mae = (1 - min(lows) / price) * 100, (1 - max(highs) / price) * 100
        out[key] = {"status": "done", "day": _d(win[-1]).isoformat(), "close": _r(c), **ret(c), "mfe_pct": _r(mfe),
                    "mae_pct": _r(mae)}
    last = out[f"t{HORIZONS[-1]}"]["status"]
    out["complete"] = last in ("done", "series_break")
    return out


def plan_outcome(bars: List[Dict[str, Any]], *, det_day: date, plan: Dict[str, Any]) -> Dict[str, Any]:
    """The hypothetical scan-plan-v3 trade of a strong signal (see the module docstring)."""
    entry, stop = _num(plan.get("entry")), _num(plan.get("stop_loss"))
    t1, t2 = _num(plan.get("target_1")), _num(plan.get("target_2"))
    out: Dict[str, Any] = {"rules": plan.get("rules") or "scan-plan-v3", "entry": entry, "stop_loss": stop,
                           "target_1": t1, "target_2": t2, "first_event": None, "first_event_day": None,
                           "exit_price": None, "r_multiple": None, "conservative_same_bar": False, "gap_open": False,
                           "hits": {"stop": None, "target_1": None, "target_2": None, "trend_exit": None},
                           "sessions_checked": 0, "complete": False}
    if not plan.get("plan_ok") or None in (entry, stop, t1, t2) or entry <= stop:
        out["first_event"] = "no_plan"
        out["complete"] = True
        return out
    risk = entry - stop
    clean, day0, before, after = _split(bars, det_day)
    prev = before[-2] if day0 is not None and len(before) >= 2 else (before[-1] if day0 is None and before else None)
    brk = _break_index(day0, prev, after)
    hits = out["hits"]

    def first(event: str, day: date, px: float) -> None:
        if out["first_event"] is None:
            out.update(first_event=event, first_event_day=day.isoformat(), exit_price=_r(px), r_multiple=_r((px - entry) / risk))

    closes_hist = [float(b["close"]) for b in cut_at_breaks(before)[0]]       # the 20-session average never spans a bonus
    if brk == -1:
        out.update(first_event="series_break", first_event_day=det_day.isoformat(), complete=True)
        return out
    if day0 is not None and float(day0["close"]) < stop:                   # the detection day's close is after the signal
        hits["stop"] = det_day.isoformat()
        first("stop", det_day, float(day0["close"]))
        out["complete"] = True
        return out
    ended = False
    for i, b in enumerate(after[:MAX_HOLD]):
        if brk is not None and i >= brk:
            if out["first_event"] is None:
                out.update(first_event="series_break", first_event_day=_d(b).isoformat())
            ended = True
            break
        day = _d(b)
        o = _num(b.get("open")) or float(b["close"])
        h = _num(b.get("high")) or float(b["close"])
        c = float(b["close"])
        closes_hist.append(c)
        out["sessions_checked"] = i + 1
        if o < stop:
            out["gap_open"] = True
        if c < stop:
            if h >= t1 and hits["target_1"] is None:
                out["conservative_same_bar"] = True
            hits["stop"] = day.isoformat()
            first("stop", day, c)
            ended = True
            break
        if h >= t1 and hits["target_1"] is None:
            hits["target_1"] = day.isoformat()
            first("target_1", day, o if o >= t1 else t1)
        if h >= t2:
            hits["target_2"] = day.isoformat()
            first("target_2", day, o if o >= t2 else t2)
            ended = True
            break
        if len(closes_hist) >= 20 and c < sum(closes_hist[-20:]) / 20:
            hits["trend_exit"] = day.isoformat()
            first("trend_exit", day, c)
            ended = True
            break
    if not ended and len(after) >= MAX_HOLD:
        last = after[MAX_HOLD - 1]
        if out["first_event"] is None:
            first("time_exit", _d(last), float(last["close"]))
        ended = True
    if out["first_event"] is None:
        out["first_event"] = "open"
    out["complete"] = ended
    return out


def fade(kind: str, symbol: str, scores_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not scores_doc or not scores_doc.get("scores"):
        return {"faded": None, "score_at_close": None, "scores_as_of": None,
                "reason": "the day's scores doc was not available when the outcome was computed"}
    rec = (scores_doc.get("scores") or {}).get(symbol) or {}
    sc = rec.get("score")
    if not isinstance(sc, (int, float)) or isinstance(sc, bool):
        return {"faded": None, "score_at_close": None, "scores_as_of": scores_doc.get("as_of"),
                "reason": rec.get("note") or "the stock is not in the day's scores doc"}
    return {"faded": (sc < STRONG_MIN) if kind == "strong" else None, "score_at_close": sc,
            "scores_as_of": scores_doc.get("as_of"), "reason": None}


def outcome_doc(ev: Dict[str, Any], bars_read: Dict[str, Any], *, now: datetime, opportunity_ids: Sequence[str],
                fade_rec: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    det = clock.parse_ts(ev["detected_at"])
    det_day = clock.ist_day(det)
    fw = forward(bars_read.get("bars") or [], det_day=det_day, price=float(ev["detected_price"]),
                 direction=ev.get("direction") or "long")
    plan = None
    if ev.get("kind") == "strong":
        raw = ev.get("supporting_metrics") or {}
        plan = plan_outcome(bars_read.get("bars") or [], det_day=det_day, plan=raw)
    return {"_id": ev["signal_id"], "signal_id": ev["signal_id"], "kind": ev.get("kind"), "scanner_id": ev.get("scanner_id"),
            "category": ev.get("category"), "family": ev.get("family"), "horizon": ev.get("horizon"),
            "direction": ev.get("direction"), "symbol": ev.get("symbol"), "day": ev.get("day"),
            "detected_at": ev.get("detected_at"), "detected_price": ev.get("detected_price"),
            "scanner_score": ev.get("scanner_score"), "score_version": ev.get("score_version"),
            "signal_status": ev.get("status"), "opportunity_ids": list(opportunity_ids),
            "forward": {k: fw[k] for k in ("t0", "t1", "t5", "t10", "t20")}, "plan": plan,
            "fade": fade_rec, "bars_through": fw["bars_through"], "bars_source": bars_read.get("source"),
            "bars_read_at": bars_read.get("read_at"),
            "complete": bool(fw["complete"] and (plan is None or plan.get("complete"))),
            "market_regime": None, "market_regime_note": "not recorded at detection tonight",
            "version": VERSION, "computed_at": clock.utc_iso(now)}


async def _opps_of(db, ids: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for i in range(0, len(ids), 500):
        docs = await db[opp_store.COLL].find({"signals.signal_id": {"$in": ids[i:i + 500]}}).to_list(length=None)
        want = set(ids[i:i + 500])
        for d in docs:
            for s in d.get("signals") or []:
                if s.get("signal_id") in want:
                    out.setdefault(s["signal_id"], []).append(d["_id"])
    return out


async def compute(db, *, now: datetime, inputs: inputs_mod.MarketInputs, days: Sequence[str],
                  scores_docs: Optional[Dict[str, Dict[str, Any]]] = None, limit: int = MAX_PER_ROUND,
                  through: Optional[str] = None) -> Dict[str, int]:
    """(Re)compute the outcomes of the outcome-eligible events of `days` that are not complete and not yet computed
    through `through` (default: today IST), newest day first, at most `limit`; bars are read once per symbol for all its
    events. Returns counts."""
    through = through or clock.ist_day(now).isoformat()
    counts = {"events": 0, "computed": 0, "complete": 0, "skipped": 0, "bars_errors": 0, "remaining": 0}
    budget = max(0, int(limit))
    todo: List[Dict[str, Any]] = []
    prev: Dict[str, Dict[str, Any]] = {}
    for day in sorted(days, reverse=True):
        evs = [e for e in await db[sig_store.COLL].find({"day": day, "outcome_eligible": True}, LIGHT).to_list(length=None)
               if e.get("detected_price") and e.get("detected_at")]
        if not evs:
            continue
        have = {d["_id"]: d for d in await db[COLL].find({"day": day}, {"complete": 1, "bars_through": 1, "fade": 1})
                .to_list(length=None)}
        need = [e for e in evs if not (have.get(e["signal_id"], {}).get("complete")
                                       or (have.get(e["signal_id"], {}).get("bars_through") or "") >= through)]
        counts["events"] += len(evs)
        counts["skipped"] += len(evs) - len(need)
        if len(need) > budget:
            counts["remaining"] += len(need) - budget
            need = need[:budget]
        budget -= len(need)
        todo.extend(need)
        prev.update({e["signal_id"]: have.get(e["signal_id"]) or {} for e in need})
    if not todo:
        return counts
    for e in todo:
        if e.get("kind") == "strong" and "supporting_metrics" not in e:           # the plan is in the raw record
            full = await sig_store.get(db, e["signal_id"]) or {}
            e["supporting_metrics"] = full.get("supporting_metrics") or {}
    opps = await _opps_of(db, [e["signal_id"] for e in todo])
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for e in todo:
        by_symbol.setdefault(e["symbol"], []).append(e)
    for sym, evs in by_symbol.items():
        got = await inputs.bars(sym, now)
        if got.get("error"):
            counts["bars_errors"] += len(evs)
            continue
        for ev in evs:
            sdoc = (scores_docs or {}).get(ev["day"])
            fd = (fade(ev.get("kind"), sym, sdoc) if sdoc
                  else prev[ev["signal_id"]].get("fade") or fade(ev.get("kind"), sym, None))
            doc = outcome_doc(ev, got, now=now, opportunity_ids=opps.get(ev["signal_id"], []), fade_rec=fd)
            await db[COLL].update_one({"_id": doc["_id"]}, {"$set": {k: v for k, v in doc.items() if k != "_id"}},
                                      upsert=True)
            counts["computed"] += 1
            counts["complete"] += 1 if doc["complete"] else 0
    return counts


def tracked_days(now: datetime, sessions: int = TRACK_SESSIONS) -> List[str]:
    today = clock.ist_day(now)
    out, d = [today.isoformat()], today
    while len(out) < sessions + 1:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out


async def evening(db, *, now: datetime, inputs: inputs_mod.MarketInputs, scan_store: Any = None,
                  limit: int = MAX_PER_ROUND) -> Dict[str, Any]:
    """The loop's evening step (see the module docstring). Returns {skipped: why} or the compute counts."""
    ist = now.astimezone(clock.IST)
    today = ist.date().isoformat()
    if ist.weekday() >= 5 or ist.time() < EVENING_FROM:
        return {"skipped": "not_evening"}
    st = await db[C.STATE].find_one({"_id": STATE_ID}) or {}
    if st.get("done_day") == today:
        return {"skipped": "done"}
    if st.get("bars_day") != today:
        inputs.forget()                                     # bars cached before NSE's file must be read again
        ref = await inputs.bars(REFERENCE_SYMBOL, now)
        last = (ref.get("bars") or [{}])[-1].get("date") if ref.get("bars") else None
        if last is None or str(last)[:10] < today:
            return {"skipped": "nse_file_not_in", "reference_last_bar": str(last)[:10] if last else None}
        await db[C.STATE].update_one({"_id": STATE_ID}, {"$set": {"bars_day": today}}, upsert=True)
    scores_docs: Dict[str, Dict[str, Any]] = {}
    try:
        from services.scan_builder import signals as SIG
        doc = await SIG.load_scores(today, store=scan_store)
        if doc.get("scores"):
            scores_docs[today] = doc
    except Exception as e:  # noqa: BLE001 — fade stays null with its reason
        logger.warning("spt outcomes: the day's scores could not be read (%s)", type(e).__name__)
    counts = await compute(db, now=now, inputs=inputs, days=tracked_days(now), scores_docs=scores_docs, limit=limit,
                           through=today)
    if counts["remaining"] == 0 and counts["bars_errors"] == 0:
        await db[C.STATE].update_one({"_id": STATE_ID}, {"$set": {"done_day": today, "at": clock.utc_iso(now),
                                                                   "counts": counts}}, upsert=True)
    return counts
