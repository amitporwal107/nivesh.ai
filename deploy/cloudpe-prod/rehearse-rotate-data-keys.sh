#!/usr/bin/env bash
# Sandbox rehearsal of deploy/cloudpe-prod/rotate-data-keys.sh (RK-5..RK-12). Run as root. Throwaway
# containers rk-*, network rk-net, files under $SB. Prints PASS/FAIL lines; never prints a key.
set -uo pipefail
WT=/home/deploy/nivesh-wt-keyrotate
SB=/tmp/claude-1002/-home-deploy-nivesh-ai/bbf217bc-46b6-43f8-abf6-e8931f8e80e5/scratchpad/rksb
RUNBOOK=$WT/deploy/cloudpe-prod/rotate-data-keys.sh
mkdir -p "$SB"; chmod 700 "$SB"
PASS=0; FAIL=0
check() { if eval "$2"; then echo "PASS $1"; PASS=$((PASS+1)); else echo "FAIL $1"; FAIL=$((FAIL+1)); fi; }
fp() { printf %s "$1" | sha256sum | cut -c1-8; }

OLD_PII=$(openssl rand -base64 32); OLD_PI=$(openssl rand -base64 32); export OLD_PII OLD_PI
MPW=rk-mongo-pw-$(openssl rand -hex 6)
printf 'PII_ENCRYPTION_KEY=%s\nPI_PAN_ENCRYPTION_KEY=%s\nOTHER_SETTING=keep-me\n' "$OLD_PII" "$OLD_PI" > "$SB/env.prod"; chmod 600 "$SB/env.prod"
cat > "$SB/compose.yml" <<YML
services:
  app-backend:
    image: nivesh/backend:staging
    container_name: rk-backend
    env_file: $SB/env.prod
    environment:
      MONGO_URL: mongodb://rkadmin:$MPW@rk-mongo:27017/?authSource=admin
      DB_NAME: rk_prod
      APP_ENV: production
      OPENAI_API_KEY: unit-test-placeholder
      PI_PAN_ENCRYPTION_KEY: \${PI_PAN_ENCRYPTION_KEY:?missing}
    command: ["sleep", "infinity"]
    volumes: ["$WT/backend:/app/backend:ro"]
    healthcheck: {test: ["CMD", "true"], interval: 2s, retries: 3}
    networks: [rk-net]
networks:
  rk-net: {external: true}
YML

docker network create rk-net >/dev/null
docker run -d --name rk-mongo --network rk-net -e MONGO_INITDB_ROOT_USERNAME=rkadmin -e MONGO_INITDB_ROOT_PASSWORD="$MPW" mongo:7 >/dev/null
docker run -d --name rk-postgres --network rk-net -e POSTGRES_USER=rk -e POSTGRES_PASSWORD=rkpg -e POSTGRES_DB=rkpi postgres:16-alpine >/dev/null
for i in $(seq 1 40); do docker exec rk-postgres pg_isready -U rk -d rkpi >/dev/null 2>&1 && docker exec rk-mongo mongosh --quiet -u rkadmin -p "$MPW" --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 2; done
docker compose --env-file "$SB/env.prod" -f "$SB/compose.yml" up -d >/dev/null 2>&1

# Seed Mongo the way the app writes: services.pii_security under the OLD key (from the env file).
docker exec -i rk-backend sh -c 'cd /app/backend && python -' <<'PY'
import os, sys, base64
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient
from services import pii_security as p
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
other = os.urandom(32); n = os.urandom(12)
foreign = base64.b64encode(n + AESGCM(other).encrypt(n, b"foreign", None)).decode()
for c in ("users","broker_accounts","kite_platform_token","user_profiles","gmail_tokens"): db[c].delete_many({})
db.users.insert_many([{"user_id":"u1","pan_encrypted":p.encrypt("ABCDE1234F")},{"user_id":"u2","pan_encrypted":"garbage-not-cipher"},{"user_id":"u3"}])
db.broker_accounts.insert_many([{"account_id":"a1","api_key_encrypted":p.encrypt("tok-1"),"extras_encrypted":p.encrypt('{"x": 1}')},
                                {"account_id":"a2","api_key_encrypted":foreign}])
