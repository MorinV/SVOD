"""svod setup: the source of the installed svod and an instance made in one command."""
import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml
from support import (CLI_ENV, ENCODING, EXIT_OK, EXIT_USAGE, MAIN_BRANCH, ME, REPO_DIR,
                     core_text, git_env, isolated_env, run_cli)

import svod
from svod import cli, keys, setup as svod_setup
from svod.locale import load_core_locale
from svod.setup import Origin, hooks_script, installed_origin
from svod.wizard import INTEGRATIONS_DIR, SETUP_SCRIPT

TAG = f"v{svod.__version__}"
LOGIN = "tester"
EMAIL = "tester@example.com"
SERVICE = "app"
INSTANCE = "instance"
SOURCE = "svod-source"
SVOD_PREFIX = "SVOD_"
SETTINGS = Path(".claude") / "settings.json"
COMMIT_ENV = {"GIT_AUTHOR_NAME": ME[1], "GIT_AUTHOR_EMAIL": ME[0],
              "GIT_COMMITTER_NAME": ME[1], "GIT_COMMITTER_EMAIL": ME[0]}
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc")


class FakeDist:
    """A distribution whose direct_url.json is the given text, or absent."""

    def __init__(self, text=None):
        """Keep the text of direct_url.json."""
        self.text = text

    def read_text(self, name):
        """The text of direct_url.json, None for any other file."""
        return self.text if name == "direct_url.json" else None


def finder(data):
    """A distribution lookup returning a FakeDist with data as direct_url.json."""
    text = data if data is None or isinstance(data, str) else json.dumps(data)
    return lambda name: FakeDist(text)


def missing(name):
    """A distribution lookup for a package that is not installed."""
    raise importlib.metadata.PackageNotFoundError(name)


class InstalledOriginTest(unittest.TestCase):
    def test_git_install(self):
        """pip install git+URL@ref gives the URL and the ref asked for."""
        data = {"url": "https://github.com/MorinV/SVOD",
                "vcs_info": {"vcs": "git", "requested_revision": "v0.5.0", "commit_id": "abc"}}
        self.assertEqual(installed_origin(finder(data)),
                         Origin("https://github.com/MorinV/SVOD", "v0.5.0"))

    def test_git_install_without_ref(self):
        """A commit id alone is no ref: the newest release is taken later."""
        data = {"url": "git+https://example.com/svod.git",
                "vcs_info": {"vcs": "git", "commit_id": "abc"}}
        self.assertEqual(installed_origin(finder(data)), Origin("https://example.com/svod.git"))

    def test_directory_install(self):
        """An editable or directory install gives the directory."""
        for info in ({"editable": True}, {}):
            data = {"url": "file:///home/me/svod%20clone", "dir_info": info}
            self.assertEqual(installed_origin(finder(data)), Origin("/home/me/svod clone"))

    def test_nothing_found(self):
        """No metadata, bad JSON, an archive, another VCS or no package: nothing."""
        for find in (finder(None), finder("{not json"), finder([1]),
                     finder({"url": "https://x/svod.zip", "archive_info": {}}),
                     finder({"url": "https://x/svod", "vcs_info": {"vcs": "hg"}}),
                     finder({"vcs_info": {"vcs": "git"}}), missing):
            self.assertEqual(installed_origin(find), Origin())


def source_repo(base):
    """A git repository holding this tree's engine, changelog and integrations, tagged TAG."""
    source = Path(base) / SOURCE
    source.mkdir()
    shutil.copytree(REPO_DIR / "svod", source / "svod", ignore=SKIP)
    shutil.copytree(REPO_DIR / INTEGRATIONS_DIR, source / INTEGRATIONS_DIR, ignore=SKIP)
    shutil.copy(REPO_DIR / "CHANGELOG.md", source / "CHANGELOG.md")
    env = isolated_env(**git_env(Path(base)), **COMMIT_ENV)
    for argv in (("init", "-q", "-b", MAIN_BRANCH), ("add", "-A"),
                 ("commit", "-q", "-m", "release"), ("tag", TAG)):
        subprocess.run(["git", "-C", str(source), *argv], check=True, env=env,
                       capture_output=True)
    return source


