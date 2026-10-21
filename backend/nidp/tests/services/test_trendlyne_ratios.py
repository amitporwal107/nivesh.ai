"""ROE, ROCE, debt-to-equity, P/B and market cap from the Trendlyne MCP server (pass "r1").

No network, no database. The two fixtures are real replies captured read-only on 2026-10-14
(company symbols and published figures; no URL). The provider is replaced by an httpx mock
transport and the warehouse by an in-memory stand-in that answers the service's own SQL.
"""
import asyncio
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from nidp.services.trendlyne_fundamentals import parse, service
from nidp.services.trendlyne_fundamentals.client import READ_TOOLS, TrendlyneClient, TrendlyneError

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "trendlyne"
MIGRATIONS = Path(__file__).resolve().parent.parent.parent / "migrations"
SECRET_URL = "https://provider.invalid/mcp?token=s3cr3t-token-value"

# Labels exactly as the provider answered in the pilot. They differ from the names its
# parameter search shows ("ROE Annual %", "Market Capitalization").
LABELS = {"roea": "ROE Ann. %", "rocea": "ROCE Ann. %", "debtcea": "Total Debt to Total Equity Ann.",
          "pbva": "PBV Adjusted", "mcapq": "Market Cap", "currentprice": "LTP"}


def _fixture(name: str) -> str:
    return json.loads((FIXTURES / name).read_text())["text"]


def _by_parameter(blocks: dict, symbol: str) -> dict:
    return {parameter: blocks[label].get(symbol) for parameter, label in LABELS.items() if label in blocks}


# ── the pass ─────────────────────────────────────────────────────────────────

def test_the_ratio_pass_asks_for_the_five_figures_and_the_price_in_one_call():
    assert parse.PASSES["r1"] == ["roea", "rocea", "debtcea", "pbva", "mcapq", "currentprice"]
    assert len(parse.PASSES["r1"]) <= 10
    everything = [t for tokens in parse.PASSES.values() for t in tokens]
    assert len(set(everything)) == len(everything)             # market cap is not also paid for in p3


def test_the_daily_order_runs_the_ratio_pass_first_and_leaves_no_pass_out():
    assert parse.DAILY_ORDER[0] == "r1"
    assert sorted(parse.DAILY_ORDER) == sorted(parse.PASSES)


def test_units_and_bases_of_the_five_figures():
    got = {m.column: (m.parameter, m.unit, m.period_basis) for m in parse.RATIO_METRICS}
    assert got == {
        "roe_pct": ("roea", "percent", "annual"),
        "roce_pct": ("rocea", "percent", "annual"),
        "debt_to_equity": ("debtcea", "ratio", "annual"),
        "pb": ("pbva", "ratio", "point_in_time"),
        "market_cap_cr": ("mcapq", "inr_crore", "point_in_time"),
    }


# ── the real reply ───────────────────────────────────────────────────────────

def test_the_real_reply_is_read_by_field_name():
    stocks, blocks = parse.parse_parameter_values(_fixture("parameter_values_ratios.json"))
    assert stocks["RELIANCE"] == date(2026, 10, 13) and len(stocks) == 10
    # the reply's blocks are not in the order the parameters were asked for
    assert list(blocks)[:3] == ["Total Debt to Total Equity Ann.", "PBV Adjusted", "ROCE Ann. %"]
    assert _by_parameter(blocks, "TCS") == {"roea": 45.88, "rocea": 58.65, "debtcea": 0.0, "pbva": 6.37,
                                           "mcapq": 768843.59, "currentprice": 2125.0}
    assert _by_parameter(blocks, "SWARAJENG")["mcapq"] == 4542.12


def test_units_seen_in_the_real_reply():
    """Market cap is in rupees crore, P/B is a plain ratio, ROE is a percentage (not a fraction)."""
    _, blocks = parse.parse_parameter_values(_fixture("parameter_values_ratios_crosscheck.json"))
    for symbol in ("RELIANCE", "TCS", "HDFCBANK", "DMART", "SWARAJENG"):
        price, book = blocks["LTP"][symbol], blocks["BVSH Latest"][symbol]
        assert blocks["PBV Adjusted"][symbol] == pytest.approx(price / book, abs=0.006)
    # crore: Reliance's market cap over its price is about 1,353 crore shares
    assert blocks["Market Cap"]["RELIANCE"] / blocks["LTP"]["RELIANCE"] == pytest.approx(1353.25, abs=0.01)
    assert 1 < blocks["ROE Ann. %"]["RELIANCE"] < 100


