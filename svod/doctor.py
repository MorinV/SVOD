"""svod doctor: is the store ready to work in? One line per check: ok, warn or fail.

Each check stands alone and reads only what it needs, so a store that does not load still gets
every other answer: svod.yaml, the services, the hooks of Claude Code and Codex, the copy of the
engine, the newest release, the evidence log, the knowledge index and the local config.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__, keys
from .config import (DEFAULT_KNOWLEDGE_DIR, EVIDENCE_ENABLED, FIELD_EVIDENCE, FIELD_KNOWLEDGE,
                     FIELD_LOCAL_CONFIG, FIELD_SERVICES, FIELD_UPDATE_CHECK, KNOWLEDGE_DIR,
                     LOCAL_LOGIN, read_local)
from .errors import LoadError
from .locale import Locale, error_locale
from .paths import CONFIG_FILE
from .yamlio import ENCODING, read_yaml

OK = "ok"
WARN = "warn"
FAIL = "fail"
FORMAT_TEXT = "text"
FORMAT_JSON = "json"
LINE = "{status}: {text}"
DETAIL_INDENT = "  "
EXIT_OK = 0
EXIT_FAILED = 1
CHECK_CONFIG = "config"
CHECK_SERVICE = "service"
CHECK_HOOKS = "hooks"
CHECK_COPY = "copy"
CHECK_VERSION = "version"
CHECK_EVIDENCE = "evidence"
CHECK_KNOWLEDGE = "knowledge"
CHECK_LOCAL = "local_config"
GIT_DIR = ".git"
EVIDENCE_DIR = "evidence"
PROBE_PREFIX = ".svod-doctor-"
PROBE_BYTES = b"svod doctor\n"
CLAUDE_DIR = ".claude"
CLAUDE_CONFIG_ENV = "CLAUDE_CONFIG_DIR"
SETTINGS_FILE = "settings.json"
CODEX_DIR = ".codex"
CODEX_HOME_ENV = "CODEX_HOME"
CODEX_HOOKS_FILE = "hooks.json"
SETUP_COMMAND = ("integrations/setup-claude.sh --project {root} "
                 "(Codex: integrations/setup-codex.sh --project {root})")
HOOKS_FIELD = "hooks"
COMMAND_FIELD = "command"
TYPE_FIELD = "type"
TIMEOUT_FIELD = "timeout"
COMMAND_TYPE = "command"
# What Codex reads of hooks.json (codex-rs/config/src/hook_config.rs): unknown keys are errors.
CODEX_TOP_KEYS = frozenset({"description", HOOKS_FIELD})
CODEX_GROUP_KEYS = frozenset({"matcher", HOOKS_FIELD})
CODEX_HANDLER_KEYS = frozenset({TYPE_FIELD, COMMAND_FIELD, "commandWindows", TIMEOUT_FIELD,
                                "async", "statusMessage", "additionalContextLimit"})
MARKER = "svod"
HOOK_WORD = "hook"
HOOK_EVENTS = ("session-start", "prompt", "pre-tool")
ENV_PROGRAM = "env"
UPDATE_COMMAND = "svod update"
UPGRADE_COMMAND = "pip install --upgrade git+{source}"
LIST_JOIN = ", "


@dataclass(frozen=True)
class Check:
    """One answer of the doctor: what was checked, ok, warn or fail, and the line to print."""

    name: str
    status: str
    text: str
    details: tuple[str, ...] = ()


def raw_config(root: Path) -> tuple[dict[str, Any], list[str]]:
    """svod.yaml as parsed, without validation, and the errors of reading it."""
    try:
        data = read_yaml(root / CONFIG_FILE)
    except LoadError as exc:
        return {}, exc.errors
    return (data, []) if isinstance(data, dict) else ({}, [])


def config_check(root: Path, locale: Locale) -> Check:
    """svod.yaml, the profile and its pipelines, gates and locale load."""
    from .loader import load_runtime
    try:
        runtime = load_runtime(root)
    except LoadError as exc:
        errors = tuple(exc.errors) or ("",)
        return Check(CHECK_CONFIG, FAIL, locale.text(keys.DOCTOR_CONFIG_FAIL, error=errors[0]),
                     errors[1:])
    return Check(CHECK_CONFIG, OK, locale.text(keys.DOCTOR_CONFIG_OK,
                                               count=len(runtime.pipelines)))


def service_checks(root: Path, locale: Locale, data: dict[str, Any]) -> list[Check]:
    """Each service of svod.yaml is a directory under git."""
    services = data.get(FIELD_SERVICES)
    if not isinstance(services, dict) or not services:
        return [Check(CHECK_SERVICE, OK, locale.text(keys.DOCTOR_SERVICES_NONE))]
    found = []
    for name, value in services.items():
        path = (root / str(value)).resolve()
        if not path.is_dir():
            found.append(Check(CHECK_SERVICE, FAIL, locale.text(
                keys.DOCTOR_SERVICE_MISSING, name=name, path=path)))
        elif not (path / GIT_DIR).exists():
            found.append(Check(CHECK_SERVICE, FAIL, locale.text(
                keys.DOCTOR_SERVICE_NOT_GIT, name=name, path=path)))
        else:
            found.append(Check(CHECK_SERVICE, OK, locale.text(
                keys.DOCTOR_SERVICE_OK, name=name, path=path)))
    return found


def settings_files(root: Path, env: dict[str, str] | None = None) -> list[Path]:
    """Files of Claude Code and Codex that may hold the hooks: the store's, then the user's."""
    env = dict(os.environ) if env is None else env
    home = Path(env.get("HOME") or Path.home())
    user = Path(env[CLAUDE_CONFIG_ENV]) if env.get(CLAUDE_CONFIG_ENV) else home / CLAUDE_DIR
    codex = Path(env[CODEX_HOME_ENV]) if env.get(CODEX_HOME_ENV) else home / CODEX_DIR
    return [root / CLAUDE_DIR / SETTINGS_FILE, root / CODEX_DIR / CODEX_HOOKS_FILE,
            user / SETTINGS_FILE, codex / CODEX_HOOKS_FILE]


def unknown_keys(data: dict[str, Any], known: frozenset[str], where: str) -> str | None:
    """Error naming the first key Codex does not read, or None."""
    extra = sorted(set(map(str, data)) - known)
    return f"{where}: unknown key {extra[0]}" if extra else None


def handler_error(hook: Any, where: str, codex: bool) -> str | None:
    """Error of one hook handler, or None: a mapping with a type; for Codex a command handler
    of the keys it reads, with a command and a timeout in whole seconds."""
    if not isinstance(hook, dict) or not isinstance(hook.get(TYPE_FIELD), str):
        return f"{where} must be an object with a type"
    if not codex:
        return None
    timeout = hook.get(TIMEOUT_FIELD, 1)
    if hook[TYPE_FIELD] != COMMAND_TYPE or not isinstance(hook.get(COMMAND_FIELD), str):
        return f"{where} must be a command handler with a command"
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        return f"{where}.{TIMEOUT_FIELD} must be a positive integer"
    return unknown_keys(hook, CODEX_HANDLER_KEYS, where)


def hooks_format_error(data: Any, codex: bool) -> str | None:
    """Where a parsed hooks file departs from the format, or None.

    Both agents: `hooks` maps events to lists of groups, each with a list of handlers. Codex
    (hooks.json) also refuses keys it does not read and wants command handlers.
    """
    if not isinstance(data, dict):
        return "not a JSON object"
    error = unknown_keys(data, CODEX_TOP_KEYS, "top level") if codex else None
    hooks = data.get(HOOKS_FIELD, {})
    if error or not isinstance(hooks, dict):
        return error or f"{HOOKS_FIELD} must be an object"
    for event, groups in hooks.items():
        where = f"{HOOKS_FIELD}.{event}"
        if not isinstance(groups, list):
            return f"{where} must be a list"
        for i, group in enumerate(groups):
            at = f"{where}[{i}]"
            if not isinstance(group, dict) or not isinstance(group.get(HOOKS_FIELD), list):
                return f"{at} must be an object with a list of {HOOKS_FIELD}"
            error = unknown_keys(group, CODEX_GROUP_KEYS, at) if codex else None
            error = error or next((e for j, hook in enumerate(group[HOOKS_FIELD])
                                   if (e := handler_error(hook, f"{at}.{HOOKS_FIELD}[{j}]",
                                                          codex))), None)
            if error:
                return error
    return None


def hook_commands(data: Any) -> dict[str, str]:
    """svod hook commands of a parsed settings file: event of svod to the command."""
    found: dict[str, str] = {}
    hooks = data.get(HOOKS_FIELD) if isinstance(data, dict) else None
    groups = [g for gs in hooks.values() if isinstance(gs, list) for g in gs] \
        if isinstance(hooks, dict) else []
    for group in groups:
        for hook in group.get(HOOKS_FIELD, []) if isinstance(group, dict) else []:
            command = str(hook.get(COMMAND_FIELD, "")) if isinstance(hook, dict) else ""
            for event in HOOK_EVENTS:
                if MARKER in command and command.endswith(f" {HOOK_WORD} {event}"):
                    found.setdefault(event, command)
    return found


def interpreter(command: str) -> str | None:
    """The program a hook command runs, after `NAME=value` assignments and env; None if none."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    for word in words:
        name, sep, _ = word.partition("=")
        if (sep and name.isidentifier()) or word == ENV_PROGRAM:
            continue
        return word
    return None


