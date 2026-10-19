"""Market research hub for the copilot — the market-pulse analogue of
instrument_research (stocks) and mf_cards (funds).

Builds a single `market_detail` widget from the NIDP market snapshot
(`/v1/snapshots/market` — indices, India VIX, FII/DII, G-Sec yields, breadth)
plus top movers (`/v1/market-pulse/movers`), and offers suggested follow-up
chips so the user can drill into related market questions.

`build_market_widget` is pure (no network) and unit-tested; `get_market_research`
does the two DaaS fetches. Replaces the market node's old calls to
`/v1/indices/summary` and `/v1/macro/latest`, which 404 (those routes don't
exist) and made every market query fail with "couldn't retrieve the data".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketResult:
    ok: bool
    summary: str
    widget: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# Suggested follow-up chips — market-pulse lenses the user is most likely to want
# next. Discovery, not advice. Each is a routing-safe query string.
_SUGGESTIONS = [
    "Top gainers and losers today",
    "FII/DII flows this week",
    "India VIX — how fearful is the market?",
    "Which sectors are leading today?",
    "Bank Nifty outlook today",
]


def _num(d: Dict[str, Any], key: str) -> Optional[float]:
    v = d.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _vix_tone(vix: Optional[float]) -> Optional[str]:
    if vix is None:
        return None
    if vix < 13:
        return "calm"
    if vix < 18:
        return "normal"
    if vix < 25:
        return "elevated"
    return "fearful"


# Every block of the snapshot is a published end-of-day figure (nidp.market_daily_snapshot is built from NSE/RBI
# daily files); none of the sources is intraday. The word comes from that fact, the date from each source's own column.
DATA_MODE = "end of day"


def _date_str(v: Any) -> Optional[str]:
    """A source date as text, or None. Never fabricated: an absent date stays absent."""
    if v is None or v == "":
        return None
    return str(v)[:10]


def build_sectors(sector_body: Any, unavailable: Optional[str] = None) -> Dict[str, Any]:
    """Ranked sector block from the DaaS /desk/sector-returns body (name, close, 1d/1w/1m %), best 1-day first.
    No usable rows → {"unavailable": reason}; never an empty block without a reason."""
    if unavailable:
        return {"unavailable": unavailable}
    rows = (sector_body or {}).get("sectors") if isinstance(sector_body, dict) else None
    ranked = [
        {"sector": r.get("sector"), "index": r.get("index"), "close": _num(r, "close"),
         "ret_1d_pct": _num(r, "ret_1d_pct"), "ret_1w_pct": _num(r, "ret_1w_pct"),
         "ret_1m_pct": _num(r, "ret_1m_pct"), "date": _date_str(r.get("date"))}
        for r in (rows or []) if isinstance(r, dict) and _num(r, "close") is not None
    ]
    if not ranked:
        return {"unavailable": "the sector-returns route returned no sector rows"}
    # Rank by 1-day return; a sector with no 1-day figure goes last.
    ranked.sort(key=lambda r: (r["ret_1d_pct"] is None, -(r["ret_1d_pct"] or 0.0)))
    return {"as_of": _date_str(sector_body.get("as_of")), "source": sector_body.get("source"),
            "mode": DATA_MODE, "ranked": ranked}


def build_market_widget(snapshot: Optional[Dict[str, Any]],
                        movers: Optional[Dict[str, Any]] = None,
                        sectors: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pure builder: NIDP market snapshot (+ optional movers, sectors) → market_detail widget.
    Every field is gated on real data — missing inputs are simply omitted."""
    s = snapshot or {}

    indices: List[Dict[str, Any]] = []
    if _num(s, "nifty50_close") is not None:
        indices.append({"label": "Nifty 50", "value": _num(s, "nifty50_close"),
                        "change_pct": _num(s, "nifty50_pct_change")})
    if _num(s, "bank_nifty_close") is not None:
        indices.append({"label": "Bank Nifty", "value": _num(s, "bank_nifty_close"), "change_pct": None})
    if _num(s, "nifty500_close") is not None:
        indices.append({"label": "Nifty 500", "value": _num(s, "nifty500_close"), "change_pct": None})

    vix = _num(s, "india_vix")

    breadth = None
    adv, dec = _num(s, "advances_count"), _num(s, "declines_count")
    if adv is not None and dec is not None:
        breadth = {"advances": int(adv), "declines": int(dec),
                   "unchanged": int(_num(s, "unchanged_count") or 0)}

    flows = None
    fii, dii = _num(s, "fii_cash_net_cr"), _num(s, "dii_cash_net_cr")
    if fii is not None or dii is not None:
        flows = {"fii_cr": fii, "dii_cr": dii, "as_of": s.get("fii_dii_as_of")}

    yields = None
    g10 = _num(s, "rbi_10y_yield")
    if g10 is not None:
        yields = {"g10y": g10, "g91d": _num(s, "rbi_91d_yield"), "as_of": s.get("yields_as_of")}

    def _trim(lst: Any) -> List[Dict[str, Any]]:
        return [
            {"symbol": x.get("symbol"), "name": x.get("name"), "change_pct": x.get("change_pct")}
            for x in (lst or [])[:5] if isinstance(x, dict)
        ]

    mv = movers or {}
    movers_out = None
    if mv.get("gainers") or mv.get("losers"):
        movers_out = {"gainers": _trim(mv.get("gainers")), "losers": _trim(mv.get("losers")),
                      "as_of": mv.get("as_of")}

    return {
        "as_of": s.get("as_of_date"),
        "mode": DATA_MODE,
        "indices_as_of": _date_str(s.get("index_as_of")),
        "breadth_as_of": _date_str(s.get("prices_as_of")),
        "sectors": sectors,
        "indices": indices,
        "vix": vix,
        "vix_tone": _vix_tone(vix),
        "breadth": breadth,
        "flows": flows,
        "yields": yields,
        "movers": movers_out,
        "suggestions": list(_SUGGESTIONS),
        "caveat": "End-of-day NSE/BSE exchange data — not real-time, not investment advice.",
    }


