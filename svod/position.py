"""Position of a subject in a pipeline: entry, done, current step, violations, marks."""
from dataclasses import dataclass, field

from .gates import Status, unknown
from .pipeline import SEVERITY_BLOCK, SEVERITY_WARN, VIOLATION_SEPARATOR

FACT_STEP = "step"


@dataclass
class Outcome:
    """A gate use together with its result."""

    ref: object
    result: object

    @property
    def passed(self):
        """Whether the gate passed."""
        return self.result.passed


@dataclass
class StepState:
    """A step with the outcomes of its gates."""

    step: object
    outcomes: list

    @property
    def passed(self):
        """A step passes only when it has gates and all of them pass."""
        return bool(self.outcomes) and all(o.passed for o in self.outcomes)

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


def evaluate(ctx, ref, subject):
    """Outcome of one gate use; an unreadable file system is UNKNOWN."""
    try:
        result = ref.impl.evaluate(ctx, subject)
    except OSError as exc:
        result = unknown(str(exc))
    return Outcome(ref, result)


def applies(ref, subject):
    """Whether the gate use applies: its when attribute, if any, is truthy."""
    return not ref.when or bool(subject.attrs.get(ref.when))


def run_entries(ctx, refs, subject):
    """Outcomes of the applicable entry gates."""
    return [evaluate(ctx, ref, subject) for ref in refs if applies(ref, subject)]


def first_blocking(outcomes):
    """First block-severity entry that did not pass."""
    return next((o for o in outcomes
                 if o.ref.severity == SEVERITY_BLOCK and not o.passed), None)


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


def position(ctx, pipeline, subject):
    """Position of the subject; the single computation behind status and active.

    A subject the provider did not find gets neither order violations nor the code freeze.
    Every step passed while done did not: the pending text of done, when declared.
    """
    pos = Position(pipeline=pipeline, subject=subject)
    pos.entries = run_entries(ctx, pipeline.entry, subject)
    pos.blocked = first_blocking(pos.entries)
    pos.warnings = failed_warnings(pos.entries)
    pos.unknown = [o for o in pos.entries if o.result.status is Status.UNKNOWN]

    pos.steps = [StepState(s, [evaluate(ctx, g, subject) for g in s.gates])
                 for s in pipeline.steps]
    if subject.exists:
        pos.marks = [(s.step.id, [o for o in s.outcomes if o.ref.label]) for s in pos.steps]
        pos.marks = [(step_id, marks) for step_id, marks in pos.marks if marks]

    done = None
    if pipeline.done:
        done = evaluate(ctx, pipeline.done, subject)
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
    pos.warnings += failed_warnings(step_entries)
    pos.unknown += [o for o in step_entries if o.result.status is Status.UNKNOWN]
    step_block = first_blocking(step_entries)
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
