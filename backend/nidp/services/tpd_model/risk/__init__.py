"""Risk Management & Capital Allocation Engine — core (PRD docs/ai_research/tpd3/prd/Nivesh_Risk_Allocation_Engine_PRD_v1.0.md).

Pure Python, no database or network: versioned risk configuration (config), Zerodha cost model (costs), position sizing
(sizing), portfolio state (portfolio), drawdown / kill-switch state machine (drawdown), daily-bar execution simulator
(execution), append-only decision ledger (ledger) and the daily simulation loop (engine). Paper only, cash equity,
long only.
"""
