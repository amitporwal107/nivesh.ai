"""
Persona inference engine — derives investor persona from CAS portfolio signals.

Rules are additive-score based: each signal adds points to one or more personas;
the highest-scoring persona wins. Confidence = winner_score capped at 100.

Personas that require broker data (swing/intraday/options trader, NRI) are never
inferred from CAS alone — they score 0 unless the user explicitly sets them via
POST /api/user/persona.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Persona registry ──────────────────────────────────────────────────────────

PERSONAS: dict[str, dict] = {
    "retail_investor":      {"label": "Retail Investor",       "icon": "TrendingUp",  "color": "emerald"},
    "mutual_fund_investor": {"label": "Mutual Fund Investor",  "icon": "BarChart3",   "color": "blue"},
    "stock_investor":       {"label": "Stock Investor",        "icon": "Activity",    "color": "violet"},
    "swing_trader":         {"label": "Swing Trader",          "icon": "Zap",         "color": "amber"},
    "intraday_trader":      {"label": "Intraday Trader",       "icon": "Timer",       "color": "orange"},
    "options_trader":       {"label": "Options Trader",        "icon": "Crosshair",   "color": "rose"},
    "mfd_advisor":          {"label": "MFD / Advisor",         "icon": "Users",       "color": "indigo"},
    "hni_investor":         {"label": "HNI / UHNI Investor",   "icon": "Star",        "color": "amber"},
    "retirement_planner":   {"label": "Retirement Planner",    "icon": "Landmark",    "color": "teal"},
    "tax_saver":            {"label": "Tax Saver",             "icon": "Receipt",     "color": "green"},
    "beginner_investor":    {"label": "Beginner Investor",     "icon": "Sprout",      "color": "lime"},
    "nri_investor":         {"label": "NRI Investor",          "icon": "Globe",       "color": "sky"},
    # Manually-set only — not inferred from CAS
    "active_trader":        {"label": "Active Trader",         "icon": "Zap",         "color": "orange"},
    "parents_planning":     {"label": "Planning for Children", "icon": "Heart",       "color": "pink"},
    "conservative_investor":{"label": "Conservative Investor", "icon": "ShieldCheck", "color": "blue"},
}

# Personas that CAN be inferred from portfolio data
_INFERRABLE = {
    "retail_investor", "mutual_fund_investor", "stock_investor",
    "mfd_advisor", "hni_investor", "retirement_planner",
    "tax_saver", "beginner_investor",
}

_ELSS_KEYWORDS        = {"elss", "tax saver", "taxsaver", "tax saving", "80c"}
_RETIREMENT_KEYWORDS  = {"retirement", "pension", "annuity"}
_DEBT_KEYWORDS        = {"liquid", "overnight", "money market", "ultra short", "short duration",
                         "medium duration", "long duration", "gilt", "credit risk", "banking psu"}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class PersonaResult:
    persona: str
    confidence: int          # 0–100
    label: str
    icon: str
    color: str
    signals: list[str]       # human-readable reasoning shown to user
    inferred: bool = True    # False when user manually overrode
    scores: dict[str, int] = field(default_factory=dict)
    inferred_at: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_keyword(name: str, keywords: set[str]) -> bool:
    n = name.lower()
    return any(k in n for k in keywords)


def _fmt_crore(value: float) -> str:
    if value >= 10_000_000:
        return f"₹{value / 10_000_000:.1f} Cr"
    return f"₹{value / 100_000:.0f}L"


# ── Main inference function ───────────────────────────────────────────────────

async def infer_persona(
    user_id: str,
    db,
    user_profile: Optional[dict] = None,
) -> PersonaResult:
    """
    Infer investor persona from MongoDB holdings, SIPs, and user profile.
    Returns a PersonaResult with the best-match persona, confidence, and signals.
    """
    holdings = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0}
    ).to_list(length=500)

    active_sips = await db.detected_sips.find(
        {"user_id": user_id, "status": "ACTIVE"}, {"_id": 0}
    ).to_list(length=200)

    # Portfolio value from snapshot (faster than recomputing from holdings)
    snapshot = await db.portfolio_snapshots.find_one(
        {"user_id": user_id},
        sort=[("snapshot_date", -1)],
        projection={"_id": 0, "total_value": 1},
    )

    # ── No holdings yet — fall back to journey type ───────────────────────
    if not holdings:
        return _journey_fallback(user_profile)

    # ── Aggregate signals from holdings ──────────────────────────────────
    type_value: dict[str, float] = {}
    type_count: dict[str, int] = {}
    has_elss = False
    has_retirement_fund = False
    has_debt_heavy = False
    debt_fund_count = 0

    for h in holdings:
        at = h.get("asset_type", "other")
        qty = h.get("quantity", 0) or 0
        price = h.get("current_price", 0) or 0
        val = qty * price
        name = h.get("name", "")

        type_value[at] = type_value.get(at, 0) + val
        type_count[at] = type_count.get(at, 0) + 1

        if _has_keyword(name, _ELSS_KEYWORDS):
            has_elss = True
        if _has_keyword(name, _RETIREMENT_KEYWORDS):
            has_retirement_fund = True
        if at == "mutual_fund" and _has_keyword(name, _DEBT_KEYWORDS):
            debt_fund_count += 1

    # Prefer snapshot total (enriched NAV) over raw holdings multiplication
    total_value = (snapshot or {}).get("total_value") or sum(type_value.values()) or 1

    mf_value   = type_value.get("mutual_fund", 0)
    eq_value   = type_value.get("equity", 0)
    mf_pct     = mf_value / total_value * 100
    eq_pct     = eq_value / total_value * 100
    mf_count   = type_count.get("mutual_fund", 0)
    eq_count   = type_count.get("equity", 0)
    total_cnt  = len(holdings)

    active_sip_count   = len(active_sips)
    monthly_sip_total  = sum(s.get("amount", 0) or 0 for s in active_sips)

    debt_pct = debt_fund_count / max(mf_count, 1) * 100 if mf_count else 0
    has_debt_heavy = debt_pct > 50

    # Profile signals
    profile       = user_profile or {}
    journey_type  = profile.get("journey_type", "")
    quick_setup   = profile.get("quick_setup") or {}
    age           = quick_setup.get("age")
    goal          = quick_setup.get("goal")

    # ── Score board ───────────────────────────────────────────────────────
    scores: dict[str, int] = {p: 0 for p in PERSONAS}
    signals: list[str] = []

    # MFD — explicit at sign-up
    if journey_type == "mfd_advisor":
        scores["mfd_advisor"] += 100
        signals.append("Registered as MFD / Advisor at sign-up")

    # HNI
    if total_value >= 50_000_000:       # ≥ ₹5 Cr
        scores["hni_investor"] += 80
        signals.append(f"Portfolio size {_fmt_crore(total_value)} — UHNI tier")
    elif total_value >= 10_000_000:     # ≥ ₹1 Cr
        scores["hni_investor"] += 55
        signals.append(f"Portfolio size {_fmt_crore(total_value)} — HNI tier")

    # Mutual Fund Investor
    if mf_pct >= 70:
        scores["mutual_fund_investor"] += 55
        signals.append(f"{mf_pct:.0f}% of portfolio in mutual funds")
    elif mf_pct >= 50:
        scores["mutual_fund_investor"] += 35
        signals.append(f"{mf_pct:.0f}% of portfolio in mutual funds")
    elif mf_pct >= 30:
        scores["mutual_fund_investor"] += 15

    if active_sip_count >= 5:
        scores["mutual_fund_investor"] += 35
        signals.append(f"{active_sip_count} active SIPs — systematic investor")
    elif active_sip_count >= 3:
        scores["mutual_fund_investor"] += 25
        signals.append(f"{active_sip_count} active SIPs detected")
    elif active_sip_count >= 1:
        scores["mutual_fund_investor"] += 12
        signals.append(f"{active_sip_count} active SIP detected")

    if mf_count >= 8:
        scores["mutual_fund_investor"] += 10
        signals.append(f"Holds {mf_count} mutual fund schemes")

    # Stock Investor
    if eq_pct >= 60:
        scores["stock_investor"] += 55
        signals.append(f"{eq_pct:.0f}% of portfolio in individual equities")
    elif eq_pct >= 40:
        scores["stock_investor"] += 35
        signals.append(f"{eq_pct:.0f}% of portfolio in equities")
    elif eq_pct >= 20:
        scores["stock_investor"] += 15

    if eq_count >= 15:
        scores["stock_investor"] += 25
        signals.append(f"Holds {eq_count} individual stocks")
    elif eq_count >= 8:
        scores["stock_investor"] += 15
        signals.append(f"Holds {eq_count} individual stocks")

    # Tax Saver
    if has_elss:
        scores["tax_saver"] += 45
        scores["mutual_fund_investor"] += 8   # ELSS = also MF investor
        signals.append("ELSS / tax-saving funds detected")
    if goal == "wealth" and has_elss:
        scores["tax_saver"] += 15

    # Retirement Planner
    if has_retirement_fund:
        scores["retirement_planner"] += 45
        signals.append("Retirement / pension fund in portfolio")
    if goal == "retirement":
        scores["retirement_planner"] += 30
        signals.append("Retirement set as primary goal")
    if age and age >= 55:
        scores["retirement_planner"] += 20
        signals.append(f"Age {age} — retirement planning horizon")
    elif age and age >= 45:
        scores["retirement_planner"] += 10
    if has_debt_heavy:
        scores["retirement_planner"] += 10   # conservative shift signal

    # Beginner Investor — small, early-stage portfolio
    if total_cnt <= 3 and total_value < 200_000:
        scores["beginner_investor"] += 65
        signals.append("Small, early-stage portfolio — beginner profile")
    elif total_cnt <= 5 and total_value < 500_000:
        scores["beginner_investor"] += 40
        signals.append("Early-stage portfolio with few holdings")

    # Retail Investor — well-diversified, base catch-all
    if mf_pct >= 20 and eq_pct >= 10 and active_sip_count >= 1:
        scores["retail_investor"] += 35
        signals.append("Diversified across funds and equities with SIPs")
    elif mf_pct >= 20 or (eq_pct >= 20 and mf_pct >= 10):
        scores["retail_investor"] += 20
    scores["retail_investor"] += 8   # base — last-resort catch-all

    # Suppress retail when HNI or MF wins clearly
    if scores["hni_investor"] >= 55 or scores["mutual_fund_investor"] >= 55:
        scores["retail_investor"] = max(0, scores["retail_investor"] - 20)

    # Traders — never inferred from CAS; leave at 0

    # ── Pick winner ───────────────────────────────────────────────────────
    winner = max(scores, key=lambda p: scores[p])
    max_score = scores[winner]

    # HNI stacks well with other personas — if it's very close to the MF/stock
    # winner, prefer HNI as it has wider implications for the dashboard
    if (
        winner != "hni_investor"
        and scores["hni_investor"] >= 55
        and scores["hni_investor"] >= max_score - 10
    ):
        winner = "hni_investor"
        max_score = scores["hni_investor"]

    confidence = min(100, max_score)
    meta = PERSONAS[winner]

    # Deduplicate signals, cap at 5 for display
    seen: set[str] = set()
    deduped: list[str] = []
    for s in signals:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    deduped = deduped[:5]

    return PersonaResult(
        persona=winner,
        confidence=confidence,
        label=meta["label"],
        icon=meta["icon"],
        color=meta["color"],
        signals=deduped,
        inferred=True,
        scores=scores,
        inferred_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Fallback when no holdings exist ──────────────────────────────────────────

def _journey_fallback(user_profile: Optional[dict]) -> PersonaResult:
    profile      = user_profile or {}
    journey_type = profile.get("journey_type", "")
    quick_setup  = profile.get("quick_setup") or {}
    goal         = quick_setup.get("goal")

    if journey_type == "mfd_advisor":
        persona = "mfd_advisor"
        signals = ["Registered as MFD / Advisor at sign-up"]
    elif journey_type == "new_investor":
        persona = "beginner_investor"
        signals = ["No portfolio uploaded yet — new investor journey"]
    elif goal == "retirement":
        persona = "retirement_planner"
        signals = ["Retirement selected as primary goal"]
    else:
        persona = "retail_investor"
        signals = ["No holdings uploaded yet — using journey type as signal"]

    meta = PERSONAS[persona]
    return PersonaResult(
        persona=persona,
        confidence=25,
        label=meta["label"],
        icon=meta["icon"],
        color=meta["color"],
        signals=signals,
        inferred=True,
        scores={},
        inferred_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Re-inference trigger (call after CAS upload) ──────────────────────────────

async def refresh_persona(user_id: str, db) -> PersonaResult:
    """
    Re-infer persona and persist to user_profiles.
    Called automatically after CAS upload completes.
    """
    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0})

    # Don't overwrite a manually set persona
    if profile and profile.get("persona_source") == "manual":
        existing = profile.get("persona", {})
        meta = PERSONAS.get(existing.get("persona", "retail_investor"), PERSONAS["retail_investor"])
        return PersonaResult(
            persona=existing.get("persona", "retail_investor"),
            confidence=existing.get("confidence", 80),
            label=meta["label"],
            icon=meta["icon"],
            color=meta["color"],
            signals=existing.get("signals", []),
            inferred=False,
            scores={},
            inferred_at=existing.get("inferred_at", ""),
        )

    result = await infer_persona(user_id, db, profile)

    await db.user_profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "persona": {
                    "persona": result.persona,
                    "confidence": result.confidence,
                    "label": result.label,
                    "icon": result.icon,
                    "color": result.color,
                    "signals": result.signals,
                    "inferred": result.inferred,
                    "inferred_at": result.inferred_at,
                },
                "persona_source": "inferred",
                "persona_updated_at": result.inferred_at,
            }
        },
        upsert=True,
    )
    return result
