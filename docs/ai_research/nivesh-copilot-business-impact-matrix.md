# Nivesh Copilot — Business-Impact Matrix

Purpose: for every corporate event family, map WHICH business dimension it
actually moves, in which direction, over what horizon, and how persistently.
This is the layer between "what was filed" and "why it matters" — it powers
`sentiment_basis` quality, materiality scoring, and the impact chips the UI
can show next to each event ("Revenue ↑ multi-year" beats a bare green badge).

## Impact dimensions

| Dim | Meaning |
|---|---|
| REV | Future revenue trajectory |
| MAR | Margins / profitability quality |
| BS | Balance sheet: leverage, solvency |
| CF | Cash flow / liquidity of the business |
| DIL | Share count / per-share value (dilution or accretion) |
| GOV | Governance, disclosure trust, promoter alignment |
| LIQ | Trading liquidity / tradability of the stock itself |

Horizon: **now** (this quarter) / **1–2Q** / **multi-yr**.
Persistence: **one-off** / **structural** (changes the run-rate).

---

## The matrix

| Event | Primary dim | Secondary | Direction | Horizon | Persistence | Notes for basis text |
|---|---|---|---|---|---|---|
| **Order win** | REV | CF | ↑ | 1–2Q → multi-yr | structural while executing | Spread value over execution period; margin profile usually undisclosed — don't assume |
| Order cancellation / LD | REV | MAR | ↓ | now | one-off + pipeline doubt | Also dents win-rate credibility |
| L1 status | REV (potential) | — | ~ | multi-yr | not yet real | Zero committed revenue; option value only |
| **Acquisition (cash)** | REV | BS ↓ (cash out) | ↑/mixed | multi-yr | structural | Integration risk unstated; check funding line |
| Acquisition (equity-funded) | REV | DIL ↓ | mixed | multi-yr | structural | Per-share accretion is the real question |
| Demerger | GOV/value clarity | — | ↑ | multi-yr | structural | Unlock thesis; costs and stranded overheads offset |
| Distressed slump sale | BS ↑ (debt down) | REV ↓ | ↓ | now | structural | Selling the engine to pay the mortgage |
| Being acquired / open offer | — | LIQ | ↑ (premium) | now | terminal | Exit event for these shareholders |
| **Results beat (organic)** | REV/MAR | — | ↑ | now | read persistence from drivers | Volume-led beats persist; price-led fade |
| Results beat (exceptional gain) | — | — | ~ | now | one-off | Strip it; judge core. Classic trap |
| Margin compression | MAR | CF | ↓ | 1–2Q | check cause | Input costs (cyclical) vs competition (structural) — very different |
| Auditor qualification | GOV | BS (doubted) | ↓↓ | now | structural until resolved | Numbers themselves now uncertain |
| Restatement | GOV | all above | ↓↓ | now | structural | History was wrong; multiply distrust |
| **QIP for growth capex** | DIL ↓ / REV ↑ later | BS ↑ | mixed | multi-yr | structural | Dilution now, revenue later — the honest two-sided case |
| Balance-sheet-repair raise | DIL | BS ↑ | ↓ | now | structural | Dilution without growth; existence money |
| Preferential to promoters at floor | DIL/GOV | — | ↓ | now | structural | Value transfer; optionality one-way |
| Debt prepayment | BS | MAR ↑ (interest) | ↑ | 1–2Q | structural | Interest savings flow to EPS |
| **Debt DEFAULT** | BS/CF | GOV | ↓↓↓ | now | structural | Solvency question; everything else secondary |
| **Dividend raise/special** | CF (signal) | — | ↑ | now | signal, not driver | Management's confidence statement in cash |
| Dividend cut | CF (signal) | — | ↓ | now | signal | Either conserving for capex (say so) or can't afford it |
| Buyback | DIL ↑ (accretion) | CF ↓ | ↑ | now | one-off + signal | EPS accretion mechanical; signal is the larger effect |
| Bonus/split | LIQ | — | ~ | now | cosmetic | No value change; retail sentiment only |
| **CEO/CFO abrupt exit** | GOV | execution risk | ↓ | 1–2Q | until resolved | Continuity question mark on guidance |
| Auditor resignation | GOV | BS (doubted) | ↓↓ | now | structural | The books lost their referee |
| Marquee hire | GOV/execution | — | ↑ | multi-yr | structural | Priced slowly; capability signal |
| Defeated AGM resolution | GOV | — | ↓ | now | signal | Institutions publicly revolting |
| **Adverse legal order** | BS (liability) | CF | ↓ | now | one-off unless pattern | Stage matters: appealable ≠ final |
| Demand quashed | BS | — | ↑ | now | one-off | Contingent liability released |
| Insolvency petition/admission | BS | GOV, LIQ | ↓↓↓ | now | terminal-risk | Equity is residual claimant; severity max |
| Pledge invocation | GOV | LIQ (supply) | ↓↓ | now | structural | Promoter distress + forced share supply |
| Pledge release | GOV | — | ↑ | now | structural | Promoter balance sheet healing |
| Promoter open-market buying | GOV (alignment) | — | ↑ | 1–2Q | signal | Skin-in-the-game statement |
| **Rating downgrade** | BS | MAR (borrowing cost ↑) | ↓ | 1–2Q | structural | Cost of debt reprices; covenant risk |
| Issuer Not Cooperating | GOV | BS (unknown) | ↓ | now | structural | Refusing the exam is information |
| **Capacity commissioning** | REV | MAR (op leverage) | ↑ | 1–2Q | structural | Capex finally earning; utilization ramp next |
| Capex deferral | REV (future) | — | ↓ | multi-yr | structural | Management's demand forecast, revealed |
| Plant shutdown/fire | REV/CF | — | ↓ | now–1–2Q | usually one-off | Insurance recovery lags; duration is the variable |
| Cyber incident | CF (cost) | GOV | ↓ | now | usually one-off | Early "no material impact" claims age badly |
| **USFDA Warning Letter/OAI** | REV (approvals frozen from site) | — | ↓ | multi-yr | structural until cleared | Site-specific pipeline blocked |
| USFDA EIR / approval | REV | — | ↑ | 1–2Q | structural | Site cleared / product monetizable |
| Import alert | REV | — | ↓↓ | now | structural | Existing revenue stops, not just future |
| ASM/GSM placement | LIQ | — | ↓ | now | while listed | Margins up, speculation down; not fundamental |
| Trading suspension | LIQ | GOV | ↓↓↓ | now | terminal-risk | Can't exit; severity max |

