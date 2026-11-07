"""SPT configuration after the owner's decisions of 5 Nov 2026 ~06:50 IST (services/spt/policy.py, services/spt/settings.py,
routes/spt_accounts.py): defaults from the user's risk profile, sparse overrides, tighten-yourself / loosen-by-admin, the
admin routes and the market-wide SPT settings (TESTCASES test_reports/spt_b_TESTCASES.md SPT-CFG-01..10).

MOCK — not real data: every user, profile value, opportunity and bar is made up."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import deps
from services import risk_profile as rp
from services.spt import constants as C, policy
from services.spt import settings as spt_settings
from tests.spt_b_fakes import NOW, U1, FakeDB


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    monkeypatch.setattr(spt_settings, "_cache", {"at": None, "stored": {}, "version": 0})
    for f in spt_settings.FIELDS.values():
        monkeypatch.delenv(f["env"], raising=False)


def store_profile(db, **limits):
    """MOCK — a stored risk profile for U1 (as an admin's PUT /api/admin/risk/{user}/profile would leave it)."""
    doc = {"_id": "mock-profile", "user_id": U1, "profile": "custom", "version": 1, "starting_capital_rs": 1e6,
           "limits": dict(rp.NAMED[rp.OWNER_DEFAULT], **limits)}
    db["risk_profiles"].docs[:] = [doc]


def upd(db, *, admin=False, **kw):
    return run(policy.update(db, U1, actor="admin-1" if admin else U1, actor_is_admin=admin, now=NOW, **kw))


# ── SPT-CFG-01 derived defaults ──────────────────────────────────────────────
def test_spt_cfg_01_defaults_derive_from_the_owner_default_profile():
    c = run(policy.read(FakeDB(), U1))
    ex = c["extras"]
    assert ex["drawdown_ladder"] == {"reduce_at_pct": 3.33, "restrict_at_pct": 6.67, "halt_at_pct": 10.0, "reduce_factor": 0.5}
    assert ex["min_rr"] == {"positional": 1.5} and ex["risk_pct"] == {"positional": 0.5, "intraday": 0.35, "fno": 0.35}
    assert (ex["max_positions"], ex["max_new_per_day"], ex["max_chase_pct"], ex["min_adv_rs"],
            ex["max_adv_participation_pct"], ex["approval_expiry_minutes"]) == (10, 5, 1.0, 10_000_000.0, 5.0, 30)
    src = c["defaults_source"]
    assert src["risk_pct.intraday"] == "risk profile per_trade_risk_pct × 0.7"
    assert src["min_rr.positional"] == "risk profile min_reward_risk"
    assert {src[p] for p in ("max_positions", "max_new_per_day", "max_chase_pct", "min_adv_rs",
                             "max_adv_participation_pct", "approval_expiry_minutes", "drawdown_ladder.reduce_factor",
                             "allocation_buckets_pct.reserve", "stressed_gap_pct")} == {policy.OWNER_APPROVED}
    assert c["profile"]["limits"]["max_drawdown_pct"] == 10.0 and c["warnings"] == []


# ── SPT-CFG-02 a profile change flows through ────────────────────────────────
def test_spt_cfg_02_a_profile_change_flows_through_to_what_is_not_overridden():
    db = FakeDB()
    upd(db, mode="approval", extras={"max_chase_pct": 0.5, "drawdown_ladder": {"reduce_factor": 0.4}})
    store_profile(db, per_trade_risk_pct=0.3, max_drawdown_pct=9.0, min_reward_risk=2.0)
    c = run(policy.read(db, U1))
    assert c["extras"]["risk_pct"] == {"positional": 0.3, "intraday": 0.21, "fno": 0.21}
    assert c["extras"]["drawdown_ladder"] == {"reduce_at_pct": 3.0, "restrict_at_pct": 6.0, "halt_at_pct": 9.0,
                                              "reduce_factor": 0.4}
    assert c["extras"]["min_rr"]["positional"] == 2.0 and c["extras"]["max_chase_pct"] == 0.5
    assert c["overrides"] == {"max_chase_pct": 0.5, "drawdown_ladder": {"reduce_factor": 0.4}}
    [stored] = db.docs(C.ACCOUNT_CONFIG)
    assert "extras" not in stored and stored["overrides"] == c["overrides"]          # only the overrides are stored
    assert [u["extras"]["risk_pct"]["positional"] for u in run(policy.users_in_modes(db, [C.MODE_APPROVAL]))] == [0.3]


# ── SPT-CFG-03 overrides persist; null resets ────────────────────────────────
def test_spt_cfg_03_overrides_persist_and_a_null_removes_one():
    db = FakeDB()
    upd(db, extras={"max_positions": 6, "min_adv_rs": 50_000_000})
    c = run(policy.read(db, U1))
    assert c["overrides"] == {"max_positions": 6, "min_adv_rs": 50_000_000.0} and c["extras"]["max_positions"] == 6
    c = upd(db, admin=True, extras={"max_positions": None}, reason="MOCK back to the default")
    assert c["overrides"] == {"min_adv_rs": 50_000_000.0} and c["extras"]["max_positions"] == 10
    c = upd(db, admin=True, extras={"min_adv_rs": None}, reason="MOCK")
    assert c["overrides"] == {} and c["extras"] == c["defaults"]
    with pytest.raises(policy.ConfigError) as e:                       # nothing left to remove
        upd(db, admin=True, extras={"min_adv_rs": None}, reason="MOCK")
    assert e.value.code == "no_change"


# ── SPT-CFG-04 tighten yourself, loosen by an admin ──────────────────────────
@pytest.mark.parametrize("extras", [
    {"risk_pct": {"positional": 0.4}}, {"drawdown_ladder": {"halt_at_pct": 8.0}}, {"max_positions": 5},
    {"min_rr": {"positional": 2.0}}, {"min_adv_rs": 20_000_000}, {"stressed_gap_pct": 2.0},
    {"allocation_buckets_pct": {"equity_positional": 40, "equity_intraday": 25, "fno": 20, "reserve": 15}},
    {"allocation_buckets_pct": {"equity_positional": 35, "equity_intraday": 35, "fno": 20, "reserve": 10}},  # neutral
    {"approval_expiry_minutes": 10}, {"max_chase_pct": 0.5}, {"max_adv_participation_pct": 2.0},
])
def test_spt_cfg_04_the_account_holder_may_tighten(extras):
    db = FakeDB()
    c = upd(db, extras=extras)
    assert c["version"] == 1
    [row] = db.docs(C.ACCOUNT_CONFIG_VERSIONS)
    assert row["loosened"] == [] and row["actor_is_admin"] is False and row["status"] == "applied"


@pytest.mark.parametrize("extras, loosened", [
    ({"risk_pct": {"positional": 0.6}}, ["risk_pct.positional"]),
    ({"drawdown_ladder": {"halt_at_pct": 12.0}}, ["drawdown_ladder.halt_at_pct"]),
    ({"min_rr": {"positional": 1.0}}, ["min_rr.positional"]),
    ({"min_adv_rs": 5_000_000}, ["min_adv_rs"]),
    ({"max_chase_pct": 2.0}, ["max_chase_pct"]),
    ({"max_new_per_day": 8}, ["max_new_per_day"]),
    ({"approval_expiry_minutes": 60}, ["approval_expiry_minutes"]),
    ({"allocation_buckets_pct": {"equity_positional": 50, "equity_intraday": 25, "fno": 20, "reserve": 5}},
     ["allocation_buckets_pct.reserve"]),
])
def test_spt_cfg_05_a_loosening_needs_an_admin(extras, loosened):
    db = FakeDB()
    with pytest.raises(policy.ConfigError) as e:
        upd(db, extras=extras, reason="please")
    assert (e.value.code, e.value.status, e.value.extra["loosened"]) == ("admin_required", 403, loosened)
    assert db.docs(C.ACCOUNT_CONFIG) == [] and db.docs(C.ACCOUNT_CONFIG_VERSIONS) == []
    with pytest.raises(policy.ConfigError) as e:                       # an admin must say why
        upd(db, admin=True, extras=extras)
    assert e.value.code == "reason_required"
    c = upd(db, admin=True, extras=extras, reason="MOCK admin decision")
    [row] = db.docs(C.ACCOUNT_CONFIG_VERSIONS)
    assert row["loosened"] == loosened and row["actor_is_admin"] is True and row["actor"] == "admin-1"
    assert row["reason"] == "MOCK admin decision" and row["new"]["extras"] == c["extras"]


def test_spt_cfg_06_removing_a_tightening_override_is_judged_by_the_value_it_falls_back_to():
    db = FakeDB()
    upd(db, extras={"max_positions": 6})
    with pytest.raises(policy.ConfigError) as e:                       # 6 → the default 10 is a loosening
        upd(db, extras={"max_positions": None}, reason="back")
    assert e.value.code == "admin_required"
    upd(db, admin=True, extras={"max_positions": 9}, reason="MOCK")            # an admin loosens to 9
    c = upd(db, extras={"max_positions": 7})                            # the holder tightens again
    assert c["extras"]["max_positions"] == 7 and c["version"] == 3
    rows = sorted(db.docs(C.ACCOUNT_CONFIG_VERSIONS), key=lambda r: r["version"])
    assert [(r["actor_is_admin"], r["loosened"]) for r in rows] == [(False, []), (True, ["max_positions"]), (False, [])]
    assert rows[1]["old"]["overrides"] == {"max_positions": 6} and rows[1]["new"]["overrides"] == {"max_positions": 9}


def test_spt_cfg_07_an_admin_risk_above_the_profile_is_capped_where_used():
    db = FakeDB()
    c = upd(db, admin=True, extras={"risk_pct": {"positional": 0.75}}, reason="MOCK")
    assert c["extras"]["risk_pct"]["positional"] == 0.75 and "capped" in c["warnings"][0]
    assert policy.effective_risk_pct(c, "positional", c["profile"]["limits"])["pct"] == 0.5


# ── SPT-CFG-08 routes ────────────────────────────────────────────────────────
USERS = {"u": {"user_id": U1, "email": "u@example.com"},
         "adm": {"user_id": "adm", "email": "adm@example.com", "role": "admin"},
         "adm_self": {"user_id": U1, "email": "u@example.com", "role": "admin"}}


@pytest.fixture
def client(monkeypatch):
    from routes import spt_accounts
    db = FakeDB()
    monkeypatch.setattr(spt_accounts, "db", db)

    async def current_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return dict(USERS[who])
    monkeypatch.setattr(spt_accounts, "get_current_user", current_user)
    monkeypatch.setattr(deps, "get_current_user", current_user)          # what require_role("admin") calls
    app = FastAPI()
    app.include_router(spt_accounts.router)
    app.include_router(spt_accounts.admin_router)
    c = TestClient(app)
    c.db = db
    return c


ADMIN_ROUTES = [("get", f"/api/admin/spt/{U1}/config", None), ("put", f"/api/admin/spt/{U1}/config", {"mode": "auto"}),
                ("get", "/api/admin/spt/settings", None), ("put", "/api/admin/spt/settings", {"values": {}})]


@pytest.mark.parametrize("method, url, body", ADMIN_ROUTES)
def test_spt_cfg_08_admin_routes_need_a_session_and_an_admin(client, method, url, body):
    kw = {"json": body} if body is not None else {}
    assert getattr(client, method)(url, **kw).status_code == 401
    assert getattr(client, method)(url, headers={"X-Test-User": "u"}, **kw).status_code == 403


def test_spt_cfg_08b_user_tightens_user_loosening_is_403_admin_loosens(client):
    A, ADM = {"X-Test-User": "u"}, {"X-Test-User": "adm"}
    r = client.put(f"/api/v1/paper/accounts/{U1}/config", headers=A, json={"mode": "approval", "extras": {"max_positions": 6}})
    assert r.status_code == 200 and r.json()["config"]["extras"]["max_positions"] == 6
    r = client.put(f"/api/v1/paper/accounts/{U1}/config", headers=A, json={"extras": {"max_positions": 9}, "reason": "x"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_required"
    r = client.put(f"/api/admin/spt/{U1}/config", headers=ADM, json={"extras": {"max_positions": 9}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    r = client.put(f"/api/admin/spt/{U1}/config", headers=ADM, json={"extras": {"max_positions": 9}, "reason": "MOCK"})
    assert r.status_code == 200 and r.json()["config"]["extras"]["max_positions"] == 9
    got = client.get(f"/api/admin/spt/{U1}/config", headers=ADM).json()
    for k in ("extras", "overrides", "defaults", "defaults_source", "profile"):
        assert k in got["config"], k
    assert [v["version"] for v in got["versions"]] == [2, 1] and got["versions"][0]["actor"] == "adm"
    assert got["versions"][0]["actor_is_admin"] is True
    r = client.put(f"/api/v1/paper/accounts/{U1}/config", headers={"X-Test-User": "adm_self"},
                   json={"extras": {"max_positions": 10}, "reason": "MOCK an admin on their own account"})
    assert r.status_code == 200 and r.json()["config"]["extras"]["max_positions"] == 10


# ── SPT-CFG-09 market-wide settings ──────────────────────────────────────────
def test_spt_cfg_09_settings_validate_version_and_overlay(monkeypatch):
    db = FakeDB()
    s = run(spt_settings.read(db))
    assert s["values"] == {"min_adv_rs": 10_000_000.0, "positional_window_sessions": 5, "validate_max_per_round": 60,
                           "quote_max_age_s": 120.0} and set(s["sources"].values()) == {"default"}
    monkeypatch.setenv("SPT_QUOTE_MAX_AGE_S", "90")
    assert run(spt_settings.read(db))["values"]["quote_max_age_s"] == 90.0 and spt_settings.quote_max_age_s() == 90.0
    for changes, reason, code in (({"quote_max_age_s": 1}, "x", "out_of_range"), ({"nope": 1}, "x", "unknown_field"),
                                  ({"positional_window_sessions": 2.5}, "x", "invalid_number"),
                                  ({"min_adv_rs": 5e7}, "", "reason_required"), ({}, "x", "invalid_body")):
        with pytest.raises(spt_settings.SettingsError) as e:
            run(spt_settings.update(db, actor="adm", changes=changes, reason=reason))
        assert e.value.code == code
    out = run(spt_settings.update(db, actor="adm", changes={"min_adv_rs": 5e7, "quote_max_age_s": 60}, reason="MOCK",
                                  now=NOW))
    assert out["values"]["min_adv_rs"] == 5e7 and out["sources"]["quote_max_age_s"] == "spt_settings (admin)"
    env = spt_settings.overlay({"SPT_MIN_ADV_RS": "1", "OTHER": "kept"})              # the cache was refreshed by update
    assert env["SPT_MIN_ADV_RS"] == "50000000.0" and env["SPT_QUOTE_MAX_AGE_S"] == "60.0" and env["OTHER"] == "kept"
    assert spt_settings.quote_max_age_s() == 60.0
    from services.spt import proposals
    from services.spt.paper import config as c_config
    from services.spt.opportunities import runner, validate as val
    from services.spt.signals import clock
    assert proposals.quote_max_age_s() == 60.0 and c_config.quote_max_age_s() == 60.0           # slices B and C
    assert val.policy()["min_adv_rs"] == 5e7 and clock.window_sessions() == 5 and runner.max_per_round() == 60   # A
    out = run(spt_settings.update(db, actor="adm", changes={"quote_max_age_s": None, "positional_window_sessions": 7,
                                                            "validate_max_per_round": 30}, reason="MOCK",
                                  now=NOW + timedelta(minutes=1)))
    assert out["values"]["quote_max_age_s"] == 90.0 and out["sources"]["quote_max_age_s"] == "env SPT_QUOTE_MAX_AGE_S"
    assert clock.window_sessions() == 7 and runner.max_per_round() == 30 and c_config.quote_max_age_s() == 90.0
    rows = sorted(db.docs(spt_settings.SETTINGS_VERSIONS), key=lambda r: r["version"])
    assert [(r["version"], r["status"], r["actor"]) for r in rows] == [(1, "applied", "adm"), (2, "applied", "adm")]
    assert rows[1]["old"]["stored"] == {"min_adv_rs": 5e7, "quote_max_age_s": 60.0}
    with pytest.raises(spt_settings.SettingsError) as e:
        run(spt_settings.update(db, actor="adm", changes={"min_adv_rs": 6e7}, reason="x", expected_version=1))
    assert e.value.code == "concurrent_change" and e.value.status == 409


def test_spt_cfg_09b_settings_routes(client):
    ADM = {"X-Test-User": "adm"}
    r = client.put("/api/admin/spt/settings", headers=ADM, json={"values": {"min_adv_rs": 2e7}, "reason": "MOCK"})
    assert r.status_code == 200 and r.json()["values"]["min_adv_rs"] == 2e7
    r = client.put("/api/admin/spt/settings", headers=ADM, json={"values": {"min_adv_rs": -1}, "reason": "MOCK"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "out_of_range"
    got = client.get("/api/admin/spt/settings", headers=ADM).json()
    assert got["stored"] == {"min_adv_rs": 2e7} and got["versions"][0]["version"] == 1


def test_spt_cfg_10_slice_a_qualifies_against_the_settings_floor():
    """Slice A's validation reads the admin's floor (₹50 crore, MOCK) over the env/default ₹1 crore: the same liquid
    MOCK stock (≈ ₹10 crore a day) that qualifies by default is REJECTED liquidity_too_low under it."""
    from services.spt.opportunities import validate as val
    from tests.spt_a_fakes import DB as ADB, Inputs, reset_module_state
    from tests.test_spt_a_opportunities import NOW as A_NOW, market, qualified_setup

    reset_module_state()
    db = ADB()
    o = qualified_setup(db)
    run(spt_settings.update(db, actor="adm", changes={"min_adv_rs": 5e8}, reason="MOCK floor", now=NOW))
    r = asyncio.run(val.validate(db, o["_id"], inputs=Inputs(market()), now=A_NOW))
    assert r["state"] == C.OPP_REJECTED and r["validation"]["reason_codes"] == ["liquidity_too_low"]
    assert "below the minimum ₹50.00 cr" in r["validation"]["explanations"][0]
    reset_module_state()
    db2 = ADB()
    o2 = qualified_setup(db2)
    run(spt_settings.update(db2, actor="adm", changes={"min_adv_rs": 1e7}, reason="MOCK floor back", now=NOW))
    assert asyncio.run(val.validate(db2, o2["_id"], inputs=Inputs(market()), now=A_NOW))["state"] == C.OPP_QUALIFIED
