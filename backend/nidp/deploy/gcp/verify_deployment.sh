#!/usr/bin/env bash
# verify_deployment.sh — single comprehensive health check for the
# entire NIDP GCP deployment. Read-only — performs no destructive
# actions. Prints a categorized check matrix and exits 0 only when
# every check passes.
#
# Usage:
#   ./verify_deployment.sh [--project=PROJECT] [--region=asia-south1]
#                          [--smoke]   # also fire a real ingester run
#
# Exit codes:
#   0 — everything green
#   1 — at least one check failed
#   2 — preflight (gcloud / auth / project) failed; checks didn't run

set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"
ZONE="${GCP_ZONE:-${REGION}-a}"
VM="${NIDP_VM_NAME:-nidp-stack-vm}"
RUN_SMOKE=

for arg in "$@"; do
    case "$arg" in
        --project=*) PROJECT="${arg#*=}" ;;
        --region=*)  REGION="${arg#*=}"; ZONE="${REGION}-a" ;;
        --zone=*)    ZONE="${arg#*=}" ;;
        --smoke)     RUN_SMOKE=1 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
    esac
done

# ── Output helpers ──────────────────────────────────────────────────
PASS=0
FAIL=0
WARN=0
FAILED_CHECKS=()

GREEN="\033[1;32m"; RED="\033[1;31m"; YEL="\033[1;33m"
CYAN="\033[1;36m"; MAGENTA="\033[1;35m"; RESET="\033[0m"

section() { echo; echo -e "${MAGENTA}── $1 ──${RESET}"; }
ok()    { echo -e "  ${GREEN}✅${RESET} $1"; PASS=$((PASS+1)); }
fail()  { echo -e "  ${RED}❌${RESET} $1"; FAIL=$((FAIL+1)); FAILED_CHECKS+=("$1"); }
warn()  { echo -e "  ${YEL}⚠${RESET}  $1"; WARN=$((WARN+1)); }
info()  { echo -e "  ${CYAN}ℹ${RESET}  $1"; }

cat <<EOF
${CYAN}NIDP deployment verification${RESET}
  project:   $PROJECT
  region:    $REGION
  zone:      $ZONE
  vm:        $VM
  smoke run: $([[ -n "$RUN_SMOKE" ]] && echo yes || echo no)

EOF

# ── 0. Preflight ────────────────────────────────────────────────────
section "0. Preflight"
if ! command -v gcloud >/dev/null; then
    echo "ERROR: gcloud CLI not found." >&2; exit 2
fi
ok "gcloud installed"

ACTIVE=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)
if [[ -z "$ACTIVE" ]]; then
    fail "no active gcloud account — run gcloud auth login"
    exit 2
fi
ok "authenticated as $ACTIVE"

if ! gcloud projects describe "$PROJECT" &>/dev/null; then
    fail "project '$PROJECT' not accessible"
    exit 2
fi
ok "project accessible"

# ── 1. Service account + key ────────────────────────────────────────
section "1. Service account"
SA="nidp-sa@${PROJECT}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$SA" --project="$PROJECT" &>/dev/null; then
    ok "SA exists: $SA"
else
    fail "SA missing: $SA"
fi

