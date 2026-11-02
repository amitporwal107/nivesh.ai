# OVERRIDE — prod data-key rotation (2 Nov 2026)

REASON: The tooling is built, unit-tested, rehearsed end to end and dry-run on prod, but the final step — running
`rotate-data-keys.sh --apply` on the prod VM (stops the backend ~1 min, re-encrypts 6 values, swaps keys in
/opt/nivesh/.env.prod) — was refused by the auto-mode classifier as [Production Deploy]. The owner runs it, or allows it.

Owner request: "prod needs to have different encryption key than staging". Branch `ops/prod-data-key-rotation`.

## Confirmed on the real systems (2 Nov, ~21:15 IST)
- Prod and staging share BOTH data keys (8-char SHA-256 fingerprints, keys never printed):
  PII_ENCRYPTION_KEY prod fbdaf164 = staging fbdaf164 · PI_PAN_ENCRYPTION_KEY prod 9aa029f1 = staging 9aa029f1.
- Prod dry run (`bash rotate-data-keys.sh`, nothing written): Postgres PAN table present, 0 encrypted rows;
  Mongo nivesh_prod to rotate: gmail_tokens.access_token 3, gmail_tokens.refresh_token 2 (+1 legacy PLAINTEXT, left as is),
  kite_platform_token.token_enc 1; users / broker_accounts / user_profiles / gmail PAN fields: 0.
- Files on prod /root/key-rotation/ match the branch (sha256 prefixes 9883c2600972, 44efccc5f2f5).

## Verified off prod
- `pytest tests/test_rotate_data_keys.py` (staging backend image): 10 passed (RK-1..RK-4, RK-8 compare-and-set,
  target coverage; compatibility with services.pii_security encrypt/seal_field both ways).
- Sandbox rehearsal `deploy/cloudpe-prod/rehearse-rotate-data-keys.sh` (real mongo:7 + postgres:16 + backend image
  running the real pii_security): **35 passed, 0 failed** — RK-11 rollback on an unopenable PAN row (nothing changed,
  backend untouched), RK-5 dry run writes nothing, RK-6/9/10 apply: app opens every rotated value with the new key and
  the old key opens none, plaintext/foreign values untouched, RK-7 verify clean, RK-12 pending keys reused after an
  interrupted run and a second --apply refused, backups written, no key material in any output.
  (First run: 33/2 — the 2 failures were a harness bug in my name-mangling loop, fixed; rerun 35/0.)

## Not done / needs the owner
- RK-13: `--apply` on prod, then confirm its own post-checks (running backend fingerprints = new, ≠ staging; healthy;
  `app_cannot_open` 0 for rotated fields).
- Copy /root/nivesh-keys/prod-data-keys-<ts>.env into the password manager from your own terminal (not via Claude).
