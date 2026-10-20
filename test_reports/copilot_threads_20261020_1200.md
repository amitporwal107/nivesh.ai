# Copilot threads — bookmark, tag, clear, 2-day rail window

Branch feat/copilot-round4 (worktree /home/deploy/nivesh-copilot-ui), uncommitted.

## Test cases
- TC-T1 rail shows only threads <= 2 days old; older (incl. bookmarked) under Past conversations, searchable
- TC-T2 bookmark -> PATCH {bookmarked:true}, floats to top, "★ saved" filter
- TC-T3 tag add (lower-cased) -> PATCH {tags}, chip, filter chip, remove
- TC-T4 clear asks first; Keep cancels (no DELETE); Clear -> DELETE, row removed
- TC-T5 clearing the open thread navigates to home
- TC-B1 backend: _clean_tags trims/lower-cases/dedupes/caps (8 tags, 24 chars); SessionPatch fields optional

## Evidence (real output, this session)
- `tsc --noEmit` (docker): exit 0, no output
- backend: `pytest tests/test_chat_session_patch.py` -> `2 passed`
- Playwright, full copilot-app suite on a production build, mocked /api: `23 skipped, 320 passed (3.6m)`
  (skipped = pre-existing live-staging and screenshot specs). TC-T1..T5 all pass (first run had one
  selector error in my own test, fixed; rerun green).

## UNVERIFIED
- PATCH endpoint never called against a real DB or staging (see OVERRIDE_copilot_threads.md).
- Layout not looked at (no screenshot); hover buttons vs the time label at 280px drawer width unchecked.
- Real list response carrying `bookmarked`/`tags` (raw documents are returned, expected but unconfirmed).

## Verdict: BLOCKED on deployment — UI and unit level PASS, staging API check outstanding