def setup_args(directory, **given):
    """The parsed arguments of svod setup with the given flags."""
    values = {"directory": str(directory), "template": "standard", "source": None, "ref": None,
              "locale": None, "login": None, "email": None, "services": None, "autonomy": None,
              "checks": None, "hooks": None}
    return argparse.Namespace(**{**values, **given})


class SetupTestCase(unittest.TestCase):
    """A temporary directory with a source repository, git isolated, no SVOD_ variables."""

    def setUp(self):
        """Make the directory and the source; isolate the environment."""
        self.base = Path(tempfile.mkdtemp(prefix="svod-setup-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {**git_env(self.home), **CLI_ENV, "CLAUDE_CONFIG_DIR": str(self.home)}
        self.drop = tuple(n for n in os.environ if n.startswith(SVOD_PREFIX))
        self.source = source_repo(self.base)
        self.root = self.base / INSTANCE

    def cli(self, *args):
        """Run svod in the base directory, in this process, stdin not a terminal."""
        return run_cli(args, self.base, self.env, self.drop)

    def git(self, *args):
        """Output of git in the instance."""
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, text=True,
                              capture_output=True, env={**os.environ, **self.env}).stdout.strip()


class SetupCommandTest(SetupTestCase):
    def test_one_command_makes_the_instance(self):
        """Non-interactive setup: template, engine copy, wizard answers, commit, hooks."""
        service = self.base / SERVICE
        (service / ".git").mkdir(parents=True)
        done = self.cli("setup", INSTANCE, "--from", str(self.source), "--login", LOGIN,
                        "--email", EMAIL, "--service", f"{SERVICE}=../{SERVICE}",
                        "--hooks", "project", "--locale", "ru")
        self.assertEqual(done.returncode, EXIT_OK, done.stderr + done.stdout)
        config = yaml.safe_load((self.root / "svod.yaml").read_text(encoding=ENCODING))
        self.assertEqual(config["locale"], "ru")
        self.assertEqual(config["services"], {SERVICE: f"../{SERVICE}"})
        stamp = yaml.safe_load((self.root / ".svod" / "VERSION").read_text(encoding=ENCODING))
        self.assertEqual(stamp, {"version": svod.__version__, "source": str(self.source),
                                 "ref": TAG, "template": "standard",
                                 "template_version": svod.__version__})
        local = yaml.safe_load((self.root / ".svod-local.yaml").read_text(encoding=ENCODING))
        self.assertEqual(local, {"login": LOGIN, "email": EMAIL})
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD"), MAIN_BRANCH)
        self.assertEqual(self.git("log", "-1", "--format=%an <%ae>"), f"{LOGIN} <{EMAIL}>")
        tracked = self.git("ls-files").splitlines()
        self.assertIn("svod.yaml", tracked)
        self.assertIn(".svod/VERSION", tracked)
        self.assertNotIn(".svod-local.yaml", tracked)
        self.assertEqual(self.git("status", "--porcelain", "--", ".", ":!.claude"), "")
        settings = (self.root / SETTINGS).read_text(encoding=ENCODING)
        for event in ("session-start", "prompt", "pre-tool"):
            self.assertIn(f"--root {self.root} hook {event}", settings)
        self.assertIn(load_core_locale("ru").text(keys.SETUP_DONE, path=self.root), done.stdout)

    def test_without_a_terminal_it_needs_the_login(self):
        """No terminal and no --login: refused before anything is made."""
        done = self.cli("setup", INSTANCE, "--from", str(self.source), "--hooks", "none")
        self.assertEqual(done.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.SETUP_NOT_TTY), done.stderr)
        self.assertFalse(self.root.exists())

    def test_bad_service_is_refused_first(self):
        """A --service that is not a git checkout: refused before anything is made."""
        done = self.cli("setup", INSTANCE, "--from", str(self.source), "--login", LOGIN,
                        "--service", f"{SERVICE}=../{SERVICE}")
        self.assertEqual(done.returncode, EXIT_USAGE)
        self.assertIn(f"{SERVICE}: ", done.stderr)
        self.assertFalse(self.root.exists())

    def test_no_source_asks_for_from(self):
        """Nothing tells where svod came from and no terminal: --from is asked for."""
        with mock.patch.object(svod_setup, "installed_origin", lambda: Origin()):
            done = self.cli("setup", INSTANCE, "--login", LOGIN)
        self.assertEqual(done.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.SETUP_NO_SOURCE), done.stderr)
        self.assertFalse(self.root.exists())

    def test_not_handed_over_to_a_copy(self):
        """The engine at hand runs setup, as install: a copy in .svod may not know it."""
        with mock.patch.object(cli, "launch") as launch:
            done = self.cli("setup", INSTANCE)
        launch.assert_not_called()
        self.assertEqual(done.returncode, EXIT_USAGE)

    def test_existing_directory_is_kept(self):
        """An existing destination is refused as by svod new."""
        self.root.mkdir()
        done = self.cli("setup", INSTANCE, "--from", str(self.source), "--to", TAG,
                        "--login", LOGIN)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_failed_install_stops_and_names_the_step(self):
        """A ref the source lacks: install fails, the step is named, nothing is committed."""
        done = self.cli("setup", INSTANCE, "--from", str(self.source), "--to", "v9.9.9",
                        "--login", LOGIN)
        self.assertEqual(done.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.SETUP_STOPPED, step=svod_setup.STEP_INSTALL,
                                path=self.root), done.stderr)
        self.assertFalse((self.root / ".svod").exists())


