"""Smart trading desk — paper trades with the DaaS paper_trades field set (PRD §13.4, D1, B18).

Covers what services/desk_trading.py and routes/desk_trading.py add on top of the first version (whose own tests are
test_desk_trading.py and reuse the same harness): the entry rule and whether the entry was reached, the eligible price
observations, the exit rule (stop / target / time / entry not reached), estimated costs from the strategy_engine cost
model, gross and net P&L, MFE and MAE from the price path, and the flags for gaps, same-session ambiguity and missing
bars. Nothing here places an order: the desk has no order route, and these tests only ever read end-of-day bars.

MOCK — not real data: the FIX* symbols and their bars are made up (same harness as test_desk_trading.py: in-memory
Mongo, a fake data platform serving GET /v1/prices/eod/{symbol}, the clock fixed at 2026-10-12 10:30 IST).

Cost model (services/strategy_engine/backtest.py): 0.05% of the traded value plus ₹20, per side.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

import pytest

from services import desk_trading as svc
from tests.test_desk_trading import (  # noqa: F401  (`world` and `api` are fixtures)
    A, B, NOW, TRADES_URL, api, open_trade, trade_body, trades, world,
)


def obar(day: str, open_: Optional[float], high: Optional[float], low: Optional[float], close: Optional[float],
         series: str = "EQ") -> Dict[str, Any]:
    """One /v1/prices/eod row with an open price (the first version's harness sends none)."""
    return {"as_of_date": day, "symbol": None, "series": series, "isin": None, "prev_close": None,
            "open_price": open_, "high_price": high, "low_price": low, "close_price": close,
            # MOCK volume 10 lakh shares (was 1,000): the risk service caps a position at 5% of the traded value.
            "volume": 1_000_000, "turnover": None, "trades": None, "deliv_qty": None, "deliv_pct": None}


def side(price: float, qty: int) -> float:
    """One side's estimated cost under the FLAT model (desk-flat-v1, what older trades keep): 0.05% of the traded
    value plus ₹20."""
    return price * qty * 0.0005 + 20.0


def _paisa(x: float) -> float:
    return float(Decimal(repr(float(x))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def card_side(price: float, qty: int, buy: bool) -> float:
    """One equity-delivery order side under the desk cost card (desk-cost-v2), worked by hand from its rates, each
    component rounded to the paisa: ₹20 brokerage + STT 0.1% + NSE exchange 0.00307% + SEBI ₹10/crore + stamp 0.015%
    (buy only) + GST 18% of (brokerage + exchange + SEBI) + slippage 0.05%. E.g. 100 x 10 bought: 20 + 1.00 + 0.03 +
    0.00 + 0.15 + 3.61 + 0.50 = 25.29; 110 x 10 sold: 20 + 1.10 + 0.03 + 0 + 0 + 3.61 + 0.55 = 25.29."""
    v = price * qty
    brokerage, exchange, sebi = 20.0, _paisa(v * 0.0000307), _paisa(v * 10 / 1e7)
    parts = [brokerage, _paisa(v * 0.001), exchange, sebi, _paisa(v * 0.00015) if buy else 0.0,
             _paisa((brokerage + exchange + sebi) * 0.18), _paisa(v * 0.0005)]
    return _paisa(sum(parts))


def buy(price: float, qty: int) -> float:
    return card_side(price, qty, True)


def sell(price: float, qty: int) -> float:
    return card_side(price, qty, False)


def only(body: Dict[str, Any]) -> Dict[str, Any]:
    [row] = body["trades"]
    return row


def flag_codes(row: Dict[str, Any]) -> list:
    return [f["code"] for f in row["flags"]]


# ── create: the field set ────────────────────────────────────────────────────
def test_create_stores_the_field_set_and_echoes_the_cost_estimates(api, world):
    r = api.post(TRADES_URL, headers=A, json=trade_body(
        quantity=20, entry_rule="break_above", entry_window_sessions=3, max_hold_sessions=10,
        signal_at="2026-10-12T03:30:00Z", strategy_version="positional-scanner v2", rationale="  Broke a 20-day high on volume  ",
        source={"kind": "scanner", "bucket": "breakout_confirmed", "signal_date": "2026-10-09"}))
    assert r.status_code == 201, r.text
    t = r.json()["trade"]
    assert (t["entry_rule"], t["entry_window_sessions"], t["max_hold_sessions"]) == ("break_above", 3, 10)
    assert t["signal_at"] == "2026-10-12T03:30:00+00:00"
    assert t["strategy_version"] == "positional-scanner v2" and t["rationale"] == "Broke a 20-day high on volume"
    assert t["rules_version"] == svc.RULES_VERSION
    # A new trade snapshots the desk cost card (paper_fills_pnl follow-up, statutory charges).
    assert t["cost_model"] == svc.COST_MODEL and t["cost_model"]["version"] == "desk-cost-v2"
    assert (t["cost_model"]["slippage_pct_per_side"], t["cost_model"]["brokerage_rs_per_side"]) == (0.05, 20.0)
    # Not reached yet: nothing has been read, so the entry is waiting and no P&L or MFE exists.
    assert (t["entry_status"], t["sim_entry_price"], t["entry_session"]) == ("waiting", None, None)
    assert t["gross_pnl_rs"] is None and t["net_pnl_rs"] is None and t["mfe_pct"] is None and t["mae_pct"] is None
    # Estimates at the levels: entry 100 × 20 → ₹21.00; target 110 × 20 → ₹21.10; stop 95 × 20 → ₹20.95.
    # Under the card (statutory charges added): buy 100 x 20 = 26.97; sell 110 x 20 = 26.98; sell 95 x 20 = 26.52.
    assert t["est_costs_rs"] == {"at_target": round(buy(100, 20) + sell(110, 20), 2), "at_stop": round(buy(100, 20) + sell(95, 20), 2)}
    assert t["est_costs_rs"] == {"at_target": 53.95, "at_stop": 53.49}
    [stored] = world.db.trades.docs
    assert stored["entry_rule"] == "break_above" and stored["cost_model"]["slippage_pct_per_side"] == 0.05
    assert stored["rules_version"] == svc.RULES_VERSION


def test_create_defaults_are_the_first_versions_behaviour(api):
    t = open_trade(api)
    assert (t["entry_rule"], t["entry_window_sessions"], t["max_hold_sessions"]) == ("at_once", None, None)
    assert t["entry_status"] == "assumed" and t["sim_entry_price"] == 100.0
    assert t["signal_at"] is None and t["strategy_version"] is None and t["rationale"] is None
    # No target: the estimate at the target is null, never 0. (Another user: a second open FIXA trade for the same
    # user is refused as a duplicate.)
    # A trade with no target can only be on record from before Phase 1 (the risk policy now needs one): built directly.
    t2 = svc.public_trade(svc.new_trade("user_b", trade_body(target_price=None), NOW))
    assert t2["est_costs_rs"]["at_target"] is None and t2["est_costs_rs"]["at_stop"] == round(buy(100, 10) + sell(95, 10), 2) == 50.36


@pytest.mark.parametrize("over, code", [
    ({"entry_rule": "market"}, "invalid_entry_rule"),
    ({"entry_rule": 1}, "invalid_entry_rule"),
    ({"entry_rule": "break_above", "entry_window_sessions": 0}, "invalid_entry_window"),
    ({"entry_rule": "break_above", "entry_window_sessions": 21}, "invalid_entry_window"),
    ({"entry_rule": "break_above", "entry_window_sessions": 2.5}, "invalid_entry_window"),
    ({"entry_window_sessions": 3}, "invalid_entry_window"),              # only a conditional entry waits
    ({"max_hold_sessions": 0}, "invalid_max_hold"),
    ({"max_hold_sessions": 251}, "invalid_max_hold"),
    ({"max_hold_sessions": "5"}, "invalid_max_hold"),
    ({"signal_at": "yesterday"}, "invalid_signal_at"),
    ({"signal_at": "2026-10-13T09:00:00Z"}, "invalid_signal_at"),          # after now (2026-10-12 05:00 UTC)
    ({"signal_at": 1760000000}, "invalid_signal_at"),
    ({"strategy_version": ""}, "invalid_strategy_version"),
    ({"strategy_version": "x" * 61}, "invalid_strategy_version"),
    ({"strategy_version": "v2\n<script>"}, "invalid_strategy_version"),
    ({"rationale": "x" * 501}, "invalid_rationale"),
    ({"rationale": 5}, "invalid_rationale"),
])
def test_create_refuses_bad_new_fields_with_a_code(api, world, over, code):
    r = api.post(TRADES_URL, json=trade_body(**over), headers=A)
    assert (r.status_code, r.json()["detail"]) == (422, code)
    assert world.db.trades.docs == []


def test_signal_at_takes_a_date_too(api):
    assert open_trade(api, signal_at="2026-10-09")["signal_at"] == "2026-10-09"


# ── at once: costs, net, MFE / MAE from the path ─────────────────────────────
def test_target_exit_records_costs_net_mfe_mae_and_observations(api, world):
    open_trade(api)                                                     # 10 × 100, stop 95, target 110
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 103), obar("2026-10-14", 103, 111, 99, 109))
    t = only(trades(api))
    assert (t["status"], t["exit_reason"], t["exit_price"], t["exit_session"]) == ("closed", "target", 110.0, "2026-10-14")
    # gross (110 − 100) × 10 = 100; costs (desk cost card) buy 100 x 10 = 25.29 and sell 110 x 10 = 25.29 → 50.58;
    # net 49.42 (41.05 and 58.95 under the flat model, before the statutory charges were counted)
    assert t["gross_pnl_rs"] == 100.0 == t["realized_pnl_rs"]
    assert t["costs_rs"] == round(buy(100, 10) + sell(110, 10), 2) == 50.58
    assert t["net_pnl_rs"] == round(100.0 - 50.58, 2) == 49.42
    assert t["costs_breakdown"] == {"brokerage": 40.0, "stt": 2.1, "exchange": 0.06, "sebi": 0.0, "stamp": 0.15, "gst": 7.22,
                                    "slippage": 1.05, "total": 50.58}
    # Sessions after the IST open date: highs 104, 111 → MFE (111 − 100) / 100 = +11.00%, ₹110; lows 98, 99 → MAE −2.00%, −₹20
    assert (t["mfe_pct"], t["mfe_rs"], t["mae_pct"], t["mae_rs"]) == (11.0, 110.0, -2.0, -20.0)
    assert (t["observations"], t["held_sessions"], t["entry_status"]) == (2, 2, "assumed")
    assert t["flags"] == []
    stored = world.db.trades.docs[0]
    assert (stored["costs_rs"], stored["net_pnl_rs"], stored["mfe_pct"], stored["mae_pct"], stored["observations"]) == (50.58, 49.42, 11.0, -2.0, 2)


def test_an_open_trade_is_marked_gross_and_net_with_the_path_so_far(api, world):
    open_trade(api)
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 102))
    t = only(trades(api))
    assert t["status"] == "open" and t["last_close"] == 102.0
    # gross (102 − 100) × 10 = 20; costs (desk cost card) buy 100 x 10 = 25.29 + sell 102 x 10 = 25.17 → 50.46; net −30.46
    assert t["unrealized_pnl_rs"] == 20.0 == t["gross_pnl_rs"]
    assert t["costs_rs"] == round(buy(100, 10) + sell(102, 10), 2) == 50.46 and t["net_pnl_rs"] == -30.46
    assert (t["mfe_pct"], t["mae_pct"], t["observations"]) == (4.0, -2.0, 1)
    # The basis now says what the figure includes (gate 4: risk and cost figures say whether costs are in them).
    assert t["costs_basis"] == "entry at the fill, exit side estimated at the last close; " + svc.COSTS_CARD_TEXT


