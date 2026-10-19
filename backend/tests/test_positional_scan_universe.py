"""Opportunity scanner rules (services/positional_engine/setup_rules.py) and the routes that use them:
GET /api/positional/watchlist (bucket thresholds, gap gate, rules + versions), GET /api/positional/picks (versions) and
GET /api/positional/scan-universe (eligible universe, exclusions, categories, model rank percentile).

No database and no network: pg_client.get_pool answers each SQL with fixture rows, daas_client.get_raw answers with
fixture bodies, and the move_odds gate is replaced. Every fixture is MOCK — not real data.

Worked examples
  rank percentile  values A 0.30, B 0.20, C 0.20, D 0.10 (n = 4, n − 1 = 3)
                   A: 3 below            → 100 × 3 / 3          = 100.0
                   B: 1 below, 1 equal   → 100 × (1 + 0.5) / 3  = 50.0   (C the same)
                   D: 0 below            → 0.0
  traded value     the snapshot sends traded_value_cr_20d; the ₹10 Cr gate passes 10.0 and fails 9.99
  band limit       prev 100, close 119.95, band 20 % → move 19.95 % ≥ 20 − 0.1 → at the limit (excluded)
  gap gate         previous close 99.50, open 104.98 → +5.51 % > 5 % → not breakout_confirmed;
                   open 104.47 → +4.995 % → confirmed; exactly 5.00 % passes (checked on the rule itself)
"""
from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.positional as route
from services.positional_engine import setup_rules as rules

DAY = date(2026, 10, 12)


# ── fakes ────────────────────────────────────────────────────────────────────

class _Conn:
    def __init__(self, handler, calls):
        self.handler, self.calls = handler, calls

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.handler(sql, args)

    async def fetchrow(self, sql, *args):
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, handler, calls):
        self.conn = _Conn(handler, calls)

    def acquire(self):
        return _Acquire(self.conn)


def _client(monkeypatch, *, handler=None, daas=None, model_denied: Optional[str] = None, configured=True):
    calls: List[tuple] = []
    daas_calls: List[tuple] = []

    async def get_pool():
        return _Pool(handler or (lambda sql, args: []), calls)

    async def fake_user(request: Request):
        return {"user_id": "u1", "email": "u1@example.com"}

    async def get_raw(path, params=None, timeout=10.0):
        daas_calls.append((path, params))
        r = daas(path, params) if callable(daas) else daas
        if isinstance(r, Exception):
            raise r
        return copy.deepcopy(r)

    async def denied(request):
        return model_denied

    monkeypatch.setattr(route.pg_client, "get_pool", get_pool)
    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(route.daas_client, "get_raw", get_raw)
    monkeypatch.setattr(route.daas_client, "is_configured", lambda: configured)
    monkeypatch.setattr(route, "_move_odds_denied", denied)
    route._snapshot_cache.update(at=float("-inf"), body=None)
    route._model_cache.clear()
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), calls, daas_calls


# ── watchlist: thresholds from the config, gap gate, rules and versions ───────

def _bars(n=40, last=date(2026, 10, 13), last_open=None):
    """close_i = 90 + 0.25 i; volume 1e6 except the last three at 5e6 (3-day spike 5e6 / 20-day 1.6e6 = 3.1×)."""
    out = []
    for i in range(n):
        close = 90 + 0.25 * i
        out.append({"nse_symbol": "AAA", "bar_date": last - timedelta(days=n - 1 - i), "open": close,
                    "high": close + 0.1, "low": close - 0.1, "close": close,
                    "volume": 5_000_000 if i >= n - 3 else 1_000_000, "delivery_qty": None, "delivery_pct": None})
    if last_open is not None:
        out[-1]["open"] = last_open
        out[-1]["high"] = max(last_open, out[-1]["close"]) + 0.1
    return out


