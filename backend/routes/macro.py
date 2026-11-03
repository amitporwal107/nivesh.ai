"""Macro Intelligence routes — read-only API for the Copilot + UI.

  GET  /api/macro/today                — current regime + values + insight, and `regime`: the
                                          Smart trading desk's five-regime reading of the same
                                          session (macro_engine.classify_desk_regime)
  POST /api/macro/refresh              — manual trigger (admin / debug)
  POST /api/macro/backfill             — pull last N days of history
                                          (one-shot at first deploy)
  GET  /api/macro/regime-history       — the desk regime (desk-regime-v1) of each stored session,
                                          recomputed from the stored end-of-day inputs
  GET  /api/macro/sector               — per-sector tilt heatmap (PR-2)
  GET  /api/stock/{symbol}/why         — explainability for one stock (PR-2)
"""
from __future__ import annotations
import asyncio
import logging
import time
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/macro", tags=["macro"])


def _uninitialised_payload(reason: Optional[str] = None) -> Dict[str, Any]:
    """Default empty-state response — UI flips into the backfill CTA card."""
    return {
        "_uninitialised": True,
        "_reason": reason,
        "market": "NEUTRAL",
        "inflation": "STABLE",
        "liquidity": "EASY",
        "risk": "MEDIUM",
        "multiplier": 1.0,
        "insight": "Macro intelligence layer is initialising — daily ingestion runs at 18:35 IST.",
        "values": {},
        "features": {},
        "sources": {},
        "confidence": {},
    }


@router.get("/today")
async def macro_today(request: Request):
    """Latest macro snapshot for the Copilot bar.

    Auth: any logged-in user. The macro view is global (not per-user)
    so we don't gate by workspace.

    Never 500s — any internal failure (missing tables, missing columns,
    PG down) returns the `_uninitialised` payload with `_reason` set so
    the operator can see what's broken in the UI without checking logs.
    """
    try:
        await get_current_user(request)
    except Exception:
        # Auth failures should still bubble up — only macro-internal errors
        # get the soft-landing treatment.
        raise
    try:
        from services import macro_engine
        snap = await macro_engine.latest_state()
    except Exception as e:  # noqa: BLE001
        logger.warning("/macro/today failed: %s", e, exc_info=True)
        return _uninitialised_payload(reason=f"{type(e).__name__}: {str(e)[:200]}")
    if snap is None:
        return _uninitialised_payload(reason="macro_state empty — backfill needed")
    snap["regime"] = await _desk_regime(snap)
    return snap


# The session's advances / declines change only when that day's bars are reloaded, so one read
# per session is kept for ten minutes (the desk reads /macro/today every ten minutes as well).
_BREADTH_TTL = 600.0
_BREADTH_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


async def _session_breadth(session: date) -> Optional[Dict[str, Any]]:
    from services import macro_engine
    key = session.isoformat()
    now = time.time()
    hit = _BREADTH_CACHE.get(key)
    if hit and now - hit[0] < _BREADTH_TTL:
        return hit[1]
    data = await macro_engine.session_breadth(session)
    _BREADTH_CACHE[key] = (now, data)
    return data


# The 50-session average needs 50 daily Nifty closes in macro_daily, which fills one row per day from the day the job was
# first run. When macro_daily is short of them the closes are read from the warehouse (nidp.index_eod, the same NSE index
# close the desk sector table uses) and the answer names that source. The rule itself is not touched.
NIFTY_WAREHOUSE_SOURCE = "nidp.index_eod 'Nifty 50' close (DaaS /v1/indices/Nifty 50/eod)"
NIFTY_MACRO_SOURCE = "macro_daily nifty (macro_engine.compute_features nifty_50dma)"
_NIFTY_LOOKBACK_DAYS = 120          # calendar days: 50 sessions with room for holidays
_NIFTY_TTL = 600.0
_NIFTY_CACHE: Dict[str, Tuple[float, Tuple[Optional[float], Optional[float], Optional[str]]]] = {}


