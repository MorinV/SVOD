"""Three-way merge of the files a template gives a store, run by svod update.

base is the template of the engine being replaced, theirs the template of the new engine, ours
the store. Only template files under SCOPE are candidates; files of the store alone are never
touched. A file equal in both templates is skipped, a file the store never changed is replaced,
anything else is merged by `git merge-file`, a conflict written with git markers.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

SCOPE = ("svod.yaml", "AGENTS.md", "profile", "skills")
PROFILE_DIR = "profile"
IGNORED_DIR = "__pycache__"
IGNORED_SUFFIXES = (".pyc", ".pyo")
UPDATED = "updated"
ADDED = "added"
REMOVED = "removed"
MERGED = "merged"
CONFLICT = "conflict"
KEPT = "kept"
CHANGING = (UPDATED, ADDED, REMOVED, MERGED, CONFLICT)
GIT = "git"
MERGE_TIMEOUT_SEC = 60
MAX_CONFLICTS = 127
LABEL_OURS = "store"
LABEL_BASE = "template {version}"
LABEL_THEIRS = "template {version}"
FILE_OURS = "ours"
FILE_BASE = "base"
FILE_THEIRS = "theirs"
TEMP_PREFIX = "svod-merge-"
MARKER = b"<<<<<<<"
TEXT_MARKER = MARKER.decode()
ENCODING = "utf-8"
NO_GIT = "git is not found on PATH: the three-way merge needs `git merge-file`"
MERGE_FAILED = "git merge-file failed on {path}: {reason}"
MARKER_ERROR = ("{path}:{line}: conflict marker {marker} left by svod update; "
                "resolve the conflict and remove the markers")


class MergeError(Exception):
    """The merge could not run at all: no git, or git failed on a file."""


@dataclass(frozen=True)
class Outcome:
    """What the merge does with one file: its kind and the bytes to write, None to remove."""

    path: str
    kind: str
    content: bytes | None = None


def ignored(rel: Path) -> bool:
    """Whether a file is a byte-code artefact that never belongs to a template."""
    return IGNORED_DIR in rel.parts or rel.suffix in IGNORED_SUFFIXES


def scoped_files(directory: Path, scope: tuple[str, ...] = SCOPE) -> set[str]:
    """POSIX paths, relative to directory, of the files under scope."""
    directory = Path(directory)
    found = set()
    for name in scope:
        path = directory / name
        if path.is_file():
            found.add(name)
        elif path.is_dir():
            found.update(p.relative_to(directory).as_posix() for p in path.rglob("*")
                         if p.is_file() and not ignored(p.relative_to(directory)))
    return found


def read(directory: Path, rel: str) -> bytes | None:
    """Bytes of a file, None when it is absent."""
    path = Path(directory) / rel
    return path.read_bytes() if path.is_file() else None


def merge_file(path: str, base: bytes, ours: bytes, theirs: bytes,
               labels: tuple[str, str, str]) -> tuple[bytes, bool]:
    """(merged bytes, whether they hold conflicts) of `git merge-file -p ours base theirs`."""
    git = shutil.which(GIT)
    if git is None:
        raise MergeError(NO_GIT)
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as work:
        files = []
        for name, data in ((FILE_OURS, ours), (FILE_BASE, base), (FILE_THEIRS, theirs)):
            target = Path(work) / name
            target.write_bytes(data)
            files.append(str(target))
        args = [git, "merge-file", "-p"]
        for label in labels:
            args += ["-L", label]
        try:
            done = subprocess.run([*args, *files], capture_output=True,
                                  timeout=MERGE_TIMEOUT_SEC)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MergeError(MERGE_FAILED.format(path=path, reason=exc)) from exc
    if not 0 <= done.returncode <= MAX_CONFLICTS:
        reason = done.stderr.decode(ENCODING, "replace").strip() or done.returncode
        raise MergeError(MERGE_FAILED.format(path=path, reason=reason))
    return done.stdout, done.returncode > 0


def decide(path: str, base: bytes | None, ours: bytes | None, theirs: bytes | None,
           labels: tuple[str, str, str]) -> Outcome | None:
    """What to do with one template file; None when there is nothing to do."""
    if base == theirs or ours == theirs:
        return None
    if ours == base:
        kind = ADDED if ours is None else REMOVED if theirs is None else UPDATED
        return Outcome(path, kind, theirs)
    if ours is None or theirs is None:
        return Outcome(path, KEPT, ours)
    merged, conflicted = merge_file(path, base or b"", ours, theirs, labels)
    return Outcome(path, CONFLICT if conflicted else MERGED, merged)


def plan(base_dir: Path, theirs_dir: Path, root: Path, old: str | None = None,
         new: str | None = None) -> list[Outcome]:
    """Outcome of every template file that changed between the two templates, sorted by path.

    Nothing is written: apply() does that. MergeError when git cannot merge.
    """
    labels = (LABEL_OURS, LABEL_BASE.format(version=old or FILE_BASE),
              LABEL_THEIRS.format(version=new or FILE_THEIRS))
    found = []
    for rel in sorted(scoped_files(base_dir) | scoped_files(theirs_dir)):
        outcome = decide(rel, read(base_dir, rel), read(root, rel), read(theirs_dir, rel),
                         labels)
        if outcome is not None:
            found.append(outcome)
    return found


def apply(root: Path, outcomes: list[Outcome]) -> None:
    """Write the merged files into the store, removing the ones the template dropped."""
    for outcome in outcomes:
        if outcome.kind not in CHANGING:
            continue
        target = Path(root) / outcome.path
        if outcome.content is None:
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(outcome.content)


def profile_matches(template_dir: Path, root: Path) -> bool:
    """Whether every profile file of the template is in the store, byte for byte."""
    files = scoped_files(template_dir, (PROFILE_DIR,))
    return bool(files) and all(read(root, rel) == read(template_dir, rel) for rel in files)


def identify(root: Path, homes: list[Path]) -> tuple[str, Path] | None:
    """(name, directory) of the one template whose profile the store holds unchanged.

    homes are templates directories, searched in order; None when no name or several match.
    """
    found: dict[str, Path] = {}
    for home in homes:
        if not Path(home).is_dir():
            continue
        for directory in sorted(Path(home).iterdir()):
            if directory.is_dir() and profile_matches(directory, root):
                found.setdefault(directory.name, directory)
    return next(iter(found.items())) if len(found) == 1 else None


def conflict_markers(root: Path) -> list[tuple[str, int]]:
    """(file, line) of every conflict start marker in the files under SCOPE of the store."""
    found = []
    for rel in sorted(scoped_files(root)):
        try:
            lines = (Path(root) / rel).read_bytes().splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if line.startswith(MARKER) and line[len(MARKER):len(MARKER) + 1] in (b"", b" "):
                found.append((rel, number))
                break
    return found


def conflict_errors(root: Path) -> list[str]:
    """Validation errors naming every file of the store left with a conflict marker."""
    return [MARKER_ERROR.format(path=rel, line=line, marker=TEXT_MARKER)
            for rel, line in conflict_markers(root)]
