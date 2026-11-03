"""Trade Desk › Chart Analysis › Live chart: market events drawn on the chart, and the stock's price / volume reaction to
each (contract C in test_reports/live_chart_comprehensive_TESTCASES.md). Pure: no I/O. routes/desk_chart_events.py reads
the sources and hands their rows here.

Event (one shape for every source)
    {"id", "date": "YYYY-MM-DD" (IST), "time": "HH:MM" IST | None, "kind", "scope": "stock" | "market", "title",
     "detail" | None, "source", "url" | None, "reaction": {...} | None}

Sources → kinds (what each row is; nothing is inferred beyond what the row says)
    NSE event calendar (nidp.event_calendar, DaaS /events/{symbol})
        quarterly_results → results; agm → agm; board_meeting, 'other' and the meetings that will "consider" a dividend /
        bonus / split / buyback / rights → board (the meeting, not the action). A board row on a results day is folded into
        the results event (NSE lists the same meeting under both). The calendar has no time of day: time is None.
    NSE corporate actions (nidp.corporate_actions, DaaS /corporate-actions)
        the EX-DATE of a dividend / split / bonus / buyback / rights / demerger (the day the price adjusts); a record date
        that differs is named in the detail. Bond and trust payments, mergers and other rows are not shown.
    Exchange filings (nidp.corporate_announcements, DaaS /announcements)
        each filing on its IST filing date and time; rows the classifier filed as 'regulatory' or 'other' are left out
        (the Filings feed's rule, /api/filings/feed), unclassified rows stay.
    Macro calendar (nidp.macro_releases, DaaS /desk/macro-calendar, India and US, impact H)
        on the release's IST date and usual IST time (date_ist / time).
    F&O expiry (nidp.fno_bhavcopy, DaaS /fno/{symbol}/expiries)
        the symbol's own contract expiries; a symbol without F&O contracts gets NIFTY's monthly expiries (the last NIFTY
        expiry of each month). Nothing is taken from a hard-coded calendar.
    FII / DII cash flows (nidp.fii_dii_flows, DaaS /market-pulse/fii-dii: NSE first, else Sensibull daily)
        a FLOW DAY is a session where |FII net| or |DII net| is at or above the 90th percentile of that side's |net| over
        the last 250 stored sessions (fewer when fewer are stored; `flow_rule` says how many).

Merging: events of the same kind on the same day at the same time become one (titles and details joined): two macro
releases at 18:00, two board rows of one meeting. Filings merge only when the same subject and text repeat on one day
(the same filing twice); different filings stay separate. Sorted by date, time (unknown first), kind, title.

Reaction (the chart symbol's own daily bars: nidp.prices_eod_adjusted, plus today's Kite bar when it joins, provisional)
    session            the event's own session; an event after 15:30 IST reacts on the next day's session, and a day that
                       is not a trading day (weekend, NSE holiday) on the next session
    day_change_pct     session close ÷ previous session close − 1 (%)
    next_day_change_pct  next session close ÷ session close − 1 (%), None until that session exists
    gap_pct            session open ÷ previous session close − 1 (%)
    volume_x_avg20     session volume ÷ the mean volume of the 20 sessions before it, None with fewer than 20
    provisional        True when the session's bar, or the next session's bar used above, is today's Kite bar
    None               a future event, or a day without bars: a weekday skipped between the reaction day and the
                       next bar that is not a known holiday (when the holidays could not be read, any skipped weekday)
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

IST = timezone(timedelta(hours=5, minutes=30))
NSE_CLOSE = "15:30"
DEFAULT_BACK_DAYS = 90
DEFAULT_AHEAD_DAYS = 30
MAX_SPAN_DAYS = 400
AVG_SESSIONS = 20
FLOW_SESSIONS = 250
FLOW_PERCENTILE = 90.0
FLOW_MIN_SESSIONS = 60
TEXT_MAX = 240

KINDS = ("results", "board", "agm", "dividend", "split", "bonus", "buyback", "rights", "demerger", "filing", "macro",
         "fno_expiry", "fii_dii")
KIND_ORDER = {k: i for i, k in enumerate(KINDS)}
MARKET_KINDS = frozenset({"macro", "fno_expiry", "fii_dii"})
REACTION_BASIS = "nidp.prices_eod_adjusted (+ today's Kite close, provisional)"

SRC_CALENDAR = "NSE event calendar (nidp.event_calendar)"
SRC_ACTIONS = "NSE corporate actions (nidp.corporate_actions)"
SRC_FILINGS = "filing (nidp.corporate_announcements)"
SRC_MACRO = "Macro calendar (nidp.macro_releases)"
SRC_EXPIRY = "NSE F&O bhavcopy (nidp.fno_bhavcopy), contract expiry dates"
SRC_FLOWS = "FII/DII cash-market flows (nidp.fii_dii_flows: NSE, else Sensibull daily)"

CAL_KIND = {"quarterly_results": "results", "agm": "agm", "board_meeting": "board", "other": "board", "dividend": "board",
            "bonus": "board", "split": "board", "buyback": "board", "rights": "board"}
CAL_TITLE = {"quarterly_results": "Quarterly results", "agm": "Annual general meeting", "board_meeting": "Board meeting",
             "other": "Board meeting", "dividend": "Board meeting: dividend", "bonus": "Board meeting: bonus issue",
             "split": "Board meeting: stock split", "buyback": "Board meeting: buyback", "rights": "Board meeting: rights issue"}
ACTION_KIND = {"DIVIDEND": "dividend", "SPLIT": "split", "BONUS": "bonus", "BUYBACK": "buyback", "RIGHTS": "rights",
               "DEMERGER": "demerger"}
FILING_DROPPED = frozenset({"regulatory", "other"})


# ── small helpers ────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _day(v: Any) -> Optional[str]:
    """'YYYY-MM-DD' from a date, a datetime or an ISO string; None when it is not a real date."""
    if v is None:
        return None
    s = v.isoformat() if hasattr(v, "isoformat") else str(v)
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


def _clip(v: Any, n: int = TEXT_MAX) -> Optional[str]:
    s = " ".join(str(v or "").split())
    if not s:
        return None
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _join(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """`a · b` without repeating a part either already holds."""
    parts: List[str] = []
    for s in (a, b):
        for p in (s or "").split(" · "):
            p = p.strip()
            if p and p not in parts:
                parts.append(p)
    return " · ".join(parts) or None


def _money(v: Optional[float]) -> str:
    return "" if v is None else (str(int(v)) if v == int(v) else f"{v:g}")


def pct(value: Optional[float], base: Optional[float]) -> Optional[float]:
    """(value ÷ base − 1) × 100 to 2 decimals; None when either is missing or the base is not positive."""
    if value is None or base is None or base <= 0:
        return None
    return round((value / base - 1.0) * 100.0, 2)


def ist_stamp(v: Any) -> Tuple[Optional[str], Optional[str]]:
    """(IST date, 'HH:MM' IST) of an ISO timestamp; a naive stamp is taken as UTC (the warehouse stores timestamptz)."""
    if not v:
        return None, None
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return _day(v), None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    d = d.astimezone(IST)
    return d.date().isoformat(), d.strftime("%H:%M")


def make_event(kind: str, day: str, title: str, *, source: str, time: Optional[str] = None, detail: Optional[str] = None,
               url: Optional[str] = None, key: Optional[str] = None) -> Dict[str, Any]:
    return {"id": f"{kind}:{day}" + (f":{key}" if key else ""), "date": day, "time": time, "kind": kind,
            "scope": "market" if kind in MARKET_KINDS else "stock", "title": title, "detail": detail, "source": source,
            "url": url or None, "reaction": None}


def window(frm: Optional[str], to: Optional[str], today: date) -> Tuple[date, date]:
    """[from, to] (default today − 90 days → today + 30). ValueError when a date is not real, from is after to, or the
    window is longer than MAX_SPAN_DAYS."""
    try:
        lo = date.fromisoformat(frm) if frm else today - timedelta(days=DEFAULT_BACK_DAYS)
        hi = date.fromisoformat(to) if to else today + timedelta(days=DEFAULT_AHEAD_DAYS)
    except ValueError:
        raise ValueError("from and to must be real dates (YYYY-MM-DD)") from None
    if hi < lo:
        raise ValueError("from must not be after to")
    if (hi - lo).days + 1 > MAX_SPAN_DAYS:
        raise ValueError(f"the window is at most {MAX_SPAN_DAYS} days")
    return lo, hi


def months(lo: date, hi: date) -> List[str]:
    """'YYYY-MM' of every month that [lo, hi] touches."""
    out, y, m = [], lo.year, lo.month
    while (y, m) <= (hi.year, hi.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _inside(day: Optional[str], lo: date, hi: date) -> bool:
    return day is not None and lo.isoformat() <= day <= hi.isoformat()


# ── sources → events ─────────────────────────────────────────────────────────

def from_calendar(rows: Iterable[Dict[str, Any]], lo: date, hi: date) -> List[Dict[str, Any]]:
    """NSE event-calendar rows of one symbol (event_type, event_date, period, purpose) → results / board / agm events.
    A board row on a day that has a results row is folded into the results event's detail."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        typ = str(r.get("event_type") or "").strip().lower()
        kind, d = CAL_KIND.get(typ), _day(r.get("event_date"))
        if kind is None or not _inside(d, lo, hi):
            continue
        title = CAL_TITLE[typ]
        period = _clip(r.get("period"), 40)
        if kind == "results" and period:
            title = f"{title}, {period}"
        out.append(make_event(kind, d, title, source=SRC_CALENDAR, detail=_clip(r.get("purpose"))))
    results = {e["date"]: e for e in out if e["kind"] == "results"}
    kept = []
    for e in out:
        res = results.get(e["date"])
        if e["kind"] == "board" and res is not None:
            extra = e["title"].replace("Board meeting: ", "also on the agenda: ") if e["title"] != "Board meeting" else None
            res["detail"] = _join(_join(res["detail"], e["detail"]), extra)
            continue
        kept.append(e)
    return kept


