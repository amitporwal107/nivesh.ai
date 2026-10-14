# Functionality verification — Copilot market tool DaaS paths

- Date: 2026-10-12 (staging, CloudPe app VM 45.64.105.88)
- Commit: `ad604620` on `dev`, deployed by CI (repo HEAD on the VM = `ad604620`, backend restarted 2026-10-12T18:23:05Z)
- Changed: `backend/services/copilot_tools/market_research.py` (two request paths), new `backend/tests/test_copilot_market_tool_paths.py`
- Frontend: not changed, so no Playwright run.

## Defect

`daas_client._get` prepends `/v1`. The market tool passed `/v1/snapshots/market` and
`/v1/market-pulse/movers`, so it requested `/v1/v1/...`, got 404 (returned as `None`), and the
market agent answered with "Market snapshot unavailable" regardless of provider.

Before the fix, on staging:

```
daas_client._get('/v1/snapshots/market') → ok, keys: NoneType
daas_client._get('/snapshots/market') → ok, keys: ['data']
market tool → error:market snapshot unavailable | Market snapshot unavailable
```

## Test cases

| # | Case | Expected | Result |
|---|---|---|---|
| 1 | Unit: tool requests only un-prefixed paths, including `/snapshots/market` | pass | PASS |
| 2 | Staging app test: `get_market_research()` in the running backend container | `ok: True`, indices and breadth filled | PASS |
| 3 | Staging data test: tool figures equal `nidp.index_eod` on the NIDP VM for the same date | equal | PASS |
| 4 | Staging health after deploy | 200 | PASS |
| 5 | Other callers of `daas_client._get` use un-prefixed paths | none prefixed | PASS (read: `stocks_insights.py:225,237`, `sector_analysis.py:369`) |

## Evidence

Case 1:

```
$ python -m pytest tests/test_copilot_market_tool_paths.py -q -p no:cacheprovider
.                                                                        [100%]
1 passed in 0.32s
```

Case 2 (inside `nivesh-staging-app-backend`, after the deploy):

```
ok: True
indices: [{"label": "Nifty 50", "value": 22363.35, "change_pct": -0.7}, {"label": "Bank Nifty", "value": 54918.0, "change_pct": null}, {"label": "Nifty 500", "value": 21822.75, "change_pct": null}]
breadth: {"advances": 1583, "declines": 1686, "unchanged": 63}
widget keys: ['as_of', 'breadth', 'caveat', 'flows', 'indices', 'movers', 'suggestions', 'vix', 'vix_tone', 'yields']
summary: Nifty 50 22,363 (-0.70%) · Bank Nifty 54,918 · Nifty 500 21,823 · India VIX 15.25 (normal) · breadth 1583 adv / 1686 decl · FII ₹-1,708cr, DII ₹3,045cr · 10Y G-Sec 7.23%
```

Case 3 (`nidp.index_eod` on the NIDP VM):

```
India VIX | 2026-10-12 | 15.2500 | 6.1000
Nifty 50 | 2026-10-12 | 22363.3500 | -0.7000
Nifty 500 | 2026-10-12 | 21822.7500 | -0.2000
Nifty Bank | 2026-10-12 | 54918.0000 | -0.6100
```

Case 4:

```
curl https://staging.niveshcopilot.com/api/healthz -> 200
{"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
```

## Not verified / known gaps

- UNVERIFIED: a full chat turn through the market agent on Claude. No Anthropic key is on staging
  (`llm provider: openai | anthropic key present: False`), and the OpenAI key has no credits.
- Movers are empty for every cap bucket (`gainers=0 losers=0` for large, mid and small), so the
  widget's `movers` is null. This is a data gap on NIDP (market-cap buckets not built yet; the
  Screener backfill is still running), not a path problem.
- Bank Nifty and Nifty 500 show `change_pct: null` in the widget although `nidp.index_eod` has the
  values (-0.61, -0.20): the snapshot endpoint only carries `nifty50_pct_change`. Not changed here.

## Verdict: PASS
