# OVERRIDE — One-screen Copilot app (`/v5/app`), branch `feat/copilot-one-screen`

REASON: Two test cases written up front are still open. (1) TC-22 is only partly done: against the real staging backend the home data, all 20 screens and two real chat answers are verified from a local build (see `copilot_one_screen_20261013_1413.md`, "Live checks"), but a question sent from a browser on the deployed origin has not run — staging's cross-site check correctly rejects writes from a page at `localhost`, and the push to `dev` that would deploy the build was blocked by the permission system as a deploy action, so the user has to merge the branch. (2) TC-23, the native Android / iOS build, needs a device build, and the APK script publishes to a public download URL. To finish: merge `feat/copilot-one-screen` into `dev`, wait for staging to redeploy, ask one question at `https://staging.niveshcopilot.com/v5/app`, and decide on the native build.

- Date: 2026-10-13
- Branch pushed: `origin/feat/copilot-one-screen`. `dev` and staging are unchanged.
- This is not a pass. Do not merge to `main` on the strength of this file.

## What is still unverified
- A chat question posted by the browser from the deployed origin (thread creation and live streaming in the page).
- Every write path other than chat: `POST /api/plans/refresh` ("Build my plan"), CAS upload and Gmail import from the new onboarding and connections screens, saved-screen create / update / delete, goal archive, the advisor-workspace upgrade, and the advisor "open client" switch.
- Whether the figures are correct and fresh at source; only that the screens show what the API returns.
- The Capacitor (Android / iOS) shell: safe-area insets and the on-screen keyboard over the ask box.
