"""Risk analytics tools for the Nivesh Copilot.

TASK-039: Risk suitability — compare user risk profile vs portfolio beta/volatility/sector.
TASK-040: Portfolio VaR — parametric VaR using volatility_20d from DAAS stock features.

Functions:
  get_risk_suitability(user_id)               → RiskResult
  get_portfolio_var(user_id, confidence=0.95) → RiskResult
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Z-scores for parametric VaR ──────────────────────────────────────────────
_Z = {0.95: 1.645, 0.99: 2.326}

# ── Risk band → acceptable portfolio metrics ──────────────────────────────────
_PROFILE_BOUNDS: Dict[str, Dict[str, float]] = {
    "conservative": {"max_beta": 0.7,  "max_small_mid_pct": 20.0, "max_equity_pct": 50.0},
    "moderate":     {"max_beta": 1.1,  "max_small_mid_pct": 40.0, "max_equity_pct": 75.0},
    "aggressive":   {"max_beta": 1.5,  "max_small_mid_pct": 70.0, "max_equity_pct": 100.0},
}

# Annualised volatility → risk rating thresholds (daily vol × √252)
_VAR_RATING_THRESHOLDS = [
    (0.08, "LOW"),
    (0.15, "MEDIUM"),
    (0.22, "HIGH"),
]

# Name/category keywords that mark a fund as NON-equity. Used to classify
# MF/ETF holdings when an explicit equity_allocation_pct isn't available on the
# holding (the common case for CAS-imported holdings).
_NON_EQUITY_KEYWORDS = (
    "liquid", "money market", "overnight", "gilt", "g-sec", "bond", "debt",
    "duration", "credit risk", "arbitrage", "gold", "silver", "ultra short",
    "ultra-short", "short term", "short duration", "low duration",
    "corporate bond", "banking & psu", "banking and psu", "dynamic bond",
    "floating rate", "fixed maturity", "fmp", "income fund",
)


# Historical / hypothetical stress scenarios. Each entry encodes the
# asset-class shocks needed to project portfolio drawdown. Recovery years
# come from the post-event mean-reversion windows observed in Nifty 50.
_STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "gfc_2008": {
        "name": "2008 Global Financial Crisis",
        "description": "Nifty 50 fell ~60% peak-to-trough over 14 months; debt held up.",
        "equity_drop_pct": -60.0,
        "debt_drop_pct":   -5.0,
        "gold_drop_pct":    8.0,
        "recovery_years":  4.0,
    },
    "covid_2020": {
        "name": "COVID-19 Crash (Feb–Mar 2020)",
        "description": "Nifty 50 fell ~38% in 40 days. Recovery took ~14 months.",
        "equity_drop_pct": -38.0,
        "debt_drop_pct":   -2.0,
        "gold_drop_pct":    5.0,
        "recovery_years":  1.2,
    },
    "rate_shock": {
        "name": "Rate Shock (+200 bps)",
        "description": "Sudden 200 bps rate hike: long-duration debt loses 7–10%, equity ~12% on multiple compression.",
        "equity_drop_pct": -12.0,
        "debt_drop_pct":   -8.0,
        "gold_drop_pct":   -3.0,
        "recovery_years":  1.5,
    },
    "inflation_spike": {
        "name": "Inflation Spike (CPI > 7%)",
        "description": "Sticky CPI > 7% triggers earnings downgrades and real-rate compression on debt.",
        "equity_drop_pct": -18.0,
        "debt_drop_pct":   -6.0,
        "gold_drop_pct":   10.0,
        "recovery_years":  2.0,
    },
}


@dataclass
class RiskResult:
    ok: bool
    summary: str
    risk_rating: str = "UNKNOWN"
    risk_score_0_to_10: float = 0.0
    user_profile_category: str = "moderate"
    misalignment: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        parts = [f"risk_rating={self.risk_rating}", f"risk_score={self.risk_score_0_to_10:.1f}/10"]
        if self.misalignment:
            parts.append("misalignment: " + "; ".join(self.misalignment))
        if self.data:
            for k, v in self.data.items():
                if k not in ("rows",):
                    parts.append(f"{k}={v}")
        return self.summary + " | " + ", ".join(parts)


# ── Canonical precomputed risk (PRA) ─────────────────────────────────────────

async def get_portfolio_risk_pra(user_id: str) -> RiskResult:
    """Precomputed portfolio risk (VaR / volatility / beta / max-drawdown) from
    the PRA engine — the SAME source the Risk dashboard reads via
    ``daas_client.get_portfolio_risk``. The copilot must prefer this over
    recomputing parametric VaR from per-symbol volatility_20d (which times out
    and disagrees with the dashboard). ``ok=False`` when PRA has no result yet,
    so the caller can fall back to the parametric estimate.
    """
    from services.copilot_tools.daas_client import get_portfolio_risk as _pra
    pra: Optional[Dict[str, Any]] = None
    try:
        pra = await _pra(user_id, timeout=8.0)
    except Exception:  # noqa: BLE001 — live PRA often times out; fall back to cache
        pra = None
    # Fall back to pra_daily_cache (written by the Risk dashboard) so the copilot
    # shows the same VaR/vol/beta even when the live PRA endpoint is unavailable.
    if not (pra and pra.get("var_95_1y_pct") is not None):
        try:
            from deps import db
            doc = await db.pra_daily_cache.find_one({"user_id": user_id}, sort=[("date", -1)])
            if doc and (doc.get("payload") or {}).get("var_95_1y_pct") is not None:
                pra = doc["payload"]
        except Exception:  # noqa: BLE001
            pass
    if not pra or pra.get("var_95_1y_pct") is None:
        return RiskResult(ok=False, summary="No precomputed PRA risk result for this user yet")

    def _f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    var_pct = _f(pra.get("var_95_1y_pct"))      # PRA stores the loss magnitude (e.g. 33.1)
    var_inr = _f(pra.get("var_95_1y_inr"))
    vol     = _f(pra.get("volatility_annual_pct"))
    beta    = _f(pra.get("beta_nifty500"))
    mdd     = _f(pra.get("max_drawdown_pct"))
    data = {
        "var_95_1y_pct":         round(var_pct, 1) if var_pct is not None else None,
        "var_95_1y_inr":         round(var_inr) if var_inr is not None else None,
        "volatility_annual_pct": round(vol, 1) if vol is not None else None,
        "beta_nifty500":         round(beta, 2) if beta is not None else None,
        "max_drawdown_pct":      round(mdd, 1) if mdd is not None else None,
        "source":                "PRA (precomputed nightly)",
    }
    bits: List[str] = []
    if var_pct is not None:
        bits.append(f"VaR 95% 1Y −{abs(var_pct):.1f}%" + (f" (~₹{round(var_inr):,})" if var_inr else ""))
    if vol is not None:
        bits.append(f"volatility {vol:.1f}%")
    if beta is not None:
        bits.append(f"beta {beta:.2f} vs NIFTY 500")
    if mdd is not None:
        bits.append(f"max drawdown −{abs(mdd):.1f}%")
    summary = "Precomputed portfolio risk — " + ", ".join(bits) if bits else "Precomputed portfolio risk available"
    return RiskResult(ok=True, summary=summary, data=data)


# ── Risk-overview widget builder ──────────────────────────────────────────

_PROFILE_BAND = {
    "conservative": [0, 4], "moderate": [3, 6],
    "moderately_aggressive": [4, 7], "aggressive": [6, 10],
}


def build_risk_overview_widget(pra_tr: Any, suit_tr: Any) -> Dict[str, Any]:
    """Build the 'rebalance my risk' widget (gauge, stat tiles, worst-case VaR,
    risk drivers, suggested action) from the PRA and suitability tool results.
    """
    pd = (getattr(pra_tr, "data", None) or {})
    sd = (getattr(suit_tr, "data", None) or {})

    def _n(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    var_pct  = _n(pd.get("var_95_1y_pct"))
    var_inr  = _n(pd.get("var_95_1y_inr"))
    vol      = _n(pd.get("volatility_annual_pct"))
    beta     = _n(pd.get("beta_nifty500")) or _n(sd.get("portfolio_beta"))
    mdd      = _n(pd.get("max_drawdown_pct"))
    equity   = _n(sd.get("equity_pct"))
    smallmid = _n(sd.get("small_mid_pct"))
    score    = _n(sd.get("risk_score"))
    rating   = (sd.get("risk_rating") or "—")
    profile  = str(sd.get("user_profile") or "moderate")

    band = _PROFILE_BAND.get(profile.lower().replace(" ", "_").replace("-", "_"), [3, 6])
    profile_label = profile.replace("_", " ").title()
    sc = score if score is not None else 5.0
    over = sc > band[1]

    description = (
        "The needle sits just past the top of your stated band — not wildly off-profile, but at the "
        "high edge. The drivers below are why." if over else
        "The needle sits inside your stated tolerance band; the drivers below are the main contributors."
    )
    tiles = []
    if equity is not None: tiles.append({"label": "Equity exposure", "value": f"{round(equity)}%"})
    if beta is not None:   tiles.append({"label": "Beta vs NIFTY 500", "value": f"{beta:.2f}"})
    if vol is not None:    tiles.append({"label": "Volatility", "value": f"{vol:.1f}%"})
    if mdd is not None:    tiles.append({"label": "Max drawdown", "value": f"−{abs(mdd):.0f}%"})

    var_block = None
    if var_pct is not None:
        lakh = (var_inr or 0) / 1e5
        var_block = {
            "pct": -abs(var_pct),
            "inr": round(var_inr) if var_inr else None,
            "inr_label": f"₹{lakh:.1f} lakh" if var_inr else None,
            "subtitle": (
                f"In a severe year (1-in-20), losses of about ₹{round(var_inr):,} are within range. "
                f"1-day VaR isn't available from this data." if var_inr else
                "1-in-20 worst case over 12 months."
            ),
        }

    items = []
    if equity is not None:
        items.append({"label": "Equity concentration", "value_label": f"{round(equity)}%", "pct": equity,
                      "color": "red" if equity >= 85 else "amber",
                      "note": "Almost no debt cushion — full exposure to market drawdowns." if equity >= 85
                              else "Heavy equity tilt."})
    if beta is not None:
        items.append({"label": "Market sensitivity (beta)", "value_label": f"{beta:.2f}×",
                      "pct": min(100, beta / 2 * 100), "color": "amber",
                      "note": (f"Tends to fall ~{round((beta - 1) * 100)}% more than the broad market on down days."
                               if beta > 1 else "Roughly market-like.")})
    if smallmid is not None:
        items.append({"label": "Small / mid-cap exposure", "value_label": f"{round(smallmid)}%",
                      "pct": smallmid, "color": "amber",
                      "note": "Modest, but adds extra volatility on top of the large-cap core."
                              if smallmid < 30 else "Meaningful small/mid tilt — a real volatility driver."})

    action = {
        "title": "Suggested action",
        "text": (
            f"Nudge risk down toward the middle of your band: redirect future SIPs and rebalances toward "
            f"lower-risk categories (a debt sleeve, given {round(equity) if equity is not None else 0}% "
            f"equity today) rather than selling in one go." if over else
            "You're within band — keep contributions on plan and review the allocation periodically."
        ),
    }
    caveat = (
        "Risk metrics only — scheme-level overlap, expense ratios, manager tenure, AUM trend and "
        "category-gap analysis aren't available from this data. Not financial advice."
    )
    return {
        "gauge": {"rating": str(rating).upper(), "score": round(sc, 1), "max": 10,
                  "profile": profile_label, "band": band},
        "description": description, "tiles": tiles, "var": var_block,
        "drivers": {"title": "What's driving the risk", "items": items},
        "action": action, "caveat": caveat,
    }


def _inr_in(v: Any) -> str:
    """Indian-grouped rupee string, e.g. 108211 → '₹1,08,211'."""
    import re as _re
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return "—"
    s = str(abs(n))
    if len(s) > 3:
        last3, rest = s[-3:], s[:-3]
        rest = _re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", rest)
        s = f"{rest},{last3}"
    return ("-" if n < 0 else "") + "₹" + s


def build_risk_assessment_widget(pra_tr: Any, suit_tr: Any, stress_tr: Any,
                                 var_tr: Any = None) -> Dict[str, Any]:
    """Comprehensive risk view: an overall suitability rating, VaR / volatility /
    equity KPI tiles, the stress-test downside per scenario (₹ value-after +
    loss), the key risk drivers, and a profile-misalignment alert. Built from
    the PRA, suitability, stress and (fallback) parametric-VaR tool results —
    nothing invented."""
    pd = getattr(pra_tr, "data", None) or {}
    sd = getattr(suit_tr, "data", None) or {}
    std = getattr(stress_tr, "data", None) or {}
    vd = getattr(var_tr, "data", None) or {}

    def _n(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    vol = _n(pd.get("volatility_annual_pct")) or _n(vd.get("portfolio_annual_vol_pct"))
    equity = _n(sd.get("equity_pct"))
    smallmid = _n(sd.get("small_mid_pct"))
    rating = str(sd.get("risk_rating") or pd.get("risk_rating") or "—").upper()
    profile = str(sd.get("user_profile") or "moderate").replace("_", " ")
    misalignment = sd.get("misalignment") or []
    current_value = (_n(std.get("current_value_rs")) or _n(sd.get("total_portfolio_value"))
                     or _n(vd.get("total_portfolio_value_rs")) or _n(pd.get("portfolio_value_rs")))

    # ── VaR 1-day / 10-day (95%) ──────────────────────────────────────────────
    # Prefer the parametric VaR tool's directly-computed figures (used as the
    # fallback when the precomputed PRA result isn't available for this user);
    # otherwise derive from annual volatility: σ_daily = σ_annual/√252,
    # 95% VaR = 1.645·σ_daily·value, 10-day = ·√10.
    var_1d = _n(vd.get("var_1d_95_rs"))
    var_10d = _n(vd.get("var_10d_95_rs"))
    if not (var_1d and var_1d > 0):
        var_1d = var_10d = None
        if vol and current_value:
            daily_sigma = (vol / 100.0) / (252 ** 0.5)
            var_1d = 1.645 * daily_sigma * current_value
            var_10d = var_1d * (10 ** 0.5)
    # Model confidence: PRA-backed → medium; pure parametric estimate → medium
    # too (normal-assumption), only "high" model risk when we have no VaR at all.
    var_model_risk = "medium" if var_1d is not None else "high"

    # Overall rating tone
    _tone = {"VERY HIGH": "neg", "HIGH": "neg", "MEDIUM": "warm", "LOW": "accent"}.get(rating, "warm")
    hero = {
        "tone": _tone,
        "title": "Overall suitability risk",
        "rating": rating,
        "profile": profile,
        "var_model_risk": var_model_risk,
    }

    kpis = []
    if var_1d is not None:
        kpis.append({"label": "1-day 95% VaR", "value": _inr_in(var_1d)})
    if var_10d is not None:
        kpis.append({"label": "10-day 95% VaR", "value": _inr_in(var_10d)})
    if vol is not None:
        kpis.append({"label": "Annual volatility", "value": f"{vol:.1f}%"})
    if equity is not None:
        kpis.append({"label": "Equity allocation", "value": f"{round(equity)}%"})

    # ── Stress-test downside ──────────────────────────────────────────────────
    scenarios = std.get("scenarios") or []
    base = current_value or _n(std.get("current_value_rs"))
    rows = []
    any_recovery = False
    s_sorted = sorted(scenarios, key=lambda s: _n(s.get("drop_pct")) or 0)  # worst (most negative) first
    max_drop = max((abs(_n(s.get("drop_pct")) or 0) for s in scenarios), default=1) or 1
    for s in s_sorted:
        drop = _n(s.get("drop_pct"))
        after = _n(s.get("stressed_value_rs"))
        if drop is None or after is None:
            continue
        loss = (base - after) if base else None
        rec = s.get("recovery_years")
        if rec:
            any_recovery = True
        ad = abs(drop)
        color = "red" if ad >= 25 else "amber" if ad >= 15 else "blue"
        rows.append({
            "name": s.get("name") or s.get("key", "Scenario"),
            "drop_label": f"−{ad:.1f}%",
            "bar_pct": round(ad / max_drop * 100, 1),
            "color": color,
            "value_after": _inr_in(after),
            "loss": _inr_in(loss) if loss is not None else None,
            "recovery_years": rec,
        })
    stress = ({
        "title": "Stress-test downside",
        "subtitle": (f"Estimated portfolio value after each scenario (base ≈ {_inr_in(base)})."
                     + ("" if any_recovery else " Recovery horizons: data unavailable.")),
        "rows": rows,
    } if rows else None)

    # ── Key risk drivers ──────────────────────────────────────────────────────
    drivers = []
    if equity is not None and equity >= 60:
        drivers.append(f"High equity concentration at {round(equity)}%")
    if smallmid is not None and smallmid >= 10:
        drivers.append(f"Small/mid exposure at {round(smallmid)}% can amplify crash drawdowns")
    if rows:
        drivers.append(f"Stress sensitivity is highest in a {rows[0]['name'].split('(')[0].strip()}")

    # ── Misalignment alert ────────────────────────────────────────────────────
    alert = None
    if misalignment:
        body = (str(misalignment[0]) if isinstance(misalignment, (list, tuple)) else str(misalignment))
        alert = {
            "title": "Misalignment alert",
            "body": (f"Portfolio risk is above a {profile} profile. Suggested action: reduce equity "
                     f"and small/mid exposure, and rebalance toward lower-volatility debt, gold, "
                     f"international, or alternatives in a tax-aware manner."),
            "detail": body,
        }

    return {
        "hero": hero,
        "kpis": kpis,
        "stress": stress,
        "drivers": {"title": "Key risk drivers", "items": drivers} if drivers else None,
        "alert": alert,
        "caveat": ("Risk metrics and asset-class stress assumptions only — scheme-level analysis isn't "
                   "included here. VaR is a parametric estimate, not a guarantee. Not financial advice."),
    }


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _load_holdings(user_id: str) -> List[Dict[str, Any]]:
    from deps import db
    raw: List[Dict[str, Any]] = []
    async for h in db.holdings.find({"user_id": user_id}, {"_id": 0}):
        raw.append(h)
    if not raw:
        async for h in db.portfolio_holdings.find({"user_id": user_id}, {"_id": 0}):
            raw.append(h)
    return raw


async def _load_user_risk_profile(user_id: str) -> Dict[str, Any]:
    """Fetch user risk profile from DB. Returns default moderate profile if not found."""
    try:
        from deps import db
        profile = await db.user_profiles.find_one(
            {"user_id": user_id}, {"_id": 0, "risk_profile": 1}
        )
        if profile and profile.get("risk_profile"):
            return profile["risk_profile"]
    except Exception as exc:
        logger.debug("could not load risk profile for %s: %s", user_id, exc)
    return {"category": "moderate", "score": 50, "loss_tolerance_pct": 15.0, "horizon_years": 5}


# ── DAAS feature fetch (with concurrency limit) ───────────────────────────────

async def _fetch_volatilities(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Fetch volatility_20d for each symbol from DAAS. Returns symbol → vol or None."""
    from services.copilot_tools.daas_client import get_stock_features_latest, DaasError

    sem = asyncio.Semaphore(8)

    async def _one(sym: str) -> tuple[str, Optional[float]]:
        async with sem:
            try:
                feat = await get_stock_features_latest(sym)
                if feat and feat.get("volatility_20d") is not None:
                    return sym, float(feat["volatility_20d"])
            except DaasError:
                pass
        return sym, None

    results = await asyncio.gather(*[_one(s) for s in symbols])
    return dict(results)


