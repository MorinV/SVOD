"""Bounded optimistic replacement for planning outputs, with cooperative writer locking."""
from __future__ import annotations

import os
import secrets
from contextlib import contextmanager
from collections.abc import Callable, Iterator
from pathlib import Path

from svod.plan_schema import Invalid


def read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


@contextmanager
def directory(path: Path) -> Iterator[int]:
    """Open each directory without following substituted ancestors."""
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def read_at(descriptor: int, name: str) -> bytes | None:
    try:
        file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
    except FileNotFoundError:
        return None
    with os.fdopen(file, "rb") as stream:
        return stream.read()


def replace(path: Path, content: bytes, expected: bytes | None,
            verify: Callable[[], bool]) -> None:
    """Refuse observed races; keep every write anchored to the original directory."""
    with directory(path.parent) as parent:
        lock = path.name + ".lock"
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
        except FileExistsError as exc:
            raise Invalid("concurrent_write", "Output is locked; retry after inspection") from exc
        temp: str | None = None
        try:
            os.close(descriptor)

            def unchanged() -> bool:
                if read_at(parent, path.name) != expected or not verify():
                    return False
                # Reopen the path without symlinks and compare directory identities.
                with directory(path.parent) as current:
                    return os.fstat(parent) == os.fstat(current)

            if not unchanged():
                raise Invalid("concurrent_write", "Inputs changed; refusing replacement")
            name = ".plan-" + secrets.token_hex(16)
            file = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                           0o600, dir_fd=parent)
            temp = name
            with os.fdopen(file, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if not unchanged():
                raise Invalid("concurrent_write", "Inputs changed; refusing replacement")
            os.replace(temp, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            temp = None
        finally:
            if temp is not None:
                os.unlink(temp, dir_fd=parent)
            os.unlink(lock, dir_fd=parent)
