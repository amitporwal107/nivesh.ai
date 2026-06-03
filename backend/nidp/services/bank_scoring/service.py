"""Bank quality scoring service.

Reads from:
  nidp.nse_financials_quarterly   — raw_data JSONB time series (Screener.in data)
  nidp.v_shareholding_latest      — promoter_pct for PSU/private classification
  nidp.stock_features_daily       — roe_pct

Writes to:
  nidp.bank_metrics_daily
  nidp.bank_quality_scores_daily
"""
from __future__ import annotations

import json
import logging
import math
import statistics
from datetime import date
from typing import Any, Dict, List, Optional

def _parse_raw(raw_data) -> Optional[Dict]:
    """asyncpg may return JSONB as a str; normalise to dict."""
    if raw_data is None:
        return None
    if isinstance(raw_data, str):
        try:
            return json.loads(raw_data)
        except Exception:
            return None
    return raw_data

from nidp.shared.storage.pg import get_pool

from .scorer import (
    classify_bank,
    compute_bank_quality_score,
)

logger = logging.getLogger(__name__)

ENGINE_VERSION = "v1"


# ─── Metric extraction helpers ────────────────────────────────────────────────

def _arr(raw_data: Optional[Dict], key: str) -> List[Optional[float]]:
    """Extract a named array from raw_data['data'], returning [] if absent."""
    if not raw_data:
        return []
    data = raw_data.get("data") or {}
    vals = data.get(key)
    if not vals or not isinstance(vals, list):
        return []
    result: List[Optional[float]] = []
    for v in vals:
        if v is None:
            result.append(None)
        else:
            try:
                result.append(float(v))
            except (TypeError, ValueError):
                result.append(None)
    return result


def _latest(arr: List[Optional[float]]) -> Optional[float]:
    """Return the last non-null element of an array (most recent quarter)."""
    for v in reversed(arr):
        if v is not None:
            return v
    return None


def _yoy_growth(arr: List[Optional[float]]) -> Optional[float]:
    """YoY growth: compare latest (index -1) to 4 quarters ago (index -5)."""
    vals = [v for v in arr if v is not None]
    if len(vals) < 5:
        return None
    latest = vals[-1]
    year_ago = vals[-5]
    if year_ago is None or year_ago == 0:
        return None
    return round((latest - year_ago) / abs(year_ago) * 100.0, 2)


def _earnings_consistency(pat_arr: List[Optional[float]]) -> Optional[float]:
    """Return a 0–100 consistency score based on CoV of 8-quarter PAT.

    Coefficient of Variation (std/mean): lower = more consistent = higher score.
    Score = max(0, 100 - CoV * 200) capped at 0–100.
    """
    vals = [v for v in pat_arr if v is not None and v != 0]
    if len(vals) < 4:
        return None
    recent = vals[-8:]
    if len(recent) < 4:
        return None
    # Ignore sign flips (negative PAT distorts CoV badly)
    mean_val = statistics.mean(recent)
    if mean_val <= 0:
        return 20.0  # loss-making = low quality
    try:
        stdev = statistics.stdev(recent)
    except statistics.StatisticsError:
        return 50.0
    cov = stdev / abs(mean_val)
    score = max(0.0, min(100.0, 100.0 - cov * 200.0))
    return round(score, 2)


def _annualised_pat_from_series(pat: List[Optional[float]]) -> Optional[float]:
    """Annualised PAT from the raw_data quarterly series.

    Banks' March-quarter structured pat_cr column includes the cumulative annual
    figure (not just Q4), so we use the Screener time series instead — which has
    consistent quarterly values.  Average of the last 4 non-null quarters × 4.
    """
    vals = [v for v in pat if v is not None and v > 0]
    if not vals:
        return None
    recent = vals[-4:]
    return round(statistics.mean(recent) * 4, 2)


