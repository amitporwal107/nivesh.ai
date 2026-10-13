"""Routes around a native broker connection: /api/broker/native/{supported,
start,callback}, the registry's `configured` / `connectable` flags, and what
/api/auth/logout does to broker sessions.

Offline: `FakeDb` (from test_broker_sessions.py) stands in for Mongo, the
signed-in user and the audit writer are injected, brokers are fake adapters
registered for the test, and `hub_reads.sync_account` is stubbed. No real
broker is contacted.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
import routes.broker_native as bn
import services.brokers as brokers_pkg
from services import pii_security as pii
from services.brokers import registry, sessions
from services.brokers.base import AccessToken
from tests.test_broker_sessions import FakeDb

USER = {"user_id": "u1", "email": "a@example.com"}


@pytest.fixture(autouse=True)
def _throwaway_pii_key(monkeypatch):
    monkeypatch.setenv("PII_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(pii, "_cached_key", None)


class FakeBroker:
    """An oauth-style adapter that never leaves the process."""
    AUTH_STYLE = "oauth"

    def __init__(self, slug="fakebroker", display="Fake Broker", **attrs):
        self.SLUG, self.DISPLAY = slug, display
        self.exchanged: list[dict] = []
        self.result = AccessToken("tok-from-broker", {"user_id": "AB1234"})
        for name, value in attrs.items():
            setattr(self, name, value)

    def auth_url(self, *, state, redirect_uri):
        return f"https://login.broker.example/authorize?state={state}"

    async def exchange_code(self, *, code, state, redirect_uri):
        self.exchanged.append({"code": code, "state": state, "redirect_uri": redirect_uri})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Harness:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.db = FakeDb()
        self.audits: list[dict] = []
        self.synced: list[dict] = []
        self.sync_result: object = {"count": 2, "holdings": []}
        self.signed_in = True
        self.broker = self.register(FakeBroker())

        monkeypatch.setattr(bn, "db", self.db)

        # The flag gate re-reads persisted flags from the database; keep this worker's copy.
        async def flags_fresh(_db, now=None):
            return False
        monkeypatch.setattr(feature_gate, "refresh_if_stale", flags_fresh)

        async def current_user(request):
            if not self.signed_in:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return dict(USER)
        monkeypatch.setattr(bn, "get_current_user", current_user)

        async def record(**kwargs):
            self.audits.append(kwargs)
            return "aud_test"
        monkeypatch.setattr(bn._audit, "record", record)

        async def sync_account(db, doc):
            self.synced.append(dict(doc))
            if isinstance(self.sync_result, Exception):
                raise self.sync_result
            if callable(self.sync_result):
                return await self.sync_result()
            return self.sync_result
        stub = types.ModuleType("services.brokers.hub_reads")
        stub.sync_account = sync_account
        monkeypatch.setitem(sys.modules, "services.brokers.hub_reads", stub)
        monkeypatch.setattr(brokers_pkg, "hub_reads", stub, raising=False)

        app = FastAPI()
        app.include_router(bn.router)
        app.include_router(bn.short_router)
        self.client = TestClient(app, follow_redirects=False)

    def register(self, broker):
        self.monkeypatch.setitem(registry._REGISTRY, broker.SLUG, broker)
        return broker

    def state(self, token="state-1", *, broker="fakebroker", return_to=None, age_min=0, user_id="u1"):
        created = datetime.now(timezone.utc) - timedelta(minutes=age_min)
        doc = {"state": token, "user_id": user_id, "broker": broker,
               "redirect_uri": f"https://nivesh.example/api/broker/native/callback?broker={broker}",
               "created_at": created.isoformat(),
               "expires_at": (created + timedelta(minutes=bn.OAUTH_STATE_TTL_MIN)).isoformat()}
        if return_to:
            doc["return_to"] = return_to
        self.db.broker_oauth_states.docs.append(doc)
        return token

    def callback(self, **params):
        return self.client.get("/api/broker/native/callback", params=params)


@pytest.fixture
def h(monkeypatch):
    return Harness(monkeypatch)


def _landing(response):
    """(path, [(key, value), ...], fragment) of a redirect."""
    assert response.status_code in (302, 307), response.text
    parts = urlsplit(response.headers["location"])
    assert (parts.scheme, parts.netloc) == ("", ""), "must stay on the same site"
    return parts.path, parse_qsl(parts.query, keep_blank_values=True), parts.fragment


# ── broker_hub feature flag ──────────────────────────────────────────────
@pytest.fixture
def flag_off(monkeypatch):
    ff._ensure_defaults()
    monkeypatch.setitem(ff._flags, bn.FLAG, {"mode": "off", "allowlist": []})


def test_broker_hub_flag_is_on_for_everyone_by_default():
    assert ff.KNOWN_FEATURES[bn.FLAG]["default_mode"] == "everyone"


def test_start_is_refused_when_the_flag_is_off(h, flag_off):
    r = h.client.get("/api/broker/native/start/fakebroker")
    assert (r.status_code, r.json()["detail"]) == (403, "feature_not_enabled")
    assert h.db.broker_oauth_states.docs == []


def test_start_fails_closed_when_the_flag_state_cannot_be_read(h, monkeypatch):
    async def unreadable(_db, now=None):
        raise RuntimeError("mongo unavailable")
    monkeypatch.setattr(feature_gate, "refresh_if_stale", unreadable)

    r = h.client.get("/api/broker/native/start/fakebroker")
    assert r.status_code == 503
    assert h.db.broker_oauth_states.docs == []


def test_the_listing_and_a_started_callback_do_not_depend_on_the_flag(h, flag_off):
    assert h.client.get("/api/broker/native/supported").status_code == 200
    h.state()
    r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")
    assert ("broker_connected", "fakebroker") in _landing(r)[1]


# ── path-style callback (brokers that append their own query string) ─────
def test_a_path_style_broker_is_given_a_callback_url_without_a_query_string(h):
    seen = {}

    class PathBroker(FakeBroker):
        CALLBACK_PATH_STYLE = True
        CALLBACK_CODE_PARAMS = ("auth_token",)

        def auth_url(self, *, state, redirect_uri):
            seen["redirect_uri"] = redirect_uri
            return "https://login.broker.example/authorize"

    h.register(PathBroker("pathbroker", "Path Broker"))
    r = h.client.get("/api/broker/native/start/pathbroker", headers={"host": "nivesh.example"})

    assert r.status_code in (302, 307)
    assert seen["redirect_uri"] == "https://nivesh.example/api/broker/native/callback/pathbroker"
    assert h.db.broker_oauth_states.docs[0]["redirect_uri"] == seen["redirect_uri"]


def test_path_style_callback_completes_the_sign_in(h):
    broker = h.register(FakeBroker("pathbroker", "Path Broker",
                                   CALLBACK_PATH_STYLE=True, CALLBACK_CODE_PARAMS=("auth_token",)))
    h.state(broker="pathbroker", return_to="/v5/app/page/brokers")

    # What the broker's page builds: the registered URL + "?auth_token=…&state=…".
    r = h.client.get("/api/broker/native/callback/pathbroker?auth_token=jwt-from-broker&state=state-1")

    path, query, _ = _landing(r)
    assert path == "/v5/app/page/brokers" and ("broker_connected", "pathbroker") in query
    assert broker.exchanged[0]["code"] == "jwt-from-broker"
    assert "jwt-from-broker" not in r.headers["location"]
    assert len(h.db.broker_accounts.docs) == 1


def test_path_style_callback_for_an_unknown_broker(h):
    r = h.client.get("/api/broker/native/callback/nosuchbroker?auth_token=x&state=state-1")
    assert ("broker_error", "unknown_broker") in _landing(r)[1]


def test_angel_one_uses_the_path_style_callback():
    adapter = registry.get("angel")
    assert adapter.AUTH_STYLE == "oauth" and adapter.CALLBACK_PATH_STYLE is True
    assert adapter.CALLBACK_CODE_PARAMS == ("auth_token",)


# ── the server cannot store a session token (no encryption key) ──────────
# Seen on staging 2026-10-13: Zerodha signed the user in, the save raised and
# the callback answered a raw 500 page.
NO_KEY = RuntimeError("PII_ENCRYPTION_KEY is not configured (or invalid) and APP_ENV='staging' is not a dev environment.")


def test_nothing_is_connectable_and_no_sign_in_starts_when_tokens_cannot_be_stored(h, monkeypatch):
    monkeypatch.setattr(sessions, "storage_ready", lambda: False)

    rows = h.client.get("/api/broker/native/supported").json()["brokers"]
    assert rows and not any(r["connectable"] or r["configured"] for r in rows)

    r = h.client.get("/api/broker/native/start/fakebroker")
    assert (r.status_code, r.json()["detail"]) == (503, "Broker connections are not set up on this server yet.")
    assert "PII" not in r.text
    assert h.db.broker_oauth_states.docs == []                 # the user is never sent to the broker
    assert (h.audits[0]["outcome"], h.audits[0]["details"]["reason"]) == ("error", "token storage not configured")


@pytest.mark.parametrize("return_to, path", [(None, "/dashboard"), ("/v5/app/page/settings", "/v5/app/page/settings")])
def test_a_session_that_cannot_be_saved_returns_to_the_page_with_a_code_not_a_500(h, monkeypatch, caplog, return_to, path):
    async def cannot_store(*_a, **_k):
        raise NO_KEY
    monkeypatch.setattr(sessions, "upsert_native_account", cannot_store)
    h.state(return_to=return_to)

    with caplog.at_level(logging.DEBUG, logger=bn.logger.name):
        r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")

    landed, query, _ = _landing(r)
    assert landed == path and ("broker_error", "server_error") in query
    assert "tok-from-broker" not in r.headers["location"]
    assert h.db.broker_accounts.docs == [] and h.synced == []
    assert h.db.broker_oauth_states.docs == []                 # the one-time state is spent
    assert (h.audits[0]["outcome"], h.audits[0]["details"]["stage"], h.audits[0]["details"]["reason"]) == (
        "error", "store", "RuntimeError")
    assert "PII_ENCRYPTION_KEY" not in repr(h.audits) and "tok-from-broker" not in caplog.text


def test_start_refuses_a_broker_whose_sign_in_is_not_built_or_is_switched_off(h):
    h.register(FakeBroker("notyet", "Not Yet Broker", IMPLEMENTED=False))
    r = h.client.get("/api/broker/native/start/notyet")
    assert (r.status_code, r.json()["detail"]) == (400, "Not Yet Broker cannot be connected from Nivesh yet.")
    assert h.db.broker_oauth_states.docs == []


def test_icici_direct_is_listed_and_connectable_only_with_both_app_keys(h, monkeypatch):
    def row():
        return next(b for b in h.client.get("/api/broker/native/supported").json()["brokers"]
                    if b["slug"] == "icicidirect")

    monkeypatch.delenv("BROKER_ICICIDIRECT_API_KEY", raising=False)
    monkeypatch.delenv("BROKER_ICICIDIRECT_API_SECRET", raising=False)
    assert (row()["name"], row()["implemented"], row()["auth_style"]) == ("ICICI Direct", True, "oauth")
    assert (row()["configured"], row()["connectable"]) == (False, False)
    # Listed but not set up: start stops before the broker, as for any oauth broker without keys.
    assert h.client.get("/api/broker/native/start/icicidirect").status_code == 503
    assert h.db.broker_oauth_states.docs == []

    monkeypatch.setenv("BROKER_ICICIDIRECT_API_KEY", ICICI_APP_KEY)
    assert row()["connectable"] is False                               # the secret half is still missing
    monkeypatch.setenv("BROKER_ICICIDIRECT_API_SECRET", "unit-test-secret")
    assert (row()["configured"], row()["connectable"]) == (True, True)


def test_groww_is_listed_as_built_but_not_connectable_by_redirect(h):
    row = next(b for b in h.client.get("/api/broker/native/supported").json()["brokers"]
               if b["slug"] == "groww")
    assert (row["implemented"], row["auth_style"], row["connectable"]) == (True, "apikey", False)


# ── /supported + registry flags ──────────────────────────────────────────
def _unset_all_broker_keys(monkeypatch):
    for names in registry._REQUIRED_SECRETS.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)


def test_supported_keeps_its_path_and_keys_and_adds_the_two_flags(h, monkeypatch):
    _unset_all_broker_keys(monkeypatch)
    r = h.client.get("/api/broker/native/supported")
    assert r.status_code == 200
    rows = r.json()["brokers"]
    assert rows == registry.list_supported()
    for row in rows:
        assert {"slug", "name", "auth_style", "implemented", "configured", "connectable"} <= set(row)


def test_configured_needs_every_app_key_and_connectable_needs_oauth_too(monkeypatch):
    _unset_all_broker_keys(monkeypatch)
    by_slug = lambda: {r["slug"]: r for r in registry.list_supported()}  # noqa: E731

    rows = by_slug()
    assert (rows["zerodha"]["configured"], rows["zerodha"]["connectable"]) == (False, False)
    assert (rows["upstox"]["configured"], rows["upstox"]["connectable"]) == (False, False)

    monkeypatch.setenv("BROKER_ZERODHA_API_KEY", "unit-test-key-value")
    assert by_slug()["zerodha"]["configured"] is False                 # the secret half is still missing
    monkeypatch.setenv("BROKER_ZERODHA_API_SECRET", "unit-test-secret-value")
    rows = by_slug()
    assert (rows["zerodha"]["configured"], rows["zerodha"]["connectable"]) == (True, True)
    assert (rows["upstox"]["configured"], rows["upstox"]["connectable"]) == (False, False)

    # form / api-key brokers are never connectable by redirect, configured or not
    for name in registry._REQUIRED_SECRETS["fivepaisa"]:
        monkeypatch.setenv(name, "unit-test-value")
    rows = by_slug()
    assert (rows["fivepaisa"]["configured"], rows["fivepaisa"]["connectable"]) == (True, False)
    assert (rows["dhan"]["configured"], rows["dhan"]["connectable"]) == (True, False)   # reads no app key
    assert registry.missing_secrets("upstox") == ["BROKER_UPSTOX_API_KEY", "BROKER_UPSTOX_API_SECRET"]
    assert registry.missing_secrets("zerodha") == []


def test_list_supported_never_returns_secret_values_and_keeps_its_order(monkeypatch):
    for names in registry._REQUIRED_SECRETS.values():
        for name in names:
            monkeypatch.setenv(name, "SENTINEL-secret-value-9731")
    rows = registry.list_supported()

    assert "SENTINEL-secret-value-9731" not in repr(rows)
    assert not any("BROKER_" in repr(row) for row in rows)
    assert rows == sorted(rows, key=lambda r: (not r["implemented"], r["name"].lower()))
    for row in rows:
        assert row["connectable"] == (row["implemented"] and row["auth_style"] == "oauth" and row["configured"])
        if not row["implemented"]:                                     # placeholders read no keys at all
            assert (row["configured"], row["connectable"]) == (False, False)
    assert any(row["connectable"] for row in rows)


# ── /start ───────────────────────────────────────────────────────────────
def test_start_unknown_broker_is_404(h):
    r = h.client.get("/api/broker/native/start/no-such-broker")
    assert r.status_code == 404
    assert h.db.broker_oauth_states.docs == []


def test_start_requires_a_signed_in_user(h):
    h.signed_in = False
    assert h.client.get("/api/broker/native/start/fakebroker").status_code == 401


def test_start_without_app_keys_is_503_and_audited(h, monkeypatch):
    monkeypatch.setitem(registry._REQUIRED_SECRETS, "fakebroker", ("BROKER_FAKE_API_KEY", "BROKER_FAKE_API_SECRET"))
    monkeypatch.setenv("BROKER_FAKE_API_KEY", "unit-test-key-value")
    monkeypatch.delenv("BROKER_FAKE_API_SECRET", raising=False)

    r = h.client.get("/api/broker/native/start/fakebroker", params={"return_to": "/v5/app/page/brokers"})

    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "Fake Broker" in detail and "not configured" in detail
    assert "BROKER_" not in detail and "unit-test-key-value" not in detail
    assert h.db.broker_oauth_states.docs == []                         # nobody was sent to the broker
    assert len(h.audits) == 1
    audit = h.audits[0]
    assert (audit["user_id"], audit["action"], audit["outcome"]) == ("u1", "broker_connect", "error")
    assert audit["details"]["broker"] == "fakebroker" and audit["details"]["stage"] == "auth_url"
    assert "BROKER_FAKE_API_SECRET" in audit["details"]["reason"]      # the name, for the operator
    assert "unit-test-key-value" not in repr(audit)


@pytest.mark.parametrize("return_to, stored", [
    (None, None),
    ("/v5/app/page/brokers", "/v5/app/page/brokers"),
    ("/v5/app/onboarding", "/v5/app/onboarding"),
    ("/v5/app/onboarding?step=broker&from=settings", "/v5/app/onboarding?step=broker&from=settings"),
    ("//evil.com", None),
    ("https://evil.com/v5/app", None),
    ("/\\evil.com", None),
    ("/%2F%2Fevil.com", None),
])
def test_start_redirects_to_the_broker_and_keeps_only_a_safe_return_to(h, return_to, stored):
    params = {} if return_to is None else {"return_to": return_to}
    r = h.client.get("/api/broker/native/start/fakebroker", params=params,
                     headers={"x-forwarded-host": "nivesh.example", "x-forwarded-proto": "https"})

    assert r.status_code in (302, 307)
    assert len(h.db.broker_oauth_states.docs) == 1
    state = h.db.broker_oauth_states.docs[0]
    assert r.headers["location"] == f"https://login.broker.example/authorize?state={state['state']}"
    assert (state["user_id"], state["broker"]) == ("u1", "fakebroker")
    assert state["redirect_uri"] == "https://nivesh.example/api/broker/native/callback?broker=fakebroker"
    assert state.get("return_to") == stored
    assert ("return_to" in state) == (stored is not None)
    assert h.audits == []


def test_start_for_a_non_oauth_broker_behaves_as_before(h, monkeypatch):
    _unset_all_broker_keys(monkeypatch)
    r = h.client.get("/api/broker/native/start/dhan")
    assert r.status_code in (302, 307)
    state = h.db.broker_oauth_states.docs[0]["state"]
    assert r.headers["location"] == f"/broker-credentials/dhan?state={state}"


def test_start_other_adapter_failures_stay_500_and_audited(h):
    def broken(*, state, redirect_uri):
        raise RuntimeError("adapter cannot build a login URL")
    h.broker.auth_url = broken
    r = h.client.get("/api/broker/native/start/fakebroker")
    assert r.status_code == 500 and r.json()["detail"] == "adapter cannot build a login URL"
    assert h.audits[0]["details"] == {"broker": "fakebroker", "stage": "auth_url",
                                      "reason": "adapter cannot build a login URL"}


# ── /callback: success ───────────────────────────────────────────────────
@pytest.mark.parametrize("return_to, path, kept_query, fragment", [
    (None, "/dashboard", [], ""),
    ("/v5/app/page/brokers", "/v5/app/page/brokers", [], ""),
    ("/v5/app/onboarding", "/v5/app/onboarding", [], ""),
    ("/v5/app/onboarding?step=broker", "/v5/app/onboarding", [("step", "broker")], ""),
    ("/v5/app/page/brokers?tab=accounts&q=a%20b", "/v5/app/page/brokers", [("tab", "accounts"), ("q", "a b")], ""),
    ("/v5/app/page/brokers?tab=accounts#list", "/v5/app/page/brokers", [("tab", "accounts")], "list"),
    # outcome params left in the URL by an earlier attempt are replaced, not stacked
    ("/v5/app/page/brokers?broker_error=denied&tab=accounts&account_id=ba_old&broker_connected=upstox",
     "/v5/app/page/brokers", [("tab", "accounts")], ""),
])
def test_callback_success_lands_on_return_to_with_the_outcome_appended(h, return_to, path, kept_query, fragment):
    h.state(return_to=return_to)

    r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")

    assert len(h.db.broker_accounts.docs) == 1
    row = h.db.broker_accounts.docs[0]
    assert _landing(r) == (path, kept_query + [("broker_connected", "fakebroker"), ("account_id", row["account_id"])], fragment)

    assert h.broker.exchanged == [{"code": "auth-code-1", "state": "state-1",
                                   "redirect_uri": "https://nivesh.example/api/broker/native/callback?broker=fakebroker"}]
    assert (row["user_id"], row["broker"], row["label"], row["native"]) == ("u1", "fakebroker", "Fake Broker", True)
    assert row["status"] == sessions.STATUS_ACTIVE and row["last_error"] is None
    assert sessions.load_token(row).token == "tok-from-broker"
    assert "tok-from-broker" not in r.headers["location"]
    assert h.db.broker_oauth_states.docs == []                         # the state is single-use
    # first holdings sync ran against the stored document
    assert [d["account_id"] for d in h.synced] == [row["account_id"]]
    assert sessions.load_token(h.synced[0]).token == "tok-from-broker"
    assert h.audits == [{"user_id": "u1", "action": "broker_connect", "resource": row["account_id"],
                         "outcome": "success", "ip": "testclient", "ua": "testclient",
                         "details": {"broker": "fakebroker", "native": True}}]


def test_callback_reconnect_refreshes_the_row_and_a_second_login_adds_one(h):
    h.state("s1")
    first = dict(_landing(h.callback(broker="fakebroker", code="c1", state="s1"))[1])

    h.broker.result = AccessToken("tok-second", {"user_id": "AB1234"})
    h.state("s2")
    again = dict(_landing(h.callback(broker="fakebroker", code="c2", state="s2"))[1])

    assert again["account_id"] == first["account_id"] and len(h.db.broker_accounts.docs) == 1
    assert sessions.load_token(h.db.broker_accounts.docs[0]).token == "tok-second"

    h.broker.result = AccessToken("tok-other-login", {"user_id": "CD5678"})
    h.state("s3")
    other = dict(_landing(h.callback(broker="fakebroker", code="c3", state="s3"))[1])
    assert other["account_id"] != first["account_id"] and len(h.db.broker_accounts.docs) == 2


def test_callback_status_success_is_not_an_error(h):
    """Kite's redirect carries `status=success&action=login` next to the request_token."""
    h.state()
    r = h.callback(broker="fakebroker", request_token="kite-request-token", action="login", status="success", state="state-1")
    assert dict(_landing(r)[1])["broker_connected"] == "fakebroker"
    assert h.broker.exchanged[0]["code"] == "kite-request-token"


