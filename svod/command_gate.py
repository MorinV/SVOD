"""The command gate: a script decides the step, its result cached until the source changes."""
from __future__ import annotations

import datetime as dt
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Any, cast

from . import command_cache
from .cache import RunCache
from .errors import ParamError
from .gates import CORE_GATES, Gate, Result, Status, non_empty_strings, unknown
from .git import COMMON_DIR

if TYPE_CHECKING:
    from .context import Context
    from .locale import Locale
    from .pipeline import Pipeline
    from .subject import Subject

PARAM_ARGV = "argv"
PARAM_SERVICE = "service"
PARAM_CWD = "cwd"
PARAM_TIMEOUT = "timeout"
PARAM_WATCH = "watch"
PARAM_ENV = "env"
PARAM_CACHE = "cache"
FACT_CODE = "code"
FACT_DETAIL = "detail"
FACT_CACHED = "cached"
FACT_DURATION = "duration"
DESCRIBE_COMMAND = "gate.command"
DEFAULT_TIMEOUT_SEC = 120
TAIL_LINES = 20
TAIL_CHARS = 2000
# Bytes read from the end of the output for its tail.
TAIL_READ_BYTES = 64 * 1024
DURATION_DIGITS = 3
EXIT_OK = 0
STORE_ROOT = "."
PARENT = ".."
MEMO = "command"
ENCODING = "utf-8"
POSIX = "posix"
SERVICES_ATTR = "services"
WORKTREES_ATTR = "worktrees"
# Placeholders of argv: the subject id, its path relative to the store root, the store root.
SUB_ID = "{id}"
SUB_PATH = "{path}"
SUB_ROOT = "{root}"
REASON_POSIX = "command: running a command requires POSIX"
REASON_SERVICE = "command: service {service} is not declared in services of svod.yaml"
REASON_CWD = "command: directory not found: {cwd}"
REASON_TIMEOUT = "command: {argv} did not finish in {timeout}s"
REASON_START = "command: {argv} could not start: {error}"


def common_dir(ctx: Context, path: Path) -> Path | None:
    """Resolved git common directory of a checkout, or None when git fails."""
    out = ctx.cache.git(path, *COMMON_DIR)
    return (path / out.out).resolve() if out.ok else None


def workspace_gate(ctx: Context) -> Any:
    """Instance of the gate named by workspace_gate in svod.yaml, or None.

    The class is found among the gates the loaded pipelines use, else among the core gates.
    """
    name = ctx.config.workspace_gate
    if not name:
        return None
    classes = {type(ref.impl) for p in ctx.pipelines.values() for ref in p.gate_refs()
               if ref.impl is not None and ref.impl.name == name}
    cls = next(iter(classes), None) or CORE_GATES.get(name)
    if cls is None or not hasattr(cls, WORKTREES_ATTR):
        return None
    try:
        return cls()
    except ParamError:
        return None


def subject_worktree(ctx: Context, subject: Subject, service: Path) -> Path | None:
    """Work directory of the subject in the repository of the service, or None when unknown."""
    gate = workspace_gate(ctx) if subject.keys else None
    if gate is None:
        return None
    target = common_dir(ctx, service)
    if target is None:
        return None
    pairs, _ = gate.worktrees(ctx, subject.keys)
    return next((Path(path) for path, _ in pairs if common_dir(ctx, Path(path)) == target), None)


def subject_rel(ctx: Context, subject: Subject) -> str:
    """Path of the subject relative to the store root; the id when it has no path there."""
    if subject.path is None:
        return subject.id
    path = Path(subject.path)
    path = path if path.is_absolute() else ctx.root / path
    try:
        return path.resolve().relative_to(ctx.root.resolve()).as_posix()
    except ValueError:
        return str(path)


def substitute(argv: list[str], ctx: Context, subject: Subject) -> list[str]:
    """argv with {id}, {path} and {root} replaced in every item; other braces stay as written."""
    values = ((SUB_ID, subject.id), (SUB_PATH, subject_rel(ctx, subject)),
              (SUB_ROOT, str(ctx.root)))
    out = []
    for item in argv:
        for token, value in values:
            item = item.replace(token, value)
        out.append(item)
    return out


