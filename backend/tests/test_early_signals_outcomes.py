"""Early-signals study: outcomes after each flag and the report's arithmetic (research/early_signals).

MOCK — not real data: every candle, flag and stock below is hand-made (symbols AAA, BBB, CCC, DDD on one session)."""
import json
import re

import numpy as np
import pandas as pd
import pytest

from research.early_signals import outcomes as O
from research.early_signals import report as R

DAY = "2026-11-02"
T0 = O.step_ts(DAY, "09:15")


def candles(closes, highs=None, lows=None, opens=None):
    n = len(closes)
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs if highs is not None else c + 0.2, dtype=float)
    l = np.asarray(lows if lows is not None else c - 0.2, dtype=float)
    o = np.asarray(opens if opens is not None else np.r_[c[0], c[:-1]], dtype=float)
    ts = T0 + np.arange(n, dtype=np.int64) * 300
    return {"ts": ts, "o": o, "h": h, "l": l, "c": c, "v": np.full(n, 1000.0)}


def aaa():
    """Climbs 0.5 a candle to 106 by 10:15 (candle 12), then flat; candle 6 (09:45) dips to 97."""
    c = np.array([100 + 0.5 * i if i <= 12 else 106.0 for i in range(75)])
    lows = c - 0.2
    lows[6] = 97.0
    o = np.r_[100.0, c[:-1]]
    return candles(c, c + 0.2, lows, o)


def bbb():
    """Never moves: high 100.5."""
    return candles(np.full(75, 100.0), np.full(75, 100.5), np.full(75, 99.5), np.full(75, 100.0))


def ccc():
    """+6% inside the first candle (09:15–09:20): not catchable by a 15-minute step."""
    c = np.full(75, 105.5)
    h = np.full(75, 105.8)
    h[0] = 106.0
    o = np.full(75, 105.5)
    o[0] = 100.0
    return candles(c, h, np.full(75, 99.9), o)


def ddd():
    """Reaches +5% at candle 25 (11:20–11:25)."""
    c = np.full(75, 101.0)
    c[25:] = 105.3
    h = c + 0.1
    o = np.r_[100.0, c[:-1]]
    return candles(c, h, c - 0.1, o)


def days_of(**bars):
    return {s: O.split_days(b) for s, b in bars.items()}


# ── outcomes ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_open_and_t5_is_the_end_of_the_first_candle_at_plus_five_percent():
    d = O.split_days(aaa())[DAY]
    assert d.open == 100.0
    assert d.t5 == O.step_ts(DAY, "10:10")              # candle 10 (10:05–10:10) is the first with high >= 105
    assert O.split_days(bbb())[DAY].t5 is None
    assert O.split_days(ccc())[DAY].t5 == O.step_ts(DAY, "09:20")


def test_an_early_flag_its_lead_time_move_done_upside_and_drawdown():
    d = O.split_days(aaa())[DAY]
    r = O.outcome(d, DAY, "AAA", "w:A", "widget", "09:45", None)    # price from the candles: close of 09:40–09:45 = 102.5
    assert r["flag_price"] == 102.5 and r["early"] and r["hit"] and not r["late"]
    assert r["lead_min"] == 25.0
    assert r["move_done_pct"] == pytest.approx(2.5)
    assert r["upside_pct"] == pytest.approx((106.2 / 102.5 - 1) * 100)
    assert r["drawdown_pct"] == pytest.approx((97.0 / 102.5 - 1) * 100)   # the 09:45 candle's dip, before the high
    assert r["close_vs_flag_pct"] == pytest.approx((106.0 / 102.5 - 1) * 100)


def test_a_flag_at_or_after_the_move_is_late_not_early():
    d = O.split_days(aaa())[DAY]
    r = O.outcome(d, DAY, "AAA", "w:A", "widget", "10:15", 106.0)
    assert r["late"] and not r["early"] and not r["hit"] and r["lead_min"] is None
    flat = O.outcome(O.split_days(bbb())[DAY], DAY, "BBB", "w:A", "widget", "09:30", 100.0)
    assert flat["early"] and not flat["hit"] and flat["drawdown_pct"] == pytest.approx((99.5 / 100 - 1) * 100)


def test_a_flag_price_from_the_replay_is_used_when_given():
    d = O.split_days(aaa())[DAY]
    assert O.outcome(d, DAY, "AAA", "w:A", "widget", "09:45", 102.0)["flag_price"] == 102.0
    assert O.outcome(d, DAY, "AAA", "w:A", "widget", "09:45", float("nan"))["flag_price"] == 102.5


def flags_df(rows):
    return pd.DataFrame(rows, columns=["day", "step", "symbol", "widget", "close_at_step"])


FLAGS = [
    (DAY, "09:45", "AAA", "A", np.nan), (DAY, "10:00", "AAA", "A", np.nan), (DAY, "10:00", "AAA", "B", np.nan),
    (DAY, "10:30", "AAA", "A", np.nan),
    (DAY, "09:30", "BBB", "A", np.nan),
    (DAY, "09:30", "CCC", "B", np.nan),
]


