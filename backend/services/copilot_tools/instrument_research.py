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

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
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


def _nested(d: Any, *path: str) -> Any:
    """Safely walk a nested dict path; None if any hop is absent/non-dict.
    JSONB columns (e.g. quality_components) can arrive as JSON strings — parse
    those transparently so the walk still works."""
    cur = d
    for p in path:
        if isinstance(cur, str):
            try:
                cur = json.loads(cur)
            except (ValueError, TypeError):
                return None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


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

_CAP_LABELS = {
    "LARGE_CAP": "Large cap", "MID_CAP": "Mid cap", "SMALL_CAP": "Small cap", "MICRO_CAP": "Micro cap",
    "LARGE": "Large cap", "MID": "Mid cap", "SMALL": "Small cap", "MICRO": "Micro cap",
}


def _cap_label(feat: Dict[str, Any]) -> Optional[str]:
    raw = (feat.get("market_cap_bucket") or feat.get("cap_bucket") or "").strip().upper()
    return _CAP_LABELS.get(raw)


def _fmt_asof(raw: Any) -> Optional[str]:
    """Render the DaaS as_of_date as '19 Jun 2026'. EOD snapshot — no intraday time."""
    if not raw:
        return None
    s = str(raw)
    for cut in (19, 10):
        try:
            d = datetime.fromisoformat(s[:cut])
            return f"{d.day} {d.strftime('%b %Y')}"
        except ValueError:
            continue
    return None


def _join_clauses(items: List[Optional[str]]) -> str:
    xs = [i for i in items if i]
    if not xs:
        return ""
    if len(xs) == 1:
        return xs[0]
    if len(xs) == 2:
        return f"{xs[0]} and {xs[1]}"
    return ", ".join(xs[:-1]) + f" and {xs[-1]}"


def _fundamental_band(f_score: Optional[float], piotroski: Optional[float]) -> Optional[tuple[int, str, str]]:
    """Map the persisted fundamental score (0-100) to (score, label, tone). Falls
    back to scaling the Piotroski F-score (0-9) when no composite is present."""
    s = f_score
    if s is None and piotroski is not None:
        s = piotroski / 9 * 100
    if s is None:
        return None
    s = max(0.0, min(100.0, s))
    if s >= 75:
        lbl, tone = "Strong", "pos"
    elif s >= 58:
        lbl, tone = "Above average", "pos"
    elif s >= 45:
        lbl, tone = "Average", "warm"
    else:
        lbl, tone = "Below average", "neg"
    return int(round(s)), lbl, tone


def _technical_band(score: Optional[float]) -> Optional[tuple[int, str, str]]:
    """Map a real NIDP technical/health composite (0-100) to (score, label, tone)."""
    if score is None:
        return None
    s = int(round(max(0.0, min(100.0, score))))
    if s >= 60:
        lbl, tone = "Bullish", "pos"
    elif s >= 45:
        lbl, tone = "Neutral", "warm"
    else:
        lbl, tone = "Bearish", "neg"
    return s, lbl, tone


def _technical_score(feat: Dict[str, Any], close: Optional[float]) -> Optional[tuple[int, str, str]]:
    """Deterministic 0-100 technical composite derived from DaaS primitives.

    NIDP does not store a technical composite, so we blend the signals it DOES
    return — trend (price vs SMA50/200), RSI, MACD sign, and the persisted
    momentum_score — into a weighted score. Methodology is fixed and documented
    here so the number is reproducible (no invented inputs)."""
    rsi = _pick(feat, "rsi14", "rsi_14")
    sma50 = _pick(feat, "sma50", "sma_50")
    sma200 = _pick(feat, "sma200", "sma_200")
    macd = _pick(feat, "macd")
    macd_hist = _pick(feat, "macd_hist")
    momentum = _pick(feat, "momentum_score")

    comps: List[tuple[float, float]] = []  # (value 0-100, weight)
    if close is not None and (sma50 is not None or sma200 is not None):
        trend = 50.0
        if sma50 is not None:
            trend += 25 if close > sma50 else -25
        if sma200 is not None:
            trend += 25 if close > sma200 else -25
        comps.append((max(0.0, min(100.0, trend)), 0.30))
    if rsi is not None:
        comps.append((max(0.0, min(100.0, rsi)), 0.20))
    if macd is not None:
        if macd > 0:
            m = 72.0 if (macd_hist is not None and macd_hist > 0) else 64.0
        elif macd < 0:
            m = 28.0
        else:
            m = 50.0
        comps.append((m, 0.20))
    if momentum is not None:
        comps.append((max(0.0, min(100.0, momentum)), 0.30))
    if not comps:
        return None
    tw = sum(w for _, w in comps)
    score = int(round(sum(v * w for v, w in comps) / tw))
    if score >= 60:
        lbl, tone = "Bullish", "pos"
    elif score >= 45:
        lbl, tone = "Neutral", "warm"
    else:
        lbl, tone = "Bearish", "neg"
    return score, lbl, tone


