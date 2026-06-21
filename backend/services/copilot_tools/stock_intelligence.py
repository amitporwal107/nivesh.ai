"""NIDP-backed stock intelligence tool for the copilot.

Aggregates four NIDP intelligence layers for a single stock:

  1. V3 primitives → stock_scoring.score_stock() → quality/health/exit/add scores
  2. AI event signals  → /v1/signals/{symbol}          (sentiment, confidence)
  3. Recent announcements → /v1/announcements?symbol=X  (AI-classified filings)
  4. Intelligence features → /v1/intelligence/features/stocks/{symbol}
                             (volatility, beta, sharpe, relative strength)

Public API:
    get_stock_intelligence(symbol) → StockIntelResult
    get_nidp_screener(metric, sector, market_cap, limit) → list[dict]
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StockIntelResult:
    symbol: str
    ok: bool
    summary: str
    # V3 composite scores (None if not computed)
    quality_score:  Optional[float] = None
    health_score:   Optional[float] = None
    exit_score:     Optional[float] = None
    add_score:      Optional[float] = None
    recommendation: str = "REVIEW"
    recommendation_reason: str = ""
    # Rich data for LLM
    primitives:  Dict[str, Any] = field(default_factory=dict)
    signals:     List[Dict[str, Any]] = field(default_factory=list)
    news:        List[Dict[str, Any]] = field(default_factory=list)
    intel_features: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        lines = [f"symbol={self.symbol}"]
        if self.quality_score is not None:
            lines.append(
                f"V3_scores quality={self.quality_score:.1f} health={self.health_score:.1f} "
                f"exit={self.exit_score:.1f} add={self.add_score:.1f} "
                f"→ {self.recommendation}: {self.recommendation_reason}"
            )
        for k, v in self.primitives.items():
            if v is not None and k not in ("symbol", "as_of_date"):
                lines.append(f"  {k}={v}")
        if self.signals:
            lines.append("AI_signals:")
            for s in self.signals[:3]:
                lines.append(f"  [{s.get('event_type','?')}] sentiment={s.get('sentiment','?')} conf={s.get('confidence',0):.0%} {s.get('headline','')[:80]}")
        if self.news:
            lines.append("recent_announcements:")
            for n in self.news[:3]:
                lines.append(f"  [{n.get('category','?')}] {n.get('headline','')[:80]} impact={n.get('ai_impact','?')}")
        if self.intel_features:
            f = self.intel_features
            lines.append(
                f"intel_features: vol={f.get('volatility_20d')} beta={f.get('beta_nifty')} "
                f"sharpe={f.get('sharpe_1y')} rel_strength={f.get('relative_strength_nifty')}"
            )
        return " | ".join(lines)


async def _daas_get(path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """Thin async GET against DAAS; mirrors daas_bridge.call_daas() without circular import."""
    import os, httpx
    base = os.environ.get("NIDP_DAAS_BASE_URL", "https://data.niveshcopilot.com/daas").rstrip("/")
    # Admin UI registers the key as NIDP_DAAS_INTERNAL_TOKEN; Cloud Run may use
    # NIDP_DAAS_API_KEY — accept either so the call authenticates on both paths.
    key  = os.environ.get("NIDP_DAAS_API_KEY", "") or os.environ.get("NIDP_DAAS_INTERNAL_TOKEN", "")
    headers = {"X-API-Key": key, "Accept": "application/json"} if key else {"Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{base}{path}", params=params or {}, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception as exc:
        logger.debug("DAAS %s failed: %s", path, exc)
        return {}


async def get_stock_intelligence(symbol: str) -> StockIntelResult:
    """Fetch all NIDP intelligence layers for `symbol` concurrently, compute V3 scores,
    and return a structured result the copilot nodes can embed into LLM context."""
    sym = symbol.upper()

    # ── Concurrent fetch of all 4 data sources ────────────────────────
    primitives_resp, signals_resp, announcements_resp, intel_resp = await asyncio.gather(
        _daas_get(f"/v1/stocks/{sym}/score"),
        _daas_get(f"/v1/signals/{sym}", {"limit": 5}),
        _daas_get("/v1/announcements", {"symbol": sym, "limit": 3, "sort": "filed_at"}),
        _daas_get(f"/v1/intelligence/features/stocks/{sym}", {"limit": 1}),
        return_exceptions=True,
    )

    # ── Parse primitives ──────────────────────────────────────────────
    primitives: Dict[str, Any] = {}
    if isinstance(primitives_resp, dict) and primitives_resp.get("data"):
        primitives = primitives_resp["data"]

    # ── Compute V3 composite scores from primitives ───────────────────
    quality_score = health_score = exit_score = add_score = None
    recommendation = "REVIEW"
    rec_reason = ""
    if primitives:
        try:
            from services import stock_scoring
            bundle = stock_scoring.score_stock(primitives)
            quality_score = bundle.get("quality_score")
            health_score  = bundle.get("health_score")
            exit_score    = bundle.get("exit_score")
            add_score     = bundle.get("add_score")
            rec           = bundle.get("recommendation") or {}
            recommendation = rec.get("action", "REVIEW")
            rec_reason     = rec.get("reason", "")
        except Exception as exc:
            logger.debug("V3 scoring failed for %s: %s", sym, exc)

    # ── Parse AI signals ──────────────────────────────────────────────
    signals: List[Dict] = []
    if isinstance(signals_resp, dict):
        signals = signals_resp.get("rows") or signals_resp.get("signals") or []
    elif isinstance(signals_resp, list):
        signals = signals_resp

    # ── Parse announcements ───────────────────────────────────────────
    news: List[Dict] = []
    if isinstance(announcements_resp, dict):
        news = announcements_resp.get("rows") or announcements_resp.get("announcements") or []
    elif isinstance(announcements_resp, list):
        news = announcements_resp

    # ── Parse intelligence features ───────────────────────────────────
    intel_features: Dict[str, Any] = {}
    if isinstance(intel_resp, dict):
        rows = intel_resp.get("rows") or intel_resp.get("data") or []
        if rows and isinstance(rows, list):
            intel_features = rows[0] if isinstance(rows[0], dict) else {}
        elif isinstance(intel_resp.get("data"), dict):
            intel_features = intel_resp["data"]

    ok = bool(primitives or signals or news)
    summary_parts = []
    if quality_score is not None:
        summary_parts.append(f"Q={quality_score:.0f} H={health_score:.0f} E={exit_score:.0f} A={add_score:.0f} → {recommendation}")
    if signals:
        summary_parts.append(f"{len(signals)} AI signals")
    if news:
        summary_parts.append(f"{len(news)} announcements")
    summary = f"{sym}: " + (", ".join(summary_parts) if summary_parts else "data unavailable")

    return StockIntelResult(
        symbol=sym,
        ok=ok,
        summary=summary,
        quality_score=quality_score,
        health_score=health_score,
        exit_score=exit_score,
        add_score=add_score,
        recommendation=recommendation,
        recommendation_reason=rec_reason,
        primitives=primitives,
        signals=signals,
        news=news,
        intel_features=intel_features,
    )


async def get_nidp_screener(
    metric: str = "momentum_score",
    sector: Optional[str] = None,
    market_cap: Optional[str] = None,
    limit: int = 10,
    min_roe: Optional[float] = None,
    max_de: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Fetch top-N stocks from NIDP screener sorted by `metric`.

    Returns a list of stock dicts with full V3 primitives. The recommendation
    node uses this as the primary ranking source instead of per-stock scoring.
    """
    resp = await _daas_get(
        "/v1/stocks/screener/top",
        {
            "metric":     metric,
            "sector":     sector,
            "market_cap": market_cap,
            "limit":      limit,
        },
    )
    if isinstance(resp, dict):
        stocks = resp.get("stocks") or resp.get("rows") or []
    elif isinstance(resp, list):
        stocks = resp
    else:
        stocks = []

    # Compute V3 scores for each returned stock (batch)
    try:
        from services import stock_scoring
        scored = []
        for s in stocks:
            try:
                bundle = stock_scoring.score_stock(s)
                s["quality_score"] = bundle.get("quality_score")
                s["health_score"]  = bundle.get("health_score")
                s["exit_score"]    = bundle.get("exit_score")
                s["add_score"]     = bundle.get("add_score")
                rec = bundle.get("recommendation") or {}
                s["recommendation"]        = rec.get("action", "REVIEW")
                s["recommendation_reason"] = rec.get("reason", "")
            except Exception:
                pass
            scored.append(s)
        return scored
    except Exception as exc:
        logger.debug("Batch scoring failed: %s", exc)
        return stocks


