#!/bin/bash
# Connect svod to Claude Code: hooks in settings.json and the skills, those of the store when it
# has its own, else of the copy kept by the store, else of this repository.
#
#   integrations/setup-claude.sh [--engine <clone>] --project <store>
#   integrations/setup-claude.sh [--engine <clone>] [store]
#
# With --project the hooks go to the project settings of the store, <store>/.claude/settings.json,
# and the skills to <store>/.claude/skills: they run only in sessions started in that store,
# with the store as --root. Without it they go to the Claude Code directory, CLAUDE_CONFIG_DIR,
# ~/.claude by default, and run in every project of the user; the optional store is then the
# one the hooks use when a session runs outside any store. --engine puts that Svod clone on
# PYTHONPATH of the hooks; the line "-> engine:" names the engine they import. The original
# settings.json is copied to settings.json.bak-svod before each change. Running again changes
# nothing.

set -eu
# shellcheck source-path=SCRIPTDIR source=common.sh
. "$(dirname "$0")/common.sh"

PROJECT_FLAG="--project"
PROJECT_DIR=".claude"
SETTINGS_FILE="settings.json"
SKILLS_DIR="skills"
USAGE="usage: setup-claude.sh [$ENGINE_FLAG <clone>] $PROJECT_FLAG <store> | setup-claude.sh [$ENGINE_FLAG <clone>] [store]"

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
    HOME_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
    echo "Warning: the hooks go to $HOME_DIR/$SETTINGS_FILE and run on every tool call in every project of this user; to limit them to one store, run with $PROJECT_FLAG <store>." >&2
    [ -n "$STORE" ] || echo "Note: without a store argument the hooks guard only sessions started inside a store; to guard work directories next to a store, run again with its path." >&2
fi

show_engine
register_hooks "$HOME_DIR/$SETTINGS_FILE" "$BASE"
link_skills "$HOME_DIR/$SKILLS_DIR" "$STORE"

echo
if [ -n "$PROJECT" ]; then
    echo "Done. New Claude Code sessions started in $(dirname "$HOME_DIR") run the svod hooks."
else
    echo "Done. New Claude Code sessions run the svod hooks."
fi
