# Plan: encrypt PAN and statement passwords at rest (Nivesh)

Status: **plan only — nothing in it has been implemented.** Written 2026-10-14 from a read-only investigation of the code on `dev` (as of `004f4dfd`). No `.env` or token file was read, no database was queried, and the PDFs under `data/` were not opened, so every statement about what is deployed or stored in production is marked UNVERIFIED where it could not be seen in the code. Paths are relative to the repository root.

## Five-line summary

1. **In the clear today:** the investor's PAN (twice) and statement password on `user_profiles`, both mirrored on `gmail_tokens`; advisor-entered client PANs on `profiles`, shadow `users` and `client_cas_invites`; and `GET /api/user/profile` returns the PAN and password to the browser as stored.
2. **What the plan changes:** one encrypted record per user (AES-256-GCM, key id in every value, fail-closed), the duplicate copies deleted, masked PAN only in every response, and export, deletion and Gmail-disconnect made to cover these fields. AES-256-GCM already exists in the code; the gap is that onboarding never calls it and its key handling is weak.
3. **Size:** about 15 engineer-days in 9 pull requests for the retail scope, 4 to 5 calendar weeks including a staging run and one scheduled monthly import. About 12 more days if advisor client PANs and the legacy ingestion store are included. Rough.
4. **Owner must decide or provision:** where the key lives and who may read it, an offline escrow copy, scope (retail only or also advisor and legacy stores), whether the statement password is kept after import, what to do with old backups and the PDFs committed to git, and the UI wording.
5. **Main risk:** a missing or malformed key. Today that silently stores plaintext; after the change it blocks imports. The second risk is removing the plain fields before every reader is switched, which would stop the monthly Gmail import.

Size key used below: S = up to 1 day, M = 2 to 3 days, L = 4 to 6 days.

---

## 0. Corrections to the earlier investigation

| Earlier claim | What the code shows |
|---|---|
| `upload_cas_pdf` writes to both collections | It writes only `user_profiles` (`backend/routes/onboarding_gmail.py:669-689`). No `gmail_tokens` write. |
| `save_pan` / `save_cas_password` mirror to `gmail_tokens` | True, but with `upsert=False` (lines 143-147, 181-185). The mirror exists only if Gmail was connected first. After a disconnect and reconnect the mirror is gone, and the monthly sweep, which selects on `gmail_tokens.cas_password` (`backend/services/gmail_auto_import.py:177-188`), skips that user. |
| A helper exists "for the Gmail access token" | `pii_security` is already AES-256-GCM. It seals both access and refresh tokens (`backend/services/gmail_service.py:87-88`), but `seal_field` stores plaintext when the key is missing. |
| Statement password is used at upload, Gmail import and scheduled import | True. The scheduled import and the "Sync Gmail" button also send the PDF and the password to the hosted casparser.in API (`gmail_auto_import.py:131-133` → `backend/services/cas_api_client.py:333-341`). Onboarding and upload parse locally. |
| Export and deletion do not cover these fields consistently | Confirmed and wider: export omits `user_profiles` entirely; deletion removes only holdings, action plans and `users.pan_encrypted`; nothing reads `is_deleted`. |

New findings not in the earlier investigation:

- `GET /api/user/profile` and `POST /api/user/journey` return the whole `user_profiles` document, including `pan`, `cas_password`, `cas_pdf_password` (`backend/routes/user.py:15-36, 56-57`).
- Any admin can read the encryption key over HTTP: `GET /api/admin/secrets/{key}/reveal` falls back to the process environment for any name (`backend/routes/admin.py:430-492`). The audit call there passes `metadata=`, which `audit.record` does not accept, so the reveal is not recorded.
- 65 statement-sized PDFs (390 to 510 KB) are tracked in git under `data/cas_uploads/` (50) and `data/gmail_cas/user_*/` (15), added by "auto-commit" commits. UNVERIFIED whether they are real investor statements; I did not open them.
- Three more PAN stores exist: advisor client profiles, client invites, and the legacy `portfolio_ingestion` module (Postgres plus a second Mongo collection).

---

## 1. Inventory

### 1a. By store

