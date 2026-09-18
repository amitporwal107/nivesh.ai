"""Move odds profile — each stock's quality beside its move odds (PRD "stock analysis rankings": movement probability
is not investment quality, so the two are shown side by side and never combined).

Pure functions only (grades, the ratio catalogue, event categories); the route that reads the database lives in
routers/move_odds.py. Every value served comes straight from an NIDP table, except two things computed here from real
rows and stated as such on the page:

  * the sector rating — the median V3 quality score of the sector's stocks whose score has at least 80% of its inputs;
  * the 1-year return — adjusted close 252 sessions apart. The stored stock_features_daily.return_252d_pct matches
    neither the raw nor the adjusted 252-session change (2026-09-16: TATACHEM stored +3.2%, computed −22.6%), so it is
    not served.

A missing value is null, never 0. A ratio is offered only when the universe actually has it (the metric-registry rule:
non-null for at least 5% of stocks and more than one distinct value); the rest are listed with the reason.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence

GRADE_A = 70.0
GRADE_B = 50.0
COVERAGE_MIN = 80.0            # below this share of inputs a V3 score is marked partial and left out of sector medians
MIN_COVERAGE_PCT = 5.0         # a ratio is offered only if at least this share of the universe has it …
MIN_DISTINCT = 2               # … and it takes more than one value (177 readings of exactly 0.00 is not a ratio)

CAP_LABEL = {"LARGE_CAP": "Large", "MID_CAP": "Mid", "SMALL_CAP": "Small", "MICRO_CAP": "Micro"}


def grade(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    return "A" if score >= GRADE_A else ("B" if score >= GRADE_B else "C")


def cap_label(bucket: Optional[str]) -> Optional[str]:
    return CAP_LABEL.get((bucket or "").upper()) if bucket else None


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None          # NaN → None


def quality_block(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The V3 composite for one stock, or None when there is no score (never a default)."""
    if not row:
        return None
    score = _f(row.get("quality_score"))
    if score is None:
        return None
    cov = _f(row.get("quality_coverage_pct"))
    shown = round(score, 1)                                   # graded on the number shown beside it
    return {
        "score": shown, "grade": grade(shown), "coverage": round(cov, 1) if cov is not None else None,
        "partial": cov is None or cov < COVERAGE_MIN,
        "fundamental": _r1(_f(row.get("fundamental_score"))), "technical": _r1(_f(row.get("technical_score"))),
        "as_of": _iso(row.get("as_of_date")),
    }


