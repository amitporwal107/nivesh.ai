"""The Research Copilot's Wave-1 visual answers (owner 2 Nov 2026; docs/research_copilot/RESEARCH_COPILOT_REQUIREMENTS.md).

    financial_trend   revenue, EBITDA, PAT and margins over the last quarters and fiscal years (category 2)
    valuation_view    P/E and P/B now, against the sector label's median and the stock's own stored P/E history (category 6)
    ownership_trend   promoter / FII / DII / MF holding over quarters, pledge, the fund houses behind the latest month (category 8)
    peer_compare      the named companies, or one company and its sector peers, on growth, margins, returns, valuation (7)
    company_risks     fixed, stated checks on debt, interest cover, liquidity, cash flow vs profit, receivables, working capital,
                      pledge and margins; what cannot be checked is listed (categories 13, 3 and the runnable half of 14)

Every figure is read through the data platform (research_readers.py) and carries its source and date. Nothing is estimated: a
figure the data does not have is "not in our data", and a gap is named in a notice. Filed statements are dated by the period they
cover (Sources.filed), so a September quarter filed in October never reads as stale price data. Wording is evidence only (SEBI,
section 7 of the requirement): no buy / sell / target / rating, no "cheap" or "expensive" verdict; a check's flag is a prompt to
read further, with its rule printed beside it. The stock analyst explains the card; it never sees a number the card does not show.
"""
from __future__ import annotations

import asyncio
import statistics
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import research_readers as rr
from .intents import Intent
from .payload import MINUS, Sources, assemble, block, day_text, follow, iso_day, notice, num, why

SRC_FIN_Q = "Quarterly results (nidp.nse_financials_quarterly)"
SRC_FIN_A = "Annual results (nidp.nse_financials_quarterly, annual rows)"
SRC_CF = "Cash-flow statements (nidp.nse_financials_cashflow)"
SRC_SHP = "Shareholding pattern (nidp.shareholding_pattern)"
SRC_FEAT = "Stock features (nidp.stock_features_daily)"
SRC_PE = "Daily P/E history (nidp.stock_features_daily)"
SRC_AMC = "Mutual-fund holdings by fund house (nidp.mf_holdings_deltas)"
SRC_UNIV = "Sector map (nidp.stock_features_daily sector label; nidp.index_constituents industry)"

# Filing cadence: how long after a period's end the next period's filing is due, plus a margin. Older than this, a newer
# filing may exist that is not in our data, and the answer says so.
QUARTER_MAX_AGE = 150         # results are due 45-60 days after a quarter; the next quarter ends 90 days later
SHAREHOLDING_MAX_AGE = 120    # the pattern is due 21 days after the quarter
ANNUAL_MAX_AGE = 430          # fiscal-year results: due within 60 days of the year end
CASHFLOW_MAX_AGE = 545        # the cash-flow statement comes with the annual report, up to six months after the year end

QUARTERS_SHOWN = 8            # the default window; a question can ask for up to 12 quarters / 10 years
YEARS_SHOWN = 6
MAX_QUARTERS_SHOWN = 12
MAX_YEARS_SHOWN = 10
PEERS_SHOWN = 8
CAVEAT = ("Evidence for your own research, from filed statements and the platform's end-of-day data. It is not investment "
          "advice and carries no rating.")
PROVIDERS = {"screener_in": "screener.in", "screener_in_annual": "screener.in", "trendlyne_mcp": "Trendlyne", "truedata": "TrueData",
             "NSE_SHP": "NSE filing", "nse_xbrl": "NSE filing", "NSE": "NSE filing"}
LENDER_SECTORS = {"banking", "banking and finance", "finance", "financial services", "bank", "banks", "nbfc"}


# ── formatting (every value already read; nothing here makes a number) ──────────────────────────────────────────────

def _indian(n: float) -> str:
    """7,68,844 — Indian digit grouping for rupee crore figures."""
    s = f"{abs(int(round(n))):d}"
    if len(s) > 3:
        head, tail, groups = s[:-3], s[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups + [tail])
    return (MINUS if n < 0 and round(n) != 0 else "") + s


def _cr(v: Any) -> Optional[str]:
    """'₹73,188 Cr', '−₹80 Cr' (the sign before the rupee)."""
    f = num(v)
    return None if f is None else (MINUS if f < 0 and round(f) != 0 else "") + f"₹{_indian(abs(f))} Cr"


def _cr_cell(v: Any) -> Optional[str]:
    f = num(v)
    return None if f is None else _indian(f)


def _lvl(v: Any, digits: int = 1) -> Optional[str]:
    """A level in percent, unsigned unless negative: '25.7%'."""
    f = num(v)
    return None if f is None else (MINUS if f < 0 else "") + f"{abs(f):.{digits}f}%"


def _signed(v: Any, digits: int = 1, unit: str = "%") -> Optional[str]:
    f = num(v)
    if f is None:
        return None
    return ("+" if f > 0 else MINUS if f < 0 else "±") + f"{abs(f):.{digits}f}{unit}"


def _pp(v: Any) -> Optional[str]:
    return _signed(v, 2, " pp")


def _times(v: Any, digits: int = 1) -> Optional[str]:
    f = num(v)
    return None if f is None else (MINUS if f < 0 else "") + f"{abs(f):.{digits}f}×"


def _whole(v: float) -> str:
    return (MINUS if round(v) < 0 else "") + f"{abs(round(v)):d}"


def _r(v: Any, digits: int = 2) -> Optional[float]:
    f = num(v)
    return None if f is None else round(f, digits)


def _q_label(d: Any) -> str:
    x = date.fromisoformat(iso_day(d))
    return f"{x.strftime('%b')} {x.strftime('%y')}"


def _fy_label(d: Any) -> str:
    x = date.fromisoformat(iso_day(d))
    return f"FY{x.strftime('%y')}" if x.month == 3 else f"Year to {x.strftime('%b')} {x.year}"


def _provider(raw: Any) -> str:
    return PROVIDERS.get(str(raw), str(raw)) if raw else "not stated"


def _growth(a: Any, b: Any) -> Optional[float]:
    """Percent change from b to a; None unless both exist and the base is positive (a change from a loss is not a growth rate)."""
    fa, fb = num(a), num(b)
    if fa is None or fb is None or fb <= 0:
        return None
    return round((fa / fb - 1.0) * 100.0, 2)


def _ratio(a: Any, b: Any) -> Optional[float]:
    fa, fb = num(a), num(b)
    if fa is None or fb is None or fb == 0:
        return None
    return fa / fb


def _days_between(a: Any, b: Any) -> int:
    return (date.fromisoformat(iso_day(a)) - date.fromisoformat(iso_day(b))).days


async def _try(coro):
    try:
        return await coro, None
    except Exception as e:  # noqa: BLE001 — a failed read is recorded as a missing source, never raised into the answer
        return None, e


def _lead(intent: Intent) -> List[Dict[str, Any]]:
    if intent.symbol_from_thread:
        return [notice(f"You did not name a company, so this is about {intent.symbol}, the last stock in this conversation.",
                       "info", "thread")]
    return []


def _finish(p: Dict[str, Any], as_of: Optional[str]) -> Dict[str, Any]:
    p["caveat"] = (f"Data up to {day_text(as_of)}. " if as_of else "") + CAVEAT
    return p


def _newest(*days: Any) -> Optional[str]:
    ds = sorted(d for d in (iso_day(x) for x in days if x) if d)
    return ds[-1] if ds else None


def _is_lender(feat: Optional[Dict[str, Any]], rows: Sequence[Dict[str, Any]] = ()) -> bool:
    """Banks and other lenders: EBITDA, debt to equity, current ratio and working capital do not describe them."""
    for key in ("sector", "industry"):
        v = str((feat or {}).get(key) or "").strip().lower()
        if v in LENDER_SECTORS or "bank" in v:
            return True
    return any(num(r.get("interest_earned_cr")) is not None for r in rows)


# ── statements: one basis, one row per period ────────────────────────────────────────────────────────────────────────

def _series(rows: Optional[List[Dict[str, Any]]], kind: str) -> Tuple[List[Dict[str, Any]], Optional[bool]]:
    """(rows newest first, consolidated?) — one basis for the whole series: consolidated when the newest period has a
    consolidated row, else standalone. Mixing the two would read as a jump that is only a change of basis."""
    rows = [r for r in rows or [] if str(r.get("period_type") or "").lower() == kind and iso_day(r.get("period_end"))]
    if not rows:
        return [], None
    newest = max(iso_day(r["period_end"]) for r in rows)
    basis = any(bool(r.get("consolidated")) for r in rows if iso_day(r["period_end"]) == newest)
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: iso_day(r["period_end"]), reverse=True):
        d = iso_day(r["period_end"])
        if bool(r.get("consolidated")) != basis or d in seen:
            continue
        seen.add(d)
        out.append(r)
    return out, basis


