# Deal-feature calibration audit — confidence asymmetry, entity classification, tilt calibration

**Date:** 2026-10-22
**Scope:** READ-ONLY audit of three claims carried by the Study C diagnosis, plus a ruling on
whether each candidate fix changes the REGISTERED design. Nothing was changed: no code, no DB
write, no re-run, no edit to either frozen contract, no run row created. This report is the only
file created.
**Database:** `nidp_staging` via `~/.config/nivesh/nidp-psql.sh`. Every number below is real query
output obtained this session.
**Sibling report:** `test_reports/deal_contract_audit_20261022.md` covers registered-vs-implemented
feature coverage. This report does not repeat it; it audits calibration and rules on disposition.

---

## 0. Two things that moved under this audit, and how they were pinned

### 0a. The deal table GREW mid-audit. All Claim-2 numbers are snapshot-qualified.

`nidp.trendlyne_deals` was 19,787 legs / 328 symbols when the diagnosis was written. The ingest
repair (migration 181 + the `_symbols()` reordering) landed and ran **while this audit was in
progress**, at 09:26 IST:

```
 snapshot_taken_at                | legs_total | symbols_total | legs_at_run_time | symbols_at_run_time
----------------------------------+------------+---------------+------------------+---------------------
 2026-10-22 09:26:42.886119+05:30 |      33290 |           561 |            19787 |                 328
```

`retrieved_at <= '2026-10-22 05:11:06+05:30'` reconstructs the diagnosis snapshot **exactly**
(19,787 legs / 328 symbols), so that cutoff is used as the reproduction key throughout. Every
population figure below is labelled either **cohort A** (what the reported run could see) or
**cohort B** (the table now). Numbers I computed before noticing the growth were discarded and
re-run inside one `REPEATABLE READ` transaction.

The root-cause fix is now committed — `_symbols()` no longer orders alphabetically:

```
107: ORDER BY f.last_attempt_at ASC NULLS FIRST, md5(c.symbol)
```

Ingest is still incomplete: **561 of 984 candidates** (57%).

### 0b. The working tree moved. The tilt formula is pinned three ways.

`evaluator.py` was committed by another session during this audit and HEAD advanced to `bc3bb2bf`.
The reported run recorded `code_commit` values (`b4d521e5`, `72a9243c`) that are **not ancestors of
this tree's HEAD**, because the evaluator runs from a different checkout
(`/opt/nidp/dev-repo/nivesh.ai`). The deal path was therefore confirmed independently:

