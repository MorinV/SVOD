"""Public local workflow API. Execution is argv-only and never publishes source."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from . import local_evidence as evidence
from . import local_workflow as workflow
from .approval import digest
from .context import Context
from .loader import load_runtime
from .resolve import exact_pairs, key_pairs

COMMAND_TIMEOUT = 600


def state(root, key, *, recorded=False):
    """Resolve one exact native subject/key; never accept fuzzy substring selection."""
    runtime = load_runtime(Path(root).resolve())
    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    # Container ids are store-relative; its provider's match_exact accepts the leaf name.
    matches = [(p, s) for p in runtime.pipelines for s in p.subject.impl.enumerate(ctx)
               if s.id == key]
    if not matches:
        matches = exact_pairs(ctx, runtime.pipelines, key)
    if not matches:
        matches = key_pairs(ctx, runtime.pipelines, key)
    matches = [(p, s) for p, s in matches if s.exists and not s.archived]
    if len(matches) != 1:
        raise ValueError('key must identify one exact current local task')
    pipeline, subject = matches[0]
    if not any(workflow.is_local_phase(ref, {'contract', 'result', 'complete'})
               for ref in pipeline.gate_refs()):
        raise ValueError('pipeline does not declare the local workflow')
    return ctx, subject, workflow.policy(ctx, subject, recorded=recorded)


def prepare(root, key):
    """Validate compact input and live clean source; does not grant or write consent."""
    return state(root, key)[2]


def _stop_owned_group(process):
    """Stop descendants in the owned POSIX session, including after leader exit.

    This is cleanup, not a sandbox: descendants that create another session escape it.
    """
    def send(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
    try:
        send(signal.SIGTERM)
        until = time.monotonic() + 2
        while time.monotonic() < until:
            process.poll()
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                process.wait()
                return
            time.sleep(.01)
        send(signal.SIGKILL)
        process.wait(timeout=2)
    except BaseException:
        # Group cleanup can fail (for example an OS permission denial). Never
        # abandon the direct child, and propagate failure rather than claim PASS.
        try:
            if process.poll() is None:
                process.kill()
        finally:
            process.wait(timeout=2)
        raise


def checks(root, key):
    """Run once, retain actual output and pre/post Git observations, report failure honestly."""
    from .workflow_policy import required_prerequisites, subject_pipeline, step_applies
    from .position import applies, evaluate, first_blocking
    ctx, subject, policy = state(root, key)
    pipeline, resolved = subject_pipeline(ctx, subject)
    for step in pipeline.steps:
        if not step.blocks_code or not step_applies(step, resolved):
            continue
        entries = [evaluate(ctx, ref, resolved) for ref in step.entry if applies(ref, resolved)]
        outcomes = [evaluate(ctx, ref, resolved) for ref in step.gates if applies(ref, resolved)]
        if not step.gates or first_blocking(entries) or any(not item.passed for item in outcomes):
            raise ValueError('readiness prerequisites pending at ' + step.id)
    if policy['command'] is not None and os.name != 'posix':
        raise ValueError('local command cleanup requires POSIX')
    required_prerequisites(ctx, subject,
                           exclude=lambda ref: workflow.is_local_phase(ref, {'result', 'complete'}))
    consent = workflow.initial_approval(ctx, subject)
    contract_sha = digest(subject.path, evidence.plan_patterns(ctx, subject))
    approval_sha = evidence.sha(consent) if consent is not None else None
    head = evidence.git_ref(policy['workspace'])
    # A new attempt invalidates old completion even when it fails or is interrupted.
    evidence.confined(subject.path, workflow.DELIVERY).unlink(missing_ok=True)
    receipt = evidence.confined(subject.path, evidence.RECEIPT)
    receipt.unlink(missing_ok=True)
    log = evidence.confined(subject.path, evidence.LOG)
    log.parent.mkdir(parents=True, exist_ok=True)
    code = None
    with log.open('wb') as output:
        if policy['command'] is None:
            output.write(b'No command selected.\n')
        else:
            try:
                child = subprocess.Popen(policy['command'], cwd=policy['workspace'],
                                         stdout=output, stderr=subprocess.STDOUT,
                                         shell=False, start_new_session=True)
                try:
                    code = child.wait(timeout=COMMAND_TIMEOUT)
                finally:
                    _stop_owned_group(child)
            except (OSError, subprocess.SubprocessError) as exc:
                code = -1
                output.write((type(exc).__name__ + ': ' + str(exc) + '\n').encode())
    after, source_error = None, None
    try:
        after = evidence.git_ref(policy['workspace'])
    except workflow.ERRORS as exc:
        source_error = str(exc)
    value = {'command': policy['command'], 'cwd': policy['workspace'], 'git_ref': head,
             'git_ref_after': after, 'source_error': source_error, 'exit_code': code,
             'log': evidence.LOG, 'log_sha': evidence.sha(log.read_bytes()),
             'contract_sha': contract_sha, 'approval_sha': approval_sha}
    receipt.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    try:
        workflow.checks(ctx, subject)
        reason = None
    except workflow.ERRORS as exc:
        reason = str(exc)
    return {'passed': reason is None, 'receipt': str(receipt), 'log': str(log),
            'exit_code': code, 'reason': reason}


def verify(root, key):
    """Verify current evidence against live clean source (not just durable completion)."""
    ctx, subject, _ = state(root, key)
    workflow.checks(ctx, subject)
    return {'passed': True, 'receipt': str(subject.path / evidence.RECEIPT)}


def deliver(root, key):
    """Record local completion after live validation; later read it without source."""
    ctx, subject, _ = state(root, key)
    target = evidence.confined(subject.path, workflow.DELIVERY)
    value = workflow.completion_record(ctx, subject)
    if target.is_file():
        workflow.delivery(ctx, subject)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        workflow.delivery(ctx, subject)
    return {'passed': True, 'completion': str(target)}
