#!/usr/bin/env bash
# cloudflare-cutover.sh — point the two STAGING DNS records at the CloudPe VMs.
#
#   bash cloudflare-cutover.sh [plan]   [--token-file PATH]
#   bash cloudflare-cutover.sh apply    --backup FILE --yes [--skip-origin-check] [--token-file PATH]
#   bash cloudflare-cutover.sh rollback --backup FILE --yes [--token-file PATH]
#
#   plan      (default) GET the two records and print current -> target. Changes nothing.
#   apply     check the new origins answer, write the records' current state to
#             --backup FILE (must not exist yet), then PATCH only `content` of the
#             two A records. proxied/ttl are not sent, so they stay as they are.
#   rollback  PATCH the two records' `content` back to what --backup FILE holds.
#
#   --token-file PATH     read the API token from the first line of PATH
#                         (otherwise from env CF_API_TOKEN). Never printed.
#   --yes                 required for apply and rollback.
#   --skip-origin-check   apply without probing the new origins first.
#
# Safety: the only records this script can write are the A records named exactly
# staging.niveshcopilot.com and staging-data.niveshcopilot.com. It stops if a
# lookup returns anything but exactly one record, or if a record's current
# content is neither the known old IP nor the new one.
#
# Needs: curl, jq.   exit 0 ok · 1 refused/failed · 2 usage

set -euo pipefail

TAG="cf-cutover"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/common.sh
source "${HERE}/lib/common.sh"

# ── Constants ─────────────────────────────────────────────────────────────────
# Staging only. Every other record in the zone (apex, www, api, admin, assets,
# work, data, ide, tunnels, mail) is prod or unrelated and is never touched.
ZONE_NAME="niveshcopilot.com"
CF_API="https://api.cloudflare.com/client/v4"

HOSTS=(staging.niveshcopilot.com staging-data.niveshcopilot.com)

# OLD = GCP VMs (shared with prod).  NEW = CloudPe VMs (staging only).
declare -A OLD_IP=(
    [staging.niveshcopilot.com]="34.47.250.214"       # GCP app VM
    [staging-data.niveshcopilot.com]="34.93.60.254"   # GCP NIDP VM
)
declare -A NEW_IP=(
    [staging.niveshcopilot.com]="45.64.105.88"        # CloudPe app VM
    [staging-data.niveshcopilot.com]="45.64.105.224"  # CloudPe NIDP VM
)

# Ports Cloudflare will connect to on each new origin. The zone has an Origin
# Rule that sends staging.niveshcopilot.com to origin port 8443, so 8443 is the
# port that actually carries traffic for the app; 443 is checked too so the rule
# can be removed later. staging-data has no rule and uses 443.
declare -A ORIGIN_PORTS=(
    [staging.niveshcopilot.com]="443 8443"
    [staging-data.niveshcopilot.com]="443"
)
declare -A ORIGIN_PATH=(
    [staging.niveshcopilot.com]="/api/healthz"
    [staging-data.niveshcopilot.com]="/health"
)

IPV4_RE='^([0-9]{1,3}\.){3}[0-9]{1,3}$'

# ── Args ──────────────────────────────────────────────────────────────────────
usage() {
    sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
}

CMD="plan"
TOKEN_FILE=""
BACKUP=""
YES=false
SKIP_ORIGIN_CHECK=false

if [[ $# -gt 0 && "$1" != --* ]]; then CMD="$1"; shift; fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --token-file)        [[ $# -ge 2 ]] || usage; TOKEN_FILE="$2"; shift 2 ;;
        --backup)            [[ $# -ge 2 ]] || usage; BACKUP="$2"; shift 2 ;;
        --yes)               YES=true; shift ;;
        --skip-origin-check) SKIP_ORIGIN_CHECK=true; shift ;;
        -h|--help)           usage ;;
        *)                   echo "unknown argument: $1" >&2; usage ;;
    esac
done
case "$CMD" in plan|apply|rollback) ;; *) echo "unknown subcommand: $CMD" >&2; usage ;; esac

