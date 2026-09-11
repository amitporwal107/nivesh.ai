"""Technical indicators must see split/bonus-adjusted prices.

prices_eod is unadjusted, so a 1:1 bonus used to read as a 50% crash:
ANANDRATHI showed return_20d −51% the week after its 2026-06-03 bonus.
_to_arrays now scales each bar by the price adjuster's own factors,
normalised to the last bar so recomputed history has no look-ahead.
"""
from datetime import date, timedelta

import numpy as np

from nidp.services.price_adjuster.factors import CorpActionEvent
from nidp.services.technical_indicator_engine.service import _to_arrays


def _recs(closes, start=date(2026, 5, 25)):
    return [{"as_of_date": start + timedelta(days=i), "close_price": c, "open_price": c,
             "high_price": c * 1.01, "low_price": c * 0.99, "volume": 1000,
             "deliv_pct": 50.0, "source": "NSE_BHAVCOPY"} for i, c in enumerate(closes)]


def test_bonus_inside_window_is_adjusted_to_last_bar_basis():
    recs = _recs([3500.0, 3502.0, 1754.0, 1760.0])          # 1:1 bonus ex-dated on bar 2
    bonus = CorpActionEvent("X", recs[2]["as_of_date"], "BONUS", 0.5, 0.5)
    closes, opens, highs, lows, vols, _ = _to_arrays(recs, [bonus])
    assert np.allclose(closes, [1750.0, 1751.0, 1754.0, 1760.0])
    assert np.allclose(highs[:2], [3535.0 * 0.5, 3537.02 * 0.5])
    assert np.allclose(vols, [2000, 2000, 1000, 1000])       # pre-bonus share counts double
    assert closes[-1] == 1760.0                               # last bar keeps its actual price


def test_event_after_last_bar_is_ignored():
    recs = _recs([100.0, 101.0, 102.0])
    later = CorpActionEvent("X", recs[-1]["as_of_date"] + timedelta(days=5), "SPLIT", 0.2, 0.2)
    closes, *_ = _to_arrays(recs, [later])
    assert np.allclose(closes, [100.0, 101.0, 102.0])


def test_no_events_leaves_prices_untouched():
    closes, *_ = _to_arrays(_recs([100.0, 90.0]), None)
    assert np.allclose(closes, [100.0, 90.0])
