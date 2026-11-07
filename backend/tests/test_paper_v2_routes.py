"""Paper Trading v2 — every new route: sessions, account ownership, admin, wording and no writes on reads (routes/
spt_paper_v2.py, the stress-test extension in routes/spt_risk.py; TESTCASES PV2-B-01..03, 27, 28).
MOCK — not real data: every user and document here is made up."""
from __future__ import annotations

import re

import pytest

from services import desk_trading as desk
from services import risk_profile
from services.spt import constants as C
from tests.paper_v2_fakes import A, ADM, B, U1, client, world  # noqa: F401 (fixtures)
from tests.test_paper_v2_analytics import seed as seed_trades
from tests.test_paper_v2_overview import seed as seed_overview

GETS = ["/api/v1/paper/overview", f"/api/v1/paper/accounts/{U1}/policy", f"/api/v1/risk/correlation/{U1}",
        f"/api/v1/analytics/account/{U1}", "/api/v1/paper/fno-structures", f"/api/v1/risk/stress-test/{U1}"]
OWNED = [u for u in GETS if f"/{U1}" in u]
PUT = (f"/api/v1/paper/accounts/{U1}/policy", {"expected_version": 0, "values": {"daily_loss_pct": 1.5}})
ADMIN = [("get", f"/api/admin/spt/{U1}/policy", None),
         ("put", f"/api/admin/spt/{U1}/policy", {"expected_version": 0, "values": {"daily_loss_pct": 1.5}, "reason": "x"})]
BANNED = re.compile(r"recommend|\bpicks?\b|suggest", re.IGNORECASE)


# ── PV2-B-01 / 02 / 03 ───────────────────────────────────────────────────────
@pytest.mark.parametrize("url", GETS)
def test_pv2_b_01_every_get_needs_a_session(client, url):
    assert client.get(url).status_code == 401


def test_pv2_b_01b_the_put_needs_a_session(client):
    assert client.put(PUT[0], json=PUT[1]).status_code == 401


@pytest.mark.parametrize("url", OWNED)
def test_pv2_b_02_another_users_account_is_403(client, url):
    r = client.get(url, headers=B)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_your_account"


def test_pv2_b_02b_put_on_another_users_account_is_403_and_writes_nothing(client):
    r = client.put(PUT[0], headers=B, json=PUT[1])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_your_account"
    assert client.world.db.docs(risk_profile.PROFILES) == []


@pytest.mark.parametrize("method, url, body", ADMIN)
def test_pv2_b_03_admin_routes_need_an_admin(client, method, url, body):
    kw = {"json": body} if body is not None else {}
    assert getattr(client, method)(url, **kw).status_code == 401
    assert getattr(client, method)(url, headers=A, **kw).status_code == 403
    assert getattr(client, method)(url, headers=ADM, **kw).status_code == 200


# ── PV2-B-27 wording ─────────────────────────────────────────────────────────
def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def test_pv2_b_27_no_banned_words_in_any_response(client):
    seed_overview(client.world.db)
    seed_trades(client.world.db)
    bodies = [client.get(u, headers=A).json() for u in GETS]
    bodies.append(client.put(f"/api/v1/paper/accounts/{U1}/policy", headers=A,
                             json={"expected_version": 0, "values": {"daily_loss_pct": 3.0}}).json())   # the 403 text
    bodies.append(client.put(f"/api/v1/paper/accounts/{U1}/policy", headers=A,
                             json={"expected_version": 0, "values": {"halt_at_pct": 3}}).json())        # a 422 text
    hits = [s for b in bodies for s in strings(b) if BANNED.search(s)]
    assert hits == []


# ── PV2-B-28 reads write nothing ─────────────────────────────────────────────
WATCHED = (risk_profile.PROFILES, risk_profile.AUDIT, C.ACCOUNT_CONFIG, C.ACCOUNT_CONFIG_VERSIONS, C.PROPOSALS, C.ORDERS,
           C.POSITIONS, C.OPPORTUNITIES, C.SIGNAL_EVENTS, desk.TRADES, "risk_decisions")


def test_pv2_b_28_gets_write_nothing(client):
    db = client.world.db
    seed_overview(db)
    seed_trades(db)
    before = {n: (db[n].writes, [dict(d) for d in db[n].docs]) for n in WATCHED}
    for u in GETS:
        assert client.get(u, headers=A).status_code == 200, u
    assert client.get(f"/api/admin/spt/{U1}/policy", headers=ADM).status_code == 200
    after = {n: (db[n].writes, [dict(d) for d in db[n].docs]) for n in WATCHED}
    assert after == before


def test_pv2_b_20d_stress_route_reads_the_fno_book(client):
    r = client.get(f"/api/v1/risk/stress-test/{U1}", headers=A).json()
    assert r["named"]["book"]["fno_structures"] == 0           # read (empty MOCK book), not failed
    iv = next(s for s in r["scenarios"] if s["name"] == "iv_up")
    assert iv["loss_rs"] == 0.0 and iv["reason"] is None
    import math
    assert all(math.copysign(1.0, s["loss_rs"]) > 0 for s in r["scenarios"] if s.get("loss_rs") is not None)  # no −0.0
