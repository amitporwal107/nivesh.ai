#!/usr/bin/env bash
# setup_daas.sh — one-time provisioning for the NIDP DaaS API on GCP.
#
# Run this ONCE per environment, after bootstrap.sh --confirm.
# Idempotent: every step checks existence before creating.
#
# What it creates:
#   1. Secret Manager secrets   NIDP_DAAS_INTERNAL_TOKEN (optional escape-hatch)
#   2. Serverless VPC Connector nidp-vpc  (if not already present — needed to
#      reach the GCE VM's Postgres from Cloud Run)
#   3. Cloud Build IAM binding  cloud-build SA → Cloud Run developer
#      (so the Cloud Build pipeline can deploy the service)
#   4. [optional] Cloud Armor   rate-limiting WAF in front of the Cloud Run
#      service (requires a Global External HTTPS LB — see --armor flag)
#   5. [optional] Custom domain mapping on the Cloud Run service
#
# Usage:
#   ./setup_daas.sh --project=<PROJECT_ID> [options] [--confirm]
#
# Options:
#   --project=<ID>            GCP project (or GCP_PROJECT env)
#   --region=asia-south1      (default)
#   --vpc-network=default     VPC network name (default)
#   --vpc-subnet-range=10.8.0.0/28   /28 is the minimum; must not overlap
#   --internal-token=<tok>    Value for NIDP_DAAS_INTERNAL_TOKEN secret (random
#                             UUID generated if omitted)
#   --armor                   Also set up Cloud Armor WAF (needs a global LB —
#                             adds ~$18/mo for the LB + $1/mo per 1M requests)
#   --domain=api.nivesh.com   Custom domain to map to the service
#   --confirm                 Actually create resources

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$SCRIPT_DIR/gcp_resources.jsonl"

# ── Defaults ────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
VPC_NETWORK="${VPC_NETWORK:-default}"
VPC_SUBNET_RANGE="${VPC_SUBNET_RANGE:-10.8.0.0/28}"
INTERNAL_TOKEN="${NIDP_DAAS_INTERNAL_TOKEN:-}"
SETUP_ARMOR=false
CUSTOM_DOMAIN=""
DRY=true
SVC_NAME="nidp-daas-api"

# ── Args ────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --project=*)         PROJECT="${arg#*=}" ;;
        --region=*)          REGION="${arg#*=}" ;;
        --vpc-network=*)     VPC_NETWORK="${arg#*=}" ;;
        --vpc-subnet-range=*)VPC_SUBNET_RANGE="${arg#*=}" ;;
        --internal-token=*)  INTERNAL_TOKEN="${arg#*=}" ;;
        --armor)             SETUP_ARMOR=true ;;
        --domain=*)          CUSTOM_DOMAIN="${arg#*=}" ;;
        --confirm)           DRY=false ;;
        --dry-run)           DRY=true ;;
        -h|--help)           sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

# ── Helpers ──────────────────────────────────────────────────────────
log()     { echo "[setup-daas] $*"; }
maybe()   { if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi; }
die()     { echo "ERROR: $*" >&2; exit 1; }
manifest() {
    local row="{\"ts\":\"$(date -u +%FT%TZ)\",\"type\":\"$1\",\"name\":\"$2\",\"region\":\"$3\""
    [[ -n "${4:-}" ]] && row="$row,\"extra\":$4"
    row="$row}"
    echo "$row" >> "$MANIFEST"
}

command -v gcloud >/dev/null || die "gcloud CLI not found"
[[ -n "$PROJECT" ]] || die "--project is required (or GCP_PROJECT env)"

$DRY && log "🚧 dry-run mode — re-run with --confirm to apply"
log "project=$PROJECT  region=$REGION"

# ── 0. Pre-check: bootstrap.sh was run ─────────────────────────────
gcloud artifacts repositories describe nidp \
    --location="$REGION" --project="$PROJECT" &>/dev/null \
    || die "Artifact Registry 'nidp' not found. Run bootstrap.sh --confirm first."

