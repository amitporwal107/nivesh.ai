"""Thin async client for the NIDP DAAS API.

Uses env vars:
  NIDP_DAAS_BASE_URL  — e.g. https://data.niveshcopilot.com/daas
  NIDP_DAAS_API_KEY   — API key issued by the DAAS /admin/keys endpoint

All methods raise DaasError on HTTP or connectivity failures so callers
can handle them uniformly without caring about httpx internals.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Lazy import to avoid circular deps at module load time.
def _secrets_get(key: str) -> str:
    try:
        from helpers import secrets
        return secrets.get(key)
    except Exception:
        return os.environ.get(key, "")

_DEFAULT_TIMEOUT = 10.0


class DaasError(Exception):
    """Raised when the DAAS API returns a non-200 response or is unreachable."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _creds() -> tuple[str, str]:
    base = _secrets_get("NIDP_DAAS_BASE_URL").rstrip("/")
    # Admin UI registers the key as NIDP_DAAS_INTERNAL_TOKEN; Cloud Run env var
    # may be named NIDP_DAAS_API_KEY — try both so either path works.
    key = _secrets_get("NIDP_DAAS_INTERNAL_TOKEN") or _secrets_get("NIDP_DAAS_API_KEY")
    if not base or not key:
        raise DaasError(
            "NIDP_DAAS_BASE_URL and NIDP_DAAS_API_KEY (or NIDP_DAAS_INTERNAL_TOKEN) must be set to call DAAS"
        )
    return base, key


