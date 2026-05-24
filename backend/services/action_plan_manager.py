"""Action Plan Manager — CRUD and lifecycle management for portfolio action plans.

Handles:
1. Plan generation from signals and scores
2. CRUD operations
3. Lifecycle management (preview → active → completed → archived)
4. Action state transitions
5. Plan versioning
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal
import logging

from deps import db
from services import signal_detector, decision_engine, instrument_scoring, tax_calculator
from services.instrument_scoring import (
    PORTFOLIO_HEALTHY_SCORE, MAX_ACTIONS_PER_PLAN,
)
from services import rules_config
from services import v3_integration
from services.action_recommendation_schema import augment_all as _augment_v4_fields

logger = logging.getLogger(__name__)

# Plan statuses
STATUS_PREVIEW = "preview"
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_ARCHIVED = "archived"

# Action statuses
ACTION_PENDING = "PENDING"
ACTION_IN_PROGRESS = "IN_PROGRESS"
ACTION_COMPLETED = "COMPLETED"
ACTION_SKIPPED = "SKIPPED"


def convert_decimals_to_float(obj: Any) -> Any:
    """Recursively convert Decimal objects to float for MongoDB compatibility.
    
    PostgreSQL numeric/decimal types return Python Decimal objects which
    MongoDB's BSON encoder cannot serialize. This converts them to float.
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_decimals_to_float(item) for item in obj)
    return obj


def _normalize_fund_name(name: str) -> str:
    """Normalize fund name for fuzzy matching.
    
    Lowercases, strips punctuation, collapses whitespace, removes common
    broker/CAS prefixes (3-4 letter codes like "DFG -", "MCOG -"), and drops
    parenthetical notes like "(erstwhile Value Discovery Fund)".
    Example:
        "DFG - ICICI Prudential Value Fund (erstwhile Value Discovery Fund) - Growth"
        → "icici prudential value fund growth"
    """
    import re
    n = name.lower()
    n = re.sub(r"\([^)]*\)", " ", n)  # drop parenthetical notes
    n = n.replace(",", " ").replace("-", " ")
    # Strip leading broker/CAS code prefix: "dfg", "mcog", "scgp" etc followed
    # by whitespace. Max 5 chars to avoid eating real words.
    n = re.sub(r"^\s*\b[a-z]{2,5}\b\s+(?=[a-z])", "", n)
    return " ".join(n.split())