# ── stock_screener widget (chat) ───────────────────────────────────────────
# Powers the V5 `stock_screener` chat widget. Fetches a real universe from the
# NIDP multi-metric screener (GET /v1/stocks/screener over nidp.stock_features_daily)
# and shapes it into the widget contract the frontend renders. The frontend
# filters/sorts THESE rows locally and recompiles the query string — it never
# recomputes a metric NIDP owns.

# ── Primitive catalog ───────────────────────────────────────────────────────
# The full set of screenable primitives, each backed by a REAL column on
# nidp.stock_features_daily (exposed by GET /v1/stocks/screener — see
# daas_api/routers/stock_scores.py _PRIMITIVE_COLS). Grouped screener.in-style.
# (key, nidp_col, label, group). This single list drives the universe field map,
# the query-bar labels, and the NL parser — so chat, autocomplete and the widget
# stay in lock-step. The displayed TABLE and the Refine PANEL use curated subsets
# (below) for readability; any primitive here is still NL/autocomplete-filterable.
_SCREENER_PRIMITIVES = [
    # Valuation
    ("pe",                 "pe_ttm",                     "P/E",                 "Valuation"),
    ("pb",                 "pb",                         "P/B",                 "Valuation"),
    ("evEbitda",           "ev_ebitda",                  "EV / EBITDA",         "Valuation"),
    ("peVsSector",         "pe_vs_sector_pct",           "P/E vs sector",       "Valuation"),
    ("divYield",           "dividend_yield_pct",         "Dividend Yield",      "Valuation"),
    # Profitability / quality
    ("roe",                "roe_pct",                    "ROE",                 "Profitability"),
    ("roce",               "roce_pct",                   "ROCE",                "Profitability"),
    ("profitMargin",       "profit_margin_pct",          "Net margin",          "Profitability"),
    ("interestCoverage",   "interest_coverage",          "Interest cover",      "Profitability"),
    ("earningsConsistency","earnings_consistency_score", "Earnings consistency","Profitability"),
    # Growth
    ("salesG",             "revenue_growth_3y_cagr_pct", "Sales growth 3Y",     "Growth"),
    ("profitG",            "eps_growth_3y_cagr_pct",     "Profit growth 3Y",    "Growth"),
    ("salesGyoy",          "revenue_growth_yoy_pct",     "Sales growth YoY",    "Growth"),
    ("profitGyoy",         "pat_growth_yoy_pct",         "Profit growth YoY",   "Growth"),
    ("epsGyoy",            "eps_growth_yoy_pct",         "EPS growth YoY",      "Growth"),
    ("marginTrend",        "profit_margin_trend_pct",    "Margin trend",        "Growth"),
    # Financial health
    ("de",                 "debt_to_equity",             "Debt / Equity",       "Financial health"),
    ("debtTrend",          "debt_trend_pct",             "Debt trend",          "Financial health"),
    ("liquidity",          "liquidity_score",            "Liquidity score",     "Financial health"),
    # Size
    ("mcap",               "market_cap_cr",              "Market Cap",          "Size"),
    # Price / technical
    ("return1y",           "return_252d_pct",            "1Y return",           "Price / technical"),
    ("volatility",         "volatility_1y_pct",          "Volatility 1Y",       "Price / technical"),
    ("beta",               "beta_1y",                    "Beta",                "Price / technical"),
    ("maxDrawdown",        "max_drawdown_1y_pct",        "Max drawdown 1Y",     "Price / technical"),
    ("rsi",                "rsi14",                      "RSI (14)",            "Price / technical"),
    ("momentum",           "momentum_score",             "Momentum score",      "Price / technical"),
    ("accumulation",       "accumulation_score",         "Accumulation score",  "Price / technical"),
    # Ownership / smart money
    ("promoter",           "promoter_pct",               "Promoter holding",    "Ownership"),
    ("promoterPledge",     "promoter_pledged_pct",       "Promoter pledge",     "Ownership"),
    ("fii",                "fii_pct",                    "FII holding",         "Ownership"),
    ("dii",                "dii_pct",                    "DII holding",         "Ownership"),
    ("fiiChange",          "fii_pct_change_qoq",         "FII change QoQ",      "Ownership"),
    ("promoterChange",     "promoter_pct_change_qoq",    "Promoter change QoQ", "Ownership"),
]

