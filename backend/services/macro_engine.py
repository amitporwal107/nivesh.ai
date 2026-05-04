"""Macro Intelligence engine — features, regime, sector tilt.

Pure compute layer that sits on top of `macro_daily`. Three jobs:

  1. compute_features(date)    → rows in macro_features (PRD §7)
  2. classify_regime(date)     → row in macro_state    (PRD §8)
  3. compute_sector_scores()   → rows in sector_macro_scores (PR-2 — stub here)

All three are idempotent. Re-running for the same date overwrites with
the latest derivations. The reason we don't fold this into the ingester:
the engine should be runnable against historical macro_daily rows for
backtesting, without touching the network.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from services import pg_client

logger = logging.getLogger(__name__)


# ── Feature math primitives ────────────────────────────────────────────
def _sma(values: List[float], window: int) -> Optional[float]:
    """Simple moving average over the last `window` elements. None if
    not enough non-null values."""
    clean = [v for v in values[-window:] if v is not None]
    if len(clean) < max(2, int(window * 0.6)):  # tolerate up to 40% gaps
        return None
    return sum(clean) / len(clean)


def _pct_change(values: List[float], lookback: int) -> Optional[float]:
    """% change between values[-1] and values[-1-lookback]."""
    if len(values) < lookback + 1:
        return None
    cur, prev = values[-1], values[-1 - lookback]
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / prev * 100.0


def _rolling_max(values: List[float], window: int) -> Optional[float]:
    """Max of the last `window` values (excluding the very last — we want
    'is today above the prior 20-day high?')."""
    if len(values) < window + 1:
        return None
    window_slice = [v for v in values[-window - 1:-1] if v is not None]
    if not window_slice:
        return None
    return max(window_slice)


# ── Load history ──────────────────────────────────────────────────────
async def _load_series(end_date: date, lookback_days: int = 80) -> Dict[str, List[Optional[float]]]:
    """Pull the last N daily prints for each metric, ordered ascending."""
    pool = await pg_client.get_pool()
    empty = {k: [] for k in (
        "crude", "usd", "bond", "nifty",
        "india_vix", "us_vix", "dxy", "sp500", "nasdaq", "nikkei", "hang_seng",
    )}
    if pool is None:
        return empty
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, crude_price, usd_inr, bond_10y, nifty,
                   india_vix, us_vix, dxy, sp500, nasdaq, nikkei, hang_seng
            FROM macro_daily
            WHERE date <= $1
            ORDER BY date DESC
            LIMIT $2
            """,
            end_date, lookback_days,
        )
    rows = list(reversed(rows))   # ascending
    def _col(name: str) -> List[Optional[float]]:
        return [float(r[name]) if r[name] is not None else None for r in rows]
    return {
        "crude":     _col("crude_price"),
        "usd":       _col("usd_inr"),
        "bond":      _col("bond_10y"),
        "nifty":     _col("nifty"),
        "india_vix": _col("india_vix"),
        "us_vix":    _col("us_vix"),
        "dxy":       _col("dxy"),
        "sp500":     _col("sp500"),
        "nasdaq":    _col("nasdaq"),
        "nikkei":    _col("nikkei"),
        "hang_seng": _col("hang_seng"),
    }


def _zscore(values: List[Optional[float]], window: int = 60) -> Optional[float]:
    """Z-score of the latest value vs the trailing window. Used to detect
    VIX spikes — much more reliable than absolute thresholds since VIX
    baselines drift over time."""
    clean = [v for v in values[-window:] if v is not None]
    if len(clean) < 10:
        return None
    cur = clean[-1]
    mean = sum(clean) / len(clean)
    var = sum((v - mean) ** 2 for v in clean) / len(clean)
    sd = var ** 0.5
    if sd <= 0:
        return 0.0
    return round((cur - mean) / sd, 3)


def _overnight_change_pct(values: List[Optional[float]]) -> Optional[float]:
    """% change between today's close and yesterday's close. For US indices
    this is the "overnight" move that India's open will react to."""
    return _pct_change(values, 1)


