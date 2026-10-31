"""The Copilot's "What are my open trades doing?" on the user's own BROKER book (owner, 31 Oct 2026), with the paper trades beside it.

Before this the answer read only the desk's paper trades. The owner: "why only paper positions are shown we should list the
broker live positions or latest EOD positions and review the plans and provide AI commentary. Also we need to show minimum
margin required, available and utilized for those broker positions", "ask the user to connect to the broker ... if not
connected", "show live data refreshed every 5 seconds".

What the answer is, by the user's broker configuration (services/positions/book.py):
    no broker connected      one notice with a "Connect a broker" action; the paper trades below, as before
    session ended            a notice with a "Sign in again" action; the LAST STORED read shown with its time (never as live)
    signed in                the live positions of every account (a failing account is reported alone), the account's funds,
                             Zerodha's margin calculator for the F&O legs, the user's stop/target (or the plan they recorded)

Blocks (ids; the live ones are re-sent by GET /api/positions/book/live every 5 s while the market is open):
    book         kpis       positions, unrealised P&L, margin required, available cash, used margin     (live)
    positions    ranked     one row per broker position: qty, average, price, the BROKER's P&L          (live)
    levels       ranked     one row per underlying: price, stop, target, distance, loss at the stop, margin, expiry   (live)
    accounts     ranked     one row per account: state, available cash, collateral, used margin           (live)
    commentary   list       the deterministic checks the written commentary explains                       (live)
    summary, trades         the paper trades, unchanged                                                  (end of day)

Every figure is worked out here from the book; the model only explains the commentary list (payload.facts) and computes
nothing. Wording: ideas to review, not recommendations. Read-only: no order can be placed from here.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.positions import analytics
from services.positions import book as bk

from . import fno_board as fb
from . import readers as rd
from .payload import (
    IST, Sources, assemble, block, day_text, follow, iso_day, notice, num, price, r2, rupees, tone_of, why,
)

logger = logging.getLogger(__name__)

LIVE_PATH = "/api/positions/book/live"
LIVE_INTERVAL_S = 5
LIVE_BLOCKS = ("book", "positions", "levels", "accounts", "commentary")
COMMENT_MAX = 14
MARGIN_VIEW_TTL_S = 120.0

SRC_PAPER = "Your paper trades (desk_paper_trades, marked at the last available close)"
SRC_BOOK = "Your broker positions (read from the broker)"
SRC_STORED = "Your broker positions (last stored read)"
SRC_FUNDS = "Your broker accounts' funds (read from the broker)"
SRC_MARGIN = "Margin required (Zerodha margin calculator)"
SRC_KITE = "Share prices (the platform's Kite live feed)"
READ_ONLY_TEXT = ("Nivesh reads your broker positions; it cannot place, modify or cancel an order. These are checks to review, "
                  "not recommendations.")
STATE_WORD = {bk.LIVE: "Live", bk.ENDED: "Session ended", bk.FAILED: "Read failed", bk.UNSUPPORTED: "Not supported",
              bk.UNREADABLE: "Not readable"}

_MARGINS: Dict[str, Tuple[float, Dict[str, Any], Dict[str, Any]]] = {}


# ── time ─────────────────────────────────────────────────────────────────────

def _dt(iso: Any) -> Optional[datetime]:
    if not isinstance(iso, str):
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(IST)


def stamp(iso: Any) -> str:
    """'31 Oct 2026, 17:28 IST'."""
    d = _dt(iso)
    return f"{d.day} {d.strftime('%b %Y, %H:%M')} IST" if d else "an unknown time"


def hm(iso: Any) -> str:
    d = _dt(iso)
    return d.strftime("%H:%M:%S") if d else "?"


def short_stamp(iso: Any) -> str:
    d = _dt(iso)
    return f"{d.day} {d.strftime('%b %H:%M')}" if d else "?"


def _day_of(iso: Any) -> Optional[str]:
    d = _dt(iso)
    return d.date().isoformat() if d else None


# ── groups → table rows ──────────────────────────────────────────────────────

def _signed_qty(q: Any) -> Optional[float]:
    f = num(q)
    return None if f is None else (int(f) if float(f).is_integer() else f)


def margin_request(g: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The body for Zerodha's margin calculator: the group's listed F&O legs in whole lots (shares are paid in full and are
    not in it). None when the group has no F&O leg, or a leg is not a whole number of lots."""
    legs = []
    for l in g.get("legs") or []:
        inst = l.get("instrument")
        if inst not in ("FUT", "CE", "PE"):
            continue
        lot, q = l.get("lot_size"), num(l.get("quantity"))
        if not lot or not q or not l.get("expiry") or q % lot:
            return None
        legs.append({"side": "buy" if q > 0 else "sell", "option_type": {"CE": "call", "PE": "put", "FUT": "future"}[inst],
                     "expiry": l["expiry"], "strike": l.get("strike"), "lots": int(abs(q) // lot)})
    return {"underlying": g["underlying"], "legs": legs} if legs and len(legs) <= 10 else None


def _ltp_tip(l: Dict[str, Any]) -> str:
    if l.get("ltp_source") == "Kite live":
        return f"Kite live (the platform's feed){' · ' + hm(l['ltp_at']) if l.get('ltp_at') else ''}"
    who = l.get("broker_display") or "The broker"
    return f"{who}'s own price in its read at {hm(l.get('read_at'))}" + (" (a stored read, not live)" if l.get("state") == "snapshot" else "")


def _pnl_tip(l: Dict[str, Any]) -> str:
    who = l.get("broker_display") or "The broker"
    basis = l.get("pnl_basis")
    if basis == bk.PNL_LIVE:
        return (f"{who}'s own P&L at {hm(l.get('read_at'))}, moved by quantity × the price change since (Kite live). "
                "Before charges.")
    if basis == bk.PNL_MARKED:
        return f"Marked at the last price (quantity × (price − average)), before charges: {who} sent no P&L for this row."
    if basis == bk.PNL_NONE:
        return f"{who} sent no P&L and there is no price to mark it with."
    return f"{who}'s own P&L, as read at {hm(l.get('read_at'))}."


def _badge(l: Dict[str, Any], in_session: bool) -> str:
    if l.get("state") == "snapshot":
        return f"As of {short_stamp(l.get('read_at'))}"
    return "Live" if in_session else f"Read {hm(l.get('read_at'))[:5]}"


def position_rows(groups: List[Dict[str, Any]], in_session: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for g in groups:
        if g["kind"] == "unmapped":
            for u in g.get("unmapped") or []:
                pnl = num(u.get("pnl_rs"))
                rows.append({"symbol": u.get("broker_code"), "tone": tone_of(pnl), "badge": "Not mapped",
                             "tips": {"symbol": u.get("problem") or "This row could not be named as an NSE contract."},
                             "cells": {"symbol": u.get("broker_code"), "account": u.get("broker_display"),
                                       "qty": _signed_qty(u.get("quantity")), "avg": r2(u.get("avg_price")), "ltp": r2(u.get("last_price")),
                                       "pnl": r2(pnl)}})
            continue
        u = g["underlying"]
        for l in g["legs"]:
            pnl = num(l.get("pnl_rs"))
            lots = l.get("lots")
            tips = {"ltp": _ltp_tip(l), "pnl": _pnl_tip(l)}
            if lots is not None and l.get("lot_size"):
                tips["qty"] = f"{abs(lots):g} lot{'' if abs(lots) == 1 else 's'} × {l['lot_size']}"
            rows.append({"symbol": u, "ask": f"Is my trade in {u} still valid?", "tone": tone_of(pnl), "badge": _badge(l, in_session),
                         "tips": tips,
                         "cells": {"symbol": l.get("label") or u, "account": l.get("broker_display"), "qty": _signed_qty(l.get("quantity")),
                                   "avg": r2(l.get("avg_price")), "ltp": r2(l.get("ltp")), "pnl": r2(pnl)}})
    return rows


POSITION_COLUMNS = [{"key": "symbol", "label": "Position", "align": "left", "format": "text"},
                    {"key": "account", "label": "Account", "align": "left", "format": "text"},
                    {"key": "qty", "label": "Qty", "align": "right", "format": "int"},
                    {"key": "avg", "label": "Average", "align": "right", "format": "price"},
                    {"key": "ltp", "label": "Price", "align": "right", "format": "price"},
                    {"key": "pnl", "label": "P&L", "align": "right", "format": "price"}]
LEVEL_COLUMNS = [{"key": "symbol", "label": "Underlying", "align": "left", "format": "text"},
                 {"key": "spot", "label": "Price", "align": "right", "format": "price"},
                 {"key": "stop", "label": "Stop", "align": "right", "format": "price"},
                 {"key": "target", "label": "Target", "align": "right", "format": "price"},
                 {"key": "to_stop", "label": "To stop", "align": "right", "format": "pct"},
                 {"key": "risk", "label": "Loss at stop", "align": "right", "format": "price"},
                 {"key": "margin", "label": "Margin required", "align": "right", "format": "price"},
                 {"key": "expiry", "label": "Expires", "align": "left", "format": "text"}]
ACCOUNT_COLUMNS = [{"key": "symbol", "label": "Account", "align": "left", "format": "text"},
                   {"key": "state", "label": "State", "align": "left", "format": "text"},
                   {"key": "avail", "label": "Available cash", "align": "right", "format": "price"},
                   {"key": "collateral", "label": "Collateral", "align": "right", "format": "price"},
                   {"key": "used", "label": "Used margin", "align": "right", "format": "price"},
                   {"key": "read", "label": "Read", "align": "left", "format": "text"}]


def _expiry_cell(g: Dict[str, Any], today: date) -> Tuple[Optional[str], bool]:
    days = []
    for l in g["legs"]:
        if l.get("expiry"):
            try:
                days.append(date.fromisoformat(l["expiry"]))
            except ValueError:
                continue
    if not days:
        return None, False
    d = min(days)
    left = (d - today).days
    soon = 0 <= left <= analytics.EXPIRY_SOON_DAYS
    return f"{d.day} {d.strftime('%b')} · {'today' if left == 0 else f'{left}d'}", soon


def level_rows(groups: List[Dict[str, Any]], margins: Dict[str, Dict[str, Any]], today: date) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for g in groups:
        if g["kind"] == "unmapped":
            continue
        a = g.get("analytics") or {}
        pay = a.get("payoff") or {}
        lv = g.get("levels")
        codes = {w["code"] for w in g.get("warnings") or []}
        spot = (g.get("price") or {}).get("spot")
        tips: Dict[str, str] = {"symbol": " · ".join(f"{l.get('label')} ({_signed_qty(l.get('quantity'))})" for l in g["legs"])}
        if spot is not None:
            p = g["price"]
            tips["spot"] = f"{ {'kite_live': 'Kite live', 'kite_close': 'Kite close', 'nse_bhavcopy': 'NSE end of day', 'broker': 'the broker'}.get(p.get('source'), p.get('source') or 'a price') } · {p.get('as_of') or ''}".strip(" ·")
        stop_cell: Any
        if lv and lv.get("effective_stop"):
            stop_cell = r2(lv["effective_stop"])
            tips["stop"] = ("Set by you (your Nivesh-side level)" if lv.get("set_by") == "you"
                            else f"From the plan you recorded ({lv.get('plan_id')}); you set none") + \
                (f", trailing {lv['trail_pct']:g}% from the best price" if lv.get("trail_pct") else "")
        else:
            stop_cell = "No stop set"
        risk: Any
        if pay.get("risk_basis") == "expiry":
            risk = r2(pay.get("max_loss")) if pay.get("max_loss") is not None else ("Unbounded" if pay.get("loss_unbounded") else None)
            tips["risk"] = "A defined-risk structure: the most it can lose at expiry, gross, before charges."
        elif pay.get("loss_at_stop_rs") is not None:
            risk = -abs(pay["loss_at_stop_rs"])
            tips["risk"] = (f"If the price reaches your stop ({stop_cell:,.2f}), valued {pay.get('pnl_at_stop_basis') or 'at expiry'}; "
                            "gross, before charges. Never the price falling to zero.")
        else:
            risk = "No stop set" if not lv else None
            tips["risk"] = "Without a stop the loss at a stop cannot be shown, and a to-zero figure is not the risk of a position."
        m = margins.get(g["key"])
        req = margin_request(g)
        margin: Any
        if req is None:
            margin, tips["margin"] = ("None (shares)", "Shares are paid in full: no exchange margin to calculate.") if g["kind"] == "equity" \
                else (None, "This group's F&O legs are not whole lots of a listed contract, so no margin is calculated.")
        elif m and m.get("estimate") is not None:
            margin = r2(m["estimate"])
            tips["margin"] = (f"{m.get('source')}. A calculation for these contracts"
                              + (" (the F&O legs only; shares are paid in full)" if any(l.get("instrument") == "EQ" for l in g["legs"]) else "")
                              + ", not your broker's own requirement.")
        else:
            reason = (m or {}).get("reason") or "not calculated"
            margin = "Needs Kite login" if reason == fb.NO_CALCULATOR else "Not available"
            tips["margin"] = reason
        exp, soon = _expiry_cell(g, today)
        tone = "down" if codes & {"stop_breached"} else "warn" if codes & {"near_stop", "expiry_soon", "price_unavailable"} else \
            "up" if "target_reached" in codes else None
        rows.append({"symbol": g["underlying"], "tone": tone, "ask": f"Is my trade in {g['underlying']} still valid?", "tips": tips,
                     "cells": {"symbol": g["underlying"], "spot": r2(spot), "stop": stop_cell, "target": r2(lv.get("target")) if lv else None,
                               "to_stop": a.get("distance_to_stop_pct"), "risk": risk, "margin": margin, "expiry": exp}})
    return rows


def account_rows(accounts: List[Dict[str, Any]], in_session: bool) -> List[Dict[str, Any]]:
    rows = []
    for a in accounts:
        name = a["broker_display"] or a["broker"] or "Broker"
        f = a.get("funds") or {}
        why_na = (a.get("funds_error") or a.get("error") or {}).get("message") or "Not read."
        if a["state"] != bk.LIVE:
            why_na = (a.get("error") or {}).get("message") or why_na
        cells: Dict[str, Any] = {"symbol": name + (f" · {a['label']}" if a.get("label") and a["label"] != name else ""), "state": STATE_WORD.get(a["state"], a["state"])}
        tips: Dict[str, str] = {}
        for key, field in (("avail", "available_cash_rs"), ("collateral", "collateral_rs"), ("used", "used_margin_rs")):
            v = num(f.get(field)) if f else None
            if v is not None:
                cells[key] = r2(v)
            else:
                cells[key] = "Not available"
                tips[key] = why_na
        if a["state"] == bk.LIVE:
            cells["read"] = f"Positions {hm(a['rows_at'])}" + (f", funds {hm(a['funds_at'])}" if a.get("funds_at") else "")
        elif a.get("rows_at"):
            cells["read"] = f"Last stored read {short_stamp(a['rows_at'])}"
        else:
            cells["read"] = "No stored read"
        rows.append({"symbol": name, "tone": None if a["state"] == bk.LIVE else "warn", "cells": cells, "tips": tips or None,
                     "badge": ("Live" if in_session else None) if a["state"] == bk.LIVE else None})
    return rows


# ── the checks the commentary explains ───────────────────────────────────────

def _dir_word(d: Optional[str]) -> str:
    return {"long": "long", "short": "short"}.get(d or "", "mixed")


def commentary(groups: List[Dict[str, Any]], accounts: List[Dict[str, Any]], margins: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic facts per position, worst first. Every figure is read from the book; none is the model's."""
    warn: List[Dict[str, Any]] = []
    info: List[Dict[str, Any]] = []
    no_plan: List[str] = []
    marked: List[str] = []
    stored = {a["account_id"]: a for a in accounts if a["state"] != bk.LIVE and a.get("rows_at")}
    by_acct = {a["account_id"]: a for a in accounts}
    for g in groups:
        if g["kind"] == "unmapped":
            codes = ", ".join(str(u.get("broker_code")) for u in g.get("unmapped") or [])
            warn.append({"text": f"{len(g.get('unmapped') or [])} broker row(s) could not be named as NSE contracts ({codes}); "
                                 "nothing is worked out from them.", "tone": "warn"})
            continue
        u = g["underlying"]
        a = g.get("analytics") or {}
        pay = a.get("payoff") or {}
        lv, d, plan = g.get("levels"), (g.get("stop_dir") or ""), g.get("plan")
        wmap = {w["code"]: w for w in g.get("warnings") or []}
        side = _dir_word(d)
        if "stop_breached" in wmap:
            warn.append({"text": f"{u}: {wmap['stop_breached']['text']} ({side} position)", "tone": "warn"})
        elif "near_stop" in wmap:
            warn.append({"text": f"{u}: {wmap['near_stop']['text']} ({side} position)", "tone": "warn"})
        elif lv and lv.get("effective_stop") and a.get("distance_to_stop_pct") is not None:
            loss = pay.get("loss_at_stop_rs")
            info.append({"text": f"{u}: {a['distance_to_stop_pct']:.2f}% {'above' if d == 'long' else 'below'} the stop "
                                 f"{lv['effective_stop']:,.2f}" + (f"; the loss at that stop is {price(loss)} (gross)" if loss is not None else "")
                                 + f" ({'your level' if lv.get('set_by') == 'you' else 'from your recorded plan'}).", "tone": None})
        elif not lv:
            warn.append({"text": f"{u}: no stop of yours and no matching plan is on record, so the loss at a stop cannot be shown.", "tone": "warn"})
        if "target_reached" in wmap:
            info.append({"text": f"{u}: {wmap['target_reached']['text']}", "tone": "up"})
        for code in ("expiry_soon", "physical_settlement", "price_unavailable"):
            if code in wmap:
                warn.append({"text": f"{u}: {wmap[code]['text']}", "tone": "warn"})
        if plan:
            day = day_text(iso_day(plan.get("created_at")))
            pdir = plan.get("direction")
            want = {"long": "bullish", "short": "bearish"}.get(d)
            if want and pdir and pdir != want:
                warn.append({"text": f"{u}: the plan you recorded {('on ' + day) if day else ''} is {pdir}, but this position is {side}: "
                                     "they point opposite ways.", "tone": "warn"})
            elif want and pdir == want:
                bits = [f"entry {plan['entry']:,.2f}" if plan.get("entry") is not None else None,
                        f"stop {plan['stop']:,.2f}" if plan.get("stop") is not None else None,
                        f"target {plan['target']:,.2f}" if plan.get("target") is not None else None]
                info.append({"text": f"{u}: the plan you recorded {('on ' + day) if day else ''} ({pdir}; {', '.join(b for b in bits if b)}) "
                                     "points the same way as this position"
                                     + ("; its stop and target are used here because you set none." if lv and lv.get("set_by") == "plan" else "."),
                             "tone": None})
            else:
                info.append({"text": f"{u}: a plan is recorded {('on ' + day) if day else ''} ({pdir or 'direction unknown'}), but this "
                                     f"position is {side}, so it is not compared.", "tone": None})
        else:
            no_plan.append(u)
        m = margins.get(g["key"])
        accts = [x["account_id"] for x in g.get("accounts") or []]
        if m and m.get("estimate") is not None and len(accts) == 1 and by_acct.get(accts[0], {}).get("funds"):
            avail = num(by_acct[accts[0]]["funds"].get("available_cash_rs"))
            if avail:
                info.append({"text": f"{u}: margin for its F&O legs is {price(m['estimate'])} (Zerodha's calculator), "
                                     f"{m['estimate'] / avail * 100:.1f}% of {by_acct[accts[0]]['broker_display']}'s available {price(avail)}.",
                             "tone": None})
        if any(l.get("pnl_basis") == bk.PNL_MARKED for l in g["legs"]):
            marked.append(u)
        old = [stored[x] for x in accts if x in stored]
        if old:
            warn.append({"text": f"{u}: the figures are from the stored read of {stamp(old[0]['rows_at'])} ({old[0]['broker_display']}, "
                                 "session ended): the position may have changed since.", "tone": "warn"})
    for a in accounts:
        f = a.get("funds")
        if a["state"] == bk.LIVE and f:
            bits = [f"available {money(f['available_cash_rs'])}" if num(f.get("available_cash_rs")) is not None else None,
                    f"collateral {money(f['collateral_rs'])}" if num(f.get("collateral_rs")) is not None else None,
                    f"used margin {money(f['used_margin_rs'])}" if num(f.get("used_margin_rs")) is not None else None]
            if any(bits):
                info.append({"text": f"{a['broker_display']}: {', '.join(b for b in bits if b)} (the broker's own funds figures).", "tone": None})
    if marked:
        info.append({"text": f"No P&L was sent for {', '.join(marked)}: it is marked at the last price, before charges.", "tone": None})
    if no_plan:
        info.append({"text": f"No plan of yours is on record for {', '.join(no_plan)}, so no plan is compared with them.", "tone": None})
    return (warn + info)[:COMMENT_MAX]


# ── the view ─────────────────────────────────────────────────────────────────

def money(v: Any) -> Optional[str]:
    """A rupee amount that may be negative, with a true minus before the sign ('−₹92.27'); not a profit or loss (no plus sign)."""
    f = num(v)
    return None if f is None else (f"−₹{abs(f):,.2f}" if f < 0 else f"₹{f:,.2f}")


def _kpi(label: str, value: Optional[str], sub: Optional[str] = None, tone: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"label": label, "value": value, "sub": sub}
    if tone:
        out["tone"] = tone
    return out


def _tot(vals: List[Optional[float]]) -> Optional[float]:
    known = [v for v in vals if v is not None]
    return r2(sum(known)) if known else None


async def _margins(request: Any, uid: str, groups: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    reqs = {g["key"]: r for g in groups if g["kind"] != "unmapped" for r in [margin_request(g)] if r}
    if not reqs:
        return {}, {}
    ck = json.dumps(reqs, sort_keys=True, default=str)
    hit = _MARGINS.get(uid)
    if hit and hit[1].get("_key") == ck and time.monotonic() - hit[0] < MARGIN_VIEW_TTL_S:
        return hit[1]["m"], hit[2]
    try:
        margins, facts = await rd.position_margins(request, uid, reqs)
    except Exception as e:  # noqa: BLE001 — no margin figure is an answer, with its reason
        logger.warning("open book: margin not calculated (%s)", type(e).__name__)
        return {k: {"estimate": None, "reason": f"the margin calculation failed ({type(e).__name__})", "source": None} for k in reqs}, {}
    _MARGINS[uid] = (time.monotonic(), {"_key": ck, "m": margins}, facts)
    return margins, facts


async def view(request: Any, uid: str, now: datetime, *, tick: bool = False) -> Dict[str, Any]:
    """The broker book ready to draw: accounts, groups with the live prices over them, margins. Raises only on a fault in
    the book read itself (the caller records the source as missing)."""
    session = rd.in_session(now)
    book = await rd.open_book(request, uid, tick)
    groups = book["groups"]
    quotes: Dict[str, Any] = {"source": None, "quotes": {}}
    live_accts = [a for a in book["accounts"] if a["state"] == bk.LIVE]
    if session and live_accts and groups:
        unders = sorted({g["underlying"] for g in groups if g["kind"] != "unmapped"})
        try:
            quotes = await rd.underlying_quotes(unders)
        except Exception as e:  # noqa: BLE001 — the broker's own prices stand
            logger.warning("open book: live prices not read (%s)", type(e).__name__)
        groups = bk.apply_marks(groups, quotes)
    margins, mfacts = await _margins(request, uid, groups)
    return {**book, "groups": groups, "quotes": quotes, "margins": margins, "margin_facts": mfacts, "session": session,
            "live": bool(live_accts)}


def book_blocks(v: Dict[str, Any], today: date) -> Dict[str, Dict[str, Any]]:
    """The live blocks by id."""
    groups, accounts, margins, session = v["groups"], v["accounts"], v["margins"], v["session"]
    mapped = [g for g in groups if g["kind"] != "unmapped"]
    legs = [l for g in mapped for l in g["legs"]]
    pnls = [num(l.get("pnl_rs")) for l in legs] + [num(u.get("pnl_rs")) for g in groups if g["kind"] == "unmapped" for u in g.get("unmapped") or []]
    pnl_total = _tot(pnls)
    n_marked = sum(1 for l in legs if l.get("pnl_basis") == bk.PNL_MARKED)
    live_acc = [a for a in accounts if a["state"] == bk.LIVE and a.get("funds")]
    ests = [num((margins.get(g["key"]) or {}).get("estimate")) for g in mapped if margin_request(g)]
    n_rows = len(legs) + sum(len(g.get("unmapped") or []) for g in groups if g["kind"] == "unmapped")
    unm = [u for g in groups if g["kind"] == "unmapped" for u in g.get("unmapped") or []]
    per = [f"{a['broker_display']} {sum(1 for l in legs if l.get('account_id') == a['account_id']) + sum(1 for u in unm if u.get('account_id') == a['account_id'])}" for a in accounts
           if a["state"] in (bk.LIVE, bk.ENDED, bk.FAILED)]
    kpis = [
        _kpi("Broker positions", str(n_rows), ", ".join(per) or None),
        _kpi("Unrealised P&L", rupees(pnl_total) if pnl_total is not None else None,
             ("the brokers' own figures" + (f"; {n_marked} marked at the last price" if n_marked else "")
              + ("; some rows have none" if any(p is None for p in pnls) else "")) if pnl_total is not None else "no P&L to total",
             tone_of(pnl_total)),
        _kpi("Margin required", price(_tot(ests)) if _tot(ests) is not None else None,
             (f"Zerodha's calculator, F&O legs ({sum(1 for e in ests if e is not None)} of {len(ests)} underlyings)"
              if ests and _tot(ests) is not None else ("needs a Kite login" if ests else "no F&O positions"))),
        _kpi("Available cash", money(_tot([num(a["funds"].get("available_cash_rs")) for a in live_acc])) if live_acc else None,
             "the brokers' own figures" if live_acc else "not available: no live session"),
        _kpi("Used margin", money(_tot([num(a["funds"].get("used_margin_rs")) for a in live_acc])) if live_acc else None,
             "the brokers' own figures" if live_acc else "not available: no live session"),
    ]
    out: Dict[str, Dict[str, Any]] = {}
    if not accounts:
        return out
    out["book"] = block("kpis", "book", "Your broker book", None, items=kpis)
    prow = position_rows(groups, session)
    if prow:
        out["positions"] = block("ranked", "positions", f"Broker positions · {n_rows}",
                                 "The brokers' own quantities, averages and P&L. Shares move with Kite's live price while the market is "
                                 "open; a future or option keeps its broker price from the last read (shown on hover).",
                                 columns=POSITION_COLUMNS, rows=prow)
    lrow = level_rows(groups, margins, today)
    if lrow:
        out["levels"] = block("ranked", "levels", "Stops, loss at the stop and margin, by underlying",
                              "Your own stops and targets (or the plan you recorded when you set none). The loss at the stop is gross and is "
                              "never the price falling to zero. Margin is Zerodha's calculator for the F&O legs.",
                              columns=LEVEL_COLUMNS, rows=lrow)
    if accounts:
        out["accounts"] = block("ranked", "accounts", "Your broker accounts",
                                "Available cash, collateral and used margin are each broker's own figures, read only while the session is live.",
                                columns=ACCOUNT_COLUMNS, rows=account_rows(accounts, session))
    items = commentary(groups, accounts, margins)
    if items:
        out["commentary"] = block("list", "commentary", "Checks against your stops and plans",
                                  "Worked out by the platform from the book above. The written commentary explains these; it adds no figure.",
                                  items=items)
    return out


def state_notices(v: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if v["hub"] == "off":
        out.append(notice("Broker connections are not switched on for your account, so only your paper trades are shown.", "info", "no-hub"))
        return out
    if not v["accounts"]:
        n = notice("No broker is connected, so only your paper trades are shown. Connect your broker to see your real positions, "
                   "their margin and live prices here.", "info", "no-broker")
        n["actions"] = [{"kind": "connect_broker", "label": "Connect a broker"}]
        return [n]
    for a in v["accounts"]:
        name = a["broker_display"] or a["broker"] or "Your broker"
        if a["state"] == bk.ENDED:
            tail = (f" Showing the last stored read, as of {stamp(a['rows_at'])} (not live)." if a.get("rows_at")
                    else " There is no stored read to show.")
            n = notice(f"Your {name} session has ended, so live positions, funds and margin are not available. Sign in to {name} again "
                       f"to see them.{tail}", "warn", f"ended-{a['account_id']}")
            n["actions"] = [{"kind": "connect_broker", "label": f"Sign in to {name} again"}]
            out.append(n)
        elif a["state"] == bk.FAILED:
            tail = (f" Showing the last stored read, as of {stamp(a['rows_at'])} (not live)." if a.get("rows_at") else " There is no stored read to show.")
            out.append(notice(f"{(a.get('error') or {}).get('message') or name + ' could not be read just now.'}{tail}", "warn", f"failed-{a['account_id']}"))
        elif a["state"] in (bk.UNSUPPORTED, bk.UNREADABLE):
            out.append(notice(f"{name}: {(a.get('error') or {}).get('message') or 'positions cannot be read for this account.'}", "info",
                              f"unreadable-{a['account_id']}"))
    return out


def _paper_blocks(out: Any, err: Optional[BaseException], src: Sources) -> Tuple[List[Dict[str, Any]], Optional[str], str, Optional[str], Optional[float], int]:
    """The paper section, exactly as the answer showed it before the broker book: (blocks, headline, tone, as_of, unrealised, count)."""
    blocks: List[Dict[str, Any]] = []
    head, tone, as_of, unreal, n = None, "neutral", None, None, 0
    if err or not isinstance(out, dict):
        src.miss(SRC_PAPER, why(err) if err else "the paper book could not be read")
        return blocks, head, tone, as_of, unreal, n
    as_of = iso_day(out.get("as_of"))
    if as_of:
        src.add(SRC_PAPER, as_of)
    else:
        src.missing.append(f"{SRC_PAPER}: no end-of-day mark date on this answer (an F&O-only book marks on its own schedule)")
    trades = [t for t in out.get("trades") or [] if isinstance(t, dict)]
    n = len(trades)
    summ = out.get("summary") or {}
    unreal = num(summ.get("unrealized_pnl_rs"))
    kp = [_kpi("Open", str(summ.get("open") or 0), None),
          _kpi("Unrealised P&L", price(unreal) if unreal is not None else None,
               "net of estimated costs" if unreal is not None else "not every open trade is marked yet", tone_of(unreal))]
    if summ.get("entry_pending"):
        kp.append(_kpi("Not yet triggered", str(summ["entry_pending"]), "waiting for its entry condition"))
    blocks.append(block("kpis", "summary", "Your open paper trades", None, items=kp))
    if trades:
        rows = []
        for t in trades[:15]:
            sym = t.get("symbol")
            pnl = num(t.get("unrealized_pnl_rs"))
            rows.append({"symbol": sym, "ask": f"Should I book profits or hold {sym}?" if sym else None, "tone": tone_of(pnl),
                         "cells": {"symbol": sym, "qty": t.get("quantity"), "entry": r2(t.get("entry_price")), "last": r2(t.get("last_close")),
                                   "stop": r2(t.get("stop_price")), "target": r2(t.get("target_price")), "pnl": r2(pnl)}})
        blocks.append(block("ranked", "trades", f"{n} open paper trade{'s' if n != 1 else ''}",
                            "Paper, not a broker's. Marked at the last available close. Not every trade may be marked yet; see the P&L above.",
                            columns=[{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                                     {"key": "qty", "label": "Qty", "align": "right", "format": "int"},
                                     {"key": "entry", "label": "Entry", "align": "right", "format": "price"},
                                     {"key": "last", "label": "Last close", "align": "right", "format": "price"},
                                     {"key": "stop", "label": "Stop", "align": "right", "format": "price"},
                                     {"key": "target", "label": "Target", "align": "right", "format": "price"},
                                     {"key": "pnl", "label": "Unrealised P&L", "align": "right", "format": "price"}], rows=rows))
        tone = tone_of(unreal)
        head = f"{n} open paper trade{'s' if n != 1 else ''}" + (f", unrealised {price(unreal)}" if unreal is not None else "") + "."
    else:
        blocks.append(notice("No open paper trades right now.", "info", "empty"))
        head = "No open paper trades right now."
    return blocks, head, tone, as_of, unreal, n


def _src_book(src: Sources, v: Dict[str, Any], today: str) -> None:
    live = [a for a in v["accounts"] if a["state"] == bk.LIVE]
    if live:
        src.add(SRC_BOOK, max(_day_of(a["rows_at"]) or "" for a in live) or today)
    for a in v["accounts"]:
        if a["state"] in (bk.ENDED, bk.FAILED) and a.get("rows_at"):
            src.add(f"{SRC_STORED} · {a['broker_display']}", _day_of(a["rows_at"]))
        if a["state"] == bk.LIVE and a.get("funds_error"):
            src.miss(f"{SRC_FUNDS} · {a['broker_display']}", a["funds_error"]["message"])
    if any(a["state"] == bk.LIVE and a.get("funds") for a in v["accounts"]):
        src.add(SRC_FUNDS, today)
    if v["quotes"].get("source") == "kite_live":
        src.add(SRC_KITE, today)
    if any(m.get("estimate") is not None for m in v["margins"].values()):
        src.add(SRC_MARGIN, today)


def _headline(v: Dict[str, Any], paper_head: Optional[str], n_paper: int, paper_unreal: Optional[float]) -> Tuple[Optional[str], str]:
    groups = v["groups"]
    mapped = [g for g in groups if g["kind"] != "unmapped"]
    legs = [l for g in mapped for l in g["legs"]]
    n_rows = len(legs) + sum(len(g.get("unmapped") or []) for g in groups if g["kind"] == "unmapped")
    pnls = [num(l.get("pnl_rs")) for l in legs]
    total = _tot(pnls) if pnls and all(p is not None for p in pnls) else None
    parts: List[str] = []
    if n_rows:
        stored = any(g.get("state") == "snapshot" for g in mapped)
        # While the page is live its P&L moves every few seconds; the tables carry it, not a sentence that would go stale.
        parts.append(f"{n_rows} open broker position{'s' if n_rows != 1 else ''}"
                     + (f" in {len(mapped)} underlying{'s' if len(mapped) != 1 else ''}" if mapped else "")
                     + (f", unrealised {rupees(total)}" if total is not None and not (v["session"] and v["live"]) else "")
                     + (" (a stored read, not live)" if stored else ""))
    if n_paper:
        parts.append(f"{n_paper} open paper trade{'s' if n_paper != 1 else ''}" + (f", unrealised {price(paper_unreal)}" if paper_unreal is not None else ""))
    if not parts:
        return paper_head, "neutral"
    tone = tone_of(total if total is not None else paper_unreal)
    return "; ".join(parts) + ".", tone


async def build_open_trades(intent: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Q13 on the unified book: the user's broker positions (when connected) and the desk's paper trades, labelled."""
    src: Sources = ctx["src"]
    uid, request = ctx["user_id"], ctx["request"]
    now = (ctx.get("now") or datetime.now(IST)).astimezone(IST)
    today = now.date()
    (paper, e_p), (v, e_v) = await _gather_two(rd.open_trades(request), view(request, uid, now))
    blocks: List[Dict[str, Any]] = []
    live_blocks: Dict[str, Dict[str, Any]] = {}
    if e_v or not isinstance(v, dict):
        src.miss("Your broker positions", why(e_v) if e_v else "the broker book could not be read")
        v = None
    else:
        blocks += state_notices(v)
        _src_book(src, v, today.isoformat())
        live_blocks = book_blocks(v, today)
        login = [g for g in v["groups"] if g["kind"] != "unmapped" and margin_request(g)
                 and (v["margins"].get(g["key"]) or {}).get("reason") == fb.NO_CALCULATOR]
        order = [i for i in LIVE_BLOCKS if i in live_blocks]
        blocks += [live_blocks[i] for i in order]
        if login:
            n = notice(fb.login_text(v.get("margin_facts") or {}, "Margin required"), "info", "login")
            n["actions"] = [{"kind": "kite_login", "label": "Log in to Kite"}, {"kind": "connect_broker", "label": "Connect a broker"}]
            blocks.append(n)
    paper_blocks, paper_head, paper_tone, paper_as_of, paper_unreal, n_paper = _paper_blocks(paper, e_p, src)
    blocks += paper_blocks
    has_book = bool(v and (v["groups"]))
    if has_book:
        head, tone = _headline(v, paper_head, n_paper, paper_unreal)
        blocks.append(notice(READ_ONLY_TEXT, "info", "read-only"))
    else:
        head, tone = paper_head, paper_tone
    stored_days = [d for d in (_day_of(a["rows_at"]) for a in (v or {}).get("accounts", []) if a["state"] != bk.LIVE and a.get("rows_at")) if d]
    as_of = today.isoformat() if (v and v["live"]) else (max(stored_days) if stored_days and has_book else paper_as_of)
    p = assemble("open_trades", "Your open trades", as_of, head, tone, blocks, src,
                 follow("How much should I risk?", "Which F&O setups are attractive?", "What is the market view today?",
                        "Today's top 5 opportunities"), now=now)
    if v and v["live"]:
        p["mode"] = "mixed" if v["session"] else "eod"
        p["caveat"] = ("Read from your broker " + (f"at {hm(next(a['rows_at'] for a in v['accounts'] if a['state'] == bk.LIVE))} IST" if v["session"] else "")
                       + ("; shares move with Kite's live price, futures and options keep the broker's last price. " if v["session"]
                          else "; the market is closed, so prices are the last traded. ")
                       + "Nivesh cannot place, modify or cancel an order. Ideas to review, not recommendations.").replace("broker ;", "broker;")
        if v["session"]:
            p["refresh"] = {"path": LIVE_PATH, "interval_s": LIVE_INTERVAL_S, "block_ids": [i for i in LIVE_BLOCKS if i in live_blocks]}
    return p


async def _gather_two(a: Any, b: Any):
    import asyncio
    ra, rb = await asyncio.gather(_try(a), _try(b))
    return ra, rb


async def _try(coro: Any) -> Tuple[Any, Optional[BaseException]]:
    try:
        return await coro, None
    except Exception as e:  # noqa: BLE001 — a failed source is said, never raised
        return None, e


async def live(request: Any, user: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """GET /api/positions/book/live: the live blocks re-worked out from the cached book (no broker call inside the book's
    15 s) and Kite's live share prices, plus whether the page should keep asking. Never a block the answer did not have."""
    now = (now or datetime.now(IST)).astimezone(IST)
    v = await view(request, user["user_id"], now, tick=True)
    blocks = book_blocks(v, now.date())
    active = bool(v["session"] and v["live"])
    why_stop = None if active else ("the market is closed" if not v["session"] else "no broker session is live")
    legs = [l for g in v["groups"] if g["kind"] != "unmapped" for l in g["legs"]]
    return {"generated_at": now.isoformat(timespec="seconds"), "mode": "mixed" if active else "eod",
            "blocks": [blocks[i] for i in LIVE_BLOCKS if i in blocks],
            "refresh": {"active": active, "interval_s": LIVE_INTERVAL_S, "why": why_stop}}
