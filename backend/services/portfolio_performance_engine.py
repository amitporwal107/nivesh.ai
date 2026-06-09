"""Portfolio Performance Engine — v5 Performance Dashboard backend.

Computes the full performance payload for GET /api/dashboards/performance:

  • Period-aware portfolio XIRR and benchmark XIRR (category peer average)
  • Alpha = portfolio_xirr − benchmark_xirr
  • Sharpe ratio (annualised)
  • Hit rate — fraction of months where portfolio beat benchmark
  • Attribution waterfall — fund-contribution model:
      each fund's alpha contribution = weight_pct × (fund_return − benchmark_return)
  • Monthly returns strip — portfolio vs benchmark per month
  • Top contributors — ranked by |alpha_contribution|

Results are cached in portfolio_performance_cache (per user_id × period) so the
Performance page renders in <2.5 s on 100+ holding portfolios (REQ 14).
Cache is invalidated by POST /api/portfolio/resync and on new CAS upload.

Attribution model: fund-contribution (confirmed in decisions-log OQ-3).
Benchmark: category peer average from fund_performance.compute_benchmark_ratings()
(confirmed in decisions-log OQ-2).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Period → approximate days lookback
_PERIOD_DAYS: dict[str, int] = {
    "1M":  30,
    "3M":  91,
    "6M":  182,
    "1Y":  365,
    "3Y":  1095,
    "inception": 9999,
}

_VALID_PERIODS = set(_PERIOD_DAYS)


# ── Cache read/write ──────────────────────────────────────────────────────────

async def _read_cache(pool, user_id: str, period: str) -> Optional[dict]:
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM portfolio_performance_cache WHERE user_id=$1 AND period=$2",
                user_id, period,
            )
            if not row:
                return None
            return dict(row)
    except Exception as e:
        logger.warning("perf_engine: cache read failed: %s", e)
        return None


async def _write_cache(pool, user_id: str, period: str, payload: dict) -> None:
    import json
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO portfolio_performance_cache
                    (user_id, period, portfolio_xirr, benchmark_xirr, alpha,
                     sharpe, hit_rate, waterfall, monthly_returns, top_contributors,
                     verdict_headline, status_pill, computed_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (user_id, period) DO UPDATE SET
                    portfolio_xirr   = EXCLUDED.portfolio_xirr,
                    benchmark_xirr   = EXCLUDED.benchmark_xirr,
                    alpha            = EXCLUDED.alpha,
                    sharpe           = EXCLUDED.sharpe,
                    hit_rate         = EXCLUDED.hit_rate,
                    waterfall        = EXCLUDED.waterfall,
                    monthly_returns  = EXCLUDED.monthly_returns,
                    top_contributors = EXCLUDED.top_contributors,
                    verdict_headline = EXCLUDED.verdict_headline,
                    status_pill      = EXCLUDED.status_pill,
                    computed_at      = EXCLUDED.computed_at
                """,
                user_id,
                period,
                payload.get("portfolio_xirr"),
                payload.get("benchmark_xirr"),
                payload.get("alpha"),
                payload.get("sharpe"),
                payload.get("hit_rate"),
                json.dumps(payload.get("waterfall") or []),
                json.dumps(payload.get("monthly_returns") or []),
                json.dumps(payload.get("top_contributors") or []),
                payload.get("verdict_headline"),
                payload.get("status_pill"),
                datetime.now(timezone.utc),
            )
    except Exception as e:
        logger.warning("perf_engine: cache write failed: %s", e)


# ── Core computation ──────────────────────────────────────────────────────────

