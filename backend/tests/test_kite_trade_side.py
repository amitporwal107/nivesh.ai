"""Buyer/seller-initiated prints counted from Kite WebSocket ticks (services/kite_live_feed/trade_side.py) and their path through
the live feed into the quote cache rows.

No network, no Kite, no Redis: ticks, the ticker, Mongo and the clock are the fakes of tests/test_kite_live_feed.py
(MOCK -- not real data). What these tests cannot show is how Kite's real 'full' mode ticks for cash stocks behave in a session.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pytest

from services.kite_live_feed import quote_cache as qc
from services.kite_live_feed import trade_side as ts
from tests.test_kite_live_feed import IST, OPEN_NOW, FakeKite, FakeTicker, make_feed, run

DAY = date(2026, 10, 20)
T0 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=IST)
ZERO = {"ask_trades": 0, "bid_trades": 0, "ask_volume": 0, "bid_volume": 0}


def at(sec: float) -> datetime:
    return T0 + timedelta(seconds=sec)


def counts(d):
    return {k: d[k] for k in ("ask_trades", "bid_trades", "ask_volume", "bid_volume")}


def seeded(bid=100.0, ask=101.0, ltp=100.5, vol=1000):
    s = ts.TradeSides()
    s.on_tick("AAA", DAY, ltp, vol, bid, ask, at(0))
    return s


# ── the switch ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env,want", [({}, False), ({"APP_ENV": "staging"}, True), ({"APP_ENV": "production"}, False),
                                      ({"APP_ENV": "staging", ts.ENV: "0"}, False), ({ts.ENV: "1"}, True),
                                      ({"APP_ENV": "Staging "}, True)])
def test_enabled_on_staging_or_by_switch(env, want):
    assert ts.enabled(env) is want


# ── classification ───────────────────────────────────────────────────────────

def test_first_tick_is_the_baseline_and_counts_nothing():
    s = ts.TradeSides()
    out = s.on_tick("AAA", DAY, 100.5, 1000, 100.0, 101.0, at(0))
    assert counts(out) == ZERO and out["sides_since"] == "2026-10-20T10:00:00+05:30"
    assert set(out) == set(ts.FIELDS)


def test_at_or_above_the_previous_ask_is_an_ask_print_with_the_volume_rise():
    s = seeded()
    out = s.on_tick("AAA", DAY, 101.0, 1050, 100.5, 101.5, at(1))       # the book moved up after the trade; the PREVIOUS ask counts
    assert counts(out) == {"ask_trades": 1, "bid_trades": 0, "ask_volume": 50, "bid_volume": 0}


def test_at_or_below_the_previous_bid_is_a_bid_print():
    s = seeded()
    out = s.on_tick("AAA", DAY, 100.0, 1030, 99.5, 100.5, at(1))
    assert counts(out) == {"ask_trades": 0, "bid_trades": 1, "ask_volume": 0, "bid_volume": 30}


@pytest.mark.parametrize("ltp,side", [(100.7, "ask"), (100.3, "bid")])
def test_strictly_inside_the_spread_goes_by_the_mid(ltp, side):
    s = seeded(bid=100.0, ask=101.0)
    out = s.on_tick("AAA", DAY, ltp, 1010, 100.0, 101.0, at(1))
    assert out[f"{side}_trades"] == 1 and out[f"{side}_volume"] == 10


@pytest.mark.parametrize("prev_ltp,side", [(100.4, "ask"), (100.6, "bid")])
def test_at_the_mid_the_tick_test_decides(prev_ltp, side):
    s = seeded(bid=100.0, ask=101.0, ltp=prev_ltp)
    out = s.on_tick("AAA", DAY, 100.5, 1010, 100.0, 101.0, at(1))
    assert out[f"{side}_trades"] == 1


def test_at_the_mid_unchanged_keeps_the_last_counted_side_and_with_no_side_yet_counts_nothing():
    s = seeded(bid=100.0, ask=101.0, ltp=100.5)
    out = s.on_tick("AAA", DAY, 100.5, 1010, 100.0, 101.0, at(1))       # mid, unchanged price, no side yet
    assert counts(out) == ZERO
    s.on_tick("AAA", DAY, 101.0, 1020, 100.0, 101.0, at(2))             # at the ask
    out = s.on_tick("AAA", DAY, 100.5, 1025, 100.0, 101.0, at(3))       # mid, price down 101 -> 100.5: tick test says bid
    assert (out["ask_trades"], out["bid_trades"]) == (1, 1)
    out = s.on_tick("AAA", DAY, 100.5, 1027, 100.0, 101.0, at(4))       # mid, unchanged: the last side (bid)
    assert (out["ask_trades"], out["bid_trades"], out["bid_volume"]) == (1, 2, 7)


def test_a_tick_without_a_volume_rise_is_not_a_print_but_updates_the_quote():
    s = seeded(bid=100.0, ask=101.0)
    out = s.on_tick("AAA", DAY, 100.5, 1000, 102.0, 103.0, at(1))       # the book moved, nothing traded
    assert counts(out) == ZERO
    out = s.on_tick("AAA", DAY, 102.0, 1040, 102.0, 103.0, at(2))       # 102 = the NEW previous bid
    assert counts(out) == {"ask_trades": 0, "bid_trades": 1, "ask_volume": 0, "bid_volume": 40}


@pytest.mark.parametrize("bid,ask", [(None, None), (None, 101.0), (0.0, 101.0), (101.0, 100.0)])
def test_no_usable_previous_bid_ask_falls_back_to_the_tick_test(bid, ask):
    s = seeded(bid=bid, ask=ask, ltp=100.0)
    out = s.on_tick("AAA", DAY, 100.2, 1010, None, None, at(1))         # up from 100.0
    assert out["ask_trades"] == 1
    out = s.on_tick("AAA", DAY, 100.1, 1020, None, None, at(2))         # down
    assert out["bid_trades"] == 1


def test_a_new_ist_day_starts_from_zero():
    s = seeded()
    s.on_tick("AAA", DAY, 101.0, 1050, 100.5, 101.5, at(1))
    nxt = datetime(2026, 10, 21, 9, 20, tzinfo=IST)
    out = s.on_tick("AAA", date(2026, 10, 21), 101.0, 200, 100.5, 101.5, nxt)
    assert counts(out) == ZERO and out["sides_since"] == "2026-10-21T09:20:00+05:30"
    assert s.counts("AAA", DAY) is None and s.counts("AAA", date(2026, 10, 21))["ask_trades"] == 0


def test_the_opening_auction_is_never_classified():
    s = ts.TradeSides()
    pre = datetime(2026, 10, 20, 9, 8, 0, tzinfo=IST)
    s.on_tick("AAA", DAY, 100.0, 0, 99.0, 100.0, pre)
    out = s.on_tick("AAA", DAY, 100.0, 5000, 99.5, 100.5, datetime(2026, 10, 20, 9, 15, 0, tzinfo=IST))     # at 09:15:00
    assert counts(out) == ZERO
    out = s.on_tick("AAA", DAY, 100.5, 9000, 100.0, 100.5, datetime(2026, 10, 20, 9, 15, 0, 600000, tzinfo=IST))
    assert counts(out) == ZERO                    # the first tick after a pre-open baseline is a baseline (may hold the auction)
    assert out["sides_since"] == "2026-10-20T09:15:00+05:30"
    out = s.on_tick("AAA", DAY, 100.5, 9100, 100.0, 100.5, datetime(2026, 10, 20, 9, 15, 2, tzinfo=IST))
    assert counts(out) == {"ask_trades": 1, "bid_trades": 0, "ask_volume": 100, "bid_volume": 0}


def test_after_1530_the_counts_stay():
    s = seeded()
    s.on_tick("AAA", DAY, 101.0, 1050, 100.5, 101.5, at(1))
    out = s.on_tick("AAA", DAY, 99.0, 9050, 98.5, 99.5, datetime(2026, 10, 20, 15, 45, tzinfo=IST))
    assert counts(out) == {"ask_trades": 1, "bid_trades": 0, "ask_volume": 50, "bid_volume": 0}


def test_rebase_makes_the_next_tick_a_baseline_and_keeps_the_counts():
    s = seeded()
    s.on_tick("AAA", DAY, 101.0, 1050, 100.5, 101.5, at(1))
    s.rebase()
    out = s.on_tick("AAA", DAY, 99.0, 50000, 98.5, 99.5, at(60))        # 48,950 traded while the socket was down: not counted
    assert counts(out) == {"ask_trades": 1, "bid_trades": 0, "ask_volume": 50, "bid_volume": 0}
    assert out["sides_since"] == "2026-10-20T10:00:00+05:30"
    out = s.on_tick("AAA", DAY, 98.5, 50010, 98.5, 99.5, at(61))
    assert (out["bid_trades"], out["bid_volume"]) == (1, 10)


def test_a_volume_that_goes_back_is_neither_counted_nor_a_new_baseline():
    s = seeded(vol=1000)
    out = s.on_tick("AAA", DAY, 101.0, 990, 100.5, 101.5, at(1))
    assert counts(out) == ZERO
    out = s.on_tick("AAA", DAY, 101.0, 1010, 100.5, 101.5, at(2))       # 10 over the 1,000 baseline, at the old ask 101
    assert (out["ask_trades"], out["ask_volume"]) == (1, 10)


def test_symbols_are_counted_apart():
    s = ts.TradeSides()
    s.on_tick("AAA", DAY, 100.5, 1000, 100.0, 101.0, at(0))
    s.on_tick("BBB", DAY, 50.0, 10, 49.9, 50.1, at(0))
    s.on_tick("AAA", DAY, 101.0, 1100, 100.0, 101.0, at(1))
    s.on_tick("BBB", DAY, 49.9, 30, 49.9, 50.1, at(1))
    assert (s.counts("AAA", DAY)["ask_volume"], s.counts("BBB", DAY)["bid_volume"]) == (100, 20)


def test_the_rule_is_the_same_as_the_truedata_path():
    from services.scan_builder import tick_flow
    grid = [(l, b, a, p, sd) for l in (99.0, 100.0, 100.4, 100.5, 100.6, 101.0, 102.0) for b, a in
            ((100.0, 101.0), (None, None), (0.0, 101.0), (101.0, 100.0), (100.0, 100.0)) for p in (None, 100.5)
            for sd in (-1, 0, 1)]
    assert all(ts.classify(*g) == tick_flow.classify(*g) for g in grid)


# ── through the feed ─────────────────────────────────────────────────────────

def _depth(bid, ask):
    return {"buy": [{"price": bid, "quantity": 10, "orders": 1}], "sell": [{"price": ask, "quantity": 10, "orders": 1}]}


def _tick(token, ltp, vol, bid=None, ask=None, **extra):
    t = {"instrument_token": token, "last_price": ltp, "ohlc": {"open": 99.0, "high": 102.0, "low": 98.0, "close": 98.0},
         "volume_traded": vol, "exchange_timestamp": datetime(2026, 10, 20, 14, 32, 6)}
    if bid is not None:
        t["depth"] = _depth(bid, ask)
    t.update(extra)
    return t


def ws_feed(on=True, kite=None):
    FakeTicker.instances.clear()
    f = make_feed(force_rest=False, trade_sides=on, kite=kite or FakeKite())
    run(f.tick())
    f._ticker._connect(None)
    return f


def test_cash_stocks_go_to_full_mode_when_on_and_indices_stay_in_quote_mode():
    f = ws_feed(on=True)
    modes = FakeTicker.instances[0].modes
    full = {t for m, toks in modes if m == "full" for t in toks}
    quote = {t for m, toks in modes if m == "quote" for t in toks}
    assert {1000, 1001, 1002} <= full                       # AAA, BBB, CCC (Nifty 500 in the fake universe)
    assert 256265 in quote and 256265 not in full           # NIFTY 50 stays in quote mode
    assert {f.token_map[s] for s in f.ordered if f._kind(s) == "EQ"} <= f._full_tokens()


def test_when_off_the_cash_stocks_stay_in_quote_mode_and_quotes_carry_no_counts():
    f = ws_feed(on=False)
    full = {t for m, toks in FakeTicker.instances[0].modes if m == "full" for t in toks}
    assert not ({1000, 1001, 1002} & full) and f._sides is None
    f._ticker._ticks(None, [_tick(1000, 100.5, 1000, 100.0, 101.0), _tick(1000, 101.0, 1050, 100.5, 101.5)])
    assert not set(ts.FIELDS) & set(f.quotes["AAA"])
    row = qc.cache_row(f.quotes["AAA"], "EQ", "open")
    assert all(row[k] is None for k in ts.FIELDS) and not set(ts.FIELDS) & set(qc.as_quote(row))


def test_cash_ticks_accumulate_onto_the_quote_and_the_cache_row():
    f = ws_feed(on=True)
    t = f._ticker
    t._ticks(None, [_tick(1000, 100.5, 1000, 100.0, 101.0)])           # baseline
    t._ticks(None, [_tick(1000, 101.0, 1050, 100.5, 101.5)])           # at the previous ask: 50 on the ask
    t._ticks(None, [_tick(1000, 100.5, 1080, 100.0, 100.5)])           # at the previous bid: 30 on the bid
    q = f.quotes["AAA"]
    assert (q["ask_trades"], q["bid_trades"], q["ask_volume"], q["bid_volume"]) == (1, 1, 50, 30)
    assert q["sides_since"] == "2026-10-20T14:32:05+05:30" and q["ltp"] == 100.5 and q["volume"] == 1080
    row = qc.cache_row(q, f._kind("AAA"), "open")
    assert (row["kind"], row["ask_trades"], row["bid_trades"], row["ask_volume"], row["bid_volume"], row["sides_since"]) == \
        ("EQ", 1, 1, 50, 30, "2026-10-20T14:32:05+05:30")
    assert qc.as_quote(row) == {k: v for k, v in q.items() if k != "symbol"}      # round trip, same keys as the snapshot


def test_the_leader_writes_the_counts_to_the_cache(monkeypatch):
    f = ws_feed(on=True)
    f._ticker._ticks(None, [_tick(1000, 100.5, 1000, 100.0, 101.0), _tick(1000, 101.0, 1050, 100.5, 101.5)])
    written = []

    async def fake_write(rows, chains, ttl):
        written.extend(rows)
        return True
    monkeypatch.setattr(qc, "write", fake_write)
    run(f._flush_cache(OPEN_NOW + timedelta(seconds=5)))
    row = {r["symbol"]: r for r in written}["AAA"]
    assert (row["ask_trades"], row["ask_volume"], row["bid_trades"], row["source"]) == (1, 50, 0, "ws")


def test_futures_and_index_ticks_are_not_counted():
    from tests.test_kite_live_feed import FakeKiteFut
    f = ws_feed(on=True, kite=FakeKiteFut())
    t = f._ticker
    for _ in range(2):
        t._ticks(None, [_tick(7001, 250.0, 10, 249.5, 250.5, oi=5000), _tick(256265, 25000.0, 0)])
    assert not set(ts.FIELDS) & set(f.quotes["AAA26OCTFUT"]) and not set(ts.FIELDS) & set(f.quotes["NIFTY 50"])
    assert f.quotes["AAA26OCTFUT"]["oi"] == 5000.0
    full = {x for m, toks in FakeTicker.instances[0].modes if m == "full" for x in toks}
    assert {7001, 7101, 1000} <= full


def test_a_counting_failure_never_drops_the_quote_and_warns_once_a_minute(monkeypatch, caplog):
    f = ws_feed(on=True)

    def boom(*a, **k):
        raise RuntimeError("bad state")
    monkeypatch.setattr(f._sides, "on_tick", boom)
    with caplog.at_level(logging.WARNING):
        f._ticker._ticks(None, [_tick(1000, 100.5, 1000, 100.0, 101.0), _tick(1001, 50.0, 10, 49.9, 50.1)])
    assert f.quotes["AAA"]["ltp"] == 100.5 and f.quotes["BBB"]["ltp"] == 50.0
    assert "AAA" in f._dirty and not set(ts.FIELDS) & set(f.quotes["AAA"])
    warns = [r for r in caplog.records if "trade-side count failed" in r.getMessage()]
    assert len(warns) == 1 and "RuntimeError" in warns[0].getMessage() and "bad state" not in warns[0].getMessage()


def test_a_reconnect_makes_the_next_tick_a_baseline():
    f = ws_feed(on=True)
    t = f._ticker
    t._ticks(None, [_tick(1000, 100.5, 1000, 100.0, 101.0), _tick(1000, 101.0, 1050, 100.5, 101.5)])
    t._connect(None)                                                    # KiteTicker reconnected
    t._ticks(None, [_tick(1000, 99.0, 90000, 98.5, 99.5)])              # the gap's volume: not on a side
    q = f.quotes["AAA"]
    assert (q["ask_trades"], q["ask_volume"], q["bid_trades"], q["bid_volume"]) == (1, 50, 0, 0)
    t._ticks(None, [_tick(1000, 98.5, 90020, 98.0, 99.0)])
    assert (f.quotes["AAA"]["bid_trades"], f.quotes["AAA"]["bid_volume"]) == (1, 20)


def test_a_rest_quote_keeps_the_day_counts_so_far():
    f = ws_feed(on=True)
    f._ticker._ticks(None, [_tick(1000, 100.5, 1000, 100.0, 101.0), _tick(1000, 101.0, 1050, 100.5, 101.5)])
    run(f._rest_cycle(OPEN_NOW, full=True))
    q = f.quotes["AAA"]
    assert q["source"] == "rest" and q["volume"] == 1234                # FakeKite's REST quote
    assert (q["ask_trades"], q["ask_volume"], q["bid_trades"]) == (1, 50, 0)
    assert not set(ts.FIELDS) & set(f.quotes["NIFTY 50"])               # an index never carries them
    assert not set(ts.FIELDS) & set(f.quotes["CCC"])                    # nothing counted for CCC today: no fields
