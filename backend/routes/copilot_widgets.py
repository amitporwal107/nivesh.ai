"""Copilot embedded-widget producers — Phase B critical 4.

Each endpoint returns a `WidgetEnvelope` (see models_copilot_widgets.py)
that the frontend renders identically inside a chat bubble or inside
Dashboard / Insights / Holding drawer.

Datasource priority (Doc design — no pgvector yet):
  1. Local DB (portfolio_intelligence, mf_master, prices_eod, etc.)
  2. NIDP DaaS API `/v1/intelligence/*` (via nidp_query_client) for
     market snapshots, security master, events search.
  3. LLM oneshot (emergentintegrations) for rationale text only —
     never for raw numbers.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import logging
import os
import httpx

from deps import db, get_current_user
from models_copilot_widgets import (
    WidgetEnvelope, FreshnessChip, AgentInfo,
    FundCardData, MarketBriefData, MarketBriefIndex,
    CompareTableData, CompareRow, SipPlanData, SipPlanAllocation,
    RebalancePlanData, RebalanceAction,
    TaxHarvestData, TaxHarvestCandidate,
    StressTestData, StressTestBreakdown,
    SectorRotationData, SectorPoint,
    OverlapRevealData, OverlapStock,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/copilot/widgets", tags=["copilot-widgets"])


# ── DaaS proxy (re-use existing NIDP DaaS auth) ──────────────────

_DAAS_URL = (
    os.environ.get("NIDP_DAAS_BASE_URL")
    or os.environ.get("NIDP_DAAS_API_URL")
    or "https://data.niveshcopilot.com/daas"
).rstrip("/")
_DAAS_KEY = os.environ.get("NIDP_DAAS_API_KEY") or ""


async def _daas_get(path: str, params: Optional[dict] = None, timeout: float = 6.0) -> Optional[dict]:
    """Best-effort GET against DaaS. Returns None on any failure so the
    widget can degrade to local-only data instead of 5xx-ing the UI."""
    if not _DAAS_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{_DAAS_URL}{path}",
                params=params or {},
                headers={"X-API-Key": _DAAS_KEY},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.info("DaaS GET %s → %s", path, resp.status_code)
            return None
    except Exception as e:  # noqa: BLE001
        logger.warning("DaaS GET %s failed: %s", path, e)
        return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 1. Fund Card ────────────────────────────────────────────────

class FundCardRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200,
                       description="Scheme name, code, or natural-language fragment")


_QUALITY_LABEL_VERDICT = {
    "Elite":           "Strong Buy",
    "Good":            "Buy",
    "Average":         "Hold",
    "Below Average":   "Hold",
    "Underperformer":  "Sell",
}

_RED_FLAG_EVENT_TYPES = {
    "MANAGER_CHANGE", "TER_INCREASE", "RISK_INCREASE", "MERGER", "CATEGORY_CHANGE",
}


@router.post("/fund_card")
async def fund_card(request: Request, payload: FundCardRequest):
    """Produce a Fund Card widget envelope for the given scheme.

    Reads from `mf_master` for static facts (category, AUM, expense),
    enriches with NIDP DaaS scorecard (composite_score, quality_label,
    peer-group rank) and lifecycle events (manager changes, TER hikes, mergers)
    when available. Falls back to heuristic scoring when NIDP has no data.
    """
    import asyncio
    from services.copilot_tools import daas_client
    from services.copilot_tools.daas_client import DaasError

    await get_current_user(request)
    q = payload.query.strip()

    # Find the scheme — exact code, ISIN, or name match.
    scheme = await db.mf_master.find_one(
        {"$or": [
            {"scheme_code": q},
            {"isin": q.upper()},
            {"scheme_name": {"$regex": f"^{q}", "$options": "i"}},
        ]},
        {"_id": 0},
    ) or await db.mf_master.find_one(
        {"scheme_name": {"$regex": q, "$options": "i"}},
        {"_id": 0},
    )

    if not scheme:
        raise HTTPException(status_code=404,
                            detail=f"No mutual fund matched '{q}'. Try a fuller scheme name.")

    scheme_name = scheme.get("scheme_name", q)
    scheme_code = scheme.get("scheme_code")

    # Returns: pull what we have locally.
    rets = scheme.get("returns_summary") or {}
    aum_cr = scheme.get("aum_cr") or scheme.get("aum")
    expense_ratio = scheme.get("expense_ratio")

    # ── NIDP DaaS enrichment ─────────────────────────────────────────
    nidp_scorecard: Optional[dict] = None
    nidp_events: List[dict] = []
    if scheme_code:
        try:
            sc_task = daas_client.get_mf_scorecard(scheme_code)
            ev_task = daas_client.get_mf_events(scheme_code, limit=20)
            nidp_scorecard, nidp_events = await asyncio.gather(sc_task, ev_task,
                                                                return_exceptions=True)
            # gather returns exceptions as values when return_exceptions=True
            if isinstance(nidp_scorecard, Exception):
                logger.info("NIDP scorecard unavailable for %s: %s", scheme_code, nidp_scorecard)
                nidp_scorecard = None
            if isinstance(nidp_events, Exception):
                nidp_events = []
        except Exception as exc:
            logger.info("NIDP fund_card enrichment failed for %s: %s", scheme_code, exc)
            nidp_scorecard = None
            nidp_events = []

    # ── Derive score + verdict ────────────────────────────────────────
    why: List[str] = []
    watch_outs: List[str] = []
    nidp_composite_score = None
    nidp_quality_label = None
    nidp_composite_rank = None
    nidp_total_in_category = None
    nidp_top_position_pct = None
    nidp_red_flags: List[str] = []

    if nidp_scorecard:
        # Use NIDP composite_score (0–100) as the authoritative score
        nidp_composite_score = nidp_scorecard.get("composite_score")
        nidp_quality_label   = nidp_scorecard.get("quality_label")
        nidp_composite_rank  = nidp_scorecard.get("composite_rank")
        nidp_total_in_category = nidp_scorecard.get("total_in_category")
        nidp_top_position_pct  = nidp_scorecard.get("top_position_pct")

        score = int(round(nidp_composite_score)) if nidp_composite_score is not None else 50
        verdict = _QUALITY_LABEL_VERDICT.get(nidp_quality_label or "", "Hold")

        # Peer-group rank bullet
        if nidp_composite_rank and nidp_total_in_category:
            sub_cat = nidp_scorecard.get("sub_category") or scheme.get("category") or "category"
            why.append(
                f"Ranked #{nidp_composite_rank} of {nidp_total_in_category} "
                f"{sub_cat} funds (NIDP composite score)"
            )

        # Q1 strengths from quartile flags
        for metric, label in (
            ("qtile_ret1y",  "1Y return"), ("qtile_ret3y", "3Y return"),
            ("qtile_sharpe", "Sharpe ratio"), ("qtile_ter",   "TER"),
        ):
            q_val = nidp_scorecard.get(metric)
            if q_val == 1:
                why.append(f"Top quartile {label} within peer group")

        # Return metrics from scorecard if local data sparse
        if not rets:
            rets = {
                k: nidp_scorecard.get(v)
                for k, v in (("1Y", "return_1y"), ("3Y", "return_3y"),
                             ("5Y", "return_5y"), ("6M", "return_6m"))
                if nidp_scorecard.get(v) is not None
            }

        # TER from scorecard if missing locally
        if expense_ratio is None and nidp_scorecard.get("ter") is not None:
            expense_ratio = nidp_scorecard["ter"]
        if expense_ratio and expense_ratio <= 0.8:
            why.append(f"Low expense ratio ({expense_ratio:.2f}%)")

        # Q4 red flags
        for metric, label in (
            ("qtile_maxdd", "max drawdown"), ("qtile_sortino", "Sortino ratio"),
        ):
            if nidp_scorecard.get(metric) == 4:
                watch_outs.append(f"Bottom quartile {label} within peer group")

    else:
        # ── Heuristic fallback (no NIDP data yet) ────────────────────
        score = 50
        if expense_ratio and expense_ratio <= 0.8:
            score += 15
            why.append(f"Low expense ratio ({expense_ratio:.2f}%)")
        if rets.get("5Y") and rets["5Y"] >= 15:
            score += 15
            why.append(f"Strong 5Y rolling return ({rets['5Y']:.1f}%)")
        if rets.get("3Y") and rets["3Y"] >= 15:
            score += 10
        if (scheme.get("category") or "").lower().startswith("flexi"):
            why.append("Flexi-cap mandate gives manager full freedom")
        score = max(20, min(score, 95))
        verdict = (
            "Strong Buy" if score >= 80 else
            "Buy"        if score >= 65 else
            "Hold"       if score >= 50 else
            "Sell"
        )

    # ── Lifecycle events → watch-outs ────────────────────────────────
    if isinstance(nidp_events, list):
        for ev in nidp_events:
            ev_type = (ev.get("event_type") or "").upper()
            if ev_type in _RED_FLAG_EVENT_TYPES:
                label = ev_type.replace("_", " ").title()
                detail = ev.get("description") or ev.get("detail") or ""
                nidp_red_flags.append(label)
                msg = f"⚠️ {label}"
                if detail:
                    msg += f": {detail[:80]}"
                if msg not in watch_outs:
                    watch_outs.append(msg)

    # Regular-plan cost warning (local data)
    if scheme.get("plan_type", "").lower() == "regular":
        watch_outs.append("Regular plan — Direct version saves ~0.8%/yr on expense")
        if not nidp_scorecard:
            score -= 5

    if not why:
        why = ["Stable manager tenure", "Consistent rolling returns"]

    data_source = ["AMFI", "mf_master", "NIDP"] if nidp_scorecard else ["AMFI", "mf_master"]

    data = FundCardData(
        scheme_code=scheme_code,
        scheme_name=scheme_name,
        category=scheme.get("category"),
        plan_type=scheme.get("plan_type"),
        nav=scheme.get("nav") or scheme.get("current_nav"),
        aum_cr=aum_cr,
        risk_label=scheme.get("risk_label") or scheme.get("riskometer"),
        verdict=verdict,
        verdict_score=score,
        why=why,
        watch_outs=watch_outs,
        returns=rets,
        benchmark=scheme.get("benchmark"),
        alpha=scheme.get("alpha") or (nidp_scorecard or {}).get("alpha_1y"),
        expense_ratio=expense_ratio,
        manager_tenure_years=scheme.get("manager_tenure_years"),
        nidp_composite_score=nidp_composite_score,
        nidp_quality_label=nidp_quality_label,
        nidp_composite_rank=nidp_composite_rank,
        nidp_total_in_category=nidp_total_in_category,
        nidp_top_position_pct=nidp_top_position_pct,
        nidp_red_flags=nidp_red_flags,
    )

    env = WidgetEnvelope(
        kind="fund_card",
        title=scheme_name,
        freshness=FreshnessChip(
            state="live" if nidp_scorecard else "cached",
            last_updated=_iso_now(),
            source=data_source,
            confidence=score,
        ),
        agent=AgentInfo(id="mf_research", label="Mutual Fund Research",
                        version="v2" if nidp_scorecard else "v1", confidence=score),
        data=data.model_dump(),
        primary_cta={"label": "Compare with my fund", "action": "compare_with_mine"},
        suggestions=[
            "Compare with my fund",
            "Show overlap with my portfolio",
            "Cheaper alternatives",
            "Start SIP",
        ],
    )
    return env.model_dump()


# ── 2. Market Brief ─────────────────────────────────────────────

@router.post("/market_brief")
async def market_brief(request: Request):
    """Today's market brief widget. Reads the NIDP DaaS
    `/v1/intelligence/snapshots/market` endpoint (already deployed)
    and overlays the user's portfolio impact (Phase C will plug
    the impact in; Phase B just shows market-side data)."""
    await get_current_user(request)

    snap = await _daas_get("/v1/intelligence/snapshots/market")
    # snap shape (from existing intelligence router): {data:{...}} or raw dict
    snap = (snap or {}).get("data") if isinstance(snap, dict) and "data" in snap else snap
    if not snap:
        # Fallback: lightweight local fixture so the widget still renders
        snap = {
            "nifty_close": None, "nifty_change_pct": None,
            "banknifty_close": None, "banknifty_change_pct": None,
            "fii_net_cr": None, "dii_net_cr": None,
            "regime": "UNKNOWN",
            "as_of_date": None,
        }

    # Build envelope
    indices: List[MarketBriefIndex] = []
    if snap.get("nifty_close") is not None:
        indices.append(MarketBriefIndex(
            name="Nifty 50", value=float(snap["nifty_close"]),
            change_pct=float(snap.get("nifty_change_pct") or 0),
        ))
    if snap.get("banknifty_close") is not None:
        indices.append(MarketBriefIndex(
            name="Bank Nifty", value=float(snap["banknifty_close"]),
            change_pct=float(snap.get("banknifty_change_pct") or 0),
        ))

    fii = snap.get("fii_net_cr")
    dii = snap.get("dii_net_cr")
    fii_dii = None
    if fii is not None or dii is not None:
        fii_dii = {
            "fii_cr": float(fii or 0),
            "dii_cr": float(dii or 0),
            "net_cr": float((fii or 0) + (dii or 0)),
        }

    bullets: List[str] = []
    regime = (snap.get("regime") or "").upper()
    if regime == "RISK_OFF":
        bullets.append("Regime: RISK_OFF — institutional flows leaning defensive")
    elif regime == "RISK_ON":
        bullets.append("Regime: RISK_ON — institutional flows favouring growth")
    if fii_dii and fii_dii["fii_cr"] < -1000:
        bullets.append(f"FII heavy selling: ₹{abs(fii_dii['fii_cr']):,.0f} Cr outflow")
    if fii_dii and fii_dii["dii_cr"] > 1000:
        bullets.append(f"DII absorbing supply: ₹{fii_dii['dii_cr']:,.0f} Cr inflow")
    if not bullets:
        bullets.append("Market data being refreshed — full brief loads after the next NIDP tick.")

    data = MarketBriefData(
        indices=indices,
        sector_heatmap=snap.get("sectors") or [],
        breadth=snap.get("breadth"),
        fii_dii=fii_dii,
        summary_bullets=bullets,
        portfolio_impact=None,   # Phase C wires this
    )

    as_of = snap.get("as_of_date") or _iso_now()
    state = "live" if indices else "stale"

    env = WidgetEnvelope(
        kind="market_brief",
        title="Markets · Today",
        freshness=FreshnessChip(
            state=state, last_updated=str(as_of),
            source=["NIDP", "NSE", "DaaS"],
        ),
        agent=AgentInfo(id="market_strategist", label="Market Strategist",
                        version="v1", confidence=84),
        data=data.model_dump(),
        primary_cta={"label": "Impact on my portfolio", "action": "portfolio_impact"},
        suggestions=[
            "Which sectors should I trim?",
            "Set an alert on Nifty 50",
            "FII/DII trends over 5 days",
        ],
    )
    return env.model_dump()


# ── 3. Compare Table ────────────────────────────────────────────

class CompareRequest(BaseModel):
    scheme_codes: List[str] = Field(..., min_items=2, max_items=4)


@router.post("/compare_funds")
async def compare_funds(request: Request, payload: CompareRequest):
    """Build a Compare-Table widget for 2–4 schemes."""
    await get_current_user(request)
    codes = payload.scheme_codes
    schemes = []
    async for doc in db.mf_master.find(
        {"scheme_code": {"$in": codes}}, {"_id": 0},
    ):
        schemes.append(doc)
    if len(schemes) < 2:
        raise HTTPException(status_code=404,
                            detail="Need at least 2 valid scheme codes")
    # Preserve request order
    schemes.sort(key=lambda d: codes.index(d["scheme_code"]) if d.get("scheme_code") in codes else 99)
    names = [s.get("scheme_name", s.get("scheme_code", "?")) for s in schemes]

    def _row(metric: str, key: str, higher_is_better: bool = True,
             getter=None) -> CompareRow:
        vals = []
        for s in schemes:
            v = (getter(s) if getter else s.get(key))
            vals.append(v)
        numeric = [(i, v) for i, v in enumerate(vals) if isinstance(v, (int, float))]
        best_i = worst_i = None
        if numeric:
            if higher_is_better:
                best_i = max(numeric, key=lambda kv: kv[1])[0]
                worst_i = min(numeric, key=lambda kv: kv[1])[0]
            else:
                best_i = min(numeric, key=lambda kv: kv[1])[0]
                worst_i = max(numeric, key=lambda kv: kv[1])[0]
        return CompareRow(
            metric=metric, values=vals,
            best_index=best_i, worst_index=worst_i,
            higher_is_better=higher_is_better,
        )

    rets_get = lambda s, w: ((s.get("returns_summary") or {}).get(w))  # noqa: E731

    rows: List[CompareRow] = [
        _row("Category", "category", higher_is_better=True),
        _row("1Y return %",  "", getter=lambda s: rets_get(s, "1Y"),  higher_is_better=True),
        _row("3Y rolling %", "", getter=lambda s: rets_get(s, "3Y"),  higher_is_better=True),
        _row("5Y rolling %", "", getter=lambda s: rets_get(s, "5Y"),  higher_is_better=True),
        _row("Expense ratio %", "expense_ratio", higher_is_better=False),
        _row("AUM (₹ Cr)", "aum_cr", higher_is_better=True),
        _row("Manager tenure (yr)", "manager_tenure_years", higher_is_better=True),
    ]

    verdict = None
    fivey = [(i, rets_get(s, "5Y")) for i, s in enumerate(schemes)]
    fivey_numeric = [(i, v) for i, v in fivey if isinstance(v, (int, float))]
    if fivey_numeric:
        winner_i, winner_v = max(fivey_numeric, key=lambda kv: kv[1])
        verdict = (
            f"{names[winner_i]} leads on 5Y rolling return ({winner_v:.1f}%). "
            "Diff-highlighted cells flag the per-metric best and worst."
        )

    data = CompareTableData(
        funds=names, rows=rows, verdict=verdict, differences_only_default=False,
    )

    env = WidgetEnvelope(
        kind="compare_table",
        title=f"Compare — {len(schemes)} funds",
        freshness=FreshnessChip(state="cached", last_updated=_iso_now(),
                                source=["mf_master"]),
        agent=AgentInfo(id="mf_research", label="Mutual Fund Research", version="v1",
                        confidence=82),
        data=data.model_dump(),
        primary_cta={"label": "Switch to leader", "action": "switch_to_leader"},
        suggestions=[
            "Show overlap between these",
            "Cheaper alternatives",
            "Explain the verdict",
        ],
    )
    return env.model_dump()


# ── 4. SIP plan ─────────────────────────────────────────────────

class SipPlanRequest(BaseModel):
    monthly_budget: float = Field(..., gt=0, le=10_000_000)
    risk_label: Optional[str] = "Moderate"   # Conservative | Moderate | Aggressive
    years: Optional[int] = Field(default=10, ge=1, le=40)
    goal_amount: Optional[float] = Field(default=None, ge=0)
    step_up_pct: Optional[float] = Field(default=0.0, ge=0.0, le=0.5)


# Fund split templates by risk band — used for allocation labels only;
# amounts come from the SIP projection tool.
_SPLITS = {
    "Conservative": [
        ("Nifty 50 Index Fund", 0.30, "equity"),
        ("Short-term Debt Fund", 0.45, "debt"),
        ("Hybrid Equity Savings", 0.25, "balanced"),
    ],
    "Moderate": [
        ("Flexi-Cap Fund (Parag Parikh)", 0.50, "equity"),
        ("Nifty Next 50 Index Fund", 0.30, "equity"),
        ("Short-term Debt Fund", 0.20, "debt"),
    ],
    "Aggressive": [
        ("Flexi-Cap Fund (Parag Parikh)", 0.45, "equity"),
        ("Small-Cap Index Fund", 0.30, "equity"),
        ("Mid-Cap Growth Fund", 0.25, "equity"),
    ],
}

_RATE_BY_CATEGORY = {"equity": 0.12, "debt": 0.07, "balanced": 0.10}


@router.post("/sip_plan")
async def sip_plan(request: Request, payload: SipPlanRequest):
    """SIP allocation envelope backed by the sip.py projection engine."""
    await get_current_user(request)
    rl = (payload.risk_label or "Moderate").title()
    plan = _SPLITS.get(rl, _SPLITS["Moderate"])
    years = payload.years or 10

    # Build per-fund allocations using the projection tool for accurate FV
    try:
        from services.copilot_tools.sip import get_sip_projection
        sip_available = True
    except ImportError:
        sip_available = False

    allocations = []
    portfolio_fv = 0.0
    for scheme_name, pct, cat in plan:
        bucket_amount = payload.monthly_budget * pct
        rationale_rate = _RATE_BY_CATEGORY.get(cat, 0.10)
        if sip_available:
            proj = await get_sip_projection(
                monthly_amount=bucket_amount,
                years=years,
                annual_rate=rationale_rate,
                goal_amount=payload.goal_amount * pct if payload.goal_amount else None,
                step_up_pct=payload.step_up_pct or 0.0,
                fund_category=cat,
            )
            fv_str = f"→ ~₹{proj.data['future_value']:,.0f} in {years}yr" if proj.ok else ""
            portfolio_fv += proj.data.get("future_value", 0) if proj.ok else 0
        else:
            fv_str = ""
        allocations.append(SipPlanAllocation(
            scheme_name=scheme_name,
            monthly_amount=round(bucket_amount / 100) * 100,
            rationale=f"{int(pct * 100)}% of budget · {cat.title()} {fv_str}".strip(),
        ))

    # Build why_these including overall projection summary
    fv_display = f"₹{portfolio_fv / 1e7:.1f}Cr" if portfolio_fv >= 1e7 else (
        f"₹{portfolio_fv / 1e5:.1f}L" if portfolio_fv >= 1e5 else f"₹{portfolio_fv:,.0f}"
    )
    why_these = [
        f"Aligned to {rl} risk profile across {len(plan)} buckets",
        "Blends index + active funds for cost-efficiency and alpha potential",
        f"Projected corpus in {years}yr: ~{fv_display} (before tax, at assumed CAGR)",
    ]
    if payload.step_up_pct and payload.step_up_pct > 0:
        why_these.append(f"{int(payload.step_up_pct * 100)}% annual step-up applied to each bucket")
    counter_points = [
        "Replace flexi-cap with a value/contra fund if you already hold one",
        "STCG applies if equity units redeemed within 12 months",
    ]
    if payload.goal_amount:
        counter_points.insert(0, "Re-run projection if your goal amount or horizon changes")

    data = SipPlanData(
        monthly_budget=payload.monthly_budget,
        allocations=allocations,
        why_these=why_these,
        counter_points=counter_points,
    )
    env = WidgetEnvelope(
        kind="sip_plan",
        title=f"SIP plan · ₹{int(payload.monthly_budget):,}/month · {years}yr",
        freshness=FreshnessChip(state="live", last_updated=_iso_now(),
                                source=["nivesh.sip_engine"]),
        agent=AgentInfo(id="goal_planner", label="Goal Planner",
                        version="v2", confidence=82),
        data=data.model_dump(),
        primary_cta={"label": "Set up SIP", "action": "setup_sip"},
        suggestions=[
            f"What if I increase SIP by 10% every year?",
            "Compare these fund picks",
            "Show tax impact of this plan",
        ],
    )
    return env.model_dump()


# ── 5. Rebalance Plan ───────────────────────────────────────────────

@router.post("/rebalance_plan")
async def rebalance_plan(request: Request):
    """Build a rebalance-plan widget from the user's current holdings.

    Reads `holdings` collection for the authenticated user, computes
    current asset-class weights, and generates BUY/SELL/SWITCH actions
    toward a risk-appropriate target allocation.  Phase C will wire the
    Advisor agent LLM for the rationale text; Phase B uses heuristics.
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    # Fetch holdings ─ try several collection shapes used across the codebase
    raw: list = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)

    current_value = sum(float(h.get("current_value") or h.get("value") or 0) for h in raw)

    actions: list[RebalanceAction] = []
    if raw and current_value > 0:
        # Compute simple equity/debt split from asset_class tag
        equity_val = sum(
            float(h.get("current_value") or 0)
            for h in raw
            if (h.get("asset_class") or "equity").lower() == "equity"
        )
        debt_val = current_value - equity_val
        equity_pct = round(equity_val / current_value * 100, 1)
        debt_pct = round(debt_val / current_value * 100, 1)

        target_equity = 65.0
        target_debt = 35.0

        if equity_pct > target_equity + 5:
            excess = (equity_pct - target_equity) / 100 * current_value
            actions.append(RebalanceAction(
                action="SELL", fund_name="Highest-drift equity fund",
                current_pct=equity_pct, target_pct=target_equity,
                amount_rs=round(excess, -2),
                reason=f"Equity is {equity_pct}% vs target {target_equity}%",
            ))
            actions.append(RebalanceAction(
                action="BUY", fund_name="Short-term Debt Fund",
                current_pct=debt_pct, target_pct=target_debt,
                amount_rs=round(excess, -2),
                reason="Redirect proceeds to restore debt allocation",
            ))
        elif equity_pct < target_equity - 5:
            deficit = (target_equity - equity_pct) / 100 * current_value
            actions.append(RebalanceAction(
                action="BUY", fund_name="Flexi-Cap Fund",
                current_pct=equity_pct, target_pct=target_equity,
                amount_rs=round(deficit, -2),
                reason=f"Equity is {equity_pct}% vs target {target_equity}%",
            ))
        else:
            actions.append(RebalanceAction(
                action="HOLD", fund_name="All holdings",
                current_pct=equity_pct, target_pct=target_equity,
                reason="Allocation is within ±5% of target — no rebalance needed.",
            ))

        # Flag regular-plan funds for a direct-plan switch
        for h in raw[:3]:
            plan = (h.get("plan_type") or "").lower()
            name = h.get("fund_name") or h.get("scheme_name") or "Fund"
            if plan == "regular":
                actions.append(RebalanceAction(
                    action="SWITCH", fund_name=name,
                    reason="Switch Regular → Direct to save ~0.8%/yr expense",
                ))

    summary = (
        f"Portfolio value ₹{current_value:,.0f}. "
        + (f"{len(actions)} action(s) suggested." if actions else "No rebalance needed.")
    )

    data = RebalancePlanData(
        current_value_rs=current_value or None,
        actions=actions,
        summary=summary,
    )
    env = WidgetEnvelope(
        kind="rebalance_plan",
        title="Rebalance Plan",
        freshness=FreshnessChip(state="cached", last_updated=_iso_now(),
                                source=["portfolio_holdings"]),
        agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer",
                        version="v1", confidence=80),
        data=data.model_dump(),
        primary_cta={"label": "Execute plan", "action": "execute_rebalance"},
        suggestions=["Simulate tax impact", "Show only equity changes", "Compare with my goals"],
    )
    return env.model_dump()


