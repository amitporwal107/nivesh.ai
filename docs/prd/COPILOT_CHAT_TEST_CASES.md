# AI Copilot Chatbot — Functional Test Cases (validated against live data)

**Source:** `docs/prd/COPILOT_CHATBOT.prd.md` (FR-CHAT-001…015, AC-01…21)
**Target:** staging — https://staging.niveshcopilot.com (V5 `/v5/chat`, API `/api/chat/send`)
**Validation account:** **aporwal107@gmail.com** (`user_ed05fb1daa45`, Amit Porwal, admin)
**Live snapshot captured:** 2026-06-08 from staging (pulled via `scripts/dump-portfolio-staging.mjs`).
**Method:** run each case on live staging → assert the reply against the ground-truth numbers below → watch the Grafana log signal → on fail, capture the log, fix, redeploy to `nivesh-app-vm`, re-run.

### Monitoring (Grafana / GCP logs)
- Dashboard: https://data.niveshcopilot.com/grafana/d/app-logs-central (admin/admin)
- App logs are in **`jsonPayload.msg` + `jsonPayload.logger`** (project `niveshdataintelligence`), NOT `jsonPayload.log`.
- Filters: route taken `jsonPayload.logger=~"copilot_agent.nodes"` · tool fail `jsonPayload.msg=~"fetch failed|no attribute|no_data|timed out"` · handler error `jsonPayload.logger="routes.chat" AND severity>=ERROR` · DaaS `jsonPayload.logger=~"copilot_tools.daas_client"`. Each turn has a `correlationId` — filter the whole turn by it.

### Result vocabulary
**PASS** = reply matches the ground-truth value (within stated tolerance). **FAIL(app)** = our code/data. **FAIL(NIDP)** = DaaS/feed side. **BLOCKED** = not built in V5. **DISCREPANCY** = copilot value ≠ canonical dashboard/DB value (a grounding failure even if it "answers").

---

## Ground truth — aporwal107@gmail.com (assert against these)

**Portfolio totals**
| Field | Value |
|---|---|
| Holdings count | **111** (50 unique stocks + 35 MF investments + ETFs) |
| Total value | **₹1,04,74,171** (₹10,474,171.43) |
| Enrichment coverage | 82.9% · look-through 29.9% |

**Asset allocation** (from `/intelligence/portfolio`)
| Class | % | ₹ |
|---|---|---|
| Equity | **93.6%** | ₹98,07,882 |
| Gold | **6.3%** | ₹6,59,745 |
| Debt | **0.1%** | ₹6,545 |

**Concentration** (`/portfolio/exposure/concentration`)
- AMC: **HDFC 39.04%** (₹33.99L, 11 funds) · Mirae 12.03% · SBI 9.67% · ICICI Pru 7.8%
- Compression score 27.0 · effective stocks **21.6 of 50** · top-10 26.51% · top-20 35.08%

**Fund overlap** (`/intelligence/portfolio` — 25 pairs)
- Highest pair: **Nippon India Small Cap Growth ↔ Nippon India Small Cap Direct Growth = 97.38%**
- Next: 87.24%, 79.79%, 68.66%, 64.57%, 60.97%
- Redundancy #1: **remove "UTI Nifty 50 Index Fund" (₹1,02,232)** → cuts portfolio overlap from 21.97%

**Risk** (`/dashboards/risk`)
- VaR 95% · 1Y = **−33.1%** (~₹35.1L) · Volatility **19.4%** (bench 10.6%) · Max Drawdown **22.5%** · Beta **1.15** vs NIFTY 500

**Performance** (`/dashboards/performance`)
- XIRR **−7.8%** (badge "Fair"; Nifty 500 −4.3%; Alpha −3.5pp; Hit rate 58%)
- ⚠️ copilot `portfolio_analyst` returned **+3.7% XIRR** — **DISCREPANCY** to reconcile (likely 1Y vs since-inception).

**Tax** (`/dashboards/tax`)
- Harvestable loss **₹1,13,000** · net saved **₹22,693** · **8 harvest lots** · LTCG exempt left ₹1.25L · est. tax if exit ₹4.36L (STCG ₹21.8L @20%)
- Top lots: quant Small Cap −₹19,976 · JIO Financial −₹12,436 · NTPC Green −₹9,940 · Parag Parikh Flexicap −₹7,397 · HDFC Balanced Advantage Direct −₹6,171
- ⚠️ copilot `tax` returned **14 lots / ₹9,042** — **DISCREPANCY** to reconcile.

**Goals** (`/api/goals`)
- One goal: **"Kids Education"** — target **₹20,00,000**, horizon **8 yrs**, SIP **₹5,000/mo**, exp. return 10.05%, current corpus ₹0, alloc equity60/debt30/hybrid10.

