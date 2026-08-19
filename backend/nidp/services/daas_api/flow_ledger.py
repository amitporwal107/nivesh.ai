"""FLOW LEDGER auto-fill — turns NIDP data into the tracker's input fields.

The FLOW LEDGER scores FII/DII distribution from evidence streams that were, until
now, typed in by hand. This module fills the fields NIDP can actually source.

**It fills inputs, not verdicts.** The tracker's own scoring — the 0.4/0.3/0.2/0.1
quarter weights, the x1.25 consistency bonus, the renormalised composite — stays the
single implementation. Returning a score here would create a second one to drift
against, and the tracker's maths is the part a user can already read and check.

**A stream NIDP cannot source returns a reason, never a zero.** The tracker
deliberately excludes unfilled streams and renormalises the weights, so a fabricated
neutral would not merely be wrong, it would dilute the streams that are real. Every
`null` here carries the sentence explaining it.

Availability measured on nidp_staging 2026-08-19, after the NSE egress fix:

    company S1 FII QoQ      1,940 symbols have >=1 QoQ; only ~353 have the 4 the
                            tracker asks for (NSE_SHP holds 2 quarters; the deeper
                            history is screener_in and covers 388 symbols)
    company S2 DII QoQ      same shape. The "+ MF" half does not exist: mf_pct is
                            NULL in all 8,959 rows, so the label is DII-only here.
    company S3 deals        NOT sourceable — see BULK_DEAL_LIMIT below
    company S4 delivery     2,793 symbols with >=20 sessions
    company S5 MF monthly   NOT sourceable — mf_holdings is PARTIAL (10 of 14 AMCs
                            missing), so "net action across large houses" would be
                            computed from a minority of them
    company S6 F&O          215 stock-futures names
    sector  S1 NSDL         23 of 24 NSDL sectors map to sector_master; 9
                            fortnights on record (2026-03-31..07-31)
    sector  S2 AUC vs index same rows — AUC change minus the sector index move
    sector  S3 breadth      all sectors with >=1 ranked constituent
    sector  S4 rel strength 14 Nifty sector indices, unblocked by the index_close fix
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

FEATURES = "nidp.stock_features_daily"

# Why S3 cannot be filled from nidp.bulk_deals / nidp.block_deals. The stream needs
# "net FII/FPI direction by value", but the exchange deal lists name the trading
# member, not the beneficial owner. Measured over 90 days: of 4,137 bulk deals from
# 734 distinct clients, 10 carry anything that reads as foreign, and the top
# counterparties are domestic prop desks (QE Securities, HRTI, Junomoneta, NK
# Securities). Scoring FII direction off that would be inventing a signal.
BULK_DEAL_LIMIT = (
    "Exchange deal lists name the trading member, not the beneficial owner — of "
    "4,137 bulk deals in the last 90 days only 10 identify as foreign, so FII "
    "direction cannot be derived from them"
)
MF_MONTHLY_LIMIT = (
    "The monthly AMC feed is incomplete — 10 of 14 fund houses are missing, so "
    "'net action across large houses' would be computed from a minority of them"
)
NSDL_NO_SECTOR = (
    "NSDL reports FPI flows on BSE's 22-sector classification and this sector has no "
    "counterpart there, so no fortnightly flow can be attributed to it"
)
NSDL_TOO_SHORT = (
    "Fewer than two fortnightly FPI reports are on record for this sector — a streak "
    "needs at least two to have a direction"
)

# NIDP sector (nidp.sector_master.sector) -> the Nifty index that represents it.
# Only pairs where the index genuinely tracks the sector; an approximate match would
# put a wrong denominator into a relative-strength score.
SECTOR_INDEX: Dict[str, str] = {
    "Information Technology": "Nifty IT",
    "Automobile":             "Nifty Auto",
    # Healthcare, not Pharma: sector_master's Healthcare includes hospitals and
    # diagnostics, which Nifty Pharma excludes.
    "Healthcare":             "Nifty Healthcare Index",
    "FMCG":                   "Nifty FMCG",
    "Metals":                 "Nifty Metal",
    "Oil Gas":                "Nifty Energy",
    "Realty":                 "Nifty Realty",
    "Media":                  "Nifty Media",
    "Finance":                "Nifty Financial Services",
    "Capital Goods":          "Nifty Capital Goods",
    "Chemicals":              "Nifty Chemicals",
    "Consumer Durables":      "Nifty Consumer Durables",
    "Consumer Services":      "Nifty Consumer Services",
    "Construction":           "Nifty Construction",
    # NSE files cement under construction materials; Nifty Cement is that sector's
    # index, not a subset of it.
    "Construction Materials": "Nifty Cement",
    "Power":                  "Nifty Power",
}
# Left unmapped on purpose. "Telecommunication" has only Nifty MidSmall IT & Telecom,
# which blends two sectors; "Services" has only Nifty Commercial & Transport
# Services, a subset; Textiles and Diversified have no index at all. An approximate
# index would put a wrong denominator into relative strength and into the
# AUC-minus-index residual — a wrong number is worse here than an absent one.
UNMAPPED_BY_DESIGN = ("Telecommunication", "Services", "Textiles", "Diversified")
BENCHMARK_INDEX = "Nifty 50"


def fo_quadrant(price_change: Optional[float],
                oi_change: Optional[float]) -> Optional[str]:
    """Map price and open-interest direction onto the tracker's F&O codes.

    Returns the tracker's own option values so the field can be set directly:
    ``sb`` short buildup, ``lu`` long unwinding, ``sc`` short covering,
    ``lb`` long buildup, ``n`` no clear pattern.
    """
    if price_change is None or oi_change is None:
        return None
    if price_change == 0 or oi_change == 0:
        return "n"
    if price_change < 0:
        return "sb" if oi_change > 0 else "lu"
    return "lb" if oi_change > 0 else "sc"


def qoq_bps(series: List[Optional[float]]) -> List[Optional[int]]:
    """Consecutive quarter-on-quarter changes in basis points, latest first.

    ``series`` is percentage holdings ordered newest-first. n quarters give n-1
    changes; a missing quarter yields None rather than being bridged over, because
    silently differencing across a gap would report a two-quarter move as one.
    """
    out: List[Optional[int]] = []
    for cur, prev in zip(series, series[1:]):
        out.append(None if cur is None or prev is None else round((cur - prev) * 100))
    return out


def as_field(values: List[Optional[int]], width: int = 4) -> List[str]:
    """Shape a bps list into the tracker's fixed-width string inputs."""
    padded = (list(values) + [None] * width)[:width]
    return ["" if v is None else str(v) for v in padded]


