"""Paper Trading v2 — GET /api/v1/analytics/account/{id} (services/spt/account_analytics.py; TESTCASES PV2-B-21..23).
MOCK — not real data: every position, proposal, opportunity and figure here is made up; the expected values are worked by
hand in the comments."""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

import pytest

from services.spt import account_analytics as aa
from services.spt import constants as C
from tests.paper_v2_fakes import A, NOW, U1, client, world  # noqa: F401 (fixtures)

#         id    net     R      setup       desk regime (trend)       opened        closed
TRADES = [("t1", 2000.0, 2.0, "breakout", ("bullish", "up"), "2026-10-01", "2026-10-05"),
          ("t2", -1000.0, -1.0, "breakout", ("bearish", "down"), "2026-10-06", "2026-10-08"),
          ("t3", 1500.0, 1.5, "momentum", ("high_volatility", "up"), "2026-10-09", "2026-10-12"),
          ("t4", -500.0, -0.5, "momentum", ("mixed", "flat"), "2026-10-13", "2026-10-14"),
          ("t5", 600.0, None, "breakout", None, "2026-10-15", "2026-10-20")]


def seed(db, trades=TRADES):
    for tid, net, r, setup, reg, opened, closed in trades:
        db[C.POSITIONS].docs.append({
            "_id": tid, "user_id": U1, "symbol": f"FIX{tid.upper()}", "state": C.POS_CLOSED, "realized_net_rs": net,
            "initial_risk_rs": 1000.0 if r is not None else None, "outcome": {"r_multiple": r} if r is not None else {},
            "proposal_id": f"p-{tid}", "opportunity_id": f"o-{tid}", "opened_at": f"{opened}T04:00:00+00:00",
            "closed_at": f"{closed}T09:00:00+00:00"})
        db[C.PROPOSALS].docs.append({"_id": f"p-{tid}", "user_id": U1, "opportunity": {"category": setup.title()}})
        db[C.OPPORTUNITIES].docs.append({"_id": f"o-{tid}", "category": setup.title(),
                                         "validation": {"market": {"key": reg[0], "trend": reg[1]}} if reg else {}})
    db[C.POSITIONS].docs.append({"_id": "open1", "user_id": U1, "symbol": "FIXO", "state": C.POS_MONITORING,
                                 "realized_net_rs": 0.0})


# ── PV2-B-21 the figures ─────────────────────────────────────────────────────
def test_pv2_b_21_figures_hand_checked(client):
    seed(client.world.db)
    r = client.get(f"/api/v1/analytics/account/{U1}?days=90", headers=A)
    assert r.status_code == 200, r.text
    b = r.json()
    assert set(b) >= {"days", "trades", "wins", "losses", "win_rate_pct", "avg_win_r", "avg_loss_r", "expectancy_r",
                      "profit_factor", "max_drawdown_pct", "sharpe", "sortino", "by_setup", "by_regime", "certification",
                      "basis", "notes"}
    assert (b["days"], b["trades"], b["wins"], b["losses"]) == (90, 5, 3, 2)
    assert b["win_rate_pct"] == 60.0
    assert b["avg_win_r"] == 1.75                        # (2.0 + 1.5) / 2; t5 has no R
    assert b["avg_loss_r"] == -0.75                      # (−1.0 − 0.5) / 2
    assert b["expectancy_r"] == 0.5                      # (2 − 1 + 1.5 − 0.5) / 4
    assert b["profit_factor"] == 2.733                   # (2000 + 1500 + 600) / (1000 + 500) = 2.7333
    # equity 10,00,000 → 10,02,000 (peak) → 10,01,000: 1,000 / 10,02,000 = 0.0998 % (the worst trough)
    assert b["max_drawdown_pct"] == round(1000 / 1_002_000 * 100, 4)
    assert any("no initial risk" in n for n in b["notes"])


# ── PV2-B-22 ratios ──────────────────────────────────────────────────────────
def test_pv2_b_22_ratios_from_the_daily_series(client):
    seed(client.world.db)
    b = client.get(f"/api/v1/analytics/account/{U1}", headers=A).json()
    # independent: every weekday from 1 Oct to 5 Nov 2026, that day's closed net ÷ equity at the start of the day
    by_day = {date(2026, 10, 5): 2000.0, date(2026, 10, 8): -1000.0, date(2026, 10, 12): 1500.0,
              date(2026, 10, 14): -500.0, date(2026, 10, 20): 600.0}
    eq, rets, d = 1_000_000.0, [], date(2026, 10, 1)
    while d <= date(2026, 11, 5):
        if d.weekday() < 5:
            pnl = by_day.get(d, 0.0)
            rets.append(pnl / eq)
            eq += pnl
        d += timedelta(days=1)
    assert b["daily_points"] == len(rets) == 26
    sharpe = statistics.mean(rets) / statistics.stdev(rets) * math.sqrt(252)
    sortino = statistics.mean(rets) / math.sqrt(sum(min(r, 0) ** 2 for r in rets) / len(rets)) * math.sqrt(252)
    assert b["sharpe"] == pytest.approx(round(sharpe, 3)) and b["sortino"] == pytest.approx(round(sortino, 3))
    assert b["ratio_reason"] is None


