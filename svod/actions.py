"""Actions: bash scripts of the profile the engine runs for one subject, with its environment.

An action is `<profile>/actions/<name>.sh`, run as `bash <script> [extra args]` without a shell
around it, in the store root, with the output going to the terminal as it is and the exit code
handed back. Scripts keep themselves idempotent: each checks what is already done and exits 0.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import os
import re
import shlex
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .subject import ATTR_FRONTMATTER

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import Pipeline
    from .subject import Subject

ACTIONS_DIR = "actions"
ACTION_SUFFIX = ".sh"
ACTION_GLOB = f"*{ACTION_SUFFIX}"
ACTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
SHELL = "bash"
ACTION_TIMEOUT = 600
EXIT_TIMEOUT = 124
STOP_GRACE_SEC = 2
STOP_POLL_SEC = .01
ENCODING = "utf-8"
COMMENT = "#"
SHEBANG = "#!"

ENV_PREFIX = "SVOD_"
ENV_ROOT = "SVOD_ROOT"
ENV_ID = "SVOD_ID"
ENV_KEY = "SVOD_KEY"
ENV_PIPELINE = "SVOD_PIPELINE"
ENV_KIND = "SVOD_KIND"
ENV_SERVICES = "SVOD_SERVICES"
ENV_SUBJECT_PATH = "SVOD_SUBJECT_PATH"
ENV_LOCALE = "SVOD_LOCALE"
ENV_SERVICE_PREFIX = "SVOD_SERVICE_"
ENV_FM_PREFIX = "SVOD_FM_"
ENV_CHECKS_PREFIX = "SVOD_CHECKS_"
PROFILE_CHECKS = "checks"
PROFILE_CONFIG = "profile_config"
ENV_GENERATED_PREFIXES = (ENV_SERVICE_PREFIX, ENV_FM_PREFIX)
ENV_NAME_INVALID = re.compile(r"[^A-Z0-9_]")
ENV_NAME_REPLACEMENT = "_"
SERVICES_SEPARATOR = ","
FIELD_KIND = "kind"
FIELD_SERVICES = "services"
FIELD_SERVICE_PATH = "path"
CONFIG_SERVICES = "services"
OWN_FIELDS = frozenset({FIELD_KIND, FIELD_SERVICES})
TRUE_TEXT = "true"
FALSE_TEXT = "false"
MISSING_SCRIPT = "{source}: steps[{index}]: action script not found: {script}"


@dataclass(frozen=True)
class Action:
    """One script of the profile: its name, path and the first comment line as description."""

    name: str
    path: Path
    description: str


def actions_dir(ctx: Context) -> Path:
    """Directory of the action scripts of the profile."""
    return ctx.config.profile / ACTIONS_DIR


def script_path(ctx: Context, name: str) -> Path | None:
    """Script of the action, or None for a name outside the syntax or without a file."""
    if not ACTION_NAME_RE.fullmatch(name):
        return None
    path = actions_dir(ctx) / f"{name}{ACTION_SUFFIX}"
    return path if path.is_file() else None


def description(path: Path) -> str:
    """First comment line of a script after its shebang, without the comment sign; else empty."""
    try:
        with open(path, encoding=ENCODING, errors="replace") as fh:
            for line in fh:
                text = line.strip()
                if not text or text.startswith(SHEBANG):
                    continue
                return text[len(COMMENT):].strip() if text.startswith(COMMENT) else ""
    except OSError:
        return ""
    return ""


def list_actions(ctx: Context) -> list[Action]:
    """Actions of the profile sorted by name; files outside the name syntax are left out."""
    directory = actions_dir(ctx)
    if not directory.is_dir():
        return []
    return [Action(path.stem, path, description(path))
            for path in sorted(directory.glob(ACTION_GLOB))
            if path.is_file() and ACTION_NAME_RE.fullmatch(path.stem)]


def action_errors(ctx: Context, pipelines: Sequence[Pipeline]) -> list[str]:
    """Errors for steps naming an action without a script in the profile."""
    errors = []
    for pipeline in pipelines:
        for index, step in enumerate(pipeline.steps):
            if step.action and script_path(ctx, step.action) is None:
                script = Path(ACTIONS_DIR) / f"{step.action}{ACTION_SUFFIX}"
                errors.append(MISSING_SCRIPT.format(source=pipeline.source.name, index=index,
                                                    script=script.as_posix()))
    return errors


def env_name(prefix: str, name: str) -> str:
    """Environment variable of a name: the prefix and the name in upper case, other signs as _."""
    return prefix + ENV_NAME_INVALID.sub(ENV_NAME_REPLACEMENT, str(name).upper())


def scalar_text(value: Any) -> str | None:
    """Text of a scalar frontmatter value; None for a list, a mapping or another structure."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return TRUE_TEXT if value else FALSE_TEXT
    if isinstance(value, (str, int, float)):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return None


def subject_services(frontmatter: Mapping[str, Any]) -> list[str]:
    """Service names of the frontmatter field services: a list, or a comma separated string."""
    value = frontmatter.get(FIELD_SERVICES)
    if isinstance(value, str):
        items = value.split(SERVICES_SEPARATOR)
    elif isinstance(value, list):
        items = [str(item) for item in value if scalar_text(item)]
    else:
        return []
    return [item.strip() for item in items if item.strip()]


