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
    v = {"id": aid, "importance": importance, "confidence": "HIGH", "positive": 40, "negative": 5,
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
    raw = {"verdicts": [_verdict("f1"), _verdict("f2", importance=140), _verdict("zz"), _verdict("f3", title="  ")]}
    good, problems = core.clean_filter(raw, ["f1", "f2", "f3", "f4"])
    assert list(good) == ["f1"]
    text = " | ".join(problems)
    assert "f2" in text and "zz" in text and "f3" in text and "f4" in text


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
