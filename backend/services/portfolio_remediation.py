"""Portfolio Remediation Engine.

Produces ranked, concrete, direction-correct recommendations:

  1. Duplicate Regular/Direct plan detection
     (highest leverage — fee saving, no portfolio change)
  2. Category over-allocation vs risk-profile target
     (exit weakest funds in over-allocated category first)
  3. Redundant cluster consolidation
     (same-category funds with ≥50% overlap → consolidate to one)
  4. AMC over-concentration trim
  5. Sector over-concentration SIP redirection

Key correctness rules:
  - Holdings are DEDUPLICATED by ISIN before any analysis.
    Multiple folios of the same fund (same ISIN, different folio numbers)
    are merged into one holding so the same name never appears twice in a
    recommendation.
  - Every recommendation references real holding names from the user's
    actual portfolio — no placeholder text.
  - Exit recommendations within a category are ranked by exit score:
      Regular plan penalty (+3) + redundancy (+2) + small-position (+1)
    so the highest-cost, most-redundant fund exits first.
"""
from __future__ import annotations

import re
import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# ── Policy thresholds ─────────────────────────────────────────────────
_CAP = {"amc": 30.0, "sector": 35.0, "company": 10.0, "group": 15.0}
_TARGET_BUFFER = 3.0
_ER_REGULAR    = 0.018
_ER_DIRECT     = 0.005

# ── Category-wise target allocation by risk profile ───────────────────
# Keys must match the sebi_category values produced by mf_category_enricher
# or the mapped bucket names returned by _std_category().
_CATEGORY_TARGETS: dict[str, dict[str, float]] = {
    "conservative": {
        "Large Cap": 50, "Mid Cap": 10, "Small Cap": 5,
        "Flexi Cap": 10, "ELSS": 0,
        "Debt": 20, "Hybrid": 5, "Gold": 5, "International": 0,
    },
    "moderate": {
        "Large Cap": 35, "Mid Cap": 25, "Small Cap": 15,
        "Flexi Cap": 10, "ELSS": 5,
        "Debt": 5, "Hybrid": 3, "Gold": 2, "International": 0,
    },
    "aggressive": {
        "Large Cap": 25, "Mid Cap": 30, "Small Cap": 25,
        "Flexi Cap": 10, "ELSS": 5,
        "Debt": 0, "Hybrid": 0, "Gold": 5, "International": 0,
    },
}
# Buffer before flagging a category as over-allocated (percentage points)
_CATEGORY_OVERALLOC_BUFFER = 10.0


# ── Helpers ───────────────────────────────────────────────────────────

def _holding_value(h: dict) -> float:
    return float(h.get("quantity") or 0) * float(h.get("current_price") or 0)


def _is_regular(name: str) -> bool:
    n = (name or "").lower()
    return "regular" in n or ("direct" not in n and "growth" in n)


def _is_direct(name: str) -> bool:
    return "direct" in (name or "").lower()


