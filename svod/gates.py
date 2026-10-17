"""Gates: named checks over a subject, core set and registry."""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from .approval import bound_files, digest_matches, read_fields, text_of
from .errors import LoadError, ParamError
from .frontmatter import documents, read_frontmatter
from .keys import (
    DESCRIBE_PREFIX, DESCRIBE_EXISTS, DESCRIBE_ARTIFACT_PATH, DESCRIBE_ARTIFACT_GLOB,
    DESCRIBE_APPROVAL, DESCRIBE_APPROVAL_BOUND, DESCRIBE_FIELD_EQUALS, DESCRIBE_FIELD_NOT_EQUALS,
    DESCRIBE_FIELD_PRESENT, DESCRIBE_FIELD_ABSENT, DESCRIBE_FIELD_DATE_NOT_PAST,
    DESCRIBE_FIELD_DATE_PAST,
    DESCRIBE_DOC_TYPE, DESCRIBE_DOC_TYPE_CONTAINER, DESCRIBE_ARCHIVED, DESCRIBE_GIT_PUSHED,
    DESCRIBE_GIT_PUSHED_REPO, DESCRIBE_CHILDREN_DONE, DESCRIBE_HAS_CHILDREN, DESCRIBE_REF_EXISTS,
    DESCRIBE_QUESTIONS_ANSWERED,
)
from .params import Configurable
from .questions import DEFAULT_FILE as DEFAULT_QUESTIONS_FILE, parse_questions
from .subject import ATTR_CONTAINER, ATTR_FRONTMATTER
from .yamlio import ENCODING

if TYPE_CHECKING:
    from .context import Context
    from .locale import Locale
    from .pipeline import Pipeline
    from .position import Position
    from .providers import Provider
    from .subject import Subject

PARAM_PATH = "path"
PARAM_GLOB = "glob"
PARAM_MIN = "min"
PARAM_MARKER = "marker"
PARAM_FILE = "file"
PARAM_NAME = "name"
PARAM_EQUALS = "equals"
PARAM_NOT_EQUALS = "not_equals"
PARAM_DATE_NOT_PAST = "date_not_past"
PARAM_PRESENT = "present"
PARAM_TYPE = "type"
PARAM_SCOPE = "scope"
PARAM_REPO = "repo"
PARAM_BIND = "bind"
PARAM_IGNORE = "ignore"
PARAM_STRIP = "strip"
PARAM_PIPELINES = "pipelines"
PARAM_FIELD = "field"
LINE_RULES = (PARAM_IGNORE, PARAM_STRIP)
FACT_REASON = "reason"
FACT_VALUE = "value"
FACT_MARKER = "marker"
FACT_BY = "by"
FACT_DATE = "date"
REASON_MISSING = "missing"
REASON_LEGACY = "legacy"
REASON_DRIFT = "drift"
REASON_UNKNOWN = "unknown"
REASON_NONE = "none"
REASON_OPEN = "open"
REASON_UNANSWERED = "unanswered"
REASON_EMPTY = "empty"
FACT_DONE = "done"
FACT_TOTAL = "total"
FACT_OPEN = "open"
FACT_COUNT = "count"
FACT_PIPELINE = "pipeline"
DEFAULT_RELATION_FIELD = "parent"
IDS_SEPARATOR = ", "
CHAIN_SEPARATOR = " -> "
REF_PREFIX = "./"
REF_SUFFIX = "/"
SUBJECT_INDEX = "relation_subjects"
BIND_SEPARATOR = ", "
SCOPE_SUBJECT = "subject"
SCOPE_CONTAINER = "container"
SCOPES = (SCOPE_SUBJECT, SCOPE_CONTAINER)
FIELD_CONDITIONS = (PARAM_EQUALS, PARAM_NOT_EQUALS, PARAM_DATE_NOT_PAST, PARAM_PRESENT)
DEFAULT_MIN = 1
FIELD_TYPE = "type"
KEYS_SEPARATOR = ", "
GATES_DIR = "gates"
GATES_GLOB = "*.py"
PRIVATE_PREFIX = "_"
GATES_ATTR = "GATES"
PROVIDERS_ATTR = "PROVIDERS"
MODULE_PREFIX = "svod_profile_gates_"