def test_a_figure_the_provider_does_not_give_stays_null_never_zero():
    stocks, blocks = parse.parse_parameter_values(_fixture("parameter_values_ratios.json"))
    etf = _by_parameter(blocks, "NIFTYBEES")
    assert etf == {"roea": None, "rocea": None, "debtcea": None, "pbva": None, "mcapq": None, "currentprice": 254.66}
    # nothing to say about an ETF: no rows at all, so it never looks like "ROE 0%"
    assert parse.build_ratio_rows(etf, LABELS, stocks["NIFTYBEES"], date(2026, 10, 12)) == []
    # a real zero stays a zero: TCS has no borrowings
    tcs = {r["metric"]: r for r in parse.build_ratio_rows(
        _by_parameter(blocks, "TCS"), LABELS, stocks["TCS"], date(2026, 10, 12))}
    assert tcs["debt_to_equity"]["value"] == 0.0 and tcs["debt_to_equity"]["usable"] is True


def test_one_missing_figure_does_not_blank_or_zero_the_others():
    values = {"roea": 12.5, "rocea": None, "debtcea": 0.3, "pbva": 2.0, "mcapq": 5000.0, "currentprice": 100.0}
    rows = {r["metric"]: r for r in parse.build_ratio_rows(values, LABELS, date(2026, 10, 13), date(2026, 10, 12))}
    assert rows["roce_pct"]["value"] is None and rows["roe_pct"]["value"] == 12.5


def test_rows_carry_the_providers_field_name_basis_and_dates():
    stocks, blocks = parse.parse_parameter_values(_fixture("parameter_values_ratios.json"))
    rows = {r["metric"]: r for r in parse.build_ratio_rows(
        _by_parameter(blocks, "RELIANCE"), LABELS, stocks["RELIANCE"], date(2026, 10, 12))}
    assert set(rows) == {"roe_pct", "roce_pct", "debt_to_equity", "pb", "market_cap_cr"}
    roe, cap = rows["roe_pct"], rows["market_cap_cr"]
    assert (roe["provider_field"], roe["provider_parameter"], roe["unit"], roe["period_basis"]) == \
        ("ROE Ann. %", "roea", "percent", "annual")
    assert (cap["provider_field"], cap["unit"], cap["period_basis"], cap["value"]) == \
        ("Market Cap", "inr_crore", "point_in_time", 1568285.91)
    # the provider states no fiscal-year end for an annual figure, so none is invented
    assert all(r["period_end"] is None for r in rows.values())
    # dated by the session whose close the provider used, with the provider's own stamp kept beside it
    assert all(r["as_of_date"] == date(2026, 10, 12) and r["provider_date"] == date(2026, 10, 13) for r in rows.values())
    assert all(r["flags"] == [] and r["usable"] for r in rows.values())


# ── which session the price-based figures belong to ──────────────────────────

CLOSES = {date(2026, 10, 9): 2156.0, date(2026, 10, 12): 2125.0, date(2026, 10, 13): 2269.3}


def test_price_session_is_the_day_whose_close_the_provider_used():
    # seen in the pilot: the reply was stamped 13 Oct but its LTP was the 12 Oct close
    assert parse.price_session(2125.0, date(2026, 10, 13), CLOSES) == date(2026, 10, 12)
    assert parse.price_session(2269.3, date(2026, 10, 13), CLOSES) == date(2026, 10, 13)


def test_price_session_is_never_after_the_stamp_and_none_when_nothing_matches():
    assert parse.price_session(2269.3, date(2026, 10, 12), CLOSES) is None
    assert parse.price_session(1999.0, date(2026, 10, 13), CLOSES) is None
    assert parse.price_session(None, date(2026, 10, 13), CLOSES) is None
    assert parse.price_session(2125.0, date(2026, 10, 13), {}) is None


def test_price_session_takes_the_latest_day_when_a_price_repeats():
    flat = {date(2026, 10, 9): 10.0, date(2026, 10, 12): 10.0}
    assert parse.price_session(10.0, date(2026, 10, 13), flat) == date(2026, 10, 12)


def test_an_unconfirmed_price_date_falls_back_to_the_stamp_and_says_so():
    values = {"roea": 10.0, "rocea": 12.0, "debtcea": 0.1, "pbva": 2.0, "mcapq": 900.0, "currentprice": 55.0}
    rows = {r["metric"]: r for r in parse.build_ratio_rows(values, LABELS, date(2026, 10, 13), None)}
    assert all(r["as_of_date"] == date(2026, 10, 13) for r in rows.values())
    assert rows["pb"]["flags"] == ["price_date_unconfirmed"] and rows["market_cap_cr"]["flags"] == ["price_date_unconfirmed"]
    assert rows["roe_pct"]["flags"] == []                       # an annual figure does not move with price
    assert rows["pb"]["usable"] and rows["market_cap_cr"]["usable"]   # the value is kept; only its date is unproven


# ── sanity ranges: flagged, never silently dropped ───────────────────────────

