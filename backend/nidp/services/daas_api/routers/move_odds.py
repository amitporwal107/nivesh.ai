"""Move odds — published Ten-Percent Days estimates for the Research page (migration 149, tpd_model.publish).

    GET /v1/move-odds/latest?head=p_up5_1d&model=v4   the scored list for the session the estimates apply to
    GET /v1/move-odds/stocks/{symbol}?model=v4        one stock: all four estimates, inputs on record, events on record
    GET /v1/move-odds/history?head=&model=v4          past published sessions: what was estimated and how it turned out

Internal-plan keys only: the app is the one caller, and it gates end users with the move_odds allowlist flag.

Honesty rules enforced here (spec C4, C7, D2):
  * The session the estimates apply to is decided from the clock and the NSE cash-market calendar. If the latest
    published run is for an earlier session, the answer is status not_published with no rows — an older run's numbers
    are never served for a later session.
  * A refusal recorded for that session (incomplete data) answers 503 withheld, again with no rows — unless a later
    retry published a run for that session, which is then served.
  * Numbers are exactly the frozen ones; rows are sorted by estimate and carry no rank.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse

import nidp.shared.storage.pg as pg
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import normalise_symbol

IST = timezone(timedelta(hours=5, minutes=30))
CLOSE = time(15, 30)
Head = Literal["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"]
Model = Literal["v4"]
OPPOSITE = {"p_up5_1d": "p_down5_1d", "p_down5_1d": "p_up5_1d", "p_up10_1d": "p_down10_1d", "p_down10_1d": "p_up10_1d"}
NOT_USED = ["intraday prices", "analyst estimates", "F&O positioning history", "filing and news text (events are listed for context only)"]


def require_internal_plan(request: Request, _key=Depends(require_api_key)) -> None:
    rec = getattr(request.state, "daas_key", None)
    if rec is None or rec.plan != "internal":
        raise HTTPException(status_code=403, detail="move-odds is available to internal keys only")


router = APIRouter(prefix="/move-odds", tags=["move_odds"], dependencies=[Depends(require_internal_plan)])


def _now() -> datetime:
    return datetime.now(IST)


def expected_session(now: datetime, holidays: set[date]) -> date:
    """Before 15:30 on a trading day: that day's session. Otherwise: the next trading day."""
    local = now.astimezone(IST)
    def trading(d: date) -> bool:
        return d.weekday() < 5 and d not in holidays
    d = local.date()
    if trading(d) and local.time() < CLOSE:
        return d
    d += timedelta(days=1)
    while not trading(d):
        d += timedelta(days=1)
    return d


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _run_public(run) -> Dict[str, Any]:
    keys = ("model", "refit", "status", "data_as_of", "target_session", "frozen_at", "git_sha", "universe_size", "scored", "input_count",
            "train_rows", "train_end", "counts_toward_verdict")
    out = {k: _iso(run[k]) for k in keys}
    out["git_sha"] = (run["git_sha"] or "")[:7]
    out["skipped_holidays"] = [_iso(d) for d in (run["skipped_holidays"] or [])]
    return out


async def _resolve(conn, model: str) -> tuple[Optional[Any], date, Optional[Any]]:
    now = _now()
    hol = await conn.fetch("SELECT DISTINCT holiday_date FROM nidp.nse_holidays WHERE segment = 'CM' AND holiday_date BETWEEN $1 AND $2",
                           now.date(), now.date() + timedelta(days=21))
    expected = expected_session(now, {r["holiday_date"] for r in hol})
    refusal = await conn.fetchrow("SELECT reason, detail, recorded_at FROM nidp.tpd_run_refusals WHERE model = $1 AND target_session = $2 "
                                  "ORDER BY recorded_at DESC LIMIT 1", model, expected)
    run = await conn.fetchrow("SELECT * FROM nidp.tpd_runs WHERE model = $1 AND status = 'final' AND counts_toward_verdict AND target_session <= $2 "
                              "ORDER BY target_session DESC, published_at DESC LIMIT 1", model, expected)
    return run, expected, refusal


def _withheld(expected: date, refusal) -> JSONResponse:
    """503 with a structured body (returned, not raised: the app's HTTPException handler flattens dict details)."""
    detail = refusal["detail"]
    if isinstance(detail, str):
        detail = json.loads(detail or "{}")
    return JSONResponse(status_code=503, content={"data": {"status": "withheld", "target_session": expected.isoformat(), "reason": refusal["reason"],
                                                           "detail": detail, "recorded_at": _iso(refusal["recorded_at"])}})


