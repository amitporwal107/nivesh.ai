"""Unit tests for the corporate-event AI analysis pipeline. No network, no model call: these
assert OUR logic (candidate selection, validation of model output, document shape) and that the
documents render through the backend's real reader (services/event_ai_insight.py)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))           # ai_analysis/
sys.path.insert(0, str(HERE.parents[4] / "backend"))

import analyse  # noqa: E402
import ea_core as core  # noqa: E402
from services.event_ai_insight import build  # noqa: E402

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64
MODEL = "claude-sonnet-5-5"


def _filing(aid="f1", title="Acquisition", **kw):
    f = {"id": aid, "symbol": "ACME", "company": "Acme Ltd", "title": title, "summary": "Acme has informed the Exchange",
         "source": "NSE_ANN", "when": "2026-10-12T10:00:00+00:00", "url": "https://example.invalid/a.pdf",
         "text": "DOCUMENT BODY TEXT", "text_status": "OK"}
    f.update(kw)
    return f


def _verdict(aid="f1", importance=80, **kw):
    v = {"id": aid, "importance": importance, "category": "mna", "confidence": "HIGH", "positive": 40, "negative": 5,
         "title": "Acme buys Beta for Rs 500 cr", "why": "Adds a second product line", "cats": ["new line"], "risks": ["integration"]}
    v.update(kw)
    return v


def _analysis(**kw):
    a = {"event_type": "ACQUISITION", "event_subtype": "100% of Beta Ltd", "event_certainty": "final",
         "net_impact_score": 30, "materiality_score": 70, "confidence_score": 75,
         "sum": "Acme will acquire Beta Ltd for Rs 500 cr in cash.",
         "amt": [{"v": 500, "u": "cr", "what": "consideration"}],
         "pf": [{"text": "Adds a second product line", "weight": 40}], "nf": [{"text": "Funded by debt", "weight": 15}],
         "unk": ["Closing date"]}
    a.update(kw)
    return a


# ── candidate selection ─────────────────────────────────────────────────────
def test_routine_compliance_subjects_never_reach_the_model():
    """TC-E1: pure compliance filings are skipped without a model call; everything else is a candidate."""
    fs = [_filing("a", "Certificate under SEBI (Depositories and Participants) Regulations, 2018"),
          _filing("b", "trading window"), _filing("c", "Acquisition"), _filing("d", "Outcome of Board Meeting")]
    assert [f["id"] for f in core.candidates(fs, done=set())] == ["c", "d"]


def test_already_judged_filings_are_not_sent_again():
    """TC-E2: a filing that already has a verdict under this prompt is skipped (reruns cost nothing)."""
    assert [f["id"] for f in core.candidates([_filing("c"), _filing("d")], done={"c"})] == ["d"]


# ── model output validation ─────────────────────────────────────────────────
def test_filter_output_is_checked_against_the_batch():
    """TC-E3: out-of-range scores, an id that was not in the batch, and a missing id are all
    reported; only clean verdicts are kept."""
    raw = {"verdicts": [_verdict("f1"), _verdict("f2", importance=140), _verdict("zz"), _verdict("f3", title="  "),
                        _verdict("f5", category="M&A")]}
    good, problems = core.clean_filter(raw, ["f1", "f2", "f3", "f4", "f5"])
    assert list(good) == ["f1"] and good["f1"]["category"] == "mna"
    text = " | ".join(problems)
    assert "f2" in text and "zz" in text and "f3" in text and "f4" in text and "f5: unknown category" in text


def test_analysis_output_is_validated():
    """TC-E4: a clean analysis passes; a score outside its range or an empty summary is rejected
    rather than stored."""
    assert core.clean_analysis(_analysis())["sum"].startswith("Acme will acquire")
    for bad in (_analysis(net_impact_score=150), _analysis(sum=" "), _analysis(event_certainty="maybe"),
                _analysis(amt=[{"v": "lots", "u": "cr", "what": "x"}])):
        with pytest.raises(ValueError):
            core.clean_analysis(bad)


def test_net_band_boundaries():
    """TC-E5: the band is derived from the score, never taken from the model."""
    assert [core.net_band(n) for n in (0, 9, 10, 25, 50, 75, 100)] == [
        "neutral_mixed", "neutral_mixed", "slightly_positive", "moderately_positive", "strongly_positive",
        "extremely_positive", "extremely_positive"]
    assert [core.net_band(n) for n in (-9, -10, -25, -50, -75)] == [
        "neutral_mixed", "slightly_negative", "moderately_negative", "strongly_negative", "extremely_negative"]


# ── document shape ──────────────────────────────────────────────────────────
def test_documents_carry_what_the_ingest_api_requires():
    """TC-E6: _id is '<source>:<announcement_id>:<prompt_sha12>:<model_tag>'; the required fields
    are present; the keep decision is the importance threshold, not the model's say-so."""
    d = core.filter_doc(_filing(), _verdict(importance=80), SHA, MODEL, NOW)
    assert d["_id"] == f"NSE_ANN:f1:{'a' * 12}:{MODEL}"
    for k in ("_id", "announcement_id", "source", "prompt_sha256"):
        assert d[k]
    assert d["include"] is True and d["event_importance_score"] == 80 and d["tool_isolation"] == core.ISOLATED
    assert core.filter_doc(_filing(), _verdict(importance=59), SHA, MODEL, NOW)["include"] is False
    a = core.analysis_doc(_filing(), core.clean_analysis(_analysis()), "b" * 64, MODEL, NOW)
    assert a["mode"] == "single_full" and a["net_band"] == "moderately_positive" and a["_id"] != d["_id"]


