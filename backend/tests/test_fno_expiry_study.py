"""Stage B2 expiry-study tests (see test_reports/fno_expiry_study_TESTCASES.md): synthetic data only."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.fno_backtest import expiry_study as es


def _days(n, start="2025-10-01"):
    d, out = date.fromisoformat(start), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _row(day, sym, exp, c, pc, oi, coi, vol):
    return {"day": day, "sym": sym, "exp": exp, "c": c, "pc": pc, "oi": oi, "coi": coi, "vol": vol}


def test_tc1_weekdays_to_expiry():
    assert es.weekdays_to("2025-10-23", "2025-10-28") == 3          # Fri 24, Mon 27, Tue 28
    assert es.weekdays_to("2025-10-28", "2025-10-28") == 0
    assert es.weekdays_to("2025-10-29", "2025-10-28") == 0
    assert es.weekdays_to("2025-10-01", "2025-10-28") == 19


def test_tc2_bucket_uses_own_contract_numbers_and_never_sums():
    days = _days(25)
    rows = []
    for k, d in enumerate(days):
        rows.append(_row(d, "AAA", "2025-12-30", 100 + k, 100 + k - 1, 1000, 100, 10))     # near: oi change 100/900
        rows.append(_row(d, "AAA", "2026-01-27", 200, 199, 5000, -500, 40))                 # next: -500/5500
        rows.append(_row(d, "AAA", "2026-02-24", 300, 301, 2000, 0, 5))                     # far: no change
    b = es.build_buckets(rows, days)["AAA"]
    near, nxt, far = b[days[-1]]
    assert near["o"] == pytest.approx(100 / 900 * 100) and nxt["o"] == pytest.approx(-500 / 5500 * 100)
    assert far["o"] == 0 and far["p"] < 0
    assert near["rvol"] == pytest.approx(1.0) and nxt["rvol"] == pytest.approx(1.0)
    assert b[days[5]][0]["rvol"] is None                       # fewer than 20 prior sessions: no ratio
    assert near["liquid"] is False and nxt["liquid"] is True   # biggest OI is the next contract


def test_tc3_category_neutral_and_floors():
    e = {"p": 1.0, "o": 5.0, "rvol": 2.0}
    assert es.category(e, (0.5, 3.0, None)) == "long_buildup"
    assert es.category({"p": -1.0, "o": -5.0, "rvol": None}, (0.5, 3.0, None)) == "long_unwinding"
    assert es.category({"p": 0.0, "o": 5.0, "rvol": 2.0}, es.NO_THRESHOLD) is None
    assert es.category({"p": 1.0, "o": 2.0, "rvol": 2.0}, (0.5, 3.0, None)) is None
    assert es.category({"p": 1.0, "o": 5.0, "rvol": None}, (0.5, 3.0, 1.5)) is None
    assert es.category(None, es.NO_THRESHOLD) is None


def test_tc4_configuration_signals():
    cats = {("A", 3): ("long_buildup", "long_buildup", "long_buildup"), ("B", 3): ("long_buildup", None, None), ("C", 3): ("long_buildup", "short_buildup", None),
            ("D", 3): (None, "long_buildup", "short_buildup"), ("E", 3): ("long_buildup", "long_buildup", None)}
    f = lambda cfg, cat="long_buildup": sorted(s[1] for s in es.config_signals(cfg, cat, cats))      # noqa: E731
    assert f("near_only") == ["A", "B", "C", "E"] and f("next_only") == ["A", "D", "E"] and f("far_only") == ["A"]
    assert f("near_next_agree") == ["A", "E"] and f("all_agree") == ["A"]
    assert f("disagree_follow_near") == ["C"] and f("disagree_follow_next", "short_buildup") == ["C"]
    assert f("disagree_follow_next") == [] and [s[2] for s in es.config_signals("disagree_follow_near", "long_buildup", cats)] == [1]


def _outcomes(n=260, syms=12):
    days = _days(n)
    adj = {}
    for k in range(syms):
        adj[f"S{k}"] = [{"day": d, "o": 100.0 + i * 0.1 * (1 if k else 2), "c": 100.0 + i * 0.1 * (1 if k else 2)} for i, d in enumerate(days)]
    return days, es.Outcomes(days, adj, {f"S{k}": "X" for k in range(syms)})


def test_tc5_benchmark_relative_and_window_purge():
    days, out = _outcomes()
    bounds = es.window_bounds(days)
    assert bounds["U"][0] == 0 and bounds["test"][1] == len(days) and bounds["D"][0] == days.index("2025-12-29")
    assert out.rel("S1", 10, 5) is not None and out.rel("S0", 10, 5) > out.rel("S1", 10, 5)          # S0 climbs faster than the pack
    end_u = bounds["U"][1] - 1
    res = es.evaluate([(end_u, "S0", 1)], out, bounds, 5)                                               # forward window leaves U
    assert res["U"]["n_signals"] == 0 and res["pooled"]["n_signals"] == 0
    res = es.evaluate([(end_u - 5, "S0", 1)], out, bounds, 5)
    assert res["U"]["n_signals"] == 1 and res["D"]["n_signals"] == 0


def test_tc6_direction_and_cost_applied():
    days, out = _outcomes()
    b = es.window_bounds(days)
    long_ = es.evaluate([(i, "S0", 1) for i in range(5, 40)], out, b, 5)["U"]
    short = es.evaluate([(i, "S0", -1) for i in range(5, 40)], out, b, 5)["U"]
    raw = out.rel("S0", 20, 5)
    assert long_["mean"] > 0 > short["mean"]
    assert long_["mean"] + short["mean"] == pytest.approx(-2 * es.COST_BASE, abs=1e-3)
    assert raw > es.COST_BASE


def test_tc7_verdict_rules():
    def s(mean, t, n):
        return {"pooled": {"mean": mean, "t": t, "n_sessions": n}}
    labels = list("abcde")
    good = {k: s(0.4, 2.0, 40) for k in labels}
    assert es.verdict(good, labels, 0.01, True)["verdict"] == "supported"
    assert es.verdict(good, labels, 0.2, True)["verdict"] == "inconclusive"                  # permutation gate (near_only)
    assert es.verdict(good, labels, None, False)["verdict"] == "supported"
    assert es.verdict({k: s(-0.2, -1.0, 40) for k in labels}, labels, 0.9, True)["verdict"] == "not_supported"
    thin = {k: s(0.4, 2.0, 10) for k in labels}
    assert es.verdict(thin, labels, 0.01, False)["verdict"] == "inconclusive"                # fewer than 30 pooled sessions
    mixed = {**good, "c": s(-0.1, -0.5, 40), "d": s(-0.1, -0.5, 40), "e": s(-0.1, -0.5, 40)}
    assert es.verdict(mixed, labels, None, False)["verdict"] == "inconclusive"


def _world(seed=0):
    import random
    rng = random.Random(seed)
    days = _days(120)
    rows, adj = [], {}
    for k in range(25):
        sym = f"S{k}"
        px, oi = 100.0, 100000.0
        adj[sym] = []
        for i, d in enumerate(days):
            o = px
            px *= 1 + rng.gauss(0, 0.01)
            coi = rng.gauss(0, 4000)
            oi = max(1000.0, oi + coi)
            adj[sym].append({"day": d, "o": o, "c": px})
            for exp, scale in (("2026-01-27", 1.0), ("2026-02-24", 0.4), ("2026-03-31", 0.2)):
                rows.append(_row(d, sym, exp, px * (1 + 0.001), o, oi * scale, coi * scale, 1000 + rng.random() * 500))
    return {"stf": rows, "adjusted": adj, "industry": {f"S{k}": f"I{k % 3}" for k in range(25)}}


FROZEN = {c: [(0.5, 2.0, None), (1.0, 3.0, None), (0.75, 1.0, 1.0), (0.2, 5.0, None), (0.3, 2.0, 1.2)] for c in es.CATEGORIES}


def test_tc8_run_is_deterministic_and_counts_everything():
    a = es.run(_world(1), FROZEN, n_perm=5, generated_at="x")
    b = es.run(_world(1), FROZEN, n_perm=5, generated_at="y")
    c = es.run(_world(2), FROZEN, n_perm=5, generated_at="x")
    assert a["report_hash"] == b["report_hash"] and a["experiment_id"] == b["experiment_id"]
    assert a["validated"] is False and a["tested_configurations"] == 7 * 4 * 7 * 6
    assert set(a["configs"]) == set(es.CONFIGS) and set(a["configs"]["near_only"]) == set(es.CATEGORIES)
    assert a["report_hash"] != c["report_hash"] or a["data_window"] == c["data_window"]
    assert all(v["chosen"] in ("near", "next", "far") for v in a["expiry_selection"].values())


def test_tc9_no_lookahead_in_buckets():
    w = _world(3)
    days = sorted({r["day"] for r in w["stf"]})
    full = es.build_buckets(w["stf"], days)
    cut = es.build_buckets([r for r in w["stf"] if r["day"] <= days[60]], days)
    for sym in ("S0", "S7"):
        for d in days[:61]:
            assert full[sym][d][0]["p"] == cut[sym][d][0]["p"] and full[sym][d][0]["rvol"] == cut[sym][d][0]["rvol"]
