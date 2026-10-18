"""The approve command: record a plan approval a person left as a mark in the chat.

Without a fresh mark, --confirm asks the person at the terminal instead: the path for agents
without a prompt hook, where the person, not the agent, answers.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from . import evidence_log, keys
from .approval import (bound_files, consume_mark, digest, is_fresh, mark_keys, mark_time,
                       names_any, now, read_mark, write_fields)
from .checkouts import subject_context
from .gates import (ApprovalGate, PARAM_BIND, PARAM_FILE, PARAM_IGNORE, PARAM_MARKER,
                    PARAM_STRIP)
from .identity import approver
from .pipeline import applies, evaluate, first_blocking, run_entries, step_applies
from .render import INDENT, KEYS_SEPARATOR, Report
from .resolve import resolve
from .workflow_policy import applicable_approvals

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import GateRef, Pipeline, Step
    from .resolve import Resolution
    from .subject import Subject

SHA_SHOWN = 12
NO_SHA = "-"
YES_ANSWERS = frozenset({"y", "yes"})


def selected_step(pipeline: Pipeline, step: str | None) -> Step | None:
    """The explicitly named step, or None when the pipeline does not contain it."""
    return next((item for item in pipeline.steps if item.id == step), None)


def approval_ref(pipeline: Pipeline, step: str | None = None,
                 subject: Subject | None = None) -> GateRef | None:
    """First applicable approval, optionally restricted to an explicitly named stage."""
    return next(iter(applicable_approvals(pipeline, subject, step)), None)


def candidates(ctx: Context, pipelines: list[Pipeline], query: str,
               step: str | None = None) -> tuple[list[tuple[Subject, GateRef]], Resolution]:
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


def refusal(ctx: Context, key: str, **facts: Any) -> Report:
    """Report of a refused approval."""
    return Report(ok=False, err=[ctx.locale.text(key, **facts)], refused=True)


def passed(ctx: Context, refs: list[GateRef], subject: Subject) -> bool:
    """Whether a nonempty group of gate refs passes in the subject's own checkout."""
    if not refs:
        return False
    try:
        return all(ref.impl.evaluate(ctx, subject).passed for ref in refs)
    except OSError:
        return False


def pending_prerequisites(ctx: Context, pipeline: Pipeline, subject: Subject,
                          step: str) -> list[str]:
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


def changed_after_mark(base: Path, bind: list[str], mark: dict[str, Any]) -> bool:
    """Whether exact bound evidence cannot be shown to predate the human approval mark."""
    left = mark_time(mark)
    if left is None:
        return True
    try:
        files = bound_files(base, bind)
        return not files or max(path.stat().st_mtime for path in files) > left.timestamp()
    except (OSError, OverflowError):
        return True


def at_terminal() -> bool:
    """Whether stdin is a terminal a person types into, not a pipe or a file."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def subject_label(subject: Subject) -> str:
    """Keys of the subject as one text, or its id when it has none."""
    return KEYS_SEPARATOR.join(sorted(subject.keys)) or subject.id


def confirmed(ctx: Context, subject: Subject, step: str | None, ref: GateRef,
              files: list[Path], sha: str) -> bool:
    """Show what is approved on stderr and whether the person at the terminal answers yes.

    The binding shown is the subject, the step, the approval file and the bound files with
    the version recorded. Only y or yes, letter case ignored, confirms; end of input does not.
    """
    locale = ctx.locale
    root = subject_context(ctx, subject).root
    label = subject_label(subject)
    # Only existing subjects, which have a path, are approved.
    target = (cast(Path, subject.path) / ref.params[PARAM_FILE]).relative_to(root).as_posix()
    print(locale.text(keys.APPROVE_CONFIRM_PLAN, subject=label, step=step,
                      marker=ref.params[PARAM_MARKER], file=target), file=sys.stderr)
    if files:
        print(locale.text(keys.APPROVE_CONFIRM_FILES, sha=sha[:SHA_SHOWN]), file=sys.stderr)
        for path in files:
            print(INDENT + path.relative_to(root).as_posix(), file=sys.stderr)
    print(locale.text(keys.APPROVE_CONFIRM_QUESTION, subject=label), end="",
          file=sys.stderr, flush=True)
    try:
        answer = input()
    except EOFError:
        return False
    return answer.strip().casefold() in YES_ANSWERS


@evidence_log.approval_outcome
def approve(ctx: Context, pipelines: list[Pipeline], query: str, at: dt.datetime | None = None,
            step: str | None = None, confirm: bool = False) -> Report:
    """Write approval fields, then consume only this subject's named approval keys.

    With confirm and no fresh mark, the person at the terminal is asked instead; there is no
    mark to consume then. Without a terminal confirm changes nothing.
    """
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
    if mark and mark.get("package"):
        return refusal(ctx, keys.APPROVE_PACKAGE_ERROR, reason="apply the exact prepared package")
    marked = is_fresh(mark, ctx.config.approval_window, at)
    if not marked and not (confirm and at_terminal()):
        return refusal(ctx, keys.APPROVE_NO_MARK)
    named = mark_keys(mark) if marked else set()
    identities = {*subject.keys, subject.id}
    if named and not names_any(named, identities):
        return refusal(ctx, keys.APPROVE_FOREIGN_KEY, mark_keys=KEYS_SEPARATOR.join(sorted(named)),
                       keys=KEYS_SEPARATOR.join(sorted(subject.keys)) or subject.id)
    bind = ref.params.get(PARAM_BIND)
    # Candidates are existing subjects, which have a path; a fresh mark is a mapping.
    base = cast(Path, subject.path)
    try:
        files = bound_files(base, bind) if bind else []
        if bind and not files:
            return refusal(ctx, keys.APPROVE_NOT_READY, query=query, step=step, pending=step)
        if (marked and step is not None and bind
                and changed_after_mark(base, bind, cast("dict[str, Any]", mark))):
            return refusal(ctx, keys.APPROVE_CHANGED_AFTER_MARK, query=query, step=step)
        sha = digest(base, bind, ref.params.get(PARAM_IGNORE),
                     ref.params.get(PARAM_STRIP)) if bind else ""
    except OSError:
        return refusal(ctx, keys.APPROVE_CHANGED_AFTER_MARK, query=query, step=step)
    who = approver(ctx)
    if who is None:
        return refusal(ctx, keys.APPROVE_NO_APPROVER)
    if not marked and not confirmed(ctx, subject, step, ref, files, sha):
        return refusal(ctx, keys.APPROVE_NOT_CONFIRMED, subject=subject_label(subject))
    marker = ref.params[PARAM_MARKER]
    date = (at or now()).date().isoformat()
    path = base / ref.params[PARAM_FILE]
    write_fields(path, marker, date, who, sha)
    if marked:
        consume_mark(ctx.root, identities, mark)
    root = subject_context(ctx, subject).root
    return Report(ok=True, out=[locale.text(
        keys.APPROVE_DONE, file=path.relative_to(root).as_posix(), marker=marker, date=date,
        by=who, sha=sha[:SHA_SHOWN] or NO_SHA)])
