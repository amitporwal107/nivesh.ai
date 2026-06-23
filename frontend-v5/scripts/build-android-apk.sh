#!/usr/bin/env bash
# Rebuild the v5 Android APK after any UI/code change and publish it at the
# public download URL. Run from anywhere; paths are resolved relative to this
# script. Produces a debug APK pointing at the staging backend.
#
#   bash frontend-v5/scripts/build-android-apk.sh
#
# Output:
#   - frontend-v5/nivesh-v5-staging-debug.apk          (local copy)
#   - /var/www/nidp-downloads/nivesh-v5-staging-debug.apk  (served file)
#   - https://data.niveshcopilot.com/downloads/nivesh-v5-staging-debug.apk
#
# Toolchain (already installed on the build box):
#   JDK 17 + Android SDK at /opt/android-sdk.
set -euo pipefail

FE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FE_DIR"

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"

# API calls are baked to staging at build time (the WebView can't proxy /api).
export VITE_API_BASE_URL="https://staging.niveshcopilot.com"
export VITE_USE_MOCK_API="false"
unset VITE_BASE || true

WEBROOT="/var/www/nidp-downloads"
APK_NAME="nivesh-v5-staging-debug.apk"
BUILT="android/app/build/outputs/apk/debug/app-debug.apk"

echo "▸ Building web bundle (staging)…"
npm run build

echo "▸ Syncing web assets into Android…"
npx cap sync android

echo "▸ Assembling debug APK…"
( cd android && ./gradlew assembleDebug --no-daemon )

echo "▸ Publishing…"
cp "$BUILT" "$APK_NAME"
if [ -d "$WEBROOT" ]; then
  cp "$BUILT" "$WEBROOT/$APK_NAME"
  chmod 644 "$WEBROOT/$APK_NAME"
  echo "  published to $WEBROOT/$APK_NAME"
else
  echo "  WARN: $WEBROOT not found — copied locally only ($FE_DIR/$APK_NAME)"
fi

echo "✓ Done. sha256:"
sha256sum "$BUILT"
echo "  URL: https://data.niveshcopilot.com/downloads/$APK_NAME"
