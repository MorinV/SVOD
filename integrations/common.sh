# shellcheck shell=bash
# Shared by the setup scripts: the svod command for hooks, hook registration, skill links.
# Sourced, never run on its own.

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_SUFFIX=".bak-svod"
CONFIG_FILE="svod.yaml"
VENDORED_SKILLS=".svod/skills"
PACKAGED_SKILLS="svod/templates/local/skills"
PYTHON="python3"
CLI_MODULE="svod.cli"
NEUTRAL_DIR="/"
EXIT_USAGE=2

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

# Prints the base command of the hooks: the absolute Python running the engine module, with
# this repository on PYTHONPATH when the engine is not installed in that Python; with a store
# argument, that store as the fallback --root.
svod_command() {
    local store="${1:-}" python
    python="$(python_path)" || exit "$EXIT_USAGE"
    if engine_importable "$python"; then
        printf '%q -m %s' "$python" "$CLI_MODULE"
    else
        printf 'PYTHONPATH=%q %q -m %s' "$REPO" "$python" "$CLI_MODULE"
    fi
    if [ -n "$store" ]; then
        [ -f "$store/$CONFIG_FILE" ] || { echo "No $CONFIG_FILE in $store" >&2; exit "$EXIT_USAGE"; }
        printf ' --root %q' "$(cd "$store" && pwd)"
    fi
}

# Registers the svod hooks in a JSON hooks file: register_hooks <file> <base command>.
register_hooks() {
    "$PYTHON" "$REPO/integrations/register_hooks.py" "$1" "$2" "$BACKUP_SUFFIX"
}

# Directory the skills are linked from: the copy kept by the store when it has one,
# else this repository: skills_source [store].
skills_source() {
    local store="${1:-}"
    if [ -n "$store" ] && [ -d "$store/$VENDORED_SKILLS" ]; then
        (cd "$store/$VENDORED_SKILLS" && pwd)
    else
        printf '%s' "$REPO/$PACKAGED_SKILLS"
    fi
}

# Links every skill directory of the skills source into the given skills directory:
# link_skills <target> [store].
link_skills() {
    local target="$1" skills_dir skill
    skills_dir="$(skills_source "${2:-}")"
    mkdir -p "$target"
    for file in "$skills_dir"/*/SKILL.md; do
        [ -e "$file" ] || continue
        skill="$(dirname "$file")"
        ln -sfn "$skill" "$target/$(basename "$skill")"
        echo "-> skill $(basename "$skill"): $target"
    done
}