command -v curl >/dev/null 2>&1 || fail "curl not found"
command -v jq   >/dev/null 2>&1 || fail "jq not found"

# ── Token ─────────────────────────────────────────────────────────────────────
TOKEN="${CF_API_TOKEN:-}"
if [[ -n "$TOKEN_FILE" ]]; then
    [[ -r "$TOKEN_FILE" ]] || fail "Cannot read token file ${TOKEN_FILE}"
    TOKEN=$(sed -n 1p "$TOKEN_FILE" | tr -d '[:space:]')
fi
[[ -n "$TOKEN" ]] || fail "No API token: set CF_API_TOKEN or pass --token-file PATH."
[[ "$TOKEN" =~ ^[A-Za-z0-9_-]+$ ]] || fail "API token has unexpected characters (value not shown)."

# ── Cloudflare API ────────────────────────────────────────────────────────────
# The Authorization header goes to curl through a config on fd 3, so the token
# never appears in a process argument list or in `set -x` style output of curl.
cf_curl() {     # <method> <path> [json-body]
    local method="$1" path="$2" body="${3:-}" out
    local args=(-sS --max-time 30 -X "$method" -K /dev/fd/3 -H "Content-Type: application/json")
    [[ -n "$body" ]] && args+=(--data "$body")
    out=$(curl "${args[@]}" "${CF_API}${path}" 3< <(printf 'header = "Authorization: Bearer %s"\n' "$TOKEN")) \
        || fail "Cloudflare API ${method} ${path}: request failed."
    jq -e . >/dev/null 2>&1 <<<"$out" || fail "Cloudflare API ${method} ${path}: non-JSON response."
    if [[ "$(jq -r '.success' <<<"$out")" != "true" ]]; then
        fail "Cloudflare API ${method} ${path}: $(jq -c '.errors' <<<"$out")"
    fi
    printf '%s' "$out"
}

assert_allowed_host() {     # <fqdn> — the one gate every read and write goes through
    local h
    for h in "${HOSTS[@]}"; do [[ "$1" == "$h" ]] && return 0; done
    fail "Refusing to touch '$1' — not one of: ${HOSTS[*]}"
}

ZONE_ID=""
resolve_zone() {
    local out n
    out=$(cf_curl GET "/zones?name=${ZONE_NAME}")
    n=$(jq '.result | length' <<<"$out")
    [[ "$n" == "1" ]] || fail "Expected exactly one zone named ${ZONE_NAME}, got ${n}."
    [[ "$(jq -r '.result[0].name' <<<"$out")" == "$ZONE_NAME" ]] || fail "Zone lookup returned a different zone."
    ZONE_ID=$(jq -r '.result[0].id' <<<"$out")
    [[ "$ZONE_ID" =~ ^[0-9a-f]{32}$ ]] || fail "Unexpected zone id format."
}

# get_record <fqdn> — prints the single A record for <fqdn> as compact JSON.
get_record() {
    local host="$1" out n rec
    assert_allowed_host "$host"
    out=$(cf_curl GET "/zones/${ZONE_ID}/dns_records?type=A&name=${host}&per_page=100")
    n=$(jq '.result | length' <<<"$out")
    [[ "$n" == "1" ]] || fail "Expected exactly one A record for ${host}, found ${n} — refusing."
    rec=$(jq -c '.result[0] | {id, name, type, content, proxied, ttl}' <<<"$out")
    [[ "$(jq -r '.name' <<<"$rec")" == "$host" ]] || fail "Lookup for ${host} returned record named '$(jq -r '.name' <<<"$rec")' — refusing."
    [[ "$(jq -r '.type' <<<"$rec")" == "A" ]]     || fail "Record for ${host} is not type A — refusing."
    [[ "$(jq -r '.id' <<<"$rec")" =~ ^[0-9a-f]{32}$ ]] || fail "Unexpected record id format for ${host}."
    printf '%s' "$rec"
}

