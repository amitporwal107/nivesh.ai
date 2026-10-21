# Functionality Verification Report — Strategy config (table + endpoints + Bot details screen)

- **Branch:** feat/strategy-config (worktree /tmp/claude-1002/-home-deploy-nivesh-ai/5728eb40-e444-45ca-9343-e9c13da03b5a/scratchpad/wt-strategy-config, off origin/dev @ eb8add52)
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** migration on a THROWAWAY postgres:16-alpine (`pg-mig-scratch`, `--network none`); backend tests in a throwaway container from `nivesh/backend:staging` with the tree mounted read-only, no network. Staging DB SELECT-only. Branch NOT deployed to staging.
- **Changed areas:** backend routes/services: YES · frontend src: YES

## Summary

Implements `strategy_config` + `GET/PUT /strategies/{id}/config` + `GET /config-schema` + the
"Bot details" screen, per `docs/STRATEGY_BUILDER_CONFIG_SPEC.md` §4.3–4.4, §5, §8, §8b.

24 of 30 authored cases now PASS with real output, plus 2 regression checks. **This is still not a
PASS verdict**: TC-24…TC-29 (Playwright) have no spec yet, and the staging API cases are blocked —
see `OVERRIDE_strategy_config.md`.

**A real defect was found and fixed during verification.** TC-16 failed on the first run:
`PUT {"pyramiding": true}` returned **200** and stored `1`. Pydantic's lax mode coerces `True`→`1`
before the body reaches `NiveshConfig.validate()`, so the class's deliberate bool guard
("True is not a quantity the author chose") was bypassed at the HTTP edge. Fixed with a
`field_validator(mode="before")` on all four numeric fields that rejects `bool` prior to coercion;
TC-16 then passed. The test was not weakened to accommodate the bug.

Two deviations from the spec, both verified against the live DB:
1. Spec says `bot_config(bot_id uuid PK→bots)`. **There is no `bots` table.** The owning row is
   `public.strategies`. Table is `strategy_config(strategy_id → strategies ON DELETE CASCADE)`.
2. Spec paths `/bots/{id}/config` → `/api/strategy-builder/strategies/{id}/config`.

Scope explicitly NOT covered: screen 2 (Code editor), screen 3 (Backtests tab + drift panel), and
engine enforcement of `pyramiding` / `short_margin_pct`. The backtester is long-only and counts no
same-direction entries, so `PYRAMIDING_LIMIT`, `SHORT_MARGIN_DEPLETED` and `INSUFFICIENT_CAPITAL`
remain unreachable. Those two fields are stored only; the API response carries
`not_enforced_by_engine: ["pyramiding","short_margin_pct"]` and the screen says so in words.
`initial_capital` and `commission_pct` DO reach the engine.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Migration | applies on a DB with `strategies` present | sql | table + FK, no error | **PASS** |
| TC-2 | Migration | re-applying is a no-op | edge | exit 0 | **PASS** |
| TC-3 | Migration | deleting a strategy cascades the config row | edge | 0 rows | **PASS** |
| TC-4 | Migration | types + CHECK bounds match `config.py` | sql | exclusive/inclusive correct | **PASS** |
| TC-5 | Schema | `/config-schema` ranges equal `config.py` constants | unit | derived | **PASS** |
| TC-6 | GET | no stored row → AI_DEFAULTS, `stored:false` | api | 200 | **PASS** |
| TC-7 | GET | stored row → stored values, `stored:true` | api | 200 | **PASS** |
| TC-8 | GET | unknown strategy → 404 | failure | 404 | **PASS** |
| TC-9 | GET | another user's non-template → 403 | failure | 403 | **PASS** |
| TC-10 | GET | no auth → 401 | failure | 401 | **PASS** |
| TC-11 | PUT | valid body persists; response echoes | api | 200 | **PASS** |
| TC-12 | PUT | second PUT upserts in place | api | 1 row | **PASS** |
| TC-13 | PUT | capital 0 / −1 / >1e10 → 422 naming field | failure | 422 | **PASS** |
| TC-14 | PUT | commission 5.0 ok, 5.01 → 422 | edge | boundary | **PASS** |
| TC-15 | PUT | short margin 0 → 422, 100 ok | edge | boundary | **PASS** |
| TC-16 | PUT | pyramiding −1 → 422, `true` → 422, 0 ok | edge | bool rejected | **PASS** (after fix) |
| TC-17 | PUT | unknown field → 422 naming it, nothing stored | failure | refused | **PASS** |
| TC-18 | PUT | non-owner on a public template → 403 | failure | 403 | **PASS** |
| TC-19 | PUT | one `strategy_audit` row, action CONFIG_UPDATE | api | 1 row | **PASS** |
| TC-20 | Backtest | body omits capital → stored value reaches engine | api | stored | **PASS** |
| TC-21 | Backtest | body supplies capital → body wins | api | body | **PASS** |
| TC-22 | Backtest | commission 0.05 → `slippage_pct` 0.0005 | unit | /100 | **PASS** |
| TC-23 | Backtest | no stored config → AI_DEFAULTS, run succeeds | edge | 1,000,000 | **PASS** |
| TC-R1 | Regression | `FIELD_RANGES` refactor preserves behaviour | unit | suites green | **PASS** |
| TC-R2 | Regression | new routes register | unit | 3 paths | **PASS** |
| TC-30 | Typecheck | `tsc --noEmit` clean after step renumbering | unit | 0 errors | **PASS** |
| TC-24…TC-29 | UI | fields, validation copy, stepper, panel, PUT gating | e2e | per row | **NOT RUN** |
| — | Staging | endpoints exercised against the deployed API | api | — | **NOT RUN** |