# ── Step 1: compute_features ──────────────────────────────────────────
async def compute_features(target_date: Optional[date] = None) -> Dict[str, Any]:
    """Compute the §7 feature pack for `target_date` (defaults to today)
    and upsert into macro_features. Returns the feature dict."""
    target = target_date or date.today()
    series = await _load_series(target, lookback_days=80)

    crude, usd, bond, nifty = series["crude"], series["usd"], series["bond"], series["nifty"]

    feats: Dict[str, Any] = {}

    # ── Crude ─────────────────────────────────────────────────────────
    crude_now = crude[-1] if crude else None
    feats["crude_20dma"] = _sma(crude, 20)
    feats["crude_50dma"] = _sma(crude, 50)
    feats["crude_trend"] = (
        crude_now is not None and feats["crude_50dma"] is not None
        and crude_now > feats["crude_50dma"]
    )
    feats["crude_momentum_5d"] = _pct_change(crude, 5)
    crude_high_20 = _rolling_max(crude, 20)
    feats["crude_breakout"] = (
        crude_now is not None and crude_high_20 is not None
        and crude_now > crude_high_20
    )

    # ── USDINR ────────────────────────────────────────────────────────
    usd_now = usd[-1] if usd else None
    feats["usd_20dma"] = _sma(usd, 20)
    feats["usd_trend"] = (
        usd_now is not None and feats["usd_20dma"] is not None
        and usd_now > feats["usd_20dma"]
    )
    feats["usd_momentum_5d"] = _pct_change(usd, 5)

    # ── 10Y yield ─────────────────────────────────────────────────────
    bond_now = bond[-1] if bond else None
    feats["yield_50dma"] = _sma(bond, 50)
    feats["yield_trend"] = (
        bond_now is not None and feats["yield_50dma"] is not None
        and bond_now > feats["yield_50dma"]
    )
    feats["yield_momentum_5d"] = _pct_change(bond, 5)

    # ── Market regime (Nifty vs 50DMA) ────────────────────────────────
    nifty_now = nifty[-1] if nifty else None
    feats["nifty_50dma"] = _sma(nifty, 50)
    if nifty_now is None or feats["nifty_50dma"] is None:
        feats["market_regime"] = "NEUTRAL"
    elif nifty_now > feats["nifty_50dma"]:
        feats["market_regime"] = "BULL"
    elif nifty_now < feats["nifty_50dma"]:
        feats["market_regime"] = "BEAR"
    else:
        feats["market_regime"] = "NEUTRAL"

    # ── PR-2.5 global signals ─────────────────────────────────────────
    feats["india_vix_z"]         = _zscore(series["india_vix"])
    feats["us_vix_z"]            = _zscore(series["us_vix"])
    feats["dxy_momentum_5d"]     = _pct_change(series["dxy"], 5)
    feats["sp500_overnight_pct"] = _overnight_change_pct(series["sp500"])
    feats["nasdaq_overnight_pct"] = _overnight_change_pct(series["nasdaq"])

    nikkei_mom = _overnight_change_pct(series["nikkei"])
    hsi_mom = _overnight_change_pct(series["hang_seng"])
    if nikkei_mom is not None and hsi_mom is not None:
        feats["asia_open_pct"] = round((nikkei_mom + hsi_mom) / 2.0, 3)
    elif nikkei_mom is not None:
        feats["asia_open_pct"] = nikkei_mom
    elif hsi_mom is not None:
        feats["asia_open_pct"] = hsi_mom
    else:
        feats["asia_open_pct"] = None

    feats["composite_risk_score"] = _composite_risk_score(feats)

    await _upsert_features(target, feats)
    feats["date"] = str(target)
    return feats


def _composite_risk_score(f: Dict[str, Any]) -> Optional[float]:
    """Composite risk score in approximately [-1, +1] (positive = risk-on,
    negative = risk-off). Combines VIX z-scores, DXY direction, and the
    overnight US move into a single scalar the regime classifier can
    consume on top of the binary inflation/liquidity/risk buckets.

    Weights chosen so a single big VIX spike (z ≥ 2) dominates the score
    — that's the empirically dominant signal. DXY and overnight US are
    secondary corroborators.

    Returns None if too many inputs are missing to produce a meaningful
    number (>50% missing).
    """
    contributions: List[float] = []
    weights: List[float] = []

    # VIX z-scores: higher z → higher risk → negative composite
    if f.get("india_vix_z") is not None:
        # Tame the z-score: clip at ±3 so a single anomalous day doesn't
        # blow out the score.
        z = max(-3.0, min(3.0, float(f["india_vix_z"])))
        contributions.append(-z / 3.0)
        weights.append(0.35)
    if f.get("us_vix_z") is not None:
        z = max(-3.0, min(3.0, float(f["us_vix_z"])))
        contributions.append(-z / 3.0)
        weights.append(0.20)

    # DXY momentum: rising USD → EM outflows → risk-off for India
    if f.get("dxy_momentum_5d") is not None:
        # 1% DXY move ≈ 0.5 score impact; cap at ±2% input.
        dxy_m = max(-2.0, min(2.0, float(f["dxy_momentum_5d"])))
        contributions.append(-dxy_m / 2.0)
        weights.append(0.15)

    # Overnight US: positive S&P/Nasdaq → risk-on for India open
    if f.get("sp500_overnight_pct") is not None:
        sp = max(-3.0, min(3.0, float(f["sp500_overnight_pct"])))
        contributions.append(sp / 3.0)
        weights.append(0.15)
    if f.get("nasdaq_overnight_pct") is not None:
        nq = max(-3.0, min(3.0, float(f["nasdaq_overnight_pct"])))
        contributions.append(nq / 3.0)
        weights.append(0.10)

    # Asia open: ditto
    if f.get("asia_open_pct") is not None:
        ao = max(-3.0, min(3.0, float(f["asia_open_pct"])))
        contributions.append(ao / 3.0)
        weights.append(0.05)

    total_w = sum(weights)
    if total_w < 0.5:    # not enough signals to be meaningful
        return None
    weighted = sum(c * w for c, w in zip(contributions, weights)) / total_w
    return round(max(-1.0, min(1.0, weighted)), 3)


