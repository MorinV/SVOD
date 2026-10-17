"""Declared params for gates and providers."""
from .errors import ParamError


class Configurable:
    """Object configured by a params mapping validated against PARAMS and REQUIRED."""

    name = ""
    PARAMS: frozenset[str] = frozenset()
    REQUIRED: frozenset[str] = frozenset()

    def __init__(self, params=None):
        """Store params after checking unknown and missing names."""
        if params is not None and not isinstance(params, dict):
            raise ParamError(f"{self.name}: params must be a mapping")
        params = dict(params or {})
        unknown = sorted(set(params) - set(self.PARAMS))
        if unknown:
            raise ParamError(f"{self.name}: unknown params: {', '.join(unknown)}")
        missing = sorted(set(self.REQUIRED) - set(params))
        if missing:
            raise ParamError(f"{self.name}: missing params: {', '.join(missing)}")
        self.params = params
        self.check()

    def check(self):
        """Validate param values; subclasses raise ParamError."""

    def require_type(self, key, kind, label):
        """Raise ParamError unless the param, when given, is of the expected type."""
        value = self.params.get(key)
        if value is not None and not isinstance(value, kind):
            raise ParamError(f"{self.name}: param {key} must be {label}")
