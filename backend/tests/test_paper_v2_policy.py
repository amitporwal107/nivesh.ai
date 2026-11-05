"""Paper Trading v2 — the combined policy (services/spt/policy_view.py, routes/spt_paper_v2.py; TESTCASES
test_reports/paper_v2_backend_TESTCASES.md PV2-B-04..14). MOCK — not real data: every user and value is made up."""
from __future__ import annotations

import asyncio

import pytest

from services import risk_profile
from services.spt import constants as C
from services.spt import policy, policy_view
from tests.paper_v2_fakes import A, ADM, B, NOW, U1, client, world  # noqa: F401 (fixtures)

KEYS = ["per_trade_risk_pct", "max_open_risk_pct", "daily_loss_pct", "weekly_loss_pct", "restrict_at_pct", "halt_at_pct",
        "max_position_pct", "max_sector_pct", "margin_util_pct", "fno_max_loss_pct", "bucket_positional_pct",
        "bucket_intraday_pct", "bucket_fno_pct", "max_positions"]
META = {"value", "default", "min", "max", "step", "unit", "store", "overridden", "loosen_needs_admin", "label"}


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def write(world, values, *, version=0, admin=False, reason=None, require_reason=False):
    return run(policy_view.write(world.db, U1, values=values, expected_version=version, reason=reason,
                                 actor="adm" if admin else U1, actor_is_admin=admin, require_reason=require_reason, now=NOW))


def stored(world):
    """(profile doc, SPT config doc, profile audit rows, SPT version rows)."""
    db = world.db
    prof = next((d for d in db.docs(risk_profile.PROFILES) if d["user_id"] == U1), None)
    cfg = next((d for d in db.docs(C.ACCOUNT_CONFIG) if d["_id"] == U1), None)
    return prof, cfg, list(db.docs(risk_profile.AUDIT)), list(db.docs(C.ACCOUNT_CONFIG_VERSIONS))


def nothing_written(world):
    prof, cfg, audit, versions = stored(world)
    return prof is None and cfg is None and not audit and not versions


# ── PV2-B-04 GET on a fresh account ──────────────────────────────────────────
def test_pv2_b_04_fresh_account_view(client):
    r = client.get(f"/api/v1/paper/accounts/{U1}/policy", headers=A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body["fields"]) == KEYS
    for k, f in body["fields"].items():
        assert META <= set(f), k
        assert f["min"] <= f["value"] <= f["max"], k
        assert f["store"] in ("risk_profile", "spt")
        assert f["overridden"] is False
    vals = {k: f["value"] for k, f in body["fields"].items()}
    assert vals == {"per_trade_risk_pct": 0.5, "max_open_risk_pct": 3.0, "daily_loss_pct": 2.0, "weekly_loss_pct": 4.0,
                    "restrict_at_pct": 6.67, "halt_at_pct": 10.0, "max_position_pct": 10.0, "max_sector_pct": 25.0,
                    "margin_util_pct": 70.0, "fno_max_loss_pct": 0.35, "bucket_positional_pct": 45.0,
                    "bucket_intraday_pct": 25.0, "bucket_fno_pct": 20.0, "max_positions": 10}
    assert body["version"] == 0 and body["saved_at"] is None
    d = body["derived"]
    assert d["reserve_pct"] == 10.0 and d["per_trade_risk_rs"] == 5000.0          # 0.5 % of the ₹10L simulation default
    assert d["risk_budget_left_pct"] == 3.0 and d["risk_budget_left_rs"] == 30000.0  # nothing open
    assert body["fields"]["halt_at_pct"]["store"] == "risk_profile" and body["fields"]["restrict_at_pct"]["store"] == "spt"
    assert body["defaults_source"]["fno_max_loss_pct"] == "risk profile per_trade_risk_pct × 0.7 (PRD §9.4)"
    assert body["defaults_source"]["margin_util_pct"] == "owner's Paper Trading v2 design (5 Nov); PRD has no figure; configurable"


