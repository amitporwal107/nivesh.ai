"""Stock / Mutual-Fund research tool for the Nivesh Copilot.

Given a single instrument (stock symbol OR MF scheme code) this composes the
NIDP DaaS layers into ONE deterministic `instrument_detail` widget payload —
the same shape the V5 chat widget (`ChatWidget.tsx` → InstrumentDetailWidget)
renders — plus a compact `summary` line for LLM grounding.

Design rules (CONTEXT.md):
  * Reuse existing copilot_tools / daas_client calls — no parallel calculators.
  * Every value is read straight from DaaS. A field that DaaS does not return is
    OMITTED from the widget, never invented or defaulted to a fake number.
  * The builder functions are pure (dict in → dict out) so they unit-test
    without any network.

Public API:
    get_stock_research(symbol)      → InstrumentResearch
    get_mf_research(scheme_code)    → InstrumentResearch
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import daas_client as _daas

logger = logging.getLogger(__name__)

_SOURCE = "NIDP DaaS"


@dataclass
class InstrumentResearch:
    ok: bool
    kind: str                       # "stock" | "mf"
    identifier: str                 # symbol or scheme_code
    summary: str                    # compact LLM-context line
    widget: Dict[str, Any] = field(default_factory=dict)   # instrument_detail data
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"INSTRUMENT_RESEARCH {self.kind}={self.identifier} status=unavailable reason={self.error}"
        return f"INSTRUMENT_RESEARCH {self.kind}={self.identifier} | {self.summary}"


# ── small formatting helpers ────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick(d: Dict[str, Any], *keys: str) -> Optional[float]:
    """First non-null numeric value among the candidate keys (schema drift safe)."""
    for k in keys:
        v = _num(d.get(k))
        if v is not None:
            return v
    return None


def _ratio(v: Any) -> Optional[float]:
    """A valuation ratio (P/E, P/B, D/E) is only meaningful when > 0. NIDP returns
    a literal 0.0 when the underlying input is missing, so treat 0/negative as
    'not available' rather than render a misleading 0.00."""
    n = _num(v)
    return n if (n is not None and n > 0) else None


def _money(v: Optional[float], decimals: int = 2) -> Optional[str]:
    if v is None:
        return None
    return f"₹{v:,.{decimals}f}"


def _pct(v: Optional[float], signed: bool = False, decimals: int = 1) -> Optional[str]:
    if v is None:
        return None
    return f"{v:+.{decimals}f}%" if signed else f"{v:.{decimals}f}%"


def _quality_label_tone(score: Optional[float], band: Optional[str] = None) -> tuple[str, str]:
    """Map a 0-100 score to a (label, tone) pair. tone ∈ {pos, warm, neg}."""
    if score is None:
        return ("—", "warm")
    if score >= 75:
        return ("Strong", "pos")
    if score >= 60:
        return ("Good", "warm")
    if score >= 45:
        return ("Average", "warm")
    return ("Weak", "neg")


def _row(label: str, value: Optional[str], tone: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    r: Dict[str, Any] = {"label": label, "value": value}
    if tone:
        r["tone"] = tone
    return r


def _compact(rows: List[Optional[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r is not None]


# ── STOCK ───────────────────────────────────────────────────────────────────

def build_stock_widget(symbol: str, feat: Dict[str, Any], scores: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble the instrument_detail widget for a stock. Pure function.

    `feat`  : /v1/features/stocks/{symbol}/latest .data  (technical + fundamental)
    `scores`: /v1/stocks/scores/{symbol} .data           (quality + sector rank)
    """
    feat = feat or {}
    scores = scores or {}
    sym = symbol.upper()

    sector = feat.get("sector") or scores.get("sector")
    industry = feat.get("industry") or scores.get("industry")
    meta = " · ".join([x for x in (sector, industry) if x]) or None

    # Price + 1-day change (omit change if no prior close to compute it).
    close = _pick(feat, "close", "close_price", "last_price")
    prev = _pick(feat, "prev_close", "previous_close")
    change_pct = _pick(feat, "day_change_pct", "pct_change", "change_pct")
    change_positive = None
    if change_pct is None and close is not None and prev:
        change_pct = (close - prev) / prev * 100
    if change_pct is not None:
        change_positive = change_pct >= 0

    widget: Dict[str, Any] = {
        "kind": "stock",
        "name": feat.get("company_name") or feat.get("name") or scores.get("company_name") or sym,
        "badge": "STOCK",
        "subtitle": f"{sym} · NSE",
        "meta": meta,
        "source": _SOURCE,
        "actions": [{"label": "Compare peers"}, {"label": "1-year chart"}],
    }
    if close is not None:
        widget["price"] = {
            "label": "Last price",
            "value": _money(close),
            "change": _pct(change_pct, signed=True, decimals=2) if change_pct is not None else None,
            "change_positive": change_positive,
        }

    # Quality score (persisted V3) + sector rank (migration 086).
    q_score = _pick(scores, "quality_score", "final_score")
    if q_score is not None:
        label, tone = _quality_label_tone(q_score, scores.get("band"))
        widget["quality"] = {"score": int(round(q_score)), "label": label, "tone": tone}

    rank = _pick(scores, "sector_rank")
    size = _pick(scores, "sector_size")
    if rank is not None and size:
        caption = f"Top {math.ceil(rank / size * 100)}% in {sector}" if sector else f"Top {math.ceil(rank / size * 100)}%"
        widget["rank"] = {"value": int(rank), "of": int(size), "label": "Sector rank", "caption": caption}

    # Fundamental analysis. P/E, P/B, D/E omit when not > 0 (NIDP returns 0.0
    # for a missing input — rendering "0.00" would be a false reading).
    pe, pb, de = _ratio(feat.get("pe_ttm")), _ratio(feat.get("pb")), _ratio(feat.get("debt_to_equity"))
    f_rows = _compact([
        _row("P / E", f"{pe:.1f}" if pe is not None else None),
        _row("P / B", f"{pb:.2f}" if pb is not None else None),
        _row("ROE", _pct(_num(feat.get("roe_pct")))),
        _row("Debt / equity", f"{de:.2f}" if de is not None else None),
        _row("Revenue growth (YoY)", _pct(_pick(feat, "revenue_growth_yoy_pct"), signed=True)),
        _row("Net margin", _pct(_pick(feat, "profit_margin_pct", "net_margin_pct"))),
    ])
    if f_rows:
        f_score = _pick(scores, "fundamental_score")
        piotroski = _num(feat.get("piotroski_score"))
        f_badge = None
        if f_score is not None:
            lbl, tone = ("Fundamentally strong", "pos") if f_score >= 65 else (("Above average", "warm") if f_score >= 50 else ("Below average", "neg"))
            f_badge = {"text": lbl, "tone": tone}
        elif piotroski is not None:
            lbl, tone = ("Fundamentally strong", "pos") if piotroski >= 6 else (("Above average", "warm") if piotroski >= 4 else ("Below average", "neg"))
            f_badge = {"text": lbl, "tone": tone}
        widget["fundamental"] = {"rows": f_rows}
        if f_badge:
            widget["fundamental"]["badge"] = f_badge

    # Technical analysis.
    rsi = _pick(feat, "rsi14", "rsi_14")
    sma50 = _pick(feat, "sma50", "sma_50")
    sma200 = _pick(feat, "sma200", "sma_200")
    macd = _pick(feat, "macd")
    macd_hist = _pick(feat, "macd_hist")
    support = _pick(feat, "swing_low_20", "support")
    resistance = _pick(feat, "swing_high_20", "resistance")

    macd_val = macd_tone = None
    if macd is not None:
        if macd > 0:
            macd_val = "Bullish crossover" if (macd_hist is not None and macd_hist > 0) else "Bullish"
            macd_tone = "pos"
        elif macd < 0:
            macd_val, macd_tone = "Bearish", "neg"
        else:
            macd_val = "Neutral"

    t_rows = _compact([
        _row("RSI (14)", f"{rsi:.1f}" if rsi is not None else None),
        _row("50-day MA", _money(sma50, 0)),
        _row("200-day MA", _money(sma200, 0)),
        _row("MACD", macd_val, macd_tone),
        _row("Support", _money(support, 0)),
        _row("Resistance", _money(resistance, 0)),
    ])
    if t_rows:
        # Simple bullish/bearish bias from price-vs-MA, RSI and MACD.
        bull = bear = 0
        if close is not None and sma50 is not None:
            bull += close > sma50
            bear += close < sma50
        if close is not None and sma200 is not None:
            bull += close > sma200
            bear += close < sma200
        if macd is not None:
            bull += macd > 0
            bear += macd < 0
        if rsi is not None and rsi >= 70:
            bear += 1
        t_label, t_tone = ("Bullish", "pos") if bull > bear else (("Bearish", "neg") if bear > bull else ("Neutral", "warm"))
        widget["technical"] = {"badge": {"text": t_label, "tone": t_tone}, "rows": t_rows}

    return widget


