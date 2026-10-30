"""Research -> Charts, INTRADAY bars (5m / 15m / 30m / 60m) from Kite with the platform token. Read only.

    GET /api/research/chart-intraday/availability            which intervals can be shown right now (and why not)
    GET /api/research/chart-intraday/{symbol}?interval=5m&sessions=5

Same `charting` feature flag as the daily chart routes. The service is services/kite_live_feed/intraday.py: on-demand, short cache,
Kite's historical rate limit respected, raw Kite candles labelled "Kite intraday", the live price merged only into the candle in
progress, never a fabricated bar, empty with a reason when the token is missing or expired.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query

from feature_gate import require_feature
from services.kite_live_feed import config as cfg
from services.kite_live_feed import gateway as gw
from services.kite_live_feed.feed import get_feed
from services.kite_live_feed.intraday import INTERVALS, IntradayService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research/chart-intraday", tags=["research_chart_intraday"])
FLAG = "charting"
SymbolPath = PathParam(..., pattern=r"^[A-Za-z0-9&\- ]{1,40}$")

_service: Optional[IntradayService] = None


def get_service() -> IntradayService:
    """Kite's candles, or TrueData's when the market-data switch has TrueData serving (TI-3)."""
    global _service
    if _service is None:
        from nidp.shared import market_data_source as mds
        if mds.resolve().effective == "truedata":
            from services.truedata_live import serve
            _service = serve.intraday_service()
        else:
            _service = IntradayService()
    return _service


@router.get("/availability")
async def availability(user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    """`available` is true when the platform Kite session works (the feed's last call to Kite succeeded)."""
    st = await get_feed().read_status() or {}
    ok = st.get("state") in ("live", "market_closed")
    reason = None if ok else ("token_expired" if st.get("state") == "expired" else "token_missing" if st.get("state") in (None, "starting", "not_connected", "disabled") else "feed_error")
    return {"available": ok, "intervals": list(INTERVALS) if ok else [], "reason": reason, "source": get_service().source,
            "session": st.get("session")}


async def _refresh_platform_token() -> None:
    """Load the day's stored platform Kite login into this worker first, as the F&O routes do (routes/fno.py): a worker that is
    not the feed's leader otherwise keeps the token it started with, and Kite refuses it once the day's login has replaced it
    ("the platform Kite session expired" while the login is valid). A failed read leaves what the worker held."""
    try:
        from deps import db
        from services.kite_live_feed import platform_token
        await platform_token.refresh_cache(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("chart intraday: the platform token could not be reloaded (%s)", type(e).__name__)


@router.get("/{symbol}")
async def intraday(symbol: str = SymbolPath, interval: str = Query("5m"), sessions: int = Query(5, ge=1, le=30),
                   user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    if interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval must be one of {', '.join(INTERVALS)}")
    await _refresh_platform_token()
    feed = get_feed()
    st = await feed.read_status() or {}
    snap = await feed.read_snapshot() or {}
    sym = gw.canon(symbol)
    q = next((x for x in snap.get("quotes", []) if x.get("symbol") == sym), None)
    session_open = st.get("session") == "open"
    fresh = False
    if q:
        from routes.live_quotes import _age
        from datetime import datetime, timezone
        age = _age(snap.get("data_at"), datetime.now(timezone.utc))
        fresh = age is not None and age <= cfg.stale_after_seconds(int(st.get("cadence_seconds") or cfg.cadence_seconds()))
    try:
        return await get_service().bars(sym, interval, sessions, session_open=session_open, live_ltp=q["ltp"] if (q and fresh) else None)
    except RuntimeError:
        raise HTTPException(status_code=502, detail="upstream_unavailable")
