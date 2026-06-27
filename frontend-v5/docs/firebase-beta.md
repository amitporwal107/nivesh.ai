# Firebase email/password beta login + App Distribution

Lets beta testers sign into the **Android app** with **email/password** (Firebase
Auth) instead of Google OAuth, and distributes the APK to them via **Firebase App
Distribution**. The app's *data* still comes from the `niveshcopilot.com` backend —
Firebase is used **only** for authentication (no Firestore).

## How the login works (end to end)

```
app (frontend-v5)                         backend (FastAPI)
  signInWithEmailAndPassword(email, pw)
  → Firebase ID token
  POST /api/auth/firebase {id_token} ───▶  verify token (firebase-admin)
                                           → email → whitelist gate
                                           → upsert user → session_token
  ◀── Set-Cookie: session_token  +  body.session_token
  (cookie + Bearer used for all /api/* calls, identical to Google login)
```

The Firebase token only proves *who the tester is*. The backend still issues the
same `session_token` cookie the Google flow uses, so the rest of the app is
unchanged. **Tester emails must be whitelisted** (`whitelisted_users`), exactly
like Google users — Firebase auth is not a way around the invite list.

## One-time Firebase console setup (project `616586328496`)

1. **Auth → Sign-in method →** enable **Email/Password**.
2. **Create tester accounts**: Auth → Users → Add user (email + password), or let
   testers self-register. Then **add each tester's email to the app whitelist**
   (admin console / `whitelisted_users`) or they'll be rejected with AUTHZ-001.
3. **Register a Web app** (Project settings → General → Your apps → Web). Copy its
   config — these become the build Variables below. (A *Web* app, even though we
   ship in a WebView; the JS SDK uses the web config.)
4. **Register the Android app** (package `ai.nivesh.app`) to get the **App ID**
   used for App Distribution (`1:616586328496:android:…`).
5. **App Distribution → Testers & Groups**: create a group (e.g. `beta`) and add
   tester emails.
6. **Service account**: Project settings → Service accounts → generate a key (or a
   dedicated SA with the **Firebase App Distribution Admin** role). Used by CI.

## GitHub config

### Repository **Variables** (Settings → Secrets and variables → Actions → Variables)
Firebase **web** config is not secret (it ships in the client), so it lives in Variables:

| Variable | From |
|---|---|
| `VITE_FIREBASE_API_KEY` | Web app config `apiKey` |
| `VITE_FIREBASE_AUTH_DOMAIN` | Web app config `authDomain` |
| `VITE_FIREBASE_PROJECT_ID` | Web app config `projectId` |
| `VITE_FIREBASE_APP_ID` | Web app config `appId` |
| `FIREBASE_TESTER_GROUPS` | tester group alias(es), comma-separated (default `beta`) |

If the `VITE_FIREBASE_*` vars are unset, the email/password block is simply hidden
and the build still succeeds (Google-only).

### Repository **Secrets**

| Secret | What |
|---|---|
| `FIREBASE_ANDROID_APP_ID` | the Android App ID, `1:616586328496:android:…` |
| `FIREBASE_SERVICE_ACCOUNT` | the service-account JSON (full file contents) |

## Backend config (deployed env — see DEVOPS_ENVIRONMENTS)

The backend verifies Firebase ID tokens at `/api/auth/firebase`. Set on the
Nivesh app backend (prod + staging):

| Env var | Value |
|---|---|
| `FIREBASE_PROJECT_ID` | the Firebase project id (the `projectId` above) |
| `FIREBASE_SERVICE_ACCOUNT` | *(optional)* service-account JSON; not required for token verification |

`firebase-admin` is in `backend/requirements.txt`, so the backend image must be
rebuilt/redeployed for the endpoint to work.

## Distribution

The release workflow's **Distribute to Firebase App Distribution** step uploads
the signed APK to the tester group on every run (toggle with the `distribute`
input). Testers get an email + install via the Firebase App Tester app. The APK is
*also* still published to `data.niveshcopilot.com` (toggle `publish`).

## Verifying

- Web/typecheck build with the `VITE_FIREBASE_*` vars set → the Login screen shows
  the "or beta sign-in" email/password block.
- Backend: `POST /api/auth/firebase` with a real Firebase ID token returns the user
  + sets `session_token`; a non-whitelisted email returns AUTHZ-001; a bad token
  returns AUTH-003.
