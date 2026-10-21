"""DaaS — the Smart trading desk's macro-release calendar (India and US) and Nifty 50's past reactions.

    GET /v1/desk/macro-calendar?month=YYYY-MM&country=IN,US&impact=H,M,L
    GET /v1/desk/macro-calendar/history?code=US_CPI_YOY[&country=US]

Read-only, on nidp.macro_releases (loaded by services/macro_calendar from FRED, the Fed, MoSPI and RBI; see that
package's docstrings for how each figure is made). A missing figure is null, never 0 or a guess.

Dates and times
  `date`      the release's date in the SOURCE's calendar (the US date for US releases, the IST date for India)
  `date_ist` / `time`  the same moment in IST ('HH:MM'); a 14:00 New York FOMC decision is 00:30 IST the NEXT day in
              winter, so date_ist can differ from date. `time` is null when the agency's time is not known.
  `time_basis` always 'usual time': each agency's usual publication time (our editorial), not read from a calendar.
  `impact`    H / M / L is Nivesh's own rating; no free source rates it.
  `estimate`  always null: no free source publishes consensus forecasts.

History (Nifty 50, nidp.index_eod)
  reaction session  the first Nifty session AFTER the release: a release after the 15:30 IST close (every US release,
                    India's 16:00 CPI / IIP / GDP) reacts on the next session; RBI's 10:00 decision reacts the same day.
  event_day_pct     that session's close ÷ the previous close − 1
  d1_pct            close(next session) ÷ close(reaction session) − 1      w1_pct   close(+5 sessions) ÷ close(reaction session) − 1
  null              the later bar does not exist yet; never 0.
  n / coverage_from the warehouse's Nifty history starts where `coverage_from` says; a release before it is not counted and
                    nothing is padded.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify
from nidp.services.daas_api.routers.desk_events import (HOLIDAY_SQL, INDEX_SQL, _asrow, _num, holiday_rows, month_bounds,
                                                        reaction, stat)
from nidp.services.macro_calendar.catalog import ALL
from nidp.shared.storage.pg import get_pool

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

COUNTRIES = ("IN", "US")
IMPACTS = ("H", "M", "L")
HISTORY_LIMIT = 40
IST = ZoneInfo("Asia/Kolkata")
NSE_CLOSE = time(15, 30)
SOURCES = {
    "releases": "Macro releases (nidp.macro_releases): FRED and the Fed (US), MoSPI and RBI (India)",
    "holidays": "NSE holiday master, CM segment (nidp.nse_holidays)",
    "index": "Nifty 50 close (nidp.index_eod)",
}

GAP_ESTIMATE = "consensus estimates are not shown: no free source publishes them, so every estimate is null"
GAP_TIMES = "release times are each agency's usual time (Nivesh's editorial), not read from the calendars; the PLFS bulletin has none"
GAP_IMPACT = "impact (high / medium / low) is Nivesh's own rating; no source rates it"
GAP_IN_VALUES = ("India CPI, IIP, GDP and PLFS values are not shown, only their dates: MoSPI's data API does not connect from "
                 "our servers and FRED's India series end in 2025")
GAP_RBI = "RBI publishes no machine-readable rate history: only the latest decision carries a rate, earlier ones show none"
GAP_IN_LISTED = ("India WPI, trade balance and PMI are not listed: the Office of the Economic Adviser publishes no forward "
                 "calendar for WPI, and trade balance and PMI have no free source")
GAP_IN_REF = "India CPI and IIP reference months are inferred as the month before the release month"
GAP_US_LISTED = "US ISM and other licensed surveys are not listed; the US list is CPI, core PCE, payrolls, unemployment, GDP, jobless claims, retail sales, PPI and the Fed decision"
GAP_EMPTY = "no macro releases are stored for this month: the macro_calendar ingester has not loaded it yet"
GAP_NO_TABLE = "the macro_releases table does not exist yet (migration 164 has not been applied)"

RELEASES_SQL = """
    SELECT indicator_code, release_date, country, name, short_name, release_time, release_tz, period, previous, estimate,
           actual, unit, impact, source, source_url
      FROM nidp.macro_releases
     WHERE release_date BETWEEN $1 AND $2 AND country = ANY($3::text[]) AND impact = ANY($4::text[])
     ORDER BY release_date, release_time NULLS LAST, indicator_code
