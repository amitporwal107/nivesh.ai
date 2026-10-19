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

import asyncio
import logging
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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


# ── event calendar ───────────────────────────────────────────────────────────────

CALENDAR_SESSIONS = 5
_RESULTS = "quarterly_results"
_OTHER_EVENTS_SHOWN = 10


def next_sessions(anchor: str, holidays: set, n: int = CALENDAR_SESSIONS) -> List[str]:
    """The next `n` NSE cash sessions after `anchor` (ISO date): weekends and the exchange's holiday list skipped.
    A weekday is never assumed to be a session; the caller must have the holiday list before calling."""
    d, out = date.fromisoformat(anchor), []
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in holidays:
            out.append(d.isoformat())
    return out


def _rows(body: Any) -> List[Dict[str, Any]]:
    data = body.get("data") if isinstance(body, dict) else None
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def build_calendar(anchor: Optional[str], holidays_body: Any, holidays_err: Optional[str],
                   events_body: Any, events_err: Optional[str],
                   nifty_body: Any, nifty_err: Optional[str]) -> Dict[str, Any]:
    """Next-5-sessions event block from nidp.nse_holidays (DaaS /holidays), nidp.event_calendar (DaaS /events/calendar)
    and the Nifty 50 list (DaaS /indices/Nifty 50/constituents). Without the holiday list there is no block: the
    sessions are never worked out from weekdays alone."""
    if not anchor:
        return {"unavailable": "the market snapshot carries no as-of date to count sessions from"}
    if holidays_err:
        return {"unavailable": f"NSE holiday list: {holidays_err}"}
    if events_err:
        return {"unavailable": events_err}
    hol = {_date_str(r.get("holiday_date")): r.get("description") for r in _rows(holidays_body)
           if _date_str(r.get("holiday_date"))}
    sessions = next_sessions(anchor, set(hol))
    first, last = sessions[0], sessions[-1]
    in_window = sorted(((_date_str(r.get("event_date")), r) for r in _rows(events_body)
                        if _date_str(r.get("event_date")) and first <= _date_str(r.get("event_date")) <= last),
                       key=lambda t: (t[0], str(t[1].get("symbol"))))
    days: Dict[str, Dict[str, Any]] = {d: {"date": d, "is_session": True, "results": 0} for d in sessions}
    others: List[Dict[str, Any]] = []
    for d, r in in_window:
        day = days.setdefault(d, {"date": d, "is_session": False, "results": 0})
        if r.get("event_type") == _RESULTS:
            day["results"] += 1
        else:
            others.append({"symbol": r.get("symbol"), "event_type": r.get("event_type"), "date": d})
    out: Dict[str, Any] = {
        "as_of": anchor, "mode": "scheduled", "sessions": sessions,
        "holidays": [{"date": d, "description": hol[d]} for d in sorted(hol) if anchor < d <= last],
        "days": [days[d] for d in sorted(days)], "other_events": others,
        "refreshed": max((_date_str(r.get("fetched_at")) or "" for _, r in in_window), default="") or None,
    }
    if nifty_err:
        out["nifty50_unavailable"] = nifty_err
    else:
        members = {r.get("symbol") for r in _rows(nifty_body)}
        out["nifty50_list_date"] = _date_str(nifty_body.get("as_of")) if isinstance(nifty_body, dict) else None
        out["nifty50_reporting"] = [{"symbol": r.get("symbol"), "date": d, "event_type": r.get("event_type")}
                                    for d, r in in_window if r.get("symbol") in members and d in sessions]
    return out


# ── global markets, currency, commodities ────────────────────────────────────────

_GLOBAL_EXPECTED = ("USD / INR", "US 10Y Treasury", "Brent Crude", "Gold")


