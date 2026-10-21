#!/usr/bin/env bash
# Rebuild the v5 Android APK after any UI/code change and publish it at the
# public download URL. Run from anywhere; paths are resolved relative to this
# script. Produces a debug APK pointing at the staging backend.
#
#   bash frontend-v5/scripts/build-android-apk.sh
#
# Output:
#   - frontend-v5/nivesh-v5-staging-debug.apk              (local copy)
#   - /opt/nivesh-staging/downloads/nivesh-v5-staging-debug.apk  (served file)
#   - https://staging.niveshcopilot.com/downloads/nivesh-v5-staging-debug.apk
#
# The publish target moved here on 2026-10-21: it used to be
# /var/www/nidp-downloads on the GCP nidp-stack-vm, served at
# data.niveshcopilot.com/downloads/. That VM is gone (the hostname answers
# HTTP 522), so the APK is now served by the staging edge nginx on the app VM
# from a mounted host directory — see deploy/nivesh-staging/nginx-staging.conf
# (location /downloads/) and deploy/cloudpe/app/docker-compose.cloudpe.yml.
# Override with APK_WEBROOT / APK_PUBLIC_URL_BASE.
#
# Toolchain: JDK 17 + Android SDK. On the CloudPe app VM neither is installed on
# the host (and outbound port 80 is blocked, so apt cannot run); build inside the
# container image built from the Dockerfile documented in
# docs/BUILD_AND_DEPLOYMENT.md, which provides both at the paths below.
set -euo pipefail

FE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$FE_DIR"

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-/opt/java/jdk17}"

# API calls are baked to staging at build time (the WebView can't proxy /api).
export VITE_API_BASE_URL="https://staging.niveshcopilot.com"
export VITE_USE_MOCK_API="false"
unset VITE_BASE || true

# Build identity. Date-based by default so every staging APK has a distinct,
# always-increasing versionCode — Android refuses to install over an equal or
# newer code, which a hardcoded "1" made impossible.
export ANDROID_VERSION_NAME="${ANDROID_VERSION_NAME:-$(date +%Y.%m.%d)}"
export ANDROID_VERSION_CODE="${ANDROID_VERSION_CODE:-$(date +%Y%m%d)}"

WEBROOT="${APK_WEBROOT:-/opt/nivesh-staging/downloads}"
PUBLIC_URL_BASE="${APK_PUBLIC_URL_BASE:-https://staging.niveshcopilot.com/downloads}"
APK_NAME="nivesh-v5-staging-debug.apk"
BUILT="android/app/build/outputs/apk/debug/app-debug.apk"

echo "▸ Removing earlier build output…"
rm -rf dist android/app/build android/build ./*.apk ./*.aab

echo "▸ Building web bundle (staging)…"
npm run build

echo "▸ Syncing web assets into Android…"
npx cap sync android

echo "▸ Assembling debug APK (versionName=$ANDROID_VERSION_NAME versionCode=$ANDROID_VERSION_CODE)…"
( cd android && ./gradlew assembleDebug --no-daemon )

echo "▸ Publishing…"
cp "$BUILT" "$APK_NAME"
if [ -d "$WEBROOT" ]; then
  # Drop any earlier APK so only this build is downloadable.
  rm -f "$WEBROOT"/*.apk
  cp "$BUILT" "$WEBROOT/$APK_NAME"
  chmod 644 "$WEBROOT/$APK_NAME"
  echo "  published to $WEBROOT/$APK_NAME"
else
  echo "  WARN: $WEBROOT not found — copied locally only ($FE_DIR/$APK_NAME)"
fi

echo "✓ Done. sha256:"
sha256sum "$BUILT"
echo "  URL: $PUBLIC_URL_BASE/$APK_NAME"
