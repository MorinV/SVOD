"""Single native status collection; rendering and JSON consume captured results."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import evidence_log, keys
from .checkouts import subject_context
from .gates import Status
from .position import evaluate, position
from .relations import listed_children
from .resolve import resolve

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import Outcome, Pipeline
    from .position import Position
    from .render import Report
    from .resolve import Resolution
    from .subject import Subject


@dataclass
class StatusItem:
    """One resolved subject, including missing outcomes suppressed by another answer."""

    pipeline: Pipeline
    subject: Subject
    context: Context
    position: Position | None = None
    missing: Outcome | None = None
    missing_suppressed: bool = False
    skills: list[tuple[str, Any]] | None = None
    instruction_variant: str | None = None
    # Positions of the children the pipeline lists; None when it lists none.
    children: list[Position] | None = None


@dataclass
class Collection:
    """Captured native answer, without serialized authority or gate callbacks."""

    query: str
    resolution: Resolution
    report: Report
    items: list[StatusItem] = field(default_factory=list)

    @property
    def positions(self) -> list[Position]:
        """Positions of the evaluated items, in order."""
        return [item.position for item in self.items if item.position is not None]


def child_positions(ctx: Context, pipelines: list[Pipeline], pipeline: Pipeline,
                    subject: Subject) -> list[Position] | None:
    """Positions of the children the pipeline lists for an existing subject, else None."""
    if not subject.exists:
        return None
    found = listed_children(ctx, pipelines, pipeline, subject)
    if found is None:
        return None
    return [position(ctx, child_pipeline, child) for child_pipeline, child in found]


def collect_status(ctx: Context, pipelines: list[Pipeline], query: str,
                   *, children: bool = True) -> Collection:
    """Resolve and evaluate once, preserving the native missing/output precedence."""
    from .render import INDENT, Report, render_position, step_skills, subject_facts_of, text_key

    found = resolve(ctx, pipelines, query)
    locale = ctx.locale
    if not found.matches:
        return Collection(query, found,
                          Report(False, err=[locale.text(keys.STATUS_NOT_FOUND, query=query)]))
    if found.ambiguous:
        err: list[str] = [locale.text(keys.STATUS_AMBIGUOUS)]
        err += [INDENT + locale.text(keys.STATUS_CANDIDATE, id=s.id) for _, s in found.matches]
        return Collection(query, found, Report(False, err=err))
    out: list[str] = []
    err = []
    items: list[StatusItem] = []
    for pipeline, subject in found.matches:
        own = subject_context(ctx, subject)
        item = StatusItem(pipeline, subject, own)
        items.append(item)
        if not subject.exists and pipeline.missing is not None:
            item.missing = evaluate(own, pipeline.missing, subject)
            if item.missing.result.status is Status.FAIL:
                err.append(locale.text(pipeline.missing.text,
                                       **{**subject_facts_of(pipeline, subject),
                                          **item.missing.result.facts}))
                continue
        if out:
            out.append("")
        pos = position(own, pipeline, subject)
        item.position = pos
        evidence_log.note_position(ctx, pos)
        item.skills = step_skills(own, pos)
        item.instruction_variant = text_key(locale, pos.text, pos.facts) if pos.text else None
        if children:
            item.children = child_positions(own, pipelines, pipeline, subject)
        out += render_position(locale, pos, item.skills,
                               ctx.config.autonomy.get(pipeline.name), item.children)
    for item in items:
        item.missing_suppressed = bool(out) and item.position is None
    return Collection(query, found, Report(bool(out), out=out, err=[] if out else err), items)
