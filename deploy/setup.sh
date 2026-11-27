#!/usr/bin/env bash
# Create a production .env with freshly generated secrets.
#
#   ./deploy/setup.sh --domain atlas.example.org --admin-email you@example.org
#
# Options:
#   --domain NAME          public hostname (DNS A/AAAA record must point at this server); "localhost" for a trial
#   --admin-email EMAIL    first administrator (a random password is generated and shown once)
#   --allowed-ips "CIDRs"  optional space-separated allow-list, e.g. "203.0.113.0/24 198.51.100.7/32"
#   --registry VERSION     use published images ghcr.io/codesphere-u/atlas-osint/{api,web}:VERSION instead of
#                          building on this server (e.g. v0.2.0)
#   --force                replace an existing .env (the old file is kept as .env.bak-<timestamp>)
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/lib.sh"

DOMAIN="" ADMIN_EMAIL="" ALLOWED_IPS="" REGISTRY_VERSION="" FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="${2:-}"; shift 2 ;;
    --allowed-ips) ALLOWED_IPS="${2:-}"; shift 2 ;;
    --registry) REGISTRY_VERSION="${2:-}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

need openssl
need docker
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (docker compose ...)"

if [ -f .env ]; then
  [ "$FORCE" = 1 ] || die ".env already exists. Re-running would replace the encryption key and make existing data unreadable. Use --force only for a fresh installation."
  backup=".env.bak-$(date -u +%Y%m%dT%H%M%SZ)"
  cp -p .env "$backup" && chmod 600 "$backup"
  warn "existing .env saved as $backup"
fi

if [ -z "$DOMAIN" ] && [ -t 0 ]; then read -r -p "Public hostname (e.g. atlas.example.org, or localhost): " DOMAIN; fi
if [ -z "$ADMIN_EMAIL" ] && [ -t 0 ]; then read -r -p "Administrator email: " ADMIN_EMAIL; fi
[ -n "$DOMAIN" ] || die "--domain is required"
[ -n "$ADMIN_EMAIL" ] || die "--admin-email is required"
[[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || die "invalid hostname: $DOMAIN"
[[ "$ADMIN_EMAIL" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]] || die "invalid email: $ADMIN_EMAIL"
if [ -n "$ALLOWED_IPS" ]; then
  for cidr in $ALLOWED_IPS; do
    [[ "$cidr" =~ ^[0-9A-Fa-f:.]+(/[0-9]{1,3})?$ ]] || die "invalid CIDR in --allowed-ips: $cidr"
  done
fi
if [ -n "$REGISTRY_VERSION" ]; then
  [[ "$REGISTRY_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "--registry expects a release tag such as v0.2.0"
fi

if [ "$DOMAIN" != "localhost" ]; then
  if command -v getent >/dev/null 2>&1 && ! getent hosts "$DOMAIN" >/dev/null; then
    warn "$DOMAIN does not resolve yet. Create the DNS record before starting, or the TLS certificate cannot be issued."
  fi
fi

rand_token() { openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'; }
fernet_key() { openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'; }   # 32 bytes, url-safe, padded
admin_password="$(rand_token 18)-$(rand_token 6)"

# Start from the documented template so every optional setting stays visible in .env.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cp .env.example "$tmp"
set_var() { # set_var KEY VALUE – replaces KEY=... or appends it
  KEY="$1" VALUE="$2" awk 'BEGIN{k=ENVIRON["KEY"]; v=ENVIRON["VALUE"]; done=0}
    $0 ~ "^"k"=" { print k"="v; done=1; next } { print }
    END { if (!done) print k"="v }' "$tmp" > "$tmp.new" && mv "$tmp.new" "$tmp"
}
set_var ATLAS_ENV production
set_var ATLAS_DOMAIN "$DOMAIN"
set_var ATLAS_SECRET_KEY "$(rand_token 48)"
set_var ATLAS_ENCRYPTION_KEY "$(fernet_key)"
set_var ATLAS_HASH_KEY "$(rand_token 48)"
set_var POSTGRES_PASSWORD "$(openssl rand -hex 24)"
set_var REDIS_PASSWORD "$(openssl rand -hex 24)"
set_var ATLAS_BOOTSTRAP_ADMIN_EMAIL "$ADMIN_EMAIL"
set_var ATLAS_BOOTSTRAP_ADMIN_PASSWORD "$admin_password"
[ -n "$ALLOWED_IPS" ] && set_var ATLAS_ALLOWED_IPS "\"$ALLOWED_IPS\""
if [ -n "$REGISTRY_VERSION" ]; then
  set_var ATLAS_IMAGE_REPO ghcr.io/codesphere-u/atlas-osint
  set_var ATLAS_VERSION "$REGISTRY_VERSION"
fi

umask 077
mv "$tmp" .env
chmod 600 .env
trap - EXIT
mkdir -p backups && chmod 700 backups

ok "wrote .env (mode 600) with generated secrets"
cat <<MSG

${B}Administrator${N}
  email:    $ADMIN_EMAIL
  password: $admin_password
  This password is shown once. Sign in, then run ./deploy/check.sh --clear-bootstrap-password
  (or change it under Administration) so it no longer sits in .env.

${B}Keep a copy of .env in a password manager now.${N} ATLAS_ENCRYPTION_KEY and ATLAS_HASH_KEY are required to
read the database and every backup; without them the data cannot be recovered.

${B}Next steps${N}
  1. Open ports 80 and 443 (and SSH) in the firewall; nothing else needs to be reachable.
MSG
if [ -n "$REGISTRY_VERSION" ]; then
  echo "  2. docker compose pull && docker compose up -d --no-build"
else
  echo "  2. docker compose up -d --build"
fi
cat <<MSG
  3. ./deploy/check.sh        (waits for the stack and verifies TLS, health, headers and backups)
  4. Open https://$DOMAIN and sign in.
MSG
