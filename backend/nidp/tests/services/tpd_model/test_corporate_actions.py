"""A7 corporate actions: only factors with ex-date <= T, so later actions never rewrite the past (A3)."""
from datetime import date

import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import NOT_IMPLEMENTED, weekday_sessions

pytestmark = NOT_IMPLEMENTED

S = weekday_sessions("2026-05-01", 40)
EX = S[25]


def _bars_with_bonus():
    """1:1 bonus on EX: traded price halves overnight, business unchanged (+0.1%/day drift)."""
    closes, px = [], 200.0
    for d in S:
        px *= 1.001
        closes.append(px / 2 if d >= EX else px)
    return pd.DataFrame({"as_of_date": pd.to_datetime(S), "close": closes})


BONUS = pd.DataFrame({"ex_date": [pd.Timestamp(EX)], "factor": [0.5]})


def test_bonus_does_not_look_like_a_crash():
    from nidp.services.tpd_model.corporate_actions import adjusted_closes

    adj = adjusted_closes(_bars_with_bonus(), BONUS, as_of=S[30])
    ret20 = adj.iloc[-1] / adj.iloc[-21] - 1
    assert ret20 == pytest.approx(1.001 ** 20 - 1, rel=1e-9)  # not ~ -50%


def test_future_action_is_ignored():
    from nidp.services.tpd_model.corporate_actions import adjusted_closes

    bars = _bars_with_bonus()
    pre = bars[bars["as_of_date"] < pd.Timestamp(EX)]
    as_of = S[20]
    without = adjusted_closes(pre, BONUS.iloc[0:0], as_of=as_of)
    with_future = adjusted_closes(pre, BONUS, as_of=as_of)
    pd.testing.assert_series_equal(without, with_future)


def test_adding_a_later_action_does_not_change_earlier_values():
    from nidp.services.tpd_model.corporate_actions import adjusted_closes

    bars = _bars_with_bonus()
    later = pd.concat([BONUS, pd.DataFrame({"ex_date": [pd.Timestamp(S[35])], "factor": [0.2]})], ignore_index=True)
    a = adjusted_closes(bars, BONUS, as_of=S[30])
    b = adjusted_closes(bars, later, as_of=S[30])
    assert (a.to_numpy().view("uint64") == b.to_numpy().view("uint64")).all()


def test_only_bars_up_to_as_of_are_returned():
    from nidp.services.tpd_model.corporate_actions import adjusted_closes

    adj = adjusted_closes(_bars_with_bonus(), BONUS, as_of=S[30])
    assert adj.index.max() == pd.Timestamp(S[30])
    assert date(2026, 5, 1) <= adj.index.min().date()
