"""Filings Home — Design B's home screen API (docs/FILINGS_HOME_SPEC.md §3).

Two read endpoints over the classified corporate-filings feed:

  GET /api/filings/feed     — the feed + facets + pagination
  GET /api/filings/signals  — today's top-3 impact-ordered filings

Both WRAP the articles query in `routes/markets.py` rather than re-deriving it.
That is deliberate: a second copy of that SQL already caused a shipped bug this
session (the ORDER BY defaulted to NULLS FIRST and served 100% unclassified rows;
the fix had to land in two places, and the first copy fixed was not the one that
serves). One query, one ordering, one place to fix.

Honesty constraints this module enforces (spec §4 — all measured, not assumed):
  * `days` is capped at 30. The classifier's queue floor is 30 days, so ~127k of
    ~146k announcements are permanently unclassified; offering a longer window
    would imply history we cannot classify.
  * `one` / `period` are NULL and `hasInsights` is false until the step-3
    `filing_insights` generator exists. The row still renders. It must never
    synthesise a one-liner from the exchange boilerplate `description`
    ("X has informed the Exchange about Receipt of Order") — the actual value and
    scope live only inside the PDF.
  * `metric` is OMITTED from signals, not guessed: what it should measure is
    still an open question (spec §5 Q1).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from deps import get_current_user

# Reuse the single, verified articles implementation (see module docstring).
from routes.markets import _aux_cached, _daas_first, _articles

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/filings", tags=["filings"])

# The classifier's queue floor. Not a UI preference — see spec §4.1.
_MAX_DAYS = 30
_SORTS = ("material", "latest")


async def _feed(days: int, category: Optional[str], impact: Optional[str],
                sentiment: Optional[str], q: Optional[str],
                limit: int, offset: int, sort: str) -> Dict[str, Any]:
    """Fetch the articles payload (DaaS primary, app PG fallback) and reshape it
    into Design B's contract."""
    key = f"filings:feed:{days}:{category}:{impact}:{sentiment}:{q}:{limit}:{offset}:{sort}"
    return await _aux_cached(key, lambda: _daas_first(
        "get_market_pulse_articles",
        {"days": days, "category": category, "impact": impact, "sentiment": sentiment,
         "q": q, "limit": limit, "offset": offset, "sort": sort},
        lambda pool: _articles(pool, days, category, impact, sentiment, q, limit, offset, sort),
        {"articles": [], "total": 0, "categories": {}},
    ))


def _row(a: Dict[str, Any]) -> Dict[str, Any]:
    """One feed row. `one`/`period`/`hasInsights` are the step-3 seam."""
    return {
        "id":         a.get("id"),
        "ticker":     a.get("symbol"),
        "name":       a.get("company"),
        "date":       a.get("when"),
        "category":   a.get("category"),
        "impact":     a.get("impact"),
        "sentiment":  a.get("sentiment"),
        # The exchange's own label for the document ("Press Release", "Investor
        # Presentation"). NOT a summary — see the honesty note above.
        "docLabel":   a.get("title"),
        "url":        a.get("url"),
        "one":        None,
        "period":     None,
        "hasInsights": False,
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
    return {
        "ok": True,
        "total": int(data.get("total") or 0),
        "facets": data.get("categories") or {},
        "rows": [_row(a) for a in (data.get("articles") or [])],
    }


@router.get("/signals")
async def filings_signals(request: Request, days: int = 1):
    """Today's top-3 material filings (spec §3.2).

    `rank` is the DISPLAY POSITION in the impact-ordered list (1,2,3) — it is
    explicitly NOT a computed materiality score (user decision). Copy that
    surfaces this must not imply a model we do not have.

    `metric` is absent by design: see spec §5 Q1. `one` stays null until the
    step-3 insights generator lands.
    """
    await get_current_user(request)
    days = max(1, min(int(days or 1), _MAX_DAYS))

    # Top of the impact-ordered feed for the window — same ordering as the feed,
    # so the two surfaces can never disagree about what "most material" means.
    data = await _feed(days, None, None, None, None, 3, 0, "material")
    signals: List[Dict[str, Any]] = []
    for i, a in enumerate(data.get("articles") or [], start=1):
        signals.append({
            "rank":      i,
            "ticker":    a.get("symbol"),
            "type":      a.get("category"),
            "one":       None,
            "date":      a.get("when"),
            "sentiment": a.get("sentiment"),
        })
    return {"ok": True, "signals": signals}
