"""Goal→Fund basket tool for the Nivesh Copilot (WF-02-06 / WF-03 suitability).

Answers *"which funds should I use for this goal?"* — maps the goal's horizon +
risk profile to an asset allocation (``goal_engine.allocation_for_profile``), then
picks suitability-gated, quality-ranked funds per bucket
(``goal_fund_picker.auto_allocate_funds`` → which applies ``selection.filter_eligible``).

Pure wrapper — no new selection logic. The picks are exactly what the goal fund
picker + selection gates already produce.

Public entry point:
    get_goal_basket(risk_profile, horizon_years, per_bucket=1) -> BasketResult
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BasketResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"GOAL_BASKET status=error reason={self.error}"
        return f"GOAL_BASKET | {self.summary}"


def _pct(v: Any) -> str:
    try:
        return f"{float(v):.1f}%"
    except (TypeError, ValueError):
        return "—"


async def get_goal_basket(
    risk_profile: str = "moderate",
    horizon_years: float = 10.0,
    per_bucket: int = 1,
) -> BasketResult:
    """Build a suitability-gated fund basket for a goal's horizon + risk profile.

    Reuses ``goal_engine.allocation_for_profile`` (horizon guardrail) +
    ``goal_fund_picker.auto_allocate_funds`` (quality rank + ``selection`` gates).
    """
    try:
        from services import goal_engine, goal_fund_picker
    except ImportError as exc:  # pragma: no cover
        return BasketResult(ok=False, summary="Goal basket engine unavailable", error=str(exc))

    try:
        allocation = goal_engine.allocation_for_profile(risk_profile, float(horizon_years))
        rv = goal_engine.blend_return_vol(allocation)
    except Exception as exc:  # noqa: BLE001
        logger.warning("goal_basket: allocation failed: %s", exc)
        return BasketResult(ok=False, summary="Could not compute allocation for this goal", error=str(exc))

    try:
        basket = await goal_fund_picker.auto_allocate_funds(allocation, per_bucket=per_bucket)
    except Exception as exc:  # noqa: BLE001 — DB/pool unavailable → honest empty, not a crash
        logger.warning("goal_basket: fund pick failed: %s", exc)
        return BasketResult(
            ok=False, summary="Fund catalogue is unavailable right now — try again shortly.",
            error=str(exc), data={"allocation": allocation},
        )

    # Flatten {bucket: [funds]} → widget rows, weight already set by the picker.
    rows: List[Dict[str, Any]] = []
    empty_buckets: List[str] = []
    for bucket, funds in basket.items():
        if not funds:
            empty_buckets.append(bucket)
            continue
        for f in funds:
            rows.append({
                "bucket": bucket,
                "scheme_name": f.get("scheme_name"),
                "instrument_id": f.get("instrument_id"),
                "isin": f.get("isin"),
                "category": f.get("category"),
                "sub_category": f.get("sub_category"),
                "weight_pct": f.get("weight_pct"),
                "expense_ratio": f.get("expense_ratio"),
                "quality_score": f.get("quality_score"),
                "plan_type": f.get("plan_type"),
            })
    rows.sort(key=lambda r: (r.get("weight_pct") or 0), reverse=True)

    alloc_str = " / ".join(f"{_pct(v)} {k}" for k, v in allocation.items() if v)
    if not rows:
        summary = (f"{risk_profile.title()} · {horizon_years:g}y → {alloc_str}, but no funds cleared "
                   "the suitability gates just now.")
        ok = False
    else:
        top = ", ".join(
            f"{r['scheme_name']} (Q{r['quality_score']:.0f}, TER {r['expense_ratio']}%)"
            if r.get("quality_score") is not None else str(r["scheme_name"])
            for r in rows[:3]
        )
        summary = (
            f"{risk_profile.title()} · {horizon_years:g}y goal → allocation {alloc_str} "
            f"(exp. return {rv.get('annual_return_pct')}% / vol {rv.get('annual_vol_pct')}%). "
            f"Basket ({len(rows)} funds): {top}."
        )
        ok = True

    return BasketResult(
        ok=ok, summary=summary, rows=rows,
        data={
            "risk_profile": risk_profile,
            "horizon_years": horizon_years,
            "allocation": allocation,
            "expected": rv,
            "empty_buckets": empty_buckets,
            "basket": basket,
        },
    )
