"""The approve command: record a plan approval a person left as a mark in the chat."""
from . import keys
from .approval import (bound_files,
                       consume_mark, digest, field_names, is_fresh, mark_keys, mark_time,
                       names_any, now, read_mark, set_fields)
from .checkouts import subject_context
from .gates import (ApprovalGate, PARAM_BIND, PARAM_FILE, PARAM_IGNORE, PARAM_MARKER,
                    PARAM_STRIP)
from .identity import approver
from .pipeline import applies, evaluate, first_blocking, run_entries, step_applies
from .render import INDENT, KEYS_SEPARATOR, Report
from .resolve import resolve
from .workflow_policy import applicable_approvals

SHA_SHOWN = 12
NO_SHA = "-"


def selected_step(pipeline, step):
    """The explicitly named step, or None when the pipeline does not contain it."""
    return next((item for item in pipeline.steps if item.id == step), None)


def approval_ref(pipeline, step=None, subject=None):
    """First applicable approval, optionally restricted to an explicitly named stage."""
    return next(iter(applicable_approvals(pipeline, subject, step)), None)


def candidates(ctx, pipelines, query, step=None):
    """(subject, approval gate use) of every open subject the query names, and the resolution."""
    found = resolve(ctx, pipelines, query)
    pairs = []
    for pipeline, subject in found.matches:
        if not subject.exists or subject.archived:
            continue
        refs = applicable_approvals(pipeline, subject, step)
        ref = next(iter(refs), None)
        if step is None:
            own = subject_context(ctx, subject)
            ref = next((item for item in refs
                        if not evaluate(own, item, subject).passed), ref)
        pairs.append((subject, ref))
    return [(s, ref) for s, ref in pairs if ref is not None], found


def refusal(ctx, key, **facts):
    """Report of a refused approval."""
    return Report(ok=False, err=[ctx.locale.text(key, **facts)], refused=True)


def passed(ctx, refs, subject):
    """Whether a nonempty group of gate refs passes in the subject's own checkout."""
    if not refs:
        return False
    try:
        return all(ref.impl.evaluate(ctx, subject).passed for ref in refs)
    except OSError:
        return False


def pending_prerequisites(ctx, pipeline, subject, step):
    """Ids of preceding nonoptional steps and selected non-approval gates not yet passed."""
    own = subject_context(ctx, subject)
    selected = selected_step(pipeline, step)
    if selected is None or approval_ref(pipeline, step, subject) is None:
        return [step]
    pending = ['entry'] if first_blocking(run_entries(own, pipeline.entry, subject)) else []
    for item in pipeline.steps[:pipeline.steps.index(selected)]:
        if item.optional or not step_applies(item, subject):
            continue
        refs = [ref for ref in item.gates if applies(ref, subject)]
        if (first_blocking(run_entries(own, item.entry, subject))
                or (refs or not item.gates) and not passed(own, refs, subject)):
            pending.append(item.id)
    other = [ref for ref in selected.gates
             if not isinstance(ref.impl, ApprovalGate) and applies(ref, subject)]
    if (first_blocking(run_entries(own, selected.entry, subject))
            or other and not passed(own, other, subject)):
        pending.append(selected.id)
    return list(dict.fromkeys(pending))


def changed_after_mark(base, bind, mark):
    """Whether exact bound evidence cannot be shown to predate the human approval mark."""
    left = mark_time(mark)
    if left is None:
        return True
    try:
        files = bound_files(base, bind)
        return not files or max(path.stat().st_mtime for path in files) > left.timestamp()
    except (OSError, OverflowError):
        return True


def approve(ctx, pipelines, query, at=None, step=None):
    """Write approval fields, then consume only this subject's named approval keys."""
    locale = ctx.locale
    found, resolution = candidates(ctx, pipelines, query, step)
    if not any(subject.exists for _, subject in resolution.matches):
        return Report(ok=False, err=[locale.text(keys.STATUS_NOT_FOUND, query=query)])
    if not found:
        if step is not None:
            matched = [(pipeline, subject) for pipeline, subject in resolution.matches
                       if subject.exists and not subject.archived]
            key = (keys.APPROVE_NO_STEP if not any(selected_step(pipeline, step)
                                                   for pipeline, _ in matched)
                   else keys.APPROVE_STEP_NO_GATE)
            return refusal(ctx, key, query=query, step=step)
        return refusal(ctx, keys.APPROVE_NO_GATE, query=query)
    if len(found) > 1:
        err = [locale.text(keys.STATUS_AMBIGUOUS)]
        err += [INDENT + locale.text(keys.STATUS_CANDIDATE, id=s.id) for s, _ in found]
        return Report(ok=False, err=err)
    subject, ref = found[0]
    if step is None:
        pipeline = next(pipeline for pipeline, item in resolution.matches if item is subject)
        step = next(item.id for item in pipeline.steps
                    if step_applies(item, subject) and any(gate is ref for gate in item.gates))
    if step is not None:
        pipeline = next(pipeline for pipeline, item in resolution.matches if item is subject)
        pending = pending_prerequisites(ctx, pipeline, subject, step)
        if pending:
            return refusal(ctx, keys.APPROVE_NOT_READY, query=query, step=step,
                           pending=KEYS_SEPARATOR.join(pending))
    mark = read_mark(ctx.root)
    if not is_fresh(mark, ctx.config.approval_window, at):
        return refusal(ctx, keys.APPROVE_NO_MARK)
    named = mark_keys(mark)
    if named and not names_any(named, subject.keys):
        return refusal(ctx, keys.APPROVE_FOREIGN_KEY, mark_keys=KEYS_SEPARATOR.join(sorted(named)),
                       keys=KEYS_SEPARATOR.join(sorted(subject.keys)))
    bind = ref.params.get(PARAM_BIND)
    try:
        if bind and not bound_files(subject.path, bind):
            return refusal(ctx, keys.APPROVE_NOT_READY, query=query, step=step, pending=step)
        if step is not None and bind and changed_after_mark(subject.path, bind, mark):
            return refusal(ctx, keys.APPROVE_CHANGED_AFTER_MARK, query=query, step=step)
        sha = digest(subject.path, bind, ref.params.get(PARAM_IGNORE),
                     ref.params.get(PARAM_STRIP)) if bind else ""
    except OSError:
        return refusal(ctx, keys.APPROVE_CHANGED_AFTER_MARK, query=query, step=step)
    who = approver(ctx)
    if who is None:
        return refusal(ctx, keys.APPROVE_NO_APPROVER)
    marker, by_field, sha_field = field_names(ref.params[PARAM_MARKER])
    date = (at or now()).date().isoformat()
    values = {marker: date, by_field: who}

    if bind:
        values[sha_field] = sha
    path = subject.path / ref.params[PARAM_FILE]
    set_fields(path, values)
    consume_mark(ctx.root, subject.keys, mark)
    root = subject_context(ctx, subject).root
    return Report(ok=True, out=[locale.text(
        keys.APPROVE_DONE, file=path.relative_to(root).as_posix(), marker=marker, date=date,
        by=who, sha=sha[:SHA_SHOWN] or NO_SHA)])
