# Deal-feature contract audit — registered vs implemented design for NIDP-SM-VALIDATION-002

**Date:** 2026-10-22
**Scope:** READ-ONLY audit. Does the Study C deal overlay, as run, implement the feature design
registered in the frozen contract `NIDP-SM-VALIDATION-002`? Nothing was changed: no code, no DB
write, no re-run, no edit to either frozen contract. This report is the only file created.
**Database:** `nidp_staging` via `~/.config/nivesh/nidp-psql.sh`. Every number below is real query
output obtained this session.
**Decision this feeds:** whether a re-run continues the existing exploratory study or needs fresh
preregistration. **This audit does not make that call** — it supplies the evidence.

---

## 0. What I audited, and how I pinned it against a file another agent is editing

`backend/nidp/services/smart_money_study/evaluator.py` is being modified concurrently by another
agent (`git diff --stat` at the start of this audit: `280 ++++, 272 insertions(+), 8 deletions(-)`).
I snapshotted it before reading and did all citation against the snapshot, then proved the deal path
is unchanged by that in-flight work.

```
$ sha256sum .../scratchpad/evaluator.snapshot.py
d72c61937a643f1b16657186f37408ac0935097c03b5845a4422e345100803d5
$ git diff --stat backend/nidp/services/smart_money_study/evaluator.py
 .../nidp/services/smart_money_study/evaluator.py   | 280 ++++++++++++++++++++-
 1 file changed, 272 insertions(+), 8 deletions(-)
```

The two functions that constitute the entire deal path are byte-identical at the committed HEAD
(`00e7248b`), in the working tree, and at the commit the reported run recorded:

```
$ diff <HEAD:121-130> <worktree:191-200>   && echo ...
DEALS_SQL: HEAD == working tree
$ diff <HEAD:140-152> <worktree:283-295>   && echo ...
_deal_tilt: HEAD == working tree
$ diff <72a9243c:140-152> <worktree:283-295> && echo ...
_deal_tilt: run commit 72a9243c == working tree
$ git show 72a9243c:...evaluator.py | sed -n '121,130p' | diff - <worktree:191-200> && echo ...
_DEALS_SQL: run commit 72a9243c == working tree
```

Line numbers below are **working-tree** line numbers from that snapshot. The equivalent committed
locations are `evaluator.py:121-130` (`_DEALS_SQL`) and `evaluator.py:140-152` (`_deal_tilt`).

The run under discussion, read from the DB rather than from the brief:

```
run_id      | a4d964f7-3ae9-48de-8b88-1f17da517925
study_id    | NIDP-SM-VALIDATION-002
stage       | exploratory
status      | OK
code_commit | 72a9243c6dce323c3e586be45fd6daf8f584baaf
data_cutoff | 2026-10-22
notes_head  | ... "formation_dates_considered": 9, "formation_dates_used": 9,
              "mean_paired_diff_pp": 0.2189, "ci95_pp": [0.0, 0.5104], "portfolio_n": 30,
              "portfolio_names_changed_total": 4, "prediction_rows": 45218,
              "outcome_rows": 540, "verdict": "INCONCLUSIVE", ...
```

**The repo file IS the frozen contract.** The contract the evaluator verifies lives in
`nidp.smart_money_study_config`; I dumped it and compared it to the repo JSON using the evaluator's
own canonicalisation (`json.dumps(sort_keys=True, separators=(",",":"))`, `evaluator.py:73-74`):

```
stored_canonical_sha256 = 1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838
repo_canonical_sha256   = 1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838
stored == repo          : True
registered_prereg_sha256= 1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838
digest matches registered: True
deal_feature_rules identical: True
```

So the verbatim text quoted in §1 is exactly what run `a4d964f7` re-hashed and accepted.

---

## 1. `deal_feature_rules`, quoted VERBATIM

From `backend/nidp/studies/NIDP-SM-VALIDATION-002.json`, lines 8-23, complete and unaltered:

```json
  "deal_feature_rules": {
    "bounds": "the deal contribution is bounded SEPARATELY from the holdings overlay so neither can dominate and each can be ablated independently",
    "confidence": "lower confidence where the counterparty or ultimate beneficial owner is unclear; a single-client signal is damped as the holdings overlay already does",
    "evidence_claim": "a disclosed deal evidences that a TRANSACTION occurred, never that an institution is accumulating with a bullish view",
    "features": [
      "deal intensity vs turnover and free float",
      "net disclosed flow excluding transfers",
      "repeat buying by the same client and by independent clients over fixed lookbacks",
      "deal price vs market price",
      "distinct buying clients",
      "block vs bulk split"
    ],
    "offsetting_transfers_excluded": "legs matching an opposite-action leg on the same (symbol, date, quantity, price) are paired off before any net flow is computed. Measured on the first 38 symbols: 46.8% of symbol-days were PURE transfers with zero net demand.",
    "point_in_time": "a deal may only be used for scoring dates STRICTLY AFTER its trade date. Exchanges publish after the close and the feed carries no publication timestamp, so same-day use is forbidden.",
    "sides_kept_separate": "buyer and seller legs stored and counted separately; distinct client counts, not leg counts"
  },
```

---

## 2. The entire implemented deal path

Two code objects. There is no third.

`evaluator.py:190-200` (working tree) — the only query that reads deal data:

```python
# Deal feature, strictly before the scoring date (requirement 2), transfers already netted out.
_DEALS_SQL = """
SELECT symbol,
       sum(net_qty)                                   AS net_qty,
       sum(buying_clients)                            AS buying_clients,
       sum(selling_clients)                           AS selling_clients,
       count(*) FILTER (WHERE NOT pure_transfer_day)  AS active_days
  FROM nidp.v_trendlyne_deals_net
 WHERE deal_date < $1 AND deal_date >= $1 - $2::int
 GROUP BY symbol
"""
```

`evaluator.py:283-295` — the only function that turns deal data into score:

```python
def _deal_tilt(row: dict, max_tilt: float) -> float:
    """Bounded, separately-scaled deal contribution.

    Direction comes from distinct CLIENTS on each side, not leg counts, and magnitude is damped
    when only one client is involved — a single disclosed buyer is a transaction, not breadth.
    """
    buy = int(row.get("buying_clients") or 0)
    sell = int(row.get("selling_clients") or 0)
    if buy + sell == 0:
        return 0.0
    direction = (buy - sell) / (buy + sell)
    confidence = 1.0 if buy >= 3 else (0.6 if buy == 2 else 0.3)
    return max(-max_tilt, min(max_tilt, direction * confidence * max_tilt))
```

Call sites, which bound the audit: fetch at `evaluator.py:399-400`, single consumption at
`evaluator.py:468`, and the deal term enters the C score at `evaluator.py:470`:

```python
            deals = {r["symbol"]: dict(r) for r in await conn.fetch(
                _DEALS_SQL, d, deal_lookback_days)}
...
            d_tilt = _deal_tilt(deals.get(sym, {}), max_deal_tilt)
            rows_b.append((sym, b_score + mf_tilt))
            rows_c.append((sym, b_score + mf_tilt + d_tilt))
```

`grep` over the snapshot, confirming nothing else reads a deal column:

```
=== net_qty ===
193:       sum(net_qty)                                   AS net_qty,
=== active_days ===
196:       count(*) FILTER (WHERE NOT pure_transfer_day)  AS active_days
=== buying_clients/selling_clients ===
194:       sum(buying_clients)                            AS buying_clients,
195:       sum(selling_clients)                           AS selling_clients,
289:    buy = int(row.get("buying_clients") or 0)
290:    sell = int(row.get("selling_clients") or 0)
=== deals dict uses ===
399:            deals = {r["symbol"]: dict(r) for r in await conn.fetch(
468:            d_tilt = _deal_tilt(deals.get(sym, {}), max_deal_tilt)
```

And repo-wide, no Python anywhere reads the remaining view columns:

