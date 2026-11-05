"""The desk's open paper F&O structures for Paper Trading v2 (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.03, §2.04,
§2.05, §4 item 6, §7 `GET /api/v1/paper/fno-structures`). Reads only: nothing here applies an exit, fills a leg or calls
a broker's order API.

SOURCE  the desk's open paper strategy trades (desk_paper_trades, kind "strategy"), read through the P&L dashboard's book
        (services/paper_pnl/book.read_book: the ledger's own serialisation, exits evaluated with persist=False).
PRICES  leg LTP        services/paper_pnl/prices.resolve — the /api/desk/pnl rule: Kite live in session, else the Kite
                       close, else the exchange's end of day; a leg nobody can price is null (MISSING), never the entry
        underlying     the group's spot from services/positions (Kite day quote, else the chain day's NSE spot)
        Greeks / IV    services/positions/service.paper_groups: each option from its expiry's NSE chain (Black-76 at the
                       contract's own implied volatility); an option with no IV leaves the Greeks and the IV / theta
                       scenarios null, with a note
PAYOFF  services/strategy_plan/payoff on the FILLED legs (entry price, strike, lots × lot size): max loss, max profit,
        breakevens at expiry, gross of charges. Owner rule (30 Oct): a structure holding a long future or shares with
        no long put has no "to zero" max loss — `max_loss_rs` is null with `max_loss_reason`, and the loss at the
        structure's own stop is given when it has one.
FILL    desk paper legs are all recorded at once (entry_rule at_once), so every leg normally has its entry. A leg with no
        recorded entry price or quantity is PENDING (filled_qty 0, pnl null) and the structure is `partial`.
        `hedged` = the filled legs' loss is bounded and no long future / shares sit without a long put (defined risk);
        a partly filled spread whose protective leg is pending is therefore unhedged.
SCENARIOS (`pnl_rs` = the change from the structure's model value now, same valuation, gross of charges)
        und_down_2 / und_down_1 / und_up_1 / und_up_2   the underlying moves, every option repriced at its own IV
        iv_up_5 / iv_down_5                             every option's IV ± 5 volatility points, the underlying unchanged
        theta_1d                                        one calendar day passes, nothing else moves
        expiry_at_level                                 held to expiry with the underlying at today's level (intrinsic)
MARGIN  Zerodha's margin calculator (services/fno_margin: Kite basket_order_margins, a CALCULATION — nothing is placed),
        cached per structure for MARGIN_TTL_S; null with `margin_reason` when the platform has no Kite session today, a
        contract is not listed, or a leg is shares.
LIMITS  the Paper Trading policy's fno_max_loss_pct and margin_util_pct (services/spt/policy_view) on paper equity;
        `max_loss_flag` NEAR_LIMIT above 80 % of the per-strategy limit, BREACH above it.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from services.positions import analytics
from services.strategy_plan import payoff

logger = logging.getLogger(__name__)

VERSION = "paper-fno-structures-v1"
NEAR_LIMIT = 0.8
MARGIN_TTL_S = 900.0
MOVES = (("und_down_2", "Underlying −2%", -2.0), ("und_down_1", "Underlying −1%", -1.0),
         ("und_up_1", "Underlying +1%", 1.0), ("und_up_2", "Underlying +2%", 2.0))
IV_SHIFT = 5.0
BASIS = ("Desk paper F&O structures (desk_paper_trades, kind strategy). Leg LTP by the /api/desk/pnl rule (live → Kite "
         "close → end of day); Greeks and IV from the NSE option chain (Black-76); payoff, max loss / profit and "
         "breakevens at expiry on the filled legs; every figure gross of charges; margin from Zerodha's calculator.")
SCENARIO_NOTE = "Scenarios are assumptions, not forecasts."

_margin_cache: Dict[str, Tuple[float, Optional[float], Optional[str]]] = {}


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _r2(x: Optional[float]) -> Optional[float]:
    return None if x is None or not math.isfinite(x) else round(x + 0.0, 2)


def _sign(leg: Dict[str, Any]) -> int:
    return 1 if leg.get("side") == "buy" else -1


def _qty(leg: Dict[str, Any]) -> Optional[float]:
    lots, size = _f(leg.get("lots")), _f(leg.get("lot_size"))
    return None if lots is None or size is None else lots * size


def is_filled(leg: Dict[str, Any]) -> bool:
    q = _qty(leg)
    return _f(leg.get("entry_price")) is not None and q is not None and q > 0


def payoff_legs(legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The filled legs in services/strategy_plan/payoff's form."""
    out = []
    for leg in legs:
        if not is_filled(leg):
            continue
        out.append({"kind": leg.get("kind"), "option_type": leg.get("option_type"), "strike": _f(leg.get("strike")),
                    "sign": _sign(leg), "units": float(_qty(leg) or 0), "entry_price": float(leg["entry_price"])})
    return out


