"""scan-rules.v2 (services/positional_engine/setup_rules.py): Momentum with an RSI band, and the per-stock explanation
fields matched_filters, why_matched, risk_flags and data_status.

No database and no network. Fixtures built by `_row` are MOCK — not real data. The one real-data fixture is
tests/fixtures/scan_snapshot_20261019.json: rows copied unedited from staging's GET /v1/features/scan-snapshot SQL for
the 2026-10-19 session (see that file's "captured" note).

Worked examples
  Momentum v2   return_20d ≥ 5, 55 ≤ RSI(14) ≤ 75, close > SMA50, SMA50 slope > 0 (% a day over the 20 sessions before)
                RSI 55.0 passes, 54.99 fails; 75.0 passes, 75.01 fails; close equal to SMA50 fails (strict)
  History       indicators need 6 (5-day return), 15 (RSI, ATR), 21 (20-day return), 50 (SMA50), 61 (60-day return),
                70 (SMA50 slope) and 200 (SMA200) daily bars. A missing figure is "insufficient_history" only when
                another figure that needs MORE bars is present (so the history was short); else it is "missing".
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from services.positional_engine import setup_rules as rules

DAY = date(2026, 10, 19)


def _row(sym, **over):
    """An eligible, liquid, EQ stock that passes Momentum v2 unless `over` changes it. MOCK — not real data."""
    r = {"symbol": sym, "close": 100.0, "prev_close": 99.0, "open_price": 99.5, "traded_value_cr_20d": 25.0,
         "has_reference": True, "series": "EQ", "is_etf": False, "price_band_pct": 20.0, "fno_eligible": False,
         "atr_pct": 3.0, "return_20d_pct": 9.0, "return_5d_pct": 1.0, "return_60d_pct": 15.0, "rsi14": 62.0,
         "sma50": 95.0, "sma50_slope": 0.1, "sma200": 80.0, "vol_z20": 0.2, "last_results_date": None,
         "next_results_date": None}
    r.update(over)
    return r


def _mom(**over):
    ev = rules.evaluate([_row("X", **over)], DAY)
    return ev["rows"]["X"], ev


# ── version and rule ─────────────────────────────────────────────────────────

def test_version_is_v2_and_the_rsi_band_is_in_the_public_rules():
    assert rules.RULES_VERSION.startswith("scan-rules.v2")
    m = rules.public_rules()["categories"]["momentum"]
    assert (m["rsi14_min"], m["rsi14_max"]) == (55.0, 75.0)
    # v1 keys still sent, unchanged
    assert m["return_20d_min_pct"] == 5.0 and m["sma50_slope_above"] == 0.0 and m["rank_by"] == "return_20d_pct"


def test_momentum_v2_qualifier_passes_and_explains_itself():
    r, ev = _mom()
    assert r["categories"] == ["momentum"] and r["matched_filters"] == ["momentum"]
    why = r["why_matched"]["momentum"]
    by = {(c["indicator"], c["op"]): c for c in why}
    assert by[("return_20d_pct", ">=")]["value"] == 9.0 and by[("return_20d_pct", ">=")]["threshold"] == 5.0
    assert by[("rsi14", ">=")]["value"] == 62.0 and by[("rsi14", ">=")]["threshold"] == 55.0
    assert by[("rsi14", "<=")]["threshold"] == 75.0
    assert by[("close", ">")]["value"] == 100.0 and by[("close", ">")]["threshold"] == 95.0
    assert by[("close", ">")]["against"] == "sma50"
    assert by[("sma50_slope", ">")]["value"] == 0.1
    assert len(why) == 5 and all(c["passed"] is True and c["status"] == "ok" for c in why)


def test_momentum_v2_boundaries():
    ok = lambda **o: "momentum" in _mom(**o)[0]["categories"]
    assert ok(rsi14=55.0) and not ok(rsi14=54.99)
    assert ok(rsi14=75.0) and not ok(rsi14=75.01)
    assert ok(return_20d_pct=5.0) and not ok(return_20d_pct=4.99)
    assert not ok(close=95.0) and ok(close=95.01)                   # strict: equal to SMA50 fails
    assert not ok(sma50_slope=0.0) and ok(sma50_slope=0.001)        # strict: flat average fails


def test_an_extended_stock_leaves_momentum_and_is_flagged_extended():
    r, ev = _mom(rsi14=82.0, return_20d_pct=65.0)                   # the shape of a +65 % run-up
    assert r["categories"] == [] and "extended_price" in {f["flag"] for f in r["risk_flags"]}
    assert ev["categories"]["momentum"]["total"] == 0


# ── missing data is never a neutral value ────────────────────────────────────

def test_missing_rsi_is_not_a_pass_and_not_insufficient_history_when_longer_indicators_exist():
    r, ev = _mom(rsi14=None)
    assert "momentum" not in r["categories"]
    ds = r["data_status"]["momentum"]
    assert ds["status"] == "unevaluable" and ds["indicators"]["rsi14"] == "missing"
    assert ds["indicators"]["sma50_slope"] == "ok"                  # 70 bars were there, so RSI's 15 were too
    assert ev["categories"]["momentum"]["missing"] == 1 and ev["categories"]["momentum"]["insufficient_history"] == 0
    assert {"flag": "missing_indicators", "detail": "rsi14"} in r["risk_flags"]


def test_short_history_is_labelled_insufficient_history_not_a_failed_signal():
    # 50–69 bars: SMA50 exists, its slope (70 bars) and SMA200 do not.
    r, ev = _mom(sma50_slope=None, sma200=None, return_60d_pct=None)
    ds = r["data_status"]["momentum"]
    assert ds["status"] == "unevaluable"
    assert ds["indicators"]["sma50_slope"] == "insufficient_history"
    assert ds["indicators"]["return_20d_pct"] == "ok"
    assert ev["categories"]["momentum"]["insufficient_history"] == 1 and ev["categories"]["momentum"]["missing"] == 1
    assert {"flag": "insufficient_history", "detail": "sma50_slope"} in r["risk_flags"]
    cond = {(c["indicator"], c["op"]): c for c in r["why_matched"].get("momentum", [])}
    assert cond == {}                                               # not matched, so nothing is claimed


def test_a_stock_with_no_indicator_at_all_cannot_be_called_short_history():
    r, _ = _mom(rsi14=None, return_20d_pct=None, return_5d_pct=None, return_60d_pct=None, atr_pct=None, sma50=None,
                sma50_slope=None, sma200=None)
    ind = r["data_status"]["momentum"]["indicators"]
    assert {k: v for k, v in ind.items() if k != "close"} == {k: "missing" for k in ind if k != "close"}


def test_a_definite_failure_beats_an_unknown_figure():
    r, _ = _mom(rsi14=80.0, sma50_slope=None, sma200=None, return_60d_pct=None)
    ds = r["data_status"]["momentum"]
    assert ds["status"] == "no_match"                               # RSI 80 fails whatever the slope is
    assert r["categories"] == []


# ── overlapping filters, risk flags ──────────────────────────────────────────

def test_filters_overlap_and_each_has_its_own_explanation():
    r, ev = _mom(vol_z20=3.1, fno_eligible=True, price_band_pct=None)
    assert r["matched_filters"] == r["categories"] == ["momentum", "unusual_volume", "fno"]
    assert set(r["why_matched"]) == {"momentum", "unusual_volume", "fno"}
    uv = r["why_matched"]["unusual_volume"][0]
    assert (uv["indicator"], uv["op"], uv["threshold"], uv["value"], uv["passed"]) == ("vol_z20", ">=", 2.0, 3.1, True)
    assert ev["categories"]["fno"]["symbols"] == ["X"]


def test_results_day_explanation_carries_the_results_date():
    r, _ = _mom(last_results_date=DAY.isoformat(), return_5d_pct=4.0, vol_z20=1.5)
    names = {c["indicator"] for c in r["why_matched"]["results_day"]}
    assert names == {"last_results_date", "return_5d_pct", "vol_z20"}
    assert r["why_matched"]["results_day"][0]["value"] == DAY.isoformat()


def test_a_clean_stock_has_no_flags_and_a_stock_in_no_filter_has_empty_explanations():
    r, _ = _mom()
    assert r["risk_flags"] == []
    r2, _ = _mom(return_20d_pct=1.0)
    assert r2["matched_filters"] == [] and r2["why_matched"] == {}


def test_risk_flags_gap_event_liquidity():
    assert {"flag": "gap_risk", "detail": "+6.1% open vs previous close"} in _mom(open_price=105.0, prev_close=99.0)[0]["risk_flags"]
    assert any(f["flag"] == "gap_risk" for f in _mom(open_price=94.0, prev_close=99.0)[0]["risk_flags"])   # gap down too
    assert not any(f["flag"] == "gap_risk" for f in _mom(open_price=103.9, prev_close=99.0)[0]["risk_flags"])  # +4.9 %
    soon = (DAY + timedelta(days=rules.RISK_FLAGS["event_window_days"])).isoformat()
    later = (DAY + timedelta(days=rules.RISK_FLAGS["event_window_days"] + 1)).isoformat()
    assert any(f["flag"] == "event_risk" for f in _mom(next_results_date=soon)[0]["risk_flags"])
    assert not any(f["flag"] == "event_risk" for f in _mom(next_results_date=later)[0]["risk_flags"])
    assert not any(f["flag"] == "event_risk" for f in _mom(next_results_date=DAY.isoformat())[0]["risk_flags"])   # today's is already out
    thin, _ = _mom(traded_value_cr_20d=9.0)
    assert thin["eligible"] is False and "low_liquidity" in {f["flag"] for f in thin["risk_flags"]}


# ── backward compatibility ───────────────────────────────────────────────────

def test_v1_fields_are_unchanged_and_v2_fields_are_additive():
    r, ev = _mom()
    for k in ("eligible", "exclusion", "risk_class", "liquidity_class", "categories"):
        assert k in r
    assert r["eligible"] is True and r["exclusion"] is None and r["risk_class"] == "medium" and r["liquidity_class"] == "liquid"
    m = ev["categories"]["momentum"]
    assert {"total", "shown", "symbols", "rank_by", "missing"} <= set(m)
    assert set(ev) == {"rows", "universe", "categories"}


def test_evaluate_is_a_pure_function_of_its_rows_and_date():
    rows = [_row("A"), _row("B", rsi14=None)]
    assert rules.evaluate(rows, DAY) == rules.evaluate(rows, DAY)


# ── the latest staging snapshot (real rows, 2026-10-19) ──────────────────────

def test_real_staging_rows_2026_10_19():
    fx = json.loads((Path(__file__).parent / "fixtures" / "scan_snapshot_20261019.json").read_text())
    assert fx["as_of"] == "2026-10-19"
    ev = rules.evaluate(fx["rows"], date.fromisoformat(fx["as_of"]))
    by = ev["rows"]
    assert len(by) == len(fx["rows"])
    for sym, row in by.items():
        raw = next(x for x in fx["rows"] if x["symbol"] == sym)
        rsi, r20 = raw.get("rsi14"), raw.get("return_20d_pct")
        in_mom = "momentum" in row["categories"]
        if in_mom:
            assert rsi is not None and 55 <= float(rsi) <= 75 and float(r20) >= 5
            assert all(c["passed"] is True for c in row["why_matched"]["momentum"])
        # every row, member or not, says what is behind its status
        assert row["data_status"]["momentum"]["status"] in {"match", "no_match", "unevaluable"}
        assert row["matched_filters"] == row["categories"]