# widget key → raw NIDP column (identity fields first, then every primitive).
_SCREENER_FIELD_MAP = (
    [("name", "symbol"), ("ticker", "symbol"), ("sector", "sector")]
    + [(k, col) for (k, col, _lbl, _grp) in _SCREENER_PRIMITIVES]
)

# key → short label for the compiled query string (covers ALL primitives, so an
# NL-set filter that isn't in the Refine panel still labels cleanly).
_SCREENER_FILTER_LABELS = {k: lbl for (k, _col, lbl, _grp) in _SCREENER_PRIMITIVES}

# Curated TABLE columns (kept readable in the chat column).
_SCREENER_COLUMNS = [
    {"key": "name",     "label": "Stock",     "kind": "text", "align": "left"},
    {"key": "sector",   "label": "Sector",    "kind": "text", "align": "left"},
    {"key": "mcap",     "label": "Mkt Cap",   "unit": "Cr", "kind": "num", "align": "right"},
    {"key": "pe",       "label": "P/E",       "kind": "num", "align": "right"},
    {"key": "roe",      "label": "ROE",       "unit": "%", "kind": "num", "align": "right", "goodHigh": True},
    {"key": "roce",     "label": "ROCE",      "unit": "%", "kind": "num", "align": "right", "goodHigh": True},
    {"key": "de",       "label": "D/E",       "kind": "num", "align": "right", "goodLow": True, "decimals": 2},
    {"key": "divYield", "label": "Div Yld",   "unit": "%", "kind": "num", "align": "right"},
    {"key": "salesG",   "label": "Sales 3Y",  "unit": "%", "kind": "num", "align": "right", "signed": True},
    {"key": "profitG",  "label": "Profit 3Y", "unit": "%", "kind": "num", "align": "right", "signed": True},
    {"key": "return1y", "label": "1Y Ret",    "unit": "%", "kind": "num", "align": "right", "signed": True},
]

