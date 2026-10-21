# Kite intraday bars

Source of intraday OHLCV for the gap-down sleeve (G2–G5 entries, intraday exit matrix) and
for the `low` column that the daily bhavcopy panel lacks.

## Daily auth — the one manual step

Kite's `access_token` expires every morning (~06:00 IST) and renewing it requires an
interactive Zerodha login (credentials + 2FA). There is no unattended refresh.

```
# 1. print the login URL (safe: carries the api_key only, no secret)
python -c "import sys; sys.path.insert(0,'backend'); \
from nidp.services.kite_bars.client import login_url; print(login_url())"

# 2. open it, log in; you are redirected to <redirect>?request_token=XXXX&action=login
# 3. exchange it and SAVE THE TOKEN TO A FILE (never paste it into a shell argument —
#    argv is visible to other processes on this VM)
python - <<'PY'
import sys, pathlib; sys.path.insert(0,'backend')
from nidp.services.kite_bars.client import exchange_request_token
tok = exchange_request_token(input("request_token: ").strip())["access_token"]
p = pathlib.Path("/root/.kite-access-token"); p.write_text(tok); p.chmod(0o600)
print("saved; expires ~06:00 IST tomorrow")
PY
```

## Backfill

```
python -m nidp.services.kite_bars.collect \
  --symbols /path/to/symbols.txt --start 2024-01-01 --end 2026-09-18 \
  --interval minute --token-file /root/.kite-access-token
```

Chunking is automatic (Kite caps minute requests at 60 days). Pacing is 2.86 req/s against
a 3 req/s limit. Re-running is safe: bars upsert on `(instrument_token, interval, bar_ts)`.

## Auditability

Every attempted `(symbol, interval, window)` is recorded in `nidp.intraday_ingest_log` as
`OK` / `EMPTY` / `ERROR` with `run_id` and `source_version`. A missing bar is therefore always
attributable — never fetched, fetched-but-no-trades, or failed — which matters because a
silently short backfill would bias any model trained on it.

`source_version` on every bar row (`kite-connect-v3`) means a later vendor switch does not
contaminate an existing training set: select the source you trust.

## Secrets

Credentials resolve through `helpers.secrets` (GSM → env) under `BROKER_ZERODHA_API_KEY` and
`BROKER_ZERODHA_API_SECRET` — the same names `backend/services/brokers/zerodha.py` already
uses. No new secret path. Nothing in this package prints a key, secret or token.
