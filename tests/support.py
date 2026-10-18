"""Shared helpers for svod tests: temporary stores, git and the CLI run in this process."""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from svod import cli as svod_cli
from svod.locale import FALLBACK_LOCALE, load_core_locale

TESTS_DIR = Path(__file__).resolve().parent
REPO_DIR = TESTS_DIR.parent

TEST_PROFILE = TESTS_DIR / "profile"
CLI_MODULE = "svod.cli"
CONFIG_FILE = "svod.yaml"
ENCODING = "utf-8"
CLI_TIMEOUT_SEC = 60
STORE_DIR = "store"
MAIN_BRANCH = "main"
REMOTE = "origin"
DEFAULT_BRANCH = f"{REMOTE}/{MAIN_BRANCH}"
ME = ("me@example.com", "Me Myself")
PEER = ("peer@example.com", "Peer Person")
OTHER_PEER = ("other@example.com", "Another Peer")
FIXED_DATE = "2026-09-01T12:00:00+0000"
DOC_UPDATED = "2026-09-01"
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_UNCAUGHT = 1
PYTHONPATH_ENV = "PYTHONPATH"
CLI_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}


def isolated_env(base=None, **extra):
    """Drop inherited SVOD_* only; explicit fixture values always win."""
    inherited = os.environ if base is None else base
    return {**{k: v for k, v in inherited.items() if not k.startswith("SVOD_")}, **extra}


def child_env(base=None, **extra):
    """Environment of a child process importing svod from this checkout first.

    The checkout may be a worktree while svod is installed in editable mode from elsewhere.
    """
    env = isolated_env(base, **extra)
    inherited = env.get(PYTHONPATH_ENV)
    env[PYTHONPATH_ENV] = os.pathsep.join(filter(None, (str(REPO_DIR), inherited)))
    return env


def core_text(key, **facts):
    """Text of a core locale key in the locale the test stores use."""
    return load_core_locale(FALLBACK_LOCALE).text(key, **facts)


def core_lead(key):
    """Template of a core locale key up to its first placeholder, for texts with unknown facts."""
    return load_core_locale(FALLBACK_LOCALE).text_template(key).split("{", 1)[0].strip()


def exit_code(code):
    """Process exit code of a SystemExit argument, printing a text argument as Python does."""
    if code is None:
        return EXIT_OK
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return EXIT_UNCAUGHT


def piped_run(run):
    """subprocess.run whose children write into sys.stdout and sys.stderr.

    A child inheriting the descriptors (the copy of the engine run by the launcher) would bypass
    the streams captured by an in-process run, so its output is collected and written there.
    """
    def piped(*args, **kwargs):
        """Run, collecting the output of a child that would inherit the descriptors."""
        if kwargs.get("capture_output") or {"stdout", "stderr"} & kwargs.keys():
            return run(*args, **kwargs)
        done = run(*args, capture_output=True, **kwargs)
        for text, stream in ((done.stdout, sys.stdout), (done.stderr, sys.stderr)):
            stream.write(text if isinstance(text, str) else text.decode(ENCODING, "replace"))
        return done
    return piped


def run_cli(args, cwd, env, drop=(), stdin=None):
    """Run svod.cli.main in this process as a command line would; return a CompletedProcess.

    The working directory, the environment (env set, drop removed) and the standard streams are
    replaced for the call and restored after it.
    """
    out, err = io.StringIO(), io.StringIO()
    previous = os.getcwd()
    with mock.patch.dict(os.environ, isolated_env(**env), clear=True), \
            mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err), \
            mock.patch.object(sys, "stdin", io.StringIO(stdin or "")), \
            mock.patch.object(subprocess, "run", piped_run(subprocess.run)):
        for name in drop:
            os.environ.pop(name, None)
        os.chdir(cwd)
        try:
            code = svod_cli.main(list(args))
        except SystemExit as exc:
            code = exit_code(exc.code)
        finally:
            os.chdir(previous)
    return subprocess.CompletedProcess([CLI_MODULE, *args], code, out.getvalue(), err.getvalue())


def git_env(home):
    """Environment isolating git from the developer's global configuration."""
    return {
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_DATE": FIXED_DATE,
        "GIT_COMMITTER_DATE": FIXED_DATE,
    }


def doc(doc_type, body="", **fields):
    """Markdown text with a frontmatter block."""
    head = {"type": doc_type, "status": "active", "updated": DOC_UPDATED, **fields}
    lines = ["---"] + [f"{k}: {v}" for k, v in head.items()] + ["---", "", body, ""]
    return "\n".join(lines)


def dedent(text):
    """Dedented text with a leading newline removed."""
    return textwrap.dedent(text).lstrip("\n")