def _action_title(kind: str, r: Dict[str, Any]) -> str:
    if kind == "dividend":
        amt = _num(r.get("dividend_amount"))
        sub = _clip(r.get("action_subtype"), 30)
        base = f"Ex-dividend ₹{_money(amt)} a share" if amt is not None else "Ex-dividend"
        return f"{base} ({sub.lower()})" if sub else base
    if kind == "split":
        pre, post = _num(r.get("face_value_pre")), _num(r.get("face_value_post"))
        return f"Ex-split, face value ₹{_money(pre)} → ₹{_money(post)}" if pre is not None and post is not None else "Ex-split"
    if kind == "bonus":
        return f"Ex-bonus {r['ratio']}" if r.get("ratio") else "Ex-bonus"
    if kind == "rights":
        return f"Ex-rights {r['ratio']}" if r.get("ratio") else "Ex-rights"
    if kind == "buyback":
        return "Buyback, ex-date"
    return "Demerger, ex-date"


def from_actions(rows: Iterable[Dict[str, Any]], lo: date, hi: date) -> List[Dict[str, Any]]:
    """NSE corporate-action rows → one event on each action's ex-date (the record date when no ex-date is stored)."""
    out = []
    for r in rows:
        kind = ACTION_KIND.get(str(r.get("action_type") or "").strip().upper())
        ex, rec = _day(r.get("ex_date")), _day(r.get("record_date"))
        d = ex or rec
        if kind is None or not _inside(d, lo, hi):
            continue
        detail = _clip(r.get("purpose"))
        if ex is None:
            detail = _join(detail, "record date (no ex-date stored)")
        elif rec and rec != ex:
            detail = _join(detail, f"record date {rec}")
        out.append(make_event(kind, d, _action_title(kind, r), source=SRC_ACTIONS, detail=detail))
    return out