# set_content <fqdn> <record-id> <ipv4> — PATCH `content` only.
set_content() {
    local host="$1" id="$2" ip="$3" out
    assert_allowed_host "$host"
    [[ "$id" =~ ^[0-9a-f]{32}$ ]] || fail "Bad record id for ${host}."
    [[ "$ip" =~ $IPV4_RE ]]       || fail "Bad IPv4 '${ip}' for ${host}."
    out=$(cf_curl PATCH "/zones/${ZONE_ID}/dns_records/${id}" "$(jq -nc --arg c "$ip" '{content: $c}')")
    [[ "$(jq -r '.result.name' <<<"$out")" == "$host" && "$(jq -r '.result.type' <<<"$out")" == "A" ]] \
        || fail "PATCH response for ${host} names a different record: $(jq -c '.result | {id, name, type}' <<<"$out")"
    log "PATCHed ${host} → $(jq -r '.result.content' <<<"$out")"
}

show_record() {             # <label> <record-json>
    log "$1 $(jq -r '"\(.name)  A  \(.content)  proxied=\(.proxied)  ttl=\(.ttl)  id=\(.id)"' <<<"$2")"
}

# origin_listening <fqdn> <ip> <port> — any HTTP status counts: the origins only
# accept Cloudflare source addresses, so a 403 here still proves nginx is up
# with TLS. Connection refused / timeout / TLS failure does not.
origin_listening() {
    local host="$1" ip="$2" port="$3" code
    code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 \
            --resolve "${host}:${port}:${ip}" "https://${host}:${port}${ORIGIN_PATH[$host]}" 2>/dev/null) || true
    if [[ "$code" =~ ^[1-5][0-9][0-9]$ ]]; then
        log "origin ${ip}:${port} (${host}) answered HTTP ${code}"
        return 0
    fi
    warn "origin ${ip}:${port} (${host}) did not answer over TLS"
    return 1
}

# ── Subcommands ───────────────────────────────────────────────────────────────
declare -A CUR=()

load_current() {
    local host
    resolve_zone
    for host in "${HOSTS[@]}"; do CUR[$host]=$(get_record "$host"); done
}

do_plan() {
    local host content
    load_current
    log "Zone ${ZONE_NAME} (${ZONE_ID}) — nothing will be changed."
    for host in "${HOSTS[@]}"; do
        content=$(jq -r '.content' <<<"${CUR[$host]}")
        show_record "current:" "${CUR[$host]}"
        if   [[ "$content" == "${NEW_IP[$host]}" ]]; then log "  plan: no change (already ${NEW_IP[$host]})"
        elif [[ "$content" == "${OLD_IP[$host]}" ]]; then log "  plan: content ${content} → ${NEW_IP[$host]} (proxied/ttl unchanged)"
        else warn "  plan: UNEXPECTED content ${content} (expected ${OLD_IP[$host]} or ${NEW_IP[$host]}) — apply would refuse"
        fi
    done
}

