"""DaaS — the Smart trading desk's stock-events calendar (NSE corporate events, holidays, Nifty closes, past reactions).

    GET /v1/desk/events-calendar?month=YYYY-MM&universe=fno|n50|all
    GET /v1/desk/events-calendar/history?symbol=&type=RESULTS|BOARD|DIVIDEND|BONUS|SPLIT|BUYBACK|RIGHTS|AGM|DEMERGER

Read-only. Every answer names its sources; a missing figure is null, never 0 or a guess.

Event kinds (checked on staging 2026-10-21)
  nidp.event_calendar carries the BOARD MEETING date at which a company will "consider" a dividend / bonus / buyback /
  rights issue / split, and its quarterly-results meetings; it has no ex-date (ex_date is null on every row) and no time
  of day. nidp.corporate_actions carries the executed actions with their ex-date and record date. They are different
  events, so they are never merged by date:
    results meeting     event_calendar quarterly_results   type RESULTS   timing null
    other board meeting event_calendar board_meeting       type BOARD     timing null  (dropped when a RESULTS row exists
                                                                                         for the same symbol and day)
    board to consider   event_calendar dividend|bonus|…    type DIVIDEND… timing 'board'
    ex-date             corporate_actions.ex_date          type DIVIDEND… timing 'ex'
    record date         corporate_actions.record_date      type DIVIDEND… timing 'rec' (only when it differs from the ex-date)
  Left out and named in `gaps`: event_calendar 'other' (free-text board matters), and corporate_actions INTEREST_PAYMENT,
  DISTRIBUTION and OTHER (bond / trust payments, not equity events).
  `timing` is therefore null for meetings: the calendar has no pre / during / post-market time, and none is inferred.
  `announced_at` is NSE's own intimation time (event_calendar.intimated_at), null for corporate actions.

Universe
  n50   the latest Nifty 50 list in nidp.index_constituents
  fno   nidp.security_reference_daily.fno_eligible on its latest day (NSE F&O master)
  all   every symbol
  `universe.n50` / `universe.fno` on each event are true / false, or null when the list is empty.
  `sector` is the symbol's industry in the latest list of the broadest index that holds it (same rule as /desk/event-sources),
  null when no list holds it.

History (reaction of the stock's own price around past occurrences, nidp.prices_eod series EQ)
  occurrence dates   RESULTS: event_calendar quarterly_results dates; DIVIDEND / BONUS / SPLIT / BUYBACK / RIGHTS /
                     DEMERGER: corporate_actions ex-dates; BOARD / AGM: event_calendar dates. Only dates before today.
  event_day_pct      close ÷ the bhavcopy's own prev_close on the first session on or after the date − 1
  d1_pct             close(t+1 session) ÷ close(t) − 1      w1_pct   close(t+5 sessions) ÷ close(t) − 1
  null               the later bar does not exist yet; never 0.
  n / coverage_from  the warehouse's prices start where `coverage_from` says; an occurrence before it is not counted and
                     nothing is padded. Results released after the close show their first reaction in d1_pct.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify, normalise_symbol

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

UNIVERSES = ("fno", "n50", "all")
TYPES = ("RESULTS", "BOARD", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK", "RIGHTS", "AGM", "DEMERGER")
HISTORY_LIMIT = 40
SOURCES = {
    "calendar": "NSE event calendar (nidp.event_calendar)",
    "actions": "NSE corporate actions (nidp.corporate_actions)",
    "holidays": "NSE holiday master, CM segment (nidp.nse_holidays)",
    "index": "Nifty 50 close (nidp.index_eod)",
    "fno": "NSE F&O master (nidp.security_reference_daily.fno_eligible)",
    "n50": "Nifty 50 list (nidp.index_constituents)",
    "prices": "NSE bhavcopy, series EQ (nidp.prices_eod)",
}

# event_calendar.event_type → desk type. 'other' is not an equity event the desk shows.
CAL_TYPE = {"quarterly_results": "RESULTS", "board_meeting": "BOARD", "dividend": "DIVIDEND", "bonus": "BONUS",
            "split": "SPLIT", "buyback": "BUYBACK", "rights": "RIGHTS", "agm": "AGM"}
# corporate_actions.action_type → desk type. Bond / trust payments are left out.
ACTION_TYPE = {"DIVIDEND": "DIVIDEND", "BONUS": "BONUS", "SPLIT": "SPLIT", "BUYBACK": "BUYBACK", "RIGHTS": "RIGHTS",
               "DEMERGER": "DEMERGER"}
GAP_OTHER = "event_calendar 'other' (free-text board matters) is not shown"
GAP_BONDS = "corporate actions of type INTEREST_PAYMENT, DISTRIBUTION and OTHER (bond and trust payments) are not shown"
GAP_TIMING = "meetings carry no pre / during / post-market time in the NSE calendar, so timing is null for them"

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


# ── pure helpers ─────────────────────────────────────────────────────────────

def month_bounds(month: str) -> Tuple[date, date]:
    """First and last day of 'YYYY-MM'; 400 on anything else (year 2000–2100, month 01–12)."""
    m = MONTH_RE.match(month or "")
    if not m or not (2000 <= int(m.group(1)) <= 2100) or not (1 <= int(m.group(2)) <= 12):
        raise HTTPException(status_code=400, detail="month must be YYYY-MM")
    y, mo = int(m.group(1)), int(m.group(2))
    return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct(close: Optional[float], base: Optional[float]) -> Optional[float]:
    """(close ÷ base − 1) × 100 to 2 decimals; None when either is missing or the base is not positive."""
    if close is None or base is None or base <= 0:
        return None
    return round((close / base - 1.0) * 100.0, 2)


def _money(v: Any) -> str:
    f = _num(v)
    return "" if f is None else (str(int(f)) if f == int(f) else f"{f:g}")


def _detail_action(r: Dict[str, Any], typ: str) -> str:
    sub = (r.get("action_subtype") or "").strip().lower()
    if typ == "DIVIDEND":
        amt = _money(r.get("dividend_amount"))
        base = f"Dividend ₹{amt} a share" if amt else "Dividend"
        return f"{base} ({sub})" if sub else base
    if typ == "BONUS":
        return f"Bonus issue {r['ratio']}" if r.get("ratio") else "Bonus issue"
    if typ == "SPLIT":
        pre, post = _money(r.get("face_value_pre")), _money(r.get("face_value_post"))
        if pre and post:
            return f"Split, face value ₹{pre} → ₹{post}"
        return (r.get("purpose") or "Split").strip()
    if typ == "RIGHTS":
        return f"Rights issue {r['ratio']}" if r.get("ratio") else "Rights issue"
    if typ == "BUYBACK":
        return "Buyback"
    return (r.get("purpose") or "Demerger").strip()


_CAL_DETAIL = {"RESULTS": "Board meeting on financial results", "BOARD": "Board meeting", "AGM": "Annual general meeting",
               "DIVIDEND": "Board meeting to consider a dividend", "BONUS": "Board meeting to consider a bonus issue",
               "SPLIT": "Board meeting to consider a split", "BUYBACK": "Board meeting to consider a buyback",
               "RIGHTS": "Board meeting to consider a rights issue"}


def _detail_cal(r: Dict[str, Any], typ: str) -> str:
    base = _CAL_DETAIL.get(typ, "Board meeting")
    return f"{base}, {r['period']}" if r.get("period") else base


def event_id(day: date, symbol: str, typ: str, timing: Optional[str]) -> str:
    return f"{day.isoformat()}|{symbol}|{typ}|{timing or 'mtg'}"


def merge_events(cal_rows: Sequence[Dict[str, Any]], action_rows: Sequence[Dict[str, Any]],
                 lo: date, hi: date) -> List[Dict[str, Any]]:
    """The month's events from the two NSE tables.

    Calendar rows → RESULTS / BOARD / … with timing null (RESULTS, BOARD, AGM) or 'board'. A BOARD row is dropped when a
    RESULTS row exists for the same symbol and day (NSE lists the same meeting under both); rows that differ only in
    `period` collapse to the first. Corporate actions → an 'ex' row on the ex-date and a 'rec' row on the record date
    when it is a different day. Only days inside [lo, hi]. Order: date, symbol, type, timing."""
    out: Dict[Tuple[date, str, str, Optional[str]], Dict[str, Any]] = {}
    results_days = {(r["symbol"], r["event_date"]) for r in cal_rows if CAL_TYPE.get(r["event_type"]) == "RESULTS"}
    for r in cal_rows:
        typ = CAL_TYPE.get(r["event_type"])
        d = r["event_date"]
        if typ is None or not (lo <= d <= hi):
            continue
        if typ == "BOARD" and (r["symbol"], d) in results_days:
            continue
        timing = "board" if typ in ("DIVIDEND", "BONUS", "SPLIT", "BUYBACK", "RIGHTS") else None
        key = (d, r["symbol"], typ, timing)
        if key in out:
            continue
        out[key] = {"id": event_id(d, r["symbol"], typ, timing), "date": d, "symbol": r["symbol"], "name": r.get("company_name"),
                    "type": typ, "timing": timing, "detail": _detail_cal(r, typ), "source": SOURCES["calendar"],
                    "announced_at": r.get("intimated_at")}
    for r in action_rows:
        typ = ACTION_TYPE.get(r["action_type"])
        if typ is None:
            continue
        detail = _detail_action(r, typ)
        for timing, d in (("ex", r.get("ex_date")), ("rec", r.get("record_date"))):
            if d is None or not (lo <= d <= hi):
                continue
            if timing == "rec" and r.get("ex_date") == d:
                continue
            key = (d, r["symbol"], typ, timing)
            if key in out:
                continue
            out[key] = {"id": event_id(d, r["symbol"], typ, timing), "date": d, "symbol": r["symbol"], "name": None,
                        "type": typ, "timing": timing, "detail": detail if timing == "ex" else f"Record date, {detail}",
                        "source": SOURCES["actions"], "announced_at": None}
    return sorted(out.values(), key=lambda e: (e["date"], e["symbol"], e["type"], e["timing"] or ""))


def holiday_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """CM holidays; NSE marks the Muhurat session's day with a trailing '*' in the description."""
    out = []
    for r in rows:
        desc = (r.get("description") or "").strip()
        out.append({"date": r["holiday_date"], "description": desc.rstrip("*").strip(), "muhurat": desc.endswith("*")})
    return sorted(out, key=lambda x: x["date"])