# ── TASK-039: Risk Suitability ────────────────────────────────────────────────

async def get_risk_suitability(user_id: str) -> RiskResult:
    """Compare the user's stored risk profile against portfolio characteristics.

    Looks at:
    - Equity allocation % vs profile's max_equity_pct
    - Small/mid cap exposure vs profile's max_small_mid_pct
    - Weighted portfolio beta (using volatility_20d as beta proxy for MFs)
    Returns a risk rating (LOW/MEDIUM/HIGH/VERY HIGH) and misalignment list.
    """
    profile = await _load_user_risk_profile(user_id)
    category = profile.get("category", "moderate")
    bounds = _PROFILE_BOUNDS.get(category, _PROFILE_BOUNDS["moderate"])

    try:
        holdings = await _load_holdings(user_id)
    except Exception as exc:
        logger.warning("risk_suitability: holdings load failed for %s: %s", user_id, exc)
        return RiskResult(
            ok=False,
            summary="Could not load holdings",
            user_profile_category=category,
            data={
                "equity_pct": 0.0, "small_mid_pct": 0.0, "portfolio_beta": None,
                "total_portfolio_value": 0.0, "holdings_count": 0,
                "data_state": "load_error",
            },
            error=str(exc),
        )

    if not holdings:
        return RiskResult(
            ok=False,
            summary="No holdings found for risk assessment",
            user_profile_category=category,
            data={
                "equity_pct": 0.0, "small_mid_pct": 0.0, "portfolio_beta": None,
                "total_portfolio_value": 0.0, "holdings_count": 0,
                "data_state": "no_holdings",
            },
            error="no_holdings",
        )

    # ── Compute portfolio-level metrics from holdings ─────────────────────────
    total_value = 0.0
    equity_value = 0.0
    small_mid_value = 0.0
    sector_buckets: Dict[str, float] = {}
    holdings_with_price = 0
    holdings_skipped = 0

    rows: List[Dict[str, Any]] = []

    for h in holdings:
        try:
            price = float(h.get("current_price") or h.get("buy_price") or 0)
            qty = float(h.get("quantity") or 0)
            value = price * qty
        except (TypeError, ValueError):
            holdings_skipped += 1
            continue
        total_value += value
        if value > 0:
            holdings_with_price += 1

        asset_type = str(h.get("asset_type", "")).upper()
        sector = h.get("sector") or "Other"
        eq_pct = h.get("equity_allocation_pct")  # for MFs

        # Classify as equity.
        #   • direct stocks → always equity
        #   • MF/ETF → use equity_allocation_pct when present; otherwise (the
        #     common case — Mongo holdings don't carry it) treat the fund as
        #     equity UNLESS its name/category marks it non-equity (debt / liquid
        #     / gold / arbitrage). Without this, equity MFs were dropped and
        #     equity% read ~23% for a 93%-equity portfolio.
        name_cat = ((h.get("name") or "") + " " + str(h.get("category") or "")
                    + " " + str(sector or "")).lower()
        if asset_type in ("STOCK", "EQUITY"):
            is_equity = True
        elif asset_type in ("MF", "MUTUAL_FUND", "ETF"):
            # equity_allocation_pct is unreliable on CAS-imported holdings (often
            # 0), so classify by name/category/sector: equity unless the fund is
            # clearly debt/liquid/gold/arbitrage.
            is_equity = not any(kw in name_cat for kw in _NON_EQUITY_KEYWORDS)
        else:
            is_equity = False
        if is_equity:
            equity_value += value

        # Small/mid cap proxy via sector keyword
        name_lower = (h.get("name") or "").lower()
        if any(kw in name_lower for kw in ("small cap", "smallcap", "mid cap", "midcap",
                                            "small & mid", "small and mid")):
            small_mid_value += value

        # Sector concentration
        if asset_type in ("STOCK", "EQUITY"):
            bucket = sector_buckets.setdefault(sector, 0.0)
            sector_buckets[sector] = bucket + value

        rows.append({
            "name": h.get("name", ""),
            "asset_type": asset_type,
            "value": round(value, 2),
            "equity": is_equity,
        })

    # If all holdings had bad data, surface a meaningful partial response
    if total_value <= 0:
        logger.warning(
            "risk_suitability: %d holdings but total_value=0 (skipped=%d) for %s",
            len(holdings), holdings_skipped, user_id,
        )
        return RiskResult(
            ok=False,
            summary=f"Holdings have no price data ({len(holdings)} found, 0 priced)",
            user_profile_category=category,
            data={
                "equity_pct": 0.0, "small_mid_pct": 0.0, "portfolio_beta": None,
                "total_portfolio_value": 0.0, "holdings_count": len(holdings),
                "holdings_skipped": holdings_skipped,
                "data_state": "no_prices",
            },
            error="zero_value",
        )

    equity_pct = (equity_value / total_value * 100) if total_value > 0 else 0.0
    small_mid_pct = (small_mid_value / total_value * 100) if total_value > 0 else 0.0

    top_sector = max(sector_buckets, key=sector_buckets.get) if sector_buckets else None
    top_sector_pct = (
        sector_buckets[top_sector] / total_value * 100 if top_sector and total_value > 0 else 0.0
    )

    # ── Fetch DAAS volatility for stocks ─────────────────────────────────────
    stock_symbols = [
        h.get("symbol") or h.get("name", "")
        for h in holdings
        if str(h.get("asset_type", "")).upper() in ("STOCK", "EQUITY") and h.get("symbol")
    ]
    vol_map: Dict[str, Optional[float]] = {}
    vol_fetch_ok = True
    if stock_symbols:
        try:
            vol_map = await _fetch_volatilities(stock_symbols)
        except Exception as exc:
            vol_fetch_ok = False
            logger.warning("risk_suitability: DAAS vol fetch failed for %s: %s", user_id, exc)

    # Weighted average beta (daily vol × 252^0.5 / 0.16 as market proxy)
    weighted_beta_num = 0.0
    weighted_beta_den = 0.0
    for h in holdings:
        sym = h.get("symbol")
        if not sym:
            continue
        vol = vol_map.get(sym)
        if vol is None:
            continue
        price = float(h.get("current_price") or 0)
        qty = float(h.get("quantity") or 0)
        val = price * qty
        annual_vol = vol * math.sqrt(252)
        beta_proxy = annual_vol / 0.16  # market σ ≈ 16%
        weighted_beta_num += beta_proxy * val
        weighted_beta_den += val

    portfolio_beta = (weighted_beta_num / weighted_beta_den) if weighted_beta_den > 0 else None

    # ── Detect misalignments ──────────────────────────────────────────────────
    misalignment: List[str] = []

    if equity_pct > bounds["max_equity_pct"]:
        misalignment.append(
            f"Equity allocation {equity_pct:.0f}% exceeds {category} limit {bounds['max_equity_pct']:.0f}%"
        )
    if small_mid_pct > bounds["max_small_mid_pct"]:
        misalignment.append(
            f"Small/mid-cap exposure {small_mid_pct:.0f}% exceeds {category} limit {bounds['max_small_mid_pct']:.0f}%"
        )
    if portfolio_beta is not None and portfolio_beta > bounds["max_beta"]:
        misalignment.append(
            f"Portfolio beta {portfolio_beta:.2f} exceeds {category} limit {bounds['max_beta']:.1f}"
        )
    if top_sector_pct > 35.0:
        misalignment.append(
            f"Sector concentration in {top_sector}: {top_sector_pct:.0f}% of equity"
        )

    # ── Risk rating ───────────────────────────────────────────────────────────
    score = 5.0  # base
    score += min(3.0, equity_pct / 33.3)  # equity exposure → +0 to +3
    score -= min(2.0, len(misalignment) * 0.75)  # each misalignment → penalty

    if portfolio_beta is not None:
        if portfolio_beta > 1.3:
            score = min(10.0, score + 1.5)
        elif portfolio_beta < 0.7:
            score = max(0.0, score - 1.0)

    score = round(max(0.0, min(10.0, score)), 2)

    ann_vol_proxy = equity_pct / 100 * 0.18 + (1 - equity_pct / 100) * 0.04
    if ann_vol_proxy < 0.08:
        rating = "LOW"
    elif ann_vol_proxy < 0.15:
        rating = "MEDIUM"
    elif ann_vol_proxy < 0.22:
        rating = "HIGH"
    else:
        rating = "VERY HIGH"

    # Override upward when strongly misaligned
    if len(misalignment) >= 2 and rating in ("LOW", "MEDIUM"):
        rating = "HIGH"

    summary = (
        f"Risk rating: {rating} (score {score:.1f}/10). "
        f"Equity {equity_pct:.0f}%, Small/mid {small_mid_pct:.0f}%. "
        f"User profile: {category}. "
        + (f"{len(misalignment)} misalignment(s) detected." if misalignment else "Portfolio aligned with risk profile.")
    )

    # Surface partial-data state so the frontend can render "computing" rather
    # than blanks. "ok" stays True because allocation %/rating are still valid;
    # beta will simply be null when DAAS is down or no stocks held.
    if not stock_symbols:
        beta_state = "no_stocks"
    elif not vol_fetch_ok or all(v is None for v in vol_map.values()):
        beta_state = "vol_unavailable"
    elif any(v is None for v in vol_map.values()):
        beta_state = "partial"
    else:
        beta_state = "complete"

    return RiskResult(
        ok=True,
        summary=summary,
        risk_rating=rating,
        risk_score_0_to_10=score,
        user_profile_category=category,
        misalignment=misalignment,
        data={
            "equity_pct": round(equity_pct, 1),
            "small_mid_pct": round(small_mid_pct, 1),
            "portfolio_beta": round(portfolio_beta, 3) if portfolio_beta is not None else None,
            "top_sector": top_sector,
            "top_sector_pct": round(top_sector_pct, 1),
            "total_portfolio_value": round(total_value, 2),
            "holdings_count": len(holdings),
            "holdings_with_price": holdings_with_price,
            "user_profile_score": profile.get("score", 50),
            "loss_tolerance_pct": profile.get("loss_tolerance_pct", 15.0),
            "horizon_years": profile.get("horizon_years", 5),
            "misalignment_count": len(misalignment),
            "data_state": "complete" if beta_state == "complete" else beta_state,
        },
        rows=rows,
        error=None,
    )


