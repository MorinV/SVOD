"""The pre-tool rules: approval fields, marks, questions, a read-only main checkout, frozen code.

Guard holds the store of one event; tool_reason asks it about one tool call.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..approval import HUMAN_FILE, MARK_FILE, field_names
from ..approval_package import PACKAGE_FILE
from ..cache import RunCache
from ..checkouts import subject_context
from ..config import load_config
from ..errors import LoadError
from ..gates import PARAM_FILE, PARAM_MARKER
from ..git import GitResult, run_git, worktree_list
from ..keys import (HOOK_DENY_APPROVAL, HOOK_DENY_BROKEN, HOOK_DENY_HUMAN, HOOK_DENY_MAIN,
                    HOOK_DENY_MARK, HOOK_DENY_PLAN, HOOK_DENY_QUESTIONS, STATUS_UNKNOWN)
from ..locale import error_locale
from ..paths import find_root
from ..position import freeze
from ..render import gate_text
from ..resolve import by_key
from ..workflow_policy import approval_refs
from .protocol import (BASH_TOOL, CONTENT_FIELD, EDITS_FIELD, PATCH_TOOL, PATH_FIELDS,
                       TEXT_FIELDS, WRITE_TOOL, Event, absolute, command_of, event_cwd)
from .shell import bash_paths, bash_reads_only, bash_writes_approval
from .store import context_of, key_gates, load, one_line

if TYPE_CHECKING:
    from ..pipeline import Pipeline
    from ..subject import Subject

Run = Callable[..., GitResult]
Touches = Callable[..., bool]

PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$|^\*\*\* Move to: (.+)$")
PATCH_CHANGED = ("+", "-")
DOT_GIT = ".git"
ENCODING = "utf-8"
FIELD_LINE_RE = r"^\s*(?:{fields})\s*:"
FIELDS_SEPARATOR = ", "
LINE_SEPARATOR = "\n"
CHECK_IGNORE = ("check-ignore", "--")
QUESTIONS_FILE = "questions.md"


@dataclass(frozen=True)
class Guarded:
    """A metadata file of subjects, as trailing path parts, and the approval fields it holds."""

    parts: tuple[str, ...]
    fields: tuple[str, ...]


def guarded_files(pipelines: Iterable[Pipeline]) -> list[Guarded]:
    """Metadata files holding approval fields, from the approval gates of every pipeline step."""
    found: dict[tuple[str, ...], list[str]] = {}
    for pipeline in pipelines:
        for ref in approval_refs(pipeline):
            parts = Path(ref.params[PARAM_FILE]).parts
            fields = found.setdefault(parts, [])
            fields += [f for f in field_names(ref.params[PARAM_MARKER]) if f not in fields]
    return [Guarded(parts, tuple(fields)) for parts, fields in found.items()]


def approval_lines(text: str, fields: Iterable[str]) -> list[str]:
    """Lines of the text setting any of the fields, stripped."""
    pattern = re.compile(FIELD_LINE_RE.format(
        fields="|".join(re.escape(f) for f in fields)))
    return [line.strip() for line in text.splitlines() if pattern.match(line)]


def read_text(path: str | Path) -> str:
    """Text of the file, or an empty string."""
    try:
        return Path(path).read_text(encoding=ENCODING)
    except (OSError, UnicodeDecodeError):
        return ""


def inside(root: Path | None, path: Path) -> bool:
    """Whether the path lies in the root directory."""
    return root is not None and path.is_relative_to(root)


def existing_dir(path: Path) -> Path:
    """Nearest existing directory holding the path, or the path itself."""
    for directory in (path, *path.parents):
        if directory.is_dir():
            return directory
    return path


def checkout_dir(path: Path) -> Path | None:
    """Nearest directory holding the path that is a git checkout, or None."""
    for directory in (path, *path.parents):
        if (directory / DOT_GIT).exists():
            return directory
    return None


def patch_targets(event: Event, patch: str) -> list[tuple[Path, str]]:
    """(path, changed lines of its section) of every file of an apply_patch text, moves too."""
    sections: dict[Path, list[str]] = {}
    current: list[str] = []
    for line in patch.split(LINE_SEPARATOR):
        found = PATCH_FILE_RE.match(line)
        if found:
            path = absolute(event, (found.group(1) or found.group(2)).strip())
            if found.group(1):
                current = sections.setdefault(path, [])
            else:
                sections[path] = current
            continue
        if line.startswith(PATCH_CHANGED):
            current.append(line)
    return [(path, LINE_SEPARATOR.join(lines)) for path, lines in sections.items()]


def questions_file(path: Path) -> bool:
    """Whether the path is the questions.md of a work record: below the root of a store."""
    if path.name != QUESTIONS_FILE:
        return False
    root = find_root(existing_dir(path.parent))
    return root is not None and path.parent != root


def main_checkout(directory: Path, run: Run | None = None) -> tuple[Path, Path] | None:
    """(store, main checkout) when the directory lies in a read-only main checkout, else None.

    Nested repositories, the git directory and other worktrees of the store are not the main
    checkout. The checkout of the directory is the nearest one holding .git, which must also
    hold the store; a .git directory there is a main checkout, anything else is asked of git
    worktree list. run replaces run_git.
    """
    store = find_root(directory)
    if store is None:
        return None
    try:
        config = load_config(store, local=False)
    except LoadError:
        return None
    if not config.main_checkout_read_only:
        return None
    top = checkout_dir(directory)
    if top is None or checkout_dir(store) != top or DOT_GIT in directory.relative_to(top).parts:
        return None
    if (top / DOT_GIT).is_dir():
        return store, top
    found, _ = worktree_list(store, run)
    if not found or found[0].path != top.resolve():
        return None
    return store, found[0].path


def ignored_paths(main: Path, paths: Sequence[Path], run: Run | None = None) -> set[str]:
    """Those of the paths that git ignores in the main checkout, as given; run replaces run_git."""
    if not paths:
        return set()
    result = (run or run_git)(main, *CHECK_IGNORE, *(str(p) for p in paths))
    return set(result.out.splitlines()) if result.ok else set()


def main_text(store: Path, main: Path) -> str:
    """Refusal of an edit in the read-only main checkout."""
    return error_locale(store).text(HOOK_DENY_MAIN, main=main)


def main_reason(path: Path, run: Run | None = None) -> str | None:
    """Refusal when the path is in the main checkout of a store that keeps it read-only.

    Paths git ignores, nested repositories and other worktrees are not refused. run replaces
    run_git.
    """
    found = main_checkout(existing_dir(path), run)
    if found is None or str(path) in ignored_paths(found[1], [path], run):
        return None
    return main_text(*found)


class Guard:
    """Checks of one pre-tool event against the store of the session.

    Every git call of the event goes through one run cache, the gates of the store included.
    """

    def __init__(self, root: Path | None) -> None:
        """Load the store; without one only the main checkout rule applies."""
        self.root = root
        self.cache = RunCache()
        self.runtime, self.broken = load(root) if root is not None else (None, None)
        self.ctx = context_of(self.runtime, self.cache) if self.runtime else None
        self.guarded = guarded_files(self.runtime.pipelines) if self.runtime else []

    def fields_of(self, path: Path) -> tuple[tuple[str, ...], str | None]:
        """(approval fields, metadata file name) when the path is a guarded metadata file."""
        for item in self.guarded:
            if path.parts[-len(item.parts):] == item.parts:
                return item.fields, Path(*item.parts).as_posix()
        return (), None

    def approval_text(self, fields: Iterable[str], name: str | None) -> str:
        """Refusal of an edit of the approval fields."""
        # Guarded files come from a loaded store, so only a Guard with a runtime gets here.
        return self.runtime.locale.text(  # type: ignore[union-attr]
            HOOK_DENY_APPROVAL, fields=FIELDS_SEPARATOR.join(fields), file=name)

    def mark_text(self, name: str = MARK_FILE) -> str:
        """Refusal of a write of the approval or the human mark, in the locale of the store."""
        key = HOOK_DENY_HUMAN if name == HUMAN_FILE else HOOK_DENY_MARK
        return error_locale(self.root).text(key, file=name)

    def questions_text(self) -> str:
        """Refusal of a direct write of the questions of a work record.

        svod ask adds the questions, svod answer the answers; the text names both.
        """
        return error_locale(self.root).text(HOOK_DENY_QUESTIONS, file=QUESTIONS_FILE)

    def edit_reason(self, path: Path, touches: Touches) -> str | None:
        """Refusal of an edit of the path; touches(fields) tells whether it changes them."""
        if path.name in (MARK_FILE, HUMAN_FILE, PACKAGE_FILE):
            return self.mark_text(path.name)
        if questions_file(path):
            return self.questions_text()
        fields, name = self.fields_of(path)
        if fields and touches(fields):
            return self.approval_text(fields, name)
        return main_reason(path, self.cache.git) or self.plan_reason(path)

    def bash_reason(self, event: Event, command: str) -> str | None:
        """Refusal of a shell command writing approval fields, the mark, frozen or main code."""
        if bash_writes_approval(command, self.guarded):
            item = next(i for i in self.guarded if i.parts[-1] in command)
            return self.approval_text(item.fields, Path(*item.parts).as_posix())
        if bash_reads_only(command):
            return None
        for name in (MARK_FILE, HUMAN_FILE, PACKAGE_FILE):
            if name in command:
                return self.mark_text(name)
        if QUESTIONS_FILE in command and any(questions_file(path)
                                             for path in bash_paths(event, command)):
            return self.questions_text()
        cwd = event_cwd(event).resolve()
        reason = self.plan_reason(cwd)
        if reason:
            return reason
        by_dir: dict[Path, list[Path]] = {}
        for path in bash_paths(event, command):
            by_dir.setdefault(existing_dir(path), []).append(path)
        for directory, paths in by_dir.items():
            found = main_checkout(directory, self.cache.git)
            if found is not None:
                ignored = ignored_paths(found[1], paths, self.cache.git)
                if any(str(p) not in ignored for p in paths):
                    return main_text(*found)
            if directory != cwd:
                reason = self.plan_reason(directory)
                if reason:
                    return reason
        return None

    def dir_keys(self, name: str) -> set[str]:
        """Keys the key gates find in, or read as a query from, a directory name."""
        keys: set[str] = set()
        # Called from plan_reason only once a workspace gate shows the store loaded.
        for gate in key_gates(self.runtime.pipelines):  # type: ignore[union-attr]
            keys |= set(gate.find(name))
            key = gate.match(name)
            if key:
                keys.add(key)
        return keys

    def plan_reason(self, path: Path) -> str | None:
        """Refusal of an edit in the work directory of a subject whose code is still frozen.

        The freeze is checked before the directory is asked of the workspace gate: an edit in
        the work directory of an approved subject needs none of the git calls of the gate.
        """
        gate = self.runtime.workspace_gate if self.runtime else None
        directory = checkout_dir(path) if gate is not None else None
        if gate is None or directory is None:
            return None
        for key in sorted(self.dir_keys(directory.name)):
            text = self.frozen_text(key)
            if not text:
                continue
            found, _ = gate.worktrees(self.ctx, {key})
            if directory in {Path(item[0]).resolve() for item in found}:
                # A workspace gate exists only in a loaded store.
                return self.runtime.locale.text(  # type: ignore[union-attr]
                    HOOK_DENY_PLAN, keys=key, text=text)
        return None

    def frozen_text(self, key: str) -> str | None:
        """Freeze text of the first existing, not archived subject of the key, or None."""
        # Called from plan_reason only once a workspace gate shows the store loaded.
        for pipeline, subject in by_key(self.ctx,
                                        self.runtime.pipelines,  # type: ignore[union-attr]
                                        key):
            if not subject.exists or subject.archived:
                continue
            text = self.frozen(pipeline, subject)
            if text:
                return text
        return None

    def frozen(self, pipeline: Pipeline, subject: Subject) -> str | None:
        """Text of the first gate of a blocks_code step that did not pass, or None."""
        found = freeze(subject_context(self.ctx, subject), pipeline, subject)
        if found is None:
            return None
        # Called from frozen_text only, behind a loaded store.
        locale = self.runtime.locale  # type: ignore[union-attr]
        if found.unknown:
            return locale.text(STATUS_UNKNOWN, reason=found.reason, gate=found.gate)
        # An open step names a text: its gate's, else its own, which the schema then requires.
        return gate_text(locale, found.text, found.facts)  # type: ignore[arg-type]


def edit_touches(tool: str, data: dict[str, Any], path: Path) -> Touches:
    """Predicate over approval fields: whether an Edit, MultiEdit or Write changes their lines."""
    if tool == WRITE_TOOL:
        content = str(data.get(CONTENT_FIELD) or "")
        return lambda fields: approval_lines(content, fields) != approval_lines(read_text(path),
                                                                                fields)
    edits = data.get(EDITS_FIELD) or [data]
    texts = [str(edit.get(f) or "") for edit in edits if isinstance(edit, dict)
             for f in TEXT_FIELDS]
    return lambda fields: any(f in text for text in texts for f in fields)


def edit_path(event: Event, data: dict[str, Any]) -> Path | None:
    """Resolved file of an edit tool call, or None when it names none."""
    raw = next((data[f] for f in PATH_FIELDS if isinstance(data.get(f), str) and data[f]), None)
    return absolute(event, raw) if raw is not None else None


def tool_reason(guard: Guard, event: Event, tool: str, data: dict[str, Any]) -> str | None:
    """Refusal of the tool call, or None."""
    if tool == BASH_TOOL:
        return guard.bash_reason(event, command_of(data))
    if tool == PATCH_TOOL:
        for target, section in patch_targets(event, command_of(data)):
            reason = guard.edit_reason(target, lambda fields, section=section: any(f in section
                                                                                  for f in fields))
            if reason:
                return reason
        return None
    path = edit_path(event, data)
    return guard.edit_reason(path, edit_touches(tool, data, path)) if path is not None else None


def tool_paths(event: Event, tool: str, data: dict[str, Any]) -> list[Path]:
    """Paths a tool call may write: the file of an edit, those of a patch or of a command."""
    if tool == BASH_TOOL:
        command = command_of(data)
        return [] if bash_reads_only(command) else bash_paths(event, command)
    if tool == PATCH_TOOL:
        return [path for path, _ in patch_targets(event, command_of(data))]
    path = edit_path(event, data)
    return [path] if path is not None else []


def broken_reason(guard: Guard, event: Event, tool: str, data: dict[str, Any]) -> str | None:
    """Refusal of a write outside a store that does not load: nothing guards it until it does.

    Writes inside the store stay allowed, so the store can be repaired; they get the context line.
    """
    paths = tool_paths(event, tool, data)
    if all(inside(guard.root, path) for path in paths):
        return None
    return error_locale(guard.root).text(HOOK_DENY_BROKEN, reason=one_line(guard.broken))
