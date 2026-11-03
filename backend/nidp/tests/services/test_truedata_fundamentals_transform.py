"""TrueData fundamentals: pure transform and load planning — TC-06..TC-17 (+ plan rules of TC-18..TC-21) of
test_reports/truedata_fundamentals_job_TESTCASES.md.

Every payload is SYNTHETIC, built with the key names TrueData used on 2 Nov 2026 (the real answers are under NDA and
are not in the repository). The numbers model the cases that mattered: a TCS-like crore filer, a lakh filer, a
RADICO-like company whose TrueData revenue is gross of excise (ratio 3.475), a bank-format balance sheet, a
Dec-fiscal-year company (ABB-like), duplicated list ids.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from nidp.services.truedata_fundamentals import plan as P
from nidp.services.truedata_fundamentals import transform as T

D = Decimal


# ── synthetic payload builders ───────────────────────────────────────────────────────────────────────────────

def rec(fid, file_time, symbol="AAAA", quarter="Yearly", nature="Consolidated", scripcode="500001"):
    return {"id": fid, "file_time": file_time, "scripcode": scripcode, "Symbol": symbol, "ReportingQuarter": quarter,
            "company": f"{symbol} Synthetic Ltd", "Audited": "Audited", "Nature": nature}


def filing(fid=1, file_time="2026-04-20T18:00:00", symbol="AAAA", quarter="Yearly", nature="Consolidated"):
    return T.Filing(fid, file_time, symbol, quarter, nature)


def al(fy_start="2025-04-01", fy_end="2026-03-31", quarter="Yearly", rounding="", reporting_end=None,
       assets=1000.0, eq_liab=None, ca=600.0, cl=0.0, liabilities=400.0, ncl=100.0, equity=600.0, cap=10.0,
       inventories=50.0, recv=200.0, cash=80.0, lt_debt=30.0, st_debt=20.0, pay=90.0, advances=0.0):
    return {
        "GeneralInfo": {"Symbol": "AAAA", "DateOfStartOfFinancialYear": fy_start, "DateOfEndOfFinancialYear": fy_end,
                        "DateOfStartOfReportingPeriod": None, "DateOfEndOfReportingPeriod": reporting_end,
                        "NatureOfReportStandaloneConsolidated": "Consolidated", "ReportingQuarter": quarter,
                        "LevelOfRoundingUsedInFinancialStatements": rounding},
        "AllLiabilities": {
            "noncurrentLiabilitiesGrouup": {"BorrowingsNoncurrent": lt_debt, "NoncurrentLiabilities": ncl,
                                            "LongTermBorrowings": 0.0},
            "currentLiabilitiesGroup": {"CurrentLiabilities": cl, "Liabilities": liabilities,
                                        "EquityAndLiabilities": assets if eq_liab is None else eq_liab,
                                        "BorrowingsCurrent": st_debt, "TradePayablesCurrent": pay,
                                        "ShortTermBorrowings": 0.0},
            "equityAndLiabilitiesGroup": {"EquityShareCapital": cap, "Equity": equity, "ShareholdersFunds": 0.0},
            "capitalAndLiabilitiesGroup": {"Deposits": 0.0, "CapitalAndLiabilities": 0.0}},
        "AllAssets": {
            "NonCurrentAssetsGroup": {"NoncurrentAssets": assets - ca},
            "CurrentAssetsGroup": {"CurrentAssets": ca, "Assets": assets, "Inventories": inventories,
                                   "TradeReceivables": 0.0, "TradeReceivablesCurrent": recv,
                                   "CashAndCashEquivalents": cash},
            "OtherAssetsGroup": {"Advances": advances, "Investments": 0.0}}}


def cf(start="2026-01-01", end="2026-03-31", cfo="520", cfi="-128", cff="-421", before="-29", net="-19",
       fx="10", ppe=36.7, intangibles=4.08):
    return {"GeneralInfo": {"ReportingStartDate": start, "ReportingEndDate": end, "Nature": "Consolidated"},
            "CashFlowFromOperatingActivity": {"OperatingCashFlow": float(cfo)},
            "CashFlowFromInvestingActivity": {"PurchasePropPlantEquipAsInvesting": ppe,
                                              "PurchaseOfIntangibleAssetsAsInvesting": intangibles},
            "CashFlowFromFinancingActivity": {},
            "CashFlowSummary": {"CashFlowOperating": cfo, "CashFlowInvesting": cfi, "CashFlowFinancing": cff,
                                "CashIncreaseDecrease": net, "CashIncreaseDecreaseBeforeExchRate": before,
                                "FinancingEffectOfExchRateOnCash": fx}}


def pl(start="2025-04-01", end="2026-03-31", revenue=2000.0, total_income=None, interest=12.27, puc="10", fv="1",
       kind="Main/Ind", bank=False):
    income = {"Operating": {"RevenueFromOperations": revenue}, "TotalIncome": total_income or revenue + 40}
    if bank:
        income = {"Operating": {"TotalInterestEarned": revenue}, "TotalIncome": revenue}
    return {"GeneralInfo": {"Type": "Banking" if bank else kind, "ReportingStartDate": start, "ReportingEndDate": end,
                            "Nature": "Consolidated"},
            "Income": income, "Expenses": {"Operating": {}, "NonOperating": {"InterestExpense": interest}},
            "PaidUpCapital": puc, "FaceValue": fv}


def ours(*rows):
    return T.OurFinancials([dict(symbol=s, period_end=date.fromisoformat(pe), consolidated=c, period_type=pt,
                                 revenue_from_ops_cr=rv, total_income_cr=None) for s, pe, c, pt, rv in rows])


# ── TC-06 dedupe ─────────────────────────────────────────────────────────────────────────────────────────────

def test_tc06_one_filing_under_four_ids_and_a_one_minute_refile_is_one():
    fl = [filing(2130167, "2025-10-09T23:36:00", quarter="Second quarter"),
          filing(2278805, "2025-10-09T23:37:00", quarter="Second quarter"),
          filing(2130160, "2025-10-09T23:37:00", quarter="Second quarter"),
          filing(2278807, "2025-10-09T23:36:00", quarter="Second quarter")]
    out = T.dedupe(fl)
    assert [f.id for f in out] == [2278805]                   # latest file time, then the highest id


def test_tc06_refile_more_than_45_days_later_is_a_second_period():
    fl = [filing(1, "2025-10-09T23:36:00", quarter="Second quarter"),
          filing(2, "2026-10-08T22:05:59", quarter="Second quarter"),
          filing(3, "2026-10-08T22:05:59", quarter="Second quarter")]
    assert [f.id for f in T.dedupe(fl)] == [1, 3]


def test_tc06_dedupe_is_per_symbol_nature_and_label():
    fl = [filing(1, "2026-04-09T23:40:50", quarter="Yearly"),
          filing(2, "2026-04-09T23:40:50", quarter="Yearly", nature="Standalone"),
          filing(3, "2026-04-09T23:40:50", quarter="Yearly", symbol="BBBB")]
    assert sorted(f.id for f in T.dedupe(fl)) == [1, 2, 3]


# ── TC-07 symbols ────────────────────────────────────────────────────────────────────────────────────────────

def test_tc07_symbol_resolution():
    known = {"M&M", "BBBB", "CCCC"}
    bse = {"500520": "M&M", "500002": "BBBB", "500003": "ZZZZ"}
    assert T.resolve_symbol({"Symbol": "M&amp;M", "scripcode": "500520"}, known, bse) == "M&M"
    assert T.resolve_symbol({"Symbol": None, "scripcode": "500002"}, known, bse) == "BBBB"
    assert T.resolve_symbol({"Symbol": "NOTLISTED", "scripcode": "500002"}, known, bse) == "BBBB"
    assert T.resolve_symbol({"Symbol": "CCCC", "scripcode": ""}, known, bse) == "CCCC"
    assert T.resolve_symbol({"Symbol": "NOTLISTED", "scripcode": "500003"}, known, bse) is None   # mapped, not ours
    assert T.resolve_symbol({"Symbol": "DDDD", "scripcode": "999"}, known, bse) is None
    fl, counts = T.filings_from_records(
        [rec(1, "2026-10-08T22:05:59", symbol="M&amp;M"), rec(2, "2026-10-08T22:06:00", symbol="DDDD"),
         rec(3, "2026-10-08T22:07:00", symbol="CCCC", nature="Odd"), {"id": "x"}], known, bse)
    assert [f.symbol for f in fl] == ["M&M"]
    assert counts == Counter(list_not_our_symbol=1, list_unknown_nature=1, list_bad_id=1)


# ── TC-08 nature ─────────────────────────────────────────────────────────────────────────────────────────────

def test_tc08_consolidated_preferred_standalone_only_without_consolidated():
    fl = [filing(1, symbol="AAAA", nature="Consolidated"), filing(2, symbol="AAAA", nature="Standalone"),
          filing(3, symbol="SOLO", nature="Standalone")]
    assert sorted(f.id for f in T.prefer_consolidated(fl)) == [1, 3]


# ── TC-09 period end ─────────────────────────────────────────────────────────────────────────────────────────

def test_tc09_period_end_rules():
    gi = al()["GeneralInfo"]
    assert T.period_end_of(filing(quarter="Yearly"), gi) == date(2026, 3, 31)
    h1 = al(fy_start="2026-04-01", fy_end="2027-03-31", quarter="Second quarter")["GeneralInfo"]
    assert T.period_end_of(filing(quarter="Second quarter"), h1) == date(2026, 9, 30)
    dec_fy = al(fy_start="2026-01-01", fy_end="2026-12-31", quarter="Second quarter")["GeneralInfo"]
    assert T.period_end_of(filing(quarter="Second quarter"), dec_fy) == date(2026, 6, 30)     # ABB-like
    sme = al(fy_start="2025-04-01", fy_end="2026-03-31", quarter="Half yearly")["GeneralInfo"]
    assert T.period_end_of(filing(quarter="Half yearly", file_time="2025-11-14T18:00:00"), sme) == date(2025, 9, 30)
    assert T.period_end_of(filing(quarter="Half yearly", file_time="2026-05-20T18:00:00"), sme) == date(2026, 3, 31)
    stated = al(reporting_end="2025-09-30")["GeneralInfo"]
    assert T.period_end_of(filing(quarter="Yearly"), stated) == date(2025, 9, 30)             # stated date wins
    assert T.period_end_of(filing(quarter="First quarter"), gi) is None


# ── TC-10..12 units ──────────────────────────────────────────────────────────────────────────────────────────

TCS_OURS = ours(("AAAA", "2026-03-31", True, "annual", 267021.0))


def test_tc10_crore_from_revenue_anchor_tcs_like():
    f = filing(10)
    units, notes = T.infer_units({f.key: [(f, pl(revenue=267021.0, puc="362"))]}, TCS_OURS, {})
    u = units[f.key]
    assert (u.name, u.anchor_capital) == ("crore", 362.0)
    assert u.how == "revenue anchor (annual row) ratio 1"


def test_tc10_lakh_from_four_quarters():
    o = ours(("LAKH", "2025-06-30", True, "quarterly", 100.0), ("LAKH", "2025-09-30", True, "quarterly", 110.0),
             ("LAKH", "2025-12-31", True, "quarterly", 120.0), ("LAKH", "2026-03-31", True, "quarterly", 130.0))
    f = filing(11, symbol="LAKH")
    units, _ = T.infer_units({f.key: [(f, pl(revenue=46000.0))]}, o, {})
    assert units[f.key].name == "lakh"
    assert units[f.key].how.startswith("revenue anchor (sum of 4 quarters) ratio 100")


def test_tc10_four_quarters_must_end_at_fy_end_and_be_consecutive():
    o = ours(("GAP", "2025-03-31", True, "quarterly", 1.0), ("GAP", "2025-09-30", True, "quarterly", 1.0),
             ("GAP", "2025-12-31", True, "quarterly", 1.0), ("GAP", "2026-03-31", True, "quarterly", 1.0))
    assert o.fy_revenue("GAP", True, date(2026, 3, 31)) == (None, "")      # first quarter is a year back: a gap


def test_tc11_radico_like_gross_of_excise_falls_to_share_capital():
    o = ours(("RADX", "2026-03-31", True, "annual", 5000.0))
    f = filing(12, symbol="RADX")
    shares = {"RADX": 13.38e7}                           # 13.38 crore shares
    units, notes = T.infer_units({f.key: [(f, pl(revenue=17375.0, puc="26.76", fv="2"))]}, o, shares)
    assert units[f.key].name == "crore"                  # NOT million (the 3x-tolerance defect of 2 Nov)
    assert units[f.key].how.startswith("share-capital anchor")
    units, notes = T.infer_units({f.key: [(f, pl(revenue=17375.0, puc="26.76", fv="2"))]}, o, {})
    assert f.key not in units and notes[f.key].startswith("revenue anchor mismatch ratio 3.475")


def test_tc11_unit_tolerance_is_1_5x():
    assert T.nearest_unit(1.0) == "crore"
    assert T.nearest_unit(1.49) == "crore"
    assert T.nearest_unit(1.51) is None
    assert T.nearest_unit(3.475) is None
    assert T.nearest_unit(67.0) == "lakh"
    assert T.nearest_unit(66.5) is None
    assert T.nearest_unit(1e7) == "rupee"
    assert T.nearest_unit(0) is None and T.nearest_unit(None) is None


def test_tc12_rounding_text_then_refuse():
    f = filing(13, symbol="NOREF")
    u, why = T.unit_for(f, {}, {}, {"LevelOfRoundingUsedInFinancialStatements": "Lakhs"})
    assert (u.name, u.how) == ("lakh", "filing rounding 'Lakhs'")
    u, why = T.unit_for(f, {}, {}, {"LevelOfRoundingUsedInFinancialStatements": ""})
    assert u is None and why == "no anchor and no rounding text"
    out = T.TransformResult()
    assert T.balance_sheet_offer(filing(13, symbol="NOREF"), al(), None, why, out) is None
    assert out.rejects[0].reason.startswith("unit unknown")


# ── TC-13..15 balance sheet ──────────────────────────────────────────────────────────────────────────────────

CRORE = T.Unit("crore", "revenue anchor (annual row) ratio 1", 10.0)
LAKH = T.Unit("lakh", "revenue anchor (annual row) ratio 100", 1000.0)


def test_tc13_current_liabilities_derived_when_zero():
    out = T.TransformResult()
    o = T.balance_sheet_offer(filing(), al(cl=0.0, liabilities=400.0, ncl=100.0), CRORE, "", out)
    assert o.values["current_liabilities_cr"] == D("300.0")
    assert o.values == {"current_assets_cr": D("600.0"), "current_liabilities_cr": D("300.0"),
                        "inventory_cr": D("50.0"), "trade_receivables_cr": D("200.0"), "trade_payables_cr": D("90.0"),
                        "cash_and_equiv_cr": D("80.0"), "long_term_debt_cr": D("30.0"),
                        "short_term_debt_cr": D("20.0"), "total_equity_cr": D("600.0")}
    assert o.period_end == date(2026, 3, 31) and o.may_insert
    assert "equity_share_capital_cr" not in o.values


def test_tc13_lakh_values_are_converted_to_crore():
    out = T.TransformResult()
    o = T.balance_sheet_offer(filing(), al(assets=123456.0, ca=65432.1, liabilities=23456.0, ncl=3456.0,
                                           equity=100000.0, cap=1000.0, recv=12345.67), LAKH, "", out)
    assert o.values["current_assets_cr"] == D("654.321")
    assert o.values["trade_receivables_cr"] == D("123.4567")
    assert o.values["current_liabilities_cr"] == D("200.0")


def test_tc14_bank_format_is_skipped():
    out = T.TransformResult()
    assert T.balance_sheet_offer(filing(), al(advances=5000.0), CRORE, "", out) is None
    assert out.counts["bs_bank_format_skipped"] == 1 and not out.rejects


@pytest.mark.parametrize("kw,reason", [
    (dict(eq_liab=1100.0), "assets 1000 != equity+liabilities 1100"),
    (dict(ca=1200.0), "current assets > total assets"),
    (dict(recv=700.0), "receivables > current assets"),
    (dict(assets=0.0, eq_liab=0.0), "no total assets"),
])
def test_tc15_balance_sheet_identity_rejections(kw, reason):
    out = T.TransformResult()
    assert T.balance_sheet_offer(filing(), al(**kw), CRORE, "", out) is None
    assert reason in out.rejects[0].reason


def test_tc15_identity_within_1pct_passes():
    out = T.TransformResult()
    assert T.balance_sheet_offer(filing(), al(eq_liab=1009.0), CRORE, "", out) is not None


def test_tc15_capital_guard_unit_change_refused_bonus_allowed():
    out = T.TransformResult()
    assert T.balance_sheet_offer(filing(), al(cap=100.0), CRORE, "", out) is None      # 10x: may be lakh vs crore
    assert "unit may differ" in out.rejects[0].reason
    assert T.balance_sheet_offer(filing(), al(cap=50.0), CRORE, "", out) is not None   # 5x: a 4:1 bonus
    assert T.balance_sheet_offer(filing(), al(cap=2.0), CRORE, "", out) is not None    # 1/5


# ── TC-16 cash flow ──────────────────────────────────────────────────────────────────────────────────────────

def test_tc16_fiscal_year_cash_flow_offer():
    out = T.TransformResult()
    o = T.cash_flow_offer(filing(), cf(), al(), CRORE, "", out)
    assert o.period_end == date(2026, 3, 31)               # header says 01-Jan..31-Mar; values are the FY
    assert o.values == {"cfo_cr": D("520.0"), "cfi_cr": D("-128.0"), "cff_cr": D("-421.0"),
                        "capex_cr": D("-40.78"), "net_change_cash_cr": D("-19.0")}
    assert o.may_insert


@pytest.mark.parametrize("quarter", ["Second quarter", "Half yearly"])
def test_tc16_half_year_cash_flow_is_never_offered(quarter):
    out = T.TransformResult()
    assert T.cash_flow_offer(filing(quarter=quarter), cf(end="2026-09-30"), al(), CRORE, "", out) is None
    assert out.counts["cf_half_year_not_loaded"] == 1


def test_tc15_cash_flow_identity_rejection():
    out = T.TransformResult()
    assert T.cash_flow_offer(filing(), cf(before="-100"), al(), CRORE, "", out) is None
    assert "CFO+CFI+CFF -29 != net change before FX -100" in out.rejects[0].reason
    out = T.TransformResult()
    assert T.cash_flow_offer(filing(), cf(before="-30.5"), al(), CRORE, "", out) is not None   # within 2 units


# ── TC-17 finance costs ──────────────────────────────────────────────────────────────────────────────────────

Q_OURS = ours(("AAAA", "2026-09-30", True, "quarterly", 650.0))


def test_tc17_quarter_finance_costs_offer():
    out = T.TransformResult()
    o = T.finance_cost_offer(filing(quarter="Second quarter"), pl("2026-07-01", "2026-09-30", revenue=655.0,
                                                                  interest=3.21), CRORE, "", Q_OURS, out)
    assert (o.kind, o.period_end, o.values) == ("finance_costs", date(2026, 9, 30), {"finance_costs_cr": D("3.21")})
    assert not o.may_insert


@pytest.mark.parametrize("payload,reason", [
    (pl("2026-04-01", "2026-09-30", revenue=655.0), "is not a single quarter"),
    (pl("2026-07-01", "2026-09-30", revenue=655.0, interest=-1.0), "negative interest expense"),
    (pl("2026-07-01", "2026-09-30", revenue=800.0), "quarter revenue 800.00 cr vs ours 650.00 cr"),
    (pl("2026-04-01", "2026-06-30", revenue=650.0), "no quarter revenue on both sides"),
])
def test_tc17_finance_cost_rejections(payload, reason):
    out = T.TransformResult()
    assert T.finance_cost_offer(filing(quarter="Second quarter"), payload, CRORE, "", Q_OURS, out) is None
    assert reason in out.rejects[0].reason


def test_tc17_bank_pnl_and_missing_field_are_skipped_not_rejected():
    out = T.TransformResult()
    assert T.finance_cost_offer(filing(quarter="Yearly"), pl("2026-01-01", "2026-03-31", bank=True), CRORE, "",
                                Q_OURS, out) is None
    p = pl("2026-07-01", "2026-09-30")
    del p["Expenses"]["NonOperating"]["InterestExpense"]
    assert T.finance_cost_offer(filing(quarter="Second quarter"), p, CRORE, "", Q_OURS, out) is None
    assert out.counts == Counter(fc_bank_format_skipped=1, fc_no_interest_field=1) and not out.rejects


# ── whole pass: build + statements_needed ───────────────────────────────────────────────────────────────────

def test_build_end_to_end_and_latest_filing_wins():
    fy = filing(100, "2026-04-20T18:00:00", quarter="Yearly")
    h1 = filing(200, "2026-10-20T18:00:00", quarter="Second quarter")
    q1 = filing(150, "2026-07-20T18:00:00", quarter="First quarter")
    store = {("pl", 100): pl(revenue=2600.0), ("al", 100): al(), ("cf", 100): cf(),
             ("al", 200): al(fy_start="2026-04-01", fy_end="2027-03-31", quarter="Second quarter"),
             ("cf", 200): cf(start="2026-04-01", end="2026-09-30"),
             ("plq", 100): pl("2026-01-01", "2026-03-31", revenue=640.0, interest=3.0),
             ("plq", 150): {T.EMPTY_KEY: "EMPTY_RESPONSE: There is no row at position 0."}}
    o = ours(("AAAA", "2026-03-31", True, "annual", 2600.0), ("AAAA", "2026-03-31", True, "quarterly", 640.0))
    res = T.build([fy, q1, h1], [fy, q1, h1], lambda k, i: store.get((k, i)), o, {})
    kinds = sorted((x.kind, x.period_end.isoformat()) for x in res.offers)
    assert kinds == [("balance_sheet", "2026-03-31"), ("balance_sheet", "2026-09-30"), ("cash_flow", "2026-03-31"),
                     ("finance_costs", "2026-03-31")]
    assert res.counts["cf_half_year_not_loaded"] == 1 and res.counts["fc_empty"] == 1
    assert res.counts["fc_not_fetched"] == 1                  # the H1 filing's quarter P&L was never fetched
    later = [T.Offer("balance_sheet", "A", date(2026, 3, 31), True, "Yearly", i, t, "crore", "", {"x": D(1)})
             for i, t in ((5, "2026-04-20T10:00:00"), (4, "2026-06-20T10:00:00"))]
    c = Counter()
    assert T.latest_per_key(later, c)[0].filing_id == 4 and c["superseded_by_later_filing"] == 1


def test_statements_needed_order_largest_first_finance_costs_last():
    a_fy, a_h1 = filing(1, "2026-04-20T10:00:00", "AAAA"), filing(2, "2026-10-20T10:00:00", "AAAA", "Second quarter")
    b_fy, b_q1 = filing(3, "2026-04-21T10:00:00", "BBBB"), filing(4, "2026-07-21T10:00:00", "BBBB", "First quarter")
    need = T.statements_needed([a_h1, b_q1], [a_fy, a_h1, b_fy, b_q1], rank={"BBBB": 0, "AAAA": 1})
    assert need == [("pl", 3), ("pl", 1), ("al", 2), ("cf", 2), ("plq", 4), ("plq", 2)]
    assert ("plq", 4) not in T.statements_needed([a_h1, b_q1], [a_fy, b_fy], finance_costs=False)


# ── plan rules (TC-18..21 logic; the same plan is executed against Postgres in the PG tests) ─────────────────

def row(table, symbol="AAAA", pe="2026-03-31", cons=True, ptype="quarterly", source="trendlyne_mcp", **vals):
    cols = P.Q_COLUMNS if table == P.QUARTERLY else T.CF_COLUMNS
    return P.Row(table, symbol, date.fromisoformat(pe), cons, ptype, source, {c: vals.get(c) for c in cols})


def bs_offer(pe="2026-03-31", quarter="Yearly", **vals):
    return T.Offer("balance_sheet", "AAAA", date.fromisoformat(pe), True, quarter, 9, "t", "crore", "how",
                   vals or {"current_assets_cr": D("600"), "total_equity_cr": D("700")}, may_insert=quarter == "Yearly")


def test_plan_balance_sheet_fills_only_nulls_on_every_row_of_the_date():
    q = [row(P.QUARTERLY, ptype="quarterly", total_equity_cr=D("1")),
         row(P.QUARTERLY, ptype="annual", source="screener_in_annual")]
    plan = P.build_plan([bs_offer()], q, [])
    got = {(a.period_type, a.op): a.values for a in plan.actions}
    assert got == {("annual", "fill"): {"current_assets_cr": D("600"), "total_equity_cr": D("700")},
                   ("quarterly", "fill"): {"current_assets_cr": D("600")}}       # equity already set: untouched


def test_plan_insert_only_fy_without_any_row_half_year_never():
    plan = P.build_plan([bs_offer(), bs_offer("2026-09-30", "Second quarter")], [], [])
    assert [(a.op, a.period_type, a.row_source, a.period_end.isoformat()) for a in plan.actions] == \
        [("insert", "annual", "truedata", "2026-03-31")]
    assert plan.counts["balance_sheet_half_year_no_row"] == 1


def test_plan_cash_flow_insert_or_fill_nulls():
    off = T.Offer("cash_flow", "AAAA", date(2026, 3, 31), True, "Yearly", 9, "t", "crore", "how",
                  {"cfo_cr": D("5"), "capex_cr": D("-1")}, may_insert=True)
    assert [a.op for a in P.build_plan([off], [], []).actions] == ["insert"]
    plan = P.build_plan([off], [], [row(P.CASHFLOW, ptype="annual", source="yahoo_finance", cfo_cr=D("4"))])
    assert [(a.op, a.values) for a in plan.actions] == [("fill", {"capex_cr": D("-1")})]


def test_plan_finance_costs_only_null_quarterly_rows():
    off = T.Offer("finance_costs", "AAAA", date(2026, 3, 31), True, "Yearly", 9, "t", "crore", "how",
                  {"finance_costs_cr": D("3")})
    q = [row(P.QUARTERLY, ptype="quarterly"), row(P.QUARTERLY, ptype="annual", source="screener_in_annual")]
    plan = P.build_plan([off], q, [])
    assert [(a.period_type, a.values) for a in plan.actions] == [("quarterly", {"finance_costs_cr": D("3")})]
    plan = P.build_plan([off], [row(P.QUARTERLY, finance_costs_cr=D("2"))], [])
    assert not plan.actions and plan.counts["finance_costs_already_set"] == 1
    plan = P.build_plan([off], [], [])
    assert not plan.actions and plan.counts["finance_costs_no_quarterly_row"] == 1
