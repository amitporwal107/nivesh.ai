"""services/fno_oi_reconcile.py: the seven OI checks, worked by hand on HDFCAMC's real figures of 2 and 3 Nov 2026
(nidp.fno_bhavcopy, lot 300). Test cases: test_reports/fno_oi_reconcile_TESTCASES.md (TC-1 .. TC-19)."""
from __future__ import annotations

import copy

from scripts.reconcile_fno_oi import previous_session
from services import fno_oi_reconcile as rc

D, P, NOV, DEC = "2026-11-03", "2026-11-02", "2026-11-23", "2026-12-29"


def bhav(expiry, kind, strike, oi, chg, lot=300):
    return {"expiry_date": expiry, "option_type": kind, "strike_price": strike if kind != "FUT" else 0,
            "open_interest": oi, "change_in_oi": chg, "new_board_lot_qty": lot}


TODAY = [
    bhav(NOV, "PE", 2420, 17100, 16200), bhav(NOV, "CE", 2420, 32100, 7500), bhav(NOV, "PE", 2480, 300, 300),
    bhav(NOV, "CE", 2400, 101100, -27300), bhav(NOV, "FUT", None, 6889200, -117300),
    bhav(DEC, "FUT", None, 364200, 3000), bhav(DEC, "CE", 2420, 600, 0),
]
PREV = [
    bhav(NOV, "PE", 2420, 900, 0), bhav(NOV, "CE", 2420, 24600, 0), bhav(NOV, "CE", 2400, 128400, 0),
    bhav(NOV, "FUT", None, 7006500, 0), bhav(DEC, "FUT", None, 361200, 0), bhav(DEC, "CE", 2420, 600, 0),
]


def side(oi, chg):
    return {"oi": oi, "change_in_oi": chg}


def chains():
    return {
        NOV: {"lot_size": 300, "strike_count": 3, "strikes_returned": 3,
              "summary": {"total_call_oi": 133200, "total_put_oi": 17400, "total_call_oi_change": -19800, "total_put_oi_change": 16500},
              "strikes": [{"strike": 2400, "call": side(101100, -27300), "put": None},
                          {"strike": 2420, "call": side(32100, 7500), "put": side(17100, 16200)},
                          {"strike": 2480, "call": None, "put": side(300, 300)}]},
        DEC: {"lot_size": 300, "strike_count": 1, "strikes_returned": 1,
              "summary": {"total_call_oi": 600, "total_put_oi": 0, "total_call_oi_change": 0, "total_put_oi_change": 0},
              "strikes": [{"strike": 2420, "call": side(600, 0), "put": None}]},
    }


FUTURES = {"as_of": D, "futures": [{"expiry": NOV, "oi": 6889200, "change_in_oi": -117300},
                                   {"expiry": DEC, "oi": 364200, "change_in_oi": 3000}]}


def by_status(findings, check, status):
    return [f for f in findings if f["check"] == check and f["status"] == status]


# ── C1 previous-day closing OI ───────────────────────────────────────────────

def test_tc1_previous_oi_matches():
    f = rc.check_previous_oi(rc.chain_items(chains()), rc.bhav_book(PREV), "chain")
    pe = next(x for x in f if x["item"] == f"{NOV} 2420 PE")
    assert pe["status"] == rc.PASS and pe["expected"] == 900 and pe["actual"] == 900


def test_tc2_previous_oi_mismatch_is_a_fail_with_the_diff():
    prev = copy.deepcopy(PREV)
    prev[0]["open_interest"] = 1200
    pe = next(x for x in rc.check_previous_oi(rc.chain_items(chains()), rc.bhav_book(prev), "chain") if x["item"] == f"{NOV} 2420 PE")
    assert pe["status"] == rc.FAIL and pe["expected"] == 1200 and pe["actual"] == 900 and pe["diff"] == -300