class TempStore:
    """Temporary store directory with a svod.yaml and optional git."""

    def __init__(self, profile=TEST_PROFILE, locale="en", **config):
        """Create the directory tree and the config file."""
        self.root = Path(tempfile.mkdtemp(prefix="svod-test-"))
        self.parent = self.root / "parent"
        self.remotes = self.root / "remotes"
        self.home = self.root / "home"
        for directory in (self.parent, self.remotes, self.home):
            directory.mkdir(parents=True)
        self.store = self.parent / STORE_DIR
        self.store.mkdir()
        self.env = git_env(self.home)
        values = {"locale": locale, "profile": str(profile),
                  "default_branch": DEFAULT_BRANCH, "workspaces": "..", **config}
        self.write(CONFIG_FILE, "".join(f"{k}: {v}\n" for k, v in values.items()))

    def cleanup(self):
        """Remove the whole temporary tree."""
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel, text, base=None):
        """Write a file relative to the store or another base."""
        path = Path(base or self.store) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=ENCODING)
        return path

    def git(self, cwd, *args, author=None):
        """Run git in cwd, optionally committing as another author."""
        env = dict(os.environ, **self.env)
        if author:
            email, name = author
            env.update(GIT_AUTHOR_EMAIL=email, GIT_AUTHOR_NAME=name,
                       GIT_COMMITTER_EMAIL=email, GIT_COMMITTER_NAME=name)
        out = subprocess.run(["git", "-C", str(cwd), *args], env=env, capture_output=True,
                             text=True, encoding=ENCODING)
        if out.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} in {cwd}: {out.stderr}")
        return out.stdout.strip()

    def init_git(self, path=None, remote=True):
        """Initialise a repository with the local identity and optionally a pushed remote."""
        path = Path(path or self.store)
        path.mkdir(parents=True, exist_ok=True)
        self.git(self.root, "init", "-q", "-b", MAIN_BRANCH, str(path))
        self.git(path, "config", "user.email", ME[0])
        self.git(path, "config", "user.name", ME[1])
        self.commit(path, "init")
        if remote:
            bare = self.remotes / f"{path.name}.git"
            self.git(self.root, "init", "-q", "--bare", "-b", MAIN_BRANCH, str(bare))
            self.git(path, "remote", "add", REMOTE, str(bare))
            self.push(path)
        return path

    def commit(self, repo=None, message="change", author=None):
        """Commit everything in the working copy."""
        repo = repo or self.store
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "--allow-empty", "-m", message, author=author)

    def push(self, repo=None):
        """Push the main branch to origin."""
        self.git(repo or self.store, "push", "-q", "-u", REMOTE, MAIN_BRANCH)

    def cli(self, *args, cwd=None, stdin=None, drop=(), **extra):
        """Run the CLI from the store in this process, as a command line would run it."""
        return run_cli(args, cwd or self.store, {**self.env, **CLI_ENV, **extra}, drop, stdin)

    def cli_process(self, *args, cwd=None, stdin=None, drop=(), **extra):
        """Run the CLI as a black box in a child process, for the launcher and the interpreter.

        The child imports svod from this checkout first, whatever svod is installed.
        """
        env = child_env(**self.env, **CLI_ENV, **extra)
        for name in drop:
            env.pop(name, None)
        return subprocess.run([sys.executable, "-m", CLI_MODULE, *args], cwd=str(cwd or self.store),
                              env=env, input=stdin, capture_output=True, text=True,
                              encoding=ENCODING, timeout=CLI_TIMEOUT_SEC)


class StoreTestCase(unittest.TestCase):
    """Test case owning a TempStore with git isolated for in-process calls."""

    store_kwargs = {}

    def setUp(self):
        """Fresh store and isolated git environment per test."""
        self.sb = TempStore(**self.store_kwargs)
        patcher = mock.patch.dict(os.environ, isolated_env(**self.sb.env), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.sb.cleanup)


def make_profile(base, pipelines, locale_text, gates=None, locale="en"):
    """Profile directory with the given pipeline and gate sources."""
    base = Path(base)
    for name, text in pipelines.items():
        (base / "pipelines").mkdir(parents=True, exist_ok=True)
        (base / "pipelines" / name).write_text(dedent(text), encoding=ENCODING)
    for name, text in (gates or {}).items():
        (base / "gates").mkdir(parents=True, exist_ok=True)
        (base / "gates" / name).write_text(dedent(text), encoding=ENCODING)
    (base / "locale").mkdir(parents=True, exist_ok=True)
    (base / "locale" / f"{locale}.yaml").write_text(dedent(locale_text), encoding=ENCODING)
    return base


class SharedStoreTestCase(unittest.TestCase):
    """Test case sharing one TempStore across its tests, built by build()."""

    @classmethod
    def build(cls, sb):
        """Fill the shared store; subclasses override."""

    @classmethod
    def setUpClass(cls):
        """Build the store once with git isolated for in-process calls."""
        cls.sb = TempStore()
        cls.patcher = mock.patch.dict(os.environ, isolated_env(**cls.sb.env), clear=True)
        cls.patcher.start()
        cls.build(cls.sb)

    @classmethod
    def tearDownClass(cls):
        """Restore the environment and remove the store."""
        cls.patcher.stop()
        cls.sb.cleanup()
