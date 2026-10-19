"""DaaS — market reads for the Smart trading desk (sector index returns, bulk/block deals, F&O OI build-up).

    GET /v1/desk/sector-returns                         NSE sectoral indices: latest close and 1-day / 1-week / 1-month returns,
                                                        and breadth within each index that has a constituent list
    GET /v1/desk/sector-constituents?index=             one sector index's constituents, each with its move on the
                                                        index's latest close day, and the breadth within it
    GET /v1/desk/deals?days=5&kind=all&symbol=&limit=   NSE bulk and block deals over the last `days` calendar days
    GET /v1/desk/fno-buildup?date=                      stock-futures open-interest build-up, one row per underlying,
                                                        plus the index futures (`indices`)
    GET /v1/desk/filings?family=calls|ownership|exchange filings whose exchange subject line is in one family
    GET /v1/desk/event-sources?ids=a,b                  each filing's source records, timing, issuer, industry, peers

Prefix /desk so these never fall under /fno/{symbol}. Read-only. Every answer names its source table and the
as-of date; a missing figure is null, never 0. No data → 200 with an empty list and the as-of date.

Definitions
  sector-returns  ret_Nd_pct = close / (the close N rows earlier in THAT index's own series) − 1, in percent;
                  N = 1, 5, 21 sessions (1d / 1w / 1m). null when the index has fewer than N + 1 closes. `date` on each
                  row is that index's own latest close, so a lagging index is visible rather than mixed in silently.
  in-sector       only for an index whose list is in nidp.index_constituents (its latest list). A constituent's move
  breadth         is its bhavcopy close vs the bhavcopy's own previous close (nidp.prices_eod.prev_close) on the
                  index's latest close day: above = advance, below = decline, equal = unchanged; no bar that day =
                  no_price, never unchanged. An index without a list has no breadth (absent, not zero).
  deals           the window is `days` calendar days ending at the latest deal date across BOTH tables (a session
                  with no block deals is a real empty, not a reason to slide the window back).
                  value_cr = quantity × avg_price ÷ 1e7 (₹ crore).
  fno-buildup     stock futures (instrument_type 'STF') on the latest or given day, one row per underlying:
                  price_chg_pct  nearest expiry's close_price vs its prev_close_price
                  oi / oi_chg    open_interest / change_in_oi summed over every expiry, so a roll near expiry does not
                                 read as unwinding (null if any expiry's figure is missing)
                  oi_chg_pct     oi_chg ÷ (oi − oi_chg), the previous day's OI, in percent
                  label          price↑ OI↑ long_buildup · price↓ OI↑ short_buildup · price↑ OI↓ short_covering ·
                                 price↓ OI↓ long_unwinding · otherwise (either flat) neutral. null when the price or
                                 OI change is missing (counted as `no_data`). A reading of two figures, not a record
                                 of who traded.
                  cash_*         the stock's own close, previous close and volume that day (prices_eod); for an index
                                 future, the index close and its points change (index_eod)
                  cash_confirmation  'confirms' when the near future and the cash market moved the same way that
                                 day, 'diverges' when opposite; null when either is missing or flat
                  vol_z20        the latest stock_features_daily z-score of volume against 20 sessions, within a week
                                 of the day (its date in vol_z20_date)
                  fno_eligible   the NSE F&O master (security_reference_daily, fo_mktlots.csv) on or before the day
                  fut_contracts  futures contracts traded that day over every expiry (the bhavcopy's TtlTradgVol is in
                                 contracts: traded value ÷ (volume × price) = the lot size, checked on staging)
                  risk_flags     expiry_week, rollover, no_cash_price (RISK_FLAG_TEXT)
                  setup_quality  null: no validated model of these readings exists
                  intraday       15-minute confirmation is unavailable: no intraday OI is collected
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify, normalise_symbol, parse_date
from nidp.services.daas_api.routers.flows import DEALS_SOURCE, pct_of_shares, read_deals

DEALS_DISCLOSURE = ("Every row is NSE's own bulk or block deal disclosure, published after the close. "
                    "No institutional activity is inferred here.")

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

# ── sector returns ───────────────────────────────────────────────────────────

# NSE sectoral indices as named in nidp.index_eod (checked on staging 2026-10-14), each with the sector label the
# desk shows. One index per industry; sub-segments of these (NBFC, Insurance, Hospitals…) are left out.
SECTOR_INDICES: Tuple[Tuple[str, str], ...] = (
    ("Nifty Auto", "Auto"),
    ("Nifty Bank", "Banks"),
    ("Nifty Financial Services", "Financial Services"),
    ("Nifty FMCG", "FMCG"),
    ("Nifty IT", "IT"),
    ("Nifty Media", "Media"),
    ("Nifty Metal", "Metals"),
    ("Nifty Pharma", "Pharma"),
    ("Nifty PSU Bank", "PSU Banks"),
    ("Nifty Private Bank", "Private Banks"),
    ("Nifty Realty", "Realty"),
    ("Nifty Energy", "Energy"),
    ("Nifty Oil & Gas", "Oil & Gas"),
    ("Nifty Healthcare Index", "Healthcare"),
    ("Nifty Consumer Durables", "Consumer Durables"),
    ("Nifty Capital Goods", "Capital Goods"),
    ("Nifty Cement", "Cement"),
    ("Nifty Chemicals", "Chemicals"),
    ("Nifty Power", "Power"),
    ("Nifty Telecommunications", "Telecom"),
)
SESSIONS: Dict[str, int] = {"1d": 1, "1w": 5, "1m": 21}
_SECTOR_SOURCE = "NSE index close (nidp.index_eod)"

# The latest `$2` closes of each index, newest first. DISTINCT ON keeps one row per day should a second source
# ever load the same index, so "N rows earlier" stays "N sessions earlier".
SECTOR_SQL = """
    SELECT n.index_name, e.as_of_date, e.close_price
      FROM unnest($1::text[]) AS n(index_name)
      CROSS JOIN LATERAL (
            SELECT as_of_date, close_price
              FROM (SELECT DISTINCT ON (as_of_date) as_of_date, close_price
                      FROM nidp.index_eod
                     WHERE index_name = n.index_name AND close_price IS NOT NULL
                     ORDER BY as_of_date DESC, source) d
             ORDER BY as_of_date DESC
             LIMIT $2
      ) e
     ORDER BY n.index_name, e.as_of_date DESC
