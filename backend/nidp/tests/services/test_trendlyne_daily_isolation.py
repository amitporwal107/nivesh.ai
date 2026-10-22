"""trendlyne_fundamentals daily: one failing pass must not stop the builds.

Staging 2026-10-15..19: the p4 pass failed every morning (a label clash, then the provider's
"not subscribed" reply), the job died before `ratios`, and nidp.stock_fundamental_values stayed
empty although the ratio pass r1 was staged for 2,519 companies.
"""
import asyncio

import pytest

from nidp.services.trendlyne_fundamentals import parse, service
from nidp.services.trendlyne_fundamentals.client import TrendlyneError


def _wire(monkeypatch, failing=(), sectors_error=None):
    calls = []

    async def fetch(pass_name, **kw):
        calls.append(("fetch", pass_name))
        if pass_name in failing:
            raise TrendlyneError(f"unexpected reply for pass {pass_name}")
        return {"pass": pass_name}

    async def build(**kw):
        calls.append(("build",))
        return {"built": 1}

    async def build_ratios(**kw):
        calls.append(("ratios",))
        return {"rows_written": 5}

    async def sectors(**kw):
        calls.append(("sectors",))
        if sectors_error:
            raise sectors_error
        return {"written": 0}

    monkeypatch.setattr(service, "fetch", fetch)
    monkeypatch.setattr(service, "build", build)
    monkeypatch.setattr(service, "build_ratios", build_ratios)
    monkeypatch.setattr(service, "sectors", sectors)
    return calls


def test_a_failing_pass_does_not_stop_the_ratio_build(monkeypatch):
    calls = _wire(monkeypatch, failing=("p4",))
    with pytest.raises(TrendlyneError, match="p4"):
        asyncio.run(service.daily())
    # every pass was tried, then both builds and the sectors ran, before the failure surfaced
    assert [c for c in calls if c[0] == "fetch"] == [("fetch", p) for p in parse.DAILY_ORDER]
    assert ("build",) in calls and ("ratios",) in calls and ("sectors",) in calls


def test_the_run_still_fails_so_the_job_log_shows_it(monkeypatch):
    _wire(monkeypatch, failing=("p1", "p4"))
    with pytest.raises(TrendlyneError, match="p1"):   # the first failure is the one reported
        asyncio.run(service.daily())


def test_a_clean_run_returns_every_stage(monkeypatch):
    _wire(monkeypatch)
    out = asyncio.run(service.daily())
    assert set(out) == set(parse.DAILY_ORDER) | {"build", "ratios", "sectors"}


def test_sectors_failure_is_reported_after_the_builds(monkeypatch):
    calls = _wire(monkeypatch, sectors_error=TrendlyneError("not subscribed"))
    with pytest.raises(TrendlyneError, match="not subscribed"):
        asyncio.run(service.daily())
    assert ("ratios",) in calls


def test_a_label_the_provider_gave_to_two_tokens_is_a_trendlyne_error_not_a_crash(monkeypatch):
    import asyncpg

    class Conn:
        async def fetch(self, *a):
            return []

        async def execute(self, *a):
            raise asyncpg.UniqueViolationError("duplicate key value violates unique constraint")

    class Pool:
        def acquire(self):
            outer = self

            class _Ctx:
                async def __aenter__(self_inner):
                    return Conn()

                async def __aexit__(self_inner, *exc):
                    return False
            return _Ctx()

    class Client:
        def call(self, tool, args):
            return "payload"

    async def flush(pool, ledger):
        return None

    monkeypatch.setattr(service, "_flush_ledger", flush)
    monkeypatch.setattr(service, "_parse_values", lambda client, text, what: ({}, {"Operating Profit 6Qtr Ago": {}}))
    with pytest.raises(TrendlyneError, match="Operating Profit 6Qtr Ago"):
        asyncio.run(service._learn_labels(Pool(), Client(), [], ["opqmq6"]))
