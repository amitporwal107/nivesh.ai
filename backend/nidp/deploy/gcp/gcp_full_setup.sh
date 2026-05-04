#!/usr/bin/env bash
# gcp_full_setup.sh — end-to-end NIDP GCP provisioning.
#
# Runs phases 0..10 from the runbook. Each phase can be invoked alone
# (--only=N) or skipped to (--phase=N). Default is --dry-run. Pass
# --confirm to actually create resources.
#
# Phases:
#   0  preflight (gcloud, auth, billing, APIs)
#   1  setup_credentials.sh   — runtime SA + key
#   2  bootstrap.sh           — bucket, secrets, AR repo, VM
#   3  firewall + VPC connector for Cloud Run -> VM
#   4  data plane on VM       — install docker, run docker-compose
#   5  populate secret values — POSTGRES_URL, KAFKA_BROKERS, etc.
#   6  apply NIDP migrations  — via SSH tunnel
#   7  deploy.sh              — build/push images + Cloud Run Jobs
#   8  smoke test             — execute nidp-nse-calendar
#   9  Cloud Scheduler        — daily cron triggers
#  10  Grafana port-forward   — open dashboard locally
#
# Usage:
#   ./gcp_full_setup.sh --project=<PROJECT> [--region=asia-south1]
#                       [--phase=N]   # start at phase N (default 0)
#                       [--only=N]    # run ONLY phase N
#                       [--confirm]   # actually create resources
#
# Env overrides:
#   GCP_PROJECT, GCP_REGION, GCP_ZONE, NIDP_VM_NAME

set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────
PROJECT="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-${REGION}-a}"
VM_NAME="${NIDP_VM_NAME:-nidp-stack-vm}"
PHASE_START=0
PHASE_ONLY=
CONFIRM=
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Args ────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}" ;;
        --region=*)  REGION="${arg#*=}"; ZONE="${REGION}-a" ;;
        --zone=*)    ZONE="${arg#*=}" ;;
        --phase=*)   PHASE_START="${arg#*=}" ;;
        --only=*)    PHASE_ONLY="${arg#*=}" ;;
        --confirm)   CONFIRM=1 ;;
        --dry-run)   CONFIRM= ;;
        -h|--help)   sed -n '2,32p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

if [[ -z "$PROJECT" ]]; then
    echo "ERROR: --project is required (or GCP_PROJECT env)" >&2; exit 2
fi

DRY=$([[ -z "$CONFIRM" ]] && echo true || echo false)
log() { echo -e "\033[1;36m[gcp-setup]\033[0m $*"; }
warn() { echo -e "\033[1;33m[gcp-setup]\033[0m $*"; }
err()  { echo -e "\033[1;31m[gcp-setup]\033[0m $*" >&2; }
section() { echo; echo -e "\033[1;35m──── PHASE $1: $2 ────\033[0m"; }
maybe() {
    if $DRY; then log "DRY-RUN  $*"; else log "RUN      $*"; eval "$@"; fi
}
should_run() {
    local n=$1
    if [[ -n "$PHASE_ONLY" ]]; then [[ "$n" == "$PHASE_ONLY" ]]; return; fi
    [[ "$n" -ge "$PHASE_START" ]]
}
confirm_or_die() {
    local prompt="$1"
    $DRY && return 0
    read -p "$prompt [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || { err "aborted"; exit 1; }
}

if $DRY; then
    warn "🚧 DRY-RUN. Re-run with --confirm to actually create resources."
fi

cat <<EOF

[gcp-setup] config:
  project:    $PROJECT
  region:     $REGION
  zone:       $ZONE
  vm name:    $VM_NAME
  phases:     ${PHASE_ONLY:+only $PHASE_ONLY}${PHASE_ONLY:-from $PHASE_START}
  mode:       $($DRY && echo dry-run || echo CONFIRM)

EOF

