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
from services import pg_client
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
    """Serves screen 07 Risk Dashboard.

    Reads from pra.portfolio_risk_results (precomputed nightly by pra_engine)
    via the NIDP DaaS /v1/portfolio-risk/{user_id} endpoint.
    Falls back to the legacy weighted-beta approach if no PRA result exists yet.
    """
    from datetime import date
    from services.copilot_tools import daas_client as _daas

    # ── Primary path: precomputed PRA results ──────────────────────────
    pra: Optional[dict] = None
    pra_error: Optional[str] = None
    try:
        pra = await _daas.get_portfolio_risk(user_id)
    except Exception as exc:
        pra_error = str(exc)
        logger.warning("risk composite: PRA DaaS unavailable for user %s: %s — falling back to legacy", user_id, exc)

    if pra and pra.get("var_95_1y_pct"):
        var_pct   = float(pra["var_95_1y_pct"])
        var_inr   = float(pra.get("var_95_1y_inr") or 0)
        vol_pct   = float(pra.get("volatility_annual_pct") or 0)
        bench_vol = float(pra.get("benchmark_vol_annual_pct") or 0)
        mdd       = float(pra.get("max_drawdown_pct") or 0)
        beta      = float(pra.get("beta_nifty500") or 0)
        sharpe    = float(pra.get("sharpe_1y") or 0)
        stale     = bool(pra.get("data_stale"))
        color     = pra.get("risk_color", "amber")
        drivers   = pra.get("risk_drivers") or []
        stress    = pra.get("stress_scenarios") or []
        computed_at   = pra.get("computed_at", "")
        computed_date = pra.get("computed_date", "")
        pra_run_today = computed_date == str(date.today())

        tone = {"green": "moss", "amber": "saffron", "red": "rust"}.get(color, "saffron")
        badge_label = "High risk" if color == "red" else ("Moderate risk" if color == "amber" else "Low risk")

        return {
            "badge": {"label": badge_label, "tone": tone},
            "insight": {
                "headline": f"One bad year could cost ₹{_fmt_inr(var_inr)}.",
                "subtext": (
                    f"That's the 95th-percentile worst case over 12 months — "
                    f"a 1-in-20 scenario. Likely milder."
                ),
                "hero": {"label": "VaR 95% · 1Y", "value": f"−{var_pct:.1f}%", "tone": tone},
            },
            "stat_tiles": [
                {"label": "VaR · 95th · 1Y",  "value": f"−{var_pct:.1f}%",  "sub": f"~₹{_fmt_inr(var_inr)}", "tone": tone},
                {"label": "Volatility",         "value": f"{vol_pct:.1f}%",  "sub": f"Bench {bench_vol:.1f}%"},
                {"label": "Max Drawdown",        "value": f"{mdd:.1f}%",     "sub": "historical worst", "tone": "moss" if mdd < 15 else ("saffron" if mdd < 35 else "rust")},
                {"label": "Beta",                "value": f"{beta:.2f}",     "sub": "vs NIFTY 500"},
            ],
            "breakdown": {
                "lens": "component_var",
                "lens_options": ["component_var"],
                "items": [
                    {
                        "name":  d.get("security_name") or d.get("security_key", "Unknown"),
                        "cls":   d.get("asset_class", ""),
                        "value": round(float(d.get("share_of_sigma_pct") or 0), 1),
                        "weight": round(float(d.get("effective_weight_pct") or 0), 1),
                    }
                    for d in drivers[:10]
                ],
            },
            "stress_scenarios": [
                {
                    "name":           s.get("scenario_name"),
                    "portfolio_pct":  s.get("portfolio_impact_pct"),
                    "benchmark_pct":  s.get("benchmark_impact_pct"),
                    "recovery":       s.get("recovery_estimate"),
                }
                for s in stress
            ],
            "meta": {
                "pra_available":    True,
                "pra_run_today":    pra_run_today,
                "pra_computed_date": computed_date,
                "pra_error":        None,
                "computed_at":      computed_at,
                "data_stale":       stale,
                "sharpe_1y":        sharpe,
            },
        }

    # ── Fallback: legacy weighted-beta approach (no PRA results yet) ───
    # Determine why PRA isn't available so we can surface it in the UI.
    if pra_error:
        _pra_meta_error = f"Risk analytics service unavailable: {pra_error}"
    elif pra is None:
        _pra_meta_error = "PRA engine has not run for this user yet. Trigger a run from the admin panel."
    else:
        _pra_meta_error = "PRA results exist but are incomplete (VaR not yet computed)."
    _pra_computed_date = pra.get("computed_date") if pra else None

    holdings: list[dict] = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1,
         "quantity": 1, "current_price": 1, "category": 1},
    ).to_list(1000)
    if not holdings:
        from services.pi_bridge import pi_holdings_for_user
        holdings = await pi_holdings_for_user(user_id)

    if not holdings:
        result = _empty_domain("risk")
        result["meta"] = {
            "pra_available":     False,
            "pra_run_today":     False,
            "pra_computed_date": _pra_computed_date,
            "pra_error":         _pra_meta_error,
        }
        return result

    mf_isins = [h["ticker"] for h in holdings
                if (h.get("asset_type") or "").lower() in {"mutual_fund", "etf"} and h.get("ticker")]

    beta_fb: Optional[float] = None
    vol_fb:  Optional[float] = None
    var_fb:  Optional[float] = None
    risk_drivers_fb: list[dict] = []

    if mf_isins:
        try:
            mf_data = await _daas.get_v3_mf_primitives_bulk(mf_isins[:30])
            wb2 = wv2 = ws2 = 0.0
            for h in holdings:
                isin = h.get("ticker")
                if not isin or isin not in mf_data:
                    continue
                val = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
                d = mf_data[isin]
                b = float(d.get("beta_1y") or 1.0)
                v = float(d.get("volatility_1y") or 0.15)
                wb2 += b * val; wv2 += v * val; ws2 += val
                if b >= 1.2:
                    risk_drivers_fb.append({"fund_name": h.get("name") or isin,
                                            "beta_1y": round(b, 2),
                                            "volatility": round(v * 100, 1)})
            if ws2 > 0:
                beta_fb = round(wb2 / ws2, 2)
                vol_ann  = wv2 / ws2
                vol_fb   = round(vol_ann, 4)
                var_fb   = round(vol_ann * 1.645 * 100, 2)
        except Exception as exc:
            logger.debug("risk composite legacy DAAS error: %s", exc)

    tone = _beta_tone(beta_fb)
    badge_label = "High risk" if tone == "rust" else ("Moderate" if tone == "saffron" else "Low risk")
    return {
        "badge": {"label": badge_label, "tone": tone},
        "insight": {
            "headline": f"Portfolio beta is {beta_fb:.2f}." if beta_fb else "Risk data loading.",
            "subtext": f"VaR (95%, 1d): {var_fb:.1f}%" if var_fb else "",
            "hero": {"label": "BETA", "value": f"{beta_fb:.2f}" if beta_fb else "—", "tone": tone},
        },
        "stat_tiles": [
            {"label": "Beta",      "value": f"{beta_fb:.2f}" if beta_fb is not None else "—", "tone": tone},
            {"label": "Volatility","value": f"{round(vol_fb * 100, 1)}%" if vol_fb else "—"},
            {"label": "VaR 1d",   "value": f"{var_fb:.1f}%" if var_fb else "—"},
            {"label": "Max DD",    "value": "—"},
        ],
        "breakdown": {
            "lens": "beta",
            "lens_options": ["beta"],
            "items": [
                {"name": d.get("fund_name", "Unknown"),
                 "value": d.get("beta_1y", 0),
                 "tone": _beta_tone(d.get("beta_1y", 1))}
                for d in risk_drivers_fb[:8]
            ],
        },
        "stress_scenarios": [],
        "meta": {
            "pra_available":     False,
            "pra_run_today":     False,
            "pra_computed_date": _pra_computed_date,
            "pra_error":         _pra_meta_error,
            "data_stale":        False,
        },
    }


