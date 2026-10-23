"""Work records: container directories whose card.md frontmatter decides the steps that apply.

A record is work/<kind>/<name>/ with card.md (frontmatter type: card). Besides the container
attributes it carries the booleans pipelines name in `when`:
  hotfix        kind: hotfix (a task that skips the contract and its approval)
  planned       any other kind
  to_work       research outcome task, research or hotfix (leads_to names the record)
  to_knowledge  research outcome knowledge (knowledge names the document)
Its keys are the `key` of card.md (a tracker key), when set.

Code freeze. A step with blocks_code (the task contract approval) keeps the agent out of the
worktrees of the record until it passes; the pre-tool hook finds them through two gates:
  work_tree  workspace_gate of svod.yaml: the worktrees work.yaml of a record lists, one
             `<service>: <directory>` line each, relative to the store root (start-task.sh)
  work_id    key_gate of the task pipeline: the record a worktree directory name names
Naming of a worktree. start-task.sh names it <service>-<pipeline>-<name> next to the service
checkout, on the branch <pipeline>/<name>: ../app-task-login for work/tasks/login. A service
or a record name may hold "-", so work_id reads every "-<pipeline>-" of the directory name as
a possible boundary and names every record id it could mean; work_tree keeps only those whose
work.yaml lists that directory. A directory with no "-<pipeline>-" names no record and is not
frozen.
"""
from pathlib import Path
from unicodedata import normalize

from svod.errors import LoadError
from svod.gates import Gate, KeyGate, Result, Status
from svod.providers.base import NORMAL_FORM, normalize_name
from svod.providers.container import ContainerProvider
from svod.subject import ATTR_FRONTMATTER
from svod.yamlio import ENCODING, parse_yaml

FIELD_KIND = "kind"
FIELD_KEY = "key"
FIELD_OUTCOME = "outcome"
KIND_HOTFIX = "hotfix"
OUTCOMES_TO_WORK = frozenset({"hotfix", "task", "research"})
OUTCOME_KNOWLEDGE = "knowledge"
WORK_FILE = "work.yaml"
ID_SEPARATOR = "/"
SLUG_SEPARATOR = "+"
# Pipeline name in a worktree directory name -> root directory of its records.
ROOTS = {"task": "work/tasks", "feature": "work/features", "project": "work/projects",
         "research": "work/research"}
NAME_SEPARATOR = "-"
FACT_COUNT = "count"
FACT_WORKTREES = "worktrees"
ITEM_SEPARATOR = ", "
NOT_MAPPING = "{file}: not a mapping of service to directory"


def text(frontmatter, name):
    """Stripped string value of a frontmatter field, empty when absent."""
    value = frontmatter.get(name)
    return "" if value is None else str(value).strip()


def id_slug(record_id):
    """The id-slug of a record id: work/tasks/login is work+tasks+login."""
    return record_id.strip(ID_SEPARATOR).replace("%", "%25").replace("+", "%2B").replace(
        ID_SEPARATOR, SLUG_SEPARATOR)


def slug_id(key):
    """The record id an id-slug names; an id stays as it is."""
    if ID_SEPARATOR in key:
        return key
    return key.replace(SLUG_SEPARATOR, ID_SEPARATOR).replace("%2B", "+").replace("%25", "%")


def record_ids(text):
    """Record ids a worktree directory name may mean, a word read as a path by its last part.

    <service>-<pipeline>-<name> names work/<root of pipeline>/<name>; with "-" allowed in the
    service and the name, every "-<pipeline>-" is tried, in order of appearance.
    """
    found = []
    for word in text.split():
        name = word.rstrip(ID_SEPARATOR).rsplit(ID_SEPARATOR, 1)[-1]
        for pipeline, root in ROOTS.items():
            marker = f"{NAME_SEPARATOR}{pipeline}{NAME_SEPARATOR}"
            start = name.find(marker)
            while start > 0:
                rest = name[start + len(marker):]
                if rest.startswith("work+"):
                    found.append(slug_id(rest))
                elif rest and NAME_SEPARATOR * 2 not in rest:
                    found.append(f"{root}{ID_SEPARATOR}{rest}")
                start = name.find(marker, start + 1)
    return list(dict.fromkeys(found))


