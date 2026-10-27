"""Results week (Earnings Surprise & Guidance Tracker P1) — TC-B1 … TC-B14 of docs/EARNINGS_SURPRISE_TRACKER.md §8, plus
the coming-months OI block and the expiry-week dampening (§4c). TC-B12 (universe_for) lives in test_positional_engine.py
and the results signal in the AI scanner (§4d) in test_results_signal.py.

No network and no database: DaaS (loaders.daas_get), Mongo (a fake collection), the app Postgres pool and the NSE
session calendar are stubbed. Every fixture is MOCK — not real data — unless it says "copied from staging" with a date.
"""
from __future__ import annotations

import asyncio
import copy
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from routes import results_week as route
from scripts import build_results_week as job
from services.results_week import build, loaders, scoring as sc, store

IST = sc.IST
DAY = date(2026, 10, 27)                 # a Tuesday


def run(coro):
    return asyncio.run(coro)


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def weekdays(start: date, end: date) -> List[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]


SESSIONS = weekdays(date(2026, 4, 1), date(2026, 11, 30))    # MOCK calendar: every weekday a session


@pytest.fixture(autouse=True)
def _clean():
    loaders.clear_cache()
    route._live.clear()
    route._building.clear()
    yield
    loaders.clear_cache()


def metric(key, low, mid, high, filed=None, reliable=True, at="2026-10-26T15:29:10+00:00"):
    return {"key": key, "unit": "₹ crore", "expected": None if mid is None else {"low": low, "mid": mid, "high": high},
            "filed": None if filed is None else {"value": filed, "broadcast_at": at}, "vs_mid_pct": None,
            "within_band": None, "reliable": reliable, "note": "MOCK"}


# ── TC-B1 z and the verdict at the band edges ─────────────────────────────────────────────────────────────────────

def test_b1_z_and_verdict_at_band_edges():
    # MOCK band 90–100–110 (half-width 0.10, rated for PAT and revenue)
    assert sc.z_score(110, 90, 100, 110) == 1.0
    assert sc.metric_verdict(1.0) == ("in_line", None)
    assert sc.metric_verdict(1.01) == ("above", None)
    assert sc.metric_verdict(-1.0) == ("in_line", None)
    assert sc.metric_verdict(-2.0) == ("below", "well_below")
    assert sc.metric_verdict(2.0) == ("above", "outstanding")
    assert sc.z_score(80, 90, 100, 110) == -2.0
    r = sc.rate_metric("pat", metric("pat", 90, 100, 110, filed=110.1))
    assert r["z"] == 1.01 and r["verdict"] == "above" and abs(r["score"] - 75.25) <= 0.05        # 50 + 25 × 1.01
    assert sc.component_score(3.0) == 100.0 and sc.component_score(-3.0) == 0.0


# ── TC-B2 unreliable / missing baseline → null with the reason, never "in line" ──────────────────────────────────

@pytest.mark.parametrize("m", [metric("pat", 90, 100, 110, filed=100, reliable=False), metric("pat", None, None, None, filed=100)])
def test_b2_no_reliable_baseline_is_not_rated(m):
    s = sc.surprise([m, metric("revenue", None, None, None, filed=500, reliable=False)])
    assert s["verdict"] == {"label": None, "intensity": None, "reason": "not rated: no reliable baseline"}
    assert s["value"] is None and s["used"] == []


# ── TC-B3 bank (revenue null) → PAT only; revenue only when PAT is unreliable ────────────────────────────────────

def test_b3_pat_only_for_a_bank_and_revenue_only_without_a_pat_baseline():
    bank = sc.surprise([metric("revenue", None, None, None, reliable=False), metric("pat", 90, 100, 110, filed=105)])
    assert bank["used"] == ["pat"] and bank["weights"] == {"pat": 1.0} and bank["value"] == 62.5
    assert bank["verdict"]["label"] == "in_line" and bank["verdict"]["reason"].startswith("PAT only")
    rev = sc.surprise([metric("revenue", 900, 1000, 1100, filed=1150), metric("pat", None, None, None, reliable=False)])
    assert rev["used"] == ["revenue"] and rev["verdict"]["label"] == "above" and rev["verdict"]["reason"].startswith("revenue only")
    both = sc.surprise([metric("revenue", 900, 1000, 1100, filed=1100), metric("pat", 90, 100, 110, filed=90)])
    # 0.6 × S(−1) + 0.4 × S(1) = 0.6 × 25 + 0.4 × 75 = 45; weighted z = 0.6 × −1 + 0.4 × 1 = −0.2 → in line
    assert both["value"] == 45.0 and both["z"] == -0.2 and both["verdict"]["label"] == "in_line"


# ── TC-B4 missing components renormalise; coverage names them; no surprise and no trend → null ───────────────────

def test_b4_composite_renormalises_and_needs_a_surprise_or_a_trend():
    c = sc.composite({"surprise": 80.0, "trend": None, "outlook": 60.0, "quality": 100.0})
    assert c["coverage"] == {"present": ["surprise", "outlook", "quality"], "missing": ["trend"]}
    assert c["value"] == round((35 * 80 + 25 * 60 + 15 * 100) / 75, 1) == 77.3 and c["band"] == "above"
    none = sc.composite({"surprise": None, "trend": None, "outlook": 90.0, "quality": 100.0})
    assert none["value"] is None and none["band"] is None and none["coverage"]["missing"] == ["surprise", "trend"]
    assert sc.band_of(69.9) == "in_line" and sc.band_of(70.0) == "above" and sc.band_of(44.9) == "below"


# ── TC-B5 quality flags at their thresholds; cash flow not checked ───────────────────────────────────────────────

