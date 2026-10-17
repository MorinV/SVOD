"""Locale: key to template, core strings merged with profile strings."""
import os
import string
from pathlib import Path

from .errors import LoadError, LocaleError
from .keys import CORE_KEYS
from .yamlio import read_yaml

LOCALE_DIR = "locale"
LOCALE_SUFFIX = ".yaml"
KEY_SEPARATOR = "."
CORE_LOCALE_DIR = Path(__file__).resolve().parent / LOCALE_DIR
LOCALE_ENV = "SVOD_LOCALE"
FALLBACK_LOCALE = "en"


class Locale:
    """Flat mapping of keys to format templates."""

    def __init__(self, strings):
        """Wrap an already validated key to template mapping."""
        self._strings = dict(strings)

    def has(self, key):
        """Whether the key is defined."""
        return key in self._strings

    def missing(self, keys):
        """Keys from the iterable that are not defined, sorted."""
        return sorted({key for key in keys if key not in self._strings})

    def text_template(self, key):
        """Raw template of the key, placeholders unfilled."""
        try:
            return self._strings[key]
        except KeyError:
            raise LocaleError(f"missing locale key: {key}") from None

    def text(self, key, **facts):
        """Render the template of the key with facts substituted."""
        template = self.text_template(key)
        try:
            return template.format_map(facts)
        except (KeyError, IndexError, AttributeError) as exc:
            raise LocaleError(f"locale key {key}: placeholder not provided: {exc}") from None


def flatten(data, path, prefix=""):
    """Nested mapping to dotted keys; raise LoadError on non-string leaves."""
    if not isinstance(data, dict):
        raise LoadError([f"{path}: expected a mapping"])
    flat, errors = {}, []
    for key, value in data.items():
        full = f"{prefix}{KEY_SEPARATOR}{key}" if prefix else str(key)
        if isinstance(value, dict):
            try:
                flat.update(flatten(value, path, full))
            except LoadError as exc:
                errors.extend(exc.errors)
        elif isinstance(value, str):
            try:
                list(string.Formatter().parse(value))
                flat[full] = value
            except ValueError as exc:
                errors.append(f"{path}: {full}: bad template: {exc}")
        else:
            errors.append(f"{path}: {full}: value must be a string")
    if errors:
        raise LoadError(errors)
    return flat


def read_locale_file(path):
    """Flattened strings of one locale file."""
    return flatten(read_yaml(path) or {}, path)


def core_locale_path(name):
    """Path of the core locale file for the locale name."""
    return CORE_LOCALE_DIR / f"{name}{LOCALE_SUFFIX}"


def load_core_locale(name):
    """Core strings only, checked for every core key."""
    path = core_locale_path(name)
    strings = read_locale_file(path)
    missing = sorted(set(CORE_KEYS) - set(strings))
    if missing:
        raise LoadError([f"{path}: missing key: {key}" for key in missing])
    return Locale(strings)


def load_locale(name, profile_dir, required=()):
    """Core strings with profile strings on top; every required key must exist."""
    core = load_core_locale(name)
    profile_path = Path(profile_dir) / LOCALE_DIR / f"{name}{LOCALE_SUFFIX}"
    merged = dict(core._strings)
    merged.update(read_locale_file(profile_path))
    locale = Locale(merged)
    missing = locale.missing(required)
    if missing:
        raise LoadError([f"locale {name}: missing key: {key}" for key in missing])
    return locale


def error_locale(root):
    """Core locale for reporting errors: the configured one when readable."""
    from .config import load_config
    try:
        return load_core_locale(load_config(root, local=False).locale)
    except LoadError:
        return bootstrap_locale()


def bootstrap_locale():
    """Core locale chosen by the environment, used before any config is found."""
    return load_core_locale(os.environ.get(LOCALE_ENV) or FALLBACK_LOCALE)
