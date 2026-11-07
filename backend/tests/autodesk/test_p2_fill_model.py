"""AD-P2-32, 40..49, 70: the pure parts — order state machine, fill decisions, costs, quote checks. TEST DATA only."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.execution import costs
from autodesk.execution import fill_model as fm
from autodesk.market.live_quotes import check_quote
from tests.autodesk import p2_harness as H

D = Decimal
P = fm.DEFAULT_PARAMS
S = date(2026, 11, 5)


def ov(kind="EQ", side="BUY", otype="LIMIT", qty=100, lot=1, ref="1000", limit="1005", filled=0, inval=None):
    return fm.OrderView(key=f"{kind}:ACME", kind=kind, side=side, order_type=otype, quantity=qty, lot_size=lot,
                        ref_price=D(ref), filled_qty=filled, limit_price=D(limit) if otype == "LIMIT" else None,
                        invalidation=D(inval) if inval else None)


def op(open_="1000", prev="1000", units=1_000_000, lot=None, traded=True, exists=True):
    return fm.OpenPrint(exists=exists, open=D(open_), prev_close=D(prev), traded=traded, traded_units=units, lot_size=lot,
                        source="TEST DATA")


def rng(seed=1, side="BUY"):
    return fm.rng_for(seed, S, "EQ:ACME", side)


# ── AD-P2-32 state machine ─────────────────────────────────────────────────────────────────────────

def test_adp2_32_legal_and_illegal_moves():
    for frm, tos in C.ORDER_TRANSITIONS.items():
        for to in tos:
            assert to in C.ORDER_TRANSITIONS[frm]
    legal = [("CREATED", "VALIDATED"), ("VALIDATED", "SUBMITTED"), ("SUBMITTED", "ACKNOWLEDGED"), ("ACKNOWLEDGED", "OPEN"),
             ("OPEN", "PARTIALLY_FILLED"), ("PARTIALLY_FILLED", "FILLED"), ("OPEN", "CANCEL_PENDING"),
             ("CANCEL_PENDING", "CANCELLED"), ("SUBMITTED", "UNKNOWN"), ("UNKNOWN", "EXPIRED")]
    for a, b in legal:
        assert C.OrderState(b) in C.ORDER_TRANSITIONS[C.OrderState(a)], (a, b)
    illegal = [("FILLED", "OPEN"), ("CREATED", "FILLED"), ("EXPIRED", "OPEN"), ("EXPIRED", "FILLED"), ("CANCELLED", "OPEN"),
               ("REJECTED", "VALIDATED"), ("OPEN", "CREATED")]
    for a, b in illegal:
        assert C.OrderState(b) not in C.ORDER_TRANSITIONS[C.OrderState(a)], (a, b)
    assert all(C.ORDER_TRANSITIONS[s] == set() for s in C.ORDER_TERMINAL)


# ── AD-P2-40 / 41 market and marketable limit at the open ──────────────────────────────────────────

def test_adp2_40_market_buy_and_sell_at_the_open():
    b = fm.decide_open(ov(otype="MARKET", ref="1000"), op("1000"), P, rng())
    s = fm.decide_open(ov(side="SELL", otype="MARKET", ref="1000"), op("1000"), P, rng(side="SELL"))
    assert b.action == s.action == "FILL" and b.arrival == s.arrival == D("1000")
    assert b.price > D("1000") > s.price                                  # open ± half spread ± slippage
    assert fm.on_tick(b.price) and fm.on_tick(s.price)
    assert b.price - D("1000") >= D("0.5") and b.spread_rs == D("0.5") * 100 and b.slippage_rs > 0   # 0.05 % of 1000
    assert b.price - b.arrival - b.spread_rs / 100 == b.slippage_rs / 100          # the amounts recorded add up to the price


def test_adp2_41_marketable_limit_fills_at_the_priced_fill_never_past_the_limit():
    d = fm.decide_open(ov(limit="1005"), op("1000"), P, rng())
    assert d.action == "FILL" and d.price <= D("1005")
    tight = fm.decide_open(ov(limit="1000.50"), op("1000"), P, rng())
    assert tight.action in ("FILL", "REST") and (tight.action == "REST" or tight.price <= D("1000.50"))


def test_adp2_42_limit_not_marketable_rests_then_close_fills_only_through():
    d = fm.decide_open(ov(limit="990"), op("1000"), P, rng())
    assert d.action == "REST" and d.code == "LIMIT_NOT_REACHED"
    o = ov(limit="990")
    through = fm.decide_close(o, fm.CloseRange(low=D("989.9"), high=D("1010"), traded=True, traded_units=1_000_000), P)
    touch = fm.decide_close(o, fm.CloseRange(low=D("990"), high=D("1010"), traded=True, traded_units=1_000_000), P)
    above = fm.decide_close(o, fm.CloseRange(low=D("995"), high=D("1010"), traded=True, traded_units=1_000_000), P)
    assert through.action == "FILL" and through.price == D("990")                   # at the limit, passive
    assert through.spread_rs == 0 and through.slippage_rs == 0
    assert touch.action == "REST" and above.action == "REST"


def test_adp2_43_volume_share_partial_in_whole_lots():
    o = ov(kind="FUT", qty=1500, lot=500, ref="1000", limit="1010")
    d = fm.decide_open(o, op("1000", units=7_000, lot=500), P, rng())               # 10 % of 7,000 = 700 → 500 (one lot)
    assert d.action == "FILL" and d.qty == 500
    none = fm.decide_open(o, op("1000", units=4_000, lot=500), P, rng())            # 400 < one lot
    assert none.action == "REST" and none.code == "VOLUME_CAP"
    eq = fm.decide_open(ov(qty=1000, limit="1010"), op("1000", units=5_000), P, rng())
    assert eq.qty == 500


def test_adp2_44_latency_on_the_simulated_clock_fixed_by_seed():
    ds = [fm.decide_open(ov(), op(), P, fm.rng_for(sd, S, "EQ:ACME", "BUY")).latency_ms for sd in range(1, 40)]
    assert all(50 <= x <= 400 for x in ds) and len(set(ds)) > 5
    assert fm.decide_open(ov(), op(), P, rng(7)).latency_ms == fm.decide_open(ov(), op(), P, rng(7)).latency_ms


@pytest.mark.parametrize("name,order,pr,code", [
    ("lot", ov(kind="FUT", qty=500, lot=500, limit="1005"), op("1000", lot=250), "LOT_SIZE"),
    ("band", ov(limit="1300"), op("1250", prev="1000"), "PRICE_BAND"),
    ("moved", ov(limit="1300"), op("1150", prev="1140"), "REFERENCE_MOVED"),
    ("untraded", ov(kind="CE", qty=500, lot=500, ref="30", limit="34"), op("30", traded=False, units=0), "UNTRADED_CONTRACT"),
    ("invalidation", ov(inval="960", limit="1005"), op("955", prev="1000"), "THROUGH_INVALIDATION"),
    ("collar", ov(otype="MARKET", ref="1000"), op("1050", prev="1040"), "COLLAR"),
])
def test_adp2_45_each_rejection_has_its_code(name, order, pr, code):
    d = fm.decide_open(order, pr, P, rng())
    assert d.action == "REJECT" and d.code == code, (name, d)


def test_adp2_45_no_bar_waits():
    d = fm.decide_open(ov(), fm.OpenPrint(exists=False), P, rng())
    assert d.action == "REST" and d.code == "NO_BAR"


def test_adp2_46_costs_by_segment_equal_the_card_with_zero_slippage():
    from services import desk_cost_card as card
    for kind, seg in (("EQ", "equity_delivery"), ("FUT", "futures"), ("CE", "options")):
        for side in ("BUY", "SELL"):
            got = costs.charges(kind, side, D("100000"))
            want = card.order_side(seg, side, 100000.0, {**card.SNAPSHOT, "slippage_pct_per_side": 0.0})
            assert got["total"] == D(str(want["total"])).quantize(D("0.01")) and got["slippage"] == 0
            assert all(isinstance(v, Decimal) for v in got.values())
    first = costs.charges("EQ", "BUY", D("100000"), first_fill=True)["brokerage"]
    later = costs.charges("EQ", "BUY", D("100000"), first_fill=False)["brokerage"]
    assert first > 0 and later == 0


def test_adp2_48_same_seed_same_result_other_seed_differs_streams_independent():
    a = [fm.decide_open(ov(), op(), P, fm.rng_for(42, S, "EQ:ACME", "BUY")) for _ in range(3)]
    assert a[0] == a[1] == a[2]
    others = {fm.decide_open(ov(), op(), P, fm.rng_for(sd, S, "EQ:ACME", "BUY")).slippage_rs for sd in range(10)}
    assert len(others) > 1
    # a stream depends on seed|session|instrument|side only, not on what was drawn for another order first
    r1 = fm.rng_for(5, S, "EQ:ACME", "BUY")
    fm.rng_for(5, S, "EQ:OTHER", "BUY").random()
    r2 = fm.rng_for(5, S, "EQ:ACME", "BUY")
    assert r1.random() == r2.random()


def test_adp2_49_open_decision_cannot_see_the_rest_of_the_bar():
    import inspect
    assert set(inspect.signature(fm.OpenPrint).parameters) == {"exists", "open", "prev_close", "traded", "traded_units", "lot_size", "source"}
    base = fm.decide_open(ov(), op(), P, rng())
    again = fm.decide_open(ov(), op(), P, rng())
    assert base == again


# ── AD-P2-70 quote checks ───────────────────────────────────────────────────────────────────────────

def test_adp2_70_quote_checks():
    now = datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)                           # 10:30 IST
    ok = H.quote("EQ:ACME", "ACME", 1000, bid=999.9, ask=1000.1, at=now - timedelta(seconds=10))
    assert check_quote(ok, now) is None
    assert check_quote(H.quote("EQ:ACME", "ACME", 1000, at=now - timedelta(seconds=121)), now) == "QUOTE_STALE"
    assert check_quote(H.quote("EQ:ACME", "ACME", 1000, at=now - timedelta(days=1)), now) in ("QUOTE_NOT_TODAY", "QUOTE_STALE")
    assert check_quote(H.quote("EQ:ACME", "ACME", 1000, volume=0, at=now - timedelta(seconds=5)), now) == "QUOTE_NOT_TRADED_TODAY"
    assert check_quote(None, now) == "QUOTE_MISSING"
    nol = H.quote("EQ:ACME", "ACME", 1000, at=now - timedelta(seconds=5))
    nol = nol.__class__(**{**nol.__dict__, "ltp": None})
    assert check_quote(nol, now) == "QUOTE_NO_PRICE"
