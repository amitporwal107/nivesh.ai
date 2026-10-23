"""DaaS — Historical Smart Money Movement: disclosed ownership change vs the SAME quarter's tape.

    GET /v1/desk/ownership/reaction   one row per Nifty-500 name with a computable quarterly
                                      institutional ownership change, beside that quarter's
                                      price return, volume ratio and delivery shift.

Read-only. DESCRIPTIVE AND RETROSPECTIVE. This is CO-OCCURRENCE, NOT CAUSATION, and it is not a
trading signal in any form:

  * The shareholding pattern for Jul-Sep 2026 is published in late October 2026. The price move it
    is set against was already over before the ownership figure existed. Nothing here can be acted
    on ahead of the move; the screen explains the past.
  * There is no score and no ranking by one. `validated_study` is read LIVE from
    nidp.smart_money_promotion_decisions (zero APPROVED rows: the smart-money validation study
    NIDP-SM-VALIDATION-001/002 returned INCONCLUSIVE), never hardcoded. Rows are ordered by a
    measured quantity the caller chooses, never by a composite.
  * An absent figure is null and is reported as "not disclosed". It is never 0 and never reads as
    a positive. `price_legs_present` separates "we could not measure" from "it did not move".

What the data supports, measured on staging 2026-10-23 (every count below is from a real query):

  Universe                              nidp.index_constituents 'Nifty 500' @ max(as_of_date), less DUMMYHEG  500
  Has a 2026-09-30 FII figure                                                                                 429
  Has a COMPUTABLE two-quarter change (2026-09-30 vs 2026-06-30)                                               89
    of which SAME-SOURCE (both quarters from screener_in)                                                      65
    of which CROSS-SOURCE (2026-09-30 NSE_SHP minus 2026-06-30 screener_in)                                    24
  Has the MF / Banks-FI split as a LEVEL (NSE_SHP only)                                                        77

So the real denominator is **89 of 500**, not 500, and only 65 of those 89 rest on one publisher.

Why the basis matters more than it looks (this is the sharpest trap in this dataset)
  At period_end 2026-06-30, source NSE_SHP carries fii_pct for ZERO rows -- every prior-quarter
  figure in the warehouse comes from screener_in. The value-aware dedupe therefore produces, for 77
  of 89 names, a delta that differences TWO DIFFERENT PUBLISHERS. ICICIBANK is the proof: NSE_SHP
  discloses FII 50.44 at 2026-09-30 while screener_in discloses 34.68 for the same quarter and
  33.79 at 2026-06-30. A cross-source delta reads +16.65pp ("a huge FII increase"); the same-source
  delta is +0.89pp. The 16.65 is almost entirely the publisher switch, i.e. a data artifact.
  Measured across the 65 names where both bases exist: 33 agree to within 0.01pp, 3 differ by
  >= 0.5pp, 2 flip sign, and the worst gap is 15.77pp.
  For a CHANGE, same-publisher consistency beats level accuracy -- a consistent methodology bias
  cancels in a difference. So this endpoint prefers the same-source delta, falls back to the
  cross-source one, and ALWAYS labels which (`delta_basis`) with the publishers named
  (`delta_source`) and the other basis's figure alongside (`delta_alt_pp`) so the disagreement is
  visible rather than hidden.
  NSE_SHP is nevertheless the externally validated source for the LEVEL: HAL reads FII 9.42 and
  MF 6.72 there, matching Trendlyne exactly. It just cannot produce a change.

Deliberate omissions, each because the data is absent, not because it was inconvenient
  * No MF or Banks-FI CHANGE. mf_pct and bank_fi_pct exist for ONE quarter only (1,321 and 1,094
    rows at 2026-09-30; 0 at 2026-06-30 and at every earlier quarter). They are served as a LEVEL
    with `split_is_level` true. Differencing them is impossible, so no delta is offered.
  * No insurance / LIC line and no claim that DII is decomposed. insurance_pct and
    govt_holding_pct are 0 of 429 rows at every quarter, from both sources. LIC is invisible in
    this table, so `dii_components_complete` is false and `mf_pct + bank_fi_pct` must never be
    presented as adding up to `dii_pct_now`.
  * Nothing from nidp.mf_holdings / mf_holdings_deltas. That leg has a measured 4.03x duplication
    and 0.54x coverage and is being repaired separately. This screen does not read it at all.
  * No index benchmark, no excess-return figure and no sector-relative figure. nidp.index_eod holds
    'Nifty 500' as a PRICE index only (no TRI) and, measured, its 2025 coverage is 63 of 248
    sessions (25.4%) with a single 375-day gap -- a benchmark comparison against it would be
    computed against a series that mostly does not exist. index_constituents has only 4 snapshots,
    all dated after the periods of interest, so a point-in-time sector cut is not available either.
    Everything relative here is CROSS-SECTIONAL instead: each name against the same quarter's
    distribution of its own peer group, reported as `ret_percentile`, which is a POSITION WITHIN
    THE COHORT and is never to be labelled "vs Nifty 500" or read as excess return.
  * No moving-average or relative-strength column. nidp.stock_features_daily has sma20/50/100/200
    and return_252d_pct but no EMA and no stored relative strength; none of it is needed here, so
    none of it is read or implied.

Definitions (all measured, nothing assumed)
  quarter        The disclosed quarter is period_end 2026-09-30 => the tape window is the calendar
                 quarter ending on it, 2026-07-01..2026-09-30 (65 sessions), compared with
                 2026-04-01..2026-06-30 (60 sessions). Both derived from the data, not hardcoded.
  ret_pct        last adj_close of the quarter vs last adj_close of the prior quarter, from
                 nidp.prices_eod_adjusted. SPLIT-ADJUSTED and deliberately so -- see the SQL
                 comment on TDPOWERSYS, whose raw return reads -36.52% against a true +26.96%.
                 It is a PRICE return: adj_close handles splits and bonuses but excludes
                 dividends, so it is not a total return (tret_close exists but is not used here,
                 because the label on screen says price).
  vol_ratio      mean daily `adj_volume` this quarter / mean daily `adj_volume` last quarter --
                 adjusted for the same reason (a split multiplies the share count).
  deliv_shift_pp mean `deliv_pct` this quarter minus last quarter, in percentage points, from
                 nidp.prices_eod (series EQ+BE). It stays on the bhavcopy because it is a ratio of
                 one day's own quantities, which no split can distort, and because the adjusted
                 table carries no delivery column.
  ret_percentile Where the return sits within the peer cross-section, 0-100. Position in the
                 cohort, NOT excess return over an index.
  sessions floor A name needs >= 30 sessions in BOTH quarters or the price legs are null with
                 `price_legs_present` false. A ratio off 11 sessions is noise dressed as a
                 measurement. On the adjusted series 488 of the 500 clear it, so 12 names carry no
                 tape at all; `coverage.reference_cross_section` reports that number rather than
                 letting the names vanish quietly. prices_eod_adjusted coverage is strongly
                 time-dependent (55.5% of symbols in 2024, 94.7% in 2025, 98.0% in 2026), which is
                 why that count is published: this window sits entirely in 2026, where 497 of the
                 500 have rows at all, but a window reaching into 2024 would lose far more.
  thresholds     Derived from the DATA DISTRIBUTION, never invented round numbers, and returned in
                 the envelope so the UI can print them. They are percentiles of the same quarter's
                 Nifty-500 cross-section (492 names clearing the session floor):
                    ret_p20 = -13.55%   ret_p80 = +7.67%   vol_p50 = 0.757
                 Round numbers would badly misread this quarter: the MEDIAN name's volume FELL
                 (ratio 0.757, so "> 1.0 = expansion" would fire on only ~22% of names) and the
                 median delivery percentage ROSE +3.31pp (so "delivery up = accumulation" would
                 fire on nearly everyone). Both legs are judged against the market, not a constant.
  reaction       A CONJUNCTION of the two reliable legs, price-led and volume-confirmed:
                    strong_positive  ret >= ret_p80 AND vol_ratio >= vol_p50
                    negative         ret <= ret_p20 AND vol_ratio >= vol_p50
                    neutral          everything else
                 When the price leg is extreme but volume does not confirm, the row stays `neutral`
                 and carries an explicit `reaction_note` naming the unconfirmed leg, so a big move
                 on thin volume is visible and not silently averaged away. Both bands are always
                 returned beside the label, so the label can be checked against its own inputs.
                 Delivery shift is DISPLAYED but deliberately NOT part of the label: market-wide
                 delivery rose this quarter, which makes it a weak discriminator.
  divergence     Ownership and price pointed OPPOSITE ways AND both legs are beyond their cohort
                 median magnitude (0.42pp and 11.05%). 7 of the 89 qualify. Six are ownership UP
                 with price DOWN, which is what a quarter with a -6.8% cohort median return looks
                 like; NUVOCO is the one the other way (-0.43pp while the price rose 11.47%).
                 There is ONE definition of this word in the system: the `view=divergence` filter
                 delegates to the status, so the filter and the status chip can never disagree.

The cohort is at most 500 rows and is 89 today, so the SQL returns the measured legs and the
derivation runs in Python (`classify_row`), where it is unit-testable without a database and has a
single definition. The envelope's counts are computed over the WHOLE cohort before the view filter,
so an empty view reads "none in this quarter" instead of looking broken.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify, row_to_dict

router = APIRouter(prefix="/desk", tags=["desk"], dependencies=[Depends(require_api_key)])

MAX_LIMIT = 500
#: Minimum sessions required in EACH quarter before a return / volume ratio is reported at all.
MIN_SESSIONS = 30
#: Materiality floor on the ownership leg, in percentage points. Stated on screen, not hidden.
MATERIAL_PP = 0.5
#: A source disagreement below this is rounding, not a dispute.
SPREAD_FLOOR_PP = 0.5

UNIVERSE = "Nifty 500"

_VIEWS = ("all", "reduced", "raised", "divergence")
_SORTS = ("inst_delta", "ret", "vol_ratio", "symbol")

#: "Within 10% of the 52-week high" -- a STATED ABSOLUTE, not a percentile, because it is a
#: meaningful statement in itself. For context the cohort's median distance is -22.17% and only 5
#: of the 89 clear it, so it is a genuinely narrow gate rather than a round number that fires often.
NEAR_52W_HIGH_PCT = -10.0

_STATUSES = ("accumulation", "breakout_watch", "reversal_watch", "distribution_risk",
             "divergence", "insufficient_data", "none")


def _pct(vals: List[float], q: float) -> Optional[float]:
    """percentile_cont(q), linear interpolation -- identical to Postgres, so the figures the
    envelope publishes match a hand-check against the warehouse."""
    s = sorted(v for v in vals if v is not None)
    if not s:
        return None
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def cohort_cuts(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Percentiles of THIS quarter's eligible cohort -- the reference set the status rules are
    written against. Recomputed every quarter and published with the quarter it came from; these
    are not universal constants and must never be hardcoded downstream.

    Measured for 2026-06-30 -> 2026-09-30 over the 89 eligible names: institutional change
    p25 -0.05 / p50 +0.17 / p75 +0.87 pp; quarter return p25 -13.75 / p50 -6.77 / p75 +3.42 %;
    volume ratio p25 0.590 / p50 0.761 / p75 0.972; delivery shift p25 +1.32 / p50 +3.66 /
    p75 +5.94 pp.
    """
    def col(k: str) -> List[float]:
        return [float(r[k]) for r in rows if r.get(k) is not None]

    def acol(k: str) -> List[float]:
        return [abs(float(r[k])) for r in rows if r.get(k) is not None]

    return {
        "n": len(rows),
        "inst_p25": _pct(col("inst_delta_pp"), 0.25),
        "inst_p50": _pct(col("inst_delta_pp"), 0.50),
        "inst_p75": _pct(col("inst_delta_pp"), 0.75),
        "ret_p25": _pct(col("ret_pct"), 0.25),
        "ret_p50": _pct(col("ret_pct"), 0.50),
        "ret_p75": _pct(col("ret_pct"), 0.75),
        "vol_p25": _pct(col("vol_ratio"), 0.25),
        "vol_p50": _pct(col("vol_ratio"), 0.50),
        "vol_p75": _pct(col("vol_ratio"), 0.75),
        "deliv_p25": _pct(col("deliv_shift_pp"), 0.25),
        "deliv_p50": _pct(col("deliv_shift_pp"), 0.50),
        "deliv_p75": _pct(col("deliv_shift_pp"), 0.75),
        "high_p50": _pct(col("dist_52w_high_pct"), 0.50),
        "low_p25": _pct(col("dist_52w_low_pct"), 0.25),
        # "Beyond its median magnitude" for the divergence rule.
        "abs_inst_p50": _pct(acol("inst_delta_pp"), 0.50),
        "abs_ret_p50": _pct(acol("ret_pct"), 0.50),
        "near_52w_high_pct": NEAR_52W_HIGH_PCT,
    }


