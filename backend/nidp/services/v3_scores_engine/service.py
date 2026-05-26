"""V3 scores engine — compute + persist Quality and Health composites.

Reads primitives from nidp.v_v3_mf_primitives and nidp.v_v3_stock_primitives,
invokes the pure-Python Nivesh scorers, and upserts into the persistence
tables created by migration 065.

Coverage:
    For each (sub-score, scheme/symbol) we record coverage_pct = fraction of
    intended weight backed by a non-NULL primitive. The MF scorer surfaces
    `missing_primitives` directly; for stocks (normalisers fall back to 50
    instead of None) we measure coverage at the engine layer by checking the
    primitive dict.
"""
from __future__ import annotations

import decimal
import json
import logging
import os
import sys
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


# The Nivesh-side scorers live at /app/backend/services/. Engine code lives
# in /app/backend/nidp/services/, so we add the parent on sys.path once.
_NIVESH_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../"))
if _NIVESH_BACKEND not in sys.path:
    sys.path.insert(0, _NIVESH_BACKEND)


# Primitive sets used to measure stock coverage (mirrors stock_scoring weights).
_STOCK_QUALITY_PRIMS = (
    "roe_pct", "debt_to_equity", "eps_growth_3y_cagr_pct",
    "promoter_holding_pct", "cap_bucket", "earnings_consistency_score",
)
_STOCK_HEALTH_PRIMS = (
    "revenue_growth_3y_cagr_pct", "profit_margin_trend_pct", "debt_trend_pct",
    "earnings_surprise_pct", "volatility_1y_pct", "dividend_yield_pct",
)


def _coverage_from_missing(
    weight_profile: Dict[str, int], missing: List[str],
) -> Optional[float]:
    """MF path: scorer reports missing components + original weights."""
    total = sum(w for w in weight_profile.values())
    if total <= 0:
        return None
    miss_w = sum(weight_profile.get(m, 0) for m in (missing or []))
    return round(max(0.0, min(100.0, (1.0 - miss_w / total) * 100.0)), 2)


def _coverage_from_dict(prims: Dict[str, Any], keys: Tuple[str, ...]) -> float:
    """Stock path: fraction of expected primitives present in the input dict."""
    if not keys:
        return 0.0
    have = sum(1 for k in keys if prims.get(k) is not None)
    return round(100.0 * have / len(keys), 2)


