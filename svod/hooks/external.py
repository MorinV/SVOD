"""The external-effects rule: shell commands that reach beyond this machine wait for a person.

A command pushes, publishes, deploys or opens a remote host: the pre-tool hook refuses it,
whatever the autonomy of the pipeline, until a fresh human mark says go ahead.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..approval import HUMAN_GO, Run, fresh_human_mark
from ..config import DEFAULT_EXTERNAL_PHRASES, DEFAULT_WINDOW_MINUTES, Config
from ..keys import HOOK_DENY_EXTERNAL
from ..locale import error_locale
from .guard import DOT_GIT, checkout_dir
from .protocol import Event, absolute, event_cwd
from .shell import (ASSIGNMENT_RE, COMMAND_PREFIXES, OPTION_PREFIX, WORD_GAP, command_segments,
                    git_subcommand, shell_tokens)
from .store import config_of

PREFIXES = COMMAND_PREFIXES | {"sudo", "nohup"}
SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
SHELL_SCRIPT_FLAG = "-c"
PYTHON_RE = re.compile(r"^python[\d.]*$")
MODULE_FLAG = "-m"
GIT = "git"
GIT_PUSH = "push"
GIT_HISTORY = frozenset({"merge", "rebase"})
GIT_DIR_OPTION = "-C"
DRY_RUN = frozenset({"--dry-run", "-n"})
GH = "gh"
GH_PR_MERGE = ("pr", "merge")
GH_RELEASE = "release"
GH_RELEASE_READS = frozenset({"list", "view", "download"})
# Programs whose subcommand, among the first two plain words, has an external effect.
SUBCOMMANDS = {
    "npm": frozenset({"publish"}),
    "pip": frozenset({"upload"}),
    "pip3": frozenset({"upload"}),
    "twine": frozenset({"upload"}),
    "docker": frozenset({"push"}),
    "kubectl": frozenset({"apply", "delete"}),
    "terraform": frozenset({"apply", "destroy"}),
}
SUBCOMMAND_WORDS = 2
REMOTE_PROGRAMS = frozenset({"ssh", "scp"})
RSYNC = "rsync"
REMOTE_RE = re.compile(r"^(?:rsync://|(?:[^\s/:@]+@)?[A-Za-z0-9][\w.-]*::?)")
MAX_DEPTH = 3
PHRASES_SEPARATOR = ", "
QUOTE = '"'


def program_words(segment: Sequence[str]) -> list[str]:
    """Words of a simple command from its program on: assignments and prefixes dropped."""
    words = list(segment)
    while words and (ASSIGNMENT_RE.match(words[0]) or words[0] in PREFIXES):
        words.pop(0)
    return words


def plain_words(words: Iterable[str]) -> list[str]:
    """The words that are not options."""
    return [w for w in words if not w.startswith(OPTION_PREFIX)]


def git_dir(event: Event, words: Sequence[str]) -> Path:
    """Directory a git command works in: its last -C value from the event cwd, else the cwd."""
    found = event_cwd(event)
    for option, value in zip(words, words[1:], strict=False):
        if option == GIT_DIR_OPTION:
            found = absolute(event, value)
    return found


def main_checkout_dir(directory: Path) -> bool:
    """Whether the directory lies in a main checkout: the nearest .git above it is a directory."""
    top = checkout_dir(directory.resolve())
    return top is not None and (top / DOT_GIT).is_dir()


def git_external(event: Event, rest: Sequence[str]) -> bool:
    """git push without a dry run; merge or rebase in a main checkout, not in a worktree."""
    sub = git_subcommand(rest)
    if sub == GIT_PUSH:
        return not any(w in DRY_RUN for w in rest)
    if sub in GIT_HISTORY:
        return main_checkout_dir(git_dir(event, rest))
    return False


def gh_external(rest: Sequence[str]) -> bool:
    """gh pr merge, and gh release but for its list, view and download."""
    words = plain_words(rest)
    if tuple(words[:len(GH_PR_MERGE)]) == GH_PR_MERGE:
        return True
    return words[:1] == [GH_RELEASE] and len(words) > 1 and words[1] not in GH_RELEASE_READS


def default_external(event: Event, words: Sequence[str]) -> bool:
    """Whether a simple command is in the standard list of commands with an external effect."""
    name, rest = Path(words[0]).name, list(words[1:])
    if PYTHON_RE.match(name) and rest[:1] == [MODULE_FLAG] and len(rest) > 1:
        name, rest = rest[1], rest[2:]
    if name == GIT:
        return git_external(event, rest)
    if name == GH:
        return gh_external(rest)
    if name in SUBCOMMANDS:
        return any(w in SUBCOMMANDS[name] for w in plain_words(rest)[:SUBCOMMAND_WORDS])
    if name in REMOTE_PROGRAMS:
        return True
    if name == RSYNC:
        return any(REMOTE_RE.match(w) for w in plain_words(rest))
    return False


def matches(patterns: Iterable[str], text: str) -> bool:
    """Whether any of the regular expressions is found in the text."""
    return any(re.search(pattern, text) for pattern in patterns)


def external_command(event: Event, command: str, deny: Iterable[str] = (),
                     allow: Iterable[str] = (), depth: int = 0) -> str | None:
    """The first simple command with an external effect, as its words joined, or None.

    Each simple command is matched as its words joined by single spaces, from its program
    on: allow exempts it, the standard list or deny refuses it. The script of sh -c and
    the like is read as commands of its own.
    """
    deny, allow = tuple(deny), tuple(allow)
    for segment in command_segments(shell_tokens(command)):
        words = program_words(segment)
        if not words:
            continue
        text = WORD_GAP.join(words)
        if matches(allow, text):
            continue
        if (Path(words[0]).name in SHELLS and len(words) > 2 and words[1] == SHELL_SCRIPT_FLAG
                and depth < MAX_DEPTH):
            found = external_command(event, words[2], deny, allow, depth + 1)
            if found:
                return found
            continue
        if default_external(event, words) or matches(deny, text):
            return text
    return None


def external_reason(root: Path | None, event: Event, command: str,
                    run: Run | None = None) -> str | None:
    """Refusal of a shell command with an external effect, or None.

    Without a store the rule is off. A store whose svod.yaml does not load gets the standard
    list and the default phrases. The refusal is lifted by a fresh human mark that says go
    ahead (a reply of a person holding one of external_effects.phrases). run replaces run_git.
    """
    if root is None:
        return None
    config: Config | None = config_of(root)
    deny = config.external_deny if config else ()
    allow = config.external_allow if config else ()
    found = external_command(event, command, deny, allow)
    if found is None:
        return None
    window = config.approval_window if config else DEFAULT_WINDOW_MINUTES
    mark = fresh_human_mark(root, window, run=run)
    if mark is not None and mark.get(HUMAN_GO) is True:
        return None
    phrases = config.external_phrases if config else DEFAULT_EXTERNAL_PHRASES
    return error_locale(root).text(
        HOOK_DENY_EXTERNAL, command=found, minutes=window,
        phrases=PHRASES_SEPARATOR.join(f"{QUOTE}{phrase}{QUOTE}" for phrase in phrases))
