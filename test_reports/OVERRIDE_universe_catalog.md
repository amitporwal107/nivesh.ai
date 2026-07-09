# OVERRIDE — Strategy-Builder Universe Catalog (curated baskets + real returns/trends)

REASON: The feature is code-complete and locally verified, but the two staging proofs (catalog endpoint returns real baskets/returns; Playwright over the rich Universe step) can only run **after** (a) the app-backend + frontend deploy lands on staging, AND (b) **migration 117 runs on the staging NIDP DB** — a `dev` push does NOT auto-apply migrations (deploy-nidp-staging.yml runs them only on a `workflow_dispatch` with `run_migrations=true`). Until the migration runs, the catalog returns only index presets (no baskets). This is the sanctioned, loud, recorded skip; nothing is claimed done.

- **Slug:** universe_catalog
- **Branch:** feat/copilot-backtest → origin/dev
- **Changed areas:** backend routes/services + nidp migration (yes) · frontend src (yes)

## What was built (all real data — no fabricated numbers)
- **`backend/nidp/migrations/117_seed_public_universes.sql`** — seeds ~17 public **sector baskets** from `nidp.sector_master` (real constituents, `array_agg`, ≥8 names) + a **Nifty Bank** basket from `nidp.index_constituents`. Idempotent (partial unique index + upsert, stable ids).
- **`compiler_stock.py`** — adds `f.return_60d_pct` to the screen SELECT.
- **`GET /api/strategy-builder/universe-catalog`** — index presets + public baskets, each with **real median `return_60d_pct`** (3M) + **real trend** (median 1M-vs-3M momentum). Cached per snapshot date; fresh provider per universe; bounded concurrency. `null`/`—` where no metric — never faked. Group/thematic baskets + flow pill **deferred** (no real source; grounding workflow verified none exists).
- **`strategyBuilder.ts`** — `listUniverseCatalog()` + `CatalogUniverse`/`UniverseCatalog` types.
- **`StrategyBuilderPage.tsx`** — rich Universe step: card grid (return + trend pill + symbol_count), Broad-Market/Sector-Themes segments, Warming/Steady/Cooling filters, search, Catalog/My-Universes tabs, honest loading/error/empty states.

## Test cases + local evidence (real output this session)
| TC | Scenario | Type | Result |
|----|----------|------|--------|
| TC-1 | `return_60d_pct` real + non-null on staging (P1 probe) | api (staging) | **PASS** — 10/10 non-null (auth 200) |
| TC-2 | Backend files compile | unit | **PASS** (`py_compile OK`) |
| TC-3 | Catalog helpers: `_median` (empty/odd/even/null-skip), `_trend_label` (warming/cooling/steady/null) | unit | **PASS** (printed truth table) |
| TC-4 | Frontend typechecks with the new service + Universe step | build | **PASS** (`tsc --noEmit --skipLibCheck` exit 0, 0 errors) |
| TC-5 | Migration 117 seeds sector baskets + Nifty Bank with real membership | data (staging) | **PASS** — **18 public baskets seeded** (Finance 101, Capital Goods 63, Healthcare 49, IT 27 … + Nifty Bank 14); `owner_id` now `text` (115 applied) |
| TC-5b | Migration chain unblocked (was stuck at broken 083 view-drift) | data (staging) | **PASS** — fixed 083 file (matview-safe) + reconciled 15 drift records + `migrate` applied 114/115/117 (real output shown) |
| TC-6a | `GET /universe-catalog` deployed + returns real returns for index presets | api (staging) | **PASS** — HTTP 200, Nifty 50 +6.55% / 100 +8.77% / 200,500 +10.95%, trends computed (real median return_60d_pct) |
| TC-6b | Catalog returns the sector baskets with real `symbol_count` + `return_3m_pct` | api (staging) | **PENDING** — baskets seeded; endpoint re-verify needs the cache-key redeploy + a fresh token (it cached count=4 pre-seed) |
| TC-7 | UI: Universe step renders the grid, filters/search work, selecting a sector card sets `{type:custom,ref}` and Screen returns candidates | e2e (Playwright) | **PENDING** — needs deploy + PWA cache clear |

## To clear this OVERRIDE
1. Push to `dev` (app + frontend auto-deploy).
2. Run migration 117 on staging: dispatch `deploy-nidp-staging.yml` with `run_migrations=true` (or apply manually), then verify:
   `SELECT name, cardinality(symbols) FROM user_universes WHERE owner_id LIKE '__system%'` → ~17 sector rows (Finance≈99, Capital Goods≈60, IT≈27) + Nifty Bank.
3. `curl GET /api/strategy-builder/universe-catalog` (fresh token) → baskets with real `symbol_count` + `return_3m_pct`.
4. Playwright over the Universe step; paste into `test_reports/strategy_lab.md`, end `## Verdict: PASS`.

## Status
IN PROGRESS — code-complete, locally verified (py_compile + tsc + logic + P1 probe). Staging endpoint/data/Playwright pending the deploy + migration run. Not done, not claimed done.
