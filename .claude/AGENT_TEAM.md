# AGENT_TEAM.md — the Nivesh multiagent system & how context is shared

> **The one thing to understand.** Claude Code subagents each run in their **own isolated
> context window** and return only a summary to the parent. They do **not** share live
> memory. "Shared context" in this system is engineered, not automatic:
>
> 1. **Shared instructions (static)** — every agent inherits `CLAUDE.md`/`CONTEXT.md` and
>    reads the same `docs/`, `.claude/roles/`, `.claude/MODEL_PARAMETERS.md`, and
>    `checklists/`. Same grounding, same rules, same vocabulary for all.
> 2. **Shared workspace (dynamic)** — agents read and write artifact files in
>    `.claude/workspace/<task-id>/`. **The workspace is the shared memory.** State passes
>    between agents as files on disk, not as conversation.

## Roster

| Agent (`.claude/agents/`) | Role guide | Reads (context) | Produces |
|---|---|---|---|
| `product-manager` | PRODUCT_MANAGER.md | PRD, BUSINESS_SPEC, PRD_TEMPLATE | `spec.md` |
| `full-stack-developer` | FULL_STACK_DEVELOPER.md | TECH_ARCH, API, SCHEMA | `feasibility.md` (tech) |
| `design-engineer` | DESIGN_ENGINEER.md | tokens/components, PROJECT_CONTEXT | `feasibility.md` (UX) |
| `project-manager` | PROJECT_MANAGER.md | spec + feasibility + PROJECT_PLAN | `plan.md` |
| `qa-engineer` | QA_ENGINEER.md | spec + plan + checklists | `test-plan.md` |

The **orchestrator** is the main session (driven by a `/team-*` command), NOT a subagent —
nested subagent spawning is limited, and a single orchestrator keeps one writer.

## Who writes what (avoids races + write-approval issues)

- **Subagents are read-only** (`tools: Read, Grep, Glob`). They read shared context (static
  files + workspace artifacts on disk) and **return their output as their reply**.
- **The orchestrator is the SOLE writer** to `.claude/workspace/<task-id>/`. It persists each
  agent's reply to the right artifact, then points the next agent at that file. One writer =
  no concurrent-write corruption, and no subagent blocked on a write-permission prompt.

## Handoff protocol

```
orchestrator: create workspace/<task-id>/ from _TEMPLATE  (copy artifacts + status.md)
  └─ spawn product-manager        → reads PRD            → returns spec      → orch writes spec.md
  └─ spawn full-stack-developer   → reads spec + docs/   → returns tech      ┐
  └─ spawn design-engineer        → reads spec + tokens  → returns ux        ┘ orch writes feasibility.md
  └─ spawn project-manager        → reads spec+feasibility→ returns plan      → orch writes plan.md
  └─ spawn qa-engineer            → reads spec + plan    → returns test plan  → orch writes test-plan.md
  └─ orchestrator assembles + presents; appends to decisions-log.md, updates status.md
```

Agents that need each other's output **read the workspace file** (the orchestrator gives the
path) — that is the shared context in action. Parallel agents (full-stack + design) run
together; up to 10 subagents can run in parallel.

## Shared workspace artifacts (`.claude/workspace/_TEMPLATE/`)

| File | Owner (produces) | Purpose |
|---|---|---|
| `spec.md` | product-manager | validated problem, scope, **checkable acceptance criteria**, gaps |
| `feasibility.md` | full-stack + design | tech + UX feasibility, effort ranges, risks |
| `plan.md` | project-manager | ordered steps, owners, deps, critical path, per-env status |
| `test-plan.md` | qa-engineer | how each acceptance criterion gets verified (app + data) |
| `decisions-log.md` | orchestrator | append-only: every decision + who made it + why (prevents silent re-assumption) |
| `status.md` | orchestrator | single source of truth for task status (strict vocabulary) |
| `handoff.md` | orchestrator | running notes passed between agents / sessions |

## Rules inherited by every agent (from CONTEXT.md)

- Strict status vocabulary (§1b): `DONE` only when all-green-with-evidence; `🔴 REAL BLOCKER`;
  `NEEDS-INPUT` — **ask, never assume**. Any agent hitting a load-bearing unknown writes
  `NEEDS-INPUT` to its reply; the orchestrator surfaces it to the user and **stops** the pipeline.
- No fabricated data/effort/dates; ground every claim in `docs/`, code, or real output.
- Plans/specs are proposals (status `NOT STARTED`), not claims that anything is built.

## Cost/quality routing (optional)
Per-agent `model:` can route reasoning-heavy agents (PM, PjM, full-stack) to a stronger model
and high-volume ones to a cheaper one. Temperature is **not** per-subagent settable — see
`MODEL_PARAMETERS.md`; use the behavioral guardrails + extended thinking instead.
