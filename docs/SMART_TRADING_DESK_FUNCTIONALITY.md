# Smart Trading Desk — functionality reference

**Status:** a description of what the desk does at the code on `dev` on 2026-10-20 (merge `ec335270`), read from the source. It is not a specification: the requirement is the PRD (`docs/smart_trader`). Where the code could not confirm a point, the text says "unverified".

**Rules the desk follows everywhere**
- **Real data only.** Every figure comes from an existing route or table. Where a source does not exist the slot stays and shows "—" with the reason; nothing is estimated or filled in.
- **Read-only.** The desk never places, changes or cancels an order. The only writes are the user's own paper trades, price/event alerts, and a confirmed portfolio import.
- **Dates and sources beside data.** Each card carries a trust line: source, end-of-day or live, as-of, who made the figure (as reported, rules, model, AI) and the method or version.
- **Missing is not zero.** Missing data is null and shown as "—".
- **Probabilities are not scores.** A rules-based score, a model rank and a model probability are labelled as different things.

## The desk at a glance

| Tab | What it is for |
|---|---|
| 01 Overview | Market indices and breadth, the market regime, sector strength, top opportunities, key events, portfolio snapshot and risk summary |
| 02 AI Scanner | Ranked, explainable list of stocks by setup, with categories, filters, liquidity and risk, and the universe it was drawn from |
| 03 Market Intelligence | Filings, SEBI circulars, FII/DII and bulk/block deals as one event list with source labels, impact and alerts |
| 04 Chart Analysis | Daily chart with indicators and patterns, a ten-section opportunity detail, and the Risk desk with a scenario calculator |
| 05 Portfolio & Risk | Consolidated read-only portfolio across connected brokers and imports, ten risk rows, paper trades |
| 06 More | AI Copilot, Options & Futures Lab, Watchlists, Saved analyses, Paper trading, Settings & integrations |

A Trader / Investor switch changes the wording (not the data). On phones the tabs are a bottom bar. A Copilot dock answers questions in the desk's persona.

## Contents
- **Part 1** — Frame, Copilot dock, Overview, AI Scanner
- **Part 2** — Chart Analysis, opportunity detail, Risk desk and calculator, Market Intelligence
- **Part 3** — Portfolio & Risk, broker block, import, paper trading, Options & Futures Lab
- **Part 4** — API routes, data sources, jobs and engines, settings, security, limitations
- **Consolidated open points**

---

# Smart Trading Desk: functionality documentation, part 1

Covers the desk frame (A), the Copilot dock (B), the Overview tab (C) and the AI Scanner tab (D).

Code read: `/home/deploy/nivesh-fix-bse` (snapshot of origin/dev). Frontend root: `frontend-v5/src/pages/CopilotApp/` (abbreviated `CA/` below). Desk shell: `CA/screens/TradingDesk.tsx`. Tab code: `CA/screens/tradingdesk/`. Backend root: `backend/`.

Convention: "verified" means read in code in this snapshot. Nothing here was run against staging or production, so no live figure is quoted. "Unverified" marks anything the code does not settle. Line numbers are from this snapshot.

---

## A. The desk frame

The desk is the app view `trader/desk` (`CA/lib/views.ts:54`, label "Smart trading desk", tag "AI"). It is listed under the Trader tools. Its URL is `/app/trader/desk` plus query parameters.

### A1. Layouts and breakpoints

| Layout | Condition | Source |
|---|---|---|
| Phone | viewport under 700px (`mobile`) | `CA/index.tsx:69` |
| Desktop, Copilot not docked | 700px to 1399px | `CA/index.tsx:73` (`wide` = width of 1400px or more) |
| Desktop, Copilot docked right | 1400px or more | `TradingDesk.tsx:317` (`docked = wide`) |

Docked desktop is max 1480px wide and the tab area sits beside a 384px Copilot column (`TradingDesk.tsx:533,557`). Otherwise max width is 1180px. When docked, the right column is sticky and shows a note "Copilot docked right" beside the tab row (`:551`).

The app shell hides its own ask box wherever the desk has its own Copilot, so there is never a second ask box (`CA/index.tsx:135-144`):

- docked desktop;
- any desk view on a phone;
- an undocked desktop on `?tab=more`.

### A2. Header search (desktop top bar; phone behind a magnifier button)

What the user sees: a rounded box, placeholder "Search a stock or ask Nivesh…", an "ENTER" hint badge, and the aria label "Search any NSE stock by symbol, or ask Nivesh" (`TradingDesk.tsx:105-127`). On a phone the search is hidden until the magnifier button (aria "Search a stock or ask Nivesh") is tapped. The box then opens focused. It stays open after a submit (`searchOpen` is never reset by a submit).

Pressing Enter with non-empty text clears the box and runs `onSearch` (`:402-416`). The rule, in order:

| Step | Test on the trimmed text | Result |
|---|---|---|
| 1 | Matches a scanner stock (`matchSetup`, `:94-101`): one word, up to 20 chars, no whitespace. Exact symbol match first. Otherwise, if 2 or more chars, the best-ranked scanner symbol that starts with the text. | Sets `?sym=` to that stock. The tab does not change. A status line "SYMBOL selected  Chart ›" appears (`Picked`, `:179-186`). "Chart ›" opens the Chart tab for it. |
| 2 | Not a scanner stock, but matches `^[A-Za-z0-9&-]{1,20}$` (`SYMBOL_TOKEN`, `:88`) | If the current view is the Chart tab (not More): sets `?sym=` and stays. Anywhere else: opens the Chart tab with `?sym=` (`openChart`). The Chart tab can load any NSE symbol. The "selected" line is cleared. |
| 3 | Anything else (several words, punctuation such as "?", or over 20 chars) | Sent to the desk Copilot as a question (`askDesk`). The "selected" line is cleared. |

Facts that follow from the rule:

- A single word with no punctuation is always treated as a symbol, even if the user meant a question. For example, "why" opens the Chart tab with `?sym=WHY`. Only multi-word text or text with punctuation reaches the Copilot.
- "Scanner stock" means a setup in the merged watchlist and picks list (`useDeskScanner`, routes `GET /api/positional/watchlist` and `/picks`, both limit 30). If that read has not loaded, step 1 never matches and a typed symbol goes to step 2.
- The "selected" line is local state. It stays until the next search or a reload. It is not cleared by switching tabs.
- If the Copilot is mid-answer, a question sent from search is silently dropped (`CopilotDock.tsx:150`: `if (!q || engine.busy) return`).
- If the dock is not mounted (undocked desktop on a non-More tab, or a phone off More), the question is stored and the view moves to `?tab=more`. The page-height Copilot sends it once it mounts (`:339-355`).

### A3. Trader / Investor switch

Desktop: a two-button group "TRADER" / "INVESTOR" with `aria-pressed` (`PersonaSwitch`, `:129-153`). Tooltips are "Technical wording" and "Plain wording". Phone: one pill in the title block that shows the current persona and toggles on tap (aria "Wording: trader. Switch to investor", `:498-509`).

What it changes (verified in code): wording only. The data and the routes called are the same (`context.tsx:29-33`: "the data is the same"). It does not change the app mode (Investor/Trader/Advisor in the shell). It is stored in the URL as `?persona=investor`. Trader is the default and drops the parameter.

Where the persona changes visible text:

- **Overview**
  - the headline and intro paragraph;
  - the regime explanation sentence;
  - the evidence row labels;
  - the headings "Supporting evidence" / "What the rule looked at" and "Invalidation" / "What would change this";
  - the Top opportunities field labels, setup names, and "Against" / "What could go wrong".
- **Scanner**
  - category names;
  - column and field labels;
  - liquidity words;
  - the footnote;
  - the "Open analysis" / "See the chart" button;
  - the rank-by labels.
- **Copilot dock**
  - the persona is sent with every question and, for "investor", the model is told to use plain wording (B2).
- **Other tabs**
  - They read `persona` from the same context. Their wording is covered in the other parts.

The investor wording differences for the cards in C and D are given inline below, marked "Investor:".

### A4. Market-status pill (desktop top bar)

Text format: `{label}{ · holiday name} · {HH:MM} IST` (`StatusPill`, `:156-176`). The clock refreshes every 30 seconds (`useNow`). The tooltip is the `why` string. Dot colour and tone follow `feed`: live is mint, delayed is amber, anything else is neutral.

Logic (`overview-data.ts:595-632`, `marketStatus`) with the data from `GET /api/markets/home` (`market_state`, `is_live`, `session`):

| Situation | Label | feed | Tooltip says |
|---|---|---|---|
| Response says closed, reason "holiday" | "NSE holiday" (plus ` · <holiday name>`) | closed | "NSE holiday: <name> (NSE holiday list, GET /api/markets/home)" |
| Closed, weekend or outside hours | "Market closed" | closed | "Weekend" or "Outside NSE hours (Mon–Fri 09:15–15:30 IST), per GET /api/markets/home"; adds "The NSE holiday list could not be read, so the status follows the clock." when the calendar was not read |
| Open, holiday list read (`session.calendar == "ok"`) and `is_live` true | "Market open" | live | "Inside NSE hours; the index tape is the live feed … Today is not an NSE holiday" |
| Open, holiday list read, `is_live` false | "Market open" | delayed | "Inside NSE hours; quotes are delayed" |
| Open, holiday list NOT read | "NSE hours" (never "Market open") | live or delayed as above | the list-unread explanation |
| `/api/markets/home` not loaded or failed | "NSE hours" or "Market closed" from the browser clock (Mon–Fri 09:15–15:30 IST, `inNseHours`) | clock | "Read from this device's clock … Exchange holidays are not checked." |

Backend (`routes/markets.py:210-285`): `session_state()` marks the market open only on a weekday that is not an NSE cash-market holiday, between 09:15 and 15:30 IST inclusive. The holiday list comes from the data platform (`GET /holidays?segment=CM`, table `nidp.nse_holidays`). A holiday answer is cached 6 hours and a failed read 2 minutes. Special sessions (for example Muhurat trading) are not in the list, so they read as closed or holiday. `is_live` is `(dash.is_live or live.is_live) and session.state == "open"`.

Freshness: the app refetches `/api/markets/home` every 60 seconds (`hooks/use-markets.ts:12-19`). The server caches it 30s during hours and 300s otherwise (`routes/markets.py:36-38,324`). The phone has no header pill. The Overview's phone status line carries the same logic (C1).

### A5. The six tabs and their order

Desktop tab row, left to right (`TradingDesk.tsx:73-79,545-550`; order from PRD §3.1). Each chip is numbered:

| # | Chip label | `?tab=` | Component |
|---|---|---|---|
| 01 | Overview | `overview` | `OverviewTab` |
| 02 | AI Scanner | `scanner` | `ScannerTab` |
| 03 | Market Intelligence | `intel` | `IntelTab` |
| 04 | Chart Analysis | `chart` | `ChartTab` |
| 05 | Portfolio & Risk | `portfolio` | `PortfolioTab` |
| 06 | More | `more` | the More menu (A6) |

`DESK_TABS` also holds `fno` (Options & Futures Lab). It has no chip of its own and is reached from More. `DESK_TABS` is declared in a different order (`context.tsx:16`: overview, scanner, chart, intel, portfolio, fno); that is not the display order.

Tabs are lazy-loaded. While loading, the panel shows "Loading <tab name>" with 4 skeleton rows. Each tab is wrapped in `SafeWidget`, so a crash in one tab shows that widget's fallback instead of breaking the desk. The text of `SafeWidget`'s fallback was not read: unverified.

### A6. The More menu and its destinations

Reached from the "06 More" chip, the bottom-bar "More" item, `?tab=more`, or `?tab=fno` (which keeps More highlighted). Listed destinations (`MORE`, `:217-224`), each a real view. A one-line text under the chips says "Learning and methodology: not in the app yet." There is no button for it because there is no view.

| Destination | Note shown | What it does |
|---|---|---|
| AI Copilot | "Ask about anything on the desk, with sources" (docked: "Docked at the right of the desk. …") | Docked desktop: focuses the dock's input. Otherwise: opens `?tab=more`, which shows the Copilot at page height (`CopilotDock` variant "page", height `calc(100dvh - 250px)`). |
| Options & futures lab | "NSE F&O: open interest, build-up and option chains (end of day)" | `?tab=fno`. Covered in another part. |
| Watchlists | "Your watchlists and price alerts" | Leaves the desk: app view `page/watchlist`. |
| Saved analyses | "Copilot threads, screens and questions you kept" | Leaves the desk: `page/saved`. |
| Paper trading | "Your paper trades: predicted against actual" | Opens the Portfolio & Risk tab, then scrolls to the paper-trade card (`[data-testid="desk-portfolio-record"]`), polling every 150ms for up to 40 tries (about 6 seconds). If the card never renders it stays at the top of the tab. |
| Settings & integrations | "Broker connections (read-only) and statement imports" | Leaves the desk: `page/brokers`. |

Two presentations:

- With the Copilot docked, More shows a card "06 · More" with the destinations as a list (`MoreList`).
- On an undocked desktop or phone, More shows a scrolling row of destination chips at the top. The chip "AI Copilot" is highlighted when the page Copilot is showing, and "Options & futures lab" when `?tab=fno`. The body is the page-height Copilot, or the list.

### A7. Phone layout

Under 700px (`TradingDesk.tsx:472-523`):

- **Title block:** the "न" mark, "Nivesh Copilot", the small caption "AI SMART TRADING DESK", a search button, and the persona pill. There is no top tab row and no status pill.
- **Bottom bar** (`BottomBar.tsx`): fixed to the bottom above the safe area, 58px high, six items.
  - Order: Overview, Scanner, Intel, Chart, Portfolio, More.
  - Screen-reader names: "Overview", "AI Scanner", "Market Intelligence", "Chart Analysis", "Portfolio and Risk", and "More: AI Copilot, Options and futures lab, watchlists and settings".
  - Each is a real button; the current one has `aria-current="page"` and "(current)" in its label.
  - The bar highlights More for `?tab=more` and `?tab=fno`.
  - Content is padded so nothing hides under the bar.
- **Phone Copilot:** its ask box sits above the bar and lives only in More · AI Copilot (see B5).
- **Overview on a phone** is a separate, shorter layout (C10).
- **Scanner on a phone** shows compact cards (D8).

### A8. Footer

Shown on every tab and on the More list, except when the page-height Copilot is showing (`!pageCopilot`). Exact text (`:457-468`):

> DISCLAIMER — Scanner setups are end-of-day and rules-based. Probabilities are model outputs for the next session, not buy or sell recommendations. Broker connections are read-only; Nivesh does not place orders. 9 out of 10 individual traders in equity F&O incurred net losses (SEBI study).

The SEBI-study sentence is static text. Its source was not checked: unverified.

### A9. URL state

All desk state is in the query string and every change uses `replace`, so it adds no browser-history entries (`update`, `:328-337`).

| Param | Meaning | Parse rule |
|---|---|---|
| `tab` | overview, scanner, chart, intel, portfolio, fno, or more | An unknown or missing value shows Overview. `more` is handled separately from `DESK_TABS`. |
| `sym` | The selected stock | Uppercased, must match `^[A-Z0-9&-]{1,20}$`, else treated as none. Chart tab uses it, and so do dock chips. |
| `persona` | Wording | Only `investor` is recognised; anything else is trader. |
| Scanner params | `sc_cat`, `sc_rank`, `sc_liq`, `sc_sector`, `sc_cap`, `sc_pmin`, `sc_pmax`, `sc_rvol`, `sc_vol`, `sc_risk`, `sc_inst`, `sc_list` | D9. Other tabs may add their own parameters. |

Changing the tab copies all other existing parameters, so scanner filters survive a trip to another tab and back. The root element carries `data-tab`, `data-symbol` and `data-persona` attributes (for tests).

---

## B. The Copilot dock

Files: `CA/screens/tradingdesk/CopilotDock.tsx`; chips from `useDockChips` (`TradingDesk.tsx:283-306`); backend `backend/routes/chat.py:110-123,1469`; `backend/nidp/services/copilot_agent/persona_framing.py`.

### B1. Where it shows

| Place | Variant | Height |
|---|---|---|
| Docked desktop (1400px or more): right column, every tab | "dock": a card with header | `min(820px, calc(100dvh - 40px))`, min 420px |
| More · AI Copilot on an undocked desktop or a phone | "page": full width in the page | min `calc(100dvh - 250px)` |

The docked header reads "Nivesh Copilot", "06 · Conversational intelligence", and a pill "NIDP" (tooltip: "Answers read the Nivesh data platform (NIDP), the same data the desk shows").

### B2. What a question sends

It is the same Copilot engine as the rest of the app: `POST /api/chat/stream` through `useThreadEngine().send(question, sessionId, onSession, { persona, surface })` (`CopilotDock.tsx:148-156`). Two fields are specific to the desk:

- `persona`: the desk persona, `"trader"` or `"investor"`.
- `surface`: `"trading_desk"`.

Server handling (`routes/chat.py`):

- `_desk_persona_for(surface, persona)` (`:117-123`): returns None unless the surface string, lowercased and trimmed, equals `trading_desk`. This is an allowlist and no client text reaches the prompt. For that surface it returns `investor` or `trader`; any missing or unknown persona becomes `trader`.
- The result is passed into the agent state as `desk_persona` (`chat.py:1631`).
- `persona` has a second effect on the same request: `_advisor_mode_for` (`chat.py:~92-103`) treats `"investor"` or `"trader"` as "the advisor's own portfolio" for an advisor account. So an advisor using the desk Copilot is answered from their own holdings, not the client book.

The dock has its own thread. The thread id is kept in `sessionStorage` key `nv.copilot.desk.thread`, so it survives moving between tabs and screens in the same browser tab. It is lost when the browser tab closes. If storage is blocked (private window), the thread lasts only for the view.

### B3. Answer structure

`frame_for_persona(persona, desk_persona)` (`persona_framing.py:126-141`) adds an instruction block for desk questions. It is added in the system prompt of these answer nodes: market, goal, backtest, risk, recommendation, mf, stocks_insights, portfolio, stock. Whether any other agent node answers desk questions without it was not checked: unverified.

The instruction (`DESK_ANSWER_STRUCTURE`, `:102-118`) tells the model: where it applies, answer in this order, each part under a short bold label:

1. Direct answer, one or two sentences.
2. Evidence, the figures the tools returned, each with its source.
3. As of, the date or time of those figures. Say "end of day" or "delayed" where true, and never call a figure live unless the tool says it is.
4. Bullish factors and bearish factors.
5. Key uncertainties.
6. What would invalidate this view.
7. Sources, only those the tools returned.
8. Where to look, the desk tab with the underlying analysis (Overview, AI Scanner, Market Intelligence, Chart Analysis or Portfolio & Risk), naming the stock where there is one.

The same block also says:

- leave out a part with no data and say plainly when data is missing or stale;
- keep facts apart from interpretation;
- "a rules-based scanner score is not a probability";
- the move-odds probabilities are for the next session only;
- explain evidence and risk, do not tell the user to buy or sell, and Nivesh cannot place orders.

For `investor` it appends `DESK_PLAIN_WORDING`: avoid jargon, explain technical terms in a few words, prefer everyday phrases (for example "50-day average" rather than "SMA 50").

Limits: this is an instruction to a language model. The structure is not enforced, validated or templated in code, so a given answer can omit or reorder parts. The dock renders the streamed Markdown as received, styled with serif headings, mint emphasis and "›" bullets, and source links as small pills. If the answer carries a result card widget, the dock shows "This answer has a result card — open the full thread ›". It does not render the card.

### B4. Suggested-question chips

Up to 4 are shown (`chips.slice(0, 4)`). Duplicates are removed. They are disabled while an answer is streaming. The chip set depends on the tab (`useDockChips`). On More the Overview set is used. `sym` below is the selected stock, else the top-ranked scanner setup.

| Tab | Chips |
|---|---|
| Chart (when a symbol is known) | "Explain the {sym} setup and what would invalidate it"; "Size a trade in {sym} with 1% risk"; then the common one |
| Options & futures lab | "What does NIFTY option OI say about this expiry?"; "Which F&O stocks show long build-up today?"; then the common one |
| Portfolio & Risk | "What are the key risks in my portfolio this week?"; then the common one |
| Market Intelligence | "Summarise today's most important filings"; then the common one |
| Overview, Scanner, More and others | "Why does {top scanner symbol} rank first on the scanner?" (only if a setup exists); "Which sectors are leading today and why?"; then the common one |
| Common (always last) | "What are the key market risks this week?" |

On the Chart tab with no known symbol, the first two are omitted. The chips then fall back to the common one alone, because the Chart branch is only taken when a symbol is known. If the scanner has not loaded, `top` is empty and "Why does … rank first" is dropped.

### B5. States and controls

| State | What the user sees |
|---|---|
| Empty (no thread) | Heading "Ask about anything on the desk." and "Answers come from the same data the desk shows, with sources. The Copilot explains evidence and risk; it does not tell you to buy or sell, and it cannot place orders." |
| Loading saved thread | "Loading the conversation…" |
| Streaming, no text yet | Three pulsing dots and "Reading the desk…" |
| Streaming with text | The answer appears with a caret. A "■" stop button replaces send. |
| Stopped | Alert box "You stopped this answer." with "Retry ›" |
| Error | Alert box with the engine's error text, else "The Copilot could not finish this answer." with "Retry ›". Retry is hidden while busy. |
| Saved answer | Under it: "Educational research, not investment advice" |
| Has a thread | "Open the full thread ›" opens the app's normal thread view, with the evidence panel and any result card. |
| New conversation | "＋" clears the local thread and the stored id. It is disabled while busy, and (docked) when there is no thread. |

Input placeholders: docked "Ask about a stock, sector or your portfolio"; page "Ask Nivesh AI anything…". Send is disabled for empty text.

Phone ask box (page variant): the input is a pill, 44px high, in a sticky bar that sits above the bottom navigation (it offsets by `--desk-bottom-bar`). Under it is the static note "For education and research only. Not a buy or sell recommendation." The suggested questions appear above it, one per row, under "Suggested questions". The shell's ask box is hidden on every phone desk view, so the only way to ask on a phone is More · AI Copilot, or the header search (a multi-word question there moves the user to that screen).

Not available: voice input, file attachment, per-answer feedback, and rendering of result-card widgets inside the dock. None of these is present in `CopilotDock.tsx`.

---

## C. Overview tab

Files: `OverviewTab.tsx`, `overview-data.ts`, `trust.tsx`. Backend: `routes/markets.py`, `routes/macro.py`, `services/macro_engine.py`, `routes/markets_desk.py`, the data-platform router `nidp/services/daas_api/routers/desk_market.py`, `routes/positional.py`.

Every card ends with a one-line "trust line" (`trust.tsx`): source, then mode (Live, Delayed, End of day or Historical), as-of, maker ("As reported", "Rules-based", "Model output", "AI-generated"), method, and a "Stale" or "Source failed" prefix when set. Each block loads and fails on its own. A figure with no source shows "—" with a reason, never 0.

### C1. Layout and intro (desktop)

Order top to bottom (`OverviewTab.tsx:106-123`):

1. Intro: stamp, pills, headline, paragraph.
2. Index cards and breadth.
3. AI Market pulse (left, 7 parts) and Sector strength (right, 5 parts).
4. Top AI opportunities.
5. Key market events (left) and, stacked on the right, Portfolio snapshot and Risk summary.

The grid switches by the tab's own measured width (so the docked Copilot narrows it): `full` at 940px or more (four index cards plus breadth on one row, four pulse stat tiles); 560px or more gives four cards then breadth below; narrower gives two columns. The side-by-side cards need 640px or more, else they stack.

Intro (`Intro`, `:172-215`):

- **Stamp:** `{Wed} {14 Oct} · {HH:MM} IST` from the browser clock (30s refresh).
- **Feed pill:** "NSE · BSE live", "NSE · BSE delayed" or "NSE · BSE end of day", from `feedWords(status)` (`overview-data.ts`). The clock fallback says "delayed" if open, else "end of day". The tooltip is the status explanation.
- **Holiday pill:** "NSE holiday · {name}" when the calendar says so.
- **Static pills:** "Broker hub · read-only", "Paper trading on", "Live orders off". These are fixed text, not read from any setting (unverified that they reflect account state).
- **Paragraph:**
  - Trader: "Index tape, breadth, end-of-day setups, filings, your broker-read portfolio and F&O in one place. Every figure names its source and date."
  - Investor: "The market, ideas from an end-of-day rules-based scan, company filings and your portfolio in one place, in plain words. Every figure says where it came from and when."

Headline (`deskHeadline`, `overview-data.ts:670-`). Built only from real reads, and a part with no data is left out:

- **Breadth band** from the advancing share of `breadth` (`advances ÷ (advances + declines + unchanged) × 100`). Cut-offs are 60, 52, 48 and 40.

  | Advancing share | Trader word | Investor sentence (today / earlier day) |
  |---|---|---|
  | 60 or more | strong | Most stocks are rising today / Most stocks rose |
  | 52 up to 60 | positive | More stocks are rising than falling today / More stocks rose than fell |
  | 48 up to 52 | even | About as many stocks are rising as falling today / … rose as fell |
  | 40 up to 48 | soft | More stocks are falling than rising today / More stocks fell than rose |
  | under 40 | weak | Most stocks are falling today / Most stocks fell |

  - Trader: "Breadth is {word}" (today) or "Breadth was {word} on {date}".
  - "Today" holds only if the breadth's session day equals today in IST. For the live Nifty-50 fallback the day is taken as today. Otherwise the date is named.
- **Sector clause:**
  - It uses the best 1-day sector index return from `/api/markets/sector-returns`.
  - If positive: trader "and {sector} leads/led", investor ", led by {sector}".
  - If zero or negative: "and no sector index is up/rose" (investor: "and no sector is up/rose").
- **Setups sentence**, from the scanner merge (`useDeskScanner`):
  - Trader: "{n} of {total} setups have/has confirmed." with the count in italics.
  - Investor: "{n} ideas have confirmed, each with its evidence shown." or "No ideas have confirmed yet."
  - "Confirmed" means the setup's status is `confirmed` (bucket "Breakout confirmed", or a picks-only stock whose stage is BREAKOUT).
- **Fallback** with no data at all: "Your smart trading desk."

### C2. Index cards (four) and tape

Four tiles in fixed order: Nifty 50, Nifty Bank, Sensex, India VIX (`DESK_INDICES`, `overview-data.ts:451`). Each shows the level, the point and percent change, a sparkline labelled "DAILY CLOSES", and a stamp "{Live|Delayed|End of day} · {14 Oct, 11:32 IST}".

- **VIX tile:** its change is shown in neutral colour, because a rising VIX is not a gain. A tile missing from the response says "Not in the response".
- **Match rule:** by exact name, so "Nifty 50" never matches "Nifty 500". The VIX also matches by its `is_vix` flag.
- **Mode** (`indexMode`): "Live" only if `is_live` and the market state is open. "Delayed" if open but not live. "End of day" if closed.

Source (`GET /api/markets/home`, `routes/markets.py:314-`):

- The index tape is built from Yahoo Finance daily history (`nse_live.TAPE_INDICES`: ^NSEI, ^BSESN, ^NSEBANK, ^NSEMDCP50, ^CRSLDX, ^INDIAVIX). The value is the last daily close and the change is against the close before it. The sparkline is up to the last month of daily closes (`period="1mo"`).
- During hours, the four tiles Nifty 50, Sensex, Nifty Bank and India VIX are overlaid with the live snapshot's value and change. Whether the snapshot's own provider is Yahoo or NSE was not traced: unverified.
- The trust line reads "Yahoo Finance index quotes · {mode} · updated {fetched_at} · As reported · each line is the last N daily closes, not intraday".
- If the daily-history fetch fails, the route falls back to four tiles without sparklines.

| State | Text |
|---|---|
| Loading | "Loading the index tape" |
| Error | Card "Index levels and breadth didn't load" with retry |
| Cache | Server cache 30s in hours, 300s otherwise. The app refetches every 60s. |

### C3. Market breadth tile (desktop only as a tile; phone folds it into the pulse card)

Shows "{n}% advancing" (red under 50, mint otherwise), a bar sized by counts, advances, unchanged and declines, "A/D ratio" (advances ÷ declines, "—" with no declines), and a fixed line "A/D trend — no daily history on record" (tooltip: no route keeps a daily history of advance and decline counts). So the A/D trend is not available.

Counts and the stocks they cover (`routes/markets.py:190-232`, `market_dashboard.build`):

- **End-of-day count** (`universe_kind = "bhavcopy"`): every NSE stock with 21 or more daily bars in `stock_ohlcv` within the 80 days up to the session. Advance means the latest close is above the previous close; decline means below; the rest are unchanged. `unchanged` is `universe − advances − declines`, floored at 0. Scope line: "Across {n} NSE stocks in the end-of-day bhavcopy · {date}".
- **Live fallback** (`universe_kind = "nifty50_live"`), used only if the end-of-day count is missing: the Nifty 50 stocks with a delayed quote (`unchanged` comes from that snapshot). Scope line: "Across the {n} Nifty 50 stocks · delayed quotes".
- **Unknown kind:** the count is shown and the line says "The response does not say which stocks were counted"; nothing is guessed from the size.
- **Empty state:** "Advances and declines are not available right now." (when advances or declines is null, or the total is 0 or less).

Trust line: end-of-day source "NSE bhavcopy, end-of-day bars (stock_ohlcv)", as-of the response `as_of` date, rules-based, method "close above / below the previous close".

### C4. AI Market pulse and the five regimes

Card "01 · AI Market pulse". Header meta, when a regime exists: "Regime rule · {date} · end of day". Contents top to bottom:

1. Market regime block.
2. Supporting evidence.
3. Four small stat tiles: FII cash, DII cash, USD/INR, Crude oil.
4. A grid of Sector leadership, Important events, Potential risks, Invalidation.
5. Rules-based insight box.
6. A rule line.

Trust line: "Macro engine (macro_daily, macro_features) and end-of-day bars (stock_ohlcv) · End of day · {date} · Rules-based · regime rule {version}". A "Stale" prefix is shown when the regime is 2 or more days old.

**Source:** `GET /api/macro/today` (`routes/macro.py`). It is computed after the close (the ingestion note says 18:35 IST). The page caches it 10 minutes. It returns the macro snapshot and a `regime` object built from the same session by `macro_engine.classify_desk_regime`.

**The rule** (`services/macro_engine.py:827-1000`, rule version `desk-regime-v1`, thresholds in `DESK_REGIME_RULE` at `:835`). One end-of-day session. The route sends the thresholds with each answer and the card prints them from the response, so a changed threshold shows without a UI change.

| Threshold | Value in code |
|---|---|
| `vix_high` | 20.0 |
| `trend_average_sessions` | 50 |
| `breadth_up_pct` | 52.0 |
| `breadth_down_pct` | 48.0 |

Inputs:

- **Nifty 50 close and its 50-session average** (`macro_features.nifty_50dma`). The average is a simple average of the last 50 closes in `macro_daily`. It needs at least 60% of the window (30 of 50) present, else it is none (`_sma`, `:26-32`).
- **India VIX close** for the session.
- **Breadth for the same session** (`session_breadth`, SQL at `:858-875`): advances, declines and unchanged over stocks in `stock_ohlcv` with at least 21 daily bars in the 80 days to the session. Only stocks with a bar on that very session count, so a stock that did not trade is never counted as that day's move. Cached 10 minutes per session. Breadth from another date than the regime's session is not used.

Derived values:

- **Trend direction:** "up" if close is above the average, "down" if below, "flat" if equal. None if either is missing.
- **Breadth direction:** advancing share is `advances ÷ (advances + declines) × 100`. Up if the share is at least 52, down if at most 48, "even" strictly between. None if there are no movers.
- **VIX high:** `india_vix >= 20`.

Classification (`_regime_of`), in this order:

| Order | Condition | Regime (label) |
|---|---|---|
| 0 | No Nifty close or no 50-session average | None. The card shows "Not available". |
| 1 | VIX is 20 or more | High volatility |
| 2 | Trend is up or down AND breadth is up or down AND breadth is the opposite of trend | Mixed |
| 3 | Trend up | Bullish |
| 3 | Trend flat | Sideways |
| 3 | Trend down | Bearish |

Notes:

- Even breadth never causes "Mixed".
- An unknown VIX or unknown breadth skips that check, and the route lists the skipped check with its reason.
- The label order in the five-segment bar is Bearish, Sideways, Bullish, Mixed, High volatility (`DESK_REGIME_KEYS`). The active segment is coloured. The colour is never the only signal because the label is also printed.
- Tones: bearish and high volatility are red, sideways is neutral, bullish is mint, mixed is amber (`REGIME_TONE`).

