"""NIDP-backed stock scoring pipeline.

Reads V3 primitives from nidp.v_v3_stock_primitives (migration 055) and
produces the same {quality_score, health_score, exit_score, add_score,
recommendation} bundle that groww_stock_scraper produces from Groww data.

Call graph (nightly batch):
  refresh_from_nidp(as_of_date)
    └─ for each symbol with features for that date:
         fetch_primitives_nidp(conn, symbol, as_of_date)
         → score_stock(primitives)
         → persist_stock_score(conn, symbol, score_bundle)

On-demand use (decision_engine fallback):
  fetch_primitives_nidp(conn, symbol, as_of_date)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Primitive fetch ────────────────────────────────────────────────────
async def fetch_primitives_nidp(
    conn,
    symbol: str,
    as_of_date: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """Return V3 primitives dict for `symbol` from NIDP bridge view.

    If `as_of_date` is None, uses the most recent date available for that symbol.
    Returns None if no features row exists.
    """
    if as_of_date is None:
        row = await conn.fetchrow(
            """
            SELECT *
              FROM nidp.v_v3_stock_primitives
             WHERE symbol = $1
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            symbol,
        )
    else:
        row = await conn.fetchrow(
            """
            SELECT *
              FROM nidp.v_v3_stock_primitives
             WHERE symbol = $1 AND as_of_date = $2
            """,
            symbol,
            as_of_date,
        )
    if row is None:
        return None

    def _f(key) -> Optional[float]:
        v = row.get(key)
        return float(v) if v is not None else None

    def _b(key) -> Optional[bool]:
        v = row.get(key)
        return bool(v) if v is not None else None

    return {
        # Quality
        "roe_pct":                    _f("roe_pct"),
        "debt_to_equity":             _f("debt_to_equity"),
        "eps_growth_3y_cagr_pct":     _f("eps_growth_3y_cagr_pct"),
        "promoter_holding_pct":       _f("promoter_holding_pct"),
        "cap_bucket":                 row.get("cap_bucket"),          # str: large/mid/small
        "earnings_consistency_score": _f("earnings_consistency_score"),
        # Health
        "revenue_growth_3y_cagr_pct": _f("revenue_growth_3y_cagr_pct"),
        "profit_margin_trend_pct":    _f("profit_margin_trend_pct"),
        "debt_trend_pct":             _f("debt_trend_pct"),
        "earnings_surprise_pct":      None,                            # hard gap
        "volatility_1y_pct":          _f("volatility_1y_pct"),
        "dividend_yield_pct":         _f("dividend_yield_pct"),
        # Exit
        "pe_overvaluation_pct":       _f("pe_overvaluation_pct"),
        "earnings_decline_flag":      _b("earnings_decline_flag"),
        "debt_spike_flag":            _b("debt_spike_flag"),
        "liquidity_score":            _f("liquidity_score"),
        # Add
        "momentum_score":             _f("momentum_score"),
        # Extended context (stored in stock_primitives table)
        "pe_ratio":                   _f("pe_ttm"),
        "pb_ratio":                   _f("pb"),
        "roce_pct":                   _f("roce_pct"),
        "profit_margin_pct":          _f("profit_margin_pct"),
        "return_1y_pct":              _f("return_252d_pct"),
        "beta":                       _f("beta_1y"),
        "max_drawdown_pct":           _f("max_drawdown_1y_pct"),
    }


# ── Score + persist ────────────────────────────────────────────────────
async def score_and_persist_nidp(
    conn,
    symbol: str,
    primitives: Dict[str, Any],
) -> Dict[str, Any]:
    """Score `primitives` with V3 engine and upsert into stock_scores."""
    from services import stock_scoring  # local import avoids circular

    bundle = stock_scoring.score_stock(primitives)
    rec = bundle.get("recommendation") or {}

    await conn.execute(
        """
        INSERT INTO stock_scores (
            nse_symbol, as_of_date, quality_score, health_score,
            exit_score, add_score, quality_components, health_components,
            exit_components, add_components, recommendation,
            recommendation_reason, low_confidence, engine_version, computed_at
        ) VALUES (
            $1, CURRENT_DATE, $2, $3, $4, $5,
            $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb,
            $10, $11, $12, $13, NOW()
        )
        ON CONFLICT (nse_symbol) DO UPDATE SET
            as_of_date          = CURRENT_DATE,
            quality_score       = EXCLUDED.quality_score,
            health_score        = EXCLUDED.health_score,
            exit_score          = EXCLUDED.exit_score,
            add_score           = EXCLUDED.add_score,
            quality_components  = EXCLUDED.quality_components,
            health_components   = EXCLUDED.health_components,
            exit_components     = EXCLUDED.exit_components,
            add_components      = EXCLUDED.add_components,
            recommendation      = EXCLUDED.recommendation,
            recommendation_reason = EXCLUDED.recommendation_reason,
            low_confidence      = EXCLUDED.low_confidence,
            engine_version      = EXCLUDED.engine_version,
            computed_at         = NOW()
        """,
        symbol,
        bundle.get("quality_score"), bundle.get("health_score"),
        bundle.get("exit_score"),    bundle.get("add_score"),
        __import__("json").dumps(bundle.get("quality_components")),
        __import__("json").dumps(bundle.get("health_components")),
        __import__("json").dumps(bundle.get("exit_components")),
        __import__("json").dumps(bundle.get("add_components")),
        rec.get("action"), rec.get("reason"),
        bundle.get("quality_score") is None,
        bundle.get("engine_version"),
    )
    return bundle


# ── Nightly batch ──────────────────────────────────────────────────────
async def refresh_from_nidp(as_of_date: Optional[date] = None) -> Dict[str, Any]:
    """Score all symbols that have features rows for `as_of_date` (default: today).

    Returns a summary dict: {succeeded, failed, skipped, total, errors}.
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))
    from nidp.services import pg_client as pg  # type: ignore

    target_date = as_of_date or date.today()
    pool = await pg.get_pool()
    if pool is None:
        return {"error": "NIDP Postgres pool unavailable"}

    succeeded, failed, skipped = 0, 0, 0
    errors: List[str] = []

    async with pool.acquire() as conn:
        symbols: List[str] = [
            r["symbol"]
            for r in await conn.fetch(
                """
                SELECT DISTINCT symbol
                  FROM nidp.stock_features_daily
                 WHERE as_of_date = $1
                 ORDER BY symbol
                """,
                target_date,
            )
        ]

        logger.info("NIDP stock scorer: %d symbols for %s", len(symbols), target_date)

        for symbol in symbols:
            try:
                primitives = await fetch_primitives_nidp(conn, symbol, target_date)
                if primitives is None:
                    skipped += 1
                    continue
                await score_and_persist_nidp(conn, symbol, primitives)
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                errors.append(f"{symbol}: {exc}")
                logger.warning("NIDP score failed for %s: %s", symbol, exc)

    return {
        "date":      target_date.isoformat(),
        "total":     len(symbols),
        "succeeded": succeeded,
        "failed":    failed,
        "skipped":   skipped,
        "errors":    errors[:20],
    }
