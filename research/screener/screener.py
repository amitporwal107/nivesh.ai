"""Local stock screener on Kite quotes: declarative screens (universe, filter, sort, fields) over one market snapshot.

A snapshot = Kite `quote` for every member of the universe (500 instruments per call: Nifty 500 = 2 calls). During
market hours it is live; outside them it is the last session (last_price, open, high, low then equal the official
bhavcopy — checked 498/498 on 18 Sep). Kite resets the day's volume and VWAP to 0 outside the session, so volume and
traded value then come from the official NSE bhavcopy for that session (`volume_source` column says which). Every snapshot is archived, so screens and model validation can be re-run later
without Kite. Kite data is for internal use only.

usage:
  python screener.py list
  python screener.py run gainers --X 5 [--universe NIFTY500] [--snapshot FILE]
  python screener.py all [--universe NIFTY500]        # one snapshot, every screen, archived
  python screener.py all --session 2026-09-18          # same, from the official bhavcopy (no Kite)
"""
import argparse
import datetime as dt
import io
import json
import os
import time

import zipfile

import numpy as np
import pandas as pd
import requests

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("SCREENER_DIR", "/app/research/screener")
INDEX_CSV = {"NIFTY50": "ind_nifty50list", "NIFTY100": "ind_nifty100list", "NIFTY200": "ind_nifty200list",
             "NIFTY500": "ind_nifty500list", "MIDCAP150": "ind_niftymidcap150list", "SMALLCAP250": "ind_niftysmallcap250list"}
KITE_KEY_FILE, KITE_TOKEN_FILE = "/app/.KITE.API.KEY", "/root/.kite-access-token"