async def compute_performance(
    user_id: str,
    period: str = "1Y",
    *,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Compute (or serve from cache) the full performance payload for one user+period."""
    if period not in _VALID_PERIODS:
        period = "1Y"

    # Try cache first
    if use_cache:
        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool:
                cached = await _read_cache(pool, user_id, period)
                if cached and cached.get("computed_at"):
                    age_h = (datetime.now(timezone.utc) - cached["computed_at"]).total_seconds() / 3600
                    if age_h < 24:
                        return _cache_row_to_payload(cached, period)
        except Exception as e:
            logger.warning("perf_engine: cache lookup error: %s", e)

    # Compute fresh
    payload = await _compute_fresh(user_id, period)

    # Persist to cache (best-effort)
    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool:
            await _write_cache(pool, user_id, period, payload)
    except Exception as e:
        logger.warning("perf_engine: cache write error: %s", e)

    return payload


async def _compute_fresh(user_id: str, period: str) -> dict[str, Any]:
    """Full computation from Mongo holdings + NIDP DaaS performance data.

    Data source: NIDP DaaS /v1/mf/performance/v3-primitives/bulk (bulk ISIN fetch).
    Returns return_1y, return_3y, sharpe_1y, alpha_1y, sub_category per fund.
    Category benchmark = average return_1y across all funds in same sub_category.
    Falls back to the mfapi.in path if DaaS is unavailable.
    """
    from deps import db

    # Load holdings
    holdings = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1, "quantity": 1,
         "buy_price": 1, "current_price": 1, "buy_date": 1, "category": 1,
         "sector": 1, "amfi_matched": 1},
    ).to_list(2000)

    if not holdings:
        return _empty_payload(period)

    # Total portfolio value
    grand_total = sum(
        float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        for h in holdings
    )
    if grand_total <= 0:
        return _empty_payload(period)

    # ── Fetch performance primitives from NIDP DaaS ──────────────────────────
    mf_holdings = [h for h in holdings
                   if (h.get("asset_type") or "").lower() in ("mutual_fund", "etf")]
    isins = list({(h.get("ticker") or "").upper() for h in mf_holdings if h.get("ticker")})

    daas_primitives: dict[str, dict] = {}
    if isins:
        try:
            from services.copilot_tools import daas_client as _daas
            import feature_flags as _ff
            # Pass user_id (email) so allowlist-mode flags resolve correctly
            daas_flag = _ff.is_enabled("v3_data_source_daas", user_id)
            if _daas.is_configured() and daas_flag:
                daas_primitives = await _daas.get_v3_mf_primitives_bulk(isins)
                logger.info("perf_engine: DaaS returned %d/%d primitives", len(daas_primitives), len(isins))
        except Exception as e:
            logger.warning("perf_engine: DaaS primitives fetch failed, falling back: %s", e)

    # ── B-3: backfill amfi_matched for newly uploaded holdings ───────────────
    # The migration 021 back-fill only covers funds present at migration time.
    # Any fund whose NAV history exists (or whose ISIN DaaS just matched) needs
    # amfi_matched=TRUE set so the Holdings table and Composition Explorer show
    # the correct match status without waiting for the next scrape cycle.
    if daas_primitives:
        matched_isins = list(daas_primitives.keys())
        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE mutual_fund_metadata mfm
                           SET amfi_matched = TRUE
                          FROM instrument_master im
                         WHERE im.isin = ANY($1::text[])
                           AND im.instrument_id = mfm.instrument_id
                           AND mfm.amfi_matched = FALSE
                        """,
                        matched_isins,
                    )
        except Exception as e:
            logger.debug("perf_engine: amfi_matched backfill skipped: %s", e)

    # ── Build per-fund ratings from DaaS primitives ───────────────────────────
    # Compute category averages from the fetched data (same sub_category peer group)
    from collections import defaultdict
    cat_returns: dict[str, list[float]] = defaultdict(list)
    for prim in daas_primitives.values():
        cat = prim.get("sub_category") or prim.get("category") or ""
        # DaaS returns ret_1y; category_avg_1y is pre-computed by NIDP
        r1y = prim.get("ret_1y") or prim.get("return_1y")
        if cat and r1y is not None:
            try:
                cat_returns[cat].append(float(r1y))
            except (TypeError, ValueError):
                pass

    cat_avg: dict[str, float] = {
        cat: round(sum(vals) / len(vals), 2)
        for cat, vals in cat_returns.items() if vals
    }

    # Build ratings_by_name — same shape compute_benchmark_ratings produces
    ratings_by_name: dict[str, dict] = {}
    fund_ratings: list[dict] = []
    for h in mf_holdings:
        name = h.get("name") or ""
        isin = (h.get("ticker") or "").upper()
        prim = daas_primitives.get(isin) or {}

        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        invested = qty * bp if bp > 0 else 0.0
        current = qty * cp

        cat = prim.get("sub_category") or prim.get("category") or h.get("category") or ""
        # DaaS field is ret_1y (not return_1y); category_avg_1y is the peer benchmark
        r1y = prim.get("ret_1y") or prim.get("return_1y")
        # Prefer the DaaS-computed category average directly; fall back to client-computed
        bm_return = (
            prim.get("category_avg_1y")
            or cat_avg.get(cat)
            if cat else cat_avg.get(cat)
        )
        alpha = round(float(r1y) - float(bm_return), 2) if (r1y is not None and bm_return is not None) else None

        rating = {
            "name": name,
            "ticker": isin,
            "scheme_category": cat,
            "return_1y": float(r1y) if r1y is not None else None,
            "benchmark_return": bm_return,
            "benchmark_name": f"{cat} Avg" if cat else None,
            "alpha": alpha,
            "sharpe_1y": prim.get("sharpe") or prim.get("sharpe_1y"),
            "invested": round(invested, 2),
            "current_value": round(current, 2),
            "rating": (
                "overperforming" if (alpha or 0) > 2
                else "underperforming" if (alpha or 0) < -2
                else "meeting"
            ) if alpha is not None else "no_data",
        }
        fund_ratings.append(rating)
        ratings_by_name[name] = rating

    # Fallback to mfapi.in if DaaS returned nothing OR if it returned primitives
    # but none have useful return data (ret_1y / category_avg_1y all null).
    # This happens when the NIDP analytics pipeline hasn't run for these ISINs.
    has_useful_returns = any(
        r.get("return_1y") is not None or r.get("benchmark_return") is not None
        for r in fund_ratings
    )
    if not daas_primitives or not has_useful_returns:
        logger.warning("perf_engine: DaaS missing return data, falling back to AMFI/mfapi.in")
        try:
            from services.fund_performance import compute_benchmark_ratings
            from services.amfi_nav import fetch_nav_data
            nav_cache = await fetch_nav_data()
            ratings_result = await compute_benchmark_ratings(holdings, nav_cache)
            fund_ratings = ratings_result.get("fund_ratings") or []
            ratings_by_name = {r["name"]: r for r in fund_ratings}
            logger.info("perf_engine: AMFI fallback produced %d fund ratings", len(fund_ratings))
        except Exception as e:
            logger.warning("perf_engine: AMFI fallback also failed: %s", e)
            fund_ratings = []
            ratings_by_name = {}

    # ── Portfolio return — period-matched for bounded periods, XIRR for inception ──
    # For bounded periods (1M/3M/6M/1Y) compute:
    #   period_return = (current_value - value_N_months_ago) / value_N_months_ago × 100
    # using the cas_monthly_values stored in user_profiles.
    # For "inception" (or when CAS history is too short) use weighted XIRR.
    portfolio_xirr: Optional[float] = None
    period_return: Optional[float] = None   # bounded-period portfolio return %

    _N_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}

    if period in _N_MONTHS:
        period_return = await _period_portfolio_return(user_id, period, grand_total)

    if period_return is not None:
        # Use period return as the primary KPI for bounded periods
        portfolio_xirr = period_return
    else:
        # inception or no CAS data → money-weighted XIRR (ledger-based)
        portfolio_xirr = await _portfolio_xirr(user_id, holdings, grand_total)

    # ── Benchmark return — match same window as portfolio return ─────────────
    # Bounded periods: use weighted average of fund period returns vs category avg.
    # For 6M we use the same weights as 1Y (6M DaaS field not always populated).
    # inception: use weighted category peer average.
    _PERIOD_FIELD_MAP = {"1M": "return_1m", "3M": "return_3m", "6M": "return_3m", "1Y": "return_1y"}
    bm_period_field = _PERIOD_FIELD_MAP.get(period, "return_1y")

    # Rebuild benchmark using period-appropriate fund return fields from fund_ratings
    if period in _N_MONTHS:
        benchmark_xirr = _weighted_benchmark_period(
            holdings, fund_ratings, bm_period_field, grand_total, daas_primitives
        )
    elif has_useful_returns:
        benchmark_xirr = _weighted_benchmark_xirr(holdings, ratings_by_name, grand_total)
    else:
        benchmark_xirr = await _index_benchmark_return()

    # ── Alpha ────────────────────────────────────────────────────────────────
    alpha: Optional[float] = None
    if portfolio_xirr is not None and benchmark_xirr is not None:
        alpha = round(portfolio_xirr - benchmark_xirr, 2)

    # ── Sharpe (weighted average from DaaS primitives fetched above) ────────
    sharpe = _weighted_sharpe(mf_holdings, daas_primitives, grand_total)

    # ── Attribution waterfall (fund-contribution model) ───────────────────────
    waterfall = _build_waterfall(holdings, ratings_by_name, grand_total,
                                  portfolio_xirr, benchmark_xirr)

    # ── Top contributors ─────────────────────────────────────────────────────
    top_contributors = _build_top_contributors(holdings, ratings_by_name, grand_total)

    # ── Monthly returns strip (from CAS monthly values where available) ──────
    monthly_returns = await _build_monthly_returns_from_cas(user_id, period, fund_ratings)

    # ── Hit rate (months portfolio beat benchmark) ────────────────────────────
    hit_rate = _compute_hit_rate(monthly_returns)

    # ── Verdict + status pill ─────────────────────────────────────────────────
    verdict_headline, status_pill = _build_verdict(alpha, portfolio_xirr)

    return {
        "period": period,
        "portfolio_xirr": portfolio_xirr,
        "period_matched": period_return is not None,  # True = bounded period return; False = XIRR
        "benchmark_xirr": benchmark_xirr,
        "alpha": alpha,
        "sharpe": sharpe,
        "hit_rate": hit_rate,
        "waterfall": waterfall,
        "monthly_returns": monthly_returns,
        "top_contributors": top_contributors,
        "verdict_headline": verdict_headline,
        "status_pill": status_pill,
        "coverage": {
            "matched_funds": len([r for r in fund_ratings if r.get("return_1y") is not None]),
            "total_funds": len([h for h in holdings if (h.get("asset_type") or "").lower() in ("mutual_fund", "etf")]),
        },
    }


