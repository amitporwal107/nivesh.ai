"""V3 Engine Phase 2 — integration layer between V3 scoring and the
existing V2.5 rule engine (`action_plan_manager._apply_action_rules`).

Responsibilities:
  1. Batch-load V3 primitives for every mf_investment in a plan.
  2. Compute all 5 composite scores per fund.
  3. Run the 4 guardrails (from `v3_scoring.check_guardrails`) per holding.
  4. Expose helpers to compute `switch_score` for a Regular/Direct pair.

Everything is additive — rules that can't find a V3 score for a fund
fall back to legacy heuristics, so this integration is safe to enable
incrementally. Call `enrich_candidates_with_v3(...)` once at the top of
`_apply_action_rules` and then read the `v3_scores_by_id` dict it returns.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import pg_client, v3_scoring

logger = logging.getLogger(__name__)


async def _resolve_name_to_instrument_id(scheme_name: str) -> Optional[str]:
    """Fuzzy-match a scheme name against instrument_master. Returns UUID str
    or None. Uses pg_trgm similarity — same approach the daily cron uses.
    Silently returns None if PG is unreachable (e.g. during unit tests)."""
    if not scheme_name:
        return None
    try:
        pool = await pg_client.get_pool()
    except Exception:  # noqa: BLE001
        return None
    if pool is None:
        return None
    clean = " ".join(scheme_name.replace(",", " ").replace("-", " ").split())
    try:
        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                """
                SELECT instrument_id::text, similarity(instrument_name, $1) AS sim
                FROM instrument_master
                WHERE instrument_type = 'MUTUAL_FUND'
                  AND similarity(instrument_name, $1) > 0.45
                ORDER BY sim DESC LIMIT 1
                """,
                clean,
            )
    except Exception:  # noqa: BLE001
        return None
    return r["instrument_id"] if r else None


async def _load_v3_primitives_bulk(instrument_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """One-shot PG read: pull every V3 input column for the given funds.

    Returns {instrument_id (str): {col → value}}. Skips non-UUID inputs so
    test fixtures with synthetic IDs don't poison the PG query.
    """
    # Defensive UUID filter — drops test-only IDs like "pg-3" etc.
    import re
    UUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I,
    )
    real_ids = [i for i in instrument_ids if isinstance(i, str) and UUID_RE.match(i)]
    if not real_ids:
        return {}
    pool = await pg_client.get_pool()
    if pool is None:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              mfmd.instrument_id::text AS instrument_id,
              mfmd.category, mfmd.sub_category,
              mfmd.aum_cr::float, mfmd.fund_age_years::float,
              mfmd.expense_ratio::float, mfmd.expense_ratio_direct::float,
              mfmd.expense_ratio_regular::float, mfmd.expense_trend_delta::float,
              mfmd.manager_tenure_years::float,
              mfmd.turnover_ratio::float, mfmd.top10_concentration_pct::float,
              mfmd.category_avg_1y::float, mfmd.category_avg_3y::float, mfmd.category_avg_5y::float,
              mfmd.max_drawdown_pct::float, mfmd.consistency_score::float,
              mfmd.downside_capture_pct::float, mfmd.aum_trend_score::float,
              mfmd.credit_quality_score::float, mfmd.duration_risk_score::float,
              mfmd.ytm::float, mfmd.modified_duration::float,
              mfmd.investment_style, mfmd.moneycontrol_imid,
              mfpr.ret_1y::float, mfpr.ret_3y::float, mfpr.ret_5y::float,
              mfpr.sharpe::float, mfpr.sortino::float
            FROM mutual_fund_metadata mfmd
            LEFT JOIN LATERAL (
              SELECT * FROM mutual_fund_performance_ratios
              WHERE instrument_id = mfmd.instrument_id
              ORDER BY ratios_date DESC LIMIT 1
            ) mfpr ON TRUE
            WHERE mfmd.instrument_id = ANY($1::uuid[])
            """,
            real_ids,
        )
    return {r["instrument_id"]: dict(r) for r in rows}


def _holding_age_months(holding: Optional[Dict[str, Any]]) -> Optional[float]:
    if not holding:
        return None
    buy = holding.get("buy_date") or holding.get("purchase_date")
    if not buy:
        return None
    try:
        d = datetime.fromisoformat(str(buy).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - d.replace(tzinfo=timezone.utc)).days / 30.44
    except (ValueError, AttributeError):
        return None


