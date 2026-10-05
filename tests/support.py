"""Shared helpers for svod tests: temporary stores and git."""
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

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

    def cli(self, *args, cwd=None):
        """Run the CLI as a black box from the store."""
        env = dict(os.environ, **self.env, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-m", CLI_MODULE, *args], cwd=str(cwd or self.store),
                              env=env, capture_output=True, text=True, encoding=ENCODING,
                              timeout=CLI_TIMEOUT_SEC)


class StoreTestCase(unittest.TestCase):
    """Test case owning a TempStore with git isolated for in-process calls."""

    store_kwargs = {}

    def setUp(self):
        """Fresh store and isolated git environment per test."""
        self.sb = TempStore(**self.store_kwargs)
        patcher = mock.patch.dict(os.environ, self.sb.env)
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
        cls.patcher = mock.patch.dict(os.environ, cls.sb.env)
        cls.patcher.start()
        cls.build(cls.sb)

    @classmethod
    def tearDownClass(cls):
        """Restore the environment and remove the store."""
        cls.patcher.stop()
        cls.sb.cleanup()