# ── 1. Enable extra APIs needed for DaaS ───────────────────────────
EXTRA_APIS=(
    vpcaccess.googleapis.com       # Serverless VPC Access connector
    cloudbuild.googleapis.com      # Cloud Build CI/CD
    # Note: Cloud Armor is part of compute.googleapis.com (enabled by bootstrap.sh)
    # There is no separate cloudarmor.googleapis.com API to enable.
)
for api in "${EXTRA_APIS[@]}"; do
    maybe "gcloud services enable $api --project=$PROJECT"
done

# ── 2. Secret: NIDP_DAAS_INTERNAL_TOKEN (optional) ─────────────────
SECRET_NAME="NIDP_DAAS_INTERNAL_TOKEN"
if ! gcloud secrets describe "$SECRET_NAME" --project="$PROJECT" &>/dev/null; then
    if [[ -z "$INTERNAL_TOKEN" ]]; then
        # Generate a random 32-byte internal token — only for service-to-service
        # calls (e.g. the console admin panel querying the DaaS API).
        INTERNAL_TOKEN="$(python3 -c "import secrets; print('nvd_int_' + secrets.token_urlsafe(24))")"
        log "  generated internal token: ${INTERNAL_TOKEN:0:16}… (stored in Secret Manager)"
    fi
    maybe "printf '%s' '$INTERNAL_TOKEN' | gcloud secrets create $SECRET_NAME \
        --replication-policy=automatic --data-file=- --project=$PROJECT"
    $DRY || manifest "secret" "$SECRET_NAME" "global"
    log "  ✓ created secret: $SECRET_NAME"
else
    log "  ✓ secret already exists: $SECRET_NAME"
fi

# ── 3. Serverless VPC Access connector ──────────────────────────────
# Allows Cloud Run to reach the private GCE VM (where Postgres lives)
# without exposing the DB to the internet. /28 = 14 usable IPs —
# enough for the Cloud Run instances in this connector range.
VPC_CONN="nidp-vpc"
if ! gcloud compute networks vpc-access connectors describe "$VPC_CONN" \
        --region="$REGION" --project="$PROJECT" &>/dev/null; then
    log "  creating VPC connector $VPC_CONN ($VPC_SUBNET_RANGE on $VPC_NETWORK)"
    maybe "gcloud compute networks vpc-access connectors create $VPC_CONN \
        --network=$VPC_NETWORK \
        --region=$REGION \
        --range=$VPC_SUBNET_RANGE \
        --min-instances=2 \
        --max-instances=3 \
        --machine-type=e2-micro \
        --project=$PROJECT"
    $DRY || manifest "vpc_connector" "$VPC_CONN" "$REGION" \
        "{\"network\":\"$VPC_NETWORK\",\"range\":\"$VPC_SUBNET_RANGE\"}"
    log "  ✓ created VPC connector: $VPC_CONN"
else
    log "  ✓ VPC connector already exists: $VPC_CONN"
fi

# ── 4. Cloud Build SA needs Cloud Run developer role ─────────────────
# Cloud Build uses the default Cloud Build service account
# (PROJECT_NUMBER@cloudbuild.gserviceaccount.com) to deploy Cloud Run
# services. It needs run.developer (or run.admin) to update the
# service image on each push.
CB_SA_NUM=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
CB_SA="${CB_SA_NUM}@cloudbuild.gserviceaccount.com"
log "  granting Cloud Run developer to Cloud Build SA: $CB_SA"
for role in roles/run.developer roles/iam.serviceAccountUser; do
    maybe "gcloud projects add-iam-policy-binding $PROJECT \
        --member='serviceAccount:$CB_SA' --role='$role' --condition=None"
done

# ── 5. Grant nidp-sa access to read DaaS secrets ────────────────────
SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
maybe "gcloud secrets add-iam-policy-binding $SECRET_NAME \
    --member='serviceAccount:$SA_EMAIL' \
    --role='roles/secretmanager.secretAccessor' \
    --project=$PROJECT"
log "  ✓ nidp-sa can read $SECRET_NAME"

