"""The risk book: one user's open positions, paper equity, period P&L and drawdown, read the same way for every entry
path (Phase 1 item 1.1). Moved out of routes/ai_trader.py (`_portfolio`, `_equity`), where it served only the AI
trader, and extended so it can be relied on by the universal risk service (services/risk_gate/service.py).

WHAT IS IN THE BOOK
    desk paper trades (desk_paper_trades, status "open"): cash share trades and F&O structures (kind "strategy")
    journal trades    (trade_journal, status "OPEN"): counted for open risk, positions, exposure and sector — they are
                      the user's own logged trades and their P&L is not posted to paper cash, so they are NOT part of
                      paper equity or of the daily / weekly P&L
    AI-trader trades  are desk paper trades (the AI trader writes them through the desk), so they are already above

MARKS (end of day; a missing price is never filled in)
    shares      the newest end-of-day close (services/desk_trading.fetch_bars), through desk_trading.simulate and
                public_trade, so the net unrealised P&L is the desk's own figure
    structures  every leg from the NSE F&O bhavcopy (desk_strategy_trades.fetch_inputs) through simulate_strategy:
                futures at the settle price; OPTIONS AT THE CLOSE PRICE, never the settle price — on an expiry day the
                bhavcopy's settle_price of an option holds the UNDERLYING's price, not a premium (checked on 56 of 56
                staging legs) — and an expired leg at intrinsic value against the underlying's close. The option rows'
                settle_price is removed before simulate_strategy sees them, so its close-price fallback is what marks.
    A mark older than MARK_BUDGET_SESSIONS sessions (services/data_freshness) counts as no mark.

EQUITY      paper cash + Σ net unrealised P&L of the open desk positions (net of estimated round-trip costs). Unknown
            (None, with the reasons) when any open desk position has no fresh mark.
PERIOD P&L  for a period starting on IST date P (today; Monday of the ISO week):
            Σ over desk positions open now:   net unrealised now − net unrealised at the close of the last session
                                              before P (0 when opened on or after P, or not yet entered then)
          + Σ over desk trades closed on/after P: net realised − net unrealised at that same close (0 likewise)
            So a loss carried into the period is not counted again, and a gain given back inside it is. Unknown when
            any figure it needs is unknown. Start-of-period equity = equity now − period P&L.
PEAK        the configured equity peak: the starting capital, raised by every higher equity observed here
            (paper_accounts.equity_peak_rs, `$max`, so it is only ever raised and two readers cannot lower it).
DRAWDOWN    (peak − equity) / peak, %, never negative; unknown when equity is.

RESERVED vs LEGACY
    A position opened under Phase 1 carries a reservation on paper_accounts (services/paper_account.reserve_entry):
    its estimated risk, exposure, sector and held symbol are already in the account's counters. A position opened
    before (no `risk_reservation_id`) is "legacy": its risk is estimated here from its stored levels and counted
    against the same budgets until scripts/migrate_risk_reservations.py reserves it.

Reads only, except one write: raising the equity peak.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from services import data_freshness as fresh
from services import desk_strategy_trades as strat
from services import desk_trading as desk
from services import paper_account as acct
from services import risk_controls as rc
from services import risk_profile

logger = logging.getLogger(__name__)

BOOK_VERSION = "risk-book-v1"
JOURNAL = "trade_journal"
MARK_BUDGET_SESSIONS = 2
MAX_JOURNAL_OPEN = 500
NO_POSITION_EXITS = ("cancelled", "entry_not_reached")
FNO_MARKS_SOURCE = "NSE F&O bhavcopy (nidp.fno_bhavcopy via the data platform): futures settle, options close"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _ist(stamp: Any) -> Optional[date]:
    try:
        return desk.ist_date(stamp)
    except Exception:  # noqa: BLE001
        return None


# ── journal positions ────────────────────────────────────────────────────────
def journal_position(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Held quantity, average buy and invested amount of a journal trade, from its fills."""
    qin = qout = 0.0
    cost = 0.0
    for f in doc.get("fills") or []:
        q, p = float(f.get("qty") or 0), float(f.get("price") or 0)
        if (f.get("kind") or "ENTRY").upper() == "ENTRY":
            qin += q
            cost += q * p
        else:
            qout += q
    avg = cost / qin if qin else 0.0
    held = max(qin - qout, 0.0)
    return {"held_qty": held, "avg_buy": avg, "entry_qty": qin, "entry_notional": cost}


