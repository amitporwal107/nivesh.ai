"""Top gainers of the day for an NSE index, enriched with cached Trendlyne data — our equivalent of Trendlyne's
"Top gainers of the day" screener, which the Trendlyne MCP server does not expose.

Ranking: Kite `ohlc` for every index member in one call (last price vs previous close). During market hours this is
live; outside them it is the last session's full move (verified against the 18-Sep bhavcopy: 498/498 match).
Enrichment: only the top N go to Trendlyne through TLCache (bulk parameters ~N/10 calls; overview for ASM status and
news, 2 calls per stock), cached and archived like everything else. Kite data is for internal use only.

usage: python top_gainers.py [--index NIFTY500] [--n 20] [--out DIR] [--no-enrich]
"""
import argparse
import datetime as dt
import io
import os
import re
import time

import pandas as pd
import requests

import tl_cache as T
from screen_list import P2, P50, f, pipe_rows, section
from tl_client import TLClient

INDEX_CSV = {"NIFTY50": "ind_nifty50list", "NIFTY100": "ind_nifty100list", "NIFTY200": "ind_nifty200list",
             "NIFTY500": "ind_nifty500list", "MIDCAP150": "ind_niftymidcap150list", "SMALLCAP250": "ind_niftysmallcap250list"}
REF = os.environ.get("TL_REF_DIR", "/app/research/trendlyne/ref")
KITE_KEY_FILE, KITE_TOKEN_FILE = "/app/.KITE.API.KEY", "/root/.kite-access-token"


def members(index: str) -> pd.DataFrame:
    """Index constituents from niftyindices.com, kept locally for 7 days (membership changes twice a year)."""
    os.makedirs(REF, exist_ok=True)
    path = os.path.join(REF, f"{INDEX_CSV[index]}.csv")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 7 * T.DAY:
        r = requests.get(f"https://niftyindices.com/IndexConstituent/{INDEX_CSV[index]}.csv", timeout=30,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0"})
        r.raise_for_status()
        pd.read_csv(io.StringIO(r.text))  # refuse to overwrite the local copy with a non-CSV response
        open(path, "w").write(r.text)
    return pd.read_csv(path)


def kite():
    from kiteconnect import KiteConnect
    k = KiteConnect(api_key=open(KITE_KEY_FILE).read().splitlines()[0].strip())
    k.set_access_token(open(KITE_TOKEN_FILE).read().strip())
    return k


def day_moves(symbols: list[str]) -> pd.DataFrame:
    q = kite().ohlc([f"NSE:{s}" for s in symbols])  # one call for up to 1,000 instruments
    rows = [{"symbol": key.split(":", 1)[1], "prev_close": v["ohlc"]["close"], "last": v["last_price"],
             "open": v["ohlc"]["open"], "high": v["ohlc"]["high"], "low": v["ohlc"]["low"]} for key, v in q.items()]
    d = pd.DataFrame(rows)
    d["chg_pct"] = (d["last"] / d.prev_close - 1) * 100
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="NIFTY500", choices=sorted(INDEX_CSV))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="/app/research/trendlyne/gainers")
    ap.add_argument("--no-enrich", action="store_true")
    a = ap.parse_args()
    now = dt.datetime.now(T.IST)
    M = members(a.index)
    D = day_moves(M.Symbol.tolist()).merge(M.rename(columns={"Symbol": "symbol", "Company Name": "name"})[["symbol", "name", "Industry"]],
                                          on="symbol", how="left").sort_values("chg_pct", ascending=False)
    top = D.head(a.n).copy()
    stats = {}
    if not a.no_enrich:
        c = T.TLCache(TLClient(), T.RedisStore())
        bulk = c.get_params(top.symbol.tolist(), P50 + P2)
        keep = {"roea": "ROE %", "npqgrowth": "PAT qtr YoY %", "rev4qq": "Rev qtr YoY %", "pettm": "PE", "prompct": "Promoter %",
                "prompledge": "Pledge %", "rsi": "RSI*", "ltpyearhighdiff": "% below 52w high*", "delivery30dayavg": "Deliv% 30d*",
                "mcapq": "Mcap cr*"}
        for k, lab in keep.items():
            top[lab] = [f(bulk.get(s.upper(), {}).get(k)) for s in top.symbol]
        asm, head = [], []
        for s in top.symbol:
            ov = c.overview(s, "overview")  # overview (ASM status) + news only: 2 calls per stock, cached
            m = re.search(r"text:[ \t]*(.*)", section(ov, "asmData"))
            asm.append(m.group(1).strip() if m and m.group(1).strip() else "")
            news = pipe_rows(section(c.overview(s, "news"), "newsList"))
            head.append(f"{news[0].get('pubDate', '')[:10]} {news[0].get('title', '')}"[:110] if news else "")
        top["ASM"], top["latest news"] = asm, head
        stats = dict(c.stats)
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.join(a.out, f"{a.index}_{now:%Y-%m-%d_%H%M}")
    D.to_csv(stem + "_all.csv", index=False)
    top.to_csv(stem + "_top.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 60)
    cols = [c for c in top.columns if c not in ("open", "high", "low", "Industry")]
    print(f"{a.index} top {a.n} gainers @ {now:%Y-%m-%d %H:%M} IST (Kite; {len(D)} of {len(M)} members priced). "
          f"* = Trendlyne snapshot, may lag a session. Trendlyne {stats}")
    print(top[cols].round(2).to_string(index=False))


if __name__ == "__main__":
    main()
