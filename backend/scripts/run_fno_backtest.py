#!/usr/bin/env python3
"""run_fno_backtest.py: Stage A backtest of the F&O candidate ranking and its thresholds on the real data platform. READ ONLY.

Fetches, through the app's data-platform client (nothing is written anywhere except the report file):
  - the trading calendar (the engineered features' sessions),
  - the build-up scan for every session (DaaS /desk/fno-buildup?date=D, the classification the Lab shows),
  - the engineered features and the split/bonus-adjusted prices for every symbol that appears.
Then runs services.fno_backtest.study.run_backtest and writes the JSON report.

    docker exec -w /app/backend nivesh-staging-app-backend python -m scripts.run_fno_backtest --out /tmp/fno_backtest.json --code-version <sha>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

log = logging.getLogger("fno_backtest")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

CONCURRENCY = 6
CHUNK = 250                       # DaaS bulk reads take at most 300 symbols


async def fetch_scans(sessions: List[str]) -> Dict[str, Dict[str, Any]]:
    from routes import fno as route
    sem = asyncio.Semaphore(CONCURRENCY)
    out: Dict[str, Dict[str, Any]] = {}
    failed: List[str] = []

    async def one(day: str) -> None:
        async with sem:
            for attempt in range(3):
                try:
                    body = await route._daas("/desk/fno-buildup", {"date": day}, "stock futures")
                    if isinstance(body.get("rows"), list) and body.get("as_of") == day:
                        out[day] = body
                    else:
                        failed.append(day)
                    return
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        failed.append(day)
                        log.warning("scan %s failed (%s)", day, type(e).__name__)
                    await asyncio.sleep(1.0 + attempt)

    await asyncio.gather(*(one(d) for d in sessions))
    if failed:
        log.warning("%d sessions have no scan (they are skipped, not filled): %s", len(failed), sorted(failed)[:10])
    return out


async def fetch_bulk(fn, symbols: List[str], start: str, end: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        got = await fn(chunk, start=start, end=end, timeout=120.0)
        out.update({str(k).upper(): v for k, v in (got or {}).items()})
    return out


async def main(out_path: str, code_version: str) -> None:
    from services.copilot_tools import daas_client
    from services.fno_backtest import study

    sessions = await daas_client.get_trading_calendar("2025-10-01", datetime.now(timezone.utc).date().isoformat(), timeout=60.0)
    if len(sessions) < 60:
        raise SystemExit(f"only {len(sessions)} sessions from the data platform: refusing to run")
    log.info("sessions %s .. %s (%d)", sessions[0], sessions[-1], len(sessions))
    scans = await fetch_scans(sessions)
    symbols = sorted({str(r["symbol"]).upper() for b in scans.values() for r in b["rows"] if r.get("symbol")})
    log.info("scans for %d sessions, %d distinct symbols", len(scans), len(symbols))
    features = await fetch_bulk(daas_client.get_features_bulk, symbols, sessions[0], sessions[-1])
    adjusted = await fetch_bulk(daas_client.get_adjusted_prices_bulk, symbols, sessions[0], sessions[-1])
    log.info("features for %d symbols, adjusted prices for %d", len(features), len(adjusted))
    report = study.run_backtest({"sessions": sessions, "scans": scans, "features": features, "adjusted": adjusted},
                                code_version=code_version, generated_at=datetime.now(timezone.utc).isoformat())
    Path(out_path).write_text(json.dumps(report, indent=1, default=str))
    log.info("report written: %s | experiment %s | status %s | hash %s", out_path, report.get("experiment_id"), report.get("status"), (report.get("report_hash") or "")[:16])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Stage A backtest of the F&O candidate ranking and thresholds (read only)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--code-version", default="")
    a = ap.parse_args()
    asyncio.run(main(a.out, a.code_version))
