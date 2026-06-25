"""Sector Analysis — AI sector-overview cards backed by real NIDP data.

Each card covers one of the 8 sector *profiles* the platform already scores
against (BANK, NBFC, IT, FMCG, PHARMA, CAPGOODS, CYCLICAL, DEFAULT — see
nidp.services.sector_scoring.classifier). For each profile we:

  1. Aggregate VERIFIED quantitative facts from the data lake (per-stock
     market cap + valuation + returns, classified into a profile) — this is
     the grounded, deterministic part. Numbers come only from:
       • analytics.stock_card           (company, sector, 1d/5d/20d/60d return)
       • nidp.stock_features_daily      (market_cap_cr, pe_ttm, pb, roe_pct)
       • nidp.index_eod                 (the matching NSE sector index)

  2. Ask Claude for a short qualitative commentary (drivers / risks / outlook)
     grounded in those facts. This is clearly labelled AI commentary in the UI
     and carries a disclaimer — the model's world knowledge is NOT presented as
     platform data.

Mirrors the Daily-Iris-Update pattern in routes/markets.py: the grounded
metrics are cheap and built lazily on read; the LLM commentary is generated
lazily per sector on first detail view (and refreshed in bulk by
POST /api/markets/sectors/generate).

Auth: reads ANTHROPIC_API_KEY from helpers.secrets first (admin-console
updates take effect immediately), then the env var. Model defaults to
claude-opus-4-8; override via the DB setting SECTOR_ANALYSIS_MODEL.
"""
from __future__ import annotations

import logging
import os
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# `anthropic` is imported lazily inside _get_client() (project convention — it is
# a runtime-only dependency installed on the app VMs, not declared in
# requirements.txt). This keeps the module importable, and the grounded-metrics
# path working, in environments where the SDK isn't present.

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 1400
TOP_COMPANIES = 6
MIN_STOCKS = 3   # don't surface a profile with too few names to be meaningful

COMMENTARY_DISCLAIMER = (
    "AI-generated commentary. The figures above are from the Nivesh data "
    "platform (NSE/NIDP); the qualitative drivers, risks and outlook below are "
    "Claude's interpretation and may not reflect the latest developments. Not "
    "investment advice."
)

# ── Sector profiles → display metadata + NSE benchmark index ──────────────────
# Profiles mirror nidp.services.sector_scoring.classifier.ALL_PROFILES.
PROFILES: List[Dict[str, str]] = [
    {"slug": "banks",              "profile": "BANK",     "name": "Banks",
     "icon": "🏦", "benchmark": "Nifty Bank",                "blurb": "Public & private sector banks"},
    {"slug": "financial-services", "profile": "NBFC",     "name": "Financial Services (NBFC)",
     "icon": "💳", "benchmark": "Nifty Financial Services",  "blurb": "NBFCs, housing & consumer finance"},
    {"slug": "it",                 "profile": "IT",       "name": "Information Technology",
     "icon": "💻", "benchmark": "Nifty IT",                  "blurb": "IT services & software"},
    {"slug": "fmcg",               "profile": "FMCG",     "name": "FMCG & Consumer",
     "icon": "🛒", "benchmark": "Nifty FMCG",                "blurb": "Consumer staples & durables"},
    {"slug": "pharma",             "profile": "PHARMA",   "name": "Pharma & Healthcare",
     "icon": "💊", "benchmark": "Nifty Pharma",              "blurb": "Pharma, hospitals & diagnostics"},
    {"slug": "capital-goods",      "profile": "CAPGOODS", "name": "Capital Goods & Infrastructure",
     "icon": "🏗️", "benchmark": "Nifty Infrastructure",      "blurb": "Engineering, defence & infra"},
    {"slug": "cyclicals",          "profile": "CYCLICAL", "name": "Cyclicals",
     "icon": "⚙️", "benchmark": "Nifty 500",                 "blurb": "Auto, metals, energy, cement & realty"},
    {"slug": "diversified",        "profile": "DEFAULT",  "name": "Diversified & Others",
     "icon": "🧭", "benchmark": "Nifty 500",                 "blurb": "Telecom, media, services & others"},
]
_BY_PROFILE = {p["profile"]: p for p in PROFILES}
_BY_SLUG = {p["slug"]: p for p in PROFILES}

