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
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import daas_client

logger = logging.getLogger(__name__)

DISCLAIMER = "AI-generated from exchange filings. Verify against the original filing."

# Fields we defensively read from a DAAS announcement/event row (shapes vary a
# little across /v1/announcements, /v1/events, /v1/intelligence/events/search).
_HEADLINE_KEYS = ("headline", "subject", "title", "summary", "description")
_CATEGORY_KEYS = ("category", "event_category", "event_type", "type")
# The exchange's OWN filing category (BSE CATEGORYNAME / NSE subject) — Phase-1
# taxonomy, distinct from the AI-derived event_category (Phase-2). Surfaced so the
# card can offer the "Exchange Categories" filter (AGM/EGM, Board Meeting, …).
_EXCHANGE_CATEGORY_KEYS = ("raw_category", "exchange_category", "strcat", "categoryname")
_IMPACT_KEYS = ("ai_impact", "impact", "materiality")
_FILED_KEYS = ("filed_at", "filed_date", "as_of", "date", "event_date", "published_at", "when")
_URL_KEYS = ("url", "attachment_url", "source_url", "pdf_url", "filing_url", "link")
_SYMBOL_KEYS = ("symbol", "nse_symbol", "ticker", "security_symbol")
_ID_KEYS = ("announcement_id", "event_id", "id")
_COMPANY_KEYS = ("company", "company_name", "name")
_SUMMARY_KEYS = ("summary", "description", "body", "ai_summary", "excerpt")

# Canonical Phase-1 exchange categories (mirror the BSE/NSE filter list users see).
# We normalise the messy raw_category + headline into ONE of these buckets so the
# same taxonomy works across both exchanges (BSE gives clean CATEGORYNAMEs; NSE's
# raw_category is often the industry, so we also sniff the headline text).
_EXCHANGE_CATEGORY_RULES = (
    ("agm_egm",        ("agm", "egm", "annual general meeting", "extraordinary general")),
    ("board_meeting",  ("board meeting",)),
    ("result",         ("result", "financial result", "quarterly result", "unaudited", "audited financ")),
    ("insider_sast",   ("insider", "sast", "pledge", "reg. 7", "reg 7", "acquisition of shares", "disclosure under")),
    ("integrated",     ("integrated filing", "integrated governance", "integrated_filing")),
    ("listing",        ("new listing", "listing of", "commencement of trading", "further issue")),
    ("corp_action",    ("corp. action", "corporate action", "dividend", "bonus", "stock split",
                        "sub-division", "buyback", "buy back", "rights issue", "record date", "scheme of arrangement")),
    ("company_update", ("company update", "comp. update", "press release", "clarification",
                        "intimation", "investor presentation", "analyst", "media release", "update")),
)
_EXCHANGE_CATEGORY_LABELS = {
    "agm_egm": "AGM/EGM", "board_meeting": "Board Meeting", "result": "Result",
    "insider_sast": "Insider/SAST", "integrated": "Integrated", "listing": "Listing",
    "corp_action": "Corp Action", "company_update": "Company Update", "others": "Others",
}


def _normalize_exchange_category(raw: Any, headline: str = "") -> str:
    """Map a raw BSE/NSE category (+ headline fallback) to one Phase-1 bucket."""
    hay = f"{raw or ''} {headline or ''}".lower()
    if not hay.strip():
        return "others"
    for bucket, needles in _EXCHANGE_CATEGORY_RULES:
        if any(n in hay for n in needles):
            return bucket
    return "others"


