#!/usr/bin/env bash
# Local release APK build (debug signing, for preview only).
# A store build needs a real keystore/EAS and a signed AAB.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?set ANDROID_HOME to the Android SDK}"
npx expo prebuild --platform android --no-install
echo "sdk.dir=$ANDROID_HOME" > android/local.properties
cd android
./gradlew assembleRelease
echo "APK: $(pwd)/app/build/outputs/apk/release/app-release.apk"
