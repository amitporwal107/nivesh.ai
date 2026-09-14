"""Labels: NI-3 intraday touch (1D), TECH-1 cumulative from close_T (5D), K3 CA-in-horizon, K6 Muhurat,
K10 exact-boundary Decimal arithmetic."""
from decimal import Decimal

import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import NOT_IMPLEMENTED, make_panel, weekday_sessions

pytestmark = NOT_IMPLEMENTED


@pytest.mark.parametrize("prev,high,low,expected", [
    ("110.50", "121.55", "108.00", (True, False)),   # exactly +10.00%: float 110.5*1.1 = 121.55000000000001
    ("110.50", "121.54", "108.00", (False, False)),
    ("100.00", "101.00", "90.00", (False, True)),    # exactly -10.00%
    ("100.00", "110.00", "90.00", (True, True)),     # both touched in one session
    ("100.00", "109.99", "90.01", (False, False)),   # 10%-band circuit prints stay false
])
def test_touch_1d_is_decimal_exact(prev, high, low, expected):
    from nidp.services.tpd_model.labels import touch_1d

    assert touch_1d(Decimal(prev), Decimal(high), Decimal(low)) == expected


def test_touch_1d_accepts_float_inputs_without_binary_error():
    from nidp.services.tpd_model.labels import touch_1d

    assert touch_1d(110.5, 121.55, 108.0) == (True, False)


def test_touch_5d_is_cumulative_from_close_T_not_per_day():
    """Five +2.5% days = +13.1% from close_T, but no single day moved 10% vs its own prev close."""
    from nidp.services.tpd_model.labels import touch_1d, touch_5d

    close_t = Decimal("100")
    closes = [close_t * Decimal("1.025") ** k for k in range(1, 6)]
    assert touch_5d(close_t, highs=closes, lows=[close_t] * 5) == (True, False)
    prevs = [close_t, *closes[:-1]]
    assert not any(touch_1d(p, h, p)[0] for p, h in zip(prevs, closes))


def test_touch_5d_requires_exactly_five_bars():
    from nidp.services.tpd_model.labels import touch_5d

    assert touch_5d(Decimal("100"), highs=[Decimal("111")] * 4, lows=[Decimal("95")] * 4) is None


def _panel_and_actions(ex_offset):
    s = weekday_sessions("2026-01-01", 30)
    p = make_panel(["ACME", "PEER"], s)
    actions = pd.DataFrame({"symbol": ["ACME"], "ex_date": [pd.Timestamp(s[ex_offset])], "factor": [0.5]})
    return s, p, actions


def test_no_1d_label_on_corporate_action_day():
    from nidp.services.tpd_model.labels import build_labels

    s, p, actions = _panel_and_actions(ex_offset=11)
    lab = build_labels(p, actions).set_index(["symbol", "as_of_date"])
    row = lab.loc[("ACME", pd.Timestamp(s[10]))]  # T = s[10], D = s[11] = ex-date
    assert row["excl_1d"] == "corporate_action"
    assert pd.isna(row["up_1d"]) and pd.isna(row["down_1d"])


def test_5d_row_with_action_inside_horizon_is_excluded_k3():
    from nidp.services.tpd_model.labels import build_labels

    s, p, actions = _panel_and_actions(ex_offset=14)
    lab = build_labels(p, actions).set_index(["symbol", "as_of_date"])
    row = lab.loc[("ACME", pd.Timestamp(s[10]))]  # horizon s[11]..s[15] contains s[14]
    assert row["excl_5d"] == "corporate_action_in_horizon"
    assert pd.isna(row["up_5d"])
    assert row["excl_1d"] is None or pd.isna(row["excl_1d"])  # 1D (D = s[11]) is unaffected
    peer = lab.loc[("PEER", pd.Timestamp(s[10]))]
    assert pd.isna(peer["excl_5d"])


def test_incomplete_5d_horizon_is_excluded_not_labelled_false():
    from nidp.services.tpd_model.labels import build_labels

    s, p, _ = _panel_and_actions(ex_offset=0)
    lab = build_labels(p, pd.DataFrame(columns=["symbol", "ex_date", "factor"])).set_index(["symbol", "as_of_date"])
    row = lab.loc[("PEER", pd.Timestamp(s[-3]))]
    assert row["excl_5d"] == "incomplete_horizon"
    assert pd.isna(row["up_5d"]) and pd.isna(row["down_5d"])


def test_muhurat_session_is_never_labelled_k6():
    from nidp.services.tpd_model.labels import build_labels

    s, p, _ = _panel_and_actions(ex_offset=0)
    lab = build_labels(p, pd.DataFrame(columns=["symbol", "ex_date", "factor"]),
                       muhurat_sessions=frozenset({s[11]})).set_index(["symbol", "as_of_date"])
    assert lab.loc[("PEER", pd.Timestamp(s[10]))]["excl_1d"] == "muhurat"