"""


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pct_return(close: Optional[float], base: Optional[float]) -> Optional[float]:
    """(close ÷ base − 1) × 100 to 2 decimals; None when either is missing or the base is not positive."""
    if close is None or base is None or base <= 0:
        return None
    return round((close / base - 1.0) * 100.0, 2)


def sector_row(index_name: str, sector: str, closes: Sequence[Tuple[date, float]]) -> Dict[str, Any]:
    """One sector from its closes, newest first. Returns are against the close N rows earlier in this series."""
    latest_day, latest = (closes[0][0], closes[0][1]) if closes else (None, None)
    row: Dict[str, Any] = {"index": index_name, "sector": sector,
                           "date": latest_day.isoformat() if latest_day else None, "close": latest}
    for key, n in SESSIONS.items():
        row[f"ret_{key}_pct"] = pct_return(latest, closes[n][1]) if len(closes) > n else None
    return row


@router.get("/sector-returns", summary="NSE sectoral indices: close and 1d / 1w / 1m returns")
async def sector_returns() -> Dict[str, Any]:
    names = [name for name, _ in SECTOR_INDICES]
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SECTOR_SQL, names, max(SESSIONS.values()) + 1)
    series: Dict[str, List[Tuple[date, float]]] = {}
    for r in rows:
        close = _num(r["close_price"])
        if close is not None:
            series.setdefault(r["index_name"], []).append((r["as_of_date"], close))
    sectors = [sector_row(name, label, series.get(name, [])) for name, label in SECTOR_INDICES]
    days = [s["date"] for s in sectors if s["date"]]
    priced = [(name, series[name][0][0]) for name, _ in SECTOR_INDICES if series.get(name)]
    by_index: Dict[str, Dict[str, Any]] = {}
    if priced:
        async with pool.acquire() as conn:
            members = await conn.fetch(CONSTITUENTS_SQL, [n for n, _ in priced], [d for _, d in priced])
        grouped: Dict[str, List[Any]] = {}
        for r in members:
            grouped.setdefault(r["index_name"], []).append(r)
        for name, rows_ in grouped.items():
            by_index[name] = {"list_date": jsonify(rows_[0]["list_date"]), "date": jsonify(rows_[0]["on_date"]),
                              **sector_breadth([constituent_row(r) for r in rows_])}
    return {"as_of": max(days) if days else None, "source": _SECTOR_SOURCE, "sessions": dict(SESSIONS),
            "sectors": sectors,
            "in_sector_breadth": {"source": _CONSTITUENTS_SOURCE, "rule": BREADTH_RULE, "indices": by_index}}


# ── constituents and breadth within a sector ─────────────────────────────────

_CONSTITUENTS_SOURCE = "NSE index lists (nidp.index_constituents) with NSE bhavcopy closes (nidp.prices_eod)"
BREADTH_RULE = ("advance = a constituent that closed above its previous close (bhavcopy prev_close) on the index's "
                "latest close day; decline = below; unchanged = equal; no price = no bar that day, never counted as unchanged")
_INDEX_PATTERN = r"^[A-Za-z0-9 &\-]+$"

# $1 index names, $2 the day to price each one on (that index's own latest close day). One row per constituent of the
# index's LATEST list; the price columns are NULL when the stock has no bar that day. One bar per stock and day, the EQ
# series first should a stock ever carry two.
CONSTITUENTS_SQL = """
    SELECT q.index_name, q.on_date, l.as_of_date AS list_date, l.symbol, l.company_name, l.industry, l.weight_pct,
           p.close_price, p.prev_close
      FROM unnest($1::text[], $2::date[]) AS q(index_name, on_date)
      JOIN LATERAL (
            SELECT c.as_of_date, c.symbol, c.company_name, c.industry, c.weight_pct
              FROM nidp.index_constituents c
             WHERE c.index_name = q.index_name
               AND c.as_of_date = (SELECT MAX(m.as_of_date) FROM nidp.index_constituents m
                                    WHERE m.index_name = q.index_name)
      ) l ON TRUE
      LEFT JOIN LATERAL (
            SELECT pe.close_price, pe.prev_close
              FROM nidp.prices_eod pe
             WHERE pe.symbol = l.symbol AND pe.as_of_date = q.on_date
             ORDER BY (pe.series = 'EQ') DESC, pe.series
             LIMIT 1
      ) p ON TRUE
     ORDER BY q.index_name, l.weight_pct DESC NULLS LAST, l.symbol
