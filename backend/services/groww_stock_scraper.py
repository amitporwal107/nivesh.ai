"""Groww Nifty 100 Scraper — constituent list + per-stock primitives.

Groww server-renders all fundamentals into a `__NEXT_DATA__` JSON blob on
their stock detail pages — we extract that (no fragile HTML parsing). The
Nifty 100 constituent list comes from the same mechanism on the indices
page.

Primary endpoints (HTML scrape of Next.js pages):
  - Index:  https://groww.in/indices/nifty-218500
  - Stock:  https://groww.in/stocks/{slug}        (slug from index page)

Pipeline:
  1. `fetch_nifty_100_constituents()` — returns [{nse_symbol, slug, isin,
     name, industry}] for all 100.
  2. `fetch_stock_details(slug)` — returns a raw Groww payload with stats,
     fundamentals, shareholding, financialStatementV2.
  3. `map_to_primitives(raw)` — maps Groww fields to our `stock_primitives`
     row shape (ROE, D/E, eps_growth, promoter holding, revenue growth,
     margins, volatility, etc.).
  4. `persist_primitives(conn, sym, primitives)` + `score_and_persist` —
     writes to Postgres + calls the V3 scoring engine.
  5. `refresh_nifty_100()` — orchestrates the full pipeline.

Rate-limiting: 20 concurrent requests, 0.5s between batches. Groww is
relatively generous but we stay polite.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

from services import stock_scoring

logger = logging.getLogger(__name__)

GROWW_INDEX_URL = "https://groww.in/indices/nifty-218500"
GROWW_STOCK_URL = "https://groww.in/stocks/{slug}"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
HTTP_TIMEOUT_S = 15
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
CONCURRENCY = 10
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE_S = 1.0
REDIS_CACHE_TTL_S = 21600   # 6 hours


# ── Retry-aware HTTP ──────────────────────────────────────────────────
async def _fetch_html(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """GET with exponential backoff. Retries on 5xx / 429 / timeout /
    connection errors. Returns None after exhausting attempts."""
    last_err: Optional[str] = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            async with session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
                allow_redirects=True,
            ) as resp:
                if resp.status == 200:
                    return await resp.text()
                if resp.status in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {resp.status}"
                    # fall through to retry
                else:
                    logger.debug("%s → HTTP %s (not retryable)", url, resp.status)
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = str(e)[:120]
        if attempt < RETRY_ATTEMPTS - 1:
            await asyncio.sleep(RETRY_BACKOFF_BASE_S * (2 ** attempt))
    logger.info("Fetch gave up on %s after %s attempts: %s", url, RETRY_ATTEMPTS, last_err)
    return None


def _extract_next_data(html: Optional[str]) -> Optional[Dict[str, Any]]:
    if not html:
        return None
    m = NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


async def fetch_nifty_100_constituents(
    session: Optional[aiohttp.ClientSession] = None,
) -> List[Dict[str, Any]]:
    """Return [{nse_symbol, slug, isin, name, industry, bse_symbol}] for
    all Nifty 100 constituents."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    try:
        html = await _fetch_html(session, GROWW_INDEX_URL)
        nd = _extract_next_data(html)
        if not nd:
            logger.warning("Failed to extract Nifty 100 __NEXT_DATA__")
            return []
        try:
            children = (
                nd["props"]["pageProps"]["indexData"]["childAssets"]
            )
        except (KeyError, TypeError):
            logger.warning("Nifty 100 __NEXT_DATA__ shape changed")
            return []
        out: List[Dict[str, Any]] = []
        for c in children:
            hdr = c.get("header") or {}
            sym = hdr.get("nseScriptCode")
            if not sym:
                continue
            out.append({
                "nse_symbol": sym,
                "slug": hdr.get("searchId"),
                "isin": hdr.get("isin"),
                "name": hdr.get("displayName") or hdr.get("shortName"),
                "industry": hdr.get("industryName"),
                "bse_symbol": hdr.get("bseScriptCode"),
            })
        return out
    finally:
        if own_session:
            await session.close()


# ── Redis cache for scraped payloads ───────────────────────────────────
async def _cache_get(slug: str) -> Optional[Dict[str, Any]]:
    try:
        from services.redis_client import get_client
        r = await get_client()
        if r is None:
            return None
        raw = await r.get(f"groww:stock:{slug}")
        if raw:
            return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("cache_get failed: %s", e)
    return None


