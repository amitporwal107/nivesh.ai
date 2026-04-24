"""Deterministic V3 explanation builder.

Generates human-readable explanations for a fund's V3 scores *without* an
LLM. Everything is sourced from composite components + primitives returned
by `services/v3_scoring.py` + `services/v3_integration.py`.

Two responsibilities:
  1. `classify_danger(...)` — given a V3 bundle, return
      {is_danger, level ('critical'|'warning'|'ok'), reasons[]}.
  2. `build_explanation(...)` — given a V3 bundle + plan_type + cost_leak,
      return a short paragraph explaining WHY the fund scores the way it
      does, citing concrete primitives (manager tenure, drawdown,
      expense, overlap, etc.) and highlighting the weakest components.

No I/O. No LLM. Pure functions — testable with unit fixtures.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional


# ── Component-level "why" sentence bank ─────────────────────────────────
# Each weak-component threshold < 5.0 on 0-10 scale generates one sentence.

def _q_sentence(name: str, val: float, primitives: Dict[str, Any]) -> Optional[str]:
    """One-line plain-English reason for a weak Quality component."""
    if val is None:
        return None
    if name == "performance":
        return (f"Trailing returns trail the category average "
                f"(performance component {val:.1f}/10)")
    if name == "risk_adjusted":
        return (f"Risk-adjusted returns are sub-par — "
                f"Sharpe+Sortino combined score {val:.1f}/10")
    if name == "consistency":
        cs = primitives.get("consistency_score")
        if cs is not None:
            return (f"Inconsistent — beats its category in only "
                    f"{int(cs * 10)}% of rolling 12-month windows "
                    f"(consistency {val:.1f}/10)")
        return f"Low consistency across rolling windows ({val:.1f}/10)"
    if name == "drawdown":
        mdd = primitives.get("max_drawdown_pct")
        if mdd is not None:
            return (f"Deep peak-to-trough drawdown of {mdd:.1f}% "
                    f"(drawdown score {val:.1f}/10)")
        return f"Large historical drawdown ({val:.1f}/10)"
    if name == "cost":
        er = primitives.get("expense_ratio_direct")
        if er is not None:
            return (f"Expense ratio {er:.2f}% is on the higher side "
                    f"(cost score {val:.1f}/10)")
        return f"High expense ratio ({val:.1f}/10)"
    if name == "aum_age":
        aum = primitives.get("aum_cr")
        age = primitives.get("fund_age_years")
        bits = []
        if aum is not None:
            bits.append(f"AUM ₹{aum:,.0f}Cr")
        if age is not None:
            bits.append(f"age {age:.1f}y")
        detail = " · ".join(bits) if bits else ""
        return (f"Small/young fund ({detail}) — maturity score "
                f"{val:.1f}/10").strip()
    return None


def _h_sentence(name: str, val: float, primitives: Dict[str, Any]) -> Optional[str]:
    if val is None:
        return None
    if name == "manager_tenure":
        mt = primitives.get("manager_tenure_years")
        if mt is not None:
            return (f"Short manager tenure ({mt:.1f}y) — "
                    f"score {val:.1f}/10")
        return f"Short manager tenure ({val:.1f}/10)"
    if name == "aum_stability":
        return f"AUM trend is unstable (stability score {val:.1f}/10)"
    if name == "turnover":
        tr = primitives.get("turnover_ratio")
        if tr is not None:
            return (f"Portfolio turnover {tr:.0f}% is outside the healthy "
                    f"band (turnover score {val:.1f}/10)")
        return f"Portfolio turnover outside healthy band ({val:.1f}/10)"
    if name == "concentration":
        tc = primitives.get("top10_concentration_pct")
        if tc is not None:
            return (f"Top-10 holdings = {tc:.1f}% of corpus "
                    f"(concentration risk, score {val:.1f}/10)")
        return f"High top-10 concentration ({val:.1f}/10)"
    if name == "downside_protection":
        dc = primitives.get("downside_capture_pct")
        if dc is not None:
            return (f"Downside capture {dc:.1f}% — amplifies benchmark "
                    f"losses (score {val:.1f}/10)")
        return f"Weak downside protection ({val:.1f}/10)"
    if name == "expense_trend":
        return f"Expense ratio is trending up (score {val:.1f}/10)"
    return None


def _strong_sentence(comps: Dict[str, Optional[float]], axis: str,
                     primitives: Dict[str, Any]) -> Optional[str]:
    """Pick one strong (>=7) component to mention as a positive."""
    if not comps:
        return None
    best = [(k, v) for k, v in comps.items() if v is not None and v >= 7.0]
    if not best:
        return None
    best.sort(key=lambda kv: -kv[1])
    k, v = best[0]
    # Translate to plain English
    pretty = {
        "performance": "strong trailing returns vs category",
        "risk_adjusted": "strong Sharpe/Sortino",
        "consistency": "consistent outperformance across rolling windows",
        "drawdown": "contained drawdowns",
        "cost": "competitive expense ratio",
        "aum_age": "mature/large fund",
        "manager_tenure": "long-tenured manager",
        "aum_stability": "stable AUM trend",
        "turnover": "healthy portfolio turnover",
        "concentration": "well-diversified top holdings",
        "downside_protection": "cushions benchmark drawdowns",
        "expense_trend": "declining expense ratio",
    }.get(k, k.replace("_", " "))
    return f"Strength on {axis.lower()}: {pretty} ({v:.1f}/10)"


# ── Public API ───────────────────────────────────────────────────────────
def classify_danger(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Return {level: 'critical'|'warning'|'ok', reasons: [...], is_danger: bool}."""
    q = bundle.get("quality_score")
    h = bundle.get("health_score")
    e = bundle.get("exit_score")
    switch = bundle.get("switch_score")
    guardrail_blocked = bool(bundle.get("guardrail_blocked"))
    guardrail_reasons = bundle.get("guardrail_reasons") or []

    reasons: List[Dict[str, str]] = []
    level = "ok"

    # Critical triggers
    if q is not None and q < 40:
        reasons.append({"code": "very_low_quality",
                        "message": f"Quality score {q:.0f}/100 — well below healthy floor (55)"})
        level = "critical"
    if h is not None and h < 40:
        reasons.append({"code": "very_low_health",
                        "message": f"Health score {h:.0f}/100 — structural concerns "
                                    f"(manager, concentration or expense trend)"})
        level = "critical"
    if e is not None and e >= 75:
        reasons.append({"code": "high_exit",
                        "message": f"Exit score {e:.0f}/100 — engine strongly recommends exit"})
        if level != "critical":
            level = "critical"

    # Warning triggers (only promote if not already critical)
    if level != "critical":
        if q is not None and q < 55:
            reasons.append({"code": "low_quality",
                            "message": f"Quality {q:.0f}/100 is below the 55 floor"})
            level = "warning"
        if h is not None and h < 55:
            reasons.append({"code": "low_health",
                            "message": f"Health {h:.0f}/100 flags structural weakness"})
            level = "warning"
        if e is not None and e >= 60:
            reasons.append({"code": "elevated_exit",
                            "message": f"Elevated exit score {e:.0f}/100 — consider reviewing"})
            level = "warning"

    # Switch-score signal — only meaningful for Regular plans
    if switch is not None and switch >= 2.0:
        reasons.append({"code": "strong_switch",
                        "message": f"Switch score {switch:.1f} ≥ 2.0 — "
                                    f"net benefit from moving to Direct plan"})
        if level == "ok":
            level = "warning"

    # Guardrails (only surface lockouts that block action — high_quality_protection
    # is a POSITIVE signal, not a danger)
    blocking_reasons = [r for r in guardrail_reasons
                        if r in ("tax_exceeds_benefit", "recent_investment_lockout")]
    if guardrail_blocked and blocking_reasons:
        for r in blocking_reasons:
            msg = {
                "tax_exceeds_benefit": "Exit blocked: tax cost exceeds annual benefit",
                "recent_investment_lockout": "Holding < 6 months — exit locked out",
            }[r]
            reasons.append({"code": r, "message": msg})

    return {"level": level, "reasons": reasons, "is_danger": level != "ok"}


