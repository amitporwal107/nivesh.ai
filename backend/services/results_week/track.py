"""Results This Week (docs/EARNINGS_SURPRISE_TRACKER.md §9): cash and F&O positioning before and after a result.

Before / after snapshots ("Snap") for the watchlist rows (§9a), and the per-stock session track from 5 sessions before the
first reaction session to the latest loaded (§9b). Pure functions here; the reads are the existing loaders (DaaS
/desk/fno-buildup — total futures OI over every expiry and the cash close, one call per date for every stock — and app
Postgres stock_ohlcv). Nothing is guessed: a missing figure is null with a note.

The expiry trap: when the window spans a monthly expiry, total OI falls because unrolled contracts expire, so a falling-OI
state there is labelled, never read as short covering or long unwinding (§4c expiry-week dampening, same reason).
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import scoring as sc

TRACK_BEFORE = 5            # sessions before the first reaction session
TRACK_AFTER = 5             # sessions from the first reaction session on (rel 0 … 4), up to the latest loaded
VOLUME_BASE_SESSIONS = 20   # volume × = the session's volume ÷ the mean of the 20 sessions before the track starts
EXPIRY_NOTE = ("spans a monthly expiry: total OI is not comparable across it (the expiring month still counts on expiry day while the next month fills, then drops out); read the carry against the stock's own past expiries instead")
CARRY_NORMAL_PP = 3.0     # within ±3 pts of its own past expiry-day carry = normal rollover


def _spot(row: Optional[Dict[str, Any]]) -> Optional[float]:
    return sc.num((row or {}).get("cash_close"))


def snap_day(day: Optional[str], row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """One session's own build-up (that day's change) from a /desk/fno-buildup row."""
    if not row:
        return None
    t = sc.total_block(row, None, None)
    if not t:
        return None
    st = t["state_1s"]
    return {"date": day, "state": st, "text": sc.BUILDUP_TEXT.get(st, "no clear signal") if st else None,
            "price_pct": t["price_chg_pct_1s"], "oi_pct": t["oi_chg_pct_1s"], "span": "1 session"}


def snap_span(d0: str, row0: Optional[Dict[str, Any]], d1: str, row1: Optional[Dict[str, Any]],
              expiries: Sequence[date]) -> Optional[Dict[str, Any]]:
    """Cumulative change from the close of d0 to the close of d1 (spot and total OI)."""
    if not row0 or not row1:
        return None
    p = sc.pct_change(_spot(row1), _spot(row0))
    o = sc.pct_change(sc.num(row1.get("oi")), sc.num(row0.get("oi")))
    st = sc.oi_state(p, o)
    a, b = date.fromisoformat(d0), date.fromisoformat(d1)
    crosses = any(a < e <= b for e in expiries)
    out = {"date": d1, "since": d0, "state": st, "text": sc.BUILDUP_TEXT.get(st, "no clear signal") if st else None,
           "price_pct": sc.r2(p), "oi_pct": sc.r2(o), "span": f"{d0} close → {d1} close", "note": None,
           "oi_comparable": not crosses, "carry_vs_usual_pp": None}
    if crosses:
        # On and around an expiry total OI is not comparable either way: the expiring month still counts on expiry day
        # while the next month fills, then drops out. The state is not read; the carry against the stock's own past
        # expiries (carry_text) is the reading to use.
        out["note"] = EXPIRY_NOTE
        out["state"] = None
        out["text"] = "spans an expiry: OI not comparable"
    return out


def carry_text(rollover: Optional[Dict[str, Any]]) -> Optional[str]:
    """The standard rollover reading on an expiry day: the share of futures OI already in later months, against the
    stock's own mean of the same reading on its last expiries."""
    pp = roll_carry(rollover)
    if pp is None:
        return None
    pct = sc.num((rollover or {}).get("pct"))
    usual = pct - pp if pct is not None else None
    word = "normal" if abs(pp) < CARRY_NORMAL_PP else ("higher than usual" if pp > 0 else "lower than usual")
    return f"rollover {pct:.1f} % vs its usual {usual:.1f} % ({word})" if pct is not None and usual is not None else None


def pre_session(first: Optional[date], sessions: Sequence[date]) -> Optional[date]:
    """The last session before the first reaction session."""
    if first is None:
        return None
    before = [s for s in sorted(sessions) if s < first]
    return before[-1] if before else None


def fno_track(row: Dict[str, Any], sessions: Sequence[date], latest: Optional[date],
              by_day: Dict[str, Dict[str, Dict[str, Any]]], expiries: Sequence[date]) -> Optional[Dict[str, Any]]:
    """§9a: {before, after} for an F&O row. by_day = {iso date: {symbol: build-up row}}."""
    if not row.get("fno"):
        return None
    sym = str(row.get("symbol") or "").upper()
    first = _first_reaction(row, sessions)
    lat = latest.isoformat() if latest else None
    if first is None or (latest is not None and first > latest):
        # not reacted yet (upcoming, or filed after the latest loaded session): "before" is the positioning so far
        return {"before": snap_day(lat, (by_day.get(lat) or {}).get(sym)) if lat else None, "after": None}
    pre = pre_session(first, sessions)
    if pre is None:
        return {"before": None, "after": None}
    p = pre.isoformat()
    before = snap_day(p, (by_day.get(p) or {}).get(sym))
    after = snap_span(p, (by_day.get(p) or {}).get(sym), lat, (by_day.get(lat) or {}).get(sym), expiries) if lat else None
    if after and not after["oi_comparable"]:
        rb = row.get("fno_buildup") or {}
        if str(rb.get("as_of") or "")[:10] == lat:
            after["carry_vs_usual_pp"] = roll_carry(rb.get("rollover"))
            after["text"] = carry_text(rb.get("rollover")) or after["text"]
    return {"before": before, "after": after}


