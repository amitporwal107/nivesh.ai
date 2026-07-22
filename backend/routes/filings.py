"""Filings Home — Design B's home screen API (docs/FILINGS_HOME_SPEC.md §3).

Read endpoints over the classified corporate-filings feed:

  GET /api/filings/feed                     — the feed + facets + pagination
  GET /api/filings/signals                  — today's top-3 impact-ordered filings
  GET /api/filings/{announcement_id}/insights — the generated insight for one filing

The feed/signals WRAP the articles query in routes/markets.py rather than
re-deriving the SQL (a second copy of that query already caused a shipped bug this
session). The generated insight (one-liner / period / headline metric) is fetched
SEPARATELY from the stage-7 filing_insights output and merged in — deliberately
NOT joined into that load-bearing articles query. `one`/`period`/`metric`/
`hasInsights` are null/false for any filing the generator has not processed yet;
the row still renders (honest degradation — spec §4.2).

Honesty constraints enforced here (spec §4, measured):
  * days capped at 30 (the classifier's queue floor).
  * one/period/metric come ONLY from a generated insight, never fabricated from
    the exchange boilerplate; metric is null unless the filing stated a number.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from datetime import datetime, timezone

from deps import db, get_current_user

# Reuse the single, verified articles implementation + the DaaS-first helper and
# the app-PG insight fallback (see module docstring).
from routes.markets import _aux_cached, _daas_first, _articles, _filing_insights_pg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/filings", tags=["filings"])

# The classifier's queue floor. Not a UI preference — see spec §4.1.
_MAX_DAYS = 30
_SORTS = ("material", "latest")

# ── Alerts preferences ────────────────────────────────────────────────────
# The filing types the Alerts screen offers. Keys are the REAL
# nidp.documents.doc_type values the pipeline produces, so a stored preference
# can be matched against a filing without a translation table. Labels are the
# design's wording.
_ALERT_TYPES: Dict[str, str] = {
    "concall_transcript":    "Earnings transcripts",
    "annual_report":         "Annual reports",
    "investor_presentation": "Investor presentations",
    "financial_results":     "Quarterly results",
}
_ALERT_CHANNELS = ("email", "whatsapp")

# Defaults for a user who has never opened the screen (matches the design's
# initial state: all types on, email on, WhatsApp off).
_DEFAULT_ALERTS: Dict[str, Any] = {
    "types": {k: True for k in _ALERT_TYPES},
    "channels": {"email": True, "whatsapp": False},
}

# ⚠️ Delivery is NOT implemented. This endpoint persists a user's stated
# preference; no worker reads it and nothing is sent. There is no WhatsApp
# provider in this repo (only wa.me deeplinks) and nidp.shared.notify is
# ops-only SMTP to a fixed address. The flag is returned so the UI can say so
# plainly instead of implying alerts fire — flipping it on is a lie until a
# sender exists.
_DELIVERY_ACTIVE = False


async def _feed(days: int, category: Optional[str], impact: Optional[str],
                sentiment: Optional[str], q: Optional[str],
                limit: int, offset: int, sort: str,
                symbol: Optional[str] = None) -> Dict[str, Any]:
    """Fetch the articles payload (DaaS primary, app PG fallback).

    `symbol` scopes the feed AND its facets to one company (exact ticker), which
    is what selecting a type-ahead suggestion does. `q` stays a fuzzy free-text
    match for the case where the user just types.
    """
    key = f"filings:feed:{days}:{category}:{impact}:{sentiment}:{q}:{limit}:{offset}:{sort}:{symbol}"
    return await _aux_cached(key, lambda: _daas_first(
        "get_market_pulse_articles",
        {"days": days, "category": category, "impact": impact, "sentiment": sentiment,
         "q": q, "limit": limit, "offset": offset, "sort": sort, "symbol": symbol},
        lambda pool: _articles(pool, days, category, impact, sentiment, q, limit, offset,
                               sort, symbol),
        {"articles": [], "total": 0, "categories": {}},
    ))


async def _insights_for(ids: List[str]) -> Dict[str, Any]:
    """Batch-fetch generated insights for a set of announcement ids (DaaS primary,
    app PG fallback). Returns {id: insight-dict}; a missing id means "no insight
    yet". Never raises — insights are additive, so a lookup failure just degrades
    the feed to filing rows without a one-liner."""
    ids = [i for i in (ids or []) if i]
    if not ids:
        return {}
    data = await _daas_first(
        "get_filing_insights", {"ids": ids},
        lambda pool: _filing_insights_pg(pool, ids),
        {"insights": {}},
    )
    return (data or {}).get("insights") or {}


# Placeholder strings a model returns instead of a real JSON null. The generator
# now normalises these at write time, but ~66% of the insights already stored on
# staging predate that fix (measured 2026-07-19: 79/120 rows had period == "null",
# and units of "null" were being concatenated onto the metric). Normalising on
# READ as well means those rows display honestly without a full regeneration.
_NULLISH = {"null", "none", "nan", "n/a", "na", "nil", "not disclosed", "undisclosed",
            "not specified", "not applicable", "not available", "unknown", "-", "--", ""}


def _nullish(v: Any) -> bool:
    return v is None or str(v).strip().lower() in _NULLISH


def _clean(v: Any) -> Optional[str]:
    """A stored text field, or None when it is a placeholder rather than a value."""
    return None if _nullish(v) else str(v).strip()


def _fmt_metric(m: Optional[Dict[str, Any]]) -> Optional[str]:
    """Format a headline metric {label,value,unit} for display, or None.

    A metric without a label or value is absent, not partial. A placeholder UNIT
    is dropped rather than sinking the metric — otherwise a real figure renders
    as "PAT: 8.4 null".
    """
    if not m:
        return None
    label, value = _clean(m.get("label")), _clean(m.get("value"))
    if not (label and value):
        return None
    unit = _clean(m.get("unit")) or ""
    return f"{label}: {value} {unit}".strip()


def _row(a: Dict[str, Any], ins: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One feed row. `one`/`period`/`metric`/`hasInsights` come from a generated
    insight when one exists (else null/false — the honest step-3 seam)."""
    ins = ins or {}
    return {
        "id":         a.get("id"),
        "ticker":     a.get("symbol"),
        "code":       a.get("symbol"),   # spec §5 Q2 → the NSE symbol/ticker
        "name":       a.get("company"),
        "date":       a.get("when"),
        "category":   a.get("category"),
        "impact":     a.get("impact"),
        "sentiment":  a.get("sentiment"),
        # The exchange's own label for the document ("Press Release", "Investor
        # Presentation"). NOT a summary — see the honesty note above.
        "docLabel":   a.get("title"),
        "url":        a.get("url"),
        "one":        _clean(ins.get("one")),
        "period":     _clean(ins.get("period")),
        "metric":     _fmt_metric(ins.get("metric")),
        "hasInsights": bool(ins),
    }


