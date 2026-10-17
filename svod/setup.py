"""svod setup: an instance in one command.

It does what five commands did: svod new, git init with a first commit, svod install from the
source the running svod was installed from, svod init --wizard and the registration of the hooks.
Each step calls the function of its command; a failed step stops and keeps the directory.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from . import keys
from .config import FIELD_LOCALE, LOCAL_EMAIL, LOCAL_LOGIN, load_config, read_local
from .errors import LoadError
from .git import run_git
from .locale import Locale, bootstrap_locale, error_locale, load_core_locale
from .paths import CONFIG_FILE
from .scaffold import scaffold
from .update import DEFAULT_SOURCE, default_ref, deliver, fetch, resolved_source
from .wizard import (FLAG_SERVICE, HOOKS_NONE, INTEGRATIONS_DIR, SETUP_SCRIPT, Wizard,
                     WizardError, ask_line, edit_config, pairs, register_hooks, service_dir,
                     service_error, setup_script, wizard)
from .yamlio import ENCODING

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
DIST_NAME = "svod"
DIRECT_URL_FILE = "direct_url.json"
FIELD_URL = "url"
FIELD_VCS_INFO = "vcs_info"
FIELD_DIR_INFO = "dir_info"
FIELD_VCS = "vcs"
FIELD_REVISION = "requested_revision"
VCS_GIT = "git"
GIT_PREFIX = "git+"
FILE_SCHEME = "file"
MAIN_BRANCH = "main"
NAME_KEY = "user.name"
EMAIL_KEY = "user.email"
COMMIT_MESSAGE = "Svod instance made by svod setup"
GIT_TIMEOUT_SEC = 120
PATH_ENV = "PATH"
SCRIPT_PREFIX = "svod-setup-"
STEP_GIT = "git init"
STEP_INSTALL = "svod install"
STEP_WIZARD = "svod init --wizard"
STEP_COMMIT = "git commit"
STEP_HOOKS = "hooks"


@dataclass(frozen=True)
class Origin:
    """Where the running svod was installed from: a git URL or a directory, and the ref asked."""

    source: str | None = None
    ref: str | None = None


def file_path(url: str) -> str | None:
    """The local path of a file:// URL, else None."""
    parsed = urlparse(url)
    return url2pathname(parsed.path) if parsed.scheme == FILE_SCHEME else None


def installed_origin(find: Callable[[str], Any] = importlib.metadata.distribution) -> Origin:
    """The source of the installed svod by the direct_url.json of its distribution (PEP 610).

    A git install gives its URL and requested_revision; a commit id alone is no ref that
    git clone --branch takes, so the newest release is taken then. A directory install, editable
    or not, gives the directory. An archive, an index install or no metadata give nothing.
    """
    try:
        text = find(DIST_NAME).read_text(DIRECT_URL_FILE)
        data = json.loads(text) if text else None
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
        return Origin()
    if not isinstance(data, dict) or not isinstance(data.get(FIELD_URL), str):
        return Origin()
    url = data[FIELD_URL].removeprefix(GIT_PREFIX)
    vcs = data.get(FIELD_VCS_INFO)
    if isinstance(vcs, dict):
        if vcs.get(FIELD_VCS) != VCS_GIT:
            return Origin()
        ref = vcs.get(FIELD_REVISION)
        return Origin(file_path(url) or url, ref if isinstance(ref, str) and ref else None)
    if isinstance(data.get(FIELD_DIR_INFO), dict):
        return Origin(file_path(url))
    return Origin()


def source_and_ref(args: argparse.Namespace, origin: Origin, locale: Locale, tty: bool,
                   ask: Callable[[str], str | None]) -> tuple[str, str] | None:
    """(source, ref) to install: --from, else the origin, else asked at a terminal.

    The ref is --to, else the one the origin was installed at, else the newest vX.Y.Z tag.
    None after saying why there is none.
    """
    source, ref = args.source, args.ref
    if not source and origin.source:
        source, ref = origin.source, ref or origin.ref
    if not source:
        if not tty:
            print(locale.text(keys.SETUP_NO_SOURCE), file=sys.stderr)
            return None
        answer = ask(locale.text(keys.SETUP_PROMPT_SOURCE, default=DEFAULT_SOURCE))
        if answer is None:
            print(locale.text(keys.WIZARD_ABORTED), file=sys.stderr)
            return None
        source = answer or DEFAULT_SOURCE
    source = resolved_source(source)
    ref = ref or default_ref(Path.cwd(), locale, source)
    return (source, ref) if ref else None


def set_locale(root: Path, name: str) -> None:
    """Write the locale into svod.yaml, the other lines kept."""
    path = root / CONFIG_FILE
    text = path.read_text(encoding=ENCODING)
    path.write_text(edit_config(text, {FIELD_LOCALE: name}, None), encoding=ENCODING)


def git_init(root: Path, locale: Locale) -> int:
    """git init on the main branch."""
    out = run_git(root, "init", "-q", "-b", MAIN_BRANCH)
    if not out.ok:
        print(locale.text(keys.SETUP_GIT_FAILED, reason=out.error, path=root), file=sys.stderr)
        return EXIT_FINDINGS
    return EXIT_OK


def local_identity(root: Path) -> dict[str, Any]:
    """The local config the wizard wrote, empty when there is none."""
    try:
        path = load_config(root, local=False).local_path
        return read_local(path) if path is not None else {}
    except LoadError:
        return {}


