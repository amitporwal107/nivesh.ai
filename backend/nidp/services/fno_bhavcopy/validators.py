"""Validation rules for the fno_bhavcopy ingester."""
from __future__ import annotations

from nidp.shared.validation import register
from nidp.shared.validation.rules import (
    CountAtLeastRule, CustomSQLRule, FailureClass, NoNullsRule, Severity,
)

# F&O bhavcopy publishes ~70-90k contracts per day across all expiries.
# <30k means partial fetch.
ROW_COUNT_MIN = CountAtLeastRule(
    name="fno_bhavcopy.row_count_min",
    sql="""
        SELECT count(*) FROM nidp.fno_bhavcopy
         WHERE as_of_date = $1::date
           AND source_run_id = $2
    """,
    min_count=30000,
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
)

REQUIRED_FIELDS = NoNullsRule(
    name="fno_bhavcopy.required_fields",
    table="nidp.fno_bhavcopy",
    columns=["ticker_symbol", "expiry_date", "instrument_type", "as_of_date"],
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
)

# At least one Nifty 50 options chain must be present per run. Acts
# as the canary that the FO file actually has options data (not just
# futures or a partial slice).
#
# Post-2024 NSE F&O codes (from F&O segment migration to new exchange
# stack): index options use `IDO` (Index Derivative Option), index
# futures use `IDF` (Index Derivative Future). Stock options/futures
# use STO/STF. Pre-2024 the codes were OPTIDX/FUTIDX/OPTSTK/FUTSTK —
# kept here as a fallback for any rerun against historical archives.
NIFTY_OPTIONS_PRESENT = CustomSQLRule(
    name="fno_bhavcopy.nifty_options_present",
    sql="""
        SELECT NOT EXISTS (
            SELECT 1 FROM nidp.fno_bhavcopy
             WHERE source_run_id = $1
               AND ticker_symbol = 'NIFTY'
               AND instrument_type IN ('IDO', 'IDF', 'OPTIDX', 'FUTIDX')
               AND (
                    -- IDO + legacy OPTIDX: must be a CE/PE row
                    (instrument_type IN ('IDO', 'OPTIDX') AND option_type IN ('CE', 'PE'))
                    -- IDF + legacy FUTIDX: futures rows have no option_type
                    OR instrument_type IN ('IDF', 'FUTIDX')
               )
               AND expiry_date IS NOT NULL
        )
    """,
    message="Nifty 50 options/futures missing from FO bhavcopy — partial fetch likely (checked IDO/IDF + legacy OPTIDX/FUTIDX)",
    severity=Severity.CRITICAL,
    failure_class=FailureClass.BLOCK,
    params_fn=lambda c: [c.job_run_id],
)

# Open-interest sanity: positive bounded values. Negative OI is
# nonsense; > 1e10 is clearly a data error.
OI_IN_RANGE = CustomSQLRule(
    name="fno_bhavcopy.oi_in_range",
    sql="""
        SELECT count(*) FROM nidp.fno_bhavcopy
         WHERE source_run_id = $1
           AND open_interest IS NOT NULL
           AND (open_interest < 0 OR open_interest > 1e10)
    """,
    sample_sql="""
        SELECT ticker_symbol, expiry_date, strike_price, option_type, open_interest
          FROM nidp.fno_bhavcopy
         WHERE source_run_id = $1
           AND open_interest IS NOT NULL
           AND (open_interest < 0 OR open_interest > 1e10)
         LIMIT 5
    """,
    message="open_interest outside sane range",
    severity=Severity.ERROR,
    failure_class=FailureClass.FIX,
    params_fn=lambda c: [c.job_run_id],
)

register("fno_bhavcopy", [
    ROW_COUNT_MIN,
    REQUIRED_FIELDS,
    NIFTY_OPTIONS_PRESENT,
    OI_IN_RANGE,
])