def _clamp_common(days: Any, limit: Any, offset: Any, sort: Any):
    sort = (sort or "material").lower()
    if sort not in _SORTS:
        # 400, not a silent fallback: a caller that asked for an ordering and
        # quietly got a different one would mis-rank the feed.
        raise HTTPException(status_code=400, detail="sort must be 'material' or 'latest'")
    days = max(1, min(int(days or 7), _MAX_DAYS))
    limit = max(1, min(int(limit or 60), 120))
    offset = max(0, int(offset or 0))
    return days, limit, offset, sort


@router.get("/feed")
async def filings_feed(
    request: Request,
    days: int = 7,
    category: Optional[str] = None,
    impact: Optional[str] = None,
    sentiment: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 60,
    offset: int = 0,
    sort: str = "material",
    symbol: Optional[str] = None,
):
    """The Filings Home feed (spec §3.1).

    `total` is the full count for the same predicate (NOT len(rows)), so the
    client can paginate. `facets` are the per-category counts for that predicate.
    """
    await get_current_user(request)
    days, limit, offset, sort = _clamp_common(days, limit, offset, sort)
    category = category.lower() if category else None
    impact = impact.lower() if impact else None
    sentiment = sentiment.lower() if sentiment else None

    data = await _feed(days, category, impact, sentiment, q, limit, offset, sort,
                       (symbol or "").strip().upper() or None)
    articles = data.get("articles") or []
    ins_map = await _insights_for([a.get("id") for a in articles])
    return {
        "ok": True,
        "total": int(data.get("total") or 0),
        "facets": data.get("categories") or {},
        "rows": [_row(a, ins_map.get(a.get("id"))) for a in articles],
    }


