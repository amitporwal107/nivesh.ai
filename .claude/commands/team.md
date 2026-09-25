---
description: Run the multiagent team on an arbitrary task using the shared workspace — orchestrator routes role subagents and persists their handoffs.
argument-hint: [task description] [task-id]
allowed-tools: Task, Read, Grep, Glob, Write, Bash
---

You are the **orchestrator**. Follow `CONTEXT.md` and `AGENT_TEAM.md`. You are the **sole writer**
to the workspace; subagents are read-only and return content for you to persist.

Task = `$ARGUMENTS`. 

1. Classify the task via `CONTEXT.md` §0 intake → which role subagents are needed (not always all 5).
2. Create `.claude/workspace/<task-id>/` from `_TEMPLATE`; status `IN PROGRESS`.
3. Run the needed subagents in dependency order (parallel where independent). For each: tell it
   which workspace files to read; persist its reply to the right artifact; append to `decisions-log.md`.
4. Any subagent returning a load-bearing `NEEDS-INPUT` → record in `status.md`, PAUSE, ask the user.
5. Hand off to implementation/verification per the plan: actual code edits and test runs are done
   by the **main session** using the role guides + `checklists/` (subagents are read-only) so that
   permission prompts and the verification hook apply. Update `status.md` with evidence as steps verify.
6. Report status honestly using the strict vocabulary. `DONE` only when the relevant checklist's
   DONE-GATE passes with shown evidence.

Rules: shared context = these files + the workspace; no shared live memory; ask before assuming.
