"""Point-in-time discipline: no slippage/execution/liquidity function in this package accepts a bar,
a list of bars, a DataFrame, or anything else shaped like a bars/future-data feed. Each one only
takes scalars the caller must already have computed from data strictly before the signal date. This
is enforced by the function signatures themselves; this test asserts that via introspection so a
future edit can't quietly add a bars-shaped parameter and reintroduce look-ahead.
"""
import inspect
from decimal import Decimal

import pandas as pd
import pytest

from research.costs import liquidity, slippage

FORBIDDEN_PARAM_NAME_FRAGMENTS = ("bar", "bars", "df", "dataframe", "frame", "series", "future", "window", "history")

SLIPPAGE_FUNCS = [
    slippage.fixed_pct, slippage.fixed_bps, slippage.liquidity_bucket_pct, slippage.liquidity_bucket,
    slippage.volume_dependent, slippage.atr_based, slippage.atr_based_pct, slippage.fixed_amount,
    slippage.apply_slippage,
]
LIQUIDITY_FUNCS = [liquidity.participation_ratio, liquidity.is_liquid]


@pytest.mark.parametrize("fn", SLIPPAGE_FUNCS + LIQUIDITY_FUNCS)
def test_signature_has_no_bars_shaped_parameter(fn):
    sig = inspect.signature(fn)
    for name in sig.parameters:
        lowered = name.lower()
        for fragment in FORBIDDEN_PARAM_NAME_FRAGMENTS:
            assert fragment not in lowered, (
                f"{fn.__name__}'s parameter {name!r} looks bars/history-shaped ({fragment!r}); "
                "slippage/liquidity functions must take only already-known scalars"
            )


@pytest.mark.parametrize("fn", SLIPPAGE_FUNCS)
def test_slippage_functions_reject_a_dataframe_argument(fn):
    """Belt-and-braces: even if a caller tried to hand a bars-shaped object in, passing a DataFrame
    where a Decimal/number is expected must fail loudly (a TypeError/decimal error from the
    arithmetic), not silently "work" by reading future rows."""
    bars = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2]})
    sig = inspect.signature(fn)
    args = [bars] * len(sig.parameters)
    with pytest.raises(Exception):
        fn(*args)


def test_engine_round_trip_takes_one_date_per_leg_not_a_bar_series():
    from research.costs.engine import compute_round_trip

    sig = inspect.signature(compute_round_trip)
    for name in ("buy_date", "sell_date"):
        assert name in sig.parameters
    for name in sig.parameters:
        lowered = name.lower()
        for fragment in FORBIDDEN_PARAM_NAME_FRAGMENTS:
            assert fragment not in lowered, f"compute_round_trip's parameter {name!r} looks bars-shaped"