"""
HISTORY_SQL = """
    SELECT indicator_code, release_date, country, name, short_name, release_time, release_tz, period, previous, actual, unit
      FROM nidp.macro_releases
     WHERE indicator_code = $1 AND release_date < CURRENT_DATE
     ORDER BY release_date DESC LIMIT $2
"""
BARS_SQL = """
    SELECT DISTINCT ON (as_of_date) as_of_date, close_price, pts_change
      FROM nidp.index_eod WHERE index_name = 'Nifty 50' AND close_price IS NOT NULL
     ORDER BY as_of_date, source
"""


# ── pure helpers ─────────────────────────────────────────────────────────────

def parse_csv(value: str, allowed: Sequence[str], what: str) -> List[str]:
    """'IN,US' → ['IN', 'US'] (upper-cased, de-duplicated, in the allowed order); 400 on anything else or an empty list."""
    parts = {p.strip().upper() for p in (value or "").split(",") if p.strip()}
    if not parts or not parts <= set(allowed):
        raise HTTPException(status_code=400, detail=f"{what} must be a comma-separated subset of {', '.join(allowed)}")
    return [a for a in allowed if a in parts]


def to_ist(release_date: date, time_local: Optional[str], tz: Optional[str]) -> Tuple[date, Optional[str]]:
    """(IST date, 'HH:MM' IST) of a release at `time_local` in `tz` on `release_date`; (release_date, None) with no time."""
    if not time_local or not tz:
        return release_date, None
    hh, mm = (int(x) for x in time_local.split(":"))
    ist = datetime(release_date.year, release_date.month, release_date.day, hh, mm, tzinfo=ZoneInfo(tz)).astimezone(IST)
    return ist.date(), ist.strftime("%H:%M")


def reaction_day(release_date: date, time_local: Optional[str], tz: Optional[str]) -> date:
    """The calendar day on or after which the first Nifty session reacts: the IST date, or the next day when the
    release lands after the 15:30 close (no known time → the IST date)."""
    d_ist, t_ist = to_ist(release_date, time_local, tz)
    if t_ist is None:
        return d_ist
    hh, mm = (int(x) for x in t_ist.split(":"))
    return d_ist + timedelta(days=1) if time(hh, mm) > NSE_CLOSE else d_ist


def shape_event(r: Dict[str, Any]) -> Dict[str, Any]:
    d_ist, t_ist = to_ist(r["release_date"], r.get("release_time"), r.get("release_tz"))
    return {
        "id": f"{r['release_date'].isoformat()}|{r['indicator_code']}", "code": r["indicator_code"],
        "date": r["release_date"], "date_ist": d_ist, "time": t_ist, "time_basis": "usual time" if t_ist else None,
        "country": r["country"], "impact": r["impact"], "name": r["name"], "short": r["short_name"], "period": r.get("period"),
        "previous": _num(r.get("previous")), "estimate": _num(r.get("estimate")), "actual": _num(r.get("actual")),
        "unit": r.get("unit"), "source": r["source"], "source_url": r.get("source_url"),
    }


def build_gaps(countries: Sequence[str], n_events: int) -> List[str]:
    gaps = [GAP_ESTIMATE, GAP_TIMES, GAP_IMPACT]
    if "IN" in countries:
        gaps += [GAP_IN_VALUES, GAP_RBI, GAP_IN_LISTED, GAP_IN_REF]
    if "US" in countries:
        gaps.append(GAP_US_LISTED)
    if n_events == 0:
        gaps.append(GAP_EMPTY)
    return gaps


def bars_with_prev(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Index bars for desk_events.reaction(): prev_close = close − pts_change (None when the points change is missing)."""
    out = []
    for r in rows:
        close, pts = _num(r["close_price"]), _num(r.get("pts_change"))
        out.append({"as_of_date": r["as_of_date"], "close_price": close, "prev_close": (close - pts) if (close is not None and pts is not None) else None})
    return out


# ── routes ───────────────────────────────────────────────────────────────────

