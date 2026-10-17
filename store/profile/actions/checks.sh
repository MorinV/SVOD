# Run the checks of every service in its worktree (work.yaml) or checkout; checks.md on success, checks.log always.
# Usage: bash profile/actions/checks.sh work/<kind>/<name>. The command: SVOD_CHECKS_<NAME>, else found by the files.
# shellcheck source-path=SCRIPTDIR source=_env.sh
. "$(dirname "$0")/_env.sh"

# check_command <name> <dir>: SVOD_CHECKS_<NAME>, else the usual command of the project in dir.
check_command() {
  local var
  var="SVOD_CHECKS_$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"
  if [ -n "${!var:-}" ]; then printf '%s\n' "${!var}"
  elif [ -f "$2/Makefile" ] && grep -q '^check:' "$2/Makefile"; then echo "make check"
  elif [ -f "$2/Makefile" ] && grep -q '^test:' "$2/Makefile"; then echo "make test"
  elif [ -f "$2/package.json" ]; then echo "npm test"
  elif [ -f "$2/go.mod" ]; then echo "go test ./..."
  elif [ -f "$2/pyproject.toml" ] || [ -d "$2/tests" ]; then echo "python3 -m pytest -q"
  fi
}

if [ -z "$SVOD_SERVICES" ]; then
  echo "no services: name them in ${CARD#"$SVOD_ROOT"/} as services: [app]" >&2
  exit 1
fi
log="$SVOD_SUBJECT_PATH/checks.log"
report="$SVOD_SUBJECT_PATH/checks.md"
: > "$log"
rm -f "$report"
lines=()
failed=0
for name in $SVOD_SERVICES; do
  dir="$(worktree_of "$name")"
  dir="${dir:-$(service_path "$name")}"
  path="$(abs "$dir")"
  cmd="$(check_command "$name" "$path")"
  if [ -z "$cmd" ]; then
    echo "$name: no check command: set SVOD_CHECKS_$(printf '%s' "$name" | tr 'a-z-' 'A-Z_')" >&2
    failed=1; continue
  fi
  if [ -n "$(git -C "$path" status --porcelain)" ]; then
    echo "$name: $dir has uncommitted changes: commit them first" >&2
    failed=1; continue
  fi
  commit="$(git -C "$path" rev-parse --short HEAD)"
  echo "== $name @ $commit: $cmd" >> "$log"
  if (cd "$path" && bash -c "$cmd") >> "$log" 2>&1; then
    lines+=("- $name @ $commit: \`$cmd\` passed")
  else
    echo "$name: \`$cmd\` failed, see ${log#"$SVOD_ROOT"/}" >&2
    failed=1
  fi
done
if [ "$failed" != 0 ]; then
  exit 1
fi
{ echo "# Checks"; echo; printf '%s\n' "${lines[@]}"; } > "$report"
cat "$report"
