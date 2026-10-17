"""svod init --wizard: the answers that set up a store, asked at a terminal or given as flags.

The answers are the login and the email (the local config, as svod init writes it), the
service repositories, the autonomy of each pipeline, the check command of each service and
where to register the hooks of Claude Code. svod.yaml is edited line by line: only the block of
a changed key is rewritten, so comments and the order of the keys stay as written.
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import keys
from .config import (AUTONOMY_GUIDED, AUTONOMY_KINDS, AUTONOMY_LEVELS, FIELD_AUTONOMY,
                     FIELD_LOCAL_CONFIG, FIELD_PROFILE_CONFIG, FIELD_SERVICES, LOCAL_EMAIL,
                     LOCAL_LOGIN, read_local, write_local)
from .errors import LoadError
from .git import run_git
from .locale import Locale, error_locale
from .paths import CONFIG_FILE
from .yamlio import ENCODING, parse_yaml

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
CHECKS_KEY = "checks"
HOOKS_PROJECT = "project"
HOOKS_GLOBAL = "global"
HOOKS_NONE = "none"
HOOKS_CHOICES = (HOOKS_PROJECT, HOOKS_GLOBAL, HOOKS_NONE)
HOOKS_INTERACTIVE_DEFAULT = HOOKS_PROJECT
PAIR_SEPARATOR = "="
LIST_JOIN = ", "
LEVELS_JOIN = "/"
GIT_DIR = ".git"
EMPTY_REASON = "no words"
DEFAULT_SERVICE_PATH = "../{name}"
FLAG_SERVICE = "--service"
FLAG_AUTONOMY = "--autonomy"
FLAG_CHECKS = "--checks"
WIZARD_FLAGS = ("services", "autonomy", "checks", "hooks")
INTEGRATIONS_DIR = "integrations"
SETUP_SCRIPT = "setup-claude.sh"
PROJECT_FLAG = "--project"
SHELL = "bash"
CLONE_DIR = "svod-src"
EMAIL_KEY = "user.email"
INDENT_STEP = 2
FLOW_WIDTH = 1 << 16
DOCUMENT_END = "..."
COMMENT = "#"
NEWLINE = "\n"
EXAMPLE_LINE = r"^#\s*{key}\s*:"
EXAMPLE_CHILD = re.compile(r"^#\s{2,}\S")
KEY_LINE = r"^ {{{indent}}}{key}\s*:(?:\s|$)"


class WizardError(Exception):
    """A refused answer or input that ended early: the text says why; nothing is written."""


# --- svod.yaml edited line by line -------------------------------------------------------


def inline(value: Any) -> str:
    """One-line YAML of a value: a flow list or mapping, or a scalar quoted when needed."""
    text = yaml.safe_dump(value, default_flow_style=True, sort_keys=False, allow_unicode=True,
                          width=FLOW_WIDTH)
    return " ".join(line for line in text.splitlines() if line != DOCUMENT_END).strip()


def indent_of(line: str) -> int:
    """Number of leading spaces of a line."""
    return len(line) - len(line.lstrip(" "))


def key_index(lines: list[str], key: str, indent: int, start: int, end: int) -> int | None:
    """Index of the line holding the key at exactly that indent in lines[start:end], or None."""
    pattern = re.compile(KEY_LINE.format(indent=indent, key=re.escape(key)))
    return next((i for i in range(start, end) if pattern.match(lines[i])), None)


def block_end(lines: list[str], start: int, end: int) -> int:
    """Index after the block of the key at lines[start]: the deeper indented lines after it.

    Blank lines count only between two lines of the block; a line indented as the key or less,
    a comment included, ends it.
    """
    indent, last = indent_of(lines[start]), start
    for i in range(start + 1, end):
        if not lines[i].strip():
            continue
        if indent_of(lines[i]) <= indent:
            break
        last = i
    return last + 1


def inline_value(line: str) -> bool:
    """Whether a key line carries its value on the line itself, not in a block under it."""
    rest = line.split(":", 1)[1].strip()
    return bool(rest) and not rest.startswith(COMMENT)


def flow_value(line: str) -> bool:
    """Whether a key line carries a flow mapping: `key: {a: b}`."""
    return line.split(":", 1)[1].strip().startswith("{")


def render(key: str, value: Any, indent: int, flow: bool) -> list[str]:
    """Lines of one key: a flow line, or a block of `name: value` lines for a mapping."""
    pad = " " * indent
    if flow or not isinstance(value, dict) or not value:
        return [f"{pad}{key}: {inline(value)}{NEWLINE}"]
    child = " " * (indent + INDENT_STEP)
    return [f"{pad}{key}:{NEWLINE}"] + [f"{child}{inline(name)}: {inline(item)}{NEWLINE}"
                                       for name, item in value.items()]


def insertion_index(lines: list[str], key: str) -> int:
    """Where a new top-level key goes: after its commented example (`# key:` and the
    indented comment lines under it), else at the end."""
    pattern = re.compile(EXAMPLE_LINE.format(key=re.escape(key)))
    for i, line in enumerate(lines):
        if pattern.match(line):
            j = i + 1
            while j < len(lines) and EXAMPLE_CHILD.match(lines[j]):
                j += 1
            return j
    return len(lines)


def ended(lines: list[str]) -> list[str]:
    """Lines whose last one ends with a newline."""
    if lines and not lines[-1].endswith(NEWLINE):
        lines[-1] += NEWLINE
    return lines


def set_top(lines: list[str], key: str, value: Any) -> list[str]:
    """Lines with the top-level key set to the value; a flow mapping stays a flow mapping."""
    lines = ended(list(lines))
    i = key_index(lines, key, 0, 0, len(lines))
    if i is None:
        at = insertion_index(lines, key)
        return lines[:at] + render(key, value, 0, False) + lines[at:]
    j = block_end(lines, i, len(lines))
    return lines[:i] + render(key, value, 0, flow_value(lines[i])) + lines[j:]


def set_child(lines: list[str], parent: str, key: str, value: Any, whole: Any) -> list[str]:
    """Lines with parent.key set to the value, the other lines of the parent block kept.

    whole is the new value of the parent, written as a block when the parent holds its value
    on its own line or is absent.
    """
    lines = ended(list(lines))
    i = key_index(lines, parent, 0, 0, len(lines))
    if i is None:
        return lines + [f"{parent}:{NEWLINE}"] + render(key, value, INDENT_STEP, False)
    if inline_value(lines[i]):
        return set_top(lines, parent, whole)
    j = block_end(lines, i, len(lines))
    children = [n for n in range(i + 1, j)
                if lines[n].strip() and not lines[n].lstrip().startswith(COMMENT)]
    indent = indent_of(lines[children[0]]) if children else INDENT_STEP
    c = key_index(lines, key, indent, i + 1, j)
    if c is None:
        return lines[:j] + render(key, value, indent, False) + lines[j:]
    end = block_end(lines, c, j)
    return lines[:c] + render(key, value, indent, flow_value(lines[c])) + lines[end:]


def edit_config(text: str, changes: dict[str, Any], checks: dict[str, Any] | None) -> str:
    """svod.yaml text with top-level keys set and, when given, profile_config.checks set.

    The result is parsed back and compared with the data expected; a difference raises
    WizardError, so a file the line edit cannot handle is never written half right.
    """
    data = parse_yaml(text, CONFIG_FILE) or {}
    expected = copy.deepcopy(data)
    lines = text.splitlines(keepends=True)
    for key, value in changes.items():
        lines = set_top(lines, key, value)
        expected[key] = value
    if checks is not None:
        profile = dict(expected.get(FIELD_PROFILE_CONFIG) or {})
        profile[CHECKS_KEY] = checks
        lines = set_child(lines, FIELD_PROFILE_CONFIG, CHECKS_KEY, checks, profile)
        expected[FIELD_PROFILE_CONFIG] = profile
    result = "".join(lines)
    written = parse_yaml(result, CONFIG_FILE) or {}
    differing = sorted(str(k) for k in set(written) | set(expected)
                       if written.get(k) != expected.get(k))
    if differing:
        raise WizardError(LIST_JOIN.join(differing))
    return result


# --- answers --------------------------------------------------------------------------------


def ask_line(prompt: str) -> str | None:
    """A line typed at the terminal, stripped; None at the end of input."""
    try:
        return input(prompt).strip()
    except EOFError:
        return None


@dataclass
class Answers:
    """What the wizard writes."""

    services: dict[str, str] = field(default_factory=dict)
    autonomy: dict[str, str] = field(default_factory=dict)
    checks: dict[str, list[str]] = field(default_factory=dict)
    local: dict[str, Any] | None = None
    hooks: str = HOOKS_NONE


def pairs(values: Iterable[str] | None, flag: str, locale: Locale) -> list[tuple[str, str]]:
    """(name, value) of each `name=value` flag; WizardError for one without both."""
    found = []
    for raw in values or ():
        name, sep, value = raw.partition(PAIR_SEPARATOR)
        if not sep or not name.strip() or not value.strip():
            raise WizardError(locale.text(keys.WIZARD_BAD_PAIR, flag=flag, value=raw))
        found.append((name.strip(), value.strip()))
    return found


def service_dir(root: Path, path: str) -> Path:
    """Directory of a service path as typed: relative to the store root, or absolute."""
    given = Path(path).expanduser()
    return given if given.is_absolute() else root / given


def stored_path(root: Path, path: str) -> str:
    """The path written to svod.yaml: relative to the store root, as svod.yaml requires."""
    given = Path(path).expanduser()
    if not given.is_absolute():
        return given.as_posix()
    return Path(os.path.relpath(given, root)).as_posix()


def service_error(root: Path, locale: Locale, name: str, path: str) -> str | None:
    """Why the path cannot be the checkout of a service, or None for a directory with .git."""
    directory = service_dir(root, path)
    if directory.is_dir() and (directory / GIT_DIR).exists():
        return None
    return locale.text(keys.WIZARD_BAD_SERVICE, name=name, path=directory)


def command_argv(locale: Locale, name: str, command: str) -> list[str]:
    """argv of a check command split as a shell would; WizardError when it cannot be."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise WizardError(locale.text(keys.WIZARD_BAD_CHECKS, name=name, command=command,
                                      reason=exc)) from None
    if not argv:
        raise WizardError(locale.text(keys.WIZARD_BAD_CHECKS, name=name, command=command,
                                      reason=EMPTY_REASON))
    return argv


