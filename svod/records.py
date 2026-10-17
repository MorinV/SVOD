"""New records: the directory of a subject of a pipeline, made from the skeletons of the profile.

`svod record new <pipeline> <name>` copies every file of `<profile>/records/<pipeline>/` into
`<root>/<name>/`, where `<root>` is the first of the `roots` the pipeline's subject provider reads
(the `container` provider and the providers built on it, such as `work` of the standard template).
The provider is the one place that knows where the subjects of a pipeline live, so no second
mapping is kept in svod.yaml; a pipeline whose provider names no roots has no records to make.

The placeholders below are replaced in every file; any other brace is kept as written. A record
whose directory holds any file is refused: nothing is overwritten. An empty directory is filled.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import keys
from .document import relative_or_absolute
from .render import Report
from .yamlio import ENCODING

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import Pipeline

RECORDS_DIR = "records"
PARAM_ROOTS = "roots"
LIST_SEPARATOR = ","
YAML_LIST = "[{items}]"
YAML_ITEM_SEPARATOR = ", "
FILES_SEPARATOR = ", "
PIPELINES_SEPARATOR = ", "
# A YAML scalar written as it is; anything else is quoted as a JSON string, which YAML reads.
PLAIN_SCALAR = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./+-]*$")
FORBIDDEN_NAME = re.compile(r"[/\\\s]")
HIDDEN_PREFIX = "."
PLACEHOLDER = "{{{name}}}"
LINE_ENDS = "\r\n"
FIELD_NAME = "name"
FIELD_KIND = "kind"
FIELD_KEY = "key"
FIELD_SERVICES = "services"
FIELD_PARENT = "parent"
FIELD_TAGS = "tags"
FIELD_DATE = "date"


@dataclass
class NewRecord:
    """What the person asked for: the pipeline, the name and the frontmatter values."""

    pipeline: str
    name: str
    services: list[str] = field(default_factory=list)
    parent: str = ""
    kind: str = ""
    tags: list[str] = field(default_factory=list)
    key: str = ""


def split_list(text: str | None) -> list[str]:
    """Items of a comma separated option, stripped, empty ones dropped."""
    return [item.strip() for item in (text or "").split(LIST_SEPARATOR) if item.strip()]


def yaml_scalar(value: str) -> str:
    """A YAML scalar: plain when it reads back as the same string, else a quoted string."""
    if not value or PLAIN_SCALAR.match(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def yaml_list(items: list[str]) -> str:
    """A YAML flow list: [a, b], [] when empty."""
    return YAML_LIST.format(items=YAML_ITEM_SEPARATOR.join(yaml_scalar(i) for i in items))


def subject_root(pipeline: Pipeline) -> str | None:
    """The directory the subjects of the pipeline live in: the first root of its provider."""
    params = getattr(pipeline.subject.impl, "params", None) or {}
    roots = params.get(PARAM_ROOTS)
    if isinstance(roots, list) and roots and isinstance(roots[0], str):
        return roots[0].strip("/")
    return None


def skeleton_dir(ctx: Context, pipeline: Pipeline) -> Path:
    """<profile>/records/<pipeline>/ of the store."""
    return ctx.config.profile / RECORDS_DIR / pipeline.name


def skeleton_files(directory: Path) -> list[Path]:
    """Files of the skeleton directory, relative to it, in sorted order."""
    if not directory.is_dir():
        return []
    return sorted(p.relative_to(directory) for p in directory.rglob("*") if p.is_file())


def values_of(record: NewRecord, today: str) -> dict[str, str]:
    """Placeholder name to the text it is replaced with."""
    return {FIELD_NAME: record.name, FIELD_KIND: yaml_scalar(record.kind or record.pipeline),
            FIELD_KEY: yaml_scalar(record.key), FIELD_SERVICES: yaml_list(record.services),
            FIELD_PARENT: yaml_scalar(record.parent), FIELD_TAGS: yaml_list(record.tags),
            FIELD_DATE: today}


def fill(text: str, values: dict[str, str]) -> str:
    """The text with every {placeholder} of the values replaced; other braces are kept.

    A line holding a placeholder loses its trailing spaces, so an empty value leaves `key:`.
    """
    marks = {PLACEHOLDER.format(name=name): value for name, value in values.items()}
    lines = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip(LINE_ENDS)
        if any(mark in body for mark in marks):
            for mark, value in marks.items():
                body = body.replace(mark, value)
            line = body.rstrip(" ") + line[len(line.rstrip(LINE_ENDS)):]
        lines.append(line)
    return "".join(lines)


def bad_name(name: str) -> bool:
    """A record name is one directory name: not empty, no separator or space, not hidden."""
    return not name or name.startswith(HIDDEN_PREFIX) or FORBIDDEN_NAME.search(name) is not None


def occupied(path: Path) -> bool:
    """Whether the path is a file, or a directory holding anything."""
    return path.exists() and (not path.is_dir() or any(path.iterdir()))


def new_record(ctx: Context, pipelines: list[Pipeline], record: NewRecord) -> Report:
    """Create the record from the skeletons of its pipeline; refuse an existing one.

    Exit 0 created, 1 the record exists (refused), 2 an unknown pipeline, a bad name, a pipeline
    without a record directory or without skeletons.
    """
    locale = ctx.locale
    pipeline = next((p for p in pipelines if p.name == record.pipeline), None)
    if pipeline is None:
        return Report(False, err=[locale.text(
            keys.RECORD_UNKNOWN_PIPELINE, name=record.pipeline,
            names=PIPELINES_SEPARATOR.join(p.name for p in pipelines))])
    if bad_name(record.name):
        return Report(False, err=[locale.text(keys.RECORD_BAD_NAME, name=record.name)])
    root = subject_root(pipeline)
    if root is None:
        return Report(False, err=[locale.text(keys.RECORD_NO_ROOT, name=pipeline.name)])
    source = skeleton_dir(ctx, pipeline)
    files = skeleton_files(source)
    if not files:
        return Report(False, err=[locale.text(keys.RECORD_NO_SKELETON, name=pipeline.name,
                                              dir=relative_or_absolute(ctx.root, source))])
    target = ctx.root / root / record.name
    shown = relative_or_absolute(ctx.root, target)
    if occupied(target):
        return Report(False, err=[locale.text(keys.RECORD_EXISTS, path=shown)], refused=True)
    values = values_of(record, ctx.today.isoformat())
    for rel in files:
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (source / rel).read_text(encoding=ENCODING)
        path.write_text(fill(text, values), encoding=ENCODING)
    return Report(True, out=[locale.text(keys.RECORD_CREATED, path=shown,
                                         files=FILES_SEPARATOR.join(p.as_posix() for p in files))])