class Status(str, Enum):
    """Outcome of a gate."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Result:
    """Gate outcome with facts for texts, an optional display line and a failure reason."""

    status: Status
    facts: dict[str, Any] = field(default_factory=dict)
    display: str | None = None
    reason: str | None = None

    @property
    def passed(self) -> bool:
        """Whether the gate passed."""
        return self.status is Status.PASS


def verdict(ok: bool, **facts: Any) -> Result:
    """PASS or FAIL result with facts."""
    return Result(Status.PASS if ok else Status.FAIL, facts)


def unknown(reason: str, **facts: Any) -> Result:
    """UNKNOWN result: the check could not be performed."""
    return Result(Status.UNKNOWN, facts, reason=reason)


def subject_dir(subject: Subject) -> Path | None:
    """Artifact root of an existing subject, or None."""
    if not subject.exists or subject.path is None:
        return None
    return subject.path


class Gate(Configurable):
    """Named check over a subject."""

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Result of the check for the subject."""
        raise NotImplementedError

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """What must hold for the gate to pass, from the locale key gate.<name> and the params."""
        return locale.text(f"{DESCRIBE_PREFIX}{self.name}", **params)


class KeyGate(Gate):
    """Gate that also recognises tracker keys in queries and texts."""

    def match(self, query: str) -> str | None:
        """Tracker key named by the query, or None."""
        raise NotImplementedError

    def find(self, text: str) -> set[str]:
        """Set of tracker keys mentioned in the text."""
        raise NotImplementedError

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Passes when the subject carries at least one tracker key."""
        return verdict(bool(subject.keys), keys=KEYS_SEPARATOR.join(sorted(subject.keys)))


class ExistsGate(Gate):
    """Passes when the subject was found."""

    name = "exists"

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """PASS when the provider found the subject."""
        return verdict(subject.exists)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The subject was found."""
        return locale.text(DESCRIBE_EXISTS)


class ArtifactGate(Gate):
    """Passes when a path exists under the subject or a glob matches enough entries."""

    name = "artifact"
    PARAMS = frozenset({PARAM_PATH, PARAM_GLOB, PARAM_MIN})

    def check(self) -> None:
        """Exactly one of path and glob; min is a positive integer."""
        if (PARAM_PATH in self.params) == (PARAM_GLOB in self.params):
            raise ParamError(f"{self.name}: exactly one of {PARAM_PATH} and {PARAM_GLOB}")
        self.require_type(PARAM_PATH, str, "a string")
        self.require_type(PARAM_GLOB, str, "a string")
        minimum = self.params.get(PARAM_MIN, DEFAULT_MIN)
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < DEFAULT_MIN:
            raise ParamError(f"{self.name}: {PARAM_MIN} must be a positive integer")
        if PARAM_PATH in self.params and minimum > DEFAULT_MIN:
            raise ParamError(f"{self.name}: {PARAM_MIN} applies to {PARAM_GLOB} only")

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Count matching files under the subject; facts.count."""
        base = subject_dir(subject)
        count = 0
        if base is not None and base.is_dir():
            if PARAM_PATH in self.params:
                count = int((base / self.params[PARAM_PATH]).exists())
            else:
                count = sum(1 for _ in base.glob(self.params[PARAM_GLOB]))
        return verdict(count >= self.params.get(PARAM_MIN, DEFAULT_MIN), count=count)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The path exists, or the glob matches at least min entries."""
        if PARAM_PATH in params:
            return locale.text(DESCRIBE_ARTIFACT_PATH, path=params[PARAM_PATH])
        return locale.text(DESCRIBE_ARTIFACT_GLOB, glob=params[PARAM_GLOB],
                           min=params.get(PARAM_MIN, DEFAULT_MIN))