def build_global(snap: Any, unavailable: Optional[str] = None) -> Dict[str, Any]:
    """From positional_engine.nse_live.get_global_snapshot (Yahoo Finance daily closes: the same feed the desk
    Overview's USD/INR and crude tiles and /api/markets/home read). The vendor gives no per-asset trading date, only
    the fetch time, and that is what is reported."""
    if unavailable:
        return {"unavailable": unavailable}
    if not isinstance(snap, dict):
        return {"unavailable": "the vendor quote fetch returned nothing"}
    cues, coms = snap.get("global_cues") or [], snap.get("commodities") or []
    regions = snap.get("global_indices") or {}
    present = {q.get("name") for q in [*cues, *coms] if isinstance(q, dict)}
    return {"as_of": _date_str(snap.get("fetched_at")), "mode": "vendor quote (Yahoo Finance), last daily close",
            "fetched_at": snap.get("fetched_at"),
            "indices": {k: [q for q in (regions.get(k) or []) if isinstance(q, dict)] for k in ("us", "europe", "asia")},
            "cues": [q for q in cues if isinstance(q, dict)], "commodities": [q for q in coms if isinstance(q, dict)],
            "missing": [n for n in _GLOBAL_EXPECTED if n not in present]}


# ── 5-session trend ──────────────────────────────────────────────────────────────

def build_trend(recent_body: Any, recent_err: Optional[str], yields_body: Any,
                yields_err: Optional[str]) -> Dict[str, Any]:
    """Five-session change from nidp.market_daily_snapshot history (DaaS /snapshots/market/recent), and the 10Y
    G-Sec from its own series (DaaS /macro/rbi-yields, published about weekly, so never called a 5-session change)."""
    rows = sorted(_rows(recent_body), key=lambda r: str(r.get("as_of_date")), reverse=True)
    if recent_err:
        hist: Dict[str, Any] = {"unavailable": recent_err}
    elif len(rows) < 6:
        hist = {"unavailable": f"only {len(rows)} sessions of history (a 5-session change needs 6)"}
    else:
        new, old, window = rows[0], rows[5], rows[:5]

        def _sum(k: str) -> Optional[float]:
            v = [_num(r, k) for r in window]
            return None if any(x is None for x in v) else sum(v)  # type: ignore[arg-type]
        n0, n1 = _num(new, "nifty50_close"), _num(old, "nifty50_close")
        hist = {"from": _date_str(old.get("as_of_date")), "to": _date_str(new.get("as_of_date")),
                "nifty50_pct": round((n0 / n1 - 1) * 100, 1) if n0 and n1 else None,
                "vix": [_num(old, "india_vix"), _num(new, "india_vix")],
                "advances": [_num(old, "advances_count"), _num(new, "advances_count")],
                "declines": [_num(old, "declines_count"), _num(new, "declines_count")],
                "fii_net_sum_cr": _sum("fii_cash_net_cr"), "dii_net_sum_cr": _sum("dii_cash_net_cr")}
    y = sorted([r for r in _rows(yields_body) if _num(r, "yield_pct") is not None],
               key=lambda r: str(r.get("as_of_date")), reverse=True)
    if yields_err:
        yld: Dict[str, Any] = {"unavailable": yields_err}
    elif len(y) < 2:
        yld = {"unavailable": f"only {len(y)} 10Y observations"}
    else:
        yld = {"latest": _num(y[0], "yield_pct"), "latest_date": _date_str(y[0].get("as_of_date")),
               "previous": _num(y[1], "yield_pct"), "previous_date": _date_str(y[1].get("as_of_date")),
               "change_pts": round(_num(y[0], "yield_pct") - _num(y[1], "yield_pct"), 2)}
    return {"history": hist, "yield_10y": yld}


# ── F&O positioning ──────────────────────────────────────────────────────────────

FNO_INDICES = ("NIFTY", "BANKNIFTY")


