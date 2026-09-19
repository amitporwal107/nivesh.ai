"""Unit + leakage tests for the PIT audit core (QA-02..05, TOL-02, AV-03..05, POL-03..05, ARC-01/05)."""
import datetime as dt
import gzip
import json
import multiprocessing as mp
import os

import pytest

import availability as A
import compare as C
import pit_policy as P
from archive import Archive
from contracts import IST, canonical_json, filing_record, metric_record, sha256_json
from session import TradingCalendar, decision_at, filename_ts, first_usable_session, parse_nse_ts


def T(y, m, d, H=0, M=0, S=0):
    return dt.datetime(y, m, d, H, M, S, tzinfo=IST)


CAL = TradingCalendar([dt.date(2026, 9, d) for d in (14, 15, 16, 17, 18, 21, 22)])  # 19/20 weekend; 14 is a session here


# ---------------- timestamps & sessions ----------------
def test_parse_precision_and_formats():
    assert parse_nse_ts("31-Oct-2024 20:36:01") == (T(2024, 10, 31, 20, 36, 1), "second")
    assert parse_nse_ts("31-Oct-2024 20:36") == (T(2024, 10, 31, 20, 36), "minute")
    assert parse_nse_ts("20-AUG-2026 15:13:12") == (T(2026, 8, 20, 15, 13, 12), "second")
    t, p = parse_nse_ts("20-AUG-2026")
    assert p == "day" and t == T(2026, 8, 20)
    assert parse_nse_ts(None) == (None, None) and parse_nse_ts("-") == (None, None) and parse_nse_ts("garbage") == (None, None)


def test_filename_timestamp():
    assert filename_ts("https://x/INTEGRATED_FILING_INDAS_181410_31072026222906_iXBRL.html") == T(2026, 7, 31, 22, 29, 6)
    assert filename_ts("https://x/no_timestamp.pdf") is None


def test_calendar_unknown_outside_range():
    assert CAL.is_session(dt.date(2026, 9, 19)) is False
    assert CAL.is_session(dt.date(2026, 10, 30)) is None  # beyond the certified calendar: unknown, not a session
    assert CAL.next_session(dt.date(2026, 9, 18)) == dt.date(2026, 9, 21)
    assert CAL.next_session(dt.date(2026, 9, 22)) is None


def test_decision_at_defaults():
    assert decision_at("eod", dt.date(2026, 9, 18)) == T(2026, 9, 18, 15, 30)
    assert decision_at("next_open", dt.date(2026, 9, 18)) == T(2026, 9, 18, 9, 14)
    with pytest.raises(ValueError):
        decision_at("bar_5m", dt.date(2026, 9, 18))


@pytest.mark.parametrize("avail,freq,expected", [
    (T(2026, 9, 18, 8, 0), "next_open", dt.date(2026, 9, 18)),     # pre-open: same session
    (T(2026, 9, 18, 9, 10), "next_open", dt.date(2026, 9, 21)),    # 09:10 + 5 min margin > 09:14
    (T(2026, 9, 18, 15, 24), "eod", dt.date(2026, 9, 18)),         # 15:29 <= 15:30 inclusive
    (T(2026, 9, 18, 15, 26), "eod", dt.date(2026, 9, 21)),         # 15:31 > 15:30
    (T(2026, 9, 18, 12, 0), "intraday", dt.date(2026, 9, 18)),
    (T(2026, 9, 18, 15, 31), "intraday", dt.date(2026, 9, 21)),    # after the close
    (T(2026, 9, 19, 11, 0), "eod", dt.date(2026, 9, 21)),          # non-trading day
    (T(2026, 9, 22, 18, 0), "eod", None),                          # beyond the calendar: unknown
])
def test_first_usable_session(avail, freq, expected):
    assert first_usable_session(avail, freq, CAL) == expected


def test_naive_timestamps_rejected():
    with pytest.raises(ValueError):
        first_usable_session(dt.datetime(2026, 9, 18, 10), "eod", CAL)