def _stock_summary(symbol: str, w: Dict[str, Any]) -> str:
    parts = [symbol.upper()]
    q = w.get("quality")
    if q:
        parts.append(f"quality={q['score']}/100 ({q['label']})")
    r = w.get("rank")
    if r:
        parts.append(f"sector_rank=#{r['value']}/{r['of']}")
    if w.get("fundamental", {}).get("badge"):
        parts.append(f"fundamentals={w['fundamental']['badge']['text']}")
    if w.get("technical", {}).get("badge"):
        parts.append(f"technicals={w['technical']['badge']['text']}")
    return " | ".join(parts)


async def get_stock_research(symbol: str) -> InstrumentResearch:
    """Fetch + assemble the full research card for a stock."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return InstrumentResearch(ok=False, kind="stock", identifier="", summary="", error="no_symbol")
    import asyncio
    try:
        feat, scores = await asyncio.gather(
            _daas.get_stock_features_latest(sym),
            _daas.get_stock_scores(sym),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        return InstrumentResearch(ok=False, kind="stock", identifier=sym, summary="", error=str(exc))

    feat = feat if isinstance(feat, dict) else None
    scores = scores if isinstance(scores, dict) else None
    if not feat and not scores:
        return InstrumentResearch(
            ok=False, kind="stock", identifier=sym,
            summary=f"No research data available for {sym}", error="not_found",
        )

    widget = build_stock_widget(sym, feat or {}, scores)
    ok = bool(widget.get("quality") or widget.get("fundamental") or widget.get("technical"))
    return InstrumentResearch(
        ok=ok, kind="stock", identifier=sym,
        summary=_stock_summary(sym, widget), widget=widget,
        error=None if ok else "insufficient_data",
    )


# ── MUTUAL FUND ─────────────────────────────────────────────────────────────

def build_mf_widget(scheme_code: str, sc: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble the instrument_detail widget for an MF scheme. Pure function.

    `sc`: /v1/mf/performance/scorecard/{scheme_code} .data (nidp.v_mf_category_scorecard)
    """
    sc = sc or {}
    name = sc.get("scheme_name") or sc.get("name") or f"Scheme {scheme_code}"
    category = sc.get("sub_category") or sc.get("fund_category") or sc.get("category")
    plan = sc.get("plan_type") or sc.get("scheme_type")
    subtitle = " · ".join([x for x in (sc.get("fund_category"), sc.get("sub_category"), plan) if x]) or category
    amc = sc.get("amc_name") or sc.get("amc")
    benchmark = sc.get("benchmark") or sc.get("benchmark_index")
    meta = " · ".join([x for x in (amc, f"Benchmark: {benchmark}" if benchmark else None) if x]) or None

    widget: Dict[str, Any] = {
        "kind": "mf",
        "name": name,
        "badge": "MUTUAL FUND",
        "subtitle": subtitle,
        "meta": meta,
        "source": _SOURCE,
        "actions": [{"label": "Compare category"}, {"label": "Holdings"}, {"label": "SIP returns"}],
        "disclaimer": (
            "Mutual fund investments are subject to market risks. Read all scheme-related "
            "documents carefully. Past performance does not guarantee future returns. "
            "This is not investment advice."
        ),
    }

    nav = _pick(sc, "nav", "latest_nav")
    nav_change = _pick(sc, "nav_change_pct", "day_change_pct")
    if nav is not None:
        widget["price"] = {
            "label": "NAV",
            "value": _money(nav),
            "change": _pct(nav_change, signed=True, decimals=2) if nav_change is not None else None,
            "change_positive": (nav_change >= 0) if nav_change is not None else None,
        }

    # Quality score + category rank. Derive label AND tone from the score so
    # they never disagree (NIDP's own quality_label has drifted from the score
    # for some schemes — e.g. "Weak" at 56).
    q_score = _pick(sc, "composite_score", "quality_score")
    if q_score is not None:
        label, tone = _quality_label_tone(q_score)
        widget["quality"] = {"score": int(round(q_score)), "label": label, "tone": tone}

    rank = _pick(sc, "composite_rank", "category_rank")
    size = _pick(sc, "total_in_category", "category_size")
    if rank is not None and size:
        cap_cat = sc.get("sub_category") or sc.get("fund_category") or "category"
        caption = f"Top {math.ceil(rank / size * 100)}% in {cap_cat}"
        widget["rank"] = {"value": int(rank), "of": int(size), "label": "Category rank", "caption": caption}

    # Trailing returns (CAGR).
    returns = _compact([
        _row("1Y", _pct(_pick(sc, "return_1y", "ret_1y", "ret1y"))),
        _row("3Y", _pct(_pick(sc, "return_3y", "ret_3y", "ret3y"))),
        _row("5Y", _pct(_pick(sc, "return_5y", "ret_5y", "ret5y"))),
    ])
    si = _pct(_pick(sc, "return_since_inception", "return_since_launch_cagr", "since_inception_cagr"))
    if si is not None:
        returns.append({"label": "Since inception", "value": si, "muted": True})
    if returns:
        widget["returns"] = returns

    # Fundamental analysis (fund characteristics).
    aum = _pick(sc, "aum_cr", "aum")
    f_rows = _compact([
        _row("Expense ratio", _pct(_pick(sc, "ter", "ter_pct", "expense_ratio"), decimals=2)),
        _row("AUM", f"₹{aum:,.0f} Cr" if aum is not None else None),
        _row("Exit load", sc.get("exit_load_text") or (_pct(_pick(sc, "exit_load_pct")) if _pick(sc, "exit_load_pct") is not None else None)),
        _row("Portfolio turnover", _pct(_pick(sc, "portfolio_turnover_pct", "turnover_pct"), decimals=0)),
        _row("Portfolio P/E", f"{_pick(sc, 'portfolio_pe'):.1f}" if _pick(sc, "portfolio_pe") is not None else None),
        _row("Top-10 holdings", _pct(_pick(sc, "top10_weight_pct", "top_10_pct"), decimals=0)),
    ])
    if f_rows:
        widget["fundamental"] = {"rows": f_rows}
        qtr = _pick(sc, "qtile_ret3y", "qtile_ret1y")
        if qtr is not None:
            lbl, tone = ("Above average", "warm") if qtr <= 2 else ("Below average", "neg")
            if qtr == 1:
                lbl, tone = "Top quartile", "pos"
            widget["fundamental"]["badge"] = {"text": lbl, "tone": tone}

    # Technical analysis (NAV-based). Only real NAV indicators + max drawdown —
    # we deliberately DON'T synthesise a "vs benchmark" row from alpha_1y, whose
    # values in the scorecard are unreliable (observed -42% on a large-cap fund).
    t_rows = _compact([
        _row("NAV trend", sc.get("nav_trend"), "pos" if (sc.get("nav_trend") or "").lower().startswith("up") else None),
        _row("50-day MA", _money(_pick(sc, "nav_sma50", "sma50"))),
        _row("200-day MA", _money(_pick(sc, "nav_sma200", "sma200"))),
        _row("RSI (14, NAV)", f"{_pick(sc, 'nav_rsi14', 'rsi14'):.1f}" if _pick(sc, "nav_rsi14", "rsi14") is not None else None),
        _row("Max drawdown (1Y)", _pct(_pick(sc, "max_drawdown_1y", "maxdd_1y")), "neg"),
    ])
    if t_rows:
        widget["technical"] = {"title": "Technical analysis (NAV)", "rows": t_rows}

    # Risk & ratios.
    r_items = _compact([
        _row("Alpha", f"{_pick(sc, 'alpha_3y', 'alpha'):.1f}" if _pick(sc, "alpha_3y", "alpha") is not None else None),
        _row("Beta", f"{_pick(sc, 'beta_3y', 'beta'):.2f}" if _pick(sc, "beta_3y", "beta") is not None else None),
        _row("Sharpe", f"{_pick(sc, 'sharpe_3y', 'sharpe_1y', 'sharpe'):.2f}" if _pick(sc, "sharpe_3y", "sharpe_1y", "sharpe") is not None else None),
        _row("Sortino", f"{_pick(sc, 'sortino_3y', 'sortino_1y', 'sortino'):.2f}" if _pick(sc, "sortino_3y", "sortino_1y", "sortino") is not None else None),
        _row("Std dev", _pct(_pick(sc, "std_dev_3y", "volatility_1y", "std_dev"))),
    ])
    if r_items:
        widget["ratios"] = {"title": "Risk & ratios", "items": r_items}

    return widget


