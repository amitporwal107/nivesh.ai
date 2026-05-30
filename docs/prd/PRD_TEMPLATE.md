# PRD_TEMPLATE.md — Standard PRD (copy per feature)

> Reusable template. To spec a feature: copy this file to `docs/prd/⟨feature-name⟩.md`,
> fill the ⟨placeholders⟩, delete guidance. Owned by the PRODUCT role
> (`.claude/roles/PRODUCT_MANAGER.md`).
>
> **The acceptance criteria here are the contract QA verifies against** — write them so
> a tester (or code) can mechanically check pass/fail. No "should feel fast."

---

## Feature: ⟨name⟩
**Status:** DRAFT / APPROVED / BUILDING / SHIPPED · **Author:** ⟨…⟩ · **Date:** ⟨…⟩

## 1. Problem
⟨Who has what pain, and why now. One paragraph. Ties up to `BUSINESS_SPECIFICATION.md`.⟩

## 2. Goals & non-goals
- **Goals:** ⟨what this feature must achieve⟩
- **Non-goals:** ⟨what it deliberately will NOT do — prevents scope creep⟩

## 3. User stories
- As a ⟨user type⟩, I want ⟨capability⟩ so that ⟨outcome⟩.

## 4. Requirements
- **Functional:** ⟨numbered, testable behaviors⟩
- **Non-functional:** ⟨performance, security, accessibility, limits⟩

## 5. Acceptance criteria (the QA contract)
Write each as an observable pass/fail check.
- [ ] Given ⟨state⟩, when ⟨action⟩, then ⟨observable result⟩.
- [ ] Error case: given ⟨bad input⟩, then ⟨specific error behavior⟩.
- [ ] Edge case: ⟨empty / max / concurrent / unauthorized⟩ → ⟨expected⟩.

## 6. UX / design notes
⟨Flows, states (loading/empty/error), key screens. Owned with the DESIGNER role.
Reference mocks/tokens; list the states that must be handled.⟩

## 7. Technical notes
⟨APIs touched (link `API_DOCUMENTATION.md`), schema changes (link `DATABASE_SCHEMA.md`),
new dependencies + justification. Flag anything that needs an ADR.⟩

## 8. Dependencies & sequencing
⟨What must exist first. Hand to PROJECT role (`PROJECT_MANAGER.md`) for ordering.⟩

## 9. Risks
⟨What could go wrong + mitigation.⟩

## 10. Success metric & rollout
- **Measure:** ⟨how we know post-launch it worked⟩
- **Rollout:** ⟨flag / phased / full; rollback trigger⟩

## 11. Open questions
⟨Unresolved items with an owner. Resolve before status → APPROVED.⟩