| Store | Field | State today | Target |
|---|---|---|---|
| Mongo `user_profiles` | `pan` | plain | removed; encrypted in `user_secrets.pan_enc` |
| Mongo `user_profiles` | `cas_password` | plain copy of the PAN | removed, not replaced (derived from the PAN at use time) |
| Mongo `user_profiles` | `cas_pdf_password` | plain | removed; encrypted in `user_secrets.cas_pdf_password_enc` |
| Mongo `gmail_tokens` | `cas_password`, `cas_pdf_password` | plain copies | removed, not replaced; a boolean `unlock_ready` if a flag is wanted |
| Mongo `gmail_tokens` | `pan_saved_at`, `cas_password_saved_at` | timestamps | move to `user_secrets` |
| Mongo `users` | `pan_encrypted`, `pan_last4` | AES-256-GCM, no key id | migrated into `user_secrets`, then removed |
| Mongo `profiles` (advisor clients) | `pan`, `pan_norm` | plain, indexed | `pan_last4` + `pan_bidx` (HMAC); ciphertext in `user_secrets` under the shadow user id |
| Mongo `users` (shadow) | `pan`, `pan_norm` | plain, indexed | removed |
| Mongo `client_cas_invites` | `client_pan` | plain, written by a public no-login endpoint | stop storing; existing values moved or deleted |
| Postgres `portfolio_ingestion.users` | `pan_hash` | unkeyed SHA-256 | HMAC-SHA-256, or module retired |
| Postgres `portfolio_ingestion.users` | `pan_enc` | pgcrypto `pgp_sym_encrypt`, default cipher | AES-256, or module retired |
| Postgres `portfolio_ingestion.ingestion_jobs / snapshots / holdings / audit_log` | `pan_hash` | unkeyed SHA-256 join key | same as above |
| Mongo (PI database) `pi_raw_parsed_data` | `pan_hash`, `parsed_data.investor.pan` | hash plus plain PAN inside the archived payload | scrub `investor.pan`, or retire |
| Mongo `cas_parsed_responses` | `raw_payload` | no live writer found; old rows may hold investor PAN (UNVERIFIED) | scan, then scrub or delete |
| Disk `/app/data/cas_uploads` | stored client PDFs | legacy; writer `_save_cas_bytes` has no caller | delete after review |
| Main Postgres, Redis, NIDP/GCS export | none | not mirrored (checked) | no change |

### 1b. By file

| File | Lines | What happens |
|---|---|---|
| `backend/routes/onboarding_gmail.py` | 121-148 | `save_pan`: writes `pan` and `cas_password` to `user_profiles`, `cas_password` to `gmail_tokens` |
| same | 157-186 | `save_cas_password`: writes `cas_pdf_password` to both |
| same | 189-204 | `_resolve_cas_password`: custom password first, else PAN upper-cased |
| same | 232-240, then 335, 359, 381, 405, 450, 496, 509-512 | Gmail import: reads both documents, passes the plaintext to four local extractors, the Vision helper and a background task |
| same | 663-698 | `upload_cas_pdf`: stores the supplied secret on `user_profiles` only, also sets it on the in-memory profile dict (674-675, 683) |
| same | 701-845 (723, 737, 752, 768, 789, 838) | `import_cas_pdf_for_user`: shared with the advisor upload |
| same | 436, 608-615 | `error_detail` from parser exception text returned to the client |
| same | 871 | `pan_on_file` flag |
| `backend/services/gmail_auto_import.py` | 56-64 | reads the password, `gmail_tokens` first then profile; no upper-casing |
| same | 131-133 | sends PDF and password to the hosted parser |
| same | 177-188 | monthly sweep selects users on `gmail_tokens.cas_password` |
| `backend/services/cas_api_client.py` | 289-368 | hosted call `POST {base}/v4/smart/parse` with `data={"password": ...}`; logs and returns the third party's response body (349-351) |
| same | 897-960 | offline `casparser` path (local) |
| `backend/services/nsdl_cas_extractor.py`:408, `cdsl_cas_extractor.py`:112, `cams_kfin_cas_extractor.py`:291, `nsdl_cas_transactions.py`:150 | | `pdfplumber.open(..., password=)`, local |
| `backend/services/cas_summary_vision.py` | 70-99, 105-135 | decrypts locally, sends images of pages 2-3 to OpenAI. Password is not sent. UNVERIFIED whether those pages show the PAN |
| `backend/routes/gmail.py` | 148-156 | OAuth callback upserts tokens |
| same | 201 | `auto_import_ready` reads `gmail_tokens.cas_password` |
| same | 228-233 | disconnect deletes the `gmail_tokens` document only |
| `backend/routes/user.py` | 15-36, 56-57 | whole profile returned to the browser |
| `backend/routes/auth.py` | 203, 245, 354, 541 | whole `users` document returned: `pan_encrypted` ciphertext and `pan_last4`; when an advisor has a client open (`backend/deps.py:91-98`) the shadow user's plain `pan` and `pan_norm` |
| `backend/routes/compliance.py` | 93-157 | encrypted PAN store: get masked, put, delete. No frontend calls it |
| same | 161-193 | export: `users`, holdings, action plans, consents |
| same | 196-228 | deletion |
| `backend/routes/mfd.py` | 60, 70, 300-324, 340-358 | advisor adds or edits a client PAN; 409 responses echo the conflicting PAN |
| same | 209, 270-287, 331 | whole `profiles` documents returned, full PAN included |
| same | 435-446 | advisor upload unlocks with `profiles.pan` |
| `backend/services/mfd_workspace.py` | 156-201, 218-258, 261-275 | client PAN written to `profiles` and the shadow `users` row; profile delete leaves the shadow user's `user_profiles` row |
| `backend/services/identity_uniqueness.py` | 95-202, 206-227, 231-256, 259-270 | lookup by PAN on `pan_norm`; stamper; duplicate scan returns PAN values; indexes |
| `backend/routes/admin_users.py` | 162-180, 354-361, 525-590 | admin user detail returns whole `users` doc; reset keeps PAN and password; identity endpoints |
| `backend/routes/client_cas_invite.py` | 365, 387-431, 657 | public endpoint stores `client_pan` (comment: "encrypted in future; plaintext MVP"); full PAN returned to the advisor. Line 548 also writes a refreshed Gmail access token unsealed |
| `backend/routes/portfolio_tax.py`:85 and `backend/services/cg_statement.py`:38-41, 99 | | capital-gains header reads `users.pan`; masks as `XXXXX1234F` (five characters shown) |
| `backend/routes/upload.py` | 184 | `X-Password` header read and never used (PDFs return 410 at 208-209) |
| `backend/portfolio_ingestion/api/sdk_callback.py`:46, `api/uploads.py`:49, 121, `api/webhooks.py`:89 | | PAN arrives in a body field, an `X-User-Pan` header, or a webhook payload |
| `backend/portfolio_ingestion/services/checksum.py`:7-16, `services/user_resolver.py`:30-95, `services/parsed_data_archive.py`:65-80, `db/migrations/002_pgcrypto_pan.sql`:24-50 | | unkeyed hash, pgcrypto encryption with a placeholder key fallback, raw archive |
| `backend/core/logging_config.py` | 145-157, 223-226, 233, 284 | masks only `extra=` keys by name; message text and tracebacks are not scrubbed |
| `backend/routes/session_logs.py` | 12 | says logs are "already email/PAN-masked"; not true for message text. Buffer is Redis, 24 h |
| `backend/services/audit.py` | 42-55 | sanitiser redacts by key name; a key named `pan` is not redacted. Onboarding writes no audit rows |
| `scripts/reset_user_full.py` | 70-74, 268-291 | reads `users.pan` / `kyc_pan`, recomputes the unkeyed hash |

