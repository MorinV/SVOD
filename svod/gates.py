"""Gates: named checks over a subject, core set and registry."""
import datetime as dt
import importlib.util
import re
from dataclasses import dataclass, field
from enum import Enum

from .approval import digest_matches, field_names
from .errors import LoadError, ParamError
from .frontmatter import documents, read_frontmatter
from .keys import (
    DESCRIBE_PREFIX, DESCRIBE_EXISTS, DESCRIBE_ARTIFACT_PATH, DESCRIBE_ARTIFACT_GLOB,
    DESCRIBE_APPROVAL, DESCRIBE_APPROVAL_BOUND, DESCRIBE_FIELD_EQUALS, DESCRIBE_FIELD_NOT_EQUALS,
    DESCRIBE_FIELD_PRESENT, DESCRIBE_FIELD_ABSENT, DESCRIBE_FIELD_DATE_NOT_PAST,
    DESCRIBE_FIELD_DATE_PAST,
    DESCRIBE_DOC_TYPE, DESCRIBE_DOC_TYPE_CONTAINER, DESCRIBE_ARCHIVED, DESCRIBE_GIT_PUSHED,
    DESCRIBE_GIT_PUSHED_REPO,
)
from .params import Configurable
from .subject import ATTR_CONTAINER, ATTR_FRONTMATTER
from .yamlio import read_yaml

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
LINE_RULES = (PARAM_IGNORE, PARAM_STRIP)
FACT_REASON = "reason"
FACT_VALUE = "value"
FACT_MARKER = "marker"
FACT_BY = "by"
FACT_DATE = "date"
REASON_MISSING = "missing"
REASON_LEGACY = "legacy"
REASON_DRIFT = "drift"
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
    facts: dict = field(default_factory=dict)
    display: str | None = None
    reason: str | None = None

    @property
    def passed(self):
        """Whether the gate passed."""
        return self.status is Status.PASS


def verdict(ok, **facts):
    """PASS or FAIL result with facts."""
    return Result(Status.PASS if ok else Status.FAIL, facts)


def unknown(reason, **facts):
    """UNKNOWN result: the check could not be performed."""
    return Result(Status.UNKNOWN, facts, reason=reason)


def subject_dir(subject):
    """Artifact root of an existing subject, or None."""
    if not subject.exists or subject.path is None:
        return None
    return subject.path


class Gate(Configurable):
    """Named check over a subject."""

    def evaluate(self, ctx, subject):
        """Result of the check for the subject."""
        raise NotImplementedError

    def describe(self, params, locale):
        """What must hold for the gate to pass, from the locale key gate.<name> and the params."""
        return locale.text(f"{DESCRIBE_PREFIX}{self.name}", **params)


class KeyGate(Gate):
    """Gate that also recognises tracker keys in queries and texts."""

    def match(self, query):
        """Tracker key named by the query, or None."""
        raise NotImplementedError

    def find(self, text):
        """Set of tracker keys mentioned in the text."""
        raise NotImplementedError

    def evaluate(self, ctx, subject):
        """Passes when the subject carries at least one tracker key."""
        return verdict(bool(subject.keys), keys=KEYS_SEPARATOR.join(sorted(subject.keys)))


class ExistsGate(Gate):
    """Passes when the subject was found."""

    name = "exists"

    def evaluate(self, ctx, subject):
        """PASS when the provider found the subject."""
        return verdict(subject.exists)

    def describe(self, params, locale):
        """The subject was found."""
        return locale.text(DESCRIBE_EXISTS)


class ArtifactGate(Gate):
    """Passes when a path exists under the subject or a glob matches enough entries."""

    name = "artifact"
    PARAMS = frozenset({PARAM_PATH, PARAM_GLOB, PARAM_MIN})

    def check(self):
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

    def evaluate(self, ctx, subject):
        """Count matching files under the subject; facts.count."""
        base = subject_dir(subject)
        count = 0
        if base is not None and base.is_dir():
            if PARAM_PATH in self.params:
                count = int((base / self.params[PARAM_PATH]).exists())
            else:
                count = sum(1 for _ in base.glob(self.params[PARAM_GLOB]))
        return verdict(count >= self.params.get(PARAM_MIN, DEFAULT_MIN), count=count)

    def describe(self, params, locale):
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

    def check(self):
        """Marker and file are strings; bind and the line rules are non-empty lists."""
        self.require_type(PARAM_MARKER, str, "a string")
        self.require_type(PARAM_FILE, str, "a string")
        bind = self.params.get(PARAM_BIND)
        if bind is not None and not non_empty_strings(bind):
            raise ParamError(f"{self.name}: {PARAM_BIND} must be a non-empty list of globs")
        for rule in LINE_RULES:
            self.check_line_rule(rule, bind)

    def check_line_rule(self, rule, bind):
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
                                 f"expression: {exc}")

    def failed(self, reason, **facts):
        """FAIL with the reason among the facts."""
        return Result(Status.FAIL, {**facts, FACT_REASON: reason})

    def evaluate(self, ctx, subject):
        """Read the approval fields; facts.value, marker, by, date and reason on failure."""
        marker = self.params[PARAM_MARKER]
        empty = {FACT_VALUE: "", FACT_MARKER: marker, FACT_BY: "", FACT_DATE: ""}
        base = subject_dir(subject)
        path = base / self.params[PARAM_FILE] if base is not None else None
        if path is None or not path.is_file():
            return self.failed(REASON_MISSING, **empty)
        try:
            data = read_yaml(path)
        except LoadError as exc:
            return unknown(str(exc), **empty)
        data = data if isinstance(data, dict) else {}
        date_field, by_field, sha_field = field_names(marker)
        value, by, sha = (text_of(data.get(f)) for f in (date_field, by_field, sha_field))
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

    def describe(self, params, locale):
        """The marker is set in the file, for the current bound files when bound."""
        if params.get(PARAM_BIND):
            return locale.text(DESCRIBE_APPROVAL_BOUND, marker=params[PARAM_MARKER],
                               file=params[PARAM_FILE],
                               bind=BIND_SEPARATOR.join(params[PARAM_BIND]))
        return locale.text(DESCRIBE_APPROVAL, marker=params[PARAM_MARKER], file=params[PARAM_FILE])