Explanation sentence under the label (`regimeText`, written from the route's classification; the UI never classifies):

| Regime | Trader | Investor |
|---|---|---|
| High volatility | "India VIX closed at {vix}, at or above {20}, so volatility overrides the trend reading." | "Expected swings are large: India VIX, a gauge of expected volatility, closed at {vix}, at or above {20}. That outweighs the trend." |
| Mixed | "The Nifty 50 trend is {up/down} (close vs its {50}-day average) but breadth points {up/down}: the index and the broad market disagree." | "The Nifty 50 and the wider market are pointing different ways (the index is above/below its {50}-day average while most stocks fell/rose), so the picture is unclear." |
| Bullish | "The Nifty 50 closed above its {50}-day average; India VIX is under {20} and breadth does not disagree." | "The Nifty 50 is above its average of the last {50} sessions, so the broad trend is up, and the other checks do not contradict it." |
| Bearish | "… closed below … ; India VIX is under {20} and breadth does not disagree." | "… is below its average … so the broad trend is down …" |
| Sideways | "The Nifty 50 closed level with its {50}-day average." | "The Nifty 50 is level with its average of the last {50} sessions." |

Under the label the card also shows:

- a pill "Macro risk low/medium/high" (the macro engine's separate risk level, below);
- "{n} days old" when 2 or more days stale;
- "As of {date} · end of day".

**Supporting evidence** (investor: "What the rule looked at"). Three rows, each with the value and a reading tag:

| Row (trader / investor label) | Shows | Tag |
|---|---|---|
| "Nifty 50 vs 50-day avg" / "Trend" | `close vs average (±gap%)`, or "— no close or average on record" | up / down / flat |
| "India VIX" / "Expected swings (India VIX)" | `{vix} · at or above / under 20`, or "— {reason} (check skipped)" | high / normal |
| "Breadth" / "Stocks rising vs falling" | `{adv} up · {dec} down · {share}% of movers up · {universe} stocks`, or "— {reason} (check skipped)" | up / down / even |

**Invalidation** (investor: "What would change this"). Each is a single change to one input that would move the reading to a different regime, computed by `classify_desk_regime`. Examples of the wording: "A Nifty 50 close below {average} (its 50-day average) → Bearish"; "India VIX closing below 20 → {regime}"; "Advancing stocks at or below 48% of advances + declines → {regime}". It lists only changes that would produce a different regime. Empty list: "No single input change listed by the rule." No regime: "— no regime to invalidate."

**Potential risks** lists only facts from the routes:

- the macro engine's risk level, with the note "(crude, bond-yield and rupee trends, and global risk signals)";
- each check the rule skipped, as "Volatility not checked: …" or "Breadth not checked: …";
- "Breadth is even (…% of movers up): the wider market does not confirm the trend." when breadth is "even";
- "The regime is N days old." for 2 or more days.

With none: "— none flagged by the routes."

Macro risk level (separate from the five regimes; `macro_engine.classify_regime`, `:437-`):

- Inputs: crude trend, 10-year yield trend, USD trend (each against its 50-day average), and the Nifty-versus-50DMA market regime.
- Inflation is "RISING" if both crude and yield trends are up.
- Risk is HIGH if inflation is rising and the USD trend is up. Else LOW if the market regime is BULL. Else MEDIUM.
- A composite risk score at or below -0.5 forces HIGH. A composite at or above +0.5 turns MEDIUM into LOW.
- The market regime BULL/NEUTRAL/BEAR is the Nifty 50 close against its 50-day average.

**Flow and quote tiles** (`FlowTiles`, from `/api/markets/home`):

| Tile | Value | Sub-line | Source |
|---|---|---|---|
| FII · cash | net ₹ crore, signed | "Net buy/Net sell · {date}" | Data platform market-pulse FII/DII, newest day of the last 7 (`routes/markets.py:113-134`). The exact table behind it was not traced: unverified. |
| DII · cash | as above | as above | same |
| USD / INR | level | "Spot · {change%}" | Yahoo `INR=X` through `nse_live.get_global_snapshot` (cached 60s) |
| Crude oil | `$`level | "Brent · {change%}" | Yahoo `BZ=F`, same snapshot |

Missing values show "Not available" or "—". If `/api/markets/home` failed the tiles show one line saying the market overview didn't load.

**Sector leadership · 1 day:** "Leading {sector} +x.xx% · lagging {sector} -y.yy% · close of {date}", from the sector-returns data in C5. Empty: "— no sector index returns yet."

**Important events:** the three newest key events (C6) and a link "All events ›" to Market Intelligence. States: "Loading events…", "— the event feed didn't load.", "— no events in the feed's window."

**Rules-based insight box** ("Rules-based insight · not a forecast"): shows the macro engine's one-line `insight` and the "Deploy stance" pill with its reason. If neither exists: "No rules-based read is available right now." The footer line reads "stance rules: macro risk, then breadth above the 20-day average, then the Nifty trend".

The insight text comes from `macro_engine._build_insight`. For example, risk HIGH gives "High-risk regime · …", and LOW risk with a BULL market gives "Bullish, low-risk regime · Lean into momentum + cyclicals.". The stance comes from `market_dashboard._deploy_verdict` (`services/positional_engine/market_dashboard.py:35-77`):

| Order | Condition | Stance | Reason text |
|---|---|---|---|
| 1 | Macro risk HIGH | DEFENSIVE | "Macro risk HIGH — keep cash, hedge longs, avoid new positions" |
| 2 | Macro risk MEDIUM | CAUTIOUS | "Macro risk MEDIUM — half size, only highest-conviction setups" |
| 3 | Otherwise, Nifty trend DOWN | CAUTIOUS | "Nifty below 20-DMA · breadth {b}% — no aggressive entries" |
| 4 | Breadth above 20-EMA of 65% or more AND at least 2 HOT sectors | AGGRESSIVE | "Strong breadth …% above 20EMA · N sectors hot · Nifty trending up" |
| 5 | Breadth above 20-EMA of 50% or more | NORMAL | "Breadth …% above 20EMA — selective entries, full size on A+ setups" |
| 6 | Otherwise | CAUTIOUS | "Weak breadth (…% above 20EMA) — wait for confirmation" |

The stance pill is coloured AGGRESSIVE mint, NORMAL neutral, CAUTIOUS amber, DEFENSIVE red. During market hours the verdict is recomputed with the live Nifty trend and live sector tones. HOT sector means a relative strength of 3.0 points or more against the Nifty over 5 days (`_sector_tone`, `:80-91`).

**Rule line** (`RuleLine`): printed from the response, for example "Rule desk-regime-v1: High volatility when India VIX ≥ 20; Mixed when the Nifty 50 trend and breadth disagree (breadth up at ≥ 52%, down at ≤ 48% of advances + declines); otherwise Bullish / Sideways / Bearish by the Nifty 50 close against its 50-day average. One end-of-day session."

States of the regime block:

| State | Text |
|---|---|
| Loading | "Loading the market regime" |
| Fetch error | "The market regime didn't load" with retry |
| Macro route says uninitialised (`_uninitialised`) | "The macro engine has not produced a regime yet, so none is shown. It runs after the close each trading day." The raw reason is shown to admins only. |
| Route sent no `regime` object | "This server sent no regime classification, so none is shown." |
| Rule could not classify | "The regime rule could not classify the session: {reason}." The reason is "no Nifty 50 close or 50-session average on record for the session". |

`/api/macro/today` never returns 500 for internal failures. It returns the uninitialised payload, which the desk reads as "not available" and never as a regime.

### C5. Sector strength (desktop only)

Card "Sector strength" with a 1D / 1W / 1M switch, a sort switch ("Best first" / "Worst first" / "A–Z"), a one-sector filter with "Clear", and tiles in two columns.

Source: `GET /api/markets/sector-returns` (`routes/markets_desk.py`, forwarding to the data platform `GET /v1/desk/sector-returns`, `desk_market.py:139-165`). Table `nidp.index_eod`. Cached 10 minutes in the page. It is end of day.

- **20 sector indices** (`SECTOR_INDICES`, `desk_market.py:68-89`): Nifty Auto, Bank, Financial Services, FMCG, IT, Media, Metal, Pharma, PSU Bank, Private Bank, Realty, Energy, Oil & Gas, Healthcare Index, Consumer Durables, Capital Goods, Cement, Chemicals, Power, Telecommunications. Sub-segments such as NBFC, Insurance and Hospitals are left out on purpose.
- **Return formula:** `ret_Nd_pct = close ÷ (the close N rows earlier in THAT index's own series) − 1`, in percent, with N = 1 (1D), 5 (1W) and 21 (1M) sessions. A tile is null (shown "—") if the index has fewer than N + 1 closes. Each row carries the index's own latest close date, and a tile whose date differs from the response's as-of says "Close of {date}".
- **Tile colour:** tint depends on the move size: `6 + |v| ÷ max|v| × 18` percent, where max is the largest absolute move across all sectors for the chosen period.

Each tile also shows:

- **Sector leader:** the sector's best 5-session stock, as "SYMBOL +x.x% · 5 sessions". Clicking opens its chart. This comes from `GET /api/positional/market-dashboard` (best 5-session return of the stocks in that sector in the end-of-day bars), matched only when the sector names are equal after stripping case and punctuation, or equal to the index name without "Nifty". There is no partial match, so "Bank" does not lend its leader to "PSU Bank". A failed leaders read drops only the leaders, with a note.
- **In-sector breadth:** "N↑ M↓ K=" (advances, declines, unchanged), or "Breadth —". The rule is: a constituent counts as an advance if its bhavcopy close is above the bhavcopy's own previous close (`nidp.prices_eod.prev_close`) on that index's latest close day; decline if below; unchanged if equal; a stock with no bar that day is `no_price` and is never counted as unchanged. It is shown only for indices whose constituent list is in `nidp.index_constituents`. The tile lists "Only X and Y have a constituent list on record; the others show 'Breadth —'". Which indices have lists was not checked: unverified.
- **Stocks ›:** opens a panel listing the index's constituents (`GET /api/markets/sector-constituents?index=`), each with close and change, each opening the stock's chart; capped at a 260px scroll box. Panel states: loading, error, or "No stock list for {index}: {reason}. Breadth within this sector shows '—' until a list is loaded."

Display rules: ten tiles are shown by default. With more than ten and a sort other than A–Z, it shows the five strongest and five weakest, with "Show all N sector indices ›" to expand. Sectors with no figure for the period go last. A footnote states the period ("1 day · 1 session · end of day"), the source and the as-of date. States: loading ("Loading sector strength"), error (a retry block), empty ("No sector figures yet — The route returned no sector indices for the latest session."). A data platform that is unconfigured or unreachable gives HTTP 502 `upstream_unavailable`, never an empty or older list.

Not available: a sector heatmap from a live (intraday) feed. This card is end of day only.

### C6. Top AI opportunities (desktop)

Card "02 · Top AI opportunities", meta "End-of-day scan · {date}", eight rows (`TOP_ROWS = 8`, `:1088`), ranked by score. Each row opens that stock's Chart tab. The row's rank number, symbol, company name, a status pill (Confirmed / Awaiting / Forming), and these fields:

| Field (trader / investor) | Source and rule |
|---|---|
| Setup / Shape | Bucket name (see D3). Picks-only stocks: stage BREAKOUT gives "Breakout", EARLY_BREAKOUT "Early breakout", ACCUMULATION "Accumulation", else "Scanner pick". Investor: "Broke above a recent high", "Close to a recent high", "Dipped within an uptrend", "Trading in a tight range", else "Picked by the scanner". |
| Horizon / Time frame | The pick's planned holding window "{min}–{max} sessions", or "up to {max} sessions", else "—". Only picks have it. |
| Liquidity | "Liquid · ₹N Cr/day" if the 20-session average traded value is at least ₹10 Cr (`LIQUID_MIN_CR = 10`), else "Thin · …", or "Liquidity —". |
| Risk | ATR(14) as a percent of the close: Low under 2, High over 4, Medium from 2 to 4 inclusive (`RISK_ATR_BANDS`, `overview-data.ts:792`), shown as "Risk: Medium · ATR 2.8%". "—" with no ATR. |
| Evidence / Why it shows up | The watchlist's one-line reason (for example "Broke above ₹… (+x%) on N× avg volume"), else the pick's first stored reason, else "—". |
| Against / What could go wrong | From `GET /api/positional/picks/mine?live=true` (each pick's conviction check penalties, plus a live-readiness note when it works against the pick, plus overlap with the user's own holdings). Shows up to the first two, joined by "; ". Otherwise: "checking…", "— the live check didn't load", "none flagged", or "— not one of the picks the live check reads". |
| Price | The latest close in the scan, with "close {date}". Never the plan's entry price. A delayed live price is shown beside it as "LTP … · delayed" when the live check has one. |
| Score | "Score N/100": the scanner's rules-based score, 0 to 100 (final_score × 100). Not a probability. It is highlighted from 80. |
| P(+5% next session) | See the discrepancy note below. |
| to target | `(target − close) ÷ close × 100` (close, else entry), only when the pick has a target. |

Readiness words used inside "Against" (`READINESS_WORDS`, `overview-data.ts:780`; set by `routes/positional.py` `_readiness`): LATE is "already more than 8% past the entry"; STOPPED is "at or below the stop"; FAR is "more than 5% below the entry". Only these three count as "against".

Source: the merged watchlist and picks (`useDeskScanner`: `GET /api/positional/watchlist?limit=30` and `/picks?limit=30`). The details of both are in D2. The live check is refreshed every 2 minutes. Company names come from the move-odds rows when published, because the scanner routes send only symbols. Otherwise the name shows "—".

Legend under the list and the trust line (source "Positional scanner (watchlist and picks)", End of day, Rules-based, plus "live check read {time} (delayed quotes)") are printed on the card.

States:

| State | Text |
|---|---|
| Loading | "Loading the scanner" |
| Error | "The scanner didn't load" with retry |
| Empty | "No setups in the latest end-of-day scan — The scanner lists stocks only after its end-of-day run. Nothing is shown in place of a real scan." |

Discrepancy to resolve (verified in code, not run): the Scanner tab always withholds the move-odds probability, because `probabilityGate` returns "not shown" for every case (`desk-data.ts:603-616`; PRD §5.8: a probability is shown only if calibrated). The Overview card does not apply that gate. At `OverviewTab.tsx:1168` it passes `o.bySymbol.get(symbol).p` whenever `GET /api/move-odds/latest` returns a published ("final") run, and `:1248-1250` prints it as "P(+5% next session) {x.x}%". So for an account that has the move-odds feature and a published run, the Overview shows a number that the Scanner withholds. The legend's own state text is: "published for {date}", "not published for {date}", "withheld: {reason}", or "not enabled for this account"; the figure is "—" when there is none. The Overview legend does not say the estimate is uncalibrated.

### C7. Key market events

Card "03 · Key market events", meta "NSE · BSE · SEBI". It selects from Market Intelligence's "All" chip (the same reads and the same cache as that tab; `useIntelEvents("all")`).

Selection rule (`keyEvents`, `overview-data.ts:812-`):

1. The 3 highest-impact filings (`KEY_FILINGS = 3`): ranked by the classifier's impact (high, then medium, then low, then unknown), newest first within a level.
2. The newest of the five largest bulk or block deals.
3. The latest SEBI circular.
4. The latest FII/DII session.

The union is then sorted newest first. A source with nothing to give is skipped. The feed window is 7 days (`FEED_DAYS`, `intel-data.ts:65`) for filings. FII/DII is read over 90 days. The details of each source belong to the Market Intelligence part.

Each row shows time, type, title, an optional sub-line, the stock (button to its chart, with icon) or "Market-wide", and "Source: {as published} · open ↗" with the link when one exists ("not stated" otherwise). The phone shows only the first 3.

States: loading ("Loading market events"); error ("Market events didn't load"); empty ("No market events in the window — No filings, deals, SEBI circulars or FII / DII sessions came back for the last week."); partial ("Partial: {sources} didn't load."). The footer states the selection rule and links "Open Market Intelligence ›". Trust line: "NSE / BSE filings, NSE deals, SEBI, NSE FII / DII · latest {time} · As reported · filing impact from the event classifier".

### C8. Portfolio snapshot (desktop)

Card "05 · Portfolio snapshot" with a "Read-only" pill. Read-only means Nivesh reads the broker data. It places nothing.

Source: `GET /api/portfolio/holdings-enriched` (`useHoldingsEnriched`), the user's holdings on record from broker reads and statement imports, plus `GET /api/broker/accounts` for the last-read time.

It shows:

- **Broker line:** broker icons and names with "last read {stamp}" (the latest of the accounts' last-sync times), or "nothing read yet". With none connected: "No broker connected · holdings on record in Nivesh". While loading: "Checking broker connections". On failure: "Broker connections didn't load".
- **Total value and unrealised P&L:** for example "₹x Cr · ₹y · +z% unrealised". The tooltip is "Unrealised P&L on what you paid".
- **Realised P&L:** a fixed line: "Realised P&L — not in the holdings read (no closed trades on record here)". It is not available.
- **Asset allocation:** a bar plus a legend of Stocks, Mutual funds, ETFs, Bonds, Gold, Fixed deposits and Other. Each share is `value ÷ summed value of the holdings that have a value × 100` (`allocationOf`). "stock" is merged into Stocks. Holdings with no value are left out and counted: "{n} holdings without a value are left out." If none has a value: "— no holding has a value on record."
- **Top holdings:** the 5 largest by value, with value and the route's weight %.
- **Concentration line:** "largest holding {name} {weight}% · top five {sum of the five weights}% of the portfolio".

States: loading "Loading your portfolio"; error "Your portfolio didn't load"; empty (no holdings) shows "No portfolio connected — Connect a broker (read-only) or import a statement to see your value, P&L and risk here. Nothing is shown until then." with the button "Connect a broker or import ›" (opens `page/brokers`). The trust line says source "Your holdings on record (broker reads and imports)", As reported, as-of the response's `generated_at`, and "Source failed" if broker accounts failed.

### C9. Risk summary (desktop)

Card "05 · Risk summary". Five rows, shown only when holdings exist:

| Row | Value and word | Rule | Source |
|---|---|---|---|
| Portfolio concentration | Largest direct stock's weight %, then "Above limit" if over the limit, else "Within limit". Detail: "Largest stock {symbol} · limit 25%". | Limit `SINGLE_STOCK_LIMIT_PCT = 25` (`portfolio-data.ts:156`) | holdings-enriched |
| Volatility category | "{x}% a year" and Low / Medium / High / Very high. Detail: "Value-weighted 1-year volatility, the route's band". | Annual volatility under 10% is LOW; under 18% MEDIUM; under 28% HIGH; else VERY_HIGH (`routes/portfolio_risk_analytics.py:28-40`) | `GET /api/portfolio/risk-analytics` (`weighted_volatility`, a fraction a year converted to percent) |
| Liquidity | Always "—"; detail "No traded-value figure is read for holdings yet" | none | Not available |
| Sector concentration | The largest classified sector's % and "Balanced" / "Elevated" / "Over-concentrated". Detail: "{sector} is the largest sector". | The sector lens verdict from `usePortfolioConcentration` (`GET /api/portfolio/exposure/concentration`). Over-concentrated if any sector exceeds the route's cap (`caution_pct`). Elevated if one is within 3 points under the cap, or classification coverage is under 80%. Else Balanced. The cap value itself is sent by the route (not read: unverified). | `portfolio/concentration-data.ts:100-120` |
| Missing or stale data | "Check" or "OK". Detail lists: holdings without a value; "risk figures cover x% of the value"; "brokers last read {time}" with "(over a day ago)" when it is more than 24 hours old. | Flag "Check" if any holding has no value or the last broker read is over 24 hours old | holdings-enriched, risk-analytics, broker accounts |

The trust line says "Risk analytics, concentration and your holdings on record · Rules-based · single stock limit 25%; volatility bands of the risk-analytics route". The same loading, error and empty states as C8 apply (the empty state uses the same "No portfolio connected" block).

Not available: a liquidity measure for the portfolio, and realised P&L (C8).

### C10. Phone Overview (separate layout, `MobileOverview`, `:1529-1553`)

Top to bottom: two-column grid of the four index tiles; a status line ("● Market open · Wed 14 Oct, 11:32 IST", same logic as A4) and the index trust line; a compact AI Market pulse card; Top AI opportunities (five rows); two mini tiles; Key market events (three rows).

The phone Overview does NOT show: the headline and intro, the breadth tile, the sector strength card, and the sector leadership and important-events blocks.

- **Pulse card:** regime label chip and the same explanation sentence; Advances, Declines and Unchanged counts with the scope line and "A/D {ratio}"; the rules-based insight box. The button "View details ›" expands: supporting evidence, the FII/DII/USD-INR/crude tiles (two columns), Invalidation, Potential risks, and the rule line. Loading, error and unavailable states are the same as C4 (short wording).
- **Top AI opportunities (phone):** five rows, each with rank, icon, symbol, latest close, a score badge (green from 80), "upside" (to target; "—" if none), the setup name, and a 24-session sparkline. It has no live check, no "Against" line, no liquidity, no risk, and no probability. Footnote: "Score is rules-based, 0–100, not a probability · upside = close to the pick's target · price = the latest close in the scan". Empty: "No setups in the latest end-of-day scan."
- **Mini tiles:**
  - "Your portfolio": total value, P&L, and the sub-text "Loading", "Didn't load" or "No holdings on record". It opens Portfolio & Risk.
  - "Risk status": the word Low / Medium / High / Very high, a 5-part bar, and "Volatility x% a year". The bar fills `ceil(volatility ÷ 8)` parts, from 1 to 5 (the route's 0 to 40% scale). It opens Portfolio & Risk.

---

## D. AI Scanner tab

Files: `ScannerTab.tsx`, `desk-data.ts`, `chart-data.ts` (labels). Backend: `routes/positional.py` (`/watchlist` `:212-`, `/picks` `:187-`, `/scan-universe` `:543-`), `services/positional_engine/setup_rules.py` (all thresholds), `nidp` data platform `GET /v1/features/scan-snapshot`.

The whole tab is end of day. The thresholds shown come from the `rules` block the routes send, versioned. This snapshot's version string is `scan-rules.v2 (2026-10-20)` (`setup_rules.py:RULES_VERSION`). The UI keeps no copy of thresholds except `LIQUID_MIN_CR = 10` for screens that don't read `rules`.

### D1. What the user sees

Header (desktop): "02 · AI Opportunity scanner", an eyebrow "NSE · end of day {date} · {n} of {m} shown", and on the right the move-odds status ("Move-odds {model} · out-of-sample {window}", "Move-odds · not enabled for this account", "Move-odds · not published for {date}", "Move-odds · run withheld", "Move-odds didn't load", or "Move-odds · loading"). Two trust lines: the scanner (source "NSE end-of-day scanner · NIDP feature store", End of day, Rules-based, method = rules version, classifier and engine versions) and the model (source "Move-odds model", Model output, "probability withheld, not marked calibrated"). A trust line shows "Source failed" if the scanner routes failed, the universe failed, or only one of the two scanner routes answered.

The date shown is the watchlist's session. If the picks are on a different session, both are shown: "Watchlist {date} · picks {date}".

Controls row: Rank-by switch, category chips, "Liquid only" switch, list picker (for User watchlist), the category's rule line, then notes. Then the filter bar, the list, and a footnote with sources, "Eligible universe" and "About the model" disclosures.

### D2. Where the rows come from

| Source | Route | Underlying data and as-of | What it supplies |
|---|---|---|---|
| Setup watchlist | `GET /api/positional/watchlist?limit=30` | `stock_technical_features` on its latest `as_of_date`, plus the last 60 bars (90-day fetch) from `stock_ohlcv`, in the app database | bucket, close, trigger (breakout level), stop, ATR %, RSI, EMA20, SMA50, signals, resistance, support, a 24-close sparkline, 20-session average traded value |
| Scanner picks | `GET /api/positional/picks?limit=30` | `positional_signals` on its latest `signal_date`, joined to `stock_technical_features`. The route default `min_score` is 0.55 (the desk does not override it). | final score, confidence, stage, entry, stop, target, reward-to-risk, holding window in days, reasons, source scans |
| Universe scan | `GET /api/positional/scan-universe?setups=…&symbols=…` | The data platform's `GET /v1/features/scan-snapshot` (each NSE stock's latest end-of-day feature row, with that day's bhavcopy row, the NSE security reference and the event calendar). Cached 10 minutes. | momentum, unusual volume, results-day and F&O categories, eligibility, risk and liquidity class, model rank |
| Move-odds model | `GET /api/move-odds/latest?head=p_up5_1d` and `p_up10_1d` (desk) and the same published run through the universe route | Data platform `nidp.tpd_*`, behind the `move_odds` feature flag | events on record per stock, run details, the model rank percentile |
| User lists | `GET /api/watchlists`, `/api/watchlists/{id}` | The user's own lists | the "User watchlist" category |

How the two scanner routes are merged by symbol (`mergeSetups`, `desk-data.ts:251-293`):

- A stock in both lists uses the pick's plan (entry, stop, target) and keeps the watchlist bucket as its "where it stands" label.
- Status: bucket `breakout_confirmed` is Confirmed; `pre_breakout` and `trend_continuation` are Awaiting; `true_accumulation` is Forming. A picks-only stock uses its stage: BREAKOUT is Confirmed, EARLY_BREAKOUT is Awaiting, else Forming.
- Score: the pick's score if present, else the watchlist's. Both are `final_score × 100`.
- Reward-to-risk for a stock is the stored value, else `(target − entry) ÷ (entry − stop)` when all three exist and the stop is below the entry.
- The list is sorted by score descending.

Watchlist caps: each bucket is capped from one score-ordered candidate list: Confirmed and Pre-breakout `max(4, int(30 ÷ 3))` = 10 each; Accumulation and Trend continuation `max(4, int(30 ÷ 4))` = 7 each. So the watchlist sends at most 34 rows at limit 30 (`routes/positional.py:432-437`).

Candidate pre-selection (`WATCHLIST.candidates`, `setup_rules.py`): from the latest `stock_technical_features` date; stage not WEAK or EXTENDED; close above ₹5; top 80 by score; at least 30 daily bars. A candidate with fewer bars is skipped.

Partial failure: if one scanner route fails the other still lists. A banner says which one failed: "The setup watchlist (GET /api/positional/watchlist) did not answer, so only the scanner's picks are listed." or "The scanner picks (GET /api/positional/picks) did not answer, so only the setup watchlist is listed and no stock has a target."

### D3. Categories and exact rules

Eleven category chips in this order (`CATS`, `ScannerTab.tsx:48-60`). Investor wording in brackets. Each shows its rule under the chips, with thresholds from the route. The "rule · {rules version}" suffix appears for rule-based categories.

| Chip (investor) | Kind | Rule as in code (`setup_rules.py`) |
|---|---|---|
| All (All) | union | Every scanner setup plus every stock in any universe category. Ranked by the chosen rank-by. |
| Breakouts (Broke out) | watchlist bucket `breakout_confirmed` | Distance to the breakout level (`(close − breakout) ÷ breakout × 100`) from 0.0 to 3.0 percent; volume spike (mean volume of the last 3 sessions ÷ mean of the 20 before) at least 1.5; stage BREAKOUT or EARLY_BREAKOUT; and the scan session's open not more than 5.0 percent above the previous close (`max_gap_up_pct`; a missing gap does not fail it). Stop = breakout level − 1.5 × ATR(14). |
| Near breakout (About to break out) | bucket `pre_breakout` | Distance to breakout from −2.0 up to (not including) 0.0 percent; volume spike at least 1.2; 10-day volume slope above −3.0 (or missing). Stop = breakout level − 1.5 × ATR(14). |
| Momentum (Rising steadily) | universe `momentum` (v2) | 20-day return at least 5.0%; RSI(14) between 55.0 and 75.0; close above the 50-day average; the 50-day average slope above 0 (percent per day, the feature engine's figure). Ranked by 20-day return. |
| Pullback continuation (Dip in an uptrend) | bucket `trend_continuation` | Close above the 20-day EMA, which is above the 50-day average; close 0.0 to 4.0 percent above the 20-day EMA; average upper wick under 0.5 (or missing). Stop = EMA20 − 1.5 × ATR(14). |
| Accumulation (Quiet sideways range) | bucket `true_accumulation` | 15-day range under 8.0%; 10-day volume slope below 0; at least 1 higher low; upper wick under 0.5 (or missing); close above 0.97 × the 50-day average (or missing). Stop = close − 1.5 × ATR(14). |
| Reversal candidates (Turning around) | none | No rule is defined, so no list is made. The chip is drawn dashed. Its text: "No reversal rule is defined, so no list is made. The repo has only research-only mean-reversion variants that are not on this branch and not validated; a rule needs the owner's choice." The list body says "No reversal list: no rule is defined." |
| Unusual volume (Heavy trading) | universe `unusual_volume` | The day's volume z-score against its 20 days (`vol_z20`) at least 2.0. Ranked by the z-score. |
| Results-day momentum (Moving after results) | universe `results_day` | A quarterly-results date (NSE event calendar) within the last 7 calendar days up to and including the scan date; 5-day return at least 3.0%; `vol_z20` at least 1.0. Ranked by 5-day return. |
| F&O candidates (Has futures & options) | universe `fno` | Eligible for F&O (NSE lot-size file, `security_reference_daily.fno_eligible`) AND in another universe category or a scanner setup. Ranked by 20-session traded value. The chip row adds a link "Open the Options & futures lab ›". |
| User watchlist (Your list) | the user's list | The stocks on the chosen list, each with scanner and universe figures where they exist. |

Bucket precedence (`classify_setup`): the first bucket a stock passes wins, in the order confirmed, then pre-breakout, then accumulation, then continuation. A stock lands in at most one bucket. The "why" lines in the table come from the route, for example "Broke above ₹… (+x.x%) on N.N× avg volume".

Universe gates, checked in this order, and a stock is counted under the first it fails (`UNIVERSE`, `exclusion`):

| Order | Key | Rule |
|---|---|---|
| 1 | `missing_price` | no close or no previous close for the scan date (or not above 0) |
| 2 | `no_traded_value` | fewer than 20 sessions of close × volume |
| 3 | `no_reference` | no NSE security reference row (series, price band, F&O flag) |
| 4 | `series` | not in the EQ or BE series |
| 5 | `etf` | an ETF |
| 6 | `price_band` | price band under 10% (NSE's 2% and 5% tight circuit limits; F&O stocks carry no band and pass) |
| 7 | `at_band_limit` | closed within 0.1 point of its band limit (move ≥ band − 0.1) |
| 8 | `illiquid` | 20-session average traded value under ₹10 Cr a day |

Only eligible stocks can be in a universe category and can have a model rank. A stock missing a figure a rule needs does not pass that rule and is counted as "missing" (`categories[x].missing`). Each category lists at most 50 stocks (`MAX_ROWS_PER_CATEGORY`), and the count line reads "{n} match; the top {m} are listed; {k} could not be judged for missing figures".

Risk class: ATR(14) as a percent of the close, Low under 2.0, High over 4.0, Medium otherwise (`RISK_BANDS`; in the UI `riskClassOf` uses the route's bands). Liquidity class: "Liquid" at ₹10 Cr a day or more, else "Thin" (investor: "Easy to trade" / "Thinly traded").

Per-stock risk flags exist in the backend (`RISK_FLAGS`: gap of 5% or more, results within 7 days, RSI above 75, thin trading, missing indicators), but `ScannerTab.tsx` does not render them. Where else they show was not checked: unverified.

### D4. Filters

Controls: a "Filters ▾" button (with a count), a chip per active filter (click to clear), "Reset filters", and a "Liquid only" switch. The panel offers (`FilterPanel`, `FILTERS`):

| Filter | Options and test | Needs |
|---|---|---|
| Liquid only (switch) | 20-session average traded value at least ₹10 Cr (value from the route) | traded value |
| Sector / industry | any sector found in the rows | sector |
| Market cap | Large, Mid, Small, Micro | market-cap bucket. The control is disabled with the note "Not available: no stock here carries a market-cap bucket (filled on none on the latest features date), and the Midcap 150 / Smallcap 250 lists are not loaded." when no row has a bucket. Whether that is true now is unverified. |
| Price ₹ min and max | numbers; applied on blur or Enter | price |
| Relative volume | 1.5×, 2×, 3× or more (day's volume ÷ its 20-session average) | `rvol20` |
| Volatility (1 year) | 25%, 35%, 50% or less | `volatility_1y_pct` |
| Risk category | Low / Medium / High, using the route's ATR bands (note shows them) | ATR |
| Instrument | "F&O eligible", "Cash only (no F&O)", "In the eligible universe" | an NSE reference row |
| Prediction horizon | fixed "Next session"; disabled. Note: "The model has next-session estimates only; longer horizons need model work." | none |
| Model probability | disabled; the note is the withheld reason (D6) | none |

A row that lacks the figure an active filter needs is hidden, never passed. A note counts them: "Hidden because a filter needs a figure they do not have: {n} with no 20-session traded value, …". While Liquid is on, a note repeats the definition and rules version.

### D5. Columns, fields and rank-by

Desktop table columns, in order (`COLS`, `TABLE_COLUMNS`, `ScannerTab.tsx:720-757`). Investor labels in brackets:

| Column | Content |
|---|---|
| # | rank, two digits |
| Stock | symbol, name (list stocks only), last close, rupee change and percent change |
| Score | 0–100, `final_score × 100`, green from 80. "—" for a stock without a scanner setup (tooltip: only the scanner's own setups have a score) |
| P(+5% next session) ("Chance +5% next day") | always "Withheld" (D6) |
| Model rank | percentile such as "87th pct", or "—" with a reason |
| Pattern / catalyst ("Why it shows up") | setup name, the catalyst ("Results {date}" if results were inside the window, else "Results due {date}", plus "+ N events" the move-odds model has on record), and the why text |
| Confirmation ("What backs it") | status pill (Confirmed / Awaiting / Forming, or "Rule met" for a universe-only stock, or "No setup"), evidence like "Vol 1.8× · Gap +0.4% · 20d +7.1%", and a warning line "⚠ Excluded: {reason}" for a stock that fails a gate |
| Liquidity · risk ("Easy to trade") | "₹N Cr a day" or "No traded value", class, "F&O" or "Band N%", then "Risk Low/Medium/High" and "ATR x.x%" |
| To target | `(target − base) ÷ base × 100`, base is close else entry; only picks have a target |
| 24 sessions | sparkline of the last up to 24 daily closes, green if the last is above the first. "No line" if fewer than 2 points. |
| Action | "Act ▾" expands the actions (D7) |

The price and change on the Stock column come from the last two closes in the 24-session line when it has them, else the universe row's close and previous close, else the setup's close or entry (shown as "Entry …" if only entry exists).

**Rank by** (`RankBySwitch`): "Score", "Model rank +5%" and "Model rank +10%" (investor: "… +5% day", "… +10% day"). The two model ranks are disabled unless the universe read succeeded and the model status is `final`. The tooltip then says "Needs the model's rank: the model is not published, not enabled for this account, or the universe did not load". If the URL asks for a model rank but the model is not ready, the screen falls back to Score (the URL value is left unchanged).

Sort order:

- Score: score (descending, missing last), then the category's own figure (20-day return, volume z-score, 5-day return or traded value), then the +5% model rank, then traded value, then symbol.
- Model rank: that rank (descending, missing last), then the Score order above.

**Model rank** is the stock's model estimate as a percentile among the eligible stocks the model scored (`setup_rules.rank_percentiles`). It is an order, not a probability. The tooltip reads "the stock's +5% next-session estimate is above x% of the N eligible stocks the model scored. A percentile, not a probability." When missing the reason is one of: "The universe route did not load, so there is no model rank."; "Loading the universe."; the model's own reason; "Not in the latest feature snapshot."; "Not in the eligible universe: {gate}."; "The model did not score this stock."

### D6. Probability: withheld, and the other model states

The probability column and the probability filter are always withheld in this snapshot. `probabilityGate` (`desk-data.ts:603-616`) has no code path that returns a shown value: the move-odds route sends a 2025 band record but no calibration flag (PRD §5.8 requires one). The cell shows the word "Withheld" with the reason as its tooltip and as screen-reader text. Reasons by model state:

| Model state (`GET /api/move-odds/latest`) | Reason text (trader) |
|---|---|
| Loading | "Loading the move-odds model." |
| Published (final) | "Withheld: GET /api/move-odds/latest does not mark these estimates as calibrated (it sends a 2025 band record, not a calibration flag), so no probability is shown (PRD §5.8)." Investor: "Not shown: the model's chances are not marked as checked against real outcomes (calibrated), so they are held back." |
| Not published for the session | "Not published for {date} yet." |
| Run withheld (HTTP 503 "withheld") | "The model's run was withheld: {reason}." |
| Not enabled (HTTP 403, account not on the `move_odds` list) | "Move probabilities are not enabled for this account." |

When the model is not enabled for the account, the model-rank columns, the rank-by options and the "Model rank" cell show the same reason, while the scanner rows still list.

"About the model" (collapsed) states: the score is a rules-based end-of-day rank, not a probability; the move-odds model gives next-session estimates only (the chance the next session's high reaches the previous close plus 5% or 10%); estimates are frozen nightly as a hashed snapshot; the published run's model, refit, train end and scored count when available; the PRD §5.4 limitation text in amber; and that the baseline configuration PRD §5.4 names could not be matched to code, and PRD §5.5 tasks B and C have no model yet. A line states "Hit rate · n: no per-setup back-tested record is published." (investor: "Past record: no track record per idea is published yet.").

### D7. Actions

Click or press Enter/Space on a table row (or on a card, outside its own controls) opens the stock on the Chart tab (`openChart` sets `?tab=chart&sym=`). The selected symbol's row is highlighted. "Act ▾" (cards: "Actions ▾") expands a panel with:

- **Open analysis ›** (investor: "See the chart ›"): same as the row click.
- **Add to list:** the existing `AddToList` control (`workspace/PersonalLists.tsx`); `POST /api/watchlists/{id}/symbols`. Its states are in that component and were not read: unverified.
- **Paper trade · shares:** a quantity box and "Add paper trade". The quantity must be a whole number from 1 to 1,000,000. It posts `POST /api/desk/paper-trades` with the setup's entry and stop, the target only if it is above the entry, and source `{kind: "scanner", bucket, signal_date}`. It is hypothetical: "No order is placed and nothing is sent to a broker; it is marked against end-of-day closes." Success: "Paper trade added: {qty} {symbol} at {entry}. No order is placed." Failure: "Not added — {reason}". Without a scanner setup that has an entry and a stop below it, the panel says "Paper trade needs a scanner setup with an entry and a stop below it; {symbol} has none on this scan." So universe-only and watchlist-only stocks without those levels cannot be paper traded here.

There is no order placement or broker action.

### D8. Cards versus table

- Phone (under 700px): compact cards (stock, score, pattern, confirmation, then a grid of probability, model rank, liquidity, risk, to target; no sparkline), the category chips scroll horizontally, and filters sit in a card. A "Scanner insights" card ends the tab with counts ("{n} stocks in {category} on the {date} scan; {k} confirmed setups. {eligible} of {total} stocks pass the eligibility gates."), the trust lines, and a collapsed "How these figures are worked out".
- Desktop: the table needs a box width of 940px or more (`TABLE_MIN_WIDTH`, measured with a ResizeObserver). Narrower, for example next to the docked Copilot, the rows become the same cards with five fields in a row and a sparkline. It starts in card mode until the width is measured.

### D9. URL persistence

All scanner state lives in query parameters and changes use `replace` (`useScanState`, `ScannerTab.tsx:76-138`). A reload or a shared link restores it. They also persist across other tabs, since tab changes keep the other parameters.

| Param | Value | Default (omitted) |
|---|---|---|
| `sc_cat` | category key: all, breakouts, near_breakout, momentum, pullbacks, accumulation, reversal, unusual_volume, results_day, fno, watchlist | all |
| `sc_rank` | m5 or m10 | score |
| `sc_liq` | 1 | off |
| `sc_sector`, `sc_cap`, `sc_risk`, `sc_inst`, `sc_pmin`, `sc_pmax`, `sc_rvol`, `sc_vol` | the filter values | none |
| `sc_list` | a watchlist id (User watchlist) | the user's first list |

Not persisted: whether the filter panel is open, and which row's actions are expanded. Invalid values fall back to the default. Number filters accept only values that are 0 or more.

### D10. Universe and exclusion disclosure

A collapsed "Eligible universe: {eligible} of {total} stocks on {date} · how stocks are excluded" (`UniverseNote`). Open, it states:

- the universe categories and model rank use each NSE stock's latest end-of-day feature row in the data platform with that day's bhavcopy price;
- the eight gates in order, each with its count of stocks excluded (the first gate a stock fails), worded from the route's thresholds (for example "a price band under 10% (NSE's tight circuit limits): n");
- "F&O eligible in the eligible universe: {n} (NSE lot-size file, reference of {date})";
- how setups are chosen: "the top 80 stocks by score above ₹5 whose stage is not WEAK or EXTENDED, with at least 30 sessions of bars".

If the universe route fails, it says so in red ("GET /api/positional/scan-universe did not answer, so momentum, unusual volume, results-day and F&O candidates, the model rank and the exclusion counts are not shown.") with a Retry button. The route returns HTTP 502 `upstream_unavailable` if the data platform is not configured or does not answer. It never returns an empty universe.

The footnote also states, in trader and investor wording, that the score is not a probability, what the model rank is, that entry, stop and target are hypothetical and never sent to a broker, and the sources: "NSE end-of-day scanner (GET /api/positional/watchlist, /picks) · NIDP feature store (GET /api/positional/scan-universe) · move-odds model (GET /api/move-odds/latest)".

### D11. Loading, empty, error and other states

| State | Text and behaviour |
|---|---|
| Loading | "Loading the scanner" (5 rows) |
| Both scanner routes fail and universe fails | "The scanner didn't load: neither the setup watchlist nor the scanner picks answered", with retry |
| Scanner routes fail but universe loads | Tab still shows the universe categories, with a red note "The scanner's own setups (GET /api/positional/watchlist, /picks) didn't load; only the universe categories are listed." and Retry |
| A universe category with the universe failed | "This category needs the universe scan, which didn't load" with retry |
| A universe category still loading | "Loading the universe scan" |
| User watchlist: loading | "Loading your list" |
| User watchlist: error | "Your lists didn't load" with retry |
| User watchlist: no lists | "You have no lists yet. Make one under Watchlist & alerts, then add stocks to it." |
| User watchlist: empty list | "This list has no stocks." |
| No rows | All: "No setups or universe matches on the {date} scan." Bucket: "No setup in this group on the {date} scan." Universe category: "No stock meets this rule on the latest scan." |
| Everything filtered out | "The one stock in this category does not pass the filters." or "None of the N stocks in this category passes the filters." |
| Reversal | "No reversal list: no rule is defined." |

What is NOT available in the Scanner (and why):

- A calibrated probability (D6).
- Predictions beyond the next session, because the model has next-session estimates only.
- A reversal list (no rule is defined).
- Per-idea track record or hit rate ("no per-setup back-tested record is published").
- A market-cap filter, when no stock carries a bucket.
- Intraday scanning: all inputs are end of day.

---

## Open points found while reading (for the owner)

1. Overview Top AI opportunities prints the move-odds probability as a number for accounts with a published run, while the Scanner withholds the same estimate (C6, D6). This is verified in code and has not been run. The PRD §5.8 gate is applied in one place and not the other.
2. A one-word question typed in the header search is treated as a stock symbol and opens the Chart tab (A2).
3. A question sent while an answer is streaming is dropped without a message (A2).
4. Static Overview pills "Paper trading on" and "Live orders off" are fixed text (C1).
5. The phone Overview omits the headline, the breadth tile, the sector card and the leadership/events blocks (C10). Whether this meets the PRD's phone requirement was not checked here.
6. Per-stock risk flags (gap, event window, extended RSI) are produced by `scan-universe` but `ScannerTab.tsx` does not render them (D3).
7. The earlier gap matrix was not used as a source. Everything above was read from the code in this snapshot.


---

# Smart Trading Desk — functionality documentation, part 2

Covers: (A) Chart Analysis tab, (B) the ten-section opportunity detail, (C) the Risk desk, (D) the Market Intelligence tab.

## 0. How to read this

- Source snapshot: `/home/deploy/nivesh-fix-bse` (a snapshot of origin/dev). Everything below was read from that code. Nothing was run, and no staging data was queried, so statements about what staging currently holds are marked "unverified".
- Path shorthand:
  - `FE/` = `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/`
  - `BE/` = `backend/`
  - `daas/` = `backend/nidp/services/daas_api/routers/`
- "Trader" and "Investor" are the desk's two wordings (a switch in the header, kept in the URL as `?persona=investor`). The data is identical; only labels and some sentences change (`FE/context.tsx`). Where wording differs it is listed.
- The earlier gap matrix (`prd-gap-matrix.md`) predates this code. Where it disagrees with the code (for example "the browser computes the calculator", "indicators computed in the browser"), the code wins: indicators, patterns and the scenario calculator are all computed on the server now.
- All price data on these screens is end of day. Nothing is live (`ChartTab.tsx:1213`: "Everything here is end of day or older; nothing on this page is live.").

### Feature gates that affect these screens

| Gate | Where enforced | Effect when the account lacks it |
|---|---|---|
| `charting` | `BE/routes/research_chart_live.py:27`, `BE/routes/research_chart.py` (`require_feature`) — admins are not exempt | Candles, indicators and patterns answer 403. The Chart tab shows "Charting is not enabled for this account". |
| `move_odds` | `BE/routes/move_odds.py:34` (`FLAG`) | Model probabilities answer 403. Screens say "Move probabilities are not enabled for this account." |
| Signed-in only | `/api/filings/feed`, `/api/markets/*`, `/api/positional/*`, `/api/desk/*` | No flag. |

If the feature-flag store cannot be read, the gate fails closed with 503 `feature_state_unavailable` (`BE/feature_gate.py:60`).

---

# A. Chart Analysis tab

Tab id `chart`, label "Chart Analysis" (`FE/context.tsx`). The desk header reads `?tab=chart&sym=SYMBOL`. With no symbol chosen the tab uses the scanner's first setup (`ChartTab.tsx:1284`).

## A.1 Layout and states of the tab

| Situation | What the user sees | Code |
|---|---|---|
| No symbol chosen, scanner still loading | "Loading the scanner" | `ChartTab.tsx:1304` |
| No symbol, scanner empty or failed | "Pick a stock to chart". Body: "The scanner has no setups on its latest scan, so there is no stock to open yet." (or "The scanner didn't load, so there is no first setup to show." on error), plus an "Open the AI scanner" button | `ChartTab.tsx:1306-1313` |
| Desk (wide) | Two columns, 7 : 5. Left: "03 · AI Chart intelligence" card, then the opportunity detail (part B). Right: the Risk desk (part C). Below 640 px of width the two stack. | `ChartTab.tsx:1397-1447`, `SIDE_BY_SIDE_MIN` = 640 (line 53) |
| Phone | Header, controls, chart card, "AI chart analysis" card, "Historical performance · similar setups" (3 tiles), "05 · Trade scenario" card, opportunity detail | `ChartTab.tsx:1336-1393` |

Head row (`HeadRow`, `ChartTab.tsx:285`): stock icon, symbol, company name, last close (34 px), change versus the previous bar's close (`last − prev`, and `% = (last − prev) ÷ prev × 100`), and "<date> close · end of day". The company name comes from the move-odds run (`row.company_name`) or the stock's move-odds record; it can be absent. Pills on the right: the scanner setup label, "Volume n.n×" (last-3-session volume ÷ 20-day average, from the scanner), "Stage · …" — or "Not on today's scanner" when the stock is not a setup.

## A.2 Where the chart's figures come from

| What | Route (flag) | Underlying source and as-of | Notes |
|---|---|---|---|
| Daily candles and volume | `GET /api/research/chart-live/{symbol}/ohlcv?start=<today − 320 calendar days>` (`charting`) — `BE/routes/research_chart_live.py:51`; FE call `chart-data.ts:92`, `HISTORY_DAYS = 320` (`chart-data.ts:66`) | DaaS `/prices/adjusted/{symbol}` → `nidp.prices_eod_adjusted` (columns `adj_open/high/low/close/volume`). As-of = last bar date, returned in `provenance.last_bar_date`. Server returns up to `MAX_BARS = 5000` (line 31). | Cached 10 min on the client (`staleTime`). |
| EMA 20/50/200 lines, VWAP 20D line, all indicator values, hypothetical levels, price band | `GET /api/research/chart/live/{symbol}/indicators` (`charting`) — `BE/routes/research_chart.py:457` | Same adjusted bars (latest `LIVE_BARS = 750`, line 160) run through `nidp/services/technical_indicator_engine/calculator.py`; Nifty 50 closes from `nidp.index_eod` (DaaS `/indices/Nifty 50/eod`, last 150 rows); price band from `nidp.security_reference_daily`. | `as_of` = last bar. |
| Patterns | `GET /api/research/chart/live/{symbol}/patterns` (`charting`) — `BE/routes/research_chart.py:621` | `research.charting.patterns.detect_as_of` on the same 750 bars, evaluated at the last bar. | 503 `pattern_engine_unavailable` when the `research/` package is not deployed beside `backend/` (line 627). |
| Filing markers | `GET /api/filings/feed?symbol=&days=30&sort=latest&limit=20` | Classified exchange filings (see D.2). | Only the 20 newest filings in 30 days can become markers (`ChartTab.tsx:57, 1289`). |
| Scanner setup, entry/stop/target, "Setup check", "Why it ranks" | `GET /api/positional/watchlist` + `/picks` (`desk-data.ts`) | Positional engine, end-of-day scan. | Part 1 of this documentation covers the scanner. |

The ohlcv route builds each bar as `[date, o, h, l, c, v]`, oldest first. A row missing any of open/high/low/close, or with a non-positive price, or with `high < max(open, close)` or `low > min(open, close)`, is dropped, not repaired (`research_chart_live.py:34-48`). If any row was dropped, `data_quality_status` is `PARTIAL`, and the chart's source line adds "the data platform dropped some incomplete sessions from this series". The response always carries `pit_status: "PIT_UNVERIFIED"` and `adjustment_status: "SPLIT_BONUS_ADJUSTED"` (lines 81-92).

Adjustment basis: the route docstring says "split and bonus adjusted, price-return" (line 13). The DaaS endpoint's own summary says "Split/bonus/dividend-adjusted OHLCV" (`daas/prices.py:59`). Which corporate actions the `adj_*` columns include is therefore not settled by the code read here — unverified. The screen says "split and bonus adjusted".

## A.3 The chart (`CandleChart.tsx`)

What the user sees:

- Inline SVG, no chart library. Desk size 540 × 272 (price pane 230, volume strip 36); phone 330 × 194 (160 + 28). A right-hand gutter carries the last-price tag and, if levels are drawn, the level labels (or a price axis if no level is drawn).
- Candles: green when `close ≥ open`, red otherwise; wick high-low. Volume bars sit under the price pane, scaled to the largest volume in view.
- A readout line above the chart: `date · O · H · L · C · Vol`, plus "n filing(s)" when that session has filing markers. Pointing at the chart (or focusing it and pressing the left and right arrow keys) moves the readout to that session; leaving resets it to the last bar.
- Range chips (right of the card header): `1M`, `3M` (default), `6M` = 22, 63, 126 daily candles (`ChartTab.tsx:49`). If fewer sessions exist the chart shows all and the source line says "only n sessions on record, all shown".
- Legend under the chart lists only what is drawn, with "DAILY · 3 MONTHS" at the right. Investor wording on the legend/level labels: "20-day avg", "50-day avg", "200-day avg", "Month's avg", "Buy above", "Exit" (`CandleChart.tsx:70`).

### Overlay chips

| Chip | Draws | Rule | Disabled when |
|---|---|---|---|
| EMA (on by default) | EMA 20, EMA 50, EMA 200 lines | Server series (below), aligned to the drawn bars by date. EMA 200 is drawn (and appears in the legend) only if at least one of its points in view is non-null. | Never disabled; lines are absent if the indicator route did not answer (the source line then says "no indicator lines: the indicator route did not answer"). |
| VWAP (on by default) | VWAP 20D line | See A.4. A 20-day volume-weighted average of daily prices, not the intraday VWAP — the source line says so. | As above. |
| Levels (on by default) | Dashed lines for the scanner's Target, Entry and Stop, each labelled in the gutter | Only the scanner's levels (`setup.entry/stop/target`). | Disabled, with title "No scanner levels for this stock", when the stock has no scanner levels. |

Important fact: the chart draws only scanner levels. The rule-based hypothetical levels (B.7) are shown in the Risk desk, the opportunity detail and the "Open full chart" link, but not as lines on the desk chart (`ChartTab.tsx:240`).

### Filing markers

A small diamond sits at the foot of the price pane under each session that had at least one exchange filing in the last 30 days. One marker per session, however many filings; the hover text (SVG `<title>`) is "<date>: n filings — doc label · category; …" or "Exchange filing" when no label exists (`ChartTab.tsx:164-175`). The legend adds "Filing". The source line adds "◆ n sessions with an exchange filing in the last 30 days". A filing is placed on the first 10 characters of its date field; whether that date is in IST or UTC is not determined by the code read — unverified.

### Source line and trust line (under the chart)

The source line (`ChartTab.tsx:244-256`) states, in order: "NSE daily bars, split and bonus adjusted (nidp.prices_eod_adjusted) · end of day · last session <date>", then any of: only-n-sessions, partial-series, unadjusted-split sentence (A.5), no-EMA-200 reason, the VWAP statement or "no indicator lines…", and the filing count. The trust line reads "NSE daily bars (nidp.prices_eod_adjusted) · End of day · <last bar date> · Rules-based · Indicators: stock_features_daily engine (calculator.py) · scanner setups: rules"; its status turns to "Source failed" if the bars or the indicator read errored (`ChartTab.tsx:1323-1332`).

### Chart body states

| State | Text | Code |
|---|---|---|
| Loading | "Loading <SYMBOL> daily bars" | `:205` |
| Error | "<SYMBOL> prices didn't load" with a Retry | `:206` |
| 403 (no `charting`) | "Charting is not enabled for this account." Body: "Daily candles and the indicators worked out from them need the charting feature. The scanner levels and the risk desk still show." | `:207-215` |
| 404 or no plottable bars (`no_bars_for_symbol`, `no_plottable_bars`) | "No daily prices on record for <SYMBOL>" — "The data platform has no adjusted end-of-day bars for this symbol. Pick a stock from the AI scanner." | `:217-222` |

## A.4 Intervals — why only daily

`INTERVALS` (`chart-data.ts:545`) lists `1D` (enabled), `60m`, `30m`, `15m`, `5m` (all disabled). The segmented control under the chart shows them; the disabled ones carry the reason: "No intraday bars on record: nidp.intraday_bars is not collected on this environment and has no read route yet. Daily bars only." (`chart-data.ts:552`). The control's `onChange` does nothing. Investor label for the row: "Each candle". The desk has no weekly or monthly interval either. (The snapshot chart route has `1W`/`1M` for its fixed symbol set, but the desk does not use it.)

Backend facts behind the reason: the chart-live route reads only `nidp.prices_eod_adjusted` (`research_chart_live.py:13`). An intraday bar collector and `nidp.intraday_bars` exist in the repo history (migration 152, commit "feat(kite): intraday bar collector"), but the gap matrix (B12) records "not collected on staging, no Kite token". No route in this snapshot reads intraday bars for the desk. Whether the table has rows anywhere is unverified.

## A.5 Indicators: server formulas, lookbacks, unadjusted splits

All indicator values and all overlay series are computed in `BE/routes/research_chart.py` using `calculator.py` (the engine that fills `stock_features_daily`). The browser computes none of them (`FE/indicators.ts:1-12`). The lookback and formula of each indicator come back in the response (`definitions`) and are what the drawer prints.

### The indicator tiles

Five default tiles (`DEFAULT_TILES`, `ChartTab.tsx:353`): EMA 20, RSI 14, ATR 14, VWAP 20D, RVOL. Seven more can be switched on from the drawer: EMA 50, EMA 200, MACD, Rate of change, Relative strength vs Nifty 50, Volume MA, Support / resistance (`EXTRA_TILES`, `:355-363`; off by default, "never every indicator at once"). On a card narrower than 520 px the grid is 3 columns, otherwise 5 (`FIVE_TILES_MIN`, `:55`). Hovering a tile shows "<label> · <lookback>: <formula>" (except the Support/resistance tile, whose hover text is empty because the tile looks up key `sr20`, while the definition key is `resistance20`; the drawer's toggle chip does show its formula — a defect in the lookup, `ChartTab.tsx:347` vs `:362`).

| Tile (Trader / Investor label) | Value shown | Sub-line rule | Min sessions |
|---|---|---|---|
| EMA 20 / "Trend" | EMA 20 | "Price above" / "Price below" / "Price at" by close vs EMA 20 (investor: "Price above it" / "Price below it"). Green when above, red when below. | 20 |
| RSI 14 / "Momentum" | RSI to 1 decimal | `rsiZone`: ≥ 70 "Overbought" (amber), ≥ 55 "Healthy" (green), otherwise "Neutral". Investor words: "Stretched", "Strong", "Neutral". The 70 and 55 cut-offs are UI constants (`FE/indicators.ts:46-51`), not part of the engine. | 15 |
| ATR 14 / "Daily swing" | ATR in ₹ | "<ATR %> of price" | 15 |
| VWAP 20D / "Month's avg" | VWAP 20D | price above/below it, as EMA 20 | 20 |
| RVOL / "Activity" | volume ratio, "n.nn×" | ≥ 1.5 "Volume expansion" (green), else "No volume expansion" (investor: "Busier than usual" / "Usual activity"). The 1.5 cut-off is a UI constant (`:333`). | 20 (a full 20-session baseline needs 21) |
| EMA 50 / "50-day avg" | EMA 50 | as EMA 20 | 50 |
| EMA 200 / "200-day avg" | EMA 200 | "Needs 200 sessions" when null | 200 |
| MACD 12 / 26 / 9 | histogram, 2 decimals | "MACD x · signal y" or "Needs 35 sessions"; coloured by the histogram's sign | 35 |
| ROC 20 / "Change · 20 days" | % change, signed | "vs the close 20 sessions ago" | 21 |
| RS vs Nifty 50 / "vs Nifty 50" | excess points, signed | "Stock +a% · index +b%", or "Needs Nifty 50 closes" | 64 |
| Volume MA 20 / "Usual volume" | mean volume | "shares a day, before the last session" | 20 |
| Support / resistance / "Recent range" | "low – high" | "20-session low – high" | 20 |

### The "More indicators and how each is worked out" drawer

Closed by default; `aria-expanded`. Contains the toggle chips for the seven extra tiles, then every definition from the route, then "<method> · <n> sessions to <date> · end of day". The 15 definitions (`research_chart.py:166-202`; `RS_SESSIONS = 63` line 163):

| Key | Lookback | Formula (as served) |
|---|---|---|
| `ema20` | 20 sessions | EMA of the close, k = 2 ÷ (20 + 1), seeded with the first close of the window (`_ema_series`); none until 20 sessions exist |
| `ema50` | 50 | as EMA 20 with k = 2 ÷ 51 |
| `ema200` | 200 | as EMA 20 with k = 2 ÷ 201, seeded with the first close of the window (up to 750 sessions) |
| `rsi14` | 14 | Wilder: first average gain and loss are the means of the first 14 daily changes, then (previous × 13 + today) ÷ 14; RSI = 100 − 100 ÷ (1 + gain ÷ loss); 100 when average loss is 0 (`calculator.py:52-71`) |
| `atr14` | 14 | Wilder: TR = max(H − L, abs(H − previous C), abs(L − previous C)); first ATR = mean of 14 TRs, then (previous × 13 + TR) ÷ 14; in ₹ |
| `atr_pct` | 14 | ATR 14 ÷ last close × 100 |
| `macd` | 35 | EMA 12 − EMA 26 of the close; signal = EMA 9 of the MACD line from the 26th session on; histogram = MACD − signal (needs 26 + 9 = 35 closes, `calculator.py:74-92`) |
| `roc20` | 20 | (close ÷ close 20 sessions earlier − 1) × 100 |
| `avg_volume20` | 20 | mean volume of the 20 sessions before the last; the last session is not in its own baseline (NaN volumes are dropped; fewer than max(5, 10) usable → none) |
| `rvol20` | 20 | last session's volume ÷ volume MA 20 |
| `vwap20` | 20 | Σ(typical price × volume) ÷ Σ volume over the last 20 sessions, typical = (H + L + C) ÷ 3 (`_vwap_series`, `:295`); none if the 20-session volume sums to 0 |
| `rs63` | 63 | stock's 63-session return minus Nifty 50's over the same two dates (close on or before each date), in percentage points |
| `resistance20` | 20 | highest high of the last 20 sessions |
| `support20` | 20 | lowest low of the last 20 sessions |
| `avg_traded_value_cr20` | 20 | mean of close × volume over the last 20 sessions, ₹ crore a day (÷ 1e7) |

Series for the chart lines: the last `SERIES_SESSIONS = 126` sessions (line 161) of EMA 20/50/200 and VWAP 20D. An EMA point exists only from its `n`-th session on (`_ema_masked`, line 304).

Missing figures are `null`, never 0 (`_flt`, line 236). Tiles show "—".

### Unadjusted splits, and when EMA 200 is hidden

- Detection: `BREAK_MOVE = 0.4` (`research_chart.py:311`). `_adjustment_break` walks back from the last bar and returns the most recent session whose close differs from the previous close by 40% or more (`abs(cur ÷ prev − 1) ≥ 0.4`). NSE circuit limits stop at 20%, so a 40% one-day move is treated as an unapplied split or bonus. The code comment cites KOTAKBANK's 5:1 split of 2026-01-14 as having no row in `nidp.corporate_actions`.
- Handling: when a break is found, indicators use only the bars from the break day on (`used = bars with date ≥ break date`, line 461). The response carries `adjustment_break {date, prev_close, close, ratio}`, `sessions` = the number of bars actually used, and `adjustment_status: "UNADJUSTED_BREAK_IN_HISTORY"`.
- What the user sees: the chart source line adds "the price series jumps ₹a to ₹b on <date>, a split or bonus the data platform has not adjusted: indicators use only the n sessions from that day" (`ChartTab.tsx:248-250`). The candles before the break are still drawn at their stored (other-scale) prices; the lines start only after the break.
- EMA 200 hidden: it is not drawn when fewer than 200 usable sessions exist (a recent listing, or history cut at a break). The server returns `series_notes.ema200` = "EMA 200 needs 200 sessions; only n are usable[, because the bars before the <date> price break (close a to b, a split or bonus the warehouse has not adjusted) are on another price scale and are left out]." (`_series_notes`, `:412-421`). The chart shows it in the source line as " · no EMA 200 line: <reason>" while the EMA chip is on. The EMA 200 tile shows "—" with "Needs 200 sessions"; the legend omits EMA 200. The same applies to EMA 20 and EMA 50 below 20 and 50 sessions.
- Not handled the same way in patterns: `live_patterns` computes indicators on all bars (`research_chart.py:629`: `_indicator_values(bars, bench)`), not on the post-break bars. For a stock with an unapplied split, pattern criteria that read EMA 50 / EMA 200 or relative strength use values from the full, mixed-scale series. Pattern detection itself (`_detect`) also receives all bars. This is a difference in the code, not a documented behaviour.

## A.6 Patterns: states and per-criterion checks

Shown in opportunity-detail section 3 ("Technical evidence") and used by section 9 — there is no separate patterns card on the chart itself.

### What is detected

The engine (`research.charting`, `ENGINE_VERSION "0.1.0"`, profile `PATTERN_CONFIRMATION_V1_RESEARCH`, `research/charting/config.py:11-12`) has 19 families in the registry (`research/charting/pattern_registry.py`, registry version 1.0.0). Three are enabled: Support / resistance, Rectangle, Higher highs / higher lows. The other 16 (the triangles, wedges, channels, flags, pennants, double top/bottom, head and shoulders, inverse head and shoulders, cup and handle) are `enabled = False` with `disabled_reason = "no detector implemented; specification only"` (line 72). The screen prints: "Not detected yet — no validated detector: <labels>." (`ChartTab.tsx:786-788`).

At most `MAX_PATTERNS = 12` patterns are returned, sorted by state (confirmed, awaiting confirmation, candidate, invalidated, expired), most recent first within a state (`research_chart.py:618-661, 164`). If more exist: "Showing 12 of N, confirmed first."

### The five states (`_prd_state`, `research_chart.py:513-534`; `STATE_LABEL`, `chart-data.ts:~365`)

| State | Trader / Investor label | Engine lifecycle status that maps to it | Reason printed |
|---|---|---|---|
| `candidate` | Candidate / "Shape forming" | `CANDIDATE`, `FORMING` ("still forming; it is not a valid pattern yet"); `GEOMETRY_VALID` ("a valid shape with no breakout yet. A shape alone is not a confirmed signal") | as quoted |
| `awaiting_confirmation` | Awaiting confirmation / "Waiting for proof" | `BREAKOUT_ATTEMPT` (through the level intraday, no close beyond it); or `PRICE_CONFIRMED`, `VOLUME_CONFIRMED`, `CONTEXT_VALIDATED`, `RESEARCH_ELIGIBLE` when the volume component is `FAIL` or not yet `PASS` | "Price went through the level during a session but did not close beyond it." / "Closed beyond the level, but the follow-through volume did not confirm." / "…has not confirmed yet." |
| `confirmed` | Confirmed / "Confirmed" | `PRICE_CONFIRMED` or later **and** the volume component is `PASS` | "Closed beyond the level by the breakout buffer, on follow-through volume in the band." |
| `invalidated` | Invalidated / "Did not hold" | `FAILED` ("price came back through the level"), `INVALIDATED` ("the pattern's invalidation rule fired") | as quoted |
| `expired` | Expired / "Ran out of time" | `EXPIRED` | "The pattern ran past its confirmation window without confirming." |

A status that maps to none gives `state: null`, shown as "— no state" with "The engine reports <status>, which maps to none of the five states." Engine constants relevant to confirmation (`research/charting/config.py`): `breakout_buffer_atr = 0.25`, `relative_volume_supporting = 1.20`, `relative_volume_strong = 1.50`, `confirmation_window_bars = 3`, `require_close_confirmation = True`, `require_volume_confirmation = False`, `minimum_pattern_length = 15`, `maximum_pattern_length = 120`. How these combine inside each detector is in `research/charting/patterns.py`, not read here — unverified beyond the registry text.

### The per-criterion checks (`_criteria`, `research_chart.py:540-605`)

Each pattern card lists eight criteria with a mark: "✓ Passed", "✕ Failed", "… Pending", "– Not judged" (`ChartTab.tsx:702-707`).

| Criterion (`key`) | Judged by | Pass / fail rule | Not judged (`na`) when |
|---|---|---|---|
| Price structure (`price_structure`) | engine | fail if geometry or price component is `FAIL`; pass if both `PASS`; pending if each is `PASS` or `PENDING`; else `na`. Observed: "geometry X · price Y". | engine sent neither |
| Volume (`volume`) | engine | engine's volume component: `PASS` / `FAIL` / `PENDING` → pass / fail / pending | engine sent none |
| Trend (`trend`) | desk rule | bullish pattern: pass if `close > EMA 50 > EMA 200`; bearish: pass if `close < EMA 50 < EMA 200`; otherwise fail. Observed: "close x · EMA 50 y · EMA 200 z". | pattern has no direction; or EMA 50 / EMA 200 missing ("Needs EMA 50 and EMA 200 (at least 200 sessions of bars)") |
| Relative strength (`relative_strength`) | desk rule | bullish: pass if the 63-session excess return versus Nifty 50 is > 0; bearish: pass if < 0 | no direction; or no RS figure ("Needs 64 sessions of the stock and Nifty 50 closes") |
| Volatility (`volatility`) | engine | engine's volatility component (ATR expansion on the breakout) | engine sent none |
| Liquidity (`liquidity`) | desk rule | pass if the 20-session mean traded value ≥ the desk gate, ₹10 Cr a day (`setup_rules.LIQUIDITY.min_traded_value_cr = 10.0`, `BE/services/positional_engine/setup_rules.py:54`); else fail. Threshold is sent with the criterion. | fewer than 20 sessions |
| Market regime (`regime`) | none | always `na`: "The pattern engine has no market context yet (it never sets CONTEXT_VALIDATED)." | always |
| Events (`events`) | none | always `na`: "The live engine does not join corporate events; the stock's filings are listed separately." | always |

A "bullish" or "bearish" direction comes from the engine's `direction` (`BULLISH`/`BEARISH`; anything else, including `NEUTRAL`, is "no direction"). The card also shows the engine's raw rules in a collapsed "The engine's rules (n)" list: `rule_id · result · observed … · threshold …`, and "Detected <date>. Engine status <STATUS>." The "detected on" date is the first event's date, else the formation end.

Footer trust line: "research.charting pattern engine · End of day · <as-of> · Rules-based · engine 0.1.0 · config <8 chars of hash> · registry 1.0.0".

### Pattern block states

| State | Text |
|---|---|
| Loading | "Loading the pattern engine…" |
| Error | "Patterns didn't load" with a Retry |
| 403 | "Patterns — Pattern detection needs the charting feature, which this account does not have." |
| 404 | "Patterns — No daily bars on record, so nothing to detect patterns on." |
| 503 | Label "Pattern states" (investor: "Chart shapes"), "—", and "The pattern engine is not running on this server (<reason>): its research package is not deployed beside the backend, so no state is shown rather than a guess." |
| 200, no patterns | "The engine found no support / resistance, rectangle or higher-high pattern at the last bar (<date>)." |

## A.7 Setup check, "Why it ranks", history tiles (below the chart, desk)

These are scanner-driven and only exist for a stock that is a scanner setup. Otherwise the block says "Not on today's scanner — no levels" with "<SYMBOL> did not pass the end-of-day scanner's rules on the <date> scan, so it has no trigger, stop or target. The chart and indicators still show from its daily bars." (or "The scanner didn't load, so there is no trigger, stop or target for <SYMBOL>…").

- Setup check ("What the chart shows" for investors): up to 7 rows chosen from, in order: breakout level and distance, volume vs 20-day average, RSI, distance to EMA 20, next resistance, next support, higher lows in 20 sessions, 15-day range, ATR % of close, volume trend over 10 sessions, delivery trend over 10 sessions, holding window (`setupLines`, `ChartTab.tsx:452-474`). Colour cut-offs are UI constants (for example volume ≥ 1.5×, RSI ≥ 70 amber / ≥ 55 green, EMA-20 gap between 0 and 4%, 15-day range < 8%). Empty: "The scanner sent no structure figures for this setup."
- "Why it ranks" ("Why it shows up"): the scanner's reason text, "Score n · rules-based", and four rows — Trend (close vs EMA 20; EMA 20 vs EMA 50), Momentum (RSI zone plus volume), Catalyst ("News" — count and latest event from the move-odds model's events on record), Risk ("Watch" — stop distance `(entry − stop) ÷ entry` and that as a multiple of ATR %). "Ask Copilot ›" sends "Explain the <SYM> setup and what would invalidate it" to the desk's Copilot.
- Four history tiles, from `GET /api/positional/backtest/calibration?symbol=&horizon_days=10` (`RECORD_HORIZON = 10`, `chart-data.ts:390`): "Hit rate · n" (the `broke_high` metric in the stock's score bucket: share of scans in that bucket where the intraday high went above the scan-day 20-session high within 10 sessions), "Average move" (mean best move within 10 sessions — labelled "(MFE) — not an average return"), "Reward : risk" (from the scanner's levels; needs target and stop), "Scanner confidence" (the scanner's own grade). Empty reasons: "The historical record didn't load", "Loading the historical record", "No historical record is on file yet", "No accumulation score for this stock, so no bucket to quote", "No record for this stock's score bucket".

## A.8 The watchlist action

Under the chart: `AddToList` (`FE/../workspace/PersonalLists.tsx:573`), the user's own personal lists.

- Renders nothing until the list index has loaded (`if (!index.data) return null`), including when it fails.
- Closed state: "Add to a list ›". Open: "Add <SYMBOL> to [list picker] [Add] [Close]". The first list with room is preselected; a list shows "· full" when it holds 100 stocks (`MAX_SYMBOLS = 100`, `BE/routes/watchlists.py:66`; `MAX_LISTS = 20`, line 65).
- Route: `GET /api/watchlists` for the lists; `POST /api/watchlists/{id}/symbols {symbol}` to add. Stored in MongoDB `user_watchlists` (`watchlists.py:340`).
- Outcomes: "Added to <list>." / "Already in <list>, so nothing changed." / "Not added, so nothing changed — <reason>" / with no lists: "Make a list under "Your lists" first, then add <name> to it." / full list: "<list> has 100 stocks, the most a list holds."
- It is a personal list. It is not the scanner's watchlist and has no alert attached.

## A.9 "Open full chart" and its parameters

The link under the chart (investor: "Open the full chart ↗"). It is a real link (a fresh navigation), built by `fullChartHref` (`chart-data.ts:533`):

`<BASE_URL>research?screen=charts&symbol=<SYMBOL>[&entry=<n>][&stop=<n>][&t1=<n>]`

- `symbol` is upper-cased. `entry`, `stop`, `t1` are added only when the value exists, is finite and is above 0 — an absent target never arrives as 0.
- The levels are `deskLevels(setup, live)`: the scanner's, else the rule-based hypothetical ones (B.7). So the link carries rule levels even though the desk chart does not draw them.
- The Research chart workspace (`frontend-v5/src/pages/Research/charts/ChartsScreen.tsx:81-102`) reads `symbol`, `entry`, `stop`, `t1` (also `t2` and `trade`) once, on mount; `symbol` must match `^[A-Z0-9&-]{1,32}$` or the whole context is ignored. Its levels are drawn as ENTRY, STOP, TARGET_1. It can load a symbol outside the frozen snapshot through the same `chart-live` route (`Research/charts/contract.ts:530`).
- What the full chart adds: drawing tools, saved layouts, pattern overlays (screen-reader note on the link, `ChartTab.tsx:154-156`). Section 7 of the opportunity detail has a second link, "Open full chart with these levels ↗".

## A.10 Symbol search

In the desk header (`FE/../TradingDesk.tsx:105-124, 398-416`), placeholder "Search a stock or ask Nivesh…", label "Search any NSE stock by symbol, or ask Nivesh". On phone it is behind a search toggle button. Rules, applied on Enter:

| Input | Result |
|---|---|
| One word (no spaces, ≤ 20 chars) that equals a scanner setup's symbol, or (≥ 2 letters) starts a scanner setup's symbol — first match in scanner rank order | That scanner stock is selected; the tab stays; a "<SYMBOL> selected" line with a link to its chart appears (`matchSetup`, `:93-101`) |
| Any other single word matching `^[A-Za-z0-9&-]{1,20}$` | Treated as an NSE symbol: the Chart tab opens with `?sym=<UPPERCASE>` (or the symbol changes if already on the Chart tab). No existence check is made in the search; if there are no bars the chart says "No daily prices on record for …". |
| Anything else (words, a question) | Sent to the desk's Copilot as a question |

The search matches only the scanner list by name prefix; there is no company-name search and no suggestions list. The `sym` parameter must pass `^[A-Z0-9&-]{1,20}$` (`TradingDesk.tsx:70`), otherwise it is ignored.

## A.11 What is not available in the Chart tab, and why

| Missing | Reason shown or found in code |
|---|---|
| Intraday intervals, weekly/monthly | No intraday bars collected or readable (A.4); desk uses daily bars only |
| Rule-based levels as chart lines | The chart overlay takes only scanner levels (`ChartTab.tsx:240`) |
| F&O ban list; ASM / GSM surveillance | "Not ingested" (section 6) |
| Market-regime and event criteria for a pattern | Engine has no market context; live engine joins no events (A.6) |
| 16 of 19 pattern families | No detector implemented (A.6) |
| Average / median return, costs, benchmark, out-of-sample for the historical record | Not stored in the record (B.8) |
| Live price | All data end of day |

---

# B. Opportunity detail (ten sections)

Located under the chart card (desk) or at the bottom (phone). Heading "03 · Opportunity detail" (investor: "Everything about this idea"). Sub-line "Ten sections, summaries first; open one for its evidence." (investor: "Short answers first; open a section for the detail."). An "Open all / Close all" button. Each section is a button with a number, a title, a one-line summary, and (when open) its body; all start closed. Component: `OpportunityDetail`, `ChartTab.tsx:894-1273`. Footer trust line: "Positional scanner · move-odds model · data platform · End of day · <scan date> · Rules-based · Each section names its own source; missing figures show — with the reason".

Convention used throughout: a missing figure shows "—" with the reason under it. Nothing is estimated.

Shared reads for the sections: indicators (A.2), patterns (A.2), daily bars, scanner setup, `useDeskOdds("p_up5_1d")` = `GET /api/move-odds/latest?head=p_up5_1d` (`BE/routes/move_odds.py`, DaaS `/v1/move-odds/latest`), `GET /api/move-odds/stocks/{symbol}`, calibration (A.7), `POST /api/copilot/widgets/company_financials {symbol, quarters: 8}` (5-min cache), `GET /api/filings/feed?symbol=&days=30&sort=latest&limit=20`.

Titles (Trader / Investor), `SECTION_TITLES` `:853-864`:

| # | Trader | Investor |
|---|---|---|
| 1 | Prediction definition and horizon | What is being estimated, and for how long |
| 2 | Model score and calibration | The score, and how reliable it has been |
| 3 | Technical evidence | What the chart shows |
| 4 | Fundamental and ownership context | The business and who owns it |
| 5 | Corporate events and news | Company news and filings |
| 6 | Liquidity and tradability | Is it easy to buy and sell? |
| 7 | Hypothetical entry, stop and target | Possible buy, exit and target prices |
| 8 | Historical validation | How similar setups did before |
| 9 | Contradictory evidence | What argues against it |
| 10 | Data freshness and missing inputs | How fresh the data is, and what is missing |

## B.1 Section 1 — Definition and horizon

Summary: "<setup label> · scanner rules · P(+5%) for <session>" or "Not on today's scanner · next-session odds and patterns only".

| Row | Shows | Source |
|---|---|---|
| Scanner setup (rules, not a prediction) | The setup bucket's label (investor words: "Broke above a recent high", "Just under a recent high", "Dipped in an uptrend", "Tight sideways range") and the scanner's rule text | `/api/positional/watchlist` + `/picks` |
| Holding window | `min–max days` of the pick | picks only ("Only the scanner's picks carry a holding window.") |
| P(+5% next session) | "for <target session>" | move-odds run. Text: "The move-odds model's estimate that the next session's high reaches the last close plus 5%. One session only — never a multi-day horizon." |
| Historical outcome | "within 10 sessions" | "Did the stock break its 20-session high within 10 sessions after a scan with a similar score? An intraday touch, not a close and not a trade." |
| Pattern states | "at the last bar" | pointer to section 3 |

## B.2 Section 2 — Model score and calibration

| Row | Shows / rule | Source and as-of |
|---|---|---|
| Scanner score (rules-based, not a probability) | `score / 100`; grade text if present | scanner; scan date |
| P(+5% next session) · model estimate | probability, 1 decimal | `/latest` row `p` for the symbol, else `/stocks/{symbol}` `estimates.p_up5_1d` |
| P(−5% next session) | probability | `/stocks/{symbol}` `estimates.p_down5_1d` only |
| Model version | "Move-odds <model>" and "Refit … · trained to <date> · data as of <date> · for <date> · build <git sha>" | run block of `/latest` or `/stocks/{symbol}` |
| Evaluation period | the run's `record.window_label`, then "Out of sample: top-10 hit rate x% over n sessions vs a base rate of y%. The model's record, not this stock's." | `/latest` `record` |
| Calibration · predicted band → what happened | one line per band: "lo–hi% predicted", "x% realised · n rows" | `record.bands` of `/latest` |

Empty/blocked texts (`oddsWhy`, `:926-930`): "Move probabilities are not enabled for this account." (403); "Withheld: <reason>." (503 withheld); "The model has not published for <date> yet (preview only)."; "Loading the move-odds model."; "The move-odds model didn't load."; "No estimate for <SYM> in the published run."; calibration with no run: "— <reason>"; with a run but no bands: "— The run publishes no calibration bands."; no record: "No out-of-sample record is published with this run."

Facts to note:

- This section prints the probability whenever the route returns it. The scanner tab (`ScannerTab.tsx:991`, `probabilityGate`, `desk-data.ts:603`) withholds the probability column for every stock because the route marks no estimate as "calibrated". The Chart tab's section 2 and the Risk desk do not apply that gate. They show the number, and the Risk desk adds "Not shown as high-confidence" when the gate checks fail (C.3). Whether this difference is intended is not stated in code.
- The calibration bands are the model's own out-of-sample record (a 2025 test window per the gate text), not a per-stock calibration.

## B.3 Section 3 — Technical evidence

Summary: "Above/Below EMA 20 · RSI n · k confirmed, m awaiting" (patterns count) or "Indicators —".

Rows (all from the indicators route, A.5): close versus EMA 20 / 50 / 200 (investor: "Price vs 20 / 50 / 200-day averages"); RSI 14 · MACD histogram · ROC 20; relative strength versus Nifty 50 over 63 sessions (with the benchmark reason when null: "No <Nifty 50> closes on record (nidp.index_eod)." / "…did not load (…)" / "Needs 64 sessions of the stock and Nifty 50 closes on both dates."); relative volume · ATR %. Then the pattern block (A.6).

States: "Loading indicators…"; error block "Indicators didn't load"; no indicator read: "Indicators — The indicator route did not answer for this stock (charting not enabled, or no bars)."

## B.4 Section 4 — Fundamentals and ownership

Source: `POST /api/copilot/widgets/company_financials` → `BE/services/copilot_tools/company_financials.py` (`get_company_overview`): the quarterly results (P&L trend, `nse_financials_quarterly` per the file header), DaaS `/v1/shareholding/{symbol}`, and the latest `stock_features_daily` row (valuation features). The envelope's own "outlook" label and score are deliberately not read (`markets/hooks.ts:325-329`).

| Row | Shows | If missing |
|---|---|---|
| P/E · P/B | `pe_ttm`, `pb` | "No feature row for this stock (stock_features_daily)." or "<what>: not filled on the <date> feature row (stock_features_daily). Figures there come from <source>, as of <date>, and this one is missing." |
| ROE · debt to equity | `roe_pct`, `debt_to_equity` | same pattern |
| Market cap | `₹ n Cr` | same pattern |
| Latest quarter | revenue and profit (₹ Cr), with year-on-year % | "No quarterly results on record (nse_financials_quarterly)." |
| Promoter · <quarter> | promoter %, with the change vs the previous quarter that has holdings | "No shareholding pattern on record." / "Only a pledge figure is loaded for <period>; the exchange's shareholding filing for that quarter is not in the warehouse. Pledged x%." / "The <period> filing gives no promoter holding." |
| FII · DII · mutual funds | three percentages | "Mutual funds: the filing's mutual-fund line is not loaded for this quarter." |

The ownership row uses the newest quarter that has any ownership figure; the pledge shown comes from the very newest row (`:934-940`). Trust line: "NSE quarterly results · shareholding pattern · stock_features_daily · Historical · As reported". Loading: "Loading results and shareholding…"; error: "Results and shareholding didn't load".

Gap matrix B5/B16 and the memory notes record that several `stock_features_daily` columns (market cap, ROE) were unfilled on staging at the time; the current state is unverified.

## B.5 Section 5 — Filings and news

`GET /api/filings/feed?symbol=<SYM>&days=30&sort=latest&limit=20`. Shows up to 8 rows (`slice(0, 8)`): date, document label ("Filing" if none), category, link "Exchange filing (NSE|BSE) ↗", and — when the generated read exists — an amber pill "AI read · not verified" followed by the generated one-line read. Summary: "n filings in 30 days · latest <date>" or "No filings in 30 days". Empty: "Filings · last 30 days — None: No exchange filing for <SYM> in the last 30 days." Loading: "Loading filings…"; error: "Filings didn't load".

The `days` parameter is capped at 30 by the route (`BE/routes/filings.py`, `_MAX_DAYS`).

## B.6 Section 6 — Liquidity, price band and tradability

| Row | Shows | Rule / source |
|---|---|---|
| Traded value · 20 sessions · gate ₹10 Cr (investor: "Money traded a day") | `₹ n Cr` with "Passes" (green) or "Below the gate" (red) | One figure on the page: the scanner's 20-session figure `avg_traded_value_cr_20d` (from `stock_ohlcv`) if the stock is a setup, else the indicator route's `avg_traded_value_cr20` (mean of close × volume over 20 sessions ÷ 1e7, from the adjusted bars). Gate: `LIQUID_MIN_CR = 10` (`desk-data.ts:240`), equal to `setup_rules.LIQUIDITY.min_traded_value_cr` (₹10 Cr, "owner decision 2026-10-14", `setup_rules.py:53-54`). Missing: "Needs 20 sessions of close and volume." |
| Price band | `±n%` or "No price band" | `nidp.security_reference_daily` latest row for the symbol, EQ series first, columns `price_band_pct`, `band_raw`, `fno_eligible`, `is_etf` (`research_chart.py:276-287`). "F&O stocks trade without a daily price band." appears when `band_raw` matches "no band". Sub-line: "Exchange reference data · <as-of date>". Missing: "No row for <SYM> in nidp.security_reference_daily." or "The exchange reference data … could not be read." |
| F&O eligible | Yes / No / — | same row |
| ETF | Yes / No / — | same row |
| F&O ban list | — | "Not ingested: no F&O ban list is on record, so a ban cannot be checked." |
| ASM / GSM surveillance | — | "Not ingested: no surveillance list is on record." |

Summary: "₹n Cr a day · ±b% · F&O ban list —". Whether `security_reference_daily` is populated on staging is unverified (gap matrix B7 says its job was commented out in the staging cron).

## B.7 Section 7 — Hypothetical entry, stop and target

Source line shows which of two sources is used (`deskLevels`, `chart-data.ts:296`):

1. "AI scanner pick" — if the scanner setup has any of entry / stop / target, its levels are used and the rule is not consulted. A watchlist-only setup has `entry = trigger`, `stop`, and `target = null` (`desk-data.ts:257`); picks carry all three plus a risk-reward. A watchlist-only setup therefore shows "Only the scanner's picks carry a target." even though the rule could derive one.
2. "Rule ATR_2X_STOP v1" — only when the stock has no scanner levels at all. Source: `_hypothetical_levels` (`BE/routes/research_chart.py:371-409`), returned as `hypothetical_levels` by the indicators route.

### The rule `ATR_2X_STOP`, version "1"

Constants (`HYPOTHETICAL_RULE`, `research_chart.py:372-373`; the code says "Change a constant here and bump VERSION"):

| Constant | Value |
|---|---|
| `atr_multiple` | 2.0 |
| `min_stop_atr` | 0.5 |
| `reward_multiple` | 2.0 |
| `atr_period` | 14 |

Label printed with it: "Rule-based hypothetical levels, not a scanner pick and not a recommendation" (line 374).

Formula, computed on the same adjusted bars as the indicators (after any unadjusted-split cut):

```
entry   = last close
ATR     = Wilder ATR(14)
stop    = entry − 2.0 × ATR                      (basis "atr")
support = lowest low of the last 20 sessions (includes the last bar)
if  stop < support <= entry − 0.5 × ATR:
        stop = support                           (basis "support20")
if stop <= 0: no levels
risk    = entry − stop
target  = entry + 2.0 × risk
reward : risk = 2.0 (always)
```

The 20-session low replaces the ATR stop only when it is higher than the ATR stop (a tighter stop) and still at least half an ATR below the entry.

What the section prints: Source ("Rule ATR_2X_STOP v1" with the label), Entry ("The last close."), Stop (either "The 20-session low, closer than the ATR stop." or "2.0 × ATR(14) below the entry."), Target ("Entry plus 2.0 × the risk."), Reward : risk ("2.0 : 1"), and "Size them in the risk desk; nothing is sent to a broker." with the "Open full chart with these levels ↗" link. Investor labels: "Buy above", "Exit if wrong", "Reward for risk".

When there are no levels: reason strings from the route: "ATR(14) needs 15 sessions and n are usable, so no stop can be derived." or "The ATR stop would be at or below zero, so no levels are derived."; if the indicator read is absent: "No indicator read, so no rule-based levels."; if the route sent none: "The indicator route did not publish rule-based levels." Summary then reads "No levels".

The Risk desk repeats the rule in one line (`RiskDesk.tsx:872-876`).

## B.8 Section 8 — Historical validation

Source: `GET /api/positional/backtest/calibration?symbol=&horizon_days=10` (`BE/routes/positional.py:1246`) → table `accumulation_calibration` (positional engine Postgres), the labelled period from `positional_backtest_labels`, the stock's latest accumulation score from `stock_technical_features.components.pre_breakout.accumulation_score`. Method (from the route): each (symbol, scan date) is replayed with the bars known that day, then the next 5 / 10 / 20 sessions are checked; scans are bucketed by accumulation score. The desk reads horizon 10 only.

Rows shown for the buckets that contain the stock's score (`matched`):

| Item | Meaning |
|---|---|
| Accumulation score | the stock's latest score, "As of <date>; the record below is for scans in the same score bucket." |
| Per outcome metric (`broke_high`, `moved_scaled`, `moved_5pct`) | occurrences (`sample_count`), hit rate, 95% interval, mean best move (MFE) and mean worst move (MAE), plus the rule text. Interval = Wilson score, z = 1.96 (`_wilson_ci`, `positional.py:1229`). All outcomes are intraday touches. |
| Holding period | "10 sessions": "Every row checks the sessions after the scan day; no exit rule is simulated." |
| Average return, Median return, Transaction costs, Benchmark comparison, Out-of-sample | always "—" with the route's `not_measured` text: median return "Not stored: the labeller keeps each scan's maximum excursion, not a realised exit return"; costs "None applied: the labels are price-only, with no brokerage, slippage or taxes"; benchmark "None: the labels are not compared with an index over the same sessions"; out-of-sample "None: the buckets are fitted on every labelled scan; no later period is held out. Treat the hit rates as in-sample." (`positional.py:1220-1226`) |
| Sample period | first–last scan date and the number of labelled scans and engine versions |

Closing line: "The accumulation detector's record, bucketed by accumulation score — scans like this one, not this setup's own trades." Summary: "Hit rate x% · n N (touch, 10 sessions)" or "— No record for this stock's bucket".

Empty reasons (first non-empty of): `empty_reason`, `symbol_reason`, `_reason`, "No record row for this stock's score bucket." The route's own reasons include "No labelled scans on record (positional_backtest_labels is empty)." and "No accumulation score on record for <SYM> (stock_technical_features is empty for it)…". Whether staging has these tables filled is unverified (gap matrix and memory notes say the scanner tables were empty on staging when written).

## B.9 Section 9 — Contradictory evidence

Rules-based checks; each point names the figure behind it and a source tag. If none is found: "Points against: None found — None of the checks below found evidence against the setup. That is not evidence for it." A "Could not check: …" line lists checks whose input was missing. Footer line lists all checks. Constants: `PLEDGE_FLAG_PCT = 5` (`ChartTab.tsx:59`), `LIQUID_MIN_CR = 10`.

| Key | Fires when | Needs |
|---|---|---|
| `below-ema200` | close < EMA 200 | indicators; unchecked "Long-term trend (needs 200 sessions for EMA 200)" |
| `overbought` | RSI 14 ≥ 70 | indicators |
| `weak-rs` | 63-session excess vs Nifty 50 < 0 | indicators; unchecked "Relative strength (Nifty 50 closes did not load)" |
| `thin-volume` | scanner status is `confirmed` and RVOL < 1 | indicators + scanner |
| `pat-<id>` | pattern state `invalidated` or `expired` | patterns; unchecked "Pattern failures (the pattern engine did not answer)" |
| `crit-<id>` | pattern `awaiting_confirmation` or `confirmed` with any criterion `fail` | patterns |
| `odds-down` | P(−5%) ≥ P(+5%) | both model estimates; unchecked "Down-move odds (no published estimate for this stock)" |
| `illiquid` | 20-session traded value < ₹10 Cr | liquidity figure; unchecked "Liquidity (no 20-session traded value)" |
| `gap` | largest opening gap in the last 64 bars (63 gaps) ≥ the stop distance `(entry − stop) ÷ entry` | scanner entry and stop (not rule levels) and bars |
| `past-target` | last close ≥ scanner target | scanner levels |
| `past-stop` | last close ≤ scanner stop | scanner levels |
| `profit-fall` | latest quarter's profit year-on-year change < 0 | results; unchecked "Results trend (no quarterly results on record)" |
| `pledge` | promoter pledge ≥ 5% | shareholding |

Largest gap = `open ÷ previous close − 1` (percent, signed), the biggest by absolute value (`FE/indicators.ts:30-38`). Summary: "n point(s) against" or "None found among the checks". Investor text differs only for the EMA 200 point.

## B.10 Section 10 — Data freshness and missing inputs

A list of ten sources with an as-of date or "—" and a reason line:

| Source row | As-of shown |
|---|---|
| Daily bars · nidp.prices_eod_adjusted | last bar date |
| Indicators · stock_features_daily engine | indicator `as_of` |
| Patterns · research.charting | pattern `as_of` |
| Scanner · positional engine | scan date (or "Watchlist <date> · picks <date>" if the two routes differ) |
| Move-odds model | run `data_as_of` |
| Quarterly results | latest quarter label |
| Shareholding pattern | latest period with holdings |
| Exchange filings | newest filing date |
| Price band · security_reference_daily | reference date |
| Historical record · accumulation backtest | last labelled scan date |

"Missing inputs" lists every row with no as-of (by its short name) plus four fixed items: "Intraday bars", "F&O ban list", "ASM / GSM lists", "Market-regime and event context for patterns". Summary: "n of 10 sources on record · m missing inputs". Closing line: "Everything here is end of day or older; nothing on this page is live."

## B.11 What the detail does not have

No actual fundamental valuation model, no peer comparison, no analyst estimates, no news feed beyond exchange filings, no intraday or order-book data, no surveillance lists. The "model score" is the scanner's rules-based score, labelled as not a probability.

---

# C. Risk desk

Desk: card "05 · AI Risk desk" to the right of the chart. Phone: card "05 · Trade scenario" (a reduced version: no range bar, no gate, no alert button, no "Edit the scenario" open by default). File `FE/RiskDesk.tsx`. Header lists its reads and writes (`:1-33`).

## C.1 What it shows, top to bottom (desk)

1. Status pill from the scanner: "Confirmed", "Awaiting confirmation" or "Forming" (`RISK_STATUS`, `:80`).
2. "Scenario · <SYM>" (investor: "Idea") with the setup label or "Not on today's scanner"; Reward / risk (large number "n.n : 1", or "—").
3. Range bar (when entry > stop): stop → entry in red, entry → target in green with width proportional to reward ÷ risk, and a marker for the last close. Marker text adds " · below the stop", " · above the target" or " · above the entry" when applicable. Without a target only the red part is drawn. Under it: "Stop ₹…", "Entry ₹…", "Target ₹…" or "No target" (investor: "Exit if wrong", "Buy above").
   - If there are no levels: scanner stock without a usable entry/stop: "This setup has no entry with a stop below it, so there is no range to draw. Enter levels under "Edit the scenario" to size one."; non-scanner stock with no rule levels: "Not on today's scanner — no levels. The scanner suggests an entry, stop and target only for stocks that pass its end-of-day rules, and nothing is made up for the…" (text continues in the file, `:869`).
   - If levels come from the rule: one line "<label>. Rule ATR_2X_STOP v1: entry = last close; stop = 2 × ATR(14) below it, or the 20-session low when that is closer; target = entry + 2 × the risk. These levels are…" (`:874`; the tail of the sentence is cut in the line read — unverified).
   - If the setup has an entry but no target: "Reward / risk needs a target; only the scanner's picks carry one."
4. Two stat tiles: "Move probability" (investor: "Chance of +5%") and "Trade win rate" (always "—": "No back-tested win rate for this setup is published.").
5. An explanation paragraph plus the model's out-of-sample record line.
6. The validation gate (C.3).
7. "Position size" (investor: "How much to buy") with Capital and Risk chips and the 2 × 2 size tiles (C.4).
8. The stop caveat line.
9. "Edit the scenario" disclosure (C.2), and the portfolio block (C.7).
10. The four checks (C.5).
11. Paper trade and alert buttons (C.6).
12. Trust line: "Positional scanner levels · scenario route (server) · End of day · <scan date> · Rules-based · PRD §8.5 sizing · costs 0.05% + ₹20 a side (strategy_engine)"; status "Source failed" if the scenario route errored.

## C.2 The scenario calculator

### Inputs

Editable under "Edit the scenario — levels, capital, limits and costs" (investor: "Change the numbers"). It opens by itself when a typed field is wrong or the server rejects a direction; it starts open when the stock is not a scanner setup. Defaults (`RiskDesk.tsx:47-69`):

| Field | UI label (investor) | Default | Front-end validation (`readFields`, `:340-379`) | Query param |
|---|---|---|---|---|
| Entry | Entry ₹ ("Buy at ₹") | the levels' entry | required, > 0 | `entry` |
| Stop | Stop ₹ ("Exit if wrong ₹") | levels' stop | required, > 0 | `stop` |
| Target | Target ₹ | levels' target | optional, > 0 | `target` (only if set) |
| Capital | Capital ₹ ("Money you have ₹") | ₹5,00,000; quick chips ₹2L, ₹5L, ₹10L | required, > 0 | `capital` |
| Risk per trade % | ("Willing to lose") | 1; chips 0.5%, 1%, 2% | required, > 0, ≤ 100 | `risk_pct` |
| Max allocation % | ("Most in one stock") | 25 | required, > 0, ≤ 100 | `max_alloc_pct` |
| Slippage a side % | | 0.05 | 0 to 5 | `slippage_pct` |
| Brokerage a side ₹ | | 20 | ≥ 0 | `brokerage_per_side` |
| Max shares | | blank | optional, positive whole number | `max_qty` |
| Lot size | | 1 | positive whole number | `lot_size` |
| Portfolio value, stock value, sector value | | from the user's holdings (C.7) | — | `portfolio_value`, `existing_value`, `sector_value` |

Input handling: commas, "₹" and spaces are stripped; a non-number is flagged. Changing stock re-seeds entry/stop/target from that stock's levels and keeps the sizing choices. A "Back to the scanner's levels" / "Back to the rule's levels" link appears once levels are edited. Typing is debounced 300 ms; the previous answer stays (dimmed to 60% opacity) until the new one arrives; answers are cached 5 min (`chart-data.ts` `useScenario`). The route is `GET /api/positional/scenario`; the client sends only the fields that are set (`scenarioQuery`).

Problem list: front-end problems and the server's `problems` are shown together in a red box with `role="alert"`.

### Server rules (`BE/routes/positional.py`, `_trade_scenario` from line 1583; route at 1726; long only)

Cost-model constants (`BE/services/strategy_engine/backtest.py:54-55`): `DEFAULT_SLIPPAGE_PCT = 0.0005` (5 bps a side), `DEFAULT_BROKERAGE_INR = 20.0` (flat per side). Used when a request omits them; the desk always sends its field values.

Validation of price directions (a 200 response with `valid: false` and `problems`; malformed numbers are 422), `positional.py:1618-1640`:

| Code | Field | Condition | Message |
|---|---|---|---|
| `entry_not_positive` | entry | entry ≤ 0 | "The entry must be a price above zero." |
| `stop_not_positive` | stop | stop ≤ 0 | "The stop must be a price above zero." |
| `stop_not_below_entry` | stop | stop ≥ entry | "For a long position the stop (₹s) must be below the entry (₹e)." |
| `target_not_above_entry` | target | target given and target ≤ entry | "For a long position the target (₹t) must be above the entry (₹e)." |
| `needs_capital_or_risk_budget` | risk | no positive risk budget | "Give a risk budget in rupees, or a capital with a risk per trade." |

Query-level limits: `entry`, `stop`, `target`, `capital`, `risk_budget`, `portfolio_value` > 0; `risk_pct` in (0, 100]; `max_alloc_pct` in (0, 100], default 25; `slippage_pct` 0–5; `brokerage_per_side` 0–100,000; `max_qty` ≥ 1; `lot_size` ≥ 1; `side` must be `long`. On `valid: false` no figures are returned (`per_share`, `sizing`, `costs`, `outcomes`, `portfolio` are null).

### Formulas (with `eps = 1e-9` to stop float noise dropping a share; `positional.py:1645-1700`)

```
risk budget          = capital × risk% ÷ 100            (or the given risk_budget ₹)
risk per share       = entry − stop
reward per share     = target − entry                    (when a target is given)
reward : risk        = reward per share ÷ risk per share
qty by risk          = floor(risk budget ÷ risk per share)
qty by allocation    = floor(capital × max alloc% ÷ 100 ÷ entry)      (when capital given)
quantity             = min(qty by risk, qty by allocation, max qty)   (the ones that exist)
binding limit        = the limit that gave the minimum; on ties the first of
                       risk_budget, max_allocation, max_qty
lot rounding         = if lot size > 1: quantity = floor(quantity ÷ lot) × lot;
                       binding becomes "lot_size" if that changed it
gross exposure       = quantity × entry
allocation %         = gross exposure ÷ capital × 100
slip                 = slippage% ÷ 100
entry cost           = quantity × entry × slip + brokerage
exit cost at stop    = quantity × stop × slip + brokerage
exit cost at target  = quantity × target × slip + brokerage      (when target given)
round trip at stop   = entry cost + exit cost at stop
round trip at target = entry cost + exit cost at target
loss at stop         = quantity × risk per share
loss at stop, net    = loss at stop + round trip at stop
profit at target     = quantity × reward per share
profit at target, net= profit at target − round trip at target
```

If `quantity` is 0 the response has a warning `no_whole_share`: "The risk budget (₹b) is smaller than one share's risk (₹r), so no whole share fits." and no costs or outcomes. All amounts are rounded to 2 decimals in the response.

Arithmetic illustration (not a live value): capital 5,00,000, risk 1%, entry 100, stop 95, 25% cap → budget ₹5,000; risk per share ₹5; qty by risk 1000; qty by allocation floor(500000 × 0.25 ÷ 100) = 1250; quantity 1000 (binding: risk budget); gross ₹1,00,000 (20% of capital); entry cost 1000 × 100 × 0.0005 + 20 = ₹70; exit cost at stop 1000 × 95 × 0.0005 + 20 = ₹67.50; round trip ₹137.50; loss at stop ₹5,000 gross, ₹5,137.50 net.

Not modelled: taxes, exchange charges, STT, GST (caveat: "Costs are estimates from the strategy_engine model (slippage per side plus a flat brokerage per side); taxes and exchange charges are not included."). Short positions are not offered.

### What the outputs show (`ScenarioOutputs`, `RiskDesk.tsx:503-526`)

Downside a share (entry − stop); Upside a share (target − entry; "No target entered."); Reward : risk; Illustrative quantity ("Limited by the risk budget: risk budget ₹b → n shares; 25% cap → m shares; max k; lots of L."); Gross exposure with "% of capital"; Estimated costs · round trip ("₹a at the stop · ₹b at the target" or "no target") with "0.05% slippage + ₹20 brokerage a side (strategy_engine cost model); taxes not included."; Loss at the stop ("−₹n after costs", "−₹m before costs"); Profit at the target after and before costs. Warnings appear in amber. Binding limit words: "the risk budget", "the maximum allocation", "the maximum quantity", "the lot size".

States: "Working it out…" (waiting); error block "The scenario didn't compute" with Retry; invalid → only the problem list; the answer is dimmed while a newer request is pending. The response always carries `sent_to_broker: false`.

The formula line (`desk-risk-formula`): "₹capital × risk% = ₹budget at risk ÷ ₹risk-per-share (entry − stop), capped at 25% of capital. Costs: …".

## C.3 The validation gate ("Validation gate · model checks")

Five checks about the move-odds model run and the stock's liquidity — explicitly not the historical validation (that is section 8) (`useRiskFigures`, `RiskDesk.tsx:167-252`). A check is judged only if its source answered; otherwise it shows "–" and is not counted as passed. The header shows "n of 5 passed" (always out of 5), or "—" when none could be judged.

| Check | Trader / Investor label | Value shown | Passes (`ok`) when |
|---|---|---|---|
| `published` | Model run for the next session / "Model ran for the next day" | target session date, or "Not published yet" / "Withheld" / "—" | a run exists = pass; withheld = fail; not published or not loaded = not judged |
| `record` | Out-of-sample record / "Tested on past data" | "n sessions" | the `/latest` response carries a `record` = pass; absent = fail; model not `final` = not judged |
| `edge` | Top-10 hit rate above base rate / "Beat the average stock" | "x% vs y%" | `record.top10_hit_rate > record.base_rate` |
| `events` | Events on record · SYM / "News or filings on record · SYM" | count of events the model has on record | count > 0 (0 events = fail) |
| `liquidity` | Liquidity · ADV ≥ ₹10 Cr / "Easy to trade · ₹10 Cr+ a day" | "₹n Cr a day" | scanner's 20-session traded value ≥ ₹10 Cr; not a scanner stock = not judged |

With none judged: "None of these checks applies yet: the model has not published a run and the stock is not on the scanner. "—" means not judged, not failed."

Effect on the probability tile: the P(+5% next session) number is shown whenever the model has one. It turns green and carries "<head> · <session> · base rate x%" only if all 5 checks passed; otherwise the note is "<head>. Not shown as high-confidence: n of 5 gate checks passed." Other notes: "Move probabilities are not enabled for this account." / "Withheld: <reason>." / "The model has not published for <date> yet." / "Loading the move-odds model." / "The move-odds model didn't load." / "No estimate for <SYM> in the published run." Explanatory paragraph: probability = "the move-odds model's estimate that the next session's high reaches the last close plus 5%, one session only".

## C.4 Position size (the 2 × 2 tiles)

`SizeTiles` (`:693`): Quantity ("Shares", with "shares · limited by …"), Capital used ("Money used": gross exposure and % of capital, amber when the allocation cap binds), Max loss ("If wrong": net loss at stop, with gross in brackets), At target ("If right": net profit, with gross; "No target on this scenario"). Chips for capital (₹2L / ₹5L / ₹10L) and risk (0.5 / 1 / 2%) drive the same fields as the editor. If inputs are invalid: "Sizing needs an entry with a stop below it, a capital and a risk per trade; see the problems under "Edit the scenario"." If the quantity is 0: "The risk budget is smaller than one share's risk, so no whole share fits." Stop caveat under it (from the server's first caveat): "A stop price does not guarantee the exit price: a gap or thin trading can fill the exit beyond the stop, so the loss can be larger than shown."

## C.5 The four checks (`riskChecks`, `:580-624`)

Computed only from a current, valid scenario; "–" (not judged) otherwise.

| Check | Rule | Text |
|---|---|---|
| Position size | needs quantity and outcomes | "₹budget at risk (r% of ₹capital); max loss ₹n at the stop after costs." Otherwise "— The risk budget fits no whole share." / "— Needs an entry with a stop below it, a capital and a risk per trade." |
| Concentration | with portfolio: `stock_weight_after_pct` > the max-allocation limit → amber | "x% of your portfolio after the buy (y% now), above/within the 25% limit." Without a portfolio: "The 25% single-stock limit caps it at n shares (x% of capital); the risk budget alone would buy m." if the cap binds, else "x% of capital, within the 25% single-stock limit." |
| Correlation | never computed | "— Not worked out for a new position; your holdings' correlations are on Portfolio & risk." |
| Gap risk | largest opening gap over the last `GAP_SESSIONS = 63` sessions (`:69`, from the chart bars) compared with the stop distance; amber when `abs(gap) ≥ stop distance` | "Largest opening gap in the last 63 sessions: x% (date); the stop is y% below the entry, so a gap that size would jump past it." Without bars: "— Needs the stock's daily bars." |

## C.6 Paper-trade and alert buttons

The only writes on the screen (`DeskActions`, `RiskDesk.tsx:1012-1096`). Footer note: "Paper trade only. Nivesh reads broker positions and cannot place orders." Neither button sends anything to a broker.

### "Add to paper trades"

- Enabled only when: the stock is a scanner setup with `entry > stop`; the scenario is valid and current; and the quantity is ≥ 1. Disabled reasons printed under the button: "Needs a scanner setup: this stock has no entry or stop." / "Needs an entry with a stop below it; this setup does not have both." / "The scenario didn't compute, so there is no quantity to add." / "Fix the scenario's inputs first." / "Working out the quantity…" / "The risk budget fits no whole share; pick more capital or a larger risk." A stock with only rule-based levels cannot be added (the gate looks at the scanner setup).
- Request: `POST /api/desk/paper-trades` with `{symbol, quantity (the scenario's), entry_price, stop_price, target_price (only if above the entry, else null), source: {kind: "scanner", bucket?, signal_date?}}`. The entry, stop and target sent are the (possibly edited) scenario fields, not the setup's. `signal_date` is the picks' signal date if the stock is in the picks, else the watchlist as-of date. No entry rule is sent, so the server uses `at_once`.
- Server (`BE/routes/desk_trading.py:85`, `BE/services/desk_trading.py`): per-user MongoDB `desk_paper_trades`; long only; symbol `^[A-Z0-9&-]{1,20}$`; quantity a whole number 1 to 1,000,000 (`MAX_QUANTITY`); prices positive and ≤ ₹1 crore (`MAX_PRICE = 10_000_000`); `stop < entry`; `target > entry`; at most 100 open trades (`MAX_OPEN_TRADES`, 409 `open_trade_limit`); rules version `desk-paper-v2`; the cost model (0.05% + ₹20 a side) is stored on the trade.
- After it is added the trade is marked on end-of-day bars of raw traded prices (`nidp.prices_eod` via the data platform, not the split-adjusted series), from the first session after the IST date it was opened: a low at or below the stop closes it at the stop; a high at or above the target closes it at the target; a session that touched both counts as the stop. A gap through the stop still fills at the stop, flagged. These marks and exits appear on the Portfolio & Risk tab (part 3 of this documentation).
- Success: "Paper trade added: n SYM at ₹p. No order is placed." with "See your paper trades ›". Failure: "Not added — <server wording> (code)". Server wordings (`desk-trading.ts:55-87`) include "You have the most open paper trades allowed (100). Close one first.", "The stop must be below the entry.", "The target must be above the entry.", "The quantity must be a whole number from 1 to 10,00,000."

### "Alert on trigger" (desk only; not on the phone)

- Enabled when the setup has a trigger or an entry: level = `setup.trigger ?? setup.entry`. Otherwise "Needs a trigger or an entry level; this stock has neither on today's scanner."
- Request: `POST /api/desk/alerts {symbol, condition: "above", level}`. Meaning (printed): "Watches for a session whose high reaches ₹level (the trigger|entry), checked after each close. Shown in your alerts list only."
- Server: condition `above` fires when a session's high ≥ the level on end-of-day bars from the first session after the IST date the alert was made (`desk_trading.py:667 find_alert_fire`). Dedupe, limits and reasons: see D.7.
- After success the button reads "Alert set ✓" and stays disabled for that stock; text "Alert set: SYM above ₹x, checked against end-of-day highs." with "See your alerts ›". Failure: "Not set — <wording>" (for example "You already have this alert, and it is still active." / "You have the most active alerts allowed (50). Delete one first.").

## C.7 Portfolio-aware analysis (PRD §8.6)

Block "Portfolio fit · your holdings" (investor: "Your portfolio and this idea"); on the phone it sits inside the "Edit the scenario" panel.

Source: `GET /api/portfolio/holdings-enriched` (`BE/routes/portfolio.py:73`), the user's synced or uploaded holdings. Direct stocks only: rows whose `asset_type` is "equity" or "stock"; the stock is matched by `nse_symbol`, the sector by the case-insensitive equality of the holding's `sector` and the scanner's sector for the stock. Mutual funds and ETFs are not looked through.

| Row | Rule |
|---|---|
| Existing exposure · SYM | sum of `value_rs` of matching holdings across accounts; "x% of the portfolio, all accounts" (= value ÷ total portfolio value × 100), or "None" / "Not in your holdings." |
| Sector exposure · <sector> | sum of values of direct stocks in the same sector ÷ portfolio value; after the buy from the server; "— The scanner gives no sector for this stock." when none |
| Related holdings | up to 5 other holdings in that sector with weights, "+n more"; "No other stock you hold is in this sector." |
| Incremental concentration | from the scenario route: `before% → after%` where, with `ex` = existing value, `P` = portfolio value, `g` = gross exposure: before = ex ÷ P × 100; after = (ex + g) ÷ (P + g) × 100; change = after − before. Assumption printed: "The buy is new money added to the portfolio; weights are of the portfolio after the buy." Sector weights use the same formula with the sector value. |
| Scenario impact on portfolio value | `−loss at stop (net) ÷ P × 100` and `profit at target (net) ÷ P × 100`, "Net of costs, against a portfolio of ₹P." |

States: "Loading your holdings…"; error "Your holdings didn't load" with a Retry; empty (no holdings or total value ≤ 0): "No portfolio on record, so there is nothing to weigh this idea against. Connect a broker (read-only) or upload your holdings on Portfolio & risk." Limits note: "holdings as last synced or uploaded; sectors matched by name; mutual funds and ETFs not looked through; correlation with your holdings is not worked out for a new stock. Informational only — nothing is rebalanced or traded."

The portfolio figures are passed to the scenario route as `portfolio_value`, `existing_value`, `sector_value` (only when state is "ok" and total > 0). As-of is whatever the holdings sync time is; this block does not display it — unverified how fresh the holdings are.

## C.8 Not available in the Risk desk, and why

| Missing | Why |
|---|---|
| Trade win rate | "No back-tested win rate for this setup is published." |
| Correlation of the new stock with the holdings | Not computed for a candidate; per-holding correlations live on Portfolio & risk |
| Short trades | Route accepts `side=long` only |
| Taxes and exchange charges in costs | Not in the strategy_engine cost model |
| Order placement | None; "Nivesh reads broker positions and cannot place orders" |
| Paper trade or alert for a stock with only rule-based levels | The buttons gate on the scanner setup (paper trade: entry and stop; alert: trigger or entry) |

---

# D. Market Intelligence tab

Tab id `intel`, label "Market Intelligence". Title "04 · AI Event intelligence" with "NSE · BSE · SEBI · linked to the scanner" (phone: "04 · Top market events", "Tap for why"). Desk: chips, then a two-pane list (events on the left, the selected event's detail on the right), a sources line, then the "Your alerts" card. Phone: chips, a list where tapping an event expands it, a "Sector impact · 1D" card, "Your alerts". File `FE/IntelTab.tsx`, data `FE/intel-data.ts`.

## D.1 The event list and its sources

| Source | Route | Underlying table / source | Window and limits (constants) |
|---|---|---|---|
| Classified filings (NSE and BSE) | `GET /api/filings/feed?days=7&sort=latest&limit=&provenance=1[&category=][&family=]` (`BE/routes/filings.py:287`) | `nidp.corporate_announcements` (classifier category `event_category`), the generated read from the stage-7 `filing_insights` output; with `provenance=1`: the filing's source records, exchange publication time, Nivesh ingestion time, resolved NSE symbol, market timing (`v_event_asof`), sector, same-industry peers, classifier version (DaaS `/v1/desk/event-sources`) | `FEED_DAYS = 7` (`intel-data.ts:65`); route caps `days` at 30 and `limit` at 120; `LIMIT_SINGLE = 40`, `LIMIT_GROUPED = 20` (used when a chip reads more than one category or family) |
| Filings by the exchange's own subject line | same route with `family=calls|ownership|exchange` | DaaS `/v1/desk/filings` (`daas/desk_market.py`) | same |
| SEBI circulars and master circulars | `GET /api/markets/circulars?days=30&limit=50` (`BE/routes/circulars.py:33`) | `nidp.sebi_circulars`, filled from SEBI's RSS feed every 3 h Mon–Sat plus a one-off backfill; enforcement orders and recovery notices are never stored | `CIRCULAR_DAYS = 30`, limit 50 |
| Bulk and block deals | `GET /api/markets/deals?days=5&kind=all&limit=200` (`BE/routes/markets_desk.py:70`) → DaaS `/v1/desk/deals` | `nidp.bulk_deals`, `nidp.block_deals`; the window is `days` calendar days ending at the latest deal date across both tables | `DEAL_DAYS = 5`, `DEAL_LIMIT = 200` |
| FII / DII net cash flows | `GET /api/markets/fii-dii?days=90` (`BE/routes/markets.py:540`) | `nidp.fii_dii_flows` (NSE provisional), ₹ crore | 90 days fetched; the chip lists the latest `FLOW_SESSIONS = 10`; "All" takes 5 |
| Sector index moves | `GET /api/markets/sector-returns` → DaaS `/v1/desk/sector-returns` | `nidp.index_eod`, 20 sectoral indices (`SECTOR_INDICES` in `daas/desk_market.py`); `ret_1d = close ÷ the close one row earlier in that index's own series − 1` | an index is listed if `abs(1-day return) ≥ SECTOR_MOVE_MIN = 1` percent |

The list is merged newest first. Filings sort by their timestamp; date-only items (deals, flows, circulars, sectors) count as the end of that IST day (`sortTime`). Times shown: "HH:mm" (24 h IST) for items from today, otherwise "13 Oct". Items with no date sort last. The list shows 12 at a time with "Show more" (`PAGE = 12`). Count line, for example: "12 of 37 events · newest first · 30 filings (41 records; repeats consolidated) of 55 in the last 7 days, the 5 largest deals of the last 5 days, the 5 latest SEBI circulars, the 5 latest FII / DII sessions" (`countLine`, `IntelTab.tsx:260`).

On "All" the non-filing sources are limited to `ALL_TAKE = 5`: the 5 largest deals by value, the 5 latest circulars, the 5 latest FII / DII sessions. "All" reads the route's default filing mix (`category` omitted).

State texts: loading "Loading market events"; all sources failed "Market events didn't load" (with Retry); partial failure "<Sources> didn't load; the rest are listed" (`desk-intel-partial`); the provenance lookup failing: "The filings' source records could not be read, so ingestion times, sectors and related companies are not shown." Empty list "No events here yet" with a per-chip body (D.3). The deals/circulars/sector routes answer 502 `upstream_unavailable` when the data platform is down, never an empty or older list.

## D.2 Duplicate consolidation (`consolidate`, `intel-data.ts:510-543`)

NSE and BSE publish separate rows with no shared id. Two filings with a resolved symbol are merged into one event when, comparing with any member of an existing group of the same symbol:

- they come from different exchanges and were filed within `DUPLICATE_WINDOW_MIN = 10` minutes of each other; or
- they come from the same exchange, have the same subject (compared after lower-casing and removing punctuation) and the same IST day.

No record is dropped. The merged event lists every record under Sources and shows an indigo "n sources" pill. The NSE copy leads; if none is NSE, the earliest filed. The lead's AI read, sector, peers and timing are kept, else taken from another member. Only filings are consolidated; deals, circulars, flows and sector moves pass through. A filing with no resolved symbol is never merged. The footer note says: "The same filing on NSE and BSE (same company, within 10 minutes) is one event with both…".

## D.3 The twelve categories (chips) — `INTEL_CHIPS`, `intel-data.ts:132-151`

"All" plus the PRD's twelve categories. Eleven are on a real source; one is disabled.

| Chip | Reads | State |
|---|---|---|
| All | default filing mix, 5 largest deals, 5 latest circulars, 5 latest FII / DII sessions | on |
| Announcements | filing categories `management`, `capex`, `qip`, `rating` | on |
| Results | `earnings` | on; offers "Alert me on the next results filing" |
| Calls & guidance | filings whose exchange subject is an analyst or investor meet, a call, a transcript or an investor presentation (family `calls`) | on |
| Orders | `orders` | on; offers "Alert me on the next orders filing" |
| M&A & actions | `mna`, `dividend`, `buyback` | on |
| Ownership | filings under SEBI's takeover (SAST) and insider-trading rules, pledges, shareholding (family `ownership`) | on, with a stated gap: "Promoter and insider trades from NSE's SAST / PIT disclosure files are not loaded yet (nidp.insider_sast is empty); these are the companies' own filings." |
| Bulk & block | NSE bulk and block deals | on |
| FII / DII | NSE provisional cash flows | on |
| Regulatory | filing categories `regulatory`, `litigation`, plus SEBI circulars | on |
| Sector | NSE sector indices that moved ≥ 1% in the last session | on, with a stated gap: "No sector news feed is ingested. These are NSE sector indices that closed 1% or more up or down in their last session." |
| Macro | — | **disabled**: "No macro-economic calendar (RBI policy, inflation, GDP dates) is ingested, so there are no macro events to list." The chip is drawn struck through; clicking it opens the empty panel "Macro: not available" with that sentence. No request is made. |
| Exchange notices | the companies' answers to the exchange's surveillance queries (family `exchange`) | on, with a stated gap: "F&O ban lists and ASM / GSM surveillance lists are not ingested, so trading restrictions are not listed; these are the companies' own answers to the exchange's queries." |

A hidden chip "Corporate" (all corporate categories) exists in code but is not drawn.

Empty-list texts (`emptyText`, `IntelTab.tsx:297`): FII / DII "No FII / DII sessions are on record right now."; Bulk & block "No bulk or block deals are on record in the last 5 calendar days."; Regulatory "No regulatory or legal filings in the last 7 days and no SEBI circulars in the last 30."; Sector "No NSE sector index moved that much in its last session."; Calls / Ownership / Exchange "No filings of this kind in the last 7 days."; others "No classified filings of this type in the last 7 days."

Classifier categories (`CATEGORY_LABEL`): earnings → Results, orders → Order, mna → M&A, capex, management, dividend, buyback, qip → QIP, rating, litigation, regulatory, other, "markets" → Unclassified (the articles query uses "Markets" for a filing the classifier has not labelled yet).

Event groups and their type line: Results (`earnings`), Corporate · <category> (every other classifier category and the `calls`/`ownership` families, which show "Call / guidance" and "Ownership disclosure"), Regulatory (`regulatory`, `litigation` → "Regulatory · Litigation", SEBI circulars → "Regulatory · SEBI circular"/"master circular"), FII / DII, Bulk & block (type "Bulk deal" / "Block deal"), "Sector move", "Exchange notice"/"Exchange query".

## D.4 Event fields

### In the list row

Time; type line (colour by group); title; a one-line sub-line; on the right: the "AI read · not verified" pill (only for filings that have a tone or a generated read), the "n sources" pill, a stock tag (icon and symbol), and "Change".

| Field | Rule |
|---|---|
| Title | the filing's document label ("Exchange filing" if none); deals: "<client> bought/sold n shares" (quantity ≥ 1 lakh shown as "x.xx L"); circulars: the title; flows: "FIIs net bought ₹n Cr · DIIs net sold ₹m Cr"; sector: "<index> rose/fell x.xx%" |
| Sub-line | filings: the generated one-line read, else the headline metric, else the company name; deals: "Block deal · ₹n Cr · at ₹p average"; circulars: "Issued by SEBI"; flows: "Cash market · provisional figures"; sector: "<sector> · close n · ±x% on the session" |
| Change | a stock's last 1-day move at the end-of-day close (from the scanner's 24 daily closes) for stocks in today's scan; "—" otherwise ("No end-of-day close for this stock on the desk: it is not in today's scan"); FII / DII rows show the FII net flow; market-wide events show "—" ("No single stock") |

### In the detail pane

1. Header: type · full time (IST) and a source pill — "Exchange filing (NSE)", "Exchange disclosure (NSE)", "SEBI circular"/"SEBI master circular", "Exchange data (NSE, provisional)", "Exchange index close (NSE)". Hover text: "Where this came from. Nivesh does not mark events as verified; it names the source." The desk never writes "verified".
2. Title.
3. "Why it may matter": rules-written text per kind of event, not AI (`whyText`); the investor wording differs (for example corporate: "The company told the exchange about a new order or contract. News like this can affect the share price."; deals: "A large investor bought or sold a big lot of this company's shares. The exchange publishes such deals after the market closes."). Trader text for deals: "A bulk deal is one in which a client traded more than 0.5% of the company's listed shares in a day; a block deal is a large trade done in the exchange's separate block window. Both are published after the close…".
4. The AI box (filings with any AI output): dashed box headed "AI read · not verified" — see D.5.
5. "The deal" box (deals): see D.6.
6. "Sourced facts": Event ID; Source (with "· n sources" when merged); Company; Published ("the exchange's own time stamp"); Ingested ("when Nivesh last fetched it; a first-seen time is not stored", or "not sent for this filing"); Category; Sector (with the sector's source, or "no industry on record for this company"); Market timing ("Filed before the market opened | during market hours | after the close | on a day the market was shut; the first session whose open can reflect it is <date>", "rules-based, from the filing time and the NSE calendar").
7. Impact view (D.8).
8. "Alert me" buttons (D.7).
9. Sources: numbered list "[1] Filed with NSE · <subject> ↗" (one per consolidated record), "SEBI · Circular ↗", "NSE · provisional FII / DII cash-market figures, <date>", etc. Links are shown only for http(s) URLs.

## D.5 "AI read · not verified" labelling

- Applies to the classifier's tone/sentiment, importance (`impact_score`), the generated one-line read, and the period and headline figure extracted from the document.
- The pill "AI read · not verified" appears on a row/event when it has a tone or a generated read (`AiPill`, `IntelTab.tsx:166-179`). Its hover text: "The classifier read the tone as <tone>. An AI label, not checked against the price and not a direction."
- The detail's box: the generated summary, "Extracted by AI: Period … · Headline figure …", then "Tone: Positive/Neutral/Negative · Importance: High/… · labels from the announcement classifier, not checked against the price and not a buy or sell direction." When the filing has a stored full insight, "Show the full generated read ›" fetches and shows it (`GET /api/filings/{id}/insights`). Trust line: "Announcement classifier and filing summariser · AI-generated · classifier <version>".
- No bullish/bearish colour or label is drawn from the tone (PRD §6.5). Events with no AI output show "No AI read of this filing yet; the filing itself has the detail." (filings only).
- The same pill text appears in the Chart tab's section 5 on each filing that has a one-line read.
- The route only returns `one` / `period` / `metric` from a generated insight, never from exchange boilerplate; `metric` is null unless the filing stated a number (`BE/routes/filings.py` docstring).
- Deals, circulars, flows and sector moves carry no AI content and no AI pill.

## D.6 Bulk and block deal fields

Source: `/api/markets/deals` → DaaS `/v1/desk/deals`. The deal box is headed "The deal" with a pill "Confirmed · exchange disclosure".

| Field | Meaning | Rule |
|---|---|---|
| Buyer / Seller / Client | client name | by `side` BUY/SELL |
| Quantity | shares | positive only |
| Deal price | "average traded price" | positive only |
| Value | ₹ crore | `quantity × avg_price ÷ 1e7` (DaaS definition) |
| Share of company | "x.xx% of total shares, shareholding pattern <period end>" | `pct_of_shares` = quantity ÷ the company's total shares × 100 (shares count from the shareholding pattern; "no shareholding pattern on record for the share count" if absent) |
| Close that day | stock's close on the deal date, with the previous close | end-of-day closes (NSE bhavcopy) |
| Deal vs that close | `price_vs_close_pct` | deal price against that day's close, signed |
| Next session close | close and date of the next session | "no later session on record yet" if none |

Closing note: "Prices are the stock's own end-of-day closes (NSE bhavcopy). Every deal here is NSE's own disclosure; no institutional activity is inferred." The fact row says "Exchange disclosure (NSE) · confirmed, not inferred" and "NSE publishes the day's deals after the close". Trade date, not time, is the only timestamp; the ingestion time is when Nivesh loaded NSE's file.

## D.7 Alerts

### Six kinds, created from an event (`EventAlerts`, `IntelTab.tsx:710-737`)

Each button is a real `POST /api/desk/alerts` and creates a one-shot alert. After a click the button reads "<label> ✓" and is disabled; failures print the server's wording. The kinds offered:

| Kind (`condition`) | Button (Trader / Investor) | Parameters sent | Fires when (server rule, `BE/services/desk_alerts.py` `RULES`, line 93) |
|---|---|---|---|
| `filing` | "New filing by SYM" / "Tell me about its next filing" | `symbol` (impact "any" by default) | the stock's first exchange filing (NSE or BSE) filed after the alert was made; with `impact: "high"` only filings the classifier rated high impact (an AI label — the UI does not offer "high") |
| `category` | "Next <category> by SYM" and "Next bulk / block deal in SYM" / "Tell me about a big deal in it" | `category` (one of the 11 classifier categories, or `deal`), `symbol` | the first filing in that category after the alert was made (classifier label, an AI label); for `deal`, the stock's first bulk or block deal NSE discloses for a later session. The "Next <category>" button appears only for a filing event with an alertable category. |
| `volume` | "Volume ≥ 2× average" / "Tell me if trading jumps" | `symbol`, `multiple: 2` | a session's volume ≥ multiple × the mean volume of the 20 sessions before it |
| `scanner` | "Enters the scanner" / "Tell me if the scanner picks it" | `symbol` (optional `stage`: BREAKOUT, EARLY_BREAKOUT, ACCUMULATION — not offered by the UI) | the stock is in the positional scanner's picks (`positional_signals`) on a signal date after the alert was made |
| `sector` | "<index> moves ≥ 2%" (sector-move events only, no stock) | `index`, `threshold_pct: 2`, `direction: "either"` | the index's close-to-close return reaches the threshold in the chosen direction |
| `risk` | "ATR ≥ 4% of price" / "Tell me if its swings get large" | `symbol`, `level: 4` | the stock's 14-session Wilder ATR as a percent of its close reaches the level |

Buttons shown: for an event with a stock — filing, (category), deal, volume, scanner, risk; for a sector move — the sector button; for other market-wide events (circulars, flows) — none, and the section is omitted. In addition, the Results and Orders chips offer a general category alert with no stock: "Alert me on the next results|orders filing" (`ChipAlert`).

The server also supports `above` and `below` price alerts (used by the Risk desk button, C.6). In total 8 conditions: `above, below, filing, category, volume, scanner, sector, risk` (`desk_alerts.py:56`).

Accepted ranges (`desk_alerts.py:75-80`; invalid values answer 422 with a code): volume `multiple` 1.5 to 20 (`invalid_multiple`); risk `level` 0.5 to 20 (`invalid_level`); sector `threshold_pct` 0.5 to 10 (`invalid_threshold`); `direction` up, down or either; sector index must be one of the 20 listed in `SECTOR_INDEX_NAMES` (`invalid_index`); `impact` any or high; `category` one of earnings, orders, mna, capex, management, dividend, buyback, qip, rating, litigation, regulatory, deal (`invalid_category`). Sector indices: Nifty Auto, Bank, Financial Services, FMCG, IT, Media, Metal, Pharma, PSU Bank, Private Bank, Realty, Energy, Oil & Gas, Healthcare Index, Consumer Durables, Capital Goods, Cement, Chemicals, Power, Telecommunications.

### Dedupe and limits (`BE/routes/desk_trading.py:216`)

- Duplicate: an active alert identical in condition, stock, level and settings to one the user already has is refused: 409 `duplicate_alert` ("You already have this alert, and it is still active.") (`dedupe_key`, `desk_alerts.py:196`: condition, symbol, level rounded to 4 decimals, and the non-null params).
- Limit: at most `MAX_ACTIVE_ALERTS = 50` active alerts per user (`desk_trading.py:71`): 409 `active_alert_limit`. A second count after the insert removes the new alert if two requests raced past the limit. Fired alerts do not count; up to 1000 fired alerts are listed (`MAX_FIRED_LISTED`).
- Every alert is scoped to its owner; another user's alert answers 404.

### Delivery: in-app only

Alerts are listed in the "Your alerts" card at the bottom of the tab (fired first, then active), labelled "In-app only". Nothing is emailed, pushed or sent to a phone: "Nothing is emailed or sent to your phone." (`AlertsCard`, `IntelTab.tsx:935-967`). Card states: loading "Loading your alerts"; error "Your alerts didn't load"; empty "No alerts yet. Open an event and choose "Alert me", or set one for a category above the list." The card note: "Checked when you open the desk and once each weekday evening; shown in this list only (in-app)." (server text: "Checked when you open the alerts and once each weekday evening… Counted from the first session after the day the alert was made; a filing counts from the moment it was made.") Each item has a Delete button (`DELETE /api/desk/alerts/{id}`).

When checks run: every `GET /api/desk/alerts` evaluates all of the user's active alerts first (`desk_trading.py:241`), and the evening job `backend/scripts/check_desk_alerts.py` evaluates all users; the installer is `deploy/nivesh-staging/install-desk-alerts.sh`. Whether that job is installed and running on staging is unverified.

Timing rules (`desk_alerts.py` docstring): a filing counts when its exchange time is after the moment the alert was made; everything read from daily data (prices, volume, ATR, sector closes, deals, scanner dates) counts from the first session strictly after the IST date the alert was made. A session whose figure is missing ends that alert's scan for now; it is never skipped.

### How a firing records its reason

When an alert fires, one conditional write sets `status = fired`, `fired_at`, `fired_session`, `fired_price` (price alerts only), `reason` (a plain sentence) and `evidence` (a small JSON object), with the status `active` in the update filter, so a second check, two tabs or the evening job cannot fire it twice (`fire()`, `desk_alerts.py:499-512`). The list shows "Fired <date>" and the reason, with a "Filing ↗" link when `evidence.url` is an http(s) address. Reason templates:

| Kind | Reason sentence | Evidence fields |
|---|---|---|
| above / below | "<SYM>'s high|low of ₹x on <date> reached your level of ₹y." | session, high or low, level |
| filing | "<SYM> filed "<subject>" with NSE|BSE at HH:MM IST on <date>." + " The classifier labelled it <Category> (an AI label)." or " The classifier rated it high impact (an AI label)." | announcement id, source, subject, filed_at, url, symbol, event_category, impact |
| category = deal | "<client> bought|sold n shares of <SYM> at ₹p in a bulk|block deal on <date> (NSE's own deal disclosure)." | session, kind, client, side, quantity, price, pct_of_shares |
| volume | "<SYM> traded n shares on <date>, r× its average of m over the 20 sessions before (your level: k×)." | session, volume, average, ratio, multiple |
| scanner | "<SYM> entered the scanner's picks on <date> as <stage> (score s)." | session, stage, score |
| sector | "<index> rose|fell x.xx% on <date> (close a against b; your threshold: t% either way|up|down)." | session, index, close, prev_close, return_pct |
| risk | "<SYM>'s 14-session ATR reached x.xx% of its close on <date> (your level: l%)." | session, atr_pct, level |

Active alerts show the rule text (for example "A session's high reaches the level (end-of-day bars).") and "Checked through <date>." If a source could not be read, the alert stays active and shows "Not checked: a source it reads could not be read."; the card adds "Some alerts were not checked this time: a source they read could not be read." An alert is never fired, and never shown as checked, on data that was not read.

Sources the checks read: end-of-day bars from DaaS `/v1/prices/eod` (raw bhavcopy prices), filings from `/v1/announcements`, deals from `/v1/flows/bulk-deals` and `/block-deals`, index closes from `/v1/indices/{index}/eod`, scanner picks from the app database's `positional_signals`. The staging memory records that the scanner tables were empty on CloudPe staging; whether a scanner alert can fire there is therefore unverified.

## D.8 Impact view (PRD §6.5) — "Linked stocks and sectors"

In the detail pane of an event (phone: inside the expanded row).

| Part | What it shows | Source |
|---|---|---|
| Linked stock | A chip with the symbol; click opens that stock's chart. Green if it is the stock already selected on the desk, indigo if it is in today's scan, grey otherwise. A sector pill (the filing's sector with its source on hover, or the scanner's sector). | provenance block / scanner |
| Scanner position | "SYM is #r of n in today's scan. Select it to load the setup." with "end-of-day scan <date>"; or "SYM is not in today's scan. Select it to open its chart."; or "The scanner didn't load, so its rank is not shown." | `useDeskScanner` |
| Related companies | Chips for same-industry peers, "the largest-index members first. Related by industry only, not by this event." Each opens its chart. Empty: "— No same-industry list for this company in the NSE index files." / "— No industry on record for this company." | DaaS `/v1/desk/event-sources` (`peers`, `largest_index`) |
| Technical confirmation | "Close ₹x on <date>: above|below its 20-day EMA (₹a), above|below its 50-day EMA (₹b); RSI 14 n; volume r× its 20-session average." Then "Move on <date> (<why>): +x.xx%, close to close." Trust line from the indicator route. | `GET /api/research/chart/live/{symbol}/indicators` + `…/chart-live/{symbol}/ohlcv` (A.2) |
| Past reactions to similar events | "— No study of how prices reacted to this kind of event is published yet, so none is shown. The AI read is not a forecast." | none (no source) |

Reaction rule (`reactionBar`, `IntelTab.tsx:616-627`): for a filing with market timing, the bar is the first daily bar whose date is on or after the "first session whose open could reflect the filing" (`known_at_open_session`, from `v_event_asof`); for a deal it is the first bar after the deal date ("the session after the deal (deals are published after the close)"); the move is `close ÷ the previous bar's close − 1`. If no such bar exists yet, or the event has no timing: "Move since the event: — (no session after it in the bars yet, or no market timing for it)." Technical confirmation states: loading "Reading <SYM>'s indicators"; 403 "Chart data is not enabled for this account, so the technical check is not shown."; 404 "No daily prices on record for <SYM>."; 503 "The indicator service could not answer: <reason>."

Events with no single stock (circulars, flows) read "No single stock: this is a market-wide event." and show no technical confirmation. On the phone, a "Sector impact · 1D" card shows the six sectoral indices with the largest absolute 1-day return, as heat tiles ("the six NSE sector indices that moved most", end-of-day source line), from `/api/markets/sector-returns`.

## D.9 The "Sources" status line (PRD §12.4)

A line at the bottom of the card (desk) or the list (phone), `SourcesStatus` (`IntelTab.tsx:333-361`):

`Sources · Filings: answered · latest <date, time IST> · Bulk and block deals: answered · latest <date> · SEBI circulars: … · FII / DII flows: … · Sector index closes: …`

- It lists only the sources the open chip reads ("none for this category" if there are none).
- Each source reads "answered · latest <date>", "answered · nothing on record", "loading" or "failed" (failed in red). For filings the date is the newest `ingested_at` on the rows; for the others it is the source's own `as_of`.
- For admins a second line reads `GET /api/admin/nidp/feeds/live` and prints any of these ingesters that are not "healthy" or "running": `corporate_announcements_nse`, `corporate_announcements_bse`, `corporate_announcements_bse_subcat`, `announcement_classifier`, `document_parser`, `bulk_deals`, `block_deals`, `fii_dii`, `index_close`, `event_calendar`, with their state and last success; or "every Intel feed is healthy". Non-admins do not see it.
- Below it the trust line: "Exchange filings (NSE, BSE) · NSE deals · SEBI · NSE FII / DII · Delayed · last ingested <time> · As reported · AI reads are labelled where shown" with status "Source failed" if any source failed.
- The footer note under the list explains "Change" and the duplicate rule (D.2).

## D.10 What the Market Intelligence tab does not have

| Missing | Reason |
|---|---|
| Macro events | No macro-economic calendar ingested (chip disabled) |
| Promoter and insider trades (SAST / PIT) | `nidp.insider_sast` is empty and has no app route; only the companies' own filings under those rules are listed |
| Sector news | No sector-news feed; only index moves ≥ 1% |
| F&O ban list; ASM / GSM | Not ingested |
| Verified/unverified flag | The desk names the source instead of a verification claim; a verification flag is not available |
| Past price reactions to similar events | No published study |
| Alert delivery by email, push or SMS | In-app only |
| Events older than 7 days (filings) | The list asks for 7 days; the route's ceiling is 30 |

---

## Appendix — facts worth a reader's attention

1. Chart levels versus rule levels: the desk chart draws only scanner levels; the Open full chart link and sections 7/Risk desk also carry rule levels.
2. Split handling differs: indicators cut history at an unapplied split (40% one-day move); patterns do not.
3. P(+5%) is shown on the Chart tab and Risk desk, but withheld on the Scanner tab by the calibration gate.
4. The Support/resistance tile tooltip is empty (key mismatch `sr20` vs `resistance20`).
5. Paper trade and alert buttons require a scanner setup; a stock with only rule-based levels can be sized but not saved.
6. Historical record: in-sample, price-only, no costs, no benchmark (stated on screen).
7. Unverified here: what staging currently holds in `security_reference_daily`, `accumulation_calibration`, `positional_signals`, `nidp.insider_sast`, bulk/block deal tables, holdings freshness, whether the evening alert job is installed, and whether `adj_*` prices include dividends.


---

# Smart Trading Desk: Portfolio & Risk, Paper trading, Options & Futures Lab

Scope of this part: (A) the Portfolio & Risk tab, (B) paper trading, (C) the Options & Futures Lab (under More).

Source read: `/home/deploy/nivesh-fix-bse` (snapshot of origin/dev). Nothing was run and no staging call was made, so every statement below comes from reading code. Where code cannot confirm something, the text says "unverified".

Path shorthand used throughout:

| Short | Full path |
|---|---|
| `td/` | `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/` |
| `desk/` | `frontend-v5/src/pages/CopilotApp/screens/desk/` |
| `trading/` | `frontend-v5/src/pages/CopilotApp/screens/trading/` |
| `be/` | `backend/` |
| `daas/` | `backend/nidp/services/daas_api/routers/` |

Persona note. The desk has a TRADER / INVESTOR switch (`td/context.tsx`). It changes wording only; the data is the same. Investor wording is listed next to each feature.

Read-only rule that applies to all three parts: nothing in this desk places, changes or cancels a broker order. The only writes are the user's own simulated paper trades, price alerts, and a portfolio import the user confirms (`td/PortfolioTab.tsx` lines 1-4).

---

## A. Portfolio & Risk tab

The tab (`td/PortfolioTab.tsx`) is tab 05. Desktop layout, top to bottom: two cards side by side ("Portfolio · broker hub" and "Paper trades · predicted vs actual"), the optional import card, the broker block, the "Your paper trades and price alerts" card, and a footnote. Phone layout (`PhonePortfolio`, line 1331): "Your portfolio" card, "Risk dashboard" card, "Positions" card, a read-only note, the import card (when open), the paper card, the broker block and the paper lists.

### A1. Where the card's figures come from

| Figure | Route | Underlying source | As-of |
|---|---|---|---|
| Broker names and "last read" | `GET /api/broker/accounts` | Mongo `broker_accounts` | latest `lastSyncAt` of the accounts |
| Value, invested, unrealised P&L, positions, weights | `GET /api/portfolio/holdings-enriched` (`be/routes/portfolio.py:73`; built by `services/portfolio_enrichment.py`) | Mongo `db.holdings` (quantity x `current_price`) | cached 5 minutes per user in Redis (`portfolio_enrichment.py` `ttl_s=300`); prices are the last price stored on the holding |
| Scope line, asset allocation, freshness, duplicates | `GET /api/portfolio/composition/scope` (`be/routes/portfolio_composition.py:262`) | Mongo `db.holdings` + `db.broker_accounts` | request time; freshness is the newest `price_updated_at` / `uploaded_at` / `created_at` of the rows |
| Realised P&L | `GET /api/portfolio/capital-gains-statement` (`be/routes/portfolio_tax.py:60`) | FIFO over stored statement transactions (`services/tax_engine_fifo`) | current financial year (1 Apr to 31 Mar) |
| Cash | `GET /api/broker/funds` | each broker's own read-only funds call, never stored | read time of the call |
| Live vs stored check | `GET /api/broker/holdings` | live broker read vs the lines in the scope response | read time |
| Market-cap donut | `GET /api/portfolio/market-cap-split` (`be/routes/portfolio_desk.py`) | holdings as in holdings-enriched, plus NSE index membership via DaaS `/indices/{index}/constituents` (`nidp.index_constituents`) | latest constituents date of each list |
| Ten risk rows | see A4 | see A4 | see A4 |

Hook cache times (frontend): scope 5 min, risk-analytics 5 min, market-cap split 10 min, correlation 30 min, holding-risk 30 min, realised gains 30 min (`td/portfolio-data.ts`).

How the price on a holding is set. `services/live_price.py` header: primary source is DaaS `/v1/prices/latest/{symbol}` (NSE end-of-day), fallback Yahoo Finance. It writes `current_price`, `price_updated_at` and `nse_symbol` on equity, ETF and gold holdings only. What triggers that refresh is not visible in the files read: unverified.

### A2. The portfolio card ("Portfolio · broker hub")

What the user sees, in order (`HubCard`, line 1024):

1. A pill "Read-only". On the header, "Import ›" opens the import card (A6).
2. Sources line: broker icons plus `ZERODHA · last read 12 Oct, 3:42 pm`. Phone shows names only.
3. Value line: total value (compact rupees) and `P&L · %` in the P&L tone. The P&L is "Total P&L on what you paid".
4. Scope line (`OverviewFigures`, line 203): "Totals cover N holdings on record from A, B and C · equity 3 · mutual fund 1. Valued at the last price on file (stored, not live)." Account names come from the scope route: a broker account is `Broker · label`, a broker file is `Broker file`, a CAS import is `CAS statement`, everything else is `Added by hand or from a plain sheet` (`portfolio_composition.py:239`). The instrument types are row counts per asset type, largest first, underscores shown as spaces. Investor wording opens with "These totals add up N holdings...".
5. Four figures:

| Figure (trader / investor) | Rule | Sub-line |
|---|---|---|
| Invested / Paid | `sum(quantity x buy_price)` over holdings with a cost (`buy_price > 0`) (`portfolio_enrichment.py:775-790`) | "What you paid for the holdings on record", or "N holdings have no cost on record and are left out" |
| Unrealised P&L / Gain on paper | `value of costed rows - invested`; percent = that / invested (`portfolio_enrichment.py:1318-1324`). Rows without a cost are excluded from P&L, but their value is still in the total value | "x% on what you paid · stored prices", or "No cost on record to compare with" |
| Realised P&L / Gain taken | Sum of short-term and long-term equity gains of the current FY from the FIFO statement (sections `A_stcg_equity` + `B_ltcg_equity`) (`portfolio-data.ts` `readRealisedGains`) | "FY 2026-27 · N sales · equity, FIFO, before costs" |
| Cash | Sum of `available_cash_rs` over broker accounts read live (A5) | "Available funds at X, Y (not read: Z), as each broker reports it · read <time>" |

6. Asset allocation (investor: "Mix"): `Equity 62.0% · Debt 20.0% ...`. Classes come from `_asset_class_for` (`portfolio_composition.py:47`): asset type equity/stock = Equity; gold/sgb = Gold; debt = Debt; cash = Cash; otherwise a fund's category text decides: liquid/debt/bond/gilt/corporate/short term/low duration/overnight/money market = Debt; hybrid/balanced/multi asset/arbitrage = Hybrid; gold/commodity = Gold; international/global/overseas/us equity/nasdaq = International; anything else = Equity. Weight = class value / total value.
7. Freshness: "Last updated <newest stamp> · oldest source <oldest stamp>". If any holding has no price: "N holdings have no price on record and count as nothing in the value" (amber).
8. Live vs stored, one line per connected broker account (A5 explains the read): `live ₹x read <time> · quantities match the last sync` or `N lines differ from the last sync (sync the account to update the totals)` (amber), or `not read live (the session ended) · stored ₹x as of <last sync>`. The comparison (`reconcileAccount`, `portfolio-data.ts:793`) keys each line by ISIN, else symbol, sums quantities per key, and calls it a match only if every key is on both sides with the same quantity (tolerance 1e-6). A line only live = "onlyLive", only stored = "onlyStored", different quantity = "differing"; the count shown is the sum of the three.
9. Reconciliation sentence. Duplicates are instruments (by ISIN) held in two or more sources: "RELIANCE is in Zerodha and CAS statement; ... - counted in each, not merged." With none: "Reconciled: no holding is on record from two sources." A toggle "The rule ›" shows `SCOPE_RULE` (`portfolio_composition.py:224`): a broker account or a broker's own file replaces a statement's copy of the same ISIN; holdings at two different brokers, or a plain sheet beside a statement, both count; overlaps are listed, never merged.
10. The market-cap donut (A3).
11. Positions list (A3b).
12. "Risk checks · linked holdings" (A4).
13. Trust line: "Stored holdings in Nivesh · broker accounts read-only", "updated <stamp>", end-of-day mode, "N sources · values at the last price on file".

States of the card:

| State | What is shown |
|---|---|
| Loading | "Loading your holdings" skeleton (4 rows) |
| Holdings call failed | Error block "Your holdings didn't load" with Retry |
| No holdings (`holdings.length == 0`) | Empty block "No holdings on record yet" with "Import a portfolio" and "Connect a broker" (goes to `page/brokers`). Body: "Import your broker's holdings file (checked and previewed before anything is saved) or connect a broker account (read-only)..." |
| Scope loading | "Working out which accounts these totals include..." |
| Scope failed | inline problem "The accounts behind these totals" with retry |
| No broker connected | sources line: "No broker connected · holdings on record in Nivesh" |
| Broker list failed | "Broker connections didn't load" |
| Realised P&L loading / failed / no sale | "..." / "Realised gains didn't load" / "-" with "No sale on record in FY ...: realised P&L comes from your statement's transactions, and none are stored" |
| Cash: no broker | "-" with "No broker connected, so no cash balance is read" |
| Cash: forbidden (403) | "Live broker reads are not enabled for this account" |
| Cash: other failure | "Cash didn't load from your brokers" |
| Cash: none read | "Not read from X: a live read needs an account signed in on the broker's own page" |

Cash is the sum over accounts whose funds call succeeded. An account that was not read is named in "(not read: ...)" and is not counted as zero (`cashOf`, `desk/broker.ts`; the donut also leaves unknown cash out, `capDonut`).

### A3. The market-cap donut and its rule

Route `GET /api/portfolio/market-cap-split`, rule in `be/routes/portfolio_desk.py` (`CAP_LISTS` line 61, `split_by_cap`).

The rule, exactly:

| Bucket | A holding is placed here when |
|---|---|
| Large | it is in the latest Nifty 100 list |
| Mid | not Large, and in Nifty Midcap 150 |
| Small | not Large/Mid, and in Nifty Smallcap 250 |
| Micro | not Large/Mid/Small, and in Nifty Total Market |
| Unclassified | in none of the four lists |
| Not split yet (`unsplit`) | an earlier list in the order Large, Mid, Small, Micro is not in the warehouse, so the holding cannot be placed; it is never guessed into a bucket |

- Only direct stocks (asset type equity or stock) are split. A stock held in two accounts counts once with values added (`split_holdings`). Funds, ETFs and other holdings are not split; their total value is reported as `excluded.funds_value_rs`, note "Mutual funds, ETFs and other non-stock holdings are not split by market cap".
- A holding matches a list by ISIN, else by symbol. Each list is read at its own latest constituents date (limit 1000 rows, `CONSTITUENTS_LIMIT`). Route `as_of` is the newest of those dates.
- A bucket is reported only when every list that decides it is available. The route then sets `available: false` and `reason: "<index names> constituents are not in the warehouse yet; the buckets they decide are not reported"`.

What the user sees: a ring chart whose centre shows the count of direct stocks and the word STOCK(S), a legend, and a note. The legend rows are Large, Mid, Small (always listed), Micro and Unclassified (only when they hold value), Not split yet (when present), Funds & other, and Cash. Each row shows its share; "-" when it cannot be known. An unavailable bucket is drawn as a dashed dot, with the route's reason as tooltip.

Share arithmetic (`capDonut`, `portfolio-data.ts:494`): total = route `total_value_rs` of the direct stocks + funds value + cash (cash only when the brokers returned it and it is above zero). Each slice = value / that total x 100. The note under the ring says "Shares of the ₹X the route valued plus the brokers' cash. Large = Nifty 100, mid = Nifty Midcap 150, small = Nifty Smallcap 250 (NSE index lists, <date>). Cash: <cash text>." followed by the route's reason in amber when there is one. The text names three lists; Micro and Unclassified are defined by the route as above.

States: loading "Loading the market-cap split"; failed "The market-cap split" with retry; no value at all "No holdings to split by market cap."; DaaS not configured or unreachable gives 502 `upstream_unavailable`; holdings unreadable 503 `holdings_unavailable`.

### A3b. Positions list

Direct stocks only (asset type equity or stock), sorted by value, largest first. Columns: Stock (icon and symbol), Value ₹, P&L (percent), Weight. Weight is the holding's share of the whole portfolio's value (all holdings including funds) as computed in holdings-enriched (`weight_pct = value / grand total x 100`, `portfolio_enrichment.py:864`). A weight above 25% is amber and bold with the tooltip "Above the 25% single-stock limit" (`SINGLE_STOCK_LIMIT_PCT = 25`, `portfolio-data.ts:156`). Eight rows are shown, then "Show all N". With no direct stocks: "No direct stocks on record. Your N holdings are funds or other assets."

Note: this list is per holding row. The same stock in two accounts shows twice here; the risk routes merge it.

### A4. The ten risk rows and each rule

Rendered by `useRiskChecks` / `CheckRow` (`td/PortfolioTab.tsx:643-948`). Each row has: a label, a one-line detail, a figure and level at the right, "Details ›" (a per-holding or per-pair list, only on rows that have one), and "Why <level> ›" / "How it is judged ›" which opens the rule sentence. Every coloured level is explained by its rule text, and the rule is also bound to the level with `aria-describedby`. Colour is never the only signal (the level word is always printed). Levels map to a 5-segment bar: low 2, medium 3, high 4, very high 5 segments; no level fills none.

Scope footer: "Scope: the direct stocks on record (funds are not looked through here), end-of-day prices." Code fact that qualifies this: rows 1 and 9 and the 1-day VaR use `GET /api/portfolio/risk-analytics`, which reads both stocks and funds (`be/routes/portfolio_risk_analytics.py`: it loads every holding, takes mutual-fund and ETF primitives as well as stock primitives, and weights them by value). Rows 5 to 8 and 10 use direct stocks only. The footer therefore describes rows 5-8 and 10 accurately and row 1/9 only partly.

Labels (trader / investor): `ROW_LABEL`, line 564.

| # | Row (trader / investor) | Figure and level | Rule (thresholds as in code) | Source route and table |
|---|---|---|---|---|
| 1 | Overall risk / How risky overall | Low, Medium, High, Very high, or "-" | Volatility is the value-weighted average of each holding's 1-year annualised volatility (holdings with a figure). Under 10% = LOW, under 18% = MEDIUM, under 28% = HIGH, otherwise VERY_HIGH; no volatility = UNKNOWN, shown "-". (`_vol_to_rating`, `portfolio_risk_analytics.py:29`; text `OVERALL_RULE`, `PortfolioTab.tsx:577`.) Score = `min(10, vol / 0.04)`, one decimal ("score 4.5 of 10") (`:43`) | `/api/portfolio/risk-analytics`; DaaS v3 primitives (`volatility_1y`), stocks and funds. Detail line adds beta vs Nifty 50 and "1-day VaR ₹x (y%) at 95% confidence" |
| 2 | Position concentration / Biggest single holding | Largest stock weight; "Above limit" (high) or "Within limit" (low) | One direct stock above 25% of the whole portfolio is high; 25% or less is low. Two levels only. "-" with "No direct stock with a weight on record" when none | holdings-enriched weights (client-side, `largestStock`) |
| 3 | Sector concentration / Biggest sector | Largest classified sector share; Balanced (low), Elevated (medium), Over-concentrated (high) | The frontend verdict (`concentration-data.ts:103-116`): sector cap = 35% (`caution_pct`, from `warn_largest_pct=35`, `be/services/portfolio_concentration.py:514`). Any classified sector above the cap = over-concentrated (high); else any sector within 3 points below the cap, or sector classification coverage under 80% = elevated (medium); else balanced (low). Unclassified/other/unknown/residual items are not judged. Detail adds HHI and effective number of sectors | `GET /api/portfolio/exposure/concentration` (stocks plus fund look-through from `fund_holdings_cache`) |
| 4 | Correlated positions / Holdings that move together | "N pairs" (high) or "None" (low) | Pearson correlation of daily log returns of split/bonus-adjusted closes over the last 120 sessions (`CORR_SESSIONS`). A stock needs at least 60 return observations (`MIN_SESSIONS`); a pair needs at least 60 common dates. A pair at 0.7 or above is high (`HIGH_THRESHOLD`). Any flagged pair = high; none = low. "Details" lists the top 10 pairs, their portfolio weights and common sessions, and stocks that were not compared with the reason | `GET /api/portfolio/correlation?sessions=120&limit=10`; DaaS `/prices/adjusted/{symbol}` (`nidp.prices_eod_adjusted`), six reads at a time. Fewer than two usable stocks: "Fewer than two of your stocks have enough daily prices to compare" |
| 5 | Gap risk / Sudden overnight jumps | "x% of sessions"; Low/Medium/High | An overnight gap is a session whose open is 2% or more away from the previous close (split-adjusted). Rate = share of sessions with one, value-weighted over the stocks. Low under 5%, medium 5% to 15%, high above 15% (`GAP_RULE`, `portfolio_desk.py:89`; `level_for`, line 380). Detail names the largest overnight fall and its date | `GET /api/portfolio/holding-risk?sessions=250`; DaaS adjusted open and close |
| 6 | Volatility · 1M / How much it swings · 1 month | annualised % ; Low/Medium/High/Very high | Annualised standard deviation of daily log returns of today's stocks held together, over the last 21 sessions (`SHORT_VOL_SESSIONS`). Under 10% low, under 18% medium, under 28% high, otherwise very high (`VOL_RULE`). The 1-year figure from row 1 is shown beside it | holding-risk; "held together" = today's value of each stock carried back on its adjusted closes, on dates every included stock has a close |
| 7 | Liquidity / How easy to sell | "x days" to sell the slowest position; Low/Medium/High | Per stock: average traded value (raw close x raw volume) over the last 20 sessions, and days to sell = quantity / (10% x average daily volume). High: any holding needs more than 5 days. Medium: any holding needs more than 1 day, or trades under ₹10 Cr a day. Low otherwise. The worst holding decides (`LIQUIDITY_RULE`, `liquidity_of`). "Details" lists each stock's ₹ Cr a day and days to sell | holding-risk |
| 8 | Drawdown · 1Y / Biggest fall · 1 year | largest fall from a peak, % ; Low/Medium/High | The largest fall from a peak in the value of today's stocks held together over the window (today's quantities on split-adjusted closes). Above -10% low, -10% to -20% medium, below -20% high (`DRAWDOWN_RULE`). A stock with a stale last bar or under 60 sessions is left out of the series and listed in "Details". Detail also shows each stock's own 1-year drawdown, value-weighted (`max_drawdown_1y_pct` via DaaS v3 primitives), and the deepest one | holding-risk and risk-analytics. The portfolio's own drawdown from the PRA engine is not available (field `max_drawdown_pct` is always null; `portfolio_risk_analytics.py` comment: 0 rows on staging 2026-10-14) |
| 9 | Beta / Moves with the market | beta (2 decimals), level text "No band" | Shown without a level on purpose: "it measures how far the holdings tend to move with Nifty 50, not a risk band on its own". Value-weighted 1-year beta of the holdings that have one | risk-analytics (`beta_1y`, stocks and funds) |
| 10 | Missing price or position data / Missing prices or holdings | "N gaps" or "None"; Incomplete (medium) / Complete (low) | Medium when any holding has no price, no NSE symbol, no cost, or a price older than the newest session; low otherwise. Nothing missing is filled in. Lists: no prices at the data platform, no NSE symbol, stale price with its last session, holdings with no price on record, holdings with no cost on record | holding-risk `missing` + scope totals |

Other risk-analytics facts (not separate rows): the "Details" list of row 1 shows risk drivers: Smallcap weight (shown from 10%; HIGH above 30%, else MEDIUM), High-beta names (holdings with beta above 1.3; shown from 20%; HIGH above 40%), Cyclical sectors (sector keywords bank, nbfc, finance, metal, real estate, auto, construct, oil, chemical; shown from 25%; HIGH above 50%), and always a "Debt + gold buffer" (LOW at 15% or more, MEDIUM at 5% or more, else HIGH) (`portfolio_risk_analytics.py:215-250`). It also says "These figures cover x% of the portfolio's value". The 1-day VaR is parametric: `value x (vol / sqrt(252)) x 1.645`, 95% confidence, on the total value including holdings with no primitives (`:262-270`).

States of a risk row: while loading, the detail says "Working out ..." or "Loading the risk figures"; on failure, "<x> didn't load" with a Retry link (the three holding-risk rows share one fetch); with no data, the figure is "-" and the detail states why, for example "No stock with an NSE symbol and two sessions of prices to compare" (gap), "Today's stocks do not share enough sessions of prices for a 1-month figure" (volatility), "No stock with an NSE symbol and traded volume on record" (liquidity), "Not enough common sessions of prices for today's stocks held together" (drawdown), "No beta on record for these holdings" (beta). A failure of risk-analytics adds a problem line "Beta, volatility and value at risk".

Footer trust line: "NSE end-of-day prices via the data platform", end-of-day mode, as-of from holding-risk, "Rules shown per row".

Phone: the card is titled "Risk dashboard" and carries a pill "<Level> risk" (from row 1) or "Risk -". Rows show the level bar and level word instead of the figure.

What is not available: a portfolio-level max drawdown (always null), a win rate for a setup, and the correlation of a candidate new position with holdings (`td/RiskDesk.tsx` header: shown as "-" with the reason, no route publishes them).

### A5. The broker block ("Broker account · read-only")

Component: `desk/BrokerPositions.tsx`, mounted in the Portfolio tab (and elsewhere in the trader desk). Route code: `be/routes/broker_connect.py`; read logic: `be/services/brokers/hub_reads.py`.

Access. All `/api/broker/*` hub routes require the feature flag `broker_hub` for the user (`broker_connect.py:559`, `_hub_user`). Without it the call is 403. On the screen: "Reading holdings live from a broker is not switched on for this account. The holdings stored at the last sync are shown instead." (holdings) and "Reading positions from a broker is not switched on for this account." (positions).

What the user sees per connected account (one card each, broker icon and name):

- A status under the name: "Reading holdings...", "Live · read 3:45 pm" (today, India time) or "Live · read 12 Oct, 3:45 pm", "Session ended · reconnect to read live", "Not read live", or "Live read failed".
- A funds line: "Cash available ₹x · margin used ₹y · collateral ₹z · as <Broker> reports it, read <time>". Collateral shows only when non-zero. Failures: "Cash not read: the session ended", "Cash not read: this connection cannot be read live", "Cash didn't load", "Reading cash...". Cash is read-only and never stored.
- Live holdings table: Stock, Qty, Average, Last price, Value, P&L, P&L %. Value = last price x quantity; P&L = (last price - average) x quantity (footnote text). A last price marked "not live" means the broker sent none and the latest stored exchange close or NAV from masterdata was used (`price_source: "masterdata"`, `hub_reads.py` `_live_rows`). Clicking a row sends a question to the Copilot ("Show the X chart with support and resistance. My broker account holds ...").
- Totals line: "Value ₹ · Invested ₹ · P&L ₹ · %". A total exists only if every row has the figure (`holdings_totals`, `hub_reads.py:567`: any missing row makes the total null; no rows = a known zero). When a total is missing: "N of M holdings has/have no price or no average from <Broker>, so the account totals are not added up", followed by value and P&L of the holdings that do have both.
- Open positions with filter chips All / F&O / Intraday and their counts (counts cover the whole read). Columns: Instrument (with contract line for FUT/CE/PE: expiry, strike, "future"/"call"/"put"), Held as (Intraday, Delivery, Carry forward, Margin), Qty ("Short n" for negative), Average, Last price ("Not sent" when absent), P&L ("Not sent" when absent). Total P&L sums rows that carry one and says "n of m positions carry one" otherwise. Clicking a row asks the Copilot about that contract and passes the position reference. Empty: "No open positions in this account." / "No open position of this kind in this account."
- Rules for the chips: F&O = position `segment == "fno"`, where segment comes from the exchange (NFO or BFO = fno; MCX = commodity; CDS or BCD = currency; otherwise equity) (`hub_reads.py:660`); Intraday = product code is intraday (`is_intraday`).

One "Refresh" button reads holdings, positions and funds again. Nothing polls ("brokers rate-limit"); the hooks use `refetchOnWindowFocus: false` and a stale time of `LIVE_STALE_MS` (`desk/broker.ts`; value not read). A line above reads "Holdings and positions read live <time>" or "Not read live". A second button "Broker connections" goes to `page/brokers`.

Per-account failures and Reconnect (`LiveFailure`, `AccountPositions`): each account is read on its own, four at a time (`LIVE_READ_CONCURRENCY = 4`); one account failing never fails the others.

| Server code | Holdings wording | Action |
|---|---|---|
| `BROKER_SESSION_EXPIRED` | "Your <Broker> session has ended, so this account's holdings and positions cannot be read live. Reconnect by signing in at <Broker> again." (positions: "...Sign in again from Broker connections to read its positions.") | "Reconnect" button (goes to `page/brokers`). The server also ends the stored session when the broker rejects the token |
| `BROKER_READ_NOT_SUPPORTED` | "Holdings cannot be read live from this <Broker> connection. A live read needs an account signed in on the broker's own page, at a broker Nivesh can read." | none |
| `BROKER_READ_FAILED` | "<Broker> did not return its holdings just now. Try again in a little while." | "Try again" (same as Refresh) |
| any other | "The holdings of this <Broker> account could not be read." | "Try again" |
| account missing from the live read | "This account was not in the live read. Refresh to read it again." | none |

The server's own error sentence is shown to admins only ("Server said: ..."). The server's sentences are built from fixed text and the broker's display name, never from the exception (`describe_failure`, `hub_reads.py:106`), so they cannot carry a token or payload.

Stored rows labelled "as of last sync". When an account's live holdings read failed, the block also fetches `GET /api/portfolio/holdings` (stored rows) and shows that account's rows under "Stored at the last sync · not live" with "N holdings · as of last sync <stamp>" and a "Price as of" column. It is never shown as live. If none are stored: "No holdings from this account are stored from an earlier sync either." Stored rows are written when an account connects, on demand (`POST /api/broker/accounts/{id}/sync`), and once a day while the session is live (`daily_sync`, `hub_reads.py:836`); on a sync the broker's copy wins and a statement's copy of the same instrument is removed (`helpers/holdings_reconcile`).

Which brokers are supported. Registered adapters (`be/services/brokers/registry.py`): Zerodha, Upstox, Angel One, Fyers, Dhan, 5paisa, AliceBlue, Groww, ICICI Direct, Motilal Oswal. Each has `fetch_holdings`, `fetch_positions` and `fetch_funds`. Other listed brokers are placeholder stubs that raise "not yet implemented" (`_stub.py`). Connecting needs the user to sign in on the broker's own page (accounts with `native == true`); an account connected another way (OpenAlgo) is listed but is not read live, with code `BROKER_READ_NOT_SUPPORTED` and, for funds, "Live funds are available only for accounts connected by signing in on the broker's own page". Which reader serves a read is deterministic: the Fenix reader when `fenix_reader.supports(slug)` is true, otherwise the broker's own adapter; there is no fallback from one to the other on error (`hub_reads.py` module docstring). Fenix has built-in header builders for Zerodha, Upstox, Fyers, AliceBlue and Dhan; Angel One's Fenix class is deliberately not set, so it uses its own adapter (`angelone.py:344`). Whether Fenix is installed and supports each read on a given server is a runtime fact: unverified. Day positions (`kind=day`) exist only for Zerodha and AliceBlue; this desk reads the net book (`kind=net`), as the block's "not read" notice says.

Not read, in every state (`PositionBookMissing`): the broker's day P&L, and a stop or target per position. Notice: "Day P&L and a stop or target per position are not read". The block lists three needs: a read-only day P&L figure (adapters' funds readers send a day M2M on some brokers only; not wired), day positions only where the broker has a day book, and a stop and target per position (a broker's book has neither).

What is never done: Nivesh places, changes or closes no order and moves no money. Footnote: "Nivesh only reads; it cannot place, change or close a position." Positions are not stored (read live and discarded); the trust line says "Read on open and on Refresh; never stored" (this refers to positions, funds and live holdings; stored holdings are written by the sync, described above).

Other states: broker list loading "Checking broker connections"; failed "Broker connections" with retry; none connected: "No broker account is connected" with "Broker connections" button, body "When a broker account is connected, its holdings and open positions are read live here...". Whole live-holdings call failed (not 403): "Live holdings" problem with retry.

### A6. Portfolio import with preview

Opened by "Import a portfolio" (empty state) or "Import ›" (card header) (`td/PortfolioImport.tsx`). The card is titled "Import a portfolio · preview before saving" with a pill "Nothing saved until you confirm". Backend: `be/routes/upload.py:601` (preview) and `:650` (commit).

Steps:

1. Choose a file: "CSV · XLSX · XLS · up to 5 MB". The page checks the extension (`.csv`, `.xlsx`, `.xls`); otherwise "Choose a .csv, .xlsx or .xls file." and "Check the file" stays disabled. Help text lists the broker downloads it reads (Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities, Kotak, Dhan, 5paisa, MF Central) or any sheet with a name and quantity column, and says a CAS statement PDF is imported from Broker connections instead.
2. "Check the file" posts the file to `POST /api/portfolio/upload/preview`. The server validates every row and saves nothing. The preview is stored in Mongo `holdings_import_previews` for 30 minutes (`PREVIEW_TTL`) with a TTL index.
3. The preview view shows: a trust line (file name, "read as <Broker>" if recognised, "checked <time>"); counts "N rows · ready · to review · not imported"; file kind and size and "N non-holding lines skipped"; an account note ("Read as a Zerodha holdings file", "Read as a plain sheet: no broker account is named", or "The columns do not name a broker; no broker account is named"); currency "INR (Indian broker exports and Indian ISINs are in rupees; the file has no currency column)"; and the effects note (below). Each row shows a checkbox, row number, name, symbol, ISIN (marked "from the NSE list" when looked up), exchange ("not in the file" - the importer never sets one), quantity, average cost, type, account, currency, a status pill and its flags. "File checks ›" lists the checks.
4. The user ticks rows. Ready rows start ticked; review rows start unticked; rejected rows cannot be ticked. A banner says "Nothing has been saved yet... Duplicates and mismatches are not merged: a ticked duplicate is added as its own row."
5. "Import N rows" calls `POST /api/portfolio/upload/preview/{id}/commit` with `{rows: [row numbers]}`. "Cancel" discards the preview on screen.

Limits (`upload.py:354-359`):

| Limit | Value | Response when exceeded |
|---|---|---|
| File types | `.csv`, `.xlsx`, `.xls`, checked by content as well as name | validation error from `validate_upload_async` (wording not read: unverified) |
| Size | 5 MB (`PREVIEW_MAX_BYTES`) | 413 "The file is over 5 MB; a holdings file is much smaller." |
| Rows | 5,000 (`PREVIEW_MAX_ROWS`) | 413 "The file has more than 5,000 rows of holdings." |
| Workbook members / expanded size | 2,000 members, 50 MB expanded | 413 "The workbook expands to more than a holdings file can hold; it was not opened." |
| Macros, ActiveX, embeddings, custom UI | refused | 415 "The workbook contains macros or other active content; save it as a plain .xlsx or .csv." (`.xls`: "contains macros") |
| Damaged `.xlsx` | refused | 400 "The .xlsx file could not be opened..." |
| Preview life | 30 minutes | commit gives 410 `preview_expired` |

Other file checks listed on screen: malware scan when the scanner is available; formulas are never run (cached cell values are read; text starting with `=`, `+`, `-`, `@`, tab or CR is stored as plain text).

Row status: any `reject` flag makes the row "rejected"; else any `review` flag makes it "review"; else "ready". Investor wording: Ready = "Looks fine", Review = "Check this", Not imported = "Can't import". Flag prefixes on screen: "Not imported:", "Check:", "Note:".

Every flag (`assess_rows`, `upload.py:~467-560`):

| Code | Level | Text / condition |
|---|---|---|
| `formula_text` | review | name starts like a spreadsheet formula; stored as plain text without the leading character |
| `isin_check_failed` | review | the ISIN fails the ISO 6166 check digit |
| `symbol_isin_mismatch` | review | the symbol belongs to a different ISIN on the NSE list |
| `unknown_symbol` | review | symbol not on the NSE list Nivesh holds (not applied to derivative-looking symbols or when the file gave an ISIN) |
| `no_identifier` | review | no symbol or ISIN; matched by name only |
| `unsupported_instrument` | reject | symbol looks like a futures/options contract (regex ending in FUT/CE/PE): "the holdings import takes delivery holdings only"; or the type is not one of equity, mutual fund, ETF, bond, gold, SGB, FD, NPS, other (with the aliases in `_SUPPORTED_TYPES`) |
| `no_quantity` | reject | quantity zero or missing |
| `fractional_shares` | review | equity or ETF quantity not a whole number |
| `no_average_cost` | review | no average cost; if included, the file's price is recorded as cost, so the row shows no gain or loss |
| `no_price` | info | no price in the file; the holding has no value until Nivesh prices it |
| `duplicate_in_file` | review | same instrument as an earlier row; not merged |
| `held_by_connected_account` | reject | the connected account of the same broker already reports this holding |
| `replaces_earlier_export` | info | replaces this holding from the user's earlier file of the same broker |
| `replaces_statement_row` | info | a broker's file wins over a CAS statement copy |
| `already_on_file` | review | already on file from a connected account, earlier file, statement or manual entry; importing adds a second row, nothing merged |

What commit does:

- Checks the preview belongs to the user, is open (not already committed: 409 `preview_already_committed`), not expired (410), and that `rows` are integers that exist and are not rejected (422 `invalid_rows`); an empty choice is 422 `nothing_to_import`; a body with fields other than `rows` is 422 `invalid_body`; an unknown preview is 404 `preview_not_found`. These codes are not in the screen's plain-language table, so the screen prints the raw code (`writeProblem`, `td/desk-trading.ts`).
- Claims the preview (status "committing") so two clicks cannot import twice, then calls `save_holdings(user, rows, "CSV" | "Excel")` (`helpers/parsing.py:325`). That is not a CAS import, so it does not clear existing holdings. A file recognised as a broker's holdings file replaces that broker's earlier file rows ("Confirming replaces every row of your earlier <Broker> file (N) with the rows you include"; for a plain sheet, "Rows you include are added to what is on file; nothing on file is replaced"), then removes statement copies the file supersedes. Masterdata fills names and sectors. If a row has no cost but has a price, the cost is set to that price. Fundamentals refresh in the background (failures never block the import).
- Responds with `count`, `committed_rows`, `left_out_rows`. The screen shows "N holdings imported (rows ...). Left out: rows ... Your portfolio figures are refreshed." and refetches holdings, scope, risk, correlation, market-cap and holding-risk.
- If saving fails, the preview is reopened so the user can retry.

### A7. Right-hand card and the lists under the broker block

These belong to part B; see B6 to B8.

Footnote of the tab: "Holdings and risk figures are as Nivesh last valued them; broker connections are read-only and nothing here places an order."

---

## B. Paper trading

Paper trades are the user's own simulated long trades. Routes: `be/routes/desk_trading.py` (prefix `/api/desk`); logic and constants: `be/services/desk_trading.py`; the evening evaluator `scripts/check_desk_alerts.py` shares the logic (named in the docstring, not read). Store: Mongo `desk_paper_trades`. Rules version string: `desk-paper-v2` (`RULES_VERSION`, line 92).

Nothing here can create a broker order: no broker import, no order call (`desk_trading.py` docstring; the API sends `"orders": "Paper trades are simulated and never create a broker order."`).

### B1. Creating a paper trade

Where the user does it in the UI (two places, and the Lab, C7):

| Place | How the fields are set |
|---|---|
| Scanner tab, a stock's action panel (`td/ScannerTab.tsx` `PaperTrade`, line 667) | User types the quantity (1 to 1,000,000 whole shares). Entry, stop and target are the scanner setup's; target is sent only if above entry. Needs entry > stop, else "Paper trade needs a scanner setup with an entry and a stop below it; <SYM> has none on this scan." Source `{kind:"scanner", bucket?, signal_date?}` |
| Chart tab risk desk, "Add to paper trades" (`td/RiskDesk.tsx` `DeskActions`) | Quantity is the server's trade-scenario quantity: `floor(risk budget / risk per share)`, capped by `floor(capital x max allocation % / entry)` and a max quantity (`be/routes/positional.py:1572, 1652-1658`). Defaults: capital ₹5L (choices 2L, 5L, 10L), risk 1% (0.5, 1, 2), max allocation 25%. Same source object. Disabled with a reason when there is no setup, no entry/stop, the scenario failed, or the risk budget fits no whole share |
| Options & Futures Lab, "Cash · delivery" card | See C7 |

The screens send only `symbol, quantity, entry_price, stop_price, target_price, source`. They never send `entry_rule`, `entry_window_sessions`, `max_hold_sessions`, `signal_at`, `strategy_version` or `rationale` (grep of `frontend-v5/src` finds them only in the type definition and the record display). The API accepts them, so a trade made from the desk is always an "at once" entry with no time exit. Whether other clients use them: unverified.

API fields and validation (`POST /api/desk/paper-trades`, `desk_trading.py:310`, `new_trade`):

| Field | Required | Rule | Error code (422 unless noted) |
|---|---|---|---|
| `symbol` | yes | upper-cased; regex `^[A-Z0-9&-]{1,20}$` | `invalid_symbol` |
| `quantity` | yes | whole number 1 to 1,000,000 (`MAX_QUANTITY`) | `invalid_quantity` |
| `entry_price` | yes | number > 0 and <= 10,000,000 (`MAX_PRICE`) | `invalid_entry_price` |
| `stop_price` | yes | same price rule; must be below entry | `invalid_stop_price`, `stop_not_below_entry` |
| `target_price` | no (null) | same price rule; must be above entry | `invalid_target_price`, `target_not_above_entry` |
| `note` | no | string, max 500 characters after trimming | `invalid_note` |
| `source` | no | object with only `kind` (regex `^[A-Za-z0-9_-]{1,40}$`), optional `bucket` (1-60 chars, no control characters), optional `signal_date` (ISO date) | `invalid_source` |
| `entry_rule` | no | `at_once` (default), `break_above`, `pullback_to` | `invalid_entry_rule` |
| `entry_window_sessions` | no | whole 1 to 20; only with a conditional entry rule (error if sent with `at_once`); default 5 for a conditional rule | `invalid_entry_window` |
| `max_hold_sessions` | no | whole 1 to 250 | `invalid_max_hold` |
| `signal_at` | no | ISO date or date-time, not after now (5-minute skew allowed) | `invalid_signal_at` |
| `strategy_version` | no | up to 60 chars of letters, digits and ` ._:+/#()-` | `invalid_strategy_version` |
| `rationale` | no | like `note`, 500 chars | `invalid_rationale` |
| any other field / non-object body / bad JSON | | | `unknown_field`, `invalid_body` |

Limits: 100 open paper trades per user; over it, 409 `open_trade_limit` (the screen says "You have the most open paper trades allowed (100). Close one first."). A second count after the insert removes the new trade if two requests raced. Long only: there is no short paper trade (`new_trade` requires stop below entry). Writes go through the app's CSRF middleware like all other writes.

Entry rules (`ENTRY_RULE_TEXT`, line 94):

| Rule | Meaning |
|---|---|
| at_once | Filled at the reference entry price when recorded (assumed, not checked against a bar) |
| break_above | Filled at the reference entry on the first session after it was recorded whose high reaches it; a session that opened above it is flagged |
| pullback_to | Filled at the reference entry on the first session after it was recorded whose low reaches it; a session that opened below it is flagged |

A conditional entry that is not reached within `entry_window_sessions` sessions closes as `entry_not_reached` with no price, no P&L (note: "The entry level was not reached within the entry window; no position was taken.").

### B2. How a trade is simulated and exited

The simulator (`simulate`, `desk_trading.py:533`) runs on every list read and on close. It writes only through filters that include `status: "open"`, so running it twice, from two tabs or from the evening script, never closes a trade twice and never overwrites a manual close.

Prices: end-of-day daily bars of raw traded prices from the data platform, `GET /v1/prices/eod/{symbol}` (`nidp.prices_eod`, NSE bhavcopy), not split-adjusted because users type the prices they would really trade at. One bar per session is kept, from the first available series in the order EQ, BE, BZ, SM, ST, IV, RR (`SERIES_PREFERENCE`); block-deal window and debt series are ignored. Reads: up to 5 pages of 5,000 rows, 15 s timeout, 8 symbols at a time. A missing price stays missing; nothing is filled in.

Sessions checked: strictly after the India-time (IST) calendar date the trade was opened. A bar with no high or no low ends the scan: later sessions wait until it is readable, and the trade carries the flag `bar_missing_high_low`.

Exit order within one session, after the position exists:

1. Stop: session low at or below the stop closes the trade at the stop price ("stop").
2. Target: session high at or above the target closes at the target ("target").
3. Time: if `max_hold_sessions` is set and sessions held reaches it, closes at that session's close ("time", note "Held for the most sessions the exit rule allows; closed at that session's close."), only when the bar has a close and neither stop nor target fired.

Same-session stop-and-target rule: if one session's range holds both the stop and the target, the trade is closed at the stop, with exit note "The stop and the target were both inside this session's range; counted as the stop (conservative)." and flag `both_in_range`. Reason: a daily bar does not show which came first.

Conditional entry sessions: for `break_above`, the entry session counts a stop (the low may have come first) and flags `entry_session_ambiguous`. For `pullback_to`, a target on the entry session is not counted (the high may have come first) and is flagged, and the target counts from the next session.

Gap flags (the paper fill price is never changed by them):

| Flag code | When |
|---|---|
| `gap_through_stop` | the exit session opened below the stop: "a real stop order would have filled near the open. The paper fill is the stop." |
| `entry_gap` | conditional entry reached on a session that opened beyond the entry ("a real order would have filled near the open, not at the entry") |
| `entry_outside_day_range` | an at-once entry whose price is outside the low-high range of the day it was recorded: "that fill could not have happened that day" |
| `entry_session_ambiguous`, `both_in_range`, `bar_missing_high_low` | as above |

Manual close (`POST /api/desk/paper-trades/{id}/close`): the screen sends an empty body, so the close is at the last end-of-day close (reason "manual", note "Closed at the last end-of-day close (<date>).") (the API also accepts `exit_price`). The exit rule is checked first: if the bars show the stop/target/time exit has already happened, the trade is closed that way and the call answers 409 `trade_already_closed`. A waiting conditional entry is cancelled instead: reason `cancelled`, no price, no P&L, note "Closed by you before the entry level was reached; no position was taken." If no close exists: 409 `no_close_available`; if prices cannot be read: 503 `prices_unavailable` (a conditional entry cannot be closed blind). The screen asks for confirmation first: "Close the X paper trade (N shares) at its last close, ₹p (end of day <date>)? It is simulated: no order is placed." or, for a waiting entry, "Cancel the X paper trade? Its entry has not been reached, so there is no position and no P&L."

There is no route or button to delete a paper trade. Only price alerts can be deleted (`DELETE /api/desk/alerts/{id}`). A closed trade stays in the list. (Code check: `routes/desk_trading.py` defines POST create, GET list, POST close for trades; the only DELETE is for alerts.)

### B3. Costs

Cost model (`COST_MODEL`, `desk_trading.py:106`, constants from `services/strategy_engine/backtest.py:54-55`):

| Term | Value |
|---|---|
| Slippage per side | 0.0005 of traded value = 0.05% |
| Brokerage per side | ₹20 flat |

Round-trip cost = `entry x qty x 0.0005 + 20` (entry side) + `exit x qty x 0.0005 + 20` (exit side), rounded to 2 decimals (`trade_costs`, line 629). No other terms are in the model; taxes and statutory charges are not modelled (the model has only these two terms; there is no tax term in the code). The model is stored on each trade (name "strategy_engine default"), and older trades use the model stored with them. The screen states: "Net figures take off estimated costs: 0.05% of the traded value + ₹20 a side (strategy_engine default)."

Gross P&L = `(exit - entry) x quantity` for a closed trade (`realized_pnl`). For an open, entered trade: `(last close - fill) x quantity`, with the exit side of the cost estimated at the last close ("exit side estimated at the last close"). A closed trade's costs basis reads "entry and exit at the fill prices". `est_costs_rs` shows the round-trip cost at the target and at the stop from the reference entry.

Net P&L = gross - costs.

### B4. MFE, MAE, entry status, observations

- Observations: eligible sessions read since the trade was recorded.
- Held sessions: sessions from the first held session (the entry session for a conditional entry, the first session after opening for an at-once entry) through the exit.
- MFE (best point) = `(highest high / fill - 1) x 100` percent and `(highest high - fill) x quantity` rupees; MAE (worst point) = same with the lowest low. Measured from the first session held through the exit session, against the fill. Null (never zero) when the trade was never entered or nothing was read (`path_figures`, line 648). A trade that closed before these fields existed shows nothing.
- Entry status values: `assumed` (at once, filled when recorded: "Filled when recorded" / investor "Bought when added"), `reached` ("Entry reached" / "Bought"), `waiting` ("Waiting for entry" / "Waiting to buy"), `not_reached` ("Entry not reached" / "Never bought").

### B5. Exit reasons and wording

| Reason | Trader label | Investor label |
|---|---|---|
| stop | Stop | Exit if wrong |
| target | Target | Exit if right |
| time | Time exit | Held long enough |
| manual | Closed by you | Closed by you |
| entry_not_reached | Entry not reached | Never bought |
| cancelled | Cancelled | Cancelled |

Other investor wording (`PaperDesk.tsx` `wordsFor`): Entry = Buy price, Stop = Exit if wrong, Target = Exit if right, Gross = Before costs, Net = After costs, MFE = Best point, MAE = Worst point, Entry rule = When it buys (At once = Buy now, Break above = Buy above, Pull back to = Buy on a dip to), Observations = Days checked, Unrealised = Gain now, Realised = Gain taken.

### B6. The lists and the trade record

Block "Your paper trades" (`PaperTradesBlock`), inside the card "Your paper trades and price alerts" with a pill "Simulated · no orders".

Tiles: Open (sub-line: "N waiting for the entry" or "Marked at the last close"), Closed ("N won · M lost · K never entered"), Realised (gross; sub-line shows net after costs), Unrealised (gross; sub-line shows net after est. costs, or "N open without a mark"). Rules for the totals (`summarize`, `desk_trading.py:922`): wins and losses count closed trades with realised P&L above or below zero; an unrealised total exists only if every held open trade has a mark (a partial sum would read as the whole); a waiting entry holds nothing and is excluded from unrealised.

Open table columns: Stock (with "Opened <date> · entry status"), Qty, Entry, Stop, Target ("None" if none), Last close (tooltip: end-of-day date, or the mark error), gross P&L, net after costs, a "Record" toggle, and "Close". Closed table columns: Stock ("Closed <date>"), Qty, Entry, Exit, Exit reason pill (asterisk when there is an exit note, explained under the table), Realised, Net, MFE / MAE, Record.

Trade record ("Record" toggle) rows: Signal time, entry rule (with its sentence and window), Entry (status, session, simulated price), Exit rule ("Stop ₹x, target ₹y, or the close of session N held"), Quantity, Estimated costs, Strategy version, Rationale (or note), Observations ("N sessions read - M held"), Exit, gross - costs - net, MFE and MAE, Rules version; then "Rule violations or missing data" listing the flags ("None found.", or "Not recorded for this trade." for old trades). Missing values read "- not recorded".

Rule sentence under the lists: "Simulated: no order is placed. Marks and exits use end-of-day daily bars, checked through <date> (<source>). A session whose low reaches the stop closes the trade at the stop; one whose high reaches the target closes it at the target; one that reaches both closes it at the stop. ... Rules desk-paper-v2. MFE and MAE are the best and worst points reached from the fill through the exit session."

Data: `GET /api/desk/paper-trades?status=all`. Response carries `as_of` (newest session read), `checked_through` (the session every symbol with prices has been read through), `source`, `exit_rule`, `entry_rules`, `rules_version`, `cost_model`, `orders`, `marks_error`, `summary`, `limits.max_open` (100), `evaluated_at`. Closed trades read: the newest 2,000 (`MAX_CLOSED_LISTED`); beyond that `summary.partial` is true and the screen says "Only the most recent closed trades are listed; the counts above cover those listed." Frontend cache: 60 s.

States:

| State | Text |
|---|---|
| Loading | "Loading your paper trades" |
| Failed | "Your paper trades" problem with retry |
| None yet | "No paper trades yet. Add one from a scanner setup on the Chart tab: its risk desk sizes it and records it here, with no order placed." and a button "Open the Chart tab" |
| No open trades | "No open paper trades." |
| All prices unreadable (`marks_error = prices_unavailable`) | "End-of-day prices could not be read just now, so open trades have no mark and none was checked. Nothing is made up; try again later." The lists still show stored trades with null marks |
| Some unreadable (`prices_partially_unavailable`) | "Some end-of-day prices could not be read just now; open trades without a mark were not checked." |
| Per-trade mark error | `no_prices_for_symbol` or `prices_unavailable` in the Last close tooltip |
| Close failed | the error text under the confirmation, e.g. "That paper trade is already closed. (trade_already_closed)" |

Whether the list refreshes immediately after a 409 on close is unverified (the close hook invalidates the list on success only).

### B7. The "Paper trades · predicted vs actual" card

Right-hand card (`PaperCard`, `td/PortfolioTab.tsx:1274`); header meta shows "N closed" (your closed trades). It has two parts.

Part 1, "The model's paper trades · P5-NEXT" (`ModelRecord`). This is the move-odds model's own paper portfolio, not the user's. P5-NEXT is described on screen as "the move-odds model's probability that a stock's high reaches +5% in the next session, over the five it selects each session". A switch chooses the sample:

| Sample | Meaning (note on screen) |
|---|---|
| Forward | "sessions recorded as they happened, after the model was frozen" |
| Replay · 2025 | "the frozen model run over 2025 sessions after the fact; not live" |

Forward and Replay are never pooled (`daas/paper_trades.py` docstring). Route `GET /api/paper-trades/evaluation?sample=&portfolio=P5-NEXT` proxies DaaS `/v1/paper-trades/evaluation`, which returns the latest stored row of `nidp.tpd_paper_evaluations` for that sample and portfolio (newest `as_of_session`, then `computed_at`). "Everything is read back exactly as the engine stored it; nothing here recomputes an outcome." The engine code that fills the table (`tpd_model.paper`) is not in this snapshot, so how the stored figures are computed is unverified here.

Tiles (`recordTiles`, `portfolio-data.ts:524`), over the five selected positions per session ("selected" buckets):

| Tile | Meaning |
|---|---|
| Predicted | prediction-count-weighted mean of the model's probability across buckets, percent. Sub-line "Average model probability - n N" |
| Realised | weighted share of predictions where the high reached +5% the next session. Sub-line "High reached +5% the next session" |
| Net after costs | headline mode's mean net return per trade, x 100, percent, 2 decimals. Sub-line "Average per trade after x% costs - N trades", where x is `costs.base` from the stored evaluation (value not in this snapshot: unverified) |
| False positives | `round(n - realised count)`: selected, but no +5% move, "of N" |

Then: the engine's own statement text (`statement.text`), with "N counted sessions; the pre-registered minimum is M" appended when the text does not mention counted sessions (values come from the stored payload: unverified); then "Calibration": one row per probability bucket that has predictions and both rates stored, e.g. `10-20%  predicted 14% -> actual 11% - n 40`, with two bars (predicted grey, actual mint) on a common 0 to N% scale (N = the larger of 10 and the highest value rounded up to a multiple of 10). Footer: "Latest evaluation stored for the session of <date>."

States: not enabled (403): "The model's paper-trade record is not enabled for this account. It is limited to invited accounts; an admin can turn on the move-odds research feature." (gate: feature flag `move_odds`, 403 for everyone not on the allowlist, admins included; `be/routes/paper_trades.py`); loading "Loading the model's evaluation"; failed "The model's evaluation didn't load" (retry); none stored: "No evaluation of the forward sample is stored yet. The engine stores one after each run." (replace "forward" with "replay"); no bucket with outcomes: "No probability bucket has a selected trade with an outcome yet in the <sample> sample."; unreachable DaaS gives 502 `upstream_unavailable`, never an older copy.

Part 2, your trades: "Open · added today" (open trades whose opened date, India time, is today): symbol, quantity, a pill "P -" (tooltip "No model probability is stored with a desk paper trade"), and "Entry x - Stop y - Target z". "Last 5 closed" table: Trade (symbol, setup label, days held, "target"/"stop"/"closed by you"), P ("-"), Outcome (`(exit - entry) / entry`, percent), R (`(exit - entry) / (entry - stop)`, one decimal, "-" without a stop below entry). Setup label: from `source.bucket` (breakout_confirmed = "Breakout confirmed", pre_breakout = "Near breakout", trend_continuation = "Trend pullback", true_accumulation = "Accumulation"), else "Scanner setup" for a scanner source, else "Setup not recorded" (a trade made from the Lab shows "Setup not recorded"). Empty texts: "No paper trade added today", "No closed paper trades yet." Predicted-vs-actual for the user's own trades is not available: a desk paper trade stores no model probability.

Trust line: source "Move-odds model paper portfolio (frozen) - your desk paper trades, NSE end-of-day bars", historical mode, model-made.

### B8. Price alerts (same card)

"Your price alerts" lists above/below alerts. Above fires on a session whose high reaches the level; below when its low does, from the first session after the alert was made; the fired price is the level. Delete asks for confirmation. Limit 50 active alerts (409 `active_alert_limit`); an identical active alert is 409 `duplicate_alert`. Alerts show here only, no email or push. Other alert conditions (filing, category, volume, scanner, sector, risk) exist in the API and are managed on the Market Intelligence tab (`IntelTab.tsx`); they are outside this part.

---

## C. Options & Futures Lab (under More)

Component `td/FnoTab.tsx`; tab id `fno`, label "Options & Futures Lab". It is not in the desktop tab row; it sits under More (`td/context.tsx:15` comment, `TradingDesk.tsx` header). Analysis only; end of day.

### C1. Data sources and as-of

All data is one NSE F&O bhavcopy per day (`nidp.fno_bhavcopy`), read through the data platform. The app routes are in `be/routes/fno.py`; they require a signed-in user. Frontend cache for chain, expiries and futures: 5 minutes (`trading/fno.ts:231`); scan 10 minutes (`td/fno-buildup.ts`).

| Used for | Route | Underlying |
|---|---|---|
| Expiry switch | `GET /api/fno/{symbol}/expiries` | DaaS `/fno/{symbol}/expiries`; an expiry is "live" if it appeared on the latest day, has option contracts and is not before that day (`live_option_expiries`); `days_to_expiry` counts calendar days from the data's day, not from today |
| Stats, chain table, index cards, strategies | `GET /api/fno/{symbol}/chain?expiry=` | DaaS `/fno/{symbol}/chain`; summary over every strike; the window sent is 40 strikes each side of the ATM strike (`DEFAULT_AROUND = 40`, max 500) |
| Futures price, basis | `GET /api/fno/{symbol}/futures` | DaaS `/fno/{symbol}` for instrument types IDF, STF, FUTIDX, FUTSTK |
| Build-up scan, eligibility | `GET /api/fno/scan/buildup` | DaaS `/v1/desk/fno-buildup` (`daas/desk_market.py:361-545`) |
| India VIX and an index's day change | `GET /api/markets/home` | markets tape |

Spot: the bhavcopy's `underlying_price` for the day, the first positive value among the chain rows (`find_spot`). Lot size: the first positive `new_board_lot_qty` among rows; null if the data platform does not send it.

### C2. Header and underlying row

- Eyebrow "Options & futures lab - NSE F&O", pills "Trader mode"/"Investor mode", "Analysis only", "End of day"; headline "Build, test and understand option trades."
- Spot block (right): "<SYM> - spot", the spot, "Bhavcopy <date> - end of day", and "India VIX x.xx" (with "live" when the tape is live, else the date). Hidden if no spot.
- Underlying row: index buttons NIFTY and BANKNIFTY (default NIFTY); a stock ticker box ("Stock ticker, e.g. RELIANCE", max 20 chars) with Load. Errors: format ("A ticker is letters, digits, & or -, up to 20 characters."); not in the F&O list ("<SYM> is not in NSE's F&O list for <date> (N stocks have futures), so it has no option chain to load."), checked against the build-up scan when it has loaded and is not empty, before any read. A loaded stock shows a pill "<SYM> loaded". Other index symbols (FINNIFTY, MIDCPNIFTY, NIFTYNXT50) can be typed and are treated as indices (not checked against the stock scan).
- F&O eligibility source. For a loaded stock the note reads the NSE F&O lot-size master (`fo_mktlots.csv`, `nidp.security_reference_daily.fno_eligible`, latest row on or before the scan day): "F&O eligible - NSE F&O master <date>"; "Not on the NSE F&O master, though the bhavcopy has its futures"; "In the bhavcopy's stock futures; the F&O master has no row for it"; or "Not in the scan's F&O list". Eligibility is never assumed from a cash listing. Not shown for index underlyings.
- Expiry switch (`ExpiryChooser`): Weekly and Monthly. NSE lists futures for monthly expiries only, so an option expiry that a future shares is "monthly"; "weekly" is the nearest other expiry before the farthest listed future (longer-dated quarterly options lie beyond it). The nearest expiry still to come is the default (expiries 0 days away are used only if no later one exists). If the futures did not load, one button "Nearest - <date>" appears (weekly and monthly cannot be told apart). A disabled option says "No weekly expiry is listed for <SYM>" (stocks have no weekly expiry). If the expiry list fails: "The expiry list didn't load, so only the nearest expiry is shown." with Retry.

### C3. The eight stats

Shown in a grid (4 x 2; 2 columns on phone) under the header (`chainTiles`, `td/fno-parts.tsx:276`). Beneath: "IV and the expected move: Model estimate from end-of-day prices (Black-76), at an interest rate of 5.75% a year. They are estimates, not quotes; the expected move is what the ATM straddle cost at the close, not a forecast. PCR is put open interest / call open interest over every strike; max pain is the strike where open options pay out least at expiry; build-up reads the stock future's price change against the change in its open interest over every expiry." Then the build-up caveat and a trust line.

| Tile (trader / investor) | Rule |
|---|---|
| ATM implied volatility / Expected volatility | Mean of the call and put implied volatility at the ATM strike (or the one that exists), percent a year. Implied volatility: Black-76 on a forward, solved from the contract's settle price, else its close; search range 0.01% to 500% a year; `RISK_FREE_RATE = 0.0575`; time = calendar days / 365 (`services/option_pricing.py:66-68`). A contract with zero volume and zero open interest is not priced; one expiring on the data's day is not priced; a price at or below intrinsic gives none. "-" with "No model estimate at the ATM strike" if none |
| Expected move to expiry / Expected swing | ATM straddle = call close + put close at the ATM strike (both above zero), price points, plus percent of spot. Null on the expiry day itself. "A market price for movement to expiry, not a forecast and not a probability" (`fno.py` docstring) |
| Futures - <expiry> | Nearest future's settle price (first future whose expiry is after the data's day, else the first); sub-line "+x premium to spot" / "-x discount to spot" / "Level with the spot". Basis = futures settle - spot, 2 decimals |
| Days to expiry | calendar days from the data's day to the expiry |
| Put-call ratio - OI | total put open interest / total call open interest over every strike of the expiry; null when there is no call OI |
| Max pain | strike K where `sum(call OI x max(K - k, 0)) + sum(put OI x max(k - K, 0))` is smallest, over every strike of the expiry; a tie goes to the strike nearer the spot, then the lower; null with no open interest |
| OI range | "<put wall> - <call wall>": the strike with the most put OI to the strike with the most call OI (tie: nearer the spot, then lower) |
| Futures build-up / Open bets (OI) change | The loaded underlying's build-up label with "Price x% - OI y% - <date>" (investor: plain sentence). Stock: its row in the scan. Index: its row in the scan's index list. Otherwise the reason: "Reading the build-up scan", "The build-up scan didn't load", "Not in the stock-futures scan for <date>", "A price or OI change is missing in the scan", or "The build-up scan has no index futures row for this index", plus "OI +n" from the futures list |

Forward used for the model: the settle price of the future expiring the same day ("future"); else the put-call-parity forward from the strike where call and put are closest in price among strikes where both traded (volume above zero) ("put-call parity"); else spot carried at the rate ("carried spot"). If the futures read failed, no forward is chosen and all model fields are null (the chain still answers). The Lab shows only ATM IV and expected move from this model; the chain route also returns per-contract IV and Greeks, which the Lab does not display.

States (`FnoGate`): loading "Loading the <SYM> chain"; error "The <SYM> option chain" with retry; no rows: title "No F&O rows for <SYM> on the latest day", body "The server said: '<message>'. Only indices and stocks in NSE's F&O segment have contracts in the end-of-day file, so check the ticker." Server messages: 404 "No F&O data for <SYM>", "No option contracts are listed for <SYM>", "No option contracts for <SYM> expiring <date>"; 502 `upstream_unavailable` when the data platform is not configured, unreachable or answers unexpectedly. Futures failure adds a problem line "<SYM> futures" and the tile says "The futures didn't load".

Investor extras: a "Read first" amber note: "9 out of 10 individual traders in equity F&O incurred net losses (SEBI study). Options and futures can lose more than you put in, quickly. Everything here explains end-of-day data; Nivesh cannot place orders." (`SEBI_FNO_NOTE`, `trading/parts.tsx:10`).

### C4. Sub-tab 1: "OI build-up - F&O stocks" (`td/FnoBuildup.tsx`)

Four quadrant cards, a scatter, a table, the 15-minute confirmation state, and notes.

The exact build-up rule (`buildup_label`, `daas/desk_market.py:418`; one row per stock future underlying):

| Label | Price change | OI change | Trader / investor description |
|---|---|---|---|
| Long build-up | > 0 | > 0 | "Price up, OI up" / "Price rose and new bets were opened" |
| Short build-up | < 0 | > 0 | "Price down, OI up" / "Price fell and new bets were opened" |
| Short covering | > 0 | < 0 | "Price up, OI down" / "Price rose as bets were closed" |
| Long unwinding | < 0 | < 0 | "Price down, OI down" / "Price fell as bets were closed" |
| Neutral | either is exactly 0 | | "Price or OI unchanged" |
| (no label) | a change is missing | | counted as "no data" |

Definitions behind the inputs:

- Price change = the nearest expiry's `close_price` vs its `prev_close_price` (the label reads the raw difference, so +0.004% still counts as up; `price_chg_pct` is the rounded percent).
- OI = open interest summed over every expiry; OI change = `change_in_oi` summed over every expiry, so a roll near expiry does not read as unwinding. If any expiry's figure is missing, the sum is null (a partial sum is never passed off as the whole).
- `oi_chg_pct` = OI change / (OI - OI change), in percent.
- It is "a reading of two figures, not a record of who traded." The screen says: "These are heuristic readings of two figures, not proof of what traders intended. Rollovers, expiry, intraday noise and changes in who trades a contract can distort them."

Quadrant cards: four buttons with the route's count of stocks per label, "of N stocks", and the rule. A card is a filter (click again to clear). Under them: "N neutral (price or OI unchanged) - N without a label (a change is missing) - N F&O stocks scanned - showing <label> only". Counts are over the whole universe the route scanned.

Scatter "Price change vs futures OI change - N largest OI moves": x = price change %, y = OI change %; the 24 stocks (`SCATTER_N`) with the largest absolute OI change that have both figures; the six biggest moves and the loaded stock are named; quadrants are tinted and named; a dot (click or Enter) loads that stock's option chain. "No stock has both a price change and an OI change in the rows sent." when none. The scan has no traded volume, so "most active" is read as the largest OI move.

Table "Stock futures - OI build-up" (12 columns, scrolls sideways): Stock (with futures close), Price (change %), Futures OI (OI change % with a bar), Cash (cash close and change %), Cash check (Confirms / Diverges; investor "Same way / Opposite": the near future and the cash close moved the same way / opposite ways that day; "-" when either move is missing or flat), RVOL z (the stock's `vol_z20` from `stock_features_daily`, the latest within 7 days of the scan day; the tooltip gives its date), Volume (futures contracts traded over every expiry; tooltip gives ₹ Cr traded), PCR and IV (only for the loaded stock, "-" for others because the scan does not send them), Expiry - flags (near expiry date, days to expiry, flags), Quality ("-" always: `setup_quality` is null and the scan says "not_validated"; no model of these readings has been tested), Build-up (label pill and description). Default order is the route's: largest absolute OI change % first. Sort by stock, price change or OI change (first click: symbol ascending, others descending; missing values last). Thirty rows first, then "Show all N". A row click loads the stock's chain.

Risk flags (`risk_flags`, `desk_market.py:346`): `expiry_week` (the nearest contract expires within 7 calendar days; "price and OI moves are distorted by expiry"), `rollover` (in expiry week and the next expiry holds more OI than the nearest), `no_cash_price` (no cash close that day; the cash check cannot be made). The table shows the first two as pills; `no_cash_price` appears as an empty cash check.

Universe: stock futures (instrument type STF) on the latest bhavcopy day or the given date, one row per underlying; the cash side is `prices_eod` with series preference EQ, BE, BZ, SM, ST. The footer line says how many scanned stocks are on the NSE F&O master, how many are in the bhavcopy but not on the master, and how many the master's file has no row for.

15-minute confirmation (`IntradayState`, PRD §10.5): a card with four states shown as pills (candidate, confirmed, invalidated, unavailable) and the current one marked. Today the state is always "unavailable". The reason comes from the scan (`intraday.reason`): "No intraday open interest is collected: the F&O data is the end-of-day bhavcopy, and the intraday bar collector stores no OI and no NFO contracts. A 15-minute confirmation cannot be worked out." The screen adds "No setup is marked confirmed from a single end-of-day reading." The state is never faked. The route currently hard-codes "unavailable" (`desk_market.py`, `intraday` key); the other three states are never produced by this code.

States: loading "Scanning F&O stocks for OI build-up"; failed "OI build-up across F&O stocks" with retry; no rows: "No stock futures on the latest day" ("The end-of-day F&O file the route read has no stock-futures rows to scan."); a filter with no matches: "No stock has this label in the rows sent."

### C5. Sub-tab 2: "NIFTY & BANKNIFTY"

Two cards (`IndexCard`), one per index, each reading its own chain (nearest expiry), futures and the scan's index rows. Header: symbol, "<date> expiry", a build-up pill (the index future's label from the scan's `indices` list, with tooltip "Price up, OI up - index futures, <date>"; "Build-up -" with a reason when missing). Body:

- Spot (display size), a change figure and "end of day <date>". The change is the markets tape's, shown only when the tape is a closed session on the same date as the bhavcopy; otherwise "change -" with the tooltip "The bhavcopy has no previous spot, and the markets tape is for another session".
- A headline sentence: "Spot is below the X put wall." / "Spot is above the Y call wall." / "Spot sits between the X put wall and the Y call wall." (investor: "Below the level where most put bets sit (X)." etc.); "The chain has no open-interest walls to read." if a wall or spot is missing.
- "OI range and expected move": a bar with the put wall, call wall, spot and the expected-move band (spot +/- straddle), with a legend.
- Rows: Futures - premium (settle, premium/discount to spot), Futures OI change (nearest future's `change_in_oi`, signed), Futures chg - cash check (the index future's price change % and "same way as the index" / "opposite to the index" / "no index move to compare"; the index close is the cash side, from `nidp.index_eod`; index names Nifty 50 and Nifty Bank), Put-call ratio - OI, Max pain, ATM IV - expected move ("x% - +/-points (pct)").
- A link "Open the <SYM> option chain >" which switches to the chain sub-tab for that index.

The scan's index list also covers FINNIFTY (Nifty Financial Services), MIDCPNIFTY (Nifty Midcap Select) and NIFTYNXT50 (Nifty Next 50) (`INDEX_FUTURES`), but the Lab shows cards for NIFTY and BANKNIFTY only. Index futures are not counted in the stock quadrant counts.

### C6. Sub-tab 3: "Option chain OI - <SYM>" (`ChainOiTable`)

Card header "Option chain OI - <SYM> - <expiry date>" with meta "R call wall - S put wall - MP max pain".

Columns, left to right: Call OI chg, Call OI (with a red bar), Call close, Strike (with tags), Put close, Put OI (with a mint bar), Put OI chg. Shown: 10 strikes each side of the ATM strike (`CHAIN_EACH = 10`), centred on it, in a table that scrolls sideways on narrow screens. OI bars are scaled to the largest OI shown. Close is the end-of-day closing price, not a live quote. OI changes are signed and coloured.

Tags next to a strike (`strikeTags`):

| Tag | Meaning | How computed |
|---|---|---|
| ATM | strike nearest the end-of-day spot | `atm_strike`: minimum of `abs(strike - spot)`; an exact tie goes to the lower strike. Highlighted row |
| R | call wall | the strike with the most call open interest in the whole expiry (`top_oi_strike`; a tie goes to the strike nearer the spot, then the lower) |
| S | put wall | the strike with the most put open interest in the whole expiry (same tie rule) |
| MP | max pain | as in C3 |

The route works these over every strike of the expiry the data platform returned, not just the 10 shown ("the tags and the totals cover all of them"). A strike can carry several tags. Below the table: one plain reading, for example "For the 27 Oct expiry, the most call open interest is at 25,500 (x), the most put open interest at 25,000 (y), the put-call ratio on open interest is 0.9, max pain is 25,200. The end-of-day spot of ... is between the two. These are positions at the close, not price targets." plus "Showing 21 of the expiry's N strikes", and the source line "NSE F&O bhavcopy - end of day - as of <date>". If the chain is missing: "No option chain for <SYM>; see the note above." (or the loading block).

### C7. Sub-tab 4: "Paper strategies" (`td/FnoStrategies.tsx`)

Rules-based paper ideas for the loaded underlying and expiry, worked out in the browser from three inputs: the build-up label, the chain (walls, ATM IV, expected move, option closes) and the nearest future's settle price. Header: "<SYM> - <expiry>", the build-up pill, "Rules-based - paper trading only". Three cards: Futures, Options, Cash - delivery; then "Why these"; then a table of every F&O underlying; then the disclaimer.

Rule 1, names from the build-up alone (`strategyNames`):

| Build-up | Futures | Options | Cash - delivery |
|---|---|---|---|
| Long build-up | Long futures | Bull call spread | Delivery long (not for an index) |
| Short build-up | Short futures | Bear put spread | none |
| Short covering | none | Bull call spread | none |
| Long unwinding | none | Bear put spread | none |
| Neutral | none | Iron condor | none |
| No label | none | none | none |

Futures only on fresh positions (OI up); options as defined-risk spreads; delivery only on long build-up.

Rule 2, levels from the OI walls (`levelsFrom`): a rising idea's stop is the put wall and its target the call wall; a falling idea the other way round. A wall on the wrong side of the entry price is replaced by the edge of the expected move (entry -/+ the straddle). A level that would be zero or negative is dropped.

Rule 3, spread strikes (`spreadStrike`): the long leg is at the ATM strike. The short strike is the wall (call wall for a bull call spread, put wall for a bear put spread) when it lies on the correct side of the ATM strike and within the expected-move edge (spot +/- straddle); otherwise the listed strike nearest that edge on the correct side. Debit = long close - short close (the idea is "no idea" if either close is missing or the debit is not positive). Max profit = strike width - debit; max loss = debit; breakeven = ATM strike +/- debit.

Iron condor: only suggested if the spot is strictly between the put wall and the call wall and both walls are at least one expected move away from the spot. Legs: short put at the put wall, long put at the strike one step below it, short call at the call wall, long call one step above. Net credit = (short put - long put) + (short call - long call); width = the larger wing width; max loss = width - credit; breakevens = put wall - credit and call wall + credit. If a leg has no closing price, or there is no strike beyond a wall, the card explains and shows no figures. If the price is not between the walls, or the expected move reaches past a wall, no condor is offered and the card says why.

Futures card: entry = the nearest future's settle price; stop and target from rule 2; reward : risk; "One lot risks ₹x to make ₹y" using the lot size (when the lot size is known). Cards show per-unit end-of-day closes; one lot = the route's lot size.

What posts a paper trade. Only the "Cash - delivery" card can. Its "Add to paper trades" button posts `POST /api/desk/paper-trades` with symbol, quantity = one lot's worth of shares (the route's lot size), entry = spot (the bhavcopy underlying close, rounded to paise), stop and target from rule 2 (rising: put wall and call wall, or the expected-move edges), and source `{kind: "fno-lab", bucket: "Cash - delivery - long build-up", signal_date: <bhavcopy day>}`. It is an at-once long share paper trade like any other (B1 to B6), marked against end-of-day closes. The button is disabled with a reason when: no idea (the build-up gives none, or the underlying is an index), no spot, no lot size ("The route sent no lot size, so the quantity (one lot's worth of shares) is unknown."), or no stop below / target above ("Needs a stop below and a target above the price; the chain gives neither wall nor expected move."). On success: "Paper trade added: N <SYM> at ₹x. No order is placed." with a link to the Portfolio tab. Failure: "Not added - <server words>".

Futures and Options buttons stay disabled: "Paper trades hold shares only for now, so a futures idea cannot be recorded." (same for options). So the Lab never records a futures or option position.

Index underlyings. The strategy view gets the build-up row only for stocks (`row = index ? null : buildupRowFor(...)`, `FnoStrategies.tsx:475`), so every index (NIFTY, BANKNIFTY) shows "No trade suggested" in all three cards, with the text "Index futures have no build-up reading here (the futures route sends no previous close), so the rules suggest nothing." and the "Why these" line saying the same. This is inconsistent with the other tabs: the stats tile and the index cards do show an index build-up label from the scan's `indices` rows. The "no previous close" reason is true of `GET /api/fno/{symbol}/futures` (DaaS `/fno/{symbol}` does not select `prev_close_price`, `daas/fno.py`) but not of the scan. Recorded here as observed code behaviour.

"Why these" lists: the build-up reading with the future's price and OI change; the walls; the ATM IV and straddle swing to the expiry; the three one-line rules; and "Prices are end-of-day closes per unit; one lot is N units."

The all-underlyings table: rows are NIFTY, BANKNIFTY (no label, names "-"), then every stock in the scan; columns Underlying, Build-up, Futures, Options, Cash (names from the build-up alone); 12 rows first then "Show all N". Clicking a row loads that underlying. Only the loaded underlying has legs and levels.

Disclaimer: "Rules-based paper ideas from end-of-day data, for learning - not a recommendation to buy or sell. 9 out of 10 individual traders in equity F&O incurred net losses (SEBI study). Nivesh cannot place orders."

States: the chain gate states of C3 apply; the table shows "Reading the build-up scan..." and an error with Retry when the scan fails.

### C8. What is not available in the Lab, and why

| Item | Why |
|---|---|
| Index day change on the card | the bhavcopy carries no previous spot; the markets tape is used only when it is for the same closed session |
| Per-stock PCR and IV in the build-up table | the scan does not send them; only the loaded stock's own chain supplies them |
| Setup quality or probability on a build-up | no validated model exists; `setup_quality` is null / "not_validated" |
| 15-minute confirmation | no intraday open interest is collected |
| Futures day change and option build-up on the futures list | `GET /api/fno/{symbol}/futures` shows change and build-up only once the data platform sends `prev_close_price` for futures rows; its `/fno/{symbol}` query does not select that column, so they are null. (The chain route's per-option `oi_buildup` exists but the Lab does not display it.) |
| Greeks and per-contract IV | returned by the chain route; not shown in the Lab |
| Recording a futures or options paper trade | the paper store holds long share positions only |
| Orders | never; analysis only |
| Live prices | all figures are one end-of-day file |


---

# Smart Trading Desk: API, data sources and operations

Basis: code snapshot `/home/deploy/nivesh-fix-bse` (origin/dev), PRD `/home/deploy/nivesh.ai/docs/smart_trader`. Freshness figures come from read-only SELECTs on the staging warehouse run on 2026-10-20 about 09:13 IST. Anything not confirmed in code or by a check is marked "unverified". Nothing on the desk places an order.

## 1. Route catalogue

Conventions:
- "Session" means `get_current_user` (signed-in user). "Flag X" means `require_feature("X")`: the account must be on that flag's allowlist, otherwise 403 `feature_not_enabled` (503 `feature_state_unavailable` if flags cannot be read). Source: `backend/feature_gate.py`.
- The browser calls the app backend (`/api/...`). Most reads then call the data API (DaaS, `/v1/...`) through `backend/services/copilot_tools/daas_client.py`. Writes only ever go to the app's MongoDB.
- Every write passes the app's CSRF middleware (`backend/middleware.py`); the desk routes are not exempt (`routes/desk_trading.py` docstring).
- The frontend files are under `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/` unless stated.

### 1.1 Overview, macro and market status

| Method and path | Auth | Key parameters | Response (fields) | Source | Writes |
|---|---|---|---|---|---|
| GET `/api/markets/home` | Session | none | index tape, breadth, `market_state`, `is_live`, FII/DII, `holiday` | `services/positional_engine/market_dashboard.py` (app-DB `stock_ohlcv`) plus `nse_live.py` (yfinance quotes); holiday check via DaaS `/v1/holidays` (`nidp.nse_holidays`); cached in process | No |
| GET `/api/macro/today` | Session | none | `market` BULL/NEUTRAL/BEAR, `regime.key` (five desk regimes), values, insight; soft-fails with `_reason` | app-DB tables `macro_state`, `macro_features`, `macro_daily` via `services/macro_engine.py`; refreshed 18:35 IST by `mf_scheduler` in the app backend | No |
| GET `/api/markets/sector-returns` | Session | none | per sector index: close, `ret_1d/5d/21d_pct`, own `date`, breadth | DaaS `/v1/desk/sector-returns`; `nidp.index_eod`, `nidp.index_constituents`, `nidp.prices_eod` | No |
| GET `/api/markets/sector-constituents` | Session | `index` | constituents with their move on the index's latest close day, breadth | DaaS `/v1/desk/sector-constituents`; same tables | No |
| GET `/api/positional/market-dashboard` | Session | none | `sector_heatmap` (the desk reads leaders only) | app-DB `stock_ohlcv` | No |

### 1.2 Scanner, setups and risk

| Method and path | Auth | Key parameters | Response (fields) | Source | Writes |
|---|---|---|---|---|---|
| GET `/api/positional/watchlist` | Session | `limit` (30) | `as_of_date`, four `buckets` (TRUE_ACCUMULATION, PRE_BREAKOUT, BREAKOUT_CONFIRMED, TREND_CONTINUATION), trigger, stop, support, resistance, `spark_closes`, `rules` | app-DB `stock_technical_features` plus 60 daily bars from `stock_ohlcv` (`routes/positional.py`) | No |
| GET `/api/positional/picks` | Session | `date`, `min_score` (0.55), `stage`, `limit` | `signal_date`, `picks` (entry, stop, target, score), `rules_version`, `engine_versions` | app-DB `positional_signals` joined to `stock_technical_features` | No |
| GET `/api/positional/picks/mine?live=true` | Session | `live`, `limit` | picks filtered to the user's portfolio, delayed live price, readiness | same tables plus the user's holdings | No |
| GET `/api/positional/scan-universe` | Session; the move-odds rank is added only if the user has flag `move_odds` (`routes/positional.py` line 506) | `setups`, `symbols` | momentum, unusual volume, results-day, F&O candidate categories; eligible universe with exclusion counts; model rank; `rules` | DaaS `/v1/features/scan-snapshot` (`nidp.stock_features_daily`, `nidp.security_reference_daily`); rank from DaaS `/v1/move-odds/latest` | No |
| GET `/api/positional/backtest/calibration` | Session | `symbol`, `horizon_days`, `metric` | accumulation detector's historical record, Wilson intervals, period | app-DB backtest tables (`routes/positional.py`) | No |
| GET `/api/positional/scenario` | Session | `entry`, `stop`, `target`, `capital`, `risk_pct`, ... | sizing result | pure calculation; "nothing is sent to a broker" (docstring) | No |
| GET `/api/move-odds/latest` | Flag `move_odds` | `head` (default `p_up5_1d`) | model run, out-of-sample record, per-stock estimates | DaaS `/v1/move-odds/latest` (`nidp.tpd_*`) | No |
| GET `/api/move-odds/stocks/{symbol}` | Flag `move_odds` | `symbol` | four next-session estimates and events for one stock | DaaS `/v1/move-odds/stocks/{symbol}` | No |
| GET `/api/watchlists`, `/api/watchlists/{id}` | Session | none | the user's own lists | MongoDB | No |
| POST `/api/watchlists/{id}/symbols` | Session | symbol | updated list | MongoDB (the user's own list) | Yes (user's own watchlist; not desk-specific) |

### 1.3 Chart tab

| Method and path | Auth | Key parameters | Response (fields) | Source | Writes |
|---|---|---|---|---|---|
| GET `/api/research/chart-live/{symbol}/ohlcv` | Flag `charting` | `start`, `end` | bars `[date, o, h, l, c, v]` (split and bonus adjusted); bad bars dropped | DaaS `/v1/prices/adjusted/{symbol}` (`nidp.prices_eod_adjusted`) | No |
| GET `/api/research/chart/live/{symbol}/indicators` | Flag `charting` | symbol | every indicator value with lookback | DaaS `/v1/prices/adjusted/{symbol}` (LIVE_BARS) plus `/v1/indices/{benchmark}/eod`; computed in `routes/research_chart.py` | No |
| GET `/api/research/chart/live/{symbol}/patterns` | Flag `charting` | symbol | detected patterns, states, criteria (`research.charting`) | same bars | No |
| GET `/api/filings/feed` | Session | `symbol`, `days`, `category`, `family=calls|ownership|exchange`, `provenance=1`, `limit`, `sort` | filings, facets, pagination; with provenance: published_at, ingested_at, broadcast_at, sector, peers | classified articles query (`routes/markets.py`); with `family`, DaaS `/v1/desk/filings` and `/v1/desk/event-sources` (`nidp.corporate_announcements`, `nidp.v_event_asof`) | No |
| POST `/api/copilot/widgets/company_financials` | Session | symbol | fundamentals and ownership figures | `services/copilot_tools/company_financials.py` (DaaS) | No (a read despite POST) |

### 1.4 Intel tab

| Method and path | Auth | Key parameters | Response (fields) | Source | Writes |
|---|---|---|---|---|---|
| GET `/api/filings/feed` | Session | as above, `family` | as above | as above | No |
| GET `/api/filings/{id}/insights` | Session | id | generated read for one filing | filing insights output (`routes/filings.py`) | No |
| GET `/api/markets/deals` | Session | `days` (5), `kind` (all/bulk/block), `limit` (200) | rows with qty, price, `value_cr`, % of shares, close around the deal, `as_of`, source | DaaS `/v1/desk/deals`; `nidp.bulk_deals`, `nidp.block_deals` | No |
| GET `/api/markets/circulars` | Session | `days` (1-365, 30), `limit` (1-200, 50) | `rows` (title, url, kind, issued_on), `as_of`, `checked_at`, `source` | DaaS `/v1/circulars/sebi`; `nidp.sebi_circulars`; 502 `upstream_unavailable` if DaaS fails | No |
| GET `/api/markets/fii-dii` | Session | `days` (7-365) | `as_of`, `daily`, `monthly` | DaaS `/v1/market-pulse/fii-dii`; `nidp.fii_dii_flows` | No |
| GET `/api/markets/sector-returns` | Session | none | as 1.1 | as 1.1 | No |

### 1.5 Futures and options tab

| Method and path | Auth | Key parameters | Response (fields) | Source | Writes |
|---|---|---|---|---|---|
| GET `/api/fno/{symbol}/expiries` | Session | symbol | expiry list | DaaS `/v1/fno/{symbol}/expiries`; `nidp.fno_bhavcopy` | No |
| GET `/api/fno/{symbol}/chain` | Session | `expiry` | strikes, OI, change in OI, IV and expected move (Black-76 on end-of-day prices, `services/option_pricing.py`) | DaaS `/v1/fno/{symbol}/chain` | No |
| GET `/api/fno/{symbol}/futures` | Session | symbol | futures price, basis, OI change | DaaS `/v1/fno/{symbol}` per instrument type | No |
| GET `/api/fno/scan/buildup` | Session | `date` | one row per F&O stock (price change, OI, `oi_chg_pct`, `label`, `cash_confirmation`, `vol_z20`, `fno_eligible`, `risk_flags`), `indices`, `intraday` state | DaaS `/v1/desk/fno-buildup`; `nidp.fno_bhavcopy`, `prices_eod`, `index_eod`, `stock_features_daily`, `security_reference_daily` | No |
| GET `/api/markets/home` | Session | none | India VIX and index change | as 1.1 | No |

### 1.6 Portfolio tab

| Method and path | Auth | Key parameters | Response (fields) | Source | Writes |
|---|---|---|---|---|---|
| GET `/api/portfolio/holdings-enriched` | Session | none | holdings, weights, totals (5-minute cache) | MongoDB holdings plus prices (`services/portfolio_enrichment.py`) | No |
| GET `/api/portfolio/holdings` | Session | none | stored holdings, including rows a broker read wrote | MongoDB | No |
| GET `/api/portfolio/composition/scope` | Session | none | accounts and sources behind the totals, instrument types, allocation, instruments in more than one source | MongoDB | No |
| GET `/api/portfolio/capital-gains-statement` | Session | none | realised gains this FY (FIFO) | MongoDB transactions (`routes/portfolio_tax.py`) | No |
| GET `/api/portfolio/risk-analytics` | Session | none | weighted beta, volatility, Sharpe, VaR, risk drivers | DaaS V3 primitives in bulk | No |
| GET `/api/portfolio/exposure/concentration` | Session | none | sector, AMC and company look-through | MongoDB plus DaaS | No |
| GET `/api/portfolio/correlation` | Session | `sessions` (120), `limit` (10) | pairs, `avg_corr`, `pairs_excluded`, skipped stocks | DaaS `/v1/prices/adjusted/{symbol}` per held stock | No |
| GET `/api/portfolio/market-cap-split` | Session | none | Large/Mid/Small/Micro/Unclassified buckets, `unsplit` | DaaS `/v1/indices/{index}/constituents` for Nifty 100, Midcap 150, Smallcap 250, Total Market | No |
| GET `/api/portfolio/holding-risk` | Session | `sessions` (250) | liquidity, days to sell, overnight gaps, drawdown, 1-month volatility, `rules` | DaaS `/v1/prices/adjusted/{symbol}` | No |
| GET `/api/paper-trades/evaluation` | Flag `move_odds` | `sample`, `portfolio` (P5-NEXT) | calibration buckets, modes | DaaS `/v1/paper-trades/evaluation` | No |
| GET `/api/paper-trades/trades/{id}` | Flag `move_odds` | id | one trade with lifecycle log | DaaS `/v1/paper-trades/trades/{id}` | No |
| POST `/api/portfolio/upload/preview` | Session | multipart `file` (.csv/.xlsx/.xls) | `preview_id`, `rows` with status and flags, `counts`, `effects`, `limits`, `nothing_saved: true` | parsed in `routes/upload.py`; stored in Mongo collection of previews, 30-minute TTL | Writes the preview document only. Holdings are not touched |
| POST `/api/portfolio/upload/preview/{id}/commit` | Session | body `{rows?: [row_no]}` | `count`, `holdings`, `committed_rows`, `left_out_rows` | `save_holdings` into the user's holdings | Yes: user's holdings (import). 404 not yours, 410 expired, 409 committed, 422 invalid rows |

### 1.7 Broker reads (desk "Positions" and Portfolio)

All require a session. Routes `/api/broker/holdings`, `/positions`, `/funds`, `/accounts/{id}/contract-chart`, and syncing a native account need flag `broker_hub` (default mode "everyone" in `feature_flags.py`). Accounts and disconnect do not.

| Method and path | Key parameters | Response | Source | Writes |
|---|---|---|---|---|
| GET `/api/broker/accounts` | none | the user's broker connections | MongoDB | No |
| GET `/api/broker/holdings` | none | live holdings per account; OpenAlgo accounts listed as "not readable" | broker adapter through `services/brokers/hub_reads.py` | No (never stored) |
| GET `/api/broker/positions` | none | live open positions per account | same | No |
| GET `/api/broker/funds` | none | cash and margin per account | adapter `fetch_funds` | No |
| GET `/api/broker/accounts/{id}/contract-chart` | contract query | chart for a position contract | broker read | No |

### 1.8 Paper trading and alerts (desk-only writes)

Defined in `backend/routes/desk_trading.py` (prefix `/api/desk`) with the rules in `services/desk_trading.py` and `services/desk_alerts.py`. Session auth. The store is MongoDB collections `desk_paper_trades` and `desk_price_alerts`. Every document carries `user_id`.

| Method and path | Body or parameters | Response | Writes |
|---|---|---|---|
| POST `/api/desk/paper-trades` (201) | `symbol, quantity, entry_price, stop_price, target_price|null, note?, source?{kind,bucket?,signal_date?}, entry_rule? (at_once, break_above, pullback_to), entry_window_sessions?, max_hold_sessions?, signal_at?, strategy_version?, rationale?`. Long only | `{trade, ...price context}` | Yes: inserts a paper trade. 409 `open_trade_limit` at 100 open |
| GET `/api/desk/paper-trades?status=open|closed|all` | `status` | `{as_of, checked_through, trades, summary}`; applies the exit rule first; marks null with `marks_error` if prices cannot be read | Yes, idempotent: stop/target exits are written with the trade's status in the update filter |
| POST `/api/desk/paper-trades/{id}/close` | `{exit_price?}` only (other keys 422 `unknown_field`) | closed trade; a conditional entry never reached becomes "cancelled" | Yes: closes the user's own trade. 404 if not yours |
| POST `/api/desk/alerts` (201) | `{condition, ...}` with condition in above, below, filing, category, volume, scanner, sector, risk | `{alert}` | Yes: inserts an alert. 409 `active_alert_limit` at 50, 409 `duplicate_alert` |
| GET `/api/desk/alerts?status=active|fired|all` | `status` | `{as_of, checked_through, alerts, conditions, check_errors}`; checks every active alert first | Yes, idempotent: fires one-shot alerts |
| DELETE `/api/desk/alerts/{id}` (204) | none | empty | Yes: deletes the user's own alert; 404 if not yours |

Condition inputs are listed in the `services/desk_alerts.py` docstring (above/below: symbol, level; filing: symbol, impact; category: category, symbol?; volume: symbol, multiple; scanner: symbol, stage?; sector: index, threshold_pct, direction; risk: symbol, level).

### 1.9 Other routes the desk touches

| Method and path | Auth | Use | Writes |
|---|---|---|---|
| POST `/api/chat/stream` | Session | the Copilot dock (same Copilot as the rest of the app) | Writes chat history (app behaviour; not desk-specific) |
| GET `/api/sim-lab/run`, `/matrix`, `/trades`, `/candidates` | Flag `sim_lab` | Simulation Lab screen; reads a committed snapshot, no DB or network | No |
| GET `/api/research/chart-layouts` | not checked | exists in backend; whether the desk calls it is unverified | not checked |

**No order placement.** Nothing in the catalogue sends an order. The desk writes only paper trades, alerts, a portfolio import (after a user-confirmed preview), watchlist symbols and chat history. See section 5.

## 2. Data sources

Scheduling lives in `deploy/cloudpe/nidp/nidp-staging.cron` (warehouse VM, user `nidp-staging`, `CRON_TZ=Asia/Kolkata`, each entry runs `/opt/nidp-staging/run_service.sh <service>`; the wrapper locks per service and retries 3 times with backoff unless `NIDP_MAX_ATTEMPTS` is set) and the app-VM cron files in `deploy/nivesh-staging/`. "Latest" below is the maximum date seen on 2026-10-20 about 09:13 IST.

| Source (table) | Holds | Loaded by | Schedule (IST) | Latest on staging | Gaps and failure behaviour on the desk |
|---|---|---|---|---|---|
| `nidp.prices_eod` | raw NSE bhavcopy bars | `bhavcopy` | 19:00 Mon-Fri | 2026-10-19 (872,537 rows) | Desk marks, alerts and paper trades use raw prices. If DaaS fails, paper-trade lists still answer with stored trades, marks null and `marks_error` set |
| `nidp.prices_eod_adjusted` | split/bonus adjusted bars | `price_adjuster` | 22:30 Mon-Fri | 2026-10-19 | Charts, indicators, correlation and holding risk. `charting` 403 without the flag |
| `nidp.index_eod` | index closes | `index_close` | 19:00 Mon-Fri | 2026-10-19 | Sector tiles show each index's own date, so a lagging index is visible |
| `nidp.index_constituents` | NSE index lists | `index_constituents` | 06:30 on the 1st of the month; also ran 2026-10-20 00:28 | 2026-10-20; 27 indices including Nifty Midcap 150 (150 rows), Smallcap 250 (251), Total Market (755), 15+ sector lists | Market-cap split reports a bucket only when every list that decides it exists; otherwise `unsplit` |
| `nidp.fno_bhavcopy` | futures and options, all expiries | `fno_bhavcopy` | 19:30, 21:00, 22:15 Mon-Fri (retries, upsert) | 2026-10-19 (635 STF rows that day) | NSE posts the file after 19:30. The job log shows the 19:30 run on 2026-10-19 FAILED and the 22:21 run OK. No intraday or 15-minute OI: the build-up `intraday` state is "unavailable" and the UI shows the reason |
| `nidp.fii_dii_flows` | FII/DII cash flows (NSE provisional) | `fii_dii` | 19:30 Mon-Fri | 2026-10-19 (14 rows in total) | Thin history. Chart is short |
| `nidp.bulk_deals`, `nidp.block_deals` | NSE deal disclosures | `bulk_deals`, `block_deals` | 19:30 Mon-Fri | bulk 2026-10-19; block 2026-10-12 (2 rows in total) | Window ends at the latest deal date across both tables. A day with no block deals is a real empty |
| `nidp.corporate_announcements` | NSE and BSE filings, classifier fields | `corporate_announcements_nse`; `corporate_announcements_bse` (HELD) | NSE every 10 min 09-23 Mon-Fri, every 30 min 09-23 Sat/Sun | NSE_ANN to 2026-10-20 07:10 (187,600 rows); BSE_ANN last filing 2026-10-13 (3,486 rows) | BSE returns HTTP 403 "Access Denied" to this VM; every `corporate_announcements_bse` run in the last days is FAILED. Fix needs `BSE_PROXY_URL`. Desk filings and filing alerts see NSE filings only after 2026-10-13 |
| `nidp.sebi_circulars` | SEBI circulars and master circulars | `sebi_circulars` | 09:15-21:15 every 3 h, Mon-Sat (in the cron file) | table is empty (0 rows); `job_log` has no `sebi_circulars` row | `/api/markets/circulars` returns 200 with `rows: []`. Cause is unverified; either the cron line is not installed on the VM or runs never logged. Migration 163 is present. One-off backfill: `run_service.sh sebi_circulars --source listing` |
| `nidp.stock_features_daily` | technical indicators plus fundamentals columns (`pe_ttm`, `roce_pct`, `fundamentals_source`) | `technical_indicator_engine` then `fundamental_engine`; ratios from `trendlyne_fundamentals` | 22:35 and 23:05 Mon-Fri | 2026-10-19, 2,480 rows; 2,138 with `fundamentals_source = trendlyne_mcp`, 342 without | Stocks without a source have null fundamentals. The scan-universe route reads this table |
| `nidp.stock_fundamental_values` | Trendlyne ratios (ROE, ROCE, D/E, P/B, market cap) | `trendlyne_fundamentals daily` | 06:10 daily (in the cron file) | 2026-10-16 | `job_log` has no `trendlyne_fundamentals` row ever, so the cron line is probably not installed (unverified). Trendlyne subscription errors: no code or log evidence found, so unverified |
| `nidp.security_reference_daily` | F&O master, price band, ETF flags | `nse_reference_snapshot` | 07:30 Mon-Fri | 2026-10-20 | Drives `fno_eligible` |
| `nidp.nse_holidays` | NSE holiday calendar | `nse_calendar` | 06:00 on the 1st of the month | 239 rows | The market-status pill falls back to the IST clock if the calendar cannot be read (`overview-data.ts`) |
| `nidp.delivery_data` | delivery percentages | `delivery` | 10:30 Tue-Sat | 2026-10-19 | None for the desk found |
| `nidp.rbi_yields` | RBI yields | `rbi_yields` | 20:30 Mon-Fri | 2026-10-09 (8 rows) | Stale since 2026-10-09 |
| `nidp.fred_macro` | FRED series | `fred_macro` (HELD, needs `FRED_API_KEY`) | not scheduled | empty (0 rows) | No FRED data |
| `nidp.international_etf_price` | international ETF prices | `intl_etf_prices` | not in the staging cron | empty (0 rows) | No international ETF data |
| `nidp.corporate_actions` | splits, bonuses, dividends | `corporate_actions` | 20:00 daily | last ingest 2026-10-20 00:44 (2,234 rows) | See section 3 for rolling versus backfill |
| `nidp.tpd_runs` and `tpd_*` | move-odds model runs | model on the research VM; not on cron here | not scheduled on the warehouse VM | `tpd_runs` is empty (0 rows) | `/api/move-odds/*` and the model rank return nothing useful until a run is published (memory note says empty by design; unverified here) |
| App DB (Postgres) `stock_ohlcv`, `stock_technical_features`, `positional_signals` | scanner state | positional engine | no cron file for staging in the repo (see section 3) | not queried (no read path from here); unverified | If empty, `/api/positional/watchlist` answers `buckets: {}` with `_reason`, `/picks` answers `no signals available yet` and the scanner shows only what DaaS gives |
| App DB `macro_*` tables | macro regime | `macro_engine` in `mf_scheduler` | 18:35 daily (in the app backend) | not queried; unverified | `/api/macro/today` returns an "uninitialised" payload with `_reason` rather than failing |
| MongoDB | holdings, broker accounts, paper trades, alerts, previews | the app | on use | n/a | Not applicable |
| AIF and PMS | not in the code | none | none | none | I found no AIF or PMS source or field in the desk code; absent |

Known gaps recorded in code: no 15-minute OI; F&O ban list and ASM/GSM lists not ingested; no intraday bars (`ChartTab.tsx` header); BSE announcements blocked; FRED and international ETF tables empty; the move-odds model "does not mark estimates as calibrated", so no probability is shown (`desk-data.ts`).

## 3. Jobs and engines

### 3.1 Daily order of dependence (warehouse VM, Mon-Fri, IST)

| Time | Job | Depends on |
|---|---|---|
| 06:10 | `trendlyne_fundamentals daily` | Trendlyne MCP, daily call budget |
| 07:30 | `nse_reference_snapshot` | NSE |
| 19:00 | `bhavcopy`, `index_close` | NSE close |
| 19:30 | `fii_dii`, `bulk_deals`, `block_deals`, `fno_bhavcopy` (first try) | NSE; F&O file often not yet posted |
| 20:00 | `corporate_actions`; positional engine (app VM prod only) | bhavcopy |
| 20:30 | `rbi_yields`, `nse_financials` | |
| 21:00 | `fno_bhavcopy` (retry 2) | |
| 22:15 | `fno_bhavcopy` (retry 3) | file present by about 22:20 per the cron comment |
| 22:30 | `price_adjuster` | bhavcopy plus corporate actions |
| 22:35 | `technical_indicator_engine` | `prices_eod` (default date rule below) |
| 23:05 | `fundamental_engine` | `stock_features_daily` filled by the indicator engine |
| 20:45 (app VM) | `check_desk_alerts` | the 19:00 bhavcopy in `prices_eod` |
| 20:15 (app VM) | `refresh_research_watchlist_prices` | |

Observation: the job log shows `price_adjuster` started 2026-10-20 00:45, `technical_indicator_engine` 2026-10-19 23:37 and `fundamental_engine` 23:05 and 00:29. Those start times differ from the cron times above for the first two, so those runs may have been manual re-runs. The cause is unverified.

### 3.2 Engines

| Engine | What it does | Default rule | By hand |
|---|---|---|---|
| Positional engine (`backend/scripts/run_positional_engine.py`) | bhavcopy into app-DB `stock_ohlcv`, Chartink scans, scores and ranks into `stock_technical_features` and `positional_signals` | `--date` defaults to today (UTC) | `docker exec nivesh-backend python -m scripts.run_positional_engine` (add `--date YYYY-MM-DD`, `--skip-bhavcopy`, `--skip-scans`). Prod cron `deploy/nivesh-app/positional-engine.cron`: 06:00 Mon-Sat (`--skip-bhavcopy`) and 20:00 Mon-Fri. Staging has no such cron file in the repo |
| Technical indicator engine (`nidp.services.technical_indicator_engine`) | indicators into `nidp.stock_features_daily` | latest `as_of_date` in `prices_eod` where `series = 'EQ'`; falls back to yesterday; never after today | `python -m nidp.services.technical_indicator_engine [--date D] [--backfill-days N] [--from D --to D] [--symbols A,B]` |
| Fundamental engine (`nidp.services.fundamental_engine`) | fills fundamentals in rows the indicator engine loaded; copies Trendlyne ratio pass r1 | latest `as_of_date` in `stock_features_daily` (fixed after Monday 2026-10-19 targeted a Sunday) | `python -m nidp.services.fundamental_engine [--date D] [--symbols A,B] [--skip-populate]` |
| Price adjuster (`nidp.services.price_adjuster`) | split/bonus adjusted bars | last 30 days (`DEFAULT_SINCE_DAYS`) | `python -m nidp.services.price_adjuster [--since YYYY-MM-DD] [--symbols X,Y] [--no-dividends]`; `--since 1900-01-01` is a full rebuild (one-shot) |
| Corporate actions (`nidp.services.corporate_actions`) | NSE actions per board (main, SME, ETF/MF boards best-effort) | rolling feed lists upcoming ex-dates only | rolling: `python -m nidp.services.corporate_actions`. Backfill: `--backfill-from YYYY-MM-DD [--backfill-to YYYY-MM-DD]` (date-range endpoint, fails loudly on any fetch error, upsert on symbol, type, ex-date, source) |
| Index constituents (`nidp.services.index_constituents`) | lists in `INDEX_CONSTITUENT_URLS` (`nidp/shared/config.py`), one transaction per index | today | `python -m nidp.services.index_constituents [--date YYYY-MM-DD]` |
| Desk alerts checker (`backend/scripts/check_desk_alerts.py`) | applies the stop/target rule to all users' open paper trades and fires active alerts; in-app only | each run checks from each item's first session on | `docker exec nivesh-staging-app-backend python -m scripts.check_desk_alerts [--dry-run]`; cron `deploy/nivesh-staging/desk-alerts.cron` (20:45 Mon-Fri, installed by `install-desk-alerts.sh`, not CI-managed) |
| Trendlyne fundamentals | ratios and quarterly passes | daily call budget `TRENDLYNE_DAILY_CALL_BUDGET`; r1 refreshed every `TRENDLYNE_RATIOS_REFRESH_DAYS` (7) | subcommands `fetch --pass P`, `sectors`, `build`, `ratios`, `daily` |
| SEBI circulars | RSS or listing pages | RSS | `run_service.sh sebi_circulars [--source listing] [--date D]` |

Warehouse-VM manual form (from the cron header and the BSE note): `sudo -u nidp-staging /opt/nidp-staging/run_service.sh <service> [args]`. The same wrapper takes args, for example `nse_financials.backfill_screener --concurrency 1 --delay-ms 3000` (HELD).

Held in the staging cron file: `fred_macro` (needs `FRED_API_KEY`), `corporate_announcements_bse` (needs `BSE_PROXY_URL`), `announcement_classifier` (replaced by the Claude Code filing pipeline on the app VM), the Screener.in backfill (connections refused since 2026-10-12), and three portfolio sync jobs (the app pushes to the Query API instead).

## 4. Environments and settings

Names only. No values are recorded here.

| Name | Used by | Where set |
|---|---|---|
| `NIDP_DAAS_BASE_URL` | app backend `daas_client._creds()` | staging: `deploy/nivesh-staging/docker-compose.staging.yml` (line 116, points at the staging data host's `/daas`) |
| `NIDP_DAAS_INTERNAL_TOKEN` (alias `NIDP_DAAS_API_KEY`) | app backend, sent as `X-API-Key` | compose passes `${NIDP_DAAS_INTERNAL_TOKEN:-}` from the staging env file; `deploy/cloudpe/check-env.sh` lists it as RECOMMENDED |
| `NIDP_DAAS_INTERNAL_URL`, `NIDP_DAAS_HOST` | optional internal route for strategy bulk reads (`strategy_creds`) | app env; not set in the files I read (unverified) |
| `NIDP_POSTGRES_URL` | NIDP engines and DaaS | `/opt/nidp-staging/nidp.env`, loaded by `run_service.sh` |
| `NSE_HTTPS_PROXY` | NIDP NSE fetches (NSE hosts only) | `nidp.env`; `check-env.sh` lists it; `deploy/cloudpe/README.md` line 96 says it points at a proxy inside the GCP VPC |
| `BSE_PROXY_URL` | NIDP BSE fetches (bseindia.com only; credentials redacted from logs) | one line in `/opt/nidp-staging/nidp.env`; deliberately not in `check-env.sh`; procedure in `docs/DEVOPS_ENVIRONMENTS.md` |
| `FRED_API_KEY` | `fred_macro` (held) | `nidp.env` |
| `TRENDLYNE_MCP_URL`, `TRENDLYNE_DAILY_CALL_BUDGET`, `TRENDLYNE_RATIOS_REFRESH_DAYS` | Trendlyne client | `nidp.env` (URL carries a token; never logged) |
| `NIDP_MAX_ATTEMPTS`, `NIDP_RETRY_BACKOFF_S` | `run_service.sh` retry policy | per cron line or environment |
| `MONGO_URL`, `DB_NAME` | app backend (paper trades, alerts, holdings) | app env |
| Feature flags (not env vars; stored in the app DB, managed by admin) | `charting` (allowlist only), `move_odds` (allowlist only), `sim_lab` (allowlist only), `broker_hub` (default everyone), plus `ai_copilot`, `chat_streaming` and others | `backend/feature_flags.py` `KNOWN_FEATURES`; re-read every 30 s by `feature_gate.py` |

## 5. Security and read-only guarantees

- **No order path.** Broker access goes through adapters in `backend/services/brokers/`. `hub_reads.py` states "Strictly read-only: nothing here places, modifies or cancels an order"; `fenix_reader.py` states it does not wrap any Fenix order method; `base.py` defines "Read-only holdings fetch". `zerodha.py` states the code never calls `place_order`, `modify_order` or `cancel_order`. A repo grep for `place_order` outside tests finds only that docstring in `zerodha.py`. The routes in `routes/broker_connect.py` expose accounts, holdings, positions, funds, sync (stores holdings only), snapshots and disconnect: no order route. Tests exist: `test_broker_fenix_reader.py`, `test_broker_funds_read.py`, `test_broker_hub_reads.py` (I did not run them).
- **Desk writes are paper only.** `desk_trading.py` and `desk_alerts.py` docstrings: "Nothing here places an order", "No orders, no brokers", in-app notification only.
- **Secrets.** Per-user OpenAlgo keys are AES-256-GCM encrypted (`services.pii_security`) before storage; raw broker passwords, TOTP seeds and PINs are never stored (`broker_connect.py` header). DaaS credentials are read through `helpers.secrets` with an environment fallback. The Trendlyne URL and `BSE_PROXY_URL` are kept out of logs (`trendlyne_fundamentals/client.py`, `nse_fetcher.py` redaction). Env values are not in the repo.
- **SEBI rule on individuals' PAN.** `nidp/services/sebi_circulars/parser.py` keeps only links under `/legal/circulars/` and `/legal/master-circulars/`, drops any item whose title matches a PAN pattern (`[A-Z]{5}[0-9]{4}[A-Z]`), and hands on only a redacted copy of the feed to the raw archive (channel header plus circular items). Enforcement orders and recovery notices therefore never reach `nidp.sebi_circulars` (migration `163_sebi_circulars.sql`; `routes/circulars.py` docstring).
- **Per-user ownership.** Paper trade and alert reads and writes filter on `user_id` from `get_current_user`; a trade or alert that is not yours returns 404, same as a missing one (`desk_trading.py`; the delete handler filters on `{"_id": id, "user_id": uid}`). Upload previews are looked up with `{"_id": id, "user_id": uid}`. IDs longer than a fixed maximum are refused. Limits: 100 open paper trades and 50 active alerts per user, quantity at most 1,000,000, price at most 10,000,000 (`services/desk_trading.py`).
- **Upload limits** (`routes/upload.py`): 5 MB, 5,000 rows, extensions .csv/.xlsx/.xls only, magic bytes checked, malware scan, no macros or ActiveX in workbooks, at most 2,000 zip members and 50 MB expanded, formulas never evaluated, formula-leading text neutralised and flagged; previews expire after 30 minutes; commit accepts only `rows` and only non-rejected rows.
- **Data-platform access.** The browser never talks to DaaS. The app holds the key and routes check the session or flag first. DaaS routers use `require_api_key`; move-odds routers also use `require_internal_plan`.
- **CSRF.** Writes pass `middleware.py` origin checks.

## 6. Known limitations and open items (as of the snapshot)

| Item | Evidence |
|---|---|
| BSE announcements blocked | `job_log`: every recent `corporate_announcements_bse` run FAILED with HTTP 403 Access Denied; last BSE filing 2026-10-13; cron line HELD in `nidp-staging.cron` |
| SEBI circulars empty on staging | `nidp.sebi_circulars` has 0 rows; no `sebi_circulars` entry in `nidp.job_log`; the Intel tab's circular list is empty |
| Move-odds not populated | `nidp.tpd_runs` has 0 rows; `desk-data.ts` withholds probabilities because the route sends no calibration flag |
| FRED and international ETF tables empty | 0 rows each; `fred_macro` HELD in the cron file; no `intl_etf_prices` line in it |
| No intraday or 15-minute OI | `desk_market.py` docstring (`intraday` unavailable); `FnoBuildup.tsx` |
| F&O ban list and ASM/GSM not ingested | `ChartTab.tsx` header comment |
| Positional scanner needs the app-VM engine | `deploy/nivesh-app/positional-engine.cron` is prod only; no staging equivalent in `deploy/nivesh-staging/`. State of the app-DB scanner tables not checked (unverified) |
| Trendlyne fundamentals coverage | 342 of 2,480 rows on 2026-10-19 have no `fundamentals_source`; no `trendlyne_fundamentals` rows in `job_log` (cron not confirmed installed). Subscription errors: no evidence found, unverified |
| Chart data is flag-gated | `charting` allowlist only; 403 `feature_not_enabled` otherwise (`ChartTab.tsx` states this) |
| Stale or thin feeds | `rbi_yields` last 2026-10-09; `fii_dii_flows` 14 rows; `block_deals` 2 rows, last 2026-10-12 |
| Job times differ from the cron file | `price_adjuster` and `technical_indicator_engine` start times in `job_log` differ from 22:30 and 22:35; cause unverified |
| F&O file arrives late | 19:30 run FAILED, 22:21 run OK on 2026-10-19; the cron comment records 404 at 19:30 on 16 and 19 Oct |
| Desk alerts cron is manual to install | `desk-alerts.cron` says "one-off, not CI-managed"; whether installed on the staging VM is unverified |
| Broker data not stored | live broker reads (holdings, positions, funds) are not persisted; the Portfolio card must show live versus stored (`desk/broker.ts`) |
| AIF and PMS | no source found in the desk code |
| Midcap and Smallcap lists | present on staging as of 2026-10-20 (Midcap 150 and Smallcap 250 have rows); the market-cap split depends on them being refreshed monthly |
| Technical details I could not confirm | auth of `/api/research/chart-layouts` use by the desk; whether `NIDP_DAAS_INTERNAL_URL` is set on staging |

---

# Consolidated open points

Collected from the four parts while writing; each was observed in the code reading and not re-tested live.

**Consistency**
1. The move-odds probability is withheld on the Scanner but printed on the Overview's Top opportunities card (for accounts with a published run), on the Chart tab and in the Risk desk. The PRD §5.8 rule (show a probability only when calibrated) is applied in one place only.
2. Patterns are computed on the untrimmed bars, while indicators cut the history at an unadjusted split. A split stock can therefore show a pattern from before the split.
3. The Risk desk's paper-trade and alert buttons need a scanner setup; the desk chart draws only scanner levels, not the rule-based `ATR_2X_STOP` levels shown in the opportunity detail.
4. The risk rows' footer says "direct stocks", but overall risk, beta and value at risk also include funds.
5. Paper strategies show "No trade suggested" for NIFTY and BANKNIFTY although the stats tile and index cards show an index build-up.

**Behaviour to review**
6. A one-word question in the header search is treated as a stock symbol and opens the Chart tab; a question sent while an answer is streaming is dropped.
7. Paper trades can only be closed or cancelled, never deleted (alerts can be deleted). The desk screens always create "at once" long share trades, although the API also accepts conditional entries.
8. The Support/resistance tile's tooltip is empty (a key mismatch).

**Not shown, though data exists**
9. The backend sends per-stock risk flags the scanner table does not render.
10. The phone Overview omits the headline, the breadth tile, the sector card and the leadership and events blocks.

**Data limits (see Part 4)**
11. BSE announcements are blocked at BSE's edge for the staging server (403); no BSE-only filings since 13 Oct. A rotating-proxy setting (`BSE_PROXY_URL`) exists in code and is off.
12. The scanner, move-odds runs (`tpd_runs`), SEBI circulars, FRED and the international ETF table were empty on staging when this was written; no intraday data and no 15-minute open interest exist; no AIF/PMS source exists.
13. Demergers, rights issues and stocks that moved between NSE series are not price-adjusted.
