"""Research Watchlist API — powers the public /watchlist page.

No auth (`/api/public/...`, the established no-auth prefix — see
`routes/client_cas_invite.py`'s `public_router` for the precedent). This is
personal/internal equity research, not a recommendation the app pushes to
users: it is a static page you have to know the URL for, not linked from any
in-app navigation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

from services import research_watchlist_store as store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/public/research-watchlist", tags=["research-watchlist-public"])

DISCLAIMER = (
    "Personal / internal equity research only. Not investment advice, not a product "
    "recommendation, and not a buy or sell call. Figures are point-in-time and will "
    "drift — re-verify before acting on anything here."
)


@router.get("")
async def get_research_watchlist() -> Dict[str, Any]:
    picks: List[Dict[str, Any]] = await store.list_picks()
    return {
        "meta": {
            "count": len(picks),
            "disclaimer": DISCLAIMER,
        },
        "items": picks,
    }
