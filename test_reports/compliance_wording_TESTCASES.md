# Compliance wording — test cases, inventory and planned replacements (written BEFORE any edit)

Branch `fix/compliance-wording` (from origin/dev `19d8d974`), worktree `/home/deploy/nivesh-wt-wording`. Status: **IN PROGRESS**.

## 1. The rule (owner, 3 Nov 2026)

> "Please check compliance and do not use words like buy, stop loss, target"

Nivesh.ai is not a SEBI-registered Research Analyst, so no user-visible text may read like a trading call. The owner said
"ok" to the replacement vocabulary below. "Words like" also covers exit / book profits / accumulate / add / trim / upside /
downside / price target / recommend(ed) / pick(s) / suggested trade / "buy now" / "sell signal". The 25 Oct rule still
applies: "ideas", "fits", "ordered for review"; never "pick", "recommend", "suggested", "best trade".

## 2. Vocabulary (approved, then derived for each context)

| Old (trading sense) | New | Note |
|---|---|---|
| Buy / BUY / leg button "B" | **Long** / LONG / "L" | approved; legs too: "Buy 1 NIFTY 24000 CE" → "Long 1 NIFTY 24000 CE" |
| Sell / SELL / leg button "S" | **Short** / SHORT / "S" | approved |
| Stop loss / SL / stop / stop-loss / "Exit if wrong" | **Risk level** | approved |
| Target / T1 / T2 / "Exit if right" | **Reward level** / Reward level 1 / Reward level 2 | approved |
| Entry / entry price / "Buy at" / "Buy price" | **Reference price** | approved |
| Loss at stop / LOSS AT STOP (`max_loss_at`) | **Loss at risk level** | approved |
| Profit at target | Profit at reward level | derived |
| Trailing stop / initial stop | Trailing risk level / initial risk level | derived |
| Stopped / stopped out / "Target hit" | Risk level reached / Reward level reached | derived |
| Entry reached / Waiting for entry / Entry not reached | Reference price reached / Waiting for the reference price / Reference price not reached | derived |
| Exit / Exit rule / Exit reason / Time exit / Trend exit (the user's OWN paper position) | Close / Close rule / Close reason / Time close / Trend close | "Close position" only for the user's own paper position |
| Bought / Never bought (paper states) | Opened / Never opened | derived |
| Buy above ₹X / Buy on a dip to ₹X / Buy now | Long above ₹X / Long on a dip to ₹X / At the current price | derived from Long |
| Upside / downside (to a level) | Reward / risk (a share), room to the reward / risk level | derived |
| Downside / upside capture, downside risk (portfolio statistics) | Down-market / up-market capture, loss risk | derived, LISTED |
| Recommend / recommendation(s) / recommended / pick(s) | ideas / fits / ordered for review | 25 Oct rule |
| Suggested trade / suggested strategy / best trade | idea / structure that fits | 25 Oct rule |
| Buy signal / sell signal | Long setup / short setup | derived |
| Accumulate / add (to a holding) | raise weight / increase holding (descriptive) | derived, LISTED |
| Trim / reduce (as a call) | lower weight (descriptive) | derived, LISTED |
| Book profits / profit booking | realised gains / gains realised | derived, LISTED |
| Gross buy / gross sell (FII-DII, deals) | gross purchases / gross sales | derived (data label; exchange codes unchanged) |
| Net buyers / net sellers | net inflow / net outflow | derived |
| Price target / target price | (no price targets: removed) | |
| Pick (UI verb: "pick a date") | choose | trivial, avoids ambiguity |
| Target allocation / target mix (portfolio) | planned mix | derived, LISTED |
| Goal target / target amount | goal amount | derived, LISTED |

Words left as they are because they are not a trading call in context: "Stop" / "Exit" as UI controls (stop streaming, exit
full screen), "entry" meaning a record (journal entry, list entry), "add" as a UI verb (add to list, add a goal), "hold" /
holdings, short-term / long-term, "Suggestions" / "suggested questions" for chat prompt chips, "Long/Short buildup" (OI
categories).

## 3. Classification rules

- **CHANGE** — user-visible text: JSX text, labels, titles, `aria-label`, placeholders, notices, chips, tooltips, error
  messages, backend builder labels / notices / follow-ups / suggestion templates, LLM answer instructions.
- **KEEP (contract)** — API field names and values (`stop_loss`, `target`, `entry`, `side: "BUY"`, `exit_reason` codes),
  route paths, exchange data codes. Where such a value is rendered RAW (e.g. `{l.side}`), add a display mapping; the data
  stays.
- **KEEP (identifier)** — variable / type / component / file names (`TargetMix`, CSS `target`), `data-testid`, keys,
  comparisons, string-literal types.
- **KEEP (question recognition)** — regexes that recognise these words in a USER'S question. Where a chip's visible text
  changes, its new wording must still route to the same intent; if it does not, the regex is EXTENDED additively (old
  words still recognised) and the change is listed.
- Comments and docstrings are not user-visible: unchanged.

## 4. Inventory (machine-extracted on the untouched tree, then classified by hand while editing)

Extraction: frontend with the TypeScript compiler API (string literals, template text, JSX text; comments excluded) over
`frontend-v5/src/pages/CopilotApp` and `frontend-v5/src/components/chat`; backend with Python `ast` (string constants and
f-strings; docstrings excluded) over `services/copilot_visual`, `services/suggestions`, `nidp/services/copilot_agent` and the
desk / idea / level / prompt routes. Candidate regex:
`buy|sell|sold|bought|stop[- ]?loss|sl|stop(s|ped)?|target(s)?|t1|t2|entry|entries|exit(s|ed)?|book profits|profit booking|accumulate|trim|upside|downside|recommend\w*|pick(s)?|suggested|suggestion|suggest(s)?`.

Codes: `C?` = user-visible candidate (change unless it is a non-trading sense), `K-tok?` = single-token literal (contract
value; change only where rendered raw), `K-id` = identifier / key / test id / comparison (keep, not listed one by one).

| Area | C? (user-visible candidate) | K-tok? (single token: contract value unless rendered raw) | K-id (identifier/key/test id/comparison) |
|---|---:|---:|---:|
| be-nidp/services | 60 | 13 | 2 |
| be-routes | 81 | 26 | 34 |
| be-services/copilot_visual | 114 | 86 | 25 |
| be-services/suggestions | 15 | 6 | 7 |
| fe-app-other | 212 | 32 | 53 |
| fe-chat | 28 | 6 | 5 |
| fe-desk | 565 | 189 | 215 |

Raw renders of API values found by a separate grep (need a display mapping, data unchanged):
`tabs/trade-desk/StructureCard.tsx` `{l.side}`, `tabs/trade-desk/analysis/OptionChain.tsx` `{side}`,
`tabs/trade-desk/Journal.tsx` `{r.side}`, `chartink/ChartinkPicks.tsx` `{pick.action}`, `PaperDesk.tsx` `{w.signal}`.

Out of scope (older non-Copilot v5 pages and shared components; NOT changed, listed for the owner): 515 candidate strings —
pages/Research 116, pages/Learn 95, pages/Blog 67, pages/Copilot 58, pages/Chat 25, pages/Dashboard 23, pages/FlowLedger 13,
components/shared 11, pages/StrategyBuilder 11, components/marketing 9, pages/AdvisorDashboard 7, pages/Concentration 7,
pages/Markets 7, components/admin 6, pages/Recommendations 6, pages/Performance 5, and ≤ 4 each in 23 more folders.

## 5. Test cases

| ID | Type | Case | Expected |
|---|---|---|---|
| TC-1 | unit (backend, NEW) | every `copilot_visual` builder payload for the fixtures used by the existing suites, run through a banned-word lint | no banned word in any user-visible string (titles, labels, cells, notices, follow-ups) |
| TC-2 | unit (backend, NEW) | every static string in `services/suggestions/catalog.py` templates and `copilot_visual` follow-up chips | no banned word |
| TC-3 | unit (backend, NEW) | `copilot_agent` answer + compliance prompts carry the vocabulary rule; `compliance_node` scrubs the new phrases ("stop loss at", "target of", "buy now", "sell signal", "book profits") and its own note has no banned word | rule present; scrub fires; note clean |
| TC-4 | unit (backend) | existing copilot_visual / suggestions / copilot_agent / desk / positional / paper / strategy suites | same pass/fail as the dev baseline, with only the asserted texts updated |
| TC-5 | contract | repo-wide grep of each API field / value touched (`stop_loss`, `target`, `entry`, `side`, `"BUY"`, `"SELL"`, `exit_reason` …) in the diff | no field name or value changes in request/response shapes; only labels |
| TC-6 | e2e (Playwright, NEW) | render the Trading Desk screens (Scanner, Top 10, Chart, F&O builder / levels / strategies, Risk Desk, Paper Desk, Trade desk analysis) with mocked API and scan `document.body.innerText` + `aria-label`/`title` | no banned word in the rendered text |
| TC-7 | e2e (Playwright) | existing copilot-app specs | same pass/fail as the dev baseline, with only the asserted texts updated |
| TC-8 | typecheck | `tsc --noEmit -p tsconfig.json` | no new errors vs dev |
| TC-9 | edge | a value that is a contract code AND rendered (side "buy"/"BUY") | shows Long / Short; `data-side` attribute and payload unchanged |
| TC-10 | edge | words in a non-trading sense ("Stop" streaming, "journal entry", "add to list", "Suggestions") | unchanged, not flagged by the guards (allow-list) |
| TC-11 | question routing | each chip / example question whose visible text changed | routes to the same intent as before (backend intent regexes) |
| TC-12 | staging (read-only, now) | fetch the deployed staging desk pages / APIs with the session token | lists where the old words still show today (expected before merge) |
| TC-13 | staging (after merge + deploy) | same pages after deploy | old words gone — UNVERIFIED until merged and deployed |

## Appendix — full candidate inventory (untouched tree)

### Frontend (`frontend-v5/src/`)


**components/chat/ChatWidget.tsx** — 5 to review, 1 identifier/key/comparison (keep)

- `C?` L1084 [jsx] Recommendation
- `K-tok?` L1490 [attr:dataKey] target
- `C?` L2884 [jsx] No realised gains recorded for this FY — no sell/redeem transactions. This covers
- `K-tok?` L2961 [prop:query] /recommendations
- `C?` L2961 [jsx] Open recommendations →

**components/chat/CopilotDock.tsx** — 4 to review, 3 identifier/key/comparison (keep)

- `C?` L65 [prop:"/recommendations"] Recommendations
- `K-tok?` L179 [prop:note] stopped
- `C?` L357 [jsx] Stopped
- `C?` L411 [attr:aria-label] Stop generating

**components/chat/PortfolioBuilderWidget.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L43 [var:STEPS] Pick
- `C?` L47 [prop:label] Buy a home
- `C?` L527 [jsx] Model and category-level guidance, not a recommendation of specific schemes or stocks. Projections use house capital-market assumptions and ignore taxes; mutual

**components/chat/ResearchLauncher.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L27 [prop:label] Worth buying now?
- `C?` L38 [prop:label] Worth buying now?
- `C?` L57 [return] Should I buy ${…}?

**components/chat/ScreenerQueryBuilder.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L244 [jsx] Add a condition or pick a universe to build a screen

**components/chat/StrategyLabWidget.tsx** — 9 to review, 1 identifier/key/comparison (keep)

- `C?` L65 [prop:0] Pick the pool of stocks to screen against. All liquid NSE stocks is point-in-time: a backtest on it has no survivorship bias.
- `C?` L67 [prop:2] Run the entry rules against the latest data to see the ranked candidates.
- `C?` L69 [prop:4] Save the strategy and export its target portfolio. Live order placement is advisory-only.
- `C?` L148 [prop:title] Run the screen first to build a target portfolio
- `C?` L159 [prop:title] Exported ${…} target holdings
- `C?` L280 [jsx] Entry rules (all of)
- `C?` L281 [jsx] No entry rules in this template.
- `C?` L386 [jsx] Export target portfolio
- `C?` L391 [jsx] Deployment is advisory-only: export the target portfolio (equal-weight of the screened set) to your broker/OMS. Automated order placement is a later, compliance

**components/chat/TradePlanChatCard.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L120 [jsx] ) and sized by your risk profile. Enter only when the entry condition is met. An idea to review, not a recommendation; nothing is sent to a broker.

**components/chat/screenerPrimitives.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L53 [prop:hint] buying pressure

**components/chat/visual/VisualAnswer.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L150 [var:text] Updates stopped${…} · as of ${…} IST

**components/chat/visual/blocks/Candles.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L19 [prop:name] Entry
- `C?` L20 [prop:name] Stop
- `C?` L21 [prop:name] Target

**components/chat/visual/schema.ts** — 3 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L30 [var:LEVEL_KINDS] entry
- `K-tok?` L30 [var:LEVEL_KINDS] stop
- `K-tok?` L30 [var:LEVEL_KINDS] target

**pages/CopilotApp/components/DailyTraderPanel.tsx** — 6 to review, 0 identifier/key/comparison (keep)

- `C?` L33 [prop:questions] Find today's top 5 trading opportunities with entry, stop-loss and targets
- `C?` L36 [prop:questions] Is this stock a buy now?
- `C?` L37 [prop:questions] What is the entry, target and stop-loss for this stock?
- `C?` L42 [prop:questions] Should I book profits or hold?
- `C?` L58 [prop:questions] Did I follow my entry, stop-loss and exit rules?
- `C?` L164 [jsx] Answers use the latest market data available and show its date. Ideas to review, not recommendations; nothing is sent to a broker.

**pages/CopilotApp/components/NiftyFallCard.tsx** — 0 to review, 1 identifier/key/comparison (keep)


**pages/CopilotApp/components/SuggestionsPanel.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L121 [attr:aria-label] Suggestion categories
- `C?` L163 [jsx] Nothing to suggest in

**pages/CopilotApp/lib/answer.ts** — 1 to review, 2 identifier/key/comparison (keep)

- `C?` L55 [var:head] Stopped

**pages/CopilotApp/lib/use-copilot-prompts.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L78 [prop:path] /api/copilot/suggested-prompts

**pages/CopilotApp/lib/use-suggestions.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L144 [prop:queryKey] suggestion-why

**pages/CopilotApp/lib/use-thread-engine.ts** — 1 to review, 1 identifier/key/comparison (keep)

- `K-tok?` L233 [prop:note] stopped

**pages/CopilotApp/lib/use-thread-turns.ts** — 0 to review, 1 identifier/key/comparison (keep)


**pages/CopilotApp/lib/views.ts** — 2 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L43 [prop:view] tool/recommend
- `C?` L43 [prop:label] Recommendations

**pages/CopilotApp/screens/Advisor.tsx** — 7 to review, 0 identifier/key/comparison (keep)

- `C?` L261 [prop:label] Which clients are off their target allocation?
- `C?` L261 [prop:query] Which clients are deviating more than 10% from their target allocation? List the bucket that is off.
- `C?` L264 [prop:label] Which clients stopped their SIPs recently?
- `C?` L264 [prop:query] Which of my clients have stopped or paused SIPs in the last 3 months? Show last contribution date.
- `C?` L265 [prop:query] Draft a portfolio review for my client ${…}: what changed, the top issue and the recommended next step.
- `C?` L279 [attr:sub] Your ${…} ranked on portfolio weakness, risk, assets, pending recommendations and time since the last review. Open any client in the Copilot to work on their pl
- `C?` L288 [attr:body] No client has a risk flag, a pending recommendation or an overdue review right now.

**pages/CopilotApp/screens/Ledger.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L120 [attr:note] ${…} sold ${…} · FIFO
- `C?` L263 [attr:body] You can correct a holding’s buy price, purchase date or units from its row above. What is not there yet: a list of the corrections you made with a way to undo o
- `C?` L265 [attr:needs] A corrections log written by PUT /api/portfolio/holdings/{id} (what changed, when, the value before) and an endpoint to list and undo entries

**pages/CopilotApp/screens/Onboarding.tsx** — 4 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L67 [var:PICK_KEY] nivesh.copilot.onboarding-pick
- `C?` L171 [attr:body] A short questionnaire places you between Conservative and Aggressive. Nivesh uses the result in its recommendations.
- `C?` L182 [attr:body] Limits such as the most you want in one stock or one sector, a cash buffer, or things never to suggest.
- `C?` L185 [attr:needs] Recommendations and Copilot answers reading those limits

**pages/CopilotApp/screens/OpsFeeds.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L166 [jsx] seconds · this page does not start or stop any job

**pages/CopilotApp/screens/OpsKpis.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L145 [attr:needs] Feed freshness within SLA — a per-source freshness target and a daily history of whether it was met (the quality gate scores one day at a time)

**pages/CopilotApp/screens/Paper.tsx** — 23 to review, 0 identifier/key/comparison (keep)

