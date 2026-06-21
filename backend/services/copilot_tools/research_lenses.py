"""Question-first research lens contract for the Copilot instrument card.

Maps the 10 user-facing research questions ("Worth buying now?", "How risky?") onto
the data the stock / MF widget builders already produce, and emits a **research hub**:
an ordered chip rail plus a lens-keyed `lens_views` dict the frontend renders as a
fixed rail on the card (see docs/prd/COPILOT_RESEARCH_HUB.prd.md).

Design rules (CONTEXT.md):
  * Compose what the widget builders already returned — no new DaaS calls, no parallel
    calculators. This module is pure (dict in → dict out) and unit-tests offline.
  * A lens appears ONLY when its underlying data is present. Gaps hide themselves
    (decision: hide the chip, never show a faked or empty section). So a stock with no
    dividend-yield feed simply has no `costs` chip; an MF with no news has no `whats_new`.
  * Every value is sliced straight from the real widget — nothing is invented here.

Public API:
    LENSES                              → the ordered 10-lens catalogue
    build_research_hub(kind, widget)    → mutates widget: adds research_rail / lens_views /
                                          active_lens; returns the same widget for chaining
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Lens:
    id: str
    primary: str   # the chip's headline label
    alt: str       # the alternate phrasing / the question we actually answer


# The canonical taxonomy. Order is the rail order. Same 10 questions for a stock or an
# MF; the data path underneath differs (see _stock_views / _mf_views).
LENSES: Tuple[Lens, ...] = (
    Lens("buy_verdict", "Worth buying now?", "Should I buy?"),
    Lens("performance", "How's it performed?", "Track record"),
    Lens("valuation",   "Cheap or pricey?",  "Fair value?"),
    Lens("risk",        "How risky is it?",  "Risk check"),
    Lens("peers",       "Compare to peers",  "Beats its peers?"),
    Lens("drivers",     "What drives it?",   "Under the hood"),
    Lens("red_flags",   "Any red flags?",    "What's the catch?"),
    Lens("costs",       "What it costs",     "Fees & payouts"),
    Lens("people",      "Who runs it?",      "The people behind it"),
    Lens("whats_new",   "What's new?",       "Latest updates"),
)

_LENS_BY_ID: Dict[str, Lens] = {l.id: l for l in LENSES}


def _nonempty(*vals: Any) -> bool:
    """True if any value is a non-empty dict/list or a truthy scalar."""
    for v in vals:
        if isinstance(v, (dict, list)):
            if v:
                return True
        elif v:
            return True
    return False


# ── STOCK ─────────────────────────────────────────────────────────────────────

def _stock_red_flags(w: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The bear case, assembled ONLY from negative signals already in the widget —
    negative 'what stands out' items, a promoter pledge, a Sell stance, and weak
    score bands. Nothing invented; if there's nothing negative, returns []."""
    items: List[Dict[str, Any]] = []
    for h in w.get("highlights") or []:
        if h.get("tone") == "neg" and h.get("text"):
            items.append({"text": h["text"], "tone": "neg"})
    pledge = ((w.get("shareholding") or {}).get("pledge")) or {}
    if pledge.get("tone") == "neg" and pledge.get("value"):
        items.append({"text": f"Promoters have pledged {pledge['value']} of their holding.", "tone": "neg"})
    rec = w.get("recommendation") or {}
    for horizon, lbl in (("long_term", "Long-term"), ("short_term", "Short-term")):
        leg = rec.get(horizon) or {}
        if (leg.get("stance") or "").lower() == "sell" and leg.get("rationale"):
            items.append({"text": f"{lbl}: {leg['rationale']}", "tone": "neg"})
    scores = w.get("scores") or {}
    for key, lbl in (("fundamental", "Fundamentals"), ("technical", "Technicals")):
        leg = scores.get(key) or {}
        if leg.get("tone") == "neg" and leg.get("score") is not None:
            items.append({"text": f"{lbl} score is weak at {leg['score']}/100 ({leg.get('label','')}).".replace(" ().", "."), "tone": "neg"})
    # de-dupe identical texts while preserving order
    seen, out = set(), []
    for it in items:
        if it["text"] not in seen:
            seen.add(it["text"])
            out.append(it)
    return out


