#!/usr/bin/env python3
"""Run the pre-registered Results-week study on the built dataset.

Design: docs/ai_research/EARNINGS_SURPRISE_PREREGISTRATION.md, §6–§9 (commit b3415111) and amendment A1 (commit c5bc89a1),
both registered before any statistic was computed. This script implements those sections and nothing else.

    python run_study.py <events.csv> <out_dir>

Needs numpy and pandas only (no scipy: the t distribution is computed here). Writes result.json and summary.md.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

B, SEED, ALPHA = 10_000, 20261027, 0.05
PRIMARY = ("2026-03-31", "2026-06-30")
ALL4 = ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")
SEASON_NAME = {"2025-09-30": "Oct–Nov 2025", "2025-12-31": "Jan–Feb 2026", "2026-03-31": "Apr–May 2026", "2026-06-30": "Jul–Aug 2026"}
MIN_GROUP, MIN_IC_H2, MIN_IC_FNO = 30, 100, 60


# ── distributions ────────────────────────────────────────────────────────────

def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > 1e-300 else 1e-300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > 1e-300 else 1e-300
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_sf(t: float, df: float) -> float:
    """P(T > t) for Student t."""
    x = df / (df + t * t)
    tail = 0.5 * betainc(df / 2.0, 0.5, x)
    return tail if t > 0 else 1.0 - tail


def holm(ps: Dict[str, float]) -> Dict[str, float]:
    items = sorted(ps.items(), key=lambda kv: kv[1])
    m, out, run = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


# ── statistics ───────────────────────────────────────────────────────────────

def rank(a: np.ndarray) -> np.ndarray:
    return pd.Series(a).rank(method="average").to_numpy()


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx, ry = rank(x), rank(y)
    sx, sy = rx.std(), ry.std()
    return float("nan") if sx == 0 or sy == 0 else float(np.corrcoef(rx, ry)[0, 1])


def winsorise(df: pd.DataFrame, col: str, base_mask: pd.Series) -> pd.Series:
    """Clip `col` at the 1st/99th percentile of each season's base sample (§6)."""
    out = df[col].copy()
    for s, g in df[base_mask & df[col].notna()].groupby("season"):
        lo, hi = g[col].quantile(0.01), g[col].quantile(0.99)
        m = df["season"].eq(s)
        out[m] = df.loc[m, col].clip(lo, hi)
    return out


class Season:
    """One season's rows, grouped by reaction date for the date-cluster bootstrap."""

    def __init__(self, g: pd.DataFrame, cols: Sequence[str]):
        self.dates = np.array(sorted(g["S"].unique()))
        idx = {d: i for i, d in enumerate(self.dates)}
        self.di = g["S"].map(idx).to_numpy()
        self.by_date = [np.flatnonzero(self.di == i) for i in range(len(self.dates))]
        self.cols = {c: g[c].to_numpy() for c in cols}
        self.n = len(g)

    def draw(self, rng: np.random.Generator) -> np.ndarray:
        pick = rng.integers(0, len(self.dates), len(self.dates))
        return np.concatenate([self.by_date[i] for i in pick]) if len(pick) else np.array([], int)