# ── PV2-B-05 the holder tightens both stores in one write ────────────────────
def test_pv2_b_05_tighten_writes_both_stores_one_version(world):
    out = write(world, {"per_trade_risk_pct": 0.4, "margin_util_pct": 60})
    assert out["version"] == 2
    assert out["fields"]["per_trade_risk_pct"]["value"] == 0.4 and out["fields"]["margin_util_pct"]["value"] == 60.0
    assert out["fields"]["margin_util_pct"]["overridden"] is True
    prof, cfg, audit, versions = stored(world)
    assert prof["limits"]["per_trade_risk_pct"] == 0.4 and prof["version"] == 1
    assert cfg["overrides"] == {"margin_util_pct": 60.0} and cfg["version"] == 1
    assert len(audit) == 1 and audit[0]["reason"] == policy_view.DEFAULT_REASON and audit[0]["loosened"] == []
    assert len(versions) == 1 and versions[0]["status"] == "applied" and versions[0]["loosened"] == []


# ── PV2-B-06 / 07 a loosening by the holder: 403, nothing written ────────────
def test_pv2_b_06_loosen_is_403_and_writes_nothing(world):
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"per_trade_risk_pct": 1.0})
    # the F&O limit is 0.7 × the risk per trade, so it loosens with it (0.35 → 0.7) and is named too
    assert (e.value.status, e.value.code, e.value.extra["loosened"]) == (403, "admin_required",
                                                                         ["per_trade_risk_pct", "fno_max_loss_pct"])
    assert nothing_written(world)


def test_pv2_b_07_tighten_plus_loosen_writes_neither(world):
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"margin_util_pct": 60, "daily_loss_pct": 3.0})
    assert e.value.status == 403 and e.value.extra["loosened"] == ["daily_loss_pct"]
    assert nothing_written(world)


# ── PV2-B-08 version conflict ────────────────────────────────────────────────
def test_pv2_b_08_stale_version_is_409(world):
    write(world, {"margin_util_pct": 60})                                     # version 0 → 1
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"margin_util_pct": 50}, version=0)
    assert (e.value.status, e.value.code, e.value.extra["current_version"]) == (409, "version_conflict", 1)
    assert stored(world)[1]["overrides"] == {"margin_util_pct": 60.0}


# ── PV2-B-09 validation ──────────────────────────────────────────────────────
@pytest.mark.parametrize("values, code, field", [
    ({"per_trade_risk_pct": 9}, "out_of_range", "per_trade_risk_pct"),
    ({"bogus": 1}, "unknown_field", "bogus"),
    ({"daily_loss_pct": "2"}, "invalid_number", "daily_loss_pct"),
    ({"max_positions": 5.5}, "invalid_number", "max_positions"),
    ({"bucket_fno_pct": 40}, "reserve_negative", "bucket_fno_pct"),
    ({"halt_at_pct": 5, "restrict_at_pct": 5}, "halt_not_above_restricted", "halt_at_pct"),
    ({"restrict_at_pct": 1.0}, "ladder_not_ascending", "restrict_at_pct"),
    ({"max_open_risk_pct": 0.3}, "open_risk_below_per_trade", "max_open_risk_pct"),
    ({"weekly_loss_pct": 1.0}, "weekly_below_daily", "weekly_loss_pct"),
    ({"margin_util_pct": 70}, "no_change", None),
    ({}, "invalid_body", "values"),
])
def test_pv2_b_09_bad_input_is_422_and_writes_nothing(world, values, code, field):
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, values, admin=True, reason="MOCK")
    assert (e.value.status, e.value.code, e.value.field) == (422, code, field)
    assert set(e.value.detail()) >= {"code", "field", "message"}
    assert nothing_written(world)


