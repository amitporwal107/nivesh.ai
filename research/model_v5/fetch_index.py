"""Fetch daily index history from Kite for ONE period block (PREREGISTRATION_P2_P3.md §7, §9): the development block
(2021-01-01..2022-12-31) now; test/confirmation blocks only at their own step. Credentials are read from their files
and never printed. The output is refused if any bar falls outside the requested block.
run: python fetch_index.py dev
"""
import datetime as dt
import sys

import pandas as pd

BLOCKS = {"dev": (dt.date(2021, 1, 1), dt.date(2022, 12, 31)), "test": (dt.date(2023, 1, 1), dt.date(2024, 7, 31))}
INDICES = ("NIFTY 500", "NIFTY 50")
OUT = "/app/research/model_v5/index_{block}.csv"


def main(block: str):
    from kiteconnect import KiteConnect
    lo, hi = BLOCKS[block]
    k = KiteConnect(api_key=open("/app/.KITE.API.KEY").read().splitlines()[0].strip())
    k.set_access_token(open("/root/.kite-access-token").read().strip())
    toks = {r["tradingsymbol"]: r["instrument_token"] for r in k.instruments("NSE") if r.get("segment") == "INDICES"}
    frames = []
    for name in INDICES:
        rows = k.historical_data(toks[name], lo, hi, "day")
        x = pd.DataFrame(rows)[["date", "open", "high", "low", "close"]]
        x["date"] = pd.to_datetime(x.date.astype(str).str[:10]).dt.date
        x["index"] = name
        frames.append(x)
    out = pd.concat(frames, ignore_index=True)
    assert out.date.min() >= lo and out.date.max() <= hi, "bars outside the requested block"
    out.to_csv(OUT.format(block=block), index=False)
    print(block, {n: (int((out["index"] == n).sum()), str(out[out["index"] == n].date.min()), str(out[out["index"] == n].date.max())) for n in INDICES})


if __name__ == "__main__":
    main(sys.argv[1])
