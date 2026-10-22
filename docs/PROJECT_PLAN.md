# PROJECT_PLAN.md — Nivesh.ai / NIDP

> Owned by PROJECT_MANAGER role. Honesty rule: status = verified reality. "DONE" only if the
> owning role's env checklist is green with evidence. Estimates are ranges with assumptions.

## 1. Status model
Per task: `NOT STARTED · IN PROGRESS · ON STAGING (verified) · IN PROD (verified) · 🔴 BLOCKED`.
Nothing is `IN PROD` unless it was `ON STAGING (verified)` first and merged to `main` via PR.

## 2. Known roadmap (from validated doc, 2026-05-29)

### A. NIDP 7-Gate Data Quality system — TECHNICAL_ARCHITECTURE §16
Current: Gate 3 tables live (migration 077); Gate 4 LIVE (migration 075). Rest PLANNED.
Rollout Q3–Q4 2026; each gate: Shadow (2w) → Canary (1w) → Progressive (2w) → Full.

| Phase | Weeks | Gates | Status |
|---|---|---|---|
| 1 | 1–4 | Gate 3 (Snapshot Completion) ⭐ | PARTIAL (tables live) |
| 2 | 5–8 | Gate 5 (Warm-Tier Export) | PLANNED |
| 3 | 9–14 | Gate 6 (API Output) + Copilot DQ | PLANNED |
| 4 | 15–22 | Gates 1+2 (Ingestion + Stream) | PLANNED |
| 5 | 23–26 | Gate 4 polish + Gate 7 SLO migration | PARTIAL (Gate 4 live) |

### B. Security hardening (DEVOPS gaps)
| Item | Severity | Status |
|---|---|---|
| Rotate any tokens in git history | CRITICAL | ONGOING |
| PAN AES-256 at rest | HIGH | PLANNED — scoped in §2D-2 |
| gitleaks in CI | HIGH | PLANNED |
| Admin MFA | MEDIUM | PLANNED |

### D. PII backlog (added 2026-10-22, from the AI Trading Bot PRD gap analysis)

Both items were raised by the user on 2026-10-22 and are NOT STARTED. Scoping notes are from real
probes of the staging image, not estimates, so the next session does not repeat the investigation.

**D-1 · Mask PII regions in CAS page images before upload — HIGH — NOT STARTED**

The PII guard merged in PR #285 (`services/llm_guard.py`) stops PAN, Aadhaar, mobile, email, DOB and
address reaching a model provider **in text**. It cannot help with images, and **all CAS parsers are
vision parsers**: `hybrid_cas_parser.py:286-289` sends base64 JPEGs of each page. A CAS page carries
every one of those details, so they still leave in full, as pixels. This is the largest remaining PII
flow in the product.

The user chose "mask regions before upload" over stopping vision parsing or accepting it with consent.

Scoping, probed in `nivesh/backend:staging` on 2026-10-22:
- `fitz` (PyMuPDF) **1.24.14 is installed** → for a text-layer PDF the PII can be located by
  `page.search_for()` and covered with a redaction annotation **without OCR**. That is the accurate,
  cheap path and covers the common NSDL/CDSL statement.
- `PIL` 12.3.0, `cv2` 4.13.0, `pdfplumber`, `pypdfium2`, `pikepdf` are installed; `pdftoppm` exists.
- `pytesseract` is installed but the **`tesseract` BINARY is NOT** (`shutil.which("tesseract")` →
  None). A scanned/photographed CAS therefore has no OCR path today: the image would need tesseract
  added to the backend image, or a different OCR.
- Must fail closed: if a page cannot be analysed, it must not be uploaded unredacted.
- `llm_safety.extract_pan()` already exists so a parser can keep the investor's PAN locally instead of
  asking the model to read it back.

**D-2 · Encryption at rest and on disk — HIGH — NOT STARTED**

Requested 2026-10-22 ("data encryption both in rest and on disk"). Read `docs/PII_ENCRYPTION_PLAN.md`
first; it predates this request and may already answer part of it.

The two readings solve different threats and the decision has not been made:
- **Column/application-level** (e.g. AES-256 on PAN, mobile, address, DOB in Postgres) — protects
  against a database dump or a read-only leak; needs a key-management decision and changes every read
  path that touches those columns. This is the existing `PAN AES-256 at rest` row above.
- **Volume/disk-level** on the CloudPe VMs — protects against physical/image theft; transparent to the
  app, but does nothing against an authenticated query.

Neither is started. No key store is in place.

### C. Scaffolded / not implemented (Admin console §18)
NIDP Diagnostics (SCAFFOLDED) · Grafana embed (SCAFFOLDED) · audit-log viewer (NOT IMPL) ·
data-retention sweeps (NOT IMPL) · DPO alerting (NOT IMPL) · SIEM (NOT IMPL) ·
`staging-data.niveshcopilot.com` CNAME (NOT LIVE) · V5 frontend prod rollout (staging only) ·
Sentry SDK instrumentation in app code (datasource only today).

## 3. Workstream template (per initiative)
| Task | Owner role | Depends on | Verify by | Status |
|---|---|---|---|---|
| ⟨…⟩ | FULL_STACK_DEVELOPER / QA_ENGINEER / DESIGN_ENGINEER | ⟨…⟩ | ⟨role env checklist⟩ | NOT STARTED |

## 4. Deploy-ordering rule
`dev` → staging verify (role checklist green, evidence) → PR → `main` → prod verify. No task
reaches prod before staging verification. Report blockers as `🔴 REAL BLOCKER`, never softened.

## 5. Risks & blockers
| Risk / blocker | Likelihood | Impact | Mitigation / unblock | Owner |
|---|---|---|---|---|
| Bad data → V3 scores → Copilot (pre-Gate-1/2) | M | H | Prioritize Gate 3; data-test in QA | — |
| Secrets in git history | M | H | Rotate; add gitleaks (planned) | — |