# ── PV2-B-10 the second store fails: the first is restored ───────────────────
def test_pv2_b_10_spt_first_then_profile_fails_spt_is_restored(world, monkeypatch):
    """SPT config first (its new override is valid under today's profile); the profile write fails → the SPT write is
    undone."""
    async def broken(*a, **kw):
        raise RuntimeError("MOCK: the profile store is down")
    monkeypatch.setattr(risk_profile, "set_limits", broken)
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"per_trade_risk_pct": 0.4, "margin_util_pct": 60})
    assert (e.value.status, e.value.code, e.value.extra["rolled_back"]) == (500, "policy_write_failed", True)
    prof, cfg, audit, versions = stored(world)
    assert prof is None and audit == []                                              # the profile never changed
    assert cfg["overrides"] == {} and cfg["version"] == 2                            # written, then put back
    assert [v["status"] for v in versions] == ["applied", "applied"]
    assert versions[1]["reason"].startswith("rollback") and versions[1]["new"]["overrides"] == {}


def test_pv2_b_10b_profile_first_then_spt_fails_profile_is_restored(world, monkeypatch):
    """A ladder valid only under the new halt (restricted 3.2 is under ⅓ of the old halt 10) → the profile goes first;
    the SPT write fails → the profile is put back."""
    async def broken(*a, **kw):
        raise RuntimeError("MOCK: the SPT store is down")
    monkeypatch.setattr(policy, "update", broken)
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"halt_at_pct": 4.5, "restrict_at_pct": 3.0, "daily_loss_pct": 1.5})
    assert (e.value.status, e.value.code, e.value.extra["rolled_back"]) == (500, "policy_write_failed", True)
    prof, cfg, audit, versions = stored(world)
    assert prof["limits"] == risk_profile.NAMED[risk_profile.OWNER_DEFAULT]          # back to what it was
    assert cfg is None and versions == []
    assert [a["version_after"] for a in audit] == [1, 2]
    assert audit[1]["reason"].startswith("rollback") and audit[1]["changes"]["max_drawdown_pct"] == {"before": 4.5, "after": 10.0}


def test_pv2_b_10c_a_failed_restore_says_what_is_left(world, monkeypatch):
    async def broken(*a, **kw):
        raise RuntimeError("MOCK: the SPT store is down")
    monkeypatch.setattr(policy, "update", broken)
    real = risk_profile.set_limits
    calls = []

    async def second_fails(*a, **kw):
        calls.append(kw.get("reason"))
        if len(calls) == 2:
            raise risk_profile.ProfileError("concurrent_change", "MOCK: someone else changed it")
        return await real(*a, **kw)
    monkeypatch.setattr(risk_profile, "set_limits", second_fails)
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"halt_at_pct": 4.5, "restrict_at_pct": 3.0})
    assert (e.value.status, e.value.code) == (500, "policy_rollback_failed")
    assert e.value.extra == {"rolled_back": False, "written": ["max_drawdown_pct"]}


def test_pv2_b_10d_profile_race_is_409_and_the_spt_part_is_undone(world, monkeypatch):
    async def raced(*a, **kw):
        raise risk_profile.ProfileError("concurrent_change", "MOCK race")
    monkeypatch.setattr(risk_profile, "set_limits", raced)
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"per_trade_risk_pct": 0.4, "margin_util_pct": 60})
    assert (e.value.status, e.value.code, e.value.extra["rolled_back"]) == (409, "version_conflict", True)
    assert stored(world)[1]["overrides"] == {}


def test_pv2_b_10e_profile_first_and_spt_judges_against_the_new_halt(world):
    """Halt 10 → 4.5 (tighter) with restricted 6.67 → 3.2 (tighter than before, but above ⅔ × 4.5 = 3.0, the new
    default): the SPT store calls that a loosening → 403 for the holder, and the profile part is put back."""
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"halt_at_pct": 4.5, "restrict_at_pct": 3.2})
    assert (e.value.status, e.value.code, e.value.extra["rolled_back"]) == (403, "admin_required", True)
    prof, cfg, audit, _ = stored(world)
    assert prof["limits"]["max_drawdown_pct"] == 10.0 and cfg is None and len(audit) == 2


