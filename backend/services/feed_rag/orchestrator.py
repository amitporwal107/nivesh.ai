"""Public entry point for feed RAG.

Fans out a query to every retriever the user is subscribed to, runs
them in parallel, merges the resulting Citation lists by score, and
returns the global top-K.

Score normalization: each retriever returns its own score scale (FTS
rank, vector cosine, structured rank). We z-score per-feed before
merging so one feed's "100" doesn't dominate another's "0.05".
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
from typing import Optional

from .base import Citation, RetrieverContext
from .subscriptions import resolve

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 10
PER_FEED_OVERFETCH = 3      # request 3× top_k per feed so the merger has headroom
RETRIEVER_TIMEOUT_S = 4.0    # per-feed budget; one slow retriever doesn't block the rest


async def search(
    user_id: str,
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    feed_ids: Optional[list[str]] = None,
) -> list[Citation]:
    """Return up to `top_k` merged citations across the user's subscribed feeds.

    feed_ids: optional filter — restrict to this subset of the user's
        subscriptions. Useful when an intent classifier has decided the
        query is about (e.g.) only financials.
    """
    subs = await resolve(user_id)
    if feed_ids:
        wanted = set(feed_ids)
        subs = [s for s in subs if s.feed_id in wanted]
    if not subs:
        return []

    per_feed_k = max(top_k, top_k * PER_FEED_OVERFETCH // len(subs)) if subs else top_k

    async def _one(s) -> list[Citation]:
        ctx = RetrieverContext(
            user_id=user_id,
            query=query,
            subscription_params=s.params,
            top_k=per_feed_k,
        )
        try:
            return await asyncio.wait_for(s.retriever.search(ctx), timeout=RETRIEVER_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("feed_rag: %s timed out after %.1fs", s.feed_id, RETRIEVER_TIMEOUT_S)
            return []
        except Exception as e:                                  # noqa: BLE001
            logger.exception("feed_rag: %s failed: %s", s.feed_id, e)
            return []

    t0 = time.monotonic()
    per_feed_results = await asyncio.gather(*[_one(s) for s in subs])
    duration = time.monotonic() - t0

    # Per-feed z-score so heterogeneous score scales merge cleanly. A
    # feed with only 1 result keeps the raw score (no variance to scale).
    merged: list[tuple[float, Citation]] = []
    for results in per_feed_results:
        if not results:
            continue
        scores = [c.score for c in results]
        if len(scores) >= 2:
            mu = statistics.mean(scores)
            sigma = statistics.stdev(scores) or 1e-9
            for c in results:
                merged.append(((c.score - mu) / sigma, c))
        else:
            merged.append((float(results[0].score), results[0]))

    merged.sort(key=lambda x: x[0], reverse=True)
    out = [c for _, c in merged[:top_k]]

    logger.info(
        "feed_rag: user=%s query=%r feeds=%d results=%d duration=%.2fs",
        user_id, query, len(subs), len(out), duration,
    )
    return out