class WorkProvider(ContainerProvider):
    """The container provider plus the when-attributes and the tracker key of a work record."""

    name = "work"

    def owns_path(self, ctx, subject, path):
        """Owner documents exclude the live child containers, including moved children."""
        if not super().owns_path(ctx, subject, path):
            return False
        # Match covers()' canonical equivalence without casefolding filesystem paths.
        owner = normalize(NORMAL_FORM, subject.path.relative_to(ctx.root).as_posix())
        relative = Path(normalize(NORMAL_FORM, str(path))).relative_to(owner)
        frontmatter = subject.attrs.get(ATTR_FRONTMATTER) or {}
        kind = text(frontmatter, FIELD_KIND)
        children = {"tasks", "research", "features"} if kind == "project" else {"tasks", "research"}
        return not (kind in {"project", "feature"} and relative.parts
                    and relative.parts[0] in children)

    def creation_target(self, ctx, record):
        """Standard placement; research parent is provenance, never a container."""
        from fnmatch import fnmatchcase

        opted_in = any("*" in root or root.startswith("work/headless/")
                       for root in self.params["roots"])
        if not opted_in:
            return super().creation_target(ctx, record)

        def resolve_parent(ref):
            matches = {s.id: (p, s) for p in ctx.pipelines.values()
                       for s in p.subject.impl.match_exact(ref, ctx) if s.exists}
            if len(matches) != 1:
                raise ValueError(f"Parent must resolve to one record: {ref}")
            return next(iter(matches.values()))

        kind = record.kind or record.pipeline
        if kind not in ({"task", "hotfix"} if record.pipeline == "task" else {record.pipeline}):
            raise ValueError(f"Invalid kind {kind!r} for pipeline {record.pipeline!r}")
        owner = None
        if record.parent:
            parent_pipeline, parent = resolve_parent(record.parent)
            record.parent = parent.id
            visited = set()
            while parent_pipeline.name == "research" and record.pipeline in {"task", "research"}:
                if parent.id in visited:
                    raise ValueError(f"Research parent cycle: {parent.id}")
                visited.add(parent.id)
                # Prefer the physical owner; a research's logical parent is provenance.
                owners = [(p, s) for p in ctx.pipelines.values() if p.name in {"project", "feature"}
                          for s in p.subject.impl.enumerate(ctx)
                          if s.exists and parent.path.is_relative_to(s.path)]
                if owners:
                    parent_pipeline, parent = max(owners, key=lambda pair: len(pair[1].path.parts))
                    break
                ref = text(parent.attrs.get(ATTR_FRONTMATTER) or {}, "parent")
                if not ref:
                    break
                parent_pipeline, parent = resolve_parent(ref)
            if parent_pipeline.name in {"project", "feature"}:
                owner = parent
            elif parent_pipeline.name != "research" or record.pipeline not in {"task", "research"}:
                raise ValueError(f"Invalid parent for {record.pipeline}: {parent.id}")
        if record.pipeline == "task" and kind == "hotfix":
            root = "work/hotfix"
        elif record.pipeline in {"task", "research"}:
            container = "tasks" if record.pipeline == "task" else "research"
            root = f"{owner.id}/{container}" if owner else f"work/headless/{container}"
        elif record.pipeline == "feature":
            if owner is not None and parent_pipeline.name != "project":
                raise ValueError("A feature parent must be a project")
            root = f"{owner.id}/features" if owner else "work/features"
        else:
            if owner is not None:
                raise ValueError("A project cannot have a parent")
            root = "work/projects"
        # Compare segments: '*' must not accidentally accept additional hierarchy levels.
        def accepts(pattern):
            parts, actual = pattern.split("/"), root.split("/")
            return len(parts) == len(actual) and all(
                fnmatchcase(a, p) for a, p in zip(actual, parts, strict=True))
        if not any(accepts(pattern) for pattern in self.params["roots"]):
            raise ValueError(f"Creation target is outside provider roots: {root}")
        return ctx.root / root / record.name

    def subject(self, ctx, path):
        """Container subject with hotfix, planned, to_work and to_knowledge attributes.

        Its keys are the key of card.md alone: what the key gate finds in the documents is not
        a key of the record.
        """
        subject = super().subject(ctx, path)
        frontmatter = subject.attrs.get(ATTR_FRONTMATTER) or {}
        hotfix = text(frontmatter, FIELD_KIND) == KIND_HOTFIX
        outcome = text(frontmatter, FIELD_OUTCOME)
        key = text(frontmatter, FIELD_KEY)
        subject.keys = frozenset({key}) if key else frozenset()
        subject.attrs.update(hotfix=hotfix, planned=not hotfix,
                             to_work=outcome in OUTCOMES_TO_WORK,
                             to_knowledge=outcome == OUTCOME_KNOWLEDGE)
        return subject

    def match_key(self, key, ctx):
        """The record whose id (or id-slug) the key names; a tracker key is matched elsewhere."""
        if SLUG_SEPARATOR in key or ID_SEPARATOR in key:
            return self.match_exact(slug_id(key), ctx)
        return []


