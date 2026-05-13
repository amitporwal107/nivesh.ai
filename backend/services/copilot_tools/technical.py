"""Technical analysis tools for the Nivesh Copilot.

These functions are the data layer for technical analysis queries. They:
  1. Call the NIDP DAAS API to fetch pre-computed indicators
  2. Interpret the raw numbers into actionable signals
  3. Return structured dicts ready for LLM context or direct widget rendering

Each function returns a `TechnicalResult` that the RAG orchestrator
and (future) LangGraph agents consume identically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .daas_client import DaasError, get_stock_features_latest, get_stock_features_history

logger = logging.getLogger(__name__)


@dataclass
class TechnicalResult:
    symbol: str
    ok: bool
    summary: str                    # one-liner for LLM context
    signals: List[str] = field(default_factory=list)   # bullish/bearish signals
    data: Dict[str, Any] = field(default_factory=dict)  # raw feature values
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        """Compact string for LLM system prompt injection (~300 chars max)."""
        if not self.ok:
            return f"TECHNICAL_ANALYSIS symbol={self.symbol} status=unavailable reason={self.error}"
        parts = [f"TECHNICAL_ANALYSIS symbol={self.symbol}"]
        d = self.data
        if d.get("close"):
            parts.append(f"close={d['close']:.2f}")
        if d.get("rsi14") is not None:
            parts.append(f"rsi14={d['rsi14']:.1f}")
        if d.get("macd") is not None:
            parts.append(f"macd={d['macd']:.3f}")
        if d.get("sma20") is not None:
            parts.append(f"sma20={d['sma20']:.2f}")
        if d.get("sma50") is not None:
            parts.append(f"sma50={d['sma50']:.2f}")
        if d.get("return_20d_pct") is not None:
            parts.append(f"ret20d={d['return_20d_pct']:+.1f}%")
        if d.get("atr_pct") is not None:
            parts.append(f"atr_pct={d['atr_pct']:.2f}%")
        if d.get("vol_z20") is not None:
            parts.append(f"vol_z={d['vol_z20']:.2f}")
        parts.append(f"signals=[{'; '.join(self.signals[:4])}]")
        parts.append(f"summary={self.summary}")
        return " | ".join(parts)


def _rsi_signal(rsi: Optional[float]) -> Optional[str]:
    if rsi is None:
        return None
    if rsi >= 70:
        return f"RSI {rsi:.0f} — overbought"
    if rsi <= 30:
        return f"RSI {rsi:.0f} — oversold"
    return f"RSI {rsi:.0f} — neutral"


def _macd_signal(macd: Optional[float], hist: Optional[float]) -> Optional[str]:
    if macd is None:
        return None
    direction = "bullish" if macd > 0 else "bearish"
    momentum = ""
    if hist is not None:
        momentum = ", momentum building" if hist > 0 else ", momentum fading"
    return f"MACD {macd:.2f} — {direction}{momentum}"


def _trend_signal(close: Optional[float], sma20: Optional[float], sma50: Optional[float]) -> Optional[str]:
    if close is None:
        return None
    signals = []
    if sma20 is not None:
        signals.append("above SMA20" if close > sma20 else "below SMA20")
    if sma50 is not None:
        signals.append("above SMA50" if close > sma50 else "below SMA50")
    if not signals:
        return None
    return "Price " + " & ".join(signals)


def _volume_signal(vol_z: Optional[float]) -> Optional[str]:
    if vol_z is None:
        return None
    if vol_z > 2.0:
        return f"Volume surge (z={vol_z:.1f}σ)"
    if vol_z < -1.5:
        return f"Volume dry-up (z={vol_z:.1f}σ)"
    return None


def _52w_signal(dist_high: Optional[float], dist_low: Optional[float]) -> Optional[str]:
    if dist_high is None:
        return None
    if dist_high >= -5:
        return f"Near 52-week high ({dist_high:+.1f}%)"
    if dist_low is not None and dist_low <= 10:
        return f"Near 52-week low (+{dist_low:.1f}% from low)"
    return None


def _interpret(feat: Dict[str, Any]) -> tuple[str, List[str]]:
    """Derive a summary sentence and signal list from raw feature dict."""
    signals: List[str] = []

    rsi_sig = _rsi_signal(feat.get("rsi14"))
    if rsi_sig:
        signals.append(rsi_sig)

    macd_sig = _macd_signal(feat.get("macd"), feat.get("macd_hist"))
    if macd_sig:
        signals.append(macd_sig)

    trend_sig = _trend_signal(feat.get("close"), feat.get("sma20"), feat.get("sma50"))
    if trend_sig:
        signals.append(trend_sig)

    vol_sig = _volume_signal(feat.get("vol_z20"))
    if vol_sig:
        signals.append(vol_sig)

    w52_sig = _52w_signal(feat.get("dist_52w_high_pct"), feat.get("dist_52w_low_pct"))
    if w52_sig:
        signals.append(w52_sig)

    if feat.get("pivot_breakout_flag"):
        signals.append("Pivot breakout today")

    # Overall bias
    bullish = sum(1 for s in signals if any(w in s for w in ["bullish", "above", "surge", "oversold", "high", "breakout"]))
    bearish = sum(1 for s in signals if any(w in s for w in ["bearish", "below", "dry-up", "overbought", "low"]))

    if bullish > bearish:
        bias = "Bullish bias"
    elif bearish > bullish:
        bias = "Bearish bias"
    else:
        bias = "Mixed/neutral"

    ret20 = feat.get("return_20d_pct")
    ret_str = f", 20d return {ret20:+.1f}%" if ret20 is not None else ""
    summary = f"{bias}{ret_str}. {len(signals)} signal(s) active."
    return summary, signals


async def get_technical_analysis(symbol: str) -> TechnicalResult:
    """Fetch and interpret the latest technical indicators for a stock.

    Primary tool for copilot agents answering questions like:
      "Is RELIANCE technically strong?"
      "What does the chart say about INFY?"
      "Should I buy TCS based on technicals?"
    """
    sym = symbol.upper().strip()
    try:
        feat = await get_stock_features_latest(sym)
    except DaasError as exc:
        logger.warning("technical_tool_daas_error symbol=%s error=%s", sym, exc)
        return TechnicalResult(symbol=sym, ok=False, summary="DAAS unavailable", error=str(exc))

    if not feat:
        return TechnicalResult(
            symbol=sym, ok=False,
            summary="No technical data available — stock may not be in NSE EQ series or data not yet computed",
            error="not_found",
        )

    summary, signals = _interpret(feat)
    return TechnicalResult(symbol=sym, ok=True, summary=summary, signals=signals, data=feat)


async def get_technical_comparison(symbols: List[str]) -> List[TechnicalResult]:
    """Fetch technical analysis for multiple symbols for side-by-side comparison.

    Used by: "Compare HDFC Bank vs ICICI Bank technically"
    """
    import asyncio
    results = await asyncio.gather(
        *[get_technical_analysis(s) for s in symbols],
        return_exceptions=True,
    )
    out = []
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception):
            out.append(TechnicalResult(symbol=sym.upper(), ok=False, summary="fetch error", error=str(res)))
        else:
            out.append(res)
    return out


async def get_momentum_screener(
    symbols: List[str],
    *,
    min_rsi: float = 40.0,
    max_rsi: float = 70.0,
    require_macd_positive: bool = False,
    min_return_20d: Optional[float] = None,
) -> List[TechnicalResult]:
    """Filter a list of symbols by technical momentum criteria.

    Used by: "Which of my holdings are technically strong right now?"
    """
    all_results = await get_technical_comparison(symbols)
    filtered = []
    for r in all_results:
        if not r.ok:
            continue
        d = r.data
        rsi = d.get("rsi14")
        if rsi is None or not (min_rsi <= rsi <= max_rsi):
            continue
        if require_macd_positive and (d.get("macd") is None or d["macd"] <= 0):
            continue
        if min_return_20d is not None:
            ret = d.get("return_20d_pct")
            if ret is None or ret < min_return_20d:
                continue
        filtered.append(r)

    # Sort by RSI descending (closer to 70 = stronger momentum)
    filtered.sort(key=lambda r: r.data.get("rsi14") or 0, reverse=True)
    return filtered


async def summarise_holding_technicals(
    symbol: str,
    quantity: float,
    avg_cost: float,
) -> Dict[str, Any]:
    """Combine holding cost basis with live technicals for a portfolio holding.

    Returns a rich dict suitable for widget rendering:
    {
      symbol, quantity, avg_cost, current_price, unrealised_pnl_pct,
      rsi14, macd, trend, signals, summary, risk_flag
    }
    """
    result = await get_technical_analysis(symbol)
    current = result.data.get("close") if result.ok else None

    pnl_pct = None
    if current and avg_cost and avg_cost > 0:
        pnl_pct = (current - avg_cost) / avg_cost * 100

    risk_flag = None
    if result.ok:
        rsi = result.data.get("rsi14")
        macd_val = result.data.get("macd")
        if rsi and rsi > 70:
            risk_flag = "overbought"
        elif rsi and rsi < 30:
            risk_flag = "oversold"
        elif macd_val is not None and macd_val < 0 and pnl_pct and pnl_pct < -10:
            risk_flag = "downtrend_with_loss"

    return {
        "symbol": symbol,
        "quantity": quantity,
        "avg_cost": avg_cost,
        "current_price": current,
        "unrealised_pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "rsi14": result.data.get("rsi14") if result.ok else None,
        "macd": result.data.get("macd") if result.ok else None,
        "sma20": result.data.get("sma20") if result.ok else None,
        "sma50": result.data.get("sma50") if result.ok else None,
        "return_20d_pct": result.data.get("return_20d_pct") if result.ok else None,
        "vol_z20": result.data.get("vol_z20") if result.ok else None,
        "signals": result.signals,
        "summary": result.summary,
        "risk_flag": risk_flag,
        "data_available": result.ok,
    }
