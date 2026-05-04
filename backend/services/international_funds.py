"""International Fund Recommendation Engine.

End-to-end pipeline that answers two questions for a user:

  1. "How much of my portfolio should be in international funds?"
  2. "Which international funds should I pick?"

Pieces:
  * `INTERNATIONAL_FUND_SEED`   — curated list of international FoFs we
                                   actively track (US / Global / EM / Tech).
  * `classify_international()`  — pure function: scheme_name + sub_category
                                   → bucket ("US"|"Global"|"EM"|"Tech"|None).
  * `refresh_international_funds()` — scrape primitives via the existing
                                   groww_client and persist to the mongo
                                   cache `international_funds_cache`.
  * `compute_target_international_pct()` — returns recommended % of
                                   portfolio in international funds, derived
                                   from risk profile + horizon + age.
  * `recommend_international_funds()` — produces the Core/Selective/
                                   Tactical/Avoid bands for a given user,
                                   with portfolio-aware overrides
                                   (e.g. block Nasdaq when IT exposure
                                   already > 25%).

All allocation outputs are amounts AND percentages, never just %.
The recommender NEVER fabricates fund metadata — if the cache hasn't been
refreshed, the response includes a `_stale: true` flag.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Seed list of international FoFs we actively track ──────────────────
# Each entry: (display_name, groww_slug, bucket_hint)
# bucket_hint is the *expected* classification — used as a tiebreaker when
# Groww's sub_category is generic ("Fund of Funds Overseas").
INTERNATIONAL_FUND_SEED: List[Dict[str, str]] = [
    # US-focused
    {"name": "Franklin India Feeder Franklin US Opportunities Fund",
     "slug": "franklin-india-feeder-franklin-us-opportunities-fund",
     "bucket": "US"},
    {"name": "ICICI Prudential US Bluechip Equity Fund",
     "slug": "icici-prudential-us-bluechip-equity-fund",
     "bucket": "US"},
    {"name": "Motilal Oswal Nasdaq 100 Fund of Fund",
     "slug": "motilal-oswal-nasdaq-100-fund-of-fund",
     "bucket": "Tech"},
    {"name": "Edelweiss US Technology Equity Fund of Fund",
     "slug": "edelweiss-us-technology-equity-fund-of-fund",
     "bucket": "Tech"},
    {"name": "Mirae Asset NYSE FANG Plus ETF Fund of Fund",
     "slug": "mirae-asset-nyse-fang-plus-etf-fund-of-fund",
     "bucket": "Tech"},
    # Global / Developed
    {"name": "Axis Global Equity Alpha Fund of Fund",
     "slug": "axis-global-equity-alpha-fund-of-fund",
     "bucket": "Global"},
    {"name": "HDFC Developed World Indexes Fund of Funds",
     "slug": "hdfc-developed-world-indexes-fund-of-funds",
     "bucket": "Global"},
    {"name": "Invesco Global Equity Income Fund of Fund",
     "slug": "invesco-global-equity-income-fund-of-fund",
     "bucket": "Global"},
    # Emerging Markets
    {"name": "Edelweiss Emerging Markets Opportunities Equity Offshore Fund",
     "slug": "edelweiss-emerging-markets-opportunities-equity-offshore-fund",
     "bucket": "EM"},
    {"name": "Kotak Global Emerging Market Fund",
     "slug": "kotak-global-emerging-market-fund",
     "bucket": "EM"},
    {"name": "Aditya Birla Sun Life Global Emerging Opportunities Fund",
     "slug": "aditya-birla-sun-life-global-emerging-opportunities-fund",
     "bucket": "EM"},
]


# ── Classifier ────────────────────────────────────────────────────────
_BUCKET_KEYWORDS: Dict[str, List[str]] = {
    "Tech":   ["nasdaq", "technology", "fang", "ai ", "innovation"],
    "US":     ["us bluechip", " us ", "u.s.", "america", "s&p 500", "us opportun", "us equity"],
    "EM":     ["emerging market", "emerging markets", "asean", "china", "asia ", "brazil"],
    "Global": ["global", "developed world", "world equity", "world index", "international"],
}
# Order matters — Tech wins over US (Nasdaq is both); US wins over Global.
_BUCKET_PRIORITY = ["Tech", "US", "EM", "Global"]


def classify_international(
    scheme_name: Optional[str], sub_category: Optional[str] = None,
) -> Optional[str]:
    """Return one of {US, Global, EM, Tech} or None.

    Heuristic-only — drives bucketing for funds we can't pre-curate. The
    sub_category hint from Groww is rarely specific (it's usually just
    "Fund of Funds Overseas"), so the scheme name is the primary signal.
    """
    if not scheme_name:
        return None
    text = f"{scheme_name} {sub_category or ''}".lower()
    # Quick reject: must look international
    if not any(k in text for k in ("us ", "u.s", "global", "world",
                                    "nasdaq", "fang", "emerging",
                                    "international", "overseas",
                                    "developed", "asia", "china",
                                    "brazil", "america", "feeder")):
        return None
    for bucket in _BUCKET_PRIORITY:
        kws = _BUCKET_KEYWORDS[bucket]
        if any(kw in text for kw in kws):
            return bucket
    # Anything left that mentioned overseas/feeder but didn't keyword-match
    # falls back to Global as the safest default.
    return "Global"


# ── Scraper refresh ────────────────────────────────────────────────────
async def refresh_international_funds(
    *, force: bool = False, ttl_hours: int = 24,
) -> Dict[str, Any]:
    """Refresh the local cache of international FoF primitives.

    Walks `INTERNATIONAL_FUND_SEED`, calls the existing groww_client to
    scrape primitives (scores, expense ratio, returns, AUM, holdings,
    sectors), and upserts into `db.international_funds_cache`. Skips
    funds whose cached row is fresher than `ttl_hours` unless force=True.

    Returns a summary {refreshed, skipped, failed, errors[]}.
    """
    from deps import db
    from services import groww_client as gc

    now = datetime.now(timezone.utc)
    refreshed = skipped = failed = 0
    errors: List[Dict[str, str]] = []

    for seed in INTERNATIONAL_FUND_SEED:
        slug = seed["slug"]
        try:
            # Skip if recent
            if not force:
                existing = await db.international_funds_cache.find_one(
                    {"slug": slug}, {"fetched_at": 1, "_id": 0},
                )
                if existing and existing.get("fetched_at"):
                    try:
                        prev = datetime.fromisoformat(
                            existing["fetched_at"].replace("Z", "+00:00"),
                        )
                        if (now - prev).total_seconds() < ttl_hours * 3600:
                            skipped += 1
                            continue
                    except (TypeError, ValueError):
                        pass

            parsed = await gc.fetch_fund_with_sibling(seed["name"], explicit_slug=slug)
            if not parsed:
                failed += 1
                errors.append({"slug": slug, "error": "fetch returned None"})
                continue

            meta = parsed.get("metadata") or {}
            ratios = parsed.get("ratios") or {}
            v3 = parsed.get("v3_primitives") or {}

            # Re-classify using the freshly scraped sub_category — falls
            # back to seed bucket when classifier returns None.
            bucket = classify_international(
                meta.get("scheme_name") or seed["name"],
                meta.get("sub_category"),
            ) or seed.get("bucket")

            doc = {
                "slug": slug,
                "scheme_name": meta.get("scheme_name") or seed["name"],
                "isin": meta.get("isin"),
                "amc": meta.get("amc") or meta.get("fund_house"),
                "category": meta.get("category"),
                "sub_category": meta.get("sub_category"),
                "bucket": bucket,                  # US | Global | EM | Tech
                "plan_type": meta.get("plan_type"),
                # Cost & size
                "expense_ratio_regular": meta.get("expense_ratio_regular"),
                "expense_ratio_direct": meta.get("expense_ratio_direct"),
                "expense_ratio": meta.get("expense_ratio"),
                "aum_cr": meta.get("aum_cr"),
                "min_sip": meta.get("min_sip"),
                "launch_date": meta.get("launch_date"),
                # Returns
                "ret_1y": ratios.get("ret_1y"),
                "ret_3y": ratios.get("ret_3y"),
                "ret_5y": ratios.get("ret_5y"),
                "ret_10y": ratios.get("ret_10y"),
                # Risk
                "alpha": ratios.get("alpha"),
                "beta": ratios.get("beta"),
                "sharpe": ratios.get("sharpe"),
                "sortino": ratios.get("sortino"),
                "std_dev": ratios.get("std_dev"),
                "risk_label": ratios.get("risk_label"),
                # Composition
                "holdings_top10": (parsed.get("holdings") or [])[:10],
                "sectors": parsed.get("sectors") or [],
                "split": parsed.get("split") or {},
                # V3 primitives (sibling slugs etc.)
                "v3_primitives": v3,
                # Lineage
                "fetched_at": now.isoformat(),
                "source": "groww",
            }
            await db.international_funds_cache.update_one(
                {"slug": slug}, {"$set": doc}, upsert=True,
            )
            refreshed += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            errors.append({"slug": slug, "error": str(e)[:200]})
            logger.warning("international_funds: refresh failed for %s: %s", slug, e)

    return {
        "refreshed": refreshed,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        "total_seed": len(INTERNATIONAL_FUND_SEED),
        "ttl_hours": ttl_hours,
    }


# ── Allocation sizing ──────────────────────────────────────────────────
# Base international % by risk profile. International is volatile and
# has currency overlay risk, so even aggressive caps at 15% — beyond that
# the Indian market's higher growth + currency stability is the better
# core. Conservative gets a small allocation purely for diversification.
_BASE_INTL_PCT_BY_RISK: Dict[str, float] = {
    "conservative": 5.0,
    "moderate":     10.0,
    "aggressive":   15.0,
}


def compute_target_international_pct(
    *, risk_profile: str, horizon_years: Optional[float] = None,
    age: Optional[int] = None,
) -> Dict[str, Any]:
    """Decide what % of the portfolio should be in international funds.

    Drivers (in order of weight):
      1. Risk profile — base allocation.
      2. Horizon — long-horizon holders absorb USD/INR volatility better;
         <3y is treated as cash-like, no international exposure.
      3. Age — older investors are pushed toward the conservative end of
         their band (volatility hurts more close to drawdown).

    Returns {pct, band, rationale[]} so the UI can explain the number.
    """
    risk = (risk_profile or "moderate").strip().lower()
    if risk not in _BASE_INTL_PCT_BY_RISK:
        risk = "moderate"
    pct = _BASE_INTL_PCT_BY_RISK[risk]
    rationale = [f"Base {pct:.0f}% for {risk} risk profile."]

    # Short-horizon money should not chase international — tax + currency
    # friction eats the benefit before compounding kicks in.
    if horizon_years is not None and horizon_years < 3:
        return {
            "pct": 0.0,
            "band": "none",
            "rationale": ["Horizon < 3 years — no international exposure recommended (currency + tax friction outweighs benefit)."],
        }

    # Long horizon → modest bump (currency mean-reverts over decades).
    if horizon_years is not None and horizon_years >= 10:
        pct = min(20.0, pct + 2.5)
        rationale.append(f"Long horizon ({horizon_years:.0f}y) → +2.5pp, capped at 20%.")

    # Older investors → trim by 2.5pp (sequence-of-returns risk).
    if age is not None and age >= 55:
        pct = max(0.0, pct - 2.5)
        rationale.append(f"Age {age} → -2.5pp (closer to drawdown phase).")

    band = "small" if pct < 7 else "moderate" if pct < 13 else "large"
    return {
        "pct": round(pct, 1),
        "band": band,
        "rationale": rationale,
    }


# ── Recommender ────────────────────────────────────────────────────────
# Verdict bands (per product spec):
#   Core      — the diversified, low-friction default holding
#   Selective — strong but with a caveat (e.g. valuation, concentration)
#   Tactical  — high-growth/high-risk; small allocation only
#   Avoid     — hard-block reason (poor scores OR portfolio overlap)
_BAND_LABELS = {
    "core":      "Core Allocation — diversified default",
    "selective": "Selective — strong but watch valuation",
    "tactical":  "Tactical — small slice only (high growth / high risk)",
    "avoid":     "Avoid for now",
}


def _quality_score(fund: Dict[str, Any]) -> float:
    """Composite quality on 0-100 from cached primitives.

    Components:
      • 3y CAGR        (40%)
      • Expense ratio  (20% — lower is better)
      • AUM size       (15% — minimum liquidity)
      • Sharpe ratio   (15%)
      • Alpha          (10%)
    Scaling is intentionally simple — we don't have V3 scoring for FoFs.
    """
    ret_3y = fund.get("ret_3y") or 0
    expense = fund.get("expense_ratio_direct") or fund.get("expense_ratio") or 2.0
    aum = fund.get("aum_cr") or 0
    sharpe = fund.get("sharpe") or 0
    alpha = fund.get("alpha") or 0

    # Normalize each to 0-100
    ret_score = max(0.0, min(100.0, ret_3y * 4.0))             # 25% CAGR → 100
    cost_score = max(0.0, min(100.0, (2.5 - expense) / 2.5 * 100))  # 0% expense → 100
    aum_score = max(0.0, min(100.0, aum / 20.0))                # 2000Cr → 100
    sharpe_score = max(0.0, min(100.0, (sharpe + 0.5) * 50))    # sharpe 1.5 → 100
    alpha_score = max(0.0, min(100.0, (alpha + 5) * 10))        # alpha 5 → 100

    return round(
        0.40 * ret_score + 0.20 * cost_score + 0.15 * aum_score
        + 0.15 * sharpe_score + 0.10 * alpha_score, 1,
    )


def _portfolio_overrides(
    fund: Dict[str, Any], *,
    us_exposure_pct: float, it_concentration_pct: float,
    risk_profile: str,
) -> Optional[str]:
    """Return a hard-block reason for the fund given portfolio context, or None.

    These are the "you already own this risk" rules:
      • Conservative + Tech → block (too volatile)
      • IT concentration > 25% + Tech FoF → block (compounds sector risk)
      • Existing US exposure > 20% + US-bucket → block (already covered)
    """
    bucket = fund.get("bucket")
    if bucket == "Tech":
        if (risk_profile or "").lower() == "conservative":
            return "Tech FoFs are too volatile for a conservative profile."
        if it_concentration_pct > 25:
            return f"Your portfolio already has {it_concentration_pct:.0f}% IT exposure — adding a Tech FoF compounds sector risk."
    if bucket == "US" and us_exposure_pct > 20:
        return f"You already have ~{us_exposure_pct:.0f}% US exposure — additional US FoF adds concentration without diversification."
    return None


def _band_for(quality: float) -> str:
    """Map composite quality → verdict band."""
    if quality >= 70:
        return "core"
    if quality >= 55:
        return "selective"
    if quality >= 40:
        return "tactical"
    return "avoid"


async def _portfolio_context(user_id: str) -> Dict[str, Any]:
    """Pull the portfolio-aware signals the recommender needs.

    Today we compute:
      • us_exposure_pct       — sum of holdings already in US-bucket FoFs
      • it_concentration_pct  — IT sector % from holdings sectors
      • risk_profile          — from user_profiles
      • horizon_years         — longest active goal horizon, fallback 10y
      • age                   — from user_profiles when available
      • portfolio_value_rs    — for the ₹ amount on the recommendation
    """
    from deps import db

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    portfolio_value_rs = 0.0
    us_value_rs = 0.0
    it_value_rs = 0.0
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        v = qty * cp
        portfolio_value_rs += v
        sector = (h.get("sector") or "").lower()
        if "information technology" in sector or sector == "it" or "tech" in sector:
            it_value_rs += v
        # Detect existing international/US exposure on the holding.
        bucket = classify_international(h.get("name"), h.get("category"))
        if bucket in ("US", "Tech"):
            us_value_rs += v

    us_exposure_pct = (us_value_rs / portfolio_value_rs * 100.0) if portfolio_value_rs > 0 else 0.0
    it_concentration_pct = (it_value_rs / portfolio_value_rs * 100.0) if portfolio_value_rs > 0 else 0.0

    profile = await db.user_profiles.find_one(
        {"user_id": user_id}, {"_id": 0, "risk_profile": 1, "age": 1, "dob": 1},
    ) or {}
    risk_profile = ((profile.get("risk_profile") or {}).get("category") or "moderate").lower()
    age = profile.get("age")

    # Goal horizon — longest active goal wins (most generous for international)
    horizon_years: Optional[float] = None
    try:
        from services import pg_client as _pg
        import uuid as _uuid
        pool = await _pg.get_pool()
        if pool is not None:
            try:
                uid = _uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            except Exception:  # noqa: BLE001
                uid = _uuid.uuid5(_uuid.NAMESPACE_DNS, f"nivesh:user:{user_id}")
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT MAX(horizon_years) AS h FROM user_goals "
                    "WHERE user_id = $1 AND COALESCE(status,'') <> 'archived'",
                    uid,
                )
                if row and row["h"] is not None:
                    horizon_years = float(row["h"])
    except Exception as e:  # noqa: BLE001
        logger.debug("recommend_international: horizon lookup skipped: %s", e)

    return {
        "portfolio_value_rs": portfolio_value_rs,
        "us_exposure_pct": round(us_exposure_pct, 2),
        "it_concentration_pct": round(it_concentration_pct, 2),
        "risk_profile": risk_profile,
        "age": age,
        "horizon_years": horizon_years,
    }


async def recommend_international_funds(user_id: str) -> Dict[str, Any]:
    """End-to-end recommendation for one user.

    Pipeline:
      1. Resolve portfolio context (existing US/IT exposure, risk, horizon).
      2. Compute target international % and ₹ amount to deploy.
      3. Pull cached fund metadata, score each, apply portfolio overrides.
      4. Group into Core / Selective / Tactical / Avoid bands.

    The response is deliberately verbose — the UI/copilot consumes the
    `why` and `rationale` fields directly so the user understands not just
    what to do but why.
    """
    from deps import db

    ctx = await _portfolio_context(user_id)
    target = compute_target_international_pct(
        risk_profile=ctx["risk_profile"],
        horizon_years=ctx["horizon_years"],
        age=ctx["age"],
    )
    target_pct = float(target["pct"])
    target_rs = round(ctx["portfolio_value_rs"] * (target_pct / 100.0), 0)
    current_rs = round(ctx["portfolio_value_rs"] * (ctx["us_exposure_pct"] / 100.0), 0)
    gap_rs = max(0.0, target_rs - current_rs)

    # Pull all cached funds. If the cache is empty, mark response as stale
    # and tell the caller to trigger a refresh.
    cached = await db.international_funds_cache.find({}, {"_id": 0}).to_list(200)
    if not cached:
        return {
            "_stale": True,
            "_message": "International fund cache is empty — call POST /portfolio/international-funds/refresh first.",
            "target": target,
            "target_pct": target_pct,
            "target_rs": target_rs,
            "current_pct": ctx["us_exposure_pct"],
            "current_rs": current_rs,
            "gap_rs": gap_rs,
            "portfolio_context": ctx,
            "bands": {"core": [], "selective": [], "tactical": [], "avoid": []},
        }

    bands: Dict[str, List[Dict[str, Any]]] = {
        "core": [], "selective": [], "tactical": [], "avoid": [],
    }
    for f in cached:
        quality = _quality_score(f)
        block_reason = _portfolio_overrides(
            f,
            us_exposure_pct=ctx["us_exposure_pct"],
            it_concentration_pct=ctx["it_concentration_pct"],
            risk_profile=ctx["risk_profile"],
        )
        band = "avoid" if block_reason else _band_for(quality)
        # Build the human-readable why line.
        why_parts = []
        if block_reason:
            why_parts.append(block_reason)
        else:
            if f.get("ret_3y") is not None:
                why_parts.append(f"3y return {f['ret_3y']:.1f}%")
            if f.get("expense_ratio_direct") is not None:
                why_parts.append(f"expense {f['expense_ratio_direct']:.2f}%")
            if f.get("aum_cr"):
                why_parts.append(f"AUM ₹{f['aum_cr']:.0f} Cr")
            if f.get("sharpe") is not None:
                why_parts.append(f"Sharpe {f['sharpe']:.2f}")

        bands[band].append({
            "scheme_name": f.get("scheme_name"),
            "amc": f.get("amc"),
            "bucket": f.get("bucket"),
            "quality_score": quality,
            "ret_1y": f.get("ret_1y"),
            "ret_3y": f.get("ret_3y"),
            "ret_5y": f.get("ret_5y"),
            "expense_ratio_direct": f.get("expense_ratio_direct"),
            "aum_cr": f.get("aum_cr"),
            "min_sip": f.get("min_sip"),
            "sharpe": f.get("sharpe"),
            "alpha": f.get("alpha"),
            "risk_label": f.get("risk_label"),
            "why": " · ".join(why_parts) if why_parts else None,
            "block_reason": block_reason,
            "verdict_label": _BAND_LABELS[band],
        })

    # Sort each band by quality desc; cap "core" to top 2, others to top 3.
    for k in bands:
        bands[k].sort(key=lambda x: x["quality_score"] or 0, reverse=True)
    bands["core"] = bands["core"][:2]
    bands["selective"] = bands["selective"][:3]
    bands["tactical"] = bands["tactical"][:3]
    # Avoid is full list — important to show users why each was blocked.

    # Suggested ₹ split across bands (only if there's a positive gap).
    # 60% to core, 30% selective, 10% tactical — purely a default split.
    split_rs = (
        {
            "core": round(gap_rs * 0.60, 0),
            "selective": round(gap_rs * 0.30, 0),
            "tactical": round(gap_rs * 0.10, 0),
        } if gap_rs > 0 else
        {"core": 0, "selective": 0, "tactical": 0}
    )

    return {
        "target": target,                # {pct, band, rationale[]}
        "target_pct": target_pct,
        "target_rs": target_rs,
        "current_pct": ctx["us_exposure_pct"],
        "current_rs": current_rs,
        "gap_rs": gap_rs,
        "split_rs": split_rs,
        "portfolio_context": ctx,
        "bands": bands,
    }
