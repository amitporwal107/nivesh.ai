"""App routes /api/move-odds (TC-9..TC-14 in test_reports/move_odds_research_20260916_2351.md). No Mongo, no DaaS: the
user resolver, the flag store and the DaaS call are injected, so the gate and proxy logic run for real."""
import copy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate


class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return copy.deepcopy(d)
        return None


class _DB:
    def __init__(self, flags=None, users=()):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll(list(users))


USERS = {"invited": {"user_id": "u1", "email": "invited@example.com", "role": "user"},
         "other": {"user_id": "u2", "email": "other@example.com", "role": "user"},
         "admin": {"user_id": "u3", "email": "admin@example.com", "role": "admin", "is_admin": True},
         "client_of_invited": {"user_id": "c9", "email": "client@example.com", "_session_user_id": "u1"},
         "client_of_other": {"user_id": "c8", "email": "invited@example.com", "_session_user_id": "u2"}}
PAYLOAD = {"data": {"status": "final", "head": "p_up5_1d", "rows": [{"symbol": "PNCINFRA", "p": 0.366}]}}


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def _client(monkeypatch, db, clock=lambda: 0.0, daas=(200, PAYLOAD), configured=True):
    import routes.move_odds as mo
    from services.copilot_tools import daas_client

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("move_odds", resolve_user=resolve, get_db=lambda: db, clock=clock)
    calls = []
    async def get_raw(path, params=None, timeout=30):
        calls.append((path, params))
        if isinstance(daas, Exception):
            raise daas
        return daas
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    app = FastAPI(); app.include_router(mo.router)
    # the routes captured require_feature("move_odds") at import; swap that dependency for the injected gate
    for route in app.routes:
        for dep in getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []:
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app), calls


def _get(c, path, who):
    return c.get(path, headers={"X-Test-User": who})


def test_tc9_default_flag_denies_everyone_on_both_routes(monkeypatch):
    c, calls = _client(monkeypatch, _DB())
    for who in ("invited", "other"):
        assert _get(c, "/api/move-odds/latest", who).status_code == 403
        r = _get(c, "/api/move-odds/stocks/PNCINFRA", who)
        assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"
    assert calls == []                                             # DaaS never called for a denied user
    assert ff.KNOWN_FEATURES["move_odds"]["default_mode"] == "allowlist" and ff.KNOWN_FEATURES["move_odds"]["default_allowlist"] == []


def test_tc10_allowlisted_non_admin_gets_the_payload_unchanged(monkeypatch):
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    c, calls = _client(monkeypatch, db)
    r = _get(c, "/api/move-odds/latest?head=p_down5_1d", "invited")
    assert r.status_code == 200 and r.json() == PAYLOAD
    assert calls == [("/move-odds/latest", {"head": "p_down5_1d", "model": "v4"})]
    assert _get(c, "/api/move-odds/stocks/pncinfra", "invited").status_code == 200 and calls[-1][0] == "/move-odds/stocks/PNCINFRA"
    assert _get(c, "/api/move-odds/latest?head=p_up20_1d", "invited").status_code == 422


def test_tc11_everyone_is_rejected_and_a_persisted_everyone_reads_as_off(monkeypatch):
    with pytest.raises(ValueError, match="not allowed"):
        ff.set_flag("move_odds", mode="everyone")
    assert ff._flags["move_odds"]["mode"] == "allowlist"
    ff.set_flag("move_odds", mode="off"); ff.set_flag("move_odds", mode="allowlist")
    db = _DB(flags={"move_odds": {"mode": "everyone", "allowlist": []}})
    c, _ = _client(monkeypatch, db)
    assert _get(c, "/api/move-odds/latest", "other").status_code == 403 and ff._flags["move_odds"]["mode"] == "off"
    ff.set_flag("research", mode="everyone")                        # other flags keep all three modes


def test_tc12_admin_not_on_the_allowlist_is_denied(monkeypatch):
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    c, _ = _client(monkeypatch, db)
    assert _get(c, "/api/move-odds/latest", "admin").status_code == 403


def test_gate_uses_the_logged_in_person_not_the_client_profile_an_advisor_acts_for(monkeypatch):
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}}, users=[USERS["invited"], USERS["other"]])
    c, _ = _client(monkeypatch, db)
    assert _get(c, "/api/move-odds/latest", "client_of_invited").status_code == 200    # invited advisor acting for a client
    assert _get(c, "/api/move-odds/latest", "client_of_other").status_code == 403      # client email is allowlisted, advisor is not


def test_tc13_upstream_failures(monkeypatch):
    from services.copilot_tools.daas_client import DaasError

    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    c, _ = _client(monkeypatch, db, daas=DaasError("connect refused"))
    r = _get(c, "/api/move-odds/latest", "invited"); assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable"
    withheld = {"data": {"status": "withheld", "reason": "stale_data", "detail": {"rows": 812}, "target_session": "2026-09-18"}}
    c, _ = _client(monkeypatch, db, daas=(503, withheld))
    r = _get(c, "/api/move-odds/latest", "invited")
    assert r.status_code == 503 and r.json()["data"] == withheld["data"] and r.json()["detail"] == "withheld: stale_data"
    c, _ = _client(monkeypatch, db, daas=(500, {"error": {"status": 500}}))
    assert _get(c, "/api/move-odds/latest", "invited").status_code == 502
    c, _ = _client(monkeypatch, db, configured=False)
    assert _get(c, "/api/move-odds/latest", "invited").status_code == 502
    c, _ = _client(monkeypatch, db, daas=(404, {"error": {"status": 404}}))
    assert _get(c, "/api/move-odds/stocks/NOSUCH", "invited").status_code == 404