@router.get("/signals")
async def filings_signals(request: Request, days: int = 1, today_only: bool = True):
    """Today's top-3 material filings (spec §3.2).

    `rank` is the DISPLAY POSITION in the impact-ordered list (1,2,3) — it is
    explicitly NOT a computed materiality score (user decision). Copy that
    surfaces this must not imply a model we do not have.

    `one`/`metric` come from the generated insight when present, else null.
    """
    await get_current_user(request)
    days = max(1, min(int(days or 1), _MAX_DAYS))

    # Impact-ordered feed for a short window, then keep STRICTLY today's (IST) filings —
    # "today's read" must be honestly today's corporate events (empty early in the day is
    # expected; the UI says so). `today_only=false` falls back to the rolling window.
    data = await _feed(max(days, 2), None, None, None, None, 12, 0, "material")
    articles = data.get("articles") or []
    from datetime import timedelta
    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date().isoformat()
    if today_only:
        articles = [a for a in articles if str(a.get("when") or "")[:10] == today]
    articles = articles[:3]
    ins_map = await _insights_for([a.get("id") for a in articles])
    signals: List[Dict[str, Any]] = []
    for i, a in enumerate(articles, start=1):
        ins = ins_map.get(a.get("id")) or {}
        signals.append({
            "rank":      i,
            "id":        a.get("id"),
            "ticker":    a.get("symbol"),
            "company":   a.get("company"),
            "type":      a.get("category"),
            "one":       _clean(ins.get("one")),
            "metric":    _fmt_metric(ins.get("metric")),
            "date":      a.get("when"),
            "sentiment": a.get("sentiment"),
        })
    return {"ok": True, "signals": signals, "today": today, "today_only": today_only}


# The document types the UI offers as downloads, in the order the design lists
# them. Anything else the pipeline stored still appears, after these.
_DOC_LABELS: Dict[str, str] = {
    "concall_transcript":    "Earnings transcripts",
    "investor_presentation": "Investor presentations",
    "financial_results":     "Quarterly results",
    "annual_report":         "Annual reports",
    "press_release":         "Press releases",
}