def test_tc3_new_contract_previous_is_zero():
    f = rc.check_previous_oi(rc.chain_items(chains()), rc.bhav_book(PREV), "chain")
    new = next(x for x in f if x["item"] == f"{NOV} 2480 PE")
    assert new["status"] == rc.PASS and new["expected"] == 0 and "not listed" in new["note"]
    chg = next(x for x in rc.check_change(rc.chain_items(chains()), rc.bhav_book(TODAY), rc.bhav_book(PREV), "chain")
               if x["item"] == f"{NOV} 2480 PE")
    assert chg["status"] == rc.PASS and chg["expected"] == 300


# ── C2 current closing OI ────────────────────────────────────────────────────

def test_tc4_app_oi_not_the_bhavcopy_fails():
    ch = chains()
    ch[NOV]["strikes"][1]["call"]["oi"] = 32400
    f = rc.check_close_oi(rc.chain_items(ch), rc.bhav_book(TODAY), "chain")
    ce = next(x for x in f if x["item"] == f"{NOV} 2420 CE")
    assert ce["status"] == rc.FAIL and ce["expected"] == 32100 and ce["actual"] == 32400


def _options(bars_by_contract, series=(), missing=()):
    contracts = [{"tradingsymbol": f"X{k}{t}", "strike": float(k), "type": t, "bars": b} for (k, t), b in bars_by_contract.items()]
    return {"availability": "ok", "expiry": NOV, "contracts": contracts, "series": list(series), "missing": list(missing)}


def test_tc5_kite_last_candle_vs_bhavcopy():
    opts = _options({(2420, "CE"): [[f"{D}T15:15:00+05:30", 0, 0, 0, 0, 1, 32100], [f"{D}T15:30:00+05:30", 0, 0, 0, 0, 1, 31800]],
                     (2420, "PE"): [[f"{P}T15:15:00+05:30", 0, 0, 0, 0, 1, 900], [f"{D}T15:30:00+05:30", 0, 0, 0, 0, 1, 17100]]})
    last, none, reason = rc.kite_last_on_day(None, opts, D)
    assert reason is None and not none
    f = rc.check_kite_close(last, none, reason, rc.bhav_book(TODAY), D)
    ce = next(x for x in f if x["item"] == f"{NOV} 2420 CE")
    pe = next(x for x in f if x["item"] == f"{NOV} 2420 PE")
    assert ce["status"] == rc.FAIL and ce["diff"] == -300 and ce["source"] == "kite" and "15:30" in ce["note"]
    assert pe["status"] == rc.PASS


def test_tc6_no_kite_candle_on_the_day_is_not_comparable():
    opts = _options({(2480, "PE"): [[f"{P}T15:15:00+05:30", 0, 0, 0, 0, 1, 0]]}, missing=["XNOV2520PE"])
    last, none, reason = rc.kite_last_on_day(None, opts, D)
    f = rc.check_kite_close(last, none, reason, rc.bhav_book(TODAY), D)
    assert not by_status(f, "C2", rc.PASS) and len(by_status(f, "C2", rc.SKIP)) == 2


def test_tc6_a_contract_listed_and_missing_counts_once():
    # staging 3 Nov: options/intraday sent HDFCAMC26NOV2520PE in `contracts` (no bars) AND in `missing`
    opts = _options({(2520, "PE"): []}, missing=["X2520PE"])
    last, none, _ = rc.kite_last_on_day(None, opts, D)
    assert none == [f"{NOV} 2520 PE"]
    t1 = f"{D}T09:15:00+05:30"
    opts = _options({(2420, "CE"): [[t1, 0, 0, 0, 0, 1, 100]], (2520, "PE"): []}, series=[_row(t1, None, None, None, None)],
                    missing=["X2520PE"])
    (w,) = rc.check_options_series(opts)
    assert w["status"] == rc.WARN and "of 2 contracts" in w["note"]


def test_tc6_kite_unavailable_is_a_skip_with_the_reason():
    last, none, reason = rc.kite_last_on_day({"mode": "eod", "kite_reason": "token_expired"}, {"availability": "token_expired"}, D)
    f = rc.check_kite_close(last, none, reason, rc.bhav_book(TODAY), D)
    assert [x["status"] for x in f] == [rc.SKIP] and "token_expired" in f[0]["note"]


