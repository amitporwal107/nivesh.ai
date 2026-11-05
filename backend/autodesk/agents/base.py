"""Agent runtime contract (architecture §3.3, §11).

An agent is a function of (task, resolved inputs, policy, point-in-time market view) → AgentResult. Agents never
write to the database and never call a broker: the orchestrator persists their validated results. This keeps every
agent replayable — the same inputs and versions give the same output (PRD §29.7 decision consistency).

Inputs: the orchestrator resolves the task's input_refs ("signal://…", "plan://TRD-…@2", "assessment://…",
"book://ACC-…") into `ctx.inputs` before the agent runs, so an agent reads only what its task references (shared
context is not shared memory, PRD §29.4).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..contracts import AgentDescriptor, AgentResult, TaskSpec, TASK_OWNER
from ..market.view import MarketView, RestrictedView


@dataclass
class AgentContext:
    tenant_id: str
    account: dict[str, Any]                 # autodesk.accounts row
    policy: dict[str, Any]                  # {"policy_id", "version", "body": PolicyBody-json}
    market: MarketView                      # already restricted to the agent's tools by the runtime
    as_of: datetime                         # sim clock in a simulation, wall clock otherwise (UTC)
    simulation_id: Optional[str] = None
    workflow_id: Optional[str] = None
    inputs: dict[str, Any] = field(default_factory=dict)
    settings: Any = None


class Agent(ABC):
    descriptor: AgentDescriptor

    def market_tools(self) -> set[str]:
        """Market view methods this agent may call (its tool allowlist)."""
        return {t.split(".", 1)[1] for t in self.descriptor.tools if t.startswith("market.")}

    def restrict(self, view: MarketView) -> RestrictedView:
        return RestrictedView(view, self.market_tools() | {"latest_session"}, self.descriptor.agent_key.value)

    def accept(self, task: TaskSpec, ctx: AgentContext) -> Optional[str]:
        """Return None to accept, or the reason to reject. Default: ownership + tenant/account scope."""
        if TASK_OWNER[task.task_type] != self.descriptor.agent_key:
            return f"{self.descriptor.agent_key.value} does not own {task.task_type.value}"
        if task.tenant_id != ctx.tenant_id:
            return "task tenant does not match the context tenant"
        if task.account_id and task.account_id != ctx.account.get("account_id"):
            return "task account does not match the context account"
        if task.task_type not in self.descriptor.task_types:
            return f"{task.task_type.value} is not in this agent's task types"
        return None

    @abstractmethod
    async def run(self, task: TaskSpec, ctx: AgentContext) -> AgentResult:
        ...
