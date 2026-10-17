#!/bin/bash
# Connect svod to Codex: hooks in hooks.json and the skills, those of the store when it has its
# own, else of the copy kept by the store, else of this repository.
#
#   integrations/setup-codex.sh [--engine <clone>] --project <store>
#   integrations/setup-codex.sh [--engine <clone>] [store]
#
# With --project the hooks go to the project layer of the store, <store>/.codex/hooks.json, and
# the skills to <store>/.codex/skills: Codex reads the hooks.json next to each config layer, so
# they run only in sessions started in that store, with the store as --root. Without it they go
# to the Codex directory, CODEX_HOME, ~/.codex by default; the optional store is then the one
# the hooks use when a session runs outside any store. The original hooks.json is copied to
# hooks.json.bak-svod before each change. --engine puts that Svod clone on PYTHONPATH of the
# hooks; the line "-> engine:" names the engine they import. Running again changes nothing.

set -eu
# shellcheck source-path=SCRIPTDIR source=common.sh
. "$(dirname "$0")/common.sh"

PROJECT_FLAG="--project"
PROJECT_DIR=".codex"
HOOKS_FILE="hooks.json"
SKILLS_DIR="skills"
USAGE="usage: setup-codex.sh [$ENGINE_FLAG <clone>] $PROJECT_FLAG <store> | setup-codex.sh [$ENGINE_FLAG <clone>] [store]"

# Prints the usage and stops with the usage exit code.
usage() {
    echo "$USAGE" >&2
    exit "$EXIT_USAGE"
}

engine_flag "$@" || usage
set -- "${ARGS[@]+"${ARGS[@]}"}"

PROJECT=""
case "${1:-}" in
    "$PROJECT_FLAG") [ "$#" -eq 2 ] || usage; PROJECT=1; STORE="$2" ;;
    -*) usage ;;
    *) [ "$#" -le 1 ] || usage; STORE="${1:-}" ;;
esac

BASE="$(svod_command "$STORE")"
if [ -n "$PROJECT" ]; then
    HOME_DIR="$(cd "$STORE" && pwd)/$PROJECT_DIR"
else
    HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
    [ -n "$STORE" ] || echo "Note: without a store argument the hooks guard only sessions started inside a store; to guard work directories next to a store, run again with its path." >&2
fi

show_engine
register_hooks "$HOME_DIR/$HOOKS_FILE" "$BASE"
link_skills "$HOME_DIR/$SKILLS_DIR" "$STORE"

echo
if [ -n "$PROJECT" ]; then
    echo "Done. Codex sessions started in $(dirname "$HOME_DIR") run the svod hooks once the project is trusted; on the next start Codex asks to trust the new hooks: confirm it, untrusted hooks do not run."
else
    echo "Done. On the next start Codex asks to trust the new hooks: confirm it, untrusted hooks do not run."
fi
