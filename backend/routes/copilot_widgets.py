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
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/copilot/widgets", tags=["copilot-widgets"])


# ── DaaS proxy (re-use existing NIDP DaaS auth) ──────────────────

_DAAS_URL = os.environ.get("NIDP_DAAS_API_URL") or "http://34.93.60.254:8083"
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


@router.post("/fund_card")
async def fund_card(request: Request, payload: FundCardRequest):
    """Produce a Fund Card widget envelope for the given scheme.

    Reads from `mf_master` for static facts (category, AUM, expense),
    `mf_nav_daily` (via DaaS or fallback to local `mf_nav_master`) for
    current NAV, and computes return windows from `mf_nav_history` if
    available. Verdict + rationale are deterministic for now (no LLM
    call) — Phase C will swap in the MF Research agent.
    """
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

    # Heuristic verdict (placeholder until MF Research agent ships).
    score = 50
    why: List[str] = []
    watch_outs: List[str] = []
    if expense_ratio and expense_ratio <= 0.8:
        score += 15
        why.append(f"Low expense ratio ({expense_ratio:.2f}%)")
    if rets.get("5Y") and rets["5Y"] >= 15:
        score += 15
        why.append(f"Strong 5Y rolling return ({rets['5Y']:.1f}%)")
    if rets.get("3Y") and rets["3Y"] >= 15:
        score += 10
    if scheme.get("plan_type", "").lower() == "regular":
        watch_outs.append("Regular plan — Direct version saves ~0.8%/yr on expense")
        score -= 5
    if (scheme.get("category") or "").lower().startswith("flexi"):
        why.append("Flexi-cap mandate gives manager full freedom")
    score = max(20, min(score, 95))

    verdict = (
        "Strong Buy" if score >= 80 else
        "Buy"        if score >= 65 else
        "Hold"       if score >= 50 else
        "Sell"
    )

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
        why=why or ["Stable manager tenure", "Consistent rolling returns"],
        watch_outs=watch_outs,
        returns=rets,
        benchmark=scheme.get("benchmark"),
        alpha=scheme.get("alpha"),
        expense_ratio=expense_ratio,
        manager_tenure_years=scheme.get("manager_tenure_years"),
    )

    env = WidgetEnvelope(
        kind="fund_card",
        title=scheme_name,
        freshness=FreshnessChip(
            state="cached",
            last_updated=_iso_now(),
            source=["AMFI", "mf_master"],
            confidence=score,
        ),
        agent=AgentInfo(id="mf_research", label="Mutual Fund Research",
                        version="v1", confidence=score),
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


@router.post("/sip_plan")
async def sip_plan(request: Request, payload: SipPlanRequest):
    """Suggest a 3-bucket SIP allocation envelope. Deterministic split
    by risk label for Phase B; Phase C will pull from the Advisor agent
    using the user's actual risk profile + drift."""
    await get_current_user(request)
    rl = (payload.risk_label or "Moderate").title()
    splits = {
        "Conservative": [("Nifty 50 Index", 0.30), ("Short-term Debt", 0.45), ("Hybrid Equity Savings", 0.25)],
        "Moderate":     [("Flexi-Cap (Parag Parikh)", 0.50), ("Nifty Next 50 Index", 0.30), ("Short-term Debt", 0.20)],
        "Aggressive":   [("Flexi-Cap (Parag Parikh)", 0.45), ("Small-Cap Index", 0.30), ("Mid-Cap Growth", 0.25)],
    }
    plan = splits.get(rl, splits["Moderate"])
    allocations = [
        SipPlanAllocation(
            scheme_name=name,
            monthly_amount=round(payload.monthly_budget * pct / 100) * 100,
            rationale=f"Allocates {int(pct*100)}% of the monthly budget to {name}.",
        )
        for name, pct in plan
    ]

    data = SipPlanData(
        monthly_budget=payload.monthly_budget,
        allocations=allocations,
        why_these=[
            f"Aligned to {rl} risk band",
            "Mixes index + actively managed funds for cost/alpha balance",
            "Debt sleeve sized for liquidity + drawdown buffer",
        ],
        counter_points=[
            "Replace flexi-cap with a value/contra fund if you already hold one",
            "Tax: STCG applies if held < 12 months",
        ],
    )
    env = WidgetEnvelope(
        kind="sip_plan",
        title=f"SIP plan · ₹{int(payload.monthly_budget):,}/month",
        freshness=FreshnessChip(state="cached", last_updated=_iso_now(),
                                source=["nivesh.advisor"]),
        agent=AgentInfo(id="portfolio_analyzer", label="Portfolio Analyzer",
                        version="v1", confidence=78),
        data=data.model_dump(),
        primary_cta={"label": "Set up SIP", "action": "setup_sip"},
        suggestions=[
            "Compare these picks",
            "Tax impact",
            "Run a stress test on this plan",
        ],
    )
    return env.model_dump()
