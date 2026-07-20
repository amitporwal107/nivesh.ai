# Functionality Verification Report — staging evidence (HDFC Life probe)

> **PARTIALLY SUPERSEDED (2026-07-19).** The code this report was written alongside
> (event_type extraction, the denominator join, migration 129, the Sentiment tab) was
> **dropped** — superseded upstream by `04292a04`, `919c96d6`, `2256dcc8`, `96d472d0`.
> Its companion reports were withdrawn.
>
> **What remains valid**, because it is measured data about staging rather than a
> claim about that code:
> * TC-21/TC-22 — the denominator join executes; symbol format matches (4,990 joins).
> * Market-cap coverage: 221 of 2,583 symbols (8.6%); only 13% of ticker-bearing
>   filings can anchor on market cap.
> * The BFSI finding — HDFCLIFE has EBITDA (2,845) BELOW PAT (3,389), "revenue" of
>   ₹183,270 cr is the wrong denominator, EBITDA appears 0 times across four
>   transcripts while VNB appears 23 times. The margin vocabulary is APE/VNB/product
>   mix/persistency. This still argues for sector-gating any ratio language.
> * TC-7 — 511 of 785 filing_insight rows carried a placeholder period. Note the fix
>   that landed (`04292a04`) normalises on READ instead of migrating the rows, so the
>   511 remain in the table and display correctly rather than being rewritten.

- **Branch:** fix/filing-insights-period-sentiment
- **Date:** 2026-07-19
- **Author:** Claude (full-stack-developer + qa-engineer + domain review)
- **Environment:** **staging** — `nidp-postgres-staging` on nidp-stack-vm, db `nidp_staging`, via IAP. Read-only SELECTs only; the prod container `nidp-postgres` was NOT touched.
- **Changed areas:** none this session — this report closes previously BLOCKED cases with real data.

## Summary

Closes TC-7, TC-21 and TC-22 from the two prior reports, and records a **domain
finding that materially affects the business-impact matrix design**: the generic
denominator set does not work for financials/insurers.

## Cases closed

| ID | Scenario | Result | Evidence |
|----|----------|--------|----------|
| TC-21 | `_FETCH_SQL` joins parse and execute | **PASS** | query returned counts over 19,136 rows |
| TC-22 | filings from companies with no fundamentals still returned | **PASS** | LEFT semantics hold: 13,845 with ticker vs 4,990 joined |
| TC-7 | migration 129 predicate matches placeholder rows | **PASS (dry-run)** | matches exactly 511 rows, all literal `null` |

### TC-21 / TC-22 — the denominator join executes

```
 announcements | with_ticker | join_fundamentals | join_mcap
---------------+-------------+-------------------+-----------
         19136 |       13845 |              4990 |      1861
```

**The symbol-format mismatch I flagged as the main risk did NOT materialise.**
4,990 successful fundamentals joins prove `corporate_announcements.ticker_symbol`
matches `symbol` in `v_stock_fundamentals_latest`.

### But denominator COVERAGE is the real constraint

```
 syms_with_mcap | syms_total | syms_fundamentals | ann_symbols
----------------+------------+-------------------+-------------
            221 |       2583 |               647 |        2327
```

`market_cap_cr` is populated for **221 of 2,583** symbols (8.6%). Only **1,861 of
13,845** ticker-bearing filings (13%) can anchor on market cap. The matrix's primary
materiality anchor — "% of market cap" — is therefore unavailable for ~87% of
filings. The code degrades honestly (LEFT join → prompt says "NOT AVAILABLE"), so
this is a data-coverage gap, not a defect. But the matrix cannot be scored as
designed until `stock_features_daily.market_cap_cr` is backfilled.

### TC-7 — migration 129, dry-run

```
 period | count
--------+-------
 null   |   511
```

511 of 785 filing_insight rows (**65%**) carry a placeholder period, all the literal
lowercase string `null`. Migration 129's `IN (...)` predicate matches exactly these
511 and nothing else. The UPDATE was **not executed** — this is the SELECT with the
migration's own WHERE clause. The `NULL` chip is the majority case, not an edge case.