def market_summary(widget: Dict[str, Any]) -> str:
    """One-line LLM context line from the built widget (the only thing the LLM sees)."""
    mode = widget.get("mode") or DATA_MODE

    def _asof(d: Any) -> str:
        return f"[{mode}, as of {d}]" if d else f"[{mode}, date not provided by source]"

    parts: List[str] = []
    idx_bits = []
    for i in widget.get("indices") or []:
        seg = f"{i['label']} {i['value']:,.0f}"
        if i.get("change_pct") is not None:
            seg += f" ({i['change_pct']:+.2f}%)"
        idx_bits.append(seg)
    if widget.get("vix") is not None:
        idx_bits.append(f"India VIX {widget['vix']} ({widget.get('vix_tone')})")
    if idx_bits:
        parts.append(", ".join(idx_bits) + " " + _asof(widget.get("indices_as_of") or widget.get("as_of")))
    b = widget.get("breadth")
    if b:
        parts.append(f"breadth {b['advances']} adv / {b['declines']} decl "
                     + _asof(widget.get("breadth_as_of") or widget.get("as_of")))
    f = widget.get("flows")
    if f:
        bits = []
        if f.get("fii_cr") is not None:
            bits.append(f"FII ₹{f['fii_cr']:,.0f}cr")
        if f.get("dii_cr") is not None:
            bits.append(f"DII ₹{f['dii_cr']:,.0f}cr")
        if bits:
            parts.append(", ".join(bits) + " " + _asof(f.get("as_of")))
    y = widget.get("yields")
    if y:
        parts.append(f"10Y G-Sec {y['g10y']}% " + _asof(y.get("as_of")))
    m = widget.get("movers")
    if m and m.get("gainers"):
        top = m["gainers"][0]
        if top.get("change_pct") is not None:
            parts.append(f"top gainer {top.get('symbol')} {top['change_pct']:+.1f}% " + _asof(m.get("as_of")))
    sec = widget.get("sectors")
    if isinstance(sec, dict):
        if sec.get("unavailable"):
            parts.append(f"sector data unavailable: {sec['unavailable']}")
        elif sec.get("ranked"):
            def _r(v: Any) -> str:
                return "n/a" if v is None else f"{v:+.2f}%"
            rows = "; ".join(
                f"{r['sector']} {r['close']:,.0f} (1d {_r(r['ret_1d_pct'])}, 1w {_r(r['ret_1w_pct'])}, "
                f"1m {_r(r['ret_1m_pct'])})" for r in sec["ranked"])
            parts.append(f"sectors ranked by 1-day return, best first: {rows} "
                         + _asof(sec.get("as_of")) + f" source: {sec.get('source') or 'not stated'}")
    return " · ".join(parts) if parts else "Market snapshot unavailable"


async def get_market_research() -> MarketResult:
    """Fetch the market snapshot + top movers from NIDP and build the widget.
    Never raises — degrades to ok=False so the node answers honestly."""
    from . import daas_client

    snapshot: Dict[str, Any] = {}
    movers: Optional[Dict[str, Any]] = None
    try:
        # daas_client._get prepends /v1 itself; a path that also starts with /v1
        # requests /v1/v1/... , which 404s and comes back as None.
        body = await daas_client._get("/snapshots/market")
        if isinstance(body, dict):
            snapshot = body.get("data") or body
    except Exception as exc:  # noqa: BLE001 — never break the turn
        logger.warning("market snapshot fetch failed: %s", exc)
    try:
        movers = await daas_client._get("/market-pulse/movers", params={"cap": "large"})
    except Exception as exc:  # noqa: BLE001
        logger.debug("market movers fetch failed: %s", exc)

    sector_body: Any = None
    sector_err: Optional[str] = None
    try:
        sector_body = await daas_client._get("/desk/sector-returns")
        if sector_body is None:
            sector_err = "the sector-returns route was not found (HTTP 404)"
    except Exception as exc:  # noqa: BLE001 — a missing block must be said, not silent
        logger.warning("sector returns fetch failed: %s", exc)
        sector_err = str(exc)[:200]

    widget = build_market_widget(snapshot, movers if isinstance(movers, dict) else None,
                                 build_sectors(sector_body, sector_err))
    ok = bool(widget.get("indices") or widget.get("breadth"))
    return MarketResult(
        ok=ok,
        summary=market_summary(widget),
        widget=widget,
        data=snapshot,
        error=None if ok else "market snapshot unavailable",
    )