async def _upsert_features(target: date, f: Dict[str, Any]) -> None:
    pool = await pg_client.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO macro_features (
                date,
                crude_20dma, crude_50dma, crude_trend, crude_momentum_5d, crude_breakout,
                usd_20dma, usd_trend, usd_momentum_5d,
                yield_50dma, yield_trend, yield_momentum_5d,
                nifty_50dma, market_regime,
                india_vix_z, us_vix_z, dxy_momentum_5d,
                sp500_overnight_pct, nasdaq_overnight_pct, asia_open_pct,
                composite_risk_score
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                $15,$16,$17,$18,$19,$20,$21
            )
            ON CONFLICT (date) DO UPDATE SET
                crude_20dma           = EXCLUDED.crude_20dma,
                crude_50dma           = EXCLUDED.crude_50dma,
                crude_trend           = EXCLUDED.crude_trend,
                crude_momentum_5d     = EXCLUDED.crude_momentum_5d,
                crude_breakout        = EXCLUDED.crude_breakout,
                usd_20dma             = EXCLUDED.usd_20dma,
                usd_trend             = EXCLUDED.usd_trend,
                usd_momentum_5d       = EXCLUDED.usd_momentum_5d,
                yield_50dma           = EXCLUDED.yield_50dma,
                yield_trend           = EXCLUDED.yield_trend,
                yield_momentum_5d     = EXCLUDED.yield_momentum_5d,
                nifty_50dma           = EXCLUDED.nifty_50dma,
                market_regime         = EXCLUDED.market_regime,
                india_vix_z           = EXCLUDED.india_vix_z,
                us_vix_z              = EXCLUDED.us_vix_z,
                dxy_momentum_5d       = EXCLUDED.dxy_momentum_5d,
                sp500_overnight_pct   = EXCLUDED.sp500_overnight_pct,
                nasdaq_overnight_pct  = EXCLUDED.nasdaq_overnight_pct,
                asia_open_pct         = EXCLUDED.asia_open_pct,
                composite_risk_score  = EXCLUDED.composite_risk_score
            """,
            target,
            f.get("crude_20dma"), f.get("crude_50dma"), f.get("crude_trend"),
            f.get("crude_momentum_5d"), f.get("crude_breakout"),
            f.get("usd_20dma"), f.get("usd_trend"), f.get("usd_momentum_5d"),
            f.get("yield_50dma"), f.get("yield_trend"), f.get("yield_momentum_5d"),
            f.get("nifty_50dma"), f.get("market_regime"),
            f.get("india_vix_z"), f.get("us_vix_z"), f.get("dxy_momentum_5d"),
            f.get("sp500_overnight_pct"), f.get("nasdaq_overnight_pct"),
            f.get("asia_open_pct"), f.get("composite_risk_score"),
        )


# ── Step 2: classify_regime ───────────────────────────────────────────
def _build_insight(*, market: str, inflation: str, liquidity: str, risk: str) -> str:
    """One-line human-readable insight for Copilot. PRD §13 / §15."""
    if risk == "HIGH":
        if inflation == "RISING":
            return "High-risk regime · Avoid consumption/aviation; prefer IT/Oil exporters."
        return "High-risk regime · Trim leverage; favour quality + defensive sectors."
    if risk == "LOW" and market == "BULL":
        return "Bullish, low-risk regime · Lean into momentum + cyclicals."
    if liquidity == "TIGHT":
        return "Tight liquidity · Reduce position sizes; avoid high-beta names."
    if market == "BEAR":
        return "Bearish market · Defensive bias; raise cash."
    return "Neutral macro · No tactical tilt; trade individual setups."


def _build_interpretation(*, market: str, inflation: str, liquidity: str, risk: str) -> str:
    """A second, more conversational line that explains WHY the regime calls
    are what they are — paired with `_build_insight` (which is more
    prescriptive). This is the "thinking out loud" voice the user asked for."""
    if risk == "HIGH" and inflation == "RISING":
        return ("Rising input costs + USD strength compress margins. "
                "Importers + discretionary spend hurt; exporters insulated.")
    if risk == "HIGH":
        return ("Volatility regime — drawdowns are likely sharper than usual. "
                "Survive first, optimise returns second.")
    if risk == "LOW" and market == "BULL":
        return ("Trend is intact and risk indicators are quiet. "
                "Momentum names tend to outperform mean-reversion in this regime.")
    if liquidity == "TIGHT" and market != "BULL":
        return ("Tight liquidity is supportive of quality but punishes leverage. "
                "Stock-specific setups preferred over index trades.")
    if market == "BEAR":
        return ("Indices below trend filters — bias is toward shorts or cash. "
                "Long ideas need stronger-than-usual confirmation to act on.")
    if market == "NEUTRAL":
        return ("Liquidity supportive but no strong directional edge. "
                "Stock-specific setups preferred over index trades.")
    return "No dominant macro signal — trade individual setups on their merits."


def _build_strategy(*, risk: str, multiplier: float, market: str,
                     top_sectors: List[str], weak_sectors: List[str]) -> Dict[str, Any]:
    """Today's actionable strategy block — converts macro state into the
    "what should I do today?" answer. Returns structured fields so the UI
    can render bullets without parsing prose.

    Bias    — Aggressive / Selective long / Neutral / Defensive / Risk-off
    Aggression — text + multiplier (e.g. "Medium · 0.8x position size")
    Avoid   — sector list (worst tilts) — pulled from heatmap
    Focus   — sector list (best tilts) — pulled from heatmap
    """
    # Bias selection
    if risk == "HIGH":
        bias = "Defensive — survive first" if market == "BEAR" else "Risk-off — trim leverage"
    elif risk == "LOW" and market == "BULL":
        bias = "Aggressive — lean into momentum"
    elif market == "BULL":
        bias = "Selective longs only"
    elif market == "BEAR":
        bias = "Defensive — wait for confirmation"
    else:
        bias = "Neutral — selective stock-specific trades"

    # Aggression
    label = "High" if multiplier >= 1.1 else ("Low" if multiplier <= 0.8 else "Medium")
    aggression = f"{label} · {multiplier:.1f}× position size"

    # Sector focus / avoid (top 3 each, capped)
    focus = top_sectors[:3]
    avoid = weak_sectors[:3]

    return {
        "bias": bias,
        "aggression": aggression,
        "aggression_label": label,
        "multiplier": multiplier,
        "focus_sectors": focus,
        "avoid_sectors": avoid,
    }


def _build_macro_confidence(composite: Optional[float], risk: str) -> Dict[str, Any]:
    """Translate the composite_risk_score (-1..+1) into a 0-100 confidence
    percentage + a human label. When composite is missing (PR-1 only data),
    we fall back to a risk-band proxy so the UI never blanks the value."""
    if composite is not None:
        # Map -1 → 0%, +1 → 100%
        pct = round((float(composite) + 1.0) / 2.0 * 100.0, 1)
    else:
        pct = {"LOW": 75.0, "MEDIUM": 50.0, "HIGH": 25.0}.get((risk or "").upper(), 50.0)
    if pct >= 70:
        label = "High"
    elif pct >= 50:
        label = "Moderate"
    elif pct >= 30:
        label = "Low"
    else:
        label = "Very low"
    return {"pct": pct, "label": label}


def _build_risk_warning(*, risk: str, composite: Optional[float],
                         market: str, inflation: str) -> Optional[str]:
    """One-liner red banner copy when the regime warrants a visible warning.
    Returns None when conditions don't justify shouting at the user."""
    if risk == "HIGH" and composite is not None and composite <= -0.3:
        return ("HIGH risk + global signals risk-off — avoid new long exposure today. "
                "Cut leveraged positions; raise cash.")
    if risk == "HIGH":
        return "HIGH risk regime — trim aggressive sizing and avoid weak sectors."
    if market == "BEAR" and inflation == "RISING":
        return "Bearish market with rising inflation — defensive bias warranted."
    if composite is not None and composite <= -0.5:
        return "Composite risk score deeply negative — global risk-off conditions."
    return None


