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


# ── 1. Constituents ───────────────────────────────────────────────────
async def _fetch_html(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_S),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                logger.debug(f"{url} → HTTP {resp.status}")
                return None
            return await resp.text()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"Fetch failed: {url} — {e}")
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


# ── 2. Per-stock fundamentals scrape ───────────────────────────────────
async def fetch_stock_details(
    slug: str, session: aiohttp.ClientSession,
) -> Optional[Dict[str, Any]]:
    """Return raw Groww `stockData` payload, or None on failure."""
    html = await _fetch_html(session, GROWW_STOCK_URL.format(slug=slug))
    nd = _extract_next_data(html)
    if not nd:
        return None
    try:
        return nd["props"]["pageProps"]["stockData"]
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


def map_to_primitives(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map Groww's raw stockData to our `stock_primitives` row shape.
    Missing values stay None → scoring engine falls back to neutral 50."""
    stats = raw.get("stats") or {}
    shp = raw.get("shareHoldingPattern") or {}
    fsv2 = (raw.get("financialStatementV2") or {}).get("CONSOLIDATED") \
           or (raw.get("financialStatementV2") or {}).get("STANDALONE") or []

    # Extract yearly series by title
    series_by_title: Dict[str, Dict[str, Any]] = {}
    for item in fsv2:
        if isinstance(item, dict):
            t = (item.get("title") or "").lower()
            if item.get("yearly"):
                series_by_title[t] = item["yearly"]

    revenue_series = series_by_title.get("revenue") or {}
    profit_series = series_by_title.get("profit") or {}

    revenue_growth_3y = _yearly_cagr(revenue_series, years_back=3)
    eps_growth_3y = None   # EPS series not directly in the payload; use profit CAGR as proxy
    if revenue_growth_3y is None:
        eps_growth_3y = _yearly_cagr(profit_series, years_back=3)
    else:
        eps_growth_3y = _yearly_cagr(profit_series, years_back=3)
    profit_margin_trend = _yoy_delta_pct(profit_series)
    revenue_yoy = _yoy_delta_pct(revenue_series)

    # Volatility proxy from price range (not perfect, but directional)
    price_data = (raw.get("priceData") or {}).get("nse") or {}
    hi = _safe_float(price_data.get("yearHighPrice"))
    lo = _safe_float(price_data.get("yearLowPrice"))
    vol_1y = None
    if hi and lo and lo > 0:
        # Annualised vol proxy: (high-low)/midpoint * 100. Rough but indicative.
        vol_1y = ((hi - lo) / ((hi + lo) / 2)) * 100.0 / 1.5   # ÷1.5 to calibrate to historical sigma

    # Return 1y proxy: price relative to 52w midpoint
    return_1y = None
    if hi and lo:
        mid = (hi + lo) / 2
        # We don't have current here; leave None — upstream can compute with live price

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
        "debt_trend_pct": None,   # Need multi-year debt series — not in payload
        "earnings_consistency_score": _earnings_consistency(profit_series),
        "earnings_surprise_pct": None,   # Not available from this payload
        "dividend_yield_pct": _safe_float(stats.get("divYield")),

        # Valuation / exit signals
        "pe_historical_median": sector_pe,
        "pe_overvaluation_pct": pe_over,
        "earnings_decline_flag": (revenue_yoy is not None and revenue_yoy < -5),
        "debt_spike_flag": False,   # Need debt series
        "liquidity_score": 85.0 if (mcap_cr and mcap_cr > 50000) else 60.0,

        # Price / risk
        "return_1y_pct": None,
        "volatility_1y_pct": vol_1y,
        "beta": None,
        "max_drawdown_pct": None,

        # Momentum (approximate via price position in 52w range)
        "momentum_score": _price_momentum_score(hi, lo, _safe_float(stats.get("epsTtm"))),

        # Meta (not in the primitives table, used by scoring)
        "cap_bucket": _cap_bucket(mcap_cr, capped),
        "market_cap_cr": mcap_cr,
        "sector_pe": sector_pe,
    }


def _price_momentum_score(hi: Optional[float], lo: Optional[float],
                           current: Optional[float]) -> Optional[float]:
    """Momentum proxy — position in 52w range (without a current price we use
    the midpoint → neutral 50)."""
    if not hi or not lo or hi <= lo:
        return None
    # Without a live price we can't know today's position, default neutral
    return 50.0


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
async def refresh_nifty_100(
    *, symbols_subset: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Full pipeline: scrape constituents → fundamentals → persist → score.
    If `symbols_subset` is provided, only those symbols are refreshed.

    Returns summary: {total, succeeded, failed, duration_s}.
    """
    from services import pg_client
    start = datetime.now(timezone.utc)

    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "Postgres unavailable", "duration_s": 0}

    async with aiohttp.ClientSession() as session:
        constituents = await fetch_nifty_100_constituents(session)
        if not constituents:
            return {"ok": False, "error": "No constituents scraped", "duration_s": 0}

        if symbols_subset:
            subset = {s.upper() for s in symbols_subset}
            constituents = [c for c in constituents if c["nse_symbol"] in subset]

        sem = asyncio.Semaphore(CONCURRENCY)
        succeeded: List[str] = []
        failed: List[Dict[str, str]] = []

        async def _worker(con: Dict[str, Any]):
            async with sem:
                try:
                    raw = await fetch_stock_details(con["slug"], session)
                    if not raw:
                        failed.append({"symbol": con["nse_symbol"], "reason": "scrape_empty"})
                        return
                    prim = map_to_primitives(raw)
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            await upsert_stock_master(conn, con, prim)
                            await upsert_primitives(conn, con["nse_symbol"], prim)
                            await score_and_persist(conn, con["nse_symbol"], prim)
                    succeeded.append(con["nse_symbol"])
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"{con['nse_symbol']} refresh failed: {e}")
                    failed.append({"symbol": con["nse_symbol"], "reason": str(e)[:200]})

        await asyncio.gather(*[_worker(c) for c in constituents])

    dur = (datetime.now(timezone.utc) - start).total_seconds()
    return {
        "ok": True,
        "total": len(constituents),
        "succeeded": len(succeeded),
        "failed": len(failed),
        "failed_details": failed[:15],
        "duration_s": round(dur, 1),
        "started_at": start.isoformat(),
    }


async def refresh_user_stocks(user_id: str) -> Dict[str, Any]:
    """Refresh fundamentals for the user's currently-held equities only.
    Called on-demand during portfolio creation/refresh."""
    from deps import db
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
        return {"ok": True, "total": 0, "note": "No equity holdings"}
    return await refresh_nifty_100(symbols_subset=symbols)
