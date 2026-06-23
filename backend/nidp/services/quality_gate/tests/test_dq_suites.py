"""
Regression tests — each schema-forced CORRECTION catches its bad pattern AND
passes clean. Run: python test_nidp_dq.py   (or pytest)

These pin the four corrections the schema pass forced, plus the mf_holdings
grouped/subtotal/shorts behavior and the gate verdict + finding mapping.
"""

from datetime import date
import pandas as pd

from nidp.services.quality_gate import dq_rules as E
from nidp.services.quality_gate.dq_suites import build_suites
from nidp.services.quality_gate.dq_gate import run_suite, finding_rows, run_header, RunContext


# ===========================================================================
# CORRECTION 1 — nse_financials uniqueness drops period_type
# ===========================================================================
def test_correction1_casing_dupe_caught_without_period_type_in_key():
    # Two rows, same (symbol, period_end, consolidated), differing ONLY by
    # period_type casing. The corrected key (no period_type) must flag them.
    df = pd.DataFrame([
        ("HDFCBANK", date(2024, 3, 31), "quarterly", False),
        ("HDFCBANK", date(2024, 3, 31), "QUARTERLY", False),
    ], columns=["symbol", "period_end", "period_type", "consolidated"])

    corrected = E.compound_unique("symbol", "period_end", "consolidated")
    r = corrected.run(df)
    assert not r.success and r.severity == "fail"

    # contrast: the doc-asserted key (WITH period_type) would mask it
    masked = E.compound_unique("symbol", "period_end", "period_type", "consolidated")
    assert masked.run(df).success, "period_type in key wrongly masks the case-dupe"


def test_correction1_distinct_basis_not_flagged():
    # consolidated True vs False is a legitimately distinct row, not a dupe
    df = pd.DataFrame([
        ("HDFCBANK", date(2024, 3, 31), "quarterly", True),
        ("HDFCBANK", date(2024, 3, 31), "quarterly", False),
    ], columns=["symbol", "period_end", "period_type", "consolidated"])
    assert E.compound_unique("symbol", "period_end", "consolidated").run(df).success


# ===========================================================================
# CORRECTION 2 — period_type casing: membership passes, canonical warns
# ===========================================================================
def test_correction2_mixed_casing_passes_membership():
    df = pd.DataFrame({"period_type": ["annual", "quarterly", "QUARTERLY"]})
    r = E.in_set("period_type", {"annual", "quarterly"}, case_insensitive=True).run(df)
    assert r.success, "case-insensitive membership must accept QUARTERLY"


def test_correction2_unknown_value_fails_membership():
    df = pd.DataFrame({"period_type": ["annual", "monthly"]})
    r = E.in_set("period_type", {"annual", "quarterly"}, case_insensitive=True).run(df)
    assert not r.success and r.severity == "fail"


def test_correction2_canonical_casing_warns_not_fails():
    df = pd.DataFrame({"period_type": ["annual", "quarterly", "QUARTERLY"]})
    r = E.canonical_casing("period_type", canonical="lower", severity="warn").run(df)
    assert not r.success and r.severity == "warn"     # surfaced, not gated hard


# ===========================================================================
# CORRECTION 3 — shareholding uniqueness tighter than PK (drops source)
# ===========================================================================
def test_correction3_multisource_dupe_caught():
    # PK allows NSE + Screener for the same symbol/period_end; our tighter check flags it
    df = pd.DataFrame([
        ("INFY", date(2024, 3, 31), "NSE"),
        ("INFY", date(2024, 3, 31), "Screener"),
    ], columns=["symbol", "period_end", "source"])
    assert not E.compound_unique("symbol", "period_end").run(df).success
    # the real PK (with source) would NOT catch it
    assert E.compound_unique("symbol", "period_end", "source").run(df).success


# ===========================================================================
# CORRECTION 4 — fii_dii domain {FII, DII}; band allows blank
# ===========================================================================
def test_correction4_fii_dii_domain():
    df = pd.DataFrame({"category": ["FII", "DII"]})
    assert E.in_set("category", {"FII", "DII"}).run(df).success
    bad = pd.DataFrame({"category": ["FII", "FPI"]})           # FPI not in real domain
    assert not E.in_set("category", {"FII", "DII"}).run(bad).success