def _multiplier_for(risk: str) -> float:
    if risk == "HIGH":
        return 0.8
    if risk == "LOW":
        return 1.1
    return 1.0


async def classify_regime(target_date: Optional[date] = None) -> Dict[str, Any]:
    """Read the latest `macro_features` row, derive inflation / liquidity /
    risk, persist into macro_state, and return the full state dict.

    Falls back to NEUTRAL/STABLE/MEDIUM when feature inputs are missing —
    the engine should never raise on a partial macro day."""
    target = target_date or date.today()

    pool = await pg_client.get_pool()
    if pool is None:
        return _empty_state(target, reason="no_pg_pool")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM macro_features WHERE date = $1", target,
        )
        if row is None:
            # Most recent prior date as fallback
            row = await conn.fetchrow(
                "SELECT * FROM macro_features WHERE date < $1 "
                "ORDER BY date DESC LIMIT 1", target,
            )
    if row is None:
        return _empty_state(target, reason="no_features_yet")

    crude_trend = bool(row["crude_trend"]) if row["crude_trend"] is not None else False
    yield_trend = bool(row["yield_trend"]) if row["yield_trend"] is not None else False
    usd_trend = bool(row["usd_trend"]) if row["usd_trend"] is not None else False
    market_regime = row["market_regime"] or "NEUTRAL"

    inflation = "RISING" if (crude_trend and yield_trend) else "STABLE"
    liquidity = "TIGHT" if yield_trend else "EASY"
    if inflation == "RISING" and usd_trend:
        risk = "HIGH"
    elif market_regime == "BULL":
        risk = "LOW"
    else:
        risk = "MEDIUM"

    # PR-2.5: composite risk overrides the rule-based risk band when the
    # global signal is strong enough. A composite ≤ -0.5 (deep risk-off
    # via VIX spike + overnight US dump + DXY rally) bumps risk to HIGH
    # even if the 3-input classifier said MEDIUM. Symmetric on the upside:
    # composite ≥ +0.5 bumps a MEDIUM regime down to LOW.
    composite = row["composite_risk_score"] if "composite_risk_score" in row.keys() else None
    composite = float(composite) if composite is not None else None
    if composite is not None:
        if composite <= -0.5 and risk != "HIGH":
            risk = "HIGH"
        elif composite >= 0.5 and risk == "MEDIUM":
            risk = "LOW"

    multiplier = _multiplier_for(risk)
    insight = _build_insight(
        market=market_regime, inflation=inflation, liquidity=liquidity, risk=risk,
    )
    preopen_summary = _build_preopen(row)

    await _upsert_state(
        target, inflation, liquidity, risk, multiplier, insight,
        composite_risk_score=composite, preopen_summary=preopen_summary,
    )

    return {
        "date": str(target),
        "market": market_regime,
        "inflation": inflation,
        "liquidity": liquidity,
        "risk": risk,
        "multiplier": multiplier,
        "insight": insight,
        "composite_risk_score": composite,
        "preopen_summary": preopen_summary,
        "features_used_date": str(row["date"]),
    }


