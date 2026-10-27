"""Strategy Builder evidence sources: cash-flow quality, ownership changes, bulk/block deals, live bid/ask, broker margin.

Every source here is a MOCK — not real data (labelled MOCK in the snapshot's `source`). Expected values are computed
from the payload the test built, never typed in. The broker doubles raise if any order method is touched.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import date, datetime, timezone

import pytest

from services.strategy_plan import evidence as ev
from services.strategy_plan import margin as mg
from services.strategy_plan import quotes as qt
from services.strategy_plan.evidence import src_fail, src_ok
from services.strategy_plan.rules import RULES, STRATEGY_RULES_VERSION

ASOF = "2026-10-19"
NOW = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)      # 10:30 IST
REQUIRED = {"group", "key", "value", "interpretation", "direction", "source", "source_as_of", "version"}


def by_key(items):
    return {i["key"]: i for i in items}


def run(coro):
    return asyncio.run(coro)


def check_shape(items):
    for i in items:
        assert REQUIRED <= set(i), i
        assert i["direction"] in ev.DIRECTIONS
        if i["direction"] == "unavailable":
            assert i["value"] is None and i["interpretation"]


# ── cash-flow quality ────────────────────────────────────────────────────────

def features(**o):                                              # MOCK — not real data
    row = {"symbol": "MOCKCO", "as_of_date": ASOF, "pe_ttm": 20.0, "pb": 3.0, "roe_pct": 15.0, "roce_pct": 18.0, "debt_to_equity": 0.4,
           "market_cap_cr": 5000.0, "cfo_pat_ratio": 1.2}
    row.update(o)
    return src_ok(row, "MOCK DaaS features", ASOF)


def cash_items(snap, d="bullish"):
    return by_key(ev.cash_flow_items({"features": snap}, d))


@pytest.mark.parametrize("ratio,d,expected", [
    (RULES["cash_flow"]["strong_at_or_above"] + 0.3, "bullish", "supports"),
    (RULES["cash_flow"]["weak_below"] - 0.2, "bullish", "conflicts"),
    ((RULES["cash_flow"]["weak_below"] + RULES["cash_flow"]["strong_at_or_above"]) / 2, "bullish", "neutral"),
    (RULES["cash_flow"]["weak_below"] - 0.2, "bearish", "supports"),
    (RULES["cash_flow"]["strong_at_or_above"] + 0.3, "bearish", "conflicts"),
    (RULES["cash_flow"]["strong_at_or_above"] + 0.3, "volatility_expansion", "neutral"),
])
def test_cash_flow_direction_rule(ratio, d, expected):
    items = cash_items(features(cfo_pat_ratio=ratio), d)
    it = items["cash_flow_quality"]
    assert it["direction"] == expected
    assert it["value"]["cfo_pat_ratio"] == ratio
    assert it["source_as_of"] == ASOF and "DaaS" in it["source"]
    assert str(ratio) in it["interpretation"] or f"{ratio:g}" in it["interpretation"]
    check_shape(items.values())


def test_cash_flow_negative_ratio_has_no_direction_but_is_not_missing():
    it = cash_items(features(cfo_pat_ratio=-0.5))["cash_flow_quality"]
    assert it["direction"] == "neutral" and "opposite signs" in it["interpretation"]


def test_cash_flow_empty_is_unavailable_with_the_loader():
    items = cash_items(features(cfo_pat_ratio=None))
    it = items["cash_flow_quality"]
    assert it["direction"] == "unavailable" and it["value"] is None
    assert "cfo_pat_ratio is empty" in it["interpretation"] and "yahoo_fundamentals" in it["interpretation"]
    assert items["free_cash_flow"]["direction"] == "unavailable"
    check_shape(items.values())


def test_cash_flow_failing_or_unread_source_is_unavailable_never_neutral():
    for snap in (src_fail("HTTP 500: boom", "MOCK features"), None):
        items = by_key(ev.cash_flow_items({} if snap is None else {"features": snap}, "bullish"))
        assert items["cash_flow_quality"]["direction"] == "unavailable"
        assert items["free_cash_flow"]["direction"] == "unavailable"
    assert "HTTP 500" in by_key(ev.cash_flow_items({"features": src_fail("HTTP 500: boom", "x")}, "bullish"))["cash_flow_quality"]["interpretation"]


# ── ownership changes ────────────────────────────────────────────────────────

def sh(period, source="NSE_SHP", **o):                            # MOCK — not real data
    row = {"symbol": "MOCKCO", "period_end": period, "source": source, "promoter_pct": None, "promoter_pledged_pct": None,
           "fii_pct": None, "dii_pct": None, "mf_pct": None}
    row.update(o)
    return row


def holding(rows):
    return src_ok(rows, "MOCK DaaS /v1/shareholding/{symbol}", max((r["period_end"] for r in rows), default=None))


def own(rows, d="bullish"):
    return by_key(ev.ownership_items({"shareholding": holding(rows), "deals": src_fail("not read", "x")}, d, TODAY_DAY))


TODAY_DAY = date(2026, 10, 20)

QUARTERS = [sh("2026-09-30", promoter_pct=49.0, promoter_pledged_pct=5.0, fii_pct=20.0, dii_pct=15.0),
            sh("2026-06-30", promoter_pct=50.0, promoter_pledged_pct=4.0, fii_pct=19.0, dii_pct=15.1)]


def test_ownership_changes_are_newest_minus_previous_with_dates():
    items = own(QUARTERS)
    new, old = QUARTERS
    p = items["ownership_promoter"]
    assert p["value"]["latest"] == {"period_end": "2026-09-30", "value": new["promoter_pct"]}
    assert p["value"]["previous"] == {"period_end": "2026-06-30", "value": old["promoter_pct"]}
    assert p["value"]["change_pp"] == round(new["promoter_pct"] - old["promoter_pct"], 2)
    assert "2026-09-30" in p["interpretation"] and "2026-06-30" in p["interpretation"]
    assert p["source_as_of"] == "2026-09-30"
    check_shape(items.values())


def test_ownership_direction_rules_for_a_bullish_view():
    items = own(QUARTERS, "bullish")
    assert items["ownership_promoter"]["direction"] == "conflicts"       # promoter holding fell by 1.0 pp
    assert items["ownership_pledge"]["direction"] == "conflicts"         # pledge rose by 1.0 pp
    assert items["ownership_fii"]["direction"] == "supports"             # FII holding rose by 1.0 pp
    assert items["ownership_dii"]["direction"] == "neutral"              # moved 0.1 pp, inside the band


def test_ownership_direction_rules_for_a_bearish_view_are_mirrored():
    items = own(QUARTERS, "bearish")
    assert items["ownership_promoter"]["direction"] == "supports"
    assert items["ownership_pledge"]["direction"] == "supports"
    assert items["ownership_fii"]["direction"] == "conflicts"


def test_ownership_band_is_a_rule():
    band = RULES["ownership"]["min_change_pp"]
    rows = [sh("2026-09-30", promoter_pct=50.0 + band / 2), sh("2026-06-30", promoter_pct=50.0)]
    assert own(rows)["ownership_promoter"]["direction"] == "neutral"
    rows = [sh("2026-09-30", promoter_pct=50.0 + band * 2), sh("2026-06-30", promoter_pct=50.0)]
    assert own(rows)["ownership_promoter"]["direction"] == "supports"


def test_ownership_merges_per_quarter_gaps_using_newest_quarter_that_has_the_figure():
    # the newest row carries only the pledge (the NSE pledge file); the holding split sits in older rows
    rows = [sh("2026-09-30", promoter_pledged_pct=3.0),
            sh("2026-06-30", promoter_pct=51.0, promoter_pledged_pct=2.0, fii_pct=10.0),
            sh("2026-03-31", promoter_pct=52.0, fii_pct=9.0)]
    items = own(rows)
    p = items["ownership_promoter"]
    assert p["value"]["latest"]["period_end"] == "2026-06-30" and p["value"]["previous"]["period_end"] == "2026-03-31"
    assert p["value"]["change_pp"] == -1.0
    pl = items["ownership_pledge"]
    assert pl["value"]["latest"]["period_end"] == "2026-09-30" and pl["value"]["previous"]["period_end"] == "2026-06-30"


def test_ownership_two_rows_for_one_quarter_take_the_first_non_null_per_field():
    rows = [sh("2026-09-30", source="NSE_SHP", promoter_pct=None, fii_pct=20.0),
            sh("2026-09-30", source="screener_in", promoter_pct=48.0, fii_pct=99.0),
            sh("2026-06-30", promoter_pct=50.0, fii_pct=19.0)]
    items = own(rows)
    assert items["ownership_promoter"]["value"]["latest"]["value"] == 48.0
    assert items["ownership_fii"]["value"]["latest"]["value"] == 20.0     # the first listed source wins where it has the figure


def test_ownership_unavailable_when_null_or_single_quarter_and_mutual_funds_null_today():
    rows = [sh("2026-09-30", promoter_pct=50.0), sh("2026-06-30", promoter_pct=None)]
    items = own(rows)
    assert items["ownership_promoter"]["direction"] == "unavailable" and "two quarters" in items["ownership_promoter"]["interpretation"]
    assert items["ownership_mf"]["direction"] == "unavailable" and "mf_pct" in items["ownership_mf"]["interpretation"]
    assert items["ownership_fii"]["direction"] == "unavailable"
    check_shape(items.values())


def test_ownership_failing_empty_or_unread_source():
    for snap in (src_fail("HTTP 502", "MOCK"), holding([]), None):
        snaps = {} if snap is None else {"shareholding": snap, "deals": src_fail("x", "x")}
        items = by_key(ev.ownership_items(snaps, "bullish", TODAY_DAY))
        assert items["ownership_changes"]["direction"] == "unavailable"
        assert items["ownership_changes"]["value"] is None and items["ownership_changes"]["interpretation"]
        assert "ownership_promoter" not in items


# ── bulk / block deals and insider ───────────────────────────────────────────

def deal(day, side, qty, kind="bulk", client="MOCK FUND", pct=None):    # MOCK — not real data
    return {"as_of_date": day, "kind": kind, "symbol": "MOCKCO", "client_name": client, "deal_type": side, "quantity": qty,
            "avg_price": 100.0, "pct_of_shares": pct}


def deals_snap(rows, coverage_from="2026-09-01"):
    return src_ok({"window": {"from": "2026-09-20", "to": "2026-10-20"}, "rows": rows, "coverage_from": coverage_from},
                  "MOCK DaaS /v1/flows/bulk-deals + block-deals", "2026-10-20")


def deal_items(snap, d="bullish"):
    return by_key(ev.ownership_items({"shareholding": src_fail("x", "x"), "deals": snap}, d, TODAY_DAY))


def test_deals_net_buy_supports_bullish_with_dates_and_clients():
    rows = [deal("2026-10-15", "BUY", 3_000_000, pct=0.3), deal("2026-10-12", "SELL", 1_000_000, "block", "OTHER", 0.1)]
    it = deal_items(deals_snap(rows))["bulk_block_deals"]
    assert it["direction"] == "supports"
    assert it["value"]["net_quantity"] == 2_000_000 and it["value"]["buy_quantity"] == 3_000_000 and it["value"]["sell_quantity"] == 1_000_000
    assert it["value"]["count"] == 2 and it["value"]["latest_deal_date"] == "2026-10-15"
    assert "2026-10-15" in it["interpretation"]
    assert deal_items(deals_snap(rows), "bearish")["bulk_block_deals"]["direction"] == "conflicts"


def test_deals_net_sell_conflicts_bullish():
    it = deal_items(deals_snap([deal("2026-10-15", "SELL", 500, pct=0.5)]))["bulk_block_deals"]
    assert it["direction"] == "conflicts"


def test_deals_below_the_size_rule_is_neutral():
    tiny = RULES["ownership"]["deal_min_net_pct_of_shares"] / 2
    it = deal_items(deals_snap([deal("2026-10-15", "BUY", 10, pct=tiny)]))["bulk_block_deals"]
    assert it["direction"] == "neutral"


def test_deals_without_share_count_are_not_directional():
    it = deal_items(deals_snap([deal("2026-10-15", "BUY", 10, pct=None)]))["bulk_block_deals"]
    assert it["direction"] == "neutral" and "share count" in it["interpretation"]


def test_no_deals_in_a_fully_covered_window_is_a_real_neutral_finding():
    it = deal_items(deals_snap([], coverage_from="2026-09-01"))["bulk_block_deals"]
    assert it["direction"] == "neutral" and it["value"]["count"] == 0 and "No bulk or block deal" in it["interpretation"]


def test_no_deals_in_a_partly_covered_window_says_so():
    it = deal_items(deals_snap([], coverage_from="2026-10-09"))["bulk_block_deals"]
    assert it["direction"] == "neutral" and "2026-10-09" in it["interpretation"] and "starts" in it["interpretation"]


def test_deals_failing_source_is_unavailable():
    items = deal_items(src_fail("DAAS connectivity error", "MOCK"))
    assert items["bulk_block_deals"]["direction"] == "unavailable" and "connectivity" in items["bulk_block_deals"]["interpretation"]
    assert items["insider_sast"]["direction"] == "unavailable"
    check_shape(items.values())


# ── bid / ask in the derivatives group ───────────────────────────────────────

def chain_snap():
    return src_ok({"summary": {"expiry": "2026-10-27", "atm_strike": 1300.0, "spot": 1301.0}, "strikes": []}, "MOCK chain", ASOF)


def quote_snapshot(mode="live", **o):                             # MOCK — not real data
    q = {"label": "ATM call 1300", "instrument_type": "CE", "strike": 1300.0, "expiry": "2026-10-27", "bid": 20.0, "ask": 21.0, "bid_qty": 550, "ask_qty": 275,
         "ltp": 20.5, "last_traded_at": "2026-10-20T10:29:30+05:30", "mode": mode, "spread": 1.0, "spread_pct": round(1.0 / 20.5 * 100, 2), "age_seconds": 30}
    q.update(o)
    return src_ok({"broker": "icicidirect", "display": "ICICI Direct", "read_at": "2026-10-20T10:30:00+05:30", "quotes": [q], "skipped": []},
                  "MOCK ICICI Direct quotes (read-only)", "2026-10-20", "broker-quote-v1")


def derivs(quotes):
    snaps = {"chain": chain_snap(), "buildup": src_fail("x", "x"), "futures": src_fail("x", "x")}
    if quotes is not None:
        snaps["broker_quotes"] = quotes
    return by_key(ev.derivatives(snaps, "bullish", ASOF))


def test_bid_ask_live_quote_is_an_item_with_the_time_and_mode():
    it = derivs(quote_snapshot())["bid_ask"]
    assert it["direction"] == "neutral" and it["value"]["mode"] == "live" and it["value"]["broker"] == "ICICI Direct"
    q = it["value"]["quotes"][0]
    assert (q["bid"], q["ask"]) == (20.0, 21.0)
    assert "live" in it["interpretation"] and "10:30" in it["interpretation"] and "ICICI Direct" in it["interpretation"]
    assert it["source_as_of"] == "2026-10-20"


def test_bid_ask_delayed_quote_is_labelled_delayed():
    it = derivs(quote_snapshot(mode="delayed", age_seconds=9000))["bid_ask"]
    assert it["value"]["mode"] == "delayed" and "delayed" in it["interpretation"]


def test_bid_ask_wide_spread_is_flagged_by_the_rule():
    wide = RULES["quotes"]["wide_spread_pct"] + 1
    it = derivs(quote_snapshot(spread_pct=wide))["bid_ask"]
    assert "wide" in it["interpretation"].lower()


def test_bid_ask_without_a_broker_stays_unavailable_with_the_eod_reason():
    for snaps in (None, src_fail("no connected broker has a live session", "MOCK"), src_ok({"quotes": [], "skipped": ["x"], "display": "ICICI Direct"}, "MOCK")):
        it = derivs(snaps)["bid_ask"]
        assert it["direction"] == "unavailable" and it["value"] is None
        assert "no bid or ask" in it["interpretation"]


# ── the live quote reader (fake broker) ──────────────────────────────────────

class NoOrders:
    """A broker double that fails the test if any order-shaped method is touched."""

    def __getattr__(self, name):
        raise AssertionError(f"order or unexpected method touched: {name}")


class FakeDepth(NoOrders):
    def __init__(self, rows=None, boom=None):
        object.__setattr__(self, "rows", rows or {})
        object.__setattr__(self, "boom", boom)
        object.__setattr__(self, "calls", [])

    async def read(self, token, underlying, isin, contracts):
        self.calls.append((token, underlying, isin, list(contracts)))
        if self.boom:
            raise self.boom
        return [self.rows.get((c["instrument_type"], c["strike"])) for c in contracts]


def account(broker="icicidirect", live=True, **o):
    return {"account_id": "acc1", "user_id": "u1", "broker": broker, "native": True, "status": "active" if live else "ended", **o}


CONTRACTS = [{"label": "ATM call 1300", "instrument_type": "CE", "strike": 1300.0, "expiry": "2026-10-27"},
             {"label": "ATM put 1300", "instrument_type": "PE", "strike": 1300.0, "expiry": "2026-10-27"}]


def read_quotes(accounts, readers, **kw):
    return run(qt.read_option_bid_ask(accounts, "RELIANCE", "INE002A01018", CONTRACTS, load_token=lambda doc: f"tok-{doc['account_id']}",
                                      is_live=lambda doc: doc.get("status") == "active", readers=readers, now=NOW, **kw))


def test_quote_reader_returns_bid_ask_live_with_time_and_never_orders():
    fake = FakeDepth({("CE", 1300.0): {"bid": 20.0, "ask": 21.0, "bid_qty": 550, "ask_qty": 275, "ltp": 20.5, "last_traded_at": "2026-10-20T10:29:30+05:30"},
                      ("PE", 1300.0): {"bid": 15.0, "ask": 15.5, "bid_qty": 10, "ask_qty": 20, "ltp": 15.2, "last_traded_at": "2026-10-20T10:29:00+05:30"}})
    snap = read_quotes([account()], {"icicidirect": ("ICICI Direct", fake)})
    assert snap["ok"] and snap["as_of"] == "2026-10-20"
    q = snap["data"]["quotes"]
    assert [x["label"] for x in q] == ["ATM call 1300", "ATM put 1300"]
    assert (q[0]["bid"], q[0]["ask"], q[0]["spread"]) == (20.0, 21.0, 1.0)
    assert q[0]["spread_pct"] == round(1.0 / ((20.0 + 21.0) / 2) * 100, 2)
    assert q[0]["mode"] == "live" and q[0]["age_seconds"] == 30
    assert snap["data"]["broker"] == "icicidirect" and snap["data"]["read_at"].startswith("2026-10-20T10:30")
    assert fake.calls[0][0] == "tok-acc1" and fake.calls[0][1:3] == ("RELIANCE", "INE002A01018")


def test_quote_reader_old_trade_time_is_delayed():
    fake = FakeDepth({("CE", 1300.0): {"bid": 20.0, "ask": 21.0, "ltp": 20.5, "last_traded_at": "2026-10-19T15:29:00+05:30"}})
    q = read_quotes([account()], {"icicidirect": ("ICICI Direct", fake)})["data"]["quotes"][0]
    assert q["mode"] == "delayed" and q["age_seconds"] > RULES["quotes"]["live_max_age_seconds"]


def test_quote_reader_empty_depth_or_crossed_book_is_skipped_not_invented():
    fake = FakeDepth({("CE", 1300.0): {"bid": 0, "ask": 0, "ltp": 20.5}, ("PE", 1300.0): {"bid": 22.0, "ask": 21.0, "ltp": 21.0}})
    snap = read_quotes([account()], {"icicidirect": ("ICICI Direct", fake)})
    assert snap["ok"] and snap["data"]["quotes"] == [] and len(snap["data"]["skipped"]) == 2


def test_quote_reader_without_a_usable_account_degrades():
    fake = FakeDepth()
    for accounts, why in (([], "no connected broker"), ([account(live=False)], "no connected broker"),
                          ([account(broker="zerodha")], "no connected broker")):
        snap = read_quotes(accounts, {"icicidirect": ("ICICI Direct", fake)})
        assert not snap["ok"] and why in snap["error"]
    assert fake.calls == []


def test_quote_reader_failure_degrades_with_a_reason_and_does_not_raise():
    snap = read_quotes([account()], {"icicidirect": ("ICICI Direct", FakeDepth(boom=RuntimeError("503 from broker")))})
    assert not snap["ok"] and "503 from broker" in snap["error"] and "ICICI Direct" in snap["error"]


def test_quote_reader_tries_the_next_account_after_a_failure():
    bad, good = FakeDepth(boom=RuntimeError("down")), FakeDepth({("CE", 1300.0): {"bid": 1.0, "ask": 1.5, "ltp": 1.2, "last_traded_at": "2026-10-20T10:29:59+05:30"}})
    snap = read_quotes([account(), account(broker="other", account_id="acc2")], {"icicidirect": ("ICICI Direct", bad), "other": ("Other", good)})
    assert snap["ok"] and snap["data"]["broker"] == "other"


def test_icici_reader_uses_only_holdings_and_quotes_reads():
    # the real ICICI reader, with its adapter calls replaced: it may call fetch_holdings and the signed GET of /quotes only
    import services.brokers.icicidirect as ic

    calls = []

    class H:                                                     # MOCK — not real data
        isin, symbol = "INE002A01018", "MOCKCODE"

    async def holdings(token):
        calls.append("holdings")
        return [H()]

    async def signed_get(path, payload, token, what):
        calls.append(("GET", path, payload["stock_code"], payload["right"], payload["strike_price"]))
        return [{"ltp": 20.5, "ltt": "20-Oct-2026 10:29:30", "best_bid_price": 20.0, "best_bid_quantity": "550",
                 "best_offer_price": 21.0, "best_offer_quantity": "275"}]

    reader = qt.IciciDepthReader(fetch_holdings=holdings, signed_get=signed_get, payload=ic._contract_payload, contract_ref=ic.ContractRef)
    rows = run(reader.read("tok", "RELIANCE", "INE002A01018", CONTRACTS))
    assert rows[0]["bid"] == 20.0 and rows[0]["ask"] == 21.0 and rows[0]["bid_qty"] == 550 and rows[0]["ask_qty"] == 275
    assert rows[0]["last_traded_at"] == "2026-10-20T10:29:30+05:30"
    assert calls[0] == "holdings" and all(c == "holdings" or c[:3] == ("GET", "quotes", "MOCKCODE") for c in calls)


def test_icici_reader_without_the_underlying_in_the_account_says_why():
    async def holdings(token):
        return []

    async def signed_get(*a, **k):
        raise AssertionError("no quote may be requested for an unknown stock code")

    import services.brokers.icicidirect as ic
    reader = qt.IciciDepthReader(fetch_holdings=holdings, signed_get=signed_get, payload=ic._contract_payload, contract_ref=ic.ContractRef)
    with pytest.raises(qt.QuoteUnavailable) as e:
        run(reader.read("tok", "RELIANCE", "INE002A01018", CONTRACTS))
    assert "stock code" in str(e.value)


# ── the margin reader (fake Kite) ────────────────────────────────────────────

class FakeKite(NoOrders):
    def __init__(self, result=None, boom=None):
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "boom", boom)
        object.__setattr__(self, "seen", [])

    def basket_order_margins(self, params, consider_positions=True, mode=None):
        self.seen.append((params, consider_positions, mode))
        if self.boom:
            raise self.boom
        return self.result


LEGS = [{"kind": "option", "side": "buy", "quantity": 2, "lot_size": 250, "strike": 1300.0, "option_type": "call", "expiry": "2026-10-27"},
        {"kind": "option", "side": "sell", "quantity": 2, "lot_size": 250, "strike": 1360.0, "option_type": "call", "expiry": "2026-10-27"}]
KITE_RESULT = {"initial": {"total": 90_000.0, "span": 70_000.0, "exposure": 20_000.0}, "final": {"total": 41_500.5, "span": 30_000.0, "exposure": 11_500.5},
               "orders": [{}, {}]}


def margin_for(legs, kite, accounts=None, underlying="RELIANCE"):
    return run(mg.read_margin_estimate(accounts if accounts is not None else [account("zerodha")], underlying, legs, kite_factory=lambda token: kite,
                                       load_token=lambda doc: "tok", is_live=lambda doc: doc.get("status") == "active", now=NOW))


def test_margin_uses_the_calculator_with_units_and_the_final_total():
    kite = FakeKite(KITE_RESULT)
    r = margin_for(LEGS, kite)
    assert r["estimate"] == KITE_RESULT["final"]["total"] and r["before_offset"] == KITE_RESULT["initial"]["total"]
    assert r["broker"] == "zerodha" and r["reason"] is None
    assert "estimate from Zerodha's margin calculator" in r["source"] and "no order is placed" in r["source"]
    params, consider, mode = kite.seen[0]
    assert consider is False
    assert [(p["tradingsymbol"], p["transaction_type"], p["quantity"], p["exchange"]) for p in params] == [
        ("RELIANCE26OCT1300CE", "BUY", 500, "NFO"), ("RELIANCE26OCT1360CE", "SELL", 500, "NFO")]
    assert all(p["variety"] == "regular" and p["order_type"] == "MARKET" and p["product"] == "NRML" for p in params)


def test_margin_for_a_future_and_a_fractional_strike():
    legs = [{"kind": "future", "side": "buy", "quantity": 1, "lot_size": 250, "expiry": "2026-10-27"},
            {"kind": "option", "side": "buy", "quantity": 1, "lot_size": 250, "strike": 1297.5, "option_type": "put", "expiry": "2026-10-27"}]
    kite = FakeKite(KITE_RESULT)
    margin_for(legs, kite)
    assert [p["tradingsymbol"] for p in kite.seen[0][0]] == ["RELIANCE26OCTFUT", "RELIANCE26OCT1297.5PE"]


@pytest.mark.parametrize("accounts,why", [
    ([], "no connected"),
    ([account("zerodha", live=False)], "no connected"),
    ([account("icicidirect")], "no connected"),
])
def test_margin_without_a_zerodha_session_is_null_with_a_reason(accounts, why):
    kite = FakeKite(KITE_RESULT)
    r = margin_for(LEGS, kite, accounts)
    assert r["estimate"] is None and why in r["reason"] and kite.seen == []


def test_margin_index_underlyings_and_cash_legs_are_not_attempted():
    kite = FakeKite(KITE_RESULT)
    r = margin_for(LEGS, kite, underlying="NIFTY")
    assert r["estimate"] is None and "index" in r["reason"] and kite.seen == []
    r = margin_for([{"kind": "cash", "side": "buy", "quantity": 10, "lot_size": 1}], kite)
    assert r["estimate"] is None and "cash" in r["reason"] and kite.seen == []


def test_margin_failure_and_unreadable_result_degrade_to_null():
    r = margin_for(LEGS, FakeKite(boom=RuntimeError("Token invalid")))
    assert r["estimate"] is None and "Token invalid" in r["reason"] and "Zerodha" in r["reason"]
    r = margin_for(LEGS, FakeKite({"final": {}}))
    assert r["estimate"] is None and "no total" in r["reason"]


def test_margin_item_for_the_ledger():
    ok = mg.margin_item(margin_for(LEGS, FakeKite(KITE_RESULT)))
    assert ok["group"] == "derivatives" and ok["key"] == "margin_estimate" and ok["direction"] == "neutral"
    assert ok["value"]["estimate"] == KITE_RESULT["final"]["total"] and "no order is placed" in ok["interpretation"]
    check_shape([ok])
    no = mg.margin_item(margin_for(LEGS, FakeKite(boom=RuntimeError("x"))))
    assert no["direction"] == "unavailable" and no["value"] is None
    check_shape([no])


def test_no_order_method_is_named_anywhere_in_the_new_modules():
    forbidden = ("place_order", "modify_order", "cancel_order", "place_gtt", "modify_gtt", "delete_gtt", "convert_position", "exit_order",
                 "placeorder", "cancelorder", "modifyorder")
    for mod in (mg, qt):
        src = inspect.getsource(mod).lower()
        # the modules may only mention such a name inside the guard list that refuses it
        for name in forbidden:
            assert src.count(name) == 0, f"{mod.__name__} mentions {name}"


# ── the ledger as a whole ────────────────────────────────────────────────────

def test_ledger_items_are_complete_and_missing_is_never_neutral():
    snaps = {"features": features(cfo_pat_ratio=None), "shareholding": holding(QUARTERS), "deals": deals_snap([deal("2026-10-15", "BUY", 500, pct=0.5)]),
             "chain": chain_snap(), "broker_quotes": src_fail("no connected broker has a live session", "MOCK")}
    inputs = {"direction": "bullish", "horizon_days": 10, "underlying": "MOCKCO"}
    items = ev.build_ledger(snaps, inputs, ASOF, ASOF)["items"]
    check_shape(items)
    keys = {(i["group"], i["key"]): i for i in items}
    assert keys[("fundamental", "cash_flow_quality")]["direction"] == "unavailable"
    assert keys[("fundamental", "ownership_promoter")]["direction"] == "conflicts"
    assert keys[("fundamental", "bulk_block_deals")]["direction"] == "supports"
    assert keys[("derivatives", "bid_ask")]["direction"] == "unavailable"
    assert all(i["direction"] != "neutral" or i["value"] is not None for i in items if i["key"] in ("cash_flow_quality", "bid_ask"))


def test_rules_version_was_bumped_for_the_new_constants():
    assert STRATEGY_RULES_VERSION.startswith("strategy-rules.v1.6")
    for k in ("ownership", "cash_flow", "quotes"):
        assert k in RULES


# ── live broker reads in the plan (flag, margin on candidates, leg bid/ask, ideas stay off) ──────────────

import copy

from services.strategy_plan import live_reads as lr
from services.strategy_plan import plan as pl
from services.strategy_plan import sources as srcs


def test_live_broker_reads_is_off_by_default_and_disclosed():
    base = {"underlying": "RELIANCE", "direction": "bullish"}
    i, probs = pl.normalise_inputs(base)
    assert not probs and i["live_broker_reads"] is False and "live_broker_reads" in i["defaults_applied"]
    i, _ = pl.normalise_inputs({**base, "live_broker_reads": True})
    assert i["live_broker_reads"] is True and "live_broker_reads" not in i["defaults_applied"]
    _, probs = pl.normalise_inputs({**base, "live_broker_reads": "yes"})
    assert any(p["code"] == "bad_live_broker_reads" for p in probs)


def test_the_quote_source_is_not_called_when_the_flag_is_off(monkeypatch):
    called = []

    async def boom(*a, **k):
        called.append(1)
        raise AssertionError("a broker read was attempted")

    monkeypatch.setattr(srcs, "_broker_bid_ask", boom)
    off = run(srcs._live_quotes("u1", "RELIANCE", chain_snap(), {"live_broker_reads": False}))
    assert not off["ok"] and "live_broker_reads" in off["error"] and called == []
    on = run(srcs._safe("q", srcs._live_quotes("u1", "RELIANCE", chain_snap(), {"live_broker_reads": True})))
    assert called == [1] and not on["ok"]          # the double raised; _safe turns it into a failed snapshot, never an exception


def test_ideas_force_the_flag_off_and_make_no_broker_call():
    import inspect
    from services.strategy_plan import ideas
    src = inspect.getsource(ideas)
    assert 'plan_in["live_broker_reads"] = False' in src
    assert "attach_live_reads" not in src and "read_margin_estimate" not in src and "read_option_bid_ask" not in src


def plan_doc():                                                  # MOCK — not real data
    leg_a = {"kind": "option", "side": "buy", "quantity": 1, "lot_size": 250, "strike": 1300.0, "option_type": "call", "expiry": "2026-10-27"}
    leg_b = {"kind": "option", "side": "sell", "quantity": 1, "lot_size": 250, "strike": 1360.0, "option_type": "call", "expiry": "2026-10-27"}
    fut = {"kind": "future", "side": "buy", "quantity": 1, "lot_size": 250, "expiry": "2026-10-27"}
    flags = ["Low open interest at 1360"]
    opt = {"id": "opt1", "segment": "options", "status": "candidate", "legs": [leg_a, leg_b], "payoff": {"margin": None, "margin_reason": "none"},
           "options_selection": {"preferred_flags": flags}, "warnings": []}
    twin = {"id": "opt2", "segment": "options", "status": "candidate", "legs": [leg_a, leg_b], "payoff": {"margin": None, "margin_reason": "none"},
            "options_selection": {"preferred_flags": []}, "warnings": []}
    fx = {"id": "fut1", "segment": "futures", "status": "candidate", "legs": [fut], "payoff": {"margin": None, "margin_reason": "none"}, "options_selection": None,
          "warnings": ["Futures losses can exceed the initial margin; the plan does not estimate margin, so the notional is used for the allocation cap."]}
    blocked = {"id": "opt3", "segment": "options", "status": "no_trade", "legs": [leg_a], "payoff": {"margin": None, "margin_reason": "none"}, "options_selection": None, "warnings": []}
    cash = {"id": "cash1", "segment": "cash", "status": "candidate", "legs": [{"kind": "cash", "side": "buy", "quantity": 10, "lot_size": 1}], "payoff": {"margin": None}, "options_selection": None, "warnings": []}
    return {"inputs": {"underlying": "RELIANCE", "live_broker_reads": True}, "preferred": "opt1", "candidates": [opt, twin, fx, blocked, cash],
            "alternatives": [{"id": "opt1", "liquidity_flags": flags}, {"id": "opt2", "liquidity_flags": []}],
            "evidence": [], "evidence_summary": {g: {x: 0 for x in ev.DIRECTIONS} for g in ev.GROUPS},
            "caveats": ["x", pl.EOD_CAVEAT, "y", pl.MARGIN_CAVEAT], "data_as_of": {"mode": "end_of_day"}, "sent_to_broker": False}


class CountingKite(FakeKite):
    pass


def attach(plan, accounts, kite=None, readers=None):
    return run(lr.attach_live_reads(plan, accounts, "INE002A01018", load_token=lambda d: "tok", is_live=lambda d: d.get("status") == "active",
                                    readers=readers or {}, kite_factory=(lambda t: kite) if kite else None, now=NOW))


def test_margin_is_attached_to_viable_fno_candidates_with_one_call_per_distinct_legs():
    kite, p = FakeKite(KITE_RESULT), plan_doc()
    stats = attach(p, [account("zerodha")], kite)
    by = {c["id"]: c for c in p["candidates"]}
    for k in ("opt1", "opt2", "fut1"):
        m = by[k]["payoff"]["margin"]
        assert m["estimate"] == KITE_RESULT["final"]["total"] and "estimate from Zerodha's margin calculator, read-only; no order is placed" in m["source"]
        assert by[k]["payoff"]["margin_reason"] is None
    assert by["opt3"]["payoff"]["margin"] is None and by["cash1"]["payoff"]["margin"] is None      # blocked and cash: not asked
    assert len(kite.seen) == 2 and stats["margin_calls"] == 2                                       # opt1 == opt2 legs: one call (cached); plus the future
    items = [i for i in p["evidence"] if i["key"] == "margin_estimate"]
    assert len(items) == 1 and items[0]["direction"] == "neutral" and p["evidence_summary"]["derivatives"]["neutral"] == 1
    assert pl.EOD_CAVEAT in p["caveats"] and pl.MARGIN_CAVEAT not in p["caveats"] and any("margin calculator" in c for c in p["caveats"])
    assert "Futures losses can exceed the initial margin" in by["fut1"]["warnings"][0] and "broker's margin estimate" in by["fut1"]["warnings"][0]
    assert p["sent_to_broker"] is False


def test_no_live_session_means_no_call_and_a_null_margin_with_the_reason():
    kite, p = FakeKite(KITE_RESULT), plan_doc()
    stats = attach(p, [account("zerodha", live=False)], kite)
    assert kite.seen == [] and stats["margin_calls"] == 0
    for c in p["candidates"]:
        assert c["payoff"]["margin"] is None
    assert "no connected Zerodha account" in p["candidates"][0]["payoff"]["margin_reason"]
    assert p["evidence"][0]["key"] == "margin_estimate" and p["evidence"][0]["direction"] == "unavailable"
    assert pl.MARGIN_CAVEAT in p["caveats"]


def test_a_failing_calculator_is_null_with_the_reason_and_the_plan_survives():
    p = plan_doc()
    attach(p, [account("zerodha")], FakeKite(boom=RuntimeError("Token invalid")))
    assert p["candidates"][0]["payoff"]["margin"] is None and "Token invalid" in p["candidates"][0]["payoff"]["margin_reason"]


def test_the_flag_off_touches_nothing():
    kite, quotes_reader, p = FakeKite(KITE_RESULT), FakeDepth(), plan_doc()
    p["inputs"]["live_broker_reads"] = False
    before = copy.deepcopy(p)
    stats = attach(p, [account("zerodha"), account("icicidirect")], kite, {"icicidirect": ("ICICI Direct", quotes_reader)})
    assert p == before and kite.seen == [] and quotes_reader.calls == [] and stats == {"margin_calls": 0, "quote_calls": 0}


def test_leg_bid_ask_is_shown_wide_spreads_are_flagged_and_direction_is_untouched():
    good = {"bid": 20.0, "ask": 21.0, "bid_qty": 5, "ask_qty": 5, "ltp": 20.5, "last_traded_at": "2026-10-20T10:29:30+05:30"}
    wide = {"bid": 2.0, "ask": 3.0, "bid_qty": 5, "ask_qty": 5, "ltp": 2.5, "last_traded_at": "2026-10-20T10:29:30+05:30"}
    depth = FakeDepth({("CE", 1300.0): good, ("CE", 1360.0): wide})
    p = plan_doc()
    stats = attach(p, [account("icicidirect")], None, {"icicidirect": ("ICICI Direct", depth)})
    opt = p["candidates"][0]
    ba = opt["options_selection"]["bid_ask"]
    assert ba["mode"] == "live" and ba["broker"] == "ICICI Direct" and [q["strike"] for q in ba["quotes"]] == [1300.0, 1360.0]
    assert stats["quote_calls"] == 1 and len(depth.calls) == 1 and [c["strike"] for c in depth.calls[0][3]] == [1300.0, 1360.0]
    spread = round(1.0 / 2.5 * 100, 2)
    assert any("1360" in f and f"{spread:g}" in f and "wide spread" in f.lower() for f in opt["options_selection"]["preferred_flags"])
    assert not any("1300" in f and "wide spread" in f.lower() for f in opt["options_selection"]["preferred_flags"])
    assert p["alternatives"][0]["liquidity_flags"] == opt["options_selection"]["preferred_flags"]
    assert opt["status"] == "candidate" and p["data_as_of"]["bid_ask"]["mode"] == "live"
    assert pl.EOD_CAVEAT not in p["caveats"] and any("live" in c and "end of day" in c for c in p["caveats"])


def test_leg_bid_ask_failure_leaves_the_end_of_day_caveat_and_says_why():
    p = plan_doc()
    attach(p, [account("icicidirect")], None, {"icicidirect": ("ICICI Direct", FakeDepth(boom=RuntimeError("503")))})
    ba = p["candidates"][0]["options_selection"]["bid_ask"]
    assert ba["status"] == "unavailable" and "503" in ba["reason"] and pl.EOD_CAVEAT in p["caveats"]


def test_plan_caveat_reads_the_quote_snapshot():
    assert pl.caveats({})[1] == pl.EOD_CAVEAT
    live = {"broker_quotes": quote_snapshot()}
    assert pl.EOD_CAVEAT not in pl.caveats(live) and any("live" in c for c in pl.caveats(live))
    assert pl.EOD_CAVEAT in pl.caveats({"broker_quotes": src_fail("none", "x")})
