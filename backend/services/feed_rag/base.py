"""FeedRetriever ABC + Citation dataclass.

Every retriever (text / vector / structured) implements the same
interface. The orchestrator fans out to all subscribed retrievers and
merges Citation lists by score.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Citation:
    """One result from one feed.

    Designed to be safe to embed verbatim in an LLM context — short,
    self-contained, attributable. The copilot must surface
    `feed_id` + `title` + (when present) `url` for source attribution.
    """

    feed_id: str
    title: str
    excerpt: str                          # 200-500 chars, ready for prompt
    score: float                          # 0..1; higher = more relevant
    as_of: datetime
    url: Optional[str] = None             # source link, when available
    # Feed-specific structured fields. Examples:
    #   text:       {ticker, source, event_category, impact_score}
    #   vector:     {doc_id, chunk_index, page_start, page_end}
    #   structured: {ticker, period, line_item, value, unit}
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_block(self) -> str:
        """Render as a single context block for the LLM. Keeps the model
        anchored to *this* citation rather than free-associating.
        """
        head = f"[{self.feed_id}] {self.title}"
        if self.url:
            head += f" ({self.url})"
        return f"{head}\n{self.excerpt}"


@dataclass
class RetrieverContext:
    """Per-query inputs passed to a retriever.

    `subscription_params` carries the user's filters from
    `nidp.user_feed_subscriptions.params` (e.g. {"tickers": [...]}).
    The retriever decides how to merge them into its WHERE clause.
    """

    user_id: str
    query: str
    subscription_params: dict[str, Any]
    top_k: int


class FeedRetriever(abc.ABC):
    """Stateless. One instance per feed_id, reused across queries."""

    feed_id: str = ""        # set on subclass, must match nidp.feeds.feed_id

    @abc.abstractmethod
    async def search(self, ctx: RetrieverContext) -> list[Citation]:
        """Return up to ctx.top_k citations, sorted by descending score."""
