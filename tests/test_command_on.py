"""A cheap status: the command gate runs on its current step only, its key leaves out the log.

The cache key ignores the evidence log, logs, the knowledge index and cache_ignore of svod.yaml;
with on: current a command runs only while its step is current or under status --fresh, and
elsewhere its last result is shown as stale with its age; 50 records stay under the budget.
"""
import dataclasses
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from support import CLI_ENV, StoreTestCase, TempStore, core_text, make_profile, run_cli

from svod import command_cache, keys
from svod.command_cache import DEFAULT_IGNORE, ignored
from svod.command_gate import CommandGate, age_text, fresh_commands, record_age
from svod.config import load_config
from svod.context import Context
from svod.errors import LoadError, ParamError
from svod.gates import Status
from svod.loader import load_runtime
from svod.position import position
from svod.scaffold import scaffold
from svod.subject import Subject

PY = sys.executable
PASS, FAIL = Status.PASS, Status.FAIL
COUNT_PY = """\
import pathlib, sys
base = pathlib.Path(sys.argv[1])
counter = base / "count.txt"
counter.write_text(counter.read_text() + "x" if counter.exists() else "x")
code = base / "code.txt"
print("ran")
sys.exit(int(code.read_text()) if code.exists() else 0)
"""
PIPELINE = """
    pipeline: toy
    subject: { provider: container, params: { roots: [boxes] } }
    done: { gate: artifact, params: { path: done.md }, text: toy.done }
    steps:
      - id: draft
        text: toy.draft
        gates: [ { gate: artifact, params: { path: draft.md }, label: toy.mark.draft } ]
      - id: checks
        text: toy.checks
        gates:
          - { gate: command, params: { argv: [PY, SCRIPT, BASE]ON }, label: toy.mark.checks }
      - id: review
        text: toy.review
        gates: [ { gate: artifact, params: { path: review.md }, label: toy.mark.review } ]
"""
LOCALE = """
    toy:
      done: "done"
      draft: "write draft.md"
      checks: "make the checks pass"
      review: "write review.md"
      mark:
        draft: "draft.md"
        checks: "checks pass"
        review: "review.md"
"""
BOX = "one"
BUDGET_SEC = 2.0
RECORDS = 50
FEATURE = "big"


def outer_env():
    """The environment without SVOD_ variables, as a session of the agent has it."""
    return {name: value for name, value in os.environ.items() if not name.startswith("SVOD_")}


class IgnoredTest(unittest.TestCase):
    """Patterns read as in .gitignore."""

    def test_patterns(self):
        """Unanchored names match at any depth, a slash anchors, a trailing slash a directory."""
        cases = (
            ("evidence/task/x.jsonl", DEFAULT_IGNORE, True),
            ("evidence/store.jsonl", DEFAULT_IGNORE, True),
            ("work/tasks/a/checks.log", DEFAULT_IGNORE, True),
            ("knowledge/INDEX.md", DEFAULT_IGNORE, True),
            ("knowledge/note.md", DEFAULT_IGNORE, False),
            ("docs/knowledge/INDEX.md", DEFAULT_IGNORE, False),
            ("evidence", DEFAULT_IGNORE, False),
            ("work/tasks/a/card.md", DEFAULT_IGNORE, False),
            ("notes/a/b.md", ("notes",), True),
            ("work/notes.md", ("work/*.md",), True),
            ("work/sub/notes.md", ("work/*.md",), False),
            ("build/out/x", ("build/out/",), True),
            ("build/out", ("build/out/",), False),
        )
        for rel, patterns, expected in cases:
            with self.subTest(rel=rel, patterns=patterns):
                self.assertEqual(ignored(rel, patterns), expected)

    def test_age_text(self):
        """One unit, rounded down."""
        cases = ((0, "0s"), (59.9, "59s"), (60, "1m"), (3599, "59m"), (7200, "2h"),
                 (3 * 86400 + 5, "3d"), (-4, "0s"))
        for seconds, text in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(age_text(seconds), text)

    def test_record_age(self):
        """Time since the run ended; empty for an unreadable time."""
        started = time.time() - 600
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(started))
        self.assertEqual(record_age(command_cache.Record(0, "", stamp, 100.0)), "8m")
        self.assertEqual(record_age(command_cache.Record(0, "", "later", 1.0)), "")


class CacheIgnoreConfigTest(StoreTestCase):
    """cache_ignore of svod.yaml: a list of relative paths or globs."""

    def test_valid_and_invalid(self):
        """A list of relative strings loads; anything else is a load error."""
        good = TempStore(cache_ignore="[notes/, '*.tmp']")
        self.addCleanup(good.cleanup)
        self.assertEqual(load_config(good.store).cache_ignore, ("notes/", "*.tmp"))
        self.assertEqual(load_config(self.sb.store).cache_ignore, ())
        for value in ("notes/", "[1]", "['']", "[/abs]", "[a/../b]"):
            with self.subTest(value=value):
                bad = TempStore(cache_ignore=value)
                self.addCleanup(bad.cleanup)
                with self.assertRaises(LoadError):
                    load_config(bad.store)


