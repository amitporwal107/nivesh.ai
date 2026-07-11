# Pillar 1 — Fundamental Analysis & Reading a Balance Sheet

**Grounding first:** the repo's TTM/annualization basis is non-obvious and has been fixed
several times. Before quoting *any* fundamental figure, read the code that produces it —
`backend/nidp/services/fundamental_engine/calculator.py`, the parser
`backend/nidp/services/nse_financials/parser.py`, and migrations
`100_fix_fundamentals_ttm_single_basis.sql`, `101/107/108` (Q4 contamination),
`089` (revenue-3y-CAGR basis). If the code's definition differs from the textbook one below,
**the code wins** and you say so. Pull actuals via the DaaS/fundamentals tools
(`copilot_tools/fundamental.py`, `company_financials.py`), not memory.

## Reading the three statements like an analyst

**P&L (income statement).** Revenue → gross → EBITDA → EBIT → PBT → PAT. Watch: revenue
*quality* (organic vs one-off/other-income), margin *trend* (not just level), the gap between
EBITDA and operating cash flow (accrual quality), and "exceptional/other income" propping PBT.
For banks/NBFCs the top line is **Net Interest Income (NII)**, not revenue — different template
(see `bank_npa_patch.py`, `bank_scoring/`).

**Balance sheet.** Assets = Equity + Liabilities. Read it as: how is the business *funded*
(debt vs equity), where is capital *tied up* (fixed assets, working capital, goodwill/
intangibles), and is it *getting worse* (rising receivables/inventory vs sales, rising
short-term borrowings). Reconcile equity movement to PAT + OCI − dividends; unexplained
reserve moves are a flag. Goodwill/intangibles as a large share of net worth = impairment risk.

**Cash flow.** The lie-detector. CFO should track PAT over time; persistent PAT > CFO = earnings
not converting to cash (channel stuffing, receivables build). FCF = CFO − capex. CFF shows
whether growth is debt-funded. Migration `091_current_ratio_cfo_pat_wiring.sql` wires CFO/PAT
here — read it before quoting the ratio.

## Core ratios (formula ↔ what the code computes)

Group and interpret; never quote a bare number without the trend and the peer/category context.

- **Profitability:** Gross/EBITDA/EBIT/Net margin; **ROE** = PAT / avg equity; **ROCE** =
  EBIT / (avg debt + avg equity); **ROA**. ROE decomposed (DuPont) = net margin × asset
  turnover × leverage — a high ROE driven only by leverage is lower quality. View wiring:
  `071_fix_view_roe_debt_equity.sql`, scores `048_nidp_fundamental_scores.sql`.
- **Leverage/solvency:** **Debt/Equity**, Net Debt/EBITDA, **Interest coverage** = EBIT /
  interest. For banks use CAR/Tier-1, GNPA/NNPA, PCR instead.
- **Liquidity:** Current ratio = current assets / current liabilities; Quick ratio (ex-inventory);
  `090_screener_balance_cashflow.sql`, `091`.
- **Efficiency:** Asset turnover, inventory/receivable/payable days, cash conversion cycle.
- **Valuation:** **P/E** (trailing on TTM EPS vs forward on estimates — `114_nidp_earnings_estimates.sql`),
  **P/B**, **EV/EBITDA**, **P/S**, **dividend yield**, **PEG**. Always pair a multiple with
  growth + ROCE + the sector's own norm — a "cheap" P/E on a declining ROCE is a trap.
- **Growth:** revenue/EPS CAGR — **mind the basis** (annual source per `089`); TTM vs FY.
- **DCF (when asked to value):** FCFF discounted at WACC, terminal via Gordon growth
  (TV = FCFF·(1+g)/(WACC−g)); state every assumption (g, WACC, horizon) — DCF is an opinion
  wearing a number's clothes, so show the sensitivity, don't present one point estimate.

## Quality & distress composites (models, label them as such)

- **Piotroski F-score (0–9):** 9 binary tests across profitability, leverage/liquidity, and
  operating efficiency. High = improving fundamentals. Good screen, not a verdict.
- **Altman Z-score:** distress predictor (original for manufacturers; Z″ for
  non-manufacturers/EM — pick the right variant and say which). < ~1.8 = distress zone.
- **Beneish M-score:** earnings-manipulation likelihood from 8 accrual/growth ratios.
Report these as *signals with a definition*, compute against real inputs, and cite the model.

## Red flags an expert always checks (retrieve the real data)

- **Promoter pledge** rising / high (feed: `nse_pledge_data/`) — forced-sale + governance risk.
- **Shareholding shifts** — promoter stake falling, pledge up (`025`, `109_shareholding_nse_golden_source.sql`).
- **Accrual quality** — PAT ≫ CFO, receivable/inventory days ballooning vs revenue.
- **Related-party transactions**, frequent **auditor/CFO change**, qualified audit opinion.
- **Contingent liabilities / off-balance-sheet** > net worth.
- **Other-income dependence**, capitalised interest, aggressive revenue recognition.
- **Banks/NBFC:** GNPA/NNPA trend, slippage, restructured book, provision coverage, NIM
  compression, CASA mix (`bank_npa_patch.py`, `bank_scoring/`, PRA engine `092_pra_fundamental_risk.sql`).

## India-specific care

- **Ind-AS** vs old GAAP restatements; consolidated vs standalone (always compare like-for-like).
- **Q4 = FY − 9M** derivation is where errors hide — the repo fixed this repeatedly
  (`101/107/108`); never quote a Q4/TTM figure without reading those.
- Sector templates differ: banks, NBFCs, insurers, and financials are **not** the industrial
  template — the parser branches for them; check which template produced the row.

## Definition of Done for a fundamental call
Formula shown and matched to the code's definition (basis stated: TTM/FY, consolidated/standalone);
inputs pulled this turn from the real parser/DaaS; the `nse_financials` feed checked fresh in
`nidp.v_feed_status`; trend + peer/category context given; red flags surfaced from real data;
valuation opinions carry their assumptions and a sensitivity, not a false-precision single number.
