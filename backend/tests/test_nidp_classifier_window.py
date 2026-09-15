"""The classifier's fetch window must be able to reach older rows.

A hard-coded 30-day window left 42,359 unclassified announcements permanently out of reach:
every run asked only for the last 30 days, so nothing older was ever retried.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nidp.services.announcement_classifier import db as D  # noqa: E402


def _capture(monkeypatch, **kwargs):
    seen = {}

    class Conn:
        async def fetch(self, sql, *args):
            seen["sql"], seen["args"] = sql, args
            return []

    class Pool:
        def acquire(self):
            class A:
                async def __aenter__(self):
                    return Conn()

                async def __aexit__(self, *_):
                    return False
            return A()

    async def pool():
        return Pool()

    monkeypatch.setattr(D, "get_pool", pool)
    asyncio.run(D.fetch_unclassified(**kwargs))
    return seen


def test_the_window_is_a_parameter_not_a_hardcoded_30_days(monkeypatch):
    seen = _capture(monkeypatch, limit=200, days=400)
    assert seen["args"] == (200, 400)
    assert "INTERVAL '30 days'" not in seen["sql"]


def test_zero_days_means_any_age(monkeypatch):
    seen = _capture(monkeypatch, limit=50, days=0)
    assert seen["args"] == (50, 0)
    assert "$2::int = 0 OR" in seen["sql"]      # the window predicate is skipped entirely


def test_default_is_still_30_days_and_oldest_first(monkeypatch):
    seen = _capture(monkeypatch, limit=200)
    assert seen["args"] == (200, 30)
    assert "ORDER BY filed_at ASC" in seen["sql"]
