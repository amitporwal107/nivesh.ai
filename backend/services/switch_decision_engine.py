"""Nivesh Switch Engine — v2 (full PRD).

Implements the full 9-step spec verbatim:

  Step 0: Inputs (scores, position, fund, goal, candidate universe)
  Step 1: Tax + exit cost
  Step 2: Switch score signals (exit/add/quality/health)
  Step 3: Candidate universe filter + best-alt selection
  Step 4: Benefit calc (cost saving, alpha gain, net benefit)
  Step 5: Hard blockers (tax-ineff, exit-load, no option)
  Step 6: Direct plan priority (STRONG / PHASED)
  Step 7: Fund switch decision (STRONG / PARTIAL / WATCHLIST / HOLD)
  Step 8: Tax optimisation layer (LTCG harvest, SIP redirect)
  Step 9: Structured output {action, allocation, from/to, breakdown, reason[]}

Pure function. No I/O. Candidate universe is passed in as a list;
caller is responsible for hydrating it (MF metadata cache).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_YEARS_TO_GOAL = 10
DEFAULT_EXIT_LOAD_PCT = 0.0
DEFAULT_DEBT_SLAB_RATE = 0.30
LTCG_EXEMPTION_RS = 100_000
LTCG_RATE = 0.10
STCG_EQUITY_RATE = 0.15
EXPENSE_DIFF_MIN_FOR_DIRECT = 0.005         # 0.5%
MIN_AUM_CR = 500                            # ₹500 Cr minimum for candidate
MIN_TRACK_RECORD_YEARS = 3
WEAK_CANDIDATE_RETURN_MIN = 0.01            # 1% return uplift floor
WEAK_CANDIDATE_COST_MIN = 0.003             # 0.3% cost saving floor

# ── Switch cost framework (PRD: Cost-of-Switch) ─────────────────────────
# Total Switch Cost (%) = Exit Load % + Tax Impact % + Slippage %
# Decision rules layered on top of normal scoring:
#   * SWITCH_COST_AGGRESSIVE_PCT  — below this, switch freely
#   * SWITCH_COST_BLOCK_PCT       — above this, switch only on strong signals
#   * TAX_IMPACT_STAGGER_PCT      — above this, route to STP/staggered switch
DEFAULT_SLIPPAGE_PCT = 0.002                # 0.2% — T+2/T+3 redemption gap
SWITCH_COST_AGGRESSIVE_PCT = 0.01           # < 1% friction → free-flow
SWITCH_COST_BLOCK_PCT = 0.02                # > 2% friction → require strong signal
TAX_IMPACT_STAGGER_PCT = 0.02               # > 2% → escalate to staggered/STP
STRONG_SIGNAL_THRESHOLD = 3                 # switch_score >= 3 = "strong underperformance"

# ── Action constants ────────────────────────────────────────────────────
ACTION_STRONG_SWITCH_DIRECT   = "STRONG_SWITCH_DIRECT"
ACTION_PHASED_SWITCH_DIRECT   = "PHASED_SWITCH_DIRECT"
ACTION_STRONG_SWITCH          = "STRONG_SWITCH"            # fund → fund, 100%
ACTION_PARTIAL_SWITCH         = "PARTIAL_SWITCH"           # 25-50%
ACTION_WATCHLIST              = "WATCHLIST"                # wait for tax eff.
ACTION_SIP_REDIRECT           = "SIP_REDIRECT"             # new flows → alt
ACTION_HOLD                   = "HOLD"
ACTION_HOLD_TAX               = "HOLD_TAX"
ACTION_HOLD_EXIT_LOAD         = "HOLD_EXIT_LOAD"
ACTION_HOLD_DEFER             = "HOLD_DEFER"
ACTION_HOLD_NO_OPTION         = "HOLD_NO_OPTION"
ACTION_EXIT                   = "EXIT"
ACTION_ADD                    = "ADD"
ACTION_STAGGERED_SWITCH       = "STAGGERED_SWITCH"         # STP-style, tax-spread

UI_LABELS: Dict[str, Tuple[str, str]] = {
    ACTION_STRONG_SWITCH_DIRECT: ("Switch to Direct",         "✅"),
    ACTION_PHASED_SWITCH_DIRECT: ("Phased switch to Direct",  "📅"),
    ACTION_STRONG_SWITCH:        ("Switch (better fund)",     "🔁"),
    ACTION_PARTIAL_SWITCH:       ("Partial switch",           "⚖️"),
    ACTION_WATCHLIST:            ("Watchlist",                "👀"),
    ACTION_SIP_REDIRECT:         ("Redirect new SIPs",        "🔀"),
    ACTION_HOLD:                 ("Hold",                     "—"),
    ACTION_HOLD_TAX:             ("Hold · tax inefficient",   "⏳"),
    ACTION_HOLD_EXIT_LOAD:       ("Hold · exit load high",    "🛑"),
    ACTION_HOLD_DEFER:           ("Hold · defer switch",      "⏳"),
    ACTION_HOLD_NO_OPTION:       ("Hold · no better option",  "—"),
    ACTION_EXIT:                 ("Exit fund",                "⛔"),
    ACTION_ADD:                  ("Increase allocation",      "✅"),
    ACTION_STAGGERED_SWITCH:     ("Staggered switch (STP)",   "📅"),
}

# 5-bucket recommendation taxonomy per PRD §13. Maps each internal action
# to (recommendation_label, action_strength). UI uses these for colour /
# CTA mapping (ADD=green Invest More · SWITCH=orange Switch Now ·
# EXIT=red Exit · REVIEW=yellow Review · WATCH=grey Monitor).
RECOMMENDATION_BY_ACTION: Dict[str, Tuple[str, str]] = {
    ACTION_STRONG_SWITCH_DIRECT: ("SWITCH", "HIGH"),
    ACTION_PHASED_SWITCH_DIRECT: ("SWITCH", "MEDIUM"),
    ACTION_STRONG_SWITCH:        ("SWITCH", "HIGH"),
    ACTION_PARTIAL_SWITCH:       ("SWITCH", "MEDIUM"),
    ACTION_SIP_REDIRECT:         ("SWITCH", "LOW"),
    ACTION_EXIT:                 ("EXIT",   "HIGH"),
    ACTION_ADD:                  ("ADD",    "HIGH"),
    ACTION_STAGGERED_SWITCH:     ("SWITCH", "MEDIUM"),
    ACTION_WATCHLIST:            ("REVIEW", "MEDIUM"),
    ACTION_HOLD_TAX:             ("REVIEW", "LOW"),
    ACTION_HOLD_EXIT_LOAD:       ("REVIEW", "LOW"),
    ACTION_HOLD_DEFER:           ("REVIEW", "LOW"),
    ACTION_HOLD_NO_OPTION:       ("WATCH",  "LOW"),
    ACTION_HOLD:                 ("WATCH",  "LOW"),
}


# ── Data classes ────────────────────────────────────────────────────────
@dataclass
class CandidateFund:
    """One fund in the candidate universe (Step 3)."""
    name: str
    category: str
    expense: float                 # decimal fraction (0.0074 = 0.74%)
    return_5y: float               # decimal fraction (0.14 = 14% CAGR)
    drawdown: float                # decimal fraction (0.22 = -22%)
    consistency: float             # 0-100 score
    aum_cr: float                  # AUM in ₹ crore
    track_record_years: float


@dataclass
class DecisionInputs:
    # Scores (Step 0)
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
    # Fund data
    expense_current: Optional[float] = None       # decimal fraction
    expense_direct: Optional[float] = None        # decimal fraction (same fund's Direct variant)
    current_return_5y: Optional[float] = None
    current_drawdown: Optional[float] = None
    current_consistency: Optional[float] = None
    current_category: Optional[str] = None
    current_fund_name: Optional[str] = None
    # Goal
    years_to_goal: float = DEFAULT_YEARS_TO_GOAL
    # Flags
    direct_plan_available: bool = False
    # Portfolio context (PRD §9 — category override + over-allocation)
    portfolio_weight_pct: Optional[float] = None     # e.g., 22.5 for 22.5%
    is_sector_or_thematic: bool = False
    # Candidate universe (Step 3)
    candidate_funds: List[CandidateFund] = field(default_factory=list)
    # Taxation
    debt_slab_rate: float = DEFAULT_DEBT_SLAB_RATE
    # Switch cost — slippage from T+2/T+3 redemption gap (PRD: 0.1-0.3%).
    # Tunable per-case (e.g., higher in volatile markets).
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT


@dataclass
class DecisionResult:
    action: str
    label: str
    allocation_pct: int
    from_fund: Optional[str]
    to_fund: Optional[str]
    switch_score: int
    signals: Dict[str, int]
    breakdown: Dict[str, float]
    reason: List[str]
    alt_score: Optional[float] = None


# ── Step 1: tax & exit ──────────────────────────────────────────────────
def compute_tax_cost(inp: DecisionInputs) -> float:
    gain = inp.current_value - inp.invested_amount
    if gain <= 0:
        return 0.0
    if not inp.is_equity:
        return gain * inp.debt_slab_rate
    if inp.holding_period_days is not None and inp.holding_period_days < 365:
        return gain * STCG_EQUITY_RATE
    taxable = max(0.0, gain - LTCG_EXEMPTION_RS)
    return taxable * LTCG_RATE


# ── Switch Cost framework (PRD: Cost-of-Switch) ─────────────────────────
def compute_switch_costs(inp: DecisionInputs) -> Dict[str, float]:
    """Returns the structured Cost-of-Switch breakdown.

    All `*_pct` values are decimal fractions (0.035 == 3.5%) so they
    can be compared to alpha and the threshold constants directly.

    Slippage is applied only when an actual switch is on the table —
    same-fund Direct migration involves no redemption + reinvestment lag,
    so callers passing direct_plan_only=True get slippage zeroed out.
    """
    cv = max(1.0, inp.current_value)   # avoid div-by-zero
    tax = compute_tax_cost(inp)
    exit_load = inp.current_value * max(0.0, inp.exit_load_pct)
    slip = inp.current_value * max(0.0, inp.slippage_pct)

    tax_pct = tax / cv
    exit_pct = exit_load / cv
    slip_pct = slip / cv
    total_pct = tax_pct + exit_pct + slip_pct

    return {
        "tax_cost": round(tax, 2),
        "exit_cost": round(exit_load, 2),
        "slippage_cost": round(slip, 2),
        "total_cost": round(tax + exit_load + slip, 2),
        # Decimal fractions for math; multiply ×100 for display.
        "tax_impact_pct": tax_pct,
        "exit_load_pct": exit_pct,
        "slippage_pct": slip_pct,
        "switch_cost_pct": total_pct,
    }


# ── Step 2: signals ─────────────────────────────────────────────────────
def compute_signals(inp: DecisionInputs) -> Dict[str, int]:
    e, a, q, h = inp.exit_s, inp.add, inp.quality, inp.health
    sig: Dict[str, int] = {}
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


# ── Step 3: filter + score candidates ───────────────────────────────────
def _filter_candidates(inp: DecisionInputs) -> List[CandidateFund]:
    out: List[CandidateFund] = []
    for f in inp.candidate_funds:
        if inp.current_category and f.category != inp.current_category:
            continue
        if f.aum_cr < MIN_AUM_CR:
            continue
        if f.track_record_years < MIN_TRACK_RECORD_YEARS:
            continue
        out.append(f)
    return out


def _score_candidate(f: CandidateFund, inp: DecisionInputs) -> Optional[float]:
    """Return weighted alt_score or None if weak-candidate reject triggers."""
    cur_ret = inp.current_return_5y or 0.0
    cur_dd  = inp.current_drawdown or 0.0
    cur_exp = inp.expense_current or 0.0
    cur_con = inp.current_consistency or 0.0

    return_delta      = f.return_5y - cur_ret
    risk_delta        = cur_dd - f.drawdown       # lower drawdown = better
    cost_delta        = cur_exp - f.expense        # lower expense = better
    consistency_delta = f.consistency - cur_con

    # Weak-candidate reject (from PRD 3.2)
    if return_delta < WEAK_CANDIDATE_RETURN_MIN and cost_delta < WEAK_CANDIDATE_COST_MIN and risk_delta <= 0:
        return None
    if consistency_delta < 0:
        return None

    return (
        0.35 * return_delta
        + 0.25 * risk_delta
        + 0.20 * cost_delta
        + 0.20 * (consistency_delta / 100.0)      # normalise 0-100 → 0-1
    )


def _find_best_alternative(inp: DecisionInputs) -> Tuple[Optional[CandidateFund], Optional[float]]:
    best: Optional[CandidateFund] = None
    best_score = float("-inf")
    for f in _filter_candidates(inp):
        s = _score_candidate(f, inp)
        if s is None:
            continue
        if s > best_score:
            best, best_score = f, s
    return best, (best_score if best else None)


# ── Main decision function ──────────────────────────────────────────────
def decide(inp: DecisionInputs, *, plan_type: str = "regular") -> DecisionResult:
    # Step 1: tax + exit
    gain = inp.current_value - inp.invested_amount
    tax_cost = compute_tax_cost(inp)
    exit_cost = inp.current_value * max(0.0, inp.exit_load_pct)
    # Cost-of-Switch framework — total friction as % of current value.
    cost_pct = compute_switch_costs(inp)
    switch_cost_pct = cost_pct["switch_cost_pct"]
    tax_impact_pct = cost_pct["tax_impact_pct"]
    slippage_cost = cost_pct["slippage_cost"]

    # Step 2: score signals
    signals = compute_signals(inp)
    switch_score = sum(signals.values())

    # Step 3: best alternative
    best_alt, alt_score = _find_best_alternative(inp)
    better_alternative_exists = best_alt is not None

    # Step 4: benefit calc
    # 4.1 alt-based
    alt_cost_saving = 0.0
    alpha_gain = 0.0
    if better_alternative_exists:
        exp_diff = max(0.0, (inp.expense_current or 0.0) - best_alt.expense)
        alt_cost_saving = inp.current_value * exp_diff * max(1.0, inp.years_to_goal)
        alpha = max(0.0, best_alt.return_5y - (inp.current_return_5y or 0.0))
        alpha_gain = inp.current_value * alpha * max(1.0, inp.years_to_goal)

    # 4.2 direct plan saving
    direct_saving = 0.0
    expense_diff_direct = 0.0
    if inp.direct_plan_available and inp.expense_current is not None and inp.expense_direct is not None:
        expense_diff_direct = max(0.0, inp.expense_current - inp.expense_direct)
        direct_saving = inp.current_value * expense_diff_direct * max(1.0, inp.years_to_goal)

    # 4.3 net benefit — two views depending on which path we take
    net_benefit_alt = alt_cost_saving + alpha_gain - tax_cost - exit_cost
    net_benefit_direct = direct_saving - tax_cost - exit_cost

    breakdown = {
        "gain": round(gain, 2),
        "tax_cost": round(tax_cost, 2),
        "exit_cost": round(exit_cost, 2),
        "slippage_cost": round(slippage_cost, 2),
        "cost_saving_alt": round(alt_cost_saving, 2),
        "alpha_gain": round(alpha_gain, 2),
        "direct_saving": round(direct_saving, 2),
        "expense_diff_direct_pct": round(expense_diff_direct * 100, 3),
        "net_benefit_alt": round(net_benefit_alt, 2),
        "net_benefit_direct": round(net_benefit_direct, 2),
        # Cost-of-Switch framework (PRD): all in % terms for UX clarity
        "switch_cost_pct": round(switch_cost_pct * 100, 3),
        "tax_impact_pct": round(tax_impact_pct * 100, 3),
        "exit_load_pct": round(cost_pct["exit_load_pct"] * 100, 3),
        "slippage_pct": round(cost_pct["slippage_pct"] * 100, 3),
        "alpha_pct_annual": round(
            (max(0.0, best_alt.return_5y - (inp.current_return_5y or 0.0)) * 100)
            if better_alternative_exists else 0.0,
            3,
        ),
    }

    from_name = inp.current_fund_name
    reasons: List[str] = []

    # Helper to package a result
    def _res(action: str, alloc: int, to_fund: Optional[str], reason_lines: List[str]) -> DecisionResult:
        return DecisionResult(
            action=action,
            label=UI_LABELS[action][0],
            allocation_pct=alloc,
            from_fund=from_name,
            to_fund=to_fund,
            switch_score=switch_score,
            signals=signals,
            breakdown=breakdown,
            reason=reason_lines,
            alt_score=round(alt_score, 4) if alt_score is not None else None,
        )

    # ── Step 5: HARD BLOCKERS ─────────────────────────────────────────
    # 5a: Tax inefficiency inside 1 year
    if gain > 0 and inp.holding_period_days is not None and inp.holding_period_days < 365:
        benefit_ceiling = alt_cost_saving + alpha_gain if better_alternative_exists else direct_saving
        if tax_cost > benefit_ceiling and benefit_ceiling > 0:
            return _res(ACTION_HOLD_TAX, 0, None, [
                f"STCG ₹{tax_cost:,.0f} exceeds projected saving ₹{benefit_ceiling:,.0f}.",
                "Wait for 1-year LTCG window before switching.",
            ])

    # 5b: Exit load protection
    cost_saving_for_exit_check = (
        alt_cost_saving if better_alternative_exists else direct_saving
    )
    if exit_cost > 0 and exit_cost > cost_saving_for_exit_check and cost_saving_for_exit_check > 0:
        return _res(ACTION_HOLD_EXIT_LOAD, 0, None, [
            f"Exit load ₹{exit_cost:,.0f} exceeds total cost saving ₹{cost_saving_for_exit_check:,.0f}.",
            "Wait for the exit-load window to expire.",
        ])

    # 5c: No better option AT ALL — but only if the fund actually needs
    # action. We defer this check until after EXIT/ADD/Sector overrides
    # have a chance to run.

    # ── ADD check (PRD §7.1) — positive action, no alt needed ────────
    # Strong scores across the board → fund is a portfolio winner.
    # Recommend increasing exposure (only when not over-allocated).
    # Runs early so that strong-fund holders without a peer universe
    # still get a positive recommendation instead of HOLD_NO_OPTION.
    if (
        inp.add is not None and inp.add >= 65
        and inp.quality is not None and inp.quality >= 60
        and inp.health is not None and inp.health >= 60
        and inp.exit_s is not None and inp.exit_s >= 50
        and (inp.portfolio_weight_pct is None or inp.portfolio_weight_pct < 15)
    ):
        return _res(ACTION_ADD, 25, inp.current_fund_name, [
            f"Strong fund — Q={inp.quality:.0f}, H={inp.health:.0f}, A={inp.add:.0f}, E={inp.exit_s:.0f}.",
            "Increase allocation by ~25% via SIP top-up or lump sum.",
        ])

    # ── EXIT check (PRD §7.3) — overrides Direct priority because you ─
    # don't migrate a doomed fund to its Direct variant; you exit it.
    # Trigger: E < 35 AND (Q < 40 OR H < 50) AND alternative exists, and
    # net_benefit of leaving (with peer redirect) is positive after tax.
    if (
        inp.exit_s is not None and inp.exit_s < 35
        and (
            (inp.quality is not None and inp.quality < 40)
            or (inp.health is not None and inp.health < 50)
        )
        and better_alternative_exists
    ):
        # Check tax / exit-load aren't crushing the move.
        proceed_benefit = alt_cost_saving + alpha_gain
        if proceed_benefit - tax_cost - exit_cost > 0:
            return _res(ACTION_EXIT, 100, best_alt.name, [
                f"Exit signal critical (E={inp.exit_s:.0f}<35, Q={inp.quality or 0:.0f}, H={inp.health or 0:.0f}).",
                f"Redirect proceeds to {best_alt.name}.",
                f"Net benefit ₹{proceed_benefit - tax_cost - exit_cost:,.0f} after tax+exit.",
            ])
        # Otherwise tax drag forces a REVIEW
        return _res(ACTION_WATCHLIST, 0, best_alt.name, [
            f"Exit signal critical but tax+exit ₹{tax_cost + exit_cost:,.0f} exceeds projected ₹{proceed_benefit:,.0f}.",
            "Review monthly; redirect new SIPs to alternative.",
        ])

    # ── Sector / Thematic override (PRD §9) ──────────────────────────
    # Concentrated thematic funds with even moderate switch_score should
    # exit rather than hold (sector rotation risk).
    if inp.is_sector_or_thematic and switch_score >= 2 and better_alternative_exists:
        return _res(ACTION_EXIT, 100, best_alt.name, [
            f"Sector/thematic fund with switch_score {switch_score}/5.",
            "Concentration risk — rotate into a diversified peer.",
        ])

    # ── Over-allocation override (PRD §9) — partial trim ─────────────
    OVERWEIGHT_PCT = 25.0
    if (
        inp.portfolio_weight_pct is not None
        and inp.portfolio_weight_pct > OVERWEIGHT_PCT
    ):
        trim_target = best_alt.name if best_alt else "Other peer fund"
        return _res(ACTION_PARTIAL_SWITCH, 30, trim_target, [
            f"Position is {inp.portfolio_weight_pct:.1f}% of portfolio — above {OVERWEIGHT_PCT}% cap.",
            "Trim 30% to restore diversification.",
        ])

    # ── Deferred 5c: No better option — fires only after positive-action
    # branches (ADD/EXIT/Sector/Overweight) had a chance to run.
    if not better_alternative_exists and not inp.direct_plan_available:
        return _res(ACTION_HOLD_NO_OPTION, 0, None, [
            "No better fund alternative found and Direct plan unavailable.",
            "Continue holding.",
        ])

    # ── Step 6: DIRECT PLAN PRIORITY (takes precedence over fund switch) ──
    # Rationale: same fund + lower TER = zero diversification risk,
    # just pure cost saving. Fund swap only makes sense when Direct
    # isn't available OR when fund itself is truly weak.
    if inp.direct_plan_available and expense_diff_direct >= EXPENSE_DIFF_MIN_FOR_DIRECT:
        if (tax_cost + exit_cost) < direct_saving:
            reasons = [
                f"Direct plan saves ~₹{direct_saving / max(1, inp.years_to_goal):,.0f}/yr "
                f"(~₹{direct_saving:,.0f} over {int(inp.years_to_goal)}y).",
                f"Tax+exit cost ₹{tax_cost + exit_cost:,.0f} is covered by saving — clear economic win.",
            ]
            return _res(ACTION_STRONG_SWITCH_DIRECT, 100, "Direct plan (same fund)", reasons)
        # Partial / phased
        if net_benefit_direct > 0:
            return _res(ACTION_PHASED_SWITCH_DIRECT, 40, "Direct plan (phase over time)", [
                f"Net benefit ₹{net_benefit_direct:,.0f} is positive but tax+exit erodes half.",
                "Stop Regular SIPs; migrate tranches as each crosses LTCG threshold.",
            ])
        # Net negative — defer
        return _res(ACTION_HOLD_DEFER, 0, None, [
            f"Tax+exit cost ₹{tax_cost + exit_cost:,.0f} currently exceeds direct-plan saving ₹{direct_saving:,.0f}.",
            "Revisit after LTCG eligibility or exit-load drop.",
        ])

    # ── Step 7: FUND SWITCH DECISION ─────────────────────────────────
    if better_alternative_exists:
        # SIP redirect first — it has ZERO switch cost (no redemption),
        # so cost-of-switch overlay doesn't apply.
        if switch_score >= 2 and net_benefit_alt <= 0:
            return _res(ACTION_SIP_REDIRECT, 0, best_alt.name, [
                f"Existing units stay put (tax drag ₹{tax_cost:,.0f}). Redirect NEW SIPs to {best_alt.name}.",
                "Zero-tax migration over the investment horizon.",
            ])

        # PRD Cost-of-Switch overlay: compare friction% vs alpha%.
        # alpha_pct_annual is the annual edge of the alt fund over current.
        alpha_pct_annual = max(0.0, best_alt.return_5y - (inp.current_return_5y or 0.0))
        # Total round-trip friction expected to be recovered within
        # `years_to_goal`. We compare yearly friction (amortised) vs alpha.
        amortised_cost_pct = switch_cost_pct / max(1.0, inp.years_to_goal)

        # Rule 3 (PRD): Tax impact > 2% → escalate to staggered/STP switch.
        # Even when signals + benefit say full switch is warranted, a 2%+
        # tax hit is too lumpy to absorb at once.
        if (
            tax_impact_pct > TAX_IMPACT_STAGGER_PCT
            and switch_score >= 2
            and net_benefit_alt > 0
        ):
            return _res(ACTION_STAGGERED_SWITCH, 25, best_alt.name, [
                f"Tax impact {tax_impact_pct * 100:.1f}% exceeds 2% threshold.",
                f"Stagger 25%/quarter over a year (STP) to spread tax across slabs.",
                f"Net benefit at full migration: ₹{net_benefit_alt:,.0f}.",
            ])

        # Rule 1 (PRD): Switch cost > 2% AND signals not "strong" → block.
        # Allow it through only when switch_score >= 3 (strong underperf).
        if (
            switch_cost_pct > SWITCH_COST_BLOCK_PCT
            and switch_score < STRONG_SIGNAL_THRESHOLD
        ):
            return _res(ACTION_WATCHLIST, 0, best_alt.name, [
                f"Switch cost {switch_cost_pct * 100:.1f}% > 2% but signals not strong (score {switch_score}/5).",
                f"Tax {tax_impact_pct * 100:.1f}% + exit {cost_pct['exit_load_pct'] * 100:.1f}% + slippage {cost_pct['slippage_pct'] * 100:.2f}%.",
                "Watchlisted — review as LTCG threshold approaches.",
            ])

        # Friction sanity check: if amortised cost > alpha, switch erodes returns.
        if (
            switch_cost_pct > SWITCH_COST_BLOCK_PCT
            and amortised_cost_pct > alpha_pct_annual
        ):
            return _res(ACTION_WATCHLIST, 0, best_alt.name, [
                f"Switch cost {switch_cost_pct * 100:.1f}% (amortised {amortised_cost_pct * 100:.2f}%/yr)",
                f"exceeds expected alpha {alpha_pct_annual * 100:.1f}%/yr.",
                "Switch would erode returns — watchlisted.",
            ])

        if switch_score >= 3 and net_benefit_alt > 0:
            tag = " (low-friction)" if switch_cost_pct < SWITCH_COST_AGGRESSIVE_PCT else ""
            reasons = [
                f"Switch score {switch_score}/5 with net benefit ₹{net_benefit_alt:,.0f}{tag}.",
                f"Better alternative found: {best_alt.name}.",
                f"Total switch cost {switch_cost_pct * 100:.1f}% vs alpha {alpha_pct_annual * 100:.1f}%/yr.",
            ]
            _append_signal_reasons(reasons, signals)
            return _res(ACTION_STRONG_SWITCH, 100, best_alt.name, reasons)

        if switch_score == 2 and net_benefit_alt > 0:
            reasons = [
                f"Switch score 2/5 with modest benefit ₹{net_benefit_alt:,.0f}.",
                f"Switch cost {switch_cost_pct * 100:.1f}% vs alpha {alpha_pct_annual * 100:.1f}%/yr.",
                f"Migrate 25-50% to {best_alt.name}; keep core for LTCG staging.",
            ]
            return _res(ACTION_PARTIAL_SWITCH, 40, best_alt.name, reasons)

        if switch_score >= 3 and net_benefit_alt <= 0:
            # Wait-for-tax-efficiency watchlist
            return _res(ACTION_WATCHLIST, 0, best_alt.name, [
                f"Switch score {switch_score}/5 — signals are weak but tax drag kills the deal.",
                "Watchlisted: review monthly as LTCG threshold approaches.",
            ])

    # ── Step 8: LTCG harvesting (default fall-through) ───────────────
    # If the fund is held ≥ 1yr and gain exceeds ₹1L exemption, even if
    # we otherwise recommend HOLD, propose a partial harvest to lock in
    # tax-free gains.
    if inp.is_equity and inp.holding_period_days is not None and inp.holding_period_days >= 365 and gain > LTCG_EXEMPTION_RS:
        return _res(ACTION_PARTIAL_SWITCH, 20, best_alt.name if best_alt else "Same fund (harvest)", [
            f"Gain ₹{gain:,.0f} exceeds ₹1L LTCG exemption.",
            "Harvest ₹1L tax-free annually to reset cost basis.",
        ])

    # ── Default: HOLD ────────────────────────────────────────────────
    return _res(ACTION_HOLD, 0, None, ["No compelling switch case. Continue holding."])


def _append_signal_reasons(reasons: List[str], signals: Dict[str, int]) -> None:
    if signals.get("exit_signal", 0) >= 2:
        reasons.append("Low exit score (E < 40)")
    elif signals.get("exit_signal", 0) == 1:
        reasons.append("Moderate exit signal (E 40-60)")
    if signals.get("quality_signal"):
        reasons.append("Weak quality (Q < 50)")
    if signals.get("health_signal"):
        reasons.append("Weak health (H < 50)")
    if signals.get("add_signal"):
        reasons.append("Low add-score fit (A < 50)")


# ── Output serialiser (Step 9) ──────────────────────────────────────────
def result_to_dict(res: DecisionResult) -> Dict[str, Any]:
    rec, strength = RECOMMENDATION_BY_ACTION.get(res.action, ("WATCH", "LOW"))
    bk = res.breakdown
    # Pick the larger benefit view as the canonical net_benefit so the UI
    # always reports the path actually taken.
    if res.action in (ACTION_STRONG_SWITCH_DIRECT, ACTION_PHASED_SWITCH_DIRECT, ACTION_HOLD_DEFER):
        net_benefit = bk.get("net_benefit_direct", 0)
        cost_saving = bk.get("direct_saving", 0)
        alpha_gain = 0.0
    else:
        net_benefit = bk.get("net_benefit_alt", 0)
        cost_saving = bk.get("cost_saving_alt", 0)
        alpha_gain = bk.get("alpha_gain", 0)

    return {
        # 5-bucket taxonomy (PRD §13)
        "recommendation": rec,
        "action_strength": strength,
        "allocation_change": f"{res.allocation_pct}%",
        "from_fund": res.from_fund,
        "to_fund": res.to_fund,
        # Score signals + scores (per output spec §12)
        "scores": {
            "switch_score": res.switch_score,
            **res.signals,
        },
        # Detailed action (internal — useful for advisor context)
        "action": res.action,
        "label": res.label,
        "allocation": f"{res.allocation_pct}%",
        "allocation_pct": res.allocation_pct,
        # Reasons + financial impact (PRD §12 + Cost-of-Switch overlay)
        "reason": res.reason,
        "impact": {
            "cost_saving": round(cost_saving, 0),
            "alpha_gain": round(alpha_gain, 0),
            "tax_cost": round(bk.get("tax_cost", 0), 0),
            "exit_cost": round(bk.get("exit_cost", 0), 0),
            "slippage_cost": round(bk.get("slippage_cost", 0), 0),
            "net_benefit": round(net_benefit, 0),
            # Cost-of-Switch percentages (PRD)
            "switch_cost_pct": bk.get("switch_cost_pct", 0),
            "tax_impact_pct": bk.get("tax_impact_pct", 0),
            "exit_load_pct": bk.get("exit_load_pct", 0),
            "slippage_pct": bk.get("slippage_pct", 0),
            "alpha_pct_annual": bk.get("alpha_pct_annual", 0),
        },
        # Backwards-compat fields (existing consumers)
        "switch_score": res.switch_score,
        "signals": res.signals,
        "net_benefit": net_benefit,
        "breakdown": bk,
        "alt_score": res.alt_score,
    }
