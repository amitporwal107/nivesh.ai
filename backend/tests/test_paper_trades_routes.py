"""App routes /api/paper-trades and the live target/stop status (TC-P21, TC-P22 in test_reports/paper_trades_engine_20260918_1338.md).
No Mongo, no DaaS, no Yahoo: the user resolver, flag store, DaaS call and bars are injected, so gate, proxy and status logic run for real."""
import copy
from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate
from services import paper_trades_live as live

IST = timezone(timedelta(hours=5, minutes=30))


class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return copy.deepcopy(d)
        return None


class _DB:
    def __init__(self, flags=None):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll([])


USERS = {"invited": {"user_id": "u1", "email": "invited@example.com", "role": "user"},
         "other": {"user_id": "u2", "email": "other@example.com", "role": "user"},
         "admin": {"user_id": "u3", "email": "admin@example.com", "role": "admin", "is_admin": True}}
ALLOW = {"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}}
PAYLOAD = {"data": {"status": "ok", "positions": [{"symbol": "PNCINFRA"}]}}


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def _client(monkeypatch, db, daas=(200, PAYLOAD), configured=True):
    import routes.paper_trades as pt
    from services.copilot_tools import daas_client

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("move_odds", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    calls = []
    async def get_raw(path, params=None, timeout=30):
        calls.append((path, params))
        if isinstance(daas, Exception):
            raise daas
        return daas
    monkeypatch.setattr(daas_client, "get_raw", get_raw)
    monkeypatch.setattr(daas_client, "is_configured", lambda: configured)
    app = FastAPI(); app.include_router(pt.router)
    for route in app.routes:
        for dep in getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []:
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app), calls


def _get(c, path, who):
    return c.get(path, headers={"X-Test-User": who})


# ── TC-P21: gate, pass-through, upstream failures ──────────────────────────────────────────────────────────────────
def test_only_the_move_odds_allowlist_gets_in(monkeypatch):
    c, calls = _client(monkeypatch, _DB(flags=ALLOW))
    for path in ("/api/paper-trades/portfolio", "/api/paper-trades/trades/5", "/api/paper-trades/evaluation", "/api/paper-trades/live"):
        for who in ("other", "admin"):
            r = _get(c, path, who)
            assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled", (path, who)
    assert calls == []


def test_pass_through_unchanged_with_the_right_params(monkeypatch):
    c, calls = _client(monkeypatch, _DB(flags=ALLOW))
    r = _get(c, "/api/paper-trades/portfolio?sample=replay&portfolio=P10-NEXT&prediction_date=2025-03-10", "invited")
    assert r.status_code == 200 and r.json() == PAYLOAD
    assert calls[-1] == ("/paper-trades/portfolio", {"sample": "replay", "portfolio": "P10-NEXT", "top": 25, "prediction_date": "2025-03-10"})
    assert _get(c, "/api/paper-trades/portfolio", "invited").status_code == 200
    assert calls[-1] == ("/paper-trades/portfolio", {"sample": "forward", "portfolio": "P5-NEXT", "top": 25})
    assert _get(c, "/api/paper-trades/trades/536", "invited").status_code == 200 and calls[-1] == ("/paper-trades/trades/536", {})
    assert _get(c, "/api/paper-trades/evaluation?sample=replay", "invited").status_code == 200
    assert calls[-1] == ("/paper-trades/evaluation", {"sample": "replay", "portfolio": "P5-NEXT"})
    for bad in ("/api/paper-trades/portfolio?portfolio=P20-NEXT", "/api/paper-trades/portfolio?sample=live", "/api/paper-trades/trades/0",
                "/api/paper-trades/portfolio?prediction_date=18-09-2026"):
        assert _get(c, bad, "invited").status_code == 422, bad


def test_upstream_failures(monkeypatch):
    from services.copilot_tools.daas_client import DaasError
    db = _DB(flags=ALLOW)
    c, _ = _client(monkeypatch, db, daas=DaasError("connect refused"))
    r = _get(c, "/api/paper-trades/portfolio", "invited"); assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable"
    c, _ = _client(monkeypatch, db, daas=(404, {"error": {"status": 404}}))
    assert _get(c, "/api/paper-trades/trades/99", "invited").status_code == 404
    c, _ = _client(monkeypatch, db, configured=False)
    assert _get(c, "/api/paper-trades/evaluation", "invited").status_code == 502
    c, _ = _client(monkeypatch, db, daas=(200, {"data": {"status": "empty", "dates": []}}))
    assert _get(c, "/api/paper-trades/live", "invited").json() == {"data": {"status": "empty", "portfolio": "P5-NEXT", "positions": []}}


# ── TC-P22: live target/stop status on the pre-registered levels ──────────────────────────────────────────────────────
def test_levels_reproduce_the_engine_numbers_stored_on_staging():
    # nidp.tpd_paper_trades, forward 2026-09-16: PNCINFRA (P5, k 1.5) and DELTACORP (P10, k 2.0)
    p = live.levels(132.48, 9.592995, None, 1.5, 5.0)
    assert p["stop"] == pytest.approx(121.8816) and p["stop_method"] == "CAP_8PCT" and p["target"] == pytest.approx(139.104)
    d = live.levels(55.56, 1.924319, 51.66, 2.0, 10.0)
    assert d["stop"] == pytest.approx(51.66) and d["stop_method"] == "SUPPORT" and d["target"] == pytest.approx(61.116)
    a = live.levels(500.0, 12.0, 490.0, 1.5, 5.0)
    assert a["stop"] == pytest.approx(482.0) and a["stop_method"] == "ATR"
    assert live.levels(None, 12.0, None, 1.5, 5.0) is None and live.levels(500.0, None, None, 1.5, 5.0) is None


def _b(hhmm, o, h, l, c, day=date(2026, 9, 21)):
    hh, mm = map(int, hhmm.split(":"))
    return {"start": datetime.combine(day, time(hh, mm), tzinfo=IST), "open": o, "high": h, "low": l, "close": c}


def test_first_touch_rules():
    bars = [_b("09:15", 100, 101, 99, 100), _b("09:20", 100, 106, 95, 103), _b("09:25", 103, 107, 102, 106)]
    hit = live.first_touch(bars, 96.0, 105.0, gap_rule=False)
    assert hit["kind"] == "stop" and hit["at"].strftime("%H:%M") == "09:20"            # both in one bar: the stop counts
    hit = live.first_touch([_b("09:15", 100, 101, 99, 100), _b("09:20", 100, 105.5, 99, 105)], 96.0, 105.0, gap_rule=False)
    assert hit["kind"] == "target" and hit["price"] == 105.0
    assert live.first_touch([_b("09:15", 94, 99, 93, 98)], 96.0, 105.0, gap_rule=True) == {"kind": "stop", "price": 94, "at": bars[0]["start"], "gap": True}
    assert live.first_touch([_b("09:15", 107, 108, 106, 107)], 96.0, 105.0, gap_rule=True)["kind"] == "target"
    assert live.first_touch([_b("09:15", 94, 99, 93, 98)], 96.0, 105.0, gap_rule=False)["price"] == 96.0   # entry day: no gap rule
    assert live.first_touch([_b("09:15", 100, 101, 99, 100)], 96.0, 105.0, gap_rule=False) is None


def _pos(**over):
    p = {"trade_id": 1, "symbol": "PNCINFRA", "intended_entry_date": "2026-09-21", "status": "PENDING_ENTRY", "status_reason": None, "entry_price": None,
         "prev_close": 132.0, "atr_14": 9.592995, "support_level": None, "stop_loss_price": None, "stop_method": None, "target_1_price": None,
         "target_2_price": None, "exits": {}}
    p.update(over)
    return p


CFG = {"target_pct": 5.0, "atr_multiplier": 1.5}


def test_position_states():
    today = date(2026, 9, 21)
    s = live.position_status(_pos(), CFG, None, date(2026, 9, 19), time(11, 0))
    assert s["state"] == "awaiting_open" and "2026-09-21" in s["note"]                     # weekend before the entry session
    assert live.position_status(_pos(), CFG, None, today, time(9, 5))["state"] == "awaiting_open"
    assert live.position_status(_pos(), CFG, None, today, time(10, 0))["state"] == "unavailable"          # Yahoo did not answer
    assert live.position_status(_pos(), CFG, [], today, time(10, 0))["state"] == "awaiting_open"         # no bars of today
    bars = [_b("09:15", 132.48, 133.0, 131.0, 132.9), _b("09:20", 132.9, 134.0, 132.5, 133.5)]
    s = live.position_status(_pos(), CFG, bars, today, time(9, 30))
    assert s["state"] == "holding" and s["provisional"] and s["entry_source"] == "yahoo_first_bar"
    assert s["entry"] == 132.48 and s["stop"] == 121.88 and s["stop_method"] == "CAP_8PCT" and s["target"] == 139.1
    assert s["return_from_entry"] == pytest.approx(133.5 / 132.48 - 1) and s["note"] == "neither level touched yet"
    s = live.position_status(_pos(), CFG, bars + [_b("11:05", 138, 139.5, 137.9, 139)], today, time(11, 10))
    assert s["state"] == "target" and s["at"] == "11:05" and s["label"] == "Exit · target"
    uc = [_b("09:15", 138.6, 138.6, 138.6, 138.6)]                                                # opened locked 5% up
    assert live.position_status(_pos(), CFG, uc, today, time(9, 30))["state"] == "no_entry"
    assert live.position_status(_pos(), CFG, bars, today, time(15, 45))["note"] == "carry to next session"


def test_official_levels_and_recorded_exits_win():
    day2 = date(2026, 9, 22)
    off = _pos(status="MONITORING", entry_price=132.48, stop_loss_price=121.8816, stop_method="CAP_8PCT", target_1_price=139.104)
    s = live.position_status(off, CFG, [_b("09:15", 120, 121, 119, 120, day2)], day2, time(9, 20))
    assert s["state"] == "stop" and s["entry_source"] == "official" and not s["provisional"] and s["note"].startswith("opened beyond")
    closed = _pos(status="EVALUATED", entry_price=132.48, exits={"TARGET_STOP": {"state": "CLOSED", "target_hit": True, "stop_hit": False, "exit_date": "2026-09-21"}})
    s = live.position_status(closed, CFG, None, day2, time(10, 0))
    assert s["state"] == "exited_target" and "2026-09-21" in s["note"]
    assert live.position_status(_pos(status="ENTRY_UNAVAILABLE", status_reason="UPPER_CIRCUIT_OPEN"), CFG, None, day2, time(10, 0))["state"] == "no_entry"
    late = live.position_status(_pos(), CFG, [_b("09:15", 130, 131, 129, 130, day2)], day2, time(10, 0))
    assert late["state"] == "unavailable" and "tonight" in late["note"]            # entry day passed, official record not in yet


def test_bars_of_another_day_are_never_used():
    fri = datetime(2026, 9, 18, 15, 25, tzinfo=IST).timestamp()
    mon = datetime(2026, 9, 21, 9, 15, tzinfo=IST).timestamp()
    res = {"timestamp": [int(fri), int(mon)], "indicators": {"quote": [{"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, None]}]}}
    assert live.bars5(res, date(2026, 9, 21)) == []                           # Monday's only bar is incomplete; Friday's is dropped
    assert [b["open"] for b in live.bars5(res, date(2026, 9, 18))] == [1.0]
    assert live.bars5(None, date(2026, 9, 21)) == []


def test_live_status_counts(monkeypatch):
    import asyncio
    async def fake_bars(client, sem, symbol, day):
        return {"A": [_b("09:15", 100, 106, 99.5, 105.5)], "B": [_b("09:15", 100, 100.5, 91, 92)], "C": None}.get(symbol)
    monkeypatch.setattr(live, "_bars", fake_bars)
    pf = {"prediction_date": "2026-09-18", "portfolio": "P5-NEXT", "config": CFG,
          "positions": [_pos(symbol=s, trade_id=k, atr_14=1.0) for k, s in enumerate("ABC")] + [_pos(symbol="D", trade_id=9, status="ENTRY_UNAVAILABLE")]}
    out = asyncio.run(live.live_status(pf, now=datetime(2026, 9, 21, 10, 0, tzinfo=IST)))
    assert [p["state"] for p in out["positions"]] == ["target", "stop", "unavailable", "no_entry"]
    assert out["counts"] == {"holding": 0, "target": 1, "stop": 1, "awaiting": 2} and "TARGET_STOP" in out["experiment"]