def test_negative_book_value_is_flagged_and_kept_out_of_the_feature_row():
    """Vodafone Idea, real figures: net worth is negative, so P/B, D/E and ROE come out negative
    (ROE -96.62% in a year the provider shows a profit). The values are stored as given."""
    stocks, blocks = parse.parse_parameter_values(_fixture("parameter_values_ratios_crosscheck.json"))
    rows = {r["metric"]: r for r in parse.build_ratio_rows(
        _by_parameter(blocks, "IDEA"), LABELS, stocks["IDEA"], date(2026, 10, 12))}
    assert (rows["pb"]["value"], rows["debt_to_equity"]["value"], rows["roe_pct"]["value"]) == (-3.47, -4.18, -96.62)
    for metric in ("pb", "debt_to_equity", "roe_pct"):
        assert rows[metric]["flags"] == ["negative_book_value"] and rows[metric]["usable"] is False
    assert rows["market_cap_cr"]["usable"] and rows["market_cap_cr"]["value"] == 137270.63
    assert rows["roce_pct"]["usable"] and rows["roce_pct"]["flags"] == []


def test_roe_beyond_200_percent_is_flagged_but_kept():
    for roe in (250.0, -310.5):
        values = {"roea": roe, "rocea": 20.0, "debtcea": 0.2, "pbva": 30.0, "mcapq": 800.0, "currentprice": 10.0}
        row = {r["metric"]: r for r in parse.build_ratio_rows(values, LABELS, date(2026, 10, 13), date(2026, 10, 13))}["roe_pct"]
        assert row["flags"] == ["roe_beyond_200"] and row["usable"] is True and row["value"] == roe
    inside = {"roea": 200.0, "rocea": 20.0, "debtcea": 0.2, "pbva": 3.0, "mcapq": 800.0, "currentprice": 10.0}
    assert parse.build_ratio_rows(inside, LABELS, date(2026, 10, 13), date(2026, 10, 13))[0]["flags"] == []


def test_market_cap_of_zero_is_flagged_and_unusable_but_stored():
    values = {"roea": 5.0, "rocea": 6.0, "debtcea": 0.2, "pbva": 1.1, "mcapq": 0.0, "currentprice": 10.0}
    cap = {r["metric"]: r for r in parse.build_ratio_rows(values, LABELS, date(2026, 10, 13), date(2026, 10, 13))}["market_cap_cr"]
    assert cap["value"] == 0.0 and cap["flags"] == ["market_cap_zero"] and cap["usable"] is False


def test_a_figure_too_large_for_its_column_is_flagged_and_unusable():
    values = {"roea": 2_500_000.0, "rocea": 6.0, "debtcea": 0.2, "pbva": 1.1, "mcapq": 10.0, "currentprice": 10.0}
    roe = {r["metric"]: r for r in parse.build_ratio_rows(values, LABELS, date(2026, 10, 13), date(2026, 10, 13))}["roe_pct"]
    assert "implausible_magnitude" in roe["flags"] and roe["usable"] is False


# ── an unknown code fails the whole call ─────────────────────────────────────

def test_unresolved_codes_are_read_from_the_error_reply():
    real = '{"status": "error", "message": "Could not resolve stock code(s): ZZNOTREAL. [code:1012]"}'
    assert parse.unresolved_codes(real) == ["ZZNOTREAL"]
    two = '{"status": "error", "message": "Could not resolve stock code(s): M&M-X, BAJAJ-ZZ. [code:1012]"}'
    assert parse.unresolved_codes(two) == ["M&M-X", "BAJAJ-ZZ"]
    assert parse.unresolved_codes(_fixture("parameter_values_ratios.json")) == []
    assert parse.unresolved_codes('{"status": "error", "message": "rate limited"}') == []
    assert parse.unresolved_codes("not json") == []


# ── stand-ins for the provider and the warehouse ─────────────────────────────

class Provider:
    """Answers get_stock_parameter_values in the shape seen in the pilot: a header line per
    stock, one block per parameter under the provider's label, blocks NOT in request order,
    and an error for the whole call when any code is unknown."""

    def __init__(self, values=None, stamp="2026-10-13", unknown=(), status=200, raise_error=None):
        self.values, self.stamp, self.unknown = values or {}, stamp, set(unknown)
        self.status, self.raise_error = status, raise_error
        self.tool_calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        self.tool_calls.append((body["params"]["name"], body["params"]["arguments"]))
        if self.raise_error:
            raise self.raise_error(f"cannot reach {request.url}", request=request)
        if self.status != 200:
            return httpx.Response(self.status, text=f"error at {request.url}")
        codes, parameters = body["params"]["arguments"]["stock_codes"], body["params"]["arguments"]["parameters"]
        bad = [c for c in codes if c in self.unknown]
        if bad:
            text = json.dumps({"status": "error",
                               "message": f"Could not resolve stock code(s): {', '.join(bad)}. [code:1012]"})
        else:
            header = "\n".join(f"{n}|{c} Ltd|{c}|5{n:05d}|{self.stamp}" for n, c in enumerate(codes, 1))
            blocks = [LABELS[p] + "\n" + "\n".join(f"{c}:{self._cell(c, p)}" for c in codes)
                      for p in reversed(parameters)]
            text = json.dumps({"status": "success", "data": header + "\n\n" + "\n\n---\n\n".join(blocks) + "\n\n---"})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                         "result": {"content": [{"type": "text", "text": text}], "isError": False}})

    def _cell(self, code: str, parameter: str) -> str:
        value = self.values.get(code, DEFAULT_VALUES).get(parameter)
        return "None" if value is None else f"{value:.2f}"


