"""Intelligence-layer APIs over ref/dq/features/graph/events/analytics schemas."""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, page_params, parse_date, row_to_dict


router = APIRouter(prefix="/intelligence", tags=["intelligence"], dependencies=[Depends(require_api_key)])


class RelationshipType(str, Enum):
    STOCK_STOCK = "STOCK_STOCK"
    STOCK_INDEX = "STOCK_INDEX"
    STOCK_MACRO = "STOCK_MACRO"
    FUND_STOCK  = "FUND_STOCK"


class EventType(str, Enum):
    DIVIDEND     = "DIVIDEND"
    SPLIT        = "SPLIT"
    BONUS        = "BONUS"
    EARNINGS     = "EARNINGS"
    MGMT_CHANGE  = "MGMT_CHANGE"
    ANNOUNCEMENT = "ANNOUNCEMENT"


@router.get("/reference/securities", summary="Canonical security master")
async def reference_securities(
    entity_type:      Optional[str]  = Query(None),
    asset_class:      Optional[str]  = Query(None),
    symbol:           Optional[str]  = Query(None),
    isin:             Optional[str]  = Query(None),
    amfi_scheme_code: Optional[str]  = Query(None),
    sector:           Optional[str]  = Query(None),
    industry:         Optional[str]  = Query(None),
    is_active:        Optional[bool] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT security_id, entity_type, asset_class, symbol, isin, nse_symbol,
                   bse_code, amfi_scheme_code, security_name, sector, industry,
                   is_active, valid_from, valid_to, source_system, created_at, updated_at
              FROM ref.security_master
             WHERE ($1::text IS NULL OR entity_type = $1)
               AND ($2::text IS NULL OR asset_class = $2)
               AND ($3::text IS NULL OR symbol = UPPER($3))
               AND ($4::text IS NULL OR isin = $4)
               AND ($5::text IS NULL OR amfi_scheme_code = $5)
               AND ($6::text IS NULL OR sector = $6)
               AND ($7::text IS NULL OR industry = $7)
               AND ($8::bool IS NULL OR is_active = $8)
             ORDER BY entity_type, symbol NULLS LAST, security_name
             LIMIT $9 OFFSET $10
            """,
            entity_type, asset_class, symbol, isin, amfi_scheme_code, sector, industry, is_active,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/dq/scores", summary="Daily data quality scores")
async def dq_scores(
    target_date:  Optional[str] = Query(None),
    dataset_name: Optional[str] = Query(None),
    quality_tier: Optional[str] = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d = parse_date(target_date, field="target_date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT score_id, target_date, dataset_name,
                   freshness_score, accuracy_score, consistency_score,
                   completeness_score, overall_score, quality_tier, computed_at
              FROM dq.quality_scores
             WHERE ($1::date IS NULL OR target_date = $1)
               AND ($2::text IS NULL OR dataset_name = $2)
               AND ($3::text IS NULL OR quality_tier = $3)
             ORDER BY target_date DESC, computed_at DESC
             LIMIT $4 OFFSET $5
            """,
            d, dataset_name, quality_tier, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/features/stocks/{symbol}", summary="Intelligence feature rows for a stock")
async def intelligence_features(
    symbol: str,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date:   Optional[str] = Query(None, alias="to"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d_from = parse_date(from_date, field="from")
    d_to   = parse_date(to_date,   field="to")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT f.*
              FROM features.stock_features_daily f
              JOIN ref.security_master sm ON sm.security_id = f.security_id
             WHERE sm.symbol = UPPER($1)
               AND ($2::date IS NULL OR f.as_of_date >= $2)
               AND ($3::date IS NULL OR f.as_of_date <= $3)
             ORDER BY f.as_of_date DESC
             LIMIT $4 OFFSET $5
            """,
            symbol, d_from, d_to, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/graph/entity-links", summary="Entity relationship graph edges")
async def entity_links(
    security_id:       Optional[str]              = Query(None, description="Matches either left_security_id or right_security_id"),
    relationship_type: Optional[RelationshipType] = Query(None),
    as_of_date:        Optional[str]              = Query(None),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d = parse_date(as_of_date, field="as_of_date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT link_id, as_of_date, left_security_id, right_security_id,
                   relationship_type, weight_pct, metadata_json,
                   source_system, valid_from, valid_to, created_at
              FROM graph.entity_links
             WHERE ($1::uuid IS NULL OR left_security_id = $1 OR right_security_id = $1)
               AND ($2::text IS NULL OR relationship_type = $2)
               AND ($3::date IS NULL OR as_of_date = $3)
             ORDER BY as_of_date DESC NULLS LAST, created_at DESC
             LIMIT $4 OFFSET $5
            """,
            security_id, relationship_type, d, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/snapshots/market", summary="Market intelligence snapshot")
async def market_intelligence_snapshot(
    on: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to most recent"),
) -> Dict[str, Any]:
    d = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if d is None:
            row = await conn.fetchrow("SELECT * FROM analytics.market_snapshot ORDER BY as_of_date DESC LIMIT 1")
        else:
            row = await conn.fetchrow("SELECT * FROM analytics.market_snapshot WHERE as_of_date = $1", d)
    if row is None:
        raise HTTPException(status_code=404, detail="no intelligence market snapshot found")
    return {"data": row_to_dict(row)}


@router.get("/snapshots/market/recent", summary="Recent market intelligence snapshots")
async def market_intelligence_recent(
    days: int = Query(30, ge=1, le=365),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
              FROM analytics.market_snapshot
             WHERE as_of_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')
             ORDER BY as_of_date DESC
             LIMIT $2 OFFSET $3
            """,
            days, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"days": days})


@router.get("/graph/correlations", summary="Correlation graph edges")
async def correlations(
    security_id:       Optional[str]              = Query(None, description="Matches either side security id"),
    relationship_type: Optional[RelationshipType] = Query(None),
    window_days:       Optional[int]              = Query(None, ge=1, le=3650),
    as_of_date:        Optional[str]              = Query(None),
    min_abs_corr:      float                      = Query(0.0, ge=0.0, le=1.0),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d = parse_date(as_of_date, field="as_of_date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT correlation_id, as_of_date, window_days, left_security_id, right_security_id,
                   relationship_type, correlation_value, abs_correlation, method, created_at
              FROM graph.correlations
             WHERE ($1::uuid IS NULL OR left_security_id = $1 OR right_security_id = $1)
               AND ($2::text IS NULL OR relationship_type = $2)
               AND ($3::int  IS NULL OR window_days = $3)
               AND ($4::date IS NULL OR as_of_date = $4)
               AND abs_correlation >= $5
             ORDER BY as_of_date DESC, abs_correlation DESC
             LIMIT $6 OFFSET $7
            """,
            security_id, relationship_type, window_days, d, min_abs_corr,
            page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


@router.get("/events", summary="Normalized intelligence events")
async def intelligence_events(
    security_id: Optional[str]       = Query(None),
    event_type:  Optional[EventType] = Query(None),
    from_date:   Optional[str]       = Query(None, alias="from"),
    to_date:     Optional[str]       = Query(None, alias="to"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d_from = parse_date(from_date, field="from")
    d_to   = parse_date(to_date,   field="to")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT event_id, security_id, event_date, event_ts, event_type, event_subtype,
                   title, summary, payload_json, impact_score, source_system, source_ref, created_at
              FROM events.normalized_events
             WHERE ($1::uuid IS NULL OR security_id = $1)
               AND ($2::text IS NULL OR event_type = $2)
               AND ($3::date IS NULL OR event_date >= $3)
               AND ($4::date IS NULL OR event_date <= $4)
             ORDER BY event_date DESC, created_at DESC
             LIMIT $5 OFFSET $6
            """,
            security_id, event_type, d_from, d_to, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)


# ── Sector resolution via the master tables ─────────────────────────────────
# A thematic ask often names a SECTOR ("how are IT companies doing", "PSU banks",
# "pharma M&A") rather than one ticker. We resolve the sector to its constituents
# from nidp.sector_master — the golden table that carries {isin, nse_symbol,
# canonical name, sector} — then pull those companies' filings from
# corporate_announcements. Join key is ISIN (NSE filings carry it 100%); BSE
# filings carry neither ISIN nor ticker, so they fall back to a canonical
# (normalised) company-name match. Values below are the exact sector labels in
# nidp.sector_master; phrases are ordered most-specific-first so
# "construction materials"/"consumer durables" win over a bare "construction"/
# "consumer". 'IT' is handled separately (uppercase token / explicit "IT sector")
# so the pronoun "it" never triggers the Information-Technology sector.
_SECTOR_SYNONYMS: List[Tuple[str, List[str]]] = [
    ("Information Technology", ["information technology", "infotech", "software", "it services"]),
    ("Healthcare", ["healthcare", "health care", "pharma", "pharmaceutical", "drugmaker", "hospital", "diagnostic"]),
    ("Finance", ["banking", "bank", "banks", "nbfc", "financial services", "financials", "lender", "lending", "insurance", "insurer"]),
    ("Automobile", ["automobile", "automotive", "auto ancillary", "two-wheeler", "carmaker", "auto sector", "auto stocks", "autos"]),
    ("FMCG", ["fmcg", "consumer staples", "consumer goods"]),
    ("Metals", ["metals", "metal", "steel", "mining", "aluminium", "zinc", "copper"]),
    ("Power", ["power sector", "power compan", "power stock", "power utilit", "electricity", "renewable energy", "thermal power"]),
    ("Oil Gas", ["oil & gas", "oil and gas", "petroleum", "refiner", "refinery", "upstream"]),
    ("Chemicals", ["chemical", "chemicals", "agrochem", "specialty chem"]),
    ("Realty", ["realty", "real estate", "property develop", "housing develop"]),
    ("Telecommunication", ["telecom", "telecommunication", "telco"]),
    ("Construction Materials", ["cement"]),
    ("Capital Goods", ["capital goods", "engineering", "machinery", "defence", "defense"]),
    ("Consumer Durables", ["consumer durable", "durables", "appliance"]),
    ("Consumer Services", ["consumer services", "hospitality", "hotels", "airlines", "aviation"]),
    ("Construction", ["construction", "infrastructure", "epc"]),
    ("Textiles", ["textile", "apparel", "garment"]),
    ("Media", ["media", "broadcast", "entertainment"]),
]


def _detect_sector(q: str) -> Optional[str]:
    """Map a free-text query to a canonical nidp.sector_master sector, else None."""
    if re.search(r"\bIT\b", q) or re.search(r"\bit (sector|compan|stock|space|firm|player|major)", q.lower()):
        return "Information Technology"
    ql = q.lower()
    for sector, kws in _SECTOR_SYNONYMS:
        for kw in kws:
            if re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", ql):
                return sector
    return None


_SECTOR_EVENTS_SQL = """
    WITH secs AS (
        SELECT isin,
               lower(regexp_replace(company_name, '[^a-z0-9]', '', 'gi')) AS norm
          FROM nidp.sector_master
         WHERE sector = $1 AND isin IS NOT NULL AND isin <> ''
    )
    SELECT a.announcement_id            AS doc_id,
           a.company_name               AS entity_name,
           a.event_category             AS event_type,
           a.event_category,
           a.filed_at                   AS event_date,
           a.filed_at,
           a.subject                    AS headline,
           a.subject,
           a.ticker_symbol,
           a.impact_score,
           s.signal_json->>'summary'        AS summary,
           s.signal_json->'headline_metric' AS headline_metric,
           d.source_url
      FROM nidp.corporate_announcements a
      JOIN secs
        ON ( (a.isin IS NOT NULL AND a.isin <> '' AND a.isin = secs.isin)
             OR lower(regexp_replace(a.company_name, '[^a-z0-9]', '', 'gi')) = secs.norm )
      LEFT JOIN nidp.corporate_event_signals s
             ON s.signal_type = 'filing_insight'
            AND s.announcement_ref    = a.announcement_id
            AND s.announcement_source = a.source
      LEFT JOIN LATERAL (
            SELECT dd.source_url FROM nidp.documents dd
             WHERE dd.announcement_id = a.announcement_id
               AND dd.announcement_source = a.source
               AND dd.parse_status = 'parsed'
             ORDER BY dd.filed_at DESC NULLS LAST LIMIT 1
          ) d ON TRUE
     WHERE a.filed_at >= now() - interval '30 days'
       AND a.event_category IS NOT NULL
       AND a.event_category NOT IN ('other', 'regulatory')
     ORDER BY (a.impact_score = 'high') DESC NULLS LAST, a.filed_at DESC
     LIMIT $2 OFFSET $3
"""


@router.get("/events/search", summary="Search normalized intelligence events")
async def intelligence_events_search(
    q: str = Query(..., min_length=1, max_length=128),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    # The events.* schema (normalized_events / v_search_documents) was never
    # populated — 0 rows — so this endpoint returned nothing for every thematic
    # query while the copilot's cross-company "Ask" leans on it. The real filings
    # (with AI event_category + the filing_insight summary/metric) live in
    # nidp.corporate_announcements. Query THAT.
    #
    # A sector query ("how are IT companies doing", "pharma M&A") resolves to its
    # constituents via nidp.sector_master (ISIN + canonical name) and returns their
    # material filings — see _SECTOR_EVENTS_SQL. This is the golden-data path the
    # copilot relies on for cross-company sector asks.
    sector = _detect_sector(q)
    if sector:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(_SECTOR_EVENTS_SQL, sector, page["limit"], page["offset"])
        return envelope([row_to_dict(r) for r in rows], **page, extra={"query": q, "sector": sector})

    # Otherwise, free-text match over the announcement subject + category.
    # Matching: plainto_tsquery ANDs every term ('dividend' & 'declar' & 'quarter'),
    # so a natural-language ask like "Dividends declared this quarter" matched NO
    # subject (a filing reads just "Dividend" / "Record Date" — it has 'dividend'
    # but not 'declar' AND 'quarter'). Users type intent as a phrase, not the exact
    # subject line, so AND-of-all-terms is wrong here. Rewrite the AND-query to an
    # OR-query (share ANY stemmed term) via replace(::text,' & ',' | '), rank by
    # ts_rank so the filings hitting the most terms surface first, then break ties
    # material-and-recent. 'english' config stems (dividends->dividend, orders->order)
    # and drops stopwords. Empty tsquery (all-stopword input) matches nothing safely.
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH qq AS (
                SELECT NULLIF(replace(plainto_tsquery('english', $1)::text, ' & ', ' | '), '')::tsquery AS tsq,
                       lower(btrim($1)) AS cat
            )
            SELECT a.announcement_id            AS doc_id,
                   a.company_name               AS entity_name,
                   a.event_category             AS event_type,
                   a.event_category,
                   a.filed_at                   AS event_date,
                   a.filed_at,
                   a.subject                    AS headline,
                   a.subject,
                   a.ticker_symbol,
                   a.impact_score,
                   s.signal_json->>'summary'        AS summary,
                   s.signal_json->'headline_metric' AS headline_metric,
                   d.source_url
              FROM nidp.corporate_announcements a
              CROSS JOIN qq
              LEFT JOIN nidp.corporate_event_signals s
                     ON s.signal_type = 'filing_insight'
                    AND s.announcement_ref    = a.announcement_id
                    AND s.announcement_source = a.source
              LEFT JOIN LATERAL (
                    SELECT dd.source_url FROM nidp.documents dd
                     WHERE dd.announcement_id = a.announcement_id
                       AND dd.announcement_source = a.source
                       AND dd.parse_status = 'parsed'
                     ORDER BY dd.filed_at DESC NULLS LAST LIMIT 1
                  ) d ON TRUE
             WHERE a.filed_at >= now() - interval '30 days'
               AND a.event_category IS NOT NULL
               AND a.event_category NOT IN ('other', 'regulatory')
               AND ( to_tsvector('english',
                        coalesce(a.subject,'') || ' ' || coalesce(replace(a.event_category,'_',' '),''))
                        @@ qq.tsq
                     OR a.event_category = qq.cat )
             ORDER BY ts_rank(
                        to_tsvector('english',
                          coalesce(a.subject,'') || ' ' || coalesce(replace(a.event_category,'_',' '),'')),
                        qq.tsq) DESC NULLS LAST,
                      (a.impact_score = 'high') DESC NULLS LAST,
                      a.filed_at DESC
             LIMIT $2 OFFSET $3
            """,
            q, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"query": q})


@router.get("/thematic-commentary",
            summary="Cross-company 'who flagged X?' — LLM-curated management commentary")
async def thematic_commentary(
    q: str = Query(..., min_length=3, max_length=200),
    depth: int = Query(150, ge=20, le=1500,
                       description="candidate companies the LLM reads (deeper = better recall, more latency)"),
    show_all: bool = Query(False, alias="all",
                           description="true = the full keyword-matched company list (paginated), skipping LLM curation"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    """Precise cross-company thematic commentary. A wide keyword net over the chunk
    corpus (GIN-indexed, deduped by company, ranked by breadth of discussion) yields
    the candidates; an LLM then reads the passages and keeps ONLY the companies whose
    management genuinely flagged the theme — the curated 'who flagged X?' answer that
    keyword/vector ranking alone cannot produce. Degrades to the comprehensive
    keyword-ranked list if the LLM is unavailable. See daas_api.thematic_search."""
    import asyncio
    from nidp.services.daas_api import thematic_search as _ts

    # Daily result cache: thematic results are market-wide and expensive, so serve the
    # cached full list for (query, depth, all) if it was computed today; a new day misses
    # and recomputes ("refresh next day"). Pagination slices the cached list.
    ckey = _ts.cache_key(q, depth, show_all)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await _ts.ensure_cache(conn)
        cached = await _ts.cache_get(conn, ckey)

    if cached is None:
        tsq, theme, variations = await asyncio.to_thread(_ts.classify_theme, q)
        if not tsq:
            return envelope([], **page, extra={"query": q, "theme": theme, "note": "no searchable terms"})

        async with pool.acquire() as conn:
            rows = await conn.fetch(_ts.CANDIDATE_SQL, tsq, _ts._WINDOW_DAYS, depth)
        candidates = [row_to_dict(r) for r in rows]

        # LLM extraction over the candidate set, batched and run concurrently.
        BATCH = 50
        batches = [candidates[i:i + BATCH] for i in range(0, len(candidates), BATCH)]
        results = await asyncio.gather(
            *[asyncio.to_thread(_ts.extract_flagged, theme, b) for b in batches]
        ) if batches else []

        used_llm = any(r is not None for r in results)
        # show_all=true (or LLM unavailable) → the full keyword-matched list, not just the
        # LLM-curated flaggers. Either way, collapse to one row per company (a company can
        # appear in several passages), keeping its strongest (highest-intensity) hit.
        curated = used_llm and not show_all
        rows_out = ([row for r in results if r for row in r]
                    if curated else candidates)
        if curated:  # strongest passage first so dedup keeps it
            rows_out = sorted(rows_out, key=lambda r: (r.get("intensity") or 0), reverse=True)

        flagged: List[Dict[str, Any]] = []
        seen: set = set()
        for row in rows_out:
            dk = re.sub(r"[^a-z0-9]", "",
                        re.sub(r"\b(limited|ltd|corporation|corp|company|co|pvt|private)\b", "",
                               (row.get("company_name") or "").lower()))
            if dk and dk not in seen:
                seen.add(dk)
                flagged.append(row)

        # Ranking: market-cap tier first (large -> mid -> small -> micro -> unknown) UNLESS
        # the user explicitly asked for a segment, then intensity (curated) / breadth
        # (show-all) within tier. "Explicitly asked" = the query names a cap segment.
        ql = q.lower()
        only_tier = ("LARGE_CAP" if re.search(r"large[- ]?cap|bluechip|blue chip", ql)
                     else "MID_CAP" if re.search(r"mid[- ]?cap", ql)
                     else "SMALL_CAP" if re.search(r"small[- ]?cap", ql)
                     else "MICRO_CAP" if re.search(r"micro[- ]?cap", ql)
                     else None)
        if only_tier:
            flagged = [r for r in flagged if (r.get("market_cap_bucket") or "").upper() == only_tier]
        flagged.sort(key=lambda r: (
            _ts.cap_rank(r.get("market_cap_bucket")),
            -(r.get("intensity") or 0) if curated else -(r.get("hits") or 0),
        ))

        payload = {
            "theme": theme, "variations": variations, "curated": curated,
            "cap_filter": only_tier, "candidates_scanned": len(candidates), "flagged": flagged,
        }
        async with pool.acquire() as conn:
            await _ts.cache_put(conn, ckey, q, payload)
    else:
        payload = cached

    flagged = payload.get("flagged") or []
    window = flagged[page["offset"]: page["offset"] + page["limit"]]
    return envelope(window, **page, extra={
        "query": q, "theme": payload.get("theme"), "variations": payload.get("variations"),
        "curated": payload.get("curated"), "cap_filter": payload.get("cap_filter"),
        "candidates_scanned": payload.get("candidates_scanned"), "matches": len(flagged),
        "cached": cached is not None,
    })


@router.get("/events/{event_id}", summary="Single normalized event")
async def intelligence_event_detail(event_id: str) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT event_id, security_id, event_date, event_ts, event_type, event_subtype,
                   title, summary, payload_json, impact_score, source_system, source_ref, created_at
              FROM events.normalized_events
             WHERE event_id = $1::uuid
            """,
            event_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="event not found")
    return {"data": row_to_dict(row)}


@router.post("/graph/correlations/bulk", summary="Pairwise correlations for a portfolio of securities")
async def portfolio_correlations_bulk(
    body: Dict[str, Any] = Body(
        ...,
        example={"security_ids": ["<uuid1>", "<uuid2>", "<uuid3>"]},
    ),
    min_abs_corr: float = Query(0.0, ge=0.0, le=1.0),
    window_days:  Optional[int] = Query(None, ge=1, le=3650),
) -> Dict[str, Any]:
    """Return all pairwise correlations where BOTH sides are in the supplied
    security_id list — i.e. the correlation subgraph for a portfolio.

    Accepts up to 50 security_ids. Returns pairs ordered by abs_correlation DESC.
    Missing pairs (not enough shared history) are simply absent.
    """
    raw_ids: List[str] = body.get("security_ids") or []
    if not isinstance(raw_ids, list):
        raise HTTPException(status_code=400, detail="security_ids must be a list")
    ids = [s.strip() for s in raw_ids if isinstance(s, str) and s.strip()]
    if not ids:
        return {"data": [], "count": 0, "requested": 0}
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail="security_ids must not exceed 50")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Use the latest available date for each pair when no window specified
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (LEAST(c.left_security_id, c.right_security_id),
                                GREATEST(c.left_security_id, c.right_security_id))
                   c.correlation_id, c.as_of_date, c.window_days,
                   c.left_security_id, c.right_security_id,
                   c.relationship_type, c.correlation_value, c.abs_correlation, c.method,
                   c.created_at
              FROM graph.correlations c
             WHERE c.left_security_id  = ANY($1::uuid[])
               AND c.right_security_id = ANY($1::uuid[])
               AND c.left_security_id != c.right_security_id
               AND ($2::int IS NULL OR c.window_days = $2)
               AND c.abs_correlation >= $3
             ORDER BY LEAST(c.left_security_id, c.right_security_id),
                      GREATEST(c.left_security_id, c.right_security_id),
                      c.as_of_date DESC
            """,
            ids, window_days, min_abs_corr,
        )
    result = [row_to_dict(r) for r in rows]
    return {"data": result, "count": len(result), "requested": len(ids)}


@router.get("/graph/correlations/{security_id}/top", summary="Top correlation peers for one security")
async def top_correlations(
    security_id: str,
    as_of_date:  Optional[str] = Query(None),
    top_n:       int           = Query(20, ge=1, le=200),
    direction:   str           = Query("both", pattern="^(positive|negative|both)$"),
) -> Dict[str, Any]:
    d = parse_date(as_of_date, field="as_of_date")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.correlation_id, c.as_of_date, c.window_days,
                   c.left_security_id, c.right_security_id,
                   c.relationship_type, c.correlation_value, c.abs_correlation, c.method,
                   c.created_at
              FROM graph.correlations c
             WHERE ($1::uuid = c.left_security_id OR $1::uuid = c.right_security_id)
               AND ($2::date IS NULL OR c.as_of_date = $2)
               AND (
                       $3::text = 'both'
                    OR ($3::text = 'positive' AND c.correlation_value > 0)
                    OR ($3::text = 'negative' AND c.correlation_value < 0)
                   )
             ORDER BY c.abs_correlation DESC, c.as_of_date DESC
             LIMIT $4
            """,
            security_id, d, direction, top_n,
        )
    return {"data": [row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/portfolio/{external_user_id}/snapshot", summary="User portfolio intelligence snapshot")
async def portfolio_snapshot(
    external_user_id: str,
    on: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to latest"),
) -> Dict[str, Any]:
    d = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if d is None:
            row = await conn.fetchrow(
                """
                SELECT * FROM portfolio.user_intelligence_snapshot
                 WHERE external_user_id = $1
                 ORDER BY snapshot_date DESC LIMIT 1
                """,
                external_user_id,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT * FROM portfolio.user_intelligence_snapshot
                 WHERE external_user_id = $1 AND snapshot_date = $2
                 LIMIT 1
                """,
                external_user_id, d,
            )
    if row is None:
        raise HTTPException(status_code=404, detail="portfolio snapshot not found")
    return {"data": row_to_dict(row)}


@router.get("/portfolio/{external_user_id}/holdings", summary="User holdings resolved against security master")
async def portfolio_holdings(
    external_user_id: str,
    on: Optional[str] = Query(None, description="YYYY-MM-DD; defaults to latest"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    d = parse_date(on, field="on")
    pool = await get_pool()
    async with pool.acquire() as conn:
        if d is None:
            d = await conn.fetchval(
                "SELECT max(snapshot_date) FROM portfolio.user_holdings_snapshot WHERE external_user_id = $1",
                external_user_id,
            )
        rows = await conn.fetch(
            """
            SELECT h.snapshot_id, h.snapshot_date, h.asset_class, h.symbol, h.isin, h.amfi_scheme_code,
                   h.instrument_name, h.quantity, h.avg_buy_price, h.market_value_inr, h.weight_pct,
                   m.security_id, m.match_confidence, m.match_method,
                   sm.security_name, sm.sector, sm.industry,
                   fcr.ter             AS expense_ratio,
                   fcr.return_1y       AS ret_1y,
                   fcr.return_3y       AS ret_3y,
                   fcr.return_5y       AS ret_5y,
                   fcr.rank_date       AS perf_as_of
              FROM portfolio.user_holdings_snapshot h
              LEFT JOIN portfolio.holding_security_map m ON m.snapshot_id = h.snapshot_id
              LEFT JOIN ref.security_master sm           ON sm.security_id = m.security_id
              LEFT JOIN LATERAL (
                  SELECT ter, return_1y, return_3y, return_5y, rank_date
                    FROM analytics.fund_category_rank
                   WHERE scheme_code = h.amfi_scheme_code
                   ORDER BY rank_date DESC
                   LIMIT 1
              ) fcr ON h.amfi_scheme_code IS NOT NULL
             WHERE h.external_user_id = $1
               AND ($2::date IS NULL OR h.snapshot_date = $2)
             ORDER BY h.market_value_inr DESC
             LIMIT $3 OFFSET $4
            """,
            external_user_id, d, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page, extra={"external_user_id": external_user_id, "snapshot_date": str(d) if d else None})


@router.get("/portfolio/sync/status", summary="Portfolio sync audit log (latest run per client)")
async def portfolio_sync_status(
    external_user_id: Optional[str] = Query(None, description="Filter by email"),
    page: Dict[str, int] = Depends(page_params),
) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                cm.external_user_id,
                cm.display_name,
                cm.last_sync_at,
                sal.snapshot_date,
                sal.status,
                sal.holdings_upserted,
                sal.synced_at,
                sal.error_detail
            FROM portfolio.client_master cm
            LEFT JOIN LATERAL (
                SELECT snapshot_date, status, holdings_upserted, synced_at, error_detail
                  FROM portfolio.sync_audit_log sal
                 WHERE sal.external_user_id = cm.external_user_id
                 ORDER BY synced_at DESC
                 LIMIT 1
            ) sal ON TRUE
            WHERE ($1::text IS NULL OR cm.external_user_id = $1)
            ORDER BY cm.last_sync_at DESC NULLS LAST
            LIMIT $2 OFFSET $3
            """,
            external_user_id, page["limit"], page["offset"],
        )
    return envelope([row_to_dict(r) for r in rows], **page)