# ── Sub-computations ──────────────────────────────────────────────────────────

async def _portfolio_xirr(
    user_id: str, holdings: list[dict], current_value: float
) -> Optional[float]:
    """Money-weighted portfolio XIRR.

    Primary: a single IRR solved over the dated `cas_transactions` ledger
    (purchases negative, redemptions positive, today's value as the final
    flow) — the textbook money-weighted return. Fallback when the ledger is
    too thin/absent: a value-weighted average of per-holding XIRR, with each
    holding CLAMPED to a sane band so a short-horizon annualisation artifact
    can't blow the portfolio figure up (the old +1211% bug).
    """
    from services.portfolio_enrichment import portfolio_xirr_from_ledger, _holding_xirr

    cost_basis = sum(
        float(h.get("quantity") or 0) * float(h.get("buy_price") or 0) for h in holdings
    )
    ledger = await portfolio_xirr_from_ledger(
        user_id, current_value, cost_basis=cost_basis or None
    )
    if ledger.get("reliable") and ledger.get("xirr_pct") is not None:
        return ledger["xirr_pct"]

    weighted_sum = 0.0
    weight_den = 0.0
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        if qty <= 0 or bp <= 0 or cp <= 0:
            continue
        val = qty * cp
        xirr = _holding_xirr(h.get("buy_date"), bp, cp, qty)
        if xirr is not None and -60.0 <= xirr <= 120.0:
            weighted_sum += xirr * val
            weight_den += val
    if weight_den <= 0:
        return None
    return round(weighted_sum / weight_den, 2)