```
$ grep -rn 'had_block\|had_bulk\|gross_value_inr\|qty_bought\|qty_sold\|offsetting_legs' \
      --include=*.py backend/
(no output — zero matches)
$ grep -rln 'trendlyne_deals\|v_trendlyne_deals_net' --include=*.py backend/
backend/nidp/services/smart_money_study/evaluator.py
backend/nidp/services/trendlyne_ownership/deals.py        # ingest only: parse + INSERT
```

For reference, the full column surface the feature view actually exposes
(`nidp.v_trendlyne_deals_net`, from `information_schema.columns`, live DB):

```
    column_name    | data_type | ordinal_position
-------------------+-----------+------------------
 symbol            | text      |                1
 deal_date         | date      |                2
 legs              | bigint    |                3
 offsetting_legs   | bigint    |                4
 buying_clients    | bigint    |                5
 selling_clients   | bigint    |                6
 qty_bought        | numeric   |                7
 qty_sold          | numeric   |                8
 net_qty           | numeric   |                9
 gross_value_inr   | numeric   |               10
 had_block         | boolean   |               11
 had_bulk          | boolean   |               12
 pure_transfer_day | boolean   |               13
(13 rows)
```

13 columns exist; `_DEALS_SQL` selects 5; `_deal_tilt` reads 2.

---

## 3. Registered feature → implemented? (one row per registered feature)

| # | Registered feature (verbatim) | Computed? | Evidence |
|---|---|---|---|
| 1 | `deal intensity vs turnover and free float` | **NO** | No turnover or free-float term anywhere in the deal path. `_DEALS_SQL` (`evaluator.py:191-200`) selects no value/intensity column; `gross_value_inr` and `qty_bought`/`qty_sold` exist in the view and are never selected (grep above, zero matches). `_deal_tilt` (`283-295`) takes no turnover or float argument. The liquidity `med_turnover` that `_UNIVERSE_SQL` computes (`evaluator.py:92`, used at `390-391`) is consumed **only** for eligibility, never joined to deals. |
| 2 | `net disclosed flow excluding transfers` | **NO — computed in SQL, then discarded** | The quantity itself is produced twice: by the view (migration `176_trendlyne_deals.sql:83-85`, purchase-minus-sell over non-offsetting legs) and summed by `_DEALS_SQL:193`. It is loaded into `deals` (`evaluator.py:399-400`) and **never read**: the only reader of that dict is `_deal_tilt`, which touches `buying_clients`/`selling_clients` only (`289-290`). It is not persisted either — the prediction columns are `[... baseline_score, baseline_rank, smart_money_score, tilt, tilted_score, tilted_rank, data_confidence, evidence_class, single_amc_signal, eligible, ineligible_reason]` (`evaluator.py:591-594`), with no deal column. So net flow contributes **zero** to the score. |
| 3 | `repeat buying by the same client and by independent clients over fixed lookbacks` | **NO** | Requires `client_name`, which the view aggregates away into per-symbol-day `count(DISTINCT client_name)` (migration `176:76-79`). `_DEALS_SQL` reads the view, not the base table, so client identity is unreachable on this path. No repeat/lookback term exists in `_deal_tilt`. Not computable without changing the view or the query. |
| 4 | `deal price vs market price` | **NO** | `price` exists on the base table (`176:35`) but the view exposes **no price column at all** (13-column listing above). `_DEALS_SQL` selects no price and joins no price series. Not computable on this path as written. |
| 5 | `distinct buying clients` | **PARTIAL / degraded** | This is the one feature that reaches the score, and it is the only one. `buying_clients`/`selling_clients` are read at `evaluator.py:289-290` and drive `direction` at `293`. But `_DEALS_SQL:194-195` **sums per-symbol-day distinct counts across the 90-day window**, which equals distinct clients over the window only if no client transacts on more than one day. Measured on the live raw buy legs: `symbol_client_buy_pairs = 6200`, `pairs_on_multiple_days = 1385`, `pct_repeat = 22.34`, `max_days_one_client_one_symbol = 42`. So the implemented quantity is buying **client-days**, not distinct buying clients, and the contract's `sides_kept_separate` phrase "distinct client counts, not leg counts" is honoured at the day level but not at the window level. |
| 6 | `block vs bulk split` | **NO** | `had_block` and `had_bulk` are materialised by the view (`176:87-88`) and never selected by `_DEALS_SQL`; repo-wide grep for them over `--include=*.py backend/` returns zero matches. The six `reporting_breakdowns` the contract also registers (`bulk only`, `block only`, `repeated buying`, `repeated selling`, `mixed activity`, `pure-transfer days excluded vs included`) are therefore **not producible** by any code in the repo — same zero-match grep. |