def pipeline_names(root: Path) -> list[str]:
    """Names of the pipelines of the store in load order; empty when it does not load."""
    from .loader import load_runtime
    try:
        return [p.name for p in load_runtime(root).pipelines]
    except LoadError:
        return []


def given_flags(args: argparse.Namespace) -> bool:
    """Whether any answer of the wizard was given as a flag."""
    return any(getattr(args, name, None) for name in WIZARD_FLAGS) or bool(
        getattr(args, "login", None) or getattr(args, "email", None))


class Wizard:
    """The questions of the wizard over one store, asked or read from the flags."""

    def __init__(self, root: Path, locale: Locale, args: argparse.Namespace, interactive: bool,
                 ask: Callable[[str], str | None] = ask_line) -> None:
        """Read svod.yaml; LoadError when it is not readable YAML."""
        self.root = root
        self.locale = locale
        self.args = args
        self.interactive = interactive
        self._ask = ask
        self.text = (root / CONFIG_FILE).read_text(encoding=ENCODING)
        data = parse_yaml(self.text, root / CONFIG_FILE)
        self.data: dict[str, Any] = data if isinstance(data, dict) else {}
        self.existing_local: dict[str, Any] | None = None

    def ask(self, key: str, **facts: Any) -> str:
        """The answer to one question; WizardError at the end of input."""
        answer = self._ask(self.locale.text(key, **facts))
        if answer is None:
            raise WizardError(self.locale.text(keys.WIZARD_ABORTED))
        return answer

    def say(self, text: str) -> None:
        """A note to the person on stderr, so stdout keeps the prompts and the results."""
        print(text, file=sys.stderr)

    def mapping(self, key: str) -> dict[str, Any]:
        """A mapping of svod.yaml, empty when absent or not a mapping."""
        value = self.data.get(key)
        return dict(value) if isinstance(value, dict) else {}

    def current_checks(self) -> dict[str, Any]:
        """profile_config.checks of svod.yaml, empty when absent."""
        value = self.mapping(FIELD_PROFILE_CONFIG).get(CHECKS_KEY)
        return dict(value) if isinstance(value, dict) else {}

    def local(self) -> dict[str, Any] | None:
        """The local config to write, or None when svod.yaml names none."""
        name = self.data.get(FIELD_LOCAL_CONFIG)
        if not isinstance(name, str) or not name.strip():
            self.say(self.locale.text(keys.INIT_NOT_CONFIGURED, field=FIELD_LOCAL_CONFIG))
            return None
        try:
            existing = read_local(self.root / name)
        except LoadError:
            existing = {}
        self.existing_local = existing
        login = self.args.login or existing.get(LOCAL_LOGIN) or ""
        git = run_git(self.root, "config", EMAIL_KEY)
        email = self.args.email or existing.get(LOCAL_EMAIL) or (git.out if git.ok else "")
        if self.interactive and not self.args.login:
            while True:
                login = self.ask(keys.WIZARD_PROMPT_LOGIN, default=login) or login
                if login:
                    break
                self.say(self.locale.text(keys.INIT_NEED_LOGIN))
        if self.interactive and not self.args.email:
            email = self.ask(keys.INIT_PROMPT_EMAIL, default=email) or email
        if not login:
            raise WizardError(self.locale.text(keys.INIT_NEED_LOGIN))
        values = {**existing, LOCAL_LOGIN: login, LOCAL_EMAIL: email}
        return {key: value for key, value in values.items() if value}

    def services(self) -> dict[str, str]:
        """Services to add or move, name to the path written to svod.yaml."""
        found: dict[str, str] = {}
        for name, path in pairs(self.args.services, FLAG_SERVICE, self.locale):
            error = service_error(self.root, self.locale, name, path)
            if error:
                raise WizardError(error)
            found[name] = stored_path(self.root, path)
        if not self.interactive:
            return found
        current = {**self.mapping(FIELD_SERVICES), **found}
        if current:
            self.say(self.locale.text(keys.WIZARD_SERVICES_CURRENT, services=LIST_JOIN.join(
                f"{n}={p}" for n, p in current.items())))
        while name := self.ask(keys.WIZARD_PROMPT_SERVICE):
            default = current.get(name) or DEFAULT_SERVICE_PATH.format(name=name)
            while True:
                path = self.ask(keys.WIZARD_PROMPT_PATH, name=name, default=default) or default
                error = service_error(self.root, self.locale, name, path)
                if not error:
                    break
                self.say(error)
            found[name] = current[name] = stored_path(self.root, path)
        return found

    def autonomy(self) -> dict[str, str]:
        """Levels to set, pipeline name to level."""
        current = self.mapping(FIELD_AUTONOMY)
        names = pipeline_names(self.root)
        names += [n for n in current if n not in names]
        known = set(names) | AUTONOMY_KINDS
        found: dict[str, str] = {}
        for name, level in pairs(self.args.autonomy, FLAG_AUTONOMY, self.locale):
            if names and name not in known:
                raise WizardError(self.locale.text(keys.WIZARD_UNKNOWN_PIPELINE, name=name,
                                                   names=LIST_JOIN.join(names)))
            self.check_level(name, level)
            found[name] = level
        if not self.interactive:
            return found
        for name in names:
            if name in found:
                continue
            default = str(current.get(name) or AUTONOMY_GUIDED)
            while True:
                level = self.ask(keys.WIZARD_PROMPT_AUTONOMY, name=name, default=default,
                                 levels=LEVELS_JOIN.join(AUTONOMY_LEVELS))
                if not level:
                    break
                try:
                    self.check_level(name, level)
                except WizardError as exc:
                    self.say(str(exc))
                    continue
                found[name] = level
                break
        return found

    def check_level(self, name: str, level: str) -> None:
        """WizardError for a level that is not one of the autonomy levels."""
        if level not in AUTONOMY_LEVELS:
            raise WizardError(self.locale.text(keys.WIZARD_BAD_LEVEL, name=name, level=level,
                                               levels=LEVELS_JOIN.join(AUTONOMY_LEVELS)))

    def checks(self, services: Iterable[str]) -> dict[str, list[str]]:
        """Check commands to set, service name to argv."""
        names = list(dict.fromkeys([*self.mapping(FIELD_SERVICES), *services]))
        found: dict[str, list[str]] = {}
        for name, command in pairs(self.args.checks, FLAG_CHECKS, self.locale):
            if name not in names:
                raise WizardError(self.locale.text(keys.WIZARD_UNKNOWN_SERVICE, name=name,
                                                   names=LIST_JOIN.join(names)))
            found[name] = command_argv(self.locale, name, command)
        if not self.interactive:
            return found
        current = self.current_checks()
        for name in names:
            if name in found:
                continue
            value = current.get(name)
            default = (shlex.join(value) if isinstance(value, list) else str(value)) if value \
                else self.locale.text(keys.WIZARD_CHECKS_AUTO)
            while True:
                command = self.ask(keys.WIZARD_PROMPT_CHECKS, name=name, default=default)
                if not command:
                    break
                try:
                    found[name] = command_argv(self.locale, name, command)
                    break
                except WizardError as exc:
                    self.say(str(exc))
        return found

    def hooks(self) -> str:
        """Where to register the hooks: project, global or none."""
        if self.args.hooks or not self.interactive:
            return str(self.args.hooks or HOOKS_NONE)
        while True:
            answer = self.ask(keys.WIZARD_PROMPT_HOOKS, default=HOOKS_INTERACTIVE_DEFAULT)
            answer = answer or HOOKS_INTERACTIVE_DEFAULT
            if answer in HOOKS_CHOICES:
                return answer
            self.say(self.locale.text(keys.WIZARD_BAD_HOOKS, answer=answer))

    def answers(self) -> Answers:
        """Every answer, the flags first; WizardError before anything is written."""
        local = self.local()
        services = self.services()
        autonomy = self.autonomy()
        checks = self.checks(services)
        return Answers(services, autonomy, checks, local, self.hooks())

    def new_text(self, answers: Answers) -> tuple[str, list[str]]:
        """svod.yaml text with the answers and the keys it changes."""
        changes: dict[str, Any] = {}
        services = {**self.mapping(FIELD_SERVICES), **answers.services}
        if services != self.mapping(FIELD_SERVICES):
            changes[FIELD_SERVICES] = services
        autonomy = {**self.mapping(FIELD_AUTONOMY), **answers.autonomy}
        if autonomy != self.mapping(FIELD_AUTONOMY):
            changes[FIELD_AUTONOMY] = autonomy
        checks = {**self.current_checks(), **answers.checks}
        checks_changed = checks != self.current_checks()
        if not changes and not checks_changed:
            return self.text, []
        try:
            text = edit_config(self.text, changes, checks if checks_changed else None)
        except WizardError as exc:
            raise WizardError(self.locale.text(keys.WIZARD_WRITE_FAILED, reason=exc)) from None
        names = list(changes) + ([f"{FIELD_PROFILE_CONFIG}.{CHECKS_KEY}"] if checks_changed
                                 else [])
        return text, names


