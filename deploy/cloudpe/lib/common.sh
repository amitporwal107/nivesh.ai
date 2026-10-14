#!/usr/bin/env bash
# common.sh — helpers shared by the CloudPe staging scripts. Source, don't run.
#
# Callers set TAG (log prefix) before sourcing.

TAG="${TAG:-cloudpe}"

log()  { echo "[${TAG}] $*"; }
warn() { echo "[${TAG}] WARN: $*" >&2; }
fail() { echo "[${TAG}] FATAL: $*" >&2; exit 1; }

require_root() { [[ $EUID -eq 0 ]] || fail "Run as root (sudo)."; }

# The scripts are written for Ubuntu 24.04 (what the CloudPe VMs run). Debian
# works for the Docker repo too; anything else is refused rather than guessed at.
require_apt_os() {
    [[ -r /etc/os-release ]] || fail "/etc/os-release missing — unsupported OS."
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
        ubuntu|debian) ;;
        *) fail "Unsupported OS '${ID:-unknown}' (need ubuntu or debian)." ;;
    esac
    OS_ID="$ID"
    OS_CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
    [[ -n "$OS_CODENAME" ]] || fail "Could not determine OS codename."
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
}

# The staging cron files schedule in IST via CRON_TZ, which Debian/Ubuntu cron
# ignores (crontab(5), LIMITATIONS) — the schedules only mean IST if the system
# clock is IST. The GCP VMs are set the same way (vm/bootstrap-staging.sh).
set_timezone_ist() {
    if [[ "$(timedatectl show -p Timezone --value 2>/dev/null)" != "Asia/Kolkata" ]]; then
        log "Setting system timezone to Asia/Kolkata"
        timedatectl set-timezone Asia/Kolkata
        systemctl restart cron 2>/dev/null || true
    fi
}

# Docker CE + compose plugin from Docker's own apt repo. The override files use
# !reset / !override (Compose >= 2.24) and the app base file uses gw_priority,
# which Compose rejects before 2.33.1 (checked: 2.32.4 fails, 2.33.1 passes).
MIN_COMPOSE_VERSION="2.33.1"

install_docker() {
    if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
        log "Installing Docker CE + compose plugin (${OS_ID} ${OS_CODENAME})..."
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${OS_ID} ${OS_CODENAME} stable" \
            > /etc/apt/sources.list.d/docker.list
        apt-get update -qq
        apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    else
        log "Docker already installed: $(docker --version)"
    fi
    systemctl enable --now docker >/dev/null 2>&1 || true
    docker info >/dev/null 2>&1 || fail "docker daemon not reachable"
    require_compose_version
}

require_compose_version() {
    local have
    have=$(docker compose version --short 2>/dev/null | sed 's/^v//') \
        || fail "docker compose plugin not found"
    if [[ "$(printf '%s\n%s\n' "$MIN_COMPOSE_VERSION" "$have" | sort -V | head -1)" != "$MIN_COMPOSE_VERSION" ]]; then
        fail "docker compose ${have} is too old (need >= ${MIN_COMPOSE_VERSION})."
    fi
}

