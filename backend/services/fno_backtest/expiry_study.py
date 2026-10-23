"""Stage B2: per-expiry futures signals (near / next / far) on the bhavcopy year. Pre-registered in
docs/FO_STAGE_B2_EXPIRY_CURVE_PREREGISTRATION.md and docs/FO_STAGE_B_AMENDMENT_20261023_EXPIRY_AWARE_STUDY.md (committed before this ran).

Pure functions over plain rows: no network, no database. Every number comes from the contract's own bhavcopy row; nothing is summed across
expiries. One observation per underlying-session per setting per configuration; the session is the statistical unit."""
from __future__ import annotations

import random
from bisect import bisect_left, bisect_right
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import outcomes, stats

STUDY_VERSION = "fno-expiry-study-b2-v1"
FROZEN_BASELINE_HASH = "c5b125ba612073e0ce4e2c69b18c49c483c9bc813abcd7341a48a490ed287ea1"
CATEGORIES = ("long_buildup", "short_buildup", "short_covering", "long_unwinding")
BULL = {"long_buildup": 1, "short_covering": 1, "short_buildup": -1, "long_unwinding": -1}
PRICE_UP = {"long_buildup": 1, "short_covering": 1, "short_buildup": -1, "long_unwinding": -1}
OI_UP = {"long_buildup": 1, "short_buildup": 1, "short_covering": -1, "long_unwinding": -1}
CAT_OF = {(1, 1): "long_buildup", (-1, 1): "short_buildup", (1, -1): "short_covering", (-1, -1): "long_unwinding"}
BUCKETS = ("near", "next", "far")
CONFIGS = ("near_only", "next_only", "far_only", "near_next_agree", "all_agree", "disagree_follow_near", "disagree_follow_next")
HORIZONS = outcomes.HORIZONS
PRIMARY_H = 5
VOL_LOOKBACK = 20
ROLL_WD = 3
WINDOWS = {"U": ("2025-10-01", "2025-12-26"), "D": ("2025-12-29", "2026-06-25"), "V": ("2026-06-29", "2026-08-21"), "T": ("2026-08-24", None)}
ACCEPT = ("U", "V", "T")
MIN_POOLED_SESSIONS = 30
T_CRIT = 1.645
SELECT_MIN_SIGNALS = 100
N_PERM = 200
SEED = 20261023
COST_BASE, COST_STRESS = outcomes.COSTS["round_trip_pct_base"], outcomes.COSTS["round_trip_pct_stress"]
Thr = Tuple[float, float, Optional[float]]
NO_THRESHOLD: Thr = (0.0, 0.0, None)
PRODUCTION_FLOORS: Thr = (0.5, 3.0, None)


def weekdays_to(day: str, expiry: str) -> int:
    """Mon-Fri days in (day, expiry]; 0 on the expiry day. Holidays are ignored (a stated limit)."""
    a, b = date.fromisoformat(day), date.fromisoformat(expiry)
    if b <= a:
        return 0
    full, extra = divmod((b - a).days, 7)
    n = full * 5
    d = a.toordinal()
    for k in range(1, extra + 1):
        if date.fromordinal(d + k).weekday() < 5:
            n += 1
    return n


