"""Session index: open records from their frontmatter, nested, cut, chosen by session_start."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from support import ENCODING, REPO_DIR, child_env, core_text

from svod import keys, position
from svod.config import DEFAULT_INDEX_LINES, index_limit, load_config, session_start_mode
from svod.errors import LoadError
from svod.hooks import events
from svod.hooks.protocol import CONTEXT, OUTPUT, PROJECT_ENV
from svod.scaffold import scaffold

LOCAL_CONFIG = ".svod-local.yaml"
FEATURE = "work/features/shop"
TASK = "work/tasks/login"
HOTFIX = "work/tasks/crash"
DONE = "work/tasks/old"
LOOP_A = "work/tasks/loop-a"
LOOP_B = "work/tasks/loop-b"
SELF = "work/tasks/self"
BARE = "work/research/bare"
EXAMPLE = "work/tasks/example"
HEAVY = ("svod.position", "svod.gates", "svod.git", "svod.command_cache")
BUDGET_SEC = 0.5
RECORDS = 50
AGENT_CONTEXT = "profile_config:\n  agent_context:\n"


def card(title=None, **fields):
    """card.md text with the fields in its frontmatter and the title as its first heading."""
    head = {"type": "card", "status": "open", **fields}
    lines = ["---", *(f"{k}: {v}" for k, v in head.items()), "---", ""]
    return "\n".join(lines + ([f"# {title}", ""] if title else ["Text without a heading.", ""]))


class IndexStore:
    """A standard store in a temporary directory, with its local config written."""

    def __init__(self):
        """Scaffold the store."""
        self.base = Path(tempfile.mkdtemp(prefix="svod-index-"))
        self.store = scaffold(self.base / "store", "standard")
        self.write(LOCAL_CONFIG, "login: tester\n")
        self.config = (self.store / "svod.yaml").read_text(encoding=ENCODING)

    def write(self, rel, text):
        """Write a file relative to the store."""
        path = self.store / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=ENCODING)

    def record(self, rel, title=None, **fields):
        """A record directory with its card."""
        self.write(f"{rel}/card.md", card(title, **fields))

    def agent_context(self, text):
        """svod.yaml with the agent_context block of the template replaced by text."""
        head = self.config.split(AGENT_CONTEXT, 1)[0]
        self.write("svod.yaml", head + AGENT_CONTEXT + text)

    def session_start(self):
        """additionalContext of the session-start hook, or None."""
        found = events.session_start({"cwd": str(self.store)}, None)
        return json.loads(found)[OUTPUT][CONTEXT] if found else None


class IndexTestCase(unittest.TestCase):
    def setUp(self):
        """A fresh standard store; the environment of an agent session outside any project."""
        self.sb = IndexStore()
        self.addCleanup(shutil.rmtree, self.sb.base, ignore_errors=True)
        environ = {k: v for k, v in os.environ.items()
                   if not k.startswith("SVOD_") and k != PROJECT_ENV}
        patcher = mock.patch.dict(os.environ, environ, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class IndexTest(IndexTestCase):
    """What the index lists and how."""

    def setUp(self):
        """A feature with its tasks, a hotfix, a done task, a cycle, a self-parent, a research."""
        super().setUp()
        sb = self.sb
        sb.record(FEATURE, "Shop", kind="feature")
        sb.record(TASK, "Login form", kind="task", parent=FEATURE)
        sb.record(HOTFIX, "Crash on start", kind="hotfix", parent=f"./{FEATURE}/")
        sb.record(DONE, "Old task", kind="task", status="done")
        sb.record(LOOP_A, "Loop A", parent=LOOP_B)
        sb.record(LOOP_B, "Loop B", parent=LOOP_A)
        sb.record(SELF, "Self", parent=SELF)
        sb.record(BARE, kind="research")

    def test_lines(self):
        """Nested in provider order, kind only when not the pipeline's, closed records out,
        records on a cycle of parents in their own pipeline."""
        text = self.sb.session_start()
        lines = text.split("\n")
        self.assertEqual(lines[0], core_text(keys.INDEX_HEAD))
        self.assertEqual(lines[-1], core_text(keys.INDEX_TAIL))
        feature = lines.index("feature:")
        self.assertEqual(lines[feature + 1:feature + 4], [
            f"  - {FEATURE}: Shop",
            f"    - {HOTFIX} (hotfix): Crash on start",
            f"    - {TASK}: Login form",
        ])
        task = lines.index("task:")
        self.assertEqual(sorted(lines[task + 1:task + 4]),
                         [f"  - {LOOP_A}: Loop A", f"  - {LOOP_B}: Loop B", f"  - {SELF}: Self"])
        self.assertIn(f"  - {BARE}", lines)
        self.assertLess(lines.index("feature:"), lines.index("task:"))
        for absent in (DONE, EXAMPLE, "project:"):
            self.assertNotIn(absent, text)
        self.assertNotIn(core_text(keys.ACTIVE_HOOK_TAIL), text)

    def test_limit(self):
        """index_lines caps the records listed; the rest is one line with the count."""
        self.sb.agent_context("    session_start: index\n    index_lines: 2\n")
        lines = self.sb.session_start().split("\n")
        items = [line for line in lines if line.lstrip().startswith("- ")]
        self.assertEqual(len(items), 2)
        self.assertIn(core_text(keys.INDEX_MORE, count=5), lines)

    def test_local_config_notice(self):
        """A missing local config is said first, as in the summary."""
        (self.sb.store / LOCAL_CONFIG).unlink()
        text = self.sb.session_start()
        self.assertTrue(text.startswith(core_text(keys.ACTIVE_NO_LOCAL_CONFIG,
                                                  file=LOCAL_CONFIG)), text)

    def test_nothing_open(self):
        """No open record and a local config: nothing is said."""
        for rel in (FEATURE, TASK, HOTFIX, LOOP_A, LOOP_B, SELF, BARE):
            self.sb.record(rel, "Closed", status="archived")
        self.assertIsNone(self.sb.session_start())

    def test_nothing_runs(self):
        """No position, no process (git or command), no summary and no knowledge notes."""
        refuse = mock.Mock(side_effect=AssertionError("called on session start"))
        with mock.patch.object(subprocess, "run", refuse), \
                mock.patch.object(subprocess, "Popen", refuse), \
                mock.patch.object(position, "position", refuse), \
                mock.patch.object(events, "summarize", refuse), \
                mock.patch.object(events, "knowledge_context", refuse), \
                mock.patch.object(events, "update_notice", refuse):
            self.assertIn(FEATURE, self.sb.session_start())


class ModeTest(IndexTestCase):
    """agent_context.session_start, its old spelling session_summary, and their errors."""

    def setUp(self):
        """One open task."""
        super().setUp()
        self.sb.record(TASK, "Login form", kind="task")

    def test_template_default_is_the_index(self):
        """The standard template says index; a store that says nothing gets the index too."""
        config = load_config(self.sb.store).profile_config
        self.assertEqual(session_start_mode(config), "index")
        self.assertEqual(index_limit(config), DEFAULT_INDEX_LINES)
        self.assertEqual((session_start_mode({}), index_limit({})), ("index", DEFAULT_INDEX_LINES))
        self.assertIn(core_text(keys.INDEX_HEAD), self.sb.session_start())

    def test_modes(self):
        """summary gives the active summary, off nothing here; session_summary as before."""
        summary = core_text(keys.ACTIVE_HOOK_TAIL)
        cases = (
            ("summary", "    session_start: summary\n", summary),
            ("off", "    session_start: off\n", None),
            ("old summary", "    session_summary: true\n", summary),
            ("old off", "    session_summary: false\n", None),
            ("both agree", "    session_start: summary\n    session_summary: true\n", summary),
        )
        for name, text, expected in cases:
            with self.subTest(case=name):
                self.sb.agent_context(text)
                found = self.sb.session_start()
                if expected is None:
                    self.assertIsNone(found)
                else:
                    self.assertIn(expected, found)
                    self.assertNotIn(core_text(keys.INDEX_HEAD), found)

    def test_errors(self):
        """An unknown mode, a contradiction with session_summary, a bad index_lines."""
        cases = (
            ("unknown mode", "    session_start: full\n", "session_start must be one of"),
            ("true", "    session_start: true\n", "session_start must be one of"),
            ("contradiction", "    session_start: index\n    session_summary: true\n",
             "session_start: index contradicts session_summary: true"),
            ("off against true", "    session_start: off\n    session_summary: true\n",
             "contradicts"),
            ("zero lines", "    index_lines: 0\n", "index_lines must be a positive integer"),
            ("text lines", "    index_lines: many\n", "index_lines must be a positive integer"),
        )
        for name, text, expected in cases:
            with self.subTest(case=name):
                self.sb.agent_context(text)
                with self.assertRaises(LoadError) as raised:
                    load_config(self.sb.store)
                self.assertTrue(any(expected in e for e in raised.exception.errors),
                                raised.exception.errors)


class BudgetTest(IndexTestCase):
    """Session start stays cheap: 50 records under half a second, no heavy import."""

    def test_fifty_records(self):
        """25 features with a task each, the index listing all of them, under the budget."""
        for i in range(RECORDS // 2):
            feature = f"work/features/feature-{i:02d}"
            self.sb.record(feature, f"Feature {i}", kind="feature")
            self.sb.record(f"work/tasks/task-{i:02d}", f"Task {i}", kind="task", parent=feature)
        self.sb.agent_context(f"    index_lines: {RECORDS}\n")
        started = time.perf_counter()
        text = self.sb.session_start()
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, BUDGET_SEC)
        self.assertEqual(sum(line.lstrip().startswith("- ") for line in text.split("\n")),
                         RECORDS)

    def test_index_imports_nothing_heavy(self):
        """svod.index loads no position, gate, git or command-cache module."""
        script = ("import sys, svod.index; "
                  f"print(','.join(m for m in {HEAVY!r} if m in sys.modules))")
        out = subprocess.run([sys.executable, "-c", script], env=child_env(),
                             cwd=str(REPO_DIR), capture_output=True, text=True,
                             encoding=ENCODING, check=True)
        self.assertEqual(out.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
