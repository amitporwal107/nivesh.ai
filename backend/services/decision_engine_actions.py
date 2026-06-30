"""Decision-Engine Action Generator — Step 5 of the architecture.

Given a `DeviationResult` and a sector/category cap analysis, emits
concrete SELL/BUY/TRIM actions in the same shape `action_plan_manager`
already persists. Two rule families:

  • Rule 6 — Asset-class drift (equity/debt/gold over- or under-weight
    vs target by more than the hard threshold).
  • Rule 7 — Sector cap (any sector >30% of equity exposure).
  • Rule 8 — Market-cap cap (any fund-category bucket >40% of MF AUM,
    e.g. small-cap heavy).

Rule 6 actions:
  • OVERWEIGHT bucket → TRIM the largest holdings in that bucket
    (₹ amount = (current_pct - target_pct) × portfolio_value).
  • UNDERWEIGHT bucket → ADD a placeholder fund in that bucket.

Each emitted action has the same field set as the action_plan_manager
rules (type, asset_name, amount, reason_codes, reason_text) so it
slots cleanly into the existing plan-board UI.

This module is INTENTIONALLY decoupled from action_plan_manager.py —
that file is large and rules 2 / 4 / 5 there are already battle-tested.
The new rules live here so they can be invoked / tested independently
and surfaced via the chat RAG without touching the dashboard plan flow.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Caps tuned against the architecture doc. Tweakable later via
# rules_config.system_config if business wants UI control.
_SECTOR_CAP_PCT = 30.0       # any sector >30% of equity → trim
_CATEGORY_CAP_PCT = 40.0     # any fund-category >40% of MF AUM → trim
_MIN_ACTION_RS = 5_000       # don't emit micro-actions below ₹5k
_MAX_TRIMS_PER_BUCKET = 2    # at most N trim suggestions per asset bucket
                             # (otherwise 5 SGBs in gold burn the action cap)

# Composite trim-ranking weights (user-confirmed): when an asset bucket is
# over-weight, *which* holding to trim first is decided by a blend of real
# per-fund signals rather than raw size. Higher composite ⇒ trim first.
_TRIM_W_QUALITY = 0.40       # exit/quality score (weak-vs-peers) — 0-10, higher worse
_TRIM_W_OVERLAP = 0.30       # max overlap with a sibling fund — 0-100, higher worse
_TRIM_W_TAX     = 0.30       # tax cost to exit — % of proceeds, lower = trim first

# Appended to any card that names a specific instrument to buy/sell. Naming
# specific funds/stocks is investment advice (RIA-regulated in India), so each
# such card carries this educational-only qualifier.
_ADVICE_DISCLAIMER = " ⓘ Educational only — not investment advice."


@dataclass
class ProposedAction:
    type: str                       # "TRIM" | "EXIT" | "ADD"
    asset_name: str                 # holding/fund name (or generic for ADDs)
    amount_rs: float                # ₹ amount to move
    reason_codes: List[str] = field(default_factory=list)
    reason_text: str = ""
    bucket: Optional[str] = None    # "equity" | "debt" | "gold" | sector | category
    rule: Optional[str] = None      # "Rule 6" | "Rule 7" | "Rule 8"
    priority: str = "medium"        # "high" | "medium" | "low" — set by rule
    score: float = 5.0              # for cap-tiebreak vs legacy actions

    def to_dict(self) -> Dict[str, Any]:
        # Drop-in compatible with both:
        #   • orchestrator's plan formatter (reads `action_type`)
        #   • action_plan_manager's pipeline (reads `type`, `priority`,
        #     `status`, `action_id`, `amount`, optionally `score`).
        # Emitting all fields lets the same dict survive both consumers.
        from uuid import uuid4
        return {
            "action_id": f"act_{uuid4().hex[:12]}",
            "type": self.type,
            "action_type": self.type,
            "asset_name": self.asset_name,
            "amount": round(self.amount_rs, 0),
            "amount_rs": round(self.amount_rs, 0),
            "reason_codes": self.reason_codes,
            "reason_text": self.reason_text,
            "priority": self.priority,
            "status": "PENDING",
            "score": self.score,
            "tax_impact": None,     # drift moves don't have computed tax
            "bucket": self.bucket,
            "rule": self.rule,
            "source": "decision_engine",  # marker for telemetry
        }


# ── Composite trim-ranking (which holding to trim first, and why) ──────
def _minmax_norm(vals: List[float]) -> List[float]:
    """Min-max normalise to 0..1. Flat input → all zeros (no signal)."""
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span <= 0:
        return [0.0 for _ in vals]
    return [(v - lo) / span for v in vals]


def _composite_trim_order(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order trim candidates worst-first by a composite of whatever signals
    are present on each dict: ``exit_score`` (0-10, higher worse),
    ``overlap_pct`` (0-100, higher worse), ``tax_pct`` (% of proceeds, lower =
    trim first). Each signal is min-max normalised across the candidate set;
    missing signals are dropped and the remaining weights renormalised so a
    fund with partial data is judged only on what it has. Falls back to pure
    size ordering when no candidate carries any signal (so behaviour is
    unchanged — and the reason stays the plain drift sentence — when the
    enrichment couldn't run). Annotates ``_decider`` on each returned dict."""
    if not candidates:
        return []

    def norm_for(key: str, invert: bool) -> Dict[int, float]:
        present = [(i, c[key]) for i, c in enumerate(candidates) if c.get(key) is not None]
        if not present:
            return {}
        normed = _minmax_norm([v for _, v in present])
        return {i: (1.0 - nv if invert else nv) for (i, _), nv in zip(present, normed)}

    q = norm_for("exit_score", invert=False)   # higher exit_score → trim first
    o = norm_for("overlap_pct", invert=False)  # higher overlap   → trim first
    t = norm_for("tax_pct", invert=True)        # lower tax cost   → trim first

    scored: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates):
        parts = []  # (weight, normval, label)
        if i in q:
            parts.append((_TRIM_W_QUALITY, q[i], "quality"))
        if i in o:
            parts.append((_TRIM_W_OVERLAP, o[i], "overlap"))
        if i in t:
            parts.append((_TRIM_W_TAX, t[i], "tax"))
        if parts:
            wsum = sum(w for w, _, _ in parts)
            composite = sum(w * nv for w, nv, _ in parts) / wsum
            decider = max(parts, key=lambda p: p[0] * p[1])[2]
        else:
            composite, decider = None, None
        c["_decider"] = decider
        scored.append({"c": c, "composite": composite})

    if all(s["composite"] is None for s in scored):
        # No real signals anywhere — preserve legacy size ordering.
        for c in candidates:
            c["_decider"] = None
        return sorted(candidates, key=lambda x: x["value"], reverse=True)

    # Worst composite first; tie-break by larger value so the cut is absorbable.
    scored.sort(key=lambda s: (-(s["composite"] if s["composite"] is not None else -1.0),
                               -s["c"]["value"]))
    return [s["c"] for s in scored]