**Count: 1 of 6 implemented (degraded), 1 of 6 computed-then-discarded, 4 of 6 absent.**

This is a *stricter* reading than the diagnosis report's "4 of the 6 registered features are
unimplemented" (`test_reports/deal_feature_effectiveness_20261022.md:312`). That claim is correct
and I confirm it: features 1, 3, 4, 6 are absent. I add two refinements the diagnosis did not state:
feature 2's value **is** computed and then thrown away (so the gap is a wiring gap, not a data gap),
and feature 5 — the sole surviving feature — is implemented as a sum of per-day distinct counts
rather than a window distinct count.

### Non-`features` keys of `deal_feature_rules`, for completeness

| Key | Status | Evidence |
|---|---|---|
| `bounds` ("bounded SEPARATELY … each can be ablated independently") | **Implemented** | Deal term is a distinct addend with its own bound: `mf_tilt` clamped to ±8.0 at `evaluator.py:467`, `d_tilt` clamped to `±max_deal_tilt` (default 4.0, `evaluator.py:341`) at `295`; C = `b_score + mf_tilt + d_tilt` at `470`, so dropping `d_tilt` recovers B exactly. |
| `confidence` ("lower confidence where the counterparty or ultimate beneficial owner is unclear; a single-client signal is damped") | **PARTIAL** | Single-client damping exists (`294`), but it keys on `buy` only, so the sell side is never graded: any sell-only row has `buy = 0` → `confidence = 0.3`, `direction = -1`, tilt = exactly `-1.2`, against `+4.0` available on the buy side. No counterparty / UBO classification exists anywhere — `client_name` is never inspected on this path (§2 grep). |
| `evidence_claim` | Documentation-only, no computation required | — |
| `offsetting_transfers_excluded` | **Implemented** in the view | `176:63-68` pairs on `(symbol, deal_date, quantity, price)` with opposite action; `net_qty`, client counts and `pure_transfer_day` are all computed on non-offsetting legs (`176:76-90`). |
| `point_in_time` ("STRICTLY AFTER its trade date") | **Implemented** | `_DEALS_SQL:198` → `WHERE deal_date < $1`, strict. |
| `sides_kept_separate` | **Implemented at the day level**, see feature 5 for the window-level caveat | `176:76-79` counts distinct clients per side; `_DEALS_SQL:194-195` sums those. |

---

## 4. Columns `_DEALS_SQL` loads but never reads — confirmed independently

Verified: **`net_qty` and `active_days`**. Both are selected (`evaluator.py:193`, `:196`), both land
in the `deals` dict via `dict(r)` (`:399-400`), and neither appears again anywhere in the module
(§2 grep: `net_qty` appears on exactly one line, `active_days` on exactly one line, both the SELECT
list). They are not read by `_deal_tilt`, not logged, and not persisted (`:591-594` column list).
`symbol` is read as the dict key (`:399`); `buying_clients` and `selling_clients` are read at
`:289-290`. So of 5 selected columns, 3 are used and 2 are dead.

This independently confirms the diagnosis report's point (iii)
(`test_reports/deal_feature_effectiveness_20261022.md:310`).

