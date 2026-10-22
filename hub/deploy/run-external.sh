#!/usr/bin/env bash
# LEGACY DEMO ONLY. This script binds the API to a public interface.
# Do not use it in production; use hub-api.service behind nginx TLS.
set -euo pipefail

echo "Refusing to run: this legacy helper binds the API publicly." >&2
echo "Use deploy/hub-api.service on loopback behind the TLS nginx vhost." >&2
exit 2
