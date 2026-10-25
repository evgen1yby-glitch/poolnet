#!/bin/sh
# Publish the current public snapshot to the GitHub `lists` branch from this
# host as a fallback for GitHub's scheduler. The branch is disposable: one
# force-pushed commit, not history.
set -eu

ROOT=${POOLNET_ROOT:-/home/dev/poolnet}
REPO=${POOLNET_GITHUB_REPO:-evgen1yby-glitch/poolnet}
KEY=${POOLNET_GITHUB_KEY:-$HOME/.ssh/id_ed25519_github}
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

exec 9>/tmp/poolnet-lists.lock
flock -n 9 || { echo "lists: another run is active"; exit 0; }
GITHUB_REPOSITORY=$REPO python3 "$ROOT/scripts/build_lists.py" --out "$STAGE"
cd "$STAGE"
git init -q
git checkout -q -b lists
git config user.name "PoolNet lists"
git config user.email "lists@poolnet.online"
git add -A
git commit -qm "lists: snapshot $(date -u +%Y-%m-%dT%H:%MZ)"
GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes" \
  git push --force "git@github.com:$REPO.git" lists