Note which one is dead: `active_days` is the non-pure-transfer day count — the natural denominator
for feature 1's intensity and the natural lookback counter for feature 3. `net_qty` is feature 2 in
its entirety. The two unread columns are precisely the two registered features that were half-built.

---

## 5. Did the contract permit a staged / partial implementation?

**No. I searched for permissive language and there is none.** This is an absence-of-text finding, so
here is the search rather than an assertion:

```
$ grep -ion 'phase\|phased\|staged\|stage\|partial\|subset\|initial\|first pass\|v1\|version 1\
         \|minimum\|may implement\|incremental implementation\|scope\|roadmap\|later\|future\|defer' \
      backend/nidp/studies/NIDP-SM-VALIDATION-002.json
24:subset
$ grep -ion 'phase\|staged\|partial\|subset\|scope\|defer' \
      backend/nidp/studies/NIDP-SM-VALIDATION-001.json
69:subset
```

One hit in each file, and in both it is a **prohibition, not a permission**. 002 line 24 is the
`failure_policy`; 001 line 69 is `promotion_rule.failure_policy`. There is no `scope`, `phasing`,
`phase_1`, `must_implement`, `minimum_viable`, or "features are indicative" key anywhere in either
contract. The `features` list sits inside `deal_feature_rules` — the block that defines the model —
with no qualifier of any kind on it.

**The two clauses that settle it, quoted verbatim:**

From 002 `models` (line 42):

```
"C": "Model B + a SEPARATELY bounded bulk/block deal feature"
```

From 002 `why_a_separate_study` (line 56):

```
"NIDP-SM-VALIDATION-001 is frozen and immutable by trigger. Adding a hypothesis to it after the
fact is exactly what preregistration exists to prevent, so the bulk/block deal feature is
registered as its own versioned experiment with its own holdout. 001's acceptance criteria are
unchanged."
```

The contract's stated purpose for existing is that the deal feature's *design* is the thing being
preregistered. A `features` list inside the design block, under a contract whose own rationale is
"this is registered so it cannot be changed after the fact", is a specification, not a menu.

**Corroborating evidence from the implementation itself.** The code enumerates exactly which choices
it considers out-of-contract, and writes that enumeration onto every run
(`evaluator.py:370-374`):

```python
                json.dumps({"portfolio_n": portfolio_n, "deal_lookback_days": deal_lookback_days,
                            "max_deal_tilt": max_deal_tilt, "paired_against": other,
                            "paired_run_id": str(run_id[other]),
                            "note": "portfolio_n and deal tilt bounds are implementation "
                                    "parameters, not part of either frozen contract"}))
```

Its module docstring makes the same distinction (`evaluator.py:22-23`): *"Portfolio size is NOT part
of either frozen contract, so it is an explicit implementation parameter."* Three items are claimed
as implementation latitude — `portfolio_n`, `deal_lookback_days`, `max_deal_tilt`. **The feature
subset is not among them**, and no run record declares a reduced feature set. The author's own
boundary between "contract" and "implementation detail" therefore places the `features` list on the
contract side.

**Also note what the frozen-contract guard does and does not catch.** `load_study`
(`evaluator.py:66-81`) re-hashes the stored config and aborts on mismatch — and it passed, as §0
shows. That guard proves the *contract text* was not altered. It performs no check that the
implementation implements the registered features, so the gap in §3 passed through the "FROZEN
CONTRACTS ARE NOT NEGOTIABLE" rule (docstring `evaluator.py:15-16`) without tripping it. A clean
contract hash on a run record is therefore not evidence of design fidelity.

**Conclusion for §5, stated as the audit finding:** running Model C with 1 implemented (degraded) +
1 discarded + 4 absent features is a **DEFECT against the registered design** — the executed model
is not the model described by `deal_feature_rules.features`. The contract contains no clause
permitting it. I note the one mitigating fact in the record: both runs are stamped
`stage = exploratory` (DB output in §0; default at `evaluator.py:342`), not confirmatory, and the
`features` list is prose rather than an executable spec, so the gap is at least as consistent with
an incomplete build as with a post-hoc narrowing. **Whether that mitigation is sufficient is the
study owner's call, not this audit's.**