class ApprovalGate(Gate):
    """Passes when a marker field in a YAML file under the subject is set.

    With bind the approval is tied to a version: the approver and the digest of the bound
    files must be recorded next to the marker, and the digest must match the files now.
    With ignore the digest skips blank lines and lines matched by any of the patterns; with
    strip the matches are cut out of every line first, so only the rest counts.
    """

    name = "approval"
    PARAMS = frozenset({PARAM_MARKER, PARAM_FILE, PARAM_BIND, *LINE_RULES})
    REQUIRED = frozenset({PARAM_MARKER, PARAM_FILE})

    def check(self) -> None:
        """Marker and file are strings; bind and the line rules are non-empty lists."""
        self.require_type(PARAM_MARKER, str, "a string")
        self.require_type(PARAM_FILE, str, "a string")
        bind = self.params.get(PARAM_BIND)
        if bind is not None and not non_empty_strings(bind):
            raise ParamError(f"{self.name}: {PARAM_BIND} must be a non-empty list of globs")
        for rule in LINE_RULES:
            self.check_line_rule(rule, bind)

    def check_line_rule(self, rule: str, bind: Any) -> None:
        """A line rule, when given, needs bind and is a non-empty list of regular expressions."""
        patterns = self.params.get(rule)
        if patterns is None:
            return
        if bind is None:
            raise ParamError(f"{self.name}: {rule} applies to {PARAM_BIND} only")
        if not non_empty_strings(patterns):
            raise ParamError(f"{self.name}: {rule} must be a non-empty list of regular "
                             "expressions")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ParamError(f"{self.name}: {rule}: {pattern!r} is not a regular "
                                 f"expression: {exc}") from exc

    def failed(self, reason: str, **facts: Any) -> Result:
        """FAIL with the reason among the facts."""
        return Result(Status.FAIL, {**facts, FACT_REASON: reason})

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Read the approval fields; facts.value, marker, by, date and reason on failure."""
        marker = self.params[PARAM_MARKER]
        empty = {FACT_VALUE: "", FACT_MARKER: marker, FACT_BY: "", FACT_DATE: ""}
        bind = self.params.get(PARAM_BIND)
        base = subject_dir(subject)
        if bind and (base is None or not bound_files(base, bind)):
            return self.failed(REASON_MISSING, **empty)
        if base is None or not (path := base / self.params[PARAM_FILE]).is_file():
            return self.failed(REASON_MISSING, **empty)
        try:
            value, by, sha = read_fields(path, marker)
        except LoadError as exc:
            return unknown(str(exc), **empty)
        facts = {FACT_VALUE: value, FACT_MARKER: marker, FACT_BY: by, FACT_DATE: value}
        if not value:
            return self.failed(REASON_MISSING, **facts)
        bind = self.params.get(PARAM_BIND)
        if not bind:
            return Result(Status.PASS, facts)
        if not by or not sha:
            return self.failed(REASON_LEGACY, **facts)
        if not digest_matches(base, bind, self.params.get(PARAM_IGNORE), sha,
                              self.params.get(PARAM_STRIP)):
            return self.failed(REASON_DRIFT, **facts)
        return Result(Status.PASS, facts)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The marker is set in the file, for the current bound files when bound."""
        if params.get(PARAM_BIND):
            return locale.text(DESCRIBE_APPROVAL_BOUND, marker=params[PARAM_MARKER],
                               file=params[PARAM_FILE],
                               bind=BIND_SEPARATOR.join(params[PARAM_BIND]))
        return locale.text(DESCRIBE_APPROVAL, marker=params[PARAM_MARKER], file=params[PARAM_FILE])


def non_empty_strings(value: Any) -> bool:
    """Whether the value is a non-empty list of non-blank strings."""
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value)


