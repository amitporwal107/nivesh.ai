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
    key  = os.environ.get("NIDP_DAAS_API_KEY", "")
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