def _mf_summary(scheme_code: str, w: Dict[str, Any]) -> str:
    parts = [w.get("name") or str(scheme_code)]
    q = w.get("quality")
    if q:
        parts.append(f"quality={q['score']}/100 ({q['label']})")
    r = w.get("rank")
    if r:
        parts.append(f"category_rank=#{r['value']}/{r['of']}")
    rets = {x["label"]: x["value"] for x in w.get("returns", [])}
    if rets.get("1Y"):
        parts.append(f"1Y={rets['1Y']}")
    return " | ".join(parts)


async def get_mf_research(scheme_code: str) -> InstrumentResearch:
    """Fetch + assemble the full research card for an MF scheme."""
    code = str(scheme_code or "").strip()
    if not code:
        return InstrumentResearch(ok=False, kind="mf", identifier="", summary="", error="no_scheme_code")
    try:
        sc = await _daas.get_mf_scorecard(code)
    except Exception as exc:  # noqa: BLE001
        return InstrumentResearch(ok=False, kind="mf", identifier=code, summary="", error=str(exc))

    if not sc:
        return InstrumentResearch(
            ok=False, kind="mf", identifier=code,
            summary=f"No research data available for scheme {code}", error="not_found",
        )

    widget = build_mf_widget(code, sc)
    ok = bool(widget.get("quality") or widget.get("returns") or widget.get("fundamental"))
    return InstrumentResearch(
        ok=ok, kind="mf", identifier=code,
        summary=_mf_summary(code, widget), widget=widget,
        error=None if ok else "insufficient_data",
    )