def _candidate(**over):
    c = {"nse_symbol": "AAA", "stage": "BREAKOUT", "confidence": "HIGH", "final_score": 0.9,
         "close_price": 99.75, "sma_50": 95.0, "sma_200": 90.0, "rsi_14": 62.0, "atr_14": 2.0,
         "breakout_level": 99.0, "support_level": 96.5, "resistance_level": 99.0, "sector": "IT",
         "engine_version": "positional.v1.0"}
    c.update(over)
    return c


def _watch(bars, cand=None):
    def handler(sql, args):
        if "MAX(as_of_date)" in sql:
            return [{"d": date(2026, 10, 13)}]
        if "FROM stock_technical_features stf" in sql:
            return [cand or _candidate()]
        if "FROM stock_ohlcv" in sql:
            return bars
        raise AssertionError(sql)
    return handler


def _bucket_of(d):
    for name, rows in d["buckets"].items():
        if rows:
            return name
    return None


def test_watchlist_sends_the_rules_with_their_version_and_the_engine_version(monkeypatch):
    c, calls, _ = _client(monkeypatch, handler=_watch(_bars()))
    d = c.get("/api/positional/watchlist").json()
    assert d["rules"]["version"] == rules.RULES_VERSION
    assert d["rules"]["watchlist"]["breakout_confirmed"] == rules.WATCHLIST["breakout_confirmed"]
    assert d["rules"]["liquidity"]["min_traded_value_cr"] == 10.0 and d["rules"]["liquidity"]["sessions"] == 20
    assert (d["rules"]["risk_bands"]["low_below_pct"], d["rules"]["risk_bands"]["high_above_pct"]) == (2.0, 4.0)
    assert d["_classifier_version"] == "smart_v2"
    assert d["engine_versions"] == ["positional.v1.0"]
    # The candidate filter's numbers are sent as parameters from the config, not written into the SQL.
    sql, args = next(c for c in calls if "FROM stock_technical_features stf" in c[0])
    assert args[1:] == (["WEAK", "EXTENDED"], 5.0, 80)
    assert "LIMIT 80" not in sql and "> 5" not in sql


def test_a_config_threshold_moves_a_stock_between_buckets(monkeypatch):
    c, _, _ = _client(monkeypatch, handler=_watch(_bars()))
    assert _bucket_of(c.get("/api/positional/watchlist").json()) == "breakout_confirmed"
    # Volume spike is 3.1×: demanding 4× in the config sends the stock down the precedence list.
    monkeypatch.setitem(rules.WATCHLIST, "breakout_confirmed", {**rules.WATCHLIST["breakout_confirmed"], "volume_spike_min": 4.0})
    d = c.get("/api/positional/watchlist").json()
    assert d["buckets"]["breakout_confirmed"] == []
    assert d["rules"]["watchlist"]["breakout_confirmed"]["volume_spike_min"] == 4.0


def test_gap_gate_a_breakout_made_on_a_gap_is_not_confirmed(monkeypatch):
    prev_close = 90 + 0.25 * 38                                     # 99.50
    over = round(prev_close * 1.0551, 3)                            # +5.51 %
    c, _, _ = _client(monkeypatch, handler=_watch(_bars(last_open=over)))
    d = c.get("/api/positional/watchlist").json()
    assert d["buckets"]["breakout_confirmed"] == []
    under = 104.47                                                  # +4.995 %: passes
    c, _, _ = _client(monkeypatch, handler=_watch(_bars(last_open=under)))
    d = c.get("/api/positional/watchlist").json()
    row = d["buckets"]["breakout_confirmed"][0]
    assert row["signals"]["gap_up_pct"] == pytest.approx(4.99, abs=0.01)
    # The limit itself passes (rule: gap ≤ max_gap_up_pct).
    base = dict(stage="BREAKOUT", close=99.75, sma50=95.0, ema20=97.0, dist_breakout_pct=0.76, dist_ema20_pct=2.8,
                volume_spike=3.1, volume_slope=1.0, range_15d=4.0, higher_lows=1, upper_wick=0.1)
    assert rules.classify_setup(**base, gap_pct=5.0) == "breakout_confirmed"
    assert rules.classify_setup(**base, gap_pct=5.01) != "breakout_confirmed"
    assert rules.classify_setup(**base, gap_pct=None) == "breakout_confirmed"   # no open on record: not a gap


