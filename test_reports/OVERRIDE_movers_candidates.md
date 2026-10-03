# OVERRIDE — Movers "Candidates" mode: deployed, flag enabled; one human-session check left

REASON: Everything buildable without a human-provided secret is done and verified for real:

- 69 backend pytest + 48→49 Playwright (mocked DB/API), `tsc -b` clean.
- The real `candidates()` merge/rank/liquidity-floor logic run by hand against the real staging NIDP
  Postgres (39 real high-impact filings, real bulk/block deals, 53/69 symbols passing the liquidity floor).
- Merged this branch with a concurrent `dev` commit (`FORWARD tab beside MOVERS and FLAGGED` — same two
  files) into a coherent 4-mode dashboard, re-verified (69 pytest, 49 Playwright, 0 failures).
- Pushed to `dev` (`32ee917d..10503c75`) and ran the staging redeploy; smoke check `{"status":"ok", ...}`,
  all containers healthy on fresh images.
- Confirmed `GET /api/movers/candidates` is live on `staging.niveshcopilot.com` (401 unauthenticated — the
  route exists and is wired, not 404/500).
- `move_odds`'s staging allowlist was empty (a pre-existing condition, not caused by this branch) — owner
  confirmed adding their account; wrote `system_config.flags.move_odds = {mode: allowlist, allowlist:
  [aporwal107@gmail.com]}` directly to staging Mongo and read it back to confirm.

No PASS verdict is claimed because one thing remains: an **authenticated** pass through the real UI —
opening `/v5/research` as a logged-in `aporwal107@gmail.com`, clicking the new "Candidates for the next
session →" link, and confirming the rail/hero/chart/timeline render real data. This needs a human session
(the owner looking themselves, now that the account is entitled, or a session token handed to this session)
— not something to fabricate.

What would clear this: the owner opens the link in their own browser and confirms it looks right, or hands
this session a staging session token to do that pass directly. Clear this file and replace the BLOCKED
verdict in `movers_candidates_20261003.md` with PASS once that's done.
