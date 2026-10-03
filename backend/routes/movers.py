"""Top Movers Dashboard — read-only API.

Backs `frontend-v5/design/mover-dashboard/` (design package: docs/Top Movers Dashboard Design.zip).
Every computation here is the Python port of the design's own JS, so the numbers on screen are
the numbers this API returns — not a re-interpretation:

  reaction  e.re      = close[i+1] / close[i-1] - 1
  gap       e.gap     = open[i+1]  / close[i]   - 1
  vol_pre   e.volPre  = avg(vol[i-3..i-1]) / avg(vol[i-25..i-5])
  vol_post  e.volPost = avg(vol[i..i+2])   / avg(vol[i-25..i-5])
  flip      e.flip    = range>0 AND sign(c-o) != sign(o-prev_c)
                        AND |c-o|/range > .3 AND |o-prev_c|/prev_c > .01
  decomp              = R, M, S; mPart = beta*M; sPart = sbeta*(S-M); spec = R - mPart - sPart

Endpoints
  GET /api/movers                      — sidebar: ranked movers + odds badge
  GET /api/movers/{symbol}             — header, chart bars, index series, lanes, event log, model
  GET /api/movers/{symbol}/analysis    — Copilot card + market/sector sensitivity for a pinned event

Honest degradation (CONTEXT.md §1 — mock data is loud or it's a lie). Three design elements have
no complete source. None of them are faked; each returns `available: false` with a `reason` so the
UI can show "no source" instead of an empty list that reads as "nothing happened":

  * INSIDER / SAST lane  — nidp has no insider/SAST/pledge table (only quarterly
    shareholding_pattern). reason=NO_SOURCE_TABLE.
  * beta / correlation   — nidp.index_eod begins 2026-02-06, so the design's 250-session (1Y)
    regression cannot be satisfied. We regress over what exists and report `sessions_used`;
    below MIN_REG_SESSIONS the block is unavailable. reason=INSUFFICIENT_INDEX_HISTORY.
  * sector index         — nidp.sector_master maps only ~500 of 2628 symbols onto 6 coarse
    indices, so SECTOR_INDEX below pins the design's named indices first.
    reason=NO_SECTOR_INDEX when nothing maps.

Auth: any logged-in user (market-wide view, not per-portfolio). Read-only; no writes anywhere.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/movers", tags=["movers"])

# ── tunables ───────────────────────────────────────────────────────────────
MARKET_INDEX = "Nifty 50"
ODDS_CUTOFF = 0.40          # design: score < 0.40 => not in the candidate universe
ODDS_LOOKBACK = 10          # sessions before T the model may flag within
REG_MAX_SESSIONS = 250      # design's 1Y pre-T regression length
REG_MIN_SESSIONS = 30       # below this a beta is noise, so we refuse to publish one
MIN_TURNOVER = 5e6          # ₹50 L/day median — keeps illiquid scrips out of the ranking

# The design names a sector index per stock (its SECT table). nidp.sector_master is too sparse
# and too coarse to reproduce that, so these pins come straight from the design package and are
# the first lookup; sector_master is the fallback.
SECTOR_INDEX: dict[str, str] = {
    "SUZLON": "Nifty Energy", "KAYNES": "Nifty Consumer Durables",
    "ADANIENT": "Nifty Commodities", "BSE": "Nifty Capital Markets",
    "IREDA": "Nifty Financial Services", "HAL": "Nifty India Defence",
    "MAZDOCK": "Nifty India Defence", "PAYTM": "Nifty Financial Services",
    "DIXON": "Nifty Consumer Durables", "TATAMOTORS": "Nifty Auto",
}
SECTOR_FALLBACK: dict[str, str] = {
    "capital goods": "Nifty India Manufacturing", "metals": "Nifty Metal",
    "automobile and auto components": "Nifty Auto", "financial services": "Nifty Financial Services",
    "information technology": "Nifty IT", "healthcare": "Nifty Pharma",
    "oil gas & consumable fuels": "Nifty Energy", "power": "Nifty Energy",
    "fast moving consumer goods": "Nifty FMCG", "consumer durables": "Nifty Consumer Durables",
    "realty": "Nifty Realty", "construction": "Nifty Infrastructure",
}

# Design's KIND table: first matching pattern wins. (regex-free: substring groups, lowercased)
_KIND = [
    (("qip", "fund raise"), "QIP", "Qualified institutional placement — dilutive, priced at a floor."),
    (("ofs",), "OFS", "Offer for sale — promoter/GoI sells via exchange window."),
    (("block deal",), "BLOCK DEAL", "Pre-agreed trade on the block window; shows institutional conviction."),
    (("bulk deal",), "BULK DEAL", "Single party traded >0.5% of equity in one session."),
    (("bonus",), "BONUS ISSUE", "Capitalisation of reserves; share count rises, price adjusts."),
    (("dividend",), "DIVIDEND", "Record date for cash payout; price adjusts ex-date."),
    (("demerger",), "DEMERGER", "Spin-off of a business unit; value re-rating event."),
    (("pledge",), "PLEDGE", "Promoter share pledge created or released."),
    (("sast", "crosses", "below"), "SAST", "Substantial acquisition disclosure — holding crossed a threshold."),
    (("sells", "buys"), "INSIDER TRADE", "PIT Reg 7(2) promoter/director trade."),
    (("results", "financials"), "EARNINGS", "Quarterly financial results approved by the board."),
    (("board meeting",), "BOARD MEETING", "Board agenda intimation under Reg 29."),
    (("agm", "analyst meet"), "INVESTOR MEET", "Shareholder or analyst interaction."),
    (("order", "contract", "dac", "l1", "approval", "drhp"), "ORDER / CONTRACT",
     "Business win or regulatory approval disclosed under Reg 30."),
    (("rbi", "sebi", "rating"), "REGULATORY", "Regulator or rating agency action."),
    (("cyber", "concentration", "wholesale", "volume", "update"), "BUSINESS UPDATE",
     "Operational disclosure outside results."),
]

# Design's TYPE table — lane index + label + accent + glyph.
_TYPE = {
    "res":   {"lane": "fil",  "label": "RESULTS",      "color": "indigo", "glyph": "R"},
    "news":  {"lane": "fil",  "label": "FILING",       "color": "indigo", "glyph": "F"},
    "ca":    {"lane": "ca",   "label": "CORP ACTION",  "color": "amber",  "glyph": "C"},
    "dealB": {"lane": "deal", "label": "DEAL · BUY",   "color": "mint",   "glyph": "▲"},
    "dealS": {"lane": "deal", "label": "DEAL · SELL",  "color": "danger", "glyph": "▼"},
    "ins":   {"lane": "ins",  "label": "INSIDER",      "color": "rose",   "glyph": "I"},
}
LANES = [
    {"key": "fil",  "label": "RESULTS / FILINGS"},
    {"key": "ca",   "label": "CORP ACTION"},
    {"key": "deal", "label": "BULK / BLOCK"},
    {"key": "ins",  "label": "INSIDER / SAST"},
    {"key": "mdl",  "label": "ODDS MODEL"},
]
RANGE_DAYS = {"1D": 1, "T7": 7, "1M": 30, "3M": 91, "1Y": 365}

# ── TTL cache (same idiom as routes/market_events.py) ───────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_TTL = 300  # EOD data — only changes once a day after the bhavcopy lands


def _cache_get(key: str) -> Any | None:
    e = _cache.get(key)
    return e[1] if e and e[0] > time.monotonic() else None


def _cache_set(key: str, value: Any, ttl: int = _TTL) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def _lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def _pool():
    from services import pg_client
    return await pg_client.get_pool()


# ── small numeric helpers (ports of the design's JS) ────────────────────────
def _f(v: Any) -> Optional[float]:
    return None if v is None else float(v)


def _reg(y: list[float], x: list[float]) -> Optional[dict[str, float]]:
    """design: reg(y,x) -> {beta, corr}. None when the sample is too small/degenerate."""
    n = len(y)
    if n < REG_MIN_SESSIONS or n != len(x):
        return None
    my, mx = sum(y) / n, sum(x) / n
    c = vx = vy = 0.0
    for k in range(n):
        dy, dx = y[k] - my, x[k] - mx
        c += dy * dx
        vx += dx * dx
        vy += dy * dy
    if vx <= 0 or vy <= 0:
        return None
    return {"beta": c / vx, "corr": c / math.sqrt(vx * vy), "sessions": n}


def _kind_of(title: str, sub: str) -> tuple[str, str]:
    h = f"{title} {sub}".lower()
    for pats, kind, desc in _KIND:
        if any(p in h for p in pats):
            return kind, desc
    return "DISCLOSURE", "Exchange filing."


def _flags_of(ev: dict) -> list[dict]:
    """design: flagsOf() — the three trade signals, with the design's exact thresholds."""
    out = []
    gap = ev.get("gap")
    if gap is not None and abs(gap) >= 0.02:
        up = gap > 0
        out.append({
            "label": f"GAP {'UP' if up else 'DN'} {'≥3%' if abs(gap) >= 0.03 else '≥2%'} · {gap*100:.1f}%",
            "tone": "mint" if up else "danger",
        })
    vp, vq = ev.get("vol_pre"), ev.get("vol_post")
    if vp is not None and vq is not None:
        vx = max(vp, vq)
        if vx >= 2:
            when = "PRE+POST" if vp >= 2 and vq >= 2 else ("PRE" if vp >= 2 else "POST")
            out.append({"label": f"VOL {'3×+' if vx >= 3 else '2×+'} {when}", "tone": "amber"})
    if ev.get("flip"):
        out.append({"label": "COIN FLIP", "tone": "indigo"})
    return out


