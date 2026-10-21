"""DaaS — the Smart trading desk's RESULTS EXPECTATION for one results meeting, from the company's own published quarters.

    GET /v1/desk/events-calendar/expectation?symbol=&date=YYYY-MM-DD      (date = the results meeting's date)
    GET /v1/desk/events-calendar/expectations?from=&to=&universe=fno|n50|all   (every results meeting in a window of at most 3 days,
                                                                                one compact summary each: the desk's "today & tomorrow" board)

Read-only. Every figure names its source; a missing figure is null, never 0 or a guess.

What it is, and is not
  It is a BASELINE: what the company's own published quarters imply for the quarter being reported. It is not an analyst
  consensus (nidp.earnings_estimates is empty: no consensus source is ingested) and not a forecast: past behaviour only.
  There is no LLM text and no bullish / bearish label (PRD §6.5: an event is never labelled from language alone).

Method  ("same quarter last year × recent growth")
  expected(t) = value(t − 4 quarters) × (1 + g),   g = average of the two latest year-on-year growth rates,
                                                    g1 = value(t−1) ÷ value(t−5) − 1 and g2 = value(t−2) ÷ value(t−6) − 1.
  Needs 7 published quarters (t−1, t−2, t−4, t−5, t−6 and the target's own past), all positive. Comparing with the same quarter a
  year earlier removes seasonality. Quarterly history in the warehouse is 8 quarters per stock (Dec 2024 on), so that is the limit.
  Reliability: no number when a needed quarter is missing, when a profit figure the method divides by is zero or negative, when
  last year's profit was under 0.5 % of its revenue (a near-zero base makes growth meaningless), or when |g| is over 100 %.
  EPS is not compared across quarters (bonus / split change the share count): expected EPS = expected profit × (latest quarter's EPS
  ÷ latest quarter's profit), i.e. the share base is held at the latest quarter.

Band  (how far the method has been wrong, measured on real data, not assumed)
  The same method is run on EVERY stock for every quarter it can be tested on, point-in-time (only quarters known before the
  tested quarter's own filing). error = actual ÷ expected − 1. The band is the 10th–90th percentile of those errors for the
  metric, in the stock's own "instability" tercile (instability = |g1 − g2|: a stock whose growth swings is forecast less
  tightly), with a minimum half-width. A stock has only 2 testable quarters, so its own errors are shown but cannot set its band.
  universe_backtest reports the accuracy and two out-of-sample checks of the band (a stock holdout with thousands of tests, and
  the latest quarter, which is small), next to the benchmark "last year's quarter unchanged" that the method has to beat.

Point-in-time
  A stored quarter is "known" at its broadcast_at, else period_end + 60 days (SEBI's deadline is 45 days; 60 is the safe ceiling).
  For an UPCOMING meeting the cutoff is now; for a DECLARED one it is the target filing's own broadcast time: the expectation uses
  nothing the filing itself or anything after it revealed. Values are the latest stored, not as first filed (restatements are
  not tracked).

Audit status
  nidp.nse_financials_quarterly.audited is NULL on every row (the rows come from Trendlyne and Screener, which carry no audit
  flag and no XBRL link; the NSE parser would read it). The only company-published statement we hold is the wording of the board-
  meeting notice (nidp.event_calendar.purpose), e.g. "…Unaudited Standalone and Consolidated Financial Results…". So audit_status
  is "unaudited" / "audited" only when that notice says so, with audit_basis naming that source; it is "mixed" when the notice
  names both, and "not recorded" when it names neither. It is never inferred from the quarter or from SEBI rules.

Evidence  (nidp.corporate_announcements, NSE filings only)
  Up to 8 recent filings that can bear on the quarter: orders, capex, M&A, rating actions, analyst / investor meets, press
  releases, buybacks, dividends, litigation, board outcomes, management changes. Each carries its exchange subject, filing time,
  the classifier's category label (a label, never a sentiment or score) and the exchange's attachment link. There is no news
  feed in the warehouse; this is exchange filings only, and `gaps` says so.
"""
from __future__ import annotations

import asyncio
import calendar
import re
import statistics
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify, normalise_symbol
from nidp.services.daas_api.routers.desk_events import FNO_SQL, INDUSTRY_SQL, N50_SQL, UNIVERSES, event_id

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

KNOWN_LAG_DAYS = 60            # a quarter with no broadcast time is treated as known this long after its period end
MIN_PAT_MARGIN = 0.005         # last year's profit must be at least this share of its revenue
MAX_GROWTH = 1.0               # |g| over 100 % → no number
BAND_LO_Q, BAND_HI_Q = 0.10, 0.90
MIN_HALF_WIDTH = {"revenue": 0.01, "pat": 0.03}    # the band is never narrower than ±1 % revenue / ±3 % profit
MIN_BUCKET_N = 100             # fewer errors than this in a size × stability cell → the next wider group is used
SIZE_BUCKETS = 4               # company size = last year's quarterly revenue, in quarters of the universe
INST_BUCKETS = 3               # growth stability = |g1 − g2|, in terciles
EVIDENCE_DAYS = 90
EVIDENCE_LIMIT = 8
STORE_TTL_S = 1800
SOURCES = {
    "quarters": "Company quarterly results as stored (nidp.nse_financials_quarterly; rows from Trendlyne and Screener)",
    "calendar": "NSE event calendar (nidp.event_calendar)",
    "announcements": "NSE corporate announcements (nidp.corporate_announcements)",
}
METHOD_NAME = "Same quarter last year × recent growth"
METHOD_FORMULA = (
    "expected = value of the same quarter a year earlier × (1 + average of the last two year-on-year growth rates); "
    "band = 10th–90th percentile of this method's own past errors across all stocks, for stocks with similar growth stability"
)
ONLY_BASELINE = "A baseline from the company's own published quarters, not an analyst consensus and not a forecast."
GAP_CONSENSUS = "no analyst consensus is available (nidp.earnings_estimates is empty): this is a baseline, not a consensus"
GAP_NEWS = "no news feed is stored: the evidence list is exchange filings only"
GAP_RESTATE = "stored quarters are the latest values, not as first filed; restatements are not tracked"
GAP_AUDIT = ("audit status is not recorded in the stored results (the 'audited' field is empty; the sources carry no audit flag); "
             "it is shown only where the company's own board-meeting notice states it")