# ────────────────────────────────────────────────────────────────────
# Phase 0 — Preflight
# ────────────────────────────────────────────────────────────────────
if should_run 0; then
    section 0 "preflight"

    if ! command -v gcloud >/dev/null; then
        err "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
        exit 1
    fi
    log "  ✓ gcloud installed: $(gcloud version --format='value(\"Google Cloud SDK\")' 2>/dev/null | head -1)"

    ACTIVE=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)
    if [[ -z "$ACTIVE" ]]; then
        err "no active gcloud account. Run: gcloud auth login && gcloud auth application-default login"
        exit 1
    fi
    log "  ✓ authenticated as: $ACTIVE"

    if ! gcloud projects describe "$PROJECT" &>/dev/null; then
        err "project '$PROJECT' not found or no access"
        exit 1
    fi
    log "  ✓ project accessible: $PROJECT"

    BILL=$(gcloud beta billing projects describe "$PROJECT" \
        --format='value(billingEnabled)' 2>/dev/null || echo false)
    if [[ "$BILL" != "True" ]]; then
        err "billing NOT enabled on $PROJECT. Enable it in console first."
        exit 1
    fi
    log "  ✓ billing enabled"

    gcloud config set project "$PROJECT" --quiet >/dev/null
    log "  ✓ gcloud default project set to $PROJECT"

    # Budget alert reminder
    BUDGETS=$(gcloud beta billing budgets list \
        --billing-account="$(gcloud beta billing projects describe "$PROJECT" --format='value(billingAccountName)' | sed 's|.*/||')" \
        --format='value(displayName)' 2>/dev/null | wc -l || echo 0)
    if [[ "$BUDGETS" -eq 0 ]]; then
        warn "  ⚠ no budget alerts found on this billing account."
        warn "    set one at: https://console.cloud.google.com/billing/budgets"
        warn "    recommended: \$50/mo with 50%/90%/100% thresholds"
        $DRY || confirm_or_die "Continue without a budget alert?"
    else
        log "  ✓ $BUDGETS budget alert(s) configured"
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 1 — runtime SA + key
# ────────────────────────────────────────────────────────────────────
if should_run 1; then
    section 1 "runtime SA + JSON key"
    if $DRY; then
        log "would run: $SCRIPT_DIR/setup_credentials.sh --project=$PROJECT"
    else
        bash "$SCRIPT_DIR/setup_credentials.sh" --project="$PROJECT" --region="$REGION" --confirm
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 2 — project resources (bucket, secrets, AR, VM)
# ────────────────────────────────────────────────────────────────────
if should_run 2; then
    section 2 "bucket + secrets + AR + GCE VM"
    confirm_or_die "About to provision resources that cost ~₹13/day (GCE VM). OK to proceed?"
    if $DRY; then
        log "would run: $SCRIPT_DIR/bootstrap.sh"
    else
        GCP_PROJECT="$PROJECT" GCP_REGION="$REGION" GCP_ZONE="$ZONE" \
            bash "$SCRIPT_DIR/bootstrap.sh" --confirm
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 3 — firewall + VPC connector
# ────────────────────────────────────────────────────────────────────
if should_run 3; then
    section 3 "firewall + VPC connector for Cloud Run -> VM"

    if ! gcloud compute firewall-rules describe nidp-allow-internal \
            --project="$PROJECT" &>/dev/null; then
        maybe "gcloud compute firewall-rules create nidp-allow-internal \
            --network=default \
            --allow=tcp:5432,tcp:9092,tcp:8081,tcp:6379,tcp:9090,tcp:3000 \
            --source-ranges=10.0.0.0/8 \
            --target-tags=nidp-stack \
            --project=$PROJECT --quiet"
    else
        log "  ✓ firewall rule nidp-allow-internal already exists"
    fi

    # Tag the VM so the firewall applies
    if ! $DRY; then
        gcloud compute instances add-tags $VM_NAME --tags=nidp-stack \
            --zone=$ZONE --project=$PROJECT --quiet || true
    fi

    if ! gcloud compute networks vpc-access connectors describe nidp-vpc \
            --region=$REGION --project=$PROJECT &>/dev/null; then
        maybe "gcloud compute networks vpc-access connectors create nidp-vpc \
            --region=$REGION --range=10.8.0.0/28 \
            --network=default --machine-type=e2-micro \
            --min-instances=2 --max-instances=3 \
            --project=$PROJECT --quiet"
    else
        log "  ✓ VPC connector nidp-vpc already exists"
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 4 — data plane on VM (docker-compose)
# ────────────────────────────────────────────────────────────────────
if should_run 4; then
    section 4 "data plane on VM"

    DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
    if $DRY; then
        log "would scp $DEPLOY_DIR/docker-compose.dev.yml + prometheus.yml + grafana/ to VM"
        log "would ssh + apt-get install docker + docker compose up -d"
    else
        log "  pushing compose stack to VM..."
        gcloud compute scp --recurse \
            "$DEPLOY_DIR/docker-compose.dev.yml" \
            "$DEPLOY_DIR/prometheus.yml" \
            "$DEPLOY_DIR/grafana" \
            $VM_NAME:/tmp/nidp/ \
            --zone=$ZONE --project=$PROJECT --quiet

        log "  installing docker + bringing stack up (may take ~3 min)..."
        gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT --quiet \
            --command='
            set -e
            if ! command -v docker >/dev/null; then
                sudo apt-get update -qq
                sudo apt-get install -y -qq docker.io docker-compose-plugin
            fi
            sudo mkdir -p /opt/nidp
            sudo cp -r /tmp/nidp/* /opt/nidp/
            cd /opt/nidp
            sudo docker compose -f docker-compose.dev.yml up -d
            sleep 6
            sudo docker compose -f docker-compose.dev.yml ps
            '
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 5 — populate Secret Manager
# ────────────────────────────────────────────────────────────────────
if should_run 5; then
    section 5 "populate Secret Manager values"

    if $DRY; then
        log "would write VM internal IP to NIDP_POSTGRES_URL, NIDP_KAFKA_BROKERS, etc."
    else
        VM_IP=$(gcloud compute instances describe $VM_NAME --zone=$ZONE \
            --project=$PROJECT --format='value(networkInterfaces[0].networkIP)')
        log "  VM internal IP: $VM_IP"

        echo -n "postgres://postgres:postgres@${VM_IP}:5432/nidp" | \
            gcloud secrets versions add NIDP_POSTGRES_URL --data-file=- --project=$PROJECT --quiet
        echo -n "${VM_IP}:9092" | \
            gcloud secrets versions add NIDP_KAFKA_BROKERS --data-file=- --project=$PROJECT --quiet
        echo -n "nidp-raw-${PROJECT}" | \
            gcloud secrets versions add NIDP_S3_BUCKET --data-file=- --project=$PROJECT --quiet
        echo -n "redis://${VM_IP}:6379/0" | \
            gcloud secrets versions add NIDP_REDIS_URL --data-file=- --project=$PROJECT --quiet
        echo -n "http://${VM_IP}:8081" | \
            gcloud secrets versions add NIDP_SCHEMA_REGISTRY_URL --data-file=- --project=$PROJECT --quiet
        log "  ✓ all 5 NIDP_* secrets updated"
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 6 — apply NIDP migrations
# ────────────────────────────────────────────────────────────────────
if should_run 6; then
    section 6 "apply NIDP migrations"

    if $DRY; then
        log "would open SSH tunnel to VM PG and run python -m nidp.cli migrate"
    else
        log "  opening SSH tunnel localhost:5433 -> VM:5432 ..."
        # Background tunnel; trap will close it
        gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT --quiet \
            -- -L 5433:localhost:5432 -N -f
        sleep 2

        BACKEND_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
        log "  running migrations from $BACKEND_DIR ..."
        cd "$BACKEND_DIR"
        NIDP_POSTGRES_URL="postgres://postgres:postgres@localhost:5433/nidp" \
            python -m nidp.cli migrate || warn "migrations failed; check tunnel + PG"

        # Close tunnel
        pkill -f "ssh.*5433:localhost:5432" 2>/dev/null || true
        cd - >/dev/null
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 7 — build images + Cloud Run Jobs
# ────────────────────────────────────────────────────────────────────
if should_run 7; then
    section 7 "build + push images, create Cloud Run Jobs"
    confirm_or_die "Building 11 service images takes ~5 min on first run. Proceed?"
    if $DRY; then
        log "would run: $SCRIPT_DIR/deploy.sh"
    else
        GCP_PROJECT="$PROJECT" GCP_REGION="$REGION" \
            bash "$SCRIPT_DIR/deploy.sh" --confirm
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 8 — smoke test
# ────────────────────────────────────────────────────────────────────
if should_run 8; then
    section 8 "smoke test (nidp-nse-calendar)"

    if $DRY; then
        log "would: gcloud run jobs execute nidp-nse-calendar --region=$REGION --wait"
    else
        log "  executing nidp-nse-calendar (cheap, ~30s)..."
        gcloud run jobs execute nidp-nse-calendar \
            --region=$REGION --project=$PROJECT --wait || warn "smoke job failed"

        log "  recent log entries:"
        gcloud logging read \
            "resource.type=cloud_run_job AND resource.labels.job_name=nidp-nse-calendar" \
            --limit=10 --format='value(textPayload)' --project=$PROJECT \
            | sed 's/^/    /'

        # Verify rows landed in PG via a quick SSH query
        gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT --quiet \
            --command='sudo docker exec nidp-postgres psql -U postgres -d nidp \
                -c "SELECT count(*) AS holidays FROM nidp.nse_holidays;"' || true
    fi
fi

# ────────────────────────────────────────────────────────────────────
# Phase 9 — Cloud Scheduler triggers
# ────────────────────────────────────────────────────────────────────
if should_run 9; then
    section 9 "Cloud Scheduler triggers"

    SA_EMAIL="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
    RUN_API="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs"

    add_schedule() {
        local job=$1 cron=$2
        if gcloud scheduler jobs describe "nidp-cron-$job" \
                --location=$REGION --project=$PROJECT &>/dev/null; then
            log "  ✓ schedule already exists: nidp-cron-$job"
            return
        fi
        maybe "gcloud scheduler jobs create http nidp-cron-$job \
            --schedule='$cron' --time-zone='Asia/Kolkata' \
            --uri='${RUN_API}/${job}:run' --http-method=POST \
            --oauth-service-account-email=$SA_EMAIL \
            --location=$REGION --project=$PROJECT --quiet"
    }

    add_schedule nidp-bhavcopy           '0 19 * * 1-5'
    add_schedule nidp-delivery           '30 10 * * 2-6'
    add_schedule nidp-index-close        '0 19 * * 1-5'
    add_schedule nidp-fii-dii            '30 19 * * 1-5'
    add_schedule nidp-bulk-deals         '30 19 * * 1-5'
    add_schedule nidp-block-deals        '30 19 * * 1-5'
    add_schedule nidp-corporate-actions  '0 20 * * *'
    add_schedule nidp-rbi-yields         '30 20 * * 1-5'
    add_schedule nidp-nse-calendar       '0 6 1 * *'
    add_schedule nidp-snapshot-builder   '0 22 * * 1-5'
fi

# ────────────────────────────────────────────────────────────────────
# Phase 10 — Grafana access
# ────────────────────────────────────────────────────────────────────
if should_run 10; then
    section 10 "Grafana access"

    cat <<EOF

  To open Grafana from your laptop:

      gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT \\
          -- -L 3000:localhost:3000 -N -f
      open http://localhost:3000   # admin / admin

  Pre-provisioned dashboards:
      - NIDP — Ingestion Overview
      - NIDP — Snapshot & Validation

EOF
fi

# ────────────────────────────────────────────────────────────────────
echo
log "✅ done."
$DRY && warn "(dry-run only — re-run with --confirm to apply)"

cat <<EOF

  Next:
      • Tail logs:     gcloud logging read 'resource.type=cloud_run_job' \\
                            --limit=50 --project=$PROJECT
      • Trigger any:   gcloud run jobs execute <job-name> --region=$REGION --wait
      • Rotate keys:   $SCRIPT_DIR/rotate_credentials.sh --confirm
      • Tear down:     $SCRIPT_DIR/teardown.sh --confirm

EOF
