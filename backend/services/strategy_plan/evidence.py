"""Evidence ledger of a strategy plan (PRD §16.3, §16.5, §17.5). Pure: raw source snapshots in, ledger items out.

A *source snapshot* is what `sources.py` read for one source, normalised to
    {"ok": bool, "data": <raw>, "error": str | None, "source": str, "as_of": "YYYY-MM-DD" | None, "version": str | None}
A source that was not read, or failed, is `ok: False`; its items are `unavailable` with the reason, never `neutral`.

Ledger item: {group, key, value, interpretation, direction, source, source_as_of, version}
    direction  supports | conflicts | neutral | unavailable, always relative to the user's direction. `neutral` means
               the figure was read and does not point either way; `unavailable` means it could not be read.
Groups (PRD §16.3): market_context, technical, fundamental, catalysts, derivatives, validation, portfolio_fit.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .rules import RULES

GROUPS = ("market_context", "technical", "fundamental", "catalysts", "derivatives", "validation", "portfolio_fit")
DIRECTIONS = ("supports", "conflicts", "neutral", "unavailable")


# ── snapshots ────────────────────────────────────────────────────────────────

def src_ok(data: Any, source: str, as_of: Optional[str] = None, version: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "data": data, "error": None, "source": source, "as_of": as_of, "version": version}


def src_fail(error: str, source: str) -> Dict[str, Any]:
    return {"ok": False, "data": None, "error": error, "source": source, "as_of": None, "version": None}


def snap(snaps: Dict[str, Any], key: str) -> Dict[str, Any]:
    s = snaps.get(key)
    return s if isinstance(s, dict) and "ok" in s else src_fail("this source was not read", key)


def num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def day10(v: Any) -> Optional[str]:
    s = str(v)[:10] if v else ""
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def item(group: str, key: str, value: Any, interpretation: str, direction: str, s: Dict[str, Any]) -> Dict[str, Any]:
    return {"group": group, "key": key, "value": value, "interpretation": interpretation, "direction": direction,
            "source": s.get("source"), "source_as_of": s.get("as_of"), "version": s.get("version")}


def unavailable(group: str, key: str, reason: str, s: Dict[str, Any]) -> Dict[str, Any]:
    return item(group, key, None, reason, "unavailable", s)


def rel(signal: Optional[str], direction: str) -> str:
    """supports | conflicts | neutral for a reading `signal` (up | down | flat) against the user's direction."""
    if signal is None:
        return "neutral"
    if direction == "bullish":
        return {"up": "supports", "down": "conflicts"}.get(signal, "neutral")
    if direction == "bearish":
        return {"down": "supports", "up": "conflicts"}.get(signal, "neutral")
    if direction == "neutral":
        return "supports" if signal == "flat" else "conflicts"
    return "neutral"            # volatility views: a price direction neither supports nor conflicts


def sign(x: Optional[float], band: float = 0.0) -> Optional[str]:
    if x is None:
        return None
    return "up" if x > band else "down" if x < -band else "flat"


def trend_of(values: Dict[str, Any]) -> Optional[str]:
    """Trend structure: up when close > EMA50 and EMA20 > EMA50; down when close < EMA50 and EMA20 < EMA50; else flat."""
    c, e20, e50 = num(values.get("close")), num(values.get("ema20")), num(values.get("ema50"))
    if c is None or e20 is None or e50 is None:
        return None
    if c > e50 and e20 > e50:
        return "up"
    if c < e50 and e20 < e50:
        return "down"
    return "flat"


# ── market context ───────────────────────────────────────────────────────────

def sector_strength(snaps: Dict[str, Any], d: str) -> Dict[str, Any]:
    """Sector strength by index MEMBERSHIP (never by matching a sector label): the desk sector indices whose list holds the
    stock, each with its 1-day / 1-week / 1-month return and its 1-month rank among the sector indices that have one.
    The rule is RULES["sector_strength"]."""
    g, key = "market_context", "sector_strength"
    sec, mem = snap(snaps, "sectors"), snap(snaps, "sector_members")
    if not sec["ok"]:
        return unavailable(g, key, f"Sector returns unavailable: {sec['error']}", sec)
    if not mem["ok"] or not isinstance(mem["data"], dict):
        return unavailable(g, key, f"Sector index lists unavailable: {mem['error']}", mem)
    m = mem["data"]
    sym, member_of, unreadable = m.get("symbol"), list(m.get("member_of") or []), m.get("unreadable") or {}
    if not member_of:
        if unreadable:
            return unavailable(g, key, f"{sym} was not found in the sector lists that were read, and {len(unreadable)} could not be read "
                                       f"({', '.join(sorted(unreadable))}), so its sector is unknown.", mem)
        return unavailable(g, key, f"{sym} is in none of the desk's sector index lists (nidp.index_constituents), so no sector reading is made.", mem)
    rule = RULES["sector_strength"]
    by_index = {r.get("index"): r for r in (sec["data"] or {}).get("sectors") or []}
    ranked = sorted((n for n in (num(r.get("ret_1m_pct")) for r in by_index.values()) if n is not None), reverse=True)
    n_ranked = len(ranked)
    band_n = math.ceil(n_ranked * rule["band_fraction"]) if n_ranked else 0
    matches: List[Dict[str, Any]] = []
    for idx in member_of:
        r = by_index.get(idx) or {}
        ret = num(r.get("ret_1m_pct"))
        rank = band = None
        if ret is not None:
            rank = 1 + sum(1 for x in ranked if x > ret)
            band = "top" if rank <= band_n else "bottom" if rank > n_ranked - band_n else "middle"
        matches.append({"index": idx, "date": r.get("date"), "ret_1d_pct": num(r.get("ret_1d_pct")), "ret_1w_pct": num(r.get("ret_1w_pct")),
                        "ret_1m_pct": ret, "rank_1m": rank, "of": n_ranked if ret is not None else None, "band": band})
    value = {"symbol": sym, "matches": matches, "as_of": sec["data"].get("as_of") or sec["as_of"], "lists_unreadable": sorted(unreadable), "rule": rule}
    def text(x: Dict[str, Any]) -> str:
        if x["ret_1m_pct"] is None:
            return f"{x['index']}: no 1-month return on record"
        return f"{x['index']} 1m {x['ret_1m_pct']:g}% (rank {x['rank_1m']} of {x['of']}, {x['band']} third; 1d {x['ret_1d_pct']}%, 1w {x['ret_1w_pct']}%)"
    ranked_m = [x for x in matches if x["band"]]
    if not ranked_m:
        return item(g, key, value, f"{sym} is in {', '.join(member_of)}, but no 1-month return is on record for it, so the sector cannot be ranked.", "unavailable", sec)
    votes = [rel({"top": "up", "bottom": "down", "middle": "flat"}[x["band"]], d) for x in ranked_m]
    sup, con = votes.count("supports"), votes.count("conflicts")
    direction = "supports" if sup > con else "conflicts" if con > sup else "neutral"
    return item(g, key, value, f"{sym} is in " + "; ".join(text(x) for x in matches) + f". Rule: 1-month rank among the sector indices, top/bottom third.", direction, sec)