def _extract_metrics(raw_data: Optional[Dict], total_equity_cr: Optional[float]) -> Dict[str, Any]:
    """Compute all intermediate bank metrics from raw_data time series + consolidated equity.

    raw_data: Screener.in 13-quarter time series (oldest-first arrays).
    total_equity_cr: from the consolidated balance sheet row (most accurate equity base).
    Note: Screener 'expenses' includes provisions, so we use PAT margin instead of C2I.
    """
    rev = _arr(raw_data, "revenue")       # interest earned (quarterly)
    intr = _arr(raw_data, "interest")     # interest expended (quarterly)
    pat = _arr(raw_data, "net profit")    # quarterly PAT from Screener
    other = _arr(raw_data, "other income")
    gnpa_s = _arr(raw_data, "gross npa %")
    nnpa_s = _arr(raw_data, "net npa %")

    rev_latest = _latest(rev)
    intr_latest = _latest(intr)
    pat_latest = _latest(pat)
    other_latest = _latest(other)
    gnpa_latest = _latest(gnpa_s)
    nnpa_latest = _latest(nnpa_s)

    # NII = revenue - interest (true quarterly basis from Screener time series)
    nii = (rev_latest - intr_latest) if (rev_latest and intr_latest) else None

    # NII retention = NII / gross interest earned × 100
    # Higher = bank retains more interest earned = lower cost of funds = strong CASA franchise
    nii_retention = (
        round(nii / rev_latest * 100.0, 2)
        if (nii is not None and rev_latest and rev_latest > 0)
        else None
    )

    # PAT margin = PAT / (interest earned + other income) × 100
    # Used instead of cost-to-income because Screener's 'expenses' includes provisions,
    # making raw C2I unreliable. PAT margin captures both operating efficiency AND
    # credit quality (heavy provisioning = lower PAT margin).
    total_income = (rev_latest or 0) + (other_latest or 0)
    pat_margin = (
        round(pat_latest / total_income * 100.0, 2)
        if (pat_latest and total_income > 0)
        else None
    )

    # Fee income mix = other_income / total_income × 100 (revenue diversification)
    fee_mix = (
        round(other_latest / total_income * 100.0, 2)
        if (other_latest and total_income > 0)
        else None
    )

    # ROE: annualised quarterly PAT (from Screener series, avoids March annual bias)
    # / consolidated total equity
    ann_pat = _annualised_pat_from_series(pat)
    roe: Optional[float] = None
    if ann_pat and total_equity_cr and total_equity_cr > 0:
        roe = round(ann_pat / total_equity_cr * 100.0, 2)

    # YoY growths
    pat_yoy = _yoy_growth(pat)
    rev_yoy = _yoy_growth(rev)

    # Earnings consistency
    consistency = _earnings_consistency(pat)

    # GNPA trend label
    gnpa_trend = _gnpa_trend_label(gnpa_s)
    gnpa_4q_ago = _gnpa_4q_ago(gnpa_s)

    return {
        "gnpa_pct": gnpa_latest,
        "nnpa_pct": nnpa_latest,
        "gnpa_series": gnpa_s,
        "gnpa_trend": gnpa_trend,
        "gnpa_4q_ago": gnpa_4q_ago,
        "nii_cr": round(nii, 2) if nii is not None else None,
        "nii_retention_pct": nii_retention,
        "pat_margin_pct": pat_margin,     # replaces C2I (see docstring)
        "roe_pct": roe,
        "pat_yoy_growth_pct": pat_yoy,
        "fee_income_mix_pct": fee_mix,
        "revenue_yoy_growth_pct": rev_yoy,
        "earnings_consistency": consistency,
    }


def _gnpa_trend_label(gnpa_s: List[Optional[float]]) -> Optional[str]:
    """Return 'improving' | 'stable' | 'worsening' based on 4Q change."""
    vals = [v for v in gnpa_s if v is not None]
    if len(vals) < 5:
        return None
    recent, year_ago = vals[-1], vals[-5]
    delta = recent - year_ago
    if delta < -0.3:
        return "improving"
    if delta > 0.3:
        return "worsening"
    return "stable"


def _gnpa_4q_ago(gnpa_s: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in gnpa_s if v is not None]
    return vals[-5] if len(vals) >= 5 else None


# ─── DB orchestration ─────────────────────────────────────────────────────────

_BANK_SYMBOLS_SQL = """(
    SELECT DISTINCT symbol FROM nidp.stock_features_daily WHERE sector = 'BANKING'
    UNION
    SELECT unnest(ARRAY[
        'SBIN','PNB','BANKBARODA','CANBK','UNIONBANK','BANKINDIA',
        'INDIANB','IOB','MAHABANK','UCOBANK',
        'HDFCBANK','ICICIBANK','AXISBANK','KOTAKBANK','INDUSINDBK',
        'YESBANK','AUBANK','BANDHANBNK','IDFCFIRSTB','FEDERALBNK',
        'CUB','RBLBANK','J&KBANK','DCBBANK','KTKBANK'
    ])
)"""


