"""Move odds filing analysis (TC-1..TC-11 in test_reports/move_odds_filing_analysis_20260930.md).
The selection rules run on real-shaped documents (copied from staging event_ai_analysis); the route runs behind the
real move_odds gate with the Mongo read injected."""
import copy
from datetime import datetime, timedelta, timezone

from services.move_odds_filing_analysis import select, ISOLATED

NOW = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)


def _analysis(aid, days_ago=1, analyzed_hours_ago=1, iso=ISOLATED, mode="batch50_compact", **kw):
    d = {"_id": f"NSE_ANN:{aid}:cb6aba425f7b:sonnet-5:{mode}", "announcement_id": aid, "source": "NSE_ANN", "symbol": "SAPPHIRE",
         "event_ts": NOW - timedelta(days=days_ago), "exchange_category": "Action(s) taken or orders passed", "mode": mode,
         "model_tag": "sonnet-5", "tool_isolation": iso, "event_type": "LITIGATION", "event_subtype": "GST SCN Tamil Nadu",
         "event_certainty": "proposed", "net_band": "slightly_negative", "net_impact_score": -25, "materiality_score": 35,
         "confidence_score": 55, "analyzed_at": NOW - timedelta(hours=analyzed_hours_ago),
         "input": {"document_text": "SECRET RESEARCH TEXT"},
         "analysis": {"sum": f"summary {aid}", "pf": [], "nf": [["GST SCN alleging ~Rs516.8cr", 20, "p"], ["Not adjudicated", 10, "p"]],
                      "unk": ["Final adjudication outcome"]}}
    d.update(kw)
    return d


def _filter(aid, include, imp, mode="filter_v1", status="CONFIRMED"):
    return {"announcement_id": aid, "source": "NSE_ANN", "symbol": "SAPPHIRE", "mode": mode, "tool_isolation": ISOLATED,
            "include": include, "event_importance_score": imp, "resolution_status": status, "event_ts": NOW - timedelta(days=1)}


def _resolution(aid, status, imp):
    return {"announcement_id": aid, "source": "NSE_ANN", "symbol": "SAPPHIRE", "mode": "resolution_v1", "tool_isolation": ISOLATED,
            "resolution_status": status, "event_importance_score": imp, "event_ts": NOW - timedelta(days=1)}


def test_tc1_kept_isolated_analysis_is_returned_with_its_reading():
    out = select([_analysis("a1"), _filter("a1", True, 70)], NOW)
    [r] = out["rows"]
    assert r["summary"] == "summary a1" and r["impact_band"] == "slightly_negative" and r["materiality_score"] == 35
    assert r["certainty"] == "proposed" and r["evidence_status"] == "CONFIRMED" and r["importance_score"] == 70
    assert r["negative_factors"] == ["GST SCN alleging ~Rs516.8cr", "Not adjudicated"] and r["exchange"] == "NSE"
    assert out["more"] == 0 and out["window_days"] == 30


def test_tc2_not_isolated_analysis_is_never_shown():
    assert select([_analysis("a1", iso="NOT_ISOLATED_tools_were_available")], NOW)["rows"] == []


def test_tc3_filter_drop_without_a_keep_is_hidden():
    assert select([_analysis("a1"), _filter("a1", False, 40), _filter("a1", False, 45, mode="filter_v1_second")], NOW)["rows"] == []
    # resolution confirming a low-importance event does not keep it
    assert select([_analysis("a1"), _filter("a1", False, 40), _resolution("a1", "CONFIRMED", 25)], NOW)["rows"] == []


def test_tc4_same_model_second_opinion_keeps_it():
    rows = select([_analysis("a1"), _filter("a1", False, 45), _filter("a1", True, 62, mode="filter_v1_second")], NOW)["rows"]
    assert len(rows) == 1 and rows[0]["importance_score"] == 62


def test_tc5_resolution_confirmed_and_important_keeps_it_and_sets_evidence():
    docs = [_analysis("a1"), _filter("a1", False, 72, status="PENDING_RESOLUTION"), _resolution("a1", "CONFIRMED", 72)]
    [r] = select(docs, NOW)["rows"]
    assert r["evidence_status"] == "CONFIRMED"


