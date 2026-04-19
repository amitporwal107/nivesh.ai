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
        
        # 3. Build action plan based on signals and candidates
        actions = []
        action_priority = 1
        
        # Strategy: If overlap signal exists, prioritize exiting overlapping funds
        overlap_signal = next((s for s in signals if s["type"] == "OVERLAP_REDUNDANCY"), None)
        
        if overlap_signal and overlap_signal.get("details", {}).get("top_overlap_pairs"):
            # Exit from overlapping pairs - pick the one with higher exit score
            logger.info("Building actions based on overlap signal")
            pairs = overlap_signal["details"]["top_overlap_pairs"]
            
            for pair in pairs[:2]:  # Top 2 overlapping pairs
                fund_a_name = pair.get("fund_a")
                fund_b_name = pair.get("fund_b")
                
                # Find candidates for these funds
                candidate_a = next((c for c in exit_candidates if c.get("scheme_name") == fund_a_name), None)
                candidate_b = next((c for c in exit_candidates if c.get("scheme_name") == fund_b_name), None)
                
                # Exit the one with higher exit score
                if candidate_a and candidate_b:
                    exit_fund = candidate_a if candidate_a["exit_score"] >= candidate_b["exit_score"] else candidate_b
                    action = self._create_exit_action_with_tax_analysis(exit_fund, action_priority, overlap_signal)
                    actions.append(action)
                    action_priority += 1
                    logger.info(f"Added EXIT action for {exit_fund.get('scheme_name', 'Unknown')[:40]} (overlap pair)")
        
        # If no overlap-based actions, take top 2 exit candidates
        if len(actions) == 0 and len(exit_candidates) > 0:
            logger.info("No overlap pairs found, using top exit candidates")
            for candidate in exit_candidates[:2]:
                action = self._create_exit_action_with_tax_analysis(candidate, action_priority, None)
                actions.append(action)
                action_priority += 1
        
        # 4. Check for ADD opportunity (asset allocation gap)
        if portfolio_context["total_value"] > 0:
            asset_allocation = self._calculate_asset_allocation(holdings)
            portfolio_context["asset_allocation"] = asset_allocation
            
            # Calculate AMC concentration to avoid recommending overconcentrated AMCs
            # Use MF investments from portfolio intelligence (has proper scheme names)
            amc_exposure = self._calculate_amc_exposure_from_mf_investments(
                portfolio_intelligence.get("mf_investments", []),
                portfolio_context["total_value"]
            )
            excluded_amcs = [amc for amc, pct in amc_exposure.items() if pct > 15.0]
            logger.info(f"AMC exposure analysis: {amc_exposure}")
            if excluded_amcs:
                logger.info(f"Excluding overconcentrated AMCs from debt fund suggestions: {excluded_amcs}")
            
            # If debt < 20%, suggest specific debt fund
            if asset_allocation.get("debt_pct", 0) < 20:
                suggested_amount = portfolio_context["total_value"] * 0.10  # 10% of portfolio
                debt_suggestion = self._suggest_debt_fund(suggested_amount, excluded_amcs)
                add_action = self._create_add_action_specific(
                    debt_suggestion,
                    action_priority,
                    "Portfolio lacks debt allocation",
                    suggested_amount
                )
                actions.append(add_action)
                logger.info(f"Added ADD action: {debt_suggestion['fund_name']} (₹{suggested_amount:,.0f})")
        
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
        
        Changes status from "preview" to "active"
        """
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
        tax_impact = candidate.get("tax_impact", {})
        
        # Calculate amount from MF investment
        exit_amount = mf_investment.get("amount_rs", 0)
        if exit_amount == 0:
            # Fallback: calculate from holding
            exit_amount = holding.get("quantity", 0) * holding.get("current_price", 0)
        
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
        """Calculate total tax impact across all EXIT actions."""
        total_ltcg = 0
        total_stcg = 0
        
        for action in actions:
            if action["type"] == "EXIT" and action["tax_impact"]:
                total_ltcg += action["tax_impact"].get("capital_gain", 0) if action["tax_impact"].get("is_long_term") else 0
                total_stcg += action["tax_impact"].get("capital_gain", 0) if not action["tax_impact"].get("is_long_term") else 0
        
        # Apply ₹1L LTCG exemption
        exemption_used = min(100000, total_ltcg)
        taxable_ltcg = max(0, total_ltcg - 100000)
        
        ltcg_tax = taxable_ltcg * 0.10
        stcg_tax = total_stcg * 0.15
        total_tax = ltcg_tax + stcg_tax
        
        return {
            "total_ltcg": round(total_ltcg, 2),
            "total_stcg": round(total_stcg, 2),
            "exemption_used": round(exemption_used, 2),
            "taxable_ltcg": round(taxable_ltcg, 2),
            "ltcg_tax": round(ltcg_tax, 2),
            "stcg_tax": round(stcg_tax, 2),
            "total_tax": round(total_tax, 2),
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
