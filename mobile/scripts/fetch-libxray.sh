#!/usr/bin/env sh
# Fetch the prebuilt libXray AAR used by the Android VPN service.
# It is not committed: 50 MB of native binaries belongs in a release asset,
# not in every clone. Build from source instead if you prefer:
#   https://github.com/XTLS/libXray
set -eu
DEST="${1:-android/app/libs/libXray.aar}"
URL="https://github.com/evgen1yby-glitch/poolnet/releases/download/mobile-libs-v1/libXray.aar"
EXPECTED="ed2594eed754cba9f5bc1281c95bb3c0c3f06ed772f0792ef08f383ef4233415"
if [ -f "$DEST" ]; then
  echo "libXray.aar already present: $DEST"
  exit 0
fi
mkdir -p "$(dirname "$DEST")"
tmp="$DEST.tmp"
curl -fL "$URL" -o "$tmp"
actual=$(sha256sum "$tmp" | awk '{print $1}')
if [ "$actual" != "$EXPECTED" ]; then
  rm -f "$tmp"
  echo "libXray.aar checksum mismatch: $actual" >&2
  exit 1
fi
mv "$tmp" "$DEST"
echo "fetched $DEST"