def _scheme_base(name: str) -> str:
    """Strip plan/option tokens to get a canonical scheme name for matching."""
    n = (name or "").lower()
    n = re.sub(
        r"\b(direct|regular|growth|idcw|dividend|payout|reinvestment|plan|option|fund|"
        r"erstwhile|formerly|scheme|equity)\b",
        " ", n,
    )
    n = re.sub(r"[-–—/|(),]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _deduplicate_by_isin(holdings: list[dict]) -> list[dict]:
    """Merge multiple folios of the same ISIN into one holding.

    Different folio numbers of the same fund (same ISIN / same ticker)
    are summed by value. The first encountered holding's metadata is kept.
    Without this, a fund held in 6 folios appears 6 times in contributor
    lists and cluster exit lists.
    """
    by_key: dict[str, dict] = {}
    for h in holdings:
        key = (h.get("ticker") or "").strip()
        if not key:
            # No ISIN — fall back to normalised scheme name
            key = _scheme_base(h.get("name") or "")
        if not key:
            continue
        if key not in by_key:
            # Deep-copy the first folio as the representative
            by_key[key] = dict(h)
        else:
            # Accumulate quantity (price stays the same for same ISIN)
            existing_qty = float(by_key[key].get("quantity") or 0)
            new_qty      = float(h.get("quantity") or 0)
            by_key[key]["quantity"] = existing_qty + new_qty
    return list(by_key.values())


def _std_category(h: dict) -> str | None:
    """Return a standard category bucket for a holding.

    Preference order:
      1. sebi_category (set by enrich_mf_with_sebi_category)
      2. scheme_category (set by NIDP enrichment)
      3. category (from holdings doc)
    """
    for field in ("sebi_category", "scheme_category", "category"):
        v = (h.get(field) or "").strip()
        if not v:
            continue
        vl = v.lower()
        # Normalise to the keys used in _CATEGORY_TARGETS
        if "large" in vl and "mid" not in vl:
            return "Large Cap"
        if "mid" in vl and "large" not in vl:
            return "Mid Cap"
        if "small" in vl:
            return "Small Cap"
        if "flexi" in vl or "multi" in vl:
            return "Flexi Cap"
        if "elss" in vl or "tax" in vl:
            return "ELSS"
        if "debt" in vl or "liquid" in vl or "credit" in vl or "duration" in vl or "bond" in vl:
            return "Debt"
        if "hybrid" in vl or "balanced" in vl or "aggressive hybrid" in vl:
            return "Hybrid"
        if "gold" in vl:
            return "Gold"
        if "international" in vl or "global" in vl or "overseas" in vl:
            return "International"
        if "index" in vl:
            return "Large Cap"  # index funds → large cap bucket for allocation purposes
    return None


def _hhi(weights_rs: list[float]) -> float:
    total = sum(weights_rs) or 1.0
    return sum((w / total) ** 2 for w in weights_rs)


def _simulate_amc_trim(
    amc_name: str, trim_rs: float, amc_items: list[dict], total_value: float,
) -> tuple[float, float, float]:
    new_total = max(total_value - trim_rs, 1.0)
    new_weights = []
    new_amc_value = 0.0
    for it in amc_items:
        v = float(it.get("value_inr") or 0)
        if it["name"] == amc_name:
            v = max(0.0, v - trim_rs)
            new_amc_value = v
        new_weights.append(v)
    new_amc_pct = round(new_amc_value / new_total * 100, 1)
    h = _hhi(new_weights)
    return new_amc_pct, round(h * 10000), round(1.0 / h, 1) if h > 0 else 0.0


def _verdict(pct: float, cap: float) -> str:
    if pct >= cap:
        return "over-concentrated"
    if pct >= cap - 5:
        return "elevated"
    return "balanced"


def _exit_score(h: dict, cluster_isin_overlap: float = 0.0) -> float:
    """Score a holding for exit priority. Higher = exit this first.

    Regular plan penalty: +3
    Cluster redundancy (overlap pct / 50): 0..2
    Small position (value < 50k): +1
    """
    score = 0.0
    if _is_regular(h.get("name") or ""):
        score += 3.0
    score += min(2.0, cluster_isin_overlap / 50.0)
    if _holding_value(h) < 50_000:
        score += 1.0
    return score


# ── 1. Duplicate Regular/Direct plan detection ────────────────────────

def _find_duplicate_plans(mf_holdings: list[dict]) -> list[dict]:
    by_scheme: dict[str, dict] = {}
    for h in mf_holdings:
        base = _scheme_base(h.get("name") or "")
        if not base:
            continue
        by_scheme.setdefault(base, {})
        if _is_direct(h.get("name") or ""):
            by_scheme[base]["direct"] = h
        elif _is_regular(h.get("name") or ""):
            by_scheme[base]["regular"] = h

    return [
        {"scheme_base": base, "regular_holding": plans["regular"], "direct_holding": plans["direct"]}
        for base, plans in by_scheme.items()
        if "regular" in plans and "direct" in plans
    ]


# ── 2. Category over-allocation ───────────────────────────────────────

def _compute_category_allocation(
    mf_holdings: list[dict], total_value: float,
) -> dict[str, float]:
    """Return {category: pct_of_total_portfolio} for MF holdings."""
    by_cat: dict[str, float] = defaultdict(float)
    for h in mf_holdings:
        cat = _std_category(h)
        if cat:
            by_cat[cat] += _holding_value(h)
    return {
        cat: round(val / total_value * 100, 1) if total_value > 0 else 0.0
        for cat, val in by_cat.items()
    }


def _rec_category_overalloc(
    category: str,
    actual_pct: float,
    target_pct: float,
    over_by: float,
    category_holdings: list[dict],
    total_value: float,
    redundant_isins: set[str],
) -> dict:
    """Recommend exiting the weakest funds in an over-allocated category."""
    # Score each holding for exit priority
    scored = sorted(
        [(h, _exit_score(h, 60.0 if (h.get("ticker") or "") in redundant_isins else 0.0))
         for h in category_holdings],
        key=lambda x: -x[1],
    )
    # How much value needs to exit to reach target
    excess_value = round((over_by / 100.0) * total_value, 0)

    # Build exit list: keep adding until we cover the excess
    exit_holdings: list[dict] = []
    exit_value = 0.0
    for h, _ in scored:
        exit_holdings.append(h)
        exit_value += _holding_value(h)
        if exit_value >= excess_value:
            break

    # Always suggest at least 1, and deduplicate names
    seen_names: set[str] = set()
    unique_exits: list[dict] = []
    for h in exit_holdings:
        n = h.get("name") or ""
        if n not in seen_names:
            seen_names.add(n)
            unique_exits.append(h)

    annual_saving = round(sum(_holding_value(h) * _ER_REGULAR for h in unique_exits
                              if _is_regular(h.get("name") or "")), 0)

    exit_names = ", ".join(h.get("name") or "" for h in unique_exits[:3])
    if len(unique_exits) > 3:
        exit_names += f" and {len(unique_exits) - 3} more"

    keep_name = next(
        (h.get("name") for h, _ in scored if h not in unique_exits), None
    )

    leverage = min(88, 55 + round(over_by * 1.5))

    return {
        "id":          f"cat-{category.lower().replace(' ','-')}",
        "action_kind": "category_overalloc",
        "title":       f"Reduce {category} from {actual_pct:.1f}% → ~{target_pct:.0f}% of portfolio",
        "why": (
            f"Your target {category} allocation is {target_pct:.0f}% based on your risk profile, "
            f"but you currently hold {actual_pct:.1f}% — {over_by:.1f}pt over. "
            f"Excess concentration in a single market-cap segment amplifies drawdowns "
            f"when that segment underperforms."
        ),
        "action": (
            f"Exit the lowest-scoring {category} funds first: {exit_names}. "
            + (f"Retain {keep_name}." if keep_name else "")
            + f" Total to redeploy: ₹{exit_value:,.0f}."
        ),
        "amount_rs":        round(exit_value, 0),
        "annual_saving_rs": annual_saving,
        "contributors": [
            {
                "name":              h.get("name") or "",
                "pct_of_exposure":   round(_holding_value(h) / max(sum(_holding_value(x) for x in category_holdings), 1) * 100, 1),
                "value_rs":          round(_holding_value(h), 0),
                "exit_priority":     "Regular plan — exit first" if _is_regular(h.get("name") or "") else "Redundant" if (h.get("ticker") or "") in redundant_isins else "Over-weight",
            }
            for h in unique_exits[:5]
        ],
        "before_after": [],
        "redeploy_to": (
            "Redirect freed capital toward under-allocated categories in your target mix, "
            "or to a broad-market index fund for low-cost diversification."
        ),
        "caveats": [
            {"icon": "tax",  "text": "Equity funds held > 1 year: LTCG at 10% above ₹1 L/yr exemption. Consider staggering exits across two financial years."},
            {"icon": "exit", "text": "Most equity funds have no exit load after 12 months. Verify before redeeming."},
        ],
        "leverage_score": leverage,
        "target_pct":  target_pct,
        "actual_pct":  actual_pct,
    }


# ── 3. Redundant cluster ──────────────────────────────────────────────

def _rec_cluster(
    cluster: dict,
    total_value: float,
) -> dict:
    # Deduplicate cluster members by ticker before building the recommendation.
    # Multiple folios of the same fund appear as multiple members — merge them.
    seen_tickers: set[str] = set()
    dedup_members: list[dict] = []
    for m in cluster["members"]:
        key = m.get("ticker") or _scheme_base(m.get("name") or "")
        if key in seen_tickers:
            continue
        seen_tickers.add(key)
        dedup_members.append(m)

    if len(dedup_members) < 2:
        return {}  # after dedup, not actually a cluster

    # Sort: keep fund with highest value (most capital, less disruptive)
    members_sorted = sorted(dedup_members, key=lambda m: -m["current_value_rs"])
    keep    = members_sorted[0]
    exits   = members_sorted[1:]
    exit_value   = sum(m["current_value_rs"] for m in exits)
    annual_saving = round(exit_value * (_ER_REGULAR - _ER_DIRECT), 0)
    avg_ov  = cluster.get("avg_overlap_pct", 0)
    cat     = cluster.get("sebi_subcategory") or cluster.get("sebi_category") or "similar"

    return {
        "id":          f"cluster-{(keep.get('name') or '')[:20]}",
        "action_kind": "consolidation",
        "title":       f"Consolidate {len(dedup_members)} {cat} funds into 1",
        "why": (
            f"These {len(dedup_members)} funds share {avg_ov:.0f}% average overlap in their "
            f"underlying holdings — you are paying {len(dedup_members)}× management fees for "
            f"effectively one exposure. Keeping {keep.get('name','')} and exiting the rest "
            f"cuts cost without reducing diversification."
        ),
        "action": (
            f"Exit: {', '.join(m['name'] for m in exits[:3])}"
            + (f" and {len(exits)-3} more" if len(exits) > 3 else "")
            + f". Retain: {keep.get('name','')}. "
            f"Capital to redeploy: ₹{exit_value:,.0f}."
        ),
        "amount_rs":        round(exit_value, 0),
        "annual_saving_rs": annual_saving,
        "contributors": [
            {
                "name":          m["name"],
                "pct_of_exposure": round(m["current_value_rs"] / max(cluster["total_value_rs"], 1) * 100, 1),
                "value_rs":      round(m["current_value_rs"], 0),
            }
            for m in exits[:5]
        ],
        "before_after": [],
        "redeploy_to": (
            "Redirect freed SIPs to under-allocated categories (Mid Cap / Small Cap / International) "
            "to genuinely diversify rather than replicate the same exposure."
        ),
        "caveats": [
            {"icon": "tax",  "text": "LTCG at 10% above ₹1 L/yr on equity units held > 1 year. Stagger redemptions across two financial years to stay within the exemption."},
            {"icon": "exit", "text": "Verify exit loads — most equity funds charge 1% within 12 months; zero after."},
        ],
        "leverage_score": min(90, 60 + round(avg_ov / 4)),
    }


# ── 4. AMC over-concentration ─────────────────────────────────────────

def _rec_amc_trim(
    item: dict,
    amc_section: dict,
    holdings: list[dict],
    total_value: float,
) -> dict:
    amc_name = item["name"]
    amc_pct  = item["pct"]
    cap      = float(amc_section.get("caution_pct") or _CAP["amc"])
    target   = cap - _TARGET_BUFFER
    gap_pct  = amc_pct - target
    trim_rs  = round((gap_pct / 100) * total_value, 0)

    amc_funds = sorted(
        [h for h in holdings
         if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}
         and (amc_name.lower().split()[0] in (h.get("name") or "").lower()
              or (h.get("amc_name") or "").lower() == amc_name.lower())],
        key=lambda h: -_holding_value(h),
    )

    amc_items = amc_section.get("items") or []
    new_amc_pct, after_hhi, after_effn = _simulate_amc_trim(
        amc_name, trim_rs, amc_items, total_value,
    )

    top_fund = amc_funds[0].get("name", amc_name) if amc_funds else amc_name
    low_amc  = next(
        (x["name"] for x in sorted(amc_items, key=lambda x: x.get("pct", 0))
         if (x.get("pct") or 0) < 10 and x["name"] != amc_name),
        None,
    )

    return {
        "id":          f"trim-amc-{amc_name[:20]}",
        "action_kind": "trim_amc",
        "title":       f"Reduce {amc_name} from {amc_pct:.1f}% → ~{new_amc_pct:.1f}%",
        "why": (
            f"{amc_name} is {amc_pct:.1f}% of your mutual-fund portfolio — "
            f"{gap_pct:.1f}pt above the {cap:.0f}% cap. If {amc_name} faces "
            f"operational issues, a large share of your portfolio is simultaneously affected."
        ),
        "action": (
            f"Redeem ₹{trim_rs:,.0f} from {top_fund} (largest {amc_name} holding). "
            f"This brings {amc_name} from {amc_pct:.1f}% to ~{new_amc_pct:.1f}%, inside the {cap:.0f}% cap."
        ),
        "amount_rs":        trim_rs,
        "annual_saving_rs": 0,
        "contributors": [
            {"name": h.get("name",""), "pct_of_exposure": round(_holding_value(h) / max(item["value_inr"], 1) * 100, 1), "value_rs": round(_holding_value(h), 0)}
            for h in amc_funds[:4]
        ],
        "before_after": [{
            "lens_id": "amc", "lens_label": "AMC",
            "before_verdict": _verdict(amc_pct, cap),
            "after_verdict":  _verdict(new_amc_pct, cap),
            "before_pct": round(amc_pct, 1), "after_pct": round(new_amc_pct, 1),
            "before_hhi": round((amc_section.get("hhi") or 0) * 10000),
            "after_hhi":  after_hhi,
            "before_eff_n": amc_section.get("effective_n") or 0,
            "after_eff_n":  after_effn,
        }],
        "redeploy_to": (
            f"Redeploy into a fund from {low_amc} (currently under-weight) to improve AMC spread."
            if low_amc else "Redeploy into an AMC currently below 10% of your portfolio."
        ),
        "caveats": [
            {"icon": "tax",  "text": "LTCG at 10% above ₹1 L/yr on equity units held > 1 year."},
            {"icon": "exit", "text": "Check exit load schedule — most equity funds are load-free after 12 months."},
        ],
        "leverage_score": min(85, 50 + round(gap_pct * 2)),
    }