def test_correction4_band_allows_blank_gate_failures():
    df = pd.DataFrame({"band": ["BUY", "HOLD", "", "STRONG_BUY"]})
    allowed = {"HOLD", "REDUCE", "BUY", "AVOID", "STRONG_BUY"}
    assert E.in_set("band", allowed, allow_blank=True).run(df).success
    # an actually-unknown value still fails
    bad = pd.DataFrame({"band": ["BUY", "SELL"]})
    assert not E.in_set("band", allowed, allow_blank=True).run(bad).success


# ===========================================================================
# mf_holdings — shorts admitted, corruption flagged, subtotal flagged, NIPPON guard
# ===========================================================================
def test_weight_pct_admits_shorts_flags_corruption():
    df = pd.DataFrame({"weight_pct": [-20.0, 5.0, 50.0, 412.8]})
    r = E.between("weight_pct", min=-25, max=100).run(df)
    assert not r.success and r.observed["actual"] == 1     # only the 412.8


def test_no_subtotal_flags_total_not_company_names():
    df = pd.DataFrame({"security_name": [
        "Reliance Industries", "Grand Total", "TotalEnergies SE", "Sub-Total"]})
    r = E.no_subtotal_rows("security_name").run(df)
    # "Grand Total" and "Sub-Total" flagged; "TotalEnergies" (no word boundary) is NOT
    assert r.observed["actual"] == 2
    flagged = {v["security_name"] for v in r.violations}
    assert "TotalEnergies SE" not in flagged


def test_grouped_sum_reports_schemes_not_rows():
    df = pd.DataFrame([
        ("N1", 60.0), ("N1", 164.0),    # NIPPON: sums to 224
        ("N2", 50.0), ("N2", 50.0),     # clean: 100
    ], columns=["scheme_code", "weight_pct"])
    r = E.grouped_sum_between(["scheme_code"], "weight_pct", min=98, max=102).run(df)
    assert not r.success
    assert r.observed["actual"] == 1                      # ONE bad scheme, not two rows
    assert r.violations[0]["scheme_code"] == "N1"
    assert abs(r.violations[0]["group_sum"] - 224.0) < 1e-6


# ===========================================================================
# Gate — meta-guard, verdict, finding mapping
# ===========================================================================
def test_gate_meta_guard_aborts_on_missing_column():
    suites = build_suites()
    # drop a required column -> columns-exist guard must abort with FAIL
    df = pd.DataFrame({"symbol": ["INFY"]})   # missing everything else
    run = run_suite(suites["nse_financials"], df)
    assert run.aborted and run.verdict == "FAIL"
    assert run.results[0].severity == "error"


def test_gate_finding_rows_map_to_real_columns():
    suites = build_suites()
    df = pd.DataFrame([
        ("N1", date(2026, 5, 31), "INE001A01036", "Reliance", "", 60.0, "AMC"),
        ("N1", date(2026, 5, 31), "INE002A01018", "TCS",      "", 164.0, "AMC"),
    ], columns=["scheme_code", "as_of_month", "security_isin", "security_name",
                "instrument_type", "weight_pct", "source"])
    run = run_suite(suites["mf_holdings"], df)
    ctx = RunContext(ingester="mf_holdings", target_date=date(2026, 5, 31))
    rows = finding_rows(run, ctx)
    assert run.verdict == "FAIL" and rows
    needed = {"finding_id", "validation_id", "job_run_id", "ingester", "target_date",
              "rule_name", "severity", "failure_class", "message", "expected",
              "actual", "sample_rows", "detected_at"}
    assert needed <= set(rows[0].keys())
    # failure_class carries the C-category
    assert any(r["failure_class"] == "C4" for r in rows)


def test_gate_clean_data_passes():
    suites = build_suites()
    df = pd.DataFrame([
        ("N1", date(2026, 5, 31), "INE001A01036", "Reliance", "", 60.0, "AMC"),
        ("N1", date(2026, 5, 31), "INE002A01018", "TCS",      "", 40.0, "AMC"),
    ], columns=["scheme_code", "as_of_month", "security_isin", "security_name",
                "instrument_type", "weight_pct", "source"])
    run = run_suite(suites["mf_holdings"], df)
    assert run.verdict == "OK", [(r.check, r.message) for r in run.failures]


# --- standalone runner ---
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