def test_same_session_stop_and_target_stays_a_stop_with_costs_at_the_stop(api, world):
    open_trade(api, quantity=20)
    world.add("FIXA", obar("2026-10-13", 100, 112, 94, 100))
    t = only(trades(api))
    assert (t["exit_reason"], t["exit_price"]) == ("stop", 95.0)
    assert t["exit_note"] == svc.BOTH_IN_RANGE_NOTE
    assert "both_in_range" in flag_codes(t)
    # gross (95 − 100) × 20 = −100; costs (desk cost card) buy 26.97 + sell 26.52 = 53.49; net −153.49
    assert (t["gross_pnl_rs"], t["costs_rs"], t["net_pnl_rs"]) == (-100.0, 53.49, -153.49)
    body = trades(api)
    assert body["summary"]["losses"] == 1 and body["summary"]["realized_pnl_rs"] == -100.0
    assert body["summary"]["net_realized_pnl_rs"] == -153.49 and body["summary"]["costs_realized_rs"] == 53.49


def test_a_gap_through_the_stop_fills_at_the_open_and_is_flagged(api, world):
    """The session opened at 93, under the 95 stop: the price never traded at 95, so the fill is the open (cace6500;
    pinned in test_honesty_safety_pass.py). gross (93 − 100) × 10 = −70; costs (desk cost card) 25.29 + 25.04 = 50.33."""
    open_trade(api)
    world.add("FIXA", obar("2026-10-13", 93, 96, 92, 94))
    t = only(trades(api))
    assert (t["exit_reason"], t["exit_price"]) == ("stop", 93.0)
    assert t["gross_pnl_rs"] == -70.0 and t["costs_rs"] == round(buy(100, 10) + sell(93, 10), 2) == 50.33
    [gap] = [f for f in t["flags"] if f["code"] == "gap_through_stop"]
    assert gap["session"] == "2026-10-13" and gap["price"] == 93.0
    assert "93" in gap["text"]


