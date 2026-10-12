"""services/portfolio_direct_push.sync_portfolio_to_nidp — the one entry point
for sending user portfolio data to NIDP. The pushers and the Query API client
are stubbed; nothing here touches a database or the network."""
import asyncio

import pytest

from services import nidp_query_client, portfolio_direct_push as pdp, portfolio_gcs_export as gcs


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def direct(monkeypatch):
    calls = []

    def pusher(kind, fail=False):
        async def _p(db, target_date=None):
            calls.append((kind, target_date))
            if fail:
                raise RuntimeError(f"{kind} push 502")
            return {"exported": 3, "via": "direct"}
        return _p

    monkeypatch.setattr(nidp_query_client, "is_configured", lambda: True)
    monkeypatch.setattr(pdp, "_PUSHERS", {k: pusher(k) for k in ("holdings", "transactions", "goals")})
    return calls, pusher


def test_pushes_all_three_kinds_over_http_when_the_query_api_is_configured(direct):
    calls, _ = direct
    out = _run(pdp.sync_portfolio_to_nidp(object()))
    assert out["via"] == "direct"
    assert [k for k, _ in calls] == ["holdings", "transactions", "goals"]
    assert out["goals"] == {"exported": 3, "via": "direct"}


def test_include_limits_what_is_sent(direct):
    calls, _ = direct
    out = _run(pdp.sync_portfolio_to_nidp(object(), include=("holdings",)))
    assert [k for k, _ in calls] == ["holdings"] and "goals" not in out


def test_one_failing_kind_is_reported_and_does_not_stop_the_others(direct, monkeypatch):
    calls, pusher = direct
    monkeypatch.setattr(pdp, "_PUSHERS", {"holdings": pusher("holdings"), "transactions": pusher("transactions", fail=True), "goals": pusher("goals")})
    out = _run(pdp.sync_portfolio_to_nidp(object()))
    assert out["transactions"] == {"error": "transactions push 502"}
    assert out["holdings"]["exported"] == 3 and out["goals"]["exported"] == 3


def test_a_failed_direct_push_never_falls_back_to_gcs(direct, monkeypatch):
    calls, pusher = direct
    monkeypatch.setattr(pdp, "_PUSHERS", {"holdings": pusher("holdings", fail=True)})

    async def gcs_export(*a, **k):
        raise AssertionError("GCS export must not be used when the Query API is configured")
    monkeypatch.setattr(gcs, "export_portfolio_to_gcs", gcs_export)
    out = _run(pdp.sync_portfolio_to_nidp(object(), include=("holdings",)))
    assert "error" in out["holdings"] and out["via"] == "direct"


def test_gcs_export_is_used_only_when_the_query_api_is_not_configured(monkeypatch):
    seen = []

    def exporter(kind):
        async def _e(db, target_date=None):
            seen.append(kind)
            return {"exported": 1}
        return _e
    monkeypatch.setattr(nidp_query_client, "is_configured", lambda: False)
    monkeypatch.setattr(gcs, "export_portfolio_to_gcs", exporter("holdings"))
    monkeypatch.setattr(gcs, "export_cas_transactions_to_gcs", exporter("transactions"))
    monkeypatch.setattr(gcs, "export_user_goals_to_gcs", exporter("goals"))
    out = _run(pdp.sync_portfolio_to_nidp(object()))
    assert out["via"] == "gcs" and seen == ["holdings", "transactions", "goals"]


def test_goals_push_sends_json_safe_records(monkeypatch):
    import datetime, decimal, uuid
    sent = {}

    async def build(db):
        return {"records": [{"goal_id": uuid.UUID(int=1), "external_user_id": "a@example.invalid",
                             "target_amount_rs": decimal.Decimal("1000.50"),
                             "upstream_updated_at": datetime.datetime(2026, 1, 9, 10, 0)}],
                "users": {"a@example.invalid"}, "skipped_no_email": 2}

    async def push_goals(records, snapshot_date):
        sent["records"], sent["date"] = records, snapshot_date
        return {"upserted": 1}
    monkeypatch.setattr(nidp_query_client, "is_configured", lambda: True)
    monkeypatch.setattr(nidp_query_client, "push_goals", push_goals)
    monkeypatch.setattr(gcs, "build_goal_records", build)
    out = _run(pdp.push_goals_direct(object(), target_date=datetime.date(2026, 1, 9)))
    assert out == {"exported": 1, "users": 1, "date": "2026-01-09", "via": "direct", "upserted": 1, "skipped_no_email": 2}
    rec = sent["records"][0]
    assert rec["goal_id"] == "00000000-0000-0000-0000-000000000001" and isinstance(rec["target_amount_rs"], str)
    assert sent["date"] == "2026-01-09"
