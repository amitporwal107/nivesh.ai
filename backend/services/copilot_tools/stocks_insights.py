"""Stocks-Insights tool — the data layer behind the Copilot "stocks insights"
tool (Nivesh Copilot).

Answers questions about a company's *corporate disclosures* (order wins, results,
M&A, board outcomes, fund raises) grounded in exchange filings. Data comes from
the NIDP DAAS API (the reachable NIDP data plane) — the app runtime does NOT have
the nidp.* tables locally, so DAAS is the source of truth:

  • per-ticker recent filings   → GET /v1/announcements?symbol=…
  • per-ticker events           → GET /v1/events/{symbol}
  • thematic cross-company      → GET /v1/intelligence/events/search?q=…

v1 citations are **filing-level**: every event carries its source-filing URL
("View Source" → the exchange PDF). DAAS exposes no document-chunk/page retrieval,
so page-level (#page=N slide/transcript) citations are a documented fast-follow.

The node (nodes/stocks_insights.py) composes the grounded LLM answer over the
events this tool returns and enforces the no-advice + refusal-on-empty rules.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import daas_client

logger = logging.getLogger(__name__)

DISCLAIMER = "AI-generated from exchange filings. Verify against the original filing."

# Fields we defensively read from a DAAS announcement/event row (shapes vary a
# little across /v1/announcements, /v1/events, /v1/intelligence/events/search).
_HEADLINE_KEYS = ("headline", "subject", "title", "summary", "description")
_CATEGORY_KEYS = ("category", "event_category", "event_type", "type")
_IMPACT_KEYS = ("ai_impact", "impact", "materiality")
_FILED_KEYS = ("filed_at", "filed_date", "as_of", "date", "event_date", "published_at")
_URL_KEYS = ("url", "attachment_url", "source_url", "pdf_url", "filing_url", "link")
_SYMBOL_KEYS = ("symbol", "nse_symbol", "ticker", "security_symbol")
_ID_KEYS = ("announcement_id", "event_id", "id")


@dataclass
class StocksInsightsResult:
    ok: bool
    summary: str                                    # ≤300-char LLM context line
    ticker: Optional[str] = None
    mode: str = "ticker"                            # "ticker" | "thematic"
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        """A compact, numbered list of filings for the LLM to ground + cite."""
        if not self.events:
            return "recent_filings: NONE FOUND"
        lines = ["recent_filings (cite as [n]):"]
        for i, e in enumerate(self.events, start=1):
            filed = (e.get("filed_at") or "")[:10]
            lines.append(
                f"  [{i}] {filed} [{e.get('category') or 'other'}] "
                f"{(e.get('headline') or '')[:110]}"
                + (f" (impact={e['impact']})" if e.get("impact") else "")
            )
        return "\n".join(lines)


def _first(row: Dict[str, Any], keys: tuple, default: Any = None) -> Any:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return default


def _shape_event(row: Dict[str, Any]) -> Dict[str, Any]:
    """Pure: normalise one raw DAAS row into the card's event shape.

    Defensive across the slightly different shapes of /v1/announcements,
    /v1/events/{symbol} and /v1/intelligence/events/search rows.
    """
    cat = _first(row, _CATEGORY_KEYS, "other")
    return {
        "id": _first(row, _ID_KEYS),
        "symbol": _first(row, _SYMBOL_KEYS),
        "category": str(cat).lower().replace(" ", "_") if cat else "other",
        "headline": _first(row, _HEADLINE_KEYS, ""),
        "impact": _first(row, _IMPACT_KEYS),
        "filed_at": _first(row, _FILED_KEYS),
        "url": _first(row, _URL_KEYS),
    }


def _shape_events(rows: Any, limit: int = 8) -> List[Dict[str, Any]]:
    """Pure: normalise a DAAS list/response into a bounded list of card events.

    Accepts either a bare list or a {rows|announcements|events|results|items:[…]}
    envelope (DAAS is inconsistent across endpoints). Drops rows with no headline.
    """
    if isinstance(rows, dict):
        rows = (rows.get("rows") or rows.get("announcements") or rows.get("events")
                or rows.get("results") or rows.get("items") or rows.get("data")
                or rows.get("hits") or [])
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        ev = _shape_event(r)
        if ev["headline"]:
            out.append(ev)
        if len(out) >= limit:
            break
    return out


async def _daas_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Thin GET against DAAS; returns {} on any error (never raises into the node)."""
    try:
        return await daas_client._get(path, params or {})
    except Exception as exc:  # noqa: BLE001 — DaasError or connectivity; degrade gracefully
        logger.warning("DAAS %s failed: %s", path, exc)
        return {}


async def get_stocks_insights(
    query: str,
    symbol: Optional[str] = None,
    limit: int = 8,
) -> StocksInsightsResult:
    """Fetch recent corporate filings for the query.

    If ``symbol`` is given → per-ticker filings (announcements + events).
    Otherwise → thematic free-text search across companies.
    """
    if not daas_client.is_configured():
        return StocksInsightsResult(
            ok=False, summary="DAAS not configured", error="DAAS credentials missing",
        )

    if symbol:
        sym = symbol.upper()
        # NOTE: daas_client._get already prepends "/v1" — paths here must NOT.
        ann_resp, ev_resp = await asyncio.gather(
            _daas_get("/announcements", {"symbol": sym, "limit": limit, "sort": "filed_at"}),
            _daas_get(f"/events/{sym}", {"limit": limit}),
        )
        events = _shape_events(ann_resp, limit) or _shape_events(ev_resp, limit)
        mode = "ticker"
        ticker: Optional[str] = sym
    else:
        search_resp = await _daas_get("/intelligence/events/search", {"q": query, "limit": limit})
        events = _shape_events(search_resp, limit)
        mode = "thematic"
        ticker = None

    ok = bool(events)
    if ok:
        subject = ticker or "the market"
        summary = f"{len(events)} recent filings for {subject}"
    else:
        summary = f"No recent filings found for {ticker or 'that query'}"
    return StocksInsightsResult(
        ok=ok, summary=summary, ticker=ticker, mode=mode, events=events,
        error=None if ok else "no_filings",
    )


def build_widget_data(
    result: StocksInsightsResult,
    answer: str,
    company: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure: assemble the ``stock_insights`` widget payload the chat card renders.

    ``sources`` is the numbered filing register [1..N] the answer's [n] markers
    resolve to (filing-level "View Source"). Always includes the AI disclaimer.
    """
    sources: List[Dict[str, Any]] = []
    for i, e in enumerate(result.events, start=1):
        sources.append({
            "n": i,
            "title": e.get("headline") or f"Filing {i}",
            "category": e.get("category") or "other",
            "filed_at": e.get("filed_at"),
            "url": e.get("url"),
            "symbol": e.get("symbol") or result.ticker,
        })
    return {
        "ticker": result.ticker,
        "company": company or result.ticker,
        "mode": result.mode,
        "answer": answer,
        "events": result.events,
        "sources": sources,
        "disclaimer": DISCLAIMER,
        "empty": not result.ok,
    }
