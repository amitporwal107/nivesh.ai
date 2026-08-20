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

# S3 — net FPI direction on the exchange deal lists.
#
# An earlier read of this data concluded the stream was unbuildable. That was wrong,
# and wrong twice over: it ranked counterparties by DEAL COUNT (which high-frequency
# domestic desks dominate by construction — they place thousands of small trades and
# their net is ~zero by design) and it matched "foreign" with a narrow geography
# regex. Ranked by VALUE instead, named FPI portfolio investors are plainly present:
# GQG Partners EM Equity Fund, Fidelity Advisor International, Smallcap World Fund,
# Nomura India Investment Fund, Citigroup Global Markets Singapore, Goldman Sachs
# Bank Europe, Morgan Stanley Asia Singapore, Government of Singapore.
#
# Three populations share these lists and only one of them is this stream's subject:
#
#   1. FPI portfolio investors — global fund houses, bank broking arms, sovereign
#      funds. This IS "FII direction".
#   2. Foreign strategic / PE holdings — Bayer AG in Bayer CropScience, Twin Star
#      (Vedanta's holdco), Baring's BC Investments, Eight Roads Mauritius. Foreign,
#      and SEBI-registered as FPIs, but a promoter or PE block exit is not portfolio
#      flow; counting it as "heavy FII selling" would misread a one-off structural
#      trade as a distribution pattern.
#   3. Domestic proprietary and HFT desks — QE Securities, HRTI, Junomoneta,
#      Graviton, iRage. Both sides of the book, netting to roughly nothing.
#
# Only (1) scores. The house list below is curated rather than heuristic precisely
# because separating (1) from (2) cannot be done by name shape — both are offshore
# entities — only by knowing which are portfolio managers.
FPI_HOUSES = (
    "GQG", "FIDELITY", "FMRC", "SMALLCAP WORLD", "NOMURA", "GOLDMAN SACHS",
    "MORGAN STANLEY", "CITIGROUP GLOBAL", "JPMORGAN", "J P MORGAN", "BOFA",
    "MERRILL LYNCH", "SOCIETE GENERALE", "BNP PARIBAS", "HSBC", "UBS ",
    "DEUTSCHE BANK", "BARCLAYS", "MACQUARIE", "CREDIT SUISSE", "BLACKROCK",
    "VANGUARD", "GOVERNMENT OF SINGAPORE", "NORGES", "ABU DHABI INVESTMENT",
    "EASTSPRING", "SCHRODER", "ABERDEEN", "FRANKLIN TEMPLETON", "T ROWE",
    "CAPITAL GROUP", "WASATCH", "MATTHEWS", "AMUNDI", "INVESCO", "STICHTING",
    "CALIFORNIA PUBLIC EMPLOYEES", "PUBLIC INVESTMENT FUND",
    # Added after the first live run named counterparties the list had missed —
    # every one of these is a real offshore fund in nidp_staging's deal lists.
    "ALLIANZ GLOBAL INVESTORS", "POLAR CAPITAL", "JUPITER INDIA", "POLUNIN",
    "MASTER FUND", "OPPORTUNITIES FUND LLC", "FUNDS PLC", " VCC",
)

# Indian institutions carry fund-like names too, and several share a global brand.
# An India-domiciled insurer, AMC or AIF is DII however the name reads; counting one
# as FII flow inverts the stream. Checked BEFORE the house list.
DOMESTIC_VEHICLE_MARKERS_EXTRA = (
    "LIFE INSURANCE", "GENERAL INSURANCE", "NUVAMA", "360 ONE", "MOTILAL",
    "KOTAK MAHINDRA", "AXIS ", "ADITYA BIRLA", "SBI ", "ICICI PRUDENTIAL",
    "TATA AIA", "HDFC ", "NIPPON INDIA", "DSP ", "EDELWEISS", "ABAKKUS",
)

