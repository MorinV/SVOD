"""Provider of openspec changes, active and archived."""
from ..subject import ATTR_CONTAINER, Subject
from .base import Provider, author_of, covers, normalize_name, read_text, relative
from .container import key_index

PARAM_ROOT = "root"
PARAM_ARCHIVE = "archive"
PARAM_CONTAINERS = "containers"
PARAM_IGNORE_FIELDS = "ignore_fields"
DEFAULT_ROOT = "openspec/changes"
DEFAULT_ARCHIVE = "archive"
METADATA_FILE = ".openspec.yaml"
TASKS_FILE = "tasks.md"
TASK_HEADING = "## "
FIELD_SEPARATOR = ":"


class OpenspecChangeProvider(Provider):
    """Changes under the openspec store, matched by tracker key."""

    name = "openspec_change"
    PARAMS = frozenset({PARAM_ROOT, PARAM_ARCHIVE, PARAM_CONTAINERS, PARAM_IGNORE_FIELDS})

    def check(self):
        """Root and archive are strings; containers and ignored fields are lists."""
        self.require_type(PARAM_ROOT, str, "a string")
        self.require_type(PARAM_ARCHIVE, str, "a string")
        self.require_type(PARAM_CONTAINERS, list, "a list")
        self.require_type(PARAM_IGNORE_FIELDS, list, "a list")

    def change_dirs(self, ctx):
        """(path, archived) of every change: active first, then the archive."""
        root = ctx.root / self.params.get(PARAM_ROOT, DEFAULT_ROOT)
        archive_name = self.params.get(PARAM_ARCHIVE, DEFAULT_ARCHIVE)
        if not root.is_dir():
            return []
        active = [(p, False) for p in sorted(root.iterdir())
                  if p.is_dir() and p.name != archive_name]
        archive = root / archive_name
        if not archive.is_dir():
            return active
        return active + [(p, True) for p in sorted(archive.iterdir()) if p.is_dir()]

    def change_keys(self, path):
        """Keys from the metadata file, minus ignored fields, and from task headings."""
        ignored = tuple(f"{f}{FIELD_SEPARATOR}" for f in self.params.get(PARAM_IGNORE_FIELDS, []))
        keys = set()
        for line in read_text(path / METADATA_FILE).splitlines():
            if not line.startswith(ignored):
                keys |= self.keys_in(line)
        for line in read_text(path / TASKS_FILE).splitlines():
            if line.startswith(TASK_HEADING):
                keys |= self.keys_in(line)
        return frozenset(keys)

    def containers(self, ctx):
        """Tracker key to container index over the configured container roots."""
        return key_index(ctx, self.params.get(PARAM_CONTAINERS, []), self.key_gate)

    def subjects(self, ctx, dirs=None):
        """Subjects of every change, or of the given (path, archived) change directories."""
        index = self.containers(ctx)
        found = []
        for path, archived in self.change_dirs(ctx) if dirs is None else dirs:
            keys = self.change_keys(path)
            container = next((index[k] for k in sorted(keys) if k in index), None)
            found.append(Subject(
                id=path.name,
                path=path,
                archived=archived,
                keys=keys,
                author_of=author_of(ctx, relative(ctx, path)),
                attrs={ATTR_CONTAINER: container},
            ))
        return found

    def enumerate(self, ctx):
        """Every change, active and archived."""
        return self.subjects(ctx)

    def touched(self, ctx, paths):
        """Changes with a file among paths; only those are read, the rest are not enumerated."""
        dirs = [(p, a) for p, a in self.change_dirs(ctx) if covers(relative(ctx, p), paths)]
        return self.subjects(ctx, dirs) if dirs else []

    def evidence(self, ctx, subject):
        """The change directory; for a key without a change, the container mentioning it."""
        if subject.exists:
            return super().evidence(ctx, subject)
        container = subject.attrs.get(ATTR_CONTAINER)
        return [container] if container else []

    def match_exact(self, query, ctx):
        """Changes by directory name or exact store-relative path."""
        wanted = normalize_name(query)
        return [s for s in self.subjects(ctx)
                if normalize_name(s.id) == wanted
                or normalize_name(relative(ctx, s.path)) == wanted]

    def match_key(self, key, ctx):
        """All changes carrying the key; a not-found subject when there are none."""
        found = [s for s in self.subjects(ctx) if key in s.keys]
        if found:
            return found
        container = self.containers(ctx).get(key)
        return [Subject(id=key, path=None, exists=False, keys=frozenset({key}),
                        attrs={ATTR_CONTAINER: container})]
