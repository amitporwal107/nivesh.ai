# NIDP DaaS API — VM Service Operations

## Service location
- VM:        `nidp-stack-vm` (behind `data.niveshcopilot.com`)
- Port:      `8083` on loopback (nginx reverse-proxies `/daas/*` → `127.0.0.1:8083`)
- Process:   `uvicorn nidp.services.daas_api.app:app`
- systemd:   `/etc/systemd/system/nidp-daas-api.service`
- Logs:      `journalctl -u nidp-daas-api -f`

## Authentication
The service uses the standard `daas_api` API-key auth (`X-API-Key` or
`Authorization: Bearer …`). Two key paths are supported:

1. **DB-backed keys** in `nidp.daas_api_keys` (preferred for partners /
   external consumers).
2. **Internal bypass token** via env `NIDP_DAAS_INTERNAL_TOKEN`. This
   resolves to the internal placeholder key row (`key_id =
   00000000-0000-0000-0000-000000000000`, `plan = internal`, RPM 6000)
   that is seeded in the DB to satisfy the FK from `daas_daily_usage`.

The current internal token is stored in:
- VM: `/opt/nidp/nidp.env` as `NIDP_DAAS_INTERNAL_TOKEN=…`
- Pod backend: `/app/backend/.env` as `NIDP_DAAS_API_KEY=…`

Rotate by generating a new `nvd_internal_<random>` and updating both
locations + restarting `nidp-daas-api.service`.

## Access

Port 8083 is **loopback-only** — nginx terminates TLS and proxies through.
All external callers must use the HTTPS domain:

```bash
curl -H "X-API-Key: $NIDP_DAAS_API_KEY" \
  https://data.niveshcopilot.com/daas/v1/intelligence/snapshots/market
```

For direct debugging on the VM (bypassing nginx):

```bash
# SSH into the VM first, then:
curl -H "X-API-Key: $NIDP_DAAS_API_KEY" http://127.0.0.1:8083/v1/catalog
```

## Endpoints exposed (35 datasets in `/v1/catalog`)
Phase 2 intelligence routes:
- `GET /v1/intelligence/reference/securities`
- `GET /v1/intelligence/dq/scores`
- `GET /v1/intelligence/features/stocks/{symbol}`
- `GET /v1/intelligence/graph/entity-links`
- `GET /v1/intelligence/graph/correlations`
- `GET /v1/intelligence/graph/correlations/{security_id}/top`
- `GET /v1/intelligence/events`
- `GET /v1/intelligence/events/search`
- `GET /v1/intelligence/events/{event_id}`
- `GET /v1/intelligence/snapshots/market`
- `GET /v1/intelligence/snapshots/market/recent`
- `GET /v1/intelligence/portfolio/{external_user_id}/snapshot`
- `GET /v1/intelligence/portfolio/{external_user_id}/holdings`

(Plus all pre-existing `/v1/{prices,corporate-actions,flows,macro,…}`
routes from the rest of `daas_api`.)

## Service lifecycle

| Action  | Command |
|---------|---------|
| Start   | `sudo systemctl start nidp-daas-api` |
| Stop    | `sudo systemctl stop nidp-daas-api` |
| Restart | `sudo systemctl restart nidp-daas-api` |
| Status  | `sudo systemctl status nidp-daas-api --no-pager` |
| Logs    | `sudo journalctl -u nidp-daas-api -f` |
| Update  | scp the changed code into `/opt/nidp/repo/backend/nidp/...`, then restart |

The unit file is checked into the repo at
`/app/backend/nidp/deploy/vm/nidp-daas-api.service` and gets re-deployed
together with the rest of `nidp/deploy/vm/*` content.
