# Prod data-key rotation — test cases (authored before the scripts)

Owner, 2 Nov 2026: "prod needs to have different encryption key than staging". Prod kept staging's
`PII_ENCRYPTION_KEY` and `PI_PAN_ENCRYPTION_KEY` when it was cloned (deploy/cloudpe-prod/README.md).
Deliverables: `backend/scripts/rotate_data_keys.py` (Mongo fields) and `deploy/cloudpe-prod/rotate-data-keys.sh`
(runbook: keys, backups, stop, Postgres PAN column, Mongo, verify, swap env, recreate, post-checks).

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| RK-1 | crypto | value sealed with OLD opens with OLD, re-encrypted value opens with NEW only | unit | round trip exact; NEW ciphertext ≠ OLD ciphertext |
| RK-2 | classify | raw field: OLD → rotate; NEW → already_new; garbage → undecryptable; empty/non-string → skipped | unit | as listed |
| RK-3 | classify | sealed field (`enc:v1:`): same, plus unmarked legacy plaintext → plaintext (left as is) | unit | as listed |
| RK-4 | keys | missing / non-base64 / wrong length / OLD == NEW | unit | exit status 2, no DB access, key never in output |
| RK-5 | Mongo (real mongo:7) | dry run on every target field | data | counts per field; nothing written (snapshot equal) |
| RK-6 | Mongo | `--apply` | data | every OLD value now opens with NEW and not with OLD; plaintext / undecryptable / NEW values untouched |
| RK-7 | Mongo | `--verify` after apply; second `--apply` | data | verify exit 0 with 0 left under OLD; second apply rotates 0 |
| RK-8 | Mongo | value changed by someone else between read and write | data | compare-and-set: counted `changed_concurrently`, the newer value kept |
| RK-9 | Mongo | app-level read after rotation: services.pii_security with PII_ENCRYPTION_KEY=NEW decrypts every rotated value | data | all decrypt to the original plaintexts |
| RK-10 | Postgres (real postgres:16) | PAN column: dry run counts; apply re-encrypts in ONE transaction | data | pgp_sym_decrypt(NEW) = original for every row; OLD no longer opens |
| RK-11 | Postgres | a row the OLD key cannot open | data | whole UPDATE rolls back, nothing changed, runbook stops BEFORE Mongo and before the backend is stopped for long |
| RK-12 | runbook | shell syntax + dry-run path on a mock VM layout | static/e2e | `bash -n` ok; keys never echoed; pending keys reused on a rerun; refuses a second --apply |
| RK-13 | prod (owner-approved) | dry run, then apply, then post-checks on the real prod VM | prod | new fingerprints ≠ staging's; backend healthy; app reads every rotated value; 0 left under OLD |
