"""Sleeve-based portfolio builder — executes the governed allocation policy.

Reads services.allocation_policy (config/allocation_policy.yaml) and builds the
portfolio per the Investment-Committee methodology:

  L1  strategic allocation by risk profile x horizon  -> equity/debt/gold/cash %
  L2  core-satellite split (equity) + debt-by-horizon -> governed sub-sleeves
  L3  instrument selection by quality_score           -> ONLY when Compliance has
      enabled named-scheme output (compliance.mf_recommendations_mode ==
      named_scheme). Default is category_and_model: we surface the allocation
      MODEL + category-level guidance + disclaimer, with NO named schemes.

We do not invent weights the policy does not declare. The YAML governs the
core/satellite split but not the split among core members (index vs large) or
satellite members (flexi vs mid/small); those are therefore presented at the
governed core/satellite granularity, listing the member categories. Debt IS
split by the governed by-horizon table, so it carries a real category breakdown.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Instrument-kind -> display label + the NIDP V3 sub_category used to rank funds
# in named-scheme mode (Layer 3). Labels are what category_and_model output shows.
_KIND = {
    "equity_index_fund": {"label": "Index Funds",       "sub_category": "Index Funds",        "fund_category": "equity"},
    "large_cap_fund":    {"label": "Large Cap",         "sub_category": "Large Cap Fund",      "fund_category": "equity"},
    "flexi_cap_fund":    {"label": "Flexi Cap",         "sub_category": "Flexi Cap Fund",      "fund_category": "equity"},
    "mid_small_fund":    {"label": "Mid / Small Cap",   "sub_category": "Mid Cap Fund",        "fund_category": "equity"},
    "thematic_basket":   {"label": "Thematic",          "sub_category": "Sectoral/ Thematic",  "fund_category": "equity"},
    "direct_stock":      {"label": "Direct Stocks",     "sub_category": None,                  "fund_category": None},
    "corporate_bond_fund": {"label": "Corporate Bond",  "sub_category": "Corporate Bond Fund", "fund_category": "debt"},
    "short_duration_fund": {"label": "Short Duration",  "sub_category": "Short Duration Fund", "fund_category": "debt"},
    "gilt_fund":         {"label": "Gilt",              "sub_category": "Gilt Fund",           "fund_category": "debt"},
    "banking_psu_fund":  {"label": "Banking & PSU",     "sub_category": "Banking and PSU Fund","fund_category": "debt"},
    "gold_etf":          {"label": "Gold",              "sub_category": "Gold",                "fund_category": None},
    "liquid_fund":       {"label": "Liquid / Cash",     "sub_category": "Liquid Fund",         "fund_category": "liquid"},
}


def _kinds_labels(kinds: List[str]) -> List[str]:
    return [_KIND[k]["label"] for k in kinds if k in _KIND]


async def build_sleeve_portfolio(
    risk_profile: str,
    *,
    horizon_years: float = 10.0,
    monthly_sip_rs: Optional[float] = None,
    lumpsum_rs: Optional[float] = None,
    n_per_sleeve: int = 2,
) -> Dict[str, Any]:
    """Build the governed portfolio for a risk profile + horizon.

    Returns the asset-class allocation, the governed sub-sleeve model (category
    level), compliance metadata and (only in named_scheme mode) ranked funds.
    """
    from services import allocation_policy as _p

    # Capacity override + horizon bucket (policy rules).
    profile = _p.apply_capacity_caps(risk_profile, horizon_years)
    hb = _p.horizon_bucket(horizon_years)

    # L1 — strategic allocation (% of total), de-risked by the glide path as the
    # goal approaches.
    strat = _p.strategic_allocation(profile, hb)  # {equity,debt,gold,cash}
    strat = _p.apply_glide_path(strat, horizon_years)

    sleeves: List[Dict[str, Any]] = []

    def _add(key, asset_class, label, detail, members, pct):
        if pct <= 0:
            return
        sleeves.append({
            "key": key, "asset_class": asset_class, "label": label, "detail": detail,
            "category_members": _kinds_labels(members),
            "_member_kinds": members,
            "target_pct": round(pct, 1),
            "funds": [],  # filled only in named-scheme mode
        })

    # L2 equity — core / satellite (governed split; present at that granularity).
    eq = float(strat.get("equity", 0) or 0)
    if eq > 0:
        cs = _p.core_satellite_split(profile)            # % of equity sleeve
        members = _p.equity_members()
        sat_cap = float(_p.caps().get("max_satellite_total_of_equity", 0.45)) * 100.0
        sat_pct_of_sleeve = min(float(cs.get("satellite", 0)), sat_cap)
        core_pct_of_sleeve = 100.0 - sat_pct_of_sleeve
        # Drop direct_stock from satellite members unless Compliance enabled stocks.
        sat_members = [m for m in members["satellite"] if m != "direct_stock" or _p.stocks_allowed()]
        _add("equity_core", "equity", "Equity - Core", "Index & Large-cap",
             members["core"], eq * core_pct_of_sleeve / 100.0)
        _add("equity_satellite", "equity", "Equity - Satellite", "Flexi & Mid/Small-cap",
             sat_members, eq * sat_pct_of_sleeve / 100.0)

    # L2 debt — governed by-horizon split (real category breakdown).
    dt = float(strat.get("debt", 0) or 0)
    if dt > 0:
        for kind, pct_of_sleeve in _p.debt_split(hb).items():
            info = _KIND.get(kind, {"label": kind})
            _add(f"debt_{kind}", "debt", info["label"], "Debt", [kind], dt * float(pct_of_sleeve) / 100.0)

    # Gold + Cash — single sleeves.
    _add("gold", "gold", "Gold", "Inflation hedge", ["gold_etf"], float(strat.get("gold", 0) or 0))
    _add("cash", "cash", "Liquid / Cash", "Liquidity", ["liquid_fund"], float(strat.get("cash", 0) or 0))

    # SIP / lumpsum split pro-rata to each sub-sleeve's % of total.
    sip = float(monthly_sip_rs or 0)
    lump = float(lumpsum_rs or 0)
    for s in sleeves:
        share = s["target_pct"] / 100.0
        s["monthly_sip_rs"] = round(sip * share) if sip else None
        s["lumpsum_rs"] = round(lump * share) if lump else None

    # L3 — named-scheme selection ONLY if Compliance enabled it.
    names_on = _p.names_allowed()
    if names_on:
        from services.copilot_tools import daas_client as _dc

        async def _fill(s: Dict[str, Any]) -> None:
            kinds = [k for k in s["_member_kinds"] if _KIND.get(k, {}).get("sub_category")]
            picks: List[Dict[str, Any]] = []
            for k in kinds:
                info = _KIND[k]
                try:
                    if s["asset_class"] == "debt":
                        # Debt ranks on the governed debt model (config/debt_scoring_model.yaml),
                        # not the partial V3 quality score — score a candidate pool + their NAV
                        # primitives, then rank within the SEBI sub-category.
                        from services import debt_scoring as _ds
                        cand = await _dc.get_debt_sleeve_funds(info["fund_category"], info["sub_category"])
                        ranked = _ds.rank_peers(cand, info["sub_category"])[:n_per_sleeve]
                        picks.extend({"scheme_name": x.get("scheme_name"), "isin": x.get("isin"),
                                      "sub_category": info["sub_category"], "debt_score": x.get("composite_100"),
                                      "grade": x.get("grade"), "coverage_pct": x.get("coverage_pct")}
                                     for x in ranked)
                    else:
                        rows = await _dc.get_top_funds_by_subcategory(info["fund_category"], info["sub_category"], n=n_per_sleeve)
                        picks.extend({"scheme_name": r.get("scheme_name"), "isin": r.get("isin"),
                                      "sub_category": r.get("sub_category"), "quality_score": r.get("quality_score")}
                                     for r in rows)
                except Exception as e:  # noqa: BLE001
                    logger.warning("L3 fill %s/%s: %s", s["key"], k, e)
            # cap: max holdings per sub-sleeve
            cap = int(_p.caps().get("max_holdings_per_sub_sleeve", 3))
            s["funds"] = picks[:cap]
        await asyncio.gather(*(_fill(s) for s in sleeves))

    for s in sleeves:
        s.pop("_member_kinds", None)

    alloc = {ac: round(sum(s["target_pct"] for s in sleeves if s["asset_class"] == ac), 1)
             for ac in ("equity", "debt", "gold", "cash")}

    # Validation gates — Monte Carlo on house CMAs (allocation_policy.yaml).
    validation: Optional[Dict[str, Any]] = None
    try:
        from services import policy_simulation as _sim
        validation = _sim.simulate_and_validate(
            alloc, horizon_years=horizon_years, monthly_sip_rs=sip, lumpsum_rs=lump,
        )
    except Exception as e:  # noqa: BLE001 — never let the sim sink the build
        logger.warning("policy simulation failed: %s", e)

    comp = _p.compliance()
    return {
        "risk_profile": profile,
        "requested_profile": (risk_profile or "moderate"),
        "horizon_years": horizon_years,
        "horizon_bucket": hb,
        "allocation": alloc,                 # asset-class rollup (= L1 strategic)
        "sleeves": sleeves,                  # governed sub-sleeve model (category level)
        "validation": validation,            # MC gates on house CMAs (may be null)
        "compliance": {
            "mode": comp.get("mf_recommendations_mode"),
            "names_allowed": names_on,
            "stocks_allowed": _p.stocks_allowed(),
            "registration": comp.get("registration"),
            "disclaimer": ("This is model and category-level guidance, not a recommendation "
                           "of specific schemes or stocks. Mutual funds are subject to market risk."
                           if _p.disclaimer_required() else None),
        },
        "policy_version": _p.version(),
        "methodology": ("Strategic allocation by risk profile x horizon; equity split core/"
                        "satellite and debt split by horizon per the governed allocation policy. "
                        "Named schemes are shown only when Compliance enables named-scheme output."),
        "totals": {"monthly_sip_rs": monthly_sip_rs, "lumpsum_rs": lumpsum_rs},
    }