async def _period_portfolio_return(
    user_id: str, period: str, current_value: float
) -> Optional[float]:
    """Compute period-matched portfolio return from stored CAS monthly values.

    Returns (current_value - value_N_months_ago) / value_N_months_ago * 100, or
    None if there is insufficient CAS history for the requested period.
    """
    from deps import db as _db
    from dateutil.parser import parse as _dp
    from dateutil.relativedelta import relativedelta
    from datetime import date

    _N_MONTHS = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}
    n = _N_MONTHS.get(period)
    if n is None:
        return None

    try:
        profile = await _db.user_profiles.find_one(
            {"user_id": user_id}, {"_id": 0, "cas_monthly_values": 1}
        ) or {}
        cas_monthly = profile.get("cas_monthly_values") or []
        if len(cas_monthly) < 2:
            return None

        # Parse and sort entries oldest-first
        parsed = []
        for entry in cas_monthly:
            try:
                dt = _dp("1 " + entry["month"]).date()
                v = float(entry.get("value_rs") or 0)
                if v > 0:
                    parsed.append((dt, v))
            except Exception:
                continue
        parsed.sort(key=lambda x: x[0])
        if not parsed:
            return None

        # Target date = today minus N months
        target_date = date.today() - relativedelta(months=n)

        # Find the CAS entry closest to target_date (prefer the one just before)
        before = [(dt, v) for dt, v in parsed if dt <= target_date]
        if not before:
            return None  # No data old enough for this period
        _, value_n_months_ago = before[-1]

        if value_n_months_ago <= 0:
            return None

        period_ret = (current_value - value_n_months_ago) / value_n_months_ago * 100
        return round(period_ret, 2)
    except Exception as exc:
        logger.warning("_period_portfolio_return failed: %s", exc)
        return None