def build_buckets(rows: Sequence[Dict[str, Any]], sessions: Sequence[str]) -> Dict[str, Dict[str, List[Optional[Dict[str, Any]]]]]:
    """sym -> day -> [near, next, far] (None when that expiry is absent or has no usable numbers). Each bucket is that contract's own:
    price change %, OI change % (change in OI over the previous OI), relative volume (its volume over the mean of the same bucket's previous
    20 sessions), expiry, weekdays to expiry, whether the near contract changed since the previous session, and whether it is the biggest-OI contract."""
    by: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for r in rows:
        by.setdefault(r["sym"], {}).setdefault(r["day"], []).append(r)
    out: Dict[str, Dict[str, List[Optional[Dict[str, Any]]]]] = {}
    for sym, days in by.items():
        hist: List[List[float]] = [[], [], []]
        prev_near: Optional[str] = None
        per: Dict[str, List[Optional[Dict[str, Any]]]] = {}
        for day in sorted(days):
            cs = sorted((c for c in days[day] if c["exp"] >= day), key=lambda c: c["exp"])[:3]
            top = max((c["oi"] for c in cs), default=0)
            row: List[Optional[Dict[str, Any]]] = [None, None, None]
            for b, c in enumerate(cs):
                vols = hist[b][-VOL_LOOKBACK:]
                rvol = None
                if len(vols) >= VOL_LOOKBACK and sum(vols) > 0 and c["vol"] is not None:
                    rvol = c["vol"] / (sum(vols) / len(vols))
                base = c["oi"] - c["coi"] if c["oi"] is not None and c["coi"] is not None else None
                if c["c"] and c["pc"] and c["c"] > 0 and c["pc"] > 0 and base and base > 0:
                    row[b] = {"p": (c["c"] / c["pc"] - 1.0) * 100.0, "o": c["coi"] / base * 100.0, "rvol": rvol, "exp": c["exp"],
                              "wd": weekdays_to(day, c["exp"]), "liquid": bool(c["oi"] == top), "oi": c["oi"]}
                if c["vol"] is not None:
                    hist[b].append(float(c["vol"]))
            if row[0] is not None:
                row[0]["post_expiry"] = prev_near is not None and row[0]["exp"] != prev_near
                prev_near = row[0]["exp"]
            elif cs:
                prev_near = cs[0]["exp"]
            if any(row):
                per[day] = row
        out[sym] = per
    return out


def category(e: Optional[Dict[str, Any]], thr: Thr) -> Optional[str]:
    """The build-up category of one bucket under a setting, or None. A zero price or OI change is neutral and never fires."""
    if e is None:
        return None
    p, o = e["p"], e["o"]
    if p == 0 or o == 0:
        return None
    price_floor, oi_floor, rvol_floor = thr
    if abs(p) < price_floor or abs(o) < oi_floor:
        return None
    if rvol_floor is not None and (e["rvol"] is None or e["rvol"] < rvol_floor):
        return None
    return CAT_OF[(1 if p > 0 else -1, 1 if o > 0 else -1)]


def window_bounds(sessions: Sequence[str]) -> Dict[str, Tuple[int, int]]:
    """Signal-session index ranges [lo, hi) for the windows; the last one (named 'test' for outcomes.split_of) runs to the end of the data."""
    out: Dict[str, Tuple[int, int]] = {}
    for name, (start, end) in WINDOWS.items():
        lo = bisect_left(sessions, start)
        hi = len(sessions) if end is None else bisect_right(sessions, end)
        out["test" if name == "T" else name] = (lo, hi)
    return out


class Outcomes:
    """Forward returns of the underlying's adjusted cash price, minus the equal-weight universe (primary) or same-industry (second) benchmark."""

    def __init__(self, sessions: Sequence[str], adjusted: Dict[str, List[Dict[str, Any]]], industry: Dict[str, str]):
        self.sessions = list(sessions)
        px = outcomes.price_index({s: [{"adj_open": r["o"], "adj_close": r["c"], "as_of_date": r["day"]} for r in v] for s, v in adjusted.items()})
        n = len(self.sessions)
        self.ret: Dict[Tuple[str, int, int], float] = {}
        for sym in px:
            for i in range(n - 1):
                for h in HORIZONS:
                    r = outcomes.forward_return(px, sym, self.sessions, i, h)
                    if r is not None:
                        self.ret[(sym, i, h)] = r
        by_i: Dict[Tuple[int, int], List[Tuple[str, float]]] = {}
        for (sym, i, h), r in self.ret.items():
            by_i.setdefault((i, h), []).append((sym, r))
        self.ew: Dict[Tuple[int, int], float] = {k: sum(r for _, r in v) / len(v) for k, v in by_i.items() if len(v) >= 10}
        self.ind: Dict[Tuple[str, int, int], float] = {}
        for (i, h), v in by_i.items():
            groups: Dict[str, List[Tuple[str, float]]] = {}
            for sym, r in v:
                if industry.get(sym):
                    groups.setdefault(industry[sym], []).append((sym, r))
            for g in groups.values():
                total = sum(r for _, r in g)
                for sym, r in g:
                    if len(g) - 1 >= 3:
                        self.ind[(sym, i, h)] = (total - r) / (len(g) - 1)

    def rel(self, sym: str, i: int, h: int, bench: str = "ew") -> Optional[float]:
        r = self.ret.get((sym, i, h))
        if r is None:
            return None
        b = self.ew.get((i, h)) if bench == "ew" else self.ind.get((sym, i, h))
        return None if b is None else r - b