# ── Sector → profile mapping (based on NIDP classifier; first match wins) ─────
# NOTE: PHARMA keywords are placed BEFORE the IT block on purpose — the bare
# "technology" keyword would otherwise swallow "Biotechnology" into IT (a latent
# ordering bug in the upstream NIDP classifier). Order is otherwise faithful.
_SECTOR_MAP: List[tuple] = [
    ("bank", "BANK"), ("banking", "BANK"),
    ("nbfc", "NBFC"), ("finance", "NBFC"), ("housing finance", "NBFC"), ("microfinance", "NBFC"),
    ("pharma", "PHARMA"), ("healthcare", "PHARMA"), ("biotechnology", "PHARMA"),
    ("hospital", "PHARMA"), ("diagnostics", "PHARMA"),
    ("information technology", "IT"), ("software", "IT"), ("it services", "IT"), ("technology", "IT"),
    ("fmcg", "FMCG"), ("consumer staple", "FMCG"), ("personal care", "FMCG"),
    ("tobacco", "FMCG"), ("beverages", "FMCG"), ("food", "FMCG"),
    ("capital goods", "CAPGOODS"), ("industrial", "CAPGOODS"), ("infrastructure", "CAPGOODS"),
    ("engineering", "CAPGOODS"), ("defence", "CAPGOODS"), ("aerospace", "CAPGOODS"),
    ("consumer durable", "FMCG"), ("consumer electronic", "FMCG"),
    ("construction material", "CYCLICAL"), ("metal", "CYCLICAL"), ("mining", "CYCLICAL"),
    ("cement", "CYCLICAL"), ("automobile", "CYCLICAL"), ("auto", "CYCLICAL"),
    ("chemical", "CYCLICAL"), ("real estate", "CYCLICAL"), ("oil", "CYCLICAL"),
    ("gas", "CYCLICAL"), ("power", "CYCLICAL"), ("steel", "CYCLICAL"),
    ("aluminium", "CYCLICAL"), ("realty", "CYCLICAL"), ("textile", "CYCLICAL"),
    ("paper", "CYCLICAL"), ("plastic", "CYCLICAL"),
    ("construction", "CAPGOODS"),
]


def _classify(sector: Optional[str], industry: Optional[str]) -> str:
    for text in (sector, industry):
        if not text:
            continue
        norm = text.lower().strip()
        for keyword, profile in _SECTOR_MAP:
            if keyword in norm:
                return profile
    return "DEFAULT"


# ── Anthropic client (mirrors services/claude_cas_parser.py) ──────────────────
def _api_key() -> Optional[str]:
    try:
        from helpers import secrets as _secrets
        key = _secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except ImportError:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def _model() -> str:
    try:
        from helpers import secrets as _secrets
        return _secrets.get("SECTOR_ANALYSIS_MODEL") or DEFAULT_MODEL
    except ImportError:
        return os.environ.get("SECTOR_ANALYSIS_MODEL") or DEFAULT_MODEL


def is_llm_configured() -> bool:
    return bool(_api_key())


_client: Optional[Any] = None


def _get_client():
    """Lazy Anthropic client. Imports the SDK on first use; re-created if the
    API key changes between calls (mirrors services/claude_cas_parser.py)."""
    global _client
    key = _api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY missing — cannot generate sector commentary")
    import anthropic  # runtime-only dep — see module docstring
    if _client is None or getattr(_client, "_cached_key", None) != key:
        _client = anthropic.AsyncAnthropic(api_key=key)
        _client._cached_key = key  # type: ignore[attr-defined]
    return _client


