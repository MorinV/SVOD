"""Text output of the status command."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import keys
from .bindings import resolve_role
from .gates import Status

if TYPE_CHECKING:
    from .context import Context
    from .locale import Locale
    from .pipeline import Outcome, Pipeline
    from .position import Position, StepState, Violation
    from .subject import Subject

Skills = list[tuple[str, Any]]

INDENT = "  "
MARK_SEPARATOR = "   "
KEYS_SEPARATOR = ", "
SKILLS_SEPARATOR = ", "
FACT_ID = "id"
FACT_KEYS = "keys"
FACT_PIPELINE = "pipeline"
FACT_REASON = "reason"
VARIANT_SEPARATOR = "_"
ELLIPSIS = "..."
MARK_KEYS = {Status.PASS: keys.MARK_PASS, Status.FAIL: keys.MARK_FAIL,
             Status.UNKNOWN: keys.MARK_UNKNOWN}


@dataclass
class Report:
    """Rendered output of a command, its exit status and whether a failure is a refusal."""

    ok: bool
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)
    refused: bool = False


def subject_facts_of(pipeline: Pipeline, subject: Subject) -> dict[str, str]:
    """Facts describing a subject of a pipeline."""
    return {FACT_ID: subject.id, FACT_KEYS: KEYS_SEPARATOR.join(sorted(subject.keys)),
            FACT_PIPELINE: pipeline.name}


def subject_facts(pos: Position) -> dict[str, str]:
    """Facts describing the subject for headers and summary lines."""
    return subject_facts_of(pos.pipeline, pos.subject)


def mark_text(locale: Locale, outcome: Outcome) -> str:
    """Mark of a labelled gate: its display, or the standard status and label."""
    if outcome.result.display:
        return outcome.result.display
    label = locale.text(outcome.ref.label, **outcome.result.facts)
    return locale.text(MARK_KEYS[outcome.result.status], label=label)


def text_key(locale: Locale, key: str, facts: dict[str, Any]) -> str:
    """The variant <key>_<reason> when the facts carry a reason and the locale has it, else key."""
    reason = facts.get(FACT_REASON)
    if isinstance(reason, str):
        variant = f"{key}{VARIANT_SEPARATOR}{reason}"
        if locale.has(variant):
            return variant
    return key


def gate_text(locale: Locale, key: str, facts: dict[str, Any]) -> str:
    """A gate or step text rendered with the facts, in the variant of their reason."""
    return locale.text(text_key(locale, key, facts), **facts)


def step_text(locale: Locale, pos: Position) -> str | None:
    """The next-step text of a position, or None when there is none."""
    if not pos.text:
        return None
    return gate_text(locale, pos.text, pos.facts)


def violation_text(locale: Locale, violation: Violation) -> str:
    """Override text of a violation, or the general template with step ids."""
    if violation.text:
        return locale.text(violation.text)
    return locale.text(keys.STATUS_VIOLATION, later=violation.later, earlier=violation.earlier)


def step_skills(ctx: Context, pos: Position) -> Skills | None:
    """Skill bindings of the current step's role; None without a role, bindings or a next step.

    A step held by its own blocking entry has no next step to take, so no skill is offered.
    """
    if ctx.bindings is None or pos.current is None or not pos.current.step.role:
        return None
    if pos.text_from_entry:
        return None
    return resolve_role(ctx, ctx.bindings, pos.current.step.role, pos.subject)


def run_line(locale: Locale, pos: Position) -> str | None:
    """The command running the action of the current step, or None when it declares none.

    A step held by its own blocking entry has no next step to take, and a subject that does not
    exist has nothing to run for, so no action is offered then.
    """
    if pos.current is None or not pos.current.step.action or pos.text_from_entry \
            or not pos.subject.exists:
        return None
    return locale.text(keys.STATUS_RUN, action=pos.current.step.action,
                       query=shlex.quote(pos.subject.id))


def skill_line(locale: Locale, role: str | None, skills: Skills) -> str:
    """One skill for every directory, a skill per directory, or not assigned."""
    distinct = {skill for _, skill in skills}
    if distinct == {None}:
        return locale.text(keys.STATUS_SKILL_UNASSIGNED, role=role)
    if len(distinct) == 1:
        return locale.text(keys.STATUS_SKILL, skill=distinct.pop())
    none = locale.text(keys.STATUS_SKILL_NONE)
    items = list(dict.fromkeys(skills))
    return locale.text(keys.STATUS_SKILL, skill=SKILLS_SEPARATOR.join(
        locale.text(keys.STATUS_SKILL_ITEM, dir=label, skill=skill or none)
        for label, skill in items))


def step_status(state: StepState) -> Status:
    """Status of a step as one mark: PASS when passed, UNKNOWN when a gate could not be checked."""
    if state.passed:
        return Status.PASS
    if any(o.result.status is Status.UNKNOWN for o in state.outcomes):
        return Status.UNKNOWN
    return Status.FAIL


def step_mark_text(locale: Locale, state: StepState) -> str:
    """Mark of a step without labelled gates: its title when declared, else its id."""
    label = locale.text(state.step.title) if state.step.title else state.step.id
    return locale.text(MARK_KEYS[step_status(state)], label=label)


def mark_lines(locale: Locale, pos: Position) -> list[str]:
    """One line of marks per step: its labelled gates, or the step itself when none is labelled."""
    if not pos.subject.exists:
        return []
    labelled = dict(pos.marks)
    lines = []
    for state in pos.steps:
        outcomes = labelled.get(state.step.id)
        if outcomes:
            lines.append(MARK_SEPARATOR.join(mark_text(locale, o) for o in outcomes))
        else:
            lines.append(step_mark_text(locale, state))
    return lines


def sentence(text: str) -> str:
    """The text without its final period, for a template that ends the sentence itself."""
    return text[:-1] if text.endswith(".") and not text.endswith(ELLIPSIS) else text


def render_position(locale: Locale, pos: Position, skills: Skills | None = None,
                    autonomy: str | None = None) -> list[str]:
    """Lines of the status block for one position; skills of the current step when resolved.

    autonomy: the level of the pipeline from svod.yaml, printed under the header when set.
    """
    header = pos.pipeline.header or keys.STATUS_HEADER
    lines = [locale.text(header, **subject_facts(pos))]
    if autonomy:
        lines.append(INDENT + locale.text(keys.STATUS_AUTONOMY, level=autonomy))
    if pos.subject.checkout is not None:
        lines.append(INDENT + locale.text(keys.STATUS_CHECKOUT, dir=pos.subject.checkout.name))
    lines += [INDENT + line for line in mark_lines(locale, pos)]
    text = step_text(locale, pos)
    body = []
    if text:
        body.append(text if pos.text_from_entry
                    else locale.text(keys.STATUS_NEXT_STEP, step=sentence(text)))
    if skills:
        # Skills come from step_skills, which offers them only with a current step.
        body.append(skill_line(locale, pos.current.step.role, skills))  # type: ignore[union-attr]
    run = run_line(locale, pos)
    if run:
        body.append(run)
    if pos.do_not_touch is not None:
        freeze = (keys.STATUS_DO_NOT_TOUCH_BLOCKED if pos.frozen_by_entry
                  else keys.STATUS_DO_NOT_TOUCH)
        body.append(locale.text(freeze, **pos.do_not_touch))
    unknown_lines = [locale.text(keys.STATUS_UNKNOWN, reason=outcome.result.reason,
                                 gate=outcome.ref.gate) for outcome in pos.unknown]
    body += list(dict.fromkeys(unknown_lines))
    for outcome in pos.warnings:
        # The schema requires a text on every entry gate, and warnings are entry outcomes.
        body.append(gate_text(locale, outcome.ref.text, outcome.result.facts))  # type: ignore[arg-type]
    if body:
        lines.append("")
        lines += [INDENT + line for line in body]
    if pos.violations:
        lines.append(INDENT + locale.text(keys.STATUS_VIOLATIONS))
        lines += [INDENT * 2 + locale.text(keys.STATUS_VIOLATION_ITEM,
                                           text=violation_text(locale, v))
                  for v in pos.violations]
    return lines


def status_report(ctx: Context, pipelines: list[Pipeline], query: str) -> Report:
    """Status of every subject the query resolves to.

    Missing subjects nothing is known about are errors, reported only when no position is shown:
    another pipeline presenting the query is the answer.
    """
    from .status import collect_status

    return collect_status(ctx, pipelines, query).report
