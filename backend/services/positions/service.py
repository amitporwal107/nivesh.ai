"""The Open Positions workspace: every open position of the user, real and paper, grouped by underlying. Read-only
towards brokers: nothing here can place, modify or cancel an order.

Sources, each read on every call and reported in `sources` with its own time and error:
    broker   every connected broker account's NET positions, read live (services/brokers/hub_reads); each changed
             read is snapshotted (store.SNAPSHOTS). An account that cannot be read says why; it never fails the others.
    paper    the desk's open paper trades (routes/desk_trading.list_paper_trades — the desk's own read, which also
             applies the paper exit rule as the desk screen does)

Prices (owner rules of 28 and 29 Oct 2026: today's live price, else Kite's saved close, else the exchange's end of day;
never older than the previous session):
    underlying   services/kite_live_feed/day_quote.day_quotes (Kite live / Kite close), else the NSE bhavcopy spot of
                 the F&O chain's day (routes/fno, which refuses a day older than the previous session)
    options      the chain of their expiry (routes/fno.chain): settle price (else the traded close), implied volatility
                 and Greeks (Black-76) of that day; an expired or stale chain is refused there and the group says so
    futures      that day's settle (routes/fno._latest_futures)
    shares       the broker's own last price on its live read; a paper trade's last end-of-day close
P&L shown for a broker position is the BROKER's own figure on its live read. The analytics (payoff, Greeks, scenarios)
are worked out on the prices above and are gross of charges.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from services import option_pricing

from . import analytics, store, symbols

logger = logging.getLogger(__name__)

INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
READ_ONLY_NOTE = "Nivesh reads positions; it cannot place orders."
DAY_REALISED_NOTE = ("Not available: the brokers' position reads do not split the day's realised P&L from the rest, "
                     "so no figure is shown rather than a mixed one.")
BROKER_CONCURRENCY = 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


# ── reads ────────────────────────────────────────────────────────────────────

async def read_broker(request: Any, db, user_id: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(source entries, open rows) from every broker account. A row carries its account and the read's time."""
    from routes import broker_connect as bc
    from services.brokers import hub_reads as hub
    try:
        await bc._hub_user(request)
    except HTTPException as e:
        if e.status_code == 403:
            return [{"source": "broker", "ok": False, "account_id": None, "broker": None, "broker_display": None,
                     "error": {"code": "BROKER_HUB_OFF", "message": "Broker connections are not enabled for this account."},
                     "read_at": None, "broker_as_of": None, "rows": 0, "snapshot_id": None}], []
        raise
    docs = await bc._user_accounts(user_id)
    gate = asyncio.Semaphore(BROKER_CONCURRENCY)

    async def one(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        entry = {"source": "broker", **bc._account_entry(doc), "ok": False, "error": None, "read_at": None,
                 "broker_as_of": None, "rows": 0, "closed_rows": 0, "snapshot_id": None}
        if not doc.get("native"):
            entry["error"] = {"code": hub.CODE_NOT_SUPPORTED, "message": bc._NOT_NATIVE_POSITIONS}
            return entry, []
        try:
            async with gate:
                rows = await hub.read_account_positions(db, doc, "net")
        except Exception as e:  # noqa: BLE001 — one account's failure is reported in its entry
            code, message = hub.describe_failure(e, doc.get("broker") or "", "net positions")
            entry["error"] = {"code": code, "message": message}
            return entry, []
        read_at = _now()
        entry.update(ok=True, read_at=read_at)
        open_rows = [r for r in rows if _num(r.get("quantity"))]
        entry["rows"], entry["closed_rows"] = len(open_rows), len(rows) - len(open_rows)
        try:
            entry["snapshot_id"] = await store.record_snapshot(
                db, user_id=user_id, account_id=doc["account_id"], broker=doc.get("broker") or "", read_at=read_at,
                rows=rows, broker_as_of=None)
        except Exception as e:  # noqa: BLE001 — the read stands; the snapshot is reported missing
            logger.warning("positions: snapshot not stored for an account (%s)", type(e).__name__)
        for r in open_rows:
            r["_account_id"], r["_broker"], r["_broker_display"], r["_read_at"] = (
                doc["account_id"], doc.get("broker") or "", entry["broker_display"], read_at)
        return entry, open_rows

    results = await asyncio.gather(*(one(d) for d in docs))
    return [e for e, _ in results], [r for _, rows in results for r in rows]


async def read_paper(request: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]], int]:
    """(source entry, held open paper trades, waiting entries)."""
    from routes import desk_trading
    from services import desk_trading as svc
    entry = {"source": "paper", "ok": False, "error": None, "as_of": None}
    try:
        out = await desk_trading.list_paper_trades(request, status_filter="open")
    except Exception as e:  # noqa: BLE001
        detail = getattr(e, "detail", None)
        entry["error"] = {"code": "PAPER_READ_FAILED", "message": str(detail) if detail else "Paper trades could not be read."}
        return entry, [], 0
    trades = [t for t in out.get("trades") or [] if t.get("status") == "open"]
    held = [t for t in trades if t.get("entry_status", "assumed") in svc.ENTERED or t.get("kind") == "strategy"]
    entry.update(ok=True, as_of=out.get("as_of"), marks_error=out.get("marks_error"))
    return entry, held, len(trades) - len(held)


