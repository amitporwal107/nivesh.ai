"""The RS63 confirmation's readiness counter (research/p4_adx_rs/check_rs63_readiness.py; TC-RS-1 of
test_reports/p4_research_hardening_TESTCASES.md, registration docs/ai_research/P4_RS63_CONFIRMATION_PREREGISTRATION.md).

Synthetic calendars and Nifty 50 closes, MOCK — not real data: a weekday calendar, and closes built so that the regime of
each date (close vs the mean of the 200 closes ending on it) is known by construction.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_rs63_readiness", ROOT / "research" / "p4_adx_rs" / "check_rs63_readiness.py")
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


def weekdays(start: date, n: int):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def world(n_after: int, ups: int, *, before: int = 220, start=date(2025, 12, 1)):
    """`before` sessions up to and including 2026-10-09 at a flat 100, then `n_after` sessions after it. Of the dates after
    the cutoff, the first `ups` close at 200 (above any 200-session mean that includes 100s), the rest at 50 (below)."""
    pre = weekdays(start, 400)
    pre = [d for d in pre if d <= rs.CUTOFF][-before:]
    post = weekdays(rs.CUTOFF + timedelta(days=1), n_after)
    closes = {d: 100.0 for d in pre}
    for k, d in enumerate(post):
        closes[d] = 200.0 if k < ups else 50.0
    return pre + post, closes


def test_dates_on_or_before_the_cutoff_never_count_and_the_last_ten_await_their_outcome():
    s, c = world(15, 15)
    r = rs.readiness(s, c, as_of=date(2026, 11, 1))
    assert r["signal_dates_after_cutoff"] == 15
    assert r["complete_dates"] == 5 and r["pending_outcome"]["count"] == 10          # i + 10 must exist in the calendar
    assert r["first_complete"] > rs.CUTOFF.isoformat() and r["status"] == "NOT_READY"


def test_ready_at_exactly_sixty_with_twenty_and_forty():
    # 70 sessions after the cutoff: 60 complete. The first 20 close at 200 ("up": above the mean of 180 × 100 + 20 × 200
    # at most), the other 40 at 50 ("down").
    s, c = world(70, 20)
    r = rs.readiness(s, c, as_of=date(2027, 1, 30))
    assert r["complete_dates"] == 60 and r["by_regime"] == {"up": 20, "down": 40}
    assert r["status"] == "READY" and r["reasons"] == []


def test_not_ready_at_fifty_nine():
    s, c = world(69, 20)
    r = rs.readiness(s, c, as_of=date(2027, 1, 30))
    assert r["complete_dates"] == 59 and r["status"] == "NOT_READY"
    assert any("1 more signal date" in x for x in r["reasons"])


def test_not_ready_with_a_regime_short_then_single_regime_after_the_deadline():
    s, c = world(80, 19)
    r = rs.readiness(s, c, as_of=date(2027, 3, 1))
    assert r["complete_dates"] == 70 and r["by_regime"] == {"up": 19, "down": 51}
    assert r["status"] == "NOT_READY" and any("1 more 'up'" in x for x in r["reasons"])
    late = rs.readiness(s, c, as_of=date(2027, 7, 1))
    assert late["status"] == "RUN_SINGLE_REGIME" and any("single-regime" in x for x in late["reasons"])
    # the deadline does not waive the 60 dates
    s2, c2 = world(65, 0)
    assert rs.readiness(s2, c2, as_of=date(2027, 7, 1))["status"] == "NOT_READY"


def test_a_missing_nifty_close_makes_the_regime_unknown_never_guessed():
    s, c = world(70, 20)
    gap = s[-60]                                                        # a complete date after the cutoff
    c[gap] = None
    r = rs.readiness(s, c, as_of=date(2027, 1, 30))
    # every complete date whose 200-session window contains the gap has no regime
    assert r["regime_unknown"]["count"] >= 1 and gap.isoformat() in r["regime_unknown"]["dates"]
    assert r["complete_dates_known_regime"] == 60 - r["regime_unknown"]["count"] and r["status"] == "NOT_READY"


def test_fewer_than_two_hundred_closes_is_unknown():
    s, c = world(70, 20, before=150)
    r = rs.readiness(s, c, as_of=date(2027, 1, 30))
    # date index i has a regime only when i + 1 >= 200: the first 49 dates after the cutoff (indices 150..198) do not
    assert r["regime_unknown"]["count"] == 49 and r["complete_dates_known_regime"] == 11


def test_bad_inputs_are_data_errors(tmp_path):
    with pytest.raises(rs.DataError):
        rs.readiness([], {}, as_of=date(2027, 1, 1))
    with pytest.raises(rs.DataError):
        rs.readiness([date(2026, 1, 2), date(2026, 1, 1)], {}, as_of=date(2027, 1, 1))
    (tmp_path / "sessions.csv").write_text("as_of_date\n2026-01-01\n")
    assert rs.main(["--csv-dir", str(tmp_path)]) == 2                   # nifty50.csv is missing


def test_cli_reads_the_csv_exports_and_exits_one_when_not_ready(tmp_path, capsys):
    s, c = world(30, 10)
    (tmp_path / "sessions.csv").write_text("as_of_date\n" + "".join(f"{d.isoformat()}\n" for d in s))
    (tmp_path / "nifty50.csv").write_text("as_of_date,close_price\n" + "".join(f"{d.isoformat()},{v}\n" for d, v in c.items()))
    assert rs.main(["--csv-dir", str(tmp_path), "--as-of", "2026-12-01", "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "NOT_READY" and out["complete_dates"] == 20
    assert out["reads"] == "sessions and Nifty 50 closes only; no stock prices, scores or outcomes"


def test_print_sql_is_read_only_and_reads_no_stock_data(capsys):
    assert rs.main(["--print-sql"]) == 0
    sql = capsys.readouterr().out
    assert sql.count("SELECT") == 2 and "nidp.index_eod" in sql and "'Nifty 50'" in sql
    for word in ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "stock_features", "positional", "close_price, symbol"):
        assert word not in sql