def members(index: str) -> pd.DataFrame:
    """Index constituents from niftyindices.com, kept locally for 7 days (membership changes twice a year)."""
    ref = os.path.join(ROOT, "ref")
    os.makedirs(ref, exist_ok=True)
    path = os.path.join(ref, f"{INDEX_CSV[index]}.csv")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 7 * 86400:
        r = requests.get(f"https://niftyindices.com/IndexConstituent/{INDEX_CSV[index]}.csv", timeout=30,
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0"})
        r.raise_for_status()
        pd.read_csv(io.StringIO(r.text))  # never overwrite the local copy with a non-CSV response
        open(path, "w").write(r.text)
    m = pd.read_csv(path).rename(columns={"Symbol": "symbol", "Company Name": "name", "Industry": "industry"})
    return m[["symbol", "name", "industry"]]


def kite_quotes(symbols: list[str]) -> list[dict]:
    from kiteconnect import KiteConnect
    k = KiteConnect(api_key=open(KITE_KEY_FILE).read().splitlines()[0].strip())
    k.set_access_token(open(KITE_TOKEN_FILE).read().strip())
    out = []
    for i in range(0, len(symbols), 500):  # Kite quote: at most 500 instruments per call
        q = k.quote([f"NSE:{s}" for s in symbols[i:i + 500]])
        out += [dict(v, symbol=key.split(":", 1)[1]) for key, v in q.items()]
    return out


def bhavcopy(session: str) -> pd.DataFrame:
    """Official NSE CM bhavcopy (UDiFF) for one session, cached locally: symbol, series, volume, turnover."""
    d = os.path.join(ROOT, "ref", "bhavcopy")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{session}.csv.gz")
    if not os.path.exists(path):
        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{session.replace('-', '')}_F_0000.csv.zip"
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
        proxy = os.environ.get("NSE_HTTPS_PROXY", "http://10.160.0.5:3128")
        r = None
        for proxies in (None, {"https": proxy}):  # the VM's IP is sometimes blocked by NSE; the proxy is the fallback
            try:
                r = requests.get(url, headers=ua, timeout=60, proxies=proxies)
                if r.status_code == 200:
                    break
            except requests.RequestException:
                r = None
        if r is None or r.status_code != 200:
            raise RuntimeError(f"bhavcopy {session}: HTTP {getattr(r, 'status_code', 'no response')}")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        b = pd.read_csv(z.open(z.namelist()[0]))
        if str(b.TradDt.iloc[0]) != session:
            raise RuntimeError(f"bhavcopy {session}: file is for {b.TradDt.iloc[0]}")
        b.to_csv(path, index=False)
    b = pd.read_csv(path)
    b = b[b.SctySrs.isin(["EQ", "BE", "BZ", "SM", "ST"])]
    return b.rename(columns={"TckrSymb": "symbol", "SctySrs": "series", "TtlTradgVol": "volume", "TtlTrfVal": "turnover",
                             "OpnPric": "open", "HghPric": "high", "LwPric": "low", "ClsPric": "close", "PrvsClsgPric": "prev_close"})[
        ["symbol", "series", "open", "high", "low", "close", "prev_close", "volume", "turnover"]].drop_duplicates("symbol")


def snapshot_from_bhavcopy(session: str, symbols: list[str] | None = None) -> pd.DataFrame:
    """A snapshot for any past session from the official bhavcopy (no Kite needed). Note: NSE's previous close is not
    adjusted on ex-dates, so a stock going ex-dividend/bonus/split that day shows a false move."""
    b = bhavcopy(session)
    if symbols is not None:
        b = b[b.symbol.isin(symbols)]
    d = b.rename(columns={"close": "last_price"}).assign(vwap=lambda x: x.turnover / x.volume.replace(0, np.nan),
                                                          upper_circuit=np.nan, lower_circuit=np.nan,
                                                          last_trade_time=session, volume_source=f"bhavcopy {session}")
    return derive(d.drop(columns=["turnover"]))


def fill_eod_volume(d: pd.DataFrame) -> pd.DataFrame:
    """Outside the session Kite reports volume/VWAP as 0: take them from the session's bhavcopy instead."""
    d["volume_source"] = "kite"
    d["volume"], d["vwap"] = pd.to_numeric(d.volume, errors="coerce").astype(float), pd.to_numeric(d.vwap, errors="coerce").astype(float)
    if len(d) and (d.volume.fillna(0) == 0).mean() > 0.5:
        session = str(pd.to_datetime(d.last_trade_time, errors="coerce").max())[:10]
        b = bhavcopy(session).set_index("symbol")
        has = d.symbol.isin(b.index)
        d.loc[has, "volume"] = d.loc[has, "symbol"].map(b.volume).values
        d.loc[has, "vwap"] = (d.loc[has, "symbol"].map(b.turnover) / d.loc[has, "symbol"].map(b.volume).replace(0, np.nan)).values
        d.loc[has, "volume_source"] = f"bhavcopy {session}"
        d.loc[~has, ["volume", "vwap"]] = np.nan
    return d


def build_snapshot(quotes: list[dict], meta: pd.DataFrame) -> pd.DataFrame:
    """Kite quote dicts -> one row per symbol with the screen fields."""
    rows = []
    for q in quotes:
        o = q.get("ohlc", {})
        ltt = q.get("last_trade_time")
        rows.append({"symbol": q["symbol"], "last_price": q.get("last_price"), "prev_close": o.get("close"),
                     "open": o.get("open"), "high": o.get("high"), "low": o.get("low"), "volume": q.get("volume"),
                     "vwap": q.get("average_price"), "upper_circuit": q.get("upper_circuit_limit"),
                     "lower_circuit": q.get("lower_circuit_limit"),
                     "last_trade_time": ltt.isoformat() if hasattr(ltt, "isoformat") else ltt})
    return derive(fill_eod_volume(pd.DataFrame(rows).merge(meta, on="symbol", how="left")))


def derive(d: pd.DataFrame) -> pd.DataFrame:
    """Screen fields from prices: last_price, prev_close, open, high, low, volume, vwap, circuits."""
    pc = d.prev_close.where(d.prev_close > 0)
    d["daily_change_pct"] = (d.last_price / pc - 1) * 100
    d["gap_pct"] = (d.open / pc - 1) * 100
    d["high_pct"] = (d.high / pc - 1) * 100          # the v4 model's outcome: next-session high vs previous close
    d["low_pct"] = (d.low / pc - 1) * 100
    d["range_pct"] = (d.high / d.low.where(d.low > 0) - 1) * 100
    d["close_in_range"] = ((d.last_price - d.low) / (d.high - d.low).where(d.high > d.low)).clip(0, 1)
    d["traded_value_cr"] = d.volume * d.vwap / 1e7
    d["at_upper_circuit"] = np.isclose(d.last_price, d.upper_circuit) & (d.upper_circuit > 0)
    d["at_lower_circuit"] = np.isclose(d.last_price, d.lower_circuit) & (d.lower_circuit > 0)
    return d


def load_screens() -> dict:
    return json.load(open(os.path.join(HERE, "screens.json")))


def run_screen(snap: pd.DataFrame, spec: dict, params: dict | None = None) -> pd.DataFrame:
    """Apply one screen: filter (pandas query with {param} placeholders), sort, fields, limit."""
    p = dict(spec.get("params", {}), **(params or {}))
    q = spec["filter"].format(**p)
    out = snap.query(q, engine="python")
    s = spec.get("sort", {"field": "daily_change_pct", "desc": True})
    out = out.sort_values(s["field"], ascending=not s.get("desc", True), na_position="last")
    if spec.get("limit"):
        out = out.head(int(spec["limit"]))
    return out[spec["fields"]].reset_index(drop=True)


def snapshot(universe: str, snapshot_file: str | None = None, archive: bool = True, session: str | None = None) -> tuple[pd.DataFrame, str]:
    if snapshot_file:
        return pd.read_csv(snapshot_file), snapshot_file
    m = members(universe)
    if session:  # official end-of-day data for any past session, no Kite needed (no circuit limits in the bhavcopy)
        snap = snapshot_from_bhavcopy(session, m.symbol.tolist()).merge(m, on="symbol", how="left")
    else:
        snap = build_snapshot(kite_quotes(m.symbol.tolist()), m)
    session = str(pd.to_datetime(snap.last_trade_time, errors="coerce").max())[:10]
    now = dt.datetime.now(IST)
    path = ""
    if archive:
        d = os.path.join(ROOT, "snapshots", session)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{universe}_{now:%H%M%S}.csv.gz")
        snap.to_csv(path, index=False)
    return snap, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "run", "all"])
    ap.add_argument("screen", nargs="?")
    ap.add_argument("--universe", default="NIFTY500", choices=sorted(INDEX_CSV))
    ap.add_argument("--X", type=float, help="threshold for screens that take X")
    ap.add_argument("--snapshot", help="run on an archived snapshot instead of live Kite")
    ap.add_argument("--session", help="YYYY-MM-DD: use the official NSE bhavcopy for that session instead of Kite")
    a = ap.parse_args()
    screens = load_screens()
    if a.cmd == "list":
        for k, v in screens.items():
            print(f"{k:18s} {v['description']}  [filter: {v['filter']}, params {v.get('params', {})}]")
        return
    snap, path = snapshot(a.universe, a.snapshot, session=a.session)
    session = str(pd.to_datetime(snap.last_trade_time, errors="coerce").max())[:16]
    pd.set_option("display.width", 220)
    names = [a.screen] if a.cmd == "run" else list(screens)
    out_dir = os.path.join(ROOT, "results", session[:10])
    os.makedirs(out_dir, exist_ok=True)
    for name in names:
        spec = screens[name]
        if "circuit" in spec["filter"] and pd.to_numeric(snap.get("upper_circuit"), errors="coerce").isna().all():
            print(f"\n== {name}: n/a — price-band limits come from Kite (live mode); the bhavcopy does not carry them")
            continue
        res = run_screen(snap, spec, {"X": a.X} if a.X is not None else None)
        res.to_csv(os.path.join(out_dir, f"{a.universe}_{name}.csv"), index=False)
        print(f"\n== {name}: {spec['description'].format(**dict(spec.get('params', {}), **({'X': a.X} if a.X is not None else {})))} "
              f"— {len(res)} stocks ({a.universe}, data to {session} IST{', snapshot ' + path if path else ''})")
        print(res.round(2).to_string(index=False) if len(res) else "  (none)")


if __name__ == "__main__":
    main()
