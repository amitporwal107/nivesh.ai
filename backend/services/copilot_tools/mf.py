"""Mutual Fund tools for the Nivesh Copilot.

Wraps DAAS MF performance API calls + signal interpretation for:
  - Single-fund performance and risk metrics
  - Category leaderboard (top funds in a category)
  - Cross-category screener
  - Fund comparison side-by-side

All functions return structured dicts / MfResult objects for the
RAG orchestrator and (future) LangGraph agents.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .daas_client import DaasError, _get

logger = logging.getLogger(__name__)


@dataclass
class MfResult:
    scheme_code: str
    ok: bool
    summary: str
    signals: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"MF_ANALYSIS scheme={self.scheme_code} status=unavailable reason={self.error}"
        d = self.data
        parts = [f"MF scheme={self.scheme_code}"]
        if d.get("scheme_name"):
            parts.append(f"name={d['scheme_name']!r}")
        sub = d.get("sub_category") or d.get("category")
        if sub:
            parts.append(f"category={sub}")
        if d.get("return_1y") is not None:
            parts.append(f"ret_1y={float(d['return_1y']):+.1f}%")
        if d.get("return_3y") is not None:
            parts.append(f"ret_3y={float(d['return_3y']):+.1f}%")
        if d.get("return_5y") is not None:
            parts.append(f"ret_5y={float(d['return_5y']):+.1f}%")
        if d.get("sharpe_1y") is not None:
            parts.append(f"sharpe={float(d['sharpe_1y']):.2f}")
        if d.get("max_drawdown_1y") is not None:
            parts.append(f"maxdd={float(d['max_drawdown_1y']):.1f}%")
        # Scorecard fields (migration 052)
        if d.get("composite_score") is not None:
            parts.append(f"score={float(d['composite_score']):.0f}/100")
        if d.get("quality_label"):
            parts.append(f"label={d['quality_label']}")
        if d.get("composite_rank") and d.get("total_in_category"):
            pct = d.get("top_position_pct")
            pct_str = f" Top{pct}%" if pct else ""
            parts.append(f"rank=#{d['composite_rank']}/{d['total_in_category']}{pct_str}")
        elif d.get("composite_rank"):
            parts.append(f"rank=#{d['composite_rank']}")
        parts.append(f"summary={self.summary}")
        return " | ".join(parts)


# ── Signal interpretation ─────────────────────────────────────────────

def _return_signal(ret_1y: Optional[float], ret_3y: Optional[float], category: Optional[str]) -> Optional[str]:
    if ret_1y is None:
        return None
    qual = "strong" if ret_1y > 20 else "good" if ret_1y > 12 else "moderate" if ret_1y > 6 else "weak"
    r3_str = f", 3y CAGR {ret_3y:+.1f}%" if ret_3y is not None else ""
    return f"1y return {ret_1y:+.1f}% ({qual}){r3_str}"


def _risk_signal(vol: Optional[float], sharpe: Optional[float], maxdd: Optional[float]) -> Optional[str]:
    parts = []
    if vol is not None:
        risk_label = "low" if vol < 12 else "moderate" if vol < 20 else "high"
        parts.append(f"volatility {vol:.1f}% ({risk_label})")
    if sharpe is not None:
        sh_label = "excellent" if sharpe > 1.5 else "good" if sharpe > 1.0 else "average" if sharpe > 0.5 else "poor"
        parts.append(f"Sharpe {sharpe:.2f} ({sh_label})")
    if maxdd is not None:
        parts.append(f"max drawdown {maxdd:.1f}%")
    return ", ".join(parts) if parts else None


def _rank_signal(
    composite_rank: Optional[int],
    return_1y_rank: Optional[int],
    total_in_category: Optional[int],
    quality_label: Optional[str] = None,
    top_position_pct: Optional[int] = None,
) -> Optional[str]:
    if composite_rank is None:
        return None
    rank_str = f"#{composite_rank}"
    if total_in_category:
        rank_str += f"/{total_in_category}"
    label_str = f" [{quality_label}]" if quality_label else ""
    pct_str = f" — Top {top_position_pct}% in category" if top_position_pct else ""
    return f"Category rank {rank_str}{label_str}{pct_str}"


def _quartile_signals(d: Dict[str, Any]) -> List[str]:
    """Emit Q1/Q2/Q3/Q4 bullets for key metrics from scorecard data."""
    _LABELS = {1: "Q1 (top quartile)", 2: "Q2", 3: "Q3", 4: "Q4 (bottom quartile)"}
    _METRICS = [
        ("qtile_ret1y",      "1Y return"),
        ("qtile_ret3y",      "3Y return"),
        ("qtile_sharpe",     "Sharpe ratio"),
        ("qtile_maxdd",      "downside protection"),
        ("qtile_ter",        "expense ratio"),
        ("qtile_consistency","consistency"),
        ("qtile_dc",         "downside capture"),
    ]
    out = []
    for key, label in _METRICS:
        q = d.get(key)
        if q is not None:
            out.append(f"{label}: {_LABELS.get(int(q), str(q))}")
    return out


def _interpret_mf(d: Dict[str, Any]) -> tuple[str, List[str]]:
    signals = []

    r_sig = _return_signal(d.get("return_1y"), d.get("return_3y"), d.get("category"))
    if r_sig:
        signals.append(r_sig)

    risk_sig = _risk_signal(d.get("volatility_1y"), d.get("sharpe_1y"), d.get("max_drawdown_1y"))
    if risk_sig:
        signals.append(risk_sig)

    rank_sig = _rank_signal(
        d.get("composite_rank"),
        d.get("return_1y_rank"),
        d.get("total_in_category"),
        d.get("quality_label"),
        d.get("top_position_pct"),
    )
    if rank_sig:
        signals.append(rank_sig)

    if d.get("ter") is not None:
        ter = float(d["ter"])
        ter_label = "low-cost" if ter < 0.5 else "moderate-cost" if ter < 1.0 else "high-cost"
        signals.append(f"TER {ter:.2f}% ({ter_label})")

    if d.get("alpha_1y") is not None:
        a = float(d["alpha_1y"])
        signals.append(f"Alpha {a:+.2f}% vs Nifty 50 (1y)")

    # Quartile breakdown from scorecard (only when available)
    q_sigs = _quartile_signals(d)
    if q_sigs:
        signals.append("Quartile breakdown — " + "; ".join(q_sigs))

    # Derive quality from scorecard label or raw signals
    quality_label = d.get("quality_label")
    if quality_label:
        quality = quality_label.lower()
    else:
        ret_1y = d.get("return_1y")
        sharpe = d.get("sharpe_1y")
        if ret_1y is not None and sharpe is not None:
            if ret_1y > 15 and sharpe > 1.0:
                quality = "high-quality performer"
            elif ret_1y > 10 and sharpe > 0.5:
                quality = "solid performer"
            elif ret_1y < 0:
                quality = "underperformer"
            else:
                quality = "average performer"
        elif ret_1y is not None:
            quality = "strong" if ret_1y > 15 else "average" if ret_1y > 6 else "weak"
        else:
            quality = "insufficient data"

    rank_str = (
        f", ranked #{d['composite_rank']}/{d['total_in_category']}"
        if d.get("composite_rank") and d.get("total_in_category")
        else (f", ranked #{d['composite_rank']}" if d.get("composite_rank") else "")
    )
    sub = d.get("sub_category") or d.get("category", "unknown")
    summary = f"{quality}{rank_str} in {sub}."
    return summary, signals


# ── DAAS client helpers ───────────────────────────────────────────────

async def _get_scheme_scorecard(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Fetch full category scorecard (migration 052 view) — composite score,
    quality label, per-metric ranks and quartiles within sub-category."""
    try:
        data = await _get(f"/mf/performance/scorecard/{scheme_code}")
        return data.get("data") if data else None
    except DaasError as exc:
        logger.debug("mf_scorecard_unavailable scheme=%s error=%s", scheme_code, exc)
        return None


