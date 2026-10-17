# Shared by the setup scripts: the svod command for hooks, hook registration, skill links.
# Sourced, never run on its own.

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_SUFFIX=".bak-svod"
CONFIG_FILE="svod.yaml"
VENDORED_SKILLS=".svod/skills"
PACKAGED_SKILLS="svod/templates/local/skills"
EXIT_USAGE=2

# Prints the base command of the hooks: svod from PATH, else the module of this repository;
# with a store argument, that store as the fallback --root.
svod_command() {
    local store="${1:-}" base
    if base="$(command -v svod)"; then
        printf '%q' "$base"
    else
        printf 'PYTHONPATH=%q python3 -m svod.cli' "$REPO"
    fi
    if [ -n "$store" ]; then
        [ -f "$store/$CONFIG_FILE" ] || { echo "No $CONFIG_FILE in $store" >&2; exit "$EXIT_USAGE"; }
        printf ' --root %q' "$(cd "$store" && pwd)"
    fi
}

# Registers the svod hooks in a JSON hooks file: register_hooks <file> <base command>.
register_hooks() {
    python3 "$REPO/integrations/register_hooks.py" "$1" "$2" "$BACKUP_SUFFIX"
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
