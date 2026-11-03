# Regression baseline — backend, origin/dev @ 48556220 (2026-10-28 ~05:15 IST)
Command (CI-equivalent env, throwaway container, --network none, snapshot mounted read-only):
docker run nivesh/backend:staging python -m pytest <38 files> -q -p no:cacheprovider
Files: test_ai_trader, _config_risk, _execution, _strategy; test_backtest_exit_rules; test_backtest_provenance;
test_copilot_backtest; test_desk_strategy_trades; test_desk_trading; test_exit_rules; test_fno_backtest;
test_fno_idea_paper_trade_contract; test_fno_margin; test_fno_routes; test_option_pricing; test_paper_exit_rules;
test_paper_trades_routes; test_payoff_cost_card; test_plan_sizing; test_risk_gate; test_screen_to_strategy;
test_strategy_backtest_adjusted; _sizing; test_strategy_config; test_strategy_engine; test_strategy_evidence_sources;
test_strategy_ideas; test_strategy_levels; test_strategy_market_data; test_strategy_payoff; test_strategy_plan;
test_strategy_plan_templates_route; test_strategy_screen; test_strategy_templates_first_wave; test_trade_lifecycle;
test_trade_lifecycle_routes; test_trade_plan; test_trade_plan_contract
Result: 1701 passed, 3 warnings in 96.93s
Note: needs repo-root research/ on disk (ai_trader imports research.charting).
Frontend e2e baseline NOT yet run: copilot-app-desk-lab, -desk-strategy-builder, -desk-strategy-graphs,
-desk-strategy-ideas, -desk-strategy-top, -desk-trade-desk, copilot-app-builder, copilot-app-backtest-universe,
strategy-config-bot-details.
