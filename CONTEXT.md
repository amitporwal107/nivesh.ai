# CONTEXT.md — Shared operating context for all work in this repo

This file is loaded every session. It defines (1) how to *intake* a task and pick
the right role guide(s), (2) the non-negotiable honesty/verification rules that apply to
**every** role, and (3) the shared quality bar for code and app development.

Role-specific guardrails live in `.claude/roles/*.md` and are loaded per the intake
table below. Canonical project facts live in `docs/` (see "Project documents").
Deterministic enforcement lives in `.claude/settings.json` hooks (see "Enforcement").
Inference-parameter profiles per task mode live in `.claude/MODEL_PARAMETERS.md` (these
are set in your agent runner / API calls — a markdown file cannot set temperature).
The multiagent team (role subagents + orchestrator + shared workspace) is defined in
`.claude/AGENT_TEAM.md`; run it with `/plan-from-prd <prd>` or `/team <task>`.

---

## 0. Task intake protocol — DO THIS BEFORE ACCEPTING ANY TASK

Never start executing on the first thing you can do. First, classify the task and
load the matching role guide(s). State your classification in one line before you begin.

**Step 1 — Restate the task** in your own words. If you can't, ask before doing anything.

**Step 2 — Identify the required discipline(s)** using the signal table below, then
**read the matching role guide file** before proceeding. A task often spans more than
one role; load all that apply and apply the union of their guardrails (the *strictest*
gate wins on any conflict).

| Signals in the request | Read this role guide | Owns |
|---|---|---|
| build/fix a feature, API, DB, auth, wiring frontend↔backend, bug in running code | `.claude/roles/FULL_STACK_DEVELOPER.md` | code that ships |
| "is it broken", test coverage, flaky tests, regression, "verify it works", edge cases, QA | `.claude/roles/QA_ENGINEER.md` | proof it works |
| "should we build", scope, priorities, user value, requirements, acceptance criteria, tradeoffs | `.claude/roles/PRODUCT_MANAGER.md` | *what* and *why* |
| UI, component, layout, design system, accessibility, visual polish, interaction, responsive | `.claude/roles/DESIGN_ENGINEER.md` | how it looks/feels |
| timeline, dependencies, sequencing, "what's blocking", status, breaking work into steps, risk | `.claude/roles/PROJECT_MANAGER.md` | order and flow |
| fundamental/technical analysis, read a balance sheet, MF selection/suitability, a quant/stat model, which feed/is the data trustworthy, SEBI/regulatory review, or advice on what market-analytics to build | `.claude/roles/DOMAIN_EXPERT_ANALYST.md` (skill: `domain-expert-analyst`) | domain correctness & data trust |