# env_get NAME FILE — print the value of NAME from a KEY=VALUE env file (last
# definition wins, surrounding quotes stripped). Prints nothing if unset.
# Used instead of `source`, which breaks on values such as `Name <addr>`.
env_get() {
    local line
    line=$(grep -E "^[[:space:]]*(export[[:space:]]+)?$1=" "$2" 2>/dev/null | tail -1) || true
    [[ -n "$line" ]] || return 0
    line="${line#*=}"
    line="${line%$'\r'}"
    if [[ "$line" == \"*\" ]]; then line="${line#\"}"; line="${line%\"}"
    elif [[ "$line" == \'*\' ]]; then line="${line#\'}"; line="${line%\'}"
    fi
    printf '%s' "$line"
}

# ── Git access ────────────────────────────────────────────────────────────────
# The VMs pull the private repo with a read-only GitHub deploy key owned by
# root. https:// URLs skip the key entirely.

ensure_deploy_key() {   # <key-path> <comment>
    local key="$1"
    install -d -m 700 "$(dirname "$key")"
    if [[ ! -f "$key" ]]; then
        log "Generating deploy key ${key}"
        ssh-keygen -t ed25519 -N '' -C "$2" -f "$key" -q
    fi
    chmod 600 "$key"
}

git_ssh_command() {     # <key-path>
    echo "ssh -i $1 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
}

require_repo_access() { # <repo-url> <branch> <key-path>
    local url="$1" branch="$2" key="$3"
    if GIT_SSH_COMMAND="$(git_ssh_command "$key")" \
            git ls-remote --exit-code --heads "$url" "$branch" >/dev/null 2>&1; then
        log "Repo access OK (${url} @ ${branch})"
        return 0
    fi
    cat >&2 <<EOF
[${TAG}] Cannot read ${url} (branch ${branch}) yet.

Add this public key to the GitHub repo as a READ-ONLY deploy key
(Settings → Deploy keys → Add deploy key, leave "Allow write access" off):

$(cat "${key}.pub")

Then re-run this script — it is idempotent.
EOF
    exit 3
}

# ── TLS ───────────────────────────────────────────────────────────────────────

install_cert_pair() {   # <src-cert> <src-key> <dst-cert> <dst-key>
    [[ -s "$1" && -s "$2" ]] || fail "Cert/key not found or empty: $1 / $2"
    openssl x509 -in "$1" -noout >/dev/null 2>&1 || fail "$1 is not a PEM certificate"
    install -d -m 750 "$(dirname "$3")"
    install -m 644 "$1" "$3"
    install -m 600 "$2" "$4"
    log "Installed cert: $(openssl x509 -in "$3" -noout -subject -enddate | tr '\n' ' ')"
}

# Only for checking the origin before real cert files are available. Cloudflare
# in Full (strict) mode rejects it, so the public hostname will return 526.
self_signed_cert() {    # <dst-cert> <dst-key> <hostname>
    install -d -m 750 "$(dirname "$1")"
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
        -subj "/CN=$3" -addext "subjectAltName=DNS:$3" \
        -keyout "$2" -out "$1" >/dev/null 2>&1
    chmod 644 "$1"; chmod 600 "$2"
    warn "SELF-SIGNED cert installed for $3 — origin testing only."
    warn "Cloudflare Full (strict) will refuse it; install the Cloudflare origin cert before the DNS flip."
}

# ── Origin lockdown ───────────────────────────────────────────────────────────
# On GCP the origin was restricted to Cloudflare by a VPC firewall rule. Here
# the same restriction is an nginx allow-list (http context), regenerated from
# Cloudflare's published ranges. Extra args are additional `allow` sources for
# local health checks.
write_cloudflare_allowlist() {  # <dest-file> [extra-allow-cidr...]
    local dest="$1"; shift
    local v4 v6 cidr n=0 tmp
    v4=$(curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4) \
        || fail "Could not fetch Cloudflare IPv4 ranges."
    v6=$(curl -fsS --max-time 20 https://www.cloudflare.com/ips-v6) \
        || fail "Could not fetch Cloudflare IPv6 ranges."
    tmp=$(mktemp)
    {
        echo "# Generated by deploy/cloudpe on $(date -Iseconds) — do not edit."
        echo "# Only Cloudflare (plus local health checks) may reach this origin."
        for cidr in "$@"; do echo "allow ${cidr};"; done
        for cidr in $v4 $v6; do
            [[ "$cidr" =~ ^[0-9a-fA-F:.]+/[0-9]{1,3}$ ]] || { rm -f "$tmp"; fail "Unexpected Cloudflare range: ${cidr}"; }
            echo "allow ${cidr};"
            n=$((n + 1))
        done
        echo "deny all;"
        (( n >= 10 )) || { rm -f "$tmp"; fail "Only ${n} Cloudflare ranges returned — refusing to write the allow-list."; }
    } > "$tmp"
    install -d -m 755 "$(dirname "$dest")"
    # Written in place: the app VM bind-mounts this single file into the nginx
    # container, and replacing the inode would leave the container on the old one.
    cat "$tmp" > "$dest"
    chmod 644 "$dest"
    rm -f "$tmp"
    log "Wrote Cloudflare allow-list (${n} ranges) → ${dest}"
}

# ── Containers ────────────────────────────────────────────────────────────────

wait_container_healthy() {  # <container> [tries=60] [sleep=2]
    local name="$1" tries="${2:-60}" pause="${3:-2}" status i
    for ((i = 1; i <= tries; i++)); do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")
        if [[ "$status" == "healthy" ]]; then
            log "${name} healthy after ${i} checks."
            return 0
        fi
        sleep "$pause"
    done
    docker logs --tail 40 "$name" >&2 2>&1 || true
    fail "${name} did not become healthy (last status: ${status})."
}

# Retry an HTTP GET until it returns 2xx. Prints the body on success.
wait_http_ok() {            # <label> <tries> <curl-args...>
    local label="$1" tries="$2" i; shift 2
    for ((i = 1; i <= tries; i++)); do
        if curl -fsS --max-time 10 "$@"; then
            echo
            log "OK  ${label}"
            return 0
        fi
        sleep 3
    done
    fail "${label} did not return 2xx after ${tries} attempts."
}

# ── Bundles ───────────────────────────────────────────────────────────────────

verify_bundle() {           # <bundle-dir>
    local dir="$1"
    [[ -f "${dir}/MANIFEST.sha256" ]] || fail "${dir}/MANIFEST.sha256 missing — not a capture bundle."
    log "Verifying bundle checksums..."
    ( cd "$dir" && sha256sum --quiet -c MANIFEST.sha256 ) || fail "Bundle checksum mismatch in ${dir}."
    log "Bundle checksums OK."
}
