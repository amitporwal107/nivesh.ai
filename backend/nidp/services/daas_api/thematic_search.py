"""Thematic-commentary extraction — precise cross-company "who flagged X?" answers.

A thematic ask ("which companies flagged margin pressure in their Q1 concalls?") is a
JUDGEMENT question, not a keyword match: ~1,200 companies mention "margin", but only some
had management actually FLAG pressure. Hybrid vector search ranks the right companies
below its candidate pool, and keyword ts_rank favours repetition, not relevance — so
neither surfaces the curated set a human would pick.

This module does what the user asked for (chosen 2026-07-21): cast a WIDE keyword net over
the GIN-indexed chunk corpus to get every candidate company, then have an LLM READ the
passages and keep only the companies where management genuinely flagged the theme — with
the verbatim statement and its citation.

Pipeline:
  1. classify_theme(q)   — LLM turns the query into {pivot, context} term sets + a theme
                           label. We build the tsquery in Python (never LLM-generated SQL)
                           as (pivot terms) & (context terms) so it's a fast, bounded
                           GIN-indexed scan.
  2. CANDIDATE_SQL       — dedupe by company, best passage per company, top-N by ts_rank.
  3. extract_flagged()   — LLM reads the N passages, returns only the companies that
                           genuinely flagged the theme + the quoted statement.

OpenAI-only (the project has no Anthropic license — see filing_insights / memory
nidp-openai-only-no-anthropic). Every LLM hop degrades gracefully: if the SDK/key is
missing or a call fails, we fall back to the ts_rank-ordered candidates unfiltered, so the
endpoint never hard-fails — it just becomes the "comprehensive list" instead of "curated".
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("THEMATIC_LLM_MODEL", "gpt-4o-mini")
# How many candidate companies to hand the extraction LLM. Wide enough to include
# companies keyword-ranking can't isolate (a company that flags the theme in only a
# few chunks ranks deep among the ~1,200 that mention it), bounded so one LLM call
# stays cheap. Tunable up for deeper recall at more latency/cost.
_CANDIDATE_LIMIT = int(os.environ.get("THEMATIC_CANDIDATE_LIMIT", "120"))
_WINDOW_DAYS = int(os.environ.get("THEMATIC_WINDOW_DAYS", "75"))


def _openai_client():
    """OpenAI client or None (graceful — missing SDK/key must not crash the route)."""
    try:
        from openai import OpenAI
        from nidp.shared.openai_key import get_openai_api_key
    except Exception as exc:  # noqa: BLE001
        logger.warning("thematic: OpenAI unavailable (%s)", exc)
        return None
    key = os.environ.get("THEMATIC_LLM_API_KEY") or get_openai_api_key() or ""
    if not key:
        logger.warning("thematic: no OpenAI key resolved")
        return None
    try:
        return OpenAI(api_key=key, max_retries=3, timeout=40)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thematic: OpenAI client init failed (%s)", exc)
        return None


# ── Step 1: query → tsquery ────────────────────────────────────────────────
_STEM = re.compile(r"[^a-z]")


def _lexeme(word: str) -> str:
    return _STEM.sub("", (word or "").lower())


def _build_tsquery(pivot: List[str], context: List[str]) -> str:
    """Safely build a Postgres tsquery string: (pivot | …) & (context | …).
    Constructed in Python from term lists — the LLM never emits SQL syntax."""
    def grp(words: List[str]) -> str:
        toks = sorted({_lexeme(w) for w in (words or []) if _lexeme(w)})
        return " | ".join(toks)
    p, c = grp(pivot), grp(context)
    if p and c:
        return f"({p}) & ({c})"
    return f"({p or c})" if (p or c) else ""


_CLASSIFY_SYS = (
    "You convert a user's thematic question about Indian-listed-company disclosures into "
    "keyword sets for a full-text search over filing text. Return STRICT JSON: "
    '{"pivot": [..], "context": [..], "theme": ".."}. '
    "pivot = the core subject noun(s) that MUST appear (e.g. for margin pressure: "
    '["margin","profitability"]). context = words signalling the angle/qualifier '
    '(e.g. ["pressure","inflation","cost","headwind","squeeze","rising","input","hike"]). '
    "Use singular stems, lowercase, no phrases. theme = a short human label of what to "
    'look for (e.g. "management flagging margin pressure / rising input costs"). '
    "If the query names no clear subject, put the salient nouns in pivot and leave context empty."
)


def classify_theme(q: str) -> Tuple[str, str]:
    """Query → (tsquery_string, theme_label). Heuristic fallback if the LLM is absent."""
    client = _openai_client()
    if client is not None:
        try:
            resp = client.chat.completions.create(
                model=_MODEL,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _CLASSIFY_SYS},
                    {"role": "user", "content": q[:400]},
                ],
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            tsq = _build_tsquery(data.get("pivot") or [], data.get("context") or [])
            theme = (data.get("theme") or q).strip()[:200]
            if tsq:
                return tsq, theme
        except Exception as exc:  # noqa: BLE001
            logger.warning("thematic: classify LLM failed (%s) — heuristic fallback", exc)
    # Heuristic: OR the query's content lexemes (drop short stopwords).
    stop = {"who", "what", "which", "the", "and", "for", "are", "in", "their", "did",
            "on", "of", "a", "an", "to", "is", "companies", "company", "flagged",
            "this", "that", "any", "recent", "quarter", "q1", "q2", "q3", "q4", "fy",
            "concall", "concalls", "call", "calls"}
    toks = [t for t in re.findall(r"[a-z]+", q.lower()) if len(t) > 2 and t not in stop]
    return _build_tsquery(toks, []), q.strip()[:200]


# ── Step 2: candidate retrieval (GIN-indexed, deduped by company) ───────────
# Rank companies by BREADTH of discussion (how many chunks flag the theme), not by a
# single dense chunk's ts_rank — a company that genuinely discusses margin pressure
# hits the theme across many chunks, whereas ts_rank rewards keyword repetition in one.
# Dedup on a suffix-stripped name so "Elecon … Ltd" and "Elecon … Limited" (and the
# NSE/BSE name variants) count as ONE company. Return each company's single best
# passage (highest ts_rank) for the LLM to read. announcement_attachment excluded
# (newspaper/regulatory noise). $1 tsquery · $2 window-days · $3 candidate limit.
CANDIDATE_SQL = """
    WITH q AS (SELECT $1::tsquery AS tsq),
    matched AS (
        SELECT regexp_replace(
                 regexp_replace(lower(d.company_name),
                   '\\m(limited|ltd|corporation|corp|company|co|pvt|private)\\M', '', 'g'),
                 '[^a-z0-9]', '', 'g') AS norm,
               d.company_name, d.ticker_symbol, d.doc_type, d.filed_at, d.source_url,
               c.text, c.page_start, c.page_end,
               ts_rank(to_tsvector('english', c.text), q.tsq) AS rk
          FROM nidp.document_chunks c
          JOIN nidp.documents d ON d.doc_id = c.doc_id, q
         WHERE d.filed_at >= now() - make_interval(days => $2)
           AND d.doc_type IN ('concall_transcript','investor_presentation','annual_report','financial_results','press_release')
           AND to_tsvector('english', c.text) @@ q.tsq
    ),
    agg  AS (SELECT norm, count(*) AS hits FROM matched GROUP BY norm),
    best AS (SELECT DISTINCT ON (norm) * FROM matched ORDER BY norm, rk DESC)
    SELECT b.company_name, b.ticker_symbol, b.doc_type, b.filed_at, b.source_url,
           b.text, b.page_start, b.page_end, a.hits
      FROM best b JOIN agg a USING (norm)
     ORDER BY a.hits DESC, b.rk DESC
     LIMIT $3