def _trim_reason_suffix(h: Dict[str, Any]) -> str:
    """One sentence naming the signal that flagged this fund for trimming.
    Empty when no deciding signal (keeps the plain drift reason)."""
    d = h.get("_decider")
    if d == "quality" and h.get("exit_score") is not None:
        return (f" Trimming {h['name']} first — it's the weakest on quality in this"
                f" bucket (exit score {h['exit_score']:.1f}/10).")
    if d == "overlap" and h.get("overlap_pct"):
        sib = h.get("overlap_with")
        if sib:
            return (f" Trimming {h['name']} first — it overlaps {h['overlap_pct']:.0f}%"
                    f" with {sib}, so you lose the least diversification.")
        return (f" Trimming {h['name']} first — it's the most duplicated holding here"
                f" ({h['overlap_pct']:.0f}% overlap).")
    if d == "tax" and h.get("tax_pct") is not None:
        return (f" Trimming {h['name']} first — it's the cheapest to exit on tax"
                f" ({h['tax_pct']:.1f}% of proceeds).")
    return ""


def _isin_of(d: Dict[str, Any]) -> Optional[str]:
    """Normalised ISIN from an mf_investment / holding dict. Holdings keep the
    ISIN in ``ticker`` (12-char alnum); intelligence entries in ``isin``."""
    for key in ("isin", "ticker"):
        v = (d.get(key) or "").strip().upper()
        if len(v) == 12 and v.isalnum():
            return v
    return None


