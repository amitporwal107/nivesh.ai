"""Dashboard recommendation orchestrator.

Composes the *deterministic* tool functions used by the LangGraph copilot
agents (portfolio_analyst, mf_analyst, risk_analyst, recommendation) into
a single ordered list of dashboard-renderable insights.

Why this exists:
  The Top3Actions card and Intelligence Feed on V2HomeScreen need real,
  grounded recommendations — not LLM prose. The copilot agents already
  wrap deterministic DAAS-backed tools (services.copilot_tools.*). We call
  those tools directly, skipping the LLM layer, and project their outputs
  into a uniform `Insight` shape the frontend can render.

Insight shape (matches what Top3Actions.jsx expects):
  {
    "id": str,                       # stable id for dedupe / deep-link
    "signal_type": "opportunity|warning|action|risk|info",  # icon family
    "impact": "high|medium|low",     # ranking
    "title": str,                    # ≤ 80 chars headline
    "action": str,                   # one-line recommended next step
    "detail": str,                   # longer explanation, ≤ 240 chars
    "kind": str,                     # subtype: OVERLAP, TAX, COST, ...
    "amount_rs": float | None,       # ₹ impact, if known
    "metadata": {...},               # for deep-link UI (instrument_ids, etc.)
  }

Insights are sorted by impact then by signal_type rank — `Top3Actions`
takes the top 3, the Intelligence Feed shows 4–7. The same array powers
both surfaces so dashboard numbers stay coherent.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from services import portfolio_intelligence
from services.copilot_tools import (
    mf_intelligence as mf_intel,
    portfolio as port_tools,
    recommendation as rec_tools,
    risk as risk_tools,
)
from deps import db

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}
_TYPE_RANK = {"opportunity": 0, "warning": 1, "risk": 2, "action": 3, "info": 4}


def _truncate_name(s: str, max_len: int = 38) -> str:
    """Trim a long fund name for inline display. Mutual fund names
    routinely run 50+ chars (e.g. 'Mirae Asset Large Cap Fund Direct
    Growth'); the cluster detail line lists 3-5 of them so abbreviation
    keeps the row scannable."""
    if not s:
        return ""
    return s if len(s) <= max_len else s[: max_len - 1].rstrip() + "…"


def _fmt_rs(n: Optional[float]) -> str:
    if n is None or n == 0:
        return "—"
    if abs(n) >= 1e7:
        return f"₹{n / 1e7:.2f} Cr"
    if abs(n) >= 1e5:
        return f"₹{n / 1e5:.1f} L"
    if abs(n) >= 1e3:
        return f"₹{n / 1e3:.1f} K"
    return f"₹{round(n):,}"


def _rank(insight: Dict[str, Any]) -> tuple:
    impact = _IMPACT_RANK.get(insight.get("impact", "medium"), 9)
    sig = _TYPE_RANK.get(insight.get("signal_type", "info"), 9)
    return (impact, sig)


# ──────────────────────────────────────────────────────────────────────────
# Projection helpers — turn each tool result into Insight dicts
# ──────────────────────────────────────────────────────────────────────────

def _project_overlap(intelligence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Collapse pairwise-overlap edges into N-way clusters per SEBI category.

    PRE-2026-05-20 bug: every pair emitted its own insight. With 3 Nifty 50
    funds that's 3 separate "Fund A and Fund B overlap N%" rows. The user
    wants ONE cluster row: "Consolidate 3 funds in your Nifty 50 category".

    Algorithm:
      1. Filter pairs to overlap >= 40 (was already here).
      2. Group remaining pairs by (sebi_category, sebi_subcategory) —
         populated by services/portfolio_intelligence._pairwise_overlap.
      3. Run union-find on each group so transitive edges collapse.
      4. Emit one insight per connected component of size >= 2.

    Falls back gracefully when SEBI fields are absent (e.g. old upstream
    data): each pair without a SEBI bucket is emitted as its own row,
    preserving the pre-PR behaviour for that edge.
    """
    pairs = intelligence.get("pairwise_overlap") or []
    out: List[Dict[str, Any]] = []

    # ── Step 1: filter + bucket by SEBI category ─────────────────────
    by_bucket: Dict[tuple, List[Dict[str, Any]]] = {}
    unbucketed: List[Dict[str, Any]] = []
    for p in pairs:
        pct = float(p.get("overlap_pct") or 0)
        if pct < 40:
            continue
        cat = p.get("sebi_category")
        sub = p.get("sebi_subcategory")
        if not cat:
            unbucketed.append(p)
            continue
        by_bucket.setdefault((cat, sub), []).append(p)

    # ── Step 2: per-bucket union-find → cluster of fund IDs ─────────
    def _union_find(bucket_pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Returns list of cluster dicts: {members, avg_overlap, max_overlap}."""
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent.get(x, x), parent.get(x, x))
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Seed nodes
        node_names: Dict[str, str] = {}
        for p in bucket_pairs:
            for k_id, k_name in (("a", "a_name"), ("b", "b_name")):
                nid = p.get(k_id)
                if nid is not None:
                    parent.setdefault(nid, nid)
                    node_names.setdefault(nid, p.get(k_name) or nid)

        edge_weights: Dict[tuple, float] = {}
        for p in bucket_pairs:
            a, b = p.get("a"), p.get("b")
            if a is None or b is None:
                continue
            union(a, b)
            edge_weights[(a, b)] = float(p.get("overlap_pct") or 0)

        # Bucket nodes by root
        groups: Dict[str, List[str]] = {}
        for nid in parent:
            groups.setdefault(find(nid), []).append(nid)

        clusters: List[Dict[str, Any]] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            mset = set(members)
            edge_pcts = [w for (a, b), w in edge_weights.items() if a in mset and b in mset]
            clusters.append({
                "ids": members,
                "names": [node_names[m] for m in members],
                "avg_overlap": sum(edge_pcts) / len(edge_pcts) if edge_pcts else 0.0,
                "max_overlap": max(edge_pcts) if edge_pcts else 0.0,
            })
        return clusters

    # ── Step 3: emit one insight per cluster ────────────────────────
    for (cat, sub), bucket_pairs in by_bucket.items():
        for cluster in _union_find(bucket_pairs):
            n = len(cluster["ids"])
            avg_ov = cluster["avg_overlap"]
            max_ov = cluster["max_overlap"]
            label = sub or cat
            impact = "high" if max_ov >= 70 else "medium" if max_ov >= 55 else "low"

            # 2026-05-20 user directive: "Which funds are duplicated not
            # show" — surface member fund names directly in the detail
            # text so the user can see the cluster contents without
            # drilling into metadata. Cap at 4 names + "+N more" so the
            # text stays scannable even for big clusters.
            short_names = [_truncate_name(nm, 38) for nm in cluster["names"]]
            visible = short_names[:4]
            extra_n = len(short_names) - len(visible)
            member_line = ", ".join(visible) + (f", +{extra_n} more" if extra_n > 0 else "")

            # ── Winner pick via consolidation_score_engine ──────────────
            # Build a local id→name map from the cluster data itself.
            id_to_name: Dict[str, str] = dict(zip(cluster["ids"], cluster["names"]))
            mf_by_id: Dict[str, Dict] = {
                m["instrument_id"]: m
                for m in (intelligence.get("mf_investments") or [])
                if m.get("instrument_id")
            }
            retain_name: Optional[str] = None
            exit_names: List[str] = []
            winner_confidence: Optional[str] = None

            try:
                from services.consolidation_score_engine import (
                    ConsolidationInput, FundSnapshot, score_pair,
                )
                member_ids = cluster["ids"]
                win_count: Dict[str, int] = {mid: 0 for mid in member_ids}

                for i, id_a in enumerate(member_ids):
                    for id_b in member_ids[i + 1:]:
                        ma = mf_by_id.get(id_a, {})
                        mb = mf_by_id.get(id_b, {})
                        snap_a = FundSnapshot(
                            name=id_to_name.get(id_a, id_a),
                            scheme_code=id_a,
                            current_value_rs=float(ma.get("amount_rs") or 0),
                            return_1y=ma.get("ret_1y"),
                            return_3y=ma.get("ret_3y"),
                            return_5y=ma.get("ret_5y"),
                            sharpe_1y=ma.get("sharpe"),
                            ter_pct=ma.get("expense_ratio"),
                        )
                        snap_b = FundSnapshot(
                            name=id_to_name.get(id_b, id_b),
                            scheme_code=id_b,
                            current_value_rs=float(mb.get("amount_rs") or 0),
                            return_1y=mb.get("ret_1y"),
                            return_3y=mb.get("ret_3y"),
                            return_5y=mb.get("ret_5y"),
                            sharpe_1y=mb.get("sharpe"),
                            expense_ratio_pct=mb.get("expense_ratio"),
                        )
                        res = score_pair(ConsolidationInput(
                            fund_a=snap_a,
                            fund_b=snap_b,
                            overlap_pct=max_ov,
                        ))
                        if res.retain:
                            for mid in member_ids:
                                if id_to_name.get(mid) == res.retain:
                                    win_count[mid] = win_count.get(mid, 0) + 1
                                    break
                        winner_confidence = res.confidence

                if win_count:
                    winner_id = max(win_count, key=lambda k: win_count[k])
                    retain_name = id_to_name.get(winner_id)
                    exit_names = [id_to_name.get(mid) for mid in member_ids if mid != winner_id]
            except Exception as _exc:
                logger.debug("[_project_overlap] winner_pick failed: %s", _exc)

            if retain_name and exit_names:
                exit_list = ", ".join(_truncate_name(nm, 32) for nm in exit_names if nm)
                action_text = (
                    f"Keep {_truncate_name(retain_name, 38)} "
                    f"(highest quality score"
                    + (f", {winner_confidence} confidence" if winner_confidence else "")
                    + f"). Exit: {exit_list}. "
                    "Stagger exits across 2 financial years if the tax cost is material."
                )
                winner_pick_pending = False
            else:
                action_text = (
                    "Keep the highest-scoring fund and exit the others. "
                    "Stagger exits across 2 financial years if the tax cost is material."
                )
                retain_name = None
                winner_pick_pending = True

            out.append({
                "id": f"overlap_cluster:{label}:{','.join(sorted(cluster['ids']))}",
                "signal_type": "warning",
                "impact": impact,
                "kind": "OVERLAP",
                "title": f"Consolidate {n} funds in your {label} category",
                "action": action_text,
                "detail": (
                    f"{n} funds in {label} with avg pairwise overlap "
                    f"{avg_ov:.0f}% (max {max_ov:.0f}%). Funds: "
                    f"{member_line}."
                ),
                "amount_rs": None,
                "metadata": {
                    "sebi_category":     cat,
                    "sebi_subcategory":  sub,
                    "fund_ids":          cluster["ids"],
                    "fund_names":        cluster["names"],
                    "retain_name":       retain_name,
                    "exit_names":        exit_names,
                    "deep_link":         "insights#overlap",
                    "winner_pick_pending": winner_pick_pending,
                },
            })

    # ── Step 4: unbucketed pairs keep the old pair-shape (rare) ────
    # If SEBI categories aren't yet enriched upstream (e.g. older data),
    # emit pair-shape so the UI still surfaces something.
    for p in unbucketed:
        pct = float(p.get("overlap_pct") or 0)
        impact = "high" if pct >= 70 else "medium" if pct >= 55 else "low"
        out.append({
            "id": f"overlap:{p.get('a')}:{p.get('b')}",
            "signal_type": "warning",
            "impact": impact,
            "kind": "OVERLAP",
            "title": f"{p.get('a_name', 'Fund A')} and {p.get('b_name', 'Fund B')} overlap {pct:.0f}%",
            "action": "Exit the lower-scoring fund and redeploy into a non-overlapping category",
            "detail": "; ".join(p.get("reasons") or []) or f"{p.get('shared_count', 0)} stocks held in both funds",
            "amount_rs": None,
            "metadata": {
                "fund_a_id": p.get("a"),
                "fund_b_id": p.get("b"),
                "deep_link": "insights#overlap",
            },
        })

    # Sort: cluster insights (high impact) first, ties broken by max overlap.
    out.sort(key=lambda r: (
        0 if r["kind"] == "OVERLAP" and r["impact"] == "high" else
        1 if r["impact"] == "medium" else
        2,
    ))
    return out


def _project_top_stocks(intelligence: Dict[str, Any]) -> List[Dict[str, Any]]:
    top = intelligence.get("top_stocks") or []
    out: List[Dict[str, Any]] = []
    for s in top[:3]:
        pct = float(s.get("exposure_pct") or 0)
        if pct < 8:
            continue
        impact = "high" if pct >= 15 else "medium"
        out.append({
            "id": f"stock_conc:{s.get('name')}",
            "signal_type": "risk",
            "impact": impact,
            "kind": "STOCK_CONCENTRATION",
            "title": f"{s.get('name')} is {pct:.1f}% of your portfolio",
            "action": f"Review exposure — held via {s.get('fund_count', 0)} fund(s); cap single-stock weight near 10%",
            "detail": f"{_fmt_rs(s.get('exposure_rs'))} concentrated in {s.get('name')}",
            "amount_rs": s.get("exposure_rs"),
            "metadata": {"stock": s.get("name"), "deep_link": "insights#concentration"},
        })
    return out


def _project_amc_concentration(intelligence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flag when a single AMC holds > 25% of MF AUM.

    Uses the AMC parsed from scheme_name (no extra DAAS call needed; the
    AMC is the first 1–3 words of the scheme name in the AMFI master).
    """
    mfs = intelligence.get("mf_investments") or []
    if not mfs:
        return []
    total = sum(float(mf.get("amount_rs") or 0) for mf in mfs)
    if total <= 0:
        return []

    def _amc_of(name: str) -> str:
        if not name:
            return ""
        # AMFI scheme names start with the AMC: e.g. "HDFC Flexicap Fund - Direct Plan"
        # First 2 tokens are usually enough.
        toks = name.split()
        if not toks:
            return ""
        if len(toks) >= 2 and toks[1].lower() in ("mutual", "asset"):
            return " ".join(toks[:3]).rstrip(" -")
        return toks[0]

    bucket: Dict[str, float] = {}
    name_by_amc: Dict[str, List[str]] = {}
    for mf in mfs:
        amc = _amc_of(mf.get("scheme_name") or "")
        if not amc:
            continue
        bucket[amc] = bucket.get(amc, 0.0) + float(mf.get("amount_rs") or 0)
        name_by_amc.setdefault(amc, []).append(mf.get("scheme_name") or "")

    if not bucket:
        return []
    top_amc, top_rs = max(bucket.items(), key=lambda kv: kv[1])
    pct = top_rs / total * 100
    if pct < 25:
        return []
    impact = "high" if pct >= 40 else "medium"
    return [{
        "id": f"amc:{top_amc}",
        "signal_type": "warning",
        "impact": impact,
        "kind": "AMC_CONCENTRATION",
        "title": f"{top_amc} holds {pct:.0f}% of your MF corpus",
        "action": f"Diversify across AMCs — single-AMC weight should stay below 25%",
        "detail": f"{_fmt_rs(top_rs)} in {len(name_by_amc[top_amc])} {top_amc} fund(s); single-house concentration amplifies operational + style risk.",
        "amount_rs": top_rs,
        "metadata": {
            "amc": top_amc,
            "funds": name_by_amc[top_amc][:5],
            "deep_link": "insights#amc",
        },
    }]


def _project_sectors(intelligence: Dict[str, Any]) -> List[Dict[str, Any]]:
    sectors = intelligence.get("sector_exposure") or []
    out: List[Dict[str, Any]] = []
    for s in sectors[:1]:
        pct = max(0.0, min(100.0, float(s.get("pct") or 0)))
        if pct < 30:
            continue
        impact = "high" if pct >= 40 else "medium"
        out.append({
            "id": f"sector:{s.get('sector')}",
            "signal_type": "warning",
            "impact": impact,
            "kind": "SECTOR_CONCENTRATION",
            "title": f"{s.get('sector', '?')} is {pct:.0f}% of your equity",
            "action": "Diversify into other sectors to reduce single-sector drawdown risk",
            "detail": f"{_fmt_rs(s.get('rs'))} tilted to {s.get('sector', '?')}",
            "amount_rs": s.get("rs"),
            "metadata": {"sector": s.get("sector"), "deep_link": "insights#sectors"},
        })
    return out


def _project_rebalance(rebalance: Any) -> List[Dict[str, Any]]:
    if not getattr(rebalance, "ok", False):
        return []
    data = rebalance.data or {}
    rows = rebalance.rows or []
    equity_pct = float(data.get("equity_pct") or 0)
    target_equity = float(data.get("target_equity_pct") or 65)
    drift = equity_pct - target_equity
    out: List[Dict[str, Any]] = []
    primary = next((r for r in rows if r.get("action") in ("SELL", "BUY")), None)
    if primary:
        impact = "high" if abs(drift) >= 10 else "medium"
        out.append({
            "id": f"rebalance:{primary.get('action')}:{primary.get('asset')}",
            "signal_type": "action",
            "impact": impact,
            "kind": "REBALANCE",
            "title": f"Portfolio drift: equity {equity_pct:.0f}% vs target {target_equity:.0f}%",
            "action": primary.get("reason") or "Rebalance to target allocation",
            "detail": (
                f"{primary.get('action')} {_fmt_rs(primary.get('amount_rs'))} of "
                f"{primary.get('asset')} to restore the {target_equity:.0f}/{100 - target_equity:.0f} split"
            ),
            "amount_rs": primary.get("amount_rs"),
            "metadata": {"deep_link": "plan_board#rebalance"},
        })
    # Direct-plan switches (cost reduction)
    switches = [r for r in rows if r.get("action") == "SWITCH"]
    if switches:
        out.append({
            "id": f"cost:direct_switch:{len(switches)}",
            "signal_type": "opportunity",
            "impact": "medium",
            "kind": "COST_REDUCTION",
            "title": f"Save ~0.8% p.a. by switching {len(switches)} fund(s) to Direct plan",
            "action": "Move regular plans to direct plans (no broker commission)",
            "detail": f"Regular-plan funds: {', '.join(s.get('asset', '?') for s in switches[:3])}"
                      + ("…" if len(switches) > 3 else ""),
            "amount_rs": None,
            "metadata": {"funds": [s.get("asset") for s in switches], "deep_link": "plan_board#switch"},
        })
    return out


def _project_tax_harvest(harvest: Any) -> List[Dict[str, Any]]:
    if not getattr(harvest, "ok", False):
        return []
    rows = harvest.rows or []
    losses = [r for r in rows if (r.get("gain_rs") or 0) < 0]
    if not losses:
        return []
    total_loss = abs(sum(float(r.get("gain_rs") or 0) for r in losses))
    # FY 2025-26: equity LTCG 12.5%, STCG 20% — harvesting loss offsets future gain.
    tax_saved_est = total_loss * 0.20
    impact = "high" if tax_saved_est >= 50_000 else "medium" if tax_saved_est >= 10_000 else "low"
    return [{
        "id": "tax:harvest",
        "signal_type": "opportunity",
        "impact": impact,
        "kind": "TAX_HARVEST",
        "title": f"Realise {_fmt_rs(total_loss)} of losses to save up to {_fmt_rs(tax_saved_est)} in tax",
        "action": f"Book losses on {len(losses)} position(s); offset against future capital gains",
        "detail": (
            f"FY 2025-26: losses can offset equity STCG (20%) or LTCG (12.5% beyond ₹1.25L). "
            f"Re-enter after the wash-sale window."
        ),
        "amount_rs": tax_saved_est,
        "metadata": {
            "positions": [r.get("scheme_name") or r.get("name") for r in losses[:5]],
            "deep_link": "insights#tax",
        },
    }]


def _project_risk_misalignment(risk: Any) -> List[Dict[str, Any]]:
    if not getattr(risk, "ok", False):
        return []
    data = risk.data or {}
    misalignment = data.get("misalignment")
    if not misalignment:
        return []
    rating = data.get("risk_rating") or "?"
    profile = data.get("user_profile") or "?"
    return [{
        "id": "risk:misalignment",
        "signal_type": "risk",
        "impact": "high",
        "kind": "RISK_MISALIGNMENT",
        "title": f"Portfolio risk ({rating}) doesn't match your profile ({profile})",
        "action": "Rebalance to bring volatility within your risk tolerance",
        "detail": str(misalignment) if isinstance(misalignment, str) else "Mismatch between portfolio volatility and your declared risk profile",
        "amount_rs": None,
        "metadata": {"deep_link": "insights#risk"},
    }]


async def _project_weak_funds(intelligence: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fetch composite scorecards in parallel for every held MF and flag red flags."""
    mfs = intelligence.get("mf_investments") or []
    if not mfs:
        return []
    scheme_codes = [(mf.get("scheme_code") or mf.get("instrument_id"), mf) for mf in mfs if mf.get("scheme_code")]
    if not scheme_codes:
        return []

    async def _safe(code: str):
        try:
            return await mf_intel.get_mf_intelligence(code)
        except Exception as exc:
            logger.debug("mf_intel fetch failed for %s: %s", code, exc)
            return None

    results = await asyncio.gather(*[_safe(c) for c, _ in scheme_codes])
    out: List[Dict[str, Any]] = []
    for (code, mf), res in zip(scheme_codes, results):
        if res is None or not getattr(res, "ok", False):
            continue
        # Red flag events (manager change, TER hike, merger, risk increase)
        has_red = bool(getattr(res, "has_red_flags", False))
        comp_score = getattr(res, "composite_score", None)
        quality = (getattr(res, "quality_label", "") or "").lower()
        # Treat composite < 50 or quality in {weak, poor, exit, q4} as weak
        weak = (
            (comp_score is not None and float(comp_score) < 50)
            or quality in ("weak", "poor", "exit", "q4")
        )
        if has_red or weak:
            reasons = []
            if has_red:
                ev_kinds = [e.get("kind") or e.get("type") for e in (getattr(res, "events", []) or [])]
                reasons.append("red flags: " + ", ".join(filter(None, ev_kinds[:3])))
            if comp_score is not None and float(comp_score) < 50:
                reasons.append(f"composite score {comp_score:.0f}/100")
            if quality and quality not in ("good", "great", "excellent", "q1", "q2"):
                reasons.append(f"quality: {quality}")
            out.append({
                "id": f"weak_mf:{code}",
                "signal_type": "warning",
                "impact": "high" if has_red else "medium",
                "kind": "WEAK_MF",
                "title": f"Review {mf.get('scheme_name') or 'fund'} — {reasons[0] if reasons else 'underperforming'}",
                "action": "Consider exiting and switching to a top-quartile peer in the same category",
                "detail": " · ".join(reasons[:3]),
                "amount_rs": mf.get("amount_rs"),
                "metadata": {
                    "scheme_code": code,
                    "scheme_name": mf.get("scheme_name"),
                    "deep_link": "insights#weak_funds",
                },
            })
    return out


async def _project_weak_stocks(user_id: str) -> List[Dict[str, Any]]:
    """Fetch composite scores for held stocks; flag fundamentally + technically weak."""
    holdings = await db.holdings.find(
        {"user_id": user_id, "asset_type": {"$in": ["equity", "stock", "Equity", "Stock"]}},
        {"_id": 0},
    ).to_list(200)
    symbols = [h.get("symbol") or h.get("name") for h in holdings if h.get("symbol") or h.get("name")]
    symbols = [s for s in symbols if s]
    if not symbols:
        return []
    try:
        scored = await rec_tools.composite_score_batch(symbols, top_n=len(symbols))
    except Exception as exc:
        logger.debug("composite_score_batch failed: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for s in scored:
        total = float(getattr(s, "total_score", 0) or 0)
        # composite_score_batch normalises to 0–10; weak = ≤ 3.5
        if total > 3.5:
            continue
        signal = (getattr(s, "signal", "") or "").upper()
        if signal in ("BUY", "ACCUMULATE"):
            continue
        out.append({
            "id": f"weak_stock:{s.symbol}",
            "signal_type": "warning",
            "impact": "high" if total <= 2.5 else "medium",
            "kind": "WEAK_STOCK",
            "title": f"Exit candidate: {s.symbol} (score {total:.1f}/10, {signal or 'weak'})",
            "action": "Review fundamentals + technicals; switch into a higher-scoring peer in the same sector",
            "detail": " · ".join((s.reasons or [])[:2]) or "Weak composite score",
            "amount_rs": None,
            "metadata": {
                "symbol": s.symbol,
                "sector": (s.data or {}).get("sector"),
                "deep_link": "insights#weak_stocks",
            },
        })
    return out


# ──────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────

async def build_dashboard_recommendations(user_id: str) -> List[Dict[str, Any]]:
    """Run all detectors + tool projectors in parallel, return ranked insights."""
    # 1. Portfolio intelligence (used by several projectors)
    intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
    if intelligence.get("empty"):
        return []

    # 2. Fan out — tool calls are independent
    rebalance_t = asyncio.create_task(port_tools.get_rebalance_plan(user_id))
    harvest_t = asyncio.create_task(port_tools.get_tax_harvest_candidates(user_id))
    risk_t = asyncio.create_task(risk_tools.get_risk_suitability(user_id))
    weak_funds_t = asyncio.create_task(_project_weak_funds(intelligence))
    weak_stocks_t = asyncio.create_task(_project_weak_stocks(user_id))

    rebalance, harvest, risk_res, weak_funds, weak_stocks = await asyncio.gather(
        rebalance_t, harvest_t, risk_t, weak_funds_t, weak_stocks_t,
        return_exceptions=True,
    )

    def _unwrap(x, default):
        return default if isinstance(x, Exception) else x

    insights: List[Dict[str, Any]] = []
    insights.extend(_project_overlap(intelligence))
    insights.extend(_project_top_stocks(intelligence))
    insights.extend(_project_sectors(intelligence))
    insights.extend(_project_amc_concentration(intelligence))
    insights.extend(_project_rebalance(_unwrap(rebalance, None)))
    insights.extend(_project_tax_harvest(_unwrap(harvest, None)))
    insights.extend(_project_risk_misalignment(_unwrap(risk_res, None)))
    insights.extend(_unwrap(weak_funds, []))
    insights.extend(_unwrap(weak_stocks, []))

    # Dedupe by id and sort by (impact, signal_type)
    seen = set()
    unique: List[Dict[str, Any]] = []
    for ins in insights:
        if ins.get("id") in seen:
            continue
        seen.add(ins.get("id"))
        unique.append(ins)
    unique.sort(key=_rank)
    return unique