def market_context(snaps: Dict[str, Any], d: str) -> List[Dict[str, Any]]:
    g, out = "market_context", []
    reg = snap(snaps, "regime")
    r = reg["data"] if reg["ok"] and isinstance(reg["data"], dict) else None
    if r is None or not r.get("key"):
        why = reg["error"] if not reg["ok"] else (r or {}).get("reason") or "the desk regime could not be worked out"
        for k in ("desk_regime", "breadth", "nifty_trend", "india_vix"):
            out.append(unavailable(g, k, f"Desk regime unavailable: {why}", reg))
    else:
        inp = r.get("inputs") or {}
        sig = {"bullish": "up", "bearish": "down", "sideways": "flat"}.get(r["key"])
        out.append(item(g, "desk_regime", {"key": r["key"], "label": r.get("label")},
                        f"Desk regime is {r.get('label')} (macro_engine.classify_desk_regime, session {r.get('date')})."
                        + ("" if sig else " Mixed or high-volatility regimes do not point one way."), rel(sig, d), reg))
        b = inp.get("breadth")
        if b is None:
            out.append(unavailable(g, "breadth", "No advances/declines on record for the regime's session.", reg))
        else:
            out.append(item(g, "breadth", {"breadth": b, "advancing_share_pct": inp.get("advancing_share_pct"),
                                           "advances": inp.get("advances"), "declines": inp.get("declines")},
                            f"Market breadth {b} ({inp.get('advancing_share_pct')}% advancing).",
                            rel({"up": "up", "down": "down", "even": "flat"}.get(b), d), reg))
        t = inp.get("trend")
        if t is None:
            out.append(unavailable(g, "nifty_trend", "No Nifty close or 50-session average for the session.", reg))
        else:
            out.append(item(g, "nifty_trend", {"trend": t, "nifty_vs_average_pct": inp.get("nifty_vs_average_pct")},
                            f"Nifty is {t} against its 50-session average ({inp.get('nifty_vs_average_pct')}%); Nifty closes from {inp.get('nifty_source') or 'an unnamed source'}.", rel(t, d), reg))
        vix = num(inp.get("india_vix"))
        if vix is None:
            out.append(unavailable(g, "india_vix", "No India VIX close on record for the session.", reg))
        else:
            out.append(item(g, "india_vix", {"india_vix": vix, "volatility_high": inp.get("volatility_high")},
                            f"India VIX {vix:g} ({'high' if inp.get('volatility_high') else 'not high'} by the desk rule).",
                            "neutral", reg))
    out.append(sector_strength(snaps, d))
    return out


# ── technical ────────────────────────────────────────────────────────────────

SETUP_BUCKETS = {"breakout_confirmed": "up", "trend_continuation": "up", "pre_breakout": None, "true_accumulation": None}