def test_pv2_b_10f_both_orders_write_both_stores(world):
    out = write(world, {"halt_at_pct": 9.0, "restrict_at_pct": 5.0})                 # SPT first (valid under halt 10)
    assert (out["fields"]["halt_at_pct"]["value"], out["fields"]["restrict_at_pct"]["value"], out["version"]) == (9.0, 5.0, 2)
    out = write(world, {"halt_at_pct": 4.5, "restrict_at_pct": 2.9}, version=2)       # profile first (2.9 < ⅓ × 9)
    assert (out["fields"]["halt_at_pct"]["value"], out["fields"]["restrict_at_pct"]["value"], out["version"]) == (4.5, 2.9, 4)


# ── PV2-B-11 null = back to the default ──────────────────────────────────────
def test_pv2_b_11_null_resets(world):
    write(world, {"per_trade_risk_pct": 0.4, "margin_util_pct": 60})
    out = write(world, {"per_trade_risk_pct": None, "margin_util_pct": None}, version=2, admin=True, reason="MOCK reset")
    assert out["fields"]["per_trade_risk_pct"]["value"] == 0.5 and out["fields"]["margin_util_pct"]["value"] == 70.0
    assert out["fields"]["margin_util_pct"]["overridden"] is False
    assert stored(world)[1]["overrides"] == {}


# ── PV2-B-12 admin ───────────────────────────────────────────────────────────
def test_pv2_b_12_admin_loosens_with_a_reason(world):
    with pytest.raises(policy_view.PolicyError) as e:
        write(world, {"per_trade_risk_pct": 1.0}, admin=True)
    assert (e.value.status, e.value.code) == (422, "reason_required")
    out = write(world, {"per_trade_risk_pct": 1.0, "halt_at_pct": 12}, admin=True, reason="MOCK admin decision")
    assert out["fields"]["per_trade_risk_pct"]["value"] == 1.0 and out["fields"]["halt_at_pct"]["value"] == 12.0
    assert out["fields"]["restrict_at_pct"]["value"] == 8.0                     # ⅔ of the new halt, re-derived
    audit = stored(world)[2]
    assert audit[-1]["actor_is_admin"] is True and audit[-1]["reason"] == "MOCK admin decision"


# ── PV2-B-13 buckets ─────────────────────────────────────────────────────────
def test_pv2_b_13_buckets_move_reserve_rule(world):
    out = write(world, {"bucket_positional_pct": 40, "bucket_fno_pct": 25})       # 40+25+25 = 90: reserve stays 10
    assert out["derived"]["reserve_pct"] == 10.0
    assert stored(world)[1]["overrides"]["allocation_buckets_pct"] == {"equity_positional": 40.0, "fno": 25.0}
    with pytest.raises(policy_view.PolicyError) as e:                            # reserve 10 → 5: looser
        write(world, {"bucket_fno_pct": 30}, version=1)
    assert e.value.status == 403 and e.value.extra["loosened"] == ["bucket_fno_pct"]
    out = write(world, {"bucket_fno_pct": 33}, version=1, admin=True, reason="MOCK")
    assert out["derived"]["reserve_pct"] == 2.0 and any("under the 5%" in n for n in out["notes"])
    assert stored(world)[1]["overrides"]["allocation_buckets_pct"]["reserve"] == 2.0


# ── PV2-B-14 the new SPT extras ──────────────────────────────────────────────
def test_pv2_b_14_new_extras_in_the_spt_config(world):
    cfg = run(policy.read(world.db, U1))
    assert cfg["extras"]["margin_util_pct"] == 70.0 and cfg["extras"]["fno_max_loss_pct"] == 0.35   # 0.7 × 0.5
    assert cfg["defaults_source"]["fno_max_loss_pct"] == "risk profile per_trade_risk_pct × 0.7 (PRD §9.4)"
    assert "PRD has no figure" in cfg["defaults_source"]["margin_util_pct"]
    with pytest.raises(policy.ConfigError) as e:                                     # 0.35 → 0.5 is looser
        run(policy.update(world.db, U1, actor=U1, extras={"fno_max_loss_pct": 0.5}, now=NOW))
    assert e.value.status == 403 and e.value.extra["loosened"] == ["fno_max_loss_pct"]
    c = run(policy.update(world.db, U1, actor=U1, extras={"fno_max_loss_pct": 0.3}, now=NOW))
    assert c["extras"]["fno_max_loss_pct"] == 0.3
    with pytest.raises(policy.ConfigError) as e:
        run(policy.update(world.db, U1, actor=U1, extras={"margin_util_pct": 80}, now=NOW))
    assert e.value.status == 403 and e.value.extra["loosened"] == ["margin_util_pct"]


