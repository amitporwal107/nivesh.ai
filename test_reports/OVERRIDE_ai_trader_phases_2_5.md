REASON: AI Trader Phases 2 to 5 live on the unmerged branch feat/ai-trader-phases-2-5, so the staging API endpoint tests this gate requires cannot run. The ten new /api/ai-trader strategy, signal, ticket and journal endpoints do not exist on staging. Two agents are still editing routes/ai_trader.py, execution.py and strategy.py as I write this, fixing confirmed review defects, so the code is not final on the branch either.

Asked of the user, and still outstanding:
1. Merge the Phase 1 follow-up branch, so the staging backend container mounts research/. Without it /api/ai-trader/evidence answers 503 research_engine_unavailable (verified on staging at 08:23 UTC today).
2. Merge this branch and send a staging session_token, so the Phases 2 to 5 endpoint cases in test_reports/ai_trader_phases_2_5_TESTCASES.md can run. Every staging row there is NOT RUN.

VERIFIED at unit level, in a container built from the staging image with the tree mounted read-only and no network:
- `python -m pytest tests/test_ai_trader{,_config_risk,_strategy,_execution}.py -q` -> `402 passed, 1 warning in 42.91s`, taken before this round of review fixes.
- `python -m pytest tests/test_ai_trader_config_risk.py -q` -> `201 passed in 0.64s` after the two governor sizing defects were fixed test-first, with 7 of 7 mutants killed.
- `python -m pytest tests/test_ai_trader_strategy.py tests/test_ai_trader_config_risk.py -q` -> `330 passed in 2.56s`
  after the seven strategy gate defects were fixed test-first, with 9 of 9 mutants killed on the second pass.
- `python -c "import server"` registers all 13 /api/ai-trader paths.
- `python -m pytest tests/test_desk_trading.py tests/test_desk_alerts.py -q` -> `104 passed`, the desk engine the paper trades are written through.

NOT VERIFIED, and this is the important part. An adversarial review (45 agents, 39 findings, 31 confirmed by a second agent whose job was to refute them, 8 refuted) found 5 CRITICAL defects in this branch, including two ways to read the sealed out-of-sample block 2023-01-01..2024-07-31 more than once:
- A failed holdout backtest never persists the one-shot marker, so the sealed window can be re-read for as long as the data provider keeps failing, and two concurrent requests both open it.
- The signals route had no sealed-window check at all, so any past as_of inside the block screened the warehouse with nothing recorded.
- A reduced order could be stored at full size, because the confirm path re-sized from the un-reduced quantity.
A third sealed-window leak was found by one fixing agent inside another's file and is being fixed: ticket confidence
was read from the most recent stored run including the holdout run, so the sealed block would have become the basis of
the system's own confidence claims and then fed calibration.

Fixes for the route and execution defects are in progress and UNVERIFIED until the owning agents report with real test output. Until then this branch must not be merged to dev.

A pattern in the findings that the owner should weigh, because tests passing did not catch it: several defects were not wrong arithmetic but false confidence. The sector limit reported itself as checked while always measuring zero exposure; the volatility and bear-market size factors were a no-op whenever a hard cap bound, while the decision still said "size is cut"; the survivorship gate banned one provider label and passed on the others, so it would never have fired on staging. Each read as a working safeguard while protecting nothing.

THE FINDING THE OWNER MUST DECIDE ON, verified by me directly this turn: the shared backtester
services/strategy_engine/backtest.py has NO position size anywhere. `grep -c "quantity"` over that file returns 0, and
line 251 is `trade.pnl_abs = (exit_price - trade.entry_price) - 2 * brokerage_inr`, the profit on ONE share, which is
then added to an equity series starting at starting_capital (line 267, 294). So `total_return_pct` and
`max_drawdown_pct` are one-share rupees expressed as a percentage of a ten lakh account: a 6 per cent stop on a 1,400
rupee share moves the account by about 0.01 per cent, so the -25 per cent drawdown floor in assumption B3 cannot bind.
This affects the existing Strategy Builder too, not only the AI trader, since both read the same engine.
The gates now fail closed, requiring a run to declare metrics["sizing_basis"] == "portfolio", and nothing emits that
key today, so ON A REAL ENGINE RUN NO STRATEGY CAN CURRENTLY REACH THE PAPER STAGE. That is the honest state rather
than a defect introduced here. Three ways forward are written up as PRD section 10c and open question 4; I recommend
teaching the engine to size positions, and did not choose on the owner's behalf.

Other known limits, not hidden:
- No real backtest has run. strategy_engine.backtest.run_backtest needs the NIDP Postgres pool, which no unit test has. Only the call shape is proven. Whether any strategy clears the paper gate on real data is unknown.
- No real screen, no real Mongo: the unique ticket index is asserted as requested, not as enforced, and the duplicate-key branch is exercised with a simulated raise.
- Gate thresholds (PRD B3) and risk limits (B5) are assumptions awaiting the owner's review. So is the governor's new conservative reading of an unknown sector, which now refuses new orders on a book above 30 per cent of capital with no sectors recorded.
- Three pre-existing defects in services/strategy_engine/backtest.py are reported and deliberately not fixed here: the equity curve only moves on trade exits so max drawdown is understated, a no-data window returns metrics that read as a real run, and profit factor is undefined rather than infinite with no losing trades.