# ── data loaders ───────────────────────────────────────────────────────────
async def _sessions(conn, symbol: str, d0: date, d1: date) -> list[dict]:
    """Daily EQ bars for one symbol. Series is pinned to EQ: a BE/BZ stint is circuit-capped
    at 2%/5% and can never be a 5-10% mover, so mixing them would corrupt the ranking."""
    rows = await conn.fetch(
        """
        SELECT as_of_date, open_price, high_price, low_price, close_price,
               prev_close, volume, turnover
          FROM nidp.prices_eod
         WHERE symbol = $1 AND series = 'EQ' AND as_of_date BETWEEN $2 AND $3
         ORDER BY as_of_date
        """, symbol, d0, d1)
    return [{
        "t": r["as_of_date"].isoformat(),
        "o": _f(r["open_price"]), "h": _f(r["high_price"]),
        "l": _f(r["low_price"]),  "c": _f(r["close_price"]),
        "prev_c": _f(r["prev_close"]), "v": int(r["volume"] or 0),
        "turnover": _f(r["turnover"]),
    } for r in rows]


async def _index_series(conn, index_name: str, d0: date, d1: date) -> dict[str, float]:
    rows = await conn.fetch(
        """
        SELECT as_of_date, close_price FROM nidp.index_eod
         WHERE index_name = $1 AND as_of_date BETWEEN $2 AND $3 ORDER BY as_of_date
        """, index_name, d0, d1)
    return {r["as_of_date"].isoformat(): _f(r["close_price"]) for r in rows if r["close_price"]}