**Notable holdings to reference in queries:** Nippon India Small Cap, Parag Parikh Flexicap, Axis Midcap, Kotak Flexicap, HDFC Balanced Advantage (Reg+Direct), Mirae Large Cap, SBI Large & Midcap, Tata Small Cap, Tata Digital India, ICICI Gold ETF; stocks: RELIANCE, HDFC BANK, ICICI BANK, INFOSYS, BHARTI AIRTEL, TATA STEEL, JIO FINANCIAL, NTPC GREEN, WHIRLPOOL.

---

## B. Agent routing — validated against live data

**TC-10 — portfolio_analyst (XIRR + allocation)**
- Send: "What is my portfolio XIRR and asset allocation?"
- Expected (assert): total value ≈ **₹1.05 Cr**, **111 holdings**, equity **~93–94%**, gold **~6%**. XIRR figure present.
- DISCREPANCY check: copilot XIRR vs dashboard **−7.8%** — flag if copilot says +3.7% (sign mismatch = grounding bug).
- Log: `nodes.portfolio`, no `fetch failed`.

**TC-11 — risk_analyst (VaR/vol/beta)**
- Send: "How risky is my portfolio right now?"
- Expected: should surface **VaR ≈ −33%**, **volatility ≈ 19.4%**, **beta ≈ 1.15**, **max drawdown ≈ 22.5%**.
- Current known gap: copilot says it "cannot quantify volatility/VaR/beta" and falls back to overlap only → **FAIL(NIDP)** (risk tool not wired to the precomputed PRA the dashboard uses). Assert it returns the real VaR/vol/beta, not just overlap.

**TC-12 — tax (harvest)**
- Send: "What are my tax-loss harvesting options this year?"
- Expected: harvestable loss **≈ ₹1.13L**, **8 lots**, top lot **quant Small Cap ≈ −₹19,976**, net saving **≈ ₹22,693**.
- DISCREPANCY check: copilot returned **14 lots / ₹9,042** — reconcile against dashboard 8 lots / ₹22,693.

**TC-13 — mf_analyst ("too many funds") [regression]**
- Send: "Do I have too many mutual funds?"
- Expected: over-diversification verdict citing **35 MF holdings**, **25 overlap pairs**, and the **97% Nippon Small Cap pair**. Must NOT say "couldn't retrieve data".
- Log: `nodes.mf`; must NOT show `has no attribute 'get_portfolio_overlap'`. **(Now PASSing as of 50e35ae.)**

**TC-14 — stock_analyst (a held stock)**
- Send: "Give me a technical and fundamental view on RELIANCE"
- Expected: technical signal + fundamentals for RELIANCE. RSI/MACD may be "data unavailable" → partial; flag as FAIL(NIDP) if all technicals missing.

