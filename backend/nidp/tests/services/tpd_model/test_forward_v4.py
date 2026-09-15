"""v4 forward mechanics: grading all four heads, refusing to score while the print window is still open or without
the evening results capture, and the >=50% rows listed separately in the snapshot."""
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST, make_panel, weekday_sessions

T, D = date(2026, 9, 15), date(2026, 9, 16)


def _panel(include_target=True):
    s = weekday_sessions("2026-06-01", 76)
    p = make_panel(["AAA", "BBB"], s)
    extra = []
    for sym, c in {"AAA": 100.0, "BBB": 50.0}.items():
        extra.append({"symbol": sym, "as_of_date": pd.Timestamp(T), "series": "EQ", "source": "NSE_BHAVCOPY", "open": c, "high": c, "low": c,
                      "close": c, "prev_close": c, "volume": 1000, "turnover": 1e5, "deliverable_pct": 50.0})
    if include_target:
        extra.append({**extra[0], "as_of_date": pd.Timestamp(D), "high": 106.0, "low": 99.0, "close": 105.0})   # +6%: 5% yes, 10% no
        extra.append({**extra[1], "as_of_date": pd.Timestamp(D), "high": 51.0, "low": 44.0, "close": 45.0})    # -12%: both down heads
    return pd.concat([p, pd.DataFrame(extra)], ignore_index=True)


def _preds():
    rows = []
    for head in ("p_up10_1d", "p_down10_1d", "p_up5_1d", "p_down5_1d"):
        for sym, p in (("AAA", 0.55), ("BBB", 0.10)):
            rows.append({"symbol": sym, "head": head, "p_tpd3": p, "p_atr_only": 0.02, "p_own_history_only": 0.02, "p_base_rate": 0.02})
    return pd.DataFrame(rows)


def _meta():
    return {"data_as_of": str(T), "target_session": str(D), "fold_month": "2026-09", "lock_sha256": "c" * 64, "git_sha": "a" * 40}


def test_grade_v4_labels_all_four_heads_once_bars_exist(tmp_path):
    from nidp.services.tpd_model.forward import freeze
    from nidp.services.tpd_model.forward_v4 import grade_v4

    snap = freeze(tmp_path, _preds(), _meta(), now=datetime(2026, 9, 15, 21, 0, tzinfo=IST))
    none = pd.DataFrame(columns=["symbol", "ex_date"])
    assert grade_v4(snap, _panel(False), none) is None
    g = grade_v4(snap, _panel(True), none).set_index(["head", "symbol"])["y"]
    assert g[("p_up5_1d", "AAA")] == 1.0 and g[("p_up10_1d", "AAA")] == 0.0
    assert g[("p_down5_1d", "BBB")] == 1.0 and g[("p_down10_1d", "BBB")] == 1.0 and g[("p_down5_1d", "AAA")] == 0.0


def test_high_confidence_rows_are_listed_in_their_own_file():
    from nidp.services.tpd_model.forward_v4 import high_confidence_rows

    hc = high_confidence_rows(_preds(), threshold=0.5)
    assert set(hc["symbol"]) == {"AAA"} and len(hc) == 4 and list(hc.columns[:3]) == ["head", "symbol", "p_tpd3"]


def test_score_refuses_while_the_print_window_is_open():
    from nidp.services.tpd_model.forward_v4 import PrintWindowOpenError, check_print_window_closed

    check_print_window_closed(T, now=datetime(2026, 9, 15, 20, 31, tzinfo=IST))
    with pytest.raises(PrintWindowOpenError):
        check_print_window_closed(T, now=datetime(2026, 9, 15, 20, 29, tzinfo=IST))


def test_score_requires_the_evening_capture_for_T(tmp_path):
    from nidp.services.tpd_model.forward_v4 import MissingCaptureError, load_capture

    with pytest.raises(MissingCaptureError):
        load_capture(tmp_path, T)
    (tmp_path / f"{T}.csv").write_text("symbol,period_end,consolidated,revenue_from_ops_cr,pat_cr,eps_basic,broadcast_at\n")
    (tmp_path / f"{T}.csv.stats.json").write_text(json.dumps({"date": str(T), "listed": 0, "in_print_window": 0, "parsed": 0, "failed": []}))
    live, stats = load_capture(tmp_path, T)
    assert live.empty and stats["listed"] == 0


def test_v4_forward_lock_is_pre_registered():
    from nidp.services.tpd_model.forward_v4 import LOCK_V4
    from nidp.services.tpd_model.report import load_lock

    lock, sha = load_lock(LOCK_V4)
    assert lock["role"] == "forward" and lock["forward_window"]["first_target_session"] == "2026-09-17"
    assert lock["high_confidence"]["threshold"] == 0.50 and lock["high_confidence"]["min_rows_to_judge"] == 30
    assert lock["capture_health"]["min_share"] == 0.90 and len(sha) == 64


def test_preview_scores_before_the_forward_window_but_never_counts():
    """User 2026-09-15 'please run it for today': a real-clock snapshot for a target before the locked forward window
    is allowed only as a preview, which is marked as not counting toward the verdict."""
    from nidp.services.tpd_model.forward_v4 import window_decision

    lock = {"forward_window": {"first_target_session": "2026-09-17"}}
    assert window_decision(date(2026, 9, 16), lock, rehearsal=False, preview=False) == ("skip", None)
    assert window_decision(date(2026, 9, 16), lock, rehearsal=False, preview=True) == ("score", {"preview": True, "counts_toward_verdict": False})
    assert window_decision(date(2026, 9, 17), lock, rehearsal=False, preview=False) == ("score", {"preview": False, "counts_toward_verdict": True})
    assert window_decision(date(2026, 9, 17), lock, rehearsal=False, preview=True) == ("score", {"preview": True, "counts_toward_verdict": False})
    assert window_decision(date(2026, 8, 14), lock, rehearsal=True, preview=False) == ("score", {"preview": False, "counts_toward_verdict": False})