def setup_script() -> Path:
    """integrations/setup-claude.sh next to the running package, present in a clone only."""
    return Path(__file__).resolve().parent.parent / INTEGRATIONS_DIR / SETUP_SCRIPT


def register_hooks(root: Path, locale: Locale, mode: str,
                   script: Path | None = None) -> int:
    """Run the setup of Claude Code for the store, or print the command for a clone of Svod."""
    if mode == HOOKS_NONE:
        return EXIT_OK
    argv = [PROJECT_FLAG, str(root)] if mode == HOOKS_PROJECT else [str(root)]
    script = script or setup_script()
    if not script.is_file():
        command = (f"git clone {shlex.quote(default_source())} {CLONE_DIR} && "
                   + shlex.join([SHELL, f"{CLONE_DIR}/{INTEGRATIONS_DIR}/{SETUP_SCRIPT}", *argv]))
        print(locale.text(keys.WIZARD_HOOKS_MANUAL, command=command))
        return EXIT_OK
    run_argv = [SHELL, str(script), *argv]
    done = subprocess.run(run_argv, check=False)
    if done.returncode != 0:
        print(locale.text(keys.WIZARD_HOOKS_FAILED, command=shlex.join(run_argv),
                          code=done.returncode), file=sys.stderr)
        return EXIT_FINDINGS
    return EXIT_OK