db.kite_platform_token.insert_one({"_id":"platform","token_enc":p.encrypt("kite-tok")})
db.user_profiles.insert_one({"user_id":"u1","pan_encrypted":p.encrypt("PANAA1111A"),"cas_pdf_password_encrypted":p.encrypt("Pw-1")})
db.gmail_tokens.insert_many([{"user_id":"u1","access_token":p.seal_field("ya29.a"),"refresh_token":p.seal_field("1//r"),"pan_encrypted":p.encrypt("PANBB2222B")},
                             {"user_id":"u2","access_token":"legacy-plain","refresh_token":p.seal_field("1//r2")}])
print("seeded mongo")
PY
# Seed Postgres: pgcrypto PAN column under the OLD PI key (+ one row under a foreign key for RK-11).
docker exec -i -e OLD_PI rk-postgres psql -X -q -v ON_ERROR_STOP=1 -U rk -d rkpi <<'SQL'
\getenv old OLD_PI
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA portfolio_ingestion;
CREATE TABLE portfolio_ingestion.users (id serial primary key, external_id text, pan_hash text, pan_enc bytea);
INSERT INTO portfolio_ingestion.users (external_id, pan_enc) VALUES
  ('x1', public.pgp_sym_encrypt('PANCC3333C', :'old')), ('x2', public.pgp_sym_encrypt('PANDD4444D', :'old')),
  ('x3', NULL), ('bad', public.pgp_sym_encrypt('PANEE5555E', 'some-other-key'));
SQL

RUN() { env ENV_FILE="$SB/env.prod" COMPOSE_FILE="$SB/compose.yml" ROTATE_PY="$WT/backend/scripts/rotate_data_keys.py" \
  KEY_DIR="$SB/keys" DUMP_ROOT="$SB/dumps" SERVICE=app-backend BACKEND=rk-backend POSTGRES=rk-postgres MONGO=rk-mongo MONGO_DB=rk_prod \
  bash "$RUNBOOK" "$@"; }
mongo_snapshot() { docker exec rk-mongo mongosh --quiet -u rkadmin -p "$MPW" --authenticationDatabase admin rk_prod --eval \
  'JSON.stringify(["users","broker_accounts","kite_platform_token","user_profiles","gmail_tokens"].map(c=>db[c].find({},{_id:0}).sort({user_id:1,account_id:1}).toArray()))' | sha256sum | cut -c1-16; }
pg_open() { docker exec -i -e K="$1" rk-postgres psql -X -q -At -U rk -d rkpi <<'SQL' 2>/dev/null
\getenv k K
SELECT string_agg(public.pgp_sym_decrypt(pan_enc, :'k'), ',' ORDER BY external_id) FROM portfolio_ingestion.users WHERE external_id IN ('x1','x2');
SQL
}

# ── RK-11: a PAN row the old key cannot open → whole Postgres update rolls back; nothing else touched ──
S0=$(mongo_snapshot); E0=$(sha256sum < "$SB/env.prod")
OUT11=$(RUN --apply 2>&1); RC11=$?
check "RK-11 apply with an unopenable PAN row exits non-zero" '[ $RC11 -ne 0 ]'
check "RK-11 message says rolled back, backend untouched" 'grep -q "rolled back; nothing changed. Backend untouched" <<<"$OUT11"'
check "RK-11 PAN rows still open with the OLD key" '[ "$(pg_open "$OLD_PI")" = "PANCC3333C,PANDD4444D" ]'
check "RK-11 Mongo unchanged" '[ "$(mongo_snapshot)" = "$S0" ]'
check "RK-11 .env.prod unchanged" '[ "$(sha256sum < "$SB/env.prod")" = "$E0" ]'
check "RK-11 backend still running" '[ "$(docker inspect -f "{{.State.Running}}" rk-backend)" = true ]'
check "RK-12 pending keys saved (600) before any data change" '[ "$(stat -c %a "$SB/keys/pending-data-keys.env")" = 600 ]'
PEND_FP=$(fp "$(grep ^PII_ENCRYPTION_KEY= "$SB/keys/pending-data-keys.env" | cut -d= -f2-)")
docker exec rk-postgres psql -X -q -U rk -d rkpi -c "DELETE FROM portfolio_ingestion.users WHERE external_id='bad'" >/dev/null