# ── 6. Tax Harvest Plan ─────────────────────────────────────────────

@router.post("/tax_harvest")
async def tax_harvest(request: Request):
    """LTCG harvest candidates for the authenticated user.

    Reads `holdings` (or `portfolio_holdings`) and `capital_gains_summary`
    collections.  Candidates = LTCG eligible (held > 365 days) with gains
    under the ₹1L exemption limit still available.
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    raw: list = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)

    # Pull existing LTCG used from capital_gains summary if stored
    cg_doc = await db.capital_gains_summary.find_one({"user_id": user_id}) or {}
    ltcg_used = float(cg_doc.get("ltcg_booked_rs") or 0)
    ltcg_limit = 100_000.0
    ltcg_remaining = max(0.0, ltcg_limit - ltcg_used)

    candidates: list[TaxHarvestCandidate] = []
    total_harvestable = 0.0

    for h in raw:
        gain = float(h.get("unrealised_gain") or h.get("gain") or 0)
        days = int(h.get("days_held") or h.get("holding_days") or 0)
        cost = float(h.get("invested_value") or h.get("cost_basis") or 0)
        curr = float(h.get("current_value") or h.get("value") or 0)
        name = h.get("fund_name") or h.get("scheme_name") or "Unknown Fund"

        if gain <= 0 or days < 365:
            continue

        gain_type = "LTCG"
        eligible = gain <= ltcg_remaining
        total_harvestable += gain if eligible else 0

        candidates.append(TaxHarvestCandidate(
            fund_name=name,
            current_value_rs=curr or None,
            cost_basis_rs=cost or None,
            gain_rs=gain,
            gain_type=gain_type,
            days_held=days or None,
            eligible=eligible,
            wash_sale_risk=False,
        ))

    candidates.sort(key=lambda c: c.gain_rs)   # smallest gain first = safest harvest

    data = TaxHarvestData(
        fy="FY 2025-26",
        ltcg_used_rs=ltcg_used,
        ltcg_limit_rs=ltcg_limit,
        ltcg_remaining_rs=ltcg_remaining,
        candidates=candidates[:8],
        total_harvestable_rs=total_harvestable or None,
        warning="Repurchasing within 30 days may trigger wash-sale rules in some jurisdictions." if candidates else None,
    )
    env = WidgetEnvelope(
        kind="tax_harvest",
        title=f"Tax Harvest Plan · {data.fy}",
        freshness=FreshnessChip(state="cached", last_updated=_iso_now(),
                                source=["portfolio_holdings", "capital_gains_summary"]),
        agent=AgentInfo(id="tax_agent", label="Tax Agent", version="v1", confidence=85),
        data=data.model_dump(),
        primary_cta={"label": "Simulate harvest", "action": "simulate_harvest"},
        suggestions=["Plan switch", "Show STCG separately", "Generate gains statement"],
    )
    return env.model_dump()


# ── 7. Stress Test ──────────────────────────────────────────────────

class StressTestRequest(BaseModel):
    scenario: str = "covid_2020"   # covid_2020 | gfc_2008 | custom
    custom_drop_pct: Optional[float] = None   # only for scenario="custom"


_STRESS_SCENARIOS = {
    "covid_2020": {
        "name": "COVID-19 Crash (Feb–Mar 2020)",
        "description": "Nifty 50 fell ~38% in 40 days. Debt remained largely stable.",
        "equity_drop": -38.0,
        "debt_drop": -2.0,
        "recovery_years": 1.2,
    },
    "gfc_2008": {
        "name": "Global Financial Crisis (2008)",
        "description": "Nifty 50 fell ~60% peak-to-trough over 14 months.",
        "equity_drop": -60.0,
        "debt_drop": -5.0,
        "recovery_years": 4.0,
    },
    "rate_shock": {
        "name": "Rate Shock (+200 bps)",
        "description": "Simulates a sudden 200 bps rate hike. Debt NAVs fall ~4–8%.",
        "equity_drop": -12.0,
        "debt_drop": -7.0,
        "recovery_years": 1.5,
    },
}


@router.post("/stress_test")
async def stress_test(request: Request, payload: StressTestRequest):
    """Simulate portfolio performance under a historical or custom crash scenario."""
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    raw: list = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)

    scen_key = payload.scenario if payload.scenario in _STRESS_SCENARIOS else "covid_2020"
    scen = _STRESS_SCENARIOS[scen_key]

    if payload.scenario == "custom" and payload.custom_drop_pct is not None:
        drop = float(payload.custom_drop_pct)
        scen = {
            "name": f"Custom scenario ({drop:+.0f}%)",
            "description": f"User-defined uniform {drop:+.0f}% shock applied to all holdings.",
            "equity_drop": drop,
            "debt_drop": drop * 0.1,
            "recovery_years": abs(drop) / 15,
        }

    current_value = sum(float(h.get("current_value") or h.get("value") or 0) for h in raw)

    breakdown: list[StressTestBreakdown] = []
    stressed_total = 0.0
    for h in raw:
        name = h.get("fund_name") or h.get("scheme_name") or "Fund"
        curr = float(h.get("current_value") or h.get("value") or 0)
        asset = (h.get("asset_class") or "equity").lower()
        drop_pct = scen["equity_drop"] if asset == "equity" else scen["debt_drop"]
        stressed = curr * (1 + drop_pct / 100)
        stressed_total += stressed
        breakdown.append(StressTestBreakdown(
            fund_name=name,
            current_value_rs=curr,
            stressed_value_rs=round(stressed, 2),
            drop_pct=drop_pct,
        ))

    overall_drop = ((stressed_total - current_value) / current_value * 100) if current_value else 0
    insight = (
        f"Your portfolio would fall to ₹{stressed_total:,.0f} "
        f"({overall_drop:+.1f}%) under this scenario. "
        f"Historical recovery took ~{scen['recovery_years']} year(s)."
    ) if current_value else "Add holdings to run a stress test."

    data = StressTestData(
        scenario_name=scen["name"],
        scenario_description=scen.get("description"),
        current_value_rs=current_value or None,
        stressed_value_rs=round(stressed_total, 2) if current_value else None,
        drop_pct=round(overall_drop, 2) if current_value else None,
        recovery_years=scen.get("recovery_years"),
        breakdown=breakdown[:10],
        insight=insight,
    )
    env = WidgetEnvelope(
        kind="stress_test",
        title=scen["name"],
        freshness=FreshnessChip(state="cached", last_updated=_iso_now(),
                                source=["portfolio_holdings", "nidp.scenarios"]),
        agent=AgentInfo(id="market_strategist", label="Market Strategist",
                        version="v1", confidence=82),
        data=data.model_dump(),
        primary_cta={"label": "Run custom scenario", "action": "custom_stress"},
        suggestions=["Compare with 2008 GFC", "How to reduce drawdown?", "Hedge strategies"],
    )
    return env.model_dump()


# ── 8. Sector Rotation ──────────────────────────────────────────────

@router.post("/sector_rotation")
async def sector_rotation(request: Request):
    """RS quadrant chart data from DaaS, falling back to a static fixture."""
    await get_current_user(request)

    snap = await _daas_get("/v1/intelligence/snapshots/market")
    snap = (snap or {}).get("data") if isinstance(snap, dict) and "data" in snap else snap
    sectors_raw = (snap or {}).get("sectors") or []

    sectors: list[SectorPoint] = []
    for s in sectors_raw:
        name = s.get("name") or s.get("sector")
        rs = s.get("rs_score") or s.get("relative_strength")
        wk = s.get("week_change_pct") or s.get("1w_change")
        mo = s.get("month_change_pct") or s.get("1m_change")
        if not name:
            continue
        # Quadrant derived from RS score + momentum direction
        if rs is not None:
            if rs >= 55 and (mo or 0) >= 0:
                quadrant = "Leading"
            elif rs >= 55 and (mo or 0) < 0:
                quadrant = "Weakening"
            elif rs < 55 and (mo or 0) >= 0:
                quadrant = "Improving"
            else:
                quadrant = "Lagging"
        else:
            quadrant = "Improving"
        sectors.append(SectorPoint(
            name=name, quadrant=quadrant,
            rs_score=float(rs) if rs is not None else None,
            week_change_pct=float(wk) if wk is not None else None,
            month_change_pct=float(mo) if mo is not None else None,
        ))

    if not sectors:
        sectors = [
            SectorPoint(name="Banking", quadrant="Leading", rs_score=62, week_change_pct=0.8, month_change_pct=3.2),
            SectorPoint(name="Auto", quadrant="Leading", rs_score=58, week_change_pct=1.4, month_change_pct=4.1),
            SectorPoint(name="Capital Goods", quadrant="Improving", rs_score=52, week_change_pct=1.1, month_change_pct=1.8),
            SectorPoint(name="IT", quadrant="Lagging", rs_score=41, week_change_pct=-2.1, month_change_pct=-3.5),
            SectorPoint(name="FMCG", quadrant="Weakening", rs_score=57, week_change_pct=-0.4, month_change_pct=-1.2),
            SectorPoint(name="Pharma", quadrant="Improving", rs_score=50, week_change_pct=0.6, month_change_pct=2.0),
            SectorPoint(name="Metals", quadrant="Lagging", rs_score=38, week_change_pct=-1.8, month_change_pct=-4.2),
            SectorPoint(name="Realty", quadrant="Leading", rs_score=61, week_change_pct=2.0, month_change_pct=5.5),
        ]

    data = SectorRotationData(
        horizon="1M",
        sectors=sectors,
        as_of_date=_iso_now(),
    )
    env = WidgetEnvelope(
        kind="sector_rotation",
        title="Sector Rotation · 1M",
        freshness=FreshnessChip(
            state="live" if sectors_raw else "cached",
            last_updated=_iso_now(),
            source=["NIDP", "NSE"],
        ),
        agent=AgentInfo(id="market_strategist", label="Market Strategist",
                        version="v1", confidence=80),
        data=data.model_dump(),
        primary_cta={"label": "Which sectors should I trim?", "action": "sector_trim_advice"},
        suggestions=["Show my exposure to Leading sectors", "Alert me on IT recovery", "3M view"],
    )
    return env.model_dump()


# ── 9. Overlap Reveal ───────────────────────────────────────────────

class OverlapRequest(BaseModel):
    scheme_codes: Optional[List[str]] = None   # if None → use user's portfolio


@router.post("/overlap_reveal")
async def overlap_reveal(request: Request, payload: OverlapRequest):
    """Show stock-level overlap between two or more funds.

    If `scheme_codes` is supplied, compares those funds.  Otherwise,
    compares all funds in the user's portfolio.  Uses `mf_portfolio_stocks`
    (top-holdings per scheme) from the local DB.
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    codes = payload.scheme_codes or []
    if not codes:
        async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
            c = h.get("scheme_code") or h.get("isin")
            if c:
                codes.append(c)
        if not codes:
            async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
                c = h.get("scheme_code") or h.get("isin")
                if c:
                    codes.append(c)
    codes = list(dict.fromkeys(codes))[:4]   # dedupe, max 4

    # Pull top-holdings per scheme from mf_portfolio_stocks or mf_master
    fund_stocks: dict[str, set[str]] = {}
    fund_names: dict[str, str] = {}
    for code in codes:
        doc = await db.mf_master.find_one(
            {"$or": [{"scheme_code": code}, {"isin": code}]}, {"_id": 0}
        )
        if not doc:
            continue
        name = doc.get("scheme_name") or code
        fund_names[code] = name
        stocks_raw = doc.get("top_holdings") or []
        fund_stocks[code] = {
            (s.get("stock_name") or s.get("name") or "").strip()
            for s in stocks_raw if s.get("stock_name") or s.get("name")
        }

    all_funds = list(fund_stocks.keys())
    names = [fund_names.get(c, c) for c in all_funds]

    common_stocks: list[OverlapStock] = []
    overlap_pct = None
    matrix = None

    if len(all_funds) >= 2:
        # Pairwise overlap for exactly 2 funds
        if len(all_funds) == 2:
            s0, s1 = fund_stocks[all_funds[0]], fund_stocks[all_funds[1]]
            common = s0 & s1
            denom = len(s0 | s1)
            overlap_pct = round(len(common) / denom * 100, 1) if denom else 0.0
            for stk in sorted(common):
                if stk:
                    common_stocks.append(OverlapStock(
                        stock_name=stk,
                        funds=[fund_names.get(c, c) for c in all_funds if stk in fund_stocks[c]],
                    ))
        else:
            # NxN matrix
            matrix = []
            for ci in all_funds:
                row = []
                for cj in all_funds:
                    si, sj = fund_stocks[ci], fund_stocks[cj]
                    denom = len(si | sj)
                    row.append(round(len(si & sj) / denom * 100, 1) if denom else 0.0)
                matrix.append(row)
            # Cross-fund common stocks
            all_common = set.intersection(*fund_stocks.values()) if fund_stocks else set()
            for stk in sorted(all_common):
                if stk:
                    common_stocks.append(OverlapStock(
                        stock_name=stk,
                        funds=names,
                    ))

    verdict = None
    if overlap_pct is not None:
        if overlap_pct > 50:
            verdict = f"High overlap ({overlap_pct}%) — these funds largely hold the same stocks."
        elif overlap_pct > 25:
            verdict = f"Moderate overlap ({overlap_pct}%) — some diversification benefit."
        else:
            verdict = f"Low overlap ({overlap_pct}%) — good diversification between these funds."
    elif not all_funds:
        verdict = "No fund data found. Try specifying scheme codes or add holdings."

    data = OverlapRevealData(
        funds=names or codes,
        overlap_pct=overlap_pct,
        overlap_matrix=matrix,
        top_common_stocks=common_stocks[:8],
        verdict=verdict,
    )
    env = WidgetEnvelope(
        kind="overlap_reveal",
        title=f"Overlap · {' vs '.join(names[:2]) if len(names) >= 2 else 'Portfolio funds'}",
        freshness=FreshnessChip(state="cached", last_updated=_iso_now(),
                                source=["mf_master"]),
        agent=AgentInfo(id="mf_research", label="Mutual Fund Research",
                        version="v1", confidence=78),
        data=data.model_dump(),
        primary_cta={"label": "Find alternatives with less overlap", "action": "reduce_overlap"},
        suggestions=["Cheaper alternatives", "Compare returns", "Remove a fund"],
    )
    return env.model_dump()