def _build_preopen(row: Any) -> str:
    """One-line summary of the overnight + Asia open environment for the
    MacroBar's pre-open strip. Only emits parts we have data for."""
    parts: List[str] = []
    sp = row["sp500_overnight_pct"] if "sp500_overnight_pct" in row.keys() else None
    nq = row["nasdaq_overnight_pct"] if "nasdaq_overnight_pct" in row.keys() else None
    asia = row["asia_open_pct"] if "asia_open_pct" in row.keys() else None
    dxy = row["dxy_momentum_5d"] if "dxy_momentum_5d" in row.keys() else None
    vix_z = row["india_vix_z"] if "india_vix_z" in row.keys() else None

    if sp is not None:
        parts.append(f"S&P {float(sp):+.2f}%")
    if nq is not None:
        parts.append(f"Nasdaq {float(nq):+.2f}%")
    if asia is not None:
        parts.append(f"Asia {float(asia):+.2f}%")
    if dxy is not None:
        parts.append(f"DXY 5d {float(dxy):+.2f}%")
    if vix_z is not None and abs(float(vix_z)) >= 1:
        parts.append(f"VIX z {float(vix_z):+.1f}")
    return " · ".join(parts) if parts else "No global signals available yet."


def _empty_state(target: date, *, reason: str) -> Dict[str, Any]:
    return {
        "date": str(target),
        "market": "NEUTRAL",
        "inflation": "STABLE",
        "liquidity": "EASY",
        "risk": "MEDIUM",
        "multiplier": 1.0,
        "insight": "Macro layer not yet populated — neutral defaults applied.",
        "_reason": reason,
    }


