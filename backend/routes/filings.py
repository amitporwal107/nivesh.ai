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

from deps import get_current_user

# Reuse the single, verified articles implementation + the DaaS-first helper and
# the app-PG insight fallback (see module docstring).
from routes.markets import _aux_cached, _daas_first, _articles, _filing_insights_pg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/filings", tags=["filings"])

# The classifier's queue floor. Not a UI preference — see spec §4.1.
_MAX_DAYS = 30
_SORTS = ("material", "latest")


async def _feed(days: int, category: Optional[str], impact: Optional[str],
                sentiment: Optional[str], q: Optional[str],
                limit: int, offset: int, sort: str) -> Dict[str, Any]:
    """Fetch the articles payload (DaaS primary, app PG fallback)."""
    key = f"filings:feed:{days}:{category}:{impact}:{sentiment}:{q}:{limit}:{offset}:{sort}"
    return await _aux_cached(key, lambda: _daas_first(
        "get_market_pulse_articles",
        {"days": days, "category": category, "impact": impact, "sentiment": sentiment,
         "q": q, "limit": limit, "offset": offset, "sort": sort},
        lambda pool: _articles(pool, days, category, impact, sentiment, q, limit, offset, sort),
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


def _fmt_metric(m: Optional[Dict[str, Any]]) -> Optional[str]:
    """Format a headline metric {label,value,unit} for display, or None. A metric
    missing its label or value is treated as absent (no partial numbers)."""
    if not m:
        return None
    label, value, unit = m.get("label"), m.get("value"), m.get("unit")
    if not (label and value):
        return None
    return f"{label}: {value} {unit or ''}".strip()


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
        "one":        ins.get("one"),
        "period":     ins.get("period"),
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

    data = await _feed(days, category, impact, sentiment, q, limit, offset, sort)
    articles = data.get("articles") or []
    ins_map = await _insights_for([a.get("id") for a in articles])
    return {
        "ok": True,
        "total": int(data.get("total") or 0),
        "facets": data.get("categories") or {},
        "rows": [_row(a, ins_map.get(a.get("id"))) for a in articles],
    }


@router.get("/signals")
async def filings_signals(request: Request, days: int = 1):
    """Today's top-3 material filings (spec §3.2).

    `rank` is the DISPLAY POSITION in the impact-ordered list (1,2,3) — it is
    explicitly NOT a computed materiality score (user decision). Copy that
    surfaces this must not imply a model we do not have.

    `one`/`metric` come from the generated insight when present, else null.
    """
    await get_current_user(request)
    days = max(1, min(int(days or 1), _MAX_DAYS))

    # Top of the impact-ordered feed for the window — same ordering as the feed,
    # so the two surfaces can never disagree about what "most material" means.
    data = await _feed(days, None, None, None, None, 3, 0, "material")
    articles = data.get("articles") or []
    ins_map = await _insights_for([a.get("id") for a in articles])
    signals: List[Dict[str, Any]] = []
    for i, a in enumerate(articles, start=1):
        ins = ins_map.get(a.get("id")) or {}
        signals.append({
            "rank":      i,
            "ticker":    a.get("symbol"),
            "type":      a.get("category"),
            "one":       ins.get("one"),
            "metric":    _fmt_metric(ins.get("metric")),
            "date":      a.get("when"),
            "sentiment": a.get("sentiment"),
        })
    return {"ok": True, "signals": signals}


@router.get("/{announcement_id}/insights")
async def filing_insight_detail(request: Request, announcement_id: str):
    """The generated insight for one filing (spec §3.3).

    Returns the one-liner, reporting period, and headline metric produced by the
    stage-7 generator, grounded in the filing's parsed PDF. Honest 404 when no
    insight has been generated yet — an empty panel, not fabricated content.
    (The richer multi-section panel in §3.3 needs a richer generator; this returns
    what the generator actually produces today.)
    """
    await get_current_user(request)
    ins_map = await _insights_for([announcement_id])
    ins = ins_map.get(announcement_id)
    if not ins:
        return JSONResponse(status_code=404,
                            content={"ok": False, "reason": "no_insight_yet"})
    return {
        "ok": True,
        "id": announcement_id,
        "one": ins.get("one"),
        "period": ins.get("period"),
        "metric": _fmt_metric(ins.get("metric")),
        "metricRaw": ins.get("metric"),
        "sentiment": ins.get("sentiment"),
        "confidence": ins.get("confidence"),
        "docType": ins.get("docType"),
        "model": ins.get("model"),
        "generatedAt": ins.get("generatedAt"),
        "grounded": True,
        "disclaimer": "AI-generated summary · refer to the source document for complete detail.",
    }
