"""Retrospective engine: the graph of relations, the log reader, the profile rules, the review.

The graph is built once per run from the subjects of every pipeline of ctx.pipelines by their
frontmatter fields parent, cause and leads_to. The logs are read once per run and file. Rules of
the profile live in <profile>/retro/*.py as RULES = {name: class}, loaded like the gate modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import evidence_log as ev
from ..errors import LoadError
from ..gates import (GATES_GLOB, PRIVATE_PREFIX, load_module, pipeline_subjects, registered,
                     relation_field)
from .rules import (CHANGE_ANCHOR, CHANGE_FILE, CHANGE_KIND, CHANGE_TEXT, RULES,
                    SCOPE_PIPELINE, Observation, Proposal, Rule, moment)

if TYPE_CHECKING:
    from ..context import Context
    from ..locale import Locale
    from ..pipeline import Pipeline
    from ..subject import Subject

RELATION_FIELDS = ("parent", "cause", "leads_to")
GRAPH_KEY = "retro_graph"
RETRO_DIR = "retro"
RULES_ATTR = "RULES"
LOG_GLOB = "*" + ev.LOG_SUFFIX
FACT_PAIR = "{name}={value}"
FACTS_SEPARATOR = ", "
DIFF_OLD = "--- a/{file}"
DIFF_NEW = "+++ b/{file}"
DIFF_HUNK = "@@ {anchor} @@"
DIFF_ADD = "+{line}"
RULE_FAILED = "{rule}: {error}"
NO_THRESHOLD = "-"

Work = tuple["Pipeline", "Subject"]


@dataclass
class Graph:
    """Works of the store by id and the relations between them, one field at a time.

    `nodes` maps an id to its (pipeline, subject); `edges` maps a field to source id -> the id
    the field of the source names.
    """

    nodes: dict[str, Work] = field(default_factory=dict)
    edges: dict[str, dict[str, str]] = field(default_factory=dict)

    def target(self, subject_id: str, name: str) -> str:
        """Id the field of the subject names, or empty."""
        return self.edges.get(name, {}).get(subject_id, "")

    def pointing(self, name: str, target: str) -> list[Work]:
        """(pipeline, subject) of every work whose field names the target, by id."""
        return [self.nodes[source] for source, ref in sorted(self.edges.get(name, {}).items())
                if ref == target and source in self.nodes]


def read_graph(ctx: Context) -> Graph:
    """Graph of every existing subject of ctx.pipelines; the first pipeline holding an id wins."""
    graph = Graph(edges={name: {} for name in RELATION_FIELDS})
    for pipeline in ctx.pipelines.values():
        for subject in pipeline_subjects(ctx, pipeline):
            if not subject.exists or subject.id in graph.nodes:
                continue
            graph.nodes[subject.id] = (pipeline, subject)
            for name in RELATION_FIELDS:
                ref = relation_field(subject, name)
                if ref:
                    graph.edges[name][subject.id] = ref
    return graph


def build_graph(ctx: Context) -> Graph:
    """The graph of relations, built once per run and root."""
    return ctx.cache.value((GRAPH_KEY, str(ctx.root)), lambda: read_graph(ctx))


class Reader:
    """Logs of the store read once per run: one subject's, or every one of a pipeline."""

    def __init__(self, root: Path) -> None:
        """Remember the store root; nothing is read yet."""
        self.root = root
        self.logs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.pipelines: dict[str, list[list[dict[str, Any]]]] = {}

    def read(self, pipeline: str, subject_id: str) -> list[dict[str, Any]]:
        """Entries of the log of the subject, in the order written."""
        key = (pipeline, subject_id)
        if key not in self.logs:
            self.logs[key] = ev.read(self.root, pipeline, subject_id)
        return self.logs[key]

    def works(self, pipeline: str) -> list[list[dict[str, Any]]]:
        """Non-empty logs of every work of the pipeline, oldest last event first.

        Works no provider finds any more (archived, removed) count too: their log is history.
        """
        if pipeline not in self.pipelines:
            directory = ev.log_path(self.root, pipeline, pipeline).parent
            found = [self.read(pipeline, path.stem.replace(ev.ID_REPLACEMENT, ev.ID_SEPARATOR))
                     for path in sorted(directory.glob(LOG_GLOB))]
            self.pipelines[pipeline] = sorted((entries for entries in found if entries),
                                              key=last_moment)
        return self.pipelines[pipeline]


def last_moment(entries: list[dict[str, Any]]) -> float:
    """POSIX time of the last timed entry; 0 without one."""
    times = [at for at in map(moment, entries) if at is not None]
    return max(times).timestamp() if times else 0.0