async def _get(path: str, params: Optional[Dict[str, Any]] = None, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    base, key = _creds()
    url = f"{base}/v1{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"X-API-Key": key, "Accept": "application/json"},
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise DaasError(
                f"DAAS {path} returned HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()
    except httpx.TimeoutException:
        raise DaasError(f"DAAS request timed out after {timeout}s: {path}")
    except httpx.HTTPError as exc:
        raise DaasError(f"DAAS connectivity error on {path}: {exc}")


async def _post(path: str, body: Dict[str, Any], timeout: float = _DEFAULT_TIMEOUT) -> Any:
    base, key = _creds()
    url = f"{base}/v1{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "X-API-Key": key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise DaasError(
                f"DAAS {path} returned HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()
    except httpx.TimeoutException:
        raise DaasError(f"DAAS POST timed out after {timeout}s: {path}")
    except httpx.HTTPError as exc:
        raise DaasError(f"DAAS connectivity error on {path}: {exc}")


def is_configured() -> bool:
    """True when both NIDP_DAAS_BASE_URL and NIDP_DAAS_API_KEY are set.
    Callers use this to decide whether to attempt DaaS HTTP before
    falling back to a direct PG read.
    """
    key = _secrets_get("NIDP_DAAS_INTERNAL_TOKEN") or _secrets_get("NIDP_DAAS_API_KEY")
    return bool(_secrets_get("NIDP_DAAS_BASE_URL").strip() and key.strip())


async def get_stock_features_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the most recent technical feature row for a symbol.

    Returns the feature dict or None if no data exists.
    """
    data = await _get(f"/features/stocks/{symbol}/latest")
    if data is None:
        return None
    return data.get("data")


async def get_stock_features_history(
    symbol: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 30,
) -> list[Dict[str, Any]]:
    """Fetch historical feature rows for a symbol (newest first)."""
    params: Dict[str, Any] = {"limit": limit}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    data = await _get(f"/features/stocks/{symbol}", params=params)
    if data is None:
        return []
    return data.get("data", [])


async def get_stock_price_latest(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest OHLCV price row for a symbol."""
    data = await _get(f"/prices/latest/{symbol}")
    if data is None:
        return None
    return data.get("data")


async def get_stock_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest fundamental/financial data for a symbol."""
    data = await _get(f"/financials/{symbol}")
    if data is None:
        return None
    return data.get("data")


async def get_stock_scores(symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest persisted V3 composite scores + sector ranking for a symbol.

    Calls GET /v1/stocks/scores/{symbol} (nidp.v_v3_stock_scores_latest, with the
    sector-ranking columns from migration 086): quality_score, health_score,
    sector, industry, sector_rank, sector_size, sector_pct, band,
    fundamental_score, technical_score, final_score.

    Returns the score dict or None on 404 / connectivity failure so callers can
    omit the quality/rank section rather than fabricate it.
    """
    try:
        data = await _get(f"/stocks/scores/{symbol}")
    except DaasError as exc:
        logger.debug("get_stock_scores(%s): %s", symbol, exc)
        return None
    if data is None:
        return None
    return data.get("data") or None


async def get_sector_peers(sector: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Latest V3 scores for every stock in a sector, ranked by quality_score.

    Calls GET /v1/stocks/scores/ (the screener) filtered by sector. Used to build
    the in-card peer comparison. min_quality_coverage=0 so the full peer set is
    returned (ranking is by quality_score among whoever has one). Returns [] on
    any failure so the caller omits the peers section rather than fabricate it.
    """
    if not sector:
        return []
    try:
        data = await _get("/stocks/scores/", params={
            "sector": sector,
            "sort_by": "quality_score",
            "sort_desc": "true",
            "min_quality_coverage": 0,
            "limit": limit,
        })
    except DaasError as exc:
        logger.debug("get_sector_peers(%s): %s", sector, exc)
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    return rows if isinstance(rows, list) else []


async def list_stock_universe(limit: int = 800) -> List[Dict[str, Any]]:
    """All scored stocks (symbol + company_name + sector) — the full V3 equity
    universe — for chat autocomplete. Calls GET /v1/stocks/scores/ with no sector
    filter, ranked by quality so substring matches surface the better names first.
    Returns [] on any failure so the caller falls back to the curated list."""
    try:
        data = await _get("/stocks/scores/", params={
            "sort_by": "quality_score",
            "sort_desc": "true",
            "min_quality_coverage": 0,
            "limit": limit,
        })
    except DaasError as exc:
        logger.debug("list_stock_universe: %s", exc)
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


async def get_corporate_actions(symbol: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Recent corporate actions (dividends, splits, bonuses) for one symbol.

    Calls GET /v1/corporate-actions/{symbol} (newest ex_date first). Returns []
    on any failure so the caller omits the section rather than fabricate it.
    """
    try:
        data = await _get(f"/corporate-actions/{symbol}", params={"limit": limit})
    except DaasError as exc:
        logger.debug("get_corporate_actions(%s): %s", symbol, exc)
        return []
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    return rows if isinstance(rows, list) else []


# ── Market Pulse feeds — read the populated NIDP DB via DaaS ──────────────
# The Nivesh app's own Postgres carries the nidp.* schema but none of the
# ingested rows on some environments (staging), so the Market Pulse tabs must
# source these over DaaS rather than the app's direct pool. Each returns the
# dict the app's /api/markets/* endpoint forwards verbatim, or None on failure.

async def get_market_pulse_fii_dii(days: int = 90) -> Optional[Dict[str, Any]]:
    try:
        data = await _get("/market-pulse/fii-dii", params={"days": days})
    except DaasError as exc:
        logger.debug("get_market_pulse_fii_dii: %s", exc)
        return None
    return data if isinstance(data, dict) else None


async def get_market_pulse_corporate_actions(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    action_type: Optional[str] = None, q: Optional[str] = None,
    limit: int = 200, offset: int = 0,
) -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if date_from:   params["date_from"] = date_from
    if date_to:     params["date_to"] = date_to
    if action_type: params["action_type"] = action_type
    if q:           params["q"] = q
    try:
        data = await _get("/market-pulse/corporate-actions", params=params)
    except DaasError as exc:
        logger.debug("get_market_pulse_corporate_actions: %s", exc)
        return None
    return data if isinstance(data, dict) else None


async def get_market_pulse_articles(
    days: int = 7, category: Optional[str] = None, impact: Optional[str] = None,
    sentiment: Optional[str] = None, q: Optional[str] = None,
    limit: int = 60, offset: int = 0,
) -> Optional[Dict[str, Any]]:
    params: Dict[str, Any] = {"days": days, "limit": limit, "offset": offset}
    if category:  params["category"] = category
    if impact:    params["impact"] = impact
    if sentiment: params["sentiment"] = sentiment
    if q:         params["q"] = q
    try:
        data = await _get("/market-pulse/articles", params=params)
    except DaasError as exc:
        logger.debug("get_market_pulse_articles: %s", exc)
        return None
    return data if isinstance(data, dict) else None


async def get_market_pulse_movers(cap: str = "large") -> Optional[Dict[str, Any]]:
    try:
        data = await _get("/market-pulse/movers", params={"cap": cap})
    except DaasError as exc:
        logger.debug("get_market_pulse_movers: %s", exc)
        return None
    return data if isinstance(data, dict) else None


async def get_quarterly_financials(
    symbol: str,
    limit: int = 8,
    consolidated: bool = True,
) -> list[Dict[str, Any]]:
    """Fetch recent quarterly P&L, balance sheet rows from nse_financials_quarterly.

    Returns newest-first list of up to `limit` quarters.
    """
    params: Dict[str, Any] = {"limit": limit, "consolidated": str(consolidated).lower()}
    data = await _get(f"/financials/{symbol}", params=params)
    if data is None:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_shareholding_history(
    symbol: str,
    limit: int = 5,
) -> list[Dict[str, Any]]:
    """Fetch recent shareholding pattern rows (promoter/FII/DII/MF).

    Returns newest-first list of up to `limit` periods.
    """
    data = await _get(f"/shareholding/{symbol}", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_top_add_funds_by_category(
    category: str,
    n: int = 5,
    timeout: float = 8.0,
) -> List[Dict[str, Any]]:
    """Return the top-N MF candidates for an ADD recommendation in a given category.

    Calls GET /mf/performance/screener/top?metric=composite_rank&category_filter=<category>&limit=<n>.
    Returns rows with at minimum {scheme_name, isin, category, composite_rank, composite_score, return_3y}.
    Returns an empty list on DaaS unavailability so callers fall back to static defaults.
    """
    try:
        payload = await _get(
            "/mf/performance/screener/top",
            params={"metric": "composite_rank", "category_filter": category, "limit": n},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.debug("get_top_add_funds_by_category(%s): %s", category, exc)
        return []
    if not payload:
        return []
    rows = payload.get("data") or payload.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_mf_scorecard(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Full category scorecard for a scheme: composite_score, quality_label, quartile ranks.

    Returns None on 404 or DaaS unavailability so callers can degrade gracefully.
    """
    data = await _get(f"/mf/performance/scorecard/{scheme_code}")
    if data is None:
        return None
    return data.get("data") or data


async def get_mf_events(scheme_code: str, limit: int = 20) -> list[Dict[str, Any]]:
    """Lifecycle events for a scheme: TER changes, manager changes, risk shifts, mergers.

    Returns empty list on failure so callers never need to guard against None.
    """
    data = await _get(f"/mf/schemes/{scheme_code}/events", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("events") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


# ── MF card support (summary + overview/returns/holdings/peers detail views) ──

async def search_mf_schemes(q: str, limit: int = 8) -> list[Dict[str, Any]]:
    """Resolve a scheme NAME (substring, case-insensitive) to scheme master rows.

    Calls GET /mf/schemes?q=<name>&status=active (nidp.mf_scheme_master). Each row
    has scheme_code, scheme_name, amc_name, isin_growth, scheme_category, latest_nav.
    Returns an empty list on 404 / connectivity failure so callers degrade rather
    than raise. Results are AMFI-ordered by scheme_name.
    """
    q = (q or "").strip()
    if not q:
        return []
    try:
        data = await _get("/mf/schemes", params={"q": q, "status": "active", "limit": limit})
    except DaasError as exc:
        logger.debug("search_mf_schemes(%r): %s", q[:40], exc)
        return []
    if not data:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_mf_scheme(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Single scheme detail + latest disclosure (benchmark, managers, TER, risk, AUM).

    Calls GET /mf/schemes/{scheme_code}. Many disclosure fields can be null when the
    AMC-disclosure feed has not populated them — callers must omit, never default.
    Returns None on 404 / connectivity failure.
    """
    data = await _get(f"/mf/schemes/{scheme_code}")
    if data is None:
        return None
    return data.get("data") or data


async def get_mf_nav_series(scheme_code: str, limit: int = 2) -> list[Dict[str, Any]]:
    """Recent NAV rows (newest first) — used to derive the daily NAV change %.

    Calls GET /mf/nav/{scheme_code}?limit=<n>. Returns [] on failure.
    """
    data = await _get(f"/mf/nav/{scheme_code}", params={"limit": limit})
    if data is None:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_mf_holdings(
    scheme_code: str,
    instrument_type: Optional[str] = None,
    limit: int = 400,
) -> list[Dict[str, Any]]:
    """Per-security monthly holdings (weight DESC).

    Calls GET /mf/holdings/{scheme_code}. Each row: security_name, security_isin,
    instrument_type, sector, rating, quantity, market_value_inr, weight_pct.
    Returns [] on 404 (no holdings) OR HTTP 500 (the AMC-holdings feed is currently
    unreliable) so the caller can gate the holdings view on a non-empty list.
    """
    params: Dict[str, Any] = {"limit": limit}
    if instrument_type:
        params["instrument_type"] = instrument_type
    try:
        data = await _get(f"/mf/holdings/{scheme_code}", params=params)
    except DaasError as exc:
        logger.debug("get_mf_holdings(%s): %s", scheme_code, exc)
        return []
    if not data:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_mf_category_scorecard(
    sub_category: str,
    sort_by: str = "aum",
    limit: int = 12,
) -> list[Dict[str, Any]]:
    """Composite-scored category leaderboard (peers).

    Calls GET /mf/performance/scorecard/category/{sub_category} (ILIKE match on
    nidp.v_mf_category_scorecard). Each row has scheme_code, scheme_name, aum_cr,
    return_1y, return_3y, ter, composite_score, quality_label. Returns [] on 404.
    """
    sub = (sub_category or "").strip()
    if not sub:
        return []
    try:
        data = await _get(
            f"/mf/performance/scorecard/category/{sub}",
            params={"sort_by": sort_by, "limit": limit},
        )
    except DaasError as exc:
        logger.debug("get_mf_category_scorecard(%r): %s", sub[:40], exc)
        return []
    if not data:
        return []
    rows = data.get("data") or data.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_price_latest(symbol: str) -> Optional[float]:
    """Fetch the latest EOD close price for a single NSE symbol from NIDP.

    Returns None if the symbol has no price data yet (data lake may be empty
    before the yfinance backfill runs).
    """
    data = await _get(f"/prices/latest/{symbol}")
    if data is None:
        return None
    row = data.get("data") or data
    price = row.get("close_price") or row.get("prev_close")
    return float(price) if price is not None else None


async def get_prices_latest_batch(symbols: list[str]) -> Dict[str, float]:
    """Concurrently fetch latest close prices for a list of NSE symbols.

    Fires individual /prices/latest/{symbol} calls in parallel. Returns a
    symbol→close_price dict — missing symbols are simply absent (not errored).
    """
    import asyncio

    result: Dict[str, float] = {}

    async def _one(sym: str) -> None:
        try:
            p = await get_price_latest(sym)
            if p is not None:
                result[sym] = p
        except DaasError:
            pass

    await asyncio.gather(*(_one(s) for s in symbols), return_exceptions=True)
    return result


async def get_mf_category_sizes(
    categories: list[str],
    timeout: float = 3.0,
) -> Dict[str, int]:
    """Return {category: total_funds_in_category} for each category.

    Calls GET /mf/performance/category/{cat}?metric=composite_rank&limit=1
    which returns a `total` field. All requests run concurrently with a
    3s per-request timeout and a 5s hard ceiling for the whole batch,
    so this never adds more than ~5s to the critical path.
    """
    import asyncio as _asyncio

    async def _fetch_one(cat: str) -> tuple[str, int]:
        try:
            payload = await _get(
                f"/mf/performance/category/{cat}",
                params={"metric": "composite_rank", "limit": 1},
                timeout=timeout,
            )
            total = payload.get("total") if payload else None
            return cat, int(total) if total else 0
        except Exception:  # noqa: BLE001
            return cat, 0

    if not categories:
        return {}
    try:
        results = await _asyncio.wait_for(
            _asyncio.gather(*[_fetch_one(c) for c in categories]),
            timeout=5.0,
        )
    except _asyncio.TimeoutError:
        return {}
    return {cat: total for cat, total in results if total > 0}


# ── V3 primitives (bulk) ─────────────────────────────────────────────

async def get_v3_mf_primitives_bulk(
    isins: list[str],
    timeout: float = 15.0,
) -> Dict[str, Dict[str, Any]]:
    """Fetch the V3 primitive row for each ISIN.

    Returns ``{isin: {primitive_row}}`` keyed by ISIN. Empty dict on
    connectivity failure / missing config so the caller can fall back
    to a direct PG read without raising.

    NIDP keys its MF primitives view on ISIN (migration 058) — the
    natural cross-system identifier from CAS imports. The Nivesh-side
    caller resolves instrument_id → ISIN via the local instrument_master
    PG table before invoking this.
    """
    if not isins:
        return {}
    try:
        payload = await _post(
            "/mf/performance/v3-primitives/bulk",
            {"isins": isins},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.warning("get_v3_mf_primitives_bulk: %s", exc)
        return {}
    if not payload:
        return {}
    data = payload.get("data") or {}
    return data if isinstance(data, dict) else {}


async def get_category_top(
    category: str,
    n: int = 5,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """Return top-N ranked funds for a SEBI category from mf_category_rank_daily.

    Returns {category, rank_date, total_in_category, funds: [{scheme_code, scheme_name,
    category_rank, category_pct, composite, ret_3y, ret_1y, sharpe, expense_ratio}]}.
    Empty dict on failure.
    """
    if not category:
        return {}
    try:
        import urllib.parse
        params = {"category": category, "n": n}
        payload = await _get("/mf/performance/category-top", params=params, timeout=timeout)
    except DaasError as exc:
        logger.warning("get_category_top(%r): %s", category[:40], exc)
        return {}
    return payload or {}


async def get_user_holdings(
    external_user_id: str,
    on: Optional[str] = None,
    limit: int = 500,
) -> list[Dict[str, Any]]:
    """Fetch a user's holdings from NIDP — joined with `ref.security_master`
    (for scheme_name + sector) and `analytics.fund_category_rank` (for TER
    + rolling returns).

    Returns the rows list (newest snapshot, ordered by market value DESC) or
    an empty list on DaaS unavailability so the caller can fall back without
    raising.

    `external_user_id` is the email NIDP uses as the canonical user key.
    """
    if not external_user_id:
        return []
    params: Dict[str, Any] = {"limit": limit}
    if on:
        params["on"] = on
    try:
        payload = await _get(
            f"/intelligence/portfolio/{external_user_id}/holdings",
            params=params,
        )
    except DaasError as exc:
        logger.warning("get_user_holdings(%s): %s", external_user_id, exc)
        return []
    if not payload:
        return []
    rows = payload.get("data") or payload.get("rows") or []
    return rows if isinstance(rows, list) else []


async def get_portfolio_correlations(
    security_ids: list[str],
    min_abs_corr: float = 0.7,
    window_days: Optional[int] = 90,
    timeout: float = 10.0,
) -> list[dict]:
    """Fetch pairwise correlations for all holdings in a portfolio.

    Calls POST /v1/intelligence/graph/correlations/bulk — returns only pairs
    where BOTH sides are in the supplied security_id list (the portfolio
    correlation subgraph). security_ids are UUIDs from ref.security_master.

    Returns empty list on connectivity failure so the CorrelationEngine
    degrades gracefully to zero pairs rather than crashing the pipeline.

    Args:
        security_ids:  UUIDs from ref.security_master (max 50).
        min_abs_corr:  Only return pairs with |corr| >= this value (default 0.7).
        window_days:   Lookback window filter — 90 for 90-day Pearson (default).
                       Pass None to get all windows.
    """
    if not security_ids:
        return []
    try:
        payload = await _post(
            "/intelligence/graph/correlations/bulk",
            {"security_ids": security_ids},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.warning("get_portfolio_correlations: %s", exc)
        return []
    if not payload:
        return []
    rows = payload.get("data") or []
    # Apply client-side filters in case server params weren't respected
    result = [r for r in rows if isinstance(r, dict)]
    if min_abs_corr > 0:
        result = [r for r in result if float(r.get("abs_correlation") or 0) >= min_abs_corr]
    return result


async def get_v3_stock_primitives_bulk(
    symbols: list[str],
    timeout: float = 15.0,
) -> Dict[str, Dict[str, Any]]:
    """Fetch the latest V3 primitive row for each NSE symbol.

    Empty dict on connectivity failure so callers can degrade to the
    PG-direct path.
    """
    if not symbols:
        return {}
    try:
        payload = await _post(
            "/stocks/v3-primitives/bulk",
            {"symbols": symbols},
            timeout=timeout,
        )
    except DaasError as exc:
        logger.warning("get_v3_stock_primitives_bulk: %s", exc)
        return {}
    if not payload:
        return {}
    data = payload.get("data") or {}
    return data if isinstance(data, dict) else {}


async def get_portfolio_risk(
    external_user_id: str,
    timeout: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """Fetch the latest precomputed PRA risk snapshot for a user.

    Calls GET /v1/portfolio-risk/{external_user_id}.
    Returns None if no result exists (404) or on connectivity failure.
    """
    try:
        payload = await _get(
            f"/portfolio-risk/{external_user_id}",
            timeout=timeout,
        )
    except DaasError as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        logger.warning("get_portfolio_risk[%s]: %s", external_user_id, exc)
        return None
    if not payload:
        return None
    return payload.get("data") or payload


async def get_portfolio_snapshot(
    external_user_id: str,
    timeout: float = 8.0,
) -> Optional[Dict[str, Any]]:
    """Fetch the latest NIDP portfolio snapshot for a user.

    Calls GET /v1/intelligence/portfolio/{external_user_id}/snapshot.
    Returns a dict with keys like: total_market_value_inr, equity_weight_pct,
    debt_weight_pct, avg_beta_90d, top_sector, top_sector_weight_pct,
    concentration_top5_pct, quality_tier, avg_rsi_14, high_corr_pairs,
    snapshot_date.
    Returns None on 404 / connectivity failure so callers can fall back.
    """
    if not external_user_id:
        return None
    try:
        payload = await _get(
            f"/intelligence/portfolio/{external_user_id}/snapshot",
            timeout=timeout,
        )
    except DaasError as exc:
        if getattr(exc, "status_code", None) == 404:
            return None
        logger.warning("get_portfolio_snapshot[%s]: %s", external_user_id, exc)
        return None
    if not payload:
        return None
    return payload.get("data") or payload


# ── Sleeve builder support — rank funds within a sub-category ─────────────────

# Plans that should never be recommended even if they rank high: segregated side-
# pockets, unclaimed/closed/matured plans, and IDCW (income) variants.
_JUNK_PLAN = re.compile(r"segregated|unclaimed|closed[\s-]?end|matured|idcw|dividend", re.I)


async def get_top_funds_by_subcategory(
    fund_category: Optional[str],
    sub_category: str,
    n: int = 3,
    timeout: float = 8.0,
) -> List[Dict[str, Any]]:
    """Return the top-`n` V3-scored funds in a sub-category, ranked by quality.

    Powers the sleeve-based Portfolio Builder. Calls GET /v1/mf/scores/ filtered
    by fund_category (optional) + sub_category (ILIKE), sorted by quality_score
    DESC. Coverage gate is 0 here because sub-category universes are small and
    average coverage is modest; ranking is relative WITHIN the sleeve. Junk plans
    (segregated/unclaimed/IDCW) are dropped and Direct plans preferred.

    Returns [] on connectivity failure so a sleeve degrades to "no picks yet"
    rather than fabricating one.
    """
    if not sub_category:
        return []
    params: Dict[str, Any] = {
        "sub_category": sub_category,
        "sort_by": "quality_score",
        "sort_desc": "true",
        "min_quality_coverage": 0,
        "limit": 40,
    }
    if fund_category:
        params["fund_category"] = fund_category
    try:
        data = await _get("/mf/scores/", params=params, timeout=timeout)
    except DaasError as exc:
        logger.debug("get_top_funds_by_subcategory(%r): %s", sub_category, exc)
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []

    clean = [r for r in rows if not _JUNK_PLAN.search(str(r.get("scheme_name") or ""))]
    direct = [r for r in clean if "direct" in str(r.get("scheme_name") or "").lower()]
    pool = direct if len(direct) >= n else clean
    return pool[:n]


async def get_debt_sleeve_funds(
    fund_category: Optional[str],
    sub_category: str,
    pool: int = 40,
    timeout: float = 10.0,
) -> List[Dict[str, Any]]:
    """Candidate debt funds in a sub-category WITH the NAV-side primitives the
    governed debt model needs (Sharpe, TER, AUM, FM tenure, max drawdown).

    Two-step: (1) the scored screener for the candidate ISINs (junk-filtered,
    Direct-preferred), (2) the v3-primitives bulk endpoint for their raw fields.
    Returns fund dicts ready for services.debt_scoring.rank_peers(). [] on
    failure so the sleeve degrades rather than fabricates.
    """
    rows = await get_top_funds_by_subcategory(fund_category, sub_category, n=pool, timeout=timeout)
    isins = [r.get("isin") for r in rows if r.get("isin")]
    prims = await get_v3_mf_primitives_bulk(isins) if isins else {}
    out: List[Dict[str, Any]] = []
    for r in rows:
        p = prims.get(r.get("isin")) or {}
        out.append({
            "scheme_name": r.get("scheme_name"),
            "isin": r.get("isin"),
            "sub_category": sub_category,
            "sharpe": p.get("sharpe"),
            "expense_ratio": p.get("expense_ratio_direct") or p.get("expense_ratio"),
            "aum_cr": p.get("aum_cr"),
            "manager_tenure_years": p.get("manager_tenure_years"),
            "max_drawdown_pct": p.get("max_drawdown_pct"),
        })
    return out