async def _cache_put(slug: str, payload: Dict[str, Any]) -> None:
    try:
        from services.redis_client import get_client
        r = await get_client()
        if r is None:
            return
        await r.setex(f"groww:stock:{slug}", REDIS_CACHE_TTL_S,
                      json.dumps(payload, default=str))
    except Exception as e:  # noqa: BLE001
        logger.debug("cache_put failed: %s", e)


# ── 2. Per-stock fundamentals scrape (with cache) ─────────────────────
async def fetch_stock_details(
    slug: str, session: aiohttp.ClientSession,
    *, use_cache: bool = True,
) -> Optional[Dict[str, Any]]:
    """Return the complete Groww pageProps payload (stockData + livePriceData),
    or None on failure. Cached in Redis 6h when `use_cache=True`."""
    if use_cache:
        cached = await _cache_get(slug)
        if cached:
            return cached
    html = await _fetch_html(session, GROWW_STOCK_URL.format(slug=slug))
    nd = _extract_next_data(html)
    if not nd:
        return None
    try:
        pp = nd["props"]["pageProps"]
        sd = pp["stockData"]
        # Attach live price for downstream mapping (momentum, return_1y)
        live = None
        nse_code = (sd.get("header") or {}).get("nseScriptCode")
        if nse_code:
            live = (pp.get("livePriceData") or {}).get(nse_code)
        sd["_live_price"] = live
        if use_cache:
            await _cache_put(slug, sd)
        return sd
    except (KeyError, TypeError):
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _cagr(start: Optional[float], end: Optional[float], years: int) -> Optional[float]:
    if not start or not end or years <= 0 or start <= 0:
        return None
    try:
        return ((end / start) ** (1.0 / years) - 1.0) * 100.0
    except (ValueError, ZeroDivisionError):
        return None


def _yearly_cagr(series: Dict[str, Any], years_back: int = 3) -> Optional[float]:
    """Compute CAGR from Groww's yearly dict {year_str: amount}."""
    if not series:
        return None
    try:
        items = sorted(
            ((int(y), _safe_float(v)) for y, v in series.items() if _safe_float(v)),
            key=lambda x: x[0],
        )
    except (ValueError, TypeError):
        return None
    if len(items) < 2:
        return None
    items = items[-(years_back + 1):]
    if len(items) < 2:
        return None
    return _cagr(items[0][1], items[-1][1], len(items) - 1)


def _yoy_delta_pct(series: Dict[str, Any]) -> Optional[float]:
    """Return the YoY % change between the two most-recent years."""
    try:
        items = sorted(
            ((int(y), _safe_float(v)) for y, v in series.items() if _safe_float(v)),
            key=lambda x: x[0],
        )
    except (ValueError, TypeError):
        return None
    if len(items) < 2:
        return None
    prev, cur = items[-2][1], items[-1][1]
    if not prev or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def _earnings_consistency(yearly_profit: Dict[str, Any]) -> Optional[float]:
    """Score 0-100 based on consistency of profit over 5 years.
    100 = all years positive with low variance, 0 = erratic or losses."""
    vals = []
    try:
        for v in yearly_profit.values():
            f = _safe_float(v)
            if f is not None:
                vals.append(f)
    except Exception:  # noqa: BLE001
        return None
    if len(vals) < 3:
        return None
    neg = sum(1 for v in vals if v < 0)
    score = 100.0 - (neg / len(vals)) * 70.0
    # Add coefficient-of-variation penalty
    try:
        mean = statistics.mean(vals)
        if mean > 0:
            stdev = statistics.pstdev(vals)
            cv = stdev / mean
            score -= min(30.0, cv * 60.0)
    except statistics.StatisticsError:
        pass
    return max(0.0, min(100.0, score))


def _total_promoter_holding(shp: Optional[Dict[str, Any]]) -> Optional[float]:
    """Sum all promoter buckets (individual + government + corporation)."""
    if not shp:
        return None
    try:
        latest_key = list(shp.keys())[-1]
        block = shp[latest_key]
    except (IndexError, KeyError, TypeError):
        return None
    promoters = (block or {}).get("promoters") or {}
    total = 0.0
    for sub in ("individual", "government", "corporation"):
        p = (promoters.get(sub) or {}).get("percent")
        if p is not None:
            total += float(p)
    return total if total > 0 else None