"""

INDEX_LATEST_SQL = """
    SELECT MAX(as_of_date) FROM nidp.index_eod WHERE index_name = $1 AND close_price IS NOT NULL
"""


def constituent_row(r: Any) -> Dict[str, Any]:
    """One constituent and its move on the day it was priced on; the move is null without both closes."""
    close, prev = _num(r["close_price"]), _num(r["prev_close"])
    move = None
    if close is not None and prev is not None:
        move = "advance" if close > prev else "decline" if close < prev else "unchanged"
    return {"symbol": r["symbol"], "company_name": r["company_name"], "industry": r["industry"],
            "weight_pct": _num(r["weight_pct"]), "close": close, "prev_close": prev,
            "change_pct": pct_return(close, prev), "move": move}


def sector_breadth(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Counts over constituent_row()s. A constituent with no price is `no_price`, never unchanged."""
    out = {"members": len(rows), "advances": 0, "declines": 0, "unchanged": 0, "no_price": 0}
    key = {"advance": "advances", "decline": "declines", "unchanged": "unchanged"}
    for r in rows:
        out[key.get(r["move"], "no_price")] += 1
    return out


@router.get("/sector-constituents", summary="One sector index's constituents with their latest move, and breadth within it")
async def sector_constituents(
    index: str = Query(..., min_length=3, max_length=60, pattern=_INDEX_PATTERN, description="e.g. 'Nifty Bank'"),
) -> Dict[str, Any]:
    labels = dict(SECTOR_INDICES)
    name = next((n for n in labels if n.lower() == index.strip().lower()), None)
    out: Dict[str, Any] = {"index": name or index.strip(), "sector": labels.get(name) if name else None,
                           "available": False, "reason": None, "list_date": None, "date": None,
                           "source": _CONSTITUENTS_SOURCE, "rule": BREADTH_RULE, "breadth": None, "count": 0, "rows": []}
    if name is None:
        out["reason"] = "not one of the desk's sector indices"
        return out
    pool = await get_pool()
    async with pool.acquire() as conn:
        day = await conn.fetchval(INDEX_LATEST_SQL, name)
        members = await conn.fetch(CONSTITUENTS_SQL, [name], [day])
    if not members:
        out["reason"] = f"no constituent list for {name} in nidp.index_constituents"
        out["date"] = jsonify(day)
        return out
    rows = [constituent_row(r) for r in members]
    out.update({"available": True, "list_date": jsonify(members[0]["list_date"]), "date": jsonify(day),
                "breadth": sector_breadth(rows), "count": len(rows), "rows": rows})
    return out


# ── bulk and block deals ─────────────────────────────────────────────────────
# The rows and their enrichment come from the ONE deals reader in flows.py (read_deals); this route only fixes the
# window: `days` calendar days ending at the latest deal date across both tables.

_DEALS_SOURCE = DEALS_SOURCE
DEALS_MAX_DAYS = 30
DEALS_MAX_LIMIT = 5_000

DEALS_LATEST_SQL = """
    SELECT GREATEST((SELECT MAX(as_of_date) FROM nidp.bulk_deals),
                    (SELECT MAX(as_of_date) FROM nidp.block_deals)) AS d
"""

_SIDE = {"BUY": "BUY", "B": "BUY", "SELL": "SELL", "S": "SELL"}


def _get(r: Any, key: str) -> Any:
    """A column that may be absent (an older reader, a test row): None rather than a KeyError."""
    try:
        return r[key]
    except (KeyError, IndexError):
        return None


def deal_row(r: Any) -> Dict[str, Any]:
    qty, price = r["quantity"], _num(r["avg_price"])
    value_cr = round(qty * price / 1e7, 2) if qty is not None and price is not None else None
    close_day = _num(_get(r, "close_on_day"))
    return {
        "date": jsonify(r["as_of_date"]),
        "kind": r["kind"],
        "symbol": r["symbol"],
        "client_name": r["client_name"],
        "side": _SIDE.get((r["deal_type"] or "").strip().upper()),
        "quantity": int(qty) if qty is not None else None,
        "avg_price": price,
        "value_cr": value_cr,
        # §6.6: share of the company, the market price around the deal, and when Nivesh loaded it. All null when the
        # warehouse has no figure; nothing is filled in.
        "total_shares": int(_get(r, "total_shares")) if _get(r, "total_shares") is not None else None,
        "shares_period_end": jsonify(_get(r, "shares_period_end")),
        "pct_of_shares": pct_of_shares(qty, _get(r, "total_shares")),
        "close_on_day": close_day,
        "prev_close": _num(_get(r, "prev_close")),
        "next_date": jsonify(_get(r, "next_date")),
        "next_close": _num(_get(r, "next_close")),
        "price_vs_close_pct": pct_return(price, close_day),
        "ingested_at": jsonify(_get(r, "ingested_at")),
        "disclosure": "exchange",
    }