class FieldGate(Gate):
    """Condition on one frontmatter field of the subject; an empty field never equals or differs."""

    name = "field"
    PARAMS = frozenset({PARAM_NAME, *FIELD_CONDITIONS})
    REQUIRED = frozenset({PARAM_NAME})

    def check(self) -> None:
        """Exactly one condition; boolean conditions are booleans."""
        given = [c for c in FIELD_CONDITIONS if c in self.params]
        if len(given) != 1:
            raise ParamError(f"{self.name}: exactly one of {', '.join(FIELD_CONDITIONS)}")
        self.require_type(PARAM_NAME, str, "a string")
        self.require_type(PARAM_DATE_NOT_PAST, bool, "a boolean")
        self.require_type(PARAM_PRESENT, bool, "a boolean")

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Apply the condition to the frontmatter field; facts.value."""
        frontmatter = subject.attrs.get(ATTR_FRONTMATTER) or {}
        value = frontmatter.get(self.params[PARAM_NAME])
        text = "" if value is None else str(value).strip()
        if PARAM_EQUALS in self.params:
            return verdict(bool(text) and text == str(self.params[PARAM_EQUALS]), value=text)
        if PARAM_NOT_EQUALS in self.params:
            return verdict(bool(text) and text != str(self.params[PARAM_NOT_EQUALS]), value=text)
        if PARAM_PRESENT in self.params:
            return verdict(bool(text) == self.params[PARAM_PRESENT], value=text)
        try:
            day = dt.date.fromisoformat(text)
        except ValueError:
            return verdict(False, value=text)
        return verdict((day >= ctx.today) == self.params[PARAM_DATE_NOT_PAST], value=text)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The condition on the field in words."""
        name = params[PARAM_NAME]
        if PARAM_EQUALS in params:
            return locale.text(DESCRIBE_FIELD_EQUALS, name=name, value=params[PARAM_EQUALS])
        if PARAM_NOT_EQUALS in params:
            return locale.text(DESCRIBE_FIELD_NOT_EQUALS, name=name,
                               value=params[PARAM_NOT_EQUALS])
        if PARAM_PRESENT in params:
            key = DESCRIBE_FIELD_PRESENT if params[PARAM_PRESENT] else DESCRIBE_FIELD_ABSENT
            return locale.text(key, name=name)
        not_past = params[PARAM_DATE_NOT_PAST]
        return locale.text(DESCRIBE_FIELD_DATE_NOT_PAST if not_past else DESCRIBE_FIELD_DATE_PAST,
                           name=name)


class DocTypeGate(Gate):
    """Passes when the subject tree holds a document of the given type."""

    name = "doc_type"
    PARAMS = frozenset({PARAM_TYPE, PARAM_SCOPE})
    REQUIRED = frozenset({PARAM_TYPE})

    def check(self) -> None:
        """Scope is one of the known scopes."""
        self.require_type(PARAM_TYPE, str, "a string")
        if self.params.get(PARAM_SCOPE, SCOPE_SUBJECT) not in SCOPES:
            raise ParamError(f"{self.name}: {PARAM_SCOPE} must be one of {', '.join(SCOPES)}")

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Search the subject or its container for a document of the type."""
        if self.params.get(PARAM_SCOPE, SCOPE_SUBJECT) == SCOPE_CONTAINER:
            container = subject.attrs.get(ATTR_CONTAINER)
            base = ctx.root / container if container else None
        else:
            base = subject_dir(subject)
        if base is None:
            return verdict(False)
        wanted = self.params[PARAM_TYPE]
        return verdict(any((read_frontmatter(p) or {}).get(FIELD_TYPE) == wanted
                           for p in documents(base)))

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """A document of the type in the subject or in its container."""
        key = (DESCRIBE_DOC_TYPE_CONTAINER if params.get(PARAM_SCOPE) == SCOPE_CONTAINER
               else DESCRIBE_DOC_TYPE)
        return locale.text(key, type=params[PARAM_TYPE])


class ArchivedGate(Gate):
    """Passes when the subject is archived."""

    name = "archived"

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """PASS when the provider marked the subject archived."""
        return verdict(subject.archived)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The subject is archived."""
        return locale.text(DESCRIBE_ARCHIVED)


