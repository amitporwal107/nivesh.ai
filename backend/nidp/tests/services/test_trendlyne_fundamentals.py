"""Parsing and quarter dating for the Trendlyne fundamentals loader. No network, no database.
Company names and figures are made up."""
import json
from datetime import date

import httpx
import pytest

from nidp.services.trendlyne_fundamentals import parse
from nidp.services.trendlyne_fundamentals.client import BudgetExhausted, TrendlyneClient, TrendlyneError

PAYLOAD = json.dumps({"status": "success", "data": (
    "11|Alpha Ltd|ALPHA|500001|2026-10-12\n22|Beta & Co|BETA|500002|2026-10-12\n\n"
    "Net Profit 1Q Ago\nALPHA:85.01\nBETA:-1,620.5\n\n---\n\n"
    "Operating Rev. Qtr\nALPHA:482.11\nBETA:None\n\n---")})


def test_parameter_blocks_are_keyed_by_label_not_position():
    stocks, blocks = parse.parse_parameter_values(PAYLOAD)
    assert stocks == {"ALPHA": date(2026, 10, 12), "BETA": date(2026, 10, 12)}
    assert blocks == {"Net Profit 1Q Ago": {"ALPHA": 85.01, "BETA": -1620.5},
                      "Operating Rev. Qtr": {"ALPHA": 482.11, "BETA": None}}


def test_a_stock_missing_from_the_header_gets_no_values():
    text = json.dumps({"status": "success", "data": "11|Alpha Ltd|ALPHA|500001|2026-10-12\n\nNet Profit Qtr\nALPHA:1.0\nGHOST:2.0\n\n---"})
    stocks, blocks = parse.parse_parameter_values(text)
    assert "GHOST" not in stocks and blocks == {"Net Profit Qtr": {"ALPHA": 1.0}}


@pytest.mark.parametrize("text", ["not json", json.dumps({"status": "error", "message": "x"})])
def test_an_error_payload_is_refused(text):
    with pytest.raises(ValueError):
        parse.parse_parameter_values(text)


def test_entities_table():
    text = ("status: success\ndata:\n  name | nse_code | bse_code | isin | entity_type | sector | industry\n"
            "  Alpha Ltd. | ALPHA | 500001 | INE000A01011 | stock | FMCG | Packaged Foods\n"
            "  Alpha Life | ALPHALIFE | 500003 | INE000A01029 | stock | Healthcare | Pharmaceuticals\n")
    rows = parse.parse_entities(text)
    assert [r["nse_code"] for r in rows] == ["ALPHA", "ALPHALIFE"]
    assert rows[0]["sector"] == "FMCG" and rows[0]["industry"] == "Packaged Foods"


def test_pass_tokens_use_the_providers_irregular_names_and_fit_one_call():
    assert parse.series_token("np", 4) == "npqmy1" and parse.series_token("sr", 0) == "srq"
    for name, tokens in parse.PASSES.items():
        assert len(tokens) <= 10 and len(set(tokens)) == len(tokens), name
    everything = [t for tokens in parse.PASSES.values() for t in tokens]
    assert len(set(everything)) == len(everything)            # no parameter is paid for twice


@pytest.mark.parametrize("d, expected", [
    (date(2026, 10, 12), date(2026, 9, 30)), (date(2026, 9, 30), date(2026, 9, 30)),
    (date(2026, 1, 15), date(2025, 12, 31)), (date(2026, 3, 30), date(2025, 12, 31)),
])
def test_quarter_end_on_or_before(d, expected):
    assert parse.quarter_end_on_or_before(d) == expected


def test_shift_quarters_crosses_years_and_keeps_month_ends():
    assert parse.shift_quarters(date(2026, 3, 31), -1) == date(2025, 12, 31)
    assert parse.shift_quarters(date(2026, 6, 30), -7) == date(2024, 9, 30)
    assert parse.shift_quarters(date(2025, 12, 31), 1) == date(2026, 3, 31)


AS_OF = date(2026, 10, 12)


def test_anchor_dating_finds_the_offset_whose_revenue_matches():
    revenue = {0: 500.0, 1: 480.0, 2: 455.0, 3: 430.0}
    # we already hold the June quarter with revenue 480 -> the provider's latest is September
    assert parse.latest_quarter_from_anchor(revenue, date(2026, 6, 30), 480.9, AS_OF) == date(2026, 9, 30)
    assert parse.latest_quarter_from_anchor(revenue, date(2026, 6, 30), 500.0, AS_OF) == date(2026, 6, 30)


def test_anchor_dating_refuses_no_match_and_ambiguous_matches():
    assert parse.latest_quarter_from_anchor({0: 500.0, 1: 480.0}, date(2026, 6, 30), 300.0, AS_OF) is None
    assert parse.latest_quarter_from_anchor({0: 100.0, 1: 100.0}, date(2026, 6, 30), 100.0, AS_OF) is None
    assert parse.latest_quarter_from_anchor({0: 100.0}, date(2026, 6, 30), None, AS_OF) is None


