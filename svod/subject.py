"""Subject: one instance a pipeline is evaluated for."""
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

ATTR_CONTAINER = "container"
ATTR_FRONTMATTER = "frontmatter"


@dataclass
class Subject:
    """Instance found by a provider; author_of reads the author on first use of author."""

    id: str
    path: Path | None
    exists: bool = True
    archived: bool = False
    keys: frozenset = frozenset()
    attrs: dict = field(default_factory=dict)
    checkout: Path | None = None
    author_of: object = field(default=None, repr=False, compare=False)

    @cached_property
    def author(self):
        """(email, name) of the last commit touching the subject, or None without data."""
        return self.author_of() if self.author_of is not None else None
