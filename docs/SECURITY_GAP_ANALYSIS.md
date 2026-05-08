# NIVESH Security Gap Analysis

**Date:** 2026-05-07
**Source PRD:** [SECURITY_PRD.md](./SECURITY_PRD.md)
**Methodology:** Static code review of `/app` against each FR-* requirement in the PRD. Every finding cites a file path and line number. Severities follow the PRD's risk model (Critical = data breach / live exposure; High = strong control gap; Medium = hardening gap; Low = nice-to-have).

---

## TL;DR — Immediate Action Required

> **CRITICAL — live admin session tokens committed to repo.**
> [memory/test_credentials.md](../memory/test_credentials.md) contains two active admin session tokens (`370eff71-…`, `3352751a-…`) for `priyankamantri@gmail.com` and `aporwal107@gmail.com`, both `is_admin: true`, both valid until **2026-05-25**. Anyone with repo read access today can call any admin endpoint (including `/api/admin/secrets/{key}/reveal`).
>
> **Action within 24h:** invalidate both sessions in MongoDB (`db.user_sessions.deleteMany`), rotate any secret previously readable by an admin, and remove the file from git history.

| Bucket | Critical | High | Medium | Low |
| --- | --- | --- | --- | --- |
| Secrets / credentials in repo | **1** | 1 | 1 | 0 |
| Authentication & sessions | 0 | 1 | 2 | 0 |
| Authorization & RBAC | 0 | 2 | 2 | 0 |
| Broker connect | 0 | 0 | 1 | 1 |
| File upload | 0 | **3** | 2 | 0 |
| Data protection (encryption, PII) | 0 | 2 | 2 | 0 |
| API security | 0 | 0 | 3 | 1 |
| Audit logging | 0 | 0 | 3 | 1 |
| Encryption at rest / in transit | 0 | 2 | 1 | 0 |
| Frontend security headers | 0 | 1 | 2 | 0 |
| AI / LLM security | 0 | 2 | 2 | 0 |
| Monitoring & incident response | 0 | 2 | 2 | 0 |
| **Total** | **1** | **16** | **23** | **3** |

---

## 1. Authentication & Identity (FR-AUTH-001…006) — Strong (with gaps)

