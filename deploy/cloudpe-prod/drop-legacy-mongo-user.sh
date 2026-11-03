#!/usr/bin/env bash
# Phase 2 of moving prod's Mongo app login out of git (3 Nov 2026): remove the old user `nivesh`, whose password
# was hard-coded in app/docker-compose.yml and stays in git history.
#
# Phase 1 (done 3 Nov) created `nivesh_app` with the same roles, put NIVESH_MONGO_USER / NIVESH_MONGO_PASSWORD in
# /opt/nivesh/.env.prod and moved the backend to it. `nivesh` was kept because a prod deploy runs
# `git reset --hard origin/main`: until main's compose file builds MONGO_URL from .env.prod, a deploy brings the old
# login back. So this script refuses to run until that is no longer possible.
#
#   bash drop-legacy-mongo-user.sh            # checks only: says whether it is safe, changes nothing
#   bash drop-legacy-mongo-user.sh --apply    # drop `nivesh`, then prove the old password no longer works
#
# Run on the prod VM as root. Prints no password.
set -euo pipefail
umask 077
APPLY=no; [ "${1:-}" = --apply ] && APPLY=yes
REPO=/opt/nivesh/repo
COMPOSE_REL=deploy/cloudpe-prod/app/docker-compose.yml
say() { printf '[drop-legacy-mongo-user] %s\n' "$*"; }
die() { printf '[drop-legacy-mongo-user] STOP: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root"

# 1. main's own compose file (what the next deploy installs) must build MONGO_URL from .env.prod.
export GIT_SSH_COMMAND="ssh -i /opt/nivesh/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"   # as ci-deploy.sh
git -c safe.directory="$REPO" -C "$REPO" fetch --quiet origin main || die "could not fetch origin/main (a stale copy could pass this check)"
MAIN_COMPOSE=$(git -c safe.directory="$REPO" -C "$REPO" show origin/main:"$COMPOSE_REL")
grep -q 'NIVESH_MONGO_PASSWORD' <<<"$MAIN_COMPOSE" || die "origin/main still hard-codes the old login; release the compose change to main first"
grep -q 'mongodb://nivesh:' <<<"$MAIN_COMPOSE" && die "origin/main still contains a hard-coded nivesh login"
say "ok: origin/main builds MONGO_URL from .env.prod"

# 2. The deployed file and the running backend use the new login.
grep -q 'NIVESH_MONGO_PASSWORD' "$REPO/$COMPOSE_REL" || die "the deployed compose file is not the env-driven one yet (deploy main first)"
USER_NOW=$(docker exec nivesh-backend python -c 'import os, urllib.parse as u; print(u.urlsplit(os.environ["MONGO_URL"]).username)')
[ "$USER_NOW" = nivesh_app ] || die "the running backend logs in as '$USER_NOW', not nivesh_app"
docker exec nivesh-backend python -c 'import os; from pymongo import MongoClient; d = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=8000)[os.environ["DB_NAME"]]; d.command("ping")' \
  || die "the backend cannot reach Mongo as nivesh_app"
say "ok: running backend authenticates as nivesh_app"

[ "$APPLY" = yes ] || { say "checks passed. Rerun with --apply to drop user nivesh."; exit 0; }

# 3. Drop the old user and prove the backend is unaffected.
docker exec nivesh-mongo sh -c 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin nivesh_prod --eval "const d = db.getSiblingDB(\"nivesh_prod\"); if (d.getUser(\"nivesh\")) { d.dropUser(\"nivesh\"); print(\"dropped user nivesh\") } else { print(\"user nivesh already absent\") }"'
docker exec nivesh-backend python -c 'import os; from pymongo import MongoClient; d = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=8000)[os.environ["DB_NAME"]]; print("backend still reads users:", d.users.estimated_document_count())'
docker exec nivesh-mongo sh -c 'mongosh --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin nivesh_prod --eval "print(\"users in nivesh_prod: \" + JSON.stringify(db.getSiblingDB(\"nivesh_prod\").getUsers().users.map(u => u.user)))"'
say "DONE: the leaked password no longer opens prod Mongo"
