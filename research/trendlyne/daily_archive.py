"""Daily Trendlyne archive run (cron, Max plan). Only data that changes daily is fetched daily; quarterly and event
data is refetched for a stock only when its news shows a new filing or event (7-day expiry as a safety net).
Every fetched response is appended to the archive by TLCache; the run ends by writing the day's screen.

Per stock per run: news (the change trigger) + overview (ASM status, technicals, valuation) + bulk/block deals
= 3 calls; bulk parameters ~1 call per 10 stocks (daily fields only, plus invalidated quarterly fields);
events and quarterly data only when triggered. ~155 calls/day for 50 stocks.

usage: python daily_archive.py UNIVERSE_CSV REPORTS_DIR [--max-calls 400]
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
ap.add_argument("--max-calls", type=int, default=400, help="stop this run after this many calls")
a = ap.parse_args()
now = dt.datetime.now(T.IST)
U = pd.read_csv(a.universe)
c = T.TLCache(TLClient(), T.RedisStore())
triggered = {"filing": [], "event": []}
errors = []


def safe(fn, *args):
    if c.stats["calls"] >= a.max_calls:
        raise T.BudgetExceeded(f"run limit {a.max_calls} calls")
    try:
        return fn(*args)
    except T.BudgetExceeded:
        raise
    except Exception as e:  # one stock failing must not stop the archive; it is retried next run
        errors.append(f"{args[0]} {args[-1]}: {type(e).__name__}: {str(e)[:120]}")
        return None


try:
    for code in U.code:  # 1) news: daily, and the trigger for quarterly / event refetches
        news = safe(c.overview, code, "news")
        if news is None:
            continue
        seen_key = f"{T.PREFIX}newsseen:{code.upper()}"
        since = c.store.get(seen_key) or str((now - dt.timedelta(days=3)).date())
        hits, newest = T.news_triggers(news, since)
        for h in hits:
            c.invalidate(code, h)
            triggered[h].append(code)
        c.store.set_many({seen_key: (newest, 90 * T.DAY)})
    c.get_params(U.code.tolist(), P50 + P2)  # 2) bulk: expired daily fields + invalidated quarterly fields only
    for code in U.code:  # 3) per-stock views; events come from cache unless invalidated / older than 7 days
        for kind_fn, kind in ((c.overview, "overview"), (c.ownership, "bulblockdeal"), (c.overview, "events")):
            safe(kind_fn, code, kind)
except T.BudgetExceeded as e:
    print("STOP:", e)
print(f"{now:%Y-%m-%d %H:%M} stats={dict(c.stats, unmapped=sorted(c.stats.get('unmapped', [])))} calls_today={c.calls_today()} "
      f"triggered={ {k: v for k, v in triggered.items() if v} } errors={errors[:5]}")
out = os.path.join(a.reports, f"{now:%Y-%m-%d}")
sys.exit(subprocess.call([sys.executable, os.path.join(os.path.dirname(__file__), "screen_list.py"), a.universe, out,
                          "--as-of", f"{now:%Y-%m-%d}"]))