- `C?` L52 [prop:summary] Full record adds the ranked universe, each trade’s path, every exit mode and the benchmarks
- `C?` L64 [prop:"EOD-1"] close of the entry day
- `C?` L67 [prop:FIXED] close of day 5, no early exit
- `K-tok?` L175 [prop:key] entry
- `C?` L175 [prop:header] Entry
- `K-tok?` L176 [prop:key] stop
- `C?` L176 [prop:header] Stop
- `K-tok?` L177 [prop:key] target
- `C?` L177 [prop:header] Target
- `C?` L185 [arrow] Awaiting entry
- `K-tok?` L200 [prop:key] entry
- `C?` L200 [prop:header] Entry
- `K-tok?` L201 [prop:key] exit
- `C?` L201 [prop:header] Exit
- `C?` L219 [var:note] Predicted ${…} · entry ${…}
- `C?` L227 [attr:title] headline exit
- `C?` L228 [attr:empty] Nothing in this session has reached its headline exit yet.
- `C?` L251 [jsx] Entries at the next session’s official open. Target +
- `C?` L251 [jsx] % from entry. Stop
- `C?` L251 [jsx] × ATR(14) below entry, or the 10-session support when that is lower, never more than
- `C?` L252 [jsx] % below entry. Costs
- `C?` L252 [jsx] . Headline exit
- `C?` L372 [jsx] → entry

**pages/CopilotApp/screens/Recommend.tsx** — 12 to review, 20 identifier/key/comparison (keep)

- `C?` L100 [prop:s] No exit step has a tax estimate yet
- `C?` L102 [prop:s] Covers ${…}% of exit steps
- `C?` L103 [prop:s] Across the plan’s exit steps
- `C?` L109 [prop:s] From exits and trims
- `K-tok?` L177 [attr:idPrefix] recommend-card
- `K-tok?` L245 [attr:idPrefix] recommend-filter
- `C?` L246 [attr:aria-labelledby] recommend-filter-tab-${…}
- `C?` L271 [call:ask] Why these recommendations? Explain what each one is based on.
- `C?` L273 [attr:eyebrow] Recommendations · from your holdings, goals and risk profile
- `K-tok?` L296 [attr:idPrefix] recommend
- `C?` L299 [attr:label] Loading recommendations
- `C?` L301 [attr:title] Recommendations didn’t load

**pages/CopilotApp/screens/Research.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L71 [attr:title] Pick a stock to research
- `C?` L82 [attr:title] Pick a mutual fund to research

**pages/CopilotApp/screens/Screener.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L614 [jsx] Give at least one rule a value, or pick a market-cap universe.
- `C?` L708 [jsx] End-of-day data, with Kite’s live price while the market is open · fund holdings are disclosed monthly, Nifty 500 only · screen matches are candidates, not reco

**pages/CopilotApp/screens/Settings.tsx** — 4 to review, 0 identifier/key/comparison (keep)

- `C?` L100 [PropertyAccessExpression] ${…} target
- `C?` L270 [attr:sub] Your risk profile, goals and connected sources drive what Nivesh recommends.
- `C?` L311 [attr:body] A single-stock limit, a sector limit, a cash buffer and things never to suggest. Nivesh keeps your risk profile and goals, but no limits of your own.
- `C?` L314 [attr:needs] Recommendations and Copilot answers reading those limits

**pages/CopilotApp/screens/TradingDesk.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L693 [jsx] Scanner setups are end-of-day and rules-based. Probabilities are model outputs for the next session, not buy or sell recommendations. Broker connections are rea

**pages/CopilotApp/screens/Watchlist.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L148 [attr:sub] Pick a watchlist on the left. This week's results names. The AI scanner's daily ideas, your own lists, the research watchlist with live prices, your saved scree

**pages/CopilotApp/screens/account/parts.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L351 [jsx] . Any other sheet needs a heading row with a Name and a Quantity column; Symbol or ISIN, Buy price, Current price, Type, Sector and Buy date are read when prese
- `C?` L481 [jsx] Disconnect Gmail? Automatic imports stop.

**pages/CopilotApp/screens/advisor/Client360.tsx** — 3 to review, 2 identifier/key/comparison (keep)

- `C?` L208 [prop:header] Bought on
- `C?` L292 [prop:k] Tax if all were sold today
- `C?` L500 [prop:query] Draft a portfolio review for my client ${…}: what changed, the top issue and the recommended next step.

**pages/CopilotApp/screens/advisor/data.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L203 [return] Long-term · debt bought before April 2023

**pages/CopilotApp/screens/desk/BrokerPositions.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L566 [attr:title] Day P&L and a stop or target per position are not read
- `C?` L567 [attr:body] Holdings, open positions and cash are read live from a connected broker. Its day P&L is not, and a broker’s book has no stop or target, so none of those are sho
- `C?` L571 [attr:needs] A stop and a target for each position; a broker’s book has neither.

**pages/CopilotApp/screens/fnolab/Audit.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L31 [prop:k] Paper entry hashes

**pages/CopilotApp/screens/fnolab/governance-data.ts** — 0 to review, 6 identifier/key/comparison (keep)


**pages/CopilotApp/screens/index.ts** — 1 to review, 1 identifier/key/comparison (keep)

- `K-tok?` L11 [call:import] ./Recommend

**pages/CopilotApp/screens/internal/data-sources.ts** — 10 to review, 0 identifier/key/comparison (keep)

- `C?` L135 [prop:what] The active action plan and its steps, the record of past decisions, what the plan would change, and the top recommendations for each asset class.
- `C?` L142 [prop:endpoints] GET /api/portfolio/recommendations/v5
- `C?` L152 [prop:what] The user's goals with their targets and dates, and the risk profile from the assessment they answered.
- `C?` L180 [prop:what] Realised short-term and long-term gains for the financial year, the tax they lead to, and loss-making lots that could be sold to offset gains.
- `C?` L388 [prop:what] The scanner's scored signals, setups to watch with trigger and stop levels, and the trades the user has logged with their results.
- `C?` L390 [prop:endpoints] GET /api/positional/picks
- `C?` L434 [prop:note] A public route that needs no sign-in. Internal research, not a recommendation.
- `C?` L532 [prop:what] The streamed answer to a question with its tool steps and result card, the user's past threads, the specialist agents, and suggested questions.
- `C?` L538 [prop:endpoints] GET /api/chat/suggest-queries
- `C?` L540 [prop:endpoints] GET /api/copilot/suggested-prompts

**pages/CopilotApp/screens/internal/ops-feeds-sections.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L132 [prop:header] Stops publishing

**pages/CopilotApp/screens/internal/ops-kpi-sections.tsx** — 8 to review, 0 identifier/key/comparison (keep)

- `C?` L263 [prop:header] Entry setup
- `K-tok?` L264 [prop:key] target
- `C?` L264 [prop:header] Profit target
- `C?` L276 [attr:what] The entry-setup study
- `C?` L285 [prop:k] Entry setups that beat the baseline
- `C?` L287 [prop:s] Setup and profit-target pairs tested, after costs
- `C?` L295 [attr:title] Entry-setup study · result per setup
- `C?` L336 [jsx] The table that compares the positional engine’s scores with what followed is empty. An admin job fills it once enough past picks have a known outcome; until the

**pages/CopilotApp/screens/internal/ops-platform-data.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L334 [prop:queryKey] entry-setup-research

**pages/CopilotApp/screens/internal/ops-tools-sections.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L42 [prop:body] The backend returned an empty model list, so the chat has no model to pick.

**pages/CopilotApp/screens/internal/tool-templates.ts** — 33 to review, 0 identifier/key/comparison (keep)

- `C?` L59 [var:NO_ORDERS] No order placement: nothing here buys, sells or moves money
- `C?` L103 [prop:freshness] The saved risk profile, for the target mix
- `C?` L120 [prop:services] GET /api/portfolio/recommendations/v5
- `C?` L129 [prop:outputs] The asset mix against the target for the user's risk category
- `C?` L139 [prop:guardrails] The target mix is the one for the user's saved risk category; an asset class outside it is listed with no target
- `K-tok?` L148 [prop:id] recommendations
- `K-tok?` L149 [prop:view] tool/recommend
- `C?` L150 [prop:name] Recommendations
- `C?` L155 [prop:questions] What is each recommendation based on?
- `C?` L179 [prop:outputs] On each step: its verb, severity, suggested route, amount, reason, tax breakdown and expected effect
- `C?` L189 [prop:guardrails] Marking a step records the user's decision; nothing is bought or sold
- `C?` L219 [prop:outputs] The user's risk profile and its target mix
- `C?` L252 [prop:outputs] Suggested moves
- `C?` L266 [prop:questions] Which holdings could I sell at a loss to lower my tax?
- `C?` L276 [prop:outputs] Suggested moves
- `C?` L345 [prop:gaps] Fund page: a NAV chart, returns against the benchmark, the fund's score, its exit load and its overlap with the funds the user holds have no source on the page.
- `C?` L393 [prop:guardrails] Screen matches are candidates, not recommendations
- `C?` L412 [prop:questions] What are foreign and domestic institutions buying and selling?
- `C?` L467 [prop:objective] Let a trader pick a stock universe and a rule template, see which stocks pass today, backtest the rules and save the strategy.
- `C?` L471 [prop:questions] What are the entry and exit rules of this strategy?
- `C?` L477 [prop:rule] sets the entry and exit rules; they can be edited
- `C?` L562 [prop:outputs] The scanner's setups to watch, each with its close, the level to cross and a stop
- `C?` L568 [prop:guardrails] The research list carries its disclaimer: information only, not a recommendation or a buy or sell call
- `C?` L653 [prop:outputs] On each card: the verb, the holding, the amount, the reason, severity, suggested route and tax
- `C?` L657 [prop:guardrails] Moving a step records the user's decision; nothing is bought or sold
- `C?` L687 [prop:type] buy price, purchase date or units of one holding
- `C?` L766 [prop:outputs] Full record: the ranked universe, sizing what-ifs, one trade's path and lifecycle, every exit mode, the benchmarks and the calibration buckets
- `C?` L852 [prop:questions] Which clients are off their target allocation?
- `C?` L854 [prop:questions] Which clients stopped their SIPs recently?
- `C?` L986 [prop:rule] typed, or picked from a suggested question
- `C?` L993 [prop:services] GET /api/copilot/suggested-prompts
- `C?` L994 [prop:services] GET /api/chat/suggest-queries
- `C?` L1010 [prop:guardrails] A stopped or failed answer is never labelled as done

**pages/CopilotApp/screens/markets/BriefTab.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L45 [attr:body] The Daily Iris Update is written after the market data refreshes. Pick an earlier day, or check back shortly.

**pages/CopilotApp/screens/markets/FlowsTab.tsx** — 10 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L46 [call:parts.push] sold
- `K-tok?` L46 [call:parts.push] bought
- `K-tok?` L51 [call:parts.push] sold
- `K-tok?` L51 [call:parts.push] bought
- `C?` L95 [prop:header] FII buy
- `C?` L96 [prop:header] FII sell
- `C?` L98 [prop:header] DII buy
- `C?` L99 [prop:header] DII sell
- `C?` L114 [attr:note] Net = buy − sell
- `C?` L208 [jsx] Bars above the line are net buying, below it net selling. Tallest bar:

**pages/CopilotApp/screens/markets/MarketTab.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L498 [jsx] Pick a list to see the stocks nearest their 52-week high or low, or the most traded today.

**pages/CopilotApp/screens/markets/ResearchInstrument.tsx** — 6 to review, 0 identifier/key/comparison (keep)

- `C?` L249 [prop:label] Worth buying now?
- `C?` L249 [prop:query] Should I buy ${…}?
- `C?` L264 [attr:needs] Health, add and exit scores, the SWOT read and the pre-buy checks for a stock: no endpoint
- `C?` L498 [attr:body] A NAV chart, returns against the benchmark, the fund’s score, its exit load and its overlap with the funds you hold have no source on this page yet, so they are
- `C?` L501 [attr:needs] Returns against the benchmark, and 5-year and longer returns from the data platform: /api/portfolio/holding-detail/{isin} stops at 3 years and has no benchmark 
- `C?` L504 [attr:needs] Exit load and beta: in no response used here

**pages/CopilotApp/screens/markets/mkt-HeldResults.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L194 [jsx] . Pick a wider index above to check

**pages/CopilotApp/screens/portfolio/ConcentrationSection.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L149 [arrow] Is ${…} of my fund money with ${…} too much, and which ${…} funds would you trim first?
- `C?` L303 [call:ask] ${…} and ${…} overlap ${…} in my portfolio. Which one should I keep, and what would moving out of the other cost me in tax and exit load?
- `K-tok?` L347 [call:go] tool/recommend

**pages/CopilotApp/screens/portfolio/LedgerHoldings.tsx** — 4 to review, 1 identifier/key/comparison (keep)

- `C?` L45 [prop:label] Exit signal
- `C?` L127 [call:problems.push] The buy price must be a number above zero.
- `C?` L132 [prop:label] Average buy price per ${…}
- `C?` L155 [jsx] Average buy price per

**pages/CopilotApp/screens/portfolio/PerformanceSection.tsx** — 9 to review, 0 identifier/key/comparison (keep)

- `C?` L276 [jsx] . The same fund bought in different folios is merged, and its values and returns are the combined total.
- `C?` L395 [jsx] Loading the recommendation…
- `C?` L397 [jsx] No recommendation data available.
- `C?` L500 [jsx] Recommendation
- `C?` L720 [attr:title] Recommendations
- `K-tok?` L726 [call:go] tool/recommend
- `C?` L726 [jsx] Open recommendations ›
- `C?` L813 [attr:label] Loading recommendations
- `C?` L813 [attr:title] Recommendations didn’t load

**pages/CopilotApp/screens/portfolio/RemediationSection.tsx** — 4 to review, 0 identifier/key/comparison (keep)

- `C?` L152 [PropertyAccessExpression] Walk me through this step for my portfolio: ${…}. ${…} What would it cost me in tax and exit load, and is it worth doing now?
- `K-tok?` L156 [call:go] tool/recommend
- `C?` L156 [jsx] Open recommendations
- `C?` L196 [attr:label] Computing remediation recommendations

**pages/CopilotApp/screens/portfolio/StepControls.tsx** — 2 to review, 1 identifier/key/comparison (keep)

- `C?` L32 [attr:title] The route the plan engine suggests for this step
- `C?` L46 [call:parts.push] exit load ${…}

**pages/CopilotApp/screens/portfolio/TargetMix.tsx** — 20 to review, 10 identifier/key/comparison (keep)

- `C?` L71 [prop:label] Above target
- `C?` L71 [prop:label] Below target
- `C?` L83 [attr:label] Loading your target mix
- `C?` L84 [attr:title] Your target mix didn’t load
- `C?` L91 [attr:title] No target mix yet
- `C?` L92 [attr:body] The target comes from your risk profile, and you have not set one. It takes about two minutes.
- `C?` L103 [attr:title] No target mix for this risk category
- `C?` L116 [var:headline] ${…} is ${…} points ${…} the target.
- `C?` L117 [var:headline] Every class is within ${…} points of the target.
- `K-tok?` L122 [prop:key] target
- `C?` L122 [prop:header] Target
- `C?` L128 [prop:header] Held vs target
- `C?` L130 [attr:aria-label] ${…}: ${…} held, no target
- `C?` L130 [attr:aria-label] ${…}: ${…} held against a target of ${…}
- `C?` L139 [jsx] No target
- `C?` L148 [jsx] Your mix against the target for a
- `C?` L158 [call:ask] My ${…} allocation is ${…} against a target of ${…} for a ${…} risk profile. What would bringing it in line involve, and what would it cost in tax?
- `C?` L162 [jsx] Target = the standard mix for the
- `C?` L166 [jsx] not part of the four-class target, so
- `C?` L166 [jsx] no target of

**pages/CopilotApp/screens/portfolio/concentration-data.ts** — 5 to review, 0 identifier/key/comparison (keep)

- `C?` L341 [prop:trim_amc] Trim AMC
- `C?` L342 [prop:trim_sector] Trim sector
- `C?` L343 [prop:trim] Trim
- `C?` L349 [prop:exit] Exit load
- `K-tok?` L353 [call:kind.startsWith] trim

**pages/CopilotApp/screens/portfolio/data.ts** — 6 to review, 1 identifier/key/comparison (keep)

- `C?` L394 [prop:label] Exit
- `C?` L395 [prop:label] Sell
- `C?` L396 [prop:label] Trim
- `C?` L403 [prop:label] Buy
- `C?` L446 [prop:"sell-now"] Sell now
- `K-tok?` L631 [ForOfStatement] recommendations

**pages/CopilotApp/screens/portfolio/parts.tsx** — 0 to review, 1 identifier/key/comparison (keep)


**pages/CopilotApp/screens/portfolio/performance-data.ts** — 4 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L742 [prop:path] /api/portfolio/recommendations/v5
- `C?` L744 [call:ApiError.contractDr] portfolio.recommendationsV5: missing `top5_by_asset_class`
- `K-tok?` L753 [prop:queryKey] recommendations-v5
- `C?` L762 [prop:label] Exit

**pages/CopilotApp/screens/positions/OpenPositions.tsx** — 26 to review, 5 identifier/key/comparison (keep)

