"""One builder per Release-1 intent: the platform's own data (readers.py) → a `visual-answer-v1` payload.

Every number shown is read from a source in readers.py, or is plain arithmetic on two such numbers (a percent change,
an advancing share, a sum of daily flows), labelled as such. A source that fails is listed as missing with a notice and
none of its figures appear; a source older than the previous NSE session is shown with its date and a stale notice
(services/market_freshness, owner rule 2026-10-28). Ideas to review, not recommendations.
"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import fno_board as fb
from . import readers as rd
from .intents import Intent
from .payload import (
    CAVEAT_TAIL, DECISION_LABELS, IST, MINUS, Sources, assemble, block, candle_bars, crore, day_text, follow, iso_day, level, notice,
    num, pct, price, r2, rupees, short_day, times, tone_of, why,
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
SRC_MARKET_STATE = "Market state the risk service uses (regime, India VIX)"
SRC_WATCHLIST = "AI scanner watchlist (Top 10, stored nightly)"
SRC_POSITIONAL = "Positional scanner watchlist (breakout_confirmed)"
SRC_SCAN = "Stock features + NSE bhavcopy (scan snapshot)"
SRC_DELIVERY = "NSE delivery (nidp.delivery_data)"
SRC_BARS = "NSE prices, split/bonus adjusted (prices_eod_adjusted)"
SRC_PLAN = "Desk trade plan (StrategyPlan + TradePlan, end of day)"
SRC_PAPER = "Your paper trades (desk_paper_trades, marked at the last available close)"
SRC_FNO_TOP = "Desk F&O board (StrategyPlan, fit to today's regime)"
SRC_RISK_PROFILE = "Your risk profile (risk_profiles)"
SRC_RISK_BOOK = "Your paper account's risk book (equity, day/week P&L, open risk)"
SRC_TRADE_PLANS = "A plan recorded earlier (trade_plans)"
SRC_CLOSED = "Your closed paper trades (desk_paper_trades)"
SRC_DECISIONS = "Your entry risk checks (risk_decisions)"


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

def _size_rule(regime: Optional[str], vix: Optional[float]) -> Tuple[str, str, Optional[str]]:
    """What the market state does to a NEW paper trade's size limits, by the risk governor's own thresholds:
    (value, why, tone). It states the rule; it predicts nothing."""
    from services.ai_trader.risk_governor import DEFAULT_LIMITS as lim
    if vix is not None and vix >= lim.vix_defer_at:
        return "Deferred", f"India VIX at {lim.vix_defer_at:g} or above: the governor defers new positions.", "warn"
    if regime == "BEAR":
        return "Halved", "New-trade size limits are halved in BEAR.", "warn"
    if vix is not None and vix >= lim.vix_reduce_at:
        return "Halved", f"India VIX at {lim.vix_reduce_at:g} or above halves them.", "warn"
    return "Not cut", "No regime cut on new-trade size limits (only BEAR halves them).", None


async def market_view(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    (snap, e_snap), (nifty, e_n), (bank, e_b), (vix, e_v), (sect, e_s), (ch, e_c), (mkt, e_m) = await asyncio.gather(
        _try(rd.market_snapshot()), _try(rd.index_rows("Nifty 50", INDEX_HISTORY)), _try(rd.index_rows("Nifty Bank", 2)),
        _try(rd.index_rows("India VIX", 2)), _try(rd.sector_returns()), _try(rd.chain(ctx["request"], "NIFTY")),
        _try(rd.market_state()))
    kpis: List[Dict[str, Any]] = []
    flows: List[Dict[str, Any]] = []
    flows_day = None
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
            flows_day = snap.get("fii_dii_as_of")
            src.add(SRC_FII, flows_day)
            flows = [{"label": who, "value": r2(v), "tone": tone_of(v), "sub": None} for who, v in (("FII", fii), ("DII", dii)) if v is not None]
    if kpis:
        blocks.append(block("kpis", "day", "The day", None, items=kpis))
    # The market regime, as the desk's Market regime card reads it: the state the risk service sizes new paper trades with.
    if e_m:
        src.miss(SRC_MARKET_STATE, why(e_m))
    else:
        j = mkt.get("freshness") or {}
        src.add(SRC_MARKET_STATE, mkt.get("as_of"))
        regime_word, mvix = str(mkt["regime"]), num(mkt.get("vix"))
        rule_value, rule_why, rule_tone = _size_rule(regime_word, mvix)
        age = j.get("age_sessions")
        blocks.append(block("kpis", "regime", "Market regime", "Descriptive: the state the desk's risk rules read, not a forecast.", items=[
            _kpi("Regime", regime_word, f"as of {short_day(mkt.get('as_of'))}" + (f" · India VIX {mvix:.2f}" if mvix is not None else ""),
                 "down" if regime_word == "BEAR" else "up" if regime_word == "BULL" else "neutral"),
            _kpi("New-trade size limits", rule_value, rule_why, rule_tone),
            _kpi("Market state", f"{age} of {j.get('budget')} sessions old" if age is not None and j.get("budget") is not None else "age unknown",
                 "the state the risk service sizes and checks new paper trades with", None if j.get("ok") else "warn")]))
        head.append(f"the market regime reads {regime_word}")
    if flows:
        blocks.append(block("bars", "flows", "Net cash flows, last session",
                            f"Net buy − sell, ₹ crore, {day_text(iso_day(flows_day))} (NSE provisional)." if iso_day(flows_day) else "Net buy − sell, ₹ crore (NSE provisional).",
                            unit="₹ Cr", orientation="h", items=flows, baseline=0))
    moves_block = heat_block = None
    if e_s:
        src.miss(SRC_SECTORS, why(e_s))
    else:
        src.add(SRC_SECTORS, sect.get("as_of"))
        cells = [{"label": str(r.get("sector") or r.get("index")), "value": r2(r.get("ret_1d_pct")), "group": None,
                  "sub": f"1w {pct(r.get('ret_1w_pct'))}" if num(r.get("ret_1w_pct")) is not None else None}
                 for r in sect["sectors"] if isinstance(r, dict) and (r.get("sector") or r.get("index"))]
        cells.sort(key=lambda c: -(c["value"] if c["value"] is not None else -1e9))
        if cells:
            heat_block = block("heatmap", "sectors", "Sectors on the day", None, unit="%", cells=cells)
            ranked = [c for c in cells if c["value"] is not None]
            up = ranked[:min(3, (len(ranked) + 1) // 2)]
            rest = ranked[len(up):]
            down = rest[-min(3, len(rest)):][::-1] if rest else []
            if up or down:
                moves_block = block("bars", "sector_moves", "Leading and lagging sectors · 1 day",
                                    "The three strongest and the three weakest of the NSE sector indices on the day.", unit="%", orientation="h",
                                    items=[{"label": c["label"], "value": c["value"], "tone": tone_of(c["value"]), "sub": None} for c in up + down],
                                    baseline=0)
    if moves_block:
        blocks.append(moves_block)
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
    if heat_block:
        blocks.append(heat_block)
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
            refusal = next((str(r["message"]).rstrip(". ") for r in sized.get("blocking") or [] if isinstance(r, dict) and r.get("message")), None)
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


# ── Release 2 ──────────────────────────────────────────────────────────────── (owner, 30 Oct: "complete Release 2")

async def open_trades(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q13 "What are my open trades doing?" — the paper book (not a broker's), the same read the desk's own Paper
    trades screen uses, with marks and each trade's own stop and target."""
    src: Sources = ctx["src"]
    out, err = await _try(rd.open_trades(ctx["request"]))
    blocks: List[Dict[str, Any]] = []
    head = None
    tone = "neutral"
    as_of = None
    if err or not isinstance(out, dict):
        src.miss(SRC_PAPER, why(err) if err else "the paper book could not be read")
    else:
        as_of = iso_day(out.get("as_of"))
        if as_of:
            src.add(SRC_PAPER, as_of)
        else:
            src.missing.append(f"{SRC_PAPER}: no end-of-day mark date on this answer (an F&O-only book marks on its own schedule)")
        trades = [t for t in out.get("trades") or [] if isinstance(t, dict)]
        summ = out.get("summary") or {}
        unreal = num(summ.get("unrealized_pnl_rs"))
        kpis = [_kpi("Open", str(summ.get("open") or 0), None),
                _kpi("Unrealised P&L", price(unreal) if unreal is not None else None,
                     "net of estimated costs" if unreal is not None else "not every open trade is marked yet", tone_of(unreal))]
        if summ.get("entry_pending"):
            kpis.append(_kpi("Not yet triggered", str(summ["entry_pending"]), "waiting for its entry condition"))
        blocks.append(block("kpis", "summary", "Your open paper trades", None, items=kpis))
        if trades:
            rows = []
            for t in trades[:15]:
                sym = t.get("symbol")
                pnl = num(t.get("unrealized_pnl_rs"))
                rows.append({"symbol": sym, "ask": f"Should I book profits or hold {sym}?" if sym else None,
                             "tone": tone_of(pnl),
                             "cells": {"symbol": sym, "qty": t.get("quantity"), "entry": r2(t.get("entry_price")),
                                       "last": r2(t.get("last_close")), "stop": r2(t.get("stop_price")),
                                       "target": r2(t.get("target_price")), "pnl": r2(pnl)}})
            blocks.append(block("ranked", "trades", f"{len(trades)} open paper trade{'s' if len(trades) != 1 else ''}",
                                "Marked at the last available close. Not every trade may be marked yet; see the P&L above.",
                                columns=[{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                         {"key": "qty", "label": "Qty", "align": "right", "format": "int"},
                                         {"key": "entry", "label": "Entry", "align": "right", "format": "price"},
                                         {"key": "last", "label": "Last close", "align": "right", "format": "price"},
                                         {"key": "stop", "label": "Stop", "align": "right", "format": "price"},
                                         {"key": "target", "label": "Target", "align": "right", "format": "price"},
                                         {"key": "pnl", "label": "Unrealised P&L", "align": "right", "format": "price"}],
                                rows=rows))
            tone = tone_of(unreal)
            head = (f"{len(trades)} open paper trade{'s' if len(trades) != 1 else ''}"
                    + (f", unrealised {price(unreal)}" if unreal is not None else "") + ".")
        else:
            blocks.append(notice("No open paper trades right now.", "info", "empty"))
            head = "No open paper trades right now."
    return assemble("open_trades", "Your open trades", as_of, head, tone, blocks, src,
                    follow("How much should I risk?", "Which F&O setups are attractive?",
                           "What is the market view today?", "Today's top 5 opportunities"), now=ctx.get("now"))


FNO_VIEWS = {"up": "Bullish", "down": "Bearish"}
FNO_COLUMNS = [{"key": "symbol", "label": "Underlying", "align": "left", "format": "text"},
               {"key": "structure", "label": "Structure", "align": "left", "format": "text"},
               {"key": "view", "label": "View", "align": "left", "format": "text"},
               {"key": "lots", "label": "Lots", "align": "left", "format": "text"},
               {"key": "maxloss", "label": "Max loss", "align": "right", "format": "price"},
               {"key": "maxprofit", "label": "Max profit", "align": "right", "format": "price"},
               {"key": "atmove", "label": "At exp. move", "align": "right", "format": "price"},
               {"key": "rr", "label": "R:R at move", "align": "right", "format": "x"},
               {"key": "margin", "label": "Margin", "align": "right", "format": "price"},
               {"key": "fit", "label": "Fit", "align": "right", "format": "text"}]
FNO_SECTIONS = (("index_options", "fno_index", "Index options"), ("stock_fno", "fno_stock", "Stock F&O"))
FNO_NOTE = ("Fit to today's measured regime, not a performance rank. Figures are for the lots shown, gross, before charges. "
            "A bought option's profit is not capped in practice, so the profit at the expected move is shown instead; "
            "R:R is measured at that move. Margin is Zerodha's calculator for the structure.")


def _fno_fields(idea: Dict[str, Any]) -> Dict[str, Any]:
    return {k: idea.get(k) for k in ("max_profit", "max_loss", "profit_unbounded", "loss_unbounded", "net_at_expected_move", "reward_risk")}


def _fno_row(idea: Dict[str, Any], f: Dict[str, Any], margin: Optional[Dict[str, Any]], badge: Optional[str],
             margin_cell: Optional[str]) -> Dict[str, Any]:
    sym = idea.get("underlying")
    view = idea.get("view")
    cap, tip = fb.profit_cell(idea.get("structure"), f)
    est = num((margin or {}).get("estimate"))
    cells = {"symbol": sym, "structure": idea.get("name"), "view": FNO_VIEWS.get(view, "Neutral"),
             "lots": fb.lots_text(idea.get("legs") or []),
             "maxloss": None if f.get("loss_unbounded") else r2(f.get("max_loss")), "maxprofit": cap,
             "atmove": r2(f.get("net_at_expected_move")), "rr": r2(f.get("reward_risk")),
             "margin": r2(est) if est is not None else margin_cell, "fit": r2((idea.get("fit") or {}).get("score"))}
    row: Dict[str, Any] = {"symbol": sym, "plan_id": (idea.get("trade_plan") or {}).get("plan_id"),
                           "ask": f"What's the setup for {sym}?" if sym else None,
                           "tone": "up" if view == "up" else ("down" if view == "down" else "neutral"), "cells": cells}
    if badge:
        row["badge"] = badge
    if tip:
        row["tips"] = {"maxprofit": tip}
    return row


def _class_reason(body: Dict[str, Any]) -> str:
    un = [u for u in body.get("unavailable") or [] if isinstance(u, dict)]
    if un:
        return "; ".join(f"{u.get('underlying') or 'the scanner'}: {u.get('reason')}" for u in un[:3])[:300]
    skipped = (body.get("universe") or {}).get("skipped") or []
    return (f"{len(skipped)} scanner names are not in the F&O list" if skipped else "no structure priced with a valid payoff today")


async def fno_setups(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q10 "Which F&O setups are attractive?" — the desk's own F&O board, ranked by fit to today's measured regime, never a
    performance rank (services/strategy_plan/regime_fit.py says so). Two sections, one row per underlying with its other
    structures folded under it (owner, 31 Oct 2026: a flattened first five was all index and showed no stock). Each row
    carries its lots and Zerodha's margin; in the session the premiums are live (Kite), the ranking still the close's."""
    from datetime import datetime as _dt

    from services.strategy_plan import regime_fit as _rf
    src: Sources = ctx["src"]
    n = 5
    top, err = await _try(rd.fno_top(ctx["request"], ctx["user_id"], limit=n))
    blocks: List[Dict[str, Any]] = []
    head = None
    as_of = None
    live_at: Optional[str] = None
    login_need: List[str] = []
    mfacts: Dict[str, Any] = {}
    if err or not isinstance(top, dict):
        src.miss(SRC_FNO_TOP, why(err) if err else "the F&O board could not be built")
        return assemble("fno_setups", "F&O setups that fit today", as_of, head, "neutral", blocks, src, follow(
            "What is the expected move in Nifty?", "How much should I risk?", "What is the market view today?",
            "Today's top 5 opportunities"), now=ctx.get("now"))
    regime = top.get("regime") or {}
    classes = top.get("classes") or {}
    # The board's data day: the chain the ideas were priced from (newest), else the day the regime was classified. The real
    # regime carries `as_of` (strategy_plan.regime_fit.read_regime), not `date`: reading `date` gave every answer a false
    # "unknown date, stale" notice (found on staging data, 31 Oct 2026; the unit fixtures had the wrong key).
    chain_days = sorted(d for c in classes.values() for i in (c or {}).get("ideas") or [] if isinstance(i, dict)
                        for d in [iso_day((i.get("data_as_of") or {}).get("chain"))] if d)
    as_of = chain_days[-1] if chain_days else iso_day(regime.get("as_of") or regime.get("date"))
    src.add(SRC_FNO_TOP, as_of)
    leads: Dict[str, List[Dict[str, Any]]] = {}
    shown: List[Dict[str, Any]] = []                    # every idea on screen (leads then their alternatives), by position
    for cls, _bid, _title in FNO_SECTIONS:
        leads[cls] = [i for i in ((classes.get(cls) or {}).get("ideas") or []) if isinstance(i, dict)][:n]
        for i in leads[cls]:
            shown.append(i)
            shown.extend(a for a in (i.get("alternatives") or [])[:_rf.ALTERNATIVES_MAX] if isinstance(a, dict))
    now = ctx.get("now") or _dt.now(IST)
    today_iso = src.w.today.isoformat() if src.w is not None else now.astimezone(IST).date().isoformat()

    # Live premiums, only in the session; every figure of an idea is live or none of it (fno_board.reprice).
    live: Dict[int, Dict[str, Any]] = {}
    if shown and rd.in_session(now):
        flat, at = fb.leg_requests(shown)
        (lq, e_q), (spots, e_s) = await asyncio.gather(_try(rd.fno_live_quotes(flat)), _try(rd.live_spots(sorted({i["underlying"] for i in shown}))))
        if e_q or not isinstance(lq, dict) or not lq.get("available"):
            reason = why(e_q) if e_q else (lq or {}).get("reason") or "the live read returned nothing"
            src.missing.append(f"{fb.SRC_LIVE}: {reason}")
            if "Kite login" in reason or "Kite token" in reason or "Kite access token" in reason:
                login_need.append("Live premiums")
            blocks.append(notice(f"Live option premiums are not available ({reason[:160]}), so every figure is from the "
                                 f"{short_day(as_of)} close.", "info", "live-off"))
        else:
            quotes = {int(k): v for k, v in (lq.get("quotes") or {}).items()}
            moves = {u.get("underlying"): u.get("expected_move") for c in classes.values() for u in (c or {}).get("underlyings") or []}
            spot_of = spots if isinstance(spots, dict) else {}
            for k, idea in enumerate(shown):
                got = fb.reprice(idea, k, quotes, at, spot_of.get(idea["underlying"]), num(moves.get(idea["underlying"])), today_iso)
                if got is not None:
                    live[k] = got
            if live:
                live_at = _dt.fromisoformat(lq["as_of"]).astimezone(IST).strftime("%H:%M") if lq.get("as_of") else None
                src.add(fb.SRC_LIVE, today_iso)

    # Margin: Zerodha's calculator (platform Kite login, else the user's own Zerodha), one call per structure.
    margin_of: Dict[int, Dict[str, Any]] = {}
    margin_cell: Optional[str] = None
    if shown:
        calcs, mfacts = await rd.margin_calculators(ctx["request"], ctx["user_id"])
        if calcs:
            res = await rd.fno_margins(calcs, [(str(k), i["underlying"], i.get("legs") or []) for k, i in enumerate(shown)])
            margin_of = {k: res[str(k)] for k in range(len(shown)) if str(k) in res}
            for label in sorted({m.get("source") for m in margin_of.values() if m.get("estimate") is not None and m.get("source")}):
                src.add(label, today_iso)
            for k, m in margin_of.items():
                if m.get("estimate") is None and m.get("reason") != fb.NO_CALCULATOR:
                    src.missing.append(f"Margin for {shown[k]['underlying']} {shown[k].get('name')}: {m.get('reason')}")
        # Every calculator refused its session (an expired Kite login) is the same as having none: ask for the login, once.
        refused = bool(margin_of) and all(m.get("reason") == fb.NO_CALCULATOR for m in margin_of.values())
        if not calcs or refused:
            login_need.insert(0, "Margin")
            margin_cell = "Needs login"
            if refused:
                src.missing.append("Margin: every Zerodha calculator session was refused (the Kite login has expired)")

    # Rows: the lead of each underlying, its alternatives folded under it.
    pos = {id(i): k for k, i in enumerate(shown)}
    chain_day = lambda i: iso_day((i.get("data_as_of") or {}).get("chain")) or as_of          # noqa: E731

    def make_row(idea: Dict[str, Any]) -> Dict[str, Any]:
        k = pos[id(idea)]
        badge = "Live" if k in live else (f"{short_day(chain_day(idea))} close" if chain_day(idea) else None)
        return _fno_row(idea, live.get(k) or _fno_fields(idea), margin_of.get(k), badge, margin_cell)

    first_plan = None
    counts: Dict[str, int] = {}
    for cls, bid, title in FNO_SECTIONS:
        rows = []
        for idea in leads[cls]:
            row = make_row(idea)
            alts = [make_row(a) for a in (idea.get("alternatives") or [])[:_rf.ALTERNATIVES_MAX] if isinstance(a, dict)]
            if alts:
                row["alternatives"] = alts
            rows.append(row)
        counts[cls] = len(rows)
        if rows:
            first_plan = first_plan or rows[0].get("plan_id")
            note = FNO_NOTE + (f" Premiums live at {live_at} IST; the ranking and the regime are from the {short_day(as_of)} close."
                               if live_at else "")
            blocks.append(block("ranked", bid, f"{title} · {len(rows)} setup{'s' if len(rows) != 1 else ''}", note,
                                columns=FNO_COLUMNS, rows=rows))
        else:
            blocks.append(notice(f"No {title} setup today: {_class_reason(classes.get(cls) or {})}.", "info", f"{bid}-empty"))
    if login_need:
        needs = list(dict.fromkeys(login_need))
        n_ = notice(fb.login_text(mfacts or {}, "Margin and live premiums" if len(needs) > 1 else needs[0]), "info", "login")
        n_["actions"] = [{"kind": "kite_login", "label": "Log in to Kite"}, {"kind": "connect_broker", "label": "Connect a broker"}]
        blocks.append(n_)
    if first_plan:
        first_sym = next((r["symbol"] for b in blocks if b.get("type") == "ranked" for r in b["rows"]), None)
        blocks.append(block("trade_plan", "first", f"The first idea's plan · {first_sym}", None, plan_id=first_plan))
    total = sum(counts.values())
    if total:
        head = (f"{total} F&O setup{'s' if total != 1 else ''} fit today's regime"
                + (f" ({regime['label']})" if regime.get("label") else "")
                + f": {counts.get('index_options', 0)} index, {counts.get('stock_fno', 0)} stock.")
    else:
        blocks.append(notice("No F&O setup fits today's regime with a valid payoff.", "info", "empty"))
    p = assemble("fno_setups", "F&O setups that fit today", as_of, head, "neutral", blocks, src,
                 follow("What is the expected move in Nifty?", "How much should I risk?",
                        "What is the market view today?", "Today's top 5 opportunities"), now=ctx.get("now"))
    if live:
        p["mode"] = "mixed"
        p["caveat"] = (f"Ranked on end-of-day data of {day_text(as_of)}; premiums, max loss and profit are live from Kite"
                       + (f" at {live_at} IST" if live_at else "") + ". " + CAVEAT_TAIL)
    return p


async def position_size(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q12 "How much should I risk?" — the account's own risk limits and today's usage of them (services/risk_profile,
    services/risk_book: the same figures the risk service itself checks a new trade against). A named stock adds its
    own size from the risk service's sizing (the same sizing stock_decision shows)."""
    src: Sources = ctx["src"]
    uid = ctx["user_id"]
    (prof, e_p), (book, e_b) = await asyncio.gather(_try(rd.risk_profile(uid)), _try(rd.risk_book(uid)))
    blocks: List[Dict[str, Any]] = []
    head = None
    tone = "neutral"
    as_of = None
    lim: Dict[str, Any] = {}
    if e_p or not isinstance(prof, dict):
        src.miss(SRC_RISK_PROFILE, why(e_p) if e_p else "the risk profile could not be read")
    else:
        src.add(SRC_RISK_PROFILE, None)
        lim = prof.get("limits") or {}
        kpis = [_kpi("Per trade", f"{num(lim.get('per_trade_risk_pct')) or 0:g}% of equity", prof.get("capital_basis_text")),
                _kpi("Max open risk", f"{num(lim.get('max_open_risk_pct')) or 0:g}%", "all open positions plus a new one"),
                _kpi("One position", f"{num(lim.get('max_position_pct')) or 0:g}%", "market exposure, one position"),
                _kpi("One sector", f"{num(lim.get('max_sector_pct')) or 0:g}%", "market exposure, one sector"),
                _kpi("Min reward:risk", f"{num(lim.get('min_reward_risk')) or 0:g}×", "planned, after costs")]
        blocks.append(block("kpis", "limits", "Your risk limits", (prof.get("profile") or "custom") + " profile"
                            + ("" if prof.get("stored") else " (owner default: no profile saved yet)"), items=kpis))
    if e_b or not isinstance(book, dict):
        src.miss(SRC_RISK_BOOK, why(e_b) if e_b else "today's usage could not be read")
    else:
        day = book.get("day") or {}
        eq = book.get("equity") or {}
        as_of = iso_day(book.get("as_of"))
        equity = num(eq.get("equity_rs"))
        if equity is None:
            src.missing.append(f"{SRC_RISK_BOOK}: equity is unknown ("
                               + ("; ".join(eq.get("unknown_reasons") or []) or "an open position could not be marked") + ")")
        else:
            src.add(SRC_RISK_BOOK, as_of)
            day_pnl, day_start = num(day.get("pnl_rs")), num(day.get("start_equity_rs"))
            day_pct = max(0.0, -day_pnl) / day_start * 100 if day_pnl is not None and day_start else None
            limit_pct = num(lim.get("daily_loss_pct"))
            kpis2 = [_kpi("Paper equity", price(equity), None),
                     _kpi("Used of today's loss limit", f"{day_pct:.2f}%" if day_pct is not None else None,
                          f"limit {limit_pct:g}%" if limit_pct is not None else None,
                          "warn" if day_pct is not None and limit_pct and day_pct >= limit_pct * 0.8 else None),
                     _kpi("Open risk reserved", price(num((book.get("open") or {}).get("risk_rs"))), "all open positions")]
            blocks.append(block("kpis", "usage", "Today's usage", None, items=kpis2))
            if day_pct is not None and limit_pct and day_pct >= limit_pct * 0.8:
                tone = "warn"
    if intent.symbol:
        ti, e_t = await _try(rd.trade_idea(ctx["request"], ctx["user_id"], intent.symbol, ctx.get("message") or ""))
        if not e_t and ti is not None:
            sized = getattr(ti, "sized", None) or {}
            if sized.get("status") in ("sized", "not_confirmed"):
                qty = sized.get("quantity") if sized.get("quantity") is not None else sized.get("lots")
                risk = (sized.get("estimated_risk_rs") or {}).get("total") if isinstance(sized.get("estimated_risk_rs"), dict) else None
                pct_eq = num(sized.get("risk_pct_of_equity"))
                blocks.append(block("kpis", "sized", f"Sized for {intent.symbol} at today's plan", None,
                                    items=[_kpi("Size", f"{qty} {sized.get('unit') or ''}".strip() if qty is not None else None,
                                                "risk service, your saved profile"),
                                           _kpi("Max loss", price(risk), f"{pct_eq:.2f}% of equity" if pct_eq is not None else None, "warn")]))
                if qty is not None:
                    head = f"At your per-trade limit, {intent.symbol} sizes to {qty} {sized.get('unit') or ''}".rstrip() + \
                          (f", risking {price(risk)}." if risk is not None else ".")
            elif sized.get("status") == "not_sizable":
                reason = next((r.get("message") for r in sized.get("blocking") or [] if isinstance(r, dict) and r.get("message")), None)
                blocks.append(notice(f"{intent.symbol} does not size on your account" + (f": {reason}" if reason else "") + ".", "warn", "not-sizable"))
    if not head:
        head = "Your risk budget and today's usage." if blocks else None
    title = f"How much to risk in {intent.symbol}" if intent.symbol else "How much to risk"
    return assemble("position_size", title, as_of, head, tone, blocks, src,
                    follow("What are my open trades doing?", "Which F&O setups are attractive?",
                           "What is the market view today?", "What's the setup on this stock?"), now=ctx.get("now"))


async def trade_validity(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q8 "Is my trade in X still valid?" — today's fresh read of the desk's rules for X, against the newest plan
    recorded earlier for X (Mongo trade_plans), so what changed since it was recorded is explicit, not guessed."""
    src: Sources = ctx["src"]
    sym = intent.symbol or ""
    (stored, e_s), (ti, e_t), (bars, e_bars) = await asyncio.gather(
        _try(rd.latest_trade_plan(sym)), _try(rd.trade_idea(ctx["request"], ctx["user_id"], sym, ctx.get("message") or "")),
        _try(rd.stock_bars(sym)))
    blocks: List[Dict[str, Any]] = []
    decision = None
    head = None
    tone = "neutral"
    as_of = None
    plan = getattr(ti, "plan", None) if ti is not None and not e_t else None
    status = None
    tp: Dict[str, Any] = {}
    if e_t or not isinstance(plan, dict):
        src.miss(SRC_PLAN, why(e_t) if e_t else "today's plan could not be built")
    else:
        as_of = (plan.get("data_as_of") or {}).get("price")
        src.add(SRC_PLAN, as_of)
        status = PLAN_DECISION.get(plan.get("status") or "", "no_setup")
        tp = _preferred_tp(plan, getattr(ti, "widget", None)) if status in SHOWN_PLAN else {}
        decision = _decision(status, plan, tp)
    orig: Dict[str, Any] = {}
    if e_s:
        src.miss(SRC_TRADE_PLANS, why(e_s))
    elif not stored:
        src.missing.append(f"{SRC_TRADE_PLANS}: no plan is on record for {sym}")
    else:
        orig = stored if isinstance(stored, dict) else {}
        src.add(SRC_TRADE_PLANS, orig.get("created_at") or (orig.get("data_as_of") or {}).get("price"))
    changes: List[Dict[str, Any]] = []
    if orig and tp:
        o_dir = (orig.get("strategy") or {}).get("direction")
        n_dir = (tp.get("strategy") or {}).get("direction")
        if o_dir and n_dir and o_dir != n_dir:
            changes.append({"text": f"Direction changed: recorded {o_dir}, today {n_dir}.", "tone": "warn"})
        o_stop, n_stop = num((orig.get("stop") or {}).get("price")), num(tp.get("stop", {}).get("price"))
        if o_stop is not None and n_stop is not None and r2(o_stop) != r2(n_stop):
            changes.append({"text": f"Stop moved: recorded {price(o_stop)}, today {price(n_stop)}.", "tone": "warn"})
        if orig.get("plan_id") and orig.get("plan_id") == tp.get("plan_id"):
            changes.append({"text": "The recorded plan is still the one in force today.", "tone": None})
    elif orig and not tp:
        rec_day = day_text(iso_day(orig.get("created_at") or (orig.get("data_as_of") or {}).get("price")))
        changes.append({"text": f"A plan was recorded{f' on {rec_day}' if rec_day else ''}, but the desk's rules find no setup today.",
                        "tone": "warn"})
    if changes:
        blocks.append(block("list", "changes", "What has changed since it was recorded", None, items=changes))
    levels: List[Dict[str, Any]] = []
    if tp:
        e, s = tp.get("entry") or {}, tp.get("stop") or {}
        if num(e.get("price")) is not None:
            levels.append({"kind": "entry", "price": num(e["price"]), "label": f"Today's entry {price(e['price'])}"})
        if num(s.get("price")) is not None:
            levels.append({"kind": "stop", "price": num(s["price"]), "label": f"Today's stop {price(s['price'])}"})
    if orig:
        oe = orig.get("entry") or {}
        if num(oe.get("price")) is not None:
            levels.append({"kind": "entry", "price": num(oe["price"]), "label": f"Recorded entry {price(oe['price'])}"})
    if e_bars:
        src.miss(f"{SRC_BARS} · {sym}", why(e_bars))
    else:
        src.add(SRC_BARS, bars[-1][0] if bars else None)
        chart = _chart(sym, bars, "chart", f"{sym} · the plan, then and now", None, spans=(20, 50), levels=levels)
        if chart:
            blocks.append(chart)
    if status == "setup_ready":
        tone = "up"
        head = (f"{sym}: the setup recorded earlier still holds under today's rules." if orig else
               f"{sym}: today's rules find a setup; no earlier plan is on record to compare it with.")
    elif status in ("wait", "avoid", "no_setup"):
        tone = "warn" if status == "wait" else "down"
        head = (f"{sym}: the setup is no longer there under today's rules ({DECISION_LABELS.get(status, status)})." if orig
               else f"{sym}: {DECISION_LABELS.get(status, status)} today.")
    return assemble("trade_validity", f"{sym} · is the setup still valid?", as_of, head, tone, blocks, src,
                    follow(f"Should I book profits or hold {sym}?", "What are my open trades doing?",
                           "What is the market view today?", f"What's the setup for {sym}?"),
                    decision=decision, now=ctx.get("now"))


async def exit_options(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q9 "Should I book profits or hold X?" — the open paper trade's own levels and today's price, distance to its
    stop and target. It shows the facts and never tells the user to exit or hold (that is advice, not a fact)."""
    src: Sources = ctx["src"]
    sym = intent.symbol or ""
    (out, e_o), (bars, e_bars) = await asyncio.gather(_try(rd.open_trades(ctx["request"])), _try(rd.stock_bars(sym)))
    blocks: List[Dict[str, Any]] = []
    head = None
    tone = "neutral"
    as_of = None
    trade = None
    if e_o or not isinstance(out, dict):
        src.miss(SRC_PAPER, why(e_o) if e_o else "the paper book could not be read")
    else:
        as_of = iso_day(out.get("as_of"))
        if as_of:
            src.add(SRC_PAPER, as_of)
        trade = next((t for t in out.get("trades") or [] if isinstance(t, dict) and t.get("symbol") == sym and t.get("status") == "open"), None)
    if trade:
        pnl = num(trade.get("unrealized_pnl_rs"))
        entry, last, stop, target = (num(trade.get(k)) for k in ("entry_price", "last_close", "stop_price", "target_price"))
        kpis = [_kpi("Entry", price(entry), None), _kpi("Last close", price(last), f"as of {day_text(as_of)}" if as_of else None),
                _kpi("Unrealised P&L", price(pnl), None, tone_of(pnl))]
        if last is not None and stop not in (None, 0):
            kpis.append(_kpi("Distance to stop", pct((last - stop) / stop * 100), None, "warn"))
        if last not in (None, 0) and target is not None:
            kpis.append(_kpi("Distance to target", pct((target - last) / last * 100), None, "up"))
        blocks.append(block("kpis", "trade", f"Your open trade in {sym}", None, items=kpis))
        tone = tone_of(pnl)
        bits = [x for x in (f"unrealised {price(pnl)}" if pnl is not None else None,
                            f"{price(last)} against stop {price(stop)}" if last is not None and stop is not None else None,
                            f"target {price(target)}" if target is not None else None) if x]
        head = f"{sym}: " + ", ".join(bits) + "." if bits else f"{sym}: your open trade."
    else:
        blocks.append(notice(f"No open paper trade in {sym} is on record here.", "info", "none"))
        head = f"No open paper trade in {sym} is on record here."
    if e_bars:
        src.miss(f"{SRC_BARS} · {sym}", why(e_bars))
    else:
        src.add(SRC_BARS, bars[-1][0] if bars else None)
        levels = []
        if trade:
            if num(trade.get("stop_price")) is not None:
                levels.append({"kind": "stop", "price": num(trade["stop_price"]), "label": f"Stop {price(trade['stop_price'])}"})
            if num(trade.get("target_price")) is not None:
                levels.append({"kind": "target", "price": num(trade["target_price"]), "label": f"Target {price(trade['target_price'])}"})
        chart = _chart(sym, bars, "chart", f"{sym} · price against stop and target", None, spans=(20, 50), levels=levels)
        if chart:
            blocks.append(chart)
    blocks.append(notice("Ideas to review, not advice: this shows your trade's own levels and today's price; it does "
                         "not tell you to exit or hold.", "info", "no-advice"))
    return assemble("exit_options", f"{sym} · hold, trail or exit", as_of, head, tone, blocks, src,
                    follow(f"Is my trade in {sym} still valid?", "What are my open trades doing?",
                           "What is the market view today?", "How much should I risk?"), now=ctx.get("now"))


# ── Release 3 ────────────────────────────────────────────────────────────────

REVIEW_TRADES = 300          # newest closed trades read; the curve says so when the read is full
REVIEW_LOOKBACK_DAYS = 120   # decisions read this far back, to find the latest session with activity
CURVE_SESSIONS = 20
REVIEW_ROWS = 15
RULE_EXITS = ("stop", "trailing_stop", "target", "time", "trend", "premium_stop", "premium_target", "expiry")
YOUR_EXITS = ("manual", "roll")
NOT_ENTERED = ("entry_not_reached", "cancelled")
EXIT_LABELS = {"stop": "Stop", "trailing_stop": "Trailing stop", "target": "Target", "time": "Max hold reached",
               "trend": "Trend exit", "premium_stop": "Premium stop", "premium_target": "Premium target",
               "expiry": "Expiry", "manual": "Closed by you", "roll": "Rolled", "risk_control": "Risk control",
               "entry_not_reached": "Entry not reached", "cancelled": "Cancelled"}
REFUSING = ("block", "halt", "reject", "defer")           # services/risk_gate/service.py BLOCKING
HIT_RATE_NOTE = ("There is no live hit-rate for the desk's signals yet: no signal outcome has been recorded "
                 "(positional_outcomes is empty), and the idea scorecard is a static backtest, not a live figure. "
                 "This review is your own paper record only.")


def _ist_day(v: Any) -> Optional[str]:
    """The IST calendar day of a stored UTC time (an ISO string or a datetime), or of a plain date."""
    if isinstance(v, str) and len(v) > 10:
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return iso_day(v)
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return iso_day(v)


def _close_day(t: Dict[str, Any]) -> Optional[str]:
    return iso_day(t.get("exit_session")) or _ist_day(t.get("closed_at"))


def _r_multiple(t: Dict[str, Any]) -> Optional[float]:
    """(exit − fill) ÷ (fill − stop) for a share trade with its planned stop below the fill; None otherwise (an F&O
    structure has no per-share stop, and a stop at or above the fill gives no risk to measure against)."""
    if t.get("kind") not in (None, "cash"):
        return None
    fill = num(t.get("sim_entry_price")) if num(t.get("sim_entry_price")) is not None else num(t.get("entry_price"))
    stop, out = num(t.get("stop_price")), num(t.get("exit_price"))
    if fill is None or stop is None or out is None or fill - stop <= 0:
        return None
    return round((out - fill) / (fill - stop), 2)


def _r_text(r: Optional[float]) -> Optional[str]:
    return None if r is None else ("+" if r >= 0 else MINUS) + f"{abs(r):.2f}R"


def _outcome(row: Dict[str, Any]) -> str:
    o = str(row.get("outcome") or "").lower()
    return "allowed" if o.startswith("allow") else "reduced" if o.startswith("reduc") else \
        "refused" if o.startswith(("block", "refus", "reject")) else "other"


def _review_period(mode: str, today: date, active: List[str]) -> Tuple[date, date, bool]:
    """(start, end, fell_back). The day (or ISO week) asked about when it has activity; else the latest day (week) that
    has; else the day (week) asked about, empty."""
    days = sorted({date.fromisoformat(d) for d in active if d and d <= today.isoformat()})
    if mode == "week":
        start = today - timedelta(days=today.weekday())
        if any(start <= d <= today for d in days) or not days:
            return start, today, False
        last = days[-1]
        return last - timedelta(days=last.weekday()), last, True
    if today in days or not days:
        return today, today, False
    return days[-1], days[-1], True


def _on(mode: str, period: str, this: bool = False) -> str:
    """'on 30 Oct 2026' for a day; 'this week' / 'in 26 Oct – 30 Oct 2026' for a week."""
    return f"on {period}" if mode == "day" else ("this week" if this else f"in {period}")


def _period_text(mode: str, start: date, end: date) -> str:
    if mode == "week":
        return f"{short_day(start)} – {day_text(end)}" if start != end else day_text(end)
    return day_text(start)


async def daily_review(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q15 "What did I learn from today's trades?" — the paper book's own record for the day (or the ISO week): what
    closed and how (plan vs actual, R achieved), which exits came from the plan's rules and which from you, what the
    risk checks refused, and the curve of realised P&L. Facts from the record, never advice; there is no live signal
    hit-rate to quote, and the answer says so."""
    src: Sources = ctx["src"]
    uid = ctx["user_id"]
    mode = "week" if (intent.params or {}).get("period") == "week" else "day"
    today = src.w.today if src.w is not None else datetime.now(IST).date()
    since = datetime.combine(today - timedelta(days=REVIEW_LOOKBACK_DAYS), time(0), IST).astimezone(timezone.utc).isoformat()
    (closed, e_c), (decs, e_d) = await asyncio.gather(_try(rd.closed_trades(uid, REVIEW_TRADES)),
                                                      _try(rd.risk_decisions(uid, since)))
    closed = [t for t in closed or [] if isinstance(t, dict)] if not e_c else []
    decs = [d for d in decs or [] if isinstance(d, dict)] if not e_d else []
    superseded = {d.get("supersedes") for d in decs if d.get("supersedes")}
    decs = [d for d in decs if d.get("_id") not in superseded]          # a refused reservation's row replaces the first
    active = [_close_day(t) for t in closed] + [_ist_day(d.get("at")) for d in decs]
    start, end, fell_back = _review_period(mode, today, [a for a in active if a])
    s_iso, e_iso = start.isoformat(), end.isoformat()

    def in_period(day: Optional[str]) -> bool:
        return day is not None and s_iso <= day <= e_iso
    trades = [t for t in closed if in_period(_close_day(t))]
    period_decs = [d for d in decs if in_period(_ist_day(d.get("at")))]
    # The record is read now: it is today's unless the answer falls back to an older day or week, which then carries
    # that date (and the stale notice when it is older than the previous session).
    as_of = e_iso if fell_back else today.isoformat()
    for name, err in ((SRC_CLOSED, e_c), (SRC_DECISIONS, e_d)):
        if err:
            src.miss(name, why(err))
        else:
            src.add(name, as_of)
    blocks: List[Dict[str, Any]] = []
    period = _period_text(mode, start, end)

    entered = [t for t in trades if t.get("exit_reason") not in NOT_ENTERED]
    not_entered = len(trades) - len(entered)
    nets = [num(t.get("net_pnl_rs")) for t in entered]
    known = [n for n in nets if n is not None]
    wins, losses = sum(1 for n in known if n > 0), sum(1 for n in known if n < 0)
    total = round(sum(known), 2) if known else None
    rs = [r for r in (_r_multiple(t) for t in entered) if r is not None]
    if not e_c and trades:
        decided = wins + losses
        blocks.append(block("kpis", "record", f"The record · {period}", None, items=[
            _kpi("Closed", str(len(entered)), f"{not_entered} not entered" if not_entered else None),
            _kpi("Wins / losses", f"{wins} / {losses}", "by net P&L"),
            _kpi("Win rate", f"{wins / decided * 100:.0f}%" if decided else None,
                 f"of {decided} trade{'s' if decided != 1 else ''} with a result" if decided else "no trade with a net result"),
            _kpi("Realised P&L", rupees(total), "net of estimated costs" + (
                f"; {len(nets) - len(known)} without a net figure left out" if len(known) < len(nets) else ""), tone_of(total)),
            _kpi("Average R", _r_text(round(sum(rs) / len(rs), 2)) if rs else None,
                 f"{len(rs)} of {len(entered)} had a stop to measure against, before costs" if rs
                 else "no trade had a stop to measure against")]))
        rows = []
        for t in trades[:REVIEW_ROWS]:
            sym = t.get("symbol")
            r = _r_multiple(t)
            strategy = t.get("kind") not in (None, "cash")
            label = EXIT_LABELS.get(t.get("exit_reason") or "", t.get("exit_reason") or "—")
            net = num(t.get("net_pnl_rs"))
            rows.append({"symbol": sym, "tone": tone_of(net), "cells": {
                "symbol": sym, "exit": label + (f" · {t.get('family_name')}" if strategy and t.get("family_name") else ""),
                "planned": None if strategy else r2(t.get("entry_price")),
                "fill": None if strategy else r2(t.get("sim_entry_price")),
                "stop": r2(t.get("stop_underlying") if strategy else t.get("stop_price")),
                "target": r2(t.get("target_underlying") if strategy else t.get("target_price")),
                "out": None if strategy else r2(t.get("exit_price")),
                "r": _r_text(r), "pnl": r2(net)}})
        blocks.append(block("ranked", "plan_vs_actual", f"Plan vs actual · {len(trades)} closed",
                            "Planned entry, stop and target against the fill and the exit. R = (exit − fill) ÷ (fill − stop), "
                            "before costs; an F&O structure's stop and target are underlying levels and it has no R here.",
                            columns=[{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                     {"key": "exit", "label": "Exit", "align": "left", "format": "text"},
                                     {"key": "planned", "label": "Planned entry", "align": "right", "format": "price"},
                                     {"key": "fill", "label": "Fill", "align": "right", "format": "price"},
                                     {"key": "stop", "label": "Stop", "align": "right", "format": "price"},
                                     {"key": "target", "label": "Target", "align": "right", "format": "price"},
                                     {"key": "out", "label": "Exit price", "align": "right", "format": "price"},
                                     {"key": "r", "label": "R", "align": "right", "format": "text"},
                                     {"key": "pnl", "label": "Net P&L", "align": "right", "format": "price"}],
                            rows=rows))
        facts_list: List[Dict[str, Any]] = []
        if entered:
            reasons = Counter(t.get("exit_reason") for t in entered)
            by_rule = sum(reasons[k] for k in RULE_EXITS)
            mine = [t.get("symbol") for t in entered if t.get("exit_reason") in YOUR_EXITS]
            parts = ", ".join(f"{reasons[k]} {EXIT_LABELS[k].lower()}" for k in RULE_EXITS if reasons[k])
            facts_list.append({"text": f"{by_rule} of {len(entered)} exits came from the plan's own rules"
                                       + (f" ({parts})" if parts else "") + f"; {len(mine)} "
                                       + ("was" if len(mine) == 1 else "were") + " closed by you"
                                       + (f" ({', '.join(s for s in mine if s)})" if mine else "") + ".", "tone": None})
            if reasons["risk_control"]:
                facts_list.append({"text": f"{reasons['risk_control']} closed by a risk control.", "tone": "warn"})
            gaps = [t.get("symbol") for t in entered
                    if any(isinstance(f, dict) and f.get("code") == "gap_through_stop" for f in t.get("flags") or [])]
            if gaps:
                facts_list.append({"text": f"{len(gaps)} stop exit{'s' if len(gaps) != 1 else ''} filled below the stop "
                                           f"({', '.join(s for s in gaps if s)}): the session opened through it, so the loss "
                                           "was larger than the stop distance.", "tone": "warn"})
            scored = [(t.get("symbol"), num(t.get("net_pnl_rs"))) for t in entered if num(t.get("net_pnl_rs")) is not None]
            if scored:
                best, worst = max(scored, key=lambda x: x[1]), min(scored, key=lambda x: x[1])
                facts_list.append({"text": f"Largest result: {best[0]} {rupees(best[1])}"
                                           + (f"; smallest: {worst[0]} {rupees(worst[1])}." if worst is not best else "."),
                                   "tone": None})
            held = [num(t.get("held_sessions")) for t in entered if num(t.get("held_sessions")) is not None]
            if held:
                facts_list.append({"text": f"Held {sum(held) / len(held):.1f} sessions on average, entry to exit.", "tone": None})
        if not_entered:
            facts_list.append({"text": f"{not_entered} trade{'s' if not_entered != 1 else ''} closed without an entry "
                                       "(the entry level was not reached, or it was cancelled): no P&L.", "tone": None})
        if facts_list:
            blocks.append(block("list", "exits", "How the trades ended", None, items=facts_list))
    elif not e_c:
        blocks.append(notice(f"No paper trade closed {_on(mode, period)}." if closed else
                             "No closed paper trades are on record yet.", "info", "no-closes"))
    if not e_d:
        if period_decs:
            n = Counter(_outcome(d) for d in period_decs)
            items = [{"text": f"{len(period_decs)} entry request{'s' if len(period_decs) != 1 else ''} checked: "
                              f"{n['allowed']} allowed, {n['reduced']} reduced, {n['refused']} refused"
                              + (f", {n['other']} other" if n["other"] else "") + ".", "tone": None}]
            refusals: Counter = Counter()
            example: Dict[str, str] = {}
            for d in period_decs:
                if _outcome(d) != "refused":
                    continue
                rs_ = [x for x in d.get("reasons") or [] if isinstance(x, dict)]
                hard = [x for x in rs_ if x.get("severity") in REFUSING] or rs_
                for x in hard:
                    code = x.get("code") or "unspecified"
                    refusals[code] += 1
                    example.setdefault(code, str(x.get("message") or "").strip())
            for code, k in refusals.most_common(3):
                msg = example.get(code) or ""
                items.append({"text": f"Refused for {code.replace('_', ' ')} ({k}×)" + (f": {msg[:160]}" if msg else "."),
                              "tone": "warn"})
            blocks.append(block("list", "risk_checks", "What the risk checks said", None, items=items))
        else:
            blocks.append(notice(f"No entry request was checked by the risk rules {_on(mode, period)}.", "info", "no-checks"))
    curve_src = [(_close_day(t), num(t.get("net_pnl_rs"))) for t in closed
                 if t.get("exit_reason") not in NOT_ENTERED and _close_day(t) and _close_day(t) <= e_iso]
    by_day: Dict[str, float] = {}
    for day, net in curve_src:
        if net is not None:
            by_day[day] = by_day.get(day, 0.0) + net
    days = sorted(by_day)[-CURVE_SESSIONS:]
    if days:
        run, items = 0.0, []
        for d in days:
            run += by_day[d]
            items.append({"label": short_day(d), "value": round(run, 2)})
        blocks.append(block("bars", "curve", "Equity curve: cumulative realised P&L",
                            f"Net of estimated costs, one bar per session with a close, {day_text(days[0])} to "
                            f"{day_text(days[-1])}; paper account, not a time-weighted return"
                            + (f"; the newest {REVIEW_TRADES} closed trades are read" if len(closed) >= REVIEW_TRADES else "") + ".",
                            unit="₹", orientation="v", items=items))
    blocks.append(notice(HIT_RATE_NOTE, "info", "hit-rate"))

    refused = sum(1 for d in period_decs if _outcome(d) == "refused")
    checks = (f"the risk checks refused {refused} of {len(period_decs)} entry request{'s' if len(period_decs) != 1 else ''}"
              if period_decs else None)
    when = "" if fell_back else " " + _on(mode, period, this=True)
    if e_c and e_d:
        head = None
    elif e_c:
        head = "Your closed paper trades could not be read" + (f"; {checks}{when}." if checks else ".")
    elif not closed and not decs:
        head = "No closed paper trades or risk checks are on record yet, so there is nothing to review." if not e_d else \
            "No closed paper trades are on record yet."
    else:
        lead = (f"Nothing was recorded {_on(mode, day_text(today), this=True)}; the latest "
                f"{'session' if mode == 'day' else 'week'} with activity is {period}. ") if fell_back else ""
        if entered:
            body = (f"{len(entered)} paper trade{'s' if len(entered) != 1 else ''} closed{when}: "
                    f"{wins} win{'s' if wins != 1 else ''}, {losses} loss{'es' if losses != 1 else ''}"
                    + (f", net {rupees(total)}" if total is not None else "") + ".")
        else:
            body = f"No paper trade closed{when}" + (f"; {checks}." if checks else ".")
        head = lead + body
    other = "What did I learn from today's trades?" if mode == "week" else "How did I do this week?"
    return assemble("daily_review", f"Your trading review · {period}", as_of, head,
                    tone_of(total) if entered else "neutral", blocks, src,
                    follow(other, "What are my open trades doing?", "How much should I risk?", "What is the market view today?"),
                    now=ctx.get("now"))


BUILDERS = {"market_view": market_view, "smart_money": smart_money, "top_opportunities": top_opportunities,
            "breakouts": breakouts, "unusual_volume": unusual_volume, "stock_decision": stock_decision,
            "expected_move": expected_move, "open_trades": open_trades, "fno_setups": fno_setups,
            "trade_validity": trade_validity, "exit_options": exit_options, "position_size": position_size,
            "daily_review": daily_review}


async def build(intent: Intent, user: Optional[Dict[str, Any]] = None, request: Any = None, message: str = "",
                trade_idea: Any = None, now: Any = None) -> Dict[str, Any]:
    """The payload for `intent`. Raises only on a programming fault; every data failure is inside the payload."""
    src = Sources(await rd.window())
    ctx = {"src": src, "request": request, "user_id": (user or {}).get("user_id"), "message": message,
           "trade_idea": trade_idea, "now": now}
    return await BUILDERS[intent.name](intent, ctx)
