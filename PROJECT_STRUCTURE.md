# PROJECT_STRUCTURE.md — map of the Nivesh.ai / NIDP agent setup

```
nivesh-repo/
│
├── CONTEXT.md                      # ⭐ Agent operating rules — rename to CLAUDE.md (or @import).
│                                   #    Intake protocol, honesty rules, STRICT status vocabulary
│                                   #    (DONE/🔴 REAL BLOCKER/NEEDS-INPUT), quality bar, doc index.
├── README.md                       # Setup / how the layers fit / activation steps.
├── PROJECT_STRUCTURE.md            # This file — the map.
│
├── docs/                           # 📚 CANONICAL PROJECT FACTS (the agent reads, never guesses)
│   ├── PROJECT_CONTEXT.md          #    Read first: product, stack, status, doc index, constraints.
│   ├── TECHNICAL_ARCHITECTURE.md   #    ⚠ placeholder + section map — paste your validated master doc here.
│   ├── API_DOCUMENTATION.md        #    DaaS + Nivesh App API conventions, endpoint groups.
│   ├── DATABASE_SCHEMA.md          #    3 DBs (NIDP TimescaleDB, Nivesh PG, Mongo) + migration rules.
│   ├── DEVOPS_ENVIRONMENTS.md      #    Env matrix, ports, secrets, infra, observability, gaps.
│   ├── BUILD_AND_DEPLOYMENT.md     #    Real build/test/deploy/rollback commands + verify list.
│   ├── BUSINESS_SPECIFICATION.md   #    Product/users/value/constraints (metrics = NEEDS-INPUT).
│   ├── PRD_TEMPLATE.md             #    Reusable PRD template (copy per feature).
│   └── PROJECT_PLAN.md             #    Roadmap: DQ gates, security gaps, scaffolded items, statuses.
│
├── checklists/                     # ✅ STANDARD, RUNNABLE CHECKLISTS (uniform shape)
│   ├── _STANDARD_TEMPLATE.md       #    The fixed structure every checklist follows.
│   ├── README.md                   #    How to pick one.
│   ├── SKILL_FULL_STACK_DEVELOPER.md   # per-skill
│   ├── SKILL_QA_ENGINEER.md
│   ├── SKILL_DESIGN_ENGINEER.md
│   ├── SKILL_PRODUCT_MANAGER.md
│   ├── SKILL_PROJECT_MANAGER.md
│   ├── TASK_new_feature.md             # per-task-type
│   ├── TASK_bug_fix.md
│   ├── TASK_db_migration.md
│   ├── TASK_new_nidp_ingester.md
│   ├── TASK_deploy_release.md
│   └── TASK_ui_component.md
│
└── .claude/                        # ⚙ AGENT CONFIG
    ├── settings.json               #    Hooks wiring (PostToolUse / Stop).
    ├── WORK_PROMPT.md              # ⭐ Simple self-route prompt: load required skills → work.
    ├── MODEL_PARAMETERS.md         #    Inference profiles (apply in your runner; temp not settable in md).
    ├── AGENT_TEAM.md               #    Multiagent contract + how context is shared (optional layer).
    │
    ├── roles/                      # 🧠 THE "SKILLS" — role guides loaded on demand
    │   ├── FULL_STACK_DEVELOPER.md
    │   ├── QA_ENGINEER.md
    │   ├── DESIGN_ENGINEER.md
    │   ├── PRODUCT_MANAGER.md
    │   └── PROJECT_MANAGER.md
    │
    ├── hooks/                      # 🔒 DETERMINISTIC ENFORCEMENT (the hard floor)
    │   ├── mark-unverified.sh      #    code edited → mark session unverified
    │   ├── clear-if-verified.sh    #    real verify command (make verify/yarn build/pytest/health) → clear
    │   └── require-verification.sh #    Stop hook: blocks "done" if no verification ran
    │
    ├── commands/                   # ▶ SLASH COMMANDS
    │   ├── work.md                 #    /work <task>  — self-route + work (the simple path)
    │   ├── plan-from-prd.md        #    /plan-from-prd <prd>  — PM+PjM team → project plan (optional)
    │   └── team.md                 #    /team <task>  — generic multiagent orchestrator (optional)
    │
    ├── agents/                     # 👥 SUBAGENTS (optional multiagent layer; read-only specialists)
    │   ├── product-manager.md
    │   ├── full-stack-developer.md
    │   ├── design-engineer.md
    │   ├── project-manager.md
    │   └── qa-engineer.md
    │
    └── workspace/                  # 🗂 SHARED MEMORY for the multiagent layer (files = shared context)
        └── _TEMPLATE/              #    copied to workspace/<task-id>/ per task
            ├── status.md           #    single source of truth (strict vocabulary)
            ├── spec.md             #    product-manager output
            ├── feasibility.md      #    full-stack + design output
            ├── plan.md             #    project-manager output
            ├── test-plan.md        #    qa-engineer output
            ├── decisions-log.md    #    append-only (prevents silent re-assumption)
            └── handoff.md          #    running notes between agents/sessions
```

## Two ways to operate
- **Simple (recommended for daily work):** `CONTEXT.md` + `docs/` + `roles/` + `checklists/` + `hooks/`,
  driven by `WORK_PROMPT.md` / `/work`. The agent self-routes, loads the skills it needs, and works.
- **Multiagent (optional, for PRD→plan):** add `AGENT_TEAM.md` + `agents/` + `commands/` + `workspace/`.

## Activation (once)
1. Rename `CONTEXT.md` → `CLAUDE.md` (or add `@CONTEXT.md` to a `CLAUDE.md`).
2. `chmod +x .claude/hooks/*.sh`; run `/hooks` to confirm they loaded (needs `jq`).
3. Paste your validated master doc into `docs/TECHNICAL_ARCHITECTURE.md`.
4. Commit everything so the team inherits the same context + guardrails.
```
