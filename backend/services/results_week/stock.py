"""The per-stock results file (docs/EARNINGS_SURPRISE_TRACKER.md §9b): GET /api/desk/results-week/stock/{symbol}.

One stock's results week in one answer: a pre-result preview built from data (no model text), the stored filing analyses
split into pre-result / the result / post-result with a results sentiment, analyst views (no source connected: said so),
and the cash & F&O track from 5 sessions before the first reaction session to the latest loaded session.

It reuses the week's row (the cached live body or the stored snapshot) and adds per-stock reads through the same loaders.
Read-only. A failed read is a gap; nothing is invented and nothing is a prediction.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import loaders, scoring as sc, track

logger = logging.getLogger(__name__)

SCHEMA = "results-stock-v1"
RESULT_WORD = "RESULT"          # event_type is written by the analysis model: RESULTS, QUARTERLY RESULTS, …
COMMENTARY_BACK_DAYS = 21       # filing analyses from 3 weeks before the meeting
RESULT_BEFORE_H, RESULT_AFTER_H = 6, 36   # an analysis this close to the results filing belongs to "the result"
ANALYST_NOTE = ("No analyst-views source is connected: the Trendlyne connection returns corporate events only and no "
                "consensus or brokerage feed is held. Nothing on this page is an analyst view.")
KINDS = (("earnings_call", ("transcript", "con. call", "conference call", "earnings call", "audio", "concall")),
         ("presentation", ("presentation", "investor meet", "analyst meet")),
         ("press_release", ("press release",)),
         ("business_update", ("business update", "updates", "operational update", "quarterly update")),
         ("board_outcome", ("outcome of board meeting", "board meeting")))


def kind_of(doc: Dict[str, Any]) -> str:
    cat = str(doc.get("exchange_category") or "").lower()
    et = str(doc.get("event_type") or "").upper()
    for k, words in KINDS:
        if any(w in cat for w in words):
            if k == "board_outcome" and RESULT_WORD in et:
                return "results"
            return k
    if RESULT_WORD in et or "financial result" in cat:
        return "results"
    return "other"


def _factors(v: Any) -> List[str]:
    """pf / nf: [[text, weight], …] → texts, heaviest first."""
    items = []
    for x in v or []:
        if isinstance(x, (list, tuple)) and x:
            items.append((str(x[0]), sc.num(x[1]) if len(x) > 1 else None))
        elif isinstance(x, str):
            items.append((x, None))
    items.sort(key=lambda t: -(t[1] or 0))
    return [t for t, _ in items]


def _amounts(v: Any) -> List[str]:
    out = []
    for a in v or []:
        if isinstance(a, dict) and a.get("what") and a.get("v") is not None:
            unit = {"cr": "₹ crore", "usd_mn": "USD mn", "pct": "%", "shares": "shares"}.get(str(a.get("u")), str(a.get("u") or ""))
            out.append(f"{a['what']}: {a['v']} {unit}".strip())
    return out


def item_of(doc: Dict[str, Any], urls: Dict[str, str]) -> Dict[str, Any]:
    a = doc.get("analysis") or {}
    ts = sc.parse_ts(doc.get("event_ts"))
    aid = str(doc.get("announcement_id") or "") or None
    return {"at": ts.isoformat() if ts else None, "kind": kind_of(doc), "title": doc.get("exchange_category"),
            "subtype": doc.get("event_subtype"), "band": doc.get("net_band"), "impact": sc.num(doc.get("net_impact_score")),
            "confidence": sc.num(doc.get("confidence_score")), "summary": a.get("sum"),
            "positives": _factors(a.get("pf")), "negatives": _factors(a.get("nf")), "amounts": _amounts(a.get("amt")),
            "open_questions": [str(x) for x in (a.get("unk") or []) if x], "announcement_id": aid,
            "url": urls.get(aid or "")}


def split_commentary(docs: Sequence[Dict[str, Any]], filed_at: Optional[datetime], urls: Dict[str, str]
                     ) -> Dict[str, Any]:
    """pre / results / post by time against the results filing; one item per filing (the latest analysis of it)."""
    latest: Dict[str, Dict[str, Any]] = {}
    for d in docs:
        key = str(d.get("announcement_id") or id(d))
        cur = latest.get(key)
        if cur is None or (sc.parse_ts(d.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= \
                (sc.parse_ts(cur.get("analyzed_at")) or datetime.min.replace(tzinfo=timezone.utc)):
            latest[key] = d
    items = sorted((item_of(d, urls) for d in latest.values()), key=lambda i: i["at"] or "")
    pre, res, post = [], [], []
    for it in items:
        at = sc.parse_ts(it["at"])
        if filed_at is None or at is None:
            (res if it["kind"] == "results" else pre).append(it)
        elif at < filed_at - timedelta(hours=RESULT_BEFORE_H):
            pre.append(it)
        elif at <= filed_at + timedelta(hours=RESULT_AFTER_H) and it["kind"] in ("results", "presentation", "press_release", "board_outcome"):
            res.append(it)
        elif at < filed_at:
            pre.append(it)
        else:
            post.append(it)
    sentiment = None
    rated = [i for i in res if i["band"]]
    if rated:
        best = max(rated, key=lambda i: ((i["confidence"] or 0), i["at"] or ""))
        sentiment = {"band": best["band"], "impact": best["impact"], "confidence": best["confidence"],
                     "basis": f"the filing analysis of “{best['title']}” ({(best['at'] or '')[:16].replace('T', ' ')} UTC)",
                     "n": len(rated)}
    return {"pre": pre, "results": res, "post": post, "sentiment": sentiment, "analysed": len(items)}


def quarters_table(rows: Sequence[Dict[str, Any]], target: Optional[date], declared: bool, n: int = 4) -> List[Dict[str, Any]]:
    """The last n stored quarters up to the target quarter (declared) or before it (upcoming), newest first."""
    by = sc._rows_by_end(rows)
    ends = sorted(e for e in by if target is None or (e <= target if declared else e < target))[-n:]
    out = []
    for e in reversed(ends):
        r, r4 = by[e], by.get(sc.shift_quarters(e, 4))
        m = sc._margin(r)
        out.append({"period_end": e.isoformat(), "revenue": sc._fig(r, "revenue"), "ebitda": sc._fig(r, "ebitda"),
                    "pat": sc._fig(r, "pat"), "ebitda_margin_pct": sc.r1(m),
                    "revenue_yoy_pct": sc.r1(sc.growth_pct(sc._fig(r, "revenue"), sc._fig(r4, "revenue"))),
                    "pat_yoy_pct": sc.r1(sc.growth_pct(sc._fig(r, "pat"), sc._fig(r4, "pat")))})
    return out


def past_stats(body: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    occ = [o for o in (body or {}).get("occurrences") or [] if isinstance(o, dict)]
    ev = [sc.num(o.get("event_day_pct")) for o in occ]
    ev = [x for x in ev if x is not None]
    if not ev:
        return None
    d1 = [x for x in (sc.num(o.get("d1_pct")) for o in occ) if x is not None]
    w1 = [x for x in (sc.num(o.get("w1_pct")) for o in occ) if x is not None]
    mean = lambda xs: sc.r2(sum(xs) / len(xs)) if xs else None   # noqa: E731
    return {"n": len(ev), "event_day_avg_pct": mean(ev), "d1_avg_pct": mean(d1), "w1_avg_pct": mean(w1),
            "up_share_pct": sc.r1(100.0 * sum(1 for x in ev if x > 0) / len(ev))}


def _fmt_range(m: Optional[Dict[str, Any]]) -> Optional[str]:
    x = (m or {}).get("expected") or {}
    if not (m or {}).get("reliable") or x.get("low") is None:
        return None
    return f"₹{x['low']:,.0f}–{x['high']:,.0f} crore (mid ₹{x['mid']:,.0f} crore)"


def preview_lines(row: Dict[str, Any], quarters: Sequence[Dict[str, Any]], past: Optional[Dict[str, Any]],
                  before: Optional[Dict[str, Any]]) -> List[str]:
    """Deterministic sentences from the data; nothing predicted."""
    lines: List[str] = []
    ms = ((row.get("components") or {}).get("surprise") or {}).get("metrics") or {}
    if isinstance(ms, list):
        ms = {m.get("key"): m for m in ms if isinstance(m, dict)}
    for key, word in (("revenue", "Revenue"), ("pat", "Profit (PAT)")):
        rng = _fmt_range(ms.get(key))
        if rng:
            lines.append(f"{word} baseline for {row.get('period_label') or 'the quarter'}: {rng}, from the company's own past quarters (not analyst consensus).")
        elif ms.get(key):
            lines.append(f"{word}: no reliable baseline ({(ms[key].get('note') or 'too few comparable quarters').rstrip('.')}).")
    if quarters:
        q = quarters[0]
        bits = [f"revenue {q['revenue_yoy_pct']:+.1f} % YoY" if q.get("revenue_yoy_pct") is not None else None,
                f"PAT {q['pat_yoy_pct']:+.1f} % YoY" if q.get("pat_yoy_pct") is not None else None,
                f"EBITDA margin {q['ebitda_margin_pct']:.1f} %" if q.get("ebitda_margin_pct") is not None else None]
        bits = [b for b in bits if b]
        if bits:
            lines.append(f"Latest stored quarter ({q['period_end']}): {', '.join(bits)}.")
    if past:
        lines.append(f"Past {past['n']} results: the stock moved {past['event_day_avg_pct']:+.2f} % on average on the day"
                     + (f" and {past['d1_avg_pct']:+.2f} % the next session" if past.get("d1_avg_pct") is not None else "")
                     + f"; up on {past['up_share_pct']:.0f} % of them.")
    if before and before.get("state"):
        lines.append(f"F&O going in ({before['date']}): {before['text']} (spot {before['price_pct']:+.2f} %, total OI {before['oi_pct']:+.2f} %)."
                     if before.get("price_pct") is not None and before.get("oi_pct") is not None else f"F&O going in ({before['date']}): {before['text']}.")
    return lines


async def announcements(sym: str, since: date) -> Tuple[Dict[str, str], Optional[int], Optional[str]]:
    """({announcement_id: attachment url}, number of exchange filings since `since`, gap) from DaaS /announcements."""
    try:
        st, body = await loaders.daas_get("/announcements", {"symbol": sym, "filed_from": since.isoformat(), "limit": 100})
    except Exception as e:  # noqa: BLE001
        return {}, None, f"exchange filings list could not be read ({loaders._why(e)})"
    if st != 200 or not isinstance(body, dict):
        return {}, None, f"exchange filings list could not be read (DaaS HTTP {st})"
    rows = body.get("data") or body.get("rows") or body.get("announcements") or []
    urls = {str(r.get("announcement_id")): r.get("attachment_url") for r in rows
            if isinstance(r, dict) and r.get("announcement_id") and r.get("attachment_url")}
    return urls, len(rows), None


async def all_analyses(db, sym: str, start: datetime, end: datetime) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Every full filing analysis of the stock (any event type), tools off and isolated, event_ts in [start, end)."""
    q = {"symbol": sym, "tool_isolation": loaders.ISOLATED,
         "event_ts": {"$gte": start.astimezone(timezone.utc).replace(tzinfo=None), "$lt": end.astimezone(timezone.utc).replace(tzinfo=None)}}
    proj = {"_id": 0, "symbol": 1, "announcement_id": 1, "mode": 1, "event_ts": 1, "analyzed_at": 1, "net_impact_score": 1,
            "net_band": 1, "confidence_score": 1, "analysis": 1, "exchange_category": 1, "event_type": 1, "event_subtype": 1}
    try:
        docs = await db[loaders.ANALYSIS_COLLECTION].find(q, proj).to_list(length=300)
    except Exception as e:  # noqa: BLE001
        return [], f"filing analysis (Mongo {loaders.ANALYSIS_COLLECTION}) could not be read ({type(e).__name__})"
    return [d for d in docs if loaders._is_analysis(d)], None


