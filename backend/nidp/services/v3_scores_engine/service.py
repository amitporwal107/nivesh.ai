"""V3 scores engine — compute + persist sector-aware stock scores and MF scores.

Stock scoring (V3):
    Every stock is scored through the sector-aware pipeline in
    nidp.services.sector_scoring.  The final_score (0–100) and band
    (STRONG_BUY → AVOID) are the primary outputs.  For backward compat,
    quality_score mirrors final_score and health_score mirrors technical_score
    so that existing API endpoints continue to work without changes.

MF scoring:
    Mutual funds are scored through the existing v3_scoring path unchanged.

Two-pass approach for stocks:
    Pass 1 — compute sector scores for all stocks (sector_rank_pct=None).
    Pass 2 — rank each stock within its sector peer group, then re-assign
             band using sector-relative thresholds (top decile → STRONG_BUY, etc.)
"""
from __future__ import annotations

import decimal
import json
import logging
import os
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)


# The Nivesh-side MF scorer lives at /app/backend/services/.  Engine code lives
# in /app/backend/nidp/services/, so we add the parent on sys.path once.
_NIVESH_BACKEND = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../../"))
if _NIVESH_BACKEND not in sys.path:
    sys.path.insert(0, _NIVESH_BACKEND)


def _coverage_from_missing(
    weight_profile: Dict[str, int], missing: List[str],
) -> Optional[float]:
    """MF path: scorer reports missing components + original weights."""
    total = sum(w for w in weight_profile.values())
    if total <= 0:
        return None
    miss_w = sum(weight_profile.get(m, 0) for m in (missing or []))
    return round(max(0.0, min(100.0, (1.0 - miss_w / total) * 100.0)), 2)


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


# ── Sector scoring helpers ─────────────────────────────────────────────

async def _fetch_tech_data(conn, target_date: date) -> Dict[str, Dict[str, Any]]:
    """Fetch extra tech fields from stock_features_daily not in primitives view.

    Returns {symbol: {close, sma50, sma200, sma50_slope, dist_52w_high_pct,
                       return_60d_pct, vol_z20, deliv_pct_avg_20}}.
    Falls back to latest available date if target_date has no rows.
    """
    rows = await conn.fetch(
        """SELECT symbol, close, sma50, sma200, sma50_slope,
                  dist_52w_high_pct, return_60d_pct, vol_z20, deliv_pct_avg_20
             FROM nidp.stock_features_daily
            WHERE as_of_date = $1""",
        target_date,
    )
    if not rows:
        latest = await conn.fetchval(
            "SELECT MAX(as_of_date) FROM nidp.stock_features_daily"
        )
        if latest:
            rows = await conn.fetch(
                """SELECT symbol, close, sma50, sma200, sma50_slope,
                          dist_52w_high_pct, return_60d_pct, vol_z20, deliv_pct_avg_20
                     FROM nidp.stock_features_daily
                    WHERE as_of_date = $1""",
                latest,
            )
    return {
        r["symbol"]: {
            k: (float(v) if isinstance(v, decimal.Decimal) else v)
            for k, v in r.items()
        }
        for r in (rows or [])
    }


async def _fetch_bank_metrics(conn, target_date: date) -> Dict[str, Dict[str, Any]]:
    """Fetch bank_metrics_daily for target_date (or latest available).

    Returns {symbol: row_dict}.
    """
    rows = await conn.fetch(
        "SELECT * FROM nidp.bank_metrics_daily WHERE as_of_date = $1",
        target_date,
    )
    if not rows:
        latest = await conn.fetchval(
            "SELECT MAX(as_of_date) FROM nidp.bank_metrics_daily"
        )
        if latest:
            rows = await conn.fetch(
                "SELECT * FROM nidp.bank_metrics_daily WHERE as_of_date = $1",
                latest,
            )
    return {
        r["symbol"]: {
            k: (float(v) if isinstance(v, decimal.Decimal) else v)
            for k, v in r.items()
        }
        for r in (rows or [])
    }