def own_pipeline(ctx: Context, gate: Gate) -> Pipeline | None:
    """The loaded pipeline holding this gate use, or None."""
    return next((pipeline for pipeline in ctx.pipelines.values()
                 if any(ref.impl is gate for ref in pipeline.gate_refs())), None)


def action_vars(ctx: Context, gate: Gate, subject: Subject) -> dict[str, str]:
    """SVOD_ variables an action of the subject gets, with SVOD_ACTION empty; {} outside a
    loaded pipeline. SVOD_CHECKS_<NAME> already set in the environment wins, as for actions."""
    from .actions import ENV_ACTION, ENV_CHECKS_PREFIX, action_env

    pipeline = own_pipeline(ctx, gate)
    if pipeline is None:
        return {}
    base = {name: value for name, value in os.environ.items()
            if name.startswith(ENV_CHECKS_PREFIX)}
    return {**action_env(ctx, pipeline, subject, base=base), ENV_ACTION: ""}


def output_tail(output: IO[bytes]) -> str:
    """Last TAIL_LINES lines of the output, at most TAIL_CHARS characters from its end."""
    size = output.seek(0, os.SEEK_END)
    output.seek(max(0, size - TAIL_READ_BYTES))
    text = output.read().decode(ENCODING, "replace")
    lines = text.rstrip().splitlines()[-TAIL_LINES:]
    return "\n".join(lines)[-TAIL_CHARS:]


