"""Standalone local execution against native declarations and actual Git bytes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from unittest.mock import patch

import yaml

from svod import hooks
from svod.approve import approve
from svod.context import Context
from svod.loader import load_runtime
from svod.position import position
from svod import local_runner as local


class LocalWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'store'
        self.source = self.base / 'source'
        self.root.mkdir()
        self.source.mkdir()
        self.git(self.root, 'init', '-q')
        self.git(self.root, 'config', 'user.name', 'Local Tester')
        self.git(self.root, 'config', 'user.email', 'local@example.invalid')
        self.git(self.source, 'init', '-q')
        self.git(self.source, 'config', 'user.name', 'Local Tester')
        self.git(self.source, 'config', 'user.email', 'local@example.invalid')
        (self.source / 'source.txt').write_text('exact source\n')
        self.git(self.source, 'add', '.')
        self.git(self.source, 'commit', '-qm', 'fixture')
        self.task = self.root / 'tasks' / 'demo-task'
        (self.task / 'testing').mkdir(parents=True)
        self.write('svod.yaml', yaml.safe_dump({
            'locale': 'en', 'profile': 'profile', 'local_config': 'local.yaml',
            'approval': {'phrases': ['Approved']}, 'update_check': False}))
        self.write('local.yaml', 'login: tester\nemail: local@example.invalid\n')
        self.write('profile/gates/current.py',
                   'from svod.local_workflow import CurrentProcessGate\n'
                   'GATES = {CurrentProcessGate.name: CurrentProcessGate}\n')
        self.declaration = {
            'pipeline': 'portable',
            'subject': {'provider': 'container', 'params': {'roots': ['tasks']}},
            'done': {'gate': 'current_process', 'params': {'phase': 'complete'}, 'text': 'local.done'},
            'steps': [
                {'id': 'contract', 'required': True, 'text': 'local.contract',
                 'gates': [{'gate': 'current_process', 'params': {'phase': 'contract'}}]},
                {'id': 'consent', 'required': True, 'blocks_code': True,
                 'text': 'local.approve', 'gates': [{'gate': 'approval',
                 'params': {'file': 'approval.yaml', 'marker': 'approved',
                            'bind': ['contract.md', 'testing/plan.yaml']}}]},
                {'id': 'result', 'required': True, 'text': 'local.result',
                 'gates': [{'gate': 'current_process', 'params': {'phase': 'result'}}]},
            ]}
        self.save_declaration()
        self.write('profile/locale/en.yaml', yaml.safe_dump({
            'gate.current_process': 'Local process: {phase}',
            'local.contract': 'Prepare the compact contract.',
            'local.approve': 'Obtain contract approval.',
            'local.result': 'Run the selected command.', 'local.done': 'Local completion recorded.'}))
        self.write('tasks/demo-task/contract.md', '# Contract\nObserve the selected command on exact clean source.\n')
        self.plan = {'version': 1, 'kind': 'process', 'contract': 'contract.md',
                     'workspace': str(self.source),
                     'command': [sys.executable, '-c', 'print("observed result")']}
        self.save_plan()

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], text=True,
                              capture_output=True, check=True).stdout.strip()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def save_plan(self):
        self.write('tasks/demo-task/testing/plan.yaml', yaml.safe_dump(self.plan))

    def save_declaration(self):
        self.write('profile/pipelines/local.yaml', yaml.safe_dump(self.declaration))

    def context(self):
        runtime = load_runtime(self.root)
        return runtime, Context(runtime.config, runtime.locale,
                                bindings=runtime.bindings, pipelines=runtime.by_name())

    def consent(self):
        # This is a synthetic user event in a disposable store, not fabricated approval fields.
        event = {'hook_event_name': 'UserPromptSubmit', 'cwd': str(self.root), 'prompt': 'Approved'}
        previous = os.environ.pop(hooks.PROJECT_ENV, None)
        try:
            hooks.prompt_hook(event, self.root)
        finally:
            if previous is not None:
                os.environ[hooks.PROJECT_ENV] = previous
        runtime, ctx = self.context()
        result = approve(ctx, runtime.pipelines, 'demo-task')
        self.assertTrue(result.ok, result.err)

    def test_rejects_noncompact_plan_and_symlink_paths(self):
        for field, value in [('version', True), ('command', 'echo not argv'),
                             ('workspace', 'relative/path'), ('contract', '../escape')]:
            with self.subTest(field=field):
                original = self.plan[field]
                self.plan[field] = value
                self.save_plan()
                with self.assertRaises(ValueError):
                    local.prepare(self.root, 'demo-task')
                self.plan[field] = original
        self.save_plan()
        contract = self.task / 'contract.md'
        contract.unlink()
        contract.symlink_to(self.source / 'source.txt')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            local.prepare(self.root, 'demo-task')

    def test_approval_file_tamper_invalidates_completion(self):
        self.consent()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        local.deliver(self.root, 'demo-task')
        shutil.rmtree(self.source)
        approval = self.task / 'approval.yaml'
        approval.write_text(approval.read_text() + '# altered after execution\n')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.recorded_delivery()

    def recorded_delivery(self):
        from svod.local_workflow import delivery
        runtime, ctx = self.context()
        subject = runtime.pipelines[0].subject.impl.match_exact('demo-task', ctx)[0]
        return delivery(ctx, subject)

    def test_checks_invalidates_previous_completion_on_failed_rerun(self):
        self.consent()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        local.deliver(self.root, 'demo-task')
        self.plan['command'] = [sys.executable, '-c', 'raise SystemExit(3)']
        self.save_plan()
        self.consent()
        self.assertFalse(local.checks(self.root, 'demo-task')['passed'])
        self.assertFalse((self.task / 'delivery/process.yaml').exists())

    def test_native_cli_validates_and_reports_status(self):
        command = [sys.executable, '-c', 'from svod.cli import main; raise SystemExit(main())',
                   '--root', str(self.root)]
        result = subprocess.run(command + ['validate'], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        result = subprocess.run(command + ['status', 'demo-task'], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Obtain contract approval', result.stdout)

    def test_prepare_uses_native_flat_subject(self):
        self.assertEqual(self.plan, local.prepare(self.root, 'demo-task'))
        runtime, ctx = self.context()
        subject = runtime.pipelines[0].subject.impl.match_exact('demo-task', ctx)[0]
        self.assertEqual('consent', position(ctx, runtime.pipelines[0], subject).current.step.id)


    def test_real_command_and_durable_completion(self):
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertTrue(result['passed'], result)
        self.assertEqual('observed result\n', Path(result['log']).read_text())
        receipt = json.loads(Path(result['receipt']).read_text())
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), receipt['git_ref'])
        self.assertEqual(receipt['git_ref'], receipt['git_ref_after'])
        self.assertTrue(local.verify(self.root, 'demo-task')['passed'])
        self.assertTrue(local.deliver(self.root, 'demo-task')['passed'])
        shutil.rmtree(self.source)
        self.assertTrue(self.recorded_delivery())
        with self.assertRaises((OSError, ValueError, subprocess.SubprocessError)):
            local.deliver(self.root, 'tasks/demo-task')
        runtime, ctx = self.context()
        subject = runtime.pipelines[0].subject.impl.match_exact('demo-task', ctx)[0]
        self.assertIsNotNone(position(ctx, runtime.pipelines[0], subject).done)
        with self.assertRaises((OSError, ValueError, subprocess.SubprocessError)):
            local.verify(self.root, 'demo-task')

    def test_missing_consent_never_executes(self):
        with self.assertRaisesRegex(ValueError, 'prerequisites|approval'):
            local.checks(self.root, 'demo-task')
        self.assertFalse((self.task / 'testing/process/receipt.json').exists())
        self.assertFalse((self.task / 'approval.yaml').exists())

    def test_binding_coverage_uses_actual_glob_expansion(self):
        self.declaration['steps'][1]['gates'][0]['params']['bind'] = ['*.md', 'test*']
        self.save_declaration()
        with self.assertRaisesRegex(ValueError, 'bind compact'):
            local.prepare(self.root, 'demo-task')
        self.assertFalse((self.task / 'testing/process/command.log').exists())

    def test_result_approval_follows_execution_and_blocks_delivery(self):
        self.declaration['steps'].append({'id': 'accept_result', 'required': True,
            'text': 'local.approve', 'gates': [{'gate': 'approval', 'purpose': 'result',
                'params': {'file': 'result-approval.yaml', 'marker': 'accepted',
                    'bind': ['testing/process/receipt.json', 'testing/process/command.log']}}]})
        self.save_declaration()
        self.consent()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        with self.assertRaisesRegex(ValueError, 'accept_result'):
            local.deliver(self.root, 'demo-task')
        self.consent()
        self.assertTrue(local.deliver(self.root, 'demo-task')['passed'])

    def test_failure_is_retained_but_cannot_complete(self):
        self.plan['command'] = [sys.executable, '-c', 'print("actual failure"); raise SystemExit(7)']
        self.save_plan()
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertFalse(result['passed'])
        self.assertEqual(7, result['exit_code'])
        self.assertEqual('actual failure\n', Path(result['log']).read_text())
        with self.assertRaises(ValueError):
            local.deliver(self.root, 'demo-task')

    def test_null_command_is_explicit_not_a_test_pass(self):
        self.plan['command'] = None
        self.save_plan()
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertTrue(result['passed'], result)
        self.assertIsNone(result['exit_code'])
        self.assertEqual('No command selected.\n', Path(result['log']).read_text())
        self.assertTrue(local.deliver(self.root, 'demo-task')['passed'])


    def test_nonrequired_code_blocker_still_prevents_execution(self):
        self.declaration['steps'].insert(0, {'id': 'access', 'blocks_code': True,
            'text': 'local.contract', 'gates': [
                {'gate': 'artifact', 'params': {'path': 'access-granted'}}]})
        self.save_declaration()
        (self.task / 'access-granted').touch()
        self.consent()
        (self.task / 'access-granted').unlink()
        with self.assertRaisesRegex(ValueError, 'access'):
            local.checks(self.root, 'demo-task')
        self.assertFalse((self.task / 'testing/process/command.log').exists())

    def test_dirty_source_is_rejected_before_execution(self):
        self.consent()
        (self.source / 'untracked').write_text('dirty')
        with self.assertRaisesRegex(ValueError, 'dirty'):
            local.checks(self.root, 'demo-task')
        self.assertFalse((self.task / 'testing/process/command.log').exists())

    def test_python_command_leaves_no_bytecode_in_source(self):
        """Importing a module of the source writes no __pycache__: the checkout stays clean."""
        (self.source / 'helper.py').write_text('VALUE = 1\n', encoding='utf-8')
        self.git(self.source, 'add', '-A')
        self.git(self.source, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'helper')
        self.plan['command'] = [sys.executable, '-c', 'import helper; print(helper.VALUE)']
        self.save_plan()
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertTrue(result['passed'], result)
        self.assertFalse((self.source / '__pycache__').exists())

    def test_command_that_dirties_source_records_failed_post_observation(self):
        self.plan['command'] = [sys.executable, '-c',
                                'from pathlib import Path; Path("dirty").write_text("changed")']
        self.save_plan()
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertFalse(result['passed'])
        receipt = json.loads(Path(result['receipt']).read_text())
        self.assertIsNone(receipt['git_ref_after'])
        self.assertIn('dirty', receipt['source_error'])
        (self.source / 'dirty').unlink()
        with self.assertRaises(ValueError):
            local.verify(self.root, 'demo-task')

    def test_live_head_drift_invalidates_receipt(self):
        self.consent()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        self.git(self.source, 'commit', '--allow-empty', '-qm', 'later source')
        with self.assertRaisesRegex(ValueError, 'stale'):
            local.verify(self.root, 'demo-task')
        with self.assertRaises(ValueError):
            local.deliver(self.root, 'demo-task')

    def test_changed_contract_requires_new_native_consent_and_result(self):
        self.consent()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        (self.task / 'contract.md').write_text('Changed scope\n')
        with self.assertRaisesRegex(ValueError, 'approval'):
            local.verify(self.root, 'demo-task')
        with self.assertRaises(ValueError):
            local.checks(self.root, 'demo-task')
        self.consent()
        with self.assertRaises(ValueError):
            local.verify(self.root, 'demo-task')
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])

    def test_log_and_completion_tamper_fail_after_source_removed(self):
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertTrue(result['passed'])
        local.deliver(self.root, 'demo-task')
        shutil.rmtree(self.source)
        log = Path(result['log'])
        original = log.read_bytes()
        log.write_bytes(b'invented output\n')
        with self.assertRaises(ValueError):
            self.recorded_delivery()
        log.write_bytes(original)
        self.assertTrue(self.recorded_delivery())
        (self.task / 'delivery/process.yaml').write_text('result_sha: altered\n')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.recorded_delivery()

    def test_duplicate_receipt_fields_are_rejected(self):
        self.consent()
        result = local.checks(self.root, 'demo-task')
        path = Path(result['receipt'])
        path.write_text(path.read_text().replace('{', '{"exit_code": 0,', 1))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            local.verify(self.root, 'demo-task')

    def test_duplicate_plan_fields_are_rejected(self):
        """A plan naming one field twice is refused by the shared YAML loader."""
        self.write('tasks/demo-task/testing/plan.yaml',
                   yaml.safe_dump(self.plan) + 'kind: process\n')
        with self.assertRaisesRegex(ValueError, 'duplicate key: kind'):
            local.prepare(self.root, 'demo-task')

    def test_declared_entry_and_result_side_conditions_are_not_skipped(self):
        self.declaration['entry'] = [{'gate': 'artifact', 'params': {'path': 'permit'},
                                      'severity': 'block', 'text': 'local.contract'}]
        self.declaration['steps'][2]['gates'].append({'gate': 'artifact', 'params': {'path': 'review'}})
        self.save_declaration()
        (self.task / 'permit').touch()
        self.consent()
        (self.task / 'permit').unlink()
        with self.assertRaisesRegex(ValueError, 'entry'):
            local.checks(self.root, 'demo-task')
        (self.task / 'permit').touch()
        with self.assertRaisesRegex(ValueError, 'result'):
            local.checks(self.root, 'demo-task')
        (self.task / 'review').touch()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        local.deliver(self.root, 'demo-task')
        shutil.rmtree(self.source)
        (self.task / 'review').unlink()
        with self.assertRaisesRegex(ValueError, 'result'):
            self.recorded_delivery()

    def test_code_blocking_step_entry_and_gate_gate_readiness(self):
        """checks refuses at the blocks_code step while its entry blocks or freeze() holds it."""
        self.declaration['steps'][1]['entry'] = [{'gate': 'artifact', 'params': {'path': 'permit'},
                                                  'severity': 'block', 'text': 'local.contract'}]
        self.save_declaration()
        with self.assertRaisesRegex(ValueError, 'readiness prerequisites pending at consent'):
            local.checks(self.root, 'demo-task')
        (self.task / 'permit').touch()
        self.consent()
        (self.task / 'permit').unlink()
        with self.assertRaisesRegex(ValueError, 'readiness prerequisites pending at consent'):
            local.checks(self.root, 'demo-task')
        (self.task / 'permit').touch()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])

    def test_conditional_required_step_is_honored(self):
        self.declaration['steps'].append({'id': 'conditional', 'when': 'not_selected',
            'required': True, 'text': 'local.result', 'gates': [
                {'gate': 'artifact', 'params': {'path': 'not-required'}}]})
        self.save_declaration()
        self.consent()
        self.assertTrue(local.checks(self.root, 'demo-task')['passed'])
        self.assertTrue(local.deliver(self.root, 'demo-task')['passed'])

    def test_intentionally_consent_free_policy_does_not_invent_approval(self):
        self.declaration['steps'].pop(1)
        self.save_declaration()
        result = local.checks(self.root, 'demo-task')
        self.assertTrue(result['passed'], result)
        self.assertIsNone(json.loads(Path(result['receipt']).read_text())['approval_sha'])
        self.assertFalse((self.task / 'approval.yaml').exists())

    def test_source_inside_task_is_rejected(self):
        nested = self.task / 'testing' / 'process'
        nested.mkdir()
        self.plan['workspace'] = str(nested)
        self.save_plan()
        with self.assertRaisesRegex(ValueError, 'outside source'):
            local.prepare(self.root, 'demo-task')

    def test_task_inside_source_cannot_be_prepared(self):
        self.plan['workspace'] = str(self.root)
        self.save_plan()
        with self.assertRaisesRegex(ValueError, 'outside source'):
            local.prepare(self.root, 'demo-task')

    def test_fuzzy_and_ambiguous_queries_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exact'):
            local.prepare(self.root, 'demo')
        other = dict(self.declaration, pipeline='other')
        self.write('profile/pipelines/other.yaml', yaml.safe_dump(other))
        with self.assertRaisesRegex(ValueError, 'exact'):
            local.prepare(self.root, 'demo-task')

    def test_cleanup_permission_failure_still_reaps_direct_child(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 start_new_session=True)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        with patch.object(local.os, 'killpg', side_effect=PermissionError('group denied')):
            with self.assertRaises(PermissionError):
                local._stop_owned_group(child)
        self.assertIsNotNone(child.poll())

    def test_timeout_retains_actual_failure_log(self):
        self.plan['command'] = [sys.executable, '-c',
                                'import time; print("started", flush=True); time.sleep(30)']
        self.save_plan()
        self.consent()
        with patch.object(local, 'COMMAND_TIMEOUT', .2):
            result = local.checks(self.root, 'demo-task')
        self.assertFalse(result['passed'])
        self.assertEqual(-1, result['exit_code'])
        self.assertIn('TimeoutExpired', Path(result['log']).read_text())

    def test_descendants_are_stopped_even_after_leader_exits(self):
        marker = self.base / 'descendant-stopped'
        child_code = ('import signal, time; from pathlib import Path; '
            f'signal.signal(signal.SIGTERM, lambda *_: (Path({str(marker)!r}).touch(), exit(0))); '
            'print("ready", flush=True); time.sleep(30)')
        parent_code = ('import subprocess, sys; '
            f'p = subprocess.Popen([sys.executable, "-c", {child_code!r}], stdout=subprocess.PIPE); '
            'assert p.stdout.readline() == b"ready\\n"; print("leader exited")')
        self.plan['command'] = [sys.executable, '-c', parent_code]
        self.save_plan()
        self.consent()
        result = local.checks(self.root, 'demo-task')
        self.assertTrue(result['passed'], result)
        self.assertTrue(marker.exists(), 'descendant did not acknowledge owned cleanup')


if __name__ == '__main__':
    unittest.main()