async def build_stock(row: Dict[str, Any], day: date, *, db, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    sym = str(row["symbol"]).upper()
    gaps: List[str] = []
    ev_d = date.fromisoformat(str(row.get("event_date"))[:10]) if row.get("event_date") else None
    filed_at = sc.parse_ts(row.get("filed_at"))
    sess, cal_gap = await loaders.sessions(day - timedelta(days=90), day + timedelta(days=14))
    if cal_gap:
        gaps.append(cal_gap)
    first = track._first_reaction(row, sess)
    latest = max((s for s in sess if s <= day), default=None)
    anchor, win = track.window(first, ev_d, sess, latest)
    w_start = win[0][1] if win else (latest or day)

    since = (anchor or ev_d or day) - timedelta(days=COMMENTARY_BACK_DAYS)
    a_start = datetime.combine(since, datetime.min.time(), loaders.IST)
    bu_days = [d for _, d in win]
    reads = await asyncio.gather(
        loaders.prices([sym], w_start - timedelta(days=45), day),
        loaders.nifty(w_start - timedelta(days=10), day),
        all_analyses(db, sym, a_start, now),
        announcements(sym, since),
        loaders.history([sym]),
        loaders.quarterly({sym: row.get("basis") != "standalone"}),
        *(loaders.buildup(d, fallback=False) for d in bu_days),
    )
    (px, px_gap), (nf, nf_gap), (docs, an_gap), (urls, n_filings, ann_gap), (hist, hist_gaps, _hs), (fin, fin_gaps, _fs) = reads[:6]
    for g in (px_gap, nf_gap, an_gap, ann_gap, hist_gaps.get(sym), fin_gaps.get(sym)):
        if g:
            gaps.append(g)
    by_day: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for d, res in zip(bu_days, reads[6:]):
        if res[0]:
            by_day[d.isoformat()] = res[0]
    bars = (px or {}).get(sym, {})

    # the track
    sessions_out = track.session_rows(win, sym, bars, nf or {}, by_day, sess, track.volume_base(bars, w_start, sess))
    notes: List[str] = []
    expiries: List[date] = []
    if row.get("fno"):
        try:
            expiries = await loaders.fno_expiries(sym)
        except Exception as e:  # noqa: BLE001
            gaps.append(f"F&O expiries could not be read ({loaders._why(e)})")
        extra = [s for s in sessions_out if s["rel"] == -1] + sessions_out[-1:]
        for s in {x["date"]: x for x in extra}.values():
            d = date.fromisoformat(s["date"])
            try:
                fut = await loaders.fno_contracts(sym, d, "STF", past=d < day)
            except Exception as e:  # noqa: BLE001
                gaps.append(f"futures of {s['date']} could not be read ({loaders._why(e)})")
                continue
            if s["fut"] is not None:
                s["fut"]["next_premium_pct"] = track.next_premium(fut, d)
                legs = sc._contract_day(fut)
                s["fut"]["expiry_day"] = bool(legs) and str(legs[0].get("expiry_date") or "")[:10] == s["date"]
                rb = (row.get("fno_buildup") or {})
                if s["fut"]["expiry_day"] and str(rb.get("as_of") or "")[:10] == s["date"]:
                    s["fut"]["carry_vs_usual_pp"] = track.roll_carry(rb.get("rollover"))
            opt_exp = sc.options_expiry(sc._contract_day(fut), d)
            if opt_exp:
                try:
                    s["pcr_next"] = track.pcr(await loaders.fno_contracts(sym, d, "STO", opt_exp, past=d < day))
                except Exception as e:  # noqa: BLE001
                    gaps.append(f"options of {s['date']} could not be read ({loaders._why(e)})")
        notes.append("Next-month premium and PCR are read for the session before the result and the latest session only.")
        if sessions_out:
            a, b = date.fromisoformat(sessions_out[0]["date"]), date.fromisoformat(sessions_out[-1]["date"])
            if any(a < e <= b for e in expiries):
                notes.append("This window " + track.EXPIRY_NOTE + ".")
    else:
        notes.append("Not in F&O: the track shows the cash market only.")
    ft = track.fno_track(row, sess, latest, by_day, expiries) if row.get("fno") else None

    # commentary
    com = split_commentary(docs, filed_at, urls)
    coverage_note = (f"{com['analysed']} of {n_filings} exchange filings since {since.isoformat()} have a stored analysis; "
                     "the others are not summarised here." if n_filings is not None else
                     f"{com['analysed']} filings since {since.isoformat()} have a stored analysis.")
    if row.get("status") != "upcoming" and not com["results"]:
        coverage_note += " The results filing itself has no full analysis yet (or its document could not be read)."

    # preview
    rows_fin = (fin or {}).get(sym) or []
    target = sc.period_end_of(row.get("period_label"))
    quarters = quarters_table(rows_fin, target, row.get("status") == "declared")
    past = past_stats((hist or {}).get(sym))
    before = (ft or {}).get("before")
    ms = ((row.get("components") or {}).get("surprise") or {}).get("metrics") or {}
    if isinstance(ms, list):
        ms = {m.get("key"): m for m in ms if isinstance(m, dict)}
    expected = {k: ({"low": ((ms.get(k) or {}).get("expected") or {}).get("low"), "mid": ((ms.get(k) or {}).get("expected") or {}).get("mid"),
                     "high": ((ms.get(k) or {}).get("expected") or {}).get("high"), "reliable": (ms.get(k) or {}).get("reliable"),
                     "note": (ms.get(k) or {}).get("note")} if ms.get(k) else None) for k in ("revenue", "pat")}

    return {
        "schema": SCHEMA, "symbol": sym, "name": row.get("name"), "sector": row.get("sector"), "event_date": row.get("event_date"),
        "status": row.get("status"), "filed_at": row.get("filed_at"),
        "first_reaction_session": anchor.isoformat() if anchor and first else None, "period_label": row.get("period_label"),
        "row": row,
        "preview": {"as_of": (before or {}).get("date") or (latest.isoformat() if latest else None),
                    "lines": preview_lines(row, quarters, past, before), "expected": expected, "last_quarters": quarters,
                    "past_reactions": past, "positioning": before},
        "commentary": {"pre": com["pre"], "results": com["results"], "post": com["post"], "sentiment": com["sentiment"],
                       "coverage": {"analysed": com["analysed"], "filings": n_filings, "note": coverage_note}},
        "analyst_views": {"available": False, "note": ANALYST_NOTE},
        "track": {"sessions": sessions_out, "before": (ft or {}).get("before"), "after": (ft or {}).get("after"), "notes": notes},
        "sources": {"commentary": "stored filing analyses (Mongo event_ai_analysis, full analyses, tools off), exchange filings (DaaS /announcements)",
                    "track": "stock_ohlcv (cash close, volume), Nifty 50 (DaaS index EOD), NSE F&O bhavcopy (DaaS /desk/fno-buildup, /fno/{symbol})",
                    "preview": "the results-week row (baseline), DaaS /financials (quarters), DaaS /desk/events-calendar/history (past reactions)"},
        "gaps": gaps, "read_only": True,
    }