# ── marks ────────────────────────────────────────────────────────────────────
def _open_copy(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {**doc, "status": "open"}


def _upto(bars: List[Dict[str, Any]], through: Optional[date]) -> List[Dict[str, Any]]:
    return bars if through is None else [b for b in bars if b["date"] <= through]


def cash_value(doc: Dict[str, Any], bars: List[Dict[str, Any]], through: Optional[date] = None
               ) -> Tuple[Optional[float], Optional[date]]:
    """(net unrealised P&L of a share trade at the newest close on or before `through`, that close's date).
    0.0 when the entry was not reached by then; (None, None) when there is no close to mark it at."""
    upto = _upto(bars, through)
    if through is not None and _ist(doc.get("opened_at")) and _ist(doc["opened_at"]) > through:
        return 0.0, None
    mark = desk.last_close(upto)
    copy = _open_copy(doc)
    sim = desk.simulate(copy, upto) if upto else None
    public = desk.public_trade(copy, mark, sim=sim)
    if public.get("entry_status") not in desk.ENTERED:
        return 0.0, mark["date"] if mark else None
    if mark is None or public.get("net_pnl_rs") is None:
        return None, None
    return float(public["net_pnl_rs"]), mark["date"]


def _risk_rows(leg_rows: List[List[Dict[str, Any]]], legs: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Option rows without settle_price (see MARKS above), so simulate_strategy marks them at the close price."""
    out = []
    for leg, rows in zip(legs, leg_rows):
        if leg.get("kind") == "option":
            out.append([{**r, "settle_price": None} for r in rows])
        else:
            out.append(rows)
    return out


def structure_value(doc: Dict[str, Any], bars: List[Dict[str, Any]], rows: List[List[Dict[str, Any]]],
                    through: Optional[date] = None) -> Tuple[Optional[float], Optional[date]]:
    """(net unrealised P&L of a structure at the session marks on or before `through`, the last marked session)."""
    if through is not None and _ist(doc.get("opened_at")) and _ist(doc["opened_at"]) > through:
        return 0.0, None
    upto_bars = _upto(bars, through)
    upto_rows = [[r for r in leg_rows if through is None or (desk._day(r.get("as_of_date")) or date.max) <= through]
                 for leg_rows in rows]
    sim = strat.simulate_strategy(_open_copy(doc), upto_bars, _risk_rows(upto_rows, doc["legs"]))
    gross = sim["gross_pnl_rs"]
    if gross is None:
        if sim["observations"] == 0:
            return 0.0, None              # no session after the record yet: entered at the leg prices, no move
        return None, None
    marks = [st["mark"] for st in sim["legs"]]
    breakdown = strat.strategy_cost_breakdown(doc, marks)
    if breakdown is None:
        return None, None
    return round(float(gross) - float(breakdown["total"]), 2), sim["last_mark_session"]


async def _structure_inputs(docs: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    gate = asyncio.Semaphore(desk.FETCH_CONCURRENCY)
    got: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    async def one(doc: Dict[str, Any]) -> None:
        try:
            async with gate:
                got[doc["_id"]] = await strat.fetch_inputs(doc)
        except Exception as exc:  # noqa: BLE001 — unmarked, said so; equity is then unknown, never partial
            errors[doc["_id"]] = f"{type(exc).__name__}: {str(exc)[:120]}"

    await asyncio.gather(*(one(d) for d in docs))
    return got, errors


# ── the book ─────────────────────────────────────────────────────────────────
async def read(db, user_id: str, *, now: Optional[datetime] = None, sector_of=None) -> Dict[str, Any]:
    """The whole book (see the module docstring). `sector_of(symbol)` is awaited for legacy positions with no stored
    sector. Raises only when a store cannot be read at all; every unknown figure is None with a reason."""
    moment = now or desk.utcnow()
    today = fresh.ist_today(moment)
    day_start, wk_start = today, week_start(today)
    profile = await risk_profile.read(db, user_id)
    account_doc = await db[acct.ACCOUNTS].find_one({"user_id": user_id})
    account = acct.public(account_doc, user_id)
    open_docs = await db[desk.TRADES].find({"user_id": user_id, "status": "open"}).to_list(desk.MAX_OPEN_TRADES * 2)
    closed_docs = await db[desk.TRADES].find({"user_id": user_id, "status": "closed"}) \
        .sort("closed_at", -1).to_list(desk.MAX_CLOSED_LISTED)
    recent_closed = [d for d in closed_docs if (_ist(d.get("closed_at")) or date.min) >= wk_start]
    journal_open = await db[JOURNAL].find({"user_id": user_id, "status": "OPEN"}).to_list(MAX_JOURNAL_OPEN)

    cash_docs = [d for d in open_docs + recent_closed if d.get("kind") in (None, "cash")]
    struct_docs = [d for d in open_docs + recent_closed if d.get("kind") == strat.KIND]
    starts = desk.fetch_starts(cash_docs, "opened_at") if cash_docs else {}
    (bars, bar_errors), (sinputs, s_errors) = await asyncio.gather(
        desk.fetch_bars_many(starts) if starts else _empty_pair(),
        _structure_inputs(struct_docs) if struct_docs else _empty_pair())

    unknown: List[str] = []
    marks_as_of: List[str] = []
    fno_as_of: List[Optional[str]] = []

    def value(doc: Dict[str, Any], through: Optional[date] = None) -> Tuple[Optional[float], Optional[str]]:
        """(value, why unknown)."""
        if doc.get("kind") == strat.KIND:
            if doc["_id"] in s_errors:
                return None, f"{doc.get('underlying')} structure: F&O marks unreadable ({s_errors[doc['_id']]})"
            b, rows = sinputs[doc["_id"]]
            v, d = structure_value(doc, b, rows, through)
            if through is None and doc.get("status") == "open":
                fno_as_of.append(d.isoformat() if d else None)
                if v is not None and d is not None and not fresh.assess(FNO_MARKS_SOURCE, d, budget_sessions=MARK_BUDGET_SESSIONS, now=moment)["ok"]:
                    return None, f"{doc.get('underlying')} structure: F&O marks as of {d.isoformat()} are stale"
            return (v, None) if v is not None else (None, f"{doc.get('underlying')} structure has no F&O marks")
        sym = doc["symbol"]
        if sym in bar_errors:
            return None, f"{sym}: end-of-day bars unreadable"
        v, d = cash_value(doc, bars.get(sym) or [], through)
        if v is None:
            return None, f"{sym}: no end-of-day close to mark it at"
        if through is None and d is not None and doc.get("status") == "open":
            marks_as_of.append(d.isoformat())
            if not fresh.assess(desk.SOURCE, d, budget_sessions=MARK_BUDGET_SESSIONS, now=moment)["ok"]:
                return None, f"{sym}: last close {d.isoformat()} is stale"
        return v, None

    # equity now
    unrealised = 0.0
    values_now: Dict[str, Optional[float]] = {}
    for doc in open_docs:
        v, why = value(doc)
        values_now[doc["_id"]] = v
        if v is None:
            unknown.append(why or f"{doc.get('symbol')}: unmarked")
        else:
            unrealised += v
    equity = None if unknown else round(account["cash_rs"] + unrealised, 2)

    def period(start: date) -> Tuple[Optional[float], List[str]]:
        anchor_day = start - timedelta(days=1)
        total, whys = 0.0, []
        for doc in open_docs:
            now_v = values_now.get(doc["_id"])
            opened = _ist(doc.get("opened_at")) or today
            anchor_v, why = (value(doc, anchor_day) if opened < start else (0.0, None))
            if now_v is None or anchor_v is None:
                whys.append(why or f"{doc.get('symbol')}: unmarked")
                continue
            total += now_v - anchor_v
        for doc in recent_closed:
            closed = _ist(doc.get("closed_at")) or date.min
            if closed < start:
                continue
            realised = doc.get("net_pnl_rs")
            if realised is None and doc.get("exit_reason") in NO_POSITION_EXITS:
                realised = 0.0
            if realised is None:
                whys.append(f"{doc.get('symbol')}: closed with no net P&L on record")
                continue
            opened = _ist(doc.get("opened_at")) or closed
            anchor_v, why = (value(doc, anchor_day) if opened < start else (0.0, None))
            if anchor_v is None:
                whys.append(why or f"{doc.get('symbol')}: no mark at the period start")
                continue
            total += float(realised) - anchor_v
        return (None if whys else round(total, 2)), whys

    day_pnl, day_whys = period(day_start)
    week_pnl, week_whys = period(wk_start)

    # peak and drawdown
    starting = float(profile.get("starting_capital_rs") or account["starting_capital_rs"])
    stored_peak = (account_doc or {}).get("equity_peak_rs")
    peak = max(float(stored_peak), starting) if stored_peak is not None else starting
    if equity is not None and equity > peak and account_doc is not None:
        await db[acct.ACCOUNTS].update_one({"user_id": user_id},
                                           {"$max": {"equity_peak_rs": float(equity)},
                                            "$set": {"equity_peak_at": moment.astimezone(timezone.utc).isoformat()}})
        peak = float(equity)
    drawdown = None if equity is None or peak <= 0 else round(max(0.0, (peak - equity) / peak * 100.0), 4)

    reserved = acct.reservation_summary(account_doc)
    reserved_ids = {r.get("trade_id") for r in reserved["entries"]}
    legacy: List[Dict[str, Any]] = []
    positions: List[Dict[str, Any]] = []
    for doc in open_docs:
        sym = doc.get("underlying") if doc.get("kind") == strat.KIND else doc.get("symbol")
        entry = next((r for r in reserved["entries"] if r.get("trade_id") == doc["_id"]), None)
        pos = {"trade_id": doc["_id"], "store": desk.TRADES, "kind": doc.get("kind") or "cash", "symbol": sym,
               "quantity": doc.get("quantity"), "entry_price": doc.get("entry_price"),
               "sector": (entry or {}).get("sector") or doc.get("risk_sector"),
               "exposure_rs": (entry or {}).get("exposure_rs"), "risk_rs": (entry or {}).get("risk_rs"),
               "reserved": entry is not None}
        if entry is None:
            pos.update(legacy_estimate(doc))
        positions.append(pos)
    for doc in journal_open:
        jp = journal_position(doc)
        entry = next((r for r in reserved["entries"] if r.get("trade_id") == doc["_id"]), None)
        pos = {"trade_id": doc["_id"], "store": JOURNAL, "kind": "journal", "symbol": doc.get("nse_symbol"),
               "quantity": jp["held_qty"], "entry_price": jp["avg_buy"],
               "sector": (entry or {}).get("sector") or doc.get("risk_sector"),
               "exposure_rs": (entry or {}).get("exposure_rs"), "risk_rs": (entry or {}).get("risk_rs"),
               "reserved": entry is not None}
        if entry is None:
            pos.update(legacy_journal_estimate(doc, jp))
        positions.append(pos)
    for pos in positions:
        if not pos["reserved"]:
            if pos["sector"] is None and sector_of is not None and pos["symbol"]:
                try:
                    pos["sector"] = (await sector_of(pos["symbol"])).get("sector")
                except Exception:  # noqa: BLE001 — stays unknown; counted against every sector (conservative)
                    pos["sector"] = None
            legacy.append(pos)

    legacy_risk = round(sum(p["risk_rs"] or 0.0 for p in legacy), 2)
    legacy_unknown = [p["symbol"] for p in legacy if p["risk_rs"] is None]
    legacy_exposure = round(sum(p["exposure_rs"] or 0.0 for p in legacy), 2)
    sector_rs: Dict[str, float] = dict(reserved["sector_rs_by_name"])
    unclassified = 0.0
    for p in legacy:
        if p["sector"]:
            sector_rs[p["sector"]] = round(sector_rs.get(p["sector"], 0.0) + (p["exposure_rs"] or 0.0), 2)
        else:
            unclassified += p["exposure_rs"] or 0.0
    held = sorted({p["symbol"] for p in positions if p["kind"] in ("cash", "journal") and p["symbol"]})
    fno_ok = None
    if any(d.get("kind") == strat.KIND for d in open_docs):
        fno_ok = not any("structure" in u for u in unknown)
    return {
        "version": BOOK_VERSION,
        "as_of": moment.astimezone(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "profile": profile,
        "account": {**account, "stored": account_doc is not None},
        "equity": {"equity_rs": equity, "cash_rs": account["cash_rs"], "net_unrealised_rs": None if equity is None else round(unrealised, 2),
                   "unknown_reasons": unknown, "basis": risk_profile.CAPITAL_BASIS_TEXT,
                   "marks_as_of": max(marks_as_of) if marks_as_of else None,
                   "fno_marks_as_of": max([d for d in fno_as_of if d], default=None), "fno_marks_ok": fno_ok},
        "peak": {"peak_rs": round(peak, 2), "starting_capital_rs": starting, "stored": stored_peak is not None},
        "drawdown_pct": drawdown,
        "day": {"start": day_start.isoformat(), "pnl_rs": day_pnl, "unknown_reasons": day_whys,
                "start_equity_rs": None if equity is None or day_pnl is None else round(equity - day_pnl, 2)},
        "week": {"start": wk_start.isoformat(), "pnl_rs": week_pnl, "unknown_reasons": week_whys,
                 "start_equity_rs": None if equity is None or week_pnl is None else round(equity - week_pnl, 2)},
        "open": {"positions": len(positions), "reserved_positions": reserved["positions"],
                 "legacy_positions": len(legacy), "risk_rs": round(reserved["risk_rs"] + legacy_risk, 2),
                 "reserved_risk_rs": reserved["risk_rs"], "legacy_risk_rs": legacy_risk,
                 "legacy_risk_unknown": legacy_unknown,
                 "exposure_rs": round(reserved["exposure_rs"] + legacy_exposure, 2),
                 "reserved_exposure_rs": reserved["exposure_rs"], "legacy_exposure_rs": legacy_exposure,
                 "sector_rs": sector_rs, "unclassified_exposure_rs": round(unclassified, 2), "held_symbols": held},
        "positions": positions,
        "reservations": reserved["entries"],
    }


async def _empty_pair():
    return {}, {}


def legacy_estimate(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Risk and exposure of a desk trade opened before reservations existed, from its stored levels (the same
    estimate a new entry gets). None when it cannot be worked out (counted as unknown, never as zero)."""
    from services.risk_gate import estimate as est
    if doc.get("kind") == strat.KIND:
        e, _why = est.structure_risk(doc.get("legs") or [], direction=doc.get("direction"),
                                     stop_underlying=doc.get("stop_underlying"), model=doc.get("cost_model"))
        exposure = strat.exposure_rs(doc)
        return {"risk_rs": e["total"] if e else None, "exposure_rs": exposure}
    try:
        e = est.cash_risk(int(doc["quantity"]), float(doc["entry_price"]), float(doc["stop_price"]), doc.get("cost_model"))
        return {"risk_rs": e["total"], "exposure_rs": round(float(doc["quantity"]) * float(doc["entry_price"]), 2)}
    except (KeyError, TypeError, ValueError):
        return {"risk_rs": None, "exposure_rs": None}


def legacy_journal_estimate(doc: Dict[str, Any], jp: Dict[str, Any]) -> Dict[str, Any]:
    """A journal trade opened before reservations existed: the held shares at their average buy against the stop; with
    no stop (stored as 0) the whole invested amount is at risk."""
    from services.risk_gate import estimate as est
    held, avg = jp["held_qty"], jp["avg_buy"]
    exposure = round(held * avg, 2)
    stop = float(doc.get("stop_loss") or 0)
    if held <= 0:
        return {"risk_rs": 0.0, "exposure_rs": 0.0}
    if 0 < stop < avg:
        return {"risk_rs": est.cash_risk(int(held), avg, stop)["total"], "exposure_rs": exposure}
    return {"risk_rs": exposure, "exposure_rs": exposure}


def governor_positions(book: Dict[str, Any]):
    """The book as the AI-trader governor's Position list (services/ai_trader/risk_governor.Position): shares at their
    quantity and entry price; a structure as one unit valued at its exposure; a journal trade at its held shares."""
    from services.ai_trader.risk_governor import Position
    out = []
    for p in book["positions"]:
        if p["kind"] == "strategy":
            value = p.get("exposure_rs")
            if value is None:
                value = book["equity"]["equity_rs"] or book["account"]["cash_rs"]
            out.append(Position(symbol=p["symbol"], quantity=1, price=float(value), sector=p.get("sector")))
        elif p.get("quantity") and p.get("entry_price"):
            out.append(Position(symbol=p["symbol"], quantity=int(p["quantity"]), price=float(p["entry_price"]),
                                sector=p.get("sector")))
    return out


async def controls(db, user_id: str) -> Optional[Dict[str, Any]]:
    """The kill switch and halt, or None when they cannot be read (never read as off)."""
    try:
        state = await rc.read(db, user_id)
    except Exception:  # noqa: BLE001 — rc.read logs it
        return None
    return {"kill_switch": bool(state.get("kill_switch")), "halted": bool(state.get("halted")), "reason": state.get("reason")}
