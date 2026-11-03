#!/usr/bin/env bash
# Give production its own data-encryption keys (owner, 2 Nov 2026: "prod needs to have different encryption
# key than staging").
#
# Prod was built from staging and kept staging's PII_ENCRYPTION_KEY and PI_PAN_ENCRYPTION_KEY so the cloned
# rows stayed readable (README.md). This script makes two new keys, re-encrypts every value written under the
# old ones, swaps the keys in /opt/nivesh/.env.prod and recreates the backend.
#
#   bash rotate-data-keys.sh            # DRY RUN (default): counts only; nothing changes, no downtime
#   bash rotate-data-keys.sh --apply    # rotate; the backend is stopped for about a minute
#
# Run on the prod VM as root, with backend/scripts/rotate_data_keys.py at $ROTATE_PY
# (default /root/key-rotation/rotate_data_keys.py). Keys never reach argv, output or a log: only 8-character
# SHA-256 fingerprints are printed. Values are passed by environment-variable NAME (docker -e NAME).
#
# The new keys are written to /root/nivesh-keys/ (mode 600) BEFORE any data changes; copy them into the
# owner's password manager. If a run stops halfway, a rerun reuses those pending keys, so rows already moved
# stay readable. The OLD keys are not deleted: staging still uses them, and backups taken before the
# rotation (/opt/nivesh/dumps, /opt/nidp/dumps) need them for their encrypted fields.
#
# Apply order: pending keys -> backups (.env.prod, Mongo collections, PAN table) -> Postgres PAN column in ONE
# transaction (a row the old key cannot open rolls everything back; the backend is not yet stopped) -> stop
# backend -> Mongo fields (compare-and-set, idempotent) -> verify -> swap keys in .env.prod -> recreate
# backend -> check the running backend has the new keys and reads every rotated value.
set -euo pipefail
umask 077

MODE=dry-run
case "${1:-}" in
  "" ) ;;
  --apply ) MODE=apply ;;
  * ) echo "usage: $0 [--apply]" >&2; exit 64 ;;
esac

# Prod values; each can be overridden from the environment so the script can be rehearsed in a sandbox.
ENV_FILE=${ENV_FILE:-/opt/nivesh/.env.prod}
COMPOSE_FILE=${COMPOSE_FILE:-/opt/nivesh/repo/deploy/cloudpe-prod/app/docker-compose.yml}
ROTATE_PY=${ROTATE_PY:-/root/key-rotation/rotate_data_keys.py}
KEY_DIR=${KEY_DIR:-/root/nivesh-keys}
DUMP_ROOT=${DUMP_ROOT:-/opt/nivesh/dumps}
SERVICE=${SERVICE:-app-backend}
BACKEND=${BACKEND:-nivesh-backend}
POSTGRES=${POSTGRES:-nivesh-postgres}
MONGO=${MONGO:-nivesh-mongo}
MONGO_DB=${MONGO_DB:-nivesh_prod}
PENDING=$KEY_DIR/pending-data-keys.env
DONE_MARK=$KEY_DIR/data-keys-rotated
TS=$(date +%Y%m%d-%H%M%S)
DUMP_DIR=$DUMP_ROOT/key-rotation-$TS