def stream(tag: str, weight: int, title: str, *, filled: bool,
           evidence: Optional[str] = None, reason: Optional[str] = None,
           source: Optional[str] = None) -> Dict[str, Any]:
    """One stream's provenance block. A gap must state its reason."""
    if not filled and not reason:
        raise ValueError(f"{tag}: an unfilled stream must carry a reason")
    return {
        "tag": tag, "weight": weight, "title": title, "filled": filled,
        "evidence": evidence,
        "unavailable_reason": None if filled else reason,
        "source_dataset": source,
    }


# ── SQL ─────────────────────────────────────────────────────────────────────
# One row per (symbol, period_end) with NSE_SHP winning: the exchange filing beats
# the scraped source, which violates promoter+public=100 on 65% of its rows
# (migration 133 encodes the same precedence for v_shareholding_latest).
HOLDINGS_SQL = f"""
SELECT DISTINCT ON (period_end) period_end, fii_pct, dii_pct
  FROM nidp.shareholding_pattern
 WHERE symbol = $1 AND fii_pct IS NOT NULL
 ORDER BY period_end DESC,
          CASE source WHEN 'NSE_SHP' THEN 0 WHEN 'NSE_SAST_CSV' THEN 1 ELSE 2 END
 LIMIT 5
"""

# Delivery on down days vs the whole-window baseline. Down days come from the price
# table's own prev_close rather than a lagged window function, so a gap in the series
# cannot silently turn a two-day move into a one-day one.
DELIVERY_SQL = f"""
SELECT ROUND(AVG(deliv_pct)::numeric, 2)                                    AS baseline,
       ROUND(AVG(deliv_pct) FILTER (WHERE close_price < prev_close)::numeric, 2) AS down_day,
       COUNT(*) FILTER (WHERE close_price < prev_close)                     AS down_days,
       COUNT(*)                                                             AS sessions
  FROM nidp.prices_eod
 WHERE symbol = $1 AND as_of_date >= (CURRENT_DATE - $2::int)
   AND deliv_pct IS NOT NULL AND prev_close IS NOT NULL
"""

# Near-month stock future only. Summing every expiry would let a far-month roll read
# as fresh positioning.
FNO_SQL = """
WITH near AS (
    SELECT MIN(expiry_date) AS e FROM nidp.fno_bhavcopy
     WHERE ticker_symbol = $1 AND instrument_type = 'STF'
       AND expiry_date >= (SELECT MAX(as_of_date) FROM nidp.fno_bhavcopy)
)
SELECT as_of_date, close_price, open_interest
  FROM nidp.fno_bhavcopy, near
 WHERE ticker_symbol = $1 AND instrument_type = 'STF' AND expiry_date = near.e
   AND open_interest IS NOT NULL
 ORDER BY as_of_date DESC
 LIMIT $2::int
"""

