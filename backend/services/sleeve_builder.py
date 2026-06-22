"""Sleeve-based portfolio builder.

Composes the guided per-profile sleeve template (services.sleeve_templates) with
real V3-scored funds (NIDP DAAS, ranked within each sub-category) to produce the
category/sub-category portfolio the in-chat builder renders: asset class →
sub-category sleeves, each with a target %, a SIP/lumpsum split, and a ranked
fund list.

Unlike the flat 4-bucket path (services.portfolio_builder), this fills Large
Cap / Flexi Cap / Mid Cap / Balanced Advantage / Corporate Bond / FoF Overseas /
Gold etc. each from its own scored universe — which is why debt, large-cap,
international and gold sleeves populate here where the old picker showed nothing.
Glue + sourcing only; no new modelling.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _fund_view(r: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a DAAS score row to what the builder card needs."""
    return {
        "scheme_name": r.get("scheme_name"),
        "scheme_code": r.get("scheme_code"),
        "isin": r.get("isin"),
        "sub_category": r.get("sub_category"),
        "quality_score": r.get("quality_score"),
        "health_score": r.get("health_score"),
        "quality_coverage_pct": r.get("quality_coverage_pct"),
    }


async def build_sleeve_portfolio(
    risk_profile: str,
    *,
    monthly_sip_rs: Optional[float] = None,
    lumpsum_rs: Optional[float] = None,
    n_per_sleeve: int = 2,
) -> Dict[str, Any]:
    """Build the guided sleeve portfolio for a risk profile.

    Returns:
        {
          "risk_profile": "moderate",
          "allocation":   {equity, international, hybrid, gold, debt, cash},  # by asset class, for the donut
          "sleeves": [ {key, label, asset_class, sub_category, target_pct,
                        monthly_sip_rs, lumpsum_rs, funds: [...]}, ... ],
          "totals": {monthly_sip_rs, lumpsum_rs, n_funds},
        }
    """
    from services import sleeve_templates as _st
    from services.copilot_tools import daas_client as _dc

    sleeves = _st.sleeves_for(risk_profile)
    total_pct = sum(s["target_pct"] for s in sleeves) or 100.0

    # Fetch each sleeve's funds concurrently (one DAAS call per sleeve).
    async def _fill(sleeve: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            rows = await _dc.get_top_funds_by_subcategory(
                sleeve.get("fund_category"), sleeve["sub_category"], n=n_per_sleeve,
            )
        except Exception as e:  # noqa: BLE001 — a dead sleeve must not sink the build
            logger.warning("sleeve fill failed for %s: %s", sleeve.get("key"), e)
            return []
        return [_fund_view(r) for r in rows]

    fund_lists = await asyncio.gather(*(_fill(s) for s in sleeves))

    sip = float(monthly_sip_rs or 0)
    lump = float(lumpsum_rs or 0)
    out_sleeves: List[Dict[str, Any]] = []
    alloc: Dict[str, float] = {}
    n_funds = 0
    for sleeve, funds in zip(sleeves, fund_lists):
        share = sleeve["target_pct"] / total_pct
        out_sleeves.append({
            "key": sleeve["key"],
            "label": sleeve["label"],
            "asset_class": sleeve["asset_class"],
            "sub_category": sleeve["sub_category"],
            "target_pct": round(sleeve["target_pct"], 1),
            "monthly_sip_rs": round(sip * share) if sip else None,
            "lumpsum_rs": round(lump * share) if lump else None,
            "funds": funds,
        })
        alloc[sleeve["asset_class"]] = round(alloc.get(sleeve["asset_class"], 0.0) + sleeve["target_pct"], 1)
        n_funds += len(funds)

    return {
        "risk_profile": (risk_profile or "moderate").lower(),
        "allocation": alloc,
        "sleeves": out_sleeves,
        "totals": {"monthly_sip_rs": monthly_sip_rs, "lumpsum_rs": lumpsum_rs, "n_funds": n_funds},
    }
