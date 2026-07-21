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

import hashlib
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


def _build_tsquery_multi(variations: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    """UNION every variation's pivot+context terms into ONE broad (pivots) & (contexts)
    tsquery. Union — not per-variation clauses — because the LLM's variation set is not
    stable run-to-run: if it omits a specific pairing (e.g. "raw material" one call), the
    union still matches any pivot with any context, so a company that phrased the theme with
    a cost driver the LLM didn't pair is still caught. The LLM extraction step re-imposes
    precision. Returns (tsquery, human labels of the variations fired)."""
    pivots: set = set()
    contexts: set = set()
    labels: List[str] = []
    for v in variations or []:
        pivots.update(_lexeme(w) for w in (v.get("pivot") or []) if _lexeme(w))
        contexts.update(_lexeme(w) for w in (v.get("context") or []) if _lexeme(w))
        piv = "/".join(v.get("pivot") or []) or "-"
        ctx = "/".join(v.get("context") or []) or "-"
        labels.append(f"{piv} ~ {ctx}")
    return _build_tsquery(sorted(pivots), sorted(contexts)), labels


_CLASSIFY_SYS = (
    "You expand a user's thematic question about Indian-listed-company disclosures into up to "
    "5 SEMANTIC VARIATIONS (same intent, DIFFERENT vocabulary) so a full-text search over "
    "filing text does not miss a company that phrases the theme differently. Return STRICT "
    'JSON: {"theme": "..", "variations": [{"pivot": [..], "context": [..]}, ...]}. '
    "For EACH variation: pivot = the core subject noun(s) that MUST appear; context = words "
    "signalling the angle/qualifier. Singular stems, lowercase, no phrases. BE EXHAUSTIVE: "
    "cover synonyms AND the specific real-world drivers a company might cite. For a margins/"
    "costs theme the pivots MUST include the cost drivers themselves — raw material, input, "
    "commodity, energy, power, fuel, freight, logistics, packaging, wage, forex — alongside "
    "margin/profitability/gross/ebitda; contexts cover pressure, squeeze, compression, "
    "decline, inflation, rising, increase, escalation, surge, hike, headwind, volatility. "
    "Give 5-8 variations (at least 2 if the query has any clear subject). theme = short human label."
)


def classify_theme(q: str) -> Tuple[str, str, List[str]]:
    """Query → (combined_tsquery, theme_label, variation_labels). The tsquery ORs up to 5
    semantic variations so different phrasings are all searched in one scan. Heuristic
    single-query fallback if the LLM is unavailable."""
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
            tsq, labels = _build_tsquery_multi(data.get("variations") or [])
            theme = (data.get("theme") or q).strip()[:200]
            if tsq:
                return tsq, theme, labels
        except Exception as exc:  # noqa: BLE001
            logger.warning("thematic: classify LLM failed (%s) — heuristic fallback", exc)
    # Heuristic: OR the query's content lexemes (drop short stopwords).
    stop = {"who", "what", "which", "the", "and", "for", "are", "in", "their", "did",
            "on", "of", "a", "an", "to", "is", "companies", "company", "flagged",
            "this", "that", "any", "recent", "quarter", "q1", "q2", "q3", "q4", "fy",
            "concall", "concalls", "call", "calls"}
    toks = [t for t in re.findall(r"[a-z]+", q.lower()) if len(t) > 2 and t not in stop]
    return _build_tsquery(toks, []), q.strip()[:200], []


# ── Step 2: candidate retrieval (GIN-indexed, deduped by company) ───────────
# Rank companies by BREADTH of discussion (how many chunks flag the theme), not by a
# single dense chunk's ts_rank — a company that genuinely discusses margin pressure
# hits the theme across many chunks, whereas ts_rank rewards keyword repetition in one.
# Dedup on a suffix-stripped name so "Elecon … Ltd" and "Elecon … Limited" (and the
# NSE/BSE name variants) count as ONE company. Rank companies by breadth of discussion
# (hit count), take the top $3, and hand the LLM the top _PASSAGES_PER_CO passages of
# EACH — one chunk isn't enough (a company's best-ranked chunk can be a product blurb
# while its actual margin flag sits in a 2nd chunk). announcement_attachment excluded
# (newspaper/regulatory noise). $1 tsquery · $2 window-days · $3 company limit.
_PASSAGES_PER_CO = int(os.environ.get("THEMATIC_PASSAGES_PER_CO", "2"))

# Market-cap tier ordering (large first, then mid, small, micro; unknown last) — the
# default ranking after intensity is applied WITHIN each tier. Overridable when the user
# explicitly asks for a segment (see the endpoint's cap-preference detection).
_CAP_ORDER = {"LARGE_CAP": 0, "MID_CAP": 1, "SMALL_CAP": 2, "MICRO_CAP": 3}


def cap_rank(bucket: Optional[str]) -> int:
    return _CAP_ORDER.get((bucket or "").upper(), 4)


# ── Daily result cache ──────────────────────────────────────────────────────
# Thematic results are market-wide (not per-user) and expensive (~40s + LLM cost),
# so cache the full ranked list per (query, depth, all) for the DAY. A new day is a
# cache miss -> recompute, giving the "refresh next day" behaviour. Best-effort: any
# cache error degrades to a live compute. The table is created lazily (no migration).
_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS nidp.thematic_cache (
  cache_key   text        NOT NULL,
  day         date        NOT NULL DEFAULT CURRENT_DATE,
  query       text        NOT NULL,
  payload     jsonb       NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cache_key, day)
)
"""


def cache_key(q: str, depth: int, show_all: bool) -> str:
    norm = " ".join((q or "").lower().split())
    return hashlib.sha256(f"{norm}|{depth}|{int(bool(show_all))}".encode()).hexdigest()


async def ensure_cache(conn) -> None:
    try:
        await conn.execute(_CACHE_DDL)
    except Exception as exc:  # noqa: BLE001 — cache is best-effort
        logger.warning("thematic: ensure_cache failed (%s)", exc)


async def cache_get(conn, key: str) -> Optional[Any]:
    try:
        row = await conn.fetchrow(
            "SELECT payload FROM nidp.thematic_cache WHERE cache_key=$1 AND day=CURRENT_DATE", key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thematic: cache_get failed (%s)", exc)
        return None
    if not row:
        return None
    p = row["payload"]
    return json.loads(p) if isinstance(p, str) else p


async def cache_put(conn, key: str, query: str, payload: Any) -> None:
    try:
        await conn.execute(
            """INSERT INTO nidp.thematic_cache (cache_key, query, payload)
                    VALUES ($1, $2, $3::jsonb)
               ON CONFLICT (cache_key, day)
                    DO UPDATE SET payload = EXCLUDED.payload, created_at = now()""",
            key, query, json.dumps(payload, default=str))
        await conn.execute("DELETE FROM nidp.thematic_cache WHERE day < CURRENT_DATE - 7")
    except Exception as exc:  # noqa: BLE001
        logger.warning("thematic: cache_put failed (%s)", exc)
CANDIDATE_SQL = """
    WITH q AS (SELECT $1::tsquery AS tsq),
    matched AS (
        SELECT regexp_replace(
                 regexp_replace(lower(d.company_name),
                   '\\m(limited|ltd|corporation|corp|company|co|pvt|private)\\M', '', 'g'),
                 '[^a-z0-9]', '', 'g') AS norm,
               d.company_name, d.ticker_symbol, d.doc_type, d.filed_at, d.source_url,
               c.text, c.page_start, c.page_end,
               ts_rank(to_tsvector('english', c.text), q.tsq) AS rk,
               sc.market_cap_bucket
          FROM nidp.document_chunks c
          JOIN nidp.documents d ON d.doc_id = c.doc_id
          LEFT JOIN nidp.v_v3_stock_scores_latest sc ON sc.symbol = d.ticker_symbol
          CROSS JOIN q
         WHERE d.filed_at >= now() - make_interval(days => $2)
           AND d.doc_type IN ('concall_transcript','investor_presentation','annual_report','financial_results','press_release')
           AND to_tsvector('english', c.text) @@ q.tsq
    ),
    agg   AS (SELECT norm, count(*) AS hits FROM matched GROUP BY norm),
    topco AS (SELECT norm, hits FROM agg ORDER BY hits DESC LIMIT $3),
    ranked AS (
        SELECT m.*, t.hits,
               row_number() OVER (PARTITION BY m.norm ORDER BY m.rk DESC) AS prn
          FROM matched m JOIN topco t USING (norm)
    )
    SELECT company_name, ticker_symbol, doc_type, filed_at, source_url,
           text, page_start, page_end, hits, market_cap_bucket
      FROM ranked
     WHERE prn <= %d
     ORDER BY hits DESC, rk DESC