async def _fetch_event_signals(
    conn, target_date: date
) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch corporate_event_signals for the 180 days ending on target_date.

    Returns {symbol: [{event_type, event_date}, ...]}.
    """
    cutoff = target_date - timedelta(days=180)
    rows = await conn.fetch(
        """SELECT symbol, event_type, event_date
             FROM nidp.corporate_event_signals
            WHERE event_date >= $1
              AND event_date <= $2
         ORDER BY symbol, event_date""",
        cutoff,
        target_date,
    )
    events: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        sym = r["symbol"]
        events.setdefault(sym, []).append({
            "event_type": r["event_type"],
            "event_date": r["event_date"],  # already a datetime.date
        })
    return events


def _compute_sector_rank_pcts(
    sym_to_score: Dict[str, Optional[float]],
    sym_to_profile: Dict[str, str],
) -> Dict[str, float]:
    """For each symbol compute its percentile rank within its sector profile.

    Only profiles with ≥3 stocks produce a meaningful rank; others are skipped
    (band falls back to absolute thresholds).

    Returns {symbol: percentile_0_to_100}.
    """
    # Group final_scores by profile
    profile_entries: Dict[str, List[Tuple[str, float]]] = {}
    for sym, score in sym_to_score.items():
        if score is None:
            continue
        profile = sym_to_profile.get(sym, "DEFAULT")
        profile_entries.setdefault(profile, []).append((sym, score))

    rank_pcts: Dict[str, float] = {}
    for profile, entries in profile_entries.items():
        if len(entries) < 3:
            continue
        scores_sorted = sorted(s for _, s in entries)
        n = len(scores_sorted)
        for sym, score in entries:
            # Fraction of peers with score ≤ this score → percentile 0–100
            rank = sum(1 for s in scores_sorted if s <= score)
            rank_pcts[sym] = round(100.0 * rank / n, 1)

    return rank_pcts


# ── Stock scoring ──────────────────────────────────────────────────────
async def _score_stocks(conn, target_date: date) -> int:
    """Score every symbol that has a v_v3_stock_primitives row for target_date.

    V3 sector-aware scoring is the sole stock scorer.  The result is written to
    the new sector columns AND mirrored into quality_score/quality_components
    for backward compatibility with API endpoints that still read those columns.
    The legacy generic stock_scoring.py path is no longer called for stocks.
    """
    from nidp.services.sector_scoring.composer import score_stock, _assign_band
    from nidp.services.sector_scoring.coverage import aggregate_feed_gaps

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

    # ── Batch-fetch supplemental data for sector scoring ──────────────
    tech_by_symbol   = await _fetch_tech_data(conn, target_date)
    bank_by_symbol   = await _fetch_bank_metrics(conn, target_date)
    events_by_symbol = await _fetch_event_signals(conn, target_date)

    logger.info(
        "v3_scores_engine[stock]: supplemental data — tech=%d bank=%d event_syms=%d",
        len(tech_by_symbol), len(bank_by_symbol), len(events_by_symbol),
    )

    # ── Normalise all primitive rows ───────────────────────────────────
    all_prims: List[Dict[str, Any]] = []
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
        all_prims.append(prims)

    # ── Pass 1: sector-aware scores for all stocks (rank=None) ────────
    _AVOID_EVENT_TYPES = frozenset({
        "RBI_PCA_ACTION", "IMPORT_ALERT", "AUDITOR_RESIGNATION",
        "SEBI_ORDER", "CONSENT_DECREE",
    })
    per_stock_ss: Dict[str, Any] = {}  # symbol → SectorScore

    for prims in all_prims:
        sym = prims.get("symbol")
        try:
            ss = score_stock(
                symbol=sym,
                as_of_date=target_date,
                prims=prims,
                tech_data=tech_by_symbol.get(sym, {}),
                bank_metrics=bank_by_symbol.get(sym),
                event_signals=events_by_symbol.get(sym, []),
                sector_rank_pct=None,  # filled in pass 2
            )
            per_stock_ss[sym] = ss
        except Exception as exc:  # noqa: BLE001
            logger.warning("v3_scores_engine[sector] %s: scorer raised %s", sym, exc)

    # ── Pass 2: compute sector rank percentiles + update bands ────────
    rank_pcts = _compute_sector_rank_pcts(
        sym_to_score={sym: ss.final_score for sym, ss in per_stock_ss.items()},
        sym_to_profile={sym: ss.sector_profile for sym, ss in per_stock_ss.items()},
    )
    for sym, ss in per_stock_ss.items():
        pct = rank_pcts.get(sym)
        if pct is not None:
            avoid = [
                e["event_type"] for e in events_by_symbol.get(sym, [])
                if e.get("event_type") in _AVOID_EVENT_TYPES
            ]
            ss.band = _assign_band(ss.final_score, pct, avoid)

    logger.info(
        "v3_scores_engine[sector]: scored %d stocks; rank percentiles for %d",
        len(per_stock_ss), len(rank_pcts),
    )

    # ── Coverage / feed-gap report ────────────────────────────────────
    from nidp.services.sector_scoring.coverage import CoverageResult
    cov_list = [
        CoverageResult(
            profile=ss.sector_profile,
            total=0,  # not needed for aggregate
            present=0,
            missing=ss.missing_primitives,
            missing_by_feed=ss.missing_by_feed,
            coverage_pct=ss.coverage_pct,
        )
        for ss in per_stock_ss.values()
    ]
    feed_gaps = aggregate_feed_gaps(cov_list)

    logger.info(
        "v3_scores_engine[coverage]: %d/%d stocks fully covered (%.1f%%). "
        "Feed gaps: %s",
        feed_gaps["fully_covered"],
        feed_gaps["total_stocks"],
        feed_gaps["coverage_pct"],
        {
            feed: f"{info['stocks_with_gaps']} stocks"
            for feed, info in feed_gaps["by_feed"].items()
            if info["stocks_with_gaps"] > 0
        },
    )
    # Log the worst primitives (missing for >10% of stocks) as WARNING
    for field_name, info in feed_gaps["by_field"].items():
        if info["missing_pct"] >= 10.0:
            logger.warning(
                "v3_scores_engine[coverage]: '%s' missing for %.1f%% of stocks "
                "(feed: %s) — fix the %s ingester",
                field_name, info["missing_pct"], info["feed"], info["feed"],
            )

    # Persist coverage report as a JSONB audit row in v3_stock_scores_daily
    # (stored on the sentinel row symbol='__coverage__' for easy querying)
    try:
        await conn.execute(
            """
            INSERT INTO nidp.v3_stock_scores_daily
                (as_of_date, symbol, sector, engine_version, sub_scores_jsonb)
            VALUES ($1, '__coverage__', 'SYSTEM', 'v3-sector', $2::jsonb)
            ON CONFLICT (as_of_date, symbol) DO UPDATE
                SET sub_scores_jsonb = EXCLUDED.sub_scores_jsonb,
                    computed_at      = NOW()
            """,
            target_date,
            json.dumps(feed_gaps),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("v3_scores_engine[coverage]: failed to persist gap report: %s", exc)

    # ── Persist ────────────────────────────────────────────────────────
    # quality_score is mirrored from final_score for backward compat.
    # quality_components carries the sector sub-score breakdown.
    # health_score is mirrored from technical_score (the cross-sector signal).
    written = 0
    for prims in all_prims:
        sym = prims.get("symbol")
        ss  = per_stock_ss.get(sym)
        if not ss:
            continue

        sector_coverage = ss.coverage_pct

        try:
            await conn.execute(
                """
                INSERT INTO nidp.v3_stock_scores_daily (
                    as_of_date, symbol, sector, industry, market_cap_bucket,
                    quality_score, quality_components, quality_coverage_pct,
                    health_score,  health_components,  health_coverage_pct,
                    engine_version,
                    sector_profile, fundamental_score, technical_score,
                    cycle_position_score, event_overlay, red_flag_penalty,
                    sub_scores_jsonb, final_score, band
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7::jsonb, $8,
                    $9, $10::jsonb, $11,
                    $12,
                    $13, $14, $15,
                    $16, $17, $18,
                    $19::jsonb, $20, $21
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
                    sector_profile       = EXCLUDED.sector_profile,
                    fundamental_score    = EXCLUDED.fundamental_score,
                    technical_score      = EXCLUDED.technical_score,
                    cycle_position_score = EXCLUDED.cycle_position_score,
                    event_overlay        = EXCLUDED.event_overlay,
                    red_flag_penalty     = EXCLUDED.red_flag_penalty,
                    sub_scores_jsonb     = EXCLUDED.sub_scores_jsonb,
                    final_score          = EXCLUDED.final_score,
                    band                 = EXCLUDED.band,
                    computed_at          = NOW()
                """,
                target_date,
                sym,
                prims.get("sector"),
                prims.get("industry"),
                prims.get("market_cap_bucket"),
                # quality_score = final_score (backward compat mirror)
                ss.final_score,
                json.dumps(ss.sub_scores),
                sector_coverage,
                # health_score = technical_score (cross-sector momentum signal)
                ss.technical_score,
                json.dumps(ss.sub_scores.get("technical", {})),
                sector_coverage,
                "v3-sector",
                ss.sector_profile,
                ss.fundamental_score,
                ss.technical_score,
                ss.cycle_position_score,
                ss.event_overlay,
                ss.red_flag_penalty,
                json.dumps(ss.sub_scores),
                ss.final_score,
                ss.band,
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("v3_scores_engine[stock] %s persist failed: %s", sym, exc)

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
