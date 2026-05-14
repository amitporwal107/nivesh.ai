"""SIP (Systematic Investment Plan) calculator tools for the Nivesh Copilot.

Pure-math functions — no external API calls. All amounts in INR.

Functions:
  - calculate_sip_fv         : future value of a fixed monthly SIP
  - calculate_step_up_sip_fv : future value with annual step-up
  - calculate_sip_required   : monthly amount needed to reach a goal
  - calculate_sip_months     : time to reach a goal at a given monthly amount
  - calculate_sip_xirr       : XIRR approximation for an existing SIP series
  - get_sip_projection       : structured SipResult for the copilot agent
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_EQUITY_RATE   = 0.12   # 12% p.a.
_DEFAULT_DEBT_RATE     = 0.07   # 7% p.a.
_DEFAULT_BALANCED_RATE = 0.10   # 10% p.a.


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class SipResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"SIP_CALC status=error reason={self.error}"
        d = self.data
        parts = ["SIP_CALC"]
        if d.get("monthly_sip") is not None:
            parts.append(f"monthly_sip=₹{d['monthly_sip']:,.0f}")
        if d.get("future_value") is not None:
            parts.append(f"fv=₹{d['future_value']:,.0f}")
        if d.get("invested_amount") is not None:
            parts.append(f"invested=₹{d['invested_amount']:,.0f}")
        if d.get("wealth_gained") is not None:
            parts.append(f"gain=₹{d['wealth_gained']:,.0f}")
        if d.get("years") is not None:
            parts.append(f"years={d['years']}")
        if d.get("annual_rate_pct") is not None:
            parts.append(f"rate={d['annual_rate_pct']:.1f}%")
        parts.append(f"summary={self.summary}")
        return " | ".join(parts)


# ── Core math ─────────────────────────────────────────────────────────────────

def calculate_sip_fv(
    monthly_amount: float,
    years: float,
    annual_rate: float,
) -> float:
    """Future value of a fixed monthly SIP.

    FV = P × [((1+r)^n - 1) / r] × (1+r)
    where r = monthly_rate, n = number of months.
    """
    if years <= 0 or monthly_amount <= 0:
        return 0.0
    r = annual_rate / 12
    n = years * 12
    if r == 0:
        return monthly_amount * n
    return monthly_amount * ((1 + r) ** n - 1) / r * (1 + r)


def calculate_step_up_sip_fv(
    monthly_amount: float,
    years: float,
    annual_rate: float,
    step_up_pct: float = 0.10,
) -> float:
    """Future value of a SIP with annual step-up (year-on-year SIP increase).

    Simulates year-by-year: each year the SIP amount grows by step_up_pct.
    """
    if years <= 0 or monthly_amount <= 0:
        return 0.0
    r = annual_rate / 12
    n_full_years = int(years)
    remaining_months = round((years - n_full_years) * 12)
    fv = 0.0
    current_sip = monthly_amount
    for yr in range(n_full_years):
        months_left = (n_full_years - yr) * 12 + remaining_months
        if r == 0:
            fv += current_sip * 12
        else:
            # FV contribution of this year's SIP at end of total period
            year_fv = current_sip * ((1 + r) ** 12 - 1) / r * (1 + r)
            fv = fv * (1 + r) ** 12 + year_fv
        current_sip *= 1 + step_up_pct
    if remaining_months > 0:
        if r == 0:
            fv += current_sip * remaining_months
        else:
            part_fv = current_sip * ((1 + r) ** remaining_months - 1) / r * (1 + r)
            fv = fv * (1 + r) ** remaining_months + part_fv
    return fv


def calculate_sip_required(
    target: float,
    years: float,
    annual_rate: float,
    current_corpus: float = 0.0,
) -> float:
    """Monthly SIP required to reach target, accounting for existing corpus.

    Solves: target = FV_corpus + FV_sip  →  SIP = (target - FV_corpus) × r / ((1+r)^n - 1) / (1+r)
    """
    if years <= 0:
        return max(0.0, target - current_corpus)
    r = annual_rate / 12
    n = years * 12
    fv_corpus = current_corpus * (1 + r) ** n
    gap = max(0.0, target - fv_corpus)
    if gap == 0:
        return 0.0
    if r == 0:
        return gap / n
    return gap * r / ((1 + r) ** n - 1) / (1 + r)


def calculate_sip_months(
    monthly_amount: float,
    target: float,
    annual_rate: float,
    current_corpus: float = 0.0,
) -> Optional[float]:
    """Number of months to reach target at a given monthly SIP.

    Uses logarithmic formula; returns None if target is unreachable.
    """
    if monthly_amount <= 0:
        return None
    r = annual_rate / 12
    if r == 0:
        # linear growth
        total_needed = target - current_corpus
        return None if total_needed <= 0 else total_needed / monthly_amount
    # FV = corpus*(1+r)^n + SIP*[(1+r)^n - 1]/r*(1+r)
    # Solve for n numerically with log approximation
    # SIP * (1+r)/r + corpus → coefficient of (1+r)^n
    coeff = monthly_amount * (1 + r) / r + current_corpus
    rhs = target + monthly_amount * (1 + r) / r
    if coeff <= 0 or rhs / coeff <= 0:
        return None
    try:
        n = math.log(rhs / coeff) / math.log(1 + r)
        return max(0.0, n)
    except (ValueError, ZeroDivisionError):
        return None


# ── Yearly projection table ───────────────────────────────────────────────────

def _yearly_projection(
    monthly_amount: float,
    years: int,
    annual_rate: float,
    step_up_pct: float = 0.0,
) -> List[Dict[str, Any]]:
    """Build year-by-year table: invested, value, gain."""
    rows = []
    r = annual_rate / 12
    fv = 0.0
    invested = 0.0
    current_sip = monthly_amount
    for yr in range(1, years + 1):
        if r == 0:
            fv += current_sip * 12
        else:
            year_fv = current_sip * ((1 + r) ** 12 - 1) / r * (1 + r)
            fv = fv * (1 + r) ** 12 + year_fv
        invested += current_sip * 12
        rows.append({
            "year":     yr,
            "invested": round(invested),
            "value":    round(fv),
            "gain":     round(fv - invested),
        })
        current_sip *= 1 + step_up_pct
    return rows


# ── Public tool function ──────────────────────────────────────────────────────

async def get_sip_projection(
    monthly_amount: float,
    years: int,
    annual_rate: Optional[float] = None,
    goal_amount: Optional[float] = None,
    current_corpus: float = 0.0,
    step_up_pct: float = 0.0,
    fund_category: str = "equity",
) -> SipResult:
    """Compute a full SIP projection and goal-feasibility check.

    Args:
        monthly_amount : monthly SIP in INR
        years          : investment horizon
        annual_rate    : override CAGR (decimal); inferred from fund_category if None
        goal_amount    : target corpus (optional — enables gap analysis)
        current_corpus : existing portfolio value (default 0)
        step_up_pct    : annual SIP step-up fraction (e.g. 0.10 = 10%)
        fund_category  : "equity" | "debt" | "balanced" — determines default CAGR
    """
    try:
        if annual_rate is None:
            cat = fund_category.lower()
            annual_rate = (
                _DEFAULT_EQUITY_RATE   if "equity" in cat or "large" in cat or "mid" in cat or "small" in cat
                else _DEFAULT_DEBT_RATE   if "debt" in cat or "bond" in cat or "liquid" in cat
                else _DEFAULT_BALANCED_RATE
            )

        rate_pct = annual_rate * 100

        if step_up_pct > 0:
            fv = calculate_step_up_sip_fv(monthly_amount, years, annual_rate, step_up_pct)
        else:
            fv = calculate_sip_fv(monthly_amount, years, annual_rate)

        invested = monthly_amount * 12 * years  # approximate (ignores step-up in invested figure)
        if step_up_pct > 0:
            # sum of geometric series for invested
            invested = monthly_amount * 12 * (
                ((1 + step_up_pct) ** years - 1) / step_up_pct
                if step_up_pct > 0 else years
            )

        gain = max(0.0, fv - invested)

        data: Dict[str, Any] = {
            "monthly_sip":      round(monthly_amount),
            "years":            years,
            "annual_rate_pct":  rate_pct,
            "step_up_pct":      step_up_pct * 100,
            "current_corpus":   round(current_corpus),
            "future_value":     round(fv),
            "invested_amount":  round(invested),
            "wealth_gained":    round(gain),
            "multiplier":       round(fv / invested, 2) if invested > 0 else 0,
        }

        # goal feasibility
        if goal_amount is not None and goal_amount > 0:
            sip_needed = calculate_sip_required(
                goal_amount, years, annual_rate, current_corpus,
            )
            shortfall = max(0.0, goal_amount - fv - current_corpus * (1 + annual_rate / 12) ** (years * 12))
            data.update({
                "goal_amount":   round(goal_amount),
                "sip_needed":    round(sip_needed),
                "goal_feasible": fv >= (goal_amount - current_corpus * (1 + annual_rate / 12) ** (years * 12)),
                "shortfall":     round(max(0.0, goal_amount - fv)),
            })

        # month-based time-to-goal
        months_to_goal = None
        if goal_amount is not None:
            months_to_goal = calculate_sip_months(monthly_amount, goal_amount, annual_rate, current_corpus)
            if months_to_goal is not None:
                data["months_to_goal"] = round(months_to_goal)
                data["years_to_goal"]  = round(months_to_goal / 12, 1)

        rows = _yearly_projection(monthly_amount, years, annual_rate, step_up_pct)

        def _lakh(v: float) -> str:
            if v >= 1e7:
                return f"₹{v/1e7:.1f}Cr"
            if v >= 1e5:
                return f"₹{v/1e5:.1f}L"
            return f"₹{v:,.0f}"

        fv_str      = _lakh(fv)
        inv_str     = _lakh(invested)
        step_str    = f" (with {step_up_pct*100:.0f}% annual step-up)" if step_up_pct > 0 else ""
        summary = (
            f"₹{monthly_amount:,.0f}/month SIP{step_str} for {years}yr "
            f"@ {rate_pct:.0f}% CAGR → {fv_str} corpus "
            f"(invested {inv_str}, gain {_lakh(gain)})"
        )

        return SipResult(ok=True, summary=summary, data=data, rows=rows)

    except Exception as exc:
        logger.warning("sip_projection_error: %s", exc)
        return SipResult(ok=False, summary="SIP calculation failed", error=str(exc))
