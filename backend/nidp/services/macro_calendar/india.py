"""India releases: MoSPI's Advance Release Calendar, RBI's MPC schedule and the policy repo rate.

Sources (all official, all free)
  MoSPI   https://mospi.gov.in/release-calendar is a JavaScript page. Its own XHR, GET
          https://www.mospi.gov.in/api/documents/get-latest-release-calender, names the current "Advance Release
          Calendar" PDF (a text PDF: one row per release, the date in the second column). Rows kept: CPI, IIP,
          GDP (quarterly, advance, provisional and final estimates) and the PLFS monthly bulletin. The PDF gives
          the DATE; it does not give a time or a reference period, so:
            * the reference month of CPI and IIP is the month BEFORE the release month (as in MoSPI's own past
              releases: "CPI for the month of September 2026" on 12 Oct; IIP "for August 2026" on 28 Sep);
            * the year of a row is the fiscal year's: April–December → the first year, January–March → the second;
            * the time is the agency's usual 16:00 IST (editorial, time_is_typical).
  RBI     the press release "Meeting Schedule of the Monetary Policy Committee for 2026-2027" on rbi.org.in
          (prid 62422): the decision is announced on the LAST day of each three-day meeting. `actual` is set for the
          most recent decision only, from the "Policy Repo Rate" shown on rbi.org.in's home page; RBI publishes no
          machine-readable history, so earlier decisions carry no figures.
Not read (named in the API's `gaps`): India CPI / IIP / GDP / PLFS VALUES (MoSPI's data API, api.mospi.gov.in, does not
connect from our servers; FRED's India series stop in 2025), WPI dates (the Office of the Economic Adviser site lists only
published press releases, no forward calendar), trade balance and PMI.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, List, Optional, Sequence, Tuple

import aiohttp

from .catalog import IN, MOSPI_CALENDAR_URL, RBI_HOME_URL, RBI_MPC_SCHEDULE_URL, make_row

logger = logging.getLogger(__name__)

MOSPI_LATEST_ARC = "https://www.mospi.gov.in/api/documents/get-latest-release-calender"
MOSPI_BASE = "https://www.mospi.gov.in/"
Block = Tuple[float, float, float, float, str]            # x0, y0, x1, y1, text (PyMuPDF "blocks")
MON3 = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
MON_ABBR = tuple(MON3)
_DATE_RE = re.compile(r"^\s*(\d{1,2})\s*(?:st|nd|rd|th)\s*([A-Za-z]{3,9})\b(.*)$", re.S)
_FY_RE = re.compile(r"CALENDAR\s*\((\d{4})\s*-\s*(\d{2})\)", re.I)
MOSPI_SOURCE = "MoSPI Advance Release Calendar"


# ── MoSPI ────────────────────────────────────────────────────────────────────

def parse_fy_start(first_page_text: str) -> Optional[int]:
    m = _FY_RE.search(first_page_text or "")
    return int(m.group(1)) if m else None


_RELEASED_RE = re.compile(r"Released on\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s*(\d{4})", re.I)
HEADER_Y, FOOTER_Y, TITLE_X, RELEASED_X = 95.0, 735.0, 165.0, 330.0


def parse_mospi_calendar(pages: Sequence[Sequence[Block]], fy_start: int) -> List[Tuple[date, str, Optional[date]]]:
    """(planned date, title, actual release date or None) for every dated row.

    A row starts at a block that begins '12th Nov' left of the title column ('7thJan' with no space also parses; the
    month/year cell '7 Oct 2026' has no ordinal suffix, so it is not a row start). The title is the rest of that block
    plus the following blocks in the title column (170 ≤ x < 330) until the next dated row; the page header and the
    'Page n of 8' footer are skipped. For rows MoSPI has already released, the right-hand column says 'Released on
    13th April, 2026': that block is matched to the row whose top is the nearest at or above it, and gives the real
    release date (a planned Sunday release moves to Monday). Rows split across a page lose their continuation line,
    which no filter below depends on."""
    out: List[List[Any]] = []
    for blocks in pages:
        rows: List[Tuple[float, List[Any]]] = []
        released_blocks: List[Tuple[float, str]] = []
        ordered = sorted(((b[1], b[0], b[4]) for b in blocks), key=lambda t: (t[0], t[1]))
        cur: Optional[List[Any]] = None
        for y, x, text in ordered:
            if y < HEADER_Y or y > FOOTER_Y:
                continue
            if x >= RELEASED_X:
                released_blocks.append((y, text))
                continue
            m = _DATE_RE.match(text)
            if m and x < 135:
                mon = MON3.get(m.group(2)[:3].title())
                if mon:
                    year = fy_start if mon >= 4 else fy_start + 1
                    try:
                        cur = [date(year, mon, int(m.group(1))), m.group(3), None]
                    except ValueError:
                        cur = None
                        continue
                    out.append(cur)
                    rows.append((y, cur))
                    continue
            if cur is not None and x >= TITLE_X:
                cur[1] += " " + text
        for y, text in released_blocks:             # after all rows are known: the block sits a few points ABOVE its row's top
            rel = _RELEASED_RE.search(text)
            mon = MON3.get(rel.group(2)[:3].title()) if rel else None
            target = max((r for r in rows if r[0] <= y + 6), key=lambda r: r[0], default=None)
            if rel and mon and target is not None:
                try:
                    target[1][2] = date(int(rel.group(3)), mon, int(rel.group(1)))
                except ValueError:
                    pass
    return [(r[0], re.sub(r"\s+", " ", r[1]).strip(), r[2]) for r in out]


def _ref_month(release: date) -> str:
    m = release.month - 1 or 12
    y = release.year if release.month > 1 else release.year - 1
    return f"{MON_ABBR[m - 1]} {y}"


def classify_title(title: str, release: date) -> Optional[Tuple[str, Optional[str]]]:
    """(indicator code, reference-period label) for a calendar row we carry; None for everything else."""
    t = title
    if re.search(r"Consumer Price Index", t) and "Labour" not in t:
        return "IN_CPI", _ref_month(release)
    if re.search(r"Index of Industrial", t):
        return "IN_IIP", _ref_month(release)
    if re.search(r"GDP", t) and re.search(r"Estimates", t):
        q = re.search(r"Q([1-4]),?\s*FY\s*(\d{4}-\d{2})", t)
        fy = re.search(r"FY\s*(\d{4}-\d{2})", t)
        kind = ("first advance" if re.search(r"First Advance", t) else "second advance" if re.search(r"Second Advance", t)
                else "provisional" if re.search(r"Provisional", t) else "final" if re.search(r"Final", t) else None)
        if q:
            return "IN_GDP", f"Q{q.group(1)} FY{q.group(2)}"
        if fy:
            return "IN_GDP", f"FY {fy.group(1)}" + (f" ({kind})" if kind else "")
        return "IN_GDP", None
    if re.search(r"Monthly Bulletin of (?:PLFS|Periodic Labour)", t):
        m = re.search(r"(?:PLFS|Survey\s*\(PLFS\))\s*[–-]?\s*([A-Z][a-z]{2})[a-z]*\s*(\d{4})", t)
        return "IN_PLFS", (f"{m.group(1)} {m.group(2)}" if m else None)
    return None


def build_mospi_releases(entries: Sequence[Tuple[date, str, Optional[date]]], fy_start: int) -> List[dict]:
    """Rows for the kept indicators. The date is the actual release date when MoSPI states one, else the planned date.
    CPI / IIP reference month = the month before the release month, except an IIP row early in the month (the 1 June
    launch of the new IIP series, which is not a May figure): that one gets no period rather than a wrong one."""
    base = f"{MOSPI_SOURCE} {fy_start}-{str(fy_start + 1)[-2:]}"
    seen = set()
    rows: List[dict] = []
    for planned, title, released in entries:
        d = released or planned
        c = classify_title(title, d)
        if c is None or (c[0], d) in seen:
            continue
        seen.add((c[0], d))
        code, period = c
        if code == "IN_IIP" and d.day < 20:
            period = None
        src = base + (f" (planned {planned.day} {MON_ABBR[planned.month - 1]}, released {d.day} {MON_ABBR[d.month - 1]})" if released and released != planned else "")
        rows.append(make_row(IN[code], d, period, None, None, src, MOSPI_CALENDAR_URL))
    return sorted(rows, key=lambda r: (r["release_date"], r["indicator_code"]))


def pdf_pages(pdf_bytes: bytes) -> Tuple[List[str], List[List[Block]]]:
    import fitz  # PyMuPDF, already a NIDP dependency (AMC factsheets)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    return [p.get_text() for p in doc], [[tuple(b[:5]) for b in p.get_text("blocks")] for p in doc]  # type: ignore[misc]


# ── RBI ──────────────────────────────────────────────────────────────────────

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_MPC_RE = re.compile(r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),\s*(\d{1,2})\s+and\s+(\d{1,2}),\s*(\d{4})")


def _plain(html: str) -> str:
    html = re.sub(r"(?s)<(script|style).*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html).replace("&nbsp;", " ")).strip()


def parse_rbi_mpc(html: str) -> List[date]:
    """Decision dates (the last day of each meeting) from the RBI press release; [] when the heading is not there."""
    text = _plain(html)
    i = text.find("Dates of meetings of Monetary Policy Committee")
    if i < 0:
        return []
    out = []
    for m in _MPC_RE.finditer(text[i:i + 1200]):
        out.append(date(int(m.group(5)), _MONTHS.index(m.group(1)) + 1, int(m.group(4))))
    return sorted(set(out))


def parse_rbi_repo(html: str) -> Optional[float]:
    m = re.search(r"Policy Repo Rate\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", _plain(html))
    return float(m.group(1)) if m else None


def build_rbi_releases(decisions: Sequence[date], repo: Optional[float], today: date) -> List[dict]:
    """One row per meeting; only the latest decision on or before `today` carries `actual` (the current repo rate)."""
    past = [d for d in decisions if d <= today]
    latest = max(past) if past else None
    rows = []
    for d in sorted(decisions):
        actual = repo if (d == latest and repo is not None) else None
        src = "RBI MPC schedule 2026-27 (rbi.org.in press release 2025-2026/2306)" + (", policy repo rate from rbi.org.in" if actual is not None else "")
        rows.append(make_row(IN["IN_RBI_MPC"], d, f"{MON_ABBR[d.month - 1]} meeting", None, actual, src, RBI_MPC_SCHEDULE_URL))
    return rows


# ── network ──────────────────────────────────────────────────────────────────

async def collect_india(session: aiohttp.ClientSession, today: date) -> Tuple[List[dict], List[str]]:
    rows: List[dict] = []
    failures: List[str] = []
    try:
        async with session.get(MOSPI_LATEST_ARC) as r:
            r.raise_for_status()
            info = (await r.json(content_type=None))["data"]
        async with session.get(MOSPI_BASE + info["url"].lstrip("/")) as r:
            r.raise_for_status()
            pdf = await r.read()
        texts, pages = pdf_pages(pdf)
        fy = parse_fy_start(texts[0] if texts else "")
        if fy is None:
            raise RuntimeError("the calendar PDF does not name its fiscal year")
        built = build_mospi_releases(parse_mospi_calendar(pages, fy), fy)
        if not built:
            raise RuntimeError("no CPI / IIP / GDP / PLFS rows found in the calendar PDF")
        rows += built
    except Exception as e:                                                       # noqa: BLE001
        failures.append(f"MoSPI calendar: {type(e).__name__} {str(e)[:120]}")
        logger.warning("macro_calendar MoSPI failed: %s", type(e).__name__)
    try:
        async with session.get(RBI_MPC_SCHEDULE_URL) as r:
            r.raise_for_status()
            decisions = parse_rbi_mpc(await r.text())
        if not decisions:
            raise RuntimeError("no MPC meeting dates found on the RBI press release page")
        repo = None
        try:
            async with session.get(RBI_HOME_URL) as r:
                r.raise_for_status()
                repo = parse_rbi_repo(await r.text())
        except Exception as e:                                                   # noqa: BLE001
            failures.append(f"RBI repo rate: {type(e).__name__} {str(e)[:120]}")
        rows += build_rbi_releases(decisions, repo, today)
    except Exception as e:                                                       # noqa: BLE001
        failures.append(f"RBI MPC schedule: {type(e).__name__} {str(e)[:120]}")
        logger.warning("macro_calendar RBI failed: %s", type(e).__name__)
    return rows, failures
