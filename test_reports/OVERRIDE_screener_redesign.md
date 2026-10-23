# Override: Screener redesign (lenses, fund metrics, click-to-chart)

REASON: built and tested locally on feat/provider-foundations (backend 65 passed / 1 skipped; Playwright 66 passed / 2 skipped on a production build with every /api call route-mocked; tsc clean) but NOT committed, pushed or deployed. The staging checks the protocol asks for need the branch merged to dev and redeployed (a push to dev is denied to this session and I cannot open or merge PRs), and the signed-in staging API check (TC-7: a real POST /api/screeners/run with a fund rule compared with GET /api/markets/smart-money/scanner) needs the user's session token, which has not been provided.
- 2026-10-23: see screener_redesign_20261023.md for the real local output and the list of what is UNVERIFIED.
