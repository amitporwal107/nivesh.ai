"""Positional study runner — leakage and mapping tests on SYNTHETIC data only (no real price is loaded, so running
these tests reveals nothing about the pre-registered outcome)."""
from __future__ import annotations

import datetime as dt
import gzip
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import controls as K  # noqa: E402
import report as R  # noqa: E402
import signals as S  # noqa: E402
import snapshot as SN  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
RULE = {"rule_id": "R-NSE-RES-1", "rule_version": 1, "validation_sample_size": 576, "validation_coverage": "test",
        "evidence": "test", "approval_status": "APPROVED"}


def synth(days=220, symbols=("A", "B", "C", "D", "E"), seed=3, shock_after=None):
    """Random-walk panel with Phase-1-style columns computed BACKWARD only; optional huge change after `shock_after`."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-08-01", periods=days)
    rows = []
    for k, s in enumerate(symbols):
        ret = rng.normal(0.001, 0.02, days)
        close = 150 * np.exp(np.cumsum(ret))
        if shock_after is not None:
            close = np.where(dates > shock_after, close * 7.0, close)
        opn = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.005, days))
        high = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.01, days)))
        low = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.01, days)))
        vol = rng.integers(400_000, 1_600_000, days).astype(float)
        rows.append(pd.DataFrame({"symbol": s, "date": dates, "open": opn, "high": high, "low": low, "close": close, "volume": vol}))
    d = pd.concat(rows).sort_values(["symbol", "date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    d["prev_close"] = g.close.shift(1)
    d["hist_n"] = g.cumcount()
    tr = np.maximum(d.high - d.low, np.maximum((d.high - d.prev_close).abs(), (d.low - d.prev_close).abs())).fillna(d.high - d.low)
    d["atr14"] = tr.groupby(d.symbol).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False).mean())
    d["value20"] = (d.close * d.volume).groupby(d.symbol).transform(lambda s: s.rolling(20).mean())
    d["eligible"] = (d.hist_n >= 60) & (d.value20 >= 5e7) & (d.close >= 50)
    d["ema20"] = g.close.transform(lambda s: s.ewm(span=20, adjust=False).mean())
    d["ema50"] = g.close.transform(lambda s: s.ewm(span=50, adjust=False).mean())
    d["hi55"] = g.high.transform(lambda s: s.shift(1).rolling(55).max())
    rng10 = (g.high.transform(lambda s: s.shift(1).rolling(10).max()) - g.low.transform(lambda s: s.shift(1).rolling(10).min())) / d.prev_close
    d["range10_pct"] = rng10.groupby(d.symbol).transform(lambda s: s.expanding(min_periods=60).rank(pct=True))
    d["rs20"] = g.close.transform(lambda s: s / s.shift(20) - 1)
    d["rvol"] = d.volume / g.volume.transform(lambda s: s.shift(1).rolling(20).mean())
    d["close_pos"] = ((d.close - d.low) / (d.high - d.low)).where(d.high > d.low, 0.5)
    d["L5_1"] = g.close.shift(-1)          # a forward-looking outcome column, as in the real panel: must never be read
    return d


def all_signals(d):
    f = S.add_features(d)
    return pd.concat([S.e1(f), S.e2(f), S.e3(f)], ignore_index=True)


def test_signals_do_not_change_when_the_future_changes():
    cut = pd.Timestamp("2025-03-14")
    a = all_signals(synth())
    b = all_signals(synth(shock_after=cut))
    a, b = (x[pd.to_datetime(x.date) <= cut].sort_values("signal_id").reset_index(drop=True) for x in (a, b))
    assert len(a) > 0, "the synthetic panel must produce signals for the test to mean anything"
    pd.testing.assert_frame_equal(a, b)


def test_every_derived_feature_up_to_t_ignores_the_future():
    """Feature-level check (stronger than comparing emitted signals, which may be sparse for an arm)."""
    cut = pd.Timestamp("2025-03-14")
    base = synth()
    new_cols = [c for c in S.add_features(base).columns if c not in base.columns]
    a = S.add_features(base)
    b = S.add_features(synth(shock_after=cut))
    a, b = (x[x.date <= cut].sort_values(["symbol", "date"]).reset_index(drop=True)[new_cols] for x in (a, b))
    assert len(new_cols) >= 10
    pd.testing.assert_frame_equal(a, b)


def test_stop_clamp_keeps_risk_between_one_and_eight_percent():
    assert S.clamp_stop(80.0, 100.0) == pytest.approx(92.0) and S.clamp_stop(99.8, 100.0) == pytest.approx(99.0)
    assert S.clamp_stop(95.0, 100.0) == pytest.approx(95.0)


def test_reaction_session_mapping():
    sessions = [dt.date(2025, 1, 15), dt.date(2025, 1, 16), dt.date(2025, 1, 17), dt.date(2025, 1, 20)]
    at = lambda *a: dt.datetime(*a, tzinfo=IST)
    assert S.reaction_session(at(2025, 1, 15, 8, 50), sessions) == dt.date(2025, 1, 15)     # pre-open: same day
    assert S.reaction_session(at(2025, 1, 15, 9, 15), sessions) == dt.date(2025, 1, 16)     # at/after the open: next
    assert S.reaction_session(at(2025, 1, 15, 17, 30), sessions) == dt.date(2025, 1, 16)    # after the close: next
    assert S.reaction_session(at(2025, 1, 18, 11, 0), sessions) == dt.date(2025, 1, 20)     # Saturday: Monday
    assert S.reaction_session(at(2025, 1, 20, 18, 0), sessions) is None                     # beyond the calendar


def test_d1_triggers_on_the_reaction_session_only():
    d = S.add_features(synth())
    idx = pd.DataFrame({"date": sorted(d.date.unique())})
    idx["idx_close"] = 100.0
    day = lambda k: sorted(d.date.dt.date.unique())[k]
    b_day, r_day = day(100), day(101)
    sym = "A"
    # engineer a +6% reaction on 2x volume on r_day, and a +6% jump on the broadcast day itself (must NOT count)
    for dd in (b_day, r_day):
        m = (d.symbol == sym) & (d.date.dt.date == dd)
        d.loc[m, "close"] = d.loc[m, "prev_close"] * 1.06
        d.loc[m, "volume"] = d.loc[m, "vol20"] * 3
        d.loc[m, "eligible"] = True
    bc = pd.DataFrame({"symbol": [sym], "period_end": ["2024-12-31"],
                       "broadcast_at": [dt.datetime.combine(b_day, dt.time(16, 5), tzinfo=IST)]})
    sig, st = S.d1(d, idx, bc, RULE)
    assert list(sig.date) == [r_day] and st["triggered"] == 1 and st["gate_rejected"] == 0
    assert sig.iloc[0].available_at.startswith(str(b_day))


def test_snapshot_uses_only_bars_before_1515_and_rejects_sealed_rows(tmp_path):
    rows = ["symbol,instrument_token,ts,open,high,low,close,volume,source_version"]
    for hh, mm, px, vol in ((9, 15, 100, 10), (15, 5, 101, 10), (15, 10, 102, 10), (15, 15, 500, 999), (15, 25, 1, 999)):
        rows.append(f"A,1,2025-01-15T{hh:02d}:{mm:02d}:00+05:30,{px},{px},{px},{px},{vol},x")
    f = tmp_path / "part-1.csv.gz"
    with gzip.open(f, "wt") as fh:
        fh.write("\n".join(rows) + "\n")
    s = SN.snapshots({"A"}, pattern=str(tmp_path / "part-*.csv.gz"))
    r = s.iloc[0]
    assert (r.s_open, r.s_high, r.s_low, r.s_last, r.s_vol) == (100, 102, 100, 102, 30)
    bad = tmp_path / "sealed"
    bad.mkdir()
    with gzip.open(bad / "part-1.csv.gz", "wt") as fh:
        fh.write(rows[0] + "\nA,1,2024-07-31T10:00:00+05:30,1,1,1,1,1,x\n")
    with pytest.raises(AssertionError):
        SN.snapshots({"A"}, pattern=str(bad / "part-*.csv.gz"))


def test_random_control_is_seeded_excludes_the_arms_picks_and_matches_counts():
    d = S.add_features(synth())
    sessions = sorted(d.date.dt.date.unique())
    trades = pd.DataFrame({"entry_date": [sessions[120], sessions[120], sessions[150]], "symbol": ["A", "B", "C"],
                           "realised": [True, True, True], "exit_reason": ["TIME"] * 3})
    a = K.random_signals("E3", trades, d, sessions, 7)
    b = K.random_signals("E3", trades, d, sessions, 7)
    c = K.random_signals("E3", trades, d, sessions, 8)
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)
    day1 = a[a.date == sessions[119]]
    assert len(day1) == 2 and not set(day1.symbol) & {"A", "B"}             # signal day = the session before the fill
    assert (a.order_type == "MOO").all() and (a.stop < a.reference_price).all()


def test_decision_rule_needs_every_criterion_and_monitoring_is_selection_without_profit():
    good = {"net_return_pct": 5.0, "nw_daily": {"t": 3.0}, "mean_r": 0.4, "market": {"alpha_t": 2.6},
            "halves_net_inr": [100.0, 50.0], "trades_closed": 150}
    stress = {"net_return_pct": 1.0}
    assert R.verdict(good, stress, [0.1, 0.2, 0.3])["provisional_verdict"] == "VALIDATION_CANDIDATE"
    assert R.verdict(good, stress, [0.1, 0.5])["provisional_verdict"] == "CLOSED"            # a random run beat it
    weak = dict(good, net_return_pct=-1.0)
    assert R.verdict(weak, {"net_return_pct": -2.0}, [0.1])["provisional_verdict"] == "MONITORING_ONLY"
    few = dict(good, trades_closed=99)
    assert R.verdict(few, stress, [0.1])["provisional_verdict"] == "CLOSED"


def test_close_entry_features_use_only_prior_sessions_and_the_1515_snapshot():
    d = synth()
    idx = pd.DataFrame({"date": sorted(d.date.unique())})
    idx["idx_close"] = np.linspace(100, 120, len(idx))
    snap = d[["symbol", "date"]].assign(s_open=d.open, s_high=d.high * 0.999, s_low=d.low * 1.001, s_last=d.close * 0.998,
                                        s_vol=d.volume * 0.8)
    t0 = sorted(d.date.unique())[150]
    a = SN.snapshot_features(d, snap, idx)
    bad = d.copy()
    m = bad.date == t0                      # corrupt every FULL-DAY value of t0 that is not known at 15:15
    for c in ("open", "high", "low", "close", "volume", "ema20", "ema50", "atr14", "rs20", "value20", "rvol", "close_pos"):
        bad.loc[m, c] = 1e9
    bad.loc[m, "eligible"] = False
    b = SN.snapshot_features(bad, snap, idx)
    cols = ["last", "ema20_s", "ema50_s", "atr_s", "close_pos_s", "rvol_s", "rs20_s", "elig_s", "low5_s", "hi54_prev",
            "hi14_prev", "down4_prev", "low4_prev", "vol4_prev", "vol20", "prev_close", "prev_close2"]
    pick = lambda x: x[x.date == t0].sort_values("symbol")[cols].reset_index(drop=True)
    assert len(pick(a)) == 5
    pd.testing.assert_frame_equal(pick(a), pick(b))