@dataclass
class StocksInsightsResult:
    ok: bool
    summary: str                                    # ≤300-char LLM context line
    ticker: Optional[str] = None
    mode: str = "ticker"                            # "ticker" | "thematic"
    events: List[Dict[str, Any]] = field(default_factory=list)
    financials: Optional[str] = None                # compact quarterly P&L context (ticker mode)
    commentary: List[Dict[str, Any]] = field(default_factory=list)  # concall/presentation chunks
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        """Numbered filings + management commentary passages (concall/presentation
        text) + optional quarterly financials. Filings and commentary share ONE [n]
        numbering (MUST match build_widget_data's Sources register — including the
        commentary-first ordering below). Financials stated plainly."""
        parts: List[str] = []
        self._n = 0

        def _events_block() -> None:
            if self.events:
                lines = ["recent_filings (cite as [n]):"]
                for e in self.events:
                    self._n += 1
                    # DAAS field types vary across endpoints (the thematic
                    # market-pulse / events-search feed can return filed_at as a
                    # numeric epoch rather than an ISO string). str()-coerce
                    # before slicing so a non-string value can never raise
                    # TypeError and abort the whole answer.
                    filed = str(e.get("filed_at") or "")[:10]
                    # Name the company on every line: the exchange's subject alone
                    # ("Awarding of order(s)/contract(s)") says nothing about who filed.
                    who = " ".join(x for x in (str(e.get("company") or "").strip(),
                                               f"({e['symbol']})" if e.get("symbol") else "") if x)
                    line = (f"  [{self._n}] {filed} [{e.get('category') or 'other'}] "
                            f"{who + ' — ' if who else ''}{str(e.get('headline') or '')[:120]}")
                    if e.get("impact"):
                        line += f" (impact {e['impact']})"
                    # The corporate-event AI insight says what happened, with the amount and
                    # the counterparty; the exchange summary is boilerplate, so it is the fallback.
                    if e.get("insight"):
                        line += f" — {str(e['insight'])[:300]}"
                        if e.get("metric"):
                            line += f" [{e['metric']}]"
                    elif e.get("summary"):
                        line += f" — {str(e['summary'])[:200]}"
                    lines.append(line)
                parts.append("\n".join(lines))
            elif not self.commentary:
                parts.append("recent_filings: NONE FOUND")

        def _commentary_block() -> None:
            if self.commentary:
                lines = ["management_commentary — ACTUAL transcript/presentation text. Quote it, "
                         "attribute to management, and cite [n]:"]
                for c in self.commentary:
                    self._n += 1
                    # Same str()-coercion discipline as the events block — never
                    # let an unexpected non-string DAAS value abort the answer.
                    label = str(c.get("company") or "").strip()
                    dt = str(c.get("doc_type") or "document").replace("_", " ")
                    pg = f", p.{c['page']}" if c.get("page") else ""
                    lines.append(f"  [{self._n}] ({label} {dt}{pg}) \"{str(c.get('text') or '')[:320]}\"")
                parts.append("\n".join(lines))

        # Thematic "who said/flagged X" → lead with commentary (it IS the answer;
        # announcements are supporting context). Ticker mode → the company's filings
        # lead. build_widget_data uses this same condition so [n] markers align.
        if _commentary_leads(self.mode, self.commentary):
            _commentary_block()
            _events_block()
        else:
            _events_block()
            _commentary_block()
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
    headline = _first(row, _HEADLINE_KEYS, "")
    exch = _normalize_exchange_category(_first(row, _EXCHANGE_CATEGORY_KEYS), headline)
    return {
        "id": _first(row, _ID_KEYS),
        "symbol": _first(row, _SYMBOL_KEYS),
        "company": _first(row, _COMPANY_KEYS),
        "category": str(cat).lower().replace(" ", "_") if cat else "other",  # AI event_category (Phase 2)
        "exchange_category": exch,                                            # BSE/NSE native (Phase 1)
        "exchange_category_label": _EXCHANGE_CATEGORY_LABELS.get(exch, "Others"),
        "headline": headline,
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


# A cross-company question about a KIND OF EVENT ("order wins in the last 14 days") is answered
# from the filings table's own event_category, not by matching the whole question as text. The
# codes are nidp.corporate_announcements.event_category; the phrases are how people ask.
_THEME_CATEGORIES = (
    ("orders", ("order win", "orders won", "order inflow", "new order", "order book", "contract win",
                "contracts won", "bagged", "letter of award", "letter of acceptance")),
    ("buyback", ("buyback", "buy back", "buy-back")),
    ("mna", ("acquisition", "acquire", "merger", "demerger", "m&a", "stake sale", "stake purchase",
             "takeover", "open offer")),
    ("qip", ("qip", "fund raise", "fund raising", "fundraise", "fund-raise", "preferential issue",
             "preferential allotment", "rights issue", "raised money", "raising money", "raised capital")),
    ("capex", ("capex", "capacity expansion", "capacity addition", "new plant", "new-plant",
               "commercial production", "commissioned")),
    ("rating", ("credit rating", "rating upgrade", "rating downgrade", "rating action")),
    ("litigation", ("litigation", "penalty", "penalties", "insolvency", "nclt", "court order",
                    "regulatory order")),
    ("management", ("resignation", "resigned", "management change", "ceo change", "cfo change",
                    "new ceo", "new cfo")),
    ("dividend", ("dividend", "bonus issue", "stock split")),
    ("earnings", ("quarterly results", "financial results", "results announced", "reported results")),
)
_THEME_LIMIT = 15           # enough filings to rank; the thematic default of 8 is too few
_MAX_WINDOW_DAYS = 30       # the market-pulse feed's ceiling
_WINDOW_RE = re.compile(r"(?:last|past|previous)\s+(\d{1,3})\s*(day|week|month)s?")
_WINDOW_WORDS = (("fortnight", 14), ("today", 1), ("yesterday", 2), ("this week", 7), ("last week", 7),
                 ("past week", 7), ("this month", 30), ("last month", 30), ("past month", 30))


# "won their largest-ever order", "first international orders", "biggest order wins": the verb and
# the noun can sit either side of each other, so order questions are matched by pattern too.
_ORDER_RE = re.compile(
    r"\b(?:win|wins|won|winning|bag|bags|bagged|secure[ds]?|award(?:ed|s)?|receive[ds]?|largest|biggest|first)\b"
    r"[^.?!]{0,40}\b(?:orders?|contracts?)\b"
    r"|\b(?:orders?|contracts?)\b[^.?!]{0,20}\b(?:win|wins|won|bagged|secured|awarded|received)\b")


def _theme_category(text: str) -> Optional[str]:
    """The event category a cross-company question is about, or None."""
    t = (text or "").lower()
    if _ORDER_RE.search(t):
        return "orders"
    for category, phrases in _THEME_CATEGORIES:
        if any(p in t for p in phrases):
            return category
    return None


def _window_days(text: str, default: int = _MAX_WINDOW_DAYS) -> int:
    """How far back the question looks, in days, capped at the feed's maximum."""
    t = (text or "").lower()
    m = _WINDOW_RE.search(t)
    if m:
        days = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
        return max(1, min(days, _MAX_WINDOW_DAYS))
    for words, days in _WINDOW_WORDS:
        if words in t:
            return days
    return default


async def _event_ai_lookup(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    from deps import db
    from services.event_ai_insight import insights_for
    return await insights_for(db, ids)


async def _attach_insights(events: List[Dict[str, Any]], lookup=None) -> List[Dict[str, Any]]:
    """Add the corporate-event AI insight (Mongo event_ai_analysis) to each filing that has one:
    `insight` is the one-line reading, `metric` its headline figure. Additive — a failed lookup
    leaves the filings exactly as they were."""
    ids = [str(e["id"]) for e in events if e.get("id")]
    if not ids:
        return events
    try:
        found = await (lookup or _event_ai_lookup)(ids)
    except Exception as exc:  # noqa: BLE001 — never break the answer over an enrichment
        logger.warning("event AI insight lookup failed: %s", exc)
        return events
    for e in events:
        ins = found.get(str(e.get("id"))) if e.get("id") else None
        if not ins or not ins.get("one"):
            continue
        e["insight"] = ins["one"]
        m = ins.get("metric")
        if isinstance(m, dict) and m.get("label") and m.get("value"):
            e["metric"] = f"{m['label']}: {m['value']} {m.get('unit') or ''}".strip()
    return events


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
    category = None if ticker else _theme_category(q)
    if category:  # an event question: that category, in the stated window, most material first
        n = max(limit, _THEME_LIMIT)
        try:
            events = _shape_events(await daas_client.get_market_pulse_articles(
                days=_window_days(q), category=category, sort="material", limit=n), n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("category fetch failed for %s: %s", category, exc)
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


def _shape_commentary(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a DAAS /documents/search chunk row into a quotable passage."""
    return {
        "text": (row.get("text") or "").strip(),
        "page": row.get("page_start"),
        "doc_type": row.get("doc_type"),
        "company": row.get("company_name") or row.get("ticker_symbol"),
        "symbol": row.get("ticker_symbol"),
        "filed_at": (str(row.get("filed_at"))[:10] if row.get("filed_at") else None),
        "url": row.get("source_url"),
    }


# Artifact scoping. By default a thematic ask searches ALL document types: a
# company's relevant commentary can live in its concall, presentation, annual report,
# results filing OR a mis-typed announcement attachment, and narrowing to one category
# silently drops companies (e.g. Heritage/Elecon flag margin pressure in their annual
# report, having no concall). We narrow ONLY when the user explicitly asks for a single
# artifact type. None -> search everything.
_ARTIFACT_INTENT = [
    (re.compile(r"only (?:in|the).{0,20}annual report|integrated report", re.I),
     "annual_report"),
    (re.compile(r"only (?:in|the).{0,20}presentation|investor deck\b", re.I),
     "investor_presentation"),
    (re.compile(r"only (?:in|the).{0,20}(?:concall|transcript)|in the transcript\b", re.I),
     "concall_transcript"),
]


def _classify_artifacts(query):
    """Free-text query -> doc_type set for /documents/search, or None for ALL types.
    Only an EXPLICIT single-artifact request narrows it; otherwise search everything."""
    for rx, types in _ARTIFACT_INTENT:
        if rx.search(query or ""):
            return types
    return None


def _commentary_leads(mode: Optional[str], commentary: List[Dict[str, Any]]) -> bool:
    """Thematic cross-company answers lead with management commentary (it IS the
    answer); ticker mode leads with the company's own filings. as_llm_context and
    build_widget_data BOTH call this so the [n] citation numbering stays aligned."""
    return mode == "thematic" and bool(commentary)


async def _fetch_commentary(q: str, symbol: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve management-commentary passages (concall transcripts / investor
    presentations / annual reports) matching the query — DAAS /v1/documents/search,
    scoped to the artifact category the query is about (see _classify_artifacts) so
    newspaper/regulatory attachments don't crowd out real commentary.
    Returns [] when the corpus has no match (or isn't populated yet)."""
    doc_types = _classify_artifacts(q)
    try:
        data = await daas_client.search_documents(q=q, symbol=symbol, doc_type=doc_types, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("commentary search failed for %r: %s", q, exc)
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [_shape_commentary(r) for r in rows if isinstance(r, dict) and r.get("text")][:limit]


async def _fetch_thematic_commentary(q: str, limit: int = 12) -> List[Dict[str, Any]]:
    """Cross-company 'who flagged X?' commentary via the LLM-curated DAAS endpoint —
    keeps only companies whose management genuinely flagged the theme. Falls back to []
    (caller still has the plain commentary search)."""
    try:
        data = await daas_client.thematic_commentary(q=q, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thematic commentary failed for %r: %s", q, exc)
        return []
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    return [_shape_commentary(r) for r in rows if isinstance(r, dict) and r.get("text")][:limit]


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
    commentary: List[Dict[str, Any]] = []
    if symbol:
        sym = symbol.upper()
        events, financials, commentary = await asyncio.gather(
            _fetch_filings(sym, limit, ticker=True),
            _fetch_financials(sym),
            _fetch_commentary(query, sym),
        )
        mode = "ticker"
        ticker: Optional[str] = sym
    else:
        events, commentary = await asyncio.gather(
            _fetch_filings(query, limit, ticker=False),
            _fetch_thematic_commentary(query, limit=12),  # LLM-curated cross-company commentary
        )
        mode = "thematic"
        ticker = None

    events = await _attach_insights(events)
    ok = bool(events) or bool(financials) or bool(commentary)
    subject = ticker or "that query"
    bits: List[str] = []
    if events:
        bits.append(f"{len(events)} filings")
    if commentary:
        bits.append(f"{len(commentary)} commentary passages")
    if financials:
        bits.append("quarterly financials")
    summary = (", ".join(bits) + f" for {subject}") if bits else f"No disclosures found for {subject}"
    return StocksInsightsResult(
        ok=ok, summary=summary, ticker=ticker, mode=mode, events=events,
        financials=financials, commentary=commentary, error=None if ok else "no_filings",
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
    # Filings and commentary share ONE continuous [n] numbering (MUST match
    # as_llm_context — including the commentary-first order for thematic answers).
    sources: List[Dict[str, Any]] = []
    n = 0

    def _add_events() -> None:
        nonlocal n
        for e in result.events:
            n += 1
            sources.append({
                "n": n,
                "title": e.get("headline") or f"Filing {n}",
                "category": e.get("category") or "other",
                "filed_at": e.get("filed_at"),
                "url": e.get("url"),
                "symbol": e.get("symbol") or result.ticker,
            })

    def _add_commentary() -> None:
        nonlocal n
        for c in result.commentary:
            n += 1
            url = c.get("url")
            if url and c.get("page"):
                url = f"{url}#page={c['page']}"
            dt = (c.get("doc_type") or "document").replace("_", " ")
            pg = f" · p.{c['page']}" if c.get("page") else ""
            sources.append({
                "n": n,
                "title": f"{c.get('company') or result.ticker or 'Document'} — {dt}{pg}",
                "category": c.get("doc_type") or "document",
                "filed_at": c.get("filed_at"),
                "url": url,
                "symbol": c.get("symbol") or result.ticker,
            })

    if _commentary_leads(getattr(result, "mode", None), result.commentary):
        _add_commentary()
        _add_events()
    else:
        _add_events()
        _add_commentary()
    return {
        "ticker": result.ticker,
        "company": company or result.ticker,
        "mode": result.mode,
        "answer": answer,
        "events": result.events,
        "sources": sources,
        "has_commentary": bool(result.commentary),
        "disclaimer": DISCLAIMER,
        "empty": not result.ok,
    }