async def _load_bank_rows(conn, target_date: date):
    """Fetch latest quarterly row per bank symbol with consolidated balance sheet equity.

    Strategy (user instruction: rely on consolidated balance sheet):
      1. raw_data (Screener time series) comes from whichever row has it — prefer consolidated,
         fall back to standalone if no consolidated raw_data exists.
      2. total_equity_cr always comes from the most recent *consolidated* balance sheet row
         (more accurate denominator for ROE than standalone equity).
    """
    rows = await conn.fetch(
        f"""
        WITH bank_symbols AS (SELECT symbol FROM {_BANK_SYMBOLS_SQL} bs),
        -- Best raw_data row: consolidated preferred, then standalone
        latest_raw AS (
            SELECT DISTINCT ON (f.symbol)
                f.symbol,
                f.raw_data,
                f.consolidated as raw_is_consolidated,
                f.period_end
            FROM nidp.nse_financials_quarterly f
            JOIN bank_symbols USING (symbol)
            WHERE f.raw_data IS NOT NULL
              AND f.period_end <= $1
            ORDER BY f.symbol,
                     f.consolidated DESC,   -- prefer consolidated (TRUE > FALSE)
                     f.period_end DESC
        ),
        -- Consolidated equity: most recent balance sheet row
        latest_cons_equity AS (
            SELECT DISTINCT ON (f.symbol)
                f.symbol,
                f.total_equity_cr AS cons_equity_cr
            FROM nidp.nse_financials_quarterly f
            JOIN bank_symbols USING (symbol)
            WHERE f.consolidated = TRUE
              AND f.total_equity_cr IS NOT NULL
              AND f.period_end <= $1
            ORDER BY f.symbol, f.period_end DESC
        )
        SELECT
            r.symbol,
            r.raw_data,
            r.raw_is_consolidated,
            COALESCE(ce.cons_equity_cr, sa.total_equity_cr) AS total_equity_cr,
            r.period_end,
            sh.promoter_pct
        FROM latest_raw r
        -- Standalone equity fallback (for banks with no consolidated rows)
        LEFT JOIN (
            SELECT DISTINCT ON (symbol) symbol, total_equity_cr
            FROM nidp.nse_financials_quarterly
            WHERE consolidated = FALSE AND total_equity_cr IS NOT NULL
              AND period_end <= $1
            ORDER BY symbol, period_end DESC
        ) sa USING (symbol)
        LEFT JOIN latest_cons_equity ce USING (symbol)
        LEFT JOIN nidp.v_shareholding_latest sh USING (symbol)
        """,
        target_date,
    )
    return rows


async def _upsert_metrics(conn, symbol: str, as_of_date: date, m: Dict, bank_type: str) -> None:
    await conn.execute(
        """
        INSERT INTO nidp.bank_metrics_daily (
            symbol, as_of_date,
            gnpa_pct, nnpa_pct, pcr_implied_pct, gnpa_trend, gnpa_4q_ago,
            nii_cr, nii_retention_pct, pat_margin_pct,
            roe_pct, pat_yoy_growth_pct,
            fee_income_mix_pct, revenue_yoy_growth_pct,
            earnings_consistency, has_npa_data, coverage_pct
        ) VALUES (
            $1, $2,
            $3, $4, $5, $6, $7,
            $8, $9, $10,
            $11, $12,
            $13, $14,
            $15, $16, $17
        )
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            gnpa_pct              = EXCLUDED.gnpa_pct,
            nnpa_pct              = EXCLUDED.nnpa_pct,
            pcr_implied_pct       = EXCLUDED.pcr_implied_pct,
            gnpa_trend            = EXCLUDED.gnpa_trend,
            gnpa_4q_ago           = EXCLUDED.gnpa_4q_ago,
            nii_cr                = EXCLUDED.nii_cr,
            nii_retention_pct     = EXCLUDED.nii_retention_pct,
            pat_margin_pct    = EXCLUDED.pat_margin_pct,
            roe_pct               = EXCLUDED.roe_pct,
            pat_yoy_growth_pct    = EXCLUDED.pat_yoy_growth_pct,
            fee_income_mix_pct    = EXCLUDED.fee_income_mix_pct,
            revenue_yoy_growth_pct= EXCLUDED.revenue_yoy_growth_pct,
            earnings_consistency  = EXCLUDED.earnings_consistency,
            has_npa_data          = EXCLUDED.has_npa_data,
            coverage_pct          = EXCLUDED.coverage_pct,
            computed_at           = NOW()
        """,
        symbol, as_of_date,
        m["gnpa_pct"], m["nnpa_pct"],
        _implied_pcr(m["gnpa_pct"], m["nnpa_pct"]),
        m["gnpa_trend"], m["gnpa_4q_ago"],
        m["nii_cr"], m["nii_retention_pct"], m["pat_margin_pct"],
        m["roe_pct"], m["pat_yoy_growth_pct"],
        m["fee_income_mix_pct"], m["revenue_yoy_growth_pct"],
        m["earnings_consistency"],
        m["gnpa_pct"] is not None,
        _coverage(m),
    )