# ── 10. Risk Suitability ────────────────────────────────────────────

@router.post("/risk_suitability")
async def risk_suitability_widget(request: Request):
    """Portfolio risk rating vs user's risk profile.

    Calls services.copilot_tools.risk.get_risk_suitability() which computes
    equity %, small/mid-cap exposure, weighted portfolio beta from DAAS
    volatility_20d, and flags misalignments vs the user's stored risk profile
    (conservative / moderate / aggressive).
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    try:
        from services.copilot_tools.risk import get_risk_suitability
        result = await get_risk_suitability(user_id)
    except Exception as exc:
        logger.warning("risk_suitability widget error: %s", exc)
        return WidgetEnvelope(
            kind="risk_suitability",
            title="Risk Suitability",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="risk_analyst", label="Risk Analyst", version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    _RATING_COLOR = {
        "LOW": "#10B981", "MEDIUM": "#F59E0B",
        "HIGH": "#EF4444", "VERY HIGH": "#DC2626",
    }

    data = {
        "risk_rating": result.risk_rating,
        "risk_score": result.risk_score_0_to_10,
        "user_profile_category": result.user_profile_category,
        "misalignment": result.misalignment,
        "misalignment_count": len(result.misalignment),
        "rating_color": _RATING_COLOR.get(result.risk_rating, "#94A3B8"),
        **result.data,
        "rows": result.rows,
    }

    confidence = max(0, min(99, int(85 - len(result.misalignment) * 5)))
    env = WidgetEnvelope(
        kind="risk_suitability",
        title=f"Risk Suitability · {result.risk_rating}",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["portfolio_holdings", "user_profile", "DAAS"],
        ),
        agent=AgentInfo(id="risk_analyst", label="Risk Analyst",
                        version="v1", confidence=confidence),
        data=data,
        primary_cta={"label": "How do I reduce my risk?", "action": "reduce_risk"},
        suggestions=[
            "What is my portfolio beta?",
            "Rebalance to match my risk profile",
            "Show my VaR breakdown",
        ],
    )
    return env.model_dump()


# ── 11. Portfolio VaR ───────────────────────────────────────────────

@router.post("/portfolio_var")
async def portfolio_var_widget(request: Request):
    """Parametric Value at Risk for the user's portfolio.

    Calls services.copilot_tools.risk.get_portfolio_var() which computes
    weighted daily volatility using DAAS volatility_20d for stocks and
    equity_allocation_pct proxies for MFs, then returns 1-day and 10-day
    VaR at 95% and 99% confidence.
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    try:
        from services.copilot_tools.risk import get_portfolio_var
        result = await get_portfolio_var(user_id, confidence=0.95)
    except Exception as exc:
        logger.warning("portfolio_var widget error: %s", exc)
        return WidgetEnvelope(
            kind="portfolio_var",
            title="Portfolio VaR",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="risk_analyst", label="Risk Analyst", version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    data = {
        "risk_rating": result.risk_rating,
        "risk_score": result.risk_score_0_to_10,
        **result.data,
        "rows": result.rows,
    }

    env = WidgetEnvelope(
        kind="portfolio_var",
        title="Portfolio VaR · 95% Confidence",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["portfolio_holdings", "DAAS"],
        ),
        agent=AgentInfo(id="risk_analyst", label="Risk Analyst",
                        version="v1", confidence=82),
        data=data,
        primary_cta={"label": "How do I reduce my VaR?", "action": "reduce_var"},
        suggestions=[
            "What drives my portfolio risk?",
            "Show my most volatile holding",
            "Add a hedge to my portfolio",
        ],
    )
    return env.model_dump()


