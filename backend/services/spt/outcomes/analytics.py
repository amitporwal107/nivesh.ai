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


PROJECTION = {"forward": 1, "plan.first_event": 1, "plan.r_multiple": 1, "fade.faded": 1, "scanner_id": 1, "category": 1,
              "scanner_score": 1, "kind": 1}


class Acc:
    """One group's running figures (the documents are streamed, never held)."""

    def __init__(self) -> None:
        self.signals = 0
        self.rets: Dict[str, List[float]] = {f"t{k}": [] for k in tracker.HORIZONS}
        self.mfe: Dict[str, List[float]] = {f"t{k}": [] for k in tracker.HORIZONS}
        self.mae: Dict[str, List[float]] = {f"t{k}": [] for k in tracker.HORIZONS}
        self.has_plan = False
        self.plans: List[Tuple[str, Optional[float]]] = []
        self.fades: List[bool] = []

    def add(self, d: Dict[str, Any]) -> None:
        self.signals += 1
        fw = d.get("forward") or {}
        for key in self.rets:
            x = fw.get(key) or {}
            if x.get("status") != "done":
                continue
            if x.get("return_pct") is not None:
                self.rets[key].append(x["return_pct"])
            if x.get("mfe_pct") is not None:
                self.mfe[key].append(x["mfe_pct"])
            if x.get("mae_pct") is not None:
                self.mae[key].append(x["mae_pct"])
        plan = d.get("plan")
        if isinstance(plan, dict):
            self.has_plan = True
            if plan.get("first_event") in PLAN_EVENTS:
                self.plans.append((plan["first_event"], plan.get("r_multiple")))
        fd = d.get("fade")
        if isinstance(fd, dict) and fd.get("faded") is not None:
            self.fades.append(bool(fd["faded"]))

    def result(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"signals": self.signals, "horizons": {}}
        measured_max = 0
        for key, rets in self.rets.items():
            n = len(rets)
            wins = sum(1 for r in rets if r > 0)
            measured_max = max(measured_max, n)
            out["horizons"][key] = {
                "n": n, "hit_rate_pct": round(wins / n * 100, 1) if n else None, "hit_rate_ci95_pct": wilson(wins, n),
                "avg_return_pct": _avg(rets), "median_return_pct": round(statistics.median(rets), 2) if rets else None,
                "avg_mfe_pct": _avg(self.mfe[key]), "avg_mae_pct": _avg(self.mae[key]), "small_sample": n < MIN_SAMPLE}
        if self.has_plan:
            n = len(self.plans)
            rs = [r for _, r in self.plans if r is not None]
            out["plan"] = {"rules": "scan-plan-v3", "decided": n,
                           **{f"{e}_rate_pct": (round(sum(1 for f, _ in self.plans if f == e) / n * 100, 1) if n else None)
                              for e in PLAN_EVENTS},
                           "avg_r_multiple": _avg(rs), "small_sample": n < MIN_SAMPLE}
        if self.fades:
            out["fade"] = {"n": len(self.fades), "faded_rate_pct": round(sum(self.fades) / len(self.fades) * 100, 1),
                           "small_sample": len(self.fades) < MIN_SAMPLE}
        out["small_sample"] = measured_max < MIN_SAMPLE
        if out["small_sample"]:
            out["note"] = SMALL_SAMPLE_NOTE
        return out


def summarize(docs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    acc = Acc()
    for d in docs:
        acc.add(d)
    return acc.result()


def _rows(groups: Dict[str, Acc]) -> List[Dict[str, Any]]:
    rows = [{"key": k, **a.result()} for k, a in groups.items()]
    rows.sort(key=lambda r: (-r["signals"], r["key"]))
    return rows


async def scanners(db, *, day_from: str, day_to: str, kind: Optional[str] = None) -> Dict[str, Any]:
    """The report for IST days day_from..day_to (inclusive), streamed from Mongo with only the fields it uses."""
    q: Dict[str, Any] = {"day": {"$gte": day_from, "$lte": day_to}}
    if kind:
        q["kind"] = kind
    total = Acc()
    groups: Dict[str, Dict[str, Acc]] = {"scanner": {}, "category": {}, "band": {}}
    async for d in db[tracker.COLL].find(q, PROJECTION):
        total.add(d)
        for name, key in (("scanner", d.get("scanner_id")), ("category", d.get("category")),
                          ("band", band(d.get("scanner_score")))):
            groups[name].setdefault(str(key), Acc()).add(d)
    return {"ok": True, "from": day_from, "to": day_to, "kind": kind, "version": tracker.VERSION,
            "min_sample": MIN_SAMPLE, "note": NOTE, "totals": total.result(),
            "by_scanner": _rows(groups["scanner"]), "by_category": _rows(groups["category"]),
            "by_score_band": _rows(groups["band"])}