def commit(root: Path, locale: Locale) -> int:
    """Commit everything; the login and email of the local config stand in for a git without
    user.name or user.email."""
    local = local_identity(root)
    identity: list[str] = []
    for key, value in ((NAME_KEY, local.get(LOCAL_LOGIN)), (EMAIL_KEY, local.get(LOCAL_EMAIL))):
        if value and not run_git(root, "config", key).ok:
            identity += ["-c", f"{key}={value}"]
    for argv in (("add", "-A"), (*identity, "commit", "-q", "-m", COMMIT_MESSAGE)):
        out = run_git(root, *argv, timeout=GIT_TIMEOUT_SEC)
        if not out.ok:
            print(locale.text(keys.SETUP_GIT_FAILED, reason=out.error, path=root),
                  file=sys.stderr)
            return EXIT_FINDINGS
    sha = run_git(root, "rev-parse", "--short", "HEAD").out
    print(locale.text(keys.SETUP_COMMITTED, sha=sha, path=root))
    return EXIT_OK


def hooks_script(locale: Locale, source: str, ref: str, workdir: Path,
                 own: Path | None = None) -> Path | None:
    """integrations/setup-claude.sh: next to the running package, else in a source directory,
    else in a clone of ref of the source in workdir; None after saying why it was not fetched."""
    for script in (own or setup_script(), Path(source) / INTEGRATIONS_DIR / SETUP_SCRIPT):
        if script.is_file():
            return script
    fetched = fetch(workdir, locale, source, ref, workdir)
    return None if fetched is None else fetched[0] / INTEGRATIONS_DIR / SETUP_SCRIPT


@contextmanager
def python_first() -> Iterator[None]:
    """PATH with the directory of the running Python first, so the setup script writes hooks
    that run the Python holding this svod, as a pipx or virtualenv install needs."""
    previous = os.environ.get(PATH_ENV)
    os.environ[PATH_ENV] = os.pathsep.join(filter(None, (str(Path(sys.executable).parent),
                                                          previous)))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(PATH_ENV, None)
        else:
            os.environ[PATH_ENV] = previous


def hooks(root: Path, locale: Locale, mode: str | None, interactive: bool,
          ask: Callable[[str], str | None], source: str, ref: str) -> int:
    """Register the hooks where --hooks says, else where the person answers, else nowhere."""
    if not mode and interactive:
        try:
            mode = Wizard(root, locale, argparse.Namespace(hooks=None), True, ask).hooks()
        except (LoadError, WizardError) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_USAGE
    if not mode or mode == HOOKS_NONE:
        return EXIT_OK
    with tempfile.TemporaryDirectory(prefix=SCRIPT_PREFIX) as workdir:
        script = hooks_script(locale, source, ref, Path(workdir))
        if script is None:
            return EXIT_FINDINGS
        with python_first():
            return register_hooks(root, locale, mode, script)


def wizard_args(args: argparse.Namespace) -> argparse.Namespace:
    """The flags of svod init --wizard; the hooks are left to the last step, after the commit."""
    return argparse.Namespace(wizard=True, login=args.login, email=args.email,
                              services=args.services, autonomy=args.autonomy,
                              checks=args.checks, hooks=HOOKS_NONE)


def service_errors(destination: Path, locale: Locale, values: list[str] | None) -> list[str]:
    """Why the --service flags cannot be the services of the instance to be, read before the
    directory exists; the WizardError text for a malformed one."""
    try:
        found = pairs(values, FLAG_SERVICE, locale)
    except WizardError as exc:
        return [str(exc)]
    return [error for name, path in found if (error := service_error(
        destination, locale, name, os.path.normpath(service_dir(destination, path))))]


def setup(args: argparse.Namespace, ask: Callable[[str], str | None] = ask_line,
          tty: bool | None = None,
          origin: Callable[[], Origin] | None = None) -> int:
    """Make the instance; return the exit code.

    Asks only at a terminal and only when --login or --hooks is missing. Refusals before the
    directory is made: no login without a terminal, a bad --service, no source, no ref.
    Exit 0 done, 1 a step failed or the directory exists, 2 refused or an answer refused.
    """
    tty = sys.stdin.isatty() if tty is None else tty
    locale = load_core_locale(args.locale) if args.locale else bootstrap_locale()
    interactive = tty and not (args.login and args.hooks)
    if not tty and not args.login:
        print(locale.text(keys.SETUP_NOT_TTY), file=sys.stderr)
        return EXIT_USAGE
    destination = Path(args.directory).expanduser().absolute()
    errors = service_errors(destination, locale, args.services)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return EXIT_USAGE
    found = source_and_ref(args, (origin or installed_origin)(), locale, tty, ask)
    if found is None:
        return EXIT_USAGE
    source, ref = found
    try:
        root = scaffold(destination, args.template)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FINDINGS
    print(root)
    if args.locale:
        set_locale(root, args.locale)
    locale = error_locale(root)
    steps = (
        (STEP_GIT, lambda: git_init(root, locale)),
        (STEP_INSTALL, lambda: deliver(root, locale, True, source, ref)),
        (STEP_WIZARD, lambda: wizard(root, wizard_args(args), ask, interactive)),
        (STEP_COMMIT, lambda: commit(root, locale)),
        (STEP_HOOKS, lambda: hooks(root, locale, args.hooks, interactive, ask, source, ref)),
    )
    for step, run in steps:
        code = run()
        if code != EXIT_OK:
            print(locale.text(keys.SETUP_STOPPED, step=step, path=root), file=sys.stderr)
            return code
    print(locale.text(keys.SETUP_DONE, path=root))
    return EXIT_OK
