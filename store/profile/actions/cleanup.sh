# Remove the clean worktrees of a record whose card.md says status: done; dirty ones and all branches stay.
# Usage: bash profile/actions/cleanup.sh work/tasks/<name>. Idempotent: a removed worktree is skipped.
# shellcheck source-path=SCRIPTDIR source=_env.sh
. "$(dirname "$0")/_env.sh"

if [ "$(card_field status)" != "done" ]; then
  echo "status is not done in ${CARD#"$SVOD_ROOT"/}: nothing removed" >&2
  exit 1
fi
[ -f "$WORK" ] || exit 0
while IFS= read -r line; do
  name="${line%%:*}"
  dir="${line#*: }"
  path="$(abs "$dir")"
  [ -n "$name" ] && [ -d "$path" ] || continue
  if [ -n "$(git -C "$path" status --porcelain)" ]; then
    echo "$name: $dir has uncommitted changes: kept"
    continue
  fi
  git -C "$(abs "$(service_path "$name")")" worktree remove "$path"
  echo "$name: removed $dir (branch $BRANCH kept)"
done < "$WORK"