- `C?` L56 [var:risk] Open risk at your stops is ${…}.
- `C?` L57 [var:noStop] ${…} no stop set.
- `C?` L59 [jsx] past their stops
- `C?` L62 [jsx] near their stops
- `C?` L64 [jsx] none near a stop
- `C?` L106 [attr:aria-label] near or past its stop
- `K-tok?` L115 [prop:key] stop
- `C?` L115 [prop:header] Stop
- `K-tok?` L116 [prop:key] target
- `C?` L116 [prop:header] Target
- `C?` L151 [jsx] Loss at your stop:
- `C?` L151 [jsx] (stop
- `C?` L152 [jsx] Set a stop to see the loss at the stop. A to-zero figure is not shown for shares or a long future.
- `C?` L154 [jsx] · at your stop
- `C?` L162 [jsx] · ${…} from the stop
- `C?` L231 [jsx] The stop and target are the paper trade’s own. Change them on the desk’s Paper trades.
- `C?` L244 [jsx] Stop (underlying)
- `C?` L247 [jsx] Target
- `C?` L257 [jsx] Trailing ${…}%: the stop in force is ${…}.
- `C?` L308 [attr:items] Should I trail the stop on my ${…}?
- `C?` L330 [prop:k] Open risk at stops
- `C?` L331 [prop:s] ${…} without a stop
- `C?` L331 [prop:s] Loss if every stop is hit
- `C?` L333 [prop:k] Near a stop
- `C?` L353 [attr:note] ${…} still waiting for its entry
- `C?` L393 [jsx] Payoff, scenarios and the loss at a stop are gross, before brokerage, taxes and slippage.

**pages/CopilotApp/screens/positions/PayoffChart.tsx** — 4 to review, 0 identifier/key/comparison (keep)

- `C?` L63 [call:marker] Stop
- `K-tok?` L63 [call:marker] stop
- `C?` L64 [call:marker] Target
- `K-tok?` L64 [call:marker] target

**pages/CopilotApp/screens/positions/PositionsTile.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L20 [jsx] ${…} near a stop · open ›

**pages/CopilotApp/screens/positions/positions-data.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L61 [call:z.enum] stop

**pages/CopilotApp/screens/trading/odds.ts** — 0 to review, 2 identifier/key/comparison (keep)


**pages/CopilotApp/screens/trading/payoff.ts** — 37 to review, 3 identifier/key/comparison (keep)

- `C?` L117 [prop:name] Buy call
- `K-tok?` L117 [call:leg] buy
- `C?` L118 [prop:name] Sell put
- `K-tok?` L118 [call:leg] sell
- `K-tok?` L119 [call:leg] buy
- `K-tok?` L119 [call:leg] sell
- `K-tok?` L120 [call:leg] sell
- `K-tok?` L120 [call:leg] buy
- `K-tok?` L121 [call:leg] sell
- `K-tok?` L121 [call:leg] buy
- `K-tok?` L122 [call:leg] buy
- `K-tok?` L122 [call:leg] sell
- `K-tok?` L122 [call:leg] buy
- `C?` L125 [prop:name] Buy put
- `K-tok?` L125 [call:leg] buy
- `C?` L126 [prop:name] Sell call
- `K-tok?` L126 [call:leg] sell
- `K-tok?` L127 [call:leg] buy
- `K-tok?` L127 [call:leg] sell
- `K-tok?` L128 [call:leg] sell
- `K-tok?` L128 [call:leg] buy
- `K-tok?` L131 [call:leg] sell
- `K-tok?` L131 [call:leg] sell
- `K-tok?` L132 [call:leg] sell
- `K-tok?` L132 [call:leg] sell
- `K-tok?` L133 [call:leg] sell
- `K-tok?` L133 [call:leg] buy
- `K-tok?` L133 [call:leg] sell
- `K-tok?` L133 [call:leg] buy
- `K-tok?` L134 [call:leg] sell
- `K-tok?` L134 [call:leg] sell
- `K-tok?` L134 [call:leg] buy
- `K-tok?` L134 [call:leg] buy
- `K-tok?` L137 [call:leg] buy
- `K-tok?` L137 [call:leg] buy
- `K-tok?` L138 [call:leg] buy
- `K-tok?` L138 [call:leg] buy

**pages/CopilotApp/screens/trading/queries.ts** — 2 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L223 [prop:path] /api/positional/picks
- `C?` L234 [call:drift] positional.picks: no picks list

**pages/CopilotApp/screens/tradingdesk/CandleChart.tsx** — 9 to review, 0 identifier/key/comparison (keep)

- `C?` L121 [prop:target] Target
- `C?` L121 [prop:entry] Entry
- `C?` L121 [prop:stop] Stop
- `C?` L122 [prop:target] Target
- `C?` L122 [prop:entry] Buy above
- `C?` L122 [prop:stop] Exit
- `K-tok?` L208 [prop:key] target
- `K-tok?` L209 [prop:key] entry
- `K-tok?` L210 [prop:key] stop

**pages/CopilotApp/screens/tradingdesk/ChartTab.tsx** — 37 to review, 3 identifier/key/comparison (keep)

- `C?` L147 [attr:title] The scanner’s target, entry and stop
- `C?` L259 [attr:body] The data platform has no adjusted end-of-day bars for this symbol. Pick a stock from the AI scanner.
- `C?` L286 [jsx] · last bar ${…} from Kite (${…}), not yet in the adjusted series; the lines and indicators stop at the adjusted session
- `C?` L657 [jsx] Exit if it falls to
- `C?` L657 [jsx] below the buy level
- `C?` L658 [jsx] Stop
- `C?` L658 [jsx] below the entry
- `C?` L661 [prop:text] — No entry with a stop below it on this setup.
- `C?` L730 [prop:s] Needs a target and a stop
- `C?` L761 [jsx] The scanner didn’t load, so there is no trigger, stop or target for ${…}. The chart and indicators still show from its daily bars.
- `C?` L762 [jsx] ${…} did not pass the end-of-day scanner’s rules${…}, so it has no trigger, stop or target. The chart and indicators still show from its daily bars.
- `C?` L920 [prop:text] A ${…} opening gap on ${…} is larger than the ${…} stop distance: a stop may fill well below its price.
- `K-tok?` L922 [prop:key] past-target
- `C?` L922 [prop:text] The last close ${…} is already at or above the target ${…}.
- `K-tok?` L923 [prop:key] past-stop
- `C?` L923 [prop:text] The last close ${…} is at or below the stop ${…}.
- `C?` L940 [prop:plain] Is it easy to buy and sell?
- `C?` L941 [prop:trader] Hypothetical entry, stop and target
- `C?` L941 [prop:plain] Possible buy, exit and target prices
- `C?` L1045 [attr:why] Only the scanner’s ideas with targets carry a holding window.
- `C?` L1188 [attr:k] Buy above
- `C?` L1188 [attr:k] Entry
- `C?` L1188 [attr:why] No entry.
- `C?` L1189 [attr:k] Exit if wrong
- `C?` L1189 [attr:k] Stop
- `C?` L1190 [attr:why] No stop.
- `C?` L1190 [attr:why] The 20-session low, closer than the ATR stop.
- `C?` L1190 [attr:why] ${…} × ATR(${…}) below the entry.
- `C?` L1191 [attr:k] Target
- `C?` L1192 [attr:why] Only the scanner’s ideas with targets carry one.
- `C?` L1192 [attr:why] No target.
- `C?` L1192 [attr:why] Entry plus ${…} × the risk.
- `C?` L1236 [attr:why] Every row checks the sessions after the scan day; no exit rule is simulated.
- `C?` L1237 [attr:why] Not stored: the record keeps each scan’s best and worst move (MFE / MAE), not a realised exit return.
- `C?` L1269 [jsx] Cr a day · a gap larger than the stop distance · price past the target or stop · profit down year on year · promoter pledge ≥
- `C?` L1316 [prop:levels] ${…}Entry ${…} · stop ${…} · target ${…}
- `C?` L1407 [attr:title] Pick a stock to chart

**pages/CopilotApp/screens/tradingdesk/CopilotDock.tsx** — 5 to review, 2 identifier/key/comparison (keep)

- `C?` L132 [jsx] You stopped this answer.
- `C?` L238 [jsx] Answers come from the same data the desk shows, with sources. The Copilot explains evidence and risk; it does not tell you to buy or sell, and it cannot place o
- `C?` L268 [attr:aria-label] Stop the answer
- `C?` L300 [jsx] Suggested questions
- `C?` L317 [jsx] For education and research only. Not a buy or sell recommendation.

**pages/CopilotApp/screens/tradingdesk/EvidenceValidationPanel.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L102 [jsx] the quarterly disclosure became public? This is the one finished, pre-registered study behind this desk's smart-money evidence — not a score, not a ranking, and

**pages/CopilotApp/screens/tradingdesk/FnoBuilder.tsx** — 43 to review, 7 identifier/key/comparison (keep)

- `C?` L40 [prop:name] Buy Call
- `K-tok?` L40 [prop:s] buy
- `C?` L41 [prop:name] Sell Put
- `K-tok?` L41 [prop:s] sell
- `K-tok?` L42 [prop:s] buy
- `K-tok?` L42 [prop:s] sell
- `K-tok?` L43 [prop:s] sell
- `K-tok?` L43 [prop:s] buy
- `C?` L44 [prop:name] Buy Put
- `K-tok?` L44 [prop:s] buy
- `C?` L45 [prop:name] Sell Call
- `K-tok?` L45 [prop:s] sell
- `K-tok?` L46 [prop:s] buy
- `K-tok?` L46 [prop:s] sell
- `K-tok?` L47 [prop:s] sell
- `K-tok?` L47 [prop:s] buy
- `K-tok?` L48 [prop:s] sell
- `K-tok?` L48 [prop:s] sell
- `K-tok?` L48 [prop:s] buy
- `K-tok?` L48 [prop:s] buy
- `K-tok?` L49 [prop:s] sell
- `K-tok?` L49 [prop:s] buy
- `K-tok?` L49 [prop:s] sell
- `K-tok?` L49 [prop:s] buy
- `K-tok?` L50 [prop:s] buy
- `K-tok?` L50 [prop:s] buy
- `K-tok?` L51 [prop:s] buy
- `K-tok?` L51 [prop:s] buy
- `K-tok?` L52 [prop:s] buy
- `K-tok?` L52 [prop:s] sell
- `K-tok?` L52 [prop:s] buy
- `C?` L150 [jsx] Charges for the entry orders:
- `C?` L214 [return] Pick a structure to load its trades.
- `C?` L278 [jsx] Suggested by the
- `C?` L279 [jsx] No trades yet. Pick a structure below, or add a trade.
- `C?` L283 [attr:aria-label] Buy
- `C?` L283 [attr:aria-label] Sell
- `K-tok?` L283 [prop:side] sell
- `K-tok?` L283 [prop:side] buy
- `K-tok?` L284 [jsx] BUY
- `K-tok?` L284 [jsx] SELL
- `K-tok?` L302 [prop:side] buy
- `C?` L321 [jsx] Pick a structure to load it. A view is your own; no structure is shown as better than another. The shapes are illustrations.

**pages/CopilotApp/screens/tradingdesk/FnoCandidates.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L186 [jsx] This list orders stocks for you to look at. It is not a recommendation and not a forecast. When the ranking was back-tested over a year it showed no skill beyon

**pages/CopilotApp/screens/tradingdesk/FnoCompare.tsx** — 3 to review, 2 identifier/key/comparison (keep)

- `K-tok?` L112 [call:head] entry
- `C?` L112 [call:head] Entry (net)
- `K-tok?` L120 [call:cell] entry

**pages/CopilotApp/screens/tradingdesk/FnoLevels.tsx** — 24 to review, 7 identifier/key/comparison (keep)

- `C?` L96 [jsx] Estimated entry, stop-loss and targets
- `C?` L109 [attr:k] Entry · net credit
- `C?` L109 [attr:k] Entry · net debit
- `C?` L110 [attr:k] Stop-loss (structure value)
- `C?` L111 [attr:k] Target 1 (structure value)
- `C?` L112 [attr:k] Target 2 (structure value)
- `C?` L114 [attr:sub] structure value if both legs expire worthless: the whole debit is lost. It is a boundary, not the stop-loss.
- `C?` L121 [jsx] Entry
- `C?` L124 [jsx] Entry
- `C?` L124 [jsx] · thesis stop
- `C?` L124 [jsx] · target 1
- `C?` L124 [jsx] · target 2
- `C?` L127 [jsx] (model estimate for the data date), so the stop and targets here are the same ones as in A. They are not option premium levels.
- `C?` L131 [jsx] The trigger (a touch, a close or another rule) is not set: Nivesh does not monitor the underlying or place exits, so these are reference levels.
- `C?` L136 [PropertyAccessExpression] Stop
- `C?` L139 [PropertyAccessExpression] Strategy stop
- `C?` L140 [PropertyAccessExpression] Thesis stop
- `C?` L142 [PropertyAccessExpression] Emergency risk stop
- `C?` L160 [PropertyAccessExpression] Entry
- `C?` L165 [jsx] Buy
- `C?` L165 [jsx] Sell
- `C?` L175 [jsx] Entry prices are end-of-day closes. A current executable price per leg needs live option quotes, which are not available here; the structure’s value is a model 
- `C?` L206 [jsx] . The plotted net loss adds the entry costs (
- `C?` L206 [jsx] is the worst net loss with entry and exit costs on every leg (round trip

**pages/CopilotApp/screens/tradingdesk/FnoStrategies.tsx** — 21 to review, 1 identifier/key/comparison (keep)

- `C?` L62 [var:NO_TRADE] No trade suggested
- `C?` L188 [prop:text] No entry price for this idea: ${…}${…}.
- `C?` L197 [prop:k] Entry · settle
- `C?` L198 [prop:k] Exit if wrong
- `C?` L198 [prop:k] Stop
- `C?` L199 [prop:k] Target
- `C?` L202 [prop:text] Stop at ${…}${…}, target at ${…}${…}.${…}
- `C?` L225 [prop:text] Neutral build-up, but the expected move (±${…}) reaches past a wall (${…} – ${…}), so a range idea is not suggested.
- `C?` L305 [prop:text] The bhavcopy sent no price for the stock, so there is no entry.
- `C?` L305 [prop:blocked] No entry price.
- `C?` L309 [prop:k] Buy near
- `C?` L309 [prop:k] Entry · close
- `C?` L310 [prop:k] Exit if wrong
- `C?` L310 [prop:k] Stop
- `C?` L311 [prop:k] Target
- `C?` L330 [prop:text] One lot’s worth of shares, held for delivery. Stop at ${…}, target at ${…}. Recorded as a paper trade only, marked against end-of-day closes.
- `C?` L337 [return] The build-up scan has no index-futures row for this index on the latest day, so the rules suggest nothing.
- `C?` L338 [return] This stock has no build-up reading on the latest day, so the rules suggest nothing.
- `C?` L392 [var:note] Simulated: ${…} shares at ${…}, stop ${…}, target ${…}. No order is placed; it is marked against end-of-day closes.
- `C?` L460 [call:out.push] Walls: the most put open interest is at ${…} (stops for rising ideas) and the most call open interest at ${…} (targets).
- `C?` L595 [jsx] Rules-based paper ideas from end-of-day data, for learning — not a recommendation to buy or sell.

**pages/CopilotApp/screens/tradingdesk/FnoTab.tsx** — 2 to review, 1 identifier/key/comparison (keep)

- `C?` L267 [jsx] ”. Pick one:
- `C?` L370 [attr:aria-label] Pick an expiry date

**pages/CopilotApp/screens/tradingdesk/IdeaLevels.tsx** — 20 to review, 7 identifier/key/comparison (keep)

- `C?` L66 [jsx] Entry, stop and target: — (the scanner gave no entry with a stop below it on this scan)
- `C?` L73 [attr:k] Entry
- `C?` L74 [attr:k] Stop
- `C?` L75 [attr:k] Target
- `C?` L78 [jsx] Hypothetical levels from the AI scanner’s rules, not advice. A stop is a level, not a guaranteed price: a gap can fill worse.
- `C?` L90 [jsx] Working out the entry, stop and targets…
- `C?` L91 [jsx] Entry, stop and targets: the levels did not load just now, so a paper trade records none.
- `C?` L93 [jsx] No entry, stop or targets for this structure:
- `C?` L101 [attr:title] Entry, stop and targets
- `C?` L103 [attr:k] Entry · net credit
- `C?` L103 [attr:k] Entry · net debit
- `C?` L104 [attr:k] Stop
- `C?` L105 [attr:k] Target 1
- `C?` L106 [attr:k] Target 2
- `C?` L114 [jsx] lost at the stop,
- `C?` L115 [jsx] gained at target 1
- `C?` L115 [jsx] , ${…} at target 2
- `C?` L116 [jsx] Hypothetical, not advice; a stop is a level, not a guaranteed price.
- `C?` L167 [jsx] Entry, stop and targets: not stored with this day’s list (they are not worked out again on later prices).
- `C?` L169 [jsx] Entry, stop and targets:

**pages/CopilotApp/screens/tradingdesk/IntelTab.tsx** — 8 to review, 2 identifier/key/comparison (keep)

- `C?` L106 [prop:buyback] buying back its own shares
- `C?` L107 [prop:qip] raising money by selling new shares to institutions
- `C?` L118 [prop:trader] A disclosure under SEBI's takeover or insider-trading rules, a pledge or a shareholding change: who is buying, selling or pledging shares.
- `C?` L119 [prop:plain] A large owner or an insider bought, sold or pledged shares, and had to tell the exchange.
- `C?` L153 [return] Net buying (+) or selling (−) in the cash market by foreign (FII) and domestic (DII) institutions this session, as NSE reported it provisionally. One session sa
- `C?` L163 [return] A large investor bought or sold a big lot of this company’s shares. The exchange publishes such deals after the market closes.
- `C?` L164 [return] A bulk deal is one in which a client traded more than 0.5% of the company’s listed shares in a day; a block deal is a large trade done in the exchange’s separat
- `C?` L494 [jsx] · labels from the announcement classifier, not checked against the price and not a buy or sell direction.

**pages/CopilotApp/screens/tradingdesk/OwnershipReactionPanel.tsx** — 1 to review, 1 identifier/key/comparison (keep)

- `C?` L330 [attr:title] This panel describes a quarter that has already finished. It is not predictive and not a recommendation.

**pages/CopilotApp/screens/tradingdesk/PaperDesk.tsx** — 70 to review, 7 identifier/key/comparison (keep)

- `C?` L91 [prop:label] Stop
- `C?` L91 [prop:investor] Exit if wrong
- `C?` L92 [prop:label] Trailing stop
- `C?` L92 [prop:investor] Locked-in exit
- `C?` L93 [prop:label] Target
- `C?` L93 [prop:investor] Exit if right
- `C?` L94 [prop:label] Time exit
- `C?` L95 [prop:label] Trend exit
- `C?` L98 [prop:label] Entry not reached
- `C?` L98 [prop:investor] Never bought
- `C?` L110 [prop:initial] initial stop
- `C?` L115 [prop:investor] Bought when added
- `C?` L116 [prop:trader] Entry reached
- `C?` L116 [prop:investor] Bought
- `C?` L117 [prop:trader] Waiting for entry
- `C?` L117 [prop:investor] Waiting to buy
- `C?` L118 [prop:trader] Entry not reached
- `C?` L118 [prop:investor] Never bought
- `C?` L122 [prop:investor] Buy now
- `C?` L123 [prop:investor] Buy above
- `C?` L124 [prop:investor] Buy on a dip to
- `C?` L130 [prop:entry] Buy price
- `C?` L130 [prop:stop] Exit if wrong
- `C?` L130 [prop:target] Exit if right
- `C?` L131 [prop:rule] When it buys
- `C?` L133 [prop:entry] Entry
- `C?` L133 [prop:stop] Stop
- `C?` L133 [prop:target] Target
- `C?` L134 [prop:rule] Entry rule
- `C?` L165 [PropertyAccessExpression] no target
- `C?` L173 [jsx] at entry
- `C?` L186 [var:exitRules] None — stop, target and time only
- `C?` L190 [var:rows] Entry
- `K-tok?` L190 [var:rows] entry
- `C?` L191 [var:rows] Exit rule
- `K-tok?` L191 [var:rows] exit-rule
- `C?` L192 [var:rows] Research exit rules
- `K-tok?` L192 [var:rows] exit-rules
- `C?` L193 [var:rows] Stop history
- `K-tok?` L193 [var:rows] stop-history
- `C?` L195 [jsx] ${…} at the target ·
- `C?` L195 [jsx] ${…} at the stop
- `C?` L199 [var:rows] Exit
- `K-tok?` L199 [var:rows] exit
- `C?` L202 [jsx] · exits ${…}
- `C?` L259 [var:rows] Exit rule
- `K-tok?` L259 [var:rows] exit-rule
- `C?` L262 [jsx] a unit · stop
- `C?` L262 [jsx] · T1
- `C?` L262 [jsx] · T2
- `C?` L262 [jsx] (the cost to buy it back)
- `C?` L262 [jsx] (what it would sell for)
- `C?` L265 [var:rows] Exit
- `K-tok?` L265 [var:rows] exit
- `C?` L266 [jsx] at entry · ${…} at the marks
- `C?` L304 [jsx] Entry from
- `C?` L331 [jsx] The stored legs or signal no longer match what was saved at entry. Treat this record as unreliable.
- `C?` L464 [prop:sub] ${…} waiting for the entry
- `K-tok?` L484 [prop:key] entry
- `K-tok?` L485 [prop:key] stop
- `K-tok?` L486 [prop:key] target
- `K-tok?` L518 [prop:key] entry
- `K-tok?` L519 [prop:key] exit
- `C?` L519 [prop:header] Exit
- `C?` L521 [prop:header] Exit reason
- `C?` L572 [jsx] paper trade? Its entry has not been reached, so there is no position and no P&amp;L. It is simulated: no order is placed.
- `C?` L613 [jsx] Each leg is marked on its own contract: a future at its settle price, an option at its settle (else close), on the NSE F&amp;O bhavcopy, end of day. A strategy 
- `C?` L620 [jsx] Marks and exits use end-of-day daily bars
- `C?` L620 [jsx] . A session whose low reaches the stop closes the trade at the stop; one whose high reaches the target closes it at the target; one that reaches both closes it 
- `C?` L624 [jsx] MFE and MAE are the best and worst points reached from the fill through the exit session.

**pages/CopilotApp/screens/tradingdesk/PlanPaperTrade.tsx** — 5 to review, 0 identifier/key/comparison (keep)

- `C?` L26 [prop:at_once] it enters at once, at the entry price
- `C?` L27 [prop:break_above] it enters only when a later day trades up to the entry
- `C?` L28 [prop:pullback_to] it enters only when a later day dips back to the entry
- `C?` L69 [jsx] · exit if wrong
- `C?` L69 [jsx] · targets

**pages/CopilotApp/screens/tradingdesk/PortfolioTab.tsx** — 12 to review, 2 identifier/key/comparison (keep)

- `C?` L582 [prop:investor] How easy to sell
- `C?` L808 [var:liqRule] Average traded value over 20 sessions and the days to sell each position at 10% of the average daily volume.
- `C?` L816 [jsx] Slowest to sell:
- `C?` L816 [jsx] Days to sell not worked out
- `C?` L822 [prop:note] ${…} days to sell this position at 10% of the average daily volume
- `C?` L1231 [jsx] Entry
- `C?` L1231 [jsx] · Stop
- `C?` L1231 [jsx] · Target
- `K-tok?` L1253 [var:reason] target
- `K-tok?` L1253 [var:reason] stop
- `C?` L1253 [var:reason] trailing stop
- `C?` L1278 [jsx] Your desk paper trades. P is not stored with a trade, so it shows “—”. Outcome = exit vs entry; R = (exit − entry) ÷ (entry − stop). Close trades and manage ale

**pages/CopilotApp/screens/tradingdesk/ReversalPanel.tsx** — 4 to review, 0 identifier/key/comparison (keep)

- `C?` L63 [prop:valuation_risk] Valuation & downside risk
- `C?` L126 [call:h] Entry trigger (hypothetical)
- `C?` L155 [jsx] · target
- `C?` L297 [jsx] ). It ranks setups; it is not a probability and has not been validated out of sample. A part that could not be measured says Unknown and is left out of the tota

**pages/CopilotApp/screens/tradingdesk/RiskControls.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L589 [jsx] A share entry’s estimated risk is its loss at the stop plus round-trip costs
- `C?` L637 [jsx] Stop new paper positions with the kill switch or a trading halt, see the limits the policy gate applies, and every decision and change on record.

**pages/CopilotApp/screens/tradingdesk/RiskDesk.tsx** — 78 to review, 15 identifier/key/comparison (keep)

- `C?` L75 [var:STOP_NOTE] A stop does not guarantee the exit price: a gap or thin trading can fill the exit beyond the stop, so the loss can be larger than shown.
- `K-tok?` L342 [call:pos] entry
- `C?` L342 [call:pos] an entry price
- `K-tok?` L343 [call:pos] stop
- `C?` L343 [call:pos] a stop price
- `K-tok?` L344 [call:pos] target
- `C?` L344 [call:pos] the target
- `K-tok?` L449 [attr:k] entry
- `C?` L449 [attr:label] Buy at ₹
- `C?` L449 [attr:label] Entry ₹
- `K-tok?` L449 [call:st.set] entry
- `K-tok?` L449 [call:fieldProblem] entry
- `K-tok?` L450 [attr:k] stop
- `C?` L450 [attr:label] Exit if wrong ₹
- `C?` L450 [attr:label] Stop ₹
- `K-tok?` L450 [call:st.set] stop
- `K-tok?` L450 [call:fieldProblem] stop
- `K-tok?` L451 [attr:k] target
- `C?` L451 [attr:label] Target ₹
- `K-tok?` L451 [call:st.set] target
- `K-tok?` L451 [call:fieldProblem] target
- `C?` L502 [attr:k] Downside a share (entry − stop)
- `C?` L503 [attr:k] Upside a share (target − entry)
- `C?` L503 [attr:sub] No target entered.
- `C?` L507 [attr:v] ${…} at the stop · ${…}
- `C?` L507 [attr:v] ${…} at the target
- `C?` L507 [attr:v] no target
- `C?` L509 [attr:sub] At the stop: ${…}. ₹${…} brokerage a side is a desk assumption, not a broker's tariff; ${…}% slippage a side also covers the spread; DP charges and income tax a
- `C?` L511 [attr:k] Loss at the stop
- `C?` L512 [attr:k] Profit at the target
- `C?` L512 [attr:sub] No target entered.
- `C?` L534 [var:where] · below the stop
- `C?` L534 [var:where] · above the target
- `C?` L534 [var:where] · above the entry
- `C?` L539 [attr:title] Risk: entry to stop
- `C?` L540 [attr:title] Reward: entry to target
- `C?` L558 [jsx] Exit if wrong
- `C?` L558 [jsx] Stop
- `C?` L559 [jsx] Buy above
- `C?` L559 [jsx] Entry
- `C?` L561 [jsx] Target ${…}
- `C?` L561 [jsx] No target
- `K-tok?` L580 [jsx] exit
- `K-tok?` L580 [jsx] stop
- `C?` L581 [prop:text] — Needs an entry with a stop below it, a capital and a risk per trade.
- `C?` L587 [jsx] of your portfolio after the buy (
- `C?` L594 [jsx] of capital); the risk budget alone would buy
- `K-tok?` L610 [jsx] exit
- `K-tok?` L610 [jsx] stop
- `C?` L610 [jsx] buy level
- `K-tok?` L610 [jsx] entry
- `C?` L688 [jsx] Sizing needs an entry with a stop below it, a capital and a risk per trade; see the problems under “Edit the scenario”.
- `K-tok?` L705 [attr:s] exit
- `K-tok?` L705 [attr:s] stop
- `C?` L707 [attr:k] At target
- `C?` L709 [attr:s] at the target, after costs (${…} before)
- `C?` L709 [attr:s] No target on this scenario
- `C?` L715 [jsx] a share (entry − stop), capped at
- `C?` L751 [call:row] ${…} after the buy. Direct stocks only; funds are not looked through.
- `C?` L768 [call:row] Share of your money in it after buying
- `C?` L772 [call:row] ${…} at the stop · ${…} at the target
- `C?` L868 [jsx] This setup has no entry with a stop below it, so there is no range to draw. Enter levels under “Edit the scenario” to size one.
- `C?` L868 [jsx] Not on today’s scanner — no levels. The scanner suggests an entry, stop and target only for stocks that pass its end-of-day rules, and nothing is made up for th
- `C?` L873 [jsx] : entry = last close; stop =
- `C?` L873 [jsx] ) below it, or the 20-session low when that is closer; target = entry +
- `C?` L877 [jsx] Reward / risk needs a target; only the scanner’s ideas with a target carry one.
- `C?` L892 [jsx] The chance is the model’s estimate that the next trading day’s high gets 5% above the last close — one day only. A win rate would count how often whole trades l
- `C?` L893 [jsx] Move probability is the move-odds model’s estimate that the next session’s high reaches the last close plus 5%, one session only. A trade win rate would count h
- `C?` L906 [jsx] How much to buy
- `C?` L968 [jsx] Exit if wrong
- `C?` L968 [jsx] Stop
- `C?` L969 [jsx] Buy above
- `C?` L969 [jsx] Entry
- `C?` L970 [jsx] Target ${…}
- `C?` L970 [jsx] No target
- `C?` L973 [jsx] No entry with a stop below it on this setup.
- `K-tok?` L1052 [var:alertWhy] entry
- `C?` L1053 [var:alertWhy] Needs a trigger or an entry level; this stock has neither on today’s scanner.

**pages/CopilotApp/screens/tradingdesk/RiskReduce.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L36 [jsx] Same entry, stop and target
- `C?` L36 [jsx] ; ${…} at the planned entry

**pages/CopilotApp/screens/tradingdesk/ScannerTab.tsx** — 15 to review, 4 identifier/key/comparison (keep)

- `C?` L704 [jsx] Entry
- `C?` L753 [jsx] Paper trade needs a scanner setup with an entry and a stop below it;
- `C?` L779 [jsx] Hypothetical, at the setup’s levels: entry
- `C?` L779 [jsx] ), stop
- `C?` L779 [jsx] , target ${…}
- `C?` L779 [jsx] , no target
- `C?` L836 [prop:target] To target
- `K-tok?` L840 [var:TABLE_COLUMNS] target
- `K-tok?` L999 [PropertyAccessExpression] target
- `C?` L1165 [prop:watchlist] The setup watchlist did not answer, so only the scanner’s ideas with targets are listed.
- `C?` L1166 [prop:picks] The scanner’s target list did not answer, so only the setup watchlist is listed and no stock has a target.
- `C?` L1303 [attr:title] The scanner didn’t load: neither the setup watchlist nor the scanner’s target list answered
- `C?` L1372 [jsx] The scanner’s own setups (GET /api/positional/watchlist, /picks) didn’t load; only the universe categories are listed.
- `C?` L1437 [jsx] Entry, stop and target are hypothetical and never sent to a broker.
- `C?` L1439 [jsx] Sources: NSE end-of-day scanner (setup watchlist and target list) · NIDP feature store (scan universe) · move-odds model (latest estimates).

