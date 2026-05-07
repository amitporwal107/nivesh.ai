"""Generic feed-subscription RAG.

Sibling module to copilot_rag/ (which handles portfolio-centric
deterministic queries). This module retrieves *content* — corporate
announcements, filing PDFs, structured financials — gated by the
user's `nidp.user_feed_subscriptions` rows.

Public entry point:

    from services.feed_rag.orchestrator import search

    citations = await search(user_id="…", query="reliance capex", top_k=10)
    # → list[Citation], each with feed_id, title, excerpt, url, score, metadata
"""
from .base import Citation, FeedRetriever
from .orchestrator import search

__all__ = ["Citation", "FeedRetriever", "search"]
