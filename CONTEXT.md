# CONTEXT.md — Shared operating context for all work in this repo

Loaded every session. Role guides: `.claude/roles/*.md`. Canonical facts: `docs/`.
Hooks (enforcement): `.claude/settings.json`. Inference profiles: `.claude/MODEL_PARAMETERS.md`.
Multiagent team: `.claude/AGENT_TEAM.md` (`/plan-from-prd <prd>`, `/team <task>`).

## 0. Task intake — before accepting any task

1. **Restate** the task in one line. If you can't, ask.
2. **Pick the role guide(s)** and read them; strictest gate wins on conflict.

| Signals | Read |
|---|---|
| build/fix feature, API, DB, auth, wiring, bug in running code | `.claude/roles/FULL_STACK_DEVELOPER.md` |
| broken?, coverage, flaky, regression, verify, QA | `.claude/roles/QA_ENGINEER.md` |
| should we build, scope, priorities, acceptance criteria | `.claude/roles/PRODUCT_MANAGER.md` |
| UI, component, layout, a11y, polish, responsive | `.claude/roles/DESIGN_ENGINEER.md` |
| timeline, dependencies, sequencing, blockers, risk | `.claude/roles/PROJECT_MANAGER.md` |
| fundamental/technical analysis, MF selection, quant model, feed trust, SEBI review, market-analytics advice | `.claude/roles/DOMAIN_EXPERT_ANALYST.md` |

3. No clear owner → `FULL_STACK_DEVELOPER` + `QA_ENGINEER`; say so.
4. **Unknowns:** if acceptance criteria, environment or "done" are undefined, ask one question or state the assumption.
5. **Ground in `docs/`** (start at `docs/PROJECT_CONTEXT.md`; it indexes architecture, API, schema, env, build/deploy, business spec, PRD template, plan). Code and migrations beat docs; fix the doc.
6. **Open the checklist** in `checklists/` (`TASK_*` else role `SKILL_*`). Report DONE only when its DONE-GATE passes.

## 1. Honesty & verification (all roles, no exceptions)

- "Changed" ≠ "verified". Edited code is a hypothesis until proven.
- No *fixed / working / deployed / done / passing / resolved / should work* without the command and its real, unedited output in the same response.
- Never fabricate output, logs, results, metrics or status.
- Mock data is loud: label `// MOCK — not real data` in code and say so in prose. Never present it as real.
- Report failures with output. Flag the unchecked as `UNVERIFIED: did X, not Y, because Z`.
- Read the canonical source (DB, spec, test output) instead of restating from memory.
- Behavior claims need both an app test and a data test (e.g. `nidp.v_feed_status`, `nidp.validation_findings`, `mutual_fund_metadata.v3_scored_at`). A 200 is not correct data.

## 1b. Status vocabulary (reserved words, `hallucination_tolerance = zero`)

- **DONE / COMPLETE** — every checklist item for the target environment is green and evidence is shown. Otherwise IN PROGRESS. Never "done" for "I wrote the code".
- **VERIFIED** — one claim proven this turn with shown output; scope it (staging ≠ prod).
- **IN PROGRESS** — the honest default.
- **🔴 REAL BLOCKER:** — state what, why, what's needed; STOP. No mock, assumption or silent reinterpretation as a workaround.
- **NEEDS-INPUT: I need X because Y.** — for any assumption about intent, scope, environment, data shape or acceptance not verifiable from `docs/` or code, ask; don't guess. Only assumptions you immediately verify (then state as VERIFIED) are allowed.

## 2. Quality bar for code

- Obvious and readable over clever. Smallest change that solves it; note, don't make, drive-by fixes.
- No new dependency without a stated reason.
- No swallowed errors, empty catches, or `// TODO` in a path claimed done.
- Match neighboring code. No secrets in code, fixtures, commits or output.
- Leave the branch building and the app starting, or mark UNVERIFIED.

## 3. Definition of Done (plus the role guide's DoD), all shown in the final response

- [ ] Ask restated and fully addressed (no silent scope cuts).
- [ ] Verification command ran this session, real output shown, and it demonstrates the result.
- [ ] No unlabeled mock data in any path claimed working.
- [ ] Unverifiable items flagged UNVERIFIED with reason and next step.

Otherwise report UNVERIFIED / IN PROGRESS.

## 4. Enforcement

- **Baseline gate:** a session that edited code can't end without a verification command (Stop hook, exit 2; feedback on stderr). Role verify commands feed the `clear-if-verified.sh` regex.
- **Functionality gate** (`.claude/VERIFICATION_PROTOCOL.md`): editing `backend/routes|services|*routers` or `frontend*/src` blocks the turn until `test_reports/` has a fresh report (newer than the last edit) listing test cases, real staging API results (backend) and real Playwright output (frontend), ending `## Verdict: PASS`. The only skip is a loud `test_reports/OVERRIDE_<slug>.md` with a `REASON:` line. Author test cases up front, before implementation. Template: `test_reports/_TEMPLATE_functionality.md`.

## 5. Ask vs. proceed

Ask when "done" is undefined, requirements conflict, the change is destructive/irreversible, or it hinges on product intent. Otherwise proceed and note the assumption inline. Prefer one focused question.
