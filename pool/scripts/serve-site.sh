#!/usr/bin/env bash
# Keeps the static site reachable: starts a listener when the port is dark.
# The site is plain files, so any process death is just a restart away.
set -u
SITE_DIR="/home/dev/proxylist/site"
PORT="${1:-8931}"
if ss -tln | grep -q ":${PORT} "; then
  exit 0
fi
cd "$SITE_DIR" || exit 1
setsid nohup python3 -m http.server "$PORT" --bind 0.0.0.0 >>/tmp/opp-site-${PORT}.log 2>&1 < /dev/null &
exit 0
