"""Native-declaration local contract, observed result and durable completion gates."""
from pathlib import Path
import subprocess

from . import local_evidence as evidence
from .errors import LoadError, ParamError
from .gates import Gate, verdict

DELIVERY = 'delivery/process.yaml'
ERRORS = (OSError, ValueError, KeyError, TypeError, LoadError, subprocess.SubprocessError)


def policy(ctx, subject, *, recorded=False):
    value = evidence.load_policy(subject, recorded=recorded)
    workspace = Path(value['workspace'])
    task = subject.path.resolve()
    if task.is_relative_to(workspace) or workspace.is_relative_to(task):
        raise ValueError('task and logs must be outside source workspace')
    from .workflow_policy import contract_approval
    ref = contract_approval(ctx, subject)
    bind = evidence.plan_patterns(ctx, subject, recorded=recorded)
    from .approval import bound_files
    covered = {path.relative_to(subject.path).as_posix()
               for path in bound_files(subject.path, bind)}
    if not {evidence.PLAN, value['contract']}.issubset(covered):
        raise ValueError('approval must bind compact plan and contract')
    # These compact inputs must be bound in full, not through line filters.
    if ref is not None and (ref.params.get('ignore') or ref.params.get('strip')):
        raise ValueError('compact approval must bind complete plan and contract bytes')
    for pattern in bind:
        evidence.confined(subject.path, pattern)
        for path in subject.path.glob(pattern):
            evidence.confined(subject.path, path.relative_to(subject.path).as_posix())
    if not recorded:
        evidence.git_ref(value['workspace'])
    return value


def initial_approval(ctx, subject):
    from .workflow_policy import contract_approval
    policy(ctx, subject)
    ref = contract_approval(ctx, subject)
    if ref is None:
        return None
    if not ref.impl.evaluate(ctx, subject).passed:
        raise ValueError('missing current human approval')
    return evidence.confined(subject.path, ref.params['file']).read_bytes()


def checks(ctx, subject):
    initial_approval(ctx, subject)
    return evidence.validate(ctx, subject)


def is_local_phase(ref, phases):
    return isinstance(ref.impl, CurrentProcessGate) and ref.impl.params.get('phase') in phases


def completion_record(ctx, subject):
    from .workflow_policy import required_prerequisites
    required_prerequisites(ctx, subject, exclude=lambda ref: is_local_phase(ref, {'complete'}))
    return {'result_sha': evidence.fingerprint(checks(ctx, subject))}


def delivery(ctx, subject):
    """Read durable completion without reopening a disposable source directory."""
    from .workflow_policy import required_prerequisites
    value = evidence.strict_yaml(evidence.confined(subject.path, DELIVERY))
    policy(ctx, subject, recorded=True)
    result = evidence.validate(ctx, subject, recorded=True)
    required_prerequisites(ctx, subject,
                           exclude=lambda ref: is_local_phase(
                               ref, {'contract', 'result', 'complete'}))
    if value != {'result_sha': evidence.fingerprint(result)}:
        raise ValueError('completion is missing or stale')
    return value


class CurrentProcessGate(Gate):
    """Reusable profile opt-in; no globally imposed test or review ceremony."""
    name = 'current_process'
    PARAMS = frozenset({'phase'})
    REQUIRED = PARAMS

    def check(self):
        if self.params['phase'] not in {'contract', 'result', 'complete'}:
            raise ParamError('invalid current process phase')

    def describe(self, params, locale):
        return locale.text('gate.current_process', phase=params['phase'])

    def evaluate(self, ctx, subject):
        try:
            phase = self.params['phase']
            delivered = evidence.confined(subject.path, DELIVERY).is_file()
            if phase in {'contract', 'result'} and delivered:
                try:
                    delivery(ctx, subject)
                    return verdict(True)
                except ERRORS:
                    pass
            {'contract': policy, 'result': checks, 'complete': delivery}[phase](ctx, subject)
            if phase == 'complete':
                recorded = evidence.validate(ctx, subject, recorded=True)
                return verdict(True, git_ref=recorded['git_ref'])
            return verdict(True)
        except ERRORS as exc:
            return verdict(False, reason='process_contract', detail=str(exc))
