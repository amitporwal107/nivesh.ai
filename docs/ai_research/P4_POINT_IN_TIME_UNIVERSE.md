# Point-in-time backtest universe (Phase 4.2) and the index-history decision

**Status:** built on `feat/p4-research-hardening`, 2026-10-27. Code: `backend/services/strategy_engine/liquid_universe.py`
(rule `liquid-eq-v1`), wired into both market-data providers (`market_data.py`). Tests: `backend/tests/test_liquid_universe.py`.

## 1. The problem
- A DSL backtest on an index universe (Nifty 50/100/200/500) used **the latest constituent snapshot for every past date**
  (`universe_basis: latest_snapshot`). The DaaS lookup matches a snapshot date exactly, and history does not exist.
- So a stock that left the index, was merged or was delisted is missing from the past. Every stored staging backtest
  had this bias (C study Q5).
- Staging holds 4 snapshots per broad index, all from this month (read-only, 2026-10-27):

```
SELECT index_name, as_of_date, count(*) FROM nidp.index_constituents GROUP BY 1,2 ORDER BY 1,2;
 Nifty 50   | 2026-10-12, 2026-10-13, 2026-10-20, 2026-10-22 | 50 each
 Nifty 100  | same four dates                                 | 100
 Nifty 200  | same four dates                                 | 200
 Nifty 500  | same four dates                                 | 501
 (sector and thematic indices: 2026-10-20 and 2026-10-22 only; Nifty Total Market: the four dates, 755)
```

## 2. Rule `liquid-eq-v1` (`{"type": "market", "ref": "LIQUID_EQ"}`)
On each session d, a symbol is a member when all of these hold. Only data up to and including d is used.

1. It has a series-EQ bar on d with a close and a volume, and the raw close is at least ₹20.
2. Among the 30 sessions ending at d, it has at least 20 EQ bars. The median of close × volume over its latest 20 of
   those bars is at least ₹10 crore.
3. It is not an ETF: it is not on NSE's ETF list (`nidp.security_reference_daily.is_etf`, from `eq_etfseclist.csv`, the
   latest list), and its symbol does not end in BEES or ETF.

**Why these numbers.** The floors are the Phase 4.3 study's (`P4_ADX_RS_PREREGISTRATION.md` §3). That study's
220-session minimum history was a warm-up for its own scorer. The DSL reads stored features, so this rule does not
include it.

**Sessions.** Inside a window, the engine's calendar (the feature-store dates). Before the window, the 29 most recent
days that have EQ prices. On staging, prices start 2024-04-01 and features start 2025-12-29, so a window starting
2025-12-29 still gets a full lookback.

**Survivorship.** Membership comes from each date's own prices, so a later-delisted or renamed stock is a member while it
traded. Traded value is computed on the raw bar; a split leaves close × volume unchanged.

**Default.** It is the default for "all stocks" universes:
- the strategy a screen builds (`screen_bridge._DEFAULT_UNIVERSE`, previously Nifty 500);
- the first catalog card, flagged `default`;
- the default selection in both builder screens.

Index universes stay available. They keep `universe_basis: latest_snapshot` and now carry a `universe_warning`, which
the UI shows as an alert.

**Data access.**
- The DaaS backend makes one existing `GET /prices/eod?on=&series=EQ` call per session (window plus lookback;
  about 0.4–0.6 s each on staging). It then reads features and bars only for the members' union, and reads NSE's ETF
  list once from `/features/scan-snapshot`.
- A failed price read fails the run. An unreadable ETF list is reported (`universe_report.etf_list`), and the name rule
  still applies.
- There is no NIDP change. The SQL backend reads the same tables directly.

**Verified on staging (read-only, 2026-10-27).** The engine's rule on exported rows matched an independent SQL
implementation exactly on four dates:

```
date        EQ priced  members (engine)  members (SQL)  identical
2025-06-02    2090        688               688          True
2025-12-29    2378        623               623          True
2026-04-15    2456        734               734          True
2026-10-23    2706        780               780          True
```

