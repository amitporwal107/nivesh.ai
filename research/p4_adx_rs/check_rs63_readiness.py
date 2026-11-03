#!/usr/bin/env python3
r"""Readiness check for the pre-registered RS63 confirmation run (Phase 4.3).

Registration: docs/ai_research/P4_RS63_CONFIRMATION_PREREGISTRATION.md. The confirmation runs only once BOTH hold:
  * at least 60 new signal dates (strictly after 2026-10-09, the first study's last signal date) have a complete
    10-session outcome;
  * at least 20 of them fall in each regime (Nifty 50 above / not above its 200-session average).
If the regime condition is still not met after 2027-06-30, the registration says run anyway and report the result as
single-regime (status RUN_SINGLE_REGIME here; the 60-date condition still applies).

WHAT THIS SCRIPT READS, AND WHY IT CANNOT RUN THE STUDY EARLY
It reads two things only: the trading-session calendar and the Nifty 50 index close per session. It never reads stock
prices, scanner scores, features or forward returns, so it computes no outcome, no IC and no arm comparison. It only
counts dates. Launching the study (research/p4_adx_rs/run_study.py at commit 8ea7afb6, restricted to dates after
2026-10-09) stays a separate, deliberate step once this reports READY. Stdlib only, no database driver: the data comes in
as two CSV files exported with the read-only SELECTs that `--print-sql` prints.

Definitions, mirroring run_study.py (commit 8ea7afb6):
  * sessions   the study's calendar = the distinct dates of its price export (nidp.prices_eod_adjusted). On staging that
               set equals the distinct series-EQ dates of nidp.prices_eod (634 sessions, 2024-04-01..2026-10-26, checked
               2026-10-27); `--print-sql` exports the adjusted-table dates.
  * complete   session index i has a complete outcome when i + H <= len(sessions) - 1 (H = 10: entry at the next open,
               exit at the close of session i + H), i.e. run_study.py's `last_signal = len(sessions) - 1 - H` and
               `outcomes.split_of` for the final split.
  * regime     "up" when the Nifty 50 close on the date is STRICTLY above the mean of the 200 session closes ending on
               that date (run_study.py: `nifty_close[i] > nifty_sma200[i]`, pandas `rolling(200).mean()` over the session
               calendar), otherwise "down". If the date's close or any of the 199 closes before it is missing, or there are
               fewer than 200 sessions up to the date, the regime is UNKNOWN (pandas gives NaN there): the date is counted
               and listed under `regime_unknown`, never guessed, and does not count toward either threshold. (run_study.py
               itself refuses to run while the Nifty 50 series has a gap.)
  * not checked here: the study also drops a date with fewer than 30 scorable stocks (MIN_NAMES); that needs stock data,
    which this script deliberately does not read. On staging every session has ~500+ scorable names.

Exit codes: 0 READY or RUN_SINGLE_REGIME · 1 NOT_READY · 2 data error (unreadable / empty / unordered input).

Usage
    python research/p4_adx_rs/check_rs63_readiness.py --print-sql
    python research/p4_adx_rs/check_rs63_readiness.py --csv-dir DIR [--as-of YYYY-MM-DD] [--json]
DIR holds sessions.csv (column as_of_date) and nifty50.csv (columns as_of_date, close_price).

Cron-ready command (NOT installed; installing it is an owner decision). Monthly, on the 1st at 09:15 IST, on the NIDP VM
where the warehouse runs. Both SELECTs are read-only, the script only prints a report, and nothing here starts the study:

    CRON_TZ=Asia/Kolkata
    15 9 1 * *  root  cd /opt/nidp/dev-repo/nivesh.ai && D=$(mktemp -d) && \
      Q=research/p4_adx_rs/check_rs63_readiness.py && PSQL="docker exec -i <warehouse container> psql -U <read-only role> -d <db> -q" && \
      $PSQL -c "\copy ($(python3 $Q --print-sql --part sessions)) TO STDOUT WITH CSV HEADER" > $D/sessions.csv && \
      $PSQL -c "\copy ($(python3 $Q --print-sql --part nifty50)) TO STDOUT WITH CSV HEADER" > $D/nifty50.csv && \
      python3 $Q --csv-dir $D >> /var/log/nidp/rs63_readiness.log 2>&1; rm -rf $D

The container, role and database are filled in at install time (the NIDP VM's cron file runs services the same way). From
the app VM the two SELECTs can be run through ~/.config/nivesh/nidp-psql.sh instead. A READY (or RUN_SINGLE_REGIME) line in
the log is the signal for a person to run the registered study; the exit code (0) can also page its owner.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

CUTOFF = date(2026, 10, 9)       # last signal date of the first study; confirmation dates are strictly after it
H = 10                           # sessions held (run_study.py H)
SMA = 200                        # regime average length, sessions
MIN_DATES = 60
MIN_PER_REGIME = 20
DEADLINE = date(2027, 6, 30)     # after this, a short regime no longer blocks: run as single-regime

SESSIONS_SQL = ("SELECT DISTINCT as_of_date FROM nidp.prices_eod_adjusted "
                "WHERE as_of_date >= DATE '2024-04-01' ORDER BY as_of_date")
NIFTY50_SQL = ("SELECT as_of_date, close_price FROM nidp.index_eod "
               "WHERE index_name = 'Nifty 50' AND as_of_date >= DATE '2024-04-01' ORDER BY as_of_date")


class DataError(ValueError):
    """The inputs cannot be counted (empty, unparseable or unordered)."""


def readiness(sessions: Sequence[date], nifty_close: Dict[date, Optional[float]], *, as_of: date,
              cutoff: date = CUTOFF, horizon: int = H, sma: int = SMA, min_dates: int = MIN_DATES,
              min_per_regime: int = MIN_PER_REGIME, deadline: date = DEADLINE) -> Dict:
    """Count the confirmation's signal dates and their regimes. Pure: no I/O, no stock data."""
    if not sessions:
        raise DataError("the session calendar is empty")
    if any(b <= a for a, b in zip(sessions, sessions[1:])):
        raise DataError("the session calendar must be strictly ascending with no duplicates")
    last_signal = len(sessions) - 1 - horizon
    closes = [nifty_close.get(d) for d in sessions]

    def regime(i: int) -> Optional[str]:
        if i + 1 < sma:
            return None
        window = closes[i + 1 - sma:i + 1]
        if any(c is None for c in window):
            return None
        return "up" if closes[i] > sum(window) / sma else "down"

    after = [i for i, d in enumerate(sessions) if d > cutoff]
    complete = [i for i in after if i <= last_signal]
    pending = [sessions[i].isoformat() for i in after if i > last_signal]
    counts = {"up": 0, "down": 0}
    unknown: List[str] = []
    for i in complete:
        r = regime(i)
        if r is None:
            unknown.append(sessions[i].isoformat())
        else:
            counts[r] += 1
    known = counts["up"] + counts["down"]
    short = {k: max(min_per_regime - v, 0) for k, v in counts.items()}
    need_dates = max(min_dates - known, 0)
    if need_dates == 0 and not any(short.values()):
        status = "READY"
    elif need_dates == 0 and as_of > deadline:
        status = "RUN_SINGLE_REGIME"
    else:
        status = "NOT_READY"
    reasons = []
    if need_dates:
        reasons.append(f"{need_dates} more signal date(s) with a complete outcome and a known regime are needed "
                       f"({known} of {min_dates})")
    for k in ("up", "down"):
        if short[k]:
            reasons.append(f"{short[k]} more '{k}' date(s) are needed ({counts[k]} of {min_per_regime})")
    if status == "RUN_SINGLE_REGIME":
        reasons.append(f"the deadline {deadline.isoformat()} has passed: run as registered and report the result as "
                       "single-regime")
    if unknown:
        reasons.append(f"{len(unknown)} complete date(s) have no defined regime (a Nifty 50 close is missing in their "
                       "200-session window); run_study.py refuses to run until that gap is filled")
    return {
        "status": status, "as_of": as_of.isoformat(), "cutoff_exclusive": cutoff.isoformat(), "horizon_sessions": horizon,
        "calendar": {"sessions": len(sessions), "first": sessions[0].isoformat(), "last": sessions[-1].isoformat()},
        "signal_dates_after_cutoff": len(after),
        "complete_dates": len(complete),
        "complete_dates_known_regime": known,
        "by_regime": counts,
        "regime_unknown": {"count": len(unknown), "dates": unknown},
        "first_complete": sessions[complete[0]].isoformat() if complete else None,
        "last_complete": sessions[complete[-1]].isoformat() if complete else None,
        "pending_outcome": {"count": len(pending), "dates": pending},
        "thresholds": {"min_dates": min_dates, "min_per_regime": min_per_regime, "deadline": deadline.isoformat()},
        "reasons": reasons,
        "reads": "sessions and Nifty 50 closes only; no stock prices, scores or outcomes",
    }


