"""`study/heartbeat.py` — the observability a 7.8-hour unattended run needs.

The guards are the part that must be tested rather than assumed: their whole purpose is to abort
before the RUN endangers the HOST, and a guard that silently never fires is worse than none, because
it buys false confidence. Every one is asserted to actually raise.
"""
from __future__ import annotations

import json

import pytest

from research.charting.study.heartbeat import FailFast, Heartbeat, ResourceGuard


@pytest.fixture()
def hb(tmp_path):
    return Heartbeat(tmp_path, echo=False, throttle_seconds=0)


# ── progress and liveness ───────────────────────────────────────────────────────────────────────

def test_status_file_answers_where_it_is_and_whether_it_is_moving(hb, tmp_path):
    hb.stage("extraction")
    hb.progress(500, 2406, "symbols")
    s = json.loads((tmp_path / "run_status.json").read_text())
    assert s["state"] == "running"
    assert s["stage"] == "extraction"
    assert s["progress"] == {"done": 500, "total": 2406, "unit": "symbols"}
    assert s["resources"]["rss_gb"] > 0
    assert s["pid"] > 0


def test_completed_stages_record_how_long_they_really_took(hb, tmp_path):
    hb.stage("extraction")
    hb.stage("pricing")
    hb.finish("COMPLETE")
    s = json.loads((tmp_path / "run_status.json").read_text())
    assert [x["stage"] for x in s["stages_completed"]] == ["extraction", "pricing"]
    assert all("seconds" in x for x in s["stages_completed"])
    assert s["state"] == "COMPLETE" and "total_minutes" in s


def test_the_status_file_is_never_seen_half_written(hb, tmp_path):
    """Written to a temp path and renamed, so a `cat` during a write cannot catch a partial file —
    the whole point of a status file is that it is readable at an arbitrary moment."""
    for i in range(30):
        hb.progress(i, 30, "chunks")
        json.loads((tmp_path / "run_status.json").read_text())   # must always parse
    assert not list(tmp_path.glob("*.tmp")), "a temp file was left behind"


def test_the_log_is_an_append_only_narrative(hb, tmp_path):
    hb.stage("extraction")
    hb.note("symbols", 2406)
    hb.stage("pricing")
    lines = (tmp_path / "run.log").read_text().splitlines()
    assert any("[stage] extraction" in l for l in lines)
    assert any("symbols = 2406" in l for l in lines)
    assert any("[done] extraction" in l for l in lines)


# ── the guards must actually fire ───────────────────────────────────────────────────────────────

def test_the_rss_guard_aborts_the_run_before_the_host_is_at_risk(tmp_path):
    """Prod Postgres runs on this box. The 2026-07-17 incident recorded in `ray_day_backfill.py`
    was an OOM that took SSH, code-server and prod Postgres' host down — this guard exists so the
    study aborts instead."""
    hb = Heartbeat(tmp_path, echo=False, max_rss_gb=0.0001, min_disk_gb=0.0)
    with pytest.raises(ResourceGuard, match="RSS"):
        hb.check_resources()


def test_the_disk_guard_aborts_before_filling_the_host(tmp_path):
    hb = Heartbeat(tmp_path, echo=False, max_rss_gb=999.0, min_disk_gb=9e9)
    with pytest.raises(ResourceGuard, match="disk free"):
        hb.check_resources()


def test_the_guards_pass_quietly_under_normal_conditions(tmp_path):
    """A guard that fires spuriously would abort a good 8-hour run, which is its own failure."""
    hb = Heartbeat(tmp_path, echo=False, max_rss_gb=999.0, min_disk_gb=0.0)
    hb.check_resources()


# ── fail-fast gates ─────────────────────────────────────────────────────────────────────────────

def test_a_failing_gate_stops_the_run_and_says_why(hb, tmp_path):
    with pytest.raises(FailFast, match="0 families"):
        hb.require("families present", False, "0 families in post_sealed")
    s = json.loads((tmp_path / "run_status.json").read_text())
    assert s["gates"][-1] == {"gate": "families present", "passed": False,
                              "detail": "0 families in post_sealed", "at": s["gates"][-1]["at"]}


def test_a_passing_gate_is_recorded_as_evidence_not_silence(hb, tmp_path):
    """So the finished run can show WHICH checks ran, not merely that nothing complained."""
    hb.require("events exist", True, "19,388 events across 3 families")
    s = json.loads((tmp_path / "run_status.json").read_text())
    assert s["gates"] == [{"gate": "events exist", "passed": True,
                           "detail": "19,388 events across 3 families", "at": s["gates"][0]["at"]}]


def test_finish_records_a_failure_state_too(hb, tmp_path):
    hb.stage("pricing")
    hb.finish("ABORTED", "ResourceGuard: RSS ceiling exceeded")
    s = json.loads((tmp_path / "run_status.json").read_text())
    assert s["state"] == "ABORTED"
    assert "RSS ceiling" in s["detail"]


def test_no_study_metric_reaches_the_log(hb, tmp_path):
    """`execute.py`'s CLI must never print a metric. This module records run bookkeeping —
    counts, stages, resources — and must not become a back door for results."""
    hb.stage("report")
    hb.note("families", ["RECTANGLE", "SUPPORT_RESISTANCE", "HH_HL"])
    text = (tmp_path / "run.log").read_text().lower()
    for banned in ("hit_rate", "net_return", "expectancy", "profit_factor", "auc", "percentile"):
        assert banned not in text