def _cap_bucket(cap_cr: Optional[float], capped_type: Optional[str]) -> str:
    """Prefer Groww's cappedType ('Large Cap' etc); fall back to mcap bands."""
    if capped_type:
        t = capped_type.lower()
        if "large" in t:
            return "large"
        if "mid" in t:
            return "mid"
        if "small" in t:
            return "small"
    if cap_cr is None:
        return "unknown"
    if cap_cr >= 67000:
        return "large"
    if cap_cr >= 20000:
        return "mid"
    return "small"


def _quarterly_yoy_surprise_pct(quarterly: Dict[str, Any]) -> Optional[float]:
    """Earnings surprise proxy: latest quarter profit vs same-quarter-last-year.
    Groww quarterly keys are like "Dec '25", "Mar '25" — we pair by month.
    Returns % change; None if insufficient history."""
    if not quarterly:
        return None
    items = [(k, _safe_float(v)) for k, v in quarterly.items() if _safe_float(v) is not None]
    if len(items) < 5:
        # Need at least 5 quarters to get a YoY pair
        return None
    # Match on month token (first 3 letters)
    latest_key, latest_val = items[-1]
    latest_month = (latest_key.split()[0] if latest_key else "")[:3].lower()
    # Find the same-month quarter 4 positions back
    if len(items) >= 5 and items[-5][0].split()[0][:3].lower() == latest_month:
        prior_val = items[-5][1]
        if prior_val and prior_val > 0:
            return (latest_val - prior_val) / prior_val * 100.0
    return None


def _qoq_volatility_pct(quarterly: Dict[str, Any]) -> Optional[float]:
    """Secondary volatility signal: coefficient of variation of quarterly
    profits (business stability, not price vol). Used when price proxy weak."""
    vals = [_safe_float(v) for v in (quarterly or {}).values() if _safe_float(v) is not None]
    if len(vals) < 4:
        return None
    try:
        mean = statistics.mean(vals)
        if mean <= 0:
            return None
        stdev = statistics.pstdev(vals)
        return (stdev / abs(mean)) * 100.0
    except statistics.StatisticsError:
        return None


def _price_momentum_score(ltp: Optional[float], hi: Optional[float],
                           lo: Optional[float]) -> Optional[float]:
    """Momentum = position in 52-week range (0-100). 100 = near 52w high,
    0 = near 52w low."""
    if not ltp or not hi or not lo or hi <= lo:
        return None
    pos = (ltp - lo) / (hi - lo)
    return max(0.0, min(100.0, pos * 100.0))


