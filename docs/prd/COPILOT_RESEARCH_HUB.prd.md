# Copilot Research Hub — Stock & MF research chips

Status: PLAN (awaiting build approval) · Owner: full-stack + design · Branch (proposed): `feat/copilot-research-hub` off `dev`
Date: 2026-06-21

## 1. Problem & intent

Users research a stock or fund by asking questions ("is it worth buying?", "how risky?"),
not in our data taxonomy (V3 scores, Piotroski, scorecards). Today the Copilot already
answers most of these, but the answers are scattered across stock expandable-sections and
MF tabs with two different mental models.

Goal: one **question-first research surface** — 10 chips ("lenses"), each mapping the *same
human question* to the right stock-vs-MF data — attached as a **fixed rail** to every
instrument card. Same 10 questions for INFY or an HDFC fund; two data paths underneath.

## 2. The 10-lens contract (single source of truth)

| id | Primary / Alt | Stock data → tool | MF data → tool |
|----|---------------|-------------------|----------------|
| `buy_verdict` | Worth buying now? / Should I buy? | V3 quality + verdict (`stock_intelligence`, `recommendation.composite_score`) | composite score + quality label (`mf_intelligence`) |
| `performance` | How's it performed? / Track record | momentum + vs-Nifty (`technical`, `stock_intelligence` intel features) | 1Y/3Y/5Y CAGR vs category (`mf.get_mf_performance`) |
| `valuation` | Cheap or pricey? / Fair value? | P/E vs sector median (`fundamental`) | quartile/rank vs category, reframed as value (`mf_intelligence`) |
| `risk` | How risky is it? / Risk check | vol/beta/Sharpe (`technical` + intel features) | Sharpe, max-DD, risk-o-meter (`mf_intelligence`) |
| `peers` | Compare to peers / Beats peers? | sector peers (peers panel data) | category peers table (`mf` peers) |
| `drivers` | What drives it? / Under the hood | shareholding + sector exposure (`company_financials`) — partial | holdings & sectors (`mf_intelligence` top_holdings/top_sectors) |
| `red_flags` | Any red flags? / What's the catch? | pledge & shareholding shifts (`company_financials`) | lifecycle events (`mf_intelligence.events`) |
| `costs` | What it costs / Fees & payouts | dividend yield — **GAP** | TER (✅) + exit load (gap) (`mf_intelligence`) |
| `people` | Who runs it? / The people behind it | promoter % flows, no bios (`company_financials`) | fund manager (`mf_intelligence.current_manager`) |
| `whats_new` | What's new? / Latest updates | announcements + quarterly results (`stock_intelligence`, `company_financials`) | — **GAP** (no MF news feed) |

**Coverage at ship (Phase 1):** stock = 9 lenses (no `costs`); MF = 9 lenses (no `whats_new`).
Decision: **chips with no data source are hidden** (not shown disabled). A lens renders only
when its availability predicate sees real data for that instrument.

## 3. Design principles

1. **Lens = deterministic, not LLM-routed.** Tapping a chip resolves to a known tool/section,
   never re-runs intent classification. No routing roulette.
2. **Preload, then switch in-card (zero round-trip).** Extend the existing "all tabs in one
   card" MF model to all available lenses, and bring the same model to stocks (which today use
   expandable sections). Each chip tap switches a preloaded in-card section instantly. One
   tool fan-out per card (nodes already `asyncio.gather`).
3. **Hide gaps, never fake.** Matches house style (stock node already states plainly when a
   feed is absent). No `data_state:"unavailable"` UI states — the chip simply isn't there.
4. **Narrative still streams below the card.** Enrich each `ToolResult.summary` so the LLM
   prose stays grounded (the `as_llm_context()` gotcha — only `.summary` reaches the LLM).

## 4. Architecture

### 4.1 Backend — shared lens contract (new)
`backend/services/copilot_tools/research_lenses.py`
- `LENSES`: ordered list of `Lens(id, primary, alt, section_key, stock_builder, mf_builder)`.
- `build_research_rail(kind, fetched) -> {sections: {id: payload}, rail: [{id, label, alt}]}`:
  runs each lens builder over already-fetched tool data; includes a lens in `rail` only when
  its builder returns a non-empty, real payload (availability predicate). Returns sections
  keyed by lens id for in-card preload.
- Builders **compose existing tools' outputs** — no new data calls beyond what the node already
  fetches; no parallel calculators (reuse `copilot_tools/*`).

### 4.2 Backend — node wiring (edit)
`copilot_agent/nodes/stock.py` and `nodes/mf.py`:
- After the existing tool fan-out + widget build, call `build_research_rail(...)` and attach
  `widget_data["research_rail"]` and `widget_data["sections"]` to the emitted widget.
- Keep current `widget_type` (`instrument_detail` / `mf_detail`) for back-compat.

### 4.3 Frontend — unify onto one ResearchHub card (edit)
`frontend-v5/src/components/chat/ChatWidget.tsx`:
- Generalize `MfCard`'s `tabs + views + active` model into a shared `ResearchHubCard`
  (header + chip rail + active section body). Both stock (`instrument_detail`) and MF
  (`mf_detail`) render through it; `kind` selects header (price vs NAV) and section renderers.
- **Chip rail** = `data.research_rail`; render primary label, alt as `title`/aria-label,
  active state on selected lens; tap → local `setActive(id)` (no network).
- **Section registry** maps lens id → renderer, reusing existing panels:
  `buy_verdict`→`RecommendationBlock`+`ScoreDonut`; `performance`→returns bars;
  `valuation`→fundamentals_grid / MF quartile; `risk`→risk tiles; `peers`→`PeersPanel`/MF peers;
  `drivers`→`ShareholdingPanel`+sectors / MF holdings; `red_flags`→`CorporateEventsPanel` /
  MF lifecycle; `costs`→MF TER block; `people`→manager/promoter block;
  `whats_new`→announcements+`QuarterlyPanel`.
- Any lens absent from `research_rail` simply has no chip.

## 5. Phasing

- **Phase 1 (this build):** contract module + node wiring + ResearchHub card + section
  registry over the 9 covered lenses each. Gaps hidden.
- **Phase 2 (cheap fills):** MF exit load (from DaaS scheme metadata), MF `valuation`
  quartile copy, stock `drivers` richer segment proxy from MF cross-holdings.
- **Phase 3 (data sourcing, separate):** stock dividend yield, MF news feed, stock segment
  breakdown — each needs a feed and is out of scope here.

## 6. Definition of Done (Phase 1)

- [ ] `build_research_rail` returns the expected lens set for a **real** stock and a **real**
      MF (queried against live DaaS), with gaps correctly absent — shown as test output.
- [ ] Backend unit test asserts per-lens section payloads are non-empty for covered lenses
      and absent for gap lenses (data test, not just 200).
- [ ] Frontend typecheck clean; Playwright on staging shows the rail rendering and an in-card
      section switch with no network round-trip — screenshot in the report.
- [ ] Narrative below the card stays grounded (summaries enriched); no fabricated values.
- [ ] No unlabeled mock data; gap lenses verified absent, not faked.

## 7. Open questions / risks

- Stock card today uses expandable sections; converting to the rail model is the largest single
  edit — verify no regression to existing stock-card consumers.
- `instrument_detail` is consumed elsewhere? Audit before changing its render path.
- Rail with 9 chips on mobile width — design needs a horizontal scroll / wrap rule.