async def _sector_index_for(conn, symbol: str) -> Optional[str]:
    """Design pin first (its SECT table), then nidp.sector_master, then a sector-name fallback."""
    if symbol in SECTOR_INDEX:
        return SECTOR_INDEX[symbol]
    row = await conn.fetchrow(
        "SELECT sector, sector_benchmark_index FROM nidp.sector_master WHERE symbol = $1", symbol)
    if not row:
        return None
    if row["sector_benchmark_index"]:
        return row["sector_benchmark_index"]
    if row["sector"]:
        return SECTOR_FALLBACK.get(row["sector"].strip().lower())
    return None


async def _events_for(conn, symbol: str, d0: date, d1: date) -> list[dict]:
    """Every lane the DB can serve. The INSIDER/SAST lane is deliberately absent here — see
    _insider_for(): nidp has no such table, so it is reported unavailable rather than empty."""
    out: list[dict] = []

    for r in await conn.fetch(
        """
        SELECT announcement_id, COALESCE(broadcast_at, filed_at) AS at, subject, description,
               event_category, sentiment, impact_score
          FROM nidp.corporate_announcements
         WHERE ticker_symbol = $1
           AND COALESCE(broadcast_at, filed_at)::date BETWEEN $2 AND $3
         ORDER BY 2
        """, symbol, d0, d1):
        subject = (r["subject"] or "").strip()
        cat = (r["event_category"] or "").lower()
        is_res = any(k in cat or k in subject.lower() for k in ("result", "financial", "earnings"))
        out.append({
            "id": f"ann:{r['announcement_id']}", "date": r["at"].date().isoformat(),
            "type": "res" if is_res else "news", "title": subject or "Exchange filing",
            "sub": (r["description"] or "").strip()[:180] or (r["event_category"] or ""),
            "sentiment": r["sentiment"], "impact_score": r["impact_score"],
        })

    for r in await conn.fetch(
        """
        SELECT action_type, action_subtype, purpose, ratio, dividend_amount, ex_date, record_date
          FROM nidp.corporate_actions
         WHERE symbol = $1 AND ex_date BETWEEN $2 AND $3 ORDER BY ex_date
        """, symbol, d0, d1):
        bits = [b for b in (r["ratio"], (f"₹{_f(r['dividend_amount']):.2f} / share"
                                         if r["dividend_amount"] else None), r["purpose"]) if b]
        out.append({
            "id": f"ca:{symbol}:{r['ex_date']}:{r['action_type']}",
            "date": r["ex_date"].isoformat(), "type": "ca",
            "title": " · ".join(x for x in (r["action_type"], r["action_subtype"]) if x) or "Corporate action",
            "sub": " · ".join(bits)[:180],
        })

    for r in await conn.fetch(
        """
        SELECT 'BULK' AS src, as_of_date, client_name, deal_type, quantity, avg_price
          FROM nidp.bulk_deals  WHERE symbol = $1 AND as_of_date BETWEEN $2 AND $3
        UNION ALL
        SELECT 'BLOCK', as_of_date, client_name, deal_type, quantity, avg_price
          FROM nidp.block_deals WHERE symbol = $1 AND as_of_date BETWEEN $2 AND $3
        ORDER BY 2
        """, symbol, d0, d1):
        side = (r["deal_type"] or "").upper()
        buy = side.startswith("B") and "SELL" not in side
        qty = int(r["quantity"] or 0)
        out.append({
            "id": f"deal:{r['src']}:{symbol}:{r['as_of_date']}:{(r['client_name'] or '')[:24]}:{qty}",
            "date": r["as_of_date"].isoformat(), "type": "dealB" if buy else "dealS",
            "title": f"{r['src'].title()} deal",
            "sub": f"{(r['client_name'] or 'Unknown').title()} · {qty:,} sh"
                   + (f" @ ₹{_f(r['avg_price']):,.2f}" if r["avg_price"] else ""),
        })
    return out


