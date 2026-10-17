# shellcheck shell=bash
# Shared by the setup scripts: the svod command for hooks, hook registration, skill links.
# Sourced, never run on its own.
#
# The skills linked are the store's own, <store>/skills/<name>/SKILL.md, when it has any; else
# those of the copy it keeps in .svod/skills; else those of this repository. The scripts print
# the engine the hooks import as "-> engine: <file of the svod package>"; --engine <clone> puts
# that clone on PYTHONPATH of the hooks, for a Python whose svod comes from another checkout.

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_SUFFIX=".bak-svod"
CONFIG_FILE="svod.yaml"
STORE_SKILLS="skills"
VENDORED_SKILLS=".svod/skills"
PACKAGED_SKILLS="svod/skills"
SKILL_FILE="SKILL.md"
PYTHON="python3"
CLI_MODULE="svod.cli"
ENGINE_FLAG="--engine"
ENGINE_FILE="svod/cli.py"
ENGINE_SCRIPT="import svod; print(svod.__file__)"
NEUTRAL_DIR="/"
EXIT_USAGE=2

# The clone of --engine, absolute, or empty; the arguments other than --engine and its value.
ENGINE=""
ARGS=()

# Reads --engine <clone> anywhere among the arguments into ENGINE, the others into ARGS:
# engine_flag "$@". Fails without a value; stops with the usage code when the directory holds
# no engine.
engine_flag() {
    while [ "$#" -gt 0 ]; do
        if [ "$1" = "$ENGINE_FLAG" ]; then
            [ "$#" -ge 2 ] || return 1
            [ -f "$2/$ENGINE_FILE" ] || { echo "No $ENGINE_FILE in $2" >&2; exit "$EXIT_USAGE"; }
            ENGINE="$(cd "$2" && pwd)"
            shift 2
        else
            ARGS+=("$1")
            shift
        fi
    done
}

# Prints the absolute path of the Python the hooks run: sys.executable of python3 from PATH,
# else the path PATH gives for it.
python_path() {
    local found exe
    found="$(command -v "$PYTHON")" || { echo "No $PYTHON on PATH" >&2; exit "$EXIT_USAGE"; }
    exe="$("$found" -c 'import sys; print(sys.executable)' 2>/dev/null)" || exe=""
    printf '%s' "${exe:-$found}"
}

# Whether the engine imports in the given Python without PYTHONPATH and away from this
# repository, as it does when an agent runs the hook: engine_importable <python>.
engine_importable() {
    (cd "$NEUTRAL_DIR" && "$1" -E -c "import $CLI_MODULE") >/dev/null 2>&1
}

# Prints the PYTHONPATH of the hooks in the given Python: the clone of --engine, else nothing
# when the engine imports without it, else this repository: hook_pythonpath <python>.
hook_pythonpath() {
    if [ -n "$ENGINE" ]; then
        printf '%s' "$ENGINE"
    elif ! engine_importable "$1"; then
        printf '%s' "$REPO"
    fi
}

# Prints the base command of the hooks: the absolute Python running the engine module, with
# the PYTHONPATH of hook_pythonpath when there is one; with a store argument, that store as the
# fallback --root.
svod_command() {
    local store="${1:-}" python pythonpath
    python="$(python_path)" || exit "$EXIT_USAGE"
    pythonpath="$(hook_pythonpath "$python")"
    if [ -z "$pythonpath" ]; then
        printf '%q -m %s' "$python" "$CLI_MODULE"
    else
        printf 'PYTHONPATH=%q %q -m %s' "$pythonpath" "$python" "$CLI_MODULE"
    fi
    if [ -n "$store" ]; then
        [ -f "$store/$CONFIG_FILE" ] || { echo "No $CONFIG_FILE in $store" >&2; exit "$EXIT_USAGE"; }
        printf ' --root %q' "$(cd "$store" && pwd)"
    fi
}

# Prints "-> engine: <file>", the svod package the hooks import, found as the hook command
# finds it, so that an engine installed from another checkout shows: show_engine.
show_engine() {
    local python pythonpath file
    python="$(python_path)" || exit "$EXIT_USAGE"
    pythonpath="$(hook_pythonpath "$python")"
    if [ -n "$pythonpath" ]; then
        file="$(cd "$NEUTRAL_DIR" && PYTHONPATH="$pythonpath" "$python" -c "$ENGINE_SCRIPT" \
            2>/dev/null)" || file=""
    else
        file="$(cd "$NEUTRAL_DIR" && "$python" -E -c "$ENGINE_SCRIPT" 2>/dev/null)" || file=""
    fi
    echo "-> engine: ${file:-not importable by $python}"
}

# Registers the svod hooks in a JSON hooks file: register_hooks <file> <base command>.
register_hooks() {
    "$PYTHON" "$REPO/integrations/register_hooks.py" "$1" "$2" "$BACKUP_SUFFIX"
}

# Directory the skills are linked from: the store's own skills when it has any, else the copy
# kept by the store, else this repository: skills_source [store].
skills_source() {
    local store="${1:-}" file
    if [ -n "$store" ]; then
        for file in "$store/$STORE_SKILLS"/*/"$SKILL_FILE"; do
            [ -e "$file" ] || continue
            (cd "$store/$STORE_SKILLS" && pwd)
            return
        done
        if [ -d "$store/$VENDORED_SKILLS" ]; then
            (cd "$store/$VENDORED_SKILLS" && pwd)
            return
        fi
    fi
    printf '%s' "$REPO/$PACKAGED_SKILLS"
}

# Links every skill directory of the skills source into the given skills directory:
# link_skills <target> [store].
link_skills() {
    local target="$1" skills_dir skill
    skills_dir="$(skills_source "${2:-}")"
    mkdir -p "$target"
    for file in "$skills_dir"/*/"$SKILL_FILE"; do
        [ -e "$file" ] || continue
        skill="$(dirname "$file")"
        ln -sfn "$skill" "$target/$(basename "$skill")"
        echo "-> skill $(basename "$skill"): $target"
    done
}
