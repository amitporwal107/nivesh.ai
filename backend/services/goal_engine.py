"""Goal-Based Investment Planning Engine (GBIPE) — core math + planning logic.

Pure-Python; no DB/network. Callers feed inputs, this module returns the
financial model outputs. Covered here:

  * Future-value of a goal with inflation (`inflate_target`)
  * SIP / lump-sum sizing (`required_sip`, `required_lumpsum`)
  * Projected corpus under a fixed-return assumption
    (`project_corpus_fixed`)
  * Allocation profiles per risk appetite (`allocation_for_profile`)
  * Blended expected-return + volatility from an allocation
    (`blend_return_vol`)
  * Monte-Carlo success probability (`monte_carlo_success`)
  * Scenario corpus at +/- return shocks (`scenario_matrix`)
  * On-track % and gap-to-goal diagnostics (`evaluate_goal`)

PRD asset-class assumptions (editable via `ASSET_ASSUMPTIONS`):
    Equity  → μ=12%, σ=18%
    Debt    → μ=6.5%, σ=3%
    Hybrid  → μ=9%, σ=10%
    Inflation default = 6%
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import numpy as np  # type: ignore
    _HAS_NUMPY = True
except ImportError:  # fallback — tiny pure-python MC
    _HAS_NUMPY = False


# ── Assumptions ─────────────────────────────────────────────────────────
ASSET_ASSUMPTIONS: Dict[str, Dict[str, float]] = {
    "equity": {"mean_annual": 0.12, "vol_annual": 0.18},
    "debt":   {"mean_annual": 0.065, "vol_annual": 0.03},
    "hybrid": {"mean_annual": 0.09, "vol_annual": 0.10},
}

ALLOCATION_PROFILES: Dict[str, Dict[str, float]] = {
    # per PRD §8
    "conservative": {"equity": 30, "debt": 60, "hybrid": 10},
    "moderate":     {"equity": 60, "debt": 30, "hybrid": 10},
    "aggressive":   {"equity": 80, "debt": 10, "hybrid": 10},
}

DEFAULT_INFLATION_PCT = 6.0
MIN_EQUITY_HORIZON_YEARS = 5.0     # PRD §15 guardrail


# ── 7.1 / 7.2 / 7.3 – Core financial math ───────────────────────────────
def inflate_target(target_today_rs: float, years: float, inflation_pct: float = DEFAULT_INFLATION_PCT) -> float:
    """Convert a goal stated in today's rupees → future value at the goal date."""
    return round(float(target_today_rs) * (1.0 + inflation_pct / 100.0) ** float(years), 2)


def _monthly_rate(annual_pct: float) -> float:
    # Equivalent monthly rate that compounds to the annual rate.
    return (1.0 + annual_pct / 100.0) ** (1.0 / 12.0) - 1.0


def required_sip(
    future_value_rs: float,
    years: float,
    annual_return_pct: float,
    starting_corpus_rs: float = 0.0,
) -> float:
    """Monthly SIP needed to hit `future_value` in `years` given
    `annual_return_pct`, accounting for an existing `starting_corpus_rs`.

    FV = PV(1+r)^n + SIP × [((1+r)^n - 1) / r]
    """
    r = _monthly_rate(annual_return_pct)
    n = int(round(years * 12))
    if n <= 0:
        return max(0.0, future_value_rs - starting_corpus_rs)
    pv_grown = starting_corpus_rs * ((1.0 + r) ** n)
    remainder = future_value_rs - pv_grown
    if remainder <= 0:
        return 0.0
    if r == 0:
        return round(remainder / n, 2)
    sip = remainder * r / (((1.0 + r) ** n) - 1.0)
    return round(max(0.0, sip), 2)


def required_lumpsum(future_value_rs: float, years: float, annual_return_pct: float) -> float:
    """Present-value lump sum needed to reach `future_value` in `years`."""
    r = annual_return_pct / 100.0
    return round(float(future_value_rs) / ((1.0 + r) ** float(years)), 2)