class GitPushedGate(Gate):
    """Passes when a repository has no commits ahead of the default branch."""

    name = "git_pushed"
    PARAMS = frozenset({PARAM_REPO})

    def check(self) -> None:
        """Repo is a string path."""
        self.require_type(PARAM_REPO, str, "a string")

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Count commits ahead of the default branch; git failure is UNKNOWN."""
        repo = ctx.root / self.params[PARAM_REPO] if PARAM_REPO in self.params else ctx.root
        out = ctx.cache.git(repo, "rev-list", "--count", f"{ctx.config.default_branch}..HEAD")
        if not out.ok:
            return unknown(out.error)
        try:
            count = int(out.out)
        except ValueError:
            return unknown(f"git rev-list: unexpected output: {out.out}")
        return verdict(count == 0, count=count)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """No commits ahead of the default branch in the store or the given repository."""
        if PARAM_REPO in params:
            return locale.text(DESCRIBE_GIT_PUSHED_REPO, repo=params[PARAM_REPO])
        return locale.text(DESCRIBE_GIT_PUSHED)


def ref_text(value: Any) -> str:
    """A reference to a subject as written in a field: stripped, without ./ and a trailing /."""
    return text_of(value).removeprefix(REF_PREFIX).rstrip(REF_SUFFIX)


def relation_field(subject: Subject, name: str) -> str:
    """Reference held by a frontmatter field of the subject, or empty."""
    return ref_text((subject.attrs.get(ATTR_FRONTMATTER) or {}).get(name))


def pipeline_subjects(ctx: Context, pipeline: Pipeline) -> list[Subject]:
    """Every subject of the pipeline, enumerated once per run and root."""
    return ctx.cache.value((SUBJECT_INDEX, str(ctx.root), pipeline.name),
                           lambda: pipeline.subject.impl.enumerate(ctx))


def named_pipelines(ctx: Context, names: list[str]) -> list[Pipeline]:
    """Pipelines of the names from ctx.pipelines; KeyError names the first unknown one."""
    return [ctx.pipelines[name] for name in names]


def find_subject(ctx: Context, pipelines: list[Pipeline],
                 ref: str) -> tuple[Pipeline, Subject] | None:
    """First (pipeline, subject) among the pipelines whose existing subject has the id ref."""
    for pipeline in pipelines:
        for found in pipeline_subjects(ctx, pipeline):
            if found.exists and found.id == ref:
                return pipeline, found
    return None


def ancestors(ctx: Context, subject: Subject, name: str) -> Iterator[str]:
    """Ids the field leads to from the subject upward, through every pipeline of ctx.

    Stops at an empty field, an id of no subject, or after the first id met again.
    """
    every = list(ctx.pipelines.values())
    seen = {subject.id}
    ref = relation_field(subject, name)
    while ref:
        yield ref
        if ref in seen:
            return
        seen.add(ref)
        found = find_subject(ctx, every, ref)
        ref = relation_field(found[1], name) if found else ""


def is_done(pos: Position) -> bool:
    """Whether a position is done: its done gate passed; without done, every step passed."""
    if pos.done is not None:
        return True
    return (pos.pipeline.done is None and pos.subject.exists and pos.blocked is None
            and pos.current is None)


EVALUATING: ContextVar[frozenset[str]] = ContextVar("svod_children_evaluating",
                                                    default=frozenset())


def unknown_pipeline(exc: KeyError, **facts: Any) -> Result:
    """UNKNOWN for a pipeline name ctx.pipelines does not hold."""
    return unknown(f"unknown pipeline: {exc.args[0]}", **facts)


def check_pipelines(gate: Gate) -> None:
    """Raise ParamError unless the pipelines param is a non-empty list of names."""
    if not non_empty_strings(gate.params[PARAM_PIPELINES]):
        raise ParamError(f"{gate.name}: {PARAM_PIPELINES} must be a non-empty list of "
                         "pipeline names")


class RelationGate(Gate):
    """Base of the gates over children: subjects of the pipelines whose field names this one."""

    PARAMS = frozenset({PARAM_PIPELINES, PARAM_FIELD})
    REQUIRED = frozenset({PARAM_PIPELINES})
    DESCRIBE = ""

    def check(self) -> None:
        """Pipelines is a non-empty list of names; field is a string."""
        check_pipelines(self)
        self.require_type(PARAM_FIELD, str, "a string")

    @property
    def field(self) -> str:
        """Frontmatter field of a child naming its parent."""
        return str(self.params.get(PARAM_FIELD, DEFAULT_RELATION_FIELD))

    def children(self, ctx: Context, subject: Subject) -> list[tuple[Pipeline, Subject]]:
        """(pipeline, child) of every existing subject whose field names the subject.

        KeyError when a pipeline name is not loaded.
        """
        return [(pipeline, child)
                for pipeline in named_pipelines(ctx, self.params[PARAM_PIPELINES])
                for child in pipeline_subjects(ctx, pipeline)
                if child.exists and relation_field(child, self.field) == subject.id]

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """Children in the pipelines by the field."""
        return locale.text(self.DESCRIBE, pipelines=IDS_SEPARATOR.join(params[PARAM_PIPELINES]),
                           field=params.get(PARAM_FIELD, DEFAULT_RELATION_FIELD))


class HasChildrenGate(RelationGate):
    """Passes when at least one subject of the pipelines names this one in the field."""

    name = "has_children"
    DESCRIBE = DESCRIBE_HAS_CHILDREN

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Count the children; facts.total. An unknown pipeline is UNKNOWN."""
        try:
            total = len(self.children(ctx, subject))
        except KeyError as exc:
            return unknown_pipeline(exc)
        return verdict(total > 0, total=total)


