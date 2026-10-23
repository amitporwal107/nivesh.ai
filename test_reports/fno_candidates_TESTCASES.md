# Top-5 F&O build-up candidates with analysis and a best-fit strategy (2026-10-23): test cases, authored before implementation

Ask (user): from the F&O lab's four build-up categories (long build-up, short build-up, short covering, long unwinding) pull
the top 5 candidates of each, with delivery / cash / technical / fundamental analysis, and a strategy for each; the same for
NIFTY and BANKNIFTY. First of three pieces (next: live in-app notifications, then alerts for held positions).

Design (grounded in the repo):
- New read-only `GET /api/fno/scan/candidates?per=5` joins the existing build-up scan (DaaS /desk/fno-buildup) with
  one bulk read of the engineered features (DaaS /features/bulk: SMAs, RSI, MACD, delivery trend, volume z-score, ROE, ROCE,
  debt, growth). Pure rules in `services/fno_candidates`, thresholds in the response (`rules`), no score, no probability.
- Ranking (user's PRD, 2026-10-23): among the largest |OI change| stocks of a category that pass a liquidity floor, a
  configurable weighted rank score over five components: F&O signal strength 30%, cash confirmation 25%, technical 20%,
  fundamental 15%, strategy and risk quality 10%. The weights are a proposed starting configuration, not validated: they
  are returned in `rules`, and the score is an ordering aid, never a probability. A component with no data is unknown and
  left out (the others are renormalised and `coverage` says how much weight was known). Fundamental quality never removes a
  candidate and weighs 15% at most; it is a separate dimension from the signal and from execution quality.
- Six checks feed the components: cash confirms, volume elevated, delivery rising (cash group); trend aligned, momentum
  aligned, entry not extended (technical group). A `signal_state` (candidate / confirmed / invalidated / unavailable,
  PRD 10.5) never calls a single price-and-OI move confirmed.
- The best-fit strategy is NOT computed here: the card asks the existing plan engine (POST /api/desk/strategy/plan, direction
  bullish / bearish from the category). The repo ranks strategies by fit to the regime, not performance, and has no validated
  model, so nothing here is called "most profitable".

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | engine | rows are grouped by the route's own label; neutral and no-data rows never appear | unit | four groups |
| TC-2 | engine | liquidity floor and minimum move: a thin or tiny-move row is excluded and counted with a reason; a row with no turnover is unknown, excluded | unit | `excluded` counts |
| TC-3 | engine | each of the five checks passes / fails / is unknown on crafted features, for a bullish and a bearish category | unit | states and observed text |
| TC-4 | engine | ranking by the weighted rank score: components, renormalisation over known ones, coverage, ties by |OI change|, at most `per` returned | unit | order, scores |
| TC-4b | engine | entry viability: a stock already stretched beyond its normal range fails "entry not extended" and is never called confirmed | unit | state |
| TC-4c | engine | signal_state: confirmed needs cash confirmation plus at least two of the other known checks and an unextended entry; invalidated when cash diverges and the trend is against; unavailable below three known checks | unit | state |
| TC-4d | engine | weights are read from `rules`; changing them changes the order; a fundamentals-only difference moves the score by at most the fundamental weight | unit | order |
| TC-5 | engine | fundamentals: strong / mixed / weak / unavailable by the written rule; "agrees" flips with the direction | unit | rating, agrees |
| TC-6 | engine | missing features for a symbol: candidate still listed, checks unknown, fundamentals unavailable, never zero | unit | unknowns |
| TC-7 | engine | index rows (NIFTY, BANKNIFTY) listed with label, cash check and an explicit "no delivery or fundamentals for an index" note | unit | index block |
| TC-8 | engine | plan_inputs per candidate: direction bullish for long build-up and short covering, bearish for the other two | unit | direction |
| TC-9 | api | route 200 with the four categories, rules and disclosure; DaaS build-up unreachable is 502; features unreachable still answers with unknown analysis | api | shape / 502 / degrade |
| TC-10 | api | signed out is 401; `per` out of range is 422 | api | status |
| TC-11 | e2e | the F&O build-up tab shows a Top candidates section: category switch, five cards each with the five checks, fundamentals tag and risk flags | e2e | cards |
| TC-12 | e2e | a card's best-fit strategy loads lazily from the plan route; its failure or no_trade status is said plainly, not hidden | e2e | states |
| TC-13 | e2e | the NIFTY / BANKNIFTY block, and the honesty line (fit to conditions, not performance; heuristic, not proof of intent) | e2e | text |
| TC-14 | static | tsc clean; existing desk-lab, screener, workspace specs pass | regression | pass |
