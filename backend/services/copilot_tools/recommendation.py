"""Recommendation tools for the Nivesh Copilot.

TASK-042: composite_score()   — weighted 5-dimension stock scorer
TASK-043: screen_stocks()     — DAAS-backed stock screener with RSI/PE/Piotroski filters
TASK-044: recommend_mf()      — MF recommendations filtered by risk band + quality criteria

Score weights (per brief):
  Technical     25%  — RSI, MACD, price vs SMA
  Fundamental   30%  — Piotroski, ROE, D/E, Altman Z
  Valuation     15%  — valuation_signal vs sector PE
  Risk          15%  — beta / ATR vs user risk profile
  Portfolio Fit 15%  — sector concentration, equity allocation
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .daas_client import DaasError, _get, get_stock_features_latest

logger = logging.getLogger(__name__)

# ── Weights ───────────────────────────────────────────────────────────────────

_WEIGHTS: Dict[str, float] = {
    "technical":     0.25,
    "fundamental":   0.30,
    "valuation":     0.15,
    "risk":          0.15,
    "portfolio_fit": 0.15,
}


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class CompositeScore:
    symbol: str
    ok: bool

    technical_score:     float = 0.0   # 0-10, weight 25 %
    fundamental_score:   float = 0.0   # 0-10, weight 30 %
    valuation_score:     float = 0.0   # 0-10, weight 15 %
    risk_score:          float = 0.0   # 0-10, weight 15 %
    portfolio_fit_score: float = 0.0   # 0-10, weight 15 %

    total_score: float = 0.0           # weighted sum 0-10
    signal:      str   = "HOLD"        # BUY / HOLD / AVOID

    reasons: List[str]       = field(default_factory=list)
    data:    Dict[str, Any]  = field(default_factory=dict)
    error:   Optional[str]   = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"COMPOSITE_SCORE symbol={self.symbol} unavailable reason={self.error}"
        return (
            f"COMPOSITE_SCORE symbol={self.symbol} "
            f"total={self.total_score:.1f}/10 signal={self.signal} "
            f"tech={self.technical_score:.1f} fund={self.fundamental_score:.1f} "
            f"val={self.valuation_score:.1f} risk={self.risk_score:.1f} "
            f"fit={self.portfolio_fit_score:.1f} "
            f"reasons=[{'; '.join(self.reasons[:3])}]"
        )


@dataclass
class ScreenerResult:
    ok:             bool
    rows:           List[Dict[str, Any]] = field(default_factory=list)
    total_scanned:  int                  = 0
    filter_summary: str                  = ""
    error:          Optional[str]        = None


@dataclass
class MfRecommendation:
    ok:            bool
    risk_band:     str
    category_used: str
    rows:          List[Dict[str, Any]] = field(default_factory=list)
    summary:       str                  = ""
    error:         Optional[str]        = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"MF_RECOMMENDATION unavailable reason={self.error}"
        names = [r.get("scheme_name", r.get("scheme_code", "?")) for r in self.rows[:5]]
        return (
            f"MF_RECOMMENDATION risk_band={self.risk_band} "
            f"category={self.category_used} "
            f"top=[{'; '.join(names)}] "
            f"summary={self.summary}"
        )


# ── Component scorers (each returns float 0-10 + reason list) ────────────────

def _technical_score(feat: Dict[str, Any]) -> tuple[float, List[str]]:
    scores: List[float] = []
    reasons: List[str]  = []

    rsi = feat.get("rsi14")
    if rsi is not None:
        if rsi < 30:
            scores.append(9.5); reasons.append(f"RSI {rsi:.1f} — oversold (reversal setup)")
        elif rsi < 45:
            scores.append(7.5); reasons.append(f"RSI {rsi:.1f} — bullish setup")
        elif rsi < 60:
            scores.append(6.0)
        elif rsi < 70:
            scores.append(3.5); reasons.append(f"RSI {rsi:.1f} — nearing overbought")
        else:
            scores.append(2.0); reasons.append(f"RSI {rsi:.1f} — overbought (caution)")

    macd      = feat.get("macd")
    macd_sig  = feat.get("macd_signal")
    if macd is not None:
        if macd > 0:
            scores.append(7.0)
            if macd_sig is not None and macd > macd_sig:
                reasons.append("MACD bullish crossover")
        else:
            scores.append(3.5); reasons.append("MACD bearish")

    close  = feat.get("close")
    sma50  = feat.get("sma50")
    sma200 = feat.get("sma200")
    if close and sma50:
        if close > sma50:
            scores.append(7.0)
            if sma200 and close > sma200:
                reasons.append("Price above SMA50 & SMA200 (uptrend)")
            else:
                reasons.append("Price above SMA50")
        else:
            scores.append(3.0); reasons.append("Price below SMA50 (downtrend)")

    return (sum(scores) / len(scores) if scores else 5.0), reasons


def _fundamental_score(feat: Dict[str, Any]) -> tuple[float, List[str]]:
    scores: List[float] = []
    reasons: List[str]  = []

    piotroski = feat.get("piotroski_score")
    if piotroski is not None:
        scores.append(piotroski * (10.0 / 9.0))
        label = "strong" if piotroski >= 7 else "good" if piotroski >= 5 else "average" if piotroski >= 3 else "weak"
        reasons.append(f"Piotroski {piotroski}/9 ({label})")

    roe = feat.get("roe_pct")
    if roe is not None:
        if roe >= 20:
            scores.append(9.0); reasons.append(f"ROE {roe:.1f}% (high quality)")
        elif roe >= 12:
            scores.append(6.5)
        elif roe >= 0:
            scores.append(3.5)
        else:
            scores.append(1.0); reasons.append(f"ROE {roe:.1f}% (negative)")

    de = feat.get("debt_to_equity")
    if de is not None:
        if de <= 0.3:
            scores.append(9.0)
        elif de <= 0.7:
            scores.append(7.0)
        elif de <= 1.5:
            scores.append(4.5)
        else:
            scores.append(2.0); reasons.append(f"High leverage D/E {de:.1f}x")

    z = feat.get("altman_z_score")
    if z is not None:
        if z > 2.99:
            scores.append(8.5)
        elif z > 1.81:
            scores.append(5.0); reasons.append(f"Altman Z {z:.2f} — grey zone")
        else:
            scores.append(2.0); reasons.append(f"Altman Z {z:.2f} — distress zone")

    return (sum(scores) / len(scores) if scores else 5.0), reasons


def _valuation_score(feat: Dict[str, Any]) -> tuple[float, List[str]]:
    reasons: List[str] = []
    val_signal       = feat.get("valuation_signal")
    pe               = feat.get("pe_ttm")
    sector_median_pe = feat.get("sector_median_pe")

    base = {"undervalued": 8.5, "fairly_valued": 5.5, "overvalued": 2.5}.get(val_signal or "", 5.0)
    if val_signal == "undervalued":
        reasons.append("Undervalued vs sector peers")
    elif val_signal == "overvalued":
        reasons.append("Overvalued vs sector peers")

    if pe and sector_median_pe and pe > 0 and sector_median_pe > 0:
        pct = (pe / sector_median_pe - 1) * 100
        if pct < -25:
            base = min(10.0, base + 1.5)
            reasons.append(f"PE {pe:.1f}x — {abs(pct):.0f}% discount to sector {sector_median_pe:.1f}x")
        elif pct > 40:
            base = max(0.0, base - 1.5)

    return base, reasons


def _risk_score(feat: Dict[str, Any], risk_profile: str) -> tuple[float, List[str]]:
    scores: List[float] = []
    reasons: List[str]  = []

    beta    = feat.get("beta") or feat.get("beta_1y")
    atr_pct = feat.get("atr_pct")

    if beta is not None:
        if risk_profile == "conservative":
            s = max(0.0, 10.0 - (beta - 0.5) * 6)
        elif risk_profile == "aggressive":
            s = min(10.0, 4.0 + beta * 4)
        else:                          # moderate
            s = max(0.0, 10.0 - abs(beta - 1.0) * 4)
        scores.append(s)
        reasons.append(f"Beta {beta:.2f}")

    if atr_pct is not None:
        if risk_profile == "conservative":
            s = max(0.0, 10.0 - atr_pct * 2)
        elif risk_profile == "aggressive":
            s = min(10.0, 4.0 + atr_pct * 1.5)
        else:
            s = max(0.0, 8.0 - atr_pct * 1.2)
        scores.append(max(0.0, min(10.0, s)))

    return (sum(scores) / len(scores) if scores else 6.0), reasons


def _portfolio_fit_score(
    feat: Dict[str, Any],
    portfolio_data: Optional[Dict[str, Any]],
) -> tuple[float, List[str]]:
    reasons: List[str] = []
    if not portfolio_data:
        return 6.0, []

    stock_sector   = feat.get("sector")
    sector_weights = portfolio_data.get("sector_weights", {})
    equity_pct     = portfolio_data.get("equity_pct", 0)

    if stock_sector and sector_weights:
        existing_pct = sector_weights.get(stock_sector, 0)
        if existing_pct > 30:
            reasons.append(f"{stock_sector} already {existing_pct:.0f}% of portfolio — concentration risk")
            return 3.0, reasons
        elif existing_pct > 20:
            return 5.5, reasons
        elif existing_pct == 0:
            reasons.append(f"Adds {stock_sector} diversification")
            return 8.5, reasons
        return 7.0, reasons

    if equity_pct > 80:
        beta = feat.get("beta", 1.0) or 1.0
        if beta > 1.2:
            reasons.append("Portfolio equity-heavy; high-beta addition raises risk")
            return 4.0, reasons

    return 6.0, reasons


# ── TASK-042: composite_score ─────────────────────────────────────────────────

async def composite_score(
    symbol: str,
    *,
    user_risk_profile: str = "moderate",
    portfolio_data: Optional[Dict[str, Any]] = None,
) -> CompositeScore:
    """Compute weighted composite investment score for one stock.

    Calls DAAS for the latest feature row, then scores across five dimensions.
    Returns CompositeScore with total 0-10 and signal BUY / HOLD / AVOID.
    """
    sym = symbol.upper().strip()
    try:
        feat = await get_stock_features_latest(sym)
    except DaasError as exc:
        return CompositeScore(symbol=sym, ok=False, error=str(exc))

    if not feat:
        return CompositeScore(symbol=sym, ok=False, error="no_data")

    tech_s, tech_r = _technical_score(feat)
    fund_s, fund_r = _fundamental_score(feat)
    val_s,  val_r  = _valuation_score(feat)
    risk_s, risk_r = _risk_score(feat, user_risk_profile)
    fit_s,  fit_r  = _portfolio_fit_score(feat, portfolio_data)

    total = round(
        tech_s * _WEIGHTS["technical"]
        + fund_s * _WEIGHTS["fundamental"]
        + val_s  * _WEIGHTS["valuation"]
        + risk_s * _WEIGHTS["risk"]
        + fit_s  * _WEIGHTS["portfolio_fit"],
        2,
    )

    signal = "BUY" if total >= 7.0 else "HOLD" if total >= 4.5 else "AVOID"

    return CompositeScore(
        symbol=sym, ok=True,
        technical_score=round(tech_s, 2),
        fundamental_score=round(fund_s, 2),
        valuation_score=round(val_s, 2),
        risk_score=round(risk_s, 2),
        portfolio_fit_score=round(fit_s, 2),
        total_score=total,
        signal=signal,
        reasons=(tech_r + fund_r + val_r + risk_r + fit_r)[:6],
        data={
            "symbol":            sym,
            "close":             feat.get("close"),
            "rsi14":             feat.get("rsi14"),
            "macd":              feat.get("macd"),
            "pe_ttm":            feat.get("pe_ttm"),
            "piotroski_score":   feat.get("piotroski_score"),
            "valuation_signal":  feat.get("valuation_signal"),
            "sector":            feat.get("sector"),
            "beta":              feat.get("beta"),
        },
    )


async def composite_score_batch(
    symbols: List[str],
    *,
    user_risk_profile: str = "moderate",
    portfolio_data: Optional[Dict[str, Any]] = None,
    top_n: int = 5,
) -> List[CompositeScore]:
    """Score multiple stocks and return top_n by composite score (BUY first)."""
    import asyncio
    results = await asyncio.gather(
        *[composite_score(s, user_risk_profile=user_risk_profile,
                          portfolio_data=portfolio_data) for s in symbols],
        return_exceptions=True,
    )
    scored = []
    for r in results:
        if isinstance(r, Exception):
            continue
        if r.ok:
            scored.append(r)
    scored.sort(key=lambda x: x.total_score, reverse=True)
    return scored[:top_n]


# ── TASK-043: screen_stocks ───────────────────────────────────────────────────

async def screen_stocks(
    *,
    rsi_min: float = 0.0,
    rsi_max: float = 65.0,
    max_pe: Optional[float] = None,
    min_piotroski: Optional[int] = None,
    valuation: Optional[str] = None,    # "undervalued" | "fairly_valued" | "overvalued"
    min_roe: Optional[float] = None,
    max_debt_to_equity: Optional[float] = None,
    limit: int = 10,
) -> ScreenerResult:
    """Screen stocks from nidp.stock_features_daily via DAAS /screener/stocks.

    Returned rows contain: symbol, close, rsi14, macd, pe_ttm, piotroski_score,
    valuation_signal, sector, roe_pct, debt_to_equity, altman_z_score.
    Sorted by composite_rank ascending (best first).
    """
    params: Dict[str, Any] = {"limit": limit}
    desc_parts: List[str]  = []

    if rsi_min > 0:
        params["rsi_min"] = rsi_min;        desc_parts.append(f"RSI>{rsi_min:.0f}")
    if rsi_max < 100:
        params["rsi_max"] = rsi_max;        desc_parts.append(f"RSI<{rsi_max:.0f}")
    if max_pe is not None:
        params["pe_max"]  = max_pe;         desc_parts.append(f"PE<{max_pe:.0f}")
    if min_piotroski is not None:
        params["piotroski_min"] = min_piotroski; desc_parts.append(f"Piotroski≥{min_piotroski}")
    if valuation is not None:
        params["valuation_signal"] = valuation;  desc_parts.append(f"valuation={valuation}")
    if min_roe is not None:
        params["roe_min"] = min_roe;        desc_parts.append(f"ROE>{min_roe:.0f}%")
    if max_debt_to_equity is not None:
        params["de_max"]  = max_debt_to_equity;  desc_parts.append(f"D/E<{max_debt_to_equity:.1f}")

    filter_summary = ", ".join(desc_parts) if desc_parts else "no filters applied"

    try:
        resp = await _get("/screener/stocks", params=params)
        rows  = resp.get("data", []) if resp else []
        total = resp.get("total_scanned", len(rows)) if resp else len(rows)
        return ScreenerResult(ok=True, rows=rows, total_scanned=total, filter_summary=filter_summary)
    except DaasError as exc:
        logger.warning("screen_stocks daas_error: %s", exc)
        return ScreenerResult(ok=False, error=str(exc), filter_summary=filter_summary)


# ── TASK-044: recommend_mf ────────────────────────────────────────────────────

_RISK_BAND_CATEGORIES: Dict[str, List[str]] = {
    "conservative": [
        "Liquid", "Overnight", "Short Duration",
        "Corporate Bond", "Banking and PSU",
    ],
    "moderate": [
        "Balanced Advantage", "Multi Asset Allocation",
        "Large Cap", "Flexi Cap", "Hybrid",
    ],
    "aggressive": [
        "Mid Cap", "Small Cap", "Large & Mid Cap",
        "Flexi Cap", "Sectoral/Thematic",
    ],
}


async def recommend_mf(
    *,
    category: Optional[str] = None,
    risk_band: str = "moderate",
    min_return_1y: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    max_ter: Optional[float] = None,
    top_n: int = 5,
) -> MfRecommendation:
    """Recommend mutual funds by risk band and optional quality filters.

    If category is omitted, the primary category for the risk band is used.
    Fetches from DAAS /mf/performance/category/{category} (sorted by composite_rank)
    then applies quality-filter post-processing.

    Risk band → primary category:
      conservative → Liquid
      moderate     → Balanced Advantage
      aggressive   → Mid Cap
    """
    target_category = category or _RISK_BAND_CATEGORIES.get(risk_band, ["Flexi Cap"])[0]

    try:
        resp = await _get(
            f"/mf/performance/category/{target_category}",
            params={"limit": top_n * 4, "metric": "composite_rank"},
        )
        rows = resp.get("data", []) if resp else []
    except DaasError as exc:
        logger.warning("recommend_mf daas_error category=%s: %s", target_category, exc)
        return MfRecommendation(ok=False, risk_band=risk_band, category_used=target_category, error=str(exc))

    filtered: List[Dict[str, Any]] = []
    for r in rows:
        if min_return_1y is not None:
            if r.get("return_1y") is None or float(r["return_1y"]) < min_return_1y:
                continue
        if min_sharpe is not None:
            if r.get("sharpe_1y") is None or float(r["sharpe_1y"]) < min_sharpe:
                continue
        if max_ter is not None and r.get("ter") is not None:
            if float(r["ter"]) > max_ter:
                continue
        filtered.append(r)
        if len(filtered) >= top_n:
            break

    top_names = [r.get("scheme_name", r.get("scheme_code", "?")) for r in filtered[:3]]
    q_parts: List[str] = []
    if min_return_1y is not None:
        q_parts.append(f"1Y>{min_return_1y:.0f}%")
    if min_sharpe is not None:
        q_parts.append(f"Sharpe>{min_sharpe:.1f}")
    if max_ter is not None:
        q_parts.append(f"TER<{max_ter:.2f}%")

    suffix = f" ({', '.join(q_parts)})" if q_parts else ""
    summary = (
        f"Top {len(filtered)} {target_category} fund{'s' if len(filtered) != 1 else ''} "
        f"for {risk_band} investors{suffix}"
        + (f": {', '.join(top_names)}" if top_names else " — no qualifying funds found")
    )

    return MfRecommendation(
        ok=True, risk_band=risk_band, category_used=target_category,
        rows=filtered, summary=summary,
    )