def _exchange(source: Any) -> str:
    s = str(source or "").strip().upper()
    return "NSE" if s.startswith("NSE_") else "BSE" if s.startswith("BSE_") else "Exchange"


def from_filings(rows: Iterable[Dict[str, Any]], lo: date, hi: date) -> List[Dict[str, Any]]:
    """Exchange announcements (announcement_id, source, filed_at, subject, description, attachment_url, event_category)
    → filing events on their IST date and time. Classified 'regulatory' / 'other' rows are left out. NSE rows first, so a
    filing repeated by BSE merges into the NSE one."""
    ordered = sorted(rows, key=lambda r: 0 if _exchange(r.get("source")) == "NSE" else 1)
    out = []
    for r in ordered:
        if str(r.get("event_category") or "").strip().lower() in FILING_DROPPED:
            continue
        d, t = ist_stamp(r.get("filed_at"))
        if not _inside(d, lo, hi):
            continue
        title = _clip(r.get("subject"), 160) or "Corporate announcement"
        detail = _clip(r.get("description"))
        out.append(make_event("filing", d, title, time=t, source=f"{_exchange(r.get('source'))} {SRC_FILINGS}",
                              detail=None if detail == title else detail, url=r.get("attachment_url"),
                              key=str(r.get("announcement_id") or "") or None))
    return out


def _fmt_value(v: Any, unit: Optional[str]) -> Optional[str]:
    f = _num(v)
    if f is None:
        return None
    u = (unit or "").strip()
    return f"{f:g}{u}" if u == "%" else (f"{f:g} {u}" if u else f"{f:g}")


