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


class LocalWorkflowError(SvodError, ValueError):
    """The compact local workflow refused its input, evidence or source state.

    Also a ValueError: the local workflow and its callers report a refused input as one.
    """


class PolicyError(SvodError, ValueError):
    """A subject's pipeline or approval is missing or ambiguous, or a prerequisite pends.

    Also a ValueError: the local workflow and its callers report a refused input as one.
    """
