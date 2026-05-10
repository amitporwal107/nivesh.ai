"""Unit tests for nidp.quality.replay — engine + policy + failure_injector.

These tests do not require a live Postgres connection — they exercise
the pure-Python pieces (policy math, failure planning, config validation,
trading-day filter) and use a stubbed connection where needed.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nidp.quality.replay.policy import (
    ScoringPolicy, get_policy, list_policies, _BUILTIN,
)
from nidp.quality.replay.failure_injector import (
    plan_failures, FAILURE_TYPES,
)
from nidp.quality.replay.engine import (
    ReplayConfig, list_trading_days, DateOutcome,
)


# ─── ScoringPolicy ──────────────────────────────────────────────────
class TestScoringPolicy:
    def test_legacy_weights_sum_to_one(self):
        p = _BUILTIN["legacy"]
        assert p.weights_sum() == pytest.approx(1.0, abs=0.001)

    def test_v1_weights_sum_to_one(self):
        p = _BUILTIN["v1"]
        assert p.weights_sum() == pytest.approx(1.0, abs=0.001)

    def test_v1_score_matches_prd_formula(self):
        # PRD: Q = 0.30A + 0.25C + 0.20L + 0.15F + 0.10K
        p = _BUILTIN["v1"]
        q = p.score(accuracy=100, consistency=100, completeness=100,
                    freshness=100, confidence=100)
        assert q == pytest.approx(100.0)

        q2 = p.score(accuracy=80, consistency=70, completeness=60,
                     freshness=50, confidence=40)
        # 0.30*80 + 0.25*70 + 0.20*60 + 0.15*50 + 0.10*40 = 24 + 17.5 + 12 + 7.5 + 4 = 65
        assert q2 == pytest.approx(65.0)

    def test_legacy_score_matches_existing_formula(self):
        # legacy: Q = 0.40A + 0.30C + 0.15P + 0.10F + 0.05U
        p = _BUILTIN["legacy"]
        q = p.score(accuracy=80, consistency=70, completeness=60,
                    freshness=50, confidence=40)
        # 0.40*80 + 0.30*70 + 0.15*60 + 0.10*50 + 0.05*40 = 32 + 21 + 9 + 5 + 2 = 69
        assert q == pytest.approx(69.0)

    def test_certify_tiers(self):
        p = _BUILTIN["v1"]
        assert p.certify(99.5) == "GOLD"
        assert p.certify(99.0) == "GOLD"
        assert p.certify(98.0) == "SILVER"
        assert p.certify(95.0) == "SILVER"
        assert p.certify(94.9) == "REVIEW"
        assert p.certify(90.0) == "REVIEW"
        assert p.certify(89.9) == "REJECTED"

    def test_publish_decision(self):
        p = _BUILTIN["v1"]
        # publish_min=95, review_min=90, confidence_min=90
        assert p.publish_decision(98.0, 95.0) == "PUBLISH"
        assert p.publish_decision(94.0, 95.0) == "REVIEW"   # Q < publish_min but >= review_min
        assert p.publish_decision(89.0, 95.0) == "REJECT"   # Q < review_min
        assert p.publish_decision(99.0, 80.0) == "REVIEW"   # K below conf_min
        assert p.publish_decision(99.0, None) == "PUBLISH"  # K unknown → ignore

    def test_as_dict_round_trip(self):
        p = _BUILTIN["v1"]
        d = p.as_dict()
        assert d["version"] == "v1"
        assert d["w_accuracy"] == 0.30


@pytest.mark.asyncio
class TestPolicyDB:
    async def test_get_policy_falls_back_to_builtin_on_no_conn(self):
        p = await get_policy(None, "v1")
        assert p.version == "v1"

    async def test_get_policy_falls_back_when_table_missing(self):
        import asyncpg
        conn = MagicMock()
        conn.fetchrow = AsyncMock(side_effect=asyncpg.UndefinedTableError("no table"))
        p = await get_policy(conn, "legacy")
        assert p.version == "legacy"

    async def test_get_policy_unknown_raises(self):
        with pytest.raises(ValueError):
            await get_policy(None, "doesnotexist")

    async def test_list_policies_builtin(self):
        ps = await list_policies(None)
        versions = {p.version for p in ps}
        assert {"v1", "legacy"}.issubset(versions)


# ─── failure_injector ───────────────────────────────────────────────
class TestFailureInjector:
    def test_plan_deterministic_with_seed(self):
        a = plan_failures(date(2026, 5, 1), "mf", seed=42, rate=0.5)
        b = plan_failures(date(2026, 5, 1), "mf", seed=42, rate=0.5)
        assert [f.failure_type for f in a] == [f.failure_type for f in b]

    def test_zero_rate_yields_nothing(self):
        out = plan_failures(date(2026, 5, 1), "equity", seed=1, rate=0.0)
        assert out == []

    def test_full_rate_injects_all_types(self):
        out = plan_failures(date(2026, 5, 1), "equity", seed=1, rate=1.0)
        types = {f.failure_type for f in out}
        assert types == set(FAILURE_TYPES)

    def test_unknown_domain_uses_default_table(self):
        out = plan_failures(date(2026, 5, 1), "macro", seed=7, rate=1.0)
        assert all(f.target_table == "nidp.prices_eod" for f in out)


# ─── trading-day filter ─────────────────────────────────────────────
@pytest.mark.asyncio
class TestTradingDays:
    async def test_no_conn_skips_weekends(self):
        # 2026-05-01 was Fri; 2-3 are Sat-Sun; 4 is Mon
        days = await list_trading_days(None, date(2026, 5, 1), date(2026, 5, 4))
        assert days == [date(2026, 5, 1), date(2026, 5, 4)]

    async def test_include_weekends(self):
        days = await list_trading_days(
            None, date(2026, 5, 1), date(2026, 5, 4), skip_weekends=False,
        )
        assert len(days) == 4

    async def test_filters_holidays_when_table_present(self):
        import asyncpg
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[
            {"holiday_date": date(2026, 5, 1)},  # holiday
        ])
        days = await list_trading_days(conn, date(2026, 5, 1), date(2026, 5, 4))
        assert date(2026, 5, 1) not in days
        assert date(2026, 5, 4) in days

    async def test_falls_back_when_holidays_missing(self):
        import asyncpg
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=asyncpg.UndefinedTableError("no holidays"))
        days = await list_trading_days(conn, date(2026, 5, 1), date(2026, 5, 4))
        assert date(2026, 5, 1) in days
        assert date(2026, 5, 4) in days


# ─── ReplayConfig ───────────────────────────────────────────────────
class TestReplayConfig:
    def test_minimal_valid(self):
        cfg = ReplayConfig(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 5),
            domains=["mf"],
        )
        assert cfg.policy_version == "v1"
        assert cfg.parallel == 4

    def test_default_domains(self):
        cfg = ReplayConfig(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 5),
            domains=[],
        )
        assert cfg.domains == ["mf", "equity"]

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="end_date"):
            ReplayConfig(
                start_date=date(2026, 1, 5),
                end_date=date(2026, 1, 1),
                domains=["mf"],
            )

    def test_unknown_domain_raises(self):
        with pytest.raises(ValueError, match="unknown domain"):
            ReplayConfig(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 5),
                domains=["macro"],
            )

    def test_parallel_bounds(self):
        with pytest.raises(ValueError, match="parallel"):
            ReplayConfig(
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 5),
                domains=["mf"], parallel=0,
            )
        with pytest.raises(ValueError, match="parallel"):
            ReplayConfig(
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 5),
                domains=["mf"], parallel=100,
            )

    def test_failure_rate_bounds(self):
        with pytest.raises(ValueError):
            ReplayConfig(
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 5),
                domains=["mf"], failure_rate=1.5,
            )


# ─── DateOutcome dataclass shape ────────────────────────────────────
class TestDateOutcome:
    def test_defaults(self):
        d = DateOutcome(target_date=date(2026, 5, 1), domain="mf")
        assert d.block_findings == 0
        assert d.gate_outcome is None
        assert d.error is None