DEFAULT_VALUES = {"roea": 15.0, "rocea": 18.0, "debtcea": 0.25, "pbva": 3.0, "mcapq": 12000.0, "currentprice": 100.0}


class Warehouse:
    """The few statements the service runs, over dictionaries."""

    def __init__(self, universe, labels=None, calls_today=0):
        self.universe = list(universe)
        self.labels = dict(LABELS if labels is None else labels)
        self.calls_today = calls_today
        self.call_log = []
        self.staged = {}        # (symbol, parameter) -> {"value", "as_of_date", "fetched_at"}
        self.closes = []        # (symbol, as_of_date, close_price)
        self.verified_basis = {}
        self.fundamental_values = {}
        self.deleted_other_runs = False
        self.migrated = True    # migration 162 applied

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetchval(self, sql, *args, **kw):
        if "to_regclass('nidp.stock_fundamental_values')" in sql:
            return self.migrated
        assert "FROM nidp.trendlyne_call_log" in sql, sql
        return self.calls_today + len(self.call_log)

    async def fetch(self, sql, *args, **kw):
        if "FROM nidp.trendlyne_param_labels" in sql:
            return [{"parameter": p, "label": l} for p, l in self.labels.items() if p in args[0]]
        if "v_screener_backfill_universe" in sql:
            return [{"symbol": s} for s in self.universe]
        if "FROM nidp.trendlyne_param_values" in sql and "HAVING" in sql:
            parameters, days, need = args
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            fresh = {}
            for (symbol, parameter), row in self.staged.items():
                if parameter in parameters and row["fetched_at"] > cutoff:
                    fresh[symbol] = fresh.get(symbol, 0) + 1
            return [{"symbol": s} for s, n in fresh.items() if n == need]
        if "FROM nidp.trendlyne_param_values" in sql:
            return [{"symbol": s, "parameter": p, "value": r["value"], "as_of_date": r["as_of_date"],
                     "fetched_at": r["fetched_at"]} for (s, p), r in self.staged.items() if p in args[0]]
        if "FROM nidp.prices_eod" in sql:
            return [{"symbol": s, "as_of_date": d, "close_price": Decimal(str(c))} for s, d, c in self.closes]
        if "FROM nidp.nse_financials_quarterly" in sql:
            return [{"symbol": s, "consolidated": c} for s, c in self.verified_basis.items()]
        raise AssertionError(f"unexpected query: {sql}")

    async def execute(self, sql, *args, **kw):
        if "INSERT INTO nidp.trendlyne_param_labels" in sql:
            self.labels[args[0]] = args[1]
        elif "DELETE FROM nidp.stock_fundamental_values" in sql:
            self.deleted_other_runs = True
            assert args[0] == service.SOURCE
        else:
            raise AssertionError(f"unexpected statement: {sql}")

    async def executemany(self, sql, rows, **kw):
        if "INSERT INTO nidp.trendlyne_call_log" in sql:
            self.call_log.extend(rows)
        elif "INSERT INTO nidp.trendlyne_param_values" in sql:
            for symbol, parameter, value, as_of, _run in rows:
                self.staged[(symbol, parameter)] = {"value": value, "as_of_date": as_of,
                                                    "fetched_at": datetime.now(timezone.utc)}
        elif "INSERT INTO nidp.stock_fundamental_values" in sql:
            columns = [c.strip() for c in re.search(r"\(([^)]*)\)\s*VALUES", sql, re.S).group(1).split(",")]
            for row in rows:
                record = dict(zip(columns, row))
                self.fundamental_values[(record["symbol"], record["metric"], record["source"])] = record
        else:
            raise AssertionError(f"unexpected statement: {sql}")


