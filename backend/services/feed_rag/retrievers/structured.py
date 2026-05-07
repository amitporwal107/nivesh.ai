"""Parameterised-SQL retriever for structured feeds.

Structured feeds (financials, shareholding, bulk/block deals) have no
natural-language matching surface — the user's query is interpreted as
a ticker-or-keyword filter, and the SQL template handles the rest.

This module hosts the *generic* runtime; per-feed SQL templates live in
the FEED_TEMPLATES dict so adding a new structured feed is a single-row
addition + a feeds-catalog INSERT — no new code path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.feed_rag.base import Citation, FeedRetriever, RetrieverContext

try:
    from nidp.shared.storage.pg import get_pool      # type: ignore
except ImportError:
    get_pool = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class StructuredTemplate:
    """One feed's SQL contract.

    `sql` must accept exactly: $1 = ticker_filter (text[] or NULL),
    $2 = top_k (int). Additional params can be added per template.

    `to_citation` maps a row dict to a Citation. Lets each feed shape
    title/excerpt/metadata appropriately.
    """
    sql: str
    title_template: str            # Python format string over row dict
    excerpt_template: str
    feed_id: str
    url_field: Optional[str] = None
    as_of_field: str = "as_of_date"
    score_field: Optional[str] = None  # if None, score = 1.0 / (rank+1)


_TICKER_RE = re.compile(r"\b[A-Z]{2,12}\b")


def _extract_tickers_from_query(query: str) -> list[str]:
    """Pull obvious upper-case ticker tokens from the user's query.

    Falls back gracefully — if the user typed "reliance capex plan"
    we get nothing here, but their subscription params still work.
    """
    return list({m for m in _TICKER_RE.findall(query.upper())})


# ── Template registry ──────────────────────────────────────────────
# Add a new structured feed here + a row in nidp.feeds + (optionally)
# a registry mapping in services/feed_rag/registry.py. No other code
# changes required.

FEED_TEMPLATES: dict[str, StructuredTemplate] = {
    "financial_results": StructuredTemplate(
        feed_id="financial_results",
        sql="""
            SELECT ticker_symbol, period_end_date AS as_of_date,
                   metric_name, metric_value, unit
              FROM nidp.nse_financial_results
             WHERE ($1::text[] IS NULL OR ticker_symbol = ANY($1::text[]))
             ORDER BY period_end_date DESC, ticker_symbol
             LIMIT $2
        """,
        title_template="[{ticker_symbol}] {metric_name} = {metric_value} {unit}",
        excerpt_template="As of {as_of_date}: {metric_name} for {ticker_symbol} = {metric_value} {unit}.",
    ),
    "shareholding_pattern": StructuredTemplate(
        feed_id="shareholding_pattern",
        sql="""
            SELECT ticker_symbol, period_end_date AS as_of_date,
                   promoter_pct, fii_pct, dii_pct, public_pct, pledge_pct
              FROM nidp.nse_shareholding_pattern
             WHERE ($1::text[] IS NULL OR ticker_symbol = ANY($1::text[]))
             ORDER BY period_end_date DESC, ticker_symbol
             LIMIT $2
        """,
        title_template="[{ticker_symbol}] Shareholding {as_of_date}",
        excerpt_template=(
            "Promoter {promoter_pct}% / FII {fii_pct}% / DII {dii_pct}% / "
            "Public {public_pct}% / Pledge {pledge_pct}%"
        ),
    ),
    "bulk_block_deals": StructuredTemplate(
        feed_id="bulk_block_deals",
        sql="""
            SELECT as_of_date, symbol AS ticker_symbol, deal_type, client_name,
                   quantity, avg_price, deal_type AS variant
              FROM nidp.bulk_deals
             WHERE ($1::text[] IS NULL OR symbol = ANY($1::text[]))
             ORDER BY as_of_date DESC
             LIMIT $2
        """,
        title_template="[{ticker_symbol}] {variant} on {as_of_date}",
        excerpt_template=(
            "{client_name} {variant} {quantity} shares @ ₹{avg_price} on {as_of_date}"
        ),
    ),
}


class StructuredRetriever(FeedRetriever):
    """One instance per structured feed_id; bound to a FEED_TEMPLATES entry."""

    def __init__(self, feed_id: str) -> None:
        if feed_id not in FEED_TEMPLATES:
            raise KeyError(f"no structured template registered for feed_id={feed_id!r}")
        self.feed_id = feed_id
        self._tmpl = FEED_TEMPLATES[feed_id]

    async def search(self, ctx: RetrieverContext) -> list[Citation]:
        if get_pool is None:
            return []
        params = ctx.subscription_params or {}
        tickers: Optional[list[str]] = (
            params.get("tickers") or _extract_tickers_from_query(ctx.query) or None
        )
        if tickers:
            tickers = [t.upper() for t in tickers]
            if not tickers:
                tickers = None

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(self._tmpl.sql, tickers, ctx.top_k)

        out: list[Citation] = []
        for rank, r in enumerate(rows):
            d = dict(r)
            try:
                title = self._tmpl.title_template.format(**d)
                excerpt = self._tmpl.excerpt_template.format(**d)
            except KeyError as e:
                logger.warning("structured template %s missing field %s; skipping row", self.feed_id, e)
                continue
            score = (1.0 / (rank + 1.0)) if self._tmpl.score_field is None else float(d[self._tmpl.score_field])
            as_of_raw = d.get(self._tmpl.as_of_field)
            as_of = as_of_raw if isinstance(as_of_raw, datetime) else datetime.combine(
                as_of_raw, datetime.min.time(), tzinfo=timezone.utc
            ) if as_of_raw else datetime.now(timezone.utc)
            out.append(Citation(
                feed_id=self.feed_id,
                title=title,
                excerpt=excerpt,
                score=score,
                as_of=as_of,
                url=d.get(self._tmpl.url_field) if self._tmpl.url_field else None,
                metadata=d,
            ))
        return out
