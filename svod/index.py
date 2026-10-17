"""Session index: the open records of every pipeline, one line each, children under parents.

What the session-start hook gives by default instead of the active summary: per pipeline, in
the order of `active_order` then by name, the id of every open record, its kind when it is not
the pipeline's name, and its title, the first heading of its head document. Only frontmatter
and that heading are read: no position, gate, command, git call or knowledge note.

A record is open when it exists, is not archived, and the done gate of its pipeline, when it
is a `field` condition, does not hold on its frontmatter; any other done gate is not
evaluated, so such a record stays listed until it is archived. A record whose `parent` names
an open record (of any pipeline) is listed under it instead of in its own pipeline; one on a
cycle of parents stays in its own pipeline, so the walk always ends.

Importing this module loads no gate, git or command module; the reference reader shared with
the relation gates and the heading reader of the knowledge notes are imported when the index is
built, from a runtime the loader has already bound.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import keys
from .frontmatter import DOC_GLOB, read_frontmatter
from .subject import ATTR_FRONTMATTER
from .yamlio import ENCODING

if TYPE_CHECKING:
    from pathlib import Path

    from .config import Config
    from .context import Context
    from .locale import Locale
    from .pipeline import Pipeline
    from .subject import Subject

INDENT = "  "
FIELD_KIND = "kind"
FIELD_GATE = "field"
PARAM_NAME = "name"
PARAM_EQUALS = "equals"
PARAM_NOT_EQUALS = "not_equals"
PARAM_PRESENT = "present"

Key = tuple[str, str]


@dataclass
class Entry:
    """An open record of the index with the open records listed under it."""

    pipeline: Pipeline
    subject: Subject
    children: list[Entry] = field(default_factory=list)


def ordered(pipelines: Iterable[Pipeline], order: Iterable[str]) -> list[Pipeline]:
    """Pipelines named in order first, the rest by name."""
    rank = {name: i for i, name in enumerate(order)}
    return sorted(pipelines, key=lambda p: (rank.get(p.name, len(rank)), p.name))


def frontmatter_of(subject: Subject) -> dict[str, Any]:
    """Frontmatter of the record's head document, empty without one."""
    found = subject.attrs.get(ATTR_FRONTMATTER)
    return found if isinstance(found, dict) else {}


def done_by_field(pipeline: Pipeline, frontmatter: dict[str, Any]) -> bool:
    """Whether the done gate of the pipeline is a field condition the frontmatter meets.

    The conditions read as the `field` gate reads them: an empty field never equals or
    differs. A date condition, and any other done gate, is not read here: False.
    """
    ref = pipeline.done
    if ref is None or ref.gate != FIELD_GATE:
        return False
    value = frontmatter.get(str(ref.params.get(PARAM_NAME)))
    text = "" if value is None else str(value).strip()
    if PARAM_EQUALS in ref.params:
        return bool(text) and text == str(ref.params[PARAM_EQUALS])
    if PARAM_NOT_EQUALS in ref.params:
        return bool(text) and text != str(ref.params[PARAM_NOT_EQUALS])
    if PARAM_PRESENT in ref.params:
        return bool(text) == ref.params[PARAM_PRESENT]
    return False


def is_open(pipeline: Pipeline, subject: Subject) -> bool:
    """Whether the record exists, is not archived and not done by its frontmatter."""
    return (subject.exists and not subject.archived
            and not done_by_field(pipeline, frontmatter_of(subject)))


def open_records(ctx: Context, pipelines: list[Pipeline]) -> dict[Key, Entry]:
    """Open records of the pipelines by (pipeline, id), in pipeline then provider order."""
    found: dict[Key, Entry] = {}
    for pipeline in pipelines:
        for subject in pipeline.subject.impl.enumerate(ctx):
            if is_open(pipeline, subject):
                found.setdefault((pipeline.name, subject.id), Entry(pipeline, subject))
    return found


def parents(pipelines: list[Pipeline], records: dict[Key, Entry]) -> dict[Key, Key]:
    """The open record each open record's `parent` names, first pipeline in order first."""
    from .gates import DEFAULT_RELATION_FIELD, relation_field
    found: dict[Key, Key] = {}
    for key, entry in records.items():
        ref = relation_field(entry.subject, DEFAULT_RELATION_FIELD)
        host = next(((p.name, ref) for p in pipelines if (p.name, ref) in records), None)
        if ref and host is not None:
            found[key] = host
    return found


