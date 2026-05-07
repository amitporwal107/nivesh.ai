"""feed_id → FeedRetriever instance mapping.

Single source of truth for what code handles each feed. The DB catalog
in nidp.feeds is the *user-facing* list; this dict is the *runtime
binding*. A feed in the catalog without an entry here is a no-op (logs
a warning); a retriever here without a catalog row is invisible to
subscriptions.
"""
from __future__ import annotations

import logging

from .base import FeedRetriever
from .retrievers.structured import StructuredRetriever, FEED_TEMPLATES
from .retrievers.text import CorporateAnnouncementsRetriever
from .retrievers.vector import FilingDocumentsRetriever

logger = logging.getLogger(__name__)


def _build_registry() -> dict[str, FeedRetriever]:
    reg: dict[str, FeedRetriever] = {
        "corporate_announcements": CorporateAnnouncementsRetriever(),
        "filing_documents":        FilingDocumentsRetriever(),
    }
    # All structured feeds get auto-bound from FEED_TEMPLATES so adding
    # a new template is a one-place change.
    for fid in FEED_TEMPLATES:
        reg[fid] = StructuredRetriever(fid)
    return reg


REGISTRY: dict[str, FeedRetriever] = _build_registry()


def get_retriever(feed_id: str) -> FeedRetriever | None:
    r = REGISTRY.get(feed_id)
    if r is None:
        logger.warning("feed_rag: no retriever registered for feed_id=%s", feed_id)
    return r