def test_callback_without_state_uses_the_signed_in_users_latest_attempt(h):
    h.state("older", return_to="/v5/app/onboarding", age_min=5)
    h.state("newer", return_to="/v5/app/page/brokers", age_min=1)
    h.state("someone-else", user_id="u2", return_to="/v5/app/elsewhere")

    r = h.callback(broker="fakebroker", code="auth-code-1")

    path, query, _ = _landing(r)
    assert path == "/v5/app/page/brokers" and dict(query)["broker_connected"] == "fakebroker"
    assert h.broker.exchanged[0]["state"] == "newer"
    assert sorted(d["state"] for d in h.db.broker_oauth_states.docs) == ["older", "someone-else"]
    assert h.db.broker_accounts.docs[0]["user_id"] == "u1"


def test_callback_without_state_and_signed_out_goes_to_login(h):
    h.signed_in = False
    r = h.callback(broker="fakebroker", code="auth-code-1")
    assert r.headers["location"] == "/login?next=/dashboard"
    assert h.db.broker_accounts.docs == [] and h.broker.exchanged == []


# ── /callback: adapter-declared code params ──────────────────────────────
def test_callback_reads_the_code_from_params_the_adapter_declares(h):
    h.register(FakeBroker("tokenbroker", "Token Broker", CALLBACK_CODE_PARAMS=("auth_token", "apisession")))
    declared = registry.get("tokenbroker")

    h.state("s1", broker="tokenbroker")
    r = h.callback(broker="tokenbroker", auth_token="value-under-auth-token", state="s1")
    assert dict(_landing(r)[1])["broker_connected"] == "tokenbroker"

    h.state("s2", broker="tokenbroker")
    h.callback(broker="tokenbroker", apisession="value-under-apisession", state="s2")

    # declared order is respected, and `code` / `request_token` still win
    h.state("s3", broker="tokenbroker")
    h.callback(broker="tokenbroker", apisession="second", auth_token="first", state="s3")
    h.state("s4", broker="tokenbroker")
    h.callback(broker="tokenbroker", auth_token="declared", request_token="kite-style", state="s4")
    h.state("s5", broker="tokenbroker")
    h.callback(broker="tokenbroker", auth_token="declared", request_token="kite-style", code="oauth-style", state="s5")

    assert [e["code"] for e in declared.exchanged] == [
        "value-under-auth-token", "value-under-apisession", "first", "kite-style", "oauth-style"]


