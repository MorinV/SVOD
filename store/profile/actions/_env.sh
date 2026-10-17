# Shared environment of the actions, sourced by each: the record, its services and their checkouts.
# Uses SVOD_ROOT, SVOD_ID, SVOD_KEY, SVOD_KIND, SVOD_SERVICES, SVOD_SERVICE_<NAME>, SVOD_SUBJECT_PATH
# when set; otherwise the first argument (work/<kind>/<name>), card.md and svod.yaml fill them in.
set -euo pipefail

SVOD_ROOT="${SVOD_ROOT:-$PWD}"
SVOD_ID="${SVOD_ID:-${1:-}}"
if [ -z "$SVOD_ID" ]; then
  echo "usage: $0 work/<kind>/<name>  (run from the store root)" >&2
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
BRANCH="${SVOD_KEY:+${SVOD_KEY}_}$SLUG"
export SVOD_ROOT SVOD_ID SVOD_SUBJECT_PATH SVOD_SERVICES SVOD_KEY SVOD_KIND SLUG BRANCH
