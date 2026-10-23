# F&O Stage B2 expiry study: test cases (authored before the real run)

Ask: per-expiry futures signals (near/next/far), pre-registered in docs/FO_STAGE_B2_EXPIRY_CURVE_PREREGISTRATION.md and the 2026-10-23 amendment.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | weekdays to expiry (expiry day 0, past expiry 0, worked counts) | unit | numbers |
| TC-2 | a bucket uses its own contract's price, OI change and volume; no summing across expiries; rvol null before 20 sessions; liquid flag | unit | numbers |
| TC-3 | category by signs, zero is neutral, floors and volume floor | unit | category |
| TC-4 | the seven configurations select the right underlyings and directions | unit | lists |
| TC-5 | benchmark-relative outcome; a signal whose forward window leaves its window is excluded | unit | counts |
| TC-6 | direction adjustment and cost subtraction | unit | numbers |
| TC-7 | verdict rules (supported / inconclusive / not_supported, permutation gate, 30-session minimum) | unit | verdict |
| TC-8 | end-to-end run on a synthetic world: deterministic hash, everything counted, never validated | unit | hash |
| TC-9 | no look-ahead: removing later rows does not change earlier buckets | unit | equal |
| TC-10 | real run on the warehouse export under the frozen baseline hash | real data | report |
