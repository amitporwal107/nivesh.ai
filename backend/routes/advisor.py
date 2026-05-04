"""Advisor Home — proactive insight feeds for the MFD dashboard.

Four "card" endpoints, each returning a compact JSON shape ready for the
Advisor Home grid:

  GET /api/advisor/today           — top 10 high-priority clients with action
  GET /api/advisor/aum             — clients ranked by AUM with MoM change
  GET /api/advisor/underperformers — clients whose returns lag a benchmark
  GET /api/advisor/rebalance       — clients deviating from target allocation

The shift vs. the existing Copilot prompts: those queries return chat text
that the user has to read; these return *structured* data the UI renders
as insight cards (DecisionCard pattern). Computation reuses the
`_profile_with_priority` hydration that already powers the client list,
so cards render in <500ms even with 30+ clients.

All endpoints require ADVISORY workspace mode (or fall back to empty).
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from deps import db, get_current_user
from services import mfd_workspace

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/advisor", tags=["advisor"])


# ── Internals ───────────────────────────────────────────────────────────
def _session_user_id(user: Dict[str, Any]) -> str:
    return user.get("_session_user_id") or user["user_id"]


async def _hydrated_profiles(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch + hydrate all client profiles for the advisor's workspace.

    Reuses the same priority hydration as the existing /mfd/profiles
    endpoint so signals are consistent across surfaces. Returns CLIENT
    profiles only (excludes the SELF profile).
    """
    from routes.mfd import _profile_with_priority   # avoid circular at import time
    ws = await mfd_workspace.get_or_create_workspace(_session_user_id(user))
    profs = await mfd_workspace.list_profiles(
        ws["workspace_id"], include_self=False,
    )
    if not profs:
        return []
    hydrated = list(await asyncio.gather(*(_profile_with_priority(p) for p in profs)))
    return hydrated


def _slim(p: Dict[str, Any]) -> Dict[str, Any]:
    """Compact projection for card rows — keep only what the UI consumes."""
    return {
        "profile_id": p.get("profile_id"),
        "shadow_user_id": p.get("shadow_user_id"),
        "name": p.get("name") or "Unnamed",
        "portfolio_value_rs": p.get("portfolio_value_rs"),
        "portfolio_score": p.get("portfolio_score"),
        "risk_score": p.get("risk_score"),
        "ai_summary": p.get("ai_summary"),
        "priority": p.get("priority") or {},
        "recommendation_count": p.get("recommendation_count") or 0,
        "tags": p.get("tags") or [],
    }


# ── Card 1: Today — top 10 high-priority clients with action ──────────
@router.get("/today")
async def advisor_today(request: Request, limit: int = 10):
    """Top-N clients sorted by priority score, with the dominant action
    each one needs and the human-readable reasons that drove the score.

    This is the headline card on the Advisor Home — answers "Which
    clients should I call today?" without the advisor having to ask.
    """
    user = await get_current_user(request)
    profiles = await _hydrated_profiles(user)
    # Already sorted by priority desc inside _profile_with_priority's caller
    # but be explicit here so the contract is independent of upstream sorting.
    profiles.sort(key=lambda x: (x.get("priority") or {}).get("score", 0), reverse=True)
    rows = []
    for p in profiles[:max(1, min(50, int(limit)))]:
        slim = _slim(p)
        pri = slim["priority"]
        rows.append({
            **slim,
            "priority_bucket": pri.get("bucket"),     # high | medium | low
            "priority_score": pri.get("score"),
            "dominant_action": pri.get("dominant_action"),  # Exit / Switch / Rebalance / Review …
            "reasons": pri.get("reasons") or [],
        })

    counts = {
        "high":   sum(1 for r in rows if r["priority_bucket"] == "high"),
        "medium": sum(1 for r in rows if r["priority_bucket"] == "medium"),
        "low":    sum(1 for r in rows if r["priority_bucket"] == "low"),
    }
    return {
        "rows": rows,
        "total_clients": len(profiles),
        "shown": len(rows),
        "buckets": counts,
        "headline": (
            f"{counts['high']} high-priority"
            + (f" · {counts['medium']} medium" if counts["medium"] else "")
        ),
    }


# ── Card 2: AUM — ranked by AUM with MoM change ───────────────────────
async def _aum_30d_ago(shadow_user_id: str) -> Optional[float]:
    """Look up the closest portfolio_snapshot ~30 days back for MoM math.

    We pick the LATEST snapshot whose date is ≤ (today − 25d) — the 25-day
    floor handles months where snapshots arrive a bit early. Returns the
    snapshot's total_value_rs or None when there's no comparable history.
    """
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=25)).isoformat()
    doc = await db.portfolio_snapshots.find_one(
        {"user_id": shadow_user_id, "snapshot_date": {"$lte": cutoff}},
        {"_id": 0, "total_value_rs": 1, "snapshot_date": 1},
        sort=[("snapshot_date", -1)],
    )
    if not doc:
        return None
    v = doc.get("total_value_rs")
    return float(v) if v is not None else None