async def underlying_quotes(underlyings: List[str]) -> Dict[str, Any]:
    from services.kite_live_feed import day_quote
    return await day_quote.day_quotes(underlyings)


async def price_fno(request: Any, underlying: str, option_expiries: List[str]) -> Dict[str, Any]:
    """{as_of, spot, lot_size, futures: {expiry: contract}, chains: {expiry: chain}, error}. `error` names why
    nothing current could be read (stale, expired, no data) — never an older day's figures."""
    from routes import fno
    out: Dict[str, Any] = {"as_of": None, "spot": None, "lot_size": None, "futures": {}, "chains": {}, "error": None}
    try:
        as_of, spot, lot, contracts = await fno._latest_futures(underlying)
        out.update(as_of=as_of, spot=spot, lot_size=lot, futures={c["expiry"]: c for c in contracts})
    except HTTPException as e:
        out["error"] = str(e.detail)
    for exp in option_expiries:
        try:
            ch = await fno.chain(request, symbol=underlying, expiry=date.fromisoformat(exp), around=fno.MAX_AROUND)
        except HTTPException as e:
            out["chains"][exp] = {"error": str(e.detail)}
            continue
        out["chains"][exp] = ch
        s = ch.get("summary") or {}
        out["as_of"] = out["as_of"] or s.get("as_of")
        out["spot"] = out["spot"] or s.get("spot")
        out["lot_size"] = out["lot_size"] or ch.get("lot_size")
    return out


# ── legs ─────────────────────────────────────────────────────────────────────

def _option_side(chain: Dict[str, Any], strike: float, option_type: str) -> Optional[Dict[str, Any]]:
    for r in chain.get("strikes") or []:
        if abs(float(r.get("strike") or 0) - strike) < 1e-6:
            return r.get("call" if option_type == "call" else "put")
    return None


def _price_leg(leg: Dict[str, Any], c: symbols.Contract, pricing: Dict[str, Any], spot_scale: float) -> List[str]:
    """Fill mark / forward / iv / t / Greeks of an F&O leg from the pricing read; return what could not be priced."""
    problems: List[str] = []
    if c.instrument == "FUT":
        fut = pricing["futures"].get(c.expiry)
        px = _num((fut or {}).get("settle")) or _num((fut or {}).get("close"))
        if px is None:
            problems.append(f"{symbols.label(c)}: no current settle price")
        leg.update(mark=px, forward=px * spot_scale if px else None)
        return problems
    chain = pricing["chains"].get(c.expiry) or {}
    if chain.get("error") or not chain.get("strikes"):
        problems.append(f"{symbols.label(c)}: {chain.get('error') or 'the chain could not be read'}")
        return problems
    side = _option_side(chain, c.strike, leg["option_type"])
    s = chain.get("summary") or {}
    if side is None:
        problems.append(f"{symbols.label(c)}: the strike is not in the chain")
        return problems
    from routes import fno
    leg["mark"] = fno.model_price(side)
    fwd = _num(s.get("forward"))
    leg["forward"] = fwd * spot_scale if fwd else None
    days = s.get("days_to_expiry")
    leg["t"] = option_pricing.year_fraction(days) if isinstance(days, int) else None
    leg["days_to_expiry"] = days
    leg["iv"] = side["iv"] / 100.0 if side.get("iv") is not None else None
    for g in ("delta", "gamma", "theta", "vega"):
        leg[g] = side.get(g)
    if leg["iv"] is None:
        problems.append(f"{symbols.label(c)}: no implied volatility (the contract did not trade or is not held)")
    return problems


