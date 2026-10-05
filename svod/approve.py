"""The approve command: record a plan approval a person left as a mark in the chat."""
from . import keys
from .approval import (clear_mark, digest, field_names, is_fresh, mark_keys, names_any, now,
                       read_mark, set_fields)
from .checkouts import subject_context
from .gates import (ApprovalGate, PARAM_BIND, PARAM_FILE, PARAM_IGNORE, PARAM_MARKER,
                    PARAM_STRIP)
from .identity import approver
from .render import INDENT, KEYS_SEPARATOR, Report
from .resolve import resolve

SHA_SHOWN = 12
NO_SHA = "-"


def approval_ref(pipeline):
    """First step gate use of the pipeline that is an approval gate, or None."""
    return next((ref for step in pipeline.steps for ref in step.gates
                 if isinstance(ref.impl, ApprovalGate)), None)


def candidates(ctx, pipelines, query):
    """(subject, approval gate use) of every open subject the query names, and the resolution."""
    found = resolve(ctx, pipelines, query)
    pairs = [(subject, approval_ref(pipeline)) for pipeline, subject in found.matches
             if subject.exists and not subject.archived]
    return [(s, ref) for s, ref in pairs if ref is not None], found


def refusal(ctx, key, **facts):
    """Report of a refused approval."""
    return Report(ok=False, err=[ctx.locale.text(key, **facts)], refused=True)


def approve(ctx, pipelines, query, at=None):
    """Write date, approver and digest when a fresh mark allows it, then consume the mark."""
    locale = ctx.locale
    found, resolution = candidates(ctx, pipelines, query)
    if not any(subject.exists for _, subject in resolution.matches):
        return Report(ok=False, err=[locale.text(keys.STATUS_NOT_FOUND, query=query)])
    if not found:
        return refusal(ctx, keys.APPROVE_NO_GATE, query=query)
    if len(found) > 1:
        err = [locale.text(keys.STATUS_AMBIGUOUS)]
        err += [INDENT + locale.text(keys.STATUS_CANDIDATE, id=s.id) for s, _ in found]
        return Report(ok=False, err=err)
    subject, ref = found[0]
    mark = read_mark(ctx.root)
    if not is_fresh(mark, ctx.config.approval_window, at):
        return refusal(ctx, keys.APPROVE_NO_MARK)
    named = mark_keys(mark)
    if named and not names_any(named, subject.keys):
        return refusal(ctx, keys.APPROVE_FOREIGN_KEY, mark_keys=KEYS_SEPARATOR.join(sorted(named)),
                       keys=KEYS_SEPARATOR.join(sorted(subject.keys)))
    who = approver(ctx)
    if who is None:
        return refusal(ctx, keys.APPROVE_NO_APPROVER)
    marker, by_field, sha_field = field_names(ref.params[PARAM_MARKER])
    date = (at or now()).date().isoformat()
    values = {marker: date, by_field: who}
    bind = ref.params.get(PARAM_BIND)
    sha = digest(subject.path, bind, ref.params.get(PARAM_IGNORE),
                 ref.params.get(PARAM_STRIP)) if bind else ""
    if bind:
        values[sha_field] = sha
    path = subject.path / ref.params[PARAM_FILE]
    set_fields(path, values)
    clear_mark(ctx.root)
    root = subject_context(ctx, subject).root
    return Report(ok=True, out=[locale.text(
        keys.APPROVE_DONE, file=path.relative_to(root).as_posix(), marker=marker, date=date,
        by=who, sha=sha[:SHA_SHOWN] or NO_SHA)])
