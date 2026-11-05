repo: amitporwal107/nivesh.ai
branch: dev
path: frontend-v5

## Last sync
date: 2026-11-05T03:12:54Z

### Updated in this project
- Trading Desk prototype built in the V5 design system (dark + light, desktop + mobile)
- Real-time P&L screen follows the paper P&L v2 design from the repo
- Sample world: Thu 5 Nov 2026 NSE session, Nifty lot 65, Bank Nifty lot 30

## Screen map
| Screen | Built from |
|---|---|
| Trading Desk.dc.html (shell) | frontend-v5/design/nivesh-copilot/Nivesh Copilot.dc.html (shell vocabulary), colors_and_type.css |
| TDPnl.dc.html | frontend-v5/src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/PnlDashboard.tsx, pnl-top.tsx, pnl-ui.tsx; docs/paper_pnl_dashboard/DESIGN.md |
| TDTrades.dc.html | trade-desk/HeaderStrip.tsx, TradeDeskTab.tsx (paper desk vocabulary) |
| TDOverview, TDAgents, TDScanner, TDWorkbench, TDApprovals, TDRisk, TDMiddleOffice | frontend-v5/design/nivesh-copilot/NVTrader.dc.html, NVOps.dc.html (layout and wording patterns) |
