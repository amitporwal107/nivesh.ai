"""Portfolio Remediation Engine.

Produces ranked, concrete, direction-correct recommendations that move
a user's portfolio toward Balanced on each concentration lens.

Pipeline:
  1. Duplicate Regular/Direct plan detection
     (highest leverage — fee saving, no portfolio change)
  2. Redundant cluster consolidation
     (same-category funds with high overlap → reduce to one)
  3. AMC over-concentration trim
     (specific fund(s) to reduce, amount, redeploy destination)
  4. Sector over-concentration trim
     (SIP redirection preferred; redemption if gap is large)

Each recommendation includes:
  - action_kind: duplicate_plan | consolidation | trim_amc | trim_sector
  - title, why, action (plain-language)
  - amount_rs: rupees to move (0 for SIP-only actions)
  - contributors: [{name, pct_of_exposure, value_rs}]
  - before_after: [{lens_id, lens_label, before/after verdict+hhi+eff_n+pct}]
  - redeploy_to: suggestion string (or None)
  - caveats: [{icon, text}]  — tax / lock-in / exit-load
  - leverage_score: 0-100 (higher = do this first)
  - annual_saving_rs: non-zero only for fee-reduction actions
"""
from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Thresholds (must mirror _build_section warn_largest_pct) ─────────
_CAP = {"amc": 30.0, "sector": 35.0, "company": 10.0, "group": 15.0}
_TARGET_BUFFER = 3.0   # land this many pts inside cap, not on the line
_ER_REGULAR    = 0.018  # 1.8% estimated expense ratio for Regular plans
_ER_DIRECT     = 0.005  # 0.5% estimated expense ratio for Direct plans


# ── Helpers ───────────────────────────────────────────────────────────

def _holding_value(h: dict) -> float:
    return float(h.get("quantity") or 0) * float(h.get("current_price") or 0)


def _is_regular(name: str) -> bool:
    n = (name or "").lower()
    return "regular" in n or ("direct" not in n and "growth" in n)


def _is_direct(name: str) -> bool:
    return "direct" in (name or "").lower()


