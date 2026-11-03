"""DQ foundation (PR-1) — unit cases from test_reports/dq_foundation_TESTCASES.md (QS-*, G1-*, GE-1, AS-1).

No database: a recording fake connection captures every SQL statement and its arguments, so these cases prove what
the score, the gate, the Gate 1 flag and the two writers SEND. The SQL itself is exercised against a real, throwaway
Postgres in test_dq_foundation_pg.py. Coroutines run under asyncio.run (the backend image has no pytest-asyncio).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from nidp.shared import run_context
from nidp.shared.validation import quality_score as qs
from nidp.shared.validation.consistency import ConsistencyDimension, ConsistencyFinding
from nidp.shared.validation.rules import FailureClass, Severity

D = dt.date(2026, 10, 27)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _finding(rule: str, sev: Severity) -> ConsistencyFinding:
    return ConsistencyFinding(rule_name=rule, dimension=ConsistencyDimension.INTERNAL, severity=sev,
                              failure_class=FailureClass.FIX, message="m")


class FakeConn:
    """Records (sql, args); answers by the first matching substring in `answers`."""

    def __init__(self, answers=None):
        self.calls: list[tuple[str, tuple]] = []
        self.answers = answers or {}

    def _answer(self, sql, default):
        for key, val in self.answers.items():
            if key in sql:
                return val
        return default

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self._answer(sql, None)

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self._answer(sql, [])

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return self._answer(sql, 0)

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "OK"

    def sql_with(self, needle):
        return [(s, a) for s, a in self.calls if needle in s]


# ── QS-1, QS-6: the domain's ingesters, never LIKE '<domain>%' ───────────────────────────────

def test_qs1_equity_ingesters():
    assert qs.domain_ingesters("equity") == ["bhavcopy", "delivery", "index_close", "corporate_actions",
                                             "nse_equity_master", "nse_shareholding", "bulk_deals", "block_deals"]
    # Scope (owner, 29 Oct): only the trading product's data gets the corrected scoring.
    assert qs.is_scored_domain("equity") is True
    assert qs.is_scored_domain("mf") is False and qs.is_scored_domain("all") is False
    assert qs.domain_ingesters("mf") == [] and qs.domain_ingesters("nonsense") == []


def test_scope_mf_keeps_the_earlier_scoring():
    run_id = uuid.uuid4()
    conn = _score_conn(**{
        "FROM nidp.consistency_runs": {"run_id": run_id, "rules_run": 6, "rules_failed": 1},
        "FROM nidp.consistency_findings": [{"rule_name": "mf.nav_temporal", "severity": "WARN"}],
        "max(started_at) AS latest": {"latest": dt.datetime(2026, 10, 27, 14, 0, tzinfo=dt.timezone.utc)},
    })
    score = asyncio.run(qs.compute_quality_score(conn, D, "mf"))
    acc = conn.sql_with("v_latest_validation")[0]
    assert "LIKE" in acc[0] and acc[1] == (D, "mf", "mf%")                 # earlier accuracy filter
    assert conn.sql_with("max(started_at) AS latest")                       # earlier freshness query
    assert not conn.sql_with("min(started_at) AS first_ok")
    assert score.consistency == pytest.approx(100 * 5 / 6, abs=1e-3)        # a WARN still costs a full point
    assert score.freshness == 100.0                                         # 19:30 IST, before 22:00 IST


def test_scope_gate_mf_keeps_the_earlier_block_filter():
    from nidp.shared.quality_gate import QualityGate
    conn = FakeConn({"FROM nidp.v_data_certification": {"overall_score": 99.2, "confidence_score": 95.0,
                                                         "certification": "GOLD", "publish_decision": "AUTO_PUBLISH"}})
    asyncio.run(QualityGate(conn).evaluate(D, "mf"))
    q = conn.sql_with("FROM nidp.validation_findings vf")[0]
    assert "LIKE" in q[0] and q[1] == (D, "mf", "mf%")


def _score_conn(**extra):
    answers = {
        "FROM nidp.v_latest_validation": {"passed": 7, "total": 8},
        "FROM nidp.mf_nav_daily": {"total": 0, "filled": 0, "with_lineage": 0},
        "FROM nidp.prices_eod": {"total": 100, "filled": 100, "with_lineage": 100},
        "count(*) FILTER (WHERE failure_class = 'BLOCK')": {"block_findings": 0, "passed_runs": 1, "total_runs": 1},
    }
    answers.update(extra)
    return FakeConn(answers)


def test_qs1_qs6_accuracy_and_freshness_get_the_ingester_list():
    conn = _score_conn()
    asyncio.run(qs.compute_quality_score(conn, D, "equity", consistency_input=qs.ConsistencyInput(rules_run=8)))
    acc = conn.sql_with("v_latest_validation")
    assert acc and "LIKE" not in acc[0][0] and acc[0][1] == (D, qs.domain_ingesters("equity"))
    fresh = conn.sql_with("min(started_at) AS first_ok")
    assert fresh and fresh[0][1] == (D, qs.domain_ingesters("equity"))


# ── QS-2 … QS-5: consistency weighted by severity ─────────────────────────────────────────────

def test_qs2_one_warn_rule():
    inp = qs.ConsistencyInput.from_findings(8, [_finding("equity.price_temporal_change", Severity.WARN)] * 3)
    assert inp.fired == {"equity.price_temporal_change": "WARN"}
    assert qs.consistency_score(inp) == pytest.approx(98.75)


def test_qs3_error_plus_critical():
    inp = qs.ConsistencyInput.from_findings(8, [_finding("a", Severity.ERROR), _finding("b", Severity.CRITICAL)])
    assert qs.consistency_score(inp) == pytest.approx(81.25)


def test_worst_severity_per_rule_wins():
    inp = qs.ConsistencyInput.from_findings(4, [_finding("a", Severity.WARN), _finding("a", Severity.ERROR),
                                                _finding("a", Severity.INFO)])
    assert inp.fired == {"a": "ERROR"}


def test_qs4_crashed_rule_weighs_a_full_point():
    assert qs.consistency_score(qs.ConsistencyInput(rules_run=8, fired={}, crashed=1)) == pytest.approx(87.5)


def test_qs4_db_path_counts_crashed_rules():
    run_id = uuid.uuid4()
    conn = _score_conn(**{
        "FROM nidp.consistency_runs": {"run_id": run_id, "rules_run": 8, "rules_failed": 2},
        "FROM nidp.consistency_findings": [{"rule_name": "a", "severity": "WARN"}],
    })
    score = asyncio.run(qs.compute_quality_score(conn, D, "equity"))
    # one WARN rule (0.1) + one rule counted failed with no finding row (crashed, 1.0) = 1.1 / 8
    assert score.consistency == pytest.approx(100 * (1 - 1.1 / 8), abs=1e-3)
    assert conn.sql_with("consistency_findings")[0][1] == (run_id,)


def test_qs5_no_consistency_run_keeps_95():
    conn = _score_conn()
    score = asyncio.run(qs.compute_quality_score(conn, D, "equity"))
    assert score.consistency == 95.0 and score.cross_source_agreement is None


def test_qs7_in_memory_input_matches_db_path():
    findings = [_finding("a", Severity.WARN), _finding("b", Severity.ERROR)]
    mem = asyncio.run(qs.compute_quality_score(_score_conn(), D, "equity",
                                               consistency_input=qs.ConsistencyInput.from_findings(8, findings)))
    db = asyncio.run(qs.compute_quality_score(_score_conn(**{
        "FROM nidp.consistency_runs": {"run_id": uuid.uuid4(), "rules_run": 8, "rules_failed": 2},
        "FROM nidp.consistency_findings": [{"rule_name": "a", "severity": "WARN"},
                                           {"rule_name": "b", "severity": "ERROR"}],
    }), D, "equity"))
    assert mem.consistency == db.consistency == pytest.approx(100 * (1 - 0.6 / 8), abs=1e-3)


def test_qs8_mf_critical_rule_costs_the_full_weight():
    inp = qs.ConsistencyInput.from_findings(6, [_finding("mf.ter_direct_lt_regular", Severity.CRITICAL)])
    assert qs.consistency_score(inp) == pytest.approx(100 * (1 - 1 / 6))


# ── Freshness: each feed's FIRST arrival against its own deadline ─────────────────────────────

def test_freshness_on_time_feeds_score_100():
    runs = {"bhavcopy": dt.datetime(2026, 10, 27, 19, 2, tzinfo=IST),
            "delivery": dt.datetime(2026, 10, 28, 10, 31, tzinfo=IST)}     # D+1 morning is on time for delivery
    assert qs.freshness_from_first_runs(runs, D) == 100.0


def test_freshness_three_hours_late_is_50():
    runs = {"bhavcopy": dt.datetime(2026, 10, 27, 23, 0, tzinfo=IST)}   # deadline 20:00 IST
    assert qs.freshness_from_first_runs(runs, D) == pytest.approx(50.0)


def test_freshness_naive_timestamps_are_utc():
    runs = {"bhavcopy": dt.datetime(2026, 10, 27, 13, 30)}             # 19:00 IST
    assert qs.freshness_from_first_runs(runs, D) == 100.0


def test_freshness_nothing_arrived_is_0():
    assert qs.freshness_from_first_runs({}, D) == 0.0


# ── QualityGate: BLOCK count from the domain's own ingesters ─────────────────────────────────

def test_gate_block_query_uses_the_ingester_list():
    from nidp.shared.quality_gate import QualityGate
    conn = FakeConn({"FROM nidp.v_data_certification": {"overall_score": 99.0, "confidence_score": 95.0,
                                                         "certification": "GOLD", "publish_decision": "AUTO_PUBLISH"}})
    decision = asyncio.run(QualityGate(conn).evaluate(D, "equity"))
    q = conn.sql_with("FROM nidp.validation_findings vf")
    assert q and "LIKE" not in q[0][0] and q[0][1] == (D, qs.domain_ingesters("equity"))
    assert decision.outcome == "PASS"


# ── G1-1 … G1-4: the backfill flag comes from the invocation, not the date's age ─────────────

def test_g1_default_is_not_backfill(monkeypatch):
    monkeypatch.delenv("NIDP_BACKFILL", raising=False)
    assert run_context.is_backfill_run() is False


def test_g1_backfill_context_sets_and_resets(monkeypatch):
    monkeypatch.delenv("NIDP_BACKFILL", raising=False)
    with run_context.backfill_context():
        assert run_context.is_backfill_run() is True
    assert run_context.is_backfill_run() is False
    with pytest.raises(RuntimeError):
        with run_context.backfill_context():
            raise RuntimeError("boom")
    assert run_context.is_backfill_run() is False


def test_g1_env_flag(monkeypatch):
    monkeypatch.setenv("NIDP_BACKFILL", "1")
    assert run_context.is_backfill_run() is True


def test_g1_stale_check_runs_for_a_live_run_and_skips_for_a_backfill():
    from nidp.shared.dq.gate1_ingestion import IngestionGate
    old = dt.date.today() - dt.timedelta(days=10)
    conn = FakeConn({"FROM dq.feed_sla": {"row_count_min": 1, "row_count_max": None}})
    live = asyncio.run(IngestionGate(feed="bhavcopy", row_count=5, is_backfill=False)._checks(conn, old))
    backfill = asyncio.run(IngestionGate(feed="bhavcopy", row_count=5, is_backfill=True)._checks(conn, old))
    stale = [c for c in live if c.name == "G1-UNIV-004"]
    assert stale and stale[0].passed is False                      # 10 days old, a live run: AMBER
    assert "G1-UNIV-004" not in [c.name for c in backfill]


def test_g1_5_floor_comes_from_feed_sla():
    from nidp.shared.dq.gate1_ingestion import IngestionGate
    conn = FakeConn({"FROM dq.feed_sla": {"row_count_min": 25000, "row_count_max": None}})
    checks = asyncio.run(IngestionGate(feed="fno_bhavcopy", row_count=24000)._checks(conn, D))
    row = [c for c in checks if c.name == "G1-UNIV-001"][0]
    assert row.passed is False and row.details["floor"] == 25000


def test_g1_4_backfill_runner_wraps_the_ingester_call(monkeypatch):
    from nidp import backfill as bf
    seen = {}

    async def fake_run(target_date):
        seen["flag"] = run_context.is_backfill_run()

    monkeypatch.delenv("NIDP_BACKFILL", raising=False)
    monkeypatch.setattr(bf.importlib, "import_module", lambda path: SimpleNamespace(run=fake_run))

    async def never_done(*a, **k):
        return False

    monkeypatch.setattr(bf, "already_succeeded", never_done)
    spec = SimpleNamespace(name="bhavcopy", module_path="x", needs_date=True)
    report = bf.BackfillReport()
    asyncio.run(bf._run_one(spec, D, skip_existing=False, report=report))
    assert seen == {"flag": True} and report.runs_ok == 1
    assert run_context.is_backfill_run() is False


# ── GE-1: Great Expectations findings carry every NOT NULL column ─────────────────────────────

def test_ge1_insert_names_the_real_columns():
    from nidp.services.quality_gate import great_expectations_runner as ge
    conn = FakeConn()
    result = {"findings": [{
        "success": False, "unexpected_percent": 30.0, "expectation_type": "expect_column_values_to_not_be_null",
        "message": "nulls", "kwargs": {"column": "close_price"}, "unexpected_count": 9, "column": "close_price",
        "columns": None, "element_count": 30, "partial_unexpected_list": [None],
    }, {"success": True}]}
    run_id = uuid.uuid4()
    n = asyncio.run(ge._persist_findings(conn, run_id, "bhavcopy", "2026-10-27", result))
    assert n == 1
    sql, args = conn.sql_with("INSERT INTO nidp.validation_findings")[0]
    for col in ("finding_id", "validation_id", "job_run_id", "failure_class", "sample_rows"):
        assert col in sql
    assert "sample_payload" not in sql
    assert isinstance(args[0], uuid.UUID) and args[1] == run_id and args[2] == run_id
    assert args[4] == D and args[6] == "CRITICAL"


# ── AS-1: the validation runner writes asset = ingester ───────────────────────────────────────

def test_as1_runner_writes_the_asset(monkeypatch):
    from nidp.shared.validation import runner
    conn = FakeConn()

    class Pool:
        def acquire(self):
            class Ctx:
                async def __aenter__(self_inner):
                    return conn

                async def __aexit__(self_inner, *a):
                    return False
            return Ctx()

    async def get_pool():
        return Pool()

    monkeypatch.setattr(runner, "get_pool", get_pool)
    monkeypatch.setattr(runner, "get_rules", lambda ingester: [])
    asyncio.run(runner.run_validation(ingester="bhavcopy", target_date=D, job_run_id=uuid.uuid4()))
    sql, args = conn.sql_with("INSERT INTO nidp.validation_runs")[0]
    assert "asset" in sql and args[2] == "bhavcopy"
