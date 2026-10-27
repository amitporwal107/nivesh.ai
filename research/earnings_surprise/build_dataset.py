#!/usr/bin/env python3
"""Build the event dataset for the pre-registered Results-week study.

Design: docs/ai_research/EARNINGS_SURPRISE_PREREGISTRATION.md (registered in commit b3415111 before any score or return was
computed). This script implements §3–§5 of that file and nothing else. It reads the read-only exports written by export.sh /
export_eaa.py and writes events.csv, exclusions.csv and counts.json. It never writes to a database.

    python build_dataset.py <data_dir> <out_dir>

Run inside the staging backend container: it imports the DaaS router's own pure functions (desk_expectation: build_store,
run_backtest, Calibration, answer, build_metric) and the AI scanner's own feature and score functions, so the method under test
is the code itself, not a re-write. BACKEND (env) points at the repo's backend directory (default /app/backend).
"""
from __future__ import annotations

import bisect
import csv
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.environ.get("BACKEND", "/app/backend"))
from nidp.services.daas_api.routers import desk_expectation as de  # noqa: E402
from nidp.services.daas_api.routers.desk_market import buildup_label  # noqa: E402
from services.positional_engine import feature_calculator as fc  # noqa: E402
from services.positional_engine import scorer  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402

# S7 (amendment A1.2): the live results-week scoring, exactly as committed on feat/earnings-surprise-tracker. It is not
# vendored into this branch; fetch it with `git show 9f78c6ee:backend/services/results_week/scoring.py > live_scoring.py`.
LIVE_SCORING = os.environ.get("LIVE_SCORING", "/tmp/es/live_scoring.py")
_spec = importlib.util.spec_from_file_location("live_scoring", LIVE_SCORING)
LS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LS)
LIVE_SHA = hashlib.sha256(Path(LIVE_SCORING).read_bytes()).hexdigest()
# Amendment A2: TIMING=first_filing (T2, governs) uses the earlier of broadcast_at and the earliest NSE "Outcome of Board
# Meeting" filing on the broadcast's IST date or the meeting date; TIMING=broadcast (T1) is the §5 rule as registered.
TIMING = os.environ.get("TIMING", "broadcast")
assert TIMING in ("broadcast", "first_filing"), TIMING

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = date(2026, 10, 27)                       # the data freeze; answer() treats every studied meeting as declared
TARGETS = (date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30))
PRIMARY = (date(2026, 3, 31), date(2026, 6, 30))  # the live 7-quarter method is computable for these two only (§3)
HOLDOUT_TARGET = date(2026, 9, 30)
CAL_FREEZE = date(2026, 6, 30)                   # bands calibrated on tested quarters up to here (§4.1)
LAST_RETURN_SESSION = date(2026, 9, 30)          # holdout guard (§5)
MARKET_CLOSE = time(15, 30)
LIQ_RS, MIN_PRICE = 1e7, 10.0                    # ₹1 crore median traded value, ₹10 close, on S−1 (§5)
WINDOW, MIN_TECH_BARS = 260, 60                  # §4.7
W_COMPOSITE = {"surprise": 35, "trend": 25, "quality": 15}
W_COMPOSITE_OUTLOOK = {"surprise": 35, "trend": 25, "outlook": 25, "quality": 15}
W_UPCOMING = {"technical": 40, "oi": 30, "past": 15, "trend": 15}
W_DECLARED = {"earnings": 40, "reaction": 20, "oi": 20, "technical": 20}
OI_SCORE = {"long_buildup": 100.0, "short_covering": 100.0, "neutral": 50.0, "short_buildup": 0.0, "long_unwinding": 0.0}
XCOLS = ("revenue_from_ops_cr", "pat_cr", "ebitda_cr", "other_income_cr", "exceptional_items_cr", "pbt_cr", "tax_expense_cr")


def fnum(s: Optional[str]) -> Optional[float]:
    return None if s is None or s == "" else float(s)


def fdt(s: Optional[str]) -> Optional[datetime]:
    return None if not s else datetime.fromisoformat(s)


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def wmean(parts: Dict[str, Optional[float]], weights: Dict[str, float]) -> Optional[float]:
    present = {k: v for k, v in parts.items() if v is not None}
    if not present:
        return None
    return sum(weights[k] * v for k, v in present.items()) / sum(weights[k] for k in present)


# ── §4.2 surprise ────────────────────────────────────────────────────────────

def zscore(expected: Optional[Dict[str, float]], filed: Optional[float]) -> Tuple[Optional[float], Optional[str]]:
    if not expected or filed is None:
        return None, "no expected range or filed value"
    mid, lo, hi = expected["mid"], expected["low"], expected["high"]
    den = (hi - mid) if filed >= mid else (mid - lo)
    if den is None or den <= 0:
        return None, "zero-width band"
    return (filed - mid) / den, None