# ---------------- availability rule AV-1 ----------------
def test_av1_high_needs_two_independent_systems():
    e = [A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 12, 41, 19), "second"),
         A.evidence("nse_dissemination", "NSE", T(2026, 7, 24, 12, 41, 30), "second")]
    r = A.assess(e)
    assert r["availability_confidence"] == "MEDIUM" and r["available_at"] == "2026-07-24T12:41:19+05:30"
    r = A.assess(e + [A.evidence("bse_announcement", "BSE", T(2026, 7, 24, 12, 45), "minute")])
    assert r["availability_confidence"] == "HIGH" and r["first_publicly_available_at"] == "2026-07-24T12:41:19+05:30"


def test_av1_disagreement_stays_medium_and_day_precision_is_low():
    r = A.assess([A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 12, 41), "minute"),
                  A.evidence("bse_announcement", "BSE", T(2026, 7, 24, 14, 0), "minute")])
    assert r["availability_confidence"] == "MEDIUM"
    r = A.assess([A.evidence("nse_submission", "NSE", T(2026, 8, 20), "day")])
    assert r["availability_confidence"] == "LOW" and r["available_at"] is None


def test_retrieval_time_is_never_evidence():
    with pytest.raises(ValueError):
        A.evidence("retrieved_at", "LOCAL", T(2026, 9, 19, 10), "second")


def test_public_time_before_submission_is_contradiction():
    r = A.assess([A.evidence("nse_submission", "NSE", T(2026, 7, 24, 14, 0), "minute"),
                  A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 12, 0), "second")])
    assert r["availability_confidence"] == "LOW" and r["available_at"] is None and "contradiction" in r


# ---------------- tolerance, materiality, classification ----------------
CFG = C.load_config()


@pytest.mark.parametrize("m,a,b,exp", [
    ("pat_cr", 100.0, 100.4, "WITHIN_TOLERANCE"), ("pat_cr", 100.0, 101.0, "OUTSIDE_TOLERANCE"),
    ("pat_cr", 10000.0, 10040.0, "WITHIN_TOLERANCE"),        # 0.4% of a large value
    ("pat_cr", 0.0, 0.4, "WITHIN_TOLERANCE"), ("pat_cr", 0.0, 0.6, "OUTSIDE_TOLERANCE"),   # zero band: abs only
    ("pat_cr", -50.0, -50.2, "WITHIN_TOLERANCE"), ("pat_cr", None, 5.0, "UNRESOLVED"), ("pat_cr", 0.0, None, "UNRESOLVED"),
    ("eps_basic", 1.23, 1.24, "WITHIN_TOLERANCE"), ("promoter_pct", 55.42, 55.44, "OUTSIDE_TOLERANCE"),
])
def test_tolerance(m, a, b, exp):
    assert C.tolerance(m, a, b, CFG) == exp


def test_materiality_and_sign_change():
    r = C.materiality("pat_cr", 5.0, -5.0, CFG)
    assert r["sign_change"] and r["review_required"] and r["result"] == "MATERIAL_DIFFERENCE"
    assert C.materiality("pat_cr", 0.0, 0.0, CFG)["result"] == "IMMATERIAL"
    assert C.materiality("promoter_pct", 55.0, 55.6, CFG)["result"] == "MATERIAL_DIFFERENCE"
    assert C.materiality("pat_cr", None, 1.0, CFG)["result"] == "UNRESOLVED"


def test_classify_matches_and_explanations():
    assert C.classify("pat_cr", 467.45, 467.45)["reconciliation_status"] == "MATCH_FIRST_FILED"
    r = C.classify("pat_cr", 4674500000.0, 467.45)
    assert r["difference_type"] == "UNIT_CONVERSION" and r["reconciliation_status"] == "DIFFERS_EXPLAINED"
    r = C.classify("pat_cr", 300.0, 467.45, other_basis=300.2)
    assert r["difference_type"] == "DEFINITION_DIFFERENCE"
    r = C.classify("pat_cr", 253.4, 467.45, other_period_values=[("2026-03-31", 253.45)])
    assert r["difference_type"] == "PERIOD_MAPPING"
    r = C.classify("pat_cr", 999.0, 467.45)
    assert r["difference_type"] == "UNRESOLVED" and r["reconciliation_status"] == "DIFFERS_UNEXPLAINED"
    r = C.classify("pat_cr", None, 467.45)
    assert r["reconciliation_status"] == "DIFFERS_UNEXPLAINED" and "never read as zero" in r["explanation"]


