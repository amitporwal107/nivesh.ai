"""When an admin is asked for the day's Kite login (services/kite_live_feed/platform_token.login_needed), and the
GET /api/live/status fields that carry it.

The gap this closes (2026-10-26): the in-app prompt only showed between 08:30 and 15:30, so an admin who opened the app
after the close was never asked, although a login then still lets the feed save the day's closing quotes. Times are IST.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import live_quotes
from services.kite_live_feed import platform_token as pt
from services.kite_live_feed.feed import COL_CLOSE

IST = timezone(timedelta(hours=5, minutes=30))
MON = datetime(2026, 10, 26, tzinfo=IST)       # a Monday
EXPIRED = {"stored": True, "valid_until": "2026-10-25T00:30:00+00:00", "expired": True}
MISSING = {"stored": False, "valid_until": None, "expired": False}
WORKING = {"stored": True, "valid_until": "2026-10-27T00:30:00+00:00", "expired": False}


def at(day: datetime, hh: int, mm: int = 0) -> datetime:
    return day.replace(hour=hh, minute=mm)


def ask(now, token=EXPIRED, state="expired", reason="regular_session", saved=False):
    return pt.login_needed(now, feed_state=state, feed_reason=reason, token=token, close_saved_today=saved)


@pytest.mark.parametrize("hh, mm, reason", [(6, 0, "before_open"), (8, 45, "before_open"), (9, 5, "pre_open"), (11, 0, "regular_session"), (15, 30, "regular_session")])
def test_asked_from_06_00_to_the_close_on_a_trading_day(hh, mm, reason):
    assert ask(at(MON, hh, mm), reason=reason) == (True, "session")


def test_not_asked_before_06_00_when_the_previous_token_is_still_the_issue():
    assert ask(at(MON, 5, 59), reason="before_open") == (False, None)


def test_after_the_close_asked_only_until_the_days_close_is_saved():
    assert ask(at(MON, 18, 0), reason="after_hours", saved=False) == (True, "close_not_saved")
    assert ask(at(MON, 23, 30), reason="after_hours", saved=False) == (True, "close_not_saved")
    assert ask(at(MON, 18, 0), reason="after_hours", saved=True) == (False, None)


@pytest.mark.parametrize("token, state", [(MISSING, "not_connected"), (EXPIRED, "expired"), (WORKING, "expired"), (WORKING, "not_connected")])
def test_a_token_that_does_not_work_counts_as_missing(token, state):
    # A stored, unexpired token that Kite refuses (the feed says expired) still needs the login.
    assert ask(at(MON, 11, 0), token=token, state=state)[0] is True


@pytest.mark.parametrize("state", ["live", "market_closed", "starting", None])
def test_never_asked_while_the_token_works(state):
    assert ask(at(MON, 11, 0), token=WORKING, state=state) == (False, None)
    assert ask(at(MON, 18, 0), token=WORKING, state=state, reason="after_hours") == (False, None)


def test_never_asked_on_weekends_or_holidays():
    sat = MON + timedelta(days=5)
    assert ask(at(sat, 11, 0), reason="weekend") == (False, None)
    assert ask(at(sat, 11, 0), reason=None) == (False, None)            # the clock alone says weekend
    assert ask(at(MON, 11, 0), reason="holiday") == (False, None)
    assert ask(at(MON, 18, 0), reason="holiday") == (False, None)


# ── the status route carries it ───────────────────────────────────────────

class Coll:
    def __init__(self, docs=None):
        self.docs = {d["_id"]: d for d in (docs or [])}

    async def find_one(self, flt, proj=None):
        return self.docs.get(flt.get("_id"))


class DB:
    def __init__(self, close_days=(), token=None):
        self.c = {COL_CLOSE: Coll([{"_id": d} for d in close_days]), pt.COL_TOKEN: Coll([token] if token else [])}

    def __getitem__(self, name):
        return self.c.setdefault(name, Coll())


class Feed:
    def __init__(self, db, status):
        self.db, self._status = db, status

    async def read_status(self):
        return self._status

    async def read_snapshot(self):
        return None


def client(monkeypatch, feed, now):
    async def user(request: Request):
        return {"user_id": "u1"}

    class FrozenDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now

    monkeypatch.setattr(live_quotes, "get_current_user", user)
    monkeypatch.setattr(live_quotes, "get_feed", lambda: feed)
    monkeypatch.setattr(live_quotes, "datetime", FrozenDT)
    app = FastAPI()
    app.include_router(live_quotes.router)
    return TestClient(app)


def test_status_says_a_login_is_needed_after_the_close_until_the_close_is_saved(monkeypatch):
    now = at(MON, 18, 2)
    expired = {"_id": "platform", "user_id": "X", "expires_at": datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)}
    st = {"state": "expired", "session": "closed", "reason": "after_hours"}
    b = client(monkeypatch, Feed(DB(close_days=["2026-10-23"], token=expired), st), now).get("/api/live/status").json()
    assert (b["login_needed"], b["login_why"], b["close_saved_today"]) == (True, "close_not_saved", False)
    assert b["platform_token"]["expired"] is True and "token_enc" not in str(b)

    b = client(monkeypatch, Feed(DB(close_days=["2026-10-23", "2026-10-26"], token=expired), st), now).get("/api/live/status").json()
    assert (b["login_needed"], b["login_why"], b["close_saved_today"]) == (False, None, True)