def surprise_from(z_pat: Optional[float], z_rev: Optional[float]) -> Optional[float]:
    s_pat = None if z_pat is None else clamp(50 + 25 * z_pat)
    s_rev = None if z_rev is None else clamp(50 + 25 * z_rev)
    if s_pat is not None and s_rev is not None:
        return 0.6 * s_pat + 0.4 * s_rev
    return s_pat if s_pat is not None else s_rev


def verdict_from_score(s: Optional[float]) -> Optional[str]:
    if s is None:
        return None
    return "above" if s > 75 else "below" if s < 25 else "in_line"


def verdict_from_z(z: Optional[float]) -> Optional[str]:
    if z is None:
        return None
    return "above" if z > 1 else "below" if z < -1 else "in_line"


def metric_z(entry: Dict[str, Any]) -> Tuple[Optional[float], Optional[str]]:
    if not entry.get("reliable"):
        return None, "not reliable"
    filed = (entry.get("filed") or {}).get("value")
    return zscore(entry.get("expected"), filed)


# ── loading ──────────────────────────────────────────────────────────────────

def load_quarters(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            row: Dict[str, Any] = {"symbol": r["symbol"], "period_end": date.fromisoformat(r["period_end"]),
                                   "consolidated": r["consolidated"] == "t", "eps_basic": fnum(r["eps_basic"]),
                                   "broadcast_at": fdt(r["broadcast_at"]), "source": r["source"], "ingested_at": fdt(r["ingested_at"])}
            for c in XCOLS:
                row[c] = fnum(r[c])
            rows.append(row)
    return rows


def merged_extra(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, bool, date], Dict[str, Optional[float]]]:
    """Field-by-field merge across sources, most recently ingested non-null first (the same rule as de.build_store)."""
    out: Dict[Tuple[str, bool, date], Dict[str, Optional[float]]] = {}
    lo = datetime.min.replace(tzinfo=timezone.utc)
    for r in sorted(rows, key=lambda r: r["ingested_at"] or lo, reverse=True):
        cell = out.setdefault((r["symbol"], r["consolidated"], r["period_end"]), {c: None for c in XCOLS})
        for c in XCOLS:
            if cell[c] is None and r[c] is not None:
                cell[c] = r[c]
    return out


# ── §4.3 / §4.4 ──────────────────────────────────────────────────────────────

def trend_score(x: Dict, sym: str, cons: bool, q: date) -> Optional[float]:
    cur = x.get((sym, cons, q))
    if cur is None:
        return None
    p1 = x.get((sym, cons, de.shift_quarters(q, -1)), {})
    y1 = x.get((sym, cons, de.shift_quarters(q, -4)), {})
    items: List[float] = []
    for col in ("revenue_from_ops_cr", "ebitda_cr", "pat_cr"):
        for base in (y1, p1):
            a, b = cur.get(col), base.get(col)
            if a is not None and b is not None and a > 0 and b > 0:
                items.append(clamp(50 + 100 * (a / b - 1)))
    r0, r1 = cur.get("revenue_from_ops_cr"), y1.get("revenue_from_ops_cr")
    e0, e1 = cur.get("ebitda_cr"), y1.get("ebitda_cr")
    if r0 and r1 and r0 > 0 and r1 > 0 and e0 is not None and e1 is not None:
        items.append(clamp(50 + 10 * ((e0 / r0 - e1 / r1) * 100)))
    return statistics.fmean(items) if len(items) >= 2 else None


def quality_score(x: Dict, sym: str, cons: bool, q: date) -> Tuple[Optional[float], List[str]]:
    cur = x.get((sym, cons, q))
    if cur is None:
        return None, []
    y1 = x.get((sym, cons, de.shift_quarters(q, -4)), {})
    pbt, fired, checked = cur.get("pbt_cr"), [], 0
    if pbt is not None and pbt > 0:
        if cur.get("exceptional_items_cr") is not None:
            checked += 1
            if abs(cur["exceptional_items_cr"]) > 0.20 * pbt:
                fired.append("exceptional")
        if cur.get("other_income_cr") is not None:
            checked += 1
            if cur["other_income_cr"] > 0.30 * pbt:
                fired.append("other_income")
        if cur.get("tax_expense_cr") is not None:
            checked += 1
            rate = cur["tax_expense_cr"] / pbt
            if rate < 0.10 or rate > 0.40:
                fired.append("tax_rate")
    p0, p1_, r0, r1 = cur.get("pat_cr"), y1.get("pat_cr"), cur.get("revenue_from_ops_cr"), y1.get("revenue_from_ops_cr")
    o0, o1 = cur.get("other_income_cr"), y1.get("other_income_cr")
    if all(v is not None for v in (p0, p1_, r0, r1, o0, o1)) and p1_ > 0 and r1 > 0 and r0 > 0 and p0 > 0:
        checked += 1
        pg, rg = p0 / p1_ - 1, r0 / r1 - 1
        if pg > 0 and pg > 2 * rg and o0 > o1:
            fired.append("pat_vs_revenue")
    if checked == 0:
        return None, []
    return 100.0 - 25.0 * len(fired), fired


