# WORK_PROMPT — self-route, load skills, work

> The simple, prompt-based way to run a task. Paste this at the start of a task, or invoke
> `/work <task>`. It makes the agent load the right "skills" (role guides) on demand and work
> them — no subagents or orchestration needed. Honesty rules in `CONTEXT.md` §1/§1b still apply.

Before touching the task:

1. **RESTATE** it in one line. If the goal is unclear, ask — don't guess.

2. **IDENTIFY** the skill(s) needed by what the task touches (pick all; default
   FULL_STACK_DEVELOPER + QA_ENGINEER):
   - `FULL_STACK_DEVELOPER` — code that ships (feature, API, DB, auth, ingester, bug)
   - `QA_ENGINEER` — verifying behavior, tests, coverage, sign-off
   - `DESIGN_ENGINEER` — UI, component, styling, accessibility (V2 prod / V5 staging)
   - `PRODUCT_MANAGER` — scope, requirements, acceptance criteria, "should we build"
   - `PROJECT_MANAGER` — sequencing, dependencies, status, breaking work down

3. **LOAD** them, then state in ONE line what you loaded:
   - read `.claude/roles/<NAME>.md` for each skill,
   - the matching `checklists/` file (`TASK_*` if a known task type, else `SKILL_*`),
   - the `docs/` file that owns the facts you need (don't work from memory).

4. **ASK BEFORE ASSUMING.** Any load-bearing unknown → `NEEDS-INPUT: <question>`, stop, ask.
   Never invent requirements, data, or commands.

5. **WORK** the loaded checklist top to bottom. Target the right environment (staging first,
   then prod). Ground every claim in docs / code / real output. No unlabeled mocks.

6. **REPORT** with the strict vocabulary:
   - `DONE` only when the checklist's DONE-GATE passes WITH shown evidence — app test AND
     data test (real DB / feed status, not just HTTP 200);
   - else `IN PROGRESS`;
   - if stuck, `🔴 REAL BLOCKER:` <what> / <why> / <what's needed> — stop, don't fake a workaround.
