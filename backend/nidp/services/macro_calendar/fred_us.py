"""US releases from FRED (api.stlouisfed.org) and the Fed's FOMC calendar page.

What FRED gives, and how each figure is made
  release dates   release/dates?release_id=…  (past and scheduled). Dates only; the times are editorial (catalog.py).
  values          series/observations?output_type=2: the ALFRED vintage matrix, one column per date on which the
                  series changed. The column for a release date is exactly what was published on that day, so
                  `actual` is the FIRST-release figure and `previous` is the prior period AS REVISED on that day,
                  which is how releases are quoted.
  transforms (all from ONE vintage column, never mixing vintages)
      yoy    (value(t) ÷ value(t − 12 months) − 1) × 100                CPI, core PCE, PPI
      mom    (value(t) ÷ value(t − 1 month) − 1) × 100                  retail sales
      chg    value(t) − value(t − 1 month)                              payrolls (thousands)
      level  value(t)                                                    unemployment rate, GDP growth (the series is
                                                                         already the annualised QoQ % change), claims
                                                                         (persons × 0.001 → thousands)
  matching        a release date is matched to the first vintage on or after it within MATCH_DAYS; none → no row.
                  A vintage that brings no new period (same period as the previous release) → actual NULL, not repeated.
  GDP             FRED lists one release date for each of the advance, second and third estimates of a quarter; they are
                  labelled by the order in which one quarter is seen. `previous` is the prior quarter's figure.
  FOMC            decision dates from the Fed's calendar page (the second day of each meeting); actual = DFEDTARU (target
                  rate, upper limit) on the day after the meeting, previous = on the day before. A meeting today or
                  whose next-day value FRED does not hold yet has actual NULL.
  future dates    actual NULL. The first scheduled release of a series carries `previous` = the latest known figure; later
                  scheduled ones carry previous NULL (it does not exist yet).
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import aiohttp

from .catalog import FED_FOMC_URL, FOMC, FRED_RELEASE_URL, US, Indicator, make_row

logger = logging.getLogger(__name__)

FRED_API = "https://api.stlouisfed.org/fred"
MATCH_DAYS = 5
HISTORY_MONTHS = 26
FUTURE_DAYS = 240
Matrix = Dict[date, Dict[date, float]]
MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
GDP_STAGES = ("advance", "second", "third")
_KEY_RE = re.compile(r"api_key=[0-9a-fA-F]{8,}")


def redact(text: str) -> str:
    """Strip a FRED api_key from any text before it is logged or stored."""
    return _KEY_RE.sub("api_key=***", text)


# ── pure helpers ─────────────────────────────────────────────────────────────

def shift_months(d: date, n: int) -> date:
    m = d.year * 12 + (d.month - 1) + n
    y, mo = divmod(m, 12)
    return date(y, mo + 1, min(d.day, calendar.monthrange(y, mo + 1)[1]))


def parse_vintage_matrix(payload: Dict[str, Any], series_id: str) -> Matrix:
    """{vintage date: {observation date: value}} from an output_type=2 answer. '.' (missing) is dropped."""
    out: Matrix = {}
    prefix = series_id + "_"
    for row in payload.get("observations") or []:
        try:
            od = date.fromisoformat(row["date"])
        except (KeyError, ValueError):
            continue
        for k, v in row.items():
            if not k.startswith(prefix):
                continue
            try:
                vd = datetime.strptime(k[len(prefix):], "%Y%m%d").date()
                val = float(v)
            except (ValueError, TypeError):
                continue
            out.setdefault(vd, {})[od] = val
    return dict(sorted(out.items()))


def transform(kind: str, col: Dict[date, float], t: date, scale: float = 1.0) -> Optional[float]:
    """The figure for observation `t` as known in one vintage column; None when an input is missing."""
    cur = col.get(t)
    if cur is None:
        return None
    if kind == "level":
        v: Optional[float] = cur
    elif kind in ("chg", "mom"):
        prev = col.get(shift_months(t, -1))
        if prev is None:
            return None
        v = cur - prev if kind == "chg" else ((cur / prev - 1.0) * 100.0 if prev else None)
    elif kind == "yoy":
        base = col.get(shift_months(t, -12))
        v = (cur / base - 1.0) * 100.0 if base else None
    else:
        return None
    return None if v is None else round(v * scale, 2)


def prev_obs(col: Dict[date, float], t: date) -> Optional[date]:
    earlier = [d for d in col if d < t]
    return max(earlier) if earlier else None


def period_label(freq: str, t: date) -> str:
    if freq == "W":
        return f"Week ending {t.day} {MON[t.month - 1]}"
    if freq == "Q":
        return f"Q{(t.month - 1) // 3 + 1} {t.year}"
    return f"{MON[t.month - 1]} {t.year}"


def next_obs_date(freq: str, t: date) -> date:
    return t + timedelta(days=7) if freq == "W" else shift_months(t, 3 if freq == "Q" else 1)


def match_vintage(vintages: Sequence[date], release: date) -> Optional[date]:
    for v in vintages:
        if v >= release:
            return v if (v - release).days <= MATCH_DAYS else None
    return None


def _label(ind: Indicator, t: date, stage: int) -> str:
    base = period_label(ind.freq or "M", t)
    return f"{base} ({GDP_STAGES[stage - 1]})" if ind.freq == "Q" and 1 <= stage <= 3 else base


def build_us_releases(ind: Indicator, matrix: Matrix, release_dates: Iterable[date], today: date) -> List[dict]:
    """The indicator's rows for every release date given (see the module docstring for the rules).

    Dates on or before FRED's newest vintage are read from the matrix; one with no new reading is left out. Dates after it (scheduled releases, and one
    that is due today but not yet in FRED) get a period label, actual NULL, and `previous` only for the first."""
    url = FRED_RELEASE_URL.format(rid=ind.release_id)
    source = f"FRED, series {ind.series} (ALFRED first release)"
    freq = ind.freq or "M"
    vintages = sorted(matrix)
    newest = vintages[-1] if vintages else None
    dates = sorted(set(release_dates))
    rows: List[dict] = []
    seen_stage: Dict[date, int] = {}
    last_t: Optional[date] = None
    for D in (d for d in dates if newest is not None and d <= newest):
        v = match_vintage(vintages, D)
        col = matrix.get(v) if v else None
        if not col:
            continue                                   # FRED has no vintage for this date: no reading, no row
        t = max(col)
        if (t == last_t and freq != "Q") or (freq == "Q" and seen_stage.get(t, 0) >= 3):
            continue                                   # this vintage brings no new period (a revision-only date)
        stage = seen_stage.get(t, 0) + 1
        seen_stage[t] = stage
        last_t = t
        pt = prev_obs(col, t)
        rows.append(make_row(ind, D, _label(ind, t, stage),
                             transform(ind.kind, col, pt, ind.scale) if pt else None,
                             transform(ind.kind, col, t, ind.scale), source, url))
    ahead = [d for d in dates if newest is None or d > newest]
    if ahead and newest is not None:
        col = matrix[newest]
        cur_t = max(col)
        cur_stage = seen_stage.get(cur_t, 0)
        for i, D in enumerate(ahead):
            if freq == "Q" and 1 <= cur_stage < 3:
                cur_stage += 1                                     # the next estimate of the same quarter
            else:
                cur_t, cur_stage = next_obs_date(freq, cur_t), 1
            previous = None
            if i == 0:
                pt = prev_obs(col, cur_t)
                previous = transform(ind.kind, col, pt, ind.scale) if pt else None
            rows.append(make_row(ind, D, _label(ind, cur_t, cur_stage), previous, None, source, url))
    return sorted(rows, key=lambda r: r["release_date"])


def value_on(series: Dict[date, float], d: date) -> Optional[float]:
    """The daily series' value on `d`: the last observation on or before it (None when none)."""
    on_or_before = [k for k in series if k <= d]
    return series[max(on_or_before)] if on_or_before else None