# ── C3 OI change ─────────────────────────────────────────────────────────────

def test_tc7_change_is_today_minus_previous():
    f = rc.check_change(rc.chain_items(chains()) + rc.futures_items(FUTURES), rc.bhav_book(TODAY), rc.bhav_book(PREV), "app")
    assert not by_status(f, "C3", rc.FAIL)
    ch = chains()
    ch[NOV]["strikes"][0]["call"]["change_in_oi"] = -27000
    bad = by_status(rc.check_change(rc.chain_items(ch), rc.bhav_book(TODAY), rc.bhav_book(PREV), "chain"), "C3", rc.FAIL)
    assert [x["item"] for x in bad] == [f"{NOV} 2400 CE"] and bad[0]["expected"] == -27300


def test_tc7_source_change_column_against_stored_previous_day():
    today = copy.deepcopy(TODAY)
    today[4]["change_in_oi"] = -100000          # NSE's column disagrees with the stored previous day
    bad = by_status(rc.check_source_change(rc.bhav_book(today), rc.bhav_book(PREV)), "C3", rc.FAIL)
    assert [x["item"] for x in bad] == [f"{NOV} FUT"] and bad[0]["expected"] == -117300


# ── C4 OI change % ───────────────────────────────────────────────────────────

def _pct(item):
    f = rc.check_change_pct(rc.chain_items(chains()), rc.bhav_book(TODAY), rc.bhav_book(PREV), 300, "chain")
    return next(x for x in f if x["item"] == item)


def test_tc8_small_base_is_a_true_but_misleading_warn():
    x = _pct(f"{NOV} 2420 PE")
    assert x["status"] == rc.WARN and x["expected"] == 1800.0 and x["actual"] == 1800.0
    assert "3 lots -> 57 lots" in x["note"]


def test_tc9_new_contract_has_no_percent():
    x = _pct(f"{NOV} 2480 PE")
    assert x["status"] == rc.PASS and x.get("expected") is None and x.get("actual") is None and "new contract" in x["note"]


def test_tc10_large_base_is_a_plain_pass():
    x = _pct(f"{NOV} 2400 CE")
    assert x["status"] == rc.PASS and x["expected"] == -21.3 and x["actual"] == -21.3 and "note" not in x


def test_screen_pct_is_the_frontend_formula():
    assert rc.screen_pct(17100, 16200) == 1800.0
    assert rc.screen_pct(300, 300) is None          # previous 0: the screen shows a dash
    assert round(rc.screen_pct(101100, -27300), 1) == -21.3


# ── C5 intraday OI change ────────────────────────────────────────────────────

def _buildup(windows):
    return {"mode": "intraday", "contracts": [{"slot": "current", "expiry": NOV, "windows": windows, "bars": [], "daily_bars": []}]}


def test_tc11_window_change_is_the_oi_difference():
    ws = [{"start": f"{D}T09:15", "oi": 100, "oi_change": -5}, {"start": f"{D}T10:15", "oi": 90, "oi_change": -10},
          {"start": f"{D}T11:15", "oi": 95, "oi_change": 5}]
    assert [x["status"] for x in rc.check_intraday_windows(_buildup(ws)) if x["check"] == "C5"] == [rc.PASS]
    ws[2]["oi_change"] = 4
    bad = by_status(rc.check_intraday_windows(_buildup(ws)), "C5", rc.FAIL)
    assert len(bad) == 1 and bad[0]["expected"] == 5 and bad[0]["actual"] == 4


def _row(t, ce, pe, dce, dpe):
    return {"t": t, "ce_oi": ce, "pe_oi": pe, "ce_oi_change": dce, "pe_oi_change": dpe}


