"""Behavioral regressions found during nested-layout review."""

import unittest
import unicodedata
from tempfile import TemporaryDirectory

import test_standard_template as fixtures
from support import child_env

from svod.frontmatter import read_frontmatter


class NestedLayoutReviewTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = fixtures.StandardStore(temp.name)

    def test_missing_hotfix_start_creates_only_requested_hotfix(self):
        record = "work/hotfix/new"
        started = self.sb.action(
            "start-task.sh", record, SVOD_SERVICES="app",
            PYTHONPATH=child_env()["PYTHONPATH"],
        )
        self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
        card = self.sb.store / record / "card.md"
        self.assertEqual(read_frontmatter(card)["kind"], "hotfix")
        self.assertFalse((self.sb.store / "work/headless/tasks/new").exists())
        tree = self.sb.base / "app-task-work+hotfix+new"
        self.assertTrue((tree / ".git").exists())
        self.assertEqual(
            (self.sb.store / record / "work.yaml").read_text(),
            "app: ../app-task-work+hotfix+new\n",
        )
        self.assertEqual(
            self.sb.git(tree, "branch", "--show-current").strip(), "task/work+hotfix+new"
        )
        again = self.sb.action("start-task.sh", record)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(
            self.sb.git(self.sb.service, "worktree", "list", "--porcelain").count("worktree "), 2
        )

    def test_unicode_owner_changes_preserve_nested_child_exclusions(self):
        from svod.context import Context
        from svod.loader import load_runtime
        from svod.resolve import changed_in

        owner = "work/features/café"
        leaf = f"{owner}/tasks/t"
        made = self.sb.cli("record", "new", "feature", "café")
        self.assertEqual(made.returncode, 0, made.stderr)
        made = self.sb.cli("record", "new", "task", "t", "--parent", owner)
        self.assertEqual(made.returncode, 0, made.stderr)
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        feature = runtime.pipeline("feature")
        task = runtime.pipeline("task")
        for form in ("NFC", "NFD"):
            for suffix, owned in (("card.md", True), ("tasks/t/card.md", False),
                                  ("research/r/card.md", False), ("tasks-notes.md", True)):
                changed = {unicodedata.normalize(form, f"{owner}/{suffix}")}
                with self.subTest(form=form, suffix=suffix):
                    provider = feature.subject.impl
                    touched = provider.touched(ctx, changed)
                    self.assertEqual(
                        [unicodedata.normalize("NFC", s.id) for s in touched],
                        [owner] if owned else [],
                    )
                    subject = provider.match_exact(owner, ctx)[0]
                    # Exercise both subject representations even on normalizing filesystems.
                    for subject_form in ("NFC", "NFD"):
                        subject.path = self.sb.store / unicodedata.normalize(subject_form, owner)
                        self.assertEqual(changed_in(ctx, feature, subject, changed), owned)
            changed = {unicodedata.normalize(form, f"{leaf}/card.md")}
            provider = task.subject.impl
            self.assertEqual(
                [unicodedata.normalize("NFC", s.id) for s in provider.touched(ctx, changed)], [leaf]
            )
            subject = provider.match_exact(leaf, ctx)[0]
            for subject_form in ("NFC", "NFD"):
                subject.path = self.sb.store / unicodedata.normalize(subject_form, leaf)
                self.assertTrue(changed_in(ctx, task, subject, changed))
        # Canonical equivalence must not introduce case-insensitive path ownership.
        changed = {f"{owner.upper()}/card.md"}
        self.assertEqual(feature.subject.impl.touched(ctx, changed), [])
        subject = feature.subject.impl.match_exact(owner, ctx)[0]
        self.assertFalse(changed_in(ctx, feature, subject, changed))
