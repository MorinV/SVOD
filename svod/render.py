"""Text output of the status command."""
from dataclasses import dataclass, field

from . import keys
from .bindings import resolve_role
from .gates import Status
from .position import evaluate

INDENT = "  "
MARK_SEPARATOR = "   "
KEYS_SEPARATOR = ", "
SKILLS_SEPARATOR = ", "
FACT_ID = "id"
FACT_KEYS = "keys"
FACT_PIPELINE = "pipeline"
FACT_REASON = "reason"
VARIANT_SEPARATOR = "_"
MARK_KEYS = {Status.PASS: keys.MARK_PASS, Status.FAIL: keys.MARK_FAIL,
             Status.UNKNOWN: keys.MARK_UNKNOWN}


@dataclass
class Report:
    """Rendered output of a command, its exit status and whether a failure is a refusal."""

    ok: bool
    out: list = field(default_factory=list)
    err: list = field(default_factory=list)
    refused: bool = False


def subject_facts_of(pipeline, subject):
    """Facts describing a subject of a pipeline."""
    return {FACT_ID: subject.id, FACT_KEYS: KEYS_SEPARATOR.join(sorted(subject.keys)),
            FACT_PIPELINE: pipeline.name}


def subject_facts(pos):
    """Facts describing the subject for headers and summary lines."""
    return subject_facts_of(pos.pipeline, pos.subject)


def mark_text(locale, outcome):
    """Mark of a labelled gate: its display, or the standard status and label."""
    if outcome.result.display:
        return outcome.result.display
    label = locale.text(outcome.ref.label, **outcome.result.facts)
    return locale.text(MARK_KEYS[outcome.result.status], label=label)


def text_key(locale, key, facts):
    """The variant <key>_<reason> when the facts carry a reason and the locale has it, else key."""
    reason = facts.get(FACT_REASON)
    if isinstance(reason, str):
        variant = f"{key}{VARIANT_SEPARATOR}{reason}"
        if locale.has(variant):
            return variant
    return key


def gate_text(locale, key, facts):
    """A gate or step text rendered with the facts, in the variant of their reason."""
    return locale.text(text_key(locale, key, facts), **facts)


def step_text(locale, pos):
    """The next-step text of a position, or None when there is none."""
    if not pos.text:
        return None
    return gate_text(locale, pos.text, pos.facts)


def violation_text(locale, violation):
    """Override text of a violation, or the general template with step ids."""
    if violation.text:
        return locale.text(violation.text)
    return locale.text(keys.STATUS_VIOLATION, later=violation.later, earlier=violation.earlier)


def step_skills(ctx, pos):
    """Skill bindings of the current step's role; None without a role, bindings or a next step.

    A step held by its own blocking entry has no next step to take, so no skill is offered.
    """
    if ctx.bindings is None or pos.current is None or not pos.current.step.role:
        return None
    if pos.text_from_entry:
        return None
    return resolve_role(ctx, ctx.bindings, pos.current.step.role, pos.subject)


def skill_line(locale, role, skills):
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


def render_position(locale, pos, skills=None):
    """Lines of the status block for one position; skills of the current step when resolved."""
    header = pos.pipeline.header or keys.STATUS_HEADER
    lines = [locale.text(header, **subject_facts(pos))]
    if pos.subject.checkout is not None:
        lines.append(INDENT + locale.text(keys.STATUS_CHECKOUT, dir=pos.subject.checkout.name))
    for _, outcomes in pos.marks:
        lines.append(INDENT + MARK_SEPARATOR.join(mark_text(locale, o) for o in outcomes))
    text = step_text(locale, pos)
    body = []
    if text:
        body.append(text if pos.text_from_entry
                    else locale.text(keys.STATUS_NEXT_STEP, step=text))
    if skills:
        body.append(skill_line(locale, pos.current.step.role, skills))
    if pos.do_not_touch is not None:
        freeze = (keys.STATUS_DO_NOT_TOUCH_BLOCKED if pos.frozen_by_entry
                  else keys.STATUS_DO_NOT_TOUCH)
        body.append(locale.text(freeze, **pos.do_not_touch))
    unknown_lines = [locale.text(keys.STATUS_UNKNOWN, reason=outcome.result.reason,
                                 gate=outcome.ref.gate) for outcome in pos.unknown]
    body += list(dict.fromkeys(unknown_lines))
    for outcome in pos.warnings:
        body.append(gate_text(locale, outcome.ref.text, outcome.result.facts))
    if body:
        lines.append("")
        lines += [INDENT + line for line in body]
    if pos.violations:
        lines.append(INDENT + locale.text(keys.STATUS_VIOLATIONS))
        lines += [INDENT * 2 + locale.text(keys.STATUS_VIOLATION_ITEM,
                                           text=violation_text(locale, v))
                  for v in pos.violations]
    return lines


def missing_text(ctx, pipeline, subject):
    """Text of the missing gate when the subject was not found and nothing else is known of it.

    None for a found subject, a pipeline without a missing gate, or a gate that did not fail.
    """
    ref = pipeline.missing
    if subject.exists or ref is None:
        return None
    outcome = evaluate(ctx, ref, subject)
    if outcome.result.status is not Status.FAIL:
        return None
    return ctx.locale.text(ref.text, **{**subject_facts_of(pipeline, subject),
                                        **outcome.result.facts})


def status_report(ctx, pipelines, query):
    """Status of every subject the query resolves to.

    Missing subjects nothing is known about are errors, reported only when no position is shown:
    another pipeline presenting the query is the answer.
    """
    from .status import collect_status

    return collect_status(ctx, pipelines, query).report
