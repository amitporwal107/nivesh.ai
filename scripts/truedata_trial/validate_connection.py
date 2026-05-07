"""Day 1–2 trial validation: prove TrueData login + tick subscription works.

Run:
    export TRUEDATA_USERNAME=trial969
    export TRUEDATA_PASSWORD=...
    python scripts/truedata_trial/validate_connection.py --duration 120

Outputs ticks/greeks/bidask to scripts/truedata_trial/out/ as JSONL and
prints a coverage + latency summary on exit.

Trial expires 2026-05-14. Auto-reconnect was removed in truedata 6.0.4 —
we handle reconnect ourselves with exponential backoff.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from truedata import TD_live
except ImportError:
    print("Install: pip install -r scripts/truedata_trial/requirements.txt", file=sys.stderr)
    sys.exit(2)

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

CASH_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
FUTURES_SYMBOLS = ["NIFTY-I", "BANKNIFTY-I", "FINNIFTY-I"]
OPTION_CHAIN_SYMBOL = "NIFTY"


def next_monthly_expiry(today: date) -> date:
    """Last Thursday of the current month; rolls to next month if past."""
    year, month = today.year, today.month
    if month == 12:
        first_next = date(year + 1, 1, 1)
    else:
        first_next = date(year, month + 1, 1)
    last_day = first_next - timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7  # 3 == Thursday
    expiry = last_day - timedelta(days=offset)
    if expiry < today:
        return next_monthly_expiry(first_next)
    return expiry


class TickRecorder:
    def __init__(self, out_path: Path) -> None:
        self.path = out_path
        self.fh = out_path.open("a", buffering=1)
        self.tick_count: Counter[str] = Counter()
        self.greek_count: Counter[str] = Counter()
        self.bidask_count: Counter[str] = Counter()
        self.latencies_ms: list[float] = []
        self.first_tick_at: dict[str, float] = {}
        self.last_tick_at: dict[str, float] = {}

    def write(self, kind: str, payload: dict[str, Any]) -> None:
        record = {"received_at": time.time(), "kind": kind, **payload}
        self.fh.write(json.dumps(record, default=str) + "\n")

    def on_trade(self, tick: Any) -> None:
        sym = getattr(tick, "symbol", "?")
        now = time.time()
        self.tick_count[sym] += 1
        self.first_tick_at.setdefault(sym, now)
        self.last_tick_at[sym] = now
        ts = getattr(tick, "timestamp", None)
        if isinstance(ts, datetime):
            ts_epoch = ts.replace(tzinfo=timezone.utc).timestamp() if ts.tzinfo is None else ts.timestamp()
            self.latencies_ms.append((now - ts_epoch) * 1000.0)
        self.write("trade", {
            "symbol": sym,
            "ltp": getattr(tick, "ltp", None),
            "ltq": getattr(tick, "ltq", None),
            "ttq": getattr(tick, "ttq", None),
            "oi": getattr(tick, "oi", None),
            "oi_change": getattr(tick, "oi_change", None),
            "timestamp": getattr(tick, "timestamp", None),
        })

    def on_bidask(self, ba: Any) -> None:
        sym = getattr(ba, "symbol", "?")
        self.bidask_count[sym] += 1
        self.write("bidask", {
            "symbol": sym,
            "best_bid_price": getattr(ba, "best_bid_price", None),
            "best_bid_qty": getattr(ba, "best_bid_qty", None),
            "best_ask_price": getattr(ba, "best_ask_price", None),
            "best_ask_qty": getattr(ba, "best_ask_qty", None),
        })

    def on_greek(self, g: Any) -> None:
        sym = getattr(g, "symbol", "?")
        self.greek_count[sym] += 1
        self.write("greek", {
            "symbol": sym,
            "iv": getattr(g, "iv", None),
            "delta": getattr(g, "delta", None),
            "gamma": getattr(g, "gamma", None),
            "theta": getattr(g, "theta", None),
            "vega": getattr(g, "vega", None),
            "rho": getattr(g, "rho", None),
        })

    def summarize(self) -> dict[str, Any]:
        def pct(v: list[float], q: float) -> float | None:
            if not v:
                return None
            return statistics.quantiles(v, n=100)[int(q) - 1] if len(v) >= 100 else max(v)

        return {
            "trade_ticks_total": sum(self.tick_count.values()),
            "trade_ticks_per_symbol": dict(self.tick_count),
            "bidask_total": sum(self.bidask_count.values()),
            "greek_total": sum(self.greek_count.values()),
            "greek_per_symbol": dict(self.greek_count),
            "latency_ms_p50": statistics.median(self.latencies_ms) if self.latencies_ms else None,
            "latency_ms_p95": pct(self.latencies_ms, 95),
            "latency_ms_max": max(self.latencies_ms) if self.latencies_ms else None,
            "symbols_with_data": sorted(self.tick_count.keys()),
        }

    def close(self) -> None:
        self.fh.close()


def connect_with_retry(username: str, password: str, port: int | None, max_attempts: int = 5) -> TD_live:
    """truedata 6.0.4+ removed auto-reconnect; we wrap login attempts ourselves.

    Also: the SDK swallows auth errors into its own logger and retries indefinitely
    in a daemon thread instead of raising. We tee that logger to a buffer and bail
    fast if we see an auth failure.
    """
    auth_buffer: list[str] = []

    class _AuthSniffer(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            msg = self.format(record)
            auth_buffer.append(msg)

    sniffer = _AuthSniffer(level=logging.ERROR)
    root = logging.getLogger()
    root.addHandler(sniffer)
    try:
        delay = 2.0
        for attempt in range(1, max_attempts + 1):
            try:
                kwargs: dict[str, Any] = {}
                if port:
                    kwargs["live_port"] = port
                td = TD_live(username, password, **kwargs)
                # Wait briefly to give the SDK's background thread a chance to surface auth errors.
                deadline = time.time() + 8.0
                while time.time() < deadline:
                    if any("Invalid User Credentials" in m or "authentication" in m.lower()
                           for m in auth_buffer):
                        raise PermissionError(
                            "TrueData rejected credentials — check welcome email for the assigned "
                            "tdwsp_*/tdtraining_* username and dedicated API password."
                        )
                    time.sleep(0.5)
                return td
            except PermissionError:
                raise
            except Exception as e:  # noqa: BLE001
                logging.warning("Login attempt %d/%d failed: %s", attempt, max_attempts, e)
                if attempt == max_attempts:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError("unreachable")
    finally:
        root.removeHandler(sniffer)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=int, default=120, help="Seconds to record before exit")
    p.add_argument("--port", type=int, default=int(os.environ.get("TRUEDATA_LIVE_PORT", "0")) or None)
    p.add_argument("--expiry", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                   default=None, help="Option chain expiry YYYY-MM-DD (default: next monthly)")
    p.add_argument("--no-options", action="store_true", help="Skip option chain subscription")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    username = os.environ.get("TRUEDATA_USERNAME")
    password = os.environ.get("TRUEDATA_PASSWORD")
    if not (username and password):
        logging.error("Set TRUEDATA_USERNAME and TRUEDATA_PASSWORD env vars")
        return 2

    expiry = args.expiry or next_monthly_expiry(date.today())
    logging.info("Connecting as %s (port=%s, option_expiry=%s)", username, args.port, expiry)

    td = connect_with_retry(username, password, args.port)

    out_path = OUT_DIR / f"ticks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    rec = TickRecorder(out_path)

    @td.trade_callback
    def _t(t: Any) -> None: rec.on_trade(t)

    @td.bidask_callback
    def _b(b: Any) -> None: rec.on_bidask(b)

    @td.greek_callback
    def _g(g: Any) -> None: rec.on_greek(g)

    symbols = CASH_SYMBOLS + FUTURES_SYMBOLS
    logging.info("Subscribing %d symbols: %s", len(symbols), symbols)
    td.start_live_data(symbols)

    chain = None
    if not args.no_options:
        logging.info("Starting NIFTY option chain (expiry=%s, chain_length=20, greek=True)", expiry)
        try:
            chain = td.start_option_chain(
                OPTION_CHAIN_SYMBOL,
                datetime.combine(expiry, datetime.min.time()),
                chain_length=20,
                bid_ask=True,
                greek=True,
            )
        except Exception as e:  # noqa: BLE001
            logging.warning("Option chain subscription failed: %s — continuing with cash+futures only", e)

    stop_at = time.time() + args.duration

    def _sigint(_sig: int, _frm: Any) -> None:
        logging.info("Ctrl+C — stopping early")
        nonlocal_stop[0] = True

    nonlocal_stop = [False]
    signal.signal(signal.SIGINT, _sigint)

    last_log = 0.0
    while time.time() < stop_at and not nonlocal_stop[0]:
        time.sleep(1.0)
        if time.time() - last_log > 10:
            logging.info("alive — trade=%d bidask=%d greek=%d unique_symbols=%d",
                         sum(rec.tick_count.values()),
                         sum(rec.bidask_count.values()),
                         sum(rec.greek_count.values()),
                         len(rec.tick_count))
            last_log = time.time()

    logging.info("Shutting down")
    try:
        td.stop_live_data(symbols)
    except Exception as e:  # noqa: BLE001
        logging.warning("stop_live_data: %s", e)
    if chain is not None:
        try:
            chain.stop_option_chain()
        except Exception as e:  # noqa: BLE001
            logging.warning("stop_option_chain: %s", e)
    try:
        td.disconnect()
    except Exception as e:  # noqa: BLE001
        logging.warning("disconnect: %s", e)

    rec.close()
    summary = rec.summarize()
    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, default=str))

    print("\n=== TRIAL VALIDATION SUMMARY ===")
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nRaw stream: {out_path}")
    print(f"Summary:    {summary_path}")

    expected = set(CASH_SYMBOLS + FUTURES_SYMBOLS)
    got = set(rec.tick_count.keys())
    missing = expected - got
    if missing:
        print(f"\n⚠ Symbols with zero ticks: {sorted(missing)}")
        print("  Likely causes: market closed, symbol not in trial subscription tier, or wrong format.")
    if not rec.greek_count and not args.no_options:
        print("\n⚠ Zero Greeks received — option chain subscription may have failed or trial tier excludes greeks.")
    if rec.latencies_ms and statistics.median(rec.latencies_ms) > 1000:
        print(f"\n⚠ High median latency: {statistics.median(rec.latencies_ms):.0f}ms — investigate before paid commit.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