def _build_signal_index(mfs: List[Dict[str, Any]], pairs: List[Dict[str, Any]]):
    """Pure: index portfolio_intelligence output for ISIN-keyed lookup.

    Returns ``(mf_by_isin, best_ov)`` where ``best_ov`` maps an instrument_id to
    ``(best_overlap_pct, sibling_scheme_name)``. Joining on ISIN — not name —
    because the holding name ("HDFC … - Growth Plan") and the intelligence
    ``scheme_name`` ("HDFC … Growth") never normalise to the same string."""
    mf_by_isin: Dict[str, Dict[str, Any]] = {}
    for m in mfs or []:
        isin = _isin_of(m)
        if isin:
            mf_by_isin[isin] = m
    # pairwise_overlap pairs carry a/b (instrument_ids) + a_name/b_name.
    best_ov: Dict[Any, tuple] = {}
    for p in pairs or []:
        pct = float(p.get("overlap_pct") or 0)
        for x, sib in ((p.get("a"), p.get("b_name")), (p.get("b"), p.get("a_name"))):
            if x is None:
                continue
            if x not in best_ov or pct > best_ov[x][0]:
                best_ov[x] = (pct, sib or "")
    return mf_by_isin, best_ov


async def _attach_trim_signals(
    user_id: str,
    bucket_holdings: List[Dict[str, Any]],
    raw_holdings: List[Dict[str, Any]],
) -> None:
    """Best-effort: populate ``exit_score`` / ``overlap_pct`` / ``overlap_with``
    / ``tax_pct`` on each holding in ``bucket_holdings`` from real engine
    signals, joining holdings → intelligence by ISIN. Mutates in place. Any
    signal that can't be computed is left unset (None) so the composite simply
    ignores it — nothing is fabricated."""
    from services import portfolio_intelligence as _pi
    from services.decision_engine import calculate_mf_exit_score

    intel = await _pi.compute_portfolio_intelligence(user_id) or {}
    mf_by_isin, best_ov = _build_signal_index(
        intel.get("mf_investments") or [], intel.get("pairwise_overlap") or []
    )
    raw_by_isin = {iv: h for h in raw_holdings if (iv := _isin_of(h))}

    for h in bucket_holdings:
        isin = _isin_of(h)
        m = mf_by_isin.get(isin) if isin else None
        if not m:
            continue  # no ISIN match → no signals; composite falls back to size
        ov = best_ov.get(m.get("instrument_id"))
        if ov and ov[0]:
            h["overlap_pct"], h["overlap_with"] = ov
        raw = raw_by_isin.get(isin)
        if raw is not None:
            try:
                res = await calculate_mf_exit_score(m, intel, raw)
                if res:
                    es = res.get("exit_score")
                    if es is not None:
                        h["exit_score"] = float(es)
                    tp = (res.get("tax_impact") or {}).get("tax_pct_of_exit")
                    if tp is not None:
                        h["tax_pct"] = float(tp)
            except Exception as e:  # noqa: BLE001
                logger.debug("rule6 exit-score for %s failed: %s", h.get("name"), e)


