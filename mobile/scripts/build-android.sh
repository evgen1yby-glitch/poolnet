#!/usr/bin/env bash
# Local release APK build (debug signing, for website distribution).
# A store build needs a real keystore/EAS and a signed AAB.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?set ANDROID_HOME to the Android SDK}"
if [ ! -f android/app/libs/libXray.aar ]; then
  ./scripts/fetch-libxray.sh
fi
echo "sdk.dir=$ANDROID_HOME" > android/local.properties
cd android
./gradlew assembleRelease
echo "APK: $(pwd)/app/build/outputs/apk/release/app-release.apk"
