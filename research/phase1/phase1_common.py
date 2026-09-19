"""Phase 1 screener study — shared data, features, labels and statistics (docs/ai_research/tpd3/phase1/
PHASE1_PREREGISTRATION.md). Discovery data only: every loader drops rows before DISCOVERY_START."""
import glob
import json
import os

import numpy as np
import pandas as pd

DISCOVERY_START = pd.Timestamp("2024-08-01")
DAILY = "/app/research/kite_history/day_2021/part-*.csv.gz"
N500 = "/app/research/screener/ref/ind_nifty500list.csv"
OUT = "/app/research/phase1"
IDX_CACHE = os.path.join(OUT, "nifty500_index_daily.csv")


def cost(value20: pd.Series) -> pd.Series:
    """Cost model v1 round trip by 20-day traded value."""
    return np.where(value20 > 1e9, 0.0020, np.where(value20 > 2.5e8, 0.0030, 0.0040))


def bucket(value20: pd.Series) -> pd.Series:
    return pd.Series(np.where(value20 > 1e9, ">100cr", np.where(value20 > 2.5e8, "25-100cr", "5-25cr")), index=value20.index)


def load_daily(symbols: set) -> pd.DataFrame:
    parts = []
    for f in sorted(glob.glob(DAILY)):
        for ch in pd.read_csv(f, usecols=["symbol", "date", "open", "high", "low", "close", "volume"], chunksize=1_000_000):
            ch = ch[ch.symbol.isin(symbols)]
            ch["date"] = pd.to_datetime(ch.date)
            parts.append(ch[ch.date >= DISCOVERY_START])
    d = pd.concat(parts).drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    assert d.date.min() >= DISCOVERY_START, "sealed data leaked into the panel"
    return d


def load_index() -> pd.DataFrame:
    """Nifty 500 index daily closes from Kite (cached); discovery period only."""
    if not os.path.exists(IDX_CACHE):
        from kiteconnect import KiteConnect
        k = KiteConnect(api_key=open("/app/.KITE.API.KEY").read().splitlines()[0].strip())
        k.set_access_token(open("/root/.kite-access-token").read().strip())
        tok = next(r["instrument_token"] for r in k.instruments("NSE") if r.get("segment") == "INDICES" and r["tradingsymbol"] == "NIFTY 500")
        rows = k.historical_data(tok, DISCOVERY_START.date(), pd.Timestamp.today().date(), "day")
        pd.DataFrame(rows)[["date", "close"]].to_csv(IDX_CACHE, index=False)
    x = pd.read_csv(IDX_CACHE)
    x["date"] = pd.to_datetime(x.date.astype(str).str[:10])
    return x[x.date >= DISCOVERY_START].rename(columns={"close": "idx_close"}).sort_values("date").reset_index(drop=True)


def _expanding_pct(x: np.ndarray, min_prior: int = 60) -> np.ndarray:
    """Share of strictly earlier finite values <= the current value (NaN until min_prior earlier values)."""
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        if not np.isfinite(x[i]):
            continue
        prior = x[:i][np.isfinite(x[:i])]
        if len(prior) >= min_prior:
            out[i] = (prior <= x[i]).mean()
    return out