def _scheme_base(name: str) -> str:
    """Strip plan/option identifiers to get a canonical scheme name.

    'HDFC Flexi Cap Fund - Direct Plan - Growth'
    → 'hdfc flexi cap fund'
    """
    n = (name or "").lower()
    n = re.sub(
        r"\b(direct|regular|growth|idcw|dividend|payout|reinvestment|plan|option|fund)\b",
        " ", n,
    )
    n = re.sub(r"[-–—/|]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _hhi(weights_rs: list[float]) -> float:
    total = sum(weights_rs) or 1.0
    return sum((w / total) ** 2 for w in weights_rs)


def _eff_n(weights_rs: list[float]) -> float:
    h = _hhi(weights_rs)
    return round(1.0 / h, 1) if h > 0 else 0.0


def _simulate_amc_trim(
    amc_name: str,
    trim_rs: float,
    amc_items: list[dict],
    total_value: float,
) -> tuple[float, float, float]:
    """Return (new_amc_pct, new_hhi_x10000, new_eff_n) after removing
    trim_rs from amc_name.  Assumes freed capital leaves the portfolio
    (worst-case; redeploy to a different AMC keeps total_value stable
    but distributes concentration differently)."""
    new_total = max(total_value - trim_rs, 1.0)
    new_weights = []
    for it in amc_items:
        v = (it["value_inr"] or 0)
        if it["name"] == amc_name:
            v = max(0.0, v - trim_rs)
        new_weights.append(v)
    new_amc_pct = round(
        (max(0.0, (amc_items[0]["value_inr"] or 0) - trim_rs) / new_total) * 100
        if amc_items and amc_items[0]["name"] == amc_name
        else sum(
            (w / new_total) * 100
            for w, it in zip(new_weights, amc_items)
            if it["name"] == amc_name
        ),
        1,
    )
    # Recompute HHI over new weights (new_total normalises)
    h = _hhi(new_weights)
    new_eff_n = round(1.0 / h, 1) if h > 0 else 0.0
    return new_amc_pct, round(h * 10000), new_eff_n


def _verdict(pct: float, cap: float) -> str:
    if pct >= cap:
        return "over-concentrated"
    if pct >= cap - 5:
        return "elevated"
    return "balanced"


# ── 1. Duplicate Regular/Direct plan detection ────────────────────────

def _find_duplicate_plans(mf_holdings: list[dict]) -> list[dict]:
    """Return list of {regular_holding, direct_holding, scheme_base} for
    funds where the user holds both the Regular and Direct plan."""
    by_scheme: dict[str, dict[str, dict]] = {}
    for h in mf_holdings:
        name = h.get("name") or ""
        base = _scheme_base(name)
        if not base:
            continue
        by_scheme.setdefault(base, {})
        if _is_direct(name):
            by_scheme[base]["direct"] = h
        elif _is_regular(name):
            by_scheme[base]["regular"] = h

    duplicates = []
    for base, plans in by_scheme.items():
        if "regular" in plans and "direct" in plans:
            duplicates.append({
                "scheme_base":     base,
                "regular_holding": plans["regular"],
                "direct_holding":  plans["direct"],
            })
    return duplicates


# ── 2. Build individual recommendation dicts ─────────────────────────

def _rec_duplicate_plan(dup: dict, total_value: float) -> dict:
    reg = dup["regular_holding"]
    drct = dup["direct_holding"]
    reg_value  = _holding_value(reg)
    drct_value = _holding_value(drct)
    annual_saving = round(reg_value * (_ER_REGULAR - _ER_DIRECT), 0)

    return {
        "id":          f"dup-{_scheme_base(reg.get('name',''))[:30]}",
        "action_kind": "duplicate_plan",
        "title":       f"Switch {reg.get('name','Regular plan')} → Direct plan",
        "why": (
            f"You hold the same scheme in two plans. The Regular plan charges "
            f"~{_ER_REGULAR*100:.1f}% p.a. vs ~{_ER_DIRECT*100:.1f}% for the Direct plan — "
            f"identical portfolio, higher fees. Switching saves "
            f"₹{annual_saving:,.0f}/yr with no change to your portfolio."
        ),
        "action": (
            f"Redeem {reg.get('name','Regular plan')} (₹{reg_value:,.0f}) "
            f"and reinvest into {drct.get('name','Direct plan')}."
        ),
        "amount_rs":        round(reg_value, 0),
        "annual_saving_rs": annual_saving,
        "contributors": [
            {"name": reg.get("name", ""), "pct_of_exposure": 100, "value_rs": round(reg_value, 0)},
        ],
        "before_after": [],   # no concentration change — same holdings, lower fee
        "redeploy_to": drct.get("name"),
        "caveats": [
            {"icon": "tax",  "text": "Units held > 1 year: LTCG at 10% above ₹1 L/yr. Units < 1 year: STCG at 15%."},
            {"icon": "lock", "text": "ELSS units have a 3-year lock-in per instalment — initiate switch only on unlocked units."},
        ],
        "leverage_score": 95,
    }


def _rec_cluster(
    cluster: dict,
    total_value: float,
    amc_items: list[dict],
    sector_items: list[dict],
) -> dict:
    members = cluster["members"]
    members_sorted = sorted(members, key=lambda m: -m["current_value_rs"])
    keep    = members_sorted[0]   # highest value = least disruptive to exit
    exit_ms = members_sorted[1:]
    exit_value = sum(m["current_value_rs"] for m in exit_ms)
    annual_saving = round(exit_value * (_ER_REGULAR - _ER_DIRECT), 0)
    avg_ov = cluster.get("avg_overlap_pct", 0)
    cat    = cluster.get("sebi_subcategory") or cluster.get("sebi_category") or "similar category"

    return {
        "id":          f"cluster-{(keep.get('name') or '')[:20]}",
        "action_kind": "consolidation",
        "title":       f"Consolidate {len(members)} {cat} funds into 1",
        "why": (
            f"These {len(members)} funds share {avg_ov:.0f}% average overlap in their "
            f"underlying holdings. You are paying {len(members)}× management fees for "
            f"effectively one exposure. Keeping {keep.get('name','')} and exiting the rest "
            f"reduces fund count without reducing diversification."
        ),
        "action": (
            f"Exit: {', '.join(m['name'] for m in exit_ms)}. "
            f"Retain: {keep.get('name','')}. "
            f"Total capital to redeploy: ₹{exit_value:,.0f}."
        ),
        "amount_rs":        round(exit_value, 0),
        "annual_saving_rs": annual_saving,
        "contributors": [
            {"name": m["name"], "pct_of_exposure": round(m["current_value_rs"] / max(cluster["total_value_rs"], 1) * 100, 1), "value_rs": round(m["current_value_rs"], 0)}
            for m in exit_ms
        ],
        "before_after": [],  # populated by caller with AMC simulation
        "redeploy_to": (
            f"Redirect freed SIPs to under-weight categories (Mid Cap / Small Cap / "
            f"International) — avoids re-concentrating in the same large-cap universe."
        ),
        "caveats": [
            {"icon": "tax",  "text": "Equity funds held > 1 year: LTCG at 10% above ₹1 L annual exemption. Consider staggering redemptions across two financial years to stay within the exemption."},
            {"icon": "exit", "text": "Check for exit loads — most equity funds charge 1% if redeemed within 12 months. Units held > 1 year are typically exit-load free."},
        ],
        "leverage_score": min(90, 60 + round(avg_ov / 4)),
    }


def _rec_amc_trim(
    item: dict,
    amc_section: dict,
    holdings: list[dict],
    total_value: float,
    full_envelope: dict,
) -> dict:
    amc_name  = item["name"]
    amc_pct   = item["pct"]
    cap       = float(amc_section.get("caution_pct") or _CAP["amc"])
    target    = cap - _TARGET_BUFFER
    gap_pct   = amc_pct - target
    trim_rs   = round((gap_pct / 100) * total_value, 0)

    # Find the largest fund from this AMC
    amc_holdings = sorted(
        [h for h in holdings
         if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}
         and _scheme_base(h.get("name","")).find(_scheme_base(amc_name)) >= 0
         or (h.get("amc_name") or "").lower() == amc_name.lower()],
        key=lambda h: -_holding_value(h),
    )

    # Fallback: match by AMC name prefix in fund name
    if not amc_holdings:
        amc_holdings = sorted(
            [h for h in holdings
             if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}
             and amc_name.lower().split()[0] in (h.get("name") or "").lower()],
            key=lambda h: -_holding_value(h),
        )

    contributors = [
        {
            "name": h.get("name", ""),
            "pct_of_exposure": round(_holding_value(h) / max(item["value_inr"], 1) * 100, 1),
            "value_rs": round(_holding_value(h), 0),
        }
        for h in amc_holdings[:4]
    ]

    # Simulate trim on the AMC's items list
    amc_items = amc_section.get("items") or []
    before_hhi  = round((amc_section.get("hhi") or 0) * 10000)
    before_effn = amc_section.get("effective_n") or 0

    new_amc_pct, after_hhi, after_effn = _simulate_amc_trim(
        amc_name, trim_rs, amc_items, total_value,
    )

    before_after = [{
        "lens_id":       "amc",
        "lens_label":    "AMC",
        "before_verdict": _verdict(amc_pct, cap),
        "after_verdict":  _verdict(new_amc_pct, cap),
        "before_pct":     round(amc_pct, 1),
        "after_pct":      round(new_amc_pct, 1),
        "before_hhi":     before_hhi,
        "after_hhi":      after_hhi,
        "before_eff_n":   before_effn,
        "after_eff_n":    after_effn,
    }]

    # Find under-weight AMCs to recommend as redeploy destinations
    amc_items_sorted = sorted(amc_items, key=lambda x: x["pct"])
    low_amc = next(
        (x["name"] for x in amc_items_sorted if x["pct"] < 10 and x["name"] != amc_name),
        None,
    )
    redeploy = (
        f"Redeploy into a fund from {low_amc} ({next((x['pct'] for x in amc_items_sorted if x['name']==low_amc),0):.1f}% of portfolio — well under-weight) "
        f"to improve AMC diversification without leaving the asset class."
        if low_amc else
        "Redeploy into an AMC currently below 10% of your portfolio."
    )

    top_fund = amc_holdings[0].get("name", amc_name) if amc_holdings else amc_name
    leverage = min(85, 50 + round(gap_pct * 2))

    return {
        "id":          f"trim-amc-{amc_name[:20]}",
        "action_kind": "trim_amc",
        "title":       f"Reduce {amc_name} exposure from {amc_pct:.1f}% → {new_amc_pct:.1f}%",
        "why": (
            f"{amc_name} is {amc_pct:.1f}% of your mutual-fund portfolio — "
            f"{gap_pct:.1f}pt above the {cap:.0f}% cap. If {amc_name} faces "
            f"operational issues (fund-house risk), a large share of your "
            f"portfolio is simultaneously affected."
        ),
        "action": (
            f"Redeem ₹{trim_rs:,.0f} from {top_fund} "
            f"(largest {amc_name} holding). This brings {amc_name} from "
            f"{amc_pct:.1f}% to ~{new_amc_pct:.1f}%, inside the {cap:.0f}% cap."
        ),
        "amount_rs":        trim_rs,
        "annual_saving_rs": 0,
        "contributors":     contributors,
        "before_after":     before_after,
        "redeploy_to":      redeploy,
        "caveats": [
            {"icon": "tax",  "text": f"Equity funds held > 1 year: LTCG at 10% above ₹1 L annual exemption."},
            {"icon": "exit", "text": "Check for exit load — most equity funds charge 1% if redeemed within 12 months."},
        ],
        "leverage_score": leverage,
    }


