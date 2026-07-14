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
_FILED_KEYS = ("filed_at", "filed_date", "as_of", "date", "event_date", "published_at", "when")
_URL_KEYS = ("url", "attachment_url", "source_url", "pdf_url", "filing_url", "link")
_SYMBOL_KEYS = ("symbol", "nse_symbol", "ticker", "security_symbol")
_ID_KEYS = ("announcement_id", "event_id", "id")
_SUMMARY_KEYS = ("summary", "description", "body", "ai_summary", "excerpt")


@dataclass
class StocksInsightsResult:
    ok: bool
    summary: str                                    # ≤300-char LLM context line
    ticker: Optional[str] = None
    mode: str = "ticker"                            # "ticker" | "thematic"
    events: List[Dict[str, Any]] = field(default_factory=list)
    financials: Optional[str] = None                # compact quarterly P&L context (ticker mode)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        """Numbered filings (with summaries) + optional quarterly financials for the
        LLM to ground on. Filings are cited [n]; financials are stated plainly."""
        parts: List[str] = []
        if self.events:
            lines = ["recent_filings (cite as [n]):"]
            for i, e in enumerate(self.events, start=1):
                filed = (e.get("filed_at") or "")[:10]
                line = (f"  [{i}] {filed} [{e.get('category') or 'other'}] "
                        f"{(e.get('headline') or '')[:120]}")
                if e.get("summary"):
                    line += f" — {str(e['summary'])[:200]}"
                if e.get("impact"):
                    line += f" (impact={e['impact']})"
                lines.append(line)
            parts.append("\n".join(lines))
        else:
            parts.append("recent_filings: NONE FOUND")
        if self.financials:
            parts.append("quarterly_financials (state plainly; no [n] needed):\n  " + str(self.financials)[:700])
        return "\n\n".join(parts)


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
        "summary": _first(row, _SUMMARY_KEYS),
    }


def _shape_events(rows: Any, limit: int = 8) -> List[Dict[str, Any]]:
    """Pure: normalise a DAAS list/response into a bounded list of card events.

    Accepts either a bare list or a {rows|announcements|events|results|items:[…]}
    envelope (DAAS is inconsistent across endpoints). Drops rows with no headline.
    """
    if isinstance(rows, dict):
        rows = (rows.get("rows") or rows.get("announcements") or rows.get("events")
                or rows.get("results") or rows.get("items") or rows.get("data")
                or rows.get("hits") or rows.get("articles") or [])
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


async def _fetch_filings(q: str, limit: int, *, ticker: bool) -> List[Dict[str, Any]]:
    """Recent corporate filings for the query.

    ticker mode → the announcements endpoint by symbol (ALL recent filings incl.
    routine 'other' ones — the right view of a company's own disclosures). thematic
    mode → the market-pulse articles feed by free-text (curated, categorized, with
    summaries; it intentionally hides routine 'other'/'regulatory' noise). Both fall
    back to the intelligence events-search. Every hop degrades gracefully to []."""
    events: List[Dict[str, Any]] = []
    if ticker:
        try:
            events = _shape_events(await daas_client._get(
                "/announcements", {"symbol": q, "limit": limit, "sort": "filed_at"}), limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("announcements fetch failed for %s: %s", q, exc)
    if not events:  # curated articles by free-text (primary for thematic; ticker fallback)
        try:
            events = _shape_events(await daas_client.get_market_pulse_articles(
                days=30, q=q, limit=limit), limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("articles fetch failed for %r: %s", q, exc)
    if not events:  # last resort — intelligence events search
        try:
            events = _shape_events(await daas_client._get(
                "/intelligence/events/search", {"q": q, "limit": limit}), limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("events/search fallback failed for %r: %s", q, exc)
    return events


async def _fetch_financials(sym: str) -> Optional[str]:
    """Compact quarterly P&L context so ticker answers can address results / numbers
    (revenue, PAT, margins, YoY) — DaaS /v1/financials via the shared tool."""
    try:
        from . import company_financials
        res = await company_financials.get_company_financials(sym, limit=6)
        return res.summary if getattr(res, "ok", False) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("financials fetch failed for %s: %s", sym, exc)
        return None


async def get_stocks_insights(
    query: str,
    symbol: Optional[str] = None,
    limit: int = 8,
) -> StocksInsightsResult:
    """Fetch company disclosures for the query.

    ticker mode → recent classified filings (articles) + quarterly financials.
    thematic mode → classified filings matching the free-text query across companies.
    """
    if not daas_client.is_configured():
        return StocksInsightsResult(
            ok=False, summary="DAAS not configured", error="DAAS credentials missing",
        )

    financials: Optional[str] = None
    if symbol:
        sym = symbol.upper()
        events, financials = await asyncio.gather(
            _fetch_filings(sym, limit, ticker=True),
            _fetch_financials(sym),
        )
        mode = "ticker"
        ticker: Optional[str] = sym
    else:
        events = await _fetch_filings(query, limit, ticker=False)
        mode = "thematic"
        ticker = None

    ok = bool(events) or bool(financials)
    subject = ticker or "that query"
    if events and financials:
        summary = f"{len(events)} recent filings + quarterly financials for {subject}"
    elif events:
        summary = f"{len(events)} recent filings for {subject}"
    elif financials:
        summary = f"Quarterly financials for {subject} (no recent filings)"
    else:
        summary = f"No recent filings or financials found for {subject}"
    return StocksInsightsResult(
        ok=ok, summary=summary, ticker=ticker, mode=mode, events=events,
        financials=financials, error=None if ok else "no_filings",
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