def risk_figures(pl: List[Dict[str, Any]], spot: Optional[float], stop: Optional[float]) -> Dict[str, Any]:
    """Max loss / profit / breakevens on the filled legs (module docstring). Pure."""
    out: Dict[str, Any] = {"max_loss_rs": None, "max_profit_rs": None, "breakevens": [], "loss_unbounded": None,
                           "profit_unbounded": None, "risk_basis": None, "max_loss_reason": None, "loss_at_stop_rs": None,
                           "defined_risk": False}
    if not pl:
        out["max_loss_reason"] = "no leg is filled yet"
        return out
    strikes = sorted({l["strike"] for l in pl if l["kind"] == "option" and l["strike"] is not None})
    ref = spot or (strikes[len(strikes) // 2] if strikes else max(l["entry_price"] for l in pl))
    hi = max([ref * 2] + strikes)
    grid = [hi * i / 200 for i in range(201)]
    ext = payoff.extremes(pl, 0.0, hi, grid)
    be = payoff.breakevens(pl, 0.0, hi, grid)
    basis = analytics._risk_basis(pl, ext["loss_unbounded"])
    out.update(loss_unbounded=ext["loss_unbounded"], profit_unbounded=ext["profit_unbounded"], risk_basis=basis,
               breakevens=[_r2(x) for x in be["all"]],
               max_profit_rs=None if ext["profit_unbounded"] else _r2(max(ext["max_profit"], 0.0)))
    if basis == "expiry" and not ext["loss_unbounded"]:
        out["max_loss_rs"] = _r2(max(-(ext["max_loss"] or 0.0), 0.0))
        out["defined_risk"] = True
    elif ext["loss_unbounded"]:
        out["max_loss_reason"] = "the loss is unbounded as the underlying rises (an uncovered short call or future)"
    else:
        out["max_loss_reason"] = ("a long future or shares with no long put: the loss is measured at the structure's stop, "
                                  "not with the underlying at zero (owner rule, 30 Oct 2026)")
    if stop:
        at = payoff.gross(pl, float(stop))
        out["loss_at_stop_rs"] = _r2(max(-at, 0.0))
    return out


def scenarios(legs: Optional[List[Dict[str, Any]]], spot: Optional[float]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The §7 scenario rows on the priced legs (services/positions/analytics form). Pure."""
    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    level = f"{spot:,.0f}" if spot else "today's level"
    names = [(k, lbl) for k, lbl, _ in MOVES] + [("iv_up_5", f"IV +{IV_SHIFT:g} pts"), ("iv_down_5", f"IV −{IV_SHIFT:g} pts"),
                                                ("theta_1d", "1-day theta"), ("expiry_at_level", f"Expiry at {level}")]
    if not legs or not spot:
        notes.append("The structure could not be priced on the option chain, so its scenarios are not worked out.")
        return [{"name": k, "label": lbl, "pnl_rs": None} for k, lbl in names], notes
    now_v = analytics.today_pnl(legs, spot, spot)
    for key, label, move in MOVES:
        v = analytics.today_pnl(legs, spot * (1 + move / 100.0), spot)
        rows.append({"name": key, "label": label, "pnl_rs": _r2(v - now_v) if v is not None and now_v is not None else None,
                     "assumption": f"the underlying moves {move:+g}% now; every option keeps its own implied volatility"})
    for key, label, shift in (("iv_up_5", f"IV +{IV_SHIFT:g} pts", IV_SHIFT), ("iv_down_5", f"IV −{IV_SHIFT:g} pts", -IV_SHIFT)):
        v = analytics.today_pnl(legs, spot, spot, iv_shift=shift)
        rows.append({"name": key, "label": label, "pnl_rs": _r2(v - now_v) if v is not None and now_v is not None else None,
                     "assumption": f"every option's implied volatility {shift:+g} points; the underlying unchanged"})
    v = analytics.today_pnl(legs, spot, spot, days_forward=1)
    rows.append({"name": "theta_1d", "label": "1-day theta", "pnl_rs": _r2(v - now_v) if v is not None and now_v is not None else None,
                 "assumption": "one calendar day passes; the underlying and the implied volatilities unchanged"})
    exp_v = analytics.expiry_pnl(legs, spot)
    rows.append({"name": "expiry_at_level", "label": f"Expiry at {level}",
                 "pnl_rs": _r2(exp_v - now_v) if now_v is not None else None,
                 "assumption": "held to expiry with the underlying at today's level; options at intrinsic value"})
    if now_v is None:
        notes.append("An option leg has no implied volatility (it did not trade on the chain's day), so the repriced "
                      "scenarios are null rather than a guess.")
    return rows, notes


def greeks_of(legs: Optional[List[Dict[str, Any]]]) -> Dict[str, Optional[float]]:
    g = analytics.greeks(legs) if legs else None
    if g is None:
        return {"delta": None, "gamma": None, "theta_rs_day": None, "vega_rs_pt": None}
    return {"delta": g["delta"], "gamma": g["gamma"], "theta_rs_day": g["theta"], "vega_rs_pt": g["vega"]}


def structure(pub: Dict[str, Any], *, group: Optional[Dict[str, Any]], leg_ltp: Dict[str, Optional[float]],
              margin: Tuple[Optional[float], Optional[str]], limit_rs: Optional[float], today: date) -> Dict[str, Any]:
    """One structure's §7 entry. `group` is services/positions/service.paper_groups' group for it (its `_legs` / `_spot`
    are the priced legs), `leg_ltp` {position_key: ltp} from paper_pnl.prices. Pure."""
    from services.paper_pnl.book import leg_instrument
    tid = str(pub["id"])
    und = str(pub.get("underlying") or pub.get("symbol") or "").upper()
    legs_doc = list(pub.get("legs") or [])
    notes: List[str] = []
    legs_out: List[Dict[str, Any]] = []
    pnls: List[Optional[float]] = []
    for leg in legs_doc:
        key = f"{tid}:{leg.get('index')}"
        filled = is_filled(leg)
        qty = _qty(leg)
        ltp = _f(leg_ltp.get(key))
        entry = _f(leg.get("entry_price"))
        pnl = _r2(_sign(leg) * (ltp - entry) * qty) if filled and ltp is not None and entry is not None and qty else None
        pnls.append(pnl)
        legs_out.append({"side": "BUY" if leg.get("side") == "buy" else "SELL", "contract": leg_instrument(und, leg),
                         "kind": leg.get("kind"), "entry": entry, "ltp": ltp, "filled_qty": int(qty or 0) if filled else 0,
                         "qty": int(qty) if qty is not None else None, "pnl_rs": pnl, "pending": not filled,
                         "expiry": leg.get("expiry"), "strike": _f(leg.get("strike")), "option_type": leg.get("option_type")})
    pending = any(l["pending"] for l in legs_out)
    if any(l["ltp"] is None and not l["pending"] for l in legs_out):
        notes.append("A filled leg has no price now, so the structure's P&L is null.")
    # The priced legs (one per leg, in order) of the FILLED legs only: a pending leg is not held, so it adds no Greek.
    all_priced = (group or {}).get("_legs")
    priced = [p for p, d in zip(all_priced, legs_doc) if is_filled(d)] if all_priced else None
    spot = _f((group or {}).get("_spot")) or _f(((group or {}).get("price") or {}).get("spot"))
    pl = payoff_legs(legs_doc)
    risk = risk_figures(pl, spot, _f(pub.get("stop_underlying")))
    hedged = bool(risk["defined_risk"]) and bool(pl)
    if pending:
        # Only what is true is said: nothing in the desk's paper ledger blocks new orders on a partial structure.
        notes.append("Partly filled: a leg is pending, so the filled legs carry unhedged risk until it fills." if not hedged
                     else "Partly filled: a leg is pending.")
    sc, sc_notes = scenarios(priced, spot)
    notes += sc_notes
    iv10 = None
    if priced and spot:
        now_v, up_v = analytics.today_pnl(priced, spot, spot), analytics.today_pnl(priced, spot, spot, iv_shift=10.0)
        iv10 = _r2(up_v - now_v) if now_v is not None and up_v is not None else None
    for w in (group or {}).get("warnings") or []:
        if w.get("code") == "price_unavailable" and w.get("text"):
            notes.append(w["text"])
    expiries = sorted({str(l.get("expiry"))[:10] for l in legs_doc if l.get("expiry")})
    expiry = expiries[0] if expiries else None
    dte = (date.fromisoformat(expiry) - today).days if expiry else None
    lots = [_f(l.get("lots")) for l in legs_doc if l.get("kind") != "cash"]
    lots = [x for x in lots if x is not None]
    sizes = [_f(l.get("lot_size")) for l in legs_doc if l.get("kind") != "cash" and _f(l.get("lot_size"))]
    max_loss = risk["max_loss_rs"]
    used = None if max_loss is None or not limit_rs else round(max_loss / limit_rs * 100.0, 2)
    flag = None if used is None else ("BREACH" if used > 100.0 + 1e-9 else "NEAR_LIMIT" if used > NEAR_LIMIT * 100 else None)
    margin_rs, margin_reason = margin
    filled_pnls = [p for p, l in zip(pnls, legs_out) if not l["pending"]]
    return {
        "id": tid, "name": pub.get("family_name") or pub.get("summary_text") or pub.get("family"), "family": pub.get("family"),
        "summary": pub.get("summary_text"), "underlying": und, "underlying_ltp": _r2(spot),
        "underlying_source": ((group or {}).get("price") or {}).get("source"),
        "expiry": expiry, "days_to_expiry": dte, "lots": int(max(lots)) if lots else None,
        "lot_size": int(sizes[0]) if sizes else None, "status": "partial" if pending else "filled", "hedged": hedged,
        "max_loss_rs": max_loss, "max_loss_reason": risk["max_loss_reason"], "loss_at_stop_rs": risk["loss_at_stop_rs"],
        "max_profit_rs": risk["max_profit_rs"], "profit_unbounded": risk["profit_unbounded"],
        "breakevens": risk["breakevens"], "net": greeks_of(priced), "margin_rs": margin_rs, "margin_reason": margin_reason,
        "pnl_rs": _r2(sum(filled_pnls)) if filled_pnls and all(p is not None for p in filled_pnls) else None,
        "pnl_basis": "gross of charges: Σ side × (LTP − entry) × quantity over the filled legs",
        "legs": legs_out, "scenarios": sc, "max_loss_limit_rs": _r2(limit_rs), "max_loss_used_pct": used,
        "max_loss_flag": flag, "opened_at": pub.get("opened_at"), "notes": notes,
        "stress": {"iv_up_10_rs": iv10, "basis": "the change if every option's IV rises 10 points (the stress test's iv_up)"},
    }


def _sum(vals: List[Optional[float]]) -> Optional[float]:
    return None if not vals or any(v is None for v in vals) else _r2(sum(vals))


def totals(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    net = {k: _sum([r["net"][k] for r in rows]) if rows else 0.0
           for k in ("delta", "gamma", "theta_rs_day", "vega_rs_pt")}
    if rows and net["gamma"] is not None:
        net["gamma"] = round(sum(r["net"]["gamma"] for r in rows), 6)
    return {"count": len(rows), "margin_rs": _sum([r["margin_rs"] for r in rows]) if rows else 0.0,
            "max_loss_rs": _sum([r["max_loss_rs"] for r in rows]) if rows else 0.0,
            "pnl_rs": _sum([r["pnl_rs"] for r in rows]) if rows else 0.0, "net": net,
            "scenarios": [{"name": s["name"], "label": s["label"],
                           "pnl_rs": _sum([next((x["pnl_rs"] for x in r["scenarios"] if x["name"] == s["name"]), None)
                                           for r in rows])} for s in (rows[0]["scenarios"] if rows else [])],
            "partial": sum(1 for r in rows if r["status"] == "partial"),
            "unhedged": sum(1 for r in rows if not r["hedged"])}


def body(rows: List[Dict[str, Any]], *, equity: Optional[float], limits: Dict[str, Any], notes: List[str],
         as_of: str) -> Dict[str, Any]:
    t = totals(rows)
    margin_pct = limits.get("margin_util_pct")
    used = None if t["margin_rs"] is None or not equity else round(float(t["margin_rs"]) / equity * 100.0, 4)
    return {"as_of": as_of, "structures": rows, "totals": {**t, "margin_util_used_pct": used},
            "limits": {"fno_max_loss_pct": limits.get("fno_max_loss_pct"), "margin_util_pct": margin_pct,
                       "fno_max_loss_rs": _r2(equity * float(limits["fno_max_loss_pct"]) / 100.0)
                       if equity and limits.get("fno_max_loss_pct") is not None else None,
                       "margin_limit_rs": _r2(equity * float(margin_pct) / 100.0) if equity and margin_pct is not None else None,
                       "equity_rs": equity},
            "basis": BASIS, "scenario_note": SCENARIO_NOTE, "notes": notes, "version": VERSION}


# ── reads ────────────────────────────────────────────────────────────────────
def margin_legs(pub: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """POST /api/fno/margin's legs for this structure, or None when a leg cannot be priced by the calculator."""
    out = []
    for leg in pub.get("legs") or []:
        if leg.get("kind") == "cash" or not is_filled(leg) or not leg.get("expiry"):
            return None
        out.append({"side": leg.get("side"), "option_type": "future" if leg.get("kind") == "future" else leg.get("option_type"),
                    "expiry": str(leg["expiry"])[:10], "strike": _f(leg.get("strike")), "lots": int(_f(leg.get("lots")) or 0)})
    return out or None


async def zerodha_margin(db, underlying: str, legs: List[Dict[str, Any]], key: str) -> Tuple[Optional[float], Optional[str]]:
    """(required margin, None) or (None, why). Zerodha's calculator (a calculation; nothing is placed), cached."""
    hit = _margin_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < MARGIN_TTL_S:
        return hit[1], hit[2]
    from services import fno_margin
    from services.kite_live_feed import platform_token
    try:
        await platform_token.refresh_cache(db)
    except Exception as e:  # noqa: BLE001 — the calculator answers NoSession below if the token is stale
        logger.warning("fno structures: the platform token could not be reloaded (%s)", type(e).__name__)
    value: Optional[float] = None
    why: Optional[str] = None
    try:
        calc = fno_margin.default_calculator()
        rows = await asyncio.to_thread(fno_margin.instruments_today, calc)
        params, missing = fno_margin.map_legs(rows, legs, underlying)
        if missing:
            why = f"no listed contract for {', '.join(missing)}"
        else:
            raw = await asyncio.to_thread(calc.basket_margins, params)
            value = fno_margin.shape(raw if isinstance(raw, dict) else {}, date.today().isoformat())["required_margin"]
            why = None if value is not None else "the calculator returned no margin figure"
    except fno_margin.NoSession:
        why = "no Kite session for the platform today, so Zerodha's margin calculator cannot be asked"
    except Exception as e:  # noqa: BLE001 — never a guess: null with the reason
        name = type(e).__name__
        why = "no Kite session for the platform today" if name in ("TokenException", "PermissionException") \
            else f"the margin calculator failed ({name})"
    _margin_cache[key] = (time.monotonic(), _r2(value), why)
    return _r2(value), why


MarginFn = Callable[[Any, str, List[Dict[str, Any]], str], Awaitable[Tuple[Optional[float], Optional[str]]]]


async def read(request: Any, db, user_id: str, *, now: datetime, equity: Optional[float], limits: Dict[str, Any],
               margin_fn: Optional[MarginFn] = None) -> Dict[str, Any]:
    from services.paper_pnl import book as book_mod
    from services.paper_pnl import prices
    from services.positions import service as positions_service

    as_of = now.astimezone(timezone.utc).isoformat()
    notes: List[str] = []
    book = await book_mod.read_book(db, user_id)
    items = [i for i in book.open if i.kind == "strategy"]
    if book.marks_error:
        notes.append(f"End-of-day marks: {book.marks_error}")
    if not items:
        notes.append("No open desk paper F&O structure.")
        return body([], equity=equity, limits=limits, notes=notes, as_of=as_of)
    quotes, market = await prices.resolve([leg for i in items for leg in i.legs], now=now)
    notes += list(market.get("notes") or [])
    leg_ltp = {k: q.ltp for k, q in quotes.items()}
    pubs = [i.public for i in items]
    unders = sorted({str(p.get("underlying") or p.get("symbol") or "").upper() for p in pubs})
    try:
        und_quotes = await positions_service.underlying_quotes(unders)
    except Exception as e:  # noqa: BLE001 — the chain day's spot is used instead, said in the group's price source
        logger.warning("fno structures: underlying quotes unreadable (%s)", type(e).__name__)
        und_quotes = {"quotes": {}}
    groups: List[Optional[Dict[str, Any]]] = []
    for pub in pubs:
        try:
            g = (await positions_service.paper_groups(request, [pub], und_quotes))[0]
        except Exception as e:  # noqa: BLE001 — one structure's pricing failure never hides the others
            logger.warning("fno structures: pricing of %s failed (%s)", pub.get("id"), type(e).__name__)
            g = {"warnings": [{"code": "price_unavailable", "text": f"The option chain could not be read ({type(e).__name__})."}]}
        groups.append(g)
    limit_rs = equity * float(limits["fno_max_loss_pct"]) / 100.0 if equity and limits.get("fno_max_loss_pct") is not None else None
    if limit_rs is None:
        notes.append("Paper equity is unknown, so the per-strategy limit cannot be shown in rupees.")
    fn = margin_fn or zerodha_margin
    today = now.astimezone(prices.cfg.IST).date()
    rows = []
    for pub, g in zip(pubs, groups):
        legs = margin_legs(pub)
        if legs is None:
            margin = (None, "a leg is shares, not filled or has no expiry: the F&O margin calculator cannot price it")
        else:
            und = str(pub.get("underlying") or pub.get("symbol") or "").upper()
            margin = await fn(db, und, legs, f"{pub['id']}|{today.isoformat()}")
        rows.append(structure(pub, group=g, leg_ltp=leg_ltp, margin=margin, limit_rs=limit_rs, today=today))
    return body(rows, equity=equity, limits=limits, notes=notes, as_of=as_of)
