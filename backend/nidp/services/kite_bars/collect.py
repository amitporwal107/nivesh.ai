"""Fetch Kite minute bars for a symbol universe and write them to nidp.intraday_bars.

Every attempted (symbol, interval, window) lands in nidp.intraday_ingest_log with OK/EMPTY/
ERROR, so a missing bar is always attributable: never fetched, fetched-but-no-trades, or
failed. Re-running is safe — bars upsert on their primary key and the log is keyed by run_id.

Rate limit: Kite allows ~3 req/s on historical data; REQ_INTERVAL paces below that.
"""
from __future__ import annotations

import argparse
import csv
import io
import subprocess
import time
import uuid
from datetime import date, datetime, timedelta

from .client import Instrument, candles, nse_equity_instruments, windows

CONTAINER = "nidp-postgres-staging"
PSQL = ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "nidp_staging", "-d", "nidp_staging"]
SOURCE_VERSION = "kite-connect-v3"
REQ_INTERVAL = 0.35          # seconds between historical calls (~2.8 req/s, under the 3/s cap)
MAX_RETRIES = 3


def _retry(fn, *a, **kw):
    """Call fn with bounded backoff; raise the last error if every attempt fails."""
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 — the reason is recorded per symbol in the log
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def collect(access_token: str, symbols: list[str], start: date, end: date,
            interval: str = "minute", run_id: str = "") -> dict:
    """Backfill [start, end] for `symbols`. Returns a per-status tally."""
    run_id = run_id or f"kite-{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    universe = {i.symbol: i for i in nse_equity_instruments(access_token)}
    tally = {"OK": 0, "EMPTY": 0, "ERROR": 0, "UNKNOWN_SYMBOL": 0, "rows": 0, "run_id": run_id}

    for sym in symbols:
        inst: Instrument | None = universe.get(sym)
        if inst is None:
            tally["UNKNOWN_SYMBOL"] += 1
            _log(sym, interval, start, end, "ERROR", 0, "symbol not in NSE EQ instruments", run_id)
            continue
        for w_start, w_end in windows(start, end, interval):
            try:
                rows = _retry(candles, access_token, inst.token, w_start, w_end, interval)
                time.sleep(REQ_INTERVAL)
            except Exception as e:  # noqa: BLE001
                tally["ERROR"] += 1
                _log(sym, interval, w_start, w_end, "ERROR", 0, f"{type(e).__name__}: {e}"[:500], run_id)
                continue
            if not rows:
                tally["EMPTY"] += 1
                _log(sym, interval, w_start, w_end, "EMPTY", 0, None, run_id)
                continue
            n = _write(inst, interval, rows)
            tally["OK"] += 1
            tally["rows"] += n
            _log(sym, interval, w_start, w_end, "OK", n, None, run_id)
    return tally


def _psql(sql: str, stdin: str = "") -> str:
    """Run one statement through psql in the staging container (the pattern store.py uses —
    this repo has no Python Postgres driver installed)."""
    cmd = ["docker", "exec", "-i", CONTAINER, *PSQL, "-c", sql]
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()[:400]}")
    return r.stdout


BAR_COLS = ["instrument_token", "symbol", "exchange", "bar_ts", "interval",
            "open_price", "high_price", "low_price", "close_price", "volume", "source_version"]


def _write(inst: Instrument, interval: str, rows: list[dict]) -> int:
    """Upsert bars: COPY into a temp table, then merge (COPY itself cannot ON CONFLICT)."""
    tmp = f"tmp_bars_{uuid.uuid4().hex[:8]}"
    payload = [(inst.token, inst.symbol, inst.exchange, r["date"].isoformat(), interval,
                r["open"], r["high"], r["low"], r["close"], r.get("volume"), SOURCE_VERSION) for r in rows]
    # temp tables do not survive separate psql invocations, so do it in one session
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for t in payload:
        w.writerow(["" if v is None else v for v in t])
    script = (
        f"CREATE TEMP TABLE {tmp} (LIKE nidp.intraday_bars INCLUDING DEFAULTS);\n"
        f"COPY {tmp} ({','.join(BAR_COLS)}) FROM STDIN WITH (FORMAT csv);\n"
        f"{buf.getvalue()}\\.\n"
        f"INSERT INTO nidp.intraday_bars ({','.join(BAR_COLS)}) "
        f"SELECT {','.join(BAR_COLS)} FROM {tmp} "
        f"ON CONFLICT (instrument_token, interval, bar_ts) DO UPDATE SET "
        f"open_price=EXCLUDED.open_price, high_price=EXCLUDED.high_price, "
        f"low_price=EXCLUDED.low_price, close_price=EXCLUDED.close_price, "
        f"volume=EXCLUDED.volume, ingested_at=NOW();\n"
    )
    cmd = ["docker", "exec", "-i", CONTAINER, *PSQL]
    r = subprocess.run(cmd, input=script, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"bar upsert failed: {r.stderr.strip()[:400]}")
    return len(rows)


def _log(symbol, interval, w_start, w_end, status, rows_written, error_text, run_id) -> None:
    """Auditable ingestion record. Never raises — a logging failure must not lose bars."""
    err = (error_text or "").replace("'", "''")[:500]
    sql = (
        "INSERT INTO nidp.intraday_ingest_log "
        "(symbol, interval, window_start, window_end, status, rows_written, error_text, source_version, run_id) "
        f"VALUES ('{symbol}','{interval}','{w_start}','{w_end}','{status}',{rows_written},"
        f"{'NULL' if not err else chr(39)+err+chr(39)},'{SOURCE_VERSION}','{run_id}') "
        "ON CONFLICT (symbol, interval, window_start, window_end, run_id) DO NOTHING;")
    try:
        _psql(sql)
    except Exception as e:  # noqa: BLE001 — surfaced on stderr, never fatal
        print(f"WARN: ingest_log write failed for {symbol}: {type(e).__name__}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backfill Kite intraday bars into nidp.intraday_bars")
    p.add_argument("--symbols", required=True, help="comma-separated, or a path to a newline-delimited file")
    p.add_argument("--start", required=True, type=date.fromisoformat)
    p.add_argument("--end", default=str(date.today()), type=date.fromisoformat)
    p.add_argument("--interval", default="minute", choices=list(__import__("nidp.services.kite_bars.client",
                   fromlist=["MAX_DAYS"]).MAX_DAYS))
    p.add_argument("--token-file", required=True, help="file holding the daily access_token (never echoed)")
    a = p.parse_args(argv)

    import os
    syms = ([s.strip() for s in open(a.symbols) if s.strip()] if os.path.exists(a.symbols)
            else [s.strip() for s in a.symbols.split(",") if s.strip()])
    token = open(a.token_file).read().strip()
    if not token:
        raise SystemExit("access token file is empty — run the login handshake first")

    tally = collect(token, syms, a.start, a.end, a.interval)
    print({k: v for k, v in tally.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
