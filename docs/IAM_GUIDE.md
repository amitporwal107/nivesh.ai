# Nivesh GCP — IAM Users, Service Accounts & Keys

**Project:** `niveshdataintelligence`  
**Last updated:** 2026-05-20

All IAM operations require an **Owner token**. Section 1 shows how to use yours.

> **Full DevOps identity setup** (new devops user + VM access + GitHub secrets): see [DEVOPS_IDENTITY_SETUP.md](DEVOPS_IDENTITY_SETUP.md)

Sections 2–5 cover every role that exists or needs to be created.

---

## 1. Authenticate as Owner (aporwal107@gmail.com)

The owner account is the root of all IAM changes. All commands in this guide
run against this account.

```bash
# Login as owner (first time or after session expiry)
gcloud auth login aporwal107@gmail.com
gcloud config set project niveshdataintelligence
gcloud config set account aporwal107@gmail.com

# Verify you are owner
gcloud projects get-iam-policy niveshdataintelligence \
  --flatten="bindings[].members" \
  --filter="bindings.members:aporwal107@gmail.com" \
  --format="table(bindings.role)"
```

---

## 2. Existing Service Accounts (already created)

```bash
# List all SAs in the project
gcloud iam service-accounts list --project=niveshdataintelligence
```

| SA name | Email | Purpose |
|---|---|---|
| `nidp-sa` | `nidp-sa@niveshdataintelligence.iam.gserviceaccount.com` | Runtime — attached to Cloud Run jobs/services |
| `nivesh-devops` | `nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com` | CI/CD — Cloud Build, image push, Cloud Run deploy |

---

## 3. Role Reference — What Each Role Can Do

| Role | Who needs it |
|---|---|
| `roles/owner` | Only aporwal107@gmail.com — full control |
| `roles/cloudbuild.builds.editor` | Build engineers — submit/cancel builds |
| `roles/artifactregistry.writer` | Build engineers — push Docker images |
| `roles/run.admin` | Deploy engineers — create/update Cloud Run services & jobs |
| `roles/run.developer` | Ops support — list/describe Cloud Run, invoke jobs |
| `roles/secretmanager.secretAccessor` | Runtime SAs, deploy engineers — read secrets |
| `roles/secretmanager.admin` | Owner only — create/delete secrets |
| `roles/logging.viewer` | Support — read Cloud Logging |
| `roles/logging.logWriter` | Runtime SAs — write logs |
| `roles/iam.serviceAccountUser` | CI/CD SAs — act as another SA (deploy Cloud Run with a SA) |
| `roles/iam.serviceAccountTokenCreator` | Owner — impersonate SAs to get short-lived tokens |
| `roles/compute.osLogin` | VM operators — SSH into GCE VMs via OS Login |
| `roles/compute.osAdminLogin` | VM admins — SSH as root/sudo |

---

## 4. Create Service Accounts for Each Role

### 4a. Build Engineer SA (`nivesh-build-sa`)

Can submit Cloud Builds and push images. Cannot deploy to Cloud Run.

```bash
# Create SA
gcloud iam service-accounts create nivesh-build-sa \
  --display-name="Nivesh Build Engineer" \
  --description="Submit Cloud Builds and push images to Artifact Registry" \
  --project=niveshdataintelligence

# Grant roles
for role in \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.objectAdmin \
  roles/logging.viewer; do
  gcloud projects add-iam-policy-binding niveshdataintelligence \
    --member="serviceAccount:nivesh-build-sa@niveshdataintelligence.iam.gserviceaccount.com" \
    --role="$role" --condition=None --quiet
done

# Create JSON key
gcloud iam service-accounts keys create ~/nivesh-build-sa.json \
  --iam-account=nivesh-build-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --project=niveshdataintelligence
```

### 4b. Deploy Engineer SA (`nivesh-deploy-sa`)

Can deploy Cloud Run services/jobs and read secrets. Cannot create/delete secrets.