def q_rows(*, pbt=100.0, exc=None, oi=None, tax=None, pat=50.0, rev=1000.0, pat4=40.0, rev4=900.0, oi4=None):
    """MOCK: the 2026-09-30 quarter and the one a year earlier."""
    t = {"period_end": "2026-09-30", "pbt_cr": pbt, "exceptional_items_cr": exc, "other_income_cr": oi, "tax_expense_cr": tax,
         "pat_cr": pat, "revenue_from_ops_cr": rev}
    t4 = {"period_end": "2025-09-30", "pat_cr": pat4, "revenue_from_ops_cr": rev4, "other_income_cr": oi4}
    return [t, t4]


@pytest.mark.parametrize("kw,code,flagged", [
    ({"exc": 20.0}, "exceptional_items", False), ({"exc": 20.1}, "exceptional_items", True), ({"exc": -25.0}, "exceptional_items", True),
    ({"oi": 30.0}, "other_income", False), ({"oi": 30.1}, "other_income", True),
    ({"tax": 10.0}, "tax_rate", False), ({"tax": 9.9}, "tax_rate", True), ({"tax": 40.0}, "tax_rate", False), ({"tax": 40.1}, "tax_rate", True),
])
def test_b5_quality_flags_fire_at_their_thresholds(kw, code, flagged):
    q = sc.quality(q_rows(**kw), date(2026, 9, 30))
    assert code in q["checked"]
    assert any(f["code"] == code for f in q["flags"]) is flagged
    assert "cash_flow: not stored" in q["not_checked"]


def test_b5_profit_outrunning_revenue_with_other_income_rising_and_unchecked_figures():
    # PAT +50 % vs revenue +11.1 % with other income 10 → 20: flagged; the same with other income falling: not
    q = sc.quality(q_rows(pat=60.0, pat4=40.0, oi=20.0, oi4=10.0), date(2026, 9, 30))
    assert [f["code"] for f in q["flags"]] == ["profit_vs_revenue"] and q["value"] == 75.0
    q2 = sc.quality(q_rows(pat=60.0, pat4=40.0, oi=5.0, oi4=10.0), date(2026, 9, 30))
    assert q2["flags"] == [] and q2["value"] == 100.0
    none = sc.quality(q_rows(pbt=-5.0), date(2026, 9, 30))
    assert "exceptional_items: not stored" in none["not_checked"] and "tax_rate: not stored" in none["not_checked"]
    loss = sc.quality(q_rows(pbt=-5.0, exc=1.0), date(2026, 9, 30))
    assert "exceptional_items: PBT not positive" in loss["not_checked"]
    nothing = sc.quality([], date(2026, 9, 30))
    assert nothing["value"] is None and nothing["checked"] == []


# ── TC-B6 reaction: after 15:30 IST → the next session; excess vs Nifty by hand ──────────────────────────────────

def test_b6_first_session_follows_the_1530_rule():
    ss = SESSIONS
    assert sc.first_session(utc(2026, 10, 26, 15, 29), ss) == date(2026, 10, 27)       # 20:59 IST, after the close
    assert sc.first_session(utc(2026, 10, 26, 9, 59), ss) == date(2026, 10, 26)        # 15:29 IST, before it
    assert sc.first_session(utc(2026, 10, 26, 10, 0), ss) == date(2026, 10, 27)        # 15:30 IST exactly: after
    assert sc.first_session(utc(2026, 10, 24, 6, 0), ss) == date(2026, 10, 26)         # a Saturday → Monday


def test_b6_excess_return_and_volume_by_hand():
    # MOCK: stock 100 → 104.47 on 27 Oct at 3,000 shares vs 20 earlier sessions of 1,000; Nifty 22,600 → 22,753.2
    days = [d for d in SESSIONS if d <= date(2026, 10, 27)][-21:]
    bars = {d: (100.0, 1000.0) for d in days[:-1]}
    bars[days[-1]] = (104.47, 3000.0)
    nifty = {days[-2]: 22600.0, days[-1]: 22753.2}
    r, gap = sc.reaction(utc(2026, 10, 26, 15, 29), SESSIONS, bars, nifty)
    assert gap is None and r["first_session"] == "2026-10-27" and r["filed_after_close"] is True
    # 4.47 − (22753.2 / 22600 − 1) × 100 = 4.47 − 0.6779 = 3.7921
    assert r["stock_return_pct"] == 4.47 and r["nifty_return_pct"] == 0.68 and r["excess_pct"] == 3.79
    assert r["volume_x"] == 3.0 and r["score"] == 100.0          # 50 + 10 × 3.79 × 2 (volume weight capped at 2)
    none, why = sc.reaction(utc(2026, 10, 26, 15, 29), SESSIONS, {d: v for d, v in bars.items() if d != days[-1]}, nifty)
    assert none is None and "no close for 2026-10-27 yet" in why


# ── TC-B7 OI: the four states, small moves, total OI not the near month, non-F&O → null ──────────────────────────

@pytest.mark.parametrize("price,oi,state", [
    (1.0, 3.0, "long_buildup"), (-1.0, 3.0, "short_buildup"), (1.0, -3.0, "short_covering"), (-1.0, -3.0, "long_unwinding"),
    (0.49, 10.0, "no_clear_signal"), (2.0, 1.99, "no_clear_signal"), (0.5, 2.0, "long_buildup"), (None, 3.0, None),
    (0.16, 3.50, "no_clear_signal"),           # BAJAJ-AUTO 26 Oct, near-month price / total OI (coordinator, staging warehouse)
])
def test_b7_states_need_both_moves_past_the_thresholds(price, oi, state):
    assert sc.oi_state(price, oi) == state