ROLES_BOUND=$(gcloud projects get-iam-policy "$PROJECT" \
    --format=json 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
sa = '$SA'
roles = []
for b in d.get('bindings', []):
    if 'serviceAccount:' + sa in b.get('members', []):
        roles.append(b['role'])
print('\n'.join(sorted(roles)))
")
EXPECTED=(
    roles/storage.objectAdmin
    roles/secretmanager.secretAccessor
    roles/run.developer
    roles/cloudscheduler.jobRunner
    roles/artifactregistry.writer
    roles/logging.logWriter
)
for r in "${EXPECTED[@]}"; do
    if grep -qx "$r" <<< "$ROLES_BOUND"; then
        ok "role bound: $r"
    else
        fail "role MISSING: $r"
    fi
done

# ── 2. APIs enabled ─────────────────────────────────────────────────
section "2. APIs enabled"
NEEDED_APIS=(
    iam.googleapis.com
    secretmanager.googleapis.com
    storage.googleapis.com
    artifactregistry.googleapis.com
    run.googleapis.com
    cloudscheduler.googleapis.com
    compute.googleapis.com
    vpcaccess.googleapis.com
    logging.googleapis.com
)
ENABLED=$(gcloud services list --enabled --project="$PROJECT" \
    --format='value(config.name)' 2>/dev/null)
for a in "${NEEDED_APIS[@]}"; do
    if grep -qx "$a" <<< "$ENABLED"; then
        ok "$a"
    else
        fail "$a NOT enabled"
    fi
done

# ── 3. Storage bucket ───────────────────────────────────────────────
section "3. GCS bucket"
BUCKET="nidp-raw-${PROJECT}"
if gcloud storage buckets describe "gs://$BUCKET" --project="$PROJECT" &>/dev/null; then
    ok "bucket exists: gs://$BUCKET"
else
    fail "bucket missing: gs://$BUCKET"
fi

# ── 4. Secret Manager values ────────────────────────────────────────
section "4. Secrets"
for s in NIDP_POSTGRES_URL NIDP_KAFKA_BROKERS NIDP_S3_BUCKET NIDP_REDIS_URL NIDP_SCHEMA_REGISTRY_URL; do
    if gcloud secrets describe "$s" --project="$PROJECT" &>/dev/null; then
        VAL=$(gcloud secrets versions access latest --secret="$s" --project="$PROJECT" 2>/dev/null || true)
        if [[ -z "$VAL" || "$VAL" == "SET_ME" ]]; then
            fail "$s exists but value is empty/placeholder"
        else
            ok "$s populated"
        fi
    else
        fail "$s does not exist"
    fi
done

# ── 5. Artifact Registry + 11 images ────────────────────────────────
section "5. Artifact Registry"
if gcloud artifacts repositories describe nidp \
        --location="$REGION" --project="$PROJECT" &>/dev/null; then
    ok "AR repo nidp/ exists"
else
    fail "AR repo nidp/ missing"
fi

EXPECTED_IMAGES=(
    bulk_deals block_deals bhavcopy delivery
    index_close index_constituents fii_dii corporate_actions
    nse_calendar rbi_yields snapshot_builder
)
HOST="${REGION}-docker.pkg.dev"
for svc in "${EXPECTED_IMAGES[@]}"; do
    if gcloud artifacts docker tags list "$HOST/$PROJECT/nidp/$svc" \
            --project="$PROJECT" --format='value(tag)' 2>/dev/null \
            | grep -q latest; then
        ok "image $svc:latest pushed"
    else
        fail "image $svc:latest NOT pushed"
    fi
done

# ── 6. GCE VM ───────────────────────────────────────────────────────
section "6. GCE VM"
VM_STATE=$(gcloud compute instances describe "$VM" --zone="$ZONE" \
    --project="$PROJECT" --format='value(status)' 2>/dev/null || echo NONE)
if [[ "$VM_STATE" == "RUNNING" ]]; then
    ok "VM $VM is RUNNING"
elif [[ "$VM_STATE" == "NONE" ]]; then
    fail "VM $VM does not exist"
else
    fail "VM $VM is $VM_STATE (not RUNNING)"
fi

VM_IP=$(gcloud compute instances describe "$VM" --zone="$ZONE" \
    --project="$PROJECT" --format='value(networkInterfaces[0].networkIP)' 2>/dev/null || echo "")
[[ -n "$VM_IP" ]] && info "VM internal IP: $VM_IP"

# ── 7. Firewall + VPC connector ─────────────────────────────────────
section "7. Network"
if gcloud compute firewall-rules describe nidp-allow-internal \
        --project="$PROJECT" &>/dev/null; then
    ok "firewall rule nidp-allow-internal exists"
else
    fail "firewall rule nidp-allow-internal missing"
fi

VPC_STATE=$(gcloud compute networks vpc-access connectors describe nidp-vpc \
    --region="$REGION" --project="$PROJECT" \
    --format='value(state)' 2>/dev/null || echo NONE)
case "$VPC_STATE" in
    READY)    ok "VPC connector nidp-vpc is READY" ;;
    CREATING) warn "VPC connector still CREATING — wait ~5 min" ;;
    NONE)     fail "VPC connector nidp-vpc does not exist" ;;
    *)        fail "VPC connector state: $VPC_STATE" ;;
esac

