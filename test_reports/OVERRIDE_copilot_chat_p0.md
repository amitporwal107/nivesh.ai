# OVERRIDE — Copilot chat p0 fixes (fix/copilot-chat-p0): live-session and post-deploy checks

REASON: a live, signed-in walk of `/api/chat/stream` on staging (TC-CP1…4 end to end, and the trade-idea pin) needs a
staging session token I do not have, and the scheduler-lock behaviour under the real 4-worker deploy can only be
confirmed from `nidp.job_log` after a deploy and a scheduled-job tick. Everything else passes:
- 302 targeted unit/integration tests, plus the full CI allowlist with an identical failing-test set to `origin/dev`
  (no regression, 160 more tests pass);
- `tsc` clean and `28 passed` on `copilot-app.spec.ts` (mocked Playwright, production build);
- a read-only, real-data run of the fixed router and symbol resolver inside the staging container shows the exact
  fix: the owner's generic questions no longer hit "Which stock?", and real stocks still resolve.
See `test_reports/copilot_chat_p0_20261030.md`.

To finish: after the merge and deploy, (1) ask the owner (or use an existing session) for one signed-in question per
fix on staging chat, and (2) check `nidp.job_log` for one scheduled job's next tick — one row, not four. Paste the
results, set the verdict to PASS and delete this file.
Owner-visible: yes. Date: 2026-10-30. Session 3d5d2da4.
