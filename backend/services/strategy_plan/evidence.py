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

def _sector_row(sectors: Dict[str, Any], sector: Optional[str]) -> Optional[Dict[str, Any]]:
    if not sector:
        return None
    want = sector.strip().lower()
    for r in sectors.get("sectors") or []:
        label = str(r.get("sector") or "").lower()
        idx = str(r.get("index") or "").lower()
        if want in (label, idx) or (label and (label in want or want in label)):
            return r
    return None


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
                            f"Nifty is {t} against its 50-session average ({inp.get('nifty_vs_average_pct')}%).", rel(t, d), reg))
        vix = num(inp.get("india_vix"))
        if vix is None:
            out.append(unavailable(g, "india_vix", "No India VIX close on record for the session.", reg))
        else:
            out.append(item(g, "india_vix", {"india_vix": vix, "volatility_high": inp.get("volatility_high")},
                            f"India VIX {vix:g} ({'high' if inp.get('volatility_high') else 'not high'} by the desk rule).",
                            "neutral", reg))
    sec = snap(snaps, "sectors")
    sector_name = (snap(snaps, "scan_row")["data"] or {}).get("sector") if snap(snaps, "scan_row")["ok"] else None
    sector_name = sector_name or ((snap(snaps, "features")["data"] or {}).get("sector") if snap(snaps, "features")["ok"] else None)
    if not sec["ok"]:
        out.append(unavailable(g, "sector_strength", f"Sector returns unavailable: {sec['error']}", sec))
    else:
        row = _sector_row(sec["data"] or {}, sector_name)
        if row is None:
            out.append(unavailable(g, "sector_strength", f"No desk sector index matches the stock's sector ({sector_name or 'unknown'}).", sec))
        else:
            m = num(row.get("ret_1m_pct"))
            out.append(item(g, "sector_strength", {k: row.get(k) for k in ("index", "sector", "date", "ret_1d_pct", "ret_1w_pct", "ret_1m_pct")},
                            f"{row.get('index')} 1-month return {m if m is not None else 'n/a'}%.",
                            rel(sign(m, RULES["flat_band_pct"]), d) if m is not None else "unavailable", sec))
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
    sr = snap(snaps, "scan_row")
    if not sr["ok"]:
        out.append(unavailable(g, "scanner_gates", f"Scan snapshot unavailable: {sr['error']}", sr))
    else:
        row = sr["data"] or {}
        out.append(item(g, "scanner_gates", {k: row.get(k) for k in ("eligible", "exclusion", "liquidity_class", "risk_class", "traded_value_cr_20d")},
                        "Eligible for the scanner universe." if row.get("eligible") else f"Not in the scanner universe: {row.get('exclusion')}.",
                        "neutral", sr))
    return out


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


def fundamental(snaps: Dict[str, Any], d: str) -> List[Dict[str, Any]]:
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
                    "Not available: the data platform holds no analyst estimates or management guidance (PRD §17.2 #1).", "unavailable",
                    src_fail("no source exists", "none")))
    out.append(item(g, "cash_flow_quality", None, "Not available: the quarterly financials feed carries no cash-flow statement.",
                    "unavailable", src_fail("no source exists", "none")))
    out.append(item(g, "ownership_changes", None, "Not read in this release: shareholding history exists in the platform but is not part of the plan.",
                    "unavailable", src_fail("not read", "none")))
    return out


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
        out.append(item(g, "bid_ask", None, "Not available: the end-of-day F&O file carries no bid or ask; OI and volume are the liquidity proxy and fills are not assumed at mid.", "unavailable", ch))
    return out


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
    items = (market_context(snaps, d) + technical(snaps, d) + fundamental(snaps, d) + catalysts(snaps, d, asof, horizon)
             + derivatives(snaps, d, ref_session) + val_items + portfolio_fit(snaps, inputs["underlying"], sector))
    summary = {grp: {x: sum(1 for i in items if i["group"] == grp and i["direction"] == x) for x in DIRECTIONS} for grp in GROUPS}
    return {"items": items, "summary": summary, "validation": val_block}
