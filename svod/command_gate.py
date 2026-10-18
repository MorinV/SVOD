"""The command gate: a script decides the step, its result cached until the source changes.

With on: current (the default) the command runs only while its step is the current one, or
inside fresh_commands() (svod status --fresh); elsewhere the gate shows the last result, marked
stale when the source changed since.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import os
import shlex
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from . import command_cache, keys
from .cache import RunCache
from .errors import ParamError
from .gates import CORE_GATES, Gate, Result, Status, non_empty_strings, unknown
from .git import COMMON_DIR
from .run import output_tail, run_argv

if TYPE_CHECKING:
    from .context import Context
    from .locale import Locale
    from .pipeline import GateRef, Pipeline, Step
    from .subject import Subject

PARAM_ARGV = "argv"
PARAM_SERVICE = "service"
PARAM_CWD = "cwd"
PARAM_TIMEOUT = "timeout"
PARAM_WATCH = "watch"
PARAM_ENV = "env"
PARAM_CACHE = "cache"
PARAM_ON = "on"
ON_CURRENT = "current"
ON_ALWAYS = "always"
ON_VALUES = (ON_CURRENT, ON_ALWAYS)
FACT_CODE = "code"
FACT_DETAIL = "detail"
FACT_CACHED = "cached"
FACT_DURATION = "duration"
FACT_STALE = "stale"
FACT_AGE = "age"
MARK_KEYS = {Status.PASS: keys.MARK_PASS, Status.FAIL: keys.MARK_FAIL,
             Status.UNKNOWN: keys.MARK_UNKNOWN}
# Age of a result: seconds below a minute, then minutes, hours, days.
AGE_UNITS = ((86400, "d"), (3600, "h"), (60, "m"))
AGE_SECONDS = "s"
DESCRIBE_COMMAND = "gate.command"
DEFAULT_TIMEOUT_SEC = 120
DURATION_DIGITS = 3
EXIT_OK = 0
STORE_ROOT = "."
PARENT = ".."
MEMO = "command"
MEMO_CURRENT = "command-current"
ENCODING = "utf-8"
POSIX = "posix"
SERVICES_ATTR = "services"
CACHE_IGNORE_ATTR = "cache_ignore"
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
REASON_NOT_RUN = ("command: not run yet; it runs when its step is current, "
                  "or with svod status --fresh")
# Where and what a command runs: directory, substituted argv, environment.
Place = tuple[Path, list[str], dict[str, str]]
# Set by fresh_commands(): every command gate runs as if its step were current.
FRESH: contextvars.ContextVar[bool] = contextvars.ContextVar("svod_command_fresh",
                                                             default=False)


@contextlib.contextmanager
def fresh_commands(fresh: bool = True) -> Iterator[None]:
    """Within the block, commands of on: current run whatever step is current."""
    token = FRESH.set(fresh)
    try:
        yield
    finally:
        FRESH.reset(token)


def age_text(seconds: float) -> str:
    """Age as one unit, rounded down: 45s, 3m, 2h, 4d."""
    seconds = max(0, int(seconds))
    for size, unit in AGE_UNITS:
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}{AGE_SECONDS}"


def record_age(record: command_cache.Record) -> str:
    """Time since the run of the record ended; empty when its time cannot be read."""
    try:
        started = dt.datetime.fromisoformat(record.time)
    except ValueError:
        return ""
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    ended = started + dt.timedelta(seconds=record.duration)
    return age_text((dt.datetime.now(dt.timezone.utc) - ended).total_seconds())


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


def own_ref(ctx: Context, gate: Gate) -> GateRef | None:
    """The use of this gate in a loaded pipeline, or None."""
    return next((ref for pipeline in ctx.pipelines.values() for ref in pipeline.gate_refs()
                 if ref.impl is gate), None)


def holds(step: Step, gate: Gate) -> bool:
    """Whether the gate is one of the step's gates."""
    return any(ref.impl is gate for ref in step.gates)


def subject_steps(ctx: Context, pipeline: Pipeline, subject: Subject) -> list[Step]:
    """Steps of the pipeline that apply to the subject, as position walks them."""
    from .pipeline import step_applies
    from .position import steps_of
    return [step for step in steps_of(ctx, pipeline, subject) if step_applies(step, subject)]


def reached(ctx: Context, pipeline: Pipeline, earlier: list[Step], subject: Subject) -> bool:
    """Whether the subject stands at or after the steps that follow earlier: no blocking entry,
    done does not pass and every earlier step but an optional one passes."""
    from .pipeline import applies, evaluate, first_blocking, run_entries
    if first_blocking(run_entries(ctx, pipeline.entry, subject)) is not None:
        return False
    if pipeline.done is not None and evaluate(ctx, pipeline.done, subject).passed:
        return False
    for step in earlier:
        if step.optional:
            continue
        refs = [ref for ref in step.gates if applies(ref, subject)]
        if not step.gates or not all(evaluate(ctx, ref, subject).passed for ref in refs):
            return False
    return True