def map_to_primitives(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Groww's raw stockData to our `stock_primitives` row shape.
    Missing values stay None → scoring engine falls back to neutral 50."""
    stats = raw.get("stats") or {}
    shp = raw.get("shareHoldingPattern") or {}
    live = raw.get("_live_price") or {}
    # Use V1 financialStatement (has both yearly + quarterly + cagr)
    fs_v1 = raw.get("financialStatement") or []
    # Fallback to V2 if V1 missing
    if not fs_v1:
        fsv2 = (raw.get("financialStatementV2") or {}).get("CONSOLIDATED") \
               or (raw.get("financialStatementV2") or {}).get("STANDALONE") or []
        fs_v1 = fsv2

    # Index by title (lowercase)
    by_title: Dict[str, Dict[str, Any]] = {}
    for item in fs_v1:
        if isinstance(item, dict):
            by_title[(item.get("title") or "").lower()] = item

    revenue_item = by_title.get("revenue") or {}
    profit_item = by_title.get("profit") or {}
    revenue_series = revenue_item.get("yearly") or {}
    profit_series = profit_item.get("yearly") or {}
    profit_quarterly = profit_item.get("quarterly") or {}
    revenue_cagr_bundle = revenue_item.get("cagr") or {}
    profit_cagr_bundle = profit_item.get("cagr") or {}

    # Groww's own CAGR (if present — already calculated) takes priority
    def _cagr_or_compute(bundle: Dict[str, Any], series: Dict[str, Any],
                         key: str = "threeYearCagr", years: int = 3) -> Optional[float]:
        g = _safe_float(bundle.get(key))
        if g is not None:
            return g * 100.0   # Groww returns as decimal (0.11 = 11%)
        return _yearly_cagr(series, years_back=years)

    revenue_growth_3y = _cagr_or_compute(revenue_cagr_bundle, revenue_series)
    eps_growth_3y = _cagr_or_compute(profit_cagr_bundle, profit_series)
    profit_margin_trend = _yoy_delta_pct(profit_series)
    revenue_yoy = _yoy_delta_pct(revenue_series)

    # ── Earnings surprise (new): YoY quarterly profit delta ──
    earnings_surprise = _quarterly_yoy_surprise_pct(profit_quarterly)

    # ── Price signals (prefer live; fall back to 52w) ──
    price_data = (raw.get("priceData") or {}).get("nse") or {}
    hi = _safe_float(live.get("yearHighPrice")) or _safe_float(price_data.get("yearHighPrice"))
    lo = _safe_float(live.get("yearLowPrice")) or _safe_float(price_data.get("yearLowPrice"))
    ltp = _safe_float(live.get("ltp")) or _safe_float(live.get("close"))

    # Volatility: 52w range normalised to annualised-σ proxy.
    # (hi - lo) / mean → range %. ÷1.4 calibration vs historical NIFTY ~13% σ.
    vol_1y = None
    if hi and lo and lo > 0:
        rng = (hi - lo) / ((hi + lo) / 2) * 100.0
        vol_1y = rng / 1.4
    # Bump with quarterly business volatility if price proxy is suspiciously low
    qoq_vol = _qoq_volatility_pct(profit_quarterly)
    if vol_1y is not None and qoq_vol is not None:
        # Blend 70% price + 30% business for a more robust σ estimate
        vol_1y = 0.7 * vol_1y + 0.3 * min(qoq_vol, 60.0)

    # ── 1Y return: use Groww's precomputed oneYearTtm if available ──
    return_1y = None
    one_year_ttm = _safe_float(revenue_cagr_bundle.get("oneYearTtm"))
    if one_year_ttm is not None:
        return_1y = one_year_ttm * 100.0
    elif ltp and hi and lo:
        # Fallback: proxy via price position (rough)
        mid = (hi + lo) / 2
        return_1y = ((ltp - mid) / mid * 100.0) if mid > 0 else None

    # ── Max drawdown proxy: (ltp - yearHigh) / yearHigh ──
    max_dd_pct = None
    if ltp and hi and hi > 0:
        max_dd_pct = abs(min(0.0, (ltp - hi) / hi * 100.0))

    mcap_cr = _safe_float(stats.get("marketCap"))
    capped = stats.get("cappedType")
    pe = _safe_float(stats.get("peRatio"))
    sector_pe = _safe_float(stats.get("sectorPe"))
    pe_over = None
    if pe and sector_pe and sector_pe > 0:
        pe_over = (pe / sector_pe - 1.0) * 100.0

    return {
        # Fundamentals
        "pe_ratio": pe,
        "pb_ratio": _safe_float(stats.get("pbRatio")),
        "roe_pct": _safe_float(stats.get("roe")),
        "roce_pct": _safe_float(stats.get("roic")),
        "debt_to_equity": _safe_float(stats.get("debtToEquity")),
        "promoter_holding_pct": _total_promoter_holding(shp),
        "eps": _safe_float(stats.get("epsTtm")),
        "eps_growth_3y_cagr_pct": eps_growth_3y,
        "revenue_growth_3y_cagr_pct": revenue_growth_3y,
        "profit_margin_pct": _safe_float(stats.get("netProfitMargin")),
        "profit_margin_trend_pct": profit_margin_trend,
        # debt_trend needs multi-year balance sheet — Groww detail page doesn't
        # expose it (would need separate /financials scrape). Left None → neutral.
        "debt_trend_pct": None,
        "earnings_consistency_score": _earnings_consistency(profit_series),
        "earnings_surprise_pct": earnings_surprise,
        "dividend_yield_pct": _safe_float(stats.get("divYield")),

        # Valuation / exit signals
        "pe_historical_median": sector_pe,
        "pe_overvaluation_pct": pe_over,
        "earnings_decline_flag": (revenue_yoy is not None and revenue_yoy < -5),
        "debt_spike_flag": False,   # Need debt series — not available
        "liquidity_score": 85.0 if (mcap_cr and mcap_cr > 50000) else 60.0,

        # Price / risk
        "return_1y_pct": return_1y,
        "volatility_1y_pct": vol_1y,
        "beta": None,   # Not in Groww payload
        "max_drawdown_pct": max_dd_pct,

        # Momentum — now uses live ltp + 52w range
        "momentum_score": _price_momentum_score(ltp, hi, lo),

        # Meta (not in the primitives table, used by scoring)
        "cap_bucket": _cap_bucket(mcap_cr, capped),
        "market_cap_cr": mcap_cr,
        "sector_pe": sector_pe,
        "ltp": ltp,
    }


# ── 3. Persistence + scoring ───────────────────────────────────────────
async def upsert_stock_master(
    conn, constituent: Dict[str, Any], primitives: Dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO stock_master (
            nse_symbol, isin, company_name, sector, industry,
            market_cap_cr, cap_bucket, face_value, is_nifty_100,
            groww_slug, last_scraped_at, created_at, updated_at
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, TRUE, $9, NOW(), NOW(), NOW()
        )
        ON CONFLICT (nse_symbol) DO UPDATE SET
            isin = EXCLUDED.isin,
            company_name = EXCLUDED.company_name,
            industry = EXCLUDED.industry,
            market_cap_cr = EXCLUDED.market_cap_cr,
            cap_bucket = EXCLUDED.cap_bucket,
            is_nifty_100 = TRUE,
            groww_slug = EXCLUDED.groww_slug,
            last_scraped_at = NOW(),
            updated_at = NOW()
        """,
        constituent["nse_symbol"], constituent.get("isin"),
        constituent.get("name") or constituent["nse_symbol"],
        constituent.get("industry"), constituent.get("industry"),
        primitives.get("market_cap_cr"), primitives.get("cap_bucket"),
        None, constituent.get("slug"),
    )