def _first_reaction(row: Dict[str, Any], sessions: Sequence[date]) -> Optional[date]:
    fs = ((row.get("reaction") or {}).get("first_session"))
    if fs:
        try:
            return date.fromisoformat(str(fs)[:10])
        except ValueError:
            pass
    ts = sc.parse_ts(row.get("filed_at"))
    return sc.first_session(ts, sessions) if ts else None


def window(first: Optional[date], event_date: Optional[date], sessions: Sequence[date],
           latest: Optional[date]) -> Tuple[Optional[date], List[Tuple[int, date]]]:
    """(anchor, [(rel, session)]) — rel 0 = the first reaction session, or for an upcoming meeting the meeting day's
    session; from rel −5 to rel +4, never past the latest loaded session."""
    ss = sorted(sessions)
    anchor = first
    if anchor is None and event_date is not None:
        anchor = next((s for s in ss if s >= event_date), None)
    if anchor is None:
        return None, []
    before = [s for s in ss if s < anchor][-TRACK_BEFORE:]
    after = [s for s in ss if s >= anchor][:TRACK_AFTER]
    out = [(i - len(before), s) for i, s in enumerate(before)] + [(i, s) for i, s in enumerate(after)]
    if latest is not None:
        out = [(r, s) for r, s in out if s <= latest]
    return anchor, out


def session_rows(win: Sequence[Tuple[int, date]], sym: str, bars: Dict[date, Tuple[Optional[float], Optional[float]]],
                 nifty: Dict[date, float], by_day: Dict[str, Dict[str, Dict[str, Any]]], sessions: Sequence[date],
                 vol_base: Optional[float], expiries: Sequence[date] = ()) -> List[Dict[str, Any]]:
    """§9b track.sessions (without the per-day contract extras, added by the caller). A session whose one-day OI change
    straddles a monthly expiry (the expiry day itself, or the session after it) has no state: OI is not comparable."""
    exp = set(expiries)
    ss = sorted(sessions)
    out = []
    for rel, d in win:
        prev = next((s for s in reversed(ss) if s < d), None)
        c, v = (bars.get(d) or (None, None))
        cp = (bars.get(prev) or (None, None))[0] if prev else None
        chg = sc.pct_change(c, cp)
        n_chg = sc.pct_change(nifty.get(d), nifty.get(prev)) if prev else None
        bu = (by_day.get(d.isoformat()) or {}).get(sym)
        fut = None
        if bu:
            t = sc.total_block(bu, None, None)
            straddles = d in exp or (prev is not None and prev in exp)
            st = None if straddles else (t["state_1s"] if t else None)
            fut = {"total_oi": sc.num(bu.get("oi")), "oi_pct": t["oi_chg_pct_1s"] if t else None,
                   "near_price": sc.num(bu.get("close") if bu.get("close") is not None else bu.get("fut_close")),
                   "price_pct": t["price_chg_pct_1s"] if t else None, "state": st,
                   "text": ("expiry: OI not comparable" if straddles else
                            (sc.BUILDUP_TEXT.get(st, "no clear signal") if st else None)),
                   "oi_comparable": not straddles,
                   "next_premium_pct": None, "expiry_day": d in exp, "carry_vs_usual_pp": None}
        out.append({"date": d.isoformat(), "rel": rel, "close": c, "chg_pct": sc.r2(chg),
                    "excess_pct": sc.r2(chg - n_chg) if chg is not None and n_chg is not None else None,
                    "volume_x": sc.r1(v / vol_base) if v is not None and vol_base else None, "fut": fut, "pcr_next": None})
    return out


def volume_base(bars: Dict[date, Tuple[Optional[float], Optional[float]]], start: date, sessions: Sequence[date]) -> Optional[float]:
    prior = [s for s in sorted(sessions) if s < start][-VOLUME_BASE_SESSIONS:]
    vols = [bars[s][1] for s in prior if s in bars and bars[s][1] is not None]
    return sum(vols) / len(vols) if len(vols) >= 5 else None


def roll_carry(rollover: Optional[Dict[str, Any]]) -> Optional[float]:
    """On an expiry day: today's share of OI in later months minus the stock's own mean of the same reading on its last
    expiries (percentage points). None without past readings."""
    if not rollover:
        return None
    pct = sc.num(rollover.get("pct"))
    past = [sc.num(h.get("pct")) for h in rollover.get("past") or []]
    past = [p for p in past if p is not None]
    if pct is None or not past:
        return None
    return sc.r1(pct - sum(past) / len(past))


def pcr(options: Sequence[Dict[str, Any]]) -> Optional[float]:
    put = sum(sc.num(r.get("open_interest")) or 0 for r in options or [] if str(r.get("option_type")).upper() == "PE")
    call = sum(sc.num(r.get("open_interest")) or 0 for r in options or [] if str(r.get("option_type")).upper() == "CE")
    return sc.r2(put / call) if call else None


def next_premium(futures: Sequence[Dict[str, Any]], day: date) -> Optional[float]:
    """The next monthly future's premium over spot on `day` (the first expiry after the nearest one when the nearest is
    `day` itself or earlier, else the nearest)."""
    legs = sc._contract_day(futures)
    legs = [r for r in legs if str(r.get("expiry_date") or "")[:10] > day.isoformat()]
    if not legs:
        return None
    r = legs[0]
    return sc.r2(sc.pct_change(sc.num(r.get("close_price")), sc.num(r.get("underlying_price"))))
