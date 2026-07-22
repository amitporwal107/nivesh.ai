"""Unit tests for the document-RAG eval harness (nidp.eval).

Exercises the pure checkers + the runner with fake retriever/answerer — no
network, no LLM. Confirms the 32-question dataset is well-formed.
"""
from nidp.eval import rag_eval as E
from nidp.eval.rag_questions import QUESTIONS, EvalQuestion


# ── dataset integrity ────────────────────────────────────────────────

def test_dataset_has_32_unique_questions():
    assert len(QUESTIONS) == 32
    assert len({q.id for q in QUESTIONS}) == 32


def test_routes_are_known():
    known = {"single_company_rag", "thematic_rag", "event_lookup", "numeric", "policy", "verification"}
    assert {q.route for q in QUESTIONS} <= known


def test_numeric_questions_do_not_require_citations():
    for q in QUESTIONS:
        if q.route == "numeric":
            assert q.should_cite is False, q.id


def test_placeholders_are_verification_or_policy():
    for q in QUESTIONS:
        if q.placeholder:
            assert q.route in ("verification", "policy"), q.id


# ── advice / price-prediction leakage ────────────────────────────────

def test_advice_leakage_flags_recommendation_language():
    assert E.advice_leakage("You should buy this stock now.")
    assert E.advice_leakage("We recommend selling ahead of results.")
    assert E.advice_leakage("Its price target is ₹5000.")
    assert E.advice_leakage("This is a multi-bagger.")


def test_advice_leakage_allows_management_guidance():
    # 'guidance' / a company's own 'targets' are legitimate grounded content.
    assert E.advice_leakage("Management guided to 15% margins next quarter.") == []
    assert E.advice_leakage("The company targets doubling capacity by FY27 [1].") == []


# ── citation markers ─────────────────────────────────────────────────

def test_cited_marker_numbers_parses_lists():
    assert E.cited_marker_numbers("Revenue rose [1] and margins fell [2, 3].") == [1, 2, 3]


def test_dangling_markers_detects_fabricated_citation():
    assert E.dangling_markers("Claim [1] and claim [4].", n_sources=2) == [4]
    assert E.dangling_markers("Claim [1] and [2].", n_sources=2) == []


def test_unresolved_citations():
    valid = {"c1", "c2"}
    cits = [{"n": 1, "chunk_id": "c1"}, {"n": 2, "chunk_id": "c9"}]
    assert E.unresolved_citations(cits, valid) == [2]


def test_is_refusal():
    assert E.is_refusal("No filing found for that order.")
    assert E.is_refusal("I could not find any disclosure on that.")
    assert E.is_refusal("Cannot verify — nothing filed.")
    assert not E.is_refusal("BEL won a ₹500 crore order [1].")


# ── runner with fakes ────────────────────────────────────────────────

def _q(**kw):
    base = dict(id="X-1", category="single_company", route="single_company_rag",
                question="What did $LT say?", tickers=["LT"])
    base.update(kw)
    return EvalQuestion(**base)


def test_evaluate_question_clean_answer_passes():
    def retrieve(query, tickers, thematic):
        return [{"chunk_id": "c1"}, {"chunk_id": "c2"}]

    def answer(q):
        return {"answer": "Order book grew 20% YoY [1][2].",
                "sources": [{"n": 1}, {"n": 2}],
                "citations": [{"n": 1, "chunk_id": "c1"}, {"n": 2, "chunk_id": "c2"}]}

    res = E.evaluate_question(_q(), retrieve, answer)
    assert res["checks"]["coverage"] == "pass"
    assert res["checks"]["citations_resolve"] == "pass"
    assert res["checks"]["no_advice"] == "pass"
    assert res["checks"]["ok"] is True


def test_evaluate_question_fabricated_citation_fails():
    def retrieve(query, tickers, thematic):
        return [{"chunk_id": "c1"}]

    def answer(q):
        return {"answer": "Margins will rise to 20% [1][2].",  # advice + dangling [2]
                "sources": [{"n": 1}],
                "citations": [{"n": 1, "chunk_id": "c1"}, {"n": 2, "chunk_id": "ghost"}]}

    res = E.evaluate_question(_q(), retrieve, answer)
    assert res["checks"]["ok"] is False
    assert res["checks"]["no_advice"].startswith("fail")
    assert res["checks"]["no_dangling_citations"].startswith("fail")
    assert res["checks"]["citations_resolve"].startswith("fail")


def test_placeholder_empty_retrieval_is_ok_with_refusal():
    def retrieve(query, tickers, thematic):
        return []  # placeholder ticker → no data

    def answer(q):
        return {"answer": "No filing found for that order.", "sources": [], "citations": []}

    res = E.evaluate_question(_q(placeholder=True, route="verification"), retrieve, answer)
    assert res["checks"]["coverage"] == "n/a (placeholder)"
    assert res["checks"]["refusal_on_empty"] == "pass"
    assert res["checks"]["ok"] is True


def test_answer_covers_reports_missing_facts():
    assert E.answer_covers("Order book at ₹5 lakh crore, up 20%.", ["order book", "20%"]) == []
    assert E.answer_covers("Order book grew.", ["order book", "data center"]) == ["data center"]


def test_with_sample_answers_populates_must_include():
    qs = E.with_sample_answers({"SC-1": ["order book", "pipeline"]})
    sc1 = next(q for q in qs if q.id == "SC-1")
    assert sc1.must_include == ["order book", "pipeline"]
    # Untouched questions keep the empty default.
    assert next(q for q in qs if q.id == "SC-2").must_include == []


def test_content_match_fails_when_key_fact_absent():
    qs = E.with_sample_answers({"SC-1": ["order book", "record high"]})
    sc1 = next(q for q in qs if q.id == "SC-1")

    def retrieve(query, tickers, thematic):
        return [{"chunk_id": "c1"}]

    def answer(q):
        return {"answer": "Order book grew this quarter [1].",  # missing 'record high'
                "sources": [{"n": 1}], "citations": [{"n": 1, "chunk_id": "c1"}]}

    res = E.evaluate_question(sc1, retrieve, answer)
    assert res["checks"]["matches_sample_answer"].startswith("fail")
    assert "record high" in res["checks"]["matches_sample_answer"]
    assert res["checks"]["ok"] is False


def test_appendix_b_keys_apply_to_dataset():
    from nidp.eval.sample_answer_keys import SAMPLE_ANSWER_KEYS
    # Keys only reference real question ids.
    ids = {q.id for q in QUESTIONS}
    assert set(SAMPLE_ANSWER_KEYS) <= ids
    qs = E.with_sample_answers(SAMPLE_ANSWER_KEYS)
    by_id = {q.id: q for q in qs}
    # Spot-check the load-bearing entity resolutions from Appendix B.
    assert by_id["EV-4"].must_include == ["eternal"]   # Zomato → Eternal
    assert by_id["EV-5"].must_include == ["bank"]       # HDFC → HDFC Bank
    assert by_id["SC-1"].must_include == ["order book"]
    # Most questions carry at least one benchmark key.
    populated = sum(1 for q in qs if q.must_include)
    assert populated >= 25


def test_run_over_full_set_retrieval_only():
    # Fake retriever returns a chunk for any non-placeholder query.
    def retrieve(query, tickers, thematic):
        return [{"chunk_id": "c1"}]

    report = E.run(retrieve)
    assert report["total"] == 32
    # Every non-placeholder question gets coverage; placeholders are n/a → all ok.
    assert report["failed"] == 0
