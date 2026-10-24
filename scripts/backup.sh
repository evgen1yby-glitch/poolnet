#!/bin/sh
# Back up the hub database and both pool state directories.
#
# SQLite's `.backup` takes a consistent snapshot while the service is running;
# copying hub.db directly can capture a torn write and a database that fails
# `PRAGMA integrity_check` on restore. Keep 14 daily copies and nothing else.
set -eu

ROOT=${POOLNET_ROOT:-/home/dev/poolnet}
DEST=${POOLNET_BACKUP_DIR:-/var/backups/poolnet}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

install -d -m 700 "$DEST"
install -d -m 700 "$DEST/$STAMP"

sqlite3 "$ROOT/hub/data/hub.db" ".backup '$DEST/$STAMP/hub.db'"
sqlite3 "$DEST/$STAMP/hub.db" "PRAGMA integrity_check;" | grep -qx ok
tar -C "$ROOT" -czf "$DEST/$STAMP/pool-state.tar.gz" pool/.state pool/data
chmod 600 "$DEST/$STAMP/hub.db" "$DEST/$STAMP/pool-state.tar.gz"

# Retention: remove complete backup directories older than 14 days.
find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
echo "backup: $DEST/$STAMP"