# ── Helpers ───────────────────────────────────────────────────────────────────
def _f(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2) if v is not None else None
    except (TypeError, ValueError):
        return None


def _median(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 2) if vals else None


# ── Grounding: fetch real per-stock facts from the data lake ──────────────────
async def _fetch_stocks(pool) -> List[Dict[str, Any]]:
    """Per-stock facts for the latest trading day, as unified dicts:
    {symbol, name, sector, industry, return_1y_pct, market_cap_cr, pe_ttm, pb,
    roe_pct, _as_of}.

    Prefers the DaaS screener: on Cloud Run the app's own Postgres does NOT carry
    the ingested nidp.* rows (often not even the tables), so the sector
    aggregates must be sourced over DaaS like the other Market Pulse tabs. Falls
    back to a direct PG read of nidp.stock_features_daily where the data lake is
    colocated with the app. Real data only — [] when neither path yields rows.
    """
    rows = await _fetch_stocks_daas()
    if rows:
        return rows
    return await _fetch_stocks_pg(pool)


async def _fetch_stocks_daas() -> List[Dict[str, Any]]:
    """Universe via the deployed DaaS /v1/stocks/screener (nidp.stock_features_daily)."""
    try:
        from services.copilot_tools import daas_client
        if not daas_client.is_configured():
            return []
        # 600 largest-cap names span all 8 profiles with room to spare; a smaller
        # payload + a longer timeout avoids the silent timeout that left the grid
        # empty at limit=2000.
        rows = await daas_client.get_stock_screener(
            limit=600, sort_by="market_cap_cr", timeout=30.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("sector_analysis daas screener failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not r.get("sector"):
            continue
        out.append({
            "symbol":        r.get("symbol"),
            "name":          r.get("symbol"),   # screener carries no company name
            "sector":        r.get("sector"),
            "industry":      r.get("industry"),
            "return_1y_pct": _f(r.get("return_252d_pct")),
            "market_cap_cr": _f(r.get("market_cap_cr")),
            "pe_ttm":        _f(r.get("pe_ttm")),
            "pb":            _f(r.get("pb")),
            "roe_pct":       _f(r.get("roe_pct")),
            "_as_of":        r.get("as_of_date"),
        })
    return out


async def _fetch_stocks_pg(pool) -> List[Dict[str, Any]]:
    """Direct PG read — used where the nidp data lake is colocated with the app.
    DISTINCT ON dedupes the (symbol, as_of_date, source) PK so each stock counts
    once, preferring the row that actually has a market cap."""
    sql = """
        SELECT DISTINCT ON (sfd.symbol)
               sfd.symbol,
               sm.security_name AS company_name,
               sfd.sector,
               sfd.industry,
               sfd.return_252d_pct,
               sfd.market_cap_cr,
               sfd.pe_ttm,
               sfd.pb,
               sfd.roe_pct
          FROM nidp.stock_features_daily sfd
          LEFT JOIN ref.security_master sm
                 ON sm.entity_type = 'EQUITY' AND sm.symbol = sfd.symbol
         WHERE sfd.as_of_date = (SELECT max(as_of_date) FROM nidp.stock_features_daily)
           AND sfd.sector IS NOT NULL
         ORDER BY sfd.symbol, sfd.market_cap_cr DESC NULLS LAST
    """
    try:
        async with pool.acquire() as conn:
            as_of = await conn.fetchval("SELECT max(as_of_date) FROM nidp.stock_features_daily")
            rows = await conn.fetch(sql)
    except Exception as e:  # noqa: BLE001
        logger.warning("sector_analysis fetch_stocks_pg failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "symbol":        r["symbol"],
            "name":          r["company_name"] or r["symbol"],
            "sector":        r["sector"],
            "industry":      r["industry"],
            "return_1y_pct": _f(r["return_252d_pct"]),
            "market_cap_cr": _f(r["market_cap_cr"]),
            "pe_ttm":        _f(r["pe_ttm"]),
            "pb":            _f(r["pb"]),
            "roe_pct":       _f(r["roe_pct"]),
            "_as_of":        as_of,
        })
    return out


async def _fetch_index_eod(pool, names: List[str]) -> Dict[str, Dict[str, Any]]:
    """Latest close + 1d %change + P/E for the given NSE indices."""
    if not names:
        return {}
    sql = """
        SELECT DISTINCT ON (index_name)
               index_name, pct_change, pe_ratio, close_price, as_of_date
          FROM nidp.index_eod
         WHERE index_name = ANY($1)
         ORDER BY index_name, as_of_date DESC
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, names)
    except Exception as e:  # noqa: BLE001
        logger.warning("sector_analysis fetch_index_eod failed: %s", e)
        return {}
    return {
        r["index_name"]: {
            "pct_change": _f(r["pct_change"]),
            "pe_ratio":   _f(r["pe_ratio"]),
            "close":      _f(r["close_price"]),
        }
        for r in rows
    }


def _headline(name: str, m: Dict[str, Any]) -> str:
    n = m.get("stock_count") or 0
    adv, dec = m.get("advancing") or 0, m.get("declining") or 0
    breadth = "advancing broadly" if adv >= dec * 1.2 else "under pressure" if dec >= adv * 1.2 else "mixed"
    pe = m.get("median_pe")
    val = f", ~{pe:.1f}× median P/E" if pe else ""
    return f"{name}: {n} stocks {breadth} over the past year ({adv} up / {dec} down){val}."


def _metric_bullets(m: Dict[str, Any], benchmark: str) -> List[str]:
    out: List[str] = []
    if m.get("market_cap_cr") is not None:
        out.append(f"Aggregate market cap ₹{m['market_cap_cr']:,.0f} Cr across {m.get('stock_count', 0)} stocks")
    if m.get("avg_return_1y") is not None:
        out.append(f"Avg 1-year return {'+' if m['avg_return_1y'] >= 0 else ''}{m['avg_return_1y']:.2f}%")
    if m.get("median_pe") is not None:
        out.append(f"Median P/E {m['median_pe']:.1f}× (median ROE {m['median_roe']:.1f}%)"
                   if m.get("median_roe") is not None else f"Median P/E {m['median_pe']:.1f}×")
    if m.get("index_pct_change") is not None:
        out.append(f"{benchmark} {'+' if m['index_pct_change'] >= 0 else ''}{m['index_pct_change']:.2f}% today"
                   + (f" at {m['index_pe']:.1f}× P/E" if m.get("index_pe") is not None else ""))
    return out


def _build_profile_doc(meta: Dict[str, str], stocks: List[Dict[str, Any]],
                       index_eod: Dict[str, Dict[str, Any]],
                       as_of: Any, generated_at: str) -> Optional[Dict[str, Any]]:
    """Assemble the grounded (no-LLM) doc for one profile. None if too few stocks."""
    members = [s for s in stocks if _classify(s["sector"], s["industry"]) == meta["profile"]]
    if len(members) < MIN_STOCKS:
        return None

    # The screener exposes a 1-year return (return_252d_pct) — breadth and the
    # headline move are measured on that.
    adv = sum(1 for s in members if (s["return_1y_pct"] or 0) > 0)
    dec = sum(1 for s in members if (s["return_1y_pct"] or 0) < 0)
    mcap = sum(s["market_cap_cr"] for s in members if s["market_cap_cr"] is not None)
    pes = [s["pe_ttm"] for s in members if s["pe_ttm"] is not None and 0 < s["pe_ttm"] <= 200]
    idx = index_eod.get(meta["benchmark"], {})

    metrics = {
        "stock_count":      len(members),
        "advancing":        adv,
        "declining":        dec,
        "market_cap_cr":    round(mcap, 2) if mcap else None,
        "median_pe":        _median(pes),
        "median_pb":        _median([s["pb"] for s in members]),
        "median_roe":       _median([s["roe_pct"] for s in members]),
        "avg_return_1y":    _mean([s["return_1y_pct"] for s in members]),
        "index_pct_change": idx.get("pct_change"),
        "index_pe":         idx.get("pe_ratio"),
    }

    top = sorted(
        [s for s in members if s["market_cap_cr"] is not None],
        key=lambda s: s["market_cap_cr"], reverse=True,
    )[:TOP_COMPANIES]
    top_companies = [{
        "symbol":        s["symbol"],
        "name":          s["name"],
        "market_cap_cr": s["market_cap_cr"],
        "return_1y_pct": s["return_1y_pct"],
        "pe_ttm":        s["pe_ttm"],
    } for s in top]

    return {
        "slug":            meta["slug"],
        "profile":         meta["profile"],
        "name":            meta["name"],
        "icon":            meta["icon"],
        "blurb":           meta["blurb"],
        "benchmark_index": meta["benchmark"],
        "as_of_date":      (as_of.isoformat() if hasattr(as_of, "isoformat") else as_of) or None,
        "generated_at":    generated_at,
        "metrics":         metrics,
        "top_companies":   top_companies,
        "headline":        _headline(meta["name"], metrics),
        "metric_bullets":  _metric_bullets(metrics, meta["benchmark"]),
        "commentary_md":   None,
        "commentary_disclaimer": COMMENTARY_DISCLAIMER,
        "model":           None,
        "sources":         ["NIDP", "NSE"],
    }


async def diagnose(pool) -> Dict[str, Any]:
    """Probe the data state behind an empty grid — surfaces WHY (missing table
    vs empty/NULL-sector data) without needing DB/log access. Each probe is
    isolated so one failure (e.g. a missing table) still reports the rest."""
    out: Dict[str, Any] = {}

    # DaaS is the primary path (Cloud Run has no local nidp.* rows) — probe it first.
    try:
        from services.copilot_tools import daas_client
        out["daas_configured"] = daas_client.is_configured()
        if out["daas_configured"]:
            sample = await daas_client.get_stock_screener(limit=5)
            out["daas_screener_rows"] = len(sample)
            if sample:
                out["daas_sample_sectors"] = [r.get("sector") for r in sample]
            # The actual mapped count my fetch produces (limit=600, after the
            # non-null-sector filter) — the decisive number if the grid is empty.
            mapped = await _fetch_stocks_daas()
            out["daas_fetch_mapped"] = len(mapped)
    except Exception as e:  # noqa: BLE001
        out["daas_error"] = str(e)[:200]

    async def _val(key: str, sql: str) -> None:
        try:
            async with pool.acquire() as conn:
                out[key] = await conn.fetchval(sql)
        except Exception as e:  # noqa: BLE001
            out[key + "_error"] = str(e)[:200]

    await _val("sfd_table",            "SELECT to_regclass('nidp.stock_features_daily')::text")
    await _val("ref_security_master",  "SELECT to_regclass('ref.security_master')::text")
    await _val("sector_master_table",  "SELECT to_regclass('nidp.sector_master')::text")
    await _val("sfd_latest",           "SELECT max(as_of_date)::text FROM nidp.stock_features_daily")
    await _val("sfd_rows_latest",
               "SELECT count(*) FROM nidp.stock_features_daily "
               "WHERE as_of_date=(SELECT max(as_of_date) FROM nidp.stock_features_daily)")
    await _val("sfd_with_sector",
               "SELECT count(*) FROM nidp.stock_features_daily "
               "WHERE as_of_date=(SELECT max(as_of_date) FROM nidp.stock_features_daily) AND sector IS NOT NULL")
    await _val("sfd_with_mcap",
               "SELECT count(*) FROM nidp.stock_features_daily "
               "WHERE as_of_date=(SELECT max(as_of_date) FROM nidp.stock_features_daily) AND market_cap_cr IS NOT NULL")
    await _val("sector_master_rows",   "SELECT count(*) FROM nidp.sector_master")
    return out


async def build_all_metrics(pool, generated_at: str) -> List[Dict[str, Any]]:
    """Grounded metric docs for every profile that has enough stocks. No LLM."""
    stocks = await _fetch_stocks(pool)
    if not stocks:
        return []
    as_of = stocks[0].get("_as_of")
    index_eod = await _fetch_index_eod(pool, [p["benchmark"] for p in PROFILES])
    docs: List[Dict[str, Any]] = []
    for meta in PROFILES:
        doc = _build_profile_doc(meta, stocks, index_eod, as_of, generated_at)
        if doc:
            docs.append(doc)
    return docs


# ── LLM commentary ────────────────────────────────────────────────────────────
_SYSTEM = (
    "You are an equity-market analyst writing a short sector commentary for "
    "Indian retail investors on the Nivesh app. You are given VERIFIED "
    "quantitative facts about one sector from the Nivesh data platform. Write "
    "exactly three short markdown sections with these headings: '### What's "
    "driving it', '### Key risks', '### Outlook'. Rules: (1) Ground every "
    "quantitative statement in the supplied facts — never invent numbers, "
    "price targets, or company-specific guidance. (2) For qualitative context "
    "(structural drivers, policy, demand trends) you may use general market "
    "knowledge, but stay measured and avoid specific unverifiable claims or "
    "dated events. (3) Be concise: ~180-230 words total, 2-3 sentences per "
    "section. (4) No preamble, no disclaimer (the app adds one), no headline — "
    "start directly with the first heading."
)


def _facts_block(doc: Dict[str, Any]) -> str:
    m = doc["metrics"]
    lines = [
        f"Sector: {doc['name']} (benchmark: {doc['benchmark_index']})",
        f"As of: {doc.get('as_of_date')}",
        f"Stocks covered: {m.get('stock_count')} ({m.get('advancing')} advancing, {m.get('declining')} declining today)",
        f"Aggregate market cap: ₹{m['market_cap_cr']:,.0f} Cr" if m.get("market_cap_cr") else "Aggregate market cap: n/a",
        f"Median P/E: {m.get('median_pe')}, median P/B: {m.get('median_pb')}, median ROE: {m.get('median_roe')}%",
        f"Avg 1-year return: {m.get('avg_return_1y')}%",
        f"{doc['benchmark_index']} index: {m.get('index_pct_change')}% today, P/E {m.get('index_pe')}",
    ]
    top = ", ".join(f"{c['name']} (₹{c['market_cap_cr']:,.0f} Cr)" for c in doc.get("top_companies", [])[:5]
                    if c.get("market_cap_cr"))
    if top:
        lines.append(f"Largest companies by market cap: {top}")
    return "\n".join(lines)


async def generate_commentary(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Fill commentary_md on the doc via Claude, grounded in doc['metrics'].

    On any failure (no key, API error, refusal) leaves commentary_md = None and
    sets commentary_error so the caller can surface an honest 'unavailable'
    state rather than a fabricated narrative.
    """
    if not is_llm_configured():
        doc["commentary_md"] = None
        doc["commentary_error"] = "llm_not_configured"
        return doc
    model = _model()
    try:
        client = _get_client()
        resp = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Write the sector commentary for the following sector.\n\n"
                    f"VERIFIED FACTS:\n{_facts_block(doc)}"
                ),
            }],
        )
        if resp.stop_reason == "refusal":
            logger.warning("sector_analysis commentary refused for %s", doc["slug"])
            doc["commentary_md"] = None
            doc["commentary_error"] = "refusal"
            return doc
        text = next((b.text for b in resp.content if b.type == "text"), "").strip()
        doc["commentary_md"] = text or None
        doc["commentary_error"] = None if text else "empty"
        doc["model"] = model
    except Exception as e:  # noqa: BLE001
        logger.warning("sector_analysis commentary failed for %s: %s", doc["slug"], e)
        doc["commentary_md"] = None
        doc["commentary_error"] = "api_error"
    return doc