do_apply() {
    local host content port ok=true
    $YES || fail "apply changes live DNS — re-run with --yes."
    [[ -n "$BACKUP" ]] || fail "apply needs --backup FILE."
    [[ ! -e "$BACKUP" ]] || fail "Backup file ${BACKUP} already exists — refusing to overwrite it."
    [[ -d "$(dirname "$BACKUP")" ]] || fail "Directory for ${BACKUP} does not exist."

    load_current
    for host in "${HOSTS[@]}"; do
        content=$(jq -r '.content' <<<"${CUR[$host]}")
        show_record "current:" "${CUR[$host]}"
        [[ "$content" == "${OLD_IP[$host]}" || "$content" == "${NEW_IP[$host]}" ]] \
            || fail "${host} points at ${content}, neither ${OLD_IP[$host]} nor ${NEW_IP[$host]} — refusing."
    done

    if $SKIP_ORIGIN_CHECK; then
        warn "Skipping the origin check (--skip-origin-check)."
    else
        for host in "${HOSTS[@]}"; do
            for port in ${ORIGIN_PORTS[$host]}; do
                origin_listening "$host" "${NEW_IP[$host]}" "$port" || ok=false
            done
        done
        $ok || fail "New origin(s) not ready — nothing changed. (--skip-origin-check overrides.)"
    fi

    ( umask 077
      jq -n --arg zone "$ZONE_NAME" --arg zone_id "$ZONE_ID" --arg at "$(date -Iseconds)" \
            --argjson a "${CUR[${HOSTS[0]}]}" --argjson b "${CUR[${HOSTS[1]}]}" \
            '{zone: $zone, zone_id: $zone_id, captured_at: $at, records: [$a, $b]}' > "$BACKUP" )
    jq -e '.records | length == 2' "$BACKUP" >/dev/null || fail "Backup ${BACKUP} did not write correctly — nothing changed."
    log "Backup written → ${BACKUP}"

    for host in "${HOSTS[@]}"; do
        content=$(jq -r '.content' <<<"${CUR[$host]}")
        if [[ "$content" == "${NEW_IP[$host]}" ]]; then
            log "${host} already at ${NEW_IP[$host]} — no PATCH."
        else
            set_content "$host" "$(jq -r '.id' <<<"${CUR[$host]}")" "${NEW_IP[$host]}"
        fi
    done

    for host in "${HOSTS[@]}"; do show_record "now:    " "$(get_record "$host")"; done
    log "Roll back with: bash $0 rollback --backup ${BACKUP} --yes"
}

do_rollback() {
    local host saved want content
    $YES || fail "rollback changes live DNS — re-run with --yes."
    [[ -n "$BACKUP" ]] || fail "rollback needs --backup FILE."
    [[ -r "$BACKUP" ]] || fail "Cannot read backup file ${BACKUP}."
    jq -e '(.records | type == "array") and (.records | length == 2)' "$BACKUP" >/dev/null 2>&1 \
        || fail "${BACKUP} is not a backup written by this script (need exactly two records)."
    [[ "$(jq -r '.zone' "$BACKUP")" == "$ZONE_NAME" ]] || fail "${BACKUP} is for a different zone."

    load_current
    for host in "${HOSTS[@]}"; do
        saved=$(jq -c --arg n "$host" '[.records[] | select(.name == $n and .type == "A")]' "$BACKUP")
        [[ "$(jq 'length' <<<"$saved")" == "1" ]] || fail "${BACKUP} does not hold exactly one A record for ${host}."
        want=$(jq -r '.[0].content' <<<"$saved")
        [[ "$want" =~ $IPV4_RE ]] || fail "Backup content for ${host} is not an IPv4 address."
        [[ "$(jq -r '.[0].id' <<<"$saved")" == "$(jq -r '.id' <<<"${CUR[$host]}")" ]] \
            || fail "Record id for ${host} differs from the backup — the record was recreated; refusing."
        content=$(jq -r '.content' <<<"${CUR[$host]}")
        show_record "current:" "${CUR[$host]}"
        [[ "$content" == "$want" || "$content" == "${NEW_IP[$host]}" ]] \
            || fail "${host} points at ${content}, neither the backup (${want}) nor ${NEW_IP[$host]} — refusing."
    done

    for host in "${HOSTS[@]}"; do
        want=$(jq -r --arg n "$host" '.records[] | select(.name == $n and .type == "A") | .content' "$BACKUP")
        if [[ "$(jq -r '.content' <<<"${CUR[$host]}")" == "$want" ]]; then
            log "${host} already at ${want} — no PATCH."
        else
            set_content "$host" "$(jq -r '.id' <<<"${CUR[$host]}")" "$want"
        fi
    done

    for host in "${HOSTS[@]}"; do show_record "now:    " "$(get_record "$host")"; done
}

case "$CMD" in
    plan)     do_plan ;;
    apply)    do_apply ;;
    rollback) do_rollback ;;
esac