@router.get("/latest", summary="Published estimates for the session they apply to")
async def latest(head: Head = Query("p_up5_1d"), model: Model = Query("v4")):
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        run, expected, refusal = await _resolve(conn, model)
        current = run is not None and run["target_session"] == expected
        if refusal is not None and not current:          # a later successful retry outranks an earlier refusal
            return _withheld(expected, refusal)
        if not current:
            return {"data": {"status": "not_published", "head": head, "expected_session": expected.isoformat(),
                             "last_published_for": _iso(run["target_session"]) if run is not None else None, "rows": []}}
        rows = await conn.fetch(
            """
            SELECT e.symbol, s.company_name, s.sector, e.p, o.p AS p_opposite, e.p_base_rate, COALESCE(ev.n, 0) AS events_on_record
              FROM nidp.tpd_run_estimates e
              LEFT JOIN nidp.tpd_run_estimates o ON o.run_id = e.run_id AND o.symbol = e.symbol AND o.head = $3
              LEFT JOIN nidp.tpd_run_stocks s ON s.run_id = e.run_id AND s.symbol = e.symbol
              LEFT JOIN (SELECT symbol, COUNT(*) AS n FROM nidp.tpd_run_events WHERE run_id = $1 GROUP BY symbol) ev ON ev.symbol = e.symbol
             WHERE e.run_id = $1 AND e.head = $2
             ORDER BY e.p DESC, e.symbol
            """, run["run_id"], head, OPPOSITE[head])
        bands = await conn.fetch("SELECT band_lo, band_hi, rows, realised FROM nidp.tpd_band_record WHERE model = $1 AND head = $2 AND source = 'test_2025' "
                                 "ORDER BY band_lo", model, head)
        record = await conn.fetchrow("SELECT window_label, sessions, base_rate, top10_hit_rate FROM nidp.tpd_model_record WHERE model = $1 AND head = $2 "
                                     "AND source = 'test_2025'", model, head)
        live = await conn.fetchrow(
            """
            SELECT COUNT(*) AS sessions, SUM(g.top10_hits) AS top10_hits, SUM(g.touched) AS touched, SUM(g.graded_rows) AS graded_rows,
                   (ARRAY_AGG(r.target_session ORDER BY r.target_session DESC))[1] AS last_target,
                   (ARRAY_AGG(g.top10_hits ORDER BY r.target_session DESC))[1] AS last_top10_hits,
                   (ARRAY_AGG(g.touched ORDER BY r.target_session DESC))[1] AS last_touched,
                   (ARRAY_AGG(g.graded_rows ORDER BY r.target_session DESC))[1] AS last_graded_rows
              FROM nidp.tpd_run_grades g JOIN nidp.tpd_runs r ON r.run_id = g.run_id
             WHERE r.model = $1 AND g.head = $2 AND r.counts_toward_verdict
            """, model, head)
    base = float(rows[0]["p_base_rate"]) if rows else None
    return {"data": {
        "status": "final", "head": head, "expected_session": expected.isoformat(), "base_rate": base, "run": _run_public(run),
        "rows": [{"symbol": r["symbol"], "company_name": r["company_name"], "sector": r["sector"], "p": float(r["p"]),
                  "p_opposite": float(r["p_opposite"]) if r["p_opposite"] is not None else None, "events_on_record": int(r["events_on_record"])} for r in rows],
        "record": ({"window_label": record["window_label"], "sessions": int(record["sessions"]), "base_rate": float(record["base_rate"]),
                    "top10_hit_rate": float(record["top10_hit_rate"]),
                    "bands": [{"band_lo": float(b["band_lo"]), "band_hi": float(b["band_hi"]), "rows": int(b["rows"]),
                               "realised": float(b["realised"]) if b["realised"] is not None else None} for b in bands]} if record else None),
        "live_record": {k: (_iso(live[k]) if live and live[k] is not None else (0 if k == "sessions" else None))
                        for k in ("sessions", "top10_hits", "touched", "graded_rows", "last_target", "last_top10_hits", "last_touched", "last_graded_rows")},
        "limits": {"not_used": NOT_USED},
    }}


