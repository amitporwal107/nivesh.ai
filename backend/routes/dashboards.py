"""GET /api/dashboards/{type} — unified dashboard composite endpoint.

Per docs/api-changes.md New Endpoint B.1 (approved 2026-05-24).

Serves screens (mobile + webapp):
  05 Concentration Dashboard
  06 Diversification Dashboard
  07 Risk Dashboard
  08 Performance Dashboard
  09 Goals Dashboard
  10 Tax Dashboard

Each call composes three logical reads (within the ≤3 DB-query budget):
  1. Domain service (concentration / overlap / risk / performance / goals / tax)
  2. GET /api/plans/active filtered by source_domain (action recommendations)
  3. Health projection delta (cached read from Redis or Mongo plan doc)

Additive: the six focused endpoints
  /api/portfolio/exposure/concentration
  /api/portfolio/exposure/fund-overlap/matrix
  /api/portfolio/risk-analytics
  /api/portfolio/fund-performance
  /api/goals
  /api/portfolio/tax-summary
remain unchanged for existing mobile-app + partner callers.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services.action_plan_manager import ActionPlanManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])

_plan_mgr = ActionPlanManager()

VALID_TYPES = {"concentration", "diversification", "risk", "performance", "goals", "tax"}


# ── Tone helpers ──────────────────────────────────────────────────────────────

def _pct_tone(pct: float, caution: float = 25.0) -> str:
    if pct >= caution * 1.4:
        return "rust"
    if pct >= caution:
        return "saffron"
    return "moss"


def _score_tone(score: Optional[float]) -> str:
    if score is None:
        return "mute"
    if score >= 70:
        return "moss"
    if score >= 50:
        return "saffron"
    return "rust"


def _beta_tone(beta: Optional[float]) -> str:
    if beta is None:
        return "mute"
    if beta >= 1.3:
        return "rust"
    if beta >= 1.0:
        return "saffron"
    return "moss"


# ── Health projection helper ──────────────────────────────────────────────────

async def _health_projection(user_id: str, source_domain: str) -> dict[str, Any]:
    """Current health score + projected score after accepting PENDING domain actions."""
    from services.portfolio_health import build_portfolio_health as _bph
    try:
        hr = await _bph(user_id)
        current = hr.health_score or 0
    except Exception:
        current = None

    plan = await _plan_mgr.get_active_plan(user_id, source_domain=source_domain)
    deltas = [
        float(a.get("expected_impact", {}).get("health_delta") or 0)
        for a in (plan.get("actions") or [])
        if (a.get("status") or "").upper() == "PENDING"
    ]
    projected = round(current + sum(deltas), 1) if current is not None else None
    tone = _score_tone(projected)

    return {
        "metric_label": "Projected health",
        "current": current,
        "projected": projected,
        "unit": "",
        "tone": tone,
    }


# ── Domain compositors ────────────────────────────────────────────────────────

async def _concentration_composite(user_id: str, lens: str) -> dict[str, Any]:
    """Serves screen 05 Concentration Dashboard."""
    from services.portfolio_concentration import compute_concentration
    from routes.portfolio_exposure import _load_fund_lookthrough

    holdings = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "sector": 1, "amc": 1},
    ).to_list(1000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user
        holdings = await pi_holdings_for_user(user_id)

    if not holdings:
        return _empty_domain("concentration")

    lookthrough = await _load_fund_lookthrough(holdings)
    env = compute_concentration(holdings, fund_lookthrough=lookthrough)

    # Pick the requested lens; default sector
    lens_map = {"sector": env.get("sector"), "amc": env.get("amc"),
                "company": env.get("company"), "group": env.get("group")}
    lens_data = lens_map.get(lens) or env.get("sector") or {}

    items = lens_data.get("items") or []
    top5_pct = lens_data.get("top5_pct") or (
        round(sum(i.get("pct", 0) for i in items[:5]), 2) if items else 0.0
    )
    caution_pct = lens_data.get("caution_pct") or 25
    largest_pct = lens_data.get("largest_pct") or (items[0].get("pct", 0) if items else 0)
    hhi = lens_data.get("hhi_x10000") or 0

    tone = _pct_tone(largest_pct, caution_pct)
    badge_label = "High" if tone == "rust" else ("Moderate" if tone == "saffron" else "Low")

    breakdown_items = [
        {
            "name": it.get("name") or it.get("sector") or it.get("amc") or "Other",
            "pct": round(float(it.get("pct", 0)), 2),
            "tone": _pct_tone(float(it.get("pct", 0)), caution_pct),
        }
        for it in items[:10]
    ]

    return {
        "badge": {"label": badge_label, "tone": tone},
        "insight": {
            "headline": _concentration_headline(lens, items, caution_pct),
            "subtext": lens_data.get("warning") or "",
            "hero": {"label": "TOP 5", "value": f"{top5_pct:.0f}%", "tone": tone},
        },
        "stat_tiles": [
            {"label": "Top 5", "value": f"{top5_pct:.0f}%", "tone": tone},
            {"label": "HHI", "value": str(hhi), "sub": badge_label},
            {"label": "Eff. N", "value": str(lens_data.get("effective_n") or "—")},
        ],
        "breakdown": {
            "lens": lens,
            "lens_options": ["sector", "amc", "company", "group"],
            "caution_pct": caution_pct,
            "items": breakdown_items,
        },
    }


def _concentration_headline(lens: str, items: list, caution_pct: float) -> str:
    if not items:
        return "No concentration data yet."
    top = items[0]
    name = top.get("name") or top.get("sector") or "the top bucket"
    pct = round(float(top.get("pct", 0)))
    return f"{pct}% of your money is in {name}" + (
        f" — above the {caution_pct}% caution line." if pct > caution_pct else "."
    )


async def _diversification_composite(user_id: str, lens: str) -> dict[str, Any]:
    """Serves screen 06 Diversification Dashboard."""
    from routes.portfolio_exposure import (
        _load_fund_lookthrough, _build_fund_weights, _overlap_pct,
    )

    holdings = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "amc_name": 1, "category": 1},
    ).to_list(1000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user
        holdings = await pi_holdings_for_user(user_id)

    if not holdings:
        return _empty_domain("diversification")

    mf_holdings = [h for h in holdings
                   if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"}]
    fund_count = len(mf_holdings)

    # Fund overlap summary
    max_overlap = 0.0
    high_pairs = 0
    unique_stocks: set[str] = set()
    if len(mf_holdings) >= 2:
        isins = list({h["ticker"] for h in mf_holdings if h.get("ticker")})
        cache: dict[str, dict] = {}
        async for doc in db.fund_holdings_cache.find(
            {"isin": {"$in": isins}}, {"_id": 0, "isin": 1, "holdings": 1}
        ):
            if doc.get("isin"):
                cache[doc["isin"]] = doc
        weights: dict[str, dict] = {}
        for h in mf_holdings:
            isin = h.get("ticker")
            if isin and isin in cache:
                w = _build_fund_weights(cache[isin])
                weights[isin] = w
                unique_stocks.update(w.keys())
        isins_w = list(weights.keys())
        for i in range(len(isins_w)):
            for j in range(i + 1, len(isins_w)):
                ov = _overlap_pct(weights[isins_w[i]], weights[isins_w[j]])
                if ov > max_overlap:
                    max_overlap = ov
                if ov >= 65:
                    high_pairs += 1

    tone = "rust" if max_overlap >= 65 else ("saffron" if max_overlap >= 40 else "moss")
    badge_label = "High overlap" if tone == "rust" else (
        "Moderate overlap" if tone == "saffron" else "Well diversified"
    )

    return {
        "badge": {"label": badge_label, "tone": tone},
        "insight": {
            "headline": f"{int(max_overlap)}% overlap between your top 2 funds." if max_overlap else "Overlap data loading.",
            "subtext": f"{high_pairs} fund pairs overlap >65%." if high_pairs else "No high-overlap pairs detected.",
            "hero": {"label": "MAX OVERLAP", "value": f"{int(max_overlap)}%", "tone": tone},
        },
        "stat_tiles": [
            {"label": "Funds", "value": str(fund_count), "tone": "moss" if fund_count >= 4 else "saffron"},
            {"label": "High-overlap pairs", "value": str(high_pairs), "tone": tone},
            {"label": "Unique stocks", "value": str(len(unique_stocks)) if unique_stocks else "—"},
        ],
        "breakdown": {
            "lens": lens,
            "lens_options": ["overlap", "stocks", "category", "asset_mix"],
            "items": [],  # full matrix via /api/portfolio/exposure/fund-overlap/matrix
        },
    }


async def _risk_composite(user_id: str) -> dict[str, Any]:
    """Serves screen 07 Risk Dashboard."""
    # Pull risk data directly from Mongo + DAAS (mirrors portfolio_risk_analytics logic)
    holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "category": 1},
    ).to_list(1000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user
        holdings = await pi_holdings_for_user(user_id)

    if not holdings:
        return _empty_domain("risk")

    # Compute simple weighted beta from NIDP DAAS (re-uses existing service)
    from services.copilot_tools import daas_client as _daas
    mf_isins = [h["ticker"] for h in holdings
                if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"} and h.get("ticker")]
    total_value = sum(float(h.get("quantity", 0)) * float(h.get("current_price", 0)) for h in holdings)

    beta: Optional[float] = None
    vol: Optional[float] = None
    var_pct: Optional[float] = None
    risk_drivers: list[dict] = []

    if mf_isins:
        try:
            mf_data = await _daas.get_v3_mf_primitives_bulk(mf_isins[:30])
            weighted_beta = 0.0
            weighted_vol = 0.0
            w_sum = 0.0
            for h in holdings:
                isin = h.get("ticker")
                if not isin or isin not in mf_data:
                    continue
                val = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
                d = mf_data[isin]
                b = float(d.get("beta_1y") or d.get("beta") or 1.0)
                v = float(d.get("volatility_1y") or d.get("volatility") or 0.15)
                weighted_beta += b * val
                weighted_vol += v * val
                w_sum += val
                if b >= 1.2:
                    risk_drivers.append({
                        "fund_name": h.get("name") or isin,
                        "beta_1y": round(b, 2),
                        "volatility": round(v * 100, 1),
                    })
            if w_sum > 0:
                beta = round(weighted_beta / w_sum, 2)
                vol_annual = weighted_vol / w_sum
                vol = round(vol_annual, 4)
                var_pct = round(vol_annual * 1.645 * 100, 2)
        except Exception as exc:
            logger.debug("risk composite DAAS error: %s", exc)

    data = {
        "weighted_beta": beta, "weighted_volatility": vol,
        "var_1d_pct": var_pct, "max_drawdown_pct": None,
        "risk_drivers": risk_drivers,
    }
    beta = data.get("weighted_beta")
    vol = data.get("weighted_volatility")
    var_pct = data.get("var_1d_pct")
    tone = _beta_tone(beta)
    badge_label = "High risk" if tone == "rust" else ("Moderate" if tone == "saffron" else "Low risk")

    return {
        "badge": {"label": badge_label, "tone": tone},
        "insight": {
            "headline": f"Portfolio beta is {beta:.2f} — {'above' if (beta or 0) >= 1.3 else 'within'} the caution band." if beta else "Risk data loading.",
            "subtext": f"VaR (95%, 1d): {var_pct:.1f}% of portfolio." if var_pct else "",
            "hero": {"label": "BETA", "value": f"{beta:.2f}" if beta else "—", "tone": tone},
        },
        "stat_tiles": [
            {"label": "Beta", "value": f"{beta:.2f}" if beta is not None else "—", "tone": tone},
            {"label": "Volatility", "value": f"{round(vol * 100, 1)}%" if vol else "—"},
            {"label": "VaR 1d", "value": f"{var_pct:.1f}%" if var_pct else "—"},
            {"label": "Max DD", "value": f"{data.get('max_drawdown_pct', '—')}%" if data.get("max_drawdown_pct") is not None else "—"},
        ],
        "breakdown": {
            "lens": "beta",
            "lens_options": ["beta", "volatility", "drawdown"],
            "items": [
                {
                    "name": d.get("fund_name") or d.get("name") or "Unknown",
                    "value": round(float(d.get("beta_1y") or d.get("beta") or 0), 2),
                    "tone": _beta_tone(float(d.get("beta_1y") or d.get("beta") or 1)),
                }
                for d in (data.get("risk_drivers") or [])[:8]
            ],
        },
    }


async def _performance_composite(user_id: str, period: str, force: bool = False) -> dict[str, Any]:
    """Serves screen 08 Performance Dashboard — v5 full payload.

    Delegates to portfolio_performance_engine which computes:
      XIRR, benchmark_xirr, alpha, Sharpe, hit_rate,
      attribution waterfall, monthly returns strip, top contributors.
    Results are cached in portfolio_performance_cache (24h TTL).
    Pass force=True (or ?force=1 query param) to skip the cache.
    """
    from services.portfolio_performance_engine import compute_performance

    perf = await compute_performance(user_id, period, use_cache=not force)

    xirr = perf.get("portfolio_xirr")
    bm_xirr = perf.get("benchmark_xirr")
    alpha = perf.get("alpha")
    sharpe = perf.get("sharpe")
    hit_rate = perf.get("hit_rate")
    status_pill = perf.get("status_pill") or "CALCULATING"

    # Status pill → dashboard tone mapping
    _pill_tone = {"HEALTHY": "moss", "FAIR": "saffron", "POOR": "rust",
                  "CALCULATING": "mute", "EMPTY": "mute"}
    tone = _pill_tone.get(status_pill, "mute")

    # Sharpe ≥ 1.0 marker
    sharpe_marker = "above 1.0 ✓" if (sharpe is not None and sharpe >= 1.0) else None

    # Period-aware KPI label: bounded periods show "Return (1Y)" etc.;
    # inception (or fallback) shows "XIRR" (money-weighted since buy date).
    _RETURN_LABEL = {
        "1M": "Return (1M)", "3M": "Return (3M)",
        "6M": "Return (6M)", "1Y": "Return (1Y)",
    }.get(period, "XIRR")

    return {
        "badge": {
            "label": status_pill.title(),
            "tone": tone,
        },
        "insight": {
            "headline": perf.get("verdict_headline") or "Performance data loading.",
            "subtext": (
                f"{period} returns vs category peer average."
                if period != "inception"
                else "XIRR since inception vs category peer average."
            ),
            "hero": {
                "label": _RETURN_LABEL,
                "value": f"{xirr:+.1f}%" if xirr is not None else "—",
                "tone": tone,
            },
        },
        "stat_tiles": [
            {
                "label": _RETURN_LABEL,
                "value": f"{xirr:.1f}%" if xirr is not None else "—",
                **( {"sub": f"Nifty 500 {bm_xirr:+.1f}%"} if bm_xirr is not None else {} ),
                "tone": tone,
            },
            {
                "label": "Alpha",
                "value": f"{alpha:+.1f} pp" if alpha is not None else "—",
                "tone": "moss" if (alpha or 0) >= 0 else "rust",
            },
            {
                "label": "Sharpe",
                "value": f"{sharpe:.2f}" if sharpe is not None else "—",
                **( {"sub": sharpe_marker} if sharpe_marker is not None else {} ),
                "tone": "moss" if (sharpe or 0) >= 1.0 else "saffron",
            },
            {
                "label": "Hit Rate",
                "value": f"{round((hit_rate or 0) * 100):.0f}%" if hit_rate is not None else "—",
                "sub": "months beat benchmark",
                "tone": "moss" if (hit_rate or 0) >= 0.5 else "saffron",
            },
        ],
        "breakdown": {
            "waterfall": perf.get("waterfall") or [],
            "monthly_returns": perf.get("monthly_returns") or [],
            "top_contributors": perf.get("top_contributors") or [],
            "coverage": perf.get("coverage"),
            "status_pill": status_pill,
            "verdict_headline": perf.get("verdict_headline"),
            "computed_at": perf.get("computed_at"),
            "from_cache": perf.get("_from_cache", False),
        },
    }


async def _goals_composite(user_id: str) -> dict[str, Any]:
    """Serves screen 09 Goals Dashboard."""
    goals_doc = await db.goals.find_one({"user_id": user_id}) or {}
    goals = goals_doc.get("goals") or []
    at_risk = [g for g in goals if (g.get("funding_pct") or 100) < 80]
    tone = "rust" if at_risk else "moss"

    return {
        "badge": {"label": f"{len(at_risk)} goal{'s' if len(at_risk) != 1 else ''} at risk" if at_risk else "On track", "tone": tone},
        "insight": {
            "headline": f"{len(at_risk)} of {len(goals)} goals are at risk." if at_risk else "All goals on track.",
            "subtext": "Raise SIP or extend horizon to close the gap." if at_risk else "",
            "hero": {"label": "AT RISK", "value": str(len(at_risk)), "tone": tone},
        },
        "stat_tiles": [
            {"label": "Goals", "value": str(len(goals))},
            {"label": "At risk", "value": str(len(at_risk)), "tone": tone},
            {"label": "On track", "value": str(len(goals) - len(at_risk)), "tone": "moss"},
        ],
        "breakdown": {
            "lens": "goals",
            "lens_options": ["goals"],
            "items": [
                {
                    "name": g.get("name") or g.get("goal_name") or "Goal",
                    "value": round(float(g.get("funding_pct") or 0), 1),
                    "tone": _score_tone(float(g.get("funding_pct") or 0)),
                    "target_rs": g.get("target_amount_rs"),
                    "horizon_years": g.get("horizon_years"),
                }
                for g in goals[:6]
            ],
        },
    }


async def _tax_composite(user_id: str) -> dict[str, Any]:
    """Serves screen 10 Tax Dashboard."""
    from routes.portfolio_tax import get_tax_summary
    from fastapi import Request as _Req

    # Re-use the GET /api/portfolio/tax-summary logic directly
    cg_doc = await db.capital_gains_summary.find_one({"user_id": user_id}) or {}
    ltcg_remaining = max(0.0, 125_000.0 - float(cg_doc.get("ltcg_booked_rs") or 0))
    harvestable_raw = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        gain = float(h.get("unrealised_gain") or 0)
        days = int(h.get("days_held") or 0)
        if gain > 0 and days >= 365:
            harvestable_raw.append(gain)
    total_harvestable = sum(g for g in harvestable_raw if g <= ltcg_remaining)

    tone = "moss" if total_harvestable > 0 else "mute"
    from datetime import date
    fy_end_year = date.today().year if date.today().month < 4 else date.today().year + 1
    days_left = max(0, (date(fy_end_year, 3, 31) - date.today()).days)

    return {
        "badge": {"label": "Harvest available" if total_harvestable > 0 else "Nothing to harvest", "tone": tone},
        "insight": {
            "headline": f"₹{total_harvestable / 1000:.0f}K LTCG harvestable within ₹1.25L limit." if total_harvestable > 0 else "No LTCG harvest opportunities right now.",
            "subtext": f"{days_left} days until FY end.",
            "hero": {"label": "HARVESTABLE", "value": f"₹{total_harvestable / 1000:.0f}K" if total_harvestable else "—", "tone": tone},
        },
        "stat_tiles": [
            {"label": "LTCG remaining", "value": f"₹{ltcg_remaining / 1000:.0f}K", "tone": "moss" if ltcg_remaining > 0 else "rust"},
            {"label": "Days to FY end", "value": str(days_left)},
            {"label": "Harvest opp.", "value": str(len(harvestable_raw))},
        ],
        "breakdown": {
            "lens": "harvest",
            "lens_options": ["harvest", "structure"],
            "items": [],  # full list via /api/portfolio/tax-summary
        },
    }


def _empty_domain(domain: str) -> dict[str, Any]:
    return {
        "badge": {"label": "No data", "tone": "mute"},
        "insight": {"headline": "Upload your portfolio to see this dashboard.", "subtext": "", "hero": None},
        "stat_tiles": [],
        "breakdown": {"lens": domain, "lens_options": [], "items": []},
    }


# ── Main composite endpoint ───────────────────────────────────────────────────

@router.get("/{type}")
async def get_dashboard(
    type: str,
    request: Request,
    lens: str = Query("sector"),
    period: str = Query("1y"),
) -> dict[str, Any]:
    """Unified dashboard composite.

    Screens served (mobile + webapp):
      05 Concentration · 06 Diversification · 07 Risk
      08 Performance   · 09 Goals           · 10 Tax

    Query params:
      lens   — Concentration: sector|amc|company|group
               Diversification: overlap|stocks|category|asset_mix
      period — Performance: 1y|3y|5y (default 1y)
    """
    if type not in VALID_TYPES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown dashboard type '{type}'. Valid: {sorted(VALID_TYPES)}",
        )

    user = await get_current_user(request)
    user_id = user["user_id"]

    # ── 1. Domain data ────────────────────────────────────────────────────────
    try:
        if type == "concentration":
            domain = await _concentration_composite(user_id, lens)
        elif type == "diversification":
            domain = await _diversification_composite(user_id, lens)
        elif type == "risk":
            domain = await _risk_composite(user_id)
        elif type == "performance":
            force = request.query_params.get("force") == "1"
            domain = await _performance_composite(user_id, period, force=force)
        elif type == "goals":
            domain = await _goals_composite(user_id)
        else:  # tax
            domain = await _tax_composite(user_id)
    except Exception as exc:
        logger.warning("dashboard[%s] domain failed for user %s: %s", type, user_id, exc)
        domain = _empty_domain(type)

    # ── 2. Recommendations (plan actions filtered by source_domain) ───────────
    try:
        plan = await _plan_mgr.get_active_plan(user_id, source_domain=type)
        actions = (plan.get("actions") or [])[:5]
        # Normalise status to UPPERCASE for v4 consumers
        for a in actions:
            if isinstance(a.get("status"), str):
                a["status"] = a["status"].upper()
    except Exception as exc:
        logger.warning("dashboard[%s] plan failed for user %s: %s", type, user_id, exc)
        actions = []

    # ── 3. Health projection (cached / lightweight) ───────────────────────────
    try:
        projection = await _health_projection(user_id, type)
    except Exception as exc:
        logger.warning("dashboard[%s] projection failed for user %s: %s", type, user_id, exc)
        projection = {"metric_label": "Projected health", "current": None, "projected": None, "unit": "", "tone": "mute"}

    return {
        "type": type,
        **domain,
        "recommendations": actions,
        "projection": projection,
    }
