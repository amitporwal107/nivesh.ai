"""Unit tests for `services.brokers.sessions` — the broker session lifecycle.

Offline: an in-memory fake stands in for Mongo (`FakeDb`, also used by
test_broker_native_routes.py) and tokens are made up. Nothing here talks to
a real broker; the expiry rules are checked against the times the brokers'
API documentation states, not against a live session.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from services import pii_security as pii
from services.brokers import sessions
from services.brokers.base import AccessToken

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


# ── In-memory stand-in for the Mongo collections these modules touch ─────
def _project(doc, proj):
    doc = dict(doc)
    doc.pop("_id", None)
    wanted = [k for k, v in (proj or {}).items() if v]
    return {k: doc[k] for k in wanted if k in doc} if wanted else doc


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        return self._docs if length is None else self._docs[:length]


class FakeCollection:
    """Equality-only matching; like Mongo, `{"field": None}` also matches a
    document that has no such field."""

    def __init__(self):
        self.docs: list[dict] = []

    def _matching(self, query):
        return [d for d in self.docs if all(d.get(k) == v for k, v in query.items())]

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        doc["_id"] = object()  # Mongo adds `_id` to the caller's dict

    async def find_one(self, query, proj=None, sort=None):
        rows = self._matching(query)
        for key, direction in reversed(sort or []):
            rows.sort(key=lambda d: d.get(key) or "", reverse=direction < 0)
        return _project(rows[0], proj) if rows else None

    def find(self, query, proj=None):
        return _Cursor([_project(d, proj) for d in self._matching(query)])

    async def update_one(self, query, update):
        for d in self._matching(query)[:1]:
            d.update(update["$set"])

    async def delete_one(self, query):
        for d in self._matching(query)[:1]:
            self.docs.remove(d)

    async def delete_many(self, query):
        for d in self._matching(query):
            self.docs.remove(d)


class FakeDb:
    def __init__(self):
        self.broker_accounts = FakeCollection()
        self.broker_oauth_states = FakeCollection()
        self.user_sessions = FakeCollection()
        self.holdings = FakeCollection()


@pytest.fixture(autouse=True)
def _throwaway_pii_key(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(pii, "_cached_key", None)


def run(coro):
    return asyncio.run(coro)


def make_jwt(payload: dict) -> str:
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'HS256', 'typ': 'JWT'})}.{enc(payload)}.not-a-real-signature"


def _connect(db, *, user_id="u1", slug="zerodha", token="tok-first", extras=None, now=None):
    return run(sessions.upsert_native_account(
        db, user_id=user_id, slug=slug, display=slug.title(),
        token=AccessToken(token, {"user_id": "AB1234"} if extras is None else extras), now=now,
    ))


# ── safe_return_to ───────────────────────────────────────────────────────
@pytest.mark.parametrize("value", [
    "/",
    "/dashboard",
    "/v5/app/page/brokers",
    "/v5/app/onboarding",
    "/v5/app/onboarding?step=broker",
    "/v5/app/page/brokers?tab=accounts&from=settings",
    "/v5/app/page/brokers#accounts",
    "/v5/app?q=a%20b",
    "/v5/app/page/brokers?broker_error=denied",
])
def test_safe_return_to_accepts_same_site_paths(value):
    assert sessions.safe_return_to(value) == value


@pytest.mark.parametrize("value", [
    None, "", 123, "dashboard", "v5/app",
    "//evil.com", "///evil.com", "//evil.com/v5/app",
    "https://evil.com", "http://evil.com", "HTTPS://evil.com", "javascript:alert(1)", "data:text/html,x",
    "/\\evil.com", "\\\\evil.com", "\\/evil.com", "/v5\\app",
    "/%2F%2Fevil.com", "/%2f%2fevil.com", "/%2F/evil.com", "/%5Cevil.com", "/%5cevil.com",
    "/%252F%252Fevil.com", "/%255Cevil.com", "/%25252F%25252Fevil.com", "/%2525252F%2525252Fevil.com",
    "/.//evil.com", "/v5//app",
    "/\t/evil.com", "/\n/evil.com", "/\r\nSet-Cookie: x=1", "/ok\x00", "/ok\x7f",
    "/%09/evil.com", "/%0d%0aSet-Cookie:x", "/%00",
    " /dashboard", "/dash board", "/v5/äpp",
    "/x?next=//evil.com", "/x?next=https://evil.com", "/x?next=https%3A%2F%2Fevil.com",
    "/" + "a" * 600,
])
def test_safe_return_to_rejects_everything_else(value):
    assert sessions.safe_return_to(value) is None


# ── session_expiry ───────────────────────────────────────────────────────
MORNING = datetime(2026, 10, 13, 10, 0, tzinfo=IST)  # a Tuesday


def test_expiry_prefers_expires_at_from_extras_over_everything_else():
    token = AccessToken(
        make_jwt({"exp": int(datetime(2030, 1, 1, tzinfo=UTC).timestamp())}),
        {"expires_at": "2026-10-13T18:00:00+00:00", "expires_in": 60},
    )
    assert sessions.session_expiry("zerodha", token, MORNING) == datetime(2026, 10, 13, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize("stored", ["2026-10-13T18:00:00Z", "2026-10-13T18:00:00", "2026-10-13T23:30:00+05:30"])
def test_expires_at_is_read_as_utc(stored):
    got = sessions.session_expiry("groww", AccessToken("opaque", {"expires_at": stored}), MORNING)
    assert got == datetime(2026, 10, 13, 18, 0, tzinfo=UTC) and got.utcoffset() == timedelta(0)


def test_unreadable_expires_at_falls_through_to_the_next_rule():
    token = AccessToken("opaque", {"expires_at": "tomorrow-ish", "expires_in": 3600})
    assert sessions.session_expiry("groww", token, MORNING) == MORNING + timedelta(hours=1)


def test_expiry_uses_jwt_exp_before_expires_in_and_the_daily_rule():
    exp = datetime(2026, 10, 13, 21, 45, tzinfo=UTC)
    token = AccessToken(make_jwt({"sub": "x", "exp": int(exp.timestamp())}), {"expires_in": 60})
    assert sessions.session_expiry("upstox", token, MORNING) == exp
    # Angel's SDK hands the JWT back with a "Bearer " prefix.
    bearer = AccessToken("Bearer " + make_jwt({"exp": int(exp.timestamp())}))
    assert sessions.session_expiry("angel", bearer, MORNING) == exp


@pytest.mark.parametrize("token", [
    make_jwt({"sub": "no-exp"}),
    make_jwt({"exp": "soon"}),
    make_jwt({"exp": True}),
    make_jwt({"exp": -5}),
    make_jwt({"exp": 10 ** 18}),       # not a date
    "aaa.%%%.ccc",                      # three parts, not base64 JSON
    "aaa." + base64.urlsafe_b64encode(b"[1, 2]").decode() + ".ccc",  # JSON, not an object
    "plain-opaque-token",
])
def test_token_without_a_usable_exp_gives_no_jwt_expiry(token):
    assert sessions.session_expiry("groww", AccessToken(token), MORNING) is None


def test_expires_in_is_seconds_from_now():
    got = sessions.session_expiry("fyers", AccessToken("opaque", {"expires_in": 86400}), MORNING)
    assert got == MORNING + timedelta(days=1)
    assert sessions.session_expiry("fyers", AccessToken("opaque", {"expires_in": "1800"}), MORNING) == MORNING + timedelta(minutes=30)


@pytest.mark.parametrize("value", [None, 0, -10, True, "abc", float("nan"), 10 ** 12])
def test_implausible_expires_in_is_ignored(value):
    assert sessions.session_expiry("fyers", AccessToken("opaque", {"expires_in": value}), MORNING) is None


@pytest.mark.parametrize("slug, signed_in, expected", [
    # Kite: "it'll expire at 6 AM on the next day"
    ("zerodha", datetime(2026, 10, 13, 10, 0, tzinfo=IST), datetime(2026, 10, 14, 6, 0, tzinfo=IST)),
    ("zerodha", datetime(2026, 10, 13, 23, 59, tzinfo=IST), datetime(2026, 10, 14, 6, 0, tzinfo=IST)),
    ("zerodha", datetime(2026, 10, 13, 2, 0, tzinfo=IST), datetime(2026, 10, 13, 6, 0, tzinfo=IST)),
    ("zerodha", datetime(2026, 10, 13, 6, 0, tzinfo=IST), datetime(2026, 10, 14, 6, 0, tzinfo=IST)),
    # Upstox's own examples: 8 PM Tuesday -> 3:30 AM Wednesday; 2:30 AM Wednesday -> 3:30 AM Wednesday
    ("upstox", datetime(2026, 10, 13, 20, 0, tzinfo=IST), datetime(2026, 10, 14, 3, 30, tzinfo=IST)),
    ("upstox", datetime(2026, 10, 14, 2, 30, tzinfo=IST), datetime(2026, 10, 14, 3, 30, tzinfo=IST)),
    # 5paisa: "Token expires every day at 11:59 PM."
    ("fivepaisa", datetime(2026, 10, 13, 10, 0, tzinfo=IST), datetime(2026, 10, 13, 23, 59, tzinfo=IST)),
])
def test_documented_daily_expiry_for_an_opaque_token(slug, signed_in, expected):
    got = sessions.session_expiry(slug, AccessToken("opaque-token"), signed_in)
    assert got == expected and got.utcoffset() == timedelta(0)


def test_daily_expiry_takes_a_naive_now_as_utc():
    got = sessions.session_expiry("zerodha", AccessToken("opaque-token"), datetime(2026, 10, 13, 4, 30))
    assert got == datetime(2026, 10, 14, 0, 30, tzinfo=UTC)  # 04:30 UTC is 10:00 IST


@pytest.mark.parametrize("slug", ["fyers", "aliceblue", "angel", "dhan", "groww", "icicidirect", "no-such-broker"])
def test_no_expiry_is_claimed_where_none_is_documented(slug):
    assert sessions.session_expiry(slug, AccessToken("opaque-token", {"user_id": "X1"}), MORNING) is None


# ── broker_user_id ───────────────────────────────────────────────────────
@pytest.mark.parametrize("slug, extras, expected", [
    ("zerodha", {"user_id": "AB1234"}, "AB1234"),
    ("upstox", {"user_id": "7XYZ99"}, "7XYZ99"),
    ("aliceblue", {"user_id": "AL001"}, "AL001"),
    ("angel", {"client_code": "A123456"}, "A123456"),
    ("angel", {"user_id": "A123456"}, "A123456"),          # a new adapter using the generic key
    ("fivepaisa", {"client_code": 51234567}, "51234567"),
    ("dhan", {"client_id": " 1100001 "}, "1100001"),
    ("groww", {"user_id": "GW42"}, "GW42"),                # any slug without its own rule
    ("icicidirect", {"user_id": "IC9"}, "IC9"),
    ("fyers", {"refresh_token": "r", "expires_in": 60}, None),
    ("zerodha", {"user_id": "  "}, None),
    ("zerodha", {"user_id": None}, None),
    ("zerodha", {}, None),
])
def test_broker_user_id_comes_from_extras(slug, extras, expected):
    assert sessions.broker_user_id(slug, AccessToken("t", extras)) == expected


# ── upsert_native_account ────────────────────────────────────────────────
def test_first_connect_creates_a_row_in_the_existing_shape():
    db = FakeDb()
    doc = _connect(db, now=MORNING)

    assert len(db.broker_accounts.docs) == 1
    stored = db.broker_accounts.docs[0]
    assert "_id" not in doc and {k: v for k, v in stored.items()} == doc
    # every field the OpenAlgo path reads is still there
    for field in ("account_id", "user_id", "broker", "label", "openalgo_url", "openalgo_hosted",
                  "openalgo_per_account_instance", "native", "api_key_encrypted", "api_key_masked",
                  "extras_encrypted", "status", "created_at", "updated_at", "last_sync_at",
                  "last_sync_count", "last_error"):
        assert field in stored, field
    assert stored["account_id"].startswith("ba_") and stored["native"] is True
    assert (stored["user_id"], stored["broker"], stored["label"]) == ("u1", "zerodha", "Zerodha")
    assert stored["status"] == sessions.STATUS_ACTIVE and stored["last_error"] is None
    assert stored["session_started_at"] == MORNING.astimezone(UTC).isoformat()
    assert stored["session_expires_at"] == datetime(2026, 10, 14, 0, 30, tzinfo=UTC).isoformat()
    assert stored["session_ended_reason"] is None
    # `api_key_masked` is returned to the client; no part of a session token is shown.
    assert stored["api_key_masked"] == ""


def test_token_and_client_id_are_never_stored_in_the_clear():
    db = FakeDb()
    _connect(db, token="tok-super-secret-value", extras={"user_id": "AB1234"})
    stored = db.broker_accounts.docs[0]

    blob = json.dumps(stored, default=str)
    assert "tok-super-secret-value" not in blob
    assert "AB1234" not in blob
    assert stored["broker_user_key"] == hashlib.sha256(b"zerodha:AB1234").hexdigest()
    assert stored["broker_user_masked"] == "••••34"
    token = sessions.load_token(stored)
    assert token.token == "tok-super-secret-value" and token.extras == {"user_id": "AB1234"}


@pytest.mark.parametrize("client_id, masked", [("AB1234", "••••34"), ("A123456", "•••••56"), ("XY12", "•••2"), ("Z9", "••")])
def test_masked_client_id_hides_most_characters(client_id, masked):
    assert sessions._mask_user(client_id) == masked


def test_reconnecting_the_same_login_refreshes_its_row():
    db = FakeDb()
    first = _connect(db, token="tok-first", now=MORNING)
    # the account has since synced, then its session ended with an error on record
    db.broker_accounts.docs[0].update(last_sync_at="2026-10-13T05:00:00+00:00", last_sync_count=7)
    run(sessions.end_session(db, first["account_id"], "broker_rejected", error="token refused"))

    later = MORNING + timedelta(days=1)
    second = _connect(db, token="tok-second", now=later)

    assert len(db.broker_accounts.docs) == 1
    assert second["account_id"] == first["account_id"] and second["created_at"] == first["created_at"]
    assert (second["last_sync_at"], second["last_sync_count"]) == ("2026-10-13T05:00:00+00:00", 7)
    assert second["status"] == sessions.STATUS_ACTIVE
    assert second["last_error"] is None and second["session_ended_reason"] is None
    assert second["session_started_at"] == later.astimezone(UTC).isoformat()
    assert second["session_expires_at"] == datetime(2026, 10, 15, 0, 30, tzinfo=UTC).isoformat()
    assert sessions.load_token(db.broker_accounts.docs[0]).token == "tok-second"
    assert "_id" not in second


def test_a_different_login_at_the_same_broker_gets_its_own_row():
    db = FakeDb()
    first = _connect(db, extras={"user_id": "AB1234"})
    second = _connect(db, extras={"user_id": "CD5678"})

    assert len(db.broker_accounts.docs) == 2
    assert first["account_id"] != second["account_id"]
    assert first["broker_user_key"] != second["broker_user_key"]
    # and reconnecting either one still lands on its own row
    assert _connect(db, extras={"user_id": "CD5678"})["account_id"] == second["account_id"]
    assert len(db.broker_accounts.docs) == 2


def test_same_client_id_for_another_user_or_broker_is_a_separate_row():
    db = FakeDb()
    mine = _connect(db, user_id="u1", slug="zerodha")
    theirs = _connect(db, user_id="u2", slug="zerodha")
    other_broker = _connect(db, user_id="u1", slug="upstox")
    assert len({mine["account_id"], theirs["account_id"], other_broker["account_id"]}) == 3
    assert mine["broker_user_key"] != other_broker["broker_user_key"]


def test_without_a_client_id_there_is_one_row_per_broker_not_one_per_reconnect():
    db = FakeDb()
    first = _connect(db, slug="fyers", token="tok-1", extras={"refresh_token": "r1"})
    second = _connect(db, slug="fyers", token="tok-2", extras={"refresh_token": "r2"})
    third = _connect(db, slug="fyers", token="tok-3", extras={})

    assert len(db.broker_accounts.docs) == 1
    assert first["account_id"] == second["account_id"] == third["account_id"]
    assert first["broker_user_key"] is None and first["broker_user_masked"] is None
    assert sessions.load_token(db.broker_accounts.docs[0]).token == "tok-3"
    # a login the broker does identify is never folded into the unidentified row
    named = _connect(db, slug="fyers", token="tok-4", extras={"user_id": "FY0001"})
    assert named["account_id"] != first["account_id"] and len(db.broker_accounts.docs) == 2


def test_an_openalgo_row_is_never_taken_for_a_reconnect():
    db = FakeDb()
    db.broker_accounts.docs.append({"account_id": "ba_openalgo", "user_id": "u1", "broker": "zerodha",
                                    "api_key_encrypted": pii.encrypt("openalgo-key"), "status": "active"})
    doc = _connect(db, extras={})
    assert doc["account_id"] != "ba_openalgo" and len(db.broker_accounts.docs) == 2
    assert pii.decrypt(db.broker_accounts.docs[0]["api_key_encrypted"]) == "openalgo-key"


# ── end_session / end_sessions_for_user / expire_due_sessions ────────────
def test_end_session_wipes_the_token_and_keeps_the_row_and_its_holdings():
    db = FakeDb()
    doc = _connect(db)
    db.broker_accounts.docs[0].update(last_sync_at="2026-10-13T05:00:00+00:00", last_sync_count=3)
    db.holdings.docs.append({"user_id": "u1", "broker_account_id": doc["account_id"], "ticker": "INFY"})

    run(sessions.end_session(db, doc["account_id"], "logout"))

    stored = db.broker_accounts.docs[0]
    assert (stored["api_key_encrypted"], stored["extras_encrypted"], stored["api_key_masked"]) == ("", "", "")
    assert stored["status"] == sessions.STATUS_EXPIRED and stored["session_ended_reason"] == "logout"
    assert stored["account_id"] == doc["account_id"] and stored["last_sync_count"] == 3
    assert stored["broker_user_key"] == doc["broker_user_key"]      # so a reconnect finds this row again
    assert stored["last_error"] is None
    assert len(db.holdings.docs) == 1
    with pytest.raises(sessions.SessionEnded):
        sessions.load_token(stored)


def test_end_session_records_a_shortened_error_and_rejects_unknown_reasons():
    db = FakeDb()
    doc = _connect(db)
    run(sessions.end_session(db, doc["account_id"], "broker_rejected", error="x" * 1000))
    stored = db.broker_accounts.docs[0]
    assert stored["session_ended_reason"] == "broker_rejected" and stored["last_error"] == "x" * 300

    other = _connect(db, extras={"user_id": "CD5678"})
    with pytest.raises(ValueError):
        run(sessions.end_session(db, other["account_id"], "because"))
    assert sessions.is_live(db.broker_accounts.docs[1])


def test_end_session_leaves_openalgo_rows_alone():
    db = FakeDb()
    db.broker_accounts.docs.append({"account_id": "ba_openalgo", "user_id": "u1", "broker": "zerodha",
                                    "api_key_encrypted": "ciphertext", "status": "active"})
    run(sessions.end_session(db, "ba_openalgo", "logout"))
    assert db.broker_accounts.docs[0] == {"account_id": "ba_openalgo", "user_id": "u1", "broker": "zerodha",
                                          "api_key_encrypted": "ciphertext", "status": "active"}


def test_end_sessions_for_user_ends_only_that_users_live_native_sessions():
    db = FakeDb()
    a = _connect(db, user_id="u1", slug="zerodha")
    b = _connect(db, user_id="u1", slug="upstox")
    already = _connect(db, user_id="u1", slug="fyers", extras={})
    run(sessions.end_session(db, already["account_id"], "expired"))
    other_user = _connect(db, user_id="u2", slug="zerodha")
    db.broker_accounts.docs.append({"account_id": "ba_openalgo", "user_id": "u1", "broker": "dhan",
                                    "api_key_encrypted": "ciphertext", "status": "active"})

    assert run(sessions.end_sessions_for_user(db, "u1", "logout")) == 2

    by_id = {d["account_id"]: d for d in db.broker_accounts.docs}
    for doc in (a, b):
        assert by_id[doc["account_id"]]["status"] == sessions.STATUS_EXPIRED
        assert by_id[doc["account_id"]]["session_ended_reason"] == "logout"
        assert by_id[doc["account_id"]]["api_key_encrypted"] == ""
    assert by_id[already["account_id"]]["session_ended_reason"] == "expired"   # not re-labelled
    assert sessions.is_live(by_id[other_user["account_id"]])
    assert by_id["ba_openalgo"]["api_key_encrypted"] == "ciphertext"
    assert run(sessions.end_sessions_for_user(db, "u1", "logout")) == 0


def test_expire_due_sessions_ends_only_sessions_past_their_expiry():
    db = FakeDb()
    due = _connect(db, user_id="u1", slug="zerodha", now=MORNING)                       # ends 14 Oct 06:00 IST
    not_due = _connect(db, user_id="u1", slug="groww", extras={"user_id": "G1", "expires_at": "2026-10-20T00:00:00+00:00"}, now=MORNING)
    unknown = _connect(db, user_id="u1", slug="fyers", extras={}, now=MORNING)          # expiry not known
    someone_else = _connect(db, user_id="u2", slug="zerodha", now=MORNING)
    db.broker_accounts.docs.append({"account_id": "ba_openalgo", "user_id": "u1", "broker": "dhan", "status": "active",
                                    "api_key_encrypted": "ciphertext", "session_expires_at": "2020-01-01T00:00:00+00:00"})
    by_id = lambda: {d["account_id"]: d for d in db.broker_accounts.docs}  # noqa: E731

    before = datetime(2026, 10, 14, 5, 59, tzinfo=IST)
    assert run(sessions.expire_due_sessions(db, now=before)) == 0

    after = datetime(2026, 10, 14, 6, 0, tzinfo=IST)
    assert run(sessions.expire_due_sessions(db, user_id="u1", now=after)) == 1
    rows = by_id()
    assert rows[due["account_id"]]["status"] == sessions.STATUS_EXPIRED
    assert rows[due["account_id"]]["session_ended_reason"] == "expired"
    assert rows[due["account_id"]]["api_key_encrypted"] == ""
    assert sessions.is_live(rows[someone_else["account_id"]], before)       # other user not swept by a per-user call
    assert rows[someone_else["account_id"]]["status"] == sessions.STATUS_ACTIVE

    assert run(sessions.expire_due_sessions(db, now=after)) == 1            # all users: picks up u2
    rows = by_id()
    assert rows[someone_else["account_id"]]["status"] == sessions.STATUS_EXPIRED
    assert sessions.is_live(rows[not_due["account_id"]], after) and sessions.is_live(rows[unknown["account_id"]], after)
    assert rows["ba_openalgo"]["status"] == "active" and rows["ba_openalgo"]["api_key_encrypted"] == "ciphertext"
    assert run(sessions.expire_due_sessions(db, now=after)) == 0


# ── is_live / load_token / public_fields ─────────────────────────────────
def test_is_live_needs_active_status_a_token_and_an_unpassed_expiry():
    db = FakeDb()
    doc = _connect(db, now=MORNING)
    assert sessions.is_live(doc, MORNING)
    assert sessions.is_live(doc, datetime(2026, 10, 14, 5, 59, 59, tzinfo=IST))
    assert not sessions.is_live(doc, datetime(2026, 10, 14, 6, 0, tzinfo=IST))
    assert not sessions.is_live({**doc, "status": sessions.STATUS_EXPIRED}, MORNING)
    assert not sessions.is_live({**doc, "status": "error"}, MORNING)
    assert not sessions.is_live({**doc, "api_key_encrypted": ""}, MORNING)
    assert sessions.is_live({**doc, "session_expires_at": None}, MORNING + timedelta(days=400))
    assert not sessions.is_live({}, MORNING)


def test_load_token_round_trips_and_raises_session_ended_when_there_is_no_token():
    db = FakeDb()
    doc = _connect(db, token="tok-live", extras={"user_id": "AB1234", "login_time": datetime(2026, 10, 13, 10, 0)})
    token = sessions.load_token(doc)
    assert token.token == "tok-live" and token.extras["user_id"] == "AB1234"

    for broken in ({}, {"api_key_encrypted": ""}, {"api_key_encrypted": None}, {"api_key_encrypted": "not-a-ciphertext"}):
        with pytest.raises(sessions.SessionEnded) as caught:
            sessions.load_token(broken)
        assert isinstance(caught.value, RuntimeError)
    # a token with unreadable extras still loads, with empty extras
    assert sessions.load_token({**doc, "extras_encrypted": pii.encrypt("not json")}).extras == {}
    assert sessions.load_token({**doc, "extras_encrypted": ""}).extras == {}


def test_public_fields_for_each_stage_of_a_session():
    db = FakeDb()
    doc = _connect(db, now=MORNING)
    keys = {"native", "broker_user_masked", "session_expires_at", "session_ended_reason", "needs_reconnect"}

    live = sessions.public_fields(doc, MORNING)
    assert set(live) == keys
    assert live == {"native": True, "broker_user_masked": "••••34", "session_ended_reason": None,
                    "session_expires_at": doc["session_expires_at"], "needs_reconnect": False}

    # past its expiry but not swept yet: already reads as ended
    lapsed = sessions.public_fields(doc, MORNING + timedelta(days=2))
    assert lapsed["needs_reconnect"] is True and lapsed["session_ended_reason"] == "expired"
    assert lapsed["session_expires_at"] is None

    run(sessions.end_session(db, doc["account_id"], "logout"))
    ended = sessions.public_fields(db.broker_accounts.docs[0], MORNING)
    assert ended == {"native": True, "broker_user_masked": "••••34", "session_ended_reason": "logout",
                     "session_expires_at": None, "needs_reconnect": True}

    openalgo = sessions.public_fields({"account_id": "ba_x", "status": "pending", "api_key_encrypted": "c"}, MORNING)
    assert openalgo == {"native": False, "broker_user_masked": None, "session_ended_reason": None,
                        "session_expires_at": None, "needs_reconnect": False}
    # nothing secret leaks through
    assert not any("encrypted" in k or "key" in k for k in live)