def _is_missing_table(e: Exception) -> bool:
    return type(e).__name__ == "UndefinedTableError"


@router.get("/macro-calendar", summary="India and US macro releases for one month, with holidays and Nifty closes")
async def macro_calendar(
    month: str = Query(..., description="YYYY-MM"),
    country: str = Query("IN,US", description="comma-separated: IN, US"),
    impact: str = Query("H,M,L", description="comma-separated: H, M, L"),
) -> Dict[str, Any]:
    lo, hi = month_bounds(month)
    countries = parse_csv(country, COUNTRIES, "country")
    impacts = parse_csv(impact, IMPACTS, "impact")
    pool = await get_pool()
    gaps_extra: List[str] = []
    async with pool.acquire() as conn:
        try:
            rel = [_asrow(r) for r in await conn.fetch(RELEASES_SQL, lo, hi, countries, impacts)]
        except Exception as e:                                                   # noqa: BLE001
            if not _is_missing_table(e):
                raise
            rel, gaps_extra = [], [GAP_NO_TABLE]
        hols = [_asrow(r) for r in await conn.fetch(HOLIDAY_SQL, lo, hi)]
        idx = [_asrow(r) for r in await conn.fetch(INDEX_SQL, lo, hi)]
    events = [shape_event(r) for r in rel]
    gaps = build_gaps(countries, len(events))
    gaps += [g for g in gaps_extra if g not in gaps]
    return jsonify({
        "month": month, "country": countries, "impact": impacts, "as_of": date.today(), "sources": SOURCES,
        "events": events, "count": len(events), "holidays": holiday_rows(hols),
        "index_closes": [{"date": r["as_of_date"], "pct": _num(r["pct_change"])} for r in idx],
        "gaps": gaps,
    })


@router.get("/macro-calendar/history", summary="How Nifty 50 moved after past releases of one indicator")
async def macro_calendar_history(
    code: str = Query(..., min_length=3, max_length=40, description="indicator code, e.g. US_CPI_YOY"),
    country: Optional[str] = Query(None, description="optional IN | US; must match the code"),
) -> Dict[str, Any]:
    c = (code or "").strip().upper()
    ind = ALL.get(c)
    if ind is None:
        raise HTTPException(status_code=400, detail="unknown code; one of " + ", ".join(sorted(ALL)))
    if country is not None and country.strip().upper() != ind.country:
        raise HTTPException(status_code=400, detail=f"{c} is a {ind.country} indicator")
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rel = [_asrow(r) for r in await conn.fetch(HISTORY_SQL, c, HISTORY_LIMIT)]
        except Exception as e:                                                   # noqa: BLE001
            if not _is_missing_table(e):
                raise
            rel = []
        bars = bars_with_prev([_asrow(r) for r in await conn.fetch(BARS_SQL)])
    occ = []
    for r in rel:                                   # newest first
        rx = reaction(bars, reaction_day(r["release_date"], r.get("release_time"), r.get("release_tz")))
        if rx is None or rx["event_day_pct"] is None:
            continue
        occ.append({"date": r["release_date"], "period": r.get("period"), "previous": _num(r.get("previous")),
                    "actual": _num(r.get("actual")), "session": rx["session"], "event_day_pct": rx["event_day_pct"],
                    "d1_pct": rx["d1_pct"], "w1_pct": rx["w1_pct"]})
    first = bars[0]["as_of_date"] if bars else None
    return jsonify({
        "code": c, "country": ind.country, "name": ind.name, "short": ind.short, "unit": ind.unit, "source": SOURCES["index"],
        "coverage_from": first, "coverage_to": bars[-1]["as_of_date"] if bars else None,
        "n": len(occ), "occurrences": occ,
        "stats": {"event_day": stat([o["event_day_pct"] for o in occ]), "d1": stat([o["d1_pct"] for o in occ]),
                  "w1": stat([o["w1_pct"] for o in occ])},
        "basis": (f"Nifty 50's close around past {ind.short} releases: the first session after the release, then the next "
                  f"session and one week later. Nifty history starts {first.isoformat() if first else 'nowhere (no prices)'}; "
                  "earlier releases are not counted. Past behaviour, not a forecast."),
    })