# Copied from staging 2026-10-27 (DaaS /fno/MANKIND?on=2026-10-26&instrument_type=STF): the expiring October contract
# lost 959,500 OI on the roll while total OI rose.
MANKIND_STF_20261026 = [
    {"expiry_date": "2026-10-27", "close_price": 2316.7, "prev_close_price": 2214.0, "underlying_price": 2311.65, "open_interest": 639000, "change_in_oi": -959500},
    {"expiry_date": "2026-11-23", "close_price": 2329.6, "prev_close_price": 2221.0, "underlying_price": 2311.65, "open_interest": 3190500, "change_in_oi": 1298500},
    {"expiry_date": "2026-12-29", "close_price": 2334.9, "prev_close_price": 2233.4, "underlying_price": 2311.65, "open_interest": 17750, "change_in_oi": -2000},
]
MANKIND_SCAN_20261026 = {"symbol": "MANKIND", "near_expiry": "2026-10-27", "oi": 3847250, "oi_chg": 337000, "oi_chg_pct": 9.6,
                         "cash_chg_pct": 4.49, "cash_close": 2311.6, "price_chg_pct": 4.64, "label": "long_buildup"}


def test_b7_total_oi_reads_long_build_up_while_the_near_month_unwinds_on_the_roll():
    fb, gaps = sc.fno_block(True, as_of="2026-10-26", scan_row=MANKIND_SCAN_20261026,
                            back_row={"oi": 3510250 / 1.05, "cash_close": 2200.0}, back_date="2026-10-21",
                            futures=MANKIND_STF_20261026, options=None, options_exp=None, past=[], day=date(2026, 10, 26), sessions=SESSIONS)
    assert fb["total"]["state_1s"] == "long_buildup" and fb["state"] == "long_buildup" and fb["score"] == 100.0
    near = fb["by_expiry"][0]
    assert near["leg"] == "near" and near["oi_chg_pct"] == -60.03 and near["state"] == "short_covering"   # near-month alone misreads the roll
    assert fb["by_expiry"][1]["basis_pct"] == 0.78                        # Nov future 2329.6 vs spot 2311.65
    assert fb["rollover"]["pct"] == 83.4 and fb["rollover"]["sessions_to_expiry"] == 1
    assert sc.fno_block(False, as_of="2026-10-26", scan_row=MANKIND_SCAN_20261026, back_row=None, back_date=None, futures=None,
                        options=None, options_exp=None, past=[], day=date(2026, 10, 26), sessions=SESSIONS) == (None, [])


def test_b7_rollover_against_the_stocks_own_past_expiries_and_the_options_expiry():
    past = []
    for exp, d, near_oi in (("2026-09-29", "2026-09-28", 300000), ("2026-08-25", "2026-08-24", 600000)):   # MOCK
        past.append((exp, d, [{"expiry_date": exp, "close_price": 100.0, "underlying_price": 100.0, "open_interest": near_oi},
                              {"expiry_date": "x-next", "close_price": 100.5, "underlying_price": 100.0, "open_interest": 1000000 - near_oi}]))
    r = sc.rollover_block(MANKIND_STF_20261026, date(2026, 10, 26), SESSIONS, past)
    assert r["past_range"] == {"min": 40.0, "max": 70.0} and r["position"] == "above"
    assert r["past_premium_range"] == {"min": 0.5, "max": 0.5} and r["premium_position"] == "above"
    assert sc.rollover_block(MANKIND_STF_20261026, date(2026, 10, 12), SESSIONS, past) is None     # 11 sessions out: no window
    assert sc.options_expiry(MANKIND_STF_20261026, date(2026, 10, 26)) == "2026-11-23"           # October is in its expiry week
    assert sc.options_expiry(MANKIND_STF_20261026, date(2026, 10, 15)) == "2026-10-27"


def test_b7_options_block_pcr_and_its_change_from_the_days_own_rows():
    # MOCK chain: puts 400 OI (+100 today), calls 1,000 OI (+200 today) → PCR 0.40, previous 300 / 800 = 0.375
    rows = [{"strike_price": 100, "option_type": "PE", "open_interest": 300, "change_in_oi": 80},
            {"strike_price": 95, "option_type": "PE", "open_interest": 100, "change_in_oi": 20},
            {"strike_price": 110, "option_type": "CE", "open_interest": 700, "change_in_oi": 50},
            {"strike_price": 120, "option_type": "CE", "open_interest": 300, "change_in_oi": 150}]
    o = sc.options_block(rows, "2026-11-23")
    assert (o["pcr"], o["pcr_prev"], o["pcr_change"]) == (0.4, 0.38, 0.03)
    assert o["put_oi_added"] == 100 and o["call_oi_added"] == 200
    assert o["max_put_oi_strike"] == 100 and o["max_call_oi_strike"] == 110
    assert o["most_put_oi_added_strikes"][0] == 100 and o["most_call_oi_added_strikes"][0] == 120
    assert o["label"] == "open interest cannot tell buyers from writers"


# ── expiry-week dampening (§4c; coordinator 27 Oct) ──────────────────────────────────────────────────────────────

def _covering(day: date, expiry: str):
    row = {"symbol": "IEX", "near_expiry": expiry, "oi": 1000000, "oi_chg_pct": -8.2, "cash_chg_pct": 2.2, "cash_close": 150.0}
    return sc.fno_block(True, as_of=day.isoformat(), scan_row=row, back_row=None, back_date=None, futures=[], options=None,
                        options_exp=None, past=[], day=day, sessions=SESSIONS)[0]


