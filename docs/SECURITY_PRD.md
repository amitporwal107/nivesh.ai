# NIVESH — Fintech Security & Data Protection PRD

## 1. Document Overview

**Product:** NIVESH
**Module:** Security, Privacy & Data Protection Framework

### Objective

Build a banking-grade security architecture for NIVESH that:

- Protects user financial data
- Secures broker integrations
- Ensures safe document ingestion
- Builds user trust
- Meets Indian fintech compliance expectations
- Scales for retail, HNI, MFD, PMS, and enterprise use cases

---

## 2. Business Context

NIVESH handles:

- Portfolio holdings
- Mutual fund statements
- Broker connections
- Transaction history
- PAN-linked investment data
- Wealth analytics
- AI-generated financial insights

This makes security a:

- Core trust feature
- Legal requirement
- Platform differentiator
- Enterprise onboarding prerequisite

---

## 3. Product Goals

### Primary Goals

| Goal | Description |
| --- | --- |
| Secure user financial data | Protect all uploaded and connected portfolio data |
| Build user trust | Communicate strong security posture visibly |
| Prevent unauthorized access | Secure authentication and authorization |
| Protect uploaded documents | Sandbox and securely process files |
| Enable scalable broker integrations | Secure read-only architecture |
| Support compliance readiness | DPDP, SEBI, SOC2 readiness |

---

## 4. Non-Goals

NIVESH will NOT:

- Store broker passwords
- Execute trades in Phase 1
- Store banking credentials
- Provide banking/payment infrastructure
- Store unnecessary PII

---

## 5. Security Principles

### Core Principles

**A. Least Privilege** — Users, systems, and services only receive minimum required access.

**B. Read-Only Architecture** — Broker integrations must remain read-only.

**C. Zero Trust** — Every request must be authenticated and validated.

**D. Data Minimization** — Store only required user information.

**E. Encryption Everywhere** — All sensitive data encrypted in transit and at rest.

**F. Progressive Trust** — Users receive clear visibility into:

- permissions
- access scopes
- security controls
- deletion rights

---

## 6. User Personas

| Persona | Security Expectation |
| --- | --- |
| Retail Investor | Easy but safe onboarding |
| HNI | Institutional-grade privacy |
| MFD/IFA | Client segregation |
| PMS/Advisory | Auditability |
| Enterprise | Compliance readiness |

---

## 7. Functional Requirements

### 7.1 Authentication & Identity

#### Features

| Feature | Priority |
| --- | --- |
| Google OAuth Login | P1 |
| Mobile OTP Login | P1 |
| Passwordless login | P1 |
| MFA support | P2 |
| Session management | P1 |
| Device recognition | P2 |
| Suspicious login detection | P2 |

#### Requirements

- **FR-AUTH-001** — System must support Google OAuth.
- **FR-AUTH-002** — System must support mobile OTP login.
- **FR-AUTH-003** — Sessions must expire automatically.
- **FR-AUTH-004** — JWT access tokens must use short expiry.
- **FR-AUTH-005** — Refresh token rotation must be enabled.
- **FR-AUTH-006** — Authentication cookies must be:
  - Secure
  - HTTP-only
  - SameSite protected

### 7.2 Authorization & Access Control

#### Roles

| Role | Permissions |
| --- | --- |
| Retail User | Own data only |
| Advisor | Assigned client data |
| Admin | Restricted admin operations |
| Support | Limited masked access |

#### Requirements

- **FR-RBAC-001** — System must implement RBAC.
- **FR-RBAC-002** — Tenant-level data isolation required.
- **FR-RBAC-003** — All APIs must validate ownership.
- **FR-RBAC-004** — Admin access must require MFA.

### 7.3 Broker Connect Security

#### Requirements

- **FR-BROKER-001** — System must only support read-only broker access.
- **FR-BROKER-002** — System must never store broker passwords.
- **FR-BROKER-003** — OAuth/token-based authentication preferred.
- **FR-BROKER-004** — Broker tokens must be encrypted.
- **FR-BROKER-005** — Broker access scopes must be minimal.
- **FR-BROKER-006** — Expired broker sessions must auto-revoke.

### 7.4 File Upload Security

#### Supported Upload Types

| Type | Priority |
| --- | --- |
| PDF | P1 |
| XLSX | P1 |
| CSV | P1 |
| CAS Statements | P1 |

#### Requirements

- **FR-UPLOAD-001** — All uploads must pass MIME validation.
- **FR-UPLOAD-002** — All uploads must be virus scanned.
- **FR-UPLOAD-003** — Files must be processed in sandbox environment.
- **FR-UPLOAD-004** — Macros/scripts must be disabled.
- **FR-UPLOAD-005** — File size limits enforced.
- **FR-UPLOAD-006** — Uploaded files encrypted at rest.

### 7.5 Data Protection

#### Sensitive Data Types

| Data Type | Protection Level |
| --- | --- |
| PAN | High |
| Holdings | High |
| Transactions | High |
| Broker Tokens | Critical |
| CAS Statements | Critical |

#### Requirements

- **FR-DATA-001** — All sensitive data encrypted using AES-256.
- **FR-DATA-002** — PAN numbers masked in UI.
- **FR-DATA-003** — Secrets stored only in secret manager.
- **FR-DATA-004** — Data deletion APIs required.
- **FR-DATA-005** — Backups must be encrypted.

### 7.6 API Security

#### Requirements