class WorkIdGate(KeyGate):
    """Records a worktree directory name may mean: app-task-login names work/tasks/login."""

    name = "work_id"

    def match(self, query):
        """The record id the query is, else the first one a directory name in it may mean."""
        wanted = query.strip().strip(ID_SEPARATOR)
        if wanted.startswith("work/"):
            return wanted
        if wanted.startswith("work+"):
            return slug_id(wanted)
        found = record_ids(query)
        return found[0] if found else None

    def find(self, text):
        """Record ids the text may name; work_tree keeps the one whose work.yaml agrees."""
        return set(record_ids(text))


def listed(ctx, subject):
    """((directory, service) of every existing worktree work.yaml of the record lists, error).

    A relative directory is read from the root of the checkout the record lives in.
    """
    path = subject.path / WORK_FILE if subject.path is not None else None
    if path is None or not path.is_file():
        return [], None
    shown = path.relative_to(ctx.root).as_posix() if path.is_relative_to(ctx.root) else str(path)
    try:
        data = parse_yaml(path.read_text(encoding=ENCODING), shown)
    except (OSError, UnicodeDecodeError) as exc:
        return [], f"{shown}: {exc}"
    except LoadError as exc:
        return [], exc.errors[0]
    if data is None:
        return [], None
    if not isinstance(data, dict):
        return [], NOT_MAPPING.format(file=shown)
    root = subject.checkout or ctx.root
    found = []
    for service, value in data.items():
        if isinstance(value, str) and value.strip():
            directory = Path(root, value.strip()).resolve()
            if directory.is_dir():
                found.append((directory, str(service)))
    return found, None


class WorkTreeGate(Gate):
    """The worktrees work.yaml of the record lists; workspace_gate of the code freeze."""

    name = "work_tree"

    @staticmethod
    def records(ctx):
        """Every record of the pipelines of the work provider, each once."""
        seen = {}
        for pipeline in (ctx.pipelines or {}).values():
            provider = pipeline.subject.impl
            if isinstance(provider, WorkProvider):
                for subject in provider.enumerate(ctx):
                    seen.setdefault(subject.id, subject)
        return list(seen.values())

    def worktrees(self, ctx, keys):
        """((directory, service) of the records the keys name, errors of their work.yaml).

        A key names a record by its id, its id-slug or the key of its card.md.
        """
        wanted = {normalize_name(k) for k in keys}
        ids = {normalize_name(slug_id(k)) for k in keys}
        pairs, errors = [], []
        for subject in self.records(ctx):
            if (normalize_name(subject.id) in ids
                    or wanted & {normalize_name(k) for k in subject.keys}):
                found, error = listed(ctx, subject)
                pairs += found
                if error:
                    errors.append(error)
        return pairs, errors

    def evaluate(self, ctx, subject):
        """PASS when work.yaml of the record lists an existing worktree; facts count, worktrees.

        UNKNOWN when work.yaml does not read. A use in a pipeline needs a label: the profile
        locale has no gate.work_tree.
        """
        found, error = listed(ctx, subject)
        facts = {FACT_COUNT: len(found),
                 FACT_WORKTREES: ITEM_SEPARATOR.join(d.name for d, _ in found)}
        if error and not found:
            return Result(Status.UNKNOWN, facts, reason=error)
        return Result(Status.PASS if found else Status.FAIL, facts)


GATES = {cls.name: cls for cls in (WorkIdGate, WorkTreeGate)}
PROVIDERS = {WorkProvider.name: WorkProvider}