## API / Endpoint Tests

### TC-5…TC-23 — endpoint suite (throwaway container, no network, no DB)

```
$ sudo docker run --rm --network none -v <worktree>:/work:ro -w /work/backend \
    -e MONGO_URL=... -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder \
    nivesh/backend:staging python -m pytest tests/test_strategy_config.py -q -p no:cacheprovider
32 passed, 1 warning in 6.58s
```

First run of the same suite, before the bool fix — the genuine failure, unedited:

```
FAILED tests/test_strategy_config.py::test_pyramiding_rejects_a_bool
E       AssertionError: {"strategy_id":"11111111-1111-4111-8111-111111111111","stored":true,
        "schema_version":1,"initial_capital":1000000.0,"commission_pct":0.05,"pyramiding":1,
        "short_margin_pct":100.0,...,"not_enforced_by_engine":["pyramiding","short_margin_pct"]}
E       assert 200 == 422
1 failed, 31 passed, 1 warning in 6.64s
```

### Full backend regression (new suite + all ai_trader suites)

```
$ ... python -m pytest tests/test_strategy_config.py tests/test_ai_trader_config_risk.py \
    tests/test_ai_trader_strategy.py tests/test_ai_trader_execution.py tests/test_ai_trader.py \
    -q -p no:cacheprovider
486 passed, 1 warning in 41.19s
```
Result: **PASS** — the `config.py` `FIELD_RANGES` extraction and the route changes broke nothing.

### TC-1 / TC-2 — migration applied, then re-applied (throwaway postgres, NOT staging)

```
--- first apply ---
SET
CREATE TABLE
--- second apply (must be a no-op, no error) ---
SET
psql:/tmp/024.sql:41: NOTICE:  relation "strategy_config" already exists, skipping
CREATE TABLE
exit=0
```

### TC-4 — structure and CHECK constraints

```
                        Table "public.strategy_config"
      Column      |           Type           | Nullable | Default
------------------+--------------------------+----------+---------
 strategy_id      | uuid                     | not null |
 schema_version   | smallint                 | not null | 1
 symbols          | text[]                   |          |
 initial_capital  | numeric(18,2)            | not null |
 commission_pct   | numeric(6,4)             | not null |
 pyramiding       | smallint                 | not null |
 short_margin_pct | numeric(5,2)             | not null |
 updated_at       | timestamp with time zone | not null | now()
Indexes:
    "strategy_config_pkey" PRIMARY KEY, btree (strategy_id)
Check constraints:
    "strategy_config_commission_pct_check" CHECK (commission_pct >= 0 AND commission_pct <= 5)
    "strategy_config_initial_capital_check" CHECK (initial_capital > 0 AND initial_capital <= 10000000000)
    "strategy_config_pyramiding_check" CHECK (pyramiding >= 0)
    "strategy_config_short_margin_pct_check" CHECK (short_margin_pct > 0 AND short_margin_pct <= 100)
Foreign-key constraints:
    "strategy_config_strategy_id_fkey" FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
```
Bounds match `config.py`: capital and short margin exclusive at 0, commission inclusive.

### TC-3 — CHECK enforcement and FK cascade (real, unedited)

```
 rows before delete: 1
ERROR:  violates check constraint "strategy_config_initial_capital_check"
ERROR:  violates check constraint "strategy_config_commission_pct_check"
ERROR:  violates check constraint "strategy_config_pyramiding_check"
ERROR:  violates check constraint "strategy_config_short_margin_pct_check"
DELETE 1
 rows after cascade delete: 0
```

### Staging endpoint tests — NOT RUN (blocked)

```
$ curl -sk -o /dev/null -w '%{http_code}' https://staging.niveshcopilot.com:8443/api/strategy-builder/config-schema
404
$ curl -sk -o /dev/null -w '%{http_code}' https://staging.niveshcopilot.com:8443/api/strategy-builder/templates
401
```
404 on the new route vs 401 on an existing one proves the server is healthy and the branch is simply
not deployed. See `OVERRIDE_strategy_config.md`.

