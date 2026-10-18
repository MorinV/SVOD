"""Running an argv: no shell, a timeout, the process group stopped, the tail of the output.

Shared by the command gate and the actions. Stopping the group is cleanup, not a sandbox: a
descendant that creates a session of its own escapes it.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

POSIX = "posix"
NO_BYTECODE_ENV = "PYTHONDONTWRITEBYTECODE"
STOP_GRACE_SEC = 2
STOP_POLL_SEC = .01
ENCODING = "utf-8"
TAIL_LINES = 20
TAIL_CHARS = 2000
# Bytes read from the end of the output for its tail.
TAIL_READ_BYTES = 64 * 1024


def signal_group(process: subprocess.Popen, sig: int) -> bool:
    """Send sig to the process group the child leads; False when the group is gone."""
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Darwin killpg(0) reports EPERM for a zombie-only group. Reap our
        # owned leader if it exited between poll and the probe, then ask the
        # kernel again. Never equate permission denial with group absence:
        # only a subsequent ESRCH proves it has gone.
        if sys.platform != "darwin" or sig != 0:
            raise
        try:
            process.wait(timeout=STOP_GRACE_SEC)
        except subprocess.TimeoutExpired as exc:
            raise PermissionError(
                "process group probe denied while owned child remains alive") from exc
        # Zombie descendants can outlive the owned leader's reap while their
        # parent (often init) finishes reaping them. Allow that transition a
        # bounded grace period; persistent denial still propagates.
        until = time.monotonic() + STOP_GRACE_SEC
        while True:
            try:
                os.killpg(process.pid, 0)
                break
            except ProcessLookupError:
                return False
            except PermissionError:
                if time.monotonic() >= until:
                    raise
                time.sleep(STOP_POLL_SEC)
    return True


def stop_group(process: subprocess.Popen) -> None:
    """Stop the process group the child leads, descendants included, then reap the child.

    SIGTERM, up to STOP_GRACE_SEC for the group to go, then SIGKILL; it works after the child
    itself has exited too. Without POSIX process groups only the child is killed. When the
    group cannot be signalled (an OS permission denial), the child is still killed and reaped
    and the error propagates rather than let a caller claim success.
    """
    if os.name != POSIX:
        process.kill()
        process.wait()
        return
    try:
        signal_group(process, signal.SIGTERM)
        until = time.monotonic() + STOP_GRACE_SEC
        while time.monotonic() < until:
            process.poll()
            if not signal_group(process, 0):
                process.wait()
                return
            time.sleep(STOP_POLL_SEC)
        signal_group(process, signal.SIGKILL)
        process.wait(timeout=STOP_GRACE_SEC)
    except BaseException:
        try:
            if process.poll() is None:
                process.kill()
        finally:
            process.wait(timeout=STOP_GRACE_SEC)
        raise


def run_argv(argv: Sequence[str], cwd: str | Path, output: IO[bytes] | int | None,
             timeout: float, env: Mapping[str, str] | None = None) -> int:
    """Exit code of argv run in cwd without a shell, stdout and stderr together into output.

    The child leads its own POSIX session, and its group is stopped once it exits or on
    timeout; subprocess.TimeoutExpired and the errors of starting it propagate. env is added
    to the environment; bytecode is never written.
    """
    child = subprocess.Popen(list(argv), cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                             shell=False, start_new_session=True,
                             env={**os.environ, **(env or {}), NO_BYTECODE_ENV: "1"})
    try:
        return child.wait(timeout=timeout)
    finally:
        stop_group(child)


def output_tail(output: IO[bytes]) -> str:
    """Last TAIL_LINES lines of the output, at most TAIL_CHARS characters from its end."""
    size = output.seek(0, os.SEEK_END)
    output.seek(max(0, size - TAIL_READ_BYTES))
    text = output.read().decode(ENCODING, "replace")
    lines = text.rstrip().splitlines()[-TAIL_LINES:]
    return "\n".join(lines)[-TAIL_CHARS:]