def classify_status(r: Dict[str, Any], c: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """The desk's status taxonomy, evaluated against this quarter's own cohort percentiles.

    Every rule is a conjunction of measured legs and every status carries `status_reason` naming
    the legs that fired, so the word is always checkable against the row. These are DESCRIPTIONS
    of a finished quarter, not calls: "Breakout Watch" says a name that institutions added to
    ended the quarter near its 52-week high, not that it will break out.

    Precedence is fixed and declared: insufficient_data, then distribution_risk (the only status
    rendered red), then accumulation (the four-leg one, so it outranks the two narrower watches),
    then breakout_watch, reversal_watch and divergence.
    """
    inst, ret, vol = r.get("inst_delta_pp"), r.get("ret_pct"), r.get("vol_ratio")
    dlv, hi, lo = r.get("deliv_shift_pp"), r.get("dist_52w_high_pct"), r.get("dist_52w_low_pct")

    # Cannot classify: no measurable tape, or the publishers disagree by as much as the change.
    if not r.get("price_legs_present") or inst is None:
        r["status"] = "insufficient_data"
        r["status_reason"] = ("The quarter's price/volume action is not measurable for this name, so no "
                              "status can be assigned.")
        return r
    if r.get("fii_trust") == "unusable":
        r["status"] = "insufficient_data"
        r["status_reason"] = ("The two sources disagree about this quarter's FII holding by as much as the "
                              "change itself, so the ownership leg cannot carry a status.")
        return r

    inst, ret, vol = float(inst), float(ret), float(vol)
    dlvf = None if dlv is None else float(dlv)
    hif = None if hi is None else float(hi)
    lof = None if lo is None else float(lo)
    g = lambda k: c.get(k)  # noqa: E731 - local alias keeps the rules readable

    def have(*vals) -> bool:
        return all(v is not None for v in vals)

    # Ownership fell materially AND price fell on volume that did not: the only red status.
    if (have(g("ret_p50"), g("vol_p75"))
            and inst <= -MATERIAL_PP and ret <= g("ret_p50") and vol >= g("vol_p75")):
        r["status"] = "distribution_risk"
        r["status_reason"] = (
            "Institutional holding fell %.2fpp (at or beyond the -%.2fpp materiality floor) while the price "
            "fell %.2f%% (at or below the cohort median %.2f%%) on a volume ratio of %.3f (at or above the "
            "cohort 75th percentile %.3f) -- falling on rising participation while ownership dropped."
            % (inst, MATERIAL_PP, ret, g("ret_p50"), vol, g("vol_p75")))
        return r

    raised = have(g("inst_p75")) and inst >= g("inst_p75")

    # All four legs agree.
    if (raised and have(g("ret_p50"), g("vol_p75"), g("deliv_p50")) and dlvf is not None
            and ret >= g("ret_p50") and vol >= g("vol_p75") and dlvf >= g("deliv_p50")):
        r["status"] = "accumulation"
        r["status_reason"] = (
            "Institutional holding rose %.2fpp (cohort 75th percentile %.2fpp), the price held at %.2f%% "
            "(cohort median %.2f%%), the volume ratio was %.3f (75th percentile %.3f) and the delivery "
            "share rose %.2fpp (median %.2fpp): all four legs agree."
            % (inst, g("inst_p75"), ret, g("ret_p50"), vol, g("vol_p75"), dlvf, g("deliv_p50")))
        return r

    # Added to, and the quarter ended near the 52-week high.
    if (raised and hif is not None and have(g("vol_p50"))
            and hif >= NEAR_52W_HIGH_PCT and vol >= g("vol_p50")):
        r["status"] = "breakout_watch"
        r["status_reason"] = (
            "Institutional holding rose %.2fpp (cohort 75th percentile %.2fpp) and the quarter closed %.2f%% "
            "from the 52-week high -- within %.0f%% of it, against a cohort median of %.2f%% -- on a volume "
            "ratio of %.3f (cohort median %.3f)."
            % (inst, g("inst_p75"), hif, abs(NEAR_52W_HIGH_PCT),
               g("high_p50") if g("high_p50") is not None else float("nan"), vol, g("vol_p50")))
        return r

    # Added to INTO weakness. A watch item, not a risk -- never rendered red.
    if (raised and have(g("ret_p25"), g("low_p25")) and lof is not None
            and ret <= g("ret_p25") and lof <= g("low_p25")):
        r["status"] = "reversal_watch"
        r["status_reason"] = (
            "Institutional holding rose %.2fpp (cohort 75th percentile %.2fpp) while the price fell %.2f%% "
            "(cohort 25th percentile %.2f%%) and the quarter closed only %.2f%% above the 52-week low "
            "(cohort 25th percentile %.2f%%): institutions added into weakness."
            % (inst, g("inst_p75"), ret, g("ret_p25"), lof, g("low_p25")))
        return r

    # Opposite directions, both legs beyond their median magnitude.
    if (have(g("abs_inst_p50"), g("abs_ret_p50"))
            and ((inst > 0 > ret) or (inst < 0 < ret))
            and abs(inst) >= g("abs_inst_p50") and abs(ret) >= g("abs_ret_p50")):
        r["status"] = "divergence"
        r["status_reason"] = (
            "Ownership moved %+.2fpp while the price moved %+.2f%% -- opposite directions, and both beyond "
            "their cohort median magnitudes (%.2fpp and %.2f%%)."
            % (inst, ret, g("abs_inst_p50"), g("abs_ret_p50")))
        return r

    r["status"] = "none"
    r["status_reason"] = "No status rule's legs all fired for this name this quarter."
    return r


# ---------------------------------------------------------------- derivation (pure, unit-tested)

def fii_trust(fii_delta_pp: Optional[float], fii_spread_pp: Optional[float], basis: str) -> str:
    """How far the FII change can be trusted. Mirrors smart_money.fiiTrust and adds the basis.

    'unusable' means the two publishers disagree by as much as the change itself, so the change is
    not distinguishable from the disagreement -- the UI prints "sources differ", never a number.
    A cross-source delta is never better than 'contested': it differences two publishers by
    construction, which is exactly the thing the spread measures within one quarter.
    """
    if fii_delta_pp is None:
        return "none"
    if fii_spread_pp is not None and fii_spread_pp >= SPREAD_FLOOR_PP:
        if fii_spread_pp >= abs(fii_delta_pp):
            return "unusable"
        return "contested"
    return "contested" if basis == "cross_source" else "ok"


def classify_row(r: Dict[str, Any], cuts: Dict[str, float]) -> Dict[str, Any]:
    """Add the derived fields to one measured row. Absent inputs stay absent -- never 0.

    `cuts` carries ret_p20 / ret_p80 / vol_p50, themselves measured from this quarter's
    cross-section, so a label always travels with the numbers that produced it.
    """
    ret, vol = r.get("ret_pct"), r.get("vol_ratio")
    present = ret is not None and vol is not None
    r["price_legs_present"] = present

    if not present:
        # "We could not measure this quarter's tape" is not "the tape did nothing".
        r["price_band"] = None
        r["volume_band"] = None
        r["reaction"] = None
        r["reaction_corroborated"] = None
        r["reaction_note"] = ("Fewer than %d sessions in one of the two quarters, so a quarter return "
                              "and a volume ratio are not measurable for this name." % MIN_SESSIONS)
    else:
        retf, volf = float(ret), float(vol)
        p20, p80, v50 = cuts["ret_p20"], cuts["ret_p80"], cuts["vol_p50"]
        band = "bottom_quintile" if retf <= p20 else ("top_quintile" if retf >= p80 else "middle")
        vband = "expanded" if volf >= v50 else "contracted"
        r["price_band"], r["volume_band"] = band, vband

        confirmed = vband == "expanded"
        if band == "top_quintile" and confirmed:
            r["reaction"], r["reaction_corroborated"], r["reaction_note"] = "strong_positive", True, None
        elif band == "bottom_quintile" and confirmed:
            r["reaction"], r["reaction_corroborated"], r["reaction_note"] = "negative", True, None
        else:
            r["reaction"], r["reaction_corroborated"] = "neutral", band == "middle"
            if band == "middle":
                r["reaction_note"] = None
            else:
                # Loud rather than averaged away: the price leg was extreme, volume did not confirm.
                direction = "rose" if band == "top_quintile" else "fell"
                r["reaction_note"] = (
                    "Price %s into the %s of the peer group, but volume contracted "
                    "(%.3f vs the %.3f peer median), so the two legs do not agree."
                    % (direction, "top quintile" if band == "top_quintile" else "bottom quintile",
                       volf, v50))

    r["fii_trust"] = fii_trust(
        None if r.get("fii_delta_pp") is None else float(r["fii_delta_pp"]),
        None if r.get("fii_spread_pp") is None else float(r["fii_spread_pp"]),
        str(r.get("delta_basis") or ""),
    )
    # The split is a one-quarter LEVEL. There is no prior quarter to difference it against.
    r["split_is_level"] = True
    # insurance_pct / govt_holding_pct are 0 of 429 rows: LIC is invisible, DII is not decomposed.
    r["dii_components_complete"] = False
    return r


def in_view(r: Dict[str, Any], view: str) -> bool:
    """`reduced` / `raised` apply the same stated 0.5pp floor the envelope publishes.

    `divergence` delegates to the STATUS, so there is exactly one definition of divergence in the
    system. An earlier draft had a looser view-level rule (opposite signs past a 0.5pp floor, 13
    names) alongside the status rule (both legs past their cohort median magnitude, 7 names); two
    numbers for one word on one screen is a contradiction, so the stricter, stated one wins.
    """
    if view == "all":
        return True
    if view == "divergence":
        return r.get("status") == "divergence"
    inst = r.get("inst_delta_pp")
    if inst is None:
        return False
    if view == "reduced":
        return float(inst) < -MATERIAL_PP
    if view == "raised":
        return float(inst) > MATERIAL_PP
    return True


# ---------------------------------------------------------------- SQL

#: The two newest quarters that actually carry an institutional column.
_QUARTERS_SQL = """
    SELECT DISTINCT period_end FROM nidp.shareholding_pattern
     WHERE fii_pct IS NOT NULL ORDER BY period_end DESC LIMIT 2
"""

#: The quarter's tape window, derived from the disclosed period_end rather than hardcoded.
_SESSIONS_SQL = """
    SELECT count(DISTINCT as_of_date) FROM nidp.prices_eod
     WHERE series IN ('EQ','BE') AND as_of_date >= $1 AND as_of_date <= $2
"""

#: Measured legs for the whole cohort. Derivation happens in Python; see the module docstring.
#:   $1 current period_end   $2 previous period_end   $3 start of the previous quarter
#:   $4 index name           $5 session floor
_ROWS_SQL = """
    WITH n5 AS (
        SELECT DISTINCT symbol, industry
          FROM nidp.index_constituents
         WHERE index_name = $4
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = $4)
           AND symbol <> 'DUMMYHEG'
    ),
    -- Tape: price and volume come from the SPLIT-ADJUSTED series, which is not optional here.
    -- Measured on the raw bhavcopy over this very window, TDPOWERSYS split mid-quarter and its
    -- unadjusted quarter return reads -36.52% where the adjusted return is +26.96% -- a 63.48pp
    -- error that FLIPS THE SIGN, and would have been labelled a sharp negative reaction. PFOCUS
    -- reads +42.98% unadjusted against +9.42% adjusted. Neither is in today's 89-name cohort, but
    -- both sit in the tails of the reference cross-section that the percentile cut-points are
    -- derived from, so raw closes would bend the thresholds for every row. adj_volume is used for
    -- the same reason: a split multiplies the share count, so a raw volume ratio jumps with it.
    -- (symbol, as_of_date) is unique here -- verified, 0 duplicate pairs -- and the adjusted series
    -- carries the identical session calendar for this span (60 sessions prior, 65 current).
    adjq AS (
        SELECT a.symbol, a.as_of_date, a.adj_close, a.adj_volume, (a.as_of_date > $2) AS is_cur
          FROM nidp.prices_eod_adjusted a JOIN n5 ON n5.symbol = a.symbol
         WHERE a.as_of_date >= $3 AND a.as_of_date <= $1
    ),
    agg AS (
        SELECT symbol, is_cur, count(*) AS sessions,
               avg(adj_volume)::numeric AS avg_vol,
               (array_agg(adj_close ORDER BY as_of_date DESC))[1] AS last_close
          FROM adjq GROUP BY symbol, is_cur
    ),
    -- Delivery percentage is a RATIO of the same day's quantities, so a split cannot distort it,
    -- and the adjusted table carries no delivery column -- so this leg stays on the bhavcopy.
    dlq AS (
        SELECT p.symbol, (p.as_of_date > $2) AS is_cur, avg(p.deliv_pct) AS avg_deliv
          FROM nidp.prices_eod p JOIN n5 ON n5.symbol = p.symbol
         WHERE p.series IN ('EQ','BE') AND p.as_of_date >= $3 AND p.as_of_date <= $1
           AND p.deliv_pct IS NOT NULL
         GROUP BY p.symbol, (p.as_of_date > $2)
    ),
    act AS (
        SELECT c.symbol, c.sessions AS sessions_cur, p.sessions AS sessions_prev,
               round(100.0 * (c.last_close - p.last_close) / NULLIF(p.last_close, 0), 2) AS ret_pct,
               round(c.avg_vol / NULLIF(p.avg_vol, 0), 3)                                AS vol_ratio,
               round(dc.avg_deliv - dp.avg_deliv, 2)                                     AS deliv_shift_pp
          FROM agg c
          JOIN agg p ON p.symbol = c.symbol AND p.is_cur IS FALSE
          LEFT JOIN dlq dc ON dc.symbol = c.symbol AND dc.is_cur IS TRUE
          LEFT JOIN dlq dp ON dp.symbol = c.symbol AND dp.is_cur IS FALSE
         WHERE c.is_cur IS TRUE AND c.sessions >= $5 AND p.sessions >= $5
    ),
    -- CROSS-SECTIONAL relative strength: where this name's return sits among its own peer group
    -- over the identical window. This is a POSITION WITHIN THE COHORT, not excess return over an
    -- index, and must never be labelled "vs Nifty 500". No index series is read -- which is also
    -- the only honest option: nidp.index_eod's 'Nifty 500' row covers 63 of 248 sessions in 2025
    -- (25.4%) with a 375-day gap, so anything benchmarked against it would be measured against a
    -- series that mostly does not exist.
    rs AS (
        SELECT symbol, round((100.0 * percent_rank() OVER (ORDER BY ret_pct))::numeric, 1) AS ret_percentile
          FROM act
    ),
    -- SAME-SOURCE delta: both quarters from one publisher. The honest basis for a CHANGE, because
    -- a consistent methodology bias cancels in a difference. 65 Nifty-500 names today.
    same AS (
        SELECT c.symbol, c.source,
               round(c.fii_pct - p.fii_pct, 2) AS fii_delta_pp,
               round(c.dii_pct - p.dii_pct, 2) AS dii_delta_pp,
               c.fii_pct AS fii_pct_now, c.dii_pct AS dii_pct_now
          FROM nidp.shareholding_pattern c
          JOIN nidp.shareholding_pattern p
            ON p.symbol = c.symbol AND p.source = c.source AND p.period_end = $2
         WHERE c.period_end = $1
           AND c.fii_pct IS NOT NULL AND p.fii_pct IS NOT NULL
           AND c.dii_pct IS NOT NULL AND p.dii_pct IS NOT NULL
    ),
    -- Value-aware dedupe (NOT source-ranked: ranking by source name loses 40 of 73 computable
    -- deltas, because NSE_SHP holds NULL institutional columns at the prior quarter).
    dd AS (
        SELECT DISTINCT ON (symbol, period_end) symbol, period_end, fii_pct, dii_pct, source
          FROM nidp.shareholding_pattern
         WHERE period_end IN ($1, $2)
         ORDER BY symbol, period_end, (fii_pct IS NOT NULL) DESC, ingested_at DESC
    ),
    -- CROSS-SOURCE fallback: differences two publishers. Labelled as such, never presented as equal.
    crossb AS (
        SELECT c.symbol, c.source || ' - ' || p.source AS source,
               round(c.fii_pct - p.fii_pct, 2) AS fii_delta_pp,
               round(c.dii_pct - p.dii_pct, 2) AS dii_delta_pp,
               c.fii_pct AS fii_pct_now, c.dii_pct AS dii_pct_now
          FROM dd c JOIN dd p ON p.symbol = c.symbol AND p.period_end = $2
         WHERE c.period_end = $1
           AND c.fii_pct IS NOT NULL AND p.fii_pct IS NOT NULL
           AND c.dii_pct IS NOT NULL AND p.dii_pct IS NOT NULL
    ),
    chosen AS (
        SELECT coalesce(s.symbol, x.symbol)                                   AS symbol,
               CASE WHEN s.symbol IS NOT NULL THEN 'same_source' ELSE 'cross_source' END AS delta_basis,
               coalesce(s.source, x.source)                                   AS delta_source,
               coalesce(s.fii_delta_pp, x.fii_delta_pp)                       AS fii_delta_pp,
               coalesce(s.dii_delta_pp, x.dii_delta_pp)                       AS dii_delta_pp,
               coalesce(s.fii_pct_now, x.fii_pct_now)                         AS fii_pct_now,
               coalesce(s.dii_pct_now, x.dii_pct_now)                         AS dii_pct_now,
               -- The OTHER basis's figure, so a disagreement is visible instead of hidden.
               CASE WHEN s.symbol IS NOT NULL THEN x.fii_delta_pp END         AS delta_alt_pp
          FROM same s FULL JOIN crossb x ON x.symbol = s.symbol
    ),
    -- Within-quarter publisher disagreement, carried on the row (the smart_money fii_spread_pp
    -- pattern). ICICIBANK: 15.76pp at 2026-09-30, against a cross-source change of 16.65pp.
    spread AS (
        SELECT symbol, max(sp) AS fii_spread_pp
          FROM (SELECT symbol, period_end, max(fii_pct) - min(fii_pct) AS sp
                  FROM nidp.shareholding_pattern
                 WHERE period_end IN ($1, $2) AND fii_pct IS NOT NULL
                 GROUP BY symbol, period_end
                HAVING count(DISTINCT source) > 1) z
         GROUP BY symbol
    ),
    -- The MF / Banks-FI split, a LEVEL at the current quarter only, and NSE_SHP only (screener_in
    -- carries 0 of them). No prior-quarter value exists anywhere, so no delta is possible.
    split AS (
        SELECT DISTINCT ON (symbol) symbol, mf_pct, bank_fi_pct, source AS split_source
          FROM nidp.shareholding_pattern
         WHERE period_end = $1 AND (mf_pct IS NOT NULL OR bank_fi_pct IS NOT NULL)
         ORDER BY symbol, (mf_pct IS NOT NULL) DESC, ingested_at DESC
    ),
    -- The REAL NSE publication timestamp, not an estimate. Populated for 1,996 rows at
    -- 2026-09-30, spanning 2026-10-01..2026-10-22, and 48.5% of them land after the 15:30 close
    -- (so the figure is actionable only from the NEXT session, which is the UI's wording). It is
    -- empty for every earlier quarter, so only the current quarter's filing date can be shown.
    filed AS (
        SELECT symbol, min(broadcast_at) AS filed_at
          FROM nidp.shareholding_pattern
         WHERE period_end = $1 AND broadcast_at IS NOT NULL
         GROUP BY symbol
    ),
    -- How many quarters this name actually discloses, so the UI can refuse to draw a trend from
    -- one dot: across the Nifty 500, 340 names have exactly ONE quarter and only 91 have >= 4.
    hist AS (
        SELECT symbol, count(DISTINCT period_end) AS quarters_available
          FROM nidp.shareholding_pattern
         WHERE fii_pct IS NOT NULL
         GROUP BY symbol
    ),
    -- Point-in-time 52-week position AT THE QUARTER END -- not today's value, because this screen
    -- describes a finished quarter. 88 of the 89 cohort names carry it.
    feat AS (
        SELECT symbol, dist_52w_high_pct, dist_52w_low_pct
          FROM nidp.stock_features_daily
         WHERE as_of_date = $1
    )
    SELECT ch.symbol, n5.industry,
           ch.delta_basis, ch.delta_source,
           ch.fii_delta_pp, ch.dii_delta_pp,
           round(ch.fii_delta_pp + ch.dii_delta_pp, 2) AS inst_delta_pp,
           ch.fii_pct_now, ch.dii_pct_now, ch.delta_alt_pp,
           round(sp.fii_spread_pp, 2) AS fii_spread_pp,
           s.mf_pct, s.bank_fi_pct, s.split_source,
           a.ret_pct, a.vol_ratio, a.deliv_shift_pp, a.sessions_cur, a.sessions_prev,
           rs.ret_percentile,
           round(f.dist_52w_high_pct, 2) AS dist_52w_high_pct,
           round(f.dist_52w_low_pct, 2)  AS dist_52w_low_pct,
           fl.filed_at,
           h.quarters_available
      FROM chosen ch
      JOIN n5 ON n5.symbol = ch.symbol
      LEFT JOIN spread sp ON sp.symbol = ch.symbol
      LEFT JOIN split  s  ON s.symbol  = ch.symbol
      LEFT JOIN act    a  ON a.symbol  = ch.symbol
      LEFT JOIN rs        ON rs.symbol = ch.symbol
      LEFT JOIN feat   f  ON f.symbol  = ch.symbol
      LEFT JOIN filed  fl ON fl.symbol = ch.symbol
      LEFT JOIN hist   h  ON h.symbol  = ch.symbol
"""

#: Reaction bands are cross-sectional: percentiles of THIS quarter's own Nifty-500 tape. No index
#: series is involved, which is just as well -- there is no Nifty 500 TRI, only a price index.
_CUTS_SQL = """
    WITH n5 AS (
        SELECT DISTINCT symbol FROM nidp.index_constituents
         WHERE index_name = $4
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = $4)
           AND symbol <> 'DUMMYHEG'
    ),
    -- Same split-adjusted legs as _ROWS_SQL. Raw closes would put TDPOWERSYS at -36.52% (true
    -- +26.96%) and PFOCUS at +42.98% (true +9.42%) into the tails these percentiles are cut from.
    adjq AS (
        SELECT a.symbol, a.as_of_date, a.adj_close, a.adj_volume, (a.as_of_date > $2) AS is_cur
          FROM nidp.prices_eod_adjusted a JOIN n5 ON n5.symbol = a.symbol
         WHERE a.as_of_date >= $3 AND a.as_of_date <= $1
    ),
    agg AS (
        SELECT symbol, is_cur, count(*) AS sessions, avg(adj_volume)::numeric AS avg_vol,
               (array_agg(adj_close ORDER BY as_of_date DESC))[1] AS last_close
          FROM adjq GROUP BY symbol, is_cur
    ),
    dlq AS (
        SELECT p.symbol, (p.as_of_date > $2) AS is_cur, avg(p.deliv_pct) AS avg_deliv
          FROM nidp.prices_eod p JOIN n5 ON n5.symbol = p.symbol
         WHERE p.series IN ('EQ','BE') AND p.as_of_date >= $3 AND p.as_of_date <= $1
           AND p.deliv_pct IS NOT NULL
         GROUP BY p.symbol, (p.as_of_date > $2)
    ),
    act AS (
        SELECT c.symbol,
               100.0 * (c.last_close - p.last_close) / NULLIF(p.last_close, 0) AS ret_pct,
               c.avg_vol / NULLIF(p.avg_vol, 0)                                AS vol_ratio,
               dc.avg_deliv - dp.avg_deliv                                     AS deliv_shift_pp
          FROM agg c
          JOIN agg p ON p.symbol = c.symbol AND p.is_cur IS FALSE
          LEFT JOIN dlq dc ON dc.symbol = c.symbol AND dc.is_cur IS TRUE
          LEFT JOIN dlq dp ON dp.symbol = c.symbol AND dp.is_cur IS FALSE
         WHERE c.is_cur IS TRUE AND c.sessions >= $5 AND p.sessions >= $5
    )
    SELECT count(*) AS ref_n,
           round(percentile_cont(0.20) WITHIN GROUP (ORDER BY ret_pct)::numeric, 2)   AS ret_p20,
           round(percentile_cont(0.80) WITHIN GROUP (ORDER BY ret_pct)::numeric, 2)   AS ret_p80,
           round(percentile_cont(0.50) WITHIN GROUP (ORDER BY ret_pct)::numeric, 2)   AS ret_p50,
           round(percentile_cont(0.50) WITHIN GROUP (ORDER BY vol_ratio)::numeric, 3) AS vol_p50,
           round(percentile_cont(0.50) WITHIN GROUP (ORDER BY deliv_shift_pp)::numeric, 2) AS deliv_p50
      FROM act
"""

_COVERAGE_SQL = """
    WITH n5 AS (
        SELECT DISTINCT symbol FROM nidp.index_constituents
         WHERE index_name = $3
           AND as_of_date = (SELECT max(as_of_date) FROM nidp.index_constituents WHERE index_name = $3)
           AND symbol <> 'DUMMYHEG'
    ),
    cur AS (
        SELECT DISTINCT symbol FROM nidp.shareholding_pattern
         WHERE period_end = $1 AND fii_pct IS NOT NULL
    ),
    -- Quarters disclosed per name, so the screen can state that a multi-quarter trend is not
    -- drawable for most of the index rather than drawing a one-point line.
    hist AS (
        SELECT symbol, count(DISTINCT period_end) AS quarters
          FROM nidp.shareholding_pattern WHERE fii_pct IS NOT NULL GROUP BY symbol
    )
    SELECT (SELECT count(*) FROM n5)                                              AS universe_total,
           (SELECT count(*) FROM n5 JOIN cur USING (symbol))                      AS with_current_quarter,
           (SELECT count(*) FROM n5 JOIN hist USING (symbol) WHERE hist.quarters >= 4) AS trend_renderable,
           (SELECT count(*) FROM n5 JOIN hist USING (symbol) WHERE hist.quarters = 1)  AS single_quarter_only
"""


def _quarter_start(period_end: date) -> date:
    """First day of the calendar quarter that ENDS at `period_end`."""
    m = period_end.month - 2
    return date(period_end.year, m if m > 0 else 1, 1)


@router.get("/ownership/reaction",
            summary="Quarterly institutional ownership change beside the same quarter's price/volume action")
async def ownership_reaction(
    view: str = Query("all", pattern="^(all|reduced|raised|divergence)$",
                      description="reduced/raised apply the published 0.5pp materiality floor"),
    reaction: str = Query("any", pattern="^(any|strong_positive|neutral|negative)$"),
    status: str = Query("any",
                        pattern="^(any|accumulation|breakout_watch|reversal_watch|distribution_risk|divergence|insufficient_data|none)$",
                        description="the desk status taxonomy, evaluated against this quarter's cohort percentiles"),
    basis: str = Query("any", pattern="^(any|same_source)$",
                       description="same_source drops rows whose change differences two publishers"),
    sort: str = Query("inst_delta", pattern="^(inst_delta|ret|vol_ratio|symbol)$",
                      description="a measured column, never a composite score"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "as_of": None, "previous_period": None,
        "price_window": None, "universe": UNIVERSE,
        "retrospective": True,
        "validated_study": False,
        "filters": {"view": view, "reaction": reaction, "status": status, "basis": basis, "sort": sort},
        "source": ("nidp.shareholding_pattern (FII/DII percent, two quarters) x nidp.prices_eod "
                   "(close/volume/deliv_pct, series EQ+BE), universe nidp.index_constituents"),
        "disclosure": (
            "DESCRIPTIVE AND RETROSPECTIVE: this is co-occurrence, not causation, and not a trading "
            "signal. The Jul-Sep quarter's shareholding pattern was published in late October, so the "
            "price move shown beside it was already over before the ownership figure existed -- it "
            "explains the past and predicts nothing. No score and no ranking by one: the smart-money "
            "validation study returned INCONCLUSIVE and no promotion decision is on record. The "
            "reaction label is a conjunction of the price and volume legs against this quarter's own "
            "Nifty-500 percentiles, which are returned in `thresholds` so they can be checked. "
            "A missing figure is null and means NOT DISCLOSED; it never means zero and never reads "
            "as positive."),
        "basis_note": (
            "At the prior quarter NSE_SHP discloses no FII figure at all, so a change can only come "
            "from screener_in (same_source) or by differencing the two publishers (cross_source). "
            "ICICIBANK shows why that matters: cross-source reads +16.65pp where screener_in alone "
            "reads +0.89pp, because the publishers differ by 15.76pp on the same quarter. Every row "
            "names its basis, and `delta_alt_pp` carries the other basis where both exist."),
        "filing_note": (
            "`filed_at` is the real NSE publication timestamp from shareholding_pattern.broadcast_at, "
            "not an estimate -- which is what makes the retrospective point concrete: the quarter ended "
            "2026-09-30 and the filings land across 2026-10-01..2026-10-22. 48.5% of them are "
            "timestamped after the 15:30 close, so for those the figure was first tradable on the NEXT "
            "session. It is recorded for the current quarter only; earlier quarters carry no timestamp."),
        "trend_note": (
            "A multi-quarter ownership trend is NOT drawable for most of the index: of the 500 names, "
            "340 disclose exactly one quarter and only 91 disclose four or more. `quarters_available` "
            "is on every row so a trend is drawn only where there is one, and named as absent otherwise."),
        "split_note": (
            "mf_pct and bank_fi_pct are a LEVEL at the current quarter only -- they exist for one "
            "quarter in the whole table, so no MF or Banks-FI change is computable for any stock. "
            "insurance_pct and govt_holding_pct are empty for every row, so LIC is invisible and "
            "DII is NOT fully decomposed: the parts shown do not sum to DII."),
        "thresholds": None, "coverage": None, "counts": None,
        "count": 0, "total": 0, "rows": [],
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        qs = [r["period_end"] for r in await conn.fetch(_QUARTERS_SQL)]
        if len(qs) < 2:
            return out
        cur_end, prev_end = qs[0], qs[1]
        prev_start = _quarter_start(prev_end)

        # False unless a promotion actually passed. Read live, never hardcoded.
        out["validated_study"] = bool(await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM nidp.smart_money_promotion_decisions WHERE decision = 'APPROVED')"))

        cuts_row = row_to_dict(await conn.fetchrow(_CUTS_SQL, cur_end, prev_end, prev_start, UNIVERSE, MIN_SESSIONS))
        cov = row_to_dict(await conn.fetchrow(_COVERAGE_SQL, cur_end, prev_end, UNIVERSE))
        raw = [row_to_dict(r) for r in await conn.fetch(
            _ROWS_SQL, cur_end, prev_end, prev_start, UNIVERSE, MIN_SESSIONS)]
        # Both bounds inclusive, so the first session of each quarter is counted.
        sess_cur = await conn.fetchval(_SESSIONS_SQL, _quarter_start(cur_end), cur_end)
        sess_prev = await conn.fetchval(_SESSIONS_SQL, prev_start, prev_end)

    if cuts_row.get("ret_p20") is None or not raw:
        # Without a measurable cross-section there are no bands, so no label is honest.
        out["as_of"] = cur_end.isoformat()
        out["previous_period"] = prev_end.isoformat()
        return out

    cuts = {
        "ret_p20": float(cuts_row["ret_p20"]),
        "ret_p80": float(cuts_row["ret_p80"]),
        "vol_p50": float(cuts_row["vol_p50"]),
    }
    rows = [classify_row(dict(r), cuts) for r in raw]
    # The status rules are written against THIS quarter's eligible cohort, so its percentiles are
    # measured from the cohort itself and then applied back to it. Recomputed every quarter.
    ccuts = cohort_cuts(rows)
    rows = [classify_status(r, ccuts) for r in rows]

    # Counts over the WHOLE cohort, before any view/reaction filter, so an empty view can say
    # "none in this quarter" rather than looking broken.
    def n(pred) -> int:
        return sum(1 for r in rows if pred(r))

    # The status buckets are exhaustive and mutually exclusive, so they MUST sum to the eligible
    # cohort. A sum that misses means a name was dropped or double-counted, which would quietly
    # restate the denominator -- the exact class of error this screen exists to avoid. Published
    # so the UI and the tests can both check it rather than trust it.
    status_counts = {f"status_{s}": n(lambda r, s=s: r["status"] == s) for s in _STATUSES}

    out["counts"] = {
        "cohort": len(rows),
        **status_counts,
        "status_sum": sum(status_counts.values()),
        "status_reconciles": sum(status_counts.values()) == len(rows),
        "same_source": n(lambda r: r["delta_basis"] == "same_source"),
        "cross_source": n(lambda r: r["delta_basis"] == "cross_source"),
        "reduced": n(lambda r: in_view(r, "reduced")),
        "raised": n(lambda r: in_view(r, "raised")),
        "divergence": n(lambda r: in_view(r, "divergence")),
        "strong_positive": n(lambda r: r["reaction"] == "strong_positive"),
        "neutral": n(lambda r: r["reaction"] == "neutral"),
        "negative": n(lambda r: r["reaction"] == "negative"),
        "uncorroborated": n(lambda r: r["reaction"] == "neutral" and r["reaction_corroborated"] is False),
        "price_legs_missing": n(lambda r: not r["price_legs_present"]),
        "split_disclosed": n(lambda r: r.get("mf_pct") is not None),
        "fii_unusable": n(lambda r: r["fii_trust"] == "unusable"),
        "reduced_and_negative": n(lambda r: in_view(r, "reduced") and r["reaction"] == "negative"),
    }
    out["coverage"] = {
        "universe_total": cov.get("universe_total"),
        "with_current_quarter": cov.get("with_current_quarter"),
        "computable_change": len(rows),
        "same_source": out["counts"]["same_source"],
        "cross_source": out["counts"]["cross_source"],
        "split_disclosed": out["counts"]["split_disclosed"],
        "reference_cross_section": cuts_row.get("ref_n"),
        # A CHANGE needs two quarters: `with_current_quarter` names disclose this quarter, but only
        # `computable_change` of them have a comparable prior one. Any delta figure belongs to the
        # smaller denominator, and the screen must quote that one.
        "insufficient_for_change": (None if cov.get("universe_total") is None
                                    else cov["universe_total"] - len(rows)),
        "trend_renderable": cov.get("trend_renderable"),
        "single_quarter_only": cov.get("single_quarter_only"),
        "with_52w_position": n(lambda r: r.get("dist_52w_high_pct") is not None),
        "filing_date_known": n(lambda r: r.get("filed_at") is not None),
    }
    out["cohort_thresholds"] = {
        "quarter": f"{prev_end.isoformat()} -> {cur_end.isoformat()}",
        "note": ("Percentiles of THIS quarter's eligible cohort, recomputed every quarter. They are "
                 "quarter-specific, not universal constants, and the status rules below are written "
                 "against them. The cohort is the %d names with two comparable quarters." % len(rows)),
        "rules": {
            "accumulation": ("ownership change >= cohort p75 AND return >= cohort median AND volume ratio "
                             ">= cohort p75 AND delivery shift >= cohort median"),
            "breakout_watch": ("ownership change >= cohort p75 AND within %.0f%% of the 52-week high AND "
                               "volume ratio >= cohort median" % abs(NEAR_52W_HIGH_PCT)),
            "reversal_watch": ("ownership change >= cohort p75 AND return <= cohort p25 AND distance above "
                               "the 52-week low <= cohort p25 -- buying INTO weakness, a watch item and "
                               "NOT a risk"),
            "distribution_risk": ("ownership change <= -%.2fpp AND return <= cohort median AND volume ratio "
                                  ">= cohort p75 -- falling on rising participation" % MATERIAL_PP),
            "divergence": "ownership and return in opposite directions, both beyond their cohort median magnitude",
            "insufficient_data": ("no comparable prior quarter, no measurable tape, or the two sources "
                                  "disagree by as much as the change itself"),
        },
        **{k: (None if v is None else round(float(v), 3)) for k, v in ccuts.items()},
    }
    out["thresholds"] = {
        "basis": ("percentiles of the same quarter's Nifty-500 cross-section; "
                  "derived from the distribution, not chosen round numbers"),
        "price_series": ("nidp.prices_eod_adjusted adj_close / adj_volume (split- and bonus-adjusted, "
                         "dividends excluded, so a price return and not a total return); delivery "
                         "percentage from nidp.prices_eod, where a split cannot distort a same-day ratio"),
        "relative_strength": ("`ret_percentile` is this name's position within the peer cross-section "
                              "over the identical window. It is NOT excess return over an index and "
                              "must not be read as 'vs Nifty 500': no index series is used."),
        "reference_cross_section": cuts_row.get("ref_n"),
        "ret_p20_pct": jsonify(cuts_row.get("ret_p20")),
        "ret_p80_pct": jsonify(cuts_row.get("ret_p80")),
        "ret_median_pct": jsonify(cuts_row.get("ret_p50")),
        "vol_ratio_median": jsonify(cuts_row.get("vol_p50")),
        "deliv_shift_median_pp": jsonify(cuts_row.get("deliv_p50")),
        "material_pp": MATERIAL_PP,
        "min_sessions": MIN_SESSIONS,
        "note": ("The median name's volume FELL this quarter (ratio %s) and the median delivery "
                 "percentage ROSE (%s pp), so a fixed 1.0x or 'delivery up' rule would misread the "
                 "quarter. Both legs are judged against the market."
                 % (cuts_row.get("vol_p50"), cuts_row.get("deliv_p50"))),
    }
    out["price_window"] = {
        "current": [(_quarter_start(cur_end)).isoformat(), cur_end.isoformat()],
        "previous": [prev_start.isoformat(), prev_end.isoformat()],
        "sessions_current": sess_cur,
        "sessions_previous": sess_prev,
    }

    sel = [r for r in rows if in_view(r, view)]
    if status != "any":
        sel = [r for r in sel if r["status"] == status]
    if reaction != "any":
        sel = [r for r in sel if r["reaction"] == reaction]
    if basis == "same_source":
        sel = [r for r in sel if r["delta_basis"] == "same_source"]

    # Ordered by a measured column the caller names. Never by a composite.
    keys = {
        "inst_delta": lambda r: (r["inst_delta_pp"] is None, r["inst_delta_pp"] or 0),
        "ret":        lambda r: (r["ret_pct"] is None, r["ret_pct"] or 0),
        "vol_ratio":  lambda r: (r["vol_ratio"] is None, -(r["vol_ratio"] or 0)),
        "symbol":     lambda r: (False, r["symbol"]),
    }
    sel.sort(key=keys[sort])

    out["as_of"] = cur_end.isoformat()
    out["previous_period"] = prev_end.isoformat()
    out["total"] = len(sel)
    out["rows"] = [{k: jsonify(v) for k, v in r.items()} for r in sel[:limit]]
    out["count"] = len(out["rows"])
    return out