Signal = Tuple[int, str, int]       # (session index, symbol, direction +1/-1)


def evaluate(signals: Sequence[Signal], out: Outcomes, bounds: Dict[str, Tuple[int, int]], h: int, cost: float = COST_BASE,
             bench: str = "ew") -> Dict[str, Dict[str, Any]]:
    """Per window (U, D, V, T) and pooled U+V+T: the session-level series of mean net benchmark-relative return (direction-adjusted), its
    Newey-West summary and counts. A signal whose forward window leaves its window is excluded from it."""
    last = len(out.sessions) - 1
    per: Dict[str, Dict[int, List[float]]] = {w: {} for w in WINDOWS}
    for i, sym, d in signals:
        r = out.rel(sym, i, h, bench)
        if r is None:
            continue
        name = outcomes.split_of(i, h, bounds, last)
        if name is None:
            continue
        per["T" if name == "test" else name].setdefault(i, []).append(d * r - cost)
    res: Dict[str, Dict[str, Any]] = {}
    lag = max(h - 1, 0)
    pooled: Dict[int, List[float]] = {}
    for w, sessions in per.items():
        series = [sum(v) / len(v) for _, v in sorted(sessions.items())]
        s = stats.summarize(series, lag)
        s["n_signals"], s["n_sessions"] = sum(len(v) for v in sessions.values()), len(series)
        res[w] = s
        if w in ACCEPT:
            pooled.update(sessions)
    series = [sum(v) / len(v) for _, v in sorted(pooled.items())]
    s = stats.summarize(series, lag)
    s["n_signals"], s["n_sessions"] = sum(len(v) for v in pooled.values()), len(series)
    res["pooled"] = s
    return res


def _thr_cats(buckets: Dict[str, Dict[str, List[Optional[Dict[str, Any]]]]], thrs: Sequence[Thr], sessions: Sequence[str]) -> Dict[Thr, Dict[Tuple[str, int], Tuple[Optional[str], Optional[str], Optional[str]]]]:
    idx = {d: i for i, d in enumerate(sessions)}
    out: Dict[Thr, Dict[Tuple[str, int], Tuple[Optional[str], ...]]] = {t: {} for t in thrs}
    for sym, days in buckets.items():
        for day, row in days.items():
            i = idx[day]
            for t in thrs:
                cs = tuple(category(e, t) for e in row)
                if any(cs):
                    out[t][(sym, i)] = cs
    return out


def config_signals(cfg: str, cat: str, cats: Dict[Tuple[str, int], Tuple[Optional[str], ...]]) -> List[Signal]:
    """One signal per underlying-session for a configuration and a category. Direction is that of the category driving it."""
    d = BULL[cat]
    sig: List[Signal] = []
    for (sym, i), cs in cats.items():
        near, nxt, far = cs
        if cfg == "near_only":
            ok, dd = near == cat, d
        elif cfg == "next_only":
            ok, dd = nxt == cat, d
        elif cfg == "far_only":
            ok, dd = far == cat, d
        elif cfg == "near_next_agree":
            ok, dd = near == cat and nxt == cat, d
        elif cfg == "all_agree":
            ok, dd = near == cat and nxt == cat and far == cat, d
        elif cfg == "disagree_follow_near":
            ok, dd = near == cat and nxt is not None and BULL[nxt] == -d, d
        elif cfg == "disagree_follow_next":
            ok, dd = nxt == cat and near is not None and BULL[near] == -d, d
        else:
            raise ValueError(cfg)
        if ok:
            sig.append((i, sym, dd))
    return sig


def mean_of(res: Dict[str, Any]) -> Optional[float]:
    return res.get("mean")