"""


# ── Step 3: LLM extraction (keep only genuine flaggers) ─────────────────────
_EXTRACT_SYS = (
    "You are given a THEME and a numbered list of passages from Indian-listed-company "
    "filings (concall transcripts, presentations, annual reports). Identify ONLY the "
    "companies where MANAGEMENT genuinely expresses / flags the theme — not passages that "
    "merely contain the words, and not analyst questions. For each qualifying company return "
    "the company name, the passage number, and a one-sentence paraphrase of what management "
    'said. Return STRICT JSON: {"matches":[{"company":"..","n":<int>,"statement":".."}]}. '
    "If none qualify, return an empty list. Never invent companies or statements."
)


def extract_flagged(theme: str, candidates: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """LLM keeps only candidates whose management genuinely flagged `theme`.
    Returns the filtered+annotated rows, or None if the LLM is unavailable/failed
    (caller then falls back to the unfiltered ts_rank order)."""
    client = _openai_client()
    if client is None or not candidates:
        return None
    lines = []
    for i, r in enumerate(candidates, 1):
        txt = (r.get("text") or "").replace("\n", " ")[:600]
        lines.append(f"[{i}] {r.get('company_name')}: \"{txt}\"")
    user = f"THEME: {theme}\n\nPASSAGES:\n" + "\n".join(lines)
    try:
        resp = client.chat.completions.create(
            model=_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _EXTRACT_SYS},
                {"role": "user", "content": user[:12000]},
            ],
        )
        data = json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("thematic: extract LLM failed (%s)", exc)
        return None
    out: List[Dict[str, Any]] = []
    for m in (data.get("matches") or []):
        n = m.get("n")
        if not isinstance(n, int) or not (1 <= n <= len(candidates)):
            continue
        row = dict(candidates[n - 1])
        row["statement"] = (m.get("statement") or "").strip()
        out.append(row)
    return out