# Absence of an identified FPI is a real answer — the tracker has an option for it —
# but it is only as strong as the list above. The evidence line therefore always
# names what WAS seen, so a reader can judge whether the classifier missed someone.
BULK_DEAL_NO_DEALS = (
    "No bulk or block deals recorded for this symbol in the window — any qualifying "
    "trade must be disclosed, so this is a complete observation, not a gap"
)
# Deals happened but none matched the house list. That is NOT the same as "no FPI
# activity": the list is a whitelist and the first live run proved it misses real
# ones (Allianz Global Investors was named in the evidence and not counted). Scoring
# a neutral here would be the fabricated neutral this whole design refuses — it would
# add weight 20 of "no signal" that the composite then treats as evidence. So the
# stream stays unfilled, and the reason names who WAS there so a reader can judge.
BULK_DEAL_UNRECOGNISED = (
    "Deals occurred but no counterparty matched the known FPI-house list, which is "
    "curated and demonstrably incomplete — so this reads as 'not established', not "
    "as 'no FPI activity'. Counterparties seen: "
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
# The quarter-end guard is not defensive dressing. Measured 2026-08-20, 372 rows
# across 338 symbols carry a FILING date in period_end rather than a quarter end
# (2026-08-07, 2026-08-06, …) — 198 distinct such dates, first written 2026-07-10,
# so it predates this service. Without the filter those rows sort to the top and
# become Q0, and the QoQ difference is then taken across a 38-day gap and reported
# as a quarter-on-quarter move. A wrong number wearing the right label.
QUARTER_END_ONLY = ("period_end = (date_trunc('quarter', period_end) "
                    "+ interval '3 months - 1 day')::date")

HOLDINGS_SQL = f"""
SELECT DISTINCT ON (period_end) period_end, fii_pct, dii_pct
  FROM nidp.shareholding_pattern
 WHERE symbol = $1 AND fii_pct IS NOT NULL AND {QUARTER_END_ONLY}
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
      FROM nidp.shareholding_pattern
     WHERE fii_pct IS NOT NULL
       AND period_end = (date_trunc('quarter', period_end)
                         + interval '3 months - 1 day')::date
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


# Global brands also run INDIAN asset managers, and an India-domiciled mutual fund is
# DII by definition however familiar the parent name is. "HSBC Mutual Fund",
# "Invesco Mutual Fund" and "Franklin Templeton Mutual Fund" are all real
# counterparties in these lists, all matched by the house list above, and all wrong
# for this stream — counting a domestic MF as FII flow would invert the reading.
DOMESTIC_VEHICLE_MARKERS = (("MUTUAL FUND", " MF ", "AMC LIMITED", "AMC LTD")
                            + DOMESTIC_VEHICLE_MARKERS_EXTRA)


def is_fpi_house(client_name: Optional[str]) -> bool:
    """True when the counterparty is a recognised FPI PORTFOLIO investor.

    Deliberately a whitelist. A "does it look offshore" heuristic cannot separate a
    portfolio manager from a PE holdco or a promoter's Mauritius vehicle — Bayer AG
    and GQG Partners are both foreign, and only one of them is this stream's subject.
    The domestic-vehicle exclusion runs first, because the brand match would
    otherwise claim India's own AMCs for the foreign side.
    """
    if not client_name:
        return False
    upper = f" {client_name.upper()} "
    if any(m in upper for m in DOMESTIC_VEHICLE_MARKERS):
        return False
    return any(h in upper for h in FPI_HOUSES)


def deal_direction(buy_cr: float, sell_cr: float,
                   min_gross_cr: float = 5.0):
    """Map net FPI value onto the tracker's own deal codes.

    Returns ``(code, net_cr, gross_cr)``, code being ``hs``/``s``/``n``/``b``/``hb``.

    Scored on how ONE-SIDED the activity was — net as a share of gross — rather than
    on the rupee figure alone. A fund rotating 500 cr in and 480 cr out is not
    distribution; a fund selling 60 cr with nothing on the other side is. An absolute
    floor stops a single tiny print reading as "heavy".
    """
    gross = (buy_cr or 0) + (sell_cr or 0)
    net = (buy_cr or 0) - (sell_cr or 0)
    if gross < min_gross_cr:
        return "n", round(net, 1), round(gross, 1)
    lean = net / gross
    if lean <= -0.75:
        code = "hs"
    elif lean <= -0.25:
        code = "s"
    elif lean < 0.25:
        code = "n"
    elif lean < 0.75:
        code = "b"
    else:
        code = "hb"
    return code, round(net, 1), round(gross, 1)


# Bulk and block deals share a shape, so they are unioned rather than queried twice —
# the stream is about FPI activity on the exchange deal lists, not about which list.
# Value is quantity x price because the feeds carry no notional column.
DEALS_SQL = """
SELECT client_name, deal_type,
       SUM(quantity * avg_price) / 1e7           AS value_cr,
       COUNT(*)                                  AS deals,
       COUNT(DISTINCT as_of_date)                AS days
  FROM (
      SELECT client_name, deal_type, quantity, avg_price, as_of_date
        FROM nidp.bulk_deals
       WHERE symbol = $1 AND as_of_date >= (CURRENT_DATE - $2::int)
      UNION ALL
      SELECT client_name, deal_type, quantity, avg_price, as_of_date
        FROM nidp.block_deals
       WHERE symbol = $1 AND as_of_date >= (CURRENT_DATE - $2::int)
  ) d
 WHERE quantity IS NOT NULL AND avg_price IS NOT NULL
 GROUP BY client_name, deal_type
"""
