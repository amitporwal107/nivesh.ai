"""OHLCV validation — PRD docs/charting.md §9.1 (rules) and §9.2 (status), spec gap G-14.

Every check below returns Finding rows: `date`, `rule_id`, `observed` (plus an optional
`detail` dict for extra machine-readable context). `rule_id` is each rule's own
deterministic reason code — the same fixed string every time that rule fires, never a
free-text message — so findings can be counted, filtered and diffed run over run.

This module reports; it does not repair. research.charting.bars hands it whatever rows
the source files actually contain (duplicates, gaps and all), and every rule here exists
to describe that, not fix it.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Collection, Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

RULE_IDS = (
    "HIGH_BELOW_BODY",
    "LOW_ABOVE_BODY",
    "HIGH_BELOW_LOW",
    "NONPOSITIVE_PRICE",
    "NEGATIVE_VOLUME",
    "DUPLICATE_TIMESTAMP",
    "OUT_OF_ORDER",
    "MISSING_CANDLE",
    "CORPORATE_ACTION_DISCONTINUITY",
    "INCOMPLETE_CANDLE",
)


@dataclass(frozen=True)
class Finding:
    date: Any
    rule_id: str
    observed: Any
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# §9.1 OHLCV integrity rules (operate row-by-row on one symbol's frame)
# ---------------------------------------------------------------------------

def _check_high_below_body(df: pd.DataFrame) -> list[Finding]:
    body_top = df[["open", "close"]].max(axis=1)
    mask = df["high"] < body_top
    sub = df.loc[mask]
    return [
        Finding(date=d, rule_id="HIGH_BELOW_BODY", observed=h,
                detail={"open": o, "close": c, "expected_min_high": bt})
        for d, h, o, c, bt in zip(sub["date"], sub["high"], sub["open"], sub["close"], body_top.loc[mask])
    ]


def _check_low_above_body(df: pd.DataFrame) -> list[Finding]:
    body_bottom = df[["open", "close"]].min(axis=1)
    mask = df["low"] > body_bottom
    sub = df.loc[mask]
    return [
        Finding(date=d, rule_id="LOW_ABOVE_BODY", observed=lo,
                detail={"open": o, "close": c, "expected_max_low": bb})
        for d, lo, o, c, bb in zip(sub["date"], sub["low"], sub["open"], sub["close"], body_bottom.loc[mask])
    ]


def _check_high_below_low(df: pd.DataFrame) -> list[Finding]:
    mask = df["high"] < df["low"]
    sub = df.loc[mask]
    return [
        Finding(date=d, rule_id="HIGH_BELOW_LOW", observed=h, detail={"low": lo})
        for d, h, lo in zip(sub["date"], sub["high"], sub["low"])
    ]


def _check_nonpositive_price(df: pd.DataFrame) -> list[Finding]:
    mask = (df["open"] <= 0) | (df["close"] <= 0)
    sub = df.loc[mask]
    findings = []
    for d, o, c in zip(sub["date"], sub["open"], sub["close"]):
        observed = o if o <= 0 else c
        findings.append(Finding(date=d, rule_id="NONPOSITIVE_PRICE", observed=observed,
                                 detail={"open": o, "close": c}))
    return findings


def _check_negative_volume(df: pd.DataFrame) -> list[Finding]:
    mask = df["volume"] < 0
    sub = df.loc[mask]
    return [
        Finding(date=d, rule_id="NEGATIVE_VOLUME", observed=v)
        for d, v in zip(sub["date"], sub["volume"])
    ]


def _check_duplicate_timestamp(df: pd.DataFrame) -> list[Finding]:
    counts = df["date"].value_counts()
    dupes = counts[counts > 1]
    return [
        Finding(date=d, rule_id="DUPLICATE_TIMESTAMP", observed=int(n))
        for d, n in sorted(dupes.items())
    ]


def _check_out_of_order(df: pd.DataFrame) -> list[Finding]:
    dates = df["date"].tolist()
    findings = []
    for i in range(1, len(dates)):
        if dates[i] < dates[i - 1]:
            findings.append(Finding(date=dates[i], rule_id="OUT_OF_ORDER", observed=dates[i - 1],
                                     detail={"row_index": i}))
    return findings


def _check_incomplete_candle(df: pd.DataFrame) -> list[Finding]:
    """§9.1 incomplete sessions. `is_complete` is not one of BARS_COLUMNS — bars.py never
    supplies it — so this rule only fires when a caller passes it in explicitly (e.g. an
    intraday/live-tracking frame). Absent the column, this is a no-op.
    """
    if "is_complete" not in df.columns:
        return []
    mask = df["is_complete"] == False  # noqa: E712 - explicit False, not falsy/NaN
    return [
        Finding(date=d, rule_id="INCOMPLETE_CANDLE", observed=False)
        for d in df.loc[mask, "date"]
    ]


# Candidate split/bonus ratios (close-to-open, prior-close basis) per the task spec:
# 1:1 bonus or 1:2 split -> 0.5; 1:3 split -> 1/3; 2-for-3 style corporate actions -> 2/3;
# 1:5 split -> 0.2; 1:10 split -> 0.1. A reverse-split/consolidation (price roughly
# multiplying) is out of scope here — none of PRD's example ratios are >1 and none were
# needed for the real 2021-2026 NSE cases this was tested against (see bars 4 below).
CORPORATE_ACTION_RATIOS: tuple[float, ...] = (0.5, 1 / 3, 2 / 3, 0.2, 0.1)


def _check_corporate_action_discontinuity(
    df: pd.DataFrame, *, ratio_tolerance: float = 0.02, min_gap: float = 0.15,
) -> list[Finding]:
    """§9.1 corporate-action discontinuity: an overnight open/prior-close ratio close to
    one of CORPORATE_ACTION_RATIOS, and only when the gap is well beyond an ordinary
    trading gap (`min_gap`, default 15%) — a normal single-digit-percent gap must never
    match. `ratio_tolerance` is an absolute tolerance on the ratio itself (default 2
    percentage points), to allow for a few paise of rounding around a clean split ratio.
    """
    findings = []
    prev_close = None
    for row in df.itertuples(index=False):
        if prev_close is not None and prev_close > 0 and row.open > 0:
            ratio = row.open / prev_close
            if abs(ratio - 1) >= min_gap:
                nearest = min(CORPORATE_ACTION_RATIOS, key=lambda t: abs(t - ratio))
                if abs(ratio - nearest) <= ratio_tolerance:
                    findings.append(Finding(
                        date=row.date, rule_id="CORPORATE_ACTION_DISCONTINUITY",
                        observed=round(ratio, 4),
                        detail={"matched_ratio": nearest, "previous_close": prev_close, "open": row.open},
                    ))
        prev_close = row.close
    return findings


# ---------------------------------------------------------------------------
# §9.1 MISSING_CANDLE — needs a calendar, which is a whole-universe concept
# ---------------------------------------------------------------------------

def build_trading_calendar(frames: Iterable[pd.DataFrame]) -> frozenset:
    """The trading calendar used by MISSING_CANDLE is the UNION of every `date` value
    seen across the whole universe (data-availability.md / task instruction: "derive the
    calendar as the union of dates across the whole universe, and document that choice").

    Why: we have no independently-verified NSE holiday/session calendar loaded in this
    research engine, and building one would introduce an unverified second data source.
    The union of dates actually traded, system-wide, in the Kite daily-bars directory is
    a reasonable stand-in *as long as at least one liquid symbol traded on every real
    session* — which holds for NSE main-board equities. Its known weakness: a real
    session on which every single symbol in the directory happened to be absent would
    silently not appear in the derived calendar (undercounting gaps that day for
    everyone); conversely a bad non-trading-day row from a single corrupted symbol would
    leak a false session into the calendar (which would itself also show up as its own
    finding on that symbol, e.g. OUT_OF_ORDER or a duplicate around it).

    Pass any iterable of DataFrames with a `date` column, e.g. `(df for _, df in
    bars.load_all())` or `bars_by_symbol.values()`.
    """
    calendar: set = set()
    for df in frames:
        if df is not None and not df.empty:
            calendar.update(df["date"].tolist())
    return frozenset(calendar)


def _check_missing_candle(df: pd.DataFrame, calendar: Collection | None) -> list[Finding]:
    """Interior gaps only: dates strictly within [symbol's first date, symbol's last
    date] that are in `calendar` but absent from this symbol's own dates. Dates before a
    symbol's first observed session (not yet listed) or after its last (delisted, or the
    feed simply hasn't caught up to a newer session than this frame's last row) are not
    "missing" — see data-availability.md Finding 2, which frames existing gaps as
    "interior" for the same reason.
    """
    if calendar is None or df.empty:
        return []
    dates_present = set(df["date"].tolist())
    lo, hi = df["date"].min(), df["date"].max()
    expected = {d for d in calendar if lo <= d <= hi}
    missing = sorted(expected - dates_present)
    return [
        Finding(date=d, rule_id="MISSING_CANDLE", observed=None,
                detail={"symbol_first_date": lo, "symbol_last_date": hi})
        for d in missing
    ]


# ---------------------------------------------------------------------------
# Aggregate: run every rule for one symbol
# ---------------------------------------------------------------------------

def validate_symbol(
    df: pd.DataFrame,
    *,
    calendar: Collection | None = None,
    ca_ratio_tolerance: float = 0.02,
    ca_min_gap: float = 0.15,
) -> list[Finding]:
    """Run every §9.1 rule against one symbol's bars frame (as returned by
    research.charting.bars.load_symbol / load_all) and return every Finding, sorted by
    (date, rule_id). `calendar` is optional — pass build_trading_calendar(...) to enable
    MISSING_CANDLE; without it that rule is simply not evaluated (not "no findings" by
    fabrication, but genuinely skipped since there is nothing to compare against).
    """
    findings: list[Finding] = []
    findings += _check_high_below_body(df)
    findings += _check_low_above_body(df)
    findings += _check_high_below_low(df)
    findings += _check_nonpositive_price(df)
    findings += _check_negative_volume(df)
    findings += _check_duplicate_timestamp(df)
    findings += _check_out_of_order(df)
    findings += _check_missing_candle(df, calendar)
    findings += _check_corporate_action_discontinuity(df, ratio_tolerance=ca_ratio_tolerance, min_gap=ca_min_gap)
    findings += _check_incomplete_candle(df)
    return sorted(findings, key=lambda f: (str(f.date), f.rule_id))


# ---------------------------------------------------------------------------
# §9.2 status — spec gap G-14: data_quality_status and pit_status are two ORTHOGONAL
# fields, not one conflated enum. A symbol's OHLCV can be internally VALID while its
# adjustment/point-in-time provenance is still PIT_UNVERIFIED, or vice versa.
# ---------------------------------------------------------------------------

DATA_QUALITY_STATUSES = ("VALID", "PARTIAL", "STALE", "INVALID", "BLOCKED")
PIT_STATUSES = ("PIT_VALIDATED", "PIT_UNVERIFIED", "PIT_BLOCKED")

# Findings that mean the OHLCV itself is internally broken/untrustworthy.
HARD_INVALID_RULE_IDS = frozenset({
    "HIGH_BELOW_BODY", "LOW_ABOVE_BODY", "HIGH_BELOW_LOW",
    "NONPOSITIVE_PRICE", "NEGATIVE_VOLUME", "DUPLICATE_TIMESTAMP", "OUT_OF_ORDER",
})
# Findings that mean the data is real but incomplete, not broken.
SOFT_RULE_IDS = frozenset({"MISSING_CANDLE", "INCOMPLETE_CANDLE"})
# CORPORATE_ACTION_DISCONTINUITY is deliberately in neither set: it is informational
# (a legitimate price discontinuity, split/bonus or otherwise) and must not by itself
# downgrade data_quality_status.


@dataclass(frozen=True)
class SymbolStatus:
    data_quality_status: str
    pit_status: str


def _data_quality_status(
    df: pd.DataFrame, findings: list[Finding], *,
    as_of: Any, stale_after_days: int, blocked_row_fraction: float,
) -> str:
    n = len(df)
    if n == 0:
        return "BLOCKED"
    hard = [f for f in findings if f.rule_id in HARD_INVALID_RULE_IDS]
    if hard:
        affected_dates = {f.date for f in hard}
        if len(affected_dates) / n >= blocked_row_fraction:
            return "BLOCKED"
        return "INVALID"
    if as_of is not None:
        last = pd.Timestamp(df["date"].max())
        if (pd.Timestamp(as_of) - last).days > stale_after_days:
            return "STALE"
    if any(f.rule_id in SOFT_RULE_IDS for f in findings):
        return "PARTIAL"
    return "VALID"


def _pit_status(adjustment_verified: bool | None) -> str:
    if adjustment_verified is None:
        return "PIT_UNVERIFIED"
    return "PIT_VALIDATED" if adjustment_verified else "PIT_BLOCKED"


def symbol_status(
    df: pd.DataFrame,
    findings: list[Finding],
    *,
    as_of: Any = None,
    stale_after_days: int = 10,
    blocked_row_fraction: float = 0.5,
    adjustment_verified: bool | None = None,
) -> SymbolStatus:
    """Per-symbol status, PRD §9.2 / spec gap G-14. Two independently-computed,
    orthogonal fields in one call:

    - data_quality_status in {VALID, PARTIAL, STALE, INVALID, BLOCKED}: derived only from
      `findings` and row count. Precedence (highest wins): 0 rows -> BLOCKED; hard-invalid
      findings covering >= blocked_row_fraction of rows -> BLOCKED; any hard-invalid
      finding -> INVALID; last date older than `as_of` by more than stale_after_days (only
      evaluated when `as_of` is given — no hidden "today" assumption) -> STALE; a
      MISSING_CANDLE/INCOMPLETE_CANDLE finding -> PARTIAL; else VALID.
    - pit_status in {PIT_VALIDATED, PIT_UNVERIFIED, PIT_BLOCKED}: independent of the OHLCV
      findings entirely. Reflects whether this symbol's adjustment/availability provenance
      has been independently confirmed (`adjustment_verified=True/False`); defaults to
      PIT_UNVERIFIED, matching data-availability.md's "Manifest says yes — UNVERIFIED".
    """
    dq = _data_quality_status(df, findings, as_of=as_of, stale_after_days=stale_after_days,
                               blocked_row_fraction=blocked_row_fraction)
    pit = _pit_status(adjustment_verified)
    return SymbolStatus(data_quality_status=dq, pit_status=pit)


# ---------------------------------------------------------------------------
# Tracker T11 — corporate-action adjustment check
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorporateActionCheckResult:
    symbol: str
    event_date: Any
    before: list[dict]
    after: list[dict]
    ratio_at_event: float | None
    discontinuity_findings: list[Finding]
    verdict: str  # "LOOKS_ADJUSTED" | "LOOKS_UNADJUSTED" | "INCONCLUSIVE"


def check_known_corporate_action(
    symbol: str,
    df: pd.DataFrame,
    event_date: _dt.date | pd.Timestamp | str,
    *,
    window_bars: int = 5,
    ratio_tolerance: float = 0.02,
    min_gap: float = 0.15,
) -> CorporateActionCheckResult:
    """Tracker T11. For a symbol and a KNOWN corporate-action date (verified externally,
    not derived from this frame), report the `window_bars` closing/opening prices on
    either side of the event and whether the series shows a CORPORATE_ACTION_DISCONTINUITY
    around it.

    Verdict:
    - LOOKS_ADJUSTED: the event date is covered by this frame and no discontinuity was
      found within +/-1 session of it -> the series does not show the raw split/bonus
      jump, i.e. it appears to already be back-adjusted for this event.
    - LOOKS_UNADJUSTED: a discontinuity WAS found at/around the event date -> the series
      still shows the raw jump, i.e. it does not appear to be adjusted for this event.
    - INCONCLUSIVE: the event date (or the bars immediately around it) is not covered by
      this frame at all, so nothing can be said either way.

    This never asserts "adjusted" or "unadjusted" for the whole source, only for the one
    (symbol, event_date) pair actually checked — data-availability.md's "Manifest says
    yes — UNVERIFIED" note is about the whole directory; this function is how you verify
    one real case of it.
    """
    event_ts = pd.Timestamp(event_date)
    df = df.reset_index(drop=True)
    if df.empty or event_ts < df["date"].min() or event_ts > df["date"].max():
        return CorporateActionCheckResult(
            symbol=symbol, event_date=event_ts, before=[], after=[], ratio_at_event=None,
            discontinuity_findings=[], verdict="INCONCLUSIVE",
        )

    before_mask = df["date"] < event_ts
    after_mask = df["date"] >= event_ts
    before_rows = df.loc[before_mask].tail(window_bars)
    after_rows = df.loc[after_mask].head(window_bars)

    def _rows_to_dicts(rows: pd.DataFrame) -> list[dict]:
        return [
            {"date": r.date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": r.volume}
            for _, r in rows.iterrows()
        ]

    ratio_at_event = None
    if not before_rows.empty and not after_rows.empty:
        prev_close = before_rows.iloc[-1]["close"]
        first_open = after_rows.iloc[0]["open"]
        if prev_close > 0:
            ratio_at_event = round(first_open / prev_close, 4)

    all_findings = _check_corporate_action_discontinuity(df, ratio_tolerance=ratio_tolerance, min_gap=min_gap)
    near_event = [
        f for f in all_findings
        if abs((pd.Timestamp(f.date) - event_ts).days) <= 7
    ]

    verdict = "LOOKS_UNADJUSTED" if near_event else "LOOKS_ADJUSTED"

    return CorporateActionCheckResult(
        symbol=symbol,
        event_date=event_ts,
        before=_rows_to_dicts(before_rows),
        after=_rows_to_dicts(after_rows),
        ratio_at_event=ratio_at_event,
        discontinuity_findings=near_event,
        verdict=verdict,
    )
