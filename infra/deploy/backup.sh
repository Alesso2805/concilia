#!/bin/sh
# Daily pg_dump as concilia_backup (read-only, BYPASSRLS), kept BACKUP_KEEP_DAYS days.
# Restore: docs/DEPLOY.md, "Backups".
set -eu

while true; do
    stamp=$(date -u +%Y%m%dT%H%M%SZ)
    if pg_dump --format=custom --no-owner --no-privileges --file "/backups/concilia-$stamp.dump.tmp"; then
        mv "/backups/concilia-$stamp.dump.tmp" "/backups/concilia-$stamp.dump"
        echo "backup concilia-$stamp.dump written"
    else
        rm -f "/backups/concilia-$stamp.dump.tmp"
        echo "backup failed" >&2
    fi
    find /backups -name 'concilia-*.dump' -mtime +"$BACKUP_KEEP_DAYS" -delete
    sleep 86400
done
