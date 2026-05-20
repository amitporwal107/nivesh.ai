# DevOps Identity Setup

## Overview

Two identities serve distinct purposes. `nivesh_dev_ops@niveshcopilot.com` is a Google Workspace user for human interactive access via GCP OS Login — it gets passwordless sudo through IAM and is also a GitHub collaborator for manual operations. `devops` is a plain Linux user on each VM for GitHub Actions CI/CD; it authenticates via Ed25519 key-based SSH and has NOPASSWD sudo granted through a sudoers drop-in. The two tracks are intentionally separate: the CI key never touches OS Login, and the human user never touches GitHub Actions secrets.

## Prerequisites

- You are authenticated as `aporwal107@gmail.com` (project owner)
- `gcloud` CLI is installed and authenticated
- Both VMs are running: `nidp-stack-vm` (`34.93.60.254`) and `nivesh-app-vm` (`34.100.186.141`)

---

## Step 1 — Generate the CI/CD SSH key pair

Run once on your laptop. Do not use a passphrase.

```bash
ssh-keygen -t ed25519 -C "github-actions-devops-2026" -f ~/.ssh/nivesh_devops_ci -N ""
cat ~/.ssh/nivesh_devops_ci.pub   # → add to GitHub secret DEVOPS_SSH_KEY_PUB (for reference)
cat ~/.ssh/nivesh_devops_ci       # → add to GitHub secret DEVOPS_SSH_KEY
```

---

## Step 2 — Create the `devops` Linux user on each VM

The setup script is idempotent — safe to re-run. It accepts the public key as its only argument.

```bash
# copy setup script to each VM
gcloud compute scp backend/nidp/deploy/vm/setup_devops_access.sh \
  nidp-stack-vm:~ --project=niveshdataintelligence --zone=asia-south1-a

gcloud compute ssh nidp-stack-vm \
  --project=niveshdataintelligence --zone=asia-south1-a \
  --command="sudo bash ~/setup_devops_access.sh '$(cat ~/.ssh/nivesh_devops_ci.pub)'"

# repeat for nivesh-app-vm
gcloud compute scp backend/nidp/deploy/vm/setup_devops_access.sh \
  nivesh-app-vm:~ --project=niveshdataintelligence --zone=asia-south1-a

gcloud compute ssh nivesh-app-vm \
  --project=niveshdataintelligence --zone=asia-south1-a \
  --command="sudo bash ~/setup_devops_access.sh '$(cat ~/.ssh/nivesh_devops_ci.pub)'"
```

---

## Step 3 — Grant GCP IAM roles to `nivesh_dev_ops@niveshcopilot.com`

This block is idempotent — re-running only adds missing bindings.

```bash
gcloud auth login aporwal107@gmail.com
gcloud config set project niveshdataintelligence

DEVOPS_USER="user:nivesh_dev_ops@niveshcopilot.com"

for role in \
  roles/compute.osAdminLogin \
  roles/compute.viewer \
  roles/compute.instanceAdmin.v1 \
  roles/run.admin \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/artifactregistry.reader \
  roles/secretmanager.secretAccessor \
  roles/logging.viewer \
  roles/monitoring.viewer \
  roles/iam.serviceAccountUser \
  roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding niveshdataintelligence \
    --member="$DEVOPS_USER" --role="$role" --condition=None --quiet
  echo "✓ $role"
done
```

Also grant `iam.serviceAccountUser` on the `nidp-sa` service account specifically (required for Cloud Run deploys that impersonate this SA):

```bash
gcloud iam service-accounts add-iam-policy-binding \
  nidp-sa@niveshdataintelligence.iam.gserviceaccount.com \
  --member="$DEVOPS_USER" \
  --role="roles/iam.serviceAccountUser" \
  --project=niveshdataintelligence
```

---

## Step 4 — Register OS Login SSH key for human interactive access

This step is optional and only needed if `nivesh_dev_ops@niveshcopilot.com` wants terminal access from a laptop. This key is separate from the CI/CD key generated in Step 1.

```bash
# Register your personal laptop key for OS Login (interactive SSH)
# This is SEPARATE from the CI/CD key
gcloud compute os-login ssh-keys add \
  --key-file=~/.ssh/id_ed25519.pub \
  --project=niveshdataintelligence \
  --ttl=0    # no expiry

# Verify OS Login username
gcloud compute os-login describe-profile \
  --format="value(posixAccounts[0].username)"
# → should be: nivesh_dev_ops_niveshcopilot_com

# SSH to VMs as OS Login user
ssh nivesh_dev_ops_niveshcopilot_com@34.93.60.254    # nidp-stack-vm
ssh nivesh_dev_ops_niveshcopilot_com@34.100.186.141  # nivesh-app-vm
```

---

## Step 5 — Add GitHub Actions secrets

Add or update the following secrets in the repository (`Settings → Secrets and variables → Actions`):

| Secret name | Value | Notes |
|---|---|---|
| `DEVOPS_SSH_KEY` | Content of `~/.ssh/nivesh_devops_ci` | Private key — replaces `NIDP_VM_SSH_KEY`, `NIVESH_APP_VM_SSH_KEY` |
| `DEVOPS_SSH_USER` | `devops` | Linux username on both VMs |
| `NIDP_VM_HOST` | `34.93.60.254` | Already exists — no change |
| `NIVESH_VM_HOST` | `34.100.186.141` | Rename from `NIVESH_APP_VM_HOST` |

Old secrets to delete once the new ones are confirmed working:

- `NIDP_VM_SSH_KEY`
- `NIDP_SSH_USER`
- `NIVESH_APP_VM_SSH_KEY`
- `SSH_USER`
- `NIVESH_APP_VM_HOST`

---

## Step 6 — Add `nivesh_dev_ops@niveshcopilot.com` to GitHub

Go to `github.com/amitporwal107/nivesh.ai → Settings → Collaborators → Add people`. Add `nivesh_dev_ops@niveshcopilot.com` with `Write` access. Write access allows them to trigger `workflow_dispatch` runs, manage secrets, and review or approve pull requests. Do not grant Admin access unless specifically required.

---

## Step 7 — Verify

```bash
# Test CI SSH access
ssh -i ~/.ssh/nivesh_devops_ci devops@34.93.60.254 'sudo -u nidp echo "nidp sudo OK"'
ssh -i ~/.ssh/nivesh_devops_ci devops@34.100.186.141 'sudo echo "app sudo OK"'

# Verify GCP roles
gcloud projects get-iam-policy niveshdataintelligence \
  --flatten="bindings[].members" \
  --filter="bindings.members:nivesh_dev_ops" \
  --format="table(bindings.role)"
```

---

## Role reference

| Role | What it enables |
|---|---|
| `compute.osAdminLogin` | SSH to VMs with passwordless sudo via OS Login |
| `compute.viewer` | List/describe VMs in GCP Console |
| `compute.instanceAdmin.v1` | Start/stop/reset VMs |
| `run.admin` | Deploy, update, delete Cloud Run services and jobs |
| `cloudbuild.builds.editor` | Submit and cancel Cloud Build jobs |
| `artifactregistry.writer` | Push Docker images |
| `artifactregistry.reader` | Pull Docker images |
| `secretmanager.secretAccessor` | Read secrets (env vars, API keys, TLS certs) |
| `logging.viewer` | View Cloud Logging (all log streams) |
| `monitoring.viewer` | View Cloud Monitoring dashboards |
| `iam.serviceAccountUser` | Act as `nidp-sa` when deploying Cloud Run |
| `storage.objectAdmin` | Cloud Build staging bucket (required for `gcloud builds submit`) |
