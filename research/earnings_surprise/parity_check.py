#!/usr/bin/env python3
"""Data test: the study's offline replay of the results expectation equals the live DaaS endpoint for real past meetings.

    python parity_check.py <data_dir> <events.csv> [n]

Run inside the staging backend container. For n events from the two primary seasons (a fixed, evenly spaced pick, no
randomness), it calls GET /v1/desk/events-calendar/expectation?symbol&date on the live DaaS (sequentially, 0.5 s apart) and
compares, for PAT and revenue: the expected mid, the filed value and `reliable`. The band (low/high) is NOT compared: the
endpoint calibrates it on every tested quarter, the study on quarters ≤ 2026-06-30 (pre-registration §4.1).
"""
from __future__ import annotations

import asyncio
import csv
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, os.environ.get("BACKEND", "/app/backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("LIVE_SCORING", "/tmp/es/live_scoring.py")
import build_dataset as bd  # noqa: E402
from nidp.services.daas_api.routers import desk_expectation as de  # noqa: E402
from services.copilot_tools.daas_client import get_raw  # noqa: E402


async def main(data: Path, events_csv: Path, n: int) -> int:
    rows = [r for r in csv.DictReader(open(events_csv)) if r["season"] in ("2026-03-31", "2026-06-30")]
    pick = [rows[int(i * (len(rows) - 1) / max(1, n - 1))] for i in range(n)]
    store = de.build_store(bd.load_quarters(data / "quarters.csv"))
    recs = {m: [r for r in de.run_backtest(store, m) if r["target"] <= bd.CAL_FREEZE] for m in ("revenue", "pat")}
    models = {"store": store, "records": recs, "cal": {m: de.Calibration(recs[m], m) for m in recs},
              "universe": {"revenue": {"n": 0}, "pat": {"n": 0}}}
    cal = {(r["symbol"], r["event_date"]): r for r in csv.DictReader(open(data / "calendar.csv"))}
    ok = bad = 0
    for e in pick:
        ev = cal[(e["symbol"], e["event_date"])]
        mine = de.answer(models, e["symbol"], date.fromisoformat(e["event_date"]), ev["purpose"], bd.TODAY, [], None, None)
        status, live = await get_raw("/desk/events-calendar/expectation", {"symbol": e["symbol"], "date": e["event_date"]})
        if status != 200 or not isinstance(live, dict):
            print(f"{e['symbol']} {e['event_date']}: DaaS HTTP {status}")
            bad += 1
            continue
        lm = {m["key"]: m for m in live.get("metrics", [])}
        om = {m["key"]: m for m in mine["metrics"]}
        line = []
        same = True
        for k in ("pat", "revenue"):
            a, b = om[k], lm.get(k, {})
            fields = (((a.get("expected") or {}).get("mid"), (b.get("expected") or {}).get("mid")),
                      ((a.get("filed") or {}).get("value"), (b.get("filed") or {}).get("value")),
                      (a.get("reliable"), b.get("reliable")))
            same = same and all(x == y for x, y in fields)
            line.append(f"{k}: mid {fields[0][0]} vs {fields[0][1]}, filed {fields[1][0]} vs {fields[1][1]}, reliable {fields[2][0]} vs {fields[2][1]}")
        print(("MATCH " if same else "DIFF  ") + f"{e['symbol']} {e['event_date']} | " + " | ".join(line))
        ok += same
        bad += not same
        time.sleep(0.5)
    print(f"parity: {ok} match, {bad} differ, of {len(pick)}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 12)))