class IgnoredKeyTest(StoreTestCase):
    """Writing the evidence log, a log, the knowledge index or a cache_ignore path keeps the key."""

    def setUp(self):
        """Store under git with one source file; a counting command outside it."""
        super().setUp()
        self.sb.write("src/data.txt", "one\n")
        self.sb.init_git(remote=False)
        self.script = self.sb.write("count.py", COUNT_PY, base=self.sb.root)
        self.params = {"argv": [PY, str(self.script), str(self.sb.root)]}

    def runs(self):
        """How many times the command ran."""
        counter = self.sb.root / "count.txt"
        return len(counter.read_text()) if counter.exists() else 0

    def evaluate(self, ignore=()):
        """Result of the gate in a new run, with cache_ignore as given."""
        config = dataclasses.replace(load_config(self.sb.store), cache_ignore=tuple(ignore))
        return CommandGate(self.params).evaluate(Context(config),
                                                 Subject(id="one", path=self.sb.store))

    def test_ignored_paths_keep_the_result(self):
        """Ignored files, dirty or committed, keep the key; any other file changes it."""
        self.assertFalse(self.evaluate(["notes/"]).facts["cached"])
        changes = (
            lambda: self.sb.write("evidence/task/one.jsonl", "{}\n"),
            lambda: self.sb.write("work/tasks/a/checks.log", "out\n"),
            lambda: self.sb.write("knowledge/INDEX.md", "| a |\n"),
            lambda: self.sb.write("notes/today.md", "x\n"),
            lambda: self.sb.commit(message="log"),
            lambda: self.sb.write("evidence/task/one.jsonl", "{}\n{}\n"),
        )
        for number, change in enumerate(changes):
            change()
            with self.subTest(change=number):
                self.assertTrue(self.evaluate(["notes/"]).facts["cached"])
        self.assertEqual(self.runs(), 1)
        self.assertFalse(self.evaluate().facts["cached"])
        self.sb.write("src/data.txt", "two\n")
        self.assertFalse(self.evaluate(["notes/"]).facts["cached"])
        self.assertEqual(self.runs(), 3)