def test_restatement_only_with_filing_evidence():
    r = C.classify("pat_cr", 420.0, 467.45, latest_known=420.1)
    assert r["difference_type"] == "LATEST_REVISION_MATCH" and r["revision_type"] == "FILING_REVISION"
    r = C.classify("pat_cr", 420.0, 467.45, latest_known=420.1, restatement_evidence={"later_filing_id": "X9"})
    assert r["difference_type"] == "RESTATEMENT" and r["revision_type"] == "RESTATEMENT"
    r = C.classify("pat_cr", 420.0, 467.45)  # a numeric difference alone is never a restatement
    assert r["difference_type"] == "UNRESOLVED"


# ---------------- gate: classes and leakage ----------------
RULE_OK = {"rule_id": "R1", "rule_version": "1", "validation_sample_size": 40, "validation_coverage": 0.9,
           "evidence": ["x"], "approval_status": "APPROVED"}


def test_point_in_time_validated_mapping():
    assert P.point_in_time_validated("EXACT_PIT", value_matches_filing=True, availability_confidence="HIGH")
    assert not P.point_in_time_validated("EXACT_PIT", value_matches_filing=True, availability_confidence="MEDIUM")
    assert P.point_in_time_validated("PIT_VALIDATED_RULE", rule=RULE_OK)
    assert not P.point_in_time_validated("PIT_VALIDATED_RULE", rule=dict(RULE_OK, approval_status="PENDING"))
    for c in ("ESTIMATED_RULE", "RESTATED", "FORWARD_ONLY", "UNVERIFIED"):
        assert not P.point_in_time_validated(c)
    with pytest.raises(ValueError):
        P.point_in_time_validated("MADE_UP")


@pytest.mark.parametrize("cls", ["UNVERIFIED", "FORWARD_ONLY", "RESTATED", "ESTIMATED_RULE"])
def test_rejected_classes(cls):
    ok, why = P.is_feature_eligible(cls, T(2026, 7, 24, 12), T(2026, 7, 25, 15, 30), True)
    assert not ok and cls in why


def test_exact_pit_boundary_inclusive_after_margin():
    d = T(2026, 7, 24, 15, 30)
    assert P.is_feature_eligible("EXACT_PIT", T(2026, 7, 24, 15, 25), d, True)[0]          # 15:30 == cutoff
    assert not P.is_feature_eligible("EXACT_PIT", T(2026, 7, 24, 15, 25, 1), d, True)[0]   # one second late
    assert not P.is_feature_eligible("EXACT_PIT", T(2026, 7, 24, 12), d, True, feature_cutoff_at=T(2026, 7, 24, 11))[0]


def test_rule_governance():
    a, d = T(2026, 7, 24, 12), T(2026, 7, 25, 15, 30)
    assert P.is_feature_eligible("PIT_VALIDATED_RULE", a, d, True, rule=RULE_OK)[0]
    assert not P.is_feature_eligible("PIT_VALIDATED_RULE", a, d, True, rule=dict(RULE_OK, validation_sample_size=0))[0]
    assert not P.is_feature_eligible("PIT_VALIDATED_RULE", a, d, True)[0]


# the seven leakage scenarios of the owner's review (QA-05); each must be rejected
def test_leak_1_filing_published_after_decision():
    assert not P.is_feature_eligible("EXACT_PIT", T(2026, 7, 24, 16), T(2026, 7, 24, 15, 30), True)[0]


def test_leak_2_revised_value_published_after_decision():
    revised_available = T(2026, 8, 30, 18)  # the revision is a separate record with its own available_at
    assert not P.is_feature_eligible("EXACT_PIT", revised_available, T(2026, 8, 1, 15, 30), True)[0]