async def _insider_for(conn, symbol: str, d0: date, d1: date) -> dict:
    """INSIDER / SAST lane.

    nidp has no insider/SAST/pledge table, so this reads nidp.insider_sast — the Trendlyne-sourced
    backfill (scripts/backfill_insider_sast.py). Until that table exists the lane is reported
    unavailable; it is never returned as an empty event list, because an empty lane reads as
    "no insider activity" when the truth is "we have no source".
    """
    exists = await conn.fetchval(
        "SELECT to_regclass('nidp.insider_sast') IS NOT NULL")
    if not exists:
        return {"available": False, "reason": "NOT_BACKFILLED", "events": [],
                "note": "nidp.insider_sast not present — run scripts/backfill_insider_sast.py",
                "source": None}
    rows = await conn.fetch(
        """
        SELECT report_date, client_name, client_category, action, disclosure_type, regulation,
               quantity, holding_after_pct, pct_traded, average_price, mode
          FROM nidp.insider_sast
         WHERE symbol = $1 AND report_date BETWEEN $2 AND $3 ORDER BY report_date
        """, symbol, d0, d1)
    evs = []
    for r in rows:
        act = (r["action"] or "").strip()
        pct = _f(r["pct_traded"])
        # Pledge/Revoke/Invoke change encumbrance, not ownership, and are the majority of the
        # feed — calling them "buys"/"sells" would misreport the single most common disclosure.
        verb = {"Acquisition": "buys", "Disposal": "sells", "Pledge": "pledges",
                "Revoke": "releases pledge", "Invoke": "pledge invoked"}.get(act, act.lower())
        evs.append({
            "id": f"ins:{symbol}:{r['report_date']}:{(r['client_name'] or '')[:24]}",
            "date": r["report_date"].isoformat(), "type": "ins", "action": act or None,
            "title": f"{(r['client_category'] or 'Insider').title()} {verb}".strip()
                     + (f" {pct:.2f}%" if pct else ""),
            "sub": " · ".join(x for x in (
                (r["client_name"] or "").title()[:60],
                f"{r['disclosure_type']}{' ' + r['regulation'] if r['regulation'] else ''}",
                r["mode"]) if x),
        })
    return {"available": True, "reason": None, "events": evs, "source": "trendlyne"}


# ── corporate-action contamination ─────────────────────────────────────────
# nidp.corporate_actions starts 2026-05-26 and holds only 8 SPLIT + 9 BONUS rows, and
# prices_eod_adjusted has a non-unit factor on 0.4% of rows — so neither can be trusted to
# explain a split. TAALTECH -79.26% (2026-09-22) and PGIL -50.06% (2026-09-11) are unadjusted
# splits that appear in NO corporate-action row. A mover list built on the raw feed therefore
# leads with phantom crashes. We flag them two ways and let the caller decide.
_CA_RATIOS = (2.0, 2.5, 3.0, 4.0, 5.0, 10.0)
_CA_TOL = 0.08


def _ca_suspect(close: float, prev: float) -> Optional[str]:
    """Flag a large fall whose price ratio sits near a common split/bonus ratio.

    The tolerance is 8%, not a hair's breadth, because a split and a real move land on the same
    session: TAALTECH 2026-09-22 printed 5714.60 -> 1185.40, a ratio of 4.82 — a 1:5 split with a
    genuine ~4% fall on top. A 2% tolerance missed it.

    This is a suspicion, not a determination, and it is one-sided by design: a true -50% crash has
    a ratio of 2.0 and will be flagged too. That is the acceptable error, because the caller can
    ask for these rows with include_ca=true, whereas an unflagged phantom crash silently becomes
    the dashboard's top mover. Only consulted when nidp.corporate_actions has nothing to say.
    """
    if not close or not prev or prev <= 0 or close / prev > 0.62:
        return None
    r = prev / close
    for k in _CA_RATIOS:
        if abs(r - k) / k <= _CA_TOL:
            return (f"price ratio {r:.2f} is within {_CA_TOL:.0%} of {k:g}:1 — suspected "
                    f"unadjusted split/bonus; no matching row in nidp.corporate_actions")
    return None


