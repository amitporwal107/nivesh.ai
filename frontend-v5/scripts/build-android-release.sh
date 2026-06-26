#!/usr/bin/env bash
# Build the PRODUCTION v5 Android app and (optionally) publish it at the public
# download URL on data.niveshcopilot.com.
#
# Unlike build-android-apk.sh (staging, unsigned debug), this:
#   - bakes API calls to the PROD backend (https://niveshcopilot.com)
#   - uses the production identity (appId ai.nivesh.app, name "Nivesh")
#   - produces a SIGNED release APK *and* an AAB (Play Store upload format)
#
#   bash frontend-v5/scripts/build-android-release.sh
#
# Output:
#   - frontend-v5/nivesh-v5-prod-release.apk                       (local copy)
#   - frontend-v5/nivesh-v5-prod-release.aab                       (local copy, for Play)
#   - /var/www/nidp-downloads/nivesh-v5-prod-release.apk           (served file, if webroot present)
#   - https://data.niveshcopilot.com/downloads/nivesh-v5-prod-release.apk
#
# Required env (CI supplies these from GitHub secrets; see
# docs/android-release.md). The build FAILS FAST if any are missing rather than
# silently producing a misconfigured or unsigned app:
#   CAP_GOOGLE_SERVER_CLIENT_ID   prod web OAuth client id (aud the prod backend trusts)
#   ANDROID_KEYSTORE_FILE         path to the release keystore (.jks)
#   ANDROID_KEYSTORE_PASSWORD     store password
#   ANDROID_KEY_ALIAS             key alias
#   ANDROID_KEY_PASSWORD          key password (optional; defaults to store password)
#
# Optional env:
#   ANDROID_VERSION_CODE          integer build number (default: 1)
#   ANDROID_VERSION_NAME          user-facing version  (default: 1.0)
#
# Toolchain: JDK 17 + Android SDK (ANDROID_HOME). On the legacy build box the SDK
# lives at /opt/android-sdk; in CI it is provisioned by android-actions/setup-android.
set -euo pipefail

FE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FE_DIR"

# ── Required secrets / config ───────────────────────────────────────────────
: "${CAP_GOOGLE_SERVER_CLIENT_ID:?Set CAP_GOOGLE_SERVER_CLIENT_ID to the prod web OAuth client id}"
: "${ANDROID_KEYSTORE_FILE:?Set ANDROID_KEYSTORE_FILE to the release keystore path}"
: "${ANDROID_KEYSTORE_PASSWORD:?Set ANDROID_KEYSTORE_PASSWORD}"
: "${ANDROID_KEY_ALIAS:?Set ANDROID_KEY_ALIAS}"
if [ ! -f "$ANDROID_KEYSTORE_FILE" ]; then
  echo "✗ Keystore not found at ANDROID_KEYSTORE_FILE=$ANDROID_KEYSTORE_FILE" >&2
  exit 1
fi

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"

# ── Production identity (consumed by capacitor.config.ts + app/build.gradle) ──
export CAP_APP_ID="${CAP_APP_ID:-ai.nivesh.app}"
export CAP_APP_NAME="${CAP_APP_NAME:-Nivesh}"
export ANDROID_VERSION_CODE="${ANDROID_VERSION_CODE:-1}"
export ANDROID_VERSION_NAME="${ANDROID_VERSION_NAME:-1.0}"

# ── Prod web build: API baked to prod (the WebView can't proxy /api) ─────────
export VITE_API_BASE_URL="https://niveshcopilot.com"
export VITE_USE_MOCK_API="false"
export VITE_APP_VERSION="$ANDROID_VERSION_NAME"
unset VITE_BASE || true   # APK serves from https://localhost root, base must be "/"

WEBROOT="/var/www/nidp-downloads"
APK_NAME="nivesh-v5-prod-release.apk"
AAB_NAME="nivesh-v5-prod-release.aab"
BUILT_APK="android/app/build/outputs/apk/release/app-release.apk"
BUILT_AAB="android/app/build/outputs/bundle/release/app-release.aab"

echo "▸ Identity: appId=$CAP_APP_ID name=\"$CAP_APP_NAME\" v$ANDROID_VERSION_NAME ($ANDROID_VERSION_CODE)"
echo "▸ Building web bundle (prod → $VITE_API_BASE_URL)…"
npm run build

echo "▸ Syncing web assets into Android…"
npx cap sync android

echo "▸ Assembling signed release APK…"
( cd android && ./gradlew assembleRelease --no-daemon )

echo "▸ Bundling signed release AAB (Play Store)…"
( cd android && ./gradlew bundleRelease --no-daemon )

echo "▸ Collecting artifacts…"
cp "$BUILT_APK" "$APK_NAME"
cp "$BUILT_AAB" "$AAB_NAME"

echo "▸ Publishing APK…"
if [ -d "$WEBROOT" ]; then
  cp "$BUILT_APK" "$WEBROOT/$APK_NAME"
  chmod 644 "$WEBROOT/$APK_NAME"
  echo "  published to $WEBROOT/$APK_NAME"
else
  echo "  NOTE: $WEBROOT not found on this host — local copies only."
  echo "        CI publishes to data.niveshcopilot.com via SCP (see android-release workflow)."
fi

echo "✓ Done."
echo "  APK sha256: $(sha256sum "$BUILT_APK" | cut -d' ' -f1)"
echo "  AAB sha256: $(sha256sum "$BUILT_AAB" | cut -d' ' -f1)"
echo "  URL: https://data.niveshcopilot.com/downloads/$APK_NAME"