def project_corpus_fixed(
    starting_corpus_rs: float,
    monthly_sip_rs: float,
    years: float,
    annual_return_pct: float,
) -> float:
    """Fixed-return projection (base case for on-track %).

    Returns the future corpus after `years` given monthly SIP + starting corpus.
    """
    r = _monthly_rate(annual_return_pct)
    n = int(round(years * 12))
    if n <= 0:
        return round(starting_corpus_rs + monthly_sip_rs * n, 2)
    pv_grown = starting_corpus_rs * ((1.0 + r) ** n)
    if r == 0:
        sip_grown = monthly_sip_rs * n
    else:
        sip_grown = monthly_sip_rs * (((1.0 + r) ** n) - 1.0) / r
    return round(pv_grown + sip_grown, 2)


# ── 8. Allocation ────────────────────────────────────────────────────────
def allocation_for_profile(risk_profile: str, horizon_years: float) -> Dict[str, float]:
    """Return an allocation dict {equity, debt, hybrid} summing to 100.

    Applies horizon guardrail (PRD §15): if horizon < 5y, cap equity at 40%
    and route the surplus to debt. This prevents recommending aggressive
    equity for sub-5y goals.
    """
    profile = (risk_profile or "moderate").lower()
    alloc = dict(ALLOCATION_PROFILES.get(profile, ALLOCATION_PROFILES["moderate"]))
    if horizon_years < MIN_EQUITY_HORIZON_YEARS and alloc["equity"] > 40:
        extra = alloc["equity"] - 40
        alloc["equity"] = 40
        alloc["debt"] = round(alloc["debt"] + extra, 1)
    return alloc


def blend_return_vol(allocation: Dict[str, float]) -> Dict[str, float]:
    """Weighted expected-return and volatility for the allocation mix.

    Volatility is approximated as the weighted sum of component vols (upper
    bound — correlation assumed 1.0 which is conservative but defensible for
    a stress lens).
    """
    total = sum(allocation.values()) or 1.0
    weights = {k: float(v) / total for k, v in allocation.items()}
    mu = sum(weights[k] * ASSET_ASSUMPTIONS[k]["mean_annual"] for k in weights if k in ASSET_ASSUMPTIONS)
    sigma = sum(weights[k] * ASSET_ASSUMPTIONS[k]["vol_annual"] for k in weights if k in ASSET_ASSUMPTIONS)
    return {"annual_return_pct": round(mu * 100, 2), "annual_vol_pct": round(sigma * 100, 2)}


# ── 9. Scenario matrix (base / bull / bear / stress) ────────────────────
def scenario_matrix(
    *,
    starting_corpus_rs: float,
    monthly_sip_rs: float,
    years: float,
    allocation: Dict[str, float],
    future_target_rs: float,
) -> Dict[str, Dict[str, Any]]:
    """Deterministic corpus outputs under 4 fixed-return shocks.

    Success = corpus / future_target_rs.
    """
    base_mu = blend_return_vol(allocation)["annual_return_pct"]
    shocks = {
        "base":   base_mu,
        "bull":   base_mu + 3.0,
        "bear":   base_mu - 3.0,
        "stress": base_mu - 6.0,
    }
    out: Dict[str, Dict[str, Any]] = {}
    for name, mu in shocks.items():
        mu_clamped = max(0.5, mu)   # never go negative (user would pull out)
        corpus = project_corpus_fixed(starting_corpus_rs, monthly_sip_rs, years, mu_clamped)
        success = min(1.0, corpus / future_target_rs) if future_target_rs > 0 else 0.0
        out[name] = {
            "return_pct": round(mu_clamped, 2),
            "corpus_rs": corpus,
            "success_pct": round(success * 100, 1),
        }
    return out


