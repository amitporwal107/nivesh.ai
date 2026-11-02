"""Pure logic for TrueData daily bars: clean them, drop unfinished ones, and stitch a symbol's history to our basis.

No database, no network: nidp.services.truedata_history.service (stock history) and nidp.services.truedata_macro
(nightly TD_* macro refresh) call these, and the unit tests drive them directly.

Facts these rules come from (measured 2 Nov 2026, test_reports/truedata_research_data_20261102.md):
  * TrueData's daily bars are ADJUSTED for corporate actions INCLUDING demergers, and rounded to 0.05. Our
    nidp.prices_eod_adjusted adjusts splits and bonuses only: on 2024-04-01 RELIANCE TD 1484.80 vs ours 1484.775
    (rounding), TCS identical, ITC TD 402.55 vs ours 426.70 (ITC Hotels demerger). So history is rescaled by
    factor = our adj_close / TD close, measured on the symbol's first warehouse days.
  * Exact duplicate daily bars exist (2020-06-16 on MCX, 2021-07-23 on indices); MCX 2020-10-08's copies DISAGREE, so
    such a date is dropped rather than guessed.
  * MCX trades until ~23:30-23:55 IST: a bar for today fetched before then is partial. Index bars are final after
    15:30 IST.
  * A factor far above 1 is what a large demerger looks like (TrueData adjusts the history down, ours keeps the
    pre-demerger level): on 2 Nov SIEMENS 2.01, ALLCARGO 3.2, DCMSRIND 3.38, RAYMOND 4.95, each with a demerger in
    nidp.corporate_actions after its first warehouse day and the matching one-day drop in our adjusted series. Such a
    factor is accepted only with that record; without it the symbol is flagged (a missed split or bonus looks the same).
  * TrueData keys history under the CURRENT symbol (LTM carries LTI's bars from 2016; LTIM answers "no data"), while
    our warehouse keeps the old name until the rename date. Such a symbol's history ends long before our first row
    under the new name: that is a seam gap, flagged, never bridged by a guess.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# ── Parameters (the PR's test cases name each) ───────────────────────────────────────────────────────────────────
MIN_OVERLAP_DAYS = 3            # overlap days needed to call a factor stable
OVERLAP_DAYS = 10               # our first N warehouse days used for the factor
TD_TICK = 0.05                  # TrueData rounds adjusted prices to 0.05
REL_TOL = 0.0002                # +2 bp on top of the rounding allowance
MAX_SEAM_GAP_DAYS = 7           # calendar days between history's last bar and our first bar (Indian holidays <= 5)
FACTOR_RANGE = (0.5, 2.0)       # outside: one side missed a split/bonus — unless a demerger explains it (below)
DEMERGER_MAX_FACTOR = 10.0      # above FACTOR_RANGE, accepted only with a demerger recorded after our first day
BASIS_ABS_TOL = 0.006           # rupees: TD's close on a history date, re-fetched, must equal the raw file's

# Statuses (prices_eod_history_stitch.status)
LOADED = "LOADED"
SKIPPED_EXISTING = "SKIPPED_EXISTING"
NO_HISTORY = "NO_HISTORY"
NO_WAREHOUSE = "NO_WAREHOUSE"
SEAM_GAP = "SEAM_GAP"
NO_OVERLAP = "NO_OVERLAP"
UNSTABLE = "UNSTABLE"
FACTOR_OUT_OF_RANGE = "FACTOR_OUT_OF_RANGE"
BASIS_CHANGED = "BASIS_CHANGED"
NO_BASIS_CHECK = "NO_BASIS_CHECK"
FETCH_FAILED = "FETCH_FAILED"

# When a segment's bar for today is final (IST wall clock).
FINAL_AFTER = {
    "mcx": time(23, 59),        # MCX closes 23:30 (winter) / 23:55 (US summer time); today's bar is never stored before
    "index": time(16, 0),       # NSE indices close 15:30; 30 minutes' margin
    "equity": time(16, 0),
}


@dataclass
class Bar:
    day: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: float
    volume: Optional[int]


@dataclass
class CleanReport:
    rows_in: int = 0
    duplicate_dates: int = 0                         # dates that came more than once (identical copies collapsed)
    conflicting_dates: List[date] = field(default_factory=list)   # dates dropped: copies disagree
    bad_rows: int = 0                                # no date, or no positive close


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _key(b: Bar) -> Tuple:
    return (b.open, b.high, b.low, b.close, b.volume)


def clean_bars(rows: Iterable[Mapping[str, Any]]) -> Tuple[Dict[date, Bar], CleanReport]:
    """TrueData rows ({timestamp, open, high, low, close, volume, ...}) → one Bar per date.

    A date that came twice with identical values keeps one copy; a date whose copies disagree is DROPPED (listed in the
    report). Rows without a date or a positive close are dropped (counted)."""
    rep = CleanReport()
    seen: Dict[date, List[Bar]] = {}
    for r in rows:
        rep.rows_in += 1
        d, close = _day(r.get("timestamp")), _f(r.get("close"))
        if d is None or close is None or close <= 0:
            rep.bad_rows += 1
            continue
        vol = _f(r.get("volume"))
        seen.setdefault(d, []).append(Bar(d, _f(r.get("open")), _f(r.get("high")), _f(r.get("low")), close,
                                          None if vol is None else int(vol)))
    out: Dict[date, Bar] = {}
    for d in sorted(seen):
        copies = seen[d]
        if len(copies) > 1:
            rep.duplicate_dates += 1
            if len({_key(b) for b in copies}) > 1:
                rep.conflicting_dates.append(d)
                continue
        out[d] = copies[0]
    return out, rep


def drop_unfinished(bars: Dict[date, Bar], segment: str, now_ist: datetime) -> Tuple[Dict[date, Bar], List[date]]:
    """Remove bars dated after today, and today's bar unless the segment's day is final at `now_ist` (IST wall clock).
    Returns (kept, dropped dates)."""
    today = now_ist.date()
    final = now_ist.time() >= FINAL_AFTER[segment]
    dropped = [d for d in bars if d > today or (d == today and not final)]
    return {d: b for d, b in bars.items() if d not in dropped}, sorted(dropped)


# ── Stitching ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class StitchResult:
    symbol: str
    status: str
    reason: str = ""
    factor: Optional[float] = None
    overlap_days: int = 0
    overlap_from: Optional[date] = None
    overlap_to: Optional[date] = None
    max_dev_pct: Optional[float] = None
    history_from: Optional[date] = None
    history_to: Optional[date] = None
    warehouse_from: Optional[date] = None
    duplicate_dates: int = 0
    conflicting_dates: int = 0
    seam_move_pct: Optional[float] = None
    td_seam_move_pct: Optional[float] = None
    rows: List[Dict[str, Any]] = field(default_factory=list)   # rows for prices_eod_history (LOADED only)

    @property
    def loaded(self) -> bool:
        return self.status == LOADED

    def summary(self) -> Dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "rows"}
        out["rows_loaded"] = len(self.rows)
        return out


def _tol(td_close: float) -> float:
    """Allowed relative gap between two overlap ratios: TrueData's 0.05 rounding at this price level, plus 2 bp."""
    return REL_TOL + TD_TICK / td_close