# ── Rule 6: asset-class drift → TRIM / ADD ─────────────────────────────
async def _rule6_asset_class_drift(user_id: str) -> List[ProposedAction]:
    from services.deviation_engine import compute_deviation, _bucket_for_holding
    from deps import db

    dev = await compute_deviation(user_id)
    if not dev.rows:
        return []
    total_value = float(dev.extras.get("total_value_rs") or 0)
    if total_value <= 0:
        return []

    holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    # Pre-compute current value + bucket per holding so we can pick
    # what to trim from overweight buckets.
    enriched: List[Dict[str, Any]] = []
    for h in holdings:
        qty = float(h.get("quantity") or 0)
        cp = float(h.get("current_price") or 0)
        v = qty * cp
        if v <= 0:
            continue
        # Holdings store the ISIN in `ticker` (12-char alphanumeric) — carry it
        # so trim-signal enrichment can join to portfolio_intelligence by ISIN
        # (fund names differ between sources: "… - Growth Plan" vs "… Growth").
        tk = (h.get("ticker") or "").strip().upper()
        isin = tk if len(tk) == 12 and tk.isalnum() else None
        enriched.append({
            "name": h.get("name") or "Unknown",
            "type": (h.get("asset_type") or "").lower(),
            "value": v,
            "bucket": _bucket_for_holding(h),
            "isin": isin,
        })

    actions: List[ProposedAction] = []
    for row in dev.rows:
        if row.trigger != "hard":
            continue
        bucket = row.asset.lower()
        delta_rs = abs(row.deviation_pp) / 100.0 * total_value
        if delta_rs < _MIN_ACTION_RS:
            continue

        # Severity-driven priority + score: a 17pp-off bucket is more
        # urgent than a barely-over-10pp one and should outrank legacy
        # advisory actions in the cap sort.
        severity = abs(row.deviation_pp)
        if severity >= 15:
            prio, score = "high", 8.5
        elif severity >= 10:
            prio, score = "medium", 6.5
        else:
            prio, score = "low", 4.5

        if row.direction == "overweight":
            bucket_holdings = [h for h in enriched if h["bucket"] == bucket]
            # Augment: decide *which* holding to trim first by a composite of
            # real per-fund signals (quality/exit score, sibling overlap, tax
            # cheapness) instead of raw size, and surface the deciding signal
            # in the reason so the card explains *why this fund*. Best-effort —
            # if the signals can't be computed we fall back to size ordering
            # and the plain drift reason (no fabricated justification).
            try:
                await _attach_trim_signals(user_id, bucket_holdings, holdings)
            except Exception as e:  # noqa: BLE001
                logger.warning("rule6 trim-signal enrichment failed (%s); size order", e)
            # Cap to top-N ranked so we don't emit 5 SGB rows when one trim
            # idea is enough; the largest absorb most of the cut anyway.
            in_bucket = _composite_trim_order(bucket_holdings)[:_MAX_TRIMS_PER_BUCKET]
            remaining = delta_rs
            n = len(in_bucket)
            for idx, h in enumerate(in_bucket):
                if remaining <= _MIN_ACTION_RS:
                    break
                # Distribute the cut across the ranked holdings —
                # ~delta/n each, capped at 50% of the holding's value.
                fair_share = remaining / max(1, n)
                cut = min(h["value"] * 0.5, fair_share, remaining)
                if cut < _MIN_ACTION_RS:
                    continue
                codes = ["ASSET_CLASS_DRIFT", f"{bucket.upper()}_OVERWEIGHT"]
                # Only the top-ranked (worst) holding carries the "why this
                # fund" rationale; siblings just share the drift sentence.
                suffix = _trim_reason_suffix(h) if idx == 0 else ""
                if idx == 0 and h.get("_decider"):
                    codes.append(f"TRIM_RANK_{h['_decider'].upper()}")
                actions.append(ProposedAction(
                    type="TRIM",
                    asset_name=h["name"],
                    amount_rs=cut,
                    reason_codes=codes,
                    reason_text=(
                        f"{bucket.title()} is {row.deviation_pp:+.1f}pp above target "
                        f"({row.current_pct:.0f}% vs {row.target_pct:.0f}%); trim to free ₹{cut:,.0f}."
                        f"{suffix}"
                    ),
                    bucket=bucket,
                    rule="Rule 6",
                    priority=prio,
                    score=score,
                ))
                remaining -= cut
                n -= 1
        elif row.direction == "underweight":
            asset_name = {
                "equity": "Diversified large/flexi-cap fund",
                "debt": "Investment-grade corporate bond fund",
                "gold": "Sovereign Gold Bond / Gold ETF",
            }.get(bucket, f"{bucket} allocation top-up")
            codes = ["ASSET_CLASS_DRIFT", f"{bucket.upper()}_UNDERWEIGHT"]
            extra = ""
            disclaimer = ""
            # Debt: name a specific top-ranked fund (live DaaS, static fallback)
            # instead of a generic category placeholder.
            if bucket == "debt":
                fund = await _suggest_debt_add_fund(delta_rs)
                if fund:
                    asset_name = fund.get("fund_name") or asset_name
                    bits = [b for b in (
                        fund.get("rating"),
                        (f"3Y {fund.get('returns_3y')}" if fund.get("returns_3y") else None),
                        (f"{fund.get('fund_type')}" if fund.get("fund_type") else None),
                        (f"expense {fund.get('expense_ratio')}%"
                         if fund.get("expense_ratio") is not None else None),
                    ) if b]
                    extra = f" {asset_name} is a top-ranked option" + (
                        f" ({', '.join(str(b) for b in bits)})" if bits else "") + "."
                    codes.append("DEBT_ADD_NAMED")
                    disclaimer = _ADVICE_DISCLAIMER
            actions.append(ProposedAction(
                type="ADD",
                asset_name=asset_name,
                amount_rs=delta_rs,
                reason_codes=codes,
                reason_text=(
                    f"{bucket.title()} is {row.deviation_pp:+.1f}pp below target "
                    f"({row.current_pct:.0f}% vs {row.target_pct:.0f}%); top up by ₹{delta_rs:,.0f}."
                    f"{extra}{disclaimer}"
                ),
                bucket=bucket,
                rule="Rule 6",
                priority=prio,
                score=score,
            ))
    return actions