# Curated Refine PANEL (numeric min/max controls). The full catalog is still
# reachable via natural language / composer autocomplete.
_SCREENER_FILTER_DEFS = [
    {"key": "mcap",     "label": "Market Cap",      "qlabel": "Market Cap",      "unit": "Cr", "min": True,  "max": True},
    {"key": "pe",       "label": "P/E Ratio",       "qlabel": "P/E",             "min": True,  "max": True},
    {"key": "roe",      "label": "ROE",             "qlabel": "ROE",             "unit": "%", "min": True,  "max": True},
    {"key": "roce",     "label": "ROCE",            "qlabel": "ROCE",            "unit": "%", "min": True,  "max": True},
    {"key": "de",       "label": "Debt / Equity",   "qlabel": "Debt to Equity",  "min": False, "max": True},
    {"key": "divYield", "label": "Dividend Yield",  "qlabel": "Dividend Yield",  "unit": "%", "min": True,  "max": False},
    {"key": "salesG",   "label": "Sales Growth 3Y", "qlabel": "Sales Growth",    "unit": "%", "min": True,  "max": False},
    {"key": "profitG",  "label": "Profit Growth 3Y","qlabel": "Profit Growth",   "unit": "%", "min": True,  "max": False},
    {"key": "return1y", "label": "1Y Return",       "qlabel": "1Y Return",       "unit": "%", "min": True,  "max": True},
    {"key": "rsi",      "label": "RSI (14)",        "qlabel": "RSI",             "min": True,  "max": True},
    {"key": "promoterPledge", "label": "Promoter Pledge", "qlabel": "Promoter Pledge", "unit": "%", "min": False, "max": True},
]