@pytest.fixture
def wire(monkeypatch):
    """Point the service at a stand-in warehouse and provider."""
    def _wire(warehouse: Warehouse, provider: Provider, budget: int = 700):
        async def _pool():
            return warehouse
        monkeypatch.setattr(service, "get_pool", _pool)
        monkeypatch.setattr(service, "mcp_url", lambda: SECRET_URL)
        monkeypatch.setattr(service, "DELAY_S", 0)
        monkeypatch.setenv("TRENDLYNE_DAILY_CALL_BUDGET", str(budget))
        monkeypatch.setattr(service, "TrendlyneClient",
                            lambda url, **kw: TrendlyneClient(url, transport=httpx.MockTransport(provider), **kw))
        return warehouse, provider
    return _wire


SYMBOLS = [f"S{i:02d}" for i in range(35)]


# ── budget and resume ────────────────────────────────────────────────────────

def test_the_budget_is_respected_and_a_stopped_run_resumes_where_it_left_off(wire):
    warehouse, provider = wire(Warehouse(SYMBOLS), Provider(), budget=2)
    first = asyncio.run(service.fetch("r1"))
    assert first["calls"] == 2 and first["symbols_staged"] == 20 and "budget" in first["stopped"]
    assert len(provider.tool_calls) == 2 and len(warehouse.call_log) == 2
    assert {s for s, _ in warehouse.staged} == set(SYMBOLS[:20])

    # same day: the ledger says the budget is spent, so nothing is asked
    again = asyncio.run(service.fetch("r1"))
    assert again["calls"] == 0 and "budget" in again["stopped"] and len(provider.tool_calls) == 2

    # next day: only the 15 companies still missing are asked for
    warehouse.call_log.clear()
    second = asyncio.run(service.fetch("r1"))
    assert second["calls"] == 2 and second["symbols_staged"] == 15 and second["stopped"] is None
    asked = [c for _, arguments in provider.tool_calls[2:] for c in arguments["stock_codes"]]
    assert asked == SYMBOLS[20:]
    assert asyncio.run(service.fetch("r1"))["calls"] == 0        # complete: costs nothing


def test_calls_made_earlier_today_count_against_the_budget(wire):
    warehouse, provider = wire(Warehouse(SYMBOLS, calls_today=699), Provider(), budget=700)
    stats = asyncio.run(service.fetch("r1"))
    assert stats["calls"] == 1 and stats["symbols_staged"] == 10 and "budget" in stats["stopped"]


def test_a_full_pass_costs_one_call_per_ten_companies_plus_six_to_learn_the_labels(wire):
    warehouse, provider = wire(Warehouse(SYMBOLS, labels={}), Provider())
    stats = asyncio.run(service.fetch("r1"))
    assert stats["calls"] == 4 and stats["symbols_staged"] == 35             # ceil(35 / 10)
    assert len(provider.tool_calls) == 6 + 4 and len(warehouse.call_log) == 10
    assert warehouse.labels == LABELS
    assert all(len(arguments["stock_codes"]) <= 10 and len(arguments["parameters"]) <= 10
               for _, arguments in provider.tool_calls)


def test_staged_ratios_are_refreshed_weekly_not_monthly(wire, monkeypatch):
    warehouse, provider = wire(Warehouse(SYMBOLS[:10]), Provider())
    assert asyncio.run(service.fetch("r1"))["calls"] == 1
    for row in warehouse.staged.values():
        row["fetched_at"] -= timedelta(days=6)
    assert asyncio.run(service.fetch("r1"))["calls"] == 0
    for row in warehouse.staged.values():
        row["fetched_at"] -= timedelta(days=2)                   # now 8 days old
    assert asyncio.run(service.fetch("r1"))["calls"] == 1
    monkeypatch.setenv("TRENDLYNE_RATIOS_REFRESH_DAYS", "1")
    for row in warehouse.staged.values():
        row["fetched_at"] -= timedelta(days=2)
    assert asyncio.run(service.fetch("r1"))["calls"] == 1
    assert service.refresh_days("p1") == 30                      # the quarterly passes are unchanged


# ── what is staged ───────────────────────────────────────────────────────────

def test_fetch_stages_values_under_their_own_parameter_whatever_the_block_order(wire):
    values = {"S00": {"roea": 45.88, "rocea": 58.65, "debtcea": 0.0, "pbva": 6.37, "mcapq": 768843.59,
                      "currentprice": 2125.0},
              "S01": {"roea": None, "rocea": None, "debtcea": None, "pbva": None, "mcapq": None,
                      "currentprice": 254.66}}
    warehouse, _ = wire(Warehouse(["S00", "S01"]), Provider(values))
    asyncio.run(service.fetch("r1"))
    assert warehouse.staged[("S00", "roea")]["value"] == Decimal("45.88")
    assert warehouse.staged[("S00", "mcapq")]["value"] == Decimal("768843.59")
    assert warehouse.staged[("S00", "debtcea")]["value"] == Decimal("0.0")       # a real zero
    assert warehouse.staged[("S01", "roea")]["value"] is None                    # no value is NULL, not 0
    assert warehouse.staged[("S01", "currentprice")]["value"] == Decimal("254.66")
    assert warehouse.staged[("S00", "roea")]["as_of_date"] == date(2026, 10, 13)