@router.get("/stocks/{symbol}", summary="One stock's estimates, inputs on record and events on record")
async def stock(symbol: str = Path(..., min_length=1, max_length=20), model: Model = Query("v4")):
    sym = normalise_symbol(symbol)
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        run, expected, refusal = await _resolve(conn, model)
        current = run is not None and run["target_session"] == expected
        if refusal is not None and not current:
            return _withheld(expected, refusal)
        if not current:
            raise HTTPException(status_code=404, detail=f"not published: no run for {expected.isoformat()}")
        st = await conn.fetchrow("SELECT symbol, company_name, sector, inputs, results_filed FROM nidp.tpd_run_stocks WHERE run_id = $1 AND symbol = $2",
                                 run["run_id"], sym)
        if st is None:
            raise HTTPException(status_code=404, detail=f"{sym} is not in the published run")
        est = await conn.fetch("SELECT head, p FROM nidp.tpd_run_estimates WHERE run_id = $1 AND symbol = $2", run["run_id"], sym)
        evs = await conn.fetch("SELECT ord, event_time, source_label, is_media, event_type, event_subtype, direction, title, url, method "
                               "FROM nidp.tpd_run_events WHERE run_id = $1 AND symbol = $2 ORDER BY ord", run["run_id"], sym)
    inputs = st["inputs"]
    if isinstance(inputs, str):
        inputs = json.loads(inputs)
    return {"data": {
        "symbol": st["symbol"], "company_name": st["company_name"], "sector": st["sector"], "results_filed": bool(st["results_filed"]),
        "run": _run_public(run), "estimates": {r["head"]: float(r["p"]) for r in est}, "inputs": inputs,
        "events": [{**{k: _iso(e[k]) for k in ("ord", "event_time", "source_label", "event_type", "event_subtype", "direction", "url", "method")},
                    "is_media": bool(e["is_media"]), "title": None if e["is_media"] else e["title"]} for e in evs],
    }}


# ── History ────────────────────────────────────────────────────────────────────────────────────────────────────────
# What was published for each past session and how it turned out. Outcomes are derived from the same NSE closing rows the
# grader reads (nidp.prices_eod), using the head's own rule — verified on run 1 (2026-09-17) to reproduce
# nidp.tpd_run_grades exactly: up5 86, up10 11, down5 7, down10 0 of 994. tpd_run_grades itself only stores per-session
# totals, so per-stock outcomes have to come from the prices.
#
# within3 / within5 answer "did it get there eventually": the SAME reference close the estimate was made against
# (the target session's previous close), checked against the highest high / lowest low of the target session plus the
# next 2 / 4 sessions that exist. While a window is still incomplete both stay null and sessions_available says how many
# of the 5 are in — a partial window must never read as a miss.
LEVEL = {"p_up5_1d": 1.05, "p_up10_1d": 1.10, "p_down5_1d": 0.95, "p_down10_1d": 0.90}


def _reached(head: str, reference: float, hi, lo) -> Optional[bool]:
    """True when the head's level was reached. None when the bar it needs is missing."""
    level = reference * LEVEL[head]
    if head.startswith("p_up"):
        return None if hi is None else float(hi) >= level
    return None if lo is None else float(lo) <= level