def test_leak_3_current_trendlyne_value_for_a_historical_date():
    ok, why = P.is_feature_eligible("FORWARD_ONLY", T(2026, 9, 19, 9, 40), T(2025, 6, 1, 15, 30), True)
    assert not ok
    ok, why = P.is_forward_eligible("trendlyne_financials", T(2025, 6, 1, 15, 30), T(2026, 9, 19, 9, 40))
    assert not ok and "after the decision" in why


def test_leak_4_period_end_is_not_publication():
    period_end = T(2026, 6, 30)  # not a public timestamp: availability from period_end alone is LOW / None
    r = A.assess([A.evidence("nse_submission", "NSE", period_end, "day")])
    assert r["available_at"] is None
    assert not P.is_feature_eligible("EXACT_PIT", None, T(2026, 7, 2, 15, 30), True)[0]


def test_leak_5_retrieval_is_not_availability():
    with pytest.raises(ValueError):
        A.evidence("retrieved_at", "LOCAL", T(2026, 9, 19, 9, 40), "second")


def test_leak_6_event_date_before_announcement():
    board_meeting_date = T(2026, 7, 24)          # event date (day precision)
    announced = T(2026, 7, 24, 12, 41, 19)       # public broadcast
    decision = T(2026, 7, 24, 11, 0)             # a decision between the event date and the announcement
    assert not P.is_feature_eligible("EXACT_PIT", announced, decision, True)[0]
    assert A.assess([A.evidence("nse_submission", "NSE", board_meeting_date, "day")])["available_at"] is None


def test_leak_7_missing_availability_timestamp():
    ok, why = P.is_feature_eligible("EXACT_PIT", None, T(2026, 7, 25, 15, 30), True)
    assert not ok and why == "missing timestamp"
    with pytest.raises(ValueError):
        P.is_feature_eligible("EXACT_PIT", dt.datetime(2026, 7, 24, 12), T(2026, 7, 25, 15, 30), True)


def test_forward_eligibility_config_driven():
    pol = {"categories": {"x": {"archive_start_at": "2026-09-19T09:40:00+05:30"}, "y": {"archive_start_at": None}}}
    assert P.is_forward_eligible("x", T(2026, 9, 21, 9, 14), T(2026, 9, 20, 7, 30), pol)[0]
    assert not P.is_forward_eligible("x", T(2026, 9, 21, 9, 14), T(2026, 9, 18, 7, 30), pol)[0]
    assert not P.is_forward_eligible("y", T(2026, 9, 21, 9, 14), T(2026, 9, 20, 7, 30), pol)[0]


# ---------------- contracts & archive ----------------
def test_records_explicit_none_and_unknown_fields():
    r = filing_record(symbol="APARINDS", raw_row={"b": 1, "a": 2})
    assert r["isin"] is None and r["raw_row_sha256"] == sha256_json({"a": 2, "b": 1})
    with pytest.raises(KeyError):
        metric_record(symbol="X", made_up=1)
    with pytest.raises(ValueError):
        canonical_json({"t": dt.datetime(2026, 1, 1)})  # naive datetimes are refused


def test_deterministic_serialization():
    assert canonical_json({"b": 1, "a": [1, 2]}) == canonical_json({"a": [1, 2], "b": 1}) == '{"a":[1,2],"b":1}'


def test_archive_append_only_and_artifacts(tmp_path):
    a = Archive(str(tmp_path))
    a.append("filings", [{"id": 1}])
    a.append("filings", [{"id": 2}])
    assert [r["id"] for r in a.read("filings")] == [1, 2]
    h, p = a.store_artifact(b"xbrl-bytes", ".xml")
    assert a.store_artifact(b"xbrl-bytes", ".xml") == (h, p)
    with open(p, "wb") as f:
        f.write(b"tampered")
    with pytest.raises(RuntimeError):
        a.store_artifact(b"xbrl-bytes", ".xml")
    assert a.verify_artifacts() == [p]
    with pytest.raises(ValueError):
        a.append("../escape", [{"x": 1}])
    with pytest.raises(ValueError):
        a.store_artifact(b"x", "/../../etc")


def _writer(root, n):
    Archive(root).append("concurrent", [{"w": n, "i": i} for i in range(200)])


