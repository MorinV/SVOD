"""svod init --wizard: answers from flags or a terminal, svod.yaml edited line by line."""
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import yaml
from support import (CLI_ENV, ENCODING, EXIT_OK, EXIT_USAGE, ME, core_lead, core_text, git_env,
                     isolated_env, run_cli)

from svod import cli, keys
from svod.actions import action_env
from svod.scaffold import scaffold
from svod.wizard import edit_config, pipeline_names, register_hooks
from svod.locale import load_core_locale

SERVICE = "app"
CHECKS = "pytest -q -k 'a b'"
CHECKS_ARGV = ["pytest", "-q", "-k", "a b"]
LOGIN = "tester"
LOCAL_FILE = ".svod-local.yaml"
CONFIG = "svod.yaml"


def comments(text):
    """The comment lines of a YAML text, in order."""
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def top_keys(text):
    """Top-level keys of a YAML text in the order written."""
    return [line.split(":", 1)[0] for line in text.splitlines()
            if line and not line[0].isspace() and not line.startswith("#")]


class TtyInput(io.StringIO):
    """Typed answers on a stdin that says it is a terminal."""

    def isatty(self):
        """A terminal, so the wizard asks."""
        return True


class WizardStore:
    """A standard store with a service repository next to it, both under git."""

    def __init__(self, temp):
        """Scaffold the store and initialise the repositories."""
        self.base = Path(temp)
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = {**git_env(self.home), **CLI_ENV,
                    "CLAUDE_CONFIG_DIR": str(self.home / ".claude")}
        self.store = scaffold(self.base / "store", "standard")
        self.service = self.base / SERVICE
        for repo in (self.store, self.service):
            repo.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                           env=isolated_env(**self.env))
            subprocess.run(["git", "-C", str(repo), "config", "user.email", ME[0]], check=True,
                           env=isolated_env(**self.env))
        self.original = self.config_text()

    def config_text(self):
        """Text of svod.yaml."""
        return (self.store / CONFIG).read_text(encoding=ENCODING)

    def config(self):
        """Parsed svod.yaml."""
        return yaml.safe_load(self.config_text())

    def cli(self, *args, stdin=None):
        """Run svod in the store, in this process, stdin not a terminal."""
        return run_cli(args, self.store, self.env, stdin=stdin)

    def typed(self, answers, *args):
        """Run svod init --wizard with the answers typed at a terminal; (code, out, err)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, isolated_env(**self.env), clear=True), \
                mock.patch.object(sys, "stdin", TtyInput("".join(f"{a}\n" for a in answers))), \
                mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            code = cli.main(["--root", str(self.store), "init", "--wizard", *args])
        return code, out.getvalue(), err.getvalue()


class WizardFlagsTest(unittest.TestCase):
    def test_flags_write_the_answers_and_keep_the_comments(self):
        """Every answer given as a flag lands in svod.yaml; comments and key order stay."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            done = ws.cli("init", "--wizard", "--login", LOGIN, "--service", f"{SERVICE}=../app",
                          "--autonomy", "task=autonomous", "--checks", f"{SERVICE}={CHECKS}",
                          "--hooks", "none")
            self.assertEqual(done.returncode, EXIT_OK, done.stderr)
            self.assertIn(core_lead(keys.WIZARD_WRITTEN), done.stdout)
            data = ws.config()
            self.assertEqual(data["services"], {SERVICE: "../app"})
            self.assertEqual(data["autonomy"]["task"], "autonomous")
            self.assertEqual(data["autonomy"]["feature"], "supervised")
            self.assertEqual(data["profile_config"]["checks"], {SERVICE: CHECKS_ARGV})
            text = ws.config_text()
            self.assertEqual(comments(text), comments(ws.original))
            old_keys = top_keys(ws.original)
            self.assertEqual([k for k in top_keys(text) if k in old_keys], old_keys)
            self.assertLess(text.index("#   app: ../app"), text.index("\nservices:"))
            self.assertLess(text.index("\nservices:"), text.index("\nautonomy:"))
            self.assertIn("autonomy: {task: autonomous,", text)
            local = yaml.safe_load((ws.store / LOCAL_FILE).read_text(encoding=ENCODING))
            self.assertEqual(local, {"login": LOGIN, "email": ME[0]})
            self.assertEqual(ws.cli("validate").returncode, EXIT_OK)
            again = ws.cli("init", "--wizard", "--autonomy", "task=autonomous")
            self.assertEqual(again.returncode, EXIT_OK, again.stderr)
            self.assertIn(core_text(keys.WIZARD_UNCHANGED), again.stdout)
            self.assertNotIn(core_lead(keys.INIT_WRITTEN), again.stdout)

    def test_without_a_terminal_or_flags_it_names_the_flags(self):
        """No terminal and no answer given: refused, nothing written."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            done = ws.cli("init", "--wizard")
            self.assertEqual(done.returncode, EXIT_USAGE)
            self.assertIn("--service <name>=<path>", done.stderr)
            self.assertEqual(ws.config_text(), ws.original)
            self.assertFalse((ws.store / LOCAL_FILE).exists())

    def test_refused_answers_write_nothing(self):
        """A service without .git, an unknown level or pipeline, a check of no service."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            (ws.base / "plain").mkdir()
            cases = (
                (("--service", "plain=../plain"), core_lead(keys.WIZARD_BAD_SERVICE)),
                (("--service", "app"), core_lead(keys.WIZARD_BAD_PAIR)),
                (("--autonomy", "task=fast"), "unknown level fast"),
                (("--autonomy", "nope=guided"), "no such pipeline"),
                (("--checks", "api=make"), "no such service"),
                (("--service", "app=../app", "--checks", "app=pytest 'x"), "cannot read"),
            )
            for flags, text in cases:
                with self.subTest(flags=flags):
                    done = ws.cli("init", "--login", LOGIN, *flags)
                    self.assertEqual(done.returncode, EXIT_USAGE, done.stdout)
                    self.assertIn(text, done.stderr)
                    self.assertEqual(ws.config_text(), ws.original)
                    self.assertFalse((ws.store / LOCAL_FILE).exists())

    def test_plain_init_is_unchanged(self):
        """svod init --login without wizard flags writes only the local config, as before."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            done = ws.cli("init", "--login", LOGIN)
            self.assertEqual(done.returncode, EXIT_OK, done.stderr)
            self.assertEqual(ws.config_text(), ws.original)
            self.assertTrue((ws.store / LOCAL_FILE).is_file())


class WizardTerminalTest(unittest.TestCase):
    def test_answers_typed_at_a_terminal(self):
        """Prompts with the defaults of svod.yaml; a wrong path or level is asked again."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            names = pipeline_names(ws.store) + ["hotfix"]
            levels = {name: "" for name in names}
            levels["task"] = "fast\nguided"
            answers = [LOGIN, "", SERVICE, "../nope", "", ""]
            answers += [levels[name] for name in names]
            answers += [CHECKS, "none"]
            code, out, err = ws.typed(answers)
            self.assertEqual(code, EXIT_OK, err)
            self.assertIn("Path of app [../app]: ", out)
            self.assertIn("Autonomy of task (guided/supervised/autonomous) [supervised]: ", out)
            self.assertIn(f"Checks of app, a command run in its directory "
                          f"[{core_text(keys.WIZARD_CHECKS_AUTO)}]: ", out)
            self.assertIn(core_lead(keys.WIZARD_BAD_SERVICE), err)
            self.assertIn("unknown level fast", err)
            data = ws.config()
            self.assertEqual(data["services"], {SERVICE: "../app"})
            self.assertEqual(data["autonomy"]["task"], "guided")
            self.assertEqual(data["autonomy"]["research"], "supervised")
            self.assertEqual(data["profile_config"]["checks"], {SERVICE: CHECKS_ARGV})
            self.assertEqual(comments(ws.config_text()), comments(ws.original))

    def test_end_of_input_writes_nothing(self):
        """Input ending before the last question: nothing written."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            code, _, err = ws.typed([LOGIN, "", SERVICE])
            self.assertEqual(code, EXIT_USAGE)
            self.assertIn(core_text(keys.WIZARD_ABORTED), err)
            self.assertEqual(ws.config_text(), ws.original)


class WizardHooksTest(unittest.TestCase):
    def test_project_hooks_run_the_setup_script(self):
        """--hooks project registers the hooks in the settings of the store."""
        with TemporaryDirectory() as temp:
            ws = WizardStore(temp)
            done = ws.cli("init", "--login", LOGIN, "--hooks", "project")
            self.assertEqual(done.returncode, EXIT_OK, done.stderr)
            settings = (ws.store / ".claude" / "settings.json").read_text(encoding=ENCODING)
            self.assertIn("hook pre-tool", settings)

    def test_without_the_scripts_it_prints_the_command(self):
        """No integrations/ next to the package: the command for a clone is printed."""
        with TemporaryDirectory() as temp:
            out = io.StringIO()
            with mock.patch.object(sys, "stdout", out):
                code = register_hooks(Path(temp), load_core_locale("en"), "project",
                                      Path(temp) / "missing.sh")
            self.assertEqual(code, EXIT_OK)
            self.assertIn("git clone", out.getvalue())
            self.assertIn(f"svod-src/integrations/setup-claude.sh --project {temp}",
                          out.getvalue())


class EditConfigTest(unittest.TestCase):
    def test_nested_block_keeps_its_other_lines(self):
        """profile_config.checks is replaced inside the block; siblings and comments stay."""
        text = ("locale: en  # the language\n"
                "profile_config:\n"
                "  # publishing settings\n"
                "  publishing: {mode: review}\n"
                "  checks:\n"
                "    app: [make, test]\n"
                "  agent_context:\n"
                "    knowledge: false\n"
                "# tail comment\n")
        result = edit_config(text, {"services": {"app": "../app"}}, {"app": ["pytest"]})
        self.assertIn("locale: en  # the language\n", result)
        self.assertIn("  # publishing settings\n  publishing: {mode: review}\n", result)
        self.assertIn("  checks:\n    app: [pytest]\n  agent_context:\n", result)
        self.assertTrue(result.endswith("services:\n  app: ../app\n"))
        self.assertIn("# tail comment\n", result)

    def test_flow_parent_is_rewritten_whole(self):
        """A profile_config written on one line gets checks added to the same mapping."""
        result = edit_config("profile_config: {publishing: {mode: review}}\n", {},
                             {"api": ["go", "test", "./..."]})
        data = yaml.safe_load(result)
        self.assertEqual(data["profile_config"], {"publishing": {"mode": "review"},
                                                  "checks": {"api": ["go", "test", "./..."]}})

    def test_missing_parent_is_appended(self):
        """Without profile_config the block is added at the end."""
        result = edit_config("locale: en\n", {}, {"app": ["a b", "#c"]})
        self.assertEqual(yaml.safe_load(result)["profile_config"]["checks"]["app"],
                         ["a b", "#c"])


class ChecksEnvTest(unittest.TestCase):
    def test_actions_get_the_checks_of_svod_yaml(self):
        """profile_config.checks becomes SVOD_CHECKS_<NAME>; the environment wins."""
        config = SimpleNamespace(services={}, locale="en",
                                 profile_config={"checks": {"app": CHECKS_ARGV, "my-api": "make"}})
        ctx = SimpleNamespace(config=config, root=Path("/store"))
        subject = SimpleNamespace(attrs={}, id="work/tasks/x", keys=(), path=None)
        pipeline = SimpleNamespace(name="task")
        env = action_env(ctx, pipeline, subject, base={})
        self.assertEqual(env["SVOD_CHECKS_APP"], "pytest -q -k 'a b'")
        self.assertEqual(env["SVOD_CHECKS_MY_API"], "make")
        env = action_env(ctx, pipeline, subject, base={"SVOD_CHECKS_APP": "true"})
        self.assertEqual(env["SVOD_CHECKS_APP"], "true")


if __name__ == "__main__":
    unittest.main()
