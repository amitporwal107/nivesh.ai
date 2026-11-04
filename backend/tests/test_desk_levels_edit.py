"""Modify risk — PATCH /api/desk/paper-trades/{id}/levels (docs/paper_pnl_dashboard/DESIGN.md "v2"; test cases V2-12…V2-17 in
test_reports/paper_pnl_dashboard_v2_TESTCASES.md).

What is covered:
  * the simulator (services/desk_trading.simulate + services/exit_rules.manual_stop): a change made on day D applies to
    the bars AFTER D only (no hindsight), for the stop and for the target; a waiting entry keeps the stop it was given
    before the fill; the opt-in ATR trail raises from the new stop and never lowers it; the exit reason at a manual stop
    is "stop", at a stop the trail raised "trailing_stop"
  * the route: 200 with the change appended and pending until the next session, every refusal code, the exact body the
    P&L screen sends, Idempotency-Key replay / conflict, the audit row, nothing else on the trade changed, the exit check
    first, and the list route + the evening job's function (apply_trade_exits) using the new levels

No network and no real database: the harness of tests/test_desk_trading.py (in-memory Mongo, the data platform served from
the test's bars, a fixed clock).

MOCK — not real data: the FIXL / FIXW symbols and every bar below are made up.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import pytest

from services import desk_trading as svc
from services import exit_rules as er
from tests.test_desk_trading import A, B, TRADES_URL, api, bar, world  # noqa: F401  (pytest fixtures)

# MOCK bars: FIXL trades around ₹100.
FIXL = [bar("2026-10-08", 102, 98, 100), bar("2026-10-09", 102, 98, 100)]
FRI = datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc)            # Friday 10:30 IST: the trade is opened
MON = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)           # Monday 10:30 IST: the levels are changed (no 12 Oct bar yet)
MON_EVENING = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # Monday 20:30 IST: the evening check
TUE_EVENING = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)

# The body the P&L dashboard's "Modify risk" form sends (frontend: pnl-data.ts) — posted exactly so.
SCREEN_BODY = {"stop_price": 97.0, "target_price": 112.0, "note": "Tighter after the results"}


def levels_url(trade_id: str) -> str:
    return f"{TRADES_URL}/{trade_id}/levels"


def open_fixl(api, world, **over) -> Dict[str, Any]:
    world.add("FIXL", *copy.deepcopy(FIXL))
    world.now = FRI
    body = {"symbol": "FIXL", "quantity": 10, "entry_price": 100.0, "stop_price": 90.0, "target_price": 120.0}
    body.update(over)
    r = api.post(TRADES_URL, json=body, headers=A)
    assert r.status_code == 201, r.text
    world.now = MON
    return r.json()["trade"]


def stored(world, trade_id: str) -> Dict[str, Any]:
    return next(d for d in world.db.trades.docs if d["_id"] == trade_id)


# ── the simulator ────────────────────────────────────────────────────────────
def b(day: str, o: float, h: float, low: float, c: float) -> Dict[str, Any]:
    return {"date": date.fromisoformat(day), "open": o, "high": h, "low": low, "close": c, "volume": 1e6, "series": "EQ"}


def trade(**over) -> Dict[str, Any]:
    t = {"_id": "t1", "user_id": "u", "symbol": "X", "quantity": 10, "entry_price": 100.0, "stop_price": 90.0,
         "target_price": 130.0, "entry_rule": "at_once", "opened_at": "2026-10-05T05:00:00+00:00", "status": "open"}
    t.update(over)
    return t


def change(version: int, session: str, *, stop=None, target=None, changed=("stop",)) -> Dict[str, Any]:
    return {"version": version, "session": session, "at": f"{session}T08:00:00+00:00", "stop_price": stop,
            "target_price": target, "changed": list(changed)}


def test_v2_13_a_stop_change_applies_from_the_next_session_never_to_the_day_it_was_made():
    bars = [b("2026-10-05", 100, 101, 99, 100), b("2026-10-06", 100, 102, 95, 100),
            b("2026-10-07", 100, 101, 96, 99),       # the day of the change: low 96 is below the NEW stop 97
            b("2026-10-08", 99, 100, 96.5, 98)]      # the next session: low 96.5 reaches it
    t = trade(level_changes=[change(1, "2026-10-07", stop=97.0, target=130.0)])
    sim = svc.simulate(t, bars)
    assert sim["exit"]["exit_reason"] == "stop" and sim["exit"]["exit_price"] == 97.0
    assert sim["exit"]["exit_session"] == date(2026, 10, 8)
    assert sim["stop_history"][-1] == {"session": "2026-10-07", "stop": 97.0, "reason": "manual", "version": 2}
    assert sim["levels_applied"] == 1
    # The same bars without the change: no exit (the old stop 90 was never reached).
    assert svc.simulate(trade(), bars)["exit"] is None
    # A change dated the last bar's day has met no bar yet: nothing applied, the stop in force is still the old one.
    sim = svc.simulate(trade(level_changes=[change(1, "2026-10-08", stop=97.0, target=130.0)]), bars)
    assert sim["exit"] is None and sim["current_stop"] == 90.0 and sim["levels_applied"] == 0


def test_v2_14_a_target_change_likewise_and_removing_the_target():
    bars = [b("2026-10-05", 100, 101, 99, 100), b("2026-10-06", 100, 104, 99, 103),   # D: high 104 above the new target
            b("2026-10-07", 103, 103.5, 101, 103)]                                     # D+1 reaches it
    sim = svc.simulate(trade(level_changes=[change(1, "2026-10-06", stop=90.0, target=103.0, changed=("target",))]), bars)
    assert sim["exit"]["exit_reason"] == "target" and sim["exit"]["exit_price"] == 103.0
    assert sim["exit"]["exit_session"] == date(2026, 10, 7)
    # The target removed on D: a later high far above the old target closes nothing.
    bars2 = bars + [b("2026-10-08", 103, 140, 101, 139)]
    sim = svc.simulate(trade(level_changes=[change(1, "2026-10-06", stop=90.0, target=None, changed=("target",))]), bars2)
    assert sim["exit"] is None and sim["current_target"] is None
    assert svc.simulate(trade(), bars2)["exit"]["exit_reason"] == "target"


def test_v2_14_the_opt_in_trail_raises_from_the_new_stop_and_never_lowers_it():
    rules = [{"code": "trailing_atr", "version": "trail-atr-v1", "params": {"k": 2.0, "atr_period": 2}}]
    bars = [b("2026-10-01", 100, 103, 97, 100), b("2026-10-02", 100, 103, 97, 100), b("2026-10-05", 100, 102, 98, 100),
            b("2026-10-06", 100, 101, 99, 100), b("2026-10-07", 100, 104, 99, 103), b("2026-10-08", 103, 110, 102, 109),
            b("2026-10-09", 109, 112, 106, 110), b("2026-10-12", 110, 111, 107, 108)]
    t = trade(opened_at="2026-10-02T05:00:00+00:00", exit_rules=rules,
              level_changes=[change(1, "2026-10-05", stop=97.0, target=130.0)])
    sim = svc.simulate(t, bars)
    hist = sim["stop_history"]
    manual = next(i for i, h in enumerate(hist) if h["reason"] == "manual")
    assert hist[manual]["stop"] == 97.0 and hist[manual]["session"] == "2026-10-05"
    after = [h["stop"] for h in hist[manual + 1:]]
    assert after and all(s > 97.0 for s in after) and after == sorted(after)   # raised from 97, never below it
    # Without the change the trail had reached only 95.5 by 7 Oct: the manual 97 held on 6 and 7 Oct.
    assert all(h["session"] >= "2026-10-08" for h in hist[manual + 1:])
    # A bar through the raised stop exits as trailing_stop; one through the manual stop itself as stop.
    raised = sim["current_stop"]
    sim2 = svc.simulate(t, bars + [b("2026-10-13", 108, 108, raised - 0.5, 107)])
    assert sim2["exit"]["exit_reason"] == "trailing_stop" and sim2["exit"]["exit_price"] == raised
    sim3 = svc.simulate(t, bars[:4] + [b("2026-10-07", 100, 100.5, 96.5, 98)])
    assert sim3["exit"]["exit_reason"] == "stop" and sim3["exit"]["exit_price"] == 97.0


def test_v2_13_a_waiting_entry_gets_the_stop_it_was_given_before_the_fill():
    bars = [b("2026-10-05", 100, 101, 99, 100), b("2026-10-06", 100, 104, 97, 100),
            b("2026-10-07", 104, 106, 99, 105),      # break_above 105 fills here; the new stop 98 is in force
            b("2026-10-08", 104, 105, 97.5, 98)]
    t = trade(entry_price=105.0, stop_price=95.0, target_price=120.0, entry_rule="break_above", entry_window_sessions=5,
              level_changes=[change(1, "2026-10-06", stop=98.0, target=120.0)])
    sim = svc.simulate(t, bars)
    assert sim["entry_status"] == "reached" and sim["entry_session"] == date(2026, 10, 7)
    assert [(h["stop"], h["reason"]) for h in sim["stop_history"]] == [(95.0, "initial"), (98.0, "manual")]
    assert sim["exit"]["exit_reason"] == "stop" and sim["exit"]["exit_price"] == 98.0
    # Still waiting at the last bar: the manual version is listed and in force.
    sim = svc.simulate(t, bars[:2] + [b("2026-10-07", 100, 103, 99, 101)])
    assert sim["entry_status"] == "waiting" and sim["current_stop"] == 98.0
    assert sim["stop_history"][-1]["reason"] == "manual"


def test_manual_stop_is_a_version_and_refuses_bad_input():
    st = er.start(100.0, 90.0, er.Rules(), session=date(2026, 10, 5))
    st = er.manual_stop(st, 95.5, session=date(2026, 10, 6))
    assert st.stop == 95.5 and st.stop_version == 2 and st.stop_history[-1]["reason"] == "manual"
    with pytest.raises(ValueError):
        er.manual_stop(st, 0, session=date(2026, 10, 6))


def test_levels_now_splits_in_force_from_pending():
    t = trade(level_changes=[change(1, "2026-10-07", stop=95.0, target=130.0),
                             change(2, "2026-10-09", stop=96.0, target=125.0, changed=("stop", "target"))])
    sim = {"current_stop": 90.0, "current_target": 130.0, "levels_applied": 0}
    # Read on 9 Oct (a Friday): the 7 Oct change governs today; the 9 Oct one waits for Monday.
    v = svc.levels_now(t, sim, date(2026, 10, 9))
    assert v["current_stop"] == 95.0 and v["current_target"] == 130.0
    assert v["pending_levels"] == {"stop_loss": 96.0, "target": 125.0, "from_session": "2026-10-12", "version": 2}
    # Read on 12 Oct: both in force.
    v = svc.levels_now(t, sim, date(2026, 10, 12))
    assert (v["current_stop"], v["current_target"], v["pending_levels"]) == (96.0, 125.0, None)


def test_the_stop_below_target_guard():
    t = trade()
    sim = {"entry_status": "assumed", "current_stop": 95.0, "current_target": 130.0, "levels_applied": 0}
    with pytest.raises(svc.DeskInputError) as e:          # price fell to 50 (the stop would have closed it): only a guard
        svc.level_change(t, {"target": 60.0}, sim=sim, last_bar={"date": date(2026, 10, 9), "close": 50.0},
                         now=datetime(2026, 10, 9, 5, 0, tzinfo=timezone.utc))
    assert e.value.code == "stop_not_below_target"


# ── the route ────────────────────────────────────────────────────────────────
def test_v2_12_a_valid_change_is_appended_and_waits_for_the_next_session(api, world):
    t = open_fixl(api, world)
    before = copy.deepcopy(stored(world, t["id"]))
    r = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=A)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["replayed"] is False
    tr = out["trade"]
    assert tr["level_changes"] == [{"version": 1, "at": "2026-10-12T05:00:00+00:00", "session": "2026-10-12",
                                    "stop_price": 97.0, "target_price": 112.0, "prev_stop": 90.0, "prev_target": 120.0,
                                    "changed": ["stop", "target"], "note": "Tighter after the results"}]
    # Today's session keeps the old levels; the new ones are pending from Tuesday.
    assert (tr["current_stop"], tr["current_target"]) == (90.0, 120.0)
    assert tr["pending_levels"] == {"stop_loss": 97.0, "target": 112.0, "from_session": "2026-10-13", "version": 1}
    assert tr["stop_price"] == 90.0 and tr["target_price"] == 120.0         # the levels it was opened with stay on record
    assert tr["level_rule"] == svc.LEVEL_RULE_TEXT
    # V2-17: nothing else on the trade changed; the change is kept with its (empty) idempotency fields.
    after = stored(world, t["id"])
    changed_keys = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed_keys == {"level_changes", "level_version", "updated_at"}
    assert after["level_changes"][0]["idempotency_key"] is None
    # V2-17: the audit row.
    rows = [d for d in world.db.cols["risk_decisions"].docs if d.get("action") == "desk_paper_levels"]
    assert len(rows) == 1 and rows[0]["outcome"] == "allowed" and rows[0]["user_id"] == "user_a"
    assert rows[0]["detail"]["trade_id"] == t["id"] and rows[0]["detail"]["version"] == 1
    assert rows[0]["detail"]["stop_price"] == 97.0 and rows[0]["path"] == "desk_paper_levels"


def test_v2_16_the_screen_body_with_a_null_target_removes_it(api, world):
    t = open_fixl(api, world)
    r = api.patch(levels_url(t["id"]), json={"stop_price": 95.0, "target_price": None, "note": ""}, headers=A)
    assert r.status_code == 200, r.text
    ch = r.json()["trade"]["level_changes"][0]
    assert ch["target_price"] is None and ch["changed"] == ["stop", "target"] and ch["note"] is None
    assert r.json()["trade"]["pending_levels"]["target"] is None
    # Only one level may be sent.
    r = api.patch(levels_url(t["id"]), json={"target_price": 118.0}, headers=A)
    assert r.status_code == 200, r.text
    tr = r.json()["trade"]
    assert tr["level_changes"][1]["changed"] == ["target"] and tr["level_changes"][1]["stop_price"] == 95.0
    assert tr["pending_levels"] == {"stop_loss": 95.0, "target": 118.0, "from_session": "2026-10-13", "version": 2}


@pytest.mark.parametrize("body,code", [
    ({"stop_price": 0, "target_price": 112.0}, "invalid_stop_price"),
    ({"stop_price": "97", "target_price": 112.0}, "invalid_stop_price"),
    ({"stop_price": None, "target_price": 112.0}, "invalid_stop_price"),
    ({"stop_price": 97.0, "target_price": -1}, "invalid_target_price"),
    ({"stop_price": 100.0, "target_price": 112.0}, "stop_not_below_price"),      # last close 100 (9 Oct)
    ({"stop_price": 97.0, "target_price": 100.0}, "target_not_above_price"),
    ({"stop_price": 90.0, "target_price": 120.0}, "no_change"),
    ({}, "no_change"),
    ({"note": "only a note"}, "no_change"),
    ({"stop_price": 97.0, "quantity": 5}, "unknown_field"),
])
def test_v2_15_refusals(api, world, body, code):
    t = open_fixl(api, world)
    r = api.patch(levels_url(t["id"]), json=body, headers=A)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert (detail if isinstance(detail, str) else detail["code"]) == code
    if isinstance(detail, dict):
        assert detail["message"]                               # the screen shows the sentence
    assert "level_changes" not in stored(world, t["id"])


def test_v2_15_a_body_that_is_not_an_object(api, world):
    t = open_fixl(api, world)
    for raw in ("[1]", "not json"):
        r = api.patch(levels_url(t["id"]), content=raw, headers={**A, "Content-Type": "application/json"})
        assert r.status_code == 422 and r.json()["detail"] == "invalid_body"


def test_v2_15_unknown_or_someone_elses_trade_is_404_and_no_session_is_401(api, world):
    t = open_fixl(api, world)
    assert api.patch(levels_url("nope"), json=SCREEN_BODY, headers=A).status_code == 404
    r = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=B)
    assert r.status_code == 404 and r.json()["detail"] == "trade_not_found"
    assert api.patch(levels_url(t["id"]), json=SCREEN_BODY).status_code == 401


def test_v2_15_a_closed_trade_and_a_structure_are_409(api, world):
    t = open_fixl(api, world)
    assert api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A).status_code == 200
    r = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=A)
    assert r.status_code == 409 and r.json()["detail"] == "trade_already_closed"
    world.db.trades.docs.append({"_id": "s1", "user_id": "user_a", "kind": "strategy", "status": "open", "underlying": "NIFTY",
                                 "opened_at": "2026-10-09T05:00:00+00:00", "legs": []})
    r = api.patch(levels_url("s1"), json=SCREEN_BODY, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "levels_not_editable"


def test_the_exit_rule_is_checked_first(api, world):
    t = open_fixl(api, world)
    world.add("FIXL", bar("2026-10-12", 101, 89, 90))               # the session already went through the stop 90
    r = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=A)
    assert r.status_code == 409 and r.json()["detail"] == "trade_already_closed"
    doc = stored(world, t["id"])
    assert doc["status"] == "closed" and doc["exit_reason"] == "stop" and "level_changes" not in doc


def test_prices_unavailable_is_503_and_changes_nothing(api, world):
    t = open_fixl(api, world)
    world.fail["FIXL"] = svc.daas_client.DaasError("DAAS /prices/eod/FIXL returned HTTP 502", status_code=502)
    r = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=A)
    assert r.status_code == 503 and r.json()["detail"] == "prices_unavailable"
    assert "level_changes" not in stored(world, t["id"])


def test_v2_16_idempotency_key_replay_and_conflict(api, world):
    t = open_fixl(api, world)
    h = {**A, "Idempotency-Key": "levels-click-0001"}
    first = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=h)
    again = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=h)
    assert first.status_code == 200 and again.status_code == 200
    assert again.json()["replayed"] is True and again.json()["trade"]["level_changes"] == first.json()["trade"]["level_changes"]
    assert len(stored(world, t["id"])["level_changes"]) == 1
    assert len([d for d in world.db.cols["risk_decisions"].docs if d.get("action") == "desk_paper_levels"]) == 1
    other = api.patch(levels_url(t["id"]), json={**SCREEN_BODY, "stop_price": 96.0}, headers=h)
    assert other.status_code == 409 and other.json()["detail"]["code"] == "idempotency_conflict"
    bad = api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers={**A, "Idempotency-Key": "x"})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_idempotency_key"


def test_a_waiting_trade_is_checked_against_its_entry(api, world):
    t = open_fixl(api, world, entry_price=105.0, stop_price=95.0, target_price=120.0, entry_rule="break_above")
    r = api.patch(levels_url(t["id"]), json={"stop_price": 106.0}, headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "stop_not_below_entry"
    r = api.patch(levels_url(t["id"]), json={"stop_price": 101.0}, headers=A)        # above the close 100: fine, not filled
    assert r.status_code == 200, r.text


def test_v2_13_the_list_route_and_the_evening_job_use_the_new_levels_from_the_next_session(api, world):
    t = open_fixl(api, world)
    assert api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=A).status_code == 200      # Monday: stop 90 → 97
    # Monday's bar goes below the NEW stop but not the old one: Monday is still judged on 90 (no hindsight).
    world.add("FIXL", bar("2026-10-12", 101, 96, 99))
    world.now = MON_EVENING
    listed = api.get(TRADES_URL, params={"status": "all"}, headers=A).json()["trades"]
    tr = next(x for x in listed if x["id"] == t["id"])
    assert tr["status"] == "open" and tr["current_stop"] == 90.0 and tr["pending_levels"]["stop_loss"] == 97.0
    # The evening job's function (scripts/check_desk_alerts.py → apply_trade_exits), Tuesday: the low reaches 97.
    world.add("FIXL", bar("2026-10-13", 100, 96.8, 98))
    world.now = TUE_EVENING
    doc = stored(world, t["id"])
    bars = svc.session_bars([dict(r, symbol="FIXL") for r in world.rows["FIXL"]])
    out, counts = asyncio.run(svc.apply_trade_exits(world.db, [copy.deepcopy(doc)], {"FIXL": bars}))
    assert counts["stop"] == 1
    doc = stored(world, t["id"])
    assert doc["status"] == "closed" and doc["exit_price"] == 97.0 and doc["exit_session"] == "2026-10-13"
    assert doc["stop_history"][-1] == {"session": "2026-10-12", "stop": 97.0, "reason": "manual", "version": 2}
    assert doc["current_target"] == 112.0 and doc["levels_applied"] == 1


def test_an_in_force_change_shows_as_current_on_the_list(api, world):
    t = open_fixl(api, world)
    assert api.patch(levels_url(t["id"]), json=SCREEN_BODY, headers=A).status_code == 200
    world.add("FIXL", bar("2026-10-12", 101, 98, 100))
    world.now = datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc)                        # Tuesday 10:30 IST, no Tuesday bar yet
    tr = next(x for x in api.get(TRADES_URL, headers=A).json()["trades"] if x["id"] == t["id"])
    assert (tr["current_stop"], tr["current_target"], tr["pending_levels"]) == (97.0, 112.0, None)