# ── 10. Monte-Carlo success probability ──────────────────────────────────
def monte_carlo_success(
    *,
    starting_corpus_rs: float,
    monthly_sip_rs: float,
    years: float,
    allocation: Dict[str, float],
    future_target_rs: float,
    n_runs: int = 1000,
    seed: Optional[int] = 42,
) -> Dict[str, Any]:
    """Run N independent paths of returns drawn from Normal(μ,σ) per asset,
    blended by allocation, monthly compounded. Reports:
        prob_success_pct, p5_corpus, p50_corpus (median), p95_corpus,
        expected_shortfall_pct, worst_corpus.

    Uses numpy when available; falls back to a small-loop pure-python
    implementation (slower but dependency-free) so the module always imports
    cleanly.
    """
    n_months = max(1, int(round(years * 12)))
    stats = blend_return_vol(allocation)
    mu_a = stats["annual_return_pct"] / 100.0
    sigma_a = stats["annual_vol_pct"] / 100.0
    # Convert annual params to monthly using log-normal approximation
    mu_m = mu_a / 12.0
    sigma_m = sigma_a / math.sqrt(12.0)

    if _HAS_NUMPY:
        rng = np.random.default_rng(seed)
        # Draw an n_runs × n_months matrix of monthly returns
        shocks = rng.normal(loc=mu_m, scale=sigma_m, size=(n_runs, n_months))
        # Path corpus: start with PV, add SIP at month-end, grow.
        corpus = np.full(n_runs, float(starting_corpus_rs), dtype=np.float64)
        for m in range(n_months):
            corpus = corpus * (1.0 + shocks[:, m]) + monthly_sip_rs
        success_mask = corpus >= future_target_rs
        prob = float(success_mask.mean())
        p5, p50, p95 = np.percentile(corpus, [5, 50, 95]).tolist()
        worst = float(corpus.min())
        shortfall_pct = float(np.mean(np.clip(1.0 - corpus / future_target_rs, 0, None)) * 100)
    else:
        import random
        rnd = random.Random(seed)
        corpi: List[float] = []
        for _ in range(n_runs):
            c = float(starting_corpus_rs)
            for _m in range(n_months):
                shock = rnd.gauss(mu_m, sigma_m)
                c = c * (1.0 + shock) + monthly_sip_rs
            corpi.append(c)
        corpi.sort()
        success = sum(1 for c in corpi if c >= future_target_rs)
        prob = success / max(1, len(corpi))
        p5 = corpi[int(0.05 * len(corpi))]
        p10 = corpi[int(0.10 * len(corpi))]
        p50 = corpi[int(0.50 * len(corpi))]
        p90 = corpi[int(0.90 * len(corpi))]
        p95 = corpi[int(0.95 * len(corpi))]
        worst = corpi[0]
        shortfalls = [max(0.0, 1.0 - c / future_target_rs) for c in corpi] if future_target_rs > 0 else [0.0]
        shortfall_pct = (sum(shortfalls) / len(shortfalls)) * 100

    return {
        "prob_success_pct": round(prob * 100, 1),
        "median_corpus_rs": round(p50, 2),
        "p5_corpus_rs": round(p5, 2),
        "p10_corpus_rs": round(p10, 2),
        "p90_corpus_rs": round(p90, 2),
        "p95_corpus_rs": round(p95, 2),
        "worst_corpus_rs": round(worst, 2),
        "expected_shortfall_pct": round(shortfall_pct, 2),
        "n_runs": n_runs,
    }


# ── 11. Action Engine ────────────────────────────────────────────────────
@dataclass
class GoalAction:
    kind: str               # increase_sip | reduce_risk | increase_risk | reallocate | on_track
    title: str
    detail: str
    delta_rs: Optional[float] = None      # delta SIP in rupees
    new_allocation: Optional[Dict[str, float]] = None


def recommend_actions(
    *,
    on_track_pct: float,
    required_sip_rs: float,
    actual_sip_rs: float,
    allocation: Dict[str, float],
    risk_profile: str,
    horizon_years: float,
) -> List[GoalAction]:
    actions: List[GoalAction] = []
    # Shortfall action
    gap = required_sip_rs - actual_sip_rs
    if on_track_pct < 80 and gap > 100:
        actions.append(GoalAction(
            kind="increase_sip",
            title=f"Increase SIP by ₹{round(gap):,}/month",
            detail=(f"You're on track for {on_track_pct:.0f}%. "
                    f"Add ₹{round(gap):,}/month to hit the target at expected returns."),
            delta_rs=round(gap, 2),
        ))
    # Risk-mismatch vs horizon
    if horizon_years < MIN_EQUITY_HORIZON_YEARS and allocation.get("equity", 0) > 40:
        actions.append(GoalAction(
            kind="reduce_risk",
            title="Reduce equity exposure for short horizon",
            detail=(f"Goal is {horizon_years:.1f}y away — equity should not exceed 40% "
                    f"to avoid drawdown risk near goal date."),
            new_allocation=allocation_for_profile("conservative", horizon_years),
        ))
    # Overperformance — can dial down risk
    if on_track_pct >= 100 and allocation.get("equity", 0) > 40 and horizon_years < 10:
        actions.append(GoalAction(
            kind="reduce_risk",
            title="Goal ahead of schedule — consider glide-path",
            detail=("You're already on track. Gradually shift into debt to lock in gains "
                    "as you approach the goal date."),
        ))
    # Default — on track
    if not actions:
        actions.append(GoalAction(
            kind="on_track",
            title="On track — stay the course",
            detail=f"You're on track for {on_track_pct:.0f}% of the target. Keep the SIP running.",
        ))
    return actions


