import numpy as np
import pandas as pd
import pytest

import phase1_common as C


def synth(n=120, missing_day=None):
    cal = pd.bdate_range("2024-07-25", periods=n + 5)
    idx = pd.DataFrame({"date": cal, "idx_close": np.linspace(100, 120, len(cal))})
    rows = []
    for sym, drift in (("AAA", 0.001), ("BBB", -0.001)):
        c = 100 * np.cumprod(1 + drift + 0.01 * np.sin(np.arange(len(cal))))
        for i, dte in enumerate(cal):
            if missing_day is not None and sym == "AAA" and i == missing_day:
                continue
            rows.append({"symbol": sym, "date": dte, "open": c[i] * 0.995, "high": c[i] * 1.02, "low": c[i] * 0.98,
                         "close": c[i], "volume": 1_000_000 * (3 if i == 100 else 1)})
    return pd.DataFrame(rows), idx


@pytest.fixture
def panel(monkeypatch):
    daily, idx = synth()
    monkeypatch.setattr(C, "load_daily", lambda s: daily[daily.date >= C.DISCOVERY_START].reset_index(drop=True))
    monkeypatch.setattr(C, "load_index", lambda: idx[idx.date >= C.DISCOVERY_START].reset_index(drop=True))
    monkeypatch.setattr(C.pd, "read_csv", lambda *a, **k: pd.DataFrame({"Symbol": ["AAA", "BBB"]}))
    return C.build_panel(), daily


def test_no_sealed_rows_and_labels(panel):
    d, raw = panel
    assert d.date.min() >= C.DISCOVERY_START
    a = d[d.symbol == "AAA"].reset_index(drop=True)
    i = 30
    assert a.loc[i, "L5_1"] == float(a.loc[i + 1, "high"] >= a.loc[i, "close"] * 1.05)
    assert a.loc[i, "net1"] == pytest.approx(a.loc[i + 1, "close"] / a.loc[i + 1, "open"] - 1 - a.loc[i, "cost"])
    assert a.loc[i, "mfe1"] == pytest.approx(a.loc[i + 1, "high"] / a.loc[i + 1, "open"] - 1)
    h5 = a.loc[i + 1:i + 5, "high"].max()
    assert a.loc[i, "L5_5"] == float(h5 >= a.loc[i, "close"] * 1.05)
    assert np.isnan(a.iloc[-1]["L5_1"]) and np.isnan(a.iloc[-3]["L5_5"])


def test_features(panel):
    d, _ = panel
    a = d[d.symbol == "AAA"].reset_index(drop=True)
    j = a.index[a.volume == 3_000_000][0]
    assert a.loc[j, "rvol"] == pytest.approx(3.0)
    assert a.loc[j, "hi20"] == pytest.approx(a.loc[j - 20:j - 1, "high"].max())
    assert a.loc[j, "value20"] == pytest.approx((a.close * a.volume).iloc[j - 19:j + 1].mean())
    assert np.isnan(a.loc[59, "atr_med"]) and np.isfinite(a.loc[61, "atr_med"])


def test_calendar_gap_blanks_labels(monkeypatch):
    daily, idx = synth(missing_day=50)
    monkeypatch.setattr(C, "load_daily", lambda s: daily[daily.date >= C.DISCOVERY_START].reset_index(drop=True))
    monkeypatch.setattr(C, "load_index", lambda: idx[idx.date >= C.DISCOVERY_START].reset_index(drop=True))
    monkeypatch.setattr(C.pd, "read_csv", lambda *a, **k: pd.DataFrame({"Symbol": ["AAA", "BBB"]}))
    d = C.build_panel()
    a = d[d.symbol == "AAA"].set_index("date")
    before_gap = idx.date.iloc[49]
    assert np.isnan(a.loc[before_gap, "L5_1"])  # next row is two sessions later: no label


def test_expanding_pct():
    x = np.r_[np.arange(60, dtype=float), 30.0, 100.0]
    p = C._expanding_pct(x)
    assert np.isnan(p[59]) and p[60] == pytest.approx(31 / 60) and p[61] == pytest.approx(1.0)


def test_stats_and_costs():
    assert list(C.cost(pd.Series([2e9, 5e8, 1e8]))) == [0.002, 0.003, 0.004]
    r = C.nw(np.full(50, 0.01))
    assert r["mean_pct"] == pytest.approx(1.0)
    sig = pd.DataFrame({"date": np.repeat(pd.bdate_range("2025-01-01", periods=20), 2), "net1": 0.01, "cost": 0.004})
    s = C.session_stats(sig, "net1")
    assert s["sessions"] == 20 and s["mean_pct"] == pytest.approx(1.0) and s["cost2x"]["mean_pct"] == pytest.approx(0.6)


def bars(rows):
    return pd.DataFrame(rows, columns=["hm", "o", "h", "l", "c", "v"])


def test_hc_entry_stop_and_time_exit():
    import phase1_intraday as I
    base = [("09:15", 100, 100, 95, 96, 1000), ("09:20", 96, 97, 94, 95, 1000), ("09:25", 95, 97, 95, 96.5, 5000),
            ("09:30", 96.6, 98, 96, 97.8, 5000)]
    # 09:25 close 96.5 >= 1.01 x running low 94 and above VWAP (96.17) -> entry at the 09:30 open, 96.6
    t = I.hc_trade(bars(base + [("09:35", 98, 99, 97, 98.5, 100), ("09:40", 98.5, 100, 98, 99, 100)]), official_close=101)
    assert t[0] == 96.6 and t[1] == 101 and t[2] == "TIME"
    t = I.hc_trade(bars(base + [("09:35", 98, 99, 93.5, 94, 100), ("09:40", 94, 95, 93, 94, 100)]), official_close=90)
    assert t[1] == 94 and t[2] == "STOP"  # stop = running low 94 at the trigger bar
    t = I.hc_trade(bars(base + [("09:35", 93, 94, 92, 93, 100), ("09:40", 93, 94, 92, 93, 100)]), official_close=90)
    assert t[1] == 93 and t[2] == "STOP_GAP"
    assert I.hc_trade(bars([("09:15", 100, 100, 95, 95.5, 1000), ("09:20", 95.5, 95.6, 95, 95.2, 1000), ("09:25", 95.2, 95.3, 95, 95.1, 1000)]), 99) is None


def test_hd_short_rules():
    import phase1_intraday as I
    obs = [("09:15", 100, 100.5, 98, 98.5, 1000), ("09:20", 98.5, 99, 97, 97.5, 1000), ("09:25", 97.5, 98, 96, 96.5, 1000),
           ("09:30", 96.5, 97, 96, 96.2, 1000), ("09:35", 96.2, 96.5, 95.5, 96, 1000), ("09:40", 96, 96.2, 95, 95.2, 1000)]
    t = I.hd_trade(bars(obs + [("09:45", 95, 95.5, 93, 93.5, 100), ("09:50", 93.5, 94, 92, 92.5, 100)]), official_close=92)
    assert t[0] == 95 and t[1] == 92 and t[2] == "TIME"
    t = I.hd_trade(bars(obs + [("09:45", 95, 97.5, 94, 97, 100)]), official_close=90)
    assert t[1] == pytest.approx(96.9) and t[2] == "STOP"  # 95 x 1.02
    up = [(h, o, hi, lo, c + 3, v) for h, o, hi, lo, c, v in obs]
    assert I.hd_trade(bars(up + [("09:45", 99, 100, 98, 99, 100)]), 99) is None  # recovered: not the rejected set
