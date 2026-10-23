# Start a task: create a missing record, then a worktree per service with its full encoded record identity; preserve paths already listed in work.yaml.
# Usage: bash profile/actions/start-task.sh <record>. Idempotent: existing files and worktrees are kept.
# New worktree: <service>-<pipeline>-<encoded-record-id> in the directory holding the service
# checkout (its absolute path, so a store inside the service gets it next to the checkout, never inside);
# work.yaml lists it as "<service>: <path relative to the store root>", e.g. "app: ../app-task-login".
# shellcheck source-path=SCRIPTDIR source=_env.sh
. "$(dirname "$0")/_env.sh"

if [ ! -f "$CARD" ]; then
  # The record from the skeletons of profile/records/<pipeline>/ (the template ships card.md).
  # Infer physical owner only from an approved standard container path.
  parent="${SVOD_FM_PARENT:-}"
  case "$(dirname "$SVOD_ID")" in
    work/features/*/tasks|work/projects/*/tasks|work/projects/*/features/*/tasks|\
    work/features/*/research|work/projects/*/research|work/projects/*/features/*/research)
      parent="$(dirname "$(dirname "$SVOD_ID")")" ;;
  esac
  svod_cli --root "$SVOD_ROOT" record new "$SVOD_PIPELINE" "$SLUG" --kind "$SVOD_KIND" \
    --services "${SVOD_SERVICES// /,}" --key "$SVOD_KEY" --parent "$parent"
  if [ ! -f "$CARD" ]; then
    echo "no ${CARD#"$SVOD_ROOT"/}: create the record with svod record new first" >&2
    exit 1
  fi
fi

if [ -z "$SVOD_SERVICES" ]; then
  echo "no services: name them in ${CARD#"$SVOD_ROOT"/} as services: [app]" >&2
  exit 1
fi

for name in $SVOD_SERVICES; do
  if ! repo="$(service_dir "$name")"; then
    echo "$name: no checkout at $(service_path "$name"): set services.$name in svod.yaml" >&2
    exit 1
  fi
  dir="$(worktree_of "$name")"
  if [ -n "$dir" ]; then
    path="$(abs "$dir")"
  else
    path="$(dirname "$repo")/$name-$SVOD_PIPELINE-$WORK_SLUG"
    dir="$(rel "$path")"
  fi
  if [ ! -d "$path" ]; then
    if git -C "$repo" rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
      git -C "$repo" worktree add "$path" "$BRANCH"
    else
      git -C "$repo" worktree add -b "$BRANCH" "$path"
    fi
  fi
  if [ -z "$(worktree_of "$name")" ]; then
    printf '%s: %s\n' "$name" "$dir" >> "$WORK"
  fi
  echo "$name: $dir on $BRANCH"
done
