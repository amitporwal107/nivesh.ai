#!/usr/bin/env python3
"""reconcile_fno_oi.py: check every open-interest figure the F&O screens show against the NSE F&O bhavcopy of the day
and of the session before, and against Kite's intraday candles (services/fno_oi_reconcile.py has the seven checks).

    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.reconcile_fno_oi --symbols HDFCAMC
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.reconcile_fno_oi --symbols HDFCAMC,RELIANCE --json /tmp/oi.json
    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.reconcile_fno_oi --symbols NIFTY --no-intraday

What is read, all read only:
  the app       the F&O routes the screens call (routes/fno.py: expiries, chain per expiry with every strike,
                chain/consolidated, futures, futures/oi-buildup with daily bars, options/intraday), in process as a
                system caller (deps.system_caller): the same code, caches and data platform reads as the screen, without
                a login. Nothing is recomputed on the app's side
  bhavcopy D    every contract of the underlying on the app's day (DaaS /v1/fno/{symbol}?on=D, every page)
  bhavcopy P    the same for the session before D in the data (the day before D among the chart's daily bars)
  Kite          the candles the oi-buildup and options-intraday routes return (ReadOnlyKite inside those routes)

Writes nothing: no database, no Mongo, no file unless --json is given. Not scheduled: a schedule is a separate,
approved step.

Exit codes: 0 no check failed (warnings and skips allowed); 3 a check failed; 2 an underlying could not be read.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reconcile_fno_oi")

SYSTEM_USER: Dict[str, Any] = {"user_id": "system:fno-oi-reconcile", "name": "F&O OI reconciliation", "email": None,
                               "is_admin": False, "role": "user"}
DAY_PAGE = 5000
DAY_MAX_PAGES = 10      # one underlying's day: NIFTY's every expiry is a few thousand rows


def internal_request():
    """A request object for in-process route calls. Carries no cookie or token: the system caller is the identity."""
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": "/internal/fno-oi-reconcile", "raw_path": b"/internal/fno-oi-reconcile",
                    "query_string": b"", "headers": [], "client": ("127.0.0.1", 0), "server": ("internal", 80),
                    "scheme": "http", "root_path": ""})


def previous_session(buildup: Optional[Dict[str, Any]], day: str) -> Optional[str]:
    """The session before `day` in the data: the latest daily-bar day before it (any slot)."""
    days = {str(b[0])[:10] for s in ((buildup or {}).get("contracts") or []) + [(buildup or {}).get("consolidated") or {}]
            for b in s.get("daily_bars") or []}
    before = sorted(d for d in days if d < day)
    return before[-1] if before else None


async def read_day(sym: str, day: str) -> List[Dict[str, Any]]:
    """Every bhavcopy row of the underlying on `day`, through every page. An answer for another day raises."""
    from routes import fno

    rows: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(DAY_MAX_PAGES):
        body = await fno._daas(f"/fno/{sym}", {"on": day, "limit": DAY_PAGE, "offset": offset}, sym)
        page = fno._rows_for_day(body, day, f"/fno/{sym} all expiries")
        rows.extend(page)
        nxt = (body.get("pagination") or {}).get("next_offset") if isinstance(body.get("pagination"), dict) else None
        if not page or not isinstance(nxt, int) or isinstance(nxt, bool):
            return rows
        offset = nxt
    raise RuntimeError(f"/fno/{sym} on {day} ran past {DAY_MAX_PAGES} pages")


async def _call(what: str, skips: List[Dict[str, Any]], checks: Tuple[str, ...], coro) -> Optional[Dict[str, Any]]:
    """One route call. A route that refuses (404, 502) or fails becomes SKIP findings for the checks that need it."""
    from fastapi import HTTPException

    from services import fno_oi_reconcile as rc

    try:
        return await coro
    except HTTPException as e:
        reason = f"{what}: HTTP {e.status_code} {e.detail}"
    except Exception as e:  # noqa: BLE001 — any failure is reported as a skip with its type, never as a pass
        reason = f"{what}: {type(e).__name__}: {e}"
    log.warning("%s", reason)
    skips.extend(rc.finding(c, rc.SKIP, what, note=reason) for c in checks)
    return None


async def gather(sym: str, args: argparse.Namespace) -> Dict[str, Any]:
    """Every source for one underlying, then the checks."""
    from deps import system_caller
    from routes import fno

    from services import fno_oi_reconcile as rc

    req = internal_request()
    skips: List[Dict[str, Any]] = []
    with system_caller(SYSTEM_USER):
        listing = await fno.expiries(req, sym)
        day = listing["as_of"]
        expiries = [e["expiry"] for e in listing.get("expiries") or []]
        chains: Dict[str, Dict[str, Any]] = {}
        for e in expiries:
            ch = await _call(f"chain {e}", skips, ("C1", "C2", "C3", "C4", "C6"),
                             fno.chain(req, sym, date.fromisoformat(e), fno.MAX_AROUND))
            if ch is not None:
                chains[e] = ch
        consolidated = await _call("chain/consolidated", skips, ("C6",), fno.chain_consolidated(req, sym, fno.MAX_AROUND))
        futures = await _call("futures", skips, ("C1", "C2", "C3", "C6"), fno.futures(req, sym))
        buildup = await _call("futures/oi-buildup", skips, ("C2", "C5", "C6", "C7"),
                              fno.futures_oi_buildup(req, sym, args.interval, args.window, args.sessions, args.daily))
        options = None
        if not args.no_intraday:
            options = await _call("options/intraday", skips, ("C2", "C5", "C7"),
                                  fno.options_intraday(req, sym, args.interval, args.sessions, args.strikes))
        today_rows = await read_day(sym, day)
        prev_day = previous_session(buildup, day)
        prev_rows: Optional[List[Dict[str, Any]]] = None
        if prev_day:
            try:
                prev_rows = await read_day(sym, prev_day)
            except Exception as e:  # noqa: BLE001 — C1 / C3 / C4 become SKIP with this reason (rc.run)
                log.warning("%s bhavcopy %s could not be read: %s", sym, prev_day, getattr(e, "detail", e))
    return rc.run(sym, day, prev_day, today_rows, prev_rows, chains, consolidated, futures, buildup, options, skips,
                  small_base_lots=args.small_base_lots)


async def main_async(args: argparse.Namespace) -> int:
    from services import fno_oi_reconcile as rc

    reports, unreadable = [], []
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        try:
            r = await gather(sym, args)
        except Exception as e:  # noqa: BLE001 — one underlying that cannot be read does not stop the rest
            log.error("%s could not be read: %s: %s", sym, type(e).__name__, getattr(e, "detail", e))
            unreadable.append(sym)
            continue
        reports.append(r)
        print(rc.render(r), flush=True)
        print(flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps({"reports": reports, "unreadable": unreadable}, indent=1, default=str))
    statuses = ", ".join(f"{r['symbol']} {r['status']}" for r in reports)
    print(f"SUMMARY: {statuses}" + (f"; could not read {', '.join(unreadable)}" if unreadable else ""))
    code = rc.exit_code(reports)
    return code if code else (2 if unreadable else 0)


def parse(argv: Optional[List[str]] = None) -> argparse.Namespace:
    from services import fno_oi_reconcile as rc

    p = argparse.ArgumentParser(description="Reconcile the F&O screens' open interest with the NSE bhavcopy and Kite")
    p.add_argument("--symbols", required=True, help="Comma-separated underlyings, e.g. HDFCAMC,RELIANCE")
    p.add_argument("--daily", type=int, default=60, help="Daily bars per futures slot (the chart's 1D / 1W panes)")
    p.add_argument("--interval", default="15m", help="Intraday candle interval")
    p.add_argument("--window", type=int, default=4, help="Bars per intraday window")
    p.add_argument("--sessions", type=int, default=2, help="Intraday sessions")
    p.add_argument("--strikes", type=int, default=5, help="Option strikes each side of ATM for the intraday pane")
    p.add_argument("--no-intraday", action="store_true", help="Skip the options intraday read (Kite)")
    p.add_argument("--small-base-lots", type=int, default=rc.SMALL_BASE_LOTS, help="C4 warns below this previous OI, in lots")
    p.add_argument("--json", help="Also write every finding to this file")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return asyncio.run(main_async(parse(argv)))


if __name__ == "__main__":
    sys.exit(main())
