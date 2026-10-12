"""Pure logic for the corporate-event AI analysis pipeline: which filings are candidates, what a
valid model answer looks like, and the documents posted to /api/internal/event-ai-analysis/bulk.

The document shape is the one the backend already reads (backend/services/event_ai_insight.py,
backend/services/move_odds_filing_analysis.py). Nothing here calls a model or the network.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Iterable

ISOLATED = "tools_off+isolated"          # the readers ignore any document without this marker
FILTER_MODE = "filter_v1"
ANALYSIS_MODE = "single_full"
KEEP_IMPORTANCE = 60                     # same threshold as move_odds_filing_analysis.KEEP_IMPORTANCE
FILTER_TEXT_CHARS = 3_500                # document opening shown to the filter, per filing (1,200 was mostly cover letter)
ANALYSIS_TEXT_CHARS = 12_000
BATCH = 20

# Exchange subject lines that are compliance paperwork by definition. They are never sent to the
# model and get no insight (the card shows the exchange label). Compared case-insensitively.
ROUTINE_SUBJECTS = frozenset(s.lower() for s in (
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018",
    "Copy of Newspaper Publication",
    "Structural Digital Database",
    "Trading Window",
))

# The filings table's own vocabulary (backend/nidp/services/announcement_classifier/classifier.py).
# The Research page builds its category chips and its "material" order from these columns.
EVENT_CATEGORIES = ("orders", "mna", "earnings", "capex", "regulatory", "management",
                    "dividend", "buyback", "qip", "rating", "litigation", "other")
MEDIUM_IMPORTANCE = 30                   # impact: >= KEEP_IMPORTANCE high, >= this medium, else low

# Category by the exchange's own subject line, for filings the model has not judged (the year of
# history, and anything it has not reached yet). Only subjects whose category is unambiguous are
# listed; "general updates", "press release", "outcome of board meeting" and the like can be about
# anything, so they stay uncategorised until the model reads them. A model verdict always wins.
_BY_CATEGORY = {
    "orders": ("bagging/receiving of orders/contracts", "awarding of order(s)/contract(s)"),
    "mna": ("acquisition", "amalgamation/merger", "scheme of arrangement", "sale or disposal", "demerger",
            "public announcement-open offer", "open offer", "post offer public announcement",
            "diversification/disinvestment", "other restructuring"),
    "earnings": ("integrated filing- financial", "clarification - financial results",
                 "reply to clarification- financial results", "monthly business updates",
                 "reasons for delayed/non-submission of financial results",
                 "voluntary revision of financial statements or report"),
    "capex": ("capacity addition", "commencement of commercial production/operations",
              "postponement of commercial production/operations", "adoption of new line(s) of business"),
    "management": ("appointment", "change in management", "resignation", "resignation of director/kmp/smp",
                   "change in director(s)", "cessation", "change in auditors",
                   "change in company secretary/compliance officer", "retirement",
                   "resignation of independent director", "resignation of statutory auditor", "demise"),
    "dividend": ("dividend", "bonus", "stock split"),
    "buyback": ("buyback", "public announcement - buyback of shares", "closure of buy back",
                "post buyback public announcement"),
    "qip": ("allotment of securities", "issue of securities", "rights issue", "preferential issue",
            "qualified institutional placement", "fccbs"),
    "rating": ("credit rating", "credit rating- revision", "credit rating- new", "credit rating- others"),
    "litigation": ("action(s) taken or orders passed", "action(s) initiated or orders passed",
                   "pendency of litigation(s)/dispute(s) or the outcome impacting the company",
                   "corporate insolvency resolution process", "fraud/default/arrest",
                   "frauds/default by employees", "defaults on payment of interest/principal",
                   "delay/default in the payment of fines/penalties/dues etc. to authority",
                   "initiation of forensic audit", "final  forensic  audit  report", "one time settlement",
                   "corporate debt restructuring"),
    "regulatory": tuple(sorted(ROUTINE_SUBJECTS)) + (
        "analysts/institutional investor meet/con. call updates", "shareholders meeting", "esop/esos/esps",
        "options to purchase securities", "spurt in volume", "price movement", "monitoring agency report",
        "statement of deviation(s) or variation(s) under reg. 32", "amendment to aoa/moa",
        "committee meeting updates", "address change", "loss of share certificates",
        "issue of duplicate share certificate", "registrar & share transfer agent update",
        "trading plan under pit", "integrated filing- governance",
        "quarterly compliance report on corporate governance - within 21 days from the end of the quarter",
        "name change", "name and symbol change", "symbol change of company", "increase in authorised capital",
        "extension of annual general meeting", "extension  of financial year", "change in financial year",
        "board meeting cancelled", "cancellation of book closure"),
}
SUBJECT_CATEGORY = {subject: cat for cat, subjects in _BY_CATEGORY.items() for subject in subjects}

CONFIDENCE = ("HIGH", "MEDIUM", "LOW")
CERTAINTY = ("final", "proposed", "conditional", "unknown")
UNITS = ("cr", "usd_mn", "pct", "shares")

_STR = {"type": "string"}
_SCORE = {"type": "integer", "minimum": 0, "maximum": 100}
_FACTORS = {"type": "array", "maxItems": 4, "items": {
    "type": "object", "additionalProperties": False, "required": ["text", "weight"],
    "properties": {"text": _STR, "weight": _SCORE}}}

FILTER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdicts"], "properties": {
    "verdicts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "category", "importance", "confidence", "positive", "negative", "title", "why", "cats", "risks"],
        "properties": {"id": _STR, "category": {"type": "string", "enum": list(EVENT_CATEGORIES)},
                       "importance": _SCORE, "confidence": {"type": "string", "enum": list(CONFIDENCE)},
                       "positive": _SCORE, "negative": _SCORE, "title": _STR, "why": _STR,
                       "cats": {"type": "array", "maxItems": 3, "items": _STR},
                       "risks": {"type": "array", "maxItems": 3, "items": _STR}}}}}}

ANALYSIS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["event_type", "event_subtype", "event_certainty", "net_impact_score", "materiality_score",
                 "confidence_score", "sum", "amt", "pf", "nf", "unk"],
    "properties": {
        "event_type": _STR, "event_subtype": _STR, "event_certainty": {"type": "string", "enum": list(CERTAINTY)},
        "net_impact_score": {"type": "integer", "minimum": -100, "maximum": 100},
        "materiality_score": _SCORE, "confidence_score": _SCORE, "sum": _STR,
        "amt": {"type": "array", "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["v", "u", "what"],
            "properties": {"v": {"type": "number"}, "u": {"type": "string", "enum": list(UNITS)}, "what": _STR}}},
        "pf": _FACTORS, "nf": _FACTORS,
        "unk": {"type": "array", "maxItems": 4, "items": _STR}}}


def prompt_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def candidates(filings: Iterable[dict], done: set[str]) -> list[dict]:
    """Filings worth a model call: not compliance paperwork, not already judged under this prompt."""
    return [f for f in filings
            if f.get("id") and f["id"] not in done and str(f.get("title") or "").strip().lower() not in ROUTINE_SUBJECTS]


def _score(v: Any, lo: int = 0, hi: int = 100) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _texts(v: Any, cap: int) -> list[str]:
    return [t for t in (_text(x) for x in (v if isinstance(v, list) else [])) if t][:cap]


def clean_filter(raw: Any, batch_ids: list[str]) -> tuple[dict[str, dict], list[str]]:
    """Validate one filter answer against the batch it was asked about.
    Returns ({id: verdict}, problems). A verdict that fails any check is left out and reported."""
    good: dict[str, dict] = {}
    problems: list[str] = []
    rows = raw.get("verdicts") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return {}, ["answer has no verdicts list"]
    for v in rows:
        vid = v.get("id") if isinstance(v, dict) else None
        if vid not in batch_ids:
            problems.append(f"{vid}: not in the batch")
        elif vid in good:
            problems.append(f"{vid}: duplicate verdict")
        elif not all(_score(v.get(k)) for k in ("importance", "positive", "negative")):
            problems.append(f"{vid}: score outside 0-100")
        elif v.get("category") not in EVENT_CATEGORIES:
            problems.append(f"{vid}: unknown category")
        elif v.get("confidence") not in CONFIDENCE:
            problems.append(f"{vid}: unknown confidence")
        elif not _text(v.get("title")) or not _text(v.get("why")):
            problems.append(f"{vid}: empty title or why")
        else:
            good[vid] = {"category": v["category"],
                         "importance": v["importance"], "positive": v["positive"], "negative": v["negative"],
                         "confidence": v["confidence"], "title": _text(v["title"]), "why": _text(v["why"]),
                         "cats": _texts(v.get("cats"), 3), "risks": _texts(v.get("risks"), 3)}
    problems += [f"{i}: no verdict returned" for i in batch_ids if i not in good and not any(p.startswith(f"{i}:") for p in problems)]
    return good, problems


def _factors(v: Any) -> list[list]:
    out = []
    for x in v if isinstance(v, list) else []:
        if not isinstance(x, dict) or not _text(x.get("text")) or not _score(x.get("weight")):
            raise ValueError("factor needs text and a 0-100 weight")
        out.append([_text(x["text"]), x["weight"]])
    return out[:4]


def clean_analysis(raw: Any) -> dict:
    """Validate one full analysis. Raises ValueError; a bad analysis is never stored."""
    if not isinstance(raw, dict):
        raise ValueError("answer is not an object")
    if not _score(raw.get("net_impact_score"), -100, 100):
        raise ValueError("net_impact_score outside -100..100")
    if not _score(raw.get("materiality_score")) or not _score(raw.get("confidence_score")):
        raise ValueError("materiality or confidence outside 0-100")
    if raw.get("event_certainty") not in CERTAINTY:
        raise ValueError("unknown event_certainty")
    if not _text(raw.get("sum")) or not _text(raw.get("event_type")):
        raise ValueError("empty summary or event_type")
    amt = []
    for a in raw.get("amt") if isinstance(raw.get("amt"), list) else []:
        if (not isinstance(a, dict) or isinstance(a.get("v"), bool) or not isinstance(a.get("v"), (int, float))
                or a.get("u") not in UNITS or not _text(a.get("what"))):
            raise ValueError("amount needs a numeric v, a known unit and a label")
        amt.append({"v": a["v"], "u": a["u"], "what": _text(a["what"])})
    return {"event_type": _text(raw["event_type"]).upper(), "event_subtype": _text(raw.get("event_subtype")) or None,
            "event_certainty": raw["event_certainty"], "net_impact_score": raw["net_impact_score"],
            "materiality_score": raw["materiality_score"], "confidence_score": raw["confidence_score"],
            "sum": _text(raw["sum"]), "amt": amt[:4], "pf": _factors(raw.get("pf")), "nf": _factors(raw.get("nf")),
            "unk": _texts(raw.get("unk"), 4)}


def impact_level(importance: int) -> str:
    return "high" if importance >= KEEP_IMPORTANCE else "medium" if importance >= MEDIUM_IMPORTANCE else "low"


def sentiment(net: int) -> str:
    """Same cut-offs the backend's reader uses for the insight card."""
    return "positive" if net >= 10 else "negative" if net <= -10 else "neutral"