def reaction(bars: Sequence[Dict[str, Any]], day: date) -> Optional[Dict[str, Optional[float]]]:
    """Reaction around `day` from bars sorted by date: None when `day` falls before the first bar or after the last.
    The event session is the first bar on or after `day`; the 1-day and 1-week figures are null when that later bar
    does not exist yet."""
    if not bars or day < bars[0]["as_of_date"] or day > bars[-1]["as_of_date"]:
        return None
    i = next((k for k, b in enumerate(bars) if b["as_of_date"] >= day), None)
    if i is None:
        return None
    close = _num(bars[i]["close_price"])
    base = _num(bars[i].get("prev_close"))
    if base is None and i > 0:
        base = _num(bars[i - 1]["close_price"])
    d1 = _num(bars[i + 1]["close_price"]) if i + 1 < len(bars) else None
    w1 = _num(bars[i + 5]["close_price"]) if i + 5 < len(bars) else None
    return {"session": bars[i]["as_of_date"], "event_day_pct": pct(close, base), "d1_pct": pct(d1, close), "w1_pct": pct(w1, close)}


def stat(values: Sequence[Optional[float]]) -> Dict[str, Optional[float]]:
    v = [x for x in values if x is not None]
    if not v:
        return {"avg": None, "min": None, "max": None}
    return {"avg": round(sum(v) / len(v), 2), "min": round(min(v), 2), "max": round(max(v), 2)}


