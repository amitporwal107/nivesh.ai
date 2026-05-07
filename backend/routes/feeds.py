"""HTTP API for feed catalog + subscriptions + search.

Endpoints:
    GET    /api/feeds                       list catalog (filtered by user tier)
    GET    /api/feeds/subscriptions         current user's active subscriptions
    POST   /api/feeds/subscriptions         { feed_id, params } — subscribe/update
    DELETE /api/feeds/subscriptions/{feed}  unsubscribe
    POST   /api/feeds/subscriptions/{feed}/pause   soft-pause without losing params
    POST   /api/feeds/subscriptions/{feed}/resume
    POST   /api/feeds/search                { query, top_k?, feed_ids? } → citations
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.feed_rag.orchestrator import search as feed_search

try:
    from nidp.shared.storage.pg import get_pool       # type: ignore
except ImportError:
    get_pool = None                                   # type: ignore[assignment]

try:
    # Project-standard auth dependency. Injected user_id comes from the
    # session/JWT; same pattern as other authenticated routes.
    from helpers.auth import current_user_id           # type: ignore
except ImportError:
    async def current_user_id() -> str:                # local-dev fallback
        return "anonymous"

router = APIRouter(prefix="/api/feeds", tags=["feeds"])
logger = logging.getLogger(__name__)


class FeedOut(BaseModel):
    feed_id: str
    name: str
    description: Optional[str]
    retrieval_kind: str
    tier: str
    params_schema: Optional[dict[str, Any]]


class SubscriptionIn(BaseModel):
    feed_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class SubscriptionOut(BaseModel):
    feed_id: str
    feed_name: str
    params: dict[str, Any]
    paused: bool
    subscribed_at: str


class SearchIn(BaseModel):
    query: str
    top_k: int = Field(10, ge=1, le=50)
    feed_ids: Optional[list[str]] = None


class CitationOut(BaseModel):
    feed_id: str
    title: str
    excerpt: str
    score: float
    as_of: str
    url: Optional[str]
    metadata: dict[str, Any]


# ── Catalog ──────────────────────────────────────────────────────────

@router.get("", response_model=list[FeedOut])
async def list_feeds(user_id: str = Depends(current_user_id)) -> list[FeedOut]:
    """List enabled feeds the user can subscribe to.

    Tier gating ('pro'/'institutional') is filtered server-side based on
    the user's entitlement; the placeholder below treats every user as
    'free' until the entitlements module lands.
    """
    if get_pool is None:
        return []
    user_tier = "free"  # TODO: replace with helpers.entitlements.tier_for(user_id)
    allowed = (
        ("free",) if user_tier == "free"
        else ("free", "pro") if user_tier == "pro"
        else ("free", "pro", "institutional")
    )
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT feed_id, name, description, retrieval_kind, tier, params_schema
              FROM nidp.feeds
             WHERE enabled = TRUE AND tier = ANY($1::text[])
             ORDER BY tier, feed_id
            """,
            list(allowed),
        )
    return [FeedOut(**dict(r)) for r in rows]


# ── Subscriptions ────────────────────────────────────────────────────

@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subscriptions(user_id: str = Depends(current_user_id)) -> list[SubscriptionOut]:
    if get_pool is None:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.feed_id, f.name AS feed_name, s.params,
                   (s.paused_at IS NOT NULL) AS paused,
                   s.subscribed_at
              FROM nidp.user_feed_subscriptions s
              JOIN nidp.feeds f USING (feed_id)
             WHERE s.user_id = $1
             ORDER BY s.subscribed_at DESC
            """,
            user_id,
        )
    return [
        SubscriptionOut(
            feed_id=r["feed_id"],
            feed_name=r["feed_name"],
            params=dict(r["params"] or {}),
            paused=r["paused"],
            subscribed_at=r["subscribed_at"].isoformat(),
        )
        for r in rows
    ]


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
async def subscribe(body: SubscriptionIn, user_id: str = Depends(current_user_id)) -> SubscriptionOut:
    if get_pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DB unavailable")
    pool = await get_pool()
    async with pool.acquire() as conn:
        feed = await conn.fetchrow(
            "SELECT feed_id, name, enabled FROM nidp.feeds WHERE feed_id = $1",
            body.feed_id,
        )
        if not feed or not feed["enabled"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"feed {body.feed_id!r} not available")
        await conn.execute(
            """
            INSERT INTO nidp.user_feed_subscriptions (user_id, feed_id, params, subscribed_at, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW(), NOW())
            ON CONFLICT (user_id, feed_id) DO UPDATE
                SET params = EXCLUDED.params,
                    paused_at = NULL,
                    updated_at = NOW()
            """,
            user_id, body.feed_id, json.dumps(body.params),
        )
        row = await conn.fetchrow(
            """
            SELECT s.feed_id, f.name AS feed_name, s.params,
                   (s.paused_at IS NOT NULL) AS paused, s.subscribed_at
              FROM nidp.user_feed_subscriptions s
              JOIN nidp.feeds f USING (feed_id)
             WHERE s.user_id = $1 AND s.feed_id = $2
            """,
            user_id, body.feed_id,
        )
    return SubscriptionOut(
        feed_id=row["feed_id"],
        feed_name=row["feed_name"],
        params=dict(row["params"] or {}),
        paused=row["paused"],
        subscribed_at=row["subscribed_at"].isoformat(),
    )


@router.delete("/subscriptions/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(feed_id: str, user_id: str = Depends(current_user_id)) -> None:
    if get_pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DB unavailable")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM nidp.user_feed_subscriptions WHERE user_id=$1 AND feed_id=$2",
            user_id, feed_id,
        )


@router.post("/subscriptions/{feed_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
async def pause(feed_id: str, user_id: str = Depends(current_user_id)) -> None:
    if get_pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DB unavailable")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE nidp.user_feed_subscriptions SET paused_at = NOW(), updated_at = NOW()"
            " WHERE user_id=$1 AND feed_id=$2",
            user_id, feed_id,
        )


@router.post("/subscriptions/{feed_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume(feed_id: str, user_id: str = Depends(current_user_id)) -> None:
    if get_pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DB unavailable")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE nidp.user_feed_subscriptions SET paused_at = NULL, updated_at = NOW()"
            " WHERE user_id=$1 AND feed_id=$2",
            user_id, feed_id,
        )


# ── Search ──────────────────────────────────────────────────────────

@router.post("/search", response_model=list[CitationOut])
async def search_feeds(body: SearchIn, user_id: str = Depends(current_user_id)) -> list[CitationOut]:
    citations = await feed_search(user_id, body.query, top_k=body.top_k, feed_ids=body.feed_ids)
    return [
        CitationOut(
            feed_id=c.feed_id,
            title=c.title,
            excerpt=c.excerpt,
            score=c.score,
            as_of=c.as_of.isoformat() if c.as_of else "",
            url=c.url,
            metadata=c.metadata,
        )
        for c in citations
    ]
