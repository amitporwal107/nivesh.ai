"""
OverlapEngine — Rules 4 + 9: EXIT when two funds have high stock overlap.

OV-1 (Rule 4): Exit the weaker fund when overlap > 70% (consolidation candidate).
               Uses canonical keep_score from survivor.py to decide which fund to exit.
OV-2 (Rule 4): Emit lower-priority signal when 40–70% overlap (cleanup item).
               Threshold drops to 40% when exit proceeds can fill an allocation gap.
Rule 9: Suggest a smart reinvestment using exit proceeds.
        Priority order: fill largest allocation gap (debt/gold/international)
        first; fall back to static complement category if no gap found.

Tax harvesting: EXIT signals annotate whether the exit is tax-efficient
(LTCG ≤ ₹1L exempt, loss-booking, or STCG within budget).

Keep score delegates to services.recommendation_engine.survivor.raw_signals +
normalize_signals_batch + keep_score_normalized (normalized, D-2 weights).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from services.recommendation_engine.base_engine import BaseEngine
from services.recommendation_engine.context import EngineSignal, RecommendationContext
from services.recommendation_engine.helpers import (
    fuzzy_match_holding,
    infer_category_from_name,
    normalize_base_scheme_name,
    normalize_fund_name,
)

logger = logging.getLogger(__name__)

# Minimum allocation gap (pp) before we treat an exit as a reinvestment opportunity.
_MIN_GAP_PP = 5.0
# Minimum international exposure gap (%) to suggest topping up international.
_MIN_INTL_GAP_PCT = 5.0


def _detect_allocation_gaps(ctx: RecommendationContext) -> List[Dict[str, Any]]:
    """Return a sorted list of meaningful allocation underweights in the portfolio.

    Each entry: {"bucket": str, "gap_pp": float, "label": str}
    Covers debt, gold, and international exposure.
    Sorted by gap_pp descending (biggest gap first).
    """
    gaps: List[Dict[str, Any]] = []

    # ── 1. Structural gaps from deviation engine (debt / gold) ────────────────
    dr = ctx.deviation_result
    if dr is not None:
        for row in dr.rows:
            bucket = (row.asset or "").lower()
            gap = row.target_pct - row.current_pct  # positive = underweight
            if bucket in ("debt", "gold") and gap >= _MIN_GAP_PP:
                gaps.append({
                    "bucket": bucket,
                    "gap_pp": round(gap, 1),
                    "current_pct": round(row.current_pct, 1),
                    "target_pct": round(row.target_pct, 1),
                    "label": "Debt" if bucket == "debt" else "Gold",
                })

    # ── 2. International exposure gap ─────────────────────────────────────────
    try:
        from services import international_funds as _intl
        total = ctx.total_value_rs or 1.0
        intl_value = sum(
            float(m.get("quantity") or 0) * float(m.get("current_price") or 0)
            for m in ctx.mf_holdings
            if _intl.classify_international(
                m.get("name") or m.get("scheme_name") or "",
                m.get("category") or "",
            ) is not None
        )
        current_intl_pct = intl_value / total * 100.0
        target_info = _intl.compute_target_international_pct(risk_profile=ctx.risk_profile.lower())
        target_intl_pct = float(target_info.get("pct", 0))
        intl_gap = target_intl_pct - current_intl_pct
        if intl_gap >= _MIN_INTL_GAP_PCT:
            gaps.append({
                "bucket": "international",
                "gap_pp": round(intl_gap, 1),
                "current_pct": round(current_intl_pct, 1),
                "target_pct": round(target_intl_pct, 1),
                "label": "International",
            })
    except Exception:  # noqa: BLE001
        pass

    gaps.sort(key=lambda g: g["gap_pp"], reverse=True)
    return gaps


def _reinvestment_from_gap(
    gap: Dict[str, Any],
    amount_rs: float,
    ctx: RecommendationContext,
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """Given a gap dict, return (instrument_name, reason_fragment, fund_details_or_None)."""
    bucket = gap["bucket"]
    gap_pp = gap["gap_pp"]
    current_pct = gap["current_pct"]
    target_pct = gap["target_pct"]

    if bucket == "debt":
        live_debt = ctx.top_add_candidates.get("debt") or []
        from services.recommendation_engine.engines.allocation_engine import _suggest_debt_funds
        options = _suggest_debt_funds(amount_rs, [], live_debt, top_n=3)
        best = options[0]
        name = best["fund_name"]
        reason = (
            f"Debt is {current_pct:.0f}% — {gap_pp:.0f}pp below your {target_pct:.0f}% target. "
            f"Reinvesting exit proceeds into {name} closes this gap without triggering tax."
        )
        return name, reason, {"fund_details": best, "fund_options": options}

    if bucket == "gold":
        # Use the gold fund suggestion from action_plan_manager pattern
        gold_funds = [
            {"fund_name": "HDFC Gold ETF", "fund_type": "Gold ETF", "amc": "HDFC",
             "expense_ratio": 0.59, "aum": "₹3,200 Cr"},
            {"fund_name": "SBI Gold Fund - Direct Growth", "fund_type": "Gold Fund", "amc": "SBI",
             "expense_ratio": 0.14, "aum": "₹2,100 Cr"},
        ]
        best = gold_funds[0] if amount_rs >= 100_000 else gold_funds[1]
        name = best["fund_name"]
        reason = (
            f"Gold is {current_pct:.0f}% — {gap_pp:.0f}pp below your {target_pct:.0f}% target. "
            f"Adding {name} (Gold ETF) provides inflation hedge and lowers portfolio correlation."
        )
        return name, reason, {"fund_details": best, "fund_options": gold_funds}

    if bucket == "international":
        best_intl = None
        try:
            from services import international_funds as _intl
            for f in ctx.international_funds_cache:
                if (
                    _intl._band_for(_intl._quality_score(f)) == "core"
                    and (
                        best_intl is None
                        or _intl._quality_score(f) > _intl._quality_score(best_intl)
                    )
                ):
                    best_intl = f
        except Exception:  # noqa: BLE001
            pass
        name = (best_intl or {}).get("scheme_name") or "An international fund of funds"
        reason = (
            f"International exposure is {current_pct:.0f}% — {gap_pp:.0f}pp below target. "
            f"Reinvesting into {name} reduces India-concentration risk."
        )
        fund_details = {
            "fund_name": name,
            "fund_type": "International Fund of Funds",
            "bucket": (best_intl or {}).get("bucket", "Global"),
            "expense_ratio": (best_intl or {}).get("expense_ratio_direct"),
            "ret_3y": (best_intl or {}).get("ret_3y"),
        } if best_intl else {"fund_name": name, "fund_type": "International Fund of Funds"}
        return name, reason, {"fund_details": fund_details}

    return gap["label"] + " Fund", f"Reinvest into {gap['label']} to close the {gap_pp:.0f}pp gap.", None


def _tax_harvest_label(victim_cand: Optional[Dict[str, Any]], amount_rs: float) -> Optional[str]:
    """Return a tax note if the exit is free or low-cost (LTCG ≤ ₹1L or a loss)."""
    if not victim_cand:
        return None
    vti = victim_cand.get("tax_impact") or {}
    gain = float(vti.get("gain_rs") or vti.get("capital_gain_rs") or 0)
    gain_type = (vti.get("gain_type") or "").upper()
    tax = float(vti.get("tax_liability") or 0)

    if gain <= 0:
        return "loss-booking opportunity — no tax on exit"
    if gain_type == "LTCG" and gain <= 100_000:
        return f"LTCG ₹{gain:,.0f} within ₹1L exempt limit — tax-free exit"
    if tax > 0 and (tax / amount_rs) < 0.01:
        return f"tax cost <1% of exit value (₹{tax:,.0f})"
    return None


def _ov3_keep_score(iid: Optional[str], v3_scores: Dict[str, Any]) -> float:
    """Thin wrapper — delegates to the canonical survivor.keep_score.

    For pairwise comparisons (OV-1/OV-2) where we only have two funds,
    normalize across just those two using select_survivors' internal logic.
    Returns a comparable float; higher = better fund to keep.
    """
    from services.recommendation_engine.survivor import raw_signals, normalize_signals_batch, keep_score_normalized
    raw = raw_signals(iid, v3_scores)
    # Single-fund normalization: normalize against itself → 0.5 neutral; used only for ordering
    normed_list, overlap_available = normalize_signals_batch([raw])
    return keep_score_normalized(normed_list[0], overlap_available)

# Complementary category map: when exiting a fund in key category,
# suggest adding one from the value category.
_COMPLEMENT_CATEGORIES = {
    "Large Cap": "Small Cap",
    "Large & Mid Cap": "Small Cap",
    "Multi Cap": "Flexi Cap",
    "Flexi Cap": "International",
    "Mid Cap": "Debt",
    "Small Cap": "Debt",
    "Hybrid": "Debt",
}


def _holding_key(h: Dict[str, Any]) -> str:
    return f"{h.get('user_id','')}::{normalize_fund_name(h.get('name',''))}"


class OverlapEngine(BaseEngine):
    """Rules 4 + 9 (P1): High overlap → exit weaker fund; optionally suggest complement."""

    engine_name = "OverlapEngine"
    enabled_config_key = "rule_4_different_fund_overlap.enabled"

    def generate(self, ctx: RecommendationContext) -> List[EngineSignal]:
        pairs = ctx.portfolio_intelligence.get("pairwise_overlap") or []
        if not pairs:
            return []

        r4_params = (ctx.rules_cfg.get("rule_4_different_fund_overlap") or {}).get("params", {})
        overlap_threshold = float(r4_params.get("overlap_threshold_pct", 70.0))    # OV-1
        overlap_moderate = float(r4_params.get("overlap_moderate_pct", 50.0))      # OV-2
        max_exits = int(r4_params.get("max_overlap_exits", 2))

        r9_enabled = (ctx.rules_cfg.get("rule_9_cross_category_overlap_replacement") or {}).get("enabled", True)
        r9_params = (ctx.rules_cfg.get("rule_9_cross_category_overlap_replacement") or {}).get("params", {})
        r9_max = int(r9_params.get("max_replacements", 2))

        signals: List[EngineSignal] = []
        local_exited_ids: set = set()
        local_exited_keys: set = set()
        overlap_exit_count = 0
        r9_count = 0

        candidate_by_id: Dict[str, Dict] = {
            c.get("instrument_id"): c for c in ctx.exit_candidates if c.get("instrument_id")
        }

        def _exit_rank(iid: Optional[str], scheme_name: Optional[str] = None) -> float:
            v3 = ctx.v3_scores.get(iid or "", {})
            if v3.get("exit_score") is not None:
                return float(v3["exit_score"])
            cand = candidate_by_id.get(iid or "")
            return float((cand or {}).get("exit_score", 5.0))

        # Detect allocation gaps once — used to lower thresholds and guide reinvestment.
        alloc_gaps = _detect_allocation_gaps(ctx)
        top_gap = alloc_gaps[0] if alloc_gaps else None
        has_gap = top_gap is not None

        # When there's a gap to fill, accept moderate overlap starting at 40% (vs 50%).
        effective_moderate = 40.0 if has_gap else overlap_moderate

        for pair in pairs:
            overlap_pct = float(pair.get("overlap_pct", 0))
            is_ov1 = overlap_pct >= overlap_threshold
            is_ov2 = not is_ov1 and overlap_pct >= effective_moderate

            if not is_ov1 and not is_ov2:
                continue
            if overlap_exit_count >= max_exits:
                break

            id_a, id_b = pair.get("a"), pair.get("b")
            name_a = pair.get("a_name", "")
            name_b = pair.get("b_name", "")

            # Skip regular/direct twins (handled by RegularDirectEngine)
            if normalize_base_scheme_name(name_a) == normalize_base_scheme_name(name_b):
                continue

            # Skip if either already marked for exit
            if (id_a in ctx.exited_ids or id_a in local_exited_ids or
                    id_b in ctx.exited_ids or id_b in local_exited_ids):
                continue

            # OV-3 Keep Score: exit the fund with the lower keep score
            keep_a = _ov3_keep_score(id_a, ctx.v3_scores)
            keep_b = _ov3_keep_score(id_b, ctx.v3_scores)

            if keep_a <= keep_b:
                victim_iid, victim_name, victim_cand, partner_name = id_a, name_a, candidate_by_id.get(id_a), name_b
            else:
                victim_iid, victim_name, victim_cand, partner_name = id_b, name_b, candidate_by_id.get(id_b), name_a

            score_a = _exit_rank(id_a, name_a)
            score_b = _exit_rank(id_b, name_b)

            # Tax cost assessment — used for both the gate and the reason text.
            tax_note: Optional[str] = None
            tax_pct = 0.0
            if victim_cand:
                vti = victim_cand.get("tax_impact") or {}
                tmp_h = fuzzy_match_holding(victim_name, ctx.mf_holdings)
                exit_amt = (vti.get("exit_amount_rs") or 0) or (
                    (tmp_h.get("quantity", 0) * tmp_h.get("current_price", 0)) if tmp_h else 0
                )
                tax_pct = ((vti.get("tax_liability") or 0) / exit_amt * 10) if exit_amt else 0
                proxy_score = (victim_cand.get("exit_score", 5.0) - 5.0) - tax_pct
                tax_note = _tax_harvest_label(victim_cand, exit_amt)
                # Proxy score gate: skip if exit is costly AND no allocation gap justifies it.
                # When there is a gap (exit proceeds will be redeployed), allow proxy_score ≤ 0
                # as long as the fund is not catastrophically expensive to exit (tax_pct < 5).
                if proxy_score <= 0 and not (has_gap and tax_pct < 5.0):
                    logger.debug(
                        "[OverlapEngine] SKIP — proxy_score=%.2f tax_pct=%.1f has_gap=%s for %s",
                        proxy_score, tax_pct, has_gap, victim_name[:40],
                    )
                    continue

            # Try to get consolidation_score_engine confidence
            confidence = 0.7
            try:
                from services.consolidation_score_engine import (
                    ConsolidationInput, FundSnapshot, score_pair
                )
                def _snap(iid: Optional[str]) -> Optional[FundSnapshot]:
                    cat = ctx.portfolio_intelligence.get("catalog", {}).get(iid or "", {})
                    r = cat.get("ratios", {}) if cat else {}
                    h = fuzzy_match_holding(
                        (ctx.portfolio_intelligence.get("mf_investments") or [{}])[0].get("scheme_name",""),
                        ctx.mf_holdings
                    ) or {}
                    return FundSnapshot(
                        scheme_code=iid or "",
                        name=(cat.get("scheme_name") or iid or ""),
                        current_value_rs=float(h.get("quantity",0)) * float(h.get("current_price",0)),
                        return_1y=r.get("ret_1y"),
                        return_3y=r.get("ret_3y"),
                        ter_pct=r.get("expense_ratio"),
                    )
                snap_a = _snap(id_a)
                snap_b = _snap(id_b)
                if snap_a and snap_b:
                    result = score_pair(ConsolidationInput(
                        fund_a=snap_a, fund_b=snap_b,
                        overlap_pct=float(pair.get("overlap_pct", overlap_threshold)),
                    ))
                    rec = result.recommendation
                    if rec in ("Consolidate Immediately", "Switch to One"):
                        confidence = 0.9
                    elif rec == "Consider Consolidation":
                        confidence = 0.6
                    elif rec == "Review":
                        confidence = 0.4
                    elif rec == "Keep Both":
                        continue
            except Exception:
                pass  # consolidation engine unavailable — use default confidence

            h = fuzzy_match_holding(victim_name, ctx.mf_holdings)
            if not h:
                continue
            h_key = _holding_key(h)
            if h_key in ctx.exited_holding_keys or h_key in local_exited_keys:
                continue

            amount_rs = float(h.get("quantity", 0)) * float(h.get("current_price", 0))
            overlap_pct = pair.get("overlap_pct", overlap_threshold)

            # ── Build EXIT signal ────────────────────────────────────────────
            if is_ov1:
                rule_label = "Rule 4 (OV-1)"
                reason_code = "OVERLAP_CONSOLIDATION"
                base_score = max(score_a, score_b)
                urgency = 0.4
                reason_text = (
                    f"High overlap ({overlap_pct:.1f}%, {pair.get('shared_count',0)} shared stocks) "
                    f"with {partner_name}. Consolidating by exiting the weaker fund "
                    f"(keep score {min(keep_a, keep_b):.1f}/10 vs {max(keep_a, keep_b):.1f}/10)."
                )
            else:
                # OV-2: moderate/actionable overlap — base score boosted when gap exists
                rule_label = "Rule 4 (OV-2)"
                reason_code = "OVERLAP_MODERATE"
                if has_gap:
                    # Lift score: exit is purposeful (proceeds go into a gap)
                    base_score = max(score_a, score_b) * 0.85
                    confidence = min(confidence, 0.65)
                    urgency = 0.35
                else:
                    base_score = max(score_a, score_b) * 0.6
                    confidence = min(confidence, 0.5)
                    urgency = 0.2
                reason_text = (
                    f"Moderate overlap ({overlap_pct:.1f}%, {pair.get('shared_count',0)} shared stocks) "
                    f"with {partner_name}. Consider exiting the weaker fund when tax window is favourable."
                )

            # Append tax note to reason
            if tax_note:
                reason_text += f" ({tax_note}.)"

            sig = EngineSignal(
                signal_id=f"overlap::{victim_iid or victim_name[:20]}",
                engine_name=self.engine_name,
                rule_label=rule_label,
                action_type="EXIT",
                instrument_id=victim_iid,
                instrument_name=victim_name,
                amount_rs=amount_rs,
                base_score=base_score,
                confidence=confidence,
                risk_reduction=0.5,
                diversification_gain=0.6,
                urgency=urgency,
                implementation_ease=0.5,
                reason_codes=[reason_code],
                reason_text=reason_text,
                dedup_key=f"EXIT::{victim_iid or victim_name[:30]}",
            )
            sig.__dict__["_holding"] = h
            sig.__dict__["_candidate"] = victim_cand
            if tax_note:
                sig.__dict__["_tax_note"] = tax_note

            # PI-2: compute weighted overlap = overlap_fraction × min(weight_victim, weight_partner)
            _wv = ctx.holding_weights.get(victim_iid or "") or ctx.holding_weights.get(normalize_fund_name(victim_name))
            _wp = ctx.holding_weights.get(id_a if victim_iid != id_a else id_b or "") or ctx.holding_weights.get(normalize_fund_name(name_a if victim_name != name_a else name_b))
            _w_vict = (_wv.weight_pct / 100.0) if _wv else 0.05
            _w_part = (_wp.weight_pct / 100.0) if _wp else 0.05
            sig.__dict__["_pi2_weighted_overlap"] = round((overlap_pct / 100.0) * min(_w_vict, _w_part), 4)

            signals.append(sig)

            local_exited_keys.add(h_key)
            if victim_iid:
                local_exited_ids.add(victim_iid)
            overlap_exit_count += 1

            # ── Rule 9: smart reinvestment using exit proceeds ────────────────
            # Priority: fill the largest allocation gap first (debt > gold > international).
            # Fall back to static complement category if no gap detected.
            if r9_enabled and r9_count < r9_max:
                add_sig: Optional[EngineSignal] = None

                if alloc_gaps:
                    # Use the top gap as reinvestment target
                    gap = alloc_gaps[0]
                    reinvest_name, reinvest_reason, fund_meta = _reinvestment_from_gap(
                        gap, amount_rs, ctx
                    )
                    r9_reason = (
                        f"After removing {victim_name[:40]} ({overlap_pct:.0f}% overlap with "
                        f"{partner_name[:40]}), reinvest ₹{amount_rs/100_000:.1f}L proceeds into "
                        f"{reinvest_name} — {reinvest_reason}"
                    )
                    add_sig = EngineSignal(
                        signal_id=f"overlap_r9::add::{gap['bucket']}",
                        engine_name=self.engine_name,
                        rule_label="Rule 9",
                        action_type="ADD",
                        instrument_id=None,
                        instrument_name=reinvest_name,
                        amount_rs=amount_rs,
                        base_score=base_score * 0.9,
                        confidence=confidence,
                        diversification_gain=0.8,
                        urgency=urgency,
                        reason_codes=["REBALANCE_ON_EXIT", f"GAP_{gap['bucket'].upper()}"],
                        reason_text=r9_reason,
                        dedup_key=f"ADD::{gap['bucket'].lower()}",
                    )
                    if fund_meta:
                        for k, v in fund_meta.items():
                            add_sig.__dict__[f"_{k}"] = v
                    add_sig.__dict__["_reinvest_gap"] = gap

                else:
                    # Fallback: static complement category
                    mf_investments = ctx.portfolio_intelligence.get("mf_investments") or []
                    victim_mf = next((m for m in mf_investments if m.get("instrument_id") == victim_iid), {})
                    victim_cat = victim_mf.get("category") or infer_category_from_name(victim_name) or ""
                    complement_cat = _COMPLEMENT_CATEGORIES.get(victim_cat)
                    if complement_cat:
                        fb_reason = (
                            f"After removing {victim_name[:40]} (overlap with {partner_name[:40]}), "
                            f"consider adding a {complement_cat} fund to maintain diversification."
                        )
                        add_sig = EngineSignal(
                            signal_id=f"overlap_r9::add::{complement_cat}",
                            engine_name=self.engine_name,
                            rule_label="Rule 9",
                            action_type="ADD",
                            instrument_id=None,
                            instrument_name=f"{complement_cat} Fund",
                            amount_rs=amount_rs,
                            base_score=5.0,
                            confidence=0.5,
                            diversification_gain=0.7,
                            reason_codes=["CROSS_CATEGORY_REPLACEMENT"],
                            reason_text=fb_reason,
                            dedup_key=f"ADD::{complement_cat.lower()}",
                        )
                        add_sig.__dict__["_complement_category"] = complement_cat

                if add_sig is not None:
                    signals.append(add_sig)
                    r9_count += 1

        return signals
