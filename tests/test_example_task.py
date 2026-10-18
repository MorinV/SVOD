"""The task example: it validates, its key gate reads keys, its position moves step by step."""
import os
import unittest

from support import isolated_env
from unittest import mock

import task_example as te
from support import CONFIG_FILE, ENCODING, EXIT_FINDINGS, EXIT_OK, core_lead

from svod import keys
from svod.config import load_config
from svod.gates import build_registries
from svod.locale import load_locale

EN = "en"
PROFILE_DIR = "profile"
NO_KEY = None
SIBLINGS_WITHOUT_REMOTE = ("alpha", "beta")
MERGED_NOWHERE = "merged in: -"
MERGED_IN_SERVICE = f"merged in: {te.SERVICE};"


class ExampleTaskTest(unittest.TestCase):
    """Positions of one task through the whole pipeline, in a store copied from the example."""

    def setUp(self):
        """Fresh store with git isolated for in-process calls."""
        self.sb = te.make_task_store()
        patcher = mock.patch.dict(os.environ, isolated_env(**self.sb.env), clear=True)
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
        locale = load_locale(EN, te.EXAMPLE / PROFILE_DIR)

        def step(key):
            """Next step line of a step text of the example profile."""
            return locale.text(keys.STATUS_NEXT_STEP, step=locale.text(key))

        stages = (
            ("nothing", None, step("task.step.propose")),
            ("proposed", te.propose, step("task.step.proposal")),
            ("specified", te.specify, step("task.step.approve_missing")),
            ("approved", te.approve, step("task.step.workspace")),
            ("worktree", te.make_worktree, step("task.step.implement")),
            ("implemented", te.implement,
             locale.text("task.step.merge_open", open=te.WORKTREE)),
            ("merged", te.merge, step("task.step.archive")),
            ("archived", te.archive, step("task.done")),
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
                frozen_line = core_lead(keys.STATUS_DO_NOT_TOUCH)
                self.assertEqual(frozen, frozen_line in out.stdout, out.stdout)

    def test_merged_skips_repositories_without_remote(self):
        """Without work directories, a sibling repository with no remote default branch is left
        out of the merge check silently; one with a pushed task commit makes the work merged."""
        te.propose(self.sb)
        for name in SIBLINGS_WITHOUT_REMOTE:
            self.sb.init_git(self.sb.parent / name, remote=False)
        unknown = core_lead(keys.STATUS_UNKNOWN)
        out = self.sb.cli("status", te.KEY)
        self.assertEqual(EXIT_OK, out.returncode, out.stderr)
        self.assertNotIn(unknown, out.stdout)
        self.assertIn(MERGED_NOWHERE, out.stdout)
        service = te.service(self.sb)
        self.sb.commit(service, f"{te.KEY}: print hello")
        self.sb.push(service)
        out = self.sb.cli("status", te.KEY)
        self.assertNotIn(unknown, out.stdout)
        self.assertIn(MERGED_IN_SERVICE, out.stdout)


class TaskKeyGateTest(unittest.TestCase):
    """The key gate of the example reads queries in any case and texts as written."""

    @classmethod
    def setUpClass(cls):
        """Key gate built from the example profile with its default pattern."""
        config = load_config(te.EXAMPLE, local=False)
        cls.gate = build_registries(config.profile)[0]["key"]()

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
