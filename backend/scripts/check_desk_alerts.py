#!/usr/bin/env python3
"""check_desk_alerts.py — the evening check of every user's desk paper trades and alerts.

Applies the same rules as GET /api/desk/paper-trades and GET /api/desk/alerts (services/desk_trading.py,
services/desk_alerts.py) to ALL users, so a stop, a target or an alert is recorded even when nobody
opens the desk: open paper trades whose bars show the stop or the target are closed at that level, open
F&O strategy trades are run through their own exit rules (services/desk_strategy_trades.apply_exits: stop,
target, expiry, time, closed at the session's end-of-day marks, which also returns their reserved capital
to the paper account), and active alerts whose condition was met (price, a new filing, a category, unusual
volume, a scanner entry, a sector move, a risk level) are marked fired with the reason. Notification is
in-app only (the alerts list). Nothing here places an order or talks to a broker.

Idempotent: each write has the trade's / alert's current status in its filter, so a second run (or a GET
racing it) changes nothing and never overwrites a manual close. Bars are read once per symbol from the
data platform (GET /v1/prices/eod/{symbol}, raw traded prices), at most 8 at a time; a strategy trade reads
its underlying's bars and each leg's contract rows (GET /v1/fno/{symbol}/history) itself, as the GET does.

Scheduled runs (deploy/nivesh-staging/desk-alerts.cron) add three guards:
  --require-bars   work out the session whose bars should be in (IST: today from 19:00, when the NIDP bhavcopy ingest
                   has run; before that the previous trading day), using the NSE holiday list (GET /v1/holidays). If
                   today has no session (weekend, NSE holiday) the run stops with exit 3. If the data platform has no
                   end-of-day rows for that session yet, the run stops with exit 2: nothing is evaluated, so nothing is
                   closed on yesterday's prices. Open F&O strategy trades are evaluated only when the F&O bhavcopy for
                   the session is in too (it is ingested later, 19:30 with retries); otherwise they wait for the next run
                   and the run says so, because a strategy exit closes its legs at the session's marks.
  --skip-if-done   a run already recorded "ok" for that session: do nothing (the 22:45 retry after a good 20:45 run).
  the lease        every run that writes takes the job's lease (services/job_runs, Mongo `job_locks`); another run
                   holding it → exit 4. The cron line also wraps the command in `flock -n`.
Every run that writes records a heartbeat in Mongo `job_runs` (status, counts, error), also when it fails, so a
missed or failed run is visible: GET /api/admin/risk/jobs/check_desk_alerts. A close whose write fails for one trade
does not stop the others: the run is recorded PARTIAL with `exits_failed` and the trade ids, the trade stays open, and the
next run retries it (every close filters on the trade being open, so a retry can never close it twice). A trailing-stop
move on a trade with an opt-in research rule is stored filtered on its `stop_version` (exit-rules-v1).

Usage:
    docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts
    docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts --require-bars --skip-if-done   # cron
    docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts --dry-run   # report; write nothing

Exit codes:
  0 — ran (some symbols may have had no prices; each is logged), or skipped because the session is already done
  1 — failed: the database could not be read or written, the data platform could not be asked whether the session is
      in, or no prices could be read for anything it had to check
  2 — skipped (--require-bars): the session's end-of-day bars are not in the data platform yet; nothing was written
  3 — skipped (--require-bars): no NSE session today (weekend or holiday); nothing was written
  4 — skipped: another run holds the job's lease; nothing was written
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

log = logging.getLogger("check_desk_alerts")

JOB = "check_desk_alerts"
#: The NIDP bhavcopy ingest runs at 19:00 IST (deploy/cloudpe/nidp/nidp-staging.cron); before this the latest session
#: that can be in is the previous trading day.
READY_AFTER = time(19, 0)
#: An underlying that always has F&O rows: its rows for the session say the F&O bhavcopy is in.
FNO_REFERENCE = "NIFTY"
HOLIDAY_LOOKBACK_DAYS = 21

EXIT_OK, EXIT_FAILED, EXIT_NO_BARS, EXIT_NO_SESSION, EXIT_LOCKED = 0, 1, 2, 3, 4


async def run(db=None, *, dry_run: bool = False, session: Optional[date] = None,
              check_strategy: bool = True) -> Dict[str, Any]:
    """Check every open paper trade and active alert. Returns the counts that are logged; `ok` is False
    only when there was something to check and no prices could be read for any of it.

    `session`: the session the run expects to be the latest (from --require-bars), used to count open trades whose
    checks have not reached it. `check_strategy=False` leaves open strategy trades for the next run (their F&O marks
    for the session are not in yet)."""
    from services import desk_alerts as alerts_svc  # noqa: E402
    from services import desk_strategy_trades as strat  # noqa: E402
    from services import desk_trading as svc  # noqa: E402

    if db is None:
        from deps import db  # noqa: E402

    if not dry_run:
        await svc.ensure_indexes(db)
    trades = await db[svc.TRADES].find({"status": "open"}).to_list(None)
    alerts = await db[svc.ALERTS].find({"status": "active"}).to_list(None)
    strategy = [t for t in trades if t.get("kind") == strat.KIND]
    cash = [t for t in trades if t.get("kind") != strat.KIND]

    # One bar read per symbol for the share trades and every bar-based alert (price, volume, risk), from the
    # earliest day any of them needs. Strategy trades read their own inputs in strat.apply_exits, as in the GET.
    starts = svc.fetch_starts(cash, "opened_at")
    for symbol, start in alerts_svc.bar_starts(alerts).items():
        if symbol not in starts or start < starts[symbol]:
            starts[symbol] = start
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})

    cash_after, trade_counts = await svc.apply_trade_exits(db, trades, bars, persist=not dry_run)
    checked_strategy = strategy if check_strategy else []
    strategy_after, strategy_sims, strategy_errors = (await strat.apply_exits(db, checked_strategy, persist=not dry_run)
                                                      if checked_strategy else ([], {}, {}))
    _, alert_counts = await alerts_svc.evaluate(db, alerts, bars, persist=not dry_run)
    # Exits the strategy rules found this run, by reason: written unless dry_run (with the status in the
    # filter, so one a GET recorded first is left as it is).
    strategy_exits: Dict[str, int] = {}
    strategy_exit_failures = [tid for tid, sim in strategy_sims.items() if sim.get("close_failed")]
    for sim in strategy_sims.values():
        if sim["exit"] is not None:
            reason = sim["exit"]["exit_reason"]
            strategy_exits[reason] = strategy_exits.get(reason, 0) + 1

    no_prices = sorted(s for s, b in bars.items() if svc.last_close(b) is None)
    latest = svc.latest_day(b["date"] for b in (svc.last_close(v) for v in bars.values()) if b)
    closed_by_reason: Dict[str, int] = {r: trade_counts.get(r, 0) for r in ("stop", "trailing_stop", "target", "time", "trend",
                                                                         "entry_not_reached") if trade_counts.get(r)}
    for reason, n in strategy_exits.items():
        closed_by_reason[f"strategy_{reason}"] = n

    # Open trades whose checks did not reach the session (or the newest bar read): the next run must catch them up.
    reference = session or latest
    behind: List[str] = []
    if reference is not None:
        still_open = {d["_id"] for d in [*cash_after, *strategy_after] if d.get("status") == "open"}
        for t in cash:
            if t["_id"] not in still_open or svc.ist_date(t["opened_at"]) >= reference:
                continue
            reached = trade_counts["checked_through"].get(t["_id"])
            if reached is None or reached < reference:
                behind.append(t["_id"])
        for t in strategy:
            sim = strategy_sims.get(t["_id"])
            if (sim and sim["exit"] is not None) or svc.ist_date(t["opened_at"]) >= reference:
                continue
            reached = sim["checked_through"] if sim else None
            if reached is None or reached < reference:
                behind.append(t["_id"])

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
        # A close whose write failed: the trade stays open and the next run retries it (the close filters on status).
        "exits_failed": trade_counts.get("exit_failed", 0) + len(strategy_exit_failures),
        "exits_failed_ids": sorted([*trade_counts.get("failed_ids", []), *strategy_exit_failures])[:20],
        "stop_updates": trade_counts.get("stop_updates", 0),
        "stop_update_conflicts": trade_counts.get("stop_update_conflicts", 0),
        "open_strategy_trades": len(strategy),
        "strategy_exits": strategy_exits,
        "strategy_not_checked": len(strategy_errors),
        "strategy_waiting_for_fno": 0 if check_strategy else len(strategy),
        "alerts_fired": alert_counts["fired"],
        "alerts_fired_by_condition": dict(alert_counts["by_condition"]),
        "alerts_already_recorded": alert_counts["already_fired"],
        "alerts_not_checked": len(alert_counts["check_errors"]),
        "latest_session": latest.isoformat() if latest else None,
        "session": session.isoformat() if session else None,
        "trades_checked": len(cash) + len(checked_strategy),
        "closed_by_reason": closed_by_reason,
        "errors": (len(errors) + len(strategy_errors) + len(alert_counts["check_errors"])
                   + trade_counts.get("exit_failed", 0) + len(strategy_exit_failures)),
        "open_trades_behind": len(behind),
        "behind_trade_ids": sorted(behind)[:20],
    }
    out["ok"] = ((not starts and not checked_strategy) or len(errors) < len(starts)
                 or len(strategy_errors) < len(checked_strategy))
    return out


# ── is the session in? ───────────────────────────────────────────────────────
def expected_session(now: datetime, holidays: Set[date]) -> Tuple[Optional[date], Optional[str]]:
    """(the session whose end-of-day bars should be in at `now`, None), or (None, why there is no session today).

    From READY_AFTER IST that is today, unless today is a weekend or an NSE holiday (no session: None). Before it, the
    latest trading day before today (walking back over weekends and holidays), so a morning rerun catches up."""
    from services import desk_trading as svc

    local = now.astimezone(svc.IST)
    today = local.date()
    if local.time() >= READY_AFTER:
        if today.weekday() >= 5:
            return None, f"{today.isoformat()} is a {today.strftime('%A')}: no NSE session"
        if today in holidays:
            return None, f"{today.isoformat()} is an NSE holiday: no session"
        return today, None
    day = today - timedelta(days=1)
    while day.weekday() >= 5 or day in holidays:
        day -= timedelta(days=1)
    return day, None


async def read_holidays(today: date) -> Tuple[Set[date], Optional[str]]:
    """NSE cash-market holidays near `today` (GET /v1/holidays, nidp.nse_holidays), and an error text when the list
    could not be read. Without the list a holiday reads as a session whose bars are missing: exit 2 instead of 3, still
    nothing written."""
    from services import desk_trading as svc

    params = {"segment": "CM", "from": (today - timedelta(days=HOLIDAY_LOOKBACK_DAYS)).isoformat(),
              "to": today.isoformat(), "limit": 100, "offset": 0}
    try:
        body = await svc.daas_client._get("/holidays", params=params, timeout=svc.FETCH_TIMEOUT_S)
    except svc.daas_client.DaasError as exc:
        return set(), f"the NSE holiday list could not be read: {str(exc)[:160]}"
    rows = (body or {}).get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return set(), "the NSE holiday list came back in an unexpected shape"
    days = set()
    for row in rows:
        try:
            days.add(date.fromisoformat(str((row or {}).get("holiday_date"))[:10]))
        except ValueError:
            log.warning("ignoring an unreadable holiday row: %r", (row or {}).get("holiday_date"))
    return days, None


async def _has_rows(path: str, params: Dict[str, Any]) -> bool:
    """True when the data platform answers `path` with at least one row. Raises PricesUnavailable when it cannot."""
    from services import desk_trading as svc

    if not svc.daas_client.is_configured():
        raise svc.PricesUnavailable("the data platform is not configured")
    try:
        body = await svc.daas_client._get(path, params=params, timeout=svc.FETCH_TIMEOUT_S)
    except svc.daas_client.DaasError as exc:
        raise svc.PricesUnavailable(str(exc)) from exc
    if body is None:
        return False
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise svc.PricesUnavailable(f"unexpected answer from {path}")
    return len(rows) > 0


async def session_readiness(now: datetime) -> Dict[str, Any]:
    """{session, no_session_reason, bars_in, fno_in, calendar_error}. Reads only."""
    from services import desk_trading as svc

    today = now.astimezone(svc.IST).date()
    holidays, calendar_error = await read_holidays(today)
    if calendar_error:
        log.warning("%s; a holiday will read as missing bars", calendar_error)
    session, why = expected_session(now, holidays)
    out = {"session": session, "no_session_reason": why, "bars_in": None, "fno_in": None, "calendar_error": calendar_error}
    if session is None:
        return out
    out["bars_in"] = await _has_rows("/prices/eod", {"on": session.isoformat(), "limit": 1, "offset": 0})
    out["fno_in"] = await _has_rows(f"/fno/{FNO_REFERENCE}", {"on": session.isoformat(), "limit": 1, "offset": 0})
    return out


# ── the scheduled run: lease, readiness, heartbeat ───────────────────────────
def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:160]}"


async def run_job(db=None, *, dry_run: bool = False, require_bars: bool = False, skip_if_done: bool = False,
                  now: Optional[datetime] = None, run_id: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
    """One run as cron makes it: (exit code, outcome). A dry run reads only (no lease, no heartbeat, no writes)."""
    from services import desk_trading as svc
    from services import job_runs

    if db is None:
        from deps import db  # noqa: E402

    now = now or svc.utcnow()
    run_id = run_id or f"{JOB}-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    sched = job_runs.SCHEDULES[JOB]
    outcome: Dict[str, Any] = {"run_id": None if dry_run else run_id, "dry_run": dry_run}

    if not dry_run:
        if not await job_runs.acquire(db, JOB, run_id, now=now, lease=sched["lease"]):
            await job_runs.start(db, JOB, run_id, now=now, dry_run=False)
            await job_runs.finish(db, run_id, now=svc.utcnow(), status=job_runs.SKIPPED_LOCKED, exit_code=EXIT_LOCKED,
                                  error="another run holds the job's lease")
            return EXIT_LOCKED, {**outcome, "status": job_runs.SKIPPED_LOCKED, "error": "another run holds the job's lease"}
        await job_runs.start(db, JOB, run_id, now=now, dry_run=False)

    async def done(code: int, status: str, counts: Optional[Dict[str, Any]] = None, error: Optional[str] = None,
                   session: Optional[str] = None) -> Tuple[int, Dict[str, Any]]:
        if not dry_run:
            await job_runs.finish(db, run_id, now=svc.utcnow(), status=status, exit_code=code, counts=counts,
                                  error=error, session=session)
            await job_runs.release(db, JOB, run_id, now=svc.utcnow())
        return code, {**outcome, "status": status, "session": session, "counts": counts, "error": error}

    try:
        session: Optional[date] = None
        check_strategy = True
        ready: Dict[str, Any] = {}
        if require_bars:
            ready = await session_readiness(now)
            session = ready["session"]
            if session is None:
                return await done(EXIT_NO_SESSION, job_runs.SKIPPED_NO_SESSION, error=ready["no_session_reason"])
            if not ready["bars_in"]:
                why = f"the {session.isoformat()} end-of-day bars are not in the data platform yet"
                if ready["calendar_error"]:
                    why += f" (or it is a holiday: {ready['calendar_error']})"
                return await done(EXIT_NO_BARS, job_runs.SKIPPED_NO_BARS, error=why, session=session.isoformat())
            check_strategy = bool(ready["fno_in"])
            if skip_if_done and not dry_run:
                prior = await job_runs.latest(db, JOB, session=session.isoformat(), status=job_runs.OK)
                if prior is not None:
                    return await done(EXIT_OK, job_runs.SKIPPED_DONE, counts={"done_by": prior["_id"]},
                                      session=session.isoformat())
        out = await run(db, dry_run=dry_run, session=session, check_strategy=check_strategy)
        if ready.get("calendar_error"):
            out["calendar_error"] = ready["calendar_error"]
    except Exception as exc:  # noqa: BLE001 — the database or the data platform failed; recorded, then exit 1
        log.exception("desk check failed: %r", exc)
        try:
            return await done(EXIT_FAILED, job_runs.FAILED, error=_error_text(exc))
        except Exception as again:  # noqa: BLE001 — the heartbeat could not be written either (database down)
            log.error("the failed run could not be recorded either: %r", again)
            return EXIT_FAILED, {**outcome, "status": job_runs.FAILED, "error": _error_text(exc)}

    session_text = session.isoformat() if session else None
    if not out["ok"]:
        return await done(EXIT_FAILED, job_runs.FAILED, out, "no prices could be read for any trade or alert", session_text)
    partial = out["errors"] > 0 or out["strategy_waiting_for_fno"] > 0
    return await done(EXIT_OK, job_runs.PARTIAL if partial else job_runs.OK, out, None, session_text)


def _log_result(result: Dict[str, Any]) -> None:
    log.info(
        "desk check%s: users=%d open_trades=%d active_alerts=%d symbols=%d failed=%d no_prices=%d | "
        "exits stop=%d target=%d already=%d | strategy open=%d exits=%s not_checked=%d waiting_for_fno=%d | "
        "alerts fired=%d already=%d | latest_session=%s session=%s trades_checked=%d closed=%s errors=%d behind=%d",
        " (dry run)" if result["dry_run"] else "", result["users"], result["open_trades"], result["active_alerts"],
        result["symbols"], len(result["symbols_failed"]), len(result["symbols_without_prices"]),
        result["exits_stop"], result["exits_target"], result["exits_already_recorded"],
        result["open_strategy_trades"], result["strategy_exits"], result["strategy_not_checked"],
        result["strategy_waiting_for_fno"], result["alerts_fired"], result["alerts_already_recorded"],
        result["latest_session"], result["session"], result["trades_checked"], result["closed_by_reason"],
        result["errors"], result["open_trades_behind"],
    )
    if result.get("exits_failed"):
        log.warning("%d exit(s) could not be written and stay open for the next run: %s", result["exits_failed"],
                    ", ".join(result.get("exits_failed_ids") or []))
    if result["symbols_failed"]:
        log.warning("no prices could be read for: %s", ", ".join(result["symbols_failed"]))
    if result["symbols_without_prices"]:
        log.warning("the data platform has no end-of-day prices for: %s", ", ".join(result["symbols_without_prices"]))
    if result["strategy_not_checked"]:
        log.warning("%d strategy trade(s) were not checked: their prices could not be read", result["strategy_not_checked"])
    if result["strategy_waiting_for_fno"]:
        log.warning("%d strategy trade(s) wait for the next run: the F&O bhavcopy for %s is not in yet",
                    result["strategy_waiting_for_fno"], result["session"])
    if result["alerts_not_checked"]:
        log.warning("%d alert(s) were not checked: a source could not be read", result["alerts_not_checked"])
    if result["open_trades_behind"]:
        log.warning("%d open trade(s) were not checked through %s: %s", result["open_trades_behind"],
                    result["session"] or result["latest_session"], ", ".join(result["behind_trade_ids"]))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    p = argparse.ArgumentParser(description="Check every user's desk paper trades and price alerts against end-of-day bars")
    p.add_argument("--dry-run", action="store_true", help="Report what would close or fire; write nothing")
    p.add_argument("--require-bars", action="store_true",
                   help="Stop (exit 2 / 3) unless the expected session's end-of-day bars are in the data platform")
    p.add_argument("--skip-if-done", action="store_true",
                   help="Do nothing when a run already recorded 'ok' for the session (needs --require-bars)")
    args = p.parse_args()
    if args.skip_if_done and not args.require_bars:
        p.error("--skip-if-done needs --require-bars (it compares sessions)")

    try:
        code, outcome = asyncio.run(run_job(dry_run=args.dry_run, require_bars=args.require_bars,
                                            skip_if_done=args.skip_if_done))
    except Exception as exc:  # noqa: BLE001 — the lease or the heartbeat could not be written: the database failed
        log.exception("desk check failed before it could record a run: %r", exc)
        return EXIT_FAILED
    counts = outcome.get("counts")
    if isinstance(counts, dict) and "open_trades" in counts:
        _log_result(counts)
    status = outcome.get("status")
    if code == EXIT_FAILED:
        log.error("desk check failed (run %s): %s", outcome.get("run_id"), outcome.get("error"))
        if isinstance(counts, dict) and not counts.get("ok", True):
            log.error("no prices could be read for any trade or alert; nothing was checked")
    elif code in (EXIT_NO_BARS, EXIT_NO_SESSION, EXIT_LOCKED) or status == "skipped_done":
        log.warning("desk check skipped (%s, exit %d, run %s): %s", status, code, outcome.get("run_id"),
                    outcome.get("error") or f"session {outcome.get('session')} already done")
    else:
        log.info("desk check %s (run %s, session %s)", status, outcome.get("run_id"), outcome.get("session"))
    return code


if __name__ == "__main__":
    sys.exit(main())
