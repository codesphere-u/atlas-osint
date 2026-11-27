#!/usr/bin/env bash
# Take a backup now (in addition to the scheduled ones):  ./deploy/backup.sh [label]
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/lib.sh"
need docker
label="${1:-manual}"
[[ "$label" =~ ^[A-Za-z0-9_-]+$ ]] || die "label may contain letters, digits, - and _ only"
dir="$(env_get ATLAS_BACKUP_DIR)"; dir="${dir:-./backups}"
mkdir -p "$dir" && chmod 700 "$dir"
file="$dir/atlas-$(date -u +%Y%m%dT%H%M%SZ)-$label.dump"
umask 077
info "pg_dump → $file"
if compose exec -T postgres pg_dump -U atlas -d atlas --format=custom --compress=6 --no-owner > "$file.partial"; then
  mv "$file.partial" "$file"
  ok "backup written ($(du -h "$file" | cut -f1))"
  echo "$file"
else
  rm -f "$file.partial"
  die "pg_dump failed – is the stack running? (docker compose ps)"
fi