# ── SQL ──────────────────────────────────────────────────────────────────────

CAL_SQL = """
    SELECT symbol, company_name, event_type, event_date, period, intimated_at
      FROM nidp.event_calendar
     WHERE event_date BETWEEN $1 AND $2 AND event_type <> 'other'
"""
ACTIONS_SQL = """
    SELECT symbol, action_type, action_subtype, purpose, ratio, face_value_pre, face_value_post, dividend_amount,
           ex_date, record_date
      FROM nidp.corporate_actions
     WHERE (ex_date BETWEEN $1 AND $2 OR record_date BETWEEN $1 AND $2)
       AND action_type = ANY($3::text[])
"""
HOLIDAY_SQL = """
    SELECT DISTINCT ON (holiday_date) holiday_date, description
      FROM nidp.nse_holidays WHERE segment = 'CM' AND holiday_date BETWEEN $1 AND $2
     ORDER BY holiday_date, source
"""
INDEX_SQL = """
    SELECT DISTINCT ON (as_of_date) as_of_date, pct_change
      FROM nidp.index_eod WHERE index_name = 'Nifty 50' AND as_of_date BETWEEN $1 AND $2
     ORDER BY as_of_date, source
"""
N50_SQL = """
    SELECT symbol FROM nidp.index_constituents
     WHERE index_name = 'Nifty 50'
       AND as_of_date = (SELECT MAX(as_of_date) FROM nidp.index_constituents WHERE index_name = 'Nifty 50')
"""
FNO_SQL = """
    SELECT symbol, fno_eligible FROM nidp.security_reference_daily
     WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.security_reference_daily)
"""
# Each symbol's industry in the latest list of the index it is in (broadest list first), as /desk/event-sources.
INDUSTRY_SQL = """
    WITH latest AS (SELECT index_name, MAX(as_of_date) AS d FROM nidp.index_constituents GROUP BY index_name)
    SELECT DISTINCT ON (c.symbol) c.symbol, c.industry, c.company_name
      FROM nidp.index_constituents c
      JOIN latest l ON l.index_name = c.index_name AND l.d = c.as_of_date
     WHERE c.symbol = ANY($1::text[]) AND c.industry IS NOT NULL
     ORDER BY c.symbol, CASE c.index_name WHEN 'Nifty Total Market' THEN 0 WHEN 'Nifty 500' THEN 1 ELSE 2 END
"""
OCCURRENCE_CAL_SQL = """
    SELECT DISTINCT event_date AS d FROM nidp.event_calendar
     WHERE symbol = $1 AND event_type = $2 AND event_date < CURRENT_DATE ORDER BY d DESC LIMIT $3
"""
OCCURRENCE_ACTION_SQL = """
    SELECT DISTINCT ex_date AS d FROM nidp.corporate_actions
     WHERE symbol = $1 AND action_type = $2 AND ex_date < CURRENT_DATE ORDER BY d DESC LIMIT $3
"""
BARS_SQL = """
    SELECT DISTINCT ON (as_of_date) as_of_date, close_price, prev_close
      FROM nidp.prices_eod WHERE symbol = $1 AND series = 'EQ' AND close_price IS NOT NULL
     ORDER BY as_of_date, source
"""
HISTORY_CAL_TYPE = {"RESULTS": "quarterly_results", "BOARD": "board_meeting", "AGM": "agm"}


