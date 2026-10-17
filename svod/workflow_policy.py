"""Declaration-based workflow selection, independent of profile stage names."""
import json

from .errors import ParamError
from .gates import ApprovalGate


def step_applies(step, subject):
    """Absent predicates apply; declared predicates use subject attribute truthiness."""
    return not step.when or bool(subject.attrs.get(step.when))


def approval_refs(pipeline, purpose=None):
    """Unique declared approval mechanisms in declaration order."""
    refs, seen = [], set()
    for step in pipeline.steps:
        for ref in step.gates:
            if not isinstance(ref.impl, ApprovalGate):
                continue
            if purpose is not None and ref.purpose != purpose:
                continue
            identity = (ref.gate, json.dumps(ref.params, sort_keys=True), ref.purpose, ref.when)
            if identity not in seen:
                seen.add(identity)
                refs.append(ref)
    return refs


def approval_ref(pipeline, purpose):
    """Select exactly one semantic approval, refusing missing or ambiguous links."""
    refs = approval_refs(pipeline, purpose)
    if len(refs) != 1:
        raise ParamError(f"{pipeline.name}: expected one approval for purpose {purpose!r}")
    return refs[0]


def subject_pipeline(ctx, subject):
    """Resolve the exact subject through native providers, never a route-name guess."""
    from .resolve import resolve

    if subject.path is None:
        raise ValueError('subject has no path')
    query = (subject.path.resolve().relative_to(ctx.root.resolve()).as_posix()
             if subject.path is not None else subject.id)
    resolution = resolve(ctx, list(ctx.pipelines.values()), query)
    matches = [(pipeline, found) for pipeline, found in resolution.matches
               if found.exists and found.path is not None
               and found.path.resolve() == subject.path.resolve()]
    if resolution.ambiguous or len(matches) != 1:
        raise ValueError('missing or ambiguous subject pipeline')
    return matches[0]


def contract_approval(ctx, subject):
    """Select declared contract consent, or None when absent/inapplicable.

    Explicit purpose does not require a code-blocking stage. Untagged blockers
    retain only the unique structural bootstrap; malformed/ambiguous selection
    refuses rather than being treated as an intentionally consent-free route.
    """
    pipeline, resolved = subject_pipeline(ctx, subject)
    refs, seen, artifacts = [], set(), set()
    for step in pipeline.steps:
        if not step_applies(step, resolved):
            continue
        for ref in step.gates:
            if ref.when and not resolved.attrs.get(ref.when):
                continue
            if not isinstance(ref.impl, ApprovalGate):
                artifacts.update(ref.params[key] for key in ('path', 'glob')
                                 if isinstance(ref.params.get(key), str))
                continue
            if ref.severity == 'warn' or (ref.purpose != 'contract' and not step.blocks_code):
                continue
            identity = json.dumps(ref.params, sort_keys=True)
            identity = (identity, ref.purpose)
            if identity not in seen:
                seen.add(identity)
                refs.append(ref)
    tagged = [ref for ref in refs if ref.purpose == 'contract']
    tagged_policy = approval_refs(pipeline, 'contract')
    if tagged_policy:
        candidates = tagged
    else:
        untagged = [ref for ref in refs if ref.purpose is None]
        candidates = [ref for ref in untagged if ref.params.get('bind')]
        if untagged and not candidates:
            raise ValueError('missing bound contract approval')
        if len(candidates) > 1:
            from fnmatch import fnmatchcase
            candidates = [ref for ref in candidates if any(
                artifact == pattern or fnmatchcase(artifact, pattern)
                for artifact in artifacts for pattern in ref.params['bind'])]
            if not candidates:
                raise ValueError('missing or ambiguous bound contract approval')
    if not candidates:
        return None
    if len(candidates) != 1 or not candidates[0].params.get('bind'):
        raise ValueError('missing or ambiguous bound contract approval')
    return candidates[0]


def required_prerequisites(ctx, subject, *, exclude):
    """Evaluate applicable required YAML conditions without the terminal reader itself.

    Callers exclude their own gate mechanism, not a whole stage: other gates in
    that stage, pipeline entries and required step entries remain prerequisites.
    Use native outcomes and severity, including UNKNOWN refusal and skipped uses.
    """
    from .position import applies, evaluate, first_blocking

    pipeline, resolved = subject_pipeline(ctx, subject)
    pending = []
    entries = [evaluate(ctx, ref, resolved) for ref in pipeline.entry
               if applies(ref, resolved) and not exclude(ref)]
    if first_blocking(entries):
        pending.append('entry')
    for step in pipeline.steps:
        if not step.required or step.optional or not step_applies(step, resolved):
            continue
        entries = [evaluate(ctx, ref, resolved) for ref in step.entry
                   if applies(ref, resolved) and not exclude(ref)]
        refs = [ref for ref in step.gates if applies(ref, resolved) and not exclude(ref)]
        outcomes = [evaluate(ctx, ref, resolved) for ref in refs]
        if (first_blocking(entries) or not step.gates
                or any(not outcome.passed for outcome in outcomes)):
            pending.append(step.id)
    if pending:
        raise ValueError('required prerequisites pending: ' + ', '.join(pending))


def binding_patterns(pipeline, purpose):
    """Copy selected bindings without exposing the declaration to caller mutation."""
    return list(approval_ref(pipeline, purpose).params.get('bind', []))


def same_approval(impl, ref):
    """Repeated uses of the selected mechanism and params are one consent event."""
    return ref is not None and impl.name == ref.impl.name and impl.params == ref.params


def result_approval(ctx, subject):
    """Select applicable result consent, structurally bootstrapping untagged policy."""
    from .approve import applicable_approvals

    pipeline, resolved = subject_pipeline(ctx, subject)
    refs = applicable_approvals(pipeline, resolved)
    tagged = [ref for ref in refs if ref.purpose == 'result']
    if tagged:
        candidates = tagged
    else:
        blockers = [ref for step in pipeline.steps if step.blocks_code
                    for ref in step.gates if isinstance(ref.impl, ApprovalGate)]
        candidates = [ref for ref in refs if ref.purpose is None and ref.params.get('bind')
                      and not any(same_approval(ref.impl, blocker) for blocker in blockers)]
    if len(candidates) > 1:
        raise ValueError('ambiguous bound result approval')
    if not candidates:
        return None
    if not candidates[0].params.get('bind'):
        raise ValueError('result approval must bind its inputs')
    return candidates[0]
