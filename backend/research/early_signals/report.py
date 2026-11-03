"""Early-signals report: how well each dashboard widget, each confluence level and each widget pair flagged stocks BEFORE
they moved +5% above the day's open (owner, 3 Nov 2026), from the replay's flags and outcomes.py.

Per signal (first flag per stock-day):
  flagged      stock-days flagged (with candles)
  late         flagged at or after the +5% move (not counted as early)
  eligible     flagged while still below +5% from the open — the denominator
  precision    eligible flags that then reached +5% from the open
  base rate    for the same days and steps, the share of ALL universe stock-days still below +5% that went on to reach it
               (the flags' own mix of days and steps, so time of day does not flatter a late signal)
  lift         precision / base rate
  recall       +5% movers flagged early / all +5% movers (and / movers that reached +5% after the first step, "catchable")
  medians      lead time (hits), move already done at the flag, upside and drawdown after the flag, close vs the flag price
Time of day: first flag before 10:00, 10:00–11:30, later.

    python -m research.early_signals.report --bars-dir DIR --flags flags.csv --universe universe.csv --out report.md \
        [--json summary.json] [--outcomes-csv outcomes.csv] [--min-support 30] [--top-pairs 15]

In-sample, research only; costs, slippage and fills at the flag price are not modelled.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import outcomes as O

logger = logging.getLogger(__name__)

STEP_GRID = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 15, 30, 45) if (9, 30) <= (h, m) <= (15, 30)]
FIRST_STEP = STEP_GRID[0]
BUCKETS = (("before 10:00", lambda s: s < "10:00"), ("10:00–11:30", lambda s: "10:00" <= s <= "11:30"),
           ("after 11:30", lambda s: s > "11:30"))
BARRED = re.compile(r"\b(buy\w*|sell\w*|target\w*|stop ?loss\w*|sl|pick\w*|recommend\w*|entry|entries|exit\w*)\b", re.I)
SCOPE = ("In-sample study over the sessions listed below: the widgets were replayed on past candles with only the data known "
         "at each step, and the outcomes are what happened after each flag. There is no out-of-sample test yet; costs, "
         "slippage and whether a flag price could actually be traded are not modelled. A higher precision or lift describes "
         "the past sessions only; it is not a forecast.")


def widget_titles() -> Dict[str, str]:
    """Dashboard widget id -> title, when the app's module is importable (it is in the backend container)."""
    try:
        from services.scan_builder import market_dashboard as md
    except Exception as e:  # noqa: BLE001 — titles are cosmetic; ids are shown instead
        logger.warning("early signals report: widget titles unavailable (%s)", type(e).__name__)
        return {}
    return {w.id: w.title for w in md.WIDGETS}


def _median(x: pd.Series) -> Optional[float]:
    x = pd.to_numeric(x, errors="coerce").dropna()
    return float(x.median()) if len(x) else None


def signal_stats(rows: pd.DataFrame, sd: pd.DataFrame, brates: Dict[Tuple[str, str], float]) -> Dict[str, Any]:
    """Figures for one signal's outcome rows (see the module docstring)."""
    eligible = rows[rows["early"].astype(bool)]
    hits = eligible[eligible["hit"].astype(bool)]
    n_el, n_hit = len(eligible), len(hits)
    base_vals = [brates.get((d, s), float("nan")) for d, s in zip(eligible["day"], eligible["step"])]
    base = float(np.nanmean(base_vals)) if base_vals and not all(math.isnan(v) for v in base_vals) else None
    precision = n_hit / n_el if n_el else None
    t5 = pd.to_numeric(sd["t5"], errors="coerce")
    movers = int(t5.notna().sum())
    first_ts = pd.Series([O.step_ts(d, FIRST_STEP) for d in sd["day"]], index=sd.index, dtype=float)
    catchable = int((t5.notna() & (t5 > first_ts)).sum())
    buckets = {}
    for name, test in BUCKETS:
        b = eligible[eligible["step"].map(test)]
        bh = int(b["hit"].astype(bool).sum())
        buckets[name] = {"eligible": len(b), "hits": bh, "precision": (bh / len(b)) if len(b) else None}
    return {
        "flagged": len(rows), "late": int(rows["late"].astype(bool).sum()), "eligible": n_el, "hits": n_hit,
        "precision": precision, "base_rate": base,
        "lift": (precision / base) if precision is not None and base else None,
        "recall": (n_hit / movers) if movers else None, "recall_catchable": (n_hit / catchable) if catchable else None,
        "median_lead_min": _median(hits["lead_min"]), "median_move_done_pct": _median(eligible["move_done_pct"]),
        "median_upside_pct": _median(eligible["upside_pct"]), "median_drawdown_pct": _median(eligible["drawdown_pct"]),
        "median_close_vs_flag_pct": _median(eligible["close_vs_flag_pct"]), "by_time": buckets,
    }


