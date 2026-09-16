"""Move odds — published Ten-Percent Days estimates for the Research page (migration 149, tpd_model.publish).

    GET /v1/move-odds/latest?head=p_up5_1d&model=v4   the scored list for the session the estimates apply to
    GET /v1/move-odds/stocks/{symbol}?model=v4        one stock: all four estimates, inputs on record, events on record

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