def service_path(root: Path, value: Any) -> str | None:
    """Absolute path of a service declared in svod.yaml: a path, or a mapping with a path."""
    if isinstance(value, Mapping):
        value = value.get(FIELD_SERVICE_PATH)
    else:
        value = getattr(value, FIELD_SERVICE_PATH, value)
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return None
    return str((root / value).resolve())


def check_commands(profile_config: Mapping[str, Any]) -> dict[str, str]:
    """Check command of each service from profile_config.checks, as a shell line.

    A list is an argv, quoted for the shell; a string is taken as written; other values are
    left out.
    """
    checks = profile_config.get(PROFILE_CHECKS)
    found = {}
    for name, value in (checks.items() if isinstance(checks, Mapping) else ()):
        if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
            found[str(name)] = shlex.join(value)
        elif isinstance(value, str) and value.strip():
            found[str(name)] = value
    return found


def action_env(ctx: Context, pipeline: Pipeline, subject: Subject,
               base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment of an action: the base (the process environment) and the SVOD_ variables.

    Inherited SVOD_SERVICE_ and SVOD_FM_ variables are dropped, so a script sees only those
    of its own subject and store. SVOD_CHECKS_<NAME> comes from profile_config.checks unless
    the environment already sets it.
    """
    env = {name: value for name, value in (os.environ if base is None else base).items()
           if not name.startswith(ENV_GENERATED_PREFIXES)}
    frontmatter = subject.attrs.get(ATTR_FRONTMATTER) or {}
    services = getattr(ctx.config, CONFIG_SERVICES, None) or {}
    for name, value in services.items():
        path = service_path(ctx.root, value)
        if path is not None:
            env[env_name(ENV_SERVICE_PREFIX, name)] = path
    for name, command in check_commands(getattr(ctx.config, PROFILE_CONFIG, None) or {}).items():
        env.setdefault(env_name(ENV_CHECKS_PREFIX, name), command)
    for name, value in frontmatter.items():
        text = scalar_text(value)
        if name not in OWN_FIELDS and text is not None:
            env[env_name(ENV_FM_PREFIX, name)] = text
    kind = scalar_text(frontmatter.get(FIELD_KIND))
    env.update({
        ENV_ROOT: str(ctx.root),
        ENV_ID: subject.id,
        ENV_KEY: min(subject.keys) if subject.keys else "",
        ENV_PIPELINE: pipeline.name,
        ENV_KIND: kind or "",
        ENV_SERVICES: SERVICES_SEPARATOR.join(subject_services(frontmatter)),
        ENV_SUBJECT_PATH: str(subject.path) if subject.path is not None else "",
        ENV_LOCALE: ctx.config.locale,
    })
    return env


@dataclass(frozen=True)
class Run:
    """Exit code of one run of an action and whether the timeout stopped it."""

    code: int
    timed_out: bool = False


def stop_group(process: subprocess.Popen) -> None:
    """Stop the process group of an action that overran or was interrupted, then reap it.

    Without POSIX process groups only the script itself is killed.
    """
    if os.name != "posix":
        process.kill()
        process.wait()
        return

    def send(sig: int) -> None:
        """Signal the group; a group already gone needs nothing."""
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, sig)
    send(signal.SIGTERM)
    until = time.monotonic() + STOP_GRACE_SEC
    while time.monotonic() < until and process.poll() is None:
        time.sleep(STOP_POLL_SEC)
    send(signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=STOP_GRACE_SEC)


def record_run(ctx: Context, action: str, pipeline: Pipeline, subject: Subject,
               code: int, started: dt.datetime, seconds: float) -> None:
    """Journal one run of an action.

    A placeholder: svod.evidence_log replaces it with the record of the run in the evidence
    journal; until then a run leaves no record.
    """


def run_action(ctx: Context, action: str, pipeline: Pipeline, subject: Subject,
               extra: Sequence[str] = (), timeout: float = ACTION_TIMEOUT) -> Run:
    """Run the script of the action for the subject; return its exit code and timeout flag.

    The code is EXIT_TIMEOUT when the script overran the timeout; its process group is stopped
    then and on an interrupt. A script that cannot start raises OSError.
    """
    script = script_path(ctx, action)
    if script is None:
        raise FileNotFoundError(actions_dir(ctx) / f"{action}{ACTION_SUFFIX}")
    started = dt.datetime.now(dt.timezone.utc)
    clock = time.monotonic()
    process = subprocess.Popen([SHELL, str(script), *extra], cwd=ctx.root, shell=False,
                               env=action_env(ctx, pipeline, subject),
                               start_new_session=os.name == "posix")
    try:
        run = Run(process.wait(timeout=timeout))
    except subprocess.TimeoutExpired:
        stop_group(process)
        run = Run(EXIT_TIMEOUT, timed_out=True)
    except BaseException:
        stop_group(process)
        raise
    record_run(ctx, action, pipeline, subject, run.code, started, time.monotonic() - clock)
    return run