""" % _PASSAGES_PER_CO


# ── Step 3: LLM extraction (keep only genuine flaggers) ─────────────────────
_EXTRACT_SYS = (
    "You are given a THEME and a numbered list of passages from Indian-listed-company "
    "filings (concall transcripts, presentations, annual reports). Identify ONLY the "
    "companies where MANAGEMENT genuinely FLAGS the theme AS A CONCERN, in the DIRECTION the "
    "theme implies. A passage qualifies only if management is actually experiencing / warning "
    "of the theme — e.g. for 'margin pressure / rising input costs': the margin is under "
    "pressure or compressing, or a cost is actually rising. EXCLUDE: the opposite direction "
    "(margins IMPROVING, costs EASING, pressure that management says is fully offset/resolved), "
    "generic risk-factor boilerplate with no actual occurrence in the period, passages that "
    "merely contain the words, and analyst questions. When unsure, EXCLUDE. For each "
    "qualifying company return: "
    "company, n (the passage number), statement (a one-sentence paraphrase of what management "
    "said), metric (the single most telling NUMBER management cited about the theme — e.g. "
    "'input cost +15%', 'gross margin -300bps', 'raw material Rs.1.50/sq.ft'; null if none), "
    "and intensity (integer 0-100 = how STRONGLY they flagged it: weight the MAGNITUDE of any "
    "number cited AND the strength of the language — sharp/steep/significant/severe/"
    "unprecedented/distress = high; slight/marginal/modest/manageable = low; no number + mild "
    'wording = low). Return STRICT JSON: {"matches":[{"company":"..","n":<int>,"statement":".."'
    ',"metric":"..","intensity":<int>}]}. If none qualify, return an empty list. Never invent '
    "companies, numbers, or statements."
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
        row["metric"] = (m.get("metric") or None) or None
        try:
            row["intensity"] = max(0, min(100, int(m.get("intensity"))))
        except (TypeError, ValueError):
            row["intensity"] = 0
        out.append(row)
    return out
