#!/bin/bash
# Connect svod to Codex: hooks in hooks.json and the skills, those of the store when it has its
# own, else of the copy kept by the store, else of this repository.
#
#   integrations/setup-codex.sh [--engine <clone>] [store]
#
# The Codex directory is CODEX_HOME, ~/.codex by default. The original hooks.json is copied to
# hooks.json.bak-svod before each change. The optional store is used by the hooks when a
# session runs outside any store. --engine puts that Svod clone on PYTHONPATH of the hooks; the
# line "-> engine:" names the engine they import. Running again changes nothing.

set -eu
# shellcheck source-path=SCRIPTDIR source=common.sh
. "$(dirname "$0")/common.sh"

USAGE="usage: setup-codex.sh [$ENGINE_FLAG <clone>] [store]"

# Prints the usage and stops with the usage exit code.
usage() {
    echo "$USAGE" >&2
    exit "$EXIT_USAGE"
}

engine_flag "$@" || usage
set -- "${ARGS[@]+"${ARGS[@]}"}"
[ "$#" -le 1 ] || usage

HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
BASE="$(svod_command "${1:-}")"
[ -n "${1:-}" ] || echo "Note: without a store argument the hooks guard only sessions started inside a store; to guard work directories next to a store, run again with its path." >&2

show_engine
register_hooks "$HOME_DIR/hooks.json" "$BASE"
link_skills "$HOME_DIR/skills" "${1:-}"

echo
echo "Done. On the next start Codex asks to trust the new hooks: confirm it, untrusted hooks do not run."