---

## 6. `failure_policy`, verbatim, and what it requires

002, line 24, complete:

```
"failure_policy": "if the C-vs-B increment is not positive out of sample, deals are retained as
market-intelligence CONTEXT and must not influence the score. No horizon, subset or threshold may
be reselected after seeing results; that requires a new study_id.",
```

The inherited parent policy, 001 `promotion_rule.failure_policy`, line 69, complete:

```
"no promotion without positive out-of-sample evidence; a failed study is not rescued by changing
horizon, benchmark, threshold or subset — that requires a new study_id and a fresh holdout"
```

What they require, read strictly and nothing more:

1. **A changed feature design after results are known requires a NEW `study_id`.** 002's clause
   names "horizon, subset or threshold"; 001's names "horizon, benchmark, threshold or subset". A
   feature set is the clearest reading of "subset" in a contract whose model block is a list of
   features. Implementing features 1, 3, 4, 6 now — after the INCONCLUSIVE increment is known — is a
   change to the registered configuration made *after seeing results*, which both clauses route to a
   new `study_id`.
2. **A fresh holdout as well.** Only 001 says "and a fresh holdout". 002 says "a new study_id" and
   omits the holdout words — but 002 line 56 states its own holdout requirement
   (*"registered as its own versioned experiment with its own holdout"*), and 002 inherits 001 as
   `parent_study` (line 44). **I flag the exact wording difference rather than resolving it:** 002's
   failure_policy sentence does not itself say "fresh holdout". A reader wanting the holdout
   requirement in 002's own words must rely on `why_a_separate_study`, not on `failure_policy`.
3. **No outcome inspection before the design is fixed.** Both clauses are triggered by the phrase
   "after seeing results" / "is not rescued by". The results have now been seen: run `a4d964f7`
   carries `mean_paired_diff_pp = 0.2189`, `ci95_pp = [0.0, 0.5104]`, verdict `INCONCLUSIVE` (DB
   output, §0), and the diagnosis report attributes the inertness in detail. **Any re-run that both
   (a) alters the feature set and (b) reports on these same 9 formation dates has already consumed
   its outcome information.** The policy's remedy is a new `study_id` whose design is frozen before
   its outcomes are looked at.
4. **The default disposition on a non-positive increment.** "deals are retained as
   market-intelligence CONTEXT and must not influence the score." I record, without ruling on it,
   that the measured increment is *positive* (+0.2189 pp) with a CI lower bound of exactly 0.0000,
   and that 002's `hurdle.note` (line 33) sets no pp hurdle for C-vs-B, requiring instead
   *"a credible positive out-of-sample estimate"*. Whether a CI pinned at zero, on 9 dates against a
   12-block review floor, on an exploratory stage, is "credible positive" is the owner's judgement.

---

## 7. What the gap means for interpreting the verdict

**The INCONCLUSIVE verdict cannot be described as "the registered overlay did not add value."**
Two independent restrictions sit between the registered design and what was measured:

* **Feature restriction (this audit).** 1 of 6 registered features reached the score, in a degraded
  form; 1 more was computed and discarded; 4 were never built. The measured object is a
  client-count-direction tilt, not the registered six-feature overlay.
* **Universe restriction (the prior diagnosis, which I did not re-derive).** 1,910 of 6,873 eligible
  symbol-dates were ever queried (27.8%), because `_symbols()` orders candidates `ORDER BY 1` and
  the CallBudget cut the list at position 338 of 984 — so every symbol outside A-G was *never
  asked*.

The defensible statement is therefore the narrow one:

> A **1-of-6-feature** subset of the registered deal overlay (direction from summed per-day distinct
> client counts, with buy-side-only confidence damping), evaluated over **27.8%** of the eligible
> universe and **changing 4 of 270 top-30 slots**, produced no detectable paired increment over
> Model B on 9 exploratory formation dates.