def test_time_exit_closes_at_the_close_of_the_last_session_held(api, world):
    open_trade(api, max_hold_sessions=2)
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 103), obar("2026-10-14", 103, 105, 99, 104),
              obar("2026-10-15", 104, 111, 103, 110))
    t = only(trades(api))
    assert (t["exit_reason"], t["exit_price"], t["exit_session"]) == ("time", 104.0, "2026-10-14")
    assert t["gross_pnl_rs"] == 40.0 and t["held_sessions"] == 2
    # The session after the exit is not part of the path: MFE stops at the 105 high.
    assert t["mfe_pct"] == 5.0


# ── conditional entries ──────────────────────────────────────────────────────
def test_entry_not_reached_in_its_window_closes_without_pnl(api, world):
    open_trade(api, entry_price=106.0, stop_price=100.0, target_price=115.0, entry_rule="break_above", entry_window_sessions=2)
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 103), obar("2026-10-14", 103, 105, 99, 104))
    body = trades(api)
    t = only(body)
    assert (t["status"], t["exit_reason"], t["exit_price"], t["exit_session"]) == ("closed", "entry_not_reached", None, "2026-10-14")
    assert (t["entry_status"], t["sim_entry_price"], t["observations"], t["held_sessions"]) == ("not_reached", None, 2, 0)
    assert t["realized_pnl_rs"] is None and t["gross_pnl_rs"] is None and t["net_pnl_rs"] is None and t["costs_rs"] is None
    assert t["mfe_pct"] is None and t["mae_pct"] is None
    s = body["summary"]
    assert (s["wins"], s["losses"], s["realized_pnl_rs"], s["not_entered"]) == (0, 0, None, 1)


