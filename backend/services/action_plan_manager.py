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
        for mf in mf_investments:
            if not mf.get("resolved"):
                continue
            
            holding = next((h for h in mf_holdings if h["name"] == mf["scheme_name"]), None)
            if not holding:
                continue
            
            try:
                exit_result = await decision_engine.calculate_mf_exit_score(mf, portfolio_intelligence, holding)
                logger.info(f"MF Exit Score: {mf.get('scheme_name', 'Unknown')[:40]} = {exit_result['exit_score']} (action: {exit_result['action']})")
                
                # Lower threshold: include even HOLD recommendations in candidates
                if exit_result["exit_score"] >= 4.0:  # Was filtering only "EXIT", now include score >= 4
                    exit_candidates.append(exit_result)
            except Exception as e:
                logger.error(f"Error scoring MF {mf.get('scheme_name', 'Unknown')}: {e}")
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
        exit_candidates.sort(key=lambda x: x["exit_score"], reverse=True)
        
        # 3. Select top actions (max 3 for MVP, configurable)
        actions = []
        action_priority = 1
        
        # Add top 2 EXIT actions
        for candidate in exit_candidates[:2]:
            action = self._create_exit_action(candidate, action_priority)
            actions.append(action)
            action_priority += 1
        
        # 4. Check for ADD opportunity (asset allocation gap)
        if portfolio_context["total_value"] > 0:
            asset_allocation = self._calculate_asset_allocation(holdings)
            portfolio_context["asset_allocation"] = asset_allocation
            
            # If debt < 20%, suggest debt fund
            if asset_allocation.get("debt_pct", 0) < 20:
                add_action = self._create_add_action_generic(
                    asset_class="debt",
                    target_amount=portfolio_context["total_value"] * 0.10,  # 10% reallocation
                    reason="Portfolio lacks debt allocation",
                    priority=action_priority,
                )
                actions.append(add_action)
        
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
        """Get user's active plan."""
        plan = await db.action_plans.find_one(
            {"user_id": user_id, "status": STATUS_ACTIVE},
            {"_id": 0}
        )
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
        """Update action status (PENDING → COMPLETED/SKIPPED).
        
        Also updates plan progress.
        """
        if new_status not in [ACTION_COMPLETED, ACTION_SKIPPED]:
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
        timestamp_field = "completed_at" if new_status == ACTION_COMPLETED else "skipped_at"
        
        update_fields = {
            f"actions.{action_idx}.status": new_status,
            f"actions.{action_idx}.{timestamp_field}": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        if completion_note:
            update_fields[f"actions.{action_idx}.completion_note"] = completion_note
        
        # Calculate new progress
        actions = plan["actions"]
        actions[action_idx]["status"] = new_status
        
        completed_count = sum(1 for a in actions if a["status"] == ACTION_COMPLETED)
        skipped_count = sum(1 for a in actions if a["status"] == ACTION_SKIPPED)
        pending_count = sum(1 for a in actions if a["status"] == ACTION_PENDING)
        completion_pct = (completed_count / len(actions) * 100) if actions else 0
        
        update_fields["completed_actions"] = completed_count
        update_fields["skipped_actions"] = skipped_count
        update_fields["pending_actions"] = pending_count
        update_fields["completion_pct"] = round(completion_pct, 2)
        
        # Check if plan is completed
        if pending_count == 0:
            update_fields["status"] = STATUS_COMPLETED
            update_fields["completed_at"] = datetime.now(timezone.utc)
        
        # Update in DB
        await db.action_plans.update_one(
            {"plan_id": plan_id, "user_id": user_id},
            {"$set": update_fields}
        )
        
        # Return updated plan
        updated_plan = await self.get_plan(plan_id, user_id)
        logger.info(f"Action {action_id} status updated to {new_status}")
        return updated_plan
    
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
        
        await db.plan_history.insert_one(history_entry)
        
        # Update plan status
        await db.action_plans.update_one(
            {"plan_id": plan_id, "user_id": user_id},
            {"$set": {"status": STATUS_ARCHIVED, "updated_at": datetime.now(timezone.utc)}}
        )
        
        logger.info(f"Plan {plan_id} archived (reason: {reason})")
    
    async def refresh_plan(
        self,
        user_id: str,
        portfolio_intelligence: Dict[str, Any],
        holdings: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Refresh existing plan (create new version, archive old).
        
        Flow:
        1. Get current active plan
        2. Archive it
        3. Generate new plan with incremented version
        4. Link to parent plan
        """
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
        
        # Generate new plan
        new_plan = await self.generate_plan(user_id, portfolio_intelligence, holdings)
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


# Singleton instance
_plan_manager = None

def get_plan_manager() -> ActionPlanManager:
    """Get singleton action plan manager instance."""
    global _plan_manager
    if _plan_manager is None:
        _plan_manager = ActionPlanManager()
    return _plan_manager
