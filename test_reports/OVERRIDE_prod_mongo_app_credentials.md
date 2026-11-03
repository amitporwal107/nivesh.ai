# OVERRIDE — prod Mongo app login out of git (3 Nov 2026)

REASON: Phase 1 is done and verified on prod; phase 2 (MC-8: drop the old `nivesh` user so the leaked password stops
working) must wait until the compose change is on `main` and deployed, because every prod deploy runs
`git reset --hard origin/main` and main still hard-codes the old login. Releasing to main is the owner's step.
`drop-legacy-mongo-user.sh` enforces this and refused today (exit 1) as designed.

Owner request: "Prod's MongoDB app password is hard-coded in a compose file in git … Please do it". Branch
`ops/prod-mongo-app-credentials` (from dev 5142f906).

| ID | Result | Evidence |
|----|--------|----------|
| MC-1 | PASS | `docker compose config` with the vars set renders `MONGO_URL: mongodb://nivesh_app:<64-hex>@mongo:27017/nivesh_prod?authSource=nivesh_prod` (dummy values) |
| MC-2 | PASS | password var missing → exit 1, "set NIVESH_MONGO_PASSWORD in /opt/nivesh/.env.prod" |
| MC-3 | PASS | old password literal under deploy/cloudpe-prod: 0 files |
| MC-4 | PASS | prod: `created user nivesh_app`, `roles equal to nivesh: true ["readWrite@nivesh_prod"]`, new login `ping=1 users=4` |
| MC-5 | PASS | prod: .env.prod gained NIVESH_MONGO_USER/PASSWORD, mode 600; backups `/opt/nivesh/dumps/*before-mongo-app-user-20261103-041202*` |
| MC-6 | PASS | prod: backend recreated, healthy; `backend MONGO_URL user: nivesh_app`; `authenticated as: ['nivesh_app@nivesh_prod']`, reads users 4; 0 auth-error log lines |
| MC-7 | PASS | prod: old login still `ping=1` (a deploy from current main keeps working) |
| MC-8 | NOT RUN | waits for main; guard script check-only on prod: "STOP: origin/main still hard-codes the old login" (exit 1) |

Not in scope / found: staging uses the same old password (`deploy/nivesh-staging/docker-compose.staging.yml`,
`deploy/nivesh-app/mongo-init.js`); it is a separate database and was not changed. mongo-init.js would recreate
`nivesh` with the old password only on a brand-new empty Mongo volume.