class ChildrenDoneGate(RelationGate):
    """Passes when the subject has children and every one is done in its own pipeline."""

    name = "children_done"
    DESCRIBE = DESCRIBE_CHILDREN_DONE

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Positions of the children; facts done, total, open and reason on FAIL.

        A subject the field leads back to from itself is in a cycle: UNKNOWN.
        """
        from .position import position
        chain = list(ancestors(ctx, subject, self.field))
        if subject.id in chain:
            cycle = [subject.id, *chain[:chain.index(subject.id) + 1]]
            return unknown(f"cycle: {CHAIN_SEPARATOR.join(cycle)}")
        evaluating = EVALUATING.get()
        if subject.id in evaluating:
            return unknown(f"cycle: {subject.id}")
        try:
            children = self.children(ctx, subject)
        except KeyError as exc:
            return unknown_pipeline(exc)
        token = EVALUATING.set(evaluating | {subject.id})
        try:
            done = {child.id for pipeline, child in children
                    if is_done(position(ctx, pipeline, child))}
        finally:
            EVALUATING.reset(token)
        still = [child.id for _, child in children if child.id not in done]
        facts = {FACT_DONE: len(children) - len(still), FACT_TOTAL: len(children),
                 FACT_OPEN: IDS_SEPARATOR.join(still)}
        if not children:
            return Result(Status.FAIL, {**facts, FACT_REASON: REASON_NONE})
        if still:
            return Result(Status.FAIL, {**facts, FACT_REASON: REASON_OPEN})
        return Result(Status.PASS, facts)


class RefExistsGate(Gate):
    """Passes when a frontmatter field names an existing subject of one of the pipelines."""

    name = "ref_exists"
    PARAMS = frozenset({PARAM_FIELD, PARAM_PIPELINES})
    REQUIRED = frozenset({PARAM_FIELD, PARAM_PIPELINES})

    def check(self) -> None:
        """Field is a string; pipelines is a non-empty list of names."""
        self.require_type(PARAM_FIELD, str, "a string")
        check_pipelines(self)

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Look the reference up; facts value, pipeline on PASS, reason on FAIL."""
        value = relation_field(subject, self.params[PARAM_FIELD])
        if not value:
            return Result(Status.FAIL, {FACT_VALUE: value, FACT_REASON: REASON_MISSING})
        try:
            found = find_subject(ctx, named_pipelines(ctx, self.params[PARAM_PIPELINES]), value)
        except KeyError as exc:
            return unknown_pipeline(exc, value=value)
        if found is None:
            return Result(Status.FAIL, {FACT_VALUE: value, FACT_REASON: REASON_UNKNOWN})
        return Result(Status.PASS, {FACT_VALUE: value, FACT_PIPELINE: found[0].name})

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """The field names a subject of the pipelines."""
        return locale.text(DESCRIBE_REF_EXISTS, field=params[PARAM_FIELD],
                           pipelines=IDS_SEPARATOR.join(params[PARAM_PIPELINES]))


