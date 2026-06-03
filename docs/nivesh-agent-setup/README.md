# Setup — repo layout & how the pieces fit

```
your-repo/
├── CONTEXT.md                        # rename to CLAUDE.md, or @import it from CLAUDE.md
│                                     #   = HOW the agent behaves (intake, rules, quality bar)
├── docs/                             # = FACTS about this project (canonical sources)
│   ├── PROJECT_CONTEXT.md            #   read first: overview + status + doc index
│   ├── TECHNICAL_ARCHITECTURE.md
│   ├── API_DOCUMENTATION.md
│   ├── DATABASE_SCHEMA.md
│   ├── DEVOPS_ENVIRONMENTS.md
│   ├── BUILD_AND_DEPLOYMENT.md
│   ├── BUSINESS_SPECIFICATION.md
│   ├── PRD_TEMPLATE.md               #   reusable: copy to docs/prd/<feature>.md per feature
│   └── PROJECT_PLAN.md
└── .claude/
    ├── settings.json                 # the hooks (deterministic enforcement)
    ├── hooks/                        # mark-unverified.sh, clear-if-verified.sh, require-verification.sh
    └── roles/                        # per-role guardrails + Definition of Done
        ├── FULL_STACK_DEVELOPER.md
        ├── QA_ENGINEER.md
        ├── DESIGN_ENGINEER.md
        ├── PRODUCT_MANAGER.md
        └── PROJECT_MANAGER.md
```

## How the layers fit

1. **`CONTEXT.md`** loads every session. Its intake protocol makes the agent classify
   the task, read the matching **role guide(s)**, and ground itself in the relevant
   **`docs/`** file before acting. Its universal rules + quality bar apply to everything.
2. **`docs/`** holds the project's source-of-truth facts. The agent reads the owner of
   a fact (schema, API, architecture) instead of guessing — this is what raises code
   quality: decisions are grounded in real architecture, not invented.
3. **`.claude/roles/`** holds the role guardrails and per-role Definition of Done.
4. **The hooks** are the deterministic floor: a code-editing session can't end without
   a verification command having run.

## Important: role guides are NOT native Claude Code skills anymore

Native skill auto-trigger requires the file to be named `SKILL.md` inside a folder. With
descriptive filenames (`FULL_STACK_DEVELOPER.md` etc.), they don't auto-trigger — instead
`CONTEXT.md`'s intake table tells the agent which role guide to read for a given task.
For this to work reliably, make sure `CONTEXT.md` is active (renamed to `CLAUDE.md` or
`@CONTEXT.md`-imported), so the intake routing is always in context.

## To activate

- Rename `CONTEXT.md` → `CLAUDE.md`, or add `@CONTEXT.md` to your `CLAUDE.md`.
- Fill the ⟨placeholders⟩ in `docs/` with your real project facts.
- In `docs/BUILD_AND_DEPLOYMENT.md` and each role guide's "Verify commands", put your
  project's real test/build commands, and mirror those patterns into the hook's
  `clear-if-verified.sh` regex so a real run actually clears the verification gate.
- `chmod +x .claude/hooks/*.sh`; run `/hooks` in Claude Code to confirm they loaded.
- Commit everything so the whole team inherits the same context and guardrails.

## Quick test

Ask the agent to fix a trivial bug. It should: (1) state which role guide(s) it read and
why, (2) read the relevant `docs/` file rather than guess, (3) reproduce/verify before
claiming the fix, (4) refuse to end claiming "fixed" until it shows real command output —
and if it tries, the Stop hook blocks it.