# ── Move-odds badge (three states, never two) ──────────────────────────────
async def _odds_badge(conn, symbol: str, session: date) -> dict:
    """design: CAUGHT / MISSED / NO MODEL RUN.

    Move-odds ran on 9 of September 2026's 21 sessions. Collapsing "the model did not run" into
    "the model missed it" would read as a model failure when it is a coverage gap, so the absence
    of a run is its own state and carries the window we looked in.
    """
    runs = await conn.fetch(
        """
        SELECT run_id, target_session FROM nidp.tpd_runs
         WHERE status = 'final' AND target_session > $2 AND target_session <= $3
         ORDER BY target_session
        """, symbol, session - timedelta(days=ODDS_LOOKBACK * 2), session)
    if not runs:
        return {"state": "NO_MODEL_RUN", "score": None, "head": None, "run_session": None,
                "runs_in_window": 0,
                "note": f"no final Move-odds run in the {ODDS_LOOKBACK * 2} days to {session}"}
    ids = [r["run_id"] for r in runs]
    est = await conn.fetch(
        """
        SELECT e.run_id, e.head, e.p, e.p_base_rate, r.target_session
          FROM nidp.tpd_run_estimates e JOIN nidp.tpd_runs r USING (run_id)
         WHERE e.run_id = ANY($1::bigint[]) AND e.symbol = $2
         ORDER BY e.p DESC
        """, ids, symbol)
    if not est:
        return {"state": "MISSED", "score": None, "head": None, "run_session": None,
                "runs_in_window": len(runs), "reason": "NOT_IN_SCORED_UNIVERSE",
                "note": f"{len(runs)} run(s) covered this window but {symbol} was not scored"}
    top = est[0]
    caught = _f(top["p"]) is not None and _f(top["p"]) >= ODDS_CUTOFF
    return {
        "state": "CAUGHT" if caught else "MISSED",
        "score": _f(top["p"]), "base_rate": _f(top["p_base_rate"]), "head": top["head"],
        "run_session": top["target_session"].isoformat(), "runs_in_window": len(runs),
        "cutoff": ODDS_CUTOFF,
        "heads": {r["head"]: _f(r["p"]) for r in est},
    }


# ── design's derived metrics ───────────────────────────────────────────────
def _avg(bars: list[dict], a: int, b: int, key: str = "v") -> Optional[float]:
    w = [bars[k][key] for k in range(max(0, a), min(len(bars), b + 1)) if bars[k].get(key)]
    return sum(w) / len(w) if w else None


def _event_metrics(bars: list[dict], i: int) -> dict:
    """design lines 477-534: re, gap, volPre, volPost, flip — all indexed off the event bar i."""
    out: dict[str, Any] = {"re": None, "gap": None, "vol_pre": None, "vol_post": None,
                           "flip": False}
    n = len(bars)
    if not 0 < i < n - 1:
        return out
    d, a_, nx = bars[i], bars[i - 1]["c"], bars[i + 1]
    if a_ and nx["c"]:
        out["re"] = nx["c"] / a_ - 1
    if d["c"] and nx["o"]:
        out["gap"] = nx["o"] / d["c"] - 1
    base = _avg(bars, i - 25, i - 5)
    if base:
        pre, post = _avg(bars, i - 3, i), _avg(bars, i, i + 3)
        out["vol_pre"] = pre / base if pre else None
        out["vol_post"] = post / base if post else None
    rngd = (d["h"] or 0) - (d["l"] or 0)
    if rngd > 0 and d["o"] and d["c"] and a_:
        body, gap = d["c"] - d["o"], d["o"] - a_
        if (body > 0) != (gap > 0) and abs(body) / rngd > 0.3 and abs(gap) / a_ > 0.01:
            out["flip"] = True          # opened one way, closed the other: the day reversed
    return out


def _decomp(bars: list[dict], mk: list[Optional[float]], sx: list[Optional[float]],
            beta: Optional[float], sbeta: Optional[float], a: int, b: int) -> Optional[dict]:
    """design line 550: R = beta*M + sbeta*(S-M) + specific. Returns None when any leg is
    missing, so the UI shows "not available" instead of attributing the whole move to the stock."""
    if not (0 <= a < len(bars) and 0 <= b < len(bars)) or beta is None:
        return None
    ca, cb = bars[a]["c"], bars[b]["c"]
    if not ca or not cb:
        return None
    R = cb / ca - 1
    M = (mk[b] / mk[a] - 1) if (mk[a] and mk[b]) else None
    S = (sx[b] / sx[a] - 1) if (sx[a] and sx[b]) else None
    if M is None:
        return {"R": R, "M": None, "S": S, "m_part": None, "s_part": None, "spec": None,
                "available": False, "reason": "NO_MARKET_INDEX"}
    m_part = beta * M
    s_part = (sbeta * (S - M)) if (S is not None and sbeta is not None) else 0.0
    return {"R": R, "M": M, "S": S, "m_part": m_part, "s_part": s_part,
            "spec": R - m_part - s_part, "available": True,
            "sector_leg": S is not None and sbeta is not None}


def _rets(series: list[Optional[float]], a: int, b: int) -> list[Optional[float]]:
    out: list[Optional[float]] = []
    for k in range(a + 1, b + 1):
        p, c = series[k - 1], series[k]
        out.append((c / p - 1) if (p and c) else None)
    return out