@router.get("/deals", summary="NSE bulk and block deals over the last N calendar days")
async def deals(
    days: int = Query(5, ge=1, le=DEALS_MAX_DAYS, description="Calendar days ending at the latest deal date"),
    kind: Literal["all", "bulk", "block"] = Query("all"),
    symbol: Optional[str] = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&\-]+$"),
    limit: int = Query(500, ge=1, le=DEALS_MAX_LIMIT),
) -> Dict[str, Any]:
    sym = normalise_symbol(symbol) if symbol else None
    out: Dict[str, Any] = {"as_of": None, "from": None, "days": days, "kind": kind, "symbol": sym,
                           "source": _DEALS_SOURCE, "disclosure": DEALS_DISCLOSURE, "count": 0, "total": 0, "rows": []}
    pool = await get_pool()
    async with pool.acquire() as conn:
        latest = await conn.fetchval(DEALS_LATEST_SQL)
        if latest is None:
            return out
        first = date.fromordinal(latest.toordinal() - days + 1)
        rows = await read_deals(conn, start=first, end=latest, kind=kind, symbol=sym, limit=limit)
    out["as_of"] = latest.isoformat()
    out["from"] = first.isoformat()
    out["rows"] = [deal_row(r) for r in rows]
    out["count"] = len(out["rows"])
    out["total"] = int(rows[0]["total"]) if rows else 0
    return out


# ── F&O open-interest build-up ───────────────────────────────────────────────

_FNO_SOURCE = "NSE F&O bhavcopy (nidp.fno_bhavcopy), stock futures"
_INDEX_FNO_SOURCE = "NSE F&O bhavcopy (nidp.fno_bhavcopy), index futures; index close from nidp.index_eod"
_CASH_SOURCE = "NSE equity bhavcopy (nidp.prices_eod) for the cash close and volume"
_RVOL_SOURCE = "vol_z20 from nidp.stock_features_daily (technical indicator engine)"
_MASTER_SOURCE = "NSE F&O lot-size master fo_mktlots.csv (nidp.security_reference_daily.fno_eligible)"
LABELS = ("long_buildup", "short_buildup", "short_covering", "long_unwinding", "neutral")
# Normal-market cash series, most preferred first (the same order as the deals reader).
CASH_SERIES = ["EQ", "BE", "BZ", "SM", "ST"]
# Index futures underlyings and the index each tracks in nidp.index_eod (names checked on staging 2026-10-14).
INDEX_FUTURES: Dict[str, str] = {
    "NIFTY": "Nifty 50",
    "BANKNIFTY": "Nifty Bank",
    "FINNIFTY": "Nifty Financial Services",
    "MIDCPNIFTY": "Nifty Midcap Select",
    "NIFTYNXT50": "Nifty Next 50",
}
# Risk flags (PRD §10.7: expiry-related distortions are disclosed). Calendar days, one place.
EXPIRY_WEEK_DAYS = 7
RISK_FLAG_TEXT = {
    "expiry_week": f"The nearest contract expires within {EXPIRY_WEEK_DAYS} calendar days: price and OI moves are distorted by expiry.",
    "rollover": "Rollover: the next expiry now holds more open interest than the nearest, so positions are moving between contracts.",
    "no_cash_price": "No cash-market close for the day, so the futures move cannot be checked against the cash market.",
}

FNO_LATEST_SQL = "SELECT MAX(as_of_date) AS d FROM nidp.fno_bhavcopy WHERE instrument_type = 'STF'"

