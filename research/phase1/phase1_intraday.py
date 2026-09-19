"""Phase 1 — intraday gap-down screeners H-C (recovery after the initial low, long) and H-D (continuation, short),
evaluated once on the discovery period per PHASE1_PREREGISTRATION.md from certified Kite 5-minute bars."""
import glob

import numpy as np
import pandas as pd

import phase1_common as C

FIVE = "/app/research/kite_history/five_min_2024/part-*.csv.gz"


def vwap(b: pd.DataFrame) -> np.ndarray:
    tp = ((b.h + b.l + b.c) / 3).to_numpy(float)
    v = b.v.to_numpy(float)
    return np.cumsum(tp * v) / np.maximum(np.cumsum(v), 1)


def hc_trade(b: pd.DataFrame, official_close: float):
    """b: the day's 5-minute bars (hm, o, h, l, c, v) in time order. Returns (entry, exit, reason, mfe, mae) or None."""
    b = b.reset_index(drop=True)
    vw = vwap(b)
    low = b.l.cummin()
    for i in range(1, len(b) - 1):
        if b.hm[i] > "10:25":
            break
        if b.c[i] >= 1.01 * low[i] and b.c[i] > vw[i]:
            e, stop = b.o[i + 1], low[i]
            after = b.iloc[i + 1:]
            mfe, mae = after.h.max() / e - 1, after.l.min() / e - 1
            for _, x in after.iterrows():
                if x.o <= stop:
                    return e, x.o, "STOP_GAP", mfe, mae
                if x.l <= stop:
                    return e, stop, "STOP", mfe, mae
            return e, official_close, "TIME", mfe, mae
    return None


def hd_trade(b: pd.DataFrame, official_close: float):
    """Short at the 09:45 bar open when the 09:40 close is < 0.995 x open and below VWAP; stop +2%."""
    b = b.reset_index(drop=True)
    obs = b[b.hm <= "09:40"]
    if len(obs) < 6 or obs.hm.iloc[0] != "09:15" or (b.hm == "09:45").sum() != 1:
        return None
    o, p945, vw = obs.o.iloc[0], obs.c.iloc[-1], vwap(obs)[-1]
    if not (p945 < 0.995 * o and p945 < vw):
        return None
    after = b[b.hm >= "09:45"]
    e = after.o.iloc[0]
    stop = e * 1.02
    mfe, mae = e / after.l.min() - 1, e / after.h.max() - 1  # favourable for a short = the price falling
    for _, x in after.iterrows():
        if x.o >= stop:
            return e, x.o, "STOP_GAP", mfe, mae
        if x.h >= stop:
            return e, stop, "STOP", mfe, mae
    return e, official_close, "TIME", mfe, mae


def main():
    d = C.build_panel()
    g = d.groupby("symbol", sort=False)
    d["value20_prev"] = g.value20.shift(1)
    d["gap"] = d.open / d.prev_close - 1
    cand = d[(d.gap <= -0.03) & (d.value20_prev >= 5e7) & (d.hist_n >= 21)][["symbol", "date", "open", "close", "value20_prev"]].copy()
    cand["dkey"] = cand.date.dt.strftime("%Y-%m-%d")
    keys = set(zip(cand.symbol, cand.dkey))
    parts = []
    for f in sorted(glob.glob(FIVE)):
        for ch in pd.read_csv(f, usecols=["symbol", "ts", "open", "high", "low", "close", "volume"], chunksize=2_000_000):
            ch["dkey"] = ch.ts.str[:10]
            ch = ch[[k in keys for k in zip(ch.symbol, ch.dkey)]]
            if len(ch):
                parts.append(ch)
    B = pd.concat(parts).drop_duplicates(["symbol", "ts"])
    B["hm"] = B.ts.str[11:16]
    B = B.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"}).sort_values(["symbol", "ts"])
    bars = {k: x for k, x in B.groupby(["symbol", "dkey"], sort=False)}
    rows = []
    for r in cand.itertuples():
        b = bars.get((r.symbol, r.dkey))
        status = "OK"
        if b is None or b.hm.iloc[0] != "09:15":
            status = "NO_BARS"
        elif abs(b.o.iloc[0] - r.open) > max(0.05, 0.0005 * r.open):
            status = "OPEN_MISMATCH"  # 5-minute series disagrees with the daily open: data error, never traded
        rec = {"symbol": r.symbol, "date": r.date, "gap": r.open / d.loc[r.Index, "prev_close"] - 1, "value20": r.value20_prev,
               "cost": float(C.cost(pd.Series([r.value20_prev]))[0]), "bucket": C.bucket(pd.Series([r.value20_prev])).iloc[0],
               "regime_up": d.loc[r.Index, "regime_up"], "status": status}
        if status == "OK":
            for name, fn, side in (("HC", hc_trade, 1), ("HD", hd_trade, -1)):
                t = fn(b, r.close)
                if t:
                    e, x, why, mfe, mae = t
                    rec.update({f"{name}_entry": e, f"{name}_exit": x, f"{name}_reason": why, f"{name}_mfe": mfe, f"{name}_mae": mae,
                                f"{name}_net": side * (x / e - 1) - rec["cost"]})
        rows.append(rec)
    R = pd.DataFrame(rows)
    R.to_csv(f"{C.OUT}/signals_intraday.csv", index=False)
    report = {"candidates": int(len(R)), "status": R.status.value_counts().to_dict(), "screens": {}}
    for name in ("HC", "HD"):
        s = R[R.get(f"{name}_net").notna()] if f"{name}_net" in R else R.iloc[:0]
        s = s.rename(columns={f"{name}_net": "net"})
        half = np.where(s.date < pd.Timestamp("2025-10-01"), "2024-11..2025-09", "2025-10..2026-09")
        report["screens"][name] = {
            "trades": int(len(s)), "share_of_ok_candidates_pct": float(100 * len(s) / max(1, (R.status == "OK").sum())),
            "exit_reasons": s[f"{name}_reason"].value_counts().to_dict() if len(s) else {},
            "mfe_mean_pct": float(100 * s[f"{name}_mfe"].mean()) if len(s) else None, "mae_mean_pct": float(100 * s[f"{name}_mae"].mean()) if len(s) else None,
            "net": C.session_stats(s, "net"),
            "by_bucket": {k: C.session_stats(g, "net") for k, g in s.groupby("bucket")},
            "by_regime": {("up" if k == 1 else "down"): C.session_stats(g, "net") for k, g in s.dropna(subset=["regime_up"]).groupby("regime_up")},
            "by_half": {h: C.session_stats(g, "net") for h, g in s.groupby(half)}}
    C.write("phase1_intraday_results.json", report)
    print({k: (v["trades"], round(v["net"].get("mean_pct") or 0, 3)) for k, v in report["screens"].items()}, report["status"])


if __name__ == "__main__":
    main()