def _weighted_benchmark_period(
    holdings: list[dict],
    fund_ratings: list[dict],
    period_field: str,
    grand_total: float,
    daas_primitives: dict,
) -> Optional[float]:
    """Portfolio-level benchmark for a bounded period using fund period returns.

    Uses DaaS per-fund period return vs its category average for the same window.
    Falls back to weighted 1Y benchmark if period field is absent.
    """
    weighted_sum = 0.0
    weight_den = 0.0
    rating_by_isin = {(r.get("ticker") or "").upper(): r for r in fund_ratings}

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        if val <= 0:
            continue
        isin = (h.get("ticker") or "").upper()
        prim = daas_primitives.get(isin) or {}
        rating = rating_by_isin.get(isin) or {}

        # For the benchmark, use category_avg for the same period window.
        # DaaS currently only guarantees category_avg_1y; for shorter periods
        # we use category_avg_1y as a proxy (conservative assumption).
        bm = (
            prim.get(f"category_avg_{period_field.replace('return_', '')}")
            or prim.get("category_avg_1y")
            or rating.get("benchmark_return")
        )
        if bm is not None:
            try:
                weighted_sum += float(bm) * val
                weight_den += val
            except (TypeError, ValueError):
                pass

    if weight_den <= 0:
        return None
    return round(weighted_sum / weight_den, 2)


def _weighted_benchmark_xirr(
    holdings: list[dict],
    ratings_by_name: dict[str, dict],
    grand_total: float,
) -> Optional[float]:
    """Portfolio-level benchmark = Σ (weight × fund_benchmark_return)."""
    weighted_sum = 0.0
    weight_den = 0.0
    for h in holdings:
        name = h.get("name") or ""
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        if val <= 0:
            continue
        rating = ratings_by_name.get(name)
        if not rating:
            continue
        bm = rating.get("benchmark_return")
        if bm is not None:
            w = val / grand_total if grand_total > 0 else 0
            weighted_sum += float(bm) * w
            weight_den += w
    if weight_den <= 0:
        return None
    return round(weighted_sum / weight_den, 2)


