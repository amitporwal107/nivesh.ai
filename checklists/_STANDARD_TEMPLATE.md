# Checklist — ⟨NAME⟩

**Use when:** ⟨trigger⟩
**Target env:** ☐ Staging   ☐ Prod   *(promoting to prod? run the Staging gate first, then Prod)*
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` *(reserved — see DONE-GATE)* | `🔴 BLOCKED`

> Every checklist in this folder uses these exact sections. Section 0 (INTAKE) and the
> DONE-GATE are **identical in every file** — they are the non-negotiable bookends.
> Sections 1–4 hold the per-skill / per-task specifics. Tie every tick to shown evidence.

## 0. INTAKE  *(identical in every checklist)*
- [ ] Restated the task in my own words; scope is clear.
- [ ] Loaded the matching role guide(s) in `.claude/roles/`.
- [ ] Read the canonical `docs/` for any fact I need — did **not** guess.
- [ ] Any required assumption was raised to the user as `NEEDS-INPUT` and confirmed — never assumed silently.

## 1. PRE-FLIGHT  *(preconditions, branch, environment)*
- [ ] ⟨specifics⟩

## 2. EXECUTE  *(the work)*
- [ ] ⟨specifics⟩

## 3. VERIFY — STAGING  *(paste real, unedited output for each)*
- [ ] ⟨specifics⟩

## 4. VERIFY — PROD  *(only after Staging is green; stricter; read-only where noted)*
- [ ] ⟨specifics⟩

## DONE-GATE  *(identical in every checklist — the reserved-word gate)*
- [ ] Every box for the target environment is green AND its real output/evidence is shown in my response.
- [ ] **App test shown AND data test shown** (real DB / feed status — not just HTTP 200).
- [ ] No unlabeled mock/stub data anywhere in the path claimed working.
- [ ] No claim exceeds the evidence; "VERIFIED on staging" ≠ "VERIFIED on prod".
- [ ] Only if ALL the above hold → report **DONE**. Otherwise → **IN PROGRESS**.
- [ ] If blocked → STOP and report `🔴 REAL BLOCKER:` ⟨what⟩ / ⟨why⟩ / ⟨what's needed⟩. No workaround, mock, or guess.