def test_a_waiting_entry_has_no_mark_and_counts_as_open(api, world):
    open_trade(api, entry_price=106.0, stop_price=100.0, target_price=115.0, entry_rule="break_above", entry_window_sessions=5)
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 103))
    body = trades(api)
    t = only(body)
    assert (t["status"], t["entry_status"], t["observations"]) == ("open", "waiting", 1)
    assert t["last_close"] == 103.0                                    # the close is still shown
    assert t["unrealized_pnl_rs"] is None and t["gross_pnl_rs"] is None and t["costs_rs"] is None
    assert body["summary"]["entry_pending"] == 1 and body["summary"]["unmarked_open"] == 0
    assert body["summary"]["unrealized_pnl_rs"] is None                # nothing is held yet


def test_break_above_fills_at_the_level_and_the_path_starts_on_the_entry_session(api, world):
    open_trade(api, entry_price=103.0, stop_price=98.0, target_price=110.0, entry_rule="break_above")
    world.add("FIXA", obar("2026-10-13", 101, 104, 100, 103.5), obar("2026-10-14", 104, 111, 102, 109))
    t = only(trades(api))
    assert (t["entry_status"], t["entry_session"], t["sim_entry_price"]) == ("reached", "2026-10-13", 103.0)
    assert (t["exit_reason"], t["exit_price"], t["exit_session"]) == ("target", 110.0, "2026-10-14")
    assert t["gross_pnl_rs"] == 70.0
    # MFE (111 / 103 − 1) = +7.77%; MAE (100 / 103 − 1) = −2.91% (the entry session's low counts)
    assert t["mfe_pct"] == round((111 / 103 - 1) * 100, 2) == 7.77
    assert t["mae_pct"] == round((100 / 103 - 1) * 100, 2) == -2.91
    assert (t["observations"], t["held_sessions"]) == (2, 2)
    assert "entry_gap" not in flag_codes(t)


