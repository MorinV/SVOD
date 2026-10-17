"""Plan approval: digest of the bound files, the mark a person leaves, the approval fields.

This module is the one place that knows the approval fields: <marker> holds the date,
<marker>_by the approver, <marker>_sha the digest of the bound files. Read them with
read_fields and write them with write_fields.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .git import GitResult, common_dir_file
from .yamlio import ENCODING, read_yaml

Run = Callable[..., GitResult]
Rules = Iterable[str] | None

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
SEPARATOR_RUN_RE = re.compile(r"([,;])(?:\s*[,;])+")
SPACE_BEFORE_SEPARATOR_RE = re.compile(r"\s+(?=[,;.:])")
SEPARATOR_BEFORE_CLOSE_RE = re.compile(r"[\s,;]+(?=\))")
EMPTY_PARENS_RE = re.compile(r"\s*\(\s*\)")
WHITESPACE_RUN_RE = re.compile(r"\s+")
LEADING_SEPARATORS = " \t,;.:\u2013\u2014"
TRAILING_SEPARATORS = " \t,;:\u2013\u2014"
NO_TEXT = ""


def field_names(marker: str) -> tuple[str, str, str]:
    """(date, approver, digest) field names derived from the marker field."""
    return marker, f"{marker}{SUFFIX_BY}", f"{marker}{SUFFIX_SHA}"


def text_of(value: Any) -> str:
    """Stripped text of a field value; empty for a missing one."""
    return NO_TEXT if value is None else str(value).strip()


def read_fields(path: str | Path, marker: str) -> tuple[str, ...]:
    """(date, approver, digest) recorded under the marker in a YAML file, as stripped text.

    Each is empty when the file is absent, is not a mapping or lacks the field, as in an
    approval recorded before the approver and the digest were. LoadError when the file is
    not valid YAML.
    """
    path = Path(path)
    if not path.is_file():
        return tuple(NO_TEXT for _ in field_names(marker))
    data = read_yaml(path)
    data = data if isinstance(data, dict) else {}
    return tuple(text_of(data.get(name)) for name in field_names(marker))


def write_fields(path: str | Path, marker: str, date: str, by: str,
                 sha: str | None = None) -> None:
    """Record the approval under the marker: date, approver and, when given, the digest.

    Other lines of the file are kept as written; the fields are replaced in place or
    appended. Without a digest (an approval with no bound files) no digest field is written.
    """
    date_field, by_field, sha_field = field_names(marker)
    values = {date_field: date, by_field: by}
    if sha:
        values[sha_field] = sha
    set_fields(path, values)


def bound_files(base: str | Path, patterns: Iterable[str]) -> list[Path]:
    """Files under base matched by any of the glob patterns, sorted and without repeats."""
    base = Path(base)
    found = {p for pattern in patterns for p in base.glob(pattern) if p.is_file()}
    return sorted(found, key=lambda p: p.relative_to(base).as_posix())


def tidied(line: str) -> str:
    """Line left after cutting: separator runs, spaces, empty parentheses collapsed, edges trimmed.

    Empty when only whitespace and separators are left. A final full stop stays, so a sentence
    keeps its version whether a link stood before the stop or not.
    """
    line = SEPARATOR_RUN_RE.sub(r"\1", line)
    line = SEPARATOR_BEFORE_CLOSE_RE.sub(STRIPPED, line)
    line = EMPTY_PARENS_RE.sub(STRIPPED, line)
    line = SPACE_BEFORE_SEPARATOR_RE.sub(STRIPPED, line)
    line = WHITESPACE_RUN_RE.sub(" ", line).lstrip(LEADING_SEPARATORS)
    return line.rstrip(TRAILING_SEPARATORS) if line.strip(LEADING_SEPARATORS) else STRIPPED


def cut(line: str, strip: Iterable[re.Pattern[str]]) -> str:
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


def normalized(content: bytes, ignore: Rules, strip: Rules = None) -> bytes:
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


def digest(base: str | Path, patterns: Iterable[str], ignore: Rules = None,
           strip: Rules = None) -> str:
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


def accepted_rules(ignore: Rules = None, strip: Rules = None) -> list[tuple[Rules, Rules]]:
    """(ignore, strip) an approval digest may be taken with: current rules, ignore only, raw.

    Approvals recorded before strip carry the ignore-only digest, those before ignore the raw one.
    Transitional — drop a variant once no approval in the store carries it.
    """
    rules: list[tuple[Rules, Rules]] = [(ignore, strip)]
    if strip:
        rules.append((ignore, None))
    if ignore or strip:
        rules.append((None, None))
    return rules


def digest_matches(base: str | Path, patterns: Iterable[str], ignore: Rules, sha: str,
                   strip: Rules = None) -> bool:
    """Whether sha is the digest of the bound files now under any accepted rules."""
    return any(digest(base, patterns, i, s) == sha for i, s in accepted_rules(ignore, strip))


def mark_path(root: Path, run: Run | None = None) -> Path | None:
    """Mark file in the git common directory of the store, shared by its worktrees; None off git.

    run replaces run_git: a hook passes the git of its run cache, so the call is not repeated.
    """
    return common_dir_file(root, MARK_FILE, run)


def now() -> dt.datetime:
    """Current local time with its offset."""
    return dt.datetime.now().astimezone()


def write_mark(root: Path, keys: Iterable[str], at: dt.datetime | None = None,
               run: Run | None = None) -> Path | None:
    """Leave the approval mark with its time and the keys named; return its path or None.

    run replaces run_git.
    """
    path = mark_path(root, run)
    if path is None:
        return None
    data = {MARK_AT: (at or now()).isoformat(), MARK_KEYS: sorted(keys)}
    path.write_text(json.dumps(data), encoding=ENCODING)
    return path


def read_mark(root: Path) -> dict[str, Any] | None:
    """The approval mark as a mapping, or None when absent or unreadable."""
    path = mark_path(root)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding=ENCODING))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_mark(root: Path) -> None:
    """Remove an exhausted approval mark."""
    path = mark_path(root)
    if path is not None:
        path.unlink(missing_ok=True)


def consume_mark(root: Path, keys: Iterable[str], mark: dict[str, Any] | None = None) -> None:
    """Consume the approved subject's keys, preserving other keys and the original time.

    An unnamed mark remains single-use. Do not overwrite a newer prompt's mark if it
    arrived while the approval was being written. CLI approvals are sequential.
    """
    current = read_mark(root)
    if mark is not None and current != mark:
        return
    named = mark_keys(current)
    used = {key.casefold() for key in keys}
    remaining = {key for key in named if key.casefold() not in used}
    if not remaining:
        clear_mark(root)
        return
    path = mark_path(root)
    if path is not None:
        # Keys remain only from a current mark, so current is a mapping here.
        data = {**current, MARK_KEYS: sorted(remaining)}  # type: ignore[dict-item]
        path.write_text(json.dumps(data), encoding=ENCODING)


def mark_time(mark: dict[str, Any]) -> dt.datetime | None:
    """Time of the mark, or None when it is not an ISO time with an offset."""
    try:
        at = dt.datetime.fromisoformat(str(mark.get(MARK_AT)))
    except ValueError:
        return None
    return at if at.tzinfo is not None else None


def is_fresh(mark: dict[str, Any] | None, window_minutes: int,
             at: dt.datetime | None = None) -> bool:
    """Whether the mark was left within the window before the given time."""
    left = mark_time(mark) if mark else None
    if left is None:
        return False
    age = ((at or now()) - left).total_seconds()
    return 0 <= age <= window_minutes * SECONDS_PER_MINUTE


def mark_keys(mark: dict[str, Any] | None) -> set[str]:
    """Keys named in the mark as written."""
    keys = mark.get(MARK_KEYS) if mark else None
    return {str(k) for k in keys} if isinstance(keys, list) else set()


def names_any(named: Iterable[str], keys: Iterable[str]) -> bool:
    """Whether any of the named keys is one of the keys, ignoring letter case."""
    return bool({k.casefold() for k in named} & {k.casefold() for k in keys})


def scalar(value: Any) -> str:
    """YAML text of a value: plain when safe, a quoted string otherwise."""
    text = str(value)
    if PLAIN_VALUE_RE.match(text) and not text.isdigit():
        return text
    return json.dumps(text, ensure_ascii=False)


def set_fields(path: str | Path, values: dict[str, Any]) -> None:
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
