"""One builder per Release-1 intent: the platform's own data (readers.py) → a `visual-answer-v1` payload.

Every number shown is read from a source in readers.py, or is plain arithmetic on two such numbers (a percent change,
an advancing share, a sum of daily flows), labelled as such. A source that fails is listed as missing with a notice and
none of its figures appear; a source older than the previous NSE session is shown with its date and a stale notice
(services/market_freshness, owner rule 2026-10-28). Ideas to review, not recommendations.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from . import readers as rd
from .intents import Intent
from .payload import (
    DECISION_LABELS, Sources, assemble, block, candle_bars, crore, day_text, follow, iso_day, level, notice, num, pct,
    price, r2, short_day, times, tone_of, why,
)

logger = logging.getLogger(__name__)

CANDLE_SESSIONS = 60
INDEX_HISTORY = 260          # sessions read for an index chart, so its 50-session EMA has settled by the 60 shown
INDEX_NAMES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank"}
INDEX_LABELS = {"NIFTY": "Nifty", "BANKNIFTY": "Bank Nifty"}
PLAN_DECISION = {"plan": "setup_ready", "wait": "wait", "no_trade": "avoid", "insufficient_data": "no_setup"}
SHOWN_PLAN = ("setup_ready", "wait")
BUILDUP_NAMES = {"long_buildup": "Long buildup", "short_buildup": "Short buildup", "short_covering": "Short covering",
                 "long_unwinding": "Long unwinding"}
QUADRANT_POINTS = 40
SRC_SNAPSHOT = "NIDP market snapshot (breadth, FII/DII cash)"
SRC_INDEX = "NSE index closes (nidp.index_eod)"
SRC_SECTORS = "NSE sector indices (desk sector returns)"
SRC_FII = "NSE FII/DII cash (nidp.fii_dii_flows)"
SRC_BUILDUP = "NSE F&O bhavcopy · futures build-up"
SRC_REGIME = "Desk regime (desk-regime-v1)"
SRC_WATCHLIST = "AI scanner watchlist (Top 10, stored nightly)"
SRC_POSITIONAL = "Positional scanner watchlist (breakout_confirmed)"
SRC_SCAN = "Stock features + NSE bhavcopy (scan snapshot)"
SRC_DELIVERY = "NSE delivery (nidp.delivery_data)"
SRC_BARS = "NSE prices, split/bonus adjusted (prices_eod_adjusted)"
SRC_PLAN = "Desk trade plan (StrategyPlan + TradePlan, end of day)"


async def _try(coro) -> Tuple[Any, Optional[BaseException]]:
    try:
        return await coro, None
    except Exception as e:  # noqa: BLE001 — a failed source is said, never raised
        return None, e


def _chain_src(sym: str) -> str:
    return f"NSE F&O bhavcopy · {sym} option chain"


# ── shared pieces ────────────────────────────────────────────────────────────

def _series(bars: List[Dict[str, Any]], spans=(20, 50)) -> Dict[str, List[Optional[float]]]:
    closes = [b["c"] for b in bars]
    return {f"ema{n}": [None if x is None else round(x, 2) for x in rd.ema(closes, n)] for n in spans}


def _chart(symbol: str, raw_rows: List[list], bid: str, title: str, note: Optional[str] = None,
           spans=(20, 50), levels: Optional[List[Dict[str, Any]]] = None, band: Optional[Dict[str, Any]] = None
           ) -> Optional[Dict[str, Any]]:
    """A candles block: the last 60 sessions, EMAs worked out over the whole history read (the feature engine's EMA)."""
    bars = candle_bars(raw_rows)
    if not bars:
        return None
    full = _series(bars, spans)
    k = min(CANDLE_SESSIONS, len(bars))
    overlays = {name: s[-k:] for name, s in full.items()}
    return block("candles", bid, title, note, symbol=symbol, bars=bars[-k:], overlays=overlays,
                 levels=[lv for lv in (levels or []) if num(lv.get("price")) is not None], band=band)


def _index_raw(rows: List[Dict[str, Any]]) -> List[list]:
    return [[r.get("as_of_date"), r.get("open_price"), r.get("high_price"), r.get("low_price"), r.get("close_price"), None]
            for r in rows]


def _chain_levels(s: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    levels = []
    cw, pw, mp = (s.get("call_wall") or {}), (s.get("put_wall") or {}), num(s.get("max_pain"))
    if num(cw.get("strike")) is not None:
        levels.append({"kind": "wall_call", "price": num(cw["strike"]), "label": f"Call wall {level(cw['strike'])}"})
    if num(pw.get("strike")) is not None:
        levels.append({"kind": "wall_put", "price": num(pw["strike"]), "label": f"Put wall {level(pw['strike'])}"})
    if mp is not None:
        levels.append({"kind": "max_pain", "price": mp, "label": f"Max pain {level(mp)}"})
    spot, move = num(s.get("spot")), num(s.get("expected_move"))
    band = None
    if spot is not None and move is not None:
        band = {"low": round(spot - move, 2), "high": round(spot + move, 2),
                "label": f"Expected move to {day_text(s.get('expiry'))} (ATM straddle ±{level(move)})"}
    return levels, band


def _kpi(label: str, value: Optional[str], sub: Optional[str] = None, tone: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"label": label, "value": value, "sub": sub}
    if tone:
        out["tone"] = tone
    return out


def _last_change(rows: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    last = rows[-1] if rows else {}
    return num(last.get("close_price")), num(last.get("pct_change")), iso_day(last.get("as_of_date"))


# ── market_view ──────────────────────────────────────────────────────────────

async def market_view(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    (snap, e_snap), (nifty, e_n), (bank, e_b), (vix, e_v), (sect, e_s), (ch, e_c), (reg, e_r) = await asyncio.gather(
        _try(rd.market_snapshot()), _try(rd.index_rows("Nifty 50", INDEX_HISTORY)), _try(rd.index_rows("Nifty Bank", 2)),
        _try(rd.index_rows("India VIX", 2)), _try(rd.sector_returns()), _try(rd.chain(ctx["request"], "NIFTY")),
        _try(rd.regime()))
    kpis: List[Dict[str, Any]] = []
    blocks: List[Dict[str, Any]] = []
    head: List[str] = []
    as_of = None
    tone = "neutral"
    if e_n:
        src.miss(SRC_INDEX + " · Nifty 50", why(e_n))
    else:
        c, p, d = _last_change(nifty)
        src.add(SRC_INDEX, d)
        as_of, tone = d, tone_of(p)
        kpis.append(_kpi("Nifty 50", level(c), f"{pct(p)} on {short_day(d)}" if p is not None else short_day(d), tone_of(p)))
        if p is not None:
            head.append(f"Nifty 50 {'rose' if p > 0 else 'fell' if p < 0 else 'was flat'} {abs(p):.2f}% to {level(c)}")
    for rows, err, label in ((bank, e_b, "Bank Nifty"), (vix, e_v, "India VIX")):
        if err:
            src.miss(f"{SRC_INDEX} · {label}", why(err))
            continue
        c, p, d = _last_change(rows)
        if label == "Bank Nifty":
            kpis.append(_kpi(label, level(c), f"{pct(p)} on {short_day(d)}" if p is not None else short_day(d), tone_of(p)))
        else:
            kpis.append(_kpi(label, level(c), f"{pct(p)} on the day" if p is not None else None, "warn" if (c or 0) >= 20 else "neutral"))
            if c is not None:
                head.append(f"India VIX {c:.2f}")
    if e_snap:
        src.miss(SRC_SNAPSHOT, why(e_snap))
    else:
        src.add(SRC_SNAPSHOT, snap.get("prices_as_of") or snap.get("as_of_date"))
        adv, dec, unch = num(snap.get("advances_count")), num(snap.get("declines_count")), num(snap.get("unchanged_count")) or 0.0
        if adv is not None and dec is not None and adv + dec + unch > 0:
            share = adv / (adv + dec + unch) * 100
            kpis.append(_kpi("Breadth", f"{adv:,.0f} up · {dec:,.0f} down", f"{share:.0f}% of {adv + dec + unch:,.0f} stocks advanced",
                             "up" if adv > dec else "down" if dec > adv else "neutral"))
            head.insert(1 if head else 0, f"{share:.0f}% of stocks advanced")
        fii, dii = num(snap.get("fii_cash_net_cr")), num(snap.get("dii_cash_net_cr"))
        if fii is not None or dii is not None:
            fday = snap.get("fii_dii_as_of")
            src.add(SRC_FII, fday)
            kpis.append(_kpi("FII cash", crore(fii), f"net, {short_day(fday)}" if fday else "net", tone_of(fii)))
            kpis.append(_kpi("DII cash", crore(dii), f"net, {short_day(fday)}" if fday else "net", tone_of(dii)))
    if e_r:
        src.miss(SRC_REGIME, why(e_r))
    elif reg.get("label"):
        src.add(SRC_REGIME, reg.get("date"))
        ver = (reg.get("rule") or {}).get("version") if isinstance(reg.get("rule"), dict) else None
        kpis.append(_kpi("Regime", str(reg["label"]), f"{ver or 'desk regime'} · {short_day(reg.get('date'))}"))
    if kpis:
        blocks.append(block("kpis", "day", "The day", None, items=kpis))
    levels, band = [], None
    if e_c:
        src.miss(_chain_src("NIFTY"), why(e_c))
    else:
        s = ch.get("summary") or {}
        src.add(_chain_src("NIFTY"), s.get("as_of"))
        levels, band = _chain_levels(s)
    if not e_n:
        ch_block = _chart("NIFTY", _index_raw(nifty), "nifty", f"Nifty 50 · {CANDLE_SESSIONS} sessions",
                          "Dashed: the option walls and max pain of the nearest expiry. Shaded: the expected move from the ATM straddle."
                          if levels or band else None, levels=levels, band=band)
        if ch_block:
            blocks.append(ch_block)
    if e_s:
        src.miss(SRC_SECTORS, why(e_s))
    else:
        src.add(SRC_SECTORS, sect.get("as_of"))
        cells = [{"label": str(r.get("sector") or r.get("index")), "value": r2(r.get("ret_1d_pct")), "group": None,
                  "sub": f"1w {pct(r.get('ret_1w_pct'))}" if num(r.get("ret_1w_pct")) is not None else None}
                 for r in sect["sectors"] if isinstance(r, dict) and (r.get("sector") or r.get("index"))]
        cells.sort(key=lambda c: -(c["value"] if c["value"] is not None else -1e9))
        if cells:
            blocks.append(block("heatmap", "sectors", "Sectors on the day", None, unit="%", cells=cells))
    headline = ("; ".join(head) + ".") if head else None
    return assemble("market_view", "Market view · Nifty and Bank Nifty", as_of, headline, tone, blocks, src,
                    follow("Where is smart money moving?", "What is the expected move in Nifty?",
                           "Which breakouts are confirmed?", "Today's top 5 opportunities"), now=ctx.get("now"))


# ── smart_money ──────────────────────────────────────────────────────────────

async def smart_money(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    (flows, e_f), (sect, e_s), (bu, e_b) = await asyncio.gather(_try(rd.fii_dii(30)), _try(rd.sector_returns()), _try(rd.buildup()))
    blocks: List[Dict[str, Any]] = []
    kpis: List[Dict[str, Any]] = []
    head: List[str] = []
    as_of = None
    if e_f:
        src.miss(SRC_FII, why(e_f))
    else:
        days = [d for d in flows["daily"] if isinstance(d, dict) and iso_day(d.get("date"))][:10][::-1]
        as_of = iso_day(flows.get("as_of")) or (days[-1]["date"] if days else None)
        src.add(SRC_FII, as_of)
        for who, key in (("FII", "fii_net"), ("DII", "dii_net")):
            items = [{"label": short_day(d["date"]), "value": r2(d.get(key)), "tone": tone_of(d.get(key)), "sub": None} for d in days]
            if items:
                blocks.append(block("bars", who.lower(), f"{who} cash, last {len(items)} sessions", "Net buy − sell, ₹ crore (NSE provisional).",
                                    unit="₹ Cr", orientation="v", items=items, baseline=0))
            vals = [num(d.get(key)) for d in days]
            last = vals[-1] if vals else None
            if last is not None:
                kpis.append(_kpi(f"{who} cash · {short_day(days[-1]['date'])}", crore(last), None, tone_of(last)))
            if vals and all(v is not None for v in vals):
                total = sum(vals)  # type: ignore[arg-type]
                kpis.append(_kpi(f"{who} · {len(vals)} sessions", crore(total), "sum of the daily nets", tone_of(total)))
        last = days[-1] if days else {}
        fii, dii = num(last.get("fii_net")), num(last.get("dii_net"))
        if fii is not None and dii is not None:
            head.append(f"FIIs {'bought' if fii > 0 else 'sold'} a net {crore(abs(fii)).lstrip('+')} and DIIs "
                        f"{'bought' if dii > 0 else 'sold'} a net {crore(abs(dii)).lstrip('+')} in cash on {short_day(last['date'])}")
    if e_b:
        src.miss(SRC_BUILDUP, why(e_b))
    else:
        src.add(SRC_BUILDUP, bu.get("as_of"))
        counts = bu.get("counts") or {}
        for key in ("long_buildup", "short_covering", "short_buildup", "long_unwinding"):
            if isinstance(counts.get(key), int):
                kpis.append(_kpi(BUILDUP_NAMES[key], f"{counts[key]}", f"of {bu.get('universe')} F&O stocks",
                                 "up" if key in ("long_buildup", "short_covering") else "down"))
        rows = [r for r in bu.get("rows") or [] if r.get("label") in BUILDUP_NAMES
                and num(r.get("price_chg_pct")) is not None and num(r.get("oi_chg_pct")) is not None]
        pts = [{"label": r["symbol"], "x": r2(r["price_chg_pct"]), "y": r2(r["oi_chg_pct"]), "quadrant": BUILDUP_NAMES[r["label"]]}
               for r in rows[:QUADRANT_POINTS]]
        if pts:
            blocks.append(block("quadrant", "buildup", "F&O buildup · price vs open interest",
                                f"The {len(pts)} stock futures with the largest open-interest change on {short_day(bu.get('as_of'))}; "
                                "a reading of two figures, not a record of who traded.",
                                x={"label": "Price change", "unit": "%"}, y={"label": "OI change", "unit": "%"},
                                quadrants={"tr": "Long buildup", "tl": "Short buildup", "br": "Short covering", "bl": "Long unwinding"},
                                points=pts))
        longs = sorted((r for r in rows if r["label"] == "long_buildup"), key=lambda r: -r["oi_chg_pct"])[:5]
        covers = sorted((r for r in rows if r["label"] == "short_covering"), key=lambda r: -r["price_chg_pct"])[:5]
        ranked = [{"symbol": r["symbol"], "cells": {"symbol": r["symbol"], "buildup": BUILDUP_NAMES[r["label"]],
                                                     "price": r2(r["price_chg_pct"]), "oi": r2(r["oi_chg_pct"])},
                   "tone": "up", "ask": f"Trade plan for {r['symbol']}"} for r in longs + covers]
        if ranked:
            blocks.append(block("ranked", "strongest", "Strongest long buildup and short covering",
                                "Long buildup ranked by OI change, short covering by price change (nearest-expiry futures).",
                                columns=[{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                         {"key": "buildup", "label": "Buildup", "align": "left", "format": "text"},
                                         {"key": "price", "label": "Price %", "align": "right", "format": "pct"},
                                         {"key": "oi", "label": "OI %", "align": "right", "format": "pct"}],
                                rows=ranked))
        idx = [r for r in bu.get("indices") or [] if r.get("label") in BUILDUP_NAMES]
        if idx:
            blocks.append(block("list", "index_futures", "Index futures", None,
                                items=[{"text": f"{r['symbol']}: {BUILDUP_NAMES[r['label']].lower()}",
                                        "sub": f"price {pct(r.get('price_chg_pct'))}, OI {pct(r.get('oi_chg_pct'))}",
                                        "tone": "up" if r["label"] in ("long_buildup", "short_covering") else "down"} for r in idx]))
        if isinstance(counts.get("long_buildup"), int) and isinstance(counts.get("short_covering"), int):
            head.append(f"{counts['long_buildup']} F&O stocks show long buildup and {counts['short_covering']} short covering")
        as_of = as_of or iso_day(bu.get("as_of"))
    if e_s:
        src.miss(SRC_SECTORS, why(e_s))
    else:
        src.add(SRC_SECTORS, sect.get("as_of"))
        cells = [{"label": str(r.get("sector") or r.get("index")), "value": r2(r.get("ret_1w_pct")), "group": None,
                  "sub": (f"1d {pct(r.get('ret_1d_pct'))}" if num(r.get("ret_1d_pct")) is not None else "")
                  + (f" · 1m {pct(r.get('ret_1m_pct'))}" if num(r.get("ret_1m_pct")) is not None else "") or None}
                 for r in sect["sectors"] if isinstance(r, dict) and (r.get("sector") or r.get("index"))]
        cells.sort(key=lambda c: -(c["value"] if c["value"] is not None else -1e9))
        if cells:
            blocks.insert(min(2, len(blocks)), block("heatmap", "rotation", "Sector rotation · 1 week", "Sector index returns over 1 week.",
                                                     unit="%", cells=cells))
    if kpis:
        blocks.insert(0, block("kpis", "flows", "Flows and positioning", None, items=kpis))
    return assemble("smart_money", "Where smart money is moving", as_of, ("; ".join(head) + ".") if head else None,
                    "neutral", blocks, src,
                    follow("Today's top 5 opportunities", "Which breakouts are confirmed?", "What is the market view today?",
                           "Which stocks have unusual volume?"), now=ctx.get("now"))


# ── top_opportunities ────────────────────────────────────────────────────────

_BUCKETS = {"breakout_confirmed": "Breakout", "pre_breakout": "Pre-breakout", "true_accumulation": "Accumulation",
            "trend_continuation": "Trend pullback"}


def _primary(tp: Dict[str, Any]) -> Dict[str, Any]:
    ts = [t for t in tp.get("targets") or [] if isinstance(t, dict)]
    return next((t for t in ts if t.get("primary")), ts[0] if ts else {})


async def top_opportunities(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    n = int(intent.params.get("n") or 5)
    day, err = await _try(rd.watchlist_day())
    blocks: List[Dict[str, Any]] = []
    head = None
    as_of = None
    if err or not day:
        src.miss(SRC_WATCHLIST, why(err) if err else "no list is stored yet (the job runs each weekday at 22:45 IST)")
    else:
        as_of = day.get("list_date")
        src.add(SRC_WATCHLIST, as_of)
        rows, first_plan, ready, waiting = [], None, 0, 0
        for e in (day.get("cash") or [])[:n]:
            tp = e.get("trade_plan") or {}
            sc = e.get("scanner") or {}
            prim = _primary(tp)
            status = PLAN_DECISION.get(e.get("plan_status") or "")
            ready += status == "setup_ready"
            waiting += status == "wait"
            pid = e.get("trade_plan_id") or tp.get("plan_id")
            first_plan = first_plan or pid
            sym = e.get("symbol")
            rows.append({"symbol": sym, "plan_id": pid, "ask": f"Trade plan for {sym}" if sym else None,
                         "tone": "up" if status == "setup_ready" else "neutral",
                         "cells": {"rank": e.get("rank"), "symbol": sym,
                                   "setup": _BUCKETS.get(sc.get("bucket"), sc.get("bucket")) or (tp.get("strategy") or {}).get("label"),
                                   "status": DECISION_LABELS.get(status) if status else (e.get("plan_status") or None),
                                   "entry": r2((tp.get("entry") or {}).get("price")), "stop": r2((tp.get("stop") or {}).get("price")),
                                   "target": r2(prim.get("price")), "rr": r2(prim.get("r_multiple")),
                                   "score": r2(sc.get("score"))}})
        if rows:
            notes = day.get("notes") or {}
            blocks.append(block("ranked", "top", f"Top {len(rows)} by the scanner's score · {short_day(as_of)}",
                                " ".join(x for x in ("Reward:risk is the first target's R multiple, before charges.",
                                                     notes.get("cash_ranking")) if x),
                                columns=[{"key": "rank", "label": "#", "align": "right", "format": "int"},
                                         {"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                         {"key": "setup", "label": "Setup", "align": "left", "format": "text"},
                                         {"key": "status", "label": "Status", "align": "left", "format": "text"},
                                         {"key": "entry", "label": "Entry", "align": "right", "format": "price"},
                                         {"key": "stop", "label": "Stop", "align": "right", "format": "price"},
                                         {"key": "target", "label": "Target", "align": "right", "format": "price"},
                                         {"key": "rr", "label": "R:R", "align": "right", "format": "x"},
                                         {"key": "score", "label": "Score", "align": "right", "format": "text"}],
                                rows=rows))
            if first_plan:
                blocks.append(block("trade_plan", "first", f"The first idea's plan · {rows[0]['symbol']}", None, plan_id=first_plan))
            head = (f"{ready} of the scanner's top {len(rows)} on {short_day(as_of)} have a setup with levels"
                    + (f"; {waiting} wait for confirmation" if waiting else "") + ".")
        else:
            blocks.append(notice(f"The stored list of {day_text(as_of)} holds no cash ideas.", "info", "empty"))
    return assemble("top_opportunities", f"Today's top {n} ideas", as_of, head, "neutral", blocks, src,
                    follow("Which breakouts are confirmed?", "Which stocks have unusual volume?",
                           "What is the market view today?", "Where is smart money moving?"), now=ctx.get("now"))


# ── breakouts ────────────────────────────────────────────────────────────────

async def breakouts(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from services.positional_engine import setup_rules
    src: Sources = ctx["src"]
    wl, err = await _try(rd.positional_watchlist(ctx["request"]))
    blocks: List[Dict[str, Any]] = []
    head = None
    as_of = None
    follow_ups = ["Which stocks have unusual volume?", "Today's top 5 opportunities", "What is the market view today?"]
    if err or not isinstance(wl, dict) or not wl.get("as_of_date") or wl.get("as_of_date") == "None":
        src.miss(SRC_POSITIONAL, why(err) if err else (wl or {}).get("_reason") or "the scanner has no scan date")
    else:
        as_of = iso_day(wl["as_of_date"])
        src.add(SRC_POSITIONAL, as_of)
        rule = setup_rules.WATCHLIST["breakout_confirmed"]
        rule_note = (f"Rule ({setup_rules.WATCHLIST['classifier']}): close {rule['dist_breakout_pct_min']:g}–{rule['dist_breakout_pct_max']:g}% "
                     f"above the breakout level, 3-session volume ≥ {rule['volume_spike_min']:g}× the prior 20, stage "
                     f"{' or '.join(rule['stages'])}, gap-up ≤ {rule['max_gap_up_pct']:g}%. Stop = level − "
                     f"{setup_rules.WATCHLIST['stop_atr_multiple']:g} × ATR(14).")
        items = (wl.get("buckets") or {}).get("breakout_confirmed") or []
        if not items:
            blocks.append(notice(f"No stock met the confirmed-breakout rule on {day_text(as_of)}. {rule_note}", "info", "none"))
        else:
            rows, vol = [], []
            for it in items:
                sig = it.get("signals") or {}
                sym = it.get("nse_symbol")
                rows.append({"symbol": sym, "ask": f"Trade plan for {sym}", "tone": "up",
                             "cells": {"symbol": sym, "level": r2(it.get("trigger_price")), "close": r2(it.get("close_price")),
                                       "above": r2(sig.get("dist_breakout_pct")), "volx": r2(sig.get("volume_spike_3v20")),
                                       "stop": r2(it.get("stop_price"))}})
                if num(sig.get("volume_spike_3v20")) is not None:
                    vol.append({"label": sym, "value": r2(sig["volume_spike_3v20"]), "tone": "up", "sub": None})
            blocks.append(block("ranked", "list", f"Breakouts confirmed on {short_day(as_of)}", rule_note,
                                columns=[{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                         {"key": "level", "label": "Breakout level", "align": "right", "format": "price"},
                                         {"key": "close", "label": "Close", "align": "right", "format": "price"},
                                         {"key": "above", "label": "Above level", "align": "right", "format": "pct"},
                                         {"key": "volx", "label": "Volume ×", "align": "right", "format": "x"},
                                         {"key": "stop", "label": "Stop", "align": "right", "format": "price"}],
                                rows=rows))
            first = items[0]
            sym = first.get("nse_symbol")
            bars, e_bars = await _try(rd.stock_bars(sym))
            if e_bars:
                src.miss(f"{SRC_BARS} · {sym}", why(e_bars))
            else:
                src.add(SRC_BARS, bars[-1][0] if bars else None)
                lv = [{"kind": "resistance", "price": num(first.get("trigger_price")), "label": f"Breakout level {price(first.get('trigger_price'))}"},
                      {"kind": "stop", "price": num(first.get("stop_price")), "label": f"Stop {price(first.get('stop_price'))}"}]
                chart = _chart(sym, bars, "first", f"{sym} · the breakout",
                               f"Scanner prices are {first.get('price_basis') or 'raw'}; the chart is split/bonus adjusted.",
                               spans=(20, 50), levels=lv)
                if chart:
                    blocks.append(chart)
            if vol:
                blocks.append(block("bars", "volx", "Volume against the usual",
                                    "Mean volume of the last 3 sessions ÷ the mean of the 20 before.",
                                    unit="×", orientation="h", items=vol, baseline=1.0))
            head = (f"{len(items)} stock{'s' if len(items) != 1 else ''} closed just above the breakout level on at least "
                    f"{rule['volume_spike_min']:g}× the usual volume on {short_day(as_of)}.")
            follow_ups.insert(0, f"Entry, target and stop-loss for {sym}")
    return assemble("breakouts", "Confirmed breakouts", as_of, head, "up" if head else "neutral", blocks, src,
                    follow(*follow_ups), now=ctx.get("now"))


# ── unusual_volume ───────────────────────────────────────────────────────────

UNUSUAL_SHOWN = 10


async def unusual_volume(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from datetime import date as _date
    from services.positional_engine import setup_rules
    src: Sources = ctx["src"]
    snap, err = await _try(rd.scan_snapshot())
    blocks: List[Dict[str, Any]] = []
    head = None
    as_of = None
    if err or not isinstance(snap, dict):
        src.miss(SRC_SCAN, why(err) if err else "no snapshot")
    else:
        as_of = iso_day(snap.get("as_of"))
        src.add(SRC_SCAN, as_of)
        ev = setup_rules.evaluate(snap.get("rows") or [], _date.fromisoformat(as_of))
        cat = ev["categories"]["unusual_volume"]
        syms = cat["symbols"][:UNUSUAL_SHOWN]
        if not syms:
            blocks.append(notice(f"No eligible stock traded with volume ≥ {setup_rules.CATEGORIES['unusual_volume']['vol_z20_min']:g} "
                                 f"standard deviations above its 20-day average on {day_text(as_of)}.", "info", "none"))
        else:
            deliv = await asyncio.gather(*(_try(rd.delivery_latest(s)) for s in syms))
            ddays = sorted({iso_day((d or {}).get("as_of_date")) for d, e in deliv if not e and d and iso_day(d.get("as_of_date"))})
            if ddays:
                src.add(SRC_DELIVERY, ddays[-1], None if len(ddays) == 1 else f"dates {', '.join(ddays)}")
            else:
                src.miss(SRC_DELIVERY, next((why(e) for _, e in deliv if e), "no delivery rows for these stocks"))
            bars, rows = [], []
            for s, (d, e) in zip(syms, deliv):
                r = ev["rows"][s]
                same_day = iso_day(r.get("price_date")) == as_of
                close, prev = num(r.get("close_price")), num(r.get("prev_close"))
                chg = round((close / prev - 1) * 100, 2) if same_day and close and prev else None
                dpct = num((d or {}).get("deliverable_pct")) if not e else None
                bars.append({"label": s, "value": r2(r.get("rvol20")), "tone": tone_of(chg),
                             "sub": f"z {num(r.get('vol_z20')):.1f}" if num(r.get("vol_z20")) is not None else None})
                rows.append({"symbol": s, "ask": f"Trade plan for {s}", "tone": tone_of(chg),
                             "cells": {"symbol": s, "close": r2(close) if same_day else None, "chg": chg,
                                       "rvol": r2(r.get("rvol20")),
                                       "deliv": f"{dpct:.2f}%" if dpct is not None else None}})
            dlabel = f"Delivery % ({short_day(ddays[-1])})" if len(ddays) == 1 else "Delivery % (latest day)"
            blocks.append(block("bars", "rvol", f"Relative volume · top {len(syms)} on {short_day(as_of)}",
                                "The day's volume ÷ its 20-session average; z = standard deviations above that average.",
                                unit="×", orientation="h", items=bars, baseline=1.0))
            blocks.append(block("ranked", "table", "Price and delivery",
                                f"{cat['total']} eligible stocks met the rule (volume z-score ≥ "
                                f"{setup_rules.CATEGORIES['unusual_volume']['vol_z20_min']:g}); the top {len(syms)} by z-score.",
                                columns=[{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                         {"key": "close", "label": "Close", "align": "right", "format": "price"},
                                         {"key": "chg", "label": "Price %", "align": "right", "format": "pct"},
                                         {"key": "rvol", "label": "Volume ×", "align": "right", "format": "x"},
                                         {"key": "deliv", "label": dlabel, "align": "right", "format": "text"}],
                                rows=rows))
            top = ev["rows"][syms[0]]
            head = (f"{cat['total']} eligible stocks traded with unusually high volume on {short_day(as_of)}; {syms[0]} led at "
                    f"{times(top.get('rvol20'))} its 20-day average.")
    return assemble("unusual_volume", "Unusual volume", as_of, head, "neutral", blocks, src,
                    follow("Which breakouts are confirmed?", "Where is smart money moving?", "Today's top 5 opportunities"),
                    now=ctx.get("now"))


# ── stock_decision ───────────────────────────────────────────────────────────

def _preferred_tp(plan: Dict[str, Any], widget: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cands = [c for c in plan.get("candidates") or [] if isinstance(c, dict) and (c.get("trade_plan") or {}).get("plan_id")]
    want = ((widget or {}).get("data") or {}).get("preferred_plan_id")
    for c in cands:
        if c["trade_plan"]["plan_id"] == want:
            return c["trade_plan"]
    pref = next((c for c in cands if c.get("id") == plan.get("preferred")), None)
    return (pref or (cands[0] if cands else {})).get("trade_plan") or {}


def _entry_text(e: Dict[str, Any]) -> Optional[str]:
    """A share plan's trigger price, or an option plan's net premium (its entry has no single price)."""
    if num(e.get("price")) is not None:
        return f"entry {price(e['price'])}"
    if num(e.get("net_premium_rs")) is not None:
        return f"net premium {price(e['net_premium_rs'])}"
    return None


def _decision(status: str, plan: Dict[str, Any], tp: Dict[str, Any]) -> Dict[str, Any]:
    reasons = [r.get("message") for r in plan.get("status_reasons") or [] if isinstance(r, dict) and r.get("message")]
    e, s = tp.get("entry") or {}, tp.get("stop") or {}
    label = (tp.get("strategy") or {}).get("label")
    if status == "setup_ready":
        if num(e.get("price")) is not None and e.get("logic"):
            reason = f"{label}: {e['logic']}" if label else e["logic"]
        else:
            bits = [x for x in (_entry_text(e), f"stop {price(s.get('price'))} ({s.get('method') or 'stop'})"
                                if num(s.get("price")) is not None else None) if x]
            reason = (f"{label}: " if label else "") + ", ".join(bits) + "." if bits else label
    else:
        reason = reasons[0] if reasons else None
    conds = []
    for it in ((tp.get("evidence") or {}).get("items") or []):
        if isinstance(it, dict) and it.get("status") == "ok" and it.get("text") and it.get("direction") in ("supports", "conflicts"):
            conds.append({"text": f"{it.get('label') or it.get('key')}: {it['text']}", "met": it["direction"] == "supports"})
    conds = conds[:4]
    if status != "setup_ready":                       # what would have to change (it describes the setups not taken)
        conds += [{"text": str(w), "met": False} for w in (plan.get("would_change_if") or [])[:3]]
    if not tp:
        conds += [{"text": r, "met": False} for r in reasons[1:4]]
    inval = s.get("invalidation")
    if num(s.get("price")) is not None and status in SHOWN_PLAN:
        inval = f"{inval} ({price(s['price'])})" if inval else f"A close beyond {price(s['price'])}"
    return {"status": status, "label": DECISION_LABELS[status], "reason": reason, "conditions": conds,
            "invalidation": inval, "plan_id": tp.get("plan_id") if status in SHOWN_PLAN else None}


async def stock_decision(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from services.copilot_trade_idea import direction_of
    src: Sources = ctx["src"]
    sym = intent.symbol or ""
    ti = ctx.get("trade_idea")
    if ti is None:
        ti, err = await _try(rd.trade_idea(ctx["request"], ctx["user_id"], sym, ctx.get("message") or ""))
    bars, e_bars = await _try(rd.stock_bars(sym))
    plan = getattr(ti, "plan", None) if ti is not None else None
    blocks: List[Dict[str, Any]] = []
    decision = None
    head = None
    tone = "neutral"
    as_of = None
    tp: Dict[str, Any] = {}
    status = None
    if not isinstance(plan, dict):
        src.miss(SRC_PLAN, "the desk's plan for this stock could not be built just now")
    else:
        as_of = (plan.get("data_as_of") or {}).get("price")
        src.add(SRC_PLAN, as_of)
        status = PLAN_DECISION.get(plan.get("status") or "", "no_setup")
        tp = _preferred_tp(plan, getattr(ti, "widget", None)) if status in SHOWN_PLAN else {}
        decision = _decision(status, plan, tp)
        e, s, prim = tp.get("entry") or {}, tp.get("stop") or {}, _primary(tp)
        if status == "setup_ready":
            tone = "up"
            parts = [x for x in ((tp.get("strategy") or {}).get("label"), _entry_text(e),
                                 f"stop {price(s.get('price'))}" if num(s.get("price")) is not None else None,
                                 f"first target {price(prim.get('price'))}" if num(prim.get("price")) is not None else None) if x]
            head = f"{sym}: the desk's rules find a setup — {', '.join(parts)}."
        elif status == "wait":
            head = f"{sym}: a setup is waiting for its confirmation — {decision['reason'] or 'see the conditions'}."
        elif status == "avoid":
            tone = "down"
            head = f"{sym}: the desk's rules find no trade to take now — {decision['reason'] or 'see the reasons'}."
        else:
            tone = "warn"
            head = f"{sym}: not enough data for a setup — {decision['reason'] or 'see the reasons'}."
        dirn, stated = direction_of(ctx.get("message") or "")
        if not stated:
            blocks.append(notice(f"Direction assumed {('long' if dirn == 'bullish' else dirn)}: the question did not say. "
                                 f"Ask for a bearish plan to see the other side.", "info", "assumed"))
    levels: List[Dict[str, Any]] = []
    if tp:
        e, s = tp.get("entry") or {}, tp.get("stop") or {}
        levels.append({"kind": "entry", "price": num(e.get("price")), "label": f"Entry {price(e.get('price'))}"})
        levels.append({"kind": "stop", "price": num(s.get("price")), "label": f"Stop {price(s.get('price'))}"})
        for t in tp.get("targets") or []:
            if isinstance(t, dict) and num(t.get("price")) is not None:
                levels.append({"kind": "target", "price": num(t["price"]),
                               "label": f"Target {t.get('name') or ''} {price(t['price'])}".replace("  ", " ")})
    if e_bars:
        src.miss(f"{SRC_BARS} · {sym}", why(e_bars))
    else:
        src.add(SRC_BARS, bars[-1][0] if bars else None)
        chart = _chart(sym, bars, "chart", f"{sym} · the plan on the chart" if tp else f"{sym} · {CANDLE_SESSIONS} sessions",
                       None, spans=(20, 50, 200), levels=levels)
        if chart:
            blocks.append(chart)
    if tp:
        e, s, prim = tp.get("entry") or {}, tp.get("stop") or {}, _primary(tp)
        sized = getattr(ti, "sized", None) or {}
        strat = tp.get("strategy") or {}
        entry_kpi = (_kpi("Entry", price(e.get("price")), " · ".join(x for x in (e.get("order_type"), f"valid {e['valid_for_sessions']} sessions"
                                                                               if e.get("valid_for_sessions") else None) if x) or None)
                     if num(e.get("price")) is not None or num(e.get("net_premium_rs")) is None else
                     _kpi("Net premium", price(e.get("net_premium_rs")), e.get("order_text") or e.get("order_type")))
        kpis = ([_kpi("Strategy", strat["label"], strat.get("segment"))] if strat.get("label") else []) + [entry_kpi,
                _kpi("Stop", price(s.get("price") if num(s.get("price")) is not None else s.get("premium_stop")),
                     "underlying level" if s.get("method") == "underlying" else s.get("method")),
                _kpi("First target", price(prim.get("price")), f"{num(prim.get('r_multiple')):.1f}R" if num(prim.get("r_multiple")) is not None else None),
                _kpi("Reward:risk", times(prim.get("r_multiple")), "to the first target, before charges")]
        if sized.get("status") in ("sized", "not_confirmed"):
            qty = sized.get("quantity") if sized.get("quantity") is not None else sized.get("lots")
            risk = (sized.get("estimated_risk_rs") or {}).get("total") if isinstance(sized.get("estimated_risk_rs"), dict) else None
            kpis.append(_kpi("Size", f"{qty} {sized.get('unit') or ''}".strip() if qty is not None else None,
                             "risk service, your saved risk profile" + ("" if sized.get("status") == "sized" else " (not confirmed)")))
            kpis.append(_kpi("Max loss", price(risk), f"{num(sized.get('risk_pct_of_equity')):.2f}% of paper equity"
                             if num(sized.get("risk_pct_of_equity")) is not None else None, "warn"))
        elif sized.get("status") == "not_sizable":
            src.missing.append("Account sizing: the risk service would refuse this plan on your account (not_sizable)")
            # The plan's own rules find a setup, but the user's limits would refuse it: say so where the decision is read,
            # and point to the plan card, which lists why and the allowed ways forward.
            refusal = next((r.get("message") for r in sized.get("blocking") or [] if isinstance(r, dict) and r.get("message")), None)
            if decision:
                decision["conditions"].append({"text": "Fits your risk limits" + (f": {refusal}" if refusal else ""), "met": False})
            blocks.append(block("notice", "limits", None, None, tone="warn",
                                text="Your risk limits would not allow this plan on your account" + (f" ({refusal})" if refusal else "")
                                + ". The plan card below says why and what you can do."))
        elif sized:
            src.missing.append(f"Account sizing: {sized.get('reason') or sized.get('status') or 'unavailable'}")
        blocks.append(block("kpis", "risk", "Risk and reward", None, items=kpis))
        warns = [{"text": f"{w.get('label') or w.get('key')}: {w['text']}", "tone": "warn"} for w in tp.get("warnings") or []
                 if isinstance(w, dict) and w.get("status") == "flagged" and w.get("text")]
        if warns:
            blocks.append(block("list", "warn", "Watch out", None, items=warns[:5]))
        if tp.get("plan_id"):
            blocks.append(block("trade_plan", "plan", "The desk's plan", None, plan_id=tp["plan_id"]))
    elif decision and status not in SHOWN_PLAN:
        reasons = [r.get("message") for r in plan.get("status_reasons") or [] if isinstance(r, dict) and r.get("message")]
        if reasons:
            blocks.append(block("list", "why", "Why there is no setup", None, items=[{"text": r, "tone": "warn"} for r in reasons[:5]]))
    title = f"{sym} · entry, stop and targets" if tp else f"{sym} · is there a setup?"
    fu = [f"Plan a bearish trade for {sym} instead" if direction_of(ctx.get("message") or "")[0] == "bullish"
          else f"Plan a bullish trade for {sym} instead", "What is the market view today?", "Which breakouts are confirmed?",
          "Today's top 5 opportunities"]
    return assemble("stock_decision", title, as_of or (bars[-1][0] if bars and not e_bars else None), head, tone, blocks, src,
                    follow(*fu), decision=decision, now=ctx.get("now"))


# ── expected_move ────────────────────────────────────────────────────────────

async def expected_move(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    sym = intent.symbol if intent.symbol in INDEX_NAMES else "NIFTY"
    label = INDEX_LABELS[sym]
    (ch, e_c), (rows, e_r) = await asyncio.gather(_try(rd.chain(ctx["request"], sym)), _try(rd.index_rows(INDEX_NAMES[sym], INDEX_HISTORY)))
    blocks: List[Dict[str, Any]] = []
    head = None
    as_of = None
    levels, band = [], None
    if e_c:
        src.miss(_chain_src(sym), why(e_c))
    else:
        s = ch.get("summary") or {}
        as_of = iso_day(s.get("as_of"))
        src.add(_chain_src(sym), as_of)
        levels, band = _chain_levels(s)
        move, mpct, iv, pcr_v, mp = (num(s.get(k)) for k in ("expected_move", "expected_move_pct", "atm_iv", "pcr", "max_pain"))
        for k, v, why_null in (("expected move", move, "null on the expiry day or when the ATM call or put did not close above zero"),
                               ("ATM IV", iv, "the ATM option had no market price, or the futures read failed")):
            if v is None:
                src.missing.append(f"{k}: not worked out ({why_null})")
        kpis = [_kpi("Expected move", f"±{level(move)} pts" if move is not None else None,
                     f"±{mpct:.2f}% · ATM straddle" if mpct is not None else "ATM straddle"),
                _kpi("ATM IV", f"{iv:.2f}%" if iv is not None else None, "Black-76 on the ATM strike, end of day"),
                _kpi("PCR", f"{pcr_v:.2f}" if pcr_v is not None else None, "put OI ÷ call OI, whole expiry",
                     "up" if (pcr_v or 0) > 1 else "down" if pcr_v is not None and pcr_v < 1 else None),
                _kpi("Max pain", level(mp), None),
                _kpi("Expiry", day_text(s.get("expiry")), f"{s.get('days_to_expiry')} days from {short_day(as_of)}"
                     if s.get("days_to_expiry") is not None else None),
                _kpi("Spot", level(s.get("spot")), f"close {short_day(as_of)}")]
        blocks.append(block("kpis", "chain", f"Option chain · {day_text(s.get('expiry'))} expiry", None, items=kpis))
        if move is not None and mpct is not None:
            head = (f"The {label} options price a move of about ±{level(move)} points (±{mpct:.2f}%) to the "
                    f"{day_text(s.get('expiry'))} expiry" + (f"; PCR {pcr_v:.2f}" if pcr_v is not None else "")
                    + (f", max pain {level(mp)}" if mp is not None else "") + ".")
    if e_r:
        src.miss(f"{SRC_INDEX} · {INDEX_NAMES[sym]}", why(e_r))
    else:
        src.add(SRC_INDEX, rows[-1].get("as_of_date") if rows else None)
        chart = _chart(sym, _index_raw(rows), "chart", f"{INDEX_NAMES[sym]} with the expected-move band",
                       "Shaded: spot ± the ATM straddle. Dashed: call wall, put wall and max pain." if band or levels else None,
                       levels=levels, band=band)
        if chart:
            blocks.append(chart)
    return assemble("expected_move", f"Expected move in {label}", as_of, head, "neutral", blocks, src,
                    follow("What is the market view today?", "Where is smart money moving?",
                           "Bank Nifty expected move" if sym == "NIFTY" else "What is the expected move in Nifty?"),
                    now=ctx.get("now"))


BUILDERS = {"market_view": market_view, "smart_money": smart_money, "top_opportunities": top_opportunities,
            "breakouts": breakouts, "unusual_volume": unusual_volume, "stock_decision": stock_decision,
            "expected_move": expected_move}


async def build(intent: Intent, user: Optional[Dict[str, Any]] = None, request: Any = None, message: str = "",
                trade_idea: Any = None, now: Any = None) -> Dict[str, Any]:
    """The payload for `intent`. Raises only on a programming fault; every data failure is inside the payload."""
    src = Sources(await rd.window())
    ctx = {"src": src, "request": request, "user_id": (user or {}).get("user_id"), "message": message,
           "trade_idea": trade_idea, "now": now}
    return await BUILDERS[intent.name](intent, ctx)