# ── 12.1 Required-return solver (bisect) ─────────────────────────────────
def solve_required_return(
    *,
    future_target_rs: float,
    starting_corpus_rs: float,
    monthly_sip_rs: float,
    years: float,
) -> float:
    """Return the annual-return % at which the projected corpus exactly hits
    `future_target_rs` given the current SIP + horizon. Used to surface the
    'you need 14.2% returns' insight next to the expected return.

    Uses a bounded bisection over [0%, 40%] — monotonic in r so convergence
    is guaranteed. If target is already reachable at 0%, returns 0.
    If unreachable even at 40%, returns 40.0 (flagged 'unrealistic' upstream).
    """
    if future_target_rs <= 0 or years <= 0:
        return 0.0
    lo, hi = 0.0, 40.0
    if project_corpus_fixed(starting_corpus_rs, monthly_sip_rs, years, lo) >= future_target_rs:
        return 0.0
    if project_corpus_fixed(starting_corpus_rs, monthly_sip_rs, years, hi) < future_target_rs:
        return 40.0
    for _ in range(40):   # ~1e-9 precision
        mid = (lo + hi) / 2
        projected = project_corpus_fixed(starting_corpus_rs, monthly_sip_rs, years, mid)
        if projected >= future_target_rs:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2, 2)


def classify_feasibility(required_return_pct: float, expected_return_pct: float) -> str:
    """How realistic is the required return given the chosen allocation?"""
    gap = required_return_pct - expected_return_pct
    if required_return_pct >= 18 or gap >= 6:
        return "unrealistic"
    if gap >= 2:
        return "stretch"
    return "ok"


def classify_goal_health(on_track_pct: float, prob_success_pct: Optional[float]) -> str:
    """Combine fixed-return on_track % and MC probability into a single label."""
    signal = min(on_track_pct, prob_success_pct) if prob_success_pct is not None else on_track_pct
    if signal < 40:
        return "critical"
    if signal < 70:
        return "at_risk"
    if signal < 100:
        return "on_track"
    return "ahead"


def build_why_behind(
    *,
    required_sip_rs: float,
    actual_sip_rs: float,
    required_return_pct: float,
    expected_return_pct: float,
    horizon_years: float,
    on_track_pct: float,
) -> List[Dict[str, Any]]:
    """Rule-based reasons the plan is behind. Each reason has a machine-
    readable code + human-readable text so the UI can render with icons."""
    reasons: List[Dict[str, Any]] = []
    if on_track_pct >= 100:
        return reasons
    gap_sip = required_sip_rs - actual_sip_rs
    if gap_sip > 100:
        pct_short = (gap_sip / required_sip_rs * 100) if required_sip_rs else 0
        reasons.append({
            "code": "sip_gap",
            "label": "Current SIP too low",
            "detail": (f"You're investing ₹{round(actual_sip_rs):,}/month but need "
                       f"₹{round(required_sip_rs):,}/month — a gap of "
                       f"₹{round(gap_sip):,} ({pct_short:.0f}% short)."),
            "severity": "high" if pct_short > 40 else "medium",
        })
    gap_ret = required_return_pct - expected_return_pct
    if gap_ret > 1.0:
        reasons.append({
            "code": "return_gap",
            "label": "Expected return mismatch",
            "detail": (f"Your plan needs {required_return_pct:.1f}% returns but the "
                       f"current allocation is expected to earn only {expected_return_pct:.1f}% "
                       f"(gap {gap_ret:+.1f} pp). A more aggressive allocation can close some of this."),
            "severity": "high" if gap_ret > 4 else "medium",
        })
    if horizon_years < MIN_EQUITY_HORIZON_YEARS:
        reasons.append({
            "code": "short_horizon",
            "label": "Short horizon limits compounding",
            "detail": (f"With only {horizon_years:.1f} years left, compounding has "
                       "little time to work. Equity allocation is capped at 40% "
                       "for safety, which also lowers expected return."),
            "severity": "medium",
        })
    return reasons