def on_cycle(key: Key, up: dict[Key, Key]) -> bool:
    """Whether the parents lead from the record back to it."""
    met = {key}
    step = up.get(key)
    while step is not None:
        if step == key:
            return True
        if step in met:
            return False
        met.add(step)
        step = up.get(step)
    return False


def forest(ctx: Context, pipelines: list[Pipeline]) -> list[Entry]:
    """Records listed in their own pipeline, each with the records under it at any depth."""
    records = open_records(ctx, pipelines)
    up = parents(pipelines, records)
    nested = {key for key in up if not on_cycle(key, up)}
    for key in records:
        if key in nested:
            records[up[key]].children.append(records[key])
    return [entry for key, entry in records.items() if key not in nested]


def flatten(entries: Iterable[Entry], depth: int = 0) -> Iterator[tuple[int, Entry]]:
    """(depth, entry) of every entry of the trees, each parent before its children."""
    for entry in entries:
        yield depth, entry
        yield from flatten(entry.children, depth + 1)


def head_document(subject: Subject) -> Path | None:
    """The document the record's frontmatter comes from: the subject file, else the first
    document of its directory with that frontmatter; None without one."""
    path = subject.path
    if path is None:
        return None
    if path.is_file():
        return path
    frontmatter = frontmatter_of(subject)
    if not frontmatter or not path.is_dir():
        return None
    return next((doc for doc in sorted(path.glob(DOC_GLOB))
                 if doc.is_file() and read_frontmatter(doc) == frontmatter), None)


def title(subject: Subject) -> str | None:
    """First heading of the record's head document, or None."""
    from .knowledge import first_heading, split_document
    doc = head_document(subject)
    if doc is None:
        return None
    try:
        text = doc.read_text(encoding=ENCODING)
    except (OSError, UnicodeDecodeError):
        return None
    return first_heading(split_document(text)[1])


def kind_of(pipeline: Pipeline, subject: Subject) -> str | None:
    """The record's frontmatter kind when it is not the pipeline's own, else None."""
    kind = frontmatter_of(subject).get(FIELD_KIND)
    kind = kind.strip() if isinstance(kind, str) else ""
    return kind if kind and kind != pipeline.name else None


def item_line(locale: Locale, entry: Entry, depth: int) -> str:
    """Index line of one record, indented by its depth under its pipeline."""
    kind = kind_of(entry.pipeline, entry.subject)
    record = (locale.text(keys.INDEX_KIND, id=entry.subject.id, kind=kind) if kind
              else entry.subject.id)
    name = title(entry.subject)
    line = (locale.text(keys.INDEX_ITEM, record=record, title=name) if name
            else locale.text(keys.INDEX_ITEM_UNTITLED, record=record))
    return INDENT * (depth + 1) + line


def index_lines(ctx: Context, pipelines: Iterable[Pipeline], limit: int) -> list[str]:
    """The index of the open records, at most limit records, the rest counted in one line;
    empty when nothing is open."""
    shown = ordered(pipelines, ctx.config.active_order)
    roots = forest(ctx, shown)
    locale = ctx.locale
    lines = [locale.text(keys.INDEX_HEAD)] if roots else []
    listed = total = 0
    for pipeline in shown:
        block = [locale.text(keys.INDEX_PIPELINE, pipeline=pipeline.name)]
        for depth, entry in flatten(e for e in roots if e.pipeline is pipeline):
            total += 1
            if listed < limit:
                listed += 1
                block.append(item_line(locale, entry, depth))
        lines += block if len(block) > 1 else []
    if total > listed:
        lines.append(locale.text(keys.INDEX_MORE, count=total - listed))
    return lines


def local_config_notice(config: Config, locale: Locale) -> str | None:
    """Line asking to create the configured local config when it is missing, else None."""
    if config.local_path is None or config.local_found:
        return None
    return locale.text(keys.ACTIVE_NO_LOCAL_CONFIG,
                       file=config.local_path.relative_to(config.root).as_posix())


def session_index(ctx: Context, pipelines: Iterable[Pipeline], limit: int) -> list[str]:
    """What session start gives in index mode: a missing local config, the index and the hint
    to go deeper; empty when there is nothing to say."""
    notice = local_config_notice(ctx.config, ctx.locale)
    head = [notice] if notice else []
    body = index_lines(ctx, pipelines, limit)
    if not body:
        return head
    return head + ([""] if head else []) + body + ["", ctx.locale.text(keys.INDEX_TAIL)]