def test_document_text_is_never_stored():
    """TC-E7: the filing body is model input only; no stored document contains it."""
    docs = [core.filter_doc(_filing(), _verdict(), SHA, MODEL, NOW),
            core.analysis_doc(_filing(), core.clean_analysis(_analysis()), SHA, MODEL, NOW)]
    assert "DOCUMENT BODY TEXT" not in json.dumps(docs, default=str)


# ── the backend's reader renders them ───────────────────────────────────────
def test_reader_renders_kept_dropped_and_analysed_filings():
    """TC-E8: through services.event_ai_insight.build — a kept filing reads 'full analysis pending',
    a dropped one reads 'Assessed as routine', and a full analysis wins with its summary and metric."""
    kept = core.filter_doc(_filing("k"), _verdict("k", 80), SHA, MODEL, NOW)
    dropped = core.filter_doc(_filing("d"), _verdict("d", 20), SHA, MODEL, NOW)
    full = core.analysis_doc(_filing("k2"), core.clean_analysis(_analysis()), SHA, MODEL, NOW)
    out = build([kept, dropped, full, core.filter_doc(_filing("k2"), _verdict("k2", 85), SHA, MODEL, NOW)])
    assert out["k"]["one"] == "Acme buys Beta for Rs 500 cr" and "full analysis pending" in out["k"]["sections"][0]["h"]
    assert out["d"]["one"].startswith("Assessed as routine (importance 20/100)") and out["d"]["sentiment"] == "neutral"
    assert out["k2"]["one"].startswith("Acme will acquire") and out["k2"]["sentiment"] == "positive"
    assert out["k2"]["metric"] == {"label": "Consideration", "value": "500", "unit": "₹ cr"}
    assert "+ Adds a second product line" in out["k2"]["sections"][1]["items"]


# ── the model call ──────────────────────────────────────────────────────────
class _Proc:
    def __init__(self, payload, code=0):
        self.stdout, self.stderr, self.returncode = json.dumps(payload), "", code


def _result(**kw):
    r = {"is_error": False, "structured_output": {"ok": 1}, "modelUsage": {MODEL: {}, "claude-haiku-5-5": {}}}
    r.update(kw)
    return r