def verdict(settings: Dict[str, Dict[str, Any]], frozen_labels: Sequence[str], perm_p: Optional[float], needs_perm: bool) -> Dict[str, Any]:
    """Pre-registered rule on the pooled U+V+T primary-horizon result of the 5 frozen settings."""
    pos_any = sum(1 for k in frozen_labels if (settings[k]["pooled"]["mean"] or 0) > 0)
    qual = [k for k in frozen_labels if settings[k]["pooled"]["n_sessions"] >= MIN_POOLED_SESSIONS]
    pos = sum(1 for k in qual if (settings[k]["pooled"]["mean"] or 0) > 0)
    strong = sum(1 for k in qual if (settings[k]["pooled"]["t"] or 0) >= T_CRIT)
    perm_ok = (not needs_perm) or (perm_p is not None and perm_p <= 0.05)
    if pos >= 3 and strong >= 2 and perm_ok:
        v = "supported"
    elif pos_any == 0:
        v = "not_supported"
    else:
        v = "inconclusive"
    return {"verdict": v, "positive_qualifying": pos, "t_at_least_1_645": strong, "positive_any": pos_any, "qualifying_settings": len(qual), "permutation_p_first_setting": perm_p}


def pooled_mean_of_frozen(settings: Dict[str, Dict[str, Any]], labels: Sequence[str]) -> Optional[float]:
    vals = [settings[k]["pooled"]["mean"] for k in labels if settings[k]["pooled"]["mean"] is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def permutation(buckets, out: Outcomes, bounds, settings: Dict[str, Tuple[str, Thr]], n_perm: int = N_PERM, seed: int = SEED) -> Dict[str, Any]:
    """OI changes shuffled across underlyings within each session on the near bucket (price, volume and the outcome are untouched), primary
    horizon, pooled U+V+T. settings: label -> (category, threshold). Returns the actual pooled mean and the one-sided p-value per label."""
    sessions = out.sessions
    idx = {d: i for i, d in enumerate(sessions)}
    last = len(sessions) - 1
    per_i: Dict[int, List[Tuple[str, float, Optional[float], float, float]]] = {}
    for sym, days in buckets.items():
        for day, row in days.items():
            e = row[0]
            i = idx[day]
            if e is None:
                continue
            nm = outcomes.split_of(i, PRIMARY_H, bounds, last)
            if nm is None or nm == "D":
                continue
            r = out.rel(sym, i, PRIMARY_H)
            if r is not None:
                per_i.setdefault(i, []).append((sym, e["p"], e["rvol"], e["o"], r))
    rng = random.Random(seed)
    order = sorted(per_i)

    def pooled(os_by_i: Dict[int, List[float]], label: str) -> Optional[float]:
        c, (P, O, R) = settings[label]
        vals: List[float] = []
        for i in order:
            items, os_ = per_i[i], os_by_i[i]
            acc = []
            for (sym, p, rv, _o, r), o in zip(items, os_):
                if p == 0 or o == 0 or abs(p) < P or abs(o) < O or (R is not None and (rv is None or rv < R)):
                    continue
                if CAT_OF[(1 if p > 0 else -1, 1 if o > 0 else -1)] == c:
                    acc.append(BULL[c] * r - COST_BASE)
            if acc:
                vals.append(sum(acc) / len(acc))
        return sum(vals) / len(vals) if vals else None

    actual = {k: pooled({i: [x[3] for x in per_i[i]] for i in order}, k) for k in settings}
    ge = {k: 0 for k in settings}
    valid = {k: 0 for k in settings}
    for _ in range(n_perm):
        os_by_i = {}
        for i in order:
            os_ = [x[3] for x in per_i[i]]
            rng.shuffle(os_)
            os_by_i[i] = os_
        for k in settings:
            m = pooled(os_by_i, k)
            if m is None or actual[k] is None:
                continue
            valid[k] += 1
            ge[k] += 1 if m >= actual[k] else 0
    return {k: {"actual_pooled_mean": None if actual[k] is None else round(actual[k], 4), "perms": valid[k],
                "p_one_sided": None if valid[k] == 0 else round((ge[k] + 1) / (valid[k] + 1), 4)} for k in settings}


def run(inputs: Dict[str, Any], frozen: Dict[str, List[Thr]], code_version: str = "", generated_at: Optional[str] = None, n_perm: int = N_PERM) -> Dict[str, Any]:
    """inputs: stf (rows {day, sym, exp, c, pc, oi, coi, vol}), adjusted (sym -> rows {day, o, c}), industry (sym -> industry).
    frozen: category -> the 5 frozen thresholds from the baseline report (hash FROZEN_BASELINE_HASH)."""
    rows = inputs["stf"]
    sessions = sorted({r["day"] for r in rows})
    buckets = build_buckets(rows, sessions)
    out = Outcomes(sessions, inputs["adjusted"], inputs.get("industry") or {})
    bounds = window_bounds(sessions)
    labels = [f"f{k + 1}" for k in range(5)]
    per_cat_thr: Dict[str, Dict[str, Thr]] = {c: {**{labels[k]: tuple(t) for k, t in enumerate(frozen[c])}, "no_threshold": NO_THRESHOLD, "production_floors": PRODUCTION_FLOORS} for c in CATEGORIES}
    thrs = sorted({t for c in CATEGORIES for t in per_cat_thr[c].values()}, key=lambda t: (t[0], t[1], t[2] or 0))
    cats = _thr_cats(buckets, thrs, sessions)
    tested = 0
    configs: Dict[str, Dict[str, Any]] = {}
    for cfg in CONFIGS:
        configs[cfg] = {}
        for c in CATEGORIES:
            settings: Dict[str, Dict[str, Any]] = {}
            for label, thr in per_cat_thr[c].items():
                sig = config_signals(cfg, c, cats[thr])
                h5 = evaluate(sig, out, bounds, PRIMARY_H)
                entry: Dict[str, Any] = {"threshold": {"price_pct": thr[0], "oi_pct": thr[1], "rvol": thr[2]}, **h5,
                                         "pooled_by_horizon": {str(h): evaluate(sig, out, bounds, h)["pooled"] for h in HORIZONS if h != PRIMARY_H},
                                         "pooled_industry_relative_h5": evaluate(sig, out, bounds, PRIMARY_H, bench="ind")["pooled"]}
                m = h5["pooled"]["mean"]
                entry["pooled_mean_stress_cost_h5"] = None if m is None else round(m - (COST_STRESS - COST_BASE), 4)
                settings[label] = entry
                tested += 1 + len(HORIZONS)
            configs[cfg][c] = {"settings": settings}
    perm_settings = {f"{c}:{lab}": (c, per_cat_thr[c][lab]) for c in CATEGORIES for lab in ("f1", "production_floors")}
    perm = permutation(buckets, out, bounds, perm_settings, n_perm=n_perm)
    for cfg in CONFIGS:
        for c in CATEGORIES:
            p = perm[f"{c}:f1"]["p_one_sided"] if cfg == "near_only" else None
            configs[cfg][c]["verdict"] = verdict(configs[cfg][c]["settings"], labels, p, cfg == "near_only")
            configs[cfg][c]["frozen_pooled_mean_h5"] = pooled_mean_of_frozen(configs[cfg][c]["settings"], labels)
    # expiry selection: learned on D only, evaluated unchanged on U, V, T
    selection: Dict[str, Any] = {}
    for c in CATEGORIES:
        scored = {}
        for cfg, name in (("near_only", "near"), ("next_only", "next"), ("far_only", "far")):
            s = configs[cfg][c]["settings"]
            ms = [s[k]["D"]["mean"] for k in labels if s[k]["D"]["mean"] is not None]
            n = sum(s[k]["D"]["n_signals"] for k in labels)
            scored[name] = {"d_mean_h5": round(sum(ms) / len(ms), 4) if ms else None, "d_signals": n}
        ok = {k: v for k, v in scored.items() if v["d_mean_h5"] is not None and v["d_signals"] >= SELECT_MIN_SIGNALS}
        chosen = max(ok, key=lambda k: ok[k]["d_mean_h5"]) if ok else "near"
        cfg = {"near": "near_only", "next": "next_only", "far": "far_only"}[chosen]
        selection[c] = {"discovery": scored, "chosen": chosen, "evaluated_unchanged": {w: [configs[cfg][c]["settings"][k][w] for k in labels] for w in ACCEPT},
                        "verdict_of_chosen": configs[cfg][c]["verdict"]["verdict"]}
    # hypotheses
    hyp: Dict[str, Any] = {}
    for c in CATEGORIES:
        v = {cfg: configs[cfg][c]["verdict"]["verdict"] for cfg in CONFIGS}
        m = {cfg: configs[cfg][c]["frozen_pooled_mean_h5"] for cfg in CONFIGS}
        near_m = m["near_only"]
        better = lambda x: m[x] is not None and near_m is not None and m[x] > near_m  # noqa: E731
        hyp[c] = {"A_near_only_supported": v["near_only"] == "supported",
                  "B_deferred_expiry_supported_and_better_than_near": any(v[x] == "supported" and better(x) for x in ("next_only", "far_only")),
                  "C_agreement_supported_and_better_than_near": any(v[x] == "supported" and better(x) for x in ("near_next_agree", "all_agree")),
                  "verdicts": v, "frozen_pooled_mean_h5": m}
    out_rep: Dict[str, Any] = {
        "study": STUDY_VERSION, "stage": "B2 expiry curve (bhavcopy year)", "validated": False, "baseline_hash": FROZEN_BASELINE_HASH,
        "data_window": {"first_session": sessions[0], "last_session": sessions[-1], "sessions": len(sessions), "underlyings": len(buckets),
                        "windows": {k: [sessions[min(lo, len(sessions) - 1)], sessions[hi - 1]] for k, (lo, hi) in bounds.items()}},
        "assumptions": {"cost": outcomes.COSTS, "primary_horizon": PRIMARY_H, "volume_lookback_sessions": VOL_LOOKBACK, "roll_window_weekdays": ROLL_WD,
                        "entry": "next session open (adjusted cash price)", "benchmark": "equal-weight F&O universe (primary); same-industry equal-weight excluding the stock, >=3 peers (second)",
                        "holidays": "weekdays used for days to expiry; exchange holidays ignored"},
        "frozen_thresholds": {c: [list(t) for t in frozen[c]] for c in CATEGORIES},
        "configs": configs, "permutation": perm, "expiry_selection": selection, "hypotheses": hyp,
        "tested_configurations": tested, "limitations": [
            "One year of data (260 sessions); U has 59 sessions. All three windows are one regime sequence.",
            "Cash returns proxy a futures trade; the 0.15% round-trip cost is assumed.",
            "Far-month contracts are thin; far_only is expected to be noisy. Weekdays to expiry ignore exchange holidays.",
            "Clustering by underlying and cross-sectional dependence beyond the session mean are not modelled.",
            "A missing adjusted price (for example the 2026-02-01 session) removes the outcome; it is never filled.",
            "Nothing here is validated; a 'supported' verdict still needs live shadow validation."],
    }
    out_rep["roll_and_timing"] = roll_analysis(buckets, cats, out, bounds, per_cat_thr)
    out_rep["agreement_and_migration"] = agreement_migration(buckets, cats, out, bounds, per_cat_thr)
    out_rep["price_only_baseline"] = price_only(buckets, out, bounds, per_cat_thr, sessions)
    out_rep["experiment_id"] = "fo-b2-" + stats.canonical_hash({"stf_rows": len(rows), "sessions": [sessions[0], sessions[-1]], "frozen": out_rep["frozen_thresholds"], "v": STUDY_VERSION})[:12]
    out_rep["code_version"], out_rep["generated_at"] = code_version, generated_at
    out_rep["report_hash"] = stats.canonical_hash({k: v for k, v in out_rep.items() if k not in ("generated_at", "report_hash")})
    return out_rep


def _near_signals(cats: Dict[Tuple[str, int], Tuple[Optional[str], ...]], c: str) -> List[Tuple[int, str, Tuple[Optional[str], ...]]]:
    return [(i, sym, cs) for (sym, i), cs in cats.items() if cs[0] == c]


def roll_analysis(buckets, cats, out: Outcomes, bounds, per_cat_thr) -> Dict[str, Any]:
    """near_only under production_floors and no_threshold, pooled U+V+T, split by distance to expiry and by the session after a roll."""
    idx = {d: i for i, d in enumerate(out.sessions)}
    day_of = out.sessions
    groups = {"outside_roll_window": lambda e: e["wd"] > ROLL_WD, "roll_window_1_to_3": lambda e: 1 <= e["wd"] <= ROLL_WD, "expiry_day": lambda e: e["wd"] == 0,
              "first_session_after_expiry": lambda e: bool(e.get("post_expiry")), "wd_0_3": lambda e: e["wd"] <= 3, "wd_4_10": lambda e: 4 <= e["wd"] <= 10,
              "wd_11_20": lambda e: 11 <= e["wd"] <= 20, "wd_over_20": lambda e: e["wd"] > 20}
    res: Dict[str, Any] = {"definition": "near_only, pooled U+V+T, primary horizon, net benchmark-relative; descriptive only, never used to select a setting"}
    for sname, thr in (("production_floors", PRODUCTION_FLOORS), ("no_threshold", NO_THRESHOLD)):
        res[sname] = {}
        for c in CATEGORIES:
            sig = config_signals("near_only", c, cats[thr])
            res[sname][c] = {}
            for g, f in groups.items():
                sub = [s for s in sig if buckets[s[1]][day_of[s[0]]][0] is not None and f(buckets[s[1]][day_of[s[0]]][0])]
                r = evaluate(sub, out, bounds, PRIMARY_H)["pooled"]
                res[sname][c][g] = r
            for h in (1, 3, 10, 20):
                for g in ("roll_window_1_to_3", "outside_roll_window"):
                    sub = [s for s in sig if buckets[s[1]][day_of[s[0]]][0] is not None and groups[g](buckets[s[1]][day_of[s[0]]][0])]
                    res[sname][c][f"{g}_h{h}"] = evaluate(sub, out, bounds, h)["pooled"]
    return res


def agreement_migration(buckets, cats, out: Outcomes, bounds, per_cat_thr) -> Dict[str, Any]:
    """Near signals grouped by cross-expiry agreement (buckets in the same category / 3) and by OI migration; pooled U+V+T, primary horizon."""
    day_of = out.sessions
    res: Dict[str, Any] = {"migration_groups": "OI change flat = within +-1%; groups may overlap", "agreement": {}, "migration": {}}
    for sname, thr in (("production_floors", PRODUCTION_FLOORS), ("no_threshold", NO_THRESHOLD)):
        res["agreement"][sname], res["migration"][sname] = {}, {}
        for c in CATEGORIES:
            near = [(i, sym, cs) for (sym, i), cs in cats[thr].items() if cs[0] == c]
            res["agreement"][sname][c] = {}
            for k in (1, 2, 3):
                sub = [(i, sym, BULL[c]) for i, sym, cs in near if sum(1 for x in cs if x == c) == k]
                res["agreement"][sname][c][f"{k}_of_3"] = evaluate(sub, out, bounds, PRIMARY_H)["pooled"]
            mig: Dict[str, List[Signal]] = {"rollover_like": [], "new_near_build": [], "broad_build": [], "other": []}
            for i, sym, cs in near:
                row = buckets[sym][day_of[i]]
                o = [e["o"] if e is not None else None for e in row]
                tag = "other"
                if o[0] is not None and o[1] is not None:
                    if o[0] <= -1 and o[1] >= 1:
                        tag = "rollover_like"
                    elif o[0] >= 1 and o[1] <= 1:
                        tag = "new_near_build"
                if o[0] is not None and o[1] is not None and o[2] is not None and min(o) >= 1:
                    mig["broad_build"].append((i, sym, BULL[c]))
                mig[tag].append((i, sym, BULL[c]))
            res["migration"][sname][c] = {k: evaluate(v, out, bounds, PRIMARY_H)["pooled"] for k, v in mig.items()}
    return res


def price_only(buckets, out: Outcomes, bounds, per_cat_thr, sessions) -> Dict[str, Any]:
    """Same price and volume floors on the near contract with NO OI requirement; the direction is that of the price move."""
    res: Dict[str, Any] = {}
    for c in CATEGORIES:
        res[c] = {}
        for label, (P, _O, R) in per_cat_thr[c].items():
            sig: List[Signal] = []
            for sym, days in buckets.items():
                for day, row in days.items():
                    e = row[0]
                    if e is None or e["p"] == 0 or abs(e["p"]) < P or (R is not None and (e["rvol"] is None or e["rvol"] < R)):
                        continue
                    if (1 if e["p"] > 0 else -1) == PRICE_UP[c]:
                        sig.append((_ix(sessions, day), sym, PRICE_UP[c]))
            res[c][label] = evaluate(sig, out, bounds, PRIMARY_H)["pooled"]
    return res


def _ix(sessions: Sequence[str], day: str) -> int:
    return bisect_left(sessions, day)