UNAUDITED_RE = re.compile(r"\bun[\s-]?audited\b", re.I)
AUDITED_RE = re.compile(r"(?<![a-z-])audited\b", re.I)

QMONTHS = (3, 6, 9, 12)
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
PERIOD_RE = re.compile(
    r"(?:period|quarter|half[\s-]?year|year)\s+ended\s+(?:on\s+)?(?:the\s+)?(\d{1,2})?(?:st|nd|rd|th)?[\s,]*([A-Za-z]{3,9})\.?[\s,]*(\d{1,2})?(?:st|nd|rd|th)?[\s,]*(\d{4})",
    re.I)
DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})|([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", re.I)
DATE_PARAM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── pure helpers: dates ───────────────────────────────────────────────────────

def quarter_end(y: int, q_month: int) -> date:
    return date(y, q_month, calendar.monthrange(y, q_month)[1])


def shift_quarters(pe: date, n: int) -> date:
    """The quarter end n quarters after (n > 0) or before (n < 0) the quarter end `pe`."""
    idx = pe.year * 4 + (pe.month // 3 - 1) + n
    y, q = divmod(idx, 4)
    return quarter_end(y, QMONTHS[q])


def last_quarter_end_before(d: date) -> date:
    for n in range(0, 5):
        cand = shift_quarters(quarter_end(d.year, QMONTHS[(d.month - 1) // 3]), -n)
        if cand < d:
            return cand
    return quarter_end(d.year - 1, 12)


def is_quarter_end(d: date) -> bool:
    return d == quarter_end(d.year, d.month) and d.month in QMONTHS


def parse_period_end(purpose: Optional[str], event_date: date) -> Tuple[date, bool]:
    """(period_end, inferred). Reads "…period ended September 30, 2026" style text; else the last quarter end before the meeting."""
    text = purpose or ""
    for m in PERIOD_RE.finditer(text):
        mon = MONTHS.get((m.group(2) or "").lower())
        yr = int(m.group(4))
        if mon in QMONTHS and 2000 <= yr <= 2100:
            return quarter_end(yr, mon), False
    for m in DATE_RE.finditer(text):
        if m.group(1):
            mon, yr = MONTHS.get(m.group(2).lower()), int(m.group(3))
        else:
            mon, yr = MONTHS.get(m.group(4).lower()), int(m.group(6))
        if mon in QMONTHS and 2000 <= yr <= 2100:
            d = date(yr, mon, min(int(m.group(1) or m.group(5)), calendar.monthrange(yr, mon)[1]))
            if is_quarter_end(d) and d < event_date:
                return d, False
    return last_quarter_end_before(event_date), True


def period_label(pe: date) -> str:
    """Indian fiscal label: Sep 2026 → 'Q2 FY27 (Jul–Sep 2026)'."""
    fy = pe.year + 1 if pe.month > 3 else pe.year
    q = {6: 1, 9: 2, 12: 3, 3: 4}[pe.month]
    start = shift_quarters(pe, -1) + timedelta(days=1)
    return f"Q{q} FY{str(fy)[2:]} ({calendar.month_abbr[start.month]}–{calendar.month_abbr[pe.month]} {pe.year})"


def known_at(period_end: date, broadcast_at: Optional[datetime]) -> datetime:
    if broadcast_at is not None:
        return broadcast_at if broadcast_at.tzinfo else broadcast_at.replace(tzinfo=timezone.utc)
    return datetime.combine(period_end + timedelta(days=KNOWN_LAG_DAYS), datetime.min.time(), tzinfo=timezone.utc)


def audit_from_notice(purpose: Optional[str]) -> Tuple[str, str]:
    """(audit_status, audit_basis) from the wording of the company's own board-meeting notice. Never from anything else."""
    text = purpose or ""
    un, au = bool(UNAUDITED_RE.search(text)), bool(AUDITED_RE.search(UNAUDITED_RE.sub(" ", text)))
    if un and au:
        return "mixed", "the board-meeting notice names both audited and unaudited figures (nidp.event_calendar.purpose)"
    if un:
        return "unaudited", "stated in the company's board-meeting notice (nidp.event_calendar.purpose), not read from the filing"
    if au:
        return "audited", "stated in the company's board-meeting notice (nidp.event_calendar.purpose), not read from the filing"
    return "not recorded", "neither the stored results nor the board-meeting notice state it"


# ── pure helpers: series and forecast ─────────────────────────────────────────

METRIC_COL = {"revenue": "revenue_from_ops_cr", "pat": "pat_cr", "eps": "eps_basic"}


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_store(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[bool, Dict[date, Dict[str, Any]]]]:
    """symbol → consolidated? → period_end → {revenue, pat, eps, known_at, sources}. Several sources per quarter are merged field by
    field, the most recently ingested non-null value first."""
    ordered = sorted(rows, key=lambda r: (r.get("ingested_at") or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    store: Dict[str, Dict[bool, Dict[date, Dict[str, Any]]]] = {}
    for r in ordered:
        pe = r["period_end"]
        cell = store.setdefault(r["symbol"], {}).setdefault(bool(r["consolidated"]), {}).setdefault(
            pe, {"revenue": None, "pat": None, "eps": None, "broadcast_at": None, "sources": []})
        for key, col in METRIC_COL.items():
            if cell[key] is None:
                cell[key] = _num(r.get(col))
        if cell["broadcast_at"] is None and r.get("broadcast_at") is not None:
            cell["broadcast_at"] = r["broadcast_at"]
        if r.get("source") and r["source"] not in cell["sources"]:
            cell["sources"].append(r["source"])
    for by_basis in store.values():
        for by_pe in by_basis.values():
            for pe, cell in by_pe.items():
                cell["known_at"] = known_at(pe, cell["broadcast_at"])
    return store


def needed_quarters(target: date) -> Dict[str, date]:
    return {"y1": shift_quarters(target, -4), "p1": shift_quarters(target, -1), "p2": shift_quarters(target, -2),
            "y2": shift_quarters(target, -5), "y3": shift_quarters(target, -6)}


def _value(by_pe: Dict[date, Dict[str, Any]], pe: date, metric: str, cutoff: Optional[datetime]) -> Optional[float]:
    cell = by_pe.get(pe)
    if cell is None or (cutoff is not None and not cell["known_at"] < cutoff):
        return None
    return cell[metric]


def pick_basis(sym_store: Dict[bool, Dict[date, Dict[str, Any]]], target: date, cutoff: Optional[datetime]) -> Tuple[Optional[bool], int]:
    """Consolidated when its needed quarters are all there, else standalone when those are, else whichever has more of them.
    Returns (consolidated?, how many of the 5 needed quarters that basis has)."""
    need = list(needed_quarters(target).values())
    counts = {}
    for basis, by_pe in sym_store.items():
        counts[basis] = sum(1 for pe in need if _value(by_pe, pe, "pat", cutoff) is not None)
    if not counts:
        return None, 0
    for basis in (True, False):
        if counts.get(basis) == len(need):
            return basis, len(need)
    best = max(counts, key=lambda b: (counts[b], b))
    return best, counts[best]


def forecast_metric(by_pe: Dict[date, Dict[str, Any]], metric: str, target: date,
                    cutoff: Optional[datetime]) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    """({mid, g1, g2, g, base, prev}, None) or (None, reason). `metric` is revenue or pat."""
    nq = needed_quarters(target)
    vals = {k: _value(by_pe, pe, metric, cutoff) for k, pe in nq.items()}
    missing = [k for k, v in vals.items() if v is None]
    if missing:
        have = 5 - len(missing)
        return None, f"only {have} of the 5 earlier quarters the method needs are published for this measure (needs t−1, t−2, t−4, t−5, t−6)"
    if any(v <= 0 for v in vals.values()):
        return None, ("a quarter the method divides by was zero or negative, so a growth rate is not meaningful"
                      if metric == "pat" else "a quarter the method needs reported zero or negative revenue")
    g1 = vals["p1"] / vals["y2"] - 1.0
    g2 = vals["p2"] / vals["y3"] - 1.0
    g = (g1 + g2) / 2.0
    if abs(g) > MAX_GROWTH:
        return None, f"recent growth of {g * 100:.0f} % is beyond ±100 %: a baseline from it would not be meaningful"
    if metric == "pat":
        rev_y1 = _value(by_pe, nq["y1"], "revenue", cutoff)
        if rev_y1 and rev_y1 > 0 and vals["y1"] / rev_y1 < MIN_PAT_MARGIN:
            return None, "last year's profit was under 0.5 % of its revenue: a near-zero base makes growth meaningless"
    return {"mid": vals["y1"] * (1.0 + g), "g1": g1, "g2": g2, "g": g, "base": vals["y1"], "prev": vals["p1"]}, None


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        raise ValueError("empty")
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def run_backtest(store: Dict[str, Dict[bool, Dict[date, Dict[str, Any]]]], metric: str) -> List[Dict[str, Any]]:
    """Every (stock, quarter) the method can be tested on, point-in-time: only quarters known before the tested quarter's own
    filing are used. error_pct = actual ÷ expected − 1, in %."""
    out: List[Dict[str, Any]] = []
    for symbol, sym_store in store.items():
        for basis, by_pe in sym_store.items():
            for target, cell in by_pe.items():
                actual = cell.get(metric)
                if actual is None or actual <= 0:
                    continue
                f, _reason = forecast_metric(by_pe, metric, target, cell["known_at"])
                if f is None or f["mid"] <= 0:
                    continue
                size = by_pe.get(shift_quarters(target, -4), {}).get("revenue")
                out.append({"symbol": symbol, "consolidated": basis, "target": target, "instability": abs(f["g1"] - f["g2"]),
                            "size": size if size and size > 0 else None,
                            "error_pct": (actual / f["mid"] - 1.0) * 100.0,
                            "naive_error_pct": (actual / f["base"] - 1.0) * 100.0})
    # one basis per symbol and quarter: consolidated wins when both exist
    best: Dict[Tuple[str, date], Dict[str, Any]] = {}
    for r in out:
        k = (r["symbol"], r["target"])
        if k not in best or (r["consolidated"] and not best[k]["consolidated"]):
            best[k] = r
    return list(best.values())


def _cuts(vals: Sequence[float], n: int) -> Tuple[float, ...]:
    v = sorted(vals)
    return tuple(_quantile(v, i / n) for i in range(1, n)) if v else ()


def _bucket(cuts: Sequence[float], x: float) -> int:
    for i, c in enumerate(cuts):
        if x <= c:
            return i
    return len(cuts)


class Calibration:
    """Band quantiles for one metric, from a set of backtest errors, by company size and growth stability.

    A forecast is looked up in its (size, stability) cell; a cell with fewer than MIN_BUCKET_N past forecasts falls back to its size
    group, then to its stability group (when the size is unknown), then to every stock pooled."""

    def __init__(self, records: Sequence[Dict[str, Any]], metric: str):
        self.metric, self.n = metric, len(records)
        self.inst_cuts = _cuts([r["instability"] for r in records], INST_BUCKETS)
        self.size_cuts = _cuts([r["size"] for r in records if r.get("size")], SIZE_BUCKETS)
        self.cells: Dict[Tuple[Optional[int], Optional[int]], Tuple[float, float, int]] = {}
        groups: Dict[Tuple[Optional[int], Optional[int]], List[float]] = {}
        for r in records:
            sb = _bucket(self.size_cuts, r["size"]) if r.get("size") and self.size_cuts else None
            ib = _bucket(self.inst_cuts, r["instability"])
            for key in ((sb, ib), (sb, None), (None, ib), (None, None)):
                groups.setdefault(key, []).append(r["error_pct"])
        for key, errs in groups.items():
            if len(errs) >= (MIN_BUCKET_N if key != (None, None) else 1):
                errs = sorted(errs)
                self.cells[key] = (_quantile(errs, BAND_LO_Q), _quantile(errs, BAND_HI_Q), len(errs))
        self.pooled = self.cells.get((None, None))

    def bucket(self, instability: float) -> int:
        return _bucket(self.inst_cuts, instability)

    def band_pct(self, instability: float, size: Optional[float] = None) -> Optional[Tuple[float, float, int, str]]:
        """(low_error_pct, high_error_pct, n, scope) for a stock of this growth stability and size."""
        sb = _bucket(self.size_cuts, size) if size and size > 0 and self.size_cuts else None
        ib = self.bucket(instability)
        order = []
        if sb is not None:
            order += [((sb, ib), "similar size and growth stability"), ((sb, None), "similar size")]
        order += [((None, ib), "similar growth stability"), ((None, None), "all stocks")]
        for key, scope in order:
            if key in self.cells:
                lo, hi, n = self.cells[key]
                return lo, hi, n, scope
        return None

    def band(self, mid: float, instability: float, size: Optional[float] = None) -> Optional[Dict[str, float]]:
        bp = self.band_pct(instability, size)
        if bp is None:
            return None
        half = MIN_HALF_WIDTH.get(self.metric, 0.01)
        lo = min(mid * (1 + bp[0] / 100.0), mid * (1 - half))
        hi = max(mid * (1 + bp[1] / 100.0), mid * (1 + half))
        return {"low": lo, "mid": mid, "high": hi}


def universe_backtest(records: Sequence[Dict[str, Any]], metric: str) -> Dict[str, Any]:
    """How the method did on every stock, point-in-time, and two out-of-sample checks of the band:
      held_out_stocks   the band calibrated on one half of the stocks (by a fixed hash of the symbol), applied to the other half
      latest_quarter    the band calibrated on the earlier tested quarters, applied to the latest tested quarter (small: few stocks
                        have reported the latest quarter yet)
    naive_flat_* is the benchmark 'last year's quarter unchanged', on the same tests: the method must beat it to be worth showing."""
    if not records:
        return {"n": 0}
    abs_err = sorted(abs(r["error_pct"]) for r in records)
    naive = sorted(abs(r["naive_error_pct"]) for r in records)
    full = Calibration(records, metric)
    out: Dict[str, Any] = {"n": len(records), "median_abs_err_pct": round(statistics.median(abs_err), 1),
                           "p90_abs_err_pct": round(_quantile(abs_err, 0.9), 1),
                           "within_10pct_share": round(100.0 * sum(1 for e in abs_err if e <= 10.0) / len(abs_err), 1),
                           "naive_flat_median_abs_err_pct": round(statistics.median(naive), 1),
                           "naive_flat_p90_abs_err_pct": round(_quantile(naive, 0.9), 1),
                           "tested_quarters": sorted({r["target"].isoformat() for r in records})}
    out["in_sample_within_band_pct"] = round(100.0 * sum(1 for r in records if _in_band(full, r)) / len(records), 1)
    even = [r for r in records if zlib.crc32(r["symbol"].encode()) % 2 == 0]
    odd = [r for r in records if zlib.crc32(r["symbol"].encode()) % 2 == 1]
    if len(even) >= 3 * MIN_BUCKET_N and odd:
        cal = Calibration(even, metric)
        out["held_out_stocks"] = {"calibrated_on_n": len(even), "tested_n": len(odd),
                                  "within_band_pct": round(100.0 * sum(1 for r in odd if _in_band(cal, r)) / len(odd), 1)}
    else:
        out["held_out_stocks"] = None
    last = max(r["target"] for r in records)
    train = [r for r in records if r["target"] < last]
    test = [r for r in records if r["target"] == last]
    if len(train) >= 3 * MIN_BUCKET_N and test:
        cal = Calibration(train, metric)
        out["latest_quarter"] = {"calibrated_on": sorted({r["target"].isoformat() for r in train}), "tested_on": last.isoformat(),
                                 "tested_n": len(test), "within_band_pct": round(100.0 * sum(1 for r in test if _in_band(cal, r)) / len(test), 1)}
    else:
        out["latest_quarter"] = None
    # kept for the first contract draft: the headline out-of-sample figure is the stock holdout
    out["within_band_pct"] = out["held_out_stocks"]["within_band_pct"] if out["held_out_stocks"] else None
    out["within_band_n"] = out["held_out_stocks"]["tested_n"] if out["held_out_stocks"] else 0
    return out


def _in_band(cal: Calibration, r: Dict[str, Any]) -> bool:
    bp = cal.band_pct(r["instability"], r.get("size"))
    return bp is not None and bp[0] <= r["error_pct"] <= bp[1]


# ── pure helpers: one stock's answer ──────────────────────────────────────────

def _r(v: Optional[float], dp: int = 1) -> Optional[float]:
    return None if v is None else round(v, dp)


def build_metric(key: str, by_pe: Dict[date, Dict[str, Any]], target: date, cutoff: Optional[datetime], cal: Optional[Calibration],
                 filed_cell: Optional[Dict[str, Any]], pat_pack: Optional[Dict[str, Any]], audit: str = "not recorded") -> Dict[str, Any]:
    unit = "₹ crore" if key in ("revenue", "pat") else "₹ a share"
    nq = needed_quarters(target)
    entry: Dict[str, Any] = {"key": key, "unit": unit, "expected": None, "same_quarter_last_year": _r(_value(by_pe, nq["y1"], key, cutoff), 2),
                             "previous_quarter": _r(_value(by_pe, nq["p1"], key, cutoff), 2), "trend_yoy_pct": None, "filed": None,
                             "vs_mid_pct": None, "within_band": None, "reliable": False, "note": None, "last_year_note": None}
    filed_val = _num(filed_cell.get(key)) if filed_cell else None
    if filed_cell is not None:
        entry["filed"] = {"value": _r(filed_val, 2), "broadcast_at": filed_cell["broadcast_at"].isoformat() if filed_cell.get("broadcast_at") else None,
                          "audit_status": audit}
    if key == "eps":
        # EPS is shown against last year only when the share base is unchanged (bonus / split make the two figures incomparable)
        e_y1, p_y1 = _value(by_pe, nq["y1"], "eps", cutoff), _value(by_pe, nq["y1"], "pat", cutoff)
        e_p1, p_p1 = _value(by_pe, nq["p1"], "eps", cutoff), _value(by_pe, nq["p1"], "pat", cutoff)
        if e_y1 and p_y1 and e_p1 and p_p1 and e_y1 > 0 and p_y1 > 0 and e_p1 > 0 and p_p1 > 0:
            share_ratio = (p_y1 / e_y1) / (p_p1 / e_p1)
            if not (0.8 <= share_ratio <= 1.25):
                entry["same_quarter_last_year"] = None
                entry["last_year_note"] = "last year's EPS is not shown: the share count changed since (bonus or split), so it is not comparable"
        if pat_pack is None or pat_pack.get("expected") is None:
            entry["note"] = "expected EPS follows expected profit, which is not available for this stock"
            return entry
        p1_pat, p1_eps = _value(by_pe, nq["p1"], "pat", cutoff), _value(by_pe, nq["p1"], "eps", cutoff)
        if not p1_pat or p1_pat <= 0 or not p1_eps or p1_eps <= 0:
            entry["note"] = "the latest quarter's profit or EPS is missing or not positive, so the share base cannot be derived"
            return entry
        ratio = p1_eps / p1_pat
        e = pat_pack["expected"]
        entry["expected"] = {"low": _r(e["low"] * ratio, 2), "mid": _r(e["mid"] * ratio, 2), "high": _r(e["high"] * ratio, 2)}
        entry["reliable"] = True
        entry["note"] = "derived: expected profit × (latest quarter's EPS ÷ latest quarter's profit); the share base is held at the latest quarter"
        entry["trend_yoy_pct"] = None
        if filed_val is not None and entry["expected"]["mid"]:
            entry["vs_mid_pct"] = _r((filed_val / entry["expected"]["mid"] - 1.0) * 100.0)
            entry["within_band"] = entry["expected"]["low"] <= filed_val <= entry["expected"]["high"]
        return entry
    f, reason = forecast_metric(by_pe, key, target, cutoff)
    if f is None:
        entry["note"] = reason
        return entry
    entry["trend_yoy_pct"] = _r(f["g"] * 100.0)
    size = _value(by_pe, nq["y1"], "revenue", cutoff)
    band = cal.band(f["mid"], abs(f["g1"] - f["g2"]), size) if cal else None
    if band is None:
        entry["note"] = "no backtest is available to set a band, so no range is shown"
        return entry
    entry["expected"] = {k: _r(v, 1) for k, v in band.items()}
    entry["reliable"] = True
    bp = cal.band_pct(abs(f["g1"] - f["g2"]), size)
    entry["note"] = (f"growth of {f['g1'] * 100:.1f} % and {f['g2'] * 100:.1f} % in the last two quarters, averaged {f['g'] * 100:.1f} %; "
                     f"band from {bp[2]} past forecasts of stocks with {bp[3]}")
    entry["_instability"] = abs(f["g1"] - f["g2"])
    if filed_val is not None and f["mid"]:
        entry["vs_mid_pct"] = _r((filed_val / f["mid"] - 1.0) * 100.0)
        entry["within_band"] = band["low"] <= filed_val <= band["high"]
    return entry


def stock_backtest(records: Sequence[Dict[str, Any]], symbol: str, cal: Optional[Calibration]) -> Dict[str, Any]:
    mine = [r for r in records if r["symbol"] == symbol]
    out: Dict[str, Any] = {"n_quarters": len(mine), "median_abs_err_pct": None, "within_band_pct": None,
                           "note": "a stock has only a few testable quarters, so these figures describe it but do not set its band"}
    if mine:
        out["median_abs_err_pct"] = round(statistics.median(abs(r["error_pct"]) for r in mine), 1)
        if cal:
            hit = sum(1 for r in mine if _in_band(cal, r))
            out["within_band_pct"] = round(100.0 * hit / len(mine), 1)
    return out


EVIDENCE_KINDS = (("analyst", "analyst / investor meet"), ("investor meet", "analyst / investor meet"), ("investor presentation", "investor presentation"),
                  ("press release", "press release"), ("media release", "press release"), ("order", "order"), ("credit rating", "credit rating"),
                  ("acquisition", "acquisition"), ("transcript", "call transcript"), ("outcome of board meeting", "board meeting outcome"))


def evidence_kind(subject: str, classifier_label: Optional[str]) -> str:
    """The kind the filing's own subject names; else the classifier's category label (a label, never a sentiment)."""
    low = (subject or "").lower()
    for needle, kind in EVIDENCE_KINDS:
        if needle in low:
            return kind
    return classifier_label or "other"


def rank_evidence(rows: Sequence[Dict[str, Any]], limit: int = EVIDENCE_LIMIT) -> List[Dict[str, Any]]:
    """Relevant filings first (orders, capex, M&A, rating, analyst meets, press releases…), routine management / board items last;
    newest first within a tier; the same subject filed twice on a day is one row. No sentiment or score is carried."""
    tier1 = {"capex", "orders", "mna", "rating", "buyback", "qip", "dividend", "litigation", "earnings"}
    tier1_sub = ("analyst", "investor", "press release", "media release", "award of order", "receipt of order", "credit rating",
                 "acquisition", "investor presentation", "earnings call", "transcript")
    seen = set()
    scored = []
    for r in rows:
        subject = (r.get("subject") or "").strip()
        filed = r["filed_at"]
        key = (filed.date() if hasattr(filed, "date") else filed, subject.lower())
        if not subject or key in seen:
            continue
        seen.add(key)
        cat = (r.get("event_category") or "").lower()
        sub = ((r.get("subcategory") or "") + " " + subject).lower()
        tier = 0 if cat in tier1 or any(s in sub for s in tier1_sub) else 1 if cat == "management" else 2
        scored.append((tier, filed, r, subject))
    scored.sort(key=lambda t: (t[0], -(t[1].timestamp() if hasattr(t[1], "timestamp") else 0)))
    out = []
    for tier, filed, r, subject in scored:
        if tier == 2:
            continue
        out.append({"date": (filed.date() if hasattr(filed, "date") else filed).isoformat(), "title": subject,
                    "category": evidence_kind(subject, r.get("event_category")), "source": "NSE announcement (nidp.corporate_announcements)",
                    "url": r.get("attachment_url")})
        if len(out) >= limit:
            break
    out.sort(key=lambda e: e["date"], reverse=True)
    return out


# ── store (cached) ────────────────────────────────────────────────────────────

QUARTERS_SQL = """
    SELECT symbol, period_end, consolidated, revenue_from_ops_cr, pat_cr, eps_basic, broadcast_at, source, ingested_at
      FROM nidp.nse_financials_quarterly WHERE period_type = 'quarterly'
"""
EVENT_SQL = """
    SELECT symbol, event_date, period, purpose, intimated_at FROM nidp.event_calendar
     WHERE symbol = $1 AND event_type = 'quarterly_results' AND event_date = $2 ORDER BY intimated_at NULLS LAST LIMIT 1
"""
EVIDENCE_SQL = """
    SELECT filed_at, subject, event_category, subcategory, attachment_url
      FROM nidp.corporate_announcements
     WHERE ticker_symbol = $1 AND source = 'NSE_ANN' AND filed_at > $2 AND filed_at <= $3
     ORDER BY filed_at DESC LIMIT 400
"""

IST = timezone(timedelta(hours=5, minutes=30))
MAX_BATCH_DAYS = 3             # the batch window: from..to inclusive, at most this many days


def _today() -> date:
    """Today in IST (the desk's clock): between 00:00 and 05:30 IST the server's UTC date is still yesterday."""
    return datetime.now(IST).date()


# The exchange subject companies use for the outcome of a results meeting. It is matched exactly: "Clarification - Financial
# Results" and "Reasons for Delayed/Non-submission of Financial Results" are NOT a filed result. A filing on the meeting day
# (IST) is the only evidence we use that a company has reported before its figures reach nidp.nse_financials_quarterly.
FILING_SQL = """
    SELECT ticker_symbol, filed_at, subject, attachment_url
      FROM nidp.corporate_announcements
     WHERE ticker_symbol = ANY($1::text[]) AND source = 'NSE_ANN' AND filed_at >= $2 AND filed_at < $3
       AND lower(btrim(subject)) = 'outcome of board meeting'
     ORDER BY filed_at
"""
BATCH_EVENT_SQL = """
    SELECT DISTINCT ON (symbol, event_date) symbol, company_name, event_date, period, purpose, intimated_at
      FROM nidp.event_calendar
     WHERE event_type = 'quarterly_results' AND event_date BETWEEN $1 AND $2
     ORDER BY symbol, event_date, intimated_at NULLS LAST
"""


def ist_day_window(lo: date, hi: Optional[date] = None) -> Tuple[datetime, datetime]:
    """[00:00 IST of lo, 00:00 IST of the day after hi)."""
    hi = hi or lo
    return (datetime.combine(lo, datetime.min.time(), tzinfo=IST), datetime.combine(hi + timedelta(days=1), datetime.min.time(), tzinfo=IST))


def pick_filing(rows: Sequence[Dict[str, Any]], symbol: str, day: date) -> Optional[Dict[str, Any]]:
    """The earliest 'Outcome of Board Meeting' filing of `symbol` dated `day` in IST, or None."""
    for r in rows:
        fa = r["filed_at"]
        if r["ticker_symbol"] == symbol and fa.astimezone(IST).date() == day:
            return {"filed_at": fa.astimezone(IST).isoformat(), "subject": (r.get("subject") or "").strip(), "url": r.get("attachment_url")}
    return None


_cache: Dict[str, Any] = {"at": 0.0, "value": None}
_lock = asyncio.Lock()


def build_models(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    store = build_store(rows)
    models: Dict[str, Any] = {"store": store, "records": {}, "cal": {}, "universe": {}}
    for metric in ("revenue", "pat"):
        recs = run_backtest(store, metric)
        models["records"][metric] = recs
        models["cal"][metric] = Calibration(recs, metric) if recs else None
        models["universe"][metric] = universe_backtest(recs, metric)
    return models


async def get_models(conn: Any) -> Dict[str, Any]:
    async with _lock:
        if _cache["value"] is not None and time.monotonic() - _cache["at"] < STORE_TTL_S:
            return _cache["value"]
        rows = [dict(r) for r in await conn.fetch(QUARTERS_SQL)]
        _cache["value"] = build_models(rows)
        _cache["at"] = time.monotonic()
        return _cache["value"]


def answer(models: Dict[str, Any], symbol: str, event_date: date, purpose: Optional[str], today: date,
           evidence_rows: Sequence[Dict[str, Any]], intimated_at: Optional[datetime] = None,
           filing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    store, gaps = models["store"], [GAP_CONSENSUS, GAP_NEWS, GAP_RESTATE, GAP_AUDIT]
    target, inferred = parse_period_end(purpose, event_date)
    sym_store = store.get(symbol, {})
    # declared when the target quarter is stored for some basis
    target_cells = {b: by[target] for b, by in sym_store.items() if target in by}
    declared = bool(target_cells) and event_date <= today
    basis_pick, _ = pick_basis(sym_store, target, None)
    filed_cell = None
    cutoff: Optional[datetime]
    if declared:
        order = [basis_pick] if basis_pick in target_cells else list(target_cells)
        filed_cell = target_cells[order[0]]
        basis_pick = order[0]
        cutoff = filed_cell["known_at"]
    else:
        # upcoming: everything broadcast up to the end of today; a passed date with no stored figures: everything before that meeting
        cutoff = (datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc) if event_date >= today
                  else datetime.combine(event_date, datetime.min.time(), tzinfo=timezone.utc))
        basis_pick, _ = pick_basis(sym_store, target, cutoff)
    by_pe = sym_store.get(basis_pick, {}) if basis_pick is not None else {}
    # declared: the figures are stored, or the meeting day has passed, or the meeting is today and the company has filed its
    # outcome (`filing`). A meeting today with no filing yet is still upcoming.
    status = "declared" if (declared or event_date < today or (event_date == today and filing is not None)) else "upcoming"
    if status == "declared" and filed_cell is None:
        if filing is not None:
            gaps.append("the company has filed its board-meeting outcome (exchange filing, " + filing["filed_at"][11:16] + " IST) but the filed figures "
                        "are not in the stored results yet: they arrive from Trendlyne / Screener, usually a day or two after the filing")
        else:
            gaps.append("the meeting date has passed but the filed figures are not in the stored results yet")
    if inferred:
        gaps.append("the reporting quarter was not stated in the calendar entry; it is taken as the last quarter end before the meeting")
    metrics: List[Dict[str, Any]] = []
    cal_rev, cal_pat = models["cal"].get("revenue"), models["cal"].get("pat")
    audit, audit_basis = audit_from_notice(purpose)
    pat_entry = build_metric("pat", by_pe, target, cutoff, cal_pat, filed_cell, None, audit)
    rev_entry = build_metric("revenue", by_pe, target, cutoff, cal_rev, filed_cell, None, audit)
    eps_entry = build_metric("eps", by_pe, target, cutoff, None, filed_cell, pat_entry, audit)
    for e in (rev_entry, pat_entry, eps_entry):
        e.pop("_instability", None)
        metrics.append(e)
    if not sym_store:
        gaps.append("no published quarterly results are stored for this symbol")
    quarters_used = sum(1 for pe in by_pe if pe < target and (cutoff is None or by_pe[pe]["known_at"] < cutoff))
    sources = sorted({s for pe in by_pe.values() for s in pe["sources"]})
    return {
        "symbol": symbol, "event_date": event_date.isoformat(), "period_end": target.isoformat(), "period_label": period_label(target),
        "basis": None if basis_pick is None else ("consolidated" if basis_pick else "standalone"), "status": status,
        "intimated_at": intimated_at.isoformat() if intimated_at else None,
        "filed_state": "figures" if filed_cell is not None else ("pending" if status == "declared" else None), "filing": filing,
        "audit_status": audit, "audit_basis": audit_basis, "label": ONLY_BASELINE,
        "compared_with": "vs Nivesh baseline, not vs consensus" if filed_cell is not None else None,
        "expected_as_of": cutoff.isoformat() if cutoff else None,
        "metrics": metrics,
        "method": {"name": METHOD_NAME, "formula": METHOD_FORMULA, "n_quarters": quarters_used,
                   "backtest": stock_backtest(models["records"].get("pat", []), symbol, cal_pat),
                   "universe_backtest": models["universe"].get("pat", {"n": 0}),
                   "by_metric": {"revenue": models["universe"].get("revenue", {"n": 0}), "pat": models["universe"].get("pat", {"n": 0})}},
        "sources": {"quarters": SOURCES["quarters"] + (f" · rows from {', '.join(sources)}" if sources else ""), "calendar": SOURCES["calendar"],
                    "announcements": SOURCES["announcements"]},
        "evidence": rank_evidence(evidence_rows), "gaps": gaps,
    }


# ── route ─────────────────────────────────────────────────────────────────────

@router.get("/events-calendar/expectation", summary="Expectation for one results meeting from the company's published quarters")
async def results_expectation(
    symbol: str = Query(..., min_length=1, max_length=20),
    date_: str = Query(..., alias="date", description="YYYY-MM-DD, the results meeting's date"),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol)
    if not DATE_PARAM_RE.match(date_ or ""):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    try:
        event_date = date.fromisoformat(date_)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    pool = await get_pool()
    async with pool.acquire() as conn:
        ev = await conn.fetchrow(EVENT_SQL, sym, event_date)
        if ev is None:
            raise HTTPException(status_code=404, detail="no results meeting for this symbol on that date")
        models = await get_models(conn)
        ev = dict(ev)
        today = _today()
        target, _ = parse_period_end(ev.get("purpose"), event_date)
        # upcoming: filings up to the end of today. Declared (or date passed): filings BEFORE the meeting day, so the result's own
        # filings (outcome of the board meeting, results press release) are not shown as if they were evidence for it.
        ist = timezone(timedelta(hours=5, minutes=30))
        cutoff_hi = (datetime.combine(event_date, datetime.min.time(), tzinfo=ist) if event_date <= today
                     else datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc))
        ev_rows = [dict(r) for r in await conn.fetch(EVIDENCE_SQL, sym, cutoff_hi - timedelta(days=EVIDENCE_DAYS), cutoff_hi)]
        filing = None
        if event_date == today:
            filing = pick_filing([dict(r) for r in await conn.fetch(FILING_SQL, [sym], *ist_day_window(event_date))], sym, event_date)
    return jsonify(answer(models, sym, event_date, ev.get("purpose"), today, ev_rows, ev.get("intimated_at"), filing))


# ── batch: the desk's "results today & tomorrow" board ─────────────────────────

STATE_ORDER = {"figures": 0, "pending": 1, None: 2}
GAP_LAG = ("filed figures reach the stored results from Trendlyne / Screener, usually a day or two after the filing: a company that "
           "has reported today may show 'filed result not loaded yet'")
EVENT_GAP_SHARED = {GAP_CONSENSUS, GAP_NEWS, GAP_RESTATE, GAP_AUDIT}


def compact_event(a: Dict[str, Any], ev: Dict[str, Any], name: Optional[str], sector: Optional[str], universe: Dict[str, Optional[bool]]) -> Dict[str, Any]:
    """One results meeting as the board needs it: no evidence list, no per-stock method block (those are on the single endpoint)."""
    keep = ("key", "unit", "expected", "same_quarter_last_year", "previous_quarter", "trend_yoy_pct", "filed", "vs_mid_pct", "within_band",
            "reliable", "note", "last_year_note")
    return {
        "id": event_id(ev["event_date"], ev["symbol"], "RESULTS", None), "symbol": ev["symbol"], "name": name, "sector": sector,
        "event_date": ev["event_date"].isoformat(), "status": a["status"], "filed_state": a["filed_state"], "filing": a["filing"],
        "period_label": a["period_label"], "basis": a["basis"], "audit_status": a["audit_status"], "audit_basis": a["audit_basis"],
        "compared_with": a["compared_with"], "expected_as_of": a["expected_as_of"], "universe": universe,
        "metrics": [{k: m.get(k) for k in keep} for m in a["metrics"]],
        "gaps": [g for g in a["gaps"] if g not in EVENT_GAP_SHARED],
    }


@router.get("/events-calendar/expectations", summary="Expectation and filed result for every results meeting in a window of at most 3 days")
async def results_expectations(
    from_: str = Query(..., alias="from", description="YYYY-MM-DD"),
    to: str = Query(..., description="YYYY-MM-DD"),
    universe: str = Query("fno", description="fno | n50 | all"),
) -> Dict[str, Any]:
    if universe not in UNIVERSES:
        raise HTTPException(status_code=400, detail="universe must be fno, n50 or all")
    if not (DATE_PARAM_RE.match(from_ or "") and DATE_PARAM_RE.match(to or "")):
        raise HTTPException(status_code=400, detail="from and to must be YYYY-MM-DD")
    try:
        lo, hi = date.fromisoformat(from_), date.fromisoformat(to)
    except ValueError:
        raise HTTPException(status_code=400, detail="from and to must be YYYY-MM-DD")
    if hi < lo:
        raise HTTPException(status_code=400, detail="from must not be after to")
    if (hi - lo).days + 1 > MAX_BATCH_DAYS:
        raise HTTPException(status_code=400, detail=f"the window is at most {MAX_BATCH_DAYS} days")
    today = _today()
    pool = await get_pool()
    async with pool.acquire() as conn:
        cal = [dict(r) for r in await conn.fetch(BATCH_EVENT_SQL, lo, hi)]
        n50 = {r["symbol"] for r in await conn.fetch(N50_SQL)}
        fno = {r["symbol"] for r in await conn.fetch(FNO_SQL) if r["fno_eligible"]}
        cal = [r for r in cal if universe == "all" or (universe == "n50" and r["symbol"] in n50) or (universe == "fno" and r["symbol"] in fno)]
        symbols = sorted({r["symbol"] for r in cal})
        ind = {r["symbol"]: r for r in await conn.fetch(INDUSTRY_SQL, symbols)} if symbols else {}
        models = await get_models(conn)
        filings: List[Dict[str, Any]] = []
        today_syms = sorted({r["symbol"] for r in cal if r["event_date"] == today})
        if today_syms:
            filings = [dict(r) for r in await conn.fetch(FILING_SQL, today_syms, *ist_day_window(today))]
    out: List[Dict[str, Any]] = []
    for r in cal:
        sym, d = r["symbol"], r["event_date"]
        filing = pick_filing(filings, sym, d) if d == today else None
        a = answer(models, sym, d, r.get("purpose"), today, [], r.get("intimated_at"), filing)
        i = ind.get(sym)
        uni = {"n50": (sym in n50) if n50 else None, "fno": (sym in fno) if fno else None}
        out.append(compact_event(a, r, r.get("company_name") or (i["company_name"] if i else None), i["industry"] if i else None, uni))
    out.sort(key=lambda e: (STATE_ORDER[e["filed_state"]], e["event_date"], e["symbol"]))
    counts = {"declared_figures": sum(1 for e in out if e["filed_state"] == "figures"),
              "declared_pending": sum(1 for e in out if e["filed_state"] == "pending"),
              "upcoming": sum(1 for e in out if e["status"] == "upcoming")}
    gaps = [GAP_CONSENSUS, GAP_NEWS, GAP_RESTATE, GAP_AUDIT, GAP_LAG]
    if not fno:
        gaps.append("the F&O master has no eligible symbols, so the F&O filter returns nothing")
    return jsonify({
        "from": lo.isoformat(), "to": hi.isoformat(), "universe": universe, "as_of": today.isoformat(), "count": len(out), "counts": counts,
        "label": ONLY_BASELINE, "events": out,
        "method": {"name": METHOD_NAME, "formula": METHOD_FORMULA,
                   "by_metric": {"revenue": models["universe"].get("revenue", {"n": 0}), "pat": models["universe"].get("pat", {"n": 0})}},
        "sources": {"quarters": SOURCES["quarters"], "calendar": SOURCES["calendar"], "announcements": SOURCES["announcements"]},
        "gaps": gaps,
    })
