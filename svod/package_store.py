"""Private authoritative package state; atomic fsync writes and POSIX single-writer locks."""
from __future__ import annotations

import copy
import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .packages import ID, digest, safe_path


@contextmanager
def lock(directory: Path, *, create: bool = True):
    path = safe_path(directory, "writer.lock")
    flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
    fd = os.open(path, flags, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("run writer is active") from exc
        yield
    finally:
        os.close(fd)


def save(directory: Path, state: dict[str, Any]) -> None:
    state["revision"] += 1
    data = json.dumps(state, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    target = safe_path(directory, "state.json")
    temporary = directory / f"state-{uuid.uuid4().hex}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def base(root: Path) -> Path:
    return safe_path(root, ".svod/package-runs")


def create(root: Path, record: str, package: dict[str, Any], snapshot: str,
           boundary: dict[str, Any]):
    directory = base(root)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    # These files must stay outside Git even in stores that only ignore .svod/lib.
    ignored = safe_path(directory, ".gitignore")
    if not ignored.exists():
        ignored.write_text("*\n")
        os.chmod(ignored, 0o600)
    run_id = "run-" + uuid.uuid4().hex
    directory = directory / run_id
    directory.mkdir(mode=0o700)
    fd = os.open(directory / "writer.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    state = {"version": 1, "run_id": run_id, "record": record, "package": package,
             "package_digest": digest(json.dumps(package, sort_keys=True).encode()),
             "snapshot": snapshot, "boundary": boundary, "revision": 0,
             "status": "pending", "reason": None,
             "steps": [{"id": s["id"], "step_id": s["step_id"], "status": "pending",
                        "code": None, "timed_out": False, "logs": [], "excerpt": ""}
                       for s in package["steps"]]}
    save(directory, state)
    return directory, state


def load(root: Path, record: str, run_id: str):
    if not ID.fullmatch(run_id):
        raise ValueError("invalid run ID")
    directory = safe_path(base(root), run_id)
    if directory.stat().st_mode & 0o077:
        raise ValueError("run directory is not private")
    state_path = safe_path(directory, "state.json")
    if state_path.stat().st_mode & 0o077:
        raise ValueError("run state is not private")
    state = json.loads(state_path.read_bytes())
    if (state["version"] != 1 or state["run_id"] != run_id or state["record"] != record
            or state["package_digest"] != digest(json.dumps(state["package"],
                                                            sort_keys=True).encode())
            or not isinstance(state["revision"], int) or not isinstance(state["steps"], list)
            or [s["id"] for s in state["steps"]] != [s["id"] for s in state["package"]["steps"]]):
        raise ValueError("corrupt or mismatched run state")
    if (state["status"] not in {"pending", "running", "waiting", "stopped", "succeeded"}
            or any(s["status"] not in {"pending", "running", "succeeded", "failed"}
                   or not isinstance(s["logs"], list) or not isinstance(s["excerpt"], str)
                   or s["step_id"] != p["step_id"]
                   or (s["status"] == "succeeded" and (s["code"] != 0 or not s["logs"]))
                   or (s["status"] == "failed" and (s["code"] in (None, 0) or not s["logs"]))
                   for s, p in zip(state["steps"], state["package"]["steps"], strict=True))):
        raise ValueError("corrupt saved step state")
    return directory, state


def observed(directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Read-only crash projection. Never repair or rewrite saved state."""
    if state["status"] not in ("running", "pending"):
        return state
    try:
        with lock(directory, create=False):
            state = copy.deepcopy(state)
            state.update(status="unknown",
                         reason="writer ended without terminal state; USER inspection required")
            for step in state["steps"]:
                if step["status"] == "running":
                    step["status"] = "unknown"
    except ValueError:
        pass  # A live writer still owns the run.
    return state