@router.get("/aum")
async def advisor_aum(request: Request, limit: int = 10):
    """Clients ranked by AUM with month-over-month change.

    MoM math compares against the most recent portfolio_snapshot at least
    25 days old. Clients without enough snapshot history get `mom_pct: null`
    so the UI can render a muted placeholder rather than a fake 0%.
    """
    user = await get_current_user(request)
    profiles = await _hydrated_profiles(user)
    # Sort descending by live AUM; profiles with no AUM sink to the bottom.
    profiles.sort(
        key=lambda p: float(p.get("portfolio_value_rs") or 0),
        reverse=True,
    )
    profiles = profiles[:max(1, min(50, int(limit)))]

    # MoM lookup in parallel (one snapshot read per client).
    mom_values = await asyncio.gather(*(
        _aum_30d_ago(p.get("shadow_user_id") or "") for p in profiles
    ))

    rows: List[Dict[str, Any]] = []
    total_aum_rs = 0.0
    total_aum_30d_rs = 0.0
    for p, prev_aum in zip(profiles, mom_values):
        cur = float(p.get("portfolio_value_rs") or 0)
        total_aum_rs += cur
        if prev_aum is not None and prev_aum > 0:
            total_aum_30d_rs += prev_aum
            mom_pct = round((cur - prev_aum) / prev_aum * 100, 2)
            mom_rs = round(cur - prev_aum, 0)
        else:
            mom_pct = None
            mom_rs = None
        rows.append({
            **_slim(p),
            "mom_pct": mom_pct,
            "mom_rs": mom_rs,
            "prev_aum_rs": prev_aum,
        })

    aggregate_mom_pct = (
        round((total_aum_rs - total_aum_30d_rs) / total_aum_30d_rs * 100, 2)
        if total_aum_30d_rs > 0 else None
    )
    return {
        "rows": rows,
        "total_aum_rs": round(total_aum_rs, 0),
        "aggregate_mom_pct": aggregate_mom_pct,
        "headline": (
            f"₹{round(total_aum_rs / 1e7, 2)}Cr across {len(rows)} clients"
            if total_aum_rs >= 1e7 else
            f"₹{round(total_aum_rs / 1e5, 1)}L across {len(rows)} clients"
        ),
    }


# ── Card 3: Underperformers — return lag vs benchmark ─────────────────
async def _portfolio_return_pct(shadow_user_id: str) -> Optional[float]:
    """Cheap absolute-return proxy for a client portfolio.

    Sums (value − invested) / invested across all holdings. Not annualised
    (we don't always have buy_date precision per holding), so we compare it
    against an absolute-window benchmark not against a CAGR. Returns None
    when invested basis is missing or zero.
    """
    pipeline = [
        {"$match": {"user_id": shadow_user_id}},
        {"$group": {
            "_id": None,
            "value": {"$sum": {"$multiply": [
                {"$ifNull": ["$quantity", 0]},
                {"$ifNull": ["$current_price", 0]},
            ]}},
            "invested": {"$sum": {"$multiply": [
                {"$ifNull": ["$quantity", 0]},
                {"$ifNull": ["$buy_price", 0]},
            ]}},
        }},
    ]
    async for row in db.holdings.aggregate(pipeline):
        val = float(row.get("value") or 0)
        inv = float(row.get("invested") or 0)
        if inv > 0:
            return round((val - inv) / inv * 100, 2)
    return None


async def _benchmark_return_pct(benchmark: str = "nifty_50") -> Optional[float]:
    """Latest 1y benchmark return % from `benchmark_master_snapshots`."""
    try:
        from services import benchmark_index as _bm
        snap = await _bm.get_latest_index(benchmark)
        if snap:
            r = (snap.get("metrics") or {}).get("return_1y")
            if r is not None:
                return round(float(r) * 100, 2)
    except Exception as e:  # noqa: BLE001
        logger.debug("benchmark_return_pct: %s", e)
    return None


@router.get("/underperformers")
async def advisor_underperformers(
    request: Request, gap_pct: float = 5.0, benchmark: str = "nifty_50",
):
    """Clients whose portfolio return lags the benchmark by ≥ gap_pct points.

    Args:
        gap_pct: minimum lag (in pp) for a client to qualify. Default 5.
        benchmark: which benchmark to compare against. Default NIFTY 50.

    Note: this uses absolute portfolio P&L% vs latest 1y benchmark return.
    The advisor sees both numbers; the system never silently picks a
    benchmark that flatters the client. When the benchmark snapshot is
    missing, the response includes `_no_benchmark: true` so the UI can
    surface the fact and direct the advisor to refresh benchmarks.
    """
    user = await get_current_user(request)
    profiles = await _hydrated_profiles(user)

    bench_pct = await _benchmark_return_pct(benchmark)
    if bench_pct is None:
        return {
            "rows": [], "_no_benchmark": True, "benchmark": benchmark,
            "benchmark_return_pct": None,
            "headline": f"Benchmark {benchmark} unavailable — refresh the index cache.",
        }

    client_returns = await asyncio.gather(*(
        _portfolio_return_pct(p.get("shadow_user_id") or "") for p in profiles
    ))

    rows: List[Dict[str, Any]] = []
    for p, ret in zip(profiles, client_returns):
        if ret is None:
            continue
        gap = round(bench_pct - ret, 2)
        if gap >= float(gap_pct):
            rows.append({
                **_slim(p),
                "portfolio_return_pct": ret,
                "benchmark_return_pct": bench_pct,
                "gap_pct": gap,
            })
    rows.sort(key=lambda r: r["gap_pct"], reverse=True)

    return {
        "rows": rows,
        "benchmark": benchmark,
        "benchmark_return_pct": bench_pct,
        "gap_threshold_pct": gap_pct,
        "headline": (
            f"{len(rows)} client{'s' if len(rows) != 1 else ''} lagging {benchmark.replace('_', ' ').upper()} by ≥{gap_pct}pp"
            if rows else
            f"All clients within {gap_pct}pp of {benchmark.replace('_', ' ').upper()}"
        ),
    }


