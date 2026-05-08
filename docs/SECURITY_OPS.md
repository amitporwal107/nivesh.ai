# NIVESH Security Operations Runbook

This runbook covers the **infrastructure** controls the codebase can't enforce on its own — TLS termination, encryption-at-rest, HSTS preload, secrets, monitoring. Code-level controls live in [SECURITY_PRD.md](./SECURITY_PRD.md) and gaps in [SECURITY_GAP_ANALYSIS.md](./SECURITY_GAP_ANALYSIS.md).

> **Owner:** Platform / DevOps. Update this doc whenever a control's configuration changes.

---

## 1. TLS at the edge (FR-API §11) — P1-12

### Target state

| Setting | Required value |
| --- | --- |
| TLS version | **1.3 only** (TLS 1.2 only as fallback during migration) |
| Cipher suites | ECDHE+AES-GCM, ECDHE+CHACHA20 only — disable RSA key exchange |
| HSTS | `max-age=31536000; includeSubDomains; preload` |
| OCSP stapling | Enabled |
| Certificate authority | Let's Encrypt (Cloudflare-managed) or DigiCert for HNI tier |

### How to verify

```bash
# Cipher / version probe
curl -vsI https://nivesh.app 2>&1 | grep -E "SSL|TLS|HSTS"
# Or: SSL Labs test
open "https://www.ssllabs.com/ssltest/analyze.html?d=nivesh.app"
```

A passing run is **A+** with TLS 1.3 enabled, HSTS marked, no weak ciphers.

### How to set (Cloudflare path — recommended)

1. Cloudflare dashboard → SSL/TLS → Edge Certificates
2. Set "Minimum TLS Version" = TLS 1.3
3. Enable "Always Use HTTPS"
4. Enable "Automatic HTTPS Rewrites"
5. SSL/TLS → Edge Certificates → HSTS:
   - Enable HSTS
   - Max Age: 12 months
   - Apply HSTS to subdomains: ON
   - Preload: ON
   - No-Sniff Header: ON

### HSTS preload list submission

After 30 days of `max-age=31536000; includeSubDomains; preload` being live without rollback:

1. Visit https://hstspreload.org/
2. Enter `nivesh.app`, click "Check eligibility"
3. Submit if all checks pass

> **Warning:** Once preloaded, removing HSTS takes weeks (browsers ship the list). Don't preload until HTTPS is permanent.

---

## 2. Database encryption-at-rest (FR-DATA-001 §11) — P1-10

### Target state

MongoDB Atlas with **Encryption at Rest using Customer-Managed Keys (CMEK)**, key stored in GCP KMS or AWS KMS.

### How to verify

```bash
# Atlas Admin API
curl -u "<pub>:<priv>" \
  "https://cloud.mongodb.com/api/atlas/v2/groups/$ATLAS_PROJECT_ID/encryptionAtRest" \
  -H "Accept: application/vnd.atlas.2023-01-01+json"
```

Expected response: `googleCloudKms.enabled = true` (or the equivalent for AWS / Azure).

### How to set

1. **Create the KMS key** (GCP shown):
   ```
   gcloud kms keys create nivesh-mongo-cmek \
     --keyring=nivesh-prod --location=asia-south1 \
     --purpose=encryption
   ```
2. **Grant Atlas the role**:
   ```
   gcloud kms keys add-iam-policy-binding nivesh-mongo-cmek \
     --keyring=nivesh-prod --location=asia-south1 \
     --member="serviceAccount:mongodb-cloud-prod@..." \
     --role=roles/cloudkms.cryptoKeyEncrypterDecrypter
   ```
3. Atlas dashboard → Security → Encryption at Rest → Google Cloud KMS → enter key URL, save.
4. Existing data is re-encrypted online by Atlas; no downtime.

### What this protects against

- Disk theft / snapshot exfiltration
- Atlas-internal access without the CMEK
- Backup blob exposure (Atlas snapshots inherit CMEK)

### What this does **not** protect against

- A compromised application credential (read-then-decrypt path is normal). For that, see PII field-level encryption — already implemented at [backend/services/pii_security.py](../backend/services/pii_security.py).

---

## 3. Object storage encryption (§11)

If/when we move CAS uploads to GCS / S3:

| Provider | Required setting |
| --- | --- |
| GCS | Bucket-level CMEK (same KMS key as Mongo) |
| S3 | SSE-KMS with customer-managed key |

Default-encrypt the bucket at creation time:

```bash
gsutil mb -p $PROJECT -l asia-south1 -b on gs://nivesh-prod-cas-uploads
gcloud storage buckets update gs://nivesh-prod-cas-uploads \
  --default-encryption-key=projects/$PROJECT/locations/asia-south1/keyRings/nivesh-prod/cryptoKeys/nivesh-storage-cmek
```

---

## 4. Secrets (FR-DATA-003) — P1-11

### Target state

All secrets read from **GCP Secret Manager** (or AWS Secrets Manager). The `db.app_secrets` collection used today is dev-only.

### Required secrets in production