def summarize(outs: pd.DataFrame, sd: pd.DataFrame, brates: Dict[Tuple[str, str], float]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for sig, rows in outs.groupby("signal", sort=False):
        st = signal_stats(rows, sd, brates)
        st["kind"] = str(rows["kind"].iloc[0])
        out[str(sig)] = st
    return out


def label(sig: str, titles: Dict[str, str]) -> str:
    if sig.startswith("w:"):
        return titles.get(sig[2:], sig[2:])
    if sig.startswith("p:"):
        a, b = sig[2:].split("+", 1)
        return f"{titles.get(a, a)} + {titles.get(b, b)}"
    if sig.startswith("k>="):
        k = sig[3:]
        return "Any one widget" if k == "1" else f"Any {k} widgets at the same step"
    return sig


def _pct(v: Optional[float], dp: int = 1) -> str:
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:.{dp}f}%"


def _num(v: Optional[float], dp: int = 1, suffix: str = "") -> str:
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{dp}f}{suffix}"


def _table(stats: Dict[str, Dict[str, Any]], sigs: Sequence[str], titles: Dict[str, str]) -> List[str]:
    lines = ["| Signal | Flagged | Late | Still below +5% | Reached +5% after | Precision | Base rate | Lift | Recall "
             "(catchable) | Lead, min | Move done at flag | Upside after | Drawdown after | Close vs flag | Before 10:00 | "
             "10:00–11:30 | After 11:30 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in sigs:
        st = stats[s]
        bt = st["by_time"]
        tb = [f"{_pct(bt[n]['precision'], 0)} of {bt[n]['eligible']}" for n, _ in BUCKETS]
        lines.append("| " + " | ".join([
            label(s, titles), str(st["flagged"]), str(st["late"]), str(st["eligible"]), str(st["hits"]),
            _pct(st["precision"]), _pct(st["base_rate"]), _num(st["lift"], 2, "×"),
            f"{_pct(st['recall'])} ({_pct(st['recall_catchable'])})", _num(st["median_lead_min"], 0),
            _num(st["median_move_done_pct"], 2, "%"), _num(st["median_upside_pct"], 2, "%"),
            _num(st["median_drawdown_pct"], 2, "%"), _num(st["median_close_vs_flag_pct"], 2, "%")] + tb) + " |")
    return lines


def _ranked(stats: Dict[str, Dict[str, Any]], kind: str, min_support: int) -> Tuple[List[str], List[str]]:
    sigs = [s for s, st in stats.items() if st["kind"] == kind]
    ok = [s for s in sigs if stats[s]["eligible"] >= min_support]
    ok.sort(key=lambda s: (-(stats[s]["precision"] or 0), -stats[s]["eligible"], s))
    thin = sorted((s for s in sigs if s not in ok), key=lambda s: (-stats[s]["eligible"], s))
    return ok, thin


def render(stats: Dict[str, Dict[str, Any]], sd: pd.DataFrame, meta: Dict[str, Any], titles: Dict[str, str],
           min_support: int = 30, top_pairs: int = 15) -> str:
    t5 = pd.to_numeric(sd["t5"], errors="coerce")
    days = sorted(sd["day"].unique().tolist())
    lines = ["# Early signals on the Scan dashboard: which flags came before a +5% move from the open", "",
             SCOPE, "",
             f"- Sessions: {len(days)} ({days[0] if days else '–'} to {days[-1] if days else '–'})",
             f"- Stock-days with candles: {len(sd):,}; reached +5% above the open: {int(t5.notna().sum()):,} "
             f"({_pct(t5.notna().mean() if len(sd) else None)} of stock-days)",
             f"- Flags read: {meta.get('flag_rows', 0):,} rows; widgets seen: {meta.get('widgets', 0)}; "
             f"minimum support for a ranked row: {min_support} flags still below +5%",
             "- Steps: every 15 minutes from 09:30 to 15:30 IST; a flag counts only while the stock was still below +5% "
             "from its open (\"Still below +5%\"); flags after the move are counted as \"Late\".", ""]
    sections = (("Single widgets", "widget"), ("Confluence: several widgets at the same step", "confluence"),
                ("Widget pairs at the same step", "pair"))
    for title, kind in sections:
        ok, thin = _ranked(stats, kind, min_support)
        if kind == "pair":
            by_support = sorted(ok + thin, key=lambda s: (-stats[s]["eligible"], s))[:top_pairs]
            ok = [s for s in ok if s in by_support]
            thin = [s for s in thin if s in by_support]
        lines += [f"## {title}", ""]
        if ok:
            lines += [f"Ranked by precision (rows with at least {min_support} flags still below +5%):", ""]
            lines += _table(stats, ok, titles) + [""]
        if thin:
            lines += [f"Below the minimum support ({len(thin)} signal(s)) — too few flags to rank:", ""]
            lines += _table(stats, thin, titles) + [""]
        if not ok and not thin:
            lines += ["No flags of this kind.", ""]
    text = "\n".join(lines)
    bad = BARRED.findall(text)
    if bad:
        raise ValueError(f"report wording: barred word(s) {sorted(set(w.lower() for w in bad))}")
    return text


def run(bars_dir: str, flags_csv: str, universe_csv: str, *, min_support: int = 30, top_pairs: int = 15,
        titles: Optional[Dict[str, str]] = None) -> Tuple[str, Dict[str, Any], pd.DataFrame]:
    """(markdown, JSON summary, outcome rows) from the replay's files and the candles."""
    flags = O.read_flags(flags_csv)
    universe = O.read_universe(universe_csv)
    days = O.load_days(bars_dir, set(universe["symbol"]) | set(flags["symbol"]))
    sd = O.stock_days(days, universe)
    firsts = O.first_signals(flags)
    outs = O.outcomes(firsts, days)
    steps = sorted(set(STEP_GRID) | set(flags["step"].unique().tolist()))
    brates = O.base_rates(sd, steps)
    stats = summarize(outs, sd, brates)
    titles = widget_titles() if titles is None else titles
    meta = {"flag_rows": int(len(flags)), "widgets": int(flags["widget"].nunique()), "sessions": int(sd["day"].nunique()),
            "stock_days": int(len(sd)), "movers": int(pd.to_numeric(sd["t5"], errors="coerce").notna().sum()),
            "min_support": min_support, "scope": SCOPE}
    md = render(stats, sd, meta, titles, min_support=min_support, top_pairs=top_pairs)
    summary = {"meta": meta, "signals": [{"signal": s, "label": label(s, titles), **st} for s, st in stats.items()]}
    return md, summary, outs


def clean_json(v: Any) -> Any:
    """NaN / inf -> None and numpy scalars -> Python, so the summary is strict JSON."""
    if isinstance(v, dict):
        return {str(k): clean_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean_json(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bars-dir", required=True)
    ap.add_argument("--flags", required=True)
    ap.add_argument("--universe", required=True)
    ap.add_argument("--out", required=True, help="markdown report path")
    ap.add_argument("--json", help="JSON summary path")
    ap.add_argument("--outcomes-csv", help="per-flag outcome rows")
    ap.add_argument("--min-support", type=int, default=30)
    ap.add_argument("--top-pairs", type=int, default=15)
    a = ap.parse_args(argv)
    md, summary, outs = run(a.bars_dir, a.flags, a.universe, min_support=a.min_support, top_pairs=a.top_pairs)
    with open(a.out, "w") as fh:
        fh.write(md)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(clean_json(summary), fh, indent=1)
    if a.outcomes_csv:
        O.write_csv(outs, a.outcomes_csv)
    print(f"report: {a.out} ({summary['meta']['sessions']} sessions, {summary['meta']['stock_days']} stock-days, "
          f"{len(summary['signals'])} signals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