# ── 10. FD Comparison ───────────────────────────────────────────────

@router.post("/fd_comparison")
async def fd_comparison_widget(request: Request):
    """Compare portfolio XIRR against current FD benchmark rates.

    Used for: "Am I beating FD?", "Is my portfolio better than fixed deposit?"
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    try:
        from services.copilot_tools.portfolio import get_fd_comparison
        result = await get_fd_comparison(user_id)
    except Exception as exc:
        logger.warning("fd_comparison widget error: %s", exc)
        return WidgetEnvelope(
            kind="fd_comparison",
            title="Portfolio vs FD",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer",
                            version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    verdict = result.data.get("verdict", "")
    xirr = result.data.get("portfolio_xirr_pct", 0)
    outperformance = result.data.get("outperformance_pp", 0)

    env = WidgetEnvelope(
        kind="fd_comparison",
        title="Portfolio vs Fixed Deposit",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["portfolio_holdings", "fd_rates"],
        ),
        agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer",
                        version="v1", confidence=85),
        data={**result.data, "rows": result.rows},
        primary_cta={
            "label": "How to improve returns?",
            "action": "improve_returns",
        },
        suggestions=[
            "Show my best performing holdings",
            "Which funds should I switch?",
            "How does my equity compare to Nifty?",
        ],
    )
    return env.model_dump()


# ── 11. Tax Timing Advice ────────────────────────────────────────────

@router.post("/tax_timing")
async def tax_timing_widget(request: Request):
    """Identify holdings where waiting for LTCG classification saves tax.

    Used for: "When should I sell?", "Am I close to long-term?",
              "Which holdings flip to LTCG soon?"
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    try:
        from services.copilot_tools.portfolio import get_tax_timing_advice
        result = await get_tax_timing_advice(user_id)
    except Exception as exc:
        logger.warning("tax_timing widget error: %s", exc)
        return WidgetEnvelope(
            kind="tax_timing",
            title="Tax Timing Advice",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="tax_agent", label="Tax Agent",
                            version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    total_saving = result.data.get("total_tax_saving_if_wait_rs", 0)
    flip_count = result.data.get("ltcg_flip_count", 0)

    env = WidgetEnvelope(
        kind="tax_timing",
        title="Tax Timing · LTCG Optimiser",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["portfolio_holdings"],
        ),
        agent=AgentInfo(id="tax_agent", label="Tax Agent",
                        version="v1", confidence=88),
        data={**result.data, "rows": result.rows},
        primary_cta={
            "label": f"View {flip_count} LTCG flip opportunities",
            "action": "view_ltcg_flips",
        } if flip_count else {
            "label": "Show full tax report",
            "action": "full_tax_report",
        },
        suggestions=[
            "What's my total capital gains this year?",
            "Which losses can I harvest?",
            "Show tax report for FY 2025-26",
        ],
    )
    return env.model_dump()


