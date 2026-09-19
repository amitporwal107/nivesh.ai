"""Risk & Allocation Engine core — tests written BEFORE the implementation (plan: Risk & Allocation Engine core, rev 1;
PRD docs/ai_research/tpd3/prd/Nivesh_Risk_Allocation_Engine_PRD_v1.0.md §19). Every expected number is worked by hand
in the test from the PRD or the Zerodha schedule retrieved 2026-09-19, never read back from the engine.

Interface pinned here:
  risk.config     load_config(id) -> RiskConfig; validate(cfg) -> [errors]; with_changes(cfg, **kw) -> DRAFT copy;
                  config_hash(cfg); transition(status, action) -> status (TransitionError when not allowed)
  risk.costs      load_cost_model(id); fill_costs(model, profile, exchange, side, value, dp_applies, on_date,
                  allow_retroactive) -> {component: Decimal, "total": Decimal, "retroactive": bool}; slippage_pct(model, value20)
  risk.sizing     SizingInput(...); size(cfg, inp) -> SizingResult(status, quantity, candidates, binding, reasons)
  risk.drawdown   DrawdownMonitor(cfg, peak_equity=None); start_day(d, equity); end_day(d, equity) -> [events];
                  entries_allowed(d); risk_multiplier(); kill(d, reason); resume(d, approved)
  risk.execution  Bar(open, high, low, close, volume, prev_close); fill_entry(kind, bar, qty, slippage_pct,
                  participation_pct, trigger=None) -> Fill(status, price, qty, reason); check_stop(bar, stop, slippage_pct)
  risk.portfolio  Position; Portfolio(cash); open_risk(); sector_value(sector, prices)
  risk.engine     run(signals, bars, cfg, cost_model, sectors, exits, eligibility=None) -> Result(trades, equity, events,
                  decisions, ledger_digest)
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

import pandas as pd
import pytest

from nidp.services.tpd_model.risk import config as RC
from nidp.services.tpd_model.risk import costs as CC
from nidp.services.tpd_model.risk import drawdown as DD
from nidp.services.tpd_model.risk import engine as EN
from nidp.services.tpd_model.risk import execution as EX
from nidp.services.tpd_model.risk import portfolio as PF
from nidp.services.tpd_model.risk import sizing as SZ

POS = RC.load_config("RISK-POS-1")
V1 = RC.load_config("RISK-V1")
ZR = CC.load_cost_model("zerodha-equity-v1")


def inp(**kw) -> SZ.SizingInput:
    base = dict(capital=D("500000"), entry=D("100"), stop=D("95"), cost_per_share=D("0"), cash=D("500000"),
                reserved=D("0"), deployed_value=D("0"), stock_exposure=D("0"), sector_exposure=D("0"),
                open_risk=D("0"), avg_traded_value=D("100000000"), holds_symbol=False, open_positions=0,
                risk_multiplier=D("1"))
    base.update(kw)
    return SZ.SizingInput(**base)


# ---------------- configuration (FR-001, §6.1 hard rules, BR-007) ----------------
def test_shipped_configs_are_valid_and_match_the_decisions():
    assert RC.validate(POS) == [] and RC.validate(V1) == []
    assert (POS.risk_per_trade_pct, POS.max_open_positions, POS.max_stock_allocation_pct) == (D("0.5"), 8, D("20"))
    assert (V1.risk_per_trade_pct, V1.max_open_positions, V1.max_stock_allocation_pct) == (D("0.5"), 10, D("5"))
    assert POS.leverage == 0 and POS.hard_max_risk_per_trade_pct == D("2.0")


@pytest.mark.parametrize("change, fragment", [
    ({"risk_per_trade_pct": D("2.5")}, "risk_per_trade_pct"),
    ({"max_daily_loss_pct": D("5"), "max_weekly_loss_pct": D("4")}, "daily"),
    ({"leverage": 1}, "leverage"),
    ({"max_open_positions": 0}, "max_open_positions"),
    ({"min_cash_reserve_pct": D("-1")}, "min_cash_reserve_pct"),
    ({"min_stop_distance_pct": D("9")}, "stop_distance"),
])
def test_configuration_beyond_a_hard_bound_is_rejected(change, fragment):
    errs = RC.validate(RC.with_changes(POS, **change))
    assert errs and any(fragment in e for e in errs)


def test_versions_are_immutable_hashed_drafts():
    c = RC.with_changes(POS, risk_per_trade_pct=D("0.75"))
    assert c.status == "DRAFT" and RC.config_hash(c) != RC.config_hash(POS)
    assert RC.config_hash(POS) == RC.config_hash(RC.load_config("RISK-POS-1"))
    with pytest.raises(Exception):
        POS.risk_per_trade_pct = D("1")          # frozen


def test_status_machine_needs_validation_and_approval_before_activation():
    s = RC.transition("DRAFT", "validate")
    s = RC.transition(s, "approve")
    assert RC.transition(s, "activate") == "ACTIVE" and RC.transition("ACTIVE", "retire") == "RETIRED"
    for status, action in (("DRAFT", "activate"), ("VALIDATED", "activate"), ("RETIRED", "activate"), ("ACTIVE", "approve")):
        with pytest.raises(RC.TransitionError):
            RC.transition(status, action)


# ---------------- sizing (§7, BR-002/003/004/005/009) ----------------
def test_prd_worked_example_stock_cap_binds():
    r = SZ.size(V1, inp(entry=D("500"), stop=D("480")))
    assert r.candidates["risk"] == 125 and r.candidates["stock_cap"] == 50
    assert r.quantity == 50 and r.binding == "stock_cap" and r.status == "REDUCED"


def test_owner_baseline_risk_binds_at_a_five_percent_stop():
    r = SZ.size(POS, inp())                         # 2,500 / 5 = 500 shares = 10% of capital
    assert r.quantity == 500 and r.binding == "risk" and r.status == "APPROVED"
    assert r.candidates["stock_cap"] == 1000 and r.candidates["deployment"] == 4000


def test_cost_per_share_and_reduced_risk_multiplier_enter_the_risk_quantity():
    assert SZ.size(POS, inp(cost_per_share=D("0.25"))).candidates["risk"] == 476      # floor(2500 / 5.25)
    assert SZ.size(POS, inp(risk_multiplier=D("0.5"))).candidates["risk"] == 250


@pytest.mark.parametrize("kw, reason", [
    ({"stop": D("100")}, "INVALID_STOP"),                       # BR-002 stop >= entry
    ({"stop": D("101")}, "INVALID_STOP"),
    ({"entry": None}, "MISSING_INPUT"),                         # BR-009
    ({"stop": D("NaN")}, "MISSING_INPUT"),
    ({"stop": D("90")}, "STOP_TOO_WIDE"),                       # 10% > max 8%
    ({"stop": D("99.5")}, "STOP_TOO_TIGHT"),                    # 0.5% < min 1%
    ({"holds_symbol": True}, "DUPLICATE_EXPOSURE"),             # BR-004
    ({"open_positions": 8}, "MAX_POSITIONS"),
    ({"cash": D("100000")}, "INSUFFICIENT_CASH"),               # BR-003: 100,000 - 20% reserve of 500,000 = 0
    ({"sector_exposure": D("100000")}, "SECTOR_CAP"),           # BR-005: sector already at 20%
    ({"avg_traded_value": D("1000000")}, "ILLIQUID"),           # below min average traded value
])
def test_rejections_carry_a_coded_reason(kw, reason):
    r = SZ.size(POS, inp(**kw))
    assert r.status == "REJECTED" and r.quantity == 0 and reason in r.reasons


def test_caps_reduce_before_they_reject():
    r = SZ.size(POS, inp(sector_exposure=D("95000")))          # room 5,000 -> 50 shares
    assert r.quantity == 50 and r.binding == "sector_cap" and r.status == "REDUCED"
    r = SZ.size(POS, inp(open_risk=D("24000")))                 # 25,000 cap - 24,000 = 1,000 / 5 = 200
    assert r.quantity == 200 and r.binding == "portfolio_risk"
    liquid = RC.with_changes(POS, min_avg_traded_value=D("0"))
    r = SZ.size(liquid, inp(avg_traded_value=D("400000")))      # 5% x 4 lakh = 20,000 / 100 = 200
    assert r.quantity == 200 and r.binding == "liquidity"
    r = SZ.size(POS, inp(deployed_value=D("380000")))           # 80% = 400,000 - 380,000 = 20,000 / 100
    assert r.quantity == 200 and r.binding == "deployment"


# ---------------- Zerodha cost engine (§12) ----------------
def test_delivery_buy_and_sell_charges_to_the_paisa():
    b = CC.fill_costs(ZR, "delivery", "NSE", "BUY", D("50000"), dp_applies=False, on_date=date(2026, 9, 21))
    assert (b["stt"], b["exchange_txn"], b["sebi"], b["stamp"], b["gst"], b["brokerage"], b["dp"]) == \
        (D("50.00"), D("1.54"), D("0.05"), D("7.50"), D("0.29"), D("0.00"), D("0.00"))
    assert b["total"] == D("59.38") and b["retroactive"] is False
    s = CC.fill_costs(ZR, "delivery", "NSE", "SELL", D("52000"), dp_applies=True, on_date=date(2026, 9, 21))
    assert (s["stt"], s["exchange_txn"], s["sebi"], s["stamp"], s["gst"], s["dp"]) == \
        (D("52.00"), D("1.60"), D("0.05"), D("0.00"), D("0.30"), D("15.34"))
    assert s["total"] == D("69.29")


def test_intraday_profile_brokerage_is_the_lower_of_pct_and_flat():
    b = CC.fill_costs(ZR, "intraday", "NSE", "BUY", D("50000"), dp_applies=False, on_date=date(2026, 9, 21))
    assert b["brokerage"] == D("15.00") and b["stt"] == D("0.00") and b["stamp"] == D("1.50") and b["gst"] == D("2.99")
    assert b["total"] == D("21.08")


def test_cost_rates_are_effective_dated_and_retroactive_use_is_flagged():
    with pytest.raises(CC.CostModelError):
        CC.fill_costs(ZR, "delivery", "NSE", "BUY", D("50000"), dp_applies=False, on_date=date(2025, 1, 10))
    r = CC.fill_costs(ZR, "delivery", "NSE", "BUY", D("50000"), dp_applies=False, on_date=date(2025, 1, 10),
                      allow_retroactive=True)
    assert r["retroactive"] is True and r["total"] == D("59.38")
    assert ZR.cost_model_id == "zerodha-equity-v1" and ZR.source_url.startswith("https://zerodha.com/charges")


def test_slippage_by_liquidity_bucket():
    assert CC.slippage_pct(ZR, D("2e9")) == D("0.05") and CC.slippage_pct(ZR, D("5e8")) == D("0.10")
    assert CC.slippage_pct(ZR, D("1e8")) == D("0.20")


# ---------------- execution simulator (§11, v1.1 §32.6-32.7) ----------------
def bar(o, h, l, c, v=100000, pc=100):
    return EX.Bar(open=D(str(o)), high=D(str(h)), low=D(str(l)), close=D(str(c)), volume=v, prev_close=D(str(pc)))


def test_market_on_open_fills_at_the_open_plus_slippage():
    f = EX.fill_entry("MOO", bar(100, 103, 99, 102), qty=100, slippage_pct=D("0.10"), participation_pct=D("5"))
    assert f.status == "FILLED" and f.price == D("100.10") and f.qty == 100


def test_locked_upper_circuit_open_is_not_filled():
    f = EX.fill_entry("MOO", bar(120, 120, 118, 119, pc=100), qty=100, slippage_pct=D("0.10"), participation_pct=D("5"))
    assert f.status == "NO_FILL" and f.reason == "LOCKED_UPPER"


def test_buy_stop_fills_at_trigger_or_the_gap_open_never_better():
    f = EX.fill_entry("BUY_STOP", bar(103, 107, 102, 106), qty=10, slippage_pct=D("0"), participation_pct=D("5"), trigger=D("105"))
    assert f.price == D("105.00")
    f = EX.fill_entry("BUY_STOP", bar(106, 108, 105.5, 107), qty=10, slippage_pct=D("0"), participation_pct=D("5"), trigger=D("105"))
    assert f.price == D("106.00")                                # gapped over the trigger: the open, not the trigger
    f = EX.fill_entry("BUY_STOP", bar(101, 104, 100, 103), qty=10, slippage_pct=D("0"), participation_pct=D("5"), trigger=D("105"))
    assert f.status == "NO_FILL" and f.reason == "NOT_TRIGGERED"


def test_market_on_close_and_partial_fills():
    f = EX.fill_entry("MOC", bar(100, 103, 99, 102), qty=10, slippage_pct=D("0.10"), participation_pct=D("5"))
    assert f.price == D("102.10")
    f = EX.fill_entry("MOO", bar(100, 103, 99, 102, v=10000), qty=1000, slippage_pct=D("0"), participation_pct=D("5"))
    assert f.status == "PARTIAL" and f.qty == 500
    f = EX.fill_entry("MOO", bar(100, 103, 99, 102, v=0), qty=10, slippage_pct=D("0"), participation_pct=D("5"))
    assert f.status == "NO_FILL" and f.reason == "NO_VOLUME"


def test_stops_fill_at_the_stop_or_the_gap_open_and_locked_lower_circuit_cannot_sell():
    f = EX.check_stop(bar(97, 98, 94, 96), D("95"), D("0.10"))
    assert f.reason == "STOP" and f.price == D("94.91")          # 95 x 0.999 = 94.905 -> 94.91
    f = EX.check_stop(bar(93, 96, 92, 95), D("95"), D("0.10"))
    assert f.reason == "GAP_THROUGH" and f.price == D("92.91")    # 93 x 0.999 = 92.907
    assert EX.check_stop(bar(97, 99, 96, 98), D("95"), D("0.10")) is None
    f = EX.check_stop(bar(80, 80, 80, 80, pc=100), D("95"), D("0.10"))
    assert f.status == "NO_FILL" and f.reason == "LOCKED_LOWER"


# ---------------- portfolio risk (§9) ----------------
def test_open_risk_uses_entry_minus_stop_and_trailed_stops_carry_no_risk():
    p = PF.Portfolio(cash=D("500000"))
    p.add(PF.Position("A", "X", 100, D("100"), D("95"), date(2026, 1, 1)))
    p.add(PF.Position("B", "X", 50, D("200"), D("210"), date(2026, 1, 1)))
    assert p.open_risk() == D("500")
    assert p.sector_value("X", {"A": D("102"), "B": D("205")}) == D("20450")


# ---------------- drawdown state machine (§10, BR-006, BR-008) ----------------
def test_daily_loss_pauses_entries_for_one_session_then_resumes():
    m = DD.DrawdownMonitor(POS)
    d0 = date(2026, 1, 5)
    m.start_day(d0, D("500000"))
    ev = m.end_day(d0, D("489000"))                             # -2.2% > 2% daily limit
    assert m.state == "ENTRY_PAUSE" and any(e["event_type"] == "DAILY_LOSS_LIMIT" for e in ev)
    assert not m.entries_allowed(d0 + timedelta(days=1))
    m.start_day(d0 + timedelta(days=1), D("489000"))
    m.end_day(d0 + timedelta(days=1), D("489000"))
    m.start_day(d0 + timedelta(days=2), D("489000"))
    assert m.entries_allowed(d0 + timedelta(days=2)) and m.state == "NORMAL"


def test_drawdown_reduces_risk_then_kills_and_only_an_approved_review_resumes():
    m = DD.DrawdownMonitor(POS, peak_equity=D("500000"))
    d = date(2026, 2, 2)
    m.start_day(d, D("500000"))
    m.end_day(d, D("491000"))                                   # -1.8% day, drawdown 1.8%
    for k, eq in enumerate(("482000", "474000", "466000")):     # cumulative drawdown 3.6% .. 6.8%
        dd = d + timedelta(days=7 * (k + 1))                    # a new week each time: no weekly breach
        m.start_day(dd, D(eq) + D("1"))
        m.end_day(dd, D(eq))
    x = d + timedelta(days=35)
    m.start_day(x, D("466000"))
    m.end_day(x, D("459000"))                                   # 8.2% below the 500,000 peak
    assert m.state == "REDUCED_RISK" and m.risk_multiplier() == D("0.5")
    for k, eq in enumerate(("450000", "442000", "434000", "425000")):
        dd = x + timedelta(days=7 * (k + 1))
        m.start_day(dd, D(eq) + D("1"))
        m.end_day(dd, D(eq))                                    # 15% below the peak at 425,000
    assert m.state == "KILL_SWITCH" and not m.entries_allowed(x + timedelta(days=60))
    m.resume(x + timedelta(days=61), approved=False)
    assert m.state == "KILL_SWITCH"
    m.resume(x + timedelta(days=62), approved=True)
    assert m.state == "NORMAL"


def test_peak_equity_is_not_reset_by_a_configuration_change():
    m = DD.DrawdownMonitor(RC.with_changes(POS, risk_per_trade_pct=D("0.4")), peak_equity=D("600000"))
    m.start_day(date(2026, 3, 2), D("540000"))
    m.end_day(date(2026, 3, 2), D("540000"))
    assert m.peak_equity == D("600000") and m.drawdown_pct() == D("10.00")


def test_manual_kill_switch_blocks_entries_and_is_an_event():
    m = DD.DrawdownMonitor(POS)
    ev = m.kill(date(2026, 3, 3), "owner halt")
    assert m.state == "KILL_SWITCH" and ev["event_type"] == "KILL_SWITCH_MANUAL" and not m.entries_allowed(date(2026, 3, 4))


# ---------------- engine: end-to-end on synthetic bars (§19.2, §19.3) ----------------
DAYS = list(pd.bdate_range("2026-01-05", periods=10).date)
EXITS = {"breakeven_at_r": D("1"), "trail_at_r": D("2"), "trail_atr_mult": D("2"), "max_sessions": 5,
         "cost_estimate_pct_for_sizing": D("0.30")}


def bars_frame(rows):
    return pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume", "value20"])


def flat(symbol, price, n=10, vol=10_000_000):
    return [(symbol, DAYS[k], price, price * 1.01, price * 0.99, price, vol, 5e9) for k in range(n)]


def signal(sid, sym, day, stop, ref, kind="MOO", trigger=None, rank=1.0):
    return {"signal_id": sid, "date": DAYS[day], "symbol": sym, "arm": "T", "order_type": kind, "trigger": trigger,
            "valid_sessions": 1, "stop": stop, "reference_price": ref, "atr": 2.0, "rank": rank}


def test_gap_through_stop_exits_at_the_open_and_costs_more_than_one_r():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 94, 95, 93, 94.5, 10_000_000, 5e9)          # opens below the 95 stop
    res = EN.run(pd.DataFrame([signal("s1", "A", 0, 95, 100)]), bars_frame(rows), POS, ZR, {"A": "X"}, EXITS,
                 allow_retroactive_costs=True)
    t = res.trades.iloc[0]
    assert t.qty == 471                                                  # floor(2500 / (5 + 100 x 0.30%))
    assert t.entry_price == D("100.05") and t.exit_reason == "GAP_THROUGH" and t.exit_price == D("93.95")
    assert t.r_multiple < -1 and t.net_pnl < t.gross_pnl                  # the gap cost more than 1R; costs recorded
    assert t.cost_model_id == "zerodha-equity-v1" and t.risk_config_id == "RISK-POS-1"


def test_breakeven_stop_after_one_r_and_time_exit_after_five_sessions():
    b = flat("B", 200)
    b[2] = ("B", DAYS[2], 205, 212, 204, 211, 10_000_000, 5e9)           # close 211 >= entry + 1R (R = 10)
    b[3] = ("B", DAYS[3], 205, 206, 199, 203, 10_000_000, 5e9)           # low 199 hits the breakeven stop (entry)
    c = flat("C", 50)
    sigs = pd.DataFrame([signal("s2", "B", 0, 190, 200), signal("s3", "C", 0, 48, 50)])
    res = EN.run(sigs, bars_frame(b + c), POS, ZR, {"B": "X", "C": "Y"}, EXITS, allow_retroactive_costs=True)
    tb = res.trades.set_index("symbol").loc["B"]
    assert tb.exit_reason == "STOP" and tb.exit_date == DAYS[3] and tb.exit_price < tb.entry_price
    tc = res.trades.set_index("symbol").loc["C"]
    assert tc.exit_reason == "TIME" and tc.exit_date == DAYS[5]          # s1 = entry session DAYS[1], s5 = DAYS[5]


def test_pit_gate_and_kill_switch_block_entries_and_every_decision_is_recorded():
    sigs = pd.DataFrame([signal("s4", "A", 0, 95, 100)])
    res = EN.run(sigs, bars_frame(flat("A", 100)), POS, ZR, {"A": "X"}, EXITS,
                 eligibility=lambda s: (False, "published after cutoff"), allow_retroactive_costs=True)
    assert res.trades.empty
    [d] = res.decisions
    assert d["decision_status"] == "REJECTED" and "PIT_VIOLATION" in d["rejection_reasons"]
    for k in ("signal_id", "risk_config_version", "cost_model_version", "decision_timestamp", "risk_checks"):
        assert k in d


def test_run_is_deterministic_for_identical_inputs_and_versions():
    sigs = pd.DataFrame([signal("s5", "A", 0, 95, 100), signal("s6", "C", 1, 48, 50)])
    args = (sigs, bars_frame(flat("A", 100) + flat("C", 50)), POS, ZR, {"A": "X", "C": "Y"}, EXITS)
    a = EN.run(*args, allow_retroactive_costs=True)
    b = EN.run(*args, allow_retroactive_costs=True)
    assert a.ledger_digest == b.ledger_digest and len(a.trades) == 2


def test_stop_touched_on_the_entry_bar_exits_the_same_day_at_the_stop():
    rows = flat("A", 100)
    rows[1] = ("A", DAYS[1], 100, 101, 94, 97, 10_000_000, 5e9)          # entered at the open, low 94 breaches 95
    res = EN.run(pd.DataFrame([signal("s7", "A", 0, 95, 100)]), bars_frame(rows), POS, ZR, {"A": "X"}, EXITS,
                 allow_retroactive_costs=True)
    t = res.trades.iloc[0]
    assert t.exit_reason == "STOP_SAME_DAY" and t.exit_date == DAYS[1] and t.exit_price == D("94.95")  # 95 x 0.9995
    assert t.stop_kind == "INITIAL" and t.realised


def test_trailing_stop_after_two_r_fills_at_the_stop_intraday_and_at_the_open_on_a_gap():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 104, 112, 103, 111, 10_000_000, 5e9)        # +2R close (R = 100.05 - 95 = 5.05)
    # trailing stop = highest close 111 - 2 x ATR 2 = 107 (above breakeven), effective from DAYS[3]
    intraday = rows[:3] + [("A", DAYS[3], 110, 111, 105, 106, 10_000_000, 5e9)]   # opens above 107, trades through it
    t = EN.run(pd.DataFrame([signal("s8", "A", 0, 95, 100)]), bars_frame(intraday), POS, ZR, {"A": "X"}, EXITS,
               allow_retroactive_costs=True).trades.iloc[0]
    assert t.exit_reason == "STOP" and t.stop_kind == "TRAILING" and t.exit_price == D("106.95")   # 107 x 0.9995
    gap = rows[:4]                                                        # DAYS[3] opens at 100, below the 107 stop
    t = EN.run(pd.DataFrame([signal("s9", "A", 0, 95, 100)]), bars_frame(gap), POS, ZR, {"A": "X"}, EXITS,
               allow_retroactive_costs=True).trades.iloc[0]
    assert t.exit_reason == "GAP_THROUGH" and t.stop_kind == "TRAILING" and t.exit_price == D("99.95")  # 100 x 0.9995


def test_positions_open_at_the_end_of_the_data_are_flagged_unrealised():
    res = EN.run(pd.DataFrame([signal("s10", "A", 0, 95, 100)]), bars_frame(flat("A", 100, n=3)), POS, ZR, {"A": "X"},
                 EXITS, allow_retroactive_costs=True)
    t = res.trades.iloc[0]
    assert t.exit_reason == "OPEN_AT_END" and not t.realised and t.exit_date == DAYS[2]


def test_stop_ablation_keeps_entries_and_quantities_but_exits_only_on_time():
    rows = flat("A", 100)
    rows[2] = ("A", DAYS[2], 94, 95, 93, 94.5, 10_000_000, 5e9)          # would gap through the 95 stop
    sig = pd.DataFrame([signal("s11", "A", 0, 95, 100)])
    on = EN.run(sig, bars_frame(rows), POS, ZR, {"A": "X"}, EXITS, allow_retroactive_costs=True).trades.iloc[0]
    off = EN.run(sig, bars_frame(rows), POS, ZR, {"A": "X"}, EXITS, allow_retroactive_costs=True,
                 stops_active=False).trades.iloc[0]
    assert on.exit_reason == "GAP_THROUGH" and off.exit_reason == "TIME" and off.exit_date == DAYS[5]
    assert off.qty == on.qty == 471 and off.entry_price == on.entry_price


def test_prepared_bars_give_the_same_ledger():
    sig = pd.DataFrame([signal("s12", "A", 0, 95, 100)])
    frame = bars_frame(flat("A", 100))
    a = EN.run(sig, frame, POS, ZR, {"A": "X"}, EXITS, allow_retroactive_costs=True)
    b = EN.run(sig, None, POS, ZR, {"A": "X"}, EXITS, allow_retroactive_costs=True, prepared=EN.prepare_bars(frame))
    assert a.ledger_digest == b.ledger_digest
