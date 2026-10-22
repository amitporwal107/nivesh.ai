"""The indicator engine's default target date: the latest session with prices, not calendar yesterday."""
import asyncio
from datetime import date

from nidp.services.technical_indicator_engine.__main__ import default_target_date


class _Pool:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    async def fetchval(self, sql):
        assert "nidp.prices_eod" in sql and "series = 'EQ'" in sql
        if self.error:
            raise self.error
        return self.value


def _run(pool, today):
    return asyncio.run(default_target_date(pool, today=today))


def test_monday_run_targets_friday_not_sunday():
    # Monday 2026-10-19: Friday's session is the latest loaded; "yesterday" would be Sunday the 18th.
    assert _run(_Pool(date(2026, 10, 16)), date(2026, 10, 19)) == date(2026, 10, 16)


def test_normal_weekday_targets_the_day_just_loaded():
    assert _run(_Pool(date(2026, 10, 19)), date(2026, 10, 19)) == date(2026, 10, 19)


def test_empty_price_table_falls_back_to_yesterday():
    assert _run(_Pool(None), date(2026, 10, 19)) == date(2026, 10, 18)


def test_unreadable_price_table_falls_back_to_yesterday():
    assert _run(_Pool(error=RuntimeError("down")), date(2026, 10, 19)) == date(2026, 10, 18)


def test_a_date_after_today_is_not_used():
    assert _run(_Pool(date(2026, 10, 25)), date(2026, 10, 19)) == date(2026, 10, 18)