def test_picks_send_the_rules_version_and_engine_versions(monkeypatch):
    def handler(sql, args):
        if "MAX(signal_date)" in sql:
            return [{"d": DAY}]
        if "FROM positional_signals ps" in sql:
            assert "ps.engine_version" in sql
            return [{"nse_symbol": "AAA", "signal_date": DAY, "final_score": 0.8, "engine_version": "positional.v1.0",
                     "pre_breakout": None, "features_raw": None}]
        if "FROM stock_ohlcv" in sql:
            return []
        raise AssertionError(sql)
    c, _, _ = _client(monkeypatch, handler=handler)
    d = c.get("/api/positional/picks").json()
    assert d["rules_version"] == rules.RULES_VERSION and d["engine_versions"] == ["positional.v1.0"]


# ── universe rules (pure) ────────────────────────────────────────────────────

def _row(sym, **over):
    """An eligible, liquid, EQ stock in no category unless `over` puts it in one."""
    r = {"symbol": sym, "close": 100.0, "prev_close": 99.0, "traded_value_cr_20d": 25.0, "has_reference": True,
         "series": "EQ", "is_etf": False, "price_band_pct": 20.0, "fno_eligible": False, "atr_pct": 3.0,
         "return_20d_pct": 1.0, "sma50": 95.0, "sma50_slope": 0.1, "vol_z20": 0.2, "return_5d_pct": 0.5,
         "last_results_date": None}
    r.update(over)
    return r


def test_each_excluded_stock_is_counted_once_under_its_first_failing_gate():
    rows = [
        _row("OK1"),
        _row("NOPX", close=None),                                   # missing_price
        _row("NOTV", traded_value_cr_20d=None, series="SM"),        # no_traded_value (first), not series
        _row("NOREF", has_reference=False),                         # no_reference
        _row("SME", series="SM"),                                   # series
        _row("ETF1", is_etf=True),                                  # etf
        _row("BAND5", price_band_pct=5.0, traded_value_cr_20d=1.0), # price_band (before illiquid)
        _row("CAPPED", prev_close=100.0, close=119.95),             # at_band_limit: +19.95 % on a 20 % band
        _row("THIN", traded_value_cr_20d=9.99),                     # illiquid
        _row("EDGE", traded_value_cr_20d=10.0),                     # exactly ₹10 Cr: eligible
        _row("FNO", price_band_pct=None, fno_eligible=True),        # F&O stocks carry no band: eligible
    ]
    ev = rules.evaluate(rows, DAY)
    ex = ev["universe"]["excluded"]
    assert ex == {"missing_price": 1, "no_traded_value": 1, "no_reference": 1, "series": 1, "etf": 1,
                  "price_band": 1, "at_band_limit": 1, "illiquid": 1}
    assert ev["universe"]["total"] == 11 and ev["universe"]["eligible"] == 3
    assert ev["universe"]["total"] - ev["universe"]["eligible"] == sum(ex.values())
    assert ev["rows"]["NOTV"]["exclusion"] == "no_traded_value"
    assert ev["rows"]["EDGE"]["eligible"] and ev["rows"]["FNO"]["eligible"]
    assert ev["universe"]["fno_eligible"] == 1


