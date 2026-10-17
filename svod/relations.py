"""Children of a work: subjects whose frontmatter field names it, for the summary and status.

The relation gates (`has_children`, `children_done`) count the same children; subjects are
enumerated once per run and root through the cache they share.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .gates import (DEFAULT_RELATION_FIELD, PARAM_FIELD, PARAM_PIPELINES, pipeline_subjects,
                    relation_field)

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import GateRef, Pipeline
    from .subject import Subject

CHILD_INDEX = "relation_children"
ID_INDEX = "relation_ids"
RELATION_GATES = frozenset({"has_children", "children_done"})

Keep = Callable[["Pipeline", "Subject"], bool]


@dataclass
class Node:
    """A child in the tree under a subject, with its own children."""

    pipeline: Pipeline
    subject: Subject
    children: list[Node] = field(default_factory=list)


def by_name(pipelines: Iterable[Pipeline]) -> dict[str, Pipeline]:
    """Pipelines by name."""
    return {pipeline.name: pipeline for pipeline in pipelines}


def child_index(ctx: Context, pipeline: Pipeline, name: str) -> dict[str, list[Subject]]:
    """Existing subjects of the pipeline by the reference their field holds, once per run."""
    def build() -> dict[str, list[Subject]]:
        """Index of the enumerated subjects by the field."""
        index: dict[str, list[Subject]] = {}
        for subject in pipeline_subjects(ctx, pipeline):
            ref = relation_field(subject, name)
            if subject.exists and ref:
                index.setdefault(ref, []).append(subject)
        return index
    return ctx.cache.value((CHILD_INDEX, str(ctx.root), pipeline.name, name), build)


def subject_by_id(ctx: Context, pipeline: Pipeline, ref: str) -> Subject | None:
    """Existing subject of the pipeline with the id, from the enumeration of the run."""
    def build() -> dict[str, Subject]:
        """Existing subjects by id, the first one of an id kept."""
        index: dict[str, Subject] = {}
        for subject in pipeline_subjects(ctx, pipeline):
            if subject.exists:
                index.setdefault(subject.id, subject)
        return index
    return ctx.cache.value((ID_INDEX, str(ctx.root), pipeline.name), build).get(ref)


def children_of(ctx: Context, pipelines: Iterable[Pipeline], subject: Subject,
                child_pipelines: Iterable[str],
                field: str = DEFAULT_RELATION_FIELD) -> list[tuple[Pipeline, Subject]]:
    """(pipeline, child) of every existing subject of the child pipelines naming the subject.

    In the order of child_pipelines, then of the provider; names not among pipelines are skipped.
    """
    known = by_name(pipelines)
    return [(known[name], child)
            for name in dict.fromkeys(child_pipelines) if name in known
            for child in child_index(ctx, known[name], field).get(subject.id, [])]


def relation_refs(pipeline: Pipeline) -> list[GateRef]:
    """Uses of the relation gates in the steps and the done gate of the pipeline, in order."""
    refs = [ref for step in pipeline.steps for ref in step.gates]
    refs += [pipeline.done] if pipeline.done is not None else []
    return [ref for ref in refs if ref.gate in RELATION_GATES]


def declared_children(pipeline: Pipeline) -> list[tuple[str, str]]:
    """(child pipeline, field) pairs the status lists children by; empty when it lists none.

    `active.children` when declared, else the pipelines of every `has_children` and
    `children_done` use in the steps and the done gate, in the order of first mention.
    """
    if pipeline.active is not None and pipeline.active.children:
        return [(name, DEFAULT_RELATION_FIELD) for name in pipeline.active.children]
    pairs: dict[tuple[str, str], None] = {}
    for ref in relation_refs(pipeline):
        names = ref.params.get(PARAM_PIPELINES)
        name_field = ref.params.get(PARAM_FIELD, DEFAULT_RELATION_FIELD)
        for name in names if isinstance(names, list) else []:
            if isinstance(name, str) and isinstance(name_field, str):
                pairs[(name, name_field)] = None
    return list(pairs)


def listed_children(ctx: Context, pipelines: Iterable[Pipeline], pipeline: Pipeline,
                    subject: Subject) -> list[tuple[Pipeline, Subject]] | None:
    """Children the status lists for the subject; None when its pipeline declares none."""
    pairs = declared_children(pipeline)
    if not pairs:
        return None
    pipelines = list(pipelines)
    found: dict[tuple[str, str], tuple[Pipeline, Subject]] = {}
    for name, name_field in pairs:
        for child_pipeline, child in children_of(ctx, pipelines, subject, [name], name_field):
            found.setdefault((child_pipeline.name, child.id), (child_pipeline, child))
    return list(found.values())


def active_children(pipeline: Pipeline) -> list[str]:
    """Names of the pipelines whose subjects the summary shows under a subject of this one."""
    return list(pipeline.active.children) if pipeline.active is not None else []


def tree(ctx: Context, pipelines: Iterable[Pipeline], pipeline: Pipeline, subject: Subject,
         keep: Keep | None = None, seen: set[tuple[str, str]] | None = None) -> list[Node]:
    """Children of the subject by `active.children`, each with its own, at any depth.

    keep: which children are taken, with their subtrees; every child by default.
    seen: (pipeline, id) of the subjects already placed, shared across calls; a subject is
    placed once, so a cycle of references stops at the first subject met again.
    """
    pipelines = list(pipelines)
    placed = seen if seen is not None else set()
    placed.add((pipeline.name, subject.id))
    nodes = []
    for child_pipeline, child in children_of(ctx, pipelines, subject,
                                             active_children(pipeline)):
        key = (child_pipeline.name, child.id)
        if key in placed or (keep is not None and not keep(child_pipeline, child)):
            continue
        placed.add(key)
        nodes.append(Node(child_pipeline, child))
    for node in nodes:
        node.children = tree(ctx, pipelines, node.pipeline, node.subject, keep, placed)
    return nodes


def flatten(nodes: Iterable[Node], depth: int = 0) -> Iterable[tuple[int, Node]]:
    """(depth, node) of every node of the trees, each parent before its children."""
    for node in nodes:
        yield depth, node
        yield from flatten(node.children, depth + 1)
