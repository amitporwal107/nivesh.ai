#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Nivesh GCP Monitoring — Terraform apply script
#
# Usage:
#   ./apply.sh [plan|apply|destroy] [--var-file=path/to/vars.tfvars]
#
# Prerequisites:
#   - Terraform >= 1.5 installed
#   - gcloud authenticated: gcloud auth application-default login
#   - APIs enabled: logging, monitoring, cloudresourcemanager
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TF_DIR="${SCRIPT_DIR}/terraform"

COMMAND="${1:-plan}"
shift || true

# ── Pre-flight checks ─────────────────────────────────────────────────────────
if ! command -v terraform &>/dev/null; then
  echo "ERROR: terraform not found. Install from https://developer.hashicorp.com/terraform/downloads"
  exit 1
fi

TF_VERSION=$(terraform version -json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['terraform_version'])" 2>/dev/null || terraform version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
echo "Using Terraform ${TF_VERSION}"

if ! gcloud auth application-default print-access-token &>/dev/null; then
  echo "ERROR: No GCP credentials found."
  echo "Run: gcloud auth application-default login"
  exit 1
fi

PROJECT=$(gcloud config get-value project 2>/dev/null)
echo "GCP project: ${PROJECT:-<not set>}"

# ── Enable required APIs ──────────────────────────────────────────────────────
enable_apis() {
  local APIS=(
    "logging.googleapis.com"
    "monitoring.googleapis.com"
    "cloudresourcemanager.googleapis.com"
  )
  echo "Ensuring required APIs are enabled..."
  for api in "${APIS[@]}"; do
    gcloud services enable "${api}" --quiet 2>/dev/null || true
  done
}

# ── Terraform operations ──────────────────────────────────────────────────────
cd "${TF_DIR}"

case "${COMMAND}" in
  init)
    terraform init "$@"
    ;;
  plan)
    enable_apis
    terraform init -upgrade -reconfigure
    terraform validate
    terraform plan -out=tfplan "$@"
    ;;
  apply)
    enable_apis
    terraform init -upgrade -reconfigure
    terraform validate
    if [[ -f tfplan ]]; then
      echo "Applying saved plan..."
      terraform apply tfplan
    else
      terraform apply -auto-approve "$@"
    fi
    echo ""
    echo "✓ Monitoring resources applied."
    echo ""
    echo "Dashboard URLs (replace PROJECT_ID with your project):"
    terraform output -json | python3 -c "
import sys, json
out = json.load(sys.stdin)
for k, v in out.items():
    if 'dashboard' in k:
        val = v.get('value', '')
        # Extract dashboard ID from resource path
        # Format: projects/{project}/dashboards/{id}
        parts = val.split('/')
        if len(parts) >= 4:
            dash_id = parts[-1]
            print(f'  {k}: https://console.cloud.google.com/monitoring/dashboards/custom/{dash_id}')
" 2>/dev/null || true
    ;;
  destroy)
    echo "WARNING: This will delete all monitoring resources."
    read -p "Type 'yes' to confirm: " CONFIRM
    if [[ "${CONFIRM}" == "yes" ]]; then
      terraform destroy "$@"
    else
      echo "Aborted."
      exit 1
    fi
    ;;
  validate)
    terraform init -backend=false
    terraform validate
    echo "✓ Configuration is valid."
    ;;
  *)
    echo "Usage: $0 [init|plan|apply|destroy|validate] [terraform-args...]"
    exit 1
    ;;
esac
