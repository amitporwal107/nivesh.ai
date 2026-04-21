"""NAV-derived analytics (V3 Engine Phase 1a).

Pure compute on `mutual_fund_nav_history` + `mutual_fund_aum_history`. Feeds
the 4 primitives that Groww doesn't expose natively:

    max_drawdown             (from NAV series)
    consistency_score        (from rolling 1y returns vs category avg)
    downside_capture         (from fund NAV vs benchmark NAV in down months)
    aum_trend_score          (from AUM monthly snapshots — OLS slope)

All functions return `None` when insufficient data rather than zeros — the
scoring layer treats None as "missing primitive" and redistributes weight.
"""
from __future__ import annotations
import logging
import math
from datetime import date, timedelta
from typing import List, Optional, Tuple

from services import pg_client

logger = logging.getLogger(__name__)


# ── Data access ──────────────────────────────────────────────────────────
async def _fetch_nav_series(
    instrument_id: str, window_days: int = 365 * 3
) -> List[Tuple[date, float]]:
    """Return [(nav_date, nav), ...] sorted ascending. Empty list if none."""
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    cutoff = date.today() - timedelta(days=window_days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT nav_date, nav::float AS nav
            FROM mutual_fund_nav_history
            WHERE instrument_id = $1::uuid AND nav_date >= $2
            ORDER BY nav_date ASC
            """,
            instrument_id, cutoff,
        )
    return [(r["nav_date"], r["nav"]) for r in rows]


async def _fetch_aum_series(instrument_id: str) -> List[Tuple[date, float]]:
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT snapshot_date, aum_cr::float AS aum
            FROM mutual_fund_aum_history
            WHERE instrument_id = $1::uuid
            ORDER BY snapshot_date ASC
            """,
            instrument_id,
        )
    return [(r["snapshot_date"], r["aum"]) for r in rows]


# ── Drawdown ─────────────────────────────────────────────────────────────
def max_drawdown_from_series(navs: List[float]) -> Optional[float]:
    """Return max peak-to-trough drawdown as a positive percentage (0-100).

    Example: a fund that peaks at 200 and troughs at 140 before new highs
    has max_drawdown = 30.0.
    """
    if len(navs) < 30:  # need at least ~6 weeks of data
        return None
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return round(max_dd, 2)


async def compute_max_drawdown(
    instrument_id: str, window_days: int = 365 * 3
) -> Optional[float]:
    series = await _fetch_nav_series(instrument_id, window_days)
    return max_drawdown_from_series([nav for _, nav in series])


# ── Consistency ──────────────────────────────────────────────────────────
def _annualised_return(nav_start: float, nav_end: float, days: int) -> Optional[float]:
    if nav_start <= 0 or nav_end <= 0 or days <= 0:
        return None
    years = days / 365.25
    try:
        return ((nav_end / nav_start) ** (1 / years) - 1) * 100.0
    except (ValueError, ZeroDivisionError):
        return None


def consistency_score_from_series(
    series: List[Tuple[date, float]],
    category_avg_return_pct: Optional[float],
) -> Optional[float]:
    """Fraction of rolling 1y windows where fund return beats category avg.

    Returns a 0-10 score where 10 = beat category in every window.
    Needs >= 18 months of data and a category_avg_return_pct to compare against.
    """
    if len(series) < 400:  # need >18 months of daily NAVs
        return None
    if category_avg_return_pct is None:
        return None

    # Resample to monthly end-of-month NAV points
    monthly: List[Tuple[date, float]] = []
    last_month = None
    for d, nav in series:
        key = (d.year, d.month)
        if key != last_month:
            monthly.append((d, nav))
            last_month = key
    if len(monthly) < 13:
        return None

    wins = total = 0
    for i in range(12, len(monthly)):
        d_start, nav_start = monthly[i - 12]
        d_end, nav_end = monthly[i]
        days = (d_end - d_start).days
        ret = _annualised_return(nav_start, nav_end, days)
        if ret is None:
            continue
        total += 1
        if ret >= category_avg_return_pct:
            wins += 1
    if total == 0:
        return None
    return round((wins / total) * 10.0, 2)


async def compute_consistency_score(
    instrument_id: str,
    category_avg_return_pct: Optional[float],
    window_days: int = 365 * 3,
) -> Optional[float]:
    series = await _fetch_nav_series(instrument_id, window_days)
    return consistency_score_from_series(series, category_avg_return_pct)


# ── Downside Capture ─────────────────────────────────────────────────────
def _monthly_returns(series: List[Tuple[date, float]]) -> List[Tuple[date, float]]:
    """Resample daily NAVs → monthly end-of-month returns %."""
    monthly: List[Tuple[date, float]] = []
    last_month = None
    for d, nav in series:
        key = (d.year, d.month)
        if key != last_month:
            monthly.append((d, nav))
            last_month = key
    rets: List[Tuple[date, float]] = []
    for i in range(1, len(monthly)):
        prev, curr = monthly[i - 1][1], monthly[i][1]
        if prev > 0:
            rets.append((monthly[i][0], (curr - prev) / prev * 100.0))
    return rets