async def upsert_primitives(
    conn, nse_symbol: str, primitives: Dict[str, Any],
) -> None:
    await conn.execute(
        """
        INSERT INTO stock_primitives (
            nse_symbol, as_of_date, pe_ratio, pb_ratio,
            roe_pct, roce_pct, debt_to_equity, promoter_holding_pct,
            eps, eps_growth_3y_cagr_pct, revenue_growth_3y_cagr_pct,
            profit_margin_pct, profit_margin_trend_pct, debt_trend_pct,
            earnings_consistency_score, earnings_surprise_pct, dividend_yield_pct,
            pe_historical_median, pe_overvaluation_pct,
            earnings_decline_flag, debt_spike_flag, liquidity_score,
            return_1y_pct, volatility_1y_pct, beta, max_drawdown_pct,
            momentum_score
        ) VALUES (
            $1, CURRENT_DATE, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
            $22, $23, $24, $25, $26
        )
        ON CONFLICT (nse_symbol, as_of_date) DO UPDATE SET
            pe_ratio = EXCLUDED.pe_ratio,
            pb_ratio = EXCLUDED.pb_ratio,
            roe_pct = EXCLUDED.roe_pct,
            roce_pct = EXCLUDED.roce_pct,
            debt_to_equity = EXCLUDED.debt_to_equity,
            promoter_holding_pct = EXCLUDED.promoter_holding_pct,
            eps = EXCLUDED.eps,
            eps_growth_3y_cagr_pct = EXCLUDED.eps_growth_3y_cagr_pct,
            revenue_growth_3y_cagr_pct = EXCLUDED.revenue_growth_3y_cagr_pct,
            profit_margin_pct = EXCLUDED.profit_margin_pct,
            profit_margin_trend_pct = EXCLUDED.profit_margin_trend_pct,
            earnings_consistency_score = EXCLUDED.earnings_consistency_score,
            dividend_yield_pct = EXCLUDED.dividend_yield_pct,
            pe_historical_median = EXCLUDED.pe_historical_median,
            pe_overvaluation_pct = EXCLUDED.pe_overvaluation_pct,
            earnings_decline_flag = EXCLUDED.earnings_decline_flag,
            liquidity_score = EXCLUDED.liquidity_score,
            volatility_1y_pct = EXCLUDED.volatility_1y_pct,
            momentum_score = EXCLUDED.momentum_score
        """,
        nse_symbol,
        primitives.get("pe_ratio"), primitives.get("pb_ratio"),
        primitives.get("roe_pct"), primitives.get("roce_pct"),
        primitives.get("debt_to_equity"), primitives.get("promoter_holding_pct"),
        primitives.get("eps"), primitives.get("eps_growth_3y_cagr_pct"),
        primitives.get("revenue_growth_3y_cagr_pct"),
        primitives.get("profit_margin_pct"), primitives.get("profit_margin_trend_pct"),
        primitives.get("debt_trend_pct"),
        primitives.get("earnings_consistency_score"),
        primitives.get("earnings_surprise_pct"),
        primitives.get("dividend_yield_pct"),
        primitives.get("pe_historical_median"), primitives.get("pe_overvaluation_pct"),
        primitives.get("earnings_decline_flag"), primitives.get("debt_spike_flag"),
        primitives.get("liquidity_score"),
        primitives.get("return_1y_pct"), primitives.get("volatility_1y_pct"),
        primitives.get("beta"), primitives.get("max_drawdown_pct"),
        primitives.get("momentum_score"),
    )