- Of the 688 members on 2025-06-02, 245 are not in today's Nifty 500, and 22 no longer trade as EQ under the same
  symbol: CIGNITITEC, DHANI, E2E, GANESHHOUC, GSPL, GUJGASLTD, HEG, HFCL, ICICIPRULI, INFIBEAM, ITDCEM, IWEL,
  JBCHEPHARM, LTIM, MANGCHEFER, MOREPENLAB, PEL, RELINFRA, SEQUENT, SGLTL, SWANENERGY and TATAMOTORS (renames, mergers,
  demergers, series moves). A today's-list universe silently drops all of them.
- Before NSE's ETF list was added, the name rule alone let 10 (2025-06-02) to 19 (2026-10-23) ETFs through, for example
  GOLD1, LIQUIDCASE and MON100. All had feature rows a strategy could have bought.

**Known limits.**
- A renamed symbol restarts its 20-bar history under the new name: LTIM → LTM on 2026-02-27 is out for about 20
  sessions. The fix is to join by ISIN, a later rule version.
- A fund delisted before NSE's current ETF list is caught only by the name rule.

## 3. Owner decision: importing NSE's historical index constituents

Nothing was imported, and no historical constituents were invented. Until an import is done and validated, index
universes stay labelled `latest_snapshot (survivorship bias)`.

**What exists in the repo.**
- `nidp/services/index_constituents` downloads the *current* list per index from `INDEX_CONSTITUENT_URLS`
  (`nidp/shared/config.py:141`: nsearchives `ind_nifty50list.csv` and others, with six sector lists from niftyindices.com).
- It runs monthly: `deploy/cloudpe/nidp/nidp-staging.cron:54`, `30 6 1 * *`. So history grows by one snapshot a month
  from now on. It cannot reach back.

**Possible sources for the past.** None was fetched for this note, so their availability is UNVERIFIED.
1. *NSE Indices' index-change announcements.* Press releases and circulars for the semi-annual reconstitutions
   (effective late March and late September) and for ad hoc replacements (mergers, delistings, F&O-driven changes).
   Each lists inclusions and exclusions with an effective date.
2. *Archived constituent CSVs.* The same `ind_nifty*list.csv` files captured on past dates by a third-party archive. Only
   usable if each capture's date is certain.
3. *A vendor's point-in-time constituent history.* Paid. The owner chooses the vendor.

**Method (source 1).**
- Start from a verified snapshot, the staging one of 2026-10-12.
- Walk backwards through the dated inclusion/exclusion events to rebuild the membership after each event, back to
  2024-04-01 (the price history's start). Store one snapshot per effective date.
- Validate:
  - each rebuilt snapshot has exactly the index size (50/100/200/500);
  - every member has EQ prices on the effective date;
  - the forward walk from the oldest rebuilt snapshot reproduces the four stored snapshots exactly;
  - symbols are joined by ISIN, because renames such as LTIM → LTM break symbol joins.

**Effort.** M–L in total:
- S to collect and parse about 5 semi-annual reviews plus ad hoc changes for four indices (two and a half years);
- M for the reconstruction and validation script with tests;
- S for the write and its review.

The announcements are PDFs, so parsing them is the main risk.

**The staging write (needs the go-ahead of §9.2).**
- Table `nidp.index_constituents`, upsert on `(as_of_date, index_name, symbol, source)` with a new
  `source = 'NSE_INDEX_HISTORY_REBUILT'`. It is distinct from `NSE_INDEX_LIST`, so a rebuilt row never overwrites a
  downloaded one and can be removed by `source`.
- Size: about 5 reviews × (50 + 100 + 200 + 500) members plus the ad hoc events ≈ 4,500–6,000 rows.
- Steps: snapshot the table first; dry run with exact row counts; apply in one transaction; rerun the validations;
  rollback is `DELETE … WHERE source = 'NSE_INDEX_HISTORY_REBUILT'`.
- After that, the DaaS provider would need the snapshot dates (`/indices/{name}/constituents` matches a date exactly
  today) to apply point-in-time membership. That is an NIDP API change, which also needs the DaaS restart.

**Recommendation.** Use the liquid universe for research now. Import index history only if a strategy must be evaluated
on an index specifically: index membership is itself a selection rule, and the liquid universe already removes
survivorship bias for "all stocks".