@router.get("/history", summary="Past published sessions: the top estimates and how they turned out")
async def history(head: Head = Query("p_up5_1d"), model: Model = Query("v4"),
                  sessions: int = Query(30, ge=1, le=120), top: int = Query(20, ge=1, le=50)):
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        runs = await conn.fetch(
            "SELECT run_id, target_session, data_as_of, frozen_at, scored, universe_size FROM nidp.tpd_runs "
            "WHERE model = $1 AND status = 'final' AND counts_toward_verdict ORDER BY target_session DESC LIMIT $2",
            model, sessions + 1)                      # +1: the extra oldest run is only read to decide is_new on the one above it
        if not runs:
            return {"data": {"head": head, "model": model, "top_n": top, "sessions": []}}
        ids = [r["run_id"] for r in runs]
        rows = await conn.fetch(
            """
            WITH ranked AS (
              SELECT e.run_id, e.symbol, e.p, e.p_base_rate,
                     ROW_NUMBER() OVER (PARTITION BY e.run_id ORDER BY e.p DESC, e.symbol) AS rk
                FROM nidp.tpd_run_estimates e
               WHERE e.head = $1 AND e.run_id = ANY($2::bigint[])
            )
            SELECT r.run_id, r.symbol, r.p, r.rk, s.company_name, s.sector,
                   ref.prev_close, ref.high_price AS d_high, ref.low_price AS d_low,
                   w3.max_high AS h3, w3.min_low AS l3, w3.n AS n3,
                   w5.max_high AS h5, w5.min_low AS l5, w5.n AS n5
              FROM ranked r
              JOIN nidp.tpd_runs u ON u.run_id = r.run_id
              LEFT JOIN nidp.tpd_run_stocks s ON s.run_id = r.run_id AND s.symbol = r.symbol
              LEFT JOIN LATERAL (
                    SELECT prev_close, high_price, low_price FROM nidp.prices_eod
                     WHERE symbol = r.symbol AND as_of_date = u.target_session AND series = 'EQ'
                     ORDER BY source LIMIT 1
                   ) ref ON true
              LEFT JOIN LATERAL (
                    SELECT MAX(high_price) AS max_high, MIN(low_price) AS min_low, COUNT(*) AS n
                      FROM (SELECT DISTINCT ON (as_of_date) as_of_date, high_price, low_price FROM nidp.prices_eod
                             WHERE symbol = r.symbol AND series = 'EQ' AND as_of_date >= u.target_session
                             ORDER BY as_of_date, source LIMIT 3) x
                   ) w3 ON true
              LEFT JOIN LATERAL (
                    SELECT MAX(high_price) AS max_high, MIN(low_price) AS min_low, COUNT(*) AS n
                      FROM (SELECT DISTINCT ON (as_of_date) as_of_date, high_price, low_price FROM nidp.prices_eod
                             WHERE symbol = r.symbol AND series = 'EQ' AND as_of_date >= u.target_session
                             ORDER BY as_of_date, source LIMIT 5) x
                   ) w5 ON true
             WHERE r.rk <= $3
             ORDER BY r.run_id DESC, r.rk
            """, head, ids, top)
        grades = await conn.fetch("SELECT run_id, graded_rows, touched, top10_hits FROM nidp.tpd_run_grades "
                                  "WHERE head = $1 AND run_id = ANY($2::bigint[])", head, ids)
        base = await conn.fetchrow("SELECT p_base_rate FROM nidp.tpd_run_estimates WHERE run_id = $1 AND head = $2 LIMIT 1", ids[0], head)

    by_run: Dict[Any, list] = {}
    for r in rows:
        by_run.setdefault(r["run_id"], []).append(r)
    graded_by_run = {g["run_id"]: g for g in grades}

    out = []
    for i, run in enumerate(runs[:sessions]):
        rid = run["run_id"]
        mine = by_run.get(rid, [])
        prev = runs[i + 1]["run_id"] if i + 1 < len(runs) else None
        prev_top = {r["symbol"] for r in by_run.get(prev, [])} if prev is not None else None
        g = graded_by_run.get(rid)
        session_rows = []
        for r in mine:
            ref = float(r["prev_close"]) if r["prev_close"] is not None else None
            if ref is None:
                outcome = {"state": "pending", "touched": None, "move_pct": None, "reference_close": None,
                           "within3": None, "within5": None, "sessions_available": 0}
            else:
                hi, lo = r["d_high"], r["d_low"]
                move = (float(hi) / ref - 1) if head.startswith("p_up") and hi is not None else (
                       (float(lo) / ref - 1) if lo is not None else None)
                n5 = int(r["n5"] or 0)
                outcome = {
                    "state": "graded", "touched": _reached(head, ref, hi, lo),
                    "move_pct": move, "reference_close": ref,
                    "within3": _reached(head, ref, r["h3"], r["l3"]) if int(r["n3"] or 0) >= 3 else None,
                    "within5": _reached(head, ref, r["h5"], r["l5"]) if n5 >= 5 else None,
                    "sessions_available": n5,
                }
            session_rows.append({
                "rank": int(r["rk"]), "symbol": r["symbol"], "company_name": r["company_name"], "sector": r["sector"],
                "p": float(r["p"]),
                "is_new": None if prev_top is None else (r["symbol"] not in prev_top),
                "outcome": outcome,
            })
        touched_in_top = [row for row in session_rows if row["outcome"]["touched"] is True]
        state = "graded" if g is not None else ("graded" if session_rows and all(row["outcome"]["state"] == "graded" for row in session_rows) else "pending")
        out.append({
            "target_session": _iso(run["target_session"]), "data_as_of": _iso(run["data_as_of"]), "frozen_at": _iso(run["frozen_at"]),
            "scored": int(run["scored"]) if run["scored"] is not None else None,
            "base_rate": float(base["p_base_rate"]) if base and base["p_base_rate"] is not None else None,
            "state": state,
            "summary": {
                "graded_rows": int(g["graded_rows"]) if g else None,
                "touched": int(g["touched"]) if g else None,
                "touch_rate": (float(g["touched"]) / float(g["graded_rows"])) if g and g["graded_rows"] else None,
                "top10_touched": int(g["top10_hits"]) if g else None,
                "top_n_touched": len(touched_in_top) if state == "graded" else None,
            },
            "rows": session_rows,
        })
    return {"data": {"head": head, "model": model, "top_n": top, "sessions": out}}
