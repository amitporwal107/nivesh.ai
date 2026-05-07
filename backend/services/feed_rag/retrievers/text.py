"""Postgres full-text-search retriever for corporate_announcements.

Uses the built-in `to_tsvector('english', …)` over subject + description
+ company_name. ts_rank_cd is the score; we add a freshness boost so a
high-relevance 6-month-old filing doesn't outrank a today-filed one of
equal lexical match.

Supported subscription_params:
  tickers       list[str]  filter to these NSE symbols (or BSE company match)
  min_impact    'low'|'medium'|'high'   filter rows below this impact level
  event_category str       filter to a specific classifier category
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from services.feed_rag.base import Citation, FeedRetriever, RetrieverContext

try:                                                  # asyncpg is the canonical pool
    from nidp.shared.storage.pg import get_pool      # type: ignore
except ImportError:                                   # for non-NIDP test contexts
    get_pool = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}

_SQL = """
WITH q AS (
    SELECT plainto_tsquery('english', $1) AS tsq
)
SELECT
    a.announcement_id,
    a.source,
    a.ticker_symbol,
    a.scrip_code,
    a.company_name,
    a.subject,
    a.description,
    a.attachment_url,
    a.event_category,
    a.impact_score,
    a.sentiment,
    a.filed_at,
    ts_rank_cd(
        to_tsvector('english',
            coalesce(a.subject,'') || ' ' ||
            coalesce(a.description,'') || ' ' ||
            coalesce(a.company_name,'')
        ),
        q.tsq
    ) AS lex_score,
    -- Freshness multiplier: 1.0 today, ~0.5 at 30 days, ~0.1 at 1 year.
    EXP(- EXTRACT(EPOCH FROM (NOW() - a.filed_at)) / (30 * 86400.0)) AS freshness
  FROM nidp.corporate_announcements a, q
 WHERE to_tsvector('english',
            coalesce(a.subject,'') || ' ' ||
            coalesce(a.description,'') || ' ' ||
            coalesce(a.company_name,'')
       ) @@ q.tsq
   AND ($2::text[]   IS NULL OR a.ticker_symbol = ANY($2::text[]) OR a.scrip_code = ANY($2::text[]))
   AND ($3::text     IS NULL OR a.event_category = $3)
   AND ($4::int      IS NULL OR (
            a.impact_score IS NOT NULL AND
            CASE a.impact_score WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 END >= $4
       ))
 ORDER BY lex_score * freshness DESC
 LIMIT $5
"""


class CorporateAnnouncementsRetriever(FeedRetriever):
    feed_id = "corporate_announcements"

    async def search(self, ctx: RetrieverContext) -> list[Citation]:
        if get_pool is None:
            return []
        params = ctx.subscription_params or {}
        tickers: list[str] | None = params.get("tickers") or None
        if tickers:
            tickers = [t.upper() for t in tickers]
        category: str | None = params.get("event_category") or None
        min_impact_str: str | None = params.get("min_impact") or None
        min_impact = _IMPACT_RANK.get(min_impact_str) if min_impact_str else None

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                _SQL,
                ctx.query,
                tickers,
                category,
                min_impact,
                ctx.top_k,
            )

        out: list[Citation] = []
        for r in rows:
            score = float(r["lex_score"]) * float(r["freshness"])
            ticker_or_scrip = r["ticker_symbol"] or r["scrip_code"] or "?"
            title = f"[{ticker_or_scrip}] {r['subject'] or '(no subject)'}"
            excerpt = r["description"] or r["subject"] or ""
            if len(excerpt) > 500:
                excerpt = excerpt[:497] + "…"
            out.append(Citation(
                feed_id=self.feed_id,
                title=title,
                excerpt=excerpt,
                score=score,
                as_of=r["filed_at"] or datetime.now(timezone.utc),
                url=r["attachment_url"],
                metadata={
                    "source": r["source"],
                    "ticker": r["ticker_symbol"],
                    "scrip_code": r["scrip_code"],
                    "company_name": r["company_name"],
                    "event_category": r["event_category"],
                    "impact_score": r["impact_score"],
                    "sentiment": r["sentiment"],
                },
            ))
        return out
