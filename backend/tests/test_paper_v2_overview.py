"""Paper Trading v2 — GET /api/v1/paper/overview (services/spt/overview.py; TESTCASES PV2-B-15..17).
MOCK — not real data: every user, symbol, signal, proposal, order and position here is made up."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.spt import constants as C
from services.spt import overview
from tests.paper_v2_fakes import A, NOW, U1, U2, client, world  # noqa: F401 (fixtures)

AT = NOW.isoformat()


def seed(db):
    """MOCK pipeline of 5 Nov 2026 (IST) plus a day-before row of each kind that must not count."""
    sig = db[C.SIGNAL_EVENTS].docs
    sig += [{"_id": f"sig:2026-11-05:w:{s}", "day": "2026-11-05"} for s in ("FIXA", "FIXB", "FIXC")]
    sig += [{"_id": "sig:2026-11-04:w:FIXD", "day": "2026-11-04"}]
    db[C.OPPORTUNITIES].docs.extend([
        {"_id": "opp-A", "day": "2026-11-05", "state": C.OPP_QUALIFIED, "validation": {"decision": C.OPP_QUALIFIED}},
        {"_id": "opp-B", "day": "2026-11-05", "state": C.OPP_WATCHLIST, "validation": {"decision": C.OPP_WATCHLIST}},
        {"_id": "opp-C", "day": "2026-11-05", "state": C.OPP_EXPIRED, "validation": {"decision": C.OPP_QUALIFIED}},
        {"_id": "opp-D", "day": "2026-11-04", "state": C.OPP_QUALIFIED, "validation": {"decision": C.OPP_QUALIFIED}}])
    db[C.PROPOSALS].docs.extend([
        {"_id": "p1", "user_id": U1, "day": "2026-11-05", "symbol": "FIXA", "risk": {"decision": C.RISK_APPROVE}},
        {"_id": "p2", "user_id": U1, "day": "2026-11-05", "symbol": "FIXB", "risk": {"decision": C.RISK_APPROVE_REDUCED}},
        {"_id": "p3", "user_id": U1, "day": "2026-11-05", "symbol": "FIXC",
         "risk": {"decision": C.RISK_BLOCKED, "at": "2026-11-05T05:32:00+00:00", "reason_codes": ["open_risk_exceeded"],
                  "explanations": ["MOCK: the open-risk room is used up."]}},
        {"_id": "p4", "user_id": U2, "day": "2026-11-05", "symbol": "FIXA", "risk": {"decision": C.RISK_APPROVE}}])
    db[C.ORDERS].docs.extend([
        {"_id": "o1", "user_id": U1, "purpose": "ENTRY", "state": C.ORD_FILLED, "fills": [{"at": "2026-11-05T04:00:00+00:00"}]},
        {"_id": "o2", "user_id": U1, "purpose": "ENTRY", "state": C.ORD_FILLED, "fills": [{"at": "2026-11-03T04:00:00+00:00"}]},
        {"_id": "o3", "user_id": U1, "purpose": "EXIT", "state": C.ORD_FILLED, "fills": [{"at": "2026-11-05T04:30:00+00:00"}]}])
    db[C.POSITIONS].docs.append(
        {"_id": "pos1", "user_id": U1, "symbol": "FIXA", "state": C.POS_MONITORING, "quantity": 10, "entry_qty": 10,
         "avg_entry_price": 500.0, "stop_loss": 490.0, "realized_net_rs": 0.0, "opened_at": "2026-11-05T04:00:00+00:00",
         "mark": {"price": 495.0, "unrealized_net_rs": 120.0, "at": AT}})


# ── PV2-B-15 shape and counts ────────────────────────────────────────────────
def test_pv2_b_15_shape_and_counts(client):
    seed(client.world.db)
    r = client.get("/api/v1/paper/overview", headers=A)
    assert r.status_code == 200, r.text
    b = r.json()
    assert set(b) >= {"account_id", "as_of", "status", "kpis", "pipeline", "warnings", "headline"}
    assert b["account_id"] == U1
    assert [(p["stage"], p["count"]) for p in b["pipeline"]] == [
        ("signals", 3), ("opportunities", 3), ("qualified", 2), ("risk_approved", 2), ("orders_filled", 1),
        ("open_positions", 1)]
    st = b["status"]
    assert set(st) >= {"feed_state", "last_tick_age_s", "session", "kill_switch", "policy_version", "mode"}
    assert (st["feed_state"], st["last_tick_age_s"], st["session"], st["policy_version"], st["mode"]) == ("live", 1.2, "open", 0, "off")
    assert set(st["kill_switch"]) >= {"state", "entries_blocked", "text"} and st["kill_switch"]["state"] == "DISABLED"
    k = b["kpis"]
    assert set(k) == {"equity_rs", "start_equity_rs", "day_pnl_rs", "day_loss_limit_pct", "day_loss_used_pct", "deployed_rs",
                      "deployed_pct", "cash_rs", "open_risk_pct", "open_risk_limit_pct", "drawdown_pct", "drawdown_warn_pct",
                      "positions_open", "positions_max", "orders_pending"}
    assert k["equity_rs"] == 1_000_120.0 and k["start_equity_rs"] == 1_000_000.0             # + the SPT mark's ₹120
    assert (k["day_loss_limit_pct"], k["open_risk_limit_pct"], k["drawdown_warn_pct"], k["positions_max"]) == (2.0, 3.0, 3.33, 10)
    h = b["headline"]
    assert (h["setups_cleared"], h["blocked"], h["reduced"], h["signals"], h["opportunities"]) == (2, 1, 1, 3, 3)
    assert h["worst_concentration"] is None


# ── PV2-B-16 warnings ────────────────────────────────────────────────────────
def test_pv2_b_16_warnings_from_the_day(client):
    seed(client.world.db)
    w = client.get("/api/v1/paper/overview", headers=A).json()["warnings"]
    assert [(x["level"], x["code"]) for x in w] == [("danger", "RISK_REJECTED"), ("amber", "STOP_APPROACHING"),
                                                     ("mint", "FEEDS_HEALTHY")]
    assert w[0]["symbol"] == "FIXC" and w[0]["at"] == "2026-11-05T05:32:00+00:00" and "open-risk room" in w[0]["title"]
    assert w[1]["symbol"] == "FIXA" and set(w[2]) >= {"level", "title", "code", "at"}


def state(**over):
    """MOCK account state in services/spt/allocation.account_state's shape."""
    s = {"user_id": U1, "error": None, "equity_rs": 1_000_000.0, "open_risk_rs": 25_000.0, "day_pnl_rs": -25_000.0,
         "day_start_equity_rs": 1_025_000.0, "drawdown_pct": 1.0, "positions_open": 3, "max_positions": 10,
         "pending_entries": [], "deployed_rs": 200_000.0, "cash_rs": 1_000_000.0,
         "profile": {"limits": {"daily_loss_pct": 2.0, "max_open_risk_pct": 3.0, "max_drawdown_pct": 10.0,
                                "max_sector_pct": 25.0}},
         "config": {"mode": "approval", "extras": {"drawdown_ladder": {"reduce_at_pct": 3.33}}},
         "sector_rs": {"IT": 230_000.0, "Bank": 50_000.0},
         "book": {"account": {"starting_capital_rs": 1_000_000.0},
                  "reservations": [{"sector": "IT", "risk_rs": 3000.0}, {"sector": "Bank", "risk_rs": 1000.0}],
                  "positions": []}}
    s.update(over)
    return s


