# Android app — production build & publish

The Nivesh v5 web app is wrapped as a native Android app with **Capacitor**. The
web bundle (`dist/`) is packaged into the APK and served from the in-app
`https://localhost` origin; all `/api/*` calls are baked to a backend URL at
**web build time** (the WebView can't proxy them).

There are **two flavors**, produced from the *same* `android/` native project —
identity and backend are switched by env, not by forking the tree:

| Flavor | Script | appId | Backend (baked) | Signing | Published to |
|---|---|---|---|---|---|
| Staging | `scripts/build-android-apk.sh` | `ai.nivesh.staging` | `staging.niveshcopilot.com` | debug (unsigned) | `data.niveshcopilot.com/downloads/nivesh-v5-staging-debug.apk` |
| **Prod** | `scripts/build-android-release.sh` | `ai.nivesh.app` | `niveshcopilot.com` | **release (signed)** | `data.niveshcopilot.com/downloads/nivesh-v5-prod-release.apk` |

> **Why `data.niveshcopilot.com`?** That host (the NIDP VM, `nidp-stack-vm`)
> already serves static downloads from `/var/www/nidp-downloads` at
> `…/downloads/`. The APK is hosted there for direct download/sideloading. The
> **AAB** is a CI artifact only (Play Store upload format) — it is never served
> publicly.

## CI workflow (recommended path)

`.github/workflows/android-release.yml` — **manual trigger**
(Actions → *Build & publish Android app [prod]* → Run workflow). It:

1. sets up JDK 17 + Node 20 + Android SDK,
2. `npm ci`, decodes the keystore, runs `build-android-release.sh`,
3. uploads the APK + AAB as a workflow artifact, and
4. (if *publish* is checked) SCPs the APK to the NIDP VM and `sudo install`s it
   into `/var/www/nidp-downloads`, then HEAD-checks the public URL.

**Bump `version_code` on every release** (Android requires a strictly
increasing integer); set `version_name` to the human version (e.g. `1.0.3`).

### Required GitHub secrets

| Secret | What it is |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | `base64 -w0 release.jks` of the release keystore |
| `ANDROID_KEYSTORE_PASSWORD` | keystore store password |
| `ANDROID_KEY_ALIAS` | signing key alias |
| `ANDROID_KEY_PASSWORD` | signing key password (optional; defaults to store pw) |
| `PROD_GOOGLE_SERVER_CLIENT_ID` | the **prod web** OAuth client id — the one `niveshcopilot.com`'s backend uses as `GOOGLE_CLIENT_ID` (so native-login ID tokens have an `aud` the prod backend accepts) |
| `NIDP_VM_HOST` | IP of `nidp-stack-vm` *(already configured for NIDP deploys)* |
| `DEVOPS_SSH_USER` | CI/CD Linux user on the VM *(already configured)* |
| `DEVOPS_SSH_KEY` | Ed25519 private key for that user *(already configured)* |

The last three already exist (used by the NIDP deploy workflows). Only the
keystore + `PROD_GOOGLE_SERVER_CLIENT_ID` secrets are new.

## One-time prerequisites (outside this repo)

These are **infra actions** that cannot be done from CI and must be completed
once before the prod app will sign-in / install:

1. **Generate a release keystore** (keep it safe and backed up — losing it means
   you can never update the app on Play under the same key):
   ```bash
   keytool -genkeypair -v -keystore release.jks -alias nivesh \
     -keyalg RSA -keysize 2048 -validity 10000
   base64 -w0 release.jks   # paste into the ANDROID_KEYSTORE_BASE64 secret
   ```
2. **Register an Android OAuth client** in the GCP project
   (`niveshdataintelligence`) for package `ai.nivesh.app` + the release keystore's
   SHA-1, so Google trusts native sign-in:
   ```bash
   keytool -list -v -keystore release.jks -alias nivesh   # copy the SHA1
   ```
   The client *id* is never referenced in code — only its existence matters; the
   token's `aud` is `PROD_GOOGLE_SERVER_CLIENT_ID` (the web client).
3. **Webroot + nginx**: `/var/www/nidp-downloads` must exist on `nidp-stack-vm`
   and be served at `https://data.niveshcopilot.com/downloads/` (the staging APK
   is already published the same way, so this is typically already in place).

## Local / build-box path (alternative to CI)

On a box with JDK 17 + Android SDK (`ANDROID_HOME`) and the keystore present:

```bash
export CAP_GOOGLE_SERVER_CLIENT_ID="<prod web client id>"
export ANDROID_KEYSTORE_FILE="$PWD/release.jks"
export ANDROID_KEYSTORE_PASSWORD="…"
export ANDROID_KEY_ALIAS="nivesh"
export ANDROID_VERSION_NAME="1.0.0"
export ANDROID_VERSION_CODE="1"
bash frontend-v5/scripts/build-android-release.sh
```

The script fails fast if any required secret is missing, and only copies the APK
into `/var/www/nidp-downloads` when that directory exists on the host.

## Notes for prod

- `MainActivity` enables third-party cookies so the session cookie set by
  `/api/auth/google` (on `niveshcopilot.com`) survives the next request from the
  `https://localhost` WebView origin. Confirm prod CORS allows the WebView
  origin with `Access-Control-Allow-Credentials: true`.
- `namespace` in `android/app/build.gradle` stays `ai.nivesh.staging` (it must
  match the `MainActivity` Java package); only `applicationId` switches to
  `ai.nivesh.app`. This is the standard Android split and is intentional.