def test_callback_ignores_undeclared_params(h):
    h.state(return_to="/v5/app/page/brokers")
    r = h.callback(broker="fakebroker", auth_token="not-declared-by-this-adapter", state="state-1")
    assert _landing(r) == ("/v5/app/page/brokers", [("broker_error", "missing_params")], "")
    assert h.broker.exchanged == [] and h.db.broker_accounts.docs == []


# ── ICICI Direct: the broker returns by a cross-site form POST ───────────
# ICICI's page POSTs the form field `API_Session` to the registered URL and also appends
# `?apisession=<same value>` to it; it echoes no `state`. Observed in Chromium 148, Firefox 130
# and WebKit 18 (2026-10-14, two local sites): a `SameSite=Lax` cookie is NOT sent on that POST
# and IS sent on the GET the 303 leads to. Nothing here contacts ICICI Direct.
ICICI_APP_KEY = "unit+test/app=key"
ICICI_CALLBACK = "/api/broker/native/callback/icicidirect"
ICICI_ORIGIN = "https://api.icicidirect.com"
SESSION_KEY = "1731980"   # the value in ICICI's own screenshot of the redirect URL


@pytest.fixture
def icici(h, monkeypatch):
    """The real ICICI Direct adapter with its app keys set. Its one outbound call during sign-in
    (/customerdetails) is answered locally: `icici.calls` holds the bodies it sent, `icici.reply`
    is what comes back (the success shape from ICICI's API reference by default)."""
    import httpx

    monkeypatch.setenv("BROKER_ICICIDIRECT_API_KEY", ICICI_APP_KEY)
    monkeypatch.setenv("BROKER_ICICIDIRECT_API_SECRET", "unit-test-secret")
    wire = types.SimpleNamespace(calls=[], reply={
        "Success": {"idirect_userid": "379XTZ300", "session_token": "QUgzNzkzMDA6NDUwNTM0MjI="},
        "Status": 200, "Error": None})

    def answer(request: httpx.Request) -> httpx.Response:
        wire.calls.append(json.loads(request.content))
        return httpx.Response(200, json=wire.reply)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(answer), **kw))
    return wire


