#!/usr/bin/env python3
"""check_desk_alerts.py — the evening check of every user's desk paper trades and price alerts.

Applies the same end-of-day rules as GET /api/desk/paper-trades and GET /api/desk/alerts
(services/desk_trading.py) to ALL users, so a stop, a target or an alert is recorded even when nobody
opens the desk: open paper trades whose bars show the stop or the target are closed at that level, and
active alerts whose level was reached are marked fired. Notification is in-app only (the alerts list).
Nothing here places an order or talks to a broker.

Idempotent: each write has the trade's / alert's current status in its filter, so a second run (or a GET
racing it) changes nothing and never overwrites a manual close. Bars are read once per symbol from the
data platform (GET /v1/prices/eod/{symbol}, raw traded prices), at most 8 at a time.

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts
    docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts --dry-run   # report, write nothing

Exit codes (like scripts/run_positional_engine.py):
  0 — ran (some symbols may have had no prices; each is logged)
  1 — fatal: the database could not be read or written, or no symbol's prices could be read at all
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("check_desk_alerts")


async def run(db=None, *, dry_run: bool = False) -> Dict[str, Any]:
    """Check every open paper trade and active alert. Returns the counts that are logged; `ok` is False
    only when there was something to check and no prices could be read for any of it."""
    from services import desk_trading as svc  # noqa: E402

    if db is None:
        from deps import db  # noqa: E402

    if not dry_run:
        await svc.ensure_indexes(db)
    trades = await db[svc.TRADES].find({"status": "open"}).to_list(None)
    alerts = await db[svc.ALERTS].find({"status": "active"}).to_list(None)

    starts = svc.fetch_starts(trades, "opened_at")
    for symbol, start in svc.fetch_starts(alerts, "created_at").items():
        if symbol not in starts or start < starts[symbol]:
            starts[symbol] = start
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})

    _, trade_counts = await svc.apply_trade_exits(db, trades, bars, persist=not dry_run)
    _, alert_counts = await svc.apply_alert_fires(db, alerts, bars, persist=not dry_run)

    no_prices = sorted(s for s, b in bars.items() if svc.last_close(b) is None)
    latest = svc.latest_day(b["date"] for b in (svc.last_close(v) for v in bars.values()) if b)
    out = {
        "dry_run": dry_run,
        "open_trades": len(trades),
        "active_alerts": len(alerts),
        "users": len({d["user_id"] for d in [*trades, *alerts]}),
        "symbols": len(starts),
        "symbols_failed": sorted(errors),
        "symbols_without_prices": no_prices,
        "exits_stop": trade_counts["stop"],
        "exits_target": trade_counts["target"],
        "exits_already_recorded": trade_counts["already_closed"],
        "alerts_fired": alert_counts["fired"],
        "alerts_already_recorded": alert_counts["already_fired"],
        "latest_session": latest.isoformat() if latest else None,
    }
    out["ok"] = not starts or len(errors) < len(starts)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description="Check every user's desk paper trades and price alerts against end-of-day bars")
    p.add_argument("--dry-run", action="store_true", help="Report what would close or fire; write nothing")
    args = p.parse_args()

    try:
        result = asyncio.run(run(dry_run=args.dry_run))
    except Exception as exc:  # noqa: BLE001 — the database (or something under it) failed; cron needs a non-zero exit
        log.exception("desk check failed: %r", exc)
        return 1
    log.info(
        "desk check%s: users=%d open_trades=%d active_alerts=%d symbols=%d failed=%d no_prices=%d | "
        "exits stop=%d target=%d already=%d | alerts fired=%d already=%d | latest_session=%s",
        " (dry run)" if result["dry_run"] else "", result["users"], result["open_trades"], result["active_alerts"],
        result["symbols"], len(result["symbols_failed"]), len(result["symbols_without_prices"]),
        result["exits_stop"], result["exits_target"], result["exits_already_recorded"],
        result["alerts_fired"], result["alerts_already_recorded"], result["latest_session"],
    )
    if result["symbols_failed"]:
        log.warning("no prices could be read for: %s", ", ".join(result["symbols_failed"]))
    if result["symbols_without_prices"]:
        log.warning("the data platform has no end-of-day prices for: %s", ", ".join(result["symbols_without_prices"]))
    if not result["ok"]:
        log.error("no symbol's prices could be read; nothing was checked")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