def _betas(bars: list[dict], mk: list[Optional[float]], sx: list[Optional[float]],
           ti: int) -> dict:
    """design line 745: regress on bars[ti-250 .. ti-4] — the window must END BEFORE the event
    (T-4), or the move being explained would be inside the sample that estimates beta.

    index_eod starts 2026-02-06 (144 sessions), so for a September 2026 event the market leg is
    shorter than the design's 250. We publish the window we actually used rather than pretend.
    """
    a, b = max(0, ti - REG_MAX_SESSIONS), max(0, ti - 4)
    if b - a < REG_MIN_SESSIONS:
        return {"beta": None, "corr": None, "sbeta": None, "scorr": None, "sessions": 0,
                "available": False, "reason": "INSUFFICIENT_HISTORY",
                "requested_sessions": REG_MAX_SESSIONS}
    rs = _rets([x["c"] for x in bars], a, b)
    rm = _rets(mk, a, b)
    rx = _rets(sx, a, b)
    ys = [(y, m) for y, m in zip(rs, rm) if y is not None and m is not None]
    m1 = _reg([y for y, _ in ys], [m for _, m in ys]) if ys else None
    out: dict[str, Any] = {
        "beta": m1["beta"] if m1 else None, "corr": m1["corr"] if m1 else None,
        "sbeta": None, "scorr": None,
        "sessions": m1["sessions"] if m1 else 0,
        "requested_sessions": REG_MAX_SESSIONS,
        "window": [bars[a]["t"], bars[b]["t"]],
        "available": m1 is not None,
    }
    if m1 is None:
        out["reason"] = "NO_MARKET_OVERLAP"
        return out
    if m1["sessions"] < REG_MAX_SESSIONS:
        out["degraded"] = True
        out["reason"] = (f"market index history covers {m1['sessions']} of the design's "
                         f"{REG_MAX_SESSIONS} sessions (nidp.index_eod starts 2026-02-06)")
    # sector leg: regress the market-residual on the sector's excess return
    tri = [(y, m, x) for y, m, x in zip(rs, rm, rx)
           if y is not None and m is not None and x is not None]
    if tri:
        resid = [y - m1["beta"] * m for y, m, _ in tri]
        s1 = _reg(resid, [x - m for _, m, x in tri])
        if s1:
            out["sbeta"], out["scorr"] = s1["beta"], s1["corr"]
            out["sector_sessions"] = s1["sessions"]
    return out


def _rbeta(bars: list[dict], mk: list[Optional[float]], a: int, b: int) -> Optional[dict]:
    """design line 790: rolling 20D beta/corr either side of the event."""
    a, b = max(0, a), min(len(bars) - 1, b)
    if b <= a:
        return None
    rs, rm = _rets([x["c"] for x in bars], a, b), _rets(mk, a, b)
    ys = [(y, m) for y, m in zip(rs, rm) if y is not None and m is not None]
    if len(ys) < 10:          # a 20-session window with <10 usable pairs is not a beta
        return None
    r = _reg([y for y, _ in ys], [m for _, m in ys])
    if r is None:             # _reg's own REG_MIN_SESSIONS floor is 30; relax it for the 20D window
        y_, x_ = [y for y, _ in ys], [m for _, m in ys]
        n = len(y_)
        my, mx = sum(y_) / n, sum(x_) / n
        c = vx = vy = 0.0
        for k in range(n):
            dy, dx = y_[k] - my, x_[k] - mx
            c += dy * dx
            vx += dx * dx
            vy += dy * dy
        if vx <= 0 or vy <= 0:
            return None
        r = {"beta": c / vx, "corr": c / math.sqrt(vx * vy), "sessions": n}
    return r