1. read in this working tree;
2. read on the staging checkout at `72a9243c` (the 09:07 run's commit) — **byte-identical**;
3. recomputed in SQL from `nidp.v_trendlyne_deals_net` and compared against the stored tilts —
   `max_abs_gap = 0.001`, which is the 3-dp storage rounding, and `0` gaps above 0.002.

### 0c. Which run pair is the audit anchor

Two surviving pairs reproduce the reported verdict. The 05:11 pair matches the diagnosis funnel
exactly (6,873 eligible) and is used throughout:

```
        lbl        | dates | b_slots | c_slots | mean_diff_pp | zero_diffs
-------------------+-------+---------+---------+--------------+------------
 05:11 (6873 elig) |     9 |     270 |     270 |       0.2189 |          6
 09:07 (6871 elig) |     9 |     270 |     270 |       0.2189 |          6
```

- Model B run: `4faf3eaa-2b3f-4bbc-af4b-2fca627830bf`
- Model C run: `9c0eb9f6-be16-41e9-bbcd-b83ba7e0f82f`

The run's own notes confirm `"mean_paired_diff_pp": 0.2189`, `"ci95_pp": [0.0, 0.5104]`,
`"portfolio_names_changed_total": 4`, `"verdict": "INCONCLUSIVE"`.

**The diagnosis funnel reproduces exactly under the cutoff:**

```
 eligible_symbol_dates | with_a_deal_row | survived_netting | zeroed_by_buy_eq_sell | nonzero_tilt
-----------------------+-----------------+------------------+-----------------------+--------------
                  6873 |             498 |              363 |                   180 |          183
```

---

## 1. CLAIM 1 — Confidence asymmetry. **CONFIRMED.**

### 1a. The real code

`backend/nidp/services/smart_money_study/evaluator.py`, lines 283-292 (identical on the staging
checkout at `72a9243c`):

```python
def _deal_tilt(row: dict, max_tilt: float) -> float:
    buy = int(row.get("buying_clients") or 0)
    sell = int(row.get("selling_clients") or 0)
    if buy + sell == 0:
        return 0.0
    direction = (buy - sell) / (buy + sell)
    confidence = 1.0 if buy >= 3 else (0.6 if buy == 2 else 0.3)
    return max(-max_tilt, min(max_tilt, direction * confidence * max_tilt))
```

The claimed formula is exact. `confidence` keys **only** on the buy count.

### 1b. The asymmetry is structural, not a data artefact

`|direction| <= 1` and `confidence <= 1.0`, so:

| side | attainable extreme | why |
|---|---|---|
| positive | **+4.0** | `buy >= 3, sell = 0` -> `direction = +1`, `confidence = 1.0` |
| negative | **-1.2** | `direction = -1` **requires** `buy = 0`, which forces `confidence = 0.3` |

The negative side can reach only **30%** of the positive side, and no amount of selling evidence
can change that: a name with 50 distinct sellers and zero buyers is capped at -1.2.

**Corollary — the clamp is dead code.** Since `|direction * confidence * max_tilt| <= max_tilt`
always, `max(-max_tilt, min(max_tilt, ...))` can never bind. The declared bound enforces nothing;
the operative range is `[-0.3 * max_tilt, +max_tilt]`.

### 1c. Realised range from real data

```
 eligible_symbol_dates | nonzero_tilt | pct_nonzero | min_tilt | max_tilt | n_negative | n_positive
-----------------------+--------------+-------------+----------+----------+------------+------------
                  6873 |          183 |        2.66 |   -1.200 |    3.653 |         63 |        120
```

Realised **[-1.2000, +3.6530]**; `1.200 / 3.6522 = 32.9%`. Claim confirmed.

**Every one of the 46 buy=0 symbol-dates received exactly -1.2.** The distinct negative values are:

```
 d_tilt | count
--------+-------
 -1.200 |    46      <- buy = 0 (floor, reached only here)
 -0.800 |     4
 -0.600 |     1
 -0.572 |     2
 ... (11 distinct values in all)
 -0.138 |     2
```

and the confidence buckets confirm 46 is exactly the `buy = 0, sell > 0` population:

```
                bucket                 | symbol_dates | where_buy_eq_sell
---------------------------------------+--------------+-------------------
 buy=0, sell>0  -> conf 0.3, tilt -1.2 |           46 |                 0
 buy=0,sell=0 (netted to nothing)      |          135 |               135
 buy=1          -> conf 0.3            |          146 |               110
 buy=2          -> conf 0.6            |           37 |                19
 buy>=3         -> conf 1.0            |          134 |                51
```

(498 = 46+135+146+37+134; 363 = 498-135; 180 = 110+19+51; 183 = 363-180. The whole funnel closes.)

### 1d. The incoherence is measurable, not merely theoretical

Of the 46 sell-only symbol-dates, **17 have 2-4 distinct selling clients** and are still damped as
if they were a single-client signal:

```
 selling_clients_in_window | symbol_dates |    treatment
---------------------------+--------------+------------------
                         1 |           29 | conf 0.3 applied
                         2 |            7 | conf 0.3 applied
                         3 |            6 | conf 0.3 applied
                         4 |            4 | conf 0.3 applied
```

**10 of them have 3-4 distinct sellers** — breadth that, on the buy side, earns `confidence = 1.0`.

Counterfactual with confidence keyed on the dominant side's client count:

```
     side      |  n  | mean_abs_actual | mean_abs_sym | extreme_actual | extreme_sym | n_magnitude_grows
---------------+-----+-----------------+--------------+----------------+-------------+-------------------
 negative side |  63 |          1.0099 |       1.6509 |        -1.2000 |     -4.0000 |                24
 positive side | 120 |          1.4722 |       1.4722 |         3.6522 |      3.6522 |                 0
```

**Zero positive rows change.** The rule is a pure sell-side penalty: mean |tilt| on the negative
side is suppressed by 39% (1.6509 -> 1.0099) and 24 of 63 negative rows are under-weighted.

### 1e. A second, independent defect found in the same path

`_DEALS_SQL` (line 194) does `sum(buying_clients)`, where the view computes
`count(DISTINCT client_name)` **per day**. Summing per-day distinct counts over a 90-day window is
neither a distinct client count nor a leg count — a client transacting on 12 days contributes 12.
Measured under the cutoff:

```
 symbol_dates | rows_where_summing_inflates | max_inflation | conf_1_0_on_under_3_true_clients | tilt_differs_gt_0_05 | sign_flips | max_abs_tilt_gap
--------------+-----------------------------+---------------+----------------------------------+----------------------+------------+------------------
          363 |                          71 |            55 |                                3 |                   27 |          4 |           0.6788
```

**4 sign flips** and a max tilt error of 0.6788 — against rank-30 boundary gaps of 0.003-0.270
(section 3). Clearest case:

```
     d      |   symbol   | buy_summed | sell_summed | buy_true | sell_true | tilt_asis | tilt_true
------------+------------+------------+-------------+----------+-----------+-----------+-----------
 2026-08-12 | SUDEEPPHRM |          2 |           4 |        2 |         2 |    -0.800 |     0.000
 2026-08-12 | BLUESTONE  |         27 |          29 |        6 |         8 |    -0.143 |    -0.571
```

SUDEEPPHRM: the same 2 buyers and 2 sellers across several days are summed to 2 vs 4, producing a
-0.800 tilt where the true distinct-client picture is exactly neutral.

---

## 2. CLAIM 2 — Classification gap. **CONFIRMED, and materially worse than reported on the data
the overlay actually consumes. But the mechanism is evidence DESTRUCTION, not false promotion.**

### 2a. No counterparty category exists anywhere in the deal path — confirmed

`nidp.trendlyne_deals` columns: `symbol, deal_date, client_name, deal_type, action, quantity,
price, traded_percent, exchange, source, retrieved_at, source_run_id`. No category.
`nidp.v_trendlyne_deals_net` exposes 13 columns, none a category.

A schema-wide search for any counterparty classification found exactly one relevant column —
`nidp.insider_sast.client_category` — and **that table holds 0 rows**:

```
 insider_sast_total_rows
-------------------------
                       0
```

So the only category column in the schema, on a sibling feed from the *same* vendor tool
(`get_ownership_deals_insider_sast`), is empty and gives no evidence either way.

### 2b. Prop / market-maker share — recomputed. **Treat as a LOWER BOUND.**

No classification exists in the data, so this is name-pattern matching: 22 patterns, which matched
29 distinct `client_name` values out of **3,172** in the surviving set. The true share is higher by
an unknown amount.

```
                    cohort                     | surviving_legs | prop_legs | pct_prop
-----------------------------------------------+----------------+-----------+----------
 A) legs visible to the reported 05:11 run     |          12844 |      4740 |    36.90
 B) legs in the table NOW (post ingest repair) |          22646 |      8803 |    38.87
```

Whole-table share is **36.90%** (cohort A) against the reported ~30.4% — higher because my list is
longer, consistent as lower bounds. **It does not dilute as coverage completes: it rises** (36.90%
-> 38.87%, and 4,740 -> 8,803 legs in absolute terms).

**On the legs the study actually consumed, it is far worse:**

```
 consumed_legs | surviving_legs | prop22_legs | pct_prop22 | pct_narrow7 | client_symbol_days | both_sides | pct_both_sides
---------------+----------------+-------------+------------+-------------+--------------------+------------+----------------
          2083 |           1717 |         980 |      57.08 |       49.04 |               1005 |        593 |          59.00
```

**57.08%** of consumed surviving legs are prop/market-making on the 22-pattern list, and **49.04%**
on a conservative 7-name list (the names the diagnosis itself cited). The eligible universe is
large liquid names — exactly where HFT market makers concentrate — so the consumed subset is about
twice as contaminated as the table at large.

**Classification-free corroboration** (no name list at all — pure round-trip signature, clients
with >=10 legs whose buys and sells are within 10%): 86 clients, 6,021 of 12,844 surviving legs =
**46.88%** whole-table; on the consumed subset, 21 clients, 1,114 of 1,717 legs = **64.88%**.

The leg counts make the mechanism self-evident — perfect buy/sell symmetry is the signature of a
market maker, not of accumulation:

```
                     client_name                      | surviving_legs | symbols | buys | sells
------------------------------------------------------+----------------+---------+------+-------
 GRAVITON RESEARCH CAPITAL LLP                        |           1500 |     152 |  750 |   750
 HRTI PRIVATE LIMITED                                 |            502 |      59 |  251 |   251
 NK SECURITIES RESEARCH PRIVATE LIMITED               |            386 |      85 |  193 |   193
 QE SECURITIES LLP                                    |            274 |      52 |  137 |   137
 JUNOMONETA FINSOL PRIVATE LIMITED                    |            274 |      53 |  137 |   137
 MICROCURVES TRADING PRIVATE LIMITED                  |            188 |      51 |   94 |    94
 IRAGE BROKING SERVICES LLP                           |            188 |      37 |   94 |    94
 XTX MARKETS LLP                                      |            158 |      31 |   79 |    79
 TOWER RESEARCH CAPITAL MARKETS INDIA PRIVATE LIMITED |            140 |      18 |   70 |    70
 ALPHAGREP SECURITIES PRIVATE LIMITED                 |            124 |      22 |   62 |    62
```

### 2c. Same client on both sides — recomputed. **38.46% confirmed.**

```
           cohort            | client_symbol_days | both_sides | pct_both_sides
-----------------------------+--------------------+------------+----------------
 A) visible to the 05:11 run |               8815 |       3390 |          38.46
 B) table NOW                |              15266 |       6362 |          41.67
```

**38.46%** against the reported 38.5% — confirmed. Leg-weighted it is 54.12%. On the consumed
subset it is **59.00%** (593 of 1,005). Again it rises with coverage, not falls.

These are the legs that escape the registered netting rule: that rule pairs off legs matching on
`(symbol, date, quantity, price)`, so a market maker who buys 10,000 @ 100 and sells 10,000 @ 100.5
on the same day survives netting and is then counted as both a distinct buyer and a distinct seller.

### 2d. **IMPORTANT REFRAMING — the gap destroys evidence; it does not currently inflate it**

```
 survived_netting | zeroed_buy_eq_sell | would_revive_without_prop | were_purely_prop | would_be_silenced_without_prop
------------------+--------------------+---------------------------+------------------+--------------------------------
              363 |                180 |                         0 |              111 |                              0
```

**111 of 363 surviving symbol-dates (30.6%) consist ENTIRELY of prop/market-maker legs**, and they
already produce tilt 0 because `buy = sell` exactly — market makers are symmetric by construction.
**Zero** of the 180 zeroed cases would revive if prop legs were removed, and **zero** would be
silenced.

So the classification gap is currently **self-cancelling** rather than bullish-biased. That is a
correction to the diagnosis's framing, and it matters for the disposition: the defect is **latent**,
not active. Two ways it is nonetheless real:

**(i) It corrupts the breadth certificate that `confidence` depends on.**

```
 awarded_confidence_1_0 | would_LOSE_1_0_without_prop | breadth_was_ENTIRELY_prop | conf_0_6_depends_on_prop
------------------------+-----------------------------+---------------------------+--------------------------
                    134 |                          60 |                        30 |                       19
```

**44.8% of full-confidence awards (60 of 134) rest on market-maker legs, and 22.4% (30 of 134) rest
ENTIRELY on them** — zero genuine buyers. `confidence = 1.0` is supposed to certify independent
breadth; in 30 cases it certifies a market maker's book.

**(ii) When a prop desk's per-day presence is asymmetric, it injects an arbitrary magnitude.** This
is demonstrated on a slot that actually changed:

```
     d      |   sym    | buy_summed | sell_summed | tilt_as_implemented | buy_no_prop | sell_no_prop | tilt_prop_excluded | distinct_prop_names
------------+----------+------------+-------------+---------------------+-------------+--------------+--------------------+---------------------
 2026-03-12 | BAJAJCON |          6 |           4 |               0.800 |           2 |            0 |              2.400 |                   4
 2026-04-13 | CPPLUS   |          4 |           2 |               1.333 |           4 |            2 |              1.333 |                   0
 2026-08-12 | ANTHEM   |         22 |           1 |               3.652 |          22 |            1 |              3.652 |                   0
 2026-08-12 | EMCURE   |          9 |           1 |               3.200 |           9 |            1 |              3.200 |                   0
```

BAJAJCON was promoted 38 -> 29 on a tilt of +0.800 built from 6 buyers and 4 sellers, of which
**4 distinct names are market makers appearing on BOTH sides** (ALPHAGREP, MICROCURVES,
NK SECURITIES RESEARCH, QE SECURITIES). Excluding them gives buy=2 / sell=0 and a tilt of
**+2.400 — three times larger.** The sign survives; the magnitude is unstable by 3x on a
classification that does not exist. That is the defect: not bias, but arbitrariness.

The other three promotions carry zero prop names and rest on genuine institutional counterparties.
Worth recording what they actually are, because 002's `evidence_claim` speaks to it directly:

- **ANTHEM** (22 distinct buyers, 1 seller): SBI MF, HDFC MF, UTI MF, Kotak Life, 360 ONE MF,
  Canara Robeco, Edelweiss MF, Mahindra Manulife, WhiteOak, Nordea, Manulife Global, Prudential HK,
  Societe Generale — against one individual seller. A broad placement/anchor allocation.
- **EMCURE** (9 buyers, 1 seller): Aditya Birla SL MF, Axis MF, HSBC MF, HDFC Life, Goldman Sachs
  Mauritius, Morgan Stanley Asia, BNP Paribas — against **BC INVESTMENTS IV LIMITED**, which
  `flow_ledger.py`'s own comment names as a PE holdco ("Baring's BC Investments"). A PE block exit
  absorbed by institutions.
- **CPPLUS** (4 buyers, 2 sellers): EPF Board, Kotak MF, Motilal Oswal MF, Nomura India Stock
  Mother Fund — against **DIXON TECHNOLOGIES** (corporate/strategic) and **HARI KHEMKA BUSINESS
  FAMILY TRUST** (promoter family). A promoter/strategic sell-down absorbed by institutions.

Three of the four promotions are the *absorption side of a one-off supply event*. That is real
institutional buying and it is also precisely what 002 warns against reading as accumulation:
*"a disclosed deal evidences that a TRANSACTION occurred, never that an institution is accumulating
with a bullish view."*

### 2e. Can the repo's own FPI classifier be wired in? **No, not as the needed classifier.**

`backend/nidp/services/daas_api/flow_ledger.py` defines `is_fpi_house()` (line 353) over a curated
`FPI_HOUSES` whitelist plus a `DOMESTIC_VEHICLE_MARKERS` pre-exclusion. What it actually classifies:

```
                   verdict                   | surviving_legs | pct_legs | distinct_names
---------------------------------------------+----------------+----------+----------------
 UNCLASSIFIED (classifier returns FALSE)     |          17840 |    82.84 |           3668
 recognised FPI house (TRUE)                 |           1996 |     9.27 |            566
 domestic_vehicle (classifier returns FALSE) |           1700 |     7.89 |            485
```

Four reasons it does not solve this problem:

1. **It answers the wrong question.** It is a POSITIVE whitelist for *FPI portfolio investors*. A
   `False` answer conflates prop desks, domestic AMCs and 3,668 unclassified names. It cannot
   express "this is a market maker" — the needed predicate.
2. **It is deliberately incomplete and says so.** The module's own constant:
   `"the known FPI-house list, which is curated and demonstrably incomplete"`. It returns `False`
   for **90.7%** of surviving legs.
3. **It reads different tables.** Its deal SQL is over `nidp.bulk_deals` / `nidp.block_deals`
   (lines 408, 412), not `nidp.trendlyne_deals`. It is imported only by
   `daas_api/routers/flow_ledger.py:94` and **nowhere in the smart-money or trendlyne path**.
4. **The knowledge exists only as a comment.** `flow_ledger.py` lines 61-63 already name the
   population precisely — *"Domestic proprietary and HFT desks — QE Securities, HRTI, Junomoneta,
   Graviton, iRage. Both sides of the book, netting to roughly nothing."* — but there is no code
   list for it. Population (3) is documented and unimplemented.

What *is* reusable is the module's three-population taxonomy and its stated reason for curating by
hand: *"separating (1) from (2) cannot be done by name shape ... only by knowing which are portfolio
managers."* That argument applies with equal force here, and is exactly why a prop-desk list is a
researcher degree of freedom (see section 4c).

---

## 3. CLAIM 3 — Calibration risk. **CONFIRMED. +/-4.0 is too hot, and the masking is already
coming off — measured, not projected.**

### 3a. Boundary gaps — confirmed exactly

```
 scoring_date | score_rank30 | score_rank31 | gap_30_31 | gap_25_35
--------------+--------------+--------------+-----------+-----------
 2026-01-12   |      57.9550 |      57.9200 |    0.0350 |    0.8320
 2026-02-12   |      58.1180 |      58.1050 |    0.0130 |    0.9280
 2026-03-12   |      56.7580 |      56.7400 |    0.0180 |    1.1250
 2026-04-13   |      58.5720 |      58.3020 |    0.2700 |    1.5710
 2026-05-12   |      58.1200 |      58.0600 |    0.0600 |    0.6940
 2026-06-12   |      58.6800 |      58.6770 |    0.0030 |    0.5180
 2026-07-13   |      59.1030 |      59.0340 |    0.0690 |    0.7950
 2026-08-12   |      62.0190 |      61.8130 |    0.2060 |    1.1540
 2026-09-15   |      60.5800 |      60.4360 |    0.1440 |    1.0730
```

Range **0.0030 - 0.2700**, exactly as claimed. The span across *ten* ranks (25 -> 35) is only
0.518 - 1.571 points, so **a +1.2 tilt exceeds the entire 10-rank span on 7 of 9 dates**.

And `max_deal_tilt = 4.0` is confirmed in code at line 341 (function default) and line 684
(`--max-deal-tilt`).

### 3b. Ranks bought per unit of tilt

At the boundary (the rank-31 name, where the head of the distribution is thinner):

```
 scoring_date | eligible_names | ranks_gained_at_1_2 | ranks_gained_at_2_4 | ranks_gained_at_4_0
--------------+----------------+---------------------+---------------------+---------------------
 2026-01-12   |            650 |                   8 |                  15 |                  23
 2026-06-12   |            801 |                  13 |                  24 |                  25
 2026-09-15   |            831 |                  12 |                  22 |                  27
```

Across all 9 dates: **+1.2 buys 8-13 ranks, +2.4 buys 15-24 ranks, +4.0 buys 23-27 ranks.**

Deeper in the list, where density is higher, the leverage is larger — and this is **observed, not
modelled**:

```
 scoring_date |  symbol   | b_rk | c_rk | deal_tilt |         change
--------------+-----------+------+------+-----------+------------------------
 2026-03-12   | BAJAJCON  |   38 |   29 |    0.8000 | PROMOTED into top30
 2026-03-12   | PETRONET  |   30 |   31 |    0.0000 | DISPLACED out of top30
 2026-04-13   | CPPLUS    |   31 |   22 |    1.3340 | PROMOTED into top30
 2026-04-13   | POWERGRID |   30 |   31 |    0.0000 | DISPLACED out of top30
 2026-08-12   | EMCURE    |   52 |   13 |    3.2000 | PROMOTED into top30
 2026-08-12   | ANTHEM    |   64 |   19 |    3.6520 | PROMOTED into top30
 2026-08-12   | HAL       |   29 |   31 |    0.0000 | DISPLACED out of top30
 2026-08-12   | PETRONET  |   30 |   32 |    0.0000 | DISPLACED out of top30
```

ANTHEM's +3.652 moved it **45 ranks** (64 -> 19); EMCURE's +3.200 moved it **39 ranks** (52 -> 13).
All four promoted begin A-E; all four displaced begin H-P and received tilt **exactly 0.0** — pushed
out passively, having never been asked. The smoking gun reproduces exactly.

The "reorders roughly 100 names" claim is best stated as the size of the *promotable pool* — names
sitting within X points below the cut, any of which a tilt of X could lift into the portfolio:

```
 scoring_date | within_1_2 | within_2_4 | within_4_0
--------------+------------+------------+------------
 2026-01-12   |         16 |         39 |         75
 2026-05-12   |         15 |         46 |        114
 2026-07-13   |         14 |         47 |        100
 2026-09-15   |         21 |         52 |         95
```

**72-114 names per date (median ~86) are within reach of a +4.0 tilt.** The claim is sound; the two
quantities (one name's displacement vs the promotable pool) are different and both are given here.

### 3c. Is +/-4.0 too hot? **Yes — plainly.**

- The maximum tilt is **15x to 1,300x** the gap that separates the 30th name from the 31st
  (0.0030 - 0.2700), and **2.5x to 7.7x** the gap spanning ten ranks.
- It is earned by a *minimal* qualifying event: three distinct buying clients and no sellers over
  90 days. There is no quantity, no turnover normalisation, no price context (section 4d) — so the
  largest available score movement is triggered by the thinnest available evidence.
- The bound is calibrated as if the baseline score were spread over tens of points at the boundary.
  It is spread over hundredths.

**And the registered "neither can dominate" clause is already violated in realised terms.** 002
requires the deal contribution be *"bounded SEPARATELY from the holdings overlay so neither can
dominate"*. Nominally 4.0 vs the MF overlay's registered 8.0 looks conservative. Measured:

```
 mf_min  | mf_max | mf_mean_abs | mf_nonzero | deal_min | deal_max | deal_mean_abs_when_fires | deal_beats_mf | deal_nonzero
---------+--------+-------------+------------+----------+----------+--------------------------+---------------+--------------
 -5.7350 | 6.6320 |      1.5114 |       5184 |  -1.2000 |   3.6530 |                   1.3131 |            98 |          183
```

Mean |tilt| is 1.5114 (MF) vs **1.3131** (deal, when it fires) — essentially equal. And of the 183
name-dates where the deal feature fires, **98 (53.6%) have |deal tilt| > |MF tilt| for the same
name-date.** When the deal feature speaks, it out-weighs the overlay it is registered not to
dominate, more often than not.

### 3d. The masking is coming off. **Measured against the repaired feed.**

The repaired ingest landed mid-audit. Against the **same 9 dates and the same eligible universe**:

```
 eligible_symbol_dates | with_a_deal_row | survived_netting | nonzero_tilt_NOW | fire_rate_pct_NOW | tilt_ge_1_2 | tilt_ge_2_4 | min_tilt | max_tilt
-----------------------+-----------------+------------------+------------------+-------------------+-------------+-------------+----------+----------
                  6873 |             857 |              655 |              302 |              4.39 |         205 |          42 |  -1.2000 |   3.6522
```

| | reported run | now (57% ingest) | change |
|---|---|---|---|
| symbol-dates with a deal row | 498 | 857 | +72% |
| survived netting | 363 | 655 | +80% |
| non-zero tilt | 183 | 302 | +65% |
| **fire rate** | **2.66%** | **4.39%** | **1.65x** |
| names with \|tilt\| >= 1.2 | — | 205 | — |
| names with \|tilt\| >= 2.4 | — | 42 | — |

Note the realised extremes are **unchanged at [-1.2000, +3.6522]**: more data does not fix the
asymmetry, exactly as section 1b predicts.

Audit counterfactual on stored Model-B scores (read-only arithmetic; **no run row written, no
config touched**): top-30 slot changes would go **4 -> 6 of 270**, and **all 6 displaced names
still have tilt exactly 0.0** — passive displacement is structural, not incidental.

**Honest calibration of the warning:** at 57% ingest completion the fire rate has risen 1.65x but
slot churn only 1.5x, because most newly-firing names are not near the boundary. The masking is
coming off *gradually*, not catastrophically. But 205 names now carry a tilt large enough to buy
8-13 ranks against boundary gaps of 0.003-0.270, 423 candidates remain unqueried, and 57% of the
consumed evidence is market-maker legs. The protection the current result enjoys is a low fire rate,
and it is being removed.

---

## 4. Does each candidate fix change the REGISTERED design?

### 4.0 The fact that governs all four rulings

**No confirmatory run has ever happened. The holdout is intact.**

```
    stage    | status  | runs |              first               |               last
-------------+---------+------+----------------------------------+----------------------------------
 exploratory | OK      |    8 | 2026-10-22 05:06:26.007538+05:30 | 2026-10-22 09:07:36.173067+05:30
 exploratory | RUNNING |   10 | 2026-10-22 05:04:03.037778+05:30 | 2026-10-22 05:10:52.595697+05:30
```

All 18 runs are `stage = 'exploratory'`. No repair below burns a holdout.

Also governing: **no numeric deal tilt bound is registered anywhere.**

```
        study_id        | has_max_deal_tilt_key |                     registered_bounds_text                      | mf_tilt_bounds
------------------------+-----------------------+-----------------------------------------------------------------+----------------
 NIDP-SM-VALIDATION-001 | f                     |                                                                 | [-8.0, 8.0]
 NIDP-SM-VALIDATION-002 | f                     | "the deal contribution is bounded SEPARATELY from the holdings  |
                        |                       |  overlay so neither can dominate and each can be ablated        |
                        |                       |  independently"                                                 |
```

002 registers only the *principle*. The run's own notes agree: `"portfolio_n and deal tilt bounds
are implementation parameters, not part of either frozen contract"`.

### 4a. Symmetric confidence -> **DEFECT REPAIR. No new study_id.**

The contract settles it. 002 `deal_feature_rules.confidence`:

> *"lower confidence where the counterparty or ultimate beneficial owner is unclear; a single-client
> signal is damped as the holdings overlay already does"*

The registered predicates are (i) counterparty/UBO unclear, (ii) single-client. **Neither predicate
is "the flow is negative."** And the clause points at the holdings overlay as the model to follow —
001 `comparison.tilt_scaling`:

> *"confidence multiplier (high 1.0 / medium 0.6 / low 0.25) x concentration damping (0.5 when
> single_amc_signal)"*

That keys confidence on `data_confidence`, a **data-quality field that is blind to the sign of the
direction**. The implementation instead makes damping a function of the direction's sign, which
applies single-client damping to names with 2, 3 and 4 distinct *sellers* (17 of 46 measured in
§1d). The registered text does not describe that behaviour, so fixing it moves the code **toward**
the contract. No feature is added, no threshold reselected, no subset changed.

**Permissible within 002.** Required conditions: re-run and report both before and after, and keep
the stage exploratory.

### 4b. Window-level distinct client counts (the §1e defect) -> **DEFECT REPAIR. No new study_id.**

002 `deal_feature_rules.sides_kept_separate`:

> *"buyer and seller legs stored and counted separately; **distinct client counts, not leg counts**"*

`sum(buying_clients)` over per-day distinct counts is neither of the two things the contract names.
A client transacting on 12 days contributes 12 — that is a leg-ish count wearing a distinct-count
label. Repairing it to a window-level `count(DISTINCT client_name)` implements the registered
wording literally. **Permissible within 002**, same conditions as 4a.

### 4c. Entity classification -> **NEW PREREGISTRATION REQUIRED (new study_id + fresh holdout).**

Two independent reasons, either sufficient.

**(1) No classification data exists, so any implementation is a curated name list — a researcher
degree of freedom.** Verified in §2a: `client_name` is free text, the only category column in the
schema is empty, and the repo's own classifier covers 9.27% of legs and answers a different
question. `flow_ledger.py` states the problem itself: *"separating (1) from (2) cannot be done by
name shape ... only by knowing which are portfolio managers."* A hand-curated list, chosen with the
+0.2189 result in hand, can be tuned to the outcome — which is what preregistration exists to
prevent. 002 `why_a_separate_study`:

> *"Adding a hypothesis to it after the fact is exactly what preregistration exists to prevent, so
> the bulk/block deal feature is registered as its own versioned experiment with its own holdout."*

**(2) It is a subset change, and subset changes are forbidden post-result.** 002 `failure_policy`:

> *"No horizon, subset or threshold may be reselected after seeing results; that requires a new
> study_id."*

reinforced by 001 `promotion_rule.failure_policy`:

> *"a failed study is not rescued by changing horizon, benchmark, threshold or subset — that
> requires a new study_id and a fresh holdout"*

Excluding prop legs changes which rows enter the feature for **57.08%** of consumed surviving legs
and would strip the breadth certificate from **60 of 134** confidence-1.0 awards. That is not a
marginal correction; it is a different measurement.

**Counter-argument considered and rejected.** One could argue prop exclusion is already implied by
002 `offsetting_transfers_excluded` — legs paired off *"before any net flow is computed"* — since a
market maker's round trip is the same economic non-event the netting rule exists to remove, escaping
only because the rule matches identical `(symbol, date, quantity, price)`. That argument has real
force on *intent*. It fails on *mechanism*: the registered rule is a fully specified, data-driven
predicate requiring no judgement, whereas a prop-desk list is judgement all the way down. Extending
the former's intent via the latter's method is a new design, not a repair.

### 4d. Quantity weighting using the already-loaded `net_qty` -> **FEATURE is registered; the FORM
is not. New preregistration required before any reportable run.**

The feature is unambiguously registered. 002 `deal_feature_rules.features` includes:

> *"net disclosed flow excluding transfers"*

and `net_qty` is already selected by `_DEALS_SQL` (line 193) and then **discarded** — `_deal_tilt`
reads only `buying_clients` and `selling_clients`. So wiring it in *completes* a registered feature
rather than adding one. To that extent **no new study_id is needed to justify the feature**.

But the **functional form is registered nowhere**: how quantity maps to magnitude (linear? log?
normalised by turnover or free float?), its scale, its cap. Choosing that now, with
`+0.2189 pp / CI [0.0000, +0.5104] / INCONCLUSIVE` in hand, is a post-hoc specification search. A
weighting scale *is* a threshold in effect, and `failure_policy` forbids reselecting a threshold
after seeing results. **Ruling: in scope as a feature, out of scope as a free parameter. It needs a
new registered config (new study_id) that writes the form down before the run.**

The same ruling applies to `max_deal_tilt` itself. It is unregistered (§4.0), so correcting an
evidently mis-scaled bound is legitimate in principle — but the replacement value must be fixed by a
rule stated **in advance** (e.g. a stated fraction of the realised boundary-gap distribution), never
by trying values and keeping the one that improves the increment.

### 4e. The four unimplemented registered features -> **feature set needs no new study_id;
parameterisation does.**

Traced every deal field the evaluator consumes:

```
193:       sum(net_qty)                                   AS net_qty,        <- selected, DISCARDED
194:       sum(buying_clients)                            AS buying_clients, <- used
195:       sum(selling_clients)                           AS selling_clients,<- used
196:       count(*) FILTER (WHERE NOT pure_transfer_day)  AS active_days     <- selected, DISCARDED
289:    buy = int(row.get("buying_clients") or 0)
290:    sell = int(row.get("selling_clients") or 0)
```

`had_block`, `had_bulk`, `gross_value_inr`, `qty_bought`, `qty_sold`, `traded_percent` and `price`
are never selected at all. Against 002's registered six:

| registered feature | status |
|---|---|
| deal intensity vs turnover and free float | **NOT IMPLEMENTED** (no turnover or free-float term exists) |
| net disclosed flow excluding transfers | netting applied in the view; `net_qty` loaded and **discarded** — magnitude carries no flow quantity |
| repeat buying by same client / independent clients over fixed lookbacks | **NOT IMPLEMENTED** (and §1e shows the two are actively conflated) |
| deal price vs market price | **NOT IMPLEMENTED** (`price` never selected) |
| distinct buying clients | implemented only as a **sum of per-day** distinct counts (§1e) |
| block vs bulk split | **NOT IMPLEMENTED** (`had_block`/`had_bulk` never selected) |

Because 002 already names all six, implementing them **does not change the registered design**. But
every one needs a functional form that 002 does not specify, so §4d applies to each. And a Study C
carrying six features instead of one is materially a different model from the one that produced
+0.2189 pp. **Ruling: new study_id with the full feature set and all parameters written down.**

---

## 5. Recommended disposition

### 5.0 The overriding constraint

002 `failure_policy`:

> *"if the C-vs-B increment is not positive out of sample, deals are retained as market-intelligence
> CONTEXT and must not influence the score."*

The increment is +0.2189 pp with CI **[0.0000, +0.5104]** — a lower bound of exactly zero, against
001's review floor of 12 effectively independent blocks with only 9 available. The run's own verdict
is INCONCLUSIVE. **The deal feature is not promotable today regardless of any repair below, and
Study C stays in SHADOW MODE.** Nothing in this audit changes that, and no repair should be
presented as moving it closer to promotion.

### 5.1 Legitimate to change now (defect repairs inside 002)

All four move the code toward the registered text; none reselects a horizon, subset or threshold;
none burns a holdout, because no confirmatory run exists.

1. **Symmetric confidence** (§4a) — key the damping on the dominant side's distinct client count, or
   on a data-quality field as 001 does. Not on the buy count.
2. **Window-level distinct client counts** (§4b) — replace `sum(buying_clients)` with a window-level
   `count(DISTINCT client_name)` per side. Removes 4 measured sign flips and a 0.6788 max tilt error.
3. **Remove the dead clamp or make it real** (§1b) — `max(-max_tilt, min(max_tilt, ...))` can never
   bind. Either delete it as misleading, or state the operative range
   `[-0.3 * max_tilt, +max_tilt]` honestly in the docstring.
4. **Disclose the coverage limitation.** 002 `data_source.vendor_cap` already requires the 200-row
   cap *"be reported as a coverage limitation"*. The alphabetical truncation is a second, far larger
   limitation of the same kind: 4,963 of 6,873 eligible symbol-dates were **never asked**. It
   belongs in the same disclosure, and the correct wording is "never asked", not "no institutional
   interest".

Conditions on all four: re-run paired, keep `stage = 'exploratory'`, and report before-and-after
side by side. The repaired result is a **new exploratory observation, not a corrected verdict.**

### 5.2 Must wait for a new preregistration (new study_id + fresh holdout)

5. **Entity / counterparty classification** (§4c) — the curated list is a researcher degree of
   freedom and it changes 57% of consumed legs. Preregister the list itself, by name, before any run
   that uses it.
6. **Quantity / net-flow weighting** (§4d) — feature registered, functional form not.
7. **The four unimplemented registered features** (§4e) — registered, unparameterised.
8. **Any change to `max_deal_tilt`** (§4d) — unregistered, but it is a threshold; fix it by a rule
   stated in advance, inside the new registration.
9. **Any re-reading of the C-vs-B verdict** as anything other than INCONCLUSIVE.

### 5.3 Sequencing note

The ingest repair (§0a) is the highest-value change already in flight and it is **not** a design
change — it fixes "never asked". It should complete (423 of 984 candidates remain) **before** the
new study is registered, because every calibration decision in §5.2 depends on the realised tilt
distribution, and that distribution is still moving: the fire rate has gone 2.66% -> 4.39% at 57%
completion. Registering tilt bounds against a 57%-complete feed would bake in a parameter chosen on
partial data.

---

## 6. UNVERIFIED

- **UNVERIFIED: whether the Trendlyne `bulblockdeal` payload carries a counterparty category field
  at all.** `deals.py`'s `_FIELD_MAP` has no category key and `_header_order()` reads headers from
  the payload, so a category column present in the feed would be **silently dropped**. I did not
  make a live API call because the daily allowance is shared and the ingest-repair agent is actively
  consuming it. `nidp.insider_sast` has a `client_category` column but 0 rows, so the sibling feed
  from the same vendor tool gives no evidence either way. Next step: one diagnostic call printing
  `_header_order()` for a single symbol.
- **UNVERIFIED: the true prop/market-maker share.** 36.90% (cohort A) / 57.08% (consumed) are
  **name-pattern lower bounds** from 22 patterns matching 29 of 3,172 distinct client names. No
  classification exists in the data, so the real share is higher by an unknown amount. The
  classification-free round-trip signature (46.88% / 64.88%) is a second, independent lower bound.
- **UNVERIFIED: the canonical prereg digest.** `prereg_sha256` is computed over the canonicalised DB
  `config` (`json.dumps(..., sort_keys=True, separators=(",", ":"))`, evaluator line 73), **not** the
  contract file bytes, so the file digests I recorded
  (`9d3cde48...` / `8b2ba2a8...`) do not and should not equal the registered values. I did not
  recompute the canonical digest — that is the study-integrity audit's scope and its report is owned
  by another agent. Indirect evidence the gate passed: `load_study()` aborts on mismatch (line 75)
  and both anchor runs finished `status = 'OK'`.
- **UNVERIFIED: the consumed-leg count against the diagnosis's figure.** My consumed set is 2,083
  distinct legs (distinct on symbol/date/client/action/qty/price/exchange, joined to eligible
  symbols per date); the diagnosis cited 1,212 consumed rows. I did not reconcile the two
  definitions. My funnel figures (498 / 363 / 180 / 183) match the diagnosis exactly, so the
  difference is in leg-level de-duplication, not in the symbol-date population.
- **Counterfactuals are arithmetic, not runs.** The symmetric-confidence, prop-excluded and
  post-repair slot figures are read-only computations over stored Model-B scores. No evaluator run
  was launched, no `smart_money_study_runs` row written, no frozen config touched.
- **Snapshot caveat.** Cohort-B population figures reflect `nidp.trendlyne_deals` at
  2026-10-22 09:26:42 IST with the ingest 57% complete. They will move as it finishes.

---

## 7. Verification command and real output

No product code was edited by this audit — the only file created is this report. Test suite run to
confirm the baseline has not moved:

```
$ docker exec -w /app/backend nidp-daas-api-staging sh -c \
    "python -m pytest nidp/tests -q -p no:cacheprovider" 2>&1 | tail -8
FAILED nidp/tests/test_failing_feeds_golden.py::test_fno_bhavcopy_avro_roundtrip_real_rows
FAILED nidp/tests/test_failing_feeds_golden.py::test_fno_bhavcopy_db_columns_match_migration
FAILED nidp/tests/test_feed_registry_drift.py::test_every_recoverable_daily_feed_is_scheduled
FAILED nidp/tests/test_pipeline_stages_endpoint.py::TestEndpoint::test_weekend_produces_no_stale_stage
FAILED nidp/tests/test_pipeline_stages_endpoint.py::TestEndpoint::test_classify_is_backlog_not_stale
FAILED nidp/tests/test_pipeline_stages_endpoint.py::TestEndpoint::test_discover_is_healthy
FAILED nidp/tests/test_pipeline_stages_endpoint.py::TestDegradation::test_missing_holiday_table_does_not_blank_the_panel
51 failed, 1291 passed, 5 skipped, 23 warnings in 11.27s
```

Baseline is 51 failed / 1281 passed / 5 skipped. Failures unchanged at **51**; passes rose
1281 -> 1291 from other agents' new tests. **Not made worse.**

## Verdict: PASS
