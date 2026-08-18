"""NIDP-backed MF intelligence tool for the copilot.

Aggregates four intelligence layers for a single MF scheme concurrently:

  1. Scorecard        → /v1/mf/performance/scorecard/{scheme_code}
                        composite_score, quality_label, quartile ranks (migration 052)
  2. Lifecycle events → /v1/mf/schemes/{scheme_code}/events
                        TER changes, fund manager changes, risk-o-meter shifts,
                        mergers, renames — essential for "should I continue?"
  3. Top holdings     → /v1/mf/holdings/{scheme_code}?limit=10
                        Top 10 securities + sector weights — "what does it own?"
  4. Disclosure trail → /v1/mf/schemes/{scheme_code}/disclosure?limit=4
                        Recent TER and risk-o-meter snapshots — "is TER creeping up?"

Public API:
    get_mf_intelligence(scheme_code) → MfIntelResult
    get_mf_screener(category, sort_by, min_composite, max_ter, limit) → list[dict]
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Event types that are red-flags — highlighted in LLM context
_RED_FLAG_EVENTS = {"MANAGER_CHANGE", "RISK_INCREASE", "MERGER", "TER_INCREASE", "SUSPENSION"}
_POSITIVE_EVENTS = {"TER_DECREASE", "RISK_DECREASE", "STRATEGY_CLARIFICATION"}


@dataclass
class MfIntelResult:
    scheme_code: str
    ok: bool
    summary: str
    # Layer 1: Scorecard
    composite_score:    Optional[float] = None
    quality_label:      Optional[str]   = None
    composite_rank:     Optional[int]   = None
    total_in_category:  Optional[int]   = None
    top_position_pct:   Optional[float] = None
    scorecard:          Dict[str, Any]  = field(default_factory=dict)
    # Layer 2: Lifecycle events
    events:             List[Dict[str, Any]] = field(default_factory=list)
    has_red_flags:      bool = False
    # Layer 3: Holdings
    top_holdings:       List[Dict[str, Any]] = field(default_factory=list)
    top_sectors:        List[Dict[str, Any]] = field(default_factory=list)
    # Layer 4: Disclosure
    disclosures:        List[Dict[str, Any]] = field(default_factory=list)
    current_ter:        Optional[float] = None
    current_manager:    Optional[str]   = None
    risk_o_meter:       Optional[str]   = None
    error:              Optional[str]   = None

    def as_llm_context(self) -> str:
        lines = [f"scheme={self.scheme_code}"]

        # Scorecard
        if self.composite_score is not None:
            rank_str = f"#{self.composite_rank}/{self.total_in_category}" if self.composite_rank else ""
            pct_str  = f" Top{self.top_position_pct:.0f}%" if self.top_position_pct else ""
            lines.append(
                f"scorecard: score={self.composite_score:.0f}/100 "
                f"label={self.quality_label} rank={rank_str}{pct_str}"
            )
            sc = self.scorecard
            qtiles = []
            for k, label in [
                ("qtile_ret1y", "1Y ret"), ("qtile_ret3y", "3Y ret"),
                ("qtile_sharpe", "Sharpe"), ("qtile_maxdd", "drawdown"),
                ("qtile_ter", "TER"), ("qtile_consistency", "consistency"),
            ]:
                q = sc.get(k)
                if q is not None:
                    qtiles.append(f"{label}=Q{int(q)}")
            if qtiles:
                lines.append("  quartiles: " + " | ".join(qtiles))

        # Disclosure
        if self.current_ter is not None:
            lines.append(f"TER={self.current_ter:.2f}% manager={self.current_manager or '?'} risk={self.risk_o_meter or '?'}")

        # Lifecycle events (most recent 4, red-flags first)
        if self.events:
            lines.append(f"lifecycle_events ({len(self.events)} total, red_flags={self.has_red_flags}):")
            flags = [e for e in self.events if e.get("event_type","").upper() in _RED_FLAG_EVENTS]
            others = [e for e in self.events if e not in flags]
            for e in (flags + others)[:4]:
                flag = "⚠️ " if e.get("event_type","").upper() in _RED_FLAG_EVENTS else ""
                lines.append(
                    f"  {flag}[{e.get('event_type','?')}] {e.get('event_date','')} "
                    f"{(e.get('description') or e.get('headline') or '')[:80]}"
                )

        # Top holdings
        if self.top_holdings:
            holdings_str = ", ".join(
                f"{h.get('security_name','?')} {h.get('weight_pct',0):.1f}%"
                for h in self.top_holdings[:5]
            )
            lines.append(f"top_holdings: {holdings_str}")

        if self.top_sectors:
            sector_str = ", ".join(
                f"{s.get('sector','?')} {s.get('total_weight',0):.1f}%"
                for s in self.top_sectors[:4]
            )
            lines.append(f"sector_allocation: {sector_str}")

        return " | ".join(lines) if len(lines) == 1 else "\n  ".join(lines)


async def _daas_get(path: str, params: Optional[Dict] = None) -> Any:
    import os, httpx
    base = os.environ.get("NIDP_DAAS_BASE_URL", "https://data.niveshcopilot.com/daas").rstrip("/")
    # Admin UI registers the key as NIDP_DAAS_INTERNAL_TOKEN; Cloud Run may use
    # NIDP_DAAS_API_KEY — accept either so the call authenticates on both paths.
    key  = os.environ.get("NIDP_DAAS_API_KEY", "") or os.environ.get("NIDP_DAAS_INTERNAL_TOKEN", "")
    headers = {"X-API-Key": key, "Accept": "application/json"} if key else {"Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(f"{base}{path}", params=params or {}, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        return {}
    except Exception as exc:
        logger.debug("DAAS %s failed: %s", path, exc)
        return {}


def _aggregate_sectors(holdings: List[Dict]) -> List[Dict]:
    """Roll up holdings into sector weights, sorted descending."""
    totals: Dict[str, float] = {}
    for h in holdings:
        sector = h.get("sector") or "Other"
        wt = float(h.get("weight_pct") or 0)
        totals[sector] = totals.get(sector, 0.0) + wt
    return sorted(
        [{"sector": s, "total_weight": round(w, 2)} for s, w in totals.items()],
        key=lambda x: x["total_weight"],
        reverse=True,
    )


async def get_mf_intelligence(scheme_code: str) -> MfIntelResult:
    """Fetch all four NIDP intelligence layers for an MF scheme concurrently."""

    scorecard_resp, events_resp, holdings_resp, disclosure_resp = await asyncio.gather(
        _daas_get(f"/v1/mf/performance/scorecard/{scheme_code}"),
        _daas_get(f"/v1/mf/schemes/{scheme_code}/events", {"limit": 10}),
        _daas_get(f"/v1/mf/holdings/{scheme_code}", {"limit": 15, "instrument_type": "EQUITY"}),
        _daas_get(f"/v1/mf/schemes/{scheme_code}/disclosure", {"limit": 4}),
        return_exceptions=True,
    )

    # ── Layer 1: Scorecard ────────────────────────────────────────────────
    scorecard: Dict[str, Any] = {}
    composite_score = quality_label = composite_rank = total_in_category = top_position_pct = None
    if isinstance(scorecard_resp, dict) and scorecard_resp.get("data"):
        scorecard = scorecard_resp["data"]
        composite_score   = scorecard.get("composite_score")
        quality_label     = scorecard.get("quality_label")
        composite_rank    = scorecard.get("composite_rank")
        total_in_category = scorecard.get("total_in_category")
        top_position_pct  = scorecard.get("top_position_pct")

    # ── Layer 2: Lifecycle events ─────────────────────────────────────────
    events: List[Dict] = []
    if isinstance(events_resp, dict):
        events = events_resp.get("rows") or events_resp.get("events") or []
    elif isinstance(events_resp, list):
        events = events_resp
    has_red_flags = any(
        e.get("event_type", "").upper() in _RED_FLAG_EVENTS for e in events
    )

    # ── Layer 3: Holdings ─────────────────────────────────────────────────
    top_holdings: List[Dict] = []
    if isinstance(holdings_resp, dict):
        top_holdings = holdings_resp.get("rows") or holdings_resp.get("data") or []
    elif isinstance(holdings_resp, list):
        top_holdings = holdings_resp
    top_sectors = _aggregate_sectors(top_holdings)

    # ── Layer 4: Disclosure trail ─────────────────────────────────────────
    disclosures: List[Dict] = []
    current_ter = current_manager = risk_o_meter = None
    if isinstance(disclosure_resp, dict):
        disclosures = disclosure_resp.get("rows") or disclosure_resp.get("data") or []
        if not isinstance(disclosures, list) and isinstance(disclosure_resp.get("data"), dict):
            disclosures = [disclosure_resp["data"]]
    if disclosures:
        latest = disclosures[0]
        current_ter     = latest.get("ter_pct")
        current_manager = latest.get("primary_manager")
        risk_o_meter    = latest.get("risk_o_meter")

    # ── Build summary ─────────────────────────────────────────────────────
    ok = bool(scorecard or events or top_holdings or disclosures)
    parts = []
    if quality_label and composite_rank and total_in_category:
        parts.append(f"{quality_label} score={composite_score:.0f}/100 rank=#{composite_rank}/{total_in_category}")
    if has_red_flags:
        red_types = [e.get("event_type","") for e in events if e.get("event_type","").upper() in _RED_FLAG_EVENTS]
        parts.append(f"⚠️ red flags: {', '.join(set(red_types))}")
    if current_ter:
        parts.append(f"TER={current_ter:.2f}%")
    if top_holdings:
        parts.append(f"{len(top_holdings)} holdings loaded")
    summary = f"{scheme_code}: " + (", ".join(parts) if parts else "data unavailable")

    return MfIntelResult(
        scheme_code=scheme_code,
        ok=ok,
        summary=summary,
        composite_score=composite_score,
        quality_label=quality_label,
        composite_rank=composite_rank,
        total_in_category=total_in_category,
        top_position_pct=top_position_pct,
        scorecard=scorecard,
        events=events,
        has_red_flags=has_red_flags,
        top_holdings=top_holdings,
        top_sectors=top_sectors,
        disclosures=disclosures,
        current_ter=current_ter,
        current_manager=current_manager,
        risk_o_meter=risk_o_meter,
    )


async def get_mf_screener(
    category: Optional[str] = None,
    sort_by: str = "composite_score",
    min_composite: Optional[float] = None,
    max_ter: Optional[float] = None,
    min_return_3y: Optional[float] = None,
    min_sharpe: Optional[float] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Fetch top MF schemes filtered by quality criteria.

    Uses the composite scorecard (migration 052) so every returned scheme
    has composite_score, quality_label, and quartile ranks.
    Falls back to `/v1/mf/performance/screener/top` when no filters are set.
    """
    params: Dict[str, Any] = {"limit": limit}

    if category:
        path = f"/v1/mf/performance/screener/advanced"
        params.update({
            "category":      category,
            "sort_by":       sort_by,
            "min_composite": min_composite,
            "max_ter":       max_ter,
            "min_return_3y": min_return_3y,
            "min_sharpe":    min_sharpe,
        })
        # strip None values
        params = {k: v for k, v in params.items() if v is not None}
    else:
        # Cross-category screener
        path = "/v1/mf/performance/screener/top"
        sort_metric_map = {
            "composite_score": "composite_rank",
            "return_3y":       "return_3y",
            "sharpe":          "sharpe_1y",
            "ter":             "ter",
        }
        params["metric"] = sort_metric_map.get(sort_by, "composite_rank")

    resp = await _daas_get(path, params)
    if isinstance(resp, dict):
        return resp.get("rows") or resp.get("data") or []
    return []
