"""Publishing frozen snapshots for the Research page (test cases TC-15..TC-19 in
test_reports/move_odds_research_20260916_2351.md). The publisher reads only verified, counted snapshots and emits one
idempotent psql script; nothing touches a database unless --apply is given."""
import json
import sqlite3
from datetime import date, datetime

import pandas as pd
import pytest

from nidp.tests.services.tpd_model.conftest import IST, make_panel, weekday_sessions

HEADS = ("p_up10_1d", "p_down10_1d", "p_up5_1d", "p_down5_1d")


def _snapshot(root, T, D, **meta_over):
    from nidp.services.tpd_model.forward import freeze

    preds = pd.DataFrame([{"symbol": s, "head": h, "p_tpd3": p, "p_atr_only": 0.02, "p_own_history_only": 0.02, "p_base_rate": 0.05}
                          for h in HEADS for s, p in (("AAA", 0.36), ("BBB", 0.04))])
    meta = {"data_as_of": str(T), "target_session": str(D), "fold_month": "2026-09", "lock_sha256": "c" * 64, "git_sha": "a" * 40,
            "model": "v4", "columns": 84, "universe_size": 1000, "skipped_holidays": [], "preview": False, "counts_toward_verdict": True,
            "filed_today_in_universe": 1, "train": {h: {"train_rows": 366080, "train_end_max_horizon": "2026-08-31"} for h in HEADS}}
    meta.update(meta_over)
    live = "symbol,period_end,consolidated,revenue_from_ops_cr,pat_cr,eps_basic,broadcast_at\nAAA,2026-06-30,True,10,1,0.1,2026-09-15 14:03:06+00:00\n"
    return freeze(root, preds, meta, now=datetime(2026, 9, 15, 20, 50, tzinfo=IST), rehearsal=bool(meta_over.get("rehearsal")),
                  extra_files={"results_live.csv": live.encode(), "high_confidence.csv": b"head,symbol,p_tpd3\n"})


def _dates():
    s = weekday_sessions("2026-07-01", 55)
    return s, s[-1], date(2026, 9, 16)


def test_tampered_snapshot_is_refused_and_nothing_is_emitted(tmp_path):
    from nidp.services.tpd_model.forward import TamperError
    from nidp.services.tpd_model.publish import load_publishable

    s, T, D = _dates()
    snap = _snapshot(tmp_path, T, D)
    (snap / "tpd3_predictions.csv").write_text((snap / "tpd3_predictions.csv").read_text().replace("0.36", "0.96"))
    with pytest.raises(TamperError):
        load_publishable(snap)


def test_rehearsal_and_preview_snapshots_are_not_publishable(tmp_path):
    from nidp.services.tpd_model.publish import PublishRefused, load_publishable

    s, T, D = _dates()
    with pytest.raises(PublishRefused, match="preview"):
        load_publishable(_snapshot(tmp_path / "p", T, D, preview=True, counts_toward_verdict=False))
    with pytest.raises(PublishRefused, match="rehearsal"):
        load_publishable(_snapshot(tmp_path / "r", T, D, rehearsal=True, counts_toward_verdict=False))
    manifest, preds, filed = load_publishable(_snapshot(tmp_path / "ok", T, D))
    assert manifest["model"] == "v4" and len(preds) == 8 and filed == {"AAA"}


def test_inputs_on_record_carry_values_and_their_own_data_dates():
    from nidp.services.tpd_model.publish import INPUT_KEYS, inputs_on_record

    s, T, D = _dates()
    panel = make_panel(["AAA", "BBB"], s)
    panel.loc[(panel["symbol"] == "AAA") & (panel["as_of_date"] == pd.Timestamp(T)), "deliverable_pct"] = float("nan")   # delivery lags a day
    rec = inputs_on_record(panel, ["AAA", "BBB", "ZZZ"], T)
    a = rec["AAA"]
    assert list(a) == list(INPUT_KEYS)
    row = panel[(panel["symbol"] == "AAA") & (panel["as_of_date"] == pd.Timestamp(T))].iloc[0]
    assert a["close_change_pct"]["v"] == pytest.approx(round((row["close"] / row["prev_close"] - 1) * 100, 2))
    assert a["close_change_pct"]["date"] == str(T) and a["delivery_pct"]["date"] == str(s[-2])
    assert all(set(v) == {"v", "date"} for v in a.values())
    assert "ZZZ" not in rec                                             # no bar on T: no inputs, never zeros


