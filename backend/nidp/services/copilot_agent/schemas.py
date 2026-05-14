"""Shared Pydantic schemas for the Nivesh Copilot LangGraph agent framework.

These types flow through the entire agent pipeline:
  ChatMessage  — one message in a conversation thread (user / assistant / tool)
  ToolResult   — structured output from any copilot tool (data + display hint)
  AgentResponse — final structured response emitted by any specialist node
  CopilotState  — LangGraph state that travels across all nodes in the graph
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence
from datetime import datetime

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class AgentName(str, Enum):
    INTENT = "intent"
    MARKET = "market_analyst"
    STOCK = "stock_analyst"
    MF = "mf_analyst"
    PORTFOLIO = "portfolio_analyst"
    RISK = "risk_analyst"
    GOAL = "goal_planner"
    RECOMMENDATION = "recommendation"
    COMPLIANCE = "compliance"


class WidgetType(str, Enum):
    PORTFOLIO_OVERVIEW = "portfolio_overview"
    STRESS_TEST = "stress_test"
    TAX_HARVEST = "tax_harvest"
    REBALANCE_PLAN = "rebalance_plan"
    OVERLAP_REVEAL = "overlap_reveal"
    SECTOR_ROTATION = "sector_rotation"
    STOCK_SCREENER = "stock_screener"
    FUND_COMPARISON = "fund_comparison"
    GOAL_TRACKER = "goal_tracker"
    SIP_PLAN = "sip_plan"
    NONE = "none"


# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    """A single message in the copilot conversation thread."""

    role: MessageRole
    content: str
    name: Optional[str] = None          # tool name when role=tool
    tool_call_id: Optional[str] = None  # matches the LLM tool-call id
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------

class ToolResult(BaseModel):
    """Structured output returned by every copilot tool function.

    The `rows` list is widget-ready; `summary` goes into the LLM context.
    `widget_type` tells the frontend which widget component to render.
    """

    ok: bool
    tool_name: str
    summary: str                                    # ≤ 300-char LLM context line
    data: Dict[str, Any] = Field(default_factory=dict)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    widget_type: WidgetType = WidgetType.NONE
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"TOOL={self.tool_name} status=error reason={self.error}"
        return f"TOOL={self.tool_name} | {self.summary}"

    model_config = ConfigDict(use_enum_values=True)


# ---------------------------------------------------------------------------
# AgentResponse
# ---------------------------------------------------------------------------

class AgentResponse(BaseModel):
    """Final structured response produced by a specialist agent node.

    This is what the compliance node receives and what eventually streams
    back to the frontend.  `text` is the markdown narrative; `widget_type`
    + `widget_data` drive the frontend widget renderer.
    """

    agent: AgentName
    text: str                                       # markdown answer to user
    widget_type: WidgetType = WidgetType.NONE
    widget_data: Dict[str, Any] = Field(default_factory=dict)

    # provenance / grounding
    tool_results: List[ToolResult] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    # compliance additions (filled by compliance node)
    disclaimer: Optional[str] = None
    grounding_ok: bool = True                       # False → numeric mismatch detected

    model_config = ConfigDict(use_enum_values=True)


# ---------------------------------------------------------------------------
# IntentClassification
# ---------------------------------------------------------------------------

class IntentClassification(BaseModel):
    """Output of the intent classifier node — determines which agent handles this turn."""

    agent: AgentName
    confidence: float = Field(ge=0.0, le=1.0)
    # structured slots extracted from the user message
    symbol: Optional[str] = None            # stock/ETF ticker (NSE format)
    scheme_code: Optional[str] = None       # AMFI scheme code
    scenario: Optional[str] = None          # stress-test scenario key
    goal_name: Optional[str] = None
    category: Optional[str] = None         # MF category
    extras: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(use_enum_values=True)


# ---------------------------------------------------------------------------
# CopilotState  (LangGraph state that flows through the graph)
# ---------------------------------------------------------------------------

class CopilotState(BaseModel):
    """State object that persists and evolves across all nodes in the graph.

    `messages` uses the LangGraph `add_messages` reducer — each node appends
    rather than overwrites, giving the full conversation history.
    """

    # conversation thread (accumulates across turns via add_messages reducer)
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)

    # identifiers
    user_id: str = ""
    session_id: str = ""

    # intent routing (filled by intent node)
    intent: Optional[IntentClassification] = None

    # tool outputs (filled by specialist nodes)
    tool_results: List[ToolResult] = Field(default_factory=list)

    # final answer (filled by specialist node, may be revised by compliance)
    response: Optional[AgentResponse] = None

    # flags
    needs_compliance_check: bool = True
    is_advisor_mode: bool = False

    # token budget guard (rough estimate, updated by each node)
    tokens_used: int = 0

    model_config = ConfigDict(arbitrary_types_allowed=True)  # for BaseMessage
