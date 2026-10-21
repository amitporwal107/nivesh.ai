"""Daily platform Kite login (callback, state, token store) and the morning token alert.

No network, no Mongo, no Kite, no real notifier: Mongo, the Kite SDK exchange, the clock and the channels are fakes
(MOCK -- not real data). What these cannot show is Zerodha's real redirect and real alert delivery: UNVERIFIED, see
test_reports/OVERRIDE_kite_live_feed.md. There is no auto-login anywhere in this feature; a human taps the link.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import broker_native, live_quotes
from services.kite_live_feed import config as cfg
from services.kite_live_feed import platform_token as pt
from services.kite_live_feed import token_alert as ta
from tests.test_kite_live_feed import (  # the same in-memory fakes
    AFTER_CLOSE, FakeDB, FakeKite, TokenException, make_feed, run,
)

IST = cfg.IST
TOKEN = "platform-ACCESS-TOKEN-0123456789"
REQ_TOKEN = "request-TOKEN-ABCDEFGH"
KEY = "api-key-PUBLIC"
SECRET = "api-SECRET-ZZZZZZZZ"
TUE = lambda h, m=0, s=0: datetime(2026, 10, 20, h, m, s, tzinfo=IST)   # a Tuesday  # noqa: E731


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("KITE_PLATFORM_USER_ID", "WVX837")
    monkeypatch.setenv("KITE_API_SECRET", SECRET)
    from helpers import secrets
    monkeypatch.setattr(secrets, "get", lambda k: {"KITE_API_SECRET": SECRET, "KITE_PLATFORM_USER_ID": "WVX837"}.get(k, ""))
    pt.clear_cache()
    yield
    pt.clear_cache()


def exchange_ok(user="WVX837", token=TOKEN):
    calls = []

    def ex(key, secret, request_token):
        calls.append((key, request_token))
        return {"access_token": token, "user_id": user}
    ex.calls = calls
    return ex


async def login(db, params_extra=None, *, exchange=None, now=None):
    now = now or TUE(9, 0)
    made = await pt.create_login_state(db, "admin1", now)
    params = {"broker": "zerodha", "request_token": REQ_TOKEN, "action": "login", "status": "success", "state": made["state"], **(params_extra or {})}
    return made, await pt.handle_callback(db, params, exchange=exchange or exchange_ok(), get_api_key=lambda: KEY, now=now)


# ── expiry and URL ───────────────────────────────────────────────────────────

def test_expiry_is_the_next_0600_ist():
    assert pt.next_expiry(TUE(5, 0)) == TUE(6, 0).astimezone(timezone.utc)
    assert pt.next_expiry(TUE(9, 0)) == (TUE(6, 0) + timedelta(days=1)).astimezone(timezone.utc)
    assert pt.next_expiry(TUE(6, 0)) == (TUE(6, 0) + timedelta(days=1)).astimezone(timezone.utc)


def test_login_url_shape():
    u = pt.login_url(KEY, "kp.abc.def")
    assert u.startswith("https://kite.zerodha.com/connect/login?v=3&api_key=api-key-PUBLIC&redirect_params=")
    assert u.endswith("state%3Dkp.abc.def")


# ── callback ─────────────────────────────────────────────────────────────────

def test_happy_path_stores_encrypted_token_until_next_0600_and_default_token_prefers_it(monkeypatch):
    db, ex = FakeDB(), exchange_ok()
    now = datetime.now(timezone.utc)            # default_token() reads the real clock
    made, (ok, reason) = run(login(db, exchange=ex, now=now))
    assert (ok, reason) == (True, "connected") and ex.calls == [(KEY, REQ_TOKEN)]
    doc = db[pt.COL_TOKEN].docs[pt.TOKEN_DOC_ID]
    assert doc["user_id"] == "WVX837" and doc["obtained_at"] == now
    assert doc["expires_at"] == pt.next_expiry(now)
    assert TOKEN not in json.dumps(doc, default=str) and doc["token_enc"]       # encrypted at rest
    assert pt.cached_token(now) == TOKEN
    from helpers import secrets
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "env-token")
    monkeypatch.setattr(secrets, "get", lambda k: "env-token" if k == "KITE_ACCESS_TOKEN" else "")
    from services.providers.kite_adapter import default_token
    assert default_token() == TOKEN                                                # platform session first
    pt._cache = (TOKEN, datetime.now(timezone.utc) - timedelta(seconds=1))         # past 06:00 IST
    assert default_token() == "env-token"                                          # then env / file


def test_cache_loads_from_mongo_for_another_container():
    db = FakeDB()
    run(login(db))
    pt.clear_cache()
    assert pt.cached_token(TUE(9, 1)) == ""
    assert run(pt.refresh_cache(db, TUE(9, 1))) is True
    assert pt.cached_token(TUE(9, 1)) == TOKEN
    assert run(pt.refresh_cache(db, TUE(9, 1) + timedelta(days=1))) is False       # expired: not served


def test_wrong_zerodha_user_is_rejected_and_nothing_is_stored():
    db = FakeDB()
    _, (ok, reason) = run(login(db, exchange=exchange_ok(user="ABC123")))
    assert (ok, reason) == (False, "wrong_account")
    assert pt.COL_TOKEN not in db.cols or not db[pt.COL_TOKEN].docs
    assert pt.cached_token() == ""


def test_unset_platform_user_refuses_everything(monkeypatch):
    monkeypatch.delenv("KITE_PLATFORM_USER_ID")
    from helpers import secrets
    monkeypatch.setattr(secrets, "get", lambda k: "")
    _, (ok, reason) = run(login(FakeDB()))
    assert (ok, reason) == (False, "platform_user_not_configured")


def test_state_is_single_use_short_lived_and_signed():
    db = FakeDB()
    made, first = run(login(db))
    assert first[0] is True
    again = run(pt.handle_callback(db, {"state": made["state"], "request_token": REQ_TOKEN}, exchange=exchange_ok(), get_api_key=lambda: KEY, now=TUE(9, 1)))
    assert again == (False, "state_used")                                          # replay
    old = run(pt.create_login_state(db, "a", TUE(9, 0)))
    late = TUE(9, 0) + timedelta(minutes=pt.state_ttl_minutes(), seconds=1)
    assert run(pt.handle_callback(db, {"state": old["state"], "request_token": "x"}, exchange=exchange_ok(), get_api_key=lambda: KEY, now=late)) == (False, "state_expired")
    forged = old["state"][:-3] + "AAA"
    assert run(pt.handle_callback(db, {"state": forged, "request_token": "x"}, exchange=exchange_ok(), get_api_key=lambda: KEY, now=TUE(9, 1)))[1] == "invalid_state"
    unknown = f"{pt.STATE_PREFIX}nonce.{pt._sign('nonce')}"                        # right signature, never issued
    assert run(pt.handle_callback(db, {"state": unknown, "request_token": "x"}, exchange=exchange_ok(), get_api_key=lambda: KEY, now=TUE(9, 1)))[1] == "invalid_state"


def test_kite_denied_missing_token_and_failed_exchange(caplog):
    caplog.set_level(logging.DEBUG)
    db = FakeDB()
    assert run(login(db, {"status": "cancelled"}))[1] == (False, "denied")
    assert run(login(db, {"request_token": ""}))[1] == (False, "missing_params")

    def boom(k, s, r):
        raise TokenException(f"bad {REQ_TOKEN} {SECRET} {KEY}")
    assert run(login(db, exchange=boom))[1] == (False, "token_exchange_failed")
    text = "\n".join(r.getMessage() + str(r.exc_info) for r in caplog.records)
    assert REQ_TOKEN not in text and SECRET not in text and TOKEN not in text


def test_token_never_logged_or_returned_by_any_route(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    db = FakeDB()
    run(login(db))
    f = make_feed(db, token=TOKEN)
    run(f.tick())
    monkeypatch.setattr(live_quotes, "get_feed", lambda: f)

    async def admin(request: Request):
        return {"user_id": "adm", "is_admin": True}
    monkeypatch.setattr(live_quotes, "get_current_user", admin)
    monkeypatch.setattr(live_quotes, "require_admin", admin)
    monkeypatch.setattr(cfg, "get_api_key", lambda: KEY)
    app = FastAPI()
    app.include_router(live_quotes.router)
    c = TestClient(app)
    bodies = [c.get("/api/live/status").text, c.get("/api/live/quotes", params={"symbols": "AAA"}).text, c.post("/api/live/kite/login-url").text]
    for b in bodies:
        assert TOKEN not in b and SECRET not in b and "token_enc" not in b
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert TOKEN not in text and SECRET not in text


# ── routes ───────────────────────────────────────────────────────────────────

def _native_client(monkeypatch, db, exchange):
    monkeypatch.setattr(broker_native, "db", db)
    monkeypatch.setattr(pt, "_default_exchange", exchange)
    app = FastAPI()
    app.include_router(broker_native.router)
    return TestClient(app, follow_redirects=False)


def test_native_callback_platform_state_redirects_to_dashboard_connected(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cfg, "get_api_key", lambda: KEY)
    c = _native_client(monkeypatch, db, lambda k, s, r: {"access_token": TOKEN, "user_id": "WVX837"})
    made = run(pt.create_login_state(db, "adm"))
    r = c.get("/api/broker/native/callback", params={"broker": "zerodha", "request_token": REQ_TOKEN, "status": "success", "state": made["state"]})
    assert r.status_code in (302, 307) and r.headers["location"] == "/dashboard?kite=connected"
    assert db[pt.COL_TOKEN].docs[pt.TOKEN_DOC_ID]["user_id"] == "WVX837"
    r2 = c.get("/api/broker/native/callback", params={"broker": "zerodha", "request_token": REQ_TOKEN, "status": "success", "state": made["state"]})
    assert r2.headers["location"] == "/dashboard?kite=error&reason=state_used"      # replay


def test_native_callback_wrong_account_redirects_with_reason(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cfg, "get_api_key", lambda: KEY)
    c = _native_client(monkeypatch, db, lambda k, s, r: {"access_token": TOKEN, "user_id": "STRANGER1"})
    made = run(pt.create_login_state(db, "adm"))
    r = c.get("/api/broker/native/callback", params={"broker": "zerodha", "request_token": REQ_TOKEN, "state": made["state"]})
    assert r.headers["location"] == "/dashboard?kite=error&reason=wrong_account"
    assert not db[pt.COL_TOKEN].docs


def test_per_user_flow_is_unchanged_for_other_states(monkeypatch):
    db = FakeDB()
    c = _native_client(monkeypatch, db, lambda k, s, r: pytest.fail("the platform exchange must not run"))
    r = c.get("/api/broker/native/callback", params={"broker": "zerodha", "request_token": REQ_TOKEN, "state": "someUserState123"})
    assert r.status_code in (302, 307) and ("broker_error=invalid_state" in r.headers["location"] or r.headers["location"].startswith("/login"))
    assert not db.cols.get(pt.COL_TOKEN) or not db[pt.COL_TOKEN].docs
    r = c.get("/api/broker/native/callback", params={"broker": "upstox", "code": "x", "state": f"{pt.STATE_PREFIX}a.b"})
    assert "kite=" not in r.headers["location"]                                      # a kp. state is platform-only for zerodha


def test_login_url_endpoint_is_admin_only_and_needs_configuration(monkeypatch):
    from fastapi import HTTPException
    db = FakeDB()
    f = make_feed(db)
    monkeypatch.setattr(live_quotes, "get_feed", lambda: f)

    async def deny(request: Request):
        raise HTTPException(status_code=403, detail="Admin access required")
    monkeypatch.setattr(live_quotes, "require_admin", deny)
    app = FastAPI()
    app.include_router(live_quotes.router)
    c = TestClient(app)
    assert c.post("/api/live/kite/login-url").status_code == 403

    async def admin(request: Request):
        return {"user_id": "adm"}
    monkeypatch.setattr(live_quotes, "require_admin", admin)
    monkeypatch.setattr(cfg, "get_api_key", lambda: "")
    assert c.post("/api/live/kite/login-url").status_code == 503
    monkeypatch.setattr(cfg, "get_api_key", lambda: KEY)
    r = c.post("/api/live/kite/login-url")
    assert r.status_code == 200 and r.json()["login_url"].startswith("https://kite.zerodha.com/connect/login?v=3&api_key=")
    assert len(db[pt.COL_STATES].docs) == 1


# ── feed recovery ────────────────────────────────────────────────────────────

def test_feed_recovers_when_the_token_arrives_without_restart():
    db = FakeDB()
    f = make_feed(db, token="", )
    f.token_getter = lambda: pt.cached_token(f.clock())
    run(f.tick())
    assert f.state == "not_connected"
    run(login(db, now=f.clock()))                                    # stored by "another container"
    pt.clear_cache()                                                 # this process has not seen it yet
    f._clock.now += timedelta(seconds=10)                            # inside the 30 s not_connected backoff
    run(f.tick())
    assert f.state == "live" and f.snapshot["count"] > 0


def test_feed_clears_expired_when_a_new_token_arrives():
    db = FakeDB()
    kite = FakeKite(fail=TokenException("expired"))
    f = make_feed(db, kite=kite, token=TOKEN)
    f.token_getter = lambda: pt.cached_token(f.clock()) or TOKEN
    run(f.tick())
    assert f.state == "expired"
    kite.fail = None
    run(login(db, now=f.clock(), exchange=exchange_ok(token="renewed-token")))
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    assert f.state == "live"


# ── token alert ──────────────────────────────────────────────────────────────

class Notifier:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, subject, body):
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append((subject, body))
        return ["telegram"]


def alerter(db, n, minutes=30):
    return ta.TokenAlerter(db, notifier=n, interval_min=minutes, key_getter=lambda: KEY)


def test_alert_cadence_link_countdown_and_confirmation(caplog):
    caplog.set_level(logging.INFO)
    db, n = FakeDB(), Notifier()
    a = alerter(db, n)
    assert run(a.run_pass(TUE(8, 29), valid=False, reason="before_open"))["sent"] is False     # before 08:30: silent
    assert run(a.run_pass(TUE(8, 30), valid=False, reason="before_open"))["sent"] is True
    subject, body = n.sent[0]
    assert "Kite login needed" in subject and "opens at 09:15 IST, in 0h 45m" in body.replace("in 45 minutes", "in 0h 45m") or "45 minutes" in body
    assert "https://kite.zerodha.com/connect/login?v=3&api_key=api-key-PUBLIC&redirect_params=state%3Dkp." in body
    assert run(a.run_pass(TUE(8, 45), valid=False, reason="before_open"))["sent"] is False     # not due
    assert run(a.run_pass(TUE(9, 0), valid=False, reason="before_open"))["sent"] is True       # 30 min later
    assert len(n.sent) == 2 and n.sent[0][1] != n.sent[1][1]                                   # a fresh login link each time
    assert len(db[pt.COL_STATES].docs) == 2
    assert a.state()["state"] == "TOKEN_ALERT" and a.state()["alerts_sent_today"] == 2
    out = run(a.run_pass(TUE(9, 10), valid=True, reason="regular_session"))
    assert out["confirmed"] is True and n.sent[-1][0].startswith("Kite connected")
    assert run(a.run_pass(TUE(9, 11), valid=True, reason="regular_session"))["confirmed"] is False   # one confirmation only
    assert run(a.run_pass(TUE(9, 45), valid=True, reason="regular_session"))["sent"] is False
    assert a.state()["state"] is None
    assert any("sent via telegram" in r.getMessage() for r in caplog.records)                   # the channel is logged
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "kp." not in text and KEY not in text                                                # the link itself is not logged


def test_alert_is_silent_on_non_trading_days_after_close_and_when_never_needed():
    db, n = FakeDB(), Notifier()
    a = alerter(db, n)
    sat = datetime(2026, 10, 24, 10, 0, tzinfo=IST)
    assert run(a.run_pass(sat, valid=False, reason="weekend"))["sent"] is False
    assert run(a.run_pass(TUE(10), valid=False, reason="holiday"))["sent"] is False
    assert run(a.run_pass(AFTER_CLOSE, valid=False, reason="after_hours"))["sent"] is False
    assert run(a.run_pass(TUE(9, 0), valid=True, reason="regular_session"))["confirmed"] is False   # nothing was alerted: no confirmation
    assert n.sent == [] and a.state()["state"] is None


def test_alert_resets_the_next_day():
    db, n = FakeDB(), Notifier()
    a = alerter(db, n)
    run(a.run_pass(TUE(8, 30), valid=False, reason="before_open"))
    nxt = TUE(8, 31) + timedelta(days=1)
    assert run(a.run_pass(nxt, valid=False, reason="before_open"))["sent"] is True
    assert a.state()["alerts_sent_today"] == 1 and len(n.sent) == 2


def test_two_containers_do_not_both_send_in_one_interval():
    db = FakeDB()
    n1, n2 = Notifier(), Notifier()
    a1, a2 = alerter(db, n1), alerter(db, n2)
    run(a1.run_pass(TUE(8, 30), valid=False, reason="before_open"))
    run(a2.run_pass(TUE(8, 30, 5), valid=False, reason="before_open"))
    assert len(n1.sent) + len(n2.sent) == 1


def test_a_failing_notifier_never_breaks_the_pass_or_the_feed(caplog):
    caplog.set_level(logging.WARNING)
    db = FakeDB()
    a = alerter(db, Notifier(fail=True))
    assert run(a.run_pass(TUE(8, 30), valid=False, reason="before_open"))["sent"] is True
    assert a.last_channels == [] and any("NOT delivered" in r.getMessage() for r in caplog.records)
    f = make_feed(db, token="", clock=None)
    f.alerter = alerter(db, Notifier(fail=True))
    f._clock.now = TUE(8, 40)
    run(f.tick())                                                    # the feed keeps running
    assert f.state == "not_connected"


def test_interval_env_is_clamped(monkeypatch):
    for raw, want in ((None, 30), ("45", 45), ("1", 5), ("9999", 240), ("x", 30)):
        assert ta.interval_minutes({} if raw is None else {ta.INTERVAL_ENV: raw}) == want


def test_feed_raises_token_alert_then_confirms_when_connected():
    db, n = FakeDB(), Notifier()
    f = make_feed(db, token="")
    f.token_getter = lambda: pt.cached_token(f.clock())
    f.alerter = alerter(db, n)
    f._clock.now = TUE(8, 31)
    run(f.tick())
    assert f.state == "not_connected" and len(n.sent) == 1
    assert db["kite_live_snapshot"].docs["status"]["token_alert"]["state"] == "TOKEN_ALERT"
    f._clock.now += timedelta(seconds=40)
    run(login(db, now=f._clock.now))
    run(f.tick())
    assert f.state == "market_closed" and n.sent[-1][0].startswith("Kite connected")
    assert db["kite_live_snapshot"].docs["status"]["token_alert"]["state"] is None
    f._clock.now += timedelta(seconds=40)
    run(f.tick())
    assert len(n.sent) == 2                                          # stopped


def test_default_notifier_reports_channels(monkeypatch):
    from nidp.shared import notify as nn
    monkeypatch.setattr(nn, "email_configured", lambda: True)
    monkeypatch.setattr(nn, "send_email", lambda s, b: True)
    monkeypatch.setattr(nn, "send_telegram", lambda t: False)
    assert ta.default_notifier("s", "b") == ["email"]
    monkeypatch.setattr(nn, "email_configured", lambda: False)
    monkeypatch.delenv("KITE_TOKEN_ALERT_EMAIL_TO", raising=False)
    assert ta.default_notifier("s", "b") == []


def test_no_auto_login_code_exists():
    import re
    from pathlib import Path
    root = Path(pt.__file__).parent
    bad = re.compile(r"pyotp|totp|selenium|playwright|puppeteer|headless|kite\.zerodha\.com/api/login|/api/twofa", re.I)
    for p in root.glob("*.py"):
        text = "\n".join(l for l in p.read_text().splitlines() if "NOT" not in l and "no supported" not in l.lower())
        assert not bad.search(text), p.name