def build_recovery_paths(
    *,
    target_today_rs: float,
    horizon_years: float,
    starting_corpus_rs: float,
    monthly_sip_rs: float,
    risk_profile: str,
    inflation_pct: float,
    required_sip_rs: float,
    on_track_pct: float,
    n_mc_runs: int,
) -> List[Dict[str, Any]]:
    """Re-run the sim under three tweaks and return success-% deltas so the
    UI can offer side-by-side "what if you do X" cards."""
    paths: List[Dict[str, Any]] = []
    if on_track_pct >= 100:
        return paths

    def _quick_sim(*, sip: float, years: float, alloc: Dict[str, float]) -> Dict[str, Any]:
        fv = inflate_target(target_today_rs, years, inflation_pct)
        stats = blend_return_vol(alloc)
        mu = stats["annual_return_pct"]
        projected = project_corpus_fixed(starting_corpus_rs, sip, years, mu)
        on_track = round(min(100.0, (projected / fv * 100) if fv > 0 else 0), 1)
        mc = monte_carlo_success(
            starting_corpus_rs=starting_corpus_rs, monthly_sip_rs=sip,
            years=years, allocation=alloc, future_target_rs=fv,
            n_runs=max(300, n_mc_runs // 3),   # lighter MC for recovery paths
        )
        return {
            "projected_corpus_rs": projected,
            "on_track_pct": on_track,
            "prob_success_pct": mc["prob_success_pct"],
            "expected_return_pct": mu,
        }

    base_alloc = allocation_for_profile(risk_profile, horizon_years)

    # A. Increase SIP by gap
    gap_sip = required_sip_rs - monthly_sip_rs
    if gap_sip > 100:
        sim_a = _quick_sim(sip=required_sip_rs, years=horizon_years, alloc=base_alloc)
        paths.append({
            "id": "increase_sip",
            "title": "Increase SIP to required level",
            "tweak_label": f"SIP ₹{round(monthly_sip_rs):,} → ₹{round(required_sip_rs):,}/mo",
            "delta_text": f"+₹{round(gap_sip):,}/mo",
            "apply": {"monthly_sip_rs": required_sip_rs},
            **sim_a,
        })

    # B. Extend horizon by 5 years
    new_years = horizon_years + 5
    sim_b = _quick_sim(sip=monthly_sip_rs, years=new_years,
                       alloc=allocation_for_profile(risk_profile, new_years))
    paths.append({
        "id": "extend_horizon",
        "title": "Extend goal by 5 years",
        "tweak_label": f"Horizon {horizon_years:.0f}y → {new_years:.0f}y",
        "delta_text": "+5 years",
        "apply": {"horizon_years": new_years},
        **sim_b,
    })

    # C. Shift to aggressive allocation
    if risk_profile.lower() != "aggressive" and horizon_years >= MIN_EQUITY_HORIZON_YEARS:
        aggr = allocation_for_profile("aggressive", horizon_years)
        sim_c = _quick_sim(sip=monthly_sip_rs, years=horizon_years, alloc=aggr)
        paths.append({
            "id": "increase_risk",
            "title": "Shift to aggressive allocation",
            "tweak_label": f"Equity {base_alloc.get('equity', 0):.0f}% → {aggr.get('equity', 0):.0f}%",
            "delta_text": f"+{aggr.get('equity', 0) - base_alloc.get('equity', 0):.0f}pp equity",
            "apply": {"allocation_override": aggr},
            **sim_c,
        })

    return paths


# ── 12. One-shot evaluator ───────────────────────────────────────────────
@dataclass
class GoalEvaluation:
    future_target_rs: float
    expected_return_pct: float
    expected_vol_pct: float
    required_sip_rs: float
    required_return_pct: float
    projected_corpus_rs: float
    shortfall_rs: float
    on_track_pct: float
    feasibility: str                    # ok | stretch | unrealistic
    goal_health: str                    # critical | at_risk | on_track | ahead
    why_behind: List[Dict[str, Any]] = field(default_factory=list)
    recovery_paths: List[Dict[str, Any]] = field(default_factory=list)
    scenarios: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    monte_carlo: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "future_target_rs": self.future_target_rs,
            "expected_return_pct": self.expected_return_pct,
            "expected_vol_pct": self.expected_vol_pct,
            "required_sip_rs": self.required_sip_rs,
            "required_return_pct": self.required_return_pct,
            "projected_corpus_rs": self.projected_corpus_rs,
            "shortfall_rs": self.shortfall_rs,
            "on_track_pct": self.on_track_pct,
            "feasibility": self.feasibility,
            "goal_health": self.goal_health,
            "why_behind": self.why_behind,
            "recovery_paths": self.recovery_paths,
            "scenarios": self.scenarios,
            "monte_carlo": self.monte_carlo,
            "actions": self.actions,
        }