Checked and clean: no log statement in the files above prints the PAN or password directly. No PAN or password reaches an LLM prompt (`backend/routes/chat.py:1320-1323` picks the risk profile only). `backend/services/llm_safety.py` has no callers. Data-platform exports project `user_id`, `email`, `name` only (`backend/services/portfolio_gcs_export.py:106`, `portfolio_direct_push.py:121`). Main Postgres migrations have no PAN or password column. No browser analytics or session-replay SDK was found in `frontend-v5` (`src/lib/observability/sentry.ts` is a stub).

### 1c. Lookups by PAN (needs a keyed hash)

- Advisor duplicate check: `profiles.pan_norm` and `users.pan_norm` (`identity_uniqueness.py:126-127, 167-168`).
- Legacy ingestion: `pan_hash` is the unique key on `users`, part of a unique constraint on `ingestion_jobs`, and the join key across snapshots, holdings and audit rows; also `backend/services/pi_bridge.py:86`.
- Retail onboarding: no lookup by PAN exists. No index needed there.

---

## 2. What already exists

### `pii_security` (`backend/services/pii_security.py`)

| Property | Today |
|---|---|
| Algorithm | AES-256-GCM (`cryptography` AESGCM), 32-byte key, random 12-byte nonce per value, 16-byte tag. Already AES-256. |
| Encoding | `base64(nonce ‖ ciphertext ‖ tag)`; `seal_field` adds the prefix `enc:v1:` |
| Key source | env `PII_ENCRYPTION_KEY` (base64 of 32 bytes), then `helpers.secrets.get`, which is the Mongo-backed admin secret store, then a deterministic dev key when `APP_ENV` is a dev name |
| Key ids / rotation | none. One key, cached for the life of the process. `v1` is a format marker, not a key id |
| Associated data | none; a ciphertext can be copied between users or fields |
| Failure mode | `encrypt` raises without a key; `seal_field` logs an error and stores plaintext (lines 151-168); `decrypt` returns `None` |
| Users today | Gmail tokens (`seal_field`), broker tokens (`encrypt`, strict), `users.pan_encrypted` |

Weaknesses to fix: plaintext fallback; no key id; key may be read from the same database as the data; the key is readable through the admin reveal endpoint; it is not read from Secret Manager although empty `PII_ENCRYPTION_KEY_STAGING/_PROD` secrets are scaffolded (`deploy/gsm-scaffold-secrets.sh:34`); `.env.staging.example` and `cloudpe/check-env.sh:25-27` do not list the key; the laptop template says `openssl rand -hex 32` (`deploy/dev-laptops/laptop1-app/.env.example:89`), which the loader rejects because it wants base64 of 32 bytes. The rotation steps in `docs/SECURITY_OPS.md:145-155` would make every existing ciphertext unreadable with the current code.

UNVERIFIED: whether `PII_ENCRYPTION_KEY` is set in production or staging. If it is not, Gmail tokens are stored in plaintext today and broker connect fails. Step 1 of the work checks this.

### `users.pan_encrypted` store (`compliance.py:93-157`)

Same helper, bare base64 without prefix or key id, plus `pan_last4` in clear. Requires the `data_processing` consent. Decrypts on every read only to build the mask. No caller in either frontend.

### `portfolio_ingestion` PAN store

`pgp_sym_encrypt` with no options. Per the pgcrypto documentation the default cipher is AES-128 (not taken from this repo). Key is a passphrase from `PI_PAN_ENCRYPTION_KEY`, with a hard-coded placeholder when unset (`002_pgcrypto_pan.sql:33-38`) and a default in `deploy/nivesh-staging/docker-compose.staging.yml:127`. `pan_hash` is unkeyed SHA-256; the PAN space is small enough to reverse by brute force.

