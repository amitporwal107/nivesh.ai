"""Tests for /api/data-health pipeline orchestration logic."""
import asyncio
from unittest.mock import patch, AsyncMock

from routes import data_health


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── _run_step (capture success / fail / timeout) ────────────────────────
def test_run_step_captures_success():
    async def _ok():
        return {"upserted": 42}
    res = _run(data_health._run_step("test_step", _ok))
    assert res["ok"] is True
    assert res["step"] == "test_step"
    assert res["result"]["upserted"] == 42


def test_run_step_captures_exception():
    async def _fail():
        raise ValueError("boom")
    res = _run(data_health._run_step("flaky", _fail))
    assert res["ok"] is False
    assert "boom" in res["error"]


def test_run_step_captures_timeout():
    """asyncio.TimeoutError → step marked failed with error='timeout'."""
    orig = data_health._RUN_ALL_TIMEOUT_S
    data_health._RUN_ALL_TIMEOUT_S = 0.1
    try:
        async def _slow():
            await asyncio.sleep(2)
        res = _run(data_health._run_step("slow", _slow))
        assert res["ok"] is False
        assert res["error"] == "timeout"
    finally:
        data_health._RUN_ALL_TIMEOUT_S = orig


# ── End-to-end pipeline state mgmt (mocked steps) ───────────────────────
def test_pipeline_sets_paused_on_full_success():
    """When every step succeeds, _set_paused(True) must fire."""
    from deps import db

    async def _setup():
        await db.system_config.delete_many({"key": "data_pipeline"})
        await db.system_config.delete_many({"key": data_health._RUN_STATE_KEY})

    async def _verify():
        assert await data_health._is_paused() is True
        state = await data_health._read_run_state()
        assert state["running"] is False
        assert state["ok"] is True
        assert len(state["steps"]) == 4
        assert all(s["ok"] for s in state["steps"])

    async def _cleanup():
        await db.system_config.delete_many({"key": "data_pipeline"})
        await db.system_config.delete_many({"key": data_health._RUN_STATE_KEY})

    _run(_setup())
    with patch("scripts.fetch_amfi_navs.run", new=AsyncMock(return_value={"upserted": 100})), \
         patch("services.nav_analytics_sweep.run_analytics_sweep", new=AsyncMock(return_value={"ok": True})), \
         patch("services.nav_analytics_sweep.run_v3_rescore", new=AsyncMock(return_value={"scored": 50})), \
         patch("scripts.mirror_pg_to_mongo.run", new=AsyncMock(return_value={"rows": 1000})):
        _run(data_health._run_pipeline_in_background())
    _run(_verify())
    _run(_cleanup())


def test_pipeline_does_not_pause_on_failure():
    """If any step fails, paused flag stays False."""
    from deps import db

    async def _setup():
        await db.system_config.delete_many({"key": "data_pipeline"})
        await db.system_config.delete_many({"key": data_health._RUN_STATE_KEY})

    async def _ok():
        return {"ok": True}

    async def _fail():
        raise RuntimeError("simulated failure")

    async def _verify():
        assert await data_health._is_paused() is False
        state = await data_health._read_run_state()
        assert state["ok"] is False
        assert state["running"] is False

    async def _cleanup():
        await db.system_config.delete_many({"key": "data_pipeline"})
        await db.system_config.delete_many({"key": data_health._RUN_STATE_KEY})

    _run(_setup())
    with patch("scripts.fetch_amfi_navs.run", new=AsyncMock(side_effect=_ok)), \
         patch("services.nav_analytics_sweep.run_analytics_sweep", new=AsyncMock(side_effect=_fail)), \
         patch("services.nav_analytics_sweep.run_v3_rescore", new=AsyncMock(side_effect=_ok)), \
         patch("scripts.mirror_pg_to_mongo.run", new=AsyncMock(side_effect=_ok)):
        _run(data_health._run_pipeline_in_background())
    _run(_verify())
    _run(_cleanup())


def test_paused_flag_round_trip():
    from deps import db
    _run(data_health._set_paused(True))
    assert _run(data_health._is_paused()) is True
    _run(data_health._set_paused(False))
    assert _run(data_health._is_paused()) is False
    _run(db.system_config.delete_many({"key": "data_pipeline"}))


def test_run_state_round_trip():
    """_write_run_state and _read_run_state should round-trip cleanly."""
    from deps import db
    _run(data_health._write_run_state({
        "running": True, "current_step": "amfi_navs",
        "started_at": "2026-04-26T00:00:00+00:00",
        "steps": [], "ok": None, "finished_at": None, "message": None,
    }))
    state = _run(data_health._read_run_state())
    assert state["running"] is True
    assert state["current_step"] == "amfi_navs"
    assert state["steps"] == []
    _run(db.system_config.delete_one({"key": data_health._RUN_STATE_KEY}))
