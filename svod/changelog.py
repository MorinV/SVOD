"""CHANGELOG.md of the engine in the Keep a Changelog format: releases between two versions."""
import re
from dataclasses import dataclass

from .versions import in_range

CHANGELOG_FILE = "CHANGELOG.md"
RELEASE_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]")
SECTION_PREFIX = "## "
SUBSECTION_PREFIX = "### "
MIGRATION_HEADING = "Migration"
NO_MIGRATION = "none"
NOTE_TRIM = " \t-*.;"


@dataclass(frozen=True)
class Release:
    """One release of the changelog: its version and lines, the heading included."""

    version: str
    lines: tuple

    def migration(self):
        """Lines of the Migration subsection, without blanks; empty when it says none."""
        notes, inside = [], False
        for line in self.lines[1:]:
            if line.startswith(SUBSECTION_PREFIX):
                inside = line[len(SUBSECTION_PREFIX):].strip() == MIGRATION_HEADING
                continue
            if inside and line.strip():
                notes.append(line.rstrip())
        if all(n.strip(NOTE_TRIM).casefold() == NO_MIGRATION for n in notes):
            return []
        return notes


def releases(text):
    """Every release of the changelog in the order written; Unreleased is left out."""
    found, current = [], None
    for line in text.splitlines():
        if line.startswith(SECTION_PREFIX):
            if current is not None:
                found.append(Release(current[0], tuple(current[1])))
            matched = RELEASE_RE.match(line)
            current = (matched.group(1), [line]) if matched else None
        elif current is not None:
            current[1].append(line)
    if current is not None:
        found.append(Release(current[0], tuple(current[1])))
    return [Release(r.version, tuple(trimmed(r.lines))) for r in found]


def trimmed(lines):
    """Lines without trailing blanks."""
    lines = list(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def between(text, old, new):
    """Releases after old and up to new, in the order written; old None means every one."""
    return [r for r in releases(text) if in_range(r.version, old, new)]
