"""Results week — one day's answer for GET /api/desk/results-week (docs/EARNINGS_SURPRISE_TRACKER.md §5).

build_day reads every source (services/results_week/loaders) and applies the §4 rules (scoring). It writes nothing and
needs no user: the per-user Chartink column is joined afterwards (join_chartink), so the same body serves the live
route and the nightly snapshot (scripts/build_results_week.py). The live route rebuilds at most every few minutes.

The results list is the date's week (Monday .. Saturday). The ideas also look 3 sessions back ("declared": filed in the
last 3 sessions) and 5 sessions ahead ("upcoming"), so on a Monday last Thursday's late filers still count, and on a
Friday next week's meetings do; those extra meetings are ordered but not listed in `results` or `counts`.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import loaders, scoring as sc, track

IST = sc.IST
STATUS_ORDER = {"declared": 0, "pending": 1, "upcoming": 2}
CALENDAR_PAD_DAYS = 21
CALENDAR_BACK_DAYS = 200            # the rollover comparison reads the stock's last 5 expiries
PRICE_LOOKBACK_DAYS = 45            # ≥ 20 sessions before the earliest first session, for volume ×
ANALYSIS_BEFORE_DAYS, ANALYSIS_AFTER_DAYS = 1, 4   # filing analyses with event_ts in [meeting − 1 day, meeting + 4 days)
SCHEMA = "results-week-v1"


def status_of(ev: Dict[str, Any]) -> str:
    """declared (figures stored) · pending (meeting held / outcome filed, figures not stored yet) · upcoming."""
    if ev.get("status") == "declared":
        return "declared" if ev.get("filed_state") == "figures" else "pending"
    return "upcoming"


def filed_at_of(ev: Dict[str, Any], exchange: Sequence[datetime] = ()) -> Optional[datetime]:
    """When the market could know: the earliest of the outcome filing's time, the figures' broadcast time and the first
    results filing on the exchange dated the meeting day or the day after (IST)."""
    cands = [sc.parse_ts((ev.get("filing") or {}).get("filed_at"))]
    ev_d = _ev_date(ev)
    if ev_d:
        cands += [t for t in exchange if ev_d <= t.astimezone(IST).date() <= ev_d + timedelta(days=1)]
    for m in ev.get("metrics") or []:
        if isinstance(m, dict) and isinstance(m.get("filed"), dict):
            cands.append(sc.parse_ts(m["filed"].get("broadcast_at")))
    cands = [c for c in cands if c is not None]
    return min(cands) if cands else None


def pick_analysis(docs: Sequence[Dict[str, Any]], ev_date: date, cutoff: datetime) -> Optional[Dict[str, Any]]:
    """The most material RESULTS analysis of this meeting known by `cutoff` (then the latest analysed)."""
    lo = datetime.combine(ev_date - timedelta(days=ANALYSIS_BEFORE_DAYS), time(0), IST)
    hi = min(cutoff, datetime.combine(ev_date + timedelta(days=ANALYSIS_AFTER_DAYS), time(0), IST))
    keep = []
    for d in docs or []:
        ts, at = sc.parse_ts(d.get("event_ts")), sc.parse_ts(d.get("analyzed_at"))
        if ts is None or not (lo <= ts < hi) or (at is not None and at > cutoff):
            continue
        keep.append(d)
    if not keep:
        return None
    floor = datetime.min.replace(tzinfo=timezone.utc)
    return max(keep, key=lambda d: (sc.num(d.get("materiality_score")) or -1.0, sc.parse_ts(d.get("analyzed_at")) or floor))


def _ev_date(ev: Dict[str, Any]) -> Optional[date]:
    try:
        return date.fromisoformat(str(ev.get("event_date"))[:10])
    except ValueError:
        return None


def assemble_row(ev: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """One results row from the meeting's DaaS row and the loaded context (pure: no I/O)."""
    sym = str(ev.get("symbol")).upper()
    status = status_of(ev)
    ev_d = _ev_date(ev)
    gaps: List[str] = [g for g in ev.get("gaps") or [] if isinstance(g, str)]
    is_fno = bool((ev.get("universe") or {}).get("fno"))
    target = sc.period_end_of(ev.get("period_label"))

    # §4a surprise and the headline verdict
    surp = sc.surprise(ev.get("metrics") or [])
    if status == "pending":
        surp["value"], surp["used"], surp["weights"], surp["z"] = None, [], {}, None
        surp["verdict"] = {"label": None, "intensity": None, "reason": sc.REASON_PENDING}
    elif status == "upcoming":
        surp["value"], surp["used"], surp["weights"], surp["z"] = None, [], {}, None
        surp["verdict"] = {"label": None, "intensity": None, "reason": sc.REASON_UPCOMING}
    verdict = surp.pop("verdict")
    if status == "declared":
        for k in sc.METRICS:
            r = surp["metrics"][k]
            if r.get("reason"):
                gaps.append(f"{'PAT' if k == 'pat' else 'revenue'} {r['reason']}")

    # operating trend and quality, from the stored quarters
    fin = ctx["fin"].get(sym)
    if fin is None:
        quarter, why = None, ctx["fin_gaps"].get(sym) or ("not read" if status == "pending" else "quarterly results not read")
    else:
        quarter, why = sc.pick_quarter(fin, target, declared=status != "upcoming")
    if fin is not None or status != "pending":
        if why:
            gaps.append(f"operating trend: {why}")
    tr = sc.trend(fin or [], quarter)
    tr["basis"] = "declared quarter" if status != "upcoming" else "latest stored quarter before the meeting"
    if status == "upcoming":
        ql = {"value": None, "flags": [], "checked": [], "not_checked": [], "quarter": None, "reason": "results not declared yet"}
    else:
        ql = sc.quality(fin or [], quarter)
        ql["quarter"] = tr["quarter"]

    # outlook (filing analysis)
    doc = None
    if status == "upcoming":
        ol = sc.outlook(None, declared=False)
    elif ctx["analysis_gap"]:
        ol = sc.outlook(None, read_failed=True)
    else:
        doc = pick_analysis(ctx["analysis"].get(sym) or [], ev_d, ctx["cutoff"]) if ev_d else None
        ol = sc.outlook(doc)
        if doc is None:
            gaps.append("outlook: not analysed (no filing analysis of these results)")

    comps: Dict[str, Any] = {"surprise": surp, "trend": tr, "outlook": ol, "quality": ql}

    # §4b composite — declared results only
    if status == "declared":
        score = sc.composite({"surprise": surp["value"], "trend": tr["value"], "outlook": ol["value"], "quality": ql["value"]})
    else:
        score = {"value": None, "band": None, "coverage": {"present": [], "missing": list(sc.COMPOSITE_WEIGHTS)}, "weights": {},
                 "reason": "figures pending" if status == "pending" else "results not declared yet"}

    # past results reactions — upcoming only (the early-signal order uses them)
    if status == "upcoming":
        if sym in ctx["hist"]:
            comps["past_reactions"] = sc.past_reactions(ctx["hist"][sym])
        else:
            comps["past_reactions"] = None
            gaps.append(f"past results reactions: {ctx['hist_gaps'].get(sym) or 'not read'}")

    # reaction vs Nifty — once the outcome is filed. Figures not stored yet: the analysed filing's own time stands in
    filed_at = filed_at_of(ev, (ctx.get("exchange_filings") or {}).get(sym) or ())
    if filed_at is None and doc is not None:
        filed_at = sc.parse_ts(doc.get("event_ts"))
    reaction = None
    if status != "upcoming":
        if ctx["prices_gap"]:
            gaps.append(f"reaction: {ctx['prices_gap']}")
        elif ctx["nifty_gap"]:
            gaps.append(f"reaction: {ctx['nifty_gap']}")
        else:
            reaction, g = sc.reaction(filed_at, ctx["sessions"], ctx["prices"].get(sym) or {}, ctx["nifty"])
            if g:
                gaps.append(g)

    # OI across the coming months — F&O names only
    fb = None
    if is_fno:
        if ctx["buildup_gap"] and not ctx["buildup"]:
            gaps.append(ctx["buildup_gap"])
        else:
            dp = ctx.get("deep", {}).get(sym) or {}
            fb, g = sc.fno_block(True, as_of=ctx["buildup_as_of"], scan_row=ctx["buildup"].get(sym),
                                 back_row=(ctx.get("back_rows") or {}).get(sym), back_date=ctx.get("back_date"),
                                 futures=dp.get("futures"), options=dp.get("options"), options_exp=dp.get("options_exp"),
                                 past=dp.get("past") or [], day=ctx.get("fno_day"), sessions=ctx["sessions"])
            gaps += g
            if ctx.get("deep_gaps", {}).get(sym):
                gaps.append(f"OI build-up: {ctx['deep_gaps'][sym]}")

    # technicals — the AI scanner's latest row
    tech = None
    if ctx["tech_gap"]:
        gaps.append(ctx["tech_gap"])
    else:
        tech = sc.technical_block(ctx["tech"].get(sym))
        if tech is None:
            gaps.append("technical: no AI scanner row within a week of the date")

    evidence = []
    f = ev.get("filing") or {}
    if f.get("url"):
        t = sc.parse_ts(f.get("filed_at"))
        when = f" (filed {t.astimezone(IST).strftime('%d %b %H:%M')} IST)" if t else ""
        evidence.append({"label": f"{f.get('subject') or 'Exchange filing'} — NSE{when}", "url": f["url"]})

    return {
        "id": ev.get("id"), "symbol": sym, "name": ev.get("name"), "sector": ev.get("sector"),
        "event_date": ev.get("event_date"), "status": status, "fno": is_fno, "period_label": ev.get("period_label"),
        "basis": ev.get("basis"), "filed_at": filed_at.isoformat() if filed_at else None,
        "verdict": verdict, "score": score, "components": comps,
        "reaction": reaction, "fno_buildup": fb, "technical": tech, "chartink": None,
        "evidence": evidence, "gaps": list(dict.fromkeys(gaps)),
    }