# ── RK-5: dry run changes nothing ──
OUT5=$(RUN 2>&1); RC5=$?
check "RK-5 dry run exit 0" '[ $RC5 -eq 0 ]'
check "RK-5 dry run counts 2 PAN rows" 'grep -q "pan table: rows with pan_enc=2" <<<"$OUT5"'
check "RK-5 dry run classifies Mongo fields" 'grep -q "\"users.pan_encrypted\": {\"to_rotate\": 1, \"total\": 2, \"undecryptable\": 1}" <<<"$OUT5"'
check "RK-5 dry run wrote nothing (Mongo, PG, env)" '[ "$(mongo_snapshot)" = "$S0" ] && [ "$(pg_open "$OLD_PI")" = "PANCC3333C,PANDD4444D" ] && [ "$(sha256sum < "$SB/env.prod")" = "$E0" ]'

# ── RK-6/7/9/10/12: apply (reuses the pending keys from the failed run) ──
OUT=$(RUN --apply 2>&1); RC=$?
echo "----- runbook output (apply) -----"; sed -E 's/^/  | /' <<<"$OUT" | cut -c1-220; echo "----------------------------------"
check "RK-6 apply exit 0" '[ $RC -eq 0 ]'
check "RK-12 the rerun reused the pending keys" 'grep -q "reusing pending keys" <<<"$OUT"'
KF=$(ls "$SB"/keys/prod-data-keys-*.env 2>/dev/null | head -1)
NEW_PII=$(grep ^PII_ENCRYPTION_KEY= "$KF" | cut -d= -f2-); NEW_PI=$(grep ^PI_PAN_ENCRYPTION_KEY= "$KF" | cut -d= -f2-); export NEW_PII NEW_PI
check "RK-12 final key = pending key from the interrupted run" '[ "$(fp "$NEW_PII")" = "$PEND_FP" ]'
check "custody file 600, pending removed, done mark written" '[ "$(stat -c %a "$KF")" = 600 ] && [ ! -f "$SB/keys/pending-data-keys.env" ] && [ -f "$SB/keys/data-keys-rotated" ]'
check "env.prod holds the NEW keys, other lines kept, mode 600" 'grep -qx "PII_ENCRYPTION_KEY=$NEW_PII" "$SB/env.prod" && grep -qx "PI_PAN_ENCRYPTION_KEY=$NEW_PI" "$SB/env.prod" && grep -qx "OTHER_SETTING=keep-me" "$SB/env.prod" && [ "$(stat -c %a "$SB/env.prod")" = 600 ]'
check "running backend carries the NEW PII key" '[ "$(docker exec rk-backend sh -c "printf %s \"\$PII_ENCRYPTION_KEY\"" | sha256sum | cut -c1-8)" = "$(fp "$NEW_PII")" ]'
check "RK-10 PAN rows open with the NEW PI key" '[ "$(pg_open "$NEW_PI")" = "PANCC3333C,PANDD4444D" ]'
check "RK-10 PAN rows no longer open with the OLD PI key" '[ -z "$(pg_open "$OLD_PI")" ]'
# RK-6/9: the app (new key) opens every rotated value; untouched values stay as they were; OLD opens nothing.
APP=$(docker exec -i -e OLD_PII rk-backend sh -c 'cd /app/backend && python -' <<'PY'
import os, sys, base64, json
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient
from services import pii_security as p
from scripts import rotate_data_keys as rk
db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
old = base64.b64decode(os.environ["OLD_PII"])
u = {d["user_id"]: d for d in db.users.find()}
a = {d["account_id"]: d for d in db.broker_accounts.find()}
g = {d["user_id"]: d for d in db.gmail_tokens.find()}
pr = db.user_profiles.find_one({"user_id": "u1"}); k = db.kite_platform_token.find_one({"_id": "platform"})
checks = {
  "app opens users.pan_encrypted": p.decrypt(u["u1"]["pan_encrypted"]) == "ABCDE1234F",
  "undecryptable value left as is": u["u2"]["pan_encrypted"] == "garbage-not-cipher",
  "app opens broker api_key + extras": p.decrypt(a["a1"]["api_key_encrypted"]) == "tok-1" and p.decrypt(a["a1"]["extras_encrypted"]) == '{"x": 1}',
  "foreign-key value left as is (still unopenable)": p.decrypt(a["a2"]["api_key_encrypted"]) is None,
  "app opens kite platform token": p.decrypt(k["token_enc"]) == "kite-tok",
  "app opens profile PAN + statement password": p.decrypt(pr["pan_encrypted"]) == "PANAA1111A" and p.decrypt(pr["cas_pdf_password_encrypted"]) == "Pw-1",
  "app unseals gmail tokens": p.unseal_field(g["u1"]["access_token"]) == "ya29.a" and p.unseal_field(g["u1"]["refresh_token"]) == "1//r" and p.unseal_field(g["u2"]["refresh_token"]) == "1//r2",
  "sealed field stays sealed": g["u1"]["access_token"].startswith("enc:v1:"),
  "legacy plaintext gmail token untouched": g["u2"]["access_token"] == "legacy-plain",
  "app opens gmail PAN mirror": p.decrypt(g["u1"]["pan_encrypted"]) == "PANBB2222B",
  "OLD key opens none of the rotated values": all(rk.open_with(old, v) is None for v in [u["u1"]["pan_encrypted"], a["a1"]["api_key_encrypted"], k["token_enc"], pr["pan_encrypted"], g["u1"]["access_token"][7:]]),
}
print(json.dumps(checks))
PY
)
while IFS=$'\t' read -r name ok; do
  check "RK-6/9 $name" '[ "$ok" = True ]'