def test_momentum_rule_and_missing_figures_are_never_neutral():
    rows = [
        _row("EXACT", return_20d_pct=5.0),                          # 5.0 passes
        _row("LOW", return_20d_pct=4.99),
        _row("BELOW50", return_20d_pct=12.0, close=94.0, prev_close=93.0),
        _row("FLAT50", return_20d_pct=12.0, sma50_slope=0.0),       # slope must be above 0
        _row("BEST", return_20d_pct=18.0),
        _row("NOR20", return_20d_pct=None),                         # missing → not in, counted missing
        _row("NOSMA", return_20d_pct=20.0, sma50=None),
    ]
    ev = rules.evaluate(rows, DAY)
    m = ev["categories"]["momentum"]
    assert m["symbols"] == ["BEST", "EXACT"]                        # ordered by 20-day return
    assert m["total"] == 2 and m["missing"] == 2 and m["rank_by"] == "return_20d_pct"
    assert "momentum" not in ev["rows"]["NOSMA"]["categories"]


def test_unusual_volume_threshold_is_inclusive():
    ev = rules.evaluate([_row("Z2", vol_z20=2.0), _row("Z199", vol_z20=1.99), _row("Z5", vol_z20=5.1),
                         _row("ZNONE", vol_z20=None)], DAY)
    u = ev["categories"]["unusual_volume"]
    assert u["symbols"] == ["Z5", "Z2"] and u["missing"] == 1


def test_results_day_momentum_window_and_thresholds():
    win = rules.CATEGORIES["results_day"]["window_calendar_days"]
    rows = [
        _row("TODAY", last_results_date=DAY.isoformat(), return_5d_pct=4.0, vol_z20=1.5),
        _row("EDGE", last_results_date=(DAY - timedelta(days=win - 1)).isoformat(), return_5d_pct=3.0, vol_z20=1.0),
        _row("OLD", last_results_date=(DAY - timedelta(days=win)).isoformat(), return_5d_pct=9.0, vol_z20=3.0),
        _row("FUTURE", last_results_date=(DAY + timedelta(days=1)).isoformat(), return_5d_pct=9.0, vol_z20=3.0),
        _row("WEAK", last_results_date=DAY.isoformat(), return_5d_pct=2.9, vol_z20=3.0),
        _row("NOVOL", last_results_date=DAY.isoformat(), return_5d_pct=6.0, vol_z20=None),
        _row("NORESULTS", return_5d_pct=None, vol_z20=None),         # no results: not counted as missing
    ]
    ev = rules.evaluate(rows, DAY)
    r = ev["categories"]["results_day"]
    assert r["symbols"] == ["TODAY", "EDGE"] and r["missing"] == 1
    assert rules.results_window(DAY) == {"from": (DAY - timedelta(days=win - 1)).isoformat(), "to": DAY.isoformat()}


def test_fno_candidates_need_eligibility_and_another_category_or_a_setup():
    rows = [
        _row("FMOM", fno_eligible=True, price_band_pct=None, return_20d_pct=9.0),
        _row("FSETUP", fno_eligible=True, price_band_pct=None),
        _row("FIDLE", fno_eligible=True, price_band_pct=None),
        _row("CASHMOM", return_20d_pct=9.0),
    ]
    ev = rules.evaluate(rows, DAY, setup_symbols=["fsetup"])
    assert sorted(ev["categories"]["fno"]["symbols"]) == ["FMOM", "FSETUP"]
    assert "fno" not in ev["rows"]["FIDLE"]["categories"] and "fno" not in ev["rows"]["CASHMOM"]["categories"]


def test_categories_hold_only_eligible_stocks_and_are_capped(monkeypatch):
    monkeypatch.setattr(rules, "MAX_ROWS_PER_CATEGORY", 2)
    rows = [_row(f"M{i}", return_20d_pct=6.0 + i) for i in range(4)] + [_row("THINMOM", return_20d_pct=30.0, traded_value_cr_20d=2.0)]
    ev = rules.evaluate(rows, DAY)
    m = ev["categories"]["momentum"]
    assert m["total"] == 4 and m["shown"] == 2 and m["symbols"] == ["M3", "M2"]
    assert ev["rows"]["THINMOM"]["categories"] == []


def test_risk_and_liquidity_classes_use_the_configured_bands():
    assert [rules.risk_class(v) for v in (1.99, 2.0, 4.0, 4.01, None)] == ["low", "medium", "medium", "high", None]
    assert [rules.liquidity_class(v) for v in (9.99, 10.0, None)] == ["thin", "liquid", None]