def sector_ratings(scores: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Median quality score per sector over stocks whose score has >= COVERAGE_MIN of its inputs, with the count.
    A sector with no such stock gets median None and grade None."""
    by: Dict[str, List[float]] = {}
    scored: Dict[str, int] = {}
    for r in scores:
        sec = r.get("sector")
        s = _f(r.get("quality_score"))
        if not sec or s is None:
            continue
        scored[sec] = scored.get(sec, 0) + 1
        cov = _f(r.get("quality_coverage_pct"))
        if cov is not None and cov >= COVERAGE_MIN:
            by.setdefault(sec, []).append(s)
    out = {}
    for sec, n_scored in scored.items():
        vals = by.get(sec, [])
        m = round(median(vals), 1) if vals else None
        out[sec] = {"median": m, "grade": grade(m), "n": len(vals), "n_scored": n_scored}
    return out


# ── Ratio catalogue ─────────────────────────────────────────────────────────────────────────────────────────────────
# Groups and the recent / preceding / historical columns follow the owner's design (a Screener-style picker). Only the
# `source` keys below are read; everything else in the design's list is shown as not available with its reason.
@dataclass(frozen=True)
class Ratio:
    key: str
    label: str
    group: str
    column: str                  # recent | preceding | historical
    unit: str                    # cr | pct | x | rs | pts
    source: Optional[str] = None  # column on the features row (or "return_1y", computed); None = not served
    note: Optional[str] = None
    reason: Optional[str] = None  # why it is not served, when source is None


_NOT_YET = "Held in NIDP but not served on this page yet"
_NOT_COMPUTED = "Not computed in NIDP"
_HISTORY = "Needs 3–5 years of filings; NIDP does not compute it"
_PRICE_DEPTH = "Price history on record is under 3 years"
_ZERO_NOTE = "A reading of 0 can mean none or no data; the two are not told apart"

CATALOGUE: List[Ratio] = [
    Ratio("sales_ttm", "Sales (TTM)", "Most Used", "recent", "cr", reason=_NOT_YET),
    Ratio("opm", "Operating margin (OPM)", "Most Used", "recent", "pct", "operating_margin_pct"),
    Ratio("pat_ttm", "Profit after tax (TTM)", "Most Used", "recent", "cr", reason=_NOT_YET),
    Ratio("mcap", "Market capitalisation", "Most Used", "recent", "cr", "market_cap_cr"),
    Ratio("sales_q", "Sales latest quarter", "Quarter P&L", "recent", "cr", reason=_NOT_YET),
    Ratio("pat_q", "Profit after tax latest quarter", "Quarter P&L", "recent", "cr", reason=_NOT_YET),
    Ratio("sales_q_yoy", "YoY quarterly sales growth", "Quarter P&L", "recent", "pct", reason=_NOT_YET),
    Ratio("pat_q_yoy", "YoY quarterly profit growth", "Quarter P&L", "recent", "pct", reason=_NOT_YET),
    Ratio("pe", "Price to earnings", "Ratios", "recent", "x", "pe_ttm"),
    Ratio("divy", "Dividend yield", "Ratios", "recent", "pct", "dividend_yield_pct", note=_ZERO_NOTE),
    Ratio("pbv", "Price to book value", "Ratios", "recent", "x", "pb"),
    Ratio("roce", "Return on capital employed", "Ratios", "recent", "pct", "roce_pct"),
    Ratio("roe", "Return on equity", "Ratios", "recent", "pct", "roe_pct"),
    Ratio("npm", "Net profit margin", "Ratios", "recent", "pct", "profit_margin_pct"),
    Ratio("evebitda", "EV / EBITDA", "Ratios", "recent", "x", "ev_ebitda"),
    Ratio("ev", "Enterprise value", "Ratios", "recent", "cr", "enterprise_value_cr"),
    Ratio("roa", "Return on assets", "Ratios", "recent", "pct", reason=_NOT_COMPUTED),
    Ratio("ey", "Earnings yield", "Ratios", "recent", "pct", reason=_NOT_COMPUTED),
    Ratio("indpe", "Industry P/E", "Ratios", "recent", "x", reason="Not computed in NIDP (the sector median P/E column is empty)"),
    Ratio("ps", "Price to sales", "Ratios", "recent", "x", reason=_NOT_COMPUTED),
    Ratio("icr", "Interest coverage", "Ratios", "preceding", "x", "interest_coverage"),
    Ratio("peg", "PEG ratio", "Ratios", "preceding", "x", reason=_NOT_COMPUTED),
    Ratio("de", "Debt to equity", "Balance Sheet", "recent", "x", "debt_to_equity"),
    Ratio("debt", "Debt", "Balance Sheet", "recent", "cr", reason=_NOT_YET),
    Ratio("prom", "Promoter holding", "Balance Sheet", "recent", "pct", "promoter_pct"),
    Ratio("dprom", "Change in promoter holding (QoQ)", "Balance Sheet", "recent", "pts", "promoter_pct_change_qoq"),
    Ratio("pledge", "Pledged percentage", "Balance Sheet", "recent", "pct", "promoter_pledged_pct", note=_ZERO_NOTE),
    Ratio("cr", "Current ratio", "Balance Sheet", "preceding", "x", "current_ratio"),
    Ratio("eps", "EPS (TTM)", "Annual P&L", "recent", "rs", reason=_NOT_YET),
    Ratio("sg", "Sales growth (TTM, YoY)", "Annual P&L", "preceding", "pct", "revenue_growth_yoy_pct"),
    Ratio("pg", "Profit growth (TTM, YoY)", "Annual P&L", "preceding", "pct", "pat_growth_yoy_pct"),
    Ratio("epsg", "EPS growth (TTM, YoY)", "Annual P&L", "preceding", "pct", "eps_growth_yoy_pct"),
    Ratio("sg3", "Sales growth 3 years", "Annual P&L", "historical", "pct", reason=_HISTORY),
    Ratio("sg5", "Sales growth 5 years", "Annual P&L", "historical", "pct", reason=_HISTORY),
    Ratio("pg3", "Profit growth 3 years", "Annual P&L", "historical", "pct", reason=_HISTORY),
    Ratio("pg5", "Profit growth 5 years", "Annual P&L", "historical", "pct", reason=_HISTORY),
    Ratio("aroe3", "Average return on equity 3 years", "Annual P&L", "historical", "pct", reason=_HISTORY),
    Ratio("cfopat", "Cash from operations / profit", "Cash Flow", "recent", "x", "cfo_pat_ratio"),
    Ratio("pfcf", "Price to free cash flow", "Cash Flow", "recent", "x", reason=_NOT_COMPUTED),
    Ratio("close", "Close", "Price", "recent", "rs", "close"),
    Ratio("r1m", "Return over 1 month (20 sessions)", "Price", "historical", "pct", "return_20d_pct"),
    Ratio("r3m", "Return over 3 months (60 sessions)", "Price", "historical", "pct", "return_60d_pct"),
    Ratio("r1y", "Return over 1 year (252 sessions, adjusted)", "Price", "historical", "pct", "return_1y",
          note="Adjusted closes 252 sessions apart; adjusted for the corporate actions on record"),
    Ratio("r3y", "Return over 3 years", "Price", "historical", "pct", reason=_PRICE_DEPTH),
]
FEATURE_COLUMNS: List[str] = sorted({r.source for r in CATALOGUE if r.source and r.source != "return_1y"})
GROUPS = ["Most Used", "Annual P&L", "Quarter P&L", "Balance Sheet", "Cash Flow", "Ratios", "Price", "User Ratios"]


def measure(values: Sequence[Optional[float]], universe: int) -> Dict[str, Any]:
    nn = [v for v in values if v is not None]
    pct = (100.0 * len(nn) / universe) if universe else 0.0
    return {"n": len(nn), "covered_pct": round(pct, 1), "distinct": len(set(nn))}


def offered(m: Dict[str, Any]) -> bool:
    return m["covered_pct"] >= MIN_COVERAGE_PCT and m["distinct"] >= MIN_DISTINCT


def build_catalogue(values_by_key: Dict[str, List[Optional[float]]], universe: int) -> tuple[List[Dict[str, Any]], List[str]]:
    """(catalogue payload, keys of the offered ratios in catalogue order). values_by_key holds one list per served key,
    aligned to the universe; unserved keys are absent."""
    cat, keys = [], []
    for r in CATALOGUE:
        entry = {"key": r.key, "label": r.label, "group": r.group, "column": r.column, "unit": r.unit, "note": r.note}
        if r.source is None:
            entry.update(available=False, n=0, reason=r.reason)
        else:
            m = measure(values_by_key.get(r.key, []), universe)
            ok = offered(m)
            entry.update(available=ok, n=m["n"], covered_pct=m["covered_pct"],
                         reason=None if ok else ("Every reading is identical" if m["distinct"] == 1 else
                                                 f"Only {m['covered_pct']:.1f}% of these stocks have it (needs {MIN_COVERAGE_PCT:.0f}%)"))
            if ok:
                keys.append(r.key)
        cat.append(entry)
    return cat, keys


# ── Events → categories ─────────────────────────────────────────────────────────────────────────────────────────────
# The published events carry the catalyst engine's (type, subtype). They are mapped onto the announcement classifier's
# category names (metric_registry.EVENT_CATEGORIES) so the page offers one vocabulary. "qip" is shown as "Fund raise":
# fund_raise also covers rights and preferential issues, so calling all of it QIP would be wrong.
EVENT_LABELS: Dict[str, str] = {
    "management": "Management", "dividend": "Dividend", "qip": "Fund raise", "mna": "M&A", "rating": "Rating",
    "orders": "Orders", "earnings": "Earnings", "litigation": "Litigation", "capex": "Capex", "buyback": "Buyback",
    "regulatory": "Regulatory", "other": "Other",
}
_MANAGEMENT = {"director_change", "resignation", "management_change", "appointment"}
_CORP_MNA = {"acquisition", "divestment", "restructuring", "merger", "demerger", "stake_sale"}


def event_category(event_type: Optional[str], subtype: Optional[str]) -> str:
    t, s = (event_type or "").upper(), (subtype or "").lower()
    if t == "RESULTS":
        return "earnings"
    if t == "CAPITAL":
        return {"dividend": "dividend", "buyback": "buyback", "fund_raise": "qip"}.get(s, "other")
    if t == "M&A":
        return "mna"
    if t == "CORPORATE":
        if s in _MANAGEMENT:
            return "management"
        if s in _CORP_MNA:
            return "mna"
        if s in {"capacity", "expansion", "capex"}:
            return "capex"
        return "other"
    if t == "FINANCIAL":
        return "rating" if s.startswith("rating") else "other"
    if t == "CONTRACT":
        return "orders"
    if t == "GOVERNMENT":
        return "orders" if s in {"tender", "procurement", "project"} else "regulatory"
    if t == "INSTITUTION":
        return "management" if s == "appointment" else "other"
    if t == "LEGAL":
        return "litigation"
    if t in {"REGULATORY", "PHARMA"}:
        return "regulatory"
    return "other"


def events_block(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Count, material count (classified positive, negative or mixed), the latest time, and categories by count."""
    n = material = 0
    latest = None
    counts: Dict[str, int] = {}
    for e in events:
        n += 1
        if (e.get("direction") or "").lower() in {"positive", "negative", "mixed"}:
            material += 1
        t = e.get("event_time")
        if t is not None and (latest is None or t > latest):
            latest = t
        c = event_category(e.get("event_type"), e.get("event_subtype"))
        counts[c] = counts.get(c, 0) + 1
    cats = sorted(counts, key=lambda c: (-counts[c], list(EVENT_LABELS).index(c)))
    return {"n": n, "material": material, "latest": _iso(latest), "categories": cats}


def _r1(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 1)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v