_MONTHS = {m: i + 1 for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August",
                                           "September", "October", "November", "December"))}
_MEET_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
                      r"(\d{1,2})\s*[-–]\s*(?:(January|February|March|April|May|June|July|August|September|October|November|December)\s+)?(\d{1,2})")


def parse_fomc_meetings(html: str, years: Sequence[int]) -> List[date]:
    """Decision dates (the last day of each scheduled meeting) in the given years, from the Fed's calendar page text."""
    text = re.sub(r"(?s)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r"(\d{4}) FOMC Meetings", text)]
    out: List[date] = []
    for i, (pos, year) in enumerate(heads):
        if year not in years:
            continue
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        for m in _MEET_RE.finditer(text[pos:end]):
            mon2 = _MONTHS[m.group(3) or m.group(1)]
            try:
                out.append(date(year, mon2, int(m.group(4))))
            except ValueError:
                continue
    return sorted(set(out))


def build_fomc_releases(meetings: Iterable[date], target_upper: Dict[date, float], today: date) -> List[dict]:
    rows = []
    last_obs = max(target_upper) if target_upper else None
    first_ahead = True
    for D in sorted(meetings):
        actual = previous = None
        if D >= today and target_upper and first_ahead:
            previous = value_on(target_upper, today)       # the next meeting's "previous" is the rate in force now
            first_ahead = False
        if target_upper and D < today and last_obs is not None and last_obs >= D + timedelta(days=1):
            actual = value_on(target_upper, D + timedelta(days=1))
            previous = value_on(target_upper, D - timedelta(days=1))
        rows.append(make_row(FOMC, D, f"{MON[D.month - 1]} meeting", previous, actual,
                             "Fed FOMC calendar (dates), FRED DFEDTARU (target rate, upper limit)", FED_FOMC_URL))
    return rows


# ── network ──────────────────────────────────────────────────────────────────

async def _get_json(session: aiohttp.ClientSession, path: str, key: str, **params: Any) -> Dict[str, Any]:
    q = {**params, "api_key": key, "file_type": "json"}
    for attempt in range(3):
        async with session.get(f"{FRED_API}/{path}", params=q) as resp:
            if resp.status in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if resp.status != 200:
                raise RuntimeError(f"FRED {path} HTTP {resp.status}")
            return await resp.json(content_type=None)
    raise RuntimeError(f"FRED {path} failed")


async def fetch_release_dates(session, key: str, release_id: int, start: date, end: date) -> List[date]:
    d = await _get_json(session, "release/dates", key, release_id=release_id, realtime_start=start.isoformat(),
                        realtime_end=end.isoformat(), include_release_dates_with_no_data="true", sort_order="asc", limit=1000)
    return sorted({date.fromisoformat(x["date"]) for x in d.get("release_dates", [])})


async def fetch_matrix(session, key: str, series: str, today: date) -> Matrix:
    rt_start = shift_months(today, -HISTORY_MONTHS)
    d = await _get_json(session, "series/observations", key, series_id=series, output_type=2,
                        realtime_start=rt_start.isoformat(), realtime_end=today.isoformat(),
                        observation_start=shift_months(rt_start, -14).isoformat())
    return parse_vintage_matrix(d, series)


async def fetch_daily(session, key: str, series: str, start: date) -> Dict[date, float]:
    d = await _get_json(session, "series/observations", key, series_id=series, observation_start=start.isoformat())
    out: Dict[date, float] = {}
    for o in d.get("observations", []):
        try:
            out[date.fromisoformat(o["date"])] = float(o["value"])
        except (KeyError, ValueError, TypeError):
            continue
    return out


async def collect_us(session: aiohttp.ClientSession, key: str, today: date) -> Tuple[List[dict], List[str]]:
    """All US rows plus a failure line per indicator that could not be read (failures never stop the others)."""
    rows: List[dict] = []
    failures: List[str] = []
    start = shift_months(today, -HISTORY_MONTHS)
    for ind in US.values():
        try:
            dates = await fetch_release_dates(session, key, ind.release_id, start, today + timedelta(days=FUTURE_DAYS))
            matrix = await fetch_matrix(session, key, ind.series, today)
            rows += build_us_releases(ind, matrix, dates, today)
        except Exception as e:                                                   # noqa: BLE001
            failures.append(redact(f"{ind.code}: {type(e).__name__} {str(e)[:120]}"))
            logger.warning("macro_calendar %s failed: %s", ind.code, type(e).__name__)
    try:
        page = await session.get(FED_FOMC_URL)
        html = await page.text()
        meetings = parse_fomc_meetings(html, (today.year - 1, today.year, today.year + 1))
        if not meetings:
            raise RuntimeError("no FOMC meetings found on the Fed page")
        target = await fetch_daily(session, key, "DFEDTARU", start)
        rows += build_fomc_releases([m for m in meetings if m >= start], target, today)
    except Exception as e:                                                       # noqa: BLE001
        failures.append(redact(f"US_FOMC: {type(e).__name__} {str(e)[:120]}"))
        logger.warning("macro_calendar US_FOMC failed: %s", type(e).__name__)
    return rows, failures
