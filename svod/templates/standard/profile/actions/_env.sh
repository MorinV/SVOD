# Shared environment of the actions, sourced by each: the record, its services and their checkouts.
# The record is the first argument not starting with -- (work/<kind>/<name>, relative to the store
# root, which is the working directory); the options go to OPTIONS. svod do passes no record: it
# sets SVOD_ACTION=<action>, SVOD_ROOT, SVOD_ID, SVOD_KEY, SVOD_KIND, SVOD_PIPELINE, SVOD_SERVICES,
# SVOD_SERVICE_<NAME>, SVOD_SUBJECT_PATH, which are used then. The argument wins over inherited
# variables: when it names a record other than SVOD_ID, or SVOD_ROOT is not the working directory
# (a nested run: checks running tests that run these scripts on another store), every inherited
# record variable, SVOD_SERVICE_<NAME> and SVOD_FM_<NAME> is dropped and found again from the
# argument, card.md and svod.yaml.
#
# Names: the worktree of service <service> for record work/<kind>/<name> of pipeline <pipeline>
# is <directory holding the service checkout>/<service>-<pipeline>-<name>, on branch
# <pipeline>/<name>; work.yaml lists it relative to the store root. <pipeline> is SVOD_PIPELINE,
# else <kind> without its final s (tasks -> task, features -> feature, research -> research).
set -euo pipefail

RECORD=""
OPTIONS=""
for arg in "$@"; do
  case "$arg" in
    --*) OPTIONS="$OPTIONS $arg" ;;
    *) [ -n "$RECORD" ] || RECORD="$arg" ;;
  esac
done
RECORD="${RECORD#./}"
RECORD="${RECORD%/}"

# has_option <--name>: whether the option was given.
has_option() {
  case "$OPTIONS " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

HERE="$(pwd -P)"
stale=""
if [ -n "${SVOD_ROOT:-}" ] && [ "$(cd "$SVOD_ROOT" 2>/dev/null && pwd -P)" != "$HERE" ]; then
  stale=1
fi
if [ -n "$RECORD" ] && [ -n "${SVOD_ID:-}" ] && [ "$RECORD" != "$SVOD_ID" ]; then
  stale=1
fi
if [ -n "$stale" ]; then
  unset SVOD_ACTION SVOD_ROOT SVOD_ID SVOD_KEY SVOD_KIND SVOD_PIPELINE SVOD_SERVICES SVOD_SUBJECT_PATH
  for name in $(compgen -e); do
    case "$name" in SVOD_SERVICE_*|SVOD_FM_*) unset "$name" ;; esac
  done
fi

SVOD_ROOT="${SVOD_ROOT:-$HERE}"
SVOD_ID="${RECORD:-${SVOD_ID:-}}"
if [ -z "$SVOD_ID" ]; then
  echo "usage: $0 work/<kind>/<name> [options]  (run from the store root)" >&2
  exit 2
fi
SVOD_SUBJECT_PATH="${SVOD_SUBJECT_PATH:-$SVOD_ID}"
case "$SVOD_SUBJECT_PATH" in /*) ;; *) SVOD_SUBJECT_PATH="$SVOD_ROOT/$SVOD_SUBJECT_PATH" ;; esac
CARD="$SVOD_SUBJECT_PATH/card.md"
WORK="$SVOD_SUBJECT_PATH/work.yaml"

# card_field <name>: a frontmatter field of card.md; a [a, b] list comes out as "a b".
card_field() {
  [ -f "$CARD" ] || return 0
  awk -v k="$1" '
    NR == 1 { if ($0 != "---") exit; next }
    $0 == "---" { exit }
    { i = index($0, ":"); if (i && substr($0, 1, i - 1) == k) {
        v = substr($0, i + 1); sub(/[ \t]+#.*/, "", v); gsub(/[][,]/, " ", v)
        gsub(/^[ \t]+|[ \t]+$/, "", v); gsub(/[ \t]+/, " ", v); print v; exit } }' "$CARD"
}

# abs <path>: the path itself when absolute, else relative to the store root.
abs() {
  case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s\n' "$SVOD_ROOT/$1" ;; esac
}

# rel <path>: an absolute path without symbolic links, relative to the store root.
rel() {
  local base target up=""
  base="$(cd "$SVOD_ROOT" && pwd -P)"
  target="$1"
  while [ "$base" != / ] && [ "$target" != "$base" ] && [ "${target#"$base"/}" = "$target" ]; do
    base="$(dirname "$base")"
    up="../$up"
  done
  if [ "$target" = "$base" ]; then printf '%s\n' "${up%/}"
  elif [ "$base" = / ]; then printf '%s%s\n' "$up" "${target#/}"
  else printf '%s%s\n' "$up" "${target#"$base"/}"
  fi
}

# service_path <name>: checkout of a service as configured, relative to the store root or absolute:
# SVOD_SERVICE_<NAME>, else services.<name> of svod.yaml, else ../<name>.
service_path() {
  local var path
  var="SVOD_SERVICE_$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"
  path="${!var:-}"
  if [ -z "$path" ] && [ -f "$SVOD_ROOT/svod.yaml" ]; then
    path=$(awk -v k="$1" '
      /^services:/ { s = 1; next }
      s && /^[^ \t#]/ { exit }
      s { line = $0; sub(/[ \t]+#.*/, "", line); i = index(line, ":")
          if (i) { n = substr(line, 1, i - 1); gsub(/[ \t]/, "", n)
                   if (n == k) { v = substr(line, i + 1); gsub(/^[ \t]+|[ \t]+$/, "", v); print v; exit } } }' \
      "$SVOD_ROOT/svod.yaml")
  fi
  printf '%s\n' "${path:-../$1}"
}

# service_dir <name>: absolute path of the service checkout without symbolic links; fails when missing.
service_dir() {
  (cd "$(abs "$(service_path "$1")")" 2>/dev/null && pwd -P)
}

# worktree_of <name>: the worktree of the service recorded in work.yaml, or nothing.
worktree_of() {
  [ -f "$WORK" ] || return 0
  awk -v k="$1" 'index($0, k ": ") == 1 { print substr($0, length(k) + 3); exit }' "$WORK"
}

SVOD_SERVICES="${SVOD_SERVICES:-$(card_field services)}"
SVOD_SERVICES="${SVOD_SERVICES//,/ }"
SVOD_KEY="${SVOD_KEY:-$(card_field key)}"
SVOD_KIND="${SVOD_KIND:-$(card_field kind)}"
SLUG="$(basename "$SVOD_ID")"
if [ -z "${SVOD_PIPELINE:-}" ]; then
  SVOD_PIPELINE="$(basename "$(dirname "$SVOD_ID")")"
  SVOD_PIPELINE="${SVOD_PIPELINE%s}"
fi
BRANCH="$SVOD_PIPELINE/$SLUG"
export SVOD_ROOT SVOD_ID SVOD_SUBJECT_PATH SVOD_SERVICES SVOD_KEY SVOD_KIND SVOD_PIPELINE SLUG BRANCH