# ── endpoints ──────────────────────────────────────────────────────────────
@router.get("")
async def list_movers(
    request: Request,
    frm: date = Query(..., alias="from", description="window start (inclusive)"),
    to: date = Query(..., description="window end (inclusive)"),
    min_abs_pct: float = Query(5.0, ge=0, le=100),
    direction: str = Query("both", pattern="^(both|up|down)$"),
    limit: int = Query(100, ge=1, le=500),
    include_ca: bool = Query(False, description="include moves flagged as unadjusted split/bonus"),
) -> dict:
    """The dashboard's left rail: movers in a window, each with its Move-odds badge.

    Ranked on the raw feed because that is what nidp serves, but every row carries `ca_flag` /
    `ca_suspect`; with include_ca=false (the default) suspect rows are withheld from the ranking,
    because the raw September list is led by TAALTECH -79% and PGIL -50%, both unadjusted splits.
    """
    await get_current_user(request)
    if to < frm:
        raise HTTPException(400, "`to` must not precede `from`")
    if (to - frm).days > 400:
        raise HTTPException(400, "window capped at 400 days")
    ck = f"list:{frm}:{to}:{min_abs_pct}:{direction}:{limit}:{include_ca}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    async with _lock(ck):
        if (hit := _cache_get(ck)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            op = {"up": ">=", "down": "<=", "both": "!="}[direction]
            sign = 1 if direction == "up" else -1 if direction == "down" else 0
            rows = await conn.fetch(
                f"""
                SELECT p.symbol, p.as_of_date, p.open_price, p.high_price, p.low_price,
                       p.close_price, p.prev_close, p.volume, p.turnover,
                       100 * (p.close_price / p.prev_close - 1) AS pct,
                       c.action_type AS ca_type, c.ratio AS ca_ratio
                  FROM nidp.prices_eod p
                  LEFT JOIN nidp.corporate_actions c
                         ON c.symbol = p.symbol AND c.ex_date BETWEEN p.as_of_date - 1
                                                                 AND p.as_of_date + 1
                 WHERE p.series = 'EQ' AND p.as_of_date BETWEEN $1 AND $2
                   AND p.prev_close > 0 AND p.turnover >= $3
                   AND abs(100 * (p.close_price / p.prev_close - 1)) >= $4
                   AND ($5 = 0 OR sign(p.close_price / p.prev_close - 1) {op} 0)
                 ORDER BY abs(p.close_price / p.prev_close - 1) DESC
                 LIMIT $6
                """, frm, to, MIN_TURNOVER, min_abs_pct, sign, limit * 3)

            out, withheld = [], 0
            for r in rows:
                if len(out) >= limit:
                    break
                close, prev = _f(r["close_price"]), _f(r["prev_close"])
                suspect = None if r["ca_type"] else _ca_suspect(close, prev)
                if suspect and not include_ca:
                    withheld += 1
                    continue
                sess = r["as_of_date"]
                out.append({
                    "symbol": r["symbol"], "session": sess.isoformat(),
                    "pct": _f(r["pct"]), "close": close, "prev_close": prev,
                    "open": _f(r["open_price"]), "high": _f(r["high_price"]),
                    "low": _f(r["low_price"]),
                    "volume": int(r["volume"] or 0), "turnover": _f(r["turnover"]),
                    "ca_flag": ({"type": r["ca_type"], "ratio": r["ca_ratio"]}
                                if r["ca_type"] else None),
                    "ca_suspect": suspect,
                    "odds": await _odds_badge(conn, r["symbol"], sess),
                })
        res = {
            "from": frm.isoformat(), "to": to.isoformat(), "count": len(out),
            "withheld_ca_suspect": withheld, "lanes": LANES, "ranges": list(RANGE_DAYS),
            "filters": {"min_abs_pct": min_abs_pct, "direction": direction,
                        "min_turnover": MIN_TURNOVER, "include_ca": include_ca},
            "movers": out,
        }
        _cache_set(ck, res)
        return res


@router.get("/{symbol}")
async def mover_detail(
    request: Request,
    symbol: str,
    session: date = Query(..., description="the move session T the timeline centres on"),
    range_: str = Query("T7", alias="range", pattern="^(1D|T7|1M|3M|1Y|custom)$"),
    frm: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
) -> dict:
    """Chart + event lanes for one mover, centred on T. `range` matches the design's chart legend;
    `custom` takes from/to. The regression window always extends further back than the chart so
    beta is estimated on history, not on the window being explained."""
    await get_current_user(request)
    symbol = symbol.strip().upper()
    if range_ == "custom":
        if not frm or not to or to < frm:
            raise HTTPException(400, "range=custom needs from<=to")
        d0, d1 = frm, to
    else:
        n = RANGE_DAYS[range_]
        d0, d1 = session - timedelta(days=n), session + timedelta(days=n)
    ck = f"detail:{symbol}:{session}:{range_}:{d0}:{d1}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    async with _lock(ck):
        if (hit := _cache_get(ck)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            # Pull enough history for the 250-session regression, then slice the chart out of it.
            hist0 = min(d0, session - timedelta(days=int(REG_MAX_SESSIONS * 1.6)))
            bars = await _sessions(conn, symbol, hist0, d1)
            if not bars:
                raise HTTPException(404, f"no EQ price history for {symbol}")
            sector_idx = await _sector_index_for(conn, symbol)
            mkt = await _index_series(conn, MARKET_INDEX, hist0, d1)
            sct = await _index_series(conn, sector_idx, hist0, d1) if sector_idx else {}
            mk = [mkt.get(b["t"]) for b in bars]
            sx = [sct.get(b["t"]) for b in bars]

            # the event bar: T itself, or the first session at/after it
            ti = next((k for k, b in enumerate(bars) if b["t"] >= session.isoformat()), None)
            if ti is None:
                raise HTTPException(404, f"{symbol} has no session on or after {session}")

            reg = _betas(bars, mk, sx, ti)
            events = await _events_for(conn, symbol, d0, d1)
            ins = await _insider_for(conn, symbol, d0, d1)
            events += ins["events"]

            idx = {b["t"]: k for k, b in enumerate(bars)}
            for e in events:
                k = idx.get(e["date"])
                if k is None:                      # a holiday-dated filing: attach to the next session
                    k = next((j for j, b in enumerate(bars) if b["t"] >= e["date"]), None)
                    e["session_shifted"] = k is not None
                e["bar_index"] = k
                e["kind"], e["lane"] = _kind_of(e.get("title", ""), e.get("sub", ""))
                e["flags"] = _flags_of(e)
                e["metrics"] = _event_metrics(bars, k) if k is not None else None

            lo, hi = idx.get(d0.isoformat()), idx.get(d1.isoformat())
            chart = [b for b in bars if d0.isoformat() <= b["t"] <= d1.isoformat()]
            tb = bars[ti]
            res = {
                "symbol": symbol, "session": session.isoformat(), "range": range_,
                "from": d0.isoformat(), "to": d1.isoformat(),
                "header": {
                    "pct": ((tb["c"] / tb["prev_c"] - 1) * 100
                            if tb["prev_c"] else None),
                    "open": tb["o"], "high": tb["h"], "low": tb["l"], "close": tb["c"],
                    "prev_close": tb["prev_c"], "volume": tb["v"], "turnover": tb["turnover"],
                },
                "bars": chart,
                "market": {"name": MARKET_INDEX,
                           "series": [mkt.get(b["t"]) for b in chart],
                           "available": bool(mkt)},
                "sector": {"name": sector_idx,
                           "series": [sct.get(b["t"]) for b in chart],
                           "available": bool(sct),
                           "reason": None if sector_idx else "SYMBOL_NOT_IN_SECTOR_MASTER"},
                "regression": reg,
                "rolling_beta": {
                    "before": _rbeta(bars, mk, ti - 20, ti - 1),
                    "after": _rbeta(bars, mk, ti + 1, ti + 20),
                },
                "windows": [
                    {"key": "BEFORE", "label": "E-7 → E-1",
                     "decomp": _decomp(bars, mk, sx, reg["beta"], reg["sbeta"], ti - 8, ti - 1)},
                    {"key": "EVENT", "label": "E-1 → E+1",
                     "decomp": _decomp(bars, mk, sx, reg["beta"], reg["sbeta"], ti - 1, ti + 1)},
                    {"key": "AFTER", "label": "E+1 → E+7",
                     "decomp": _decomp(bars, mk, sx, reg["beta"], reg["sbeta"], ti + 1, ti + 8)},
                ],
                "lanes": LANES,
                "insider_lane": {k: v for k, v in ins.items() if k != "events"},
                "events": sorted(events, key=lambda e: (e["date"], e["type"])),
                "model": await _odds_badge(conn, symbol, session),
                "bar_index_of_session": ti - (lo if lo is not None else 0),
            }
        _cache_set(ck, res)
        return res


@router.get("/{symbol}/analysis")
async def mover_analysis(
    request: Request,
    symbol: str,
    session: date = Query(...),
    event_id: Optional[str] = Query(None, description="pin the decomposition to one event"),
) -> dict:
    """The correlation card: how much of the move the market, the sector and the stock itself
    account for, over the design's three windows, plus the event the user pinned.

    This returns arithmetic over real bars. It does not assert that the pinned event CAUSED the
    move: 374 pre-registered tests in this repo found event direction is not predictable, so the
    card is framed as attribution of what happened, never as a causal claim.
    """
    await get_current_user(request)
    symbol = symbol.strip().upper()
    ck = f"analysis:{symbol}:{session}:{event_id}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    async with _lock(ck):
        if (hit := _cache_get(ck)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            hist0 = session - timedelta(days=int(REG_MAX_SESSIONS * 1.6))
            d1 = session + timedelta(days=30)
            bars = await _sessions(conn, symbol, hist0, d1)
            if not bars:
                raise HTTPException(404, f"no EQ price history for {symbol}")
            sector_idx = await _sector_index_for(conn, symbol)
            mkt = await _index_series(conn, MARKET_INDEX, hist0, d1)
            sct = await _index_series(conn, sector_idx, hist0, d1) if sector_idx else {}
            mk = [mkt.get(b["t"]) for b in bars]
            sx = [sct.get(b["t"]) for b in bars]
            ti = next((k for k, b in enumerate(bars) if b["t"] >= session.isoformat()), None)
            if ti is None:
                raise HTTPException(404, f"{symbol} has no session on or after {session}")
            reg = _betas(bars, mk, sx, ti)

            pinned = None
            if event_id:
                evs = await _events_for(conn, symbol, session - timedelta(days=30), d1)
                evs += (await _insider_for(conn, symbol, session - timedelta(days=30), d1))["events"]
                pinned = next((e for e in evs if e["id"] == event_id), None)
                if pinned is None:
                    raise HTTPException(404, f"event {event_id} not found for {symbol}")
                k = next((j for j, b in enumerate(bars) if b["t"] >= pinned["date"]), None)
                pinned["bar_index"] = k
                pinned["metrics"] = _event_metrics(bars, k) if k is not None else None

            ei = pinned.get("bar_index") if pinned else ti
            ei = ti if ei is None else ei
            res = {
                "symbol": symbol, "session": session.isoformat(),
                "market_index": MARKET_INDEX, "sector_index": sector_idx,
                "regression": reg,
                "pinned_event": pinned,
                "anchor": {"bar": bars[ei]["t"], "is_pinned_event": bool(pinned)},
                "windows": [
                    {"key": k, "label": lab,
                     "decomp": _decomp(bars, mk, sx, reg["beta"], reg["sbeta"], a, b)}
                    for k, lab, a, b in (
                        ("BEFORE", "E-7 → E-1", ei - 8, ei - 1),
                        ("EVENT", "E-1 → E+1", ei - 1, ei + 1),
                        ("AFTER", "E+1 → E+7", ei + 1, ei + 8),
                    )
                ],
                "rolling_beta": {"before": _rbeta(bars, mk, ei - 20, ei - 1),
                                 "after": _rbeta(bars, mk, ei + 1, ei + 20)},
                "model": await _odds_badge(conn, symbol, session),
                "disclaimer": ("Attribution of realised return, not a causal claim: direction "
                               "around events is not predictable in this dataset."),
            }
        _cache_set(ck, res)
        return res
