"""user_id → list[(FeedRetriever, params)] resolver.

Read-side of nidp.user_feed_subscriptions. The orchestrator calls this
once per query to decide which retrievers to fan out to.

CRUD lives in routes/feeds.py — this module is read-only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .base import FeedRetriever
from .registry import get_retriever

try:
    from nidp.shared.storage.pg import get_pool      # type: ignore
except ImportError:
    get_pool = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_FETCH_SQL = """
SELECT feed_id, params
  FROM nidp.v_active_subscriptions
 WHERE user_id = $1
"""


@dataclass
class ResolvedSubscription:
    feed_id: str
    retriever: FeedRetriever
    params: dict[str, Any]


async def resolve(user_id: str) -> list[ResolvedSubscription]:
    """Return one ResolvedSubscription per *active* (unpaused, enabled)
    subscription whose feed_id has a registered retriever.
    """
    if get_pool is None:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_FETCH_SQL, user_id)
    out: list[ResolvedSubscription] = []
    for r in rows:
        retriever = get_retriever(r["feed_id"])
        if retriever is None:
            continue
        out.append(ResolvedSubscription(
            feed_id=r["feed_id"],
            retriever=retriever,
            params=dict(r["params"] or {}),
        ))
    return out