def runnable(program: str) -> bool:
    """Whether the program exists and can be run: an executable path, or a name on PATH."""
    if os.sep in program:
        return os.path.isfile(program) and os.access(program, os.X_OK)
    return shutil.which(program) is not None


def hooks_checks(root: Path, locale: Locale, files: Iterable[Path]) -> list[Check]:
    """The hooks of svod are registered in files the agents can read and run an interpreter
    that exists."""
    files = list(files)
    found: list[Check] = []
    registered = False
    for path in files:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding=ENCODING))
        except (OSError, ValueError) as exc:
            found.append(Check(CHECK_HOOKS, WARN, locale.text(
                keys.DOCTOR_HOOKS_UNREADABLE, file=path, reason=exc)))
            continue
        codex = path.name == CODEX_HOOKS_FILE
        error = hooks_format_error(data, codex)
        if error:
            # Codex refuses the whole file; Claude Code skips what it cannot read.
            found.append(Check(CHECK_HOOKS, FAIL if codex else WARN, locale.text(
                keys.DOCTOR_HOOKS_FORMAT, file=path, reason=error)))
            continue
        commands = hook_commands(data)
        if not commands:
            continue
        registered = True
        programs = sorted({p for p in map(interpreter, commands.values()) if p})
        missing = [p for p in programs if not runnable(p)]
        lacking = [e for e in HOOK_EVENTS if e not in commands]
        if missing or not programs:
            found.append(Check(CHECK_HOOKS, FAIL, locale.text(
                keys.DOCTOR_HOOKS_PYTHON, file=path, python=LIST_JOIN.join(missing or ["?"]))))
        elif lacking:
            found.append(Check(CHECK_HOOKS, WARN, locale.text(
                keys.DOCTOR_HOOKS_PARTIAL, file=path, events=LIST_JOIN.join(lacking))))
        else:
            found.append(Check(CHECK_HOOKS, OK, locale.text(
                keys.DOCTOR_HOOKS_OK, file=path, python=LIST_JOIN.join(programs))))
    if not registered:
        found.append(Check(CHECK_HOOKS, WARN, locale.text(
            keys.DOCTOR_HOOKS_NONE, files=LIST_JOIN.join(map(str, files)),
            command=SETUP_COMMAND.format(root=shlex.quote(str(root))))))
    return found