def test_rank_percentile_worked_example():
    assert rules.rank_percentiles({"A": 0.30, "B": 0.20, "C": 0.20, "D": 0.10, "E": None}) == {
        "A": 100.0, "B": 50.0, "C": 50.0, "D": 0.0, "E": None}
    assert rules.rank_percentiles({"ONLY": 0.4}) == {"ONLY": None}


# ── GET /api/positional/scan-universe ────────────────────────────────────────

SNAP = {"as_of": "2026-10-12", "reference_as_of": "2026-10-12", "sessions": 20, "source": "fixture snapshot",
        "count": 6, "rows": [
            _row("MOMO", return_20d_pct=9.0, fno_eligible=True, price_band_pct=None),
            _row("VOLY", vol_z20=3.0, atr_pct=1.5),
            _row("PLAIN"),
            _row("THIN", traded_value_cr_20d=3.0, return_20d_pct=20.0),
            _row("SETUP1", atr_pct=4.5),
            _row("WATCH1"),
        ]}


def _latest(head, rows):
    return 200, {"data": {"status": "final", "head": head, "expected_session": "2026-10-13",
                          "run": {"model": "v4", "refit": "monthly", "data_as_of": "2026-10-12", "target_session": "2026-10-13",
                                  "universe_size": 1000, "scored": 994, "train_end": "2026-08-31"},
                          "rows": rows}}


def _daas(model_rows=None):
    model_rows = model_rows if model_rows is not None else {
        "p_up5_1d": [{"symbol": "MOMO", "p": 0.30}, {"symbol": "VOLY", "p": 0.20}, {"symbol": "PLAIN", "p": 0.20},
                     {"symbol": "SETUP1", "p": 0.10}, {"symbol": "THIN", "p": 0.90}],
        "p_up10_1d": [{"symbol": "MOMO", "p": 0.05}],
    }

    def reply(path, params):
        if path == "/features/scan-snapshot":
            return 200, SNAP
        if path == "/move-odds/latest":
            return _latest(params["head"], model_rows[params["head"]])
        raise AssertionError(path)
    return reply


