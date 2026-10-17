"""Position of a subject in a pipeline: entry, done, current step, violations, marks."""
from dataclasses import dataclass, field

from .gates import ArchivedGate, Status
from .pipeline import (SEVERITY_WARN, VIOLATION_SEPARATOR, Outcome, applies, evaluate,
                       first_blocking, open_step, run_entries, step_applies)

FACT_STEP = "step"


@dataclass
class StepState:
    """A step with the outcomes of its gates."""

    step: object
    outcomes: list

    @property
    def passed(self):
        """A declared gate group passes when all applicable gates pass.

        A genuinely gateless stage stays manual; a conditional-only group with no
        applicable gates is skipped, consistently with approval and code guards.
        """
        return bool(self.step.gates) and all(o.passed for o in self.outcomes)

    @property
    def first_open(self):
        """First gate that did not pass, or None."""
        return next((o for o in self.outcomes if not o.passed), None)


@dataclass
class Violation:
    """A passed step preceded by a required step that did not pass."""

    later: str
    earlier: str
    text: str | None


@dataclass
class Position:
    """Everything status and active need to say about one subject."""

    pipeline: object
    subject: object
    entries: list = field(default_factory=list)
    blocked: Outcome | None = None
    warnings: list = field(default_factory=list)
    done: Outcome | None = None
    steps: list = field(default_factory=list)
    current: StepState | None = None
    text: str | None = None
    facts: dict = field(default_factory=dict)
    text_from_entry: bool = False
    do_not_touch: dict | None = None
    frozen_by_entry: bool = False
    violations: list = field(default_factory=list)
    unknown: list = field(default_factory=list)
    marks: list = field(default_factory=list)
    current_entries: list = field(default_factory=list)
    current_blocked: Outcome | None = None
    done_outcome: Outcome | None = None


def failed_warnings(outcomes):
    """Warn-severity entries that failed; an UNKNOWN one is reported as unknown instead."""
    return [o for o in outcomes
            if o.ref.severity == SEVERITY_WARN and o.result.status is Status.FAIL]


def entry_text(outcome):
    """Text and facts of a blocking entry; none when it could not be checked."""
    if outcome.result.status is Status.UNKNOWN:
        return None, {}
    return outcome.ref.text, outcome.result.facts


def violations_of(pipeline, states):
    """Order violations among non-optional steps."""
    found = []
    for i, later in enumerate(states):
        if not later.passed:
            continue
        for earlier in states[:i]:
            if earlier.step.required and not earlier.passed:
                key = f"{later.step.id}{VIOLATION_SEPARATOR}{earlier.step.id}"
                found.append(Violation(later.step.id, earlier.step.id,
                                       pipeline.violations.get(key)))
    return found


def do_not_touch_facts(states, start):
    """Facts for the code freeze when a blocks_code step lies at or after start."""
    step = next((s for s in states[start:] if s.step.blocks_code), None)
    if step is None:
        return None
    gate = step.first_open
    return {**(gate.result.facts if gate else {}), FACT_STEP: step.step.id}


def freeze(ctx, pipeline, subject):
    """What keeps the code frozen: the first applicable blocks_code step that has not passed.

    Returns an OpenStep (step, text key, facts, and gate and reason for an UNKNOWN gate) or
    None. A step without gates is open with its own text; an UNKNOWN gate is open. Unlike
    the status line, a passed blocks_code step never freezes, whatever precedes it. Pass
    the context of the subject's own checkout.
    """
    for step in pipeline.steps:
        if step.blocks_code and step_applies(step, subject):
            found = open_step(ctx, step, subject)
            if found is not None:
                return found
    return None


def position(ctx, pipeline, subject):
    """Position of the subject; the single computation behind status and active.

    A subject the provider did not find gets neither order violations nor the code freeze.
    Every step passed while done did not: the pending text of done, when declared.
    """
    pos = Position(pipeline=pipeline, subject=subject)
    done = None
    if subject.archived and pipeline.done and isinstance(pipeline.done.impl, ArchivedGate):
        # Archive presentation is history, not evidence of live checks or delivery.
        done = evaluate(ctx, pipeline.done, subject)
        pos.done_outcome = done
        if done.passed:
            pos.done = done
            pos.text, pos.facts = done.ref.text, done.result.facts
            return pos

    pos.entries = run_entries(ctx, pipeline.entry, subject)
    pos.blocked = first_blocking(pos.entries)
    pos.warnings = failed_warnings(pos.entries)
    pos.unknown = [o for o in pos.entries if o.result.status is Status.UNKNOWN]

    pos.steps = [StepState(s, [evaluate(ctx, g, subject) for g in s.gates
                              if applies(g, subject)])
                 for s in pipeline.steps if step_applies(s, subject)]
    if subject.exists:
        pos.marks = [(s.step.id, [o for o in s.outcomes if o.ref.label]) for s in pos.steps]
        pos.marks = [(step_id, marks) for step_id, marks in pos.marks if marks]

    if pipeline.done:
        if done is None:
            done = evaluate(ctx, pipeline.done, subject)
        pos.done_outcome = done
        if done.passed:
            pos.done = done
            pos.text, pos.facts = done.ref.text, done.result.facts
            return pos
        if done.result.status is Status.UNKNOWN:
            pos.unknown.append(done)

    states = [s for s in pos.steps if not s.step.optional]
    pos.unknown += [o for s in states for o in s.outcomes if o.result.status is Status.UNKNOWN]
    if subject.exists:
        pos.violations = violations_of(pipeline, states)

    if pos.blocked:
        pos.text, pos.facts = entry_text(pos.blocked)
        pos.text_from_entry = True
        if subject.exists:
            pos.do_not_touch = do_not_touch_facts(states, 0)
        pos.frozen_by_entry = pos.do_not_touch is not None
        return pos

    index = next((i for i, s in enumerate(states) if not s.passed), None)
    if index is None:
        if done is not None and done.ref.pending:
            pos.text, pos.facts = done.ref.pending, done.result.facts
        return pos
    pos.current = states[index]
    step_entries = run_entries(ctx, pos.current.step.entry, subject)
    pos.current_entries = step_entries
    pos.warnings += failed_warnings(step_entries)
    pos.unknown += [o for o in step_entries if o.result.status is Status.UNKNOWN]
    step_block = first_blocking(step_entries)
    pos.current_blocked = step_block
    gate = pos.current.first_open
    if step_block:
        pos.text, pos.facts = entry_text(step_block)
        pos.text_from_entry = True
    elif gate and gate.ref.text:
        pos.text, pos.facts = gate.ref.text, gate.result.facts
    else:
        pos.text, pos.facts = pos.current.step.text, gate.result.facts if gate else {}
    if subject.exists:
        pos.do_not_touch = do_not_touch_facts(states, index)
    return pos
