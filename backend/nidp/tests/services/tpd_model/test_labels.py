"""Labels: NI-3 intraday touch (1D), TECH-1 cumulative from close_T (5D), K3 CA-in-horizon, K6 Muhurat,
K10 exact-boundary Decimal arithmetic."""
from decimal import Decimal

import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import make_panel, weekday_sessions


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


def test_suspended_on_target_session_is_excluded_not_labelled_false():
    """Horizons are market sessions: a stock with no bar on D gets a reason, not its next bar days later."""
    from nidp.services.tpd_model.labels import build_labels

    s, p, _ = _panel_and_actions(ex_offset=0)
    p = p[~((p["symbol"] == "ACME") & (p["as_of_date"] == pd.Timestamp(s[11])))]
    lab = build_labels(p, pd.DataFrame(columns=["symbol", "ex_date", "factor"])).set_index(["symbol", "as_of_date"])
    row = lab.loc[("ACME", pd.Timestamp(s[10]))]
    assert row["target_session"] == pd.Timestamp(s[11])
    assert row["excl_1d"] == "no_bar_on_target" and pd.isna(row["up_1d"])
    assert row["excl_5d"] == "missing_bar_in_horizon"


def _hand_panel(closes, highs, lows):
    s = weekday_sessions("2026-03-02", len(closes))
    return s, pd.DataFrame({
        "symbol": "ACME", "as_of_date": pd.to_datetime(s), "series": "EQ", "source": "NSE_BHAVCOPY",
        "open": closes, "high": highs, "low": lows, "close": closes, "prev_close": closes,
        "volume": 1000, "turnover": 1e6, "deliverable_pct": 50.0,
    })


NO_ACTIONS = pd.DataFrame(columns=["symbol", "ex_date", "factor"])


def test_build_labels_counts_an_exact_ten_percent_touch():
    """14.60 -> 16.06 is exactly +10.00% and 10.20 -> 9.18 exactly -10.00%, but in float arithmetic
    16.06 * 100 = 1605.9999999999998 < 14.60 * 110 and 9.18 * 100 > 10.20 * 90 — both would be missed."""
    from nidp.services.tpd_model.labels import build_labels

    flat = [15.0] * 5
    s, up = _hand_panel([14.60, 15.00, *flat], [14.60, 16.06, *flat], [14.60, 14.50, *flat])
    assert build_labels(up, NO_ACTIONS).set_index("as_of_date").loc[pd.Timestamp(s[0]), "up_1d"] is True
    s, dn = _hand_panel([10.20, 9.50, *flat], [10.20, 9.90, *flat], [10.20, 9.18, *flat])
    assert build_labels(dn, NO_ACTIONS).set_index("as_of_date").loc[pd.Timestamp(s[0]), "down_1d"] is True


def test_build_labels_5d_is_cumulative_from_close_T():
    """The +10% touch happens mid-window (day 3) and fades: the window's highest high counts, not the last day's."""
    from nidp.services.tpd_model.labels import build_labels

    closes = [100.0, 102.5, 105.0, 108.0, 104.0, 103.0, 103.0]
    highs = [100.0, 103.0, 106.0, 111.0, 105.0, 103.5, 103.0]
    s, p = _hand_panel(closes, highs, closes)
    row = build_labels(p, NO_ACTIONS).set_index("as_of_date").loc[pd.Timestamp(s[0])]
    assert row["up_1d"] is False  # +3% on D
    assert row["up_5d"] is True and row["down_5d"] is False