class QuestionsAnsweredGate(Gate):
    """Passes when every question of the questions file has an answer, or the file says none."""

    name = "questions_answered"
    PARAMS = frozenset({PARAM_FILE})

    def check(self) -> None:
        """File is a string."""
        self.require_type(PARAM_FILE, str, "a string")

    def evaluate(self, ctx: Context, subject: Subject) -> Result:
        """Read the file under the subject; facts total, count (unanswered), reason on FAIL."""
        base = subject_dir(subject)
        path = base / self.params.get(PARAM_FILE, DEFAULT_QUESTIONS_FILE) if base else None
        if path is None or not path.is_file():
            return Result(Status.FAIL, {FACT_TOTAL: 0, FACT_COUNT: 0,
                                        FACT_REASON: REASON_MISSING})
        found = parse_questions(path.read_text(encoding=ENCODING))
        facts = {FACT_TOTAL: len(found.items), FACT_COUNT: len(found.unanswered)}
        if found.none:
            return Result(Status.PASS, facts)
        if not found.items:
            return Result(Status.FAIL, {**facts, FACT_REASON: REASON_EMPTY})
        if found.unanswered:
            return Result(Status.FAIL, {**facts, FACT_REASON: REASON_UNANSWERED})
        return Result(Status.PASS, facts)

    def describe(self, params: dict[str, Any], locale: Locale) -> str:
        """Every question in the file is answered, or the file says none."""
        return locale.text(DESCRIBE_QUESTIONS_ANSWERED,
                           file=params.get(PARAM_FILE, DEFAULT_QUESTIONS_FILE))


CORE_GATES = {cls.name: cls for cls in (
    ExistsGate, ArtifactGate, ApprovalGate, FieldGate, DocTypeGate, ArchivedGate, GitPushedGate,
    ChildrenDoneGate, HasChildrenGate, RefExistsGate, QuestionsAnsweredGate,
)}


def load_module(path: Path) -> ModuleType:
    """Import a profile gate module from its file path."""
    spec = importlib.util.spec_from_file_location(f"{MODULE_PREFIX}{path.stem}", path)
    # A spec or loader of None raises here; load_profile reports it as a failed import.
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def registered(path: Path, table: dict[str, Any], base: type[Configurable], core: dict[str, Any],
               found: dict[str, Any], errors: list[str]) -> None:
    """Add the classes of one module mapping to found; record every problem in errors."""
    for name, cls in table.items():
        if not (isinstance(cls, type) and issubclass(cls, base)):
            errors.append(f"{path}: {name}: not a {base.__name__} subclass")
        elif cls.name != name:
            errors.append(f"{path}: {name}: class declares name {cls.name!r}")
        elif name in core or name in found:
            errors.append(f"{path}: {name}: {base.__name__.lower()} name already registered")
        else:
            found[name] = cls


def load_profile(
        profile_dir: Path) -> tuple[dict[str, type[Gate]], dict[str, type[Provider]]]:
    """(gates, providers) declared by GATES and the optional PROVIDERS of the profile modules."""
    from .providers import CORE_PROVIDERS, Provider
    directory = profile_dir / GATES_DIR
    if not directory.is_dir():
        return {}, {}
    gates: dict[str, type[Gate]] = {}
    providers: dict[str, type[Provider]] = {}
    errors: list[str] = []
    for path in sorted(directory.glob(GATES_GLOB)):
        if path.name.startswith(PRIVATE_PREFIX):
            continue
        try:
            module = load_module(path)
        except Exception as exc:
            errors.append(f"{path}: import failed: {exc!r}")
            continue
        table = getattr(module, GATES_ATTR, None)
        if not isinstance(table, dict):
            errors.append(f"{path}: {GATES_ATTR} mapping of name to gate class is required")
            continue
        registered(path, table, Gate, CORE_GATES, gates, errors)
        extra = getattr(module, PROVIDERS_ATTR, {})
        if not isinstance(extra, dict):
            errors.append(f"{path}: {PROVIDERS_ATTR} must map names to provider classes")
            continue
        registered(path, extra, Provider, CORE_PROVIDERS, providers, errors)
    if errors:
        raise LoadError(errors)
    return gates, providers


def build_registries(
        profile_dir: Path) -> tuple[dict[str, type[Gate]], dict[str, type[Provider]]]:
    """(gate registry, provider registry): the core ones plus those of the profile."""
    from .providers import CORE_PROVIDERS
    gates, providers = load_profile(profile_dir)
    return {**CORE_GATES, **gates}, {**CORE_PROVIDERS, **providers}


from . import command_gate  # noqa: E402,F401  registers the command gate in CORE_GATES
