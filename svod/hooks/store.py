"""The store of a hook event: where it is, how it loads, and the line when it does not."""
from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config, load_config
from ..context import Context
from ..errors import LoadError
from ..keys import HOOK_ENGINE_BROKEN
from ..loader import Runtime, load_runtime
from ..locale import error_locale
from ..paths import CONFIG_FILE, find_root
from .protocol import FIELD_CWD, PROJECT_ENV, Event

if TYPE_CHECKING:
    from ..cache import RunCache
    from ..gates import KeyGate
    from ..pipeline import Pipeline

ENGINE_BROKEN_FALLBACK = "The pipeline engine failed to load: {reason}."
MORE_ERRORS = " (+{count})"
PROFILE_CONFIG = "profile_config"
AGENT_CONTEXT = "agent_context"


def first_error(errors: list[str]) -> str:
    """First load error and how many more there are."""
    if not errors:
        return ""
    rest = len(errors) - 1
    return errors[0] + (MORE_ERRORS.format(count=rest) if rest else "")


def one_line(reason: object) -> str:
    """The reason with its whitespace collapsed to single spaces."""
    return " ".join(str(reason).split())


def broken_text(root: Path, reason: object) -> str:
    """One line about the engine that did not load, in the locale of the store when readable."""
    reason = one_line(reason)
    try:
        return error_locale(root).text(HOOK_ENGINE_BROKEN, reason=reason)
    except Exception:
        return ENGINE_BROKEN_FALLBACK.format(reason=reason)


def store_root(event: Event, fallback: str | Path | None = None) -> Path | None:
    """Store of the session: the one holding the project directory or the event cwd, else fallback.

    None when neither lies in a store.
    """
    for candidate in (os.environ.get(PROJECT_ENV), event.get(FIELD_CWD)):
        if isinstance(candidate, str) and candidate:
            root = find_root(Path(candidate).expanduser())
            if root is not None:
                return root
    if fallback:
        root = Path(fallback).expanduser().resolve()
        return root if (root / CONFIG_FILE).is_file() else None
    return None


def load(root: Path) -> tuple[Runtime | None, str | None]:
    """(runtime, None) of the store, or (None, reason) when it does not load."""
    try:
        return load_runtime(root), None
    except LoadError as exc:
        return None, first_error(exc.errors)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def config_of(root: Path | None) -> Config | None:
    """svod.yaml of the store without the local config, or None without a store or when broken.

    Cheaper than load: no profile, gate or git call, so a hook may ask it of every command.
    """
    if root is None:
        return None
    try:
        return load_config(root, local=False)
    except Exception:
        return None


def context_of(runtime: Runtime, cache: RunCache | None = None) -> Context:
    """Evaluation context of a loaded store; cache, when given, is the memory of the event."""
    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    if cache is not None:
        ctx.cache = cache
    return ctx


def agent_context_setting(runtime: Runtime, name: str) -> bool:
    """Whether an optional agent-context output is enabled (legacy defaults on)."""
    profile = getattr(runtime.config, PROFILE_CONFIG, {})
    settings = profile.get(AGENT_CONTEXT, {}) if isinstance(profile, dict) else {}
    return not (isinstance(settings, dict) and settings.get(name) is False)


def key_gates(pipelines: Iterable[Pipeline]) -> list[KeyGate]:
    """Key gates of the pipelines that declare one."""
    return [p.subject.key_impl for p in pipelines if p.subject.key_impl is not None]


def query_keys(pipelines: Iterable[Pipeline], text: str) -> list[str]:
    """Keys the key gates recognise in a query, each gate asked until nothing is left, in order."""
    found: list[str] = []
    for gate in key_gates(pipelines):
        rest = text
        key = gate.match(rest)
        while key:
            found.append(key)
            cut = cut_key(rest, key)
            if cut == rest:
                break
            rest = cut
            key = gate.match(rest)
    return list(dict.fromkeys(found))


def cut_key(text: str, key: str) -> str:
    """The text with every occurrence of the key, in any letter case, replaced by a gap."""
    return re.sub(re.escape(key), " ", text, flags=re.IGNORECASE)