---

## How the product uses this

1. **Impact chips in the feed.** Beyond the sentiment badge, show the
   dimension + horizon: "REV ↑ multi-yr" (order win) vs "one-off gain"
   (exceptional-item beat). Two events with identical green badges can have
   opposite persistence — this matrix is what tells users which is which.

2. **`sentiment_basis` template.** The best basis sentence = event + size +
   dimension + persistence: "Order of Rs 218 cr (~7% of mcap) adds
   multi-year revenue visibility through FY29." The family prompts already
   gesture at this; the matrix makes it systematic.

3. **Materiality refinement.** Same rupee size, different score: a Rs 100 cr
   one-off gain < Rs 100 cr structural revenue addition < Rs 100 cr solvency
   hole. Persistence and dimension should modulate the %-of-mcap anchor.

4. **Signal vs driver separation.** Dividends, buybacks, promoter buying,
   bonus issues are SIGNALS about management's view — real information, but
   not business changes. Never let the basis text conflate "management is
   confident" with "revenue will grow."

5. **The four terminal-risk events** (default, insolvency, fraud
   classification, suspension) sit outside normal scoring — they question
   whether equity survives at all, which is why they carry severity_override
   regardless of size.

6. **User education surface.** This matrix, rendered as a help page
   ("what does each event mean for the business?"), is itself a retention
   feature — it teaches retail users the analytical frame while showing
   your feed's badges aren't arbitrary.