async def _companies_pg(pool, q: str, limit: int) -> Dict[str, Any]:
    """App-PG fallback for symbol type-ahead."""
    like = f"%{q.strip().upper()}%"
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (ticker_symbol) ticker_symbol AS symbol, company_name
                  FROM nidp.corporate_announcements
                 WHERE ticker_symbol IS NOT NULL
                   AND (UPPER(ticker_symbol) LIKE $1 OR UPPER(company_name) LIKE $1)
                 ORDER BY ticker_symbol
                 LIMIT $2
                """,
                like, limit,
            )
    except Exception as e:  # noqa: BLE001 — type-ahead must never 500 the screen
        logger.warning("company search fallback failed: %s", e)
        return {"data": []}
    return {"data": [dict(r) for r in rows]}


async def _documents_by_symbol_pg(pool, sym: str, limit: int) -> Dict[str, Any]:
    """App-PG fallback for the company document library."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT doc_id, doc_type, company_name, ticker_symbol, filed_at,
                       source_url, page_count, parse_status, raw_size_bytes
                  FROM nidp.documents
                 WHERE UPPER(ticker_symbol) = $1 AND source_url IS NOT NULL
                 ORDER BY filed_at DESC NULLS LAST
                 LIMIT $2
                """,
                sym, limit,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("company documents fallback failed: %s", e)
        return {"data": []}
    return {"data": [dict(r) for r in rows]}


@router.get("/companies/search")
async def companies_search(request: Request, q: str = "", limit: int = 8):
    """Type-ahead over companies (design: the header search suggests as you type).

    A query shorter than 2 chars returns an empty list rather than the whole
    master — a blank dropdown is the right answer to "no input", not 20
    arbitrary tickers.
    """
    await get_current_user(request)
    q = (q or "").strip()
    limit = max(1, min(int(limit or 8), 25))
    if len(q) < 2:
        return {"ok": True, "companies": []}

    data = await _daas_first(
        "search_symbols", {"q": q, "limit": limit},
        lambda pool: _companies_pg(pool, q, limit),
        {"data": []},
    )
    seen, out = set(), []
    for r in (data or {}).get("data") or []:
        s = (r.get("symbol") or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append({"symbol": s,
                    "name": r.get("company_name") or s,
                    "sector": r.get("sector")})
    return {"ok": True, "companies": out[:limit]}


@router.get("/companies/{symbol}/documents")
async def company_documents(request: Request, symbol: str, limit: int = 200):
    """A company's source documents, grouped by type, for download.

    Every entry links to the document AS FILED with the exchange — we do not
    re-host PDFs. `parsed` says whether Nivesh actually read it, so the UI can
    distinguish "we analysed this" from "here is the filing".
    """
    await get_current_user(request)
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")
    limit = max(1, min(int(limit or 200), 500))

    data = await _daas_first(
        "documents_by_symbol", {"symbol": sym, "limit": limit},
        lambda pool: _documents_by_symbol_pg(pool, sym, limit),
        {"data": []},
    )
    rows = (data or {}).get("data") or []

    groups: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        dt = r.get("doc_type") or "other"
        g = groups.setdefault(dt, {"key": dt,
                                   "label": _DOC_LABELS.get(dt, dt.replace("_", " ").title()),
                                   "documents": []})
        filed = r.get("filed_at")
        g["documents"].append({
            "docId":   str(r.get("doc_id")) if r.get("doc_id") else None,
            "url":     r.get("source_url"),
            "filedAt": filed.isoformat() if hasattr(filed, "isoformat") else filed,
            "pages":   r.get("page_count"),
            "bytes":   r.get("raw_size_bytes"),
            "parsed":  (r.get("parse_status") == "parsed"),
        })

    # Design order first, then anything else — so the named types always lead and
    # a new pipeline doc_type still surfaces instead of being dropped.
    order = list(_DOC_LABELS)
    ordered = sorted(groups.values(),
                     key=lambda g: (order.index(g["key"]) if g["key"] in order else len(order),
                                    g["label"]))
    name = next((r.get("company_name") for r in rows if r.get("company_name")), None)
    return {"ok": True, "symbol": sym, "name": name or sym,
            "total": len(rows), "groups": ordered}


def _alerts_payload(prefs: Dict[str, Any]) -> Dict[str, Any]:
    """Merge stored prefs over the defaults and attach the catalogue the screen
    renders, so the client never hardcodes the filing-type list."""
    stored = prefs or {}
    types = {**_DEFAULT_ALERTS["types"], **(stored.get("types") or {})}
    channels = {**_DEFAULT_ALERTS["channels"], **(stored.get("channels") or {})}
    return {
        "ok": True,
        "types": {k: bool(types.get(k)) for k in _ALERT_TYPES},
        "channels": {c: bool(channels.get(c)) for c in _ALERT_CHANNELS},
        "catalog": [{"key": k, "label": v} for k, v in _ALERT_TYPES.items()],
        "delivery": {
            "active": _DELIVERY_ACTIVE,
            "note": ("Preferences are saved. Scheduled delivery is not switched on yet — "
                     "nothing is sent to you today."),
        },
        "updatedAt": stored.get("updated_at"),
    }


@router.get("/alerts")
async def get_filing_alerts(request: Request):
    """The user's filing-alert preferences (design: Alerts screen).

    Returns documented defaults for a user who has never saved any — never 404,
    so the screen has something honest to render on first open.
    """
    user = await get_current_user(request)
    profile = await db.user_profiles.find_one(
        {"user_id": user["user_id"]}, {"_id": 0, "preferences": 1}
    ) or {}
    return _alerts_payload((profile.get("preferences") or {}).get("filing_alerts") or {})


@router.put("/alerts")
async def put_filing_alerts(request: Request):
    """Replace the user's filing-alert preferences.

    Validates the whole body BEFORE writing: an unknown filing type or channel is
    a 400 with nothing persisted, rather than a partial save that silently drops
    the key the user actually toggled.
    """
    user = await get_current_user(request)
    body = await request.json() or {}

    types_in = body.get("types")
    channels_in = body.get("channels")
    if types_in is not None and not isinstance(types_in, dict):
        raise HTTPException(status_code=400, detail="types must be an object")
    if channels_in is not None and not isinstance(channels_in, dict):
        raise HTTPException(status_code=400, detail="channels must be an object")

    unknown_types = sorted(set(types_in or {}) - set(_ALERT_TYPES))
    if unknown_types:
        raise HTTPException(status_code=400,
                            detail=f"unknown filing type(s): {', '.join(unknown_types)}")
    unknown_channels = sorted(set(channels_in or {}) - set(_ALERT_CHANNELS))
    if unknown_channels:
        raise HTTPException(status_code=400,
                            detail=f"unknown channel(s): {', '.join(unknown_channels)}")

    merged = {
        "types": {k: bool((types_in or {}).get(k, _DEFAULT_ALERTS["types"][k]))
                  for k in _ALERT_TYPES},
        "channels": {c: bool((channels_in or {}).get(c, _DEFAULT_ALERTS["channels"][c]))
                     for c in _ALERT_CHANNELS},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.user_profiles.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"preferences.filing_alerts": merged},
         "$setOnInsert": {"user_id": user["user_id"]}},
        upsert=True,
    )
    return _alerts_payload(merged)


def _cite_label(sec: Dict[str, Any], doc_type: Optional[str]) -> Optional[str]:
    """"[transcript · pp. 6-8]" — the design's citation chip. None when the
    generator could not point at a page (an unverifiable citation is dropped
    upstream, so absence here means "not cited", never "cited vaguely")."""
    start, end = sec.get("cite_page_start"), sec.get("cite_page_end")
    if not start:
        return None
    kind = (doc_type or "filing").replace("_", " ")
    kind = {"concall transcript": "transcript",
            "investor presentation": "presentation",
            "financial results": "results",
            "annual report": "annual report"}.get(kind, kind)
    pages = f"pp. {start}-{end}" if end and end != start else f"p. {start}"
    return f"[{kind} · {pages}]"


def _cite_url(source_url: Optional[str], sec: Dict[str, Any]) -> Optional[str]:
    """Deep-link straight to the cited page of the source PDF (same `#page=N`
    convention the copilot's commentary sources already use)."""
    start = sec.get("cite_page_start")
    if not (source_url and start):
        return source_url or None
    return f"{source_url}#page={start}"


import re as _held_re


@router.get("/portfolio-held")
async def portfolio_held(request: Request):
    """The current user's held companies as normalized match keys, so the research feed
    can badge 'In your portfolio'. Holdings carry a name + an ISIN (in `ticker`); we return
    normalized names + ISINs + any NSE symbols for client-side matching against filings."""
    user = await get_current_user(request)

    def _norm(x: Any) -> str:
        t = _held_re.sub(r"\b(limited|ltd|corporation|corp|company|co|pvt|private)\b", "", (x or "").lower())
        return _held_re.sub(r"[^a-z0-9]", "", t)

    names, isins, symbols = set(), set(), set()
    cur = db.holdings.find({"user_id": user["user_id"]},
                           {"_id": 0, "name": 1, "ticker": 1, "isin": 1, "nse_symbol": 1, "symbol": 1})
    async for h in cur:
        if h.get("name"):
            n = _norm(h["name"])
            if n:
                names.add(n)
        for k in ("ticker", "isin"):
            v = h.get(k)
            if isinstance(v, str) and v.upper().startswith("INE"):
                isins.add(v.upper())
        for k in ("nse_symbol", "symbol"):
            v = h.get(k)
            if v:
                symbols.add(str(v).upper())
    return {"ok": True, "names": sorted(names), "isins": sorted(isins), "symbols": sorted(symbols)}


@router.get("/{announcement_id}/insights")
async def filing_insight_detail(request: Request, announcement_id: str):
    """The generated insight for one filing (spec §3.3).

    Returns the one-liner, reporting period and headline metric, PLUS the
    expanded panel: `tabs[]` (doc-type aware — an annual report gets Business
    Overview / MD & A / Financial Statements / Accounting Notes, everything else
    Quick Summary / Sentiment / Business Outlook / Potential Risks) and
    `sections[]` grouped under those tabs with real `pp. N-M` citations into the
    source PDF.

    Honest 404 when no insight has been generated yet — an empty panel, not
    fabricated content. A tab the document could not support is simply absent
    rather than padded (see the generator's section rules).
    """
    await get_current_user(request)
    ins_map = await _insights_for([announcement_id])
    ins = ins_map.get(announcement_id)
    if not ins:
        return JSONResponse(status_code=404,
                            content={"ok": False, "reason": "no_insight_yet"})

    doc_type = ins.get("docType")
    source_url = ins.get("sourceUrl")
    raw_sections = ins.get("sections") or []

    sections = [{
        "tab":      s.get("tab"),
        "h":        s.get("h"),
        "items":    s.get("items") or [],
        "cite":     _cite_label(s, doc_type),
        "cite_url": _cite_url(source_url, s),
    } for s in raw_sections if s.get("tab") and s.get("items")]

    # Only tabs that actually carry a section — the panel never shows an empty
    # tab the user can click into and find nothing behind.
    seen: List[str] = []
    for s in sections:
        if s["tab"] not in seen:
            seen.append(s["tab"])
    tabs = [{"key": t.lower().replace(" ", "_"), "label": t} for t in seen]

    return {
        "ok": True,
        "id": announcement_id,
        "one": _clean(ins.get("one")),
        "period": _clean(ins.get("period")),
        "metric": _fmt_metric(ins.get("metric")),
        "metricRaw": ins.get("metric"),
        "sentiment": ins.get("sentiment"),
        "confidence": ins.get("confidence"),
        "docType": doc_type,
        "docLabel": (doc_type or "").replace("_", " ").title() or None,
        "model": ins.get("model"),
        "generatedAt": ins.get("generatedAt"),
        "tabs": tabs,
        "sections": sections,
        "sourceUrl": source_url,
        "grounded": True,
        "disclaimer": "AI-generated summary · refer to the source document for complete detail.",
    }