# ── "last year unchanged" baseline (S1) ──────────────────────────────────────

def srw_records(store: Dict, metric: str) -> List[Dict[str, Any]]:
    out = []
    for sym, by_basis in store.items():
        for cons, by_pe in by_basis.items():
            for target, cell in by_pe.items():
                actual = cell.get(metric)
                if actual is None or actual <= 0:
                    continue
                f, _ = srw_forecast(by_pe, metric, target, cell["known_at"])
                if f is None:
                    continue
                out.append({"symbol": sym, "consolidated": cons, "target": target, "instability": 0.0,
                            "size": f["size"], "error_pct": (actual / f["mid"] - 1.0) * 100.0})
    best: Dict[Tuple[str, date], Dict[str, Any]] = {}
    for r in out:
        k = (r["symbol"], r["target"])
        if k not in best or (r["consolidated"] and not best[k]["consolidated"]):
            best[k] = r
    return list(best.values())


def srw_forecast(by_pe: Dict, metric: str, target: date, cutoff: datetime) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    y1pe = de.shift_quarters(target, -4)
    y1 = de._value(by_pe, y1pe, metric, cutoff)
    if y1 is None:
        return None, "last year's quarter not published"
    if y1 <= 0:
        return None, "last year's quarter zero or negative"
    rev_y1 = de._value(by_pe, y1pe, "revenue", cutoff)
    if metric == "pat" and rev_y1 and rev_y1 > 0 and y1 / rev_y1 < de.MIN_PAT_MARGIN:
        return None, "last year's profit under 0.5 % of revenue"
    return {"mid": y1, "size": rev_y1 if rev_y1 and rev_y1 > 0 else None}, None


# ── main ─────────────────────────────────────────────────────────────────────

