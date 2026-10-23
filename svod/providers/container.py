"""Provider of container directories."""
from ..errors import ParamError
from ..frontmatter import DOC_GLOB, documents, read_frontmatter
from ..subject import ATTR_CONTAINER, ATTR_FRONTMATTER, Subject
from .base import (ARCHIVED_STATUS, FIELD_STATUS, Provider, author_of, normalize_name,
                   read_text, relative)

PARAM_ROOTS = "roots"
PARAM_HEAD_TYPE = "head_type"
FIELD_TYPE = "type"
KEY_INDEX = "key_index"


def container_dirs(ctx, roots):
    """Container directories under the roots, in root order then by name."""
    seen = set()
    for root in roots:
        bases = sorted(ctx.root.glob(root)) if any(c in root for c in "*?[") else [ctx.root / root]
        for base in bases:
            if base.is_dir():
                for path in sorted(p for p in base.iterdir() if p.is_dir()):
                    if path not in seen:
                        seen.add(path)
                        yield path


def key_index(ctx, roots, key_gate):
    """Tracker key to the first container whose documents mention it; read once per run."""
    if key_gate is None:
        return {}
    return ctx.cache.value((KEY_INDEX, str(ctx.root), tuple(roots), id(key_gate)),
                           lambda: read_key_index(ctx, roots, key_gate))


def read_key_index(ctx, roots, key_gate):
    """Tracker key to the first container whose documents mention it, read from the documents."""
    index = {}
    for path in container_dirs(ctx, roots):
        rel = relative(ctx, path)
        for doc in documents(path):
            for key in key_gate.find(read_text(doc)):
                index.setdefault(key, rel)
    return index


class ContainerProvider(Provider):
    """Directories directly under the configured roots."""

    name = "container"
    PARAMS = frozenset({PARAM_ROOTS, PARAM_HEAD_TYPE})
    REQUIRED = frozenset({PARAM_ROOTS})

    def check(self):
        """Roots is a non-empty list of strings; head type is a string."""
        roots = self.params[PARAM_ROOTS]
        if not isinstance(roots, list) or not roots or not all(isinstance(r, str) for r in roots):
            raise ParamError(f"{self.name}: {PARAM_ROOTS} must be a non-empty list of strings")
        self.require_type(PARAM_HEAD_TYPE, str, "a string")

    def creation_target(self, ctx, record):
        """Default placement under the first literal root; patterns are discovery only."""
        root = self.params[PARAM_ROOTS][0]
        if any(c in root for c in "*?["):
            return None
        return ctx.root / root.strip("/") / record.name

    def head(self, path):
        """Frontmatter of the top-level document of the head type, or an empty mapping."""
        head_type = self.params.get(PARAM_HEAD_TYPE)
        if not head_type:
            return {}
        for doc in sorted(path.glob(DOC_GLOB)):
            frontmatter = read_frontmatter(doc)
            if frontmatter and frontmatter.get(FIELD_TYPE) == head_type:
                return frontmatter
        return {}

    def subject(self, ctx, path):
        """Subject of one container directory."""
        rel = relative(ctx, path)
        frontmatter = self.head(path)
        keys = frozenset().union(*(self.keys_in(read_text(d)) for d in documents(path)))
        return Subject(
            id=rel,
            path=path,
            archived=frontmatter.get(FIELD_STATUS) == ARCHIVED_STATUS,
            keys=keys,
            author_of=author_of(ctx, rel),
            attrs={ATTR_CONTAINER: rel, ATTR_FRONTMATTER: frontmatter},
        )

    def select(self, ctx, accept):
        """Subjects of the containers whose normalized name satisfies accept."""
        return [self.subject(ctx, p) for p in container_dirs(ctx, self.params[PARAM_ROOTS])
                if accept(normalize_name(p.name))]

    def enumerate(self, ctx):
        """Every container."""
        return self.select(ctx, lambda name: True)

    def match_exact(self, query, ctx):
        """Containers addressed by their short name or exact store-relative path."""
        wanted = normalize_name(query)
        if "/" in wanted:
            return [self.subject(ctx, path)
                    for path in container_dirs(ctx, self.params[PARAM_ROOTS])
                    if normalize_name(relative(ctx, path)) == wanted]
        return self.select(ctx, lambda name: name == wanted)

    def match_substring(self, query, ctx):
        """Containers whose name contains the query."""
        wanted = normalize_name(query)
        return self.select(ctx, lambda name: wanted in name)
