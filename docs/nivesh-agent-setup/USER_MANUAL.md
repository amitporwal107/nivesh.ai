# USER_MANUAL.md — how to use the Nivesh.ai / NIDP agent setup

A practical guide to running your Claude Code agent against this repo so it produces
verified, honest, project-grounded work. Read top to bottom once; after that use the
Quick Reference at the end.

---

## 1. What this is (30-second version)

A configuration layer that makes the coding agent: (1) **load the right skill** for a task,
(2) **work from real project facts** instead of guessing, (3) **verify with real output**
before claiming anything, and (4) **stop and ask** instead of assuming. It has two modes —
a simple prompt-based path for daily work, and an optional multiagent path for planning.

Map of every file: see `PROJECT_STRUCTURE.md`.

---

## 2. One-time setup

1. **Activate the rules.** Rename `CONTEXT.md` → `CLAUDE.md`, **or** create a `CLAUDE.md`
   containing one line: `@CONTEXT.md`. (Claude Code only auto-loads a file named `CLAUDE.md`.)
2. **Turn on enforcement.** From the repo root:
   ```bash
   chmod +x .claude/hooks/*.sh
   jq --version    # hooks need jq; install if missing (brew/apt install jq)
   ```
   Start Claude Code and run `/hooks` — you should see PostToolUse + Stop entries.
3. **Drop in your architecture doc.** Paste your validated master document into
   `docs/TECHNICAL_ARCHITECTURE.md` (replacing the placeholder body).
4. **Fill the gaps.** Replace `NEEDS-INPUT` business metrics in `docs/BUSINESS_SPECIFICATION.md`.
5. **Commit it all** so every teammate inherits the same context, skills, and guardrails.

That's it. No build step.

---

## 3. The two ways to operate

| Mode | Use for | How |
|---|---|---|
| **Simple (default)** | day-to-day: fix a bug, add a feature, write a migration | `/work <task>` or paste `.claude/WORK_PROMPT.md` |
| **Multiagent (optional)** | turning a PRD into a project plan | `/plan-from-prd <prd>` or `/team <task>` |

You almost always want the simple path. The multiagent path is for planning, not coding.

---

## 4. Daily use — the simple path

Type your task. Either invoke `/work` or just describe it (CONTEXT.md makes the agent
self-route either way):

```
/work fix the Goals page showing no data on staging
```

What the agent does, in order:
1. **Restates** the task; asks if unclear.
2. **Identifies the skill(s)** — here `FULL_STACK_DEVELOPER` (+ `QA_ENGINEER`).
3. **Loads them** — reads `.claude/roles/FULL_STACK_DEVELOPER.md`, the matching checklist
   (`checklists/TASK_bug_fix.md`), and the relevant doc (`docs/API_DOCUMENTATION.md` /
   `DATABASE_SCHEMA.md`). It states what it loaded in one line.
4. **Asks before assuming** — if something load-bearing is unknown, it stops with `NEEDS-INPUT`.
5. **Works the checklist** — reproduces, fixes at root cause, runs the real verify commands.
6. **Reports** with the strict vocabulary (below).

You don't have to name the skill — the agent picks it. You *can* steer it ("use the QA
checklist", "target staging only") and it will.

---

## 5. How to read the agent's output (the vocabulary)

These words are reserved and mean exactly one thing. This is what protects you from
"it's fixed" when it isn't:

- **DONE / COMPLETE** — every checklist box for the target environment is green **and** the
  real command output is shown. If you see "DONE" without pasted output, that's a bug — push back.
- **IN PROGRESS** — started, not all green. The honest default.
- **🔴 REAL BLOCKER** — the agent is genuinely stuck and **stopped**. It tells you what's
  blocking, why, and what it needs. It will **not** fake a workaround. This is success, not failure.
- **NEEDS-INPUT** — an assumption would be required; the agent stopped and is asking you.
  Answer it; it won't proceed on a guess.

Example of a healthy "blocked" response you *want* to see:
> `🔴 REAL BLOCKER:` Can't reach staging at `staging.niveshcopilot.com/api/healthz` (connection
> refused). I changed the Zod `horizon_years` coercion but have NOT verified it. Need the staging
> stack up, or confirmation to test against a local instance.

Example of a healthy "done" response:
> `DONE` on staging. Ran `make verify` → 12/12 passed [output]. `curl …/api/healthz` → ok [output].
> Goals endpoint now returns rows; queried staging DB, no `BLOCK` findings [output].

---

## 6. The checklists

Every task type has a standard checklist in `checklists/` (same shape every time:
INTAKE → PRE-FLIGHT → EXECUTE → VERIFY STAGING → VERIFY PROD → DONE-GATE). The agent opens the
matching one and works the boxes. You can open the same file to see exactly what "done" requires
for that task — there's no hidden bar. If a checklist's items don't match your team's reality,
edit that file; the structure stays fixed.

---

## 7. The hooks (enforcement) — what you'll see

The hooks are the part the agent can't talk its way around:
- After it edits code, a flag is set.
- A real verify command (`make verify`, `yarn build`, `pytest`, `./test_locally.sh`, a health
  `curl`) clears the flag.