## UI / Playwright Tests

### TC-30 — typecheck, pinned to a stable file

```
$ md5sum .../StrategyBuilderPage.tsx  -> 25b9edabb7df
$ sudo docker run --rm --network none -v <worktree>/frontend-v5:/app \
    -v wl-fe-node-modules:/app/node_modules -w /app \
    mcr.microsoft.com/playwright:v1.47.0-jammy bash -lc 'npx tsc --noEmit -p tsconfig.json'
tsc exit=0
$ md5sum .../StrategyBuilderPage.tsx  -> 25b9edabb7df   (unchanged — result is pinned)
```
Result: **PASS**. An earlier `tsc` run this session was **retracted**: the file changed during that
run (`d21bd986` → `25b9edab`), so it tested a version that no longer exists.

### TC-24…TC-29 — NOT RUN

`frontend-v5/e2e/tests/strategy-config-bot-details.spec.ts` does not exist; the agent authoring it had
not finished. **No Playwright run has happened.** Not asserted, not claimed.

## Data Correctness

- Staging (read-only): `SELECT to_regclass('public.strategy_config') IS NOT NULL` → **False**.
  Correct — the migration has not been applied there and must not be without authorisation.
- Staging (read-only): `portfolio_ingestion.schema_migrations` holds 4 rows (`001`…`004`).
  `post_deploy_migrate`'s own `schema_migrations` does not exist, i.e. the `backend/migrations/`
  series has never run on this database. This changes how the rollout must be done — see override.
- Throwaway DB after the cascade test: `strategy_config` 0 rows, `strategies` 0 rows.

## Final run after the defect-fix round (supersedes the per-case notes above)

An adversarial review found 14 located defects (7 backend, 7 frontend); all were fixed on this
branch. The numbers below are the state that was committed, and every one is pinned by identical
file hashes before and after its run.

```
$ ... python -m pytest tests/test_strategy_config.py tests/test_ai_trader_config_risk.py \
    tests/test_ai_trader_strategy.py tests/test_ai_trader_execution.py tests/test_ai_trader.py -q
501 passed, 1 warning in 44.90s
```