def test_an_unknown_code_does_not_sink_its_batch_or_the_pass(wire):
    warehouse, provider = wire(Warehouse(SYMBOLS[:12]), Provider(unknown={"S03"}))
    stats = asyncio.run(service.fetch("r1"))
    assert stats["symbols_unknown_to_provider"] == 1 and stats["stopped"] is None
    assert stats["calls"] == 3                                   # the failed call, its retry, the second batch
    assert provider.tool_calls[1][1]["stock_codes"] == [s for s in SYMBOLS[:10] if s != "S03"]
    assert warehouse.staged[("S03", "roea")]["value"] is None    # staged empty, so it is not asked again tomorrow
    assert warehouse.staged[("S04", "roea")]["value"] == Decimal("15.0")
    assert asyncio.run(service.fetch("r1"))["calls"] == 0


# ── read-only, and no URL anywhere ───────────────────────────────────────────

def test_the_pass_only_ever_calls_the_read_tool(wire):
    warehouse, provider = wire(Warehouse(SYMBOLS, labels={}), Provider(unknown={"S07"}))
    asyncio.run(service.fetch("r1"))
    assert {name for name, _ in provider.tool_calls} == {"get_stock_parameter_values"}
    assert {tool for tool, _ok, _detail in warehouse.call_log} == {"get_stock_parameter_values"}


@pytest.mark.parametrize("tool", ["watchlist_add_stock", "watchlist_remove_stock", "watchlist_creation",
                                  "watchlist_listing", "watchlist_stocks"])
def test_no_watchlist_tool_of_the_server_can_be_called(tool):
    provider = Provider()
    client = TrendlyneClient(SECRET_URL, budget_left=5, transport=httpx.MockTransport(provider))
    with pytest.raises(TrendlyneError, match="allowlist"):
        client.call(tool, {"stock_id": 1, "watchlist_id": 1})
    assert provider.tool_calls == [] and tool not in READ_TOOLS


@pytest.mark.parametrize("provider", [Provider(status=500), Provider(status=403),
                                      Provider(raise_error=httpx.ConnectError),
                                      Provider(raise_error=httpx.ReadTimeout)])
def test_nothing_with_the_url_appears_in_an_error_or_in_the_ledger(wire, provider):
    warehouse, _ = wire(Warehouse(SYMBOLS[:10]), provider)
    with pytest.raises(TrendlyneError) as raised:
        asyncio.run(service.fetch("r1"))
    for text in [str(raised.value), repr(raised.value)] + [str(row) for row in warehouse.call_log]:
        assert "s3cr3t" not in text and "provider.invalid" not in text and "token=" not in text
    # the transport's own exception (its text can carry the URL) is not chained to ours
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None or raised.value.__suppress_context__
    assert len(warehouse.call_log) == 1 and warehouse.call_log[0][1] is False     # the failed call is still counted


def test_a_reply_that_is_not_the_expected_shape_is_refused_without_the_url(wire):
    class Garbage(Provider):
        def __call__(self, request):
            body = json.loads(request.content)
            if body["method"] == "initialize":
                return super().__call__(request)
            self.tool_calls.append((body["params"]["name"], body["params"]["arguments"]))
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {
                "content": [{"type": "text", "text": f"<html>see {request.url}</html>"}]}})
    warehouse, _ = wire(Warehouse(SYMBOLS[:10]), Garbage())
    with pytest.raises(TrendlyneError) as raised:
        asyncio.run(service.fetch("r1"))
    assert "s3cr3t" not in str(raised.value) and "provider.invalid" not in str(raised.value)
    assert warehouse.staged == {}


# ── build: staged values -> rows that say where they came from ───────────────

def _stage(warehouse, symbol, values, stamp=date(2026, 10, 13), fetched_at=None):
    for parameter, value in values.items():
        warehouse.staged[(symbol, parameter)] = {
            "value": None if value is None else Decimal(str(value)), "as_of_date": stamp,
            "fetched_at": fetched_at or datetime(2026, 10, 14, 0, 45, tzinfo=timezone.utc)}


RELIANCE = {"roea": 8.93, "rocea": 9.17, "debtcea": 0.41, "pbva": 1.69, "mcapq": 1568285.91, "currentprice": 1158.90}
IDEA = {"roea": -96.62, "rocea": -1.68, "debtcea": -4.18, "pbva": -3.47, "mcapq": 137270.63, "currentprice": 12.67}
ETF = {"roea": None, "rocea": None, "debtcea": None, "pbva": None, "mcapq": None, "currentprice": 254.66}