def test_falling_oi_states_score_as_no_clear_signal_inside_the_expiry_week():
    # IEX 26 Oct: +2.2 % / OI −8.2 % (coordinator, staging); MOCK expiries 2 and 8 sessions ahead
    inside = _covering(date(2026, 10, 23), "2026-10-27")        # 2 sessions before expiry (26, 27)
    assert inside["state"] == "short_covering" and inside["score"] == 50.0 and inside["sessions_to_expiry"] == 2
    assert inside["text"] == "short covering (expiry week: open interest falls as contracts close)" and inside["expiry_window"]
    outside = _covering(date(2026, 10, 15), "2026-10-27")       # 8 sessions before expiry
    assert outside["state"] == "short_covering" and outside["score"] == 75.0 and outside["note"] is None
    build_up = sc.fno_block(True, as_of="2026-10-26", scan_row=MANKIND_SCAN_20261026, back_row=None, back_date=None, futures=[],
                            options=None, options_exp=None, past=[], day=date(2026, 10, 26), sessions=SESSIONS)[0]
    assert build_up["expiry_window"] and build_up["score"] == 100.0                     # rising OI keeps its score


# ── TC-B14 a baseline band too wide is not rated ─────────────────────────────────────────────────────────────────

def test_b14_too_wide_bands_are_not_rated_and_the_verdict_uses_the_rest():
    # Copied from staging 2026-10-27 (DaaS expectations, 26–28 Oct window): BAJAJ-AUTO PAT 1848.3–3687.0–7200.4
    # (half-width 0.73), ITCHOTELS PAT 109.9–172.4–281.3 (0.50) and revenue 893.8–977.9–1173.5 (0.14), filed 203 / 1054
    bajaj = sc.rate_metric("pat", metric("pat", 1848.3, 3687.0, 7200.4, filed=3500.0))
    assert bajaj["reason"] == "not rated: baseline too uncertain" and bajaj["half_width"] == 0.73 and bajaj["z"] is None
    itc = sc.surprise([metric("revenue", 893.8, 977.9, 1173.5, filed=1054.0), metric("pat", 109.9, 172.4, 281.3, filed=203.0)])
    assert itc["metrics"]["pat"]["reason"] == "not rated: baseline too uncertain"
    assert itc["used"] == ["revenue"] and itc["z"] == 0.39 and itc["verdict"]["label"] == "in_line"
    assert itc["verdict"]["reason"] == "revenue only (PAT: baseline too uncertain)"
    # revenue at exactly the 0.20 limit is rated; just over is not
    assert sc.rate_metric("revenue", metric("revenue", 80, 100, 120, filed=100))["z"] == 0.0
    assert sc.rate_metric("revenue", metric("revenue", 79, 100, 121, filed=100))["reason"] == "not rated: baseline too uncertain"
    both = sc.surprise([metric("revenue", 500, 1000, 1500, filed=1000), metric("pat", 1848.3, 3687.0, 7200.4, filed=3000.0)])
    assert both["verdict"] == {"label": None, "intensity": None, "reason": "not rated: baseline too uncertain"}
    assert build.counts_of([{"status": "declared", "verdict": both["verdict"]}])["not_rated"] == 1


# ── TC-B8 ideas: F&O list, All list, ties, the note, one per symbol, renormalisation on the filing evening ───────

def idea_row(sym, status="declared", fno=True, earn=70.0, reaction=None, oi=None, tech=60.0, ev="2026-10-26"):
    return {"symbol": sym, "name": sym, "status": status, "fno": fno, "event_date": ev, "verdict": {"label": "in_line"},
            "score": {"value": earn}, "reaction": None if reaction is None else {"score": reaction, "excess_pct": 1.0, "first_session": "2026-10-27", "volume_x": 1.0},
            "fno_buildup": None if oi is None else {"score": oi, "state": "long_buildup", "text": "long build-up", "total": {}},
            "technical": {"score": tech, "stage": "ACCUMULATION"}, "components": {"trend": {"value": 60.0}, "past_reactions": {"score": 55.0, "mean_two_session_pct": 0.5, "n": 4}}}


def test_b8_fno_list_holds_only_fno_names_and_the_all_list_has_no_oi_part():
    rows = [idea_row("AAA", oi=100.0), idea_row("BBB", fno=False), idea_row("CCC", status="pending")]
    f = sc.order_ideas(rows, DAY, SESSIONS, fno_list=True)
    assert [i["symbol"] for i in f["items"]] == ["AAA"] and "oi" in f["items"][0]["parts"]
    a = sc.order_ideas(rows, DAY, SESSIONS, fno_list=False)
    assert [i["symbol"] for i in a["items"]] == ["AAA", "BBB"] and all("oi" not in i["parts"] for i in a["items"])
    assert a["left_out"]["pending"] == 1


def test_b8_on_the_filing_evening_the_missing_reaction_renormalises():
    # filed after the close: no reaction yet → earnings 40, OI 20, technical 20 renormalised to 50 / 25 / 25 (80 % ≥ 50 %)
    i = sc.order_ideas([idea_row("AAA", earn=80.0, oi=100.0, tech=40.0)], date(2026, 10, 26), SESSIONS, fno_list=True)["items"][0]
    assert i["parts"]["earnings"]["weight"] == 50.0 and i["parts"]["oi"]["weight"] == 25.0 and i["parts"]["reaction"]["weight"] == 0.0
    assert i["signal"] == 0.5 * 80 + 0.25 * 100 + 0.25 * 40 == 75.0 and i["missing"] == ["reaction"]