def _implied_pcr(gnpa: Optional[float], nnpa: Optional[float]) -> Optional[float]:
    if gnpa and gnpa > 0 and nnpa is not None:
        return round((1.0 - nnpa / gnpa) * 100.0, 2)
    return None


def _coverage(m: Dict) -> float:
    keys = ["gnpa_pct", "nnpa_pct", "nii_retention_pct", "pat_margin_pct",
            "roe_pct", "pat_yoy_growth_pct", "fee_income_mix_pct",
            "revenue_yoy_growth_pct", "earnings_consistency"]
    have = sum(1 for k in keys if m.get(k) is not None)
    return round(100.0 * have / len(keys), 1)


async def _upsert_scores(conn, symbol: str, as_of_date: date, sc) -> None:
    await conn.execute(
        """
        INSERT INTO nidp.bank_quality_scores_daily (
            symbol, as_of_date,
            asset_quality_score, profitability_score,
            liability_franchise_score, earnings_quality_score,
            growth_score, bank_quality_score,
            has_npa_data, coverage_pct, engine_version
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
        )
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            asset_quality_score       = EXCLUDED.asset_quality_score,
            profitability_score       = EXCLUDED.profitability_score,
            liability_franchise_score = EXCLUDED.liability_franchise_score,
            earnings_quality_score    = EXCLUDED.earnings_quality_score,
            growth_score              = EXCLUDED.growth_score,
            bank_quality_score        = EXCLUDED.bank_quality_score,
            has_npa_data              = EXCLUDED.has_npa_data,
            coverage_pct              = EXCLUDED.coverage_pct,
            engine_version            = EXCLUDED.engine_version,
            computed_at               = NOW()
        """,
        symbol, as_of_date,
        sc.asset_quality_score, sc.profitability_score,
        sc.liability_franchise_score, sc.earnings_quality_score,
        sc.growth_score, sc.bank_quality_score,
        sc.has_npa_data, sc.coverage_pct, ENGINE_VERSION,
    )


# ─── Entry point ──────────────────────────────────────────────────────────────

async def run(
    target_date: Optional[date] = None,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Score all banking stocks and return a summary."""
    target_date = target_date or date.today()
    pool = await get_pool()

    written_metrics = written_scores = 0
    results: list[dict] = []

    async with pool.acquire() as conn:
        rows = await _load_bank_rows(conn, target_date)

        for row in rows:
            sym = row["symbol"]
            if symbol and sym != symbol:
                continue

            try:
                raw_data = _parse_raw(row["raw_data"])
                promoter_pct = float(row["promoter_pct"]) if row["promoter_pct"] else None
                bank_type = classify_bank(sym, promoter_pct)

                m = _extract_metrics(
                    raw_data,
                    float(row["total_equity_cr"]) if row["total_equity_cr"] else None,
                )

                sc = compute_bank_quality_score(
                    bank_type=bank_type,
                    gnpa_pct=m["gnpa_pct"],
                    nnpa_pct=m["nnpa_pct"],
                    gnpa_series=m["gnpa_series"],
                    roe_pct=m["roe_pct"],
                    pat_margin_pct=m["pat_margin_pct"],
                    pat_yoy_growth_pct=m["pat_yoy_growth_pct"],
                    nii_retention_pct=m["nii_retention_pct"],
                    fee_income_mix_pct=m["fee_income_mix_pct"],
                    revenue_yoy_growth_pct=m["revenue_yoy_growth_pct"],
                    earnings_consistency=m["earnings_consistency"],
                )

                await _upsert_metrics(conn, sym, target_date, m, bank_type)
                written_metrics += 1

                await _upsert_scores(conn, sym, target_date, sc)
                written_scores += 1

                results.append({
                    "symbol": sym,
                    "bank_type": bank_type,
                    "bank_quality_score": sc.bank_quality_score,
                    "asset_quality_score": sc.asset_quality_score,
                    "profitability_score": sc.profitability_score,
                    "has_npa_data": sc.has_npa_data,
                    "coverage_pct": sc.coverage_pct,
                    "gnpa_pct": m["gnpa_pct"],
                    "nnpa_pct": m["nnpa_pct"],
                    "gnpa_trend": m["gnpa_trend"],
                    "roe_pct": m["roe_pct"],
                })

            except Exception as exc:
                logger.warning("bank_scoring[%s]: failed — %s", sym, exc, exc_info=True)

    logger.info(
        "bank_scoring: wrote %d metrics + %d scores for %s",
        written_metrics, written_scores, target_date,
    )

    # Sort by composite score desc for readable summary
    results.sort(key=lambda r: r["bank_quality_score"] or 0, reverse=True)

    return {
        "as_of_date": target_date.isoformat(),
        "banks_scored": written_scores,
        "results": results,
    }