def downside_capture_from_series(
    fund_series: List[Tuple[date, float]],
    benchmark_series: List[Tuple[date, float]],
) -> Optional[float]:
    """Fund cumulative return during benchmark-down months / benchmark same.

    Classic formula: lower is better. 100% = matches benchmark's losses.
    < 100% = protects capital (we want this). > 100% = amplifies losses.
    """
    fr = _monthly_returns(fund_series)
    br = _monthly_returns(benchmark_series)
    if len(fr) < 12 or len(br) < 12:
        return None

    # Align by (year, month) — pick fund return on same month as benchmark
    bm_map = {(d.year, d.month): r for d, r in br}
    fund_down = bm_down = 0.0
    down_count = 0
    for d, fret in fr:
        bret = bm_map.get((d.year, d.month))
        if bret is None or bret >= 0:
            continue
        fund_down += fret
        bm_down += bret
        down_count += 1
    if down_count < 6:  # need at least 6 down months for a meaningful ratio
        return None
    if bm_down >= 0:  # can't happen given guard above, but be safe
        return None
    return round((fund_down / bm_down) * 100.0, 2)


async def compute_downside_capture(
    instrument_id: str, benchmark_instrument_id: Optional[str] = None,
    window_days: int = 365 * 3,
) -> Optional[float]:
    if not benchmark_instrument_id:
        return None
    fund = await _fetch_nav_series(instrument_id, window_days)
    bench = await _fetch_nav_series(benchmark_instrument_id, window_days)
    return downside_capture_from_series(fund, bench)


# ── AUM Trend Score ──────────────────────────────────────────────────────
def aum_trend_from_series(series: List[Tuple[date, float]]) -> Optional[float]:
    """OLS slope of ln(AUM) over months, normalised to a 0-10 score.

    - Strong growth (>30%/yr)          → 10
    - Moderate growth (10-30%/yr)      → 7-9
    - Flat (±5%/yr)                    → 5
    - Mild decline (-5 to -15%/yr)     → 3
    - Sharp decline (<-15%/yr)         → 0-2
    """
    if len(series) < 3:
        return None
    xs = [(d - series[0][0]).days / 30.44 for d, _ in series]  # months
    ys = [math.log(a) for _, a in series if a > 0]
    if len(ys) != len(series):
        return None
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den == 0:
        return None
    slope_per_month = num / den
    ann_growth_pct = (math.exp(slope_per_month * 12) - 1) * 100.0
    # Piecewise linear mapping → 0-10
    if ann_growth_pct >= 30:
        score = 10.0
    elif ann_growth_pct >= 10:
        score = 7.0 + (ann_growth_pct - 10) / 20 * 3.0
    elif ann_growth_pct >= -5:
        score = 5.0 + (ann_growth_pct + 5) / 15 * 2.0
    elif ann_growth_pct >= -15:
        score = 3.0 + (ann_growth_pct + 15) / 10 * 2.0
    else:
        score = max(0.0, 3.0 + (ann_growth_pct + 15) / 30 * 3.0)
    return round(max(0.0, min(10.0, score)), 2)


async def compute_aum_trend_score(instrument_id: str) -> Optional[float]:
    series = await _fetch_aum_series(instrument_id)
    return aum_trend_from_series(series)


# ── Bulk refresh ─────────────────────────────────────────────────────────
async def refresh_all_analytics(instrument_id: str) -> dict:
    """Compute all 4 NAV-derived primitives + write back to mutual_fund_metadata.

    Looks up category_avg_3y and benchmark_instrument_id on the fly. Returns
    the dict of computed values (with None for anything insufficient).
    """
    pool = await pg_client.get_pool()
    if pool is None:
        return {"max_drawdown": None, "consistency_score": None,
                "downside_capture": None, "aum_trend_score": None}

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT mfmd.category_avg_3y::float AS cat_avg_3y, mfmd.benchmark_index
            FROM mutual_fund_metadata mfmd
            WHERE mfmd.instrument_id = $1::uuid
            """,
            instrument_id,
        )
        cat_avg = row["cat_avg_3y"] if row else None

        # Pick benchmark MF by name match (best-effort; returns None if not in our DB)
        bench_iid: Optional[str] = None
        if row and row["benchmark_index"]:
            b = await conn.fetchrow(
                """
                SELECT instrument_id FROM instrument_master
                WHERE instrument_type = 'MUTUAL_FUND'
                  AND lower(instrument_name) LIKE lower('%' || $1 || '%')
                LIMIT 1
                """,
                row["benchmark_index"].split(" TRI")[0],
            )
            if b:
                bench_iid = str(b["instrument_id"])

    mdd = await compute_max_drawdown(instrument_id)
    cons = await compute_consistency_score(instrument_id, cat_avg)
    dc = await compute_downside_capture(instrument_id, bench_iid)
    aum_t = await compute_aum_trend_score(instrument_id)

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE mutual_fund_metadata SET
                max_drawdown_pct      = $2,
                consistency_score     = $3,
                downside_capture_pct  = $4,
                aum_trend_score       = $5,
                nav_analytics_at      = NOW()
            WHERE instrument_id = $1::uuid
            """,
            instrument_id, mdd, cons, dc, aum_t,
        )

    return {
        "max_drawdown": mdd,
        "consistency_score": cons,
        "downside_capture": dc,
        "aum_trend_score": aum_t,
    }
