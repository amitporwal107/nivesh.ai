"""Switch/Exit Decision Engine (v2 — PRD-driven).

Implements the user-provided spec exactly:

  INPUTS:
    - Scores: Q, H, E, A (all 0-100)
    - Position: invested_amount, current_value, holding_period_days,
                is_equity, exit_load_pct
    - Cost: expense_regular, expense_direct, years_to_goal
    - Alt fund: alt_expected_alpha, better_alternative_exists

  DERIVED:
    - gain, tax_cost (STCG 15% < 1y, LTCG 10% > 1y with ₹1L exemption,
                       Debt = 30% slab)
    - exit_cost = current_value × exit_load_pct
    - annual_saving = current_value × (expense_reg − expense_dir)
    - total_cost_saving = annual_saving × years_to_goal
    - alpha_gain = current_value × alt_expected_alpha × years_to_goal
    - net_benefit = total_cost_saving + alpha_gain − tax_cost − exit_cost

  SIGNALS (composite switch_score, 0-5):
    exit_signal:    E<40 → 2,  40≤E<60 → 1, else 0
    add_signal:     A<50 → 1, else 0
    quality_signal: Q<50 → 1, else 0
    health_signal:  H<50 → 1, else 0

  DECISION:
    Case A — Direct Plan Switch (same fund):
      IF expense_diff > 0.5%:
        IF tax+exit < cost_saving*0.5 → STRONG_SWITCH_DIRECT
        ELIF net_benefit > 0         → PARTIAL_SWITCH
        ELSE                         → HOLD_DEFER (wait for LTCG/exit load)
    Case B — Fund-to-Fund Switch:
      IF !better_alternative_exists → HOLD
      ELIF score≥3 AND net>0        → STRONG_SWITCH_FUND
      ELIF score==2 AND net>0       → PARTIAL_SWITCH
      ELSE                          → HOLD
    Case C — Tax Override (CRITICAL):
      IF holding<365 AND tax > (cost_saving + alpha) → HOLD_TAX
    Case D — Exit Load Protection:
      IF exit_cost > cost_saving → HOLD_EXIT_LOAD

Pure function. No I/O. Fully testable.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# ── Defaults (used when caller doesn't provide) ─────────────────────────
DEFAULT_YEARS_TO_GOAL = 10
DEFAULT_ALT_EXPECTED_ALPHA = 0.01          # 1.0% p.a. — conservative midpoint
DEFAULT_EXIT_LOAD_PCT = 0.0                # most equity funds have 0 load after 1y
DEFAULT_DEBT_SLAB_RATE = 0.30              # post-2023 debt taxation default
LTCG_EXEMPTION_RS = 100_000                # ₹1L LTCG exemption on equity
LTCG_RATE = 0.10
STCG_EQUITY_RATE = 0.15
EXPENSE_DIFF_MIN_FOR_CASE_A = 0.005        # 0.5% diff threshold


@dataclass
class DecisionInputs:
    # Scores
    quality: Optional[float] = None
    health: Optional[float] = None
    exit_s: Optional[float] = None
    add: Optional[float] = None
    # Position
    invested_amount: float = 0.0
    current_value: float = 0.0
    holding_period_days: Optional[int] = None
    is_equity: bool = True
    exit_load_pct: float = DEFAULT_EXIT_LOAD_PCT
    # Cost (decimal fractions, e.g. 0.0185 = 1.85%)
    expense_regular: Optional[float] = None
    expense_direct: Optional[float] = None
    years_to_goal: float = DEFAULT_YEARS_TO_GOAL
    # Alt fund
    alt_expected_alpha: float = DEFAULT_ALT_EXPECTED_ALPHA
    better_alternative_exists: bool = False
    # Taxation
    debt_slab_rate: float = DEFAULT_DEBT_SLAB_RATE


@dataclass
class DecisionResult:
    action: str
    label: str
    reason: str
    decision_case: str                     # "A_direct" | "B_fund" | "C_tax" | "D_exit_load" | "default"
    signals: Dict[str, int] = field(default_factory=dict)
    switch_score: int = 0
    economics: Dict[str, float] = field(default_factory=dict)


# ── Decision action constants (UI-facing) ───────────────────────────────
ACTION_STRONG_SWITCH_DIRECT = "STRONG_SWITCH_DIRECT"   # ✅ Switch (Direct)
ACTION_STRONG_SWITCH_FUND   = "STRONG_SWITCH_FUND"     # 🔁 Switch (Better Fund)
ACTION_PARTIAL_SWITCH       = "PARTIAL_SWITCH"         # ⚖️  Partial Switch (25-50%)
ACTION_HOLD                 = "HOLD"                   # default hold
ACTION_HOLD_TAX             = "HOLD_TAX"               # ⏳ Tax inefficient
ACTION_HOLD_EXIT_LOAD       = "HOLD_EXIT_LOAD"         # 🛑 Exit load high
ACTION_HOLD_DEFER           = "HOLD_DEFER"             # ⏳ defer (wait for LTCG/load drop)

UI_LABELS = {
    ACTION_STRONG_SWITCH_DIRECT: ("Switch to Direct",    "✅"),
    ACTION_STRONG_SWITCH_FUND:   ("Switch (better fund)", "🔁"),
    ACTION_PARTIAL_SWITCH:       ("Partial switch",      "⚖️"),
    ACTION_HOLD:                 ("Hold",                "—"),
    ACTION_HOLD_TAX:             ("Hold · tax inefficient", "⏳"),
    ACTION_HOLD_EXIT_LOAD:       ("Hold · exit load high", "🛑"),
    ACTION_HOLD_DEFER:           ("Hold · defer switch", "⏳"),
}


def compute_tax_cost(inp: DecisionInputs) -> float:
    """STCG 15% if equity & <365d, else LTCG 10% on (gain − ₹1L exemption).
    Debt: flat slab rate."""
    gain = max(0.0, inp.current_value - inp.invested_amount)
    if gain <= 0:
        return 0.0
    if not inp.is_equity:
        return gain * inp.debt_slab_rate
    if inp.holding_period_days is not None and inp.holding_period_days < 365:
        return gain * STCG_EQUITY_RATE
    taxable = max(0.0, gain - LTCG_EXEMPTION_RS)
    return taxable * LTCG_RATE


def compute_signals(inp: DecisionInputs) -> Dict[str, int]:
    """Per-PRD normalised boolean signals (each contributes to switch_score)."""
    e, a, q, h = inp.exit_s, inp.add, inp.quality, inp.health
    sig = {}
    # Exit signal — weighted heavier (up to 2 pts)
    if e is None:
        sig["exit_signal"] = 0
    elif e < 40:
        sig["exit_signal"] = 2
    elif e < 60:
        sig["exit_signal"] = 1
    else:
        sig["exit_signal"] = 0
    sig["add_signal"]     = 1 if (a is not None and a < 50) else 0
    sig["quality_signal"] = 1 if (q is not None and q < 50) else 0
    sig["health_signal"]  = 1 if (h is not None and h < 50) else 0
    return sig


def decide(inp: DecisionInputs, *, plan_type: str = "regular") -> DecisionResult:
    """Main decision function — takes fully-hydrated inputs, returns action.
    `plan_type` is "regular" | "direct" — only "regular" is eligible for
    Case A (Regular → Direct of the same fund)."""
    # ── Derived economics ────────────────────────────────────────────
    gain = inp.current_value - inp.invested_amount
    tax_cost = compute_tax_cost(inp)
    exit_cost = inp.current_value * max(0.0, inp.exit_load_pct)

    expense_diff = 0.0
    if inp.expense_regular is not None and inp.expense_direct is not None:
        expense_diff = max(0.0, inp.expense_regular - inp.expense_direct)
    annual_saving = inp.current_value * expense_diff
    total_cost_saving = annual_saving * max(1.0, inp.years_to_goal)
    alpha_gain = (
        inp.current_value * max(0.0, inp.alt_expected_alpha) * max(1.0, inp.years_to_goal)
        if inp.better_alternative_exists else 0.0
    )
    net_benefit = total_cost_saving + alpha_gain - tax_cost - exit_cost

    signals = compute_signals(inp)
    switch_score = sum(signals.values())   # 0-5

    economics = {
        "gain": round(gain, 2),
        "tax_cost": round(tax_cost, 2),
        "exit_cost": round(exit_cost, 2),
        "annual_saving": round(annual_saving, 2),
        "total_cost_saving": round(total_cost_saving, 2),
        "alpha_gain": round(alpha_gain, 2),
        "net_benefit": round(net_benefit, 2),
        "expense_diff_pct": round(expense_diff * 100, 3),
    }

    # ── Case D: Exit Load Protection (check before Case A to avoid false SWITCH) ──
    if exit_cost > 0 and exit_cost > total_cost_saving and total_cost_saving > 0:
        return DecisionResult(
            action=ACTION_HOLD_EXIT_LOAD,
            label=UI_LABELS[ACTION_HOLD_EXIT_LOAD][0],
            reason=f"Exit load ₹{exit_cost:,.0f} exceeds total cost saving ₹{total_cost_saving:,.0f}. Wait for the exit-load window.",
            decision_case="D_exit_load",
            signals=signals,
            switch_score=switch_score,
            economics=economics,
        )

    # ── Case C: Tax Override (STCG drag kills the switch) ──────────
    if (inp.holding_period_days is not None and inp.holding_period_days < 365
            and tax_cost > (total_cost_saving + alpha_gain)
            and (total_cost_saving + alpha_gain) > 0):
        return DecisionResult(
            action=ACTION_HOLD_TAX,
            label=UI_LABELS[ACTION_HOLD_TAX][0],
            reason=f"STCG ₹{tax_cost:,.0f} exceeds the projected saving ₹{total_cost_saving + alpha_gain:,.0f}. Wait till 1-year LTCG window.",
            decision_case="C_tax",
            signals=signals,
            switch_score=switch_score,
            economics=economics,
        )

    # ── Case A: Direct Plan Switch (SAME fund) ─────────────────────
    if plan_type == "regular" and expense_diff > EXPENSE_DIFF_MIN_FOR_CASE_A:
        if (tax_cost + exit_cost) < total_cost_saving * 0.5:
            return DecisionResult(
                action=ACTION_STRONG_SWITCH_DIRECT,
                label=UI_LABELS[ACTION_STRONG_SWITCH_DIRECT][0],
                reason=(
                    f"Switching to Direct saves ~₹{annual_saving:,.0f}/yr "
                    f"(~₹{total_cost_saving:,.0f} over {int(inp.years_to_goal)}y). "
                    f"Tax+exit cost ₹{tax_cost + exit_cost:,.0f} is < 50% of saving — clear economic win."
                ),
                decision_case="A_direct",
                signals=signals,
                switch_score=switch_score,
                economics=economics,
            )
        if net_benefit > 0:
            return DecisionResult(
                action=ACTION_PARTIAL_SWITCH,
                label=UI_LABELS[ACTION_PARTIAL_SWITCH][0],
                reason=(
                    f"Net benefit ₹{net_benefit:,.0f} is positive but tax+exit erodes it. "
                    f"Phase the switch — stop Regular SIPs, migrate tranches as they cross LTCG."
                ),
                decision_case="A_direct",
                signals=signals,
                switch_score=switch_score,
                economics=economics,
            )
        return DecisionResult(
            action=ACTION_HOLD_DEFER,
            label=UI_LABELS[ACTION_HOLD_DEFER][0],
            reason=(
                f"Tax+exit cost ₹{tax_cost + exit_cost:,.0f} currently exceeds projected saving "
                f"₹{total_cost_saving:,.0f}. Revisit after LTCG eligibility or exit-load drop."
            ),
            decision_case="A_direct",
            signals=signals,
            switch_score=switch_score,
            economics=economics,
        )

    # ── Case B: Fund-to-Fund Switch (only if alt exists) ───────────
    if inp.better_alternative_exists:
        if switch_score >= 3 and net_benefit > 0:
            return DecisionResult(
                action=ACTION_STRONG_SWITCH_FUND,
                label=UI_LABELS[ACTION_STRONG_SWITCH_FUND][0],
                reason=f"Switch score {switch_score}/5 with positive net benefit ₹{net_benefit:,.0f} — better alternative found.",
                decision_case="B_fund",
                signals=signals,
                switch_score=switch_score,
                economics=economics,
            )
        if switch_score == 2 and net_benefit > 0:
            return DecisionResult(
                action=ACTION_PARTIAL_SWITCH,
                label=UI_LABELS[ACTION_PARTIAL_SWITCH][0],
                reason=f"Switch score {switch_score}/5 with modest net benefit ₹{net_benefit:,.0f} — migrate 25-50% to alternative.",
                decision_case="B_fund",
                signals=signals,
                switch_score=switch_score,
                economics=economics,
            )

    # ── Default: HOLD ───────────────────────────────────────────────
    return DecisionResult(
        action=ACTION_HOLD,
        label=UI_LABELS[ACTION_HOLD][0],
        reason="No compelling switch case. Continue holding.",
        decision_case="default",
        signals=signals,
        switch_score=switch_score,
        economics=economics,
    )


def result_to_dict(res: DecisionResult) -> Dict[str, Any]:
    """Serialise DecisionResult for JSON response."""
    return {
        "action": res.action,
        "label": res.label,
        "reason": res.reason,
        "decision_case": res.decision_case,
        "signals": res.signals,
        "switch_score": res.switch_score,
        "economics": res.economics,
    }