```
$ npx playwright test e2e/tests/strategy-config-bot-details.spec.ts --project=desktop-chrome
  9 passed (29.3s)
```
Nine, not six: the fix round added TC-31 ("a failed config save abandons the run — it is never run
half-applied") and TC-32 ("Save with an invalid Bot-details field warns and writes nothing"),
covering two of the defects.

```
$ npx tsc --noEmit -p tsconfig.json
tsc exit=0        (StrategyBuilderPage.tsx 1fc6bcdf3c before AND after)
```

### Migration re-tested on a FRESH throwaway postgres after the fix round

```
--- apply #1 ---      DO / CREATE TABLE
--- apply #2 ---      DO / CREATE TABLE / NOTICE: relation "strategy_config" already exists, skipping
SHOW search_path ->   "$user", public        (default — the SET no longer leaks, defect D6 fixed)
pyramiding 40000 ->   ERROR: smallint out of range   (and the class now 422s it before the DB sees it)
```

### Migration APPLIED TO THE STAGING DB (authorised by the user this turn)

```
BEFORE:  strategy_config: None | strategies rows: 4
APPLY :  applied OK                        (024_strategy_config.sql, md5 d951f3a945)
AFTER (read back from the staging database):
  strategy_id       uuid            null=NO
  schema_version    smallint        null=NO
  symbols           ARRAY           null=YES
  initial_capital   numeric(18,2)   null=NO
  commission_pct    numeric(6,4)    null=NO
  pyramiding        smallint        null=NO
  short_margin_pct  numeric(5,2)    null=NO
  updated_at        timestamptz     null=NO
  strategy_config_commission_pct_check    -> CHECK (commission_pct >= 0 AND commission_pct <= 5)
  strategy_config_initial_capital_check   -> CHECK (initial_capital > 0 AND initial_capital <= 10000000000)
  strategy_config_pyramiding_check        -> CHECK (pyramiding >= 0 AND pyramiding <= 32767)
  strategy_config_short_margin_pct_check  -> CHECK (short_margin_pct > 0 AND short_margin_pct <= 100)
  strategy_config_strategy_id_fkey        -> FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
  strategy_config_pkey                    -> PRIMARY KEY (strategy_id)
  rows: 0
  search_path after apply: "$user", public
```
Data test: 0 rows written; `strategies` untouched at 4 rows; no other table altered.

### Delivery state

- Commit `9143e0b7`, 13 files, +2932/−43. Pushed as `feat/strategy-config`.
- **PR #279** open against `dev`, `mergeable: True clean` — https://github.com/amitporwal107/nivesh.ai/pull/279
- **Not merged.** The merge API call was denied by the Claude Code permission classifier (writes to
  `dev`). `origin/dev` is still `eb8add52`. Not worked around.
- **Not deployed.** `/opt/nivesh-staging/repo` still needs a pull + rebuild.

## Staging API endpoint tests — RUN, against the deployed code

PR #279 was merged (`merged_at 2026-10-21T15:45:22Z`, `origin/dev` = `60e5ccb5`) and
`/opt/nivesh-staging/repo` redeployed to that commit. The user supplied a staging `session_token`.
Token validated first, so a 200 cannot be mistaken for an unauthenticated pass-through:

```
templates (with cookie)  -> HTTP 200
templates (no cookie)    -> HTTP 401
```

Real `curl` against `https://staging.niveshcopilot.com:8443`, strategy
`5acc4fab-4449-4d56-96ed-a936be65d10a` ("Simple Momentum (Phase-1 friendly)"), owned by that user:

```
##### TC-5 GET /config-schema #####
HTTP 200 | {"$schema":"https://json-schema.org/draft/2020-12/schema","title":"Strategy config (Bot details)",
            "schema_version":1,"type":"object","additionalProperties":false,"required":[],"properties":{...}}

##### TC-6 GET config, no stored row #####
HTTP 200 | {"strategy_id":"5acc4fab-...","stored":false,"schema_version":1,"initial_capital":1000000.0,
            "commission_pct":0.05,"pyramiding":0,"short_margin_pct":100.0,"symbols":[],
            "symbols_source":"unavailable","updated_at":null,...}

##### TC-8 unknown strategy #####
HTTP 404 | {"status":404,"error":"NOT_FOUND","code":"RES-001","message":"strategy not found",...}

##### TC-10 no auth #####
HTTP 401
```

Result: TC-5, TC-6, TC-8, TC-10 **PASS on the deployed API**.

### The deployed schema proves the fixes shipped

```
initial_capital   {"exclusiveMinimum": 0.0, "maximum": 10000000000.0, "multipleOf": 0.01,   "default": 1000000.0, "owner": "code"}
commission_pct    {"minimum": 0.0,          "maximum": 5.0,           "multipleOf": 0.0001, "default": 0.05,      "owner": "bot_details"}
pyramiding        {"minimum": 0,            "maximum": 32767,                               "default": 0,         "owner": "bot_details"}
short_margin_pct  {"exclusiveMinimum": 0.0, "maximum": 100.0,         "multipleOf": 0.01,   "default": 100.0,     "owner": "bot_details"}
```
Four review defects are visible as fixed, live: `multipleOf` is the NUMERIC scale (D1, the
500-instead-of-422), `pyramiding maximum 32767` is its SMALLINT domain (D2), `exclusiveMinimum` vs
`minimum` matches `config.py` exactly, and **`symbols` is absent from `properties`** (D3, the key the
schema used to advertise and PUT then rejected). Every bound equals `config.py`'s `FIELD_RANGES`.

### Data test (staging, SELECT only)

```
strategy_config rows : 0
strategies rows      : 4
CONFIG_UPDATE audits : 0
```
Consistent with the write path never having been exercised on staging — see the limitation below.

## Known limitation — the staging WRITE path was permission-denied

Every `PUT .../config` call was refused by the Claude Code permission classifier
(`[Modify Shared Resources]`), including the ones that store nothing and only assert a 422. I did not
work around the denial. So on staging the read path is proven live and the write path is not.

The write path is instead covered by **19 endpoint cases against the real FastAPI router** via
TestClient (`test_strategy_config.py`, part of the 501): upsert, partial-body merge, 403 for a
non-owner on a public template, the `CONFIG_UPDATE` audit row, every boundary, and each of the four
coercion holes the review found (`0.004`, `40000`, `true`, `"3"`). Those run offline against the same
code now deployed. To close it on staging, a permission rule for the PUT is needed; the exact calls
are listed in this report's history.

## Verdict: PASS

Scope: the `strategy_config` table, the three config endpoints, and the Bot details screen.
501 backend tests, 9 Playwright cases, `tsc --noEmit` clean, the migration applied to staging with its
structure read back from the database, and four endpoint cases verified against the deployed staging
API with a validated session token. 14 reviewer-found defects fixed, four of them confirmed fixed on
staging. The single gap — the staging write path — is a permission denial, documented above rather
than skipped, with the equivalent coverage named.

Out of scope and NOT built: screen 2 (code editor), screen 3 (backtests tab + drift panel), and
engine enforcement of `pyramiding` / `short_margin_pct`.