**pages/CopilotApp/screens/tradingdesk/ScannerTop10.tsx** — 9 to review, 0 identifier/key/comparison (keep)

- `C?` L110 [jsx] has no trade plan on this scan (no entry with a stop below it). Open the plan to see why.
- `C?` L126 [jsx] A paper trade needs the scanner’s entry and a stop below it;
- `C?` L152 [jsx] At the scanner’s levels: entry
- `C?` L152 [jsx] ), stop
- `C?` L152 [jsx] , target ${…}
- `C?` L152 [jsx] , no target
- `C?` L297 [jsx] Ideas for review, not recommendations; entry, stop and target are the plan’s, and nothing is sent to a broker.
- `C?` L524 [var:IDEAS_FOOTER] Ideas, not recommendations. The rank orders ideas; our test found no measurable ranking skill.
- `C?` L542 [jsx] End of day · ideas for review, not recommendations

**pages/CopilotApp/screens/tradingdesk/SmartMoneyTab.tsx** — 11 to review, 0 identifier/key/comparison (keep)

- `C?` L96 [jsx] net bought
- `C?` L96 [jsx] net sold
- `C?` L154 [var:word] more buying than
- `C?` L154 [var:word] less buying than
- `C?` L407 [jsx] net bought
- `C?` L407 [jsx] net sold
- `C?` L894 [jsx] delta, never a market-value delta, so a price move alone cannot read as buying. It is still an estimate: it assumes every change traded at the month’s VWAP, and
- `C?` L925 [jsx] . A proxy move on its own is never called accumulation: delivery and volume do not disclose who bought.
- `C?` L1037 [attr:title] Who is buying and selling
- `C?` L1054 [attr:sub] What fund houses actually filed they bought or sold, plus the deals the exchanges published. It is a record of who moved, not advice to follow them.
- `C?` L1081 [jsx] Smart money is evidence, not a buy signal.

**pages/CopilotApp/screens/tradingdesk/chart-data.ts** — 4 to review, 0 identifier/key/comparison (keep)

- `C?` L194 [return] Watchlist ${…} · targets ${…}
- `K-tok?` L564 [call:put] entry
- `K-tok?` L565 [call:put] stop
- `K-tok?` L566 [call:put] t1

**pages/CopilotApp/screens/tradingdesk/chartink/ChartinkPicks.tsx** — 8 to review, 41 identifier/key/comparison (keep)

- `K-tok?` L162 [call:fact] ck-pick-st-maxloss
- `K-tok?` L163 [call:fact] ck-pick-st-capital
- `K-tok?` L164 [call:fact] ck-pick-st-rr
- `K-tok?` L165 [call:fact] ck-pick-st-maxprofit
- `K-tok?` L166 [call:fact] ck-pick-st-breakeven
- `K-tok?` L167 [call:fact] ck-pick-st-sizing
- `K-tok?` L168 [call:fact] ck-pick-st-margin
- `K-tok?` L317 [BindingElement] ck-picks

**pages/CopilotApp/screens/tradingdesk/chartink/ChartinkSettings.tsx** — 0 to review, 1 identifier/key/comparison (keep)


**pages/CopilotApp/screens/tradingdesk/chartink/picks-contract.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L44 [var:OUTCOMES] pick

**pages/CopilotApp/screens/tradingdesk/chartink/picks-data.ts** — 3 to review, 1 identifier/key/comparison (keep)

- `K-tok?` L16 [var:CHARTINK_PICKS_PATH] /api/desk/chartink/picks
- `K-tok?` L22 [prop:queryKey] picks
- `C?` L31 [new:ApiError] The Chartink best picks were not in the expected form.

**pages/CopilotApp/screens/tradingdesk/decision/CarryTag.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L41 [return] entry —
- `C?` L43 [return] entry ${…}
- `C?` L46 [arrow] ${…} · stop ${…} · target ${…}

**pages/CopilotApp/screens/tradingdesk/decision/DecisionCard.tsx** — 26 to review, 8 identifier/key/comparison (keep)