- **FR-API-001** — All APIs protected behind API Gateway.
- **FR-API-002** — Rate limiting mandatory.
- **FR-API-003** — WAF protection mandatory.
- **FR-API-004** — API authentication required.
- **FR-API-005** — Input validation mandatory.
- **FR-API-006** — API versioning required.

### 7.7 Audit Logging

#### Must Log

| Event | Priority |
| --- | --- |
| Login attempts | Critical |
| Broker connections | Critical |
| File uploads | Critical |
| Data exports | Critical |
| Permission changes | Critical |

#### Requirements

- **FR-LOG-001** — Audit logs must be immutable.
- **FR-LOG-002** — Logs must exclude sensitive secrets.
- **FR-LOG-003** — Suspicious events must trigger alerts.

---

## 8. Non-Functional Requirements

### 8.1 Performance

| Metric | Target |
| --- | --- |
| Auth response time | < 500ms |
| File scan time | < 10 sec |
| Broker connect auth | < 5 sec |
| Token validation | < 100ms |

### 8.2 Availability

| Requirement | Target |
| --- | --- |
| Uptime | 99.9% |
| Backup retention | 30+ days |
| Disaster recovery | < 4 hours |

### 8.3 Scalability

System must support:

- 1M+ users
- 100K concurrent sessions
- Multi-tenant advisory usage

---

## 9. Security Architecture

### Recommended High-Level Architecture

```
Frontend
   ↓
CDN + WAF
   ↓
API Gateway
   ↓
Authentication Layer
   ↓
Microservices
   ↓
Encrypted Database
```

---

## 10. Recommended Tech Stack

| Layer | Recommendation |
| --- | --- |
| Cloud | GCP / AWS |
| CDN/WAF | Cloudflare |
| Auth | Auth0 / Firebase / Cognito |
| Database | PostgreSQL |
| Secrets | GCP Secret Manager |
| Container | Docker |
| Orchestration | Kubernetes |
| Monitoring | Grafana |
| Logging | ELK / Datadog |

---

## 11. Encryption Standards

### Data in Transit

| Standard | Requirement |
| --- | --- |
| TLS | TLS 1.3 |
| HSTS | Enabled |
| Secure headers | Mandatory |

### Data at Rest

| Component | Standard |
| --- | --- |
| Database | AES-256 |
| Object Storage | AES-256 |
| Backups | AES-256 |
| Logs | Encrypted |

---

## 12. Frontend Security Requirements

### Required Headers

```
Content-Security-Policy
X-Frame-Options
X-Content-Type-Options
Strict-Transport-Security
Referrer-Policy
Permissions-Policy
```

---

## 13. Secure File Processing Flow

```
User Upload
    ↓
Quarantine Storage
    ↓
Virus Scan
    ↓
Sandbox Parsing
    ↓
Extraction Engine
    ↓
Encrypted Storage
```

---

## 14. Mobile Security Requirements

| Requirement | Priority |
| --- | --- |
| SSL pinning | P2 |
| Biometric unlock | P2 |
| Secure local storage | P1 |
| Root detection | P2 |
| Jailbreak detection | P2 |

---

## 15. AI & LLM Security

### Risks

| Risk | Mitigation |
| --- | --- |
| Prompt injection | Input sanitization |
| PII leakage | Redaction layer |
| Hallucination | Validation engine |
| Unauthorized tool access | RBAC |

---

## 16. Compliance Requirements

### India

| Compliance | Priority |
| --- | --- |
| DPDP Act | Mandatory |
| CERT-In logging norms | Mandatory |
| SEBI cybersecurity alignment | Recommended |

### Future Global Compliance

| Compliance | Priority |
| --- | --- |
| SOC2 Type II | High |
| ISO 27001 | High |
| GDPR | Medium |

---

## 17. Monitoring & Incident Response

### Requirements

- **FR-MON-001** — Real-time monitoring required.
- **FR-MON-002** — Security alerts required.
- **FR-MON-003** — Anomaly detection required.
- **FR-MON-004** — Incident escalation workflows required.

---

## 18. Security UX Requirements

### UI Messaging

Application must visibly display:

- Read-only access
- AES-256 encryption
- No trading permissions
- Delete anytime
- Secure broker connection

---

## 19. Security Benchmarks

| Area | Benchmark |
| --- | --- |
| Encryption | AES-256 |
| Transport | TLS 1.3 |
| Auth | OAuth + OTP |
| Access Control | RBAC |
| Upload Security | Sandbox + AV |
| API Security | WAF + rate limit |
| Secrets | Secret Manager |
| Logging | Immutable audit logs |

---

## 20. Success Metrics

| Metric | Target |
| --- | --- |
| Security incidents | 0 critical |
| Upload malware detection | 100% scanned |
| Unauthorized access incidents | 0 |
| Broker credential exposure | 0 |
| Compliance readiness | SOC2-ready |

---

## 21. Rollout Plan

### Phase 1 — MVP

**Must Have**

- OAuth login
- OTP login
- AES-256 encryption
- Virus scanning
- WAF
- RBAC
- Secure uploads
- Audit logs
- Secret manager

### Phase 2

- MFA
- Device intelligence
- SIEM integration
- Threat detection
- Security analytics

### Phase 3

- Zero trust architecture
- Behavioral anomaly detection
- Enterprise SSO
- HSM integration
- Advanced fraud detection

---

## 22. Strategic Recommendation

Security should not remain invisible backend infrastructure.

For NIVESH:

### Security = Product Trust = Growth

Strong visible security messaging increases:

- onboarding conversion
- broker connection rates
- portfolio upload trust
- enterprise adoption
- advisor confidence

Security must become a visible competitive advantage.