def test_b8_ties_are_deterministic_and_each_symbol_appears_once():
    rows = [idea_row("ZZZ", earn=70.0, tech=70.0), idea_row("AAA", earn=70.0, tech=70.0),
            idea_row("MMM", earn=80.0, tech=60.0),                                 # (40 × 80 + 20 × 60) / 60 = 73.3
            idea_row("AAA", status="upcoming", ev="2026-10-29")]
    items = sc.order_ideas(rows, DAY, SESSIONS, fno_list=False)["items"]
    assert [i["symbol"] for i in items].count("AAA") == 1
    sigs = {i["symbol"]: i["signal"] for i in items}
    assert sigs["AAA"] == sigs["ZZZ"] == 70.0 and sigs["MMM"] == 73.3
    assert [i["symbol"] for i in items] == ["MMM", "AAA", "ZZZ"]                  # signal, then earnings, then symbol
    same_signal = [idea_row("BBB", earn=60.0, tech=80.0), idea_row("CCC", earn=80.0, tech=40.0)]   # both 66.7 / 66.7
    order = [i["symbol"] for i in sc.order_ideas(same_signal, DAY, SESSIONS, fno_list=False)["items"]]
    assert order == ["CCC", "BBB"]                                               # the higher earnings score first


# ── the full build with stubbed sources (used by TC-B9, TC-B10, TC-B11, TC-B13) ─────────────────────────────────

def fin_rows(pat, pat4, rev, rev4, ebitda=None, ebitda4=None, oi=10.0, pbt=None):
    """MOCK eight quarters, newest first; the latest two that matter are 2026-09-30 and 2025-09-30."""
    ends = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31"]
    rows = []
    for i, e in enumerate(ends):
        r = {"period_end": e, "revenue_from_ops_cr": rev * (1 - 0.01 * i), "pat_cr": pat * (1 - 0.01 * i), "ebitda_cr": (ebitda or rev * 0.2),
             "other_income_cr": oi, "pbt_cr": pbt or pat * 1.3, "exceptional_items_cr": None, "tax_expense_cr": None}
        rows.append(r)
    rows[0].update(revenue_from_ops_cr=rev, pat_cr=pat, ebitda_cr=ebitda or rev * 0.2)
    rows[4].update(revenue_from_ops_cr=rev4, pat_cr=pat4, ebitda_cr=ebitda4 or rev4 * 0.2)
    return rows


def ev(sym, d, status, filed_state, fno, metrics, filing=None):
    return {"id": f"{d}|{sym}|RESULTS|mtg", "symbol": sym, "name": f"{sym} Ltd", "sector": "Test", "event_date": d, "status": status,
            "filed_state": filed_state, "filing": filing, "period_label": "Q2 FY27 (Jul–Sep 2026)", "basis": "consolidated",
            "universe": {"fno": fno, "n50": False}, "metrics": metrics, "gaps": []}


EVENTS = [   # MOCK
    ev("AAA", "2026-10-26", "declared", "figures", True,
       [metric("revenue", 900, 1000, 1100, filed=1150), metric("pat", 90, 100, 110, filed=112)]),
    ev("BBB", "2026-10-26", "declared", "figures", False,
       [metric("revenue", None, None, None, reliable=False), metric("pat", 45, 50, 55, filed=49)]),
    ev("CCC", "2026-10-27", "declared", "pending", True, [metric("revenue", 90, 100, 110), metric("pat", None, None, None, reliable=False)],
       filing={"filed_at": "2026-10-27T14:59:50+05:30", "subject": "Outcome of Board Meeting", "url": "https://example.invalid/ccc.pdf"}),
    ev("DDD", "2026-10-29", "upcoming", None, True, [metric("revenue", 950, 1000, 1050), metric("pat", 95, 100, 105)]),
    ev("EEE", "2026-10-30", "upcoming", None, False, [metric("revenue", None, None, None, reliable=False), metric("pat", None, None, None, reliable=False)]),
]


