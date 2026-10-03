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
  GET /v1/movers                      — sidebar: ranked movers + odds badge
  GET /v1/movers/{symbol}             — header, chart bars, index series, lanes, event log, model
  GET /v1/movers/{symbol}/analysis    — Copilot card + market/sector sensitivity for a pinned event

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

Auth: internal DaaS key (the app proxy enforces the user session + move_odds gate). Read-only; no writes anywhere.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

import nidp.shared.storage.pg as pg
from nidp.services.daas_api.routers.move_odds import require_internal_plan

logger = logging.getLogger(__name__)

# Runs inside the DaaS API, next to the nidp.* tables. The app backend's own database has none
# of them, so backend/routes/movers.py is a thin proxy that keeps the login session and the
# Move-odds feature gate and forwards here with the internal key.
router = APIRouter(prefix="/movers", tags=["movers"], dependencies=[Depends(require_internal_plan)])

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
    "dealB": {"lane": "deal", "label": "DEAL · BOUGHT", "color": "mint",   "glyph": "▲"},
    "dealS": {"lane": "deal", "label": "DEAL · SOLD",   "color": "danger", "glyph": "▼"},
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

# ── Top Movers v4 ────────────────────────────────────────────────────────────────────────────────
# Round-trip friction. The design uses 0.628%, which is this repo's own measured figure, not a guess:
# the paper-engine loss diagnosis put real friction at 0.628% against the 0.25% originally assumed.
COST = 0.00628
# Tolerance for threshold tests. A touch of exactly +5.000% is a touch; binary floating point
# should not be what decides it.
_EPS = 1e-9
HORIZONS = (3, 20)              # the design's on-screen grade switch
CAL_BAND = 0.05                 # calibration band width
# The design bands from 0.40 up. Measured on staging 2026-10-03, only 7 of September's 8,972
# p_up5_1d estimates reach 0.40 at all, so those bands would every one of them be noise and the chart
# would come out empty. Band across the observed range instead and let the high bands show their own
# emptiness — that is the finding, not a defect to hide.
CAL_FROM = 0.00
CAL_MIN_N = 30                  # below this a band is noise and its realised rate is withheld
DECILES = 10

# v4 ships a LIFT table of SAMPLE constants and jitters them with a sine hash; its own README says
# "Flag lift constants remain sample values; all data is synthetic". Nothing from that table is used
# here. Every lift below is computed from nidp or returned as available=false with a reason.
FLAG_DEFS = [
    ("gap2", "GAP ≥2%"), ("gap3", "GAP ≥3%"),
    ("vol2", "VOL 2×+"), ("vol3", "VOL 3×+"),
    ("flip", "COIN FLIP"), ("leak", "PRE-DRIFT LEAK"),
    ("d1", "BULK DEAL D-1"), ("ins", "INSIDER / SAST ±3D"),
]

