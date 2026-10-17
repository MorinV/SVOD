"""Store configuration: svod.yaml at the store root."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import LoadError
from .paths import CONFIG_FILE
from .yamlio import ENCODING, dump_yaml, read_yaml

FIELD_LOCALE = "locale"
FIELD_PROFILE = "profile"
FIELD_DEFAULT_BRANCH = "default_branch"
FIELD_WORKSPACES = "workspaces"
FIELD_ACTIVE_ORDER = "active_order"
FIELD_RENDER_EXCLUDE = "render_exclude"
FIELD_BINDINGS = "bindings"
FIELD_LOCAL_CONFIG = "local_config"
FIELD_APPROVAL = "approval"
FIELD_PROFILE_CONFIG = "profile_config"
FIELD_WORKSPACE_GATE = "workspace_gate"
FIELD_MAIN_READ_ONLY = "main_checkout_read_only"
FIELD_UPDATE_CHECK = "update_check"
FIELD_SERVICES = "services"
APPROVAL_PHRASES = "phrases"
APPROVAL_WINDOW = "window_minutes"
APPROVAL_FIELDS = frozenset({APPROVAL_PHRASES, APPROVAL_WINDOW})
AGENT_CONTEXT = "agent_context"
AGENT_CONTEXT_FIELDS = frozenset({"session_summary", "prompt_positions", "approval_notice",
                                  "knowledge"})
FIELD_KNOWLEDGE = "knowledge"
KNOWLEDGE_DIR = "dir"
KNOWLEDGE_LIMIT = "limit_lines"
KNOWLEDGE_FIELDS = frozenset({KNOWLEDGE_DIR, KNOWLEDGE_LIMIT})
DEFAULT_KNOWLEDGE_DIR = "knowledge"
DEFAULT_KNOWLEDGE_LIMIT = 20
DEFAULT_WINDOW_MINUTES = 10
REQUIRED_FIELDS = (FIELD_LOCALE, FIELD_PROFILE)
STRING_FIELDS = (FIELD_LOCALE, FIELD_PROFILE, FIELD_DEFAULT_BRANCH, FIELD_WORKSPACES,
                 FIELD_BINDINGS, FIELD_LOCAL_CONFIG, FIELD_WORKSPACE_GATE)
LIST_FIELDS = (FIELD_ACTIVE_ORDER, FIELD_RENDER_EXCLUDE)
BOOL_FIELDS = (FIELD_MAIN_READ_ONLY, FIELD_UPDATE_CHECK)
KNOWN_FIELDS = frozenset(STRING_FIELDS + LIST_FIELDS + BOOL_FIELDS
                         + (FIELD_APPROVAL, FIELD_PROFILE_CONFIG, FIELD_SERVICES,
                            FIELD_KNOWLEDGE))
DEFAULT_BRANCH_FALLBACK = "origin/main"
LOCAL_LOGIN = "login"
LOCAL_EMAIL = "email"
LOCAL_FIELDS = (LOCAL_LOGIN, LOCAL_EMAIL, FIELD_WORKSPACES, FIELD_LOCALE)
LOCAL_MAPPINGS = (FIELD_PROFILE_CONFIG,)


@dataclass(frozen=True)
class Config:
    """Validated store configuration with paths resolved against the root."""

    root: Path
    locale: str
    profile: Path
    default_branch: str
    workspaces: Path | None
    active_order: tuple[str, ...]
    render_exclude: tuple[str, ...] = ()
    bindings: Path | None = None
    local_path: Path | None = None
    local_found: bool = False
    login: str | None = None
    email: str | None = None
    approval_phrases: tuple[str, ...] = ()
    approval_window: int = DEFAULT_WINDOW_MINUTES
    profile_config: dict[str, Any] = field(default_factory=dict)
    workspace_gate: str | None = None
    main_checkout_read_only: bool = False
    update_check: bool = True
    services: dict[str, Path] = field(default_factory=dict)
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR
    knowledge_limit: int = DEFAULT_KNOWLEDGE_LIMIT


def string_errors(path: Path, data: dict[str, Any], keys: Iterable[str]) -> list[str]:
    """Errors for keys present in data whose value is not a non-empty string."""
    return [f"{path}: {key} must be a non-empty string" for key in keys
            if key in data and (not isinstance(data[key], str) or not data[key].strip())]


def approval_errors(path: Path, data: Any) -> list[str]:
    """Errors of the approval block: known keys, phrases as strings, a positive window."""
    if not isinstance(data, dict):
        return [f"{path}: {FIELD_APPROVAL} must be a mapping"]
    errors = [f"{path}: {FIELD_APPROVAL}: unknown key: {key}"
              for key in sorted(set(data) - APPROVAL_FIELDS)]
    phrases = data.get(APPROVAL_PHRASES, [])
    if not isinstance(phrases, list) or not all(isinstance(x, str) and x.strip() for x in phrases):
        errors.append(f"{path}: {FIELD_APPROVAL}.{APPROVAL_PHRASES} must be a list of strings")
    window = data.get(APPROVAL_WINDOW, DEFAULT_WINDOW_MINUTES)
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        errors.append(f"{path}: {FIELD_APPROVAL}.{APPROVAL_WINDOW} must be a positive integer")
    return errors


def services_errors(path: Path, root: Path, data: Any) -> list[str]:
    """Errors of the services mapping: names to relative paths of existing directories."""
    if not isinstance(data, dict):
        return [f"{path}: {FIELD_SERVICES} must be a mapping of names to directories"]
    errors = []
    for name, value in data.items():
        where = f"{path}: {FIELD_SERVICES}.{name}"
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}: {FIELD_SERVICES}: names must be non-empty strings")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"{where} must be a non-empty string")
        elif Path(value).is_absolute():
            errors.append(f"{where} must be relative to the store root: {value}")
        elif not (root / value).is_dir():
            errors.append(f"{where}: service directory not found: {(root / value).resolve()}")
    return errors


def agent_context_errors(path: Path, profile_config: Any) -> list[str]:
    """Errors of profile_config.agent_context: a mapping of known keys with boolean values."""
    if not isinstance(profile_config, dict) or AGENT_CONTEXT not in profile_config:
        return []
    where = f"{path}: {FIELD_PROFILE_CONFIG}.{AGENT_CONTEXT}"
    data = profile_config[AGENT_CONTEXT]
    if not isinstance(data, dict):
        return [f"{where} must be a mapping"]
    errors = [f"{where}: unknown key: {key}" for key in sorted(set(data) - AGENT_CONTEXT_FIELDS)]
    errors += [f"{where}.{key} must be a boolean"
               for key in sorted(set(data) & AGENT_CONTEXT_FIELDS)
               if not isinstance(data[key], bool)]
    return errors


def knowledge_errors(path: Path, data: Any) -> list[str]:
    """Errors of the knowledge block: known keys, dir a non-empty string, a positive limit."""
    where = f"{path}: {FIELD_KNOWLEDGE}"
    if not isinstance(data, dict):
        return [f"{where} must be a mapping"]
    errors = [f"{where}: unknown key: {key}" for key in sorted(set(data) - KNOWLEDGE_FIELDS)]
    errors += string_errors(path, data, (KNOWLEDGE_DIR,))
    limit = data.get(KNOWLEDGE_LIMIT, DEFAULT_KNOWLEDGE_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        errors.append(f"{where}.{KNOWLEDGE_LIMIT} must be a positive integer")
    return errors


def read_local(path: Path) -> dict[str, Any]:
    """Validated local config mapping, empty when the file is absent."""
    if not path.is_file():
        return {}
    data = read_yaml(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise LoadError([f"{path}: expected a mapping"])
    known = set(LOCAL_FIELDS) | set(LOCAL_MAPPINGS)
    errors = [f"{path}: unknown key: {key}" for key in sorted(set(data) - known)]
    errors += string_errors(path, data, LOCAL_FIELDS)
    errors += [f"{path}: {key} must be a mapping" for key in LOCAL_MAPPINGS
               if key in data and not isinstance(data[key], dict)]
    if errors:
        raise LoadError(errors)
    return data


def load_config(root: str | Path, local: bool = True) -> Config:
    """Read and validate the config file of the given store root.

    The local config named by local_config is read on top unless local is false: its
    workspaces and locale win, its login and email identify the person.
    """
    root = Path(root).resolve()
    path = root / CONFIG_FILE
    data = read_yaml(path)
    if not isinstance(data, dict):
        raise LoadError([f"{path}: expected a mapping"])
    errors = []
    for key in sorted(set(data) - KNOWN_FIELDS):
        errors.append(f"{path}: unknown key: {key}")
    for key in REQUIRED_FIELDS:
        if key not in data:
            errors.append(f"{path}: missing key: {key}")
    errors += string_errors(path, data, STRING_FIELDS)
    errors += [f"{path}: {key} must be a boolean" for key in BOOL_FIELDS
               if key in data and not isinstance(data[key], bool)]
    if FIELD_APPROVAL in data:
        errors += approval_errors(path, data[FIELD_APPROVAL])
    if not isinstance(data.get(FIELD_PROFILE_CONFIG, {}), dict):
        errors.append(f"{path}: {FIELD_PROFILE_CONFIG} must be a mapping")
    errors += agent_context_errors(path, data.get(FIELD_PROFILE_CONFIG))
    if FIELD_SERVICES in data:
        errors += services_errors(path, root, data[FIELD_SERVICES])
    errors += knowledge_errors(path, data[FIELD_KNOWLEDGE]) if FIELD_KNOWLEDGE in data else []
    for key in LIST_FIELDS:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            errors.append(f"{path}: {key} must be a list of strings")
    if errors:
        raise LoadError(errors)
    profile = root / data[FIELD_PROFILE]
    if not profile.is_dir():
        raise LoadError([f"{path}: profile directory not found: {profile}"])
    local_path = root / data[FIELD_LOCAL_CONFIG] if data.get(FIELD_LOCAL_CONFIG) else None
    own: dict[str, Any] = read_local(local_path) if local and local_path is not None else {}
    workspaces = own.get(FIELD_WORKSPACES, data.get(FIELD_WORKSPACES))
    approval = data.get(FIELD_APPROVAL) or {}
    store_locale: str = data[FIELD_LOCALE]
    knowledge = data.get(FIELD_KNOWLEDGE) or {}
    return Config(
        root=root,
        locale=own.get(FIELD_LOCALE, store_locale),
        profile=profile.resolve(),
        default_branch=data.get(FIELD_DEFAULT_BRANCH, DEFAULT_BRANCH_FALLBACK),
        workspaces=(root / workspaces).resolve() if workspaces else None,
        active_order=tuple(data.get(FIELD_ACTIVE_ORDER, [])),
        render_exclude=tuple(data.get(FIELD_RENDER_EXCLUDE, [])),
        bindings=root / data[FIELD_BINDINGS] if data.get(FIELD_BINDINGS) else None,
        local_path=local_path,
        local_found=local_path is not None and local_path.is_file(),
        login=own.get(LOCAL_LOGIN),
        email=own.get(LOCAL_EMAIL),
        approval_phrases=tuple(approval.get(APPROVAL_PHRASES, [])),
        approval_window=approval.get(APPROVAL_WINDOW, DEFAULT_WINDOW_MINUTES),
        profile_config=data.get(FIELD_PROFILE_CONFIG) or {},
        workspace_gate=data.get(FIELD_WORKSPACE_GATE),
        main_checkout_read_only=data.get(FIELD_MAIN_READ_ONLY, False),
        update_check=data.get(FIELD_UPDATE_CHECK, True),
        services={name: (root / value).resolve()
                  for name, value in (data.get(FIELD_SERVICES) or {}).items()},
        knowledge_dir=knowledge.get(KNOWLEDGE_DIR, DEFAULT_KNOWLEDGE_DIR),
        knowledge_limit=knowledge.get(KNOWLEDGE_LIMIT, DEFAULT_KNOWLEDGE_LIMIT),
    )


def write_local(path: str | Path, values: dict[str, Any]) -> None:
    """Write the local config with the non-empty values, in the given order."""
    data = {key: value for key, value in values.items() if value}
    Path(path).write_text(dump_yaml(data), encoding=ENCODING)
