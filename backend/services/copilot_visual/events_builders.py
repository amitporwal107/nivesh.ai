"""Results and market-research event answers (owner, 31 Oct 2026): `results_calendar` and `event_intelligence`.

The owner's screenshot: "Which companies report results this week?" was answered by the Filings analyst with "I have no
results calendar". The platform has one (Market Desk › Market Intelligence), and the owner asked for "an AI summary of each
of the result and management commentary and source pdf link to download", and for questions on "order winning, Mergers and
Acquisitions, Ownership" from the desk's AI Event Intelligence chips. These two builders answer from the SAME sources the desk
reads (readers.py), as `briefs` cards (a company or filing, its stored AI summary, commentary points, source-filing links).

Rules (the honesty of the answer):
  - A summary is the stored text of an existing analysis (Mongo event_ai_analysis, through the desk's own functions). This
    module never writes summary text. Where no analysis exists the card says "Not analysed yet" and still shows the filing link.
    Where the analyses could not be read it says that instead: a failed read is never "not analysed".
  - A link is an attachment URL the data carries (links.py), never built from a symbol or a date.
  - The badge is the desk's verdict against the company's OWN past quarters (no analyst consensus is held: nothing here is
    called a beat or a miss), else the classifier's reading of the filing, labelled as such.
  - The answer says how many were left out and offers Market Intelligence for the rest.
  - Cost is bounded: one calendar read for the range, one stored-analysis query, and one file read per card shown (CARD_CAP of
    them, FILE_CONCURRENCY at a time, each with a timeout).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import links as lk
from . import readers as rd
from .intents import Intent
from .payload import IST, Sources, assemble, block, day_text, follow, iso_day, notice, num, short_day, why

logger = logging.getLogger(__name__)

CARD_CAP = 8                  # briefs shown per answer
LIST_CAP = 15                 # rows of the "still to report" / deals tables
CIRCULAR_CAP = 5
FILE_CONCURRENCY = 4          # company-file reads in flight
FILE_TIMEOUT_S = 8.0
FEED_LIMIT = 40               # per feed query, as the desk's chips ask
SYMBOL_FEED_LIMIT = 120       # the feed's own maximum: one company's filings for the window
COMPANY_DAYS = 100            # the desk's MGMT_BACK_DAYS: what management said since the previous results
POINT_CAP = 7

SRC_CALENDAR = "Results calendar (NSE board-meeting dates, DaaS events calendar)"
SRC_ANALYSES = "Stored AI filing analyses (event_ai_analysis)"
SRC_FILES = "Companies' exchange filings (DaaS announcements)"
SRC_FEED = "Exchange filings feed (NSE, AI-read by Nivesh)"
SRC_DEALS = "NSE bulk and block deals"
SRC_CIRCULARS = "SEBI circulars"

AI_NOTE = "AI summary of the filing. Not a recommendation."
NOT_ANALYSED = "Not analysed yet"
KIND_LABEL = {"earnings_call": "Earnings call", "presentation": "Investor presentation", "business_update": "Business update",
              "press_release": "Press release"}
MGMT_KINDS = tuple(KIND_LABEL)


async def _try(coro) -> Tuple[Any, Optional[BaseException]]:
    try:
        return await coro, None
    except Exception as e:  # noqa: BLE001 — a failed source is said, never raised
        return None, e


def _today(src: Sources) -> date:
    return src.w.today if src.w is not None else datetime.now(IST).date()


def _ist_day(v: Any) -> Optional[str]:
    """The IST calendar day of an ISO time (or date) as YYYY-MM-DD."""
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str) and len(v) > 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return iso_day(v)
    else:
        return iso_day(v)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST).date().isoformat()


def _plain(band: Optional[str]) -> str:
    return (band or "").replace("_", " ")


def _band_tone(band: Optional[str]) -> str:
    b = band or ""
    return "up" if b.endswith("positive") else "down" if b.endswith("negative") else "neutral"


def _finish(p: Dict[str, Any], as_of: Optional[str]) -> Dict[str, Any]:
    p["caveat"] = (f"Built from exchange filings and board-meeting dates, data of {day_text(as_of)}. " if as_of else "Built from exchange filings and board-meeting dates. ") \
        + "AI summaries are Nivesh's stored analyses of each filing, not recommendations; nothing is sent to a broker."
    return p


def _open_intel(text: str, bid: str = "more") -> Dict[str, Any]:
    n = notice(text, "info", bid)
    n["actions"] = [{"kind": "open_market_intel", "label": "Open in Market Intelligence"}]
    return n


# ── results_calendar ─────────────────────────────────────────────────────────

def _span(period: str, today: date) -> Tuple[date, date]:
    """The date range of a period. Weeks are Monday to Saturday, as the desk's Results week; on a Sunday "this week" is the
    coming one (the week that ended is last week)."""
    mon = today - timedelta(days=today.weekday())
    if period == "today":
        return today, today
    if period == "tomorrow":
        return today + timedelta(days=1), today + timedelta(days=1)
    if period == "yesterday":
        return today - timedelta(days=1), today - timedelta(days=1)
    if today.weekday() == 6:
        mon = today + timedelta(days=1)
        shift = {"last_week": -14, "next_week": 7}.get(period, 0)
    else:
        shift = {"last_week": -7, "next_week": 7}.get(period, 0)
    start = mon + timedelta(days=shift)
    return start, start + timedelta(days=5)


def _range_text(a: date, b: date) -> str:
    if a == b:
        return f"{a.strftime('%a')} {day_text(a)}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {b.strftime('%b %Y')}"
    return f"{a.day} {a.strftime('%b')} – {b.day} {b.strftime('%b %Y')}"


def _verdict_badge(row: Dict[str, Any]) -> Tuple[str, str]:
    """The result rated against EXPECTATION: the desk's verdict against the company's own baseline built from its past quarters
    (no analyst consensus is held, so nothing is called a beat or a miss against the street). Not rated otherwise; the filing's
    sentiment is a different thing and is never passed off as this rating (it is in the commentary)."""
    v = row.get("verdict") or {}
    label, intensity = v.get("label"), v.get("intensity")
    if label == "above":
        return ("Well above expectation" if intensity == "outstanding" else "Above expectation"), "up"
    if label == "in_line":
        return "Meets expectation", "neutral"
    if label == "below":
        return ("Well below expectation" if intensity == "well_below" else "Below expectation"), "down"
    return "Not rated", "neutral"


def _unrated_reason(row: Dict[str, Any]) -> Optional[str]:
    """Why the desk could not rate a result, in plain words ("baseline too uncertain", "no reliable baseline")."""
    r = ((row.get("verdict") or {}).get("reason") or "").strip()
    if not r:
        return None
    return re.sub(r"^not rated:\s*", "", r, flags=re.I) or None


# ── the five-line AI commentary of one event (owner, 1 Nov 2026) ─────────────────────────────────────────────────────────────
# What happened / Why it matters / Market impact / What to watch / AI take, with a signal, an impact level and a confidence.
# Every line is the STORED AI read (the filing analysis: summary, positives, negatives, open questions, band, materiality,
# confidence, or the feed classifier's one-line, sentiment and impact). Nothing is generated here; a line the stored read does not
# support says so.
COMMENTARY_LABELS = ("What happened", "Why it matters", "Market impact", "What to watch", "AI take")
NOT_STATED = "Not stated in the stored AI read."
BAND_SIGNAL = {
    "extremely_positive": ("Extremely positive", "up", "Bullish"), "strongly_positive": ("Strongly positive", "up", "Bullish"),
    "moderately_positive": ("Moderately positive", "up", "Bullish"), "slightly_positive": ("Slightly positive", "up", "Bullish"),
    "neutral_mixed": ("Mixed or neutral", "warn", "Mixed"),
    "slightly_negative": ("Slightly negative", "down", "Bearish"), "moderately_negative": ("Moderately negative", "down", "Bearish"),
    "strongly_negative": ("Strongly negative", "down", "Bearish"), "extremely_negative": ("Extremely negative", "down", "Bearish"),
}
FEED_SIGNAL = {"positive": ("Positive", "up", "Bullish"), "negative": ("Negative", "down", "Bearish"), "mixed": ("Mixed", "warn", "Mixed"),
               "neutral": ("Neutral", "neutral", "Neutral")}
INFORMATIONAL = ("Informational", "neutral", "Neutral")
IMPACT_HIGH_AT, IMPACT_MEDIUM_AT = 70.0, 45.0           # the stored materiality score (0-100)


def _impact_level(materiality: Any) -> Optional[str]:
    m = num(materiality)
    if m is None:
        return None
    return "High" if m >= IMPACT_HIGH_AT else "Medium" if m >= IMPACT_MEDIUM_AT else "Low"


def _first_sentence(text: Any, cap: int = 200) -> Optional[str]:
    t = " ".join(str(text or "").split())
    if not t:
        return None
    first = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9₹])", t, maxsplit=1)[0]
    if len(first) > cap:
        first = first[:cap].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return first


def _sentences(items: Any, n: int = 2) -> Optional[str]:
    parts = [str(x).strip().rstrip(" .") for x in (items or []) if x and str(x).strip()][:n]
    return (". ".join(parts) + ".") if parts else None


def _commentary(text: Any, signal: Tuple[str, str, str], basis: str, materiality: Any = None, confidence: Any = None, pos: Any = (), neg: Any = (),
                unk: Any = (), rating: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The five lines and the signal chip of one event, or None when the stored read has no text at all."""
    happened = _first_sentence(text)
    if not happened:
        return None
    label, tone, view = signal
    if tone == "up":
        why = _sentences(pos)
    elif tone == "down":
        why = _sentences(neg)
    else:
        a, b = _sentences(pos, 1), _sentences(neg, 1)
        why = " ".join(x for x in ((f"For: {a}" if a else None), (f"Against: {b}" if b else None)) if x) or None
    impact = _impact_level(materiality)
    conf = num(confidence)
    conf = int(round(conf)) if conf is not None else None
    market = f"{view} — {basis}" + (f"; rated {rating.lower()} against its own baseline" if rating and rating != "Not rated" else "") + "."
    watch = "; ".join(str(x).strip().rstrip(" .") for x in (unk or []) if x and str(x).strip())
    watch = "; ".join(watch.split("; ")[:2]) if watch else None
    take = " · ".join(x for x in (label, f"{impact} impact" if impact else None, f"confidence {conf}%" if conf is not None else None) if x)
    lines = [happened, why or NOT_STATED, market, watch or NOT_STATED, f"{take} — an analysis of the filing, not a recommendation."]
    return {"signal": {"label": label, "tone": tone, "impact": impact, "confidence": conf},
            "lines": [{"label": l, "text": t} for l, t in zip(COMMENTARY_LABELS, lines)]}