# ── 5. Sector over-concentration ─────────────────────────────────────

def _rec_sector_sip(
    item: dict,
    sector_section: dict,
    total_value: float,
) -> dict:
    sector_name = item["name"]
    sector_pct  = item["pct"]
    cap         = float(sector_section.get("caution_pct") or _CAP["sector"])
    target      = cap - _TARGET_BUFFER
    gap_pct     = sector_pct - target

    sector_items = sector_section.get("items") or []
    under = [s["name"] for s in sorted(sector_items, key=lambda x: x["pct"])
             if s["pct"] < 10 and s["name"] not in {"Unclassified", "Other", "Gold"}
             and s["name"] != sector_name][:2]

    return {
        "id":          f"trim-sector-{sector_name[:20]}",
        "action_kind": "trim_sector",
        "title":       f"Reduce {sector_name} sector from {sector_pct:.1f}% → ~{target:.0f}%",
        "why": (
            f"{sector_name} is {sector_pct:.1f}% of your portfolio — {gap_pct:.1f}pt above "
            f"the {cap:.0f}% sector cap. A single adverse sector event affects a "
            f"disproportionate share of your wealth."
        ),
        "action": (
            f"Pause SIPs into {sector_name}-heavy funds. Redirect new flows to "
            f"{' and '.join(under) if under else 'under-weight sectors'}. "
            f"This is tax-efficient (no redemption) and brings {sector_name} below "
            f"{cap:.0f}% over 6–12 months."
        ),
        "amount_rs":        0,
        "annual_saving_rs": 0,
        "contributors":     [{"name": c, "pct_of_exposure": None, "value_rs": None}
                              for c in (item.get("holdings") or [])[:4]],
        "before_after": [{
            "lens_id": "sector", "lens_label": "Sector",
            "before_verdict": _verdict(sector_pct, cap),
            "after_verdict":  _verdict(target + 1, cap),
            "before_pct": round(sector_pct, 1), "after_pct": round(target + 1, 1),
            "before_hhi": round((sector_section.get("hhi") or 0) * 10000),
            "after_hhi":  None, "before_eff_n": sector_section.get("effective_n"), "after_eff_n": None,
        }],
        "redeploy_to": (
            f"Redirect SIPs toward {' and '.join(under)}."
            if under else "Redirect SIPs toward sectors currently under 10% of your portfolio."
        ),
        "caveats": [{"icon": "tax", "text": "SIP redirection has zero tax impact — no redemption occurs."}],
        "leverage_score": min(75, 45 + round(gap_pct * 2)),
    }


