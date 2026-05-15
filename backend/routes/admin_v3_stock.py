"""Admin endpoints for V3 STOCK weight configuration + stock master data.

Mirrors `admin_v3_weights.py` (for MFs) but operates on direct equity
scoring weights (Quality/Health/Exit/Add) and exposes a read-only listing
of the Nifty 100 / stock_master for the admin dashboard's "Equity" tab.

  GET  /api/admin/v3-stock-weights        — current stock weight config
  PUT  /api/admin/v3-stock-weights        — replace full config (sum-to-100)
  POST /api/admin/v3-stock-weights/reset  — restore defaults
  GET  /api/admin/v3-stock-master         — list all scored stocks (Nifty 100 by default)
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from deps import db, require_admin
from services import stock_scoring

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class StockWeightsPayload(BaseModel):
    weights: Dict[str, Dict[str, float]]


def _summary() -> Dict[str, Any]:
    cfg = stock_scoring.get_full_config()
    summary = {}
    for dim, wmap in cfg.items():
        total = sum(v for k, v in wmap.items() if k != "reserved")
        summary[dim] = {
            "weights": wmap,
            "total": total,
            "components": [k for k in wmap if k != "reserved"],
        }
    return summary


@router.get("/admin/v3-stock-weights")
async def get_v3_stock_weights(request: Request):
    await require_admin(request)
    return {
        "weights": stock_scoring.get_full_config(),
        "defaults": stock_scoring.DEFAULT_STOCK_WEIGHTS,
        "summary": _summary(),
        "engine_version": stock_scoring.ENGINE_VERSION,
    }


@router.put("/admin/v3-stock-weights")
async def put_v3_stock_weights(request: Request, payload: StockWeightsPayload):
    await require_admin(request)
    cfg = payload.weights
    # Validate: each dimension's weights sum to 100 ± 0.5 (ignoring reserved)
    issues = []
    for dim, wmap in cfg.items():
        total = sum(v for k, v in wmap.items() if k != "reserved")
        # Health includes an explicit `reserved` slot that should bring the
        # stated sum to 100; tolerate both.
        if abs(total - 100) > 0.5 and abs(sum(wmap.values()) - 100) > 0.5:
            issues.append(f"{dim} sums to {total} (or {sum(wmap.values())} incl. reserved), expected 100")
    if issues:
        raise HTTPException(status_code=422, detail={"issues": issues})
    for dim, wmap in cfg.items():
        stock_scoring.set_weights(dim, {k: int(round(v)) for k, v in wmap.items()})
    await stock_scoring.persist_to_db(db)
    logger.info("v3-stock-weights updated; dimensions=%s", list(cfg))
    return {"status": "ok", "weights": stock_scoring.get_full_config()}


@router.post("/admin/v3-stock-weights/reset")
async def reset_v3_stock_weights(request: Request):
    await require_admin(request)
    from copy import deepcopy
    for dim, wmap in deepcopy(stock_scoring.DEFAULT_STOCK_WEIGHTS).items():
        stock_scoring.set_weights(dim, wmap)
    await stock_scoring.persist_to_db(db)
    return {"status": "ok", "weights": stock_scoring.get_full_config()}


# ── Groww scraper refresh endpoint ──────────────────────────────────────
@router.post("/admin/v3-stock-refresh")
async def trigger_v3_stock_refresh(request: Request, symbol: Optional[str] = None):
    """Trigger Groww Nifty 100 scrape + score. `symbol` (optional) refreshes
    just that NSE symbol. No-arg = full Nifty 100 refresh (runs in request
    thread; typically 60-90s)."""
    await require_admin(request)
    from services import groww_stock_scraper as _gs
    subset = [symbol.upper()] if symbol else None
    job_label = "stock_refresh_manual" if symbol else "nifty100_refresh"
    result = await _gs.refresh_nifty_100(symbols_subset=subset, job_name=job_label)
    logger.info("v3-stock-refresh done: %s/%s", result.get('succeeded', 0), result.get('total', 0))
    return result


# ── NIDP-native score refresh endpoint ──────────────────────────────────
@router.post("/admin/v3-stock-score-nidp")
async def trigger_nidp_stock_score(request: Request, as_of_date: Optional[str] = None):
    """Score all stocks from NIDP features (migration 053-055) for the given
    date (YYYY-MM-DD). Defaults to today. No Groww scraping — reads entirely
    from nidp.v_v3_stock_primitives. Run nightly AFTER refresh_stock_features()."""
    await require_admin(request)
    from datetime import date as _date
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))
    from nidp.services.stock_scorer_nidp import refresh_from_nidp

    target = None
    if as_of_date:
        try:
            target = _date.fromisoformat(as_of_date)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "as_of_date must be YYYY-MM-DD")

    result = await refresh_from_nidp(target)
    logger.info("NIDP stock score done: %s/%s", result.get("succeeded", 0), result.get("total", 0))
    return result


# ── Stock master listing ───────────────────────────────────────────────
@router.get("/admin/v3-stock-master")
async def get_v3_stock_master(
    request: Request,
    nifty_100_only: bool = True,
    limit: int = 200,
):
    """List stocks with current V3 scores. Defaults to Nifty 100 subset."""
    await require_admin(request)
    try:
        from services import pg_client as pg
        pool = await pg.get_pool()
        if pool is None:
            return {"funds": [], "total": 0, "error": "Postgres unavailable"}
        async with pool.acquire() as conn:
            filter_sql = "WHERE sm.is_nifty_100 = TRUE" if nifty_100_only else ""
            rows = await conn.fetch(
                f"""
                SELECT sm.nse_symbol, sm.company_name, sm.sector, sm.industry,
                       sm.market_cap_cr, sm.cap_bucket, sm.is_nifty_100,
                       sm.last_scraped_at,
                       ss.quality_score, ss.health_score, ss.exit_score,
                       ss.add_score, ss.recommendation, ss.recommendation_reason,
                       ss.low_confidence, ss.computed_at
                FROM stock_master sm
                LEFT JOIN stock_scores ss ON ss.nse_symbol = sm.nse_symbol
                {filter_sql}
                ORDER BY ss.quality_score DESC NULLS LAST
                LIMIT $1
                """,
                limit,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("v3-stock-master fetch failed: %s", e)
        return {"funds": [], "total": 0, "error": str(e)}

    out = []
    for r in rows:
        out.append({
            "nse_symbol": r["nse_symbol"],
            "company_name": r["company_name"],
            "sector": r["sector"],
            "industry": r["industry"],
            "market_cap_cr": float(r["market_cap_cr"]) if r["market_cap_cr"] is not None else None,
            "cap_bucket": r["cap_bucket"],
            "is_nifty_100": r["is_nifty_100"],
            "last_scraped_at": r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
            "scores": {
                "quality": float(r["quality_score"]) if r["quality_score"] is not None else None,
                "health": float(r["health_score"]) if r["health_score"] is not None else None,
                "exit": float(r["exit_score"]) if r["exit_score"] is not None else None,
                "add": float(r["add_score"]) if r["add_score"] is not None else None,
            },
            "recommendation": r["recommendation"],
            "recommendation_reason": r["recommendation_reason"],
            "low_confidence": bool(r["low_confidence"]) if r["low_confidence"] is not None else True,
            "computed_at": r["computed_at"].isoformat() if r["computed_at"] else None,
        })
    return {"funds": out, "total": len(out), "engine_version": stock_scoring.ENGINE_VERSION}
