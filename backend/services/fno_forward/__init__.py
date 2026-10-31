"""Forward test of the one F&O hypothesis the research left standing: near-month short build-up, RECORDED at signal time and judged later.

Rules (test_reports/fno_forward_test_TESTCASES.md): a session's signals are written once when that session's data is in (first write wins; never reconstructed, never
overwritten); entry at the next session's open and exit at the close 5 sessions after the signal, on adjusted prices; outcome = -(stock return - equal-weight universe return) - 0.15%;
no mean or t is shown before 30 sessions have a judged signal. Pure functions: no network, no database (the route and the recorder script do the I/O)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from services.fno_backtest import stats

VERSION = "fno-forward-v1"
HORIZON = 5
COST_PCT = 0.15
MIN_SESSIONS = 30
NW_LAG = HORIZON - 1
MIN_BENCH = 10                      # at least this many universe returns for a benchmark
COLLECTION = "fno_forward_signals"
SETTINGS: Dict[str, Tuple[float, float]] = {"production_floors": (0.5, 3.0), "no_threshold": (0.0, 0.0)}   # |price %| floor, OI % floor
HYPOTHESIS = ("A stock whose near-month future shows price down and open interest up (the contract's own figures) underperforms the F&O universe over the next 5 sessions, "
              "net of an assumed 0.15% round trip. Past tests were inconclusive; this forward test records each signal when it appears and judges it later.")


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def near_state(contracts: Sequence[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """The near-month contract's own price % and OI % (change in OI over its own previous OI); None when either figure is missing, never 0."""
    if not contracts:
        return None
    c = min((x for x in contracts if x.get("expiry")), key=lambda x: x["expiry"], default=None)
    if c is None:
        return None
    p, oi, coi = _num(c.get("change_pct")), _num(c.get("oi")), _num(c.get("change_in_oi"))
    if p is None or oi is None or coi is None or oi - coi <= 0:
        return None
    return {"p": p, "o": coi / (oi - coi) * 100.0}


def fires(state: Dict[str, float], setting: str) -> bool:
    pf, of = SETTINGS[setting]
    return state["p"] < 0 and state["o"] > 0 and abs(state["p"]) >= pf and state["o"] >= of


def build_record(as_of: str, states: Dict[str, Optional[Dict[str, float]]], now: Optional[datetime] = None) -> Dict[str, Any]:
    ok = {s: st for s, st in states.items() if st is not None}
    return {
        "_id": as_of, "as_of": as_of, "recorded_at": (now or datetime.now(timezone.utc)), "version": VERSION,
        "universe_symbols": sorted(states), "with_state": len(ok),
        "settings": {name: [{"symbol": s, "p": round(st["p"], 4), "o": round(st["o"], 4)} for s, st in sorted(ok.items()) if fires(st, name)] for name in SETTINGS},
    }


async def record(db, as_of: str, states: Dict[str, Optional[Dict[str, float]]], now: Optional[datetime] = None) -> bool:
    """Write the session's record once. True when written, False when the session was already recorded (first write wins)."""
    doc = build_record(as_of, states, now)
    res = await db[COLLECTION].update_one({"_id": as_of}, {"$setOnInsert": doc}, upsert=True)
    return res.upserted_id is not None


def _bars(rows: Iterable[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
    out: Dict[str, Tuple[float, float]] = {}
    for r in rows:
        o, c, d = _num(r.get("adj_open")), _num(r.get("adj_close")), str(r.get("as_of_date") or "")[:10]
        if o and c and o > 0 and c > 0 and d:
            out[d] = (o, c)
    return out


def evaluate(docs: Sequence[Dict[str, Any]], bars: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Counts and, once 30 sessions are judged, the pooled result per setting. A session is judged when 5 later sessions exist in the price series."""
    px = {s.upper(): _bars(rows) for s, rows in bars.items()}
    cal = sorted({d for b in px.values() for d in b})
    idx = {d: i for i, d in enumerate(cal)}
    out: Dict[str, Any] = {}
    for name in SETTINGS:
        series: List[float] = []
        recorded = signals = judged_signals = open_sessions = 0
        for doc in sorted(docs, key=lambda d: d["as_of"]):
            sigs = (doc.get("settings") or {}).get(name) or []
            recorded += 1
            signals += len(sigs)
            i = idx.get(doc["as_of"])
            if i is None or i + HORIZON >= len(cal):
                open_sessions += 1
                continue
            entry_day, exit_day = cal[i + 1], cal[i + HORIZON]
            rets: Dict[str, float] = {}
            for s in doc.get("universe_symbols") or []:
                b = px.get(s.upper())
                if b and entry_day in b and exit_day in b:
                    rets[s.upper()] = (b[exit_day][1] / b[entry_day][0] - 1.0) * 100.0
            if len(rets) < MIN_BENCH:
                open_sessions += 1
                continue
            bench = sum(rets.values()) / len(rets)
            vals = [-(rets[x["symbol"].upper()] - bench) - COST_PCT for x in sigs if x["symbol"].upper() in rets]
            if vals:
                series.append(sum(vals) / len(vals))
                judged_signals += len(vals)
        res: Dict[str, Any] = {"recorded_sessions": recorded, "signals_recorded": signals, "judged_sessions": len(series), "judged_signals": judged_signals,
                               "open_sessions": open_sessions, "sessions_needed": max(MIN_SESSIONS - len(series), 0), "mean_pct": None, "t": None}
        if len(series) >= MIN_SESSIONS:
            s = stats.summarize(series, NW_LAG)
            res["mean_pct"], res["t"] = s["mean"], s["t"]
        out[name] = res
    return {"version": VERSION, "horizon_sessions": HORIZON, "cost_pct": COST_PCT, "min_sessions": MIN_SESSIONS, "settings": out}
