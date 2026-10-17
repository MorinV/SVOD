# Print a pull request description from card.md, contract.md and checks.md of the record; writes nothing.
# Usage: bash profile/actions/pr.sh work/tasks/<name>. Paste the output into the PR of every service.
# shellcheck source-path=SCRIPTDIR source=_env.sh
. "$(dirname "$0")/_env.sh"

# body <file>: the markdown without frontmatter, its first heading and HTML comments.
body() {
  [ -f "$1" ] || return 0
  awk '
    NR == 1 && $0 == "---" { front = 1; next }
    front { if ($0 == "---") front = 0; next }
    !title && /^# / { title = 1; next }
    /<!--/ { comment = 1 }
    comment { if (/-->/) comment = 0; next }
    { print }' "$1" | cat -s
}

title="$(grep -m1 '^# ' "$CARD" 2>/dev/null | sed 's/^# //' || true)"
echo "${SVOD_KEY:+$SVOD_KEY: }${title:-$SLUG}"
echo
echo "Record: $SVOD_ID; branch: $BRANCH"
body "$CARD"
body "$SVOD_SUBJECT_PATH/contract.md"
if [ -f "$SVOD_SUBJECT_PATH/checks.md" ]; then
  echo
  body "$SVOD_SUBJECT_PATH/checks.md"
fi
