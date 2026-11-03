"""Point-in-time liquid EQ universe (liquid-eq-v1) and the survivorship labels of the DSL backtest (Phase 4.2).

TC-LU-1 … TC-LU-10 of test_reports/p4_research_hardening_TESTCASES.md. Every bar below is MOCK — not real data: round
numbers so membership can be read off by hand (traded value = close × volume; the floor is ₹10 crore = 1e8).
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Dict, List

import pytest

from services.copilot_tools import daas_client as dc
from services.strategy_engine import backtest as bt
from services.strategy_engine import dsl
from services.strategy_engine import liquid_universe as lu
from services.strategy_engine import market_data as md
from services.strategy_engine import screen_bridge
from services.strategy_engine.compiler_stock import compile_stock_query, to_asyncpg


def sessions(n: int, start: date = date(2026, 1, 1)) -> List[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


S = sessions(60)


def row(sym: str, close: float, volume: float, series: str = "EQ") -> Dict[str, Any]:
    return {"symbol": sym, "series": series, "close_price": close, "volume": volume}


def market(n_sessions: int = 60, *, dead_until: int = 44, gaps=frozenset(range(5, 16))) -> Dict[date, List[Dict[str, Any]]]:
    """LIQ: close 100 × 2,000,000 = ₹20 crore every session.  DEAD: ₹30 crore until session `dead_until`, then gone
    (delisted).  THIN: ₹5 crore.  CHEAP: close 15 with ₹30 crore.  NIFTYBEES / GOLDETF: ₹50 crore, ETF names.
    GOLDCASE: ₹50 crore, an ETF only NSE's list names.  BESER: series BE only.  GAPPY: ₹20 crore but missing on the 11
    sessions in `gaps`."""
    by: Dict[date, List[Dict[str, Any]]] = {}
    for i, d in enumerate(S[:n_sessions]):
        rows = [row("LIQ", 100.0, 2_000_000), row("THIN", 100.0, 500_000), row("CHEAP", 15.0, 20_000_000),
                row("NIFTYBEES", 250.0, 2_000_000), row("GOLDETF", 50.0, 10_000_000), row("GOLDCASE", 50.0, 10_000_000),
                row("BESER", 100.0, 5_000_000, "BE")]
        if i <= dead_until:
            rows.append(row("DEAD", 300.0, 1_000_000))
        if i not in gaps:
            rows.append(row("GAPPY", 200.0, 1_000_000))
        by[d] = rows
    return by


# ── TC-LU-1: each condition of the rule ──────────────────────────────────────

ETF_LIST = {"GOLDCASE", "NIFTYBEES"}


def test_tc_lu1_each_condition():
    members, report = lu.membership(S, market(), etf_symbols=ETF_LIST)
    # session index 19 is the 20th session: LIQ has its 20 bars, median ₹20 crore -> in. Index 18: only 19 bars -> out.
    assert "LIQ" in members[S[19]] and "LIQ" not in members[S[18]]
    for d in S[19:]:
        assert "THIN" not in members[d]                       # median ₹5 crore < ₹10 crore
        assert "CHEAP" not in members[d]                      # close 15 < ₹20
        assert not {"NIFTYBEES", "GOLDETF", "GOLDCASE"} & members[d]   # NSE's ETF list, and ETF names
        assert "BESER" not in members[d]                      # series BE only
    # GAPPY misses sessions 5..15 (11 of them). Bars in the 30-session window ending at index i: at 19, sessions 0..4 and
    # 16..19 = 9; at 29 (window 0..29) 30 − 11 = 19; at 34 (window 5..34) still 19 -> out throughout. At 35 the window is
    # 6..35 and only 10 gap sessions remain in it: 20 bars -> in.
    assert all("GAPPY" not in members[S[i]] for i in range(0, 35))
    assert "GAPPY" in members[S[35]]
    assert report["sessions_without_prices"] == [] and report["members_per_session"]["max"] == 3


def test_tc_lu1_without_the_list_only_the_name_rule_catches_etfs():
    members, _ = lu.membership(S, market())
    assert "GOLDCASE" in members[S[30]] and "GOLDETF" not in members[S[30]] and "NIFTYBEES" not in members[S[30]]


def test_tc_lu1_the_floor_is_inclusive_and_uses_the_median():
    by = {d: [row("EDGE", 100.0, 1_000_000)] for d in S[:20]}        # exactly ₹10 crore
    assert "EDGE" in lu.membership(S[:20], by)[0][S[19]]
    # one huge day does not lift a thin stock: the median, not the mean
    by2 = {d: [row("SPIKE", 100.0, 100_000 if i < 19 else 1_000_000_000)] for i, d in enumerate(S[:20])}
    assert "SPIKE" not in lu.membership(S[:20], by2)[0][S[19]]


def test_tc_lu1_a_symbol_must_be_priced_on_the_date():
    by = market()
    by[S[40]] = [r for r in by[S[40]] if r["symbol"] != "LIQ"]          # LIQ has no bar on session 40
    members, _ = lu.membership(S, by)
    assert "LIQ" not in members[S[40]] and "LIQ" in members[S[41]]       # 29 of 30 bars on 41: still in


# ── TC-LU-2: point in time ───────────────────────────────────────────────────

def test_tc_lu2_membership_never_reads_the_future():
    full, _ = lu.membership(S, market())
    for k in (20, 33, 45, 59):
        cut = {d: rows for d, rows in market().items() if d <= S[k]}
        part, _ = lu.membership(S[:k + 1], cut)
        assert part[S[k]] == full[S[k]], k
    # and it does not depend on where a window starts: the members of sessions 50..55 read with a 29-session lookback
    lookback = sorted(d for d in lu.weekdays_before(S[50], 29))
    assert lookback == S[21:50]                                          # the synthetic calendar has no holidays
    read, window = lookback + S[50:56], S[50:56]
    sub, _ = lu.membership(read, {d: market()[d] for d in read}, window)
    assert all(sub[d] == full[d] for d in window)


# ── TC-LU-3: survivorship ────────────────────────────────────────────────────

def test_tc_lu3_a_delisted_stock_is_a_member_while_it_traded():
    members, _ = lu.membership(S, market(dead_until=44))
    assert all("DEAD" in members[S[i]] for i in range(19, 45))
    assert all("DEAD" not in members[S[i]] for i in range(45, 60))


# ── TC-LU-4: a missing price session ─────────────────────────────────────────

def test_tc_lu4_a_missing_session_is_reported_and_does_not_empty_the_universe():
    by = market()
    by[S[40]] = []                                                       # the price file of session 40 is missing
    members, report = lu.membership(S, by, S[30:])
    assert members[S[40]] == set()                                       # nobody is priced that day
    assert {"LIQ", "DEAD"} <= members[S[41]]                             # 29 bars of 30: still members the next day
    assert report["sessions_without_prices"] == [S[40].isoformat()]


# ── TC-LU-5: DSL ─────────────────────────────────────────────────────────────

def _spec(universe, asset="STOCK"):
    return {"version": "1", "asset_class": asset, "name": "t", "universe": universe,
            "entry": {"all_of": [{"feature": "rsi14", "op": ">", "value": 55}]},
            "exit": {"stoploss_pct": 5, "target_rr": 2, "max_hold_days": 10},
            "ranking": {"by": "rsi14", "limit": 5, "order": "desc"}, "rebalance": "daily"}


def test_tc_lu5_market_universe_validation():
    assert dsl.validate_strategy(_spec({"type": "market", "ref": "LIQUID_EQ"})) == []
    errs = [str(e) for e in dsl.validate_strategy(_spec({"type": "market", "ref": "ALL"}))]
    assert any("LIQUID_EQ" in e for e in errs)
    mf = _spec({"type": "market", "ref": "LIQUID_EQ"}, asset="MF")
    mf.pop("exit")
    assert any("MF strategies cannot use market universes" in str(e) for e in dsl.validate_strategy(mf))


def test_tc_lu5_the_compiler_binds_the_members_per_date():
    sql, params = compile_stock_query(_spec({"type": "market", "ref": "LIQUID_EQ"}))
    assert "f.symbol = ANY(:universe_members)" in sql and "index_constituents" not in sql and "is_nifty_100" not in sql


# ── TC-LU-6 / TC-LU-8 / TC-LU-9: the DaaS provider ──────────────────────────

class FakeDaas:
    def __init__(self, by_day, fail_on=None, constituents=None, etf_reply=(200, {"reference_as_of": "2026-02-27",
                 "rows": [{"symbol": "GOLDCASE", "is_etf": True}, {"symbol": "NIFTYBEES", "is_etf": True}, {"symbol": "LIQ", "is_etf": False}]})):
        self.by_day, self.fail_on, self.constituents, self.etf_reply = by_day, fail_on, constituents or [], etf_reply
        self.eod_calls: List[str] = []
        self.feature_symbols: List[str] = []

    async def get_trading_calendar(self, start=None, end=None, timeout=15.0):
        # the FEATURE calendar; shorter than the price history, as on staging (features from session 30, prices from 0)
        return [d.isoformat() for d in S[30:] if (start is None or d.isoformat() >= start) and (end is None or d.isoformat() <= end)]

    async def get_prices_eod_on(self, on, series="EQ", timeout=30.0):
        self.eod_calls.append(on)
        if on == self.fail_on:
            raise dc.DaasError("DAAS /prices/eod returned HTTP 503: down", status_code=503)
        return [r for r in self.by_day.get(date.fromisoformat(on), []) if r["series"] == series]

    async def get_features_bulk(self, symbols, start=None, end=None, timeout=30.0):
        self.feature_symbols.extend(symbols)
        out = {}
        for s in symbols:
            out[s] = [{"symbol": s, "as_of_date": d.isoformat(), "close": 100.0, "rsi14": 60.0, "atr14": 2.0,
                       "accumulation_score": 0.9 if s == "DEAD" else 0.5}
                      for d in S if start <= d.isoformat() <= end and any(r["symbol"] == s for r in self.by_day.get(d, []))]
        return out

    async def get_adjusted_prices_bulk(self, symbols, start=None, end=None, timeout=30.0):
        out = {}
        for s in symbols:
            out[s] = [{"symbol": s, "as_of_date": d.isoformat(), "adj_open": 100.0, "adj_high": 101.0, "adj_low": 99.5,
                       "adj_close": 100.0, "cumulative_adj_factor": 1.0}
                      for d in S if start <= d.isoformat() <= end and any(r["symbol"] == s for r in self.by_day.get(d, []))]
        return out

    async def get_index_constituents(self, index_name, on=None, timeout=15.0):
        return list(self.constituents)

    async def get_raw(self, path, params=None, timeout=10.0):
        assert path == "/features/scan-snapshot"
        if isinstance(self.etf_reply, Exception):
            raise self.etf_reply
        return self.etf_reply


@pytest.fixture
def daas(monkeypatch):
    def install(fake):
        for name in ("get_trading_calendar", "get_prices_eod_on", "get_features_bulk", "get_adjusted_prices_bulk",
                     "get_index_constituents", "get_raw"):
            monkeypatch.setattr(dc, name, getattr(fake, name))
        return fake
    return install


def test_tc_lu6_daas_provider_reads_the_lookback_and_limits_each_date(daas):
    fake = daas(FakeDaas(market()))
    p = md.DaasMarketDataProvider(None)
    spec = _spec({"type": "market", "ref": "LIQUID_EQ"})
    asyncio.run(p.prepare(spec, S[40], S[50]))
    # the window's 11 sessions, then one batch of 35 weekdays before it (S[5..39]): its 29 most recent priced days are
    # the lookback, S[11..39]. The price history starts before the feature calendar, so the lookback is complete.
    assert sorted(fake.eod_calls) == [d.isoformat() for d in S[5:51]]
    assert p.basis["universe_report"]["lookback_sessions"] == 29
    assert p.basis["universe_report"]["etf_list"]["count"] == 2 and "scan-snapshot" in p.basis["universe_report"]["etf_list"]["source"]
    # features only for the symbols that were ever members in the window
    assert sorted(set(fake.feature_symbols)) == ["DEAD", "GAPPY", "LIQ"]
    assert p.basis["universe_basis"] == "point_in_time" and p.basis["universe_rule"]["version"] == "liquid-eq-v1"
    assert "universe_warning" not in p.basis
    on_44 = {r["symbol"] for r in asyncio.run(p.screen(spec, S[44]))}
    on_45 = {r["symbol"] for r in asyncio.run(p.screen(spec, S[45]))}
    assert "DEAD" in on_44 and "DEAD" not in on_45 and "LIQ" in on_45


def test_tc_lu6_the_lookback_skips_weekdays_without_prices_and_stops_at_the_start_of_history(daas):
    by = market()
    for i in (35, 36, 37):                                               # three holidays just before the window
        by[S[i]] = []
    fake = daas(FakeDaas(by))
    p = md.DaasMarketDataProvider(None)
    asyncio.run(p.prepare(_spec({"type": "market", "ref": "LIQUID_EQ"}), S[40], S[42]))
    assert p.basis["universe_report"]["lookback_sessions"] == 29
    # 29 priced days back from S[39], skipping the three holidays, reaches S[8]: a second batch was not needed
    assert set(fake.eod_calls) >= {d.isoformat() for d in S[8:43]}
    assert p.basis["universe_report"]["sessions_without_prices"] == []   # holidays in the lookback are not sessions
    # near the start of the price history the lookback is short, and says so
    p2 = md.DaasMarketDataProvider(None)
    asyncio.run(p2.prepare(_spec({"type": "market", "ref": "LIQUID_EQ"}), S[30], S[31]))
    assert p2.basis["universe_report"]["lookback_sessions"] == 29        # S[1..29]
    early = md.DaasMarketDataProvider(None)
    asyncio.run(early.prepare(_spec({"type": "market", "ref": "LIQUID_EQ"}), S[10], S[31]))
    assert early.basis["universe_report"]["lookback_sessions"] == 10     # only S[0..9] exist before S[10]


def test_tc_lu8_an_unreadable_etf_list_is_reported_and_the_name_rule_still_applies(daas):
    fake = daas(FakeDaas(market(), etf_reply=dc.DaasError("DAAS connectivity error", status_code=None)))
    p = md.DaasMarketDataProvider(None)
    asyncio.run(p.prepare(_spec({"type": "market", "ref": "LIQUID_EQ"}), S[40], S[42]))
    note = p.basis["universe_report"]["etf_list"]
    assert note["source"] == "unavailable" and "DaasError" in note["error"]
    assert "GOLDCASE" in fake.feature_symbols and "NIFTYBEES" not in fake.feature_symbols


def test_tc_lu8_a_failed_price_read_fails_the_run(daas):
    daas(FakeDaas(market(), fail_on=S[30].isoformat()))
    with pytest.raises(dc.DaasError):
        asyncio.run(md.DaasMarketDataProvider(None).prepare(_spec({"type": "market", "ref": "LIQUID_EQ"}), S[40], S[50]))


def test_tc_lu9_an_index_universe_is_labelled_latest_snapshot_with_a_warning(daas):
    daas(FakeDaas(market(), constituents=["LIQ"]))
    p = md.DaasMarketDataProvider(None)
    asyncio.run(p.prepare(_spec({"type": "index", "ref": "NIFTY500"}), S[40], S[50]))
    assert p.basis["universe_basis"] == "latest_snapshot"
    assert p.basis["universe_warning"].startswith("Survivorship bias") and lu.LABEL in p.basis["universe_warning"]


def test_tc_lu3_tc_lu6_the_backtest_enters_a_stock_later_delisted(daas, monkeypatch):
    # End to end through run_backtest on the DaaS provider: DEAD (ranked first) is bought on the first window date it is a
    # member; with an index universe from today's list (LIQ only) it would never have been in the run.
    daas(FakeDaas(market(dead_until=44)))
    monkeypatch.setattr(bt, "get_provider", lambda pool: md.DaasMarketDataProvider(None))
    spec = _spec({"type": "market", "ref": "LIQUID_EQ"})
    spec["ranking"] = {"by": "score", "limit": 5, "order": "desc"}
    res = asyncio.run(bt.run_backtest(None, spec, from_date=S[40], to_date=S[50], max_positions=5, slippage_pct=0.0))
    syms = {(t.symbol, t.entry_date) for t in res.trades}
    assert ("DEAD", S[40]) in syms
    assert all(not (t.symbol == "DEAD" and t.entry_date > S[44]) for t in res.trades)
    m = res.metrics
    assert m["universe_basis"] == "point_in_time" and m["universe_rule"]["version"] == "liquid-eq-v1"
    assert m["provenance"]["universe"] == {"type": "market", "ref": "LIQUID_EQ", "basis": "point_in_time", "warning": None,
                                           "rule": m["universe_rule"]}


# ── TC-LU-7: the SQL provider ────────────────────────────────────────────────

class _Conn:
    def __init__(self, by_day):
        self.by_day, self.screens = by_day, []

    async def fetch(self, sql, *args):
        if "FROM nidp.stock_features_daily WHERE as_of_date BETWEEN" in sql:
            return [{"as_of_date": d} for d in S[30:] if args[0] <= d <= args[1]]
        if "SELECT DISTINCT as_of_date FROM nidp.prices_eod" in sql:
            assert "LIMIT 29" in sql and "series = 'EQ'" in sql
            return [{"as_of_date": d} for d in sorted((d for d in S if d < args[0] and self.by_day.get(d)), reverse=True)[:29]]
        if "FROM nidp.security_reference_daily WHERE is_etf" in sql:
            return [{"symbol": "GOLDCASE"}, {"symbol": "NIFTYBEES"}]
        if "FROM nidp.prices_eod" in sql:
            assert "series = 'EQ'" in sql
            return [{"as_of_date": d, **r} for d in args[0] for r in self.by_day.get(d, []) if r["series"] == "EQ"]
        self.screens.append((sql, args))
        return []


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _A:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _A()


def test_tc_lu7_sql_provider_uses_the_same_rule_and_binds_members_per_date():
    conn = _Conn(market())
    p = md.SqlMarketDataProvider(_Pool(conn))
    spec = _spec({"type": "market", "ref": "LIQUID_EQ"})
    asyncio.run(p.prepare(spec, S[40], S[50]))
    assert p.basis["universe_basis"] == "point_in_time" and p.basis["universe_rule"]["version"] == "liquid-eq-v1"
    asyncio.run(p.screen(spec, S[45]))
    sql, args = conn.screens[-1]
    n_base = len(to_asyncpg(*compile_stock_query(spec))[1])
    assert f"f.as_of_date = ${n_base + 1}" in sql and f"f.symbol = ANY(${n_base + 2})" in sql and ":universe_members" not in sql
    assert args[-2] == S[45] and args[-1] == sorted(lu.membership(S, market(), [S[45]], ETF_LIST)[0][S[45]]) == ["GAPPY", "LIQ"]
    assert p.basis["universe_report"]["etf_list"] == {"source": "nidp.security_reference_daily.is_etf", "count": 2}


def test_tc_lu9_sql_index_fallback_is_warned():
    class C(_Conn):
        async def fetchrow(self, sql, *args):
            return None                                                  # index_constituents empty for the index
    p = md.SqlMarketDataProvider(_Pool(C({})))
    asyncio.run(p.prepare(_spec({"type": "index", "ref": "NIFTY500"}), S[40], S[50]))
    assert p.basis["universe_basis"] == "present_day_fallback" and p.basis["universe_warning"].startswith("Survivorship bias")


# ── TC-LU-10: defaults ───────────────────────────────────────────────────────

def test_tc_lu10_a_screen_built_strategy_defaults_to_the_liquid_universe():
    definition, dropped = screen_bridge.build_definition_from_screen(name="s", filters={"rsi_min": 55})
    assert definition["universe"] == {"type": "market", "ref": "LIQUID_EQ"} and dsl.validate_strategy(definition) == []
    explicit, _ = screen_bridge.build_definition_from_screen(name="s", filters={"rsi_min": 55}, universe={"type": "index", "ref": "NIFTY50"})
    assert explicit["universe"] == {"type": "index", "ref": "NIFTY50"}


def test_tc_lu10_the_catalog_lists_the_liquid_universe_first_as_the_default(monkeypatch):
    import routes.strategy_builder as route

    class Prov:
        def __init__(self, *_):
            self.basis = {}

        async def latest_date(self):
            return S[-1]

        async def prepare(self, spec, a, b):
            return None

        async def screen(self, spec, as_of):
            return [{"return_60d_pct": 6.0, "return_20d_pct": 3.0}]

    class C:
        async def fetch(self, sql, *args):
            return []

    async def user(request):
        return {"user_id": "u"}

    async def pool():
        return _Pool(C())
    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(route.pg_client, "get_pool", pool)
    monkeypatch.setattr(route, "get_provider", lambda p: Prov())
    route._CATALOG_CACHE.clear()
    out = asyncio.run(route.universe_catalog(None))
    first = out["universes"][0]
    assert first["universe"] == {"type": "market", "ref": "LIQUID_EQ"} and first["default"] is True
    assert first["survivorship"] == "point_in_time" and first["name"] == lu.LABEL and first["kind"] == "broad"
    idx = [u for u in out["universes"] if (u.get("universe") or {}).get("type") == "index"]
    assert [u["ref"] for u in idx] == ["NIFTY50", "NIFTY100", "NIFTY200", "NIFTY500"]
    assert all(u["survivorship"] == "latest_snapshot" and not u.get("default") for u in idx)
    route._CATALOG_CACHE.clear()


# ── TC-LU-12 (contract): the browser spec's fixture carries the engine's own universe texts ─

def test_tc_lu12_the_e2e_fixture_matches_the_engine():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures" / "strategy-backtest-universe.json"
    assert path.exists(), f"{path} is the shared browser/engine fixture and must be present"
    fx = json.loads(path.read_text(encoding="utf-8"))
    assert fx["index_run"]["metrics"]["universe_basis"] == "latest_snapshot"
    assert fx["index_run"]["metrics"]["universe_warning"] == md.SURVIVORSHIP_WARNING
    assert fx["liquid_run"]["metrics"]["universe_basis"] == "point_in_time"
    assert fx["liquid_run"]["metrics"]["universe_rule"] == lu.rule()
    first = fx["catalog"]["universes"][0]
    assert first["universe"] == {"type": "market", "ref": lu.REF} and first["name"] == lu.LABEL and first["default"] is True