# ── TTL cache (same idiom as routes/market_events.py) ───────────────────────
_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}
_TTL = 300  # EOD data — only changes once a day after the bhavcopy lands
# The calibration and flag-lift endpoints sweep a whole month of estimates and bars. Timed on
# staging 2026-10-03 the equivalent single query took 16.5 s, so the first caller pays a lot and a
# 5-minute TTL would make that happen twelve times an hour. The inputs only change when a new
# session resolves, so hold them for the day. This is a mitigation, not a fix: the real answer is a
# nightly job writing (flag, fired, lift_uncond, lift_within, computed_at) to a table and an
# endpoint that just reads it. Noted in the report as outstanding.
_TTL_HEAVY = 6 * 3600


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
    return await pg.get_pool()


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
    """Daily EQ bars for one symbol, on the CORPORATE-ACTION-ADJUSTED series.

    Series is pinned to EQ: a BE/BZ stint is circuit-capped at 2%/5% and can never be a 5-10%
    mover, so mixing them would corrupt the ranking.

    Prices come from nidp.prices_eod_adjusted, which covers the whole universe (2,747 of 2,747
    September EQ symbols) and is identical to the raw feed wherever there is no event — checked
    2026-10-03 over 55,630 September rows with a unit factor: zero differed, max |diff| 0.0000.
    Where there IS an event it is the only correct series: AASTHA's 1:1 bonus prints as -45.96% raw
    and +8.09% adjusted.

    `prev_c` is the previous ADJUSTED close, not the feed's prev_close column, because the two
    disagree exactly on the sessions that matter. The window is widened by a few sessions so the
    first bar still has a predecessor.

    This does NOT remove the need for the circuit-band check. The adjusted table is derived from
    nidp.corporate_actions, which holds 8 SPLIT and 9 BONUS symbols in total, so TAALTECH, PGIL,
    TCC, ESDS and the rest carry a unit factor and stay unadjusted.
    """
    rows = await conn.fetch(
        """
        WITH a AS (
            SELECT as_of_date, adj_open, adj_high, adj_low, adj_close, adj_volume,
                   cumulative_adj_factor,
                   lag(adj_close)  OVER (ORDER BY as_of_date) AS prev_adj,
                   lag(as_of_date) OVER (ORDER BY as_of_date) AS prev_dt,
                   bool_or(cumulative_adj_factor <> 1) OVER () AS has_event
              FROM nidp.prices_eod_adjusted
             WHERE symbol = $1 AND as_of_date BETWEEN $2::date - 10 AND $3)
        SELECT a.as_of_date, a.adj_open, a.adj_high, a.adj_low, a.adj_close,
               CASE WHEN a.has_event AND a.prev_adj > 0 AND a.prev_dt >= a.as_of_date - 7
                    THEN a.prev_adj ELSE p.prev_close END AS prev_adj,
               a.cumulative_adj_factor, p.volume, p.turnover
          FROM a JOIN nidp.prices_eod p
            ON p.symbol = $1 AND p.series = 'EQ' AND p.as_of_date = a.as_of_date
         WHERE a.as_of_date BETWEEN $2 AND $3
         ORDER BY a.as_of_date
        """, symbol, d0, d1)
    return [{
        "t": r["as_of_date"].isoformat(),
        "o": _f(r["adj_open"]), "h": _f(r["adj_high"]),
        "l": _f(r["adj_low"]),  "c": _f(r["adj_close"]),
        "prev_c": _f(r["prev_adj"]), "v": int(r["volume"] or 0),
        "turnover": _f(r["turnover"]),
        "adj_factor": _f(r["cumulative_adj_factor"]),
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
# The widest NSE circuit band is 20%; allow a little slack for rounding in the feed.
_BAND_MAX_PCT = 20.5
# The smallest rise worth testing: below the smallest matchable ratio nothing can ever match.
_CONSOLIDATION_MIN_RATIO = min(_CA_RATIOS) * (1 - _CA_TOL)


def _ca_suspect(close: float, prev: float) -> Optional[str]:
    """Flag a large fall whose price ratio sits near a common split/bonus ratio.

    The tolerance is 8%, not a hair's breadth, because a split and a real move land on the same
    session: TAALTECH 2026-09-22 printed 5714.60 -> 1185.40, a ratio of 4.82 — a 1:5 split with a
    genuine ~4% fall on top. A 2% tolerance missed it.

    This is a suspicion, not a determination: a true -50% crash has a ratio of 2.0 and will be
    flagged too. That is the acceptable error, because the caller can ask for these rows with
    include_ca=true, whereas an unflagged phantom crash silently becomes the dashboard's top mover.
    Only consulted when nidp.corporate_actions has nothing to say.

    It covers BOTH directions. The first version only looked at falls, which missed the mirror case:
    an unadjusted consolidation multiplies the price and shows up as an enormous RISE.
    """
    if not close or not prev or prev <= 0:
        return None
    pct = (close / prev - 1) * 100

    # A move beyond the circuit band is not possible in an ordinary banded session. NSE bands are
    # 2/5/10/20%, so anything past ~20% means the session was unbanded — a listing or relisting day —
    # or the feed is comparing two prices that are not comparable. Either way it is not a mover.
    # Found 2026-09: ESDS +111.75%, SSRETAIL +76.60%, KARAMTARA +38.58%, LUMINO +34.54%,
    # RENTOMOJO +32.24%, STEAMHOUSE +26.60%, POLICYBZR -36.00%.
    if abs(pct) > _BAND_MAX_PCT:
        return (f"{pct:+.1f}% exceeds the widest circuit band ({_BAND_MAX_PCT:.0f}%) — an ordinary "
                f"session cannot print this, so it is a listing/relisting day or an unadjusted "
                f"corporate action, not a move")

    # Falls: an unadjusted split or bonus. prev/close lands near the ratio.
    if close / prev <= 0.62:
        r = prev / close
        for k in _CA_RATIOS:
            if abs(r - k) / k <= _CA_TOL:
                return (f"price ratio {r:.2f} is within {_CA_TOL:.0%} of {k:g}:1 — suspected "
                        f"unadjusted split/bonus; no matching row in nidp.corporate_actions")
    # Rises: the mirror case, which the first version missed entirely. A reverse split or
    # consolidation multiplies the price, so close/prev lands near the ratio instead.
    if close / prev >= _CONSOLIDATION_MIN_RATIO:
        r = close / prev
        for k in _CA_RATIOS:
            if abs(r - k) / k <= _CA_TOL:
                return (f"price ratio {r:.2f} is within {_CA_TOL:.0%} of 1:{k:g} — suspected "
                        f"unadjusted consolidation/reverse split; no matching row in "
                        f"nidp.corporate_actions")
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
         WHERE status = 'final' AND target_session > $1 AND target_session <= $2
         ORDER BY target_session
        """, session - timedelta(days=ODDS_LOOKBACK * 2), session)
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


def _chart_span(bars: list[dict], d0: date, d1: date) -> tuple[Optional[int], Optional[int]]:
    """First and last index of `bars` that fall inside [d0, d1]; (None, None) when none do.

    `bars` is the long series the regression needs; the chart plots only this slice, so every index the
    client receives must be relative to `lo`. An index into the long series (e.g. 234) addresses no
    candle in a 10-bar chart and every marker silently vanishes into 'outside the plotted window'."""
    a, b = d0.isoformat(), d1.isoformat()
    inside = [j for j, x in enumerate(bars) if a <= x["t"] <= b]
    return (inside[0], inside[-1]) if inside else (None, None)


def _chart_index(k: Optional[int], lo: Optional[int], hi: Optional[int]) -> Optional[int]:
    """Absolute bar index -> index within the plotted slice; None if there is no bar or it is off-chart."""
    if k is None or lo is None or hi is None or k < lo or k > hi:
        return None
    return k - lo


async def _names(conn, symbols: list[str]) -> dict[str, str]:
    """Company names from nidp.sector_master (2,628 symbols). A symbol with no row (an ETF, say) simply has no name:
    the client shows the symbol and never an invented name."""
    syms = sorted({x for x in symbols if x})
    if not syms:
        return {}
    rows = await conn.fetch(
        "SELECT symbol, company_name FROM nidp.sector_master WHERE symbol = ANY($1::text[]) AND company_name IS NOT NULL", syms)
    return {r["symbol"]: r["company_name"].strip() for r in rows if r["company_name"] and r["company_name"].strip()}


# ── design's derived metrics ───────────────────────────────────────────────
def _avg(bars: list[dict], a: int, b: int, key: str = "v") -> Optional[float]:
    w = [bars[k][key] for k in range(max(0, a), min(len(bars), b + 1)) if bars[k].get(key)]
    return sum(w) / len(w) if w else None


def _exec_of(bars: list[dict], i: int, H: int = 3) -> dict:
    """v4's execOf(), verbatim.

    The point of it: the old headline (close the day before an event to close the day after) is mostly
    the overnight gap, which nobody could have traded. So each event now carries four figures and the
    one that matters is `net` — buy at the next open, sell at that close, minus costs.

    `out` is the outcome within H sessions of the next open, and NONE is its own state. It is never a
    zero return: "it reached neither +5% nor -5%" and "it returned 0%" are different facts.
    """
    n = len(bars) - 1
    if i + 1 > n:
        return {"gap": None, "intra": None, "re": None, "net": None,
                "out": "PENDING", "el": 0, "H": H, "cost": COST}
    nb, d = bars[i + 1], bars[i]
    o, end = nb["o"], min(n, i + H)
    prev_c = bars[max(0, i - 1)]["c"]
    gap = (o / d["c"] - 1) if (o and d["c"]) else None
    intra = (nb["c"] / o - 1) if (o and nb["c"]) else None
    re = (nb["c"] / prev_c - 1) if (prev_c and nb["c"]) else None
    up = dn = False
    if o:
        for k in range(i + 1, end + 1):
            # same ratio comparison as _head_hit, for the same floating-point reason
            if bars[k]["h"] and bars[k]["h"] / o - 1 >= 0.05 - _EPS:
                up = True
            if bars[k]["l"] and bars[k]["l"] / o - 1 <= -0.05 + _EPS:
                dn = True
    out = ("BOTH" if (up and dn) else "UP" if up else "DOWN" if dn
           else ("PENDING" if i + H > n else "NONE"))
    return {"gap": gap, "intra": intra, "re": re,
            "net": (intra - COST) if intra is not None else None,
            "out": out, "el": end - i, "H": H, "cost": COST}


def _leak(bars: list[dict], i: int) -> bool:
    """v4's `leak`: the price already drifted the move's way before the news landed.

    Measured as the 5 sessions ending at i-1 moving >=1.5% in the same direction as the event day's own
    close-to-close. Computed from bars only, so it is available wherever prices are.
    """
    if not 5 < i < len(bars):
        return False
    a, b, d = bars[i - 6]["c"], bars[i - 1]["c"], bars[i]
    if not (a and b and d["c"] and d["prev_c"]):
        return False
    drift, move = b / a - 1, d["c"] / d["prev_c"] - 1
    return abs(drift) >= 0.015 and (drift > 0) == (move > 0)


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
    y_, x_ = [y for y, _ in ys], [m for _, m in ys]
    r = _reg(y_, x_)
    if r is None:             # _reg's own REG_MIN_SESSIONS floor is 30; relax it for the 20D window
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
    r = dict(r)
    r["se"] = _slope_se(y_, x_, r["beta"])
    return r


def _slope_se(y: list[float], x: list[float], beta: float) -> Optional[float]:
    """Standard error of an OLS slope: sqrt( (1/(n-2)) * sum(resid^2) / sum((x-xbar)^2) ).

    None, not 0, when it cannot be computed (n<=2 or no spread in x): a zero SE would claim the beta is
    exact, which is the opposite of "we could not estimate its uncertainty"."""
    n = len(y)
    if n <= 2 or n != len(x):
        return None
    my, mx = sum(y) / n, sum(x) / n
    sxx = sum((v - mx) ** 2 for v in x)
    if sxx <= 0:
        return None
    sse = sum((yy - (my + beta * (xx - mx))) ** 2 for yy, xx in zip(y, x))
    return math.sqrt((sse / (n - 2)) / sxx)


def _rolling_pair(bars: list[dict], mk: list[Optional[float]], ti: int) -> dict:
    """Before/after 20D beta +/- 1 SE. The pair is published only when BOTH sides exist (v4 review-3 fix):
    a lone side invites reading a change in beta that was never measured. Withheld, not half-filled."""
    before, after = _rbeta(bars, mk, ti - 20, ti - 1), _rbeta(bars, mk, ti + 1, ti + 20)
    if before is None or after is None:
        return {"before": None, "after": None, "available": False,
                "reason": "ONE_SIDED" if (before or after) else "NO_BETA_EITHER_SIDE"}
    return {"before": before, "after": after, "available": True, "reason": None}


async def _deal_days_and_coverage(conn, symbol: str, d0: date, d1: date) -> dict:
    """ONE round trip for both lookups the detail view needs beyond the base queries.

    deal_days: every session a bulk or block deal printed on, for BULK D-1. Reaches 10 calendar days
    before the chart so an event on the first visible bar can still see the session before it.
    coverage: distinct symbols with a sector_master row vs distinct EQ symbols that traded in the window."""
    row = await conn.fetchrow(
        """
        WITH uni AS (SELECT DISTINCT symbol FROM nidp.prices_eod
                      WHERE series = 'EQ' AND as_of_date BETWEEN $2 AND $3)
        SELECT (SELECT count(*) FROM uni) AS total,
               (SELECT count(DISTINCT s.symbol) FROM nidp.sector_master s
                  JOIN uni u ON u.symbol = s.symbol) AS mapped,
               (SELECT array_agg(DISTINCT d) FROM (
                    SELECT as_of_date AS d FROM nidp.bulk_deals
                     WHERE symbol = $1 AND as_of_date BETWEEN $4 AND $3
                    UNION
                    SELECT as_of_date FROM nidp.block_deals
                     WHERE symbol = $1 AND as_of_date BETWEEN $4 AND $3) x) AS deal_days
        """, symbol, d0, d1, d0 - timedelta(days=10))
    total = int(row["total"] or 0)
    return {"deal_days": {d.isoformat() for d in (row["deal_days"] or [])},
            "coverage": ({"mapped": int(row["mapped"] or 0), "total": total} if total else None)}


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
                -- Rank on the CORPORATE-ACTION-ADJUSTED series. It covers the whole universe and
                -- is identical to the raw feed where there is no event, so this only ever changes
                -- the rows an event touched — which is exactly the set the raw ranking gets wrong.
                WITH a AS (
                    SELECT symbol, as_of_date, adj_open, adj_high, adj_low, adj_close,
                           cumulative_adj_factor,
                           lag(adj_close)   OVER w AS prev_adj,
                           lag(as_of_date)  OVER w AS prev_dt,
                           -- does this symbol have a corporate action anywhere in the window?
                           bool_or(cumulative_adj_factor <> 1)
                               OVER (PARTITION BY symbol) AS has_event
                      FROM nidp.prices_eod_adjusted
                     -- widened so the first session in the window still has a predecessor
                     WHERE as_of_date BETWEEN $1::date - 10 AND $2
                    WINDOW w AS (PARTITION BY symbol ORDER BY as_of_date)),
                b AS (
                    SELECT a.symbol, a.as_of_date, a.adj_open, a.adj_high, a.adj_low,
                           a.adj_close, a.cumulative_adj_factor, p.volume, p.turnover,
                           -- Use the adjusted lag ONLY for a symbol that actually has an event and
                           -- whose previous adjusted row is the session right before this one.
                           -- prices_eod_adjusted holds EQ rows only, so a BE/BZ stint leaves a hole
                           -- in it: INDIAGLYCO went EQ->BE on 2026-09-02 and back on 09-17, and a
                           -- bare lag() jumped the hole and printed -77.63% where the move was
                           -- -6.57%. Everywhere else the feed's own prev_close is right, and
                           -- adjusted equals raw anyway (55,630 September rows checked, 0 differ).
                           CASE WHEN a.has_event AND a.prev_adj > 0
                                     AND a.prev_dt >= a.as_of_date - 7
                                THEN 100 * (a.adj_close / a.prev_adj - 1)
                                ELSE 100 * (p.close_price / p.prev_close - 1) END AS pct,
                           CASE WHEN a.has_event AND a.prev_adj > 0
                                     AND a.prev_dt >= a.as_of_date - 7
                                THEN a.prev_adj ELSE p.prev_close END AS prev_adj
                      FROM a JOIN nidp.prices_eod p
                        ON p.symbol = a.symbol AND p.series = 'EQ'
                       AND p.as_of_date = a.as_of_date
                     WHERE a.as_of_date BETWEEN $1 AND $2
                       AND p.prev_close > 0 AND p.turnover >= $3)
                SELECT b.symbol, b.as_of_date, b.adj_open, b.adj_high, b.adj_low, b.adj_close,
                       b.prev_adj, b.volume, b.turnover, b.pct, b.cumulative_adj_factor,
                       c.action_type AS ca_type, c.ratio AS ca_ratio
                  FROM b
                  LEFT JOIN nidp.corporate_actions c
                         ON c.symbol = b.symbol AND c.ex_date BETWEEN b.as_of_date - 1
                                                                 AND b.as_of_date + 1
                 WHERE abs(b.pct) >= $4 AND ($5 = 0 OR sign(b.pct) {op} 0)
                 ORDER BY abs(b.pct) DESC
                 LIMIT $6
                """, frm, to, MIN_TURNOVER, min_abs_pct, sign, limit * 3)

            out, withheld = [], 0
            for r in rows:
                if len(out) >= limit:
                    break
                close, prev = _f(r["adj_close"]), _f(r["prev_adj"])
                suspect = None if r["ca_type"] else _ca_suspect(close, prev)
                if suspect and not include_ca:
                    withheld += 1
                    continue
                sess = r["as_of_date"]
                out.append({
                    "symbol": r["symbol"], "session": sess.isoformat(),
                    "pct": _f(r["pct"]), "close": close, "prev_close": prev,
                    "open": _f(r["adj_open"]), "high": _f(r["adj_high"]),
                    "low": _f(r["adj_low"]),
                    "volume": int(r["volume"] or 0), "turnover": _f(r["turnover"]),
                    "ca_flag": ({"type": r["ca_type"], "ratio": r["ca_ratio"]}
                                if r["ca_type"] else None),
                    "ca_suspect": suspect,
                    "adjusted": _f(r["cumulative_adj_factor"]) not in (None, 1.0),
                    "odds": await _odds_badge(conn, r["symbol"], sess),
                })
            nm = await _names(conn, [x["symbol"] for x in out])
            for x in out:
                x["name"] = nm.get(x["symbol"])
        res = {
            "from": frm.isoformat(), "to": to.isoformat(), "count": len(out),
            "withheld_ca_suspect": withheld, "lanes": LANES, "ranges": list(RANGE_DAYS),
            "filters": {"min_abs_pct": min_abs_pct, "direction": direction,
                        "min_turnover": MIN_TURNOVER, "include_ca": include_ca},
            "movers": out,
        }
        _cache_set(ck, res, _TTL_HEAVY)
        return res


# NOTE ON ORDER: these three sit ABOVE @router.get("/{symbol}") deliberately. FastAPI matches in
# registration order, so with /{symbol} first a request for /api/movers/calibration is matched as a
# stock named CALIBRATION and the analytics endpoints become unreachable. Keep them here.
# ── v4 analytics: one population, every number computed ──────────────────────────────────────────
async def _population(conn, d0: date, d1: date, head: str) -> dict:
    """The design's "one population": every session x name the model actually scored in the window.

    Calibration, the flag-lift card and the mirror list all read from this same set, which is the whole
    point of v4's review-3 fix — three panels that disagreed about their denominator are three panels
    that cannot be reconciled.
    """
    runs = await conn.fetch(
        """
        SELECT run_id, target_session FROM nidp.tpd_runs
         WHERE status = 'final' AND target_session BETWEEN $1 AND $2
         ORDER BY target_session
        """, d0, d1)
    if not runs:
        return {"rows": [], "sessions": 0, "reason": "NO_FINAL_RUN_IN_WINDOW"}
    by_run = {r["run_id"]: r["target_session"] for r in runs}
    est = await conn.fetch(
        """
        SELECT run_id, symbol, p, p_base_rate FROM nidp.tpd_run_estimates
         WHERE run_id = ANY($1::bigint[]) AND head = $2 AND p IS NOT NULL
        """, list(by_run), head)
    if not est:
        return {"rows": [], "sessions": len(runs), "reason": "NO_ESTIMATES_FOR_HEAD"}
    rows = [{"symbol": e["symbol"], "session": by_run[e["run_id"]],
             "p": _f(e["p"]), "base": _f(e["p_base_rate"])} for e in est]
    return {"rows": rows, "sessions": len(runs), "reason": None}


async def _bars_for(conn, symbols: list[str], d0: date, d1: date) -> dict[str, list[dict]]:
    """EQ bars for a set of symbols in one round trip, keyed by symbol and ordered by date."""
    out: dict[str, list[dict]] = {}
    if not symbols:
        return out
    for r in await conn.fetch(
        """
        SELECT symbol, as_of_date, open_price, high_price, low_price, close_price,
               prev_close, volume, turnover
          FROM nidp.prices_eod
         WHERE symbol = ANY($1::text[]) AND series = 'EQ' AND as_of_date BETWEEN $2 AND $3
         ORDER BY symbol, as_of_date
        """, symbols, d0, d1):
        out.setdefault(r["symbol"], []).append({
            "t": r["as_of_date"].isoformat(),
            "o": _f(r["open_price"]), "h": _f(r["high_price"]), "l": _f(r["low_price"]),
            "c": _f(r["close_price"]), "prev_c": _f(r["prev_close"]),
            "v": int(r["volume"] or 0), "turnover": _f(r["turnover"]),
        })
    return out


def _idx_of(bars: list[dict], session: date) -> Optional[int]:
    t = session.isoformat()
    for k, b in enumerate(bars):
        if b["t"] == t:
            return k
    return None


def _atr_pct(bars: list[dict], i: int, n: int = 14) -> Optional[float]:
    """Realised range as a % of close, over the n sessions ending at i. Used only to rank names into
    volatility deciles — the control the flag-lift card exists to apply."""
    a = max(1, i - n + 1)
    if i < a:
        return None
    tr = []
    for k in range(a, i + 1):
        h, l, pc = bars[k]["h"], bars[k]["l"], bars[k - 1]["c"]
        if h is None or l is None or not pc:
            continue
        tr.append(max(h - l, abs(h - pc), abs(l - pc)) / pc)
    # Require most of the window. Averaging 5 bars and calling it a 14-session ATR produces a number
    # that looks measured but is not, and these values rank names into the volatility deciles that
    # the flag-lift card controls on — a thin ATR there quietly corrupts every verdict.
    if len(tr) < max(3, (n * 2) // 3):
        return None
    return sum(tr) / len(tr)


def _flags_fired(bars: list[dict], i: int) -> set[str]:
    """Which of the design's price-derived flags fired on bar i. The two source-dependent ones
    (BULK DEAL D-1, INSIDER +/-3D) are decided by the caller, which knows whether the source exists."""
    out: set[str] = set()
    m = _event_metrics(bars, i)
    g = m["gap"]
    if g is not None and abs(g) >= 0.02:
        out.add("gap2")
        if abs(g) >= 0.03:
            out.add("gap3")
    # Only PRE-event information may count as a signal here. vol_post is avg(vol[i..i+2]) / base,
    # which overlaps the outcome window (the move is measured from the open of i+1), so a flag built
    # on it is partly measuring the move it claims to predict. Measured on staging 2026-10-03 the
    # look-ahead version scored vol>=2x at 1.687 and vol>=3x at 1.815 within volatility deciles —
    # the strongest flags on the card, and partly tautological. The timeline still SHOWS vol_post,
    # because describing what happened is a different job from claiming to have predicted it.
    vp = m["vol_pre"]
    if vp is not None:
        if vp >= 2:
            out.add("vol2")
        if vp >= 3:
            out.add("vol3")
    if m["flip"]:
        out.add("flip")
    if _leak(bars, i):
        out.add("leak")
    return out


def _head_hit(bar: dict, head: str) -> Optional[bool]:
    """Did the head's OWN event happen on this bar?

    This matters more than it looks. v4's calibration chart scores a flag against its outcome pill,
    which asks "+/-5% from the NEXT OPEN within 3 sessions" — a different horizon, a different
    reference price and two-sided instead of one-sided. Measured on staging 2026-10-03, scoring
    p_up5_1d that way reports the model under-predicting by 6.3x (mean p 0.0557 vs a 0.3498 realised
    rate), which says nothing about the model and everything about the mismatch.

    p_up5_1d means: on the target session, high >= prev_close * 1.05. One session, upside only. Scored
    that way the same population gives 0.0556 predicted against 0.0671 realised — a ratio of 0.83.
    """
    pc = bar.get("prev_c")
    if not pc:
        return None
    up, mag = head.startswith("p_up"), (0.10 if "10" in head else 0.05)
    v = bar["h"] if up else bar["l"]
    if v is None:
        return None
    # Compare the ratio, not the product: 100 * 1.1 is 110.00000000000001 in binary floating point,
    # so `high >= pc * 1.1` scored a high of exactly +10.000% as a MISS. That silently under-counts
    # realised hits right at the threshold, which is exactly where calibration is read.
    r = v / pc - 1
    return r >= mag - _EPS if up else r <= -mag + _EPS


def _verdict(lift: Optional[float], key: str) -> Optional[str]:
    """The design's cut-offs, applied to the COMPUTED within-decile lift. v4 applies them to its own
    sample constants; we never do."""
    if lift is None:
        return None
    if lift >= 1.5:
        return "PRE-PRICED" if key == "leak" else "SURVIVES"
    return "WEAK" if lift >= 1.25 else "DECORATION"


@router.get("/calibration")
async def calibration(
    request: Request,
    frm: date = Query(..., alias="from"),
    to: date = Query(..., description="window end (inclusive)"),
    head: str = Query("p_up5_1d", pattern="^p_(up|down)(5|10)_1d$"),
    horizon: int = Query(3),
) -> dict:
    """Does a 70% flag move 70% of the time? Predicted vs realised per probability band.

    PENDING is counted in the population but excluded from the bands: a name whose horizon has not
    finished has not told us anything yet, and scoring it as "did not move" would flatter the model.
    """
    H = horizon if horizon in HORIZONS else 3
    ck = f"cal:{frm}:{to}:{head}:{H}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    async with _lock(ck):
        if (hit := _cache_get(ck)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            pop = await _population(conn, frm, to, head)
            base = {"from": frm.isoformat(), "to": to.isoformat(), "head": head, "horizon": H,
                    "population": len(pop["rows"]), "pending_excluded": 0,
                    "available": False, "reason": pop["reason"], "over_prediction": None,
                    "bands": [], "min_band_n": CAL_MIN_N}
            if not pop["rows"]:
                _cache_set(ck, base, _TTL_HEAVY)
                return base
            syms = sorted({r["symbol"] for r in pop["rows"]})
            bars = await _bars_for(conn, syms, frm - timedelta(days=40), to + timedelta(days=60))
            resolved, pending = [], 0
            for r in pop["rows"]:
                bb = bars.get(r["symbol"]) or []
                i = _idx_of(bb, r["session"])
                if i is None:
                    continue
                hit = _head_hit(bb[i], head)
                if hit is None:
                    pending += 1
                    continue
                resolved.append((r["p"], hit))
            base["pending_excluded"] = pending
            if not resolved:
                base["reason"] = "NO_RESOLVED_OUTCOMES"
                _cache_set(ck, base, _TTL_HEAVY)
                return base
            edges = []
            lo = CAL_FROM
            while lo < 0.85:
                edges.append(lo)
                lo = round(lo + CAL_BAND, 10)
            out_bands = []
            for k, lo in enumerate(edges):
                top = (k == len(edges) - 1)
                hi = None if top else round(lo + CAL_BAND, 10)
                xs = [m for p_, m in resolved if p_ is not None and p_ >= lo and (top or p_ < hi)]
                n = len(xs)
                out_bands.append({
                    "lo": lo, "hi": hi, "n": n,
                    "predicted": round(lo + CAL_BAND / 2, 4),
                    # below CAL_MIN_N a rate is noise; null, never a number that looks measured
                    "realised": (sum(xs) / n) if n >= CAL_MIN_N else None,
                })
            num = sum(b["predicted"] * b["n"] for b in out_bands if b["realised"] is not None)
            den = sum(b["realised"] * b["n"] for b in out_bands if b["realised"] is not None)
            base.update({
                "available": True, "reason": None, "bands": out_bands,
                "scored_as": f"the head's own event on the target session ({head})",
                "note": ("Scored against what the head actually predicts — one session, one side, "
                         "against the previous close. The outcome pills on events ask a different "
                         "question (+/-5% from the next open within the horizon) and the two are not "
                         "comparable."),
                "over_prediction": (num / den) if den > 0 else None,
                "resolved": len(resolved),
            })
            _cache_set(ck, base, _TTL_HEAVY)
            return base


@router.get("/flag-lift")
async def flag_lift(
    request: Request,
    frm: date = Query(..., alias="from"),
    to: date = Query(..., description="window end (inclusive)"),
    head: str = Query("p_up5_1d", pattern="^p_(up|down)(5|10)_1d$"),
    horizon: int = Query(3),
) -> dict:
    """Which flags still add information once volatility is controlled for.

    The volume and gap flags mostly fire because the stock is volatile, and the model already uses
    volatility — so an unconditional lift flatters them. Each flag is therefore reported twice: across
    the whole population, and within volatility deciles. Both numbers are computed here; v4's own LIFT
    table is sample data and is never read.
    """
    H = horizon if horizon in HORIZONS else 3
    ck = f"lift:{frm}:{to}:{head}:{H}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    async with _lock(ck):
        if (hit := _cache_get(ck)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            pop = await _population(conn, frm, to, head)
            res = {"from": frm.isoformat(), "to": to.isoformat(), "head": head, "horizon": H,
                   "population": 0, "deciles": DECILES, "flags": []}
            has_ins = await conn.fetchval("SELECT to_regclass('nidp.insider_sast') IS NOT NULL")
            deal_tbl = await conn.fetchval(
                "SELECT to_regclass('nidp.bulk_deals') IS NOT NULL"
                "   AND to_regclass('nidp.block_deals') IS NOT NULL")
            if not pop["rows"]:
                res["flags"] = [{"key": k, "label": lab, "available": False,
                                 "reason": pop["reason"], "lift_uncond": None,
                                 "lift_within": None, "n": 0, "verdict": None}
                                for k, lab in FLAG_DEFS]
                _cache_set(ck, res, _TTL_HEAVY)
                return res
            syms = sorted({r["symbol"] for r in pop["rows"]})
            bars = await _bars_for(conn, syms, frm - timedelta(days=60), to + timedelta(days=60))
            # BULK DEAL D-1: a bulk or block deal printed on the session before the flag day.
            deal_days: set[tuple[str, str]] = set()
            if deal_tbl:
                for r in await conn.fetch(
                    """
                    SELECT symbol, as_of_date FROM nidp.bulk_deals
                     WHERE symbol = ANY($1::text[]) AND as_of_date BETWEEN $2 AND $3
                    UNION
                    SELECT symbol, as_of_date FROM nidp.block_deals
                     WHERE symbol = ANY($1::text[]) AND as_of_date BETWEEN $2 AND $3
                    """, syms, frm - timedelta(days=60), to):
                    deal_days.add((r["symbol"], r["as_of_date"].isoformat()))
            obs = []
            for r in pop["rows"]:
                bb = bars.get(r["symbol"]) or []
                i = _idx_of(bb, r["session"])
                if i is None:
                    continue
                e = _exec_of(bb, i, H)
                if e["out"] == "PENDING":
                    continue
                vol = _atr_pct(bb, i)
                if vol is None:
                    continue
                ff = _flags_fired(bb, i)
                if deal_tbl and i > 0 and (r["symbol"], bb[i - 1]["t"]) in deal_days:
                    ff.add("d1")
                obs.append({"flags": ff, "moved": e["out"] != "NONE", "vol": vol})
            res["population"] = len(obs)
            if len(obs) < CAL_MIN_N:
                res["flags"] = [{"key": k, "label": lab, "available": False,
                                 "reason": "POPULATION_TOO_SMALL", "lift_uncond": None,
                                 "lift_within": None, "n": len(obs), "verdict": None}
                                for k, lab in FLAG_DEFS]
                _cache_set(ck, res, _TTL_HEAVY)
                return res
            obs.sort(key=lambda x: x["vol"])
            for d, x in enumerate(obs):
                x["dec"] = min(DECILES - 1, (d * DECILES) // len(obs))
            base_rate = sum(1 for x in obs if x["moved"]) / len(obs)
            out = []
            for key, label in FLAG_DEFS:
                if key == "d1" and not deal_tbl:
                    out.append({"key": key, "label": label, "available": False,
                                "reason": "NO_BULK_DEAL_TABLE", "lift_uncond": None,
                                "lift_within": None, "n": 0, "verdict": None})
                    continue
                if key == "ins" and not has_ins:
                    out.append({"key": key, "label": label, "available": False,
                                "reason": "NIDP_INSIDER_SAST_NOT_BACKFILLED", "lift_uncond": None,
                                "lift_within": None, "n": 0, "verdict": None})
                    continue
                hit_rows = [x for x in obs if key in x["flags"]]
                n = len(hit_rows)
                if n < CAL_MIN_N or base_rate <= 0:
                    out.append({"key": key, "label": label, "available": False,
                                "reason": "TOO_FEW_FIRINGS", "lift_uncond": None,
                                "lift_within": None, "n": n, "verdict": None})
                    continue
                unc = (sum(1 for x in hit_rows if x["moved"]) / n) / base_rate
                # within-decile: compare like with like, then weight by how many firings each decile held
                num = den = 0.0
                by_decile = []          # the design's D1..D10 strip: one entry per volatility decile, real numbers only
                for d in range(DECILES):
                    dd = [x for x in obs if x["dec"] == d]
                    ff = [x for x in dd if key in x["flags"]]
                    br = (sum(1 for x in dd if x["moved"]) / len(dd)) if dd else None
                    hit = (sum(1 for x in ff if x["moved"]) / len(ff)) if ff else None
                    # A lift needs firings AND a non-zero base rate in that decile; otherwise it is None, never 0.
                    cell = (hit / br) if (hit is not None and br) else None
                    by_decile.append({"decile": d + 1, "firings": len(ff), "moved": sum(1 for x in ff if x["moved"]),
                                      "base_rate": br, "lift": cell})
                    if not ff or not dd:
                        continue
                    if not br or br <= 0:
                        continue
                    num += (sum(1 for x in ff if x["moved"]) / len(ff)) / br * len(ff)
                    den += len(ff)
                within = (num / den) if den > 0 else None
                out.append({"key": key, "label": label, "available": True, "reason": None,
                            "lift_uncond": unc, "lift_within": within, "n": n,
                            "verdict": _verdict(within, key), "by_decile": by_decile})
            res["flags"] = out
            res["base_rate"] = base_rate
            # the BASE row of the strip: how often a name in each volatility decile moved at all
            res["decile_base"] = [
                {"decile": d + 1, "n": sum(1 for x in obs if x["dec"] == d),
                 "base_rate": (sum(1 for x in obs if x["dec"] == d and x["moved"])
                               / max(1, sum(1 for x in obs if x["dec"] == d)))}
                for d in range(DECILES)]
            _cache_set(ck, res, _TTL_HEAVY)
            return res


@router.get("/flagged")
async def flagged_no_move(
    request: Request,
    frm: date = Query(..., alias="from"),
    to: date = Query(..., description="window end (inclusive)"),
    head: str = Query("p_up5_1d", pattern="^p_(up|down)(5|10)_1d$"),
    horizon: int = Query(3),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """The other side of the model: names it flagged that did NOT move.

    v1 could only show how many movers the model caught, so it could never show how often its flags were
    wrong. The list keeps NONE first and PENDING after, exactly as the design re-derives it when the
    horizon changes; a name that reached +/-5% leaves the list.
    """
    H = horizon if horizon in HORIZONS else 3
    ck = f"flagged:{frm}:{to}:{head}:{H}:{limit}"
    if (hit := _cache_get(ck)) is not None:
        return hit
    async with _lock(ck):
        if (hit := _cache_get(ck)) is not None:
            return hit
        pool = await _pool()
        async with pool.acquire() as conn:
            pop = await _population(conn, frm, to, head)
            res = {"from": frm.isoformat(), "to": to.isoformat(), "head": head, "horizon": H,
                   "cutoff": ODDS_CUTOFF, "count": 0, "flagged_total": 0, "moved_late": 0,
                   "outcomes": {k: 0 for k in ("UP", "DOWN", "BOTH", "NONE", "PENDING")},
                   "available": False, "reason": pop["reason"], "rows": []}
            flagged = [r for r in pop["rows"] if r["p"] is not None and r["p"] >= ODDS_CUTOFF]
            res["flagged_total"] = len(flagged)
            if not flagged:
                if res["reason"] is None:
                    res["reason"] = "NO_NAME_ABOVE_CUTOFF"
                _cache_set(ck, res, _TTL_HEAVY)
                return res
            syms = sorted({r["symbol"] for r in flagged})
            bars = await _bars_for(conn, syms, frm - timedelta(days=40), to + timedelta(days=60))
            none_rows, pend_rows = [], []
            nm = await _names(conn, syms)
            for r in sorted(flagged, key=lambda x: -(x["p"] or 0)):
                bb = bars.get(r["symbol"]) or []
                i = _idx_of(bb, r["session"])
                if i is None:
                    continue
                e = _exec_of(bb, i, H)
                res["outcomes"][e["out"]] += 1
                if e["out"] not in ("NONE", "PENDING"):
                    continue
                row = {"symbol": r["symbol"], "name": nm.get(r["symbol"]), "session": r["session"].isoformat(),
                       "model_p": r["p"], "model_head": head, "base_rate": r["base"],
                       "pct": ((bb[i]["c"] / bb[i]["prev_c"] - 1) * 100
                               if (bb[i]["prev_c"] and bb[i]["c"]) else None),
                       "close": bb[i]["c"], "prev_close": bb[i]["prev_c"],
                       "open": bb[i]["o"], "high": bb[i]["h"], "low": bb[i]["l"],
                       "volume": bb[i]["v"], "turnover": bb[i]["turnover"],
                       "ca_flag": None, "ca_suspect": None, "exec": e,
                       "odds": {"state": "CAUGHT", "score": r["p"], "base_rate": r["base"],
                                "head": head, "run_session": r["session"].isoformat(),
                                "runs_in_window": pop["sessions"], "cutoff": ODDS_CUTOFF}}
                (none_rows if e["out"] == "NONE" else pend_rows).append(row)
            rows = (none_rows + pend_rows)[:limit]
            res.update({"available": True, "reason": None, "rows": rows, "count": len(rows),
                        "moved_late": len(flagged) - len(none_rows) - len(pend_rows)})
            _cache_set(ck, res, _TTL_HEAVY)
            return res



@router.get("/{symbol}")
async def mover_detail(
    request: Request,
    symbol: str,
    session: date = Query(..., description="the move session T the timeline centres on"),
    range_: str = Query("T7", alias="range", pattern="^(1D|T7|1M|3M|1Y|custom)$"),
    frm: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    horizon: int = Query(3),
) -> dict:
    """Chart + event lanes for one mover, centred on T. `range` matches the design's chart legend;
    `custom` takes from/to. The regression window always extends further back than the chart so
    beta is estimated on history, not on the window being explained."""
    symbol = symbol.strip().upper()
    H = horizon if horizon in HORIZONS else 3
    if range_ == "custom":
        if not frm or not to or to < frm:
            raise HTTPException(400, "range=custom needs from<=to")
        d0, d1 = frm, to
    else:
        n = RANGE_DAYS[range_]
        d0, d1 = session - timedelta(days=n), session + timedelta(days=n)
    ck = f"detail:{symbol}:{session}:{range_}:{d0}:{d1}:{H}"
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

            aux = await _deal_days_and_coverage(conn, symbol, d0, d1)
            deal_days = aux["deal_days"]
            idx = {b["t"]: k for k, b in enumerate(bars)}
            lo, hi = _chart_span(bars, d0, d1)
            # insider/SAST rows -> the bar each one lands on; empty when nidp.insider_sast is absent,
            # in which case INSIDER +/-3D is simply never raised (no source != no activity).
            ins_bars: list[tuple[str, int]] = []
            for ie in ins["events"]:
                ik = idx.get(ie["date"])
                if ik is None:
                    ik = next((j for j, b in enumerate(bars) if b["t"] >= ie["date"]), None)
                if ik is not None:
                    ins_bars.append((ie["id"], ik))
            for e in events:
                k = idx.get(e["date"])
                if k is None:                      # a holiday-dated filing: attach to the next session
                    k = next((j for j, b in enumerate(bars) if b["t"] >= e["date"]), None)
                    e["session_shifted"] = k is not None
                e["bar_index"] = _chart_index(k, lo, hi)   # relative to the plotted slice; k stays absolute below
                e["kind"], e["kind_note"] = _kind_of(e.get("title", ""), e.get("sub", ""))
                ty = _TYPE.get(e["type"], _TYPE["news"])
                e["lane"], e["type_label"], e["glyph"] = ty["lane"], ty["label"], ty["glyph"]
                # metrics BEFORE flags: _flags_of reads gap/vol_pre/vol_post, which are
                # _event_metrics keys. Fed the bare event it saw None for all three and
                # silently returned [] for every event on the timeline.
                e["metrics"] = _event_metrics(bars, k) if k is not None else None
                e["flags"] = _flags_of(e["metrics"] or {})
                # `exec` is None, not a zeroed dict, when the event has no bar to trade against.
                e["exec"] = _exec_of(bars, k, H) if k is not None else None
                if k is not None:
                    if _leak(bars, k):
                        e["flags"].append({"label": "LEAK", "tone": "amber"})
                    if k > 0 and bars[k - 1]["t"] in deal_days:
                        e["flags"].append({"label": "BULK D-1", "tone": "amber"})
                    # an insider row is not "near" itself, so it is excluded from its own flag
                    if any(abs(ik - k) <= 3 for iid, ik in ins_bars if iid != e["id"]):
                        e["flags"].append({"label": "INSIDER ±3D", "tone": "amber"})

            chart = bars[lo:hi + 1] if lo is not None else []
            tb = bars[ti]
            res = {
                "symbol": symbol, "name": (await _names(conn, [symbol])).get(symbol),
                "session": session.isoformat(), "range": range_, "horizon": H,
                "from": d0.isoformat(), "to": d1.isoformat(),
                "header": {
                    "pct": ((tb["c"] / tb["prev_c"] - 1) * 100
                            if tb["prev_c"] else None),
                    "open": tb["o"], "high": tb["h"], "low": tb["l"], "close": tb["c"],
                    "prev_close": tb["prev_c"], "volume": tb["v"], "turnover": tb["turnover"],
                },
                "bars": chart,
                # The label says what the series IS. nidp.index_eod holds the configured index itself
                # (verified: Nifty 50, 144 rows from 2026-02-06), so it is not a proxy. If it is ever
                # missing the leg is withheld with a reason; an ETF is never quietly swapped in and
                # then called "Nifty 50".
                "market": {"name": MARKET_INDEX, "label": MARKET_INDEX, "is_proxy": False,
                           "series": [mkt.get(b["t"]) for b in chart],
                           "available": bool(mkt),
                           "reason": None if mkt else "MARKET_INDEX_NOT_IN_INDEX_EOD"},
                "sector": {"name": sector_idx,
                           "series": [sct.get(b["t"]) for b in chart],
                           "available": bool(sct),
                           "reason": None if sector_idx else "SYMBOL_NOT_IN_SECTOR_MASTER",
                           # computed per request, never hardcoded; None when no EQ symbol traded
                           "coverage": aux["coverage"]},
                "regression": reg,
                "rolling_beta": _rolling_pair(bars, mk, ti),
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
                pinned["kind"], pinned["kind_note"] = _kind_of(pinned.get("title", ""), pinned.get("sub", ""))
                ty = _TYPE.get(pinned["type"], _TYPE["news"])
                pinned["lane"], pinned["type_label"], pinned["glyph"] = ty["lane"], ty["label"], ty["glyph"]
                pinned["metrics"] = _event_metrics(bars, k) if k is not None else None
                pinned["flags"] = _flags_of(pinned["metrics"] or {})

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
                "rolling_beta": _rolling_pair(bars, mk, ei),
                "model": await _odds_badge(conn, symbol, session),
                "disclaimer": ("Attribution of realised return, not a causal claim: direction "
                               "around events is not predictable in this dataset."),
            }
        _cache_set(ck, res)
        return res