def test_build_writes_the_source_the_field_name_and_the_dates(wire):
    warehouse, _ = wire(Warehouse(["RELIANCE", "IDEA", "NIFTYBEES", "NEWCO"]), Provider())
    _stage(warehouse, "RELIANCE", RELIANCE)
    _stage(warehouse, "IDEA", IDEA)
    _stage(warehouse, "NIFTYBEES", ETF)
    _stage(warehouse, "NEWCO", dict(RELIANCE, currentprice=77.0))          # we hold no price that matches
    warehouse.closes = [("RELIANCE", date(2026, 10, 12), 1158.90), ("RELIANCE", date(2026, 10, 13), 1166.70),
                        ("IDEA", date(2026, 10, 12), 12.67), ("NEWCO", date(2026, 10, 12), 80.0)]
    warehouse.verified_basis = {"RELIANCE": True}

    stats = asyncio.run(service.build_ratios())

    rows = warehouse.fundamental_values
    assert {source for _, _, source in rows} == {"trendlyne_mcp"}
    cap = rows[("RELIANCE", "market_cap_cr", "trendlyne_mcp")]
    assert cap["value"] == Decimal("1568285.91") and cap["unit"] == "inr_crore"
    assert cap["provider_field"] == "Market Cap" and cap["provider_parameter"] == "mcapq"
    assert cap["as_of_date"] == date(2026, 10, 12) and cap["provider_date"] == date(2026, 10, 13)
    assert cap["fetched_at"] == datetime(2026, 10, 14, 0, 45, tzinfo=timezone.utc)
    assert cap["consolidated"] is True and cap["usable"] is True and cap["flags"] == []
    roe = rows[("RELIANCE", "roe_pct", "trendlyne_mcp")]
    assert roe["value"] == Decimal("8.93") and roe["period_basis"] == "annual" and roe["period_end"] is None
    # basis not verified for this company -> not asserted
    assert rows[("IDEA", "roe_pct", "trendlyne_mcp")]["consolidated"] is None
    # negative book value: stored as given, flagged, not usable
    pb = rows[("IDEA", "pb", "trendlyne_mcp")]
    assert pb["value"] == Decimal("-3.47") and pb["usable"] is False and pb["flags"] == ["negative_book_value"]
    # nothing is written for a company the provider has no figures for
    assert not any(symbol == "NIFTYBEES" for symbol, _, _ in rows)
    # no matching close -> the provider's stamp, flagged
    newco = rows[("NEWCO", "market_cap_cr", "trendlyne_mcp")]
    assert newco["as_of_date"] == date(2026, 10, 13) and newco["flags"] == ["price_date_unconfirmed"]

    assert stats["symbols_staged"] == 4 and stats["symbols_written"] == 3 and stats["no_values"] == 1
    assert stats["rows_written"] == 15 and stats["price_date_confirmed"] == 2 and stats["price_date_unconfirmed"] == 1
    assert stats["flags"] == {"negative_book_value": 3, "price_date_unconfirmed": 2}
    assert warehouse.deleted_other_runs            # rows this source no longer supplies do not linger


def test_build_dry_run_and_symbol_filter_write_or_delete_nothing_else(wire):
    warehouse, _ = wire(Warehouse(["RELIANCE", "IDEA"]), Provider())
    _stage(warehouse, "RELIANCE", RELIANCE)
    _stage(warehouse, "IDEA", IDEA)
    dry = asyncio.run(service.build_ratios(dry_run=True))
    assert dry["rows_candidate"] == 10 and dry["rows_written"] == 0 and warehouse.fundamental_values == {}
    only = asyncio.run(service.build_ratios(symbols=["IDEA"]))
    assert only["rows_written"] == 5 and {s for s, _, _ in warehouse.fundamental_values} == {"IDEA"}
    assert not warehouse.deleted_other_runs        # a partial build must not delete the other companies' rows


def test_build_says_plainly_when_migration_162_is_not_applied_and_writes_nothing(wire):
    warehouse, _ = wire(Warehouse(["RELIANCE"]), Provider())
    warehouse.migrated = False
    _stage(warehouse, "RELIANCE", RELIANCE)
    with pytest.raises(TrendlyneError, match="migration 162"):
        asyncio.run(service.build_ratios())
    assert warehouse.fundamental_values == {} and not warehouse.deleted_other_runs


def test_daily_before_the_migration_still_does_the_sectors_and_then_fails_loudly(wire, monkeypatch):
    done = []

    async def _ok(name):
        done.append(name)
        return {}

    async def _not_migrated():
        raise TrendlyneError("nidp.stock_fundamental_values does not exist: apply migration 162")

    monkeypatch.setattr(service, "fetch", lambda pass_name, **kw: _ok(pass_name))
    monkeypatch.setattr(service, "build", lambda: _ok("build"))
    monkeypatch.setattr(service, "build_ratios", _not_migrated)
    monkeypatch.setattr(service, "sectors", lambda: _ok("sectors"))
    with pytest.raises(TrendlyneError, match="migration 162"):
        asyncio.run(service.daily())
    assert done[-1] == "sectors" and done[0] == "r1"