def _weighted_sharpe(
    mf_holdings: list[dict],
    daas_primitives: dict[str, dict],
    grand_total: float,
) -> Optional[float]:
    """Value-weighted portfolio Sharpe from per-fund DaaS primitives."""
    num = den = 0.0
    for h in mf_holdings:
        isin = (h.get("ticker") or "").upper()
        prim = daas_primitives.get(isin) or {}
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        if val <= 0:
            continue
        sharpe_val = prim.get("sharpe") or prim.get("sharpe_1y")
        if isinstance(sharpe_val, (int, float)):
            num += float(sharpe_val) * val
            den += val
    return round(num / den, 3) if den > 0 else None


async def _index_benchmark_return() -> Optional[float]:
    """Return Nifty 500 1Y return (%) as a broad market benchmark.

    Used when DaaS category_avg_1y is unavailable (mfapi.in fallback path).
    Nifty 500 is the widest-coverage Indian equity index and a fair reference
    for diversified MF portfolios. Returns None if the index snapshot is missing.
    """
    try:
        from services.benchmark_index import get_latest_index
        snap = await get_latest_index("nifty_500")
        if not snap:
            snap = await get_latest_index("nifty_50")
        if snap:
            r1y = (snap.get("metrics") or {}).get("return_1y")
            if r1y is not None:
                # return_1y is stored as decimal (0.08 = 8%); convert to %
                val = float(r1y)
                # Guard: if already in percent form (abs > 1), use as-is
                if abs(val) <= 1.5:
                    val = round(val * 100, 2)
                else:
                    val = round(val, 2)
                logger.info("perf_engine: using Nifty 500 benchmark = %s%%", val)
                return val
    except Exception as e:
        logger.debug("perf_engine: index benchmark lookup failed: %s", e)
    return None


def _build_waterfall(
    holdings: list[dict],
    ratings_by_name: dict[str, dict],
    grand_total: float,
    portfolio_xirr: Optional[float],
    benchmark_xirr: Optional[float],
) -> list[dict]:
    """Fund-contribution attribution waterfall.

    Steps:
      base  = benchmark_xirr (what you'd earn matching the benchmark)
      per fund step = weight × (fund_return − benchmark_return)
      final = portfolio_xirr
    """
    if portfolio_xirr is None or benchmark_xirr is None:
        return []

    steps = []
    for h in holdings:
        name = h.get("name") or ""
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        if val <= 0 or grand_total <= 0:
            continue
        rating = ratings_by_name.get(name)
        if not rating:
            continue
        fund_return = rating.get("return_1y")
        bm_return = rating.get("benchmark_return")
        if fund_return is None or bm_return is None:
            continue
        weight = val / grand_total
        contribution = round(weight * (float(fund_return) - float(bm_return)), 3)
        if abs(contribution) < 0.01:
            continue
        steps.append({
            "label": name[:40],
            "value": contribution,
            "type": "pos" if contribution >= 0 else "neg",
        })

    # Sort by absolute contribution descending, keep top 8 to avoid visual clutter
    steps.sort(key=lambda s: abs(s["value"]), reverse=True)
    steps = steps[:8]

    # Verify reconciliation: base + sum(steps) should ≈ final
    step_sum = sum(s["value"] for s in steps)
    residual = round(portfolio_xirr - benchmark_xirr - step_sum, 3)

    waterfall = [{"label": "Benchmark", "value": round(benchmark_xirr, 2), "type": "start"}]
    waterfall.extend(steps)
    if abs(residual) >= 0.01:
        waterfall.append({"label": "Other funds", "value": residual,
                           "type": "pos" if residual >= 0 else "neg"})
    waterfall.append({"label": "You", "value": round(portfolio_xirr, 2), "type": "end"})

    return waterfall