async def _suggest_debt_add_fund(amount_rs: float) -> Optional[Dict[str, Any]]:
    """Top debt-fund candidate for an ADD: live NIDP DaaS screener when up,
    static fallback otherwise (reuses allocation_engine._suggest_debt_funds, the
    same mechanism the reinvest card uses). Best-effort — returns None on error."""
    live: List[Dict[str, Any]] = []
    try:
        from services.copilot_tools import daas_client as _daas
        live = await _daas.get_top_add_funds_by_category("debt", n=3)
    except Exception as e:  # noqa: BLE001
        logger.debug("rule6 debt DaaS fetch failed: %s", e)
    try:
        from services.recommendation_engine.engines.allocation_engine import _suggest_debt_funds
        opts = _suggest_debt_funds(amount_rs, [], live, top_n=1)
        return opts[0] if opts else None
    except Exception as e:  # noqa: BLE001
        logger.debug("rule6 _suggest_debt_funds failed: %s", e)
        return None


def _sector_lookthrough(intel: Dict[str, Any], sector: str):
    """Per-fund and per-stock ₹ attribution for one look-through sector, from
    the user's OWN portfolio (catalog holdings × fund amount). Returns
    ``(top_funds, top_stocks)`` — each a list of ``(name, rs)`` sorted desc.
    Lets a sector-cap card say *which* of your funds/stocks drive the exposure
    rather than the generic "funds with high X exposure"."""
    mfs = (intel or {}).get("mf_investments") or []
    catalog = (intel or {}).get("catalog") or {}
    fund_rs: List[tuple] = []
    stock_rs: Dict[str, float] = {}
    for inv in mfs:
        if not inv.get("resolved"):
            continue
        cat = catalog.get(inv.get("instrument_id"), {})
        amt = float(inv.get("amount_rs") or 0)
        f_rs = 0.0
        for h in cat.get("holdings", []):
            if (h.get("holding_sector") or "") == sector:
                contrib = amt * (float(h.get("weight_percent") or 0) / 100.0)
                f_rs += contrib
                nm = h.get("holding_name") or "Unknown"
                stock_rs[nm] = stock_rs.get(nm, 0.0) + contrib
        if f_rs > 0:
            fund_rs.append((cat.get("scheme_name") or inv.get("scheme_name") or "a fund", f_rs))
    fund_rs.sort(key=lambda x: x[1], reverse=True)
    top_stocks = sorted(stock_rs.items(), key=lambda x: x[1], reverse=True)
    return fund_rs, top_stocks


