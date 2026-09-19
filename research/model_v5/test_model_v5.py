"""Tests for the Phases 2-3 dataset builder on synthetic data only (PREREGISTRATION_P2_P3.md §10 deliverable 1).
run: /app/research/tpd3_forward/venv/bin/python -m pytest -q test_model_v5.py
"""
import datetime as dt
import os
import sys
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dataset as DS  # noqa: E402
import labels as LB  # noqa: E402

from nidp.services.tpd_model.features_v4 import compute_features_v4  # noqa: E402
from nidp.services.tpd_model.risk import costs as CC  # noqa: E402

NAN = np.nan
CM = CC.load_cost_model(DS.COST_MODEL)


def arr(*rows):
    return np.array(rows, dtype=float)


def tbs(entry, O, H, L, C, tm=1.05, sm=0.98):
    r = LB.target_before_stop(np.array([entry], float), arr(O), arr(H), arr(L), arr(C), tm, sm)
    return r["outcome"][0], r["exit_px"][0], r["exit_k"][0]


# ---------- §4 tbs rule ----------

def test_target_first():
    assert tbs(100, [100, 101, 103, 104, 104], [101, 103, 106, 105, 105], [99, 100, 102, 103, 103],
               [100.5, 102, 104, 104, 104]) == ("TARGET", 105.0, 2)


def test_stop_first():
    assert tbs(100, [100, 99, 98.5, 97, 97], [101, 100, 99, 98, 98], [99, 98.5, 97.9, 96, 96],
               [99.5, 99, 98, 97, 97]) == ("STOP", 98.0, 2)


def test_same_bar_touching_both_is_stop():
    assert tbs(100, [100, 100, 100, 100, 100], [101, 106, 101, 101, 101], [99, 97, 99, 99, 99],
               [100, 100, 100, 100, 100]) == ("STOP", 98.0, 1)


def test_same_bar_on_s1_is_stop():
    assert tbs(100, [100, 100, 100, 100, 100], [106, 101, 101, 101, 101], [97.5, 99, 99, 99, 99],
               [100, 100, 100, 100, 100]) == ("STOP", 98.0, 0)


def test_gap_through_stop_exits_at_open():
    assert tbs(100, [100, 95, 96, 97, 97], [101, 96, 97, 98, 98], [99, 94, 95, 96, 96],
               [100, 95, 96, 97, 97]) == ("STOP", 95.0, 1)


def test_gap_over_target_exits_at_open():
    assert tbs(100, [100, 108, 100, 100, 100], [101, 109, 101, 101, 101], [99, 90, 99, 99, 99],
               [100, 100, 100, 100, 100]) == ("TARGET", 108.0, 1)


def test_expire_at_s5_close():
    assert tbs(100, [100, 101, 102, 103, 103], [101, 102, 103, 104, 104.9], [99, 100, 101, 102, 102],
               [100.5, 101.5, 102.5, 103, 104]) == ("EXPIRED", 104.0, 4)


def test_exact_levels_count_as_touched():
    assert tbs(100, [100, 101, 101, 101, 101], [101, 105, 102, 102, 102], [99, 100, 100, 100, 100],
               [100, 101, 101, 101, 101])[0] == "TARGET"
    assert tbs(100, [100, 101, 101, 101, 101], [101, 102, 102, 102, 102], [99, 98, 100, 100, 100],
               [100, 101, 101, 101, 101])[0] == "STOP"


def test_missing_bar_skipped_and_expires_at_last_bar():
    assert tbs(100, [100, NAN, 101, 102, NAN], [101, NAN, 102, 103, NAN], [99, NAN, 100, 101, NAN],
               [100, NAN, 101, 102.5, NAN]) == ("EXPIRED", 102.5, 3)


def test_tbs_10_4_levels():
    out, px, k = tbs(100, [100, 100, 100, 100, 100], [106, 109, 110, 101, 101], [97, 97, 99, 99, 99],
                     [100, 100, 100, 100, 100], 1.10, 0.96)
    assert (out, k) == ("TARGET", 2) and px == pytest.approx(110.0, abs=1e-9)       # exactly at +10% counts


# ---------- other labels ----------

