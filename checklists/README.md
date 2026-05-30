# checklists/ — standard, runnable checklists

Every file here uses the **same structure** (defined in `_STANDARD_TEMPLATE.md`):
`0. INTAKE → 1. PRE-FLIGHT → 2. EXECUTE → 3. VERIFY (STAGING) → 4. VERIFY (PROD) → DONE-GATE`.
Section 0 and the DONE-GATE are **identical across every file** — the non-negotiable bookends.
Every tick must be backed by shown evidence; the reserved words (`DONE`, `🔴 REAL BLOCKER`,
`NEEDS-INPUT`) are defined in `CONTEXT.md` §1b.

## How to pick one
1. Is this a known **task type**? Use the `TASK_*` file.
2. Otherwise, use the **skill** file for the owning role (`SKILL_*`).
3. Multi-step work: PROJECT_MANAGER sequences it; each step runs its own checklist.

## Files
| Skill | Task type |
|---|---|
| `SKILL_FULL_STACK_DEVELOPER.md` | `TASK_new_feature.md` |
| `SKILL_QA_ENGINEER.md` | `TASK_bug_fix.md` |
| `SKILL_DESIGN_ENGINEER.md` | `TASK_db_migration.md` |
| `SKILL_PRODUCT_MANAGER.md` | `TASK_new_nidp_ingester.md` |
| `SKILL_PROJECT_MANAGER.md` | `TASK_deploy_release.md` |
| `_STANDARD_TEMPLATE.md` (the shape) | `TASK_ui_component.md` |

## Adding a checklist
Copy `_STANDARD_TEMPLATE.md`, keep sections 0 and DONE-GATE verbatim, fill 1–4. Keep items
binary and evidence-bound. Don't invent a new structure — standardization is the point.
