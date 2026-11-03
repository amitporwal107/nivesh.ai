"""A desk paper trade can cite the stored strategy version it came from: `strategy_ref {strategy_id, version_id}` on
POST /api/desk/paper-trades (Strategy Copilot Phase 1.1; PAPER LIVE in Strategy Lab is derived from it).

Covers TC-30 … TC-33 of test_reports/strategy_store_v2_20261028.md. Runs on the in-memory desk world of
tests/test_desk_trading.py (MOCK Mongo, MOCK prices, MOCK user). The strategy store lookup
(`strategy_store.resolve_version_ref`, a Postgres read) is replaced by a dict. MOCK — not real data: invented ids.
"""
from __future__ import annotations

import pytest

from services import strategy_store
from tests.test_desk_trading import A, B, TRADES_URL, api, trade_body, world  # noqa: F401  (fixtures)
from tests.test_fno_roll import OPENED, ROLL_EVENING, body as roll_body, chain, roll_url  # noqa: F401  (fixtures)

SID = "11111111-1111-4111-8111-111111111111"
VID = "22222222-2222-4222-8222-222222222222"
OTHER_VID = "33333333-3333-4333-8333-333333333333"
INDEX_SID = "44444444-4444-4444-8444-444444444444"
INDEX_VID = "55555555-5555-4555-8555-555555555555"

# (owner, strategy_id, version_id) → what the store answers. MOCK.
VERSIONS = {
    ("user_a", SID, VID): {"strategy_id": SID, "version_id": VID, "version_no": 2, "underlying": "FIXA"},
    ("user_a", INDEX_SID, INDEX_VID): {"strategy_id": INDEX_SID, "version_id": INDEX_VID, "version_no": 1,
                                        "underlying": "NIFTY"},
}


@pytest.fixture(autouse=True)
def store_lookup(monkeypatch):
    calls = []

    async def resolve(uid, raw):
        calls.append((uid, raw))
        ref = strategy_store.clean_strategy_ref(raw)              # the real shape check
        found = VERSIONS.get((uid, ref["strategy_id"], ref["version_id"]))
        if found is None:
            raise strategy_store.StoreInputError("invalid_strategy_ref", strategy_store.STRATEGY_REF_UNKNOWN,
                                                 field="strategy_ref")
        return found

    monkeypatch.setattr(strategy_store, "resolve_version_ref", resolve)
    return calls


# ── TC-30: no strategy_ref, no change ────────────────────────────────────────
def test_tc30_a_trade_without_strategy_ref_answers_as_before(api, world, store_lookup):
    r = api.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 201, r.text
    assert "strategy_ref" not in r.json()["trade"]
    [doc] = world.db.trades.docs
    assert "strategy_ref" not in doc
    assert store_lookup == []                                     # the store is not even asked


# ── TC-31: a bad reference is refused and nothing is written ─────────────────
@pytest.mark.parametrize("ref", [
    "not-an-object",
    {"strategy_id": SID},
    {"strategy_id": SID, "version_id": VID, "extra": 1},
    {"strategy_id": "not-a-uuid", "version_id": VID},
    {"strategy_id": SID, "version_id": OTHER_VID},                # unknown version
])
def test_tc31_malformed_or_unknown_strategy_ref_is_422(api, world, ref):
    r = api.post(TRADES_URL, json={**trade_body(), "strategy_ref": ref}, headers=A)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_strategy_ref" and detail["field"] == "strategy_ref"
    assert world.db.trades.docs == []


def test_tc31_another_users_version_is_refused_like_an_unknown_one(api, world):
    r = api.post(TRADES_URL, json={**trade_body(), "strategy_ref": {"strategy_id": SID, "version_id": VID}}, headers=B)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_strategy_ref"
    assert world.db.trades.docs == []


def test_tc31_a_version_of_another_underlying_is_409(api, world):
    r = api.post(TRADES_URL, json={**trade_body(), "strategy_ref": {"strategy_id": INDEX_SID, "version_id": INDEX_VID}},
                 headers=A)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "strategy_ref_mismatch"
    assert world.db.trades.docs == []


# ── TC-32: a valid reference is stored and returned ──────────────────────────
def test_tc32_a_valid_strategy_ref_is_stored_with_the_version_number(api, world):
    r = api.post(TRADES_URL, json={**trade_body(), "strategy_ref": {"strategy_id": SID, "version_id": VID}}, headers=A)
    assert r.status_code == 201, r.text
    want = {"strategy_id": SID, "version_id": VID, "version_no": 2}
    assert r.json()["trade"]["strategy_ref"] == want
    [doc] = world.db.trades.docs
    assert doc["strategy_ref"] == want
    listed = api.get(TRADES_URL, params={"status": "open"}, headers=A).json()
    assert [t.get("strategy_ref") for t in listed["trades"]] == [want]


def test_tc32_a_rolled_trade_keeps_citing_the_strategy(api, chain):
    """The NIFTY spread of tests/test_fno_roll.py, opened with a strategy_ref, rolled on the expiry evening: the new
    structure still cites the stored strategy, so PAPER LIVE does not drop after a roll."""
    chain.now = OPENED
    r = api.post(TRADES_URL, json={**roll_body(), "strategy_ref": {"strategy_id": INDEX_SID, "version_id": INDEX_VID}},
                 headers=A)
    assert r.status_code == 201, r.text
    tid = r.json()["trade"]["id"]
    chain.now = ROLL_EVENING
    rolled = api.post(roll_url(tid), json={}, headers=A)
    assert rolled.status_code == 201, rolled.text
    new = next(d for d in chain.db.trades.docs if d["_id"] == rolled.json()["new"]["id"])
    assert new["strategy_ref"] == {"strategy_id": INDEX_SID, "version_id": INDEX_VID, "version_no": 1}


# ── TC-33: the check route accepts the same body ─────────────────────────────
def test_tc33_check_accepts_a_body_with_strategy_ref(api, world):
    plain = api.post(TRADES_URL + "/check", json=trade_body(), headers=A)
    cited = api.post(TRADES_URL + "/check", json={**trade_body(), "strategy_ref": {"strategy_id": SID, "version_id": VID}},
                     headers=A)
    assert plain.status_code == cited.status_code == 200, cited.text
    keys = ("outcome", "reasons", "requested_qty", "approved_qty", "estimated_risk_rs", "budget", "duplicate")
    # a strategy link changes no risk number
    assert {k: cited.json()[k] for k in keys} == {k: plain.json()[k] for k in keys}
    assert world.db.trades.docs == []
