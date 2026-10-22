"""GET /api/onboarding/state reports broker connections and stored holdings, so the
onboarding Portfolio step can tell a portfolio is on file however it arrived."""
import asyncio

import pytest

from routes import onboarding_gmail as og
from services.brokers import sessions as broker_sessions

USER = {"user_id": "u_1"}


class _Collection:
    def __init__(self, doc=None, rows=()):
        self._doc = doc
        self._rows = list(rows)

    async def find_one(self, *_args, **_kwargs):
        return self._doc

    async def count_documents(self, query):
        return sum(1 for r in self._rows if all(r.get(k) == v for k, v in query.items()))


class _Db:
    def __init__(self, *, profile=None, gmail=None, accounts=(), holdings=()):
        self.user_profiles = _Collection(profile)
        self.gmail_tokens = _Collection(gmail)
        self.broker_accounts = _Collection(rows=accounts)
        self.holdings = _Collection(rows=holdings)


@pytest.fixture
def wire(monkeypatch):
    swept = []

    async def _user(_request):
        return USER

    async def _sweep(db, *, user_id=None, now=None):
        swept.append(user_id)
        return 0

    monkeypatch.setattr(og, "get_current_user", _user)
    monkeypatch.setattr(broker_sessions, "expire_due_sessions", _sweep)

    def _run(db):
        monkeypatch.setattr(og, "db", db)
        return asyncio.run(og.onboarding_state(request=None))

    _run.swept = swept
    return _run


def test_nothing_on_file_reports_zeroes_and_keeps_existing_keys(wire):
    state = wire(_Db())
    assert (state["broker_accounts"], state["broker_accounts_live"], state["holdings_count"]) == (0, 0, 0)
    for key in ("onboarding_completed", "pan_on_file", "gmail_connected", "cas_statement_period",
                "cas_portfolio_value_rs", "cas_statement_date", "cas_monthly_values", "persona",
                "persona_confidence", "persona_label", "has_risk_profile"):
        assert key in state


def test_counts_cover_only_the_signed_in_user(wire):
    db = _Db(
        accounts=[
            {"user_id": "u_1", "status": "active"},
            {"user_id": "u_1", "status": "expired"},
            {"user_id": "u_2", "status": "active"},
        ],
        holdings=[{"user_id": "u_1"}] * 3 + [{"user_id": "u_2"}] * 5,
    )
    state = wire(db)
    assert state["broker_accounts"] == 2
    assert state["broker_accounts_live"] == 1
    assert state["holdings_count"] == 3


def test_ended_sessions_are_swept_for_this_user_before_counting(wire):
    wire(_Db())
    assert wire.swept == ["u_1"]


def test_a_failed_sweep_does_not_fail_the_bootstrap(wire, monkeypatch):
    async def _boom(db, *, user_id=None, now=None):
        raise RuntimeError("mongo unavailable")

    monkeypatch.setattr(broker_sessions, "expire_due_sessions", _boom)
    state = wire(_Db(accounts=[{"user_id": "u_1", "status": "active"}]))
    assert state["broker_accounts_live"] == 1