- If the agent tries to end its turn having edited code but run **no** verification, the **Stop
  hook blocks it** and feeds back: *"you edited code but ran no verification command…"* — and it
  keeps working until it verifies.

If the gate won't clear after a genuine test run, your command isn't in the regex —
add it to `VERIFY_RE` in `.claude/hooks/clear-if-verified.sh` (and keep it in sync with
`docs/BUILD_AND_DEPLOYMENT.md` and the role checklists).

---

## 8. Staging vs prod

Every checklist has separate staging and prod gates, and the rule is **staging first**:
`dev branch → verify on staging.niveshcopilot.com → PR → main → verify on niveshcopilot.com`.
Prod verification is **read-only** — the agent won't run write/load/destructive operations
against production; if a task seems to require that, it raises `🔴 REAL BLOCKER` and asks for
explicit sign-off.

---

## 9. The optional multiagent path (PRD → plan)

When you have a PRD and want a project plan rather than code:

```
/plan-from-prd docs/prd/my-feature.md my-feature
```

The orchestrator spins up a shared workspace (`.claude/workspace/my-feature/`) and runs the
team: product-manager writes the spec → full-stack + design assess feasibility →
project-manager builds the ordered plan → qa-engineer writes the test plan. Because subagents
don't share live memory, they share **files** in that workspace — that's the shared context.
The output is a *proposal* (everything `NOT STARTED`); actual building is then done via the
simple `/work` path. If any agent hits a load-bearing unknown, the pipeline pauses with
`NEEDS-INPUT` and asks you.

---

## 10. Worked examples

**Fix a bug**
```
/work Goals page returns empty on staging since the horizon_years change
```
→ loads FULL_STACK_DEVELOPER + TASK_bug_fix → reproduces → finds root cause → fixes →
`make verify` + staging health + DB data-test shown → `DONE` on staging, or `🔴 REAL BLOCKER`.

**Add a feature**
```
/work add CSV export to the MFD client list, behind a feature flag
```
→ FULL_STACK_DEVELOPER (+ DESIGN_ENGINEER if UI) + TASK_new_feature → built behind a flag →
staging verify → asks before assuming any unstated requirement.

**Database migration**
```
/work add a nullable consent_at column to users
```
→ TASK_db_migration → forward-only `IF NOT EXISTS` → applied on staging DB, output shown →
destructive? → `🔴 REAL BLOCKER` + asks for sign-off + snapshot.

**Plan a PRD**
```
/plan-from-prd docs/prd/goal-sharing.md goal-sharing
```
→ team produces spec + feasibility + plan + test-plan in `.claude/workspace/goal-sharing/`.

---

## 11. Maintaining & extending

- **New task checklist:** copy `checklists/_STANDARD_TEMPLATE.md`, keep INTAKE + DONE-GATE
  verbatim, fill sections 1–4. Add it to the `WORK_PROMPT` mental map if it's common.
- **New skill/role:** add `.claude/roles/<NAME>.md` (follow an existing one), add a row to the
  CONTEXT.md intake table and a `checklists/SKILL_<NAME>.md`.
- **Changed test/build commands:** update them in three places that must agree — the role
  checklists, `docs/BUILD_AND_DEPLOYMENT.md`, and the hook `VERIFY_RE` regex.
- **Docs drift:** when code changes, fix the owning `docs/` file. Code/migrations are the truth.

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Agent claims "fixed" with no output | Push back; ensure `CONTEXT.md` is active as `CLAUDE.md`. |
| `/hooks` shows nothing | `chmod +x .claude/hooks/*.sh`; install `jq`; confirm `.claude/settings.json` exists. |
| Stop hook never blocks | Exec bit missing, or you exited 1 not 2 if you edited the script. |
| Verify gate won't clear after a real test | Add your command to `VERIFY_RE` in `clear-if-verified.sh`. |
| Agent invents requirements | It should `NEEDS-INPUT` instead — check `CONTEXT.md` §1b is loaded. |
| Agent picks the wrong skill | Name it explicitly ("use the QA checklist") or refine the intake table. |
| Subagent blocked on a write | Expected — subagents are read-only; the orchestrator writes. |

---

## 13. Quick reference

**Commands**
- `/work <task>` — self-route + work (daily driver)
- `/plan-from-prd <prd> [id]` — PRD → project plan (team)
- `/team <task> [id]` — generic multiagent orchestrator
- `/hooks` — confirm enforcement is loaded

**Key files**
- `CONTEXT.md` (→ `CLAUDE.md`) — rules + routing
- `.claude/WORK_PROMPT.md` — the self-route prompt
- `.claude/roles/*.md` — the skills
- `checklists/*.md` — the standard checklists
- `docs/*.md` — canonical project facts
- `.claude/hooks/*` — enforcement

**Vocabulary:** `DONE` (all green + evidence) · `IN PROGRESS` · `🔴 REAL BLOCKER` · `NEEDS-INPUT`

**Golden rule:** if it's not backed by shown output, it's not DONE. Ask before assuming.