def _events_db(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE stock_events (symbol TEXT, event_id TEXT, event_time TEXT, source TEXT, source_url TEXT, event_type TEXT, event_subtype TEXT, "
               "direction TEXT, catalyst_score REAL, title TEXT, classification_method TEXT)")
    rows = [("AAA", "e1", "2026-09-14T21:02:18+05:30", "nse_announcements_api", "https://nse/x.pdf", "REGULATORY", "debarment", "negative", 90, "AAA: Action(s) taken", "RULE"),
            ("AAA", "e2", "2026-09-15T10:13:00+05:30", "et_stocks", "https://et/y", "REGULATORY", "debarment", "negative", 46, "AAA shares tank; should you buy?", "RULE"),
            ("AAA", "e3", "2026-09-15T11:00:00+05:30", "mint_markets", "https://mint/z", "CONTRACT", "order_win", "positive", 40, "AAA wins order, a best pick", "RULE+LLM"),
            ("AAA", "e4", "2026-09-15T12:00:00+05:30", "bse_subcat_api", "https://bse/w", "CAPITAL", "dividend", "positive", 10, "AAA dividend", "RULE"),
            ("AAA", "e5", "2026-09-15T13:00:00+05:30", "cnbc_market", "https://cnbc/v", "UNCLASSIFIED", "unclassified", "neutral", 3, "AAA stocks to buy", "RULE"),
            ("AAA", "e6", "2026-09-09T13:00:00+05:30", "nse_announcements_api", "https://nse/old", "CAPITAL", "bonus", "positive", 60, "AAA old bonus", "RULE"),
            ("AAA", "e7", "2026-09-15T21:30:00+05:30", "nse_announcements_api", "https://nse/late", "M&A", "open_offer", "positive", 70, "AAA after the freeze", "RULE"),
            ("BBB", "e8", "2026-09-15T09:00:00+05:30", "nhai_news", "https://nhai/clip.pdf", "GOVERNMENT", "policy", "mixed", 30, "Clipping", "RULE")]
    db.executemany("INSERT INTO stock_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows); db.commit(); db.close()


def test_events_on_record_withhold_media_titles_and_respect_the_window_and_limit(tmp_path):
    from nidp.services.tpd_model.publish import events_on_record

    _events_db(tmp_path / "ev.sqlite")
    T = date(2026, 9, 15); frozen = datetime(2026, 9, 15, 20, 50, tzinfo=IST)
    ev = events_on_record(tmp_path / "ev.sqlite", ["AAA", "BBB"], T, frozen)
    a = ev["AAA"]
    assert [e["ord"] for e in a] == [1, 2, 3]
    assert a[0]["event_subtype"] == "debarment" and a[0]["title"] == "AAA: Action(s) taken" and a[0]["is_media"] is False
    assert all(e["event_subtype"] != "unclassified" for e in a)                        # unclassified never listed
    assert {e["event_subtype"] for e in a} == {"debarment", "order_win", "dividend"}     # one per subtype, highest score first
    assert not any("old bonus" in (e["title"] or "") or "after the freeze" in (e["title"] or "") for e in a)   # 5 calendar days to the freeze
    media = [e for e in a if e["is_media"]]
    assert media and all(e["title"] is None for e in media) and media[0]["source_label"] == "Mint"
    assert ev["BBB"][0]["is_media"] is True and ev["BBB"][0]["title"] is None and ev["BBB"][0]["source_label"] == "NHAI press clippings"


def test_run_script_is_one_idempotent_transaction_keyed_on_the_manifest_hash(tmp_path):
    from nidp.services.tpd_model.publish import load_publishable, manifest_sha, run_script

    s, T, D = _dates()
    snap = _snapshot(tmp_path, T, D)
    manifest, preds, filed = load_publishable(snap)
    stocks = {"AAA": {"company_name": "Alpha O'Brien Ltd", "sector": "Chemicals", "inputs": {"close_change_pct": {"v": 1.2, "date": str(T)}}},
              "BBB": {"company_name": "Beta Ltd", "sector": "", "inputs": {}}}
    events = {"AAA": [{"ord": 1, "event_time": "2026-09-14T21:02:18+05:30", "source_label": "NSE filing", "is_media": False, "event_type": "REGULATORY",
                       "event_subtype": "debarment", "direction": "negative", "title": "AAA: Action(s) taken", "url": "https://nse/x.pdf", "method": "rules"}]}
    sql = run_script(manifest, manifest_sha(snap), preds, stocks, events, filed)
    sha = manifest_sha(snap)
    assert sql.startswith("\\set ON_ERROR_STOP on") and sql.count("BEGIN;") == 1 and sql.rstrip().endswith("COMMIT;")
    assert f"ON CONFLICT (snapshot_sha256) DO NOTHING" in sql and sql.count(f"r.snapshot_sha256 = '{sha}'") == 3
    assert sql.count("ON CONFLICT DO NOTHING") == 3 and "Alpha O''Brien" not in sql          # CSV via COPY, not string-built SQL
    assert "COPY _est FROM STDIN" in sql and "\n\\.\n" in sql
    assert "'v4'" in sql and f"'{T}'" in sql and f"'{D}'" in sql and "'final'" in sql
    est_block = sql.split("COPY _est FROM STDIN WITH (FORMAT csv, HEADER true);\n", 1)[1].split("\n\\.\n", 1)[0]
    assert est_block.splitlines()[0] == "head,symbol,p,p_base_rate" and len(est_block.splitlines()) == 9


def test_model_record_script_reads_the_pre_registered_test_window(tmp_path):
    from nidp.services.tpd_model.publish import record_script

    verdict = {"graded_sessions": 165, "heads": {h: {"base_rate": 0.08, "p10": 0.31, "rows_by_p_band": {"0.00-0.05": {"rows": 10, "realised": 0.03}, "0.60-1.01": {"rows": 0, "realised": None}}} for h in HEADS}}
    p = tmp_path / "v.json"; p.write_text(json.dumps(verdict))
    sql = record_script("v4", p, "Jan–Aug 2025")
    assert sql.count("INSERT INTO nidp.tpd_model_record") == 4 and sql.count("ON CONFLICT DO NOTHING") >= 8
    assert "'test_2025', 0.6, 1.0, 0, NULL)" in sql and "'test_2025', 0.0, 0.05, 10, 0.03)" in sql and "'Jan–Aug 2025'" in sql