def build_fno(buildup: Any, buildup_err: Optional[str], options: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Index-futures build-up and stock-futures label counts (DaaS /desk/fno-buildup), plus per-index option PCR and
    max pain over the nearest expiry that is still live after the data's day (DaaS /fno/{symbol}/chain, worked out
    with routes.fno.summarise_chain). `options[sym]` is a summary or {"unavailable": reason}."""
    if buildup_err or not isinstance(buildup, dict):
        fut: Dict[str, Any] = {"unavailable": buildup_err or "the fno-buildup route returned nothing"}
    else:
        by = {r.get("symbol"): r for r in (buildup.get("indices") or []) if isinstance(r, dict)}
        fut = {"as_of": _date_str(buildup.get("as_of")), "universe": buildup.get("universe"),
               "counts": buildup.get("counts") or {},
               "indices": [{"symbol": s, "label": by[s].get("label"), "price_chg_pct": _num(by[s], "price_chg_pct"),
                            "oi_chg_pct": _num(by[s], "oi_chg_pct"), "near_expiry": by[s].get("near_expiry")}
                           for s in FNO_INDICES if s in by]}
    as_of = fut.get("as_of") or next((o.get("as_of") for o in options.values() if o.get("as_of")), None)
    return {"as_of": as_of, "mode": DATA_MODE, "futures": fut, "options": options}


AIF_PMS = {"available": False,
           "reason": "no AIF or PMS source exists in the data platform (checked routes, services and migrations)"}


def build_market_widget(snapshot: Optional[Dict[str, Any]],
                        movers: Optional[Dict[str, Any]] = None,
                        sectors: Optional[Dict[str, Any]] = None,
                        extras: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        **(extras or {}),
        "aif_pms": AIF_PMS,
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


def _pct(v: Any) -> str:
    return "change n/a" if v is None else f"{v:+.2f}%"


def _calendar_part(c: Dict[str, Any]) -> str:
    if c.get("unavailable"):
        return f"event calendar unavailable: {c['unavailable']}"
    hol = "; ".join(f"{h['date']} {h['description']} is an NSE holiday" for h in c["holidays"]) \
        or "no NSE holiday in the window"
    days = "; ".join(f"{d['date']}{'' if d['is_session'] else ' (not a session)'}: {d['results']} results"
                     for d in c["days"])
    txt = (f"event calendar, next {len(c['sessions'])} sessions {', '.join(c['sessions'])} ({hol}) "
           f"[scheduled, as of {c['as_of']}]"
           + (f" (calendar refreshed {c['refreshed']})" if c.get("refreshed") else "") + f": results meetings per day: {days}")
    if c.get("nifty50_unavailable"):
        txt += f"; Nifty 50 membership unavailable: {c['nifty50_unavailable']}"
    else:
        rep = ", ".join(f"{r['symbol']} {r['date']}" for r in c.get("nifty50_reporting") or [])
        txt += (f"; Nifty 50 companies reporting: {rep}" if rep else "; no Nifty 50 company reports in the window")
        txt += f" (Nifty 50 list dated {c.get('nifty50_list_date') or 'date not provided'})"
    oth = c.get("other_events") or []
    if oth:
        txt += "; other events: " + ", ".join(f"{o['symbol']} {o['event_type']} {o['date']}"
                                              for o in oth[:_OTHER_EVENTS_SHOWN])
        if len(oth) > _OTHER_EVENTS_SHOWN:
            txt += f" (+{len(oth) - _OTHER_EVENTS_SHOWN} more)"
    return txt


def _global_part(g: Dict[str, Any]) -> str:
    if g.get("unavailable"):
        return f"global markets unavailable: {g['unavailable']}"

    def q(x: Dict[str, Any], fmt: str) -> str:
        return f"{x.get('name')} {fmt.format(x['value'])} ({_pct(x.get('change_pct'))})"
    segs = []
    for label, key in (("US", "us"), ("Europe", "europe"), ("Asia", "asia")):
        qs = [q(x, "{:,.0f}") for x in g["indices"][key] if isinstance(x.get("value"), (int, float))]
        if qs:
            segs.append(f"{label}: " + ", ".join(qs))
    cur = [x for x in g["cues"] if x.get("name") == "USD / INR" and isinstance(x.get("value"), (int, float))]
    if cur:
        segs.append("currency: " + q(dict(cur[0], name="USD/INR"), "{:.2f}"))
    us10 = [x for x in g["cues"] if x.get("name") == "US 10Y Treasury" and isinstance(x.get("value"), (int, float))]
    if us10:
        segs.append(f"rates: US 10Y Treasury {us10[0]['value']}% ({_pct(us10[0].get('change_pct'))})")
    coms = [f"{x.get('name')} {x['value']:,.2f} {x.get('unit') or ''} ({_pct(x.get('change_pct'))})"
            for x in g["commodities"] if isinstance(x.get("value"), (int, float))]
    if coms:
        segs.append("commodities: " + ", ".join(coms))
    txt = f"global markets and commodities ({'; '.join(segs)}) [{g['mode']}, fetched {g.get('as_of') or 'time not provided'}]"
    if g.get("missing"):
        txt += f"; not in the vendor feed: {', '.join(g['missing'])}"
    return txt


def _trend_parts(t: Dict[str, Any]) -> List[str]:
    out = []
    h = t["history"]
    if h.get("unavailable"):
        out.append(f"trend unavailable: {h['unavailable']}")
    else:
        bits = []
        if h.get("nifty50_pct") is not None:
            bits.append(f"Nifty 50 {h['nifty50_pct']:+.1f}%")
        if None not in h["vix"]:
            bits.append(f"India VIX {h['vix'][0]} to {h['vix'][1]}")
        if None not in h["advances"] and None not in h["declines"]:
            bits.append(f"advances {h['advances'][0]:.0f} to {h['advances'][1]:.0f} "
                        f"(declines {h['declines'][0]:.0f} to {h['declines'][1]:.0f})")
        for k, lab in (("fii_net_sum_cr", "FII"), ("dii_net_sum_cr", "DII")):
            if h.get(k) is not None:
                bits.append(f"{lab} net over the 5 sessions ₹{h[k]:,.0f}cr")
        out.append(f"5-session trend {h['from']} to {h['to']} [{DATA_MODE}, as of {h['to']}]: " + ", ".join(bits))
    y = t["yield_10y"]
    if y.get("unavailable"):
        out.append(f"10Y trend unavailable: {y['unavailable']}")
    else:
        out.append(f"10Y G-Sec {y['latest']}% ({y['latest_date']}) vs {y['previous']}% ({y['previous_date']}), "
                   f"change {y['change_pts']:+.2f} pts [published about weekly, as of {y['latest_date']}]")
    return out


def _fno_part(f: Dict[str, Any]) -> str:
    segs = []
    fut = f["futures"]
    if fut.get("unavailable"):
        segs.append(f"F&O futures build-up unavailable: {fut['unavailable']}")
    else:
        for r in fut["indices"]:
            oi = "n/a" if r["oi_chg_pct"] is None else f"{r['oi_chg_pct']:+.2f}%"
            segs.append(f"{r['symbol']} futures {r['label']} (price {_pct(r['price_chg_pct'])}, OI {oi})")
        counts = sorted(((k, v) for k, v in (fut.get("counts") or {}).items() if v), key=lambda kv: -kv[1])
        if counts:
            segs.append(f"stock futures build-up over {fut.get('universe')} underlyings: "
                        + ", ".join(f"{k} {v}" for k, v in counts))
    for sym, o in f["options"].items():
        if o.get("unavailable"):
            segs.append(f"{sym} option OI/PCR unavailable: {o['unavailable']}")
        else:
            bits = [f"PCR {o['pcr']:.2f}" if o.get("pcr") is not None else "PCR n/a"]
            if o.get("max_pain") is not None:
                bits.append(f"max pain {o['max_pain']:g}")
            if o.get("spot") is not None:
                bits.append(f"spot {o['spot']:,.0f}")
            for k, lab in (("max_call_oi", "heaviest call OI strike"), ("max_put_oi", "heaviest put OI strike")):
                if o.get(k):
                    bits.append(f"{lab} {o[k]['strike']:g}")
            segs.append(f"{sym} options expiry {o['expiry']}: " + ", ".join(bits))
    return f"F&O positioning [{DATA_MODE}, as of {f.get('as_of') or 'date not provided'}]: " + "; ".join(segs)


def _extra_parts(widget: Dict[str, Any]) -> List[str]:
    parts: List[str] = []
    if isinstance(widget.get("calendar"), dict):
        parts.append(_calendar_part(widget["calendar"]))
    if isinstance(widget.get("global"), dict):
        parts.append(_global_part(widget["global"]))
    if isinstance(widget.get("trend"), dict):
        parts.extend(_trend_parts(widget["trend"]))
    if isinstance(widget.get("fno"), dict):
        parts.append(_fno_part(widget["fno"]))
    if isinstance(widget.get("aif_pms"), dict) and not widget["aif_pms"].get("available"):
        parts.append("AIF/PMS data: not available (no AIF or PMS source exists in the data platform)")
    return parts


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
    parts.extend(_extra_parts(widget))
    return " · ".join(parts) if parts else "Market snapshot unavailable"


async def _none() -> Tuple[Any, Optional[str]]:
    return None, None


def _plus_days(iso: Optional[str], n: int) -> Optional[str]:
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat() if iso else None


async def _read(path: str, params: Optional[Dict[str, Any]] = None,
                label: Optional[str] = None) -> Tuple[Any, Optional[str]]:
    """(body, None) or (None, the reason it is missing). A failing source is said, never silent."""
    from . import daas_client
    try:
        body = await daas_client._get(path, params=params)
    except Exception as exc:  # noqa: BLE001 — a missing block must be said, not silent
        logger.warning("market source %s failed: %s", path, exc)
        return None, str(exc)[:200]
    if body is None:
        return None, f"the {label or path.rstrip('/').rsplit('/', 1)[-1]} route was not found (HTTP 404)"
    return body, None


async def _global_read() -> Tuple[Any, Optional[str]]:
    try:
        from ..positional_engine import nse_live
        body = await nse_live.get_global_snapshot()
    except Exception as exc:  # noqa: BLE001
        logger.warning("global snapshot failed: %s", exc)
        return None, str(exc)[:200]
    return (body, None) if body else (None, "the vendor quote fetch returned nothing")


async def _option_summary(sym: str) -> Dict[str, Any]:
    """PCR / max pain for one index over its nearest option expiry strictly after the data's day (the contracts
    expiring on that day are at their last close, so their open interest says nothing about what comes next)."""
    from routes import fno as fno_routes
    body, err = await _read(f"/fno/{sym}/expiries")
    if err:
        return {"unavailable": err}
    as_of, live = fno_routes.live_option_expiries(body.get("data"))
    nxt = next((e for e in live if e["days_to_expiry"] > 0), None)
    if as_of is None or nxt is None:
        return {"unavailable": "no option expiry is listed after the data's day"}
    chain, err = await _read(f"/fno/{sym}/chain", {"expiry": nxt["expiry"]})
    if err:
        return {"unavailable": err}
    raw = chain.get("strikes")
    strikes = fno_routes.shape_strikes(raw)
    if not strikes:
        return {"unavailable": f"no option contracts for {sym} expiring {nxt['expiry']}"}
    sides = [i.get(k) for i in raw if isinstance(i, dict) for k in ("CE", "PE")]
    day = _date_str(chain.get("as_of")) or as_of
    return fno_routes.summarise_chain(strikes, fno_routes.find_spot(sides), day, nxt["expiry"])


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

    sector_body, sector_err = await _read("/desk/sector-returns")

    anchor = _date_str(snapshot.get("as_of_date"))
    (hol_body, hol_err), recent, yields, buildup, nifty, glob = await asyncio.gather(
        _read("/holidays", {"segment": "CM", "from": anchor, "to": _plus_days(anchor, 21), "limit": 100})
        if anchor else _none(),
        _read("/snapshots/market/recent", {"days": 21, "limit": 30}),
        _read("/macro/rbi-yields", {"tenor": "10Y", "limit": 4}),
        _read("/desk/fno-buildup"),
        _read("/indices/Nifty 50/constituents", {"limit": 100}, label="Nifty 50 list"),
        _global_read(),
    )
    events: Tuple[Any, Optional[str]] = (None, None)
    if anchor and not hol_err:
        rows = {_date_str(r.get("holiday_date")) for r in _rows(hol_body)}
        sessions = next_sessions(anchor, rows)
        events = await _read("/events/calendar", {"from_date": sessions[0], "to_date": sessions[-1], "limit": 5000})
    options = dict(zip(FNO_INDICES, await asyncio.gather(*(_option_summary(sym) for sym in FNO_INDICES))))

    extras = {
        "calendar": build_calendar(anchor, hol_body, hol_err, events[0], events[1], nifty[0], nifty[1]),
        "global": build_global(glob[0], glob[1]),
        "trend": build_trend(recent[0], recent[1], yields[0], yields[1]),
        "fno": build_fno(buildup[0], buildup[1], options),
    }
    widget = build_market_widget(snapshot, movers if isinstance(movers, dict) else None,
                                 build_sectors(sector_body, sector_err), extras)
    ok = bool(widget.get("indices") or widget.get("breadth"))
    return MarketResult(
        ok=ok,
        summary=market_summary(widget),
        widget=widget,
        data=snapshot,
        error=None if ok else "market snapshot unavailable",
    )