def _stock_views(w: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Slice the flat stock widget into lens-keyed view payloads. Each payload carries
    only the sub-objects its lens renders; a lens is included only when non-empty."""
    views: Dict[str, Dict[str, Any]] = {}

    # 1 — Worth buying now?  (quality + composite scores + buy/hold/sell verdict)
    bv = _compact_view({
        "view": "stock_verdict",
        "quality": w.get("quality"),
        "rank": w.get("rank"),
        "scores": w.get("scores"),
        "recommendation": w.get("recommendation"),
        "summary": w.get("summary"),
        "highlights": w.get("highlights"),
    })
    if _nonempty(bv.get("quality"), bv.get("scores"), bv.get("recommendation")):
        views["buy_verdict"] = bv

    # 2 — How's it performed?  (price position + momentum/technical cards)
    perf = _compact_view({
        "view": "stock_performance",
        "price_position": w.get("price_position"),
        "technicals_cards": w.get("technicals_cards"),
    })
    if _nonempty(perf.get("price_position"), perf.get("technicals_cards")):
        views["performance"] = perf

    # 3 — Cheap or pricey?  (benchmarked fundamentals incl. P/E vs sector)
    if _nonempty(w.get("fundamentals_grid")):
        views["valuation"] = _compact_view({
            "view": "stock_valuation",
            "fundamentals_grid": w.get("fundamentals_grid"),
            "rank": w.get("rank"),
        })

    # 4 — How risky?  (volatility / beta / Sharpe / drawdown)
    if _nonempty(w.get("risk")):
        views["risk"] = {"view": "stock_risk", **w["risk"]}

    # 5 — Compare to peers
    if _nonempty((w.get("peers") or {}).get("rows")):
        views["peers"] = {"view": "stock_peers", "peers": w["peers"]}

    # 6 — What drives it? (business segments) — no NIDP segment feed for equities → hidden.

    # 7 — Any red flags?  (bear case from real negative signals)
    flags = _stock_red_flags(w)
    if flags:
        views["red_flags"] = {"view": "stock_red_flags", "items": flags}

    # 8 — What it costs (dividend yield) — not in the NIDP fundamentals feed → hidden.

    # 9 — Who runs it?  (promoter / FII / DII shareholding — no mgmt bios feed)
    if _nonempty((w.get("shareholding") or {}).get("rows")):
        views["people"] = {"view": "stock_people", "shareholding": w["shareholding"]}

    # 10 — What's new?  (quarterly results + corporate events)
    wn = _compact_view({
        "view": "stock_whats_new",
        "quarterly": w.get("quarterly"),
        "corporate_events": w.get("corporate_events"),
    })
    if _nonempty((wn.get("quarterly") or {}).get("rows"), (wn.get("corporate_events") or {}).get("rows")):
        views["whats_new"] = wn

    return views


# ── MUTUAL FUND ─────────────────────────────────────────────────────────────

def _facts_subset(facts: List[Dict[str, Any]], labels: Tuple[str, ...]) -> List[Dict[str, Any]]:
    return [f for f in (facts or []) if f.get("label") in labels]


def _mf_views(w: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Remap the MF full-card `views` (summary/overview/returns/holdings/peers) onto the
    lens taxonomy, deriving the valuation / risk / costs / people lenses from data already
    present in those views (no new fetch)."""
    src: Dict[str, Any] = w.get("views") or {}
    summary = src.get("summary") or {}
    overview = src.get("overview") or {}
    returns = src.get("returns") or {}
    holdings = src.get("holdings") or {}
    peers = src.get("peers") or {}
    views: Dict[str, Dict[str, Any]] = {}

    # 1 — Worth buying now?  (quality donut + prose + returns/risk columns) = the summary view
    if _nonempty(summary.get("quality"), summary.get("returns"), summary.get("ratios")):
        views["buy_verdict"] = {**summary, "view": "summary"}

    # 2 — How's it performed?  (CAGR vs category) = the returns view
    if _nonempty(returns.get("cagr")):
        views["performance"] = {**returns, "view": "returns"}

    # 3 — Cheap or pricey?  reframed as standing vs category (rank + return quartile badge)
    q = summary.get("quality") or {}
    if q.get("rank") is not None and q.get("of") is not None:
        views["valuation"] = _compact_view({
            "view": "mf_valuation",
            "quality": q,
            "returns_badge": summary.get("returns_badge"),
            "note": "Mutual funds don't have a P/E — 'value' here means standing in the "
                    "category: rank by Nivesh score and the return quartile.",
        })

    # 4 — How risky?  (Sharpe / beta / std-dev / max-drawdown) from the summary ratios
    if _nonempty((summary.get("ratios") or {}).get("items")):
        ratios = {**summary["ratios"], "title": summary["ratios"].get("title") or "Risk & ratios"}
        views["risk"] = {"view": "mf_risk", "ratios": ratios}

    # 5 — Compare to peers
    if _nonempty(peers.get("rows")):
        views["peers"] = {**peers, "view": "peers"}

    # 6 — What drives it?  (holdings & sectors) = the holdings view
    if _nonempty(holdings.get("top_holdings"), holdings.get("asset_allocation")):
        views["drivers"] = {**holdings, "view": "holdings"}

    # 7 — Any red flags? — lifecycle events aren't carried in the full card → hidden in Phase 1.

    # 8 — What it costs  (expense ratio / AUM / exit load) from the overview facts
    cost_facts = _facts_subset(overview.get("facts") or [], ("Expense ratio", "AUM", "Exit load"))
    if cost_facts:
        views["costs"] = {"view": "mf_costs", "facts": cost_facts}

    # 9 — Who runs it?  (fund managers) from the overview
    if overview.get("managers"):
        views["people"] = _compact_view({
            "view": "mf_people",
            "managers": overview.get("managers"),
            "facts": _facts_subset(overview.get("facts") or [], ("Launched", "Benchmark")),
        })

    # 10 — What's new? — no MF news feed → hidden.

    return views


# ── shared ────────────────────────────────────────────────────────────────────

def _compact_view(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop None values so the frontend's `length`/presence checks stay simple."""
    return {k: v for k, v in d.items() if v is not None}


def build_research_hub(kind: str, widget: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Attach the research hub (rail + lens views) to a built instrument widget.

    Adds three keys IN PLACE and returns the same widget:
      research_rail : [{id, primary, alt}]  — only the lenses with real data, in catalogue order
      lens_views    : {lens_id: payload}    — the data each lens renders
      active_lens   : the first available lens id ("buy_verdict" when present)

    Returns the widget unchanged (no rail) when it isn't an instrument card or has
    no lens data — callers can attach unconditionally.
    """
    if not isinstance(widget, dict):
        return widget
    if kind == "stock":
        views = _stock_views(widget)
    elif kind == "mf":
        views = _mf_views(widget)
    else:
        return widget
    if not views:
        return widget

    rail = [
        {"id": l.id, "primary": l.primary, "alt": l.alt}
        for l in LENSES if l.id in views
    ]
    widget["research_rail"] = rail
    widget["lens_views"] = views
    widget["active_lens"] = rail[0]["id"] if rail else None
    return widget
