"""Research feed insight fallback from Mongo event_ai_analysis (TC-R1..TC-R8 in
test_reports/research_feed_ai_insight_20260930.md). Documents are shaped like the real staging ones."""
import asyncio
import copy
import sys
import types
from datetime import datetime, timedelta, timezone

from services.event_ai_insight import ISOLATED, build, insights_for

NOW = datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc)


def _analysis(aid, hours_ago=1, iso=ISOLATED, **kw):
    d = {"announcement_id": aid, "source": "NSE_ANN", "symbol": "GANESHBE", "mode": "batch25_compact", "tool_isolation": iso,
         "event_type": "STAKE SALE", "event_subtype": "business transfer to KKR-backed buyer", "event_certainty": "final",
         "net_band": "slightly_positive", "net_impact_score": 20, "materiality_score": 70, "confidence_score": 80,
         "analyzed_at": NOW - timedelta(hours=hours_ago), "input": {"document_text": "SECRET RESEARCH TEXT"},
         "analysis": {"sum": f"summary {aid}", "amt": [{"v": 1154.0, "u": "cr", "what": "consideration"}],
                      "pf": [["Rs1,154cr consideration", 30, "p"]], "nf": [["Loses logistics revenue", 10, "p"]],
                      "unk": ["Use of proceeds"]}}
    d.update(kw)
    return d


def _filter(aid, include, imp, mode="filter_v1", hours_ago=2):
    return {"announcement_id": aid, "source": "NSE_ANN", "symbol": "ARMANFIN", "mode": mode, "tool_isolation": ISOLATED,
            "include": include, "event_importance_score": imp, "evidence_confidence": "HIGH",
            "positive_impact_score": 40, "negative_impact_score": 5, "analyzed_at": NOW - timedelta(hours=hours_ago),
            "analysis": {"title": f"title {aid}", "why": f"why {aid}", "cats": ["new product line"], "risks": ["execution"]}}


def test_r1_full_analysis_becomes_the_insight():
    ins = build([_analysis("a1"), _filter("a1", True, 80)])["a1"]
    assert ins["one"] == "summary a1" and ins["sentiment"] == "positive" and ins["confidence"] == 0.8
    assert ins["metric"] == {"label": "Consideration", "value": "1,154", "unit": "₹ cr"}
    tabs = [s["tab"] for s in ins["sections"]]
    assert tabs == ["Quick Summary", "Sentiment", "Potential Risks"]
    sent = ins["sections"][1]["items"]
    assert sent[0].startswith("Reads slightly positive for the company") and "+ Rs1,154cr consideration" in sent
    assert "− Loses logistics revenue" in sent


def test_r2_not_isolated_is_ignored():
    assert build([_analysis("a1", iso="NOT_ISOLATED_tools_were_available")]) == {}


def test_r3_latest_analysis_wins():
    out = build([_analysis("a1", hours_ago=30, analysis={"sum": "old"}), _analysis("a1", hours_ago=1)])
    assert out["a1"]["one"] == "summary a1"


def test_r4_kept_by_filter_but_not_yet_analysed():
    ins = build([_filter("b1", True, 75)])["b1"]
    assert ins["one"] == "title b1" and "full analysis pending" in ins["sections"][0]["h"]
    assert [s["tab"] for s in ins["sections"]] == ["Quick Summary", "Business Outlook", "Potential Risks"]


def test_r5_dropped_filing_says_routine_and_never_reads_important():
    ins = build([_filter("c1", False, 25), _filter("c1", False, 30, mode="filter_v1_second")])["c1"]
    assert ins["one"].startswith("Assessed as routine (importance") and ins["sentiment"] == "neutral"
    assert [s["tab"] for s in ins["sections"]] == ["Quick Summary"]


def test_r6_second_opinion_keep_overrides_first_drop():
    ins = build([_filter("d1", False, 40), _filter("d1", True, 65, mode="filter_v1_second", hours_ago=1)])["d1"]
    assert ins["one"] == "title d1"


def test_r7_no_research_input_leaves_the_backend():
    assert "SECRET RESEARCH TEXT" not in repr(build([_analysis("a1")]))


class _Cur:
    def __init__(self, docs): self.docs = docs
    async def to_list(self, length=None): return [copy.deepcopy(d) for d in self.docs]


class _Mongo:
    def __init__(self, docs, fail=False): self.docs, self.fail, self.q = docs, fail, []
    def __getitem__(self, name):
        outer = self
        class C:
            def find(self, q, proj=None):
                if outer.fail:
                    raise RuntimeError("mongo down")
                outer.q.append((q, proj))
                ids = set(q["announcement_id"]["$in"])
                return _Cur([d for d in outer.docs if d["announcement_id"] in ids and d["tool_isolation"] == q["tool_isolation"]])
        return C()


def test_r8_lookup_queries_isolated_ids_only_and_fails_soft():
    m = _Mongo([_analysis("a1"), _analysis("zz")])
    out = asyncio.run(insights_for(m, ["a1"]))
    assert list(out) == ["a1"] and m.q[0][1] == {"input": 0} and m.q[0][0]["tool_isolation"] == ISOLATED
    assert asyncio.run(insights_for(_Mongo([], fail=True), ["a1"])) == {}
    assert asyncio.run(insights_for(m, [])) == {}


def test_r9_feed_prefers_claude_and_reads_legacy_stage7_only_for_the_rest(monkeypatch):
    """routes/filings._insights_for: the Claude analysis wins; stored stage-7 rows only fill ids it lacks."""
    fake_deps = types.ModuleType("deps")
    fake_deps.db = _Mongo([_analysis("a1", analysis={"sum": "from mongo"}), _analysis("both", analysis={"sum": "claude wins"})])
    async def _gcu(request): return {"user_id": "u1"}
    fake_deps.get_current_user = _gcu
    monkeypatch.setitem(sys.modules, "deps", fake_deps)
    fake_markets = types.ModuleType("routes.markets")
    asked = []
    async def _daas_first(tool, params, pg, default):
        asked.append(sorted(params["ids"]))
        return {"insights": {"old": {"one": "stage-7 one-liner"}, "both": {"one": "stale stage-7"}}}
    fake_markets._daas_first = _daas_first
    fake_markets._aux_cached = fake_markets._articles = fake_markets._filing_insights_pg = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "routes.markets", fake_markets)
    monkeypatch.delitem(sys.modules, "routes.filings", raising=False)
    import routes.filings as F
    out = asyncio.run(F._insights_for(["old", "a1", "both", "none"]))
    assert out["a1"]["one"] == "from mongo" and out["both"]["one"] == "claude wins"
    assert out["old"] == {"one": "stage-7 one-liner"} and "none" not in out
    assert asked == [["none", "old"]]                      # legacy is asked only for ids Claude did not cover
    assert F._row({"id": "a1"}, out["a1"])["one"] == "from mongo" and F._row({"id": "a1"}, out["a1"])["hasInsights"] is True