def test_tc12_options_sums_and_changes():
    t1, t2 = f"{D}T09:15:00+05:30", f"{D}T09:30:00+05:30"
    opts = _options({(2420, "CE"): [[t1, 0, 0, 0, 0, 1, 100], [t2, 0, 0, 0, 0, 1, 130]],
                     (2440, "CE"): [[t1, 0, 0, 0, 0, 1, 50], [t2, 0, 0, 0, 0, 1, 40]],
                     (2420, "PE"): [[t1, 0, 0, 0, 0, 1, 70], [t2, 0, 0, 0, 0, 1, 90]]},
                    series=[_row(t1, 150, 70, None, None), _row(t2, 170, 90, 20, 20)])
    f = rc.check_options_series(opts)
    assert [x["status"] for x in f] == [rc.PASS]
    opts["series"][1]["ce_oi"] = 171
    assert by_status(rc.check_options_series(opts), "C5", rc.FAIL)


def test_tc13_all_null_pane_is_a_warn_naming_the_contracts():
    t1, t2 = f"{D}T09:15:00+05:30", f"{D}T09:30:00+05:30"
    opts = _options({(2420, "CE"): [[t1, 0, 0, 0, 0, 1, 100], [t2, 0, 0, 0, 0, 1, 130]],
                     (2420, "PE"): [[t2, 0, 0, 0, 0, 1, 90]]},
                    series=[_row(t1, None, None, None, None), _row(t2, None, None, None, None)], missing=["XNOV2520PE"])
    f = rc.check_options_series(opts)
    assert [x["status"] for x in f] == [rc.WARN]
    assert "XNOV2520PE" in f[0]["note"] and "X2420PE" in f[0]["note"] and "4 of 4" in f[0]["note"]


# ── C6 chart totals vs the chain ─────────────────────────────────────────────

def test_tc14_chain_summary_totals_equal_the_bhavcopy():
    f = rc.check_chain_totals(chains(), rc.bhav_book(TODAY))
    assert not by_status(f, "C6", rc.FAIL) and len(f) == 8
    ch = chains()
    ch[NOV]["summary"]["total_put_oi"] = 17000
    bad = by_status(rc.check_chain_totals(ch, rc.bhav_book(TODAY)), "C6", rc.FAIL)
    assert [x["item"] for x in bad] == [f"{NOV} chain summary total_put_oi"] and bad[0]["expected"] == 17400


def _consolidated():
    return {"expiries": [NOV, DEC],
            "strikes": [{"strike": 2420, "call": side(32700, 7500), "put": side(17100, 16200)}],
            "summary": {"total_call_oi": 133800, "total_put_oi": 17400, "total_call_oi_change": -19800, "total_put_oi_change": 16500}}


def test_tc15_consolidated_is_the_sum_of_the_expiries():
    f = rc.check_consolidated(_consolidated(), chains())
    assert not by_status(f, "C6", rc.FAIL) and by_status(f, "C6", rc.PASS)
    c = _consolidated()
    c["strikes"][0]["call"]["oi"] = 32100           # the December 600 left out
    bad = by_status(rc.check_consolidated(c, chains()), "C6", rc.FAIL)
    assert len(bad) == 1 and bad[0]["expected"] == 32700


def test_tc16_chart_futures_pane_equals_the_futures_route():
    b = {"mode": "intraday", "contracts": [
        {"slot": "current", "expiry": NOV, "daily_bars": [[P, 1, 1, 7006500, -76200, NOV], [D, 1, 1, 6889200, -117300, NOV]]},
        {"slot": "next", "expiry": DEC, "daily_bars": [[P, 1, 1, 361200, 0, DEC], [D, 1, 1, 364200, 3000, DEC]]}],
        "consolidated": {"slot": "consolidated", "daily_bars": [[P, 1, 1, 7367700, 0, NOV], [D, 1, 1, 7253400, -114300, NOV]]}}
    f = rc.check_chart_futures(b, FUTURES)
    assert [x["status"] for x in f] == [rc.PASS, rc.PASS, rc.PASS]
    assert [x["status"] for x in rc.check_chart_close(b, rc.bhav_book(TODAY), D)] == [rc.PASS, rc.PASS]
    assert [x["status"] for x in rc.check_chart_change(b, rc.bhav_book(TODAY), rc.bhav_book(PREV), D)] == [rc.PASS, rc.PASS]


