#!/usr/bin/env bash
# Upgrade a running installation. A backup is taken first; database migrations run when the API starts.
#
#   ./deploy/upgrade.sh                # source install: git pull + rebuild
#   ./deploy/upgrade.sh v0.3.0         # image install (ATLAS_IMAGE_REPO set): switch to that release
#
# Rollback: migrations are forward-only in production. To go back, restore the "pre-upgrade" backup with
# ./deploy/restore.sh and run the previous version (git checkout <tag> or ATLAS_VERSION=<tag>).
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/lib.sh"
need docker
[ -f .env ] || die ".env not found"

info "Backup before upgrading"
"$(dirname "$0")/backup.sh" pre-upgrade >/dev/null && ok "saved (label pre-upgrade)"

if [ -n "$(env_get ATLAS_IMAGE_REPO)" ]; then
  version="${1:-}"
  [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "usage: ./deploy/upgrade.sh vX.Y.Z (current: $(env_get ATLAS_VERSION))"
  sed -i.bak -e "s/^ATLAS_VERSION=.*/ATLAS_VERSION=$version/" .env && rm -f .env.bak
  grep -q '^ATLAS_VERSION=' .env || echo "ATLAS_VERSION=$version" >> .env
  info "Pulling $version images"
  compose pull api web
  compose up -d --no-build
else
  need git
  [ -z "$(git status --porcelain --untracked-files=no)" ] || die "tracked files have local changes; commit or stash them first"
  info "Updating source ($(git rev-parse --short HEAD))"
  git pull --ff-only
  info "Building images ($(git rev-parse --short HEAD))"
  compose build api web
  compose up -d
fi
"$(dirname "$0")/check.sh"