compose() { docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"; }
fp() { printf %s "$1" | sha256sum | cut -c1-8; }
env_value() { python3 - "$ENV_FILE" "$1" <<'PY'
import sys
path, name = sys.argv[1], sys.argv[2]
val = ""
for line in open(path):
    if line.startswith(name + "="):
        val = line.rstrip("\n").split("=", 1)[1].strip().strip('"').strip("'")
print(val, end="")
PY
}
say() { printf '[rotate-data-keys] %s\n' "$*"; }
die() { printf '[rotate-data-keys] ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root"
[ -f "$ENV_FILE" ] && [ -f "$COMPOSE_FILE" ] && [ -f "$ROTATE_PY" ] || die "missing $ENV_FILE, $COMPOSE_FILE or $ROTATE_PY"
if [ "$MODE" = apply ] && [ -f "$DONE_MARK" ]; then
  die "keys were already rotated ($(cat "$DONE_MARK")). Delete $DONE_MARK only if you mean to rotate again."
fi

OLD_PII_KEY=$(env_value PII_ENCRYPTION_KEY)
OLD_PI_KEY=$(env_value PI_PAN_ENCRYPTION_KEY)
[ -n "$OLD_PII_KEY" ] || die "PII_ENCRYPTION_KEY is not set in $ENV_FILE"
[ -n "$OLD_PI_KEY" ] || die "PI_PAN_ENCRYPTION_KEY is not set in $ENV_FILE"
say "mode=$MODE  current PII key fp=$(fp "$OLD_PII_KEY")  current PI PAN key fp=$(fp "$OLD_PI_KEY")"

# New keys: reuse a pending pair from an interrupted run, else make one (saved before any data changes).
mkdir -p "$KEY_DIR"; chmod 700 "$KEY_DIR"
if [ "$MODE" = apply ]; then
  if [ -f "$PENDING" ]; then
    say "reusing pending keys from an interrupted run ($PENDING)"
  else
    { printf 'PII_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32)"
      printf 'PI_PAN_ENCRYPTION_KEY=%s\n' "$(openssl rand -base64 32)"
      printf '# made %s on %s; previous fingerprints PII=%s PI=%s\n' "$TS" "$(hostname)" "$(fp "$OLD_PII_KEY")" "$(fp "$OLD_PI_KEY")"
    } > "$PENDING"
    chmod 600 "$PENDING"
  fi
  NEW_PII_KEY=$(ENV_FILE=$PENDING; env_value PII_ENCRYPTION_KEY)
  NEW_PI_KEY=$(ENV_FILE=$PENDING; env_value PI_PAN_ENCRYPTION_KEY)
else
  NEW_PII_KEY=$(openssl rand -base64 32)   # throwaway: the dry run only classifies
  NEW_PI_KEY=$(openssl rand -base64 32)
fi
export OLD_PII_KEY NEW_PII_KEY OLD_PI_KEY NEW_PI_KEY
[ "$NEW_PII_KEY" != "$OLD_PII_KEY" ] && [ "$NEW_PI_KEY" != "$OLD_PI_KEY" ] || die "new key equals old key"
say "new PII key fp=$(fp "$NEW_PII_KEY")  new PI PAN key fp=$(fp "$NEW_PI_KEY")$( [ "$MODE" = apply ] || echo '  (throwaway, dry run)')"

# The Mongo pass runs in a one-off container of the backend image: same network, env_file and Mongo URL.
mongo_pass() {  # $1 = --apply | --verify | (empty for dry run)
  compose run --rm --no-deps -T -e OLD_PII_KEY -e NEW_PII_KEY "$SERVICE" python - ${1:-} < "$ROTATE_PY"
}

# Postgres PAN column (portfolio_ingestion.users.pan_enc, pgcrypto). Call only when the table exists.
# The SQL carries no key: psql reads both from the environment with \getenv.
pan_sql() {  # $1 = count | apply | verify
  cat <<'SQL'
\getenv old OLD_PI_KEY
\getenv new NEW_PI_KEY
SELECT 'pan table: rows with pan_enc=' || count(*) FROM portfolio_ingestion.users WHERE pan_enc IS NOT NULL;
SQL
  case "$1" in
    apply) cat <<'SQL'
BEGIN;
UPDATE portfolio_ingestion.users
   SET pan_enc = public.pgp_sym_encrypt(public.pgp_sym_decrypt(pan_enc, :'old'), :'new')
 WHERE pan_enc IS NOT NULL;
COMMIT;
SELECT 'pan table: re-encrypted';
SQL
    ;;
    verify) cat <<'SQL'
SELECT 'pan table: rows opening with the new key=' || count(public.pgp_sym_decrypt(pan_enc, :'new'))
  FROM portfolio_ingestion.users WHERE pan_enc IS NOT NULL;
SQL
    ;;
  esac
}
pan_pass() {
  pan_sql "$1" | docker exec -i -e OLD_PI_KEY -e NEW_PI_KEY "$POSTGRES" \
    sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
pan_table_exists() {
  echo "SELECT to_regclass('portfolio_ingestion.users') IS NOT NULL;" | docker exec -i "$POSTGRES" \
    sh -c 'psql -X -q -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}
PAN_TABLE=$(pan_table_exists)
[ "$PAN_TABLE" = t ] || say "pan table: absent (nothing to re-encrypt in Postgres)"

if [ "$MODE" = dry-run ]; then
  [ "$PAN_TABLE" = t ] && pan_pass count
  mongo_pass ""
  say "dry run done: nothing changed. Rerun with --apply to rotate."
  exit 0
fi

# ── apply ─────────────────────────────────────────────────────────────────────
mkdir -p "$DUMP_DIR"; chmod 700 "$DUMP_DIR"
cp -p "$ENV_FILE" "$DUMP_DIR/env.prod.before"
for c in users broker_accounts kite_platform_token user_profiles gmail_tokens; do
  docker exec "$MONGO" sh -c 'mongodump --quiet --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --db '"$MONGO_DB"' --collection '"$c"' --archive --gzip' > "$DUMP_DIR/mongo-$c.archive.gz"
done
if [ "$PAN_TABLE" = t ]; then
  docker exec "$POSTGRES" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t portfolio_ingestion.users' | gzip > "$DUMP_DIR/pg-portfolio_ingestion-users.sql.gz"
fi
say "backups in $DUMP_DIR (encrypted fields in them need the OLD keys)"

# Postgres first: one transaction, and the backend is still up. A failure here changes nothing.
if [ "$PAN_TABLE" = t ]; then
  pan_pass apply || die "PAN column re-encryption failed and was rolled back; nothing changed. Backend untouched."
fi

say "stopping $BACKEND"
compose stop "$SERVICE"
STAGE="the backend is STOPPED and .env.prod still holds the OLD keys"
trap 'say "FAILED: $STAGE. Rerun: bash $0 --apply (pending keys are reused; rows already moved are skipped). Backups: $DUMP_DIR"' ERR

mongo_pass --apply
mongo_pass --verify
if [ "$PAN_TABLE" = t ]; then pan_pass verify; fi

# Swap the keys in .env.prod atomically (values from the environment, never argv).
python3 - "$ENV_FILE" <<'PY'
import os, sys, tempfile
path = sys.argv[1]
new = {"PII_ENCRYPTION_KEY": os.environ["NEW_PII_KEY"], "PI_PAN_ENCRYPTION_KEY": os.environ["NEW_PI_KEY"]}
seen, out = set(), []
for line in open(path):
    name = line.split("=", 1)[0]
    if name in new and "=" in line:
        out.append(f"{name}={new[name]}\n"); seen.add(name)
    else:
        out.append(line)
for name in new.keys() - seen:
    out.append(f"{name}={new[name]}\n")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as f:
    f.writelines(out)
st = os.stat(path)
os.chmod(tmp, 0o600)
os.chown(tmp, st.st_uid, st.st_gid)
os.replace(tmp, path)
PY
say "keys swapped in $ENV_FILE"
STAGE="data and .env.prod are on the NEW keys but the backend is not up yet; start it with: docker compose --env-file $ENV_FILE -f $COMPOSE_FILE up -d --no-deps --force-recreate app-backend"

say "recreating $BACKEND with the new keys"
compose up -d --no-deps --force-recreate "$SERVICE"
for i in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$BACKEND" 2>/dev/null)" = healthy ] && break
  sleep 5
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$BACKEND")" = healthy ] || die "backend did not become healthy — $STAGE"
trap - ERR