# ── Recommendation (EXIT / SWITCH / REVIEW / HOLD / BUY) ─────────────────
def derive_recommendation(
    bundle: Dict[str, Any],
    plan_type: str = "regular",
    cost_leak_rs: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a deterministic per-fund action recommendation.

    Priority: EXIT > SWITCH > REVIEW > BUY > HOLD.

    - EXIT:  exit_score ≥ 75 (and not guardrail-blocked).
    - SWITCH: Regular plan with switch_score ≥ 2.0 (meaningful Reg→Direct saving).
    - REVIEW: watch flags — quality<55 OR health<55 OR exit≥60, or EXIT signal
              that is currently guardrail-blocked (tax/lockout).
    - BUY:   quality ≥ 75, exit < 40, health ≥ 60 (or unknown).
    - HOLD:  default — keep holding, no urgent action.

    Returns `{action, label, reason}`. Pure function — no I/O.
    """
    q = bundle.get("quality_score")
    h = bundle.get("health_score")
    e = bundle.get("exit_score")
    switch = bundle.get("switch_score")
    guardrail_blocked = bool(bundle.get("guardrail_blocked"))
    guardrail_reasons = bundle.get("guardrail_reasons") or []

    # 1) EXIT — high exit score, subject to guardrails
    if e is not None and e >= 75:
        blocking = [r for r in guardrail_reasons
                    if r in ("tax_exceeds_benefit", "recent_investment_lockout")]
        if guardrail_blocked and blocking:
            pretty = {
                "tax_exceeds_benefit": "tax cost exceeds annual benefit",
                "recent_investment_lockout": "holding < 6 months — lockout",
            }[blocking[0]]
            return {
                "action": "REVIEW",
                "label": "Review",
                "reason": (f"High exit signal (Exit {e:.0f}/100) but exit is "
                           f"currently locked — {pretty}."),
            }
        return {
            "action": "EXIT",
            "label": "Exit",
            "reason": (f"Exit score {e:.0f}/100 — engine strongly recommends "
                       f"exiting this fund."),
        }

    # 2) SWITCH — delegate to the Nivesh Switch Engine v2.
    # Full 9-step decision. Returns one of:
    #   STRONG_SWITCH_DIRECT | PHASED_SWITCH_DIRECT | STRONG_SWITCH |
    #   PARTIAL_SWITCH | WATCHLIST | SIP_REDIRECT |
    #   HOLD_TAX | HOLD_EXIT_LOAD | HOLD_DEFER | HOLD_NO_OPTION | HOLD
    sd = bundle.get("switch_decision")
    switch_actions = {
        "STRONG_SWITCH_DIRECT", "PHASED_SWITCH_DIRECT",
        "STRONG_SWITCH", "PARTIAL_SWITCH",
        "WATCHLIST", "SIP_REDIRECT",
        "HOLD_TAX", "HOLD_EXIT_LOAD", "HOLD_DEFER",
    }
    if sd and sd.get("action") in switch_actions:
        return {
            "action": sd["action"],
            "label": sd.get("label", sd["action"].replace("_", " ").title()),
            "reason": " ".join(sd.get("reason", [])) or sd.get("label", ""),
            "decision_case": sd.get("decision_case"),
            "economics": sd.get("breakdown"),
            "switch_score": sd.get("switch_score"),
            "allocation": sd.get("allocation"),
            "to_fund": sd.get("to_fund"),
        }

    # Legacy fallback — only used when the v2 engine didn't run (e.g.
    # missing expense data). Keeps behaviour for stocks / pre-v2 calls.
    if sd is None and plan_type == "regular" and switch is not None and switch >= 2.0:
        saving = f"~₹{cost_leak_rs:,.0f}/yr" if cost_leak_rs else "meaningful"
        return {
            "action": "SWITCH",
            "label": "Switch to Direct",
            "reason": (f"Switch score {switch:.1f} ≥ 2.0 — move to Direct plan "
                       f"for {saving} cost saving with negligible quality impact."),
        }

    # 3) REVIEW — watch flags
    bits: List[str] = []
    if q is not None and q < 55:
        bits.append(f"Quality {q:.0f}/100 below floor")
    if h is not None and h < 55:
        bits.append(f"Health {h:.0f}/100 below floor")
    if e is not None and e >= 60:
        bits.append(f"Exit {e:.0f}/100 elevated")
    if bits:
        return {
            "action": "REVIEW",
            "label": "Review",
            "reason": "Watch closely — " + "; ".join(bits) + ".",
        }

    # 4) BUY — strong, add-worthy
    if (q is not None and q >= 75
            and (h is None or h >= 60)
            and (e is None or e < 40)):
        h_bit = f", Health {h:.0f}/100" if h is not None else ""
        return {
            "action": "BUY",
            "label": "Hold / Add",
            "reason": (f"Strong fund — Quality {q:.0f}/100{h_bit}; engine ranks "
                       f"this among best-in-class for its category."),
        }

    # 5) HOLD — default
    return {
        "action": "HOLD",
        "label": "Hold",
        "reason": "Neither urgent action nor conviction-grade add — keep holding.",
    }




def build_explanation(
    bundle: Dict[str, Any],
    scheme_name: str = "",
    plan_type: str = "regular",
    cost_leak_rs: Optional[float] = None,
) -> str:
    """Return a single paragraph explaining the fund's V3 scores.

    Surfaces up to 3 weak components across Quality + Health plus up to 1
    strength, and appends a switch-score note for Regular plans.
    """
    q = bundle.get("quality_score")
    h = bundle.get("health_score")
    e = bundle.get("exit_score")
    primitives = bundle.get("v3_primitives") or {}
    q_components = bundle.get("quality_components") or {}
    h_components = bundle.get("health_components") or {}

    # Assemble weak-component sentences from Quality
    weak_q = sorted(
        [(k, v) for k, v in q_components.items() if v is not None and v < 5.0],
        key=lambda kv: kv[1],
    )
    weak_h = sorted(
        [(k, v) for k, v in h_components.items() if v is not None and v < 5.0],
        key=lambda kv: kv[1],
    )

    sentences: List[str] = []

    # Headline sentence: overall positioning
    if q is not None and h is not None:
        if q >= 70 and h >= 70:
            headline = f"**Strong fund** — Quality {q:.0f}/100, Health {h:.0f}/100."
        elif q >= 55 and h >= 55:
            headline = f"**Acceptable** — Quality {q:.0f}/100, Health {h:.0f}/100."
        elif q < 55 or h < 55:
            headline = (f"**Below par** — Quality {q:.0f}/100, "
                        f"Health {h:.0f}/100.")
        else:
            headline = f"Quality {q:.0f}/100, Health {h:.0f}/100."
        sentences.append(headline)

    # Weak-component details (cap at 3 total)
    detail_bits: List[str] = []
    for k, v in weak_q[:2]:
        s = _q_sentence(k, v, primitives)
        if s:
            detail_bits.append(s)
    for k, v in weak_h[:2]:
        if len(detail_bits) >= 3:
            break
        s = _h_sentence(k, v, primitives)
        if s:
            detail_bits.append(s)
    if detail_bits:
        sentences.append("Drags: " + "; ".join(detail_bits) + ".")

    # Add a positive callout (at most one)
    strength = _strong_sentence(q_components, "Quality", primitives) or \
               _strong_sentence(h_components, "Health", primitives)
    if strength:
        sentences.append(strength + ".")

    # Exit-score note
    if e is not None and e >= 60:
        sentences.append(f"Exit score {e:.0f}/100 — engine flags this for review.")

    # Switch-score note (Regular plans only)
    switch = bundle.get("switch_score")
    if plan_type == "regular" and switch is not None:
        if switch >= 2.0:
            saving = (f"~₹{cost_leak_rs:,.0f}/yr" if cost_leak_rs else "meaningful")
            sentences.append(f"Regular→Direct switch score {switch:.1f} (≥2.0 threshold) "
                             f"— {saving} cost saving with negligible quality impact.")
        elif switch >= 1.0:
            sentences.append(f"Regular→Direct switch score {switch:.1f} — "
                             f"modest net benefit; review if tax is low.")

    return " ".join(sentences).strip()
