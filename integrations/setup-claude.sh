#!/bin/bash
# Connect svod to Claude Code: hooks in settings.json and the skills of this repository.
#
#   integrations/setup-claude.sh [store]
#
# The Claude Code directory is CLAUDE_CONFIG_DIR, ~/.claude by default. The original
# settings.json is copied to settings.json.bak-svod before each change. The optional
# store is used by the hooks when a session runs outside any store. Running again changes
# nothing.

set -eu
. "$(dirname "$0")/common.sh"

HOME_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
BASE="$(svod_command "${1:-}")"

register_hooks "$HOME_DIR/settings.json" "$BASE"
link_skills "$HOME_DIR/skills"

echo
echo "Done. New Claude Code sessions run the svod hooks."
