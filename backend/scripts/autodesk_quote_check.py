"""AD-P2-98: one real, read-only quote through the desk's live-price path (market/live_quotes.KiteQuoteSource). Writes nothing.
It needs the day's admin Kite login: with no valid login it prints the reason and no price. Prints no secret.

  usage: a container from the staging backend image on the staging network, with REDIS_URL, MONGO_URL, DB_NAME, KITE_API_KEY and
  PII_ENCRYPTION_KEY passed in (process substitution from docker inspect, never printed), worktree mounted read-only:
    python scripts/autodesk_quote_check.py RELIANCE
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OPENAI_API_KEY", "quote-check-placeholder")


async def main(symbol: str) -> None:
    from deps import db
    from services.kite_live_feed import platform_token

    from autodesk.market.live_quotes import KiteQuoteSource, check_quote
    from autodesk.market.session_bars import LegRef
    now = datetime.now(timezone.utc)
    status = await platform_token.token_status(db)
    out = {"now": now.isoformat(), "login": {k: status.get(k) for k in ("stored", "valid_until", "expired")}}
    leg = LegRef("EQ", symbol)
    answer = await KiteQuoteSource().quotes([leg], now)
    q = answer.quotes.get(leg.key)
    out["problems"] = answer.problems
    out["freshness_check"] = check_quote(q, now) or "OK: this quote may price a fill"
    if q is not None:
        out["quote"] = {"symbol": q.symbol, "source": q.source, "ltp": str(q.ltp), "bid": str(q.bid), "ask": str(q.ask),
                        "bid_qty": q.bid_qty, "ask_qty": q.ask_qty, "volume": q.volume,
                        "received_at": q.received_at.isoformat() if q.received_at else None}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"))
