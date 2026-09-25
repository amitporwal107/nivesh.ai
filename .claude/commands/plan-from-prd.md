---
description: From a PRD, run the Product + Project Manager team (with Design + Full-Stack feasibility and QA test plan) to produce a verified project plan in a shared workspace.
argument-hint: [path-to-PRD-file] [task-id]
allowed-tools: Task, Read, Grep, Glob, Write, Bash
---

You are the **orchestrator** for Plan-from-PRD mode. Follow `CONTEXT.md` and `AGENT_TEAM.md`.
You are the **sole writer** to the workspace; subagents are read-only and return content you persist.

Inputs: PRD = `$1`  ·  task-id = `$2` (if missing, derive a short slug from the PRD title).
If `$1` is empty or unreadable → STOP with `NEEDS-INPUT: which PRD file?` (do not assume one).

Steps:
1. Create the shared workspace: `cp -r .claude/workspace/_TEMPLATE .claude/workspace/<task-id>`.
   Set Overall status `IN PROGRESS` in `status.md`.
2. Spawn **product-manager** (give it the PRD path). Persist its reply to
   `.claude/workspace/<task-id>/spec.md`; update status. If it returned any load-bearing
   `NEEDS-INPUT` → write it to `status.md` (Open NEEDS-INPUT), PAUSE, and ask the user. Do not proceed.
3. In parallel, spawn **full-stack-developer** and **design-engineer**, each told to read
   `.claude/workspace/<task-id>/spec.md`. Persist their replies into `feasibility.md` (tech / UX).
4. Spawn **project-manager**, told to read `spec.md` + `feasibility.md`. Persist to `plan.md`
   (mirror `docs/PROJECT_PLAN.md`; every step names its `checklists/` file; statuses `NOT STARTED`).
5. Spawn **qa-engineer**, told to read `spec.md` + `plan.md`. Persist to `test-plan.md`.
6. Append a `decisions-log.md` entry per stage (decision + agent + rationale). Update `status.md`.
7. Present the assembled plan (link the workspace files). This is a **proposal** — nothing is
   built; do not claim DONE. Surface every remaining `NEEDS-INPUT`.

Rules: no fabricated effort/dates; ground in `docs/`/code; ask before assuming; one writer (you).
