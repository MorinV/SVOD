"""Base class of subject providers and helpers they share."""
import unicodedata

from ..params import Configurable
from ..yamlio import ENCODING

NORMAL_FORM = "NFC"
FIELD_STATUS = "status"
ARCHIVED_STATUS = "archived"
AUTHOR_FORMAT = "--format=%ae%n%an"
AUTHOR_PARTS = 2
PATH_SEPARATOR = "/"


def normalize_name(name):
    """Name comparable across Unicode forms and letter case."""
    return unicodedata.normalize(NORMAL_FORM, name).casefold()


def read_text(path):
    """File text, or an empty string when unreadable."""
    try:
        with open(path, encoding=ENCODING) as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def last_author(ctx, path):
    """(email, name) of the last commit touching the path, or None without data."""
    out = ctx.cache.git(ctx.root, "log", "-1", AUTHOR_FORMAT, "--", str(path))
    parts = out.out.split("\n") if out.ok else []
    if len(parts) < AUTHOR_PARTS or not parts[0]:
        return None
    return parts[0].casefold(), parts[1]


def author_of(ctx, path):
    """Reader of the last author of the path, run when the author is first asked for."""
    return lambda: last_author(ctx, path)


def relative(ctx, path):
    """Path relative to the store root in POSIX form."""
    return path.relative_to(ctx.root).as_posix()


def covers(rel, paths):
    """Whether any of the relative paths is rel itself or lies under it, in any Unicode form."""
    rel = unicodedata.normalize(NORMAL_FORM, rel)
    prefix = rel + PATH_SEPARATOR
    return any(p == rel or p.startswith(prefix)
               for p in (unicodedata.normalize(NORMAL_FORM, p) for p in paths))


class Provider(Configurable):
    """Finds subjects of one kind in the store."""

    def __init__(self, params=None, key_gate=None):
        """Validate params and keep the key gate used to read tracker keys."""
        self.key_gate = key_gate
        super().__init__(params)

    def keys_in(self, text):
        """Tracker keys mentioned in the text, empty without a key gate."""
        return frozenset(self.key_gate.find(text)) if self.key_gate else frozenset()

    def enumerate(self, ctx):
        """Every subject of this kind, for the active summary."""
        raise NotImplementedError

    def touched(self, ctx, paths):
        """Subjects with a file among paths, given relative to the store root in POSIX form."""
        return [s for s in self.enumerate(ctx)
                if s.path is not None and covers(relative(ctx, s.path), paths)]

    def evidence(self, ctx, subject):
        """Paths relative to the root that ground the subject: its own path when it has one."""
        return [relative(ctx, subject.path)] if subject.path is not None else []

    def match_exact(self, query, ctx):
        """Subjects whose name equals the query."""
        return []

    def match_key(self, key, ctx):
        """Subjects addressed by a tracker key."""
        return []

    def match_substring(self, query, ctx):
        """Subjects whose name contains the query."""
        return []

    def resolve(self, query, ctx):
        """Exact name first, then tracker key, then substring."""
        exact = self.match_exact(query, ctx)
        if exact:
            return exact
        key = self.key_gate.match(query) if self.key_gate else None
        found = self.match_key(key, ctx) if key else []
        return found or self.match_substring(query, ctx)