### Recommendation: extend, do not replace

Keep `pii_security` and the `cryptography` dependency. Add a v2 format and a keyring beside the existing functions so Gmail and broker ciphertext keep working. Fold `users.pan_encrypted` into the new record. Treat the ingestion module as a separate decision (D2).

---

## 3. Target design

### 3.1 Envelope

```
enc:v2:<kid>:<base64url( nonce[12] ‖ ciphertext ‖ tag[16] )>
AAD = "nivesh-pii|v2|" + purpose + "|" + owner_id
```

AES-256-GCM, fresh random nonce per value, `purpose` is `pan` or `cas_pdf_password`, `owner_id` is the `user_id`. A value copied to another user or field fails to decrypt. Legacy `enc:v1:` and bare base64 values are still read with the key named `legacy`.

New functions in `pii_security.py`; existing ones untouched:

```python
encrypt_field(plaintext: str, *, purpose: str, owner_id: str) -> str   # raises if no key; never returns plaintext
decrypt_field(value: str, *, purpose: str, owner_id: str) -> str       # raises on any failure
needs_reencrypt(value: str) -> bool                                    # key id is not the active one
blind_index(kind: str, normalised: str) -> str                         # "h1:" + base64url(HMAC-SHA-256(index_key, kind|value))
key_status() -> dict                                                   # active id, known ids, source; never key bytes
```

### 3.2 Keys

Recommended: a versioned keyring of AES-256 data keys held in Google Secret Manager, which is the master-key layer (it encrypts secret payloads under a KMS key; a customer-managed KMS key can be attached to the secret later with no code change). This matches the deployment: production is a GCP VM with Secret Manager already used for other secrets (`backend/helpers/gsm.py`); staging on CloudPe has no GCP credentials and falls back to the env file, as the README there states.

```
PII_KEYRING  = {"active":"k1","keys":{"k1":"<base64 32 bytes>","legacy":"<today's PII_ENCRYPTION_KEY, if one exists>"}}
PII_INDEX_KEY = <base64 32 bytes>      # separate key for the HMAC lookup hash
```

Load order: Secret Manager `PII_KEYRING_<ENV>`, then env `PII_KEYRING`, then env `PII_ENCRYPTION_KEY` as the single key `legacy`, then the dev key in dev environments only. Never the Mongo secret store.

Two code details: `gsm.get_for_env` upper-cases `APP_ENV`, so production looks for `..._PRODUCTION` while the scaffold script creates `..._PROD` (`gsm.py:122`, `gsm-scaffold-secrets.sh:44`); map it explicitly. Add the key names to a deny-list in the admin secret endpoints (`admin.py:389`, `413`, `430`, `494`, `609`).

| Alternative | Why not first |
|---|---|
| Random data keys stored wrapped in Mongo, master key in Secret Manager | Cheap master rotation, but adds a key collection whose loss loses the data. Not needed at this row count. |
| Cloud KMS as master key, called by the app | Strongest custody and an audit log per unwrap. Needs a new dependency and GCP credentials on every host; CloudPe has none. Good later step if production stays on GCP. |
| Keep one `PII_ENCRYPTION_KEY` env var | No rotation without a big-bang re-encryption. |
| MongoDB client-side field encryption | Automatic mode needs Enterprise or Atlas; explicit mode adds a key vault and a native library for three fields. |
| One data key per user | Helps erasure, adds complexity; backups still hold the wrapped keys. |

Owner provisions: two secrets per environment generated with `openssl rand -base64 32`; read access limited to the backend's service account and two named people (today `roles/secretmanager.secretAccessor` is project-wide for two service accounts, `deploy/setup-iam.sh:166, 201`); an offline escrow copy.

### 3.3 Storage

New collection `user_secrets`, one document per `user_id` (unique index):

```
{ user_id, pan_enc, pan_last4, pan_set_at, cas_pdf_password_enc, cas_pdf_password_set_at, updated_at }
```

New module `backend/services/investor_secrets.py` is the only code that reads or writes it:

```python
set_pan(user_id, pan) / set_statement_password(user_id, pw)
get_unlock_password(user_id) -> str | None      # custom password, else PAN upper-cased
get_pan_masked(user_id) -> str | None           # from pan_last4, no decryption
has_unlock_secret(user_id) -> bool
clear_statement_password(user_id) / clear_all(user_id)
```

Why a separate collection: `user_profiles` is read whole in about 28 places and returned whole by two routes, and `users` is returned whole by four. A separate record never travels with them. It gives the same shape for retail users and advisor clients (keyed by the shadow user id) and replaces `users.pan_encrypted`. Alternative: encrypted fields in place on `user_profiles`; smaller change, but relies on every whole-document read being filtered from now on.

### 3.4 What stops being stored

