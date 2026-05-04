"""Macro Intelligence routes — read-only API for the Copilot + UI.

  GET  /api/macro/today                — current regime + values + insight
  POST /api/macro/refresh              — manual trigger (admin / debug)
  POST /api/macro/backfill             — pull last N days of history
                                          (one-shot at first deploy)
  GET  /api/macro/sector               — per-sector tilt heatmap (PR-2)
  GET  /api/stock/{symbol}/why         — explainability for one stock (PR-2)
"""
from __future__ import annotations
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, HTTPException
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
    return snap


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