def test_a_gap_open_beyond_the_entry_fills_at_the_open_and_is_flagged(api, world):
    """The session opened at 105, above the 103 trigger: the price never traded at 103, so the fill is the open."""
    open_trade(api, entry_price=103.0, stop_price=98.0, target_price=120.0, entry_rule="break_above")
    world.add("FIXA", obar("2026-10-13", 105, 107, 104, 106))
    t = only(trades(api))
    assert t["entry_status"] == "reached" and t["sim_entry_price"] == 105.0
    [gap] = [f for f in t["flags"] if f["code"] == "entry_gap"]
    assert gap["price"] == 105.0 and gap["session"] == "2026-10-13"


def test_break_above_entry_session_touching_the_stop_counts_as_the_stop_and_says_so(api, world):
    open_trade(api, entry_price=103.0, stop_price=98.0, target_price=110.0, entry_rule="break_above")
    world.add("FIXA", obar("2026-10-13", 100, 104, 97, 101))
    t = only(trades(api))
    assert (t["exit_reason"], t["exit_price"], t["exit_session"]) == ("stop", 98.0, "2026-10-13")
    assert "entry_session_ambiguous" in flag_codes(t)


def test_pullback_entry_session_does_not_count_the_target(api, world):
    # 100 shares (MOCK): at 10 the costs exceed the Rs 4 move to the target, which the risk policy refuses.
    open_trade(api, quantity=100, entry_price=99.0, stop_price=95.0, target_price=103.0, entry_rule="pullback_to")
    world.add("FIXA", obar("2026-10-13", 102, 104, 98.5, 100), obar("2026-10-14", 100, 103.5, 99.5, 103))
    t = only(trades(api))
    # 13 Oct: the low 98.5 fills at 99; its high 104 may have come first, so the target counts from 14 Oct.
    assert (t["entry_session"], t["exit_reason"], t["exit_session"]) == ("2026-10-13", "target", "2026-10-14")
    [amb] = [f for f in t["flags"] if f["code"] == "entry_session_ambiguous"]
    assert amb["session"] == "2026-10-13"


def test_a_missing_bar_stops_the_scan_and_is_flagged(api, world):
    open_trade(api)
    world.add("FIXA", obar("2026-10-13", 101, None, None, 100), obar("2026-10-14", 100, 111, 90, 100))
    t = only(trades(api))
    assert t["status"] == "open" and t["observations"] == 0
    [miss] = [f for f in t["flags"] if f["code"] == "bar_missing_high_low"]
    assert miss["session"] == "2026-10-13"


def test_an_at_once_entry_outside_the_days_range_is_flagged(api, world):
    # The route now refuses such an entry when it is recorded (paper_fills_pnl TESTCASES FM-2) ...
    r = api.post(TRADES_URL, json=trade_body(entry_price=120.0, stop_price=110.0, target_price=130.0), headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "entry_not_tradable"
    # ... and a trade stored before that check is still flagged on its open date's range (12 Oct traded 94–104).
    world.db.trades.docs.append(svc.new_trade("user_a", trade_body(entry_price=120.0, stop_price=110.0, target_price=130.0), world.now))
    t = only(trades(api))
    assert "entry_outside_day_range" in flag_codes(t)


# ── manual close ─────────────────────────────────────────────────────────────
def test_closing_a_waiting_trade_cancels_it_without_pnl(api, world):
    t = open_trade(api, entry_price=106.0, stop_price=100.0, target_price=115.0, entry_rule="break_above")
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 103))
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    assert r.status_code == 200, r.text
    c = r.json()["trade"]
    assert (c["status"], c["exit_reason"], c["exit_price"], c["realized_pnl_rs"], c["net_pnl_rs"]) == ("closed", "cancelled", None, None, None)
    assert c["entry_status"] == "not_reached"