# ── MF scoring ─────────────────────────────────────────────────────────
async def _score_mf(conn, target_date: date) -> int:
    """Score every scheme that has a primitive row for target_date."""
    from services import v3_scoring  # noqa: WPS433  (Nivesh-side)

    # The primitives view is not date-keyed (it serves "latest" per scheme).
    # We treat target_date as the as_of_date stamp for the score row.
    rows = await conn.fetch(
        """
        SELECT *
          FROM nidp.v_v3_mf_primitives
         WHERE isin IS NOT NULL
        """,
    )
    if not rows:
        logger.info("v3_scores_engine[mf]: no primitive rows")
        return 0

    written = 0
    for row in rows:
        f = {
            k: float(v) if isinstance(v, decimal.Decimal) else v
            for k, v in ((k, row.get(k)) for k in row.keys())
        }

        try:
            q = v3_scoring.compute_quality_score(f)
            h = v3_scoring.compute_health_score(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning("v3_scores_engine[mf] %s: scorer raised %s", f.get("isin"), exc)
            continue

        q_weights = q.get("weight_profile") or {}
        h_weights = h.get("weight_profile") or {}
        q_coverage = _coverage_from_missing(q_weights, q.get("missing_primitives") or [])
        h_coverage = _coverage_from_missing(h_weights, h.get("missing_primitives") or [])

        try:
            await conn.execute(
                """
                INSERT INTO nidp.v3_mf_scores_daily (
                    as_of_date, isin, scheme_code, scheme_name,
                    fund_category, sub_category,
                    quality_score, quality_components, quality_missing,
                    quality_eff_weights, quality_coverage_pct,
                    health_score, health_components, health_missing,
                    health_eff_weights, health_coverage_pct,
                    weight_profile, engine_version
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6,
                    $7, $8::jsonb, $9::text[],
                    $10::jsonb, $11,
                    $12, $13::jsonb, $14::text[],
                    $15::jsonb, $16,
                    $17::jsonb, $18
                )
                ON CONFLICT (as_of_date, isin) DO UPDATE SET
                    scheme_code          = EXCLUDED.scheme_code,
                    scheme_name          = EXCLUDED.scheme_name,
                    fund_category        = EXCLUDED.fund_category,
                    sub_category         = EXCLUDED.sub_category,
                    quality_score        = EXCLUDED.quality_score,
                    quality_components   = EXCLUDED.quality_components,
                    quality_missing      = EXCLUDED.quality_missing,
                    quality_eff_weights  = EXCLUDED.quality_eff_weights,
                    quality_coverage_pct = EXCLUDED.quality_coverage_pct,
                    health_score         = EXCLUDED.health_score,
                    health_components    = EXCLUDED.health_components,
                    health_missing       = EXCLUDED.health_missing,
                    health_eff_weights   = EXCLUDED.health_eff_weights,
                    health_coverage_pct  = EXCLUDED.health_coverage_pct,
                    weight_profile       = EXCLUDED.weight_profile,
                    engine_version       = EXCLUDED.engine_version,
                    computed_at          = NOW()
                """,
                target_date,
                f.get("isin"),
                f.get("scheme_code"),
                f.get("scheme_name"),
                q.get("category"),
                f.get("sub_category"),
                q.get("score"),
                json.dumps(q.get("components") or {}),
                q.get("missing_primitives") or [],
                json.dumps(q.get("effective_weights") or {}),
                q_coverage,
                h.get("score"),
                json.dumps(h.get("components") or {}),
                h.get("missing_primitives") or [],
                json.dumps(h.get("effective_weights") or {}),
                h_coverage,
                json.dumps({"quality": q_weights, "health": h_weights}),
                getattr(v3_scoring, "ENGINE_VERSION", "v3"),
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("v3_scores_engine[mf] %s persist failed: %s", f.get("isin"), exc)

    logger.info("v3_scores_engine[mf]: wrote %d / %d", written, len(rows))
    return written


# ── Stock scoring ──────────────────────────────────────────────────────
async def _score_stocks(conn, target_date: date) -> int:
    """Score every symbol that has a v_v3_stock_primitives row for target_date."""
    from services import stock_scoring  # noqa: WPS433  (Nivesh-side)

    rows = await conn.fetch(
        """
        SELECT *
          FROM nidp.v_v3_stock_primitives
         WHERE as_of_date = $1
        """,
        target_date,
    )
    if not rows:
        # Fall back to latest date if target_date has nothing yet (engine
        # may run before TI/fundamental have published the day's row).
        latest = await conn.fetchval(
            "SELECT MAX(as_of_date) FROM nidp.v_v3_stock_primitives"
        )
        if latest is None:
            logger.info("v3_scores_engine[stock]: primitive view empty")
            return 0
        logger.info("v3_scores_engine[stock]: no rows for %s, falling back to %s",
                    target_date, latest)
        rows = await conn.fetch(
            "SELECT * FROM nidp.v_v3_stock_primitives WHERE as_of_date = $1",
            latest,
        )
        target_date = latest

    written = 0
    for row in rows:
        prims = {
            k: float(v) if isinstance(v, decimal.Decimal) else v
            for k, v in ((k, row.get(k)) for k in row.keys())
        }

        # Normalise the cap_bucket alias (view returns CASE-derived 'large'/'mid'/'small')
        if prims.get("cap_bucket") is None and prims.get("market_cap_bucket"):
            mc = str(prims["market_cap_bucket"]).upper()
            prims["cap_bucket"] = (
                "large" if mc == "LARGE_CAP" else
                "mid"   if mc == "MID_CAP"   else
                "small" if mc in ("SMALL_CAP", "MICRO_CAP") else None
            )

        try:
            q = stock_scoring.compute_quality_score(prims)
            h = stock_scoring.compute_health_score(prims)
        except Exception as exc:  # noqa: BLE001
            logger.warning("v3_scores_engine[stock] %s: scorer raised %s", prims.get("symbol"), exc)
            continue

        q_coverage = _coverage_from_dict(prims, _STOCK_QUALITY_PRIMS)
        h_coverage = _coverage_from_dict(prims, _STOCK_HEALTH_PRIMS)

        try:
            await conn.execute(
                """
                INSERT INTO nidp.v3_stock_scores_daily (
                    as_of_date, symbol, sector, industry, market_cap_bucket,
                    quality_score, quality_components, quality_coverage_pct,
                    health_score,  health_components,  health_coverage_pct,
                    engine_version
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7::jsonb, $8,
                    $9, $10::jsonb, $11,
                    $12
                )
                ON CONFLICT (as_of_date, symbol) DO UPDATE SET
                    sector               = EXCLUDED.sector,
                    industry             = EXCLUDED.industry,
                    market_cap_bucket    = EXCLUDED.market_cap_bucket,
                    quality_score        = EXCLUDED.quality_score,
                    quality_components   = EXCLUDED.quality_components,
                    quality_coverage_pct = EXCLUDED.quality_coverage_pct,
                    health_score         = EXCLUDED.health_score,
                    health_components    = EXCLUDED.health_components,
                    health_coverage_pct  = EXCLUDED.health_coverage_pct,
                    engine_version       = EXCLUDED.engine_version,
                    computed_at          = NOW()
                """,
                target_date,
                prims.get("symbol"),
                prims.get("sector"),
                prims.get("industry"),
                prims.get("market_cap_bucket"),
                q.get("score"),
                json.dumps(q.get("components") or {}),
                q_coverage,
                h.get("score"),
                json.dumps(h.get("components") or {}),
                h_coverage,
                getattr(stock_scoring, "ENGINE_VERSION", "v3"),
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("v3_scores_engine[stock] %s persist failed: %s", prims.get("symbol"), exc)

    logger.info("v3_scores_engine[stock]: wrote %d / %d", written, len(rows))
    return written


# ── Entry point ────────────────────────────────────────────────────────
async def run(
    target_date: Optional[date] = None,
    domain: str = "both",
) -> Dict[str, Any]:
    """Score the chosen domain(s) and return a summary."""
    target_date = target_date or date.today()
    pool = await get_pool()

    summary: Dict[str, Any] = {
        "as_of_date":  target_date.isoformat(),
        "domain":      domain,
        "mf_written":     0,
        "stock_written":  0,
    }

    async with pool.acquire() as conn:
        if domain in ("mf", "both"):
            summary["mf_written"] = await _score_mf(conn, target_date)
        if domain in ("stock", "both"):
            summary["stock_written"] = await _score_stocks(conn, target_date)

    summary["rows_written"] = summary["mf_written"] + summary["stock_written"]
    return summary