# One row per underlying (stock futures STF and index futures IDF): the nearest expiry's prices and contracts, OI and
# its change summed over every expiry (NULL when any expiry's figure is missing, so a partial sum never passes for the
# whole), and the second expiry's OI for the rollover flag. DISTINCT ON keeps one row per contract should a second
# source ever load the same day. Then, per stock: the cash close, previous close and volume that day ($2 = series in
# preference order), the latest vol_z20 within a week, and the F&O master's eligibility on or before the day; per
# index: the index close and its points change that day ($3 symbols, $4 index names).
FNO_BUILDUP_SQL = """
    WITH fut AS (
        SELECT DISTINCT ON (instrument_type, ticker_symbol, expiry_date)
               instrument_type, ticker_symbol, expiry_date, close_price, prev_close_price, open_interest, change_in_oi,
               traded_volume, traded_value
          FROM nidp.fno_bhavcopy
         WHERE as_of_date = $1 AND instrument_type IN ('STF', 'IDF')
         ORDER BY instrument_type, ticker_symbol, expiry_date, source
    ), g AS (
        SELECT instrument_type, ticker_symbol AS symbol,
               (ARRAY_AGG(expiry_date      ORDER BY expiry_date))[1] AS near_expiry,
               (ARRAY_AGG(close_price      ORDER BY expiry_date))[1] AS close,
               (ARRAY_AGG(prev_close_price ORDER BY expiry_date))[1] AS prev_close,
               (ARRAY_AGG(open_interest    ORDER BY expiry_date))[1] AS near_oi,
               (ARRAY_AGG(open_interest    ORDER BY expiry_date))[2] AS next_oi,
               CASE WHEN COUNT(open_interest) = COUNT(*) THEN SUM(open_interest) END AS oi,
               CASE WHEN COUNT(change_in_oi)  = COUNT(*) THEN SUM(change_in_oi)  END AS oi_chg,
               CASE WHEN COUNT(traded_volume) = COUNT(*) THEN SUM(traded_volume) END AS fut_contracts,
               CASE WHEN COUNT(traded_value)  = COUNT(*) THEN SUM(traded_value)  END AS fut_value,
               COUNT(*) AS expiries
          FROM fut
         GROUP BY instrument_type, ticker_symbol
    )
    SELECT g.*,
           px.close_price AS cash_close, px.prev_close AS cash_prev_close, px.volume AS cash_volume,
           sf.vol_z20, sf.as_of_date AS vol_z20_date,
           ref.fno_eligible, ref.as_of_date AS master_date,
           ix.close_price AS index_close, ix.pts_change AS index_change
      FROM g
      LEFT JOIN LATERAL (
            SELECT e.close_price, e.prev_close, e.volume
              FROM nidp.prices_eod e
             WHERE g.instrument_type = 'STF' AND e.symbol = g.symbol AND e.as_of_date = $1 AND e.series = ANY($2::text[])
             ORDER BY array_position($2::text[], e.series)
             LIMIT 1) px ON TRUE
      LEFT JOIN LATERAL (
            SELECT f.vol_z20, f.as_of_date
              FROM nidp.stock_features_daily f
             WHERE g.instrument_type = 'STF' AND f.symbol = g.symbol AND f.as_of_date <= $1 AND f.as_of_date > $1 - 7
             ORDER BY f.as_of_date DESC
             LIMIT 1) sf ON TRUE
      LEFT JOIN LATERAL (
            SELECT r.fno_eligible, r.as_of_date
              FROM nidp.security_reference_daily r
             WHERE g.instrument_type = 'STF' AND r.symbol = g.symbol AND r.as_of_date <= $1
             ORDER BY r.as_of_date DESC, (r.series = 'EQ') DESC
             LIMIT 1) ref ON TRUE
      LEFT JOIN LATERAL (
            SELECT i.close_price, i.pts_change
              FROM nidp.index_eod i
             WHERE g.instrument_type = 'IDF' AND i.as_of_date = $1
               AND i.index_name = ($4::text[])[array_position($3::text[], g.symbol)]
             ORDER BY i.source
             LIMIT 1) ix ON TRUE
"""


def buildup_label(price_chg: Optional[float], oi_chg: Optional[float]) -> Optional[str]:
    """The build-up reading of a price change and an OI change. None when either is missing."""
    if price_chg is None or oi_chg is None:
        return None
    if price_chg > 0 and oi_chg > 0:
        return "long_buildup"
    if price_chg < 0 and oi_chg > 0:
        return "short_buildup"
    if price_chg > 0 and oi_chg < 0:
        return "short_covering"
    if price_chg < 0 and oi_chg < 0:
        return "long_unwinding"
    return "neutral"


def cash_confirmation(fut_move: Optional[float], cash_move: Optional[float]) -> Optional[str]:
    """'confirms' when the futures and the cash market moved the same way, 'diverges' when they moved opposite ways;
    None when either move is missing or flat (nothing to compare)."""
    if fut_move is None or cash_move is None or fut_move == 0 or cash_move == 0:
        return None
    return "confirms" if (fut_move > 0) == (cash_move > 0) else "diverges"


def risk_flags(day: Optional[date], near_expiry: Optional[date], near_oi: Optional[int], next_oi: Optional[int],
               cash_known: bool) -> List[str]:
    """expiry_week, rollover and no_cash_price, in that order (definitions in RISK_FLAG_TEXT)."""
    flags: List[str] = []
    in_week = day is not None and near_expiry is not None and 0 <= (near_expiry - day).days <= EXPIRY_WEEK_DAYS
    if in_week:
        flags.append("expiry_week")
    if in_week and near_oi is not None and next_oi is not None and next_oi > near_oi:
        flags.append("rollover")
    if not cash_known:
        flags.append("no_cash_price")
    return flags