def copy_check(root: Path, locale: Locale) -> Check:
    """The copy of the engine in .svod matches its MANIFEST, when the store has one."""
    from .vendor import copy_errors, has_copy, read_stamp
    if not has_copy(root):
        return Check(CHECK_COPY, OK, locale.text(keys.DOCTOR_COPY_NONE))
    errors = copy_errors(root)
    if errors:
        return Check(CHECK_COPY, FAIL, LIST_JOIN.join(errors))
    return Check(CHECK_COPY, OK, locale.text(keys.DOCTOR_COPY_OK,
                                             version=read_stamp(root).version or "?"))


LatestFn = Callable[[Path, str, dt.datetime], Any]


def version_check(root: Path, locale: Locale, data: dict[str, Any],
                  latest: LatestFn | None = None, at: dt.datetime | None = None) -> Check:
    """The engine against the newest release tag of its source, by the update notice cache."""
    from .notice import latest_known, now
    from .update import DEFAULT_SOURCE
    from .vendor import has_copy, read_stamp
    from .versions import is_newer
    stamp = read_stamp(root) if has_copy(root) else None
    current = (stamp.version if stamp else None) or __version__
    source = (stamp.source if stamp else None) or DEFAULT_SOURCE
    if data.get(FIELD_UPDATE_CHECK) is False:
        return Check(CHECK_VERSION, WARN, locale.text(
            keys.DOCTOR_VERSION_UNCHECKED, current=current, reason=FIELD_UPDATE_CHECK))
    try:
        newest = (latest or latest_known)(root, source, at or now())
    except Exception as exc:
        newest, reason = None, f"{type(exc).__name__}: {exc}"
    else:
        reason = source
    if not newest:
        return Check(CHECK_VERSION, WARN, locale.text(
            keys.DOCTOR_VERSION_UNCHECKED, current=current, reason=reason))
    if is_newer(newest, current):
        command = UPDATE_COMMAND if stamp else UPGRADE_COMMAND.format(source=source)
        return Check(CHECK_VERSION, WARN, locale.text(
            keys.DOCTOR_VERSION_NEWER, current=current, latest=newest, command=command))
    return Check(CHECK_VERSION, OK, locale.text(keys.DOCTOR_VERSION_OK, current=current,
                                                latest=newest))