def run_command(argv: list[str], cwd: Path, env: dict[str, str],
                timeout: float) -> tuple[command_cache.Record | None, str | None]:
    """(record of one run, None) or (None, the reason the command gave no exit code)."""
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
    UNKNOWN and never cached. With on: current the command runs only while its step is current
    (see is_current) or inside fresh_commands(); otherwise the last result is shown, stale when
    its source changed since, and a command that never ran fails as not run.
    """

    name = "command"
    PARAMS = frozenset({PARAM_ARGV, PARAM_SERVICE, PARAM_CWD, PARAM_TIMEOUT, PARAM_WATCH,
                        PARAM_ENV, PARAM_CACHE, PARAM_ON})
    REQUIRED = frozenset({PARAM_ARGV})

    def __init__(self, params: dict[Any, Any] | None = None) -> None:
        """Params as given; a key true is on, which YAML 1.1 reads as a boolean."""
        if isinstance(params, dict) and True in params:
            params = {(PARAM_ON if key is True else key): value for key, value in params.items()}
        super().__init__(params)

    def check(self) -> None:
        """argv and watch are non-empty lists; one place at most; a positive timeout."""
        if not non_empty_strings(self.params[PARAM_ARGV]):
            raise ParamError(f"{self.name}: {PARAM_ARGV} must be a non-empty list of strings")
        if PARAM_SERVICE in self.params and PARAM_CWD in self.params:
            raise ParamError(f"{self.name}: at most one of {PARAM_SERVICE} and {PARAM_CWD}")
        self.require_type(PARAM_SERVICE, str, "a string")
        self.require_type(PARAM_CWD, str, "a string")
        self.require_type(PARAM_CACHE, bool, "a boolean")
        if self.params.get(PARAM_ON, ON_CURRENT) not in ON_VALUES:
            raise ParamError(f"{self.name}: {PARAM_ON} must be one of {', '.join(ON_VALUES)}")
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

    def place(self, ctx: Context, subject: Subject) -> Place | Result:
        """(directory, substituted argv, env) of the command, or the UNKNOWN result."""
        if os.name != POSIX:
            return self.unknown(REASON_POSIX)
        cwd, reason = self.directory(ctx, subject)
        if cwd is None:
            return self.unknown(reason or "")
        argv = substitute(list(self.params[PARAM_ARGV]), ctx, subject)
        env = {**action_vars(ctx, self, subject), **(self.params.get(PARAM_ENV) or {})}
        return cwd, argv, env

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Exit code of the command; facts code, detail (tail of the output), cached, duration,
        stale and age."""
        found = self.place(ctx, subject)
        if isinstance(found, Result):
            return found
        cwd, argv, env = found
        memo = (MEMO, str(cwd), tuple(argv), tuple(sorted(env.items())),
                tuple(self.params.get(PARAM_WATCH) or ()), self.params.get(PARAM_CACHE, True))
        return ctx.cache.value(memo, lambda: self.outcome(ctx, subject, cwd, argv, env))

    def entry(self, ctx: Context, cwd: Path, argv: list[str], env: dict[str, str],
              cache: RunCache) -> Path | None:
        """Cache file of the command as its source is now; None uncached or outside git."""
        if not self.params.get(PARAM_CACHE, True):
            return None
        ignore = getattr(ctx.config, CACHE_IGNORE_ATTR, None) or ()
        return command_cache.entry(cwd, argv, env, self.params.get(PARAM_WATCH), cache,
                                   ignore)

    def outcome(self, ctx: Context, subject: Subject, cwd: Path, argv: list[str],
                env: dict[str, str]) -> Result:
        """Result from the disk cache when the directory did not change, from a run while the
        step is current, else the last result.

        A run is stored only when git sees the directory as before it: a command that wrote
        into the source would make its own result stale. The last result is stored always.
        """
        entry = self.entry(ctx, cwd, argv, env, ctx.cache)
        record = command_cache.load(entry) if entry is not None else None
        if record is not None:
            return self.result(record, cached=True)
        last_path = command_cache.last_entry(cwd, argv, env, ctx.cache)
        last = command_cache.read(last_path) if last_path is not None else None
        if not self.runs_now(ctx, subject, last[0] if last else None):
            if last is None:
                return self.not_run(ctx)
            stale = entry is None or last[1] != entry.stem
            return self.shown(ctx, self.result(last[0], cached=True, stale=stale))
        from .actions import trust_required, trust_snapshot_reason
        pipeline = own_pipeline(ctx, self)
        if pipeline is not None and trust_required(ctx, subject):
            reason = trust_snapshot_reason(ctx, pipeline, subject)
            if reason:
                return self.unknown(reason)
        record, reason = run_command(argv, cwd, env,
                                     self.params.get(PARAM_TIMEOUT, DEFAULT_TIMEOUT_SEC))
        if record is None:
            return self.unknown(reason or "")
        if entry is not None and self.entry(ctx, cwd, argv, env, RunCache()) == entry:
            command_cache.store(entry, record)
        if last_path is not None:
            command_cache.store(last_path, record, entry.stem if entry is not None else "")
        return self.result(record, cached=False)

    def known(self, ctx: Context, subject: Subject) -> Result | None:
        """The result as known without running: the disk cache, else the last result."""
        found = self.place(ctx, subject)
        if isinstance(found, Result):
            return found
        cwd, argv, env = found
        entry = self.entry(ctx, cwd, argv, env, ctx.cache)
        record = command_cache.load(entry) if entry is not None else None
        if record is None:
            path = command_cache.last_entry(cwd, argv, env, ctx.cache)
            last = command_cache.read(path) if path is not None else None
            record = last[0] if last is not None else None
        return self.result(record, cached=True) if record is not None else None

    def runs_now(self, ctx: Context, subject: Subject,
                 last: command_cache.Record | None) -> bool:
        """Whether the command runs: on: always, fresh_commands(), or its step is current."""
        if self.params.get(PARAM_ON, ON_CURRENT) == ON_ALWAYS or FRESH.get():
            return True
        return self.is_current(ctx, subject, last)

    def is_current(self, ctx: Context, subject: Subject,
                   last: command_cache.Record | None) -> bool:
        """Whether the step of this gate is the current step of the subject.

        As status sees it: the subject is not done, no entry blocks, every earlier step but an
        optional one passes, and the step itself does not pass on the results already known
        (this gate's last result, the known results of the other command gates of the step).
        A gate outside the steps of a loaded pipeline is always current.
        """
        from .pipeline import applies, evaluate
        pipeline = own_pipeline(ctx, self)
        if pipeline is None or not any(holds(step, self) for step in pipeline.steps):
            return True
        steps = subject_steps(ctx, pipeline, subject)
        index = next((i for i, step in enumerate(steps) if holds(step, self)), None)
        if index is None:
            return True
        step = steps[index]
        memo = (MEMO_CURRENT, pipeline.name, subject.id, str(subject.path), step.id)
        if not ctx.cache.value(memo, lambda: reached(ctx, pipeline, steps[:index], subject)):
            return False
        if last is None or last.code != EXIT_OK:
            return True
        for ref in step.gates:
            if ref.impl is self or not applies(ref, subject):
                continue
            if isinstance(ref.impl, CommandGate):
                result = ref.impl.known(ctx, subject)
                if result is None or not result.passed:
                    return True
            elif not evaluate(ctx, ref, subject).passed:
                return True
        return False

    @staticmethod
    def result(record: command_cache.Record, cached: bool, stale: bool = False) -> Result:
        """PASS on exit code 0, else FAIL, with the facts of the record; the age when cached."""
        status = Status.PASS if record.code == EXIT_OK else Status.FAIL
        return Result(status, {FACT_CODE: record.code, FACT_DETAIL: record.tail,
                               FACT_CACHED: cached, FACT_DURATION: record.duration,
                               FACT_STALE: stale, FACT_AGE: record_age(record) if cached else ""})

    @staticmethod
    def unknown(reason: str) -> Result:
        """UNKNOWN with the reason, and empty facts so that texts still render."""
        return unknown(reason, **{FACT_CODE: "", FACT_DETAIL: reason, FACT_CACHED: False,
                                  FACT_DURATION: "", FACT_STALE: False, FACT_AGE: ""})

    def not_run(self, ctx: Context) -> Result:
        """FAIL of a command that never ran here: its step was never current."""
        result = Result(Status.FAIL, {FACT_CODE: "", FACT_DETAIL: REASON_NOT_RUN,
                                      FACT_CACHED: False, FACT_DURATION: "", FACT_STALE: False,
                                      FACT_AGE: ""})
        return self.shown(ctx, result, keys.MARK_NOT_RUN)

    def shown(self, ctx: Context, result: Result, key: str = keys.MARK_STALE) -> Result:
        """The result with its mark saying stale and the age (or not run) when it is either."""
        if key == keys.MARK_STALE and not result.facts[FACT_STALE]:
            return result
        ref = own_ref(ctx, self)
        if ctx.locale is None or ref is None or not ref.label:
            return result
        label = ctx.locale.text(ref.label, **result.facts)
        mark = ctx.locale.text(MARK_KEYS[result.status], label=label)
        return replace(result, display=ctx.locale.text(key, mark=mark,
                                                       age=result.facts[FACT_AGE]))

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The command exits with 0 in the service, the directory or the store root."""
        where = params.get(PARAM_SERVICE) or params.get(PARAM_CWD) or STORE_ROOT
        return locale.text(DESCRIBE_COMMAND, argv=shlex.join(params[PARAM_ARGV]), where=where)


# CORE_GATES is inferred from the classes of gates.py; the cast admits one more Gate class.
cast(dict[str, type[Gate]], CORE_GATES)[CommandGate.name] = CommandGate
