# Start the work on a task: write its work note once.
# Idempotent: when the note is already there the script says so and exits 0.
set -eu
note="$SVOD_SUBJECT_PATH/work.md"
if [ -f "$note" ]; then
  echo "already started: $note"
  exit 0
fi
printf '# Work on %s (%s)\n' "$SVOD_ID" "${SVOD_KEY:-no key}" > "$note"
echo "started: $note"
