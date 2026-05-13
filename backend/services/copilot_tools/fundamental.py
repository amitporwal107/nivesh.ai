"""Fundamental analysis tools for the Nivesh Copilot.

Wraps DAAS API calls + local signal interpretation for:
  - Single-stock fundamental analysis (PE, PB, ROE, D/E, growth, Piotroski, Altman)
  - Sector peer comparison (TASK-023)
  - Valuation signal (TASK-024)
  - Multi-stock screening by fundamental quality

All functions return structured dicts / FundamentalResult objects that
the RAG orchestrator and (future) LangGraph agents consume identically.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .daas_client import DaasError, get_stock_features_latest, get_stock_fundamentals

logger = logging.getLogger(__name__)


@dataclass
class FundamentalResult:
    symbol: str
    ok: bool
    summary: str
    signals: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"FUNDAMENTAL_ANALYSIS symbol={self.symbol} status=unavailable reason={self.error}"
        d = self.data
        parts = [f"FUNDAMENTAL_ANALYSIS symbol={self.symbol}"]
        if d.get("pe_ttm") is not None:
            parts.append(f"PE={d['pe_ttm']:.1f}")
        if d.get("pb") is not None:
            parts.append(f"PB={d['pb']:.2f}")
        if d.get("roe_pct") is not None:
            parts.append(f"ROE={d['roe_pct']:.1f}%")
        if d.get("debt_to_equity") is not None:
            parts.append(f"D/E={d['debt_to_equity']:.2f}")
        if d.get("revenue_growth_yoy_pct") is not None:
            parts.append(f"rev_growth={d['revenue_growth_yoy_pct']:+.1f}%")
        if d.get("pat_growth_yoy_pct") is not None:
            parts.append(f"pat_growth={d['pat_growth_yoy_pct']:+.1f}%")
        if d.get("piotroski_score") is not None:
            parts.append(f"piotroski={d['piotroski_score']}/9")
        if d.get("altman_z_score") is not None:
            parts.append(f"altman_z={d['altman_z_score']:.2f}")
        if d.get("valuation_signal"):
            parts.append(f"valuation={d['valuation_signal']}")
        if d.get("sector_median_pe") is not None and d.get("pe_ttm") is not None:
            parts.append(f"sector_median_pe={d['sector_median_pe']:.1f}")
        parts.append(f"signals=[{'; '.join(self.signals[:4])}]")
        parts.append(f"summary={self.summary}")
        return " | ".join(parts)


# ── Signal interpretation ────────────────────────────────────────────

def _pe_signal(pe: Optional[float], sector_median: Optional[float]) -> Optional[str]:
    if pe is None:
        return None
    if pe <= 0:
        return f"PE negative (loss-making)"
    base = f"PE {pe:.1f}x"
    if sector_median and sector_median > 0:
        pct = (pe / sector_median - 1) * 100
        if pct < -25:
            return f"{base} — {abs(pct):.0f}% discount to sector median {sector_median:.1f}x"
        if pct > 35:
            return f"{base} — {pct:.0f}% premium to sector median {sector_median:.1f}x"
        return f"{base} — in line with sector median {sector_median:.1f}x"
    return base


def _roe_signal(roe: Optional[float]) -> Optional[str]:
    if roe is None:
        return None
    if roe >= 20:
        return f"ROE {roe:.1f}% — high quality returns"
    if roe >= 12:
        return f"ROE {roe:.1f}% — acceptable"
    if roe >= 0:
        return f"ROE {roe:.1f}% — below threshold (>12% preferred)"
    return f"ROE {roe:.1f}% — negative"


def _de_signal(de: Optional[float]) -> Optional[str]:
    if de is None:
        return None
    if de <= 0.3:
        return f"D/E {de:.2f} — low leverage"
    if de <= 1.0:
        return f"D/E {de:.2f} — moderate leverage"
    return f"D/E {de:.2f} — high leverage"


def _growth_signal(rev_g: Optional[float], pat_g: Optional[float]) -> Optional[str]:
    parts = []
    if rev_g is not None:
        parts.append(f"revenue {rev_g:+.1f}%")
    if pat_g is not None:
        parts.append(f"PAT {pat_g:+.1f}%")
    if not parts:
        return None
    label = "YoY growth:"
    if rev_g is not None and rev_g > 15:
        label = "Strong YoY growth:"
    elif pat_g is not None and pat_g < 0:
        label = "Declining profit:"
    return f"{label} {', '.join(parts)}"


def _piotroski_signal(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    labels = {(0, 2): "weak", (3, 5): "average", (6, 7): "good", (8, 9): "strong"}
    label = next((v for (lo, hi), v in labels.items() if lo <= score <= hi), "unknown")
    return f"Piotroski {score}/9 — fundamental quality {label}"


def _altman_signal(z: Optional[float]) -> Optional[str]:
    if z is None:
        return None
    if z > 2.99:
        return f"Altman Z {z:.2f} — safe zone (no near-term distress)"
    if z > 1.81:
        return f"Altman Z {z:.2f} — grey zone (monitor)"
    return f"Altman Z {z:.2f} — distress zone (elevated risk)"


def _shareholding_signals(feat: Dict[str, Any]) -> list[str]:
    signals = []
    promoter = feat.get("promoter_pct")
    promoter_pledge = feat.get("promoter_pledged_pct")
    fii_chg = feat.get("fii_pct_change_qoq")
    dii_chg = feat.get("dii_pct_change_qoq")

    if promoter is not None:
        if promoter >= 60:
            signals.append(f"High promoter holding {promoter:.1f}%")
        elif promoter < 30:
            signals.append(f"Low promoter holding {promoter:.1f}%")

    if promoter_pledge is not None and promoter_pledge > 20:
        signals.append(f"High promoter pledge {promoter_pledge:.1f}% — risk")

    if fii_chg is not None:
        if fii_chg > 1.0:
            signals.append(f"FII buying (+{fii_chg:.1f}pp QoQ)")
        elif fii_chg < -1.0:
            signals.append(f"FII selling ({fii_chg:.1f}pp QoQ)")

    if dii_chg is not None:
        if dii_chg > 1.0:
            signals.append(f"DII buying (+{dii_chg:.1f}pp QoQ)")

    return signals


def _interpret_fundamental(feat: Dict[str, Any]) -> tuple[str, List[str]]:
    signals: list[str] = []

    pe_sig = _pe_signal(feat.get("pe_ttm"), feat.get("sector_median_pe"))
    if pe_sig:
        signals.append(pe_sig)

    roe_sig = _roe_signal(feat.get("roe_pct"))
    if roe_sig:
        signals.append(roe_sig)

    de_sig = _de_signal(feat.get("debt_to_equity"))
    if de_sig:
        signals.append(de_sig)

    g_sig = _growth_signal(feat.get("revenue_growth_yoy_pct"), feat.get("pat_growth_yoy_pct"))
    if g_sig:
        signals.append(g_sig)

    p_sig = _piotroski_signal(feat.get("piotroski_score"))
    if p_sig:
        signals.append(p_sig)

    a_sig = _altman_signal(feat.get("altman_z_score"))
    if a_sig:
        signals.append(a_sig)

    signals.extend(_shareholding_signals(feat))

    # Overall verdict
    val_signal = feat.get("valuation_signal") or "unknown"
    piotroski = feat.get("piotroski_score")
    roe = feat.get("roe_pct")

    quality = "unknown"
    if piotroski is not None:
        if piotroski >= 6:
            quality = "good"
        elif piotroski <= 2:
            quality = "weak"
        else:
            quality = "average"

    growth_str = ""
    pat_g = feat.get("pat_growth_yoy_pct")
    if pat_g is not None:
        growth_str = f", PAT growth {pat_g:+.1f}%"

    summary = f"Fundamentals: {quality} quality, {val_signal} valuation{growth_str}."
    return summary, signals


# ── Public tool functions ────────────────────────────────────────────

async def get_fundamental_analysis(symbol: str) -> FundamentalResult:
    """Fetch and interpret fundamental metrics for a stock.

    Covers: PE, PB, ROE, D/E, growth, Piotroski, Altman Z, valuation signal,
    shareholding (promoter, FII/DII trends).

    Primary tool for queries like:
      "Is RELIANCE fundamentally strong?"
      "Is INFY undervalued?"
      "What is the Piotroski score for TCS?"
    """
    sym = symbol.upper().strip()
    try:
        feat = await get_stock_features_latest(sym)
    except DaasError as exc:
        logger.warning("fundamental_tool_daas_error symbol=%s error=%s", sym, exc)
        return FundamentalResult(symbol=sym, ok=False, summary="DAAS unavailable", error=str(exc))

    if not feat:
        return FundamentalResult(
            symbol=sym, ok=False,
            summary="No fundamental data — financials may not be filed or synced yet",
            error="not_found",
        )

    # Check if fundamentals have been populated (PE is the canary)
    if feat.get("pe_ttm") is None and feat.get("piotroski_score") is None:
        return FundamentalResult(
            symbol=sym, ok=False,
            summary="Fundamental engine has not yet run for this stock (PE and Piotroski score both NULL)",
            error="not_computed",
        )

    summary, signals = _interpret_fundamental(feat)
    return FundamentalResult(symbol=sym, ok=True, summary=summary, signals=signals, data=feat)


async def get_valuation_metrics(symbol: str) -> Dict[str, Any]:
    """Return just the valuation-focused metrics for a symbol.

    Used by agents answering: "Is X overvalued?", "What's the PE of Y?"
    Returns: {symbol, pe_ttm, pb, sector, sector_median_pe, valuation_signal, roe_pct}
    """
    sym = symbol.upper().strip()
    try:
        feat = await get_stock_features_latest(sym)
    except DaasError as exc:
        return {"symbol": sym, "error": str(exc)}

    if not feat:
        return {"symbol": sym, "error": "not_found"}

    return {
        "symbol": sym,
        "close": feat.get("close"),
        "pe_ttm": feat.get("pe_ttm"),
        "pb": feat.get("pb"),
        "roe_pct": feat.get("roe_pct"),
        "sector": feat.get("sector"),
        "sector_median_pe": feat.get("sector_median_pe"),
        "valuation_signal": feat.get("valuation_signal"),
        "latest_quarter_end": str(feat.get("latest_quarter_end") or ""),
    }


async def get_fundamental_comparison(symbols: List[str]) -> List[FundamentalResult]:
    """Fundamental analysis for multiple symbols — for peer comparison queries."""
    import asyncio
    results = await asyncio.gather(
        *[get_fundamental_analysis(s) for s in symbols],
        return_exceptions=True,
    )
    out = []
    for sym, res in zip(symbols, results):
        if isinstance(res, Exception):
            out.append(FundamentalResult(symbol=sym.upper(), ok=False, summary="fetch error", error=str(res)))
        else:
            out.append(res)
    return out


async def screen_by_fundamentals(
    symbols: List[str],
    *,
    min_roe: Optional[float] = None,
    max_pe: Optional[float] = None,
    max_de: Optional[float] = None,
    min_piotroski: Optional[int] = None,
    valuation: Optional[str] = None,
) -> List[FundamentalResult]:
    """Filter symbols by fundamental quality criteria.

    Used by: "Which of my holdings are fundamentally strong?"
             "Show me undervalued stocks from my portfolio"
    """
    all_results = await get_fundamental_comparison(symbols)
    filtered = []
    for r in all_results:
        if not r.ok:
            continue
        d = r.data
        if min_roe is not None and (d.get("roe_pct") is None or float(d["roe_pct"]) < min_roe):
            continue
        if max_pe is not None and d.get("pe_ttm") is not None:
            if float(d["pe_ttm"]) > max_pe:
                continue
        if max_de is not None and d.get("debt_to_equity") is not None:
            if float(d["debt_to_equity"]) > max_de:
                continue
        if min_piotroski is not None and (d.get("piotroski_score") is None or d["piotroski_score"] < min_piotroski):
            continue
        if valuation is not None and d.get("valuation_signal") != valuation:
            continue
        filtered.append(r)

    # Sort by Piotroski descending (best quality first)
    filtered.sort(key=lambda r: r.data.get("piotroski_score") or 0, reverse=True)
    return filtered
