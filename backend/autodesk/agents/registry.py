"""The production agent set (one instance each, stateless between tasks)."""
from __future__ import annotations

from ..contracts import AgentKey


def default_agents() -> dict:
    from .ai_trader import AITrader
    from .middle_office import MiddleOffice
    from .risk_ops import RiskOps
    from .tech_support import TechSupport
    from .trading_assistant import TradingAssistant
    return {AgentKey.TECH_SUPPORT: TechSupport(), AgentKey.AI_TRADER: AITrader(),
            AgentKey.TRADING_ASSISTANT: TradingAssistant(), AgentKey.RISK_OPS: RiskOps(),
            AgentKey.MIDDLE_OFFICE: MiddleOffice()}