class SetupInteractiveTest(SetupTestCase):
    def test_terminal_asks_what_is_missing(self):
        """At a terminal: the source by the installed origin, the wizard questions, the hooks
        question last, after the commit."""
        prompts = []

        def ask(prompt):
            """Answer the login and the hooks; take every default."""
            prompts.append(prompt)
            if prompt == core_text(keys.WIZARD_PROMPT_LOGIN, default=""):
                return LOGIN
            if prompt == core_text(keys.INIT_PROMPT_EMAIL, default=""):
                return EMAIL
            if prompt == core_text(keys.WIZARD_PROMPT_HOOKS, default="project"):
                self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
                return "none"
            return ""

        origin = Origin(str(self.source), TAG)
        with mock.patch.dict(os.environ, self.env):
            for name in self.drop:
                os.environ.pop(name, None)
            code = svod_setup.setup(setup_args(self.root), ask=ask, tty=True,
                                    origin=lambda: origin)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(self.git("log", "-1", "--format=%an <%ae>"), f"{LOGIN} <{EMAIL}>")
        self.assertEqual(prompts[-1], core_text(keys.WIZARD_PROMPT_HOOKS, default="project"))
        self.assertIn(core_text(keys.WIZARD_PROMPT_SERVICE), prompts)
        self.assertFalse((self.root / SETTINGS).exists())
        self.assertEqual(yaml.safe_load((self.root / ".svod" / "VERSION").read_text(
            encoding=ENCODING))["ref"], TAG)

    def test_terminal_asks_for_the_source(self):
        """No origin at a terminal: the source is asked; end of input stops before anything."""
        with mock.patch.dict(os.environ, self.env):
            for name in self.drop:
                os.environ.pop(name, None)
            code = svod_setup.setup(setup_args(self.root, login=LOGIN), ask=lambda p: None,
                                    tty=True, origin=Origin)
        self.assertEqual(code, EXIT_USAGE)
        self.assertFalse(self.root.exists())


class HooksScriptTest(SetupTestCase):
    def test_script_found_or_fetched(self):
        """The script next to the package, else in a source directory, else in a clone."""
        locale = load_core_locale("en")
        own = REPO_DIR / INTEGRATIONS_DIR / SETUP_SCRIPT
        work = self.base / "work"
        work.mkdir()
        absent = self.base / "absent.sh"
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(hooks_script(locale, str(self.source), TAG, work, own), own)
            self.assertEqual(hooks_script(locale, str(self.source), TAG, work, absent),
                             self.source / INTEGRATIONS_DIR / SETUP_SCRIPT)
            fetched = hooks_script(locale, self.source.as_uri(), TAG, work, absent)
            self.assertTrue(fetched.is_file())
            self.assertTrue(fetched.is_relative_to(work))


if __name__ == "__main__":
    unittest.main()