# ── over HTTP ────────────────────────────────────────────────────────────────
def test_pv2_b_05_06_08_over_http(client):
    url = f"/api/v1/paper/accounts/{U1}/policy"
    r = client.put(url, headers=A, json={"expected_version": 0, "values": {"daily_loss_pct": 1.5}})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1 and r.json()["fields"]["daily_loss_pct"]["value"] == 1.5
    r = client.put(url, headers=A, json={"expected_version": 1, "values": {"daily_loss_pct": 3}})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_required"
    assert r.json()["detail"]["loosened"] == ["daily_loss_pct"]
    r = client.put(url, headers=A, json={"expected_version": 0, "values": {"daily_loss_pct": 1.0}})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"
    r = client.put(url, headers=A, json={"expected_version": 1, "values": {"daily_loss_pct": 99}})
    assert r.status_code == 422 and r.json()["detail"] == {"code": "out_of_range", "field": "daily_loss_pct",
                                                            "message": "Daily loss limit must be between 0.1 and 20%"}
    r = client.put(url, headers=A, json={"expected_version": 1, "values": {"daily_loss_pct": 1.0}, "extra": 1})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_field"
    r = client.put(url, headers=A, json={"values": {"daily_loss_pct": 1.0}})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "expected_version"


def test_pv2_b_12_admin_routes_over_http(client):
    url = f"/api/admin/spt/{U1}/policy"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=A).status_code == 403
    r = client.get(url, headers=ADM)
    assert r.status_code == 200 and r.json()["version"] == 0
    r = client.put(url, headers=ADM, json={"expected_version": 0, "values": {"max_positions": 8}})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "reason_required"
    r = client.put(url, headers=ADM, json={"expected_version": 0, "values": {"per_trade_risk_pct": 0.8}, "reason": "MOCK"})
    assert r.status_code == 200 and r.json()["fields"]["per_trade_risk_pct"]["value"] == 0.8
    assert r.json()["saved_by"] == "adm"
    assert client.put(url, headers=B, json={"expected_version": 1, "values": {"max_positions": 8}}).status_code == 403


def test_pv2_b_11b_a_full_draft_does_not_pin_unchanged_values(world):
    """A draft that sends every field with only halt changed: only the profile moves; restrict follows the new halt
    (⅔ of it) because sending its old value is not a change."""
    vals = {k: f["value"] for k, f in policy_view.view(risk_profile.default_state(U1), policy.default_state(U1))["fields"].items()}
    vals["halt_at_pct"] = 9.0
    out = write(world, vals)
    assert out["fields"]["halt_at_pct"]["value"] == 9.0 and out["fields"]["restrict_at_pct"]["value"] == 6.0
    prof, cfg, _, _ = stored(world)
    assert cfg is None and prof["limits"]["max_drawdown_pct"] == 9.0 and out["version"] == 1


def test_pv2_b_14b_fno_max_loss_follows_the_profile(world):
    """No override: fno_max_loss_pct = 0.7 × the profile's risk per trade, so tightening the profile moves it."""
    out = write(world, {"per_trade_risk_pct": 0.4})
    assert out["fields"]["fno_max_loss_pct"]["value"] == 0.28 and out["fields"]["fno_max_loss_pct"]["overridden"] is False
    assert stored(world)[1] is None                                                  # nothing stored in the SPT config