def test_direction():
    e = np.array([100.0] * 4)
    H = arr([101, 106, 101, 101, 101], [101, 101, 101, 101, 101], [101, 106, 101, 101, 101], [104, 104, 104, 104, 104])
    L = arr([99, 99, 94, 99, 99], [99, 95, 99, 99, 99], [99, 95, 99, 99, 99], [96, 96, 96, 96, 96])
    assert list(LB.direction(e, H, L)) == ["UP", "DOWN", "AMBIGUOUS", "NONE"]


def test_direction_gap_bar_touching_both_is_ambiguous_literal_rule():
    e = np.array([100.0])
    assert list(LB.direction(e, arr([101, 107, 101, 101, 101]), arr([99, 94, 99, 99, 99]))) == ["AMBIGUOUS"]


def test_hit_labels_and_horizons():
    e = np.array([100.0, 100.0])
    H = arr([105, 101, 101, 101, 101], [101, 101, 101, 104, 110])
    L = arr([99, 99, 99, 99, 90], [99, 99, 99, 99, 99])
    C = arr([104, 100, 100, 100, 100], [100, 100, 100, 100, 105])
    assert list(LB.hit_high(e, H, 1.05, 1)) == [1.0, 0.0]
    assert list(LB.hit_high(e, H, 1.05, 3)) == [1.0, 0.0]
    assert list(LB.hit_high(e, H, 1.05, 5)) == [1.0, 1.0]
    assert list(LB.hit_high(e, H, 1.10, 5)) == [0.0, 1.0]
    assert list(LB.hit_low(e, L, 0.90, 5)) == [1.0, 0.0]
    assert list(LB.hit_close(e, C, 1.05, 5)) == [0.0, 1.0]


def test_net_return_hand_computed():
    # ₹100 entry, ₹105 exit, 0.05% per side: fills 100.05 / 104.9475; qty 499.
    got = LB.net_return(100.0, 105.0, Decimal("0.05"), CM, CC.fill_costs, dt.date(2022, 3, 1), dt.date(2022, 3, 3))
    buy, sell = Decimal("100.05") * 499, Decimal("104.9475") * 499
    # buy: STT 0.1% + txn 0.00307% + SEBI ₹10/cr + stamp 0.015% + GST 18% on (txn + SEBI)
    def c(v, side):
        txn, sebi = v * Decimal("0.0000307"), v * 10 / Decimal(10**7)
        parts = [v * Decimal("0.001"), txn, sebi, (txn + sebi) * Decimal("0.18")]
        parts += [v * Decimal("0.00015")] if side == "BUY" else [Decimal("15.34")]
        return sum(p.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP") for p in parts)
    want = float((sell - buy - c(buy, "BUY") - c(sell, "SELL")) / buy)
    assert got == pytest.approx(want, abs=1e-12)
    assert 0.045 < got < 0.047          # 5% gross - 0.1% slippage - 0.2% STT - stamp, DP etc.


# ---------- synthetic panel for the builder ----------

def _calendar(start="2021-01-01", n=150):
    return pd.bdate_range(start, periods=n)


def _bars(cal, symbols=("AAA", "BBB", "CCC"), seed=7):
    rng = np.random.default_rng(seed)
    rows = []
    for j, s in enumerate(symbols):
        c = 200.0 * (1 + j)
        for d in cal:
            o = c * (1 + rng.normal(0, 0.01))
            c = o * (1 + rng.normal(0, 0.02))
            h, lo = max(o, c) * (1 + abs(rng.normal(0, 0.01))), min(o, c) * (1 - abs(rng.normal(0, 0.01)))
            rows.append((s, d, o, h, lo, c, float(rng.integers(2e5, 6e5))))
    return pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])


def _block(cal, first=80, last_feat=140, last_bar=None):
    last_bar = cal[-1] if last_bar is None else last_bar
    return DS.Block("dev", cal[first].date(), cal[last_feat].date(), pd.Timestamp(last_bar).date(), ("dev",))


@pytest.fixture(scope="module")
def synth():
    cal = _calendar()
    bars = DS.prepare(_bars(cal))
    return cal, bars, _block(cal)


