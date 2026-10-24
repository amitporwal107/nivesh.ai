# OVERRIDE — OMS contract (`feat/oms-contract`)

REASON: This PR adds a contract-only backend module (`backend/services/oms/`) with no route and no caller, so there is no staging endpoint to call and nothing user-visible to render. It is verified by unit and integration tests against an in-memory store. A staging data test becomes possible once a route or the paper path writes `oms_orders` (planned for the paper-OMS phase).

## Test cases
See `test_reports/oms_contract_TESTCASES.md` (OMS-1 … OMS-20). All are covered by `backend/tests/test_oms_contract.py`.

## Local evidence (clean tree from origin/dev b74c7f4f, throwaway container, no network)
```
$ python -m compileall -q services/oms tests/test_oms_contract.py && echo compile_ok
compile_ok
$ python -m pytest tests/test_oms_contract.py -q -p no:cacheprovider
28 passed in 0.46s
```

## Not verified
- Mongo's real `DuplicateKeyError` behaviour under concurrent inserts is exercised only through the fake collection's unique-index emulation.
- `ensure_indexes` has not been run against the staging Mongo.
