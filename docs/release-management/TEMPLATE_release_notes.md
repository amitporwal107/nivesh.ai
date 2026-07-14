# Release Notes — Generic Template

> Generic, reusable skeleton interpreted from `release_notes_v4.2.0.md`.
> Fill every `<...>` token. Sections marked *(optional)* may be omitted when empty.
> This template also defines the **structured content model** the in-app authoring
> form renders (see `docs/release-management/DESIGN.md` → Data Model).

**Document type:** `release_notes`
**Release version (semver):** `<MAJOR.MINOR.PATCH>`

---

## 1. Document Information

| Field | Value |
|---|---|
| Document Title | Release Notes — <Product> v<version> |
| Version | <version> |
| Release Date | <YYYY-MM-DD> |
| Document Status | Draft \| In Review \| Approved \| Final |
| Prepared By | <team/person> |
| Reviewed By | <person(s)> |
| Approved By | <person> |
| Environment | Staging \| Production |
| Related Sprint | <sprint / date range> |

## 2. Release Summary

<One paragraph: what this release delivers.>

| Category | Count | Priority Breakdown |
|---|---|---|
| New Features | <n> | <x High · y Medium · z Low> |
| Bug Fixes | <n> | <critical/high/medium> |
| Performance Improvements | <n> | <...> |
| Security Patches | <n> | <...> |
| Deprecated Features | <n> | — |

## 3. New Features

> Repeat this block per feature.

### <FEAT-ID> — <Feature name>
- **Priority:** High \| Medium \| Low
- **Module:** <module>
- **Description:** <what it does>
- **Changes Made:**
  - <change 1>
  - <change 2>
- **Impact Analysis:**

  | Area | Impact | Risk Level |
  |---|---|---|
  | <Frontend/API/DB/Perf/Infra> | <impact> | Low \| Medium \| High |

## 4. Bug Fixes

| Bug ID | Severity | Module | Description | Root Cause | Fix Summary |
|---|---|---|---|---|---|
| <BUG-ID> | Critical \| High \| Medium | <module> | <desc> | <cause> | <fix> |

## 5. Testing Verification

### 5.1 Test Coverage Summary
| Test Type | Total | Passed | Failed | Skipped | Pass Rate |
|---|---|---|---|---|---|
| Unit | | | | | |
| Integration | | | | | |
| E2E | | | | | |
| Regression | | | | | |
| Security | | | | | |
| UAT | | | | | |

### 5.2 Known Failing Tests & Mitigations *(optional)*
| Test ID | Type | Description | Risk | Mitigation |
|---|---|---|---|---|
| | | | | |

### 5.3 Feature-Level Coverage *(optional)*
| Feature / Bug | Unit | Integration | E2E | UAT | Security | Overall |
|---|---|---|---|---|---|---|
| | | | | | | |

## 6. Impact Analysis

### 6.1 System Component Impact Matrix
| Component | Impacted? | Change Type | Risk | Rollback Plan |
|---|---|---|---|---|
| | | | | |

### 6.2 Performance Impact *(optional)*
| Metric | Before | After | Delta | Status |
|---|---|---|---|---|
| | | | | |

### 6.3 Security Impact *(optional)*
| Area | Change | Compliance Impact |
|---|---|---|
| | | |

## 7. Rollback & Deployment Plan
- **Deployment Steps:** <ordered steps>
- **Rollback Triggers:** <conditions>
- **Rollback Procedure:** <steps + owners>

## 8. Approval & Sign-Off

| Role | Name | Date | Status |
|---|---|---|---|
| QA Lead | | | Pending \| Approved |
| Tech Lead | | | |
| Product Manager | | | |
| Security Officer | | | |
| VP Engineering | | | |
