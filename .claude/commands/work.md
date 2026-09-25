---
description: Self-route a task — analyze it, load the required skill(s) + checklist + docs, then work it under the project honesty rules.
argument-hint: [task description]
---

Follow `.claude/WORK_PROMPT.md` for this task: **$ARGUMENTS**

Do exactly its 6 steps in order. Crucially: in step 3 state which role guide(s), checklist,
and docs you loaded; in step 4 ask before assuming; in step 6 report with the strict vocabulary
(`DONE` only when the checklist DONE-GATE passes with shown evidence; else `IN PROGRESS`; or
`🔴 REAL BLOCKER`). Honesty rules in `CONTEXT.md` §1/§1b apply throughout.