**Exists**
- Google OAuth via `id_token` verification, audience-validated against `GOOGLE_CLIENT_ID` — [backend/routes/auth.py:14-46](../backend/routes/auth.py#L14-L46).
- Session = UUID in `db.user_sessions`, 7-day expiry — [backend/routes/auth.py:76-82](../backend/routes/auth.py#L76-L82).
- Cookie attrs `httponly=True, secure=True, samesite="none"` — [backend/routes/auth.py:85-92](../backend/routes/auth.py#L85-L92).
- Session validation on every request — [backend/deps.py:39-81](../backend/deps.py#L39-L81).
- Login / logout / failed-login audit — [backend/routes/auth.py:96-105](../backend/routes/auth.py#L96-L105).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| AUTH-G1 | No mobile OTP / passwordless flow | FR-AUTH-002 | High |
| AUTH-G2 | No MFA on admin accounts | FR-RBAC-004 | High |
| AUTH-G3 | 7-day session, no short-lived access + refresh-token rotation | FR-AUTH-004,5 | Medium |
| AUTH-G4 | No device recognition / suspicious-login detection | §7.1 | Medium |

---

## 2. Authorization & RBAC (FR-RBAC-001…004) — Partial

**Exists**
- Binary admin gate `require_admin()` — [backend/deps.py:84-89](../backend/deps.py#L84-L89).
- Per-resource ownership on broker accounts — [backend/routes/broker_connect.py:71-77](../backend/routes/broker_connect.py#L71-L77).
- `user_id`-scoped filters on compliance / portfolio / export — [backend/routes/compliance.py:38-80](../backend/routes/compliance.py#L38-L80).
- Advisor impersonation falls back safely — [backend/deps.py:66-80](../backend/deps.py#L66-L80).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| RBAC-G1 | No role enum (advisor / support / viewer) — only `is_admin` boolean | FR-RBAC-001 | High |
| RBAC-G2 | Tenant isolation is implicit (per-query filters); no row-level enforcement | FR-RBAC-002 | High |
| RBAC-G3 | Admin ops (incl. secret reveal) require no MFA, only `is_admin` flag | FR-RBAC-004 | High |
| RBAC-G4 | Impersonation chain not explicitly audited | FR-LOG | Medium |

---

## 3. Broker Connect Security (FR-BROKER-001…006) — Strong

**Exists**
- OpenAlgo integration is read-only; passwords / TOTP / PIN never persisted — [backend/routes/broker_connect.py:1-20](../backend/routes/broker_connect.py#L1-L20).
- API keys encrypted via AES-256-GCM — [backend/services/pii_security.py:84-107](../backend/services/pii_security.py#L84-L107).
- Masked key stored alongside ciphertext — [backend/routes/broker_connect.py:136-153](../backend/routes/broker_connect.py#L136-L153).
- Health-check probe before persisting — [backend/services/openalgo_client.py:71-109](../backend/services/openalgo_client.py#L71-L109).
- Disconnect deletes ciphertext + dependent holdings, with audit — [backend/routes/broker_connect.py:213-233](../backend/routes/broker_connect.py#L213-L233).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| BROK-G1 | No `expires_at` tracking; key invalidation only surfaces on next sync failure | FR-BROKER-006 | Medium |
| BROK-G2 | No in-place key rotation | FR-BROKER-006 | Low |

---

## 4. File Upload Security (FR-UPLOAD-001…006) — Partial

**Exists**
- Extension allowlist — [backend/routes/upload.py:18-57](../backend/routes/upload.py#L18-L57).
- Password-protected PDF handling with redaction in error logs — [backend/routes/upload.py:234-267](../backend/routes/upload.py#L234-L267).
- CAS upload audited with size + filename — [backend/routes/upload.py:41-49](../backend/routes/upload.py#L41-L49).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| UPL-G1 | No MIME magic-byte validation (extension only) | FR-UPLOAD-001 | High |
| UPL-G2 | No file-size limit (streaming upload unbounded) | FR-UPLOAD-005 | High |
| UPL-G3 | No virus / malware scanning | FR-UPLOAD-002 | High |
| UPL-G4 | No sandboxed parsing — `openpyxl` / `pdfplumber` run in-process | FR-UPLOAD-003,4 | High |
| UPL-G5 | Files-at-rest encryption not documented | FR-UPLOAD-006 | Medium |
| UPL-G6 | CAS PDFs proxied to third-party `casparser.in` — no documented DPA | DPDP §8 | Medium |

---

## 5. Data Protection (FR-DATA-001…005) — Strong (with gaps)

**Exists**
- AES-256-GCM, 12-byte random nonce + auth tag — [backend/services/pii_security.py:84-107](../backend/services/pii_security.py#L84-L107).
- PAN encrypted at rest, only masked form returned — [backend/routes/compliance.py:113-141](../backend/routes/compliance.py#L113-L141).
- Right-to-delete (PAN) and right-to-erase (account) — [backend/routes/compliance.py:144-228](../backend/routes/compliance.py#L144-L228).
- Versioned consent ledger — [backend/services/consents.py:1-184](../backend/services/consents.py#L1-L184).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| DATA-G1 | `PII_ENCRYPTION_KEY` falls back to deterministic SHA-256 of fixed string; if `APP_ENV` is misconfigured in prod, ciphertext is re-derivable | FR-DATA-001,3 | High |
| DATA-G2 | No documented MongoDB encryption-at-rest (TDE / Atlas KMS) | FR-DATA-001 §11 | High |
| DATA-G3 | No backup-encryption documentation | FR-DATA-005 | Medium |
| DATA-G4 | No PII_ENCRYPTION_KEY rotation workflow | FR-DATA-001 | Medium |

---

## 6. Secrets in Repository — **Critical**

**Exists**
- `.gitignore` covers `.env`, `.fred-token`, `.gcp-token`, `.gh-token`. Verified: **no `.env` file has ever been committed** (`git log --all -- backend/.env` returns empty). The earlier audit's "OpenAI / Google / CAS keys committed in `.env`" claim was incorrect.
- DB-backed secret store fronted by admin UI — [backend/helpers/secrets.py:14-32](../backend/helpers/secrets.py#L14-L32).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| SEC-G1 | **Live admin session tokens for two `is_admin: true` users** committed at [memory/test_credentials.md](../memory/test_credentials.md), valid until 2026-05-25 | FR-AUTH, FR-RBAC, FR-LOG-002 | **CRITICAL** |
| SEC-G2 | Plaintext local `.env` files on dev disks; production secret-manager wiring not visible from code | FR-DATA-003 §10 | High |
| SEC-G3 | `db.app_secrets` is the source of truth for OpenAI/CAS keys — same Mongo as user data, no KMS envelope | FR-DATA-003 | Medium |

---

## 7. API Security (FR-API-001…006) — Partial

**Exists**
- In-memory sliding-window rate limiter, per-path budgets — [backend/middleware.py:14-68](../backend/middleware.py#L14-L68).
- Rate-limit key prefers session token over IP — [backend/middleware.py:40-42](../backend/middleware.py#L40-L42).
- Pydantic models on broker-connect inputs — [backend/routes/broker_connect.py:46-50](../backend/routes/broker_connect.py#L46-L50).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| API-G1 | No managed API gateway | FR-API-001 | Medium |
| API-G2 | No WAF (Cloudflare / Cloud Armor / ModSecurity) | FR-API-003 | Medium |
| API-G3 | Mixed input validation — some routes use Pydantic, others read raw `await request.json()` | FR-API-005 | Medium |
| API-G4 | No URL versioning (`/v1/`) | FR-API-006 | Low |

---

## 8. Audit Logging (FR-LOG-001…003) — Strong (with hardening gaps)

**Exists**
- Audit ledger with sanitiser stripping `password`, `pan_plain`, `aadhaar`, `otp`, `token`, `secret` — [backend/services/audit.py:42-55](../backend/services/audit.py#L42-L55).
- Canonical action enum covers login, broker, PAN, consent, data export/delete — [backend/services/audit.py:29-39](../backend/services/audit.py#L29-L39).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| LOG-G1 | Audit log in plain Mongo collection — no immutability enforcement | FR-LOG-001 | Medium |
| LOG-G2 | No real-time alerting (no Sentry / Slack hook) | FR-LOG-003, FR-MON-002 | Medium |
| LOG-G3 | No integrity chain (hash-of-prev-record) | FR-LOG-001 | Medium |
| LOG-G4 | Admin-creation / admin-removal not audited | FR-LOG | Low |

---

## 9. Encryption Standards (§11) — Partial

**Exists**
- AES-256-GCM in app-layer crypto.
- Cookies `secure=True`.

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| ENC-G1 | TLS termination & cipher policy not in repo — TLS 1.3 + HSTS not verifiable | §11 | High |
| ENC-G2 | DB encryption at rest not enabled / not documented | §11 | High |
| ENC-G3 | Object storage encryption not documented | §11 | Medium |

---

## 10. Frontend Security Headers (§12) — **Missing**

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| FE-G1 | No CSP, X-Frame-Options, X-Content-Type-Options, HSTS, Referrer-Policy, Permissions-Policy | §12 | High |
| FE-G2 | CORS allows credentials with regex-`.*` origin | FR-API | Medium |
| FE-G3 | No SRI on third-party scripts | §12 | Medium |

---

## 11. AI / LLM Security (§15) — Partial

**Exists**
- Consent flow documents which fields go to OpenAI — [backend/routes/compliance.py:44-53](../backend/routes/compliance.py#L44-L53).
- Privacy notice version-pinned in consent ledger — [backend/services/consents.py:42-52](../backend/services/consents.py#L42-L52).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| LLM-G1 | No prompt-injection guard | §15 | High |
| LLM-G2 | No code-level PII redaction before LLM call | §15 | High |
| LLM-G3 | No per-user tool / function allowlist | §15 | Medium |
| LLM-G4 | No LLM-output capture in audit trail | FR-LOG | Medium |

---

## 12. Monitoring & Incident Response (§17) — Minimal

**Exists**
- Python `logging` to stdout — [backend/server.py:71](../backend/server.py#L71).
- Audit writes are best-effort — [backend/services/audit.py:82-89](../backend/services/audit.py#L82-L89).

**Gaps**
| ID | Gap | PRD | Severity |
| --- | --- | --- | --- |
| MON-G1 | No external observability (Sentry / Datadog / Cloud Logging sink) | FR-MON-001 | High |
| MON-G2 | No alerting on failed-login bursts, data-export, admin ops, 5xx spikes | FR-MON-002,3 | High |
| MON-G3 | No Prometheus `/metrics` | FR-MON | Medium |
| MON-G4 | No documented incident-response runbook | FR-MON-004 | Medium |

---

## 13. Mobile Security (§14) — Missing (all P2 per PRD)

Capacitor scaffolds exist (`frontend/android/`, `frontend/ios/`, `frontend/capacitor.config.json`); none of SSL pinning, biometric, secure local storage, root/jailbreak detection are wired up. PRD marks all P2 — no immediate action.

---

## 14. Compliance Posture (§16)

| Requirement | Status | Note |
| --- | --- | --- |
| **DPDP Act** (Mandatory) | Partial | Consent ledger ✅, right of access + erasure ✅. Breach-notification workflow + DPO contact + data-residency proof missing. |
| **CERT-In logging norms** (Mandatory) | Gap | 180-day NTP-synced retention not enforced. |
| **SEBI cybersecurity** (Recommended) | Gap | No CSCRF alignment doc; no VAPT cadence / SOC / DR drills documented. |

---

## What this audit could not verify

- TLS / cipher posture at the edge (depends on prod ingress)
- Whether MongoDB Atlas tier has CMEK enabled
- Whether casparser.in has a signed DPA
- Production secrets path — whether `helpers.secrets` is the only one or Cloud Run env vars / Secret Manager are also wired
- Backup retention / DR RTO/RPO

These are called out in the implementation plan as ops-verification tasks rather than coding tasks.
