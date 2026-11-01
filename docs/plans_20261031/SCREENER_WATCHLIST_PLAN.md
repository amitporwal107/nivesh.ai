# Screener and Watchlists in the Copilot: menu items, and "screen, then add to a watchlist" in chat

Date: 31 Oct 2026, facts refreshed 1 Nov 2026 · Status: PLAN. Nothing below is built. · Basis: code on `origin/dev` (read at `0e73741f`, re-checked at `13f4ac9d`; PRs #430, #431,
#432, #437 merged; #435 and #436 open, they touch the open-trades and daily-review answers, not these screens); data read from the staging Mongo and warehouse on 31 Oct 2026 (read-only). The Screener, Watchlist, rail and desk-nav files are
unchanged between `25c61610` and `0e73741f` (VERIFIED: `git diff --stat` over them is empty).

Owner asks (28 and 31 Oct): "Plan ... the Screener/Watchlist menu/view item"; screen, then add to a watchlist, from the Copilot chat.

Note on the shared checkout: `/home/deploy/nivesh.ai` has uncommitted edits to `backend/routes/screeners.py`,
`frontend-v5/.../screens/Screener.tsx` and `markets/screener-run.ts`. I diffed each against `origin/dev`: 0 differing lines (VERIFIED with
`git show origin/dev:<file> | diff - <file>`), so they are dev's own newer code. Everything below is read from `origin/dev`.

## 1. In plain words

Most of what you want already exists, in pieces. There is a Screener page (filters, results table, "keep this screen as a watchlist"). There
is a Watchlists page with eight kinds of list, one of which, "My lists", is yours to fill by hand. What is missing is the bridge: **no
screen result can be put into "My lists"**, and the chat cannot screen or touch a watchlist at all (VERIFIED: no watchlist wording in the
chat's intent patterns; "Screen large cap stocks with ROE over 20" and "Add these to my watchlist" both match no visual-answer intent when run
through the deployed `resolve_intent`).

**Recommendation.** Build it in five small steps, each useful alone: (1) two menu rows for Trader mode, (2) a safe "add many" call on the
server, (3) "Add to a list" on the Screener page, (4) screening in chat, (5) "add these to my list" in chat with a confirmation card. The chat
never writes by itself: it shows what it understood and what it would add, and the write happens only when you press the button, from your
own browser session. The LLM only turns your sentence into filter rules; the real screener runs them.

## 2. Inventory: what exists today (VERIFIED by reading code unless marked)

**Menu entries per mode** (`frontend-v5/src/pages/CopilotApp/lib/views.ts`):

| Mode | Screener | Watchlists |
|---|---|---|
| Investor | tools: "Screener" → `tool/screener` | workspace: "Watchlist & alerts" → `page/watchlist` |
| Advisor | tools: "Screener" → `tool/screener` | workspace: "Watchlist & alerts" → `page/watchlist` |
| Trader | **no rail row.** The rail lists only "Smart trading desk" (owner decision 27 Oct 16:30, comment at `TRADER_RAIL_TOOLS`); `tool/screener` redirects to `trader/desk?tab=market&view=screener` (`TRADER_TOOL_TO_DESK` in `tradingdesk/desk-nav.ts`) | **no rail row** (workspace shows Settings only); reachable at `trader/desk?tab=trade&view=watchlists` |

Both desk views host the same screens: Market Desk › Screener renders `screens/Screener.tsx` (`tabs/market-desk/MarketDesk.tsx`), Trade Desk ›
Watchlists renders `screens/Watchlist.tsx` (`TradingDesk.tsx`, case `watchlists`).

**Screener page** (`screens/Screener.tsx`, `markets/screener-run.ts`, `screener/{catalog.ts,ResultsTable.tsx,StockPanel.tsx}`):
rule rows over 71 chat primitives plus 4 mutual-fund metrics (fund metrics cover Nifty 500 only), size bucket, templates; runs
`POST /api/screeners/run` (`backend/routes/screeners.py`), read-only, up to 50 rules, 500 rows back, whole day read from
`nidp.stock_features_daily` (page cap 5,000), coverage count per rule, `as_of_date`, "empty result says why". Four-lens results table, row opens
the stock panel, Kite LTP while the feed is live. **"Save as a watchlist"** (`workspace/SaveAsWatchlist.tsx`) saves the *rules* (`POST
/api/screeners`, Mongo `saved_screeners`, 1 document on staging) so the screen re-runs each day. It does not store the stocks.

**Watchlist page** (`screens/Watchlist.tsx`, left list, choice kept in `?wl=`): eight entries.

| List | Source | Store | Writable by the user |
|---|---|---|---|
| Results This Week | `/api/desk/results-week` | computed | no |
| AI scanner watchlist | `GET /api/desk/ai-watchlist` (`routes/ai_watchlist.py`), Top 10 cash + Top 10 F&O per day | Mongo `ai_watchlist_days`: 5 days on staging (2026-10-26 to 30) | no (job writes) |
| My lists | `routes/watchlists.py` | Mongo `user_watchlists` (1 doc), `user_watchlist_state` (1 doc) | **yes**: create, rename, delete, add, remove; max 20 lists × 100 stocks; name unique per user, case-folded |
| Research watchlist | `/api/public/research-watchlist` (no auth) | Mongo `research_watchlist_picks` (110 docs) | no |
| Saved screens | `/api/screeners` + `/api/strategy-builder/strategies` | `saved_screeners`; Postgres strategies | delete only |
| Price levels to watch | `GET /api/positional/watchlist` | computed | no |
| Filing alerts | settings | settings | yes (choices) |

Price or volume alerts have no store or job (stated in `Watchlist.tsx`); this plan does not change that.

**Write safety already in `routes/watchlists.py`:** every route scoped to the signed-in user, a list that is not yours answers 404
(`_owned`); `POST /watchlists/{id}/symbols` is idempotent (already there → `added:false, reason:already_in_list`, not an error), guarded
atomically against the 100 cap, and refuses a symbol the instrument master does not know (`_company_name`: 422, or 503 if the master does not
answer). CSRF: `middleware.py` `CsrfProtectMiddleware` rejects any cookie-authenticated POST/PUT/PATCH/DELETE to `/api` whose `Origin` is not on the
allowlist (the session cookie is `SameSite=None`, so this check is the defence). **Gap found:** the starter-list route refuses when an
advisor is viewing a client (`_active_profile_id`, "would write into the client's account unasked"), but `add_symbol`, `create`, `rename`,
`delete` do not. Under impersonation `get_current_user` sets `user["user_id"]` to the client's id (`deps.py`), so an advisor's click writes into the
client's list. Today's only caller is the Watchlist page.

**Chat today:**
- Legacy path: the recommendation node parses a screen sentence with a regex DSL, `_parse_screen_filters`
  (`backend/nidp/services/copilot_agent/nodes/recommendation.py`, "forward phrasing only"). It claims matched phrases and **ignores the rest
  without telling the user** (verified in the code; `screener/catalog.ts` documents the same risk). It returns the `stock_screener` widget
  (`ChatWidget.tsx`) with its own table. `ScreenerQueryBuilder.tsx` and the composer compile sentences the parser knows.
- Visual-answer engine (`services/copilot_visual/*`; contract `docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md`): the server builds a
  validated payload from existing services, the LLM only explains the figures. 16 intents on dev (`INTENTS` in `intents.py`, now including
  `sector_rotation`, `results_calendar`, `event_intelligence`). Blocks: `kpis candles bars heatmap quadrant ranked trade_plan list notice briefs`.
  A `ranked` row can ask a follow-up (`ask`) or open a plan or a stock dialog. A `notice` can carry `actions`, but only the navigation kinds
  `kite_login`, `connect_broker`, `set_risk_profile`, `open_market_intel` (`NOTICE_ACTIONS` in `payload.py`; `Simple.tsx` maps them to `go()` or a
  login). **There is no write action and no confirmation pattern.** `links.py` is the one precedent for letting a payload carry something the
  user can click: https-only, allow-listed exchange hosts, repeated in `schema.ts`, so a forged payload cannot point elsewhere; a write action
  needs the same two-sided check. An unknown block type renders a "not supported yet" note (`VisualAnswer.tsx`), so an old frontend degrades safely.
- Adding an intent has a fixed checklist (traps in the agent brief, #2): `INTENTS`, `AGENT_FOR`, `BUILDERS`, `payload.validate`, a suggestions
  `QUERY_TEMPLATE` (`test_sg_t1b`), the spec's `INTENTS` list, and a real staging capture of the payload in
  `frontend-v5/e2e/fixtures/contract-visual-answer.json` (`test_c2`).

## 3. Gaps

1. Trader mode has no Screener or Watchlist menu row.
2. No way to put a screen's stocks into "My lists" (only the rules can be kept).
3. The chat cannot run a screen with a visible interpretation, cannot write, and has no confirmation pattern for a write.
4. The screen logic lives inside the route function `run_screener`; the chat would have to call the route or copy it.
5. The regex parser drops what it does not understand, silently.
6. List writes are unguarded under advisor impersonation; there is no bulk add (100 stocks = 100 calls, each with an instrument-master look-up).

## 4. Design

**Menu.** Trader rail gets two rows, "Screener" → `trader/desk?tab=market&view=screener` and "Watchlists" →
`trader/desk?tab=trade&view=watchlists` (deep links already work; UNVERIFIED: how the rail marks the active row when `view` carries a query,
to be tested in slice W1). Investor and Advisor keep what they have.

**Screener page.** A checkbox on each result row (select all, up to 100), and a bar "Add N to a list": a list picker (your lists, or "New
list…" with a name), the exact count, then a confirm button; afterwards "Added 9, 3 were already there". The existing "Save as a watchlist" is
renamed on screen to "Keep this screen (re-runs daily)" so the two meanings stay apart: *keep the rules* vs *add these stocks, a fixed snapshot*.

**Server.** Move the body of `run_screener` into `services/screener_run.py` (pure move; `tests/test_screeners_run.py`, 425 lines, must stay green).
Add `POST /api/watchlists/{id}/symbols/bulk` `{symbols:[≤100]}` → `{added[], already[], refused[{symbol, code}], watchlist}`: one guarded `$push
$each`, instrument-master look-ups batched (8 at a time, the module's `_STORED_CONCURRENCY`), idempotent, owner-scoped, 403 `viewing_a_client`
under impersonation (and the same guard on the other list writes).

**Chat, screen.** New visual intent `screen_stocks`: a `ranked` block (≤25 rows shown, "N matched" KPI, coverage notice, data date) built by
calling `services/screener_run`. The first line always states the interpretation: "I read this as: ROE over 20, debt to equity under 0.5, large
cap" with an "Open in Screener" link that loads the same rules into the page.

**Natural language → spec.** The spec is exactly `ScreenRunRequest` (`conditions[{key, op, value}]`, `bucket`, `sector`, `limit`). Order: (1) try the
deterministic regex parser; if it consumed every number and keyword, use it. (2) Otherwise one LLM call through `make_chat_llm` with a forced tool
call returning `{conditions, bucket, sector, unparsed[]}` (not `run_agent_oneshot`, which returns a stub that looks like an answer when no key is set,
per the 28 Oct review). (3) The server validates with the same pydantic model, checks every `key` against the catalog, bounds `value`, and drops
nothing silently: words it could not map are printed as "Not used: …". The LLM never sees results and cannot run anything.

**Chat, write.** The `screen_stocks` payload carries a new block `watchlist_add` `{symbols[], source:{screen_in_words, as_of}, default_list}`.
The frontend renders a confirmation card (list picker, count, first names, "Add 12 stocks"). Pressing it calls the bulk route from the browser with
the user's session. The chat server never writes; the model never calls the route. A phrase like "add them to Tech" only makes the card appear
(pre-filled), it does not write. Old frontends show "not supported yet".

**Data freshness and wording.** Results carry `as_of_date`; older than the previous NSE session gets the stale notice (rule in memory
`no-stale-market-data`). Say "stocks that match your filters", never "picks" or "best"; a list is "your own note of stocks to follow, not advice"
(wording already in `PersonalLists.tsx`).

**Mobile.** Chat rows become cards by the existing rule (560 px + 110 px per column beyond seven); the confirmation card is one column, native
`<select>`, buttons at least 44 px high; checkboxes on the Screener cards. Check at 360 px.

## 5. Slices (each ships alone, in this order)

| # | Slice | Acceptance criteria | Depends on | Size | Who verifies what |
|---|---|---|---|---|---|
| W1 | Trader rail rows Screener and Watchlists | Rows show in Trader mode; each opens the right desk view; the active row highlights; phone drawer shows them; other modes unchanged | decision D1 | S | Eng: `views` unit + Playwright rail spec. Owner: look at it on staging |
| W2 | Server: extract `screener_run`, bulk add, impersonation guard | `test_screeners_run.py` unchanged and green; bulk: 100 symbols in one call, repeat call adds 0, 101st refused, unknown symbol in `refused`, another user's list 404, advisor-on-client 403, master down → 503 and nothing added | none | M | Eng: pytest. QA: real staging call with a throwaway list, deleted after (the user's own test account) |
| W3 | Screener page "Add to a list" | Select rows → picker → confirm → result line; works for a new list; 100 cap explained; label rename; mobile cards; no write without the confirm press | W2 | M | Eng: `copilot-app-screener.spec.ts` + new spec. QA: real run on staging, screenshot read at 360 px and desktop |
| W4 | Chat `screen_stocks` intent, read-only | "Screen large cap stocks with ROE over 20 and debt to equity under 0.5" → interpretation line, N matched, ≤25 rows, data date, "Open in Screener"; the deterministic parser only; every dropped phrase is printed | W2 (service) | M | Eng: `test_copilot_visual.py` (+ `test_c2` capture, `test_sg_t1b` template, spec INTENTS). QA: probe over staging data; compare count with the page's count for the same rules |
| W5 | Chat `watchlist_add` block with confirmation | Card appears under W4's answer; confirm writes via the bulk route; cancel writes nothing; double press adds nothing twice; refusal and error texts shown | W3, W4 | M | Eng: schema + contract + Playwright (mock) ; QA: real add on staging, then remove the throwaway list |
| W6 | LLM translation fallback | A 30-sentence golden set (incl. Hinglish and sloppy phrasing): every spec validates, none uses a key outside the catalog, "Not used" lists the rest; with the LLM down the answer says so and offers the page | W4 | M | Eng: golden-set test with a stubbed model. QA: 10 real sentences once on staging (provider quota: be economical) |
| W7 | Chat follow-ups: "show my list X", "keep this screen as Y" | Read-only list view as a `ranked` block with quotes; "keep" opens a confirm card that calls `POST /api/screeners` | W5 | S | Eng + QA as above |

## 6. Decisions needed from the owner

1. **What is the "menu/view item"?** (a) Two Trader rail rows pointing at the existing desk views; Investor and Advisor unchanged (recommended: smallest, matches what you have). (b) One new combined "Screener & Watchlists" view: a new screen, so a new design from you and more to keep consistent. (c) No menu change, chat only. Cost of (a): reverses part of your 27 Oct "rail lists only the Smart trading desk" decision, for two rows.
2. **May the chat add to a list at all?** (a) Yes, with the confirmation card (recommended). (b) Chat only screens and links to the page, where the Add button is. Cost of (b): one more click, no write risk from chat.
3. **Where do "added" stocks go and how many?** Recommended: your choice of list or a new list named "Screen · <rules> · <date>"; at most 100 per list (existing limit), more than 100 matches → the card says "the first 100 by market cap". Alternative: raise the limit (changes `MAX_SYMBOLS` and the quote load of every list read).
4. **LLM translation: allowed and how much?** Recommended: deterministic parser first, LLM only when it leaves words unmapped, 20 translations a user per day. The provider is chosen per call by `llm_provider()` (`nidp/services/copilot_agent/_llm.py`: claude_code, groq or OpenAI); the coordinator reports staging chat now runs on Groq's free endpoint (UNVERIFIED by me, I did not read the staging environment). That ends the shared 5-hour Claude limit but brings Groq's own rate limits and a weaker model, so translation accuracy must be measured (W6 golden set) before it is relied on. Without the LLM, anything but the exact phrasing fails.
5. **Advisor mode.** Block list writes while viewing a client (recommended, matches the starter-list rule), or allow the advisor to manage the client's lists (then say so on screen).
6. **Fund-house metrics in chat screens?** They exist on the page only (Nifty 500 coverage). Recommended: off in chat until asked by name; chat would otherwise silently screen a smaller universe.

## 7. Risks

- **SEBI wording.** A screen is a filter. Use "match your filters"; no "top", "best", "buy". A list is the user's own note. The chat's LLM explains only from the payload's facts.
- **Data freshness.** `stock_features_daily` is a daily table; show its date on every answer. A stale day gets the stale notice. A run where the source did not answer (`ok:false`) is a failure, never "0 matches".
- **Cost.** Each LLM translation uses the chat provider's quota (Groq free tier on staging per the coordinator, rate limits not checked; or the shared Claude login if the provider is switched back). Screen runs read a day's table (up to 5,000 rows) per call: cache per rule set and day if it shows up in logs (UNVERIFIED: latency of a run under load, not measured).
- **Security.** Writes only from the browser with the user's session; Origin check applies; ownership 404; symbols validated server-side; no secrets involved. Prompt injection cannot reach a write because the model returns only a rule spec and never holds a write tool. Impersonation guard (gap above). Watchlist contents feed the Smart Suggestions inputs (`services/suggestions/inputs.py` reads `user_watchlists`), so adds change what the user is suggested: mention on the card.
- **Deploy order.** New block types need the frontend image rebuilt and the backend restarted (memory `staging-deploy-timing-trap`); an old frontend shows "not supported yet", it does not break.

## 8. What I would NOT build

Price or volume alerts on lists; auto-adding the AI scanner's picks to a user's list; a second screener engine for chat; a screen that places or suggests orders; scheduled "email me this screen"; a chat command that deletes lists or stocks (remove stays on the page); sharing lists between users; any write the model can trigger without a button press.

## 9. Not verified

Rail highlighting with a query in `view` (W1 tests it); screen-run latency under load; whether the instrument master (`nidp.sector_master`, sparse per memory `staging-warehouse-price-quirks`) refuses many symbols that a screen returns (W2 measures: count `refused` on a real 100-row run before W3); LLM translation accuracy (W6's golden set is the first measurement).

Commands run for this plan (read-only): `git show origin/dev:<file> | diff - <file>` for the three files; `docker exec nivesh-staging-app-backend` with
`resolve_intent` on seven sentences, and Mongo `estimated_document_count` on `saved_screeners`, `user_watchlists`, `user_watchlist_state`,
`ai_watchlist_days`, `research_watchlist_picks`.