| Name | Used by | Rotation cadence |
| --- | --- | --- |
| `PII_ENCRYPTION_KEY` | [backend/services/pii_security.py](../backend/services/pii_security.py) | Annual + on suspected compromise |
| `OPENAI_API_KEY` | [backend/services/llm_safety.py](../backend/services/llm_safety.py) callers | Quarterly |
| `EMERGENT_LLM_KEY` | LLM proxy fallback | Quarterly |
| `GOOGLE_CLIENT_SECRET` | [backend/routes/auth.py](../backend/routes/auth.py) | On dev-account turnover |
| `CASPARSER_API_KEY` | [backend/services/cas_api_client.py](../backend/services/cas_api_client.py) | When provider rotates |
| `MONGO_URL` | [backend/deps.py](../backend/deps.py) | When Atlas user rotates |

### Verification

The startup log line `pii_key_source=...` shows where the PII key came from. Acceptable values in prod: `env` or `secret`. **Reject any deploy where `pii_key_source=dev_fallback` appears.** ([backend/services/pii_security.py:_get_key](../backend/services/pii_security.py))

### Emergency rotation

```bash
# 1. Generate new key
NEWKEY=$(openssl rand -base64 32)

# 2. Push to Secret Manager
echo -n "$NEWKEY" | gcloud secrets versions add PII_ENCRYPTION_KEY --data-file=-

# 3. Deploy. The next pod start picks up the new key.
# Existing ciphertext still decrypts because the old key is still active
# until you destroy the version. DO NOT destroy until backfill re-encrypts.
```

---

## 5. CORS allowlist (FR-API)

The current default allows any origin via regex — set explicitly in prod:

```
CORS_ORIGINS=https://nivesh.app,https://app.nivesh.app
```

[backend/server.py:130](../backend/server.py#L130) reads this. Empty string keeps the dev-friendly wildcard behaviour.

---

## 6. Backups (FR-DATA-005)

### Target

| Property | Value |
| --- | --- |
| Cadence | Continuous (Atlas Cloud Backup) + daily snapshot |
| Retention | 30 days rolling, 12 monthly archives |
| Encryption | Inherits CMEK (see §2) |
| Restore RTO | < 4 hours (PRD §8.2) |
| Restore RPO | < 1 hour |

### DR drill

Schedule a **quarterly** restore test: spin up a staging cluster from a snapshot, run the smoke-test suite, document the wall-clock time. Owner: Platform on-call.

---

## 7. Monitoring & alerting (§17) — P1-16

### Required wiring

| Source | Destination | Signal |
| --- | --- | --- |
| Backend errors | Sentry | All 5xx + uncaught exceptions |
| Audit ledger ([backend/services/audit.py](../backend/services/audit.py)) | Cloud Logging | Every record |
| Cloud Logging | Slack `#sec-ops` | `action ∈ {data_export, admin_*, broker_disconnect}` |
| Cloud Logging | PagerDuty | `action == "login_failed"` × > 5 / 5 min / IP |
| Uptime checks | PagerDuty | `/api/` returns non-200 for > 2 min |

### Sentry init

```python
# backend/server.py — to be added when SENTRY_DSN is provisioned
import sentry_sdk
if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        environment=os.environ.get("APP_ENV", "dev"),
        traces_sample_rate=0.1,
        send_default_pii=False,  # PRD: never send PII off-platform
    )
```

---

## 8. Incident response (FR-MON-004)

### Severity levels

| Sev | Definition | Response |
| --- | --- | --- |
| Sev-1 | Active data exfiltration / live unauthorised access | Page on-call + founders + legal within 15 min |
| Sev-2 | Auth/authz failure suspected; no confirmed breach | Page on-call within 1 hour |
| Sev-3 | Single-user impact; degraded but not dangerous | Next business day |

### Playbook (high-level)

1. **Contain** — disable affected sessions (`db.user_sessions.deleteMany`), revoke admin tokens, freeze new logins if needed.
2. **Preserve** — copy current Mongo collections to a read-only snapshot bucket before any cleanup.
3. **Notify** — DPDP §8(6) requires the Data Protection Board be notified of personal-data breaches; legal owns the wording.
4. **Eradicate** — rotate any credentials in scope (see §4 emergency rotation).
5. **Recover** — restore from clean snapshot if integrity is in question.
6. **Post-mortem** — within 5 business days, blameless write-up, link to this doc.

---

## 9. Compliance evidence checklist

| Control | Owner | Evidence location |
| --- | --- | --- |
| TLS A+ rating | Platform | SSL Labs report (quarterly) |
| Atlas CMEK enabled | Platform | Atlas API response (this doc §2) |
| Secret Manager source-of-truth | Platform | `pii_key_source=secret` in prod startup log |
| DR drill completed | Platform | Wall-clock log + restore validation |
| VAPT report | Security vendor | Annual third-party report |
| DPDP DPA with vendors | Legal | Signed MSAs (OpenAI, casparser.in, Atlas, Cloudflare) |

---

## 10. Quick links

- PRD: [SECURITY_PRD.md](./SECURITY_PRD.md)
- Gap analysis: [SECURITY_GAP_ANALYSIS.md](./SECURITY_GAP_ANALYSIS.md)
- App-layer crypto: [backend/services/pii_security.py](../backend/services/pii_security.py)
- Audit ledger: [backend/services/audit.py](../backend/services/audit.py)
- LLM safety helpers: [backend/services/llm_safety.py](../backend/services/llm_safety.py)
- Upload validation: [backend/helpers/upload_validation.py](../backend/helpers/upload_validation.py)
- Security headers middleware: [backend/middleware.py](../backend/middleware.py)