def from_macro(rows: Iterable[Dict[str, Any]], lo: date, hi: date) -> List[Dict[str, Any]]:
    """Macro-calendar events (code, date_ist, time, country, short, name, period, actual, previous, unit, source,
    source_url) → macro events on the IST date and time; the same release read twice is kept once."""
    seen: Set[Tuple[str, str]] = set()
    out = []
    for r in rows:
        d = _day(r.get("date_ist") or r.get("date"))
        code = str(r.get("code") or "")
        if not _inside(d, lo, hi) or (d, code) in seen:
            continue
        seen.add((d, code))
        title = " ".join(x for x in (str(r.get("country") or "").strip(), str(r.get("short") or r.get("name") or code).strip()) if x)
        bits = [str(r.get("name") or "").strip() + (f", {r['period']}" if r.get("period") else "")]
        actual, previous = _fmt_value(r.get("actual"), r.get("unit")), _fmt_value(r.get("previous"), r.get("unit"))
        if actual:
            bits.append(f"actual {actual}")
        if previous:
            bits.append(f"previous {previous}")
        src = f"{SRC_MACRO}, {r['source']}" if r.get("source") else SRC_MACRO
        out.append(make_event("macro", d, title or "Macro release", time=r.get("time") or None, source=src,
                              detail=_clip("; ".join(b for b in bits if b)), url=r.get("source_url"), key=code or None))
    return out