def evidence_check(root: Path, locale: Locale, data: dict[str, Any]) -> Check:
    """A file can be written where the evidence log goes, unless the log is off."""
    block = data.get(FIELD_EVIDENCE)
    if isinstance(block, dict) and block.get(EVIDENCE_ENABLED) is False:
        return Check(CHECK_EVIDENCE, OK, locale.text(keys.DOCTOR_EVIDENCE_OFF))
    directory = root / EVIDENCE_DIR
    probe = directory if directory.exists() else root
    try:
        with tempfile.NamedTemporaryFile(dir=probe, prefix=PROBE_PREFIX) as handle:
            handle.write(PROBE_BYTES)
            handle.flush()
    except OSError as exc:
        return Check(CHECK_EVIDENCE, FAIL, locale.text(
            keys.DOCTOR_EVIDENCE_FAIL, dir=directory, reason=f"{type(exc).__name__}: {exc}"))
    return Check(CHECK_EVIDENCE, OK, locale.text(keys.DOCTOR_EVIDENCE_OK, dir=directory))


def knowledge_check(root: Path, locale: Locale, data: dict[str, Any]) -> Check:
    """knowledge/INDEX.md lists the notes as they are now: the table between its markers is
    what svod knowledge index would write."""
    from .knowledge import INDEX_FILE, entries, index_lines, knowledge_dir, marked_span
    block = data.get(FIELD_KNOWLEDGE)
    directory = str(block.get(KNOWLEDGE_DIR) or DEFAULT_KNOWLEDGE_DIR) \
        if isinstance(block, dict) else DEFAULT_KNOWLEDGE_DIR
    notes = entries(root, directory)
    index = knowledge_dir(root, directory) / INDEX_FILE
    if not notes and not index.is_file():
        return Check(CHECK_KNOWLEDGE, OK, locale.text(keys.DOCTOR_KNOWLEDGE_NONE))
    try:
        lines = index.read_text(encoding=ENCODING).split("\n")
    except (OSError, UnicodeDecodeError):
        lines = []
    span = marked_span(lines)
    if span is None or lines[span[0] + 1:span[1]] != index_lines(root, directory):
        return Check(CHECK_KNOWLEDGE, WARN, locale.text(keys.DOCTOR_KNOWLEDGE_STALE,
                                                        path=index))
    return Check(CHECK_KNOWLEDGE, OK, locale.text(keys.DOCTOR_KNOWLEDGE_OK, path=index,
                                                  count=len(notes)))


def local_check(root: Path, locale: Locale, data: dict[str, Any]) -> Check:
    """The local config named by svod.yaml exists and reads."""
    name = data.get(FIELD_LOCAL_CONFIG)
    if not isinstance(name, str) or not name.strip():
        return Check(CHECK_LOCAL, WARN, locale.text(keys.DOCTOR_LOCAL_NOT_CONFIGURED,
                                                    field=FIELD_LOCAL_CONFIG))
    path = root / name
    if not path.is_file():
        return Check(CHECK_LOCAL, FAIL, locale.text(keys.DOCTOR_LOCAL_MISSING, path=path))
    try:
        local = read_local(path)
    except LoadError as exc:
        return Check(CHECK_LOCAL, FAIL, locale.text(keys.DOCTOR_LOCAL_INVALID, path=path,
                                                    error=LIST_JOIN.join(exc.errors)))
    return Check(CHECK_LOCAL, OK, locale.text(keys.DOCTOR_LOCAL_OK, path=path,
                                              login=local.get(LOCAL_LOGIN) or "?"))


def checks(root: Path, locale: Locale, env: dict[str, str] | None = None,
           latest: LatestFn | None = None, at: dt.datetime | None = None) -> list[Check]:
    """Every check of the store, in the order printed."""
    data, _ = raw_config(root)
    return [config_check(root, locale),
            *service_checks(root, locale, data),
            *hooks_checks(root, locale, settings_files(root, env)),
            copy_check(root, locale),
            version_check(root, locale, data, latest, at),
            evidence_check(root, locale, data),
            knowledge_check(root, locale, data),
            local_check(root, locale, data)]


def as_json(found: list[Check]) -> dict[str, Any]:
    """JSON of the checks: ok when none failed, and each check with its details."""
    return {"ok": all(c.status != FAIL for c in found),
            "checks": [{**asdict(c), "details": list(c.details)} for c in found]}


def doctor(root: Path, output: str = FORMAT_TEXT, latest: LatestFn | None = None) -> int:
    """Print every check; exit 0 when none failed, 1 otherwise."""
    found = checks(root, error_locale(root), latest=latest)
    if output == FORMAT_JSON:
        print(json.dumps(as_json(found), ensure_ascii=False))
    else:
        for check in found:
            print(LINE.format(status=check.status, text=check.text))
            for detail in check.details:
                print(f"{DETAIL_INDENT}{detail}")
    return EXIT_OK if all(c.status != FAIL for c in found) else EXIT_FAILED