def _year_ago(rows: List[Dict[str, Any]], r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((x for x in rows if 350 <= _days_between(r["period_end"], x["period_end"]) <= 380), None)


def _prev_q(rows: List[Dict[str, Any]], r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((x for x in rows if 80 <= _days_between(r["period_end"], x["period_end"]) <= 100), None)


def _margin(r: Optional[Dict[str, Any]], key: str) -> Optional[float]:
    if not r:
        return None
    v, rev = num(r.get(key)), num(r.get("revenue_from_ops_cr"))
    return round(v / rev * 100.0, 2) if v is not None and rev and rev > 0 else None


def _ttm(rows: List[Dict[str, Any]], end: Any, key: str) -> Optional[float]:
    """The sum of the four quarters ending at `end`; None unless all four are in the data."""
    picked = [x for x in rows if 0 <= _days_between(end, x["period_end"]) <= 300]
    vals = [num(x.get(key)) for x in picked]
    if len(picked) != 4 or any(v is None for v in vals):
        return None
    return float(sum(vals))


def _rev12(qs: List[Dict[str, Any]], ys: List[Dict[str, Any]], end1: Any, end0: Any) -> Tuple[Optional[float], Optional[float]]:
    """Revenue for the twelve months to two balance-sheet dates, on ONE basis for both (a sum of quarters and a filed fiscal year
    are never mixed in one growth rate): the four quarters ending at each date, else the fiscal years ending there, else none."""
    t1, t0 = _ttm(qs, end1, "revenue_from_ops_cr"), _ttm(qs, end0, "revenue_from_ops_cr")
    if t1 is not None and t0 is not None:
        return t1, t0

    def fy(end: Any) -> Optional[float]:
        y = next((y for y in ys if iso_day(y["period_end"]) == iso_day(end)), None)
        return num((y or {}).get("revenue_from_ops_cr"))
    f1, f0 = fy(end1), fy(end0)
    return (f1, f0) if f1 is not None and f0 is not None else (None, None)


def _filed_note(r: Dict[str, Any], basis: Optional[bool]) -> str:
    bits = ["consolidated" if basis else "standalone"]
    if iso_day(r.get("broadcast_at")):
        bits.append(f"filed {day_text(r['broadcast_at'])}")
    return ", ".join(bits)


# ═════ financial_trend ═══════════════════════════════════════════════════════════════════════════════════════════════

async def financial_trend(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    sym = intent.symbol
    want_q = int(intent.params.get("quarters") or QUARTERS_SHOWN)
    want_y = int(intent.params.get("years") or YEARS_SHOWN)
    follow_ups = follow(f"What is the valuation of {sym}?", f"What are the biggest risks for {sym}?",
                        f"Compare {sym} with its peers", f"How were {sym} results?")
    title = f"{sym} · Financial trend"
    (q, e_q), (a, e_a), (feat, e_f) = await asyncio.gather(
        _try(rr.financials(sym, "quarterly", 40)), _try(rr.financials(sym, "annual", 20)), _try(rr.features_latest(sym)))
    blocks = _lead(intent)
    qs, qbasis = _series(q, "quarterly")
    ys, ybasis = _series(a, "annual")
    lender = _is_lender(feat, qs)
    if e_q is not None:
        src.miss(SRC_FIN_Q, why(e_q))
    elif qs:
        src.filed(SRC_FIN_Q, qs[0]["period_end"], _filed_note(qs[0], qbasis), QUARTER_MAX_AGE)
    if e_a is not None:
        src.miss(SRC_FIN_A, why(e_a))
    elif ys:
        src.filed(SRC_FIN_A, ys[0]["period_end"], "consolidated" if ybasis else "standalone", ANNUAL_MAX_AGE)
    if e_f is not None:
        src.miss(SRC_FEAT, why(e_f))
    elif feat:
        src.add(SRC_FEAT, feat.get("as_of_date"), _ratios_note(feat))

    if not qs and not ys:
        if e_q is None and e_a is None:
            blocks.append(notice(f"Quarterly and annual results for {sym} are not in our data, so there is no trend to show.", "warn", "nodata"))
        return _finish(assemble("financial_trend", title, None, None, "neutral", blocks, src, follow_ups, now=ctx.get("now")), None)

    shown_q = qs[:max(1, min(want_q, MAX_QUARTERS_SHOWN))]
    kpis: List[Dict[str, Any]] = []
    head = None
    if shown_q:
        lq = shown_q[0]
        ya = _year_ago(qs, lq)
        pq = _prev_q(qs, lq)
        lab = _q_label(lq["period_end"])
        rev_yoy, pat_yoy = _growth(lq.get("revenue_from_ops_cr"), (ya or {}).get("revenue_from_ops_cr")), _growth(lq.get("pat_cr"), (ya or {}).get("pat_cr"))
        rev_qoq = _growth(lq.get("revenue_from_ops_cr"), (pq or {}).get("revenue_from_ops_cr"))
        kpis.append({"label": f"Revenue · {lab} quarter", "value": _cr(lq.get("revenue_from_ops_cr")),
                     "sub": " · ".join(x for x in (f"{_signed(rev_yoy)} YoY" if rev_yoy is not None else "YoY: no year-ago quarter",
                                                    f"{_signed(rev_qoq)} QoQ" if rev_qoq is not None else None) if x)})
        kpis.append({"label": f"PAT · {lab} quarter", "value": _cr(lq.get("pat_cr")),
                     "sub": f"{_signed(pat_yoy)} YoY" if pat_yoy is not None else "YoY: no comparable year-ago quarter"})
        if not lender:
            m, m_ya = _margin(lq, "ebitda_cr"), _margin(ya, "ebitda_cr")
            kpis.append({"label": "EBITDA margin", "value": _lvl(m),
                         "sub": f"{_pp(m - m_ya)} vs {_q_label(ya['period_end'])}" if m is not None and m_ya is not None else "no year-ago margin"})
        bits = []
        if num(lq.get("revenue_from_ops_cr")) is not None:
            bits.append(f"revenue of {_cr(lq.get('revenue_from_ops_cr'))}" + (f" ({_signed(rev_yoy)} year on year)" if rev_yoy is not None else ""))
        if num(lq.get("pat_cr")) is not None:
            bits.append(f"PAT of {_cr(lq.get('pat_cr'))}" + (f" ({_signed(pat_yoy)})" if pat_yoy is not None else ""))
        head = f"{sym} reported {' and '.join(bits)} for the {lab} quarter." if bits else None
        # Faster or slower: the latest quarter's YoY revenue growth against the previous quarter's (both need a year-ago quarter).
        if pq is not None and rev_yoy is not None:
            prev_yoy = _growth(pq.get("revenue_from_ops_cr"), (_year_ago(qs, pq) or {}).get("revenue_from_ops_cr"))
            if prev_yoy is not None and head:
                word = "faster than" if rev_yoy > prev_yoy else "slower than" if rev_yoy < prev_yoy else "the same as"
                head += f" Year-on-year revenue growth was {word} the {_q_label(pq['period_end'])} quarter's ({_signed(prev_yoy)})."
    for label, key in (("ROE (latest)", "roe_pct"), ("ROCE (latest)", "roce_pct")):
        if feat and num(feat.get(key)) is not None:
            kpis.append({"label": label, "value": _lvl(feat.get(key)),
                         "sub": f"{_provider(feat.get('fundamentals_source'))}, {day_text(feat.get('fundamentals_as_of')) or 'date not stated'}"})
    if kpis:
        blocks.append(block("kpis", "latest", "Latest quarter", None, items=kpis))

    if shown_q:
        old_first = list(reversed(shown_q))
        blocks.append(block("bars", "revenue", "Revenue by quarter", f"₹ crore, {'consolidated' if qbasis else 'standalone'}, as filed.",
                            unit="₹ Cr", orientation="v",
                            items=[{"label": _q_label(r["period_end"]), "value": _r(r.get("revenue_from_ops_cr"), 0),
                                    "sub": (lambda g: f"{_signed(g)} YoY" if g is not None else None)(
                                        _growth(r.get("revenue_from_ops_cr"), (_year_ago(qs, r) or {}).get("revenue_from_ops_cr")))}
                                   for r in old_first]))
        blocks.append(block("bars", "pat", "PAT by quarter", "Profit after tax, ₹ crore, as filed.", unit="₹ Cr", orientation="v",
                            items=[{"label": _q_label(r["period_end"]), "value": _r(r.get("pat_cr"), 0)} for r in old_first]))
        margins = [_margin(r, "ebitda_cr") for r in old_first]
        if not lender and any(m is not None for m in margins):
            blocks.append(block("bars", "margin", "EBITDA margin by quarter", "EBITDA ÷ revenue from operations.", unit="%", orientation="v",
                                items=[{"label": _q_label(r["period_end"]), "value": m} for r, m in zip(old_first, margins)]))
        cols = [{"key": "q", "label": "Quarter", "format": "text"}, {"key": "rev", "label": "Revenue ₹Cr", "format": "text"},
                {"key": "rev_yoy", "label": "YoY", "format": "pct"}, {"key": "rev_qoq", "label": "QoQ", "format": "pct"}]
        if not lender:
            cols += [{"key": "ebitda", "label": "EBITDA ₹Cr", "format": "text"}, {"key": "ebitda_m", "label": "EBITDA margin", "format": "text"}]
        cols += [{"key": "pat", "label": "PAT ₹Cr", "format": "text"}, {"key": "pat_yoy", "label": "PAT YoY", "format": "pct"},
                 {"key": "pat_m", "label": "PAT margin", "format": "text"}]
        if any(r.get("source") for r in shown_q):
            cols.append({"key": "src", "label": "Source", "format": "text"})
        rows = []
        for r in shown_q:
            ya, pq = _year_ago(qs, r), _prev_q(qs, r)
            cells = {"q": _q_label(r["period_end"]), "rev": _cr_cell(r.get("revenue_from_ops_cr")),
                     "rev_yoy": _growth(r.get("revenue_from_ops_cr"), (ya or {}).get("revenue_from_ops_cr")),
                     "rev_qoq": _growth(r.get("revenue_from_ops_cr"), (pq or {}).get("revenue_from_ops_cr")),
                     "pat": _cr_cell(r.get("pat_cr")), "pat_yoy": _growth(r.get("pat_cr"), (ya or {}).get("pat_cr")),
                     "pat_m": _lvl(_margin(r, "pat_cr")), "src": _provider(r.get("source"))}
            if not lender:
                cells.update(ebitda=_cr_cell(r.get("ebitda_cr")), ebitda_m=_lvl(_margin(r, "ebitda_cr")))
            rows.append({"symbol": None, "cells": cells})
        blocks.append(block("ranked", "quarters", "Quarter by quarter",
                            "YoY compares the same quarter a year earlier and is blank when that quarter is not in our data or its "
                            "base was a loss. Figures are as filed, in ₹ crore.", columns=cols, rows=rows))
        providers = sorted({_provider(r.get("source")) for r in shown_q if r.get("source")})
        if len(providers) > 1:
            blocks.append(notice(f"These quarters come from more than one provider ({', '.join(providers)}). Providers can define "
                                 "EBITDA differently, so a jump between quarters from different providers may be a definition change.",
                                 "info", "providers"))
        no_ebitda = sum(1 for r in shown_q if num(r.get("ebitda_cr")) is None)
        if no_ebitda and not lender:
            blocks.append(notice(f"EBITDA is not in our data for {no_ebitda} of the {len(shown_q)} quarters shown.", "info", "noebitda"))

    shown_y = ys[:max(1, min(want_y, MAX_YEARS_SHOWN))]
    if shown_y:
        eq_by = _equity_by_period(ys, qs)
        cols = [{"key": "fy", "label": "Year", "format": "text"}, {"key": "rev", "label": "Revenue ₹Cr", "format": "text"},
                {"key": "rev_yoy", "label": "Revenue YoY", "format": "pct"}, {"key": "pat", "label": "PAT ₹Cr", "format": "text"},
                {"key": "pat_yoy", "label": "PAT YoY", "format": "pct"}]
        if not lender:
            cols.append({"key": "ebitda_m", "label": "EBITDA margin", "format": "text"})
        cols.append({"key": "roe", "label": "ROE (computed)", "format": "text"})
        if any(r.get("source") for r in shown_y):
            cols.append({"key": "src", "label": "Source", "format": "text"})
        rows = []
        for r in shown_y:
            prev = _year_ago(ys, r)
            roe = _roe(r, prev, eq_by)
            cells = {"fy": _fy_label(r["period_end"]), "rev": _cr_cell(r.get("revenue_from_ops_cr")),
                     "rev_yoy": _growth(r.get("revenue_from_ops_cr"), (prev or {}).get("revenue_from_ops_cr")),
                     "pat": _cr_cell(r.get("pat_cr")), "pat_yoy": _growth(r.get("pat_cr"), (prev or {}).get("pat_cr")),
                     "roe": _lvl(roe), "src": _provider(r.get("source"))}
            if not lender:
                cells["ebitda_m"] = _lvl(_margin(r, "ebitda_cr"))
            rows.append({"symbol": None, "cells": cells})
        blocks.append(block("ranked", "years", "Fiscal years",
                            "ROE (computed) = PAT ÷ the average of the opening and closing equity, from filed balance sheets; blank "
                            "when either balance sheet is not in our data.", columns=cols, rows=rows))
        cagr = _cagr(shown_y)
        if cagr:
            blocks.append(block("kpis", "cagr", "Growth across the years shown", "Compound annual growth, first to last year shown.", items=cagr))

    depth = []
    if qs:
        depth.append(f"{len(qs)} quarters ({_q_label(qs[-1]['period_end'])} to {_q_label(qs[0]['period_end'])})")
    if ys:
        depth.append(f"{len(ys)} fiscal years ({_fy_label(ys[-1]['period_end'])} to {_fy_label(ys[0]['period_end'])})")
    asked = []
    if intent.params.get("years") and len(ys) < int(intent.params["years"]):
        asked.append(f"you asked for {intent.params['years']} years")
    if intent.params.get("quarters") and len(qs) < int(intent.params["quarters"]):
        asked.append(f"you asked for {intent.params['quarters']} quarters")
    blocks.append(notice(f"Our data has {' and '.join(depth) or 'no periods'} for {sym}"
                         + (f"; {' and '.join(asked)}, so the answer covers only what is there." if asked else "."), "info", "depth"))
    gaps = ["Segment revenue and profit (only in the company's filings and presentations)",
            "ROE and ROCE history: the platform keeps only the latest provider value; ROE above is computed from filed statements"]
    if lender:
        gaps.insert(0, "Bank metrics: GNPA, NNPA, CASA and capital adequacy; EBITDA is not a measure for a lender, so it is left out")
    blocks.append(block("list", "gaps", "Not in our data", None, items=[{"text": t} for t in gaps]))
    as_of = _newest(*(r.get("as_of") for r in src.rows))
    return _finish(assemble("financial_trend", title, as_of, head, "neutral", blocks, src, follow_ups, now=ctx.get("now")), as_of)


def _ratios_note(feat: Dict[str, Any]) -> str:
    return (f"P/E from the feature engine on {day_text(feat.get('as_of_date')) or 'n/a'}; ROE, ROCE, D/E, P/B and market cap from "
            f"{_provider(feat.get('fundamentals_source'))} as of {day_text(feat.get('fundamentals_as_of')) or 'an unstated date'}")


def _equity_by_period(ys: List[Dict[str, Any]], qs: List[Dict[str, Any]]) -> Dict[str, float]:
    """Total equity by balance-sheet date: annual rows first, then the quarterly row of the same date (the TrueData load
    fills the March and September quarterly rows)."""
    out: Dict[str, float] = {}
    for r in list(ys) + list(qs):
        v = num(r.get("total_equity_cr"))
        if v is not None and v > 0:
            out.setdefault(iso_day(r["period_end"]), v)
    return out


def _roe(r: Dict[str, Any], prev: Optional[Dict[str, Any]], eq_by: Dict[str, float]) -> Optional[float]:
    if prev is None:
        return None
    close, open_ = eq_by.get(iso_day(r["period_end"])), eq_by.get(iso_day(prev["period_end"]))
    pat = num(r.get("pat_attrib_owners_cr"))
    pat = pat if pat is not None else num(r.get("pat_cr"))
    if close is None or open_ is None or pat is None:
        return None
    return round(pat / ((close + open_) / 2.0) * 100.0, 2)


def _cagr(ys: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(ys) < 3:
        return []
    first, last = ys[-1], ys[0]
    n = round(_days_between(last["period_end"], first["period_end"]) / 365.25)
    out = []
    for label, key in (("Revenue CAGR", "revenue_from_ops_cr"), ("PAT CAGR", "pat_cr")):
        a, b = num(last.get(key)), num(first.get(key))
        if a is None or b is None or b <= 0 or a <= 0 or n < 2:
            continue
        out.append({"label": label, "value": _signed(((a / b) ** (1.0 / n) - 1.0) * 100.0),
                    "sub": f"{_fy_label(first['period_end'])} to {_fy_label(last['period_end'])}, {n} years"})
    return out


# ═════ valuation_view ════════════════════════════════════════════════════════════════════════════════════════════════

async def valuation_view(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    sym = intent.symbol
    follow_ups = follow(f"Compare {sym} with its peers", f"What is the financial trend of {sym}?", f"What are the biggest risks for {sym}?",
                        f"Has promoter holding of {sym} changed over time?")
    title = f"{sym} · Valuation"
    (feat, e_f), (hist, e_h) = await asyncio.gather(_try(rr.features_latest(sym)), _try(rr.pe_history(sym)))
    blocks = _lead(intent)
    if e_f is not None:
        src.miss(SRC_FEAT, why(e_f))
    elif not feat:
        blocks.append(notice(f"The platform has no feature row for {sym}, so its valuation figures are not in our data.", "warn", "nodata"))
    else:
        src.add(SRC_FEAT, feat.get("as_of_date"), _ratios_note(feat))
    series = []
    if e_h is not None:
        src.miss(SRC_PE, why(e_h))
    else:
        series = sorted(((iso_day(r.get("as_of_date")), num(r.get("pe_ttm"))) for r in hist or [] if iso_day(r.get("as_of_date"))),
                        key=lambda t: t[0])
        series = [(d, v) for d, v in series if v is not None and v > 0]
        if series:
            src.add(SRC_PE, series[-1][0], f"{len(series)} sessions from {day_text(series[0][0])}")
    pe = num((feat or {}).get("pe_ttm"))
    median = num((feat or {}).get("sector_median_pe"))
    vs = round((pe / median - 1.0) * 100.0, 2) if pe and median and pe > 0 and median > 0 else None
    sector = (feat or {}).get("sector") or (feat or {}).get("industry")
    kpis = [
        {"label": "P/E (trailing 12 months)", "value": _times(pe) if pe and pe > 0 else ("negative earnings" if pe is not None else "not in our data"),
         "sub": f"feature engine, {day_text((feat or {}).get('as_of_date'))}" if pe is not None else None},
        {"label": "Sector median P/E", "value": _times(median) if median else "not in our data",
         "sub": f"stocks under the sector label “{sector}”" if median and sector else None},
        {"label": "P/E vs sector median", "value": _signed(vs) if vs is not None else "not in our data",
         "sub": "P/E ÷ sector median − 1" if vs is not None else None},
        {"label": "P/B", "value": _times((feat or {}).get("pb"), 2) or "not in our data",
         "sub": f"{_provider((feat or {}).get('fundamentals_source'))}, {day_text((feat or {}).get('fundamentals_as_of'))}" if num((feat or {}).get("pb")) is not None else None},
        {"label": "Market cap", "value": _cr((feat or {}).get("market_cap_cr")) or "not in our data", "sub": None},
        {"label": "EV/EBITDA", "value": "not in our data", "sub": "no enterprise-value series is filled for any stock"},
        {"label": "Dividend yield", "value": _lvl((feat or {}).get("dividend_yield_pct"), 2) or "not in our data", "sub": None},
    ]
    blocks.append(block("kpis", "now", "Valuation now", None, items=kpis))
    head = None
    if series and pe and pe > 0:
        vals = [v for _, v in series]
        lo_d, lo = min(series, key=lambda t: t[1])
        hi_d, hi = max(series, key=lambda t: t[1])
        med = statistics.median(vals)
        below = sum(1 for v in vals if v < pe)
        pctile = round(100.0 * below / len(vals))
        blocks.append(block("bars", "pe_range", f"P/E since {day_text(series[0][0])}",
                            f"The daily P/E the platform stored over {len(vals)} sessions, {day_text(series[0][0])} to "
                            f"{day_text(series[-1][0])}. The stored history starts there; an older range is not in our data.",
                            unit="×", orientation="h",
                            items=[{"label": "Lowest", "value": round(lo, 2), "sub": day_text(lo_d)},
                                   {"label": "Median", "value": round(med, 2)},
                                   {"label": "Highest", "value": round(hi, 2), "sub": day_text(hi_d)},
                                   {"label": "Now", "value": round(pe, 2), "sub": day_text((feat or {}).get("as_of_date")), "tone": "neutral"}]))
        blocks.append(block("kpis", "pctile", "Today's P/E against its own history", None, items=[
            {"label": "Sessions with a lower P/E", "value": f"{pctile}%", "sub": f"{below} of {len(vals)} sessions"},
            {"label": "Average P/E", "value": _times(sum(vals) / len(vals)), "sub": f"since {day_text(series[0][0])}"}]))
        head = (f"{sym} trades at {_times(pe)} trailing earnings ({day_text((feat or {}).get('as_of_date'))})"
                + ((f", in line with the median P/E of its sector label ({_times(median)})" if abs(vs) < 0.05 else
                    f", {abs(vs):.1f}% {'below' if vs < 0 else 'above'} the median P/E of its sector label ({_times(median)})") if vs is not None else "")
                + f"; its P/E was lower on {pctile}% of the {len(vals)} sessions since {day_text(series[0][0])}.")
    elif pe and pe > 0:
        head = f"{sym} trades at {_times(pe)} trailing earnings ({day_text((feat or {}).get('as_of_date'))})."
    growth = [g for g in intent.params.get("growth") or [] if num(g) is not None]
    if growth and pe and pe > 0:
        blocks.append(block("ranked", "scenarios", "Growth scenarios (arithmetic, not a forecast)",
                            f"If trailing earnings grew by each rate and the price stayed at the {day_text((feat or {}).get('as_of_date'))} close, "
                            "the P/E would be today's P/E ÷ (1 + growth). A scenario under stated assumptions; no price is projected.",
                            columns=[{"key": "g", "label": "Earnings growth", "format": "text"},
                                     {"key": "pe", "label": "P/E at today's price", "format": "text"}],
                            rows=[{"symbol": None, "cells": {"g": f"{g:g}%", "pe": _times(pe / (1.0 + g / 100.0))}} for g in growth]))
    elif growth:
        blocks.append(notice("The growth scenarios need a positive trailing P/E, which is not in our data for this stock.", "info", "noscen"))
    gaps = ["EV/EBITDA: no enterprise-value series is filled for any stock",
            f"P/E before {day_text(series[0][0]) if series else '29 Dec 2025'}: the stored daily history starts there",
            "The growth a price implies (a valuation model with a discount rate) is not run here",
            "Forward P/E: no analyst consensus estimates are in our data"]
    blocks.append(block("list", "gaps", "Not in our data", None, items=[{"text": t} for t in gaps]))
    as_of = _newest(*(r.get("as_of") for r in src.rows))
    return _finish(assemble("valuation_view", title, as_of, head, "neutral", blocks, src, follow_ups, now=ctx.get("now")), as_of)


# ═════ ownership_trend ═══════════════════════════════════════════════════════════════════════════════════════════════

_SHP_FIELDS = ("promoter_pct", "fii_pct", "dii_pct", "mf_pct", "promoter_pledged_pct", "promoter_pledged_to_total_pct")
_HOLDERS = (("Promoters", "promoter_pct"), ("FIIs", "fii_pct"), ("DIIs", "dii_pct"), ("Mutual funds", "mf_pct"))


class Holdings:
    """The shareholding pattern, one record per quarter (newest first), with the source of every field.

    Two providers fill nidp.shareholding_pattern: NSE's own filing (NSE_SHP, mostly the latest quarter) and screener.in (the
    history). Measured on staging, 2 Nov 2026: of 807 quarters both report, FII % differs by more than 0.5 points in 7, all
    companies with depository receipts (ICICIBANK 50.44 vs 34.68); promoter % never does. So, per field:
      * the providers disagree on some quarter (> 0.5 points) → the series takes screener.in, which carries the earlier quarters,
        and no change is computed across the two sources;
      * otherwise NSE first, screener.in where NSE lacks the field; a change across the two sources is computed, and the answer
        says so when they were never checked against each other for this company.
    screener.in's `public_pct` is retail only (NSE's is everything not promoter), so neither public figure is used.
    Pledge is in NSE's rows only, and is kept only when it agrees with the promoter holding (pledged-of-total ≈ promoter ×
    pledged-of-promoter): 1,149 NSE rows carry a pledge with no promoter holding (HDFCBANK 17.53%, ITC 100%)."""

    TOL = 0.5
    JUMP = 5.0

    def __init__(self, rows: Optional[List[Dict[str, Any]]]):
        by: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for r in rows or []:
            d = iso_day(r.get("period_end"))
            if d:
                by.setdefault(d, {}).setdefault(str(r.get("source") or ""), r)
        self.conflicts: Dict[str, Tuple[str, float, float]] = {}
        self.verified: set = set()
        for d, provs in by.items():
            n, sc = provs.get("NSE_SHP"), provs.get("screener_in")
            for f in ("promoter_pct", "fii_pct", "dii_pct"):
                a, b = num((n or {}).get(f)), num((sc or {}).get(f))
                if a is None or b is None:
                    continue
                if abs(a - b) > self.TOL:
                    if f not in self.conflicts or d > self.conflicts[f][0]:
                        self.conflicts[f] = (d, a, b)
                else:
                    self.verified.add(f)
        self.crossed: set = set()
        self.pledge_dropped: List[str] = []
        self.recs: List[Dict[str, Any]] = []
        for d in sorted(by, reverse=True):
            provs = by[d]
            rec: Dict[str, Any] = {"period_end": d, "src_of": {}, "broadcast_at": None}
            for f in _SHP_FIELDS:
                order = (["screener_in", "NSE_SHP"] if f in self.conflicts else ["NSE_SHP", "screener_in"]) + sorted(provs)
                rec[f] = None
                for prov in order:
                    v = num((provs.get(prov) or {}).get(f))
                    if v is not None:
                        rec[f], rec["src_of"][f] = v, _provider(prov)
                        break
            self._check_pledge(rec)
            rec["sources"] = set(rec["src_of"].values())
            rec["broadcast_at"] = next((r.get("broadcast_at") for r in provs.values() if r.get("broadcast_at")), None)
            if any(rec[f] is not None for f in ("promoter_pct", "fii_pct", "dii_pct", "mf_pct")):
                self.recs.append(rec)

    def _check_pledge(self, rec: Dict[str, Any]) -> None:
        plg, tot, prom = rec.get("promoter_pledged_pct"), rec.get("promoter_pledged_to_total_pct"), rec.get("promoter_pct")
        if plg is None and tot is None:
            return
        ok = prom is not None and prom > 0 and plg is not None and 0 <= plg <= 100 and (
            tot is None or abs(prom * plg / 100.0 - tot) <= max(0.02, 0.05 * tot))
        if not ok:
            self.pledge_dropped.append(rec["period_end"])
            rec["promoter_pledged_pct"] = rec["promoter_pledged_to_total_pct"] = None
            rec["src_of"].pop("promoter_pledged_pct", None)
            rec["src_of"].pop("promoter_pledged_to_total_pct", None)

    def ago(self, r: Optional[Dict[str, Any]], quarters: int) -> Optional[Dict[str, Any]]:
        if not r:
            return None
        lo, hi = 91 * quarters - 15, 91 * quarters + 15
        return next((x for x in self.recs if lo <= _days_between(r["period_end"], x["period_end"]) <= hi), None)

    def delta(self, a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]], f: str) -> Optional[float]:
        if not a or not b or a.get(f) is None or b.get(f) is None:
            return None
        if a["src_of"].get(f) != b["src_of"].get(f):
            if f in self.conflicts:
                return None                         # the two sources define this field differently for this company
            if f not in self.verified:
                self.crossed.add(f)
        return round(a[f] - b[f], 2)

    def notices(self, sym: str) -> List[Dict[str, Any]]:
        out = []
        names = {"promoter_pct": "promoter holding", "fii_pct": "FII holding", "dii_pct": "DII holding"}
        for f, (d, a, b) in sorted(self.conflicts.items()):
            out.append(notice(f"For {_q_label(d)}, NSE's filing puts {sym}'s {names[f]} at {a:.2f}% and screener.in at {b:.2f}%: the two "
                              "sources define it differently for this company. The series uses screener.in, which carries the earlier "
                              "quarters, and no change is computed across the two sources.", "warn", f"conflict-{f}"))
        if self.crossed:
            out.append(notice("Some quarter-on-quarter changes compare NSE's filing (the latest quarter) with screener.in (earlier quarters); "
                              f"for {sym} the two sources have no quarter in common to check them against each other.", "info", "crossed"))
        jumps = []
        for i, r in enumerate(self.recs):
            prev = self.ago(r, 1)
            for f, label in (("promoter_pct", "promoters"), ("fii_pct", "FIIs"), ("dii_pct", "DIIs")):
                if prev and r.get(f) is not None and prev.get(f) is not None and r["src_of"].get(f) == prev["src_of"].get(f) \
                        and abs(r[f] - prev[f]) > self.JUMP:
                    jumps.append(f"{label} {_pp(r[f] - prev[f])} ({_q_label(prev['period_end'])} to {_q_label(r['period_end'])})")
        if jumps:
            out.append(notice(f"Unusually large one-quarter changes for {sym}: {'; '.join(jumps[:4])}. A move of more than {self.JUMP:g} "
                              "points can be real, or a change in how the source classifies holders; check the company's shareholding "
                              "filings for those quarters.", "warn", "jumps"))
        if self.pledge_dropped:
            out.append(notice(f"NSE's filing carries a pledge figure for {sym} ({', '.join(_q_label(d) for d in self.pledge_dropped[:3])}) that "
                              "does not agree with the promoter holding (or no promoter group is reported), so it is not shown.",
                              "info", "pledge-dropped"))
        return out


def _merge_shp(rows: Optional[List[Dict[str, Any]]]) -> Holdings:
    return Holdings(rows)


async def ownership_trend(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    sym = intent.symbol
    follow_ups = follow(f"Any ownership filings for {sym}?", f"What are the biggest risks for {sym}?", f"What is the valuation of {sym}?",
                        f"Compare {sym} with its peers")
    title = f"{sym} · Ownership"
    (shp, e_s), (amc, e_a) = await asyncio.gather(_try(rr.shareholding(sym)), _try(rr.amc(sym)))
    blocks = _lead(intent)
    hold = _merge_shp(shp if e_s is None else [])
    recs = hold.recs
    if e_s is not None:
        src.miss(SRC_SHP, why(e_s))
    elif recs:
        src.filed(SRC_SHP, recs[0]["period_end"], f"{len(recs)} quarters; NSE filing and screener.in, field by field", SHAREHOLDING_MAX_AGE)
    else:
        blocks.append(notice(f"The shareholding pattern of {sym} is not in our data.", "warn", "noshp"))
    head = None
    if recs:
        last, prev, year = recs[0], hold.ago(recs[0], 1), hold.ago(recs[0], 4)
        lab = _q_label(last["period_end"])
        kpis = []
        for label, f in _HOLDERS:
            if last.get(f) is None:
                kpis.append({"label": f"{label} · {lab}", "value": "not reported", "sub": "MF share is in NSE's own filing only" if f == "mf_pct" else None})
                continue
            d1, d4 = hold.delta(last, prev, f), hold.delta(last, year, f)
            sub = " · ".join(x for x in ((f"{_pp(d1)} vs {_q_label(prev['period_end'])}" if d1 is not None else None),
                                         (f"{_pp(d4)} vs {_q_label(year['period_end'])}" if d4 is not None else None)) if x)
            kpis.append({"label": f"{label} · {lab}", "value": _lvl(last[f], 2), "sub": sub or "no earlier quarter to compare"})
        pledge = next((r for r in recs if r.get("promoter_pledged_pct") is not None), None)
        kpis.append({"label": "Pledged (of promoter shares)",
                     "value": _lvl(pledge["promoter_pledged_pct"], 2) if pledge else "not reported",
                     "sub": (f"{_q_label(pledge['period_end'])}" + (f"; {_lvl(pledge['promoter_pledged_to_total_pct'], 2)} of all shares"
                                                                    if pledge.get("promoter_pledged_to_total_pct") is not None else ""))
                     if pledge else "NSE's filing reports pledge; a blank is not reported, not zero"})
        blocks.append(block("kpis", "latest", f"Shareholding · {lab}", None, items=kpis))
        span = recs[:QUARTERS_SHOWN]
        base = span[-1]
        changes = [{"label": label, "value": hold.delta(last, base, f)} for label, f in _HOLDERS if hold.delta(last, base, f) is not None]
        if len(span) > 1 and changes:
            blocks.append(block("bars", "change", f"Change from {_q_label(base['period_end'])} to {lab}", "Percentage points of the company's shares.",
                                unit="pp", orientation="h", items=changes))
        cols = [{"key": "q", "label": "Quarter", "format": "text"}, {"key": "prom", "label": "Promoters", "format": "text"},
                {"key": "d_prom", "label": "Δ", "format": "text"}, {"key": "fii", "label": "FIIs", "format": "text"},
                {"key": "d_fii", "label": "Δ", "format": "text"}, {"key": "dii", "label": "DIIs", "format": "text"},
                {"key": "d_dii", "label": "Δ", "format": "text"}, {"key": "mf", "label": "MFs", "format": "text"},
                {"key": "pledge", "label": "Pledged (of promoter)", "format": "text"}, {"key": "src", "label": "Source", "format": "text"}]
        rows = []
        for r in span:
            p = hold.ago(r, 1)
            rows.append({"symbol": None, "cells": {
                "q": _q_label(r["period_end"]), "prom": _lvl(r.get("promoter_pct"), 2), "d_prom": _pp(hold.delta(r, p, "promoter_pct")),
                "fii": _lvl(r.get("fii_pct"), 2), "d_fii": _pp(hold.delta(r, p, "fii_pct")), "dii": _lvl(r.get("dii_pct"), 2),
                "d_dii": _pp(hold.delta(r, p, "dii_pct")), "mf": _lvl(r.get("mf_pct"), 2), "pledge": _lvl(r.get("promoter_pledged_pct"), 2),
                "src": " + ".join(sorted(r["sources"]))}})
        blocks.append(block("ranked", "quarters", "Quarter by quarter",
                            "Percent of the company's shares. Δ is the change from the previous quarter in percentage points. A blank is "
                            "not reported for that quarter, not zero.", columns=cols, rows=rows))
        if len(recs) < 4:
            blocks.append(notice(f"Our data has only {len(recs)} quarter{'s' if len(recs) != 1 else ''} of shareholding for {sym}, so a "
                                 "four-quarter trend cannot be shown.", "info", "depth"))
        else:
            blocks.append(notice(f"Our data has {len(recs)} quarters of shareholding for {sym} ({_q_label(recs[-1]['period_end'])} to {lab}).",
                                 "info", "depth"))
        parts = [f"{label} {_lvl(last[f], 2)}" + (f" ({_pp(hold.delta(last, prev, f))})" if hold.delta(last, prev, f) is not None else "")
                 for label, f in _HOLDERS[:3] if last.get(f) is not None]
        if parts:
            head = (f"{sym} at {lab}, percent of shares: " + "; ".join(parts)
                    + (f" (change from {_q_label(prev['period_end'])} in brackets)." if prev and "(" in "".join(parts) else "."))
        blocks.extend(hold.notices(sym))
    _amc_blocks(sym, amc, e_a, src, blocks)
    gaps = ["Promoter trades one by one: the insider-trading table is empty; the exchange filings (ask for ownership filings) list SAST and pledge disclosures",
            "Which FIIs entered or exited: FII holdings are reported only as a category total",
            "Mutual-fund holdings before September 2025"]
    blocks.append(block("list", "gaps", "Not in our data", None, items=[{"text": t} for t in gaps]))
    as_of = _newest(*(r.get("as_of") for r in src.rows))
    return _finish(assemble("ownership_trend", title, as_of, head, "neutral", blocks, src, follow_ups, now=ctx.get("now")), as_of)


def _amc_blocks(sym: str, amc: Optional[Dict[str, Any]], err: Optional[BaseException], src: Sources, blocks: List[Dict[str, Any]]) -> None:
    if err is not None:
        reason = why(err)
        if "404" in reason:
            reason = "the data platform does not serve the fund-house view yet (HTTP 404)"
        src.miss(SRC_AMC, reason)
        return
    rows = [r for r in (amc or {}).get("rows") or [] if isinstance(r, dict)]
    if not (amc or {}).get("as_of") or not rows:
        blocks.append(notice(f"No disclosed mutual-fund scheme holding of {sym} was found in the latest months. The fund-house view covers "
                             "stocks with an ISIN in NSE's index files.", "info", "noamc"))
        return
    cur, prv = amc["as_of"], amc.get("previous_month")
    src.filed(SRC_AMC, cur, f"monthly scheme disclosures, {day_text(prv)} to {day_text(cur)}", 75)
    t = amc.get("totals") or {}
    blocks.append(block("kpis", "amc_totals", f"Mutual funds · {_month(cur)} vs {_month(prv)}",
                        "Monthly scheme disclosures, every scheme of a fund house added together, the stock matched by ISIN.", items=[
        {"label": "Fund houses holding", "value": f"{int(t.get('amcs') or len(rows))}", "sub": f"{int(t.get('schemes') or 0)} schemes"},
        {"label": "Schemes that added", "value": f"{int(t.get('schemes_up') or 0)}", "sub": f"{int(t.get('schemes_dn') or 0)} reduced"},
        {"label": "Disclosed MF holding", "value": _lvl(t.get("pct_of_equity"), 2) or "not reported", "sub": "of the company's shares"},
        {"label": "Largest house's share", "value": _lvl(t.get("largest_amc_share_pct")) or "not reported", "sub": "of the disclosed MF holding"}]))
    cols = [{"key": "amc", "label": "Fund house", "format": "text"}, {"key": "schemes", "label": "Schemes (up/down)", "format": "text"},
            {"key": "delta", "label": "Shares change", "format": "text"}, {"key": "chg", "label": "Change", "format": "pct"},
            {"key": "share", "label": "Share of MF holding", "format": "text"}]
    out = []
    for r in rows[:8]:
        d = num(r.get("shares_delta"))
        out.append({"symbol": None, "cells": {
            "amc": str(r.get("amc_name") or r.get("amc_id") or "not named"),
            "schemes": f"{int(r.get('schemes') or 0)} ({int(r.get('schemes_up') or 0)}/{int(r.get('schemes_dn') or 0)})",
            "delta": None if d is None else ("+" if d > 0 else MINUS if d < 0 else "") + _indian(abs(d)),
            "chg": _r(r.get("shares_pct_change")), "share": _lvl(r.get("share_of_disclosed_pct"))}})
    blocks.append(block("ranked", "amc", "Fund houses that moved the most shares",
                        "Every scheme of a house added together; the share count change, not the value change (a value change mixes in "
                        "the price move).", columns=cols, rows=out))


def _month(d: Any) -> str:
    x = date.fromisoformat(iso_day(d)) if iso_day(d) else None
    return f"{x.strftime('%b')} {x.year}" if x else "n/a"


# ═════ peer_compare ══════════════════════════════════════════════════════════════════════════════════════════════════

def _label_of(row: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    row = row or {}
    return (str(row.get("sector")).strip() or None) if row.get("sector") else None, (str(row.get("industry")).strip() or None) if row.get("industry") else None


def _peer_set(sym: str, universe: Dict[str, Any]) -> Tuple[List[str], Optional[str], Optional[str], int, int]:
    """(symbols, how they were chosen, the label, stocks with a sector label, stocks in the universe). Exact label match, never a
    substring ("IT" must not match "Capital Goods"): the sector label first, then NSE's industry."""
    rows = [r for r in universe.get("rows") or [] if isinstance(r, dict) and r.get("symbol")]
    me = next((r for r in rows if str(r["symbol"]).upper() == sym), None)
    sector, industry = _label_of(me)
    labelled = sum(1 for r in rows if r.get("sector"))
    for key, label in (("sector", sector), ("industry", industry)):
        if not label:
            continue
        same = [r for r in rows if str(r.get(key) or "").strip().lower() == label.lower() and str(r["symbol"]).upper() != sym]
        same.sort(key=lambda r: -(num(r.get("market_cap_cr")) or 0.0))
        if same:
            return [sym] + [str(r["symbol"]).upper() for r in same[:PEERS_SHOWN - 1]], key, label, labelled, len(rows)
    return [sym], None, None, labelled, len(rows)


def _latest_q_metrics(rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    qs, _ = _series(rows, "quarterly")
    if not qs:
        return {}
    lq = qs[0]
    ya = _year_ago(qs, lq)
    return {"q": _q_label(lq["period_end"]), "rev_yoy": _growth(lq.get("revenue_from_ops_cr"), (ya or {}).get("revenue_from_ops_cr")),
            "pat_yoy": _growth(lq.get("pat_cr"), (ya or {}).get("pat_cr")), "ebitda_m": _margin(lq, "ebitda_cr"), "period_end": lq["period_end"]}


async def peer_compare(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    sym = intent.symbol
    named = [s for s in intent.params.get("symbols") or [] if s]
    title = f"{' vs '.join(named)} · Comparison" if len(named) >= 2 else f"{sym} · Peer comparison"
    blocks = _lead(intent)
    how, label = None, None
    if len(named) >= 2:
        syms = named
        feats_l = await asyncio.gather(*(_try(rr.features_latest(s)) for s in syms))
        feats = {s: (f if isinstance(f, dict) else None) for s, (f, _e) in zip(syms, feats_l)}
        errs = [why(e) for _f, e in feats_l if e is not None]
        days = [iso_day(f.get("as_of_date")) for f in feats.values() if f]
        if days:
            src.add(SRC_FEAT, max(days), "P/E from the feature engine; ROE, ROCE, D/E, P/B, market cap and holdings from the provider row of each stock")
        if errs:
            src.miss(f"{SRC_FEAT}, {len(errs)} of {len(syms)} companies", errs[0])
    else:
        uni, e_u = await _try(rr.universe())
        labelled = total = 0
        if e_u is not None:
            src.miss(SRC_UNIV, why(e_u))
            syms, labelled, total = [sym], 0, 0
        else:
            syms, how, label, labelled, total = _peer_set(sym, uni)
            src.add(SRC_UNIV, uni.get("as_of"), f"{labelled:,} of {total:,} stocks carry a sector label")
        day = iso_day((uni or {}).get("as_of"))
        feats: Dict[str, Optional[Dict[str, Any]]] = {}
        if day:
            got, e_b = await _try(rr.features_on(syms, day))
            if e_b is not None:
                src.miss(SRC_FEAT, why(e_b))
            else:
                feats = {s: (got or {}).get(s) for s in syms}
                src.add(SRC_FEAT, day, "P/E from the feature engine; ROE, ROCE, D/E, P/B, market cap and holdings from the provider row of each stock")
        if how is None and e_u is None:
            blocks.append(notice(f"{sym} has no sector label or NSE industry in our data, so its peers cannot be chosen. The sector map "
                                 f"covers {labelled:,} of {total:,} stocks. Name the companies to compare (for example “Compare {sym} and …”).",
                                 "warn", "nomap"))
        if intent.params.get("one_recognised"):
            blocks.append(notice(f"Only {sym} was recognised as a company in your question, so it is compared with its peers. If a company "
                                 "you named is not in the table, ask again with its NSE symbol.", "info", "one_named"))
        if how is not None:
            blocks.append(notice(f"Peers are the largest stocks our data files under the same {'sector label' if how == 'sector' else 'NSE industry'} "
                                 f"(“{label}”), by market cap. The sector map covers {labelled:,} of {total:,} stocks, so a listed peer "
                                 "outside it is missing here.", "info", "peers"))
    fins = await asyncio.gather(*(_try(rr.financials(s, "quarterly", 12)) for s in syms))
    qm = {s: (_latest_q_metrics(rows) if e is None else {}) for s, (rows, e) in zip(syms, fins)}
    fin_err = [s for s, (_r_, e) in zip(syms, fins) if e is not None]
    latest_q = [m["period_end"] for m in qm.values() if m.get("period_end")]
    if latest_q:
        src.filed(SRC_FIN_Q, max(latest_q), "each company's latest quarter, shown per row", QUARTER_MAX_AGE)
    if fin_err:
        src.miss(f"{SRC_FIN_Q}, {len(fin_err)} of {len(syms)} companies", f"not read for {', '.join(fin_err)}")
    lender = any(_is_lender(feats.get(s)) for s in syms)
    missing = [s for s in syms if not feats.get(s) and not qm.get(s)]
    if missing:
        blocks.append(notice(f"No figures are in our data for {', '.join(missing)}.", "warn", "missing_cos"))

    def cells_growth(s: str) -> Dict[str, Any]:
        f, m = feats.get(s) or {}, qm.get(s) or {}
        c = {"co": s, "q": m.get("q"), "rev_yoy": m.get("rev_yoy"), "pat_yoy": m.get("pat_yoy"),
             "roe": _lvl(f.get("roe_pct")), "roce": _lvl(f.get("roce_pct")), "de": _times(f.get("debt_to_equity"), 2)}
        if not lender:
            c["ebitda_m"] = _lvl(m.get("ebitda_m"))
        return c

    def cells_value(s: str) -> Dict[str, Any]:
        f = feats.get(s) or {}
        pe = num(f.get("pe_ttm"))
        return {"co": s, "mcap": _cr_cell(f.get("market_cap_cr")), "pe": _times(pe) if pe and pe > 0 else ("negative" if pe is not None else None),
                "pb": _times(f.get("pb"), 2), "prom": _lvl(f.get("promoter_pct"), 2), "fii": _lvl(f.get("fii_pct"), 2), "dii": _lvl(f.get("dii_pct"), 2)}

    shown = [s for s in syms if s not in missing] or syms
    pes = [num((feats.get(s) or {}).get("pe_ttm")) for s in shown]
    pes = [p for p in pes if p and p > 0]
    roes = [num((feats.get(s) or {}).get("roe_pct")) for s in shown]
    roes = [r for r in roes if r is not None]
    my_pe = num((feats.get(sym) or {}).get("pe_ttm"))
    med_pe = statistics.median(pes) if len(pes) >= 2 else None
    kpis = [{"label": "Companies compared", "value": f"{len(shown)}", "sub": f"{'sector label' if how == 'sector' else 'NSE industry'} “{label}”" if label else "as named"},
            {"label": "Median P/E of the set", "value": _times(med_pe) if med_pe else "not in our data", "sub": f"{len(pes)} with a positive P/E"},
            {"label": f"{sym} P/E vs the set's median", "value": _signed((my_pe / med_pe - 1.0) * 100.0) if my_pe and my_pe > 0 and med_pe else "not in our data",
             "sub": "P/E ÷ median − 1" if my_pe and med_pe else None},
            {"label": "Median ROE of the set", "value": _lvl(statistics.median(roes)) if len(roes) >= 2 else "not in our data", "sub": f"{len(roes)} with an ROE"}]
    blocks.append(block("kpis", "summary", "The comparison", None, items=kpis))
    g_cols = [{"key": "co", "label": "Company", "format": "text"}, {"key": "q", "label": "Latest quarter", "format": "text"},
              {"key": "rev_yoy", "label": "Revenue YoY", "format": "pct"}, {"key": "pat_yoy", "label": "PAT YoY", "format": "pct"}]
    if not lender:
        g_cols.append({"key": "ebitda_m", "label": "EBITDA margin", "format": "text"})
    g_cols += [{"key": "roe", "label": "ROE", "format": "text"}, {"key": "roce", "label": "ROCE", "format": "text"},
               {"key": "de", "label": "Debt / equity", "format": "text"}]
    blocks.append(block("ranked", "growth", "Growth, margins and returns",
                        "Growth and margin from each company's latest filed quarter against the same quarter a year earlier (the quarter "
                        "is shown per row). ROE, ROCE and debt / equity are the provider's latest values.",
                        columns=g_cols, rows=[{"symbol": s, "badge": "This company" if s == sym and len(named) < 2 else None,
                                               "ask": f"What is the financial trend of {s}?", "cells": cells_growth(s)} for s in shown]))
    v_cols = [{"key": "co", "label": "Company", "format": "text"}, {"key": "mcap", "label": "Mkt cap ₹Cr", "format": "text"},
              {"key": "pe", "label": "P/E", "format": "text"}, {"key": "pb", "label": "P/B", "format": "text"},
              {"key": "prom", "label": "Promoters", "format": "text"}, {"key": "fii", "label": "FIIs", "format": "text"},
              {"key": "dii", "label": "DIIs", "format": "text"}]
    blocks.append(block("ranked", "value", "Valuation and ownership",
                        "P/E is trailing twelve months; holdings are percent of shares at the latest quarter the provider reports.",
                        columns=v_cols, rows=[{"symbol": s, "badge": "This company" if s == sym and len(named) < 2 else None,
                                               "ask": f"What is the valuation of {s}?", "cells": cells_value(s)} for s in shown]))
    extremes = _extremes(shown, feats, qm, lender)
    if extremes:
        blocks.append(block("list", "extremes", "Highest and lowest in this set", "A position in this set, not a ranking of the companies.",
                            items=[{"text": t} for t in extremes]))
    if lender:
        blocks.append(notice("Asset quality (GNPA, NNPA), CASA and capital adequacy are not in our data, so a bank comparison here covers "
                             "growth, returns, valuation and ownership only. EBITDA margin is left out: it is not a measure for a lender.",
                             "info", "lender"))
    head = (f"{len(shown)} companies compared on their latest filed quarter and the platform's latest ratios"
            + (f"; {sym}'s P/E is {_times(my_pe)} against a median of {_times(med_pe)} for the set." if my_pe and my_pe > 0 and med_pe else "."))
    follow_ups = follow(f"What is the valuation of {sym}?", f"What is the financial trend of {sym}?", f"What are the biggest risks for {sym}?",
                        f"Has promoter holding of {sym} changed over time?")
    as_of = _newest(*(r.get("as_of") for r in src.rows))
    return _finish(assemble("peer_compare", title, as_of, head, "neutral", blocks, src, follow_ups, now=ctx.get("now")), as_of)


def _extremes(syms: List[str], feats: Dict[str, Any], qm: Dict[str, Any], lender: bool) -> List[str]:
    out = []
    specs = [("Revenue growth YoY", lambda s: (qm.get(s) or {}).get("rev_yoy"), lambda v: _signed(v)),
             ("ROE", lambda s: num((feats.get(s) or {}).get("roe_pct")), lambda v: _lvl(v)),
             ("Debt / equity", lambda s: num((feats.get(s) or {}).get("debt_to_equity")), lambda v: _times(v, 2)),
             ("P/E", lambda s: (lambda p: p if p and p > 0 else None)(num((feats.get(s) or {}).get("pe_ttm"))), lambda v: _times(v)),
             ("FII holding", lambda s: num((feats.get(s) or {}).get("fii_pct")), lambda v: _lvl(v, 2))]
    if not lender:
        specs.insert(1, ("EBITDA margin", lambda s: (qm.get(s) or {}).get("ebitda_m"), lambda v: _lvl(v)))
    for name, get, fmt in specs:
        vals = [(s, get(s)) for s in syms]
        vals = [(s, v) for s, v in vals if v is not None]
        if len(vals) < 2:
            continue
        hi = max(vals, key=lambda t: t[1])
        lo = min(vals, key=lambda t: t[1])
        out.append(f"{name}: highest {hi[0]} ({fmt(hi[1])}), lowest {lo[0]} ({fmt(lo[1])}); {len(vals)} of {len(syms)} have it.")
    return out


# ═════ company_risks ═════════════════════════════════════════════════════════════════════════════════════════════════

FLAG, OK, NODATA, NA = "Flagged", "Within the rule", "Not in our data", "Not applicable"
DEBT_RULE = "debt up over 20%, faster than PAT, and at least 0.1× equity"
BS_COLS = ("current_assets_cr", "current_liabilities_cr", "trade_receivables_cr", "inventory_cr")
CANNOT_CHECK = ["Related-party transactions (only in the annual report's notes)",
                "When the debt matures (only in the annual report's notes)",
                "Auditor remarks and contingent liabilities (only in the annual report)",
                "A ranking of risks by potential impact: there is no stated method for it, so the checks are listed in a fixed order"]


def _bs_rows(qs: List[Dict[str, Any]], ys: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Balance sheets by date, newest first: rows that carry equity or debt (March and September, filed half-yearly)."""
    by: Dict[str, Dict[str, Any]] = {}
    for r in list(qs) + list(ys):
        d = iso_day(r.get("period_end"))
        if d and (num(r.get("total_equity_cr")) is not None or num(r.get("current_assets_cr")) is not None) and d not in by:
            by[d] = r
    return [by[d] for d in sorted(by, reverse=True)]


def _debt(r: Optional[Dict[str, Any]]) -> Optional[float]:
    if not r:
        return None
    a, b = num(r.get("long_term_debt_cr")), num(r.get("short_term_debt_cr"))
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


def _check(name: str, value: Optional[str], rule: str, result: str, when: Optional[str]) -> Dict[str, Any]:
    return {"name": name, "value": value, "rule": rule, "result": result, "when": when}


async def company_risks(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    sym = intent.symbol
    follow_ups = follow(f"What is the financial trend of {sym}?", f"Has promoter holding of {sym} changed over time?",
                        f"What is the valuation of {sym}?", f"Any ownership filings for {sym}?")
    title = f"{sym} · Financial health and risk checks"
    (q, e_q), (a, e_a), (cf, e_c), (shp, e_s), (feat, e_f) = await asyncio.gather(
        _try(rr.financials(sym, "quarterly", 40)), _try(rr.financials(sym, "annual", 12)), _try(rr.cashflow(sym)),
        _try(rr.shareholding(sym)), _try(rr.features_latest(sym)))
    blocks = _lead(intent)
    qs, qbasis = _series(q, "quarterly")
    ys, ybasis = _series(a, "annual")
    lender = _is_lender(feat, qs)
    bs = _bs_rows(qs, ys) if e_q is None else []
    served = bool(q or a) and any(c in r for r in (q or []) + (a or []) for c in BS_COLS)
    if e_q is not None:
        src.miss(SRC_FIN_Q, why(e_q))
    elif qs:
        src.filed(SRC_FIN_Q, qs[0]["period_end"], _filed_note(qs[0], qbasis), QUARTER_MAX_AGE)
    if e_a is not None:
        src.miss(SRC_FIN_A, why(e_a))
    elif ys:
        src.filed(SRC_FIN_A, ys[0]["period_end"], "consolidated" if ybasis else "standalone", ANNUAL_MAX_AGE)
    cfs: List[Dict[str, Any]] = []
    if e_c is not None:
        reason = why(e_c)
        src.miss(SRC_CF, "the data platform does not serve cash-flow statements yet (HTTP 404)" if "404" in reason else reason)
    else:
        rows = [r for r in cf or [] if iso_day(r.get("period_end"))]
        basis = any(bool(r.get("consolidated")) for r in rows) if rows else None
        seen = set()
        for r in sorted(rows, key=lambda r: iso_day(r["period_end"]), reverse=True):
            d = iso_day(r["period_end"])
            if bool(r.get("consolidated")) == basis and d not in seen:
                seen.add(d)
                cfs.append(r)
        if cfs:
            src.filed(SRC_CF, cfs[0]["period_end"], f"{'consolidated' if basis else 'standalone'}, provider {_provider(cfs[0].get('source'))}",
                      CASHFLOW_MAX_AGE)
        else:
            blocks.append(notice(f"Cash-flow statements for {sym} are not in our data yet, so the cash checks show no figure.", "info", "nocf"))
    hold = _merge_shp(shp if e_s is None else [])
    recs = hold.recs
    if e_s is not None:
        src.miss(SRC_SHP, why(e_s))
    elif recs:
        src.filed(SRC_SHP, recs[0]["period_end"], "NSE filing and screener.in, field by field", SHAREHOLDING_MAX_AGE)
    if e_f is not None:
        src.miss(SRC_FEAT, why(e_f))
    elif feat:
        src.add(SRC_FEAT, feat.get("as_of_date"), _ratios_note(feat))
    if (q or a) and not served:
        blocks.append(notice("Current assets and liabilities, receivables and inventory are not served by the data platform yet, so the "
                             "liquidity, receivables and working-capital checks show no figure.", "info", "bs_not_served"))

    checks = _run_checks(sym, lender, qs, ys, bs, cfs, hold, feat, served, e_c is None)
    flagged = [c for c in checks if c["result"] == FLAG]
    ran = [c for c in checks if c["result"] in (FLAG, OK)]
    nodata = [c for c in checks if c["result"] == NODATA]
    blocks.append(block("kpis", "summary", "The checks", "A flag is a prompt to read further, not a verdict on the company.", items=[
        {"label": "Flagged", "value": f"{len(flagged)} of {len(ran)}", "sub": "checks that could run", "tone": "warn" if flagged else None},
        {"label": "No data", "value": f"{len(nodata)}", "sub": "checks without the figures they need"},
        {"label": "Latest balance sheet", "value": _q_label(bs[0]["period_end"]) if bs else "not in our data",
         "sub": f"filed {day_text(bs[0]['broadcast_at'])}" if bs and iso_day(bs[0].get("broadcast_at")) else None},
        {"label": "Latest cash-flow year", "value": _fy_label(cfs[0]["period_end"]) if cfs else "not in our data", "sub": None}]))
    blocks.append(block("ranked", "checks", "Checks, in a fixed order", "Each rule is printed beside its result.",
                        columns=[{"key": "check", "label": "Check", "format": "text"}, {"key": "value", "label": "Value", "format": "text"},
                                 {"key": "rule", "label": "Rule", "format": "text"}, {"key": "result", "label": "Result", "format": "text"},
                                 {"key": "when", "label": "Period", "format": "text"}],
                        rows=[{"symbol": None, "tone": "warn" if c["result"] == FLAG else None,
                               "cells": {"check": c["name"], "value": c["value"], "rule": c["rule"], "result": c["result"], "when": c["when"]}}
                              for c in checks]))
    _cash_blocks(cfs, ys, lender, blocks)
    _bs_block(bs, lender, served, blocks)
    if lender:
        blocks.append(notice("For a bank or lender, asset quality (GNPA, NNPA), capital adequacy and CASA are the core risk checks; they are "
                             "not in our data. Checks built for non-financial companies are marked not applicable.", "info", "lender"))
    blocks.append(block("list", "cannot", "Cannot be checked here", None, items=[{"text": t} for t in CANNOT_CHECK]))
    if flagged:
        head = (f"{len(flagged)} of the {len(ran)} {'check' if len(ran) == 1 else 'checks'} that could run "
                f"{'is' if len(flagged) == 1 else 'are'} flagged for {sym}: " + "; ".join(c["name"] for c in flagged) + ".")
    elif ran:
        head = (f"None of the {len(ran)} {'check' if len(ran) == 1 else 'checks'} that could run is flagged for {sym}"
                + (f"; {len(nodata)} could not run for lack of data." if nodata else "."))
    elif lender:
        head = (f"For a bank or lender like {sym}, these checks mostly do not apply, and the ones that do (asset quality, capital "
                "adequacy) are not in our data.")
    else:
        head = f"No check could run for {sym}: the figures they need are not in our data."
    as_of = _newest(*(r.get("as_of") for r in src.rows))
    return _finish(assemble("company_risks", title, as_of, head, "warn" if flagged else "neutral", blocks, src, follow_ups,
                            now=ctx.get("now")), as_of)


def _run_checks(sym: str, lender: bool, qs, ys, bs, cfs, hold: Holdings, feat, served: bool, cf_served: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    recs = hold.recs
    last_bs = bs[0] if bs else None
    bs_year_ago = _year_ago(bs, last_bs) if last_bs else None
    bs_when = _q_label(last_bs["period_end"]) if last_bs else None

    # 1. Debt to equity
    if lender:
        out.append(_check("Debt to equity", None, "above 1.0×", NA, None))
    else:
        d, e = _debt(last_bs), num((last_bs or {}).get("total_equity_cr"))
        if d is None or e is None or e <= 0:
            out.append(_check("Debt to equity", None, "above 1.0×", NODATA, bs_when))
        else:
            de = d / e
            out.append(_check("Debt to equity", f"{de:.2f}× ({_cr(d)} debt)", "above 1.0×", FLAG if de > 1.0 else OK, bs_when))

    # 2. Debt growth against profit growth (fiscal years)
    if lender:
        out.append(_check("Debt growth vs profit growth", None, DEBT_RULE, NA, None))
    else:
        d1, d0 = _debt(last_bs), _debt(bs_year_ago)
        fy, fy0 = (ys[0], _year_ago(ys, ys[0])) if ys else (None, None)
        pat_g = _growth((fy or {}).get("pat_cr"), (fy0 or {}).get("pat_cr"))
        eq1 = num((last_bs or {}).get("total_equity_cr"))
        if d1 is None or d0 is None:
            out.append(_check("Debt growth vs profit growth", None, DEBT_RULE, NODATA, bs_when))
        elif d0 == 0 and d1 == 0:
            out.append(_check("Debt growth vs profit growth", "no debt at either date", DEBT_RULE, OK, bs_when))
        else:
            dg = _growth(d1, d0)
            material = eq1 is not None and eq1 > 0 and d1 >= 0.1 * eq1
            val = (f"debt {_signed(dg) if dg is not None else 'from zero'} to {_cr(d1)} ({_times(d1 / eq1, 2) if eq1 else 'n/a'} equity); "
                   f"PAT {_signed(pat_g) if pat_g is not None else 'n/a'} ({_fy_label(fy['period_end']) if fy else 'n/a'})")
            flag = material and ((dg is None and d1 > 0) or (dg is not None and dg > 20 and (pat_g is None or dg > pat_g)))
            out.append(_check("Debt growth vs profit growth", val, DEBT_RULE, FLAG if flag else OK,
                              f"{_q_label(bs_year_ago['period_end'])} to {bs_when}"))

    # 3. Interest cover (latest fiscal year): (PBT + finance costs) ÷ finance costs
    fy = ys[0] if ys else None
    fc, pbt = num((fy or {}).get("finance_costs_cr")), num((fy or {}).get("pbt_cr"))
    when = _fy_label(fy["period_end"]) if fy else None
    if lender:
        out.append(_check("Interest cover", None, "below 3×", NA, None))
    elif fc is None or pbt is None:
        out.append(_check("Interest cover", "finance costs not in our data" if fy else None, "below 3×", NODATA, when))
    elif fc <= 0:
        out.append(_check("Interest cover", "no finance cost filed", "below 3×", OK, when))
    else:
        ic = (pbt + fc) / fc
        out.append(_check("Interest cover", _times(ic), "below 3×", FLAG if ic < 3 else OK, when))

    # 4. Current ratio
    ca, cl = num((last_bs or {}).get("current_assets_cr")), num((last_bs or {}).get("current_liabilities_cr"))
    if lender:
        out.append(_check("Current ratio", None, "below 1.0×", NA, None))
    elif not served:
        out.append(_check("Current ratio", "not served by the data platform yet", "below 1.0×", NODATA, None))
    elif ca is None or cl is None or cl <= 0:
        out.append(_check("Current ratio", None, "below 1.0×", NODATA, bs_when))
    else:
        out.append(_check("Current ratio", _times(ca / cl, 2), "below 1.0×", FLAG if ca / cl < 1.0 else OK, bs_when))

    # 5-7. Cash: CFO ÷ PAT, PAT growth vs CFO growth, free cash flow (fiscal years)
    cf = cfs[0] if cfs else None
    cf_prev = _year_ago(cfs, cf) if cf else None
    pat_fy = next((y for y in ys if cf and iso_day(y["period_end"]) == iso_day(cf["period_end"])), None)
    pat_prev = next((y for y in ys if cf_prev and iso_day(y["period_end"]) == iso_day(cf_prev["period_end"])), None)
    cf_when = _fy_label(cf["period_end"]) if cf else None
    cf_reason = None if cf_served else "not served by the data platform yet"
    if lender:
        for name, rule in (("Cash from operations ÷ PAT", "below 0.8×"), ("PAT growth vs cash-flow growth", "PAT growth over 20 points above CFO growth"),
                           ("Free cash flow", "negative")):
            out.append(_check(name, None, rule, NA, None))
    else:
        cfo, pat = num((cf or {}).get("cfo_cr")), num((pat_fy or {}).get("pat_cr"))
        if cfo is None or pat is None or pat <= 0:
            v = cf_reason or ("PAT is a loss" if pat is not None and pat <= 0 else None)
            out.append(_check("Cash from operations ÷ PAT", v, "below 0.8×", NODATA, cf_when))
        else:
            out.append(_check("Cash from operations ÷ PAT", f"{_times(cfo / pat, 2)} ({_cr(cfo)} ÷ {_cr(pat)})", "below 0.8×",
                              FLAG if cfo / pat < 0.8 else OK, cf_when))
        pg = _growth((pat_fy or {}).get("pat_cr"), (pat_prev or {}).get("pat_cr"))
        cg = _growth((cf or {}).get("cfo_cr"), (cf_prev or {}).get("cfo_cr"))
        if pg is None or cg is None:
            out.append(_check("PAT growth vs cash-flow growth", cf_reason, "PAT growth over 20 points above CFO growth", NODATA, cf_when))
        else:
            out.append(_check("PAT growth vs cash-flow growth", f"PAT {_signed(pg)}, CFO {_signed(cg)}", "PAT growth over 20 points above CFO growth",
                              FLAG if pg - cg > 20 else OK, f"{_fy_label(cf_prev['period_end'])} to {cf_when}"))
        capex = num((cf or {}).get("capex_cr"))
        if cfo is None or capex is None:
            out.append(_check("Free cash flow", cf_reason, "negative", NODATA, cf_when))
        else:
            fcf = cfo + capex
            out.append(_check("Free cash flow", f"{_cr(fcf)} (CFO {_cr(cfo)}, capex {_cr(capex)})", "negative", FLAG if fcf < 0 else OK, cf_when))

    # 8. Receivables growth against revenue growth (twelve months to each balance sheet)
    rec1, rec0 = num((last_bs or {}).get("trade_receivables_cr")), num((bs_year_ago or {}).get("trade_receivables_cr"))
    rev1, rev0 = _rev12(qs, ys, last_bs["period_end"], bs_year_ago["period_end"]) if last_bs and bs_year_ago else (None, None)
    rule = "receivables growth over 15 points above revenue growth"
    if lender:
        out.append(_check("Receivables vs revenue growth", None, rule, NA, None))
    elif not served:
        out.append(_check("Receivables vs revenue growth", "not served by the data platform yet", rule, NODATA, None))
    else:
        rg, vg = _growth(rec1, rec0), _growth(rev1, rev0)
        if rg is None or vg is None:
            out.append(_check("Receivables vs revenue growth", None, rule, NODATA, bs_when))
        else:
            out.append(_check("Receivables vs revenue growth", f"receivables {_signed(rg)}, revenue (12 months) {_signed(vg)}", rule,
                              FLAG if rg - vg > 15 else OK, f"{_q_label(bs_year_ago['period_end'])} to {bs_when}"))

    # 9. Working capital (current assets − cash − current liabilities) in days of twelve-month revenue
    rule = "up more than 15 days of revenue in a year"
    if lender:
        out.append(_check("Working capital days", None, rule, NA, None))
    elif not served:
        out.append(_check("Working capital days", "not served by the data platform yet", rule, NODATA, None))
    else:
        def wc_days(r, rev):
            ca_, cl_, cash_ = num((r or {}).get("current_assets_cr")), num((r or {}).get("current_liabilities_cr")), num((r or {}).get("cash_and_equiv_cr"))
            if None in (ca_, cl_, rev) or not rev or rev <= 0:
                return None
            return (ca_ - (cash_ or 0.0) - cl_) / rev * 365.0
        w1, w0 = wc_days(last_bs, rev1), wc_days(bs_year_ago, rev0)
        if w1 is None or w0 is None:
            out.append(_check("Working capital days", None, rule, NODATA, bs_when))
        else:
            out.append(_check("Working capital days", f"{_whole(w1)} days (a year earlier {_whole(w0)})", rule, FLAG if w1 - w0 > 15 else OK,
                              f"{_q_label(bs_year_ago['period_end'])} to {bs_when}"))

    # 10. Promoter pledge (latest reported)
    pledge = next((r for r in recs if r.get("promoter_pledged_pct") is not None), None)
    if pledge is None:
        out.append(_check("Promoter pledge", "not reported", "above 10% of promoter shares", NODATA, None))
    else:
        v = pledge["promoter_pledged_pct"]
        out.append(_check("Promoter pledge", f"{_lvl(v, 2)} of promoter shares", "above 10% of promoter shares", FLAG if v > 10 else OK,
                          _q_label(pledge["period_end"])))

    # 11. Promoter holding over four quarters
    last = recs[0] if recs else None
    year = hold.ago(last, 4) if last else None
    d = hold.delta(last, year, "promoter_pct")
    if d is None:
        out.append(_check("Promoter holding change", None, "down more than 2 points in four quarters", NODATA, None))
    else:
        out.append(_check("Promoter holding change", f"{_pp(d)} to {_lvl(last['promoter_pct'], 2)}", "down more than 2 points in four quarters",
                          FLAG if d < -2 else OK, f"{_q_label(year['period_end'])} to {_q_label(last['period_end'])}"))

    # 12. EBITDA margin against the same quarter a year earlier
    rule = "down more than 3 points"
    if lender:
        out.append(_check("EBITDA margin trend", None, rule, NA, None))
    else:
        lq = qs[0] if qs else None
        ya = _year_ago(qs, lq) if lq else None
        m1, m0 = _margin(lq, "ebitda_cr"), _margin(ya, "ebitda_cr")
        if m1 is None or m0 is None:
            out.append(_check("EBITDA margin trend", None, rule, NODATA, _q_label(lq["period_end"]) if lq else None))
        else:
            out.append(_check("EBITDA margin trend", f"{_lvl(m1)} vs {_lvl(m0)}", rule, FLAG if m1 - m0 < -3 else OK,
                              f"{_q_label(ya['period_end'])} to {_q_label(lq['period_end'])}"))

    # 13. Piotroski F-score (provider)
    f = num((feat or {}).get("piotroski_score"))
    if lender:
        out.append(_check("Piotroski F-score", None, "3 or below (of 9)", NA, None))
    elif f is None:
        out.append(_check("Piotroski F-score", None, "3 or below (of 9)", NODATA, None))
    else:
        out.append(_check("Piotroski F-score", f"{int(f)} of 9 ({_provider((feat or {}).get('fundamentals_source'))})", "3 or below (of 9)",
                          FLAG if f <= 3 else OK, day_text((feat or {}).get("fundamentals_as_of"))))
    return out


def _cash_blocks(cfs: List[Dict[str, Any]], ys: List[Dict[str, Any]], lender: bool, blocks: List[Dict[str, Any]]) -> None:
    if not cfs:
        return
    rows, bars = [], []
    for c in cfs[:YEARS_SHOWN]:
        y = next((x for x in ys if iso_day(x["period_end"]) == iso_day(c["period_end"])), None)
        cfo, pat, capex = num(c.get("cfo_cr")), num((y or {}).get("pat_cr")), num(c.get("capex_cr"))
        ratio = cfo / pat if cfo is not None and pat and pat > 0 else None
        rows.append({"symbol": None, "cells": {"fy": _fy_label(c["period_end"]), "cfo": _cr_cell(cfo), "pat": _cr_cell(pat),
                                               "ratio": _times(ratio, 2), "capex": _cr_cell(capex),
                                               "fcf": _cr_cell(cfo + capex) if cfo is not None and capex is not None else None,
                                               "src": _provider(c.get("source"))}})
        if ratio is not None:
            bars.append({"label": _fy_label(c["period_end"]), "value": round(ratio, 2)})
    blocks.append(block("ranked", "cash", "Cash flow by fiscal year",
                        "₹ crore as filed. Free cash flow = cash from operations + capex (capex is filed as a negative outflow)."
                        + (" For a lender, operating cash flow moves with deposits and loans, so it is not read as profit quality." if lender else ""),
                        columns=[{"key": "fy", "label": "Year", "format": "text"}, {"key": "cfo", "label": "CFO ₹Cr", "format": "text"},
                                 {"key": "pat", "label": "PAT ₹Cr", "format": "text"}, {"key": "ratio", "label": "CFO ÷ PAT", "format": "text"},
                                 {"key": "capex", "label": "Capex ₹Cr", "format": "text"}, {"key": "fcf", "label": "Free cash flow ₹Cr", "format": "text"},
                                 {"key": "src", "label": "Source", "format": "text"}], rows=rows))
    if bars and not lender:
        blocks.append(block("bars", "cfo_pat", "Cash from operations ÷ PAT", "1× (dashed) = every rupee of profit arrived as operating cash.",
                            unit="×", orientation="v", baseline=1.0, items=list(reversed(bars))))


def _bs_block(bs: List[Dict[str, Any]], lender: bool, served: bool, blocks: List[Dict[str, Any]]) -> None:
    if not bs:
        return
    cols = [{"key": "p", "label": "Balance sheet", "format": "text"}, {"key": "eq", "label": "Equity ₹Cr", "format": "text"},
            {"key": "debt", "label": "Debt ₹Cr", "format": "text"}, {"key": "cash", "label": "Cash ₹Cr", "format": "text"}]
    if served and not lender:
        cols += [{"key": "cr", "label": "Current ratio", "format": "text"}, {"key": "rec", "label": "Receivables ₹Cr", "format": "text"},
                 {"key": "inv", "label": "Inventory ₹Cr", "format": "text"}]
    cols.append({"key": "src", "label": "Source", "format": "text"})
    rows = []
    for r in bs[:4]:
        ca, cl = num(r.get("current_assets_cr")), num(r.get("current_liabilities_cr"))
        cells = {"p": _q_label(r["period_end"]), "eq": _cr_cell(r.get("total_equity_cr")), "debt": _cr_cell(_debt(r)),
                 "cash": _cr_cell(r.get("cash_and_equiv_cr")),
                 "src": "TrueData balance sheet" if r.get("bs_truedata") else f"filed ({_provider(r.get('source'))} row)"}
        if served and not lender:
            cells.update(cr=_times(ca / cl, 2) if ca is not None and cl else None, rec=_cr_cell(r.get("trade_receivables_cr")),
                         inv=_cr_cell(r.get("inventory_cr")))
        rows.append({"symbol": None, "cells": cells})
    blocks.append(block("ranked", "balance", "Balance sheets (filed half-yearly)",
                        "Debt = long-term + short-term borrowings. A blank is not in our data, not zero.", columns=cols, rows=rows))


BUILDERS = {"financial_trend": financial_trend, "valuation_view": valuation_view, "ownership_trend": ownership_trend,
            "peer_compare": peer_compare, "company_risks": company_risks}
