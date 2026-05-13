"""Pure-Python fundamental indicator computations.

Inputs are lists of quarterly financial dicts (oldest-first), each
containing fields from nidp.nse_financials_quarterly plus derived
fields from v_stock_fundamentals_latest.

No external dependencies — importable anywhere for unit testing.
"""
from __future__ import annotations

from typing import Optional


# ── Helpers ──────────────────────────────────────────────────────────

def _f(val) -> Optional[float]:
    """Safe float conversion; returns None for None/zero-length."""
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _safe_div(num, den) -> Optional[float]:
    n, d = _f(num), _f(den)
    if n is None or d is None or d == 0:
        return None
    return n / d


# ── Piotroski F-Score ────────────────────────────────────────────────
# Modified for NSE XBRL data: CFO-based signals replaced with
# EBITDA and margin proxies (cash flow statements rarely filed separately).
#
# Signals (each = 1 point if True):
#  Profitability (4)
#  F1  ROA positive: PAT > 0
#  F2  ROA improving: PAT growth YoY > 0
#  F3  Cash quality: EBITDA > 0 (operating profit proxy)
#  F4  Revenue quality: revenue growth YoY > 0
#
#  Leverage / Liquidity (3)
#  F5  D/E decreasing: total_debt / equity dropped vs prior year
#  F6  Liquidity: cash_and_equiv / short_term_debt improved vs prior year
#  F7  No dilution: EPS did not shrink vs prior year
#
#  Operating efficiency (2)
#  F8  EBITDA margin improved vs prior year
#  F9  Revenue per equity (asset turnover proxy) improved vs prior year

def compute_piotroski(
    latest: dict,
    prior: Optional[dict],
) -> tuple[int, list[str]]:
    """Compute Piotroski F-Score (0-9) from financial dicts.

    Args:
        latest: most recent quarter's financial data
        prior:  same quarter prior year (or None if unavailable)

    Returns:
        (score, signal_list) where signal_list names the fired signals.
    """
    score = 0
    signals: list[str] = []

    pat = _f(latest.get("pat_cr"))
    ebitda = _f(latest.get("ebitda_cr"))
    revenue = _f(latest.get("revenue_from_ops_cr"))
    equity = _f(latest.get("total_equity_cr"))
    lt_debt = _f(latest.get("long_term_debt_cr")) or 0.0
    st_debt = _f(latest.get("short_term_debt_cr")) or 0.0
    cash = _f(latest.get("cash_and_equiv_cr"))
    eps = _f(latest.get("eps_basic"))

    # ── Profitability ─────────────────────────────────────────────────
    # F1: ROA positive
    if pat is not None and pat > 0:
        score += 1
        signals.append("F1_roa_positive")

    # F3: EBITDA > 0
    if ebitda is not None and ebitda > 0:
        score += 1
        signals.append("F3_ebitda_positive")

    if prior is not None:
        pat_prior = _f(prior.get("pat_cr"))
        equity_prior = _f(prior.get("total_equity_cr"))
        revenue_prior = _f(prior.get("revenue_from_ops_cr"))
        ebitda_prior = _f(prior.get("ebitda_cr"))
        lt_debt_prior = _f(prior.get("long_term_debt_cr")) or 0.0
        st_debt_prior = _f(prior.get("short_term_debt_cr")) or 0.0
        cash_prior = _f(prior.get("cash_and_equiv_cr"))
        eps_prior = _f(prior.get("eps_basic"))

        # F2: ROA improving (PAT/equity improving as ROA proxy)
        roa_cur = _safe_div(pat, equity)
        roa_prior = _safe_div(pat_prior, equity_prior)
        if roa_cur is not None and roa_prior is not None and roa_cur > roa_prior:
            score += 1
            signals.append("F2_roa_improving")

        # F4: Revenue growth
        if revenue is not None and revenue_prior is not None and revenue_prior > 0:
            if revenue > revenue_prior:
                score += 1
                signals.append("F4_revenue_growth")

        # F5: D/E decreasing
        total_debt = lt_debt + st_debt
        total_debt_prior = lt_debt_prior + st_debt_prior
        de_cur = _safe_div(total_debt, equity)
        de_prior = _safe_div(total_debt_prior, equity_prior)
        if de_cur is not None and de_prior is not None and de_cur < de_prior:
            score += 1
            signals.append("F5_leverage_down")

        # F6: Liquidity improved (cash / short_term_debt)
        liq_cur = _safe_div(cash, st_debt) if st_debt and st_debt > 0 else _f(cash)
        liq_prior = _safe_div(cash_prior, st_debt_prior) if st_debt_prior and st_debt_prior > 0 else _f(cash_prior)
        if liq_cur is not None and liq_prior is not None and liq_cur > liq_prior:
            score += 1
            signals.append("F6_liquidity_up")

        # F7: EPS not declining (no dilution signal)
        if eps is not None and eps_prior is not None and eps >= eps_prior:
            score += 1
            signals.append("F7_eps_nodilution")

        # F8: EBITDA margin improved
        margin_cur = _safe_div(ebitda, revenue)
        margin_prior = _safe_div(ebitda_prior, revenue_prior)
        if margin_cur is not None and margin_prior is not None and margin_cur > margin_prior:
            score += 1
            signals.append("F8_margin_up")

        # F9: Revenue / equity (asset turnover proxy) improved
        turnover_cur = _safe_div(revenue, equity)
        turnover_prior = _safe_div(revenue_prior, equity_prior)
        if turnover_cur is not None and turnover_prior is not None and turnover_cur > turnover_prior:
            score += 1
            signals.append("F9_turnover_up")

    return score, signals