def buildup_row(r: Any, day: Optional[date] = None) -> Dict[str, Any]:
    close, prev = _num(r["close"]), _num(r["prev_close"])
    oi = int(r["oi"]) if r["oi"] is not None else None
    oi_chg = int(r["oi_chg"]) if r["oi_chg"] is not None else None
    prev_oi = oi - oi_chg if oi is not None and oi_chg is not None else None
    # The label reads the raw changes, not the rounded percents: +0.004% is still up.
    price_move = close - prev if close is not None and prev is not None and prev > 0 else None
    is_index = _get(r, "instrument_type") == "IDF"
    if is_index:
        cash_close = _num(_get(r, "index_close"))
        chg = _num(_get(r, "index_change"))
        cash_prev = cash_close - chg if cash_close is not None and chg is not None else None
    else:
        cash_close, cash_prev = _num(_get(r, "cash_close")), _num(_get(r, "cash_prev_close"))
    cash_move = cash_close - cash_prev if cash_close is not None and cash_prev is not None and cash_prev > 0 else None
    near = _get(r, "near_expiry")
    near_day = near if isinstance(near, date) else None
    fut_value = _num(_get(r, "fut_value"))
    contracts = _get(r, "fut_contracts")
    return {
        "symbol": r["symbol"],
        "near_expiry": jsonify(r["near_expiry"]),
        "close": close,
        "prev_close": prev,
        "price_chg_pct": pct_return(close, prev),
        "oi": oi,
        "oi_chg": oi_chg,
        "oi_chg_pct": round(oi_chg / prev_oi * 100.0, 2) if prev_oi is not None and prev_oi > 0 else None,
        "expiries": int(r["expiries"]),
        "label": buildup_label(price_move, oi_chg),
        # PRD §10.3 / §10.6 additions (B20). Every one is null when the warehouse has no figure.
        "days_to_expiry": (near_day - day).days if near_day is not None and day is not None else None,
        "fut_contracts": int(contracts) if contracts is not None else None,
        "fut_turnover_cr": round(fut_value / 1e7, 2) if fut_value is not None else None,
        "cash_close": cash_close,
        "cash_prev_close": cash_prev,
        "cash_chg_pct": pct_return(cash_close, cash_prev),
        "cash_volume": int(_get(r, "cash_volume")) if _get(r, "cash_volume") is not None else None,
        "cash_confirmation": cash_confirmation(price_move, cash_move),
        "vol_z20": round(_num(_get(r, "vol_z20")), 2) if _num(_get(r, "vol_z20")) is not None else None,
        "vol_z20_date": jsonify(_get(r, "vol_z20_date")),
        "fno_eligible": _get(r, "fno_eligible"),
        "master_date": jsonify(_get(r, "master_date")),
        "risk_flags": risk_flags(day, near_day, _get(r, "near_oi"), _get(r, "next_oi"), cash_move is not None),
        # Setup quality needs a validated model of these readings; none exists, so it is null on every row.
        "setup_quality": None,
    }


def _activity(row: Dict[str, Any]) -> Tuple[float, str]:
    """Sort key: the largest OI change in percent first (missing last), then symbol."""
    pct = row["oi_chg_pct"]
    return (-abs(pct) if pct is not None else float("inf"), row["symbol"])