async def _upsert_state(
    target: date, inflation: str, liquidity: str, risk: str,
    multiplier: float, insight: str,
    *,
    composite_risk_score: Optional[float] = None,
    preopen_summary: Optional[str] = None,
) -> None:
    pool = await pg_client.get_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO macro_state (
                date, inflation, liquidity, risk, macro_multiplier, insight,
                composite_risk_score, preopen_summary
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (date) DO UPDATE SET
                inflation             = EXCLUDED.inflation,
                liquidity             = EXCLUDED.liquidity,
                risk                  = EXCLUDED.risk,
                macro_multiplier      = EXCLUDED.macro_multiplier,
                insight               = EXCLUDED.insight,
                composite_risk_score  = EXCLUDED.composite_risk_score,
                preopen_summary       = EXCLUDED.preopen_summary
            """,
            target, inflation, liquidity, risk, multiplier, insight,
            composite_risk_score, preopen_summary,
        )


# ── Step 3: latest macro snapshot for /api/macro/today ─────────────────
async def latest_state() -> Optional[Dict[str, Any]]:
    """Read the most recent macro_state row + the matching macro_features
    + the matching macro_daily so the API can hand the UI a single
    self-contained payload."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    # Wrapped in try/except so a missing-table/missing-column error
    # (e.g. migration 016/017 didn't apply on first deploy) returns None
    # rather than 500-ing. The route then surfaces the empty-state CTA
    # which lets the operator click "Backfill" without context-switching.
    #
    # We also retry once on InvalidCachedStatementError. asyncpg caches
    # the prepared-statement plan, and after a migration adds columns
    # the cached plan is stale. New pool init disables the cache, but
    # this guards against any in-flight pool that pre-dated the fix.
    async def _read():
        async with pool.acquire() as conn:
            state = await conn.fetchrow(
                "SELECT * FROM macro_state ORDER BY date DESC LIMIT 1",
            )
            if state is None:
                return None, None, None
            feats = await conn.fetchrow(
                "SELECT * FROM macro_features WHERE date = $1", state["date"],
            )
            daily = await conn.fetchrow(
                "SELECT * FROM macro_daily WHERE date = $1", state["date"],
            )
            return state, feats, daily

    try:
        result = await _read()
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "cached statement plan is invalid" in msg:
            # Force-clear by recreating the pool, then retry once.
            logger.info("latest_state: cached plan invalidated — rebuilding pool and retrying")
            try:
                from services import pg_client as _pg
                await _pg.close_pool()
                pool = await _pg.get_pool()
                if pool is None:
                    return None
                result = await _read()
            except Exception as e2:  # noqa: BLE001
                logger.warning("latest_state retry failed: %s", e2)
                return None
        else:
            logger.warning("latest_state failed (likely schema): %s", e)
            return None
    if result is None or result[0] is None:
        return None
    state, feats, daily = result

    # PR-A holiday correction: if the latest macro_state row points at a
    # day where Nifty (the canonical Indian open marker) is missing, that
    # row is meaningless for Indian regime classification — yfinance
    # back-dated a forex/global tick to a non-trading day. Walk back to
    # the most recent date that has a real Nifty print.
    if daily is None or daily["nifty"] is None:
        try:
            async with pool.acquire() as conn:
                fallback = await conn.fetchrow(
                    "SELECT date FROM macro_daily "
                    "WHERE nifty IS NOT NULL AND date < $1 "
                    "ORDER BY date DESC LIMIT 1",
                    state["date"],
                )
            if fallback and fallback["date"]:
                logger.info(
                    "latest_state: %s has no Nifty (likely NSE holiday) — "
                    "falling back to %s",
                    state["date"], fallback["date"],
                )
                async with pool.acquire() as conn:
                    state = await conn.fetchrow(
                        "SELECT * FROM macro_state WHERE date = $1",
                        fallback["date"],
                    )
                    if state is not None:
                        feats = await conn.fetchrow(
                            "SELECT * FROM macro_features WHERE date = $1",
                            state["date"],
                        )
                        daily = await conn.fetchrow(
                            "SELECT * FROM macro_daily WHERE date = $1",
                            state["date"],
                        )
                if state is None:
                    return None
        except Exception as e:  # noqa: BLE001
            logger.debug("Nifty-fallback walk failed: %s", e)
    def _f(d: Any, key: str) -> Optional[float]:
        if d is None:
            return None
        v = d[key] if key in d.keys() else None
        return float(v) if v is not None else None

    def _b(d: Any, key: str) -> Optional[bool]:
        if d is None:
            return None
        v = d[key] if key in d.keys() else None
        return bool(v) if v is not None else None

    def _s(d: Any, key: str) -> Optional[str]:
        if d is None:
            return None
        return d[key] if key in d.keys() else None

    # Derive holiday flag — if the most recent macro_state row is older
    # than today, today is a market holiday (or the cron hasn't run yet).
    today = date.today()
    state_date = state["date"]
    is_open_today = state_date is not None and state_date >= today
    days_stale = (today - state_date).days if state_date is not None else None

    # PR-A — Build the action layer + interpretation + confidence + warning
    # by reading the same `state` row we already have. Sector focus/avoid
    # comes from sector_macro_scores (best-effort; empty list on missing data).
    market = _s(feats, "market_regime") or "NEUTRAL"
    inflation = state["inflation"] or "STABLE"
    liquidity = state["liquidity"] or "EASY"
    risk = state["risk"] or "MEDIUM"
    multiplier = _f(state, "macro_multiplier") or 1.0
    composite = _f(state, "composite_risk_score")

    top_sectors: List[str] = []
    weak_sectors: List[str] = []
    try:
        async with pool.acquire() as conn:
            sec_rows = await conn.fetch(
                "SELECT sector, macro_score FROM sector_macro_scores "
                "WHERE date = $1 ORDER BY macro_score DESC", state_date,
            )
        if sec_rows:
            top_sectors = [r["sector"] for r in sec_rows[:3]
                           if r["macro_score"] is not None and float(r["macro_score"]) > 0.3]
            weak_sectors = [r["sector"] for r in reversed(sec_rows[-3:])
                            if r["macro_score"] is not None and float(r["macro_score"]) < -0.3]
    except Exception as e:  # noqa: BLE001
        logger.debug("sector top/weak fetch failed: %s", e)

    interpretation = _build_interpretation(
        market=market, inflation=inflation, liquidity=liquidity, risk=risk,
    )
    strategy = _build_strategy(
        risk=risk, multiplier=multiplier, market=market,
        top_sectors=top_sectors, weak_sectors=weak_sectors,
    )
    confidence = _build_macro_confidence(composite, risk)
    risk_warning = _build_risk_warning(
        risk=risk, composite=composite, market=market, inflation=inflation,
    )

    return {
        "date": state_date.isoformat() if state_date else None,
        "market_open_today": is_open_today,
        "is_holiday_view": not is_open_today,
        "days_stale": days_stale,
        "as_of_message": (
            None if is_open_today else
            f"Markets closed today — showing data as of {state_date.isoformat()}"
            + (f" ({days_stale} day{'s' if days_stale != 1 else ''} ago)"
               if days_stale and days_stale > 1 else "")
        ),
        "market": market,
        "inflation": inflation,
        "liquidity": liquidity,
        "risk": risk,
        "multiplier": multiplier,
        "insight": state["insight"],
        # PR-A action layer
        "interpretation": interpretation,
        "strategy": strategy,
        "confidence": confidence,
        "risk_warning": risk_warning,
        "composite_risk_score": composite,
        "preopen_summary": _s(state, "preopen_summary"),
        "values": {
            "crude":     _f(daily, "crude_price"),
            "usd_inr":   _f(daily, "usd_inr"),
            "bond_10y":  _f(daily, "bond_10y"),
            "nifty":     _f(daily, "nifty"),
            "india_vix": _f(daily, "india_vix"),
            "us_vix":    _f(daily, "us_vix"),
            "dxy":       _f(daily, "dxy"),
            "sp500":     _f(daily, "sp500"),
            "nasdaq":    _f(daily, "nasdaq"),
            "nikkei":    _f(daily, "nikkei"),
            "hang_seng": _f(daily, "hang_seng"),
        },
        "features": {
            "crude_trend":          _b(feats, "crude_trend"),
            "crude_breakout":       _b(feats, "crude_breakout"),
            "crude_momentum_5d":    _f(feats, "crude_momentum_5d"),
            "usd_trend":            _b(feats, "usd_trend"),
            "usd_momentum_5d":      _f(feats, "usd_momentum_5d"),
            "yield_trend":          _b(feats, "yield_trend"),
            "yield_momentum_5d":    _f(feats, "yield_momentum_5d"),
            "india_vix_z":          _f(feats, "india_vix_z"),
            "us_vix_z":             _f(feats, "us_vix_z"),
            "dxy_momentum_5d":      _f(feats, "dxy_momentum_5d"),
            "sp500_overnight_pct":  _f(feats, "sp500_overnight_pct"),
            "nasdaq_overnight_pct": _f(feats, "nasdaq_overnight_pct"),
            "asia_open_pct":        _f(feats, "asia_open_pct"),
        },
        "sources": {
            "crude":     _s(daily, "source_crude"),
            "usd":       _s(daily, "source_usd"),
            "bond":      _s(daily, "source_bond"),
            "nifty":     _s(daily, "source_nifty"),
            "india_vix": _s(daily, "source_india_vix"),
            "us_vix":    _s(daily, "source_us_vix"),
            "dxy":       _s(daily, "source_dxy"),
            "sp500":     _s(daily, "source_sp500"),
            "nasdaq":    _s(daily, "source_nasdaq"),
            "nikkei":    _s(daily, "source_nikkei"),
            "hang_seng": _s(daily, "source_hang_seng"),
        },
        # Per-metric data-quality confidence (e.g. crude=1.0 = primary
        # source, bond=0.5 = US 10Y proxy). Renamed from "confidence" to
        # "source_confidence" because it was colliding with the PR-A
        # macro-confidence object (which is the user-facing percentage).
        "source_confidence": {
            "crude":     _f(daily, "confidence_crude"),
            "usd":       _f(daily, "confidence_usd"),
            "bond":      _f(daily, "confidence_bond"),
            "nifty":     _f(daily, "confidence_nifty"),
            "india_vix": _f(daily, "confidence_india_vix"),
            "us_vix":    _f(daily, "confidence_us_vix"),
            "dxy":       _f(daily, "confidence_dxy"),
            "sp500":     _f(daily, "confidence_sp500"),
            "nasdaq":    _f(daily, "confidence_nasdaq"),
            "nikkei":    _f(daily, "confidence_nikkei"),
            "hang_seng": _f(daily, "confidence_hang_seng"),
        },
    }


# ── Migration runner (idempotent — called from server startup) ─────────
async def ensure_schema() -> None:
    """Apply macro migrations on startup if PG is available.

    Runs 016 (PR-1 base tables) then 017 (PR-2.5 global indicator columns).
    Both are idempotent — every CREATE uses IF NOT EXISTS, every ALTER uses
    ADD COLUMN IF NOT EXISTS."""
    pool = await pg_client.get_pool()
    if pool is None:
        return
    import os
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
    for fname in ("016_macro_intelligence.sql", "017_macro_global_indicators.sql"):
        sql_path = os.path.join(base, fname)
        if not os.path.exists(sql_path):
            logger.warning("macro_engine: migration file missing: %s", sql_path)
            continue
        sql = open(sql_path).read()
        async with pool.acquire() as conn:
            try:
                await conn.execute(sql)
            except Exception as e:  # noqa: BLE001
                logger.warning("macro_engine schema apply failed (%s): %s", fname, e)


# ── End-to-end driver (called by cron) ─────────────────────────────────
async def run_daily(target_date: Optional[date] = None) -> Dict[str, Any]:
    """Ingest → features → regime → sector scores, in one call. Caller is
    the cron job. The sector_scores step (PR-2) is best-effort — failure
    there shouldn't block the regime classification.

    Holiday handling: ingest_today() now dates the row by the actual
    Nifty trading day (not today's calendar date). We honour that
    `as_of_date` for downstream feature/regime/sector compute, so on
    a Saturday everything correctly recomputes against Friday's row
    rather than creating an empty Saturday row."""
    from services import macro_ingester
    target = target_date or date.today()
    ing = await macro_ingester.ingest_today(target_date=target)
    # Honour the actual trading date the ingester wrote to. On a holiday
    # this is the prior trading day; on a regular session it's `target`.
    as_of = target
    try:
        as_of_str = ing.get("as_of_date") if isinstance(ing, dict) else None
        if as_of_str:
            as_of = date.fromisoformat(as_of_str)
    except (TypeError, ValueError):
        pass
    feats = await compute_features(as_of)
    state = await classify_regime(as_of)
    sector_summary: Dict[str, Any] = {"ok": False, "error": "not_attempted"}
    try:
        from services import macro_sector
        sector_summary = await macro_sector.compute_sector_scores(as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("compute_sector_scores failed: %s", e)
        sector_summary = {"ok": False, "error": str(e)[:200]}
    return {
        "ingest": ing, "features": feats, "state": state,
        "sector_scores": sector_summary,
        "as_of_date": str(as_of),
        "market_open_today": (ing or {}).get("market_open_today", True),
    }
