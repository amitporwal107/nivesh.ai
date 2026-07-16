"""Document-RAG evaluation harness.

Two layers, so most of it is unit-testable without network:

  * Pure checkers — citation resolution, dangling-citation markers, advice/price-
    prediction leakage, refusal-on-empty. No I/O; unit-tested directly.
  * Runner — `evaluate_question` / `run` take an injected `retrieve_fn` (and an
    optional `answer_fn`), so tests drive them with fakes. `default_retriever`
    wires the real DaaS `/documents/search` when you run it live.

Live run (needs the deployed DaaS + a DaaS API key):
    NIDP_DAAS_BASE_URL=... NIDP_DAAS_API_KEY=... python -m nidp.eval.rag_eval
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from .rag_questions import QUESTIONS, EvalQuestion

# A retriever: (query, tickers, is_thematic) -> list of chunk rows (dicts with
# at least "chunk_id"). An answerer: (question) -> {"answer": str,
# "citations": [{"n": int, "chunk_id": str}], "sources": [...]}.
RetrieveFn = Callable[[str, List[str], bool], List[Dict[str, Any]]]
AnswerFn = Callable[[EvalQuestion], Dict[str, Any]]


# ── Pure checkers ────────────────────────────────────────────────────

_ADVICE_PATTERNS = [
    r"\byou\s+should\s+(buy|sell|invest|avoid|hold|book\s+profit)",
    r"\bwe\s+(recommend|advise|suggest)\s+(buy|sell|invest|book)",
    r"\b(strong\s+)?(buy|sell)\s+(rating|call)\b",
    r"\b(price\s+target|target\s+price)\b",
    r"\bwill\s+(rise|surge|rally|jump|double|crash|fall)\s+to\b",
    r"\bmulti[-\s]?bagger\b",
    r"\bguaranteed\s+returns?\b",
]
_ADVICE_RE = re.compile("|".join(_ADVICE_PATTERNS), re.IGNORECASE)

# Phrasing a grounded answer uses when the corpus has nothing — the correct
# behaviour for placeholder tickers / no-data questions.
_REFUSAL_RE = re.compile(
    r"(no\s+(filing|record|announcement|disclosure|document|data|result)s?\s+"
    r"(found|available|on\s+file)|could\s+not\s+find|nothing\s+(on\s+file|filed)|"
    r"don't\s+have|do\s+not\s+have|no\s+information|not\s+disclosed|cannot\s+verify|"
    r"unable\s+to\s+(find|verify|locate))",
    re.IGNORECASE,
)

# Inline citation markers like [1] or [1, 2].
_CITE_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def advice_leakage(answer_text: str) -> List[str]:
    """Return the advice/price-prediction phrases found (empty = clean). None of
    the 32 questions ask for advice, so any hit is a failure."""
    return [m.group(0) for m in _ADVICE_RE.finditer(answer_text or "")]


def cited_marker_numbers(answer_text: str) -> List[int]:
    """Every distinct [n] number referenced in the answer body."""
    nums: set[int] = set()
    for m in _CITE_MARKER_RE.finditer(answer_text or ""):
        for part in m.group(1).split(","):
            nums.add(int(part.strip()))
    return sorted(nums)


def dangling_markers(answer_text: str, n_sources: int) -> List[int]:
    """[n] markers whose n exceeds the real source count → fabricated citation."""
    return [n for n in cited_marker_numbers(answer_text) if n < 1 or n > n_sources]


def unresolved_citations(citations: List[Dict[str, Any]],
                         valid_chunk_ids: set[str]) -> List[Any]:
    """Citations whose chunk_id is not among the retrieved chunks."""
    out = []
    for c in citations or []:
        cid = c.get("chunk_id")
        if cid is None or str(cid) not in valid_chunk_ids:
            out.append(c.get("n", cid))
    return out


def is_refusal(answer_text: str) -> bool:
    """True when the answer honestly says it has nothing (vs. fabricating)."""
    return bool(_REFUSAL_RE.search(answer_text or ""))


def answer_covers(answer_text: str, must_include: List[str]) -> List[str]:
    """Return the expected key facts/phrases MISSING from the answer (empty =
    fully covered). Case-insensitive substring match — this is how the harness
    'matches the sample answers': each sample answer's load-bearing facts are
    listed in the question's `must_include`, and the produced answer must contain
    them all."""
    lower = (answer_text or "").lower()
    return [k for k in (must_include or []) if k.lower() not in lower]


# ── Per-question evaluation ──────────────────────────────────────────

def evaluate_question(q: EvalQuestion,
                      retrieve_fn: RetrieveFn,
                      answer_fn: Optional[AnswerFn] = None) -> Dict[str, Any]:
    """Run one question through retrieval (+ optional answer) and score it."""
    checks: Dict[str, Any] = {}

    chunks = retrieve_fn(q.question, q.tickers, q.is_thematic) or []
    valid_ids = {str(c.get("chunk_id")) for c in chunks if c.get("chunk_id") is not None}
    checks["retrieved_count"] = len(chunks)

    # Coverage: real tickers/thematic should surface at least one chunk;
    # placeholder tickers ($XYZ/$ABC) legitimately return nothing.
    if q.placeholder:
        checks["coverage"] = "n/a (placeholder)"
    else:
        checks["coverage"] = "pass" if chunks else "fail"

    if answer_fn is not None:
        ans = answer_fn(q) or {}
        text = ans.get("answer") or ans.get("answer_markdown") or ""
        sources = ans.get("sources") or []
        citations = ans.get("citations") or []

        leaks = advice_leakage(text)
        checks["no_advice"] = "pass" if not leaks else f"fail: {leaks}"

        dangling = dangling_markers(text, len(sources))
        checks["no_dangling_citations"] = "pass" if not dangling else f"fail: {dangling}"

        unresolved = unresolved_citations(citations, valid_ids)
        checks["citations_resolve"] = "pass" if not unresolved else f"fail: {unresolved}"

        if not chunks and q.should_cite:
            # No evidence available → the answer must say so, not invent one.
            checks["refusal_on_empty"] = "pass" if is_refusal(text) else "fail"

        # Content match against the sample answer's key facts (Appendix B).
        if q.must_include:
            missing = answer_covers(text, q.must_include)
            checks["matches_sample_answer"] = "pass" if not missing else f"fail: missing {missing}"

    checks["ok"] = all(
        v in ("pass", "n/a (placeholder)") or k in ("retrieved_count",)
        for k, v in checks.items()
    )
    return {"id": q.id, "route": q.route, "category": q.category, "checks": checks}


def run(retrieve_fn: RetrieveFn,
        answer_fn: Optional[AnswerFn] = None,
        questions: Optional[List[EvalQuestion]] = None) -> Dict[str, Any]:
    """Run the full set; return a summary + per-question results."""
    qs = questions or QUESTIONS
    results = [evaluate_question(q, retrieve_fn, answer_fn) for q in qs]
    passed = sum(1 for r in results if r["checks"].get("ok"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "answer_mode": answer_fn is not None,
        "results": results,
    }


# ── Sample-answer wiring (Appendix B) ────────────────────────────────

def with_sample_answers(mapping: Dict[str, List[str]],
                        questions: Optional[List[EvalQuestion]] = None) -> List[EvalQuestion]:
    """Return the question set with `must_include` populated from a
    {question_id: [key facts]} mapping — this is how you plug the sample answers
    in. Unknown ids are ignored; ids absent from the mapping keep their default."""
    import dataclasses
    qs = questions or QUESTIONS
    return [dataclasses.replace(q, must_include=list(mapping.get(q.id, q.must_include))) for q in qs]


def load_sample_answers(path: str) -> Dict[str, List[str]]:
    """Load the sample answers from a JSON file. Accepts either
    {id: [facts]} or {id: {"must_include": [...]}}."""
    import json
    with open(path) as fh:
        raw = json.load(fh)
    out: Dict[str, List[str]] = {}
    for qid, val in raw.items():
        if isinstance(val, dict):
            out[qid] = list(val.get("must_include") or [])
        elif isinstance(val, list):
            out[qid] = list(val)
    return out


# ── Live wiring (used only when run as a script) ─────────────────────

def default_retriever() -> RetrieveFn:
    """DaaS-backed retriever: /documents/search for RAG/thematic, plus a symbol
    filter when tickers are present. Requires NIDP_DAAS_BASE_URL + key."""
    import os
    import httpx

    base = os.environ.get("NIDP_DAAS_BASE_URL", "https://data.niveshcopilot.com/daas").rstrip("/")
    key = os.environ.get("NIDP_DAAS_API_KEY", "") or os.environ.get("NIDP_DAAS_INTERNAL_TOKEN", "")
    headers = {"X-API-Key": key} if key else {}

    def _retrieve(query: str, tickers: List[str], is_thematic: bool) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"q": query, "limit": 8}
        if tickers and not is_thematic:
            params["symbol"] = tickers[0]
        try:
            with httpx.Client(timeout=15.0) as client:
                r = client.get(f"{base}/v1/documents/search", params=params, headers=headers)
            if r.status_code != 200:
                return []
            body = r.json()
            return body.get("data") or body.get("rows") or []
        except Exception:                                          # noqa: BLE001
            return []

    return _retrieve


def _main() -> None:
    import json
    import os
    # Default to the Appendix-B benchmark keys; override with a JSON file.
    from .sample_answer_keys import SAMPLE_ANSWER_KEYS
    mapping = dict(SAMPLE_ANSWER_KEYS)
    sa_path = os.environ.get("NIDP_RAG_SAMPLE_ANSWERS")
    if sa_path:
        mapping.update(load_sample_answers(sa_path))
    questions = with_sample_answers(mapping)
    report = run(default_retriever(), questions=questions)
    print(json.dumps(report, indent=2, default=str))
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    _main()