def _leg_from_contract(c: symbols.Contract, qty: float, avg: float) -> Dict[str, Any]:
    kind = "cash" if c.instrument == "EQ" else "future" if c.instrument == "FUT" else "option"
    return {"kind": kind, "option_type": {"CE": "call", "PE": "put"}.get(c.instrument), "strike": c.strike,
            "sign": 1 if qty > 0 else -1, "units": abs(qty), "entry_price": avg, "mark": None, "forward": None,
            "iv": None, "t": None, "delta": None, "gamma": None, "theta": None, "vega": None}


def _public_leg(leg: Dict[str, Any], c: Optional[symbols.Contract], extra: Dict[str, Any]) -> Dict[str, Any]:
    q = leg["sign"] * leg["units"]
    lot = extra.get("lot_size")
    lots = q / lot if lot else None
    return {
        "key": c.key if c else None, "label": symbols.label(c) if c else extra.get("label"),
        "instrument": c.instrument if c else None, "expiry": c.expiry if c else None, "strike": c.strike if c else None,
        "quantity": q, "lots": lots if lots is None or float(lots).is_integer() else round(lots, 2),
        "lot_size": lot, "avg_price": analytics.r2(leg["entry_price"]), "mark": analytics.r2(leg.get("mark")),
        "iv_pct": round(leg["iv"] * 100, 2) if leg.get("iv") is not None else None,
        "greeks": None if leg["kind"] == "option" and leg.get("delta") is None else {
            "delta": round(q * (leg.get("delta") if leg["kind"] == "option" else 1.0), 2),
            "gamma": round(q * (leg.get("gamma") or 0.0), 6), "theta": round(q * (leg.get("theta") or 0.0), 2),
            "vega": round(q * (leg.get("vega") or 0.0), 2)},
        **{k: v for k, v in extra.items() if k != "lot_size"},
    }


# ── groups ───────────────────────────────────────────────────────────────────

def _group_shell(key: str, source: str, underlying: str, kind: str) -> Dict[str, Any]:
    return {"key": key, "source": source, "underlying": underlying, "kind": kind, "accounts": [], "legs": [],
            "unmapped": [], "price": {"spot": None, "source": None, "as_of": None, "pricing_as_of": None},
            "pnl_rs": None, "pnl_source": None, "levels": None, "warnings": [], "analytics": None,
            "margin_request": None, "paper_trade_id": None}


def _finish(group: Dict[str, Any], legs: List[Dict[str, Any]], spot: Optional[float], levels: Optional[Dict[str, Any]],
            physically_settled: bool, problems: List[str]) -> Dict[str, Any]:
    days = [l.get("days_to_expiry") for l in legs if isinstance(l.get("days_to_expiry"), int)]
    priced = [l for l in legs if l["kind"] == "cash" or l.get("mark") is not None]
    # Analytics need every leg: a group with an unpriced leg would show a payoff that is not the position's.
    complete = bool(legs) and len(priced) == len(legs) and bool(spot)
    group["_legs"], group["_spot"] = (legs, spot) if complete else (None, None)
    a = analytics.analyse(legs if complete else [], spot if complete else None, levels,
                          days_to_expiry=min(days) if days else None, physically_settled=physically_settled)
    group["analytics"] = {k: v for k, v in a.items() if k != "warnings"}
    group["warnings"] = a["warnings"] + [{"code": "price_unavailable", "tone": "amber", "text": p} for p in problems]
    if legs and not complete and not problems:
        group["warnings"].append({"code": "price_unavailable", "tone": "amber",
                                  "text": "No current price for the underlying, so nothing is worked out from it."})
    return group