def technical(snaps: Dict[str, Any], d: str) -> List[Dict[str, Any]]:
    g, out = "technical", []
    ind = snap(snaps, "indicators")
    if not ind["ok"] or not isinstance(ind["data"], dict):
        for k in ("trend_structure", "momentum", "relative_strength", "atr", "volume", "levels"):
            out.append(unavailable(g, k, f"Price indicators unavailable: {ind['error']}", ind))
    else:
        v = ind["data"].get("values") or {}
        t = trend_of(v)
        out.append(unavailable(g, "trend_structure", "Needs the close and the 20- and 50-day EMAs.", ind) if t is None else
                   item(g, "trend_structure", {k: v.get(k) for k in ("close", "ema20", "ema50", "ema200")},
                        f"Trend {t}: close {v.get('close'):.2f} vs EMA50 {v.get('ema50'):.2f}, EMA20 {v.get('ema20'):.2f}.", rel(t, d), ind))
        hist, roc, rsi = num(v.get("macd_hist")), num(v.get("roc20")), num(v.get("rsi14"))
        if hist is None or roc is None:
            out.append(unavailable(g, "momentum", "Needs MACD histogram and 20-day rate of change.", ind))
        else:
            sg = "up" if hist > 0 and roc > 0 else "down" if hist < 0 and roc < 0 else "flat"
            note = ""
            if rsi is not None and rsi >= RULES["rsi"]["stretched_above"]:
                note = f" RSI {rsi:.0f} is stretched."
            elif rsi is not None and rsi <= RULES["rsi"]["weak_below"]:
                note = f" RSI {rsi:.0f} is weak."
            out.append(item(g, "momentum", {"rsi14": rsi, "macd_hist": hist, "roc20": roc},
                            f"MACD histogram {hist:+.2f}, 20-day change {roc:+.2f}%.{note}", rel(sg, d), ind))
        rs = v.get("rs63")
        if not isinstance(rs, dict) or num(rs.get("excess_pct")) is None:
            reason = ((ind["data"].get("benchmark") or {}).get("reason")) or "Needs 64 sessions of the stock and the benchmark."
            out.append(unavailable(g, "relative_strength", reason, ind))
        else:
            ex = num(rs["excess_pct"])
            out.append(item(g, "relative_strength", rs, f"63-session return {ex:+.2f}% against the benchmark.",
                            rel(sign(ex, RULES["rs_flat_band_pct"]), d), ind))
        atr, atrp = num(v.get("atr14")), num(v.get("atr_pct"))
        out.append(unavailable(g, "atr", "ATR(14) needs 15 usable sessions.", ind) if atr is None else
                   item(g, "atr", {"atr14": atr, "atr_pct": atrp}, f"ATR(14) {atr:.2f} ({atrp:.2f}% of the close)." if atrp is not None else f"ATR(14) {atr:.2f}.", "neutral", ind))
        rv, tv = num(v.get("rvol20")), num(v.get("avg_traded_value_cr20"))
        out.append(unavailable(g, "volume", "Needs 20 sessions of volume.", ind) if rv is None and tv is None else
                   item(g, "volume", {"rvol20": rv, "avg_traded_value_cr20": tv},
                        f"Relative volume {rv if rv is not None else 'n/a'}x; average traded value {tv if tv is not None else 'n/a'} Cr a day.", "neutral", ind))
        sup, res = num(v.get("support20")), num(v.get("resistance20"))
        out.append(unavailable(g, "levels", "Needs 20 sessions.", ind) if sup is None and res is None else
                   item(g, "levels", {"support20": sup, "resistance20": res}, f"20-session support {sup} and resistance {res}.", "neutral", ind))
    pat = snap(snaps, "patterns")
    if not pat["ok"]:
        out.append(unavailable(g, "chart_patterns", f"Pattern engine unavailable: {pat['error']}", pat))
    else:
        live = [p for p in (pat["data"] or {}).get("patterns") or [] if p.get("state") in ("confirmed", "awaiting_confirmation")][:3]
        if not live:
            out.append(item(g, "chart_patterns", [], "No chart pattern is confirmed or awaiting confirmation.", "neutral", pat))
        for p in live:
            sg = {"bullish": "up", "bearish": "down"}.get(str(p.get("direction") or "").lower())
            direction = rel(sg, d) if p.get("state") == "confirmed" else "neutral"
            out.append(item(g, "chart_pattern:" + str(p.get("pattern_type")),
                            {k: p.get(k) for k in ("pattern_type", "label", "direction", "state", "detected_on", "levels")},
                            f"{p.get('label')} ({p.get('direction')}) is {p.get('state').replace('_', ' ')}: {p.get('state_reason')}", direction, pat))
    sb = snap(snaps, "scanner_bucket")
    if not sb["ok"]:
        out.append(unavailable(g, "scanner_setup", f"Scanner watchlist unavailable: {sb['error']}", sb))
    else:
        b = (sb["data"] or {}).get("bucket")
        sg = SETUP_BUCKETS.get(b)
        out.append(item(g, "scanner_setup", {"bucket": b, "as_of": sb["as_of"]},
                        (f"The scanner lists it in the {b.replace('_', ' ')} bucket." if b else "It is in none of the scanner's four buckets.")
                        + " A scanner bucket is a rule match, not a probability and not validated.",
                        rel(sg, d) if b in SETUP_BUCKETS else "neutral", sb))
    if "chartink" in snaps:
        out.append(chartink_item(snaps, d))
    sr = snap(snaps, "scan_row")
    if not sr["ok"]:
        out.append(unavailable(g, "scanner_gates", f"Scan snapshot unavailable: {sr['error']}", sr))
    else:
        row = sr["data"] or {}
        out.append(item(g, "scanner_gates", {k: row.get(k) for k in ("eligible", "exclusion", "liquidity_class", "risk_class", "traded_value_cr_20d")},
                        "Eligible for the scanner universe." if row.get("eligible") else f"Not in the scanner universe: {row.get('exclusion')}.",
                        "neutral", sr))
    return out


def chartink_item(snaps: Dict[str, Any], d: str) -> Dict[str, Any]:
    """The user's Chartink scans as evidence (rules.RULES["chartink"]["evidence"]). A bullish-tagged hit is an up signal and a bearish-tagged hit a down
    signal; hits of both tags are neutral. A scan is a rule match the user chose, not validated and not a probability. Only for a bullish or bearish view."""
    g, ck = "technical", snap(snaps, "chartink")
    if not ck["ok"]:
        return unavailable(g, "chartink_scans", f"Chartink scans unavailable: {ck['error']}", ck)
    data = ck["data"] or {}
    hits = data.get("hits") or []
    when = f"fetched {data.get('fetched_at')} for {data.get('scan_date')}"
    names = [h.get("name") for h in hits]
    up, down = [h for h in hits if h.get("direction") == "bullish"], [h for h in hits if h.get("direction") == "bearish"]
    value = {"scans": [{k: h.get(k) for k in ("id", "name", "direction")} for h in hits], "count": len(hits), "enabled_scans": data.get("enabled_scans"),
             "fetched_at": data.get("fetched_at"), "scan_date": data.get("scan_date"), "mode": data.get("mode")}
    note = " A scan is a rule match the user chose, not validated and not a probability."
    if not hits:
        return item(g, "chartink_scans", value, f"None of the {data.get('enabled_scans')} enabled Chartink scans listed it ({when}).", "neutral", ck)
    text = f"Listed by {len(hits)} Chartink scan(s) ({when}): " + ", ".join(str(n) for n in names) + "." + note
    if up and down:
        return item(g, "chartink_scans", value, text + " Bullish-tagged and bearish-tagged scans both listed it, so it points neither way.", "neutral", ck)
    signal = "up" if up else "down" if down else None
    return item(g, "chartink_scans", value, text, rel(signal, d) if d in ("bullish", "bearish") else "neutral", ck)


# ── fundamental (context) ────────────────────────────────────────────────────

VALUATION_FIELDS = ("pe_ttm", "pb", "roe_pct", "roce_pct", "debt_to_equity", "market_cap_cr")


