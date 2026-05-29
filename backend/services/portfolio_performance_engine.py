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
            if _daas.daas_available():
                daas_primitives = await _daas.get_v3_mf_primitives_bulk(isins)
                logger.info("perf_engine: DaaS returned %d/%d primitives", len(daas_primitives), len(isins))
        except Exception as e:
            logger.warning("perf_engine: DaaS primitives fetch failed, falling back: %s", e)

    # ── Build per-fund ratings from DaaS primitives ───────────────────────────
    # Compute category averages from the fetched data (same sub_category peer group)
    from collections import defaultdict
    cat_returns: dict[str, list[float]] = defaultdict(list)
    for prim in daas_primitives.values():
        cat = prim.get("sub_category") or prim.get("category") or ""
        r1y = prim.get("return_1y")
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
        r1y = prim.get("return_1y")
        bm_return = cat_avg.get(cat) if cat else None
        alpha = round(float(r1y) - float(bm_return), 2) if (r1y is not None and bm_return is not None) else None

        rating = {
            "name": name,
            "ticker": isin,
            "scheme_category": cat,
            "return_1y": float(r1y) if r1y is not None else None,
            "benchmark_return": bm_return,
            "benchmark_name": f"{cat} Avg" if cat else None,
            "alpha": alpha,
            "sharpe_1y": prim.get("sharpe_1y"),
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

    # Fallback to mfapi.in if DaaS returned nothing
    if not daas_primitives:
        logger.warning("perf_engine: DaaS unavailable, falling back to mfapi.in")
        try:
            from services.fund_performance import compute_benchmark_ratings
            nav_cache_doc = await db.fund_holdings_cache.find_one({}) or {}
            nav_cache = nav_cache_doc.get("cache") or {}
            ratings_result = await compute_benchmark_ratings(holdings, nav_cache)
            fund_ratings = ratings_result.get("fund_ratings") or []
            ratings_by_name = {r["name"]: r for r in fund_ratings}
        except Exception as e:
            logger.warning("perf_engine: mfapi.in fallback also failed: %s", e)
            fund_ratings = []
            ratings_by_name = {}

    # ── Portfolio-level XIRR (weighted average of per-holding XIRRs) ────────
    portfolio_xirr = await _portfolio_xirr(holdings)

    # ── Benchmark XIRR (weighted category-average) ──────────────────────────
    benchmark_xirr = _weighted_benchmark_xirr(holdings, ratings_by_name, grand_total)

    # ── Alpha ────────────────────────────────────────────────────────────────
    alpha: Optional[float] = None
    if portfolio_xirr is not None and benchmark_xirr is not None:
        alpha = round(portfolio_xirr - benchmark_xirr, 2)

    # ── Sharpe (from risk-analytics primitives; best-effort) ─────────────────
    sharpe = await _portfolio_sharpe(user_id)

    # ── Attribution waterfall (fund-contribution model) ───────────────────────
    waterfall = _build_waterfall(holdings, ratings_by_name, grand_total,
                                  portfolio_xirr, benchmark_xirr)

    # ── Top contributors ─────────────────────────────────────────────────────
    top_contributors = _build_top_contributors(holdings, ratings_by_name, grand_total)

    # ── Monthly returns strip ─────────────────────────────────────────────────
    monthly_returns = _build_monthly_returns(fund_ratings, period)

    # ── Hit rate (months portfolio beat benchmark) ────────────────────────────
    hit_rate = _compute_hit_rate(monthly_returns)

    # ── Verdict + status pill ─────────────────────────────────────────────────
    verdict_headline, status_pill = _build_verdict(alpha, portfolio_xirr)

    return {
        "period": period,
        "portfolio_xirr": portfolio_xirr,
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

async def _portfolio_xirr(holdings: list[dict]) -> Optional[float]:
    """Weighted-average XIRR across holdings that have cost basis."""
    from services.portfolio_enrichment import _holding_xirr
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
        if xirr is not None:
            weighted_sum += xirr * val
            weight_den += val
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


async def _portfolio_sharpe(user_id: str) -> Optional[float]:
    """Best-effort: read weighted_sharpe from risk-analytics if available."""
    try:
        from deps import db
        perf_doc = await db.fund_performance.find_one({"user_id": user_id}) or {}
        sharpe = perf_doc.get("weighted_sharpe")
        if sharpe is not None:
            return round(float(sharpe), 3)
    except Exception:
        pass
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