def _margin_request(underlying: str, legs: List[Tuple[symbols.Contract, Dict[str, Any], Optional[int]]]) -> Optional[Dict[str, Any]]:
    """The body for POST /api/fno/margin (Zerodha's calculator), when every leg is a listed F&O contract in whole lots."""
    out = []
    for c, leg, lot in legs:
        if c.instrument == "EQ" or not lot or leg["units"] % lot:
            return None
        out.append({"side": "buy" if leg["sign"] > 0 else "sell",
                    "option_type": {"CE": "call", "PE": "put", "FUT": "future"}[c.instrument],
                    "expiry": c.expiry, "strike": c.strike, "lots": int(leg["units"] // lot)})
    return {"underlying": underlying, "legs": out} if out and len(out) <= 10 else None


async def broker_groups(request: Any, db, user_id: str, rows: List[Dict[str, Any]], quotes: Dict[str, Any],
                        levels_by_u: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    named: List[Tuple[symbols.Contract, Dict[str, Any]]] = [(symbols.normalise(r, r["_broker"]), r) for r in rows]
    by_u: Dict[str, List[Tuple[symbols.Contract, Dict[str, Any]]]] = {}
    unmapped: List[Dict[str, Any]] = []
    for c, r in named:
        if c.mapped:
            by_u.setdefault(c.underlying, []).append((c, r))
        else:
            unmapped.append({"broker_code": r.get("symbol"), "broker_display": r["_broker_display"],
                             "account_id": r["_account_id"], "quantity": _num(r.get("quantity")),
                             "pnl_rs": _num(r.get("pnl")), "problem": c.problem,
                             "avg_price": _num(r.get("avg_price")), "last_price": _num(r.get("last_price"))})
    out: List[Dict[str, Any]] = []
    for u, items in sorted(by_u.items()):
        derivative = any(c.is_derivative for c, _ in items)
        pricing: Dict[str, Any] = {"as_of": None, "spot": None, "lot_size": None, "futures": {}, "chains": {}, "error": None}
        if derivative:
            # A monthly Kite contract carries its month only; its day is the listed futures expiry of that month.
            pricing = await price_fno(request, u, [])
            items = [(symbols.resolve_monthly(c, pricing["futures"].keys()), r) for c, r in items]
            opt_exp = sorted({c.expiry for c, _ in items if c.instrument in ("CE", "PE") and c.mapped and c.expiry})
            if opt_exp:
                more = await price_fno(request, u, opt_exp)
                pricing["chains"] = more["chains"]
                pricing["as_of"] = pricing["as_of"] or more["as_of"]
                pricing["spot"] = pricing["spot"] or more["spot"]
                pricing["lot_size"] = pricing["lot_size"] or more["lot_size"]
                pricing["error"] = pricing["error"] if pricing["spot"] is None else None
        g = _group_shell(f"broker:{u}", "broker", u, "fno" if derivative else "equity")
        q = (quotes.get("quotes") or {}).get(u)
        live = _num((q or {}).get("ltp"))
        if live is not None:
            spot, spot_src, spot_as_of = live, quotes.get("source"), quotes.get("as_of")
        elif derivative and pricing["spot"] is not None:
            spot, spot_src, spot_as_of = pricing["spot"], "nse_bhavcopy", pricing["as_of"]
        else:
            ltps = [_num(r.get("last_price")) for c, r in items if c.instrument == "EQ" and _num(r.get("last_price"))]
            spot, spot_src, spot_as_of = (ltps[0], "broker", items[0][1]["_read_at"]) if ltps else (None, None, None)
        scale = spot / pricing["spot"] if (spot and pricing["spot"] and derivative) else 1.0
        g["price"] = {"spot": spot, "source": spot_src, "as_of": spot_as_of, "pricing_as_of": pricing["as_of"]}
        legs: List[Dict[str, Any]] = []
        problems: List[str] = []
        margin_legs = []
        pnl = 0.0
        pnl_known = True
        for c, r in items:
            qty, avg = _num(r.get("quantity")) or 0.0, _num(r.get("avg_price")) or 0.0
            leg = _leg_from_contract(c, qty, avg)
            if c.instrument == "EQ":
                leg["mark"] = _num(r.get("last_price"))
            elif not c.mapped:
                problems.append(c.problem or f"{r.get('symbol')}: not mapped")
                unmapped.append({"broker_code": r.get("symbol"), "broker_display": r["_broker_display"],
                                 "account_id": r["_account_id"], "quantity": qty, "pnl_rs": _num(r.get("pnl")),
                                 "problem": c.problem, "avg_price": _num(r.get("avg_price")), "last_price": _num(r.get("last_price"))})
                continue
            else:
                problems += _price_leg(leg, c, pricing, scale)
            lot = pricing["lot_size"] if c.is_derivative else None
            if c.is_derivative and lot is None:
                problems.append(f"{symbols.label(c)}: the lot size could not be read from the NSE bhavcopy")
            legs.append(leg)
            margin_legs.append((c, leg, lot))
            bp = _num(r.get("pnl"))
            pnl_known = pnl_known and bp is not None
            pnl += bp or 0.0
            g["legs"].append(_public_leg(leg, c, {
                "lot_size": lot, "ltp": _num(r.get("last_price")), "ltp_source": "broker", "pnl_rs": bp,
                "broker_code": r.get("symbol"), "account_id": r["_account_id"], "broker_display": r["_broker_display"],
                "product": r.get("product"), "read_at": r["_read_at"]}))
            acct = {"account_id": r["_account_id"], "broker_display": r["_broker_display"]}
            if acct not in g["accounts"]:
                g["accounts"].append(acct)
        if pricing.get("error") and derivative:
            problems.append(pricing["error"])
        g["pnl_rs"], g["pnl_source"] = (analytics.r2(pnl) if pnl_known and legs else None), "broker"
        lv = levels_by_u.get(u)
        d = None
        if legs and spot:
            gr = analytics.greeks(legs)
            d = {1: "long", -1: "short", 0: None}[analytics.direction(legs, spot, gr)]
        if lv:
            await store.track_extremes(db, lv, spot)
            g["levels"] = {"stop": lv.get("stop"), "target": lv.get("target"), "trail_pct": lv.get("trail_pct"),
                           "effective_stop": analytics.r2(store.effective_stop(lv, spot, d)), "set_by": "you",
                           "updated_at": lv.get("updated_at")}
        eff = {"stop": g["levels"]["effective_stop"], "target": g["levels"]["target"]} if g["levels"] else None
        _finish(g, legs, spot, eff, derivative and u not in INDEX_UNDERLYINGS, problems)
        g["margin_request"] = _margin_request(u, margin_legs) if derivative else None
        out.append(g)
    if unmapped:
        g = _group_shell("broker:unmapped", "broker", "Not mapped", "unmapped")
        g["unmapped"] = unmapped
        g["warnings"] = [{"code": "unmapped", "tone": "amber",
                          "text": "These rows could not be named as NSE contracts, so nothing is worked out from them."}]
        out.append(g)
    return out


async def paper_groups(request: Any, trades: List[Dict[str, Any]], quotes: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in trades:
        u = (t.get("underlying") or t.get("symbol") or "").upper()
        if t.get("kind") == "strategy":
            g = _group_shell(f"paper:{t['id']}", "paper", u, "fno")
            exps = sorted({l["expiry"] for l in t.get("legs") or [] if l.get("kind") == "option" and l.get("expiry")})
            pricing = await price_fno(request, u, exps)
            q = (quotes.get("quotes") or {}).get(u)
            live = _num((q or {}).get("ltp"))
            spot = live if live is not None else pricing["spot"]
            scale = spot / pricing["spot"] if (spot and pricing["spot"]) else 1.0
            g["price"] = {"spot": spot, "source": quotes.get("source") if live is not None else "nse_bhavcopy",
                          "as_of": quotes.get("as_of") if live is not None else pricing["as_of"],
                          "pricing_as_of": pricing["as_of"]}
            legs, problems = [], []
            for pl in t.get("legs") or []:
                units = (pl.get("lots") or 0) * (pl.get("lot_size") or 1)
                sign = 1 if pl.get("side") == "buy" else -1
                if pl.get("kind") == "cash":
                    c = symbols.Contract(u, "EQ")
                else:
                    c = symbols.Contract(u, "FUT" if pl["kind"] == "future" else ("CE" if pl.get("option_type") == "call" else "PE"),
                                         expiry=pl.get("expiry"), strike=pl.get("strike"))
                leg = _leg_from_contract(c, sign * units, _num(pl.get("entry_price")) or 0.0)
                if c.instrument == "EQ":
                    leg["mark"] = spot
                else:
                    problems += _price_leg(leg, c, pricing, scale)
                legs.append(leg)
                g["legs"].append(_public_leg(leg, c, {"lot_size": pl.get("lot_size"), "ltp": _num(pl.get("mark")),
                                                      "ltp_source": "paper mark", "ltp_date": pl.get("mark_date"),
                                                      "pnl_rs": _num(pl.get("pnl_rs"))}))
            if pricing.get("error") and spot is None:
                problems.append(pricing["error"])
            g["pnl_rs"], g["pnl_source"] = _num(t.get("unrealized_pnl_rs")) or _num(t.get("gross_pnl_rs")), "paper"
            stop, target = _num(t.get("stop_underlying")), _num(t.get("target_underlying"))
            g["levels"] = {"stop": stop, "target": target, "trail_pct": None, "effective_stop": stop,
                           "set_by": "paper trade", "updated_at": t.get("opened_at")} if (stop or target) else None
            g["paper_trade_id"], g["label"] = t["id"], t.get("summary_text") or t.get("family_name")
            _finish(g, legs, spot, {"stop": stop, "target": target}, u not in INDEX_UNDERLYINGS, problems)
        else:
            g = _group_shell(f"paper:{t['id']}", "paper", u, "equity")
            close = _num(t.get("last_close"))
            q = (quotes.get("quotes") or {}).get(u)
            live = _num((q or {}).get("ltp"))
            spot = live if live is not None else close
            g["price"] = {"spot": spot, "source": quotes.get("source") if live is not None else "paper mark (end of day)",
                          "as_of": quotes.get("as_of") if live is not None else t.get("last_close_date"),
                          "pricing_as_of": t.get("last_close_date")}
            qty = _num(t.get("quantity")) or 0.0
            leg = _leg_from_contract(symbols.Contract(u, "EQ"), qty, _num(t.get("entry_price")) or 0.0)
            leg["mark"] = spot
            g["legs"].append(_public_leg(leg, symbols.Contract(u, "EQ"), {
                "lot_size": None, "ltp": close, "ltp_source": "paper mark (end of day)", "ltp_date": t.get("last_close_date"),
                "pnl_rs": _num(t.get("unrealized_pnl_rs"))}))
            g["pnl_rs"], g["pnl_source"] = _num(t.get("unrealized_pnl_rs")), "paper"
            stop, target = _num(t.get("stop_price")), _num(t.get("target_price"))
            g["levels"] = {"stop": stop, "target": target, "trail_pct": None, "effective_stop": stop,
                           "set_by": "paper trade", "updated_at": t.get("opened_at")}
            g["paper_trade_id"] = t["id"]
            problems = [] if spot else [f"{u}: no end-of-day close to mark the paper trade"]
            _finish(g, [leg], spot, {"stop": stop, "target": target}, False, problems)
        out.append(g)
    return out


def summarise(groups: List[Dict[str, Any]], waiting_paper: int) -> Dict[str, Any]:
    real = [g for g in groups if g["kind"] != "unmapped"]
    pnls = [g["pnl_rs"] for g in real if g["legs"]]
    at_stop = [((g.get("analytics") or {}).get("payoff") or {}).get("loss_at_stop_rs") for g in real]
    codes = [w["code"] for g in groups for w in g["warnings"]]
    exposure = [(g.get("analytics") or {}).get("exposure_rs") for g in real]
    return {
        "groups": len(real),
        "positions": sum(len(g["legs"]) for g in real),
        "broker_positions": sum(len(g["legs"]) for g in real if g["source"] == "broker"),
        "paper_positions": sum(1 for g in real if g["source"] == "paper"),
        "paper_waiting_entry": waiting_paper,
        "unmapped_rows": sum(len(g["unmapped"]) for g in groups),
        "unrealised_pnl_rs": analytics.r2(sum(pnls)) if pnls and all(p is not None for p in pnls) else None,
        "unrealised_partial": any(p is None for p in pnls),
        "open_risk_at_stops_rs": analytics.r2(sum(x for x in at_stop if x is not None)) if any(x is not None for x in at_stop) else None,
        "near_stop": codes.count("near_stop"),
        "stop_breached": codes.count("stop_breached"),
        "without_stop": codes.count("no_stop"),
        "expiring_soon": sum(1 for g in groups if any(w["code"] == "expiry_soon" for w in g["warnings"])),
        "exposure_rs": analytics.r2(sum(x for x in exposure if x)) if any(exposure) else None,
        "day_realised_pnl_rs": None,
        "day_realised_note": DAY_REALISED_NOTE,
    }


def public(book: Dict[str, Any]) -> Dict[str, Any]:
    """The book without the working fields (`_legs`, `_spot`) the scenario route reuses."""
    return {**book, "groups": [{k: v for k, v in g.items() if not k.startswith("_")} for g in book["groups"]]}


async def build(request: Any, db, user: Dict[str, Any]) -> Dict[str, Any]:
    """Every open position of the user, grouped, with working fields; pass the result through `public` to send it."""
    uid = user["user_id"]
    await store.ensure_indexes(db)
    (b_sources, b_rows), (p_source, p_trades, waiting), levels_by_u = await asyncio.gather(
        read_broker(request, db, uid), read_paper(request), store.read_levels(db, uid))
    unders = sorted({symbols.normalise(r, r["_broker"]).underlying for r in b_rows}
                    | {(t.get("underlying") or t.get("symbol") or "").upper() for t in p_trades})
    quotes = await underlying_quotes([u for u in unders if u]) if unders else {"quotes": {}, "source": None}
    groups = await broker_groups(request, db, uid, b_rows, quotes, levels_by_u) + await paper_groups(request, p_trades, quotes)
    return {
        "as_of": _now(),
        "read_only": True,
        "note": READ_ONLY_NOTE,
        "sources": b_sources + [p_source],
        "quotes": {"source": quotes.get("source"), "as_of": quotes.get("as_of"), "why": quotes.get("why")},
        "summary": summarise(groups, waiting),
        "groups": groups,
        "method": {"near_stop_pct": analytics.NEAR_STOP_PCT, "expiry_soon_days": analytics.EXPIRY_SOON_DAYS,
                   "gross": "Payoff, scenarios and the loss at a stop are gross: before brokerage, taxes and slippage.",
                   "rate": option_pricing.RISK_FREE_RATE},
    }


async def group_scenario(request: Any, db, user: Dict[str, Any], key: str, moves: List[float], iv_shift: float,
                         days_forward: int) -> Optional[Dict[str, Any]]:
    """One group's scenario table for the given moves of the underlying, volatility shift (points) and days forward.
    None when the user has no such group; `rows` is None (with `why`) when the group cannot be valued."""
    book = await build(request, db, user)
    g = next((x for x in book["groups"] if x["key"] == key), None)
    if g is None:
        return None
    legs, spot = g.get("_legs"), g.get("_spot")
    out = {"key": key, "as_of": book["as_of"], "underlying": g["underlying"], "price": g["price"], "iv_shift": iv_shift,
           "days_forward": days_forward, "gross": True, "rows": None, "why": None}
    if not legs or not spot:
        out["why"] = next((w["text"] for w in g["warnings"] if w["code"] == "price_unavailable"),
                          "This group has no current price, so it cannot be valued.")
        return out
    out["rows"] = analytics.scenario(legs, spot, moves, iv_shift, days_forward)
    if any(r["today_pnl_rs"] is None for r in out["rows"]):
        out["why"] = "An option leg has no implied volatility, so only the expiry column is worked out."
    return out