- `cas_password` on both collections: it is only ever a copy of the PAN. Derive at use time.
- Both `gmail_tokens` password fields. The sweep selects on Gmail auto-import being enabled and checks `has_unlock_secret`. Side effect: users the sweep skips today because of the `upsert=False` gap will be imported again.
- The custom statement password after a successful upload when Gmail auto-import is off. It is needed only for scheduled imports (D3).
- `client_cas_invites.client_pan`: the import and upload endpoints that used it return 410 (`client_cas_invite.py:566-575, 601-612`).
- The unused `X-Password` header read.

### 3.5 What the user sees

Masked PAN only, one format everywhere: `XXXXX1234X` from `pii_security.mask_pan`. Replace the `XXXXX1234F` mask in `cg_statement.py` and the full `client_pan` shown to advisors (`frontend/src/components/mfd/SharedCasFiles.jsx:292-300`). The statement password is never shown; show "saved on <date>" with a remove button. `GET /api/onboarding/state` gains `pan_masked` beside `pan_on_file`.

### 3.6 Lookup hash

`pan_bidx = blind_index("pan", normalised_pan)` on `profiles` and shadow `users`, replacing `pan_norm` and its indexes. Conflict responses stop echoing the PAN. The protection lasts only while the index key stays secret, because the PAN space is small.

---

## 4. Migration

Tool: `backend/scripts/pii_backfill.py`, run inside the backend container so it uses the same key loader. It prints user ids and counts, never values.

| Mode | What it does |
|---|---|
| `--dry-run` (default) | Counts per collection and field: plain values present, PAN-shaped or not, conflicts between copies, already migrated. Writes nothing. |
| `--copy` | For each user: resolve the PAN (`user_profiles.pan`, then `cas_password` if PAN-shaped, then `gmail_tokens.cas_password`, then legacy `users.pan_encrypted`) and the custom password (`user_profiles.cas_pdf_password`, then `gmail_tokens.cas_pdf_password`; a non-PAN-shaped `cas_password` counts as custom). Encrypt, upsert `user_secrets`, decrypt and compare in memory. Old fields untouched. |
| `--verify` | For every user that still has an old field: decrypted new value equals old value. Lists mismatches and conflicts by user id. |
| `--unset` | Removes old fields only where verify passes, using an update filtered on the old value so a concurrent user edit is not lost. |

Idempotent: a user whose record already matches is skipped. Resumable: `--resume-after <user_id>` and a batch size. Conflicting copies are reported for manual review; default winner is `user_profiles.pan`, matching `onboarding_gmail.py:202-204`.

Sequence:

1. Deploy code that writes only the new record and reads new first, old second. Every new write also unsets that user's old fields.
2. `--dry-run`, then `--copy`, then `--verify` on staging, then production.
3. Run one scheduled import on the new code (the 1st of the month at 06:30, `backend/services/mf_scheduler.py:357`, or a manual trigger). Watch a counter of fallback reads; it should reach zero.
4. `--unset`, drop the `pan_norm` indexes, compact the affected collections in a quiet window (removed values stay in the data files until then).
5. Remove the fallback reader in a later release.

Verification that none remain (expect 0 for each):

```js
db.user_profiles.countDocuments({$or:[{pan:{$exists:true}},{cas_password:{$exists:true}},{cas_pdf_password:{$exists:true}}]})
db.gmail_tokens.countDocuments({$or:[{cas_password:{$exists:true}},{cas_pdf_password:{$exists:true}}]})
db.users.countDocuments({$or:[{pan:{$exists:true}},{pan_norm:{$exists:true}},{pan_encrypted:{$exists:true}},{kyc_pan:{$exists:true}},{pan_number:{$exists:true}}]})
db.profiles.countDocuments({$or:[{pan:{$exists:true}},{pan_norm:{$exists:true}}]})
db.client_cas_invites.countDocuments({client_pan:{$exists:true}})
db.user_secrets.countDocuments({$or:[{pan_enc:{$exists:true,$not:/^enc:v2:/}},{cas_pdf_password_enc:{$exists:true,$not:/^enc:v2:/}}]})
```

Plus a read-only scan, `backend/scripts/pii_audit.py`, that walks every collection for strings matching `^[A-Z]{5}[0-9]{4}[A-Z]$` and reports collection, field path and count. It catches copies nobody listed, for example `cas_parsed_responses.raw_payload` and `pi_raw_parsed_data.parsed_data.investor.pan`.

Copies that still hold plain values:

- The Mongo data directory until compaction. The compose files run a single `mongo:7` container with no replica set (`deploy/nivesh-app/docker-compose.prod.yml:17-34`), so no secondaries and no oplog. UNVERIFIED for the running production host.
- Migration bundles written by `deploy/cloudpe/migrate/capture-gcp-app.sh` (a full `mongodump`, a `pg_dump`, and at line 253 the env file in the same bundle), the old GCP staging data directory, and any developer dumps (`deploy/dev-laptops/scripts/dump-app-vm.sh`).
- No scheduled backup of the app database is defined in `deploy/`. UNVERIFIED whether VM disk snapshots or ad hoc dumps exist.
- Logs: docker json-file, Cloud Logging through the ops agent, and the 24 h Redis session buffer. They cannot be edited; they age out.
- Git history for the PDFs under `data/`.

Rollback:

- Before step 4: roll the code back freely. Users who saved a PAN after step 1 are asked for it again; nothing is lost.
- After step 4: data rollback is not possible by design. Code must not go back past the step-1 release. Take one encrypted pre-migration dump, keep it for a fixed short period (suggest 14 days), then destroy it and record that.
- If the new key is wrong or lost before step 4, the old fields are still there; fix the key and re-run `--copy`.

---

## 5. Operations

| Topic | Rule |
|---|---|
| Generation | `openssl rand -base64 32` per key, on a trusted machine, straight into the secret store. Fix the hex instruction in the laptop template. |
| Storage | Production: Secret Manager. CloudPe staging: env file, mode 600, root only. Never in Mongo, never in the repo, never in a migration bundle (exclude the key lines at `capture-gcp-app.sh:253`). |
| Access | Backend service account plus two named people. Admin secret endpoints refuse these names. Fix the reveal audit call. |
| Rotation | Add a new key id and make it active; restart; run `pii_reencrypt --dry-run` (counts per key id), then `--apply` (re-encrypts values whose id is not active, filtered on the old ciphertext); confirm zero values on the old id; remove the old key once backups that need it have expired. Rehearse on staging. |
| Index key rotation | Recompute `pan_bidx` from decrypted PANs under prefix `h2:`; look up both during the change. |
| Key lost | Encrypted PANs and statement passwords are unreadable; users re-enter them. Holdings are unaffected. If the legacy key is lost too, users reconnect Gmail and brokers. Escrow copy and secret versions are the protection. |
| Fail closed | Missing or invalid key: PAN endpoints return 503 and store nothing. After the key is confirmed in each environment, make startup fail without it. Do not change `seal_field` for Gmail tokens in the same step; that is a follow-up. |
| Logging | Add a filter in `core/logging_config.py` that redacts PAN-shaped tokens in message text and exception text. Strip the supplied secret from parser error strings before logging or returning them. Fix the comment in `session_logs.py:12`. |
| Memory | Decrypt inside the function that opens the PDF. No caching of decrypted values. Stop writing them into the profile dict (`onboarding_gmail.py:674-675, 683`). Python cannot wipe strings, so also disable core dumps for the backend container and keep local variables out of any future error reporter. |
| Environments | Different keys for staging and production. When production data is restored elsewhere, exclude `user_secrets` (the restore script already takes `--nsExclude`, `deploy/cloudpe/app/restore.sh:124`). Laptops keep the dev key and must not hold real data. |
| Scan test | A pytest that drives save-PAN, save-password, upload, Gmail import and scheduled import with a canary PAN and canary password against a fake database, then asserts the canaries and any PAN-shaped string are absent from every log record, every response body and every stored document. Plus the audit script as a scheduled check, and a CI grep that fails on new writes of `"pan"`, `cas_password` or `cas_pdf_password` outside `investor_secrets.py`. |

CI today only byte-compiles the backend (`.github/workflows/ci.yml:26-28`); no workflow, Jenkinsfile or Makefile runs pytest. Add a job for the new tests.

---

## 6. Related fixes in the same work

### UI text

| Place | Now | Before the change (true today) | After the change |
|---|---|---|---|
| `frontend-v5/src/pages/Onboarding/index.tsx:457` | "Used only to decrypt your CAS PDF — never stored in plain text or shared." | "Used to open your CAS PDF. It is saved on your profile so later statements open without asking again." | "Used to open your CAS PDF. Stored encrypted; only the last four digits are ever shown. You can remove it any time." |
| `frontend-v5/src/pages/CopilotApp/screens/account/parts.tsx:230` | already accurate | no change | add "in encrypted form" |
| `frontend-v5/src/pages/CopilotApp/screens/Brokers.tsx:257` | already accurate ("Disconnecting Gmail does not remove it") | no change | reword to match decision D4 |
| `frontend-v5/src/pages/CopilotApp/screens/Settings.tsx:238, 327` | already accurate about export and deletion gaps | no change | update when export and deletion are fixed |
| `frontend/src/components/OnboardingCopilotWrapped.jsx:335` | "Stored encrypted." | same correction as the first row | restore |
| `frontend/src/v3/screens/onboarding/Onboarding.jsx:705` | "256-bit · encrypted at rest · DPDP compliant" | remove until true | owner wording |

"Or shared" should not come back while the scheduled import sends the password to the hosted parser (D5). Other claims on the same onboarding page for the owner to check: "AES-256", "PDFs deleted after parsing", and "India-hosted (Bangalore)" at lines 159 and 244; the production VM script uses `asia-south1` (`deploy/nivesh-app/create-vm.sh:11-12`).

### Export (`compliance.py:161-193`)

Add the profile (without secrets), `pan_masked`, and whether a statement password is saved with its date. Never plaintext, ciphertext or the lookup hash. Strip `pan_norm` and `pan_encrypted` from the `users` part.

### Deletion (`compliance.py:196-228`)

Minimum for this work: delete `user_secrets`, the `user_profiles` row, `gmail_tokens`, sessions, and the ingestion rows for that user; make `is_deleted` block sign-in. The full list of per-user collections already exists in `admin_users.py:228-256`; completing account deletion across all of them is a larger task (D2). Advisor profile delete (`mfd_workspace.py:261-275`) should also clear the shadow user's secrets and profile row.