done < <(python3 -c 'import json,sys; [print(f"{k}\t{v}") for k, v in json.loads(sys.argv[1]).items()]' "$APP")
check "RK-7 runbook verify reported nothing left under OLD" 'grep -q "\"mode\": \"verify\"" <<<"$OUT" && ! grep -q "to_rotate\": [1-9]" <<<"$(grep "\"mode\": \"verify\"" <<<"$OUT")"'
check "backups written (env, 5 Mongo archives, PG table)" '[ -f "$(ls -d "$SB"/dumps/key-rotation-*/ | tail -1)env.prod.before" ] && [ "$(ls "$SB"/dumps/key-rotation-*/mongo-*.archive.gz | wc -l)" -ge 10 ] && ls "$SB"/dumps/key-rotation-*/pg-portfolio_ingestion-users.sql.gz >/dev/null'
check "app-level read in the runbook: no field the app cannot open except the 2 planted" 'grep -q "\"app_cannot_open\"" <<<"$OUT" && [ "$(grep -o "\"app_cannot_open\": [0-9]*" <<<"$OUT" | awk "{s+=\$2} END{print s}")" = 2 ]'
OUT2=$(RUN --apply 2>&1); RC2=$?
check "RK-12 a second --apply is refused" '[ $RC2 -ne 0 ] && grep -q "already rotated" <<<"$OUT2"'
ALL="$OUT11$OUT5$OUT$OUT2"
check "no key material in any runbook output" '! grep -qF "$OLD_PII" <<<"$ALL" && ! grep -qF "$NEW_PII" <<<"$ALL" && ! grep -qF "$OLD_PI" <<<"$ALL" && ! grep -qF "$NEW_PI" <<<"$ALL"'

docker compose --env-file "$SB/env.prod" -f "$SB/compose.yml" down >/dev/null 2>&1
docker rm -f rk-mongo rk-postgres >/dev/null 2>&1; docker network rm rk-net >/dev/null 2>&1
echo "REHEARSAL: $PASS passed, $FAIL failed"
[ $FAIL -eq 0 ]