def test_daily_fetches_the_ratio_pass_first_then_builds_the_ratios(wire, monkeypatch):
    order = []

    async def _fetch(pass_name, **kw):
        order.append(pass_name)
        return {}

    async def _step(name):
        order.append(name)
        return {}

    monkeypatch.setattr(service, "fetch", _fetch)
    monkeypatch.setattr(service, "build", lambda: _step("build"))
    monkeypatch.setattr(service, "build_ratios", lambda: _step("ratios"))
    monkeypatch.setattr(service, "sectors", lambda: _step("sectors"))
    out = asyncio.run(service.daily())
    assert order == ["r1", "p1", "p2", "p3", "p4", "build", "ratios", "sectors"]
    assert "ratios" in out and "r1" in out


# ── the migration and the engine step ────────────────────────────────────────

def _migration() -> str:
    files = sorted(MIGRATIONS.glob("162_*.sql"))
    assert len(files) == 1, files
    return files[0].read_text()


def _function_body(sql: str, name: str) -> str:
    start = sql.index(f"FUNCTION nidp.{name}(")
    return sql[start:sql.index("$function$;", start)]


def test_the_migration_records_the_source_without_wiring_the_providers_name_into_the_logic():
    sql = _migration()
    assert "fundamentals_source" in sql and "fundamentals_as_of" in sql
    for column in ("source", "provider_field", "value", "period_end", "fetched_at", "as_of_date"):
        assert re.search(rf"^\s+{column}\s", sql, re.M), column
    body = _function_body(sql, "populate_stock_fundamentals_sourced")
    assert "trendlyne" not in body.lower()                     # the function reads the source from the data
    assert "v.as_of_date <= p_target_date" in body             # a later snapshot never lands on an earlier day
    assert "v.usable" in body
    assert "'trendlyne_mcp'" in sql                            # ... and the data says who it is


def test_the_cap_bucket_thresholds_are_the_ones_the_engine_already_uses():
    engine = (MIGRATIONS / "146_consecutive_ttm_and_same_period_ratios.sql").read_text()
    theirs = re.findall(r">=\s*(\d+)\s+THEN '([A-Z_]+_CAP)'", engine) + re.findall(r"ELSE '([A-Z_]+_CAP)'", engine)
    ours_body = _function_body(_migration(), "market_cap_bucket")
    ours = re.findall(r">=\s*(\d+)\s+THEN '([A-Z_]+_CAP)'", ours_body) + re.findall(r"ELSE '([A-Z_]+_CAP)'", ours_body)
    assert ours == theirs == [("50000", "LARGE_CAP"), ("10000", "MID_CAP"), ("1000", "SMALL_CAP"), "MICRO_CAP"]


class _Conn:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def fetchval(self, sql, *args, **kwargs):
        self.calls.append((sql, args, kwargs.get("timeout")))
        if self.fail:
            raise TimeoutError()
        return 2184


def test_the_engine_step_calls_the_migration_162_function_and_survives_its_failure():
    from nidp.services.fundamental_engine import service as engine
    conn = _Conn()
    assert asyncio.run(engine._populate_sourced_fundamentals(conn, date(2026, 10, 12))) == 2184
    sql, args, timeout = conn.calls[0]
    assert "nidp.populate_stock_fundamentals_sourced" in sql and args == (date(2026, 10, 12),)
    assert timeout == engine._POPULATE_TIMEOUT_S
    assert asyncio.run(engine._populate_sourced_fundamentals(_Conn(fail=True), date(2026, 10, 12))) == 0


def test_the_engine_step_runs_after_the_extended_pass_and_before_the_v3_pass():
    """populate_stock_features_extended rewrites the five columns on every run, so the sourced
    values must be applied after it; populate_stock_features_v3 reads market cap, so before that."""
    import inspect
    from nidp.services.fundamental_engine import service as engine
    src = inspect.getsource(engine.compute_for_date)
    extended = src.index("await _populate_extended(conn, target_date)")
    sourced = src.index("await _populate_sourced_fundamentals(conn, target_date)")
    v3 = src.index("await _populate_v3(conn, target_date)")
    assert extended < sourced < v3


def test_the_snapshotter_applies_the_sourced_values_after_its_own_extended_pass():
    src = (MIGRATIONS.parent / "services" / "feature_snapshotter" / "service.py").read_text()
    assert src.index("nidp.populate_stock_features_extended(") < src.index("nidp.populate_stock_fundamentals_sourced(")