def test_builder_labels_match_the_pure_rule(synth):
    cal, bars, block = synth
    lab = DS.build_labels(bars, cal, block, CM)
    r = lab[(lab.symbol == "BBB") & (lab.date == cal[100])].iloc[0]
    w = bars[(bars.symbol == "BBB") & bars.date.isin(cal[101:106])].sort_values("date")
    assert r.entry_px == w.open.iloc[0] and r.entry_date == cal[101] and r.label_end_date == cal[105]
    out, px, k = tbs(w.open.iloc[0], *(w[c].to_list() for c in ("open", "high", "low", "close")))
    assert (r.tbs_5_2, r.tbs_5_2_exit_px, r.tbs_5_2_exit_date) == (out, px, cal[101 + k])
    assert r.hit_high_5_5d == float(w.high.max() >= w.open.iloc[0] * 1.05)
    assert r.gross_ret_5_2 == pytest.approx(px / w.open.iloc[0] - 1)


def test_no_bar_on_s1_is_excluded_and_counted(synth):
    cal, bars, block = synth
    b = bars[~((bars.symbol == "AAA") & (bars.date == cal[101]))]
    lab = DS.build_labels(b, cal, block, CM)
    r = lab[(lab.symbol == "AAA") & (lab.date == cal[100])].iloc[0]
    assert r.entry_status == "NO_BAR_S1" and np.isnan(r.entry_px) and r.tbs_5_2 is None and np.isnan(r.net_ret_5_2)


def test_upper_circuit_locked_open_is_excluded(synth):
    cal, bars, block = synth
    b = bars.copy()
    i = b.index[(b.symbol == "CCC") & (b.date == cal[101])][0]
    prev = b.loc[b.index[(b.symbol == "CCC") & (b.date == cal[100])][0], "close"]
    b.loc[i, ["open", "high"]] = prev * 1.20
    b.loc[i, "low"], b.loc[i, "close"] = prev * 1.15, prev * 1.18
    lab = DS.build_labels(b, cal, block, CM)
    assert lab[(lab.symbol == "CCC") & (lab.date == cal[100])].entry_status.iloc[0] == "LOCKED_UPPER_OPEN"


def test_net_return_only_on_eligible_entered_rows(synth):
    cal, bars, block = synth
    lab = DS.build_labels(bars, cal, block, CM)
    tradable = lab.eligible & (lab.entry_status == "OK")
    assert tradable.any() and lab.loc[tradable, "net_ret_5_2"].notna().all()
    assert lab.loc[~tradable, "net_ret_5_2"].isna().all()
    t = lab[tradable]
    assert (t.net_ret_5_2_opt >= t.net_ret_5_2).all() and (t.net_ret_5_2 >= t.net_ret_5_2_cons).all()
    assert (t.net_ret_5_2 < t.gross_ret_5_2).all()


# ---------- period guards ----------

def test_label_window_past_block_end_is_refused(synth):
    cal, bars, _ = synth
    with pytest.raises(DS.SealedDataError):
        DS.build_labels(bars, cal, _block(cal, last_feat=146), CM)       # s5 would be cal[151], beyond the calendar


def test_bar_after_block_end_is_refused(synth):
    cal, bars, _ = synth
    short = _block(cal, last_feat=130, last_bar=cal[135])
    with pytest.raises(DS.SealedDataError):
        DS.build_labels(bars, cal, short, CM)
    with pytest.raises(DS.SealedDataError):
        DS.build_features(DS.to_panel(bars), cal, short, {"AAA", "BBB", "CCC"}, workers=1)


def test_label_reading_past_bar_end_is_refused(synth):
    cal, bars, _ = synth
    blk = _block(cal, last_feat=132, last_bar=cal[135])
    b, c = bars[bars.date <= cal[135]], cal[:136]
    with pytest.raises(DS.SealedDataError):
        DS.build_labels(b, c, blk, CM)                                   # D = cal[132] needs cal[137]


def test_loader_cuts_at_block_end(tmp_path, synth):
    cal, _, _ = synth
    raw = _bars(cal)
    raw.assign(date=raw.date.dt.strftime("%Y-%m-%d")).to_csv(tmp_path / "part-1.csv.gz", index=False)
    blk = _block(cal, last_feat=100, last_bar=cal[110])
    got = DS.load_bars({"AAA", "BBB"}, blk, pattern=str(tmp_path / "part-*.csv.gz"))
    assert got.date.max() == cal[110] and set(got.symbol) == {"AAA", "BBB"}