@router.get("/fno-buildup", summary="Stock-futures OI build-up scan, one row per underlying")
async def fno_buildup(
    on: Optional[str] = Query(None, alias="date", description="Trading day YYYY-MM-DD; defaults to the latest"),
) -> Dict[str, Any]:
    day = parse_date(on, field="date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if day is None:
            day = await conn.fetchval(FNO_LATEST_SQL)
        rows = (await conn.fetch(FNO_BUILDUP_SQL, day, CASH_SERIES, list(INDEX_FUTURES), list(INDEX_FUTURES.values()))
                if day is not None else [])
    stock_rows = sorted((buildup_row(r, day) for r in rows if _get(r, "instrument_type") != "IDF"), key=_activity)
    index_rows = sorted((buildup_row(r, day) for r in rows if _get(r, "instrument_type") == "IDF"), key=lambda x: x["symbol"])
    for row in index_rows:
        row["index_name"] = INDEX_FUTURES.get(row["symbol"])
        row["fno_eligible"] = True if row["symbol"] in INDEX_FUTURES else None
    counts = {label: 0 for label in LABELS}
    counts["no_data"] = 0
    for row in stock_rows:
        counts[row["label"] or "no_data"] += 1
    master = [r for r in stock_rows if r["fno_eligible"] is not None]
    return {
        "as_of": day.isoformat() if day else None,
        "source": _FNO_SOURCE,
        "universe": len(stock_rows),
        "counts": counts,
        "rows": stock_rows,
        "indices": index_rows,
        "index_source": _INDEX_FNO_SOURCE,
        "sources": {"cash": _CASH_SOURCE, "rvol": _RVOL_SOURCE, "master": _MASTER_SOURCE},
        # PRD §10.2: the maintained master's say on the universe (null when the master has no row for the day).
        "master": {
            "as_of": max((r["master_date"] for r in master if r["master_date"]), default=None),
            "eligible": sum(1 for r in master if r["fno_eligible"] is True),
            "not_eligible": sum(1 for r in master if r["fno_eligible"] is False),
            "unknown": len(stock_rows) - len(master),
        },
        "risk_flag_text": dict(RISK_FLAG_TEXT),
        "setup_quality": "not_validated",
        "intraday": {
            "status": "unavailable",
            "reason": ("No intraday open interest is collected: the F&O data is the end-of-day bhavcopy, and the intraday "
                       "bar collector stores no OI and no NFO contracts. A 15-minute confirmation cannot be worked out."),
        },
    }


# ── market intelligence: filings by exchange subject, and each filing's source records ─────────────────────────

_FILINGS_SOURCE = "NSE and BSE corporate announcements (nidp.corporate_announcements)"
_EVENT_SOURCES_SOURCE = ("nidp.corporate_announcements (publication and ingestion times), nidp.v_event_asof (issuer "
                         "resolution and market timing), nidp.index_constituents (industry and same-industry peers)")
FILINGS_MAX_DAYS = 30
FILINGS_MAX_LIMIT = 120
EVENT_SOURCES_MAX_IDS = 200
PEERS_PER_INDUSTRY = 6
# The peer universe: the broadest NSE index list loaded (checked on staging 2026-10-14: 755 names).
PEER_INDEX = "Nifty Total Market"

# The PRD §6.2 categories the classifier has no label for, read from the exchange's OWN subject line (NSE's "desc",
# BSE's headline). ILIKE patterns; one table, so the screen and this route never disagree on what a family holds.
SUBJECT_FAMILIES: Dict[str, Tuple[str, ...]] = {
    # Earnings calls and guidance: analyst / investor meets and call updates, transcripts, investor presentations.
    "calls": ("%Con. Call%", "%Analyst%Meet%", "%Investor Meet%", "%Transcript%", "%Earnings Call%", "%Investor Presentation%"),
    # Promoter and ownership disclosures: SEBI takeover (SAST) and insider-trading disclosures, pledges, shareholding.
    "ownership": ("%Takeover%", "%SAST%", "%Insider Trading%", "%Shareholding Pattern%", "%Pledge%", "%Encumbrance%",
                  "%Promoter%"),
    # Exchange notices: the company's answers to the exchange's surveillance queries (volume spurts, price moves,
    # news and rumour verification). F&O ban and ASM / GSM lists are not ingested.
    "exchange": ("%Spurt in Volume%", "%Price movement%", "%News Verification%", "%Rumour Verification%",
                 "%Clarification sought%", "%Clarification on%"),
}

# $1 since (date), $2 patterns, $3 limit, $4 offset. Newest first.
FILINGS_SQL = """
    SELECT announcement_id, source, ticker_symbol, company_name, subject, event_category, impact_score, sentiment,
           filed_at, attachment_url, ingested_at, COUNT(*) OVER () AS total
      FROM nidp.corporate_announcements
     WHERE filed_at >= $1::date AND subject ILIKE ANY($2::text[])
     ORDER BY filed_at DESC, announcement_id
     LIMIT $3 OFFSET $4
"""


@router.get("/filings", summary="Exchange filings in one subject family (calls, ownership, exchange notices)")
async def filings_by_family(
    family: Literal["calls", "ownership", "exchange"] = Query(...),
    days: int = Query(7, ge=1, le=FILINGS_MAX_DAYS),
    limit: int = Query(60, ge=1, le=FILINGS_MAX_LIMIT),
    offset: int = Query(0, ge=0, le=10_000),
) -> Dict[str, Any]:
    """Rows in the shape of /v1/market-pulse/articles (id, title, company, symbol, category, impact, sentiment, when,
    source, url) plus ingested_at, so the app's filings feed renders them the same way. `total` counts every match."""
    since = date.today() - timedelta(days=days)
    patterns = list(SUBJECT_FAMILIES[family])
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(FILINGS_SQL, since, patterns, limit, offset)
    articles = [{
        "id": r["announcement_id"],
        "title": (r["subject"] or "").strip() or "Corporate announcement",
        "company": r["company_name"] or r["ticker_symbol"],
        "symbol": r["ticker_symbol"],
        "category": (r["event_category"] or "markets").replace("_", " ").title(),
        "impact": r["impact_score"],
        "sentiment": r["sentiment"],
        "when": jsonify(r["filed_at"]),
        "source": r["source"],
        "url": r["attachment_url"],
        "ingested_at": jsonify(r["ingested_at"]),
    } for r in rows]
    return {"family": family, "patterns": patterns, "days": days, "source": _FILINGS_SOURCE,
            "total": int(rows[0]["total"]) if rows else 0, "categories": {}, "articles": articles}


EVENT_RECORDS_SQL = """
    SELECT announcement_id, source, ticker_symbol, company_name, subject, filed_at, broadcast_at, ingested_at,
           classified_at, classifier_version, attachment_url, raw_payload->>'smIndustry' AS exchange_industry
      FROM nidp.corporate_announcements
     WHERE announcement_id = ANY($1::text[])
"""

# One row per filing per exchange, with the as-of rule applied once (migration 156).
EVENT_ASOF_SQL = """
    SELECT announcement_id, source, nse_symbol, resolution, timing_type, known_at_open_session, known_by_close_session,
           primary_row, ts_basis
      FROM nidp.v_event_asof
     WHERE announcement_id = ANY($1::text[])
"""

# Each symbol's industry in the latest list of the index it is in (the broadest list first).
INDUSTRY_SQL = """
    WITH latest AS (SELECT index_name, MAX(as_of_date) AS d FROM nidp.index_constituents GROUP BY index_name)
    SELECT DISTINCT ON (c.symbol) c.symbol, c.industry, c.index_name, c.as_of_date
      FROM nidp.index_constituents c
      JOIN latest l ON l.index_name = c.index_name AND l.d = c.as_of_date
     WHERE c.symbol = ANY($1::text[]) AND c.industry IS NOT NULL
     ORDER BY c.symbol, (c.index_name = $2) DESC, c.index_name
"""

# Same-industry names from the peer index's latest list, the ones in the narrowest broad index first (Nifty 50, then
# 100, 200, 500, Total Market: index_constituents carries no weights on staging, so membership is the size order).
PEER_TIERS = ["Nifty 50", "Nifty 100", "Nifty 200", "Nifty 500", "Nifty Total Market"]
PEERS_SQL = """
    WITH latest AS (SELECT index_name, MAX(as_of_date) AS d FROM nidp.index_constituents GROUP BY index_name),
    ic AS (SELECT c.symbol, c.company_name, c.industry, c.index_name
             FROM nidp.index_constituents c JOIN latest l ON l.index_name = c.index_name AND l.d = c.as_of_date),
    tier AS (SELECT symbol, MIN(array_position($4::text[], index_name)) AS t FROM ic GROUP BY symbol)
    SELECT industry, symbol, company_name, t
      FROM (SELECT i.industry, i.symbol, i.company_name, tier.t,
                   ROW_NUMBER() OVER (PARTITION BY i.industry ORDER BY tier.t NULLS LAST, i.symbol) AS rn
              FROM ic i JOIN tier USING (symbol)
             WHERE i.index_name = $2 AND i.industry = ANY($1::text[])) x
     WHERE rn <= $3
     ORDER BY industry, rn
"""


@router.get("/event-sources", summary="Each filing's source records, timing, issuer, industry and peers")
async def event_sources(ids: str = Query(..., min_length=1, max_length=20_000,
                                         description="Comma-separated announcement ids")) -> Dict[str, Any]:
    """For each id: every stored record (one per exchange copy) with its publication time (filed_at, the exchange's
    dissemination stamp), broadcast_at and ingested_at (when Nivesh last fetched it: the store keeps the latest fetch
    only, so a first-seen time is not available), the resolved NSE symbol, the market timing from v_event_asof, the
    industry from the NSE index lists (else the exchange's own industry field on an NSE filing) and up to six
    same-industry peers. An id the store does not know is left out."""
    wanted = [x.strip() for x in ids.split(",") if x.strip()][:EVENT_SOURCES_MAX_IDS]
    out: Dict[str, Any] = {"source": _EVENT_SOURCES_SOURCE, "peer_index": PEER_INDEX, "events": {}}
    if not wanted:
        return out
    pool = await get_pool()
    async with pool.acquire() as conn:
        records = await conn.fetch(EVENT_RECORDS_SQL, wanted)
        asof = await conn.fetch(EVENT_ASOF_SQL, wanted)
        timing = {(r["announcement_id"], r["source"]): r for r in asof}
        symbols = sorted({(timing.get((r["announcement_id"], r["source"])) or {}).get("nse_symbol") or r["ticker_symbol"]
                          for r in records} - {None})
        industries = await conn.fetch(INDUSTRY_SQL, symbols, PEER_INDEX) if symbols else []
        by_symbol = {r["symbol"]: r for r in industries}
        names = sorted({r["industry"] for r in industries})
        peer_rows = await conn.fetch(PEERS_SQL, names, PEER_INDEX, PEERS_PER_INDUSTRY + 1, PEER_TIERS) if names else []
    peers: Dict[str, List[Dict[str, Any]]] = {}
    for p in peer_rows:
        tier = p["t"]
        peers.setdefault(p["industry"], []).append({"symbol": p["symbol"], "name": p["company_name"],
                                                    "largest_index": PEER_TIERS[tier - 1] if tier else None})
    for r in records:
        t = timing.get((r["announcement_id"], r["source"]))
        sym = (t["nse_symbol"] if t else None) or r["ticker_symbol"]
        ind = by_symbol.get(sym) if sym else None
        sector, sector_source = None, None
        if ind:
            sector, sector_source = ind["industry"], f"NSE index list ({ind['index_name']}, {ind['as_of_date'].isoformat()})"
        elif r["exchange_industry"]:
            sector, sector_source = r["exchange_industry"], "The exchange's industry field on the filing (NSE)"
        record = {
            "announcement_id": r["announcement_id"],
            "source": r["source"],
            "company": r["company_name"],
            "subject": r["subject"],
            "url": r["attachment_url"],
            "published_at": jsonify(r["filed_at"]),
            "broadcast_at": jsonify(r["broadcast_at"]),
            "ingested_at": jsonify(r["ingested_at"]),
            "classified_at": jsonify(r["classified_at"]),
            "classifier_version": r["classifier_version"],
        }
        ev = out["events"].setdefault(r["announcement_id"], {
            "nse_symbol": sym,
            "resolution": t["resolution"] if t else None,
            "timing_type": t["timing_type"] if t else None,
            "known_at_open_session": jsonify(t["known_at_open_session"]) if t else None,
            "known_by_close_session": jsonify(t["known_by_close_session"]) if t else None,
            "primary_row": t["primary_row"] if t else None,
            "ts_basis": t["ts_basis"] if t else None,
            "sector": sector,
            "sector_source": sector_source,
            "peers": [p for p in peers.get(sector, []) if p["symbol"] != sym][:PEERS_PER_INDUSTRY] if ind else [],
            "records": [],
        })
        ev["records"].append(record)
    return out