# ── 12. Company Financials & Prospects ───────────────────────────────

class CompanyFinancialsRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=20,
                        description="NSE symbol (e.g. RELIANCE, TCS, INFY)")
    quarters: int = Field(8, ge=2, le=16,
                          description="Number of quarters to fetch (2-16)")


@router.post("/company_financials")
async def company_financials_widget(request: Request, payload: CompanyFinancialsRequest):
    """Multi-quarter P&L trend + balance sheet + shareholding + prospects signal.

    Used for: "Show RELIANCE quarterly results", "Future prospects of TCS",
              "Company overview", "Revenue trend", "Earnings history"
    """
    _ = await get_current_user(request)

    try:
        from services.copilot_tools.company_financials import get_company_overview
        result = await get_company_overview(payload.symbol)
    except Exception as exc:
        logger.warning("company_financials widget error: %s", exc)
        return WidgetEnvelope(
            kind="company_financials",
            title=f"{payload.symbol} — Financials",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="fundamental_analyst", label="Fundamental Analyst",
                            version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    outlook = result.data.get("outlook_label", "Neutral")
    trend = result.data.get("growth_trend", "")

    env = WidgetEnvelope(
        kind="company_financials",
        title=f"{payload.symbol.upper()} — Financials & Prospects",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["nse_financials_quarterly", "shareholding_pattern", "stock_features_daily"],
        ),
        agent=AgentInfo(id="fundamental_analyst", label="Fundamental Analyst",
                        version="v1", confidence=80),
        data={**result.data, "rows": result.rows},
        primary_cta={
            "label": f"View peer comparison",
            "action": "peer_compare",
        },
        suggestions=[
            f"Technical setup for {payload.symbol.upper()}",
            f"Should I add {payload.symbol.upper()} to my portfolio?",
            f"Recent announcements for {payload.symbol.upper()}",
        ],
    )
    return env.model_dump()