def _start_icici(h, return_to="/v5/app/page/brokers"):
    r = h.client.get("/api/broker/native/start/icicidirect", params={"return_to": return_to},
                     headers={"x-forwarded-host": "staging.niveshcopilot.com", "x-forwarded-proto": "https"})
    assert r.status_code in (302, 307), r.text
    return r


def _app_log(caplog) -> str:
    """Everything logged, minus the test client's own request lines (httpx logs the URL it was asked
    to fetch, which here is the test's input, not something the app wrote)."""
    return "\n".join(r.getMessage() for r in caplog.records if "http://testserver" not in r.getMessage())


def _nothing_was_done(h, icici, states=0):
    assert icici.calls == [] and h.db.broker_accounts.docs == [] and h.audits == [] and h.synced == []
    assert len(h.db.broker_oauth_states.docs) == states


def test_icici_start_sends_the_user_to_icicis_login_page_and_stores_the_attempt(h, icici):
    r = _start_icici(h)

    # Only the app key travels: ICICI takes no redirect parameter and no `state`.
    assert r.headers["location"] == "https://api.icicidirect.com/apiuser/login?api_key=unit%2Btest%2Fapp%3Dkey"
    [state] = h.db.broker_oauth_states.docs
    assert (state["user_id"], state["broker"], state["return_to"]) == ("u1", "icicidirect", "/v5/app/page/brokers")
    # The URL the operator registers with ICICI: no query string, because ICICI appends its own.
    assert state["redirect_uri"] == "https://staging.niveshcopilot.com/api/broker/native/callback/icicidirect"
    assert state["state"] not in r.headers["location"]
    assert h.audits == []


