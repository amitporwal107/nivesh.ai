"""AD-AL-13 (restart: no repeat, no skip) and AD-AL-14 (outbox: alert event commits with its state change).
Uses the throwaway Postgres. The transport is a fake, labelled MOCK."""
from __future__ import annotations

from autodesk import contracts as C
from autodesk import store
from autodesk.notify import cursor
from autodesk.notify.notifier import Notifier
from tests.autodesk.conftest import run
from tests.autodesk.test_alerts import FakeTransport, Clock

T = "tenant-alerts"


def _n(tr):
    clk = Clock()
    return Notifier(tr, clock=clk.now, sleep=clk.sleep)


async def _emit(pool, typ, **payload):
    async with pool.acquire() as c:
        return await store.emit(c, typ, tenant_id=T, producer="test", payload=payload)


def test_al13_first_run_starts_at_now_then_resumes_without_repeat_or_skip(pg_pool):
    run(_emit(pg_pool, C.EventType.PREMARKET_BLOCKED, status="BLOCKED"))          # history before the notifier existed
    tr = FakeTransport()
    async def go():
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, _n(tr)) == 0                       # history is not replayed
        await _emit(pg_pool, C.EventType.WORKFLOW_FAILED, error="e1")
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, _n(tr)) == 1
        async with pg_pool.acquire() as c:                                        # "restart": a fresh Notifier
            assert await cursor.run_pending(c, _n(tr)) == 0
        await _emit(pg_pool, C.EventType.MARKET_DATA_STALE)
        await _emit(pg_pool, C.EventType.AGENT_UNHEALTHY)
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, _n(tr)) == 2
    run(go())
    assert len(tr.sent) == 3 and "FAILED" in tr.sent[0] and "STALE" in tr.sent[1] and "UNHEALTHY" in tr.sent[2]


def test_al13b_failed_delivery_does_not_lose_or_repeat_the_event(pg_pool):
    from autodesk.notify.transport import SendResult
    tr = FakeTransport([SendResult(ok=False, permanent=True, reason="invalid_auth")])
    async def go():
        async with pg_pool.acquire() as c:
            await cursor.run_pending(c, _n(FakeTransport()))                      # position the cursor
        await _emit(pg_pool, C.EventType.WORKFLOW_FAILED, error="e2")
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, _n(tr)) == 1                       # attempted, recorded as failed
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, _n(tr)) == 0                       # not retried forever
    run(go())
    assert len(tr.sent) == 1


def test_al13c_disabled_notifier_leaves_the_cursor_alone(pg_pool):
    async def go():
        async with pg_pool.acquire() as c:
            await cursor.run_pending(c, _n(FakeTransport()))
            before = await c.fetchval("SELECT last_seq FROM autodesk.event_cursors WHERE consumer=$1", cursor.CONSUMER)
        await _emit(pg_pool, C.EventType.WORKFLOW_FAILED, error="e3")
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, Notifier(None)) == 0
            assert await c.fetchval("SELECT last_seq FROM autodesk.event_cursors WHERE consumer=$1",
                                    cursor.CONSUMER) == before
    run(go())


def test_al14_rollback_leaves_no_alert(pg_pool):
    tr = FakeTransport()
    async def go():
        async with pg_pool.acquire() as c:
            await cursor.run_pending(c, _n(FakeTransport()))      # drain what earlier tests left pending
        try:
            async with pg_pool.acquire() as c:
                async with c.transaction():
                    await store.emit(c, C.EventType.WORKFLOW_FAILED, tenant_id=T, producer="test", payload={"error": "x"})
                    raise RuntimeError("state change failed")
        except RuntimeError:
            pass
        async with pg_pool.acquire() as c:
            assert await cursor.run_pending(c, _n(tr)) == 0
    run(go())
    assert tr.sent == []