def evaluate_goal(
    *,
    target_today_rs: float,
    horizon_years: float,
    starting_corpus_rs: float,
    monthly_sip_rs: float,
    risk_profile: str,
    inflation_pct: float = DEFAULT_INFLATION_PCT,
    allocation_override: Optional[Dict[str, float]] = None,
    n_mc_runs: int = 1000,
) -> GoalEvaluation:
    """One-shot goal evaluation: inflate target → allocate → required SIP →
    project corpus under fixed return → scenario matrix → Monte-Carlo →
    action recommendations → why-behind + recovery paths."""
    fv = inflate_target(target_today_rs, horizon_years, inflation_pct)
    alloc = allocation_override or allocation_for_profile(risk_profile, horizon_years)
    stats = blend_return_vol(alloc)
    mu = stats["annual_return_pct"]
    sigma = stats["annual_vol_pct"]
    req_sip = required_sip(fv, horizon_years, mu, starting_corpus_rs)
    req_return = solve_required_return(
        future_target_rs=fv, starting_corpus_rs=starting_corpus_rs,
        monthly_sip_rs=monthly_sip_rs, years=horizon_years,
    )
    projected = project_corpus_fixed(starting_corpus_rs, monthly_sip_rs, horizon_years, mu)
    shortfall = round(max(0.0, fv - projected), 2)
    on_track = round(min(100.0, (projected / fv * 100) if fv > 0 else 0), 1)
    scenarios = scenario_matrix(
        starting_corpus_rs=starting_corpus_rs, monthly_sip_rs=monthly_sip_rs,
        years=horizon_years, allocation=alloc, future_target_rs=fv,
    )
    mc = monte_carlo_success(
        starting_corpus_rs=starting_corpus_rs, monthly_sip_rs=monthly_sip_rs,
        years=horizon_years, allocation=alloc, future_target_rs=fv,
        n_runs=n_mc_runs,
    )
    feasibility = classify_feasibility(req_return, mu)
    health = classify_goal_health(on_track, mc.get("prob_success_pct"))
    why = build_why_behind(
        required_sip_rs=req_sip, actual_sip_rs=monthly_sip_rs,
        required_return_pct=req_return, expected_return_pct=mu,
        horizon_years=horizon_years, on_track_pct=on_track,
    )
    recovery = build_recovery_paths(
        target_today_rs=target_today_rs, horizon_years=horizon_years,
        starting_corpus_rs=starting_corpus_rs, monthly_sip_rs=monthly_sip_rs,
        risk_profile=risk_profile, inflation_pct=inflation_pct,
        required_sip_rs=req_sip, on_track_pct=on_track, n_mc_runs=n_mc_runs,
    )
    actions = recommend_actions(
        on_track_pct=on_track, required_sip_rs=req_sip, actual_sip_rs=monthly_sip_rs,
        allocation=alloc, risk_profile=risk_profile, horizon_years=horizon_years,
    )
    return GoalEvaluation(
        future_target_rs=fv,
        expected_return_pct=mu,
        expected_vol_pct=sigma,
        required_sip_rs=req_sip,
        required_return_pct=req_return,
        projected_corpus_rs=projected,
        shortfall_rs=shortfall,
        on_track_pct=on_track,
        feasibility=feasibility,
        goal_health=health,
        why_behind=why,
        recovery_paths=recovery,
        scenarios=scenarios,
        monte_carlo=mc,
        actions=[{"kind": a.kind, "title": a.title, "detail": a.detail,
                  "delta_rs": a.delta_rs, "new_allocation": a.new_allocation}
                 for a in actions],
    )