def default_source() -> str:
    """The Svod repository svod install takes by default."""
    from .update import DEFAULT_SOURCE
    return DEFAULT_SOURCE


def wizard(root: Path, args: argparse.Namespace, ask: Callable[[str], str | None] = ask_line,
           interactive: bool | None = None) -> int:
    """Ask or read every answer, then write svod.yaml, the local config and the hooks.

    Without a terminal and without any answer given as a flag it refuses and names the flags.
    Exit 0 done, 1 the hook setup failed, 2 an answer was refused or svod.yaml is unreadable.
    """
    locale = error_locale(root)
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if not interactive and not given_flags(args):
        print(locale.text(keys.WIZARD_NOT_TTY), file=sys.stderr)
        return EXIT_USAGE
    try:
        session = Wizard(root, locale, args, interactive, ask)
        answers = session.answers()
        text, changed = session.new_text(answers)
    except LoadError as exc:
        for error in exc.errors:
            print(error, file=sys.stderr)
        return EXIT_USAGE
    except WizardError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if changed:
        (root / CONFIG_FILE).write_text(text, encoding=ENCODING)
        print(locale.text(keys.WIZARD_WRITTEN, keys=LIST_JOIN.join(changed)))
    else:
        print(locale.text(keys.WIZARD_UNCHANGED))
    if answers.local is not None:
        path = root / str(session.data[FIELD_LOCAL_CONFIG])
        if answers.local != session.existing_local:
            write_local(path, answers.local)
            print(locale.text(keys.INIT_WRITTEN, path=path))
    code = register_hooks(root, locale, answers.hooks)
    print(locale.text(keys.WIZARD_NEXT))
    return code
