"""Migrations of a store between engine versions, applied by svod update.

A migration belongs to the version that needs it and changes the store, for example renames a
key of svod.yaml or a file. svod update applies every migration whose version lies after the
old version and up to the new one, oldest first, and prints what each one changed.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .keys import MIGRATE_RENAMED_FILE, MIGRATE_RENAMED_KEY
from .paths import CONFIG_FILE
from .versions import in_range, parse

ENCODING = "utf-8"
KEY_LINE_RE = r"^{key}(\s*:)"
FACT_OLD = "old"
FACT_NEW = "new"
FACT_FILE = "file"


@dataclass(frozen=True)
class Change:
    """One change a migration made: a locale key and its facts."""

    key: str
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Migration:
    """A change of the store needed by a version: apply(root) returns the changes it made."""

    version: str
    apply: Callable[[Path], list]


def rename_config_key(root, old, new):
    """Rename a top-level key of svod.yaml in place, keeping every other line as written."""
    path = Path(root) / CONFIG_FILE
    text = path.read_text(encoding=ENCODING)
    renamed, count = re.subn(KEY_LINE_RE.format(key=re.escape(old)), rf"{new}\1", text,
                             flags=re.MULTILINE)
    if not count:
        return []
    path.write_text(renamed, encoding=ENCODING)
    return [Change(MIGRATE_RENAMED_KEY, {FACT_OLD: old, FACT_NEW: new, FACT_FILE: CONFIG_FILE})]


def rename_file(root, old, new):
    """Rename a file or directory relative to the store root when it exists and new does not."""
    source, target = Path(root) / old, Path(root) / new
    if not source.exists() or target.exists():
        return []
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return [Change(MIGRATE_RENAMED_FILE, {FACT_OLD: old, FACT_NEW: new})]


MIGRATIONS = ()


def pending(old, new, registry=None):
    """Migrations with a version after old and up to new, oldest first; registry by default."""
    found = [m for m in (MIGRATIONS if registry is None else registry)
             if in_range(m.version, old, new)]
    return sorted(found, key=lambda m: parse(m.version))


def apply(root, old, new, registry=None):
    """Apply the pending migrations to the store; return (version, changes) for each one."""
    return [(m.version, list(m.apply(Path(root)))) for m in pending(old, new, registry)]
