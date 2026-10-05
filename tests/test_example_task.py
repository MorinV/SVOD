"""The task example: it validates, its key gate reads keys, its position moves step by step."""
import os
import unittest
from unittest import mock

import task_example as te
from support import CONFIG_FILE, ENCODING, EXIT_FINDINGS, EXIT_OK

from svod.config import load_config
from svod.gates import build_registry

STEP_LINE = "Next step: {text}."
NO_KEY = None


class ExampleTaskTest(unittest.TestCase):
    """Positions of one task through the whole pipeline, in a store copied from the example."""

    def setUp(self):
        """Fresh store with git isolated for in-process calls."""
        self.sb = te.make_task_store()
        patcher = mock.patch.dict(os.environ, self.sb.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.sb.cleanup)

    def test_validates_in_every_locale(self):
        """validate passes for each locale the example ships."""
        for locale in ("en", "ru"):
            with self.subTest(locale=locale):
                te.set_config(self.sb, locale=locale)
                out = self.sb.cli("validate")
                self.assertEqual(EXIT_OK, out.returncode, out.stderr)

    def test_config_errors(self):
        """validate reports a wrong workspace gate, read-only flag or key params."""
        pipeline = self.sb.store / "profile" / "pipelines" / "task.yaml"
        source = pipeline.read_text(encoding=ENCODING)
        config = (self.sb.store / CONFIG_FILE).read_text(encoding=ENCODING)
        cases = (
            ("unknown workspace gate", {"workspace_gate": "missing"}, source,
             "workspace_gate: unknown gate: missing"),
            ("workspace gate without worktrees", {"workspace_gate": "merged"}, source,
             "merged has no worktrees(ctx, keys)"),
            ("read-only flag not a boolean", {"main_checkout_read_only": "maybe"}, source,
             "main_checkout_read_only must be a boolean"),
            ("key params without key gate", {}, source.replace("  key_gate: key\n", ""),
             "key_params needs key_gate"),
        )
        for name, values, text, expected in cases:
            with self.subTest(case=name):
                te.set_config(self.sb, **values)
                pipeline.write_text(text, encoding=ENCODING)
                out = self.sb.cli("validate")
                (self.sb.store / CONFIG_FILE).write_text(config, encoding=ENCODING)
                pipeline.write_text(source, encoding=ENCODING)
                self.assertEqual(EXIT_FINDINGS, out.returncode)
                self.assertIn(expected, out.stderr)

    def test_position_moves_by_steps(self):
        """Each action moves the position to the next step of the pipeline."""
        stages = (
            ("nothing", None,
             STEP_LINE.format(text="create the change openspec/changes/<name> with the task "
                                   "key in .openspec.yaml")),
            ("proposed", te.propose,
             STEP_LINE.format(text="write proposal.md of the change: why and what changes")),
            ("specified", te.specify,
             "show the plan (proposal, design, specs, tasks) to the person"),
            ("approved", te.approve,
             STEP_LINE.format(text="make the work directory next to the store: git worktree "
                                   "add ../<repo>-<KEY>_<slug> -b <KEY>_<slug>")),
            ("worktree", te.make_worktree,
             STEP_LINE.format(text="implement the tasks in the work directory and commit with "
                                   "the task key in the message")),
            ("implemented", te.implement,
             f"the work directories {te.WORKTREE} are not merged yet"),
            ("merged", te.merge,
             STEP_LINE.format(text="archive the change: move it to openspec/changes/archive")),
            ("archived", te.archive,
             STEP_LINE.format(text="nothing left, the change is archived")),
        )
        for name, action, expected in stages:
            if action is not None:
                action(self.sb)
            out = self.sb.cli("status", te.KEY)
            with self.subTest(stage=name):
                self.assertEqual(EXIT_OK, out.returncode, out.stderr)
                self.assertIn(expected, out.stdout)

    def test_code_frozen_until_approved(self):
        """The code freeze line is printed before the approval and gone after it."""
        te.propose(self.sb)
        te.specify(self.sb)
        cases = (("before", None, True), ("after", te.approve, False))
        for name, action, frozen in cases:
            if action is not None:
                action(self.sb)
            out = self.sb.cli("status", te.KEY)
            with self.subTest(stage=name):
                self.assertEqual(frozen, "Do not touch the code" in out.stdout, out.stdout)


class TaskKeyGateTest(unittest.TestCase):
    """The key gate of the example reads queries in any case and texts as written."""

    @classmethod
    def setUpClass(cls):
        """Key gate built from the example profile with its default pattern."""
        config = load_config(te.EXAMPLE, local=False)
        cls.gate = build_registry(config.profile)["key"]()

    def test_match(self):
        """A query names a key in any letter case; the key is upper-cased."""
        cases = (
            ("status of PROJ-12", "PROJ-12"),
            ("proj-12 please", "PROJ-12"),
            ("PROJ-12a", "PROJ-12"),
            ("PROJ-123", "PROJ-123"),
            ("no key here", NO_KEY),
            ("XPROJ12", NO_KEY),
        )
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(expected, self.gate.match(query))

    def test_find(self):
        """A text names keys as written, inside directory and branch names too."""
        cases = (
            ("ticket: PROJ-1", {"PROJ-1"}),
            ("service-PROJ-1_greeting", {"PROJ-1"}),
            ("PROJ-1 and ABC-22", {"PROJ-1", "ABC-22"}),
            ("lower proj-1", set()),
            ("PROJ-10", {"PROJ-10"}),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, self.gate.find(text))


if __name__ == "__main__":
    unittest.main()