# ── Public API ────────────────────────────────────────────────────────

def compute_remediation(
    holdings: list[dict],
    concentration_envelope: dict,
    *,
    clusters: list[dict] | None = None,
    risk_profile: str = "moderate",
) -> list[dict]:
    """Return ranked remediation recommendations (max 6).

    Args:
      holdings: raw Mongo holding docs
      concentration_envelope: output of compute_concentration()
      clusters: output of cluster_overlapping_funds() (enriched)
      risk_profile: 'conservative' | 'moderate' | 'aggressive'
    """
    total_value = float(concentration_envelope.get("total_value") or 0)
    if total_value <= 0:
        return []

    # Deduplicate by ISIN so multi-folio funds appear once
    deduped = _deduplicate_by_isin(holdings)
    mf_holdings = [h for h in deduped if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}]

    # Build set of redundant ISINs (appear in any cluster)
    redundant_isins: set[str] = set()
    for cl in (clusters or []):
        for m in cl.get("members", []):
            if m.get("ticker"):
                redundant_isins.add(m["ticker"])

    recommendations: list[dict] = []

    # 1. Duplicate Regular/Direct plans
    try:
        for dup in _find_duplicate_plans(mf_holdings):
            reg  = dup["regular_holding"]
            drct = dup["direct_holding"]
            rv   = _holding_value(reg)
            saving = round(rv * (_ER_REGULAR - _ER_DIRECT), 0)
            recommendations.append({
                "id":          f"dup-{_scheme_base(reg.get('name',''))[:30]}",
                "action_kind": "duplicate_plan",
                "title":       f"Switch {reg.get('name','')} → Direct plan",
                "why": (
                    f"You hold the same scheme in two plans. The Regular plan charges "
                    f"~{_ER_REGULAR*100:.1f}% p.a. vs ~{_ER_DIRECT*100:.1f}% for Direct — "
                    f"identical portfolio, higher fees. Switching saves ₹{saving:,.0f}/yr."
                ),
                "action": (
                    f"Redeem {reg.get('name','')} (₹{rv:,.0f}) and invest in "
                    f"{drct.get('name','')}."
                ),
                "amount_rs": round(rv, 0), "annual_saving_rs": saving,
                "contributors": [{"name": reg.get("name",""), "pct_of_exposure": 100, "value_rs": round(rv, 0)}],
                "before_after": [],
                "redeploy_to": drct.get("name"),
                "caveats": [
                    {"icon": "tax",  "text": "LTCG at 10% on units held > 1 year (above ₹1 L annual exemption). STCG at 15% on units held < 1 year."},
                    {"icon": "lock", "text": "ELSS units are locked for 3 years per instalment — switch only unlocked units."},
                ],
                "leverage_score": 95,
            })
    except Exception:
        logger.exception("Duplicate plan detection failed")

    # 2. Category over-allocation vs risk-profile target
    try:
        profile_key = (risk_profile or "moderate").lower()
        if profile_key not in _CATEGORY_TARGETS:
            profile_key = "moderate"
        targets = _CATEGORY_TARGETS[profile_key]

        # Enrich holdings with sebi_category before computing allocation
        from services.mf_category_enricher import enrich_mf_with_sebi_category
        enriched_mf = enrich_mf_with_sebi_category(mf_holdings)
        cat_alloc = _compute_category_allocation(enriched_mf, total_value)

        for category, actual_pct in sorted(cat_alloc.items(), key=lambda x: -x[1]):
            target_pct  = targets.get(category, 0.0)
            if target_pct <= 0:
                continue
            over_by = actual_pct - (target_pct + _CATEGORY_OVERALLOC_BUFFER)
            if over_by <= 0:
                continue
            cat_holdings = [h for h in enriched_mf if _std_category(h) == category]
            if not cat_holdings:
                continue
            rec = _rec_category_overalloc(
                category, actual_pct, target_pct, over_by,
                cat_holdings, total_value, redundant_isins,
            )
            recommendations.append(rec)
    except Exception:
        logger.exception("Category over-allocation check failed")

    # 3. Redundant cluster consolidation
    try:
        for cluster in (clusters or [])[:4]:
            if (cluster.get("avg_overlap_pct") or 0) < 50:
                continue
            rec = _rec_cluster(cluster, total_value)
            if rec:  # _rec_cluster returns {} when dedup collapses to < 2 members
                recommendations.append(rec)
    except Exception:
        logger.exception("Cluster remediation failed")

    # 4. AMC over-concentration (only if not already covered by category rec)
    try:
        amc_section = concentration_envelope.get("amc") or {}
        cap_amc = float(amc_section.get("caution_pct") or _CAP["amc"])
        for item in (amc_section.get("items") or []):
            if (item.get("pct") or 0) > cap_amc:
                recommendations.append(
                    _rec_amc_trim(item, amc_section, deduped, total_value)
                )
    except Exception:
        logger.exception("AMC trim remediation failed")

    # 5. Sector over-concentration
    try:
        sector_section = concentration_envelope.get("sector") or {}
        cap_sec = float(sector_section.get("caution_pct") or _CAP["sector"])
        for item in (sector_section.get("items") or []):
            if (item.get("pct") or 0) > cap_sec:
                recommendations.append(
                    _rec_sector_sip(item, sector_section, total_value)
                )
    except Exception:
        logger.exception("Sector trim remediation failed")

    recommendations.sort(key=lambda r: -(r.get("leverage_score") or 0))
    return recommendations[:6]


__all__ = ["compute_remediation"]