# ── C7 segments sum to the net movement ──────────────────────────────────────

OCT = "2026-10-27"
CURRENT_ROLL = [["2026-10-26", 1, 1, 1131000, -1513800, OCT], ["2026-10-27", 1, 1, 650100, -480900, OCT],
                ["2026-10-28", 1, 1, 7226700, 21300, NOV], ["2026-10-29", 1, 1, 7169700, -57000, NOV]]
CONSOLIDATED = [["2026-10-26", 1, 1, 7923600, 51600, OCT], ["2026-10-27", 1, 1, 8214300, 290700, OCT],
                ["2026-10-28", 1, 1, 7586100, -628200, NOV], ["2026-10-29", 1, 1, 7534500, -51600, NOV]]


def test_tc17_a_roll_is_never_a_bar():
    g = rc.segments(CURRENT_ROLL)
    assert g["net"] == 7169700 - 1131000
    assert g["increases"] + g["decreases"] == -480900 + 21300 - 57000
    assert g["rolls"] == [{"day": "2026-10-28", "from": OCT, "to": NOV, "jump": 6555300}]
    assert g["unexplained"] == 0
    b = {"contracts": [{"slot": "current", "expiry": NOV, "daily_bars": CURRENT_ROLL}]}
    (x,) = rc.check_daily_segments(b)
    assert x["status"] == rc.FAIL and "1 contract roll(s) worth +6,555,300" in x["note"]


def test_tc18_consolidated_segments_add_up():
    b = {"contracts": [], "consolidated": {"slot": "consolidated", "daily_bars": CONSOLIDATED}}
    (x,) = rc.check_daily_segments(b)
    assert x["status"] == rc.PASS and x["expected"] == x["actual"] == 7534500 - 7923600


# ── run, roll-up, exit code ──────────────────────────────────────────────────

def test_tc19_roll_up_and_exit_code():
    f = [rc.finding("C1", rc.PASS, "a"), rc.finding("C4", rc.WARN, "b"), rc.finding("C4", rc.PASS, "c"),
         rc.finding("C7", rc.FAIL, "d"), rc.finding("C7", rc.PASS, "e")]
    s = rc.summarise(f)
    assert s["C1"]["status"] == rc.PASS and s["C4"]["status"] == rc.WARN and s["C7"]["status"] == rc.FAIL
    assert s["C2"]["status"] == rc.SKIP and s["C2"]["counts"][rc.SKIP] == 0       # nothing compared is never a pass
    assert rc.overall(s) == rc.FAIL
    assert rc.exit_code([{"status": rc.FAIL}]) == 3 and rc.exit_code([{"status": rc.WARN}, {"status": rc.PASS}]) == 0


def test_run_end_to_end_on_the_fixture():
    r = rc.run("HDFCAMC", D, P, TODAY, PREV, chains(), _consolidated(), FUTURES, None, None)
    assert r["checks"]["C1"]["status"] == rc.PASS and r["checks"]["C3"]["status"] == rc.PASS
    assert r["checks"]["C4"]["status"] == rc.WARN and r["checks"]["C6"]["status"] == rc.PASS
    assert "HDFCAMC  2026-11-02 -> 2026-11-03" in rc.render(r)


def test_run_without_the_previous_day_skips_c1_c3_c4():
    r = rc.run("HDFCAMC", D, None, TODAY, None, chains(), None, FUTURES, None, None)
    for c in ("C1", "C3", "C4"):
        assert r["checks"][c]["status"] == rc.SKIP and "no previous session" in r["checks"][c]["examples"][0]["note"]


def test_previous_session_is_the_day_before_in_the_data():
    b = {"contracts": [{"daily_bars": [["2026-10-30", 0, 0, 0, 0, NOV], [P, 0, 0, 0, 0, NOV], [D, 0, 0, 0, 0, NOV]]}]}
    assert previous_session(b, D) == P and previous_session(b, "2026-10-30") is None and previous_session(None, D) is None
