"""Tiered Tax Engine — Phase 1: tax-AWARE, not tax-PRECISE.

Architecture (per user spec, 2026-04-30):

  Tier 1 (NOW)  — heuristic, ranking-based. No buy_date required.
  Tier 2 (LATER) — partial data: split holdings into long/short buckets
                   weighted by estimated holding period.
  Tier 3 (FUTURE) — full FIFO from broker / CAS-transaction trade data.

What this module ships:

  • `classify_holding(h)`           → LIKELY_LTCG / LIKELY_STCG / UNKNOWN
                                       with HIGH / MEDIUM / LOW confidence.
  • `loss_harvesting_candidates`    → unrealized-loss positions ordered
                                       by ₹ loss (largest first).
  • `rank_sell_candidates`          → priority-ranked exit list:
                                       1) losses → 2) low-gain LTCG
                                       → 3) low-gain STCG → 4) high-gain LTCG
                                       → 5) high-gain STCG.
  • `compute_tax_profile`           → portfolio-level data-quality summary.

Design tenets:
  • Honest framing — never say "you'll pay ₹X tax". Say "low tax impact"
    or "high tax impact" with a confidence tag.
  • Use what we have — buy_date when present, uploaded_at/created_at
    as proxy "first seen" date when not, mark UNKNOWN when neither
    works AND the cost basis is itself a placeholder.
  • Asset-class aware thresholds — equity/MF: 365d, debt: 1095d,
    gold/SGB: 1095d. Override per holding if SEBI category present.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from deps import db

logger = logging.getLogger(__name__)


# ── LT-bucket thresholds (days) per asset class ────────────────────────
# Indian tax regime as of FY 2024-25.
_LT_THRESHOLD_DAYS: Dict[str, int] = {
    "equity": 365,
    "mutual_fund": 365,    # equity MF default — overridden for debt
    "etf": 365,
    "gold": 1095,          # SGB / gold ETF: 36 months for LTCG
    "debt": 1095,
    "bond": 1095,
}
_DEBT_NAME_MARKERS = (
    "liquid", "debt", "bond", "gilt", "corporate", "short term",
    "ultra short", "money market", "low duration", "savings",
    "overnight", "income",
)


def _is_debt_fund(name: str) -> bool:
    n = (name or "").lower()
    return any(m in n for m in _DEBT_NAME_MARKERS)


def _lt_threshold_for(holding: Dict[str, Any]) -> int:
    at = (holding.get("asset_type") or "").lower()
    base = _LT_THRESHOLD_DAYS.get(at, 365)
    if at in ("mutual_fund", "mf", "etf") and _is_debt_fund(holding.get("name", "")):
        return _LT_THRESHOLD_DAYS["debt"]
    return base


# ── Public dataclasses ────────────────────────────────────────────────
@dataclass
class TaxClassification:
    tier: str                              # "LIKELY_LTCG" | "LIKELY_STCG" | "UNKNOWN"
    estimated_holding_days: Optional[int]
    threshold_days: int
    confidence: str                        # "HIGH" | "MEDIUM" | "LOW"
    reason: str


@dataclass
class TaxScore:
    holding_id: Optional[str]
    name: str
    asset_type: str
    quantity: float
    invested_rs: float
    current_rs: float
    gain_rs: float
    return_pct: float
    classification: TaxClassification
    sell_priority: int                     # 1 (best) … 5 (avoid)
    sell_priority_label: str               # human-readable
    relative_tax_impact: str               # "loss / nil" | "low" | "medium" | "high"
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "holding_id": self.holding_id,
            "name": self.name,
            "asset_type": self.asset_type,
            "quantity": self.quantity,
            "invested_rs": round(self.invested_rs, 0),
            "current_rs": round(self.current_rs, 0),
            "gain_rs": round(self.gain_rs, 0),
            "return_pct": round(self.return_pct, 2),
            "tax_tier": self.classification.tier,
            "tax_confidence": self.classification.confidence,
            "estimated_holding_days": self.classification.estimated_holding_days,
            "tax_classification_reason": self.classification.reason,
            "sell_priority": self.sell_priority,
            "sell_priority_label": self.sell_priority_label,
            "relative_tax_impact": self.relative_tax_impact,
            "rationale": self.rationale,
        }


# ── Date parsing helpers ───────────────────────────────────────────────
def _parse_date(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        s = str(value).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def classify_holding(h: Dict[str, Any]) -> TaxClassification:
    """Estimate LT/ST classification for a single holding doc."""
    threshold = _lt_threshold_for(h)
    today = datetime.now(timezone.utc)

    # 1. buy_date — gold standard
    buy_dt = _parse_date(h.get("buy_date"))
    if buy_dt:
        age = (today - buy_dt).days
        tier = "LIKELY_LTCG" if age >= threshold else "LIKELY_STCG"
        return TaxClassification(
            tier=tier, estimated_holding_days=age,
            threshold_days=threshold, confidence="HIGH",
            reason=f"buy_date present ({age}d held vs {threshold}d threshold)",
        )

    # 2. Cost-basis sanity — placeholder cost basis means we can't
    # trust the gain calc either; mark UNKNOWN.
    bp = float(h.get("buy_price") or 0)
    cp = float(h.get("current_price") or 0)
    if bp == 0 or (abs(bp - cp) < 0.005):
        return TaxClassification(
            tier="UNKNOWN", estimated_holding_days=None,
            threshold_days=threshold, confidence="LOW",
            reason="placeholder cost basis — neither holding period nor gain reliable",
        )

    # 3. Fallback to uploaded_at / created_at as "first seen" proxy.
    proxy_dt = _parse_date(h.get("uploaded_at")) or _parse_date(h.get("created_at"))
    if proxy_dt:
        age = (today - proxy_dt).days
        # Conservative: only flag LTCG if proxy age clears threshold by
        # a wide margin (≥ threshold + 60d). Otherwise STCG with MEDIUM
        # confidence — we'd rather classify a real LTCG as STCG than
        # the reverse (avoids the user thinking they'll pay less tax
        # than they actually will).
        if age >= threshold + 60:
            tier = "LIKELY_LTCG"
            conf = "MEDIUM"
            reason = (f"proxy holding age ({age}d) clearly past {threshold}d "
                      f"threshold; using first-seen as buy date")
        else:
            tier = "LIKELY_STCG"
            conf = "MEDIUM"
            reason = (f"proxy holding age ({age}d) within / near {threshold}d "
                      f"threshold — assuming STCG conservatively")
        return TaxClassification(
            tier=tier, estimated_holding_days=age,
            threshold_days=threshold, confidence=conf, reason=reason,
        )

    return TaxClassification(
        tier="UNKNOWN", estimated_holding_days=None,
        threshold_days=threshold, confidence="LOW",
        reason="no buy_date and no first-seen timestamp",
    )


# ── Dashboard adapter ──────────────────────────────────────────────────
def card_tax_block(holding: Dict[str, Any], invested: float, current_value: float) -> Optional[Dict[str, Any]]:
    """Build a compact tax block for a `performance_cards` row.

    Pure function — never raises. Returns ``None`` when classification fails.
    Contract consumed by the dashboard Action Matrix ("Tax Watch" bucket and
    inline STCG/LTCG badges) — keep the keys stable.
    """
    try:
        tc = classify_holding(holding)
    except Exception:  # noqa: BLE001
        return None
    days = tc.estimated_holding_days
    threshold = tc.threshold_days
    days_to_ltcg = (threshold - days) if (days is not None and days < threshold) else 0
    return {
        "tier": tc.tier,                 # LIKELY_LTCG / LIKELY_STCG / UNKNOWN
        "confidence": tc.confidence,     # HIGH / MEDIUM / LOW
        "days_held": days,
        "threshold_days": threshold,
        "days_to_ltcg": days_to_ltcg,
        "is_loss": current_value < invested,
    }


# ── Helpers shared between retrievers ─────────────────────────────────
async def _enriched_holdings(user_id: str) -> List[Dict[str, Any]]:
    rows = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
    enriched: List[Dict[str, Any]] = []
    for h in rows:
        qty = float(h.get("quantity") or 0)
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        inv = qty * bp
        cur = qty * cp
        gain = cur - inv
        ret = (gain / inv * 100) if inv > 0 else 0.0
        enriched.append({
            **h,
            "_qty": qty, "_invested": inv, "_current": cur,
            "_gain": gain, "_ret_pct": ret,
        })
    return enriched


def _score_for_sell(h: Dict[str, Any]) -> TaxScore:
    """Rank a holding for sell preference. Lower priority number = more
    attractive to sell (lower tax friction)."""
    cls = classify_holding(h)
    gain = h["_gain"]
    ret = h["_ret_pct"]
    name = h.get("name") or "Unknown"
    at = (h.get("asset_type") or "").lower()
    qty = h["_qty"]
    inv = h["_invested"]
    cur = h["_current"]

    # Priority bands (lower number = sell first)
    # 1: any loss (harvest!) — always priority 1 regardless of LT/ST
    # 2: small-gain LTCG (≤5% return) — minimal tax
    # 3: small-gain STCG (≤5%) — small absolute tax
    # 4: medium-gain LTCG (5-25%) — modest tax, may be ≤₹1L exemption
    # 5: high-gain STCG OR high-gain LTCG (>25%) — avoid unless required
    # UNKNOWN classification: bumped one band toward "avoid" because
    # we can't promise low tax.
    if gain < 0:
        prio = 1
        label = "harvest a loss"
        impact = "loss / nil"
        rationale = f"unrealized loss ₹{gain:+,.0f} ({ret:+.1f}%) — exit offsets future gains"
    else:
        is_ltcg = cls.tier == "LIKELY_LTCG"
        is_unknown = cls.tier == "UNKNOWN"
        if ret <= 5:
            base_prio = 2 if is_ltcg else 3
            label = "low-gain · " + ("LTCG" if is_ltcg else "STCG/unknown")
            impact = "low"
            rationale = f"only {ret:+.1f}% gain — minimal tax friction"
        elif ret <= 25:
            base_prio = 4
            label = "medium-gain · " + ("LTCG" if is_ltcg else "STCG/unknown")
            impact = "medium"
            rationale = f"{ret:+.1f}% gain — moderate tax on exit"
        else:
            base_prio = 5
            label = "high-gain · " + ("LTCG" if is_ltcg else "STCG/unknown")
            impact = "high"
            rationale = f"{ret:+.1f}% gain — large taxable event on exit"
        # UNKNOWN classification can only be used when nothing better
        # exists — bump toward avoid.
        prio = min(5, base_prio + (1 if is_unknown else 0))

    return TaxScore(
        holding_id=h.get("holding_id"),
        name=name, asset_type=at, quantity=qty,
        invested_rs=inv, current_rs=cur, gain_rs=gain, return_pct=ret,
        classification=cls,
        sell_priority=prio, sell_priority_label=label,
        relative_tax_impact=impact, rationale=rationale,
    )


# ── Public API ─────────────────────────────────────────────────────────
async def loss_harvesting_candidates(user_id: str) -> List[TaxScore]:
    """All positions in unrealized loss, sorted by ₹ loss (largest first).
    These are the highest-leverage tax moves: harvest the loss to offset
    realized gains in the same FY.

    Tier upgrade: when the FIFO engine has CAS-transaction-backed lots
    for a symbol, we surface PER-LOT losses (a holding that's net-
    positive but has 6 SIP installments in the red still gets those
    6 lots flagged). Falls back to the Phase-1 holding-level heuristic
    for symbols without trade history.
    """
    enriched = await _enriched_holdings(user_id)
    losers: List[TaxScore] = []

    # Try Tier-2 FIFO first
    fifo_lot_keys: set = set()
    try:
        from services import tax_engine_fifo as _tef
        state = await _tef.build_user_tax_state(user_id)
        if state.n_transactions > 0:
            cur_prices = state.harvesting._current_prices  # noqa: SLF001
            opps = state.harvesting.identify_losses(cur_prices)
            for o in opps:
                # Promote each loss-lot to a TaxScore record so the
                # caller's downstream pipeline keeps working unchanged.
                cls = TaxClassification(
                    tier=("LIKELY_LTCG" if o["bucket_if_sold_today"] == "LTCG"
                          else "LIKELY_STCG"),
                    estimated_holding_days=o["holding_days"],
                    threshold_days=365,
                    confidence="HIGH",
                    reason=(f"FIFO lot from CAS — buy_date {o['buy_date']}, "
                            f"{o['holding_days']}d held"),
                )
                qty = float(o["qty"])
                inv = qty * float(o["buy_price"])
                cur = qty * float(o["current_price"])
                ret = ((cur - inv) / inv * 100) if inv > 0 else 0.0
                losers.append(TaxScore(
                    holding_id=None,
                    name=(o.get("scheme_name") or o["symbol"]),
                    asset_type="mutual_fund",
                    quantity=qty, invested_rs=inv, current_rs=cur,
                    gain_rs=float(o["loss_rs"]), return_pct=ret,
                    classification=cls,
                    sell_priority=1,
                    sell_priority_label=f"harvest a loss · {o['bucket_if_sold_today']} lot",
                    relative_tax_impact="loss / nil",
                    rationale=(
                        f"unrealized loss ₹{o['loss_rs']:+,.0f} on a "
                        f"{o['holding_days']}d-old SIP lot — "
                        f"{o['bucket_if_sold_today']} on exit"
                    ),
                ))
                fifo_lot_keys.add(o["symbol"])
    except Exception as e:  # noqa: BLE001
        logger.warning("FIFO loss harvesting failed for %s: %s", user_id, e)

    # Phase-1 fallback for symbols without FIFO coverage
    for h in enriched:
        if h.get("isin") in fifo_lot_keys or h.get("ticker") in fifo_lot_keys:
            continue
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        if bp <= 0 or (abs(bp - cp) < 0.005 and not h.get("buy_date")):
            continue
        if h["_gain"] < 0:
            losers.append(_score_for_sell(h))

    losers.sort(key=lambda s: s.gain_rs)  # most negative first
    return losers


async def rank_sell_candidates(
    user_id: str, target_amount_rs: Optional[float] = None,
) -> List[TaxScore]:
    """Priority-ranked sell list. If `target_amount_rs` is given, the
    cumulative `current_rs` is tracked and we return enough rows to
    cover it (with a small overshoot)."""
    enriched = await _enriched_holdings(user_id)
    scores: List[TaxScore] = []
    for h in enriched:
        bp = float(h.get("buy_price") or 0)
        cp = float(h.get("current_price") or 0)
        if bp <= 0 or (abs(bp - cp) < 0.005 and not h.get("buy_date")):
            # Placeholder-cost-basis rows can still be sold; mark them
            # explicitly UNKNOWN-tier so they rank low.
            pass
        scores.append(_score_for_sell(h))
    # Sort: priority asc, then by largest current_rs (so big positions
    # contribute most when raising a target amount).
    scores.sort(key=lambda s: (s.sell_priority, -s.current_rs))
    if target_amount_rs is None:
        return scores
    out: List[TaxScore] = []
    running = 0.0
    for s in scores:
        if running >= target_amount_rs:
            break
        out.append(s)
        running += s.current_rs
    return out


async def compute_tax_profile(user_id: str) -> Dict[str, Any]:
    """Portfolio-level data-quality summary. Powers the 'tax confidence'
    badge so the user knows whether our suggestions are based on real
    buy dates or proxies."""
    enriched = await _enriched_holdings(user_id)
    if not enriched:
        return {"data_quality": "NONE", "n_holdings": 0,
                "summary": "no holdings recorded"}
    by_conf = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_tier = {"LIKELY_LTCG": 0, "LIKELY_STCG": 0, "UNKNOWN": 0}
    losers = 0
    for h in enriched:
        cls = classify_holding(h)
        by_conf[cls.confidence] = by_conf.get(cls.confidence, 0) + 1
        by_tier[cls.tier] = by_tier.get(cls.tier, 0) + 1
        if h["_gain"] < 0:
            losers += 1
    n = len(enriched)
    high_pct = by_conf["HIGH"] / n * 100 if n else 0
    medium_pct = by_conf["MEDIUM"] / n * 100 if n else 0
    if high_pct >= 70:
        quality = "HIGH"
    elif high_pct + medium_pct >= 60:
        quality = "MEDIUM"
    else:
        quality = "LOW"
    return {
        "data_quality": quality,
        "n_holdings": n,
        "by_confidence": by_conf,
        "by_tier": by_tier,
        "n_loss_positions": losers,
        "summary": (
            f"{n} holdings · {by_conf['HIGH']} HIGH-conf / "
            f"{by_conf['MEDIUM']} MEDIUM / {by_conf['LOW']} LOW-conf · "
            f"{losers} in loss"
        ),
    }
