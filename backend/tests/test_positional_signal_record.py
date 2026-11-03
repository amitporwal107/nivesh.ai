"""GET /api/positional/signals/{symbol}/record (routes/positional.py): a scanner signal's live revision and every
superseded revision from positional_signals_history (migration 025). TESTCASES S in
test_reports/desk_templates_signal_record_TESTCASES.md.

No database: `pg_client.get_pool` is replaced with a recorder that answers each SQL with fixture rows. MOCK — not real
data: FIXA and its levels are made up. The fixture is a signal re-run twice on 2026-10-20:
    revision 1  entry 100  stop 95  target 110  rr 2.0  EARLY_BREAKOUT  no stop_method        (superseded: rerun)
    revision 2  entry 100  stop 96  target 110  rr 2.5  EARLY_BREAKOUT  structural             (superseded: rerun)
    revision 3  entry 100  stop 96  target 112  rr 3.0  BREAKOUT        structural             (live)
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.positional as route
from services.positional_engine import pipeline

DAY = date(2026, 10, 20)
URL = "/api/positional/signals/FIXA/record?date=2026-10-20"
STOP_METHOD = {"method": "structural", "rule": "MOCK rule", "atr": 2.0}


def _row(revision, stop, target, rr, stage, stop_method=None, superseded_by=None, minute=0):
    r = {"revision": revision, "final_score": Decimal("0.7100"), "confidence": "MEDIUM", "stage": stage,
         "timeframe_days_min": 5, "timeframe_days_max": 15, "entry_price": Decimal("100.0000"),
         "stoploss": Decimal(str(stop)), "target_price": Decimal(str(target)), "risk_reward": Decimal(str(rr)),
         "source_scans": ["MOCK scan"], "reasons": json.dumps(["MOCK reason"]), "engine_version": "v1.4",
         "stop_method": json.dumps(stop_method) if stop_method else None,
         "computed_at": datetime(2026, 10, 20, 14, minute, tzinfo=timezone.utc)}
    if superseded_by:
        r["superseded_at"] = datetime(2026, 10, 20, 15, minute, tzinfo=timezone.utc)
        r["superseded_by"] = superseded_by
    return r


REV1 = _row(1, 95, 110, 2.0, "EARLY_BREAKOUT", superseded_by="rerun", minute=1)
REV2 = _row(2, 96, 110, 2.5, "EARLY_BREAKOUT", STOP_METHOD, superseded_by="rerun", minute=2)
LIVE = _row(3, 96, 112, 3.0, "BREAKOUT", STOP_METHOD, minute=3)


class _Conn:
    def __init__(self, data, calls):
        self.data, self.calls = data, calls

    def _answer(self, sql, args):
        self.calls.append((sql, args))
        if "to_regclass('positional_signals_history')" in sql:
            return [{"hist": self.data["ready"], "cols": 2 if self.data["ready"] else 0}]
        if "GREATEST(" in sql:
            return [{"d": self.data.get("latest")}]
        if "FROM positional_signals_history" in sql:
            return [r for r in self.data["history"] if args == (self.data["symbol"], DAY)]
        if "FROM positional_signals " in sql:
            return [self.data["live"]] if self.data["live"] and args == (self.data["symbol"], DAY) else []
        if "FROM positional_outcomes" in sql:
            if self.data.get("outcomes_error"):
                raise RuntimeError("relation \"positional_outcomes\" does not exist")
            return self.data.get("outcomes", [])
        raise AssertionError(f"unexpected SQL: {sql}")

    async def fetch(self, sql, *args):
        return self._answer(sql, args)

    async def fetchrow(self, sql, *args):
        rows = self._answer(sql, args)
        return rows[0] if rows else None

    async def fetchval(self, sql, *args):
        rows = self._answer(sql, args)
        return next(iter(rows[0].values())) if rows else None


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def _client(monkeypatch, *, live=LIVE, history=(REV1, REV2), ready=True, pool=True, signed_in=True, **extra):
    calls = []
    data = {"live": live, "history": list(history), "ready": ready, "symbol": "FIXA", **extra}

    async def get_pool():
        return _Pool(_Conn(data, calls)) if pool else None

    monkeypatch.setattr(route.pg_client, "get_pool", get_pool)
    monkeypatch.setattr(pipeline, "_history_ready", {})          # the readiness cache is per process
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls


def test_s1_live_signal_with_two_earlier_revisions(monkeypatch):
    c, calls = _client(monkeypatch)
    res = c.get(URL)
    assert res.status_code == 200
    b = res.json()
    assert (b["symbol"], b["signal_date"], b["read_only"], b["revision_count"]) == ("FIXA", "2026-10-20", True, 3)
    cur = b["current"]
    assert cur["revision"] == 3 and cur["levels"] == {"entry": 100.0, "stop": 96.0, "target": 112.0, "risk_reward": 3.0}
    assert cur["stop_method"] == STOP_METHOD and cur["setup"]["stage"] == "BREAKOUT"
    assert cur["setup"]["reasons"] == ["MOCK reason"] and cur["setup"]["final_score"] == 0.71
    assert cur["computed_at"] == "2026-10-20T14:03:00+00:00" and "superseded_by" not in cur
    r1, r2 = b["revisions"]
    assert [r1["revision"], r2["revision"]] == [1, 2]
    assert (r1["superseded_by"], r1["replaced_by_revision"], r2["replaced_by_revision"]) == ("rerun", 2, 3)
    assert r1["levels"]["stop"] == 95.0 and r1["stop_method"] is None
    assert r1["changes"] == [{"field": "stop", "from": 95.0, "to": 96.0},
                             {"field": "risk_reward", "from": 2.0, "to": 2.5},
                             {"field": "stop_method", "from": None, "to": STOP_METHOD}]
    assert r2["changes"] == [{"field": "target", "from": 110.0, "to": 112.0},
                             {"field": "risk_reward", "from": 2.5, "to": 3.0},
                             {"field": "stage", "from": "EARLY_BREAKOUT", "to": "BREAKOUT"}]
    assert b["state"]["live"] is True and b["state"]["stage"] == "BREAKOUT" and b["state"]["outcomes"] == []
    assert b["note"] is None


def test_s2_no_history_is_one_revision_and_says_so(monkeypatch):
    c, _ = _client(monkeypatch, live=_row(1, 95, 110, 2.0, "EARLY_BREAKOUT"), history=())
    b = c.get(URL).json()
    assert b["current"]["revision"] == 1 and b["revisions"] == [] and b["revision_count"] == 1
    assert "No earlier revision" in b["note"]


def test_s3_no_signal_is_404(monkeypatch):
    c, _ = _client(monkeypatch, live=None, history=())
    res = c.get(URL)
    assert res.status_code == 404 and "FIXA" in res.json()["detail"]


def test_s4_history_only_when_a_day_rewrite_removed_the_live_row(monkeypatch):
    gone = _row(1, 95, 110, 2.0, "EARLY_BREAKOUT", superseded_by="replace")
    c, _ = _client(monkeypatch, live=None, history=(gone,))
    b = c.get(URL).json()
    assert b["current"] is None and b["state"]["live"] is False and b["revision_count"] == 1
    (r,) = b["revisions"]
    assert r["superseded_by"] == "replace" and r["changes"] is None and r["replaced_by_revision"] is None
    assert "gone" in b["note"]


def test_s5_history_table_missing_is_503(monkeypatch):
    c, calls = _client(monkeypatch, ready=False)
    res = c.get(URL)
    assert res.status_code == 503 and "signal_history_not_ready" in res.json()["detail"]
    assert not any("FROM positional_signals " in sql for sql, _ in calls)        # nothing read before the check


def test_s6_no_database_is_503(monkeypatch):
    c, _ = _client(monkeypatch, pool=False)
    assert c.get(URL).status_code == 503


@pytest.mark.parametrize("url, code", [
    ("/api/positional/signals/FIXA/record?date=2026-13-01", 400),
    ("/api/positional/signals/FIXA/record?date=yesterday", 400),
    ("/api/positional/signals/FIX%20A;DROP/record?date=2026-10-20", 400),
])
def test_s7_bad_input_is_400(monkeypatch, url, code):
    c, _ = _client(monkeypatch)
    assert c.get(url).status_code == code


def test_s8_requires_sign_in(monkeypatch):
    c, calls = _client(monkeypatch, signed_in=False)
    assert c.get(URL).status_code == 401 and calls == []


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_s9_read_only(monkeypatch, method):
    c, calls = _client(monkeypatch)
    assert getattr(c, method)(URL).status_code == 405
    c.get(URL)
    assert calls and all(sql.lstrip().upper().startswith("SELECT") for sql, _ in calls)


def test_s10_symbol_is_upper_cased_and_date_defaults_to_the_latest(monkeypatch):
    c, calls = _client(monkeypatch, latest=DAY)
    b = c.get("/api/positional/signals/ fixa /record").json()
    assert b["symbol"] == "FIXA" and b["signal_date"] == "2026-10-20" and b["revision_count"] == 3
    assert any("GREATEST(" in sql and args == ("FIXA",) for sql, args in calls)


def test_s10b_no_signal_ever_without_a_date_is_404(monkeypatch):
    c, _ = _client(monkeypatch, latest=None)
    assert c.get("/api/positional/signals/FIXA/record").status_code == 404


def test_outcomes_are_the_stored_rows_or_an_explicit_error(monkeypatch):
    rows = [{"horizon_days": 10, "outcome": "TARGET_HIT", "realised_return_pct": Decimal("12.00"), "bars_to_outcome": 6,
             "evaluated_at": datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)}]
    c, _ = _client(monkeypatch, outcomes=rows)
    assert c.get(URL).json()["state"]["outcomes"] == [{"horizon_days": 10, "outcome": "TARGET_HIT",
                                                       "realised_return_pct": 12.0, "bars_to_outcome": 6,
                                                       "evaluated_at": "2026-11-03T12:00:00+00:00"}]
    c, _ = _client(monkeypatch, outcomes_error=True)
    s = c.get(URL).json()["state"]
    assert s["outcomes"] is None and s["outcomes_error"] == "positional_outcomes could not be read"