def test_tc6_one_row_per_filing_latest_analysis_wins():
    old = _analysis("a1", analyzed_hours_ago=30, mode="batch5_compact", net_band="neutral_mixed")
    new = _analysis("a1", analyzed_hours_ago=2, net_band="slightly_negative")
    [r] = select([old, new, _filter("a1", True, 70)], NOW)["rows"]
    assert r["impact_band"] == "slightly_negative"


def test_tc7_analysis_before_the_filter_existed_is_not_checked():
    [r] = select([_analysis("a1")], NOW)["rows"]
    assert r["evidence_status"] == "NOT_CHECKED" and r["importance_score"] is None


def test_tc8_newest_five_and_a_count_of_the_rest():
    docs = [_analysis(f"a{i}", days_ago=i + 1) for i in range(7)] + [_analysis("old", days_ago=31)]
    out = select(docs, NOW)
    assert [r["announcement_id"] for r in out["rows"]] == ["a0", "a1", "a2", "a3", "a4"] and out["more"] == 2


def test_tc9_no_research_input_leaves_the_backend():
    out = select([_analysis("a1")], NOW)
    assert "SECRET RESEARCH TEXT" not in repr(out) and all("input" not in r for r in out["rows"])


def test_naive_mongo_datetimes_are_read_as_utc():
    d = _analysis("a1"); d["event_ts"] = d["event_ts"].replace(tzinfo=None); d["analyzed_at"] = d["analyzed_at"].replace(tzinfo=None)
    [r] = select([d], NOW)["rows"]
    assert r["filed_at"].endswith("+00:00")


# ── route (TC-10, TC-11) behind the real gate ──────────────────────────────────────────────────────────────────────────
from tests.test_move_odds_routes import _DB, _client, _get, _reset_flags  # noqa: E402,F401  (shared gate harness + flag reset)


class _Cursor:
    def __init__(self, docs): self.docs = docs
    async def to_list(self, length=None): return [copy.deepcopy(d) for d in self.docs]


class _Mongo:
    def __init__(self, docs): self.docs = docs; self.queries = []
    def __getitem__(self, name):
        assert name == "event_ai_analysis"
        outer = self
        class C:
            def find(self, q, proj=None):
                outer.queries.append((q, proj))
                return _Cursor([d for d in outer.docs if d["symbol"] == q["symbol"]])
        return C()


def _fake_deps(monkeypatch, db):
    import sys, types
    mod = types.ModuleType("deps"); mod.db = db               # the real deps needs MONGO_URL; the route reads deps.db only
    monkeypatch.setitem(sys.modules, "deps", mod)


def test_tc10_tc11_route_gate_validation_and_payload(monkeypatch):
    mongo = _Mongo([_analysis("a1", days_ago=0.5)])
    _fake_deps(monkeypatch, mongo)
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    c, calls = _client(monkeypatch, db)
    r = _get(c, "/api/move-odds/stocks/SAPPHIRE/filing-analysis", "other")
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"
    assert _get(c, "/api/move-odds/stocks/A;B/filing-analysis", "invited").status_code == 422
    r = _get(c, "/api/move-odds/stocks/sapphire/filing-analysis", "invited")
    body = r.json()["data"]
    assert r.status_code == 200 and body["symbol"] == "SAPPHIRE" and body["rows"][0]["announcement_id"] == "a1"
    q, proj = mongo.queries[-1]
    assert q["symbol"] == "SAPPHIRE" and proj == {"input": 0} and calls == []   # Mongo only, no DaaS call


def test_route_mongo_failure_is_502_not_a_partial_list(monkeypatch):
    class Broken:
        def __getitem__(self, name): raise RuntimeError("mongo down")
    _fake_deps(monkeypatch, Broken())
    db = _DB(flags={"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    c, _ = _client(monkeypatch, db)
    r = _get(c, "/api/move-odds/stocks/SAPPHIRE/filing-analysis", "invited")
    assert r.status_code == 502 and r.json()["detail"] == "filing_analysis_unavailable"