# ── 6. Cloud Armor WAF (optional) ────────────────────────────────────
# Cloud Armor requires a Global External HTTPS Load Balancer in front
# of Cloud Run. Without it, Cloud Run is directly internet-accessible
# (--allow-unauthenticated) but without LB-layer rate limiting or WAF.
#
# Cost: Global LB ~$18/mo + Cloud Armor $5/mo policy + $1/M requests.
# If your traffic is low (< 1M req/mo), the in-app rate limiter in
# ratelimit.py is sufficient and cheaper.
if $SETUP_ARMOR; then
    log "  setting up Cloud Armor (requires a Global HTTPS LB)..."
    ARMOR_POLICY="nidp-daas-rate-limit"
    NEG_NAME="nidp-daas-neg"                # Serverless Network Endpoint Group

    # Serverless NEG — backend for the LB → Cloud Run mapping
    if ! gcloud compute network-endpoint-groups describe "$NEG_NAME" \
            --region="$REGION" --project="$PROJECT" &>/dev/null; then
        maybe "gcloud compute network-endpoint-groups create $NEG_NAME \
            --region=$REGION \
            --network-endpoint-type=serverless \
            --cloud-run-service=$SVC_NAME \
            --project=$PROJECT"
        $DRY || manifest "network_endpoint_group" "$NEG_NAME" "$REGION"
    fi

    # Cloud Armor security policy: throttle > 100 req/s per IP globally
    if ! gcloud compute security-policies describe "$ARMOR_POLICY" \
            --project="$PROJECT" &>/dev/null; then
        maybe "gcloud compute security-policies create $ARMOR_POLICY \
            --description='DaaS API rate-limit + WAF baseline' \
            --project=$PROJECT"
        # Default-allow rule at priority 1000; allow common UA bots at 999
        maybe "gcloud compute security-policies rules create 900 \
            --security-policy=$ARMOR_POLICY \
            --expression='rate(request, 100)' \
            --action=throttle \
            --rate-limit-threshold-count=100 \
            --rate-limit-threshold-interval-sec=1 \
            --conform-action=allow \
            --exceed-action=deny-429 \
            --enforce-on-key=IP \
            --project=$PROJECT"
        $DRY || manifest "security_policy" "$ARMOR_POLICY" "global"
        log "  ✓ Cloud Armor policy created: $ARMOR_POLICY"
        log "  ⚠ You still need to create a Global HTTPS LB and attach this policy."
        log "    See: https://cloud.google.com/run/docs/securing/load-balancer"
    else
        log "  ✓ Cloud Armor policy already exists: $ARMOR_POLICY"
    fi
else
    log "  (skipping Cloud Armor — pass --armor to set it up)"
fi

# ── 7. Custom domain mapping (optional) ─────────────────────────────
if [[ -n "$CUSTOM_DOMAIN" ]]; then
    log "  mapping custom domain: $CUSTOM_DOMAIN → $SVC_NAME"
    maybe "gcloud beta run domain-mappings create \
        --service=$SVC_NAME \
        --domain=$CUSTOM_DOMAIN \
        --region=$REGION \
        --project=$PROJECT"
    log "  ✓ domain mapping created — add the CNAME DNS record shown above"
fi

# ── 8. Print next steps ─────────────────────────────────────────────
cat <<EOF

[setup-daas] ✅ one-time setup complete.

Next steps:
  1. Deploy the service:
       ./deploy_daas.sh --project=$PROJECT --confirm

  2. Issue your first DaaS API key:
       python -m nidp.cli daas-keygen \\
         --name "first-user" --owner ops@yourco.com --plan free

  3. Set up CI/CD (Cloud Build trigger on push):
       ./setup_github_trigger_daas.sh --project=$PROJECT --confirm

  4. (optional) Lock down CORS to your actual domain:
       ./deploy_daas.sh --project=$PROJECT \\
         --cors-origins=https://app.nivesh.com --confirm

EOF

$DRY && log "(dry-run only — re-run with --confirm to apply)"