The weaker claim the brief offered — "a 2-of-6 subset, measured over 28% of the universe, did not add
value" — is also safe, and is *generous* to the implementation: feature 2 (`net_qty`) is loaded but
contributes exactly nothing to the score, so by effect on the result the subset is 1-of-6, not
2-of-6. Either phrasing is honest; the 6-of-6 phrasing is not.

Three consequences worth stating plainly:

1. **H0 was not tested.** 002's H0 is *"adding a bounded bulk/block deal feature does not improve
   net 20-session incremental return beyond the mutual-fund holdings tilt"* (line 36). The overlay
   that was added is not the overlay registered, so the INCONCLUSIVE result is uninformative about
   H0 as written — in either direction. It is not evidence against the deal hypothesis.
2. **The verdict text itself is not the limiting factor.** `_finish` would have returned
   INCONCLUSIVE on this sample regardless of the increment: `n = 9 < MIN_FORMATION_DATES = 12`
   (`evaluator.py:46`, `:625-628`). With 9 dates the only reachable verdict is INCONCLUSIVE, so no
   feature design could have produced PASS on this run. That is an additional reason the result
   carries no information about the overlay's value.
3. **The gap is a wiring gap, not a data gap, for 3 of the 4 missing features.** `net_qty`,
   `gross_value_inr`, `had_block`/`had_bulk` are already materialised by the view and merely not
   selected; `nidp.stock_features_daily.free_float_pct` is populated for 1,492 symbols from
   2025-12-29 (`count(free_float_pct) = 269424` of `462378` rows, live query), i.e. covering all 9
   formation dates from 2026-01-12. Only features 3 and 4 (client identity, deal price) need the
   view or the query changed to reach the base table. So "the features were not implementable" is
   **not** an available explanation for most of the gap.

---

## 8. UNVERIFIED / limits of this audit

* **UNVERIFIED: I could not reconstruct the source of the earlier run** `9c0eb9f6-be16-41e9-bbcd-b83ba7e0f82f`. Its recorded `code_commit` is `b4d521e555a468fe2ffa1b7f8cc18f3516fbba9d`, and
  `git show b4d521e5:backend/nidp/services/smart_money_study/evaluator.py` returns
  `fatal: path ... exists on disk, but not in 'b4d521e5'` — the evaluator did not exist in that
  commit, so that run was executed from an uncommitted tree. My audit is pinned to run
  `a4d964f7` / commit `72a9243c`, where the deal path is byte-identical to what I read (§0). Both
  runs report the same statistics, but I have not proven their code was the same.
* **UNVERIFIED: I did not re-derive the 27.8% coverage funnel or the A-G truncation.** Those are
  carried from `test_reports/deal_feature_effectiveness_20261022.md` (owned by another agent) and
  are cited, not reproduced, in §7.
* **UNVERIFIED: the 22.34% repeat-client figure is not window-scoped.** It is measured over all buy
  legs in `nidp.trendlyne_deals` (which spans more than 90 days), not over each formation date's
  90-day lookback, and it does not apply the view's non-offsetting filter. It establishes that the
  summed-distinct-counts aggregate double-counts repeat clients; it does not quantify the error
  inside any specific window.
* **UNVERIFIED: I did not measure how the result would change** if the four missing features were
  implemented. No re-run was performed and none should be, per §6 point 3, until the study owner
  decides the preregistration question.
* **Interpretation of "subset"** in both failure policies as covering a feature set is my reading of
  the contract text, flagged as such in §6 point 1. The contracts do not define the word. The
  clauses are quoted in full so the owner can read them directly.
* **I made no call** on whether the re-run continues `NIDP-SM-VALIDATION-002` or needs a new
  `study_id`. That is the study owner's decision; §5 and §6 supply the contract text it turns on.

---

*The gate line below attests that this audit is complete and that every claim in it is backed by
real output shown above. It is **not** a verdict on the overlay, the study, or the re-run decision.
The audit's substantive finding is in §5: the executed Model C did not implement its registered
feature design.*

## Verdict: PASS