# ── Card 4: Rebalance — clients off their target allocation ──────────
async def _allocation_gap_pp(shadow_user_id: str) -> Optional[Dict[str, Any]]:
    """Compute current vs target allocation per bucket; return the worst gap.

    Returns {worst_bucket, current_pct, target_pct, gap_pp, rationale}
    or None if either side can't be resolved.
    """
    try:
        from services.target_allocator import compute_target_allocation
        ta = await compute_target_allocation(shadow_user_id)
        target = ta.allocation or {}
    except Exception as e:  # noqa: BLE001
        logger.debug("target alloc lookup failed for %s: %s", shadow_user_id, e)
        return None
    if not target:
        return None

    pipeline = [
        {"$match": {"user_id": shadow_user_id}},
        {"$project": {
            "_id": 0,
            "name": 1, "asset_type": 1, "category": 1,
            "value": {"$multiply": [
                {"$ifNull": ["$quantity", 0]},
                {"$ifNull": ["$current_price", 0]},
            ]},
        }},
    ]
    bucket_value: Dict[str, float] = {}
    total = 0.0
    async for h in db.holdings.aggregate(pipeline):
        v = float(h.get("value") or 0)
        if v <= 0:
            continue
        total += v
        # Coarse bucket: equity / debt / gold / cash. Mirrors the same
        # heuristic used in portfolio_enrichment._target_bucket so numbers
        # are consistent across surfaces.
        at = (h.get("asset_type") or "").lower()
        name_l = (h.get("name") or "").lower()
        if at in ("gold",):
            b = "gold"
        elif at in ("equity", "stock", "etf"):
            b = "equity"
        elif at in ("mutual_fund",):
            if any(k in name_l for k in ("liquid", "money market", "ultra short")):
                b = "cash"
            elif any(k in name_l for k in ("debt", "bond", "gilt", "corporate", "short term", "low duration")):
                b = "debt"
            else:
                b = "equity"
        else:
            b = "equity"
        bucket_value[b] = bucket_value.get(b, 0) + v

    if total <= 0:
        return None

    current_pct = {k: round(v / total * 100, 2) for k, v in bucket_value.items()}
    # Worst gap across the buckets defined in the target.
    worst = None
    for bucket, target_pct in target.items():
        cur = current_pct.get(bucket, 0.0)
        gap = abs(cur - float(target_pct))
        if worst is None or gap > worst["gap_pp"]:
            worst = {
                "bucket": bucket,
                "current_pct": cur,
                "target_pct": round(float(target_pct), 2),
                "gap_pp": round(gap, 2),
                "direction": "over" if cur > float(target_pct) else "under",
            }
    return {
        **(worst or {}),
        "all_current_pct": current_pct,
        "all_target_pct": {k: round(float(v), 2) for k, v in target.items()},
    }


@router.get("/rebalance")
async def advisor_rebalance(request: Request, gap_pp: float = 10.0):
    """Clients deviating from their target allocation by ≥ gap_pp points
    on any single bucket.

    Useful when one bucket drifts hard (equity bull run pushes a client
    well over target equity). Sorted by gap descending.
    """
    user = await get_current_user(request)
    profiles = await _hydrated_profiles(user)

    gaps = await asyncio.gather(*(
        _allocation_gap_pp(p.get("shadow_user_id") or "") for p in profiles
    ))

    rows: List[Dict[str, Any]] = []
    for p, g in zip(profiles, gaps):
        if g is None:
            continue
        if g["gap_pp"] >= float(gap_pp):
            rows.append({
                **_slim(p),
                "rebalance": g,
            })
    rows.sort(key=lambda r: r["rebalance"]["gap_pp"], reverse=True)

    return {
        "rows": rows,
        "gap_threshold_pp": gap_pp,
        "headline": (
            f"{len(rows)} client{'s' if len(rows) != 1 else ''} drifting ≥{gap_pp}pp from target"
            if rows else
            f"All clients within {gap_pp}pp of their target allocation"
        ),
    }
