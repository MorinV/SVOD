"""Results of the command gate kept between runs, keyed by what the command can read.

An entry lives in <git common dir>/svod-command-cache/<key>.json, shared by every worktree of
the repository. The key is sha256 over the argv, the env, the place of the directory in its
repository, the files of HEAD, the status, the content of every changed or untracked file and
of the watched files; paths the ignore patterns name (the evidence log, logs, the knowledge
index by default) are left out. The last result of each command, whatever its key, lives in
last/<sha256 of argv, env and place>.json beside the entries. Nothing is cached outside a git
repository.
"""
from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import git
from .cache import RunCache
from .yamlio import ENCODING

CACHE_DIR = "svod-command-cache"
LAST_DIR = "last"
ENTRY_SUFFIX = ".json"
FIELD_KEY = "key"
SEP = "/"
TAB = "\t"
RENAME_LETTERS = "RC"
# Paths left out of the key whatever svod.yaml says: the evidence log, logs, the knowledge index.
DEFAULT_IGNORE = ("evidence/", "*.log", "knowledge/INDEX.md")
TEMP_SUFFIX = ".tmp"
GIT_DIR = ".git"
NUL = "\0"
TOPLEVEL = ("rev-parse", "--show-toplevel")
HEAD = ("rev-parse", "--verify", "--quiet", "HEAD")
STATUS = (*git.QUOTE_PATH_OFF, "status", "--porcelain", "-z", "--untracked-files=all")
TREE = (*git.QUOTE_PATH_OFF, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
CHANGED = (*git.QUOTE_PATH_OFF, "diff", "--name-only", "--no-renames", "-z", "HEAD")
TRACKED = (*git.QUOTE_PATH_OFF, "ls-files", "-z")
UNTRACKED = (*git.QUOTE_PATH_OFF, "ls-files", "--others", "--exclude-standard", "-z")
# Files hashed by content up to these bounds; beyond them, by size and modification time.
CONTENT_MAX_FILES = 1000
CONTENT_MAX_BYTES = 8 * 1024 * 1024
READ_CHUNK = 1 << 16


@dataclass(frozen=True)
class Record:
    """One finished run: exit code, tail of the output, UTC start time, duration in seconds."""

    code: int
    tail: str
    time: str
    duration: float


def watched(cwd: Path, patterns: Iterable[str]) -> list[str]:
    """Sorted paths relative to cwd of the files the paths or globs name; a directory counts
    with every file below it, .git directories never."""
    found: set[str] = set()
    for pattern in patterns:
        for match in cwd.glob(pattern):
            files = match.rglob("*") if match.is_dir() else [match]
            for path in files:
                rel = path.relative_to(cwd)
                if path.is_file() and GIT_DIR not in rel.parts:
                    found.add(rel.as_posix())
    return sorted(found)


def ignored(rel: str, patterns: Iterable[str]) -> bool:
    """Whether a path relative to the directory is named by one of the patterns.

    As in .gitignore: a pattern with a slash before its end is anchored at the directory, one
    without matches a name at any depth; a trailing slash names directories, and a directory
    counts with everything below it. Globs as fnmatch reads them.
    """
    parts = rel.split(SEP)
    for pattern in patterns:
        folder = pattern.endswith(SEP)
        body = pattern.rstrip(SEP)
        if not body:
            continue
        if SEP in body:
            size = len(body.split(SEP))
            if (len(parts) > size or not folder and len(parts) == size) and fnmatch.fnmatchcase(
                    SEP.join(parts[:size]), body):
                return True
        elif any(fnmatch.fnmatchcase(part, body)
                 for part in (parts[:-1] if folder else parts)):
            return True
    return False


def relative(rel: str, place: str) -> str:
    """Path relative to the repository as seen from the directory at place, when below it."""
    prefix = f"{place}{SEP}"
    return rel[len(prefix):] if place not in ("", ".") and rel.startswith(prefix) else rel


def kept(rels: Iterable[str], place: str, patterns: tuple[str, ...]) -> list[str]:
    """The repository paths no pattern names, seen from the directory at place."""
    return [rel for rel in rels if not ignored(relative(rel, place), patterns)]


def status_entries(out: git.GitResult) -> list[list[str]]:
    """Entries of git status --porcelain -z: [code, path] or [code, path, original path].

    The output comes stripped: a first entry whose code began with a space gets it back.
    """
    items = out.out.split(NUL)
    if items and len(items[0]) > 2 and items[0][1] == " " and items[0][2] != " ":
        items[0] = f" {items[0]}"
    entries, index = [], 0
    while index < len(items):
        item = items[index]
        index += 1
        if not item:
            continue
        entry = [item[:2], item[3:]]
        if any(code in RENAME_LETTERS for code in item[:2]) and index < len(items):
            entry.append(items[index])
            index += 1
        entries.append(entry)
    return entries


def tree_digest(out: git.GitResult, place: str, patterns: tuple[str, ...]) -> str:
    """sha256 of the HEAD listing (mode, type, object, path) without the ignored paths."""
    digest = hashlib.sha256()
    for item in out.out.split(NUL):
        if item and not ignored(relative(item.partition(TAB)[2], place), patterns):
            digest.update(item.encode(ENCODING) + NUL.encode(ENCODING))
    return digest.hexdigest()


def file_sha(path: Path) -> str:
    """sha256 of the file content."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_digest(base: Path, rels: list[str]) -> list[list[Any]]:
    """[path, sha256] of each file under base while the files are few and small, else
    [path, size, modification time]; a path that is not a file is [path]."""
    stats: list[tuple[str, os.stat_result | None]] = []
    for rel in rels:
        try:
            stat = (base / rel).stat()
        except OSError:
            stat = None
        stats.append((rel, stat if stat is not None and (base / rel).is_file() else None))
    total = sum(s.st_size for _, s in stats if s is not None)
    by_content = len(stats) <= CONTENT_MAX_FILES and total <= CONTENT_MAX_BYTES
    items: list[list[Any]] = []
    for rel, stat in stats:
        if stat is None:
            items.append([rel])
        elif by_content:
            items.append([rel, file_sha(base / rel)])
        else:
            items.append([rel, stat.st_size, stat.st_mtime_ns])
    return items


def names(out: git.GitResult) -> list[str]:
    """Paths of a NUL-separated git listing."""
    return [p for p in out.out.split(NUL) if p]


def location(cwd: Path, cache: RunCache) -> tuple[Path, Path, str] | None:
    """(git common dir, top level, place of cwd in it) of the directory, or None outside git."""
    cache.prefetch([(cwd, git.COMMON_DIR), (cwd, TOPLEVEL)])
    common, top = cache.git(cwd, *git.COMMON_DIR), cache.git(cwd, *TOPLEVEL)
    if not common.ok or not top.ok:
        return None
    root = Path(top.out)
    try:
        place = cwd.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        place = str(cwd.resolve())
    return (cwd / common.out).resolve(), root, place


def digest_of(material: dict[str, Any]) -> str:
    """sha256 of the material as canonical JSON."""
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode(ENCODING)).hexdigest()


def entry(cwd: str | Path, argv: list[str], env: dict[str, str] | None = None,
          watch: list[str] | None = None, cache: RunCache | None = None,
          ignore: Iterable[str] = ()) -> Path | None:
    """Cache file of the command in cwd as the directory is now, or None outside git.

    cache runs git (a fresh RunCache by default); None also when a git call fails. The paths
    DEFAULT_IGNORE and ignore name, seen from cwd, are left out of HEAD, the status and the
    changed files; watched files always count.
    """
    cache = cache or RunCache()
    cwd = Path(cwd)
    found = location(cwd, cache)
    if found is None:
        return None
    common, root, place = found
    patterns = (*DEFAULT_IGNORE, *ignore)
    source = cache.value((CACHE_DIR, str(root), place, patterns),
                         lambda: source_material(root, place, patterns, cache))
    if source is None:
        return None
    material = {
        "argv": list(argv), "env": sorted((env or {}).items()), "place": place, **source,
        "watch": files_digest(cwd, watched(cwd, watch)) if watch else None,
    }
    return common / CACHE_DIR / f"{digest_of(material)}{ENTRY_SUFFIX}"


def source_material(root: Path, place: str, patterns: tuple[str, ...],
                    cache: RunCache) -> dict[str, Any] | None:
    """What the repository at root holds as seen from place, the ignored paths left out: the
    HEAD files, the status and the changed or untracked files; None when git fails."""
    head = cache.git(root, *HEAD)
    listing = CHANGED if head.ok else TRACKED
    calls = [(root, STATUS), (root, listing), (root, UNTRACKED)]
    cache.prefetch([*calls, (root, TREE)] if head.ok else calls)
    status, changed, untracked = (cache.git(root, *args) for args in (STATUS, listing, UNTRACKED))
    tree = cache.git(root, *TREE) if head.ok else None
    if not (status.ok and changed.ok and untracked.ok) or tree is not None and not tree.ok:
        return None
    dirty = kept(sorted(set(names(changed)) | set(names(untracked))), place, patterns)
    return {"head": tree_digest(tree, place, patterns) if tree is not None else "",
            "status": [e for e in status_entries(status) if kept(e[1:], place, patterns)],
            "dirty": files_digest(root, dirty)}


def last_entry(cwd: str | Path, argv: list[str], env: dict[str, str] | None = None,
               cache: RunCache | None = None) -> Path | None:
    """File of the last result of the command in cwd, whatever the source; None outside git."""
    cwd = Path(cwd)
    found = location(cwd, cache or RunCache())
    if found is None:
        return None
    common, _, place = found
    material = {"argv": list(argv), "env": sorted((env or {}).items()), "place": place}
    return common / CACHE_DIR / LAST_DIR / f"{digest_of(material)}{ENTRY_SUFFIX}"


def read(path: Path) -> tuple[Record, str] | None:
    """(record, key of the entry it was stored under, or "") of the cache file, or None when
    it is absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
        record = Record(code=int(data["code"]), tail=str(data["tail"]), time=str(data["time"]),
                        duration=float(data["duration"]))
        return record, str(data.get(FIELD_KEY, ""))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def load(path: Path) -> Record | None:
    """Record stored in the cache file, or None when it is absent or unreadable."""
    found = read(path)
    return found[0] if found is not None else None


def store(path: Path, record: Record, key: str | None = None) -> None:
    """Write the record, with the key of its entry when given, atomically; a cache that
    cannot be written is skipped silently."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=path.parent, suffix=TEMP_SUFFIX)
    except OSError:
        return
    try:
        with os.fdopen(handle, "w", encoding=ENCODING) as output:
            data = asdict(record) if key is None else {**asdict(record), FIELD_KEY: key}
            json.dump(data, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temp)