def test_model_call_runs_with_tools_off_and_isolated(monkeypatch):
    """TC-E9: the CLI is invoked with no tools, no MCP servers and no settings, from an empty
    directory, and the filing text goes in on stdin, not argv."""
    seen = {}

    def fake(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return _Proc(_result())

    monkeypatch.setattr(analyse.subprocess, "run", fake)
    assert analyse.run_claude("SYSTEM", "FILING TEXT", {"type": "object"}) == {"ok": 1}
    cmd = seen["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == "" and cmd[cmd.index("--model") + 1] == MODEL
    assert "FILING TEXT" not in cmd and seen["input"] == "FILING TEXT"
    assert Path(seen["cwd"]).name.startswith("event-ai-") and not Path(seen["cwd"]).exists()


def test_model_call_failures_raise(monkeypatch):
    """TC-E10: an error result, a missing structured answer, or an answer from a different model
    raises — nothing is stored under a model tag that did not produce it."""
    for payload in (_result(is_error=True), _result(structured_output=None), _result(modelUsage={"claude-haiku-5-5": {}})):
        monkeypatch.setattr(analyse.subprocess, "run", lambda *a, p=payload, **k: _Proc(p))
        with pytest.raises(RuntimeError):
            analyse.run_claude("S", "U", {"type": "object"})
    monkeypatch.setattr(analyse.subprocess, "run", lambda *a, **k: _Proc({}, code=1))
    with pytest.raises(RuntimeError):
        analyse.run_claude("S", "U", {"type": "object"})


# ── scores for the filings table (category chips, materiality order) ────────
import to_pg_scores as pg  # noqa: E402

AID = "a" * 40


def test_scores_use_the_classifier_vocabulary():
    """TC-E11: importance becomes high / medium / low, the net of the two impact scores becomes the
    sentiment, and a full analysis's net score overrides the filter's when there is one."""
    assert [core.impact_level(n) for n in (0, 29, 30, 59, 60, 100)] == ["low", "low", "medium", "medium", "high", "high"]
    f = core.filter_doc(_filing(AID), _verdict(AID, 80, positive=40, negative=5), SHA, MODEL, NOW)
    rows = pg.score_rows([f], SHA)
    assert rows == [(AID, "NSE_ANN", "mna", "high", "positive", f"{MODEL}:filter_v1:{'a' * 12}")]
    a = core.analysis_doc(_filing(AID), core.clean_analysis(_analysis(net_impact_score=-40)), "b" * 64, MODEL, NOW)
    assert pg.score_rows([f, a], SHA)[0][4] == "negative"
    flat = core.filter_doc(_filing(AID), _verdict(AID, 20, positive=5, negative=5), SHA, MODEL, NOW)
    assert pg.score_rows([flat], SHA)[0][3:5] == ("low", "neutral")


def test_only_current_prompt_verdicts_with_a_real_id_are_scored():
    """TC-E12: a verdict from an older prompt, one without a category, and one whose id is not a
    40-character hash are all left out — nothing but checked values reaches SQL."""
    old = core.filter_doc(_filing(AID), _verdict(AID), "c" * 64, MODEL, NOW)
    nocat = core.filter_doc(_filing("b" * 40), _verdict("b" * 40), SHA, MODEL, NOW); nocat.pop("category")
    badid = core.filter_doc(_filing("x'; DROP"), _verdict("x'; DROP"), SHA, MODEL, NOW)
    assert pg.score_rows([old, nocat, badid], SHA) == []


def test_sql_updates_only_listed_filings_and_keeps_a_rollback():
    """TC-E13: the script saves the previous values of every row it will touch, updates by
    (announcement_id, source), and marks compliance subjects 'regulatory' only where no category
    is set. Values travel as COPY data, not as SQL text."""
    rows = [(AID, "NSE_ANN", "mna", "high", "positive", "tag")]
    sql = pg.build_sql(rows, days=3)
    assert f"{AID},NSE_ANN,mna,high,positive,tag\n\\.".replace("\\n", "\n") in sql.replace("\r", "")
    assert "CREATE TABLE IF NOT EXISTS nidp.event_ai_score_rollback" in sql
    assert sql.index("INSERT INTO nidp.event_ai_score_rollback") < sql.index("UPDATE nidp.corporate_announcements")
    assert "c.announcement_id = t.announcement_id AND c.source = t.source" in sql
    rule = sql[sql.index("-- subject rule"):]
    assert "c.event_category IS NULL" in rule and "lower(btrim(c.subject)) = m.subject" in rule
    assert "('certificate under sebi (depositories and participants) regulations, 2018', 'regulatory')" in rule
    assert "('acquisition', 'mna')" in rule
    assert AID not in sql.split("COPY")[0] and AID not in rule


def test_subject_rule_only_covers_unambiguous_subjects():
    """TC-E14: every mapped category is one the filings table knows; the subjects never sent to the
    model are all 'regulatory'; and catch-all subjects are left for the model, not guessed."""
    assert set(core.SUBJECT_CATEGORY.values()) <= set(core.EVENT_CATEGORIES)
    assert all(core.SUBJECT_CATEGORY[s] == "regulatory" for s in core.ROUTINE_SUBJECTS)
    for vague in ("general updates", "updates", "press release", "outcome of board meeting", "others", "record date"):
        assert vague not in core.SUBJECT_CATEGORY
    assert all(s == s.lower().strip() for s in core.SUBJECT_CATEGORY)