def run_test(name: str, df: pd.DataFrame, kind: str, seasons: Sequence[str], *, score: str = "", y: str = "",
             group: str = "", a: str = "", b: str = "", min_n: int = MIN_GROUP, direction: int = +1,
             welch_y: Optional[str] = None) -> Dict[str, Any]:
    """kind 'diff': mean(y | group == a) − mean(y | group == b) per season; kind 'ic': Spearman(score, y) per season.
    The decision statistic is the equal-weight mean over the seasons meeting the minimum. direction +1 tests > 0, −1 < 0."""
    cols = [y] + ([score] if kind == "ic" else [group])
    d = df[df["season"].isin(seasons)].dropna(subset=cols)
    if kind == "diff":
        d = d[d[group].isin([a, b])]
    per, objs = [], {}
    for s in seasons:
        g = d[d["season"] == s]
        if kind == "diff":
            ya, yb = g.loc[g[group] == a, y].to_numpy(), g.loc[g[group] == b, y].to_numpy()
            ok = len(ya) >= min_n and len(yb) >= min_n
            est = float(ya.mean() - yb.mean()) if len(ya) and len(yb) else float("nan")
            per.append({"season": s, "n_a": int(len(ya)), "n_b": int(len(yb)), "mean_a": float(ya.mean()) if len(ya) else None,
                        "mean_b": float(yb.mean()) if len(yb) else None, "estimate": est, "eligible": ok})
        else:
            ok = len(g) >= min_n
            est = spearman(g[score].to_numpy(), g[y].to_numpy()) if len(g) >= 3 else float("nan")
            per.append({"season": s, "n": int(len(g)), "estimate": est, "eligible": ok})
        if ok:
            objs[s] = Season(g, cols)
    elig = [p for p in per if p["eligible"]]
    res: Dict[str, Any] = {"name": name, "kind": kind, "direction": direction, "per_season": per, "seasons_eligible": len(elig)}
    if not elig:
        res.update(status="INSUFFICIENT", estimate=None)
        return res
    est = float(np.mean([p["estimate"] for p in elig]))
    rng = np.random.default_rng(SEED)
    boots, dropped = [], 0
    for _ in range(B):
        vals = []
        for s, o in objs.items():
            ix = o.draw(rng)
            yy = o.cols[y][ix]
            if kind == "diff":
                gg = o.cols[group][ix]
                ma, mb = yy[gg == a], yy[gg == b]
                vals.append(ma.mean() - mb.mean() if len(ma) and len(mb) else np.nan)
            else:
                vals.append(spearman(o.cols[score][ix].astype(float), yy.astype(float)))
        v = float(np.mean(vals))
        if math.isnan(v):
            dropped += 1
            continue
        boots.append(v)
    bt = np.array(boots)
    p_pos = (1 + np.sum(bt <= 0)) / (len(bt) + 1)
    p_neg = (1 + np.sum(bt >= 0)) / (len(bt) + 1)
    res.update(estimate=est, ci95=[float(np.percentile(bt, 2.5)), float(np.percentile(bt, 97.5))], draws=int(len(bt)),
               draws_dropped=dropped, p_one_sided=float(p_pos if direction > 0 else p_neg),
               p_opposite=float(p_neg if direction > 0 else p_pos), p_two_sided=float(min(1.0, 2 * min(p_pos, p_neg))),
               same_sign_all=all((p["estimate"] > 0) == (direction > 0) and p["estimate"] != 0 for p in elig))
    if kind == "diff":
        pooled = d[d["season"].isin([p["season"] for p in elig])]
        ya, yb = pooled.loc[pooled[group] == a, y].to_numpy(), pooled.loc[pooled[group] == b, y].to_numpy()
        va, vb = ya.var(ddof=1) / len(ya), yb.var(ddof=1) / len(yb)
        t = (ya.mean() - yb.mean()) / math.sqrt(va + vb)
        dfw = (va + vb) ** 2 / (va ** 2 / (len(ya) - 1) + vb ** 2 / (len(yb) - 1))
        res["welch"] = {"t": float(t), "df": float(dfw), "p_one_sided": float(t_sf(direction * t, dfw)),
                        "pooled_diff": float(ya.mean() - yb.mean())}
    else:
        pooled = d[d["season"].isin([p["season"] for p in elig])]
        res["pooled_ic"] = spearman(pooled[score].to_numpy(), pooled[y].to_numpy())
        res["pooled_n"] = int(len(pooled))
    k = len(elig)
    if k >= 3:
        e = np.array([p["estimate"] for p in elig])
        sd = e.std(ddof=1)
        t = e.mean() / (sd / math.sqrt(k)) if sd > 0 else float("inf")
        res["cross_season_t"] = {"t": float(t), "df": k - 1, "p_one_sided": float(t_sf(direction * t, k - 1))}
    return res


def label(test: Dict[str, Any], adj: float, adj_opp: float) -> str:
    if test.get("status") == "INSUFFICIENT":
        return "INSUFFICIENT"
    if adj < ALPHA and test["same_sign_all"]:
        return "PASS"
    if adj_opp < ALPHA and (test["estimate"] * test["direction"]) < 0:
        return "REVERSED"
    return "FAIL"


def family(tests: List[Dict[str, Any]]) -> None:
    ok = [t for t in tests if t.get("status") != "INSUFFICIENT"]
    adj = holm({t["name"]: t["p_one_sided"] for t in ok})
    adj_o = holm({t["name"]: t["p_opposite"] for t in ok})
    for t in tests:
        t["holm_p"] = adj.get(t["name"])
        t["holm_p_opposite"] = adj_o.get(t["name"])
        t["verdict"] = label(t, adj.get(t["name"], 1.0), adj_o.get(t["name"], 1.0))


