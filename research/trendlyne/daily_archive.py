"""Daily Trendlyne archive run (cron). Refreshes expired data for a universe through the Redis cache, which appends
every fetched response to the archive, then writes the day's screen.

Default budget (fits the Pro plan): bulk parameters every run (~1 call per 10 stocks: prices, technicals, scores,
insider buys/sells, delivery; shareholding/results refresh when their cache expires), and the per-stock views
(overview incl. ASM status, events, bulk/block deals, news) on --views-days (default Saturday). Set --views-days
0-6 for daily per-stock views (~4 calls per stock per day).

usage: python daily_archive.py UNIVERSE_CSV REPORTS_DIR [--views-days 5] [--max-calls 250]
"""
import argparse
import datetime as dt
import os
import subprocess
import sys

import pandas as pd

import tl_cache as T
from screen_list import P2, P50
from tl_client import TLClient

ap = argparse.ArgumentParser()
ap.add_argument("universe")
ap.add_argument("reports")
ap.add_argument("--views-days", default="5", help="weekdays (0=Mon) for per-stock views, e.g. '5' or '0,1,2,3,4,5'")
ap.add_argument("--max-calls", type=int, default=250, help="stop this run after this many calls")
a = ap.parse_args()
now = dt.datetime.now(T.IST)
U = pd.read_csv(a.universe)
c = T.TLCache(TLClient(), T.RedisStore(), daily_cap=int(os.environ.get("TL_DAILY_CALL_CAP", "300")))
c.get_params(U.code.tolist(), P50 + P2)
views = now.weekday() in {int(x) for x in a.views_days.split(",") if x.strip()}
if views:
    for code in U.code:
        if c.stats["calls"] >= a.max_calls:
            print(f"stopping per-stock views at the run limit ({a.max_calls} calls)")
            break
        for fn, kind in ((c.overview, "overview"), (c.overview, "events"), (c.ownership, "bulblockdeal"), (c.overview, "news")):
            try:
                fn(code, kind)
            except T.BudgetExceeded as e:
                print("STOP:", e)
                break
            except Exception as e:  # one stock failing must not stop the archive; it is retried next run
                print(f"{code} {kind}: {type(e).__name__}: {str(e)[:150]}")
print(f"{now:%Y-%m-%d %H:%M} views={views} stats={dict(c.stats, unmapped=sorted(c.stats.get('unmapped', [])))} "
      f"calls_today={c.calls_today()}")
out = os.path.join(a.reports, f"{now:%Y-%m-%d}")
sys.exit(subprocess.call([sys.executable, os.path.join(os.path.dirname(__file__), "screen_list.py"), a.universe, out,
                          "--as-of", f"{now:%Y-%m-%d}"]))