def test_icici_posted_return_is_answered_303_to_the_get_and_nothing_else_happens(h, icici, caplog):
    _start_icici(h)
    h.signed_in = False                      # a cross-site POST carries no SameSite=Lax cookie

    with caplog.at_level(logging.DEBUG):
        r = h.client.post(ICICI_CALLBACK, data={"API_Session": SESSION_KEY}, headers={"origin": ICICI_ORIGIN})

    assert r.status_code == 303
    assert r.headers["location"] == f"{ICICI_CALLBACK}?apisession={SESSION_KEY}"
    assert "set-cookie" not in r.headers
    _nothing_was_done(h, icici, states=1)    # the attempt is still there for the GET to use
    assert SESSION_KEY not in _app_log(caplog)


# ── short callback address: /api/b/<slug or alias> ───────────────────────
# ICICI's app form caps the Redirect URL's length, so its registered URL is
# <host>/api/b/icici.
def test_icici_short_address_posted_return_goes_to_the_full_get_path(h, icici):
    _start_icici(h)
    h.signed_in = False

    r = h.client.post("/api/b/icici", data={"API_Session": SESSION_KEY}, headers={"origin": ICICI_ORIGIN})

    assert (r.status_code, r.headers["location"]) == (303, f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")
    _nothing_was_done(h, icici, states=1)


def test_short_address_get_finishes_the_sign_in_by_slug_and_by_alias(h):
    h.state()
    r = h.client.get("/api/b/fakebroker?code=auth-code-1&state=state-1")
    assert ("broker_connected", "fakebroker") in _landing(r)[1]

    aliased = h.register(FakeBroker("longbrokername", "Long Broker", CALLBACK_ALIAS="lb"))
    h.state("state-2", broker="longbrokername")
    r = h.client.get("/api/b/lb?code=auth-code-2&state=state-2")
    assert ("broker_connected", "longbrokername") in _landing(r)[1]
    assert aliased.exchanged[0]["code"] == "auth-code-2"


def test_short_address_for_an_unknown_name(h):
    assert ("broker_error", "unknown_broker") in _landing(h.client.get("/api/b/nosuch?code=x&state=state-1"))[1]
    assert h.client.post("/api/b/nosuch", data={"API_Session": "x"}).status_code == 405
    assert h.client.post("/api/b/fakebroker", data={"API_Session": "x"}).status_code == 405   # does not return by POST


def test_callback_aliases_are_unambiguous():
    brokers = registry.all_brokers()
    aliases = [b.CALLBACK_ALIAS for b in brokers if getattr(b, "CALLBACK_ALIAS", None)]
    assert registry.get("icicidirect").CALLBACK_ALIAS == "icici"
    assert len(aliases) == len(set(aliases))
    assert not set(aliases) & {b.SLUG for b in brokers}        # an alias never shadows another broker's slug


def test_icici_posted_return_with_the_value_already_in_the_query_keeps_the_query_as_it_came(h, icici):
    # What ICICI actually sends: the value in both places.
    r = h.client.post(f"{ICICI_CALLBACK}?apisession={SESSION_KEY}", data={"API_Session": SESSION_KEY})
    assert (r.status_code, r.headers["location"]) == (303, f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")

    # The query wins over a differing body, and is never duplicated.
    r = h.client.post(f"{ICICI_CALLBACK}?apisession=from-query&x=a%20b", data={"API_Session": "from-body"})
    assert (r.status_code, r.headers["location"]) == (303, f"{ICICI_CALLBACK}?apisession=from-query&x=a%20b")
    _nothing_was_done(h, icici)


@pytest.mark.parametrize("query, posted, location_query", [
    ("", "a b+c&d=e/ü", "apisession=a+b%2Bc%26d%3De%2F%C3%BC"),                    # the value is encoded, never spliced
    ("x=a%20b&utm=1", "1731980", "x=a%20b&utm=1&apisession=1731980"),              # other params are kept
    ("apisession=", "1731980", "apisession=&apisession=1731980"),                  # an empty value is no value
    ("error=access_denied", "", "error=access_denied"),                            # nothing posted: nothing added
    ("", "", ""),
])
def test_icici_posted_value_is_copied_into_the_query_only_when_missing(h, icici, query, posted, location_query):
    url = f"{ICICI_CALLBACK}?{query}" if query else ICICI_CALLBACK
    r = h.client.post(url, data={"API_Session": posted} if posted else {"other": "1"})

    assert r.status_code == 303
    target = f"{ICICI_CALLBACK}?{location_query}" if location_query else ICICI_CALLBACK
    assert r.headers["location"] == target
    if posted:                                                                     # and it round-trips exactly
        assert ("apisession", posted) in parse_qsl(urlsplit(r.headers["location"]).query)
    _nothing_was_done(h, icici)


@pytest.mark.parametrize("kwargs", [
    {"content": b"API_Session=" + b"9" * (bn.POSTED_FORM_MAX_BYTES + 1),
     "headers": {"content-type": "application/x-www-form-urlencoded"}},            # larger than a login form
    {"json": {"API_Session": SESSION_KEY}},                                         # not a form
    {"content": b"API_Session=1731980", "headers": {"content-type": "text/plain"}},
])
def test_icici_posted_body_that_is_not_a_small_form_is_not_read(h, icici, kwargs):
    r = h.client.post(ICICI_CALLBACK, **kwargs)
    assert (r.status_code, r.headers["location"]) == (303, ICICI_CALLBACK)
    _nothing_was_done(h, icici)


def test_icici_round_trip_start_post_then_get_completes_for_the_signed_in_user(h, icici):
    _start_icici(h, return_to="/v5/app/page/brokers?tab=accounts")
    attempt = dict(h.db.broker_oauth_states.docs[0])
    h.state("someone-else", broker="icicidirect", user_id="u2")       # another user's attempt, newer

    posted = h.client.post(f"{ICICI_CALLBACK}?apisession={SESSION_KEY}", data={"API_Session": SESSION_KEY},
                           headers={"origin": ICICI_ORIGIN})
    assert posted.status_code == 303
    # The browser follows the 303 with a top-level GET, which carries the session cookie.
    r = h.client.get(posted.headers["location"])

    [row] = h.db.broker_accounts.docs
    assert _landing(r) == ("/v5/app/page/brokers",
                           [("tab", "accounts"), ("broker_connected", "icicidirect"), ("account_id", row["account_id"])], "")
    # No `state` came back: the attempt was found as u1's most recent one for this broker.
    assert icici.calls == [{"SessionToken": SESSION_KEY, "AppKey": ICICI_APP_KEY}]
    assert [d["state"] for d in h.db.broker_oauth_states.docs] == ["someone-else"]
    assert attempt["state"] not in r.headers["location"] and SESSION_KEY not in r.headers["location"]
    assert (row["user_id"], row["broker"], row["label"], row["native"]) == ("u1", "icicidirect", "ICICI Direct", True)
    stored = sessions.load_token(row)
    assert stored.token == "QUgzNzkzMDA6NDUwNTM0MjI=" and stored.extras["user_id"] == "379XTZ300"
    assert "QUgzNzkzMDA6NDUwNTM0MjI=" not in repr(row) and "379XTZ300" not in repr(row)
    # The session ends at the next midnight IST, as ICICI documents.
    expires = datetime.fromisoformat(row["session_expires_at"])
    assert expires.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M:%S") == "00:00:00"
    assert timedelta(0) < expires - datetime.now(timezone.utc) <= timedelta(hours=24)
    assert [d["account_id"] for d in h.synced] == [row["account_id"]]
    assert h.audits[-1]["outcome"] == "success" and h.audits[-1]["details"] == {"broker": "icicidirect", "native": True}


def test_icici_get_with_nobody_signed_in_goes_to_login_and_spends_nothing(h, icici):
    _start_icici(h)
    h.signed_in = False
    r = h.client.get(f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")
    assert r.headers["location"] == "/login?next=/dashboard"
    _nothing_was_done(h, icici, states=1)


def test_icici_get_without_a_started_attempt_is_invalid_state(h, icici):
    r = h.client.get(f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")
    assert ("broker_error", "invalid_state") in _landing(r)[1]
    _nothing_was_done(h, icici)


def test_icici_refusing_the_session_key_lands_back_with_the_fixed_code(h, icici, caplog):
    # What the live API answered on 2026-10-13 for an app key it does not know (HTTP 200).
    icici.reply = {"Success": None, "Status": 5, "Error": "Public Key does not exist."}
    _start_icici(h)

    with caplog.at_level(logging.DEBUG):
        r = h.client.get(f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")

    assert _landing(r) == ("/v5/app/page/brokers", [("broker_error", "token_exchange_failed")], "")
    assert h.db.broker_accounts.docs == [] and h.db.broker_oauth_states.docs == [] and h.synced == []
    assert h.audits[-1]["details"] == {"broker": "icicidirect", "stage": "exchange_code", "reason": "IciciDirectError"}
    assert "exchange_code failed for icicidirect (IciciDirectError)" in _app_log(caplog)
    assert SESSION_KEY not in _app_log(caplog) and ICICI_APP_KEY not in _app_log(caplog)


@pytest.mark.parametrize("url", [
    "/api/broker/native/callback/nosuchbroker",          # an unknown slug
    "/api/broker/native/callback/fakebroker",            # a broker that does not return by POST
    "/api/broker/native/callback/angel",                 # path-style, but returns by GET
    "/api/broker/native/callback?broker=icicidirect",    # only the path-style route takes a POST
    "/api/broker/native/start/icicidirect",
])
def test_post_is_405_everywhere_but_a_form_post_brokers_own_callback(h, icici, url):
    r = h.client.post(url, data={"API_Session": SESSION_KEY})
    assert r.status_code == 405
    assert r.headers.get("allow") == "GET"
    _nothing_was_done(h, icici)


def test_a_broker_declares_its_own_form_field_and_code_param(h):
    broker = h.register(FakeBroker("formbroker", "Form Broker", CALLBACK_PATH_STYLE=True,
                                   CALLBACK_CODE_PARAMS=("ticket", "alt"), CALLBACK_FORM_FIELDS=("Ticket", "Alt")))
    r = h.client.post("/api/broker/native/callback/formbroker", data={"Alt": "second", "Ticket": "first"})
    assert (r.status_code, r.headers["location"]) == (303, "/api/broker/native/callback/formbroker?ticket=first")
    r = h.client.post("/api/broker/native/callback/formbroker?alt=in-query", data={"Ticket": "first"})
    assert r.headers["location"] == "/api/broker/native/callback/formbroker?alt=in-query"
    assert broker.exchanged == []


# ── ICICI Direct's return through the real CSRF middleware ───────────────
@pytest.fixture
def behind_csrf(h):
    from middleware import CsrfProtectMiddleware
    app = FastAPI()
    app.include_router(bn.router)
    app.add_middleware(CsrfProtectMiddleware)
    return TestClient(app, follow_redirects=False)


STAGING_CORS = "https://staging.niveshcopilot.com,https://staging.niveshcopilot.com:8443"


@pytest.mark.parametrize("cors_origins", ["", STAGING_CORS])
@pytest.mark.parametrize("origin", [ICICI_ORIGIN, "null", None])
def test_csrf_middleware_lets_the_cookieless_cross_site_post_through(h, icici, behind_csrf, monkeypatch, cors_origins, origin):
    """SameSite=Lax (staging): the browser sends no cookie on ICICI's POST, and the middleware only
    judges requests that carry the session cookie."""
    monkeypatch.setenv("CORS_ORIGINS", cors_origins)
    headers = {} if origin is None else {"origin": origin}
    r = behind_csrf.post(ICICI_CALLBACK, data={"API_Session": SESSION_KEY}, headers=headers)
    assert (r.status_code, r.headers["location"]) == (303, f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")


@pytest.mark.parametrize("cors_origins", ["", STAGING_CORS])
def test_csrf_middleware_passes_the_follow_up_get_that_carries_the_cookie(h, icici, behind_csrf, monkeypatch, cors_origins):
    monkeypatch.setenv("CORS_ORIGINS", cors_origins)
    _start_icici(h)
    behind_csrf.cookies.set("session_token", "sess-1")
    r = behind_csrf.get(f"{ICICI_CALLBACK}?apisession={SESSION_KEY}")
    assert ("broker_connected", "icicidirect") in _landing(r)[1]


@pytest.mark.parametrize("cors_origins", ["", STAGING_CORS])
@pytest.mark.parametrize("origin", [ICICI_ORIGIN, "null"])
def test_csrf_middleware_blocks_icicis_post_when_it_carries_the_cookie(h, icici, behind_csrf, monkeypatch, cors_origins, origin):
    """KNOWN LIMIT, pinned so it is not forgotten: with a SameSite=None session cookie (the default in
    backend/deps.py) the browser attaches the cookie to ICICI's cross-site POST, and the middleware
    answers 403 before the route runs. The return then needs an exemption in the middleware for this
    one path — not made here."""
    monkeypatch.setenv("CORS_ORIGINS", cors_origins)
    behind_csrf.cookies.set("session_token", "sess-1")
    r = behind_csrf.post(ICICI_CALLBACK, data={"API_Session": SESSION_KEY}, headers={"origin": origin})
    assert (r.status_code, r.json()["error"]) == (403, "CSRF_BLOCKED")
    _nothing_was_done(h, icici)


# ── /callback: failures ──────────────────────────────────────────────────
WITH_AND_WITHOUT_RETURN_TO = [
    (None, "/dashboard", []),
    ("/v5/app/page/brokers", "/v5/app/page/brokers", []),
    ("/v5/app/onboarding?step=broker", "/v5/app/onboarding", [("step", "broker")]),
]


@pytest.mark.parametrize("return_to, path, kept_query", WITH_AND_WITHOUT_RETURN_TO)
@pytest.mark.parametrize("broker_says", [
    {"error": "access_denied"},                                         # no `status` at all — used to be dropped
    {"error": "access_denied", "error_description": "User cancelled"},
    {"error": "<script>alert(1)</script>&broker_connected=zerodha"},
    {"error": "https://evil.com/phish"},
    {"status": "failed"},
    {"status": "cancelled", "code": "auth-code-1"},
    {"error": "server_error", "status": "success", "code": "auth-code-1"},
])
def test_callback_broker_error_becomes_the_fixed_denied_code(h, return_to, path, kept_query, broker_says):
    h.state(return_to=return_to)

    r = h.callback(broker="fakebroker", state="state-1", **broker_says)

    assert _landing(r) == (path, kept_query + [("broker_error", "denied")], "")
    for text in ("access_denied", "script", "evil.com", "cancel", "failed", "server_error"):
        assert text not in r.headers["location"]
    assert h.broker.exchanged == [] and h.db.broker_accounts.docs == [] and h.synced == []


def test_callback_broker_error_without_any_state_goes_to_the_dashboard(h):
    h.signed_in = False
    r = h.callback(broker="fakebroker", error="access_denied")
    assert _landing(r) == ("/dashboard", [("broker_error", "denied")], "")


@pytest.mark.parametrize("return_to, path, kept_query", WITH_AND_WITHOUT_RETURN_TO)
def test_callback_missing_code_is_missing_params(h, return_to, path, kept_query):
    h.state(return_to=return_to)
    r = h.callback(broker="fakebroker", state="state-1")
    assert _landing(r) == (path, kept_query + [("broker_error", "missing_params")], "")
    assert len(h.db.broker_oauth_states.docs) == 1 and h.db.broker_accounts.docs == []


@pytest.mark.parametrize("return_to, path, kept_query", WITH_AND_WITHOUT_RETURN_TO)
def test_callback_missing_broker_is_missing_params(h, return_to, path, kept_query):
    h.state(return_to=return_to)
    r = h.callback(code="auth-code-1", state="state-1")
    assert _landing(r) == (path, kept_query + [("broker_error", "missing_params")], "")
    assert h.broker.exchanged == []


def test_callback_with_nothing_at_all_is_missing_params(h):
    assert _landing(h.callback()) == ("/dashboard", [("broker_error", "missing_params")], "")


@pytest.mark.parametrize("return_to, path, kept_query", WITH_AND_WITHOUT_RETURN_TO)
def test_callback_expired_state(h, return_to, path, kept_query):
    h.state(return_to=return_to, age_min=bn.OAUTH_STATE_TTL_MIN + 1)
    r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")
    assert _landing(r) == (path, kept_query + [("broker_error", "state_expired")], "")
    assert h.broker.exchanged == [] and h.db.broker_accounts.docs == []


@pytest.mark.parametrize("return_to, path, kept_query", WITH_AND_WITHOUT_RETURN_TO)
def test_callback_unknown_broker(h, return_to, path, kept_query):
    h.state(return_to=return_to)
    r = h.callback(broker="no-such-broker", code="auth-code-1", state="state-1")
    assert _landing(r) == (path, kept_query + [("broker_error", "unknown_broker")], "")
    assert "no-such-broker" not in r.headers["location"]
    assert h.broker.exchanged == [] and h.db.broker_accounts.docs == []


def test_callback_unknown_broker_without_a_code_is_still_unknown_broker(h):
    r = h.callback(broker="no-such-broker")
    assert _landing(r) == ("/dashboard", [("broker_error", "unknown_broker")], "")


def test_callback_with_no_matching_attempt_is_invalid_state(h):
    r = h.callback(broker="fakebroker", code="auth-code-1", state="never-issued")
    assert _landing(r) == ("/dashboard", [("broker_error", "invalid_state")], "")
    assert h.broker.exchanged == [] and h.db.broker_accounts.docs == []


def test_callback_ignores_an_unsafe_return_to_already_in_the_state_doc(h):
    h.state()
    h.db.broker_oauth_states.docs[0]["return_to"] = "//evil.com/v5/app"
    r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")
    path, query, _ = _landing(r)
    assert path == "/dashboard" and dict(query)["broker_connected"] == "fakebroker"


@pytest.mark.parametrize("return_to, path, kept_query", WITH_AND_WITHOUT_RETURN_TO)
@pytest.mark.parametrize("outcome", [RuntimeError("broker said no: body={'message': 'bad code'}"), AccessToken("")])
def test_callback_token_exchange_failure(h, return_to, path, kept_query, outcome):
    h.state(return_to=return_to)
    h.broker.result = outcome

    r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")

    assert _landing(r) == (path, kept_query + [("broker_error", "token_exchange_failed")], "")
    assert "bad code" not in r.headers["location"]
    assert h.db.broker_accounts.docs == [] and h.synced == []
    assert h.db.broker_oauth_states.docs == []
    assert len(h.audits) == 1
    assert (h.audits[0]["action"], h.audits[0]["outcome"]) == ("broker_connect", "error")
    assert h.audits[0]["details"]["broker"] == "fakebroker" and h.audits[0]["details"]["stage"] == "exchange_code"


def test_token_exchange_failure_keeps_the_brokers_reply_out_of_logs_and_audit(h, caplog):
    # Adapters interpolate the broker's raw reply into their error text; it can carry token fields.
    h.state()
    h.broker.result = RuntimeError("Upstox token exchange failed: {'access_token': 'tok-leaked-123'}")

    with caplog.at_level(logging.DEBUG, logger=bn.logger.name):
        h.callback(broker="fakebroker", code="auth-code-1", state="state-1")

    assert "tok-leaked-123" not in caplog.text
    assert "tok-leaked-123" not in repr(h.audits)
    assert h.audits[0]["details"]["reason"] == "RuntimeError"


# ── /callback: first holdings sync ───────────────────────────────────────
def test_first_sync_failure_does_not_fail_the_connect(h, caplog):
    h.state(return_to="/v5/app/onboarding?step=broker")
    h.sync_result = RuntimeError("upstream 502 with body token=tok-from-broker")

    with caplog.at_level(logging.WARNING, logger=bn.logger.name):
        r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")

    row = h.db.broker_accounts.docs[0]
    assert _landing(r) == ("/v5/app/onboarding", [("step", "broker"), ("broker_connected", "fakebroker"),
                                                   ("account_id", row["account_id"])], "")
    assert row["last_error"] == "First holdings sync failed."
    assert row["status"] == sessions.STATUS_ACTIVE and sessions.is_live(row)
    assert h.audits[-1]["outcome"] == "success"
    logged = [rec.getMessage() for rec in caplog.records if rec.name == bn.logger.name]
    assert any("first sync failed" in m and row["account_id"] in m and "RuntimeError" in m for m in logged)
    assert not any("tok-from-broker" in m for m in logged)             # the error text is not logged


def test_first_sync_timeout_does_not_fail_the_connect(h, monkeypatch, caplog):
    monkeypatch.setattr(bn, "FIRST_SYNC_TIMEOUT_S", 0.05)

    async def slow():
        await asyncio.sleep(5)
    h.sync_result = slow
    h.state()

    with caplog.at_level(logging.WARNING, logger=bn.logger.name):
        r = h.callback(broker="fakebroker", code="auth-code-1", state="state-1")

    row = h.db.broker_accounts.docs[0]
    assert dict(_landing(r)[1]) == {"broker_connected": "fakebroker", "account_id": row["account_id"]}
    assert row["last_error"] == "First holdings sync timed out."
    assert sessions.is_live(row)
    assert any("first sync timed out" in rec.getMessage() for rec in caplog.records)


def test_first_sync_waits_twelve_seconds_by_default():
    assert bn.FIRST_SYNC_TIMEOUT_S == 12


# ── /api/auth/logout ─────────────────────────────────────────────────────
class LogoutHarness:
    def __init__(self, monkeypatch):
        import routes.auth as auth
        from services import audit

        self.auth = auth
        self.db = FakeDb()
        self.audits: list[dict] = []
        monkeypatch.setattr(auth, "db", self.db)

        async def record(**kwargs):
            self.audits.append(kwargs)
            return "aud_test"
        monkeypatch.setattr(audit, "record", record)

        app = FastAPI()
        app.include_router(auth.router)
        self.client = TestClient(app)

    def login(self, token, user_id="u1", *, expires_in_days=7):
        expires = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        self.db.user_sessions.docs.append(
            {"user_id": user_id, "session_token": token, "expires_at": expires.isoformat()})

    def connect(self, user_id="u1", slug="zerodha", client_id="AB1234"):
        return asyncio.run(sessions.upsert_native_account(
            self.db, user_id=user_id, slug=slug, display=slug.title(),
            token=AccessToken("tok-live", {"user_id": client_id})))

    def logout(self, token):
        self.client.cookies.set("session_token", token)
        return self.client.post("/api/auth/logout")

    def row(self, account_id):
        return next(d for d in self.db.broker_accounts.docs if d["account_id"] == account_id)


@pytest.fixture
def lo(monkeypatch):
    return LogoutHarness(monkeypatch)


def test_logout_of_the_last_device_ends_the_users_broker_sessions(lo):
    lo.login("tok-a")
    mine, second = lo.connect(), lo.connect(slug="upstox", client_id="UP77")
    theirs = lo.connect(user_id="u2")
    lo.db.broker_accounts.docs.append({"account_id": "ba_openalgo", "user_id": "u1", "broker": "dhan",
                                       "api_key_encrypted": "ciphertext", "status": "active"})

    r = lo.logout("tok-a")

    assert r.status_code == 200 and r.json() == {"message": "Logged out"}
    assert lo.db.user_sessions.docs == []
    for doc in (mine, second):
        row = lo.row(doc["account_id"])
        assert row["status"] == sessions.STATUS_EXPIRED and row["session_ended_reason"] == "logout"
        assert row["api_key_encrypted"] == "" and row["extras_encrypted"] == ""
        assert sessions.public_fields(row)["needs_reconnect"] is True
    assert sessions.is_live(lo.row(theirs["account_id"]))               # another user's connection
    assert lo.row("ba_openalgo")["api_key_encrypted"] == "ciphertext"   # the OpenAlgo path is untouched
    assert [a["action"] for a in lo.audits] == ["logout", "broker_disconnect"]
    ended = lo.audits[1]
    assert ended["user_id"] == "u1" and ended["details"] == {"reason": "logout", "sessions_ended": 2}


def test_logout_keeps_broker_sessions_while_signed_in_on_another_device(lo):
    lo.login("tok-a")
    lo.login("tok-b")
    mine = lo.connect()

    assert lo.logout("tok-a").status_code == 200

    assert [s["session_token"] for s in lo.db.user_sessions.docs] == ["tok-b"]
    assert sessions.is_live(lo.row(mine["account_id"]))
    assert [a["action"] for a in lo.audits] == ["logout"]

    # ...and signing out of that last device then ends them
    assert lo.logout("tok-b").status_code == 200
    assert lo.row(mine["account_id"])["session_ended_reason"] == "logout"


def test_logout_does_not_count_expired_or_other_users_sessions_as_signed_in(lo):
    lo.login("tok-a")
    lo.login("tok-stale", expires_in_days=-3)                           # never cleaned up by a later login
    lo.db.user_sessions.docs.append({"user_id": "u1", "session_token": "tok-broken", "expires_at": "not-a-date"})
    lo.login("tok-other-user", user_id="u2")
    mine = lo.connect()

    assert lo.logout("tok-a").status_code == 200

    assert lo.row(mine["account_id"])["status"] == sessions.STATUS_EXPIRED
    assert lo.audits[-1]["details"] == {"reason": "logout", "sessions_ended": 1}


def test_logout_with_no_broker_sessions_writes_no_broker_audit(lo):
    lo.login("tok-a")
    assert lo.logout("tok-a").status_code == 200
    assert [a["action"] for a in lo.audits] == ["logout"]


def test_logout_still_succeeds_and_logs_when_ending_broker_sessions_fails(lo, monkeypatch, caplog):
    lo.login("tok-a")
    mine = lo.connect()

    async def boom(db, user_id, reason):
        raise RuntimeError("database went away")
    monkeypatch.setattr(sessions, "end_sessions_for_user", boom)

    with caplog.at_level(logging.ERROR, logger=lo.auth.logger.name):
        r = lo.logout("tok-a")

    assert r.status_code == 200 and r.json() == {"message": "Logged out"}
    assert lo.db.user_sessions.docs == []
    assert sessions.is_live(lo.row(mine["account_id"]))
    assert any("ending broker sessions failed" in rec.getMessage() for rec in caplog.records)
    assert [a["action"] for a in lo.audits] == ["logout"]


def test_logout_without_a_session_cookie_touches_nothing(lo):
    mine = lo.connect()
    r = lo.client.post("/api/auth/logout")
    assert r.status_code == 200
    assert sessions.is_live(lo.row(mine["account_id"])) and lo.audits == []
