"""Signal strength 0–100 and the positional plan (services/scan_builder/signal_strength.py, DESIGN.md §11).

Every stock, price and filing below is hand-made (MOCK — not real data), except the SAREGAMA plan numbers, which repeat the
4 Nov 2026 live check (price ₹621.50, ATR(14) ₹18.99, 20-day average ₹510.65) to pin the arithmetic."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from services.scan_builder import signal_strength as SS


@pytest.fixture(autouse=True)
def _fresh():
    SS.reset_caches()
    yield
    SS.reset_caches()


GOOD = {"roce_pct": 22.0, "roe_pct": 19.0, "debt_to_equity": 0.1, "profit_margin_pct": 15.0,
        "earnings_consistency_score": 80.0, "promoter_pct": 55.0, "fii_pct": 10.0, "dii_pct": 8.0, "market_cap_cr": 80000.0}


def rising(n=300, start=100.0):
    """+2, −1 alternating: a steady uptrend whose RSI(14) sits near 67."""
    c = [start]
    for i in range(n - 1):
        c.append(c[-1] + (2.0 if i % 2 == 0 else -1.0))
    return np.array(c)


def stock(**kw):
    c = kw.pop("closes", rising())
    base = dict(symbol="AAA", name="Aaa Industries Ltd", price=float(c[-1]) + 1.0, volume_today=3e6, closes=c,
                highs=c + 0.5, lows=c - 0.5, volumes=np.full(len(c), 1e6), fundamentals=dict(GOOD),
                snapshot={"price_band_pct": None, "is_etf": False, "sector": "Industrials"}, members={"nifty50", "nifty100"},
                fno=True, lists=[{"id": "dt_52w_high", "title": "52 week high", "direction": "long"}], usual_share=1.0)
    base.update(kw)
    return SS.StockInputs(**base)


def tech(**kw):
    t = dict(smas={5: 90.0, 10: 90.0, 20: 90.0, 30: 90.0, 50: 90.0, 100: 80.0, 150: 80.0, 200: 70.0}, hi52=99.0, lo52=50.0,
             rsi=60.0, ret21=5.0, ret63=10.0, ret125=20.0, adv20=1e6, traded_cr=100.0, atr=2.0)
    t.update(kw)
    return SS.Tech(**t)


# ── TC-S1 quality ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_quality_full_marks_and_each_band_edge():
    assert SS.quality(stock())[0] == 30
    f = dict(GOOD, roce_pct=15.0, roe_pct=12.0, debt_to_equity=1.0, profit_margin_pct=0.5, earnings_consistency_score=50.0,
             promoter_pct=30.0, fii_pct=3.0, dii_pct=2.0)
    assert SS.quality(stock(fundamentals=f))[0] == 6 + 3 + 3 + 1 + 2 + 2 + 1
    f = dict(GOOD, roce_pct=9.99, roe_pct=7.9, debt_to_equity=2.5, profit_margin_pct=-1.0, earnings_consistency_score=49.0,
             promoter_pct=29.0, fii_pct=1.0, dii_pct=1.0)
    assert SS.quality(stock(fundamentals=f))[0] == 0


def test_quality_missing_figures_score_zero_and_are_named():
    pts, text = SS.quality(stock(fundamentals={}))
    assert pts == 0 and "ROCE no data" in text and "debt/equity no data" in text


def test_financials_use_roe_and_fixed_debt_points():
    f = dict(GOOD, roce_pct=2.0, roe_pct=16.0, debt_to_equity=9.0)
    s = stock(fundamentals=f, snapshot={"sector": "Financial Services"})
    pts, text = SS.quality(s)
    assert pts == 6 + 3 + 3 + 3 + 4 + 3 + 2 and "ROCE" not in text and "debt/equity" not in text


# ── TC-S2 trend ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_trend_counts_averages_cross_setup_rsi_and_six_month_return():
    s = stock(price=100.0)
    pts, notes = SS.trend(s, tech(), "breakout")
    assert pts == 8 + 4 + 6 + 4 + 3 == 25 and "52-week-high breakout" in notes[2]
    pts, _ = SS.trend(stock(price=85.0), tech(rsi=75.0, ret125=5.0), "near_high")
    assert pts == 3 + 4 + 4 + 2 + 1                       # above the 100/150/200-day only
    pts, _ = SS.trend(stock(price=85.0), tech(rsi=85.0, ret125=-3.0, smas={50: 70.0, 200: 90.0}), None)
    assert pts == 1 + 0 + 0 + 0 + 0                       # above the 50-day only; 50-day below the 200-day
    assert SS.trend(stock(price=85.0), tech(rsi=40.0), "reversal")[0] == 3 + 4 + 6 + 1 + 3


def test_setup_breakout_near_high_and_reversal_from_the_52_week_low():
    c = rising()
    hi = float(np.max((c + 0.5)[-250:]))
    t = SS.technicals(stock(price=hi + 1))
    assert SS.setup_of(stock(price=hi + 1), t) == "breakout"
    assert SS.setup_of(stock(price=hi * 0.97), SS.technicals(stock(price=hi * 0.97))) == "near_high"
    # a long fall to a low, then 30 sessions turning up: within 30 % of the low, above the 50-day, 20-day rising
    down = np.linspace(200, 100, 260)
    up = np.linspace(100, 118, 40)
    cc = np.concatenate([down, up])
    s = stock(closes=cc, highs=cc + 0.5, lows=cc - 0.5, price=120.0)
    assert SS.setup_of(s, SS.technicals(s)) == "reversal"


def test_rsi_and_atr_are_wilders():
    c = rising(60)
    r = SS.rsi14(c, None)
    assert r is not None and 60 < r < 72
    assert SS.atr14(c + 0.5, c - 0.5, c) == pytest.approx(2.0, rel=0.05)     # |±2| and |∓1| moves plus the 1.0 range


# ── TC-S3 reason ────────────────────────────────────────────────────────────────────────────────────────────────────

def F(cat, sen, imp="medium", subj="Outcome of Board Meeting", at="2026-11-04T07:01:00"):
    return {"event_category": cat, "sentiment": sen, "impact_score": imp, "subject": subj, "filed_at": at}


def test_filing_points():
    assert SS.filing_points(F("earnings", "positive")) == 16
    assert SS.filing_points(F("orders", "positive", "high")) == 12
    assert SS.filing_points(F("orders", "positive", "low")) == 8
    assert SS.filing_points(F("other", "positive", "high")) == 8
    assert SS.filing_points(F("earnings", "neutral")) == 6
    assert SS.filing_points(F("litigation", "negative", "high")) == -8
    assert SS.filing_points(F("regulatory", "neutral", "low")) == 0


def test_event_picks_the_strongest_filing_and_shows_ist_time():
    s = stock(filings=[F("regulatory", "neutral", "low"), F("orders", "positive", "low"), F("earnings", "positive")])
    pts, text = SS.event(s)
    assert pts == 16 and text.startswith("Results filing 04 Nov 12:31 IST (positive)")   # filed_at is UTC


def test_reason_adds_setup_and_positional_lists_and_is_clamped():
    s = stock()
    assert SS.reason(s, "breakout", 16, "x")[0] == 20                    # 16 + 10 + 4 → 20
    assert SS.reason(s, None, 0, None)[0] == 4                           # positional list only
    assert SS.reason(stock(lists=[{"id": "dt_rsi_vwap", "title": "x"}]), "near_high", 0, None)[0] == 6
    assert SS.reason(stock(lists=[]), None, -8, "bad")[0] == 0


# ── TC-S4 size ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("members,fno,mcap,expect", [
    ({"nifty50", "nifty100"}, True, 9e5, 15), ({"nifty100"}, True, 9e4, 13), ({"midcap150"}, False, 3e4, 10),
    ({"nifty500"}, False, 1e4, 7), ({"nifty500"}, True, 1e4, 9), (set(), False, 9600.0, 5), (set(), False, 2500.0, 3),
    (set(), False, 1500.0, 0), (set(), True, 1500.0, 9)])
def test_size_weights_blue_chips(members, fno, mcap, expect):
    s = stock(members=members, fno=fno, fundamentals=dict(GOOD, market_cap_cr=mcap))
    assert SS.size(s, tech())[0] == expect


def test_thin_trading_caps_size():
    assert SS.size(stock(), tech(traded_cr=3.0))[0] == 2


# ── TC-S5 participation ─────────────────────────────────────────────────────────────────────────────────────────────

def test_participation_bands_trade_sides_and_lists():
    two = [{"id": "dt_52w_high", "title": "a"}, {"id": "cup_handle", "title": "b"}]
    assert SS.participation(stock(ask_trades=120, bid_trades=100, lists=two), tech(), 3.0, 0)[0] == 6 + 2 + 2
    assert SS.participation(stock(), tech(), 12.0, 16)[0] == 4
    assert SS.participation(stock(), tech(), 12.0, 0)[0] == 2
    assert SS.participation(stock(), tech(), 40.0, 16)[0] == 3
    assert SS.participation(stock(), tech(), 40.0, 0)[0] == 0
    assert SS.participation(stock(), tech(), 1.0, 0)[0] == 2
    assert SS.participation(stock(), tech(), None, 0)[0] == 0


def test_volume_ratio_uses_the_usual_share_by_now():
    assert SS.volume_ratio(stock(volume_today=5e5, usual_share=0.25), tech(adv20=1e6)) == pytest.approx(2.0)


# ── TC-S6 penalties ─────────────────────────────────────────────────────────────────────────────────────────────────

def names(pen):
    return {p["text"].split(" (")[0].split(" ₹")[0]: p["points"] for p in pen}


def test_each_penalty_fires_at_its_edge_and_is_named():
    t = tech(smas={20: 1e4})                              # far above the price: no chasing penalty in the baseline
    assert SS.penalties(stock(), t, 2.0, 0) == []
    f = dict(GOOD, market_cap_cr=499.0)
    assert any(p["points"] == 25 for p in SS.penalties(stock(fundamentals=f), t, 2.0, 0))
    f = dict(GOOD, market_cap_cr=999.0)
    assert any(p["points"] == 15 and "₹1,000 cr" in p["text"] for p in SS.penalties(stock(fundamentals=f), t, 2.0, 0))
    assert any("Price under ₹20" in p["text"] for p in SS.penalties(stock(price=19.9), t, 2.0, 0))
    for band, pts in ((2.0, 30), (5.0, 15), (10.0, 5)):
        assert any(p["points"] == pts and "price band" in p["text"] for p in
                   SS.penalties(stock(snapshot={"price_band_pct": band}), t, 2.0, 0))
    s = stock(members={"nifty100", "nifty500"})
    assert not any("no filing" in p["text"] for p in SS.penalties(s, t, 11.0, 0))      # a Nifty 500 stock: not this one
    s = stock(members=set())
    assert any("no filing" in p["text"] for p in SS.penalties(s, t, 11.0, 0))
    assert not any("no filing" in p["text"] for p in SS.penalties(s, t, 11.0, 16))
    assert any("Parabolic" in p["text"] for p in SS.penalties(stock(), tech(ret21=51.0), 2.0, 0))
    ok = stock(fundamentals=dict(GOOD, pat_growth_yoy_pct=40.0))
    assert not any("Parabolic" in p["text"] for p in SS.penalties(ok, tech(ret21=51.0), 2.0, 0))
    assert any(p["points"] == 10 and "Loss-making" in p["text"]
               for p in SS.penalties(stock(fundamentals=dict(GOOD, profit_margin_pct=-2.0)), t, 2.0, 0))
    assert any(p["points"] == 20 for p in SS.penalties(stock(fundamentals=dict(GOOD, promoter_pledged_pct=51.0)), t, 2.0, 0))
    assert any(p["points"] == 10 and "pledge" in p["text"]
               for p in SS.penalties(stock(fundamentals=dict(GOOD, promoter_pledged_pct=26.0)), t, 2.0, 0))
    thin = dict(GOOD, promoter_pct=20.0, fii_pct=2.0, dii_pct=2.0)
    assert any("Low promoter" in p["text"] for p in SS.penalties(stock(fundamentals=thin), t, 2.0, 0))
    assert any("volatility" in p["text"] for p in SS.penalties(stock(fundamentals=dict(GOOD, volatility_1y_pct=71.0)), t, 2.0, 0))
    assert any("chasing" in p["text"] for p in SS.penalties(stock(price=113.0), tech(smas={20: 90.0}), 2.0, 0))
    assert not any("chasing" in p["text"] for p in SS.penalties(stock(price=112.0), tech(smas={20: 90.0}), 2.0, 0))


def test_upper_band_lock_and_the_exchanges_queries():
    c = rising()
    prev = float(c[-1])
    locked = stock(price=round(prev * 1.05, 2), snapshot={"price_band_pct": 5.0})
    assert any("Locked at the upper 5 % price band" in p["text"] for p in SS.penalties(locked, tech(), 2.0, 0))
    free = stock(price=round(prev * 1.04, 2), snapshot={"price_band_pct": 5.0})
    assert not any("Locked" in p["text"] for p in SS.penalties(free, tech(), 2.0, 0))
    q = stock(exchange_queries=[{"title": "Spurt in Volume"}, {"title": "News Verification"}])
    pen = [p for p in SS.penalties(q, tech(), 2.0, 0) if "queried" in p["text"]]
    assert pen and pen[0]["points"] == 10 and "1 reply filed" in pen[0]["text"]          # news verification is not counted
    assert not any("queried" in p["text"] for p in SS.penalties(stock(exchange_queries=[{"title": "News Verification"}]),
                                                                 tech(), 2.0, 0))


def test_etfs_and_short_only_stocks_are_not_scored_and_the_score_is_clamped():
    r = SS.score(stock(snapshot={"is_etf": True}))
    assert r["score"] is None and "ETF" in r["note"]
    r = SS.score(stock(closes=rising(40)))
    assert r["score"] is None and "60 sessions" in r["note"]
    bad = dict(GOOD, market_cap_cr=300.0, profit_margin_pct=-5.0, promoter_pledged_pct=60.0, volatility_1y_pct=90.0,
               roce_pct=1.0, roe_pct=1.0, debt_to_equity=5.0, earnings_consistency_score=0.0, promoter_pct=10.0,
               fii_pct=0.0, dii_pct=0.0)
    r = SS.score(stock(fundamentals=bad, members=set(), fno=False, price=15.0, snapshot={"price_band_pct": 2.0}))
    assert r["score"] == 0 and r["parts"]["penalty"] <= -100


# ── TC-S7 long only ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_long_only():
    falling = [{"id": "open_interest", "title": "Open interest", "direction": "short"}]
    r = SS.score(stock(lists=falling))
    assert r["score"] is None and r["note"].startswith("Not scored: long only")
    mixed = falling + [{"id": "dt_52w_high", "title": "52 week high", "direction": "long"}]
    assert SS.score(stock(lists=mixed))["score"] is not None


def test_a_solid_blue_chip_breakout_scores_high_and_explains_itself():
    c = rising()
    s = stock(price=float(np.max(c[-250:])) + 3.0, filings=[F("earnings", "positive")], volume_today=2.5e6)
    r = SS.score(s)
    assert r["score"] >= 85 and r["parts"]["penalty"] == 0
    assert r["reasons"][0].startswith("Results filing") and any("52-week-high breakout" in x for x in r["reasons"])
    assert set(r["parts"]) == {"quality", "trend", "reason", "size", "participation", "penalty"}


# ── TC-S8 the positional plan ───────────────────────────────────────────────────────────────────────────────────────

def test_plan_v3_on_the_saregama_numbers():
    p = SS.positional_plan(621.5, 18.99, 510.65, "2026-11-03")
    assert (p["stop_loss"], p["target_1"], p["target_2"], p["risk_per_share"]) == (583.52, 697.46, 773.42, 37.98)
    assert (p["rr_1"], p["rr_2"], p["plan_ok"], p["rules"]) == (2.0, 4.0, True, "scan-plan-v3")
    assert "₹510.65 on 2026-11-03" in p["trend_exit"]


def test_plan_v3_without_price_or_atr_or_with_a_stop_below_zero():
    assert SS.positional_plan(None, 2, 10)["plan_note"].startswith("No price")
    assert SS.positional_plan(100, None, 10)["plan_note"].startswith("No ATR")
    p = SS.positional_plan(3.0, 2.0, 2.5)
    assert p["plan_ok"] is False and p["stop_loss"] is None and "exceed the price" in p["plan_note"]


def test_no_barred_words_outside_the_plan_words():
    import re
    text = SS.RULES_TEXT + SS.PLAN_TEXT + SS.CAVEAT + " ".join(SS.score(stock())["reasons"])
    assert not re.search(r"\b(buy\w*|sell\w*|recommend\w*|pick\w*)\b", text, re.I)


# ── TC-S11 loaders and the batch scorer ─────────────────────────────────────────────────────────────────────────────

class Daas:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    async def get(self, path, params=None, timeout=None):
        self.calls.append((path, dict(params or {})))
        if path in self.fail:
            raise RuntimeError("down")
        if path == "/features/scan-snapshot":
            return {"as_of": "2026-11-03", "rows": [{"symbol": "AAA", "is_etf": False, "price_band_pct": None},
                                                    {"symbol": "ETFX", "is_etf": True}]}
        if path == "/announcements":
            off = params["offset"]
            if off == 0:
                return {"data": [F("earnings", "positive") | {"ticker_symbol": "AAA"}] * SS.FILINGS_PAGE}
            return {"data": [F("orders", "positive") | {"ticker_symbol": "BBB"}]}
        if path == "/desk/filings":
            return {"articles": [{"symbol": "BBB", "title": "Spurt in Volume"}]}
        raise AssertionError(path)


def test_filings_are_paged_and_cached():
    d = Daas()
    by, _ = asyncio.run(SS.load_filings(d.get, "2026-11-03"))
    assert len(by["AAA"]) == SS.FILINGS_PAGE and len(by["BBB"]) == 1
    assert [c[1]["offset"] for c in d.calls] == [0, SS.FILINGS_PAGE]
    asyncio.run(SS.load_filings(d.get, "2026-11-03"))
    assert len(d.calls) == 2                                                   # cached


def panel_of(symbols, closes):
    T = len(closes)
    n = len(symbols)
    arr = np.tile(np.asarray(closes, float)[:, None], (1, n))
    return SimpleNamespace(symbols=list(symbols), close=arr, high=arr + 0.5, low=arr - 0.5, volume=np.full((T, n), 1e6))


def test_build_scores_scores_every_signalled_stock_and_survives_a_missing_source():
    c = list(rising()) + [float(rising()[-1]) + 3.0]                          # history + today's bar
    pnl = panel_of(["AAA", "ETFX"], c)
    ref = SimpleNamespace(fundamentals={k: {"AAA": v} for k, v in GOOD.items()}, members={"nifty50": {"AAA"}},
                          names={"AAA": "Aaa Industries Ltd"}, fno={"AAA"}, fundamentals_as_of="2026-11-03")
    entries = [{"symbol": "AAA", "widget_id": "dt_52w_high", "widget_title": "52 week high", "direction": "long"},
               {"symbol": "ETFX", "widget_id": "n50_gainers", "widget_title": "x", "direction": "long"},
               {"symbol": "ZZZ", "widget_id": "n50_gainers", "widget_title": "x", "direction": "long"}]
    at = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)

    async def sides(syms):
        return {"AAA": {"ask_trades": 300, "bid_trades": 200}}
    out, meta = asyncio.run(SS.build_scores(Daas(fail={"/desk/filings"}).get, pnl, ref, entries, at, live=True,
                                            eod_day="2026-11-03", side_reader=sides))
    assert out["AAA"]["score"] >= 70 and out["AAA"]["name"] == "Aaa Industries Ltd"
    assert out["AAA"]["reasons"][0].startswith("Results filing")
    assert out["ETFX"]["score"] is None and "ETF" in out["ETFX"]["note"]
    assert out["ZZZ"]["score"] is None and "no price history" in out["ZZZ"]["note"]
    assert meta["counts"] == {"scored": 1, "strong": 1, "below": 0, "not_scored": 2}
    assert any("queries could not be read" in w for w in meta["warnings"]) and meta["threshold"] == 70
    cand = SS.strong_candidate("AAA", out["AAA"], c[-1], "2026-11-03")
    assert cand["plan_ok"] and cand["score_at"] == out["AAA"]["score"] and cand["stop_loss"] < c[-1]


def test_a_negative_filing_is_also_a_penalty_and_unknown_categories_read_as_exchange_filings():
    pen = SS.penalties(stock(), tech(smas={20: 1e4}), 2.0, -8)
    assert any(p["points"] == 10 and "negative filing" in p["text"] for p in pen)
    pts, text = SS.event(stock(filings=[F("other", "positive", "high", "Press Release")]))
    assert pts == 8 and text.startswith("Exchange filing 04 Nov 12:31 IST (positive): Press Release")


def test_filing_texts_never_carry_a_barred_word():
    for subj in ("Buyback", "Entry into an agreement", "Exit from a joint venture", "Target price revision", "Sale and Buy"):
        pts, text = SS.event(stock(filings=[F("buyback", "positive", "high", subj)]))
        assert pts == 12 and not SS.BARRED.search(text) and text.startswith("Share repurchase filing")
    assert SS.event(stock(filings=[F("orders", "positive", "high", "Award of Order")]))[1].endswith(": Award of Order")
