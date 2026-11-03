"""The broker half of the Copilot's daily review (owner, 31 Oct 2026: "This should also consider broker trades").

`builders.daily_review` keeps its paper review exactly as it was and adds, when the user has broker trades on record, a section
labelled BROKER, never merged into the paper figures:

    notices        one per account that cannot supply trades (session ended, no trade-book reader, a failed read), each with the
                   reason; a broker that cannot be read is said so, never counted as "no trades"
    broker_record  kpis: round trips closed, wins and losses, realised P&L (the broker's own fill prices, gross; charges are not
                   estimated), legs still unmatched
    broker_trips   ranked: one row per round trip: contract, account, direction, quantity (units), entry, exit, P&L, plan
    broker_rules   list: did the trade follow its entry, stop and exit rules, ONLY where the user's own stop (position_levels) or a
                   plan they recorded (trade_plans) existed at the time; otherwise "no plan recorded", never a guess
    broker_open    list: legs with no other side in the trade books on record, shown as open

Matching and the kept trade books: services/positions/trade_book.py. Read-only; ideas to review, not advice.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.positions import trade_book as tb

from .payload import Sources, block, day_text, iso_day, notice, num, price, r2, rupees, short_day, tone_of

IST = timezone(timedelta(hours=5, minutes=30))
SRC_TRADES = "Your broker trade book (kept each day)"
TRIP_ROWS = 15
RULE_ITEMS = 12
SIDE = {"long": "Long", "short": "Short"}
PLAN_DIRECTION = {"long": "bullish", "short": "bearish"}


def _dt(iso: Any) -> Optional[datetime]:
    d = tb._dt(iso)
    if d is None:
        return None
    if isinstance(iso, str) and len(iso) > 10 and d.time() == datetime.min.time() and d.tzinfo == IST:
        return d + timedelta(hours=23, minutes=59, seconds=59)        # a broker that sends a date only: treat it as the end of that day
    return d


def _pct(a: float, b: float) -> float:
    return abs(a - b) / b * 100 if b else 0.0


def adherence(trip: Dict[str, Any], levels: Optional[Dict[str, Any]], plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{cell, facts: [{text, tone}], assessed}: the trip against the user's own stop (set before it closed) and the plan they
    recorded (before it opened). Nothing is assessed without one of them. Price levels apply to shares and futures; an option's
    premium is not compared with a level on its underlying (only the direction against the plan is)."""
    facts: List[Dict[str, Any]] = []
    long = trip["direction"] == "long"
    name = trip["label"]
    exit_dt, entry_dt = _dt(trip.get("exit_at") or trip["exit_day"]), _dt(trip.get("entry_at") or trip["entry_day"])
    lv_dt = _dt((levels or {}).get("updated_at"))
    lv = levels if levels and lv_dt and exit_dt and lv_dt <= exit_dt else None
    p_dt = _dt((plan or {}).get("created_at"))
    pl = plan if plan and p_dt and entry_dt and p_dt <= entry_dt else None
    cell = "No plan recorded"
    if levels and not lv:
        facts.append({"text": f"{name}: your stop was set on {day_text(iso_day(levels.get('updated_at')))}, after this trade closed, so it is not used.", "tone": None})
    if plan and not pl:
        facts.append({"text": f"{name}: the plan on record is from {day_text(iso_day(plan.get('created_at')))}, after this trade opened, so it is not used.", "tone": None})
    levelled = trip["kind"] in ("cash", "future")
    ex, en, q = trip["exit_price"], trip["entry_price"], trip["quantity"]
    stop = (lv or {}).get("stop") if levelled else None
    src = "your stop"
    if stop is None and pl and levelled and pl.get("stop"):
        stop, src = pl["stop"], "the plan's stop"
    target = ((lv or {}).get("target") if lv else None) or (pl or {}).get("target") if levelled else None
    if levelled and stop:
        beyond = (stop - ex) if long else (ex - stop)
        if beyond > 0:
            facts.append({"text": f"{name}: exited at {price(ex)}, {_pct(ex, stop):.2f}% beyond {src} ({price(stop)}): the stop was not honoured.", "tone": "warn"})
            cell = "Stop not honoured"
        elif trip["pnl_rs"] < 0:
            facts.append({"text": f"{name}: closed at a loss, on the safe side of {src} ({price(stop)}): you exited before it was hit.", "tone": None})
            cell = "Exited before the stop"
        else:
            facts.append({"text": f"{name}: exited at {price(ex)}, on the safe side of {src} ({price(stop)}).", "tone": None})
            cell = "Within your stop"
    if levelled and target and ((ex >= target) if long else (ex <= target)):
        facts.append({"text": f"{name}: exited at {price(ex)}, at or past the target ({price(target)}).", "tone": "up"})
        cell = "Target reached" if cell in ("No plan recorded", "Within your stop") else cell
    if pl:
        want = PLAN_DIRECTION[trip["direction"]]
        if trip.get("instrument") in ("PE",):
            want = "bearish" if long else "bullish"                       # a long put is a bearish view
        elif trip.get("instrument") == "CE":
            want = "bullish" if long else "bearish"
        if pl.get("direction") and pl["direction"] not in (want, "neutral"):
            facts.append({"text": f"{name}: opened {trip['direction']} against a {pl['direction']} plan recorded {day_text(iso_day(pl.get('created_at')))}.", "tone": "warn"})
            cell = cell if cell != "No plan recorded" else "Against the plan"
        elif pl.get("direction"):
            facts.append({"text": f"{name}: opened {trip['direction']}, the same way as the {pl['direction']} plan recorded {day_text(iso_day(pl.get('created_at')))}.", "tone": None})
        if levelled and pl.get("entry"):
            off = (en - pl["entry"]) / pl["entry"] * 100
            facts.append({"text": f"{name}: entered at {price(en)}, {abs(off):.2f}% {'above' if off > 0 else 'below'} the plan's entry ({price(pl['entry'])}).", "tone": None})
        if cell == "No plan recorded":
            cell = "Plan recorded"
    return {"cell": cell, "facts": facts, "assessed": bool(lv or pl)}


