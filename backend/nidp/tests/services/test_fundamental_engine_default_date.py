"""The fundamental engine's default target date: the latest date the indicator engine has loaded."""
import asyncio
from datetime import date

from nidp.services.fundamental_engine.__main__ import default_target_date


class _Pool:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    async def fetchval(self, sql):
        assert "nidp.stock_features_daily" in sql
        if self.error:
            raise self.error
        return self.value


def _run(pool, today):
    return asyncio.run(default_target_date(pool, today=today))


def test_monday_run_targets_the_last_loaded_session_not_sunday():
    # Staging 2026-10-19: "yesterday" was Sunday the 18th, the engine found no rows and filled nothing.
    assert _run(_Pool(date(2026, 10, 16)), date(2026, 10, 19)) == date(2026, 10, 16)


def test_normal_weekday_targets_the_day_just_loaded():
    assert _run(_Pool(date(2026, 10, 19)), date(2026, 10, 19)) == date(2026, 10, 19)


def test_empty_or_unreadable_table_falls_back_to_yesterday():
    assert _run(_Pool(None), date(2026, 10, 19)) == date(2026, 10, 18)
    assert _run(_Pool(error=RuntimeError("down")), date(2026, 10, 19)) == date(2026, 10, 18)


def test_a_date_after_today_is_not_used():
    assert _run(_Pool(date(2026, 10, 25)), date(2026, 10, 19)) == date(2026, 10, 18)