- `C?` L33 [var:CARD_CAVEAT] An idea to review, not a recommendation. The score only puts ideas in order; it does not predict a return. The prices come from fixed rules, and an exit price i
- `C?` L75 [return] a normal day's price swing below the entry, so ordinary ups and downs do not trigger it
- `C?` L282 [prop:volume] Buying interest (volume)
- `C?` L283 [prop:liquidity] Ease of buying and selling
- `C?` L327 [jsx] Sell
- `C?` L327 [jsx] Buy
- `C?` L331 [attr:k] Exit at
- `C?` L335 [attr:title] Targets (where to take profit, not forecasts)
- `C?` L337 [attr:k] Target ${…}
- `C?` L338 [attr:why] the plan has no profit target
- `C?` L342 [jsx] loss at the exit
- `C?` L383 [jsx] exit at
- `C?` L386 [jsx] the exit price moves up as the price rises
- `C?` L387 [attr:k] Trend exit
- `C?` L390 [jsx] exit if it falls to ${…}; take profit at ${…}, then ${…}
- `C?` L391 [attr:why] no option exit levels were worked out
- `C?` L397 [attr:k] Stop method
- `C?` L399 [attr:k] Premium stop
- `C?` L400 [attr:k] Entry order
- `C?` L401 [attr:k] Targets in R
- `C?` L409 [jsx] · stop ${…}, costs ${…}, gap stress ${…}
- `C?` L411 [attr:k] Exit rules
- `C?` L443 [attr:k] Exit if wrong
- `C?` L444 [attr:k] Targets
- `C?` L446 [attr:title] If it hits the exit: the loss, the charges and an allowance for a price gap, at your size
- `C?` L488 [jsx] (no entry with a stop on the loss side)

**pages/CopilotApp/screens/tradingdesk/decision/PlanPayoff.tsx** — 4 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L150 [prop:key] exit
- `C?` L150 [prop:label] exit if wrong ${…}
- `C?` L151 [prop:label] target ${…} ${…}
- `C?` L209 [jsx] Today&rsquo;s line is an estimate: each option is valued from the price swings its entry price implies, and real prices can differ. The expiry line is exact at 

**pages/CopilotApp/screens/tradingdesk/decision/plan-view.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L177 [prop:watch] Waiting for entry

**pages/CopilotApp/screens/tradingdesk/decision/ways-forward.tsx** — 7 to review, 0 identifier/key/comparison (keep)

- `C?` L45 [prop:options] Use a closer exit price, so less is lost if it goes wrong
- `C?` L47 [prop:why] The loss at the exit price would be more than your limit for one trade.
- `C?` L48 [prop:options] Use a closer exit price, so less is lost if it goes wrong
- `C?` L51 [prop:options] Wait for a better (lower) entry price
- `C?` L63 [prop:options] Trim a trade in this sector
- `C?` L66 [prop:options] Trim a related trade
- `C?` L89 [prop:why] The plan's prices or legs do not line up (an entry, exit or target is missing or on the wrong side).

**pages/CopilotApp/screens/tradingdesk/desk-data.ts** — 1 to review, 1 identifier/key/comparison (keep)

- `K-tok?` L414 [call:partial.push] picks

**pages/CopilotApp/screens/tradingdesk/desk-trading.ts** — 11 to review, 8 identifier/key/comparison (keep)

- `C?` L72 [prop:stop_not_below_entr] The stop must be below the entry.
- `C?` L73 [prop:target_not_above_en] The target must be above the entry.
- `C?` L91 [prop:invalid_entry_rule] The entry rule is not one the desk knows (at once, break above, pull back to).
- `C?` L92 [prop:invalid_entry_windo] The entry window must be 1 to 20 sessions, and only for an entry that waits for a level.
- `C?` L101 [prop:naked_short_put] A sold put needs a bought put of at least the same size. Naked short options are not recorded.
- `C?` L104 [prop:short_cash_not_supp] Selling shares is not supported in a strategy.
- `C?` L107 [prop:levels_not_supporte] A neutral strategy has no stop or target on the underlying.
- `C?` L116 [prop:futures_stop_requir] A structure with a futures leg needs a stop on the underlying.
- `K-tok?` L202 [var:EXIT_REASONS] stop
- `K-tok?` L202 [var:EXIT_REASONS] target
- `C?` L283 [return] ; exits after ${…} session${…} held

**pages/CopilotApp/screens/tradingdesk/fno-parts.tsx** — 5 to review, 10 identifier/key/comparison (keep)

- `C?` L418 [return] ${…} These are positions at the close, not price targets.
- `K-tok?` L528 [PropertyAccessExpression] buy
- `K-tok?` L528 [PropertyAccessExpression] sell
- `C?` L531 [attr:aria-label] Buy
- `C?` L531 [attr:aria-label] Sell

**pages/CopilotApp/screens/tradingdesk/intel-data.ts** — 4 to review, 2 identifier/key/comparison (keep)

- `K-tok?` L550 [var:verb] bought
- `K-tok?` L550 [var:verb] sold
- `C?` L636 [arrow] ${…} net bought ${…}
- `C?` L636 [arrow] ${…} net sold ${…}

**pages/CopilotApp/screens/tradingdesk/ownership-reaction-data.ts** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L111 [prop:reversal_watch] Institutions added while the price fell into the cohort's bottom quartile and the quarter closed near its 52-week low — buying into weakness. A watch item, not 
- `C?` L610 [var:OR_RETROSPECTIVE_NOT] that is co-occurrence, not cause, and not a reason to buy or sell.

**pages/CopilotApp/screens/tradingdesk/smart-money-data.ts** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L562 [var:side] net bought
- `C?` L562 [var:side] net sold

**pages/CopilotApp/screens/tradingdesk/strategy/LegTable.tsx** — 5 to review, 2 identifier/key/comparison (keep)

- `K-tok?` L56 [jsx] BUY
- `C?` L56 [jsx] LONG · BUY
- `K-tok?` L56 [jsx] SELL
- `C?` L56 [jsx] SHORT · SELL
- `C?` L66 [attr:k] Entry price

**pages/CopilotApp/screens/tradingdesk/strategy/PayoffChart.tsx** — 0 to review, 3 identifier/key/comparison (keep)


**pages/CopilotApp/screens/tradingdesk/strategy/PayoffSummary.tsx** — 2 to review, 2 identifier/key/comparison (keep)

- `C?` L66 [jsx] Entry
- `C?` L66 [jsx] · Exit at expiry (at the reference price)

**pages/CopilotApp/screens/tradingdesk/strategy/ScenarioFan.tsx** — 1 to review, 1 identifier/key/comparison (keep)

- `C?` L81 [prop:label] Exit if below

**pages/CopilotApp/screens/tradingdesk/strategy/StrategyGraphs.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L87 [attr:source] Nivesh payoff calculation from the legs' entry prices
- `C?` L107 [attr:source] Entry prices as given with each leg

**pages/CopilotApp/screens/tradingdesk/strategy/TopByRegime.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L102 [var:records] with the stop ${…} and target ${…} on ${…} from the levels shown
- `C?` L103 [var:records] with no stop or target: it closes at expiry or when you close it
- `C?` L131 [attr:title] Waiting for the levels, so the paper trade records the stop and target the row shows.

**pages/CopilotApp/screens/tradingdesk/strategy/plan-contract.ts** — 3 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L120 [call:z.enum] buy
- `K-tok?` L120 [call:z.enum] sell
- `K-tok?` L224 [call:z.enum] stop

**pages/CopilotApp/screens/tradingdesk/strategy/plan-data.ts** — 4 to review, 3 identifier/key/comparison (keep)

- `C?` L207 [return] Selling shares is not supported in a paper trade.
- `C?` L208 [return] The plan has no stop below the entry, which a share paper trade needs.
- `C?` L220 [return] The plan's stop or target is on the wrong side of the reference price for a bullish view.
- `C?` L221 [return] The plan's stop or target is on the wrong side of the reference price for a bearish view.

**pages/CopilotApp/screens/tradingdesk/strategy/strategy-contract.ts** — 2 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L20 [call:z.enum] buy
- `K-tok?` L20 [call:z.enum] sell

**pages/CopilotApp/screens/tradingdesk/strategy/top-live.ts** — 0 to review, 1 identifier/key/comparison (keep)


**pages/CopilotApp/screens/tradingdesk/strategy/trade-plan.ts** — 8 to review, 1 identifier/key/comparison (keep)

- `C?` L64 [return] premium stop ${…}
- `C?` L64 [return] premium stop
- `C?` L73 [var:entry] Entry ${…} (${…})
- `C?` L73 [var:entry] Entry ${…}
- `C?` L74 [var:stop] Stop ${…} (${…})
- `C?` L76 [PropertyAccessExpression] Targets ${…}
- `C?` L76 [PropertyAccessExpression] No target
- `C?` L85 [prop:WAIT_FOR_CONFIRMATI] waiting for its entry condition

**pages/CopilotApp/screens/tradingdesk/tabs/market-overview/MarketStrip.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L123 [jsx] The risk service blocks new paper entries while it cannot read the market state.
- `C?` L142 [jsx] . The risk service blocks new paper entries while this input is stale.

**pages/CopilotApp/screens/tradingdesk/tabs/market-overview/OverviewKpis.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L122 [jsx] Each trade’s entry, stop, P/L and exits are on Trade Desk ·

**pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/ControlsView.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L27 [var:CONTROL_RULE] Anyone can switch the kill switch or the halt on, with a reason. Either one blocks new paper entries only: open positions are untouched and nothing is cancelled
- `C?` L74 [var:title] The kill switch is on: new paper entries are blocked.
- `C?` L76 [var:title] Trading is halted: new paper entries are blocked.

**pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/DecisionLog.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L46 [PropertyAccessExpression] stop ${…}

**pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/LimitsView.tsx** — 8 to review, 6 identifier/key/comparison (keep)

- `C?` L44 [prop:words] the entry controls are unknown
- `C?` L45 [prop:words] new entries are blocked by the kill switch
- `C?` L46 [prop:words] new entries are halted
- `C?` L47 [prop:words] new entries are allowed
- `C?` L130 [jsx] Each entry reserves its estimated risk when it is allowed: the loss at the stop, plus round-trip costs and a gap stress. Closing the trade releases it.
- `C?` L218 [jsx] A new paper entry is blocked when any of its inputs is not ok. Age is counted in NSE sessions
- `C?` L276 [attr:k] Entries
- `C?` L299 [attr:title] Open risk reserved at entry

**pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/hedge-data.ts** — 5 to review, 3 identifier/key/comparison (keep)

- `C?` L31 [prop:lowest_cost] A put spread: cheaper, but protection stops at the fall you fear.
- `K-tok?` L92 [prop:side] sell
- `K-tok?` L92 [prop:side] buy
- `C?` L148 [return] Buy ${…}${…} put, sell the ${…} put
- `C?` L149 [return] Buy ${…}${…} put

**pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/parts.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L16 [var:PAPER_ONLY] Paper risk only: these limits and controls govern paper entries. Nothing is sent to a broker.

**pages/CopilotApp/screens/tradingdesk/tabs/risk-desk/risk-desk-data.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L207 [prop:label] Exit check

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/BookViews.tsx** — 22 to review, 2 identifier/key/comparison (keep)

- `C?` L24 [return] End-of-day prices could not be read just now, so open trades have no mark and no exit was checked on this read. Nothing is made up.
- `C?` L34 [jsx] Marks and exits use end-of-day daily bars
- `C?` L34 [jsx] . A session whose low reaches the stop closes the trade at the stop (at the open when it gaps through); one whose high reaches the target closes it at the targe
- `K-tok?` L51 [call:plural] entry
- `K-tok?` L51 [call:plural] entries
- `C?` L55 [attr:fallback] waiting for entry
- `C?` L56 [prop:header] Entry rule · validity
- `K-tok?` L57 [prop:key] stop
- `C?` L57 [prop:header] Stop
- `C?` L58 [prop:header] Target
- `K-tok?` L71 [prop:key] stop
- `C?` L71 [prop:header] Stop
- `C?` L72 [prop:header] Target
- `C?` L96 [jsx] Pending entries ·
- `K-tok?` L139 [prop:key] exit
- `C?` L139 [prop:header] Exit
- `K-tok?` L146 [prop:key] entry
- `C?` L146 [prop:header] Entry
- `C?` L147 [prop:header] Exit price
- `C?` L154 [jsx] Recent exits
- `C?` L154 [attr:note] click a row for its journal · ⚑ an exit flag
- `C?` L175 [attr:body] A trade closes at its stop, its target, its time exit or when you close it; its journal stays here.

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/HeaderStrip.tsx** — 6 to review, 4 identifier/key/comparison (keep)

- `C?` L36 [prop:text] Exits checked after the ${…} close
- `C?` L36 [prop:text] The evening exit check is up to date.
- `C?` L37 [prop:text] The evening exit check is running now
- `C?` L38 [prop:text] Exit check late: ${…}
- `C?` L40 [prop:text] Exit check missed: ${…}${…}
- `C?` L40 [prop:text] the evening exit check did not run.

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/Journal.tsx** — 39 to review, 7 identifier/key/comparison (keep)

- `C?` L33 [prop:reached] Entry reached
- `C?` L33 [prop:waiting] Waiting for entry
- `C?` L33 [prop:not_reached] Entry not reached
- `K-tok?` L106 [prop:id] entry
- `C?` L106 [prop:side] Buy
- `C?` L109 [prop:note] entry not reached
- `C?` L109 [prop:note] waiting for the entry
- `K-tok?` L113 [prop:id] exit
- `C?` L113 [prop:side] Sell
- `C?` L127 [jsx] Entry
- `C?` L127 [jsx] Exit
- `C?` L171 [jsx] Open: the exit side is estimated at the last mark.
- `C?` L182 [jsx] None: no gap through a level and no session that touched both the stop and the target.
- `C?` L201 [jsx] The initial stop
- `C?` L201 [jsx] ; no stop history recorded for this trade.
- `C?` L206 [jsx] at entry
- `C?` L206 [jsx] initial stop
- `C?` L255 [attr:title] Exit flags
- `C?` L256 [attr:title] Stop history
- `C?` L259 [attr:rows] Entry rule
- `C?` L260 [attr:rows] Entry
- `K-tok?` L260 [attr:rows] entry
- `C?` L261 [attr:rows] Exit rule
- `C?` L261 [attr:rows] stop ${…}, target ${…}${…}; a session touching both takes the stop
- `K-tok?` L261 [attr:rows] exit-rule
- `C?` L262 [attr:rows] Exit
- `K-tok?` L262 [attr:rows] exit
- `C?` L263 [attr:rows] Research exit rules
- `C?` L263 [attr:rows] None: stop, target and time only
- `K-tok?` L263 [attr:rows] exit-rules
- `C?` L266 [attr:rows] · exits ${…}
- `C?` L283 [attr:title] Exit flags
- `C?` L286 [attr:rows] Exit rule
- `C?` L286 [PropertyAccessExpression] stop ${…} ${…}
- `C?` L286 [PropertyAccessExpression] target ${…}
- `K-tok?` L286 [attr:rows] exit-rule
- `C?` L287 [attr:rows] Exit
- `K-tok?` L287 [attr:rows] exit
- `C?` L324 [attr:what] Cancel the ${…} paper trade? Its entry has not been reached, so there is no position and no P/L.

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/StructureCard.tsx** — 4 to review, 3 identifier/key/comparison (keep)

- `C?` L38 [jsx] Entry
- `C?` L38 [jsx] Exit mark
- `C?` L105 [jsx] From the payoff engine${…} on the recorded legs at their entry premiums${…}.
- `C?` L140 [jsx] at entry

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/TradeDeskTab.tsx** — 0 to review, 1 identifier/key/comparison (keep)


**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/AnalysisChart.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L404 [jsx] Buy or sell from the option chain below

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/BasketPanel.tsx** — 14 to review, 9 identifier/key/comparison (keep)

