"""Single native status collection; rendering and JSON consume captured results."""
from dataclasses import dataclass, field

from . import keys
from .checkouts import subject_context
from .gates import Status
from .position import evaluate, position
from .resolve import resolve


@dataclass
class StatusItem:
    """One resolved subject, including missing outcomes suppressed by another answer."""

    pipeline: object
    subject: object
    context: object
    position: object = None
    missing: object = None
    missing_suppressed: bool = False
    skills: object = None
    instruction_variant: str | None = None


@dataclass
class Collection:
    """Captured native answer, without serialized authority or gate callbacks."""

    query: str
    resolution: object
    report: object
    items: list = field(default_factory=list)

    @property
    def positions(self):
        return [item.position for item in self.items if item.position is not None]


def collect_status(ctx, pipelines, query):
    """Resolve and evaluate once, preserving the native missing/output precedence."""
    from .render import INDENT, Report, render_position, step_skills, subject_facts_of, text_key

    found = resolve(ctx, pipelines, query)
    locale = ctx.locale
    if not found.matches:
        return Collection(query, found, Report(False, err=[locale.text(keys.STATUS_NOT_FOUND, query=query)]))
    if found.ambiguous:
        err = [locale.text(keys.STATUS_AMBIGUOUS)]
        err += [INDENT + locale.text(keys.STATUS_CANDIDATE, id=s.id) for _, s in found.matches]
        return Collection(query, found, Report(False, err=err))
    out, err, items = [], [], []
    for pipeline, subject in found.matches:
        own = subject_context(ctx, subject)
        item = StatusItem(pipeline, subject, own)
        items.append(item)
        if not subject.exists and pipeline.missing is not None:
            item.missing = evaluate(own, pipeline.missing, subject)
            if item.missing.result.status is Status.FAIL:
                err.append(locale.text(pipeline.missing.text,
                                       **{**subject_facts_of(pipeline, subject), **item.missing.result.facts}))
                continue
        if out:
            out.append("")
        pos = position(own, pipeline, subject)
        item.position = pos
        item.skills = step_skills(own, pos)
        item.instruction_variant = text_key(locale, pos.text, pos.facts) if pos.text else None
        out += render_position(locale, pos, item.skills)
    for item in items:
        item.missing_suppressed = bool(out) and item.position is None
    return Collection(query, found, Report(bool(out), out=out, err=[] if out else err), items)