RUN_PII=$(docker exec "$BACKEND" sh -c 'printf %s "$PII_ENCRYPTION_KEY"' | sha256sum | cut -c1-8)
RUN_PI=$(docker exec "$BACKEND" sh -c 'printf %s "$PI_PAN_ENCRYPTION_KEY"' | sha256sum | cut -c1-8)
say "running backend: PII fp=$RUN_PII (want $(fp "$NEW_PII_KEY"))  PI PAN fp=$RUN_PI (want $(fp "$NEW_PI_KEY"))"
[ "$RUN_PII" = "$(fp "$NEW_PII_KEY")" ] && [ "$RUN_PI" = "$(fp "$NEW_PI_KEY")" ] || die "the running backend does not carry the new keys"

# The app's own code must now open every rotated value.
docker exec -i "$BACKEND" sh -c 'cd /app/backend && python -' <<'PY'
import json, os, sys
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient
from services import pii_security
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
targets = [("users","pan_encrypted",0),("broker_accounts","api_key_encrypted",0),("broker_accounts","extras_encrypted",0),
           ("kite_platform_token","token_enc",0),("user_profiles","pan_encrypted",0),("user_profiles","cas_pdf_password_encrypted",0),
           ("gmail_tokens","pan_encrypted",0),("gmail_tokens","cas_pdf_password_encrypted",0),
           ("gmail_tokens","access_token",1),("gmail_tokens","refresh_token",1)]
out = {}
for coll, field, sealed in targets:
    ok = bad = 0
    for d in db[coll].find({field: {"$type": "string", "$ne": ""}}, {field: 1}):
        v = d[field]
        if sealed and not v.startswith("enc:v1:"):
            continue
        pt = pii_security.unseal_field(v) if sealed else pii_security.decrypt(v)
        ok, bad = (ok + 1, bad) if pt else (ok, bad + 1)
    out[f"{coll}.{field}"] = {"app_opens": ok, "app_cannot_open": bad}
print(json.dumps(out, sort_keys=True))
PY

mv "$PENDING" "$KEY_DIR/prod-data-keys-$TS.env"
printf '%s PII=%s PI=%s\n' "$TS" "$(fp "$NEW_PII_KEY")" "$(fp "$NEW_PI_KEY")" > "$DONE_MARK"
say "DONE. New keys: $KEY_DIR/prod-data-keys-$TS.env (600). Copy them to the password manager."
