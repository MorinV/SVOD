"""Provider of single documents with frontmatter."""
from ..frontmatter import read_frontmatter
from ..subject import ATTR_FRONTMATTER, Subject
from .base import (ARCHIVED_STATUS, FIELD_STATUS, Provider, author_of, normalize_name,
                   read_text, relative)

PARAM_GLOB = "glob"
PARAM_EXCLUDE = "exclude"


class FrontmatterDocProvider(Provider):
    """Markdown files under a glob, one subject per file."""

    name = "frontmatter_doc"
    PARAMS = frozenset({PARAM_GLOB, PARAM_EXCLUDE})
    REQUIRED = frozenset({PARAM_GLOB})

    def check(self):
        """Glob is a string; exclude is a list of file names."""
        self.require_type(PARAM_GLOB, str, "a string")
        self.require_type(PARAM_EXCLUDE, list, "a list")

    def select(self, ctx, accept):
        """Subjects of documents with frontmatter whose normalized stem satisfies accept."""
        excluded = set(self.params.get(PARAM_EXCLUDE, []))
        found = []
        for path in sorted(ctx.root.glob(self.params[PARAM_GLOB])):
            if not path.is_file() or path.name in excluded:
                continue
            if not accept(normalize_name(path.stem)):
                continue
            frontmatter = read_frontmatter(path)
            if frontmatter is None:
                continue
            rel = relative(ctx, path)
            found.append(Subject(
                id=path.stem,
                path=path,
                archived=frontmatter.get(FIELD_STATUS) == ARCHIVED_STATUS,
                keys=self.keys_in(read_text(path)),
                author_of=author_of(ctx, rel),
                attrs={ATTR_FRONTMATTER: frontmatter},
            ))
        return found

    def enumerate(self, ctx):
        """Every document under the glob."""
        return self.select(ctx, lambda name: True)

    def match_exact(self, query, ctx):
        """Documents whose stem equals the query."""
        wanted = normalize_name(query)
        return self.select(ctx, lambda name: name == wanted)

    def match_substring(self, query, ctx):
        """Documents whose stem contains the query."""
        wanted = normalize_name(query)
        return self.select(ctx, lambda name: wanted in name)
