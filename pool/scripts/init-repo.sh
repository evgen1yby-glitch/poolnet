#!/usr/bin/env bash
# One-time setup after creating the empty GitHub repository:
#   ./scripts/init-repo.sh <owner/repo>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <owner/repo>" >&2
  exit 1
fi

REPO="$1"
grep -rl 'OWNER/REPO' --include='*.md' --include='*.yml' --include='*.html' --include='*.js' \
  --exclude-dir=node_modules --exclude-dir=.git . | while read -r f; do
  sed -i "s|OWNER/REPO|${REPO}|g" "$f"
  echo "patched $f"
done

git remote add origin "https://github.com/${REPO}.git" 2>/dev/null || git remote set-url origin "https://github.com/${REPO}.git"
git push -u origin main
echo "pushed to https://github.com/${REPO}"
