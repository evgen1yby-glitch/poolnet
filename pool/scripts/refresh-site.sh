#!/usr/bin/env bash
# One pipeline cycle on this box: fetch -> validate -> merge -> publish,
# rebuild the site bundle, restart the listeners if they died, commit.
# The GitHub Actions schedule exists for when the repo has a remote; this
# script is the same cadence for a box that serves the site directly.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

# exactly one cycle at a time; a slow cycle must never stack up
exec 9>/tmp/opp-refresh.lock
flock -n 9 || { echo "$(date -u +%FT%TZ) refresh already running, skipping"; exit 0; }

# the optional freeproxy key lives outside the repo
if [ -f .env.local ]; then set -a; . ./.env.local; set +a; fi

# same budget the CI workflow uses, scaled for one box
export OPP_MAX_NEW_PER_CYCLE="${OPP_MAX_NEW_PER_CYCLE:-3000}"
export OPP_PER_SOURCE_MIN="${OPP_PER_SOURCE_MIN:-150}"
export OPP_CONCURRENCY="${OPP_CONCURRENCY:-350}"

LOG=/tmp/opp-refresh.log
{
  echo "=== $(date -u +%FT%TZ) refresh start ==="
  if ! npx tsx src/index.ts cycle; then
    echo "cycle failed, keeping the previous data"
    exit 1
  fi
  npx tsx src/index.ts roast || echo "roast failed, digest stays stale"
  node scripts/build-web-data.mjs || echo "bundle build failed"
  bash scripts/serve-site.sh 8931
  bash scripts/serve-site.sh 8933
  git add -A data/ site/data/
  if ! git diff --cached --quiet; then
    git -c user.name="open-proxy-pool" -c user.email="bot@open-proxy-pool.local" \
      commit -q -m "data: refresh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi
  echo "=== $(date -u +%FT%TZ) refresh done ==="
} >>"$LOG" 2>&1
