"""Portfolio analytics tools for the Nivesh Copilot.

Wraps existing service functions for use by the RAG orchestrator and
future LangGraph agents:

  get_portfolio_xirr      — per-holding XIRR + portfolio weighted return
  get_portfolio_summary   — allocation, overlap, sector exposure
  get_portfolio_overlap   — pairwise fund overlap from portfolio_intelligence
  get_rebalance_plan      — equity/debt drift + actions
  get_tax_harvest_candidates — unrealised-loss positions for harvesting
  run_stress_test         — historical crash scenario simulation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Stress scenarios (mirrors routes/copilot_widgets.py) ─────────────────
_STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "covid_2020": {
        "name": "COVID-19 Crash (Feb–Mar 2020)",
        "equity_drop": -38.0,
        "debt_drop": -2.0,
        "recovery_years": 1.2,
    },
    "gfc_2008": {
        "name": "Global Financial Crisis (2008)",
        "equity_drop": -60.0,
        "debt_drop": -5.0,
        "recovery_years": 4.0,
    },
    "rate_shock": {
        "name": "Rate Shock (+200 bps)",
        "equity_drop": -12.0,
        "debt_drop": -7.0,
        "recovery_years": 1.5,
    },
}


@dataclass
class PortfolioResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


# ── Holdings loader ───────────────────────────────────────────────────────

async def _load_holdings(user_id: str) -> List[Dict[str, Any]]:
    from deps import db
    raw: List[Dict[str, Any]] = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)
    return raw


# ── XIRR ────────────────────────────────────────────────────────────────

async def get_portfolio_xirr(user_id: str) -> PortfolioResult:
    """Compute per-holding XIRR and portfolio-level weighted average.

    Used for: "What is my portfolio XIRR?", "How are my investments performing?"
    """
    from services.portfolio_enrichment import _holding_xirr

    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    rows: List[Dict[str, Any]] = []
    total_invested = 0.0
    total_current = 0.0
    weighted_xirr_sum = 0.0
    weighted_xirr_weight = 0.0

    for h in holdings:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or h.get("avg_cost") or 0)
        cp = float(h.get("current_price") or 0)
        name = h.get("name") or h.get("scheme_name") or h.get("fund_name") or "Unknown"
        buy_date = h.get("buy_date") or h.get("purchase_date")

        if qty <= 0 or cp <= 0:
            continue

        invested = qty * bp
        current = qty * cp
        gain = current - invested
        ret_pct = (gain / invested * 100.0) if invested > 0 else 0.0

        xirr_pct = _holding_xirr(buy_date, bp, cp, qty)

        total_invested += invested
        total_current += current
        if xirr_pct is not None and invested > 0:
            weighted_xirr_sum += xirr_pct * invested
            weighted_xirr_weight += invested

        rows.append({
            "name": name,
            "asset_type": h.get("asset_type", "equity"),
            "invested_rs": round(invested, 0),
            "current_rs": round(current, 0),
            "gain_rs": round(gain, 0),
            "return_pct": round(ret_pct, 2),
            "xirr_pct": round(xirr_pct, 2) if xirr_pct is not None else None,
        })

    if not rows:
        return PortfolioResult(ok=False, summary="No priced holdings found", error="no_data")

    portfolio_gain = total_current - total_invested
    portfolio_return_pct = (portfolio_gain / total_invested * 100.0) if total_invested > 0 else 0.0
    portfolio_xirr = (weighted_xirr_sum / weighted_xirr_weight) if weighted_xirr_weight > 0 else None

    xirr_str = f" (XIRR {portfolio_xirr:+.1f}%)" if portfolio_xirr is not None else ""
    summary = (
        f"Portfolio: invested ₹{total_invested:,.0f} → current ₹{total_current:,.0f} "
        f"= {portfolio_return_pct:+.1f}% absolute return{xirr_str} "
        f"across {len(rows)} positions"
    )

    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "total_invested_rs": round(total_invested, 0),
            "total_current_rs": round(total_current, 0),
            "total_gain_rs": round(portfolio_gain, 0),
            "portfolio_return_pct": round(portfolio_return_pct, 2),
            "portfolio_xirr_pct": round(portfolio_xirr, 2) if portfolio_xirr is not None else None,
            "position_count": len(rows),
        },
        rows=sorted(rows, key=lambda r: r.get("xirr_pct") or -999, reverse=True),
    )


# ── Portfolio summary (allocation + overlap) ──────────────────────────────

async def get_portfolio_summary(user_id: str) -> PortfolioResult:
    """High-level portfolio snapshot: allocation, overlap, sector.

    Used for: "Summarise my portfolio", "How concentrated am I?"
    """
    try:
        from services import portfolio_intelligence as PI
        intel = await PI.compute_portfolio_intelligence(user_id)
    except Exception as exc:
        logger.warning("portfolio_summary pi_failed user=%s error=%s", user_id, exc)
        return PortfolioResult(ok=False, summary="Portfolio intelligence unavailable", error=str(exc))

    # compute_portfolio_intelligence exposes the canonical allocation under
    # "asset_allocation" (equity 93.6% etc. — same as the dashboard). The old
    # key "holistic_allocation" doesn't exist on the response, so this silently
    # read {} and reported a wrong/zero equity split.
    alloc = intel.get("asset_allocation") or {}
    top_stocks = (intel.get("top_stocks") or [])[:5]
    pairs = (intel.get("pairwise_overlap") or [])
    high_overlap = [p for p in pairs if p.get("overlap_pct", 0) >= 40]
    sectors = (intel.get("sector_exposure") or [])[:5]

    equity_pct = alloc.get("equity_pct", 0)
    debt_pct = alloc.get("debt_pct", 0)
    total_rs = intel.get("total_value", 0) or alloc.get("total_value", 0)

    summary_parts = [f"Total ₹{total_rs:,.0f}" if total_rs else "Portfolio"]
    if equity_pct:
        summary_parts.append(f"equity {equity_pct:.0f}%")
    if debt_pct:
        summary_parts.append(f"debt {debt_pct:.0f}%")
    if high_overlap:
        summary_parts.append(f"{len(high_overlap)} high-overlap fund pair(s)")

    rows = []
    for s in top_stocks:
        rows.append({
            "type": "stock_exposure",
            "label": s.get("name") or s.get("slug", ""),
            "value": s.get("exposure_pct", 0),
            "amount_rs": s.get("exposure_rs", 0),
        })
    for sec in sectors:
        rows.append({
            "type": "sector",
            "label": sec.get("sector", "Unknown"),
            "value": sec.get("pct", 0),
            "amount_rs": sec.get("rs", 0),
        })

    return PortfolioResult(
        ok=True,
        summary=" · ".join(summary_parts),
        data={
            "total_value_rs": total_rs,
            "equity_pct": equity_pct,
            "debt_pct": debt_pct,
            "high_overlap_pairs": len(high_overlap),
            "effective_stocks": intel.get("effective_stocks"),
            "compression_score": intel.get("compression_score"),
        },
        rows=rows,
    )


# ── Portfolio overlap ─────────────────────────────────────────────────────

async def get_portfolio_overlap(user_id: str) -> PortfolioResult:
    """Pairwise MF overlap for user's fund holdings.

    Used for: "Which of my funds overlap?", "Show redundancy in my portfolio"
    """
    try:
        from services import portfolio_intelligence as PI
        intel = await PI.compute_portfolio_intelligence(user_id)
    except Exception as exc:
        return PortfolioResult(ok=False, summary="Could not compute overlap", error=str(exc))

    pairs = intel.get("pairwise_overlap") or []
    if not pairs:
        return PortfolioResult(ok=True, summary="No pairwise overlap data — MF holdings may lack portfolio disclosures", rows=[])

    rows = [
        {
            "fund_a": p.get("a_name") or p.get("fund_a") or p.get("a", ""),
            "fund_b": p.get("b_name") or p.get("fund_b") or p.get("b", ""),
            "overlap_pct": round(float(p.get("overlap_pct") or 0), 1),
            "shared_count": p.get("shared_count") or p.get("shared_stocks") or len(p.get("shared", []) or []),
            "top_shared": (p.get("reasons") or [])[:3],
        }
        for p in pairs
    ]
    rows.sort(key=lambda r: r["overlap_pct"], reverse=True)

    # Regular vs Direct of the SAME scheme is a cost issue, not overlap. Flag
    # each pair so the LLM can separate "switch Regular→Direct" (Fix #1) from
    # genuine cross-fund overlap (Fix #2).
    import re as _re

    def _base_scheme(name: str) -> str:
        n = (name or "").lower()
        for tok in ("direct", "regular", "growth", "idcw", "dividend", "payout",
                    "reinvestment", "plan", "option", "-"):
            n = n.replace(tok, " ")
        return _re.sub(r"\s+", " ", n).strip()

    for r in rows:
        r["is_plan_duplicate"] = bool(
            r["fund_a"] and r["fund_b"]
            and _base_scheme(r["fund_a"]) == _base_scheme(r["fund_b"])
        )

    high = [r for r in rows if r["overlap_pct"] >= 40]
    dupe_pairs = [r for r in high if r["is_plan_duplicate"]]
    cross_pairs = [r for r in high if not r["is_plan_duplicate"]]

    # Counts needed to answer "do I have too many funds?" (count, not overlap).
    mf_count = len(intel.get("mf_investments") or [])
    removable_count = len(intel.get("redundancy_suggestions") or [])

    top_lines = "; ".join(
        f"{r['fund_a']} ↔ {r['fund_b']} {r['overlap_pct']:.0f}%"
        for r in high[:5]
    ) if high else ""
    summary = (
        f"{mf_count} mutual fund(s) held; {len(rows)} pair(s) analysed; "
        f"{len(high)} pair(s) with ≥40% overlap "
        f"({len(dupe_pairs)} are Regular+Direct duplicates of the same scheme, "
        f"{len(cross_pairs)} are cross-fund); ~{removable_count} fund(s) removable "
        f"with no loss of exposure"
        + (f" — top: {top_lines}" if top_lines else "")
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "mf_count":                       mf_count,
            "pair_count":                     len(rows),
            "high_overlap_count":             len(high),
            "regular_direct_duplicate_pairs": len(dupe_pairs),
            "cross_fund_overlap_pairs":       len(cross_pairs),
            "removable_fund_count":           removable_count,
            # For pacing only — never derive per-fund switch amounts from these.
            "total_value_rs":                 intel.get("total_value"),
            "equity_pct":                     (intel.get("asset_allocation") or {}).get("equity_pct"),
        },
        rows=rows,
    )


# ── Fund-consolidation widget builder ─────────────────────────────────────

def _short_fund(name: str) -> str:
    """Trim a scheme name for display (drop plan/option/growth noise)."""
    import re as _re
    n = name or ""
    for tok in ("Regular Plan", "Direct Plan", "Growth Plan", "Growth Option",
                "Regular", "Direct", "Growth", "Plan", "Option", "Fund", "Scheme", "-"):
        n = _re.sub(_re.escape(tok), " ", n, flags=_re.I)
    return _re.sub(r"\s+", " ", n).strip()


def _redundancy_question(a: str, b: str) -> str:
    t = (a + " " + b).lower()
    if "index" in t or "nifty" in t or "sensex" in t:
        return "Same index exposure, different weighting — keep both only if you want the tilt."
    return "Keep one — does the second earn its place vs the cheaper option?"


def build_consolidation_widget(overlap: Any) -> Dict[str, Any]:
    """Build the structured fund-consolidation widget_data (verdict, stat tiles,
    hold→need bars, Step 1 cost fixes, Step 2 redundancy review, caveat) from a
    get_portfolio_overlap result (anything with .data and .rows). Every count
    comes from the tool data — no invented numbers.
    """
    d = getattr(overlap, "data", None) or {}
    rows = getattr(overlap, "rows", None) or []
    n = int(d.get("mf_count") or 0)
    dupe_rows = [r for r in rows if r.get("is_plan_duplicate") and (r.get("overlap_pct") or 0) >= 40]
    cross_rows = [r for r in rows if not r.get("is_plan_duplicate") and (r.get("overlap_pct") or 0) >= 40]
    high = int(d.get("high_overlap_count") or (len(dupe_rows) + len(cross_rows)))
    distinct = max(1, n - len(dupe_rows))
    target_lo, target_hi, target_mid = 8, 12, 10
    too_many = n > 15

    verdict = {
        "tone": "warm" if too_many else "good",
        "title": "Yes — more funds than any goal needs" if too_many else "About right — minor cleanup only",
        "subtitle": (
            f"{distinct} distinct funds is well past a sensible count on its own — before overlap "
            f"even enters the picture. This is a count problem first, an overlap problem second."
            if too_many else
            f"{distinct} distinct strategies is a manageable count; only a little overlap to tidy."
        ),
    }
    tiles = [
        {"label": "Holdings you own",    "value": str(n)},
        {"label": "Distinct strategies", "value": str(distinct)},
        {"label": "Healthy target",      "value": f"~{target_lo}–{target_hi}"},
        {"label": "High-overlap pairs",  "value": str(high)},
    ]
    bars = {
        "title": "From what you hold to what you need",
        "max": max(n, 1),
        "items": [
            {"label": "Holdings owned", "value": n, "color": "blue"},
            {"label": "Distinct strategies", "sublabel": f"{len(dupe_rows)} plan-duplicate pairs collapse",
             "value": distinct, "color": "green"},
            {"label": "Healthy target", "sublabel": "one fund per role", "value": target_mid,
             "color": "amber", "approx": True},
        ],
        "reading": (
            f"Removing duplicates gets you from {n} to {distinct} — but the real gap is "
            f"{distinct} → ~{target_mid}. You only need one fund per role: a large-cap, a mid, a "
            f"small, a hybrid, and a debt sleeve cover most goals."
        ),
    }
    step1 = None
    if dupe_rows:
        step1 = {
            "title": "Step 1 — switch same-scheme duplicates (free)",
            "subtitle": "Identical portfolio, just a cheaper plan. Move Regular units to Direct.",
            "rows": [
                {"name": f"{_short_fund(r.get('fund_a', ''))} — Regular → Direct",
                 "meta": f"{round(r.get('overlap_pct') or 0)}% overlap"}
                for r in dupe_rows[:5]
            ],
        }
    step2 = None
    if cross_rows:
        step2 = {
            "title": "Step 2 — question redundant pairs (keep one each)",
            "rows": [
                {"name": f"{_short_fund(r.get('fund_a', ''))} vs {_short_fund(r.get('fund_b', ''))}",
                 "meta": f"~{round(r.get('overlap_pct') or 0)}%",
                 "detail": _redundancy_question(r.get('fund_a', ''), r.get('fund_b', ''))}
                for r in cross_rows[:4]
            ],
        }
    tv = d.get("total_value_rs")
    eq = d.get("equity_pct")
    lead = ""
    if tv:
        lead = f"Book size ₹{tv / 1e7:.2f} cr"
        if eq is not None:
            lead += f" · {round(eq)}% equity"
        lead += ". Stagger switches across financial years to manage capital-gains tax — don't redeem in one go. "
    caveat = lead + (
        "Based on holdings overlap and counts only — no returns, fees, fund size or manager record "
        "here. Exact switch amounts aren't available from this data. Not financial advice; confirm "
        "tax and exit load before acting."
    )
    return {"verdict": verdict, "tiles": tiles, "bars": bars, "step1": step1, "step2": step2, "caveat": caveat}


def _abbrev(name: str) -> str:
    """Short code for a fund used in the heatmap (initials of significant words)."""
    short = _short_fund(name)
    stop = {"of", "the", "and", "&", "india", "asset", "mutual"}
    words = [w for w in short.split() if w.lower() not in stop]
    if not words:
        return short[:3].upper()
    code = "".join(w[0] for w in words[:4]).upper()
    return code[:4] if len(code) >= 2 else short[:3].upper()


def build_overlap_widget(overlap: Any) -> Dict[str, Any]:
    """Build the structured fund-overlap widget_data (tiles, same-scheme cost
    fixes, different-funds redundancy review, a cluster heatmap of the most
    inter-correlated funds, caveat) from a get_portfolio_overlap result.
    """
    d = getattr(overlap, "data", None) or {}
    rows = getattr(overlap, "rows", None) or []
    pair_count = int(d.get("pair_count") or len(rows))
    high_rows = [r for r in rows if (r.get("overlap_pct") or 0) >= 40]
    dupe_rows = [r for r in high_rows if r.get("is_plan_duplicate")]
    cross_rows = [r for r in high_rows if not r.get("is_plan_duplicate")]
    highest = round(max((r.get("overlap_pct") or 0) for r in rows)) if rows else 0

    tiles = [
        {"label": "Pairs analysed",       "value": str(pair_count)},
        {"label": "High overlap (≥40%)",  "value": str(len(high_rows))},
        {"label": "Highest overlap",      "value": f"{highest}%"},
    ]
    same_scheme = None
    if dupe_rows:
        same_scheme = {
            "title": "Same scheme, two plans",
            "subtitle": "Identical portfolio. Switch Regular units to Direct for a lower expense ratio.",
            "badge": "cost fix — free",
            "tone": "neg",
            "rows": [
                {"name": f"{_short_fund(r.get('fund_a', ''))} · Regular ↔ Direct",
                 "overlap_pct": round(r.get("overlap_pct") or 0)}
                for r in dupe_rows[:5]
            ],
        }
    different_funds = None
    if cross_rows:
        top = sorted(cross_rows, key=lambda r: -(r.get("overlap_pct") or 0))
        shown = top[:2]
        rest = len(top) - len(shown)
        lo = round(min((r.get("overlap_pct") or 0) for r in top[len(shown):])) if rest > 0 else 0
        hi = round(max((r.get("overlap_pct") or 0) for r in top[len(shown):])) if rest > 0 else 0
        different_funds = {
            "title": "Different funds, similar holdings",
            "subtitle": "Not duplicates — a judgement call on whether each earns its place.",
            "badge": "review — keep one",
            "tone": "warm",
            "rows": [
                {"name": f"{_short_fund(r.get('fund_a', ''))} ↔ {_short_fund(r.get('fund_b', ''))}",
                 "overlap_pct": round(r.get("overlap_pct") or 0),
                 "detail": _redundancy_question(r.get("fund_a", ""), r.get("fund_b", ""))}
                for r in shown
            ],
            "more_note": (f"+ {rest} more pair(s) in the {lo}–{hi}% range — lower priority." if rest > 0 else None),
        }

    # ── Heatmap: the 4 funds that appear most in high cross-fund pairs ──────
    heatmap = None
    if cross_rows:
        from collections import defaultdict
        deg: Dict[str, int] = defaultdict(int)
        pct: Dict[frozenset, int] = {}
        for r in cross_rows:
            a, b = r.get("fund_a", ""), r.get("fund_b", "")
            if not a or not b:
                continue
            deg[a] += 1
            deg[b] += 1
            pct[frozenset((a, b))] = round(r.get("overlap_pct") or 0)
        cluster = [f for f, _ in sorted(deg.items(), key=lambda kv: -kv[1])[:4]]
        if len(cluster) >= 3:
            labels = [{"key": _abbrev(f), "full": _short_fund(f)} for f in cluster]
            matrix = [
                [None if i == j else pct.get(frozenset((ci, cj)), 0)
                 for j, cj in enumerate(cluster)]
                for i, ci in enumerate(cluster)
            ]
            heatmap = {
                "title": "How the most-overlapping funds cluster",
                "subtitle": "Darker = more shared holdings.",
                "labels": labels,
                "matrix": matrix,
                "legend": " · ".join(f"{l['key']} = {l['full']}" for l in labels),
            }

    caveat = (
        "Based on holdings overlap only — no returns, fees, fund size or manager record here. "
        "Switching is a sell-and-rebuy: stagger across financial years and check exit load and "
        "capital-gains tax. Not financial advice."
    )
    return {
        "tiles": tiles,
        "same_scheme": same_scheme,
        "different_funds": different_funds,
        "heatmap": heatmap,
        "caveat": caveat,
    }


# ── Portfolio fund comparison (rolling returns + TER + overlap) ───────────

async def compare_portfolio_funds(user_id: str) -> PortfolioResult:
    """Side-by-side comparison of every mutual fund in the user's portfolio:
    1y/3y/5y rolling returns, expense ratio, category, AUM, Sharpe, and top
    pairwise overlap. Returns scheme NAMES (never raw instrument UUIDs).

    Used for: "Compare the mutual funds in my portfolio",
              "Show rolling returns, expense ratio, and overlap"
    """
    try:
        from services import portfolio_intelligence as PI
        intel = await PI.compute_portfolio_intelligence(user_id)
    except Exception as exc:
        return PortfolioResult(ok=False, summary="Could not compute fund comparison", error=str(exc))

    investments = intel.get("mf_investments") or []
    catalog = intel.get("catalog") or {}
    pairs = intel.get("pairwise_overlap") or []

    if not investments:
        return PortfolioResult(
            ok=True,
            summary="No mutual fund holdings found in your portfolio",
            rows=[],
        )

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    rows: List[Dict[str, Any]] = []
    funds_with_returns = 0
    funds_with_ter = 0

    for inv in investments:
        inv_id = inv.get("instrument_id")
        ratios = (catalog.get(inv_id, {}) or {}).get("ratios", {}) if inv_id else {}
        rr = inv.get("rolling_returns") or {}

        ret_1y = _f(rr.get("1y") if rr else ratios.get("ret_1y"))
        ret_3y = _f(rr.get("3y") if rr else ratios.get("ret_3y"))
        ret_5y = _f(rr.get("5y") if rr else ratios.get("ret_5y"))
        ter    = _f(inv.get("expense_ratio"))
        sharpe = _f(ratios.get("sharpe"))
        std    = _f(ratios.get("std_dev"))
        amt    = _f(inv.get("amount_rs")) or 0.0

        if any(v is not None for v in (ret_1y, ret_3y, ret_5y)):
            funds_with_returns += 1
        if ter is not None:
            funds_with_ter += 1

        rows.append({
            "scheme_name":       inv.get("scheme_name", "Unknown"),
            "category":          inv.get("category"),
            "amount_rs":         round(amt, 0),
            "return_1y_pct":     round(ret_1y, 2) if ret_1y is not None else None,
            "return_3y_pct":     round(ret_3y, 2) if ret_3y is not None else None,
            "return_5y_pct":     round(ret_5y, 2) if ret_5y is not None else None,
            "expense_ratio_pct": round(ter, 2) if ter is not None else None,
            "aum_cr":            inv.get("aum_cr"),
            "sharpe":            round(sharpe, 2) if sharpe is not None else None,
            "std_dev_pct":       round(std, 2) if std is not None else None,
        })

    rows.sort(key=lambda r: r["amount_rs"], reverse=True)

    overlap_rows: List[Dict[str, Any]] = []
    for p in sorted(pairs, key=lambda x: x.get("overlap_pct", 0), reverse=True):
        overlap_rows.append({
            "fund_a":       p.get("a_name") or p.get("a", ""),
            "fund_b":       p.get("b_name") or p.get("b", ""),
            "overlap_pct":  round(float(p.get("overlap_pct") or 0), 1),
            "shared_count": p.get("shared_count") or 0,
        })
    high_overlap = [o for o in overlap_rows if o["overlap_pct"] >= 40]

    # Build LLM-readable summary: top 10 funds (multi-line) + top 3 overlap pairs.
    # We use a multi-line block so the LLM has verbatim figures to quote.
    fund_lines: List[str] = []
    for r in rows[:10]:
        bits = [f"- {r['scheme_name']}"]
        if r["category"]:
            bits.append(f"({r['category']})")
        metrics = []
        if r["return_1y_pct"] is not None:
            metrics.append(f"1y {r['return_1y_pct']:+.1f}%")
        if r["return_3y_pct"] is not None:
            metrics.append(f"3y {r['return_3y_pct']:+.1f}%")
        if r["return_5y_pct"] is not None:
            metrics.append(f"5y {r['return_5y_pct']:+.1f}%")
        if r["expense_ratio_pct"] is not None:
            metrics.append(f"TER {r['expense_ratio_pct']:.2f}%")
        if r["sharpe"] is not None:
            metrics.append(f"Sharpe {r['sharpe']:.2f}")
        metrics.append(f"₹{r['amount_rs']:,.0f}")
        bits.append(" | ".join(metrics))
        fund_lines.append(" ".join(bits))

    overlap_lines = [
        f"- {o['fund_a']} ↔ {o['fund_b']} {o['overlap_pct']:.0f}%"
        for o in overlap_rows[:5]
    ]

    extras = []
    if len(rows) > 10:
        extras.append(f"(+{len(rows) - 10} more not shown)")
    coverage = (
        f"returns available for {funds_with_returns}/{len(rows)}, "
        f"TER for {funds_with_ter}/{len(rows)}"
    )

    summary = (
        f"{len(rows)} MFs in portfolio ({coverage}); "
        f"{len(high_overlap)} pair(s) ≥40% overlap.\n"
        + "FUNDS:\n" + "\n".join(fund_lines)
        + ("\n" + " ".join(extras) if extras else "")
        + ("\nTOP_OVERLAP:\n" + "\n".join(overlap_lines) if overlap_lines else "")
    )

    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "fund_count":           len(rows),
            "funds_with_returns":   funds_with_returns,
            "funds_with_ter":       funds_with_ter,
            "high_overlap_pairs":   len(high_overlap),
            "overlap_rows":         overlap_rows[:20],
        },
        rows=rows,
    )


# ── Rebalance plan ────────────────────────────────────────────────────────

async def get_rebalance_plan(user_id: str) -> PortfolioResult:
    """Compute equity/debt rebalance actions from current holdings.

    Used for: "Should I rebalance?", "How should I rebalance my portfolio?"
    """
    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    current_value = sum(
        float(h.get("current_value") or h.get("value") or
              float(h.get("current_price") or 0) * float(h.get("quantity") or 0))
        for h in holdings
    )
    if current_value <= 0:
        return PortfolioResult(ok=False, summary="Cannot compute — holdings have no current value", error="no_value")

    equity_val = sum(
        float(h.get("current_value") or float(h.get("current_price") or 0) * float(h.get("quantity") or 0))
        for h in holdings
        if (h.get("asset_class") or h.get("asset_type") or "equity").lower() in ("equity", "stock")
    )
    debt_val = current_value - equity_val
    equity_pct = round(equity_val / current_value * 100, 1)
    debt_pct = round(debt_val / current_value * 100, 1)

    target_equity = 65.0
    target_debt = 35.0
    actions: List[Dict[str, Any]] = []

    if equity_pct > target_equity + 5:
        excess = (equity_pct - target_equity) / 100 * current_value
        actions.append({
            "action": "SELL",
            "asset": "equity",
            "amount_rs": round(excess, -2),
            "current_pct": equity_pct,
            "target_pct": target_equity,
            "reason": f"Equity {equity_pct:.0f}% > target {target_equity:.0f}% — trim excess",
        })
        actions.append({
            "action": "BUY",
            "asset": "debt",
            "amount_rs": round(excess, -2),
            "current_pct": debt_pct,
            "target_pct": target_debt,
            "reason": "Redirect proceeds to short-term debt fund",
        })
    elif equity_pct < target_equity - 5:
        deficit = (target_equity - equity_pct) / 100 * current_value
        actions.append({
            "action": "BUY",
            "asset": "equity",
            "amount_rs": round(deficit, -2),
            "current_pct": equity_pct,
            "target_pct": target_equity,
            "reason": f"Equity {equity_pct:.0f}% < target {target_equity:.0f}% — add to flexi-cap fund",
        })
    else:
        actions.append({
            "action": "HOLD",
            "asset": "all",
            "amount_rs": 0,
            "current_pct": equity_pct,
            "target_pct": target_equity,
            "reason": f"Equity {equity_pct:.0f}% is within ±5pp of target — no rebalance needed",
        })

    # Flag regular-plan MFs for direct-plan switch
    for h in holdings:
        if (h.get("plan_type") or "").lower() == "regular":
            name = h.get("fund_name") or h.get("scheme_name") or h.get("name", "Fund")
            actions.append({
                "action": "SWITCH",
                "asset": name,
                "amount_rs": None,
                "reason": "Switch to Direct plan to save ~0.8% p.a. in expenses",
            })

    summary = (
        f"Portfolio ₹{current_value:,.0f}: equity {equity_pct:.0f}% / debt {debt_pct:.0f}% "
        f"vs target {target_equity:.0f}/{target_debt:.0f}. "
        f"{len(actions)} action(s) suggested."
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "current_value_rs": current_value,
            "equity_pct": equity_pct,
            "debt_pct": debt_pct,
            "target_equity_pct": target_equity,
            "target_debt_pct": target_debt,
        },
        rows=actions,
    )


# ── Tax harvest (FY 2025-26 engine) ──────────────────────────────────────

async def get_tax_harvest_candidates(
    user_id: str,
    *,
    slab_rate: float = 0.30,
) -> PortfolioResult:
    """Tax-loss harvesting via services.tax_engine — the SAME engine the Tax
    dashboard (_tax_composite) uses: loss_harvesting_candidates (FIFO-aware) plus
    ST/LT-offset netting. The previous implementation used a flat
    harvestable_loss x slab_rate estimate, which disagreed with the dashboard
    (e.g. Rs 10,997 vs Rs 22,693). `slab_rate` is kept for signature
    compatibility; canonical equity ST/LT rates are used for net savings.
    """
    from services import tax_engine
    from services.tax_constants import (
        EQUITY_LTCG_EXEMPTION, EQUITY_LTCG_RATE, EQUITY_STCG_RATE,
    )

    enriched = await tax_engine._enriched_holdings(user_id)
    if not enriched:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    # Bucket unrealised GAINS by long/short term (losses handled below).
    lt_gain = st_gain = 0.0
    for h in enriched:
        g = h.get("_gain") or 0.0
        if g <= 0:
            continue
        if tax_engine.classify_holding(h).tier == "LIKELY_LTCG":
            lt_gain += g
        else:  # STCG / UNKNOWN -> conservative short-term bucket
            st_gain += g

    # Harvestable losses (FIFO-aware) -- the exact call the dashboard makes.
    loss_scores = await tax_engine.loss_harvesting_candidates(user_id)
    harvestable_loss = sum(abs(s.gain_rs) for s in loss_scores)

    # Tax saved by offsetting gains with those losses: STCG first (higher rate),
    # then LTCG, each capped at the gains actually available to offset.
    st_offset = min(harvestable_loss, st_gain)
    lt_offset = min(harvestable_loss - st_offset, lt_gain)
    net_saved = round(st_offset * EQUITY_STCG_RATE + lt_offset * EQUITY_LTCG_RATE)

    rows: List[Dict[str, Any]] = [
        {
            "name":       s.name,
            "asset_type": (s.asset_type or "").replace("_", " ").title(),
            "loss_rs":    round(abs(s.gain_rs)),
            "tax_tier":   s.classification.tier,
        }
        for s in loss_scores
    ]
    loss_count = len(loss_scores)
    summary = (
        f"{loss_count} loss position(s); Rs {harvestable_loss:,.0f} harvestable loss "
        f"-> up to Rs {net_saved:,.0f} tax saved by offsetting gains "
        f"(short-term gains Rs {st_gain:,.0f}, long-term gains Rs {lt_gain:,.0f})"
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "harvestable_loss_rs":  round(harvestable_loss),
            "net_tax_saved_rs":     net_saved,
            "loss_position_count":  loss_count,
            "short_term_gain_rs":   round(st_gain),
            "long_term_gain_rs":    round(lt_gain),
            "ltcg_exemption_rs":    EQUITY_LTCG_EXEMPTION,
        },
        rows=rows,
    )


async def get_full_tax_report(
    user_id: str,
    *,
    slab_rate: float = 0.30,
    total_income_rs: float = 0.0,
) -> PortfolioResult:
    """Full FY 2025-26 capital gains report using compute_capital_gains().

    Unlike get_tax_harvest_candidates() (per-holding estimates), this runs the
    complete 10-step pipeline — cross-holding loss set-off, correct ₹1,25,000
    shared exemption, surcharge, cess — giving the actual net tax payable if
    the entire portfolio were exited today.

    Used for: "What is my total capital gains tax this year?",
              "Show me my full tax liability", "Tax report for my portfolio"
    """
    from services.capital_gains_engine import (
        classify_asset, compute_capital_gains, Transaction,
    )
    from datetime import date as _date

    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    transactions: List[Any] = []
    skipped = 0

    for h in holdings:
        try:
            bp  = float(h.get("buy_price") or 0)
            cp  = float(h.get("current_price") or 0)
            qty = float(h.get("quantity") or 0)
            bd_raw = h.get("buy_date") or h.get("purchase_date")

            if bp <= 0 or cp <= 0 or qty <= 0 or not bd_raw:
                skipped += 1
                continue

            from datetime import datetime as _dt
            if isinstance(bd_raw, str):
                bd = _dt.fromisoformat(bd_raw.replace("Z", "+00:00")).date()
            elif isinstance(bd_raw, _dt):
                bd = bd_raw.date()
            else:
                bd = bd_raw

            atype    = h.get("asset_type") or ""
            name     = h.get("fund_name") or h.get("scheme_name") or h.get("name") or ""
            eq_alloc = h.get("equity_allocation_pct")
            fmv      = h.get("fmv_31jan2018")

            category = classify_asset(atype, name, equity_allocation_pct=eq_alloc, acquisition_date=bd)
            transactions.append(Transaction(
                asset_category=category,
                quantity=qty,
                buy_price=bp,
                sell_price=cp,
                buy_date=bd,
                sell_date=_date.today(),
                fmv_31jan2018=float(fmv) if fmv is not None else None,
                name=name,
                holding_id=str(h.get("holding_id") or h.get("id") or ""),
            ))
        except Exception as exc:
            logger.debug("skip holding in full tax report: %s", exc)
            skipped += 1

    if not transactions:
        return PortfolioResult(
            ok=True,
            summary="No valid holdings to compute tax report",
            rows=[],
            data={"skipped": skipped},
        )

    result = compute_capital_gains(
        transactions,
        slab_rate=slab_rate,
        total_income_rs=total_income_rs,
    )
    d = result.to_dict()

    # Per-holding rows from gain_records
    rows = []
    for gr in result.gain_records:
        t = gr.transaction
        rows.append({
            "name":             t.name or "Unknown",
            "asset_category":   t.asset_category.value,
            "gain_type":        "LTCG" if gr.is_long_term else "STCG",
            "capital_gain":     round(gr.gross_gain, 0),
            "holding_days":     gr.holding_days,
            "is_long_term":     gr.is_long_term,
            "is_grandfathered": gr.is_grandfathered,
            "is_exempt":        gr.is_exempt,
            "tax_category":     gr.tax_category,
            "cost_basis":       round(gr.cost_basis, 2),
            "note":             gr.note,
        })

    rows.sort(key=lambda r: -abs(r["capital_gain"]))

    summary = (
        f"Total tax payable if portfolio exited today: ₹{d['net_tax_payable']:,.0f} "
        f"(LTCG ₹{d['ltcg_equity_tax']:,.0f} + STCG ₹{d['stcg_tax']:,.0f} + slab ₹{d['slab_tax']:,.0f}); "
        f"LTCG exemption applied ₹{d['equity_ltcg_exemption']:,.0f}"
    )
    if skipped:
        summary += f"; {skipped} holding(s) skipped (missing price/date data)"

    return PortfolioResult(
        ok=True,
        summary=summary,
        data=d,
        rows=rows,
    )


# ── Stress test ───────────────────────────────────────────────────────────

async def run_stress_test(
    user_id: str,
    scenario: str = "covid_2020",
    custom_equity_drop: Optional[float] = None,
    custom_debt_drop: Optional[float] = None,
) -> PortfolioResult:
    """Simulate portfolio value under a historical or custom crash scenario.

    Used for: "What if market crashes?", "Run a stress test", "COVID scenario",
              "How much would I lose in a 2008-style crash?",
              "What if market falls 20%?"

    Args:
        scenario: "covid_2020" | "gfc_2008" | "rate_shock" | "custom"
        custom_equity_drop: equity drop % (e.g. -20.0) — used when scenario=="custom"
        custom_debt_drop: debt drop % — defaults to 10% of equity drop if not set
    """
    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    if scenario == "custom" and custom_equity_drop is not None:
        eq_drop = float(custom_equity_drop)
        dbt_drop = float(custom_debt_drop) if custom_debt_drop is not None else round(eq_drop * 0.1, 1)
        scen: Dict[str, Any] = {
            "name": f"Custom Scenario ({eq_drop:+.0f}% equity)",
            "equity_drop": eq_drop,
            "debt_drop": dbt_drop,
            "recovery_years": round(abs(eq_drop) / 15, 1),
        }
    else:
        scen = _STRESS_SCENARIOS.get(scenario, _STRESS_SCENARIOS["covid_2020"])

    current_value = 0.0
    stressed_value = 0.0
    rows: List[Dict[str, Any]] = []

    for h in holdings:
        name = h.get("fund_name") or h.get("scheme_name") or h.get("name", "Fund")
        curr = float(
            h.get("current_value") or h.get("value") or
            float(h.get("current_price") or 0) * float(h.get("quantity") or 0)
        )
        asset = (h.get("asset_class") or h.get("asset_type") or "equity").lower()
        drop_pct = scen["equity_drop"] if asset in ("equity", "stock", "mutual_fund", "etf") else scen["debt_drop"]
        stressed = curr * (1 + drop_pct / 100)

        current_value += curr
        stressed_value += stressed
        rows.append({
            "name": name,
            "asset_type": asset,
            "current_rs": round(curr, 0),
            "stressed_rs": round(stressed, 0),
            "loss_rs": round(stressed - curr, 0),
            "drop_pct": drop_pct,
        })

    if current_value <= 0:
        return PortfolioResult(ok=False, summary="Holdings have no current value", error="no_value")

    total_loss = stressed_value - current_value
    total_drop_pct = total_loss / current_value * 100

    rows.sort(key=lambda r: r["loss_rs"])  # worst loss first

    summary = (
        f"Scenario: {scen['name']} — "
        f"portfolio would fall from ₹{current_value:,.0f} to ₹{stressed_value:,.0f} "
        f"({total_drop_pct:+.1f}%, loss ₹{total_loss:,.0f}). "
        f"Historical recovery: ~{scen['recovery_years']:.1f} years."
    )
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "scenario": scen["name"],
            "current_value_rs": round(current_value, 0),
            "stressed_value_rs": round(stressed_value, 0),
            "total_loss_rs": round(total_loss, 0),
            "total_drop_pct": round(total_drop_pct, 2),
            "recovery_years": scen["recovery_years"],
        },
        rows=rows,
    )


# ── FD benchmark comparison ───────────────────────────────────────────────

# Indicative SBI FD rates as of FY 2025-26 (annualised, pre-tax)
_FD_RATES: Dict[str, Dict[str, Any]] = {
    "1y": {"rate": 6.80, "label": "SBI 1-Year FD", "tax_note": "Interest taxed as income"},
    "3y": {"rate": 7.00, "label": "SBI 3-Year FD", "tax_note": "Interest taxed as income"},
    "5y": {"rate": 6.50, "label": "SBI 5-Year FD (tax-saving)", "tax_note": "Interest taxed as income; principal 80C eligible"},
}

# Post-tax FD yield assuming 30% income-tax slab (conservative estimate for comparison)
_FD_POST_TAX_RATE_PCT = 0.70  # 1 − 30% slab


async def get_fd_comparison(user_id: str) -> PortfolioResult:
    """Compare portfolio XIRR against FD reference rates.

    Used for: "Am I beating FD?", "Is my portfolio better than fixed deposit?",
              "How does my return compare to FD rates?", "FD vs my portfolio"
    """
    xirr_result = await get_portfolio_xirr(user_id)
    if not xirr_result.ok:
        return xirr_result

    portfolio_xirr = xirr_result.data.get("portfolio_xirr_pct")
    portfolio_abs_ret = xirr_result.data.get("portfolio_return_pct")
    total_invested = xirr_result.data.get("total_invested_rs", 0)
    total_current = xirr_result.data.get("total_current_rs", 0)

    # Use XIRR if available; fall back to absolute return for comparison
    portfolio_rate = portfolio_xirr if portfolio_xirr is not None else portfolio_abs_ret or 0.0

    rows: List[Dict[str, Any]] = []
    for tenure, fd in _FD_RATES.items():
        fd_gross = fd["rate"]
        fd_post_tax = round(fd_gross * _FD_POST_TAX_RATE_PCT, 2)
        diff_gross = round(portfolio_rate - fd_gross, 2)
        diff_post_tax = round(portfolio_rate - fd_post_tax, 2)
        rows.append({
            "label": fd["label"],
            "tenure": tenure,
            "fd_gross_pct": fd_gross,
            "fd_post_tax_pct": fd_post_tax,
            "portfolio_xirr_pct": round(portfolio_rate, 2),
            "outperformance_gross_pp": diff_gross,
            "outperformance_post_tax_pp": diff_post_tax,
            "verdict": (
                "Beating FD" if diff_gross > 0 else
                "Trailing FD"
            ),
        })

    best_fd_gross = max(r["fd_gross_pct"] for r in rows)
    best_fd_post_tax = max(r["fd_post_tax_pct"] for r in rows)
    diff = round(portfolio_rate - best_fd_gross, 2)

    if portfolio_rate > best_fd_gross:
        verdict = f"Your portfolio XIRR of {portfolio_rate:+.1f}% beats the best FD rate ({best_fd_gross:.1f}%) by {diff:+.1f} pp."
    else:
        verdict = (
            f"Your portfolio XIRR of {portfolio_rate:+.1f}% trails the best FD rate ({best_fd_gross:.1f}%) "
            f"by {abs(diff):.1f} pp. FD would give ₹{total_invested * (1 + best_fd_gross/100):,.0f} after 1 year."
        )

    # Post-tax note for equity (LTCG 12.5% above ₹1.25L, vs 30% on FD interest)
    post_tax_note = (
        f"Post-tax edge: equity LTCG is taxed at 12.5% vs FD interest at your income-tax slab. "
        f"After tax, FD effective yield ≈ {best_fd_post_tax:.1f}% — your {portfolio_rate:+.1f}% XIRR "
        + ("has a further tax advantage." if portfolio_rate > best_fd_post_tax else "is still trailing.")
    )

    summary = f"{verdict} {post_tax_note}"
    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "portfolio_xirr_pct": round(portfolio_rate, 2),
            "portfolio_abs_return_pct": round(portfolio_abs_ret or 0, 2),
            "total_invested_rs": total_invested,
            "total_current_rs": total_current,
            "best_fd_gross_pct": best_fd_gross,
            "best_fd_post_tax_pct": best_fd_post_tax,
            "outperformance_pp": diff,
            "verdict": "beats_fd" if diff > 0 else "trails_fd",
            "note": "FD rates are indicative (SBI, FY 2025-26). Portfolio returns are not guaranteed.",
        },
        rows=rows,
    )


# ── Tax timing optimisation ───────────────────────────────────────────────

_EQUITY_LTCG_DAYS = 365     # >365 days → LTCG for equity/MF
_DEBT_LTCG_DAYS   = 1095    # >3 years → LTCG for debt (pre-Apr 2023 purchases)
_EQUITY_STCG_RATE = 0.20    # 20% STCG on equity (post-Jul 2024 budget)
_EQUITY_LTCG_RATE = 0.125   # 12.5% LTCG on equity above ₹1.25L exemption
_DEBT_INCOME_RATE = 0.30    # Debt capital gains taxed as income


async def get_tax_timing_advice(user_id: str) -> PortfolioResult:
    """Identify holdings where waiting for LTCG classification saves tax.

    Used for: "When should I sell to minimise tax?",
              "Which holdings should I wait to sell?",
              "Am I close to becoming long-term?", "Tax timing advice"

    Shows:
      - Holdings currently STCG that flip to LTCG within 90 days
      - Estimated tax saving from waiting
      - Holdings where selling NOW saves tax (large STCG losses to harvest)
    """
    from datetime import date as _date, datetime as _dt

    holdings = await _load_holdings(user_id)
    if not holdings:
        return PortfolioResult(ok=False, summary="No holdings found", error="no_holdings")

    today = _date.today()
    rows: List[Dict[str, Any]] = []
    sell_now_saves: List[Dict[str, Any]] = []

    for h in holdings:
        try:
            bp  = float(h.get("buy_price") or 0)
            cp  = float(h.get("current_price") or 0)
            qty = float(h.get("quantity") or 0)
            bd_raw = h.get("buy_date") or h.get("purchase_date")

            if bp <= 0 or cp <= 0 or qty <= 0 or not bd_raw:
                continue

            if isinstance(bd_raw, str):
                bd = _dt.fromisoformat(bd_raw.replace("Z", "+00:00")).date()
            elif isinstance(bd_raw, _dt):
                bd = bd_raw.date()
            else:
                bd = bd_raw

            name   = h.get("fund_name") or h.get("scheme_name") or h.get("name") or "Unknown"
            atype  = (h.get("asset_type") or "equity").lower()
            gain   = (cp - bp) * qty
            invested = bp * qty

            if invested <= 0:
                continue

            days_held = (today - bd).days
            is_equity = atype in ("equity", "stock", "mutual_fund", "etf")
            ltcg_days = _EQUITY_LTCG_DAYS if is_equity else _DEBT_LTCG_DAYS

            is_ltcg = days_held >= ltcg_days
            days_to_ltcg = max(0, ltcg_days - days_held)

            if is_equity:
                current_tax = gain * _EQUITY_LTCG_RATE if is_ltcg else gain * _EQUITY_STCG_RATE
                ltcg_tax = gain * _EQUITY_LTCG_RATE  # tax after LTCG threshold reached
            else:
                current_tax = gain * _DEBT_INCOME_RATE  # always income for debt post Apr 2023
                ltcg_tax = gain * _DEBT_INCOME_RATE

            tax_saving = current_tax - ltcg_tax if not is_ltcg else 0.0
            row = {
                "name": name,
                "asset_type": atype,
                "gain_rs": round(gain, 0),
                "days_held": days_held,
                "is_ltcg": is_ltcg,
                "days_to_ltcg": days_to_ltcg,
                "current_tax_estimate_rs": round(max(0, current_tax), 0),
                "ltcg_tax_estimate_rs": round(max(0, ltcg_tax), 0),
                "tax_saving_if_wait_rs": round(max(0, tax_saving), 0),
            }

            if not is_ltcg and gain > 0 and days_to_ltcg <= 90:
                rows.append(row)   # close to flipping — worth waiting
            elif gain < 0 and not is_ltcg:
                sell_now_saves.append(row)   # loss — harvest now

        except Exception as exc:
            logger.debug("tax_timing skip: %s", exc)

    rows.sort(key=lambda r: r["tax_saving_if_wait_rs"], reverse=True)
    all_rows = rows + sell_now_saves

    if not all_rows:
        return PortfolioResult(
            ok=True,
            summary="No STCG-to-LTCG conversion opportunities within 90 days. Your holdings are either already long-term or have no significant gains.",
            rows=[],
            data={"opportunities": 0},
        )

    total_saving = sum(r["tax_saving_if_wait_rs"] for r in rows)
    summary = (
        f"Found {len(rows)} holding(s) that flip LTCG within 90 days, "
        f"saving ~₹{total_saving:,.0f} in tax if you wait. "
        + (f"{len(sell_now_saves)} loss position(s) worth harvesting now." if sell_now_saves else "")
    )

    return PortfolioResult(
        ok=True,
        summary=summary,
        data={
            "ltcg_flip_count": len(rows),
            "harvest_count": len(sell_now_saves),
            "total_tax_saving_if_wait_rs": round(total_saving, 0),
        },
        rows=all_rows,
    )