@dataclass
class Log:
    """Evidence of the work under review: its own entries and the logs of its pipeline."""

    reader: Reader
    pipeline: Pipeline
    subject_id: str

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Entries of the log of the work, in the order written."""
        return self.reader.read(self.pipeline.name, self.subject_id)

    def of(self, pipeline: str, subject_id: str) -> list[dict[str, Any]]:
        """Entries of the log of another work."""
        return self.reader.read(pipeline, subject_id)

    def works(self) -> list[list[dict[str, Any]]]:
        """Non-empty logs of every work of the pipeline, oldest last event first."""
        return self.reader.works(self.pipeline.name)


def load_rules(profile_dir: Path) -> dict[str, type[Rule]]:
    """Core rules plus those of RULES in <profile>/retro/*.py; LoadError lists every problem.

    A module starting with _ is skipped; a name taken by a core rule or another module, a value
    that is not a Rule subclass, a key differing from its name or an import failure is an error.
    """
    directory = profile_dir / RETRO_DIR
    if not directory.is_dir():
        return dict(RULES)
    found: dict[str, Any] = {}
    errors: list[str] = []
    for path in sorted(directory.glob(GATES_GLOB)):
        if path.name.startswith(PRIVATE_PREFIX):
            continue
        try:
            module = load_module(path)
        except Exception as exc:
            errors.append(f"{path}: import failed: {exc!r}")
            continue
        table = getattr(module, RULES_ATTR, None)
        if not isinstance(table, dict):
            errors.append(f"{path}: {RULES_ATTR} mapping of name to rule class is required")
            continue
        registered(path, table, Rule, RULES, found, errors)
    if errors:
        raise LoadError(errors)
    return {**RULES, **found}


def open_works(ctx: Context, pipelines: list[Pipeline]) -> list[Work]:
    """(pipeline, subject) of every existing, not archived subject, pipeline by pipeline."""
    return [(pipeline, subject) for pipeline in pipelines
            for subject in pipeline_subjects(ctx, pipeline)
            if subject.exists and not subject.archived]


def identity(proposal: Proposal) -> tuple[str, str, str]:
    """(rule, code, subject) a decision is kept under."""
    return proposal.rule, proposal.code, proposal.subject or ""


@dataclass
class Outcome:
    """What the rules made of the works: proposals, observations, failure lines.

    `observations` holds (rule, observations of one evaluate) in the order the rules ran, so a
    rule that observed nothing still has its place.
    """

    proposals: list[Proposal] = field(default_factory=list)
    observations: list[tuple[str, list[Observation]]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def make_rule(cls: type[Rule], thresholds: dict[str, int]) -> Rule:
    """An instance of the rule with the threshold of svod.yaml when it names the rule."""
    rule = cls()
    if rule.name in thresholds:
        rule.threshold = thresholds[rule.name]
    if not isinstance(getattr(rule, "observed", None), list):
        rule.observed = []
    return rule


def run_rules(ctx: Context, works: list[Work], rules: dict[str, type[Rule]]) -> Outcome:
    """Proposals (each once) and observations of the rules over the works, and failures.

    Proposals come work by work, rule by rule in registry order. A rule that raises adds a
    failure line and nothing else: a profile rule with a bug does not stop the review.
    """
    graph = build_graph(ctx)
    reader = Reader(ctx.root)
    outcome = Outcome()
    seen: set[tuple[str, str, str]] = set()
    for pipeline, subject in works:
        log = Log(reader, pipeline, subject.id)
        for name, cls in rules.items():
            try:
                rule = make_rule(cls, ctx.config.retro_thresholds)
                proposals = rule.evaluate(ctx, subject, log, graph)
            except Exception as exc:
                outcome.failures.append(RULE_FAILED.format(rule=name, error=f"{exc!r}"))
                continue
            default = pipeline.name if rule.scope == SCOPE_PIPELINE else subject.id
            for observation in rule.observed:
                observation.subject = observation.subject or default
            outcome.observations.append((name, rule.observed))
            for proposal in proposals:
                if proposal.subject is None:
                    proposal.subject = default
                if identity(proposal) not in seen:
                    seen.add(identity(proposal))
                    outcome.proposals.append(proposal)
    return outcome


def review(ctx: Context, works: list[Work],
           rules: dict[str, type[Rule]]) -> tuple[list[Proposal], list[str]]:
    """(proposals, failures) of the rules over the works, each proposal once."""
    outcome = run_rules(ctx, works, rules)
    return outcome.proposals, outcome.failures


def pending(proposals: list[Proposal], decided: set[tuple[str, str, str]]) -> list[Proposal]:
    """Proposals no decision was taken on yet."""
    return [proposal for proposal in proposals if identity(proposal) not in decided]


def text_of(locale: Locale, key: str, facts: dict[str, Any]) -> str:
    """A locale key filled with the facts, or the text itself when the locale has no such key."""
    return locale.text(key, **facts) if locale.has(key) else key


def facts_line(facts: dict[str, Any]) -> str:
    """Facts as name=value pairs in their order."""
    return FACTS_SEPARATOR.join(FACT_PAIR.format(name=name, value=value)
                                for name, value in facts.items())


def render(locale: Locale, proposals: list[Proposal]) -> list[str]:
    """Lines of the numbered list: rule and text, the facts, the proposed change."""
    from .. import keys

    lines = []
    for number, proposal in enumerate(proposals, 1):
        lines.append(locale.text(keys.RETRO_ITEM, number=number, rule=proposal.rule,
                                 subject=proposal.subject,
                                 text=text_of(locale, proposal.text_key, proposal.facts)))
        lines.append(locale.text(keys.RETRO_FACTS, facts=facts_line(proposal.facts)))
        if proposal.change:
            lines.append(locale.text(keys.RETRO_PROPOSED, file=proposal.change[CHANGE_FILE],
                                     kind=proposal.change[CHANGE_KIND],
                                     text=change_text(locale, proposal)))
    return lines


def explain(locale: Locale, outcome: Outcome, decided: set[tuple[str, str, str]]) -> list[str]:
    """Lines of --explain: per rule and what it saw, the threshold, the verdict, the facts.

    An observation with the rule, code and subject of an earlier one is shown once (a rule over
    a pipeline sees the same in each of its works). A rule that observed nothing (a rule of the
    profile not calling reaches) is shown with the facts of its proposals, or as silent.
    """
    from .. import keys

    lines: list[str] = []
    shown: set[tuple[str, str, str]] = set()
    silent: set[str] = set()
    for name, observations in outcome.observations:
        if not observations:
            own = [p for p in outcome.proposals if p.rule == name]
            for proposal in own:
                key = identity(proposal)
                if key not in shown:
                    shown.add(key)
                    lines += explain_lines(locale, name, proposal.subject or "",
                                           proposal.facts, None,
                                           verdict(key, True, None, decided))
            if not own and name not in silent:
                silent.add(name)
                lines.append(locale.text(keys.RETRO_EXPLAIN_SILENT, rule=name))
            continue
        for seen in observations:
            key = (seen.rule, seen.code, seen.subject or "")
            if key in shown:
                continue
            shown.add(key)
            lines += explain_lines(locale, name, seen.subject or "", seen.facts,
                                   seen.threshold,
                                   verdict(key, seen.fired, seen.threshold, decided))
    return lines


def verdict(key: tuple[str, str, str], fired: bool, threshold: int | None,
            decided: set[tuple[str, str, str]]) -> str:
    """Locale key of what came of one comparison."""
    from .. import keys

    if fired:
        return keys.RETRO_EXPLAIN_DECIDED if key in decided else keys.RETRO_EXPLAIN_PROPOSED
    return keys.RETRO_EXPLAIN_OFF if threshold == 0 else keys.RETRO_EXPLAIN_BELOW


def explain_lines(locale: Locale, rule: str, subject: str, facts: dict[str, Any],
                  threshold: int | None, outcome_key: str) -> list[str]:
    """Two lines of --explain: the rule, what it is about, the threshold, the verdict; facts."""
    from .. import keys

    return [locale.text(keys.RETRO_EXPLAIN, rule=rule, subject=subject,
                        threshold=NO_THRESHOLD if threshold is None else threshold,
                        verdict=locale.text(outcome_key)),
            locale.text(keys.RETRO_FACTS, facts=facts_line(facts))]


def change_text(locale: Locale, proposal: Proposal) -> str:
    """Text of the proposed change: a literal line, or a locale key filled with the facts."""
    text = str((proposal.change or {}).get(CHANGE_TEXT, ""))
    return text_of(locale, text, proposal.facts)


def hint(locale: Locale, proposal: Proposal) -> list[str]:
    """A diff to apply by hand: the file, the anchor when known, the added line."""
    if not proposal.change:
        return []
    file = proposal.change[CHANGE_FILE]
    lines = [DIFF_OLD.format(file=file), DIFF_NEW.format(file=file)]
    if proposal.change.get(CHANGE_ANCHOR):
        lines.append(DIFF_HUNK.format(anchor=proposal.change[CHANGE_ANCHOR]))
    lines += [DIFF_ADD.format(line=line)
              for line in change_text(locale, proposal).splitlines() or [""]]
    return lines