def _fmt_inr(value: float) -> str:
    """Format INR value as ₹XX.XL / ₹XX.XCr for display."""
    if value >= 1_00_00_000:
        return f"{value / 1_00_00_000:.1f}Cr"
    if value >= 1_00_000:
        return f"{value / 1_00_000:.1f}L"
    return f"{int(value):,}"


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


def _goal_fan_projection(goals: list[dict], base_year: int) -> dict:
    """Build a year-by-year fan trajectory from goal rows (values in rupees)."""
    if not goals:
        return {}
    total_sip = sum(float(g.get("monthly_sip_rs") or 0) for g in goals)
    total_corpus = sum(float(g.get("current_corpus_rs") or 0) for g in goals)
    total_target = sum(float(g.get("target_amount_rs") or 0) for g in goals)
    max_horizon = max(max(int(float(g.get("horizon_years") or 1)), 1) for g in goals)

    def fv(corpus: float, sip: float, annual_rate: float, years: int) -> float:
        n = years * 12
        if annual_rate == 0:
            return corpus + sip * n
        r = annual_rate / 12
        return corpus * (1 + r) ** n + sip * ((1 + r) ** n - 1) / r

    years = list(range(base_year, base_year + max_horizon + 1))
    median    = [round(fv(total_corpus, total_sip, 0.12, yr - base_year)) for yr in years]
    lo_68     = [round(fv(total_corpus, total_sip, 0.09, yr - base_year)) for yr in years]
    hi_68     = [round(fv(total_corpus, total_sip, 0.15, yr - base_year)) for yr in years]
    lo_95     = [round(fv(total_corpus, total_sip, 0.06, yr - base_year)) for yr in years]
    hi_95     = [round(fv(total_corpus, total_sip, 0.18, yr - base_year)) for yr in years]
    required  = [
        round(total_corpus + (total_target - total_corpus) * (yr - base_year) / max_horizon)
        for yr in years
    ]
    markers = [
        {
            "year": base_year + max(int(float(g.get("horizon_years") or 1)), 1),
            "label": (g.get("goal_name") or "Goal")[:10],
            "amount": round(float(g.get("target_amount_rs") or 0)),
            "on_track": float(g.get("on_track_pct") or 0) >= 70,
        }
        for g in goals
    ]
    return {
        "years": years, "median": median,
        "band_68_lo": lo_68, "band_68_hi": hi_68,
        "band_95_lo": lo_95, "band_95_hi": hi_95,
        "required": required, "goals": markers,
    }