def test_scan_universe_categories_exclusions_and_rows(monkeypatch):
    c, _, daas_calls = _client(monkeypatch, daas=_daas())
    r = c.get("/api/positional/scan-universe", params={"setups": "setup1", "symbols": "WATCH1,NOPE"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["as_of"] == "2026-10-12" and d["mode"] == "eod" and d["source"] == "fixture snapshot"
    assert d["rules"]["version"] == rules.RULES_VERSION
    assert d["universe"] == {"total": 6, "eligible": 5, "fno_eligible": 1,
                             "excluded": {**{k: 0 for k in rules.UNIVERSE["exclusion_order"]}, "illiquid": 1}}
    assert d["categories"]["momentum"]["symbols"] == ["MOMO"]           # THIN is not eligible
    assert d["categories"]["unusual_volume"]["symbols"] == ["VOLY"]
    assert d["categories"]["fno"]["symbols"] == ["MOMO"]
    by = {row["symbol"]: row for row in d["rows"]}
    assert set(by) == {"MOMO", "VOLY", "SETUP1", "WATCH1"}                # categories + asked-for, nothing else
    assert d["not_found"] == ["NOPE"]
    assert by["SETUP1"]["risk_class"] == "high" and by["VOLY"]["risk_class"] == "low"
    assert by["MOMO"]["liquidity_class"] == "liquid" and by["MOMO"]["categories"] == ["momentum", "fno"]
    # The snapshot is read once and cached for the next request.
    c.get("/api/positional/scan-universe")
    assert [p for p, _ in daas_calls].count("/features/scan-snapshot") == 1


def test_model_rank_is_a_percentile_within_the_eligible_universe(monkeypatch):
    c, _, _ = _client(monkeypatch, daas=_daas())
    d = c.get("/api/positional/scan-universe", params={"setups": "SETUP1", "symbols": "PLAIN,THIN"}).json()
    by = {row["symbol"]: row for row in d["rows"]}
    # Eligible and scored: MOMO 0.30, VOLY 0.20, PLAIN 0.20, SETUP1 0.10 (THIN's 0.90 is not eligible, so not counted)
    assert by["MOMO"]["model_rank_pct"]["p_up5_1d"] == 100.0
    assert by["VOLY"]["model_rank_pct"]["p_up5_1d"] == 50.0 and by["PLAIN"]["model_rank_pct"]["p_up5_1d"] == 50.0
    assert by["SETUP1"]["model_rank_pct"]["p_up5_1d"] == 0.0
    assert by["THIN"]["model_rank_pct"]["p_up5_1d"] is None
    assert by["MOMO"]["model_rank_pct"]["p_up10_1d"] is None             # alone in its head: no rank
    m = d["model"]
    assert m["status"] == "final" and m["heads"]["p_up5_1d"]["ranked_eligible"] == 4
    assert m["heads"]["p_up5_1d"]["run"]["model"] == "v4" and "p" not in m["heads"]["p_up5_1d"]
    assert "p" not in by["MOMO"] and "probability" not in by["MOMO"]    # no probability is sent here


def test_model_rank_without_access_or_publication(monkeypatch):
    c, _, daas_calls = _client(monkeypatch, daas=_daas(), model_denied="no_access")
    d = c.get("/api/positional/scan-universe").json()
    assert d["model"]["status"] == "no_access" and d["model"]["heads"] == {}
    assert all(v is None for row in d["rows"] for v in row["model_rank_pct"].values())
    assert "/move-odds/latest" not in [p for p, _ in daas_calls]

    def pending(path, params):
        if path == "/features/scan-snapshot":
            return 200, SNAP
        return 200, {"data": {"status": "not_published", "expected_session": "2026-10-13", "rows": []}}
    c, _, _ = _client(monkeypatch, daas=pending)
    d = c.get("/api/positional/scan-universe").json()
    assert d["model"]["status"] == "not_published" and "2026-10-13" in d["model"]["reason"]
    assert all(v is None for row in d["rows"] for v in row["model_rank_pct"].values())


@pytest.mark.parametrize("reply", [(500, {"error": "boom"}), (200, {"rows": "nope", "as_of": "2026-10-12"}),
                                   (200, {"as_of": None, "rows": []})])
def test_a_failing_data_platform_is_502_never_an_empty_universe(monkeypatch, reply):
    c, _, _ = _client(monkeypatch, daas=lambda p, q: reply)
    r = c.get("/api/positional/scan-universe")
    assert r.status_code == 502 and r.json()["detail"] == "upstream_unavailable"


def test_unreachable_or_unconfigured_data_platform_is_502(monkeypatch):
    c, _, _ = _client(monkeypatch, daas=lambda p, q: route.daas_client.DaasError("timeout"))
    assert c.get("/api/positional/scan-universe").status_code == 502
    c, _, calls = _client(monkeypatch, daas=_daas(), configured=False)
    assert c.get("/api/positional/scan-universe").status_code == 502 and calls == []


@pytest.mark.parametrize("qs", [{"symbols": "BAD SYMBOL"}, {"setups": "A;B"},
                                {"symbols": ",".join(f"S{i}" for i in range(151))}])
def test_bad_symbol_lists_are_422(monkeypatch, qs):
    c, _, calls = _client(monkeypatch, daas=_daas())
    assert c.get("/api/positional/scan-universe", params=qs).status_code == 422 and calls == []


def test_scan_universe_needs_a_signed_in_user(monkeypatch):
    c, _, _ = _client(monkeypatch, daas=_daas())

    async def no_user(request: Request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    monkeypatch.setattr(route, "get_current_user", no_user)
    assert c.get("/api/positional/scan-universe").status_code == 401
