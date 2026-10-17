"""Portable boundaries: conditional-only groups, entry readiness and native consent."""
import dataclasses
import unittest
from unittest import mock

from support import StoreTestCase
from svod.approval import read_mark
from svod.approve import approve
from svod.context import Context
from svod.gates import ApprovalGate, Status, unknown, verdict
from svod.loader import load_runtime
from svod.position import position
from svod.workflow_policy import subject_pipeline
import test_approve as controls


class PortablePositionTest(StoreTestCase):
    def test_all_inapplicable_gates_skip_but_gateless_stage_stays_manual(self):
        from test_position import change
        change(self.sb, 'conditional', 'tk-111', spec=True, design=True)
        runtime = load_runtime(self.sb.store)
        ctx = Context(runtime.config, runtime.locale)
        pipeline = runtime.pipeline('task')
        subject = pipeline.subject.impl.resolve('tk-111', ctx)[0]
        stage = pipeline.step('approve')
        skipped = dataclasses.replace(stage, gates=[dataclasses.replace(g, when='absent')
                                                   for g in stage.gates])
        manual = dataclasses.replace(stage, id='manual', gates=[])
        pipeline = dataclasses.replace(pipeline, entry=[], done=None, steps=[skipped, manual])
        pos = position(ctx, pipeline, subject)
        self.assertTrue(pos.steps[0].passed)
        self.assertFalse(pos.steps[1].passed)
        self.assertEqual(pos.current.step.id, 'manual')


class PortableApprovalTest(unittest.TestCase):
    def setUp(self):
        self.fx = controls.SecondApprovalTest()
        self.addCleanup(self.fx.doCleanups)
        self.fx.setUp()
        self.fx.approve_plan()
        self.runtime = load_runtime(self.fx.sb.store)
        self.ctx = Context(self.runtime.config, self.runtime.locale,
                           pipelines=self.runtime.by_name())
        self.pipeline = self.runtime.pipeline('task')
        self.subject = self.pipeline.subject.impl.resolve('tk-1', self.ctx)[0]

    def test_pipeline_previous_and_selected_entry_blocks_refuse_without_mark_consumption(self):
        template = self.pipeline.entry[0]
        for location in ('pipeline', 'previous', 'selected'):
            for result in (verdict(False), unknown('private detail')):
                with self.subTest(location=location, status=result.status):
                    gate = mock.Mock()
                    gate.evaluate.return_value = result
                    ref = dataclasses.replace(template, severity='block', when=None, impl=gate)
                    selected = self.pipeline.step(controls.SECOND_STEP)
                    previous = self.pipeline.steps[0]
                    target = (self.pipeline if location == 'pipeline'
                              else previous if location == 'previous' else selected)
                    with mock.patch.object(target, 'entry', [ref]):
                        self.fx.mark()
                        before = read_mark(self.fx.sb.store)
                        report = approve(self.ctx, self.runtime.pipelines, 'tk-1',
                                         step=controls.SECOND_STEP)
                        self.assertFalse(report.ok)
                        self.assertTrue(report.refused)
                        self.assertEqual(read_mark(self.fx.sb.store), before)
                        self.assertFalse((self.fx.sb.store / controls.SECOND_META).exists())

    def test_automatic_selection_handles_unreadable_approval_without_crashing(self):
        ref = self.pipeline.step(controls.SECOND_STEP).gates[-1]
        with mock.patch.object(ref.impl, 'evaluate', side_effect=OSError('unreadable')):
            self.fx.mark()
            report = approve(self.ctx, self.runtime.pipelines, 'tk-1')
        self.assertTrue(report.ok, report.err)

    def test_revision_named_files_never_grant_or_override_native_consent(self):
        ref = self.pipeline.step('approve').gates[0]
        self.assertIsInstance(ref.impl, ApprovalGate)
        base = self.subject.path
        for path in ('planning/revisions/initial.json', 'planning/workflow-import/consent.json'):
            target = base / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"sequence": 999, "approved": true}')
        self.assertTrue(ref.impl.evaluate(self.ctx, self.subject).passed)
        (base / 'design.md').write_text('unapproved new bytes')
        self.assertEqual(ref.impl.evaluate(self.ctx, self.subject).status, Status.FAIL)

    def test_exact_subject_path_resolves_without_profile_dependencies(self):
        pipeline, subject = subject_pipeline(self.ctx, self.subject)
        self.assertIs(pipeline, self.pipeline)
        self.assertEqual(subject.path, self.subject.path)


if __name__ == '__main__':
    unittest.main()