def test_a_waiting_trade_cannot_be_closed_blind_when_prices_fail(api, world):
    t = open_trade(api, entry_price=106.0, stop_price=100.0, target_price=130.0, entry_rule="break_above")
    world.fail["FIXA"] = svc.daas_client.DaasError("down")
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={"exit_price": 107}, headers=A)
    assert (r.status_code, r.json()["detail"]) == (503, "prices_unavailable")
    assert world.db.trades.docs[0]["status"] == "open"


def test_a_manual_close_records_costs_net_and_the_path(api, world):
    t = open_trade(api)
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 102))
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=A)
    c = r.json()["trade"]
    assert (c["exit_reason"], c["exit_price"]) == ("manual", 102.0)
    assert (c["gross_pnl_rs"], c["costs_rs"], c["net_pnl_rs"]) == (20.0, 50.46, -30.46)          # the desk cost card
    assert (c["mfe_pct"], c["mae_pct"], c["observations"]) == (4.0, -2.0, 1)


def test_another_users_waiting_trade_is_404(api, world):
    t = open_trade(api, A, entry_price=106.0, stop_price=100.0, target_price=130.0, entry_rule="break_above")
    r = api.post(f"{TRADES_URL}/{t['id']}/close", json={}, headers=B)
    assert (r.status_code, r.json()["detail"]) == (404, "trade_not_found")
    assert trades(api, B)["trades"] == []


# ── reading what the first version stored ────────────────────────────────────
def test_a_trade_stored_before_the_field_set_still_lists_with_costs_from_its_prices(api, world):
    doc = svc.new_trade("user_a", trade_body(), NOW)
    for k in ("entry_rule", "entry_window_sessions", "max_hold_sessions", "signal_at", "strategy_version", "rationale",
              "rules_version", "cost_model"):
        doc.pop(k, None)
    doc.update(status="closed", closed_at="2026-10-14T10:00:00+00:00", exit_price=110.0, exit_reason="target",
               exit_session="2026-10-14", realized_pnl_rs=100.0)
    world.db.trades.docs.append(doc)
    t = only(trades(api))
    assert t["entry_rule"] == "at_once" and t["entry_status"] == "assumed" and t["rules_version"] is None
    # No cost model on record: it predates the field set, so it keeps the flat model of its time (desk-flat-v1), never
    # the newer card (paper_fills_pnl follow-up: old trades unchanged).
    assert (t["gross_pnl_rs"], t["costs_rs"], t["net_pnl_rs"]) == (100.0, 41.05, 58.95)
    assert t["costs_breakdown"] == {"brokerage": 40.0, "stt": 0.0, "exchange": 0.0, "sebi": 0.0, "stamp": 0.0, "gst": 0.0,
                                    "slippage": 1.05, "total": 41.05}
    assert t["mfe_pct"] is None and t["observations"] is None           # not recorded then: null, never 0


def test_the_evening_script_counts_every_exit_reason(world):
    from scripts import check_desk_alerts as script
    for i, over in enumerate(({"max_hold_sessions": 1}, {"entry_price": 120.0, "stop_price": 110.0, "target_price": 130.0,
                                                          "entry_rule": "break_above", "entry_window_sessions": 1})):
        world.db.trades.docs.append({**svc.new_trade("user_a", trade_body(**over), NOW), "_id": f"t{i}"})
    world.add("FIXA", obar("2026-10-13", 101, 104, 98, 103))
    out = asyncio.run(script.run(world.db))
    assert out["ok"] is True
    assert {d["exit_reason"] for d in world.db.trades.docs} == {"time", "entry_not_reached"}


def test_list_names_the_rules_and_the_cost_model(api):
    body = trades(api)
    assert body["rules_version"] == svc.RULES_VERSION
    assert body["cost_model"]["slippage_pct_per_side"] == 0.05 and body["cost_model"]["brokerage_rs_per_side"] == 20.0
    assert set(body["entry_rules"]) == {"at_once", "break_above", "pullback_to"}
    assert "never" in body["orders"].lower()