def _asrow(r: Any) -> Dict[str, Any]:
    return dict(r)


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("/events-calendar", summary="NSE stock events for one month, with holidays and Nifty closes")
async def events_calendar(
    month: str = Query(..., description="YYYY-MM"),
    universe: str = Query("fno", description="fno | n50 | all"),
) -> Dict[str, Any]:
    lo, hi = month_bounds(month)
    if universe not in UNIVERSES:
        raise HTTPException(status_code=400, detail="universe must be fno, n50 or all")
    pool = await get_pool()
    async with pool.acquire() as conn:
        cal = [_asrow(r) for r in await conn.fetch(CAL_SQL, lo, hi)]
        acts = [_asrow(r) for r in await conn.fetch(ACTIONS_SQL, lo, hi, list(ACTION_TYPE))]
        hols = [_asrow(r) for r in await conn.fetch(HOLIDAY_SQL, lo, hi)]
        idx = [_asrow(r) for r in await conn.fetch(INDEX_SQL, lo, hi)]
        n50 = {r["symbol"] for r in await conn.fetch(N50_SQL)}
        fno_rows = [_asrow(r) for r in await conn.fetch(FNO_SQL)]
        events = merge_events(cal, acts, lo, hi)
        symbols = sorted({e["symbol"] for e in events})
        ind = {r["symbol"]: r for r in await conn.fetch(INDUSTRY_SQL, symbols)} if symbols else {}
    fno = {r["symbol"] for r in fno_rows if r["fno_eligible"]}
    gaps = [GAP_OTHER, GAP_BONDS, GAP_TIMING]
    if not fno:
        gaps.append("the F&O master has no eligible symbols, so universe.fno is null and the F&O filter returns nothing")
    if not n50:
        gaps.append("no Nifty 50 list is loaded, so universe.n50 is null and the Nifty 50 filter returns nothing")
    out = []
    for e in events:
        sym = e["symbol"]
        e["universe"] = {"n50": (sym in n50) if n50 else None, "fno": (sym in fno) if fno else None}
        if universe == "n50" and e["universe"]["n50"] is not True:
            continue
        if universe == "fno" and e["universe"]["fno"] is not True:
            continue
        i = ind.get(sym)
        e["sector"] = i["industry"] if i else None
        if not e["name"]:
            e["name"] = i["company_name"] if i else None
        out.append(e)
    return jsonify({
        "month": month, "universe": universe, "as_of": date.today(),
        "sources": {k: SOURCES[k] for k in ("calendar", "actions", "holidays", "index", "fno", "n50")},
        "events": out, "count": len(out), "holidays": holiday_rows(hols),
        "index_closes": [{"date": r["as_of_date"], "pct": _num(r["pct_change"])} for r in idx],
        "gaps": gaps,
    })