@router.post("/fd_comparison")
async def fd_comparison_widget(request: Request):
    """Compare portfolio XIRR vs FD benchmark rates.

    Used for quick-action: 'Am I beating FD?'
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    try:
        from services.copilot_tools.portfolio import get_fd_comparison
        result = await get_fd_comparison(user_id)
    except Exception as exc:
        logger.warning("fd_comparison widget error: %s", exc)
        return WidgetEnvelope(
            kind="fd_comparison",
            title="FD Comparison",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer", version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    env = WidgetEnvelope(
        kind="fd_comparison",
        title="Portfolio vs Fixed Deposit",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["portfolio_holdings"],
        ),
        agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer",
                        version="v1", confidence=80),
        data={**result.data, "rows": result.rows},
        primary_cta={"label": "Improve my returns", "action": "rebalance"},
        suggestions=[
            "How to beat FD consistently?",
            "Which asset class is underperforming?",
            "Show my top performing holdings",
        ],
    )
    return env.model_dump()


@router.post("/tax_timing")
async def tax_timing_widget(request: Request):
    """Identify LTCG flip opportunities and tax-optimal sell timing.

    Used for: 'When should I sell?', 'Am I close to LTCG?'
    """
    user = await get_current_user(request)
    user_id = str(user.get("_id") or user.get("id") or "")

    try:
        from services.copilot_tools.portfolio import get_tax_timing_advice
        result = await get_tax_timing_advice(user_id)
    except Exception as exc:
        logger.warning("tax_timing widget error: %s", exc)
        return WidgetEnvelope(
            kind="tax_timing",
            title="Tax Timing",
            freshness=FreshnessChip(state="stale", last_updated=_iso_now(), source=[]),
            agent=AgentInfo(id="tax_agent", label="Tax Agent", version="v1", confidence=0),
            data={"error": str(exc)},
        ).model_dump()

    env = WidgetEnvelope(
        kind="tax_timing",
        title="Tax Timing Optimiser",
        freshness=FreshnessChip(
            state="live" if result.ok else "stale",
            last_updated=_iso_now(),
            source=["portfolio_holdings"],
        ),
        agent=AgentInfo(id="tax_agent", label="Tax Agent", version="v1", confidence=85),
        data={**result.data, "rows": result.rows},
        primary_cta={"label": "Show full tax report", "action": "full_tax_report"},
        suggestions=[
            "Which holdings should I harvest losses on?",
            "Show my LTCG vs STCG breakdown",
            "How much LTCG exemption is left?",
        ],
    )
    return env.model_dump()