def net_band(n: int) -> str:
    """Band from the net score. Derived here so the stored band can never disagree with the score."""
    size = abs(n)
    if size < 10:
        return "neutral_mixed"
    word = "slightly" if size < 25 else "moderately" if size < 50 else "strongly" if size < 75 else "extremely"
    return f"{word}_{'positive' if n > 0 else 'negative'}"


def _base(filing: dict, mode: str, sha: str, model_tag: str, now: datetime) -> dict:
    source = filing.get("source") or "NSE_ANN"
    return {"_id": f"{source}:{filing['id']}:{sha[:12]}:{model_tag}", "announcement_id": filing["id"],
            "source": source, "symbol": filing.get("symbol"), "company": filing.get("company"),
            "exchange_category": filing.get("title"), "event_ts": filing.get("when"), "mode": mode,
            "tool_isolation": ISOLATED, "prompt_sha256": sha, "model_tag": model_tag,
            "analyzed_at": now.isoformat(), "text_status": filing.get("text_status")}


def filter_doc(filing: dict, verdict: dict, sha: str, model_tag: str, now: datetime) -> dict:
    d = _base(filing, FILTER_MODE, sha, model_tag, now)
    d.update(include=verdict["importance"] >= KEEP_IMPORTANCE, category=verdict["category"],
             event_importance_score=verdict["importance"],
             evidence_confidence=verdict["confidence"], positive_impact_score=verdict["positive"],
             negative_impact_score=verdict["negative"],
             analysis={"title": verdict["title"], "why": verdict["why"], "cats": verdict["cats"], "risks": verdict["risks"]})
    return d


def analysis_doc(filing: dict, a: dict, sha: str, model_tag: str, now: datetime) -> dict:
    d = _base(filing, ANALYSIS_MODE, sha, model_tag, now)
    d.update(event_type=a["event_type"], event_subtype=a["event_subtype"], event_certainty=a["event_certainty"],
             net_impact_score=a["net_impact_score"], net_band=net_band(a["net_impact_score"]),
             materiality_score=a["materiality_score"], confidence_score=a["confidence_score"],
             analysis={"sum": a["sum"], "amt": a["amt"], "pf": a["pf"], "nf": a["nf"], "unk": a["unk"]})
    return d
