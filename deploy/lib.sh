# shellcheck shell=bash
# Shared helpers for the deploy scripts (sourced, not executed).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [ -t 1 ]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; N=$'\e[0m'; else B=; G=; Y=; R=; N=; fi
info() { printf '%s==>%s %s\n' "$B" "$N" "$*"; }
ok() { printf '%s  ok%s  %s\n' "$G" "$N" "$*"; }
warn() { printf '%swarn%s  %s\n' "$Y" "$N" "$*"; WARNINGS=$((${WARNINGS:-0} + 1)); }
die() { printf '%serror%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed"; }
compose() { docker compose "$@"; }
env_get() { # value of KEY from .env (empty if missing)
  [ -f .env ] || return 0
  { grep -E "^$1=" .env || true; } | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}