# ── TASK-040: Portfolio VaR ───────────────────────────────────────────────────

async def get_portfolio_var(
    user_id: str,
    confidence: float = 0.95,
    holding_period_days: int = 1,
) -> RiskResult:
    """Compute parametric Value at Risk for the portfolio.

    Method: weighted portfolio daily volatility from stock_features_daily.volatility_20d.
    VaR = portfolio_value × portfolio_vol × z × √holding_period

    For MF holdings without a symbol, we use equity_allocation_pct to proxy
    equity risk at 18% annual vol and debt at 4% annual vol, converted to daily.

    Returns VaR at the requested confidence level plus 10-day VaR at both
    95% and 99% in the data dict.
    """
    _empty_var_data = {
        "var_1d_95_rs": 0.0, "var_1d_99_rs": 0.0,
        "var_10d_95_rs": 0.0, "var_10d_99_rs": 0.0,
        "portfolio_daily_vol": 0.0, "portfolio_annual_vol_pct": 0.0,
        "total_portfolio_value_rs": 0.0, "confidence_level": confidence,
        "positions_with_vol_data": 0,
    }

    try:
        holdings = await _load_holdings(user_id)
    except Exception as exc:
        logger.warning("portfolio_var: holdings load failed for %s: %s", user_id, exc)
        return RiskResult(
            ok=False, summary="Could not load holdings for VaR",
            data={**_empty_var_data, "data_state": "load_error"},
            error=str(exc),
        )

    if not holdings:
        return RiskResult(
            ok=False, summary="No holdings found for VaR",
            data={**_empty_var_data, "data_state": "no_holdings"},
            error="no_holdings",
        )

    # ── Fetch volatilities for stock/ETF holdings ─────────────────────────────
    stock_holdings = [
        h for h in holdings
        if str(h.get("asset_type", "")).upper() in ("STOCK", "ETF", "EQUITY") and h.get("symbol")
    ]
    symbols = [h["symbol"] for h in stock_holdings]
    vol_map: Dict[str, Optional[float]] = {}
    vol_fetch_ok = True
    if symbols:
        try:
            vol_map = await _fetch_volatilities(symbols)
        except Exception as exc:
            vol_fetch_ok = False
            logger.warning("VaR: could not fetch volatilities: %s", exc)

    # ── Build position-level vol × weight ─────────────────────────────────────
    total_value = 0.0
    position_rows: List[Dict[str, Any]] = []

    for h in holdings:
        try:
            price = float(h.get("current_price") or h.get("buy_price") or 0)
            qty = float(h.get("quantity") or 0)
            value = price * qty
        except (TypeError, ValueError):
            continue
        total_value += value

        asset_type = str(h.get("asset_type", "")).upper()
        sym = h.get("symbol")

        if asset_type in ("STOCK", "ETF", "EQUITY") and sym and sym in vol_map and vol_map[sym] is not None:
            daily_vol = float(vol_map[sym])
        elif asset_type in ("MF", "MUTUAL_FUND"):
            try:
                eq_pct = float(h.get("equity_allocation_pct") or 0.0) / 100.0
            except (TypeError, ValueError):
                eq_pct = 0.65  # generic equity-MF default
            # Blend: equity daily vol ≈ 18%/√252, debt daily vol ≈ 4%/√252
            daily_vol = eq_pct * (0.18 / math.sqrt(252)) + (1 - eq_pct) * (0.04 / math.sqrt(252))
        elif asset_type in ("BOND", "DEBT"):
            daily_vol = 0.04 / math.sqrt(252)
        elif asset_type == "GOLD":
            daily_vol = 0.10 / math.sqrt(252)
        elif asset_type in ("STOCK", "ETF", "EQUITY"):
            # Stock with no DAAS volatility data — fall back to broad-market proxy
            daily_vol = 0.18 / math.sqrt(252)
        else:
            # Unknown asset class — moderate equity assumption (preserves prior behaviour)
            daily_vol = 0.15 / math.sqrt(252)

        position_rows.append({
            "name": h.get("name", sym or ""),
            "asset_type": asset_type,
            "value": round(value, 2),
            "daily_vol": round(daily_vol, 6),
        })

    if total_value == 0:
        logger.warning(
            "portfolio_var: %d holdings but total_value=0 for %s",
            len(holdings), user_id,
        )
        return RiskResult(
            ok=False,
            summary=f"Holdings have no price data ({len(holdings)} found, 0 priced)",
            data={**_empty_var_data, "data_state": "no_prices",
                  "holdings_count": len(holdings)},
            error="zero_value",
        )

    # ── Weighted portfolio vol (assume uncorrelated positions as conservative approx) ──
    # σ_p = sqrt( Σ (w_i × σ_i)^2 )  with correlation = 0 → lower bound
    # For a more realistic estimate we use simple weighted sum (correlation = 1)
    # which gives an upper bound and is more prudent for risk management.
    weighted_vol_sum = sum(
        (row["value"] / total_value) * row["daily_vol"]
        for row in position_rows
    )

    z = _Z.get(confidence, 1.645)
    var_1d = total_value * weighted_vol_sum * z
    var_10d = var_1d * math.sqrt(10)
    var_1d_99 = total_value * weighted_vol_sum * _Z[0.99]
    var_10d_99 = var_1d_99 * math.sqrt(10)

    annual_vol = weighted_vol_sum * math.sqrt(252)
    if annual_vol < 0.08:
        rating = "LOW"
    elif annual_vol < 0.15:
        rating = "MEDIUM"
    elif annual_vol < 0.22:
        rating = "HIGH"
    else:
        rating = "VERY HIGH"

    conf_pct = int(confidence * 100)
    summary = (
        f"1-day {conf_pct}% VaR: ₹{var_1d:,.0f} | 10-day {conf_pct}% VaR: ₹{var_10d:,.0f}. "
        f"Portfolio vol (annual): {annual_vol*100:.1f}%. Risk rating: {rating}."
    )

    # Track whether DAAS supplied vol for every stock or we leaned on proxies.
    stocks_total = sum(
        1 for r in position_rows if r["asset_type"] in ("STOCK", "ETF", "EQUITY")
    )
    stocks_with_real_vol = sum(
        1 for h in stock_holdings
        if h.get("symbol") and vol_map.get(h["symbol"]) is not None
    )
    if stocks_total == 0:
        var_state = "complete"  # MF-only portfolio uses proxies by design
    elif not vol_fetch_ok or stocks_with_real_vol == 0:
        var_state = "vol_unavailable"
    elif stocks_with_real_vol < stocks_total:
        var_state = "partial"
    else:
        var_state = "complete"

    return RiskResult(
        ok=True,
        summary=summary,
        risk_rating=rating,
        risk_score_0_to_10=round(min(10.0, annual_vol / 0.03), 2),  # 30% vol → 10
        data={
            "var_1d_95_rs": round(var_1d if confidence == 0.95 else total_value * weighted_vol_sum * _Z[0.95], 2),
            "var_1d_99_rs": round(var_1d_99, 2),
            "var_10d_95_rs": round(var_10d if confidence == 0.95 else var_1d * math.sqrt(10), 2),
            "var_10d_99_rs": round(var_10d_99, 2),
            "portfolio_daily_vol": round(weighted_vol_sum, 6),
            "portfolio_annual_vol_pct": round(annual_vol * 100, 2),
            "total_portfolio_value_rs": round(total_value, 2),
            "confidence_level": confidence,
            "positions_with_vol_data": sum(1 for r in position_rows if r["daily_vol"] > 0),
            "stocks_with_real_vol": stocks_with_real_vol,
            "stocks_total": stocks_total,
            "data_state": var_state,
        },
        rows=position_rows,
        error=None,
    )


