"""Paper Trade Simulation Engine v1 — unit tests (test_reports/paper_trades_engine_20260918_1338.md, TC-P1..TC-P14).

Synthetic panels only: every expected number is computed by hand in the test, never read back from the engine.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nidp.services.tpd_model.paper import bench, evaluate, sim, sources, store
from nidp.services.tpd_model.paper.engine import PredictionSet, lifecycle, load_rules, rank_universe, simulate
from nidp.services.tpd_model.paper.market import build_market, wilder_atr

IST = timezone(timedelta(hours=5, minutes=30))
RULES = load_rules()
EMPTY_CA = pd.DataFrame(columns=["symbol", "series", "action_type", "action_subtype", "purpose", "ratio", "face_value_pre", "face_value_post",
                                 "dividend_amount", "record_date", "ex_date", "bc_start_date", "bc_end_date", "announcement_date", "source"])


def sessions(n: int, start: str = "2025-01-01") -> list[pd.Timestamp]:
    return list(pd.bdate_range(start, periods=n))


def bars(symbol: str, dates, closes, *, spread=0.01, turnover=5e7, opens=None, highs=None, lows=None) -> list[dict]:
    rows, prev = [], None
    for k, (d, c) in enumerate(zip(dates, closes)):
        o = opens[k] if opens is not None else c
        h = highs[k] if highs is not None else max(o, c) * (1 + spread)
        l = lows[k] if lows is not None else min(o, c) * (1 - spread)
        rows.append({"symbol": symbol, "as_of_date": d, "series": "EQ", "source": "NSE_BHAVCOPY", "open": o, "high": h, "low": l, "close": c,
                     "prev_close": prev if prev is not None else c, "volume": 1000, "turnover": turnover, "deliverable_pct": 50.0})
        prev = c
    return rows


def pset(D, nxt, probs: dict, sample="forward", counts=True) -> PredictionSet:
    wide = pd.DataFrame(probs).T
    wide.columns = ["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"]
    return PredictionSet(sample=sample, prediction_date=D.date(), next_session=nxt.date(), prediction_timestamp=datetime(2026, 9, 18, 21, tzinfo=IST),
                         data_cutoff=datetime.combine(D.date(), datetime.min.time(), tzinfo=IST), model_version="v4@test", feature_version="v4-84in",
                         snapshot_sha256="x" * 64, wide=wide, counts=counts)


NAMES = pd.DataFrame({"symbol": list("ABCDEFGH"), "isin": [f"INE{k}" for k in range(8)], "company_name": list("ABCDEFGH"),
                      "sector": ["S1", "S1", "S1", "S2", "S2", "S2", "S1", "S2"], "industry": ["i"] * 8})


# ── TC-P8: ATR14, support, 8% cap, method, R/R ─────────────────────────────────────────────────────────────────────────
def test_wilder_atr_reference():
    tr = np.array([2.0] * 14 + [16.0, 2.0])
    atr = wilder_atr(tr)
    assert np.isnan(atr[:14]).all()                       # min 15 bars
    assert atr[14] == pytest.approx((2.0 * 13 + 16.0) / 14)   # the 14-bar mean (2.0) smoothed with the 15th TR
    assert atr[15] == pytest.approx((atr[14] * 13 + 2.0) / 14)


def test_levels_rules():
    e = np.array([500.0, 500.0, 500.0, 500.0])
    atr = np.array([12.0, 12.0, 12.0, 40.0])
    sup = np.array([490.0, 470.0, 400.0, np.nan])
    lv = sim.levels(e, atr, sup, sup, 1.5, 5.0)
    assert lv["stop_loss_price"].tolist() == pytest.approx([482.0, 470.0, 460.0, 460.0])
    assert lv["stop_method"].tolist() == ["ATR", "SUPPORT", "CAP_8PCT", "CAP_8PCT"]
    assert lv["target_price"].tolist() == pytest.approx([525.0] * 4)
    assert lv["risk_reward_ratio"].iloc[0] == pytest.approx(0.05 / 0.036)
    assert lv["target_2_price"].iloc[0] == pytest.approx(550.0)


# ── TC-P4: entry at the official open and every exception ─────────────────────────────────────────────────────────────
def _inputs(o, h, l, c, prev, turnover=None, thin=False, mult=None, prev_mult=None):
    n = len(o)
    full = lambda v: np.column_stack([np.array(v, dtype=float)] + [np.full(n, np.nan)] * 5)
    return sim.SessionInputs(open=full(o), high=full(h), low=full(l), close=full(c), volume=full([1] * n),
                             mult=np.ones((n, 6)) if mult is None else mult, turnover_s1=np.array(turnover or [1e9] * n, dtype=float),
                             prev_close_raw=np.array(prev, dtype=float), prev_mult=np.ones(n) if prev_mult is None else prev_mult,
                             sessions_present=1, s1_thin=thin, suspect=np.zeros((n, 6), bool), unfactored=np.zeros((n, 6), bool))


def test_entry_exceptions():
    nan = np.nan
    x = _inputs(o=[101, nan, 0.0, 105.0, 95.0, 106.0, 101],
                h=[103, nan, 1.0, 105.0, 97.0, 108.0, 103],
                l=[100, nan, 0.0, 104.0, 95.0, 105.0, 100],
                c=[102, nan, 1.0, 105.0, 96.0, 107.0, 102],
                prev=[100] * 7, turnover=[1e9, 1e9, 1e9, 1e9, 1e9, 1e9, 1e6])
    e = sim.resolve_entries(x, 20000)
    assert e["status"].tolist() == ["ENTERED", "SUSPENDED", "ENTRY_UNAVAILABLE", "ENTRY_UNAVAILABLE", "ENTERED", "ENTERED", "ENTERED"]
    assert e["reason"].tolist()[1:4] == ["NO_BAR", "MISSING_OPEN", "UPPER_CIRCUIT_OPEN"]
    assert e["entry_price"].iloc[0] == 101
    assert "LOWER_CIRCUIT_OPEN" in e["flags"].iloc[4] and "GAP_RECORDED" in e["flags"].iloc[4]
    assert e["flags"].iloc[5] == ["GAP_RECORDED"]                 # 6% gap, open below high: entered and flagged, never rejected
    assert e["flags"].iloc[6] == ["ILLIQUID_OPEN"]                # 20,000 > 1% of a 10-lakh session
    thin = sim.resolve_entries(_inputs(o=[nan], h=[nan], l=[nan], c=[nan], prev=[100], thin=True), 20000)
    assert thin["status"].iloc[0] == "DATA_ERROR"


def test_entry_gap_uses_adjusted_prev_close():
    """A 1:1 bonus ex-dated on the entry day: the prediction-day close (200) is 100 on the entry basis, so no gap."""
    x = _inputs(o=[100.0], h=[102.0], l=[99.0], c=[101.0], prev=[200.0], mult=np.ones((1, 6)), prev_mult=np.array([0.5]))
    e = sim.resolve_entries(x, 20000)
    assert e["gap"].iloc[0] == pytest.approx(0.0)
    assert "CA_EX_ON_ENTRY" in e["flags"].iloc[0]


# ── TC-P5 / TC-P6: path on the entry basis, running statistics ────────────────────────────────────────────────────────
def test_path_continuous_across_bonus_and_running_stats():
    c = np.array([[101, 102, 51, 52, 50, 53]], dtype=float)
    mult = np.array([[0.5, 0.5, 1, 1, 1, 1]])
    x = sim.SessionInputs(open=c.copy(), high=c * 1.01, low=c * 0.99, close=c, volume=np.ones_like(c), mult=mult, turnover_s1=np.array([1e9]),
                          prev_close_raw=np.array([100.0]), prev_mult=np.array([0.5]), sessions_present=6, s1_thin=False,
                          suspect=np.zeros((1, 6), bool), unfactored=np.zeros((1, 6), bool))
    r = sim.path_returns(x, np.array([100.0]))
    assert r["r_close"][0].tolist() == pytest.approx([0.01, 0.02, 0.02, 0.04, 0.0, 0.06])
    run = sim.running(r)
    assert run["mfe"][0].tolist() == pytest.approx(np.maximum.accumulate(r["r_high"][0]).tolist())
    assert run["mae"][0].tolist() == pytest.approx(np.minimum.accumulate(r["r_low"][0]).tolist())
    assert run["high_watermark"][0].tolist() == pytest.approx([0.01, 0.02, 0.02, 0.04, 0.04, 0.06])
    assert run["max_drawdown"][0][4] == pytest.approx(0.04)


# ── TC-P7: exit modes ────────────────────────────────────────────────────────────────────────────────────────────────
def test_exit_modes():
    T, S = 0.05, -0.036
    rc = np.array([[0.01, 0.02, 0.03, 0.04, 0.05, 0.06]] * 5)
    ro = np.zeros((5, 6))
    rh = np.full((5, 6), 0.02)
    rl = np.full((5, 6), -0.01)
    rh[0, 2] = 0.05                                    # row 0: target touched in s3
    rh[1, 1], rl[1, 1] = 0.06, -0.04                   # row 1: both in s2 -> stop counts
    ro[2, 2], rh[2, 2] = 0.07, 0.08                    # row 2: s3 opens above the target -> exit at that open
    ro[3, 1], rl[3, 1] = -0.05, -0.06                  # row 3: s2 opens below the stop -> exit at that open
    r = {"r_open": ro, "r_high": rh, "r_low": rl, "r_close": rc}  # row 4: nothing -> close of s6
    ex = sim.exits(r, np.full(5, T), np.full(5, S), 6)
    assert ex["EOD-1"]["gross_return"].tolist() == pytest.approx([0.01] * 5)
    assert ex["EOD-3"]["gross_return"].tolist() == pytest.approx([0.03] * 5)
    assert ex["EOD-5"]["gross_return"].tolist() == pytest.approx([0.05] * 5)
    assert ex["FIXED"]["gross_return"].tolist() == pytest.approx([0.06] * 5)
    ts = ex["TARGET_STOP"]
    assert ts["exit_reason"].tolist() == ["target", "stop", "target (gap)", "stop (gap)", "horizon close"]
    assert ts["gross_return"].tolist() == pytest.approx([0.05, S, 0.07, -0.05, 0.06])
    assert ts["exit_session_index"].tolist() == [3, 2, 3, 2, 6]
    assert ts["target_hit"].tolist() == [True, False, True, False, False]
    partial = sim.exits(r, np.full(5, T), np.full(5, S), 2)
    assert partial["EOD-3"]["state"].tolist() == ["OPEN"] * 5 and partial["EOD-1"]["state"].tolist() == ["CLOSED"] * 5
    assert partial["TARGET_STOP"]["state"].tolist() == ["OPEN", "CLOSED", "OPEN", "CLOSED", "OPEN"]


def test_costs_separate_from_gross():
    g = np.array([0.02, -0.01])
    assert sim.net(g, 0.25).tolist() == pytest.approx([0.0175, -0.0125])
    assert sim.net(g, 1.00).tolist() == pytest.approx([0.01, -0.02])


# ── TC-P1 / TC-P13: eligibility, ranking, no information after the prediction date ──────────────────────────────────────
def _market(mutate_after=None, ca=EMPTY_CA):
    d = sessions(40)
    closes = {s: [100 + 0.5 * k for k in range(40)] for s in "AFGH"}
    rows = []
    for s in "AFGH":
        rows += bars(s, d, closes[s])
    rows += bars("B", d, [4.0 + 0.01 * k for k in range(40)])                 # below the price floor
    rows += bars("C", d, [50.0] * 40, turnover=5e5)                           # below 1 crore traded value
    rows += bars("D", d[:30], [60.0] * 30)                                    # no bar after session 30
    cz = [80.0] * 40
    cz[28] = 200.0                                                            # unexplained 2.5x jump inside the 20-session window
    rows += bars("E", d, cz, opens=cz)
    p = pd.DataFrame(rows)
    if mutate_after is not None:
        mask = p["as_of_date"] > d[34]
        p.loc[mask, ["open", "high", "low", "close"]] *= mutate_after
    return build_market(p, ca), d


def test_eligibility_filters_and_tie_break():
    m, d = _market()
    D, nxt = d[34], d[35]
    probs = {"A": [0.3, 0.1, 0.05, 0.01], "B": [0.9, 0.1, 0.2, 0.0], "C": [0.8, 0.1, 0.2, 0.0], "D": [0.7, 0.1, 0.2, 0.0],
             "E": [0.6, 0.1, 0.2, 0.0], "F": [0.3, 0.2, 0.05, 0.02], "G": [0.3, 0.1, 0.05, 0.01], "H": [0.1, 0.1, 0.01, 0.01]}
    u = rank_universe(pset(D, nxt, probs), m, "P5-NEXT", RULES, NAMES).set_index("symbol")
    assert u.loc["B", "exclusion_reason"] == "min_price"
    assert u.loc["C", "exclusion_reason"] == "min_traded_value"
    assert u.loc["D", "exclusion_reason"] == "valid_ohlc"                   # stale: no bar on the prediction date
    assert u.loc["E", "exclusion_reason"] == "ca_validated"
    assert u.loc[list("BCDE"), "rank"].isna().all()
    assert u.loc[list("AFGH"), "rank"].tolist() == [1, 2, 3, 4]              # ties at 0.30 broken by symbol A < F < G
    assert (u.loc[list("AFGH"), "selection_status"] == "SELECTED").all()     # fewer than five eligible: all selected
    u2 = rank_universe(pset(D, nxt, probs), m, "P5-NEXT", RULES, NAMES)
    pd.testing.assert_frame_equal(u.reset_index()[["symbol", "rank", "selection_status"]], u2[["symbol", "rank", "selection_status"]])


def test_no_future_information_in_snapshot_or_levels():
    m1, d = _market()
    m2, _ = _market(mutate_after=1.37)                                         # every bar after the prediction date changes
    ca_after = EMPTY_CA.copy()
    ca_after.loc[0] = ["A", "EQ", "BONUS", None, "Bonus 1:1", "1:1", None, None, None, d[37].date(), d[37].date(), None, None, None, "NSE"]
    m3, _ = _market(ca=ca_after)                                               # a bonus ex-dated after the prediction date
    D, nxt = d[34], d[35]
    probs = {s: [0.3 - 0.01 * k, 0.1, 0.05, 0.01] for k, s in enumerate("AFGH")}
    base = rank_universe(pset(D, nxt, probs), m1, "P5-NEXT", RULES, NAMES)
    for m in (m2, m3):
        u = rank_universe(pset(D, nxt, probs), m, "P5-NEXT", RULES, NAMES)
        pd.testing.assert_frame_equal(base[["symbol", "rank", "selection_status", "exclusion_reason"]], u[["symbol", "rank", "selection_status", "exclusion_reason"]])
        t0 = m.t(D)
        for s in "AFGH":
            i1, i = m1.i(s), m.i(s)
            assert m.atr_adj[t0, i] / m.mult[t0, i] == pytest.approx(m1.atr_adj[t0, i1] / m1.mult[t0, i1])
            assert m.support_adj[t0, i] / m.mult[t0, i] == pytest.approx(m1.support_adj[t0, i1] / m1.mult[t0, i1])


def test_simulate_end_to_end_and_lifecycle():
    m, d = _market()
    D, nxt = d[30], d[31]
    probs = {s: [0.3 - 0.01 * k, 0.1, 0.05, 0.01] for k, s in enumerate("AFGH")}
    u = rank_universe(pset(D, nxt, probs), m, "P5-NEXT", RULES, NAMES)
    out, arr = simulate(pset(D, nxt, probs), m, u, RULES)
    a = out.set_index("symbol").loc["A"]
    t1 = m.t(nxt)
    assert a["entry_price"] == pytest.approx(m.open[t1, m.i("A")])             # the official open of the next session
    assert a["sessions_observed"] == 6
    assert a["EOD-1|gross_return"] == pytest.approx(m.close[t1, m.i("A")] / m.open[t1, m.i("A")] - 1)
    assert lifecycle(a, 6) == "EVALUATED" and lifecycle(a, 1) == "ENTERED" and lifecycle(a, 3) == "MONITORING"


# ── TC-P10: benchmarks ─────────────────────────────────────────────────────────────────────────────────────────────
def _universe(n=12):
    rng = np.random.default_rng(1)
    u = pd.DataFrame({"symbol": [f"S{k:02d}" for k in range(n)], "rank": np.arange(1, n + 1), "p_head": np.linspace(0.4, 0.05, n),
                      "p_opposite": np.linspace(0.01, 0.5, n), "sector": ["X"] * 6 + ["Y"] * 6, "size_group": ["L", "M", "S"] * (n // 3),
                      "status": ["ENTERED"] * n, "atr_14": rng.uniform(1, 5, n)})
    u["selection_status"] = np.where(u["rank"] <= 5, "SELECTED", "NOT_SELECTED")
    u["eligibility"] = [{"close": 100.0 + k, "med_turnover_20": 1e8 * (k + 1)} for k in range(n)]
    for mode in sim.MODES:
        u[f"{mode}|state"] = "CLOSED"
        u[f"{mode}|gross_return"] = np.linspace(-0.02, 0.03, n)
        u[f"{mode}|target_hit"] = [k % 2 == 0 for k in range(n)]
    return u


def test_benchmarks_deterministic_and_rule_conformant():
    u = _universe()
    a1 = bench.members_a_random5(u, "P5-NEXT", "2026-09-21")
    assert a1 == bench.members_a_random5(u, "P5-NEXT", "2026-09-21") and len(a1) == 5
    pairs = bench.members_b_matched(u, "P5-NEXT", "2026-09-21")
    assert pairs == bench.members_b_matched(u, "P5-NEXT", "2026-09-21")
    matched = [p for _, p in pairs]
    assert len(set(matched)) == len(matched)                                    # never reused
    selected = set(u.loc[u["selection_status"] == "SELECTED", "symbol"])
    assert not set(matched) & selected                                          # never one of the model's own picks
    sec = u.set_index("symbol")["sector"]
    for s, p in pairs:
        pool = u[(u["selection_status"] == "NOT_SELECTED") & (u["sector"] == sec[s])]
        if len(pool) >= 3:
            assert sec[p] == sec[s]
    c = bench.members_c_movement(u)
    mv = (u["p_head"] + u["p_opposite"]).to_numpy()
    assert set(c) == set(u.loc[np.argsort(-mv, kind="mergesort")[:5], "symbol"])
    s = bench.summarise(u, list(selected), "EOD-1", 0.25, 1)
    g = u.loc[u["symbol"].isin(selected), "EOD-1|gross_return"]
    assert s["net_mean"] == pytest.approx(g.mean() - 0.0025) and s["state"] == "CLOSED"
    assert bench.summarise(u, list(selected), "EOD-3", 0.25, 2)["state"] == "OPEN"


def test_index_benchmark():
    idx = pd.DataFrame({"open_price": [100.0, 101.0], "close_price": [102.0, 99.0], "source": ["NSE_IND_CLOSE", "YAHOO_NSEI"]},
                       index=pd.to_datetime(["2026-09-21", "2026-09-22"]))
    sess = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
    assert bench.index_return(idx, sess, "EOD-1")["gross"] == pytest.approx(0.02)
    assert bench.index_return(idx, sess, "EOD-3") is None                      # s3 bar missing: not guessed


# ── TC-P11: statistics ─────────────────────────────────────────────────────────────────────────────────────────────
def test_newey_west_reference():
    x = np.array([0.01, -0.02, 0.03, 0.0, 0.02])
    assert evaluate.newey_west_se(x, 0) == pytest.approx(np.std(x, ddof=1) / np.sqrt(5))
    d = x - x.mean()
    g0, g1 = (d @ d) / 5, (d[1:] @ d[:-1]) / 5
    assert evaluate.newey_west_se(x, 1) == pytest.approx(np.sqrt((g0 + 2 * 0.5 * g1) / 5))


def test_daily_portfolio_overlapping_cohorts():
    def res(entry, sessions_, rc):
        u = pd.DataFrame({"symbol": ["A"], "selection_status": ["SELECTED"], "status": ["ENTERED"], "EOD-3|state": ["CLOSED"],
                          "EOD-3|exit_session_index": [3], "EOD-3|gross_return": [rc[2]]})
        arr = {"r_close": np.array([rc + [np.nan] * (6 - len(rc))])}
        return evaluate.SessionResult(entry, entry, sessions_, u, arr, True)
    d = [date(2026, 9, 21) + timedelta(days=k) for k in range(4)]
    r1 = res(d[0], d[0:3], [0.01, 0.02, 0.03])
    r2 = res(d[1], d[1:4], [-0.01, 0.0, 0.02])
    p = evaluate.daily_portfolio([r1, r2], "EOD-3", 0.25, 100000, 5).set_index("session")
    per = 20000
    assert p.loc[d[0], "pnl"] == pytest.approx(0.01 * per)
    assert p.loc[d[1], "pnl"] == pytest.approx(0.01 * per - 0.01 * per)
    assert p.loc[d[2], "pnl"] == pytest.approx(0.01 * per - 0.0025 * per + 0.01 * per)
    assert p.loc[d[3], "pnl"] == pytest.approx(0.02 * per - 0.0025 * per)
    assert p["ret"].iloc[0] == pytest.approx(0.01 * per / (100000 * 3))        # capital split into h = 3 tranches


def test_buckets_and_calibration_error():
    u = _universe()
    u["model_label_hit"] = [True, False, True, False, False, False, True, False, False, False, False, False]
    u["EOD-1|mae"] = -0.01
    r = evaluate.SessionResult(date(2026, 9, 18), date(2026, 9, 21), [date(2026, 9, 21)], u, {}, True)
    b = evaluate.bucket_table([r], [0.0, 0.1, 0.2, 0.3, 0.4, 1.0], 0.25, False)
    top = next(x for x in b if x["lo"] == 0.3)
    sel = u[(u["p_head"] >= 0.3) & (u["p_head"] < 0.4)]
    assert top["n"] == len(sel)
    assert top["calibration_error"] == pytest.approx(sel["model_label_hit"].mean() - sel["p_head"].mean())


# ── TC-P12: forward counting rule, samples never pooled ────────────────────────────────────────────────────────────────
def _freeze(root: Path, target: str, gen: str, rehearsal=False) -> Path:
    snap = root / target
    snap.mkdir(parents=True)
    rows = [f"{s},{h},0.1,0.1,0.1,0.1" for s in ("AAA", "BBB") for h in ("p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d")]
    csv = ("symbol,head,p_tpd3,p_atr_only,p_own_history_only,p_base_rate\n" + "\n".join(rows) + "\n").encode()
    (snap / "tpd3_predictions.csv").write_bytes(csv)
    man = {"data_as_of": "2026-09-18", "target_session": target, "generated_at": gen, "git_sha": "abcdef0123", "model": "v4",
           "counts_toward_verdict": True, "rehearsal": rehearsal, "preview": False, "sha256": hashlib.sha256(csv).hexdigest(), "files": {}}
    mb = json.dumps(man).encode()
    (snap / "manifest.json").write_bytes(mb)
    (snap / "manifest.sha256").write_text(hashlib.sha256(mb).hexdigest())
    return snap


def test_forward_counting_rule(tmp_path):
    reg = datetime(2026, 9, 18, 13, 37, 49, tzinfo=IST)
    _freeze(tmp_path, "2026-09-18", "2026-09-17T20:50:00+05:30")
    _freeze(tmp_path, "2026-09-21", "2026-09-18T20:50:00+05:30")
    _freeze(tmp_path, "2026-09-22", "2026-09-19T20:50:00+05:30", rehearsal=True)
    sets, refused = sources.forward_sets(tmp_path, reg)
    assert [(str(s.next_session), s.counts) for s in sets] == [("2026-09-18", False), ("2026-09-21", True)]
    assert refused and "rehearsal" in refused[0]["reason"]


def test_evaluation_uses_counted_sessions_only():
    u = _universe()
    u["model_label_hit"] = True
    u["reason"] = None
    u["flags"] = [[] for _ in range(len(u))]
    for mode in sim.MODES:
        u[f"{mode}|exit_session_index"] = sim.MODE_SESSION[mode]
        u[f"{mode}|mfe"] = 0.01
        u[f"{mode}|mae"] = -0.01
        u[f"{mode}|exit_reason"] = "close"
    arr = {"r_close": np.tile(np.linspace(0.0, 0.03, 6), (len(u), 1))}
    sess = [date(2026, 9, 21) + timedelta(days=k) for k in range(6)]
    counted = evaluate.SessionResult(date(2026, 9, 18), date(2026, 9, 21), sess, u, arr, True)
    early = evaluate.SessionResult(date(2026, 9, 16), date(2026, 9, 17), sess, u.assign(**{"EOD-1|gross_return": 9.0}), arr, False)
    out = evaluate.evaluate([early, counted], pd.DataFrame(columns=["benchmark", "mode", "state", "entry_session", "net_mean", "n",
                                                                    "target_hit_rate", "positive_rate"]),
                            RULES, "forward", "P5-NEXT", all_recorded=2)
    head = next(m for m in out["modes"] if m["mode"] == "EOD-1")
    assert out["sessions"]["counted"] == 1 and out["sessions"]["not_counted"] == ["2026-09-17"]
    assert head["gross_mean"] == pytest.approx(u.loc[u["selection_status"] == "SELECTED", "EOD-1|gross_return"].mean())   # the 9.0 never enters
    assert out["statement"]["established"] is False and "Not established" in out["statement"]["text"]
    none = evaluate.evaluate([early], pd.DataFrame(columns=["benchmark", "mode", "state", "entry_session", "net_mean", "n", "target_hit_rate",
                                                            "positive_rate"]), RULES, "forward", "P5-NEXT", all_recorded=1)
    assert none["sessions"]["counted"] == 0 and none["sessions"]["first_counted"] is None     # JSON null, not the text "None"


# ── TC-P2 / TC-P14 (structure): SQL guards and COPY formatting ────────────────────────────────────────────────────────
def test_copy_cells_and_guards():
    assert store._cell(None) == "" and store._cell(float("nan")) == "" and store._cell(True) == "true"
    assert store._cell([1.5, None, float("nan")]) == "{1.5,NULL,NULL}"
    assert store._cell({"a": 1}) == '{"a":1}'
    assert store._cell(np.float64(150.96618357)) == "150.96618357"          # numpy 2 reprs this as np.float64(...)
    assert store._cell(np.int64(3)) == "3" and store._cell(np.bool_(True)) == "true"
    assert store._cell(pd.NA) == "" and store._cell(np.float64("nan")) == ""
    assert store._cell([np.float64(0.5), np.float64("nan")]) == "{0.5,NULL}"
    sql = store.run_sql(store.rules_sql("paper-v1", "h", "g", "2026-09-18T13:37:49+05:30", {"x": 1}), [], [], [], [], [], [], [], [], [])
    assert "immutable snapshot differs" in sql and "refusing to overwrite" in sql and "registered with a different hash" in sql
    assert sql.startswith("BEGIN;") and sql.rstrip().endswith("COMMIT;")


# ── TC-P3: the entry session is the snapshot's own next session on the exchange calendar ─────────────────────────────
def test_entry_session_follows_calendar_not_weekday_arithmetic():
    from nidp.services.tpd_model.paper.__main__ import build
    from nidp.services.tpd_model.paper.engine import session_inputs
    d = [x for x in sessions(41) if x != pd.Timestamp("2025-02-19")]          # a Wednesday holiday: no session that day
    rows = []
    for s in "AFGH":
        rows += bars(s, d, [100 + 0.5 * k for k in range(len(d))])
    m = build_market(pd.DataFrame(rows), EMPTY_CA)
    D = pd.Timestamp("2025-02-18")
    probs = {s: [0.3 - 0.01 * k, 0.1, 0.05, 0.01] for k, s in enumerate("AFGH")}
    ps = pset(D, pd.Timestamp("2025-02-20"), probs)
    _, sess = session_inputs(m, ["A"], ps)
    assert sess[0] == pd.Timestamp("2025-02-20") and pd.Timestamp("2025-02-19") not in sess
    idx = pd.DataFrame(columns=["open_price", "close_price", "source"])
    reg = datetime(2026, 9, 18, 13, 37, 49, tzinfo=IST)
    with pytest.raises(SystemExit, match="not the panel's next session"):
        build([pset(D, pd.Timestamp("2025-02-19"), probs)], m, RULES, NAMES, idx, reg)   # weekday arithmetic would say the 19th
