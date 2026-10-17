"""Evaluation context shared by gates and providers."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cache import RunCache

if TYPE_CHECKING:
    from .bindings import Bindings
    from .config import Config
    from .pipeline import Pipeline


@dataclass
class Context:
    """Store configuration, locale, reference date, role bindings, pipelines by name and the
    memory of the run, shared by the contexts rooted in other checkouts."""

    config: Config
    # A Locale; None only in contexts that render no text.
    locale: Any = None
    today: dt.date = field(default_factory=dt.date.today)
    bindings: Bindings | None = None
    pipelines: dict[str, Pipeline] = field(default_factory=dict)
    cache: RunCache = field(default_factory=RunCache)

    @property
    def root(self) -> Path:
        """Store root."""
        return self.config.root
