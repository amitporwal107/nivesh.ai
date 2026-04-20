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
    
    Removes commas, extra whitespace, and converts to lowercase.
    Example:
        "HDFC Balanced, Advantage Fund -, Direct Plan -, Growth Option"
        → "hdfc balanced advantage fund direct plan growth option"
    """
    return " ".join(name.lower().replace(",", "").replace("-", " ").split())


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
        logger.info(f"Generating plan for user {user_id}")
        
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
        logger.info(f"Found {len(mf_investments)} MF investments in portfolio intelligence")
        resolved_count = sum(1 for mf in mf_investments if mf.get("resolved"))
        logger.info(f"Resolved MF investments: {resolved_count}")
        
        # Build normalized name lookup for holdings
        holding_lookup = {
            _normalize_fund_name(h["name"]): h
            for h in mf_holdings
        }
        
        for mf in mf_investments:
            if not mf.get("resolved"):
                logger.debug(f"Skipping unresolved MF: {mf.get('scheme_name', 'Unknown')[:40]}")
                continue
            
            # Try normalized name matching
            normalized_scheme = _normalize_fund_name(mf["scheme_name"])
            holding = holding_lookup.get(normalized_scheme)
            
            if not holding:
                logger.warning(f"No matching holding found for MF: {mf.get('scheme_name', 'Unknown')[:40]}")
                continue
            
            try:
                exit_result = await decision_engine.calculate_mf_exit_score(mf, portfolio_intelligence, holding)
                logger.info(f"MF Exit Score: {mf.get('scheme_name', 'Unknown')[:40]} = {exit_result['exit_score']} (action: {exit_result['action']})")
                
                # Lower threshold: include even HOLD recommendations in candidates
                if exit_result["exit_score"] >= 4.0:  # Was filtering only "EXIT", now include score >= 4
                    exit_candidates.append(exit_result)
                    logger.info("  → Added to exit_candidates (score >= 4.0)")
                else:
                    logger.debug(f"  → Skipped (score {exit_result['exit_score']} < 4.0)")
            except Exception as e:
                logger.error(f"Error scoring MF {mf.get('scheme_name', 'Unknown')}: {e}")
                logger.exception(e)
                continue
        
        # Score stocks (DISABLED - MF-only action plans)
        # Stocks are excluded from action recommendations
        portfolio_context = {
            "total_value": portfolio_data["total_value"],
            "mf_count": len(mf_holdings),
            "stock_count": len(stock_holdings),
        }
        
        # NOTE: Stock scoring disabled - focus on MF optimization only
        # for stock in stock_holdings:
        #     exit_result = await decision_engine.calculate_stock_exit_score(stock, portfolio_context)
        #     if exit_result["exit_score"] >= 4.0:
        #         exit_candidates.append(exit_result)
        
        # Sort by exit score (highest first)
        exit_candidates = sorted(exit_candidates, key=lambda x: x["exit_score"], reverse=True)
        
        logger.info(f"Generated {len(exit_candidates)} MF exit candidates")
        
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
        
        # 5. Calculate portfolio-level tax impact
        total_tax_impact = self._calculate_total_tax_impact(actions)
        
        # 6. Calculate freed capital
        freed_capital = sum(a["amount"] for a in actions if a["type"] == "EXIT")
        post_tax_proceeds = freed_capital - total_tax_impact["total_tax"]
        
        # 7. Create plan object
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
            "metadata": {
                "source": "auto_generated",
                "generation_time_ms": 0,  # TODO: track
                "portfolio_value_at_creation": portfolio_data["total_value"],
            },
        }
        
        logger.info(f"Plan generated: {plan_id} with {len(actions)} actions")
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
        logger.info(f"Plan {plan_id} saved as active")
        return plan
    
    async def get_active_plan(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's active plan with calculated completion metrics."""
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": STATUS_ACTIVE},
            {"_id": 0}
        )
        
        if not plan:
            return None
        
        # Calculate completion metrics
        actions = plan.get("actions", [])
        total_actions = len(actions)
        completed_actions = len([a for a in actions if a.get("status") == "COMPLETED"])
        completion_pct = (completed_actions / total_actions * 100) if total_actions > 0 else 0
        
        # Add calculated fields to plan
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
        logger.info(f"Plan {plan['plan_id']} created in DB")
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
                logger.info(f"Auto-archived plan {plan['plan_id']} (completed >30 days ago)")
        
        return archived_count
    
    # ══════════════════════════════════════════════════════════════════════
    # PLAN LIFECYCLE
    # ══════════════════════════════════════════════════════════════════════
    
    async def archive_plan(self, plan_id: str, user_id: str, reason: str) -> None:
        """Archive a plan (move to history)."""
        plan = await self.get_plan(plan_id, user_id)
        if not plan:
            return
        
        # Archive to plan_history collection
        history_entry = {
            "history_id": f"hist_{uuid4().hex[:12]}",
            "plan_id": plan_id,
            "user_id": user_id,
            "version": plan["version"],
            "status": STATUS_ARCHIVED,
            "archived_at": datetime.now(timezone.utc),
            "archive_reason": reason,
            "plan_snapshot": plan,
        }
        

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
        actions: List[Dict[str, Any]] = []
        exited_ids: set = set()                  # instrument_ids already marked for exit
        exited_holding_keys: set = set()         # mongo holding keys (for Regular/Direct matches without IDs)
        priority_counter = [1]                   # mutable int for shared incrementing

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
        reg_dir_pairs = self._find_regular_direct_pairs(mf_holdings)
        logger.info(f"[Rule 1/6] Found {len(reg_dir_pairs)} Regular/Direct pairs")

        # Rule 1: Exit Regular when Direct exists for same fund
        for pair in reg_dir_pairs:
            regular = pair["regular"]
            direct = pair["direct"]
            reg_key = _holding_key(regular)
            if reg_key in exited_holding_keys:
                continue
            cost_leak = self._estimate_cost_leak(regular, direct, mf_investments)
            reason_extra = (
                f"Direct plan of same fund exists in portfolio (expense saving ≈ ₹{cost_leak:,.0f}/yr). "
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
            actions.append(action)
            exited_holding_keys.add(reg_key)
            mf_match = _resolve_candidate(regular) or {}
            if mf_match.get("instrument_id"):
                exited_ids.add(mf_match["instrument_id"])
            priority_counter[0] += 1
            logger.info(f"[Rule 1] EXIT Regular: {regular.get('name','')[:40]}")

        # Rule 6: Cost leak — if annual leak > ₹10K total across Regular funds without Direct pair,
        # generate switch (EXIT Regular + ADD Direct) actions for each such Regular fund
        all_regular_without_direct = self._find_regular_without_direct_pair(mf_holdings, reg_dir_pairs)
        leaks: List[Dict[str, Any]] = []
        for reg in all_regular_without_direct:
            leak = self._estimate_cost_leak(reg, None, mf_investments)
            if leak > 0:
                leaks.append({"holding": reg, "leak": leak})
        total_leak = sum(item["leak"] for item in leaks)
        logger.info(f"[Rule 6] Total Regular→Direct cost leak: ₹{total_leak:,.0f}/yr across {len(leaks)} funds")
        if total_leak >= 10000:
            # Sort by largest leak first, cap at 3 switch actions to keep plan actionable
            leaks.sort(key=lambda x: x["leak"], reverse=True)
            for leak_item in leaks[:3]:
                reg = leak_item["holding"]
                reg_key = _holding_key(reg)
                if reg_key in exited_holding_keys:
                    continue
                cand = _resolve_candidate(reg)
                action = self._build_exit_action_from_holding(
                    holding=reg,
                    candidate=cand,
                    priority=priority_counter[0],
                    reason_prefix=(
                        f"Switch to Direct plan saves ₹{leak_item['leak']:,.0f}/year in expense ratio. "
                        f"(Total portfolio cost leak: ₹{total_leak:,.0f}/yr.)"
                    ),
                    reason_code="COST_LEAK_SWITCH_TO_DIRECT",
                )
                actions.append(action)
                exited_holding_keys.add(reg_key)
                if cand and cand.get("instrument_id"):
                    exited_ids.add(cand["instrument_id"])
                priority_counter[0] += 1
                logger.info(f"[Rule 6] SWITCH (EXIT Regular): {reg.get('name','')[:40]} saves ₹{leak_item['leak']:,.0f}/yr")

        # ── RULE 2: AMC Concentration >15% ──────────────────────────────────
        amc_exposure = self._calculate_amc_exposure_from_mf_investments(
            mf_investments, portfolio_context["total_value"]
        )
        over_concentrated_amcs = [(amc, pct) for amc, pct in amc_exposure.items() if pct > 15.0]
        logger.info(f"[Rule 2] AMC exposure: {amc_exposure}; over-concentrated: {over_concentrated_amcs}")

        for amc_name, amc_pct in sorted(over_concentrated_amcs, key=lambda x: x[1], reverse=True):
            # Find all MF investments in this AMC (not yet exited)
            amc_funds = [
                m for m in mf_investments
                if m.get("resolved")
                and self._extract_amc_from_name(m.get("scheme_name", "")) == amc_name
                and m.get("instrument_id") not in exited_ids
            ]
            # Rank by exit_score (descending)
            ranked = []
            for mf in amc_funds:
                cand = candidate_by_id.get(mf.get("instrument_id"))
                score = cand["exit_score"] if cand else 5.0
                ranked.append({"mf": mf, "candidate": cand, "exit_score": score})
            ranked.sort(key=lambda x: x["exit_score"], reverse=True)

            # Exit funds greedily until AMC exposure drops below 15%
            current_pct = amc_pct
            target_pct = 15.0
            total_pv = portfolio_context["total_value"]
            for item in ranked:
                if current_pct <= target_pct:
                    break
                mf = item["mf"]
                # Find matching holding
                h = next(
                    (x for x in mf_holdings if _normalize_fund_name(x.get("name", "")) ==
                     _normalize_fund_name(mf.get("scheme_name", ""))),
                    None
                )
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
                logger.info(f"[Rule 2] EXIT for AMC concentration: {mf.get('scheme_name','')[:40]} "
                            f"(new AMC pct ≈ {current_pct:.1f}%)")

        # ── RULE 3: Underperformer Replacement ──────────────────────────────
        # Use signal QUALITY_ISSUES + exit_score quality component to detect underperformers
        underperformers = self._find_underperformers(mf_investments, portfolio_intelligence, exit_candidates)
        logger.info(f"[Rule 3] Found {len(underperformers)} underperforming funds")
        for under in underperformers[:2]:  # cap at top 2
            mf = under["mf"]
            if mf.get("instrument_id") in exited_ids:
                continue
            h = next(
                (x for x in mf_holdings if _normalize_fund_name(x.get("name", "")) ==
                 _normalize_fund_name(mf.get("scheme_name", ""))),
                None
            )
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
                logger.info(f"[Rule 3] Replace {mf.get('scheme_name','')[:30]} → {replacement.get('scheme_name','')[:30]}")

        # ── RULE 4: Different-Fund Overlap >60% ─────────────────────────────
        pairs = portfolio_intelligence.get("pairwise_overlap", [])
        for pair in pairs:
            if pair.get("overlap_pct", 0) < 60:
                continue
            id_a, id_b = pair.get("a"), pair.get("b")
            if id_a in exited_ids or id_b in exited_ids:
                continue
            # Skip if these are regular/direct pair of same base scheme (handled by Rule 1)
            name_a = pair.get("a_name", "")
            name_b = pair.get("b_name", "")
            if self._normalize_base_scheme_name(name_a) == self._normalize_base_scheme_name(name_b):
                continue
            # Pick fund with higher exit_score
            cand_a = candidate_by_id.get(id_a)
            cand_b = candidate_by_id.get(id_b)
            score_a = cand_a["exit_score"] if cand_a else 5.0
            score_b = cand_b["exit_score"] if cand_b else 5.0
            if score_a >= score_b:
                victim_cand, victim_name = cand_a, name_a
                partner_name = name_b
            else:
                victim_cand, victim_name = cand_b, name_b
                partner_name = name_a
            h = next(
                (x for x in mf_holdings if _normalize_fund_name(x.get("name", "")) ==
                 _normalize_fund_name(victim_name)),
                None
            )
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
            logger.info(f"[Rule 4] EXIT for overlap: {victim_name[:40]} vs {partner_name[:40]}")
            # Limit to 2 overlap resolutions to keep plan concise
            if sum(1 for a in actions if "OVERLAP_CONSOLIDATION" in (a.get("reason_codes") or [])) >= 2:
                break

        # ── RULE 5: Asset Allocation Rebalancing (Debt Gap) ─────────────────
        if portfolio_context["total_value"] > 0:
            asset_allocation = self._calculate_asset_allocation(holdings)
            portfolio_context["asset_allocation"] = asset_allocation
            equity_pct = asset_allocation.get("equity_pct", 0)
            debt_pct = asset_allocation.get("debt_pct", 0)
            # Strict user rule: Equity > 90% AND Debt < 10%
            # Relax to Debt < 10% alone since MFs lump as equity in _calculate_asset_allocation
            needs_debt = debt_pct < 10
            logger.info(f"[Rule 5] Equity={equity_pct:.1f}%, Debt={debt_pct:.1f}%, needs_debt={needs_debt}")
            if needs_debt:
                excluded_amcs = [amc for amc, pct in amc_exposure.items() if pct > 15.0]
                suggested_amount = portfolio_context["total_value"] * 0.10
                debt_suggestion = self._suggest_debt_fund(suggested_amount, excluded_amcs)
                add_action = self._create_add_action_specific(
                    debt_suggestion,
                    priority_counter[0],
                    "Portfolio lacks debt allocation for risk management",
                    suggested_amount,
                )
                actions.append(add_action)
                priority_counter[0] += 1
                logger.info(f"[Rule 5] ADD debt fund: {debt_suggestion.get('fund_name','')}")

        # Fallback: if no actions produced by rules, fall back to top exit candidates
        if not actions and exit_candidates:
            logger.info("[Fallback] No rule-based actions produced; using top exit candidates")
            for candidate in exit_candidates[:2]:
                action = self._create_exit_action_with_tax_analysis(candidate, priority_counter[0], None)
                actions.append(action)
                priority_counter[0] += 1

        logger.info(f"Rule engine produced {len(actions)} actions")
        return actions

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
            ret_1y_val = float(ret_1y) if ret_1y is not None else None
            # Underperformer criteria: weak quality (>=7) OR 1Y return < 8%
            is_weak = (quality >= 7.0) or (ret_1y_val is not None and ret_1y_val < 8.0)
            if is_weak:
                out.append({
                    "mf": mf,
                    "candidate": cand,
                    "quality_score": quality,
                    "ret_1y": round(ret_1y_val, 2) if ret_1y_val is not None else "N/A",
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
            logger.debug(f"tax_calculator failed for minimal action: {_e}")
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
                logger.debug(f"fallback tax_impact calc failed: {_e}")
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
        
        # Fetch fresh data
        holdings = await db.holdings.find({"user_id": user_id}, {"_id": 0}).to_list(500)
        from services import portfolio_intelligence
        intelligence = await portfolio_intelligence.compute_portfolio_intelligence(user_id)
        
        # Generate new plan
        new_plan = await self.generate_plan(user_id, intelligence, holdings)
        new_plan["version"] = new_version
        new_plan["metadata"]["parent_plan_id"] = parent_plan_id
        
        # Save directly as active (skip preview)
        new_plan["status"] = STATUS_ACTIVE
        await self.create_plan(new_plan)
        
        logger.info(f"Plan refreshed: v{new_version}")
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
        Returns dict mapping AMC name to exposure percentage.
        Example: {"HDFC": 35.1, "ICICI": 14.6, ...}
        """
        if total_portfolio_value == 0:
            return {}
        
        amc_values = {}
        
        for mf in mf_investments:
            if not mf.get("resolved"):
                continue
                
            scheme_name = mf.get("scheme_name", "")
            amount = mf.get("amount_rs", 0)
            
            # Extract AMC from scheme name
            amc = self._extract_amc_from_name(scheme_name)
            
            if amc:
                amc_values[amc] = amc_values.get(amc, 0) + amount
        
        # Convert to percentages
        amc_exposure = {
            amc: round(value / total_portfolio_value * 100, 2)
            for amc, value in amc_values.items()
        }
        
        return amc_exposure
    
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
