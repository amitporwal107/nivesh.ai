"""Shared fixtures for the Ten-Percent Days 3.0 (`tpd_model`) pipeline tests.

These tests are written BEFORE the implementation (.claude/VERIFICATION_PROTOCOL.md). Every module
that imports `nidp.services.tpd_model` carries
`pytest.mark.xfail(raises=ModuleNotFoundError, strict=True)`, so today the suite reports them as
xfailed. Once a module lands, the import succeeds, any wrong behaviour fails for real, and a correct
implementation turns the test into a strict XPASS — remove the marker in that commit.

Interface the tests pin (spec: .claude/workspace/ten-percent-days-3/spec.md, test-plan.md §2):

panel DataFrame (one row per bar)
    symbol, as_of_date (datetime64), series, source ('NSE_BHAVCOPY' | 'BSE_BHAVCOPY'),
    open, high, low, close, prev_close, volume, turnover (rupees), deliverable_pct (float, NaN = missing)

tpd_model.panel_source
    select_nse_eq(rows, etf_symbols) -> DataFrame           NSE EQ rows only; ETFs removed; BSE never substitutes
    thin_sessions(panel, lookback=126, frac=0.8) -> list[date]
                                                            count < frac × median of the ≤lookback sessions BEFORE it

tpd_model.calendar
    cm_holidays(rows) -> set[date]                          rows with segment == 'CM' only
    next_trading_day(d, holidays, special_sessions=frozenset(), muhurat_sessions=frozenset(), known_until=None)
        -> (session: date, skipped_holidays: list[date])    weekday holidays skipped and listed; weekend special
                                                            sessions count; Muhurat never targeted; raises
                                                            CalendarUnknownError past known_until

tpd_model.universe
    pit_universe(panel, D, n=1000, lookback=126, min_bars=100) -> list[str]
                                                            sessions strictly before D; ≥min_bars bars in window;
                                                            median turnover desc, ties symbol asc

tpd_model.event_gate
    cutoff_ist(T) -> datetime                               15:30 Asia/Kolkata on session T
    results_flag(events, symbol, T, D) -> (value: bool | None, source_ts: datetime | None)
                                                            events: symbol, event_date, intimated_at (tz-aware or NaT)

tpd_model.corporate_actions
    adjusted_closes(bars, actions, as_of) -> pd.Series      bars: as_of_date, close; actions: ex_date, factor
                                                            (price multiplier, 0.5 = 1:1 bonus); ex_date > as_of ignored

tpd_model.labels
    touch_1d(prev_close, high, low) -> (up, down)           Decimal-exact, >= / <=
    touch_5d(close_T, highs, lows) -> (up, down) | None     None unless exactly 5 bars
    build_labels(panel, actions, muhurat_sessions=frozenset()) -> DataFrame
        columns: symbol, as_of_date (T), target_session, up_1d, down_1d, up_5d, down_5d, excl_1d, excl_5d

tpd_model.features
    FEATURE_LIST, EVENT_FEATURES, DELIVERY_FEATURES: tuple[str, ...]
    compute_features(panel, T, events=None, actions=None) -> DataFrame indexed by symbol, columns FEATURE_LIST
    feature_vector(panel, T, symbol, events=None, actions=None) -> {name: {"value", "data_date", ["source_ts"]}}
        data_date is a datetime.date (pandas Timestamps do not compare with date); source_ts is tz-aware IST

Dates passed in (T, D, as_of, session arguments) are datetime.date.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

IST = ZoneInfo("Asia/Kolkata")

NOT_IMPLEMENTED = pytest.mark.xfail(
    raises=ModuleNotFoundError,
    strict=True,
    reason="tpd_model not implemented yet (W1/W2) — remove this marker when the module lands",
)


def ist(d: date, hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm, ss), tzinfo=IST)


def weekday_sessions(start: str, n: int, holidays: frozenset[date] = frozenset()) -> list[date]:
    days = pd.bdate_range(start, periods=n + len(holidays) + 5)
    return [d.date() for d in days if d.date() not in holidays][:n]


def make_panel(symbols: list[str], sessions: list[date], seed: int = 7) -> pd.DataFrame:
    """Deterministic NSE EQ panel: random-walk closes, turnover rank fixed by symbol order."""
    rng = np.random.default_rng(seed)
    rows = []
    for i, sym in enumerate(symbols):
        close = 100.0 + 10 * i
        for d in sessions:
            prev = close
            close = round(prev * float(np.exp(rng.normal(0, 0.02))), 2)
            high = round(max(prev, close) * (1 + abs(rng.normal(0, 0.01))), 2)
            low = round(min(prev, close) * (1 - abs(rng.normal(0, 0.01))), 2)
            vol = int(1_000_000 / (i + 1) * (1 + rng.random()))
            rows.append({
                "symbol": sym, "as_of_date": pd.Timestamp(d), "series": "EQ", "source": "NSE_BHAVCOPY",
                "open": prev, "high": high, "low": low, "close": close, "prev_close": prev,
                "volume": vol, "turnover": vol * close, "deliverable_pct": float(40 + rng.random() * 30),
            })
    return pd.DataFrame(rows)


@pytest.fixture
def sessions() -> list[date]:
    return weekday_sessions("2025-01-01", 300)


@pytest.fixture
def symbols() -> list[str]:
    return [f"SYM{i:03d}" for i in range(40)]


@pytest.fixture
def panel(symbols, sessions) -> pd.DataFrame:
    return make_panel(symbols, sessions)
