# Start a task: card.md when missing, then a git worktree per service on branch <KEY>_<slug>, listed in work.yaml.
# Usage: bash profile/actions/start-task.sh work/tasks/<name>. Idempotent: existing files and worktrees are kept.
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
  repo="$(service_path "$name")"
  dir="$(dirname "$repo")/$(basename "$repo")-$BRANCH"
  if [ ! -d "$(abs "$dir")" ]; then
    if git -C "$(abs "$repo")" rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
      git -C "$(abs "$repo")" worktree add "$(abs "$dir")" "$BRANCH"
    else
      git -C "$(abs "$repo")" worktree add -b "$BRANCH" "$(abs "$dir")"
    fi
  fi
  if [ -z "$(worktree_of "$name")" ]; then
    printf '%s: %s\n' "$name" "$dir" >> "$WORK"
  fi
  echo "$name: $dir on $BRANCH"
done
