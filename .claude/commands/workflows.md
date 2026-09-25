---
description: Check the status of running or recently completed background workflows.
argument-hint: [workflow run ID or blank for latest]
---

Check the status of background workflow agents.

1. If $ARGUMENTS contains a run ID (starts with `wf_`), use TaskOutput with that ID (block=false, timeout=5000) to get current status.

2. If no argument given, look in the session's workflow transcript directory for recent runs:
   - Check `/root/.claude/projects/-app/` for the most recent session directory
   - List workflow script files under `.../workflows/scripts/` to find recent runs
   - For each, report: workflow name, run ID, status, phases completed, agent results

3. For each workflow found, report:
   - **Name** and **Run ID**
   - **Status**: running / completed / failed
   - **Phase**: which phase is active
   - **Agents**: how many passed / failed / still running
   - **Errors**: any agents that failed, with their error

4. If the workflow is still running, say so clearly and remind the user they will be
   notified automatically when it completes — no need to poll manually.

5. If the workflow completed, summarise what changed (files edited, tests passed/failed)
   and what the next step is.

Apply the honesty rules from CONTEXT.md §1: never claim something is done without evidence.