def test_test_block_needs_frozen_models():
    with pytest.raises(DS.SealedDataError):
        DS.check_block(DS.BLOCKS["test"], None)
    DS.check_block(DS.BLOCKS["test"], "abc123")
    DS.check_block(DS.BLOCKS["dev"], None)


def test_frozen_block_dates():
    d, t = DS.BLOCKS["dev"], DS.BLOCKS["test"]
    assert (d.feat_start, d.feat_end, d.bar_end) == (dt.date(2021, 1, 1), dt.date(2022, 12, 22), dt.date(2022, 12, 30))
    assert (t.feat_start, t.feat_end, t.bar_end) == (dt.date(2023, 1, 2), dt.date(2024, 7, 24), dt.date(2024, 7, 31))


# ---------- look-ahead ----------

def test_labels_ignore_bars_after_s5_and_features_ignore_bars_after_T(synth):
    cal, bars, block = synth
    D = cal[110]
    shocked = bars.copy()
    m = shocked.date > cal[115]
    shocked.loc[m, ["open", "high", "low", "close"]] *= 3.0
    shocked.loc[m, "volume"] *= 10
    shocked = DS.prepare(shocked[["symbol", "date", "open", "high", "low", "close", "volume"]])
    a, b = (DS.build_labels(x, cal, block, CM) for x in (bars, shocked))
    ra, rb = a[a.date <= D].reset_index(drop=True), b[b.date <= D].reset_index(drop=True)
    pd.testing.assert_frame_equal(ra, rb)
    s2 = bars.copy()
    s2.loc[s2.date > D, ["open", "high", "low", "close"]] *= 0.5
    fa = DS.build_features(DS.to_panel(bars), cal, _block(cal, first=110, last_feat=110), {"AAA", "BBB", "CCC"}, 1)
    fb = DS.build_features(DS.to_panel(DS.prepare(s2[["symbol", "date", "open", "high", "low", "close", "volume"]])),
                           cal, _block(cal, first=110, last_feat=110), {"AAA", "BBB", "CCC"}, 1)
    pd.testing.assert_frame_equal(fa, fb)
    assert len(fa) == 3


def test_label_changes_when_a_window_bar_changes(synth):
    cal, bars, block = synth
    b = bars.copy()
    i = b.index[(b.symbol == "AAA") & (b.date == cal[103])][0]
    e = b.loc[b.index[(b.symbol == "AAA") & (b.date == cal[101])][0], "open"]
    b.loc[i, "high"] = e * 1.20
    lab = DS.build_labels(b, cal, block, CM)
    assert lab[(lab.symbol == "AAA") & (lab.date == cal[100])].hit_high_10_5d.iloc[0] == 1.0


# ---------- v4 feature parity ----------

def test_feature_set_is_the_frozen_44():
    assert len(DS.FEATURES) == 44 and len(set(DS.FEATURES)) == 44
    for banned in ("deliv_prev", "deliv_avg20", "deliv_trend10", "deliv_missing", "res_on_T", "res_on_D", "fund_missing",
                   "own_missing"):
        assert banned not in DS.FEATURES


def test_features_equal_the_v4_code_and_parallel_equals_serial(synth):
    cal, bars, _ = synth
    blk = _block(cal, first=120, last_feat=127)
    panel = DS.to_panel(bars)
    members = {"AAA", "BBB", "CCC"}
    serial = DS.build_features(panel, cal, blk, members, workers=1)
    par = DS.build_features(panel, cal, blk, members, workers=2)
    pd.testing.assert_frame_equal(serial, par)
    T = cal[124]
    direct = compute_features_v4(panel[panel.as_of_date <= T], T.date(), financials=None, target_session=cal[125].date(),
                                 market_members=members)[list(DS.FEATURES)]
    mine = serial[serial.date == T].set_index("symbol")[list(DS.FEATURES)]
    pd.testing.assert_frame_equal(mine, direct, check_names=False)
    assert mine.notna().sum().sum() > 0.8 * mine.size