# ── 8. Containers running on VM ─────────────────────────────────────
section "8. VM data plane (docker compose stack)"
if [[ "$VM_STATE" == "RUNNING" ]]; then
    RUNNING_CONTAINERS=$(gcloud compute ssh "$VM" --zone="$ZONE" \
        --project="$PROJECT" --quiet \
        --command='sudo docker ps --format "{{.Names}}"' 2>/dev/null \
        | tr -d '\r' || true)
    EXPECTED_CONTAINERS=(
        nidp-postgres nidp-redpanda nidp-schema-registry
        nidp-redis nidp-minio nidp-prometheus nidp-grafana
    )
    for c in "${EXPECTED_CONTAINERS[@]}"; do
        if grep -qx "$c" <<< "$RUNNING_CONTAINERS"; then
            ok "container running: $c"
        else
            fail "container NOT running: $c"
        fi
    done

    # PG reachable + nidp schema present
    PG_TABLES=$(gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
        --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -tA \
            -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='\''nidp'\''"' \
        2>/dev/null | tr -d '\r' || echo "")
    if [[ -n "$PG_TABLES" ]] && [[ "$PG_TABLES" -ge 18 ]]; then
        ok "Postgres reachable + $PG_TABLES nidp.* tables"
    else
        fail "Postgres / nidp schema unhealthy (table count: '${PG_TABLES:-error}')"
    fi

    # Migrations applied
    MIGRATIONS=$(gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
        --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -tA \
            -c "SELECT count(*) FROM nidp.schema_migrations"' \
        2>/dev/null | tr -d '\r' || echo "")
    if [[ -n "$MIGRATIONS" ]] && [[ "$MIGRATIONS" -ge 7 ]]; then
        ok "schema_migrations rows: $MIGRATIONS"
    else
        fail "schema_migrations rows: '${MIGRATIONS:-error}' (expected ≥ 7)"
    fi
else
    warn "skipping VM-internal checks — VM not running"
fi

# ── 9. Cloud Run Jobs (config + status) ─────────────────────────────
section "9. Cloud Run Jobs"
EXPECTED_JOBS=(
    nidp-bulk-deals nidp-block-deals nidp-bhavcopy nidp-delivery
    nidp-index-close nidp-index-constituents nidp-fii-dii
    nidp-corporate-actions nidp-nse-calendar nidp-rbi-yields
    nidp-snapshot-builder
)
for j in "${EXPECTED_JOBS[@]}"; do
    JOB_DESC=$(gcloud run jobs describe "$j" --region="$REGION" \
        --project="$PROJECT" --format=json 2>/dev/null || echo "")
    if [[ -z "$JOB_DESC" ]]; then
        fail "job $j does not exist"
        continue
    fi
    HAS_VPC=$(echo "$JOB_DESC" | python3 -c "
import json, sys
d = json.load(sys.stdin)
ann = d.get('spec', {}).get('template', {}).get('metadata', {}).get('annotations', {})
print('yes' if ann.get('run.googleapis.com/vpc-access-connector') else 'no')
" 2>/dev/null || echo "no")
    if [[ "$HAS_VPC" == "yes" ]]; then
        ok "$j (VPC wired)"
    else
        fail "$j exists but VPC connector NOT wired — Cloud Run can't reach VM"
    fi
done

# ── 10. Cloud Scheduler triggers ────────────────────────────────────
section "10. Cloud Scheduler"
SCHEDULES=$(gcloud scheduler jobs list --location="$REGION" \
    --project="$PROJECT" --format='value(name)' 2>/dev/null \
    | grep -c "nidp-cron-" || echo 0)
if [[ "$SCHEDULES" -ge 10 ]]; then
    ok "Scheduler triggers: $SCHEDULES"
else
    warn "Scheduler triggers: $SCHEDULES (expected 10) — phase 9 may be incomplete"
fi

# ── 11. Optional smoke test ─────────────────────────────────────────
if [[ -n "$RUN_SMOKE" ]]; then
    section "11. Smoke test (live ingester run)"
    info "executing nidp-nse-calendar (cheapest, ~30s)..."
    if gcloud run jobs execute nidp-nse-calendar \
            --region="$REGION" --project="$PROJECT" --wait 2>&1 | tail -3; then
        # verify rows landed
        HOLIDAYS=$(gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
            --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -tA \
                -c "SELECT count(*) FROM nidp.nse_holidays"' \
            2>/dev/null | tr -d '\r' || echo "")
        if [[ -n "$HOLIDAYS" ]] && [[ "$HOLIDAYS" -gt 0 ]]; then
            ok "nidp.nse_holidays has $HOLIDAYS rows after smoke run"
        else
            fail "nidp.nse_holidays still empty after smoke run"
        fi
    else
        fail "nidp-nse-calendar smoke run failed"
    fi
fi

# ── 12. Recent job runs (read-only summary) ─────────────────────────
section "12. Last 24h runs from nidp.job_log"
if [[ "$VM_STATE" == "RUNNING" ]]; then
    gcloud compute ssh "$VM" --zone="$ZONE" --project="$PROJECT" --quiet \
        --command='sudo docker exec nidp-postgres psql -U postgres -d nidp -P pager=off -c \
        "SELECT ingester, target_date, status, rows_inserted, finished_at
           FROM nidp.job_log
          WHERE started_at > NOW() - INTERVAL '\''24 hours'\''
          ORDER BY started_at DESC LIMIT 20"' 2>/dev/null \
        | sed 's/^/    /'
else
    warn "skipped — VM not running"
fi

# ── Summary ─────────────────────────────────────────────────────────
echo
echo -e "${MAGENTA}══════════════════════════════════════════════════${RESET}"
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}✅ ALL CHECKS PASSED${RESET} (passed=$PASS, warned=$WARN)"
    exit 0
else
    echo -e "${RED}❌ $FAIL CHECK(S) FAILED${RESET} (passed=$PASS, warned=$WARN)"
    echo
    echo "failed checks:"
    for c in "${FAILED_CHECKS[@]}"; do
        echo "  - $c"
    done
    exit 1
fi
