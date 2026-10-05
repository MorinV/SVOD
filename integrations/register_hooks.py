"""Register the svod hooks in a Claude Code settings.json or a Codex hooks.json, idempotently.

Usage: register_hooks.py <file> <base command> <backup suffix>. A hook of svod already present
for an event keeps its place and gets the current command; the original file is copied next to
it before each change.
"""
import json
import shutil
import sys
from pathlib import Path

HOOKS = "hooks"
MATCHER = "matcher"
COMMAND = "command"
TYPE = "type"
TIMEOUT = "timeout"
COMMAND_TYPE = "command"
MARKER = "svod"
HOOK_SUFFIX = " hook {event}"
TOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash|apply_patch"
WANTED = (
    ("SessionStart", None, "session-start", 30),
    ("UserPromptSubmit", None, "prompt", 20),
    ("PreToolUse", TOOL_MATCHER, "pre-tool", 10),
)
ENCODING = "utf-8"
INDENT = 2
USAGE = "usage: register_hooks.py <file> <base command> <backup suffix>"
ARGS = 3
EXIT_USAGE = 2


def ours(command, event):
    """Whether a hook command is the svod hook of the event."""
    return MARKER in command and command.endswith(HOOK_SUFFIX.format(event=event))


def register(data, base):
    """Add or update the svod hooks in the parsed file; return lines about what changed."""
    hooks = data.setdefault(HOOKS, {})
    changes = []
    for name, matcher, event, timeout in WANTED:
        command = base + HOOK_SUFFIX.format(event=event)
        groups = hooks.setdefault(name, [])
        found = [h for g in groups for h in g.get(HOOKS, [])
                 if isinstance(h, dict) and ours(str(h.get(COMMAND, "")), event)]
        for hook in found:
            if hook[COMMAND] != command:
                hook[COMMAND] = command
                changes.append(f"-> hook {name}: updated {command}")
        if found:
            continue
        group = {HOOKS: [{TYPE: COMMAND_TYPE, COMMAND: command, TIMEOUT: timeout}]}
        if matcher:
            group = {MATCHER: matcher, **group}
        groups.append(group)
        changes.append(f"-> hook {name}: {command}")
    return changes


def main(argv):
    """Read the file, register the hooks, back up and write it when anything changed."""
    if len(argv) != ARGS:
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    path, base, suffix = Path(argv[0]), argv[1], argv[2]
    data = json.loads(path.read_text(encoding=ENCODING)) if path.is_file() else {}
    changes = register(data, base)
    if not changes:
        print(f"-> hooks: up to date in {path}")
        return 0
    if path.is_file():
        shutil.copyfile(path, path.with_name(path.name + suffix))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=INDENT) + "\n", encoding=ENCODING)
    print("\n".join(changes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
