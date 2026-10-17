# Start a task: card.md when missing, then a git worktree per service on branch <pipeline>/<name>, listed in work.yaml.
# Usage: bash profile/actions/start-task.sh work/tasks/<name>. Idempotent: existing files and worktrees are kept.
# The worktree of service <service> is <service>-<pipeline>-<name> in the directory holding the service
# checkout (its absolute path, so a store inside the service gets it next to the checkout, never inside);
# work.yaml lists it as "<service>: <path relative to the store root>", e.g. "app: ../app-task-login".
# shellcheck source-path=SCRIPTDIR source=_env.sh
. "$(dirname "$0")/_env.sh"

mkdir -p "$SVOD_SUBJECT_PATH"
if [ ! -f "$CARD" ]; then
  list="${SVOD_SERVICES// /, }"
  cat > "$CARD" <<EOF
---
type: card
kind: ${SVOD_KIND:-task}
key: ${SVOD_KEY}
services: [${list}]
parent:
tags: []
status: open
---

# ${SLUG}

## Description

## Acceptance
EOF
  echo "wrote ${CARD#"$SVOD_ROOT"/}"
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
    path="$(dirname "$repo")/$name-$SVOD_PIPELINE-$SLUG"
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