def _parse_day(s: str, where: str) -> date:
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError as e:
        raise DataError(f"{where}: bad date {s!r}") from e


def load_csv_dir(d: Path):
    try:
        with open(d / "sessions.csv", newline="") as f:
            sessions = [_parse_day(r["as_of_date"], "sessions.csv") for r in csv.DictReader(f)]
        closes: Dict[date, Optional[float]] = {}
        with open(d / "nifty50.csv", newline="") as f:
            for r in csv.DictReader(f):
                v = (r.get("close_price") or "").strip()
                closes[_parse_day(r["as_of_date"], "nifty50.csv")] = float(v) if v else None
    except (OSError, KeyError) as e:
        raise DataError(f"cannot read the CSV inputs in {d}: {e!r}") from e
    except ValueError as e:
        raise DataError(f"bad number in nifty50.csv: {e}") from e
    return sessions, closes


def summary(r: Dict) -> str:
    lines = [f"RS63 confirmation readiness: {r['status']} (as of {r['as_of']})",
             f"  calendar {r['calendar']['first']}..{r['calendar']['last']} ({r['calendar']['sessions']} sessions); "
             f"signal dates after {r['cutoff_exclusive']}: {r['signal_dates_after_cutoff']}",
             f"  complete {r['horizon_sessions']}-session outcomes: {r['complete_dates']} "
             f"(known regime {r['complete_dates_known_regime']}: up {r['by_regime']['up']}, down {r['by_regime']['down']}; "
             f"unknown {r['regime_unknown']['count']})",
             f"  awaiting their outcome: {r['pending_outcome']['count']}",
             f"  thresholds: >= {r['thresholds']['min_dates']} dates, >= {r['thresholds']['min_per_regime']} per regime; "
             f"deadline {r['thresholds']['deadline']}"]
    lines += [f"  - {x}" for x in r["reasons"]]
    lines.append("  (counts dates only; the study is not run by this check)")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--csv-dir", type=Path)
    ap.add_argument("--print-sql", action="store_true", help="print the read-only export SELECTs and exit")
    ap.add_argument("--part", choices=("sessions", "nifty50"), help="with --print-sql: print one SELECT only")
    ap.add_argument("--as-of", help="the run date for the deadline check (default: today)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.print_sql:
        if a.part != "nifty50":
            print(("-- sessions.csv\n" if a.part is None else "") + SESSIONS_SQL)
        if a.part != "sessions":
            print(("-- nifty50.csv\n" if a.part is None else "") + NIFTY50_SQL)
        return 0
    if a.csv_dir is None:
        ap.error("--csv-dir is required unless --print-sql")
    try:
        as_of = date.fromisoformat(a.as_of) if a.as_of else date.today()
        sessions, closes = load_csv_dir(a.csv_dir)
        r = readiness(sessions, closes, as_of=as_of)
    except (DataError, ValueError) as e:
        print(f"RS63 confirmation readiness: DATA_ERROR: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1) if a.json else summary(r))
    return 0 if r["status"] in ("READY", "RUN_SINGLE_REGIME") else 1


if __name__ == "__main__":
    sys.exit(main())
