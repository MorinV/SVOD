"""Actions: svod do runs a profile script for one subject with its environment."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import patch

from support import (EXIT_FINDINGS, EXIT_OK, EXIT_USAGE, TEST_PROFILE, StoreTestCase, core_text,
                     doc)

from svod import actions, evidence_log, keys, run
from svod.context import Context
from svod.loader import load_runtime
from svod.locale import FALLBACK_LOCALE, load_locale
from svod.providers.openspec_change import DEFAULT_ROOT, METADATA_FILE
from svod.render import INDENT

TEXTS = load_locale(FALLBACK_LOCALE, TEST_PROFILE)
SHOW_ENV = "show-env"
START_TASK = "start-task"
NOTE = "alpha-note"
TASK = "c-tk-7"
TASK_KEY = "tk-7"
WORK_NOTE = "work.md"
POSIX_ONLY = "actions run bash with POSIX process groups"


def env_lines(out):
    """Mapping of the NAME=value lines a script printed."""
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def task(sb, key=TASK_KEY, approved=True):
    """Change of the test profile at the build step when approved, else at approve."""
    root = f"{DEFAULT_ROOT}/c-{key}"
    sb.write(f"{root}/{METADATA_FILE}",
             f"ticket: {key}\n" + ("approved: 2026-09-10\n" if approved else ""))
    sb.write(f"{root}/specs/cap/spec.md", "# spec\n")
    sb.write(f"{root}/design.md", "# design\n")
    return sb.store / root


@unittest.skipUnless(os.name == "posix" and shutil.which(actions.SHELL), POSIX_ONLY)
class DoTest(StoreTestCase):
    """svod do resolves the subject, runs the script and hands its exit code back.

    A script writes to the descriptors svod inherited, so runs that print are child processes.
    """

    def setUp(self):
        """A note with frontmatter and a task at its build step."""
        super().setUp()
        self.sb.write(f"notes/{NOTE}.md",
                      doc("note", kind="feature", services="[api, web]", owner="me",
                          tags="[a, b]", exit="0"))
        self.task = task(self.sb)

    def test_environment(self):
        """The script sees the SVOD_ variables, the extra args and the store root as cwd."""
        result = self.sb.cli_process("do", SHOW_ENV, NOTE, "--", "one", "--two")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        env = env_lines(result.stdout)
        note = self.sb.store / "notes" / f"{NOTE}.md"
        expected = {
            actions.ENV_ROOT: str(self.sb.store.resolve()),
            actions.ENV_ID: NOTE,
            actions.ENV_KEY: "",
            actions.ENV_PIPELINE: "note",
            actions.ENV_KIND: "feature",
            actions.ENV_SERVICES: "api,web",
            actions.ENV_SUBJECT_PATH: str(note.resolve()),
            actions.ENV_LOCALE: "en",
            actions.ENV_ACTION: SHOW_ENV,
            "SVOD_FM_OWNER": "me",
            "SVOD_FM_TYPE": "note",
            "SVOD_FM_UPDATED": "2026-09-01",
            "ARGS": "one --two",
            "PWD": str(self.sb.store.resolve()),
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertEqual(env.get(name), value)
        for name in ("SVOD_FM_TAGS", "SVOD_FM_KIND", "SVOD_FM_SERVICES"):
            with self.subTest(name=name):
                self.assertNotIn(name, env)

    def test_key_of_a_task(self):
        """A subject with a tracker key gets it in SVOD_KEY; the query may be the key."""
        result = self.sb.cli_process("do", SHOW_ENV, TASK_KEY)
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        env = env_lines(result.stdout)
        self.assertEqual(env[actions.ENV_KEY], TASK_KEY)
        self.assertEqual(env[actions.ENV_ID], TASK)
        self.assertEqual(env[actions.ENV_PIPELINE], "task")

    def test_exit_code(self):
        """The exit code of the script is the exit code of svod do."""
        self.sb.write(f"notes/{NOTE}.md", doc("note", exit="3"))
        result = self.sb.cli_process("do", SHOW_ENV, NOTE)
        self.assertEqual(result.returncode, 3)

    def test_idempotent_example(self):
        """The example script does its work once and exits 0 on the second run."""
        first = self.sb.cli_process("do", START_TASK, TASK)
        self.assertEqual(first.returncode, EXIT_OK, first.stderr)
        self.assertIn("started", first.stdout)
        written = (self.task / WORK_NOTE).read_text(encoding="utf-8")
        self.assertIn(TASK_KEY, written)
        second = self.sb.cli_process("do", START_TASK, TASK)
        self.assertEqual(second.returncode, EXIT_OK, second.stderr)
        self.assertIn("already started", second.stdout)
        self.assertEqual((self.task / WORK_NOTE).read_text(encoding="utf-8"), written)

    def test_step_not_reached(self):
        """An action of a later step is refused with do.not_current; --force runs it anyway."""
        self.sb.write(f"{DEFAULT_ROOT}/c-{TASK_KEY}/{METADATA_FILE}", f"ticket: {TASK_KEY}\n")
        warning = core_text(keys.DO_NOT_CURRENT, name=START_TASK, step="build", id=TASK,
                            current="approve")
        refused = self.sb.cli_process("do", START_TASK, TASK)
        self.assertEqual(refused.returncode, EXIT_USAGE)
        self.assertIn(warning, refused.stderr)
        self.assertFalse((self.task / WORK_NOTE).exists())
        forced = self.sb.cli_process("do", START_TASK, TASK, "--force")
        self.assertEqual(forced.returncode, EXIT_OK, forced.stderr)
        self.assertIn(warning, forced.stderr)
        self.assertTrue((self.task / WORK_NOTE).exists())

    def test_step_passed_or_none_runs_quietly(self):
        """An action of a passed step, or of no step, runs without a warning."""
        with tempfile.TemporaryDirectory() as profile:
            shutil.copytree(TEST_PROFILE, profile, dirs_exist_ok=True)
            pipeline = Path(profile, "pipelines", "task.yaml")
            title = "    title: task.title.spec\n"
            pipeline.write_text(pipeline.read_text(encoding="utf-8").replace(
                title, f"{title}    action: {SHOW_ENV}\n"), encoding="utf-8")
            self.sb.write("svod.yaml", self.sb.store.joinpath("svod.yaml").read_text(
                encoding="utf-8").replace(str(TEST_PROFILE), profile))
            for query in (TASK, NOTE):
                with self.subTest(query=query):
                    result = self.sb.cli_process("do", SHOW_ENV, query)
                    self.assertEqual(result.returncode, EXIT_OK, result.stderr)
                    self.assertEqual(result.stderr, "")

    def test_run_is_in_the_evidence_log(self):
        """Each run is an action_run with the action, its exit code and the step naming it."""
        self.assertEqual(self.sb.cli_process("do", START_TASK, TASK).returncode, EXIT_OK)
        self.sb.write(f"notes/{NOTE}.md", doc("note", exit="3"))
        self.assertEqual(self.sb.cli_process("do", SHOW_ENV, NOTE).returncode, 3)
        runs = [(entry["step"], entry["facts"]["action"], entry["facts"]["code"])
                for pipeline, subject in (("task", TASK), ("note", NOTE))
                for entry in evidence_log.read(self.sb.store, pipeline, subject)
                if entry["event"] == evidence_log.EVENT_ACTION_RUN]
        self.assertEqual(runs, [("build", START_TASK, 0), (None, SHOW_ENV, 3)])

    def test_timeout_option(self):
        """--timeout stops the script after the given seconds; a bad value is a usage error."""
        with tempfile.TemporaryDirectory() as profile:
            shutil.copytree(TEST_PROFILE, profile, dirs_exist_ok=True)
            Path(profile, actions.ACTIONS_DIR, "slow.sh").write_text("sleep 30\n")
            self.sb.write("svod.yaml", self.sb.store.joinpath("svod.yaml").read_text(
                encoding="utf-8").replace(str(TEST_PROFILE), profile))
            result = self.sb.cli_process("do", "slow", NOTE, "--timeout", "0.3")
            self.assertEqual(result.returncode, actions.EXIT_TIMEOUT)
            self.assertIn(core_text(keys.DO_TIMEOUT, name="slow", seconds="0.3"), result.stderr)
            for value in ("0", "-1", "soon"):
                with self.subTest(value=value):
                    bad = self.sb.cli("do", "slow", NOTE, "--timeout", value)
                    self.assertEqual(bad.returncode, EXIT_USAGE)

    @unittest.skipUnless(sys.platform == "darwin", "Darwin zombie-group semantics")
    def test_timeout_waits_for_zombie_descendant_group_to_disappear(self):
        """Reaping the action leader need not immediately remove its zombie-only group."""
        ready = self.sb.root / "ready"
        release = self.sb.root / "release"
        reaped = self.sb.root / "reaped"
        helper = self.sb.root / "helper.py"
        helper.write_text(
            "import os, sys, time\nfrom pathlib import Path\n"
            "group = int(sys.argv[1])\nos.setpgid(0, 0)\npid = os.fork()\n"
            "if pid == 0:\n    os.setpgid(0, group)\n    os._exit(0)\n"
            # Keep the dead descendant waitable outside the target process group.
            "import subprocess\n"
            "while not subprocess.check_output(['ps', '-o', 'stat=', '-p', str(pid)], "
            "text=True).strip().startswith('Z'):\n    time.sleep(.01)\n"
            f"Path({str(ready)!r}).touch()\n"
            f"while not Path({str(release)!r}).exists():\n    time.sleep(.01)\n"
            f"os.waitpid(pid, 0)\nPath({str(reaped)!r}).touch()\n")
        native = os.killpg
        denials = []

        def probe(pid, sig):
            try:
                return native(pid, sig)
            except PermissionError:
                denials.append(sig)
                if len(denials) == 2:
                    release.touch()
                    deadline = time.monotonic() + 5
                    while not reaped.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(reaped.exists(), "helper did not reap the descendant")
                raise

        with tempfile.TemporaryDirectory() as profile:
            shutil.copytree(TEST_PROFILE, profile, dirs_exist_ok=True)
            Path(profile, actions.ACTIONS_DIR, "slow.sh").write_text(
                f"{sys.executable} {helper} $$ &\nwait\n")
            self.sb.write("svod.yaml", (self.sb.store / "svod.yaml").read_text().replace(
                str(TEST_PROFILE), profile))
            try:
                # Acknowledge topology readiness before allowing the real action wait to time out.
                wait = subprocess.Popen.wait

                def ready_wait(process, timeout=None):
                    if timeout == .3:
                        deadline = time.monotonic() + 5
                        while not ready.exists() and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertTrue(ready.exists(), "descendant did not become a zombie")
                    return wait(process, timeout=timeout)

                with patch.object(run.os, "killpg", side_effect=probe), \
                        patch.object(subprocess.Popen, "wait", ready_wait):
                    result = self.sb.cli("do", "slow", NOTE, "--timeout", "0.3")
                self.assertEqual(result.returncode, actions.EXIT_TIMEOUT, result.stderr)
                self.assertIn(core_text(keys.DO_TIMEOUT, name="slow", seconds="0.3"),
                              result.stderr)
                self.assertGreaterEqual(len(denials), 2)
                self.assertEqual(set(denials), {0})
                events = evidence_log.read(self.sb.store, "note", NOTE)
                self.assertEqual(events[-1]["facts"]["code"], actions.EXIT_TIMEOUT)
            finally:
                release.touch()
                deadline = time.monotonic() + 5
                while not reaped.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(reaped.exists(), "helper cleanup did not finish")

    def test_list(self):
        """--list prints every action with the first comment line as its description."""
        result = self.sb.cli("do", "--list")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            core_text(keys.DO_LIST_ITEM, name=SHOW_ENV, description="Print the environment Svod "
                      "gives an action, the arguments and the working directory."),
            core_text(keys.DO_LIST_ITEM, name=START_TASK,
                      description="Start the work on a task: write its work note once."),
        ])

    def test_unknown_action(self):
        """An action without a script, or a name outside the syntax, is refused."""
        for name in ("missing", "../show-env"):
            with self.subTest(name=name):
                result = self.sb.cli("do", name, NOTE)
                self.assertEqual(result.returncode, EXIT_USAGE)
                self.assertIn(core_text(keys.DO_UNKNOWN, name=name, script="").split(",")[0],
                              result.stderr)

    def test_usage(self):
        """Without an action and a query there is nothing to run."""
        result = self.sb.cli("do", SHOW_ENV)
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.DO_USAGE), result.stderr)

    def test_not_found_and_ambiguous(self):
        """A query matching no subject or several runs nothing."""
        result = self.sb.cli("do", SHOW_ENV, "nothing-like-it")
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.STATUS_NOT_FOUND, query="nothing-like-it"), result.stderr)
        self.assertEqual(result.stdout, "")
        self.sb.write("notes/alpha-other.md", doc("note"))
        result = self.sb.cli("do", SHOW_ENV, "alpha")
        self.assertEqual(result.returncode, EXIT_USAGE)
        self.assertIn(core_text(keys.STATUS_AMBIGUOUS), result.stderr)
        self.assertEqual(result.stdout, "")

    def test_timeout(self):
        """A script overrunning the timeout is stopped with the timeout exit code."""
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale)
        pipeline = runtime.pipeline("note")
        subject = pipeline.subject.impl.match_exact(NOTE, ctx)[0]
        with tempfile.TemporaryDirectory() as profile:
            shutil.copytree(TEST_PROFILE, profile, dirs_exist_ok=True)
            Path(profile, actions.ACTIONS_DIR, "slow.sh").write_text("sleep 30\n")
            config = SimpleNamespace(root=ctx.root, profile=Path(profile), locale="en")
            run = actions.run_action(Context(config), "slow", pipeline, subject, timeout=.2)
        self.assertTrue(run.timed_out)
        self.assertEqual(run.code, actions.EXIT_TIMEOUT)


class EnvironmentTest(unittest.TestCase):
    """The environment of an action without running it."""

    def test_services_and_inherited(self):
        """Every service of svod.yaml is a path; inherited generated variables are dropped."""
        root = Path(tempfile.gettempdir()).resolve()
        config = SimpleNamespace(root=root, profile=root, locale="ru",
                                 services={"api": "../api", "web-ui": {"path": "web"},
                                           "broken": {"repo": "x"}})
        pipeline = SimpleNamespace(name="task")
        subject = SimpleNamespace(id="x", keys=frozenset({"tk-2", "tk-1"}), path=None,
                                  attrs={"frontmatter": {"flag": True, "none": None}})
        env = actions.action_env(Context(config), pipeline, subject,
                                 base={"SVOD_FM_OLD": "1", "SVOD_SERVICE_OLD": "1", "HOME": "h"})
        self.assertEqual(env["SVOD_SERVICE_API"], str((root / "../api").resolve()))
        self.assertEqual(env["SVOD_SERVICE_WEB_UI"], str(root / "web"))
        self.assertNotIn("SVOD_SERVICE_BROKEN", env)
        self.assertNotIn("SVOD_FM_OLD", env)
        self.assertNotIn("SVOD_SERVICE_OLD", env)
        self.assertEqual(env["HOME"], "h")
        self.assertEqual(env[actions.ENV_KEY], "tk-1")
        self.assertEqual(env[actions.ENV_SUBJECT_PATH], "")
        self.assertEqual(env[actions.ENV_LOCALE], "ru")
        self.assertEqual(env["SVOD_FM_FLAG"], actions.TRUE_TEXT)
        self.assertEqual(env["SVOD_FM_NONE"], "")

    def test_description(self):
        """The first comment after the shebang; a script starting with code has none."""
        with tempfile.TemporaryDirectory() as directory:
            cases = (("#!/bin/bash\n\n#  Says hi  \n# more\n", "Says hi"),
                     ("# Only line", "Only line"), ("echo hi\n# late\n", ""), ("", ""))
            for text, wanted in cases:
                with self.subTest(text=text):
                    path = Path(directory, "a.sh")
                    path.write_text(text, encoding="utf-8")
                    self.assertEqual(actions.description(path), wanted)


class StatusAndValidateTest(StoreTestCase):
    """The step declaring an action names the command in status; validate needs its script."""

    def test_run_line(self):
        """At the build step status prints the command; before it, none."""
        task(self.sb)
        task(self.sb, "tk-9", approved=False)
        run = INDENT + core_text(keys.STATUS_RUN, action=START_TASK, query=TASK)
        result = self.sb.cli("status", TASK_KEY)
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)
        self.assertIn(run, result.stdout.splitlines())
        self.assertIn(TEXTS.text("task.step.build"), result.stdout)
        result = self.sb.cli("status", "tk-9")
        self.assertNotIn(core_text(keys.STATUS_RUN, action=START_TASK, query="c-tk-9"),
                         result.stdout)

    def test_validate_missing_script(self):
        """A step naming an action without a script is a validate error; the store still loads."""
        with tempfile.TemporaryDirectory() as profile:
            shutil.copytree(TEST_PROFILE, profile, dirs_exist_ok=True)
            Path(profile, actions.ACTIONS_DIR, f"{START_TASK}.sh").unlink()
            self.sb.write("svod.yaml", self.sb.store.joinpath("svod.yaml").read_text(
                encoding="utf-8").replace(str(TEST_PROFILE), profile))
            result = self.sb.cli("validate")
            self.assertEqual(result.returncode, EXIT_FINDINGS)
            self.assertIn(f"task.yaml: steps[3]: action script not found: "
                          f"{actions.ACTIONS_DIR}/{START_TASK}.sh", result.stderr)
            task(self.sb)
            self.assertEqual(self.sb.cli("status", TASK_KEY).returncode, EXIT_OK)

    def test_validate_ok(self):
        """The test profile declares an action whose script exists."""
        result = self.sb.cli("validate")
        self.assertEqual(result.returncode, EXIT_OK, result.stderr)


if __name__ == "__main__":
    unittest.main()