- `C?` L83 [attr:title] Switch buy / sell
- `K-tok?` L86 [jsx] BUY
- `K-tok?` L86 [jsx] SELL
- `C?` L148 [var:ruleNote] Share trade, entry rule ${…}: ${…} (entry ${…} against the LAST ${…}).
- `C?` L155 [call:clip] Entry level set on the chart, not a traded price (the ${…} future's last bhavcopy price ${…}, ${…})
- `C?` L186 [var:presetProblem] Pick Current, Next or Far: the presets need one expiry's chain with prices.
- `C?` L246 [attr:label] FUT ENTRY
- `C?` L248 [attr:label] CASH ENTRY
- `K-tok?` L251 [attr:label] STOP
- `K-tok?` L252 [attr:label] TARGET
- `C?` L253 [jsx] Stop and target are on the underlying (reference
- `C?` L256 [jsx] The future&apos;s entry
- `C?` L264 [jsx] AT THE STOP / TARGET
- `C?` L292 [jsx] Click a B or S in the option chain to add a leg. Click the chart or drag the lines to set cash and future levels. Option and future legs are recorded at the pri

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/ChartAnalysis.tsx** — 18 to review, 2 identifier/key/comparison (keep)

- `C?` L84 [jsx] Pick a stock with the symbol search above to open its chart.
- `C?` L259 [prop:key] ${…}-entry
- `C?` L259 [prop:label] C ENTRY
- `C?` L259 [prop:label] F ENTRY
- `K-tok?` L262 [prop:key] stop
- `K-tok?` L262 [prop:label] STOP
- `K-tok?` L262 [prop:drag] stop
- `K-tok?` L263 [prop:key] target
- `K-tok?` L263 [prop:drag] target
- `K-tok?` L266 [prop:key] sig-entry
- `K-tok?` L266 [prop:label] ENTRY
- `K-tok?` L267 [prop:key] sig-stop
- `K-tok?` L267 [prop:label] STOP
- `K-tok?` L269 [prop:key] sig-t1
- `K-tok?` L269 [prop:label] T1
- `C?` L290 [prop:n] pick an expiry
- `C?` L292 [prop:n] pick an expiry
- `C?` L363 [jsx] · DRAG STOP OR TGT TO MOVE IT

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/OptionChain.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L71 [var:word] Buy
- `C?` L71 [var:word] Sell
- `C?` L210 [jsx] Pick an expiry to trade: legs need one expiry.

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/RecoStrategies.tsx** — 2 to review, 1 identifier/key/comparison (keep)

- `C?` L151 [return] ENTRY ${…} · ${…}
- `C?` L177 [attr:sub] stop ${…}

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/StrategyPanel.tsx** — 8 to review, 1 identifier/key/comparison (keep)

- `C?` L163 [prop:src] not in the chain shown (pick its expiry)
- `C?` L198 [PropertyAccessExpression] Entry
- `C?` L207 [attr:title] Switch buy / sell
- `K-tok?` L209 [jsx] BUY
- `K-tok?` L209 [jsx] SELL
- `C?` L260 [attr:title] Open the basket (＋ PAPER TRADE) to place: its stop, target and plan are set there.
- `C?` L272 [jsx] Open the basket (＋ PAPER TRADE) to place: its stop, target and plan are set there.
- `C?` L335 [jsx] P&amp;L, Greeks, breakevens and max profit / loss come from the payoff route (Black-76 for the today curve and the Greeks, each option&apos;s volatility solved 

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/basket.tsx** — 2 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L153 [prop:side] buy
- `K-tok?` L153 [prop:side] sell

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/presets.ts** — 21 to review, 8 identifier/key/comparison (keep)

- `C?` L99 [return] Consolidated sums open interest over expiries and has no prices: pick Current, Next or Far to add legs.
- `C?` L138 [prop:why] Pick Current, Next or Far: the lot size comes from that expiry's chain.
- `C?` L217 [prop:why] Position delta ${…} (payoff route) is within 10% of the largest leg's ${…} units: recorded as neutral, with no stop or target.
- `C?` L231 [prop:dropped] A neutral position records no stop or target on the underlying, so the levels set are not sent.
- `C?` L237 [call:problems.push] For a ${…} position the stop (${…}) must be ${…} the reference ${…}.
- `C?` L241 [call:problems.push] For a ${…} position the target (${…}) must be ${…} the reference ${…}.
- `K-tok?` L257 [var:STOP_SCENARIO] stop
- `K-tok?` L258 [var:TARGET_SCENARIO] target
- `C?` L263 [return] The entry prices are dated ${…}, after today ${…}.
- `K-tok?` L314 [prop:side] buy
- `K-tok?` L314 [prop:side] sell
- `K-tok?` L327 [var:side] BUY
- `K-tok?` L327 [var:side] SELL
- `C?` L377 [call:clip] Stop on the underlying ${…}.
- `C?` L378 [call:clip] Target ${…}.
- `C?` L414 [call:problems.push] A share paper trade is long only: selling shares is not recorded. Flip the cash leg to BUY.
- `C?` L415 [call:problems.push] Set a stop below the entry: a share paper trade needs one.
- `C?` L416 [call:problems.push] The stop (${…}) must be below the entry (${…}).
- `C?` L417 [call:problems.push] The target (${…}) must be above the entry (${…}).
- `C?` L430 [call:clip] ${…} share paper trade from Trade Desk › Chart Analysis: ${…} shares, entry ${…} (${…}), stop ${…}${…}.
- `C?` L430 [call:clip] , target ${…}

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/analysis/reco-data.ts** — 6 to review, 6 identifier/key/comparison (keep)

- `C?` L130 [return] Pick an expiry to trade: legs need one expiry.
- `C?` L133 [return] There is no close for ${…} on ${…}, so there is no price to pick it at.
- `K-tok?` L181 [arrow] BUY
- `K-tok?` L181 [arrow] SELL
- `K-tok?` L252 [prop:kind] entry
- `C?` L259 [prop:lossLabel] LOSS AT STOP

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/parts.tsx** — 12 to review, 0 identifier/key/comparison (keep)

- `C?` L30 [prop:label] Waiting for entry
- `C?` L31 [prop:label] Entry triggered
- `C?` L33 [prop:label] Exit pending
- `C?` L77 [prop:label] Stop
- `C?` L78 [prop:label] Trailing stop
- `C?` L79 [prop:label] Target
- `C?` L80 [prop:label] Time exit
- `C?` L81 [prop:label] Trend exit
- `C?` L84 [prop:label] Entry not reached
- `C?` L92 [arrow] Stop and target both touched${…}: stop assumed
- `C?` L93 [arrow] Gapped through the stop: filled at the open
- `C?` L94 [arrow] Gapped through the entry: filled at the open

**pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/trade-desk-data.ts** — 3 to review, 0 identifier/key/comparison (keep)

- `C?` L139 [call:ApiError.contractDr] desk.exit-job-status: no known status
- `K-tok?` L149 [prop:queryKey] exit-job-status
- `K-tok?` L152 [prop:path] /api/desk/exit-job-status

**pages/CopilotApp/screens/tradingdesk/top10-data.ts** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L161 [prop:legs] Buy ${…} shares ${…}

**pages/CopilotApp/screens/workspace/AiScannerWatchlist.tsx** — 11 to review, 2 identifier/key/comparison (keep)

- `C?` L134 [jsx] A paper trade needs the scanner’s entry and a stop below it;
- `C?` L158 [jsx] : entry
- `C?` L158 [jsx] ), stop
- `C?` L158 [jsx] , target ${…}
- `C?` L158 [jsx] , no target
- `C?` L213 [jsx] Scanner levels: entry
- `C?` L213 [jsx] · stop
- `C?` L213 [jsx] · target ${…}
- `C?` L260 [jsx] Sell
- `C?` L260 [jsx] Buy
- `C?` L430 [jsx] Ideas the AI scanner ranked that day, kept as they were, for review — not recommendations. Nothing is sent to a broker; paper trades are simulated. 9 out of 10 

**pages/CopilotApp/screens/workspace/PersonalLists.tsx** — 2 to review, 1 identifier/key/comparison (keep)

- `C?` L293 [jsx] . It is yours to edit or delete. A research list is not a recommendation.
- `C?` L330 [jsx] Live prices are from Yahoo Finance and are read again every 30 seconds; when the market is shut they are the last close. A stored price is the last end-of-day c

**pages/CopilotApp/screens/workspace/ResearchWatchlist.tsx** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L51 [var:FALLBACK_DISCLAIMER] Research for information only. Not investment advice and not a buy or sell call.

**pages/CopilotApp/screens/workspace/SetupsToWatch.tsx** — 3 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L80 [prop:key] stop
- `C?` L80 [prop:header] Stop · 1.5× ATR
- `C?` L98 [jsx] End-of-day levels from the scanner, not alerts and not a recommendation. Nothing is sent when a level is crossed.

**pages/CopilotApp/shell/Composer.tsx** — 3 to review, 3 identifier/key/comparison (keep)

- `C?` L225 [attr:aria-label] Suggested for you
- `C?` L226 [jsx] Suggested for you
- `C?` L291 [attr:aria-label] Stop the answer

**pages/CopilotApp/shell/Evidence.tsx** — 1 to review, 1 identifier/key/comparison (keep)

- `C?` L179 [call:quality.push] You stopped this answer before it finished.

**pages/CopilotApp/views/Home.tsx** — 9 to review, 0 identifier/key/comparison (keep)

- `C?` L58 [prop:advisor] Which clients are off their target allocation?
- `C?` L242 [prop:cta] See the recommendations
- `K-tok?` L243 [call:go] tool/recommend
- `C?` L257 [prop:title] Portfolio drift: equity ${…}% vs target ${…}%
- `C?` L258 [prop:fact] Rebalance to align with your risk profile target allocation.
- `C?` L260 [call:ask] My equity allocation is ${…}% against a target of ${…}% for my risk profile. How should I rebalance?
- `C?` L325 [var:sub] Ask in plain English. Nivesh picks the tools, runs the numbers on your ${…} holdings and shows you the evidence behind every answer.
- `C?` L327 [var:sub] Ask in plain English. Nivesh picks the tools and shows the evidence behind every answer. Connect a portfolio to make answers about your money.
- `C?` L328 [var:sub] Ask in plain English. Nivesh picks the tools and shows you the evidence behind every answer.

**pages/CopilotApp/views/Thread.tsx** — 2 to review, 4 identifier/key/comparison (keep)

- `C?` L113 [attr:label] Stopped
- `C?` L114 [jsx] You stopped this answer.

### Backend (`backend/`)


**nidp/services/copilot_agent/_llm.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L232 [assign:ANTI_HALLUCINATIO] Anti-hallucination rules — these override every other instruction: 1. Use ONLY values present in TOOL_DATA above. Never invent fund names, ticker symbols, schem

**nidp/services/copilot_agent/graph.py** — 4 to review, 1 identifier/key/comparison (keep)

- `K-tok?` L75 [dict:?] recommendation_node
- `K-tok?` L109 [call:builder.add_node] recommendation_node
- `K-tok?` L138 [Tuple] recommendation_node
- `K-tok?` L128 [dict:recommendation_node] recommendation_node

**nidp/services/copilot_agent/nodes/compliance.py** — 7 to review, 1 identifier/key/comparison (keep)

- `C?` L157 [assign:_ADVICE_NOTE] *Factual filings/data only — Nivesh Copilot does not give buy/sell/hold advice, price targets, or price predictions.*
- `C?` L146 [call:re.compile] \b(?:short\|long\|near)[- ]term\s+(?:view\|call\|stance)\s*(?:is\|:)?\s*(?:buy\|sell\|hold\|reduce\|accumulate)\b\|\brecommendation\s*:?\s*(?:strong\s+)?(?:buy\
- `C?` L54 [dict:risk_analyst] Suggest a hedge
- `C?` L62 [dict:recommendation] Show one-click SIP for the top pick
- `C?` L63 [dict:recommendation] Compare the top 3 picks
- `C?` L64 [dict:recommendation] Why this and not the second pick?
- `C?` L166 [call:_ADVICE_RE.sub] [factual data only — no recommendation]

**nidp/services/copilot_agent/nodes/goal.py** — 4 to review, 0 identifier/key/comparison (keep)

- `C?` L21 [assign:_SYSTEM] You are the Goal Planner for Nivesh AI, an Indian investment platform. You help users plan for financial goals like retirement, education, home purchase. Use th
- `C?` L152 [assign:feas] short of target
- `C?` L192 [assign:goal_summary] {…} active goals. PRIMARY GOAL — name='{…}', target=₹{…}, horizon={…}y, corpus_earmarked=₹{…}, plan_sip=₹{…}/mo, on_track={…}%.
- `C?` L392 [dict:scheme_name] Recommended SIP allocation

**nidp/services/copilot_agent/nodes/intent.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L85 [assign:_LLM_SYSTEM] You are a financial intent classifier for an Indian investment app. Classify the user message into exactly one agent and return JSON. Agents: - market_analyst: 

**nidp/services/copilot_agent/nodes/intent_patterns.py** — 11 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L23 [assign:RECOMMENDATION] recommendation
- `C?` L37 [call:re.compile] \bback[\s-]?test\b\|\bif\s+i\s*(?:'d\|\s+had\|\s+have\|\s+would\s+have)?\s+(?:invested\|put\|bought\|started)\b\|\bwhat\s+if\s+i\s+(?:had\s+)?(?:invested\|put\|
- `C?` L75 [call:re.compile] \b((?:what\|how\|analyse\|analyze\|tell me about\|research\|buy\|sell\|hold)\s+(?:is\s+)?(?-i:[A-Z]{2,10})\b\|technical\s+(?:analysis\|view\|setup\|signal\|char
- `C?` L88 [call:re.compile] \b(?:(?:what\|how\|analyse\|analyze\|tell me about\|research\|buy\|sell\|hold)\s+(?:is\s+)?[a-z]{2,10}\|[a-z]{2,10}\s+(?:stock\|share\|equity\|target\|price))\b
- `C?` L114 [call:re.compile] too many (?:mutual )?funds?\|how many (?:mutual )?funds?\|(?:fix\|reduce\|cut\|trim\|too much\|significant\w*)\s+(?:the\s+)?overlap\|overlap\w*\s+(?:in\|between
- `C?` L154 [call:re.compile] \b(?:latest\|recent\|any)\s+(?:news\|updates?\|announcements?\|filings?\|disclosures?\|developments?\|corporate\s+actions?)\b\|\bwhat'?s\s+(?:the\s+)?(?:latest\
- `C?` L237 [call:re.compile] \b((?:my\s+)?portfolio\|my\s+investments?\|my\s+holdings?\|my\s+(?:top\|biggest\|largest\|major\|main\|current)\s+(?:\d+\s+)?(?:equity\s+\|stock\s+\|mutual\s+fu
- `C?` L269 [call:re.compile] \b(risk\s+(?:profile\|suitability\|capacity\|tolerance\|level\|score\|assessment\|exposure\|rating)\|portfolio\s+risk\|my\s+risk\|too\s+(?:much\|aggressive\|ris
- `C?` L286 [call:re.compile] \b(goal\|goals\|retirement\|education(?:\s+(?:fund\|corpus\|cost\|goal))?\|corpus\|target\s+amount\|on\s+track\|sip\s+(?:gap\|needed\|required\|adequacy)\|sip\s
- `C?` L333 [call:re.compile] \b(recommend\|recommendation\|suggest\|what\s+(?:should\|can)\s+i\s+(?:buy\|invest)\|what\s+stocks?\s+should\s+(?:i\|we)\s+(?:buy\|invest)\|where\s+(?:should\|c
- `C?` L401 [call:re.compile] \bp\s*/?\s*e\b\|\bp\s*/?\s*b\b\|\bp\s*/?\s*s\b\|\bpeg\b\|ev\s*/?\s*ebitda\|enterprise\s+value\|market\s+cap\|price[\s-]*to[\s-]*(?:book\|sales\|earnings)\|intri

**nidp/services/copilot_agent/nodes/market.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L21 [assign:_SYSTEM] You are the Market Analyst for Nivesh AI, an Indian investment platform. You have a live NSE/BSE market snapshot in the TOOL_DATA block: index levels (Nifty 50,

**nidp/services/copilot_agent/nodes/mf.py** — 7 to review, 0 identifier/key/comparison (keep)

- `C?` L21 [assign:_SYSTEM] You are the Mutual Fund Analyst for Nivesh AI, an Indian investment platform. You have fund performance, risk metrics, category rankings, lifecycle events, top 
- `C?` L53 [call:re.compile] too many\|how many (?:mutual )?funds\|consolidat\|over[\s-]?diversif\|trim (?:my )?(?:funds\|portfolio)\|reduce (?:my )?(?:number of )?funds\|portfolio size\|ho
- `C?` L111 [call:re.compile] tell me about\|good fund\|should i (?:invest in\|continue\|buy\|hold\|pick)\|start\s+a?\s*sip\s+in\|direct\s+(?:or\|vs)\s+regular\s+plan\|(?:overview\|returns?\
- `C?` L141 [call:re.compile] \b(?:best\|top\|worst\|recommend\|suggest)\b.*\bfunds?\b\|\bfunds?\b.*\b(?:best\|top\|worst)\b\|\b(?:large\|mid\|small\|flexi\|multi)[\s-]?cap\s+(?:mutual\s+)?f
- `C?` L162 [call:re.compile] what\s+(?:is\|are)\s+(?:a\s+\|an\s+)?(?:mutual\s+funds?\|nav\|sip\|elss\|expense\s+ratio\|ter\|aum\|exit\s+load\|lump\s*sum)\b\|how\s+(?:do\|does)\s+(?:mutual\s
- `C?` L207 [assign:_COUNT_FORMAT] You are answering a COUNT / portfolio-size question (e.g. "do I have too many funds?"). OUTPUT IN PLAIN TEXT ONLY. This surface does NOT render Markdown. Never 
- `C?` L263 [assign:_FIX_FORMAT] You are answering a "fix the overlap" / consolidation request. OUTPUT IN PLAIN TEXT ONLY. No '#', the asterisk character, backticks, or pipe ('\|') tables — the

**nidp/services/copilot_agent/nodes/policy.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L190 [AugAssign] {…}-sector names in the Nifty 500 (illustrative, not a buy list): {…}.

**nidp/services/copilot_agent/nodes/portfolio.py** — 13 to review, 0 identifier/key/comparison (keep)

- `C?` L20 [assign:_SYSTEM] You are the Portfolio Analyst for Nivesh AI. You have the user's personal portfolio data in TOOL_DATA below. Ground every figure in that data. Do not use generi
- `C?` L230 [call:re.compile] \bcapital\s+gains?\b\|\bcg\s+statement\b\|\breali[sz]ed?\s+(?:capital\s+)?gains?\b\|\bstcg\b\|\bltcg\b\|\btax\s+(?:if\|when)\s+i\s+(?:book\|sell\|redeem)\b\|\bb
- `C?` L237 [assign:_CG_SYSTEM] You are the Tax Analyst for Nivesh AI. TOOL_DATA holds the user's REALISED capital-gains statement for a financial year, computed FIFO: Section A short-term (Se
- `C?` L137 [Tuple] sell for tax
- `K-tok?` L88 [Tuple] trim
- `K-tok?` L88 [Tuple] exit
- `C?` L88 [Tuple] sell first
- `C?` L88 [Tuple] what should i exit
- `K-tok?` L126 [Tuple] recommend
- `C?` L126 [Tuple] top recommendation
- `K-tok?` L127 [Tuple] suggestion
- `C?` L172 [Tuple] when to sell
- `C?` L172 [Tuple] wait to sell

**nidp/services/copilot_agent/nodes/recommendation.py** — 8 to review, 0 identifier/key/comparison (keep)

- `C?` L204 [assign:_BUILDER_INTRO] Let's build your portfolio. Pick a goal and I'll shape a real, ranked mix to your risk profile — every fund scored on live V3 quality, not samples.
- `C?` L220 [assign:_STRATEGY_LAB_INT] Opening the Strategy Lab. Pick a universe, choose a factor template, then screen and backtest it on live, corp-action-adjusted data — right here in chat.
- `C?` L20 [assign:_SYSTEM] You are the Recommendation Engine for Nivesh AI, an Indian investment platform. You surface actionable investment ideas grounded in screener data in TOOL_DATA. 
- `K-tok?` L266 [call:importlib.import_mo] services.copilot_tools.recommendation
- `C?` L441 [call:logger.warning] recommendation data fetch failed: %s
- `K-tok?` L443 [kw:tool_name] recommendation_tools
- `C?` L444 [kw:summary] Recommendation data unavailable
- `K-tok?` L328 [kw:tool_name] recommend_mf

**nidp/services/copilot_agent/nodes/risk.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L23 [assign:_SYSTEM] You are the Risk Analyst for Nivesh AI, an Indian investment platform. You assess portfolio risk using the data in TOOL_DATA below. Style: - ≤ 220 words, plain 

**nidp/services/copilot_agent/nodes/stock.py** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L41 [assign:_SYSTEM] TRADE PLAN RULES (only when the message carries a TRADE_PLAN data block — the desk's own rule-based plan for this stock, built from end-of-day data): - Add a la
- `C?` L22 [assign:_SYSTEM] You are the Stock Analyst for Nivesh AI, an Indian investment platform. You have live technical indicators, fundamental data, and quarterly financial trends for

**nidp/services/copilot_agent/nodes/stocks_insights.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L31 [assign:_SYSTEM] You are Nivesh Copilot — an Indian equity research assistant that answers ONLY from authenticated exchange disclosures. TOOL_DATA gives you a numbered list of a

**nidp/services/copilot_agent/persona_framing.py** — 10 to review, 0 identifier/key/comparison (keep)

- `C?` L103 [assign:DESK_ANSWER_STRUC] This question was asked from the Smart trading desk. Where it applies, answer in this order, each part under a short bold label: 1) Direct answer: one or two se
- `C?` L22 [dict:beginner_investor] User profile: Salaried Beginner Investor. Explain in plain language, avoid jargon, and use Fixed Deposit as the reference yardstick when discussing returns. Rec
- `C?` L27 [dict:mutual_fund_investo] User profile: Mutual Fund Focused Investor. Go deep on fund-level analysis: scheme overlap, expense ratio (direct vs regular), category fit, manager tenure, AUM
- `C?` L32 [dict:stock_investor] User profile: Direct Equity Investor. Lead with valuation (P/E, P/B, ROE) and fundamentals; cite sector views and concentration when relevant. Be specific about
- `C?` L42 [dict:swing_trader] User profile: Swing Trader. Emphasise short-to-medium holding period setups, momentum, sector rotation, risk-reward ratios, and stop-loss discipline.
- `C?` L50 [dict:options_trader] User profile: Options Trader. Acknowledge derivatives context; focus on Greeks, IV, position sizing, and risk management. Do not recommend speculative naked pos
- `C?` L59 [dict:retirement_planner] User profile: Retirement Planner. Lead with income-stability, withdrawal-rate safety, and inflation protection. Bias toward downside risk and debt allocation; f
- `C?` L69 [dict:tax_saver] User profile: Tax-Conscious Investor. Apply a tax-impact lens to every recommendation. Cite STCG / LTCG implications, the ₹1.25L LTCG exemption, indexation, and
- `C?` L74 [dict:conservative_invest] User profile: Conservative Investor. Lead with capital preservation and downside risk. Use FD as the comparable yardstick; favour debt and hybrid options over h
- `C?` L84 [dict:mfd_advisor] User profile: MFD / Financial Advisor (acting on behalf of a client). Be analytically rigorous; surface tax-aware, suitability-driven recommendations the adviso

**nidp/services/copilot_agent/schemas.py** — 1 to review, 0 identifier/key/comparison (keep)

- `K-tok?` L41 [assign:RECOMMENDATION] recommendation

**routes/copilot.py** — 3 to review, 1 identifier/key/comparison (keep)

- `C?` L58 [dict:tier] Best · recommended
- `C?` L144 [call:lines.append] - {…} · target ₹{…} · {…}% on track
- `K-tok?` L407 [call:(cached or {}).get] recommendations

**routes/copilot_prompt_catalog.py** — 39 to review, 0 identifier/key/comparison (keep)

- `C?` L119 [call:_entry] Should I sell any of my stocks or funds?
- `C?` L120 [call:_entry] Tax-smart exit suggestions
- `C?` L121 [call:_entry] Should I sell any of my stocks or funds right now? Be specific and include tax impact.
- `C?` L136 [call:_entry] Curated long-horizon fund picks
- `C?` L137 [call:_entry] Which mutual funds are best for long-term wealth creation? Give me 3 concrete picks.
- `C?` L142 [call:_entry] Pick the right vehicle for you
- `K-tok?` L156 [call:_entry] Target
- `C?` L173 [call:_entry] Which of my funds are dragging down my overall portfolio performance? Suggest replacements.
- `C?` L187 [call:_entry] Top SIP picks by category
- `C?` L220 [call:_entry] Which of my stocks look overvalued on P/E and P/B today? Should I trim them?
- `C?` L239 [call:_entry] Trim winners, add to laggards
- `C?` L240 [call:_entry] Should I rebalance my equity holdings now? Suggest specific buy / sell amounts.
- `K-tok?` L264 [call:_entry] Target
- `C?` L291 [call:_entry] Cross-asset deviation from target
- `C?` L292 [call:_entry] Which assets in my portfolio should be rebalanced? Show deviation from my target allocation.
- `C?` L295 [call:_entry] Portfolio downside in a market crash?
- `C?` L297 [call:_entry] What is my portfolio's downside if equity markets fall 25%? Show rupee impact and recovery time.
- `K-tok?` L335 [call:_entry] Target
- `C?` L339 [call:_entry] Is my debt allocation adequate for someone close to retirement? Compare to recommended share.
- `K-tok?` L360 [call:_entry] Target
- `C?` L390 [call:_entry] Goal-progress against the target
- `C?` L405 [call:_entry] Gap between projected corpus and target
- `C?` L406 [call:_entry] How much shortfall exists between my projected corpus and the education target?
- `C?` L451 [call:_entry] Which holdings can I sell for tax harvesting?
- `C?` L453 [call:_entry] Which holdings should I consider selling for tax-loss harvesting this year?
- `C?` L466 [call:_entry] Hold or sell before FY ends?
- `C?` L468 [call:_entry] Should I hold or sell some positions before the financial year ends? Use the ₹1.25L LTCG exemption.
- `C?` L508 [call:_entry] How much downside do I face?
- `C?` L510 [call:_entry] How much downside risk do I face in a bad market? Estimate my max drawdown.
- `C?` L520 [call:_entry] Which of my holdings are most volatile? Rank them so I can trim the risky names.
- `C?` L525 [call:_entry] Can I earn better returns than a fixed deposit with similar low risk? Suggest options.
- `C?` L535 [call:_entry] Curated debt fund picks
- `C?` L588 [call:_entry] Repeatable swing entry rules
- `C?` L589 [call:_entry] What is an effective swing trading setup? Give me the entry, stop and exit rules.
- `C?` L595 [call:_entry] How do I manage risk as an active trader? Cover position sizing and stop discipline.
- `C?` L620 [call:_entry] Do I have adequate global diversification? Compare my international share to a recommended target.
- `C?` L651 [call:_entry] Curated global ETF picks
- `C?` L652 [call:_entry] Which international ETFs are suitable for an NRI investor? Suggest specific picks across US, EM and global.
- `C?` L663 [call:_entry] Suggested India / US / EM / other mix

**routes/copilot_prompts.py** — 21 to review, 1 identifier/key/comparison (keep)

- `K-tok?` L810 [call:router.get] /copilot/suggested-prompts
- `C?` L169 [dict:outcome] Find duplicate funds and which to exit with lowest tax hit
- `K-tok?` L192 [dict:bucket] exit
- `C?` L194 [dict:label] Which fund should I exit first
- `C?` L195 [dict:outcome] Rank my funds by exit-priority and show tax savings
- `C?` L196 [dict:query] If I want to exit some investments, which ones should I sell first with the lowest tax impact? Show tax-aware analysis.
- `C?` L208 [dict:outcome] Get a specific fund suggestion that fills my portfolio gaps
- `C?` L248 [dict:query] What happens if I follow your recommended actions? How will my portfolio look after — show before vs after allocation, risk, and expected returns.
- `K-tok?` L275 [dict:icon] Target
- `C?` L688 [Tuple] Entry zone, volume confirmation, invalidation
- `K-tok?` L690 [Tuple] Target
- `C?` L87 [Tuple] Tax-optimised exits available
- `C?` L556 [dict:caption] Debt today · target {…}%
- `C?` L567 [dict:caption] Tax-smart exits ready
- `C?` L622 [dict:outcome] Top 10 high-priority clients with the recommended action for each.
- `C?` L623 [dict:query] Give me my top 10 high-priority clients today — for each, name, the issue, and the recommended action.
- `C?` L639 [dict:outcome] Clients deviating >10% from their target allocation.
- `C?` L640 [dict:query] Which clients are deviating more than 10% from their target allocation? List the bucket that is off.
- `C?` L655 [dict:label] Which clients stopped their SIPs recently?
- `C?` L657 [dict:query] Which of my clients have stopped or paused SIPs in the last 3 months? Show last contribution date.
- `C?` L553 [dict:label] Gap to target

**routes/desk_chartink.py** — 1 to review, 2 identifier/key/comparison (keep)

- `K-tok?` L173 [call:router.get] /picks

**routes/desk_trading.py** — 9 to review, 6 identifier/key/comparison (keep)

- `K-tok?` L1054 [call:router.get] /exit-job-status
- `K-tok?` L448 [dict:source] entry
- `K-tok?` L444 [dict:source] entry
- `C?` L859 [kw:levels_error] computed at entry (exit_plan.options)
- `C?` L310 [call:logger.warning] desk: no end-of-day bars for %s to check an at-once entry: %s
- `C?` L842 [dict:message] The trade's own {…} exit fired on {…}; it closes by that rule, not by a roll.
- `K-tok?` L865 [dict:name] t1
- `C?` L965 [dict:text] Entry assumed when recorded.
- `C?` L965 [dict:text] Entry level reached.

**routes/fno.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L1164 [kw:pattern] ^(buy\|sell)$

**routes/portfolio_desk.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L85 [dict:text] Average traded value (close × volume) over the last 20 sessions, and the days to sell the position at 10% of the average daily volume. High: a holding needs mor

**routes/positional.py** — 32 to review, 22 identifier/key/comparison (keep)

- `C?` L958 [assign:_SIGNAL_COLS] COALESCE(revision, 1) AS revision, final_score, confidence, stage, timeframe_days_min, timeframe_days_max, entry_price, stoploss, target_price, risk_reward, sou
- `C?` L1830 [assign:_BASKET_RISK_BASI] loss at the stop after estimated round-trip costs (the desk cost card: brokerage, STT, exchange charge, SEBI fee, stamp duty, GST and slippage; DP charges and i
- `C?` L1855 [assign:_SCENARIO_METHOD] PRD §8.5, long only: risk per share = entry − stop; reward per share = target − entry; reward : risk = reward ÷ risk; quantity = the most shares whose loss at t
- `C?` L170 [assign:sql] SELECT ps.nse_symbol, ps.signal_date, ps.final_score, ps.confidence, ps.stage, ps.timeframe_days_min, ps.timeframe_days_max, ps.entry_price, ps.stoploss, ps.tar
- `K-tok?` L256 [call:router.get] /picks
- `K-tok?` L866 [call:router.get] /picks/mine
- `C?` L923 [call:router.get] /picks/{symbol}
- `C?` L1497 [dict:median_return] Not stored: the labeller keeps each scan's maximum excursion, not a realised exit return.
- `C?` L1847 [Tuple] A stop price does not guarantee the exit price: a gap or thin trading can fill the exit beyond the stop, so the loss can be larger than shown.
- `K-tok?` L785 [return] STOPPED
- `K-tok?` L963 [Tuple] entry
- `K-tok?` L963 [Tuple] stop
- `K-tok?` L964 [Tuple] target
- `C?` L1968 [dict:risk_basis] the loss at the stop after the entry and stop-exit costs fits the risk budget
- `C?` L1076 [dict:outcomes_basis] positional_outcomes: target / stop hit per horizon, written by the outcome job; empty until a horizon is evaluated
- `C?` L1425 [dict:instructions] scan_name in your alert will auto-match to internal names (e.g. 'TODAYS TOP BUY' → 'atlas.todays_top_buy')
- `C?` L2016 [dict:assumption] The buy is new money added to the portfolio; weights are of the portfolio after the buy.
- `C?` L2025 [kw:description] Reference entry price, ₹
- `C?` L2026 [kw:description] Stop-loss price, ₹ (below the entry)
- `C?` L2027 [kw:description] Target price, ₹ (above the entry)
- `C?` L817 [call:logger.warning] live overlay timed out — returning picks without LTP (will repopulate next tick)
- `K-tok?` L1918 [call:_scenario_problem] entry
- `C?` L1918 [call:_scenario_problem] The entry must be a price above zero.
- `K-tok?` L1920 [call:_scenario_problem] stop
- `C?` L1920 [call:_scenario_problem] The stop must be a price above zero.
- `K-tok?` L1923 [call:_scenario_problem] stop
- `C?` L1924 [call:_scenario_problem] For a long position the stop (₹{…}) must be below the entry (₹{…}).
- `K-tok?` L1927 [call:_scenario_problem] target
- `C?` L1928 [call:_scenario_problem] For a long position the target (₹{…}) must be above the entry (₹{…}).
- `C?` L1976 [call:_scenario_problem] The risk budget (₹{…}) does not cover one share's risk (₹{…}) plus the round-trip costs at the stop, so no whole share fits.
- `K-tok?` L827 [call:p.get] stoploss
- `K-tok?` L2137 [call:p.get] stoploss

**routes/strategy_builder.py** — 0 to review, 2 identifier/key/comparison (keep)


**services/copilot_visual/broker_review.py** — 28 to review, 6 identifier/key/comparison (keep)

- `C?` L67 [assign:src] your stop
- `K-tok?` L119 [dict:key] entry
- `K-tok?` L119 [dict:label] Entry
- `K-tok?` L120 [dict:key] exit
- `K-tok?` L120 [dict:label] Exit
- `K-tok?` L66 [call:(lv or {}).get] stop
- `K-tok?` L68 [call:pl.get] stop
- `C?` L69 [Tuple] the plan's stop
- `C?` L75 [assign:cell] Stop not honoured
- `C?` L84 [assign:cell] Target reached
- `C?` L61 [dict:text] {…}: your stop was set on {…}, after this trade closed, so it is not used.
- `K-tok?` L70 [call:(pl or {}).get] target
- `C?` L78 [assign:cell] Exited before the stop
- `C?` L81 [assign:cell] Within your stop
- `C?` L83 [dict:text] {…}: exited at {…}, at or past the target ({…}).
- `K-tok?` L96 [call:pl.get] entry
- `C?` L108 [dict:pnl] The broker's own fill prices: quantity × (exit − entry), gross. Charges are not estimated.
- `C?` L110 [dict:plan] No stop of yours and no plan was on record for this contract.
- `C?` L189 [call:block] Partial fills of one order are one round trip. Quantity is in units, as the broker sends it; an F&O lot is its lot size in units. A round trip is a buy matched 
- `C?` L197 [call:block] Did you follow your entry, stop-loss and exit rules?
- `C?` L198 [call:block] Only where your own stop (set before the trade closed) or a plan you recorded (before it opened) exists.
- `K-tok?` L70 [call:(lv or {}).get] target
- `C?` L74 [dict:text] {…}: exited at {…}, {…}% beyond {…} ({…}): the stop was not honoured.
- `C?` L84 [Tuple] Within your stop
- `C?` L98 [dict:text] {…}: entered at {…}, {…}% {…} the plan's entry ({…}).
- `C?` L194 [dict:text] {…} of {…} round trip{…} had a stop of yours or a recorded plan in force;
- `C?` L77 [dict:text] {…}: closed at a loss, on the safe side of {…} ({…}): you exited before it was hit.
- `C?` L80 [dict:text] {…}: exited at {…}, on the safe side of {…} ({…}).

**services/copilot_visual/builders.py** — 108 to review, 10 identifier/key/comparison (keep)

- `C?` L54 [assign:SRC_DECISIONS] Your entry risk checks (risk_decisions)
- `C?` L853 [assign:FNO_NOTE] Fit to today's measured regime, not a performance rank. Figures are for the lots shown, gross, before charges. A bought option's profit is not capped in practic
- `K-tok?` L1262 [Tuple] stop
- `K-tok?` L1262 [Tuple] target
- `K-tok?` L1265 [dict:stop] Stop
- `C?` L1265 [dict:trailing_stop] Trailing stop
- `K-tok?` L1265 [dict:target] Target
- `C?` L1266 [dict:trend] Trend exit
- `C?` L1266 [dict:premium_stop] Premium stop
- `C?` L1266 [dict:premium_target] Premium target
- `C?` L1268 [dict:entry_not_reached] Entry not reached
- `C?` L502 [assign:rule_note] Rule ({…}): close {…}–{…}% above the breakout level, 3-session volume ≥ {…}× the prior 20, stage {…}, gap-up ≤ {…}%. Stop = level − {…} × ATR(14).
- `C?` L633 [return] entry {…}
- `C?` L771 [assign:title] {…} · entry, stop and targets
- `C?` L1251 [call:assemble] {…} · hold, trail or exit
- `C?` L1514 [assign:checks] the risk checks refused {…} of {…} entry request{…}
- `C?` L1559 [return] Buy {…} {…} of the {…} put, sell the {…} put
- `C?` L1560 [return] Buy {…} {…} of the {…} put
- `C?` L411 [call:block] Sector index returns over 1 week, best first. Select a sector for its top {…} stocks by the day's move (with index weight): a rank of today's move, not a recomm
- `C?` L1195 [call:follow] Should I book profits or hold {…}?
- `C?` L1246 [call:_chart] {…} · price against stop and target
- `C?` L1249 [call:notice] Ideas to review, not advice: this shows your trade's own levels and today's price; it does not tell you to exit or hold.
- `C?` L548 [call:follow_ups.insert] Entry, target and stop-loss for {…}
- `K-tok?` L641 [call:tp.get] entry
- `K-tok?` L641 [call:tp.get] stop
- `K-tok?` L714 [dict:kind] entry
- `C?` L714 [dict:label] Entry {…}
- `K-tok?` L715 [dict:kind] stop
- `C?` L715 [dict:label] Stop {…}
- `K-tok?` L716 [call:tp.get] targets
- `K-tok?` L732 [call:_kpi] Entry
- `K-tok?` L1176 [call:orig.get] entry
- `K-tok?` L1221 [call:_kpi] Entry
- `C?` L1412 [call:block] Planned entry, stop and target against the fill and the exit. R = (exit − fill) ÷ (fill − stop), before costs; an F&O structure's stop and target are underlying
- `C?` L206 [call:block] Net buy − sell, ₹ crore, {…} (NSE provisional).
- `C?` L206 [call:block] Net buy − sell, ₹ crore (NSE provisional).
- `K-tok?` L425 [call:tp.get] targets
- `K-tok?` L692 [call:tp.get] entry
- `K-tok?` L692 [call:tp.get] stop
- `K-tok?` L713 [call:tp.get] entry
- `K-tok?` L713 [call:tp.get] stop
- `K-tok?` L729 [call:tp.get] entry
- `K-tok?` L729 [call:tp.get] stop
- `K-tok?` L737 [call:_kpi] Stop
- `C?` L739 [call:_kpi] First target
- `C?` L740 [call:_kpi] to the first target, before charges
- `C?` L1159 [dict:text] Stop moved: recorded {…}, today {…}.
- `K-tok?` L1170 [call:tp.get] entry
- `K-tok?` L1170 [call:tp.get] stop
- `K-tok?` L1172 [dict:kind] entry
- `C?` L1172 [dict:label] Today's entry {…}
- `K-tok?` L1174 [dict:kind] stop
- `C?` L1174 [dict:label] Today's stop {…}
- `K-tok?` L1178 [dict:kind] entry
- `C?` L1178 [dict:label] Recorded entry {…}
- `C?` L1224 [call:_kpi] Distance to stop
- `C?` L1226 [call:_kpi] Distance to target
- `C?` L1452 [dict:text] {…} trade{…} closed without an entry (the entry level was not reached, or it was cancelled): no P&L.
- `K-tok?` L1455 [call:block] exits
- `C?` L1482 [call:notice] No entry request was checked by the risk rules {…}.
- `C?` L1490 [call:src.miss] Your stops and recorded plans (for the broker review)
- `C?` L269 [call:block] Net buy − sell, ₹ crore (NSE provisional).
- `K-tok?` L536 [dict:kind] stop
- `C?` L536 [dict:label] Stop {…}
- `K-tok?` L718 [dict:kind] target
- `C?` L1230 [Tuple] {…} against stop {…}
- `C?` L1231 [Tuple] target {…}
- `K-tok?` L1243 [dict:kind] stop
- `C?` L1243 [dict:label] Stop {…}
- `K-tok?` L1245 [dict:kind] target
- `C?` L1245 [dict:label] Target {…}
- `C?` L1439 [dict:text] {…} stop exit{…} filled below the stop ({…}): the session opened through it, so the loss was larger than the stop distance.
- `C?` L1450 [dict:text] Held {…} sessions on average, entry to exit.
- `K-tok?` L281 [call:head.append] bought
- `K-tok?` L281 [call:head.append] sold
- `K-tok?` L282 [call:head.append] bought
- `K-tok?` L282 [call:head.append] sold
- `C?` L647 [Tuple] stop {…} ({…})
- `C?` L696 [Tuple] stop {…}
- `C?` L697 [Tuple] first target {…}
- `K-tok?` L1157 [call:tp.get] stop
- `K-tok?` L1415 [dict:key] exit
- `K-tok?` L1415 [dict:label] Exit
- `C?` L1416 [dict:label] Planned entry
- `K-tok?` L1418 [dict:key] stop
- `K-tok?` L1418 [dict:label] Stop
- `K-tok?` L1419 [dict:key] target
- `K-tok?` L1419 [dict:label] Target
- `C?` L1420 [dict:label] Exit price
- `C?` L1462 [dict:text] {…} entry request{…} checked: {…} allowed, {…} reduced, {…} refused
- `C?` L1685 [dict:label] What you would buy
- `K-tok?` L469 [dict:key] entry
- `K-tok?` L469 [dict:label] Entry
- `K-tok?` L470 [dict:key] stop
- `K-tok?` L470 [dict:label] Stop
- `K-tok?` L471 [dict:key] target
- `K-tok?` L471 [dict:label] Target
- `K-tok?` L526 [dict:key] stop
- `K-tok?` L526 [dict:label] Stop
- `C?` L719 [Attribute] Target {…} {…}
- `K-tok?` L1157 [call:orig.get] stop
- `C?` L1394 [call:_kpi] {…} of {…} had a stop to measure against, before costs
- `C?` L1395 [call:_kpi] no trade had a stop to measure against
- `C?` L463 [Tuple] Reward:risk is the first target's R multiple, before charges.
- `K-tok?` L647 [Tuple] stop
- `K-tok?` L457 [call:tp.get] entry
- `K-tok?` L457 [call:tp.get] stop
- `C?` L1430 [dict:text] {…} of {…} exits came from the plan's own rules

**services/copilot_visual/events_builders.py** — 6 to review, 0 identifier/key/comparison (keep)

- `C?` L52 [assign:AI_NOTE] AI summary of the filing. Not a recommendation.
- `C?` L95 [assign:p['caveat']] AI summaries are Nivesh's stored analyses of each filing, not recommendations; nothing is sent to a broker.
- `C?` L220 [assign:lines] {…} — an analysis of the filing, not a recommendation.
- `C?` L322 [assign:note] AI summary of the results filing{…}{…}. Not a recommendation.
- `C?` L644 [call:block] The badge rates the result Below, Meets or Above expectation where the desk has rated it (expectation = the company's own baseline from its past quarters; no an
- `C?` L417 [call:block] Showing {…} of {…} declared results: the ones with an AI summary first, F&O names first within them. The badge rates a result Below, Meets or Above expectation,

**services/copilot_visual/fno_board.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L70 [Tuple] The theoretical top is {…}, with the index at zero. That is not a realistic target, so the profit at the expected move is shown instead.

**services/copilot_visual/intents.py** — 12 to review, 0 identifier/key/comparison (keep)

- `C?` L109 [call:re.compile] \bsmart\s+money\b\|\bfiis?\b\|\bdiis?\b\|\bfpis?\b\|\binstitution(al\|s)?\b.{0,30}\b(flows?\|buying\|selling\|money\|activity)\b\|\bwhere\s+is\s+(the\s+)?money\
- `C?` L128 [call:re.compile] \btop\s+(\d{1,2}\|three\|five\|ten)?\s*(trading\s+\|trade\s+)?(opportunit\w+\|ideas?\|stocks?\|setups?\|trades?\|picks?)\b\|\bbest\s+(trading\s+\|trade\s+)?(opp
- `C?` L158 [call:re.compile] \bbook(ing)?\s+(the\s+)?(profits?\|gains)\b\|\bshould\s+i\s+(hold\|exit\|sell\|book)\b\|\b(or\|and)\s+hold\b\|\btrail(ing)?\s+(my\s+)?stop\b\|\bmove\s+(my\s+)?s
- `C?` L162 [call:re.compile] \bposition\s+siz\w*\|\bhow\s+much\s+(should\|can\|do)\s+i\s+risk\b\|\bhow\s+many\s+(shares?\|lots?\|units?)\s+(should\|can)\s+i\s+(buy\|trade\|take)\b\|\bwhat\s
- `C?` L254 [call:re.compile] \b(a\s+)?(good\s+)?buy\b\|\bbuy\s+(now\|today\|here)\b\|\bshould\s+i\s+(buy\|enter\|go\s+long)\b\|\bgood\s+time\s+to\s+(buy\|enter)\b\|\bworth\s+buying\b\|\bent
- `C?` L326 [call:re.compile] \bm\s?&\s?a\b\|\bmergers?\b\|\bmerg(e\|es\|ed\|ing)\b\|\bacqui(re\|res\|red\|ring\|sitions?)\b\|\bamalgamat\w+\|\bde-?merg\w+\|\bspin[- ]?offs?\b\|\bbuy[- ]?bac
- `C?` L339 [call:re.compile] \bpledg(e\|ed\|es\|ing)\b\|\bencumbrance\b\|\bsast\b\|\bsubstantial\s+acquisition\b\|\binsider\s+(trad\w+\|buying\|selling\|transactions?\|deals?)\b\|\b(promote
- `K-tok?` L82 [Set] SL
- `K-tok?` L84 [Set] ENTRY
- `K-tok?` L84 [Set] EXIT
- `K-tok?` L84 [Set] STOP
- `K-tok?` L85 [Set] TARGET

**services/copilot_visual/open_book.py** — 36 to review, 9 identifier/key/comparison (keep)

- `C?` L56 [assign:READ_ONLY_TEXT] Nivesh reads your broker positions; it cannot place, modify or cancel an order. These are checks to review, not recommendations.
- `K-tok?` L180 [dict:key] stop
- `K-tok?` L180 [dict:label] Stop
- `K-tok?` L181 [dict:key] target
- `K-tok?` L181 [dict:label] Target
- `C?` L182 [dict:label] To stop
- `C?` L183 [dict:label] Loss at stop
- `C?` L231 [assign:stop_cell] No stop set
- `C?` L489 [call:block] Stops, loss at the stop and margin, by underlying
- `C?` L490 [call:block] Your own stops and targets (or the plan you recorded when you set none). The loss at the stop is gross and is never the price falling to zero. Margin is Zerodha
- `C?` L499 [call:block] Checks against your stops and plans
- `C?` L238 [assign:tips['risk']] If the price reaches your stop ({…}), valued {…}; gross, before charges. Never the price falling to zero.
- `C?` L242 [assign:tips['risk']] Without a stop the loss at a stop cannot be shown, and a to-zero figure is not the risk of a position.
- `C?` L554 [call:_kpi] waiting for its entry condition
- `K-tok?` L115 [dict:side] buy
- `K-tok?` L115 [dict:side] sell
- `C?` L241 [assign:risk] No stop set
- `C?` L663 [Attribute] Nivesh cannot place, modify or cancel an order. Ideas to review, not recommendations.
- `C?` L561 [dict:ask] Should I book profits or hold {…}?
- `C?` L346 [assign:bits] entry {…}
- `C?` L347 [assign:bits] stop {…}
- `C?` L348 [assign:bits] target {…}
- `K-tok?` L568 [dict:key] entry
- `K-tok?` L568 [dict:label] Entry
- `K-tok?` L570 [dict:key] stop
- `K-tok?` L570 [dict:label] Stop
- `K-tok?` L571 [dict:key] target
- `K-tok?` L571 [dict:label] Target
- `K-tok?` L262 [call:lv.get] target
- `C?` L332 [dict:text] {…}: no stop of yours and no matching plan is on record, so the loss at a stop cannot be shown.
- `C?` L328 [dict:text] {…}: {…}% {…} the stop {…}
- `K-tok?` L346 [call:plan.get] entry
- `K-tok?` L347 [call:plan.get] stop
- `K-tok?` L348 [call:plan.get] target
- `C?` L351 [dict:text] ; its stop and target are used here because you set none.
- `C?` L329 [dict:text] ; the loss at that stop is {…} (gross)

**services/copilot_visual/payload.py** — 5 to review, 0 identifier/key/comparison (keep)

- `C?` L24 [assign:CAVEAT_TAIL] Ideas to review, not recommendations; nothing is sent to a broker.
- `K-tok?` L25 [Tuple] entry
- `K-tok?` L25 [Tuple] stop
- `K-tok?` L25 [Tuple] target
- `C?` L468 [assign:lines] : a visual dashboard built from the platform's own end-of-day data is shown above this answer. These figures are the tool data for this question. Explain what t

**services/copilot_visual/research_builders.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L732 [assign:gaps] Which FIIs entered or exited: FII holdings are reported only as a category total

**services/copilot_visual/research_intents.py** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L81 [assign:_MOVE] (?:increas\w*\|decreas\w*\|ris(?:e\|en\|es\|ing)\|fall(?:en\|ing\|s)?\|fell\|declin\w*\|drop\w*\|up\|down\|chang\w*\|trend\w*\|over\s+time\|history\|accumulat\w
- `C?` L84 [call:re.compile] \b{…}\s+(?:holding\|holdings\|stake\|shareholding\|ownership\|share\|exposure)\b\|\b(?:holding\|stake\|shareholding\|ownership)\s+(?:of\|by)\s+(?:the\s+)?{…}\b\

**services/copilot_visual/screen_builders.py** — 1 to review, 0 identifier/key/comparison (keep)

- `C?` L163 [call:block] {…} These are stocks that match the rules above, not recommendations. A stock with no value for a metric shows — and cannot pass a rule on it. The Screener page

**services/suggestions/catalog.py** — 15 to review, 0 identifier/key/comparison (keep)

- `C?` L35 [dict:footer] About your own trade's levels and limits. It does not tell you to exit or hold.
- `C?` L90 [dict:query] Should I book profits or hold {symbol}?
- `C?` L173 [dict:why] {subject} is {current} of your holdings, above the {target} ceiling the portfolio checks use.
- `C?` L179 [dict:why] {subject} manages {current} of your holdings, above the {target} guardrail.
- `C?` L191 [dict:why] Debt is {current} of your holdings; the portfolio checks look for {target}.
- `C?` L205 [dict:name] A trade near its stop
- `C?` L209 [dict:title] {symbol} is near its stop-loss
- `C?` L209 [dict:why] Last close {last} on {date}; stop {level_price}, {distance} away.
- `C?` L210 [dict:description] An open paper trade has used at least 70% of the distance from its entry to its stop.
- `C?` L211 [dict:name] A trade near its target
- `C?` L215 [dict:title] {symbol} is near its target
- `C?` L215 [dict:why] Last close {last} on {date}; target {level_price}, {distance} away.
- `C?` L216 [dict:description] An open paper trade has covered at least 80% of the distance from its entry to its target.
- `K-tok?` L208 [dict:level] stop
- `K-tok?` L214 [dict:level] target

**services/suggestions/engine.py** — 2 to review, 0 identifier/key/comparison (keep)

- `C?` L90 [assign:text] {…}: the newest data is from {…}, older than the previous session ({…}). Nothing is suggested from it today.
- `C?` L95 [dict:text] {…} could not be read just now{…}. Nothing is suggested from it.

**services/suggestions/inputs.py** — 1 to review, 4 identifier/key/comparison (keep)

- `K-tok?` L284 [call:(sim or {}).get] exit

**services/suggestions/rules.py** — 3 to review, 3 identifier/key/comparison (keep)

- `K-tok?` L153 [call:rule['params'].get] stop
- `K-tok?` L159 [call:t.get] exited
- `K-tok?` L142 [call:t.get] exited
