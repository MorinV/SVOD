"""Native approval read failures preserve both decision bytes and prompt mark."""
import importlib
from pathlib import Path
import unittest
from unittest import mock


from test_approve import SECOND_STEP, SECOND_META
from svod.approval import read_mark
from svod.approve import approve
from svod.context import Context
from svod.loader import load_runtime

# Import the module rather than a TestCase to avoid accidental suite expansion.
import test_approve as controls


class ApprovalBoundariesTest(unittest.TestCase):
    def setUp(self):
        self.fx = controls.SecondApprovalTest()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.fx.approve_plan()
        self.fx.mark()

    def test_bound_file_listing_and_digest_errors_refuse_without_consumption(self):
        module = importlib.import_module('svod.approve')
        for name in ('bound_files', 'digest'):
            with self.subTest(operation=name):
                runtime = load_runtime(self.fx.sb.store)
                ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
                before = read_mark(self.fx.sb.store)
                with mock.patch.object(module, name, side_effect=OSError('unreadable evidence')):
                    result = approve(ctx, runtime.pipelines, 'tk-1', step=SECOND_STEP)
                self.assertFalse(result.ok)
                self.assertTrue(result.refused)
                self.assertEqual(read_mark(self.fx.sb.store), before)
                self.assertFalse((self.fx.sb.store / SECOND_META).exists())

    def test_bound_stat_failure_preserves_existing_approval_and_mark(self):
        runtime = load_runtime(self.fx.sb.store)
        ctx = Context(runtime.config, runtime.locale, pipelines=runtime.by_name())
        target = self.fx.sb.store / SECOND_META
        target.write_text('unrelated: retained\n')
        # A fresh event must follow the prepared target, even in this fixture.
        self.fx.mark()
        before = read_mark(self.fx.sb.store)
        raw = target.read_bytes()
        actual = Path.stat
        subject = runtime.pipeline('task').subject.impl.resolve('tk-1', ctx)[0]
        evidence = subject.path / 'review/code.yaml'
        def stat(path, *args, **kwargs):
            if path == evidence:
                raise OSError('unreadable bound stat')
            return actual(path, *args, **kwargs)
        with mock.patch.object(Path, 'stat', stat):
            result = approve(ctx, runtime.pipelines, 'tk-1', step=SECOND_STEP)
        self.assertFalse(result.ok)
        self.assertEqual(target.read_bytes(), raw)
        self.assertEqual(read_mark(self.fx.sb.store), before)


if __name__ == '__main__':
    unittest.main()
