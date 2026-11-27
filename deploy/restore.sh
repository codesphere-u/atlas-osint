#!/usr/bin/env bash
# Restore the database from a backup made by the backup service or deploy/backup.sh.
#
#   ./deploy/restore.sh backups/atlas-20261127T020000Z.dump [--yes]
#
# The current database is dumped first (label "pre-restore"), then replaced. The .env in use must hold the same
# ATLAS_ENCRYPTION_KEY and ATLAS_HASH_KEY as the installation that made the backup, or the data stays unreadable.
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/lib.sh"
need docker
file="${1:-}"; [ -n "$file" ] || die "usage: ./deploy/restore.sh <backup.dump> [--yes]"
[ -f "$file" ] || die "file not found: $file"
compose exec -T postgres pg_restore --list < "$file" > /dev/null || die "$file is not a valid pg_dump custom-format archive"

if [ "${2:-}" != "--yes" ]; then
  printf '%sThis replaces ALL current data with %s.%s Type RESTORE to continue: ' "$Y" "$file" "$N"
  read -r answer
  [ "$answer" = RESTORE ] || die "aborted"
fi

info "Safety backup of the current database"
"$(dirname "$0")/backup.sh" pre-restore >/dev/null && ok "saved (label pre-restore)"

info "Stopping application services"
compose stop api worker web backup >/dev/null

info "Recreating database"
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U atlas -d postgres -q \
  -c "DROP DATABASE IF EXISTS atlas WITH (FORCE);" -c "CREATE DATABASE atlas OWNER atlas;"
compose exec -T postgres psql -v ON_ERROR_STOP=1 -U atlas -d atlas -q -c "REVOKE ALL ON SCHEMA public FROM PUBLIC;"

info "Restoring $file"
compose exec -T postgres pg_restore -U atlas -d atlas --no-owner --exit-on-error < "$file"
ok "restore complete"

info "Starting application services (migrations run automatically if the backup is older than the code)"
compose up -d >/dev/null
ok "started – run ./deploy/check.sh to verify"