def _build_top_contributors(
    holdings: list[dict],
    ratings_by_name: dict[str, dict],
    grand_total: float,
) -> list[dict]:
    """Ranked contributors by alpha contribution pp."""
    contributors = []
    for h in holdings:
        name = h.get("name") or ""
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        val = qty * cp
        if val <= 0 or grand_total <= 0:
            continue
        rating = ratings_by_name.get(name)
        if not rating:
            continue
        fund_return = rating.get("return_1y")
        bm_return = rating.get("benchmark_return")
        if fund_return is None or bm_return is None:
            continue
        weight = val / grand_total
        alpha_contribution = round(weight * (float(fund_return) - float(bm_return)), 3)
        contributors.append({
            "name": name[:50],
            "return_pct": round(float(fund_return), 2),
            "alpha_contribution": alpha_contribution,
        })

    contributors.sort(key=lambda c: abs(c["alpha_contribution"]), reverse=True)
    return contributors[:10]


def _build_monthly_returns(fund_ratings: list[dict], period: str) -> list[dict]:
    """Best-effort monthly returns strip from fund-level data.

    Uses simple_return_pct averaged across matched funds as a proxy for the
    portfolio monthly return when granular monthly NAV is not available.
    Returns up to N months based on the period selector.
    """
    n_months = {
        "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "inception": 12,
    }.get(period, 12)

    now = datetime.now(timezone.utc)
    rows = []
    # Generate months by stepping back calendar months (not 30-day multiples)
    # to avoid the duplicate-month bug when 30*i crosses a month boundary.
    from datetime import date
    import calendar
    year, month = now.year, now.month
    months_back: list[tuple[int, int]] = []
    y, m = year, month
    for _ in range(n_months):
        months_back.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months_back.reverse()
    for y_, m_ in months_back:
        label = date(y_, m_, 1).strftime("%b %y")
        rows.append({"month": label, "portfolio": None, "benchmark": None})

    if not fund_ratings:
        return rows

    # Use the aggregate 1Y return spread across all rated funds as a rough
    # portfolio proxy. Proper monthly data requires per-fund NAV history
    # which is built in the NAV analytics sweep — expose that when available.
    matched = [r for r in fund_ratings if r.get("return_1y") is not None
               and r.get("benchmark_return") is not None]
    if not matched:
        return rows

    # Until per-month NAV is exposed, distribute the annual return evenly
    # so the strip shows a flat line — honest (no fabricated swings)
    avg_fund_return = sum(float(r["return_1y"]) for r in matched) / len(matched)
    avg_bm_return = sum(float(r["benchmark_return"]) for r in matched) / len(matched)
    monthly_fund = round(avg_fund_return / 12, 2)
    monthly_bm = round(avg_bm_return / 12, 2)

    for row in rows:
        row["portfolio"] = monthly_fund
        row["benchmark"] = monthly_bm

    return rows