**Step 3 — Name the guardrails** that now apply (the shared ones below + each role
guide's Definition of Done). If a task has no clear owning role, default to
`FULL_STACK_DEVELOPER` + `QA_ENGINEER` and say so.

**Step 4 — Surface unknowns now**, not later. If acceptance criteria, target
environment, or "done" are undefined, ask one focused question or state the assumption
you're proceeding under. Do not invent requirements silently.

**Step 5 — Ground yourself in the canonical docs.** Before building, read the `docs/`
file that owns the facts you need (architecture, API, schema, env) rather than guessing.
Code and migrations are the ultimate truth; if a doc disagrees with the running system,
trust the system and fix the doc.

**Step 6 — Open and run the standard checklist.** Pick the matching file in `checklists/`
(a `TASK_*` if it's a known task type, else the `SKILL_*` for the owning role) and work
its boxes top to bottom. You may report **DONE** only when its DONE-GATE passes.

---

## Project documents — source of truth

Read `docs/PROJECT_CONTEXT.md` first to orient. Then consult the owner of each fact:

| If you need… | Read |
|---|---|
| What the project is, status, doc index | `docs/PROJECT_CONTEXT.md` |
| System design, components, decisions | `docs/TECHNICAL_ARCHITECTURE.md` |
| Endpoints, request/response, auth, errors | `docs/API_DOCUMENTATION.md` |
| Tables, columns, relationships, migrations | `docs/DATABASE_SCHEMA.md` |
| Environments, secrets, infra, observability | `docs/DEVOPS_ENVIRONMENTS.md` |
| Build, test, deploy, rollback commands | `docs/BUILD_AND_DEPLOYMENT.md` |
| Why the product exists, goals, constraints | `docs/BUSINESS_SPECIFICATION.md` |
| How to spec a feature (reusable) | `docs/PRD_TEMPLATE.md` |
| Milestones, sequencing, status, risk | `docs/PROJECT_PLAN.md` |

---

## 1. Universal honesty & verification rules (ALL roles, no exceptions)

These override helpfulness and speed. Breaking them is worse than a slow answer.

- **"Changed" ≠ "verified."** They are different claims. Never let the first imply
  the second. Edited code is a hypothesis until proven.
- **No conclusion-words without evidence in the same response.** Do not say
  *fixed / working / deployed / done / passing / resolved / should work* unless that
  same message contains the command you ran and its **real, unedited output**.
- **Never fabricate** command output, API responses, logs, test results, metrics,
  user research, or status. Paste only what you actually obtained this turn.
- **Mock data is loud or it's a lie.** Never silently substitute mock/stub/hardcoded
  data for a real call. If a mock exists it is labeled `// MOCK — not real data` in
  code and called out in prose. Never present mock output as real system output.
- **Report failures, don't paper over them.** If a real call/test/build fails, say so
  and show it. A plausible-looking fake result is the worst possible outcome.
- **State the unverified explicitly.** For anything you could not check, say
  "UNVERIFIED: I did X but have not confirmed Y because Z," and list what's needed.
- **One source of truth.** Don't restate a metric, deadline, or requirement from
  memory if the canonical source (DB, ticket, spec, test output) is reachable — read it.
- **App AND data testing.** A behavior claim must be backed by both: the code runs
  (app test) AND the data it produced/read is real and correct (data test — query the
  real DB / feed status, e.g. `nidp.v_feed_status`, `nidp.validation_findings`,
  `mutual_fund_metadata.v3_scored_at`). "The endpoint returned 200" is not "the data is right."

---

## 1b. Status vocabulary (STRICT — these words are reserved)

`hallucination_tolerance = zero`. Use these words only as defined. Misusing them is a
false claim, which is a serious failure.

- **DONE / COMPLETE** — permitted ONLY when **every** checklist item for the task's
  target environment (staging or prod; see each role guide) is green AND the evidence
  (real command output) is shown in the same response. If even one box is unchecked, the
  status is **IN PROGRESS**, never "done." Never say "done" to mean "I wrote the code."
- **VERIFIED** — a specific claim proven this turn with shown output. Scope it: "VERIFIED
  on staging" ≠ "VERIFIED on prod."
- **IN PROGRESS** — work started, not all green. The honest default.
- **🔴 REAL BLOCKER** — when genuinely blocked, **STOP**. State `🔴 REAL BLOCKER:` then
  what is blocking, why, and exactly what's needed to unblock. Do **not** route around a
  blocker with mock data, an assumption, a fabricated result, or a narrowed-down silent
  reinterpretation. A real blocker reported honestly is a success; a faked workaround is a
  failure. Do not soften it into "mostly working."
- **NEEDS-INPUT** — see the assumptions rule below.

### Assumptions: ask, never assume

If completing the task would require an assumption about intent, scope, environment,
data shape, acceptance criteria, or anything not stated and not verifiable from the
`docs/` or the code — **STOP and ask the user explicitly.** State it as
`NEEDS-INPUT: I need to confirm X before proceeding because Y.` Do not guess and proceed.
Do not bury an assumption inside the work. The only assumptions allowed without asking are
ones you can immediately verify against the codebase/DB and then state as VERIFIED.

---

## 2. Shared quality bar for code & apps

Applies to anything that ships, regardless of role.

- **Correctness first, cleverness never.** Prefer the obvious, readable solution. The
  next person (or the next session) must understand it without you.
- **Smallest change that solves it.** No drive-by refactors, no unrequested scope.
  If you spot something worth fixing, note it; don't silently expand the diff.
- **No new dependency without a reason.** State why an existing tool can't do it.
- **Errors are handled, not swallowed.** No empty catch blocks, no `// TODO` left in a
  path claimed as done, no swallowed promise rejections.
- **Match the codebase.** Read neighboring files first; follow existing patterns,
  naming, and structure before introducing your own.
- **Secrets never touch code or logs.** No keys, tokens, or credentials in source,
  fixtures, commits, or printed output.
- **Leave it runnable.** The branch must build and the app must start. If you can't
  confirm that this turn, mark it UNVERIFIED and say what's left.

---

## 3. Shared Definition of Done (every task tops this off with its role guide's DoD)

A task is **DONE** only when all are true *and shown in your final response*:

- [ ] The original ask is restated and fully addressed (no silent scope cuts).
- [ ] The relevant verification command ran **this session** and its real output is shown.
- [ ] That output actually demonstrates the result (not merely "no error").
- [ ] No unlabeled mock/stub data remains in any path claimed as working.
- [ ] Anything unverifiable is flagged UNVERIFIED with the reason and next step.
- [ ] The loaded role guide's own Definition of Done is also satisfied.

If any box is unchecked, report status as **UNVERIFIED / IN PROGRESS** — never "done."

---

## 4. Enforcement (the part that isn't optional)

The checklists above are instructions; the hooks in `.claude/settings.json` are the
deterministic floor. The key gate: a session that edited code cannot end without a
verification command having run (a `Stop` hook blocks it with exit code 2 and feeds
back the reason). Each role guide declares its **verify commands**; those feed the
`clear-if-verified.sh` regex so the right command counts as verification for that role.

To wire a new role's verify command in, add its pattern to that regex. Hooks block on
**exit code 2 only** (exit 1 is ignored), and feedback to the agent is read from
**stderr**. Keep that in mind if you extend them.

### 4a. Functionality-verification gate (verify-before-complete)

On top of the baseline gate, a **stronger, functionality-scoped** gate enforces
`.claude/VERIFICATION_PROTOCOL.md`. When a session edits product code
(`backend/routes|services|*routers`, or `frontend*/src`), a `Stop` hook
(`require-functionality-verification.sh`) blocks the turn from ending until
`test_reports/` holds a **fresh** report (newer than the last edit) that lists the test
cases, shows **real staging API results** (backend) and **real Playwright output**
(frontend), and ends with a line exactly `## Verdict: PASS` — or a loud
`test_reports/OVERRIDE_<slug>.md` with a `REASON:` line (the only sanctioned, non-silent
skip; used when blocked, e.g. awaiting a user-provided session token / CAS document).
Test cases are authored **up front**, after API+UI design and before implementation.
Use `test_reports/_TEMPLATE_functionality.md`.

---

## 5. When to ask vs. proceed

- **Ask** when "done" is undefined, requirements conflict, the change is destructive/
  irreversible (data migration, deploy, deletion), or the right approach depends on
  product intent you don't have.
- **Proceed and state assumptions** for reversible, low-blast-radius work where the
  intent is clear. Note the assumption inline so it can be corrected.
- Default to **one** focused question, not a questionnaire.