def _pct(x: float) -> float:
    return round(x * 100.0, 6)


def stitch_symbol(symbol: str, history_rows: Iterable[Mapping[str, Any]],
                  warehouse: Sequence[Tuple[date, float]],
                  overlap_rows: Iterable[Mapping[str, Any]],
                  demerger_dates: Sequence[date] = ()) -> StitchResult:
    """Stitch one symbol's TrueData history to our basis.

    history_rows   TrueData daily bars for the history period (the raw file or a fetch).
    warehouse      our first days for the symbol: [(as_of_date, adj_close)] ascending, from prices_eod_adjusted.
    overlap_rows   TrueData daily bars covering the last history days AND our first days (one fetch per symbol).
    demerger_dates ex-dates of the symbol's demergers in nidp.corporate_actions (any date; only those on or after our
                   first day count).

    LOADED only when: our first day is within MAX_SEAM_GAP_DAYS of history's last bar; TrueData's re-fetched close equals
    the history file's on at least one history date (the basis did not change since); >= MIN_OVERLAP_DAYS of our first
    days have a TrueData close; every overlap ratio our/TD is within rounding of the median; the factor is inside
    FACTOR_RANGE, or above it (up to DEMERGER_MAX_FACTOR) with a demerger recorded on or after our first day. A factor
    indistinguishable from 1 is stored as exactly 1."""
    hist, hrep = clean_bars(history_rows)
    res = StitchResult(symbol, NO_HISTORY, duplicate_dates=hrep.duplicate_dates,
                       conflicting_dates=len(hrep.conflicting_dates))
    wh = sorted((d, float(c)) for d, c in warehouse if c is not None and float(c) > 0)
    if wh:
        res.warehouse_from = wh[0][0]
    if not hist:
        res.reason = "TrueData has no usable bars for the history period"
        return res
    if not wh:
        res.status, res.reason = NO_WAREHOUSE, "no prices_eod_adjusted row to stitch to"
        res.history_from, res.history_to = min(hist), max(hist)
        return res
    first = wh[0][0]
    hist = {d: b for d, b in hist.items() if d < first}            # the warehouse wins on any common date
    if not hist:
        res.reason = f"no TrueData bar before our first date {first}"
        return res
    res.history_from, res.history_to = min(hist), max(hist)
    last = res.history_to
    gap = (first - last).days
    if gap > MAX_SEAM_GAP_DAYS:
        res.status = SEAM_GAP
        res.reason = (f"history ends {last}, our prices start {first} ({gap} days later): renamed symbol or late "
                      "adjuster coverage; not bridged")
        return res

    over, _ = clean_bars(overlap_rows)
    # 1. The basis did not change since the history was fetched: TD's close on history dates, re-fetched, is the same.
    common_hist = [d for d in over if d in hist]
    if not common_hist:
        res.status, res.reason = NO_BASIS_CHECK, "the overlap bars share no date with the history bars"
        return res
    moved = [d for d in common_hist if abs(over[d].close - hist[d].close) > BASIS_ABS_TOL]
    if moved:
        d = moved[0]
        res.status = BASIS_CHANGED
        res.reason = (f"TrueData's close on {d} is now {over[d].close}, the history file has {hist[d].close}: "
                      "re-fetch the history")
        return res

    # 2. Overlap ratios on our first days.
    pts = [(d, c / over[d].close, over[d].close) for d, c in wh[:OVERLAP_DAYS] if d in over]
    res.overlap_days = len(pts)
    if pts:
        res.overlap_from, res.overlap_to = pts[0][0], pts[-1][0]
    if len(pts) < MIN_OVERLAP_DAYS:
        res.status = NO_OVERLAP
        res.reason = f"{len(pts)} of our first {len(wh[:OVERLAP_DAYS])} days have a TrueData bar (need {MIN_OVERLAP_DAYS})"
        return res
    med = statistics.median(r for _, r, _ in pts)
    devs = [(abs(r / med - 1.0), _tol(tc), d) for d, r, tc in pts]
    res.max_dev_pct = _pct(max(dv for dv, _, _ in devs))
    bad = [(dv, tl, d) for dv, tl, d in devs if dv > tl]
    if bad:
        dv, tl, d = max(bad)
        res.status, res.factor = UNSTABLE, round(med, 8)
        res.reason = f"ratio on {d} is {dv * 100:.4f}% off the median (allowed {tl * 100:.4f}%)"
        return res
    same_basis = all(abs(r - 1.0) <= _tol(tc) for _, r, tc in pts)
    factor = 1.0 if same_basis else round(med, 8)
    res.factor = factor
    demergers = sorted(d for d in demerger_dates if d >= first)
    if not FACTOR_RANGE[0] <= factor <= FACTOR_RANGE[1]:
        if not (demergers and FACTOR_RANGE[1] < factor <= DEMERGER_MAX_FACTOR):
            res.status = FACTOR_OUT_OF_RANGE
            res.reason = (f"factor {factor} outside {FACTOR_RANGE} and no demerger recorded after {first} "
                          "(nidp.corporate_actions): one side missed a split or bonus; review")
            return res

    # 3. Seam: our first close vs the last stitched close, beside TrueData's own move over the same days.
    our_first = wh[0][1]
    stitched_last = hist[last].close * factor
    res.seam_move_pct = _pct(our_first / stitched_last - 1.0)
    if first in over:
        res.td_seam_move_pct = _pct(over[first].close / hist[last].close - 1.0)

    def sc(v: Optional[float]) -> Optional[float]:
        return None if v is None else round(v * factor, 6)

    res.rows = [{"symbol": symbol, "as_of_date": d, "adj_open": sc(b.open), "adj_high": sc(b.high), "adj_low": sc(b.low),
                 "adj_close": round(b.close * factor, 6), "volume": b.volume, "stitch_factor": factor}
                for d, b in sorted(hist.items())]
    res.status = LOADED
    if same_basis:
        res.reason = "same basis as ours"
    else:
        res.reason = "rescaled to our basis (TrueData adjusts what ours does not)"
        if demergers:
            res.reason += "; demerger ex-date(s) after our first day: " + ", ".join(d.isoformat() for d in demergers)
    return res


def overlap_window(history_to: date, warehouse_days: Sequence[date]) -> Tuple[date, date]:
    """The TrueData fetch that both checks the basis (a few history days) and measures the factor (our first days)."""
    end = warehouse_days[min(OVERLAP_DAYS, len(warehouse_days)) - 1]
    return history_to - timedelta(days=10), end