def counts_of(results: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    c = {"declared": 0, "declared_pending": 0, "upcoming": 0, "above": 0, "in_line": 0, "below": 0, "not_rated": 0}
    for r in results:
        if r["status"] == "declared":
            c["declared"] += 1
            c[r["verdict"]["label"] or "not_rated"] += 1
        elif r["status"] == "pending":
            c["declared_pending"] += 1
        else:
            c["upcoming"] += 1
    return c


def plan_windows(day: date, sess: Sequence[date]) -> Tuple[Tuple[date, date], List[Tuple[date, date]], List[Tuple[date, date]]]:
    """((Monday, Saturday), the week's windows, the extra windows for the ideas' look-back / look-ahead)."""
    mon, sat = loaders.week_of(day)
    past = [s for s in sess if s <= day][-sc.DECLARED_SESSIONS:]
    ahead = [s for s in sess if s > day][:sc.UPCOMING_SESSIONS]
    extra: List[Tuple[date, date]] = []
    if past and past[0] < mon:
        extra += loaders.windows(past[0], mon - timedelta(days=1))
    if ahead and ahead[-1] > sat:
        extra += loaders.windows(sat + timedelta(days=1), ahead[-1])
    return (mon, sat), loaders.windows(mon, sat), extra


async def build_day(day: date, *, now: Optional[datetime] = None, live: bool = True, db=None) -> Dict[str, Any]:
    """The day's answer, without the Chartink column. Raises loaders.SourceUnavailable when the results calendar cannot
    be read at all. `live` lets the OI build-up fall back to the newest loaded day (labelled); the snapshot does not.
    Every DaaS read of the build shares one keep-alive client (loaders.pooled)."""
    async with loaders.pooled():
        return await _build_day(day, now=now, live=live, db=db)


async def attach_fno_track(rows: List[Dict[str, Any]], sess: Sequence[date], fno_day: Optional[date],
                           bu: Dict[str, Dict[str, Any]], fno_syms: Sequence[str], gaps: List[str]) -> None:
    """§9a: `fno_track` {before, after} on every F&O row (null on the others). One cached /desk/fno-buildup read per
    distinct "session before the first reaction session", plus the latest (already read as `bu`). The expiry list comes
    from one underlying's expiries (the monthly expiry is market-wide); its failure only drops the expiry note."""
    for r in rows:
        r["fno_track"] = None
    if not fno_day or not fno_syms:
        return
    by_day: Dict[str, Dict[str, Dict[str, Any]]] = {fno_day.isoformat(): bu}
    pres = set()
    for r in rows:
        if r.get("fno"):
            first = track._first_reaction(r, sess)
            pre = track.pre_session(first, sess) if first and first <= fno_day else None
            if pre and pre.isoformat() not in by_day:
                pres.add(pre)
    reads = await asyncio.gather(*(loaders.buildup(d, fallback=False) for d in sorted(pres)), return_exceptions=True)
    missing = []
    for d, res in zip(sorted(pres), reads):
        if isinstance(res, BaseException) or not res[0]:
            missing.append(d.isoformat())
            continue
        by_day[d.isoformat()] = res[0]
    if missing:
        gaps.append(f"F&O before-results snapshots could not be read for {', '.join(missing)}")
    try:
        expiries = await loaders.fno_expiries(fno_syms[0])
    except Exception:  # noqa: BLE001
        expiries = []
        gaps.append("F&O expiry list could not be read: a window spanning an expiry is not labelled")
    for r in rows:
        if r.get("fno"):
            r["fno_track"] = track.fno_track(r, sess, fno_day, by_day, expiries)


async def _build_day(day: date, *, now: Optional[datetime], live: bool, db) -> Dict[str, Any]:
    if db is None:
        from deps import db as _db
        db = _db
    now = now or datetime.now(timezone.utc)
    cutoff = min(now, datetime.combine(day + timedelta(days=1), time(0), IST))
    gaps: List[str] = []

    sess, cal_gap = await loaders.sessions(day - timedelta(days=CALENDAR_BACK_DAYS), day + timedelta(days=CALENDAR_PAD_DAYS))
    if cal_gap:
        gaps.append(cal_gap)
    (mon, sat), week_wins, extra_wins = plan_windows(day, sess)
    events, win_meta, first, exp_gaps = await loaders.expectations(week_wins + extra_wins)
    gaps += exp_gaps
    seen, evs = set(), []
    for e in events:
        key = e.get("id") or f"{e.get('event_date')}|{e.get('symbol')}"
        if key not in seen:
            seen.add(key)
            evs.append(e)

    stat = {id(e): status_of(e) for e in evs}
    syms_all = list(dict.fromkeys(str(e["symbol"]).upper() for e in evs))
    fin_syms = {str(e["symbol"]).upper(): e.get("basis") != "standalone" for e in evs if stat[id(e)] != "pending"}
    up_syms = [str(e["symbol"]).upper() for e in evs if stat[id(e)] == "upcoming"]
    filed_syms = [str(e["symbol"]).upper() for e in evs if stat[id(e)] != "upcoming"]
    ev_dates = [d for d in (_ev_date(e) for e in evs) if d]
    lo = min(ev_dates + [mon])
    a_start = datetime.combine(lo - timedelta(days=ANALYSIS_BEFORE_DAYS), time(0), IST)
    a_end = min(cutoff, datetime.combine(max(ev_dates + [day]) + timedelta(days=ANALYSIS_AFTER_DAYS), time(0), IST))

    (fin, fin_gaps, fin_src), (hist, hist_gaps, hist_src), (bu, bu_as_of, bu_gap), (nf, nf_gap), \
        (an, an_gap), (px, px_gap), (tech, tech_gap) = await asyncio.gather(
            loaders.quarterly(fin_syms),
            loaders.history(up_syms),
            loaders.buildup(day, fallback=live),
            loaders.nifty(lo - timedelta(days=PRICE_LOOKBACK_DAYS), day),
            loaders.filing_analysis(db, filed_syms, a_start, a_end),
            loaders.prices(filed_syms, lo - timedelta(days=PRICE_LOOKBACK_DAYS), day),
            loaders.technicals(syms_all, day),
        )
    exch, exch_gap = await loaders.first_results_filings(lo - timedelta(days=1), min(day, max(ev_dates + [day])) + timedelta(days=1))
    if exch_gap:
        gaps.append(exch_gap)
    for g in (fin_src, hist_src, bu_gap, nf_gap, an_gap, px_gap, tech_gap):
        if g:
            gaps.append(g)

    # OI across the coming months, F&O names only: the build-up scan 3 sessions back (total OI) and, per underlying,
    # the day's futures of every expiry, one options expiry and (in the rollover window) its past expiries.
    fno_day = date.fromisoformat(bu_as_of) if bu_as_of else None
    fno_syms = list(dict.fromkeys(str(e["symbol"]).upper() for e in evs if (e.get("universe") or {}).get("fno")))
    back_rows, back_date, deep, deep_gaps = {}, None, {}, {}
    if fno_day and fno_syms:
        before = [s for s in sess if s < fno_day]
        back_date = before[-3].isoformat() if len(before) >= 3 else None
        async def no_back():
            return {}, None, None
        (back_rows, _b_as_of, back_gap), (deep, deep_gaps) = await asyncio.gather(
            loaders.buildup(date.fromisoformat(back_date), fallback=False) if back_date else no_back(),
            loaders.fno_deep(fno_syms, fno_day, sess))
        if back_gap:
            gaps.append(f"3-session total OI: {back_gap}")
        if fno_syms and len(deep_gaps) == len(fno_syms):
            gaps.append("OI by expiry: the futures contracts could not be read for any F&O stock")
    ctx = {"exchange_filings": exch, "fin": fin, "fin_gaps": fin_gaps, "hist": hist, "hist_gaps": hist_gaps, "buildup": bu, "buildup_as_of": bu_as_of,
           "buildup_gap": bu_gap, "nifty": nf, "nifty_gap": nf_gap, "analysis": an, "analysis_gap": an_gap,
           "prices": px, "prices_gap": px_gap, "tech": tech, "tech_gap": tech_gap, "sessions": sess, "cutoff": cutoff,
           "fno_day": fno_day, "back_rows": back_rows, "back_date": back_date, "deep": deep, "deep_gaps": deep_gaps}

    rows = [assemble_row(e, ctx) for e in evs]
    await attach_fno_track(rows, sess, fno_day, bu, fno_syms, gaps)
    in_week = [r for r in rows if r["event_date"] and mon.isoformat() <= str(r["event_date"])[:10] <= sat.isoformat()]
    in_week.sort(key=lambda r: (STATUS_ORDER[r["status"]], str(r["event_date"]), r["symbol"]))
    fno_ideas = sc.order_ideas(rows, day, sess, fno_list=True)
    all_ideas = sc.order_ideas(rows, day, sess, fno_list=False)
    tech_dates = sorted({str(t.get("as_of_date"))[:10] for t in tech.values() if t.get("as_of_date")})

    sources = {
        "expectations": {"source": "DaaS /desk/events-calendar/expectations (universe all, windows of at most 3 days)",
                         "ok": all(m["ok"] for m in win_meta), "week_windows": win_meta[:len(week_wins)],
                         "extra_windows": win_meta[len(week_wins):], "label": first.get("label"),
                         "method": (first.get("method") or {}).get("name"), "formula": (first.get("method") or {}).get("formula")},
        "financials": {"source": "DaaS /financials/{symbol} (period_type quarterly; nidp.nse_financials_quarterly)",
                       "ok": fin_src is None, "read": len(fin), "failed": len(fin_gaps)},
        "filing_analysis": {"source": "Mongo event_ai_analysis (event_type containing RESULT; single_full / *_compact; tools off, isolated)",
                            "label": sc.OUTLOOK_LABEL, "ok": an_gap is None, "stocks_analysed": len(an)},
        "history": {"source": "DaaS /desk/events-calendar/history (type RESULTS): the stock's own close on past results days and "
                              "the next session; past behaviour, not a forecast", "ok": hist_src is None,
                    "read": len(hist), "failed": len(hist_gaps)},
        "prices": {"source": "app Postgres stock_ohlcv (close, volume)", "ok": px_gap is None, "stocks": len(px),
                   "reaction_basis": "first session after the filing (filed at or after 15:30 IST → the next session), "
                                     "close to close, minus Nifty 50's return the same session; volume × vs the mean of up to 20 earlier sessions"},
        "nifty": {"source": "DaaS /indices/Nifty 50/eod", "ok": nf_gap is None,
                  "latest": max(nf).isoformat() if nf else None},
        "fno_buildup": {"source": "NSE F&O bhavcopy via DaaS: /desk/fno-buildup (total OI over every expiry, cash close) and "
                                  "/fno/{symbol} (futures of every expiry, one options expiry)",
                        "ok": bool(bu), "as_of": bu_as_of, "rows": len(bu), "back_date": back_date,
                        "deep_read": len(deep) - len(deep_gaps), "deep_failed": len(deep_gaps),
                        "thresholds": {"min_abs_price_chg_pct": sc.FNO_MIN_PRICE_PCT, "min_abs_oi_chg_pct": sc.FNO_MIN_OI_PCT},
                        "headline": "total futures OI across every expiry vs the spot, last session",
                        "rollover": f"read in the {sc.ROLLOVER_WINDOW_SESSIONS} sessions before a monthly expiry, against the "
                                    f"stock's last {sc.ROLLOVER_PAST_EXPIRIES} expiries at the same distance",
                        "options": f"the first expiry more than {sc.OPTIONS_SKIP_EXPIRY_DAYS} days after the date; {sc.OI_LABEL}"},
        "technicals": {"source": "app Postgres stock_technical_features (AI scanner, nightly 19:45 IST; price-only)",
                       "ok": tech_gap is None, "stocks": len(tech), "as_of": tech_dates[-1] if tech_dates else None},
        "calendar": {"source": "NSE CM holiday list (DaaS /holidays)", "ok": cal_gap is None},
        "chartink": None,
    }
    for g in first.get("gaps") or []:
        if isinstance(g, str):
            gaps.append(f"results calendar: {g}")
    gaps.append("cash flow is not stored on staging: the cash-flow quality check is not run")

    return {
        "schema": SCHEMA, "date": day.isoformat(), "as_of": now.astimezone(timezone.utc).isoformat(), "mode": "live" if live else "snapshot",
        "week": {"from": mon.isoformat(), "to": sat.isoformat()},
        "basis": sc.BASIS, "consensus_available": False, "label": sc.LABEL,
        "counts": counts_of(in_week), "counts_partial": not all(m["ok"] for m in win_meta[:len(week_wins)]),
        "results": in_week,
        "ideas": {"fno": fno_ideas["items"], "all": all_ideas["items"], "note": sc.IDEAS_NOTE, "tested": True,
                  "weights": {"declared": sc.DECLARED_WEIGHTS, "upcoming": sc.UPCOMING_WEIGHTS},
                  "left_out": {"fno": fno_ideas["left_out"], "all": all_ideas["left_out"]},
                  "rule": "declared: filed in the last 3 sessions; upcoming: meeting on the date or in the next 5 sessions; "
                          "the OI part reads total futures OI across every expiry; in the 5 sessions up to and including a "
                          "monthly expiry, short covering and long unwinding score as no clear signal (expiry week: open "
                          "interest falls as contracts close); All list has no OI part (its weight spread pro rata); "
                          "Chartink hits are shown, never scored; ties: higher earnings score, then symbol"},
        "rules": {"max_half_width": sc.MAX_HALF_WIDTH, "surprise_weights": sc.SURPRISE_WEIGHTS,
                  "composite_weights": sc.COMPOSITE_WEIGHTS, "bands": {"above": 70, "in_line": 45, "below": 0},
                  "status": "provisional, not validated (docs/EARNINGS_SURPRISE_TRACKER.md §4, §7)"},
        "sources": sources, "gaps": list(dict.fromkeys(gaps)), "read_only": True,
    }


def strip_chartink(body: Dict[str, Any]) -> Dict[str, Any]:
    """The body as stored: no per-user column."""
    out = copy.deepcopy(body)
    for r in out.get("results") or []:
        r["chartink"] = None
    out.setdefault("sources", {})["chartink"] = None
    return out


def join_chartink(body: Dict[str, Any], by: Optional[Dict[str, List[str]]], meta: Dict[str, Any]) -> Dict[str, Any]:
    """The signed-in user's Chartink confirmation on each row: {scans, scan_date} when hits are stored for the date
    (an empty list = not hit), null when there are none to show. Never changes a score or an order."""
    out = copy.deepcopy(body)
    for r in out.get("results") or []:
        r["chartink"] = {"scans": by.get(r["symbol"], []), "scan_date": meta.get("scan_date")} if by is not None else None
    out.setdefault("sources", {})["chartink"] = meta
    if meta.get("failed"):
        out.setdefault("gaps", []).append(meta.get("note"))
    return out