def peer_context(peers: Dict[str, Any], own: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(valuation context, None) or (None, reason). Medians over peers with a positive P/E (P/B, ROE: any value)."""
    rows = [p for p in peers.get("peers") or [] if isinstance(p, dict)]
    need = RULES["valuation_peers"]["min_peers"]
    if len(rows) < need:
        return None, f"Only {len(rows)} same-industry peer(s) have valuation figures; the rule needs {need}."

    def med(key: str, positive: bool = False) -> Tuple[Optional[float], int]:
        xs = [x for x in (num(p.get(key)) for p in rows) if x is not None and (x > 0 or not positive)]
        return (round(statistics.median(xs), 2) if xs else None), len(xs)

    pe, pe_n = med("pe_ttm", True)
    pb, pb_n = med("pb", True)
    roe, roe_n = med("roe_pct")
    own_pe, own_pb, own_roe = num(own.get("pe_ttm")), num(own.get("pb")), num(own.get("roe_pct"))
    ctx = {"industry": peers.get("industry"), "peer_count": len(rows),
           "median_pe": pe, "median_pe_n": pe_n, "median_pb": pb, "median_pb_n": pb_n, "median_roe_pct": roe, "median_roe_n": roe_n,
           "stock_pe": own_pe, "stock_pb": own_pb, "stock_roe_pct": own_roe,
           "pe_vs_median_pct": round((own_pe / pe - 1) * 100, 1) if own_pe and own_pe > 0 and pe else None,
           "pb_vs_median_pct": round((own_pb / pb - 1) * 100, 1) if own_pb and own_pb > 0 and pb else None}
    return ctx, None


def fundamental(snaps: Dict[str, Any], d: str, asof: Optional[str] = None) -> List[Dict[str, Any]]:
    g, out = "fundamental", []
    f = snap(snaps, "features")
    row = f["data"] if f["ok"] and isinstance(f["data"], dict) else None
    role = " Shown as context (valuation and quality), not as a short-horizon trigger."
    src_note = f" Source column fundamentals_source: {row.get('fundamentals_source')}." if row and row.get("fundamentals_source") else ""
    for k in VALUATION_FIELDS:
        if row is None:
            out.append(unavailable(g, k, f"Fundamental columns unavailable: {f['error']}", f))
        elif num(row.get(k)) is None:
            out.append(unavailable(g, k, f"{k} is empty in the latest feature row ({f['as_of']}).", f))
        else:
            out.append(item(g, k, num(row[k]), f"{k} = {num(row[k]):g} as of {f['as_of']}.{src_note}{role}", "neutral", f))
    p = snap(snaps, "peers")
    if not p["ok"]:
        out.append(unavailable(g, "valuation_vs_peers", f"Peer valuation unavailable: {p['error']}", p))
    else:
        ctx, why = peer_context(p["data"] or {}, row or {})
        if ctx is None:
            out.append(unavailable(g, "valuation_vs_peers", why, p))
        else:
            out.append(item(g, "valuation_vs_peers", ctx,
                            f"Against {ctx['peer_count']} {ctx['industry']} peers: median P/E {ctx['median_pe']} (n={ctx['median_pe_n']}), "
                            f"median P/B {ctx['median_pb']} (n={ctx['median_pb_n']}), median ROE {ctx['median_roe_pct']}% (n={ctx['median_roe_n']})."
                            + role, "neutral", p))
    fin = snap(snaps, "financials")
    if not fin["ok"]:
        out.append(unavailable(g, "quarterly_trend", f"Quarterly financials unavailable: {fin['error']}", fin))
    else:
        data = fin["data"] or {}
        rows = data.get("rows") or []
        latest = rows[0] if rows else {}
        out.append(item(g, "quarterly_trend",
                        {"latest_quarter": data.get("latest_quarter"), "growth_trend": data.get("growth_trend"),
                         "revenue_yoy_pct": latest.get("revenue_yoy_pct"), "pat_cr": latest.get("pat_cr"),
                         "ebitda_margin_pct": latest.get("ebitda_margin_pct"), "quarters": data.get("quarters_count")},
                        f"Latest quarter {data.get('latest_quarter')}: growth trend {data.get('growth_trend')}." + role, "neutral", fin))
    out.append(item(g, "analyst_estimates", None,
                    "Not available: the data platform holds no analyst estimates or management guidance (PRD §17.2 #1). nidp.earnings_estimates "
                    "(migration 114) exists but no loader in this repository fills it, and it was empty when last checked (2026-10-20).",
                    "unavailable", src_fail("no source exists", "none")))
    out += cash_flow_items(snaps, d)
    out += ownership_items(snaps, d, day_of(asof))
    return out


# ── cash-flow quality and ownership (fundamental, context) ───────────────────

def day_of(v: Any) -> Optional[date]:
    s = day10(v)
    return date.fromisoformat(s) if s else None


def cash_flow_items(snaps: Dict[str, Any], d: str) -> List[Dict[str, Any]]:
    """Cash-flow quality from the feature row's cfo_pat_ratio, and the free-cash-flow sign (no source reaches it)."""
    g, C = "fundamental", RULES["cash_flow"]
    f = snap(snaps, "features")
    fcf = unavailable(g, "free_cash_flow", "Free cash flow needs capex: nidp.nse_financials_cashflow (capex_cr) is empty on staging and no data route reads it. "
                      "Loaders that fill it: python -m nidp.services.nse_financials.yahoo_fundamentals or nse_financials.backfill_screener.",
                      src_fail("no source reachable", "nidp.nse_financials_cashflow"))
    if not f["ok"] or not isinstance(f["data"], dict):
        return [unavailable(g, "cash_flow_quality", f"Cash-flow quality unavailable: {f['error'] or 'no feature row'}", f), fcf]
    ratio = num(f["data"].get("cfo_pat_ratio"))
    if ratio is None:
        return [unavailable(g, "cash_flow_quality",
                            f"cfo_pat_ratio is empty in the latest feature row ({f['as_of']}): it is the latest year's cash from operations over trailing profit, and "
                            "nidp.nse_financials_cashflow has no rows to compute it from. Loader: python -m nidp.services.nse_financials.yahoo_fundamentals.", f), fcf]
    how = (f" CFO / profit after tax {ratio:g} as of {f['as_of']} (latest financial year's CFO over trailing-twelve-month PAT; the financial year end is not in the "
           f"feature row). Heuristic: at or above {C['strong_at_or_above']:g} the profit is backed by cash, below {C['weak_below']:g} it is not. Shown as context.")
    if ratio < 0:
        return [item(g, "cash_flow_quality", {"cfo_pat_ratio": ratio}, "Cash from operations and profit have opposite signs." + how + " No direction is read from a negative ratio.", "neutral", f), fcf]
    signal = "up" if ratio >= C["strong_at_or_above"] else "down" if ratio < C["weak_below"] else "flat"
    return [item(g, "cash_flow_quality", {"cfo_pat_ratio": ratio, "strong_at_or_above": C["strong_at_or_above"], "weak_below": C["weak_below"]},
                 {"up": "Profit is backed by operating cash.", "down": "Profit is poorly backed by operating cash.", "flat": "Cash conversion is in the middle band."}[signal] + how,
                 rel(signal, d), f), fcf]


OWNERSHIP_FIELDS = (
    ("promoter", "promoter_pct", "Promoter holding", 1),
    ("pledge", "promoter_pledged_pct", "Promoter pledge", -1),
    ("fii", "fii_pct", "FII holding", 1),
    ("dii", "dii_pct", "DII holding", 1),
    ("mf", "mf_pct", "Mutual-fund holding", 1),
)


def ownership_series(rows: List[Dict[str, Any]], column: str) -> List[Tuple[str, float]]:
    """(period_end, value), newest first, one per quarter: the first row listed that has the figure (the route lists NSE_SHP first)."""
    seen: Dict[str, float] = {}
    for r in rows:
        p, v = day10(r.get("period_end")), num(r.get(column))
        if p and v is not None and p not in seen:
            seen[p] = v
    return sorted(seen.items(), reverse=True)


def ownership_items(snaps: Dict[str, Any], d: str, today: Optional[date]) -> List[Dict[str, Any]]:
    g, O = "fundamental", RULES["ownership"]
    out: List[Dict[str, Any]] = []
    sh = snap(snaps, "shareholding")
    rows = [r for r in (sh["data"] or []) if isinstance(r, dict)] if sh["ok"] and isinstance(sh["data"], list) else []
    if not sh["ok"]:
        out.append(unavailable(g, "ownership_changes", f"Shareholding history unavailable: {sh['error']}", sh))
    elif not rows:
        out.append(unavailable(g, "ownership_changes", "No shareholding rows are stored for this stock.", sh))
    else:
        for key, column, label, good in OWNERSHIP_FIELDS:
            k = "ownership_" + key
            series = ownership_series(rows, column)
            if not series:
                extra = " Mutual-fund percentages were fixed in the parser and fill in only after a re-ingest." if key == "mf" else ""
                out.append(unavailable(g, k, f"{column} is empty in every stored quarter ({len({day10(r.get('period_end')) for r in rows})} read).{extra}", sh))
                continue
            if len(series) < 2:
                out.append(unavailable(g, k, f"Only one quarter has {column} ({series[0][0]}); a change needs two quarters.", {**sh, "as_of": series[0][0]}))
                continue
            (p1, v1), (p0, v0) = series[0], series[1]
            change = round(v1 - v0, 2)
            band = O["min_change_pp"]
            move = "up" if change > band else "down" if change < -band else "flat"
            signal = move if good > 0 else {"up": "down", "down": "up", "flat": "flat"}[move]
            months = round((date.fromisoformat(p1) - date.fromisoformat(p0)).days / 30.4)
            gap = f" The two figures are {months} months apart, not consecutive quarters." if months > 4 else ""
            stale = f" The newest figure is {p1}, older than {O['stale_after_days']} days before the last session." if today and (today - date.fromisoformat(p1)).days > O["stale_after_days"] else ""
            word = {"up": "rose", "down": "fell", "flat": "moved within the band"}[move]
            out.append(item(g, k, {"column": column, "latest": {"period_end": p1, "value": v1}, "previous": {"period_end": p0, "value": v0}, "change_pp": change,
                                   "min_change_pp": band}, f"{label} {word}: {v1:g}% at {p1} against {v0:g}% at {p0} ({change:+g} pp; changes inside +/-{band:g} pp are flat)."
                            + gap + stale + (" A rising pledge is adverse." if key == "pledge" else ""), rel(signal, d), {**sh, "as_of": p1}))
    out.append(deal_item(snap(snaps, "deals"), d))
    out.append(unavailable(g, "insider_sast", "Insider and SAST disclosures are not read: nidp.insider_sast has no rows on staging (loader research/trendlyne/bin/insider_sast_to_pg.py "
                                              "is on feat/provider-foundations only) and no data route reads it.", src_fail("no source reachable", "nidp.insider_sast")))
    return out


def deal_item(s: Dict[str, Any], d: str) -> Dict[str, Any]:
    g, O, key = "fundamental", RULES["ownership"], "bulk_block_deals"
    if not s["ok"]:
        return unavailable(g, key, f"Bulk and block deals unavailable: {s['error']}", s)
    data = s["data"] or {}
    rows = [r for r in data.get("rows") or [] if isinstance(r, dict)]
    win, cov = data.get("window") or {}, day10(data.get("coverage_from"))
    partial = ""
    if cov is None:
        partial = " The start of the stored deal history is unknown."
    elif win.get("from") and (date.fromisoformat(cov) - date.fromisoformat(win["from"])).days > O["deal_coverage_tolerance_days"]:
        partial = f" The stored deal history starts {cov}, so the {win['from']} to {win.get('to')} window is only partly covered."
    buy = sum(num(r.get("quantity")) or 0 for r in rows if str(r.get("deal_type")).upper() == "BUY")
    sell = sum(num(r.get("quantity")) or 0 for r in rows if str(r.get("deal_type")).upper() == "SELL")
    base = {"window": win, "count": len(rows), "coverage_from": cov}
    if not rows:
        return item(g, key, {**base, "net_quantity": 0, "buy_quantity": 0, "sell_quantity": 0, "latest_deal_date": None},
                    f"No bulk or block deal recorded between {win.get('from')} and {win.get('to')}.{partial}", "neutral", s)
    pcts = [((num(r.get("pct_of_shares")) or 0) * (1 if str(r.get("deal_type")).upper() == "BUY" else -1 if str(r.get("deal_type")).upper() == "SELL" else 0))
            for r in rows if num(r.get("pct_of_shares")) is not None]
    latest = max(day10(r.get("as_of_date")) or "" for r in rows) or None
    value = {**base, "net_quantity": buy - sell, "buy_quantity": buy, "sell_quantity": sell, "latest_deal_date": latest,
             "net_pct_of_shares": round(sum(pcts), 4) if pcts else None,
             "deals": [{k: r.get(k) for k in ("as_of_date", "kind", "client_name", "deal_type", "quantity", "avg_price", "pct_of_shares")} for r in rows[:10]]}
    head = f"{len(rows)} bulk/block deal(s) between {win.get('from')} and {win.get('to')}: bought {buy:,.0f}, sold {sell:,.0f} shares (latest {latest})."
    if not pcts:
        return item(g, key, value, head + " The company's share count is missing, so the size against its shares cannot be judged; no direction is read." + partial, "neutral", s)
    net = value["net_pct_of_shares"]
    band = O["deal_min_net_pct_of_shares"]
    signal = "up" if net > band else "down" if net < -band else "flat"
    return item(g, key, value, f"{head} Net {net:+g}% of the company's shares (deals inside +/-{band:g}% are flat)." + partial, rel(signal, d), s)



# ── catalysts and event risk ─────────────────────────────────────────────────

def window(asof: Optional[str], days: int) -> Tuple[Optional[str], Optional[str]]:
    a = day10(asof)
    return (a, (date.fromisoformat(a) + timedelta(days=days)).isoformat()) if a else (None, None)


def events_in_horizon(snaps: Dict[str, Any], asof: Optional[str], horizon_days: int) -> List[Dict[str, Any]]:
    """Result and other scheduled events dated after `asof` and within the horizon."""
    ev = snap(snaps, "events")
    lo, hi = window(asof, horizon_days)
    if not ev["ok"] or lo is None:
        return []
    rows = ev["data"] if isinstance(ev["data"], list) else []
    return [r for r in rows if isinstance(r, dict) and day10(r.get("event_date")) and lo < day10(r["event_date"]) <= hi]


def catalysts(snaps: Dict[str, Any], d: str, asof: Optional[str], horizon_days: int) -> List[Dict[str, Any]]:
    g, out = "catalysts", []
    ev = snap(snaps, "events")
    if not ev["ok"] or asof is None:
        out.append(unavailable(g, "results_and_events", f"Event calendar unavailable: {ev['error'] or 'no as-of date'}", ev))
    else:
        inside = events_in_horizon(snaps, asof, horizon_days)
        results = [r for r in inside if str(r.get("event_type")) == "quarterly_results"]
        brief = [{"event_type": r.get("event_type"), "event_date": day10(r.get("event_date")), "purpose": r.get("purpose")} for r in inside]
        if results:
            out.append(item(g, "results_and_events", brief, f"Quarterly results are scheduled on {day10(results[0]['event_date'])}, inside the {horizon_days}-day horizon: gap risk.", "conflicts", ev))
        else:
            out.append(item(g, "results_and_events", brief, f"No results date inside the {horizon_days}-day horizon" + (f"; {len(inside)} other event(s) are." if inside else "."), "neutral", ev))
    ca = snap(snaps, "corporate_actions")
    if not ca["ok"]:
        out.append(unavailable(g, "corporate_actions", f"Corporate actions unavailable: {ca['error']}", ca))
    else:
        lo, hi = window(asof, horizon_days)
        rows = [r for r in (ca["data"] or []) if isinstance(r, dict) and lo and day10(r.get("ex_date")) and lo < day10(r["ex_date"]) <= hi]
        brief = [{"action_type": r.get("action_type"), "ex_date": day10(r.get("ex_date")), "purpose": r.get("purpose")} for r in rows]
        out.append(item(g, "corporate_actions", brief,
                        (f"{len(rows)} corporate action(s) go ex inside the horizon: prices and strikes can be adjusted." if rows else "No ex-date inside the horizon."),
                        "conflicts" if rows else "neutral", ca))
    fl = snap(snaps, "announcements")
    if not fl["ok"]:
        out.append(unavailable(g, "recent_filings", f"Filings feed unavailable: {fl['error']}", fl))
    else:
        rows = [r for r in (fl["data"] or []) if isinstance(r, dict)]
        pos = sum(1 for r in rows if r.get("sentiment") == "positive")
        neg = sum(1 for r in rows if r.get("sentiment") == "negative")
        high = sum(1 for r in rows if r.get("impact_score") == "high")
        brief = [{k: r.get(k) for k in ("subject", "filed_at", "event_category", "impact_score", "sentiment")} for r in rows[:5]]
        sg = "up" if pos > neg else "down" if neg > pos else "flat"
        out.append(item(g, "recent_filings", {"count": len(rows), "positive": pos, "negative": neg, "high_impact": high, "latest": brief},
                        f"{len(rows)} filing(s) in the last {RULES['catalysts']['filings_days']} days: {pos} positive, {neg} negative, {high} high impact (classifier labels).",
                        rel(sg, d) if rows else "neutral", fl))
    return out


# ── derivatives ──────────────────────────────────────────────────────────────

BUILDUP_SIGNAL = {"long_buildup": "up", "short_buildup": "down", "short_covering": "flat", "long_unwinding": "flat", "neutral": "flat"}


def derivatives(snaps: Dict[str, Any], d: str, ref_session: Optional[str]) -> List[Dict[str, Any]]:
    g, out = "derivatives", []
    bu = snap(snaps, "buildup")
    if not bu["ok"]:
        for k in ("oi_buildup", "cash_confirmation"):
            out.append(unavailable(g, k, f"F&O build-up unavailable: {bu['error']}", bu))
    else:
        r = bu["data"] or {}
        label = r.get("label")
        out.append(item(g, "oi_buildup", {k: r.get(k) for k in ("label", "price_move", "oi", "oi_chg", "oi_chg_pct", "days_to_expiry", "risk_flags")},
                        f"Futures OI build-up: {label}. A heuristic reading of price and open interest, not proof of intent.",
                        rel(BUILDUP_SIGNAL.get(label), d) if label else "neutral", bu))
        cc = r.get("cash_confirmation")
        out.append(unavailable(g, "cash_confirmation", "Futures or cash move is flat or missing: nothing to compare.", bu) if cc is None else
                   item(g, "cash_confirmation", {"cash_confirmation": cc, "cash_chg_pct": r.get("cash_chg_pct")},
                        f"The cash market {cc} the futures move.", "neutral", bu))
    fu = snap(snaps, "futures")
    if not fu["ok"]:
        out.append(unavailable(g, "nearest_future", f"Futures unavailable: {fu['error']}", fu))
    else:
        data = fu["data"] or {}
        contracts = data.get("futures") or []
        near = contracts[0] if contracts else None
        if near is None:
            out.append(unavailable(g, "nearest_future", "No futures contract listed.", fu))
        else:
            out.append(item(g, "nearest_future", {k: near.get(k) for k in ("expiry", "settle", "basis", "oi", "change_in_oi", "volume")} | {"lot_size": data.get("lot_size")},
                            f"Nearest future {near.get('expiry')} settles {near.get('settle')} (basis {near.get('basis')}).", "neutral", fu))
            if near.get("change_pct") is None:
                out.append(unavailable(g, "future_day_change", "The futures day change is null (prev_close_price not selected by the data route). Dependency: feat/strategy-hardening.", fu))
            else:
                out.append(item(g, "future_day_change", {"change": near.get("change"), "change_pct": near.get("change_pct"), "oi_buildup": near.get("oi_buildup")},
                                f"Future moved {near.get('change_pct')}% on the day.", "neutral", fu))
    ch = snap(snaps, "chain")
    if not ch["ok"]:
        for k in ("option_chain", "bid_ask"):
            out.append(unavailable(g, k, f"Option chain unavailable: {ch['error']}", ch))
    else:
        c = ch["data"] or {}
        s = c.get("summary") or {}
        stale = bool(ref_session and ch["as_of"] and ch["as_of"] < ref_session)
        out.append(item(g, "chain_freshness", {"as_of": ch["as_of"], "reference_session": ref_session, "stale": stale},
                        (f"The chain is from {ch['as_of']}, older than the last completed session {ref_session}: delayed/historical, not a current actionable strike."
                         if stale else f"End-of-day chain for {s.get('expiry')} as of {ch['as_of']} (NSE F&O bhavcopy). Never live."), "conflicts" if stale else "neutral", ch))
        out.append(item(g, "chain_positioning", {k: s.get(k) for k in ("expiry", "days_to_expiry", "spot", "atm_strike", "pcr", "max_pain", "max_call_oi", "max_put_oi", "total_call_oi", "total_put_oi")},
                        f"PCR {s.get('pcr')}, max pain {s.get('max_pain')}, call wall {(s.get('max_call_oi') or {}).get('strike')}, put wall {(s.get('max_put_oi') or {}).get('strike')}.", "neutral", ch))
        out.append(unavailable(g, "atm_iv_expected_move", "ATM IV or the expected move could not be worked out for this expiry.", ch)
                   if s.get("atm_iv") is None and s.get("expected_move") is None else
                   item(g, "atm_iv_expected_move", {"atm_iv": s.get("atm_iv"), "expected_move": s.get("expected_move"), "expected_move_pct": s.get("expected_move_pct"), "forward_basis": s.get("forward_basis")},
                        f"ATM IV {s.get('atm_iv')}%, expected move ±{s.get('expected_move')} ({s.get('expected_move_pct')}%): a market price for movement, not a forecast.", "neutral", ch))
        atm = next((r for r in c.get("strikes") or [] if r.get("strike") == s.get("atm_strike")), None)
        liq = {side: {"oi": (atm or {}).get(side, {}).get("oi"), "volume": (atm or {}).get(side, {}).get("volume")} for side in ("call", "put")} if atm else None
        out.append(item(g, "liquidity_proxy", liq, "Liquidity proxy: open interest and volume at the ATM strike. The end-of-day bhavcopy has no bid/ask.", "neutral", ch)
                   if liq else unavailable(g, "liquidity_proxy", "The ATM strike is not in the chain window.", ch))
        out.append(bid_ask_item(snap(snaps, "broker_quotes"), ch))
    return out


def bid_ask_item(q: Dict[str, Any], ch: Dict[str, Any]) -> Dict[str, Any]:
    """Live bid/ask of the chain's ATM call and put from the user's own broker session; unavailable otherwise (the F&O file has none)."""
    g, Q = "derivatives", RULES["quotes"]
    eod = "the end-of-day F&O file carries no bid or ask; OI and volume are the liquidity proxy and fills are not assumed at mid."
    quotes = ((q["data"] or {}).get("quotes") or []) if q["ok"] else []
    if not quotes:
        why = q["error"] if not q["ok"] else "; ".join((q["data"] or {}).get("skipped") or []) or "the broker returned no usable quote"
        return unavailable(g, "bid_ask", f"Not available: {eod} No live broker quote was read ({why}).", q if not q["ok"] else {**q, "ok": False})
    data = q["data"]
    modes = {x.get("mode") for x in quotes}
    mode = "live" if modes == {"live"} else "delayed" if "delayed" in modes else "untimed"
    at = str(data.get("read_at") or "")[11:16]
    wide = [x for x in quotes if (num(x.get("spread_pct")) or 0) > Q["wide_spread_pct"]]
    parts = "; ".join(f"{x.get('label')}: bid {x.get('bid'):g} x ask {x.get('ask'):g} (spread {x.get('spread_pct')}% of mid)" for x in quotes)
    note = {"live": "Quote is live", "delayed": "Quote is delayed (last trade older than the live limit)", "untimed": "Quote has no trade time"}[mode]
    flag = f" Wide spread (over {Q['wide_spread_pct']:g}% of mid): expect to pay it; do not assume a fill at mid." if wide else ""
    return item(g, "bid_ask", {"mode": mode, "broker": data.get("display"), "read_at": data.get("read_at"), "quotes": quotes},
                f"{note}: read from {data.get('display')} at {at} IST, read-only (no order placed). {parts}.{flag}", "neutral", q)


# ── validation ───────────────────────────────────────────────────────────────

VALIDATION_REASONS = [
    "No out-of-sample study exists for these rules (PRD §16.9 Validation Gate not passed).",
    "The scanner and the strategy rules are documented heuristics; a scanner score is not a probability.",
    "The only historical record is the accumulation backtest: in-sample and price-only (no costs, no regime split).",
]


def validation(snaps: Dict[str, Any], horizon_days: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    g = "validation"
    cal = snap(snaps, "calibration")
    block: Dict[str, Any] = {"status": "not_validated", "reasons": list(VALIDATION_REASONS), "in_sample_record": None,
                             "label": "in-sample, price-only, no costs; not out-of-sample"}
    items: List[Dict[str, Any]] = [item(g, "validation_status", "not_validated", "; ".join(VALIDATION_REASONS), "neutral",
                                        src_ok(None, "strategy-plan validation gate", None, RULES["version"]))]
    if not cal["ok"]:
        items.append(unavailable(g, "accumulation_backtest", f"Accumulation backtest record unavailable: {cal['error']}", cal))
        return items, block
    data = cal["data"] or {}
    matched = [b for b in data.get("buckets") or [] if b.get("matched")]
    if not matched:
        why = data.get("empty_reason") or data.get("symbol_reason") or "The stock's accumulation score falls in no recorded bucket."
        items.append(unavailable(g, "accumulation_backtest", why, cal))
        return items, block
    best_h = min({b.get("horizon_days") for b in matched if b.get("horizon_days") is not None} or {None}, key=lambda h: abs((h or 0) - horizon_days))
    rec = [{k: b.get(k) for k in ("metric", "horizon_days", "sample_count", "moves_count", "probability", "ci95_lo", "ci95_hi", "avg_fwd_return", "avg_fwd_drawdown")}
           for b in matched if b.get("horizon_days") == best_h]
    block["in_sample_record"] = {"sample": data.get("sample"), "symbol_score": data.get("symbol_score"), "rows": rec,
                                 "source": data.get("source"), "label": block["label"]}
    items.append(item(g, "accumulation_backtest", rec, "Historical outcomes for the stock's accumulation-score bucket: " + block["label"] + ". Not a forecast.", "neutral", cal))
    return items, block


# ── portfolio fit ────────────────────────────────────────────────────────────

def portfolio_fit(snaps: Dict[str, Any], symbol: str, sector: Optional[str]) -> List[Dict[str, Any]]:
    g = "portfolio_fit"
    p = snap(snaps, "portfolio")
    if not p["ok"]:
        return [unavailable(g, "existing_exposure", f"No portfolio: {p['error']}", p)]
    rows = [h for h in (p["data"] or []) if isinstance(h, dict)]
    if not rows:
        return [unavailable(g, "existing_exposure", "No holdings on record for this account.", p)]
    total = sum(num(h.get("value_rs")) or 0.0 for h in rows)
    own = [h for h in rows if str(h.get("nse_symbol") or h.get("symbol") or "").upper() == symbol]
    own_val = sum(num(h.get("value_rs")) or 0.0 for h in own)
    out = [item(g, "existing_exposure", {"held": bool(own), "value_rs": round(own_val, 2), "weight_pct": round(own_val / total * 100, 2) if total else None, "portfolio_value_rs": round(total, 2)},
                (f"Already held: {round(own_val / total * 100, 2)}% of the portfolio." if own and total else "Not held in the portfolio."), "neutral", p)]
    sec_rows = [h for h in rows if sector and str(h.get("sector") or "").strip().lower() == sector.strip().lower()]
    if sector and any(h.get("sector") for h in rows):
        sv = sum(num(h.get("value_rs")) or 0.0 for h in sec_rows)
        out.append(item(g, "sector_exposure", {"sector": sector, "value_rs": round(sv, 2), "weight_pct": round(sv / total * 100, 2) if total else None},
                        f"Portfolio exposure to {sector}: {round(sv / total * 100, 2) if total else 'n/a'}%.", "neutral", p))
    else:
        out.append(unavailable(g, "sector_exposure", "Holdings carry no sector label to compare with.", p))
    return out


# ── the ledger ───────────────────────────────────────────────────────────────

def build_ledger(snaps: Dict[str, Any], inputs: Dict[str, Any], asof: Optional[str], ref_session: Optional[str]) -> Dict[str, Any]:
    d, horizon = inputs["direction"], inputs["horizon_days"]
    sector = None
    for k in ("scan_row", "features"):
        s = snap(snaps, k)
        if s["ok"] and (s["data"] or {}).get("sector"):
            sector = s["data"]["sector"]
            break
    val_items, val_block = validation(snaps, horizon)
    items = (market_context(snaps, d) + technical(snaps, d) + fundamental(snaps, d, asof) + catalysts(snaps, d, asof, horizon)
             + derivatives(snaps, d, ref_session) + val_items + portfolio_fit(snaps, inputs["underlying"], sector))
    summary = {grp: {x: sum(1 for i in items if i["group"] == grp and i["direction"] == x) for x in DIRECTIONS} for grp in GROUPS}
    return {"items": items, "summary": summary, "validation": val_block}
