#!/bin/sh
# Prove that the newest backup is restorable, not merely present.
# Restores into a throwaway directory; never touches the live data.
set -eu

DEST=${POOLNET_BACKUP_DIR:-/var/backups/poolnet}
SRC=${1:-$(find "$DEST" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)}
[ -n "$SRC" ] || { echo "no backup in $DEST" >&2; exit 1; }
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

sqlite3 "$SRC/hub.db" ".backup '$TMP/hub.db'"
sqlite3 "$TMP/hub.db" "PRAGMA integrity_check;" | grep -qx ok
nodes=$(sqlite3 "$TMP/hub.db" "SELECT COUNT(*) FROM nodes;")
subs=$(sqlite3 "$TMP/hub.db" "SELECT COUNT(*) FROM subscription_tokens;")
tar -xzf "$SRC/pool-state.tar.gz" -C "$TMP"
test -s "$TMP/pool/.state/pool.json.gz"
echo "restore-ok nodes=$nodes subscriptions=$subs source=$SRC"