def main(events_csv: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(events_csv, dtype={"season": str})
    for c in ("liquid", "fno_m1", "fno_s"):
        df[c] = df[c].astype(str).str.lower().eq("true")
    liq = df["liquid"]
    for m in ("R1x", "R5x", "D5x"):
        df[m + "_w"] = winsorise(df, m, liq)           # §6: base = the season's liquid sample
        df[m + "_wa"] = winsorise(df, m, df[m].notna())  # S5a: base = every event
    L = df[liq].copy()
    R: Dict[str, Any] = {"counts": {}, "families": {}, "secondary": {}, "exploratory": {}}
    for s, g in df.groupby("season"):
        gl = g[g["liquid"]]
        R["counts"][s] = {"events": int(len(g)), "liquid": int(len(gl)), "R5x": int(gl["R5x"].notna().sum()),
                          "R1x": int(gl["R1x"].notna().sum()), "D5x": int(gl["D5x"].notna().sum()),
                          "verdict": gl["verdict"].value_counts().to_dict(), "l_verdict": gl["l_verdict"].value_counts().to_dict(),
                          "h5": gl["h5"].value_counts().to_dict(), "fno_m1": int(gl["fno_m1"].sum()), "fno_s": int(gl["fno_s"].sum())}

    # F1 registered formulas
    F1 = [run_test("H1-R5", L, "diff", PRIMARY, y="R5x_w", group="verdict", a="above", b="below"),
          run_test("H1-R1", L, "diff", PRIMARY, y="R1x_w", group="verdict", a="above", b="below"),
          run_test("H2", L, "ic", PRIMARY, score="composite", y="R5x", min_n=MIN_IC_H2),
          run_test("H3", L[L["fno_m1"]], "ic", ALL4, score="upcoming", y="R5x", min_n=MIN_IC_FNO),
          run_test("H4", L[L["fno_s"]], "ic", PRIMARY, score="declared", y="D5x", min_n=MIN_IC_FNO)]
    family(F1)
    # F7 live code (S7)
    F7 = [run_test("S7-H1-R5", L, "diff", PRIMARY, y="R5x_w", group="l_verdict", a="above", b="below"),
          run_test("S7-H1-R1", L, "diff", PRIMARY, y="R1x_w", group="l_verdict", a="above", b="below"),
          run_test("S7-H2", L, "ic", PRIMARY, score="l_composite", y="R5x", min_n=MIN_IC_H2),
          run_test("S7-H3", L[L["fno_m1"]], "ic", ALL4, score="l_upcoming", y="R5x", min_n=MIN_IC_FNO),
          run_test("S7-H4", L[L["fno_s"]], "ic", PRIMARY, score="l_declared", y="D5x", min_n=MIN_IC_FNO)]
    family(F7)
    # F5 results strength (A1.1)
    F5 = [run_test("H5-STRONG-D5", L, "diff", ALL4, y="D5x_w", group="h5", a="strong", b="unflagged"),
          run_test("H5-STRONG-R5", L, "diff", ALL4, y="R5x_w", group="h5", a="strong", b="unflagged"),
          run_test("H5-WEAK-D5", L, "diff", ALL4, y="D5x_w", group="h5", a="weak", b="unflagged", direction=-1),
          run_test("H5-WEAK-R5", L, "diff", ALL4, y="R5x_w", group="h5", a="weak", b="unflagged", direction=-1)]
    family(F5)
    R["families"] = {"F1": F1, "F7": F7, "F5": F5}
    sec = R["secondary"]
    sec["H5-R1"] = [run_test("H5-STRONG-R1", L, "diff", ALL4, y="R1x_w", group="h5", a="strong", b="unflagged"),
                    run_test("H5-WEAK-R1", L, "diff", ALL4, y="R1x_w", group="h5", a="weak", b="unflagged", direction=-1)]
    sec["H5-full-2seasons"] = [run_test(f"H5full-{g}-{m}", L, "diff", PRIMARY, y=f"{m}x_w", group="h5_full", a=g, b="unflagged",
                                        direction=+1 if g == "strong" else -1) for g in ("strong", "weak") for m in ("D5", "R5")]
    sec["H5-growth-4seasons"] = [run_test(f"H5growth-{g}-{m}", L, "diff", ALL4, y=f"{m}x_w", group="h5_growth", a=g, b="unflagged",
                                          direction=+1 if g == "strong" else -1) for g in ("strong", "weak") for m in ("D5", "R5")]
    sec["S1"] = [run_test("S1-H1-R5", L, "diff", ALL4, y="R5x_w", group="srw_verdict", a="above", b="below"),
                 run_test("S1-H1-R1", L, "diff", ALL4, y="R1x_w", group="srw_verdict", a="above", b="below"),
                 run_test("S1-H2", L, "ic", ALL4, score="srw_composite", y="R5x", min_n=MIN_IC_H2)]
    sec["S2"] = [run_test("S2-R5", L, "diff", PRIMARY, y="R5x_w", group="pat_verdict", a="above", b="below"),
                 run_test("S2-R1", L, "diff", PRIMARY, y="R1x_w", group="pat_verdict", a="above", b="below")]
    sec["S3"] = [run_test("S3-R5", L, "diff", ("2026-06-30",), y="R5x_w", group="s3_verdict", a="above", b="below"),
                 run_test("S3-R1", L, "diff", ("2026-06-30",), y="R1x_w", group="s3_verdict", a="above", b="below")]
    sec["S4"] = [run_test("S4-R1", L, "ic", PRIMARY, score="pat_vs_mid_pct", y="R1x", min_n=MIN_IC_H2),
                 run_test("S4-R5", L, "ic", PRIMARY, score="pat_vs_mid_pct", y="R5x", min_n=MIN_IC_H2)]
    sec["S5"] = [run_test("S5a-noliq-R5", df, "diff", PRIMARY, y="R5x_wa", group="verdict", a="above", b="below"),
                 run_test("S5a-noliq-R1", df, "diff", PRIMARY, y="R1x_wa", group="verdict", a="above", b="below"),
                 run_test("S5b-unwins-R5", L, "diff", PRIMARY, y="R5x", group="verdict", a="above", b="below"),
                 run_test("S5b-unwins-R1", L, "diff", PRIMARY, y="R1x", group="verdict", a="above", b="below")]
    comp_h2 = [run_test(f"S6-H2-{c}", L, "ic", PRIMARY, score=c, y="R5x", min_n=MIN_IC_H2) for c in ("surprise", "trend", "quality")]
    comp_h3 = [run_test(f"S6-H3-{c}", L[L["fno_m1"]], "ic", ALL4, score=c, y="R5x", min_n=MIN_IC_FNO)
               for c in ("tech_m1", "oi_m1", "past", "trend_up")]
    for grp in (comp_h2, comp_h3):          # §9(b): Holm within the score's components, two-sided
        ok = [t for t in grp if t.get("status") != "INSUFFICIENT"]
        adj = holm({t["name"]: t["p_two_sided"] for t in ok})
        for t in grp:
            t["holm_p_two_sided"] = adj.get(t["name"])
            t["harmful_provisional"] = bool(t.get("estimate") is not None and t["estimate"] < 0 and adj.get(t["name"], 1) < ALPHA)
    sec["S6"] = comp_h2 + comp_h3
    ex = R["exploratory"]
    Lf, Ln = L[L["fno_m1"]], L[~L["fno_m1"]]
    ex["E1"] = [run_test("E1-FnO-R5", Lf, "diff", PRIMARY, y="R5x_w", group="verdict", a="above", b="below"),
                run_test("E1-FnO-R1", Lf, "diff", PRIMARY, y="R1x_w", group="verdict", a="above", b="below"),
                run_test("E1-nonFnO-R5", Ln, "diff", PRIMARY, y="R5x_w", group="verdict", a="above", b="below"),
                run_test("E1-nonFnO-R1", Ln, "diff", PRIMARY, y="R1x_w", group="verdict", a="above", b="below")]
    ex["E2"] = [run_test("E2-outlook", L, "ic", ("2026-06-30",), score="outlook", y="R5x", min_n=MIN_IC_FNO),
                run_test("E2-composite+outlook", L[L["outlook"].notna()], "ic", ("2026-06-30",), score="composite_outlook", y="R5x", min_n=MIN_IC_FNO)]
    # registered decisions
    v = {t["name"]: t for t in F1 + F7 + F5}
    dec: Dict[str, Any] = {}
    for out_name, h, s7 in (("verdict pills", "H1-R5", "S7-H1-R5"), ("composite score", "H2", "S7-H2"),
                            ("upcoming ideas order", "H3", "S7-H3"), ("declared ideas order", "H4", "S7-H4")):
        a_, b_ = v[h]["verdict"], v[s7]["verdict"]
        if "REVERSED" in (a_, b_):
            lab = "reversed in testing"
        elif a_ == b_ == "PASS":
            lab = "early evidence; confirmation pending (Oct–Nov 2026)"
        elif "INSUFFICIENT" in (a_, b_) and "FAIL" not in (a_, b_):
            lab = "not yet tested"
        else:
            lab = "no measurable skill so far"
        dec[out_name] = {"registered": a_, "live_code": b_, "label": lab}
    boost = {}
    for grp, dname, rname, pts in (("STRONG", "H5-STRONG-D5", "H5-STRONG-R5", 10), ("WEAK", "H5-WEAK-D5", "H5-WEAK-R5", -10)):
        dt, rt = v[dname], v[rname]
        if dt["verdict"] == "PASS":
            val = pts
        elif rt["verdict"] == "PASS" and dt.get("estimate") is not None and dt["estimate"] * (1 if pts > 0 else -1) > 0:
            val = pts // 2
        else:
            val = 0
        boost[grp] = {"D5": dt["verdict"], "R5": rt["verdict"], "points": val, "reversed_flag": dt["verdict"] == "REVERSED"}
    dec["results_strength_boost"] = boost
    dec["harmful_components_provisional"] = [t["name"] for t in sec["S6"] if t.get("harmful_provisional")]
    R["decisions"] = dec
    (out / "result.json").write_text(json.dumps(R, indent=1, default=str))
    print(json.dumps(dec, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