**TC-15 — goal_planner (the real goal)**
- Send: "Am I on track for my kids education goal?" (the user's real goal: ₹20L, 8 yrs, ₹5k/mo SIP)
- Expected: references the **Kids Education** goal, target **₹20L**, horizon **8 yrs**, and assesses the ₹5,000 SIP vs requirement (current corpus ₹0 → likely "behind").
- Also: "How much SIP to reach ₹20L in 8 years?" → must return a **number** (not "couldn't retrieve").

**TC-16 — recommendation (redundancy)**
- Send: "What should I sell to reduce overlap?"
- Expected: should suggest **removing UTI Nifty 50 Index Fund (₹1.02L)** or similar redundancy from the live `redundancy_suggestions`.

**TC-17 — market_analyst**
- Send: "How is the Indian market doing today?"
- Expected: today's indices/movers/FII-DII.
- Known: **FAIL(NIDP)** — DaaS `/v1/indices/summary` & `/v1/macro/latest` return **404** on staging. Log: `daas_client` 404.

**TC-18 — concentration**
- Send: "Which AMC am I most concentrated in?"
- Expected: **HDFC ≈ 39%** (11 funds), then Mirae ~12%, SBI ~10%.

**TC-19 — overlap follow-up**
- Send: "Which of my funds overlap the most?"
- Expected: **Nippon India Small Cap Growth ↔ Direct = 97%**. **(PASSing.)**

---

## C. Grounding & cross-source reconciliation (the project standard)

**TC-20 — XIRR reconciliation**
- The copilot's XIRR must match the canonical dashboard XIRR (**−7.8%**) in sign and ~magnitude, or explicitly state the horizon difference. Sign flip (+3.7 vs −7.8) = **DISCREPANCY / FAIL**.

**TC-21 — Tax reconciliation**
- Copilot harvest total must match dashboard (**₹22,693 / 8 lots**) within tolerance. Current mismatch (₹9,042 / 14 lots) = **DISCREPANCY / FAIL**.

**TC-22 — Total value reconciliation**
- Copilot "current value" must equal `/intelligence/portfolio` total **₹1,04,74,171** within rounding. (copilot showed ₹1,05,84,791 — ~1% off; investigate.)

**TC-23 — No fabrication on missing data**
- Ask for a metric NIDP lacks → reply must say "data unavailable", never invent (no placeholder funds, no round 15%).

---

## A. Core chat flow

**TC-01 — Round trip** — send TC-10's query → one grounded reply, no error. Log: `routes.chat` no ERROR.
**TC-02 — SSE sequence** (AC-01) — `route→token→widget→done`. **BLOCKED**: V5 uses `/chat/send`; `/chat/stream` throws `RuntimeError: No response returned.` (correlation middleware + StreamingResponse).
**TC-03 — Multi-turn memory** (AC-04) — ask "How risky is my portfolio?" then "How do I reduce it?" → 2nd reply references the first; same `session_id`.
**TC-04 — Follow-up chips** (AC-02) — 1–3 chips; click auto-submits. Verify in V5.
**TC-05 — Empty-state** — new session shows name "Amit", value ₹1.05Cr, 6 persona prompts.

---

## D. Persona (FR-CHAT-005)
**TC-30 — beginner: no jargon** (AC-06) — as `beginner_investor` ask "What is beta?" → plain language (note: real beta is 1.15; should explain, not just quote).
**TC-31 — active_trader: depth** (AC-07) — RSI/MACD-level detail from the technical tool.

## E. Suggested prompts (FR-CHAT-006)
**TC-40 — persona+category** (AC-08) — `?persona=sip_investor&category=goal_planning` → ≥3 matching prompts.
**TC-41 — flag off** (AC-09) — `copilot_persona_prompts_enabled=disabled` → exactly 10 universal templates.
**TC-42 — category chips** — 5 chips re-filter the list.

## F. Widgets (FR-CHAT-008)
**TC-50 — render below prose** — overlap_reveal should show the 97% Nippon pair; tax_harvest the 8 lots; portfolio_overview the health grade. **BLOCKED**: V5 has no widget components (V2 has all 10).
**TC-51 — none → nothing** (AC-11). **TC-52 — tax_harvest binding** (AC-10): lot[0].loss matches rendered row (quant Small Cap −₹19,976).

## G. Compliance (FR-CHAT-009)
**TC-60 — SEBI once, footer** (AC-12) — bubble text must not contain "SEBI".
**TC-61 — PII scrub** (AC-13) — send a PAN → not present in outbound LLM prompt. **Likely FAIL(app)**: scrub not found in code.
**TC-62 — grounding_ok=false → amber warning** (AC-05) — relevant given the XIRR/tax discrepancies above should trip grounding.

## H. History & sessions (FR-CHAT-010)
**TC-70 — new session + title** (AC-14). **TC-71 — rename** — `PATCH /api/chat/sessions/{id}` → **FAIL(app)**: endpoint not implemented. **TC-72 — delete** (AC-15). **TC-73 — grouped sidebar** — **BLOCKED** in V5.

## I. Portfolio context header (FR-CHAT-011)
**TC-80 — "NIDP CONNECTED · N holdings" (=111) + re-sync** — **BLOCKED** (not built). **TC-81 — disconnected → cached `[cached]` tag**.

## J. Advisor mode (FR-CHAT-013)
**TC-90 — cross-client** (AC-20) — as `mfd` ask "which client needs rebalancing most?" → Markdown table from client book, not single-user. (Note: aporwal107 is admin → may already route to advisor path; verify single-user questions still work for admins.)

## K. Feedback (FR-CHAT-014)
**TC-100 — thumbs up/down** → `POST /api/copilot/feedback` 200, row in `copilot_feedback`.

## L. Input UX (FR-CHAT-015)
**TC-110 — 500-char limit** (AC-19) — FE blocks >500; backend 400. **TC-111 — submit disabled while replying** (AC-18). **TC-112 — char counter >400**.

## M. Errors & edge
**TC-120 — no portfolio** (AC-16) — a fresh user → "connect your portfolio" prompt. **TC-121 — NIDP bridge down** (AC-17) — DaaS timeout → "using cached", `grounding_ok=false`. (Today some DaaS endpoints time out 10–15s; observe graceful degradation vs the generic "couldn't retrieve".)

## N. Mobile (NFR-07)
**TC-130 — 390px** (AC-21) — input pinned, thread scrolls, chips ≥44px.

## O. NFR spot checks
**TC-140 first-token <3s** · **TC-141 full <15s** (observed 5–16s — borderline) · **TC-142 OpenAI key never logged, resolves via GSM** (done).

---

## Baseline from 2026-06-08 sweep (8/9 API PASS, UI PASS)
- **PASS:** TC-10, TC-12, TC-13, TC-14, TC-15, TC-16, TC-19, TC-01, UI render.
- **FAIL(NIDP):** TC-17 market (DaaS 404), TC-11 risk (VaR/vol/beta not wired — falls back to overlap), scheme-MF scoring timeout (migration 050).
- **DISCREPANCY (grounding):** TC-20 XIRR (+3.7 vs −7.8), TC-21 tax (₹9,042 vs ₹22,693), TC-22 total value (~1% off).
- **BLOCKED (V5 not built):** TC-02 streaming, TC-50 widgets, TC-73 history sidebar, TC-80 header.
- **FAIL(app):** TC-71 rename endpoint, TC-61 PII scrub.