def test_tc14_a_flag_turned_off_elsewhere_takes_effect_within_the_refresh_window(monkeypatch):
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    t = {"now": 100.0}
    c, _ = _client(monkeypatch, db, clock=lambda: t["now"])
    assert _get(c, "/api/move-odds/latest", "invited").status_code == 200
    db.system_config.docs[0]["flags"]["move_odds"] = {"mode": "off", "allowlist": ["invited@example.com"]}   # another worker's admin write
    t["now"] = 110.0
    assert _get(c, "/api/move-odds/latest", "invited").status_code == 200        # within 30 s: this worker's copy
    t["now"] = 130.5
    assert _get(c, "/api/move-odds/latest", "invited").status_code == 403        # re-read: off everywhere


def test_unreadable_flag_state_denies(monkeypatch):
    class Broken(_DB):
        def __init__(self):
            super().__init__()
            class C:
                async def find_one(self, *a, **k): raise RuntimeError("mongo down")
            self.system_config = C()
    c, _ = _client(monkeypatch, Broken())
    r = _get(c, "/api/move-odds/latest", "invited")
    assert r.status_code == 503 and r.json()["detail"] == "feature_state_unavailable"


def test_profile_feature_map_follows_a_flag_change_made_by_another_worker():
    """Staging 2026-09-17: after an admin added an email to move_odds, /auth/me answered move_odds True on some calls
    and False on others (per-worker startup copies). The profile map now refreshes on the gate's 30 s rule."""
    import asyncio

    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": []}})
    run = asyncio.run
    m = run(feature_gate.fresh_user_feature_map(db, "invited@example.com", now=100.0))
    assert m["move_odds"] is False
    db.system_config.docs[0]["flags"]["move_odds"] = {"mode": "allowlist", "allowlist": ["invited@example.com"]}   # admin write elsewhere
    assert run(feature_gate.fresh_user_feature_map(db, "invited@example.com", now=110.0))["move_odds"] is False  # within 30 s
    assert run(feature_gate.fresh_user_feature_map(db, "invited@example.com", now=131.0))["move_odds"] is True   # refreshed

    class Broken(_DB):
        def __init__(self):
            super().__init__()
            class C:
                async def find_one(self, *a, **k): raise RuntimeError("mongo down")
            self.system_config = C()
    assert run(feature_gate.fresh_user_feature_map(Broken(), "invited@example.com", now=200.0))["move_odds"] is True   # keeps this worker's copy


def test_live_route_is_gated_validates_symbols_and_passes_the_quote_payload_through(monkeypatch):
    import services.move_odds_live as live

    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    c, _ = _client(monkeypatch, db)
    seen = {}
    async def fake_quotes(symbols, now=None):
        seen["symbols"] = symbols
        return {"source": "Yahoo Finance", "entry_signal_validated": False, "quotes": [{"symbol": s, "last": 1.0, "error": None} for s in symbols]}
    monkeypatch.setattr(live, "live_quotes", fake_quotes)
    assert _get(c, "/api/move-odds/live?symbols=PNCINFRA,antelopus", "other").status_code == 403
    r = _get(c, "/api/move-odds/live?symbols=PNCINFRA,antelopus", "invited")
    assert r.status_code == 200 and seen["symbols"] == ["PNCINFRA", "ANTELOPUS"] and r.json()["entry_signal_validated"] is False
    assert _get(c, "/api/move-odds/live?symbols=", "invited").status_code == 422
    assert _get(c, "/api/move-odds/live?symbols=" + ",".join(f"S{i}" for i in range(61)), "invited").status_code == 422
    assert _get(c, "/api/move-odds/live?symbols=PNC;DROP", "invited").status_code == 422


def test_tc56_history_is_behind_the_flag_and_passes_through(monkeypatch):
    """TC-56 in test_reports/move_odds_history_20260918_0820.md."""
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    payload = {"data": {"head": "p_up5_1d", "model": "v4", "top_n": 20, "sessions": [
        {"target_session": "2026-09-17", "state": "graded", "summary": {"touched": 86, "top10_touched": 3},
         "rows": [{"rank": 1, "symbol": "PNCINFRA", "p": 0.366, "is_new": None,
                   "outcome": {"state": "graded", "touched": True, "move_pct": 0.055}}]}]}}
    c, calls = _client(monkeypatch, db, daas=(200, payload))
    r = _get(c, "/api/move-odds/history?head=p_up5_1d&top=20", "invited")
    assert r.status_code == 200 and r.json() == payload                       # passed through unchanged
    assert calls == [("/move-odds/history", {"head": "p_up5_1d", "model": "v4", "sessions": 30, "top": 20})]
    assert _get(c, "/api/move-odds/history", "other").status_code == 403      # not allowlisted
    assert _get(c, "/api/move-odds/history?top=500", "invited").status_code == 422   # bounds enforced before the proxy
