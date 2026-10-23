"""Record creation never follows a destination substituted after validation."""

import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

import test_standard_template as fixtures

from svod import records
from svod.context import Context
from svod.loader import load_runtime


@unittest.skipUnless(os.name == "posix", "requires no-follow directory descriptors")
class RecordCreationRaceTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.sb = fixtures.StandardStore(temp.name)
        self.runtime = load_runtime(self.sb.store)
        self.ctx = Context(
            self.runtime.config, self.runtime.locale, pipelines=self.runtime.by_name()
        )
        self.outside = self.sb.base / "outside"
        self.outside.mkdir()

    def create(self):
        return records.new_record(
            self.ctx, self.runtime.pipelines, records.NewRecord("task", "escape")
        )

    def test_existing_file_is_refused_without_changes(self):
        target = self.sb.store / "work/headless/tasks/escape"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("existing\n")

        report = self.create()

        self.assertFalse(report.ok)
        self.assertTrue(report.refused)
        self.assertEqual(target.read_text(), "existing\n")

    def test_open_destination_cannot_be_redirected_during_source_read(self):
        target = self.sb.store / "work/headless/tasks/escape"
        moved = target.with_name("escape-original")
        original = type(target).read_text
        substituted = False

        def substitute(path, *args, **kwargs):
            nonlocal substituted
            if path.parent == self.sb.store / "profile/records/task" and not substituted:
                substituted = True
                target.rename(moved)
                target.symlink_to(self.outside, target_is_directory=True)
            return original(path, *args, **kwargs)

        with patch.object(type(target), "read_text", substitute):
            self.create()

        self.assertTrue(substituted)
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertTrue((moved / "card.md").is_file())

    def test_nested_skeleton_destination_symlink_is_not_followed(self):
        self.sb.write("profile/records/task/notes/plan.md", "# {name}\n")
        target = self.sb.store / "work/headless/tasks/escape"
        original = type(target).read_text

        def substitute(path, *args, **kwargs):
            if path.name == "plan.md":
                (target / "notes").symlink_to(self.outside, target_is_directory=True)
            return original(path, *args, **kwargs)

        with patch.object(type(target), "read_text", substitute):
            report = self.create()

        self.assertFalse(report.ok)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_racing_leaf_links_do_not_overwrite_existing_files(self):
        for hardlink in (False, True):
            with self.subTest(hardlink=hardlink), TemporaryDirectory() as directory:
                outside = self.outside / ("hard" if hardlink else "symbolic")
                outside.write_text("preserved\n")
                target = self.sb.store / "work/headless/tasks/escape"
                # Each attempt uses a fresh, empty record directory.
                if target.exists():
                    target.rename(type(target)(directory) / "previous")
                original = type(target).read_text

                def substitute(path, *args, _target=target, _hardlink=hardlink,
                               _outside=outside, _original=original, **kwargs):
                    if path.name == "card.md" and path.parent.name == "task":
                        leaf = _target / "card.md"
                        if _hardlink:
                            os.link(_outside, leaf)
                        else:
                            leaf.symlink_to(_outside)
                    return _original(path, *args, **kwargs)

                with patch.object(type(target), "read_text", substitute):
                    report = self.create()

                self.assertFalse(report.ok)
                self.assertEqual(outside.read_text(), "preserved\n")

    def test_open_ancestor_substituted_before_child_mkdir_stays_anchored(self):
        ancestor = self.sb.store / "work/headless/tasks"
        ancestor.mkdir(parents=True, exist_ok=True)
        original = os.mkdir

        def substitute(path, *args, **kwargs):
            if path == "escape":
                ancestor.rename(ancestor.with_name("tasks-original"))
                ancestor.symlink_to(self.outside, target_is_directory=True)
            return original(path, *args, **kwargs)

        with patch.object(os, "mkdir", side_effect=substitute) as mkdir, patch.object(
            os, "supports_dir_fd", os.supports_dir_fd | {mkdir}
        ):
            report = self.create()

        # mkdir used the pinned original tasks fd; the next no-follow open must
        # not turn the substituted pathname into an outside write.
        self.assertEqual(list(self.outside.iterdir()), [])
        self.assertTrue((ancestor.with_name("tasks-original") / "escape/card.md").is_file())
        self.assertTrue(report.ok, report.err)

    def test_new_child_substituted_between_mkdir_and_open_is_refused(self):
        target = self.sb.store / "work/headless/tasks/escape"
        original = os.mkdir

        def substitute(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == "escape":
                target.rename(target.with_name("escape-original"))
                target.symlink_to(self.outside, target_is_directory=True)
            return result

        with patch.object(os, "mkdir", side_effect=substitute) as mkdir, patch.object(
            os, "supports_dir_fd", os.supports_dir_fd | {mkdir}
        ):
            report = self.create()

        self.assertFalse(report.ok)
        self.assertEqual(list(self.outside.iterdir()), [])

    def test_missing_safe_filesystem_support_fails_closed(self):
        with patch.object(os, "supports_dir_fd", set()):
            report = self.create()

        self.assertFalse(report.ok)
        self.assertIn("no-follow directory descriptors", " ".join(report.err))
        self.assertFalse((self.sb.store / "work/headless/tasks/escape").exists())

    def test_checked_ancestor_replaced_during_skeleton_listing_is_refused(self):
        ancestor = self.sb.store / "work/headless/tasks"
        ancestor.mkdir(parents=True, exist_ok=True)
        original = records.skeleton_files

        def substitute(source):
            ancestor.rename(ancestor.with_name("tasks-original"))
            ancestor.symlink_to(self.outside, target_is_directory=True)
            return original(source)

        with patch.object(records, "skeleton_files", side_effect=substitute):
            report = self.create()

        self.assertEqual(list(self.outside.iterdir()), [], "creation escaped the store")
        self.assertFalse(report.ok, report)
        self.assertTrue(report.err)