async def _warehouse_nifty(session: date) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """(Nifty 50 close on `session`, its average over the rule's sessions up to it, why not) from nidp.index_eod. The average
    uses macro_engine._sma, so the gap tolerance is the one macro_features applies (at least 60% of the sessions present)."""
    from services import macro_engine
    from services.copilot_tools import daas_client
    key = session.isoformat()
    hit = _NIFTY_CACHE.get(key)
    if hit and time.time() - hit[0] < _NIFTY_TTL:
        return hit[1]
    try:
        rows = await daas_client.get_index_eod_history(
            "Nifty 50", start=(session - timedelta(days=_NIFTY_LOOKBACK_DAYS)).isoformat(), end=key)
    except Exception as e:  # noqa: BLE001
        logger.warning("desk regime: Nifty 50 warehouse read failed: %s", e)
        return None, None, f"{NIFTY_WAREHOUSE_SOURCE} could not be read ({type(e).__name__})"
    out = nifty_from_warehouse_rows(rows, session)
    _NIFTY_CACHE[key] = (time.time(), out)
    return out


def nifty_from_warehouse_rows(rows: Any, session: date) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """(Nifty 50 close on `session`, its average over the rule's sessions up to it, why not) from nidp.index_eod rows,
    using only the rows from `_NIFTY_LOOKBACK_DAYS` before the session up to the session (the window _warehouse_nifty
    reads), so a longer read gives the same answer for each session. The average is macro_engine._sma's."""
    from services import macro_engine
    key = session.isoformat()
    first = (session - timedelta(days=_NIFTY_LOOKBACK_DAYS)).isoformat()
    n = int(macro_engine.DESK_REGIME_RULE["trend_average_sessions"])
    series = [(str(r.get("as_of_date"))[:10], _num(r.get("close_price"))) for r in rows or [] if isinstance(r, dict)]
    series = [(d, c) for d, c in series if c is not None and first <= d <= key]
    close = next((c for d, c in series if d == key), None)
    if close is None:
        return None, None, f"{NIFTY_WAREHOUSE_SOURCE} has no close for {key}"
    avg = macro_engine._sma([c for _, c in series], n)
    return close, avg, None if avg is not None else f"{NIFTY_WAREHOUSE_SOURCE} has only {len(series[-n:])} of the {n} sessions to {key}"


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def _desk_regime(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The desk's five-regime reading of the snapshot's session (PRD OV-003). The regime is the
    rule's answer, never a guess: a missing input skips its check and says so, and a failure here
    leaves `key` null with the reason instead of failing /macro/today."""
    session = snap.get("date")
    values = snap.get("values") or {}
    feats = snap.get("features") or {}
    breadth: Optional[Dict[str, Any]] = None
    breadth_error: Optional[str] = None
    try:
        if session:
            breadth = await _session_breadth(date.fromisoformat(session))
    except Exception as e:  # noqa: BLE001
        logger.warning("/macro/today session breadth failed: %s", e)
        breadth_error = f"{type(e).__name__}: {str(e)[:120]}"
    nifty_close, nifty_average = _num(values.get("nifty")), _num(feats.get("nifty_50dma"))
    nifty_source, nifty_note = NIFTY_MACRO_SOURCE, None
    if session and (nifty_close is None or nifty_average is None):
        w_close, w_avg, nifty_note = await _warehouse_nifty(date.fromisoformat(session))
        if w_close is not None and w_avg is not None:
            nifty_close, nifty_average, nifty_source, nifty_note = w_close, w_avg, NIFTY_WAREHOUSE_SOURCE, None
    return _classify_session(session, nifty_close, nifty_average, nifty_source, nifty_note,
                             _num(values.get("india_vix")), breadth, breadth_error)


def _classify_session(session: Optional[str], nifty_close: Optional[float], nifty_average: Optional[float],
                      nifty_source: str, nifty_note: Optional[str], india_vix: Optional[float],
                      breadth: Optional[Dict[str, Any]], breadth_error: Optional[str]) -> Dict[str, Any]:
    """classify_desk_regime on one session's inputs, with the notes /macro/today adds: where the Nifty levels came
    from, why the trend check could not be made, and a breadth read that failed. Shared by /today and
    /regime-history so a session reads the same in both."""
    from services import macro_engine
    try:
        out = macro_engine.classify_desk_regime(
            session=session,
            nifty_close=nifty_close,
            nifty_average=nifty_average,
            india_vix=india_vix,
            breadth=breadth,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("/macro desk regime failed: %s", e, exc_info=True)
        return {"key": None, "label": None, "date": session, "rule": dict(macro_engine.DESK_REGIME_RULE),
                "inputs": {}, "skipped": [], "invalidation": [],
                "reason": f"the regime rule failed: {type(e).__name__}"}
    out["inputs"]["nifty_source"] = nifty_source if nifty_close is not None and nifty_average is not None else None
    if nifty_note:
        out["skipped"] = out["skipped"] + [{"check": "trend", "reason": f"macro_daily has no 50-session Nifty average, and {nifty_note}"}]
    if breadth_error:
        out["skipped"] = [c for c in out["skipped"] if c["check"] != "mixed"] + [
            {"check": "mixed", "reason": f"breadth could not be read ({breadth_error})"}]
    return out


# ── Regime history: the desk regime of every stored session ──────────────────
REGIME_HISTORY_DEFAULT_DAYS = 60
REGIME_HISTORY_MAX_DAYS = 260       # about a year of sessions; each session is one breadth query
_REGIME_HISTORY_BREADTH_CONCURRENCY = 3   # the app's Postgres pool holds five connections
REGIME_HISTORY_BASIS = (
    "Recomputed now with the rule's version from the stored end-of-day inputs of each session: macro_daily (Nifty 50 "
    "close, India VIX), macro_features (the 50-session Nifty average; the warehouse Nifty 50 closes when it has none, "
    "as /api/macro/today does) and stock_ohlcv (advances and declines). It is not a record of what the desk showed on "
    "the day: no regime reading was stored at the time, and a stored input that was later rewritten gives its current value.")
_REGIME_POINT_INPUTS = ("nifty_close", "nifty_average", "nifty_vs_average_pct", "nifty_source", "trend", "india_vix",
                        "volatility_high", "advancing_share_pct", "breadth", "breadth_universe")


def _regime_missing(points: List[Dict[str, Any]]) -> List[str]:
    """What the stored inputs lack, in sentences, from the checks each point could not make."""
    n = len(points)
    skipped = Counter(c["check"] for p in points for c in p["skipped"])
    out: List[str] = []
    no_regime = sum(1 for p in points if p["key"] is None)
    if no_regime:
        out.append(f"{no_regime} of {n} sessions have no 50-session Nifty 50 average in macro_features and none could be "
                   f"worked out from the warehouse closes: they have no regime.")
    if skipped["high_volatility"]:
        out.append(f"India VIX (macro_daily.india_vix) is missing on {skipped['high_volatility']} of {n} sessions: the "
                   f"high-volatility check is skipped on them.")
    if skipped["mixed"]:
        out.append(f"Breadth (stock_ohlcv advances and declines) is missing or could not be read on {skipped['mixed']} of "
                   f"{n} sessions: the mixed check is skipped on them.")
    warehouse = sum(1 for p in points if p["inputs"].get("nifty_source") == NIFTY_WAREHOUSE_SOURCE)
    if warehouse:
        out.append(f"{warehouse} of {n} sessions take the Nifty 50 levels from the warehouse closes because macro_features "
                   f"has no 50-session average for them.")
    return out


@router.get("/regime-history")
async def regime_history(
    request: Request,
    days: int = Query(REGIME_HISTORY_DEFAULT_DAYS, ge=1, le=REGIME_HISTORY_MAX_DAYS, description="Latest stored sessions"),
):
    """The desk regime (macro_engine.classify_desk_regime, desk-regime-v1) of each of the latest `days` stored
    sessions, oldest first. A session is a macro_daily row with a Nifty 50 close. Each point carries its rule
    version, its inputs, the checks it could not make and why; a session whose inputs are missing has a null
    regime with the reason, never a default. `missing` sums up what the stored inputs lack. The macro store
    failing to answer is 502, never an empty history. Read only."""
    await get_current_user(request)
    from services import macro_engine
    from services.copilot_tools import daas_client
    try:
        stored = await macro_engine.desk_regime_inputs(days)
    except Exception as e:  # noqa: BLE001
        logger.warning("/macro/regime-history: the stored inputs could not be read: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="macro_unavailable")
    rows: List[Dict[str, Any]] = stored["rows"]
    rule = dict(macro_engine.DESK_REGIME_RULE)
    base: Dict[str, Any] = {"rule": rule, "rule_version": rule["version"], "basis": REGIME_HISTORY_BASIS,
                            "requested_days": days, "non_session_rows": stored.get("non_session_rows", 0), "read_only": True}
    if not rows:
        return {**base, "sessions": 0, "points": [], "first_session": None, "last_session": None,
                "complete": 0, "partial": 0, "unclassified": 0, "missing": [],
                "reason": "macro_daily has no session with a Nifty 50 close: the daily macro job (18:30 IST) or "
                          "POST /api/macro/backfill fills it."}

    # The warehouse closes are read once for every session that needs them (macro_features has no average for it).
    need = [r for r in rows if r["nifty"] is None or r["nifty_50dma"] is None]
    warehouse: List[Dict[str, Any]] = []
    warehouse_note: Optional[str] = None
    if need:
        start = (date.fromisoformat(need[0]["date"]) - timedelta(days=_NIFTY_LOOKBACK_DAYS)).isoformat()
        try:
            warehouse = await daas_client.get_index_eod_history("Nifty 50", start=start, end=need[-1]["date"])
        except Exception as e:  # noqa: BLE001
            warehouse_note = f"{NIFTY_WAREHOUSE_SOURCE} could not be read ({type(e).__name__})"
        if not warehouse and warehouse_note is None:
            warehouse_note = (f"{NIFTY_WAREHOUSE_SOURCE} sent no rows for {start} to {need[-1]['date']} (this client "
                              f"answers a failed read with no rows, so the two cannot be told apart)")

    gate = asyncio.Semaphore(_REGIME_HISTORY_BREADTH_CONCURRENCY)

    async def one(r: Dict[str, Any]) -> Dict[str, Any]:
        session = r["date"]
        breadth: Optional[Dict[str, Any]] = None
        breadth_error: Optional[str] = None
        try:
            async with gate:
                breadth = await _session_breadth(date.fromisoformat(session))
        except Exception as e:  # noqa: BLE001
            breadth_error = f"{type(e).__name__}: {str(e)[:120]}"
        close, avg = r["nifty"], r["nifty_50dma"]
        source, note = NIFTY_MACRO_SOURCE, None
        if close is None or avg is None:
            if warehouse_note:
                note = warehouse_note
            else:
                w_close, w_avg, note = nifty_from_warehouse_rows(warehouse, date.fromisoformat(session))
                if w_close is not None and w_avg is not None:
                    close, avg, source, note = w_close, w_avg, NIFTY_WAREHOUSE_SOURCE, None
        out = _classify_session(session, close, avg, source, note, r["india_vix"], breadth, breadth_error)
        inputs = out.get("inputs") or {}
        return {"date": session, "rule_version": (out.get("rule") or rule).get("version"), "key": out.get("key"),
                "label": out.get("label"), "inputs": {k: inputs.get(k) for k in _REGIME_POINT_INPUTS},
                "skipped": out.get("skipped") or [], "reason": out.get("reason")}

    points = list(await asyncio.gather(*(one(r) for r in rows)))
    return {
        **base, "sessions": len(points), "points": points,
        "first_session": points[0]["date"], "last_session": points[-1]["date"],
        "complete": sum(1 for p in points if p["key"] and not p["skipped"]),
        "partial": sum(1 for p in points if p["key"] and p["skipped"]),
        "unclassified": sum(1 for p in points if not p["key"]),
        "missing": _regime_missing(points),
        "reason": None,
    }


class RefreshRequest(BaseModel):
    target_date: Optional[str] = Field(None, description="ISO date (YYYY-MM-DD); defaults to today")


@router.post("/refresh")
async def macro_refresh(payload: RefreshRequest, request: Request):
    """Manual trigger: ingest → features → regime for one day.

    Used by the admin / debug surface. Production run is the scheduler at
    18:30 IST in mf_scheduler.py.
    """
    await get_current_user(request)
    from datetime import date
    from services import macro_engine

    target = None
    if payload.target_date:
        try:
            target = date.fromisoformat(payload.target_date)
        except ValueError:
            raise HTTPException(400, f"Invalid target_date: {payload.target_date}")
    return await macro_engine.run_daily(target)


class BackfillRequest(BaseModel):
    days: int = Field(60, ge=1, le=730,
                      description="Days of history to pull (capped at 2 years)")


@router.post("/backfill")
async def macro_backfill(payload: BackfillRequest, request: Request):
    """One-shot: backfill `macro_daily` so the feature engine has 50DMA
    history. Run once after the migration lands (or click "Backfill" in
    the MacroBar empty-state CTA).

    For each prior trading day in the window we also recompute features +
    regime so the time series is queryable end-to-end. Slow but correct.

    Never 500s — wraps the whole flow in try/except and surfaces the
    actual failure as JSON so the empty-state UI can show it inline."""
    await get_current_user(request)
    try:
        from datetime import date
        from services import macro_ingester, macro_engine

        res = await macro_ingester.backfill(days=payload.days)
        if not res.get("ok"):
            return res

        # Walk every date that landed in macro_daily and compute features + regime.
        # We do this in date order so 50DMAs build progressively.
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            return {**res, "features_computed": 0, "states_computed": 0,
                    "_warning": "no pg pool — features + regime not recomputed"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT date FROM macro_daily ORDER BY date ASC LIMIT $1",
                payload.days + 30,
            )
        feats_done = 0
        states_done = 0
        feat_errors: list[str] = []
        for r in rows:
            d: date = r["date"]
            try:
                await macro_engine.compute_features(d)
                feats_done += 1
                await macro_engine.classify_regime(d)
                states_done += 1
            except Exception as e:  # noqa: BLE001
                logger.debug("macro backfill compute failed for %s: %s", d, e)
                if len(feat_errors) < 3:
                    feat_errors.append(f"{d}: {type(e).__name__}: {str(e)[:120]}")
        # After features land, recompute sector_macro_scores per day so the
        # heatmap is queryable across the backfill window.
        sector_errors: list[str] = []
        try:
            from services import macro_sector
            for r in rows:
                try:
                    await macro_sector.compute_sector_scores(r["date"])
                except Exception as e:  # noqa: BLE001
                    if len(sector_errors) < 3:
                        sector_errors.append(f"{r['date']}: {type(e).__name__}: {str(e)[:120]}")
        except Exception as e:  # noqa: BLE001
            logger.debug("macro sector backfill failed: %s", e)
        out: Dict[str, Any] = {
            **res,
            "features_computed": feats_done,
            "states_computed": states_done,
        }
        if feat_errors:
            out["_feature_errors_sample"] = feat_errors
        if sector_errors:
            out["_sector_errors_sample"] = sector_errors
        return out
    except Exception as e:  # noqa: BLE001
        logger.exception("macro backfill failed: %s", e)
        # Return structured error JSON instead of 500 so the UI's empty-state
        # CTA can surface the real reason ("relation X does not exist" etc.)
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {str(e)[:300]}",
            "hint": (
                "Likely a schema or yfinance issue. Verify migrations 016 + 017 "
                "have been applied and that the deployment can reach yfinance."
            ),
        }


# ── Sector heatmap ─────────────────────────────────────────────────────
@router.get("/sector")
async def macro_sector_heatmap(request: Request):
    """Per-sector macro tilt for the latest day. Returns rows sorted by
    tilt descending — UI renders as a heatmap or sorted strip."""
    await get_current_user(request)
    from services import macro_sector
    return await macro_sector.latest_heatmap()


# ── PR-C: What changed since yesterday ─────────────────────────────────
@router.get("/changes")
async def macro_changes(request: Request):
    """Diff today's macro_state + sector_macro_scores vs the previous
    trading day. Drives the "What changed since yesterday" strip on the
    Market Dashboard.

    Returns a structured diff so the UI doesn't have to parse prose:
      {
        "today_date": "2026-05-03",
        "previous_date": "2026-05-02",
        "regime_changes": [
          {"field": "risk", "from": "MEDIUM", "to": "HIGH"},
          {"field": "market", "from": "BULL", "to": "NEUTRAL"},
        ],
        "sector_changes": [
          {"sector": "IT", "from": 0.4, "to": 1.2, "delta": 0.8, "tier_change": "BUY → STRONG BUY"},
          ...
        ],
        "headline": "USD ↑ → IT upgraded from BUY to STRONG BUY"
      }
    """
    await get_current_user(request)
    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            return {"_uninitialised": True, "_reason": "no pg pool"}
        async with pool.acquire() as conn:
            two = await conn.fetch(
                "SELECT * FROM macro_state ORDER BY date DESC LIMIT 2",
            )
            if len(two) < 2:
                return {"_uninitialised": True,
                        "_reason": "need ≥ 2 days of macro_state to compute changes"}
            today_row, prev_row = two[0], two[1]

            today_sectors = await conn.fetch(
                "SELECT sector, macro_score FROM sector_macro_scores WHERE date = $1",
                today_row["date"],
            )
            prev_sectors = await conn.fetch(
                "SELECT sector, macro_score FROM sector_macro_scores WHERE date = $1",
                prev_row["date"],
            )
        # Regime field diff
        regime_changes: list = []
        for field in ("market", "inflation", "liquidity", "risk"):
            t = today_row[field] if field in today_row.keys() else None
            p = prev_row[field] if field in prev_row.keys() else None
            if t != p:
                regime_changes.append({"field": field, "from": p, "to": t})
        # Multiplier change
        t_mul = today_row["macro_multiplier"]
        p_mul = prev_row["macro_multiplier"]
        if t_mul is not None and p_mul is not None and float(t_mul) != float(p_mul):
            regime_changes.append({
                "field": "multiplier",
                "from": float(p_mul), "to": float(t_mul),
            })

        # Sector deltas (most-changed first, top 5 by abs delta)
        prev_by_sec = {r["sector"]: float(r["macro_score"] or 0) for r in prev_sectors}
        today_by_sec = {r["sector"]: float(r["macro_score"] or 0) for r in today_sectors}
        sector_changes: list = []

        def _tier(score: float) -> str:
            if score >= 2.5: return "STRONG BUY"
            if score >= 0.8: return "BUY"
            if score >= -0.8: return "WATCH"
            if score >= -2.5: return "AVOID"
            return "STRONG AVOID"

        for sec, t_val in today_by_sec.items():
            p_val = prev_by_sec.get(sec, 0.0)
            delta = round(t_val - p_val, 3)
            if abs(delta) < 0.3:    # noise floor
                continue
            t_tier = _tier(t_val)
            p_tier = _tier(p_val)
            sector_changes.append({
                "sector": sec,
                "from": round(p_val, 2),
                "to": round(t_val, 2),
                "delta": delta,
                "tier_change": (
                    f"{p_tier} → {t_tier}" if t_tier != p_tier else None
                ),
            })
        sector_changes.sort(key=lambda x: abs(x["delta"]), reverse=True)
        sector_changes = sector_changes[:5]

        # Build a one-line headline. Prefers sector tier-change events, else
        # highlights the largest regime-field shift.
        headline = None
        for sc in sector_changes:
            if sc.get("tier_change"):
                # Pick a quick driver from the macro_features values
                headline = f"{sc['sector']} upgraded {sc['tier_change']}" if sc["delta"] > 0 \
                    else f"{sc['sector']} downgraded {sc['tier_change']}"
                break
        if headline is None and regime_changes:
            r = regime_changes[0]
            headline = f"{r['field'].title()} shifted {r['from']} → {r['to']}"
        if headline is None:
            headline = "No material macro changes vs previous trading day."

        return {
            "today_date": today_row["date"].isoformat() if today_row["date"] else None,
            "previous_date": prev_row["date"].isoformat() if prev_row["date"] else None,
            "regime_changes": regime_changes,
            "sector_changes": sector_changes,
            "headline": headline,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("/macro/changes failed: %s", e, exc_info=True)
        return {
            "_error": True,
            "_reason": f"{type(e).__name__}: {str(e)[:200]}",
            "headline": "Unable to compute changes right now.",
            "regime_changes": [],
            "sector_changes": [],
        }


# ── PR-C: Macro-aligned positional opportunities ──────────────────────
@router.get("/aligned-picks")
async def macro_aligned_picks(request: Request, limit: int = 5):
    """Surface positional candidates whose sector aligns with today's
    macro tailwinds. Used as a "Coming opportunities" preview on the
    Market Dashboard before today's actual signals fire.

    Logic:
      1. Take sectors with macro_score ≥ 0.8 (BUY tier or stronger).
      2. Find positional_signals (or stock_technical_features if no
         signal yet) whose sector_key matches.
      3. Group by sector, return up to N candidates per sector.

    When no `positional_signals` exist yet for today, falls back to
    `stock_technical_features` so the user still gets a watchlist preview.
    """
    await get_current_user(request)
    try:
        from services import pg_client, macro_sector as _ms
        pool = await pg_client.get_pool()
        if pool is None:
            return {"sectors": [], "_reason": "no pg pool"}
        async with pool.acquire() as conn:
            # Latest tailwind sectors
            latest = await conn.fetchrow(
                "SELECT MAX(date) AS d FROM sector_macro_scores"
            )
            if not latest or latest["d"] is None:
                return {"sectors": [], "_reason": "no sector scores yet"}
            sectors_today = await conn.fetch(
                "SELECT sector, macro_score FROM sector_macro_scores "
                "WHERE date = $1 AND macro_score >= 0.8 "
                "ORDER BY macro_score DESC",
                latest["d"],
            )
            if not sectors_today:
                return {"sectors": [], "_reason": "no sectors above BUY threshold today"}

            # For each tailwind sector, find candidate symbols
            out: list = []
            for srow in sectors_today:
                sector_key = srow["sector"]
                macro_score = float(srow["macro_score"] or 0)
                # Resolve which raw stock_master.sector strings map to this key
                # by reverse-pattern-matching. Since _resolve_sector lives in
                # macro_sector and is keyword-driven, we just LIKE-match common
                # patterns inline.
                like_patterns = {
                    "IT": ["%information technology%", "%software%", "% it %", "%it services%"],
                    "PHARMA": ["%pharma%"],
                    "BANK": ["%bank%"],
                    "AUTO": ["%auto%"],
                    "FMCG": ["%fmcg%", "%consumer goods%"],
                    "OIL_GAS": ["%oil%", "%gas%", "%petroleum%"],
                    "REALTY": ["%real estate%", "%realty%"],
                    "METAL": ["%metal%", "%steel%", "%mining%"],
                    "POWER": ["%power%", "%utilit%"],
                }.get(sector_key, [f"%{sector_key.lower()}%"])

                # Build the OR clause dynamically (parameterised LIKE)
                where_or = " OR ".join(
                    [f"LOWER(sm.sector) LIKE ${i + 2}" for i in range(len(like_patterns))]
                )
                # Try positional_signals first (today's actionable picks)
                rows = await conn.fetch(
                    f"""
                    SELECT ps.nse_symbol, ps.final_score, ps.stage, ps.confidence,
                           sm.sector AS raw_sector
                    FROM positional_signals ps
                    JOIN stock_master sm ON sm.nse_symbol = ps.nse_symbol
                    WHERE ps.signal_date = (SELECT MAX(signal_date) FROM positional_signals)
                      AND ({where_or})
                    ORDER BY ps.final_score DESC
                    LIMIT $1
                    """,
                    limit, *like_patterns,
                )
                source_label = "positional_signals"
                # Fallback: stock_technical_features for sectors with no actionable signals
                if not rows:
                    rows = await conn.fetch(
                        f"""
                        SELECT stf.nse_symbol, stf.final_score, stf.stage, stf.confidence,
                               sm.sector AS raw_sector
                        FROM stock_technical_features stf
                        JOIN stock_master sm ON sm.nse_symbol = stf.nse_symbol
                        WHERE stf.as_of_date = (SELECT MAX(as_of_date) FROM stock_technical_features)
                          AND ({where_or})
                          AND stf.stage NOT IN ('WEAK', 'EXTENDED')
                        ORDER BY stf.final_score DESC
                        LIMIT $1
                        """,
                        limit, *like_patterns,
                    )
                    source_label = "stock_technical_features (preview)"

                if rows:
                    out.append({
                        "sector": sector_key,
                        "macro_score": macro_score,
                        "source": source_label,
                        "candidates": [
                            {
                                "nse_symbol": r["nse_symbol"],
                                "final_score": float(r["final_score"]) if r["final_score"] is not None else None,
                                "stage": r["stage"],
                                "confidence": r["confidence"],
                                "raw_sector": r["raw_sector"],
                            }
                            for r in rows
                        ],
                        "candidate_count": len(rows),
                    })
        return {
            "as_of_date": str(latest["d"]),
            "sectors": out,
            "total_candidates": sum(s["candidate_count"] for s in out),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("/macro/aligned-picks failed: %s", e, exc_info=True)
        return {
            "_error": True,
            "_reason": f"{type(e).__name__}: {str(e)[:200]}",
            "sectors": [],
        }


# ── Per-stock explainability ───────────────────────────────────────────
# Mounted under /api/stock — separate prefix so it lives next to /api/portfolio
# style endpoints rather than under /api/macro. We attach it via a sub-router.
stock_router = APIRouter(prefix="/api/stock", tags=["macro"])


@stock_router.get("/{symbol}/why")
async def stock_why(symbol: str, request: Request):
    """Explainability payload for a single stock, combining:

      • The macro state right now
      • The stock's sector → macro tilt
      • The position-size factor that the trade_planner would use

    Returns a self-contained JSON the UI can render as a "why this score"
    panel without needing to call /macro/today separately.
    """
    await get_current_user(request)
    from services import macro_engine, macro_sector
    from services.positional_engine import macro_overlay
    from services import pg_client

    state = await macro_engine.latest_state() or {}
    # Look up the stock's sector for the tilt mapping
    raw_sector: Optional[str] = None
    pool = await pg_client.get_pool()
    if pool is not None:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT sector FROM stock_master WHERE nse_symbol = $1",
                symbol.upper(),
            )
            raw_sector = row["sector"] if row else None

    sector_info = await macro_sector.score_for_sector(raw_sector) if raw_sector else None
    sector_modifier = sector_info["macro_score"] if sector_info else None

    pos_factor = macro_overlay.position_size_factor(
        risk=state.get("risk"),
        macro_multiplier=state.get("multiplier"),
        sector_modifier=sector_modifier,
    )
    pos_explain = macro_overlay.explain_position_size(
        risk=state.get("risk"), sector_modifier=sector_modifier,
    )

    # Macro impact on the score (additive component the scorer would apply)
    macro_impact_score = round(
        ((state.get("multiplier", 1.0) - 1.0) * 100) + (sector_modifier or 0.0), 2,
    )
    sector_bias = (
        "FAVORABLE" if (sector_modifier or 0) > 1.5
        else "UNFAVORABLE" if (sector_modifier or 0) < -1.5
        else "NEUTRAL"
    )

    return {
        "symbol": symbol.upper(),
        "raw_sector": raw_sector,
        "sector_key": (sector_info or {}).get("sector_key"),
        "macro_state": {
            "market": state.get("market"),
            "inflation": state.get("inflation"),
            "liquidity": state.get("liquidity"),
            "risk": state.get("risk"),
            "multiplier": state.get("multiplier"),
            "insight": state.get("insight"),
        },
        "macro_impact_score": macro_impact_score,
        "sector_bias": sector_bias,
        "sector_modifier": sector_modifier,
        "sector_rationale": (sector_info or {}).get("rationale"),
        "position_size": {
            "factor": pos_factor,
            "label": f"{pos_factor:g}x",
            "explanation": pos_explain,
        },
    }