def daas_answer(path: str, params: Optional[dict], fail: Optional[str] = None):
    """The stubbed DaaS (MOCK). `fail` names a path prefix that answers 503."""
    if fail and path.startswith(fail):
        return 503, {"detail": "down"}
    p = params or {}
    if path == "/desk/events-calendar/expectations":
        lo, hi = p["from"], p["to"]
        evs = [e for e in EVENTS if lo <= e["event_date"] <= hi]
        counts = {"declared_figures": sum(1 for e in evs if e["filed_state"] == "figures"),
                  "declared_pending": sum(1 for e in evs if e["filed_state"] == "pending"),
                  "upcoming": sum(1 for e in evs if e["status"] == "upcoming")}
        return 200, {"from": lo, "to": hi, "as_of": "2026-10-27", "count": len(evs), "counts": counts, "events": copy.deepcopy(evs),
                     "label": "MOCK baseline", "method": {"name": "MOCK"}, "sources": {}, "gaps": ["no analyst consensus is available"]}
    if path.startswith("/financials/"):
        sym = path.split("/")[2]
        return 200, {"data": {"AAA": fin_rows(112, 80, 1150, 1000), "BBB": fin_rows(49, 50, 0, 0), "DDD": fin_rows(100, 90, 1000, 900),
                              "EEE": fin_rows(10, 9, 100, 95)}.get(sym, [])}
    if path == "/desk/events-calendar/history":
        return 200, {"occurrences": [{"event_day_pct": 1.0, "d1_pct": 1.0}, {"event_day_pct": -1.0, "d1_pct": 3.0}]}
    if path == "/desk/fno-buildup":
        d = p["date"]
        rows = [{"symbol": "AAA", "near_expiry": "2026-10-27", "oi": 1100000, "oi_chg_pct": 4.0, "cash_chg_pct": 1.5, "cash_close": 101.5, "label": "long_buildup"},
                {"symbol": "CCC", "near_expiry": "2026-10-27", "oi": 900000, "oi_chg_pct": -5.0, "cash_chg_pct": 1.0, "cash_close": 50.0, "label": "short_covering"},
                {"symbol": "DDD", "near_expiry": "2026-10-27", "oi": 500000, "oi_chg_pct": 0.5, "cash_chg_pct": 0.2, "cash_close": 70.0, "label": "long_buildup"}]
        return 200, {"as_of": d, "rows": rows}
    if path.startswith("/fno/") and path.endswith("/expiries"):
        return 200, {"data": [{"expiry_date": e} for e in ("2026-06-30", "2026-07-28", "2026-08-25", "2026-09-29", "2026-10-27", "2026-11-23")]}
    if path.startswith("/fno/"):
        if p.get("instrument_type") == "STO":
            return 200, {"as_of": p["on"], "data": [{"strike_price": 100, "option_type": "PE", "open_interest": 50, "change_in_oi": 10},
                                                    {"strike_price": 110, "option_type": "CE", "open_interest": 100, "change_in_oi": 20}]}
        return 200, {"as_of": p["on"], "data": [
            {"expiry_date": "2026-10-27", "close_price": 101.0, "prev_close_price": 100.0, "underlying_price": 100.8, "open_interest": 200000, "change_in_oi": -50000},
            {"expiry_date": "2026-11-23", "close_price": 101.6, "prev_close_price": 100.2, "underlying_price": 100.8, "open_interest": 800000, "change_in_oi": 90000}]}
    if path.startswith("/indices/"):
        return 200, {"data": [{"as_of_date": d.isoformat(), "close_price": 20000.0 + 10 * i} for i, d in enumerate(SESSIONS) if d <= DAY]}
    raise AssertionError(f"unexpected DaaS path {path}")


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return list(self.docs)


class FakeColl:
    def __init__(self, docs, fail=False):
        self.docs, self.fail = docs, fail

    def find(self, q, proj=None):
        if self.fail:
            raise RuntimeError("mongo down")
        syms = set(q.get("symbol", {}).get("$in", []))
        return FakeCursor([d for d in self.docs if d["symbol"] in syms])


class FakeDB(dict):
    def __getitem__(self, k):
        return dict.get(self, k) or FakeColl([])


ANALYSIS = [{"symbol": "AAA", "mode": "single_full", "event_type": "QUARTERLY RESULTS", "event_ts": datetime(2026, 10, 26, 11, 0),
             "analyzed_at": datetime(2026, 10, 26, 12, 0), "net_impact_score": 30, "net_band": "moderately_positive",
             "confidence_score": 80, "materiality_score": 40, "analysis": {"sum": "MOCK summary of the quarter."}}]


class _Conn:
    def __init__(self, fail):
        self.fail = fail

    async def fetch(self, sql, *args):
        if self.fail:
            raise RuntimeError("pg down")
        if "FROM stock_ohlcv" in sql:
            out = []
            for sym in args[0]:
                for i, d in enumerate([s for s in SESSIONS if s <= DAY][-25:]):
                    out.append({"nse_symbol": sym, "bar_date": d, "close_price": 100.0 + (1.5 if d == DAY else 0.0), "volume": 2000 if d == DAY else 1000})
            return out
        if "FROM stock_technical_features" in sql:
            return [{"nse_symbol": s, "as_of_date": date(2026, 10, 26), "stage": "ACCUMULATION", "final_score": 0.6, "confidence": "MEDIUM"} for s in args[0]]
        raise AssertionError(sql)

    async def fetchrow(self, sql, *args):
        return {"n": 2900}


class _Acq:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *e):
        return False


class _Pool:
    def __init__(self, fail=False):
        self.c = _Conn(fail)

    def acquire(self):
        return _Acq(self.c)


@pytest.fixture
def sources(monkeypatch):
    """Stub every source of the build; returns a dict whose keys switch failures on."""
    state = {"fail_daas": None, "mongo_fail": False, "pg_fail": False, "calls": []}

    async def daas_get(path, params=None, timeout=20.0):
        state["calls"].append(path)
        return daas_answer(path, params, state["fail_daas"])

    async def sessions(start, end):
        return [d for d in SESSIONS if start <= d <= end], None

    async def get_pool():
        return _Pool(state["pg_fail"])

    from services import pg_client
    monkeypatch.setattr(loaders, "daas_get", daas_get)
    monkeypatch.setattr(loaders, "sessions", sessions)
    monkeypatch.setattr(pg_client, "get_pool", get_pool)
    state["db"] = lambda: FakeDB({loaders.ANALYSIS_COLLECTION: FakeColl(ANALYSIS, fail=state["mongo_fail"])})
    return state


NOW = utc(2026, 10, 27, 17, 0)           # 22:30 IST on 27 Oct


def body_of(sources, live=True):
    return run(build.build_day(DAY, now=NOW, live=live, db=sources["db"]()))


