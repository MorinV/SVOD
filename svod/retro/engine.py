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
                    SCOPE_PIPELINE, Proposal, Rule, moment)

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


def review(ctx: Context, works: list[Work],
           rules: dict[str, type[Rule]]) -> tuple[list[Proposal], list[str]]:
    """(proposals, failures) of the rules over the works, each proposal once.

    Proposals come work by work, rule by rule in registry order. A rule that raises adds a
    failure line and nothing else: a profile rule with a bug does not stop the review.
    """
    graph = build_graph(ctx)
    reader = Reader(ctx.root)
    found: list[Proposal] = []
    seen: set[tuple[str, str, str]] = set()
    failures: list[str] = []
    for pipeline, subject in works:
        log = Log(reader, pipeline, subject.id)
        for name, cls in rules.items():
            try:
                rule = cls()
                proposals = rule.evaluate(ctx, subject, log, graph)
            except Exception as exc:
                failures.append(RULE_FAILED.format(rule=name, error=f"{exc!r}"))
                continue
            for proposal in proposals:
                if proposal.subject is None:
                    proposal.subject = (pipeline.name if rule.scope == SCOPE_PIPELINE
                                        else subject.id)
                if identity(proposal) not in seen:
                    seen.add(identity(proposal))
                    found.append(proposal)
    return found, failures


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