async def _build_monthly_returns_from_cas(
    user_id: str, period: str, fund_ratings: list[dict]
) -> list[dict]:
    """Build monthly returns strip from CAS statement monthly values.

    CAS Vision API extracts month→portfolio_value pairs from the statement.
    Month-over-month return = (curr - prev) / prev * 100.
    Falls back to the flat-line method if fewer than 2 CAS data points exist.
    """
    try:
        from deps import db as _db
        from dateutil.parser import parse as _dp
        profile = await _db.user_profiles.find_one(
            {"user_id": user_id}, {"_id": 0, "cas_monthly_values": 1}
        ) or {}
        cas_monthly = profile.get("cas_monthly_values") or []

        if len(cas_monthly) >= 2:
            def _sort_key(item: dict):
                try:
                    return _dp("1 " + item["month"])
                except Exception:
                    return _dp("1 Jan 2000")

            cas_monthly = sorted(cas_monthly, key=_sort_key)

            # Determine how many months to return for the period
            n_months = {
                "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36,
            }.get(period, len(cas_monthly))

            # Compute category-avg benchmark return per month (flat proxy — same
            # month-over-month spread for every month, using annual rate / 12)
            bm_monthly: Optional[float] = None
            matched = [r for r in fund_ratings
                       if r.get("return_1y") is not None and r.get("benchmark_return") is not None]
            if matched:
                avg_bm = sum(float(r["benchmark_return"]) for r in matched) / len(matched)
                bm_monthly = round(avg_bm / 12, 2)

            rows = []
            for i in range(1, len(cas_monthly)):
                prev_val = float(cas_monthly[i - 1].get("value_rs") or 0)
                curr_val = float(cas_monthly[i].get("value_rs") or 0)
                if prev_val > 0:
                    pct = round((curr_val - prev_val) / prev_val * 100, 2)
                else:
                    pct = None
                rows.append({
                    "month": cas_monthly[i]["month"],
                    "portfolio": pct,
                    "benchmark": bm_monthly,
                })

            # Return the last n_months rows
            return rows[-n_months:] if len(rows) > n_months else rows
    except Exception as exc:
        logger.warning("monthly_returns_from_cas failed, falling back: %s", exc)

    return _build_monthly_returns(fund_ratings, period)


def _compute_hit_rate(monthly_returns: list[dict]) -> Optional[float]:
    """Fraction of months where portfolio return >= benchmark return."""
    valid = [m for m in monthly_returns
             if m.get("portfolio") is not None and m.get("benchmark") is not None]
    if not valid:
        return None
    beats = sum(1 for m in valid if m["portfolio"] >= m["benchmark"])
    return round(beats / len(valid), 3)


def _build_verdict(
    alpha: Optional[float],
    portfolio_xirr: Optional[float],
) -> tuple[str, str]:
    """Verdict headline and status pill from alpha."""
    if alpha is None or portfolio_xirr is None:
        return "Performance data loading — upload a statement to see your returns.", "CALCULATING"

    abs_alpha = round(abs(alpha), 1)
    if alpha >= 0:
        headline = f"You beat the benchmark by {abs_alpha} points."
        pill = "HEALTHY"
    else:
        headline = f"You trailed the benchmark by {abs_alpha} points."
        pill = "FAIR" if abs_alpha < 5 else "POOR"

    return headline, pill


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_payload(period: str) -> dict[str, Any]:
    return {
        "period": period,
        "portfolio_xirr": None, "benchmark_xirr": None,
        "alpha": None, "sharpe": None, "hit_rate": None,
        "waterfall": [], "monthly_returns": [], "top_contributors": [],
        "verdict_headline": "No holdings yet — upload a CAS statement to see your performance.",
        "status_pill": "EMPTY",
        "coverage": {"matched_funds": 0, "total_funds": 0},
    }


def _cache_row_to_payload(row: dict, period: str) -> dict[str, Any]:
    """Convert a DB row back to the payload dict."""
    import json

    def _parse(val):
        if val is None:
            return []
        if isinstance(val, str):
            try:
                return json.loads(val)
            except Exception:
                return []
        return val  # asyncpg may already deserialise JSONB

    return {
        "period": period,
        "portfolio_xirr": row.get("portfolio_xirr"),
        "benchmark_xirr": row.get("benchmark_xirr"),
        "alpha": row.get("alpha"),
        "sharpe": row.get("sharpe"),
        "hit_rate": row.get("hit_rate"),
        "waterfall": _parse(row.get("waterfall")),
        "monthly_returns": _parse(row.get("monthly_returns")),
        "top_contributors": _parse(row.get("top_contributors")),
        "verdict_headline": row.get("verdict_headline"),
        "status_pill": row.get("status_pill"),
        "coverage": None,
        "_from_cache": True,
        "computed_at": row.get("computed_at").isoformat() if row.get("computed_at") else None,
    }