```bash
# Create SA
gcloud iam service-accounts create nivesh-deploy-sa \
  --display-name="Nivesh Deploy Engineer" \
  --description="Deploy Cloud Run services and jobs, read secrets" \
  --project=niveshdataintelligence

# Grant roles
for role in \
  roles/run.admin \
  roles/secretmanager.secretAccessor \
  roles/artifactregistry.reader \
  roles/logging.viewer \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding niveshdataintelligence \
    --member="serviceAccount:nivesh-deploy-sa@niveshdataintelligence.iam.gserviceaccount.com" \
    --role="$role" --condition=None --quiet
done

# Create JSON key
gcloud iam service-accounts keys create ~/nivesh-deploy-sa.json \
  --iam-account=nivesh-deploy-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --project=niveshdataintelligence
```

### 4c. Ops / Support SA (`nivesh-ops-sa`)

Read-only — view logs, list services, describe jobs. Cannot deploy or change anything.

```bash
# Create SA
gcloud iam service-accounts create nivesh-ops-sa \
  --display-name="Nivesh Ops Support" \
  --description="Read-only: view logs, list/describe Cloud Run services and jobs" \
  --project=niveshdataintelligence

# Grant roles
for role in \
  roles/run.developer \
  roles/logging.viewer \
  roles/artifactregistry.reader \
  roles/monitoring.viewer; do
  gcloud projects add-iam-policy-binding niveshdataintelligence \
    --member="serviceAccount:nivesh-ops-sa@niveshdataintelligence.iam.gserviceaccount.com" \
    --role="$role" --condition=None --quiet
done

# Create JSON key
gcloud iam service-accounts keys create ~/nivesh-ops-sa.json \
  --iam-account=nivesh-ops-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --project=niveshdataintelligence
```

### 4d. VM Operator (personal Google account — OS Login)

OS Login grants SSH access to GCE VMs using a personal Google account.
No SA key is needed — it uses the person's own Google credentials.

```bash
# Grant OS Login (non-root SSH) to a team member
gcloud projects add-iam-policy-binding niveshdataintelligence \
  --member="user:teammate@gmail.com" \
  --role="roles/compute.osLogin" \
  --condition=None

# Grant OS Admin Login (sudo access) to a VM admin
gcloud projects add-iam-policy-binding niveshdataintelligence \
  --member="user:teammate@gmail.com" \
  --role="roles/compute.osAdminLogin" \
  --condition=None

# The team member SSHs in using their own gcloud
gcloud compute ssh nivesh-app-vm \
  --project=niveshdataintelligence --zone=asia-south1-a

# Or direct SSH after OS Login key registration
ssh teammate_gmail_com@34.47.250.214   # nivesh-app-vm
ssh teammate_gmail_com@34.93.60.254     # nidp-stack-vm
```

---

## 5. Get Short-Lived Tokens (using owner token — no key file needed)

Impersonation lets you generate a 1-hour access token for any SA without
downloading a JSON key. Requires the owner account to have
`roles/iam.serviceAccountTokenCreator` on the target SA (auto-granted to owners).

```bash
# Make sure you are logged in as owner
gcloud config set account aporwal107@gmail.com

# Get a token for nivesh-devops (CI/CD operations)
gcloud auth print-access-token \
  --impersonate-service-account=nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com

# Get a token for nidp-sa (runtime operations)
gcloud auth print-access-token \
  --impersonate-service-account=nidp-sa@niveshdataintelligence.iam.gserviceaccount.com

# Save to /app/.gcp-token for use by deploy scripts
gcloud auth print-access-token \
  --impersonate-service-account=nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com \
  > /app/.gcp-token

# Use the token in a gcloud command
TOKEN=$(cat /app/.gcp-token)
CLOUDSDK_AUTH_ACCESS_TOKEN="$TOKEN" gcloud run services list \
  --region=asia-south1 --project=niveshdataintelligence
```

---

## 6. Activate a JSON Key (long-lived — use for automation)

```bash
# Activate key for CI/CD work
gcloud auth activate-service-account \
  --key-file=~/nivesh-devops.json
TOKEN=$(gcloud auth print-access-token)
echo "$TOKEN" > /app/.gcp-token

# Activate key for build work
gcloud auth activate-service-account \
  --key-file=~/nivesh-build-sa.json

# Activate key for ops/support
gcloud auth activate-service-account \
  --key-file=~/nivesh-ops-sa.json

# Verify which account is currently active
gcloud auth list --filter=status:ACTIVE --format="value(account)"
```