async def score_and_persist(
    conn, nse_symbol: str, primitives: Dict[str, Any],
) -> Dict[str, Any]:
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
            $1, CURRENT_DATE, $2, $3, $4, $5, $6::jsonb, $7::jsonb,
            $8::jsonb, $9::jsonb, $10, $11, $12, $13, NOW()
        )
        ON CONFLICT (nse_symbol) DO UPDATE SET
            as_of_date = CURRENT_DATE,
            quality_score = EXCLUDED.quality_score,
            health_score = EXCLUDED.health_score,
            exit_score = EXCLUDED.exit_score,
            add_score = EXCLUDED.add_score,
            quality_components = EXCLUDED.quality_components,
            health_components = EXCLUDED.health_components,
            exit_components = EXCLUDED.exit_components,
            add_components = EXCLUDED.add_components,
            recommendation = EXCLUDED.recommendation,
            recommendation_reason = EXCLUDED.recommendation_reason,
            low_confidence = EXCLUDED.low_confidence,
            engine_version = EXCLUDED.engine_version,
            computed_at = NOW()
        """,
        nse_symbol,
        bundle.get("quality_score"), bundle.get("health_score"),
        bundle.get("exit_score"), bundle.get("add_score"),
        json.dumps(bundle.get("quality_components") or {}),
        json.dumps(bundle.get("health_components") or {}),
        json.dumps(bundle.get("exit_components") or {}),
        json.dumps(bundle.get("add_components") or {}),
        rec.get("action") or "REVIEW",
        rec.get("reason"),
        bool(bundle.get("low_confidence", False)),
        bundle.get("engine_version"),
    )
    return bundle


# ── 4. Orchestrator ────────────────────────────────────────────────────
async def _log_stock_refresh(
    job_name: str, status: str, total: int, succeeded: int, failed: int,
    duration_ms: int, error_msg: Optional[str] = None,
) -> None:
    """Write an audit row to stock_refresh_job_log. Silent on failure."""
    from services import pg_client
    pool = await pg_client.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO stock_refresh_job_log
                    (job_name, status, stocks_total, stocks_succeeded,
                     stocks_failed, duration_ms, error_msg)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                job_name, status, total, succeeded, failed,
                duration_ms, error_msg,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("stock_refresh audit write failed: %s", e)


async def refresh_nifty_100(
    *, symbols_subset: Optional[List[str]] = None,
    job_name: str = "nifty100_refresh",
) -> Dict[str, Any]:
    """Full pipeline: scrape constituents → fundamentals → persist → score.
    If `symbols_subset` is provided, only those symbols are refreshed.
    `job_name` controls the audit-log row label (e.g. 'stock_refresh_manual'
    when triggered via the admin UI for a subset).

    Returns summary: {total, succeeded, failed, duration_s}.
    """
    from services import pg_client, pipeline_progress
    start = datetime.now(timezone.utc)
    t0 = start
    # Progress is tracked under the canonical 'nifty100_refresh' key so the
    # dashboard UI sees both scheduled and manual runs on the same tile.
    progress_key = "nifty100_refresh"
    await pipeline_progress.start(progress_key, total=None,
                                   phase="fetch_index",
                                   message="scraping Nifty 100 constituent list from Groww")

    pool = await pg_client.get_pool()
    if pool is None:
        await _log_stock_refresh(job_name, "failed", 0, 0, 0, 0, "Postgres unavailable")
        await pipeline_progress.finish(progress_key, "failed", error_msg="Postgres unavailable")
        return {"ok": False, "error": "Postgres unavailable", "duration_s": 0}

    try:
        async with aiohttp.ClientSession() as session:
            constituents = await fetch_nifty_100_constituents(session)
            if not constituents:
                dur_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
                await _log_stock_refresh(job_name, "failed", 0, 0, 0, dur_ms, "No constituents scraped")
                await pipeline_progress.finish(progress_key, "failed", error_msg="No constituents scraped")
                return {"ok": False, "error": "No constituents scraped", "duration_s": 0}

            if symbols_subset:
                subset = {s.upper() for s in symbols_subset}
                constituents = [c for c in constituents if c["nse_symbol"] in subset]

            # Now that we know the real total, push it into the progress record.
            await pipeline_progress.tick(
                progress_key, processed_delta=0, total=len(constituents),
                phase="scrape_stocks",
                message=f"scraping fundamentals for {len(constituents)} stock(s) (concurrency={CONCURRENCY})",
            )

            sem = asyncio.Semaphore(CONCURRENCY)
            succeeded: List[str] = []
            failed: List[Dict[str, str]] = []

            async def _worker(con: Dict[str, Any]):
                async with sem:
                    try:
                        raw = await fetch_stock_details(con["slug"], session)
                        if not raw:
                            failed.append({"symbol": con["nse_symbol"], "reason": "scrape_empty"})
                            await pipeline_progress.tick(progress_key, processed_delta=0, failed_delta=1)
                            return
                        prim = map_to_primitives(raw)
                        async with pool.acquire() as conn:
                            async with conn.transaction():
                                await upsert_stock_master(conn, con, prim)
                                await upsert_primitives(conn, con["nse_symbol"], prim)
                                await score_and_persist(conn, con["nse_symbol"], prim)
                        succeeded.append(con["nse_symbol"])
                        await pipeline_progress.tick(progress_key, processed_delta=1)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("%s refresh failed: %s", con['nse_symbol'], e)
                        failed.append({"symbol": con["nse_symbol"], "reason": str(e)[:200]})
                        await pipeline_progress.tick(progress_key, processed_delta=0, failed_delta=1)

            await asyncio.gather(*[_worker(c) for c in constituents])
    except Exception as e:  # noqa: BLE001
        dur_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        await _log_stock_refresh(job_name, "failed", 0, 0, 0, dur_ms, str(e)[:500])
        await pipeline_progress.finish(progress_key, "failed", error_msg=str(e))
        raise

    dur_s = (datetime.now(timezone.utc) - start).total_seconds()
    dur_ms = int(dur_s * 1000)
    total = len(constituents)
    n_ok = len(succeeded)
    n_fail = len(failed)
    status = "ok" if n_fail == 0 else ("partial" if n_ok > 0 else "failed")
    err_msg = None
    if failed:
        err_msg = "; ".join(f"{f['symbol']}:{f['reason']}" for f in failed[:5])[:500]
    await _log_stock_refresh(job_name, status, total, n_ok, n_fail, dur_ms, err_msg)
    await pipeline_progress.finish(
        progress_key, status, total=total, processed=n_ok, failed=n_fail, error_msg=err_msg,
    )

    return {
        "ok": True,
        "total": total,
        "succeeded": n_ok,
        "failed": n_fail,
        "failed_details": failed[:15],
        "duration_s": round(dur_s, 1),
        "started_at": start.isoformat(),
    }


async def search_groww_by_symbol(
    symbol: str, session: aiohttp.ClientSession,
) -> Optional[Dict[str, Any]]:
    """Resolve any NSE symbol → Groww slug + company metadata via Groww's
    autosuggest API. Used to score stocks that aren't in the Nifty 100 list
    (mid/small caps)."""
    url = (
        "https://groww.in/v1/api/search/v3/query/global/st_p_query"
        f"?query={symbol}&page=0&size=5"
    )
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT},
                                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("groww search for %s failed: %s", symbol, e)
        return None
    items = (data.get("data") or {}).get("content") or []
    sym_u = symbol.upper()
    # Prefer exact NSE scrip match
    for it in items:
        if (it.get("entity_type") == "Stocks"
            and (it.get("nse_scrip_code") or "").upper() == sym_u):
            return {
                "nse_symbol": sym_u,
                "slug": it.get("search_id") or it.get("id"),
                "isin": it.get("isin") or "",
                "name": it.get("title") or it.get("company_short_name") or sym_u,
                "industry": None,
            }
    return None


async def _backfill_nse_symbols(user_id: str) -> Dict[str, int]:
    """Resolve `nse_symbol` from ISIN for any equity holding that has a
    ticker like 'INE901L01018' but no NSE symbol. Uses NSE's master CSVs
    (cached in-process for 24h via live_price._load_isin_map). Without
    this step `refresh_user_stocks` finds zero symbols to score → score
    coverage stays at the MF-only ceiling.
    """
    from deps import db
    from services.live_price import _load_isin_map
    cursor = db.holdings.find(
        {
            "user_id": user_id,
            "asset_type": "equity",
            "$or": [{"nse_symbol": None}, {"nse_symbol": ""}, {"nse_symbol": {"$exists": False}}],
        },
        {"_id": 0, "holding_id": 1, "ticker": 1, "name": 1},
    )
    candidates: List[Dict[str, str]] = []
    async for h in cursor:
        tkr = (h.get("ticker") or "").strip().upper()
        if tkr.startswith(("INE", "INF", "IN0")) and len(tkr) == 12:
            candidates.append({"holding_id": h.get("holding_id"), "isin": tkr})
    if not candidates:
        return {"resolved": 0, "missing": 0}
    isin_map = await _load_isin_map()
    resolved = 0
    misses = 0
    for c in candidates:
        sym = isin_map.get(c["isin"])
        if not sym:
            misses += 1
            continue
        await db.holdings.update_one(
            {"user_id": user_id, "holding_id": c["holding_id"]},
            {"$set": {"nse_symbol": sym.upper(), "isin": c["isin"]}},
        )
        resolved += 1
    if resolved or misses:
        logger.info("nse_symbol backfill for %s: %d resolved, %d unmatched", user_id, resolved, misses)
    return {"resolved": resolved, "missing": misses}


async def refresh_user_stocks(user_id: str) -> Dict[str, Any]:
    """Refresh fundamentals for the user's currently-held equities only.
    Strategy:
      1. Backfill nse_symbol from ISIN (NSE master CSV) for any holding
         that's missing one — without this step we score zero stocks.
      2. Try Nifty 100 path (fast — one call to fetch_nifty_100_constituents).
      3. For symbols not in Nifty 100, fall back to `search_groww_by_symbol`
         to resolve slug, then scrape + persist inline.
    """
    from deps import db
    from services import pg_client
    backfill = await _backfill_nse_symbols(user_id)
    cursor = db.holdings.find(
        {"user_id": user_id, "asset_type": "equity"},
        {"_id": 0, "nse_symbol": 1},
    )
    symbols: List[str] = []
    async for h in cursor:
        s = h.get("nse_symbol")
        if s:
            symbols.append(s.upper())
    if not symbols:
        return {"ok": True, "total": 0, "note": "No equity holdings", "backfill": backfill}

    start = datetime.now(timezone.utc)
    # Phase 1: Nifty 100 path
    nifty_result = await refresh_nifty_100(symbols_subset=symbols)
    scored_syms = set(nifty_result.get("succeeded_symbols") or []) if isinstance(nifty_result, dict) else set()
    # refresh_nifty_100 doesn't return succeeded_symbols by default — re-derive.
    # We treat any symbol missing from stock_master after phase 1 as "needs search".
    pool = await pg_client.get_pool()
    already: set[str] = set()
    if pool is not None:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT nse_symbol FROM stock_master WHERE nse_symbol = ANY($1::text[])",
                symbols,
            )
        already = {r["nse_symbol"] for r in rows}
    missing = [s for s in symbols if s not in already]

    # Phase 2: search-resolve missing symbols + scrape
    extra_succeeded: List[str] = []
    extra_failed: List[Dict[str, str]] = []
    if missing and pool is not None:
        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(CONCURRENCY)

            async def _search_worker(sym: str):
                async with sem:
                    try:
                        con = await search_groww_by_symbol(sym, session)
                        if not con or not con.get("slug"):
                            extra_failed.append({"symbol": sym, "reason": "groww_search_miss"})
                            return
                        raw = await fetch_stock_details(con["slug"], session)
                        if not raw:
                            extra_failed.append({"symbol": sym, "reason": "scrape_empty"})
                            return
                        prim = map_to_primitives(raw)
                        async with pool.acquire() as conn:
                            async with conn.transaction():
                                await upsert_stock_master(conn, con, prim)
                                await upsert_primitives(conn, sym, prim)
                                await score_and_persist(conn, sym, prim)
                        extra_succeeded.append(sym)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("search-scrape %s failed: %s", sym, e)
                        extra_failed.append({"symbol": sym, "reason": str(e)[:200]})

            await asyncio.gather(*[_search_worker(s) for s in missing])

    dur = (datetime.now(timezone.utc) - start).total_seconds()
    return {
        "ok": True,
        "total": len(symbols),
        "already_scored": len(already),
        "search_resolved": len(extra_succeeded),
        "search_failed": len(extra_failed),
        "search_failed_details": extra_failed[:15],
        "duration_s": round(dur, 1),
    }
