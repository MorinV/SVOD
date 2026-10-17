"""Frontmatter of markdown documents."""
import datetime as dt

from .errors import LoadError
from .yamlio import ENCODING, parse_yaml

FENCE = "---"
OPENING = f"{FENCE}\n"
CLOSING = f"\n{FENCE}\n"
DOC_GLOB = "*.md"


def normalize(value):
    """Dates as ISO strings, everything else unchanged."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def read_frontmatter(path):
    """Frontmatter mapping of a document, or None when absent or unreadable."""
    try:
        with open(path, encoding=ENCODING) as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith(OPENING):
        return None
    end = text.find(CLOSING, len(OPENING) - 1)
    if end == -1:
        return None
    try:
        data = parse_yaml(text[len(OPENING):end], path)
    except LoadError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): normalize(v) for k, v in data.items()}


def documents(base):
    """Markdown files under a directory recursively, or the file itself."""
    if base.is_file():
        return [base]
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob(DOC_GLOB) if p.is_file())
