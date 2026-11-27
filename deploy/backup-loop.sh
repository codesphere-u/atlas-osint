#!/bin/sh
# Runs inside the "backup" service (postgres:16-alpine): a pg_dump every INTERVAL_HOURS, keeping KEEP_DAYS days.
set -eu
umask 077
INTERVAL_HOURS="${INTERVAL_HOURS:-24}"
KEEP_DAYS="${KEEP_DAYS:-14}"
case "$INTERVAL_HOURS" in ''|*[!0-9]*|0) echo "INTERVAL_HOURS must be a positive integer" >&2; exit 1 ;; esac
case "$KEEP_DAYS" in ''|*[!0-9]*|0) echo "KEEP_DAYS must be a positive integer" >&2; exit 1 ;; esac

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  tmp="/backups/.atlas-${stamp}.dump.partial"
  if pg_dump --format=custom --compress=6 --no-owner --file="$tmp"; then
    mv "$tmp" "/backups/atlas-${stamp}.dump"
    echo "{\"event\":\"backup_completed\",\"file\":\"atlas-${stamp}.dump\",\"bytes\":$(wc -c < "/backups/atlas-${stamp}.dump")}"
  else
    rm -f "$tmp"
    echo "{\"event\":\"backup_failed\",\"time\":\"${stamp}\"}" >&2
  fi
  find /backups -maxdepth 1 -name 'atlas-*.dump' -type f -mtime "+${KEEP_DAYS}" -print -delete \
    | sed 's/^/{"event":"backup_pruned","file":"/; s/$/"}/'
  sleep "$((INTERVAL_HOURS * 3600))"
done
