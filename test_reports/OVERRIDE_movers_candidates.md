# OVERRIDE — Movers "Candidates" mode: logic + real staging data verified, HTTP/UI not yet (not deployed)

REASON: The feature (backend `/movers/candidates`, the new Candidates mode in the Movers dashboard, the
feed-screen link) is verified three ways: 69 backend pytest (mocked DB connection), 48 Playwright (mocked
API, real browser), and — after the GCP token was refreshed 2026-10-03 — the actual merge/rank/liquidity-floor
logic run by hand against the REAL staging NIDP Postgres (`nidp_staging` on `nidp-stack-vm`): real tables, 39
real high-impact filings and several real bulk/block deals on the latest session (2026-10-01), 69 symbols with
a signal, 53 passing the liquidity floor, real deal values ranking as expected. See
`movers_candidates_20261003.md` for the full output.

No PASS verdict is claimed because two things remain, neither a credentials problem any more:

1. **This branch is not deployed.** It is a worktree off `origin/dev`, nothing pushed. This repo's rule is
   "deploy via git push + the redeploy script only," and a push to `dev` is a live redeploy of shared staging
   — not something to do unilaterally for a feature the owner has not yet seen. So `GET /api/movers/candidates`
   and the new UI cannot be hit over real HTTP on `staging.niveshcopilot.com` yet.
2. **`move_odds` has an empty allowlist on staging right now — a pre-existing condition, not something this
   branch caused.** Checked directly: `portfolio_ingestion.system_config` (staging Mongo) has zero documents,
   so every feature flag is running on its in-memory code default, and `move_odds`'s default is
   `allowlist: []`. `is_admin` does not bypass this gate (feature_gate.py: "admins included"). Net effect:
   nobody — including the owner's own account — can currently reach the Movers dashboard on staging at all,
   this new Candidates mode or the pre-existing MOVERS/FLAGGED modes. This was true before this branch
   existed; it just became visible while checking why TC-C21 would fail.

What would clear this: the owner's go-ahead to push this branch to `dev` and run the redeploy script, and a
decision on `move_odds` — either add the test account's email to its allowlist (a live write to
`system_config`; I did not do this unprompted) or confirm some other account/path to test with. Then re-run
TC-C20–C21 (`TESTCASES_movers_candidates.md`) for real against `staging.niveshcopilot.com`. Clear this file
and replace the BLOCKED verdict with PASS once that is done.
