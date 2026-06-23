"""
Tests for nidp_guards (defect detectors) and nidp_sink (real-enum mapping).
Run: python test_nidp_guards.py
"""

from datetime import date
import pandas as pd

from nidp.services.quality_gate import dq_guards as G
from nidp.services.quality_gate.dq_sink import severity_for, status_for, action_for, as_text


# ===========================================================================
# columns_not_identical — the duplicated-score smell
# ===========================================================================
def test_identical_columns_flagged():
    # quality_score == final_score on every row -> duplicate-metric suspected
    df = pd.DataFrame({"final_score": [50.0, 60.0, 70.0],
                       "quality_score": [50.0, 60.0, 70.0]})
    r = G.columns_not_identical("final_score", "quality_score").run(df)
    assert not r.success and r.severity == "warn"


def test_distinct_columns_pass():
    df = pd.DataFrame({"final_score": [50.0, 60.0, 70.0],
                       "technical_score": [12.0, 88.0, 41.0]})
    assert G.columns_not_identical("final_score", "technical_score").run(df).success


# ===========================================================================
# distinct_count_per_key — fan-out guard
# ===========================================================================
def test_fanout_flagged():
    # one isin/date mapping to two scheme_codes -> join fan-out
    df = pd.DataFrame([
        ("INE001", date(2026, 5, 1), "S1"),
        ("INE001", date(2026, 5, 1), "S2"),
        ("INE002", date(2026, 5, 1), "S3"),
    ], columns=["isin", "as_of_date", "scheme_code"])
    r = G.distinct_count_per_key(["isin", "as_of_date"], "scheme_code", max_distinct=1).run(df)
    assert not r.success and r.observed["actual"] == 1


def test_fanout_clean_passes():
    df = pd.DataFrame([
        ("INE001", date(2026, 5, 1), "S1"),
        ("INE002", date(2026, 5, 1), "S3"),
    ], columns=["isin", "as_of_date", "scheme_code"])
    assert G.distinct_count_per_key(["isin", "as_of_date"], "scheme_code", max_distinct=1).run(df).success


# ===========================================================================
# single_source_per_key — nondeterministic latest-pick tripwire
# ===========================================================================
def test_multisource_tripwire():
    df = pd.DataFrame([
        ("INFY", date(2024, 3, 31), "NSE"),
        ("INFY", date(2024, 3, 31), "Screener"),
        ("TCS", date(2024, 3, 31), "NSE"),
    ], columns=["symbol", "period_end", "source"])
    r = G.single_source_per_key(["symbol", "period_end"], "source").run(df)
    assert not r.success and r.observed["actual"] == 1     # only INFY has 2 sources


# ===========================================================================
# between_excluding_sentinels — don't chase -99999
# ===========================================================================
def test_sentinel_excluded_then_bounded():
    df = pd.DataFrame({"sharpe_1y": [-99999.9999, 0.5, 1.2, -2.0, 50.0]})
    r = G.between_excluding_sentinels("sharpe_1y", min=-10, max=10,
                                      sentinels=(-99999.9999,)).run(df)
    # sentinel flagged (present) AND the 50.0 is out of band
    assert not r.success
    assert r.observed["actual"]["sentinels"] == 1
    assert r.observed["actual"]["out_of_band"] == 1        # the 50.0, NOT the sentinel


def test_no_sentinel_clean():
    df = pd.DataFrame({"sharpe_1y": [0.5, 1.2, -2.0]})
    r = G.between_excluding_sentinels("sharpe_1y", min=-10, max=10,
                                      sentinels=(-99999.9999,)).run(df)
    assert r.success


# ===========================================================================
# success_rate_floor — parse-failure detector
# ===========================================================================
def test_parse_failure_rate_floor():
    # 99.99%-style failure: 1 parsed of 100
    df = pd.DataFrame({"parse_status": ["parsed"] + ["failed"] * 99})
    r = G.success_rate_floor("parse_status", {"parsed"}, min_rate=0.5).run(df)
    assert not r.success


def test_healthy_parse_rate_passes():
    df = pd.DataFrame({"parse_status": ["parsed"] * 90 + ["failed"] * 10})
    assert G.success_rate_floor("parse_status", {"parsed"}, min_rate=0.5).run(df).success


# ===========================================================================
# null_rate_within — coverage drift
# ===========================================================================
def test_null_rate_band():
    df = pd.DataFrame({"band": ["BUY"] * 50 + [None] * 50})   # 50% null
    assert not G.null_rate_within("band", max_rate=0.25).run(df).success
    assert G.null_rate_within("band", max_rate=1.0).run(df).success  # known-null tolerated


# ===========================================================================
# sink mapping — real enums + TEXT rendering
# ===========================================================================
def test_severity_map():
    assert severity_for("warn") == "WARN"
    assert severity_for("fail") == "ERROR"
    assert severity_for("error") == "CRITICAL"


def test_status_map():
    assert status_for("OK") == "PASSED"
    assert status_for("WARN") == "PARTIAL"
    assert status_for("FAIL") == "FAILED"
    assert status_for("ERROR") == "ERROR"


def test_action_class_not_c_taxonomy():
    # failure_class is an ACTION, not C1..C8
    assert action_for("C4.grouped_sum[x]", "C4") == "BLOCK"
    assert action_for("C5.freshness[d]", "C5") == "RETRY"
    assert action_for("C2.between[x]", "C2") == "FIX"
    assert action_for("C3.q4_annual_contamination", "C3") == "BLOCK"   # override
    assert action_for("meta.columns_exist", "meta") == "BLOCK"


def test_text_rendering():
    assert as_text(True) == "True"          # bool -> text (the known gotcha)
    assert as_text(None) is None
    assert as_text({"a": 1}) == '{"a": 1}'
    assert as_text(3) == "3"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}"); traceback.print_exc(); failed += 1
    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)