@router.get("/events-calendar/history", summary="How a stock's price moved around its past occurrences of an event")
async def events_calendar_history(
    symbol: str = Query(..., min_length=1, max_length=20),
    type: str = Query(..., description="|".join(TYPES)),
) -> Dict[str, Any]:
    typ = (type or "").upper()
    if typ not in TYPES:
        raise HTTPException(status_code=400, detail="type must be one of " + ", ".join(TYPES))
    sym = normalise_symbol(symbol)
    pool = await get_pool()
    async with pool.acquire() as conn:
        if typ in HISTORY_CAL_TYPE:
            dates = [r["d"] for r in await conn.fetch(OCCURRENCE_CAL_SQL, sym, HISTORY_CAL_TYPE[typ], HISTORY_LIMIT)]
            basis_dates = "event dates in the NSE event calendar"
        else:
            dates = [r["d"] for r in await conn.fetch(OCCURRENCE_ACTION_SQL, sym, typ, HISTORY_LIMIT)]
            basis_dates = "ex-dates in the NSE corporate actions"
        bars = [_asrow(r) for r in await conn.fetch(BARS_SQL, sym)]
    occ = []
    for d in sorted(dates, reverse=True):
        r = reaction(bars, d)
        if r is None or r["event_day_pct"] is None:
            continue
        occ.append({"date": d, "session": r["session"], "event_day_pct": r["event_day_pct"], "d1_pct": r["d1_pct"], "w1_pct": r["w1_pct"]})
    return jsonify({
        "symbol": sym, "type": typ, "source": SOURCES["prices"],
        "coverage_from": bars[0]["as_of_date"] if bars else None,
        "coverage_to": bars[-1]["as_of_date"] if bars else None,
        "n": len(occ), "occurrences": occ,
        "stats": {"event_day": stat([o["event_day_pct"] for o in occ]), "d1": stat([o["d1_pct"] for o in occ]),
                  "w1": stat([o["w1_pct"] for o in occ])},
        "basis": (f"{sym}'s own close around past {typ.lower()} {basis_dates}; the warehouse's prices start "
                  f"{bars[0]['as_of_date'].isoformat() if bars else 'nowhere (no prices)'}, earlier occurrences are not counted. "
                  "Past behaviour, not a forecast."),
    })
