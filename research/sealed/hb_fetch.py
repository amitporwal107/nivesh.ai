"""DATA ONLY for the sealed H-B test (TRACK1_SCOPE_v2): 5-minute bars for every 2021-22 H-B candidate signal-day.
Candidates use the ENTRY condition only (gap <= -3% vs previous close, 20-session value >= Rs 5 cr, EQ, not open-at-band);
no outcome is computed here. Resumable; stops cleanly on a token/permission error. Rows dated 2023+ are dropped at load."""
import csv, glob, gzip, os, sys, time, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, "/app/.claude/worktrees/paper-engine/backend")
from nidp.services.kite_bars.client import kite
from nidp.services.kite_bars.auth import read_token
OUT = "/app/research/sealed/hb_5min_2021_2022"; STATUS = f"{OUT}/status.csv"
LO, HI, START = pd.Timestamp("2020-11-01"), pd.Timestamp("2022-12-31"), pd.Timestamp("2021-01-01")
parts = []
for f in sorted(glob.glob("/app/research/kite_history/day_2021/part-*.csv.gz")):
    for ch in pd.read_csv(f, usecols=["symbol", "instrument_token", "date", "open", "close", "volume"], chunksize=500_000):
        ch["date"] = pd.to_datetime(ch.date); parts.append(ch[(ch.date >= LO) & (ch.date <= HI)])
K = pd.concat(parts).drop_duplicates(["symbol", "date"]); K = K[~K.symbol.str.endswith("-BE")].sort_values(["symbol", "date"])
cal = sorted(K.date.unique()); prev_of = {cal[i]: cal[i - 1] for i in range(1, len(cal))}
K["value"] = K.volume * K.close; g = K.groupby("symbol", sort=False)
K["prev_date"] = g.date.shift(1); K["p0"] = g.close.shift(1)
K["value20"] = g.value.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
K = K[(K.date >= START) & (K.prev_date == K.date.map(prev_of))]
K["gap"] = K.open / K.p0 - 1
C = K[(K.gap <= -0.03) & (K.value20 >= 5e7)]
C = C[~np.any([np.abs(C.gap + b) <= 0.0025 for b in (0.05, 0.10, 0.20)], axis=0)][["symbol", "instrument_token", "date"]]
done = set()
if os.path.exists(STATUS):
    done = {(r["symbol"], r["date"]) for r in csv.DictReader(open(STATUS)) if r["status"] in ("OK", "EMPTY")}
todo = [r for r in C.itertuples() if (r.symbol, r.date.strftime("%Y-%m-%d")) not in done]
print(f"candidates {len(C):,}; done {len(done):,}; to fetch {len(todo):,}", flush=True)
kc = kite(read_token())
new = not os.path.exists(STATUS); sf = open(STATUS, "a", newline=""); sw = csv.writer(sf)
if new: sw.writerow(["symbol", "date", "status", "rows", "error", "fetched_at"])
bf = gzip.open(f"{OUT}/bars-{dt.datetime.now():%Y%m%dT%H%M%S}.tsv.gz", "wt", newline=""); bw = csv.writer(bf, delimiter="\t")
tally = {"OK": 0, "EMPTY": 0, "ERROR": 0}
for i, r in enumerate(todo, 1):
    d = r.date.date(); rows, err = [], None
    for attempt in range(3):
        try:
            rows = kc.historical_data(int(r.instrument_token), d, d, "5minute", continuous=False, oi=False); err = None; break
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
            if type(e).__name__ in ("TokenException", "PermissionException"):
                print(f"STOPPED ({err}) at {i}/{len(todo)} -- re-run after the next login", flush=True)
                bf.close(); sf.close(); raise SystemExit(0)
            time.sleep(1.5 * (attempt + 1))
    time.sleep(0.35); now = dt.datetime.now().isoformat(timespec="seconds")
    if err: tally["ERROR"] += 1; sw.writerow([r.symbol, d, "ERROR", 0, err, now]); continue
    if not rows: tally["EMPTY"] += 1; sw.writerow([r.symbol, d, "EMPTY", 0, "", now]); continue
    for c in rows: bw.writerow([r.symbol, c["date"].strftime("%Y-%m-%d %H:%M"), c["open"], c["high"], c["low"], c["close"], c.get("volume")])
    tally["OK"] += 1; sw.writerow([r.symbol, d, "OK", len(rows), "", now])
    if i % 250 == 0: sf.flush(); bf.flush(); print(f"  {i:,}/{len(todo):,} {tally}", flush=True)
bf.close(); sf.close(); print("FINAL", tally, flush=True)