def _result_commentary(row: Dict[str, Any], file: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The commentary of an analysed result: the desk row's stored read plus, when the company's file carries the analysis of that same
    filing, the positives, negatives and open questions the AI found in it."""
    ol = row.get("outlook") or {}
    if not (ol.get("analysed") and ol.get("summary")):
        return None
    aid = ol.get("announcement_id")
    item = next((a for a in (file or {}).get("analyses") or [] if isinstance(a, dict) and aid and a.get("announcement_id") == aid), {})
    signal = BAND_SIGNAL.get(ol.get("net_band") or "", INFORMATIONAL)
    rating, _ = _verdict_badge(row)
    return _commentary(ol["summary"], signal, f"a {signal[0].lower()} read of the results filing" if signal is not INFORMATIONAL else "no sentiment is stored for this filing",
                       ol.get("materiality_score"), ol.get("confidence_score"), item.get("positives"), item.get("negatives"), item.get("open_questions"), rating)


def _feed_commentary(r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The commentary of a feed filing: its one-line AI read, the classifier's sentiment and impact. The classifier stores no factors or
    open questions, so those two lines say so."""
    sent = (r.get("sentiment") or "").lower()
    signal = FEED_SIGNAL.get(sent, INFORMATIONAL)
    impact = (r.get("impact") or "").lower()
    mat = {"high": 80.0, "medium": 50.0, "low": 10.0}.get(impact)
    return _commentary(r.get("one"), signal, f"a {signal[0].lower()} reading by the filing classifier" if signal is not INFORMATIONAL else "no sentiment is stored for this filing", mat)


def _links_for(file: Optional[Dict[str, Any]], meeting: Optional[str], extra_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """The result's source filings from the company's exchange filings filed within a day before to four days after the
    meeting (the desk's analysis window): the results filing, its press release, the investor presentation, the earnings call."""
    out: List[Dict[str, Any]] = []
    day = date.fromisoformat(meeting) if meeting else None
    lo, hi = (day - timedelta(days=1), day + timedelta(days=4)) if day else (None, None)
    slots = ((("results", "board_outcome"), True, "Results filing"), (("press_release",), True, "Results press release"),
             (("presentation",), None, "Investor presentation"), (("earnings_call",), None, "Earnings call / investor meet"))
    filings = [f for f in (file or {}).get("filings") or [] if isinstance(f, dict)]
    for kinds, need_results, label in slots:
        cands = []
        for f in filings:
            d = _ist_day(f.get("filed_at"))
            if f.get("kind") not in kinds or (need_results and not f.get("results_related")) or not d or lk.safe_url(f.get("url")) is None:
                continue
            if day and not (lo <= date.fromisoformat(d) <= hi):
                continue
            cands.append((d, f))
        # one filing can serve two slots (a results press release that is also the presentation): shown once, under the first
        url = max((c for c in cands if not any(x and x["url"] == c[1]["url"] for x in out)), key=lambda c: c[0], default=None)
        if url:
            out.append(lk.link(label, url[1]["url"]))
    out = [x for x in out if x]
    if extra_url and not any(x["url"] == extra_url for x in out):
        extra = lk.link("Results filing" if not out else "Source filing", extra_url)
        if extra:
            out.append(extra)
    return out


def _points_for(file: Optional[Dict[str, Any]], from_day: Optional[str], extra_rows: Tuple[Dict[str, Any], ...] = ()) -> List[Dict[str, Any]]:
    """Management commentary: the stored analyses of the company's presentations, calls, business updates and press releases
    from the day before the result on (not last quarter's), newest two, as the AI read them: the summary, the points it
    found for and against, and what it says is still unknown. Plus the one-line summaries of other results filings."""
    out: List[Dict[str, Any]] = []
    items = [a for a in (file or {}).get("analyses") or [] if isinstance(a, dict) and a.get("kind") in MGMT_KINDS and a.get("summary")
             and (not from_day or (_ist_day(a.get("at")) or "") >= from_day)]
    seen = set()
    for a in sorted(items, key=lambda a: a.get("at") or "", reverse=True)[:2]:
        seen.add(a.get("announcement_id"))
        out.append({"text": f"{KIND_LABEL[a['kind']]} · {short_day(_ist_day(a.get('at')))}: {a['summary']}", "tone": "neutral"})
        out += [{"text": t, "tone": "up"} for t in (a.get("positives") or [])[:2]]
        out += [{"text": t, "tone": "down"} for t in (a.get("negatives") or [])[:2]]
        out += [{"text": f"Open question: {t}", "tone": "neutral"} for t in (a.get("open_questions") or [])[:1]]
    for r in extra_rows:
        if r.get("one") and r.get("id") not in seen:
            out.append({"text": f"{r.get('docLabel') or 'Filing'} · {short_day(_ist_day(r.get('date')))}: {r['one']}", "tone": "neutral"})
    return out[:POINT_CAP]


def _filter(rows: List[Dict[str, Any]], params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    """(rows after the F&O / sector filters, companies with no sector on record that a sector filter had to leave out)."""
    if params.get("fno_only"):
        rows = [r for r in rows if r.get("fno")]
    left_out = 0
    sector = params.get("sector")
    if sector:
        left_out = sum(1 for r in rows if not r.get("sector"))
        rows = [r for r in rows if (r.get("sector") or "").casefold() == sector.casefold()]
    return rows, left_out


def _calendar_card(row: Dict[str, Any], file: Optional[Dict[str, Any]], analyses_ok: bool) -> Dict[str, Any]:
    ol = row.get("outlook") or {}
    day = iso_day(row.get("event_date"))
    badge, tone = _verdict_badge(row)
    why_unrated = _unrated_reason(row) if badge == "Not rated" else None
    sub = " · ".join(x for x in (f"Declared {short_day(day)}", row.get("period_label"), "F&O" if row.get("fno") else None,
                                 f"Not rated: {why_unrated}" if why_unrated else None) if x)
    if ol.get("analysed") and ol.get("summary"):
        band = f", filing read: {_plain(ol.get('net_band'))}" if ol.get("net_band") else ""
        stamp = _ist_day(ol.get("analyzed_at"))
        body = ol["summary"]
        note = f"AI summary of the results filing{', analysed ' + day_text(stamp) if stamp else ''}{band}. Not a recommendation."
    else:
        body, note = None, (NOT_ANALYSED if analyses_ok else "AI summary could not be read just now (the stored analyses were unavailable).")
    card = {"title": row.get("name") or row["symbol"], "symbol": row["symbol"], "sub": sub, "badge": badge, "tone": tone, "body": body,
            "body_note": note, "points": _points_for(file, (date.fromisoformat(day) - timedelta(days=1)).isoformat() if day else None),
            "links": _links_for(file, day, row.get("filing_url")), "ask": f"Any recent announcements for {row['symbol']}?"}
    comm = _result_commentary(row, file)
    if comm:
        card["commentary"] = comm
    return card


def _card_order(r: Dict[str, Any]) -> tuple:
    ol = r.get("outlook") or {}
    d = iso_day(r.get("event_date"))
    return (0 if ol.get("analysed") else 1, 0 if r.get("fno") else 1, -(num(ol.get("materiality_score")) or 0.0),
            -(date.fromisoformat(d).toordinal() if d else 0), r["symbol"])


async def results_calendar(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    params = intent.params or {}
    today = _today(src)
    start, end = _span(params.get("period") or "this_week", today)
    when = _range_text(start, end)
    tags = (" · F&O" if params.get("fno_only") else "") + (f" · {params['sector']}" if params.get("sector") else "")
    title = f"Results calendar · {when}{tags}"
    fu = follow("Which F&O stocks report results tomorrow?", "Which companies report results next week?", "Any order wins this week?",
                "Any M&A announcements today?")
    cal, err = await _try(rd.results_rows(start, end))
    if err or not isinstance(cal, dict):
        src.miss(SRC_CALENDAR, why(err) if err else "the calendar could not be read")
        return _finish(assemble("results_calendar", title, None, None, "neutral", [], src, fu, now=ctx.get("now")), None)
    as_of = iso_day(cal.get("as_of"))
    src.add(SRC_CALENDAR, as_of)
    analyses_ok = cal.get("analysis_ok", True) is not False
    if not analyses_ok:
        src.miss(SRC_ANALYSES, "the stored filing analyses could not be read, so no summary is shown")
    extra: List[Dict[str, Any]] = []
    if cal.get("partial"):
        extra.append(notice("Part of the calendar could not be read, so the counts and lists below are partial: " + "; ".join(cal.get("gaps") or []) + ".", "warn", "partial"))
    rows, no_sector = _filter([r for r in cal.get("rows") or [] if isinstance(r, dict) and r.get("symbol")], params)
    if params.get("sector") and no_sector:
        extra.append(notice(f"{no_sector} companies have no sector on record in the calendar, so a sector filter leaves them out.", "info", "no-sector"))
    if not rows:
        extra.append(notice(f"No company has a results meeting in {when}{tags.replace(' · ', ', ') if tags else ''}.", "info", "empty"))
        return _finish(assemble("results_calendar", title, as_of, None, "neutral", extra, src, fu, now=ctx.get("now")), as_of)

    decl = [r for r in rows if r["status"] == "declared"]
    held = [r for r in rows if r["status"] == "pending"]
    due = [r for r in rows if r["status"] == "upcoming"]
    analysed = [r for r in decl if (r.get("outlook") or {}).get("analysed")]
    trend = {k: sum(1 for r in decl if (r.get("verdict") or {}).get("label") == k) for k in ("above", "in_line", "below")}
    n_fno = sum(1 for r in rows if r.get("fno"))

    # the cards: declared results, analysed first, F&O names favoured, then the more material; one bounded file read each
    ranked = sorted(decl, key=_card_order)
    cards_rows = ranked[:CARD_CAP]
    gate = asyncio.Semaphore(FILE_CONCURRENCY)

    async def read_file(r: Dict[str, Any]):
        d = iso_day(r.get("event_date"))
        since = date.fromisoformat(d) - timedelta(days=1) if d else today - timedelta(days=COMPANY_DAYS)
        async with gate:
            return await _try(asyncio.wait_for(rd.company_results_file(r["symbol"], since), FILE_TIMEOUT_S))
    reads = await asyncio.gather(*(read_file(r) for r in cards_rows))
    cards, read_ok = [], 0
    for r, (file, ferr) in zip(cards_rows, reads):
        if ferr or not isinstance(file, dict):
            src.missing.append(f"{SRC_FILES} ({r['symbol']}): {why(ferr) if ferr else 'no answer'}")
            file = None
        else:
            read_ok += 1
            for g in file.get("gaps") or []:
                src.missing.append(f"{SRC_FILES} ({r['symbol']}): {g}")
        cards.append(_calendar_card(r, file, analyses_ok))
    if read_ok:
        src.add(SRC_FILES, as_of, f"{read_ok} of {len(cards_rows)} companies read")

    kpis = [{"label": "Companies", "value": str(len(rows)), "sub": f"{when}"}]
    if decl:
        kpis.append({"label": "Declared", "value": str(len(decl)), "sub": f"{len(analysed)} with an AI summary, {len(decl) - len(analysed)} not analysed yet"})
    if held:
        kpis.append({"label": "Figures awaited", "value": str(len(held)), "sub": "meeting held, results not loaded yet"})
    if due:
        kpis.append({"label": "Still to report", "value": str(len(due))})
    kpis.append({"label": "F&O names", "value": str(n_fno)})
    if decl:
        rated = sum(trend.values())
        kpis.append({"label": "Above · meets · below", "value": f"{trend['above']} · {trend['in_line']} · {trend['below']}",
                     "sub": f"{len(decl) - rated} not rated · expectation = each company's own baseline from its past quarters, not analyst consensus"})
    blocks: List[Dict[str, Any]] = [block("kpis", "counts", "Results in this window", None, items=kpis)]
    if cards:
        blocks.append(block(
            "briefs", "declared", "Declared results · AI summary, management commentary, source filings",
            f"Showing {len(cards)} of {len(decl)} declared results: the ones with an AI summary first, F&O names first within them. The badge rates a result "
            "Below, Meets or Above expectation, where expectation is the company's own baseline from its past quarters (no analyst consensus is held, so "
            "nothing here is a beat or a miss against the street). The five-line commentary is the stored AI read of the filing: its signal, impact and "
            "confidence are the analysis's, not recommendations.", items=cards))
    waiting = sorted(held + due, key=lambda r: (0 if r.get("fno") else 1, str(r.get("event_date")), r["symbol"]))
    if waiting:
        shown = waiting[:LIST_CAP]
        blocks.append(block(
            "ranked", "due", "Still to report", "F&O names first, then by date. Select Ask for a company's latest results.",
            columns=[{"key": "symbol", "label": "Symbol", "format": "text"}, {"key": "name", "label": "Company", "format": "text"},
                     {"key": "date", "label": "Date", "format": "text"}, {"key": "status", "label": "Status", "format": "text"},
                     {"key": "fno", "label": "F&O", "format": "text"}, {"key": "sector", "label": "Sector", "format": "text"}],
            rows=[{"symbol": r["symbol"], "ask": f"How were {r['symbol']} results?",
                   "cells": {"symbol": r["symbol"], "name": r.get("name") or "—", "date": short_day(iso_day(r.get("event_date"))) or "—",
                             "status": "Figures awaited" if r["status"] == "pending" else "Due", "fno": "F&O" if r.get("fno") else "—",
                             "sector": r.get("sector") or "—"}} for r in shown]))
    cut = []
    if decl:
        cut.append(f"{len(cards)} of {len(decl)} declared results" if len(cards) < len(decl) else f"all {len(decl)} declared results")
    if waiting:
        cut.append(f"{len(shown)} of {len(waiting)} still to report" if len(shown) < len(waiting) else f"all {len(waiting)} still to report")
    blocks.append(_open_intel(f"Showing {' and '.join(cut)}. The full calendar, with every company's score and the market's reaction, is in Market Intelligence."))
    parts = [f"{len(decl)} declared ({len(analysed)} with an AI summary)" if decl else None, f"{len(held)} awaiting figures" if held else None,
             f"{len(due)} still to report" if due else None]
    scope = " (F&O names only)" if params.get("fno_only") else f" ({params['sector']} only)" if params.get("sector") else ""
    head = (f"{len(rows)} companies report in {when}{scope}: " if len(rows) != 1 else f"1 company reports in {when}{scope}: ") + ", ".join(p for p in parts if p) + "."
    return _finish(assemble("results_calendar", title, as_of, head, "neutral", extra + blocks, src, fu, now=ctx.get("now")), as_of)


# ── event_intelligence ───────────────────────────────────────────────────────

# The desk's Market Intelligence chips (frontend tradingdesk/intel-data.ts INTEL_CHIPS) and the feed queries each one makes.
CHIPS: Dict[str, Dict[str, Any]] = {
    "all": {"title": "Latest filings", "label": "filings", "cats": [None]},
    "announcements": {"title": "Corporate announcements", "label": "announcement filings", "cats": ["management", "capex", "qip", "rating"]},
    "results": {"title": "Results filings", "label": "results filings", "cats": ["earnings"]},
    "calls": {"title": "Calls and guidance", "label": "call and guidance filings", "fams": ["calls"],
              "missing": "There is no guidance tracker: these are the companies' call, investor-meet and presentation filings. A summary appears only where "
                         "Nivesh has analysed the filing."},
    "orders": {"title": "Order wins", "label": "order filings", "cats": ["orders"]},
    "mna": {"title": "M&A and corporate actions", "label": "M&A and corporate-action filings", "cats": ["mna", "dividend", "buyback"]},
    "ownership": {"title": "Ownership disclosures", "label": "ownership disclosures", "fams": ["ownership"],
                  "missing": "Promoter and insider trades from NSE's SAST / PIT disclosure files are not loaded yet (nidp.insider_sast is empty); these are the "
                             "companies' own filings."},
    "regulatory": {"title": "Regulatory", "label": "regulatory filings", "cats": ["regulatory", "litigation"]},
    "exchange": {"title": "Exchange notices", "label": "exchange notices", "fams": ["exchange"],
                 "missing": "F&O ban lists and ASM / GSM surveillance lists are not ingested, so trading restrictions are not listed; these are the companies' "
                            "answers to the exchange's queries."},
}
# DaaS /v1/desk/filings' subject patterns for the families (the feed route cannot filter a family by company).
FAMILY_RE = {
    "calls": re.compile(r"con\.?\s*call|analyst.*meet|investor\s+meet|transcript|earnings\s+call|investor\s+presentation", re.I),
    "ownership": re.compile(r"takeover|sast|insider\s+trading|shareholding\s+pattern|pledge|encumbrance|promoter", re.I),
    "exchange": re.compile(r"spurt\s+in\s+volume|price\s+movement|news\s+verification|rumou?r\s+verification|clarification\s+(sought|on)", re.I),
}
PERIOD = {"today": ("today", 2), "week": ("last 7 days", 7), "month": ("last 30 days", 30)}
IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


def _feed_badge(r: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """The classifier's reading of a filing ("Positive · high impact"), tone from its sentiment. An AI label, said so on the card."""
    sentiment, impact = (r.get("sentiment") or "").lower(), (r.get("impact") or "").lower()
    parts = [sentiment.capitalize()] if sentiment else []
    if impact:
        parts.append(f"{impact} impact" if parts else f"{impact.capitalize()} impact")
    if not parts:
        return None, None
    return " · ".join(parts), {"positive": "up", "negative": "down"}.get(sentiment, "neutral")


def _feed_card(r: Dict[str, Any]) -> Dict[str, Any]:
    sym = (r.get("ticker") or r.get("code") or "").strip().upper() or None
    badge, tone = _feed_badge(r)
    sub = " · ".join(x for x in (day_text(_ist_day(r.get("date"))), r.get("exchange") or "Exchange", r.get("docLabel")) if x)
    link = lk.link("Source filing", r.get("url"))
    one = r.get("one")
    card = {"title": r.get("name") or sym or "Filing", "symbol": sym, "sub": sub, "badge": badge, "tone": tone, "body": one,
            "body_note": AI_NOTE if one else NOT_ANALYSED, "points": [], "links": [link] if link else [],
            "ask": f"Any recent announcements for {sym}?" if sym else None}
    comm = _feed_commentary(r) if one else None
    if comm:
        card["commentary"] = comm
    return card


def _feed_order(r: Dict[str, Any]) -> tuple:
    try:
        ts = datetime.fromisoformat(str(r.get("date")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        ts = 0.0
    return (0 if r.get("one") else 1, IMPACT_RANK.get((r.get("impact") or "").lower(), 3), -ts)


def _in_period(rows: List[Dict[str, Any]], period: str, today: date) -> List[Dict[str, Any]]:
    if period != "today":
        return rows
    return [r for r in rows if _ist_day(r.get("date")) == today.isoformat()]


async def _freshness(src: Sources, request: Any, rows: List[Dict[str, Any]]) -> Optional[str]:
    """The feed's date: the newest filing of any category (how current the pipeline is, not how recent this category's last
    event was), else the newest row of the answer."""
    newest, err = await _try(rd.latest_filing_day(request))
    day = iso_day(newest) if not err else None
    if day is None:
        day = max((d for d in (_ist_day(r.get("date")) for r in rows) if d), default=None)
    src.add(SRC_FEED, day)
    return day


def _chip_rows(rows: List[Dict[str, Any]], chip: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """One company's filings that belong to a chip (the symbol feed carries every category)."""
    if key == "all":
        return rows
    if chip.get("cats"):
        cats = set(chip["cats"])
        return [r for r in rows if (r.get("category") or "").lower() in cats]
    rx = FAMILY_RE[chip["fams"][0]]
    return [r for r in rows if rx.search(r.get("docLabel") or "")]


def _plural_note(shown: int, total: int, chip: Dict[str, Any], when: str, with_summary: int) -> str:
    return (f"Showing {shown} of {total} {chip['label']} from the {when}: the ones with an AI summary first, then by impact, then newest. "
            f"{with_summary} shown {'has' if with_summary == 1 else 'have'} an AI summary; the rest are not analysed yet. Tone and impact are an AI classifier's reading of "
            "each filing, not a view on the stock. Every filing is in Market Intelligence.")


def _deal_cell(v: Any, fmt) -> str:
    n = num(v)
    return "—" if n is None else fmt(n)


async def _deals(intent: Intent, ctx: Dict[str, Any], title_tail: str, fu) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    period = intent.params.get("period") or "week"
    days = {"today": 1, "week": 5, "month": 30}.get(period, 5)
    title = f"Bulk and block deals{' · ' + intent.symbol if intent.symbol else ''}"
    body, err = await _try(rd.deals(ctx["request"], days=days, symbol=intent.symbol, limit=200))
    if err or not isinstance(body, dict):
        src.miss(SRC_DEALS, why(err) if err else "no answer")
        return _finish(assemble("event_intelligence", title, None, None, "neutral", [], src, fu, now=ctx.get("now")), None)
    as_of = iso_day(body.get("as_of"))
    src.add(SRC_DEALS, as_of)
    rows = [r for r in body.get("rows") or [] if isinstance(r, dict) and r.get("symbol")]
    if not rows:
        n = notice(f"No bulk or block deals on record for {'the latest session' if period == 'today' else 'the last ' + str(days) + ' days'}"
                   f"{' in ' + intent.symbol if intent.symbol else ''} (NSE publishes the day's deals after the close).", "info", "empty")
        return _finish(assemble("event_intelligence", title, as_of, None, "neutral", [n], src, fu, now=ctx.get("now")), as_of)
    total = int(num(body.get("total")) or len(rows))
    top = sorted(rows, key=lambda r: -(num(r.get("value_cr")) or 0.0))[:LIST_CAP]
    table = block(
        "ranked", "deals", f"Bulk and block deals · latest {day_text(as_of)}" if as_of else "Bulk and block deals",
        (body.get("disclosure") or "Every row is the exchange's own deal disclosure.") + " Largest by value first.",
        columns=[{"key": "symbol", "label": "Symbol", "format": "text"}, {"key": "kind", "label": "Deal", "format": "text"},
                 {"key": "client", "label": "Client", "format": "text"}, {"key": "side", "label": "Side", "format": "text"},
                 {"key": "value", "label": "Value", "format": "text"}, {"key": "pct", "label": "% of shares", "format": "text"},
                 {"key": "date", "label": "Date", "format": "text"}],
        rows=[{"symbol": r["symbol"], "ask": f"Any recent announcements for {r['symbol']}?",
               "cells": {"symbol": r["symbol"], "kind": (r.get("kind") or "deal").capitalize(), "client": r.get("client_name") or "—",
                         "side": (r.get("side") or "—").capitalize(), "value": _deal_cell(r.get("value_cr"), lambda n: f"₹{n:,.2f} Cr"),
                         "pct": _deal_cell(r.get("pct_of_shares"), lambda n: f"{n:.2f}%"), "date": short_day(iso_day(r.get("date"))) or "—"}} for r in top])
    more = _open_intel(f"Showing {len(top)} of {total} deals. The day's full bulk and block list is in Market Intelligence.")
    head = f"{total} bulk and block deals on record; the largest is {top[0]['symbol']} ({_deal_cell(top[0].get('value_cr'), lambda n: f'₹{n:,.2f} Cr')})."
    return _finish(assemble("event_intelligence", title, as_of, head, "neutral", [table, more], src, fu, now=ctx.get("now")), as_of)


async def _company_file_answer(intent: Intent, ctx: Dict[str, Any], fu) -> Dict[str, Any]:
    """"How were TCS results?" / "What did X's management say?": one card — the result's stored AI summary, the management
    commentary, the source filings — from the company's own feed and file."""
    src: Sources = ctx["src"]
    sym = intent.symbol
    key = intent.params.get("category") or "results"
    today = _today(src)
    (feed, ferr), (file, file_err) = await asyncio.gather(
        _try(rd.filings_feed(ctx["request"], days=30, symbol=sym, limit=SYMBOL_FEED_LIMIT)),
        _try(asyncio.wait_for(rd.company_results_file(sym, today - timedelta(days=COMPANY_DAYS)), FILE_TIMEOUT_S)))
    if ferr or not isinstance(feed, dict):
        src.miss(SRC_FEED, why(ferr) if ferr else "no answer")
        feed_rows: List[Dict[str, Any]] = []
        as_of = None
    else:
        feed_rows = [r for r in feed.get("rows") or [] if isinstance(r, dict)]
        as_of = await _freshness(src, ctx["request"], feed_rows)
    if file_err or not isinstance(file, dict):
        src.missing.append(f"{SRC_FILES} ({sym}): {why(file_err) if file_err else 'no answer'}")
        file = None
    else:
        src.add(SRC_FILES, today.isoformat())
    earn = sorted((r for r in feed_rows if (r.get("category") or "").lower() == "earnings"), key=lambda r: r.get("date") or "", reverse=True)
    main = next((r for r in earn if re.search(r"outcome\s+of\s+board|financial\s+results?|results?", r.get("docLabel") or "", re.I)), earn[0] if earn else None)
    name = (file or {}).get("name") or (main or {}).get("name") or sym
    word = "results" if key == "results" else "management commentary"
    title = f"{name} · {word}"
    result_day = _ist_day(main.get("date")) if main else next((_ist_day(f.get("filed_at")) for f in sorted(
        (f for f in (file or {}).get("filings") or [] if f.get("kind") == "results"), key=lambda f: f.get("filed_at") or "", reverse=True)), None)
    if main is None and not (file and any(f.get("kind") == "results" for f in file.get("filings") or [])):
        n = notice(f"No results filing found for {sym} in the last 30 days of the exchange feed.", "info", "empty")
        return _finish(assemble("event_intelligence", title, as_of, None, "neutral", [n], src, fu, now=ctx.get("now")), as_of)
    cal_row = None
    if result_day:
        d0 = date.fromisoformat(result_day)
        cal, cerr = await _try(rd.results_rows(d0 - timedelta(days=1), d0))
        if cerr or not isinstance(cal, dict):
            src.miss(SRC_CALENDAR, why(cerr) if cerr else "no answer")
        else:
            cal_row = next((r for r in cal.get("rows") or [] if str(r.get("symbol")).upper() == sym), None)
    others = tuple(r for r in earn if r is not main)
    one = (main or {}).get("one")
    if cal_row:
        badge, tone = _verdict_badge(cal_row)               # Below / Meets / Above expectation, or "Not rated" (the classifier's read is in the commentary)
    else:
        badge, tone = _feed_badge(main) if main else (None, None)
    sub = " · ".join(x for x in ((f"Result filed {day_text(result_day)}" if result_day else None), (cal_row or {}).get("period_label"),
                                 "F&O" if (cal_row or {}).get("fno") else None) if x)
    links_ = _links_for(file, result_day, (main or {}).get("url"))
    for r in others:
        doc = r.get("docLabel") or ""
        l = lk.link("Earnings call transcript" if re.search(r"transcript", f"{doc} {r.get('one')}", re.I) else doc if 0 < len(doc) <= 40 else "Source filing", r.get("url"))
        if l and not any(x["url"] == l["url"] for x in links_):
            links_.append(l)
    card = {"title": name, "symbol": sym, "sub": sub or None, "badge": badge, "tone": tone, "body": one,
            "body_note": AI_NOTE if one else NOT_ANALYSED,
            "points": _points_for(file, (date.fromisoformat(result_day) - timedelta(days=1)).isoformat() if result_day else None, others),
            "links": links_[:5], "ask": f"Any order wins for {sym}?"}
    comm = (_result_commentary(cal_row, file) if cal_row else None) or (_feed_commentary(main) if main and one else None)
    if comm:
        card["commentary"] = comm
    blocks = [block("briefs", "events", f"{name} · latest results", "The badge rates the result Below, Meets or Above expectation where the desk has rated it "
                    "(expectation = the company's own baseline from its past quarters; no analyst consensus is held, so nothing here is a beat or a miss against the street); "
                    "without a desk rating it is an AI classifier's reading of the filing. The five-line commentary and the summaries are Nivesh's stored AI "
                    "analyses of the filings, not recommendations.", items=[card]),
              _open_intel("The company's full results file, with the price reaction and open interest, is in Market Intelligence.")]
    return _finish(assemble("event_intelligence", title, as_of, None, "neutral", blocks, src, fu, now=ctx.get("now")), as_of)


async def event_intelligence(intent: Intent, ctx: Dict[str, Any]) -> Dict[str, Any]:
    src: Sources = ctx["src"]
    key = intent.params.get("category") or "all"
    period = intent.params.get("period") or ("month" if intent.symbol else "week")
    sym = intent.symbol
    fu = follow("Which companies report results this week?", "Any order wins this week?", "Any M&A announcements today?", "Which stocks saw bulk deals today?")
    if key == "deals":
        return await _deals(intent, ctx, "", fu)
    if sym and key in ("results", "calls"):
        return await _company_file_answer(intent, ctx, fu)
    chip = CHIPS.get(key) or CHIPS["all"]
    when, days = PERIOD.get(period, PERIOD["week"])
    title = f"{(sym + ' · ' + chip['title'].lower()) if sym else chip['title']} · {when}"
    today = _today(src)

    if sym:
        feed, err = await _try(rd.filings_feed(ctx["request"], days=days, symbol=sym, limit=SYMBOL_FEED_LIMIT))
        feeds = [(feed, err)]
    else:
        queries = [dict(category=c) for c in chip.get("cats") or []] + [dict(family=f) for f in chip.get("fams") or []]
        feeds = await asyncio.gather(*(_try(rd.filings_feed(ctx["request"], days=days, limit=FEED_LIMIT, **q)) for q in queries))
    rows: List[Dict[str, Any]] = []
    total, seen, answered = 0, set(), 0
    for body, err in feeds:
        if err or not isinstance(body, dict):
            src.miss(SRC_FEED, why(err) if err else "no answer")
            continue
        answered += 1
        part = [r for r in body.get("rows") or [] if isinstance(r, dict)]
        if sym:
            part = _chip_rows(part, chip, key)
        total += len(part) if sym else int(num(body.get("total")) or len(part))
        rows += [r for r in part if r.get("id") not in seen and not seen.add(r.get("id"))]
    circulars: List[Dict[str, Any]] = []
    if key == "regulatory" and not sym:
        circ, cerr = await _try(rd.sebi_circulars(ctx["request"], days=max(days, 7), limit=50))
        if cerr or not isinstance(circ, dict):
            src.miss(SRC_CIRCULARS, why(cerr) if cerr else "no answer")
        else:
            floor = (today - timedelta(days=days - 1)).isoformat()
            circulars = [c for c in circ.get("rows") or [] if isinstance(c, dict) and c.get("title") and (iso_day(c.get("issued_on")) or "") >= floor]
            if circ.get("as_of"):
                src.add(SRC_CIRCULARS, iso_day(circ["as_of"]))
    if not answered:
        return _finish(assemble("event_intelligence", title, None, None, "neutral", [], src, fu, now=ctx.get("now")), None)
    as_of = await _freshness(src, ctx["request"], rows)
    rows = _in_period(rows, period, today)
    extra: List[Dict[str, Any]] = []
    if chip.get("missing"):
        extra.append(notice(chip["missing"], "info", "gap"))
    blocks: List[Dict[str, Any]] = []
    if rows:
        ordered = sorted(rows, key=_feed_order)[:CARD_CAP]
        cards = [_feed_card(r) for r in ordered]
        with_summary = sum(1 for c in cards if c["body"])
        blocks.append(block("briefs", "events", chip["title"] + (f" · {sym}" if sym else ""), None, items=cards))
        blocks.append(_open_intel(_plural_note(len(cards), max(total, len(rows)) if period != "today" else len(rows), chip, when, with_summary)))
        n_listed = len(rows) if period == "today" or sym else max(total, len(rows))
        summ = f"all {len(cards)}" if with_summary == len(cards) else f"{with_summary} of the {len(cards)}"
        head = f"{chip['label'][0].upper() + chip['label'][1:]} {'dated today' if period == 'today' else 'in the ' + when}: {n_listed}. {summ[0].upper() + summ[1:]} shown {'has' if with_summary == 1 and len(cards) == 1 else 'have'} an AI summary."
    else:
        head = None
        extra.append(notice(f"No {chip['label']} {'dated today' if period == 'today' else 'in the ' + when}{' for ' + sym if sym else ''} yet in the exchange feed."
                            + (" Filings appear as the exchanges publish them." if period == "today" else ""), "info", "empty"))
        if not circulars:
            extra.append(_open_intel("Everything the exchanges filed is in Market Intelligence.", "more"))
    if circulars:
        items = []
        for c in sorted(circulars, key=lambda c: str(c.get("issued_on")), reverse=True)[:CIRCULAR_CAP]:
            link = lk.link("SEBI circular", c.get("url"))
            kind = "Master circular" if (c.get("kind") or "") == "master_circular" else "Circular"
            items.append({"title": c["title"], "symbol": None, "sub": f"{day_text(iso_day(c.get('issued_on'))) or 'Date not stated'} · SEBI · {kind}",
                          "badge": None, "tone": None, "body": None, "body_note": "A SEBI circular: read it at the source; no AI summary is made for circulars.",
                          "points": [], "links": [link] if link else [], "ask": None})
        blocks.append(block("briefs", "circulars", "SEBI circulars", None, items=items))
    return _finish(assemble("event_intelligence", title, as_of, head, "neutral", extra + blocks, src, fu, now=ctx.get("now")), as_of)


BUILDERS = {"results_calendar": results_calendar, "event_intelligence": event_intelligence}
