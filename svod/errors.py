"""Error types raised by svod."""


class SvodError(Exception):
    """Base class for all svod errors."""


class LoadError(SvodError):
    """Configuration, registries, pipelines or locale failed to load."""

    def __init__(self, errors):
        """Keep every collected error message."""
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


class ParamError(SvodError):
    """Gate or provider params do not match the declared schema."""


class LocaleError(SvodError):
    """A locale key is missing or its placeholders are not satisfied."""
