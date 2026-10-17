"""Results of the command gate kept between runs, keyed by what the command can read.

An entry lives in <git common dir>/svod-command-cache/<key>.json, shared by every worktree of
the repository. The key is sha256 over the argv, the env, the place of the directory in its
repository, HEAD, the status, the content of every changed or untracked file and of the watched
files. Nothing is cached outside a git repository.
"""
from __future__ import annotations

import contextlib
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
ENTRY_SUFFIX = ".json"
TEMP_SUFFIX = ".tmp"
GIT_DIR = ".git"
NUL = "\0"
TOPLEVEL = ("rev-parse", "--show-toplevel")
HEAD = ("rev-parse", "--verify", "--quiet", "HEAD")
STATUS = (*git.QUOTE_PATH_OFF, "status", "--porcelain", "--untracked-files=all")
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


def entry(cwd: str | Path, argv: list[str], env: dict[str, str] | None = None,
          watch: list[str] | None = None, cache: RunCache | None = None) -> Path | None:
    """Cache file of the command in cwd as the directory is now, or None outside git.

    cache runs git (a fresh RunCache by default); None also when a git call fails.
    """
    cache = cache or RunCache()
    cwd = Path(cwd)
    cache.prefetch([(cwd, git.COMMON_DIR), (cwd, TOPLEVEL)])
    common, top = cache.git(cwd, *git.COMMON_DIR), cache.git(cwd, *TOPLEVEL)
    if not common.ok or not top.ok:
        return None
    root = Path(top.out)
    head = cache.git(root, *HEAD)
    listing = CHANGED if head.ok else TRACKED
    cache.prefetch([(root, STATUS), (root, listing), (root, UNTRACKED)])
    status, changed, untracked = (cache.git(root, *args) for args in (STATUS, listing, UNTRACKED))
    if not (status.ok and changed.ok and untracked.ok):
        return None
    try:
        place = cwd.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        place = str(cwd.resolve())
    material = {
        "argv": list(argv), "env": sorted((env or {}).items()), "place": place,
        "head": head.out if head.ok else "", "status": status.out,
        "dirty": files_digest(root, sorted(set(names(changed)) | set(names(untracked)))),
        "watch": files_digest(cwd, watched(cwd, watch)) if watch else None,
    }
    key = hashlib.sha256(json.dumps(material, sort_keys=True).encode(ENCODING)).hexdigest()
    return (cwd / common.out).resolve() / CACHE_DIR / f"{key}{ENTRY_SUFFIX}"


def load(path: Path) -> Record | None:
    """Record stored in the cache file, or None when it is absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
        return Record(code=int(data["code"]), tail=str(data["tail"]), time=str(data["time"]),
                      duration=float(data["duration"]))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def store(path: Path, record: Record) -> None:
    """Write the record atomically; a cache that cannot be written is skipped silently."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp = tempfile.mkstemp(dir=path.parent, suffix=TEMP_SUFFIX)
    except OSError:
        return
    try:
        with os.fdopen(handle, "w", encoding=ENCODING) as output:
            json.dump(asdict(record), output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temp)
