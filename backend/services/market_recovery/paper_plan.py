"""Market Recovery › the paper-trade plan for the top 10 candidates (docs/market_recovery/DESIGN.md §10 A; owner, 4 Nov 2026).

For each of the page's leading-sector candidates: the shares plan (live entry, the plan's Stop loss, Target 1) and every option
strategy that passed its checks (strategies.py), re-priced at LIVE Kite quotes, each sized by the user's own risk gate as a dry
run (the same calls POST /api/desk/paper-trades/check makes: nothing written), then the best one by the owner's rule — the
highest reward : risk after costs, ties to the lower maximum loss. The answer carries, per stock, the exact body to POST to
/api/desk/paper-trades and its Idempotency-Key, so opening goes through the desk's own engine (risk gate, idempotency,
duplicates, funds) and nothing here writes.

Live only (owner's choice): a candidate without a live price of today is not eligible and says why; before the open, or without
the daily Kite login, the plan still shows but nothing can be opened.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from fastapi import Request

from services.kite_live_feed.config import IST
from services.strategy_plan import payoff as po

from . import service as page_service
from . import strategies as strat_svc
from .engine import fnum

logger = logging.getLogger(__name__)

TOP_N = 10
MAX_QUANTITY = 1_000_000          # services/desk_trading.MAX_QUANTITY: a larger request is refused as invalid_quantity
RULE = ("Highest reward : risk after costs among the shares plan and the option strategies that passed their checks, at live "
        "prices, sized by your risk gate (0.5% risk per trade of paper equity and your other limits); ties go to the lower "
        "maximum loss.")
FAMILY = {"protective_put": "protective_put", "bull_call_spread": "bull_call_spread", "collar": "collar",
          "bull_put_spread": "bull_put_spread", "put_ratio_backspread": "custom"}
NOTES = [
    "Prices are live Kite quotes when the market is open; a candidate without a live price of today is not opened.",
    "Each trade is opened through the desk's paper engine with your risk gate; refusals are shown, never worked around.",
    "Live closes: a live price at the Stop loss or Target 1 closes the trade during the day (owner's choice, 4 Nov).",
]


def _r(x: Optional[float], dp: int = 2) -> Optional[float]:
    return None if x is None else round(float(x) + 0.0, dp)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── candidates (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────

def shares_candidate(sym: str, ltp: float, plan: Dict[str, Any], *, as_of: str, at_iso: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    stop, t1 = fnum(plan.get("stop_loss")), fnum(plan.get("target_1"))
    if stop is None or t1 is None:
        return None, "The plan has no Stop loss or Target 1."
    if ltp <= stop:
        return None, f"The live price {ltp:,.2f} is at or below the Stop loss {stop:,.2f}."
    if ltp >= t1:
        return None, f"The live price {ltp:,.2f} is already at or above Target 1 {t1:,.2f}."
    gain, loss = t1 - ltp, ltp - stop                     # per share, before costs: costs are added at the approved size
    return {"key": "shares", "label": "Shares", "reward_risk_net": _r(gain / loss) if loss > 0 else None,
            "per_unit_loss": loss, "per_unit_gain": gain,
            "body": {"symbol": sym, "quantity": 1, "entry_price": round(ltp, 2), "stop_price": round(stop, 2),
                     "target_price": round(t1, 2), "entry_rule": "at_once",
                     "source": {"kind": "market_recovery", "bucket": "shares", "signal_date": as_of},
                     "price_source": {"kind": "kite_live", "at": at_iso},
                     "rationale": f"Market Recovery plan of {as_of}: Entry at the live price, Stop loss {stop:,.2f}, "
                                  f"Target 1 {t1:,.2f} (Target 2 {fnum(plan.get('target_2')) or 0:,.2f} shown)."}}, None


def shares_costs(qty: int, entry: float, exit_price: float) -> float:
    """Round-trip costs of `qty` shares on the desk cost card (equity delivery), entry to an exit at `exit_price`."""
    leg = {"index": 0, "kind": "cash", "sign": 1, "units": int(qty), "entry_price": entry, "strike": None}
    model, _ = po.cost_params({})
    return float(po.costs_block([leg], exit_price, model, "desk cost card").get("round_trip") or 0.0)


def live_legs(strategy: Dict[str, Any], quotes: Dict[str, Any], ltp: float, lot: int, expiry: str
              ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """The strategy's legs priced live: option legs at their live quote (by leg position), shares at the live price."""
    out, opt_i = [], 0
    for i, leg in enumerate(strategy.get("legs") or []):
        if leg["instrument"] == "Shares":
            out.append({"index": i, "kind": "cash", "sign": 1, "units": int(leg["units"]), "entry_price": ltp, "strike": None,
                        "_lots": int(leg["units"]), "_side": "buy", "_type": None})
            continue
        q = quotes.get(str(opt_i)) or quotes.get(opt_i)
        opt_i += 1
        price = fnum((q or {}).get("last_price"))
        if price is None or price <= 0:
            return None, f"No live quote for the {leg['strike']:,.0f} {leg['instrument'].lower()}."
        out.append({"index": i, "kind": "option", "option_type": "call" if leg["instrument"] == "Call" else "put",
                    "sign": 1 if leg["action"] == "Buy" else -1, "units": int(leg["lots"]) * lot, "strike": float(leg["strike"]),
                    "entry_price": price, "_lots": int(leg["lots"]), "_side": "buy" if leg["action"] == "Buy" else "sell",
                    "_type": "call" if leg["instrument"] == "Call" else "put"})
    return out, None