def _rec_sector_sip(
    item: dict,
    sector_section: dict,
    holdings: list[dict],
    total_value: float,
) -> dict:
    sector_name = item["name"]
    sector_pct  = item["pct"]
    cap         = float(sector_section.get("caution_pct") or _CAP["sector"])
    target      = cap - _TARGET_BUFFER
    gap_pct     = sector_pct - target

    # Find sector contributors from holdings list
    sector_contributors = [
        h_name for h_name in (item.get("holdings") or [])
    ]

    sector_items = sector_section.get("items") or []
    under_weight = [
        s["name"] for s in sorted(sector_items, key=lambda x: x["pct"])
        if s["pct"] < 10 and s["name"] not in {"Unclassified", "Other", "Gold"}
        and s["name"] != sector_name
    ][:2]

    redeploy = (
        f"Redirect SIPs toward {' and '.join(under_weight)} "
        f"(currently under-weight in your portfolio)."
        if under_weight else
        "Redirect SIPs toward sectors currently under 10% of your portfolio."
    )

    return {
        "id":          f"trim-sector-{sector_name[:20]}",
        "action_kind": "trim_sector",
        "title":       f"Reduce {sector_name} sector from {sector_pct:.1f}% → ~{target:.0f}%",
        "why": (
            f"{sector_name} is {sector_pct:.1f}% of your portfolio — "
            f"{gap_pct:.1f}pt above the {cap:.0f}% sector cap. "
            f"A single adverse sector event affects a disproportionate share of your wealth."
        ),
        "action": (
            f"Pause or reduce SIPs into {sector_name}-heavy funds. "
            f"Direct new SIP flows to under-weight sectors. "
            f"This is tax-efficient (no redemption needed) and brings {sector_name} "
            f"below {cap:.0f}% over 6–12 months."
        ),
        "amount_rs":        0,  # SIP redirect, not redemption
        "annual_saving_rs": 0,
        "contributors": [
            {"name": c, "pct_of_exposure": None, "value_rs": None}
            for c in sector_contributors[:4]
        ],
        "before_after": [{
            "lens_id":       "sector",
            "lens_label":    "Sector",
            "before_verdict": _verdict(sector_pct, cap),
            "after_verdict":  _verdict(target + 1, cap),
            "before_pct":     round(sector_pct, 1),
            "after_pct":      round(target + 1, 1),
            "before_hhi":     round((sector_section.get("hhi") or 0) * 10000),
            "after_hhi":      None,  # not simulated for SIP-redirect
            "before_eff_n":   sector_section.get("effective_n"),
            "after_eff_n":    None,
        }],
        "redeploy_to": redeploy,
        "caveats": [
            {"icon": "tax", "text": "SIP redirection has zero tax impact — no redemption occurs. This is the preferred first step for sector over-concentration."},
        ],
        "leverage_score": min(75, 45 + round(gap_pct * 2)),
    }


