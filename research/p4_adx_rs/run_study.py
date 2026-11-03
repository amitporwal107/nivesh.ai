#!/usr/bin/env python3
"""Pre-registered ADX / relative-strength study of the AI scanner score (Phase 4.3).

Design: docs/ai_research/P4_ADX_RS_PREREGISTRATION.md (registered in commit 4c408401 before any result). This script
implements that design and nothing else. It reads exported warehouse files and writes a JSON result and a short markdown
summary; it never writes to a database.

    python research/p4_adx_rs/run_study.py <data_dir> <out_dir> <code_sha>

<data_dir> holds bars.csv, etf.csv, niftybees.csv and nifty50.csv (exported read-only from the staging warehouse).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from services.fno_backtest import outcomes, stats  # noqa: E402
from services.positional_engine import feature_calculator as fc  # noqa: E402
from services.positional_engine import scorer  # noqa: E402

H = 10                      # sessions held (§5)
MIN_BARS = 220              # prior adjusted sessions (§3)
LIQ_RS = 1e8                # ₹10 crore median 20-session traded value (§3)
MIN_PRICE = 20.0            # (§3)
WINDOW = 260                # bars handed to compute_features
COST = 0.0035               # round trip (§7)
NW_LAG = 9                  # (§8)
PERM_DRAWS, PERM_BLOCK, SEED = 1000, 10, 20261027
MIN_NAMES = 30              # a date needs this many scored names for an IC
ARMS = ("B0", "A1", "A2", "A3")


def ramp(v: Optional[float], lo: float, hi: float) -> float:
    return scorer._ramp(v, lo, hi)


def wilder_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14):
    """ADX, +DI, −DI with Wilder's smoothing (an exponential average with alpha = 1/n)."""
    h, l, c = pd.Series(high), pd.Series(low), pd.Series(close)
    up, down = h.diff(), -l.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = 1.0 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm).ewm(alpha=a, adjust=False).mean() / atr
    dx = (100 * (pdi - mdi).abs() / (pdi + mdi)).replace([np.inf, -np.inf], np.nan)
    adx = dx.ewm(alpha=a, adjust=False).mean()
    return adx.to_numpy(), pdi.to_numpy(), mdi.to_numpy()


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(data: Path, out: Path, code_sha: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    bars = pd.read_csv(data / "bars.csv", parse_dates=["as_of_date"])
    bars["eq"] = bars["eq"].astype(str).eq("t")
    etf = pd.read_csv(data / "etf.csv")
    etf_syms = set(etf.loc[etf["is_etf"].astype(str).eq("t"), "symbol"])
    bench = pd.read_csv(data / "niftybees.csv", parse_dates=["as_of_date"]).set_index("as_of_date")["close_price"]
    nifty = pd.read_csv(data / "nifty50.csv", parse_dates=["as_of_date"]).set_index("as_of_date")["close_price"]

    sessions = sorted(bars["as_of_date"].unique())
    pos = {d: i for i, d in enumerate(sessions)}
    gaps = [str(pd.Timestamp(d).date()) for d in sessions if d not in nifty.index or d not in bench.index]
    if gaps:
        print(f"REFUSED: Nifty 50 / NIFTYBEES missing on {len(gaps)} sessions, e.g. {gaps[:5]}")
        return 3

    bench_close = bench.reindex(sessions).to_numpy(float)
    nifty_close = nifty.reindex(sessions).to_numpy(float)
    nifty_sma200 = pd.Series(nifty_close).rolling(200).mean().to_numpy()

    # Per date: list of rows (symbol, arm scores, R) for the universe; and every symbol's R (for coverage).
    per_date: Dict[int, List[dict]] = {}
    all_r: Dict[int, List[tuple]] = {}
    w = scorer.DEFAULT_WEIGHTS
    last_signal = len(sessions) - 1 - H

    for sym, g in bars.groupby("symbol", sort=False):
        g = g.sort_values("as_of_date")
        si = np.array([pos[d] for d in g["as_of_date"]])
        o, hi, lo, c = (g[k].to_numpy(float) for k in ("adj_open", "adj_high", "adj_low", "adj_close"))
        vol = g["adj_volume"].to_numpy(float)
        tv = (g["raw_close"] * g["raw_volume"]).to_numpy(float)
        deliv = g["deliv_pct"].to_numpy(float)
        eq = g["eq"].to_numpy(bool)
        raw_close = g["raw_close"].to_numpy(float)
        adx, pdi, mdi = wilder_adx(hi, lo, c)
        by_session = {s: k for k, s in enumerate(si)}
        is_etf = sym in etf_syms or sym.endswith("BEES") or sym.endswith("ETF")
        for k in range(len(si)):
            i = si[k]
            if i > last_signal:
                break
            # R for coverage (any priced symbol with both ends on the calendar's sessions i+1 and i+H)
            k1, kH = by_session.get(i + 1), by_session.get(i + H)
            r = (c[kH] / o[k1] - 1.0) if (k1 is not None and kH is not None and o[k1] > 0) else None
            if r is not None:
                all_r.setdefault(i, []).append((sym, r))
            if r is None or is_etf or not eq[k] or k + 1 < MIN_BARS or raw_close[k] < MIN_PRICE:
                continue
            if np.nanmedian(tv[max(0, k - 19):k + 1]) < LIQ_RS:
                continue
            lo_k = max(0, k + 1 - WINDOW)
            win = [{"open": o[j], "high": hi[j], "low": lo[j], "close": c[j], "volume": vol[j],
                    "delivery_pct": None if math.isnan(deliv[j]) else deliv[j]} for j in range(lo_k, k + 1)]
            f = fc.compute_features(win)
            ret20 = f.get("return_20d_pct")
            b20 = (bench_close[i] / bench_close[i - 20] - 1) * 100 if i >= 20 else None
            rs20 = None if ret20 is None or b20 is None else ret20 - b20
            sub = {"trend": scorer.score_trend(f), "momentum": scorer.score_momentum(f), "structure": scorer.score_structure(f),
                   "accumulation": scorer.score_accumulation(f), "sector": scorer.score_sector(rs20), "risk": scorer.score_risk(f)}
            b0 = sum(sub[x] * w[x] for x in sub)
            a = None if math.isnan(adx[k]) else float(adx[k])
            adx_term = ramp(a, 15, 25) * (1.0 if (not math.isnan(pdi[k]) and not math.isnan(mdi[k]) and pdi[k] > mdi[k]) else 0.0) if a is not None else 0.5
            rs63 = None
            if k >= 63 and i >= 63 and c[k - 63] > 0:
                rs63 = (c[k] / c[k - 63] - 1) * 100 - (nifty_close[i] / nifty_close[i - 63] - 1) * 100
            a2 = b0 - w["sector"] * sub["sector"] + w["sector"] * ramp(rs63, -10, 10)
            per_date.setdefault(i, []).append({"s": sym, "B0": b0, "A1": 0.9 * b0 + 0.1 * adx_term, "A2": a2,
                                               "A3": 0.9 * a2 + 0.1 * adx_term, "r": r})

    dates = sorted(d for d in per_date if len(per_date[d]) >= MIN_NAMES)
    first, last = dates[0], dates[-1]
    bounds = outcomes.split_bounds(first, last)
    rows = []
    for i in dates:
        split = outcomes.split_of(i, H, bounds, len(sessions) - 1)
        if split is None:
            continue
        u = per_date[i]
        mean_r = sum(x["r"] for x in u) / len(u)
        ex = [x["r"] - mean_r for x in u]
        rec = {"i": i, "date": str(pd.Timestamp(sessions[i]).date()), "split": split, "n": len(u),
               "regime": None if math.isnan(nifty_sma200[i]) else ("up" if nifty_close[i] > nifty_sma200[i] else "down")}
        for arm in ARMS:
            sc = [x[arm] for x in u]
            rec[f"ic_{arm}"] = stats.spearman(sc, ex)
            order = sorted(range(len(u)), key=lambda j: sc[j], reverse=True)
            top = order[: max(1, len(u) // 10)]
            med = sorted(ex)[len(ex) // 2]
            rec[f"top_net_{arm}"] = sum(u[j]["r"] for j in top) / len(top) - COST
            rec[f"top_spread_{arm}"] = sum(ex[j] for j in top) / len(top) - med
            rec[f"top_hit_{arm}"] = sum(1 for j in top if ex[j] > 0) / len(top)
        movers = sorted(all_r.get(i, []), key=lambda t: t[1], reverse=True)
        top_movers = movers[: max(1, len(movers) // 10)]
        in_u = {x["s"] for x in u}
        rec["coverage_top_movers_outside_universe"] = sum(1 for s, _ in top_movers if s not in in_u) / len(top_movers)
        rows.append(rec)

    rng = random.Random(SEED)
    result = {"registration_commit": "4c408401", "code_sha": code_sha, "sessions": len(sessions),
              "signal_dates": len(rows), "bounds": {k: [str(pd.Timestamp(sessions[a]).date()), str(pd.Timestamp(sessions[min(b, len(sessions)) - 1]).date())] for k, (a, b) in bounds.items()},
              "watermark": {"files": {p.name: file_sha(p) for p in sorted(data.glob("*.csv"))}, "bar_rows": int(len(bars)),
                            "input_hash": stats.canonical_hash([[str(x) for x in r] for r in bars[["symbol", "as_of_date", "adj_close"]].itertuples(index=False)])},
              "splits": {}}
    for split in ("discovery", "validation", "test"):
        part = [r for r in rows if r["split"] == split]
        sres = {"dates": len(part), "names_per_date_median": float(np.median([r["n"] for r in part])) if part else None, "arms": {}}
        for arm in ARMS:
            ic = [r[f"ic_{arm}"] for r in part if r[f"ic_{arm}"] is not None]
            entry = {"ic": stats.summarize(ic, NW_LAG),
                     "top_decile_net_mean": round(float(np.mean([r[f"top_net_{arm}"] for r in part])), 5) if part else None,
                     "top_minus_median": round(float(np.mean([r[f"top_spread_{arm}"] for r in part])), 5) if part else None,
                     "top_hit_rate": round(float(np.mean([r[f"top_hit_{arm}"] for r in part])), 4) if part else None}
            if arm != "B0":
                diff = [r[f"ic_{arm}"] - r["ic_B0"] for r in part if r[f"ic_{arm}"] is not None and r["ic_B0"] is not None]
                summ = stats.summarize(diff, NW_LAG)
                obs = sum(diff) / len(diff) if diff else 0.0
                blocks = [diff[j:j + PERM_BLOCK] for j in range(0, len(diff), PERM_BLOCK)]
                ge = 0
                for _ in range(PERM_DRAWS):
                    tot = sum((1 if rng.random() < 0.5 else -1) * sum(b) for b in blocks)
                    ge += (tot / len(diff)) >= obs if diff else 0
                by_regime = {}
                for reg in ("up", "down"):
                    d2 = [r[f"ic_{arm}"] - r["ic_B0"] for r in part if r["regime"] == reg and r[f"ic_{arm}"] is not None and r["ic_B0"] is not None]
                    by_regime[reg] = stats.summarize(d2, NW_LAG)
                entry["ic_diff_vs_B0"] = {**summ, "perm_p_one_sided": round((ge + 1) / (PERM_DRAWS + 1), 4), "by_regime": by_regime}
            sres["arms"][arm] = entry
        sres["coverage_top_movers_outside_universe"] = round(float(np.mean([r["coverage_top_movers_outside_universe"] for r in part])), 4) if part else None
        result["splits"][split] = sres

    def passes(split: str, arm: str) -> bool:
        d = result["splits"][split]["arms"][arm]["ic_diff_vs_B0"]
        return bool(d["mean"] is not None and d["mean"] > 0 and d["t"] is not None and d["t"] >= 2.0 and d["perm_p_one_sided"] < 0.05)

    decision = {}
    for arm in ("A1", "A2", "A3"):
        t_arm = result["splits"]["test"]["arms"][arm]
        t_b0 = result["splits"]["test"]["arms"]["B0"]
        reg = t_arm["ic_diff_vs_B0"]["by_regime"]
        same_sign = all(reg[x]["mean"] is not None and reg[x]["mean"] > 0 for x in ("up", "down"))
        checks = {"a_validation": passes("validation", arm), "b_test": passes("test", arm),
                  "c_test_net_spread_not_below_B0": (t_arm["top_minus_median"] or -1) >= (t_b0["top_minus_median"] or 0),
                  "d_test_same_sign_both_regimes": same_sign}
        decision[arm] = {"checks": checks, "adopt": all(checks.values())}
    adopted = next((a for a in ("A1", "A2", "A3") if decision[a]["adopt"]), None)
    result["decision"] = {"per_arm": decision, "adopted": adopted,
                          "verdict": f"adopt {adopted}" if adopted else "keep B0 (no arm met every pre-registered condition)"}
    (out / "result.json").write_text(json.dumps(result, indent=1, default=str))
    (out / "per_date.json").write_text(json.dumps(rows, default=str))
    print(json.dumps({k: result[k] for k in ("signal_dates", "bounds", "decision")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "unknown"))