# ── Rule 7: sector cap (>30% of equity exposure) ───────────────────────
async def _rule7_sector_cap(user_id: str) -> List[ProposedAction]:
    try:
        from services import portfolio_intelligence as _pi
        m = await _pi.compute_portfolio_intelligence(user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("rule7 sector data unavailable: %s", e)
        return []
    sector_exp = (m or {}).get("sector_exposure") or []
    if not sector_exp:
        return []

    # Total sector AUM (sum of look-through sector ₹) so we can size
    # the trim action proportionally to the over-cap excess.
    total_rs = sum(float(s.get("rs") or 0) for s in sector_exp)
    if total_rs <= 0:
        return []

    actions: List[ProposedAction] = []
    for s in sector_exp:
        pct = float(s.get("pct") or 0)
        if pct <= _SECTOR_CAP_PCT:
            continue
        excess_pp = pct - _SECTOR_CAP_PCT
        excess_rs = excess_pp / 100.0 * total_rs
        if excess_rs < _MIN_ACTION_RS:
            continue
        prio = "high" if excess_pp >= 5 else "medium"
        sector = s.get("sector")
        # Name which of the user's own funds (and the underlying stocks) drive
        # this sector, so the card says *what to reduce* — not just "funds with
        # high X exposure". This is the user's own portfolio data, not a buy rec.
        top_funds, top_stocks = _sector_lookthrough(m, sector)
        codes = ["SECTOR_CAP_BREACH", f"SECTOR_{(sector or '').upper()}"]
        attribution = ""
        disclaimer = ""
        if top_funds:
            fund_bits = "; ".join(f"{n} (₹{rs:,.0f})" for n, rs in top_funds[:2])
            attribution = f" Most of it comes from {fund_bits}"
            if top_stocks:
                attribution += f" — concentrated in {', '.join(n for n, _ in top_stocks[:3])}"
            attribution += ". Trimming these brings it under the cap."
            codes.append("SECTOR_LOOKTHROUGH")
            disclaimer = _ADVICE_DISCLAIMER
        actions.append(ProposedAction(
            type="TRIM",
            asset_name=f"Funds with high {sector} exposure",
            amount_rs=excess_rs,
            reason_codes=codes,
            reason_text=(
                f"{sector} exposure is {pct:.1f}% (cap {_SECTOR_CAP_PCT:.0f}%); "
                f"trim ₹{excess_rs:,.0f} to bring it under the cap."
                f"{attribution}{disclaimer}"
            ),
            bucket=sector,
            rule="Rule 7",
            priority=prio,
            score=7.0 if prio == "high" else 5.5,
        ))
    return actions


# ── Rule 8: market-cap / category concentration (>40% in one bucket) ───
async def _rule8_category_cap(user_id: str) -> List[ProposedAction]:
    from deps import db
    holdings = await db.holdings.find(
        {"user_id": user_id}, {"_id": 0, "name": 1, "asset_type": 1,
                                "quantity": 1, "current_price": 1, "sector": 1},
    ).to_list(500)
    if not holdings:
        return []
    by_cat: Dict[str, float] = {}
    grand = 0.0
    for h in holdings:
        if (h.get("asset_type") or "").lower() not in ("mutual_fund", "mf", "etf"):
            continue
        v = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        if v <= 0:
            continue
        cat = (h.get("sector") or "Uncategorised").strip()
        by_cat[cat] = by_cat.get(cat, 0.0) + v
        grand += v
    if grand <= 0:
        return []
    actions: List[ProposedAction] = []
    for cat, val in by_cat.items():
        pct = val / grand * 100
        if pct <= _CATEGORY_CAP_PCT:
            continue
        excess_pp = pct - _CATEGORY_CAP_PCT
        excess_rs = excess_pp / 100.0 * grand
        if excess_rs < _MIN_ACTION_RS:
            continue
        prio = "medium" if excess_pp >= 10 else "low"
        actions.append(ProposedAction(
            type="TRIM",
            asset_name=f"{cat} category funds (consolidate)",
            amount_rs=excess_rs,
            reason_codes=["CATEGORY_CAP_BREACH", f"CATEGORY_{cat.upper()}"],
            reason_text=(
                f"{cat} is {pct:.1f}% of MF AUM (cap {_CATEGORY_CAP_PCT:.0f}%); "
                f"trim ₹{excess_rs:,.0f} or rotate into under-allocated categories."
            ),
            bucket=cat,
            rule="Rule 8",
            priority=prio,
            score=5.5 if prio == "medium" else 4.0,
        ))
    return actions


# ── Public API: full sweep ─────────────────────────────────────────────
async def generate_actions(user_id: str) -> List[ProposedAction]:
    """Run all three rules in parallel and return a deduplicated,
    priority-ordered list. Asset-class drift (Rule 6) is the
    foundational rule; sector / category caps refine it."""
    import asyncio
    r6, r7, r8 = await asyncio.gather(
        _rule6_asset_class_drift(user_id),
        _rule7_sector_cap(user_id),
        _rule8_category_cap(user_id),
        return_exceptions=True,
    )
    out: List[ProposedAction] = []
    for batch in (r6, r7, r8):
        if isinstance(batch, list):
            out.extend(batch)
    # Sort: ADDs last, TRIMs first; within each, larger amounts first.
    type_rank = {"EXIT": 0, "TRIM": 1, "ADD": 2}
    out.sort(key=lambda a: (type_rank.get(a.type, 3), -a.amount_rs))
    return out