# ── Public API ────────────────────────────────────────────────────────

def compute_remediation(
    holdings: list[dict],
    concentration_envelope: dict,
    *,
    clusters: list[dict] | None = None,
) -> list[dict]:
    """Return a ranked list of remediation recommendations.

    Args:
      holdings: raw Mongo holding docs (name, ticker, asset_type,
                quantity, current_price, amc_name, category, …)
      concentration_envelope: output of compute_concentration()
      clusters: output of cluster_overlapping_funds() — optional;
                if not provided, cluster recommendations are skipped.

    Returns:
      List of recommendation dicts, sorted by leverage_score DESC.
      Empty list when portfolio is Balanced on all lenses.
    """
    total_value = float(concentration_envelope.get("total_value") or 0)
    if total_value <= 0:
        return []

    mf_holdings = [
        h for h in holdings
        if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}
    ]

    recommendations: list[dict] = []

    # ── 1. Duplicate plans (highest priority) ──────────────────────────
    try:
        for dup in _find_duplicate_plans(mf_holdings):
            recommendations.append(_rec_duplicate_plan(dup, total_value))
    except Exception:
        logger.exception("Duplicate plan detection failed")

    # ── 2. Redundant clusters ──────────────────────────────────────────
    try:
        for cluster in (clusters or [])[:3]:
            if cluster.get("avg_overlap_pct", 0) >= 50:
                rec = _rec_cluster(
                    cluster, total_value,
                    (concentration_envelope.get("amc") or {}).get("items") or [],
                    (concentration_envelope.get("sector") or {}).get("items") or [],
                )
                recommendations.append(rec)
    except Exception:
        logger.exception("Cluster remediation failed")

    # ── 3. AMC over-concentration ──────────────────────────────────────
    try:
        amc_section = concentration_envelope.get("amc") or {}
        cap_amc = float(amc_section.get("caution_pct") or _CAP["amc"])
        for item in (amc_section.get("items") or []):
            if (item.get("pct") or 0) > cap_amc:
                rec = _rec_amc_trim(
                    item, amc_section, holdings, total_value, concentration_envelope,
                )
                # Avoid duplicate if a cluster rec already covers the same AMC
                already_covered = any(
                    r["action_kind"] == "consolidation"
                    and item["name"].lower().split()[0] in r["title"].lower()
                    for r in recommendations
                )
                if not already_covered:
                    recommendations.append(rec)
    except Exception:
        logger.exception("AMC trim remediation failed")

    # ── 4. Sector over-concentration ───────────────────────────────────
    try:
        sector_section = concentration_envelope.get("sector") or {}
        cap_sec = float(sector_section.get("caution_pct") or _CAP["sector"])
        for item in (sector_section.get("items") or []):
            if (item.get("pct") or 0) > cap_sec:
                recommendations.append(
                    _rec_sector_sip(item, sector_section, holdings, total_value)
                )
    except Exception:
        logger.exception("Sector trim remediation failed")

    # ── Sort & cap ─────────────────────────────────────────────────────
    recommendations.sort(key=lambda r: -(r.get("leverage_score") or 0))
    return recommendations[:6]


__all__ = ["compute_remediation"]