def run_command(argv: list[str], cwd: Path, env: dict[str, str],
                timeout: float) -> tuple[command_cache.Record | None, str | None]:
    """(record of one run, None) or (None, the reason the command gave no exit code)."""
    from .local_runner import run_argv
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    clock = time.monotonic()
    shown = shlex.join(argv)
    with tempfile.TemporaryFile() as output:
        try:
            code = run_argv(argv, cwd, output, timeout, env)
        except subprocess.TimeoutExpired:
            return None, REASON_TIMEOUT.format(argv=shown, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return None, REASON_START.format(argv=shown, error=exc)
        tail = output_tail(output)
    duration = round(time.monotonic() - clock, DURATION_DIGITS)
    return command_cache.Record(code, tail, started, duration), None


class CommandGate(Gate):
    """Passes when a command exits with 0; the result is kept until what it reads changes.

    The command runs without a shell in the work directory of the subject for a service, in a
    directory of the store or in the store root, with {id}, {path} and {root} of argv replaced
    and the SVOD_ variables of an action of the subject added to its environment. Its result
    is cached on disk per repository and per run in memory; a command that cannot finish is
    UNKNOWN and never cached.
    """

    name = "command"
    PARAMS = frozenset({PARAM_ARGV, PARAM_SERVICE, PARAM_CWD, PARAM_TIMEOUT, PARAM_WATCH,
                        PARAM_ENV, PARAM_CACHE})
    REQUIRED = frozenset({PARAM_ARGV})

    def check(self) -> None:
        """argv and watch are non-empty lists; one place at most; a positive timeout."""
        if not non_empty_strings(self.params[PARAM_ARGV]):
            raise ParamError(f"{self.name}: {PARAM_ARGV} must be a non-empty list of strings")
        if PARAM_SERVICE in self.params and PARAM_CWD in self.params:
            raise ParamError(f"{self.name}: at most one of {PARAM_SERVICE} and {PARAM_CWD}")
        self.require_type(PARAM_SERVICE, str, "a string")
        self.require_type(PARAM_CWD, str, "a string")
        self.require_type(PARAM_CACHE, bool, "a boolean")
        timeout = self.params.get(PARAM_TIMEOUT, DEFAULT_TIMEOUT_SEC)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ParamError(f"{self.name}: {PARAM_TIMEOUT} must be a positive number")
        watch = self.params.get(PARAM_WATCH)
        if watch is not None and (not non_empty_strings(watch) or any(
                PurePosixPath(p).is_absolute() or PARENT in PurePosixPath(p).parts
                for p in watch)):
            raise ParamError(f"{self.name}: {PARAM_WATCH} must be a non-empty list of paths "
                             "or globs inside the directory")
        env = self.params.get(PARAM_ENV)
        if env is not None and not (isinstance(env, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
            raise ParamError(f"{self.name}: {PARAM_ENV} must map names to strings")

    def directory(self, ctx: Context, subject: Subject) -> tuple[Path | None, str | None]:
        """(directory the command runs in, None) or (None, the reason it is unknown)."""
        if PARAM_SERVICE in self.params:
            service = self.params[PARAM_SERVICE]
            path = (getattr(ctx.config, SERVICES_ATTR, None) or {}).get(service)
            if path is None:
                return None, REASON_SERVICE.format(service=service)
            base = (ctx.root / path).resolve()
            cwd = (subject_worktree(ctx, subject, base) if base.is_dir() else None) or base
        else:
            cwd = (ctx.root / self.params.get(PARAM_CWD, STORE_ROOT)).resolve()
        if not cwd.is_dir():
            return None, REASON_CWD.format(cwd=cwd)
        return cwd, None

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Exit code of the command; facts code, detail (tail of the output), cached, duration."""
        if os.name != POSIX:
            return self.unknown(REASON_POSIX)
        cwd, reason = self.directory(ctx, subject)
        if cwd is None:
            return self.unknown(reason or "")
        argv = substitute(list(self.params[PARAM_ARGV]), ctx, subject)
        env = {**action_vars(ctx, self, subject), **(self.params.get(PARAM_ENV) or {})}
        memo = (MEMO, str(cwd), tuple(argv), tuple(sorted(env.items())),
                tuple(self.params.get(PARAM_WATCH) or ()), self.params.get(PARAM_CACHE, True))
        return ctx.cache.value(memo, lambda: self.outcome(ctx, cwd, argv, env))

    def outcome(self, ctx: Context, cwd: Path, argv: list[str], env: dict[str, str]) -> Result:
        """Result from the disk cache when the directory did not change, else from a run.

        A run is stored only when git sees the directory as before it: a command that wrote
        into the source would make its own result stale.
        """
        watch = self.params.get(PARAM_WATCH)
        entry = None
        if self.params.get(PARAM_CACHE, True):
            entry = command_cache.entry(cwd, argv, env, watch, ctx.cache)
        record = command_cache.load(entry) if entry is not None else None
        if record is not None:
            return self.result(record, cached=True)
        record, reason = run_command(argv, cwd, env,
                                     self.params.get(PARAM_TIMEOUT, DEFAULT_TIMEOUT_SEC))
        if record is None:
            return self.unknown(reason or "")
        if entry is not None and command_cache.entry(cwd, argv, env, watch, RunCache()) == entry:
            command_cache.store(entry, record)
        return self.result(record, cached=False)

    @staticmethod
    def result(record: command_cache.Record, cached: bool) -> Result:
        """PASS on exit code 0, else FAIL, with the facts of the record."""
        status = Status.PASS if record.code == EXIT_OK else Status.FAIL
        return Result(status, {FACT_CODE: record.code, FACT_DETAIL: record.tail,
                               FACT_CACHED: cached, FACT_DURATION: record.duration})

    @staticmethod
    def unknown(reason: str) -> Result:
        """UNKNOWN with the reason, and empty facts so that texts still render."""
        return unknown(reason, **{FACT_CODE: "", FACT_DETAIL: reason, FACT_CACHED: False,
                                  FACT_DURATION: ""})

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The command exits with 0 in the service, the directory or the store root."""
        where = params.get(PARAM_SERVICE) or params.get(PARAM_CWD) or STORE_ROOT
        return locale.text(DESCRIBE_COMMAND, argv=shlex.join(params[PARAM_ARGV]), where=where)


# CORE_GATES is inferred from the classes of gates.py; the cast admits one more Gate class.
cast(dict[str, type[Gate]], CORE_GATES)[CommandGate.name] = CommandGate