def test_anchor_dating_allows_for_an_anchor_rounded_to_whole_crores():
    # the anchor says 6 (rounded); the provider's 5.67 this quarter and 6.01 a year ago both fit -> no date
    small = {0: 5.67, 1: 73.09, 2: 4.89, 3: 9.17, 4: 6.01}
    assert parse.latest_quarter_from_anchor(small, date(2026, 6, 30), 6.0, AS_OF) is None
    assert parse.latest_quarter_from_anchor({0: 5.67, 1: 73.09}, date(2026, 6, 30), 6.0, AS_OF) == date(2026, 6, 30)


def test_anchor_dating_works_on_a_profit_series_including_losses():
    profit = {0: 11.57, 1: 12.27, 2: -40.2}
    # a held profit rounded to 12 fits both 11.57 and 12.27 -> ambiguous, so no date
    assert parse.latest_quarter_from_anchor(profit, date(2026, 6, 30), 12.0, AS_OF) is None
    assert parse.latest_quarter_from_anchor({0: 30.0, 1: -40.2}, date(2026, 6, 30), -40.0, AS_OF) == date(2026, 9, 30)


def test_anchor_dating_never_returns_a_quarter_that_has_not_ended():
    # a match four quarters back from a June anchor would put the latest quarter in June 2027
    assert parse.latest_quarter_from_anchor({0: 9.0, 4: 6.01}, date(2026, 6, 30), 6.0, AS_OF) is None


@pytest.mark.parametrize("raw, expected", [
    ("The Karnataka Bank Limited", "Karnataka Bank"), ("Swaraj Engines Limited", "Swaraj Engines"),
    ("Alpha Foods Ltd.", "Alpha Foods"), ("Theta Limited Partners", "Theta Limited Partners"), ("", ""),
])
def test_company_search_name(raw, expected):
    assert parse.company_search_name(raw) == expected


def test_filing_dating_uses_the_newest_quarter_only_if_results_were_filed_after_it():
    as_of = date(2026, 10, 12)
    assert parse.latest_quarter_from_filings(as_of, [date(2026, 8, 5), date(2026, 10, 9)]) == date(2026, 9, 30)
    assert parse.latest_quarter_from_filings(as_of, [date(2026, 8, 5)]) == date(2026, 6, 30)
    assert parse.latest_quarter_from_filings(as_of, [date(2026, 5, 20)]) is None      # nothing recent enough
    assert parse.latest_quarter_from_filings(as_of, []) is None


def test_quarter_rows_are_dated_backwards_and_empty_quarters_dropped():
    values = {"srq": 500.0, "npq": 50.0, "opq": 90.0, "epsq": 5.0, "intq": 3.0,
              "srqmq1": 480.0, "npqmq1": 45.0, "srqmy1": 400.0, "npqmy1": None,
              "totalshareholdersfundsq": 900.0}
    rows = parse.build_quarter_rows(values, date(2026, 9, 30))
    assert [r["period_end"] for r in rows] == [date(2026, 9, 30), date(2026, 6, 30), date(2025, 9, 30)]
    assert rows[0]["revenue_from_ops_cr"] == 500.0 and rows[0]["ebitda_cr"] == 90.0
    assert rows[0]["finance_costs_cr"] == 3.0 and rows[0]["total_equity_cr"] == 900.0
    assert "finance_costs_cr" not in rows[1]                  # point-in-time items only on the latest quarter
    assert rows[2]["revenue_from_ops_cr"] == 400.0 and rows[2]["pat_cr"] is None


# ── client ───────────────────────────────────────────────────────────────────

def _transport(handler):
    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        return handler(body)
    return httpx.MockTransport(respond)


def test_client_counts_calls_against_the_budget_and_stops():
    calls = []
    ok = lambda body: httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                                                 "result": {"content": [{"type": "text", "text": "hello"}]}})
    c = TrendlyneClient("https://example.invalid/mcp?token=x", budget_left=2,
                        on_call=lambda *row: calls.append(row), transport=_transport(ok))
    assert c.call("search_entities", {"query": "A"}) == "hello"
    assert c.call("search_entities", {"query": "B"}) == "hello"
    with pytest.raises(BudgetExhausted):
        c.call("search_entities", {"query": "C"})
    assert calls == [("search_entities", True, ""), ("search_entities", True, "")]


def test_client_treats_429_as_budget_exhausted_and_never_calls_write_tools():
    c = TrendlyneClient("https://example.invalid/mcp?token=secret", budget_left=5,
                        transport=_transport(lambda body: httpx.Response(429)))
    with pytest.raises(BudgetExhausted):
        c.call("search_entities", {"query": "A"})
    with pytest.raises(TrendlyneError, match="allowlist"):
        c.call("watchlist_add_stock", {"stock_id": 1, "watchlist_id": 1})


def test_client_errors_do_not_contain_the_url():
    c = TrendlyneClient("https://example.invalid/mcp?token=secret", budget_left=5,
                        transport=_transport(lambda body: httpx.Response(500)))
    with pytest.raises(TrendlyneError) as exc:
        c.call("search_entities", {"query": "A"})
    assert "secret" not in str(exc.value) and "example.invalid" not in str(exc.value)
