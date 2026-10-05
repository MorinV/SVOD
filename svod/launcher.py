"""Hands a command over to the copy of the engine kept in the store, when there is one.

The store is found as the command would find it: --root, else upwards from the working
directory; for a hook, by the rules of the hooks, from the event read once on stdin and passed on.
"""
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .hooks import store_root
from .paths import CONFIG_FILE, PACKAGE_DIR, find_root, lib_dir, package_dir

LAUNCH_ENV = "SVOD_LAUNCHED"
PYTHONPATH_ENV = "PYTHONPATH"
CLI_MODULE = "svod.cli"
ROOT_FLAG = "--root"
ROOT_PREFIX = f"{ROOT_FLAG}="
OPTION_PREFIX = "-"
CMD_HOOK = "hook"
OWN_COMMANDS = ("install", "update")
ENCODING = "utf-8"
PACKAGE_HOME = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Launch:
    """Exit code of the copy that ran the command, or None; the stdin text read for a hook."""

    code: int | None = None
    stdin: str | None = None


def split_argv(argv):
    """(the --root value, the command) of the arguments; either may be None."""
    root, index = None, 0
    while index < len(argv):
        token = argv[index]
        if token == ROOT_FLAG:
            root = argv[index + 1] if index + 1 < len(argv) else None
            index += 2
        elif token.startswith(ROOT_PREFIX):
            root = token[len(ROOT_PREFIX):]
            index += 1
        elif token.startswith(OPTION_PREFIX):
            index += 1
        else:
            return root, token
    return root, None


def parse_event(text):
    """Hook event of the stdin text, empty when it is not a JSON object."""
    try:
        event = json.loads(text)
    except ValueError:
        return {}
    return event if isinstance(event, dict) else {}


def command_root(root_arg, command, event):
    """Store the command works on, or None."""
    if command == CMD_HOOK:
        return store_root(event, root_arg)
    if root_arg:
        root = Path(root_arg).expanduser().resolve()
        return root if (root / CONFIG_FILE).is_file() else None
    return find_root(Path.cwd())


def copy_env(lib):
    """Environment loading the copy at lib first and marking the hand-over."""
    env = dict(os.environ)
    inherited = env.get(PYTHONPATH_ENV)
    env[PYTHONPATH_ENV] = os.pathsep.join(filter(None, (str(lib), inherited)))
    env[LAUNCH_ENV] = str(lib)
    return env


def run_copy(root, argv, stdin=None):
    """Run the CLI of the copy of the store with argv; return its exit code."""
    lib = lib_dir(root).resolve()
    sys.stdout.flush()
    sys.stderr.flush()
    return subprocess.run([sys.executable, "-m", CLI_MODULE, *argv], env=copy_env(lib),
                          input=stdin, text=True, encoding=ENCODING).returncode


def handed_over(root):
    """Whether this process already runs the copy of the store or was handed over to it."""
    lib = lib_dir(root).resolve()
    return PACKAGE_HOME == (lib / PACKAGE_DIR) or os.environ.get(LAUNCH_ENV) == str(lib)


def launch(argv, stdin=None):
    """Run the command in the copy of the store when it has one and this is not it.

    install and update are run by the engine at hand, so a broken copy can still be replaced.
    """
    root_arg, command = split_argv(argv)
    text = (stdin or sys.stdin).read() if command == CMD_HOOK else None
    try:
        root = command_root(root_arg, command, parse_event(text) if text is not None else {})
    except Exception:
        return Launch(stdin=text)
    if root is None or command in OWN_COMMANDS or not package_dir(root).is_dir():
        return Launch(stdin=text)
    if handed_over(root):
        return Launch(stdin=text)
    try:
        return Launch(code=run_copy(root, argv, text), stdin=text)
    except OSError:
        return Launch(stdin=text)