def build_panel() -> pd.DataFrame:
    n5 = set(pd.read_csv(N500).Symbol)
    d = load_daily(n5)
    idx = load_index()
    cal = pd.Index(idx.date)
    g = d.groupby("symbol", sort=False)
    d["prev_close"] = g.close.shift(1)
    d["hist_n"] = g.cumcount()
    tr = np.maximum(d.high - d.low, np.maximum((d.high - d.prev_close).abs(), (d.low - d.prev_close).abs()))
    d["tr"] = tr.fillna(d.high - d.low)
    d["atr14"] = d.groupby("symbol", sort=False).tr.transform(lambda s: s.ewm(alpha=1 / 14, adjust=False).mean())
    d["atr_pct"] = d.atr14 / d.close
    d["atr_med"] = d.groupby("symbol", sort=False).atr_pct.transform(lambda s: s.shift(1).expanding(min_periods=60).median())
    d["rvol"] = d.volume / g.volume.transform(lambda s: s.shift(1).rolling(20).mean())
    d["value"] = d.close * d.volume
    d["value20"] = g.value.transform(lambda s: s.rolling(20).mean())
    d["range10"] = (g.high.transform(lambda s: s.shift(1).rolling(10).max()) - g.low.transform(lambda s: s.shift(1).rolling(10).min())) / d.prev_close
    d["range10_pct"] = d.groupby("symbol", sort=False).range10.transform(lambda s: pd.Series(_expanding_pct(s.to_numpy()), index=s.index))
    d["tr_ratio"] = d.tr / d.groupby("symbol", sort=False).atr14.shift(1)
    d["tr_pct"] = d.tr / d.prev_close
    d["hi20"] = g.high.transform(lambda s: s.shift(1).rolling(20).max())
    d["hi55"] = g.high.transform(lambda s: s.shift(1).rolling(55).max())
    d["ema20"] = g.close.transform(lambda s: s.ewm(span=20, adjust=False).mean())
    d["ema50"] = g.close.transform(lambda s: s.ewm(span=50, adjust=False).mean())
    d["close_pos"] = ((d.close - d.low) / (d.high - d.low)).where(d.high > d.low, 0.5)
    d["ret20"] = d.close / g.close.shift(20) - 1
    idx["idx_ret20"] = idx.idx_close / idx.idx_close.shift(20) - 1
    ma50 = idx.idx_close.rolling(50).mean()
    idx["regime_up"] = (idx.idx_close > ma50).astype(float).where(ma50.notna())
    d = d.merge(idx[["date", "idx_ret20", "regime_up"]], on="date", how="left")
    d["rs20"] = d.ret20 - d.idx_ret20
    # outcomes, only when the next rows are the next trading sessions of the calendar
    g = d.groupby("symbol", sort=False)
    pos = pd.Series(cal.get_indexer(d.date), index=d.index)
    nxt = {k: g.date.shift(-k) for k in (1, 5)}
    ok1 = pd.Series(cal.get_indexer(nxt[1]), index=d.index) == pos + 1
    ok5 = pd.Series(cal.get_indexer(nxt[5]), index=d.index) == pos + 5
    o1, h1, l1, c1 = (g[c].shift(-1) for c in ("open", "high", "low", "close"))
    h5 = pd.concat([g.high.shift(-k) for k in range(1, 6)], axis=1).max(axis=1, skipna=False)
    c5 = g.close.shift(-5)
    for lab, cond, ok in (("L5_1", h1 >= d.close * 1.05, ok1), ("L10_1", h1 >= d.close * 1.10, ok1),
                          ("L5_5", h5 >= d.close * 1.05, ok5), ("L10_5", h5 >= d.close * 1.10, ok5),
                          ("D5_1", l1 <= d.close * 0.95, ok1)):
        d[lab] = cond.astype(float).where(ok & h1.notna())
    d["label1_date"], d["label5_date"] = nxt[1].where(ok1), nxt[5].where(ok5)
    d["mfe1"], d["mae1"] = (h1 / o1 - 1).where(ok1), (l1 / o1 - 1).where(ok1)
    d["cost"] = cost(d.value20)
    d["net1"] = (c1 / o1 - 1 - d.cost).where(ok1)
    d["net5"] = (c5 / o1 - 1 - d.cost).where(ok5 & ok1)
    d["bucket"] = bucket(d.value20)
    d["eligible"] = (d.hist_n >= 60) & (d.value20 >= 5e7) & (d.close >= 50)
    return d


def nw(x, lags: int = 5) -> dict:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"n": n, "mean_pct": float(100 * x.mean()) if n else None}
    mu, e = x.mean(), x - x.mean()
    s = (e @ e) / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * ((e[L:] @ e[:-L]) / n)
    se = np.sqrt(max(s, 0) / n)
    return {"n": n, "mean_pct": 100 * mu, "ci95_pct": [100 * (mu - 1.96 * se), 100 * (mu + 1.96 * se)], "t": mu / se if se else None}


def boot(x, draws: int = 2000, seed: int = 7) -> list:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 10:
        return [None, None]
    r = np.random.default_rng(seed)
    m = np.array([x[r.integers(0, len(x), len(x))].mean() for _ in range(draws)])
    return [float(100 * np.percentile(m, 2.5)), float(100 * np.percentile(m, 97.5))]


def session_stats(sig: pd.DataFrame, col: str, cost_col: str = "cost") -> dict:
    """sig: one row per signal with date, col (net return), cost. Equal weight within a session."""
    s = sig.groupby("date")[col].mean().sort_index()
    s2 = (sig[col] - sig[cost_col]).groupby(sig.date).mean().sort_index()  # 2x costs: subtract the cost once more
    out = {"sessions": int(s.size), "signals": int(len(sig)), **nw(s.values), "bootstrap95_pct": boot(s.values),
           "cost2x": nw(s2.values), "win_sessions_pct": float(100 * (s > 0).mean()) if len(s) else None}
    tot = s.sum()
    srt = s.sort_values(ascending=False)
    out["top5_share_pct"] = float(100 * srt.head(5).sum() / tot) if tot > 0 else None
    out["top10_share_pct"] = float(100 * srt.head(10).sum() / tot) if tot > 0 else None
    return out


def write(name: str, obj):
    os.makedirs(OUT, exist_ok=True)
    json.dump(obj, open(os.path.join(OUT, name), "w"), indent=1, default=lambda v: None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v))