def test_archive_concurrent_writers(tmp_path):
    ps = [mp.Process(target=_writer, args=(str(tmp_path), n)) for n in range(4)]
    [p.start() for p in ps]
    [p.join() for p in ps]
    rows = list(Archive(str(tmp_path)).read("concurrent"))
    assert len(rows) == 800 and len({(r["w"], r["i"]) for r in rows}) == 800


def test_av1_nse_only_sources_never_high():
    r = A.assess([A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 12, 41, 19), "second"),
                  A.evidence("document_last_modified", "NSE", T(2026, 7, 24, 12, 41, 25), "second")])
    assert r["availability_confidence"] == "MEDIUM" and r["nse_corroborated"] is True


def test_definition_difference_explains_bank_revenue_and_is_never_a_match():
    import compare as C
    cfg = C.load_config()
    r = C.classify("revenue_cr", 8956.93, None, other_definition_values=[("interest_earned_cr", 8956.93)], cfg=cfg)
    assert r["difference_type"] == "DEFINITION_DIFFERENCE" and r["reconciliation_status"] == "DIFFERS_EXPLAINED"
    r = C.classify("revenue_cr", 10684.2, 9000.0, other_definition_values=[("total_income_cr", 10684.23)], cfg=cfg)
    assert r["difference_type"] == "DEFINITION_DIFFERENCE"
    r = C.classify("revenue_cr", 123.0, None, other_definition_values=[("total_income_cr", 10684.23)], cfg=cfg)
    assert r["difference_type"] == "UNRESOLVED" and "missing" in r["explanation"]


def test_av1_last_modified_never_sets_the_time():
    lm_early = A.evidence("document_last_modified", "NSE", T(2026, 7, 24, 12, 30), "second")
    r = A.assess([lm_early, A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 12, 41, 19), "second"),
                  A.evidence("bse_announcement", "BSE", T(2026, 7, 24, 12, 44), "second")])
    assert r["availability_confidence"] == "HIGH" and r["available_at"] == "2026-07-24T12:41:19+05:30"
    # BSE agrees only with the Last-Modified time, not with the NSE announcement -> not HIGH
    r = A.assess([lm_early, A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 13, 0), "second"),
                  A.evidence("bse_announcement", "BSE", T(2026, 7, 24, 12, 31), "second")])
    assert r["availability_confidence"] == "MEDIUM" and r["available_at"] == "2026-07-24T13:00:00+05:30"


def test_av1_high_precision_is_that_of_the_earliest_agreeing_item():
    r = A.assess([A.evidence("nse_broadcast", "NSE", T(2026, 7, 24, 12, 41), "minute"),
                  A.evidence("bse_announcement", "BSE", T(2026, 7, 24, 12, 43, 5), "second")])
    assert r["availability_confidence"] == "HIGH" and r["timestamp_precision"] == "minute"


def test_display_rounding_boundary_is_half_a_unit():
    import compare as C
    cfg = C.load_config()
    cfg["rounding_display_decimals"]["promoter_pct"] = 1
    assert C.classify("promoter_pct", 75.0, 75.05, cfg=cfg)["difference_type"] == "ROUNDING"   # half-way case
    assert C.classify("promoter_pct", 75.0, 75.06, cfg=cfg)["difference_type"] == "UNRESOLVED"


# ---------------- revision chronology (QA-03, NSE-05, TOL-05) ----------------
def _filing(listing, fid, flag, url, revised_at=None):
    return {"canonical": "X", "filing_type": "RESULTS", "period_end": "2026-06-30", "consolidation_type": "CONSOLIDATED",
            "listing": listing, "filing_id": fid, "revision_flag": flag, "document_url": url, "revised_at": revised_at}


def _metric(url, v):
    return {"document_url": url, "period_end": "2026-06-30", "consolidation_type": "CONSOLIDATED",
            "metric_name": "pat_cr", "metric_value": v}