def piotroski_label(score: int) -> str:
    if score >= 8:
        return "strong"
    if score >= 6:
        return "good"
    if score >= 3:
        return "average"
    return "weak"


# ── Altman Z-Score (modified for NSE XBRL) ───────────────────────────
# Original: Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
#
# X1 = Working Capital / Total Assets
#      ← (cash - short_term_debt) / total_capital  [proxy]
# X2 = Retained Earnings / Total Assets
#      ← total_equity / total_capital               [proxy]
# X3 = EBIT / Total Assets
#      ← (pat + finance_costs + depreciation) / total_capital  [proxy]
# X4 = Market Cap / Total Liabilities
#      ← market_cap_cr / total_debt                 [direct if price known]
# X5 = Revenue / Total Assets
#      ← revenue_ttm / total_capital                [proxy]
#
# total_capital = equity + long_term_debt + short_term_debt
# market_cap_cr = close_price * shares_outstanding_cr
#   where shares_outstanding_cr ≈ pat_cr / eps_basic * face_value / 10

def compute_altman_z(
    latest: dict,
    close_price: Optional[float] = None,
) -> Optional[float]:
    """Compute modified Altman Z-Score.

    Returns Z value or None if insufficient data.
    Interpretation:
      Z > 2.99  → safe zone
      1.81–2.99 → grey zone
      Z < 1.81  → distress zone
    """
    equity = _f(latest.get("total_equity_cr"))
    lt_debt = _f(latest.get("long_term_debt_cr")) or 0.0
    st_debt = _f(latest.get("short_term_debt_cr")) or 0.0
    cash = _f(latest.get("cash_and_equiv_cr")) or 0.0
    pat = _f(latest.get("pat_cr"))
    finance_costs = _f(latest.get("finance_costs_cr")) or 0.0
    depreciation = _f(latest.get("depreciation_cr")) or 0.0
    revenue_ttm = _f(latest.get("revenue_ttm_cr")) or _f(latest.get("revenue_from_ops_cr"))
    eps = _f(latest.get("eps_basic"))
    face_value = _f(latest.get("face_value")) or 10.0

    if equity is None or equity <= 0:
        return None
    if pat is None:
        return None

    total_debt = lt_debt + st_debt
    total_capital = equity + total_debt
    if total_capital <= 0:
        return None

    # X1: Working capital proxy
    x1 = (cash - st_debt) / total_capital

    # X2: Equity / total capital (retained earnings proxy)
    x2 = equity / total_capital

    # X3: EBIT / total capital (annualise quarterly by ×4)
    ebit_quarterly = pat + finance_costs + depreciation
    x3 = (ebit_quarterly * 4) / total_capital

    # X4: Market cap / total debt
    x4 = 0.0
    if close_price and close_price > 0 and eps and eps != 0:
        # Shares outstanding in crores: PAT_cr / (EPS per share)
        # EPS per share unit: Rs per share of face_value
        # shares_cr = pat_cr (crores) * 10^7 / eps_per_share
        # market_cap_cr = close * shares_cr / 10^7 = close * pat_cr / eps_per_share
        market_cap_cr = close_price * pat / eps if eps != 0 else 0.0
        if total_debt > 0:
            x4 = market_cap_cr / total_debt
        else:
            x4 = 10.0  # debt-free: very safe

    # X5: Revenue / total capital (annualise quarterly by ×4)
    if revenue_ttm is None:
        return None
    # TTM revenue is already annual; quarterly revenue needs ×4
    # The view provides revenue_ttm_cr when 4 quarters exist
    rev = revenue_ttm if latest.get("revenue_ttm_cr") else (revenue_ttm * 4)
    x5 = rev / total_capital

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    return round(float(z), 4)


def altman_label(z: Optional[float]) -> str:
    if z is None:
        return "unknown"
    if z > 2.99:
        return "safe"
    if z > 1.81:
        return "grey"
    return "distress"


# ── Valuation signal ──────────────────────────────────────────────────

def valuation_signal(pe_ttm: Optional[float], sector_median_pe: Optional[float]) -> Optional[str]:
    """Classify stock as undervalued / fairly_valued / overvalued vs sector median PE."""
    if pe_ttm is None or sector_median_pe is None or sector_median_pe <= 0:
        return None
    ratio = pe_ttm / sector_median_pe
    if ratio < 0.75:
        return "undervalued"
    if ratio > 1.35:
        return "overvalued"
    return "fairly_valued"