async def _goals_composite(user_id: str) -> dict[str, Any]:
    """Serves screen 09 Goals Dashboard."""
    import uuid as _uuid
    from datetime import date as _date

    # user_id from auth is a Mongo-style string (e.g. 'user_abc123');
    # user_goals.user_id is UUID — same deterministic mapping as routes/goals.py _user_uuid().
    try:
        pg_user_id = _uuid.UUID(user_id)
    except (ValueError, AttributeError):
        pg_user_id = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")

    pool = await pg_client.get_pool()
    goals = []
    if pool:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT goal_name, goal_type, target_amount_rs, horizon_years, "
                "on_track_pct, monthly_sip_rs, current_corpus_rs FROM user_goals "
                "WHERE user_id = $1 AND status != 'abandoned' ORDER BY created_at",
                pg_user_id,
            )
            goals = [dict(r) for r in rows]

    total = len(goals)
    at_risk_count = sum(1 for g in goals if (g.get("on_track_pct") or 100) < 80)
    on_track_count = total - at_risk_count
    tone = "rust" if at_risk_count else "moss"

    return {
        "badge": {
            "label": f"{at_risk_count} goal{'s' if at_risk_count != 1 else ''} at risk" if at_risk_count else "On track",
            "tone": tone,
        },
        "insight": {
            "headline": f"{at_risk_count} of {total} goals are at risk." if at_risk_count else "All goals on track.",
            "subtext": "Raise SIP or extend horizon to close the gap." if at_risk_count else "",
            "hero": {"label": "AT RISK", "value": str(at_risk_count), "tone": tone},
        },
        "stat_tiles": [
            {"label": "Goals", "value": str(total)},
            {"label": "At risk", "value": str(at_risk_count), "tone": tone},
            {"label": "On track", "value": str(on_track_count), "tone": "moss"},
        ],
        "breakdown": {
            "lens": "goals",
            "lens_options": ["goals"],
            "items": [
                {
                    "name": g.get("goal_name") or "Goal",
                    "value": round(float(g.get("on_track_pct") or 0), 1),
                    "tone": _score_tone(float(g.get("on_track_pct") or 0)),
                    "target_rs": g.get("target_amount_rs"),
                    "horizon_years": g.get("horizon_years"),
                }
                for g in goals[:6]
            ],
        },
        # Fan trajectory — consumed by GoalTrajectory SVG chart in V5
        "projection": _goal_fan_projection(goals, _date.today().year) or None,
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

    # ── 3. Projection — domain provides its own (e.g. goals fan chart); others use health delta ──
    domain_projection = domain.pop("projection", None)
    if domain_projection is not None:
        projection = domain_projection
    else:
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