### Gmail disconnect (`gmail.py:228-233`)

Today it deletes the token document, which removes the mirrored copies, and leaves the PAN and password on the profile. The same happens silently when a token is found invalid (`onboarding_gmail.py:263`, `gmail.py:298`). After the change: one shared disconnect function that deletes the token and the saved statement password; PAN handling per D4. Google-side revocation is not called today; the UI already tells the user to remove access in their Google account.

### Regulatory context (not legal advice; confirm with counsel)

- DPDP Act 2023 section 8(5): reasonable security safeguards to prevent a personal data breach. The 2025 Rules name encryption, masking, access control and access logs among them.
- Section 8(7) and section 12: erase personal data when consent is withdrawn or the purpose is served, and on request. That is why the password should not outlive Gmail import and why deletion and backups matter.
- Sections 5 and 6: the notice must describe the processing accurately. That covers the onboarding sentence and the third-party parser.
- Section 8(6): breach intimation. Ask counsel whether the PDFs in git or the plain values in bundles need assessment.
- The code cites "DPDP §8(6)" for seven-year audit retention (`compliance.py:199`); that reference should be checked.
- Onboarding stores the PAN without checking the `data_processing` consent that `PUT /api/compliance/pan` requires.

---

## 7. Work breakdown

### Decisions needed before work starts

| # | Decision | Recommendation |
|---|---|---|
| D1 | Where the key lives, who can read it, who holds the escrow copy | Secret Manager in production, env file on CloudPe staging, two named readers |
| D2 | Scope: retail only, or also advisor client PANs, the legacy ingestion store, and full account deletion | Retail first; advisor next; retire the ingestion module if nothing live uses it |
| D3 | Keep the statement password after import? Keep the PAN? | Keep the PAN encrypted; keep the custom password only while Gmail auto-import is on |
| D4 | On Gmail disconnect, delete the PAN too? | Delete the statement password; keep the PAN with a visible remove button |
| D5 | Scheduled import: keep sending PDF and password to hosted casparser.in? | Switch to the local extractors used by onboarding |
| D6 | Old backups, bundles, developer dumps, PDFs in git (history rewrite needs a force-push) | Inventory, destroy, record; rewrite history after confirming what the PDFs are |
| D7 | Does staging hold real investor data? | If yes, treat staging like production for this work |
| D8 | UI wording sign-off | Table in section 6 |

### Pull requests, in order

| # | Change | Main files | Tests | Risk | Size |
|---|---|---|---|---|---|
| 1 | Stop returning the values; correct the UI sentence; drop the unused header read. Needs no key. | `backend/routes/user.py`, `backend/routes/auth.py`, `backend/routes/upload.py:184`, the three frontend text files | Response test with canary values in a fake DB; frontend text check | Low. No reader of `profile.pan` found in `frontend-v5` | S |
| 2 | Read-only audit script and preflight: counts of plain fields, PAN-shape scan, sealed versus plain Gmail tokens, `pii_key_source`. Add a pytest CI job. | `backend/scripts/pii_audit.py`, `.github/workflows/ci.yml` | Script against a fake DB; run on staging and production | None (read-only) | S |
| 3 | Crypto core: keyring loader, v2 envelope, lookup hash, fail-closed API, admin deny-list, env-suffix fix, deploy templates, runbook. | `backend/services/pii_security.py`, `backend/helpers/gsm.py`, `backend/routes/admin.py`, `deploy/gsm-scaffold-secrets.sh`, `deploy/nivesh-staging/.env.staging.example`, `deploy/cloudpe/check-env.sh`, `deploy/dev-laptops/laptop1-app/.env.example`, `docs/SECURITY_OPS.md` | Round trip; tamper each part; wrong owner or purpose; legacy v1 and bare base64 still decrypt; two-key rotation; no key means an error, never plaintext | Medium: must not disturb Gmail and broker ciphertext | M |
| 4 | Secrets service and retail routes: write new only, read new then old; sweep selector; `pan_masked`; compliance PAN endpoints on the service. | new `backend/services/investor_secrets.py`, `backend/routes/onboarding_gmail.py`, `backend/services/gmail_auto_import.py`, `backend/routes/gmail.py`, `backend/routes/compliance.py`, `backend/server.py` | Unit matrix (new only, old only, both, neither); sweep selection; end-to-end below | Highest: all three import paths | M |
| 5 | Log and error hygiene: message redaction filter, sanitised parser errors, canary scan test. | `backend/core/logging_config.py`, `backend/routes/onboarding_gmail.py`, `backend/services/cas_api_client.py`, `backend/routes/session_logs.py` | Canary scan; extend `backend/tests/test_core_logging.py` | Low | S |
| 6 | Backfill tool and runbook; run copy and verify on staging, then production. | `backend/scripts/pii_backfill.py` | Dry-run counts on a seeded fake DB; idempotent second run; resume; conflict report; concurrent-edit filter | Medium | M |
| 7 | Export, deletion, Gmail disconnect. | `backend/routes/compliance.py`, `backend/routes/gmail.py`, `backend/services/mfd_workspace.py` | Extend `backend/tests/test_iteration44_compliance.py`; disconnect clears the password; deleted user cannot sign in | Medium: deletion is irreversible | M |
| 8 | Remove plain fields and the fallback reader; compact; final UI text; verification queries in the runbook. | backfill `--unset`, `backend/services/investor_secrets.py`, frontend text | Verification queries return 0; canary scan | Medium: irreversible | S |
| 9 | Rotation tool and staging rehearsal. | `backend/scripts/pii_reencrypt.py` | Rotate on staging, import still works, old key id count is 0 | Low | S |
| 10 (D5) | Scheduled import uses the local extractor chain. | `backend/services/gmail_auto_import.py`, shared function from `onboarding_gmail.py:701` | Parser parity on sample statements | Medium: different parser for monthly imports | M |
| 11 (D2) | Advisor scope: client PAN encrypted under the shadow user, lookup hash, masked responses, invite PAN removed, old advisor UI. | `backend/services/mfd_workspace.py`, `backend/services/identity_uniqueness.py`, `backend/routes/mfd.py`, `backend/routes/client_cas_invite.py`, `backend/routes/admin_users.py`, `backend/routes/portfolio_tax.py`, `backend/services/cg_statement.py`, `frontend/src/components/mfd/SharedCasFiles.jsx` | Duplicate detection still fires; no PAN in 409 bodies; `backend/tests/test_client_cas_invite.py` | Medium | L |
| 12 (D2) | Legacy ingestion: keyed hash across five tables and one collection, AES-256, scrub archived `investor.pan`; or retire the module. | `backend/portfolio_ingestion/services/checksum.py`, `user_resolver.py`, a new SQL migration, `backend/services/pi_bridge.py`, `scripts/reset_user_full.py` | Existing `backend/portfolio_ingestion/tests/integration/test_pan_encryption.py` and neighbours | High if migrated, low if retired | L |
| 13 (D6) | Destroy old copies: bundles, old staging data, developer dumps, `data/` PDFs and their history; add `data/` to `.gitignore`. | ops, `.gitignore` | Audit script on each remaining copy | Medium: history rewrite affects every clone | S to M |