def test_pv2_b_16b_limits_concentration_alerts_and_a_down_feed():
    ks = {"state": "ACTIVE", "entries_blocked": False, "text": "Armed"}
    alerts = [{"severity": "CRITICAL", "kind": "STOP_HIT", "text": "MOCK stop hit", "underlying": "FIXZ", "at": "t1"},
              {"severity": "INFO", "kind": "STOP_RAISED", "text": "MOCK raised", "underlying": "FIXZ", "at": "t2"}]
    b = overview.build(state=state(), ks=ks, feed={"mode": "not_connected", "age_s": None, "session": "open"},
                       policy_version=4, counts={}, proposals_today=[], alerts=alerts, positions=[], now=NOW)
    codes = [(x["level"], x["code"]) for x in b["warnings"]]
    assert ("amber", "NEAR_LIMIT_OPEN_RISK") in codes                     # 2.5 % of a 3 % limit = 83 %
    assert ("danger", "LIMIT_BREACH_DAILY_LOSS") in codes                 # 25,000 / 10,25,000 = 2.44 % ≥ 2 %
    assert ("danger", "STOP_HIT") in codes and not any(c == "STOP_RAISED" for _, c in codes)
    assert ("danger", "FEED_DOWN") in codes and not any(c == "FEEDS_HEALTHY" for _, c in codes)
    assert [x["level"] for x in b["warnings"]] == sorted((x["level"] for x in b["warnings"]),
                                                          key=["danger", "amber", "mint"].index)
    wc = b["headline"]["worst_concentration"]
    assert wc == {"name": "IT", "pct_of_open_risk": 75.0, "exposure_rs": 230000.0, "pct_of_sector_limit": 92.0}
    assert b["status"]["feed_state"] == "down" and b["status"]["policy_version"] == 4


# ── PV2-B-17 feed mapping ────────────────────────────────────────────────────
@pytest.mark.parametrize("mode, state_", [("live", "live"), ("delayed", "stale"), ("closed", "closed"), ("expired", "down"),
                                          ("not_connected", "down"), ("disabled", "down")])
def test_pv2_b_17_feed_mapping(mode, state_):
    assert overview.feed_state(mode) == state_


def test_pv2_b_17b_stale_feed_in_session_is_amber():
    b = overview.build(state=state(open_risk_rs=0.0, day_pnl_rs=0.0), ks={"state": "ACTIVE"},
                       feed={"mode": "delayed", "age_s": 14.0, "session": "open"}, policy_version=0, counts={},
                       proposals_today=[], alerts=[], positions=[], now=NOW)
    assert [(x["level"], x["code"]) for x in b["warnings"]] == [("amber", "FEED_STALE")]
    assert "14s" in b["warnings"][0]["title"]