def non_empty_strings(value):
    """Whether the value is a non-empty list of non-blank strings."""
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value)


def text_of(value):
    """Stripped text of a field value; empty for a missing one."""
    return "" if value is None else str(value).strip()


class FieldGate(Gate):
    """Condition on one frontmatter field of the subject; an empty field never equals or differs."""

    name = "field"
    PARAMS = frozenset({PARAM_NAME, *FIELD_CONDITIONS})
    REQUIRED = frozenset({PARAM_NAME})

    def check(self):
        """Exactly one condition; boolean conditions are booleans."""
        given = [c for c in FIELD_CONDITIONS if c in self.params]
        if len(given) != 1:
            raise ParamError(f"{self.name}: exactly one of {', '.join(FIELD_CONDITIONS)}")
        self.require_type(PARAM_NAME, str, "a string")
        self.require_type(PARAM_DATE_NOT_PAST, bool, "a boolean")
        self.require_type(PARAM_PRESENT, bool, "a boolean")

    def evaluate(self, ctx, subject):
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

    def describe(self, params, locale):
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

    def check(self):
        """Scope is one of the known scopes."""
        self.require_type(PARAM_TYPE, str, "a string")
        if self.params.get(PARAM_SCOPE, SCOPE_SUBJECT) not in SCOPES:
            raise ParamError(f"{self.name}: {PARAM_SCOPE} must be one of {', '.join(SCOPES)}")

    def evaluate(self, ctx, subject):
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

    def describe(self, params, locale):
        """A document of the type in the subject or in its container."""
        key = (DESCRIBE_DOC_TYPE_CONTAINER if params.get(PARAM_SCOPE) == SCOPE_CONTAINER
               else DESCRIBE_DOC_TYPE)
        return locale.text(key, type=params[PARAM_TYPE])


class ArchivedGate(Gate):
    """Passes when the subject is archived."""

    name = "archived"

    def evaluate(self, ctx, subject):
        """PASS when the provider marked the subject archived."""
        return verdict(subject.archived)

    def describe(self, params, locale):
        """The subject is archived."""
        return locale.text(DESCRIBE_ARCHIVED)


class GitPushedGate(Gate):
    """Passes when a repository has no commits ahead of the default branch."""

    name = "git_pushed"
    PARAMS = frozenset({PARAM_REPO})

    def check(self):
        """Repo is a string path."""
        self.require_type(PARAM_REPO, str, "a string")

    def evaluate(self, ctx, subject):
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

    def describe(self, params, locale):
        """No commits ahead of the default branch in the store or the given repository."""
        if PARAM_REPO in params:
            return locale.text(DESCRIBE_GIT_PUSHED_REPO, repo=params[PARAM_REPO])
        return locale.text(DESCRIBE_GIT_PUSHED)


CORE_GATES = {cls.name: cls for cls in (
    ExistsGate, ArtifactGate, ApprovalGate, FieldGate, DocTypeGate, ArchivedGate, GitPushedGate,
)}


def load_module(path):
    """Import a profile gate module from its file path."""
    spec = importlib.util.spec_from_file_location(f"{MODULE_PREFIX}{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registered(path, table, base, core, found, errors):
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


def load_profile(profile_dir):
    """(gates, providers) declared by GATES and the optional PROVIDERS of the profile modules."""
    from .providers import CORE_PROVIDERS, Provider
    directory = profile_dir / GATES_DIR
    if not directory.is_dir():
        return {}, {}
    gates, providers, errors = {}, {}, []
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


def build_registries(profile_dir):
    """(gate registry, provider registry): the core ones plus those of the profile."""
    from .providers import CORE_PROVIDERS
    gates, providers = load_profile(profile_dir)
    return {**CORE_GATES, **gates}, {**CORE_PROVIDERS, **providers}


def build_registry(profile_dir):
    """Gate registry: core gates plus profile gates, name to class."""
    return build_registries(profile_dir)[0]