def test_build_week_rows_counts_and_rows(sources):
    b = body_of(sources)
    assert b["week"] == {"from": "2026-10-26", "to": "2026-10-31"} and b["basis"] == "historical_trend"
    assert b["counts"] == {"declared": 2, "declared_pending": 1, "upcoming": 2, "above": 1, "in_line": 1, "below": 0, "not_rated": 0}
    by = {r["symbol"]: r for r in b["results"]}
    aaa = by["AAA"]
    assert aaa["verdict"]["label"] == "above" and aaa["components"]["outlook"]["net_band"] == "moderately_positive"
    assert aaa["components"]["trend"]["yoy_pct"]["pat"] == 40.0 and aaa["reaction"]["first_session"] == "2026-10-27"
    assert aaa["fno_buildup"]["state"] == "long_buildup" and aaa["fno_buildup"]["options_next_expiry"]["expiry"] == "2026-11-23"
    assert by["BBB"]["components"]["surprise"]["used"] == ["pat"] and by["BBB"]["fno_buildup"] is None
    assert by["CCC"]["status"] == "pending" and by["CCC"]["verdict"]["reason"].startswith("not rated: figures pending")
    assert by["CCC"]["score"]["value"] is None and by["CCC"]["evidence"][0]["url"].endswith("ccc.pdf")
    assert by["DDD"]["status"] == "upcoming" and by["DDD"]["components"]["past_reactions"]["n"] == 2
    assert by["EEE"]["components"]["surprise"]["metrics"]["pat"]["reason"] == "not rated: no reliable baseline"
    assert {i["symbol"] for i in b["ideas"]["fno"]} <= {"AAA", "CCC", "DDD"} and "BBB" not in {i["symbol"] for i in b["ideas"]["fno"]}
    assert all(r["chartink"] is None for r in b["results"])


# ── TC-B9 wording ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_b9_no_forbidden_wording_and_the_label_says_historical_trend(sources):
    b = body_of(sources)
    assert sc.forbidden_terms(b) == []
    assert "historical trend" in b["label"] and "not analyst consensus" in b["label"] and b["consensus_available"] is False
    assert b["ideas"]["note"] == "Ordered for review, not a prediction. This ordering has not been tested yet."
    assert sc.forbidden_terms({"x": "We recommend this pick"}) == ["recommend", "pick"]
    assert sc.forbidden_terms({"x": "results beat the Street"}) == ["beat the street"]


# ── TC-B13 a failed source nulls its block with a gap; the rest still answers ────────────────────────────────────

def test_b13_daas_financials_down_mongo_down_pg_down(sources):
    sources.update(fail_daas="/financials/", mongo_fail=True, pg_fail=True)
    b = body_of(sources)
    aaa = next(r for r in b["results"] if r["symbol"] == "AAA")
    assert aaa["verdict"]["label"] == "above"                                   # the calendar still answers
    assert aaa["components"]["trend"]["value"] is None and any("quarterly results could not be read" in g for g in aaa["gaps"])
    assert aaa["components"]["outlook"]["analysed"] is None and aaa["components"]["outlook"]["reason"] == "the filing analysis store could not be read"
    assert aaa["reaction"] is None and aaa["technical"] is None and aaa["fno_buildup"]["state"] == "long_buildup"
    assert not b["sources"]["financials"]["ok"] and not b["sources"]["filing_analysis"]["ok"] and not b["sources"]["prices"]["ok"]
    assert any("could not be read" in g for g in b["gaps"])


def test_b13_one_window_down_marks_counts_partial_and_all_down_raises(sources, monkeypatch):
    async def daas_get(path, params=None, timeout=20.0):
        if path == "/desk/events-calendar/expectations" and params["from"] == "2026-10-29":
            return 503, None
        return daas_answer(path, params)
    monkeypatch.setattr(loaders, "daas_get", daas_get)
    b = body_of(sources)
    assert b["counts_partial"] is True and b["counts"]["upcoming"] == 0
    assert any("2026-10-29 to 2026-10-31 could not be read" in g for g in b["gaps"])
    sources_fail = dict(sources)
    monkeypatch.setattr(loaders, "daas_get", lambda *a, **k: _raise())
    with pytest.raises(loaders.SourceUnavailable):
        body_of(sources_fail)


async def _raise():
    from services.copilot_tools import daas_client
    raise daas_client.DaasError("down", status_code=503)


def test_b13_fno_contracts_down_keeps_the_total_state(sources):
    sources.update(fail_daas="/fno/")
    aaa = next(r for r in body_of(sources)["results"] if r["symbol"] == "AAA")
    assert aaa["fno_buildup"]["state"] == "long_buildup" and aaa["fno_buildup"]["by_expiry"] == []
    assert any("futures contracts could not be read" in g for g in aaa["gaps"])


# ── TC-B10 the route: 401 signed out, 422 bad date, 404 past day not stored, today live with Chartink joined ──────

def client(monkeypatch, *, signed_in=True, body=None, stored=None, chartink=(None, {"connected": False})):
    if signed_in:
        async def user(request: Request):
            return {"user_id": "u1"}
        monkeypatch.setattr(route, "get_current_user", user)

    async def build_day(day, now=None, live=True, db=None):
        return copy.deepcopy(body)

    async def get_day(d, db=None):
        return copy.deepcopy(stored)

    async def ck(db, uid, day):
        return chartink

    monkeypatch.setattr(route.rw_build, "build_day", build_day)
    monkeypatch.setattr(route.store, "get_day", get_day)
    monkeypatch.setattr(route.loaders, "chartink_for", ck)
    monkeypatch.setattr(route, "today_ist", lambda: DAY)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_b10_signed_out_is_401(monkeypatch):
    c = client(monkeypatch, signed_in=False, body={})
    assert c.get("/api/desk/results-week").status_code == 401


@pytest.mark.parametrize("q", ["2026-13-01", "20261027", "abc", "2026-10-28"])
def test_b10_a_bad_or_future_date_is_422(monkeypatch, q):
    r = client(monkeypatch, body={}).get(f"/api/desk/results-week?date={q}")
    assert r.status_code == 422


