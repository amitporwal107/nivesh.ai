"""Unit tests for the Track 1 watchlist (no DB): next-session calendar, cost buckets, write-once refusal."""
import datetime as dt, json, os, sys
import pandas as pd, pytest
sys.path.insert(0, os.path.dirname(__file__))
import watchlist as W

def test_next_session_skips_weekend_and_holiday():
    hol = {dt.date(2026, 10, 2)}
    assert W.next_session(dt.date(2026, 9, 18), hol) == dt.date(2026, 9, 21)      # Fri -> Mon
    assert W.next_session(dt.date(2026, 10, 1), hol) == dt.date(2026, 10, 5)      # Thu -> holiday Fri -> Mon

def test_cost_buckets_match_cost_model_v1():
    assert W.cost_rt(2e9) == 0.0020 and W.cost_rt(5e8) == 0.0030 and W.cost_rt(6e7) == 0.0040

def test_write_once_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "REPORTS", str(tmp_path))
    repo = tmp_path / "repo"; (repo / os.path.dirname(W.SCOPE)).mkdir(parents=True)
    (repo / W.SCOPE).write_text("scope")
    w = pd.DataFrame({"symbol": ["X"], "next_session": ["2026-09-21"]})
    dq = {"next_session": "2026-09-21", "prev_session": "2026-09-18"}
    W.write(w, dq, None, str(repo))
    with pytest.raises(SystemExit, match="REFUSED"):
        W.write(w, dq, None, str(repo))
    assert os.path.exists(W.write(w, dq, 2, str(repo)))                           # an explicit new version is allowed