All paths in this table are under ``.

End-to-end test with a password-protected PDF (PR 4): build the fixture at test time with `pikepdf` (already pinned) from a synthetic one-page PDF locked with a canary PAN. A synthetic file is not a real statement, so stub the four extractors with one that opens the bytes with `pdfplumber.open(..., password=...)` and returns a fixed holding. Cover: upload with the password; second upload with the field empty (stored secret is used); Gmail import and scheduled import with Gmail calls stubbed. Assert the PDF opened, the database holds only `enc:v2:` values, and the canary appears in no log or response. No anonymised real-layout statement exists in `backend/tests/fixtures`; a true parser test needs one supplied, or a manual staging run with a team member's own statement. Do not use the PDFs under `data/`.

### What can go wrong

| Risk | Mitigation |
|---|---|
| Key missing or in the wrong format at deploy | PR 2 preflight; startup self-test; fail closed; key in place before PR 4 ships |
| Key lost | Escrow copy and secret versions; impact is re-entry by users, not data loss |
| Monthly import skips everyone after the mirror fields go | Selector changed in PR 4, before any field is removed; compare sweep summary before and after |
| Backfill damages a value | Copy, verify and unset are separate steps; in-memory comparison per row; time-boxed pre-migration dump |
| Rollback after fields are removed | Fallback reader stays one release; documented code floor |
| Custom passwords altered (case, spaces) | Store exactly what the route stores today; round-trip tests including non-ASCII |
| A client depends on `pan` or `client_pan` in a response | Only the old advisor file list does; it gets the masked value in PR 11 |
| Duplicate detection weakens when `pan_norm` goes | Fill `pan_bidx` first, look up both during the change |
| Plain values survive in files, logs, backups, bundles, laptops, git | Compaction, log expiry, PR 13, audit script on every copy |
| Production data restored to staging cannot be decrypted | Intended; exclude `user_secrets` on restore |
| Redaction filter hides something useful or slows logging | Pattern limited to the 10-character PAN shape; measured in PR 5 |

---

## UNVERIFIED (could not be confirmed from the code)

- Whether `PII_ENCRYPTION_KEY` is set in production or staging, and therefore whether Gmail tokens are encrypted today.
- Whether a hosted casparser API key is configured in production, that is, whether the scheduled import really sends the password out.
- Row counts; any conflict between the stored copies.
- Whether the 65 tracked PDFs are real investor statements.
- Whether staging holds real investor data.
- Whether the ingestion module is active in production (`PI_POSTGRES_URL` set) and whether `cas_parsed_responses` holds old payloads with a PAN.
- Whether pages 2-3 sent to OpenAI Vision show the PAN.
- Production backups, disk snapshots and the location of migration bundles; the real MongoDB topology on the production host.
- pgcrypto's default cipher (from its documentation) and the DPDP section details (for counsel).

Also seen, outside this scope: the staging compose file has a database password written inline (`deploy/nivesh-staging/docker-compose.staging.yml:109`).
