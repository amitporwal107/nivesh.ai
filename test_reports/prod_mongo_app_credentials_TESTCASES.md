# Prod MongoDB app credentials out of git — test cases (authored before the change)

Owner, 3 Nov 2026: the prod Mongo app password is hard-coded in deploy/cloudpe-prod/app/docker-compose.yml (MONGO_URL)
— change it and move it into /opt/nivesh/.env.prod. Prod deploys `git reset --hard origin/main`, and main hard-codes the
old login, so: new user `nivesh_app` now (old `nivesh` kept until the compose change is on main), then drop `nivesh`.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| MC-1 | compose | `docker compose config` with NIVESH_MONGO_USER/PASSWORD in the env file | static | MONGO_URL = mongodb://<user>:<pw>@mongo:27017/nivesh_prod?authSource=nivesh_prod |
| MC-2 | compose | either variable missing | static | config fails with the "set … in /opt/nivesh/.env.prod" message (no silent default) |
| MC-3 | git | the old password literal in deploy/cloudpe-prod after the change | static | 0 occurrences there |
| MC-4 | prod Mongo | create `nivesh_app` with the same roles as `nivesh` | prod | roles equal; ping + read with the new login ok |
| MC-5 | prod env | NIVESH_MONGO_USER/PASSWORD added to .env.prod | prod | present, mode 600, other lines unchanged, backup taken |
| MC-6 | prod backend | recreated with the env-driven MONGO_URL | prod | healthy; connects as `nivesh_app`; reads Mongo; no auth errors in the log |
| MC-7 | fallback | the old `nivesh` login still works until phase 2 | prod | ping ok (so a deploy from current main keeps working) |
| MC-8 | phase 2 | after the compose change is on main and deployed: drop `nivesh` | prod | backend healthy as `nivesh_app`; the leaked password is rejected |
