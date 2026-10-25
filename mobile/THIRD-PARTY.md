# Third-party native dependency

## libXray / Xray-core

The Android VPN tunnel embeds `libXray.aar`:

- libXray — MIT License — https://github.com/XTLS/libXray
- Xray-core — Mozilla Public License 2.0 — https://github.com/XTLS/Xray-core

The AAR is not stored in git because it is ~50 MB. `./scripts/fetch-libxray.sh`
downloads the checksum-pinned artifact from the `mobile-libs-v1` release. If you
build it yourself, use the official libXray build script and keep the same ABI
and API level.

The PoolNet Mobile application code is AGPL-3.0-or-later. The Xray-core MPL-2.0
and libXray MIT terms remain in effect for their respective files/binaries.