async def enrich_candidates_with_v3(
    mf_investments: List[Dict[str, Any]],
    exit_candidates: List[Dict[str, Any]],
    mf_holdings: List[Dict[str, Any]],
    portfolio_intelligence: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Return {key: V3 bundle} where `key` is the holding's instrument_id if
    available, else its normalised scheme_name. Callers pass either form to
    look up scores.

    Funds missing from PG are simply absent — callers degrade to legacy.
    """
    # Collect instrument_ids plus names for fuzzy fallback
    iids: set[str] = set()
    unresolved_by_name: Dict[str, str] = {}  # scheme_name → mf_investment reference
    for m in mf_investments:
        if m.get("instrument_id"):
            iids.add(m["instrument_id"])
        elif m.get("scheme_name"):
            unresolved_by_name[m["scheme_name"]] = m

    # Resolve unknown schemes via pg_trgm
    name_to_iid: Dict[str, str] = {}
    for name in unresolved_by_name:
        resolved = await _resolve_name_to_instrument_id(name)
        if resolved:
            name_to_iid[name] = resolved
            iids.add(resolved)

    logger.info(
        f"[V3 enrich] {len(iids)} instrument_ids "
        f"({len(name_to_iid)} resolved via name-match)"
    )
    if not iids:
        return {}

    primitives_by_id = await _load_v3_primitives_bulk(list(iids))
    out: Dict[str, Dict[str, Any]] = {}

    # Overlap lookup by instrument_id (from intelligence) + by fund name (from pairwise)
    overlap_by_id: Dict[str, float] = {}
    for p in portfolio_intelligence.get("pairwise_overlap") or []:
        op = float(p.get("overlap_pct") or 0)
        for side in ("a", "b"):
            k = p.get(side)
            if k:
                overlap_by_id[k] = max(overlap_by_id.get(k, 0), op)

    from services.action_plan_manager import _normalize_fund_name, _fuzzy_match_holding
    cand_by_id = {
        c.get("instrument_id"): c for c in exit_candidates if c.get("instrument_id")
    }
    cand_by_name = {
        _normalize_fund_name(c.get("scheme_name", "")): c
        for c in exit_candidates if c.get("scheme_name")
    }

    for mf in mf_investments:
        iid = mf.get("instrument_id") or name_to_iid.get(mf.get("scheme_name", ""))
        if not iid or iid not in primitives_by_id:
            continue
        f = primitives_by_id[iid]
        quality = v3_scoring.compute_quality_score(f)
        health = v3_scoring.compute_health_score(f)

        # Match exit_candidate by iid or scheme_name
        cand = cand_by_id.get(iid) or cand_by_name.get(
            _normalize_fund_name(mf.get("scheme_name", "")), {}
        )
        ti = cand.get("tax_impact") or {}
        tax_liability = float(ti.get("tax_liability") or 0)
        tax_benefit_rs = float(cand.get("annual_cost_saving_rs") or 0)
        overlap_pct = overlap_by_id.get(iid) or overlap_by_id.get(mf.get("scheme_name", ""))

        ctx_exit = {
            "overlap_pct": overlap_pct,
            "tax_liability_rs": tax_liability or None,
            "tax_benefit_rs": tax_benefit_rs or None,
            "quality_score": quality["score"],
            "portfolio_fit_score": None,
        }
        exit_s = v3_scoring.compute_exit_score(f, ctx_exit)
        ctx_add = {
            "gap_fit_0_10": None,
            "avg_overlap_pct_with_portfolio": overlap_pct,
            "quality_score": quality["score"],
            "need_score_0_10": None,
        }
        add_s = v3_scoring.compute_add_score(f, ctx_add)

        # Guardrails per holding
        h = _fuzzy_match_holding(mf.get("scheme_name", ""), mf_holdings)
        age_months = _holding_age_months(h) if h else None
        guardrail = v3_scoring.check_guardrails(
            quality_score=quality["score"], health_score=health["score"],
            overlap_pct=overlap_pct,
            tax_liability_rs=tax_liability or None,
            tax_benefit_rs=tax_benefit_rs or None,
            holding_age_months=age_months, confidence_score=None,
        )

        bundle = {
            "quality_score": quality["score"],
            "health_score": health["score"],
            "exit_score": exit_s["score"],
            "add_score": add_s["score"],
            "category": quality.get("category"),
            "quality_missing": quality["missing_primitives"],
            "health_missing": health["missing_primitives"],
            "quality_components": quality["components"],
            "health_components": health["components"],
            "guardrail_blocked": guardrail.blocked,
            "guardrail_reasons": guardrail.reasons,
            "v3_primitives": {k: f.get(k) for k in (
                "aum_cr", "fund_age_years", "expense_ratio_direct", "manager_tenure_years",
                "max_drawdown_pct", "consistency_score", "downside_capture_pct",
                "aum_trend_score", "turnover_ratio", "top10_concentration_pct",
                # Debt-specific (Moneycontrol-sourced) — surface so the insights
                # UI can display credit/duration profile for bond funds.
                "credit_quality_score", "duration_risk_score", "ytm",
                "modified_duration", "investment_style", "moneycontrol_imid",
            )},
        }
        # Dual-index: by iid AND by normalised scheme_name (for lookup when
        # action carries name but no iid)
        out[iid] = bundle
        name_key = _normalize_fund_name(mf.get("scheme_name", ""))
        if name_key:
            out[name_key] = bundle

    logger.info(
        f"[V3 enrich] Scored {len(primitives_by_id)} funds; "
        f"keyed under {len(out)} lookup entries (iid + name)"
    )
    return out


def compute_reg_to_direct_switch_score(
    regular_holding: Dict[str, Any],
    cost_leak_rs: float,
    v3_scores_by_id: Dict[str, Dict[str, Any]],
    mf_investments: List[Dict[str, Any]],
) -> float:
    """V3 Switch formula for Regular → Direct:

        Quality_new − Quality_old ≈ 0 (same strategy, same manager)
        Overlap_reduction          = 0 (same holdings)
        Cost_saving                = cost_leak_rs / year
        Tax_cost                   = estimated STCG/LTCG on exit

    In the Regular → Direct case the quality + overlap deltas are zero by
    construction, so `switch_score = cost_saving − tax_cost`. We approximate
    tax as a small % of the holding value when `buy_date` is missing.
    """
    # Find matching mf_investment to pull tax estimate
    from services.action_plan_manager import _normalize_fund_name
    norm_reg = _normalize_fund_name(regular_holding.get("name", ""))
    tax = 0.0
    for m in mf_investments:
        if _normalize_fund_name(m.get("scheme_name", "")) == norm_reg:
            ti = (m.get("tax_impact") or {}) if isinstance(m.get("tax_impact"), dict) else {}
            tax = float(ti.get("tax_liability") or 0)
            break

    result = v3_scoring.compute_switch_score(
        quality_new=None, quality_old=None,
        overlap_reduction_pct=0,
        cost_saving_rs_per_yr=cost_leak_rs,
        tax_cost_rs=tax,
    )
    return float(result["score"] or 0.0)


def v3_exit_score_or_legacy(
    instrument_id: Optional[str],
    legacy_score: float,
    v3_scores_by_id: Dict[str, Dict[str, Any]],
    scheme_name: Optional[str] = None,
) -> float:
    """Ranking helper: prefer V3 exit_score (0-100) when available (scaled to
    0-10 for compatibility with legacy heuristic), else fallback to legacy.

    Looks up by instrument_id first, then by normalised scheme_name.
    """
    v3 = None
    if instrument_id and instrument_id in v3_scores_by_id:
        v3 = v3_scores_by_id[instrument_id]
    elif scheme_name:
        from services.action_plan_manager import _normalize_fund_name
        key = _normalize_fund_name(scheme_name)
        if key in v3_scores_by_id:
            v3 = v3_scores_by_id[key]
    if v3 and v3.get("exit_score") is not None:
        return float(v3["exit_score"]) / 10.0
    return legacy_score


def lookup_v3(
    instrument_id: Optional[str],
    scheme_name: Optional[str],
    v3_scores_by_id: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Dual-key V3 bundle lookup (iid OR scheme_name)."""
    if instrument_id and instrument_id in v3_scores_by_id:
        return v3_scores_by_id[instrument_id]
    if scheme_name:
        from services.action_plan_manager import _normalize_fund_name
        key = _normalize_fund_name(scheme_name)
        return v3_scores_by_id.get(key)
    return None


ENGINE_VERSION = "v3.0-phase2"