def _fundamentals_grid(feat: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Benchmarked fundamental cards: value + a one-line note + a colour tone.
    Each card is omitted when its underlying DaaS field is missing."""
    cards: List[Dict[str, Any]] = []

    pe = _ratio(feat.get("pe_ttm"))
    sector_pe = _pick(feat, "sector_median_pe")
    pe_vs = _pick(feat, "pe_vs_sector_pct")
    if pe is not None:
        if pe_vs is None and sector_pe:
            pe_vs = (pe / sector_pe - 1) * 100
        if pe_vs is not None and pe_vs > 20:
            note, tone = "pricey", "neg"
        elif pe_vs is not None and pe_vs < -20:
            note, tone = "cheap", "pos"
        else:
            note, tone = "fair", "warm"
        if sector_pe:
            note = f"sector median {sector_pe:.1f} · {note}"
        cards.append({"label": "P / E", "value": f"{pe:.1f}", "note": note, "tone": tone})

    eps_g = _pick(feat, "eps_growth_yoy_pct")
    if pe is not None and eps_g and eps_g > 0:
        peg = pe / eps_g
        if peg < 1:
            note, tone = "under 1 · attractive", "pos"
        elif peg <= 2:
            note, tone = "fair", "warm"
        else:
            note, tone = "> 2 is rich · caution", "neg"
        cards.append({"label": "PEG ratio", "value": f"{peg:.2f}", "note": note, "tone": tone})

    roe = _num(feat.get("roe_pct"))
    if roe is not None:
        note, tone = ("healthy · above 15", "pos") if roe >= 15 else (("moderate", "warm") if roe >= 10 else ("low", "neg"))
        cards.append({"label": "ROE", "value": _pct(roe), "note": note, "tone": tone})

    de = _ratio(feat.get("debt_to_equity"))
    if de is not None:
        note, tone = ("conservative leverage", "pos") if de < 0.5 else (("moderate leverage", "warm") if de < 1 else ("high leverage", "neg"))
        cards.append({"label": "Debt / equity", "value": f"{de:.2f}", "note": note, "tone": tone})

    rev = _pick(feat, "revenue_growth_yoy_pct")
    if rev is not None:
        note, tone = ("top line expanding", "pos") if rev > 0 else ("top line shrinking", "neg")
        cards.append({"label": "Sales growth (YoY)", "value": _pct(rev, signed=True), "note": note, "tone": tone})

    pat = _pick(feat, "pat_growth_yoy_pct")
    if pat is not None:
        note, tone = ("earnings growing", "pos") if pat > 0 else ("margins squeezed", "neg")
        cards.append({"label": "Profit growth (YoY)", "value": _pct(pat, signed=True), "note": note, "tone": tone})

    return cards


def _highlights(feat: Dict[str, Any], close: Optional[float]) -> List[Dict[str, Any]]:
    """'What stands out' — up to three salient facts, each tagged with a tone."""
    pe = _ratio(feat.get("pe_ttm"))
    sector_pe = _pick(feat, "sector_median_pe")
    pe_vs = _pick(feat, "pe_vs_sector_pct")
    if pe_vs is None and pe is not None and sector_pe:
        pe_vs = (pe / sector_pe - 1) * 100
    rev = _pick(feat, "revenue_growth_yoy_pct")
    pat = _pick(feat, "pat_growth_yoy_pct")
    roe = _num(feat.get("roe_pct"))
    de = _ratio(feat.get("debt_to_equity"))
    support = _pick(feat, "swing_low_20", "support")
    resistance = _pick(feat, "swing_high_20", "resistance")

    cand: List[Dict[str, Any]] = []
    if pe is not None and sector_pe and pe_vs is not None and abs(pe_vs) >= 25:
        side = "premium to" if pe_vs > 0 else "discount to"
        cand.append({"tone": "warm" if pe_vs > 0 else "pos",
                     "text": f"Trades at P/E {pe:.1f} vs sector {sector_pe:.1f} — a ~{abs(pe_vs):.0f}% {side} peers."})
    if pat is not None and pat < 0:
        tail = f" even as sales rose {rev:.1f}%" if (rev is not None and rev > 0) else ""
        cand.append({"tone": "neg", "text": f"Net profit fell {abs(pat):.1f}% YoY last quarter{tail}."})
    if close is not None and support and (close - support) / support <= 0.05:
        cand.append({"tone": "info", "text": f"Sitting near support ({_money(support, 0)}) — a key level to watch."})
    if close is not None and resistance and (resistance - close) / resistance <= 0.05:
        cand.append({"tone": "info", "text": f"Pressing against resistance ({_money(resistance, 0)})."})
    if pat is not None and pat > 0 and rev is not None and rev > 0:
        cand.append({"tone": "pos", "text": f"Profit grew {pat:.1f}% YoY on {rev:.1f}% higher sales."})
    if roe is not None and roe >= 18:
        cand.append({"tone": "pos", "text": f"High return on equity at {roe:.1f}%."})
    if de is not None and de < 0.4:
        cand.append({"tone": "pos", "text": f"Lightly geared — debt/equity just {de:.2f}."})
    return cand[:3]


def _prose_summary(feat: Dict[str, Any], close: Optional[float],
                   band: Optional[tuple[int, str, str]], tech: Optional[tuple[int, str, str]]) -> Optional[str]:
    """Deterministic narrative assembled from the real numbers (no LLM)."""
    pe_vs = _pick(feat, "pe_vs_sector_pct")
    pe = _ratio(feat.get("pe_ttm"))
    sector_pe = _pick(feat, "sector_median_pe")
    if pe_vs is None and pe is not None and sector_pe:
        pe_vs = (pe / sector_pe - 1) * 100
    rev = _pick(feat, "revenue_growth_yoy_pct")
    pat = _pick(feat, "pat_growth_yoy_pct")
    de = _ratio(feat.get("debt_to_equity"))

    qy = band[0] if band else None
    if qy is None:
        lead = "This business"
    elif qy >= 60:
        lead = "A quality business"
    elif qy >= 45:
        lead = "A mixed business"
    else:
        lead = "A lower-quality business"

    if pe_vs is None:
        val = None
    elif pe_vs > 40:
        val = "a full valuation"
    elif pe_vs > 15:
        val = "a premium valuation"
    elif pe_vs < -15:
        val = "a discount to its sector"
    else:
        val = "a fair valuation"
    s1 = f"{lead} at {val}." if val else f"{lead}."

    pos: List[str] = []
    if rev is not None and rev > 0:
        pos.append("revenue is growing")
    if de is not None and de < 0.5:
        pos.append("the balance sheet is sound")
    neg: List[str] = []
    if pat is not None and pat < 0:
        neg.append("profit slipped year-on-year")
    if pe_vs is not None and pe_vs > 15:
        neg.append("the stock trades above its sector on earnings")

    mid = ""
    if pos and neg:
        clause = _join_clauses(pos)
        mid = f" {clause[0].upper()}{clause[1:]}, but {_join_clauses(neg)}."
    elif pos:
        clause = _join_clauses(pos)
        mid = f" {clause[0].upper()}{clause[1:]}."
    elif neg:
        mid = f" However, {_join_clauses(neg)}."

    tail = ""
    if tech:
        ts = tech[0]
        tail = " Momentum is firm." if ts >= 60 else (" Momentum is mixed." if ts >= 45 else " Momentum is weak near-term.")

    out = (s1 + mid + tail).strip()
    return out or None


def _humanize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _build_shareholding(feat: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """'Who holds it' — promoter/FII/DII/MF holdings + QoQ deltas + pledge.
    Read straight from the latest stock features (shareholding feed)."""
    defs = [
        ("Promoters", "promoter_pct", "promoter_pct_change_qoq"),
        ("FII", "fii_pct", "fii_pct_change_qoq"),
        ("DII", "dii_pct", "dii_pct_change_qoq"),
        ("Mutual funds", "mf_pct", None),
    ]
    rows: List[Dict[str, Any]] = []
    for label, pk, ck in defs:
        v = _num(feat.get(pk))
        if v is None:
            continue
        row: Dict[str, Any] = {"label": label, "pct": round(v, 2), "value": _pct(v, decimals=2)}
        if ck:
            c = _num(feat.get(ck))
            if c is not None and abs(c) >= 0.01:
                row["change"] = _pct(c, signed=True, decimals=2)
                row["change_positive"] = c >= 0
        rows.append(row)
    if not rows:
        return None
    out: Dict[str, Any] = {"rows": rows}
    pledge = _num(feat.get("promoter_pledged_pct"))
    if pledge is not None:
        out["pledge"] = {"value": _pct(pledge, decimals=2), "tone": "neg" if pledge > 0 else "pos"}
    asof = _fmt_asof(feat.get("shareholding_period_end"))
    if asof:
        out["as_of"] = asof
    return out


def _build_score_breakdown(scores: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """'Explain the score' — the real V3 pillar breakdown from quality_components
    (a JSONB blob, sometimes a JSON string). Drops the `_`-prefixed debug keys."""
    qc = scores.get("quality_components")
    if isinstance(qc, str):
        try:
            qc = json.loads(qc)
        except (ValueError, TypeError):
            return None
    if not isinstance(qc, dict):
        return None

    def pillars(node: Any) -> List[Dict[str, Any]]:
        p = (node or {}).get("pillars") if isinstance(node, dict) else None
        if not isinstance(p, dict):
            return []
        return [
            {"label": _humanize(k), "score": int(round(v))}
            for k, v in p.items()
            if not k.startswith("_") and isinstance(v, (int, float))
        ]

    fund = qc.get("fundamental") if isinstance(qc.get("fundamental"), dict) else {}
    tech = qc.get("technical") if isinstance(qc.get("technical"), dict) else {}
    cyc = qc.get("cycle_position") if isinstance(qc.get("cycle_position"), dict) else {}
    weights = qc.get("weights") if isinstance(qc.get("weights"), dict) else {}

    out: Dict[str, Any] = {}
    if weights:
        out["weights"] = {k: round(v * 100) for k, v in weights.items() if isinstance(v, (int, float))}
    fs, ts = _num(fund.get("score")), _num(tech.get("score"))
    if fs is not None:
        out["fundamental"] = {"score": int(round(fs)), "pillars": pillars(fund)}
    if ts is not None:
        out["technical"] = {"score": int(round(ts)), "pillars": pillars(tech)}
    cs = _num(cyc.get("score"))
    if cs is not None:
        out["cycle"] = {"score": int(round(cs)), "pillars": pillars(cyc)}
    if not (out.get("fundamental") or out.get("technical")):
        return None
    return out


def _build_peers(sym: str, sector: Optional[str], rows: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """'Compare peers' — same-sector stocks ranked by quality_score, with the
    current stock flagged. Peer rows come from the DaaS screener (already sorted
    desc by quality). Shows the top peers but always includes the current stock."""
    if not rows:
        return None
    peers: List[Dict[str, Any]] = []
    for r in rows:
        q = _num(r.get("quality_score"))
        psym = r.get("symbol")
        if q is None or not psym:
            continue
        peers.append({
            "symbol": psym,
            "quality": int(round(q)),
            "industry": r.get("industry"),
            "market_cap": _cap_label(r),
            "is_current": psym.upper() == sym.upper(),
        })
    if not peers:
        return None
    peers.sort(key=lambda p: p["quality"], reverse=True)
    current_rank = next((i + 1 for i, p in enumerate(peers) if p["is_current"]), None)
    top = peers[:8]
    if not any(p["is_current"] for p in top):
        cur = next((p for p in peers if p["is_current"]), None)
        if cur:
            top = top[:7] + [cur]
    out: Dict[str, Any] = {"rows": top, "total": len(peers)}
    if sector:
        out["sector"] = sector
    if current_rank is not None:
        out["current_rank"] = current_rank
    return out


def build_stock_widget(symbol: str, feat: Dict[str, Any], scores: Optional[Dict[str, Any]],
                       peers: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Assemble the rich instrument_detail widget for a stock. Pure function.

    `feat`  : /v1/features/stocks/{symbol}/latest .data  (technical + fundamental)
    `scores`: /v1/stocks/scores/{symbol} .data           (quality + sector rank)

    Every value is read straight from DaaS or derived deterministically from DaaS
    fields (technical composite, PEG, prose, highlights). A section is omitted
    when its inputs are missing — never invented or defaulted to a fake number.
    """
    feat = feat or {}
    scores = scores or {}
    sym = symbol.upper()

    sector = feat.get("sector") or scores.get("sector")
    # The readable classification ("Oil Gas & Consumable Fuels") is `industry`;
    # `sector` is the terse bucket ("Oil Gas"). Prefer industry for display.
    industry = feat.get("industry") or scores.get("industry")
    cap = _cap_label(feat)
    meta = " · ".join([x for x in (industry or sector, cap) if x]) or None

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
        "disclaimer_note": "Not investment advice",
    }
    if close is not None:
        widget["price"] = {
            "label": "Last price",
            "value": _money(close),
            "change": _pct(change_pct, signed=True, decimals=2) if change_pct is not None else None,
            "change_positive": change_positive,
            "asof": _fmt_asof(feat.get("as_of_date") or feat.get("date")),
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

    # Fundamentals + technicals composite bars. The real V3 composites live
    # NESTED under quality_components (the top-level scores row only carries the
    # blended quality_score). Prefer those; fall back to Piotroski / a derived
    # technical blend only when the composite is absent.
    f_score = _pick(scores, "fundamental_score")
    if f_score is None:
        f_score = _num(_nested(scores, "quality_components", "fundamental", "score"))
    band = _fundamental_band(f_score, _num(feat.get("piotroski_score")))

    t_score = _num(_nested(scores, "quality_components", "technical", "score"))
    if t_score is None:
        t_score = _pick(scores, "health_score")
    tech = _technical_band(t_score) if t_score is not None else _technical_score(feat, close)
    score_bars: Dict[str, Any] = {}
    if band:
        score_bars["fundamental"] = {"score": band[0], "label": band[1], "tone": band[2]}
    if tech:
        score_bars["technical"] = {"score": tech[0], "label": tech[1], "tone": tech[2]}
    if band and tech:
        if band[2] == "pos" and tech[2] == "neg":
            score_bars["explainer"] = "Quality score blends both sides — strong fundamentals are dragged down by weak short-term technicals."
        elif band[2] == "neg" and tech[2] == "pos":
            score_bars["explainer"] = "Quality score blends both sides — firmer technicals can't fully offset soft fundamentals."
        else:
            score_bars["explainer"] = "Quality score blends fundamentals with short-term technicals into one read."
    if score_bars:
        widget["scores"] = score_bars

    # Prose summary (deterministic) + 'What stands out'.
    summary = _prose_summary(feat, close, band, tech)
    if summary:
        widget["summary"] = summary
    highlights = _highlights(feat, close)
    if highlights:
        widget["highlights"] = highlights

    # Benchmarked fundamentals grid.
    grid = _fundamentals_grid(feat)
    if grid:
        widget["fundamentals_grid"] = grid

    # 'Where price sits' — position bar + trend.
    sma50 = _pick(feat, "sma50", "sma_50")
    support = _pick(feat, "swing_low_20", "support")
    resistance = _pick(feat, "swing_high_20", "resistance")
    if close is not None and (support is not None or resistance is not None):
        if tech:
            trend = {"label": f"{tech[1]} trend", "tone": tech[2]}
        else:
            trend = None
        pp: Dict[str, Any] = {
            "current": close, "current_label": _money(close, 0),
        }
        if support is not None:
            pp["support"], pp["support_label"] = support, _money(support, 0)
        if sma50 is not None:
            pp["sma50"], pp["sma50_label"] = sma50, _money(sma50, 0)
        if resistance is not None:
            pp["resistance"], pp["resistance_label"] = resistance, _money(resistance, 0)
        if trend:
            pp["trend"] = trend
        widget["price_position"] = pp

    # Technical indicator cards (RSI / MACD / Momentum).
    rsi = _pick(feat, "rsi14", "rsi_14")
    macd = _pick(feat, "macd")
    macd_hist = _pick(feat, "macd_hist")
    cards: List[Dict[str, Any]] = []
    if rsi is not None:
        rnote, rtone = ("overbought", "neg") if rsi >= 70 else (("oversold", "pos") if rsi <= 30 else ("neutral", "warm"))
        cards.append({"label": "RSI (14)", "value": f"{rsi:.1f}", "note": rnote, "tone": rtone})
    if macd is not None:
        if macd > 0:
            mval, mtone = ("Bullish crossover" if (macd_hist is not None and macd_hist > 0) else "Bullish"), "pos"
        elif macd < 0:
            mval, mtone = "Bearish", "neg"
        else:
            mval, mtone = "Neutral", "warm"
        cards.append({"label": "MACD", "value": mval, "tone": mtone})
    momentum = _pick(feat, "momentum_score")
    r1 = _pick(feat, "return_20d_pct")
    r3 = _pick(feat, "return_60d_pct")
    # 6-month return is not in DaaS, so it is honestly omitted (not faked).
    if momentum is not None:
        ret_notes = _compact([
            {"x": f"1M {r1:+.1f}%"} if r1 is not None else None,
            {"x": f"3M {r3:+.1f}%"} if r3 is not None else None,
        ])
        band_lbl = "strong" if momentum >= 60 else ("recovering" if momentum >= 45 else "weak")
        note = " · ".join([n["x"] for n in ret_notes] + [band_lbl])
        mtone = "pos" if momentum >= 60 else ("warm" if momentum >= 45 else "neg")
        cards.append({"label": "Momentum", "value": str(int(round(momentum))), "note": note, "tone": mtone})
    elif r1 is not None or r3 is not None:
        parts = _compact([
            {"x": f"{r1:+.1f}%"} if r1 is not None else None,
            {"x": f"{r3:+.1f}%"} if r3 is not None else None,
        ])
        ref = r3 if r3 is not None else r1
        cards.append({"label": "Momentum (1M / 3M)", "value": " / ".join(p["x"] for p in parts),
                      "tone": "pos" if (ref or 0) >= 0 else "neg"})
    if cards:
        widget["technicals_cards"] = cards

    # Expandable detail sections (shown inline when the matching action is
    # clicked). Each is omitted when its data is unavailable.
    breakdown = _build_score_breakdown(scores)
    if breakdown:
        widget["score_breakdown"] = breakdown
    peers_block = _build_peers(sym, sector, peers)
    if peers_block:
        widget["peers"] = peers_block
    shareholding = _build_shareholding(feat)
    if shareholding:
        widget["shareholding"] = shareholding

    # Action buttons expand the sections above — only offer ones we have data for.
    actions: List[Dict[str, Any]] = []
    if breakdown:
        actions.append({"label": "Explain the score", "expands": "score_breakdown"})
    if peers_block:
        actions.append({"label": "Compare peers", "expands": "peers"})
    if shareholding:
        actions.append({"label": "Who holds it", "expands": "shareholding"})
    if actions:
        widget["actions"] = actions

    return widget


def _stock_summary(symbol: str, w: Dict[str, Any]) -> str:
    """Compact LLM-context line. The LLM only ever sees this string (not the
    widget data), so pack the key numbers in so it can answer in prose."""
    parts = [symbol.upper()]
    q = w.get("quality")
    if q:
        parts.append(f"quality={q['score']}/100 ({q['label']})")
    sc = w.get("scores", {})
    if sc.get("fundamental"):
        parts.append(f"fundamentals={sc['fundamental']['score']}/100 ({sc['fundamental']['label']})")
    if sc.get("technical"):
        parts.append(f"technicals={sc['technical']['score']}/100 ({sc['technical']['label']})")
    for c in w.get("fundamentals_grid", []):
        parts.append(f"{c['label']}={c['value']}")
    r = w.get("rank")
    if r:
        parts.append(f"sector_rank=#{r['value']}/{r['of']}")
    pp = w.get("price_position")
    if pp:
        bits = [f"price={pp.get('current_label')}"]
        if pp.get("support_label"):
            bits.append(f"support={pp['support_label']}")
        if pp.get("sma50_label"):
            bits.append(f"50dma={pp['sma50_label']}")
        if pp.get("resistance_label"):
            bits.append(f"resistance={pp['resistance_label']}")
        if pp.get("trend"):
            bits.append(f"trend={pp['trend']['label']}")
        parts.append(" ".join(bits))
    if w.get("summary"):
        parts.append(w["summary"])
    return " | ".join(p for p in parts if p)


async def get_stock_research(symbol: str) -> InstrumentResearch:
    """Fetch + assemble the full research card for a stock."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return InstrumentResearch(ok=False, kind="stock", identifier="", summary="", error="no_symbol")
    import asyncio
    try:
        feat, scores, hist = await asyncio.gather(
            _daas.get_stock_features_latest(sym),
            _daas.get_stock_scores(sym),
            _daas.get_stock_features_history(sym, limit=2),
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

    # features/latest carries no prev_close, so inject the prior trading day's
    # close to enable a 1-day change — but ONLY when the prior row really is the
    # preceding session (≤4 calendar days). This avoids mislabelling a stale
    # weekly gap as a daily move (staging snapshots can be weekly).
    if isinstance(feat, dict) and isinstance(hist, list) and len(hist) >= 2 and feat.get("prev_close") is None:
        prev_close = _num(hist[1].get("close"))
        gap_ok = True
        d_cur, d_prev = hist[0].get("as_of_date"), hist[1].get("as_of_date")
        if d_cur and d_prev:
            try:
                gap_ok = abs((datetime.fromisoformat(str(d_cur)[:10]) - datetime.fromisoformat(str(d_prev)[:10])).days) <= 4
            except ValueError:
                gap_ok = False
        if prev_close is not None and gap_ok:
            feat["prev_close"] = prev_close

    # Peers (for the 'Compare peers' expansion) — needs the sector, which only
    # comes back with feat/scores, so this is a second hop. Best-effort: [] on
    # any failure just omits the section.
    sector = (feat or {}).get("sector") or (scores or {}).get("sector")
    peers: list = []
    if sector:
        try:
            peers = await _daas.get_sector_peers(sector)
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_sector_peers(%s) failed: %s", sector, exc)

    widget = build_stock_widget(sym, feat or {}, scores, peers=peers)
    ok = bool(
        widget.get("quality") or widget.get("scores")
        or widget.get("fundamentals_grid") or widget.get("technicals_cards")
    )
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
    """Fetch + assemble the full research (summary) card for an MF scheme."""
    import asyncio

    code = str(scheme_code or "").strip()
    if not code:
        return InstrumentResearch(ok=False, kind="mf", identifier="", summary="", error="no_scheme_code")
    try:
        sc, scheme, nav_series = await asyncio.gather(
            _daas.get_mf_scorecard(code),
            _daas.get_mf_scheme(code),
            _daas.get_mf_nav_series(code, limit=2),
        )
    except Exception as exc:  # noqa: BLE001
        return InstrumentResearch(ok=False, kind="mf", identifier=code, summary="", error=str(exc))
    sc = sc or {}
    scheme = scheme or {}
    nav_series = nav_series or []

    if not sc and not scheme:
        return InstrumentResearch(
            ok=False, kind="mf", identifier=code,
            summary=f"No research data available for scheme {code}", error="not_found",
        )

    widget = build_mf_widget(code, sc)

    # Enrich into the rich summary-card shape (prose, real NAV change, tab actions).
    # Lazy import avoids a module-load cycle (mf_cards imports this module).
    from .mf_cards import _clean_name, _nav_block, quartile_insights, _tabs
    name = _clean_name(scheme.get("scheme_name") or widget.get("name") or "") or widget.get("name")
    widget["name"] = name
    nb = _nav_block(scheme, nav_series)
    if nb:
        widget["price"] = {"label": "NAV", **nb}

    prose, _consider, _watch = quartile_insights(sc)
    if prose:
        widget["summary"] = prose

    # Column badges (derived from real quartile / beta values, never invented).
    q3 = sc.get("qtile_ret3y")
    if q3 is not None:
        try:
            q3 = int(q3)
            if q3 <= 1:
                widget["returns_badge"] = {"text": "Top quartile", "tone": "pos"}
            elif q3 == 2:
                widget["returns_badge"] = {"text": "Above category", "tone": "pos"}
            else:
                widget["returns_badge"] = {"text": "Below category", "tone": "neg"}
        except (TypeError, ValueError):
            pass
    beta = _pick(sc, "beta_3y", "beta_1y", "beta")
    if beta is not None and beta < 0.85:
        widget.setdefault("ratios", {})["badge"] = {"text": "Low beta", "tone": "pos"}

    widget["tabs"] = _tabs(name, "summary")
    widget["actions"] = [
        {"label": "Compare peers", "prompt": f"Compare {name} with its peers."},
        {"label": "Full analysis", "prompt": f"Show the overview of {name}."},
    ]

    ok = bool(widget.get("quality") or widget.get("returns") or widget.get("fundamental"))
    return InstrumentResearch(
        ok=ok, kind="mf", identifier=code,
        summary=_mf_summary(code, widget), widget=widget,
        error=None if ok else "insufficient_data",
    )
