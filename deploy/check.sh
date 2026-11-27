#!/usr/bin/env bash
# Verify a running deployment: containers healthy, HTTPS, security headers, API readiness, configuration
# hygiene and backups. Exit code is non-zero when a check fails.
#
#   ./deploy/check.sh                            # run all checks (waits up to 5 minutes for the stack)
#   ./deploy/check.sh --clear-bootstrap-password # remove the first-admin password from .env once you have signed in
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/lib.sh"
need docker
need curl
[ -f .env ] || die ".env not found – run ./deploy/setup.sh first"

if [ "${1:-}" = "--clear-bootstrap-password" ]; then
  email="$(env_get ATLAS_BOOTSTRAP_ADMIN_EMAIL)"
  # The account must exist before the password is removed, otherwise nobody could sign in.
  count="$(compose exec -T postgres psql -U atlas -d atlas -tAc "select count(*) from users where role='admin' and email=lower('${email//\'/}')" 2>/dev/null || echo 0)"
  [ "${count//[[:space:]]/}" = "1" ] || die "administrator $email not found in the database yet – start the stack first"
  sed -i.bak -e 's/^ATLAS_BOOTSTRAP_ADMIN_PASSWORD=.*/ATLAS_BOOTSTRAP_ADMIN_PASSWORD=/' .env && rm -f .env.bak
  compose up -d api worker >/dev/null
  ok "bootstrap password removed from .env; api and worker restarted"
  exit 0
fi

FAILED=0
fail() { printf '%sFAIL%s  %s\n' "$R" "$N" "$*"; FAILED=$((FAILED + 1)); }
DOMAIN="$(env_get ATLAS_DOMAIN)"; DOMAIN="${DOMAIN:-localhost}"
HTTPS_PORT="$(env_get ATLAS_HTTPS_PORT)"; HTTPS_PORT="${HTTPS_PORT:-443}"
BASE="https://$DOMAIN"; [ "$HTTPS_PORT" = 443 ] || BASE="$BASE:$HTTPS_PORT"
CURL=(curl -sS --max-time 15)
# Caddy's internal CA is not in the system trust store; for localhost trials connect to the local port.
if [ "$DOMAIN" = localhost ]; then CURL+=(-k); fi

info "Containers"
deadline=$((SECONDS + 300))
services="postgres redis api worker web caddy backup"
while :; do
  pending=""
  for s in $services; do
    cid="$(compose ps -q "$s" 2>/dev/null || true)"
    if [ -z "$cid" ]; then pending="$pending $s(missing)"; continue; fi
    state="$(docker inspect -f '{{.State.Status}}{{if .State.Health}}/{{.State.Health.Status}}{{end}}' "$cid")"
    case "$state" in running/healthy|running) ;; *) pending="$pending $s($state)" ;; esac
  done
  [ -z "$pending" ] && break
  [ $SECONDS -ge $deadline ] && break
  sleep 5
done
for s in $services; do
  cid="$(compose ps -q "$s" 2>/dev/null || true)"
  if [ -z "$cid" ]; then fail "$s is not running"; continue; fi
  state="$(docker inspect -f '{{.State.Status}}{{if .State.Health}}/{{.State.Health.Status}}{{end}}' "$cid")"
  restarts="$(docker inspect -f '{{.RestartCount}}' "$cid")"
  case "$state" in
    running/healthy|running) ok "$s $state${restarts:+ (restarts: $restarts)}" ;;
    *) fail "$s $state – see: docker compose logs --tail=50 $s" ;;
  esac
done

info "HTTPS and application"
if "${CURL[@]}" -o /dev/null "$BASE/healthz"; then
  ok "TLS handshake to $BASE"
else
  fail "cannot reach $BASE over HTTPS (DNS record, firewall ports 80/443, or certificate issuance – see: docker compose logs caddy)"
fi
code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/readyz" || true)"
[ "$code" = 200 ] && ok "API ready (database reachable)" || fail "/readyz returned $code"
headers="$("${CURL[@]}" -D - -o /dev/null "$BASE/login" || true)"
for h in strict-transport-security content-security-policy x-frame-options x-content-type-options referrer-policy; do
  grep -qi "^$h:" <<<"$headers" && ok "header $h" || fail "missing header $h on /login"
done
grep -qi '^server:' <<<"$headers" && warn "a Server header is exposed" || ok "no Server header"
HTTP_PORT="$(env_get ATLAS_HTTP_PORT)"; HTTP_PORT="${HTTP_PORT:-80}"
code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' "http://$DOMAIN:$HTTP_PORT/login" || true)"
case "$code" in 301|302|307|308) ok "HTTP redirects to HTTPS ($code)" ;; *) warn "HTTP request returned $code (expected a redirect to HTTPS)" ;; esac
meta="$("${CURL[@]}" "$BASE/api/v1/meta" || true)"
grep -q '"version"' <<<"$meta" && ok "API metadata: $(grep -o '"version":"[^"]*"' <<<"$meta" | head -1)" || fail "/api/v1/meta did not answer"

info "Configuration"
[ "$(stat -c %a .env 2>/dev/null || stat -f %Lp .env)" = 600 ] && ok ".env permissions 600" || warn ".env should be readable only by its owner: chmod 600 .env"
[ -n "$(env_get ATLAS_BOOTSTRAP_ADMIN_PASSWORD)" ] \
  && warn "ATLAS_BOOTSTRAP_ADMIN_PASSWORD is still set in .env – after signing in run: ./deploy/check.sh --clear-bootstrap-password" \
  || ok "no bootstrap password in .env"
[ "$(env_get ATLAS_ENV)" = production ] && ok "ATLAS_ENV=production" || fail "ATLAS_ENV is not production"
allowed="$(env_get ATLAS_ALLOWED_IPS)"
[ -n "$allowed" ] && ok "access restricted to: $allowed" \
  || warn "the application is reachable from any IP; consider ATLAS_ALLOWED_IPS (ATLAS has no MFA yet)"

info "Backups"
dir="$(env_get ATLAS_BACKUP_DIR)"; dir="${dir:-./backups}"
latest_dump() { find "$dir" -maxdepth 1 -name 'atlas-*.dump' -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -n1 | cut -d' ' -f2-; }
latest="$(latest_dump)"
# A fresh stack writes its first dump right after the API becomes healthy; give it a minute.
for _ in $(seq 1 12); do [ -n "$latest" ] && break; sleep 5; latest="$(latest_dump)"; done
if [ -n "$latest" ]; then
  age_h=$(( ( $(date +%s) - $(stat -c %Y "$latest" 2>/dev/null || stat -f %m "$latest") ) / 3600 ))
  interval="$(env_get ATLAS_BACKUP_INTERVAL_HOURS)"; interval="${interval:-24}"
  if [ "$age_h" -le $((interval + 2)) ]; then ok "latest backup $(basename "$latest") (${age_h}h old)"
  else fail "latest backup is ${age_h}h old – see: docker compose logs backup"; fi
  echo "      copy $dir off this server regularly (e.g. restic, rsync, object storage)"
else
  fail "no backup in $dir yet – see: docker compose logs backup"
fi

echo
if [ "$FAILED" -gt 0 ]; then
  printf '%s%d check(s) failed%s, %d warning(s)\n' "$R" "$FAILED" "$N" "${WARNINGS:-0}"; exit 1
fi
printf '%sAll checks passed%s, %d warning(s)\n' "$G" "$N" "${WARNINGS:-0}"