BREADTH_SQL = f"""
WITH d AS (
    SELECT DISTINCT ON (symbol, period_end) symbol, period_end, fii_pct
      FROM nidp.shareholding_pattern WHERE fii_pct IS NOT NULL
     ORDER BY symbol, period_end DESC,
              CASE source WHEN 'NSE_SHP' THEN 0 WHEN 'NSE_SAST_CSV' THEN 1 ELSE 2 END
), r AS (
    SELECT symbol, fii_pct,
           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY period_end DESC) rn
      FROM d
), qoq AS (
    SELECT a.symbol, (a.fii_pct - b.fii_pct) AS delta
      FROM r a JOIN r b ON b.symbol = a.symbol AND a.rn = 1 AND b.rn = 2
), top AS (
    SELECT f.symbol
      FROM {FEATURES} f JOIN nidp.sector_master m ON m.symbol = f.symbol
     WHERE f.as_of_date = $2::date AND m.sector = $1 AND f.market_cap_cr IS NOT NULL
     ORDER BY f.market_cap_cr DESC
     LIMIT 10
)
SELECT COUNT(*)                                     AS ranked,
       COUNT(q.delta)                               AS measured,
       COUNT(*) FILTER (WHERE q.delta < 0)          AS fell
  FROM top t LEFT JOIN qoq q ON q.symbol = t.symbol
"""

# Return between the oldest and newest close inside the window, per index.
INDEX_RETURN_SQL = """
SELECT index_name,
       (ARRAY_AGG(close_price ORDER BY as_of_date DESC))[1] AS last_px,
       (ARRAY_AGG(close_price ORDER BY as_of_date ASC))[1]  AS first_px,
       MIN(as_of_date) AS from_date, MAX(as_of_date) AS to_date, COUNT(*) AS bars
  FROM nidp.index_eod
 WHERE index_name = ANY($1::text[]) AND as_of_date >= (CURRENT_DATE - $2::int)
   AND close_price IS NOT NULL
 GROUP BY index_name
"""


def pct_return(last_px: Optional[float], first_px: Optional[float]) -> Optional[float]:
    if last_px is None or first_px in (None, 0):
        return None
    return round(100.0 * (float(last_px) - float(first_px)) / float(first_px), 2)


def fortnight_streak(net_flows: List[Optional[float]]):
    """Consecutive fortnights in one direction, newest first.

    Returns ``(direction, count)`` where direction is the tracker's own ``in``/``out``
    code, or ``None`` when there is no readable direction.

    The streak is counted from the LATEST fortnight, so a sector that sold for six
    fortnights and then bought reads as a 1-fortnight inflow — which is the honest
    current state. Reporting the longer historical run would describe a regime that
    has already turned.

    A zero net flow ends the streak rather than continuing it: a fortnight with no
    net movement is not evidence of the prior direction persisting.
    """
    flows = [f for f in net_flows]
    if not flows or flows[0] is None or flows[0] == 0:
        return None
    positive = flows[0] > 0
    count = 0
    for v in flows:
        if v is None or v == 0 or (v > 0) != positive:
            break
        count += 1
    return ("in" if positive else "out"), count


# Net flow and AUC per fortnight for one sector, newest first. EQUITY only — the
# tracker's stream is about equity allocation, and debt flows move on rates rather
# than on any view of the sector.
FPI_SECTOR_SQL = """
SELECT report_date, net_inv_inr_cr, auc_inr_cr
  FROM nidp.fpi_sector_auc
 WHERE sector_norm = $1 AND asset_class = 'EQUITY'
 ORDER BY report_date DESC
 LIMIT $2::int
"""

# Index return between two explicit dates — pinned to the FPI fortnight range so the
# AUC-minus-index residual is a real gap and not a window mismatch.
INDEX_RETURN_BETWEEN_SQL = """
SELECT ROUND(100.0 * (
           (ARRAY_AGG(close_price ORDER BY as_of_date DESC))[1]
         - (ARRAY_AGG(close_price ORDER BY as_of_date ASC))[1]
       ) / NULLIF((ARRAY_AGG(close_price ORDER BY as_of_date ASC))[1], 0), 2)
  FROM nidp.index_eod
 WHERE index_name = $1 AND as_of_date BETWEEN $2::date AND $3::date
   AND close_price IS NOT NULL
"""
