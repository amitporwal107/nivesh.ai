# Functionality Verification Report — User guide: direct and shared links return 403 (fix)

- **Branch:** fix/user-guide-direct-link (from origin/dev f98f8eee, which includes #487)
- **Date:** 2026-11-05
- **Author:** Claude (full-stack developer + QA)
- **Environment:** local production build served by the staging v5 nginx config (`deploy/nivesh-app/nginx-frontend-v5.conf`)
  in `nginx:alpine`; Playwright against `vite preview`; staging checked live before the fix
- **Changed areas:** backend routes/services: no · frontend src: yes (`pages/UserGuide/guide-data.ts`), public assets renamed

## Summary
After #487 deployed (frontend deploy run 41959575720, success), a direct, shared or refreshed link to the user guide failed on
staging: `https://staging.niveshcopilot.com/v5/user-guide?lang=hi` → `301` to `/v5/user-guide/?lang=hi` → `403`. Cause:
the written-guide text lived in `public/user-guide/`, the same name as the page's route, and the v5 nginx serves
`try_files $uri $uri/ /v5/index.html`, so `$uri/` matched the folder before the SPA fallback. In-app navigation from the
homepage and `vite preview` (used by the e2e run) were unaffected, which is why #487's tests passed. Fix: the folder is now
`public/guide-text/`; the page fetches `guide-text/<lang>.json`. Added TC-19, a guard that no public folder shadows the route.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-20 | Staging (before fix) | Direct link | data (curl) | reproduce: 301 → 403 | REPRODUCED |
| TC-21 | nginx, #487 layout | `/v5/user-guide?lang=hi` with the staging v5 conf | integration | 301 (control) | 301 (bug reproduced locally) |
| TC-22 | nginx, fixed layout | `/v5/user-guide?lang=hi`, `/v5/user-guide` | integration | 200 `index.html` | PASS |
| TC-19 | Guard | no `public/user-guide/`; `public/guide-text/en.json` exists | unit (spec) | true | PASS |
| TC-1..15 | Page + homepage | the full #487 suite on the fixed build | e2e | all pass | PASS (16/16 incl. TC-19) |
| TC-23 | Staging (after merge) | direct link 200 | data (curl) | 200 | UNVERIFIED until merged |

## API / Endpoint Tests (staging)
No backend change. Before the fix, live (real output):
```
$ curl -sI "https://staging.niveshcopilot.com/v5/user-guide?lang=hi"
HTTP/2 301
location: http://staging.niveshcopilot.com/v5/user-guide/?lang=hi
$ curl -sL -o /dev/null -w "after redirects: HTTP %{http_code} %{url_effective}\n" "https://staging.niveshcopilot.com/v5/user-guide?lang=hi"
after redirects: HTTP 403 https://staging.niveshcopilot.com/v5/user-guide/?lang=hi
```
The staging container's rule: `/etc/nginx/conf.d/*.conf:34: try_files $uri $uri/ /v5/index.html;`

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/homepage-user-guide.spec.ts` against the fixed build
  - Command: `npx playwright test --config playwright.config.ts --project=unauthenticated e2e/tests/homepage-user-guide.spec.ts`
  - Output: `Running 16 tests using 2 workers` … `✓ 15 … TC-19 no public folder shadows the /user-guide route (nginx try_files $uri/ would 301 then 403 a direct link) (4ms)` … `16 passed (11.9s)`
  - Result: PASS
- **Build:** `vite build` → `✓ built in 45.89s` (exit 0).

## Integration test with the staging nginx config
Built `dist`, served by `nginx:alpine` with `deploy/nivesh-app/nginx-frontend-v5.conf`; control = the same build with the
folder renamed back to `user-guide/` (the #487 layout). Real output:
```
== old layout (as merged in #487)
/v5/user-guide?lang=hi -> HTTP/1.1 301 Moved Permanently
/v5/user-guide -> HTTP/1.1 301 Moved Permanently
== fix layout (this fix)
/v5/user-guide?lang=hi -> HTTP/1.1 200 OK
/v5/user-guide -> HTTP/1.1 200 OK
     body: <!doctype html> <html lang="en">   <head>     <meta charset=
/v5/guide-text/hi.json -> HTTP/1.1 200 OK
```
Fixed build layout: `v5/guide-text/{en,gu,hi,mr,ta}.json`, no `v5/user-guide/` folder; `hi.json` starts `{ "lang": "hi", "video": "nivesh-copilot-da8691abb…`.

## Data Correctness (staging)
The written-guide files are unchanged byte for byte (`git mv`); before the fix they were live on staging at
`/v5/user-guide/<lang>.json` with 43 sections each in all five languages (HTTP 200 application/json).

## UNVERIFIED
- TC-23: the direct link on staging returns 200 only after this PR merges and the frontend deploy runs. After the merge:
  `curl -sI "https://staging.niveshcopilot.com/v5/user-guide?lang=hi"` must show `HTTP/2 200`.

## Verdict: PASS