def test_b10_past_day_not_stored_is_404_and_stored_day_answers(monkeypatch):
    assert client(monkeypatch, body={}).get("/api/desk/results-week?date=2026-10-26").status_code == 404
    stored = {"date": "2026-10-26", "results": [{"symbol": "AAA", "chartink": None}], "sources": {}, "gaps": []}
    r = client(monkeypatch, body={}, stored=stored, chartink=({"AAA": ["Breakout scan"]}, {"connected": True, "scan_date": "2026-10-26"}))
    d = r.get("/api/desk/results-week?date=2026-10-26").json()
    assert d["results"][0]["chartink"] == {"scans": ["Breakout scan"], "scan_date": "2026-10-26"}


def test_b10_today_is_built_live_and_cached(sources, monkeypatch):
    live = body_of(sources)
    c = client(monkeypatch, body=live, chartink=({"AAA": ["Volume spike"]}, {"connected": True, "scan_date": "2026-10-27"}))
    d = c.get("/api/desk/results-week").json()
    by = {r["symbol"]: r for r in d["results"]}
    assert by["AAA"]["chartink"]["scans"] == ["Volume spike"] and by["BBB"]["chartink"] == {"scans": [], "scan_date": "2026-10-27"}
    assert d["sources"]["chartink"]["connected"] is True and route._live.get("2026-10-27")


def test_b10_results_calendar_down_is_502(monkeypatch):
    async def down(day, now=None, live=True, db=None):
        raise loaders.SourceUnavailable("all windows")
    c = client(monkeypatch, body={})
    monkeypatch.setattr(route.rw_build, "build_day", down)
    assert c.get("/api/desk/results-week").status_code == 502


# ── TC-B11 the job: --dry-run writes nothing; --skip-if-done is a no-op; a stored day is never rewritten ─────────

@pytest.fixture
def job_env(sources, monkeypatch):
    calls = {"insert": 0, "refresh": [], "build": 0}
    st = {"has": False, "insert_ok": True, "prices": True, "session": (True, "weekday")}

    async def has_day(d, db=None):
        return st["has"]

    async def insert_day(doc, db=None):
        calls["insert"] += 1
        return st["insert_ok"]

    async def check_session(d):
        return st["session"]

    async def refresh(dry_run):
        calls["refresh"].append(dry_run)

    async def prices_loaded(d):
        return st["prices"]

    real_build = build.build_day

    async def build_day(day, now=None, live=True, db=None):
        calls["build"] += 1
        return await real_build(day, now=NOW, live=live, db=sources["db"]())

    from services.positional_engine import session_calendar
    monkeypatch.setattr(store, "has_day", has_day)
    monkeypatch.setattr(store, "insert_day", insert_day)
    monkeypatch.setattr(session_calendar, "check_session", check_session)
    monkeypatch.setattr(job, "refresh_chartink", refresh)
    monkeypatch.setattr(loaders, "prices_loaded", prices_loaded)
    monkeypatch.setattr(build, "build_day", build_day)
    return calls, st


def go(**kw):
    kw.setdefault("skip_if_done", False)
    kw.setdefault("dry_run", False)
    return run(job.run(DAY, show=[], today=DAY, **kw))


def test_b11_dry_run_writes_nothing(job_env, capsys):
    calls, st = job_env
    assert go(dry_run=True) == 0 and calls["insert"] == 0 and calls["refresh"] == [True]
    out = capsys.readouterr().out
    assert '"wording_check_forbidden_terms_found": []' in out


def test_b11_skip_if_done_is_a_no_op_and_a_stored_day_is_never_rewritten(job_env):
    calls, st = job_env
    st["has"] = True
    assert go(skip_if_done=True) == 0 and calls["build"] == 0 and calls["insert"] == 0
    st.update(has=False, insert_ok=False)
    assert go() == 3 and calls["insert"] == 1


def test_b11_store_refuses_to_replace_a_day():
    from pymongo.errors import DuplicateKeyError

    class Coll:
        def __init__(self):
            self.ids = set()

        async def insert_one(self, doc):
            if doc["_id"] in self.ids:
                raise DuplicateKeyError("dup")
            self.ids.add(doc["_id"])

    db = {store.COL: Coll()}
    assert run(store.insert_day({"date": "2026-10-27", "v": 1}, db=db)) is True
    assert run(store.insert_day({"date": "2026-10-27", "v": 2}, db=db)) is False


def test_b11_refusals_and_exit_codes(job_env):
    calls, st = job_env
    st["prices"] = False
    assert go() == 4 and calls["insert"] == 0                        # prices for the date not loaded
    st["prices"] = True
    st["session"] = (False, "NSE holiday")
    assert go() == 2
    st["session"] = (True, "weekday")
    assert run(job.run(DAY, show=[], today=DAY + timedelta(days=1), skip_if_done=False, dry_run=False)) == 1   # not today
    assert go() == 0 and calls["insert"] == 1                         # stored


def test_b11_snapshot_mode_refuses_another_days_fno(job_env, monkeypatch):
    calls, st = job_env
    orig = daas_answer

    async def daas_get(path, params=None, timeout=20.0):
        if path == "/desk/fno-buildup":
            return 200, {"as_of": params["date"], "rows": []}           # the F&O bhavcopy is not in yet
        return orig(path, params)
    monkeypatch.setattr(loaders, "daas_get", daas_get)
    assert go() == 4 and calls["insert"] == 0


def test_b11_store_strips_the_per_user_column(sources):
    b = build.join_chartink(body_of(sources), {"AAA": ["x"]}, {"connected": True, "scan_date": "2026-10-27"})
    s = build.strip_chartink(b)
    assert all(r["chartink"] is None for r in s["results"]) and s["sources"]["chartink"] is None
    json.dumps(s, default=str)                                         # storable