async def _get_scheme_performance(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Fetch raw performance row from analytics.fund_category_rank."""
    try:
        data = await _get(f"/mf/performance/{scheme_code}")
        return data.get("data") if data else None
    except DaasError as exc:
        logger.warning("mf_perf_daas_error scheme=%s error=%s", scheme_code, exc)
        return None


async def _get_scheme_data(scheme_code: str) -> Optional[Dict[str, Any]]:
    """Try scorecard first (richer), fall back to plain performance row."""
    sc = await _get_scheme_scorecard(scheme_code)
    if sc:
        return sc
    return await _get_scheme_performance(scheme_code)


async def _get_category_top(category: str, metric: str = "composite_rank", limit: int = 10) -> List[Dict[str, Any]]:
    try:
        data = await _get(
            f"/mf/performance/category/{category}",
            params={"metric": metric, "limit": limit},
        )
        return data.get("data", []) if data else []
    except DaasError as exc:
        logger.warning("mf_category_daas_error category=%s error=%s", category, exc)
        return []


# ── Public tool functions ─────────────────────────────────────────────

async def get_mf_scorecard(scheme_code: str) -> MfResult:
    """Fetch the full category scorecard for a scheme.

    Returns composite score (0-100), quality label, per-metric ranks and
    quartile positions within the sub-category peer group.
    Used for: "Is HDFC Top 100 in the top quartile?", "What's the category rank
    of Parag Parikh Flexi Cap?", "How does this fund compare to peers?"
    """
    data = await _get_scheme_scorecard(scheme_code)
    if not data:
        return MfResult(
            scheme_code=scheme_code, ok=False,
            summary="Scorecard not available — analytics may not have run yet",
            error="scorecard_not_found",
        )
    summary, signals = _interpret_mf(data)
    return MfResult(scheme_code=scheme_code, ok=True, summary=summary, signals=signals, data=data)


async def get_mf_performance(scheme_code: str) -> MfResult:
    """Fetch and interpret performance metrics for a single MF scheme.

    Used for: "How is Mirae Asset Large Cap doing?", "What is the Sharpe ratio of HDFC Top 100?"
    Automatically uses the richer scorecard data (composite score, quality label,
    quartile rankings) when available, falling back to plain performance metrics.
    """
    data = await _get_scheme_data(scheme_code)
    if not data:
        return MfResult(
            scheme_code=scheme_code, ok=False,
            summary="No performance data — scheme may not be in our DB or analytics not yet computed",
            error="not_found",
        )
    summary, signals = _interpret_mf(data)
    return MfResult(scheme_code=scheme_code, ok=True, summary=summary, signals=signals, data=data)


async def get_top_funds(
    category: str,
    metric: str = "composite_rank",
    limit: int = 5,
) -> List[MfResult]:
    """Return top-N funds in a category ranked by selected metric.

    Used for: "Best large cap funds", "Top equity funds by Sharpe ratio"

    Args:
        category: e.g. "Equity", "Large Cap", "Debt", "Hybrid"
        metric:   "composite_rank" | "return_1y" | "return_3y" | "sharpe_1y"
        limit:    number of funds to return
    """
    rows = await _get_category_top(category, metric=metric, limit=limit)
    results = []
    for d in rows:
        summary, signals = _interpret_mf(d)
        results.append(MfResult(
            scheme_code=d.get("scheme_code", ""),
            ok=True, summary=summary, signals=signals, data=d,
        ))
    return results


async def compare_funds(scheme_codes: List[str]) -> List[MfResult]:
    """Side-by-side performance comparison for multiple funds.

    Used for: "Compare Axis Bluechip vs Mirae Large Cap vs SBI Large Cap"
    """
    import asyncio
    raw_results = await asyncio.gather(
        *[_get_scheme_performance(code) for code in scheme_codes],
        return_exceptions=True,
    )
    out = []
    for code, data in zip(scheme_codes, raw_results):
        if isinstance(data, Exception) or not data:
            out.append(MfResult(scheme_code=code, ok=False, summary="fetch error", error=str(data)))
        else:
            summary, signals = _interpret_mf(data)
            out.append(MfResult(scheme_code=code, ok=True, summary=summary, signals=signals, data=data))
    return out


async def get_fund_overlap(scheme_codes: List[str]) -> Dict[str, Any]:
    """Compute equity holding overlap between two or more funds.

    Uses the existing DAAS /mf/holdings/overlap endpoint.
    Limited to pairwise (2 funds) in current implementation.

    Used for: "How much does SBI Bluechip overlap with HDFC Top 100?"
    """
    if len(scheme_codes) < 2:
        return {"error": "need at least 2 scheme codes", "overlap_pct": None}
    a, b = scheme_codes[0], scheme_codes[1]
    try:
        data = await _get(
            "/mf/holdings/overlap",
            params={"scheme_code_a": a, "scheme_code_b": b},
        )
        return data if data else {"error": "not_found"}
    except DaasError as exc:
        return {"error": str(exc), "overlap_pct": None}


async def screen_mf_by_quality(
    category: Optional[str] = None,
    *,
    min_return_1y: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    max_drawdown: Optional[float] = None,
    max_ter: Optional[float] = None,
    limit: int = 10,
) -> List[MfResult]:
    """Screen funds meeting quality criteria.

    Used for: "Show me debt funds with Sharpe > 1.0 and TER < 0.5%"
    """
    try:
        params: Dict[str, Any] = {"limit": 50}  # fetch more, then filter
        if category:
            url = f"/mf/performance/category/{category}"
        else:
            url = "/mf/performance/screener/top"
            params["metric"] = "sharpe_1y"

        data = await _get(url, params=params)
        rows = data.get("data", []) if data else []
    except DaasError as exc:
        logger.warning("mf_screen_daas_error error=%s", exc)
        return []

    filtered = []
    for d in rows:
        if min_return_1y is not None and (d.get("return_1y") is None or float(d["return_1y"]) < min_return_1y):
            continue
        if min_sharpe is not None and (d.get("sharpe_1y") is None or float(d["sharpe_1y"]) < min_sharpe):
            continue
        if max_drawdown is not None and d.get("max_drawdown_1y") is not None:
            if float(d["max_drawdown_1y"]) < max_drawdown:  # max_drawdown is negative
                continue
        if max_ter is not None and d.get("ter") is not None:
            if float(d["ter"]) > max_ter:
                continue
        summary, signals = _interpret_mf(d)
        filtered.append(MfResult(
            scheme_code=d.get("scheme_code", ""),
            ok=True, summary=summary, signals=signals, data=d,
        ))
        if len(filtered) >= limit:
            break

    return filtered
