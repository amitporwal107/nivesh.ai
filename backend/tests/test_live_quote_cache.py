"""Live quote cache (PR C): index options on the feed, top of book, the per-symbol Redis cache, 1-minute replay snapshots,
GET /api/live/option-chain and the Redis-first /api/live/quotes. Test IDs refer to test_reports/live_quote_cache_TESTCASES.md.

No network, no Mongo, no Redis, no Kite: Kite, the ticker, Mongo, Redis and the clock are fakes (MOCK -- not real data).
The option rows follow the shape of Kite's NFO instrument dump; the tradingsymbols are made up (MOCK) and follow no real
Kite pattern. What these tests cannot show is real Redis and Kite behaviour during a session: that is UNVERIFIED here
(see test_reports/OVERRIDE_live_quote_cache.md).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from routes import live_quotes
from services.kite_live_feed import config as cfg
from services.kite_live_feed import feed as feed_mod
from services.kite_live_feed import quote_cache as qc
from services.kite_live_feed import universe as uni
from services.kite_live_feed.feed import make_quote, top_of_book
from tests.test_kite_live_feed import AFTER_CLOSE, IST, NSE, OPEN_NOW, Clock, FakeDB, FakeKite, FakeTicker, make_feed, run

TODAY = OPEN_NOW.date()                                       # Tuesday 2026-10-20


# ── fakes (MOCK -- not real data) ────────────────────────────────────────────

def _opt_rows(name: str, expiry: date, strikes: List[float], base: int, lot: int) -> List[dict]:
    rows = []
    for i, k in enumerate(strikes):
        for j, t in enumerate(("CE", "PE")):
            rows.append({"name": name, "instrument_type": t, "segment": "NFO-OPT", "expiry": expiry, "strike": float(k),
                         "tradingsymbol": f"{name}{expiry:%y%m%d}{int(k)}{t}", "instrument_token": base + 2 * i + j,
                         "lot_size": lot})
    return rows


NIFTY_STRIKES = [24000 + 50 * i for i in range(41)]            # 24000 .. 26000
BANK_STRIKES = [55000 + 100 * i for i in range(21)]            # 55000 .. 57000
OPT_NFO = (
    [{"name": "NIFTY", "instrument_type": "FUT", "tradingsymbol": "NIFTY26OCTFUT", "instrument_token": 8001,
      "expiry": date(2026, 10, 27), "lot_size": 75},
     {"name": "BANKNIFTY", "instrument_type": "FUT", "tradingsymbol": "BANKNIFTY26OCTFUT", "instrument_token": 8002,
      "expiry": date(2026, 10, 27), "lot_size": 35},
     {"name": "NIFTY", "instrument_type": "CE", "tradingsymbol": "NIFTYBROKENCE", "instrument_token": 8999,
      "expiry": date(2026, 10, 27), "lot_size": 75}]                                      # no strike: skipped
    + _opt_rows("NIFTY", date(2026, 10, 13), NIFTY_STRIKES, 140000, 75)                    # expired
    + _opt_rows("NIFTY", date(2026, 10, 27), NIFTY_STRIKES, 110000, 75)
    + _opt_rows("NIFTY", date(2026, 11, 3), NIFTY_STRIKES, 120000, 75)
    + _opt_rows("NIFTY", date(2026, 11, 24), NIFTY_STRIKES, 130000, 75)                    # third expiry: not kept
    + _opt_rows("BANKNIFTY", date(2026, 10, 27), BANK_STRIKES, 210000, 35)
    + _opt_rows("BANKNIFTY", date(2026, 11, 24), BANK_STRIKES, 220000, 35)
    + _opt_rows("AAA", date(2026, 10, 27), [90, 100, 110], 310000, 500)                    # not a configured underlying
)
PRICES = {"NSE:NIFTY 50": 25012.0, "NSE:NIFTY BANK": 56040.0, "NFO:NIFTY26OCTFUT": 25110.0, "NFO:BANKNIFTY26OCTFUT": 56200.0}


def _depth(p: float) -> dict:
    empty = [{"price": 0, "quantity": 0, "orders": 0}] * 4
    return {"buy": [{"price": p - 0.5, "quantity": 750, "orders": 3}] + empty,
            "sell": [{"price": p + 0.5, "quantity": 600, "orders": 2}] + empty}


class FakeKiteOpt(FakeKite):
    """FakeKite with an NFO dump that has index options, per-key prices, and depth on NFO quotes."""

    def __init__(self, prices=None, absent=(), **kw):
        super().__init__(**kw)
        self.prices, self.absent = dict(PRICES, **(prices or {})), set(absent)

    def instruments(self, ex):
        if self.fail:
            raise self.fail
        return self.rows if ex == "NSE" else OPT_NFO

    def quote(self, keys):
        data = super().quote([k for k in keys if k not in self.absent])
        for k, v in data.items():
            if k in self.prices:
                v["last_price"] = self.prices[k]
            if k.startswith("NFO:"):
                v.update({"oi": 5000, "depth": _depth(v["last_price"])})
        return data


class FakePipe:
    def __init__(self, r: "FakeRedis"):
        self.r, self.cmds = r, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        self.cmds = []

    def set(self, k, v, ex=None):
        self.cmds.append(("set", k, v, ex))
        return self

    def delete(self, k):
        self.cmds.append(("delete", k))
        return self

    def hset(self, k, mapping=None):
        self.cmds.append(("hset", k, dict(mapping or {})))
        return self

    def expire(self, k, ttl):
        self.cmds.append(("expire", k, ttl))
        return self

    async def execute(self):
        if self.r.fail:
            raise self.r.fail
        self.r.executes += 1
        self.r.batches.append(list(self.cmds))
        for c in self.cmds:
            if c[0] == "set":
                self.r.kv[c[1]], self.r.ttl[c[1]] = c[2], c[3]
            elif c[0] == "delete":
                self.r.kv.pop(c[1], None)
                self.r.hashes.pop(c[1], None)
                self.r.ttl.pop(c[1], None)
            elif c[0] == "hset":
                self.r.hashes.setdefault(c[1], {}).update(c[2])
            elif c[0] == "expire":
                self.r.ttl[c[1]] = c[2]
        self.cmds = []
        return [True] * len(self.r.batches[-1])


class FakeRedis:
    """MOCK -- not real data: a dict-backed stand-in for redis.asyncio with decode_responses=True."""

    def __init__(self):
        self.kv: Dict[str, str] = {}
        self.hashes: Dict[str, Dict[str, str]] = {}
        self.ttl: Dict[str, Any] = {}
        self.executes = 0
        self.batches: List[list] = []
        self.fail = None
        self.mget_calls: List[List[str]] = []

    def pipeline(self, transaction=True):
        return FakePipe(self)

    async def mget(self, keys):
        if self.fail:
            raise self.fail
        self.mget_calls.append(list(keys))
        return [self.kv.get(k) for k in keys]

    async def hgetall(self, key):
        if self.fail:
            raise self.fail
        return dict(self.hashes.get(key, {}))

    def row(self, qkey):
        raw = self.kv.get(qc.quote_key(qkey))
        return json.loads(raw) if raw else None

    def sets(self, batch=-1):
        return [c[1] for c in self.batches[batch] if c[0] == "set"]


@pytest.fixture(autouse=True)
def redis(monkeypatch):
    for k in (cfg.OPTION_UNDERLYINGS_ENV, cfg.OPTION_EXPIRIES_ENV, cfg.OPTION_STRIKES_ENV, cfg.QUOTE_CACHE_TTL_ENV,
              cfg.MINUTE_TTL_ENV, cfg.CADENCE_ENV):
        monkeypatch.delenv(k, raising=False)
    r = FakeRedis()
    r.state = {"client": r, "raise": None}
    r.mono = {"t": 1000.0}

    async def getter():
        if r.state["raise"]:
            raise r.state["raise"]
        return r.state["client"]
    monkeypatch.setattr(qc, "get_client", getter)
    monkeypatch.setattr(qc, "_gate", qc._Gate())
    monkeypatch.setattr(qc, "_mono", lambda: r.mono["t"])
    return r


def opt_feed(db=None, **kw):
    """A leader feed with the options on: pass 1 has no spot yet (options pending), pass 2 adds them."""
    kw.setdefault("kite", FakeKiteOpt())
    f = make_feed(db, **kw)
    run(f.tick())
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    return f


def _window(f, underlying, expiry):
    return sorted({f._opt_meta[s]["strike"] for s in f.sets["options"]
                   if f._opt_meta[s]["underlying"] == underlying and f._opt_meta[s]["expiry"] == expiry})


# ── TC-1 config ──────────────────────────────────────────────────────────────

def test_option_and_cache_settings_defaults_parsing_and_clamps():
    assert cfg.option_underlyings({}) == ["NIFTY", "BANKNIFTY"]
    assert cfg.option_underlyings({cfg.OPTION_UNDERLYINGS_ENV: " nifty , finnifty,NIFTY "}) == ["NIFTY", "FINNIFTY"]
    assert cfg.option_underlyings({cfg.OPTION_UNDERLYINGS_ENV: ""}) == []
    assert (cfg.option_expiries({}), cfg.option_strikes_each_side({}), cfg.quote_cache_ttl_seconds({}), cfg.minute_ttl_days({})) == (2, 15, 600, 90)
    assert cfg.option_expiries({cfg.OPTION_EXPIRIES_ENV: "9"}) == 4 and cfg.option_expiries({cfg.OPTION_EXPIRIES_ENV: "x"}) == 2
    assert cfg.option_strikes_each_side({cfg.OPTION_STRIKES_ENV: "-3"}) == 0
    assert cfg.quote_cache_ttl_seconds({cfg.QUOTE_CACHE_TTL_ENV: "5"}) == 30
    assert cfg.minute_ttl_days({cfg.MINUTE_TTL_ENV: "30"}) == 30


# ── TC-2..4 option selection ─────────────────────────────────────────────────

def test_option_contracts_keep_the_two_nearest_unexpired_expiries_of_configured_underlyings():
    ch = uni.option_contracts(OPT_NFO, ["NIFTY", "BANKNIFTY"], TODAY, 2)
    assert sorted(ch) == ["BANKNIFTY", "NIFTY"]                             # AAA is not configured
    assert sorted(ch["NIFTY"]) == ["2026-10-27", "2026-11-03"]              # 10-13 expired, 11-24 is the third
    assert sorted(ch["BANKNIFTY"]) == ["2026-10-27", "2026-11-24"]
    c = next(x for x in ch["NIFTY"]["2026-10-27"] if x["strike"] == 25000.0 and x["option_type"] == "CE")
    assert c == {"symbol": "NIFTY26102725000CE", "token": 110000 + 2 * 20, "underlying": "NIFTY", "expiry": "2026-10-27",
                 "strike": 25000.0, "option_type": "CE", "lot_size": 75}
    assert all("BROKEN" not in x["symbol"] for x in ch["NIFTY"]["2026-10-27"])        # no strike: skipped
    assert len(ch["NIFTY"]["2026-10-27"]) == 82
    # on the expiry day itself that expiry is still the nearest
    assert sorted(uni.option_contracts(OPT_NFO, ["NIFTY"], date(2026, 10, 27), 2)["NIFTY"]) == ["2026-10-27", "2026-11-03"]
    assert uni.option_contracts(OPT_NFO, ["NIFTY"], TODAY, 0) == {} and uni.option_contracts(OPT_NFO, [], TODAY, 2) == {}


def test_atm_strike_is_the_nearest_listed_strike_and_a_tie_takes_the_lower():
    assert uni.atm_strike([24950.0, 25000.0, 25050.0], 25012.0) == 25000.0
    assert uni.atm_strike([24950.0, 25000.0, 25050.0], 25025.0) == 25000.0
    assert uni.atm_strike([24950.0, 25000.0, 25050.0], 25026.0) == 25050.0
    assert uni.atm_strike([], 25000.0) is None and uni.atm_strike([25000.0], None) is None and uni.atm_strike([25000.0], 0) is None


def test_select_options_takes_atm_plus_minus_n_both_types_clipped_at_the_ends_and_never_guesses_a_missing_spot():
    ch = uni.option_contracts(OPT_NFO, ["NIFTY", "BANKNIFTY"], TODAY, 2)
    picked, missing = uni.select_options(ch, {"NIFTY": 25012.0, "BANKNIFTY": None}, 15)
    assert missing == ["BANKNIFTY"] and {c["underlying"] for c in picked} == {"NIFTY"}
    near = [c for c in picked if c["expiry"] == "2026-10-27"]
    assert len(near) == 62 and min(c["strike"] for c in near) == 24250.0 and max(c["strike"] for c in near) == 25750.0
    assert [c["option_type"] for c in near[:2]] == ["CE", "PE"]
    picked, missing = uni.select_options(ch, {"NIFTY": 25012.0, "BANKNIFTY": 56040.0}, 15)
    bank = [c for c in picked if c["underlying"] == "BANKNIFTY" and c["expiry"] == "2026-10-27"]
    assert missing == [] and len(bank) == 42                                 # 21 listed strikes: clipped at both ends
    assert len(uni.select_options(ch, {"NIFTY": 25012.0}, 0)[0]) == 4       # ATM only: CE + PE for each of 2 expiries


# ── TC-5..9 options on the feed ──────────────────────────────────────────────

def test_options_are_the_last_universe_set_quoted_under_nfo_and_decorated():
    f = opt_feed()
    opts = f.sets["options"]
    assert len(opts) == 2 * 31 * 2 + 2 * 21 * 2
    assert f.ordered[-len(opts):] == opts                                     # last in priority
    asked = {k for call in f._kite_obj.quote_calls for k in call}
    assert "NFO:NIFTY26102725000CE" in asked and "NSE:NIFTY26102725000CE" not in asked
    q = {x["symbol"]: x for x in f.snapshot["quotes"]}["NIFTY26102725000PE"]
    assert (q["instrument"], q["underlying"], q["expiry"], q["strike"], q["option_type"], q["lot_size"]) == (
        "OPT", "NIFTY", "2026-10-27", 25000.0, "PE", 75)
    assert f._status_doc(f._clock.now)["universe"]["options"] == len(opts)


def test_the_first_pass_without_a_spot_leaves_options_pending_and_the_next_pass_adds_them():
    f = make_feed(kite=FakeKiteOpt())
    run(f.tick())
    assert f.sets["options"] == [] and sorted(f._opt_missing) == ["BANKNIFTY", "NIFTY"]
    f._clock.now += timedelta(seconds=5)                                      # far less than the 15-minute rebuild
    run(f.tick())
    assert f.sets["options"] and f._opt_missing == []


def test_atm_comes_from_the_index_quote():
    f = opt_feed()
    assert _window(f, "NIFTY", "2026-10-27") == [float(k) for k in range(24250, 25751, 50)]     # NIFTY 50 at 25012
    assert _window(f, "BANKNIFTY", "2026-10-27") == [float(k) for k in BANK_STRIKES]          # NIFTY BANK at 56040


def test_atm_falls_back_to_the_near_future_when_the_index_quote_is_absent():
    f = opt_feed(kite=FakeKiteOpt(absent={"NSE:NIFTY 50"}))
    assert "NIFTY 50" not in f.quotes
    assert _window(f, "NIFTY", "2026-10-27")[15] == 25100.0                  # NIFTY26OCTFUT at 25110


def test_options_are_subscribed_in_full_mode():
    FakeTicker.instances.clear()
    f = opt_feed(force_rest=False)
    f._ticker._connect(None)
    modes = FakeTicker.instances[-1].modes
    opt_tokens = {f.token_map[s] for s in f.sets["options"]}
    full = {t for m, toks in modes if m == "full" for t in toks}
    quote = {t for m, toks in modes if m == "quote" for t in toks}
    assert opt_tokens <= full and not (opt_tokens & quote) and 8001 in full


def test_the_window_re_centres_on_the_next_rebuild():
    FakeTicker.instances.clear()
    f = opt_feed(force_rest=False)
    old = set(f.sets["options"])
    f._kite_obj.prices["NSE:NIFTY 50"] = 25260.0
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    assert set(f.sets["options"]) == old                                     # not yet: the rebuild is every 15 minutes
    f._clock.now += timedelta(minutes=15)
    run(f.tick())
    assert _window(f, "NIFTY", "2026-10-27") == [float(k) for k in range(24500, 26001, 50)]
    assert "NIFTY26102724250CE" in old and "NIFTY26102724250CE" not in f.sets["options"]
    toks = set(f._ticker._tokens)
    assert f.token_map["NIFTY26102726000CE"] in toks and f.token_map["NIFTY26102724250CE"] not in toks


def test_over_the_cap_options_are_dropped_first_then_futures(monkeypatch):
    tm = {s: i for i, s in enumerate(["I1", "I2", "N1", "N2", "N3", "F1", "F2", "O1", "O2", "O3"])}
    args = (["I1", "I2"], [], ["N1", "N2", "N3"], [], tm, ["F1", "F2"], ["O1", "O2", "O3"])
    monkeypatch.setattr(uni, "MAX_INSTRUMENTS", 8)
    assert uni.assemble(*args)[0] == ["I1", "I2", "N1", "N2", "N3", "F1", "F2", "O1"]
    monkeypatch.setattr(uni, "MAX_INSTRUMENTS", 6)
    assert uni.assemble(*args)[0] == ["I1", "I2", "N1", "N2", "N3", "F1"]


def test_option_settings_turn_the_window_off_or_narrow_it():
    f = make_feed(kite=FakeKiteOpt())
    f.option_underlyings = []
    run(f.tick())
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    assert f.sets["options"] == [] and f._opt_meta == {}
    g = make_feed(kite=FakeKiteOpt())
    g.option_strikes, g.option_expiries = 2, 1
    run(g.tick())
    g._clock.now += timedelta(seconds=5)
    run(g.tick())
    assert len(g.sets["options"]) == 5 * 2 * 2 and _window(g, "NIFTY", "2026-10-27") == [24900.0, 24950.0, 25000.0, 25050.0, 25100.0]


# ── TC-10..11 top of book ────────────────────────────────────────────────────

def test_make_quote_keeps_top_of_book_and_none_never_zero():
    q = make_quote("X", 101.0, {"close": 100.0}, 10, 0, datetime(2026, 10, 20, 14, 32, 4), OPEN_NOW, _depth(101.0))
    assert (q["bid"], q["ask"], q["bid_qty"], q["ask_qty"]) == (100.5, 101.5, 750, 600)
    assert q["exchange_ts"] == "2026-10-20T14:32:04+05:30" and q["received_at"].startswith("2026-10-20T14:32:05")
    bare = make_quote("X", 101.0, {}, 10, 0, None, OPEN_NOW)
    assert (bare["bid"], bare["ask"], bare["bid_qty"], bare["ask_qty"], bare["exchange_ts"]) == (None, None, None, None, None)
    assert bare["ts"].startswith("2026-10-20T14:32:05")                       # ts still falls back to the receive time
    assert top_of_book({"buy": [{"price": 0, "quantity": 0}], "sell": []}) == {"bid": None, "ask": None, "bid_qty": None, "ask_qty": None}
    assert top_of_book({"buy": [{"price": 5.0, "quantity": 0}]})["bid_qty"] is None
    assert top_of_book("junk")["bid"] is None


def test_rest_and_full_mode_ticks_both_carry_the_top_of_book():
    f = opt_feed(force_rest=False)
    q = {x["symbol"]: x for x in f.snapshot["quotes"]}
    assert (q["NIFTY26OCTFUT"]["bid"], q["NIFTY26OCTFUT"]["ask"]) == (25109.5, 25110.5) and q["NIFTY26OCTFUT"]["source"] == "rest"
    assert q["AAA"]["bid"] is None                                            # no depth sent for it: None, not 0
    tok = f.token_map["NIFTY26102725000CE"]
    f._ticker._connect(None)
    f._ticker._ticks(None, [{"instrument_token": tok, "last_price": 120.0, "ohlc": {"close": 110.0}, "volume_traded": 9,
                             "oi": 700, "depth": _depth(120.0), "exchange_timestamp": datetime(2026, 10, 20, 14, 32, 9)}])
    t = f.quotes["NIFTY26102725000CE"]
    assert (t["bid"], t["ask"], t["bid_qty"], t["ask_qty"], t["source"]) == (119.5, 120.5, 750, 600, "ws")
    assert t["exchange_ts"] == "2026-10-20T14:32:09+05:30" and t["instrument"] == "OPT"


# ── TC-12..18 the Redis cache ────────────────────────────────────────────────

SPEC_FIELDS = {"symbol", "exchange", "kind", "underlying", "expiry", "strike", "option_type", "lot_size", "ltp", "change",
               "change_pct", "ohlc", "volume", "oi", "bid", "ask", "bid_qty", "ask_qty", "exchange_ts", "received_at",
               "source", "session"}


def test_the_leader_writes_every_changed_quote_with_the_spec_fields_kind_and_ttl(redis):
    f = opt_feed()
    out = run(f.cache_pass())
    assert out["cached"] == len(f.ordered) and redis.executes == 1
    eq, idx, fut, opt = (redis.row(k) for k in ("NSE:AAA", "NSE:NIFTY 50", "NFO:NIFTY26OCTFUT", "NFO:NIFTY26102725000CE"))
    assert SPEC_FIELDS <= set(opt)
    assert (eq["kind"], idx["kind"], fut["kind"], opt["kind"]) == ("EQ", "INDEX", "FUT", "OPT")
    assert (eq["exchange"], fut["exchange"], opt["exchange"]) == ("NSE", "NFO", "NFO")
    assert (opt["underlying"], opt["expiry"], opt["strike"], opt["option_type"], opt["lot_size"]) == ("NIFTY", "2026-10-27", 25000.0, "CE", 75)
    assert (opt["bid"], opt["ask"], opt["bid_qty"], opt["ask_qty"]) == (99.5, 100.5, 750, 600)
    assert opt["session"] == "open" and opt["source"] == "rest" and opt["ohlc"]["close"] == 98.0
    assert eq["bid"] is None and eq["underlying"] is None and fut["lot_size"] == 75
    assert {redis.ttl[qc.quote_key(k)] for k in ("NSE:AAA", "NFO:NIFTY26102725000CE")} == {600}


def test_the_chain_index_maps_strike_and_type_to_the_key_and_is_replaced_on_re_centre(redis):
    f = opt_feed()
    run(f.cache_pass())
    key = qc.chain_key("NIFTY", "2026-10-27")
    h = redis.hashes[key]
    assert len(h) == 62 and h["25000|CE"] == "NFO:NIFTY26102725000CE" and redis.ttl[key] == 600
    assert sorted(redis.hashes) == sorted(qc.chain_key(u, x) for u, x in (("NIFTY", "2026-10-27"), ("NIFTY", "2026-11-03"),
                                                                          ("BANKNIFTY", "2026-10-27"), ("BANKNIFTY", "2026-11-24")))
    f._kite_obj.prices["NSE:NIFTY 50"] = 25260.0
    f._clock.now += timedelta(seconds=5)
    run(f.tick())
    f._clock.now += timedelta(minutes=15)
    run(f.tick())
    run(f.cache_pass())
    h = redis.hashes[key]
    assert "24250|CE" not in h and h["26000|PE"] == "NFO:NIFTY26102726000PE" and len(h) == 62
    assert qc.strike_field(102.5, "PE") == "102.5|PE" and qc.strike_field(25000.0, "CE") == "25000|CE"


def test_writes_are_batched_once_per_second_and_only_changed_quotes_are_rewritten(redis):
    f = opt_feed()
    run(f.cache_pass())
    assert redis.executes == 1
    for p in (101.0, 102.0, 103.0):                                           # three ticks for AAA, one for BBB
        f._on_tick(1000, {"last_price": p, "ohlc": {"close": 98.0}})
    f._on_tick(1001, {"last_price": 55.0, "ohlc": {"close": 50.0}})
    assert run(f.cache_pass())["cached"] == 0 and redis.executes == 1       # same second: nothing
    f._clock.now += timedelta(seconds=1)
    assert run(f.cache_pass())["cached"] == 2 and redis.executes == 2
    assert sorted(redis.sets()) == [qc.quote_key("NSE:AAA"), qc.quote_key("NSE:BBB")]
    assert redis.row("NSE:AAA")["ltp"] == 103.0 and redis.row("NSE:AAA")["source"] == "ws"
    f._clock.now += timedelta(seconds=10)
    assert run(f.cache_pass())["cached"] == 0 and redis.executes == 2       # nothing changed: nothing written


def test_during_the_session_a_quiet_quote_is_rewritten_after_half_the_ttl(redis):
    f = opt_feed()
    n = run(f.cache_pass())["cached"]
    f._clock.now += timedelta(seconds=299)
    assert run(f.cache_pass())["cached"] == 0
    f._clock.now += timedelta(seconds=2)
    assert run(f.cache_pass())["cached"] == n                               # kept alive, received_at unchanged
    assert redis.row("NSE:AAA")["received_at"].startswith("2026-10-20T14:32:10")


def test_a_follower_writes_nothing(redis):
    db = FakeDB()
    opt_feed(db, holder="A")
    b = make_feed(db, holder="B", kite=FakeKiteOpt())
    run(b.tick())
    b._dirty.add("AAA")
    assert run(b.cache_pass()) == {} and redis.executes == 0 and b._dirty == set()


def test_redis_down_never_breaks_the_feed_warns_once_and_recovers(redis, caplog):
    f = opt_feed()
    redis.state["raise"] = ConnectionError("redis://user:pw@host down")
    with caplog.at_level(logging.WARNING):
        assert run(f.cache_pass())["cached"] == 0
        for _ in range(5):                                                    # breaker closed: no retry, no new warning
            f._clock.now += timedelta(seconds=1)
            run(f.cache_pass())
        f._clock.now += timedelta(seconds=5)
        run(f.tick())
        assert f.state == "live" and f.snapshot["count"] > 0                 # the feed carries on
        redis.mono["t"] += 3                                                  # breaker opens again; Redis still down
        f._clock.now += timedelta(seconds=1)
        run(f.cache_pass())
    warns = [r for r in caplog.records if "live quote cache: redis" in r.getMessage()]
    assert len(warns) == 1 and "ConnectionError" in warns[0].getMessage()   # rate limited, class name only
    assert "pw@host" not in caplog.text
    redis.state["raise"] = None
    redis.mono["t"] += 120
    f._clock.now += timedelta(seconds=1)
    assert run(f.cache_pass())["cached"] == len(f.ordered)                 # nothing lost: pending quotes all land
    redis.fail = RuntimeError("OOM")                                          # a failing pipeline is absorbed the same way
    f._on_tick(1000, {"last_price": 111.0, "ohlc": {"close": 98.0}})
    f._clock.now += timedelta(seconds=1)
    assert run(f.cache_pass())["cached"] == 0 and "AAA" in f._dirty


def test_redis_not_configured_is_silent_and_the_cache_is_simply_absent(redis, caplog):
    redis.state["client"] = None
    f = opt_feed()
    with caplog.at_level(logging.WARNING):
        assert run(f.cache_pass())["cached"] == 0
    assert not [r for r in caplog.records if r.name == qc.logger.name]
    assert run(qc.read_quotes(["AAA"])) is None and run(qc.read_chain("NIFTY", "2026-10-27")) == ("unavailable", [])


# ── TC-19..22 minute snapshots ───────────────────────────────────────────────

def _minutes(f):
    return f.db[feed_mod.COL_MINUTE].docs


def test_one_compact_minute_doc_per_open_minute_for_indices_futures_and_options():
    f = opt_feed()
    assert run(f.cache_pass())["minute"] is True
    assert list(_minutes(f)) == ["2026-10-20T14:32"]
    d = _minutes(f)["2026-10-20T14:32"]
    syms = {r["s"] for r in d["rows"]}
    assert {"NIFTY 50", "NIFTY BANK", "NIFTY26OCTFUT", "NIFTY26102725000CE"} <= syms and "AAA" not in syms
    assert d["count"] == len(d["rows"]) == 2 + 2 + len(f.sets["options"]) and d["saved_at"] is not None
    opt = next(r for r in d["rows"] if r["s"] == "NIFTY26102725000CE")
    assert opt == {"s": "NIFTY26102725000CE", "p": 100.0, "b": 99.5, "a": 100.5, "bq": 750, "aq": 600, "o": 5000.0,
                   "v": 1234.0, "t": "2026-10-20T14:32:04+05:30", "u": "NIFTY", "x": "2026-10-27", "k": 25000.0, "ot": "CE"}
    idx = next(r for r in d["rows"] if r["s"] == "NIFTY 50")
    assert set(idx) <= {"s", "p", "v", "t"} and "b" not in idx               # null values are left out
    f._clock.now += timedelta(seconds=10)
    assert run(f.cache_pass())["minute"] is False and len(_minutes(f)) == 1
    f._clock.now += timedelta(seconds=45)                                     # 14:33:05
    run(f.cache_pass())
    assert sorted(_minutes(f)) == ["2026-10-20T14:32", "2026-10-20T14:33"]


def test_the_first_write_of_a_minute_wins():
    f = opt_feed()
    run(f.db[feed_mod.COL_MINUTE].insert_one({"_id": "2026-10-20T14:32", "by": "other-leader"}))
    assert run(f.cache_pass())["minute"] is False
    assert _minutes(f)["2026-10-20T14:32"] == {"_id": "2026-10-20T14:32", "by": "other-leader"} and f._last_minute == "2026-10-20T14:32"


def test_no_minute_doc_outside_the_session_but_the_closing_quotes_are_cached(redis):
    f = make_feed(clock=Clock(AFTER_CLOSE), kite=FakeKiteOpt())
    run(f.tick())
    out = run(f.cache_pass())
    assert out["minute"] is False and _minutes(f) == {}
    assert out["cached"] > 0 and redis.row("NSE:AAA")["session"] == "closed"


def test_a_failed_minute_write_is_logged_once_and_retried(caplog):
    f = opt_feed()
    coll = f.db[feed_mod.COL_MINUTE]
    real = coll.insert_one

    async def boom(doc):
        raise RuntimeError("mongo down")
    coll.insert_one = boom
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            f._clock.now += timedelta(seconds=1)
            run(f.cache_pass())
    assert len([r for r in caplog.records if "minute snapshot write failed" in r.getMessage()]) == 1 and "mongo down" not in caplog.text
    coll.insert_one = real
    f._clock.now += timedelta(seconds=1)
    assert run(f.cache_pass())["minute"] is True


def test_the_minute_collection_has_a_configurable_ttl_index_and_a_conflict_does_not_stop_the_start(monkeypatch, caplog):
    db = FakeDB()
    run(feed_mod.ensure_indexes(db))
    assert any(k.get("expireAfterSeconds") == 90 * 86400 for _, k in db[feed_mod.COL_MINUTE].indexes)
    monkeypatch.setenv(cfg.MINUTE_TTL_ENV, "30")
    db2 = FakeDB()
    run(feed_mod.ensure_indexes(db2))
    assert any(k.get("expireAfterSeconds") == 30 * 86400 for _, k in db2[feed_mod.COL_MINUTE].indexes)

    async def conflict(*a, **k):
        raise RuntimeError("IndexOptionsConflict")
    db2[feed_mod.COL_MINUTE].create_index = conflict
    with caplog.at_level(logging.WARNING):
        run(feed_mod.ensure_indexes(db2))                                     # no raise
    assert any("TTL index not (re)created" in r.getMessage() for r in caplog.records)


# ── TC-23..27 routes ─────────────────────────────────────────────────────────

def _app(monkeypatch, f, user=True):
    monkeypatch.setattr(live_quotes, "get_feed", lambda: f)

    async def fake_user(request: Request):
        if not user:
            raise HTTPException(status_code=401, detail="no")
        return {"user_id": "u1"}
    monkeypatch.setattr(live_quotes, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(live_quotes.router)
    return TestClient(app)


def _opt_row(strike: float, side: str, age_s: float, expiry="2026-10-27") -> dict:
    now = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    q = make_quote(f"NIFTY{strike:.0f}{side}", 120.0, {"close": 110.0}, 50, 900, now, now, _depth(120.0))
    q.update({"instrument": "OPT", "underlying": "NIFTY", "expiry": expiry, "strike": strike, "option_type": side,
              "lot_size": 75, "source": "ws"})
    return qc.cache_row(q, "OPT", "open")


def _seed_chain(rows):
    run(qc.write(rows, {qc.chain_key("NIFTY", "2026-10-27"): {qc.strike_field(r["strike"], r["option_type"]): f"NFO:{r['symbol']}"
                                                              for r in rows}}, 600))


def test_option_chain_groups_by_strike_with_received_at_and_stale_flags(monkeypatch, redis):
    f = make_feed(cadence=30)
    run(f.tick())
    _seed_chain([_opt_row(25000.0, "CE", 5), _opt_row(25000.0, "PE", 200), _opt_row(25050.0, "CE", 5)])
    b = _app(monkeypatch, f).get("/api/live/option-chain", params={"underlying": "nifty", "expiry": "2026-10-27"})
    assert b.status_code == 200
    b = b.json()
    assert (b["underlying"], b["expiry"], b["cache"], b["stale_after_seconds"], b["count"], b["stale_count"], b["lot_size"]) == (
        "NIFTY", "2026-10-27", "ok", 60, 3, 1, 75)
    assert [r["strike"] for r in b["rows"]] == [25000.0, 25050.0] and b["rows"][1]["PE"] is None
    ce, pe = b["rows"][0]["CE"], b["rows"][0]["PE"]
    assert ce["stale"] is False and pe["stale"] is True and ce["received_at"] and 190 < pe["age_seconds"] < 230
    assert (ce["ltp"], ce["bid"], ce["ask"], ce["oi"]) == (120.0, 119.5, 120.5, 900.0) and "kind" not in ce


def test_option_chain_is_200_with_no_rows_when_the_cache_is_unavailable_or_empty(monkeypatch, redis):
    f = make_feed(cadence=30)
    run(f.tick())
    c = _app(monkeypatch, f)
    redis.state["client"] = None
    r = c.get("/api/live/option-chain", params={"underlying": "NIFTY", "expiry": "2026-10-27"})
    assert r.status_code == 200 and r.json()["cache"] == "unavailable" and r.json()["rows"] == [] and r.json()["count"] == 0
    monkeypatch.setattr(qc, "_gate", qc._Gate())
    redis.state["client"] = redis
    r = c.get("/api/live/option-chain", params={"underlying": "NIFTY", "expiry": "2026-11-03"})
    assert r.status_code == 200 and r.json()["cache"] == "empty" and r.json()["rows"] == []


def test_option_chain_needs_sign_in_and_a_valid_expiry(monkeypatch):
    f = make_feed()
    assert _app(monkeypatch, f, user=False).get("/api/live/option-chain?underlying=NIFTY&expiry=2026-10-27").status_code == 401
    c = _app(monkeypatch, f)
    assert c.get("/api/live/option-chain", params={"underlying": "NIFTY", "expiry": "27-10-2026"}).status_code == 422
    assert c.get("/api/live/option-chain", params={"underlying": "NI FTY;", "expiry": "2026-10-27"}).status_code == 422


def _fresh(f):
    f.clock = lambda: datetime.now(timezone.utc)
    f.snapshot["data_at"] = datetime.now(timezone.utc).isoformat()


def test_quotes_prefer_the_fresher_redis_quote_and_fill_the_rest_from_the_snapshot(monkeypatch, redis):
    f = make_feed(cadence=2, kite=FakeKiteOpt())
    run(f.tick())
    c = _app(monkeypatch, f)
    redis.state["client"] = None                                              # baseline: the snapshot path
    base = c.get("/api/live/quotes", params={"symbols": "AAA,BBB,NIFTY26OCTFUT,NOPE"}).json()
    monkeypatch.setattr(qc, "_gate", qc._Gate())
    redis.state["client"] = redis
    now = datetime.now(timezone.utc)
    aaa = make_quote("AAA", 105.0, {"close": 98.0}, 10, 0, None, now, _depth(105.0))
    aaa["source"] = "ws"
    fut = make_quote("NIFTY26OCTFUT", 25200.0, {"close": 25000.0}, 10, 6000, now, now, _depth(25200.0))
    fut.update({"instrument": "FUT", "underlying": "NIFTY", "expiry": "2026-10-27", "oi_high": None, "oi_low": None,
                "lot_size": 75, "source": "ws"})
    old = make_quote("BBB", 1.0, {"close": 98.0}, 10, 0, None, datetime(2020, 1, 1, tzinfo=timezone.utc))    # older than the snapshot's
    run(qc.write([qc.cache_row(aaa, "EQ", "open"), qc.cache_row(fut, "FUT", "open"), qc.cache_row(old, "EQ", "open")], {}, 600))
    b = c.get("/api/live/quotes", params={"symbols": "AAA,BBB,NIFTY26OCTFUT,NOPE"}).json()
    assert set(b) == set(base)                                                # same body keys
    assert (b["quotes"]["AAA"]["ltp"], b["quotes"]["AAA"]["bid"], b["quotes"]["AAA"]["ask"]) == (105.0, 104.5, 105.5)
    assert b["quotes"]["BBB"] == base["quotes"]["BBB"] and b["quotes"]["BBB"]["ltp"] == 100.0      # snapshot was newer
    assert b["quotes"]["NIFTY26OCTFUT"]["ltp"] == 25200.0 and b["quotes"]["NIFTY26OCTFUT"]["underlying"] == "NIFTY"
    assert set(b["quotes"]["AAA"]) == set(base["quotes"]["AAA"])             # same quote keys whichever store answered
    assert set(b["quotes"]["NIFTY26OCTFUT"]) == set(base["quotes"]["NIFTY26OCTFUT"])
    assert b["missing"] == ["NOPE"] and b["count"] == 3
    assert qc.quote_key("NFO:NIFTY26OCTFUT") in redis.mget_calls[-1] and qc.quote_key("NFO:AAA") not in redis.mget_calls[-1]


def test_quotes_with_redis_down_are_exactly_the_snapshot_answer(monkeypatch, redis):
    f = make_feed(cadence=2, kite=FakeKiteOpt())
    run(f.tick())
    _fresh(f)
    c = _app(monkeypatch, f)
    redis.state["raise"] = ConnectionError("down")
    b = c.get("/api/live/quotes", params={"symbols": "AAA,NIFTY 50"}).json()
    want = live_quotes.build_payload(f.snapshot, run(f.read_status()), ["AAA", "NIFTY 50"], datetime.now(timezone.utc))
    assert b["quotes"] == json.loads(json.dumps(want["quotes"])) and b["missing"] == [] and b["count"] == 2


def test_a_cached_row_round_trips_to_the_snapshot_quote_shape():
    f = opt_feed()
    for sym, kind in (("AAA", "EQ"), ("NIFTY 50", "INDEX"), ("NIFTY26OCTFUT", "FUT"), ("NIFTY26102725000CE", "OPT")):
        q = f.quotes[sym]
        assert f._kind(sym) == kind
        assert qc.as_quote(qc.cache_row(q, kind, "open")) == {k: v for k, v in q.items() if k != "symbol"}, sym