def option_legs_for_quote(strategy: Dict[str, Any], symbol: str, expiry: str) -> List[Dict[str, Any]]:
    return [{"underlying": symbol, "expiry": expiry, "strike": l["strike"], "kind": "option",
             "option_type": "CE" if l["instrument"] == "Call" else "PE"}
            for l in strategy.get("legs") or [] if l["instrument"] != "Shares"]


def structure_candidate(sym: str, strategy: Dict[str, Any], legs: List[Dict[str, Any]], plan: Dict[str, Any], ltp: float,
                        lot: int, expiry: str, *, as_of: str, at_iso: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    key = strategy["key"]
    live_plan = {"close": ltp, "entry_low": plan.get("entry_low"), "stop_loss": plan.get("stop_loss"),
                 "target_1": plan.get("target_1"), "target_2": plan.get("target_2")}
    model, _ = po.cost_params({})
    pay = [{k: v for k, v in l.items() if not k.startswith("_")} for l in legs]
    fig = strat_svc.figures(key, pay, live_plan, model, lot)
    loss = fnum(fig.get("max_loss_with_costs"))
    if loss is None or loss >= 0:
        return None, "Its maximum loss could not be measured."
    t1 = fnum(plan.get("target_1"))
    gain = fnum(fig["max_profit"]) if not fig["profit_unbounded"] else (po.gross(pay, t1) if t1 else None)
    if key == "put_ratio_backspread":
        gain = None                                        # judged by its loss zone, never by a ratio (strategies.py)
    costs = fnum(fig.get("costs_round_trip")) or 0.0
    rr = None if gain is None else (gain - costs) / -loss
    hhmm = datetime.fromisoformat(at_iso).astimezone(IST).strftime("%H:%M")
    body_legs = []
    for l in legs:
        if l["kind"] == "cash":
            body_legs.append({"kind": "cash", "side": "buy", "lots": l["_lots"], "lot_size": 1, "entry_price": round(ltp, 2),
                              "price_source": f"Kite live {hhmm} IST"})
        else:
            body_legs.append({"kind": "option", "side": l["_side"], "lots": l["_lots"], "lot_size": lot,
                              "entry_price": round(l["entry_price"], 2), "expiry": expiry, "strike": l["strike"],
                              "option_type": l["_type"], "price_source": f"Kite live {hhmm} IST"})
    body = {"kind": "strategy", "underlying": sym, "direction": "bullish", "family": FAMILY[key], "reference_price": round(ltp, 2),
            "stop_underlying": fnum(plan.get("stop_loss")), "target_underlying": t1, "legs": body_legs,
            "signal": {"signal_at": at_iso, "rule_version": "recovery-plan-v1",
                       "evidence_summary": f"Market Recovery {strategy['label']} for {sym} (plan of {as_of}), legs at Kite live {hhmm} IST.",
                       "source_refs": [{"kind": "market_recovery", "ref": f"{sym}:{key}", "as_of": as_of}]}}
    return {"key": key, "label": strategy["label"], "reward_risk_net": _r(rr), "max_gain_rs": _r(gain),
            "max_loss_rs": _r(loss), "body": body}, None


def rank(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Eligible first (approved size ≥ 1 and a ratio), by reward : risk desc, then the lower maximum loss."""
    def k(c):
        ok = c.get("eligible") and c.get("reward_risk_net") is not None
        return (0 if ok else 1, -(c.get("reward_risk_net") or -math.inf), -(c.get("max_loss_rs") or -math.inf))
    return sorted(cands, key=k)


# ── the risk gate as a dry run (the /paper-trades/check calls) ──────────────────────────────────────────────────────

async def gate_check(user: Dict[str, Any], body: Dict[str, Any], cid: str) -> Dict[str, Any]:
    from routes import desk_trading as dt
    from deps import db
    from services import desk_strategy_trades as strat
    from services import desk_trading as svc
    from services import risk_gate
    from services.risk_gate import service as risk_service
    uid = user["user_id"]
    clean = {k: v for k, v in body.items() if k != "price_source"}         # the decision does not depend on it
    if clean.get("kind") == strat.KIND:
        doc = strat.new_strategy_trade(uid, clean)
        await strat.check_exchange_lots(doc)
    else:
        doc = svc.new_trade(uid, clean)
    fno_additional = await risk_gate.enabled_for(db, user)
    req = dt._entry_request(user, cid, doc, fno_additional)
    decision = risk_service.decide(req, await risk_service.gather(db, req, svc.utcnow()))
    return {"outcome": decision.get("outcome"), "approved_qty": decision.get("approved_qty"),
            "approved_lots": decision.get("approved_lots"), "estimated_risk_rs": decision.get("estimated_risk_rs"),
            "reasons": [{k: r.get(k) for k in ("code", "message")} for r in decision.get("reasons") or [] if isinstance(r, dict)],
            "budget": {k: (decision.get("budget") or {}).get(k) for k in ("equity_rs", "per_trade_budget_rs", "funding_rs")}}


# ── the plan (I/O) ────────────────────────────────────────────────────────────────────────────────────────────────────

GateFn = Callable[[Dict[str, Any], Dict[str, Any], str], Awaitable[Dict[str, Any]]]


async def build_plan(request: Request, user: Dict[str, Any], *, gate: GateFn = gate_check,
                     stock_quotes: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                     option_quotes: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                     open_trades: Optional[Callable[[str], Awaitable[List[Dict[str, Any]]]]] = None,
                     account: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None,
                     now: Callable[[], datetime] = _now) -> Dict[str, Any]:
    if stock_quotes is None or option_quotes is None:
        from . import paper_live
        stock_quotes = stock_quotes or paper_live.stock_quotes
        option_quotes = option_quotes or paper_live.option_quotes
    open_trades = open_trades or _open_market_recovery_trades
    account = account or _account
    acct = await account(user["user_id"])
    svc = page_service.get_service()
    page = await svc.get()
    as_of = str(page.get("as_of"))
    t = now()
    at_iso = t.isoformat()
    list_date = t.astimezone(IST).date().isoformat()
    cands = (page.get("candidates") or [])[:TOP_N]
    sq = await stock_quotes([c["symbol"] for c in cands])
    live = sq.get("source") == "kite_live"
    quotes = sq.get("quotes") or {}
    held = {}
    for d in await open_trades(user["user_id"]):
        sym = d.get("symbol") or d.get("underlying")
        if sym:
            held[sym] = {"id": d.get("_id"), "status": d.get("status")}
    from .service import get_data  # noqa: F401  (kept for parity with the page's data layer)
    ref_fno = await _fno_set()
    items = []
    for c in cands:
        sym = c["symbol"]
        item = {"rank": c["rank"], "symbol": sym, "name": c.get("name"), "sector": c.get("sector"), "score": c.get("score"),
                "chosen": None, "alternatives": [], "skipped_reason": None, "open_trade": held.get(sym)}
        q = quotes.get(sym) or {}
        ltp = fnum(q.get("ltp"))
        if not live or ltp is None:
            item["skipped_reason"] = ("No live price yet: " + ({"feed_not_live": "the Kite live feed is not running (the daily Kite "
                                      "login may be needed)", "no_saved_close": "the market is closed",
                                      "unreadable": "the quotes could not be read"}.get(sq.get("why") or "", "the market is not open")
                                      if not live else f"{sym} has not traded today") + ".")
            items.append(item)
            continue
        plan = c.get("plan") or {}
        options: List[Dict[str, Any]] = []
        sh, why = shares_candidate(sym, ltp, plan, as_of=as_of, at_iso=at_iso)
        if sh:
            options.append(sh)
        else:
            item["alternatives"].append({"key": "shares", "label": "Shares", "eligible": False, "why": why})
        if sym in ref_fno:
            try:
                ctx = await svc.stock_context(sym)
                strat = await strat_svc.get_service().for_stock(request, sym, ctx, True, as_of)
                expiry, lot = strat.get("expiry"), int(strat.get("lot_size") or 0)
                for s in strat.get("strategies") or []:
                    if s.get("status") != "passes":
                        item["alternatives"].append({"key": s["key"], "label": s["label"], "eligible": False,
                                                     "why": f"Failed its checks: {s.get('why') or 'not available'}"})
                        continue
                    oq = await option_quotes(option_legs_for_quote(s, sym, expiry))
                    if not oq.get("available"):
                        item["alternatives"].append({"key": s["key"], "label": s["label"], "eligible": False,
                                                     "why": f"No live option quotes: {oq.get('reason') or 'not available'}."})
                        continue
                    legs, why = live_legs(s, oq.get("quotes") or {}, ltp, lot, expiry)
                    if not legs:
                        item["alternatives"].append({"key": s["key"], "label": s["label"], "eligible": False, "why": why})
                        continue
                    sc, why = structure_candidate(sym, s, legs, plan, ltp, lot, expiry, as_of=as_of, at_iso=at_iso)
                    if sc:
                        options.append(sc)
                    else:
                        item["alternatives"].append({"key": s["key"], "label": s["label"], "eligible": False, "why": why})
            except strat_svc.ChainUnavailable as e:
                item["alternatives"].append({"key": "options", "label": "Option strategies", "eligible": False, "why": e.message})
        # size each through the risk gate (dry run)
        for o in options:
            body = dict(o["body"])
            if o["key"] == "shares":
                # Oversized on purpose — all the cash could buy, within the desk's own quantity limit — so the gate REDUCES
                # it to the largest size the user's limits allow (per-trade risk, position, sector, open risk, funds).
                cash = float(acct.get("cash_rs") or 0.0)
                body["quantity"] = max(1, min(MAX_QUANTITY, int(cash // max(ltp, 0.01))))
            try:
                g = await gate(user, body, f"mr-plan-{sym}")
            except Exception as e:  # noqa: BLE001 — a candidate the desk refuses as a body is not eligible, with the reason
                detail = getattr(e, "detail", None)
                o.update(eligible=False, why=f"The desk refused the request ({detail() if callable(detail) else type(e).__name__}).")
                continue
            o["approved"] = {"outcome": g["outcome"], "quantity": g.get("approved_qty"), "lots": g.get("approved_lots"),
                             "reasons": g.get("reasons"), "estimated_risk_rs": g.get("estimated_risk_rs")}
            size_ok = (g.get("approved_qty") or 0) >= 1 if o["key"] == "shares" else (g.get("approved_lots") or 0) >= 1
            o["eligible"] = g["outcome"] in ("allow", "reduce") and size_ok
            if not o["eligible"]:
                o["why"] = "; ".join(r.get("message") or r.get("code") or "" for r in g.get("reasons") or []) or "Refused by the risk gate."
                continue
            if o["key"] == "shares":
                qty = int(g["approved_qty"])
                o["body"]["quantity"] = qty
                costs = shares_costs(qty, float(o["body"]["entry_price"]), float(o["body"]["target_price"]))
                gain_rs, loss_rs = o["per_unit_gain"] * qty - costs, o["per_unit_loss"] * qty + costs
                o["max_loss_rs"] = _r(-loss_rs)
                o["max_gain_rs"] = _r(gain_rs)
                o["reward_risk_net"] = _r(gain_rs / loss_rs) if loss_rs > 0 else None
            elif (g.get("approved_lots") or 1) != 1:
                o["why"] = "Opened at one lot (the gate approved fewer than one lot of this size)."
        for o in options:
            o.pop("per_unit_loss", None)
            o.pop("per_unit_gain", None)
            o["prices"] = {"source": "kite_live", "as_of": sq.get("as_of")}
            o["idempotency_key"] = f"mr-{list_date}-{sym}"
        ranked = rank(options)
        if ranked and ranked[0].get("eligible") and ranked[0].get("reward_risk_net") is not None:
            item["chosen"] = ranked[0]
            item["alternatives"] = ranked[1:] + item["alternatives"]
        else:
            item["alternatives"] = ranked + item["alternatives"]
            item["skipped_reason"] = "Nothing qualifies: " + ("; ".join(f"{o['label']}: {o.get('why')}" for o in ranked if o.get("why"))
                                                              or "no candidate passed the risk gate") + "."
        items.append(item)
    return {"as_of": as_of, "list_date": list_date,
            "market": {"live": live, "source": sq.get("source"), "why": sq.get("why"), "as_of": sq.get("as_of")},
            "capital": {k: acct.get(k) for k in ("starting_capital_rs", "cash_rs", "blocked_rs", "available_rs")},
            "rule": RULE, "notes": NOTES, "items": items}


async def _fno_set() -> set:
    from services.scan_builder.data import get_data
    try:
        return set((await get_data().reference()).fno)
    except Exception:  # noqa: BLE001 — without the list, no option strategies are tried (said per stock)
        return set()


async def _open_market_recovery_trades(uid: str) -> List[Dict[str, Any]]:
    from deps import db
    from services import desk_trading as svc
    return await db[svc.TRADES].find({"user_id": uid, "status": "open",
                                      "$or": [{"source.kind": "market_recovery"},
                                              {"signal.source_refs.kind": "market_recovery"}]},
                                     {"_id": 1, "symbol": 1, "underlying": 1, "status": 1}).to_list(200)


async def _account(uid: str) -> Dict[str, Any]:
    from deps import db
    from services import paper_account
    return await paper_account.read(db, uid)
