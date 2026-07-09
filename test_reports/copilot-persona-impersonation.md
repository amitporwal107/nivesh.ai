# Functionality Verification — copilot landing persona while impersonating a client

**Bug:** When an advisor is "viewing a client" (impersonation / client view), the copilot
chat landing showed the **advisor book** workflows ("Nine jobs across your book") — but the
copilot answers in **investor** mode for that client's portfolio, so the landing should
show the **investor** workflows.

**Root cause:** `isAdvisor` was `workspaceType === "ADVISORY"` only. During impersonation
the workspace is still ADVISORY, so it stayed advisor.

**Fix (Chat/index.tsx):** advisor persona now also requires being at the advisor root —
`workspaceType === "ADVISORY" && !useImpersonationStore(s => s.profileId)`. The
impersonation store is the authoritative signal (drives the `X-Active-Profile` header and
is what use-chat.ts scopes by; `me.activeProfileId` races the persisted store). So while
viewing a client, the landing renders the investor workflows — matching the copilot's mode.

## Test cases
| # | State | Expected |
|---|-------|----------|
| 1-3 | investor | investor list + guided tour (regression) |
| 4-5 | advisor at root | advisor book workflows (regression) |
| 6 | **advisor viewing a client** (impersonation store profileId set) | `data-role="investor"`, shows "Portfolio health review", NOT "At-risk & churn" |

## Real output (dev-based production build, base /v5/)
```
$ npx tsc --noEmit         # EXIT 0
$ VITE_BASE=/v5/ npx vite build   # ✓ built (EXIT 0)
$ PW_BASE_URL=http://localhost:5209 npx playwright test e2e/tests/copilot-workflows.spec.ts --config pw.copilot.config.ts

  ✓ 1 investor default list (6.2s)
  ✓ 2 investor row runs workflow (4.4s)
  ✓ 3 investor guided tour (5.1s)
  ✓ 4 advisor book workflows (2.9s)
  ✓ 5 advisor row runs book prompt (3.5s)
  ✓ 6 impersonating a client shows INVESTOR workflows, not the book (3.2s)

  6 passed (31.1s)
```

## Notes
- Verified against the dev-based production build; re-verify on staging after deploy.

## Verdict: PASS
