# Run the checks of every service in its worktree (work.yaml) or checkout; checks.md on success, checks.log always.
# Usage: bash profile/actions/checks.sh work/<kind>/<name> [--check]. The command: SVOD_CHECKS_<NAME>, else found by the files.
# --check writes nothing: it runs the checks again with their output on stdout and exits with their result, for the
# command gate of the checks step; a record naming no services passes, one without checks.md fails without running.
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

check=""
if has_option --check; then check=1; fi
log="$SVOD_SUBJECT_PATH/checks.log"
report="$SVOD_SUBJECT_PATH/checks.md"
if [ -z "$SVOD_SERVICES" ]; then
  if [ -n "$check" ]; then
    echo "no services declared in ${CARD#"$SVOD_ROOT"/}: nothing to check"
    exit 0
  fi
  echo "no services: name them in ${CARD#"$SVOD_ROOT"/} as services: [app]" >&2
  exit 1
fi
if [ -n "$check" ]; then
  if [ ! -f "$report" ]; then
    echo "not checked yet: run bash profile/actions/checks.sh $SVOD_ID"
    exit 1
  fi
  exec 3>&1
else
  : > "$log"
  rm -f "$report"
  exec 3>>"$log"
fi
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
  echo "== $name @ $commit: $cmd" >&3
  if (cd "$path" && bash -c "$cmd") >&3 2>&1; then
    lines+=("- $name @ $commit: \`$cmd\` passed")
  elif [ -n "$check" ]; then
    echo "$name: \`$cmd\` failed" >&2
    failed=1
  else
    echo "$name: \`$cmd\` failed, see ${log#"$SVOD_ROOT"/}" >&2
    failed=1
  fi
done
if [ "$failed" != 0 ]; then
  exit 1
fi
if [ -n "$check" ]; then
  printf '%s\n' "${lines[@]}"
  exit 0
fi
{ echo "# Checks"; echo; printf '%s\n' "${lines[@]}"; } > "$report"
cat "$report"
