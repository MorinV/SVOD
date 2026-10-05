"""Plan approval: digest of the bound files, the mark a person leaves, the approval fields."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from .git import run_git
from .yamlio import ENCODING

MARK_FILE = "svod-approval.json"
MARK_AT = "at"
MARK_KEYS = "keys"
SUFFIX_BY = "_by"
SUFFIX_SHA = "_sha"
DIGEST_SEPARATOR = b"\0"
SECONDS_PER_MINUTE = 60
PLAIN_VALUE_RE = re.compile(r"^[A-Za-z0-9_.@+-]+$")
FIELD_LINE_RE = r"^{field}\s*:"
NEWLINE = "\n"
DECODE_ERRORS = "surrogateescape"
STRIPPED = ""
SINGLE_SPACE = " "
SEPARATOR_RUN_RE = re.compile(r"([,;])(?:\s*[,;])+")
SPACE_BEFORE_SEPARATOR_RE = re.compile(r"\s+(?=[,;.:])")
SEPARATOR_BEFORE_CLOSE_RE = re.compile(r"[\s,;]+(?=\))")
EMPTY_PARENS_RE = re.compile(r"\s*\(\s*\)")
WHITESPACE_RUN_RE = re.compile(r"\s+")
LEADING_SEPARATORS = " \t,;.:\u2013\u2014"
TRAILING_SEPARATORS = " \t,;:\u2013\u2014"


def field_names(marker):
    """(date, approver, digest) field names derived from the marker field."""
    return marker, f"{marker}{SUFFIX_BY}", f"{marker}{SUFFIX_SHA}"


def bound_files(base, patterns):
    """Files under base matched by any of the glob patterns, sorted and without repeats."""
    base = Path(base)
    found = {p for pattern in patterns for p in base.glob(pattern) if p.is_file()}
    return sorted(found, key=lambda p: p.relative_to(base).as_posix())


def tidied(line):
    """Line left after cutting: separator runs, spaces, empty parentheses collapsed, edges trimmed.

    Empty when only whitespace and separators are left. A final full stop stays, so a sentence
    keeps its version whether a link stood before the stop or not.
    """
    line = SEPARATOR_RUN_RE.sub(r"\1", line)
    line = SEPARATOR_BEFORE_CLOSE_RE.sub(STRIPPED, line)
    line = EMPTY_PARENS_RE.sub(STRIPPED, line)
    line = SPACE_BEFORE_SEPARATOR_RE.sub(STRIPPED, line)
    line = WHITESPACE_RUN_RE.sub(SINGLE_SPACE, line).lstrip(LEADING_SEPARATORS)
    return line.rstrip(TRAILING_SEPARATORS) if line.strip(LEADING_SEPARATORS) else STRIPPED


def cut(line, strip):
    """Line with every strip match removed and tidied, indent kept; unchanged without a match."""
    indent = line[:len(line) - len(line.lstrip())]
    rest, count = line, 0
    for pattern in strip:
        rest, found = pattern.subn(STRIPPED, rest)
        count += found
    if not count:
        return line
    rest = tidied(rest)
    return indent + rest if rest else STRIPPED


def normalized(content, ignore, strip=None):
    """Content without blank lines, without lines matched by ignore, with strip matches cut.

    Ignore sees the line as written. A line strip changed is tidied and dropped when nothing
    but whitespace and separators is left of it.
    """
    dropped = [re.compile(pattern) for pattern in ignore or ()]
    cutting = [re.compile(pattern) for pattern in strip or ()]
    text = content.decode(ENCODING, errors=DECODE_ERRORS)
    kept = []
    for line in text.splitlines():
        if not line.strip() or any(pattern.search(line) for pattern in dropped):
            continue
        line = cut(line, cutting)
        if line:
            kept.append(line)
    return NEWLINE.join(kept).encode(ENCODING, errors=DECODE_ERRORS)


def digest(base, patterns, ignore=None, strip=None):
    """sha256 over the relative path and content of each bound file, normalized by ignore, strip."""
    base = Path(base)
    sha = hashlib.sha256()
    for path in bound_files(base, patterns):
        content = path.read_bytes()
        sha.update(path.relative_to(base).as_posix().encode(ENCODING))
        sha.update(DIGEST_SEPARATOR)
        sha.update(normalized(content, ignore, strip) if ignore or strip else content)
        sha.update(DIGEST_SEPARATOR)
    return sha.hexdigest()


def accepted_rules(ignore=None, strip=None):
    """(ignore, strip) an approval digest may be taken with: current rules, ignore only, raw.

    Approvals recorded before strip carry the ignore-only digest, those before ignore the raw one.
    Transitional — drop a variant once no approval in the store carries it.
    """
    rules = [(ignore, strip)]
    if strip:
        rules.append((ignore, None))
    if ignore or strip:
        rules.append((None, None))
    return rules


def digest_matches(base, patterns, ignore, sha, strip=None):
    """Whether sha is the digest of the bound files now under any accepted rules."""
    return any(digest(base, patterns, i, s) == sha for i, s in accepted_rules(ignore, strip))


def mark_path(root):
    """Mark file in the git common directory of the store, shared by its worktrees; None off git."""
    out = run_git(root, "rev-parse", "--git-common-dir")
    if not out.ok:
        return None
    return (Path(root) / out.out).resolve() / MARK_FILE


def now():
    """Current local time with its offset."""
    return dt.datetime.now().astimezone()


def write_mark(root, keys, at=None):
    """Leave the approval mark with its time and the keys named; return its path or None."""
    path = mark_path(root)
    if path is None:
        return None
    data = {MARK_AT: (at or now()).isoformat(), MARK_KEYS: sorted(keys)}
    path.write_text(json.dumps(data), encoding=ENCODING)
    return path


def read_mark(root):
    """The approval mark as a mapping, or None when absent or unreadable."""
    path = mark_path(root)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_mark(root):
    """Remove the approval mark: one mark approves once."""
    path = mark_path(root)
    if path is not None:
        path.unlink(missing_ok=True)


def mark_time(mark):
    """Time of the mark, or None when it is not an ISO time with an offset."""
    try:
        at = dt.datetime.fromisoformat(str(mark.get(MARK_AT)))
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def is_fresh(mark, window_minutes, at=None):
    """Whether the mark was left within the window before the given time."""
    left = mark_time(mark) if mark else None
    if left is None:
        return False
    age = ((at or now()) - left).total_seconds()
    return 0 <= age <= window_minutes * SECONDS_PER_MINUTE


def mark_keys(mark):
    """Keys named in the mark as written."""
    keys = mark.get(MARK_KEYS) if mark else None
    return {str(k) for k in keys} if isinstance(keys, list) else set()


def names_any(named, keys):
    """Whether any of the named keys is one of the keys, ignoring letter case."""
    return bool({k.casefold() for k in named} & {k.casefold() for k in keys})


def scalar(value):
    """YAML text of a value: plain when safe, a quoted string otherwise."""
    text = str(value)
    if PLAIN_VALUE_RE.match(text) and not text.isdigit():
        return text
    return json.dumps(text, ensure_ascii=False)


def set_fields(path, values):
    """Replace or append top-level fields line by line, keeping every other line of the file."""
    path = Path(path)
    lines = path.read_text(encoding=ENCODING).splitlines(keepends=True) if path.is_file() else []
    for name, value in values.items():
        line = f"{name}: {scalar(value)}{NEWLINE}"
        pattern = re.compile(FIELD_LINE_RE.format(field=re.escape(name)))
        index = next((i for i, text in enumerate(lines) if pattern.match(text)), None)
        if index is None:
            if lines and not lines[-1].endswith(NEWLINE):
                lines[-1] += NEWLINE
            lines.append(line)
        else:
            lines[index] = line
    path.write_text("".join(lines), encoding=ENCODING)
