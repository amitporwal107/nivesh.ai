"""Scanner-to-Paper Trading (SPT): scanner signals → consolidated opportunities → proposals → sizing → allocation → risk →
paper orders → fills → positions → exits → outcomes.

Design: docs/scanner_paper_trading/DESIGN.md (decisions, ownership, contracts). Requirements: the PRD and the Workflow in
docs/prd/. What already exists and is reused (risk service, paper ledger, kill switch, limits): EXISTING_CODE_MAP.md.
Nothing here talks to a broker: every order is a simulated paper order.
"""
