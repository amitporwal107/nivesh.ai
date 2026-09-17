"""Live prices and the pre-registered breakout conditions for the Move odds screen (Yahoo Finance; rule in
.claude/workspace/ten-percent-days-3/evidence/entry_signal/PREREGISTRATION.md). The condition logic must match the
backtest exactly: completed 60-minute bars from the second bar on; first bar where all five hold."""
from datetime import datetime, timedelta, timezone

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


def _bar(h, m, o, hi, lo, c, v):
    return {"start": datetime(2026, 9, 17, h, m, tzinfo=IST), "open": o, "high": hi, "low": lo, "close": c, "volume": v}


BARS = [_bar(9, 15, 100, 102, 99, 101, 400_000),      # first hour: high 102
        _bar(10, 15, 101, 102.5, 100.5, 101.8, 200_000),  # close 101.8 < 102: no breakout yet
        _bar(11, 15, 101.8, 103.5, 101.5, 103.2, 300_000),  # close 103.2 > 102, above VWAP, above prev close, high 103.5 < 105
        _bar(12, 15, 103.2, 105.4, 103.0, 105.0, 250_000)]  # touches 105


def test_conditions_first_met_on_the_first_completed_bar_where_all_five_hold():
    from services.move_odds_live import evaluate_conditions

    r = evaluate_conditions(BARS, prev_close=100.0, adv20=1_000_000, now=datetime(2026, 9, 17, 13, 20, tzinfo=IST))
    assert r["evaluated_bars"] == 4 and r["first_met_at"] == "11:15-12:15" and r["close_at_first_met"] == pytest.approx(103.2)
    last = r["latest"]                                                    # the 12:15 bar: level already touched → room fails
    assert last["room_to_level"] is False and last["above_prev_close"] is True
    assert r["at_first_met"]["volume_pace"] is True and r["at_first_met"]["above_vwap"] is True


def test_the_bar_in_progress_is_never_used():
    from services.move_odds_live import evaluate_conditions

    r = evaluate_conditions(BARS, prev_close=100.0, adv20=1_000_000, now=datetime(2026, 9, 17, 12, 5, tzinfo=IST))   # 11:15 bar still open
    assert r["evaluated_bars"] == 2 and r["first_met_at"] is None and r["latest"]["above_opening_range"] is False


def test_volume_pace_scales_with_elapsed_minutes():
    from services.move_odds_live import evaluate_conditions

    r = evaluate_conditions(BARS, prev_close=100.0, adv20=10_000_000, now=datetime(2026, 9, 17, 13, 20, tzinfo=IST))   # thin volume
    assert r["first_met_at"] is None and r["at_first_met"] is None
    assert evaluate_conditions(BARS[:1], prev_close=100.0, adv20=1_000_000, now=datetime(2026, 9, 17, 11, 0, tzinfo=IST))["first_met_at"] is None   # first bar only: no signal


def test_missing_inputs_give_no_conditions_rather_than_a_guess():
    from services.move_odds_live import evaluate_conditions

    assert evaluate_conditions(BARS, prev_close=100.0, adv20=None, now=datetime(2026, 9, 17, 13, 20, tzinfo=IST)) is None
    assert evaluate_conditions([], prev_close=100.0, adv20=1_000_000, now=datetime(2026, 9, 17, 13, 20, tzinfo=IST)) is None


def test_quote_summary_levels_touches_and_session_date():
    from services.move_odds_live import summarise_quote

    meta = {"regularMarketPrice": 136.0, "chartPreviousClose": 134.44, "regularMarketDayHigh": 141.5, "regularMarketDayLow": 132.2,
            "regularMarketVolume": 1_098_574, "regularMarketTime": int(datetime(2026, 9, 17, 9, 53, 21, tzinfo=IST).timestamp())}
    q = summarise_quote("PNCINFRA", meta)
    assert q["session_date"] == "2026-09-17" and q["quote_time"].startswith("2026-09-17T09:53:21")
    assert q["change_pct"] == pytest.approx((136.0 / 134.44 - 1) * 100, abs=1e-6)
    assert q["touched"] == {"p_up5_1d": True, "p_down5_1d": False, "p_up10_1d": False, "p_down10_1d": False}   # 141.5 ≥ 141.16
    assert q["levels"]["p_up5_1d"] == pytest.approx(round(134.44 * 1.05, 2))
    assert summarise_quote("X", {"regularMarketPrice": None, "chartPreviousClose": 10}) is None


def test_bars_from_chart_drop_the_trailing_quote_point_and_empty_rows():
    from services.move_odds_live import bars_from_chart

    t0 = int(datetime(2026, 9, 17, 9, 15, tzinfo=IST).timestamp())
    res = {"timestamp": [t0, t0 + 3600, t0 + 2400 + 3600],
           "indicators": {"quote": [{"open": [100, 101, 101.5], "high": [102, 102.5, 101.9], "low": [99, 100.5, 101.2], "close": [101, 101.8, 101.5], "volume": [400_000, 200_000, 0]}]}}
    bars = bars_from_chart(res)
    assert [b["start"].strftime("%H:%M") for b in bars] == ["09:15", "10:15"]             # 10:55 point is not on the :15 grid


def test_adv20_uses_the_twenty_sessions_before_today():
    from services.move_odds_live import adv20_from_daily

    days = [datetime(2026, 8, d, 9, 15, tzinfo=IST) for d in range(1, 31)] + [datetime(2026, 9, 17, 9, 15, tzinfo=IST)]
    vols = list(range(1, 31)) + [10_000]
    res = {"timestamp": [int(d.timestamp()) for d in days], "indicators": {"quote": [{"volume": vols}]}}
    assert adv20_from_daily(res, today=datetime(2026, 9, 17).date()) == pytest.approx(sum(range(11, 31)) / 20)


def test_signal_record_states_the_failed_test_and_no_field_name_carries_banned_vocabulary():
    import re
    from services import move_odds_live as live

    assert live.ENTRY_SIGNAL_VALIDATED is False and live.SIGNAL_RECORD["mean_net_return"] < 0 and live.SIGNAL_RECORD["ci95_mean_net_return"][1] < 0
    r = live.evaluate_conditions(BARS, prev_close=100.0, adv20=1_000_000, now=datetime(2026, 9, 17, 13, 20, tzinfo=IST))
    keys = set()
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items(): keys.add(k); walk(v)
    walk(r); walk(live.SIGNAL_RECORD)
    banned = re.compile(r"\b(buy|sell|invest|hold|entry|stop|target|conviction|position|multibagger|best|pick|signal)\b", re.I)
    assert not [k for k in keys if banned.search(k.replace("_", " "))], [k for k in keys if banned.search(k.replace("_", " "))]
