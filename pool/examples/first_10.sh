#!/usr/bin/env bash
# Fetch the current pool and test the first 10 proxies against an echo endpoint.
# Usage: ./examples/first_10.sh [base-url]
set -euo pipefail

BASE="${1:-https://cdn.jsdelivr.net/gh/OWNER/REPO@main/data}"
URL="${ECHO_URL:-https://api.ipify.org}"

echo "Fetching the pool from $BASE/all.txt ..."
mapfile -t proxies < <(curl -sf "$BASE/all.txt" | head -10)

if [ "${#proxies[@]}" -eq 0 ]; then
  echo "No proxies returned — the pool may be mid-refresh." >&2
  exit 1
fi

for line in "${proxies[@]}"; do
  scheme="${line%%://*}"
  addr="${line#*://}"
  t0=$(date +%s%N)
  if [ "$scheme" = "socks5" ]; then
    out=$(curl -sf --max-time 12 -x "socks5h://$addr" "$URL" || true)
  else
    out=$(curl -sf --max-time 12 -x "http://$addr" "$URL" || true)
  fi
  t1=$(date +%s%N)
  ms=$(((t1 - t0) / 1000000))
  if [ -n "$out" ]; then
    printf 'OK   %-24s %5sms  exit=%s\n' "$addr" "$ms" "$out"
  else
    printf 'DEAD %-24s %5sms\n' "$addr" "$ms"
  fi
done