---

## 7. List, View, and Delete Keys

```bash
SA="nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com"

# List all keys for a SA (shows key ID, creation date, type)
gcloud iam service-accounts keys list \
  --iam-account="$SA" \
  --project=niveshdataintelligence \
  --format="table(name.basename(),validAfterTime,keyType)"

# Delete a specific key by ID (KEY_ID is the short hash from the list above)
gcloud iam service-accounts keys delete KEY_ID \
  --iam-account="$SA" \
  --project=niveshdataintelligence --quiet

# Rotate nidp-sa key (creates new key → updates Secret Manager → deletes old key)
bash backend/nidp/deploy/gcp/rotate_credentials.sh --confirm
```

---

## 8. Use Existing Scripts (already in the repo)

```bash
# Create / verify nidp-sa (runtime SA) — dry-run first
bash backend/nidp/deploy/gcp/setup_credentials.sh \
  --project=niveshdataintelligence

# Apply
bash backend/nidp/deploy/gcp/setup_credentials.sh \
  --project=niveshdataintelligence --confirm

# Create / verify nivesh-devops SA — dry-run first
bash backend/nidp/deploy/gcp/setup_devops_sa.sh \
  --project=niveshdataintelligence

# Apply + download JSON key
bash backend/nidp/deploy/gcp/setup_devops_sa.sh \
  --project=niveshdataintelligence \
  --key-file=~/nivesh-devops.json \
  --confirm
```

---

## 9. Grant an Existing SA Access to Impersonate Another SA

Needed when one SA needs to deploy Cloud Run with a different SA attached.

```bash
# Allow nivesh-devops to act as nidp-sa (already configured — for reference)
gcloud iam service-accounts add-iam-policy-binding \
  nidp-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --member="serviceAccount:nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" \
  --project=niveshdataintelligence
```

---

## 10. View and Audit IAM Policy

```bash
# Full project IAM policy (all members + roles)
gcloud projects get-iam-policy niveshdataintelligence \
  --format="table(bindings.role,bindings.members)"

# Filter by a specific member
gcloud projects get-iam-policy niveshdataintelligence \
  --flatten="bindings[].members" \
  --filter="bindings.members:nivesh-devops" \
  --format="table(bindings.role)"

# Filter by a specific role
gcloud projects get-iam-policy niveshdataintelligence \
  --flatten="bindings[].members" \
  --filter="bindings.role:run.admin" \
  --format="table(bindings.members)"

# List all service accounts and their keys
gcloud iam service-accounts list --project=niveshdataintelligence \
  --format="table(email,displayName,disabled)"
```

---

## 11. Remove Access

```bash
# Remove a role from a SA
gcloud projects remove-iam-policy-binding niveshdataintelligence \
  --member="serviceAccount:nivesh-ops-sa@niveshdataintelligence.iam.gserviceaccount.com" \
  --role="roles/run.developer" --quiet

# Disable a SA (preserves it but blocks all authentication)
gcloud iam service-accounts disable \
  nivesh-ops-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --project=niveshdataintelligence

# Re-enable a SA
gcloud iam service-accounts enable \
  nivesh-ops-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --project=niveshdataintelligence

# Delete a SA entirely (irreversible)
gcloud iam service-accounts delete \
  nivesh-ops-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --project=niveshdataintelligence --quiet
```

---

## Quick Reference

| Task | Section |
|---|---|
| Login as owner | §1 |
| See existing SAs | §2 |
| Create build engineer SA + key | §4a |
| Create deploy engineer SA + key | §4b |
| Create ops/support SA + key | §4c |
| Grant VM SSH access to a person | §4d |
| Get short-lived token via impersonation (no key file) | §5 |
| Activate a JSON key | §6 |
| List / delete keys | §7 |
| Use existing setup scripts | §8 |
| Audit who has what access | §10 |
| Remove / disable access | §11 |
