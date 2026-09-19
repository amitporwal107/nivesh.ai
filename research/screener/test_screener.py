import numpy as np
import pandas as pd
import pytest

import screener as S
import validate_model as V


def q(sym, prev, o, h, l, last, vol=1000, vwap=None, uc=None, lc=None):
    return {"symbol": sym, "last_price": last, "volume": vol, "average_price": vwap or last, "upper_circuit_limit": uc or prev * 1.2,
            "lower_circuit_limit": lc or prev * 0.8, "last_trade_time": pd.Timestamp("2026-09-18 15:29:59"),
            "ohlc": {"open": o, "high": h, "low": l, "close": prev}}


@pytest.fixture
def snap():
    quotes = [q("UP8", 100, 101, 109, 100, 108, vol=2_000_000, vwap=105),   # +8%, strong close, Rs 21 cr
              q("UP6", 100, 104, 106, 99, 106, vol=10_000_000, vwap=103),  # +6%, gap +4, Rs 103 cr
              q("FADE", 100, 100, 107, 99, 101),                           # touched +7, closed +1
              q("UC", 50, 52, 60, 52, 60, uc=60),                          # upper circuit +20%
              q("DN", 200, 190, 192, 180, 184),                            # gap -5, -8%
              q("FLAT", 10, 10, 10.1, 9.9, 10)]
    return S.build_snapshot(quotes, pd.DataFrame({"symbol": ["UP8", "UP6", "FADE", "UC", "DN", "FLAT"], "name": list("abcdef"), "industry": "x"}))


def test_snapshot_fields(snap):
    r = snap.set_index("symbol")
    assert r.loc["UP8", "daily_change_pct"] == pytest.approx(8) and r.loc["UP8", "high_pct"] == pytest.approx(9)
    assert r.loc["UP6", "traded_value_cr"] == pytest.approx(103) and r.loc["UP6", "gap_pct"] == pytest.approx(4)
    assert r.loc["UC", "at_upper_circuit"] and not r.loc["UP8", "at_upper_circuit"]
    assert r.loc["UP8", "close_in_range"] == pytest.approx(8 / 9)


def test_gainers_filter_sort_fields_and_param(snap):
    sc = S.load_screens()
    g = S.run_screen(snap, sc["gainers"])
    assert g.symbol.tolist() == ["UC", "UP8", "UP6"]
    assert list(g.columns) == ["symbol", "last_price", "daily_change_pct", "volume", "traded_value_cr"]
    assert S.run_screen(snap, sc["gainers"], {"X": 7}).symbol.tolist() == ["UC", "UP8"]
    assert S.run_screen(snap, sc["losers"]).symbol.tolist() == ["DN"]


def test_outcome_screens(snap):
    sc = S.load_screens()
    assert S.run_screen(snap, sc["high_touch"]).symbol.tolist() == ["UC", "UP8", "FADE", "UP6"]
    assert S.run_screen(snap, sc["faded_highs"]).symbol.tolist() == ["FADE"]
    assert S.run_screen(snap, sc["gap_down"]).symbol.tolist() == ["DN"]
    assert S.run_screen(snap, sc["upper_circuit"]).symbol.tolist() == ["UC"]
    assert S.run_screen(snap, sc["liquid_gainers"]).symbol.tolist() == ["UP6"]
    assert S.run_screen(snap, sc["strong_close"]).symbol.tolist() == ["UC", "UP6"]  # UP8 closed at 8/9 = 0.89 of its range


def test_every_screen_runs(snap):
    for name, spec in S.load_screens().items():
        S.run_screen(snap, spec)


def test_evaluate_metrics():
    rng = np.random.default_rng(0)
    n = 200
    prob = np.linspace(0.3, 0.01, n)
    high = np.where(np.arange(n) < 20, 6.0, 1.0)  # the 20 highest-probability names all touch +5%
    p = pd.DataFrame({"symbol": [f"S{i}" for i in range(n)], "movement_probability": prob, "high_pct": high,
                      "daily_change_pct": high - 2, "selection_status": ["SELECTED"] * 5 + ["NOT_SELECTED"] * (n - 5)})
    r = V.evaluate(p.sample(frac=1, random_state=1), 5)
    assert r["hits"] == 20 and r["base_rate"] == pytest.approx(0.1) and r["selected_hits"] == 5
    assert r["precision_top10"] == 1 and r["lift_top10"] == pytest.approx(10) and r["recall_top50"] == 1
    assert r["auc"] == pytest.approx(1.0)
    assert r["brier"] == pytest.approx(np.mean((prob - (high >= 5)) ** 2))
    assert len(r["calibration_deciles"]) == 10


def test_auc_random_is_half():
    rng = np.random.default_rng(1)
    s, y = rng.random(5000), rng.random(5000) < 0.2
    assert abs(V.auc(s, y) - 0.5) < 0.03


def test_weekend_quote_takes_volume_from_bhavcopy(monkeypatch):
    b = pd.DataFrame({"symbol": ["A", "B"], "series": "EQ", "volume": [500, 2_000_000], "turnover": [50_000.0, 2.1e8]})
    monkeypatch.setattr(S, "bhavcopy", lambda session: b)
    quotes = [dict(q("A", 100, 100, 101, 99, 100), volume=0, average_price=0), dict(q("B", 100, 100, 106, 99, 105), volume=0, average_price=0)]
    d = S.build_snapshot(quotes, pd.DataFrame({"symbol": ["A", "B"]})).set_index("symbol")
    assert d.loc["B", "volume"] == 2_000_000 and d.loc["B", "traded_value_cr"] == pytest.approx(21.0)
    assert d.loc["B", "volume_source"] == "bhavcopy 2026-09-18"


def test_snapshot_from_bhavcopy(monkeypatch):
    b = pd.DataFrame({"symbol": ["A", "B"], "series": "EQ", "open": [100, 50], "high": [111, 51], "low": [99, 49],
                      "close": [110, 50], "prev_close": [100, 50], "volume": [1000, 0], "turnover": [105000.0, 0.0]})
    monkeypatch.setattr(S, "bhavcopy", lambda session: b)
    d = S.snapshot_from_bhavcopy("2026-09-17", ["A"]).set_index("symbol")
    assert list(d.index) == ["A"] and d.loc["A", "daily_change_pct"] == pytest.approx(10) and d.loc["A", "high_pct"] == pytest.approx(11)
    assert d.loc["A", "traded_value_cr"] == pytest.approx(0.0105) and d.loc["A", "volume_source"] == "bhavcopy 2026-09-17"