def test_first_flags_confluence_and_pairs():
    f = O.first_signals(flags_df(FLAGS))
    got = {(r.signal, r.symbol): r.step for r in f.itertuples()}
    assert got[("w:A", "AAA")] == "09:45" and got[("w:B", "AAA")] == "10:00"
    assert got[("k>=1", "AAA")] == "09:45"
    assert got[("k>=2", "AAA")] == "10:00"                  # A and B at the same step first at 10:00
    assert got[("p:A+B", "AAA")] == "10:00"
    assert ("k>=2", "BBB") not in got and ("k>=3", "AAA") not in got
    assert len(f[(f.signal == "w:A") & (f.symbol == "AAA")]) == 1    # first flag only


# ── report arithmetic ───────────────────────────────────────────────────────────────────────────────────────────────

def run_report(tmp_path, titles=None, min_support=1):
    bars = tmp_path / "bars"
    bars.mkdir()
    for s, b in {"AAA": aaa(), "BBB": bbb(), "CCC": ccc(), "DDD": ddd()}.items():
        np.savez(bars / f"{s}.npz", **b)
    flags_df(FLAGS).to_csv(tmp_path / "flags.csv", index=False)
    pd.DataFrame({"day": [DAY] * 4, "symbol": ["AAA", "BBB", "CCC", "DDD"]}).to_csv(tmp_path / "universe.csv", index=False)
    return R.run(str(bars), str(tmp_path / "flags.csv"), str(tmp_path / "universe.csv"), min_support=min_support,
                 titles=titles if titles is not None else {"A": "Widget A", "B": "Widget B"})


def test_precision_base_rate_lift_and_recall(tmp_path):
    md, summary, outs = run_report(tmp_path)
    st = {s["signal"]: s for s in summary["signals"]}
    a = st["w:A"]                                # AAA 09:45 (reaches +5% at 10:10) and BBB 09:30 (never)
    assert (a["flagged"], a["late"], a["eligible"], a["hits"]) == (2, 0, 2, 1)
    assert a["precision"] == pytest.approx(0.5)
    # base rate at 09:30 and 09:45: of AAA, BBB, DDD still below +5% (CCC was above from 09:20), AAA and DDD reach it -> 2/3
    assert a["base_rate"] == pytest.approx(2 / 3) and a["lift"] == pytest.approx(0.75)
    assert a["recall"] == pytest.approx(1 / 3)          # movers: AAA, CCC, DDD
    assert a["recall_catchable"] == pytest.approx(1 / 2)  # CCC moved before the first step
    assert a["median_lead_min"] == 25.0
    b = st["w:B"]                                # AAA at 10:00 (early, 10 min lead) and CCC at 09:30 (late)
    assert (b["flagged"], b["late"], b["eligible"], b["hits"]) == (2, 1, 1, 1)
    assert b["precision"] == 1.0 and b["lift"] == pytest.approx(1.5) and b["median_lead_min"] == 10.0
    assert st["k>=2"]["hits"] == 1 and st["p:A+B"]["eligible"] == 1
    assert a["by_time"]["before 10:00"] == {"eligible": 2, "hits": 1, "precision": 0.5}
    assert summary["meta"]["movers"] == 3 and summary["meta"]["stock_days"] == 4
    assert "Widget A + Widget B" in md and "Any 2 widgets at the same step" in md
    json.dumps(R.clean_json(summary), allow_nan=False)   # strict JSON


def test_minimum_support_keeps_thin_rows_out_of_the_ranking(tmp_path):
    md, _, _ = run_report(tmp_path, min_support=2)
    single = md.split("## Single widgets")[1].split("## ")[0]
    ranked, thin = single.split("Below the minimum support")
    assert "Widget A" in ranked and "Widget B" not in ranked and "Widget B" in thin


BARRED = re.compile(r"\b(buy\w*|sell\w*|target\w*|stop ?loss\w*|sl|pick\w*|recommend\w*|entry|exit\w*)\b", re.I)


def test_the_report_never_uses_barred_trading_words(tmp_path):
    md, summary, _ = run_report(tmp_path)
    assert BARRED.findall(md) == []
    assert BARRED.findall(json.dumps(R.clean_json(summary))) == []
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError):
        run_report(other, titles={"A": "Top buy", "B": "B"})       # a barred word in a title stops the report


def test_signal_with_only_late_flags_scores_without_error():
    # Staging smoke run 3 Nov: a signal whose every flag came after the +5 % crossing left an empty frame, and the
    # time-of-day buckets indexed it with an empty object Series (read as column labels) -> KeyError 'hit'.
    import pandas as pd
    from research.early_signals import outcomes as O, report as R
    rows = pd.DataFrame([{c: None for c in O.OUTCOME_COLUMNS}])
    rows.loc[0, ["signal", "kind", "day", "step", "early", "hit", "late"]] = ["w:x", "widget", "2026-11-03", "10:00", False, False, True]
    sd = pd.DataFrame({"day": ["2026-11-03"], "symbol": ["AAA"], "t5": [None]})
    st = R.signal_stats(rows, sd, {})
    assert st["eligible"] == 0 and st["precision"] is None and st["late"] == 1
