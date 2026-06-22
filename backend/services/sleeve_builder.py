"""Sleeve-based portfolio builder — risk sets the asset-class budget; quality+
returns set the sub-category split.

For a risk profile we take the asset-class budget (equity/intl/hybrid/gold/debt/
cash) and, WITHIN each asset class, split that budget across the eligible
sub-category sleeves in proportion to the avg V3 quality_score of each sleeve's
top funds. V3 quality is ~45% returns + risk-adjusted performance, so the split
is driven by quality ranking and returns — gated by the risk budget + per-profile
eligibility. Funds are real, ranked NIDP V3 picks (services.copilot_tools.
daas_client). Glue + sourcing; no new modelling.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fund_view(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scheme_name": r.get("scheme_name"),
        "scheme_code": r.get("scheme_code"),
        "isin": r.get("isin"),
        "sub_category": r.get("sub_category"),
        "quality_score": r.get("quality_score"),
        "health_score": r.get("health_score"),
        "quality_coverage_pct": r.get("quality_coverage_pct"),
    }


def _avg_quality(funds: List[Dict[str, Any]]) -> float:
    qs = [float(f["quality_score"]) for f in funds if f.get("quality_score") is not None]
    return round(sum(qs) / len(qs), 1) if qs else 0.0


async def build_sleeve_portfolio(
    risk_profile: str,
    *,
    monthly_sip_rs: Optional[float] = None,
    lumpsum_rs: Optional[float] = None,
    n_per_sleeve: int = 2,
) -> Dict[str, Any]:
    """Build the guided sleeve portfolio for a risk profile.

    Returns {risk_profile, allocation{asset_class:pct}, sleeves[...], totals}.
    Each sleeve: {key,label,asset_class,sub_category,target_pct,avg_quality,
    weight_basis,monthly_sip_rs,lumpsum_rs,funds[...]}.
    """
    from services import sleeve_templates as _st
    from services.copilot_tools import daas_client as _dc

    budget = _st.asset_budget(risk_profile)          # risk-driven asset-class %
    elig = _st.eligible_sleeves(risk_profile)        # {asset_class: [sleeve dicts]}

    # Flatten eligible sleeves and fetch every sleeve's funds concurrently.
    flat: List[Dict[str, Any]] = [s for ac in _st.ASSET_ORDER for s in elig.get(ac, [])]

    async def _fill(sleeve: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            rows = await _dc.get_top_funds_by_subcategory(
                sleeve.get("fund_category"), sleeve["sub_category"], n=n_per_sleeve,
            )
        except Exception as e:  # noqa: BLE001 — one dead sleeve must not sink the build
            logger.warning("sleeve fill failed for %s: %s", sleeve.get("key"), e)
            return []
        return [_fund_view(r) for r in rows]

    fund_lists = await asyncio.gather(*(_fill(s) for s in flat))
    funds_by_key = {s["key"]: fl for s, fl in zip(flat, fund_lists)}

    sip = float(monthly_sip_rs or 0)
    lump = float(lumpsum_rs or 0)
    out_sleeves: List[Dict[str, Any]] = []
    alloc: Dict[str, float] = {}
    n_funds = 0

    for ac in _st.ASSET_ORDER:
        ac_budget = float(budget.get(ac, 0) or 0)
        sleeves = elig.get(ac, [])
        if ac_budget <= 0 or not sleeves:
            continue
        scored = [(s, funds_by_key.get(s["key"], []), _avg_quality(funds_by_key.get(s["key"], []))) for s in sleeves]
        # weight by avg quality; only sleeves that actually have funds get budget.
        funded = [x for x in scored if x[2] > 0 and x[1]]
        pool = funded if funded else scored
        tot_q = sum(x[2] for x in pool)
        for s, funds, avgq in pool:
            # quality-weighted within the asset class; equal split only if no
            # quality signal at all (keeps the asset-class budget intact).
            w = (avgq / tot_q) if tot_q > 0 else (1.0 / len(pool))
            pct = round(ac_budget * w, 1)
            share = pct / 100.0
            out_sleeves.append({
                "key": s["key"],
                "label": s["label"],
                "asset_class": ac,
                "sub_category": s["sub_category"],
                "target_pct": pct,
                "avg_quality": avgq,
                "weight_basis": "quality" if tot_q > 0 else "equal",
                "monthly_sip_rs": round(sip * share) if sip else None,
                "lumpsum_rs": round(lump * share) if lump else None,
                "funds": funds,
            })
            alloc[ac] = round(alloc.get(ac, 0.0) + pct, 1)
            n_funds += len(funds)

    return {
        "risk_profile": (risk_profile or "moderate").lower(),
        "allocation": alloc,
        "sleeves": out_sleeves,
        "totals": {"monthly_sip_rs": monthly_sip_rs, "lumpsum_rs": lumpsum_rs, "n_funds": n_funds},
        "methodology": "Risk sets the asset-class budget; each sleeve's share of that "
                       "budget is proportional to the average V3 quality (which embeds "
                       "returns + risk-adjusted performance) of its top-ranked funds.",
    }
