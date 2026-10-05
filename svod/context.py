"""Evaluation context shared by gates and providers."""
import datetime as dt
from dataclasses import dataclass, field

from .cache import RunCache


@dataclass
class Context:
    """Store configuration, locale, reference date, role bindings, pipelines by name and the
    memory of the run, shared by the contexts rooted in other checkouts."""

    config: object
    locale: object = None
    today: dt.date = field(default_factory=dt.date.today)
    bindings: object = None
    pipelines: dict = field(default_factory=dict)
    cache: RunCache = field(default_factory=RunCache)

    @property
    def root(self):
        """Store root."""
        return self.config.root
