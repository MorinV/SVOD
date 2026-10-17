"""Retrospective rules: what the evidence log and the relations of works say about the profile.

A rule is a class with a name and evaluate(ctx, subject, log, graph) returning proposals. It
only reads: the log of the subject and of the other works of its pipeline, and the graph of
relations. Each rule has a default threshold, `threshold` of its class; svod.yaml overrides it
with retro.thresholds.<rule>, and 0 turns the rule off. Every comparison with the threshold is
kept as an observation for `svod retro --explain`.
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import evidence_log as ev
from ..bindings import SKILL_PLACEHOLDER
from ..document import relative_or_absolute
from ..params import Configurable
from ..subject import ATTR_FRONTMATTER

if TYPE_CHECKING:
    from ..context import Context
    from ..pipeline import Pipeline
    from ..subject import Subject
    from .engine import Graph, Log

SCOPE_SUBJECT = "subject"
SCOPE_PIPELINE = "pipeline"
TEXT_PREFIX = "retro.rule."
CHANGE_PREFIX = "retro.change."
QUESTIONS_SUFFIX = "_questions"

CHANGE_FILE = "file"
CHANGE_KIND = "kind"
CHANGE_TEXT = "text"
CHANGE_ANCHOR = "anchor"
KIND_NOTE = "note"
KIND_LINE = "line"
ANCHOR_STEP = "steps: {step}"

# dirty_checks: failed checks on a dirty source tree, at least this many in one work.
DIRTY_MIN = 2
# Thresholds of the other rules: approval_drift DRIFT_MIN, hook_denials DENIALS_MIN, hotfix_cause
# HOTFIX_MIN, instant_steps INSTANT_WORKS, long_step LONG_WORKS. Seconds and shares are fixed.
DIRTY_WORD = "dirty"
DIRTY_CODE = "dirty_tree"
GITIGNORE = ".gitignore"
GITIGNORE_LINE = "__pycache__/"
# approval_drift: refusals because the plan changed after the answer, on one step of one work.
DRIFT_MIN = 2
QUESTIONS_GATE = "questions_answered"
QUESTIONS_ROLE = "questions"
# hook_denials: refusals by one rule of the pre-tool hook in one work.
DENIALS_MIN = 3
# hotfix_cause: hotfixes whose cause is one and the same work.
HOTFIX_MIN = 2
HOTFIX_CODE = "weak_decision"
FIELD_KIND = "kind"
FIELD_CAUSE = "cause"
KIND_HOTFIX = "hotfix"
KNOWLEDGE_SUFFIX = ".md"
# instant_steps: a step current for less than this many seconds in each of the last works.
INSTANT_SECONDS = 60
INSTANT_WORKS = 3
OPTIONAL_LINE = "optional: true"
# long_step: one step takes more than this share of the time of a work, in this many works.
LONG_SHARE = 0.5
LONG_WORKS = 3
PERCENT = 100

EVENT_FACT_RULE = "rule"
FACT_COUNT = "count"
FACT_STEP = "step"
FACT_PIPELINE = "pipeline"
FACT_WORK = "work"
FACT_WORKS = "works"
FACT_HOTFIXES = "hotfixes"
FACT_HOOK_RULE = "hook_rule"
FACT_RUNS = "runs"
FACT_SECONDS = "seconds"
FACT_SHARE = "share"
FACT_PASSED = "passed"
FACT_LIMIT_SECONDS = "limit_seconds"
FACT_LIMIT_SHARE = "limit_share"
NO_STEP = "-"
IDS_SEPARATOR = ", "


@dataclass
class Proposal:
    """One proposed change of the profile with the facts behind it.

    `code` tells proposals of one rule apart (a step id, a hook rule); `subject` is what a
    decision is about: the work, or the pipeline for a rule over a pipeline; the engine fills it
    when the rule leaves it None. `change` is a hint, never applied: `file` relative to the
    store root, `kind` (`note` or `line`), `text` (a locale key or the text itself) and an
    optional `anchor` naming the place in the file.
    """

    rule: str
    code: str
    facts: dict[str, Any]
    text_key: str
    change: dict[str, Any] | None = None
    subject: str | None = None


@dataclass
class Observation:
    """What a rule compared with its threshold, fired or not: the facts behind `--explain`.

    `value` is the number compared; `threshold` is None for a rule without one; `subject` is
    filled by the engine like that of a proposal when the rule leaves it None.
    """

    rule: str
    code: str
    facts: dict[str, Any]
    value: float
    threshold: int | None
    fired: bool
    subject: str | None = None


class Rule(Configurable):
    """A retrospective rule: evaluate(ctx, subject, log, graph) returns proposals.

    `threshold` is the default of the rule; the engine sets the one of svod.yaml on the
    instance. `observed` collects what reaches() compared during one evaluate.
    """

    scope = SCOPE_SUBJECT
    threshold: int | None = None

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        """Params as for any configurable; nothing observed yet."""
        super().__init__(params)
        self.observed: list[Observation] = []

    def reaches(self, code: str, value: float, facts: dict[str, Any], also: bool = True,
                subject: str | None = None) -> bool:
        """Whether the value reaches the threshold and the other condition holds; kept as seen.

        A threshold of 0 turns the rule off: nothing reaches it. Without a threshold only the
        other condition decides.
        """
        threshold = self.threshold
        fired = also and (threshold is None or (threshold > 0 and value >= threshold))
        self.observed.append(Observation(self.name, code, dict(facts), value, threshold, fired,
                                         subject))
        return fired

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """Proposals for the subject; an empty list when the evidence says nothing."""
        raise NotImplementedError

    def propose(self, code: str, facts: dict[str, Any], change: dict[str, Any] | None = None,
                subject: str | None = None, text_key: str | None = None) -> Proposal:
        """Proposal of this rule; the text key is retro.rule.<name> unless given."""
        return Proposal(self.name, code, facts, text_key or TEXT_PREFIX + self.name, change,
                        subject)


def change(file: str, text: str, kind: str = KIND_NOTE,
           anchor: str | None = None) -> dict[str, Any]:
    """Description of a change of one file; the anchor is left out when None."""
    found: dict[str, Any] = {CHANGE_FILE: file, CHANGE_KIND: kind, CHANGE_TEXT: text}
    if anchor:
        found[CHANGE_ANCHOR] = anchor
    return found


def facts_of(entry: dict[str, Any]) -> dict[str, Any]:
    """Facts of a log entry."""
    facts = entry.get(ev.FIELD_FACTS)
    return facts if isinstance(facts, dict) else {}


def of_event(entries: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    """Entries of one event code, in order."""
    return [entry for entry in entries if entry.get(ev.FIELD_EVENT) == event]


def moment(entry: dict[str, Any]) -> dt.datetime | None:
    """Time of a log entry, or None when it does not read as an ISO time with an offset."""
    try:
        found = dt.datetime.fromisoformat(str(entry.get(ev.FIELD_AT)))
    except ValueError:
        return None
    return found if found.tzinfo is not None else None


def step_at(entries: list[dict[str, Any]], index: int) -> str | None:
    """Step of the entry at the index: its own, else the current step of the last move before."""
    own = entries[index].get(ev.FIELD_STEP)
    if own:
        return str(own)
    for entry in reversed(entries[:index]):
        if entry.get(ev.FIELD_EVENT) == ev.EVENT_POSITION_CHANGED:
            to = facts_of(entry).get(ev.FACT_TO)
            return str(to) if to else None
    return None


def durations(entries: list[dict[str, Any]]) -> dict[str, float]:
    """Seconds each step was current: from a move onto it to the next move.

    The step current at the end counts up to the last entry of the log; a move without a time
    is left out.
    """
    moves = [(entry, at) for entry in of_event(entries, ev.EVENT_POSITION_CHANGED)
             if (at := moment(entry)) is not None]
    times = [at for at in map(moment, entries) if at is not None]
    found: dict[str, float] = {}
    for i, (entry, start) in enumerate(moves):
        step = facts_of(entry).get(ev.FACT_TO)
        end = moves[i + 1][1] if i + 1 < len(moves) else max(times)
        if step:
            found[str(step)] = found.get(str(step), 0.0) + max((end - start).total_seconds(), 0.0)
    return found


def passed_steps(entries: list[dict[str, Any]]) -> set[str]:
    """Ids of the steps the log saw pass."""
    return {str(entry[ev.FIELD_STEP]) for entry in of_event(entries, ev.EVENT_STEP_PASSED)
            if entry.get(ev.FIELD_STEP)}


def current_steps(entries: list[dict[str, Any]]) -> set[str]:
    """Ids of the steps the log saw current."""
    return {str(facts_of(entry)[ev.FACT_TO])
            for entry in of_event(entries, ev.EVENT_POSITION_CHANGED)
            if facts_of(entry).get(ev.FACT_TO)}


def pipeline_file(ctx: Context, pipeline: Pipeline) -> str:
    """File of the pipeline declaration, relative to the store root."""
    return str(relative_or_absolute(ctx.root, pipeline.source))


def skill_file(ctx: Context, pipeline: Pipeline, step_id: str | None) -> str:
    """File of the first skill bound to the role of the step; the pipeline file without one."""
    step = next((s for s in pipeline.steps if s.id == step_id), None)
    bindings = ctx.bindings
    if step is None or not step.role or bindings is None or not bindings.skill_path:
        return pipeline_file(ctx, pipeline)
    skill = next((r.skill for r in bindings.roles.get(step.role, []) if r.skill), None)
    if skill is None:
        return pipeline_file(ctx, pipeline)
    return str(bindings.skill_path.replace(SKILL_PLACEHOLDER, skill))


def frontmatter_text(subject: Subject, name: str) -> str:
    """Stripped string value of a frontmatter field of the subject, empty when absent."""
    value = (subject.attrs.get(ATTR_FRONTMATTER) or {}).get(name)
    return "" if value is None else str(value).strip()


def is_dirty(entry: dict[str, Any]) -> bool:
    """Whether a checks_run failed on a dirty source tree.

    A reason fact naming the dirty tree says so; without one, a failed run whose command
    exited with 0 was refused by the source check (a dirty tree, or one the command changed).
    """
    facts = facts_of(entry)
    if facts.get(ev.FACT_PASSED) is not False:
        return False
    reason = facts.get(ev.FACT_REASON)
    if reason:
        return DIRTY_WORD in str(reason)
    return facts.get(ev.FACT_CODE) == 0


class DirtyChecksRule(Rule):
    """Checks failed again and again on a dirty tree: ignore what they write."""

    name = "dirty_checks"
    threshold = DIRTY_MIN

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """One proposal when at least the threshold of runs failed on a dirty tree."""
        runs = of_event(log.entries, ev.EVENT_CHECKS_RUN)
        count = sum(1 for entry in runs if is_dirty(entry))
        if not self.reaches(DIRTY_CODE, count, {FACT_COUNT: count, FACT_RUNS: len(runs)}):
            return []
        return [self.propose(DIRTY_CODE, {FACT_COUNT: count, FACT_RUNS: len(runs)},
                             change(GITIGNORE, GITIGNORE_LINE, KIND_LINE))]


def questions_step(pipeline: Pipeline, step_id: str | None) -> bool:
    """Whether the step asks questions: a questions_answered gate or the questions role."""
    step = next((s for s in pipeline.steps if s.id == step_id), None)
    return step is not None and (step.role == QUESTIONS_ROLE
                                 or any(ref.gate == QUESTIONS_GATE for ref in step.gates))


class ApprovalDriftRule(Rule):
    """The contract changed after the answer again and again: split it or ask earlier."""

    name = "approval_drift"
    threshold = DRIFT_MIN
    APPROVALS = frozenset({ev.EVENT_APPROVAL_RECORDED, ev.EVENT_APPROVAL_DRIFT})
    MOVES = frozenset({ev.EVENT_POSITION_CHANGED, ev.EVENT_STEP_PASSED})

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """One proposal per step with at least the threshold of drifts; 0 seen without any.

        The variant asking the questions before the contract is chosen when a questions step
        was current or passed after the first approval event of the step.
        """
        entries = log.entries
        drifts = Counter(str(entry[ev.FIELD_STEP])
                         for entry in of_event(entries, ev.EVENT_APPROVAL_DRIFT)
                         if entry.get(ev.FIELD_STEP))
        if not drifts:
            self.reaches(NO_STEP, 0, {FACT_COUNT: 0})
        found = []
        for step, count in sorted(drifts.items()):
            if not self.reaches(step, count, {FACT_STEP: step, FACT_COUNT: count}):
                continue
            first = next(i for i, entry in enumerate(entries)
                         if entry.get(ev.FIELD_EVENT) in self.APPROVALS
                         and entry.get(ev.FIELD_STEP) == step)
            later = any(entry.get(ev.FIELD_EVENT) in self.MOVES
                        and questions_step(log.pipeline, step_at(entries, i))
                        for i, entry in enumerate(entries) if i > first)
            suffix = QUESTIONS_SUFFIX if later else ""
            found.append(self.propose(
                step, {FACT_STEP: step, FACT_COUNT: count},
                change(skill_file(ctx, log.pipeline, step), CHANGE_PREFIX + self.name + suffix),
                text_key=TEXT_PREFIX + self.name + suffix))
        return found


class HookDenialsRule(Rule):
    """The hook refused by one rule again and again: the skill of the step is not clear."""

    name = "hook_denials"
    threshold = DENIALS_MIN

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """One proposal per hook rule refusing at least the threshold of times in the work.

        The step is the one most of those refusals happened at; the change names its skill.
        """
        entries = log.entries
        steps: dict[str, Counter[str]] = {}
        for i, entry in enumerate(entries):
            rule = facts_of(entry).get(EVENT_FACT_RULE)
            if entry.get(ev.FIELD_EVENT) == ev.EVENT_HOOK_DENIED and rule:
                steps.setdefault(str(rule), Counter())[step_at(entries, i) or NO_STEP] += 1
        if not steps:
            self.reaches(NO_STEP, 0, {FACT_COUNT: 0})
        found = []
        for rule, counter in sorted(steps.items()):
            count = sum(counter.values())
            step = counter.most_common(1)[0][0]
            if not self.reaches(rule, count, {FACT_HOOK_RULE: rule, FACT_COUNT: count,
                                              FACT_STEP: step}):
                continue
            target = skill_file(ctx, log.pipeline, None if step == NO_STEP else step)
            found.append(self.propose(rule, {FACT_HOOK_RULE: rule, FACT_COUNT: count,
                                             FACT_STEP: step},
                                      change(target, CHANGE_PREFIX + self.name)))
        return found


def is_hotfix(subject: Subject) -> bool:
    """Whether the work is a hotfix by its frontmatter kind."""
    return frontmatter_text(subject, FIELD_KIND) == KIND_HOTFIX


class HotfixCauseRule(Rule):
    """Several hotfixes name one work as their cause: the decision there was weak."""

    name = "hotfix_cause"
    threshold = HOTFIX_MIN

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """A proposal about the subject, or about the cause of a hotfix subject.

        The work must be a subject of the store with at least the threshold of hotfixes naming
        it; the decision is about that work.
        """
        targets = {subject.id}
        cause = graph.target(subject.id, FIELD_CAUSE)
        if is_hotfix(subject) and cause:
            targets.add(cause)
        found = []
        for work in sorted(targets):
            hotfixes = sorted(s.id for _, s in graph.pointing(FIELD_CAUSE, work) if is_hotfix(s))
            if not self.reaches(HOTFIX_CODE, len(hotfixes),
                                {FACT_WORK: work, FACT_COUNT: len(hotfixes)},
                                also=work in graph.nodes, subject=work):
                continue
            note = f"{ctx.config.knowledge_dir}/{Path(work).name}{KNOWLEDGE_SUFFIX}"
            found.append(self.propose(
                HOTFIX_CODE, {FACT_WORK: work, FACT_COUNT: len(hotfixes),
                              FACT_HOTFIXES: IDS_SEPARATOR.join(hotfixes)},
                change(note, CHANGE_PREFIX + self.name), subject=work))
        return found


class InstantStepsRule(Rule):
    """A step passes at once in every recent work of the pipeline: make it optional."""

    name = "instant_steps"
    scope = SCOPE_PIPELINE
    threshold = INSTANT_WORKS

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """One proposal per step that is not optional yet (as declared or by autonomy).

        The works are the last ones of the pipeline, as many as the threshold, whose log saw
        the step current or passed; in each it passed and was current for less than
        INSTANT_SECONDS, or never.
        """
        works = log.works()
        size = self.threshold or 0
        found = []
        for step in log.pipeline.steps:
            if step.optional:
                continue
            seen = [entries for entries in works
                    if step.id in passed_steps(entries) | current_steps(entries)]
            recent = seen[-size:] if size else []
            seconds = [durations(entries).get(step.id, 0.0) for entries in recent]
            passed = sum(1 for entries in recent if step.id in passed_steps(entries))
            longest = round(max(seconds, default=0.0))
            facts = {FACT_STEP: step.id, FACT_COUNT: len(recent), FACT_PASSED: passed,
                     FACT_SECONDS: longest, FACT_LIMIT_SECONDS: INSTANT_SECONDS}
            also = bool(recent) and passed == len(recent) and max(seconds) < INSTANT_SECONDS
            if self.reaches(step.id, len(recent), facts, also=also):
                found.append(self.propose(
                    step.id, {FACT_PIPELINE: log.pipeline.name, FACT_STEP: step.id,
                              FACT_COUNT: len(recent), FACT_SECONDS: longest},
                    change(pipeline_file(ctx, log.pipeline), OPTIONAL_LINE, KIND_LINE,
                           ANCHOR_STEP.format(step=step.id))))
        return found


class LongStepRule(Rule):
    """One step takes most of the time of many works: split it or give it an action."""

    name = "long_step"
    scope = SCOPE_PIPELINE
    threshold = LONG_WORKS

    def evaluate(self, ctx: Context, subject: Subject, log: Log,
                 graph: Graph) -> list[Proposal]:
        """One proposal per step longer than LONG_SHARE of the work in the threshold of works.

        A pipeline whose works have no such step is seen as one count of 0.
        """
        works = log.works()
        shares: dict[str, list[float]] = {}
        for entries in works:
            spent = durations(entries)
            total = sum(spent.values())
            if total <= 0:
                continue
            step, seconds = max(spent.items(), key=lambda item: item[1])
            if seconds / total > LONG_SHARE:
                shares.setdefault(step, []).append(seconds / total)
        if not shares:
            self.reaches(NO_STEP, 0, {FACT_COUNT: 0, FACT_WORKS: len(works),
                                      FACT_LIMIT_SHARE: round(LONG_SHARE * PERCENT)})
        found = []
        for step, values in sorted(shares.items()):
            if not self.reaches(step, len(values), {
                    FACT_STEP: step, FACT_COUNT: len(values), FACT_WORKS: len(works),
                    FACT_SHARE: round(min(values) * PERCENT),
                    FACT_LIMIT_SHARE: round(LONG_SHARE * PERCENT)}):
                continue
            found.append(self.propose(
                step, {FACT_PIPELINE: log.pipeline.name, FACT_STEP: step,
                       FACT_COUNT: len(values), FACT_WORKS: len(works),
                       FACT_SHARE: round(min(values) * PERCENT)},
                change(pipeline_file(ctx, log.pipeline), CHANGE_PREFIX + self.name,
                       anchor=ANCHOR_STEP.format(step=step))))
        return found


RULES: dict[str, type[Rule]] = {cls.name: cls for cls in (
    DirtyChecksRule, ApprovalDriftRule, HookDenialsRule, HotfixCauseRule, InstantStepsRule,
    LongStepRule,
)}
