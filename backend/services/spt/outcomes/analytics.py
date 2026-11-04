"""Scanner analytics from `spt_signal_outcomes` (PRD §13.1, §13.6, §13.7; Workflow §17.3 step 7). Read-only.

Per scanner, per category and per scanner-score band (unscored marks are their own band): the number of signals and, per
horizon (T+1, T+5, T+10, T+20, only signals whose horizon is measured):
    n, hit_rate_pct (share with a positive return in the signal's own direction) with its 95 % Wilson interval,
    avg_return_pct, median_return_pct, avg_mfe_pct, avg_mae_pct
and for strong signals the hypothetical scan-plan-v3 trades decided so far: target 1 / stop / trend-exit / time-exit rates
and the average R multiple; and the fade rate.

Every figure carries its sample size. A group with fewer than MIN_SAMPLE measured signals is marked small_sample with
SMALL_SAMPLE_NOTE (PRD §13.7: no conclusion from a handful of results). These are signal statistics, not trade results:
no paper trade is read (Workflow §25 item 20), and a hit rate here is a count of what happened, not a probability.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import tracker

MIN_SAMPLE = 30
MAX_DAYS = 92
BANDS: Tuple[Tuple[int, str], ...] = ((90, "90+"), (80, "80-89"), (70, "70-79"), (60, "60-69"), (50, "50-59"), (0, "<50"))
SMALL_SAMPLE_NOTE = f"Fewer than {MIN_SAMPLE} measured signals: too few to draw a conclusion."
NOTE = ("Signal outcomes measured on NSE end-of-day closes from the price at detection, in the signal's own direction. "
        "Counts of what happened, not probabilities; they say nothing about any paper trade.")
PLAN_EVENTS = ("stop", "target_1", "target_2", "trend_exit", "time_exit")


def band(score: Any) -> str:
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return "unscored"
    for lo, name in BANDS:
        if score >= lo:
            return name
    return "<50"


def wilson(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """95 % Wilson score interval of k successes in n, in percent; None for n = 0."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, mid - half) * 100, 1), round(min(1.0, mid + half) * 100, 1)]


def _avg(xs: List[float]) -> Optional[float]:
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(docs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    docs = list(docs)
    out: Dict[str, Any] = {"signals": len(docs), "horizons": {}}
    measured_max = 0
    for k in tracker.HORIZONS:
        key = f"t{k}"
        done = [d["forward"][key] for d in docs if ((d.get("forward") or {}).get(key) or {}).get("status") == "done"]
        rets = [x["return_pct"] for x in done if x.get("return_pct") is not None]
        wins = sum(1 for r in rets if r > 0)
        n = len(rets)
        measured_max = max(measured_max, n)
        out["horizons"][key] = {
            "n": n, "hit_rate_pct": round(wins / n * 100, 1) if n else None, "hit_rate_ci95_pct": wilson(wins, n),
            "avg_return_pct": _avg(rets), "median_return_pct": round(statistics.median(rets), 2) if rets else None,
            "avg_mfe_pct": _avg([x["mfe_pct"] for x in done if x.get("mfe_pct") is not None]),
            "avg_mae_pct": _avg([x["mae_pct"] for x in done if x.get("mae_pct") is not None]),
            "small_sample": n < MIN_SAMPLE}
    plans = [d["plan"] for d in docs if isinstance(d.get("plan"), dict) and d["plan"].get("first_event") in PLAN_EVENTS]
    if any(isinstance(d.get("plan"), dict) for d in docs):
        n = len(plans)
        rs = [p["r_multiple"] for p in plans if p.get("r_multiple") is not None]
        out["plan"] = {"rules": "scan-plan-v3", "decided": n,
                       **{f"{e}_rate_pct": (round(sum(1 for p in plans if p["first_event"] == e) / n * 100, 1) if n else None)
                          for e in PLAN_EVENTS},
                       "avg_r_multiple": _avg(rs), "small_sample": n < MIN_SAMPLE}
    fades = [d["fade"]["faded"] for d in docs if isinstance(d.get("fade"), dict) and d["fade"].get("faded") is not None]
    if fades:
        out["fade"] = {"n": len(fades), "faded_rate_pct": round(sum(1 for f in fades if f) / len(fades) * 100, 1),
                       "small_sample": len(fades) < MIN_SAMPLE}
    out["small_sample"] = measured_max < MIN_SAMPLE
    if out["small_sample"]:
        out["note"] = SMALL_SAMPLE_NOTE
    return out


def _group(docs: List[Dict[str, Any]], key) -> List[Dict[str, Any]]:
    by: Dict[str, List[Dict[str, Any]]] = {}
    for d in docs:
        by.setdefault(str(key(d)), []).append(d)
    rows = [{"key": k, **summarize(v)} for k, v in by.items()]
    rows.sort(key=lambda r: (-r["signals"], r["key"]))
    return rows


async def scanners(db, *, day_from: str, day_to: str, kind: Optional[str] = None) -> Dict[str, Any]:
    q: Dict[str, Any] = {"day": {"$gte": day_from, "$lte": day_to}}
    if kind:
        q["kind"] = kind
    docs = await db[tracker.COLL].find(q).to_list(length=None)
    return {"ok": True, "from": day_from, "to": day_to, "kind": kind, "version": tracker.VERSION,
            "min_sample": MIN_SAMPLE, "note": NOTE, "totals": summarize(docs),
            "by_scanner": _group(docs, lambda d: d.get("scanner_id")),
            "by_category": _group(docs, lambda d: d.get("category")),
            "by_score_band": _group(docs, lambda d: band(d.get("scanner_score")))}