## 🔴 Domain finding — the denominator model breaks for insurers

Probe: HDFC Life (HDFCLIFE), as requested.

```
  symbol  | revenue_ttm_cr | pat_ttm_cr | ebitda_ttm_cr | mcap_cr
----------+----------------+------------+---------------+---------
 HDFCLIFE |    183270.0000 |  3389.0000 |     2845.0000 |
```

Three problems, in increasing order of seriousness:

1. **No market cap.** HDFCLIFE is not among the 221 symbols with `market_cap_cr`.
2. **EBITDA (2,845) is BELOW PAT (3,389).** Arithmetically incoherent for a normal
   company. It is not a data bug — EBITDA is a meaningless construct for a life
   insurer, whose P&L is premiums, investment income and actuarial reserve movements.
   A naive margin calc yields EBITDA margin 1.55% and PAT margin 1.85%, i.e. PAT
   margin > EBITDA margin, which would be nonsense on a card.
3. **"Revenue" of ₹183,270 cr is the wrong denominator.** It aggregates premium and
   investment income. A ₹500 cr item would read as 0.27% of revenue and be scored
   immaterial, when for an insurer it may be highly material.

### The transcripts confirm it

```
                doc_id                |  filed_at  | chunks | vnb | margin | ebitda
--------------------------------------+------------+--------+-----+--------+--------
 607d4540-47b5-4a13-aa09-f8f932747d54 | 2026-07-15 |      1 |   0 |      0 |      0
 f91f39d4-1eee-4da4-84e9-86053cf90cf1 | 2026-04-23 |     46 |  13 |     13 |      0
 ce188436-880d-4c1e-aead-c3612f106c96 | 2026-04-16 |      1 |   0 |      0 |      0
 4dd93b9a-3605-4b73-bf32-1089b0a9e3ef | 2026-01-22 |     37 |  10 |     16 |      0
```

- **EBITDA: 0 mentions across all four transcripts.** Management never uses it.
- **VNB: 23 mentions** across the two real transcripts.
- Two of the four "transcripts" have a single chunk — the known letterhead/audio-tier
  pattern (a cover letter linking a recording), not a transcript.

Actual margin language from the Apr-2026 call:

> "…par products at 25%, term at 7%, and annuity at 5%… the quality of our unit-linked
> business continues to improve with higher protection multiples and better rider
> attachment supporting margins… Annuity mix increased by almost 300 basis points YoY
> to around 8% of individual APE in Q4 FY26."

The operative metrics are **APE, VNB, product mix, persistency, protection multiples**
— none of which exist in the denominator set.

### Implication for the matrix

The impact matrix assumes one denominator model (mcap / revenue / PAT / EBITDA) that
holds across all issuers. It does not hold for BFSI. Options, cheapest first:

1. **Sector-gate the ratios.** Suppress percentage-of-revenue and EBITDA-margin
   language for banks/NBFCs/insurers; emit direction and absolute figures only. Small
   change, prevents wrong numbers.
2. **Add a BFSI denominator set** (APE, VNB, AUM, NII, GWP) and a sector-specific
   rubric. Correct, materially more work, needs a data source that does not exist in
   `fundamentals_ttm` today.
3. Ship as-is for non-BFSI and exclude BFSI from the matrix until (2).

I recommend (1) now and (2) as scoped follow-up. Shipping as-is would put
arithmetically incoherent margins on insurer cards.

## Verification command (this session)

- **Command:** `python3 -m pytest backend/nidp/tests/services/test_filing_insights_generator.py backend/nidp/tests/services/test_filing_insights_impact_matrix.py -q`
- **Output:** `73 passed in 0.33s`
- **Result: PASS**

## Still not verified

- Migration 129 has still **not been executed** anywhere. TC-8 (real periods
  untouched) remains open until it runs.
- No LLM call has been made with the new prompt; `event_type` classification quality
  is unmeasured.
- TC-9 (staging API returning a cleaned period) needs this branch deployed. It is not.

## Verdict: PASS