# ── TASK-040b: Stress test scenarios ──────────────────────────────────────────

def _asset_bucket(asset_type: str, eq_pct: Optional[float]) -> str:
    """Map a holding's asset_type (and equity allocation for MFs) to a bucket
    used by the stress scenario shocks."""
    at = (asset_type or "").upper()
    if at in ("STOCK", "ETF", "EQUITY"):
        return "equity"
    if at in ("BOND", "DEBT"):
        return "debt"
    if at == "GOLD":
        return "gold"
    if at in ("MF", "MUTUAL_FUND"):
        # If equity_allocation_pct is known, treat the MF as a blend.
        return "mf_blend"
    return "equity"  # conservative default


async def get_stress_scenarios(
    user_id: str,
    scenario_keys: Optional[List[str]] = None,
) -> RiskResult:
    """Project portfolio value under one or more historical/hypothetical shocks.

    Each scenario applies asset-class drop assumptions (equity / debt / gold /
    MF-blend by equity_allocation_pct) to every holding and computes a stressed
    value, drop %, and worst-case recovery time.

    Returns a RiskResult whose `data` matches the StressTestWidget envelope
    (current_value_rs, stressed_value_rs, drop_pct, breakdown, scenarios).
    """
    keys = [k for k in (scenario_keys or list(_STRESS_SCENARIOS.keys())) if k in _STRESS_SCENARIOS]
    if not keys:
        keys = ["gfc_2008", "rate_shock", "inflation_spike"]

    try:
        holdings = await _load_holdings(user_id)
    except Exception as exc:
        logger.warning("stress_scenarios: holdings load failed for %s: %s", user_id, exc)
        return RiskResult(
            ok=False, summary="Could not load holdings for stress test",
            data={"data_state": "load_error", "current_value_rs": 0.0,
                  "stressed_value_rs": 0.0, "drop_pct": 0.0, "scenarios": []},
            error=str(exc),
        )

    if not holdings:
        return RiskResult(
            ok=False, summary="No holdings found to stress-test",
            data={"data_state": "no_holdings", "current_value_rs": 0.0,
                  "stressed_value_rs": 0.0, "drop_pct": 0.0, "scenarios": []},
            error="no_holdings",
        )

    # Normalise per-holding value + bucket once
    items: List[Dict[str, Any]] = []
    total_value = 0.0
    for h in holdings:
        try:
            price = float(h.get("current_price") or h.get("buy_price") or 0)
            qty   = float(h.get("quantity") or 0)
            value = float(h.get("current_value") or price * qty)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        try:
            eq_pct_raw = h.get("equity_allocation_pct")
            eq_pct = float(eq_pct_raw) / 100.0 if eq_pct_raw is not None else None
        except (TypeError, ValueError):
            eq_pct = None
        items.append({
            "name": h.get("fund_name") or h.get("scheme_name") or h.get("name") or h.get("symbol") or "Holding",
            "asset_type": (h.get("asset_type") or "").upper(),
            "value": value,
            "bucket": _asset_bucket(h.get("asset_type") or "", eq_pct),
            "eq_pct": eq_pct if eq_pct is not None else 0.65,  # generic MF default
        })
        total_value += value

    if total_value <= 0:
        return RiskResult(
            ok=False, summary="Holdings have no priced value to stress-test",
            data={"data_state": "no_prices", "current_value_rs": 0.0,
                  "stressed_value_rs": 0.0, "drop_pct": 0.0, "scenarios": []},
            error="zero_value",
        )

    def _stressed_value(item: Dict[str, Any], scen: Dict[str, Any]) -> tuple[float, float]:
        eq = scen["equity_drop_pct"] / 100.0
        de = scen["debt_drop_pct"] / 100.0
        gd = scen["gold_drop_pct"] / 100.0
        if item["bucket"] == "equity":
            shock = eq
        elif item["bucket"] == "debt":
            shock = de
        elif item["bucket"] == "gold":
            shock = gd
        else:  # mf_blend
            shock = item["eq_pct"] * eq + (1 - item["eq_pct"]) * de
        return item["value"] * (1 + shock), shock * 100.0  # stressed_value, drop_pct

    scenarios_out: List[Dict[str, Any]] = []
    worst: Optional[Dict[str, Any]] = None
    worst_breakdown: List[Dict[str, Any]] = []

    for k in keys:
        scen = _STRESS_SCENARIOS[k]
        stressed_total = 0.0
        breakdown: List[Dict[str, Any]] = []
        for it in items:
            sv, dp = _stressed_value(it, scen)
            stressed_total += sv
            breakdown.append({
                "fund_name": it["name"],
                "current_value_rs": round(it["value"], 2),
                "stressed_value_rs": round(sv, 2),
                "drop_pct": round(dp, 2),
            })
        drop_pct = ((stressed_total - total_value) / total_value) * 100.0
        scen_entry = {
            "key": k,
            "name": scen["name"],
            "description": scen["description"],
            "stressed_value_rs": round(stressed_total, 2),
            "drop_pct": round(drop_pct, 2),
            "recovery_years": scen["recovery_years"],
        }
        scenarios_out.append(scen_entry)
        if worst is None or stressed_total < worst["stressed_value_rs"]:
            worst = scen_entry
            worst_breakdown = sorted(breakdown, key=lambda b: b["drop_pct"])[:10]

    summary = "; ".join(
        f"{s['name']}: {s['drop_pct']:+.1f}% → ₹{s['stressed_value_rs']:,.0f}"
        for s in scenarios_out
    )

    data = {
        # StressTestWidget header fields (use the worst scenario)
        "scenario_name":        worst["name"],
        "scenario_description": worst["description"],
        "current_value_rs":     round(total_value, 2),
        "stressed_value_rs":    worst["stressed_value_rs"],
        "drop_pct":             worst["drop_pct"],
        "recovery_years":       worst["recovery_years"],
        "breakdown":            worst_breakdown,
        # Full multi-scenario list for the LLM / text rendering
        "scenarios":            scenarios_out,
        "data_state":           "complete",
    }
    return RiskResult(
        ok=True,
        summary=summary,
        data=data,
        rows=worst_breakdown,
        error=None,
    )