def main(data: Path, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    counts: Dict[str, Any] = {}

    # quarters, models (frozen calibration)
    qrows = load_quarters(data / "quarters.csv")
    x = merged_extra(qrows)
    store = de.build_store(qrows)
    recs_all = {m: de.run_backtest(store, m) for m in ("revenue", "pat")}
    recs = {m: [r for r in recs_all[m] if r["target"] <= CAL_FREEZE] for m in recs_all}
    cal = {m: de.Calibration(recs[m], m) for m in recs}
    models = {"store": store, "records": recs, "cal": cal, "universe": {"revenue": {"n": 0}, "pat": {"n": 0}}}
    counts["backtest_records"] = {m: dict(sorted(Counter(r["target"].isoformat() for r in recs_all[m]).items())) for m in recs_all}
    counts["calibration_n"] = {m: cal[m].n for m in cal}
    counts["live_scoring_sha256"] = LIVE_SHA
    counts["timing"] = TIMING
    srw = {m: [r for r in srw_records(store, m) if r["target"] <= CAL_FREEZE] for m in ("revenue", "pat")}
    cal_srw = {m: de.Calibration(srw[m], m) for m in srw}
    counts["srw_calibration_n"] = {m: cal_srw[m].n for m in cal_srw}
    # strict point-in-time calibration (S3): every record known before the filing, prefix-cached by known_at
    known_recs = {m: sorted(((store[r["symbol"]][r["consolidated"]][r["target"]]["known_at"], r) for r in recs[m]),
                            key=lambda t: t[0]) for m in recs}
    strict_cache: Dict[Tuple[str, int], Any] = {}

    def strict_cal(metric: str, cutoff: datetime):
        keys = [t[0] for t in known_recs[metric]]
        n = bisect.bisect_left(keys, cutoff)
        if (metric, n) not in strict_cache:
            strict_cache[(metric, n)] = de.Calibration([t[1] for t in known_recs[metric][:n]], metric) if n else None
        return strict_cache[(metric, n)]

    # calendar
    cal_by_sym: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    with open(data / "calendar.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            cal_by_sym[r["symbol"]].append({"event_date": date.fromisoformat(r["event_date"]), "purpose": r["purpose"],
                                            "intimated_at": fdt(r["intimated_at"]), "company_name": r["company_name"]})
    past_dates: Dict[str, List[date]] = {}
    for sym, evs in cal_by_sym.items():
        first_in_q: Dict[Tuple[int, int], date] = {}
        for e in evs:
            k = (e["event_date"].year, (e["event_date"].month - 1) // 3)
            if k not in first_in_q or e["event_date"] < first_in_q[k]:
                first_in_q[k] = e["event_date"]
        past_dates[sym] = sorted(first_in_q.values())

    # sessions, benchmark, bars
    nifty = pd.read_csv(data / "nifty50.csv", parse_dates=["as_of_date"])
    sessions = [d.date() for d in nifty["as_of_date"]]
    nclose = nifty["close_price"].to_numpy(float)
    sidx = {d: i for i, d in enumerate(sessions)}
    bees = pd.read_csv(data / "niftybees.csv", parse_dates=["as_of_date"])
    bees_map = {d.date(): c for d, c in zip(bees["as_of_date"], bees["close_price"])}
    missing_bees = [d for d in sessions if d not in bees_map]
    if missing_bees:
        print(f"REFUSED: NIFTYBEES missing on {len(missing_bees)} sessions")
        return 3
    bees_close = np.array([bees_map[d] for d in sessions], float)
    bars = pd.read_csv(data / "bars.csv", parse_dates=["as_of_date"])
    B: Dict[str, Dict[str, Any]] = {}
    for sym, g in bars.groupby("symbol", sort=False):
        g = g.sort_values("as_of_date")
        dts = [d.date() for d in g["as_of_date"]]
        B[sym] = {"pos": {d: k for k, d in enumerate(dts)}, "o": g["adj_open"].to_numpy(float), "h": g["adj_high"].to_numpy(float),
                  "l": g["adj_low"].to_numpy(float), "c": g["adj_close"].to_numpy(float), "v": g["adj_volume"].to_numpy(float),
                  "rc": g["raw_close"].to_numpy(float), "rv": g["raw_volume"].to_numpy(float), "dp": g["deliv_pct"].to_numpy(float)}
    del bars
    fno: Dict[Tuple[date, str], Tuple[Optional[float], ...]] = {}
    with open(data / "fno.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            fno[(date.fromisoformat(r["as_of_date"]), r["symbol"])] = (fnum(r["close"]), fnum(r["prev_close"]), fnum(r["oi"]),
                                                                       fnum(r["oi_chg"]), fnum(r.get("fut_value")))
    first_outcome: Dict[Tuple[str, date], datetime] = {}
    if TIMING == "first_filing":
        with open(data / "outcome.csv", newline="") as fh:
            for r in csv.DictReader(fh):
                t = datetime.fromisoformat(r["filed_at"]).astimezone(IST)
                k = (r["symbol"], t.date())
                if k not in first_outcome or t < first_outcome[k]:
                    first_outcome[k] = t
    eaa: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
    with open(data / "eaa.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["net_impact_score"] not in ("", "None"):
                eaa[r["symbol"]].append((datetime.fromisoformat(r["event_ts"]).replace(tzinfo=IST), float(r["net_impact_score"])))

    def close_at(sym: str, i: int) -> Optional[float]:
        b = B.get(sym)
        if b is None or i < 0 or i >= len(sessions):
            return None
        k = b["pos"].get(sessions[i])
        return None if k is None else float(b["c"][k])

    def ret(sym: str, i0: int, i1: int) -> Tuple[Optional[float], Optional[float]]:
        a, b = close_at(sym, i0), close_at(sym, i1)
        if a is None or b is None or a <= 0 or i1 >= len(sessions):
            return None, None
        r = b / a - 1.0
        return r, r - (nclose[i1] / nclose[i0] - 1.0)

    def liquid(sym: str, i: int) -> Optional[bool]:
        b = B.get(sym)
        k = None if b is None else b["pos"].get(sessions[i])
        if k is None:
            return None
        tv = b["rc"][max(0, k - 19):k + 1] * b["rv"][max(0, k - 19):k + 1]
        return bool(np.nanmedian(tv) >= LIQ_RS and b["rc"][k] >= MIN_PRICE)

    def technical(sym: str, i: int) -> Optional[float]:
        b = B.get(sym)
        k = None if b is None else b["pos"].get(sessions[i])
        if k is None or k + 1 < MIN_TECH_BARS:
            return None
        lo = max(0, k + 1 - WINDOW)
        win = [{"open": b["o"][j], "high": b["h"][j], "low": b["l"][j], "close": b["c"][j], "volume": b["v"][j],
                "delivery_pct": None if np.isnan(b["dp"][j]) else float(b["dp"][j])} for j in range(lo, k + 1)]
        f = fc.compute_features(win)
        ret20 = f.get("return_20d_pct")
        b20 = (bees_close[i] / bees_close[i - 20] - 1) * 100 if i >= 20 else None
        rs20 = None if ret20 is None or b20 is None else ret20 - b20
        sub = {"trend": scorer.score_trend(f), "momentum": scorer.score_momentum(f), "structure": scorer.score_structure(f),
               "accumulation": scorer.score_accumulation(f), "sector": scorer.score_sector(rs20), "risk": scorer.score_risk(f)}
        return 100.0 * sum(sub[s] * scorer.DEFAULT_WEIGHTS[s] for s in sub)

    def oi_reading(sym: str, i: int) -> Tuple[bool, Optional[str], Optional[float]]:
        r = fno.get((sessions[i], sym))
        if r is None:
            return False, None, None
        close, prev, _oi, oi_chg, _tv = r
        pc = (close / prev - 1) * 100 if close is not None and prev else None
        lab = buildup_label(pc, oi_chg)
        return True, lab, (OI_SCORE.get(lab) if lab else None)

    # ── S7: the live code's parts (amendment A1.2), fed the same point-in-time inputs ──
    def live_oi(sym: str, i: int) -> Tuple[Optional[str], Optional[float]]:
        r = fno.get((sessions[i], sym))
        if r is None:
            return None, None
        close, prev, oi, oi_chg, tv = r
        prev_oi = (oi - oi_chg) if oi is not None and oi_chg is not None else None
        row = {"price_chg_pct": (close / prev - 1) * 100 if close is not None and prev else None,
               "oi_chg_pct": oi_chg / prev_oi * 100 if prev_oi else None,
               "fut_turnover_cr": tv / 1e7 if tv is not None else None}
        row["label"] = buildup_label(row["price_chg_pct"], oi_chg)
        blk, _gap = LS.fno_block(True, row, sessions[i].isoformat())
        return (blk["state"], blk["score"]) if blk else (None, None)

    def live_reaction(sym: str, bt: datetime, S: int) -> Optional[float]:
        b = B[sym]
        bars_ = {sessions[i]: (float(b["c"][b["pos"][sessions[i]]]), float(b["v"][b["pos"][sessions[i]]]))
                 for i in range(max(0, S - 30), S + 1) if sessions[i] in b["pos"]}
        nif = {sessions[i]: float(nclose[i]) for i in range(max(0, S - 30), S + 1)}
        blk, _gap = LS.reaction(bt, sessions[:S + 1], bars_, nif)
        return blk["score"] if blk else None

    def live_past(sym: str, i_sig: int) -> Optional[float]:
        occ = []
        for d in sorted({e["event_date"] for e in cal_by_sym.get(sym, [])}, reverse=True):
            t = bisect.bisect_left(sessions, d)
            if t - 1 < 0 or t + 1 > i_sig:           # point-in-time: the event day and the next day closed by the signal
                continue
            c0, c1, c2 = close_at(sym, t - 1), close_at(sym, t), close_at(sym, t + 1)
            if c0 and c1 and c2:
                occ.append({"event_day_pct": (c1 / c0 - 1) * 100, "d1_pct": (c2 / c1 - 1) * 100})
            if len(occ) >= 40:                       # desk_events.HISTORY_LIMIT
                break
        blk = LS.past_reactions({"occurrences": occ})
        return blk["score"] if blk else None

    def live_rows(sym: str, cons: bool, cutoff: Optional[datetime]) -> List[Dict[str, Any]]:
        out_ = []
        for pe, c in store[sym][cons].items():
            if cutoff is not None and not c["known_at"] < cutoff:
                continue
            v = x.get((sym, cons, pe), {})
            out_.append({"period_end": pe.isoformat(), **v})
        return out_

    def past_reactions(sym: str, i_sig: int) -> Tuple[Optional[float], int]:
        vals = []
        for d in past_dates.get(sym, []):
            t = bisect.bisect_left(sessions, d)
            if t - 1 < 0 or t + 5 > i_sig:
                continue
            a, b = close_at(sym, t - 1), close_at(sym, t + 5)
            if a and b and a > 0:
                vals.append((d, (b / a - 1) * 100))
        vals = sorted(vals)[-4:]
        if len(vals) < 2:
            return None, len(vals)
        return clamp(50 + 2.5 * statistics.fmean(v for _, v in vals)), len(vals)

    # events
    events: List[Dict[str, Any]] = []
    excl: List[Tuple[str, str, str]] = []
    for target in TARGETS:
        if target == HOLDOUT_TARGET:
            raise SystemExit("REFUSED: the holdout quarter is not computed in the primary run")
        syms = sorted(s for s, by in store.items() if any(target in by_pe for by_pe in by.values()))
        for sym in syms:
            t_iso = target.isoformat()
            cands = [e for e in cal_by_sym.get(sym, []) if target < e["event_date"] <= target + timedelta(days=200)
                     and de.parse_period_end(e["purpose"], e["event_date"])[0] == target]
            if not cands:
                excl.append((t_iso, sym, "no results meeting for this quarter in event_calendar"))
                continue
            # the filed quarter (and so its broadcast time) does not depend on which meeting row is passed: find it once
            a0 = de.answer(models, sym, cands[0]["event_date"], cands[0]["purpose"], TODAY, [], cands[0]["intimated_at"], None)
            fb = next((m["filed"]["broadcast_at"] for m in a0["metrics"] if m.get("filed")), None)
            if fb is None:
                excl.append((t_iso, sym, "filed quarter has no broadcast_at"))
                continue
            bt = datetime.fromisoformat(fb).astimezone(IST)
            near = sorted((abs((e["event_date"] - bt.date()).days), e["event_date"], k) for k, e in enumerate(cands))
            if near[0][0] > 1:
                excl.append((t_iso, sym, "meeting not within ±1 day of broadcast_at"))
                continue
            ev = cands[near[0][2]]
            a = a0 if near[0][2] == 0 else de.answer(models, sym, ev["event_date"], ev["purpose"], TODAY, [], ev["intimated_at"], None)
            if a["period_end"] != t_iso:
                excl.append((t_iso, sym, "answer() period differs from target"))
                continue
            cons = a["basis"] == "consolidated"
            # first reaction session S, from the filing time of the chosen timing (§5 / A2)
            ft = bt
            if TIMING == "first_filing":
                ft = min([bt] + [first_outcome[k] for k in ((sym, bt.date()), (sym, ev["event_date"])) if k in first_outcome])
            j = bisect.bisect_left(sessions, ft.date())
            S = j if (j < len(sessions) and sessions[j] == ft.date() and ft.time() < MARKET_CLOSE) else bisect.bisect_right(sessions, ft.date())
            if S - 1 < 0 or S + 5 >= len(sessions):
                excl.append((t_iso, sym, "return window outside the price calendar"))
                continue
            if sessions[S + 5] > LAST_RETURN_SESSION:
                excl.append((t_iso, sym, "return window reaches the holdout period (after 2026-09-30)"))
                continue
            if sym not in B or B[sym]["pos"].get(sessions[S - 1]) is None:
                excl.append((t_iso, sym, "no price bar on S-1"))
                continue
            r1, r1x = ret(sym, S - 1, S)
            r5, r5x = ret(sym, S - 1, S + 4)
            _d5, d5x = ret(sym, S, S + 5)
            liq = liquid(sym, S - 1)

            # full live method (primary seasons only; earlier seasons have no reliable baseline by construction)
            mets = {m["key"]: m for m in a["metrics"]}
            zp, zp_why = metric_z(mets["pat"])
            zr, zr_why = metric_z(mets["revenue"])
            surprise = surprise_from(zp, zr)
            trend_d = trend_score(x, sym, cons, target)
            quality, flags = quality_score(x, sym, cons, target)
            composite = None if (surprise is None and trend_d is None) else wmean(
                {"surprise": surprise, "trend": trend_d, "quality": quality}, W_COMPOSITE)

            # S1 "last year unchanged"
            by_pe = store[sym][cons]
            fcell = by_pe[target]
            cutoff = fcell["known_at"]
            srw_z = {}
            for m in ("pat", "revenue"):
                f, _why = srw_forecast(by_pe, m, target, cutoff)
                filed = fcell.get(m)
                band = cal_srw[m].band(f["mid"], 0.0, f["size"]) if f else None
                srw_z[m] = zscore(band, filed)[0] if band and filed is not None else None
            srw_surprise = surprise_from(srw_z["pat"], srw_z["revenue"])
            srw_composite = None if (srw_surprise is None and trend_d is None) else wmean(
                {"surprise": srw_surprise, "trend": trend_d, "quality": quality}, W_COMPOSITE)

            # S3 strict point-in-time band (Jul–Aug 2026 only)
            s3_surprise = None
            if target == date(2026, 6, 30):
                zz = {}
                for m in ("pat", "revenue"):
                    c = strict_cal(m, cutoff)
                    e_ = de.build_metric(m, by_pe, target, cutoff, c, fcell, None) if c else {"reliable": False}
                    zz[m] = metric_z(e_)[0]
                s3_surprise = surprise_from(zz["pat"], zz["revenue"])

            # H3 upcoming order at S−1 (F&O names)
            fno_m1, oi_lab_m1, oi_m1 = oi_reading(sym, S - 1)
            tech_m1 = technical(sym, S - 1) if fno_m1 else None
            past, n_past = past_reactions(sym, S - 1) if fno_m1 else (None, 0)
            trend_up, q_up = None, None
            if fno_m1:
                sig_cut = datetime.combine(sessions[S - 1], MARKET_CLOSE, tzinfo=IST)
                known = [pe for pe, c in by_pe.items() if pe < target and c["known_at"] < sig_cut]
                if known:
                    q_up = max(known)
                    trend_up = trend_score(x, sym, cons, q_up)
            upcoming = (wmean({"technical": tech_m1, "oi": oi_m1, "past": past, "trend": trend_up}, W_UPCOMING)
                        if tech_m1 is not None else None)

            # H4 declared order at S (F&O names)
            fno_s, oi_lab_s, oi_s = oi_reading(sym, S)
            tech_s = technical(sym, S) if fno_s else None
            reaction = clamp(50 + 5 * r1x * 100) if r1x is not None else None
            declared = (wmean({"earnings": composite, "reaction": reaction, "oi": oi_s, "technical": tech_s}, W_DECLARED)
                        if fno_s else None)

            # E2 outlook (not point-in-time)
            outlook = None
            docs = [(abs((ts - bt).total_seconds()), ts, sc) for ts, sc in eaa.get(sym, []) if abs((ts - bt).total_seconds()) <= 86400]
            if docs:
                outlook = (min(docs)[2] + 100) / 2
            comp_outlook = None if (surprise is None and trend_d is None) else wmean(
                {"surprise": surprise, "trend": trend_d, "outlook": outlook, "quality": quality}, W_COMPOSITE_OUTLOOK)

            # S7 live code (outlook left out: not point-in-time)
            lsur = LS.surprise(a["metrics"])
            l_rows = live_rows(sym, cons, None)
            l_trend = LS.trend(l_rows, target)["value"]
            l_quality = LS.quality(l_rows, target)["value"]
            l_comp = LS.composite({"surprise": lsur["value"], "trend": l_trend, "quality": l_quality, "outlook": None})["value"]
            l_verdict = (lsur.get("verdict") or {}).get("label")
            l_up = None
            if fno_m1:
                sig_cut = datetime.combine(sessions[S - 1], MARKET_CLOSE, tzinfo=IST)
                rows_up = live_rows(sym, cons, sig_cut)
                q_l, _ = LS.pick_quarter(rows_up, target, declared=False)
                parts = {"technical": tech_m1, "oi": live_oi(sym, S - 1)[1], "past_reactions": live_past(sym, S - 1),
                         "trend": LS.trend(rows_up, q_l)["value"] if q_l else None}
                present = {k: v for k, v in parts.items() if v is not None}
                got = sum(LS.UPCOMING_WEIGHTS[k] for k in present)
                if got >= LS.MIN_PRESENT_WEIGHT_SHARE * sum(LS.UPCOMING_WEIGHTS.values()):
                    l_up = sum(LS.UPCOMING_WEIGHTS[k] * v for k, v in present.items()) / got
            l_decl = None
            if fno_s and l_comp is not None:                 # live: a declared name needs its earnings score
                parts = {"earnings": l_comp, "reaction": live_reaction(sym, ft, S), "oi": live_oi(sym, S)[1], "technical": tech_s}
                present = {k: v for k, v in parts.items() if v is not None}
                got = sum(LS.DECLARED_WEIGHTS[k] for k in present)
                if got >= LS.MIN_PRESENT_WEIGHT_SHARE * sum(LS.DECLARED_WEIGHTS.values()):
                    l_decl = sum(LS.DECLARED_WEIGHTS[k] * v for k, v in present.items()) / got

            # H5 results strength (amendment A1.1)
            cq, yq = x.get((sym, cons, target), {}), x.get((sym, cons, de.shift_quarters(target, -4)), {})
            p0, p4 = cq.get("pat_cr"), yq.get("pat_cr")
            r0, r4 = cq.get("revenue_from_ops_cr"), yq.get("revenue_from_ops_cr")
            e0, e4 = cq.get("ebitda_cr"), yq.get("ebitda_cr")
            pat_up = pat_dn = None
            if p0 is not None and p4 is not None:
                if p4 > 0:
                    g = p0 / p4 - 1
                    pat_up, pat_dn = g >= 0.20, g <= -0.10      # profit → loss gives g ≤ −100 %
                else:
                    pat_up, pat_dn = p0 > 0, False              # loss → profit counts as ≥ +20 %
            rev_g = (r0 / r4 - 1) if (r0 is not None and r4 is not None and r4 > 0) else None
            marg = ((e0 / r0 - e4 / r4) * 1e4) if (r0 and r4 and r0 > 0 and r4 > 0 and e0 is not None and e4 is not None) else None
            pbt = cq.get("pbt_cr")
            red_fin = bool(pbt is not None and pbt > 0 and (
                (cq.get("exceptional_items_cr") is not None and abs(cq["exceptional_items_cr"]) > 0.20 * pbt) or
                (cq.get("other_income_cr") is not None and cq["other_income_cr"] > 0.30 * pbt)))
            growth_hits = sum([bool(pat_up), rev_g is not None and rev_g >= 0.10, marg is not None and marg >= 50])
            weak_growth = bool(pat_dn) and rev_g is not None and rev_g < 0.05
            full_season = target in PRIMARY
            vh = l_verdict if full_season else None
            h5 = {}
            for variant, v_ in (("growth", None), ("full", vh)):
                strong = (growth_hits + (v_ == "above")) >= 2 and not red_fin and v_ != "below"
                weak = weak_growth or v_ == "below"
                h5[variant] = "conflict" if (strong and weak) else "strong" if strong else "weak" if weak else "unflagged"
            h5_live = h5["full"] if full_season else h5["growth"]

            events.append({
                "season": t_iso, "symbol": sym, "basis": a["basis"], "event_date": ev["event_date"].isoformat(),
                "broadcast_ist": bt.isoformat(), "filed_ist": ft.isoformat(), "timing": TIMING, "next_session": sessions[S] != ft.date(), "S": sessions[S].isoformat(),
                "liquid": liq, "R1": r1, "R1x": r1x, "R5": r5, "R5x": r5x, "D5x": d5x,
                "pat_reliable": bool(mets["pat"].get("reliable")), "rev_reliable": bool(mets["revenue"].get("reliable")),
                "z_pat": zp, "z_rev": zr, "z_pat_why": zp_why, "z_rev_why": zr_why,
                "pat_vs_mid_pct": mets["pat"].get("vs_mid_pct") if mets["pat"].get("reliable") else None,
                "surprise": surprise, "verdict": verdict_from_score(surprise), "pat_verdict": verdict_from_z(zp),
                "trend": trend_d, "quality": quality, "flags": "|".join(flags), "composite": composite,
                "srw_surprise": srw_surprise, "srw_verdict": verdict_from_score(srw_surprise), "srw_composite": srw_composite,
                "s3_surprise": s3_surprise, "s3_verdict": verdict_from_score(s3_surprise),
                "fno_m1": fno_m1, "tech_m1": tech_m1, "oi_label_m1": oi_lab_m1, "oi_m1": oi_m1, "past": past, "n_past": n_past,
                "q_up": q_up.isoformat() if q_up else None, "trend_up": trend_up, "upcoming": upcoming,
                "fno_s": fno_s, "tech_s": tech_s, "oi_label_s": oi_lab_s, "oi_s": oi_s, "reaction": reaction, "declared": declared,
                "outlook": outlook, "composite_outlook": comp_outlook,
                "l_surprise": lsur["value"], "l_z": lsur.get("z"), "l_verdict": l_verdict, "l_trend": l_trend,
                "l_quality": l_quality, "l_composite": l_comp, "l_upcoming": l_up, "l_declared": l_decl,
                "h5_variant": "full" if full_season else "growth_only", "h5": h5_live, "h5_growth": h5["growth"],
                "h5_full": h5["full"] if full_season else None,
            })

    pd.DataFrame(events).to_csv(out / "events.csv", index=False)
    with open(out / "exclusions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(("season", "symbol", "reason"))
        w.writerows(excl)
    ev = pd.DataFrame(events)
    counts["events_by_season"] = ev.groupby("season").size().to_dict()
    counts["exclusions"] = {s: dict(Counter(r for ss, _, r in excl if ss == s)) for s in sorted({e[0] for e in excl})}
    counts["per_season"] = {}
    for s, g in ev.groupby("season"):
        counts["per_season"][s] = {
            "events": int(len(g)), "liquid": int(g["liquid"].fillna(False).sum()), "R5x": int(g["R5x"].notna().sum()),
            "verdict": {k: int(v) for k, v in g.loc[g["liquid"].fillna(False).astype(bool), "verdict"].value_counts().items()},
            "composite": int(g.loc[g["liquid"].fillna(False).astype(bool), "composite"].notna().sum()),
            "fno_m1": int(g["fno_m1"].sum()), "upcoming": int(g["upcoming"].notna().sum()),
            "fno_s": int(g["fno_s"].sum()), "declared": int(g["declared"].notna().sum()),
            "z_pat_why": {k: int(v) for k, v in g["z_pat_why"].value_counts().items()},
            "outlook": int(g["outlook"].notna().sum()),
            "l_verdict": {k: int(v) for k, v in g.loc[g["liquid"].fillna(False).astype(bool), "l_verdict"].value_counts().items()},
            "l_composite": int(g.loc[g["liquid"].fillna(False).astype(bool), "l_composite"].notna().sum()),
            "l_upcoming": int(g["l_upcoming"].notna().sum()), "l_declared": int(g["l_declared"].notna().sum()),
            "h5": {k: int(v) for k, v in g.loc[g["liquid"].fillna(False).astype(bool), "h5"].value_counts().items()}}
    (out / "counts.json").write_text(json.dumps(counts, indent=1, default=str))
    print(json.dumps(counts, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