def _trip_row(t: Dict[str, Any], a: Dict[str, Any]) -> Dict[str, Any]:
    pnl = num(t["pnl_rs"])
    qty = int(t["quantity"]) if float(t["quantity"]).is_integer() else t["quantity"]
    return {"symbol": t.get("underlying"), "tone": tone_of(pnl), "badge": "Broker",
            "tips": {"pnl": "The broker's own fill prices: quantity × (exit − entry), gross. Charges are not estimated."
                            + (f" Fees from the broker: {price(t['fees_rs'])}." if t.get("fees_rs") is not None else ""),
                     "plan": " ".join(f["text"] for f in a["facts"]) or "No stop of yours and no plan was on record for this contract."},
            "cells": {"symbol": t["label"], "account": t["broker_display"], "side": SIDE[t["direction"]], "qty": qty,
                      "entry": r2(t["entry_price"]), "exit": r2(t["exit_price"]), "pnl": r2(pnl), "plan": a["cell"]}}


TRIP_COLUMNS = [{"key": "symbol", "label": "Contract", "align": "left", "format": "text"},
                {"key": "account", "label": "Account", "align": "left", "format": "text"},
                {"key": "side", "label": "Side", "align": "left", "format": "text"},
                {"key": "qty", "label": "Qty", "align": "right", "format": "int"},
                {"key": "entry", "label": "Entry", "align": "right", "format": "price"},
                {"key": "exit", "label": "Exit", "align": "right", "format": "price"},
                {"key": "pnl", "label": "P&L (gross)", "align": "right", "format": "price"},
                {"key": "plan", "label": "Rules", "align": "left", "format": "text"}]