def test_first_filed_value_survives_a_revision_and_the_revision_is_kept_separately():
    import analyze as Z
    fs = [_filing("integrated_results", "2", "REVISED", "u2", "2026-08-20T10:00:00+05:30"),
          _filing("integrated_results", "1", "ORIGINAL", "u1")]
    metrics = {"u1": [_metric("u1", 100.0)], "u2": [_metric("u2", 90.0)]}
    av = {("integrated_results", "1", "u1"): {"broadcast_at": "2026-08-10T17:00:00+05:30"},
          ("integrated_results", "2", "u2"): {"broadcast_at": None}}
    table, chron = Z.as_filed(fs, {}, metrics, av)
    r = table[("X", "2026-06-30", "CONSOLIDATED", "pat_cr")]
    assert r["as_filed_value"] == 100.0 and r["first_filed_id"] == "1"
    assert r["latest_known_value"] == 90.0 and r["latest_filing_kind"] == "REVISION"
    assert r["revision_status"] == "LATER_VALUE_CHANGED"


def test_duplicate_listing_is_not_a_revision_and_unflagged_later_filing_is_marked():
    import analyze as Z
    fs = [_filing("legacy_results", "a", "UNKNOWN", "ua"), _filing("integrated_results", "b", "ORIGINAL", "ub"),
          _filing("legacy_results", "c", "UNKNOWN", "uc")]
    metrics = {"ua": [_metric("ua", 50.0)], "ub": [_metric("ub", 50.0)], "uc": [_metric("uc", 55.0)]}
    av = {("legacy_results", "a", "ua"): {"broadcast_at": "2026-08-10T17:00:00+05:30"},
          ("integrated_results", "b", "ub"): {"broadcast_at": "2026-08-10T17:05:00+05:30"},
          ("legacy_results", "c", "uc"): {"broadcast_at": "2026-08-25T11:00:00+05:30"}}
    table, chron = Z.as_filed(fs, {}, metrics, av)
    r = table[("X", "2026-06-30", "CONSOLIDATED", "pat_cr")]
    assert r["as_filed_value"] == 50.0 and r["duplicate_listings"] == 1 and not r["duplicate_listing_disagreements"]
    assert r["latest_known_value"] == 55.0 and r["latest_filing_kind"] == "LATER_FILING_UNFLAGGED"


def test_feature_metadata_schema_has_the_required_provenance_fields():
    required = {"period_end", "available_at", "retrieved_at", "source", "pit_class", "data_version",
                "point_in_time_validated"}                                  # POL-02 + the PRD flag
    assert required <= set(P.FEATURE_META_FIELDS)
    assert len(P.FEATURE_META_FIELDS) == len(set(P.FEATURE_META_FIELDS))


def test_period_mapping_candidates_are_only_adjacent_or_year_apart_quarters():
    import analyze as Z
    import compare as C
    D = dt.date
    assert Z.quarter_shift(D(2026, 3, 31), 1) == D(2026, 6, 30) and Z.quarter_shift(D(2026, 3, 31), -4) == D(2025, 3, 31)
    assert Z.quarter_shift(D(2025, 12, 31), 1) == D(2026, 3, 31)
    filed = "2026-08-01T10:00:00+05:30"
    table = {("X", q, "CONSOLIDATED", "pat_cr"): {"as_filed_value": v, "latest_known_value": v, "first_filed_at": filed,
                                                  "revision_status": "NO_LATER_FILING"}
             for q, v in (("2026-06-30", 100.0), ("2026-03-31", 80.0), ("2025-06-30", 70.0), ("2025-09-30", 130.0))}
    quarters = {"2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"}
    rows, _ = Z.compare_trendlyne({("X", "pat_cr", 0): 130.0, ("X", "pat_cr", 1): 100.0}, {"X": "2026-09-18"}, table, [],
                                  C.load_config(), quarters)
    r0 = next(r for r in rows if r["lag"] == 0)           # 130 = the 2025-09-30 value: 3 quarters away -> not a mapping
    assert r0["difference_type"] == "UNRESOLVED"
    r1 = next(r for r in rows if r["lag"] == 1)           # expected 2026-03-31; 100 = the adjacent 2026-06-30 value
    assert r1["difference_type"] == "PERIOD_MAPPING" and "2026-06-30" in r1["explanation"]