def from_expiries(rows: Iterable[Dict[str, Any]], lo: date, hi: date, underlying: str, *,
                  monthly_only: bool = False, chart_symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Expiry dates of `underlying`'s listed contracts → fno_expiry events. monthly_only keeps the last expiry of each
    calendar month (NIFTY's monthly expiry, used when the chart symbol has no F&O contracts of its own)."""
    days = sorted({d for d in (_day(r.get("expiry_date")) for r in rows) if d})
    if monthly_only:
        last: Dict[str, str] = {}
        for d in days:
            last[d[:7]] = d
        days = sorted(last.values())
    out = []
    for d in days:
        if not _inside(d, lo, hi):
            continue
        if monthly_only:
            title = f"F&O expiry ({underlying} monthly)"
            detail = f"{chart_symbol or 'This symbol'} has no F&O contracts; {underlying}'s monthly contracts expire this day."
        else:
            title = "F&O expiry"
            detail = f"{underlying}'s futures and options contracts expiring this day."
        out.append(make_event("fno_expiry", d, title, source=SRC_EXPIRY, detail=detail, key=underlying))
    return out


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    """The p-th percentile by linear interpolation between the closest ranks (numpy's default); None without values."""
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p / 100.0
    f = floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def flow_rule_text(n: Optional[int] = None, first: Optional[str] = None, last: Optional[str] = None,
                   thresholds: Optional[Dict[str, Optional[float]]] = None) -> str:
    base = (f"A session where |FII net| or |DII net| (cash market, ₹ crore) is at or above the {FLOW_PERCENTILE:g}th "
            f"percentile (linear interpolation) of that side's |net| over the last {FLOW_SESSIONS} stored sessions")
    if n is None:
        return base + "."
    out = base + f"; {n} sessions used ({first} to {last})"
    if n < FLOW_SESSIONS:
        out += f", fewer than {FLOW_SESSIONS} because daily rows are stored only from {first}"
    if thresholds:
        out += "; thresholds " + ", ".join(f"{k} {v:,.0f} Cr" for k, v in thresholds.items() if v is not None)
    return out + "."


def flow_days(daily: Iterable[Dict[str, Any]], lo: date, hi: date) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
    """(flow-day events in [lo, hi], the rule as applied, why unavailable or None). `daily` rows carry date, fii_net and
    dii_net in ₹ crore. The thresholds come from the last FLOW_SESSIONS stored sessions on or before `hi`."""
    rows = sorted((r for r in daily if _day(r.get("date"))), key=lambda r: _day(r.get("date")))
    sample = [r for r in rows if _day(r.get("date")) <= hi.isoformat()][-FLOW_SESSIONS:]
    if len(sample) < FLOW_MIN_SESSIONS:
        return [], flow_rule_text(), (f"only {len(sample)} daily FII/DII sessions are stored up to {hi.isoformat()}; "
                                      f"at least {FLOW_MIN_SESSIONS} are needed for a {FLOW_PERCENTILE:g}th percentile")
    thr = {side: percentile([abs(x) for x in (_num(r.get(f"{side.lower()}_net")) for r in sample) if x is not None],
                            FLOW_PERCENTILE) for side in ("FII", "DII")}
    rule = flow_rule_text(len(sample), _day(sample[0]["date"]), _day(sample[-1]["date"]), thr)
    out = []
    for r in rows:
        d = _day(r.get("date"))
        if not _inside(d, lo, hi):
            continue
        nets = {side: _num(r.get(f"{side.lower()}_net")) for side in ("FII", "DII")}
        big = [s for s in ("FII", "DII") if nets[s] is not None and thr[s] is not None and abs(nets[s]) >= thr[s]]
        if not big:
            continue
        title = " · ".join(f"{s} {nets[s]:+,.0f} Cr" for s in big)
        detail = ("Cash-market net, ₹ crore: " + ", ".join(f"{s} {nets[s]:+,.2f}" for s in ("FII", "DII") if nets[s] is not None)
                  + "; at or above the threshold: " + ", ".join(f"{s} ({thr[s]:,.0f} Cr)" for s in big) + ".")
        out.append(make_event("fii_dii", d, title, source=SRC_FLOWS, detail=detail))
    return out, rule, None


# ── merge ────────────────────────────────────────────────────────────────────

def _merge_key(e: Dict[str, Any]) -> tuple:
    if e["kind"] == "filing":
        return (e["date"], "filing", e["title"].lower(), (e["detail"] or "").lower())
    return (e["date"], e["kind"], e["time"] or "")


def merge(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One event per (day, kind, time) — per (day, subject, text) for filings — then sorted; ids made unique."""
    out: Dict[tuple, Dict[str, Any]] = {}
    for e in events:
        k = _merge_key(e)
        m = out.get(k)
        if m is None:
            out[k] = dict(e)
            continue
        m["title"] = _join(m["title"], e["title"]) or m["title"]
        m["detail"] = _join(m["detail"], e["detail"])
        m["url"] = m["url"] or e["url"]
    res = sorted(out.values(), key=lambda e: (e["date"], e["time"] or "", KIND_ORDER.get(e["kind"], 99), e["title"]))
    seen: Dict[str, int] = {}
    for e in res:
        n = seen.get(e["id"], 0)
        seen[e["id"]] = n + 1
        if n:
            e["id"] = f"{e['id']}#{n + 1}"
    return res


# ── reactions ────────────────────────────────────────────────────────────────

def reaction_day(day: str, time: Optional[str]) -> date:
    """The calendar day whose session (or the first one after it) reacts: the next day for an event after 15:30 IST."""
    d = date.fromisoformat(day)
    return d + timedelta(days=1) if time and time > NSE_CLOSE else d


def session_index(dates: Sequence[str], rd: date, holidays: Optional[Set[date]]) -> Optional[int]:
    """Index of the bar of the first session on or after `rd`, or None (no bar yet, or a weekday skipped on the way that
    is not a known holiday — a day without bars, not a day without a session)."""
    i = bisect_left(dates, rd.isoformat())
    if i >= len(dates):
        return None
    s, d = date.fromisoformat(dates[i]), rd
    while d < s:
        if d.weekday() < 5 and (holidays is None or d not in holidays):
            return None
        d += timedelta(days=1)
    return i


def reaction(bars: Sequence[Sequence[Any]], i: int, kite_day: Optional[str]) -> Dict[str, Any]:
    """The reaction at bar i of [[day, o, h, l, c, v]] (oldest first)."""
    o, c, v = _num(bars[i][1]), _num(bars[i][4]), _num(bars[i][5])
    prev = _num(bars[i - 1][4]) if i > 0 else None
    nxt = _num(bars[i + 1][4]) if i + 1 < len(bars) else None
    vols = [_num(b[5]) for b in bars[i - AVG_SESSIONS:i]] if i >= AVG_SESSIONS else []
    avg = sum(vols) / len(vols) if vols and all(x is not None for x in vols) else None
    used = [str(bars[i][0])[:10]] + ([str(bars[i + 1][0])[:10]] if nxt is not None else [])
    return {"basis": REACTION_BASIS, "session": str(bars[i][0])[:10], "day_change_pct": pct(c, prev),
            "next_day_change_pct": pct(nxt, c), "gap_pct": pct(o, prev),
            "volume_x_avg20": round(v / avg, 2) if v is not None and avg else None,
            "provisional": bool(kite_day) and kite_day in used}


def attach_reactions(events: List[Dict[str, Any]], bars: Sequence[Sequence[Any]], *, kite_day: Optional[str] = None,
                     holidays: Optional[Set[date]] = None) -> List[Dict[str, Any]]:
    """Each event with its reaction from `bars` (None when there is no session bar for it, see `session_index`)."""
    dates = [str(b[0])[:10] for b in bars]
    for e in events:
        i = session_index(dates, reaction_day(e["date"], e["time"]), holidays) if dates else None
        e["reaction"] = reaction(bars, i, kite_day) if i is not None else None
    return events
