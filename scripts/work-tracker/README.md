# Work Tracker — ADVW ticket generators

Idempotent scripts that seed/maintain the **Advisory Workflows (ADVW)** program in the
`/api/work` tracker (the `/v5/work` Project Dashboard). Admin-only API; every script reads
the token from `$NIVESH_ADMIN_TOKEN` and the base URL from `$NIVESH_BASE`
(default `https://staging.niveshcopilot.com`). All are deduped by `sig` (prefix `advw:`),
so re-runs update rather than duplicate. Each supports `--dry-run`.

## Run order
1. `post_work_items.py`        — create the base tickets (Phase-0 tasks + Phase 1–3 epics + tracking row)
2. `migrate_work_hierarchy.py` — create the **ADVW project** + Phase-1 epics/stories, re-parent tasks into **Project → Epic → Story → Task**, stamp `project=ADVW`
3. `apply_templates.py`        — reformat every epic/story/task into the standard **Epic / Story / Task** templates (title + `requirements_md`)
4. `add_design_tasks.py`       — add **Design Tasks** (design template) under the UI-bearing stories/epics

## Usage
```
NIVESH_ADMIN_TOKEN='<staging admin session_token>' \
NIVESH_BASE='https://staging.niveshcopilot.com' \
python3 scripts/work-tracker/migrate_work_hierarchy.py --dry-run   # preview
```

## Notes
- These seed **DATA** in the target environment's MongoDB — they are not application code.
  To seed another environment (e.g. prod), run against that env's `NIVESH_BASE` with an
  admin token for it.
- Requires the backend `backend/routes/work.py` hierarchy fields
  (`issue_type` project/epic/story/task, `project`, `parent`, `phase`, `track`, `workflow`,
  `requirements_md`, …) — shipped in commit `e2045020`.
