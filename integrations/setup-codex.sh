#!/bin/bash
# Connect svod to Codex: hooks in hooks.json and the skills of this repository.
#
#   integrations/setup-codex.sh [store]
#
# The Codex directory is CODEX_HOME, ~/.codex by default. The original hooks.json is copied to
# hooks.json.bak-svod before each change. The optional store is used by the hooks when a
# session runs outside any store. Running again changes nothing.

set -eu
. "$(dirname "$0")/common.sh"

HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
BASE="$(svod_command "${1:-}")"

register_hooks "$HOME_DIR/hooks.json" "$BASE"
link_skills "$HOME_DIR/skills"

echo
echo "Done. On the next start Codex asks to trust the new hooks: confirm it, untrusted hooks do not run."