def test_pv2_b_22b_fewer_than_20_days_is_null_with_a_reason(client):
    seed(client.world.db, [("t9", 800.0, 0.8, "breakout", ("bullish", "up"), "2026-10-30", "2026-11-03")])
    b = client.get(f"/api/v1/analytics/account/{U1}", headers=A).json()
    assert b["sharpe"] is None and b["sortino"] is None
    assert b["ratio_reason"].startswith("5 daily points") and "at least 20" in b["ratio_reason"]
    assert b["profit_factor"] is None and "no losing trade" in b["profit_factor_reason"]


def test_pv2_b_22c_window_and_empty_account(client):
    seed(client.world.db)
    b = client.get(f"/api/v1/analytics/account/{U1}?days=20", headers=A).json()     # since 16 Oct: t5 only
    assert b["trades"] == 1 and b["wins"] == 1
    client.world.db[C.POSITIONS].docs.clear()
    b = client.get(f"/api/v1/analytics/account/{U1}", headers=A).json()
    assert b["trades"] == 0 and b["win_rate_pct"] is None and b["expectancy_r"] is None and b["max_drawdown_pct"] is None
    assert b["certification"] == [] and "No scanner paper trade closed" in b["notes"][0]


# ── PV2-B-23 groups and certification ────────────────────────────────────────
def test_pv2_b_23_by_setup_by_regime_and_certification(client):
    seed(client.world.db)
    b = client.get(f"/api/v1/analytics/account/{U1}", headers=A).json()
    assert [(s["setup"], s["trades"], s["expectancy_r"], s["profit_factor"], s["win_rate_pct"]) for s in b["by_setup"]] == [
        ("breakout", 3, 0.5, 2.6, 66.67),               # R (2, −1); PF 2,600 / 1,000
        ("momentum", 2, 0.5, 3.0, 50.0)]                # R (1.5, −0.5); PF 1,500 / 500
    assert [(g["regime"], g["trades"], g["expectancy_r"]) for g in b["by_regime"]] == [
        ("uptrend", 2, 1.75), ("sideways", 1, -0.5), ("downtrend", 1, -1.0), ("unknown", 1, None)]
    assert b["by_regime"][0]["desk_regimes"] == {"bullish": 1, "high_volatility": 1}
    cert = {c["setup"]: c for c in b["certification"]}
    crit = {k["key"]: (k["status"], k["value"]) for k in cert["breakout"]["criteria"]}
    assert crit == {"min_trades": ("fail", "3 / 50"), "positive_expectancy": ("warn", "+0.50R"),
                    "profit_factor": ("warn", "2.60"), "out_of_sample": ("not_measured", "no walk-forward split yet"),
                    "regimes": ("pass", "2: downtrend, uptrend")}
    assert cert["breakout"]["certified"] is False and cert["momentum"]["certified"] is False
    assert {k["key"]: k["status"] for k in cert["momentum"]["criteria"]}["regimes"] == "pass"   # uptrend + sideways


def test_pv2_b_23b_regime_mapping():
    assert aa.regime_of({"key": "bullish"}) == ("uptrend", "bullish")
    assert aa.regime_of({"key": "bearish", "trend": "up"}) == ("downtrend", "bearish")
    assert aa.regime_of({"key": "sideways"}) == ("sideways", "sideways")
    assert aa.regime_of({"key": "high_volatility", "trend": "down"}) == ("downtrend", "high_volatility")
    assert aa.regime_of({"key": "mixed", "trend": None}) == ("unknown", "mixed")
    assert aa.regime_of(None) == ("unknown", None)


def test_pv2_b_23c_a_certified_setup():
    trades = [{"position_id": f"x{i}", "net_rs": 300.0 if i % 3 else -200.0, "r": 1.5 if i % 3 else -1.0,
               "setup": "breakout", "regime": "uptrend" if i % 2 else "sideways", "desk_regime": None,
               "opened_day": None, "closed_day": None} for i in range(60)]
    c = aa.certification("breakout", trades)
    assert [k["status"] for k in c["criteria"]] == ["pass", "pass", "pass", "not_measured", "pass"]
    assert c["certified"] is False                      # out-of-sample is not measured, so never certified yet
