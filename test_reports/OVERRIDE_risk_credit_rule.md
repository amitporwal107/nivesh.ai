# OVERRIDE: risk_credit_rule (branch feat/risk-credit-structure-rule, PR to dev)

REASON: Not deployed. A staging check needs the PR merged and the staging backend restarted: a real POST /api/desk/paper-trades with a credit spread, GET /api/desk/trade-plans/{id} account_size, and a risk_decisions row recorded under universal-risk-v2. I cannot merge my own PR.
Evidence (this session, real output, test_reports/risk_credit_rule_2026-10-28.md), all from Docker `--network none`:
- new tests/test_risk_credit_rule.py: 21 passed;
- test_risk* + plan_sizing, strategy_payoff, payoff_cost_card, decision_card_contract and ai_trader_config_risk: 685 passed, 6 skipped (dev 664 / 6);
- full CI allowlist: 6676 passed, 4 failed, 28 skipped (dev 6655 / the same 4 / 28). The 4 are test_cas_api_client ×2 and test_nidp_stamp_broadcast_at (network-only), plus test_desk_paper_safety::test_i14 (expiry_in_past against today's clock). All 4 fail identically on dev.
Stated limits: the risk estimate prices a flat put side's exit at S = 0 (Rs 4,293 of costs on a 1-lot NIFTY bull put vs Rs 113 at the strike). The credit rule uses those costs as specified, so index bull put spreads and equal-wing iron condors cannot pass it. The estimate was NOT changed: that needs an owner decision. The collar width is an assumption (max loss before premiums).
UNVERIFIED: the deployed build over HTTP; the Trade Desk / Risk Desk UI showing the credit rule (frontend not touched).