_SCREENER_PRESETS = [
    {"name": "Quality compounders", "query": "Screen stocks where ROE over 18, ROCE over 18, debt to equity under 0.5"},
    {"name": "Low-debt growth",     "query": "Screen stocks where debt to equity under 0.3, sales growth over 12, profit growth over 12"},
    {"name": "Dividend payers",     "query": "Screen stocks where dividend yield over 2"},
    {"name": "Value picks",         "query": "Screen stocks where P/E under 18, ROE over 12"},
    {"name": "Large caps",          "query": "Screen large cap stocks"},
]


async def nidp_stock_screener(
    *,
    sector: Optional[str] = None,
    market_cap: Optional[str] = None,
    min_roe: Optional[float] = None,
    max_de: Optional[float] = None,
    min_sales_cagr_3y: Optional[float] = None,
    min_profit_cagr_3y: Optional[float] = None,
    max_rsi: Optional[float] = None,
    min_rsi: Optional[float] = None,
    max_pe_vs_sector: Optional[float] = None,
    sort_by: str = "roe_pct",
    limit: int = 60,
) -> Dict[str, Any]:
    """Fetch a real stock universe from GET /v1/stocks/screener.

    Server-side filters (the ones the endpoint supports — ROE, D/E, 3Y growth,
    RSI, P/E-vs-sector, sector, cap) narrow the set; every other primitive is
    applied client-side by the widget over the returned rows. Returns
    {"rows": [...], "as_of_date": str|None}.
    """
    params: Dict[str, Any] = {"sort_by": sort_by, "sort_desc": True, "limit": limit}
    if sector:             params["sector"] = sector
    if market_cap:         params["market_cap"] = market_cap
    if min_roe is not None: params["min_roe"] = min_roe
    if max_de is not None:  params["max_de"] = max_de
    if min_sales_cagr_3y is not None:  params["min_rev_cagr_3y"] = min_sales_cagr_3y
    if min_profit_cagr_3y is not None: params["min_eps_cagr_3y"] = min_profit_cagr_3y
    if max_rsi is not None:            params["max_rsi"] = max_rsi
    if min_rsi is not None:            params["min_rsi"] = min_rsi
    if max_pe_vs_sector is not None:   params["max_pe_vs_sector"] = max_pe_vs_sector

    resp = await _daas_get("/v1/stocks/screener", params)
    if not isinstance(resp, dict):
        return {"rows": [], "as_of_date": None}
    rows = resp.get("data") or resp.get("rows") or []
    # envelope() carries the date at the top level via `extra`; older shapes used meta.
    as_of = resp.get("as_of_date") or (resp.get("meta") or {}).get("as_of_date")
    return {"rows": rows, "as_of_date": as_of}


def build_stock_screener_widget(
    raw_rows: List[Dict[str, Any]],
    *,
    title: str = "Stock screen",
    initial_filters: Optional[Dict[str, float]] = None,
    as_of_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Shape raw NIDP screener rows into the `stock_screener` widget contract."""
    universe: List[Dict[str, Any]] = []
    for r in raw_rows:
        row: Dict[str, Any] = {}
        for wkey, src in _SCREENER_FIELD_MAP:
            row[wkey] = r.get(src)
        universe.append(row)

    note = "Live NIDP feature store" + (f" · as of {as_of_date}" if as_of_date else "")
    note += " · figures are exchange-filed fundamentals, not investment advice."
    return {
        "title": title,
        "columns": _SCREENER_COLUMNS,
        "universe": universe,
        "rows": universe,                       # alias — frontend reads universe||rows
        "filter_defs": _SCREENER_FILTER_DEFS,
        "filter_labels": _SCREENER_FILTER_LABELS,
        "filters": initial_filters or {},
        "presets": _SCREENER_PRESETS,
        "sort": {"key": "mcap", "dir": "desc"},
        "name_key": "name",
        "ticker_key": "ticker",
        "sector_key": "sector",
        "ask_template": "Tell me about {ticker} — is it worth a deeper look?",
        "count": len(universe),
        "source": "NIDP stock feature store",
        "note": note,
    }