class OnCurrentTest(unittest.TestCase):
    """The command runs while its step is current, or with --fresh; else the last result."""

    def setUp(self):
        """A toy pipeline draft, checks (the command), review; one box; no SVOD_ variables."""
        patcher = mock.patch.dict(os.environ, outer_env(), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.make()

    def make(self, on=None):
        """Store under git with the box, its profile giving the gate's on when set."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "count.py"
        script.write_text(COUNT_PY, encoding="utf-8")
        self.base = Path(tmp.name)
        text = (PIPELINE.replace("PY", json.dumps(PY)).replace("SCRIPT", json.dumps(str(script)))
                .replace("BASE", json.dumps(tmp.name))
                .replace("ON", f", on: {on}" if on else ""))
        profile = make_profile(self.base / "profile", {"toy.yaml": text}, LOCALE)
        self.sb = TempStore(profile=profile)
        self.addCleanup(self.sb.cleanup)
        env = mock.patch.dict(os.environ, self.sb.env)
        env.start()
        self.addCleanup(env.stop)
        self.sb.write(f"boxes/{BOX}/notes.md", "a\n")
        self.sb.init_git(remote=False)

    def runs(self):
        """How many times the command ran."""
        counter = self.base / "count.txt"
        return len(counter.read_text()) if counter.exists() else 0

    def status(self, *flags):
        """Output of svod status for the box, in this process."""
        out = run_cli(("status", BOX, *flags), self.sb.store, {**self.sb.env, **CLI_ENV})
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def gate(self):
        """Outcome of the command gate in a new run."""
        runtime = load_runtime(self.sb.store)
        pipeline = runtime.pipeline("toy")
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        subject = pipeline.subject.impl.match_exact(BOX, ctx)[0]
        state = next(s for s in position(ctx, pipeline, subject).steps if s.step.id == "checks")
        return state.outcomes[0]

    def mark(self, status, label="checks pass"):
        """The standard mark of the checks gate."""
        return core_text(keys.MARK_PASS if status is PASS else keys.MARK_FAIL, label=label)

    def test_runs_only_on_its_step(self):
        """Ahead: not run; current: runs, then cached; behind: stale; --fresh runs it."""
        out = self.status()
        self.assertEqual(self.runs(), 0)
        self.assertIn(core_text(keys.MARK_NOT_RUN, mark=self.mark(FAIL)), out)
        outcome = self.gate()
        self.assertEqual((outcome.result.status, outcome.result.facts["code"],
                          outcome.result.facts["stale"]), (FAIL, "", False))

        self.sb.write(f"boxes/{BOX}/draft.md", "draft\n")
        self.assertIn(f"{self.mark(PASS)}\n", self.status())
        self.assertEqual(self.runs(), 1)
        self.status()
        self.assertEqual(self.runs(), 1)

        self.sb.write(f"boxes/{BOX}/notes.md", "b\n")
        out = self.status()
        self.assertEqual(self.runs(), 1)
        stale = core_text(keys.MARK_STALE, mark=self.mark(PASS), age="AGE").split("AGE")
        self.assertRegex(out, re.escape(stale[0]) + r"\d+s" + re.escape(stale[1]))
        facts = self.gate().result.facts
        self.assertEqual((facts["cached"], facts["stale"], facts["code"]), (True, True, 0))
        self.assertRegex(facts["age"], r"^\d+[smhd]$")

        self.assertIn(f"{self.mark(PASS)}\n", self.status("--fresh"))
        self.assertEqual(self.runs(), 2)
        self.status()
        self.assertEqual(self.gate().result.facts["stale"], False)
        self.assertEqual(self.runs(), 2)

    def test_last_failure_makes_the_step_current(self):
        """A last result that failed holds the step: the command runs on each change."""
        self.sb.write(f"boxes/{BOX}/draft.md", "draft\n")
        self.sb.write("code.txt", "1", base=self.base)
        self.assertIn(self.mark(FAIL), self.status())
        self.sb.write(f"boxes/{BOX}/notes.md", "b\n")
        self.status()
        self.assertEqual(self.runs(), 2)
        self.sb.write("code.txt", "0", base=self.base)
        self.sb.write(f"boxes/{BOX}/notes.md", "c\n")
        self.assertIn(f"{self.mark(PASS)}\n", self.status())
        self.assertEqual(self.runs(), 3)

    def test_done_subject_runs_nothing(self):
        """A done subject has no current step: its command keeps the last result."""
        self.sb.write(f"boxes/{BOX}/draft.md", "draft\n")
        self.status()
        self.sb.write(f"boxes/{BOX}/review.md", "ok\n")
        self.sb.write(f"boxes/{BOX}/done.md", "done\n")
        self.status()
        with fresh_commands(False):
            self.assertTrue(self.gate().result.facts["stale"])
        self.assertEqual(self.runs(), 1)
        with fresh_commands():
            self.assertFalse(self.gate().result.facts["cached"])
        self.assertEqual(self.runs(), 2)

    def test_on_always_runs_on_any_step(self):
        """on: always runs the command whichever step is current."""
        self.make("always")
        self.status()
        self.assertEqual(self.runs(), 1)
        self.sb.write(f"boxes/{BOX}/notes.md", "b\n")
        self.status()
        self.assertEqual(self.runs(), 2)

    def test_on_param(self):
        """on is current or always."""
        CommandGate({"argv": ["make"], "on": "always"})
        CommandGate({"argv": ["make"], "on": "current"})
        for value in ("never", True, ["current"]):
            with self.subTest(value=value), self.assertRaises(ParamError):
                CommandGate({"argv": ["make"], "on": value})


class BudgetTest(unittest.TestCase):
    """svod status on a standard store with 50 records runs no command and stays under 2 s."""

    def setUp(self):
        """Standard store with a feature and 50 tasks, half open on their card, half done."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        home = base / "home"
        home.mkdir()
        self.env = {**outer_env(), **CLI_ENV, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "Me", "GIT_AUTHOR_EMAIL": "me@example.com",
                    "GIT_COMMITTER_NAME": "Me", "GIT_COMMITTER_EMAIL": "me@example.com"}
        self.store = Path(scaffold(base / "store", "standard"))
        self.card(f"work/features/{FEATURE}", "feature", "open")
        for number in range(RECORDS):
            self.card(f"work/features/{FEATURE}/tasks/t{number:02d}", "task",
                      "done" if number % 2 else "open")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-qm", "init")):
            subprocess.run(["git", "-C", str(self.store), *args], env=self.env, check=True,
                           capture_output=True)

    def card(self, rel, kind, status):
        """Card of a work record under the feature."""
        parent = "" if kind == "feature" else f"work/features/{FEATURE}"
        path = self.store / rel / "card.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\ntype: card\nkind: {kind}\nkey:\nservices: []\nparent: {parent}\n"
                        f"status: {status}\n---\n\n# {rel}\n", encoding="utf-8")

    def test_status_of_fifty_records(self):
        """No command runs: no cache entry appears; the status finishes within the budget."""
        with mock.patch("svod.command_gate.run_command") as run:
            started = time.monotonic()
            out = run_cli(("status", FEATURE), self.store, self.env)
            elapsed = time.monotonic() - started
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.count(f"work/features/{FEATURE}/tasks/t"), RECORDS)
        run.assert_not_called()
        self.assertFalse((self.store / ".git" / command_cache.CACHE_DIR).exists())
        self.assertLess(elapsed, BUDGET_SEC)


if __name__ == "__main__":
    unittest.main()