def _fuzzy_match_holding(mf_scheme_name: str, mf_holdings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find the Mongo holding that best matches a PG scheme_name.

    Tries exact normalized match, then substring containment either way.
    Returns None when no confident match is found.
    """
    if not mf_scheme_name:
        return None
    target = _normalize_fund_name(mf_scheme_name)
    if not target:
        return None
    # Exact normalized match
    for h in mf_holdings:
        if _normalize_fund_name(h.get("name", "")) == target:
            return h
    # Token-overlap-based substring match (handles "DFG - ICICI ..." vs "ICICI ...")
    t_tokens = set(target.split())
    if not t_tokens:
        return None
    best = None
    best_score = 0.0
    for h in mf_holdings:
        hn = _normalize_fund_name(h.get("name", ""))
        if not hn:
            continue
        h_tokens = set(hn.split())
        common = t_tokens & h_tokens
        # Jaccard-ish score; require at least 60% of target tokens present
        score = len(common) / max(len(t_tokens), 1)
        if score >= 0.6 and score > best_score:
            best = h
            best_score = score
    return best


class ActionPlanManager:
    """Manages action plans for portfolio optimization."""
    
    def __init__(self):
        self.scoring_engine = instrument_scoring.get_scoring_engine()
    
    # ══════════════════════════════════════════════════════════════════════
    # PLAN GENERATION
    # ══════════════════════════════════════════════════════════════════════
    
    async def generate_plan(
        self,
        user_id: str,
        portfolio_intelligence: Dict[str, Any],
        holdings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Generate a new action plan from portfolio data.
        
        Flow:
        1. Generate signals
        2. Calculate EXIT scores for all holdings
        3. Calculate ADD scores for gap-filling
        4. Select top 2-3 actions
        5. Calculate tax impact
        6. Create plan object
        
        Returns:
            Complete action plan with status="preview"
        """
        logger.info("Generating plan for user %s", user_id)
        
        # 1. Generate signals
        portfolio_data = {
            "portfolio_intelligence": portfolio_intelligence,
            "holdings": holdings,
            "total_value": sum(h["quantity"] * h["current_price"] for h in holdings),
        }
        signals = signal_detector.generate_signals(portfolio_data)
        
        # 2. Calculate EXIT scores for MF and stocks
        mf_holdings = [h for h in holdings if h.get("asset_type", "").lower() in ["mutual_fund", "mutual fund"]]
        stock_holdings = [h for h in holdings if h.get("asset_type", "").lower() in ["equity", "stock"]]
        
        exit_candidates = []
        
        # Score MFs
        mf_investments = portfolio_intelligence.get("mf_investments", [])
        logger.info("Found %s MF investments in portfolio intelligence", len(mf_investments))
        resolved_count = sum(1 for mf in mf_investments if mf.get("resolved"))
        logger.info("Resolved MF investments: %s", resolved_count)
        
        # Build normalized name lookup for holdings
        holding_lookup = {
            _normalize_fund_name(h["name"]): h
            for h in mf_holdings
        }
        
        for mf in mf_investments:
            if not mf.get("resolved"):
                logger.debug("Skipping unresolved MF: %s", mf.get('scheme_name', 'Unknown')[:40])
                continue
            
            # Try normalized name matching
            normalized_scheme = _normalize_fund_name(mf["scheme_name"])
            holding = holding_lookup.get(normalized_scheme)
            
            if not holding:
                logger.warning("No matching holding found for MF: %s", mf.get('scheme_name', 'Unknown')[:40])
                continue
            
            try:
                exit_result = await decision_engine.calculate_mf_exit_score(mf, portfolio_intelligence, holding)
                logger.info("MF Exit Score: %s = %s (action: %s)", mf.get('scheme_name', 'Unknown')[:40], exit_result['exit_score'], exit_result['action'])
                
                # Lower threshold: include even HOLD recommendations in candidates
                if exit_result["exit_score"] >= 4.0:  # Was filtering only "EXIT", now include score >= 4
                    exit_candidates.append(exit_result)
                    logger.info("  → Added to exit_candidates (score >= 4.0)")
                else:
                    logger.debug("  → Skipped (score %s < 4.0)", exit_result['exit_score'])
            except Exception as e:
                logger.error("Error scoring MF %s: %s", mf.get('scheme_name', 'Unknown'), e)
                logger.exception(e)
                continue
        
        # Score stocks (DISABLED - MF-only action plans)
        # Stocks are excluded from action recommendations

        # Load user's risk profile for V2.5 Rule 5 dynamic target
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
        risk_profile = (
            user_doc.get("risk_profile")
            or (user_doc.get("profile") or {}).get("risk_profile")
            or "medium"
        )

        portfolio_context = {
            "total_value": portfolio_data["total_value"],
            "mf_count": len(mf_holdings),
            "stock_count": len(stock_holdings),
            "risk_profile": risk_profile,
        }
        
        # NOTE: Stock scoring disabled - focus on MF optimization only
        # for stock in stock_holdings:
        #     exit_result = await decision_engine.calculate_stock_exit_score(stock, portfolio_context)
        #     if exit_result["exit_score"] >= 4.0:
        #         exit_candidates.append(exit_result)
        
        # Sort by exit score (highest first)
        exit_candidates = sorted(exit_candidates, key=lambda x: x["exit_score"], reverse=True)
        
        logger.info("Generated %s MF exit candidates", len(exit_candidates))
        
        # 3. Apply V2 Action Generation Rules (6 core rules)
        actions = await self._apply_action_rules(
            mf_holdings=mf_holdings,
            mf_investments=mf_investments,
            exit_candidates=exit_candidates,
            holdings=holdings,
            portfolio_intelligence=portfolio_intelligence,
            portfolio_context=portfolio_context,
            signals=signals,
        )

        # 3b. Augment with Decision Engine drift / cap rules
        # ────────────────────────────────────────────────────────────────
        # The legacy V2 rules (1, 2, 2b, 4, 5, cost-leak) cover overlap,
        # AMC concentration and the simple equity/debt floor. They do
        # NOT cover asset-class drift vs computed targets, sector caps,
        # or category caps — those live in `decision_engine_actions` and
        # use the target_allocator → deviation_engine pipeline.
        #
        # We append these here, deduped against the legacy actions: if a
        # legacy rule already touches a fund/asset, the drift suggestion
        # is dropped (legacy rules are higher-quality because they have
        # tax-impact + exit-score data the drift engine doesn't compute).
        # Drift actions ride along as advisory, priority=medium, score=5.
        try:
            from services import decision_engine_actions as _de
            drift_actions = await _de.generate_actions(user_id)
            existing_assets = {(a.get("asset_name") or "").strip().lower()
                               for a in actions}
            appended = 0
            for da in drift_actions:
                asset_l = (da.asset_name or "").strip().lower()
                # Skip when a legacy rule already targets the same fund
                # OR when this is an ADD that would duplicate an existing
                # ADD bucket (avoid two debt-fund adds, etc.).
                if asset_l in existing_assets:
                    continue
                if da.type == "ADD" and any(
                    a.get("type") == "ADD" and (a.get("bucket") or "") == da.bucket
                    for a in actions
                ):
                    continue
                actions.append(da.to_dict())
                existing_assets.add(asset_l)
                appended += 1
            if appended:
                logger.info(
                    f"[Decision Engine] appended {appended} drift / cap "
                    f"actions to plan (rules: "
                    f"{sorted({a.rule for a in drift_actions if a.rule})})"
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("decision engine augmentation failed: %s", e)

        # 5. Calculate portfolio-level tax impact
        total_tax_impact = self._calculate_total_tax_impact(actions)
        
        # 6. Calculate freed capital
        freed_capital = sum(a["amount"] for a in actions if a["type"] == "EXIT")
        post_tax_proceeds = freed_capital - total_tax_impact["total_tax"]

        # 7. V2.5 — Portfolio Health + Confidence + Plan Summary (+ Rule 7 Do-Nothing)
        portfolio_score, portfolio_score_breakdown = self._calculate_portfolio_health_score(
            portfolio_intelligence=portfolio_intelligence,
            holdings=holdings,
            actions=actions,
        )
        confidence_score, confidence_breakdown = self._calculate_confidence_score(
            portfolio_intelligence=portfolio_intelligence,
            holdings=holdings,
            actions=actions,
        )
        def _is_high_priority(a: Dict[str, Any]) -> bool:
            """Accept both string ('high') and integer (1) priority encodings."""
            p = a.get("priority")
            return p == "high" or p == "HIGH" or p == 1

        def _priority_rank(a: Dict[str, Any]) -> int:
            """Lower rank = higher priority. Used for stable sort in action-cap trim."""
            p = a.get("priority")
            if p in ("high", "HIGH", 1): return 0
            if p in ("medium", "MEDIUM", 2): return 1
            return 2

        # Rule 7 — Do-Nothing: strip actions when portfolio already healthy
        do_nothing = False
        if portfolio_score >= PORTFOLIO_HEALTHY_SCORE and not any(_is_high_priority(a) for a in actions):
            do_nothing = True
            actions = []  # replaced with a synthetic HOLD action below
            actions.append({
                "action_id": f"act_{uuid4().hex[:10]}",
                "type": "HOLD",
                "priority": "low",
                "asset_name": "Your portfolio",
                "asset_type": "portfolio",
                "amount": 0,
                "reason_codes": ["PORTFOLIO_HEALTHY"],
                "reason_text": "Your portfolio already scores ≥75/100. No action needed right now.",
                "status": ACTION_PENDING,
                "tax_impact": None,
            })
            total_tax_impact = self._calculate_total_tax_impact(actions)
            freed_capital = 0
            post_tax_proceeds = 0

        # Hard cap actions at MAX_ACTIONS_PER_PLAN
        if len(actions) > MAX_ACTIONS_PER_PLAN:
            actions = sorted(
                actions,
                key=lambda a: (_priority_rank(a), -(a.get("score") or 0)),
            )[:MAX_ACTIONS_PER_PLAN]

        # v4 Recommendation schema augmentation (Decision 2 per docs/api-changes.md).
        # Adds verb, priority_label, source_domain, effort, trade_off, impact,
        # expected_impact, exclusive, scores, switch_target — all idempotent and
        # non-destructive. Applied here so every creator path gets the v4 shape.
        _augment_v4_fields(actions)

        plan_summary = self._generate_plan_summary(
            actions=actions,
            portfolio_score=portfolio_score,
            total_tax_impact=total_tax_impact,
            portfolio_intelligence=portfolio_intelligence,
            do_nothing=do_nothing,
        )
        improvements = self._compute_improvements(portfolio_intelligence, actions)

        # 8. Create plan object
        plan_id = f"plan_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid4().hex[:8]}"
        
        plan = {
            "plan_id": plan_id,
            "user_id": user_id,
            "version": 1,
            "status": STATUS_PREVIEW,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "signals": signals,
            "actions": actions,
            "total_actions": len(actions),
            "completed_actions": 0,
            "pending_actions": len(actions),
            "skipped_actions": 0,
            "completion_pct": 0.0,
            "freed_capital": freed_capital,
            "total_tax_impact": total_tax_impact,
            "post_tax_proceeds": post_tax_proceeds,
            # V2.5 additions
            "plan_summary": plan_summary,
            "portfolio_score": portfolio_score,
            "portfolio_score_breakdown": portfolio_score_breakdown,
            "confidence_score": confidence_score,
            "confidence_breakdown": confidence_breakdown,
            "improvements": improvements,
            "do_nothing": do_nothing,
            "degraded": bool(portfolio_intelligence.get("degraded")),
            "degraded_reason": portfolio_intelligence.get("degraded_reason"),
            "metadata": {
                "source": "auto_generated",
                "generation_time_ms": 0,
                "portfolio_value_at_creation": portfolio_data["total_value"],
                "engine_version": "v2.5",
            },
        }
        
        logger.info("Plan generated: %s with %s actions · score=%s · conf=%s", plan_id, len(actions), portfolio_score, confidence_score)
        return plan
    
    # ══════════════════════════════════════════════════════════════════════
    # PLAN CRUD
    # ══════════════════════════════════════════════════════════════════════
    
    async def save_plan(self, plan_id: str, user_id: str) -> Dict[str, Any]:
        """Save a preview plan as active.
        
        Changes status from "preview" to "active".
        Also archives any pre-existing active plan(s) for the user to prevent duplicates.
        """
        # Archive any other active plan for this user first
        await db.action_plans.update_many(
            {"user_id": user_id, "status": STATUS_ACTIVE, "plan_id": {"$ne": plan_id}},
            {
                "$set": {
                    "status": STATUS_ARCHIVED,
                    "archived_at": datetime.now(timezone.utc),
                    "archive_reason": "superseded_by_new_plan",
                }
            }
        )

        result = await db.action_plans.update_one(
            {"plan_id": plan_id, "user_id": user_id, "status": STATUS_PREVIEW},
            {
                "$set": {
                    "status": STATUS_ACTIVE,
                    "updated_at": datetime.now(timezone.utc),
                }
            }
        )
        
        if result.modified_count == 0:
            raise ValueError(f"Plan {plan_id} not found or already active")
        
        plan = await db.action_plans.find_one({"plan_id": plan_id}, {"_id": 0})
        logger.info("Plan %s saved as active", plan_id)
        return plan
    
    async def get_active_plan(
        self,
        user_id: str,
        source_domain: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get user's active plan with calculated completion metrics.

        Args:
            user_id: caller's effective user_id (advisor impersonation handled upstream).
            source_domain: optional v4 filter — when set, returns only actions whose
                `source_domain` matches. Per gap-analysis Finding C.9 — pushes the
                domain filter server-side instead of client-side reason_code matching.
        """
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": STATUS_ACTIVE},
            {"_id": 0}
        )

        if not plan:
            return None

        actions = plan.get("actions", []) or []

        # Read-time v4 augmentation — handles legacy plans that pre-date Decision 2.
        # Idempotent; no-op for already-augmented documents.
        _augment_v4_fields(actions)

        # Optional source_domain filter (v4).
        if source_domain:
            sd = source_domain.lower()
            actions = [a for a in actions if (a.get("source_domain") or "").lower() == sd]
            plan["actions"] = actions

        total_actions = len(actions)
        completed_actions = len([a for a in actions if a.get("status") == "COMPLETED"])
        completion_pct = (completed_actions / total_actions * 100) if total_actions > 0 else 0

        plan["total_actions"] = total_actions
        plan["completed_actions"] = completed_actions
        plan["completion_pct"] = completion_pct
        plan["pending_actions"] = total_actions - completed_actions

        return plan
    
    async def get_plan(self, plan_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get specific plan by ID."""
        plan = await db.action_plans.find_one(
            {"plan_id": plan_id, "user_id": user_id},
            {"_id": 0}
        )
        return plan
    
    async def get_plan_history(
        self,
        user_id: str,
        limit: int = 10,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get user's plan history."""
        plans = await db.action_plans.find(
            {"user_id": user_id},
            {"_id": 0}
        ).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
        
        return plans
    
    async def create_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Insert new plan into database."""
        # Convert Decimal objects to float for MongoDB compatibility
        plan_clean = convert_decimals_to_float(plan)
        await db.action_plans.insert_one(plan_clean)
        logger.info("Plan %s created in DB", plan['plan_id'])
        return plan_clean
    
    # ══════════════════════════════════════════════════════════════════════
    # ACTION STATE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════
    
    async def update_action_status(
        self,
        plan_id: str,
        action_id: str,
        user_id: str,
        new_status: str,
        completion_note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update action status (PENDING → IN_PROGRESS → COMPLETED/SKIPPED).
        
        Also updates plan progress.
        """
        if new_status not in [ACTION_PENDING, ACTION_IN_PROGRESS, ACTION_COMPLETED, ACTION_SKIPPED]:
            raise ValueError(f"Invalid status: {new_status}")
        
        # Get current plan
        plan = await self.get_plan(plan_id, user_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        
        # Find action
        action_idx = None
        for idx, action in enumerate(plan["actions"]):
            if action["action_id"] == action_id:
                action_idx = idx
                break
        
        if action_idx is None:
            raise ValueError(f"Action {action_id} not found in plan")
        
        # Update action
        timestamp_field = None
        if new_status == ACTION_COMPLETED:
            timestamp_field = "completed_at"
        elif new_status == ACTION_SKIPPED:
            timestamp_field = "skipped_at"
        elif new_status == ACTION_IN_PROGRESS:
            timestamp_field = "started_at"
        
        update_fields = {
            f"actions.{action_idx}.status": new_status,
            "updated_at": datetime.now(timezone.utc),
        }
        
        if timestamp_field:
            update_fields[f"actions.{action_idx}.{timestamp_field}"] = datetime.now(timezone.utc)
        
        if completion_note:
            update_fields[f"actions.{action_idx}.completion_note"] = completion_note
        
        # Calculate new progress
        actions = plan["actions"]
        actions[action_idx]["status"] = new_status
        
        completed_count = sum(1 for a in actions if a["status"] == ACTION_COMPLETED)
        skipped_count = sum(1 for a in actions if a["status"] == ACTION_SKIPPED)
        in_progress_count = sum(1 for a in actions if a["status"] == ACTION_IN_PROGRESS)
        pending_count = sum(1 for a in actions if a["status"] == ACTION_PENDING)
        completion_pct = (completed_count / len(actions) * 100) if actions else 0
        
        update_fields["completed_actions"] = completed_count
        update_fields["skipped_actions"] = skipped_count
        update_fields["in_progress_actions"] = in_progress_count
        update_fields["pending_actions"] = pending_count
        update_fields["completion_pct"] = round(completion_pct, 2)
        
        # Check if plan is completed
        if pending_count == 0 and in_progress_count == 0:
            update_fields["status"] = STATUS_COMPLETED
            update_fields["completed_at"] = datetime.now(timezone.utc)
        
        # Update in DB
        await db.action_plans.update_one(
            {"plan_id": plan_id, "user_id": user_id},
            {"$set": update_fields}
        )
        
        # Return updated plan
        updated_plan = await self.get_plan(plan_id, user_id)
        return updated_plan
        
    
    async def add_action_to_active_plan(
        self,
        user_id: str,
        action_input: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v4 — Create a new action on the user's active plan.

        Per docs/api-changes.md B.10. Used for cross-domain action creation:
        Tax (from tax_harvest candidates), Goals (from goal-engine recs), or
        advisor Discuss promotion. Idempotent if `idempotency_key` is set.
        """
        # Find the active plan
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": STATUS_ACTIVE},
            {"_id": 0},
        )
        if not plan:
            raise ValueError("No active plan found")

        # Idempotency check — if this key was already applied, return existing
        if idempotency_key:
            for existing in plan.get("actions", []) or []:
                if existing.get("idempotency_key") == idempotency_key:
                    return existing

        # Build the action dict, then run through the v4 augment so all
        # schema fields are present.
        new_action = dict(action_input)
        new_action.setdefault("action_id", f"act_{uuid4().hex[:8]}")
        new_action.setdefault("status", ACTION_PENDING)
        new_action.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        if idempotency_key:
            new_action["idempotency_key"] = idempotency_key

        _augment_v4_fields([new_action])

        # Push to plan
        await db.action_plans.update_one(
            {"plan_id": plan["plan_id"], "user_id": user_id},
            {
                "$push": {"actions": new_action},
                "$set": {"updated_at": datetime.now(timezone.utc)},
                "$inc": {"total_actions": 1, "pending_actions": 1},
            },
        )

        logger.info("Action %s added to plan %s (source=%s)",
                    new_action["action_id"], plan["plan_id"], new_action.get("source_domain"))
        return new_action


    async def record_action_discussion(
        self,
        plan_id: str,
        action_id: str,
        advisor_user_id: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v4 — Advisor-side Discuss-only write per PRD §10.2.

        Records that the advisor discussed this action with the client.
        Does NOT modify action.status — client retains sole control.
        """
        # We don't know the client user_id from advisor session alone — look up by plan_id
        plan = await db.action_plans.find_one({"plan_id": plan_id}, {"_id": 0})
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")

        action_idx = None
        for idx, action in enumerate(plan.get("actions", []) or []):
            if action.get("action_id") == action_id or action.get("id") == action_id:
                action_idx = idx
                break
        if action_idx is None:
            raise ValueError(f"Action {action_id} not found in plan {plan_id}")

        now = datetime.now(timezone.utc).isoformat()
        existing_discussions = plan["actions"][action_idx].get("discussions", []) or []
        discussion_event = {
            "advisor_user_id": advisor_user_id,
            "discussed_at": now,
            "note": note or "",
        }
        new_discussions = existing_discussions + [discussion_event]

        await db.action_plans.update_one(
            {"plan_id": plan_id},
            {
                "$set": {
                    f"actions.{action_idx}.discussions": new_discussions,
                    f"actions.{action_idx}.last_discussed_at": now,
                    f"actions.{action_idx}.discussion_count": len(new_discussions),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )

        return {
            "action_id": action_id,
            "discussed_at": now,
            "discussed_by_advisor_id": advisor_user_id,
            "discussion_count": len(new_discussions),
            "discussion_note": note or "",
        }


    async def update_action_feedback(
        self,
        plan_id: str,
        action_id: str,
        user_id: str,
        useful: bool,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update action feedback (useful/not useful + optional comment).
        
        Feedback is stored per action for future recommendation improvements.
        """
        # Get current plan
        plan = await self.get_plan(plan_id, user_id)
        if not plan:
            raise ValueError(f"Plan {plan_id} not found")
        
        # Find action
        action_idx = None
        for idx, action in enumerate(plan["actions"]):
            if action["action_id"] == action_id:
                action_idx = idx
                break
        
        if action_idx is None:
            raise ValueError(f"Action {action_id} not found in plan")
        
        # Build feedback object
        feedback = {
            "useful": useful,
            "comment": comment or "",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Update action
        update_fields = {
            f"actions.{action_idx}.feedback": feedback,
            "updated_at": datetime.now(timezone.utc),
        }
        
        # Update in DB
        await db.action_plans.update_one(
            {"plan_id": plan_id, "user_id": user_id},
            {"$set": update_fields}
        )
        
        # Return updated plan
        updated_plan = await self.get_plan(plan_id, user_id)
        return updated_plan

    
    async def auto_archive_old_completed_plans(self, user_id: str) -> int:
        """Auto-archive plans with all actions completed for >30 days.
        
        Returns count of archived plans.
        """
        from datetime import timedelta
        
        threshold_date = datetime.now(timezone.utc) - timedelta(days=30)
        
        # Find active/completed plans where all actions are done for >30 days
        plans = await db.action_plans.find({
            "user_id": user_id,
            "status": {"$in": [STATUS_ACTIVE, STATUS_COMPLETED]},
        }, {"_id": 0}).to_list(100)
        
        archived_count = 0
        
        for plan in plans:
            # Check if all actions are completed/skipped
            actions = plan.get("actions", [])
            if not actions:
                continue
            
            all_done = all(
                a.get("status") in [ACTION_COMPLETED, ACTION_SKIPPED]
                for a in actions
            )
            
            if not all_done:
                continue
            
            # Check if oldest completion is >30 days
            completion_dates = []
            for action in actions:
                if action.get("status") == ACTION_COMPLETED and action.get("completed_at"):
                    completion_dates.append(action["completed_at"])
                elif action.get("status") == ACTION_SKIPPED and action.get("skipped_at"):
                    completion_dates.append(action["skipped_at"])
            
            if not completion_dates:
                continue
            
            # Get the most recent completion date
            latest_completion = max(completion_dates)
            
            # If the most recent completion is >30 days old, archive
            if isinstance(latest_completion, str):
                latest_completion = datetime.fromisoformat(latest_completion.replace('Z', '+00:00'))
            
            if latest_completion < threshold_date:
                # Archive this plan
                await db.action_plans.update_one(
                    {"plan_id": plan["plan_id"], "user_id": user_id},
                    {"$set": {
                        "status": STATUS_ARCHIVED,
                        "archived_at": datetime.now(timezone.utc),
                        "archive_reason": "auto_archived_after_30_days",
                    }}
                )
                archived_count += 1
                logger.info("Auto-archived plan %s (completed >30 days ago)", plan['plan_id'])
        
        return archived_count
    
    # ══════════════════════════════════════════════════════════════════════
    # PLAN LIFECYCLE
    # ══════════════════════════════════════════════════════════════════════
    
    async def archive_plan(self, plan_id: str, user_id: str, reason: str) -> bool:
        """Archive a plan in-place — flips status to ARCHIVED on the
        action_plans doc and records the reason. Used by the
        DELETE /api/plans/active endpoint (manual user action) and by
        refresh_plan (rev-up auto-archive). Returns True if a row was
        actually updated, False otherwise (already archived / not found).
        """
        plan = await self.get_plan(plan_id, user_id)
        if not plan:
            return False
        result = await db.action_plans.update_one(
            {"plan_id": plan_id, "user_id": user_id,
             "status": {"$ne": STATUS_ARCHIVED}},
            {"$set": {
                "status": STATUS_ARCHIVED,
                "archived_at": datetime.now(timezone.utc),
                "archive_reason": reason,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        if result.modified_count > 0:
            logger.info(
                f"Archived plan {plan_id} for user {user_id} (reason={reason})"
            )
            return True
        return False



    # ══════════════════════════════════════════════════════════════════════
    # V2 ACTION GENERATION RULES (6 Core Rules)
    # ══════════════════════════════════════════════════════════════════════

    async def _apply_action_rules(
        self,
        mf_holdings: List[Dict[str, Any]],
        mf_investments: List[Dict[str, Any]],
        exit_candidates: List[Dict[str, Any]],
        holdings: List[Dict[str, Any]],
        portfolio_intelligence: Dict[str, Any],
        portfolio_context: Dict[str, Any],
        signals: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Apply the 6 V2 Action Generation Rules in priority order.

        Rule 1 (P0): Regular → Direct consolidation (same fund, exit Regular)
        Rule 6 (P0): Regular → Direct cost-leak switch actions (>₹10K/yr)
        Rule 2 (P0): AMC concentration >15% → EXIT by highest exit_score until <15%
        Rule 3 (P1): Underperformer → replace with same-category top ADD score fund
        Rule 4 (P1): Different-fund overlap >60% → EXIT fund with higher exit_score
        Rule 5 (P2): Equity>90% & Debt<10% → ADD debt fund

        Each fund can only be selected for EXIT once (tracked via exited_ids set).
        """
        # Load live rule config (admin-tunable)
        rcfg = await rules_config.get_config()
        rules_cfg = rcfg["rules"]
        actions: List[Dict[str, Any]] = []
        exited_ids: set = set()                  # instrument_ids already marked for exit
        exited_holding_keys: set = set()         # mongo holding keys (for Regular/Direct matches without IDs)
        priority_counter = [1]                   # mutable int for shared incrementing

        # ── V3 Phase 2: Enrich with composite scores + guardrails ───────────
        # Returns {instrument_id: {quality_score, health_score, exit_score,
        #                          add_score, guardrail_blocked, guardrail_reasons}}
        v3_scores_by_id = await v3_integration.enrich_candidates_with_v3(
            mf_investments=mf_investments,
            exit_candidates=exit_candidates,
            mf_holdings=mf_holdings,
            portfolio_intelligence=portfolio_intelligence,
        )
        # Apply V3 guardrails: any candidate blocked by High-Quality-Protection,
        # Tax-Exceeds-Benefit, or Recent-Investment-Lockout is dropped from the
        # EXIT pool entirely. Guardrail results are also stashed so actions can
        # report them in reason text.
        pre_filter = len(exit_candidates)
        exit_candidates = [
            c for c in exit_candidates
            if not (
                c.get("instrument_id") and
                v3_scores_by_id.get(c["instrument_id"], {}).get("guardrail_blocked")
            )
        ]
        dropped_by_guardrail = pre_filter - len(exit_candidates)
        if dropped_by_guardrail:
            logger.info(
                f"[V3 guardrails] blocked {dropped_by_guardrail} exit candidate(s) "
                f"(protected by quality/tax/recent-investment rules)"
            )

        def _v3_exit_rank(iid: Optional[str], legacy: float, name: Optional[str] = None) -> float:
            """Unified ranking score. Prefer V3 exit_score (scaled to 0-10)
            when available (by iid or fuzzy name match); else fall back to
            legacy heuristic."""
            return v3_integration.v3_exit_score_or_legacy(iid, legacy, v3_scores_by_id, name)

        # Fast lookup helpers
        candidate_by_id = {
            c.get("instrument_id"): c
            for c in exit_candidates if c.get("instrument_id")
        }
        candidate_by_name = {
            _normalize_fund_name(c.get("instrument_name") or c.get("mf_investment", {}).get("scheme_name", "")): c
            for c in exit_candidates
        }
        def _holding_key(h: Dict[str, Any]) -> str:
            return f"{h.get('user_id','')}::{_normalize_fund_name(h.get('name',''))}"

        def _resolve_candidate(holding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Find the pre-computed exit_candidate for a mongo holding."""
            h_norm = _normalize_fund_name(holding.get("name", ""))
            return candidate_by_name.get(h_norm)

        # ── RULE 1 + RULE 6: Regular vs Direct handling ─────────────────────
        rule_1_enabled = rules_cfg["rule_1_regular_to_direct"]["enabled"]
        rule_6_enabled = rules_cfg["rule_6_cost_leak_switch"]["enabled"]
        reg_dir_pairs = self._find_regular_direct_pairs(mf_holdings)
        logger.info("[Rule 1/6] Found %s Regular/Direct pairs", len(reg_dir_pairs))

        # Rule 1: Exit Regular when Direct exists for same fund
        for pair in (reg_dir_pairs if rule_1_enabled else []):
            regular = pair["regular"]
            direct = pair["direct"]
            reg_key = _holding_key(regular)
            if reg_key in exited_holding_keys:
                continue
            cost_leak = self._estimate_cost_leak(regular, direct, mf_investments)
            # V3 Phase 2: gate on switch_score ≥ threshold, BUT only when V3
            # enrichment returned data. When PG/scraper data is unavailable
            # (unit tests, fresh deploys), fall back to legacy always-fire
            # behaviour so the rule still works.
            switch_s: Optional[float] = None
            if v3_scores_by_id:
                switch_threshold = float(
                    rules_cfg["rule_1_regular_to_direct"]["params"].get("min_switch_score", 1.0)
                )
                switch_s = v3_integration.compute_reg_to_direct_switch_score(
                    regular_holding=regular, cost_leak_rs=cost_leak,
                    v3_scores_by_id=v3_scores_by_id, mf_investments=mf_investments,
                )
                if switch_s < switch_threshold:
                    logger.info(
                        f"[Rule 1 · V3] SKIP {regular.get('name','')[:40]} — "
                        f"switch_score={switch_s:.2f} < {switch_threshold}"
                    )
                    continue
            reason_extra = (
                f"Direct plan of same fund exists in portfolio (expense saving ≈ ₹{cost_leak:,.0f}/yr"
                + (f", switch score {switch_s:.1f}" if switch_s is not None else "")
                + "). "
                if cost_leak > 0 else
                "Direct plan of same fund exists in portfolio (lower expense ratio). "
            )
            cand = _resolve_candidate(regular)
            action = self._build_exit_action_from_holding(
                holding=regular,
                candidate=cand,
                priority=priority_counter[0],
                reason_prefix=reason_extra + "Regular → Direct consolidation.",
                reason_code="REGULAR_DIRECT_DUPLICATE",
            )
            if switch_s is not None:
                action["switch_score"] = switch_s
            actions.append(action)
            exited_holding_keys.add(reg_key)
            mf_match = _resolve_candidate(regular) or {}
            if mf_match.get("instrument_id"):
                exited_ids.add(mf_match["instrument_id"])
            priority_counter[0] += 1
            logger.info(
                f"[Rule 1] EXIT Regular: {regular.get('name','')[:40]}"
                + (f" (switch={switch_s:.2f})" if switch_s is not None else "")
            )

        # Rule 6: Cost leak — if annual leak > ₹10K total across Regular funds without Direct pair,
        # generate switch (EXIT Regular + ADD Direct) actions for each such Regular fund
        all_regular_without_direct = self._find_regular_without_direct_pair(mf_holdings, reg_dir_pairs)
        leaks: List[Dict[str, Any]] = []
        for reg in all_regular_without_direct:
            leak = self._estimate_cost_leak(reg, None, mf_investments)
            if leak > 0:
                leaks.append({"holding": reg, "leak": leak})
        total_leak = sum(item["leak"] for item in leaks)
        logger.info("[Rule 6] Total Regular→Direct cost leak: ₹%s/yr across %s funds", f"{total_leak:,.0f}", len(leaks))
        leak_cfg = rules_cfg["rule_6_cost_leak_switch"]["params"]
        leak_threshold = float(leak_cfg.get("total_leak_threshold_rs", 10000.0))
        max_switches = int(leak_cfg.get("max_switches", 3))
        if rule_6_enabled and total_leak >= leak_threshold:
            # Sort by largest leak first, cap at N switch actions to keep plan actionable
            leaks.sort(key=lambda x: x["leak"], reverse=True)
            for leak_item in leaks[:max_switches]:
                reg = leak_item["holding"]
                reg_key = _holding_key(reg)
                if reg_key in exited_holding_keys:
                    continue
                # V3 Phase 2: gate on switch_score — only when V3 data available
                switch_s: Optional[float] = None
                if v3_scores_by_id:
                    switch_threshold = float(
                        rules_cfg["rule_6_cost_leak_switch"]["params"].get("min_switch_score", 1.0)
                    )
                    switch_s = v3_integration.compute_reg_to_direct_switch_score(
                        regular_holding=reg, cost_leak_rs=leak_item["leak"],
                        v3_scores_by_id=v3_scores_by_id, mf_investments=mf_investments,
                    )
                    if switch_s < switch_threshold:
                        logger.info(
                            f"[Rule 6 · V3] SKIP {reg.get('name','')[:40]} — "
                            f"switch_score={switch_s:.2f} < {switch_threshold}"
                        )
                        continue
                cand = _resolve_candidate(reg)
                action = self._build_exit_action_from_holding(
                    holding=reg,
                    candidate=cand,
                    priority=priority_counter[0],
                    reason_prefix=(
                        f"Switch to Direct plan saves ₹{leak_item['leak']:,.0f}/year in expense ratio"
                        + (f" (switch score {switch_s:.1f})" if switch_s is not None else "")
                        + f". (Total portfolio cost leak: ₹{total_leak:,.0f}/yr.)"
                    ),
                    reason_code="COST_LEAK_SWITCH_TO_DIRECT",
                )
                if switch_s is not None:
                    action["switch_score"] = switch_s
                actions.append(action)
                exited_holding_keys.add(reg_key)
                if cand and cand.get("instrument_id"):
                    exited_ids.add(cand["instrument_id"])
                priority_counter[0] += 1
                logger.info(
                    f"[Rule 6] SWITCH (EXIT Regular): {reg.get('name','')[:40]} "
                    f"saves ₹{leak_item['leak']:,.0f}/yr"
                    + (f" (switch={switch_s:.2f})" if switch_s is not None else "")
                )

        # ── RULE 2: AMC Concentration >15% ──────────────────────────────────
        amc_exposure = self._calculate_amc_exposure_from_mf_investments(
            mf_investments, portfolio_context["total_value"]
        )
        amc_cfg = rules_cfg["rule_2_amc_concentration"]["params"]
        amc_threshold = float(amc_cfg.get("threshold_pct", 15.0))
        rule_2_enabled = rules_cfg["rule_2_amc_concentration"]["enabled"]
        # Use >= so exactly-at-threshold (e.g. 15.0%) still triggers, consistent
        # with the Insights path. Prevents the "CRITICAL flag but no action" UX.
        over_concentrated_amcs = [(amc, pct) for amc, pct in amc_exposure.items() if pct >= amc_threshold] if rule_2_enabled else []
        logger.info("[Rule 2] AMC exposure: %s; over-concentrated: %s", amc_exposure, over_concentrated_amcs)

        for amc_name, amc_pct in sorted(over_concentrated_amcs, key=lambda x: x[1], reverse=True):
            # Find all MF investments in this AMC (not yet exited). Works for
            # unresolved funds too — AMC is derived from scheme_name.
            amc_funds = [
                m for m in mf_investments
                if self._extract_amc_from_name(m.get("scheme_name", "")) == amc_name
                and (m.get("instrument_id") is None or m.get("instrument_id") not in exited_ids)
            ]
            # Rank by exit_score (descending) — V3 composite preferred
            ranked = []
            for mf in amc_funds:
                cand = candidate_by_id.get(mf.get("instrument_id"))
                legacy = cand["exit_score"] if cand else 5.0
                score = _v3_exit_rank(mf.get("instrument_id"), legacy, mf.get("scheme_name"))
                ranked.append({"mf": mf, "candidate": cand, "exit_score": score})
            ranked.sort(key=lambda x: x["exit_score"], reverse=True)

            # Exit funds greedily until AMC exposure drops STRICTLY below threshold.
            # (`<` not `<=` so we don't bail at exactly-at-threshold — that's the
            # value insights already flagged as CRITICAL.)
            current_pct = amc_pct
            target_pct = amc_threshold
            total_pv = portfolio_context["total_value"]
            for item in ranked:
                if current_pct < target_pct:
                    break
                mf = item["mf"]
                # Find matching holding (fuzzy match handles broker prefixes like "DFG -")
                h = _fuzzy_match_holding(mf.get("scheme_name", ""), mf_holdings)
                if not h:
                    continue
                h_key = _holding_key(h)
                if h_key in exited_holding_keys:
                    # still reduce exposure since already exiting
                    current_pct -= (mf.get("amount_rs", 0) / total_pv * 100) if total_pv > 0 else 0
                    continue
                reason = (
                    f"Reducing {amc_name} AMC concentration from {current_pct:.1f}% toward <15% target. "
                    f"Among this AMC's funds, exit score = {item['exit_score']:.1f} (highest)."
                )
                action = self._build_exit_action_from_holding(
                    holding=h,
                    candidate=item["candidate"],
                    priority=priority_counter[0],
                    reason_prefix=reason,
                    reason_code="AMC_CONCENTRATION_EXIT",
                )
                actions.append(action)
                exited_holding_keys.add(h_key)
                if mf.get("instrument_id"):
                    exited_ids.add(mf["instrument_id"])
                priority_counter[0] += 1
                current_pct -= (mf.get("amount_rs", 0) / total_pv * 100) if total_pv > 0 else 0
                logger.info(
                    "[Rule 2] EXIT for AMC concentration: %.40s (new AMC pct ~%.1f%%)",
                    mf.get("scheme_name", ""), current_pct,
                )

        # ── RULE 2b (NEW): MF Category Concentration > threshold ────────────
        # User-flagged guardrail: no single category (Mid Cap, Large Cap, etc.)
        # should exceed the configured threshold of total MF corpus. Trims down
        # the highest-exit-score funds in the offending category.
        rule_2b_enabled = rules_cfg["rule_2b_category_concentration"]["enabled"]
        CAT_CONCENTRATION_THRESHOLD = float(
            rules_cfg["rule_2b_category_concentration"]["params"].get("threshold_pct", 35.0)
        )
        from collections import defaultdict as _dd
        cat_totals: Dict[str, float] = _dd(float)
        cat_funds: Dict[str, List[Dict[str, Any]]] = _dd(list)
        total_mf_value = sum((m.get("amount_rs") or 0) for m in mf_investments)
        for m in mf_investments:
            # Prefer PG-backed category, fall back to scheme-name inference
            cn = (m.get("category") or "").strip()
            if not cn or cn == "Uncategorised":
                inferred = self._infer_category_from_name(m.get("scheme_name", ""))
                if inferred:
                    cn = inferred
                    m["category"] = inferred  # persist for downstream rules in this run
                else:
                    cn = "Uncategorised"
            cat_totals[cn] += (m.get("amount_rs") or 0)
            cat_funds[cn].append(m)
        if rule_2b_enabled and total_mf_value > 0:
            over_cats = [
                (cn, v / total_mf_value * 100)
                for cn, v in cat_totals.items()
                if v / total_mf_value * 100 >= CAT_CONCENTRATION_THRESHOLD and cn != "Uncategorised"
            ]
            over_cats.sort(key=lambda x: -x[1])
            logger.info("[Rule 2b] Category exposure over %s%: %s", CAT_CONCENTRATION_THRESHOLD, over_cats)
            for cat_name, cat_pct in over_cats:
                ranked_funds: List[Dict[str, Any]] = []
                for mf in cat_funds[cat_name]:
                    if mf.get("instrument_id") in exited_ids:
                        continue
                    cand = candidate_by_id.get(mf.get("instrument_id"))
                    legacy = cand["exit_score"] if cand else 5.0
                    ranked_funds.append({
                        "mf": mf,
                        "candidate": cand,
                        "exit_score": _v3_exit_rank(mf.get("instrument_id"), legacy, mf.get("scheme_name")),
                    })
                ranked_funds.sort(key=lambda x: x["exit_score"], reverse=True)
                current_pct = cat_pct
                for item in ranked_funds:
                    if current_pct < CAT_CONCENTRATION_THRESHOLD:
                        break
                    mf = item["mf"]
                    h = _fuzzy_match_holding(mf.get("scheme_name", ""), mf_holdings)
                    if not h:
                        continue
                    h_key = _holding_key(h)
                    if h_key in exited_holding_keys:
                        current_pct -= (mf.get("amount_rs", 0) / total_mf_value * 100)
                        continue
                    reason = (
                        f"{cat_name} is {current_pct:.1f}% of your MF corpus — above the "
                        f"{CAT_CONCENTRATION_THRESHOLD:.0f}% guardrail. Exiting this fund "
                        f"(exit score {item['exit_score']:.1f}) to diversify category exposure."
                    )
                    action = self._build_exit_action_from_holding(
                        holding=h,
                        candidate=item["candidate"],
                        priority=priority_counter[0],
                        reason_prefix=reason,
                        reason_code="CATEGORY_CONCENTRATION_EXIT",
                    )
                    actions.append(action)
                    exited_holding_keys.add(h_key)
                    if mf.get("instrument_id"):
                        exited_ids.add(mf["instrument_id"])
                    priority_counter[0] += 1
                    current_pct -= (mf.get("amount_rs", 0) / total_mf_value * 100)
                    logger.info(
                        f"[Rule 2b] EXIT for {cat_name} concentration: "
                        f"{mf.get('scheme_name','')[:40]} (new cat pct ≈ {current_pct:.1f}%)"
                    )

        # ── RULE 3: Underperformer Replacement ──────────────────────────────
        # Use signal QUALITY_ISSUES + exit_score quality component to detect underperformers
        rule_3_enabled = rules_cfg["rule_3_underperformer_replacement"]["enabled"]
        max_replacements = int(rules_cfg["rule_3_underperformer_replacement"]["params"].get("max_replacements", 2))
        underperformers = self._find_underperformers(mf_investments, portfolio_intelligence, exit_candidates) if rule_3_enabled else []
        logger.info("[Rule 3] Found %s underperforming funds", len(underperformers))
        for under in underperformers[:max_replacements]:
            mf = under["mf"]
            if mf.get("instrument_id") in exited_ids:
                continue
            h = _fuzzy_match_holding(mf.get("scheme_name", ""), mf_holdings)
            if not h:
                continue
            h_key = _holding_key(h)
            if h_key in exited_holding_keys:
                continue
            # Find best replacement in same category
            replacement = self._find_best_same_category_replacement(
                category=mf.get("category"),
                excluded_ids=exited_ids | {mf.get("instrument_id")},
                mf_investments=mf_investments,
                portfolio_intelligence=portfolio_intelligence,
            )
            # Exit action
            exit_action = self._build_exit_action_from_holding(
                holding=h,
                candidate=under["candidate"],
                priority=priority_counter[0],
                reason_prefix=(
                    f"Underperforming benchmark (1Y return {under.get('ret_1y','N/A')}%, "
                    f"quality score {under.get('quality_score',0):.1f}/10). "
                ),
                reason_code="UNDERPERFORMER_REPLACEMENT",
            )
            actions.append(exit_action)
            exited_holding_keys.add(h_key)
            if mf.get("instrument_id"):
                exited_ids.add(mf["instrument_id"])
            priority_counter[0] += 1
            # Add action for replacement (if found)
            if replacement:
                add_priority = priority_counter[0]
                exit_amount = h.get("quantity", 0) * h.get("current_price", 0) or mf.get("amount_rs", 0)
                add_action = self._create_add_action_specific(
                    fund_suggestion={
                        "fund_name": replacement.get("scheme_name", "Recommended Fund"),
                        "fund_type": replacement.get("category", "Equity"),
                        "amc": self._extract_amc_from_name(replacement.get("scheme_name", "")) or "",
                        "expense_ratio": replacement.get("expense_ratio"),
                        "aum": f"₹{(replacement.get('aum_cr') or 0):,.0f} Cr" if replacement.get("aum_cr") else "N/A",
                        "rating": "Top-rated in category",
                        "returns_3y": f"{replacement.get('ret_3y','N/A')}%",
                    },
                    priority=add_priority,
                    reason=(
                        f"Replaces underperforming fund. Top ADD score in same category "
                        f"({mf.get('category','Equity')})"
                    ),
                    amount=exit_amount,
                )
                actions.append(add_action)
                priority_counter[0] += 1
                logger.info("[Rule 3] Replace %s → %s", mf.get('scheme_name','')[:30], replacement.get('scheme_name','')[:30])

        # ── RULE 4: Different-Fund Overlap > threshold ──────────────────────
        rule_4_enabled = rules_cfg["rule_4_different_fund_overlap"]["enabled"]
        r4_params = rules_cfg["rule_4_different_fund_overlap"]["params"]
        overlap_threshold = float(r4_params.get("overlap_threshold_pct", 60.0))
        max_overlap_exits = int(r4_params.get("max_overlap_exits", 2))
        pairs = portfolio_intelligence.get("pairwise_overlap", []) if rule_4_enabled else []
        for pair in pairs:
            if pair.get("overlap_pct", 0) < overlap_threshold:
                continue
            id_a, id_b = pair.get("a"), pair.get("b")
            if id_a in exited_ids or id_b in exited_ids:
                continue
            # Skip if these are regular/direct pair of same base scheme (handled by Rule 1)
            name_a = pair.get("a_name", "")
            name_b = pair.get("b_name", "")
            if self._normalize_base_scheme_name(name_a) == self._normalize_base_scheme_name(name_b):
                continue
            # Pick fund with higher exit_score — V3 composite preferred
            cand_a = candidate_by_id.get(id_a)
            cand_b = candidate_by_id.get(id_b)
            legacy_a = cand_a["exit_score"] if cand_a else 5.0
            legacy_b = cand_b["exit_score"] if cand_b else 5.0
            # Use candidate scheme_name if available, else fall back to pair name
            lookup_name_a = (cand_a.get("scheme_name") if cand_a else None) or name_a
            lookup_name_b = (cand_b.get("scheme_name") if cand_b else None) or name_b
            score_a = _v3_exit_rank(id_a, legacy_a, lookup_name_a)
            score_b = _v3_exit_rank(id_b, legacy_b, lookup_name_b)
            if score_a >= score_b:
                victim_cand, victim_name = cand_a, name_a
                partner_name = name_b
            else:
                victim_cand, victim_name = cand_b, name_b
                partner_name = name_a

            # V2.5 — Require positive switch_score: only consolidate if the move
            # actually creates net value (quality gain + cost saving > tax penalty).
            # When we don't have a clean replacement in hand, estimate a proxy:
            # net = |exit_score_of_victim - 5| - (tax_penalty estimated from victim's ti)
            if victim_cand:
                vti = victim_cand.get("tax_impact") or {}
                _tmp = _fuzzy_match_holding(victim_name, mf_holdings)
                exit_amt = (vti.get("exit_amount_rs") or 0) or (
                    (_tmp.get("quantity", 0) * _tmp.get("current_price", 0)) if _tmp else 0
                )
                tax_pct = ((vti.get("tax_liability") or 0) / exit_amt * 10) if exit_amt else 0
                proxy_switch_score = (victim_cand["exit_score"] - 5.0) - tax_pct
                if proxy_switch_score <= 0:
                    logger.info(
                        f"[Rule 4] SKIP overlap exit — proxy switch score {proxy_switch_score:.2f} "
                        f"<= 0 for {victim_name[:40]}"
                    )
                    continue
            h = _fuzzy_match_holding(victim_name, mf_holdings)
            if not h:
                continue
            h_key = _holding_key(h)
            if h_key in exited_holding_keys:
                continue
            reason = (
                f"High overlap ({pair.get('overlap_pct',0):.1f}%, {pair.get('shared_count',0)} shared stocks) "
                f"with {partner_name}. Consolidating by exiting the fund with higher exit score "
                f"({max(score_a, score_b):.1f})."
            )
            action = self._build_exit_action_from_holding(
                holding=h,
                candidate=victim_cand,
                priority=priority_counter[0],
                reason_prefix=reason,
                reason_code="OVERLAP_CONSOLIDATION",
            )
            actions.append(action)
            exited_holding_keys.add(h_key)
            if victim_cand and victim_cand.get("instrument_id"):
                exited_ids.add(victim_cand["instrument_id"])
            priority_counter[0] += 1
            logger.info("[Rule 4] EXIT for overlap: %s vs %s", victim_name[:40], partner_name[:40])
            # Limit to N overlap resolutions to keep plan concise
            if sum(1 for a in actions if "OVERLAP_CONSOLIDATION" in (a.get("reason_codes") or [])) >= max_overlap_exits:
                break

        # ── RULE 5: Asset Allocation Rebalancing (V2.5 Dynamic Debt Target) ─
        rule_5_enabled = rules_cfg["rule_5_debt_allocation"]["enabled"]
        r5_params = rules_cfg["rule_5_debt_allocation"]["params"]
        if rule_5_enabled and portfolio_context["total_value"] > 0:
            asset_allocation = self._calculate_asset_allocation(holdings)
            portfolio_context["asset_allocation"] = asset_allocation
            equity_pct = asset_allocation.get("equity_pct", 0)
            debt_pct = asset_allocation.get("debt_pct", 0)
            # V2.5 — dynamic debt target by risk
            risk = (portfolio_context.get("risk_profile") or "medium").lower()
            if risk in ("conservative", "low"):
                debt_target = float(r5_params.get("debt_target_conservative_pct", 30.0))
            elif risk in ("aggressive", "high"):
                debt_target = float(r5_params.get("debt_target_aggressive_pct", 10.0))
            else:
                debt_target = float(r5_params.get("debt_target_medium_pct", 20.0))
            portfolio_context["debt_target_pct"] = debt_target
            needs_debt = debt_pct < debt_target
            logger.info(
                f"[Rule 5] risk={risk} target={debt_target}% "
                f"equity={equity_pct:.1f}% debt={debt_pct:.1f}% needs_debt={needs_debt}"
            )
            if needs_debt:
                excluded_amcs = [amc for amc, pct in amc_exposure.items() if pct > amc_threshold]
                gap_pct = debt_target - debt_pct
                suggested_amount = portfolio_context["total_value"] * (gap_pct / 100)
                debt_suggestion = self._suggest_debt_fund(suggested_amount, excluded_amcs)
                add_action = self._create_add_action_specific(
                    debt_suggestion,
                    priority_counter[0],
                    f"Portfolio debt is {debt_pct:.0f}% — below your {debt_target:.0f}% target for a {risk} risk profile.",
                    suggested_amount,
                )
                actions.append(add_action)
                priority_counter[0] += 1
                logger.info("[Rule 5] ADD debt fund: %s", debt_suggestion.get('fund_name',''))

        # ── CUSTOM RULES (Phase 2) ──────────────────────────────────────────
        # Custom rules are evaluated last so built-ins take priority.
        custom_rules = rcfg.get("custom_rules", []) or []
        if custom_rules:
            try:
                custom_actions = self._apply_custom_rules(
                    custom_rules=custom_rules,
                    mf_holdings=mf_holdings,
                    mf_investments=mf_investments,
                    holdings=holdings,
                    portfolio_intelligence=portfolio_intelligence,
                    portfolio_context=portfolio_context,
                    amc_exposure=amc_exposure,
                    exit_candidates=exit_candidates,
                    candidate_by_id=candidate_by_id,
                    exited_ids=exited_ids,
                    exited_holding_keys=exited_holding_keys,
                    priority_counter=priority_counter,
                )
                actions.extend(custom_actions)
            except Exception as e:  # noqa: BLE001
                logger.warning("custom rules evaluation failed: %s", e)

        # Fallback: if no actions produced by rules, fall back to top exit candidates
        if not actions and exit_candidates:
            logger.info("[Fallback] No rule-based actions produced; using top exit candidates")
            for candidate in exit_candidates[:2]:
                action = self._create_exit_action_with_tax_analysis(candidate, priority_counter[0], None)
                actions.append(action)
                priority_counter[0] += 1

        # ── V3 Phase 2: Stamp composite scores onto EXIT actions ────────────
        # Each EXIT action carries (quality / health / exit / add) for its target
        # fund so the UI / audit log / action card can surface it.
        for a in actions:
            iid = a.get("instrument_id") or (a.get("target") or {}).get("instrument_id")
            name = a.get("asset_name") or a.get("fund_name") or a.get("scheme_name") \
                or (a.get("target") or {}).get("fund_name")
            v3 = v3_integration.lookup_v3(iid, name, v3_scores_by_id)
            if v3:
                a["v3_scores"] = {
                    "quality": v3.get("quality_score"),
                    "health": v3.get("health_score"),
                    "exit": v3.get("exit_score"),
                    "add": v3.get("add_score"),
                    "quality_missing": v3.get("quality_missing"),
                    "health_missing": v3.get("health_missing"),
                }
                if v3.get("guardrail_reasons"):
                    a["v3_guardrail_reasons"] = v3["guardrail_reasons"]

        logger.info(
            f"Rule engine produced {len(actions)} actions "
            f"(V3 enrichment: {len(v3_scores_by_id)} funds scored, "
            f"{dropped_by_guardrail} blocked by guardrails)"
        )
        return actions

    def _apply_custom_rules(
        self,
        custom_rules: List[Dict[str, Any]],
        mf_holdings: List[Dict[str, Any]],
        mf_investments: List[Dict[str, Any]],
        holdings: List[Dict[str, Any]],
        portfolio_intelligence: Dict[str, Any],
        portfolio_context: Dict[str, Any],
        amc_exposure: Dict[str, float],
        exit_candidates: List[Dict[str, Any]],
        candidate_by_id: Dict[str, Any],
        exited_ids: set,
        exited_holding_keys: set,
        priority_counter: List[int],
    ) -> List[Dict[str, Any]]:
        """Evaluate admin-defined custom rules via the safe DSL.

        Each rule: {id, name, enabled, expression, action_type, target, reason_code, reason_text}
        action_type ∈ {"EXIT_HIGHEST_EXIT_SCORE", "ADD_DEBT_FUND", "FLAG_ONLY"}
        target scope: dict with optional filters (category, amc) for EXIT_* rules.

        The expression is evaluated against a flat context:
            portfolio_score, confidence_score, total_value,
            equity_pct, debt_pct, gold_pct,
            max_category_pct, max_amc_pct, avg_overlap_pct,
            mf_count, stock_count, fund_count
        """
        from services.rules_dsl import safe_eval, SafeEvalError

        # Build evaluation context
        alloc = self._calculate_asset_allocation(holdings)
        total_mf = sum((m.get("amount_rs") or 0) for m in mf_investments) or 0
        cat_pcts: Dict[str, float] = {}
        for m in mf_investments:
            cn = (m.get("category") or "Uncategorised").strip() or "Uncategorised"
            cat_pcts[cn] = cat_pcts.get(cn, 0) + ((m.get("amount_rs") or 0) / total_mf * 100 if total_mf else 0)
        pairs = portfolio_intelligence.get("pairwise_overlap", []) or []
        avg_overlap = sum(p.get("overlap_pct", 0) for p in pairs) / max(len(pairs), 1)

        ctx = {
            "portfolio_score": portfolio_context.get("portfolio_score", 0),
            "confidence_score": portfolio_context.get("confidence_score", 0),
            "total_value": portfolio_context.get("total_value", 0),
            "equity_pct": alloc.get("equity_pct", 0),
            "debt_pct": alloc.get("debt_pct", 0),
            "gold_pct": alloc.get("gold_pct", 0),
            "max_category_pct": max(cat_pcts.values()) if cat_pcts else 0,
            "max_amc_pct": max(amc_exposure.values()) if amc_exposure else 0,
            "avg_overlap_pct": round(avg_overlap, 2),
            "mf_count": portfolio_context.get("mf_count", 0),
            "stock_count": portfolio_context.get("stock_count", 0),
            "fund_count": len(mf_investments),
        }

        out: List[Dict[str, Any]] = []
        for rule in custom_rules:
            if not rule.get("enabled", True):
                continue
            rid = rule.get("id", rule.get("name", "custom"))
            expr = rule.get("expression", "")
            try:
                matched = bool(safe_eval(expr, ctx))
            except SafeEvalError as e:
                logger.warning("[Custom:%s] expression error: %s", rid, e)
                continue
            if not matched:
                logger.info("[Custom:%s] condition not met", rid)
                continue

            action_type = rule.get("action_type", "FLAG_ONLY")
            reason_code = rule.get("reason_code", f"CUSTOM_{rid.upper()}")
            reason_text = rule.get("reason_text") or rule.get("name") or "Custom rule"
            target = rule.get("target") or {}

            if action_type == "FLAG_ONLY":
                # Per gap-analysis Finding C.8: dual id + action_id for backward compat.
                custom_id = f"custom-{rid}-{priority_counter[0]}"
                out.append({
                    "id": custom_id,
                    "action_id": custom_id,
                    "type": "REVIEW",
                    "asset_name": "Portfolio",
                    "asset_type": "portfolio",
                    "priority": priority_counter[0],
                    "reason_text": reason_text,
                    "reason_codes": [reason_code],
                    "source": "custom_rule",
                    "custom_rule_id": rid,
                })
                priority_counter[0] += 1
                logger.info("[Custom:%s] FLAG: %s", rid, reason_text[:60])
                continue

            if action_type == "ADD_DEBT_FUND":
                excluded_amcs = [a for a, p in amc_exposure.items() if p > 15.0]
                amount = float(target.get("amount_rs", 0) or (portfolio_context.get("total_value", 0) * 0.05))
                debt = self._suggest_debt_fund(amount, excluded_amcs)
                add_action = self._create_add_action_specific(debt, priority_counter[0], reason_text, amount)
                add_action["reason_codes"] = [reason_code]
                add_action["source"] = "custom_rule"
                add_action["custom_rule_id"] = rid
                out.append(add_action)
                priority_counter[0] += 1
                logger.info("[Custom:%s] ADD_DEBT_FUND: %s", rid, debt.get('fund_name',''))
                continue

            if action_type == "EXIT_HIGHEST_EXIT_SCORE":
                cat_filter = (target.get("category") or "").strip().lower()
                amc_filter = (target.get("amc") or "").strip().lower()
                cand_mfs = [
                    m for m in mf_investments
                    if (not cat_filter or (m.get("category") or "").strip().lower() == cat_filter)
                    and (not amc_filter or self._extract_amc_from_name(m.get("scheme_name", "")).lower() == amc_filter)
                    and m.get("instrument_id") not in exited_ids
                ]
                ranked = []
                for mf in cand_mfs:
                    cand = candidate_by_id.get(mf.get("instrument_id"))
                    score = cand["exit_score"] if cand else 5.0
                    ranked.append({"mf": mf, "candidate": cand, "exit_score": score})
                ranked.sort(key=lambda x: x["exit_score"], reverse=True)

                max_exits = int(target.get("max_exits", 1))
                exits_made = 0
                for item in ranked:
                    if exits_made >= max_exits:
                        break
                    mf = item["mf"]
                    h = _fuzzy_match_holding(mf.get("scheme_name", ""), mf_holdings)
                    if not h:
                        continue
                    h_key = f"{h.get('user_id','')}::{_normalize_fund_name(h.get('name',''))}"
                    if h_key in exited_holding_keys:
                        continue
                    action = self._build_exit_action_from_holding(
                        holding=h, candidate=item["candidate"],
                        priority=priority_counter[0], reason_prefix=reason_text,
                        reason_code=reason_code,
                    )
                    action["source"] = "custom_rule"
                    action["custom_rule_id"] = rid
                    out.append(action)
                    exited_holding_keys.add(h_key)
                    if mf.get("instrument_id"):
                        exited_ids.add(mf["instrument_id"])
                    priority_counter[0] += 1
                    exits_made += 1
                    logger.info("[Custom:%s] EXIT %s", rid, mf.get('scheme_name','')[:40])

        return out

    # ── Rule helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _classify_plan_type(name: str) -> str:
        """Classify fund as 'direct' or 'regular' based on its scheme name.

        Returns 'direct' only on strong indicators, otherwise 'regular'.
        """
        if not name:
            return "regular"
        lowered = name.lower()
        direct_phrases = [
            "direct plan", "direct growth", "direct - growth", "- direct -",
            "- direct", "(direct)", "dir plan", "dir growth",
        ]
        if any(p in lowered for p in direct_phrases):
            return "direct"
        tokens = lowered.replace(",", " ").replace("-", " ").replace("(", " ").replace(")", " ").split()
        if "direct" in tokens or "dir" in tokens:
            return "direct"
        return "regular"

    @staticmethod
    def _normalize_base_scheme_name(name: str) -> str:
        """Strip plan-type/option keywords to get the base scheme name.

        Example: "HDFC Flexi Cap Fund - Direct Plan - Growth" → "hdfc flexi cap fund"
        """
        if not name:
            return ""
        stop_tokens = {
            "direct", "regular", "growth", "idcw", "dividend",
            "payout", "reinvestment", "plan", "option", "div",
            "g", "d", "dir", "reg",
        }
        cleaned = (
            name.lower()
            .replace(",", " ")
            .replace("-", " ")
            .replace("(", " ")
            .replace(")", " ")
        )
        tokens = [t for t in cleaned.split() if t and t not in stop_tokens]
        return " ".join(tokens).strip()

    def _find_regular_direct_pairs(self, mf_holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group MF holdings by base scheme name; return those where BOTH Regular and Direct exist."""
        groups: Dict[str, Dict[str, Any]] = {}
        for h in mf_holdings:
            base = self._normalize_base_scheme_name(h.get("name", ""))
            if not base:
                continue
            plan_type = self._classify_plan_type(h.get("name", ""))
            g = groups.setdefault(base, {"regular": None, "direct": None, "base_name": base})
            if plan_type == "direct" and g["direct"] is None:
                g["direct"] = h
            elif plan_type == "regular" and g["regular"] is None:
                g["regular"] = h
        return [g for g in groups.values() if g["regular"] and g["direct"]]

    def _find_regular_without_direct_pair(
        self, mf_holdings: List[Dict[str, Any]], existing_pairs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return Regular-plan holdings that do NOT have a Direct counterpart in portfolio."""
        paired_bases = {p["base_name"] for p in existing_pairs}
        out = []
        for h in mf_holdings:
            base = self._normalize_base_scheme_name(h.get("name", ""))
            if not base or base in paired_bases:
                continue
            if self._classify_plan_type(h.get("name", "")) == "regular":
                out.append(h)
        return out

    def _estimate_cost_leak(
        self,
        regular_holding: Dict[str, Any],
        direct_holding: Optional[Dict[str, Any]],
        mf_investments: List[Dict[str, Any]],
    ) -> float:
        """Estimate annual cost leak (₹/yr) from holding Regular instead of Direct.

        cost_leak ≈ regular_value * (regular_er - direct_er) / 100
        When direct expense ratio is unknown, assume Direct is ~0.7% cheaper than Regular
        (industry average for active equity funds).
        """
        def _find_mf(h: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            h_norm = _normalize_fund_name(h.get("name", ""))
            for mf in mf_investments:
                if _normalize_fund_name(mf.get("scheme_name", "")) == h_norm:
                    return mf
            return None

        reg_mf = _find_mf(regular_holding)
        if not reg_mf:
            return 0.0
        reg_er = reg_mf.get("expense_ratio")
        if reg_er is None:
            reg_er = 1.5  # typical Regular equity fund default
        reg_er = float(reg_er)

        dir_er: Optional[float] = None
        if direct_holding:
            dir_mf = _find_mf(direct_holding)
            if dir_mf and dir_mf.get("expense_ratio") is not None:
                dir_er = float(dir_mf["expense_ratio"])
        if dir_er is None:
            dir_er = max(0.3, reg_er - 0.7)

        diff = max(0.0, reg_er - dir_er)
        reg_value = float(regular_holding.get("quantity", 0) or 0) * float(regular_holding.get("current_price", 0) or 0)
        if reg_value <= 0:
            reg_value = float(reg_mf.get("amount_rs", 0) or 0)
        return round(reg_value * diff / 100.0, 2)

    def _find_underperformers(
        self,
        mf_investments: List[Dict[str, Any]],
        portfolio_intelligence: Dict[str, Any],
        exit_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Detect underperforming funds using quality score and 1Y return heuristics."""
        catalog = portfolio_intelligence.get("catalog", {})
        candidate_by_id = {c.get("instrument_id"): c for c in exit_candidates if c.get("instrument_id")}
        out = []
        for mf in mf_investments:
            if not mf.get("resolved"):
                continue
            cand = candidate_by_id.get(mf.get("instrument_id"))
            if not cand:
                continue
            quality = cand.get("score_breakdown", {}).get("quality", 5.0)
            fund_data = catalog.get(mf.get("instrument_id"), {})
            ratios = fund_data.get("ratios", {})
            ret_1y = ratios.get("ret_1y")
            ret_3y = ratios.get("ret_3y")
            ret_1y_val = float(ret_1y) if ret_1y is not None else None
            ret_3y_val = float(ret_3y) if ret_3y is not None else None
            # V2.5 stricter: weak quality (raw >= 6.5, i.e. "higher=better" < 5)
            # AND underperformance in BOTH 1Y & 3Y vs 8%/10% benchmarks.
            weak_q = quality >= 6.5
            weak_1y = ret_1y_val is not None and ret_1y_val < 8.0
            weak_3y = ret_3y_val is not None and ret_3y_val < 10.0
            # When 3Y data is absent, fall back to 1Y-only (graceful degradation)
            underperf = weak_1y and (weak_3y or ret_3y_val is None)
            if weak_q and underperf:
                out.append({
                    "mf": mf,
                    "candidate": cand,
                    "quality_score": quality,
                    "ret_1y": round(ret_1y_val, 2) if ret_1y_val is not None else "N/A",
                    "ret_3y": round(ret_3y_val, 2) if ret_3y_val is not None else "N/A",
                })
        # Rank by worst quality first (highest = worst)
        out.sort(key=lambda x: (x["quality_score"], -(x["ret_1y"] if isinstance(x["ret_1y"], (int, float)) else -100)), reverse=True)
        return out

    def _find_best_same_category_replacement(
        self,
        category: Optional[str],
        excluded_ids: set,
        mf_investments: List[Dict[str, Any]],
        portfolio_intelligence: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Find the best-rated fund in the same category from Postgres instrument_master.

        Priority:
          1. Prefer Direct-plan, high-rated (high 3Y return, low expense ratio) funds
          2. Exclude funds user already holds OR already marked for exit
        """
        if not category:
            return None
        held_ids = {m.get("instrument_id") for m in mf_investments if m.get("instrument_id")}
        try:
            from services import pg_client
            import asyncio
            # NOTE: this method is sync; use a small sync wrapper via event loop
            # Caller is inside async context, so we fire an async query
        except Exception:
            return None

        # Synchronous fallback — just suggest a generic top fund name
        # (production: wire up a proper DB query here)
        category_norm = (category or "").lower()
        # Simple hard-coded top fund map by category (used when PG query not available)
        top_fund_map = {
            "large cap": {
                "scheme_name": "Nippon India Large Cap Fund - Direct Growth",
                "category": "Large Cap",
                "expense_ratio": 0.71,
                "aum_cr": 28000,
                "ret_3y": 18.5,
            },
            "small cap": {
                "scheme_name": "Nippon India Small Cap Fund - Direct Growth",
                "category": "Small Cap",
                "expense_ratio": 0.68,
                "aum_cr": 45000,
                "ret_3y": 28.2,
            },
            "mid cap": {
                "scheme_name": "Motilal Oswal Midcap Fund - Direct Growth",
                "category": "Mid Cap",
                "expense_ratio": 0.65,
                "aum_cr": 9500,
                "ret_3y": 32.1,
            },
            "flexi cap": {
                "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Growth",
                "category": "Flexi Cap",
                "expense_ratio": 0.63,
                "aum_cr": 62000,
                "ret_3y": 20.4,
            },
            "elss": {
                "scheme_name": "Quant ELSS Tax Saver Fund - Direct Growth",
                "category": "ELSS",
                "expense_ratio": 0.76,
                "aum_cr": 9800,
                "ret_3y": 23.5,
            },
        }
        for key, fund in top_fund_map.items():
            if key in category_norm:
                # Tag with synthetic id so excluded set check works
                fund_copy = {**fund, "instrument_id": f"recommendation::{key}"}
                if fund_copy["instrument_id"] in excluded_ids:
                    continue
                if fund_copy["instrument_id"] in held_ids:
                    continue
                return fund_copy
        return None

    def _build_exit_action_from_holding(
        self,
        holding: Dict[str, Any],
        candidate: Optional[Dict[str, Any]],
        priority: int,
        reason_prefix: str,
        reason_code: str,
    ) -> Dict[str, Any]:
        """Build an EXIT action, using pre-computed exit_candidate if available.

        Falls back to a minimal action when no candidate exists (e.g., unresolved MF).
        """
        if candidate:
            action = self._create_exit_action_with_tax_analysis(candidate, priority, None)
            # Prepend rule-specific reason
            existing = action.get("reason_text", "")
            action["reason_text"] = f"{reason_prefix} {existing}".strip()
            # Ensure reason_codes includes our rule code
            codes = list(action.get("reason_codes") or [])
            if reason_code not in codes:
                codes.insert(0, reason_code)
            action["reason_codes"] = codes
            return action
        # No scored candidate — build minimal action from holding
        amount = float(holding.get("quantity", 0) or 0) * float(holding.get("current_price", 0) or 0)
        # Best-effort tax impact using holding-only data (no capital gain if buy_price missing)
        try:
            from services import tax_calculator
            tax_impact = tax_calculator.calculate_tax_impact(holding)
        except Exception as _e:
            logger.debug("tax_calculator failed for minimal action: %s", _e)
            tax_impact = None
        return {
            "action_id": f"act_{uuid4().hex[:8]}",
            "type": "EXIT",
            "priority": priority,
            "asset_type": "mutual_fund",
            "asset_name": holding.get("name", "Unknown"),
            "instrument_id": None,
            "amount": round(amount, 2),
            "exit_score": None,
            "confidence": "MEDIUM",
            "reason_text": reason_prefix,
            "reason_codes": [reason_code],
            "status": "PENDING",
            "score_breakdown": None,
            "tax_impact": tax_impact,
            "fundamentals": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


    def _create_exit_action_with_tax_analysis(
        self,
        candidate: Dict[str, Any],
        priority: int,
        overlap_signal: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create EXIT action with tax cost vs benefit analysis.
        
        Highlights if tax cost > exit benefit (not advisable to exit).
        """
        # Extract data from candidate (exit_result includes mf_investment, holding, tax_impact)
        mf_investment = candidate.get("mf_investment", {})
        holding = candidate.get("holding", {})
        tax_impact = candidate.get("tax_impact") or {}

        # Calculate amount from MF investment
        exit_amount = mf_investment.get("amount_rs", 0)
        if exit_amount == 0:
            # Fallback: calculate from holding
            exit_amount = holding.get("quantity", 0) * holding.get("current_price", 0)

        # If candidate didn't pre-compute tax_impact, do it now from the
        # holding — otherwise every EXIT action would carry tax=0.
        if not tax_impact or "tax_liability" not in tax_impact:
            try:
                from services import tax_calculator as _tc
                tax_impact = _tc.calculate_tax_impact(holding, exit_amount_rs=exit_amount) or {}
            except Exception as _e:
                logger.debug("fallback tax_impact calc failed: %s", _e)
                tax_impact = {}
        
        tax_liability = tax_impact.get("tax_liability", 0)
        post_tax_proceeds = tax_impact.get("post_tax_proceeds", exit_amount - tax_liability)
        capital_gain = tax_impact.get("capital_gain", 0)
        
        # Calculate benefit: Capital gain - tax
        net_benefit = capital_gain - tax_liability if capital_gain > 0 else -tax_liability
        
        # Determine if exit is advisable
        tax_efficient = True
        exit_warning = None
        
        if capital_gain > 0 and tax_liability > capital_gain * 0.5:
            # Tax is more than 50% of gain - NOT advisable
            tax_efficient = False
            exit_warning = f"⚠️ Tax cost (₹{tax_liability:,.0f}) is {(tax_liability/capital_gain*100):.0f}% of your gain. Consider holding longer for better tax efficiency."
        elif capital_gain <= 0 and tax_liability > 0:
            # Loss-making position with tax - NOT advisable
            tax_efficient = False
            exit_warning = f"⚠️ This fund is in loss. Exiting now will incur ₹{tax_liability:,.0f} in taxes with no capital gain. Not recommended."
        elif exit_amount > 0 and tax_liability > exit_amount * 0.15:
            # Tax > 15% of total value - CAUTION
            tax_efficient = False
            exit_warning = f"⚠️ High tax impact: ₹{tax_liability:,.0f} ({(tax_liability/exit_amount*100):.1f}% of total value). Evaluate if exit benefit justifies the cost."
        
        # Build reason with overlap context
        reason_text = " • ".join(candidate.get("reasons", []))
        if overlap_signal:
            overlap_pct = overlap_signal.get("details", {}).get("max_overlap_pct", 0)
            reason_text = f"High overlap ({overlap_pct:.1f}%) with other funds. {reason_text}"
        
        return {
            "action_id": f"act_{uuid4().hex[:8]}",
            "type": "EXIT",
            "priority": priority,
            "asset_type": "mutual_fund",
            "asset_name": candidate.get("instrument_name", mf_investment.get("scheme_name", "Unknown")),
            "instrument_id": candidate.get("instrument_id"),
            "amount": exit_amount,
            "exit_score": candidate.get("exit_score"),
            "confidence": candidate.get("confidence"),
            "reason_text": reason_text,
            "reason_codes": candidate.get("reasons", []),
            "status": "PENDING",
            "score_breakdown": candidate.get("score_breakdown"),
            "tax_impact": {
                **tax_impact,
                "net_benefit": net_benefit,
                "tax_efficient": tax_efficient,
                "exit_warning": exit_warning,
            },
            "fundamentals": candidate.get("fundamentals"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    
    def _create_exit_action(self, candidate: Dict[str, Any], priority: int) -> Dict[str, Any]:
        """Create EXIT action from candidate (legacy - use _create_exit_action_with_tax_analysis)."""
        return {
            "action_id": f"act_{uuid4().hex[:8]}",
            "type": "EXIT",
            "priority": priority,
            "asset_type": candidate.get("asset_type", "mutual_fund"),
            "asset_name": candidate.get("scheme_name", "Unknown"),
            "instrument_id": candidate.get("isin"),
            "amount": candidate.get("current_value", 0),
            "exit_score": candidate.get("exit_score"),
            "confidence": candidate.get("confidence"),
            "reason_text": candidate.get("reason_text", ""),
            "reason_codes": candidate.get("reasons", []),
            "status": "PENDING",
            "score_breakdown": candidate.get("score_breakdown"),
            "tax_impact": candidate.get("tax_impact"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    
    async def refresh_plan(
        self,
        user_id: str
    ) -> Dict[str, Any]:
        """Refresh existing plan (create new version, archive old)."""
        # Get current active plan
        current_plan = await self.get_active_plan(user_id)
        
        if current_plan:
            # Archive current plan
            await self.archive_plan(
                current_plan["plan_id"],
                user_id,
                reason="portfolio_updated"
            )
            
            parent_plan_id = current_plan["plan_id"]
            new_version = current_plan["version"] + 1
        else:
            parent_plan_id = None
            new_version = 1
        
        # Fetch fresh data — with V3 Postgres fallback for V4 users
        holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
        if not holdings:
            from services.pi_bridge import pi_holdings_for_user  # noqa: WPS433
            holdings = await pi_holdings_for_user(user_id)
        from services import portfolio_intelligence
        intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
        
        # Generate new plan
        new_plan = await self.generate_plan(user_id, intelligence, holdings)
        new_plan["version"] = new_version
        new_plan["metadata"]["parent_plan_id"] = parent_plan_id
        
        # Save directly as active (skip preview)
        new_plan["status"] = STATUS_ACTIVE
        await self.create_plan(new_plan)
        
        logger.info("Plan refreshed: v%s", new_version)
        return new_plan
    
    # ══════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════════════════
    
    def _create_exit_action(
        self,
        exit_result: Dict[str, Any],
        priority: int,
    ) -> Dict[str, Any]:
        """Create EXIT action from exit scoring result."""
        instrument_type = exit_result.get("instrument_type", "mutual_fund")
        
        if instrument_type == "mutual_fund":
            mf = exit_result["mf_investment"]
            holding = exit_result["holding"]
            amount = mf.get("amount_rs", 0)
            asset_name = mf.get("scheme_name")
            asset_id = mf.get("instrument_id")
        else:  # equity
            stock = exit_result["stock_holding"]
            amount = stock["quantity"] * stock["current_price"]
            asset_name = stock.get("name")
            asset_id = stock.get("holding_id")
        
        return {
            "action_id": f"exit_{priority}",
            "type": "EXIT",
            "priority": priority,
            "asset_type": instrument_type,
            "asset_name": asset_name,
            "asset_id": asset_id,
            "amount": round(amount, 2),
            "confidence": exit_result["confidence"],
            "exit_score": exit_result["exit_score"],
            "reason_codes": exit_result["reasons"],
            "reason_text": self._generate_reason_text(exit_result),
            "tax_impact": exit_result["tax_impact"],
            "status": ACTION_PENDING,
            "completed_at": None,
            "skipped_at": None,
        }
    
    def _create_add_action_generic(
        self,
        asset_class: str,
        target_amount: float,
        reason: str,
        priority: int,
    ) -> Dict[str, Any]:
        """Create generic ADD action for asset allocation gap."""
        return {
            "action_id": f"add_{priority}",
            "type": "ADD",
            "priority": priority,
            "asset_type": "mutual_fund",
            "asset_name": f"Recommended {asset_class.title()} Fund (TBD)",
            "asset_id": None,
            "amount": round(target_amount, 2),
            "confidence": "HIGH",
            "add_score": 7.5,  # Placeholder
            "reason_codes": ["ALLOCATION_IMBALANCE"],
            "reason_text": reason,
            "tax_impact": None,  # No tax for new investments
            "status": ACTION_PENDING,
            "completed_at": None,
            "skipped_at": None,
        }
    
    def _generate_reason_text(self, score_result: Dict[str, Any]) -> str:
        """Generate human-readable reason from scoring result."""
        reasons = score_result.get("reasons", [])
        if not reasons:
            return "Optimization opportunity identified"
        
        reason_map = {
            "HIGH_OVERLAP": "High overlap with other funds",
            "HIGH_TAX_IMPACT": "Significant tax liability",
            "HIGH_COST": "High expense ratio",
            "WEAK_PERFORMANCE": "Underperforming vs category",
            "OVEREXPOSURE": "Overconcentrated position",
            "NEGATIVE_MOMENTUM": "Negative price momentum",
            "WEAK_FUNDAMENTALS": "Weak fundamentals",
        }
        
        texts = [reason_map.get(r, r) for r in reasons]
        return " • ".join(texts)
    
    def _calculate_asset_allocation(self, holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate current asset allocation percentages."""
        total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
        
        equity_value = sum(
            h["quantity"] * h["current_price"]
            for h in holdings
            if h.get("asset_type", "").lower() in ["equity", "stock", "mutual_fund", "mutual fund"]
        )
        
        debt_value = sum(
            h["quantity"] * h["current_price"]
            for h in holdings
            if h.get("asset_type", "").lower() in ["debt"]
        )
        
        gold_value = sum(
            h["quantity"] * h["current_price"]
            for h in holdings
            if h.get("asset_type", "").lower() in ["gold"]
        )
        
        return {
            "equity_pct": round(equity_value / total_value * 100, 2) if total_value > 0 else 0,
            "debt_pct": round(debt_value / total_value * 100, 2) if total_value > 0 else 0,
            "gold_pct": round(gold_value / total_value * 100, 2) if total_value > 0 else 0,
        }
    
    # ══════════════════════════════════════════════════════════════════════
    # V2.5 — Portfolio Health Score / Confidence / Plan Summary / Improvements
    # ══════════════════════════════════════════════════════════════════════

    def _calculate_portfolio_health_score(
        self,
        portfolio_intelligence: Dict[str, Any],
        holdings: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
    ) -> tuple:
        """Portfolio Health Score (0-100). Higher = healthier.

        25% Diversification · 25% Overlap reduction · 20% AMC concentration
        15% Cost efficiency · 15% Asset allocation balance
        """
        mfs = portfolio_intelligence.get("mf_investments") or []
        unique_cats = len({(m.get("category") or "").lower() for m in mfs if m.get("category")})
        div_score = min(100.0, unique_cats * 20)

        pairs = portfolio_intelligence.get("pairwise_overlap") or []
        max_ov = max((p.get("overlap_pct", 0) or 0 for p in pairs), default=0)
        overlap_score = max(0.0, 100.0 - max_ov)

        amc_exposure = portfolio_intelligence.get("amc_exposure") or {}
        total_mf = sum(amc_exposure.values()) or 1
        top_amc_pct = (max(amc_exposure.values()) / total_mf * 100) if amc_exposure else 0
        if top_amc_pct <= 15: amc_score = 100.0
        elif top_amc_pct <= 25: amc_score = 75.0
        elif top_amc_pct <= 40: amc_score = 45.0
        else: amc_score = 15.0

        total_corpus = sum((m.get("amount_rs") or 0) for m in mfs) or 1
        weighted_er = sum(
            ((m.get("amount_rs") or 0) * (m.get("expense_ratio") or 0)) for m in mfs
        ) / total_corpus if total_corpus > 0 else 0
        if weighted_er <= 0.5: cost_score = 100.0
        elif weighted_er <= 1.0: cost_score = 75.0
        elif weighted_er <= 1.5: cost_score = 50.0
        else: cost_score = 25.0

        alloc = portfolio_intelligence.get("asset_allocation") or {}
        eq = alloc.get("equity_pct", 0) or 0
        dt = alloc.get("debt_pct", 0) or 0
        gd = alloc.get("gold_pct", 0) or 0
        dist = abs(eq - 60) + abs(dt - 25) + abs(gd - 10)
        alloc_score = max(0.0, 100.0 - dist)

        total = (
            0.25 * div_score + 0.25 * overlap_score + 0.20 * amc_score +
            0.15 * cost_score + 0.15 * alloc_score
        )
        return round(total, 1), {
            "diversification": round(div_score, 1),
            "overlap": round(overlap_score, 1),
            "amc_concentration": round(amc_score, 1),
            "cost_efficiency": round(cost_score, 1),
            "asset_allocation": round(alloc_score, 1),
        }

    def _calculate_confidence_score(
        self,
        portfolio_intelligence: Dict[str, Any],
        holdings: List[Dict[str, Any]],
        actions: List[Dict[str, Any]],
    ) -> tuple:
        """Confidence Score (0-100) — how trustworthy is this plan?"""
        degraded = bool(portfolio_intelligence.get("degraded"))
        system_health = 50.0 if degraded else 95.0

        total_h = len(holdings) or 1
        with_date = sum(1 for h in holdings if h.get("buy_date"))
        data_completeness = (with_date / total_h) * 100

        exit_actions = [a for a in actions if a.get("type") in ("EXIT", "SELL", "SWITCH")]
        if exit_actions:
            tax_certain = sum(
                1 for a in exit_actions
                if a.get("tax_impact") and not a.get("tax_impact", {}).get("tax_impact_pending")
            )
            tax_cert = (tax_certain / len(exit_actions)) * 100
        else:
            tax_cert = 100.0

        freshness = 100.0
        total = (
            0.35 * system_health + 0.25 * data_completeness +
            0.25 * tax_cert + 0.15 * freshness
        )
        label = "High" if total >= 80 else ("Medium" if total >= 60 else "Low")
        return round(total, 1), {
            "system_health": round(system_health, 1),
            "data_completeness": round(data_completeness, 1),
            "tax_certainty": round(tax_cert, 1),
            "freshness": round(freshness, 1),
            "label": label,
        }

    def _compute_improvements(
        self,
        portfolio_intelligence: Dict[str, Any],
        actions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pairs = portfolio_intelligence.get("pairwise_overlap") or []
        before_overlap = max((p.get("overlap_pct", 0) or 0 for p in pairs), default=0)
        cuts = sum(
            1 for a in actions
            if any(r in (a.get("reason_codes") or [])
                   for r in ("OVERLAP_CONSOLIDATION", "UNDERPERFORMER_REPLACEMENT"))
        )
        after_overlap = max(0, before_overlap - 15 * cuts)

        # AMC concentration: portfolio_intelligence doesn't expose
        # amc_exposure, so compute it inline from mf_investments using
        # the same extractor used by the action-rule path. Without this
        # fallback, before_amc was always 0 and the dashboard showed
        # "0% → 0%" regardless of how concentrated the portfolio was.
        amc_exposure = portfolio_intelligence.get("amc_exposure") or {}
        if not amc_exposure:
            mfis = portfolio_intelligence.get("mf_investments") or []
            total_mf_val = sum(float(m.get("amount_rs") or 0) for m in mfis)
            if total_mf_val > 0:
                amc_exposure = self._calculate_amc_exposure_from_mf_investments(
                    mfis, total_mf_val,
                )
        before_amc = max(amc_exposure.values()) if amc_exposure else 0.0
        amc_cuts = sum(
            1 for a in actions
            if "AMC_CONCENTRATION_EXIT" in (a.get("reason_codes") or [])
        )
        after_amc = max(0.0, before_amc - 8 * amc_cuts)

        cost_saving_yr = 0.0
        for a in actions:
            if any(r in (a.get("reason_codes") or []) for r in ("REGULAR_DIRECT_DUPLICATE", "COST_LEAK_SWITCH")):
                amt = float(a.get("amount") or a.get("exit_amount_rs") or 0)
                er_delta = float(a.get("er_delta_pct") or 0.75) / 100
                cost_saving_yr += amt * er_delta

        # Debt projection: count both legacy ALLOCATION_GAP adds AND
        # Decision Engine drift-driven debt ADDs (DEBT_UNDERWEIGHT) so
        # the dashboard arrow reflects the full plan, not just one
        # rule's contribution.
        alloc = portfolio_intelligence.get("asset_allocation") or {}
        before_debt = alloc.get("debt_pct", 0) or 0
        total_val = portfolio_intelligence.get("total_value") or 0
        after_debt = before_debt
        for a in actions:
            codes = a.get("reason_codes") or []
            counted = False
            # Legacy: explicit ALLOCATION_GAP + asset_type filter
            if "ALLOCATION_GAP" in codes and a.get("asset_type") in (
                "mutual_fund", "bond", "debt",
            ):
                counted = True
            # Decision Engine: any debt-underweight ADD
            elif a.get("type") == "ADD" and "DEBT_UNDERWEIGHT" in codes:
                counted = True
            if counted and total_val > 0:
                after_debt += (float(a.get("amount") or 0) / total_val) * 100

        return {
            "overlap_pct": {"before": round(before_overlap, 1), "after": round(after_overlap, 1)},
            "top_amc_pct": {"before": round(before_amc, 1), "after": round(after_amc, 1)},
            "debt_pct":    {"before": round(before_debt, 1), "after": round(after_debt, 1)},
            "annual_cost_saving_rs": round(cost_saving_yr, 0),
        }

    def _generate_plan_summary(
        self,
        actions: List[Dict[str, Any]],
        portfolio_score: float,
        total_tax_impact: Dict[str, Any],
        portfolio_intelligence: Dict[str, Any],
        do_nothing: bool,
    ) -> str:
        if do_nothing:
            return (
                f"Your portfolio scores {portfolio_score:.0f}/100 — healthy. "
                "Nothing to fix right now. Stay invested, review next quarter."
            )
        imp = self._compute_improvements(portfolio_intelligence, actions)
        bits = [f"{len(actions)} action{'s' if len(actions) != 1 else ''} to improve your portfolio score."]
        # Only emit overlap/AMC deltas when the plan actually moves the needle
        if (imp["overlap_pct"]["before"] - imp["overlap_pct"]["after"]) >= 5:
            bits.append(f"Reduce overlap {imp['overlap_pct']['before']:.0f}% → {imp['overlap_pct']['after']:.0f}%.")
        if (imp["top_amc_pct"]["before"] - imp["top_amc_pct"]["after"]) >= 3:
            bits.append(f"Cut AMC concentration {imp['top_amc_pct']['before']:.0f}% → {imp['top_amc_pct']['after']:.0f}%.")
        if imp["annual_cost_saving_rs"] > 0:
            bits.append(f"Save ₹{imp['annual_cost_saving_rs']:,.0f}/yr in costs.")
        if (imp["debt_pct"]["after"] - imp["debt_pct"]["before"]) >= 1:
            bits.append(f"Raise debt from {imp['debt_pct']['before']:.0f}% → {imp['debt_pct']['after']:.0f}%.")
        tax_liab = total_tax_impact.get("total_tax_liability") or total_tax_impact.get("total_tax") or 0
        if tax_liab > 0:
            bits.append(f"Est. tax impact: ₹{tax_liab:,.0f}.")
        return " ".join(bits)


    def _calculate_total_tax_impact(self, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate total tax impact across all EXIT actions.

        Uses ClearTax FY 2025-26 rates (see services/tax_calculator.py):
          Equity LTCG 12.5% on gains > ₹1.25L
          Equity STCG 20%
          Non-equity LTCG 12.5%, STCG at slab (default 30%)

        Pending entries (missing buy_date) are counted separately so the plan
        doesn't silently assume ₹0 tax when we genuinely don't know.
        """
        from services.tax_calculator import (
            EQUITY_LTCG_EXEMPTION, EQUITY_LTCG_RATE, EQUITY_STCG_RATE,
            NON_EQUITY_LTCG_RATE, DEFAULT_SLAB_RATE,
        )
        eq_lt = 0.0
        eq_st = 0.0
        ne_lt = 0.0  # non-equity LTCG gains
        ne_st = 0.0  # non-equity STCG gains (taxed at slab)
        pending = 0
        total_liability_from_actions = 0.0

        for action in actions:
            if action.get("type") != "EXIT":
                continue
            ti = action.get("tax_impact") or {}
            if not ti:
                continue
            if ti.get("tax_impact_pending"):
                pending += 1
                continue
            gain = ti.get("capital_gain", 0) or 0
            if gain <= 0:
                continue
            asset_class = ti.get("asset_class") or "equity"
            is_lt = bool(ti.get("is_long_term"))
            if asset_class == "equity":
                if is_lt:
                    eq_lt += gain
                else:
                    eq_st += gain
            else:
                if is_lt:
                    ne_lt += gain
                else:
                    ne_st += gain
            total_liability_from_actions += ti.get("tax_liability", 0) or 0

        # Re-apply equity ₹1.25L exemption on aggregate (plan-level)
        exemption_used = min(EQUITY_LTCG_EXEMPTION, eq_lt)
        taxable_eq_lt = max(0, eq_lt - EQUITY_LTCG_EXEMPTION)

        ltcg_tax = taxable_eq_lt * EQUITY_LTCG_RATE + ne_lt * NON_EQUITY_LTCG_RATE
        stcg_tax = eq_st * EQUITY_STCG_RATE + ne_st * DEFAULT_SLAB_RATE
        total_tax = round(ltcg_tax + stcg_tax, 2)

        return {
            # Plan-level aggregate tax (this is what UI/Copilot reads)
            "total_tax_liability": total_tax,
            "total_tax": total_tax,  # legacy alias
            # Gain breakdown
            "total_ltcg": round(eq_lt + ne_lt, 2),
            "total_stcg": round(eq_st + ne_st, 2),
            "equity_ltcg": round(eq_lt, 2),
            "equity_stcg": round(eq_st, 2),
            "non_equity_ltcg": round(ne_lt, 2),
            "non_equity_stcg": round(ne_st, 2),
            "exemption_used": round(exemption_used, 2),
            "taxable_ltcg": round(taxable_eq_lt + ne_lt, 2),
            "ltcg_tax": round(ltcg_tax, 2),
            "stcg_tax": round(stcg_tax, 2),
            "pending_actions": pending,
            "sum_per_action_liability": round(total_liability_from_actions, 2),
        }
    
    def _calculate_amc_exposure_from_mf_investments(
        self, 
        mf_investments: List[Dict[str, Any]], 
        total_portfolio_value: float
    ) -> Dict[str, float]:
        """Calculate AMC concentration from MF investments data.
        
        Uses scheme_name from portfolio intelligence MF data.
        Works for unresolved funds too (AMC extraction is purely name-based).
        Returns dict mapping AMC name to exposure percentage.
        Example: {"HDFC": 35.1, "ICICI": 14.6, ...}
        """
        if total_portfolio_value == 0:
            return {}
        
        amc_values = {}
        
        for mf in mf_investments:
            scheme_name = mf.get("scheme_name", "")
            amount = mf.get("amount_rs", 0)
            if not scheme_name or not amount:
                continue
            amc = self._extract_amc_from_name(scheme_name)
            if amc:
                amc_values[amc] = amc_values.get(amc, 0) + amount
        
        # Convert to percentages
        amc_exposure = {
            amc: round(value / total_portfolio_value * 100, 2)
            for amc, value in amc_values.items()
        }
        
        return amc_exposure
    
    def _infer_category_from_name(self, name: str) -> Optional[str]:
        """Best-effort category inference from scheme name when PG lookup fails.

        Matches common SEBI category keywords. Conservative — returns None
        for ambiguous names so Rule 2b stays silent rather than miscategorise.
        """
        if not name:
            return None
        n = name.upper()
        # Order matters — more specific first
        patterns = [
            ("LARGE & MID CAP", "Large & Mid Cap"),
            ("LARGE AND MID", "Large & Mid Cap"),
            ("MID CAP", "Mid Cap"),
            ("MIDCAP", "Mid Cap"),
            ("SMALL CAP", "Small Cap"),
            ("SMALLCAP", "Small Cap"),
            ("LARGE CAP", "Large Cap"),
            ("LARGECAP", "Large Cap"),
            ("BLUECHIP", "Large Cap"),
            ("FLEXI CAP", "Flexi Cap"),
            ("FLEXICAP", "Flexi Cap"),
            ("MULTI CAP", "Multi Cap"),
            ("MULTICAP", "Multi Cap"),
            ("FOCUSED", "Focused"),
            ("VALUE", "Value Oriented"),
            ("CONTRA", "Contra"),
            ("ELSS", "ELSS"),
            ("TAX SAV", "ELSS"),
            ("INDEX", "Index"),
            ("NIFTY", "Index"),
            ("SENSEX", "Index"),
            ("BALANCED ADVANTAGE", "Dynamic Asset Allocation"),
            ("BALANCED", "Hybrid"),
            ("HYBRID", "Hybrid"),
            ("AGGRESSIVE HYBRID", "Hybrid"),
            ("CONSERVATIVE HYBRID", "Hybrid"),
            ("ARBITRAGE", "Arbitrage"),
            ("LIQUID", "Liquid"),
            ("OVERNIGHT", "Liquid"),
            ("GILT", "Gilt"),
            ("CORPORATE BOND", "Corporate Bond"),
            ("CREDIT RISK", "Credit Risk"),
            ("SHORT DURATION", "Short Duration"),
            ("MEDIUM DURATION", "Medium Duration"),
            ("LONG DURATION", "Long Duration"),
            ("ULTRA SHORT", "Ultra Short Duration"),
            ("LOW DURATION", "Low Duration"),
            ("MONEY MARKET", "Money Market"),
            ("DEBT", "Debt"),
            ("BOND", "Debt"),
            ("GOLD", "Gold"),
            ("SILVER", "Commodity"),
            ("PHARMA", "Sectoral - Pharma"),
            ("BANKING", "Sectoral - Banking"),
            ("TECH", "Sectoral - IT"),
            ("INFRA", "Sectoral - Infra"),
            ("FMCG", "Sectoral - FMCG"),
            ("EMERGING", "Thematic"),
            ("INTERNATIONAL", "International"),
            ("GLOBAL", "International"),
        ]
        for pat, out in patterns:
            if pat in n:
                return out
        return None

    def _extract_amc_from_name(self, name: str) -> Optional[str]:
        """Extract AMC name from fund/scheme name.
        
        Examples:
          "HDFC Flexi Cap Fund" -> "HDFC"
          "Aditya Birla Sun Life Frontline Equity Fund" -> "ADITYA BIRLA"
          "Parag Parikh Flexi Cap Fund" -> "PARAG PARIKH"
        """
        if not name:
            return None
            
        words = name.upper().split()
        
        # Known single-word AMCs
        known_amcs = [
            "HDFC", "ICICI", "SBI", "AXIS", "KOTAK",
            "NIPPON", "FRANKLIN", "TEMPLETON", "MIRAE", 
            "DSP", "TATA", "UTI", "INVESCO", "HSBC", "IDFC",
            "SUNDARAM", "MOTILAL", "EDELWEISS", "BARODA",
            "CANARA", "BANDHAN", "UNION", "BOI", "QUANTUM"
        ]
        
        # Check for single-word AMCs
        for word in words:
            if word in known_amcs:
                return word
        
        # Check for multi-word AMCs
        if "ADITYA" in words and "BIRLA" in words:
            return "ADITYA BIRLA"
        if "PARAG" in words and "PARIKH" in words:
            return "PARAG PARIKH"
        if "L" in words and "T" in words:
            idx_l = words.index("L")
            idx_t = words.index("T")
            if abs(idx_l - idx_t) == 1:
                return "L&T"
        
        return None
    
    def _calculate_amc_exposure(self, holdings: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate AMC concentration as percentage of total portfolio value.
        
        Returns dict mapping AMC name to exposure percentage.
        Example: {"HDFC": 35.1, "ICICI": 14.6, ...}
        """
        total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
        if total_value == 0:
            return {}
        
        amc_values = {}
        
        for holding in holdings:
            # Extract AMC from asset name (e.g., "HDFC Flexi Cap Fund" -> "HDFC")
            asset_name = holding.get("name", "")
            value = holding["quantity"] * holding["current_price"]
            
            # Try to extract AMC from the fund name (first word usually)
            amc = None
            if asset_name:
                words = asset_name.upper().split()
                # Common AMC names
                known_amcs = [
                    "HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "ADITYA", "BIRLA",
                    "PARAG", "PARIKH", "NIPPON", "FRANKLIN", "TEMPLETON",
                    "MIRAE", "DSP", "TATA", "UTI", "INVESCO", "HSBC", "IDFC"
                ]
                for word in words:
                    if word in known_amcs:
                        amc = word
                        break
                    # Handle multi-word AMCs like "ADITYA BIRLA"
                    if word == "ADITYA" and "BIRLA" in words:
                        amc = "ADITYA BIRLA"
                        break
                    if word == "PARAG" and "PARIKH" in words:
                        amc = "PARAG PARIKH"
                        break
            
            if amc:
                amc_values[amc] = amc_values.get(amc, 0) + value
        
        # Convert to percentages
        amc_exposure = {
            amc: round(value / total_value * 100, 2)
            for amc, value in amc_values.items()
        }
        
        return amc_exposure
    
    def _suggest_debt_fund(self, amount: float, excluded_amcs: List[str] = None) -> Dict[str, Any]:
        """Suggest specific debt fund, avoiding overconcentrated AMCs."""
        if excluded_amcs is None:
            excluded_amcs = []
        
        debt_funds = [
            {"fund_name": "ICICI Prudential Corporate Bond Fund - Direct Growth", "amc": "ICICI", "fund_type": "Corporate Bond", "expense_ratio": 0.23, "aum": "₹18,500 Cr", "rating": "5-Star (CRISIL)", "returns_3y": "7.1%"},
            {"fund_name": "Axis Treasury Advantage Fund - Direct Growth", "amc": "AXIS", "fund_type": "Ultra Short Duration", "expense_ratio": 0.18, "aum": "₹12,000 Cr", "rating": "4-Star", "returns_3y": "6.8%"},
            {"fund_name": "SBI Magnum Gilt Fund - Direct Growth", "amc": "SBI", "fund_type": "Gilt Fund", "expense_ratio": 0.35, "aum": "₹9,500 Cr", "rating": "4-Star", "returns_3y": "6.9%"},
            {"fund_name": "Kotak Corporate Bond Fund - Direct Growth", "amc": "KOTAK", "fund_type": "Corporate Bond", "expense_ratio": 0.32, "aum": "₹8,200 Cr", "rating": "5-Star", "returns_3y": "7.0%"},
            {"fund_name": "HDFC Corporate Bond Fund - Direct Plan - Growth", "amc": "HDFC", "fund_type": "Corporate Bond", "expense_ratio": 0.25, "aum": "₹25,000 Cr", "rating": "5-Star (CRISIL)", "returns_3y": "7.2%"},
        ]
        
        available = [f for f in debt_funds if f["amc"] not in excluded_amcs]
        if not available:
            available = debt_funds
        
        if amount >= 500000:
            return available[0]
        elif amount >= 200000:
            return available[min(1, len(available) - 1)]
        else:
            return available[min(2, len(available) - 1)]
    
    def _suggest_gold_fund(self, amount: float) -> Dict[str, Any]:
        """Suggest gold ETF/fund for diversification."""
        gold_funds = [
            {
                "fund_name": "HDFC Gold ETF",
                "fund_type": "Gold ETF",
                "expense_ratio": 0.50,
                "aum": "₹2,500 Cr",
                "rating": "4-Star",
                "returns_3y": "13.5%",
            },
            {
                "fund_name": "SBI Gold Fund - Direct Growth",
                "fund_type": "Gold Fund",
                "expense_ratio": 0.65,
                "aum": "₹1,200 Cr",
                "rating": "4-Star",
                "returns_3y": "13.2%",
            },
        ]
        
        return gold_funds[0] if amount >= 100000 else gold_funds[1]
    
    def _create_add_action_specific(
        self,
        fund_suggestion: Dict[str, Any],
        priority: int,
        reason: str,
        amount: float = 0
    ) -> Dict[str, Any]:
        """Create ADD action with specific fund recommendation."""
        fund_name = fund_suggestion.get("fund_name")
        fund_type = fund_suggestion.get("fund_type")
        
        return {
            "action_id": f"act_{uuid4().hex[:8]}",
            "type": "ADD",
            "priority": priority,
            "asset_type": "mutual_fund",
            "asset_name": fund_name,
            "fund_details": fund_suggestion,
            "amount": round(amount, 2),
            "confidence": "HIGH",
            "reason_text": f"{reason}. Consider {fund_name} ({fund_type})",
            "reason_codes": ["ALLOCATION_GAP", "DIVERSIFICATION"],
            "status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


# Singleton instance
_plan_manager = None


def get_plan_manager() -> ActionPlanManager:
    """Get singleton action plan manager instance."""
    global _plan_manager
    if _plan_manager is None:
        _plan_manager = ActionPlanManager()
    return _plan_manager