def matched(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The round trips and open lots of every account's kept days (empty when there is no data)."""
    if not isinstance(data, dict) or not data.get("stored"):
        return {"trips": [], "open": [], "days": {}}
    return tb.match(data["stored"])


def active_days(m: Dict[str, Any]) -> List[str]:
    return sorted({t["exit_day"] for t in m["trips"]})


def state_notices(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(data, dict) or data.get("hub") == "off":
        return out
    for i, a in enumerate(data.get("accounts") or []):
        name = a.get("broker_display") or a.get("broker") or "Your broker"
        nid = f"broker-{a.get('broker') or 'broker'}-{i}"
        kept = (f" Showing the {a['days']} day{'s' if a['days'] != 1 else ''} of its trade book kept so far (latest {day_text(a['last_day'])})."
                if a.get("days") else " No day of its trade book has been kept.")
        if a["state"] == tb.ENDED:
            n = notice(f"Your {name} session has ended, so today's trades could not be read. Sign in to {name} again to include them.{kept}", "warn", f"{nid}-ended")
            n["actions"] = [{"kind": "connect_broker", "label": f"Sign in to {name} again"}]
            out.append(n)
        elif a["state"] == tb.UNSUPPORTED:
            out.append(notice((a.get("error") or {}).get("message") or f"{name} has no trade-book reader yet, so its trades are not in this review.", "info", f"{nid}-unsupported"))
        elif a["state"] == tb.FAILED:
            out.append(notice(f"{(a.get('error') or {}).get('message') or name + ' could not be read just now.'}{kept}", "warn", f"{nid}-failed"))
        elif a["state"] == tb.UNREADABLE:
            out.append(notice(f"{name}: {(a.get('error') or {}).get('message') or 'trades cannot be read for this account.'}", "info", f"{nid}-unreadable"))
    return out


def section(data: Optional[Dict[str, Any]], m: Dict[str, Any], start: date, end: date, levels: Dict[str, Dict[str, Any]],
            plans: Dict[str, Dict[str, Any]], src: Sources, period_text: str, mode: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """(blocks, a sentence for the headline or None) for the review period [start, end]. Adds the broker trade book to `src`."""
    blocks = state_notices(data)
    kept = [d["day"] for d in (data or {}).get("stored") or []]
    if kept:
        src.add(SRC_TRADES, max(kept), note=f"{len(set(kept))} day(s) kept")
    s_iso, e_iso = start.isoformat(), end.isoformat()
    trips = [t for t in m["trips"] if s_iso <= t["exit_day"] <= e_iso]
    open_lots = tb.match(data["stored"], through_day=e_iso)["open"] if data and data.get("stored") else []
    if not trips and not open_lots:
        if kept:
            blocks.append(notice(f"No broker round trip closed {'on' if mode == 'day' else 'in'} {period_text}. "
                                 f"Broker trade book on record: {len(set(kept))} day{'s' if len(set(kept)) != 1 else ''} "
                                 f"({short_day(min(kept))} – {day_text(max(kept))}).", "info", "broker-none"))
        return blocks, None
    assessed = [(t, adherence(t, levels.get(t["underlying"]) if t.get("underlying") else None, plans.get(t["underlying"]) if t.get("underlying") else None))
                for t in trips]
    pnls = [t["pnl_rs"] for t in trips]
    wins, losses = sum(1 for p in pnls if p > 0), sum(1 for p in pnls if p < 0)
    total = round(sum(pnls), 2) if pnls else None
    fees_known = trips and all(t.get("fees_rs") is not None for t in trips)
    kp = [{"label": "Round trips closed", "value": str(len(trips)), "sub": ", ".join(sorted({t["broker_display"] for t in trips})) or None},
          {"label": "Wins / losses", "value": f"{wins} / {losses}", "sub": "by the broker's fill prices"},
          {"label": "Realised P&L", "value": rupees(total), "sub": "gross: the broker's own fill prices, charges not included"
           + (f"; broker fees {price(round(sum(t['fees_rs'] for t in trips), 2))}" if fees_known else ""), **({"tone": tone_of(total)} if total else {})},
          {"label": "Unmatched legs", "value": str(len(open_lots)), "sub": "shown as open: no other side on record" if open_lots else None}]
    blocks.append(block("kpis", "broker_record", f"Broker trades · {period_text}", "Labelled Broker: these are your real trades, never mixed "
                        "with the paper figures above.", items=kp))
    if assessed:
        blocks.append(block("ranked", "broker_trips", f"Broker round trips · {len(trips)} closed",
                            "Partial fills of one order are one round trip. Quantity is in units, as the broker sends it; an F&O lot is its lot size in units. "
                            "A round trip is a buy matched with a sell of the same contract, first in, first out.",
                            columns=TRIP_COLUMNS, rows=[_trip_row(t, a) for t, a in assessed[:TRIP_ROWS]]))
        items = [{"text": f["text"], "tone": f["tone"]} for _, a in assessed for f in a["facts"]][:RULE_ITEMS]
        n_ok = sum(1 for _, a in assessed if a["assessed"])
        items.append({"text": f"{n_ok} of {len(assessed)} round trip{'s' if len(assessed) != 1 else ''} had a stop of yours or a recorded plan in force; "
                              + ("the others have no plan recorded, so whether they followed a rule is not assessed." if n_ok < len(assessed)
                                 else "each is checked against it above."), "tone": None})
        blocks.append(block("list", "broker_rules", "Did you follow your entry, stop-loss and exit rules?",
                            "Only where your own stop (set before the trade closed) or a plan you recorded (before it opened) exists.", items=items))
    if open_lots:
        blocks.append(block("list", "broker_open", "Broker legs still open (unmatched)", "Each has no other side in the trade books kept; it is not assumed to be a short.",
                            items=[{"text": f"{o['label']} ({o['broker_display']}): {o['side']} {o['quantity']:g} at {price(o['avg_price'])} since {short_day(o['since_day'])}.",
                                    "tone": None} for o in open_lots[:RULE_ITEMS]]))
    sentence = (f"Broker: {len(trips)} round trip{'s' if len(trips) != 1 else ''} closed ({wins} win{'s' if wins != 1 else ''}, "
                f"{losses} loss{'es' if losses != 1 else ''}), realised {rupees(total)} gross" if trips else
                f"Broker: no round trip closed, {len(open_lots)} unmatched leg{'s' if len(open_lots) != 1 else ''}")
    return blocks, sentence + "."
