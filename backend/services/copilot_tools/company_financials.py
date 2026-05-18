"""Company financials tool for the Nivesh Copilot.

Provides multi-quarter P&L trends, balance sheet snapshot, shareholding
changes, and a data-driven "future prospects" signal.

Functions:
  get_company_financials   — 8-quarter revenue/PAT/EPS/EBITDA trend
  get_shareholding_analysis — promoter/FII/DII flow signals
  get_company_overview     — comprehensive snapshot (financials + shareholding + V3)

Data sources:
  NIDP DAAS /v1/financials/{symbol}       — quarterly P&L + balance sheet
  NIDP DAAS /v1/shareholding/{symbol}     — shareholding pattern history
  NIDP DAAS /v1/features/stocks/{symbol}/latest — derived metrics (PE, Piotroski, etc.)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompanyResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        lines = [f"COMPANY_FINANCIALS symbol={self.data.get('symbol','?')} {self.summary}"]
        for r in self.rows[:8]:
            q = r.get("quarter", "")
            rev = r.get("revenue_cr")
            pat = r.get("pat_cr")
            eps = r.get("eps_basic")
            rev_yoy = r.get("revenue_yoy_pct")
            pat_yoy = r.get("pat_yoy_pct")
            margin = r.get("ebitda_margin_pct")
            parts = [f"Q={q}"]
            if rev is not None:
                parts.append(f"rev=₹{rev:.0f}cr")
            if pat is not None:
                parts.append(f"PAT=₹{pat:.0f}cr")
            if eps is not None:
                parts.append(f"EPS={eps:.2f}")
            if rev_yoy is not None:
                parts.append(f"rev_yoy={rev_yoy:+.1f}%")
            if pat_yoy is not None:
                parts.append(f"pat_yoy={pat_yoy:+.1f}%")
            if margin is not None:
                parts.append(f"ebitda_margin={margin:.1f}%")
            lines.append("  " + " ".join(parts))
        return "\n".join(lines)


def _quarter_label(period_end: str) -> str:
    """Convert '2025-12-31' → 'Q3 FY26'."""
    try:
        d = date.fromisoformat(str(period_end)[:10])
        # Indian FY: Apr–Jun = Q1, Jul–Sep = Q2, Oct–Dec = Q3, Jan–Mar = Q4
        month = d.month
        fy_year = d.year if month >= 4 else d.year - 1
        quarter = {1: 4, 2: 4, 3: 4, 4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3}[month]
        return f"Q{quarter} FY{str(fy_year + 1)[-2:]}"
    except Exception:
        return str(period_end)[:7]


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


async def get_company_financials(symbol: str, limit: int = 8) -> CompanyResult:
    """Multi-quarter P&L trend: revenue, PAT, EPS, EBITDA margins, YoY growth.

    Used for: "Show me RELIANCE quarterly results", "How have earnings been?",
              "Revenue trend for TCS", "Quarterly financials", "Financial results"
    """
    from .daas_client import get_quarterly_financials, DaasError

    sym = symbol.strip().upper()
    try:
        raw_rows = await get_quarterly_financials(sym, limit=limit, consolidated=True)
        # If consolidated returns nothing, try standalone
        if not raw_rows:
            raw_rows = await get_quarterly_financials(sym, limit=limit, consolidated=False)
    except DaasError as exc:
        return CompanyResult(ok=False, summary=f"Financial data unavailable: {exc}", error=str(exc))

    if not raw_rows:
        return CompanyResult(
            ok=False,
            summary=f"No quarterly financials found for {sym}. Data may not be available yet.",
            error="no_data",
        )

    # raw_rows are newest-first; build enriched rows
    rows: List[Dict[str, Any]] = []
    # Build a period_end → row map for YoY lookup (same quarter, prior year)
    period_map: Dict[str, Dict[str, Any]] = {str(r.get("period_end", ""))[:10]: r for r in raw_rows}

    for r in raw_rows:
        period_end = str(r.get("period_end", ""))[:10]
        quarter = _quarter_label(period_end)

        rev   = _safe_float(r.get("revenue_from_ops_cr"))
        pat   = _safe_float(r.get("pat_cr") or r.get("pat_attrib_owners_cr"))
        ebitda = _safe_float(r.get("ebitda_cr"))
        pbt   = _safe_float(r.get("pbt_cr"))
        eps   = _safe_float(r.get("eps_basic") or r.get("eps_diluted"))
        cash  = _safe_float(r.get("cash_and_equiv_cr"))
        lt_debt = _safe_float(r.get("long_term_debt_cr"))
        st_debt = _safe_float(r.get("short_term_debt_cr"))
        equity  = _safe_float(r.get("total_equity_cr"))
        fin_cost = _safe_float(r.get("finance_costs_cr"))
        depr = _safe_float(r.get("depreciation_cr"))

        # EBITDA margin
        ebitda_margin = round(ebitda / rev * 100, 1) if ebitda and rev and rev > 0 else None
        pat_margin    = round(pat / rev * 100, 1) if pat and rev and rev > 0 else None

        # YoY: look up the same quarter one year prior
        try:
            prior_date = date.fromisoformat(period_end) - _year_delta(period_end)
            prior_key = str(prior_date)[:10]
        except Exception:
            prior_key = None

        prior = period_map.get(prior_key) if prior_key else None
        rev_yoy = pat_yoy = eps_yoy = None
        if prior:
            prior_rev = _safe_float(prior.get("revenue_from_ops_cr"))
            prior_pat = _safe_float(prior.get("pat_cr") or prior.get("pat_attrib_owners_cr"))
            prior_eps = _safe_float(prior.get("eps_basic") or prior.get("eps_diluted"))
            if rev and prior_rev and prior_rev != 0:
                rev_yoy = round((rev - prior_rev) / abs(prior_rev) * 100, 1)
            if pat and prior_pat and prior_pat != 0:
                pat_yoy = round((pat - prior_pat) / abs(prior_pat) * 100, 1)
            if eps and prior_eps and prior_eps != 0:
                eps_yoy = round((eps - prior_eps) / abs(prior_eps) * 100, 1)

        total_debt = (lt_debt or 0) + (st_debt or 0)
        net_debt   = total_debt - (cash or 0)

        rows.append({
            "quarter":           quarter,
            "period_end":        period_end,
            "revenue_cr":        rev,
            "pat_cr":            pat,
            "ebitda_cr":         ebitda,
            "pbt_cr":            pbt,
            "eps_basic":         eps,
            "ebitda_margin_pct": ebitda_margin,
            "pat_margin_pct":    pat_margin,
            "revenue_yoy_pct":   rev_yoy,
            "pat_yoy_pct":       pat_yoy,
            "eps_yoy_pct":       eps_yoy,
            "total_debt_cr":     round(total_debt, 1) if total_debt else None,
            "net_debt_cr":       round(net_debt, 1) if total_debt is not None else None,
            "cash_cr":           cash,
            "equity_cr":         equity,
            "finance_costs_cr":  fin_cost,
            "depreciation_cr":   depr,
        })

    # Growth trend signal (using 4 most-recent quarters)
    recent = [r for r in rows[:4] if r["revenue_yoy_pct"] is not None]
    trend_signal = "insufficient data"
    if len(recent) >= 2:
        latest_growth = recent[0]["revenue_yoy_pct"]
        older_growth  = recent[-1]["revenue_yoy_pct"]
        if latest_growth is None or older_growth is None:
            trend_signal = "mixed"
        elif latest_growth > older_growth + 3:
            trend_signal = "accelerating"
        elif latest_growth < older_growth - 3:
            trend_signal = "decelerating"
        elif latest_growth > 0:
            trend_signal = "steady growth"
        else:
            trend_signal = "declining"

    latest = rows[0] if rows else {}
    summary_parts = [f"{sym} — {len(rows)} quarters of data."]
    if latest.get("revenue_cr"):
        summary_parts.append(f"Latest revenue ₹{latest['revenue_cr']:.0f}cr")
    if latest.get("pat_cr"):
        summary_parts.append(f"PAT ₹{latest['pat_cr']:.0f}cr")
    if latest.get("ebitda_margin_pct") is not None:
        summary_parts.append(f"EBITDA margin {latest['ebitda_margin_pct']:.1f}%")
    if latest.get("revenue_yoy_pct") is not None:
        summary_parts.append(f"Rev YoY {latest['revenue_yoy_pct']:+.1f}%")
    summary_parts.append(f"Growth trend: {trend_signal}.")

    return CompanyResult(
        ok=True,
        summary=" ".join(summary_parts),
        data={
            "symbol":         sym,
            "quarters_count": len(rows),
            "growth_trend":   trend_signal,
            "latest_quarter": rows[0].get("quarter") if rows else None,
            "note": "No analyst estimates or management guidance available. Figures are from exchange filings.",
        },
        rows=rows,
    )


def _year_delta(period_end: str):
    """Approximate timedelta for same quarter prior year."""
    from datetime import timedelta
    return timedelta(days=365)


async def get_shareholding_analysis(symbol: str) -> CompanyResult:
    """Shareholding pattern trend: promoter/FII/DII/MF changes + pledge trend.

    Used for: "Who is buying this stock?", "Is FII selling?", "Promoter pledging?",
              "Shareholding changes", "Institutional holding trend"
    """
    from .daas_client import get_shareholding_history, DaasError

    sym = symbol.strip().upper()
    try:
        raw_rows = await get_shareholding_history(sym, limit=5)
    except DaasError as exc:
        return CompanyResult(ok=False, summary=f"Shareholding data unavailable: {exc}", error=str(exc))

    if not raw_rows:
        return CompanyResult(
            ok=False,
            summary=f"No shareholding data found for {sym}.",
            error="no_data",
        )

    rows: List[Dict[str, Any]] = []
    for r in raw_rows:
        period_end = str(r.get("period_end", ""))[:10]
        rows.append({
            "period":               _quarter_label(period_end),
            "period_end":           period_end,
            "promoter_pct":         _safe_float(r.get("promoter_pct")),
            "promoter_pledged_pct": _safe_float(r.get("promoter_pledged_pct")),
            "fii_pct":              _safe_float(r.get("fii_pct")),
            "dii_pct":              _safe_float(r.get("dii_pct")),
            "mf_pct":               _safe_float(r.get("mf_pct")),
            "public_pct":           _safe_float(r.get("public_pct")),
            "fii_change_qoq":       _safe_float(r.get("fii_pct_change_qoq")),
            "dii_change_qoq":       _safe_float(r.get("dii_pct_change_qoq")),
            "promoter_change_qoq":  _safe_float(r.get("promoter_pct_change_qoq")),
            "mf_change_qoq":        _safe_float(r.get("mf_pct_change_qoq")),
            "pledge_change_qoq":    _safe_float(r.get("pledge_pct_change_qoq")),
        })

    latest = rows[0] if rows else {}
    signals: List[str] = []

    fii_chg = latest.get("fii_change_qoq")
    dii_chg = latest.get("dii_change_qoq")
    pledge  = latest.get("promoter_pledged_pct") or 0
    pledge_chg = latest.get("pledge_change_qoq") or 0
    promoter_pct = latest.get("promoter_pct") or 0

    if fii_chg is not None:
        signals.append(f"FIIs {'buying (+' if fii_chg > 0 else 'selling ('}{abs(fii_chg):.2f}pp QoQ)")
    if dii_chg is not None:
        signals.append(f"DIIs {'increasing (+' if dii_chg > 0 else 'decreasing ('}{abs(dii_chg):.2f}pp QoQ)")
    if pledge > 20:
        signals.append(f"HIGH pledge: {pledge:.1f}% promoter shares pledged")
    elif pledge > 0:
        signals.append(f"Pledge: {pledge:.1f}% of promoter shares")
    if pledge_chg > 1:
        signals.append(f"Pledge RISING +{pledge_chg:.1f}pp — watch carefully")
    elif pledge_chg < -1:
        signals.append(f"Pledge falling {pledge_chg:.1f}pp — positive signal")

    summary = (
        f"{sym} shareholding ({latest.get('period','latest')}): "
        f"Promoter {promoter_pct:.1f}%, FII {latest.get('fii_pct', 0) or 0:.1f}%, "
        f"DII {latest.get('dii_pct', 0) or 0:.1f}%. "
        + " ".join(signals)
    )

    return CompanyResult(
        ok=True,
        summary=summary,
        data={
            "symbol":              sym,
            "periods_available":   len(rows),
            "latest_period":       latest.get("period"),
            "promoter_pct":        latest.get("promoter_pct"),
            "fii_pct":             latest.get("fii_pct"),
            "dii_pct":             latest.get("dii_pct"),
            "mf_pct":              latest.get("mf_pct"),
            "pledged_pct":         latest.get("promoter_pledged_pct"),
            "fii_trend":           "buying" if (fii_chg or 0) > 0 else "selling" if (fii_chg or 0) < 0 else "stable",
            "pledge_risk":         "high" if pledge > 20 else "medium" if pledge > 10 else "low",
        },
        rows=rows,
    )


async def get_company_overview(symbol: str) -> CompanyResult:
    """Full company snapshot: financials + shareholding + V3 score + prospects signal.

    Used for: "Tell me about RELIANCE", "Full analysis of TCS",
              "Company overview", "Future prospects of INFY",
              "Is [company] a good investment?"
    """
    import asyncio
    from .daas_client import get_stock_features_latest, DaasError

    sym = symbol.strip().upper()

    # Fire all three fetches concurrently
    fin_task  = asyncio.create_task(get_company_financials(sym, limit=8))
    shr_task  = asyncio.create_task(get_shareholding_analysis(sym))

    try:
        features = await get_stock_features_latest(sym)
    except DaasError:
        features = None

    fin_result = await fin_task
    shr_result = await shr_task

    # Build composite prospects signal
    signals: List[str] = []
    outlook_score = 0  # -5 to +5

    # --- Growth momentum ---
    trend = fin_result.data.get("growth_trend", "")
    if trend == "accelerating":
        signals.append("Revenue growth accelerating — positive momentum")
        outlook_score += 2
    elif trend == "steady growth":
        signals.append("Steady revenue growth")
        outlook_score += 1
    elif trend == "decelerating":
        signals.append("Revenue growth slowing — watch earnings")
        outlook_score -= 1
    elif trend == "declining":
        signals.append("Revenue decline — negative near-term signal")
        outlook_score -= 2

    # --- Shareholding signals ---
    fii_trend = shr_result.data.get("fii_trend", "stable")
    if fii_trend == "buying":
        signals.append("FIIs increasing stake — institutional confidence")
        outlook_score += 1
    elif fii_trend == "selling":
        signals.append("FIIs reducing stake — watch for continued outflows")
        outlook_score -= 1

    pledge_risk = shr_result.data.get("pledge_risk", "low")
    if pledge_risk == "high":
        signals.append("High promoter pledge — key risk")
        outlook_score -= 1

    # --- V3 quality / score ---
    if features:
        piotroski = features.get("piotroski_score")
        altman    = features.get("altman_z_score")
        val_sig   = features.get("valuation_signal", "")
        momentum  = features.get("momentum_score")
        pat_trend = features.get("pat_growth_yoy_pct")
        margin_trend = features.get("profit_margin_trend_pct")

        if piotroski is not None:
            if piotroski >= 7:
                signals.append(f"Piotroski {piotroski}/9 — strong financial health")
                outlook_score += 1
            elif piotroski <= 3:
                signals.append(f"Piotroski {piotroski}/9 — weak fundamentals")
                outlook_score -= 1

        if altman is not None:
            if altman >= 3.0:
                signals.append(f"Altman Z {altman:.2f} — safe zone (low distress risk)")
            elif altman < 1.81:
                signals.append(f"Altman Z {altman:.2f} — distress zone")
                outlook_score -= 1

        if val_sig == "undervalued":
            signals.append("Trading at discount to sector peers")
            outlook_score += 1
        elif val_sig == "overvalued":
            signals.append("Trading at premium to sector peers")
            outlook_score -= 1

        if momentum is not None and momentum >= 70:
            signals.append(f"Strong price momentum ({momentum:.0f}/100)")
            outlook_score += 1

        if margin_trend is not None:
            if margin_trend > 1.0:
                signals.append(f"EBITDA margins expanding (+{margin_trend:.1f}pp YoY)")
                outlook_score += 1
            elif margin_trend < -1.0:
                signals.append(f"Margins contracting ({margin_trend:.1f}pp YoY) — cost pressure")
                outlook_score -= 1

    outlook_label = (
        "Strong positive" if outlook_score >= 3 else
        "Moderately positive" if outlook_score >= 1 else
        "Neutral" if outlook_score == 0 else
        "Moderately cautious" if outlook_score >= -2 else
        "Cautious"
    )

    all_rows = fin_result.rows + [{"_type": "shareholding", **r} for r in shr_result.rows]

    combined_data: Dict[str, Any] = {
        "symbol":            sym,
        "growth_trend":      trend,
        "outlook_label":     outlook_label,
        "outlook_score":     outlook_score,
        "key_signals":       signals[:5],
        "financials":        fin_result.data,
        "shareholding":      shr_result.data,
        "disclaimer": (
            "No analyst estimates or forward guidance available. "
            "Outlook is data-driven from historical filings, shareholding changes, "
            "and NIDP technical/fundamental scores — not a buy/sell recommendation."
        ),
    }
    if features:
        combined_data["v3_score"] = {
            "pe_ttm":          features.get("pe_ttm"),
            "pb":              features.get("pb"),
            "roe_pct":         features.get("roe_pct"),
            "debt_to_equity":  features.get("debt_to_equity"),
            "piotroski_score": features.get("piotroski_score"),
            "altman_z_score":  features.get("altman_z_score"),
            "valuation_signal":features.get("valuation_signal"),
            "momentum_score":  features.get("momentum_score"),
            "market_cap_cr":   features.get("market_cap_cr"),
            "market_cap_bucket": features.get("market_cap_bucket"),
        }

    summary = (
        f"{sym} overview: {outlook_label} outlook (score {outlook_score:+d}). "
        f"Growth: {trend}. "
        + (" | ".join(signals[:3]) if signals else "Insufficient data for forward signals.")
    )

    return CompanyResult(
        ok=fin_result.ok or shr_result.ok,
        summary=summary,
        data=combined_data,
        rows=all_rows,
    )
